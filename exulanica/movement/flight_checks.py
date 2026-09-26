"""An independent check of a served flight: what a renderer is handed, step by step.

The step's guard refuses a flying move whose closed box meets a solid cell. This module asks other,
exact questions of the output instead, over a run of windows as a page reads them, the move from
one window's last step to the next window's first included:

- every flying position lies in the volume and the kind's band; every landing, take-off and perch
  lies on its perch's column, a perching flyer on its perch's point, and no perch holds two flyers;
- no move is longer than the kind's top speed allows in a step, the move into an episode's first
  step included, where every flyer must be perching at home;
- no point of any move lies in a solid cell, except a cell of the perch's own object for a flyer
  moving straight up or down that perch's column, landing, perching or taking off; those cells are
  derived here from that object's parts, never read from the input's columns;
- no move brings a flyer's body, a box as wide as its kind's span, into any object's part, except
  its own perch's object while it moves along that perch's column;
- at every episode's last step every flyer is perching at home, and the window names exactly the
  flyers that are not.

It reads windows as :func:`exulanica.movement.flight.flight_window` returns them and the input they
were made from, and nothing of the step's own bookkeeping, so a defect in the guard, in the columns
or in the server's own report shows up here as a violation rather than agreeing with itself.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from exulanica.movement.air import Cell, Solid, _solid_bounds, segment_meets_cell
from exulanica.movement.fixed import Vector, ceil_div, length, sub
from exulanica.movement.flight import FlightInput

__all__ = ["FlightCheck", "check_window", "check_windows"]


@dataclass(slots=True)
class FlightCheck:
    """What a check found: every violation named, and counts of what was looked at."""

    violations: list[dict[str, Any]] = field(default_factory=list)
    segments: int = 0
    guard_holds: int = 0
    #: Flyers not perching at home at an episode's last step, as this check finds them.
    late_home: int = 0
    #: Episode ends looked at, one a flyer.
    episode_ends: int = 0
    states: Counter[str] = field(default_factory=Counter)

    def record(self, flyer_id: str, step: int, rule: str, detail: str) -> None:
        self.violations.append({"flyer_id": flyer_id, "step": step, "rule": rule, "detail": detail})

    def add(self, other: FlightCheck) -> None:
        self.violations.extend(other.violations)
        self.segments += other.segments
        self.guard_holds += other.guard_holds
        self.late_home += other.late_home
        self.episode_ends += other.episode_ends
        self.states.update(other.states)


def _closed_cells(flight: FlightInput, low: Sequence[int], high: Sequence[int]) -> Iterable[Cell]:
    """Every grid cell a closed box meets, clipped to the grid."""
    volume = flight.volume
    size = volume.cell_mm
    origins = (volume.min_x_mm, volume.ground_mm, volume.min_z_mm)
    ranges = []
    for axis, count in enumerate(volume.shape):
        first = max(0, (low[axis] - origins[axis]) // size)
        last = min(count - 1, (high[axis] - origins[axis]) // size)
        ranges.append(range(first, last + 1))
    return ((ix, iy, iz) for ix in ranges[0] for iy in ranges[1] for iz in ranges[2])


def _segment_box(start: Sequence[int], end: Sequence[int]) -> tuple[Vector, Vector]:
    low = (min(start[0], end[0]), min(start[1], end[1]), min(start[2], end[2]))
    high = (max(start[0], end[0]), max(start[1], end[1]), max(start[2], end[2]))
    return low, high


def _segment_meets_box(
    start: Sequence[int], end: Sequence[int], low: Sequence[int], high: Sequence[int]
) -> bool:
    """Whether some point of the segment lies in the closed box ``[low, high]``, exactly."""
    first, last = Fraction(0), Fraction(1)
    for axis in range(3):
        origin, delta = start[axis], end[axis] - start[axis]
        if delta == 0:
            if not low[axis] <= origin <= high[axis]:
                return False
            continue
        enter = Fraction(low[axis] - origin, delta)
        leave = Fraction(high[axis] - origin, delta)
        first = max(first, min(enter, leave))
        last = min(last, max(enter, leave))
        if first > last:
            return False
    return first <= last


class _Solids:
    """The world's solids as this check reads them: which cells each object's parts touch, and
    which parts a body of a given half-width could meet near a cell."""

    def __init__(self, flight: FlightInput, solids: Sequence[Solid], clearance_mm: int) -> None:
        self.flight = flight
        self.solids = tuple(solids)
        self.clearance_mm = clearance_mm
        self._object_cells: dict[str, frozenset[Cell]] = {}
        self._near: dict[int, dict[Cell, list[int]]] = {}
        self._bounds = [_solid_bounds(solid) for solid in self.solids]

    def object_cells(self, object_id: str) -> frozenset[Cell]:
        """The cells an object's own parts touch, grown by the air's clearance as the grid is."""
        cells = self._object_cells.get(object_id)
        if cells is None:
            grow = self.clearance_mm
            found: set[Cell] = set()
            for solid, (low, high) in zip(self.solids, self._bounds, strict=True):
                if solid.object_id != object_id:
                    continue
                found.update(
                    _closed_cells(
                        self.flight,
                        (low[0] - grow, low[1] - grow, low[2] - grow),
                        (high[0] + grow, high[1] + grow, high[2] + grow),
                    )
                )
            cells = self._object_cells[object_id] = frozenset(found)
        return cells

    def near(self, half_width: int) -> dict[Cell, list[int]]:
        """For each cell, the parts a body ``half_width`` wide could meet from inside it."""
        index = self._near.get(half_width)
        if index is None:
            index = {}
            for number, (low, high) in enumerate(self._bounds):
                grown_low = (low[0] - half_width, low[1] - half_width, low[2] - half_width)
                grown_high = (high[0] + half_width, high[1] + half_width, high[2] + half_width)
                for cell in _closed_cells(self.flight, grown_low, grown_high):
                    index.setdefault(cell, []).append(number)
            self._near[half_width] = index
        return index

    def body_meets(
        self,
        start: Sequence[int],
        end: Sequence[int],
        half_width: int,
        spared: set[str],
    ) -> str | None:
        """The object whose part a body ``half_width`` wide meets moving from ``start`` to ``end``,
        other than the ``spared`` ones, or None."""
        index = self.near(half_width)
        low, high = _segment_box(start, end)
        seen: set[int] = set()
        for cell in _closed_cells(self.flight, low, high):
            for number in index.get(cell, ()):
                if number in seen:
                    continue
                seen.add(number)
                solid = self.solids[number]
                if solid.object_id in spared:
                    continue
                part_low, part_high = self._bounds[number]
                if _segment_meets_box(
                    start,
                    end,
                    (
                        part_low[0] - half_width,
                        part_low[1] - half_width,
                        part_low[2] - half_width,
                    ),
                    (
                        part_high[0] + half_width,
                        part_high[1] + half_width,
                        part_high[2] + half_width,
                    ),
                ):
                    return solid.object_id
        return None


def _solids_of(
    flight: FlightInput, solids: Sequence[Solid] | None, clearance_mm: int | None
) -> _Solids:
    if solids is None:
        solids = getattr(flight, "solids", None)
        if solids is None:
            raise ValueError("this input carries no solids; pass the world's solids to check it")
    if clearance_mm is None:
        clearance_mm = getattr(flight, "clearance_mm", 0)
    return _Solids(flight, solids, clearance_mm)


def _perch_under(
    columns: Mapping[str, Any], points: Mapping[str, Vector], position: Vector, state: str
) -> str | None:
    """The perch whose column holds a landing, perching or leaving flyer: which perch a flyer is
    using is not served, so it is read from where the flyer is."""
    if state == "flying":
        return None
    return next(
        (
            perch_id
            for perch_id, column in columns.items()
            if position[0] == column.approach_mm[0]
            and position[2] == column.approach_mm[2]
            and points[perch_id][1] <= position[1] <= column.approach_mm[1]
        ),
        None,
    )


def check_window(
    flight: FlightInput,
    window: Mapping[str, Any],
    *,
    before: Mapping[str, Any] | None = None,
    solids: Sequence[Solid] | None = None,
    clearance_mm: int | None = None,
    world: _Solids | None = None,
) -> FlightCheck:
    """Check every served step of every flyer in ``window`` against ``flight``.

    ``before`` is the window served just before this one: its last step and this window's first
    are checked as one move, as a page draws them. ``solids`` and ``clearance_mm`` are the world's
    parts and the air's clearance where the input does not carry them.
    """
    if world is None:
        world = _solids_of(flight, solids, clearance_mm)
    result = FlightCheck()
    states = window["states"]
    episode = window["episode_steps"]
    step_ms = window["step_ms"]
    from_step = window["from_step"]
    by_id = {flyer.flyer_id: flyer for flyer in flight.flyers}
    points = {perch.perch_id: perch.point_mm for perch in flight.perches}
    owners = {perch.perch_id: perch.object_id for perch in flight.perches}
    if before is not None and before["from_step"] + before["steps"] != from_step:
        raise ValueError("the window before does not end where this one starts")
    before_rows = {} if before is None else {row["flyer_id"]: row for row in before["flyers"]}
    #: Who is on, landing on or leaving each perch at each step, to find a perch held twice.
    holders: dict[tuple[int, str], str] = {}
    late: set[tuple[int, str]] = set()
    for row in window["flyers"]:
        flyer = by_id[row["flyer_id"]]
        kind = flight.kinds[flyer.kind]
        ground = flight.volume.ground_mm
        low_band, high_band = ground + kind.min_altitude_mm, ground + kind.max_altitude_mm
        half_width = ceil_div(kind.body_span_mm, 2)
        limit = max(kind.max_speed_mm_s, kind.takeoff_rate_mm_s, kind.landing_rate_mm_s)
        home = points[flyer.home_perch_id]
        columns = {
            perch.perch_id: perch.columns[flyer.kind]
            for perch in flight.perches
            if flyer.kind in perch.columns
        }

        previous: Vector | None = None
        previous_perch: str | None = None
        joined = before_rows.get(flyer.flyer_id)
        if joined is not None:
            last = before["steps"] - 1
            previous = tuple(joined["position_mm"][3 * last : 3 * last + 3])
            previous_perch = _perch_under(
                columns, points, previous, before["states"][joined["state"][last]]
            )
        for index in range(len(row["state"])):
            step = from_step + index
            position = tuple(row["position_mm"][3 * index : 3 * index + 3])
            state = states[row["state"][index]]
            result.states[state] += 1
            result.guard_holds += row["held"][index]
            perch_here = _perch_under(columns, points, position, state)
            if state != "flying":
                if perch_here is None:
                    result.record(
                        flyer.flyer_id, step, "off_column", f"{state} at {list(position)}"
                    )
                else:
                    other = holders.setdefault((step, perch_here), flyer.flyer_id)
                    if other != flyer.flyer_id:
                        result.record(
                            flyer.flyer_id, step, "perch_held_twice", f"{perch_here} with {other}"
                        )
                    if state == "perching" and position != points[perch_here]:
                        result.record(
                            flyer.flyer_id, step, "perched_off_point", f"at {list(position)}"
                        )
            elif not (
                flight.volume.min_x_mm <= position[0] <= flight.volume.max_x_mm
                and low_band <= position[1] <= high_band
                and flight.volume.min_z_mm <= position[2] <= flight.volume.max_z_mm
            ):
                result.record(flyer.flyer_id, step, "out_of_bounds", f"at {list(position)}")
            at_home = state == "perching" and position == home
            if step % episode == 0 and not at_home:
                result.record(
                    flyer.flyer_id, step, "genesis_not_home", f"{state} at {list(position)}"
                )
            if step % episode == episode - 1:
                result.episode_ends += 1
                if not at_home:
                    result.late_home += 1
                    late.add((step, flyer.flyer_id))
                    result.record(
                        flyer.flyer_id,
                        step,
                        "not_home_at_episode_end",
                        f"{state} at {list(position)}, {length(sub(home, position))} mm from home",
                    )
            if previous is not None:
                _check_move(
                    result,
                    flight,
                    world,
                    flyer.flyer_id,
                    step,
                    previous,
                    position,
                    moved_limit=limit * step_ms // 1000 + 1,
                    half_width=half_width,
                    # A perch's own object is spared only for a move along its column: straight
                    # up or down, as landing, perching and taking off move. A move from anywhere
                    # else onto a perch, a jump home at an episode's start among them, is not.
                    spared=(
                        {owners[p] for p in (previous_perch, perch_here) if p is not None}
                        if previous[0] == position[0] and previous[2] == position[2]
                        else set()
                    ),
                )
            previous, previous_perch = position, perch_here
    reported = {(row["step"], row["flyer_id"]) for row in window["late_home"]}
    for step, flyer_id in sorted(late ^ reported):
        result.record(
            flyer_id,
            step,
            "late_home_misreported",
            "not home, and the window does not say so"
            if (step, flyer_id) in late
            else "the window names it late, and it is home",
        )
    return result


def _check_move(
    result: FlightCheck,
    flight: FlightInput,
    world: _Solids,
    flyer_id: str,
    step: int,
    previous: Vector,
    position: Vector,
    *,
    moved_limit: int,
    half_width: int,
    spared: set[str],
) -> None:
    """One move, from the step before ``step`` to it: its length, its cells and its body."""
    result.segments += 1
    if length(sub(position, previous)) > moved_limit:
        result.record(flyer_id, step, "moved_too_far", f"{list(previous)} -> {list(position)}")
    allowed: set[Cell] = set()
    for object_id in spared:
        allowed.update(world.object_cells(object_id))
    low, high = _segment_box(previous, position)
    for cell in _closed_cells(flight, low, high):
        if (
            cell not in allowed
            and flight.occupancy.is_solid(cell)
            and segment_meets_cell(flight.volume, previous, position, cell)
        ):
            result.record(
                flyer_id,
                step,
                "entered_solid_cell",
                f"{list(previous)} -> {list(position)} meets {list(cell)}",
            )
            break
    touched = world.body_meets(previous, position, half_width, spared)
    if touched is not None:
        result.record(
            flyer_id,
            step,
            "body_meets_solid",
            f"{list(previous)} -> {list(position)} brings the body into {touched}",
        )


def check_windows(
    flight: FlightInput,
    windows: Sequence[Mapping[str, Any]],
    *,
    solids: Sequence[Solid] | None = None,
    clearance_mm: int | None = None,
) -> FlightCheck:
    """Check consecutive windows as one run: each window, and the move joining it to the last."""
    world = _solids_of(flight, solids, clearance_mm)
    total = FlightCheck()
    for index, window in enumerate(windows):
        total.add(
            check_window(flight, window, before=windows[index - 1] if index else None, world=world)
        )
    return total
