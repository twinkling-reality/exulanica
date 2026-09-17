"""A SYNTHETIC road network for the traffic tests, built only from the road record shapes.

This is test data, not a city and not a generator. Every dimension below is a fixture value
chosen so the network exercises the simulation: a signalised four-way centre, two two-way-stop
and two all-way-stop T junctions on a ring road with rounded corners, a pedestrian crossing on
every leg, and parking with bus layovers and bicycle corrals on the four spokes.

Everything is integer arithmetic. Rotations are exact quarter turns, and the ring corners use
the rational circle parametrisation ``((1 - t^2) / (1 + t^2), 2t / (1 + t^2))`` so every point
is computed the same way on every machine.

::

                N (0, 100 m) ---- ring ----,
               /|                            \\
            ring spoke                         ring
             |  |                               |
    W ------ C (0, 0) signalised ------ spoke -- E        N, S: two-way stop (ring has priority)
             |  |                               |         E, W: all-way stop
            ring spoke                         ring
               \\|                            /
                S (0, -100 m) ---- ring ----'
"""

from __future__ import annotations

from typing import Final

from exulanica.canonical import round_half_down
from exulanica.traffic import provisional_records as rec

SCOPE: Final = "5d3a1a4e-6c1b-5b7e-9f0a-2e4c6b8d0f12"
HIERARCHY: Final = "fixture_street"
LIMIT_MM_PER_H: Final = 30_000_000
ALL_CLASSES: Final = ("bicycle", "city_bus", "passenger_car", "van")

ARM_MM: Final = 100_000
STOP_MM: Final = 20_000
BOX_MM: Final = 15_000
LANE_WIDTH_MM: Final = 3_750
LANE_OFFSET_MM: Final = 1_875
PARKING_OUTER_MM: Final = 6_350
CROSSING_AT_MM: Final = 16_500
CROSSING_WIDTH_MM: Final = 3_000
RING_STRAIGHT_MM: Final = 30_000
RING_RADIUS_MM: Final = 70_000
ARC_STEPS: Final = 12

#: (length, classes) along each spoke side, from 26.6 m out from the centre.
PARKING_LAYOUT: Final = (
    (14_000, ("city_bus",)),
    (6_700, ("passenger_car", "van")),
    (6_700, ("passenger_car", "van")),
    (6_700, ("passenger_car", "van")),
    (6_700, ("passenger_car", "van")),
    (2_000, ("bicycle",)),
    (2_000, ("bicycle",)),
)
PARKING_START_MM: Final = 26_600

NODES: Final = {"C": 0, "N": 1, "E": 2, "S": 3, "W": 4}
POSITIONS: Final = {
    "C": (0, 0),
    "N": (0, ARM_MM),
    "E": (ARM_MM, 0),
    "S": (0, -ARM_MM),
    "W": (-ARM_MM, 0),
}
#: Policies by node. The centre is signalised.
POLICIES: Final = {
    "C": "signalised",
    "N": "priority_two_way_stop",
    "S": "priority_two_way_stop",
    "E": "all_way_stop",
    "W": "all_way_stop",
}

Point = tuple[int, int]


def clockwise(point: Point, turns: int) -> Point:
    x, y = point
    for _ in range(turns % 4):
        x, y = y, -x
    return (x, y)


def right_of(direction: Point) -> Point:
    return (direction[1], -direction[0])


def add(*points: Point) -> Point:
    return (sum(point[0] for point in points), sum(point[1] for point in points))


def scale(direction: Point, amount: int) -> Point:
    return (direction[0] * amount, direction[1] * amount)


def quarter_arc(centre: Point, start_axis: Point, end_axis: Point, radius: int) -> list[Point]:
    """Points on the circle from ``centre + radius*start_axis`` to ``centre + radius*end_axis``."""
    points = []
    for k in range(ARC_STEPS + 1):
        denominator = ARC_STEPS * ARC_STEPS + k * k
        along_start = (ARC_STEPS * ARC_STEPS - k * k) * radius
        along_end = 2 * ARC_STEPS * k * radius
        points.append(
            (
                centre[0]
                + round_half_down(
                    start_axis[0] * along_start + end_axis[0] * along_end, denominator
                ),
                centre[1]
                + round_half_down(
                    start_axis[1] * along_start + end_axis[1] * along_end, denominator
                ),
            )
        )
    return points


def dedupe(points: list[Point]) -> tuple[Point, ...]:
    kept: list[Point] = []
    for point in points:
        if not kept or kept[-1] != point:
            kept.append(point)
    return tuple(kept)


def ring_template(offset: int) -> list[Point]:
    """N to E, offset to the right of travel by ``offset`` (negative is left)."""
    top = ARM_MM - offset
    right = ARM_MM - offset
    radius = RING_RADIUS_MM - offset
    return dedupe(
        [
            (0, top),
            (RING_STRAIGHT_MM, top),
            *quarter_arc((RING_STRAIGHT_MM, RING_STRAIGHT_MM), (0, 1), (1, 0), radius),
            (right, RING_STRAIGHT_MM),
            (right, 0),
        ]
    )


def trim(points: tuple[Point, ...], start: int, end: int) -> tuple[Point, ...]:
    """An axis-aligned-ended polyline from ``start`` mm in to ``end`` mm before its end."""
    first, second = points[0], points[1]
    direction = (
        (second[0] > first[0]) - (second[0] < first[0]),
        (second[1] > first[1]) - (second[1] < first[1]),
    )
    head = add(first, scale(direction, start))
    last, before = points[-1], points[-2]
    direction = (
        (last[0] > before[0]) - (last[0] < before[0]),
        (last[1] > before[1]) - (last[1] < before[1]),
    )
    tail = add(last, scale(direction, -end))
    return dedupe([head, *points[1:-1], tail])


def reverse(points: tuple[Point, ...]) -> tuple[Point, ...]:
    return tuple(reversed(points))


class Builder:
    def __init__(self) -> None:
        self.records: list[object] = [rec.RoadRulesRecord("right")]
        self.segments: dict[int, dict] = {}
        self.lanes: dict[int, dict] = {}
        self.inbound: dict[str, list[dict]] = {name: [] for name in NODES}
        self.outbound: dict[str, list[dict]] = {name: [] for name in NODES}
        self.connectors: dict[str, list[tuple[int, dict, str]]] = {name: [] for name in NODES}
        self.crossings: dict[str, list[int]] = {name: [] for name in NODES}
        self.lane_ordinal = 0
        self.crossing_ordinal = 0
        self.space_ordinal = 0

    def identity(self, kind: str, *parts: int | str) -> str:
        return rec.street_record_identity(SCOPE, kind, *parts)

    def node(self, name: str) -> None:
        x, y = POSITIONS[name]
        self.records.append(rec.StreetNodeRecord(NODES[name], x, y))

    def segment(
        self,
        ordinal: int,
        start: str,
        end: str,
        centreline: tuple[Point, ...],
        turns: int,
        spoke: bool,
    ) -> None:
        from exulanica.traffic.geometry import Polyline

        length = Polyline.of(centreline).length
        offsets = (CROSSING_AT_MM, length - CROSSING_AT_MM)
        self.records.append(
            rec.StreetSegmentRecord(
                ordinal,
                NODES[start],
                NODES[end],
                centreline,
                HIERARCHY,
                2 * PARKING_OUTER_MM,
                150,
                300,
                3_000,
                BOX_MM,
                offsets,
            )
        )
        self.segments[ordinal] = {
            "start": start,
            "end": end,
            "centreline": centreline,
            "length": length,
        }
        for index, offset in enumerate(offsets):
            node_name = start if index == 0 else end
            line_axis = self.leg_axis(centreline, index == 0)
            centre = self.point_along(centreline, offset)
            across = right_of(line_axis)
            line = (
                add(centre, scale(across, -PARKING_OUTER_MM)),
                add(centre, scale(across, PARKING_OUTER_MM)),
            )
            control = "signalised" if node_name == "C" else "marked_priority"
            self.records.append(
                rec.CrossingRecord(
                    self.identity("crossing", ordinal, index),
                    self.crossing_ordinal,
                    ordinal,
                    index,
                    control,
                    line,
                    CROSSING_WIDTH_MM,
                )
            )
            self.crossings[node_name].append((self.crossing_ordinal, line_axis))
            self.crossing_ordinal += 1

    @staticmethod
    def leg_axis(points: tuple[Point, ...], at_start: bool) -> Point:
        a, b = (points[0], points[1]) if at_start else (points[-2], points[-1])
        return ((b[0] > a[0]) - (b[0] < a[0]), (b[1] > a[1]) - (b[1] < a[1]))

    @staticmethod
    def point_along(points: tuple[Point, ...], offset: int) -> Point:
        from exulanica.traffic.geometry import Polyline

        return Polyline.of(points).point_at(offset)

    def lane(self, segment: int, direction: str, centreline: tuple[Point, ...]) -> dict:
        info = self.segments[segment]
        record = rec.CarriagewayLaneRecord(
            self.identity("carriageway_lane", segment, direction, 0),
            self.lane_ordinal,
            segment,
            direction,
            0,
            centreline,
            LANE_WIDTH_MM,
            ALL_CLASSES,
            ("left", "straight", "right"),
            LIMIT_MM_PER_H,
        )
        self.records.append(record)
        start, end = (
            (info["start"], info["end"])
            if direction == "with_segment"
            else (info["end"], info["start"])
        )
        lane = {
            "record": record,
            "from": start,
            "to": end,
            "in_axis": self.leg_axis(centreline, False),
            "out_axis": self.leg_axis(centreline, True),
        }
        self.lanes[self.lane_ordinal] = lane
        self.inbound[end].append(lane)
        self.outbound[start].append(lane)
        self.lane_ordinal += 1
        return lane

    def connect(self, name: str) -> None:
        position = POSITIONS[name]
        ordinal = NODES[name]
        for source in self.inbound[name]:
            d_in = source["in_axis"]
            for target in self.outbound[name]:
                d_out = target["out_axis"]
                if d_out == (-d_in[0], -d_in[1]):
                    continue
                end = source["record"].centreline_mm[-1]
                start = target["record"].centreline_mm[0]
                if d_out == d_in:
                    turn, path = "straight", (end, start)
                else:
                    turn = "right" if d_out == right_of(d_in) else "left"
                    radius = BOX_MM - LANE_OFFSET_MM if turn == "right" else BOX_MM + LANE_OFFSET_MM
                    pre = add(position, scale(d_in, -BOX_MM), scale(right_of(d_in), LANE_OFFSET_MM))
                    post = add(
                        position, scale(d_out, BOX_MM), scale(right_of(d_out), LANE_OFFSET_MM)
                    )
                    centre = add(position, scale(d_in, -BOX_MM), scale(d_out, BOX_MM))
                    arc = quarter_arc(centre, (-d_out[0], -d_out[1]), d_in, radius)
                    assert arc[0] == pre and arc[-1] == post, (
                        name,
                        turn,
                        arc[0],
                        pre,
                        arc[-1],
                        post,
                    )
                    path = dedupe([end, *arc, start])
                connector_ordinal = sum(len(items) for items in self.connectors.values())
                record = rec.LaneConnectorRecord(
                    self.identity(
                        "lane_connector", source["record"].identity, target["record"].identity
                    ),
                    connector_ordinal,
                    ordinal,
                    source["record"].lane_ordinal,
                    target["record"].lane_ordinal,
                    turn,
                    path,
                )
                self.records.append(record)
                self.connectors[name].append((connector_ordinal, source, turn))

    def junction(self, name: str) -> None:
        ordinal = NODES[name]
        policy = POLICIES[name]
        self.records.append(
            rec.JunctionRecord(self.identity("junction", ordinal), ordinal, ordinal, policy)
        )
        legs = sorted({lane["record"].segment_ordinal for lane in self.inbound[name]})
        for index, segment in enumerate(legs):
            spoke = self.segments[segment]["start"] == "C" or self.segments[segment]["end"] == "C"
            if policy == "signalised":
                control, rank = "signal", 0
            elif policy == "all_way_stop":
                control, rank = "stop", 0
            elif spoke:
                control, rank = "stop", 1
            else:
                control, rank = "priority", 0
            self.records.append(
                rec.JunctionApproachRecord(
                    self.identity("junction_approach", ordinal, segment),
                    ordinal * 10 + index,
                    ordinal,
                    segment,
                    control,
                    rank,
                )
            )

    def signals(self) -> None:
        ordinal = NODES["C"]
        self.records.append(
            rec.SignalControllerRecord(
                self.identity("signal_controller", ordinal), 0, ordinal, "fixed_two_phase_60s", 0
            )
        )
        groups: dict[str, list[int]] = {"phase_a": [], "phase_b": [], "walk_a": [], "walk_b": []}
        for connector_ordinal, source, _ in self.connectors["C"]:
            north_south = source["in_axis"][0] == 0
            groups["phase_a" if north_south else "phase_b"].append(connector_ordinal)
        for crossing_ordinal, leg_axis in self.crossings["C"]:
            # A crossing on an east-west leg is walked north-south, alongside phase a.
            groups["walk_a" if leg_axis[1] == 0 else "walk_b"].append(crossing_ordinal)
        for group, members in groups.items():
            vehicle = group.startswith("phase")
            self.records.append(
                rec.SignalGroupRecord(
                    self.identity("signal_group", ordinal, group),
                    0,
                    group,
                    tuple(sorted(members)) if vehicle else (),
                    () if vehicle else tuple(sorted(members)),
                )
            )

    def parking(self, segment: int, turns: int) -> None:
        forward = next(
            lane
            for lane in self.lanes.values()
            if lane["record"].segment_ordinal == segment
            and lane["record"].direction == "with_segment"
        )
        backward = next(
            lane
            for lane in self.lanes.values()
            if lane["record"].segment_ordinal == segment
            and lane["record"].direction == "against_segment"
        )
        for side, lane in (("right", forward), ("left", backward)):
            along = PARKING_START_MM
            for index, (length, classes) in enumerate(PARKING_LAYOUT):
                low, high = along, along + length
                if side == "right":
                    corners = [
                        (LANE_WIDTH_MM, low),
                        (PARKING_OUTER_MM, low),
                        (PARKING_OUTER_MM, high),
                        (LANE_WIDTH_MM, high),
                    ]
                    access = (low - STOP_MM, high - STOP_MM)
                else:
                    corners = [
                        (-PARKING_OUTER_MM, low),
                        (-LANE_WIDTH_MM, low),
                        (-LANE_WIDTH_MM, high),
                        (-PARKING_OUTER_MM, high),
                    ]
                    access = (ARM_MM - STOP_MM - high, ARM_MM - STOP_MM - low)
                footprint = tuple(clockwise(corner, turns) for corner in corners)
                self.records.append(
                    rec.ParkingSpaceRecord(
                        self.identity("parking_space", segment, side, index),
                        self.space_ordinal,
                        segment,
                        side,
                        index,
                        "cycle_stand" if classes == ("bicycle",) else "parallel",
                        footprint,
                        lane["record"].lane_ordinal,
                        access[0],
                        access[1],
                        classes,
                    )
                )
                self.space_ordinal += 1
                along = high


def build_records() -> tuple[object, ...]:
    builder = Builder()
    for name in NODES:
        builder.node(name)
    spokes = [("N", 0), ("E", 1), ("S", 2), ("W", 3)]
    for ordinal, (arm, turns) in enumerate(spokes):
        centreline = ((0, 0), clockwise((0, ARM_MM), turns))
        builder.segment(ordinal, "C", arm, centreline, turns, True)
        forward = tuple(
            clockwise(point, turns)
            for point in ((LANE_OFFSET_MM, STOP_MM), (LANE_OFFSET_MM, ARM_MM - STOP_MM))
        )
        backward = tuple(
            clockwise(point, turns)
            for point in ((-LANE_OFFSET_MM, ARM_MM - STOP_MM), (-LANE_OFFSET_MM, STOP_MM))
        )
        builder.lane(ordinal, "with_segment", forward)
        builder.lane(ordinal, "against_segment", backward)
    ring = [("N", "E", 0), ("E", "S", 1), ("S", "W", 2), ("W", "N", 3)]
    for index, (start, end, turns) in enumerate(ring):
        ordinal = 4 + index
        centreline = tuple(clockwise(point, turns) for point in ring_template(0))
        builder.segment(ordinal, start, end, centreline, turns, False)
        forward = tuple(
            clockwise(point, turns)
            for point in trim(ring_template(LANE_OFFSET_MM), STOP_MM, STOP_MM)
        )
        backward = tuple(
            clockwise(point, turns)
            for point in reverse(trim(ring_template(-LANE_OFFSET_MM), STOP_MM, STOP_MM))
        )
        builder.lane(ordinal, "with_segment", forward)
        builder.lane(ordinal, "against_segment", backward)
    for name in NODES:
        builder.junction(name)
        builder.connect(name)
    builder.signals()
    for ordinal, (_, turns) in enumerate(spokes):
        builder.parking(ordinal, turns)
    return tuple(builder.records)
