"""Where traffic reads the city: city road records in, a :class:`RoadInput` out, or a refusal.

The records are the city grammar's street and road kinds: the district (for its driving side),
street nodes and segments, lanes, junctions and their approaches, lane connections, signals,
crossings and parking spaces. Any other city record is ignored, because nothing in it moves a
vehicle; anything that is not a city record is refused.

**What is checked here.** Each record against its own shape (fields and rules), each identity
against the city's derivation from its owner and ordinal, and every reference traffic follows.
The network compiler checks everything geometric and everything about right of way.

**What is mapped here.** A lane's ``lane_use`` through ``lane-use-access`` to the classes it
carries; a lane that carries none must have direction ``none`` and is left out, and a lane that
carries some must run ``forward`` or ``backward``. A space's ``parking_kind`` through
``parking-kind-access``. A signal's ``plan`` must be a plan of the signal-plan catalog whose file
bytes have exactly the ``plan_catalog_sha256`` the record names, and its ``offset_ms`` must be
whole seconds. A crossing is ``signalised`` exactly when it names a signal.

**Positions.** A crossing's centre is the point on its segment's centreline at ``offset_mm``,
walking pieces by the city's run length (the floor of each piece's true length). A parking
space's access stretch, stated along the segment centreline, becomes positions on its access
lane: each end is the segment point at that offset projected onto the nearest piece of the lane.
On the straight pieces a stretch is required to lie on, that is exact.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from itertools import pairwise
from typing import Any, Final

from exulanica.canonical import round_half_down
from exulanica.errors import ExulanicaError
from exulanica.grammar import shapes
from exulanica.grammar.geometry import integer_sqrt
from exulanica.grammar.grammars.city import CITY_SHAPES_BY_TYPE
from exulanica.grammar.grammars.city.districts import DistrictRecord
from exulanica.grammar.grammars.city.roads import (
    JunctionApproachRecord,
    JunctionRecord,
    LaneConnectionRecord,
    LaneRecord,
    ParkingSpaceRecord,
    SignalRecord,
)
from exulanica.grammar.grammars.city.streets import (
    CrossingRecord,
    StreetNodeRecord,
    StreetSegmentRecord,
)
from exulanica.traffic.catalogs import AccessMapping, TrafficCatalogs
from exulanica.traffic.errors import TrafficCatalogError, UnsupportedNetworkError
from exulanica.traffic.geometry import Point, Polyline, dot
from exulanica.traffic.road_input import (
    ApproachInput,
    ConnectionInput,
    CrossingInput,
    JunctionInput,
    LaneInput,
    NodeInput,
    ParkingInput,
    RoadInput,
    SegmentInput,
    SignalGroupInput,
    SignalInput,
)

__all__ = ["CITY_GRAMMAR_ID", "READ_KINDS", "road_input_from_city"]

CITY_GRAMMAR_ID: Final = "city"
#: The city record kinds traffic reads. Every other city kind is ignored.
READ_KINDS: Final = (
    DistrictRecord,
    StreetNodeRecord,
    StreetSegmentRecord,
    LaneRecord,
    JunctionRecord,
    JunctionApproachRecord,
    LaneConnectionRecord,
    SignalRecord,
    CrossingRecord,
    ParkingSpaceRecord,
)
_MS_PER_SECOND: Final = 1000


def _refuse(message: str) -> UnsupportedNetworkError:
    return UnsupportedNetworkError(message)


def _plan_points(what: str, points: Iterable[tuple[int, ...]]) -> tuple[Point, ...]:
    plan = tuple((point[0], point[1]) for point in points)
    for first, second in pairwise(plan):
        if first == second:
            raise _refuse(f"{what} has two points at one plan position")
    return plan


def _run_point(centreline: tuple[Point, ...], offset: int, what: str) -> Point:
    """The point at ``offset`` along ``centreline``, by the city's floored run lengths."""
    walked = 0
    for first, second in pairwise(centreline):
        dx, dy = second[0] - first[0], second[1] - first[1]
        run = integer_sqrt(dx * dx + dy * dy)
        if offset <= walked + run:
            along = offset - walked
            return (
                first[0] + round_half_down(dx * along, run),
                first[1] + round_half_down(dy * along, run),
            )
        walked += run
    raise _refuse(f"{what} offset {offset} is beyond its segment's length {walked}")


def _position_on(line: Polyline, point: Point) -> int:
    """The position on ``line`` of the nearest point to ``point``, with the line's own lengths."""
    best: tuple[int, int, int] | None = None
    for index in range(line.piece_count):
        a, b = line.piece(index)
        direction = (b[0] - a[0], b[1] - a[1])
        offset = (point[0] - a[0], point[1] - a[1])
        squared = dot(direction, direction)
        along = min(max(dot(offset, direction), 0), squared)
        # The squared distance to the nearest point, times ``squared``, is an exact integer.
        scaled = squared * dot(offset, offset) - 2 * along * dot(offset, direction) + along * along
        if best is None or scaled * best[1] < best[0] * squared:
            piece_length = line.offsets[index + 1] - line.offsets[index]
            position = line.offsets[index] + round_half_down(along * piece_length, squared)
            best = (scaled, squared, position)
    assert best is not None
    return best[2]


def _mapping(lookup: Callable[[str], AccessMapping], key: str, what: str) -> AccessMapping:
    try:
        return lookup(key)
    except TrafficCatalogError as error:
        raise _refuse(f"{what}: {error}") from error


def road_input_from_city(
    records: Iterable[object], catalogs: TrafficCatalogs, *, city_identity: str
) -> RoadInput:
    """Validate, resolve and map the city's road records, or raise ``UnsupportedNetworkError``."""
    read: list[Any] = []
    for record in records:
        shape = CITY_SHAPES_BY_TYPE.get(type(record))
        if shape is None:
            raise _refuse(f"traffic reads city records, not {type(record).__name__}")
        if not isinstance(record, READ_KINDS):
            continue
        try:
            shapes.validate_record(record, shape)
        except ExulanicaError as error:
            raise _refuse(f"{shape.name} {record.identity}: {error}") from error
        read.append(record)
    try:
        shapes.check_identities(
            read, CITY_SHAPES_BY_TYPE, grammar_id=CITY_GRAMMAR_ID, root_identity=city_identity
        )
    except ExulanicaError as error:
        raise _refuse(str(error)) from error
    stated: dict[str, Any] = {}
    for record in read:
        if record.identity in stated:
            raise _refuse(f"identity {record.identity} is stated by two records")
        stated[record.identity] = record

    def named(identity: str, kind: type, by: str) -> Any:
        found = stated.get(identity)
        if type(found) is not kind:
            raise _refuse(f"{by} names {identity}, which is no {kind.RECORD_KIND} record here")
        return found

    def of(kind: type) -> list[Any]:
        return sorted(
            (record for record in read if type(record) is kind), key=lambda item: item.identity
        )

    segments = of(StreetSegmentRecord)
    if not segments:
        raise _refuse("the records hold no street segment")
    sides = {
        named(segment.district_identity, DistrictRecord, f"segment {segment.identity}").driving_side
        for segment in segments
    }
    if len(sides) != 1:
        raise _refuse(f"the segments' districts drive on different sides: {sorted(sides)}")
    [driving_side] = sides

    nodes = tuple(
        NodeInput(node.identity, node.node_ordinal, (node.x_mm, node.y_mm))
        for node in of(StreetNodeRecord)
    )
    segment_inputs = []
    for segment in segments:
        for node in (segment.start_node_identity, segment.end_node_identity):
            named(node, StreetNodeRecord, f"segment {segment.identity}")
        segment_inputs.append(
            SegmentInput(
                identity=segment.identity,
                ordinal=segment.segment_ordinal,
                start_node=segment.start_node_identity,
                end_node=segment.end_node_identity,
                centreline=_plan_points(f"segment {segment.identity}", segment.centreline_mm),
                speed_limit_mm_per_s=segment.speed_limit_mm_s,
            )
        )
    centrelines = {item.identity: item.centreline for item in segment_inputs}

    lanes: dict[str, LaneInput] = {}
    for lane in of(LaneRecord):
        named(lane.segment_identity, StreetSegmentRecord, f"lane {lane.identity}")
        use = _mapping(catalogs.lane_use, lane.lane_use, f"lane {lane.identity}")
        if not use.classes:
            if lane.direction != "none":
                raise _refuse(
                    f"lane {lane.identity} is a {lane.lane_use} lane, which carries no traffic, "
                    f"yet runs {lane.direction}"
                )
            continue
        if lane.direction == "none":
            raise _refuse(
                f"lane {lane.identity} is a {lane.lane_use} lane, which carries traffic, "
                "and has no direction"
            )
        lanes[lane.identity] = LaneInput(
            identity=lane.identity,
            segment=lane.segment_identity,
            lane_index=lane.lane_index,
            direction=lane.direction,
            width_mm=lane.width_mm,
            centreline=_plan_points(f"lane {lane.identity}", lane.centreline_mm),
            classes=use.classes,
            turns=lane.turns,
            lane_use=lane.lane_use,
        )

    junctions = []
    for junction in of(JunctionRecord):
        named(junction.node_identity, StreetNodeRecord, f"junction {junction.identity}")
        try:
            catalogs.policy(junction.control)
        except TrafficCatalogError as error:
            raise _refuse(f"junction {junction.identity}: {error}") from error
        for signal in junction.signal_identity:
            if named(signal, SignalRecord, f"junction {junction.identity}").controls_identity != (
                junction.identity
            ):
                raise _refuse(
                    f"junction {junction.identity} names signal {signal}, which controls another"
                )
        junctions.append(JunctionInput(junction.identity, junction.node_identity, junction.control))

    approaches = []
    for approach in of(JunctionApproachRecord):
        named(approach.junction_identity, JunctionRecord, f"approach {approach.identity}")
        named(approach.segment_identity, StreetSegmentRecord, f"approach {approach.identity}")
        approaches.append(
            ApproachInput(
                identity=approach.identity,
                junction=approach.junction_identity,
                segment=approach.segment_identity,
                ordinal=approach.approach_ordinal,
                control=approach.control,
                rank=approach.priority_rank,
            )
        )

    connections = []
    for connection in of(LaneConnectionRecord):
        named(connection.junction_identity, JunctionRecord, f"connection {connection.identity}")
        for lane_identity in (connection.from_lane_identity, connection.to_lane_identity):
            named(lane_identity, LaneRecord, f"connection {connection.identity}")
            if lane_identity not in lanes:
                raise _refuse(
                    f"connection {connection.identity} joins lane {lane_identity}, "
                    "which carries no traffic"
                )
        connections.append(
            ConnectionInput(
                identity=connection.identity,
                junction=connection.junction_identity,
                ordinal=connection.connection_ordinal,
                from_lane=connection.from_lane_identity,
                to_lane=connection.to_lane_identity,
                turn=connection.movement,
                path=_plan_points(f"connection {connection.identity}", connection.path_mm),
            )
        )

    plan_bytes = catalogs.file_digest("signal-plan")
    signals = []
    for signal in of(SignalRecord):
        controlled = stated.get(signal.controls_identity)
        if type(controlled) is CrossingRecord:
            raise _refuse(
                f"signal {signal.identity} controls a mid-block crossing; "
                "traffic v1 has no mid-block signals"
            )
        junction = named(signal.controls_identity, JunctionRecord, f"signal {signal.identity}")
        if junction.signal_identity != (signal.identity,):
            raise _refuse(
                f"signal {signal.identity} controls junction {junction.identity}, "
                "which does not name it"
            )
        try:
            catalogs.plan(signal.plan)
        except TrafficCatalogError as error:
            raise _refuse(f"signal {signal.identity}: {error}") from error
        if signal.plan_catalog_sha256 != plan_bytes:
            raise _refuse(
                f"signal {signal.identity} names signal-plan catalog bytes "
                f"{signal.plan_catalog_sha256}; traffic holds {plan_bytes}"
            )
        if signal.offset_ms % _MS_PER_SECOND:
            raise _refuse(
                f"signal {signal.identity} offset {signal.offset_ms} ms is not whole seconds"
            )
        groups = []
        for group in signal.groups:
            for identity in group.connection_identities:
                named(identity, LaneConnectionRecord, f"signal {signal.identity} {group.group}")
            for identity in group.crossing_identities:
                named(identity, CrossingRecord, f"signal {signal.identity} {group.group}")
            groups.append(
                SignalGroupInput(
                    group.group, group.connection_identities, group.crossing_identities
                )
            )
        signals.append(
            SignalInput(
                identity=signal.identity,
                junction=signal.controls_identity,
                plan=signal.plan,
                offset_s=signal.offset_ms // _MS_PER_SECOND,
                groups=tuple(groups),
            )
        )

    crossings = []
    for crossing in of(CrossingRecord):
        named(crossing.segment_identity, StreetSegmentRecord, f"crossing {crossing.identity}")
        for signal in crossing.signal_identity:
            named(signal, SignalRecord, f"crossing {crossing.identity}")
        a, b = _plan_points(f"crossing {crossing.identity}", crossing.line_mm)
        crossings.append(
            CrossingInput(
                identity=crossing.identity,
                segment=crossing.segment_identity,
                ordinal=crossing.crossing_ordinal,
                offset_mm=crossing.offset_mm,
                width_mm=crossing.width_mm,
                line=(a, b),
                centre=_run_point(
                    centrelines[crossing.segment_identity],
                    crossing.offset_mm,
                    f"crossing {crossing.identity}",
                ),
                control="signalised" if crossing.signal_identity else "marked_priority",
                signal=crossing.signal_identity[0] if crossing.signal_identity else "",
            )
        )

    spaces = []
    for space in of(ParkingSpaceRecord):
        named(space.segment_identity, StreetSegmentRecord, f"parking space {space.identity}")
        named(space.access_lane_identity, LaneRecord, f"parking space {space.identity}")
        kind = _mapping(catalogs.parking_kind, space.parking_kind, f"space {space.identity}")
        access = lanes.get(space.access_lane_identity)
        if access is None:
            raise _refuse(
                f"parking space {space.identity} is reached from lane "
                f"{space.access_lane_identity}, which carries no traffic"
            )
        line = Polyline.of(access.centreline)
        centreline = centrelines[space.segment_identity]
        ends = sorted(
            _position_on(line, _run_point(centreline, offset, f"parking space {space.identity}"))
            for offset in (space.access_start_mm, space.access_end_mm)
        )
        spaces.append(
            ParkingInput(
                identity=space.identity,
                segment=space.segment_identity,
                kind=space.parking_kind,
                placement=space.placement,
                capacity=space.capacity,
                footprint=tuple(space.footprint_mm),
                classes=kind.classes,
                access_lane=space.access_lane_identity,
                access_start_mm=ends[0],
                access_end_mm=ends[1],
            )
        )

    return RoadInput(
        city=city_identity,
        driving_side=driving_side,
        nodes=nodes,
        segments=tuple(segment_inputs),
        lanes=tuple(lanes[identity] for identity in sorted(lanes)),
        junctions=tuple(junctions),
        approaches=tuple(approaches),
        connections=tuple(connections),
        signals=tuple(signals),
        crossings=tuple(crossings),
        spaces=tuple(spaces),
    )
