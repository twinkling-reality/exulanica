"""Mechanical checks of every transition, written apart from the simulation that they check.

:class:`TransitionChecker` reads two consecutive state documents and the inputs, and reports
every violation it finds. It shares the network's geometry and the catalogs with the simulation,
and nothing else: footprints, signal indications, stop observations, gap acceptance and crossing
sweeps are recomputed here from the states.

**Footprint model.** A vehicle's body is its front position minus its length, back along its
route. Each route piece it covers is a flat-ended rectangle reaching, either side, the class's
half-width, plus on a lane piece the rear-axle off-tracking of the class's wheelbase at the
piece's bends, and on a turning connector piece the class's turning envelope (inward extent on
the inside of the turn, outward extent outside). A parked vehicle is its whole stall.

**Checks.**

``overlap``
    No two bodies share interior points.
``entered_without_reservation``
    A vehicle whose front crossed a gate held a reservation for it.
``entered_on_red``
    A signalised entry happened on a green or amber second.
``did_not_stop``
    A stop-controlled entry was granted after the vehicle stood still, front at the line.
``gap_not_given``
    A yielding movement was granted only when every front vehicle of a conflicting movement with
    priority could not reach its line within the critical headway, unless that vehicle was itself
    stopped at its line and still waiting after the second.
``all_way_order``
    An all-way stop entry was granted in stopping order, with ties going to the vehicle on the
    right, and a full-cycle tie to the first approach.
``crossing_conflict``
    No body, swept over the second, met a crossing band while a pedestrian was on it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from exulanica.traffic.catalogs import TrafficCatalogs, VehicleClass
from exulanica.traffic.geometry import (
    Point,
    circumradius_floor,
    convex_overlap,
    cross,
    dot,
    offtracking_mm,
    rectangle,
)
from exulanica.traffic.inputs import TrafficInputs
from exulanica.traffic.network import JunctionSpec, RoadNetwork

__all__ = ["CHECK_KINDS", "TransitionChecker", "Violation"]

CHECK_KINDS: Final = (
    "overlap",
    "entered_without_reservation",
    "entered_on_red",
    "did_not_stop",
    "gap_not_given",
    "all_way_order",
    "crossing_conflict",
)
_CELL_MM: Final = 25_000
_MS: Final = 1000


@dataclass(frozen=True)
class Violation:
    kind: str
    second: int
    vehicles: tuple[str, ...]
    detail: str


@dataclass
class _Body:
    vehicle_id: str
    rectangles: list[tuple[Point, ...]]
    box: tuple[int, int, int, int]


def _box_of(polygons: Sequence[Sequence[Point]]) -> tuple[int, int, int, int]:
    xs = [point[0] for polygon in polygons for point in polygon]
    ys = [point[1] for polygon in polygons for point in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _boxes_touch(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> bool:
    return not (
        first[2] < second[0] or second[2] < first[0] or first[3] < second[1] or second[3] < first[1]
    )


@dataclass
class TransitionChecker:
    network: RoadNetwork
    catalogs: TrafficCatalogs
    inputs: TrafficInputs
    #: vehicle id -> (gate path, gate position, second it was first seen stopped there)
    stops: dict[str, tuple[str, int, int]] = field(default_factory=dict)
    _extents: dict[tuple[str, str], list[tuple[int, int]]] = field(default_factory=dict)

    # Footprints --------------------------------------------------------------------------------

    def piece_extents(self, path_id: str, vehicle: VehicleClass) -> list[tuple[int, int]]:
        key = (path_id, vehicle.key)
        if key in self._extents:
            return self._extents[key]
        path = self.network.paths[path_id]
        line = path.line
        half = -(-vehicle.width_mm // 2)
        extents = []
        if path.kind == "lane":
            for index in range(line.piece_count):
                extra = 0
                for vertex in (index, index + 1):
                    if 0 < vertex < len(line.points) - 1:
                        radius = circumradius_floor(
                            line.points[vertex - 1], line.points[vertex], line.points[vertex + 1]
                        )
                        if radius is not None:
                            extra = max(extra, offtracking_mm(radius, vehicle.wheelbase_mm))
                extents.append((half + extra, half + extra))
        else:
            first = line.piece_direction(0)
            last = line.piece_direction(line.piece_count - 1)
            inward = max(half, vehicle.turning_inward_extent_mm)
            outward = max(half, vehicle.turning_outward_extent_mm)
            for index in range(line.piece_count):
                direction = line.piece_direction(index)
                straight = path.turn == "straight" or any(
                    cross(direction, end) == 0 and dot(direction, end) > 0 for end in (first, last)
                )
                if straight:
                    extents.append((half, half))
                elif path.turn == "right":
                    extents.append((outward, inward))
                else:
                    extents.append((inward, outward))
        self._extents[key] = extents
        return extents

    def span_rectangles(
        self, route: Sequence[str], vehicle: VehicleClass, start: int, end: int
    ) -> list[tuple[Point, ...]]:
        """Rectangles covering route coordinates ``[start, end]``."""
        rectangles = []
        offset = 0
        for path_id in route:
            line = self.network.paths[path_id].line
            low, high = max(start - offset, 0), min(end - offset, line.length)
            if low <= high and (high > low or start == end):
                extents = self.piece_extents(path_id, vehicle)
                for index, a, b in line.span(low, high):
                    shape = rectangle(a, b, *extents[index])
                    if shape is not None:
                        rectangles.append(shape)
            offset += line.length
            if offset > end:
                break
        return rectangles

    def route_front(self, vehicle: Mapping[str, Any]) -> int:
        paths = self.network.paths
        return (
            sum(paths[path_id].length for path_id in vehicle["route"][: vehicle["route_index"]])
            + vehicle["position_mm"]
        )

    def body(self, vehicle: Mapping[str, Any]) -> _Body | None:
        vehicle_class = self.catalogs.vehicle_class(vehicle["vehicle_class"])
        if vehicle["mode"] == "parked":
            stall = self.network.spaces[vehicle["space"]].footprint
            return _Body(vehicle["id"], [stall], _box_of([stall]))
        front = self.route_front(vehicle)
        rectangles = self.span_rectangles(
            vehicle["route"], vehicle_class, max(front - vehicle_class.length_mm, 0), front
        )
        if not rectangles:
            return None
        return _Body(vehicle["id"], rectangles, _box_of(rectangles))

    # Checks ------------------------------------------------------------------------------------

    def overlaps(self, state: Mapping[str, Any]) -> list[Violation]:
        bodies = [body for body in map(self.body, state["vehicles"]) if body is not None]
        cells: dict[tuple[int, int], list[int]] = {}
        for index, body in enumerate(bodies):
            x0, y0, x1, y1 = body.box
            for cx in range(x0 // _CELL_MM, x1 // _CELL_MM + 1):
                for cy in range(y0 // _CELL_MM, y1 // _CELL_MM + 1):
                    cells.setdefault((cx, cy), []).append(index)
        pairs = set()
        for members in cells.values():
            for position, first in enumerate(members):
                for second in members[position + 1 :]:
                    pairs.add((first, second))
        violations = []
        for first, second in sorted(pairs):
            a, b = bodies[first], bodies[second]
            if not _boxes_touch(a.box, b.box):
                continue
            if any(convex_overlap(p, q) for p in a.rectangles for q in b.rectangles):
                violations.append(
                    Violation(
                        "overlap",
                        state["second"],
                        tuple(sorted((a.vehicle_id, b.vehicle_id))),
                        "bodies share interior points",
                    )
                )
        return violations

    def indication(self, junction: JunctionSpec, connector: str, second: int) -> str:
        signal = junction.signal
        assert signal is not None
        plan = self.catalogs.plan(signal.plan)
        group = dict(signal.connector_groups)[connector]
        cycle_s = sum(interval.duration_ms for interval in plan.intervals) // _MS
        position = (second - signal.offset_s) % cycle_s
        elapsed = 0
        for interval in plan.intervals:
            elapsed += interval.duration_ms // _MS
            if position < elapsed:
                if group in interval.vehicle_green:
                    return "green"
                return "amber" if group in interval.vehicle_amber else "red"
        raise AssertionError("every position in a cycle falls in an interval")

    def _gate_ahead(self, vehicle: Mapping[str, Any]) -> tuple[str, int, int, str, int] | None:
        """``(gate path, gate position, distance, kind, target)`` of the next gate, if any."""
        paths = self.network.paths
        distance = 0
        start = vehicle["position_mm"]
        for index in range(vehicle["route_index"], len(vehicle["route"])):
            path_id = vehicle["route"][index]
            for gate in self.network.gates.get(path_id, ()):
                if gate.position >= start:
                    return (
                        path_id,
                        gate.position,
                        distance + gate.position - start,
                        gate.kind,
                        gate.target,
                    )
            distance += paths[path_id].length - start
            start = 0
        return None

    def observe_stops(self, state: Mapping[str, Any]) -> None:
        for vehicle in state["vehicles"]:
            key = vehicle["id"]
            if vehicle["mode"] != "driving" or vehicle["speed_mm_per_s"] != 0:
                self.stops.pop(key, None)
                continue
            gate = self._gate_ahead(vehicle)
            if gate is None or gate[2] != 0:
                self.stops.pop(key, None)
                continue
            known = self.stops.get(key)
            if known is None or known[:2] != gate[:2]:
                self.stops[key] = (gate[0], gate[1], state["second"])

    def _front_waiting(
        self, before: Mapping[str, Any], junction: JunctionSpec
    ) -> dict[str, tuple[Mapping[str, Any], int, str]]:
        """Per inbound lane, the front unreserved vehicle headed through this junction."""
        found: dict[str, tuple[Mapping[str, Any], int, str]] = {}
        for vehicle in before["vehicles"]:
            if vehicle["mode"] != "driving" or vehicle["reservation"] is not None:
                continue
            gate = self._gate_ahead(vehicle)
            if gate is None or gate[3] != "junction" or gate[4] != junction.ordinal:
                continue
            route = vehicle["route"]
            index = route.index(gate[0], vehicle["route_index"])
            if index + 1 >= len(route):
                continue
            known = found.get(gate[0])
            if known is None or (gate[2], vehicle["id"]) < (known[1], known[0]["id"]):
                found[gate[0]] = (vehicle, gate[2], route[index + 1])
        return found

    def _reach_ms(self, vehicle: Mapping[str, Any], distance: int) -> int:
        vehicle_class = self.catalogs.vehicle_class(vehicle["vehicle_class"])
        path = self.network.paths[vehicle["route"][vehicle["route_index"]]]
        cap = min(path.speed_limit_mm_per_s, vehicle_class.speed_cap_mm_per_s)
        speed = vehicle["speed_mm_per_s"]
        covered = 0
        ticks = 0
        while covered < distance:
            speed = min(speed + vehicle_class.acceleration_mm_per_s2, cap)
            covered += speed
            ticks += 1
        return max(ticks - 1, 0) * _MS

    def grant_rules(self, before: Mapping[str, Any], after: Mapping[str, Any]) -> list[Violation]:
        second = before["second"]
        later = {vehicle["id"]: vehicle for vehicle in after["vehicles"]}
        violations = []
        for vehicle in after["vehicles"]:
            reservation = vehicle["reservation"]
            if (
                reservation is None
                or reservation["kind"] != "junction"
                or reservation["granted_second"] != second
            ):
                continue
            junction = self.network.junctions[reservation["target"]]
            policy = self.catalogs.policy(junction.policy)
            connector = reservation["connector"]
            lane = reservation["gate_path"]
            approach = junction.approach_of_lane(lane)
            stop = self.stops.get(vehicle["id"])
            stopped_here = stop is not None and stop[:2] == (lane, reservation["gate_position_mm"])
            if (policy.rule == "all_way_stop" or approach.control == "stop") and not stopped_here:
                violations.append(
                    Violation(
                        "did_not_stop", second, (vehicle["id"],), f"junction {junction.ordinal}"
                    )
                )
            if policy.rule == "signal" and self.indication(junction, connector, second) != "green":
                violations.append(
                    Violation("entered_on_red", second, (vehicle["id"],), "granted off green")
                )
            conflicts = set(junction.conflicts) | {(b, a) for a, b in junction.conflicts}
            waiting = self._front_waiting(before, junction)
            if policy.rule in ("priority", "signal"):
                ranks = sorted({item.rank for item in junction.approaches})
                minor = policy.rule == "priority" and approach.rank > ranks[0]
                turn = self.network.paths[connector].turn
                for other_lane, (other, distance, other_connector) in sorted(waiting.items()):
                    if other["id"] == vehicle["id"]:
                        continue
                    other_approach = junction.approach_of_lane(other_lane)
                    if other_approach.identity == approach.identity:
                        continue
                    if (connector, other_connector) not in conflicts:
                        continue
                    other_turn = self.network.paths[other_connector].turn
                    if policy.rule == "signal":
                        if self.indication(junction, other_connector, second) != "green":
                            continue
                        if policy.turn_rank(other_turn) >= policy.turn_rank(turn):
                            continue
                        headway = policy.headway_ms("permitted_left")
                    else:
                        higher = other_approach.rank < approach.rank or (
                            other_approach.rank == approach.rank
                            and policy.turn_rank(other_turn) < policy.turn_rank(turn)
                        )
                        if not higher:
                            continue
                        key = (
                            {
                                "left": "minor_left",
                                "right": "minor_right",
                                "straight": "minor_through",
                            }[turn]
                            if minor
                            else "major_left"
                        )
                        headway = policy.headway_ms(key)
                    still_waiting = later[other["id"]]["reservation"] is None
                    if distance == 0 and other["speed_mm_per_s"] == 0 and still_waiting:
                        continue
                    if self._reach_ms(other, distance) < headway:
                        violations.append(
                            Violation(
                                "gap_not_given",
                                second,
                                (vehicle["id"], other["id"]),
                                f"junction {junction.ordinal}",
                            )
                        )
            if policy.rule == "all_way_stop" and stopped_here:
                mine = stop[2] if stop else second
                same = []
                for other_lane, (other, distance, other_connector) in sorted(waiting.items()):
                    if (
                        other["id"] == vehicle["id"]
                        or (connector, other_connector) not in conflicts
                    ):
                        continue
                    other_stop = self.stops.get(other["id"])
                    if distance != 0 or other_stop is None or other_stop[0] != other_lane:
                        continue
                    if later[other["id"]]["reservation"] is not None:
                        continue
                    if other_stop[2] < mine:
                        violations.append(
                            Violation(
                                "all_way_order",
                                second,
                                (vehicle["id"], other["id"]),
                                "a vehicle that stopped earlier was still waiting",
                            )
                        )
                    elif other_stop[2] == mine:
                        same.append((other_lane, other, other_connector))
                if same and not _tie_allows(
                    policy, junction, self.network, lane, connector, same, conflicts
                ):
                    violations.append(
                        Violation(
                            "all_way_order",
                            second,
                            (vehicle["id"],),
                            "a tie went to a vehicle not on the right",
                        )
                    )
        return violations

    def entries(self, before: Mapping[str, Any], after: Mapping[str, Any]) -> list[Violation]:
        later = {vehicle["id"]: vehicle for vehicle in after["vehicles"]}
        violations = []
        second = before["second"]
        for vehicle in before["vehicles"]:
            if vehicle["mode"] != "driving":
                continue
            nxt = later[vehicle["id"]]
            if nxt["mode"] not in ("driving", "arriving") or nxt["route"] != vehicle["route"]:
                continue
            start, end = self.route_front(vehicle), self.route_front(nxt)
            offset = 0
            for index, path_id in enumerate(vehicle["route"]):
                for gate in self.network.gates.get(path_id, ()):
                    absolute = offset + gate.position
                    if not start <= absolute < end:
                        continue
                    reservation = nxt["reservation"]
                    held = (
                        reservation is not None
                        and reservation["gate_index"] == index
                        and reservation["gate_position_mm"] == gate.position
                    )
                    if not held:
                        violations.append(
                            Violation(
                                "entered_without_reservation",
                                second,
                                (vehicle["id"],),
                                f"{gate.kind} {gate.target}",
                            )
                        )
                    if gate.kind == "junction":
                        junction = self.network.junctions[gate.target]
                        connector = vehicle["route"][index + 1]
                        if (
                            junction.signal is not None
                            and self.indication(junction, connector, second) == "red"
                        ):
                            violations.append(
                                Violation(
                                    "entered_on_red",
                                    second,
                                    (vehicle["id"],),
                                    f"junction {junction.ordinal}",
                                )
                            )
                offset += self.network.paths[path_id].length
        return violations

    def crossings(self, before: Mapping[str, Any], after: Mapping[str, Any]) -> list[Violation]:
        second = before["second"]
        active = {}
        for feed in self.inputs.feeds:
            for entry in feed.entries:
                if entry.arrival_second <= second + 1 and second <= entry.last_second:
                    active[entry.crossing_id] = entry
        if not active:
            return []
        bands = []
        for band in self.network.bands:
            if band.society_crossing_id in active:
                shape = rectangle(
                    band.line[0], band.line[1], band.width_mm // 2, band.width_mm // 2
                )
                assert shape is not None
                bands.append((band, shape, _box_of([shape])))
        later = {vehicle["id"]: vehicle for vehicle in after["vehicles"]}
        violations = []
        for vehicle in before["vehicles"]:
            nxt = later[vehicle["id"]]
            if vehicle["mode"] == "parked" or nxt["mode"] == "parked":
                continue
            if nxt["route"] != vehicle["route"]:
                continue
            vehicle_class = self.catalogs.vehicle_class(vehicle["vehicle_class"])
            rear = max(self.route_front(vehicle) - vehicle_class.length_mm, 0)
            front = self.route_front(nxt)
            swept = self.span_rectangles(vehicle["route"], vehicle_class, rear, front)
            if not swept:
                continue
            box = _box_of(swept)
            for band, shape, band_box in bands:
                if not _boxes_touch(box, band_box):
                    continue
                if any(convex_overlap(part, shape) for part in swept):
                    violations.append(
                        Violation(
                            "crossing_conflict",
                            second,
                            (vehicle["id"],),
                            band.society_crossing_id,
                        )
                    )
        return violations

    def check(self, before: Mapping[str, Any], after: Mapping[str, Any]) -> list[Violation]:
        if before["second"] == 0:
            self.observe_stops(before)
        violations = []
        violations += self.grant_rules(before, after)
        violations += self.entries(before, after)
        violations += self.crossings(before, after)
        self.observe_stops(after)
        violations += self.overlaps(after)
        return violations


def _tie_allows(
    policy: Any,
    junction: JunctionSpec,
    network: RoadNetwork,
    lane: str,
    connector: str,
    same: Sequence[tuple[str, Mapping[str, Any], str]],
    conflicts: set[tuple[str, str]],
) -> bool:
    """Whether a same-second tie at an all-way stop could go to the vehicle on ``lane``."""

    def direction(of_lane: str) -> tuple[int, int]:
        return junction.approach_of_lane(of_lane).direction

    def yields(first_lane: str, first_turn: str, second_lane: str, second_turn: str) -> bool:
        a, b = direction(first_lane), direction(second_lane)
        if cross(a, b) > 0:
            return True
        return (
            cross(a, b) == 0
            and dot(a, b) < 0
            and policy.turn_rank(second_turn) < policy.turn_rank(first_turn)
        )

    turn = network.paths[connector].turn
    if not any(
        yields(lane, turn, other_lane, network.paths[other_connector].turn)
        for other_lane, _, other_connector in same
    ):
        return True
    group = [(lane, connector)] + [
        (other_lane, other_connector) for other_lane, _, other_connector in same
    ]
    everyone_yields = all(
        any(
            yields(
                first,
                network.paths[first_connector].turn,
                other,
                network.paths[other_connector].turn,
            )
            for other, other_connector in group
            if other != first and (first_connector, other_connector) in conflicts
        )
        for first, first_connector in group
    )
    order = {approach.identity: index for index, approach in enumerate(junction.approaches)}
    first_in_order = min(group, key=lambda item: order[junction.approach_of_lane(item[0]).identity])
    return everyone_yields and first_in_order[0] == lane
