"""A SYNTHETIC road network for the traffic tests, built only from city grammar version 2 records.

This is test data, not a generated city and not a generator. Every dimension below is a fixture
value chosen so the network exercises the simulation: a signalised four-way centre, two
two-way-stop and two all-way-stop T junctions on a ring road with rounded corners, a pedestrian
crossing on every leg, a mid-block crossing halfway along each spoke, and on both sides of every
spoke a parking lane with a bus layover, general, loading and accessible bays, and a group of two
cycle stands on the footway that holds four bicycles. Identities follow the city's rule
(:func:`exulanica.grammar.subjects.subject_identity`) under this fixture's own city identity.

Everything is integer arithmetic. Rotations are exact quarter turns, and every arc uses the
rational circle parametrisation ``((1 - t^2) / (1 + t^2), 2t / (1 + t^2))`` so every point is
computed the same way on every machine.

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

import uuid
from functools import cache, cmp_to_key
from typing import Final

from exulanica.canonical import round_half_down
from exulanica.grammar.geometry import Extent, polyline_run_length
from exulanica.grammar.grammars.city.common import SIDE_CODES
from exulanica.grammar.grammars.city.districts import DistrictRecord
from exulanica.grammar.grammars.city.roads import (
    JunctionApproachRecord,
    JunctionRecord,
    LaneConnectionRecord,
    LaneRecord,
    ParkingSpaceRecord,
    SignalGroup,
    SignalHead,
    SignalRecord,
)
from exulanica.grammar.grammars.city.streets import (
    CrossingRecord,
    StreetNodeRecord,
    StreetSegmentRecord,
)
from exulanica.grammar.subjects import subject_identity
from exulanica.traffic.catalogs import load_traffic_catalogs

CITY: Final = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.invalid/fixture/traffic"))
HIERARCHY: Final = "local_street"
SPEED_LIMIT_MM_S: Final = 8_333
SIGNAL_PLAN: Final = "fixed_two_phase_60s"

ARM_MM: Final = 100_000
STOP_MM: Final = 20_000
BOX_MM: Final = 15_000
LANE_WIDTH_MM: Final = 3_750
LANE_OFFSET_MM: Final = 1_875
PARKING_LANE_WIDTH_MM: Final = 2_600
PARKING_OUTER_MM: Final = 6_350
KERB_WIDTH_MM: Final = 200
CROSSING_AT_MM: Final = 16_500
CROSSING_WIDTH_MM: Final = 3_000
#: The mid-block crossing on each spoke, measured from the centre: the middle of the gap left
#: in the parking row, so no parking access runs across the crosswalk.
MIDBLOCK_AT_MM: Final = 52_750
RING_STRAIGHT_MM: Final = 30_000
RING_RADIUS_MM: Final = 70_000
ARC_STEPS: Final = 12

#: ``(length, parking kind)`` along each spoke side's parking lane, from 22 m out from the centre.
#: No kind is a gap with no bay, where the mid-block crossing is.
PARKING_LAYOUT: Final = (
    (14_000, "bus_layover"),
    (6_700, "general"),
    (6_700, "general"),
    (6_700, ""),
    (6_700, "loading"),
    (6_700, "accessible"),
)
PARKING_START_MM: Final = 22_000
#: The footway stand group after the parking row: its stretch along the spoke, its place across
#: the footway, and the bicycles its two stands hold (the city's cycle-stand entry holds two each).
STANDS_ALONG_MM: Final = (69_500, 72_500)
STANDS_ACROSS_MM: Final = (7_150, 7_950)
STANDS: Final = 2
STAND_CAPACITY: Final = 4

NODES: Final = {"C": 0, "N": 1, "E": 2, "S": 3, "W": 4}
POSITIONS: Final = {
    "C": (0, 0),
    "N": (0, ARM_MM),
    "E": (ARM_MM, 0),
    "S": (0, -ARM_MM),
    "W": (-ARM_MM, 0),
}
#: Junction control by node. The centre is signalised.
CONTROLS: Final = {
    "C": "signalised",
    "N": "priority_two_way_stop",
    "S": "priority_two_way_stop",
    "E": "all_way_stop",
    "W": "all_way_stop",
}

Point = tuple[int, int]


def identity(kind: str, owner: str, ordinal: int) -> str:
    return subject_identity(
        grammar_id="city",
        root_identity=CITY,
        subject_kind=kind,
        owner_identity=owner,
        ordinal=ordinal,
    )


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


def raised(points) -> tuple[tuple[int, int, int], ...]:
    return tuple((x, y, 0) for x, y in points)


def box(points) -> Extent:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return Extent(min(xs), min(ys), 0, max(xs), max(ys), 0)


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


def ring_template(offset: int) -> tuple[Point, ...]:
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


def leaving_direction(centreline: tuple[Point, ...], at_start: bool) -> Point:
    """The direction a segment leaves its start node, or leaves its end node going backward."""
    a, b = (centreline[0], centreline[1]) if at_start else (centreline[-1], centreline[-2])
    return (b[0] - a[0], b[1] - a[1])


def sort_counter_clockwise(items: list[tuple[Point, str]]) -> list[str]:
    """Identities ordered by their leaving direction, counter-clockwise from +x, exactly."""

    def half(direction: Point) -> int:
        x, y = direction
        return 0 if (y > 0 or (y == 0 and x > 0)) else 1

    def compare(first: tuple[Point, str], second: tuple[Point, str]) -> int:
        a, b = first[0], second[0]
        if half(a) != half(b):
            return half(a) - half(b)
        turn = a[0] * b[1] - a[1] * b[0]
        return -1 if turn > 0 else 1 if turn < 0 else 0

    return [leg for _, leg in sorted(items, key=cmp_to_key(compare))]


class Builder:
    def __init__(self) -> None:
        self.district = identity("district", CITY, 0)
        self.records: list[object] = [
            DistrictRecord(
                self.district,
                0,
                (
                    (-150_000, -150_000),
                    (150_000, -150_000),
                    (150_000, 150_000),
                    (-150_000, 150_000),
                ),
                "right",
                Extent(-150_000, -150_000, 0, 150_000, 150_000, 0),
            )
        ]
        self.plan_sha256 = load_traffic_catalogs().file_digest("signal-plan")
        self.nodes = {
            name: identity("street_node", CITY, ordinal) for name, ordinal in NODES.items()
        }
        self.segments: dict[int, dict] = {}
        self.inbound: dict[str, list[dict]] = {name: [] for name in NODES}
        self.outbound: dict[str, list[dict]] = {name: [] for name in NODES}
        self.connections: dict[str, list[tuple[str, dict, str]]] = {name: [] for name in NODES}
        self.crossings: dict[str, list[tuple[str, Point]]] = {name: [] for name in NODES}
        self.legs: dict[str, list[tuple[Point, str]]] = {name: [] for name in NODES}

    def node(self, name: str) -> None:
        x, y = POSITIONS[name]
        self.records.append(
            StreetNodeRecord(self.nodes[name], NODES[name], x, y, 0, Extent(x, y, 0, x, y, 0))
        )

    def segment(self, ordinal: int, start: str, end: str, centreline: tuple[Point, ...]) -> str:
        segment_id = identity("street_segment", CITY, ordinal)
        points = raised(centreline)
        length = polyline_run_length(points)
        self.records.append(
            StreetSegmentRecord(
                identity=segment_id,
                segment_ordinal=ordinal,
                street_identity=identity("street", CITY, ordinal),
                district_identity=self.district,
                start_node_identity=self.nodes[start],
                end_node_identity=self.nodes[end],
                centreline_mm=points,
                length_mm=length,
                hierarchy=HIERARCHY,
                carriageway_width_mm=2 * PARKING_OUTER_MM,
                camber_millionths=20_000,
                speed_limit_mm_s=SPEED_LIMIT_MM_S,
                extent=box(points),
            )
        )
        self.segments[ordinal] = {
            "identity": segment_id,
            "start": start,
            "end": end,
            "centreline": centreline,
            "length": length,
            "lanes": {},
        }
        self.legs[start].append((leaving_direction(centreline, True), segment_id))
        self.legs[end].append((leaving_direction(centreline, False), segment_id))
        return segment_id

    def crossings_on(self, ordinal: int, spoke: bool) -> None:
        info = self.segments[ordinal]
        length = info["length"]
        offsets = (
            (CROSSING_AT_MM, MIDBLOCK_AT_MM, length - CROSSING_AT_MM)
            if spoke
            else (CROSSING_AT_MM, length - CROSSING_AT_MM)
        )
        centreline = info["centreline"]
        for index, offset in enumerate(offsets):
            # The first and last crossings are junction legs; one between them is mid-block.
            node_name = (
                info["start"] if index == 0 else info["end"] if index == len(offsets) - 1 else None
            )
            a, b = (centreline[0], centreline[1]) if index < len(offsets) - 1 else centreline[-2:]
            axis = ((b[0] > a[0]) - (b[0] < a[0]), (b[1] > a[1]) - (b[1] < a[1]))
            centre = self.point_along(centreline, offset)
            across = right_of(axis)
            line = (
                add(centre, scale(across, -PARKING_OUTER_MM)),
                add(centre, scale(across, PARKING_OUTER_MM)),
            )
            crossing_id = identity("crossing", info["identity"], index)
            signalised = node_name == "C"
            self.records.append(
                CrossingRecord(
                    crossing_id,
                    info["identity"],
                    index,
                    "signalised" if signalised else "zebra",
                    offset,
                    CROSSING_WIDTH_MM,
                    raised(line),
                    6,
                    (self.signal_identity(),) if signalised else (),
                    box(
                        [
                            add(line[0], scale(axis, -CROSSING_WIDTH_MM // 2)),
                            add(line[1], scale(axis, CROSSING_WIDTH_MM // 2)),
                        ]
                    ),
                )
            )
            if node_name is not None:
                self.crossings[node_name].append((crossing_id, axis))

    @staticmethod
    def point_along(points: tuple[Point, ...], offset: int) -> Point:
        from exulanica.traffic.geometry import Polyline

        return Polyline.of(points).point_at(offset)

    def signal_identity(self) -> str:
        return identity("signal", identity("junction", self.nodes["C"], 0), 0)

    def lane(
        self,
        ordinal: int,
        index: int,
        use: str,
        direction: str,
        centreline: tuple[Point, ...],
        offsets: tuple[int, int],
        markings: tuple[str, str],
    ) -> dict:
        info = self.segments[ordinal]
        lane_id = identity("lane", info["identity"], index)
        traffic = direction != "none"
        points = raised(centreline)
        self.records.append(
            LaneRecord(
                identity=lane_id,
                segment_identity=info["identity"],
                lane_index=index,
                lane_use=use,
                direction=direction,
                width_mm=LANE_WIDTH_MM if traffic else PARKING_LANE_WIDTH_MM,
                centreline_mm=points,
                start_offset_mm=offsets[0],
                end_offset_mm=offsets[1],
                turns=("left", "straight", "right") if traffic else (),
                left_marking=markings[0],
                right_marking=markings[1],
                extent=box(points),
            )
        )
        lane = {"identity": lane_id, "segment": ordinal, "direction": direction}
        info["lanes"][index] = lane
        if traffic:
            start, end = (
                (info["start"], info["end"])
                if direction == "forward"
                else (info["end"], info["start"])
            )
            lane.update(
                {
                    "centreline": centreline,
                    "in_axis": self.axis(centreline[-2], centreline[-1]),
                    "out_axis": self.axis(centreline[0], centreline[1]),
                }
            )
            self.inbound[end].append(lane)
            self.outbound[start].append(lane)
        return lane

    @staticmethod
    def axis(a: Point, b: Point) -> Point:
        return ((b[0] > a[0]) - (b[0] < a[0]), (b[1] > a[1]) - (b[1] < a[1]))

    def connect(self, name: str) -> None:
        position = POSITIONS[name]
        junction_id = identity("junction", self.nodes[name], 0)
        for source in self.inbound[name]:
            d_in = source["in_axis"]
            for target in self.outbound[name]:
                d_out = target["out_axis"]
                if d_out == (-d_in[0], -d_in[1]):
                    continue
                end = source["centreline"][-1]
                start = target["centreline"][0]
                if d_out == d_in:
                    movement, path = "straight", (end, start)
                else:
                    movement = "right" if d_out == right_of(d_in) else "left"
                    radius = (
                        BOX_MM - LANE_OFFSET_MM if movement == "right" else BOX_MM + LANE_OFFSET_MM
                    )
                    pre = add(position, scale(d_in, -BOX_MM), scale(right_of(d_in), LANE_OFFSET_MM))
                    post = add(
                        position, scale(d_out, BOX_MM), scale(right_of(d_out), LANE_OFFSET_MM)
                    )
                    centre = add(position, scale(d_in, -BOX_MM), scale(d_out, BOX_MM))
                    arc = quarter_arc(centre, (-d_out[0], -d_out[1]), d_in, radius)
                    assert arc[0] == pre and arc[-1] == post, (name, movement)
                    path = dedupe([end, *arc, start])
                ordinal = len(self.connections[name])
                connection_id = identity("lane_connection", junction_id, ordinal)
                points = raised(path)
                self.records.append(
                    LaneConnectionRecord(
                        connection_id,
                        junction_id,
                        ordinal,
                        source["identity"],
                        target["identity"],
                        movement,
                        points,
                        box(points),
                    )
                )
                self.connections[name].append((connection_id, source, movement))

    def junction(self, name: str) -> None:
        junction_id = identity("junction", self.nodes[name], 0)
        control = CONTROLS[name]
        legs = sort_counter_clockwise(self.legs[name])
        x, y = POSITIONS[name]
        self.records.append(
            JunctionRecord(
                junction_id,
                self.nodes[name],
                control,
                tuple(legs),
                (self.signal_identity(),) if control == "signalised" else (),
                Extent(x - BOX_MM, y - BOX_MM, 0, x + BOX_MM, y + BOX_MM, 0),
            )
        )
        spokes = {self.segments[ordinal]["identity"] for ordinal in range(4)}
        for ordinal, segment_id in enumerate(legs):
            if control == "signalised":
                approach, rank = "signal", 0
            elif control == "all_way_stop":
                approach, rank = "stop", 0
            elif segment_id in spokes:
                approach, rank = "stop", 1
            else:
                approach, rank = "priority", 0
            self.records.append(
                JunctionApproachRecord(
                    identity("junction_approach", junction_id, ordinal),
                    junction_id,
                    segment_id,
                    ordinal,
                    approach,
                    rank,
                )
            )

    def signal(self) -> None:
        junction_id = identity("junction", self.nodes["C"], 0)
        groups: dict[str, list[str]] = {"phase_a": [], "phase_b": [], "walk_a": [], "walk_b": []}
        for connection_id, source, _ in self.connections["C"]:
            north_south = source["in_axis"][0] == 0
            groups["phase_a" if north_south else "phase_b"].append(connection_id)
        for crossing_id, leg_axis in self.crossings["C"]:
            # A crossing on an east-west leg is walked north-south, alongside phase a.
            groups["walk_a" if leg_axis[1] == 0 else "walk_b"].append(crossing_id)
        curb = identity("curb_edge", self.segments[0]["identity"], SIDE_CODES["right"])
        heads = []
        for ordinal, group in enumerate(("phase_a", "phase_b", "walk_a", "walk_b")):
            heads.append(
                SignalHead(identity("street_furniture", curb, ordinal), sorted(groups[group])[0])
            )
        self.records.append(
            SignalRecord(
                identity=self.signal_identity(),
                controls_identity=junction_id,
                plan=SIGNAL_PLAN,
                plan_catalog_sha256=self.plan_sha256,
                offset_ms=0,
                groups=tuple(
                    SignalGroup(group, tuple(sorted(members)), ())
                    if group.startswith("phase")
                    else SignalGroup(group, (), tuple(sorted(members)))
                    for group, members in groups.items()
                ),
                heads=tuple(heads),
            )
        )

    def parking(self, ordinal: int, turns: int) -> None:
        info = self.segments[ordinal]
        segment_id = info["identity"]
        for side, parking_index, traffic_index, outer in (
            ("right", 3, 2, 1),
            ("left", 0, 1, -1),
        ):
            curb = identity("curb_edge", segment_id, SIDE_CODES[side])
            parking_lane = info["lanes"][parking_index]["identity"]
            access_lane = info["lanes"][traffic_index]["identity"]
            along = PARKING_START_MM
            space_ordinal = 0
            for length, kind in PARKING_LAYOUT:
                low, high = along, along + length
                along = high
                if not kind:
                    continue
                inner, far = LANE_WIDTH_MM * outer, PARKING_OUTER_MM * outer
                corners = [(inner, low), (far, low), (far, high), (inner, high)]
                if outer < 0:
                    corners = [(far, low), (inner, low), (inner, high), (far, high)]
                footprint = tuple(clockwise(corner, turns) for corner in corners)
                self.records.append(
                    ParkingSpaceRecord(
                        identity("parking_space", curb, space_ordinal),
                        curb,
                        segment_id,
                        space_ordinal,
                        kind,
                        "carriageway",
                        1,
                        footprint,
                        (parking_lane,),
                        access_lane,
                        low,
                        high,
                        (),
                        box(footprint),
                    )
                )
                space_ordinal += 1
            near, far = STANDS_ACROSS_MM[0] * outer, STANDS_ACROSS_MM[1] * outer
            low, high = STANDS_ALONG_MM
            corners = [(near, low), (far, low), (far, high), (near, high)]
            if outer < 0:
                corners = [(far, low), (near, low), (near, high), (far, high)]
            footprint = tuple(clockwise(corner, turns) for corner in corners)
            self.records.append(
                ParkingSpaceRecord(
                    identity("parking_space", curb, space_ordinal),
                    curb,
                    segment_id,
                    space_ordinal,
                    "cycle_stand",
                    "footway",
                    STAND_CAPACITY,
                    footprint,
                    (),
                    access_lane,
                    low,
                    high,
                    tuple(
                        identity("street_furniture", curb, 10 + stand) for stand in range(STANDS)
                    ),
                    box(footprint),
                )
            )


@cache
def build_records() -> tuple[object, ...]:
    builder = Builder()
    for name in NODES:
        builder.node(name)
    spokes = [("N", 0), ("E", 1), ("S", 2), ("W", 3)]
    for ordinal, (arm, turns) in enumerate(spokes):
        centreline = ((0, 0), clockwise((0, ARM_MM), turns))
        builder.segment(ordinal, "C", arm, centreline)
        rotate = lambda points, turns=turns: tuple(clockwise(point, turns) for point in points)  # noqa: E731
        builder.lane(
            ordinal,
            0,
            "parking",
            "none",
            rotate(
                (
                    (-(LANE_WIDTH_MM + PARKING_LANE_WIDTH_MM // 2), STOP_MM),
                    (-(LANE_WIDTH_MM + PARKING_LANE_WIDTH_MM // 2), ARM_MM - STOP_MM),
                )
            ),
            (STOP_MM, ARM_MM - STOP_MM),
            ("none", "solid"),
        )
        builder.lane(
            ordinal,
            1,
            "general",
            "backward",
            rotate(((-LANE_OFFSET_MM, ARM_MM - STOP_MM), (-LANE_OFFSET_MM, STOP_MM))),
            (ARM_MM - STOP_MM, STOP_MM),
            ("solid", "dashed"),
        )
        builder.lane(
            ordinal,
            2,
            "general",
            "forward",
            rotate(((LANE_OFFSET_MM, STOP_MM), (LANE_OFFSET_MM, ARM_MM - STOP_MM))),
            (STOP_MM, ARM_MM - STOP_MM),
            ("dashed", "solid"),
        )
        builder.lane(
            ordinal,
            3,
            "parking",
            "none",
            rotate(
                (
                    (LANE_WIDTH_MM + PARKING_LANE_WIDTH_MM // 2, STOP_MM),
                    (LANE_WIDTH_MM + PARKING_LANE_WIDTH_MM // 2, ARM_MM - STOP_MM),
                )
            ),
            (STOP_MM, ARM_MM - STOP_MM),
            ("solid", "none"),
        )
    ring = [("N", "E", 0), ("E", "S", 1), ("S", "W", 2), ("W", "N", 3)]
    for index, (start, end, turns) in enumerate(ring):
        ordinal = 4 + index
        centreline = tuple(clockwise(point, turns) for point in ring_template(0))
        builder.segment(ordinal, start, end, centreline)
        length = builder.segments[ordinal]["length"]
        backward = tuple(
            clockwise(point, turns)
            for point in reversed(trim(ring_template(-LANE_OFFSET_MM), STOP_MM, STOP_MM))
        )
        forward = tuple(
            clockwise(point, turns)
            for point in trim(ring_template(LANE_OFFSET_MM), STOP_MM, STOP_MM)
        )
        builder.lane(
            ordinal,
            0,
            "general",
            "backward",
            backward,
            (length - STOP_MM, STOP_MM),
            ("none", "dashed"),
        )
        builder.lane(
            ordinal,
            1,
            "general",
            "forward",
            forward,
            (STOP_MM, length - STOP_MM),
            ("dashed", "none"),
        )
    for ordinal in range(8):
        builder.crossings_on(ordinal, ordinal < 4)
    for name in NODES:
        builder.junction(name)
        builder.connect(name)
    builder.signal()
    for ordinal, (_, turns) in enumerate(spokes):
        builder.parking(ordinal, turns)
    return tuple(builder.records)
