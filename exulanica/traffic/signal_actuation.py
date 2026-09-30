"""Versioned bounds and a pure schedule for a model's proposal to extend a signal green.

A missing choice switches at the fixed plan's green minimum. A recorded ``keep`` extends that
one green by one second, up to the catalog's maximum; amber and all-red stay exactly the plan's.
The schedule is rebuilt from recorded choices, so a worker needs no model client for replay.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Final

from exulanica.grammar.catalogs import CatalogSchema, integer_field, load_catalog, text_field
from exulanica.traffic.catalogs import SignalInterval, SignalPlan
from exulanica.traffic.network import RoadNetwork

__all__ = [
    "SignalActuation",
    "SignalTimeline",
    "signal_actuation",
    "signal_observation",
]

_DIRECTORY: Final = Path(__file__).resolve().parents[2].joinpath("assets", "catalogs", "roles")
_CATALOG: Final = "junction-signal-timing"
_VERSION: Final = 1
_MILLISECONDS_PER_SECOND: Final = 1000
_ACTIONS: Final = frozenset({"keep", "switch"})


@dataclass(frozen=True, slots=True)
class SignalActuation:
    """The bounds on one signal controller, read from its versioned catalog."""

    plan: str
    green_extension_seconds_maximum: int
    near_distance_mm: int
    segment_seconds: int
    preparation_lead_seconds: int
    pending_handoffs_maximum: int


@cache
def signal_actuation() -> SignalActuation:
    catalog = load_catalog(
        _DIRECTORY.joinpath(f"{_CATALOG}.v{_VERSION}.json"),
        CatalogSchema(
            _CATALOG,
            _VERSION,
            (
                ("plan", text_field),
                ("green_extension_seconds_maximum", integer_field(1, 60)),
                ("near_distance_mm", integer_field(1, 1_000_000)),
                ("segment_seconds", integer_field(1, 1200)),
                ("preparation_lead_seconds", integer_field(1, 1200)),
                ("pending_handoffs_maximum", integer_field(1, 1000)),
                ("reason", text_field),
            ),
        ),
    )
    if catalog.keys() != ("actuated_two_phase",):
        raise ValueError("junction signal timing states one actuated two-phase controller")
    values = dict(catalog.entries[0].values)
    return SignalActuation(
        plan=str(values["plan"]),
        green_extension_seconds_maximum=int(values["green_extension_seconds_maximum"]),
        near_distance_mm=int(values["near_distance_mm"]),
        segment_seconds=int(values["segment_seconds"]),
        preparation_lead_seconds=int(values["preparation_lead_seconds"]),
        pending_handoffs_maximum=int(values["pending_handoffs_maximum"]),
    )


@dataclass(frozen=True, slots=True)
class SignalTimeline:
    """A bounded signal schedule from a phase cursor and recorded choices.

    A fresh plan starts on its cycle boundary. A continuation supplies the exact phase after the
    preceding second, including green elapsed and extension count, so a 60-second segment or a
    1,200-second trip episode cannot skip amber or all-red when a model extended green.
    """

    plan: SignalPlan
    offset_s: int
    start_second: int
    seconds: int
    choices: Mapping[int, str]
    policy: SignalActuation
    cursor: tuple[int, int, int, int] | None = None
    _indices: tuple[int, ...] = field(init=False, repr=False)
    _intervals: tuple[SignalInterval, ...] = field(init=False, repr=False)
    _cursors: tuple[tuple[int, int, int, int], ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.plan.key != self.policy.plan or len(self.plan.intervals) != 8:
            raise ValueError("the actuation policy names no supported two-phase signal plan")
        if self.seconds <= 0 or (
            self.cursor is None
            and (self.start_second - self.offset_s)
            % (self.plan.cycle_ms // _MILLISECONDS_PER_SECOND)
        ):
            raise ValueError("actuated traffic starts on the signal plan's cycle boundary")
        for second, action in self.choices.items():
            if type(second) is not int or not (
                self.start_second <= second < self.start_second + self.seconds
            ):
                raise ValueError("a signal choice belongs to this timeline")
            if action not in _ACTIONS:
                raise ValueError("a signal choice is keep or switch")
        intervals = self.plan.intervals
        for phase in (0, 4):
            green, clearance, amber, all_red = intervals[phase : phase + 4]
            if (
                len(green.vehicle_green) != 1
                or green.vehicle_green != clearance.vehicle_green
                or green.pedestrian_walk == ()
                or clearance.pedestrian_clearance == ()
                or amber.vehicle_amber != green.vehicle_green
                or all_red.vehicle_green
                or all_red.vehicle_amber
                or any(item.duration_ms % _MILLISECONDS_PER_SECOND for item in intervals)
            ):
                raise ValueError("the two-phase plan has no safe actuation intervals")
        extensions = tuple(
            SignalInterval(
                duration_ms=_MILLISECONDS_PER_SECOND,
                vehicle_green=intervals[phase].vehicle_green,
                vehicle_amber=(),
                pedestrian_walk=(),
                pedestrian_clearance=(),
            )
            for phase in (0, 4)
        )
        object.__setattr__(self, "_intervals", (*intervals, *extensions))
        indices: list[int] = []
        cursors: list[tuple[int, int, int, int]] = []
        reached: set[int] = set()
        durations = tuple(item.duration_ms // _MILLISECONDS_PER_SECOND for item in self._intervals)

        def next_cursor(before: tuple[int, int, int, int], at: int) -> tuple[int, int, int, int]:
            index, elapsed, extensions, green_elapsed = before
            if elapsed + 1 < durations[index]:
                still_green = index in (0, 1, 4, 5, 8, 9)
                return (index, elapsed + 1, extensions, green_elapsed + int(still_green))
            if index in (1, 5, 8, 9):
                phase = 0 if index in (1, 8) else 4
                choice = self.choices.get(at)
                if extensions < self.policy.green_extension_seconds_maximum:
                    if choice is not None:
                        reached.add(at)
                    if choice == "keep":
                        return (8 if phase == 0 else 9, 0, extensions + 1, green_elapsed + 1)
                return (phase + 2, 0, extensions, green_elapsed)
            following = {0: 1, 2: 3, 3: 4, 4: 5, 6: 7, 7: 0}[index]
            if following in (0, 4):
                return (following, 0, 0, 1)
            return (following, 0, extensions, green_elapsed + int(following in (1, 5)))

        if self.cursor is None:
            current = (0, 0, 0, 1)
        else:
            if (
                len(self.cursor) != 4
                or any(type(item) is not int or item < 0 for item in self.cursor)
                or self.cursor[0] >= len(durations)
                or self.cursor[1] >= durations[self.cursor[0]]
                or self.cursor[2] > self.policy.green_extension_seconds_maximum
            ):
                raise ValueError("invalid signal phase cursor")
            current = next_cursor(self.cursor, self.start_second)
        for offset in range(self.seconds):
            if offset:
                current = next_cursor(current, self.start_second + offset)
            indices.append(current[0])
            cursors.append(current)
        if set(self.choices) != reached:
            raise ValueError("a signal choice is not at a reachable green choice point")
        object.__setattr__(self, "_indices", tuple(indices))
        object.__setattr__(self, "_cursors", tuple(cursors))

    def cursor_at(self, second: int) -> tuple[int, int, int, int]:
        """The durable phase after this second's indication has begun."""
        return self._cursors[second - self.start_second]

    def index_at(self, second: int) -> int:
        offset = second - self.start_second
        if not 0 <= offset < self.seconds:
            raise ValueError("second lies outside the sealed signal timeline")
        return self._indices[offset]

    def vehicle_indication(self, second: int, group: str) -> str:
        interval = self.interval_at(second)
        if group in interval.vehicle_green:
            return "green"
        if group in interval.vehicle_amber:
            return "amber"
        return "red"

    def pedestrian_indication(self, second: int, group: str) -> str:
        interval = self.interval_at(second)
        if group in interval.pedestrian_walk:
            return "walk"
        if group in interval.pedestrian_clearance:
            return "clearance"
        return "dont_walk"

    def interval_at(self, second: int) -> SignalInterval:
        return self._intervals[self.index_at(second)]

    def seconds_until_red(self, second: int, group: str) -> int:
        maximum = self.plan.cycle_ms // _MILLISECONDS_PER_SECOND
        for step in range(min(maximum, self.start_second + self.seconds - second)):
            if self.vehicle_indication(second + step, group) == "red":
                return step
        return maximum


def signal_observation(
    state: Mapping[str, object],
    network: RoadNetwork,
    timeline: SignalTimeline,
    signal_id: str,
) -> dict[str, int] | None:
    """The live queue and wait facts at a green's minimum or one-second extension point.

    An absent result means this is not a reachable choice point. At the point the fixed plan
    would enter amber; a model's accepted ``keep`` replaces that one second with green. Vehicles
    are counted only on inbound lanes whose next connector belongs to this signal.
    """
    second = state["second"]
    if type(second) is not int or second < timeline.start_second:
        return None
    index = timeline.index_at(second)
    if second == timeline.start_second:
        if timeline.cursor is None:
            return None
        before = timeline.cursor
    else:
        before = timeline.cursor_at(second - 1)
    if (index, before[0]) not in ((2, 1), (2, 8), (6, 5), (6, 9)):
        return None
    if before[2] >= timeline.policy.green_extension_seconds_maximum:
        # The green already holds every extension the plan allows: amber follows whatever is
        # answered, and the timeline accepts no choice here, so this second is no choice point.
        return None
    junction = next(
        (
            item
            for item in network.junctions.values()
            if item.signal is not None and item.signal.identity == signal_id
        ),
        None,
    )
    if junction is None or junction.signal is None:
        return None
    active_groups = set(timeline.interval_at(second).vehicle_amber)
    counts = {"active_near": 0, "other_near": 0, "active_queue": 0, "other_queue": 0}
    waits = {"active_wait_seconds": 0, "other_wait_seconds": 0}
    lanes = {lane for approach in junction.approaches for lane in approach.inbound_lanes}
    for vehicle in state["vehicles"]:
        if vehicle["mode"] != "driving":
            continue
        route = vehicle["route"]
        position = vehicle["route_index"]
        if position + 1 >= len(route) or route[position] not in lanes:
            continue
        group = dict(junction.signal.connector_groups).get(route[position + 1])
        if group is None:
            continue
        gates = [
            gate
            for gate in network.gates.get(route[position], ())
            if gate.kind == "junction" and gate.target == junction.identity
        ]
        if not gates:
            continue
        distance = gates[-1].position - vehicle["position_mm"]
        if not 0 <= distance <= timeline.policy.near_distance_mm:
            continue
        side = "active" if group in active_groups else "other"
        counts[f"{side}_near"] += 1
        if vehicle["speed_mm_per_s"] == 0:
            counts[f"{side}_queue"] += 1
        wait_since = vehicle["wait_since"]
        if type(wait_since) is int and wait_since >= 0:
            key = f"{side}_wait_seconds"
            waits[key] = max(waits[key], second - wait_since)
    return {
        **counts,
        **waits,
        "near_vehicle_count": counts["active_near"] + counts["other_near"],
        "green_elapsed_seconds": timeline.cursor_at(second)[3],
    }
