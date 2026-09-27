"""An independent check of a served flight: what a renderer is handed, against the world as drawn.

The flight keeps every flyer's point out of the solid cells of its own grid, which it builds from
its own placement of every object's parts (:mod:`exulanica.world.flight_input`,
:mod:`exulanica.movement.air`). A check that read that grid, or placed parts the same way, would
agree with any error in them. This checker derives everything it checks on its own:

- **parts**: each part's box is the extent of the triangles the renderer draws for it
  (:func:`exulanica.world.object_meshes.parts_extent`; a marker's box is its recipe's size), turned,
  scaled and placed by this module's own trigonometry, the kind's front facing the region's ``-z``
  as the renderer turns it, and rounded outward to the millimetre; an object moving along a bounded
  path is solid over its whole travel;
- **perches**: each is the catalog's point placed the same way; a flyer landing, perching or leaving
  is on a perch when it stands within the millimetre the flight rounds to of the point's plan
  position, between the point and its kind's approach height above;
- **its grid**: the volume the flight contract states (the largest box of whole cells inside the
  ground's area, from the ground to the module's ceiling), and a cell solid where a part's box grown
  by half the widest flying kind's span touches it, both read by this module's own lookups;
- **kinds**: each flying kind's figures, read from the flight kind catalog's file.

Over a run of windows as a page reads them, the move from one window's last step to the next
window's first included, it asks:

- every flying position lies in the volume and the kind's band; every landing, take-off and perch
  lies on a declared perch's column, a perching flyer on its perch's point, and no perch holds two
  flyers;
- no move is longer than the kind's top speed allows in a step, the move into an episode's first
  step included, where every flyer must be perching at home;
- no point of any move lies in a solid cell, except a cell of the perch's own object for a flyer
  moving straight up or down that perch's column;
- no move brings a flyer's body, a box as wide as its kind's span, into any part, except its own
  perch's object while it moves along that perch's column;
- at every episode's last step every flyer is perching at home, and the window names exactly the
  flyers that are not.

It imports nothing of the flight: not its air, its arithmetic, its step, its episodes or its
composer (``tests/test_flight_checks.py`` holds that), so a part the flight places wrongly is a
violation here rather than an error both agree on. Floats are this checker's own: every bound is
rounded outward, and a perch point is compared within a millimetre.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from fractions import Fraction
from typing import Any, Final, Protocol

from exulanica.movement.registry import FLIGHT, movement_module
from exulanica.world.flight_kinds import CATALOG_DIRECTORY, CATALOG_ID, CATALOG_VERSION
from exulanica.world.object_catalog import MarkerRecipe, WorldObjectCatalog, world_object_catalog
from exulanica.world.object_meshes import parts_extent
from exulanica.world.objects import AuthoredObject

__all__ = ["CheckedWorld", "FlightCheck", "check_window", "check_windows", "checked_world"]

Cell = tuple[int, int, int]
Box = tuple[tuple[int, int, int], tuple[int, int, int]]
_MICRO: Final = 1_000_000
_MILLI: Final = 1000
#: How far a served perch position may lie from the exact placed point on each axis: the flight
#: serves whole millimetres, truncating across and rounding the height up.
_ROUNDING_MM: Final = 1
#: The one behaviour whose travel a world states: along one axis from where it was placed and back.
_BOUNDED_PATH: Final = ("motion.bounded-path", 1)


class GroundArea(Protocol):
    centre_x_mm: int
    centre_z_mm: int
    half_width_mm: int
    half_depth_mm: int


class Ground(Protocol):
    elevation_mm: int

    @property
    def area(self) -> GroundArea: ...


@dataclass(frozen=True, slots=True)
class _Perch:
    object_id: str
    #: The exact placed point, east, up, south.
    point: tuple[float, float, float]
    span_mm: int


@dataclass(frozen=True)
class CheckedWorld:
    """The world as this checker derives it: volume, parts, perches, grid and kinds."""

    min_x_mm: int
    max_x_mm: int
    min_z_mm: int
    max_z_mm: int
    ground_mm: int
    ceiling_mm: int
    cell_mm: int
    clearance_mm: int
    #: Each part's placed box, closed, with its object.
    parts: tuple[tuple[str, Box], ...]
    perches: Mapping[str, _Perch]
    #: Each flying kind's figures, by kind, as the catalog's file states them.
    kinds: Mapping[str, Mapping[str, int]]
    #: Every solid cell and the objects whose grown parts touch it.
    solid: Mapping[Cell, frozenset[str]]
    _near: dict[int, dict[Cell, list[int]]] = field(default_factory=dict, compare=False)

    @property
    def shape(self) -> tuple[int, int, int]:
        size = self.cell_mm
        return (
            (self.max_x_mm - self.min_x_mm) // size,
            (self.ceiling_mm - self.ground_mm) // size,
            (self.max_z_mm - self.min_z_mm) // size,
        )

    def cells(self, low: Sequence[float], high: Sequence[float]) -> Iterable[Cell]:
        """Every cell the closed box ``[low, high]`` meets, clipped to the grid."""
        origins = (self.min_x_mm, self.ground_mm, self.min_z_mm)
        ranges = []
        for axis, count in enumerate(self.shape):
            first = max(0, math.floor((low[axis] - origins[axis]) / self.cell_mm))
            last = min(count - 1, math.floor((high[axis] - origins[axis]) / self.cell_mm))
            ranges.append(range(first, last + 1))
        return ((x, y, z) for x in ranges[0] for y in ranges[1] for z in ranges[2])

    def cell_low(self, cell: Cell) -> tuple[int, int, int]:
        size = self.cell_mm
        return (
            self.min_x_mm + cell[0] * size,
            self.ground_mm + cell[1] * size,
            self.min_z_mm + cell[2] * size,
        )

    def near(self, half_width: int) -> dict[Cell, list[int]]:
        """For each cell, the parts a body ``half_width`` wide could meet from inside it."""
        index = self._near.get(half_width)
        if index is None:
            index = {}
            for number, (_object_id, (low, high)) in enumerate(self.parts):
                grown_low = tuple(value - half_width for value in low)
                grown_high = tuple(value + half_width for value in high)
                for cell in self.cells(grown_low, grown_high):
                    index.setdefault(cell, []).append(number)
            self._near[half_width] = index
        return index


def _flying_kinds() -> dict[str, dict[str, int]]:
    """Each flying kind's parameter values, read from the flight kind catalog's own file."""
    path = CATALOG_DIRECTORY / f"{CATALOG_ID}.v{CATALOG_VERSION}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    return {
        entry["key"]: {name: row["value"] for name, row in entry["parameters"].items()}
        for entry in document["entries"]
    }


def _placed(point: Sequence[float], transform: Any) -> tuple[float, float, float]:
    """A point of a kind's own frame (across, front, up) in the region (east, up, south).

    The renderer draws a kind's front toward its own ``-z`` and turns it about the vertical by its
    yaw, counter-clockwise seen from above: an east offset turns toward north (``-z``) as the yaw
    grows.
    """
    scale = transform.scale_milli / _MILLI
    east, up, south = point[0] * scale, point[2] * scale, -point[1] * scale
    angle = transform.yaw_microradians / _MICRO
    cosine, sine = math.cos(angle), math.sin(angle)
    return (
        transform.x_mm + east * cosine + south * sine,
        transform.y_mm + up,
        transform.z_mm - east * sine + south * cosine,
    )


def _travel(obj: AuthoredObject) -> tuple[int, int, int]:
    behaviour = obj.behaviour
    if behaviour is None:
        return (0, 0, 0)
    if (behaviour.behaviour_key, behaviour.behaviour_version) != _BOUNDED_PATH:
        raise ValueError(f"{obj.object_id}: no rule for where behaviour {behaviour.behaviour_key}")
    axis, travel = behaviour.parameters["axis"], behaviour.parameters["travel_mm"]
    return tuple(travel if axis == name else 0 for name in ("x", "y", "z"))  # type: ignore[return-value]


def _part_boxes(kind: Any, transform: Any, travel: Sequence[int]) -> list[Box]:
    """Each part of a kind as the renderer draws it, placed: the closed box of its drawn extent's
    corners, rounded outward to the millimetre, over the whole of its travel."""
    if isinstance(kind.recipe, MarkerRecipe):
        recipe = kind.recipe
        extents = [
            (
                -recipe.size_x_mm / 2,
                -recipe.size_y_mm / 2,
                0,
                recipe.size_x_mm / 2,
                recipe.size_y_mm / 2,
                recipe.size_z_mm,
            )
        ]
    else:
        extents = []
        for part in kind.recipe.parts:
            drawn = parts_extent([part.form])
            extents.append(
                (drawn.min_x, drawn.min_y, drawn.min_z, drawn.max_x, drawn.max_y, drawn.max_z)
            )
    boxes: list[Box] = []
    for min_x, min_y, min_z, max_x, max_y, max_z in extents:
        corners = [
            _placed((x, y, z), transform)
            for x in (min_x, max_x)
            for y in (min_y, max_y)
            for z in (min_z, max_z)
        ]
        low = [math.floor(min(corner[axis] for corner in corners)) for axis in range(3)]
        high = [math.ceil(max(corner[axis] for corner in corners)) for axis in range(3)]
        for axis in range(3):
            low[axis] = min(low[axis], low[axis] + travel[axis])
            high[axis] = max(high[axis], high[axis] + travel[axis])
        boxes.append(((low[0], low[1], low[2]), (high[0], high[1], high[2])))
    return boxes


def checked_world(
    *,
    objects: Sequence[AuthoredObject],
    asset_keys: Mapping[str, str],
    ground: Ground,
    catalog: WorldObjectCatalog | None = None,
) -> CheckedWorld:
    """The world as this checker derives it from the placed ``objects`` over ``ground``.

    ``asset_keys`` maps each reviewed asset's content digest to its registry key, as the registry
    holds them; the world object catalog names the kind drawn for each key.
    """
    catalog = world_object_catalog() if catalog is None else catalog
    kinds_by_asset = catalog.by_asset_key()
    module = movement_module(FLIGHT)
    cell, ceiling = module.value("cell_mm"), module.value("ceiling_mm")
    flying = _flying_kinds()
    clearance = max(math.ceil(kind["body_span_mm"] / 2) for kind in flying.values())
    area = ground.area
    half_x = area.half_width_mm // cell * cell
    half_z = area.half_depth_mm // cell * cell
    parts: list[tuple[str, Box]] = []
    perches: dict[str, _Perch] = {}
    for obj in sorted(objects, key=lambda value: value.object_id):
        if obj.removed:
            continue
        kind = kinds_by_asset[asset_keys[obj.asset_sha256]]
        travel = _travel(obj)
        parts.extend((obj.object_id, box) for box in _part_boxes(kind, obj.transform, travel))
        if travel != (0, 0, 0):
            # A perch that moves is no perch: nothing may land on it.
            continue
        for index, perch in enumerate(kind.perches):
            perches[f"{obj.object_id}:perch:{index}"] = _Perch(
                obj.object_id,
                _placed(perch.position_mm, obj.transform),
                perch.span_mm * obj.transform.scale_milli // _MILLI,
            )
    unmarked = CheckedWorld(
        min_x_mm=area.centre_x_mm - half_x,
        max_x_mm=area.centre_x_mm + half_x,
        min_z_mm=area.centre_z_mm - half_z,
        max_z_mm=area.centre_z_mm + half_z,
        ground_mm=ground.elevation_mm,
        ceiling_mm=ground.elevation_mm + ceiling,
        cell_mm=cell,
        clearance_mm=clearance,
        parts=tuple(parts),
        perches=perches,
        kinds=flying,
        solid={},
    )
    solid: dict[Cell, set[str]] = {}
    for object_id, (low, high) in parts:
        grown_low = tuple(value - clearance for value in low)
        grown_high = tuple(value + clearance for value in high)
        for found in unmarked.cells(grown_low, grown_high):
            solid.setdefault(found, set()).add(object_id)
    return replace(unmarked, solid={key: frozenset(value) for key, value in solid.items()})


# -- exact geometry, this checker's own -----------------------------------------------------------


def _segment_meets_cell(
    start: Sequence[int], end: Sequence[int], low: Sequence[int], size: int
) -> bool:
    """Whether a point of the segment lies in the half-open cube ``[low, low + size)``, exactly."""
    earliest, earliest_open = Fraction(0), False
    latest, latest_open = Fraction(1), False
    for axis in range(3):
        begin, change = start[axis], end[axis] - start[axis]
        bottom, top = low[axis], low[axis] + size
        if change == 0:
            if not bottom <= begin < top:
                return False
            continue
        at_bottom = Fraction(bottom - begin, change)
        at_top = Fraction(top - begin, change)
        # Moving up the axis the segment is inside from reaching the bottom until reaching the
        # top, which is outside; moving down, from leaving the top (outside) until the bottom.
        if change > 0:
            enter, enter_open, leave, leave_open = at_bottom, False, at_top, True
        else:
            enter, enter_open, leave, leave_open = at_top, True, at_bottom, False
        if enter > earliest or (enter == earliest and enter_open):
            earliest, earliest_open = enter, enter_open
        if leave < latest or (leave == latest and leave_open):
            latest, latest_open = leave, leave_open
    return earliest < latest or (earliest == latest and not earliest_open and not latest_open)


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


def _length(offset: Sequence[int]) -> int:
    return math.isqrt(sum(value * value for value in offset))


# -- the check ------------------------------------------------------------------------------------


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


def _perch_under(
    world: CheckedWorld, approach_mm: int, position: Sequence[int], state: str
) -> str | None:
    """The declared perch whose column holds a landing, perching or leaving flyer, found from
    where it is: which perch a flyer uses is not served."""
    if state == "flying":
        return None
    for perch_id, perch in world.perches.items():
        x, y, z = perch.point
        if (
            abs(position[0] - x) <= _ROUNDING_MM
            and abs(position[2] - z) <= _ROUNDING_MM
            and y - _ROUNDING_MM <= position[1] <= y + approach_mm + _ROUNDING_MM
        ):
            return perch_id
    return None


def _on_point(world: CheckedWorld, perch_id: str, position: Sequence[int]) -> bool:
    point = world.perches[perch_id].point
    return all(abs(position[axis] - point[axis]) <= _ROUNDING_MM for axis in range(3))


def check_window(
    world: CheckedWorld,
    homes: Mapping[str, str],
    window: Mapping[str, Any],
    *,
    before: Mapping[str, Any] | None = None,
) -> FlightCheck:
    """Check every served step of every flyer in ``window`` against ``world``.

    ``homes`` names each flyer's home perch, as the flight's input states it. ``before`` is the
    window served just before this one: its last step and this window's first are checked as one
    move, as a page draws them.
    """
    result = FlightCheck()
    states = window["states"]
    episode = window["episode_steps"]
    step_ms = window["step_ms"]
    from_step = window["from_step"]
    if before is not None and before["from_step"] + before["steps"] != from_step:
        raise ValueError("the window before does not end where this one starts")
    before_rows = {} if before is None else {row["flyer_id"]: row for row in before["flyers"]}
    holders: dict[tuple[int, str], str] = {}
    late: set[tuple[int, str]] = set()
    for row in window["flyers"]:
        flyer_id = row["flyer_id"]
        kind = world.kinds[row["kind"]]
        low_band = world.ground_mm + kind["min_altitude_mm"]
        high_band = world.ground_mm + kind["max_altitude_mm"]
        half_width = math.ceil(kind["body_span_mm"] / 2)
        approach = kind["approach_height_mm"]
        limit = max(kind["max_speed_mm_s"], kind["takeoff_rate_mm_s"], kind["landing_rate_mm_s"])
        home = homes.get(flyer_id)
        if home not in world.perches:
            result.record(flyer_id, from_step, "home_not_declared", f"home {home!r}")
            continue
        previous: tuple[int, int, int] | None = None
        previous_perch: str | None = None
        joined = before_rows.get(flyer_id)
        if joined is not None and before is not None:
            last = before["steps"] - 1
            previous = tuple(joined["position_mm"][3 * last : 3 * last + 3])  # type: ignore[assignment]
            previous_state = before["states"][joined["state"][last]]
            previous_perch = _perch_under(world, approach, previous, previous_state)  # type: ignore[arg-type]
        for index in range(len(row["state"])):
            step = from_step + index
            position = tuple(row["position_mm"][3 * index : 3 * index + 3])
            state = states[row["state"][index]]
            result.states[state] += 1
            result.guard_holds += row["held"][index]
            perch_here = _perch_under(world, approach, position, state)
            if state != "flying":
                if perch_here is None:
                    result.record(flyer_id, step, "off_column", f"{state} at {list(position)}")
                else:
                    other = holders.setdefault((step, perch_here), flyer_id)
                    if other != flyer_id:
                        result.record(
                            flyer_id, step, "perch_held_twice", f"{perch_here} with {other}"
                        )
                    if state == "perching" and not _on_point(world, perch_here, position):
                        result.record(flyer_id, step, "perched_off_point", f"at {list(position)}")
            elif not (
                world.min_x_mm <= position[0] <= world.max_x_mm
                and low_band <= position[1] <= high_band
                and world.min_z_mm <= position[2] <= world.max_z_mm
            ):
                result.record(flyer_id, step, "out_of_bounds", f"at {list(position)}")
            at_home = state == "perching" and perch_here == home
            if step % episode == 0 and not at_home:
                result.record(flyer_id, step, "genesis_not_home", f"{state} at {list(position)}")
            if step % episode == episode - 1:
                result.episode_ends += 1
                if not at_home:
                    result.late_home += 1
                    late.add((step, flyer_id))
                    result.record(
                        flyer_id, step, "not_home_at_episode_end", f"{state} at {list(position)}"
                    )
            if previous is not None:
                _check_move(
                    result,
                    world,
                    flyer_id,
                    step,
                    previous,
                    position,  # type: ignore[arg-type]
                    moved_limit=limit * step_ms // 1000 + 1,
                    half_width=half_width,
                    # A perch's own object is spared only for a move along its column: straight
                    # up or down, as landing, perching and taking off move. A move from anywhere
                    # else onto a perch, a jump home at an episode's start among them, is not.
                    spared=(
                        {world.perches[p].object_id for p in (previous_perch, perch_here) if p}
                        if previous[0] == position[0] and previous[2] == position[2]
                        else set()
                    ),
                )
            previous, previous_perch = position, perch_here  # type: ignore[assignment]
    reported = {(entry["step"], entry["flyer_id"]) for entry in window["late_home"]}
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
    world: CheckedWorld,
    flyer_id: str,
    step: int,
    previous: tuple[int, int, int],
    position: tuple[int, int, int],
    *,
    moved_limit: int,
    half_width: int,
    spared: set[str],
) -> None:
    """One move, from the step before ``step`` to it: its length, its cells and its body."""
    result.segments += 1
    offset = tuple(b - a for a, b in zip(previous, position, strict=True))
    if _length(offset) > moved_limit:
        result.record(flyer_id, step, "moved_too_far", f"{list(previous)} -> {list(position)}")
    low = tuple(min(a, b) for a, b in zip(previous, position, strict=True))
    high = tuple(max(a, b) for a, b in zip(previous, position, strict=True))
    for cell in world.cells(low, high):
        owners = world.solid.get(cell)
        if owners is None or owners <= spared:
            continue
        if _segment_meets_cell(previous, position, world.cell_low(cell), world.cell_mm):
            result.record(
                flyer_id,
                step,
                "entered_solid_cell",
                f"{list(previous)} -> {list(position)} meets {list(cell)}",
            )
            break
    index = world.near(half_width)
    seen: set[int] = set()
    for cell in world.cells(low, high):
        for number in index.get(cell, ()):
            if number in seen:
                continue
            seen.add(number)
            object_id, (part_low, part_high) = world.parts[number]
            if object_id in spared:
                continue
            if _segment_meets_box(
                previous,
                position,
                tuple(value - half_width for value in part_low),
                tuple(value + half_width for value in part_high),
            ):
                result.record(
                    flyer_id,
                    step,
                    "body_meets_solid",
                    f"{list(previous)} -> {list(position)} brings the body into {object_id}",
                )
                return


def check_windows(
    world: CheckedWorld, homes: Mapping[str, str], windows: Sequence[Mapping[str, Any]]
) -> FlightCheck:
    """Check consecutive windows as one run: each window, and the move joining it to the last."""
    total = FlightCheck()
    for index, window in enumerate(windows):
        total.add(check_window(world, homes, window, before=windows[index - 1] if index else None))
    return total
