"""Road records a city's streets imply and write none of: lane connections and parking spaces.

The city grammar's streets stage lays lanes, junctions and their approaches and crossings, and
declares lane connections, signals and parking spaces as kinds it writes none of
(``docs/grammar-package.md``, section 7). A network needs connections to drive and spaces for its
fleet to start in, so this module derives both by rule, from the records a city states, the city's
own catalogs and traffic's ``road-derivation`` catalog, and hands them to
:func:`~exulanica.traffic.city_roads.road_input_from_city` beside the city's own. It derives no
signal: a junction keeps the control the city gives it.

**What is derived, and what is not.** A junction the city states any connection for gets none
derived, and a curb the city states any parking space on gets none: the city's statement stands.
Everything derived is a city record by shape and identity, owned as the city owns that kind (a
connection by its junction, a space by its curb), and synthetic: no record here is evidence of a
street.

**Lane connections.** At every junction, every traffic lane flowing in makes each movement its
``turns`` permits into the one traffic lane leaving by the leg that movement reaches: straight on,
a quarter turn right or a quarter turn left, never a u-turn. v1 derives only where the legs meet
along the plan axes, which is every junction the city's streets stage lays, and refuses another by
name, as it refuses a leg that has no lane, or more than one, leaving for a movement a lane
permits. A straight connection is the chord from the stop line to the lane's start. A turn runs
straight from the stop line to where a tangent arc begins, round the fullest arc the corner admits
(its radius is the nearer lane end's distance to the corner) and straight again to the lane's
start; the arc is drawn with the catalog's chord count by the rational parametrisation. Its height
runs from the stop line's to the lane start's.

**Where a space may be.** A space is laid only on an access lane of the largest set of paths a
class its kind admits can drive round, so a vehicle can both reach it and leave it: a lane that
starts or ends where the records stop is off it. The rest is read from the network traffic
compiles from the city and its derived connections.

**Kerbside bays.** Along every lane of the catalog's bay lane use, bays of the catalog's bay
parking kind stand end to end, each the longest the city's parking-kind catalog admits for that
kind and as wide as the lane, reached from the traffic lane beside it: outside the access lane's
junction region and conflict zones, the catalog's crossing clearance from every crossing band on
it, and its stop-line clearance before the junction the lane runs to. A parking lane whose access
lane is off the round network is left out.

**Cycle spaces.** Every stand of the catalog's stand category is one footway space of the stand
parking kind: the kind's shortest footprint centred on the stand, holding the bicycles the
street-furniture catalog says a stand takes, reached across the kind's shortest length from the
traffic lane nearest its curb. A stand whose access stretch meets a junction region, a zone or a
crossing band, or runs off its lane, is left out, and :attr:`DerivedRoads.left_out` says why.

Only this module and :mod:`exulanica.traffic.city_roads` read the city grammar's records.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import round_half_down
from exulanica.grammar.catalogs import Catalog
from exulanica.grammar.geometry import Extent, integer_sqrt
from exulanica.grammar.grammars.city.catalogs import entry_fields
from exulanica.grammar.grammars.city.roads import (
    JunctionRecord,
    LaneConnectionRecord,
    LaneRecord,
    ParkingSpaceRecord,
)
from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord
from exulanica.grammar.grammars.city.streets import CurbEdgeRecord, StreetSegmentRecord
from exulanica.grammar.subjects import subject_identity
from exulanica.traffic.catalogs import RoadDerivation, TrafficCatalogs
from exulanica.traffic.city_roads import CITY_GRAMMAR_ID, road_input_from_city
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.traffic.network import PathSpec, RoadNetwork, compile_network

__all__ = ["DERIVATION_KEY", "DERIVATION_PROFILE", "DerivedRoads", "derive_road_records"]

DERIVATION_PROFILE: Final = "exulanica.traffic-road-derivation/v1"
#: The road-derivation catalog entry for a city's streets.
DERIVATION_KEY: Final = "city_streets"
_PLACEMENT_CARRIAGEWAY: Final = "carriageway"
_PLACEMENT_FOOTWAY: Final = "footway"
_LEFT: Final = "left"
_RIGHT: Final = "right"

Point = tuple[int, int]


@dataclass(frozen=True, slots=True)
class DerivedRoads:
    """The city's records followed by the ones derived from them, and what was left out."""

    records: tuple[object, ...]
    connections: tuple[LaneConnectionRecord, ...]
    spaces: tuple[ParkingSpaceRecord, ...]
    #: ``(record identity, reason)`` for a stand that yields no space.
    left_out: tuple[tuple[str, str], ...]
    derivation: RoadDerivation

    def document(self) -> dict[str, Any]:
        """What was derived, as counts a reader can check against the records."""
        return {
            "profile": DERIVATION_PROFILE,
            "derivation": self.derivation.key,
            "connections": len(self.connections),
            "bays": sum(space.placement == _PLACEMENT_CARRIAGEWAY for space in self.spaces),
            "stand_spaces": sum(space.placement == _PLACEMENT_FOOTWAY for space in self.spaces),
            "left_out": [{"identity": identity, "reason": why} for identity, why in self.left_out],
        }


def _refuse(message: str) -> UnsupportedNetworkError:
    return UnsupportedNetworkError(f"road derivation: {message}")


def _identity(city: str, kind: str, owner: str, ordinal: int) -> str:
    return subject_identity(
        grammar_id=CITY_GRAMMAR_ID,
        root_identity=city,
        subject_kind=kind,
        owner_identity=owner,
        ordinal=ordinal,
    )


def _axis(first: Sequence[int], second: Sequence[int], what: str) -> Point:
    """The plan axis a piece runs along, or a refusal naming the piece."""
    dx, dy = second[0] - first[0], second[1] - first[1]
    if (dx == 0) == (dy == 0):
        raise _refuse(f"{what} does not run along a plan axis; v1 derives at axis legs only")
    return (dx > 0) - (dx < 0), (dy > 0) - (dy < 0)


def _right_of(direction: Point) -> Point:
    return direction[1], -direction[0]


def _box(points: Iterable[tuple[int, ...]], z: tuple[int, int] | None = None) -> Extent:
    points = list(points)
    xs, ys = [point[0] for point in points], [point[1] for point in points]
    if z is None:
        zs = [point[2] for point in points]
        z = (min(zs), max(zs))
    return Extent(min(xs), min(ys), z[0], max(xs), max(ys), z[1])


# -- lane connections ---------------------------------------------------------------------------


def _quarter_arc(
    centre: Point, start_axis: Point, end_axis: Point, radius: int, chords: int
) -> list[Point]:
    """Points from ``centre + radius * start_axis`` to ``centre + radius * end_axis`` by the
    rational parametrisation, exact integers on every machine."""
    points = []
    for step in range(chords + 1):
        denominator = chords * chords + step * step
        along_start = (chords * chords - step * step) * radius
        along_end = 2 * chords * step * radius
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


def _connection_path(
    source: LaneRecord, target: LaneRecord, movement: str, chords: int
) -> tuple[tuple[int, int, int], ...]:
    end, start = source.centreline_mm[-1], target.centreline_mm[0]
    p0, p1 = (end[0], end[1]), (start[0], start[1])
    if movement == "straight":
        plan = [p0, p1]
    else:
        d_in = _axis(source.centreline_mm[-2], end, f"lane {source.identity}")
        d_out = _axis(start, target.centreline_mm[1], f"lane {target.identity}")
        corner = (p1[0], p0[1]) if d_in[1] == 0 else (p0[0], p1[1])
        before = abs(corner[0] - p0[0]) + abs(corner[1] - p0[1])
        after = abs(corner[0] - p1[0]) + abs(corner[1] - p1[1])
        radius = min(before, after)
        if radius == 0:
            raise _refuse(f"lane {source.identity} turns into {target.identity} at a point")
        arc_start = (corner[0] - radius * d_in[0], corner[1] - radius * d_in[1])
        centre = (arc_start[0] + radius * d_out[0], arc_start[1] + radius * d_out[1])
        arc = _quarter_arc(centre, (-d_out[0], -d_out[1]), d_in, radius, chords)
        plan = [p0, *arc, p1]
    kept: list[Point] = []
    for point in plan:
        if not kept or kept[-1] != point:
            kept.append(point)
    count = len(kept) - 1
    return tuple(
        (x, y, end[2] + round_half_down((start[2] - end[2]) * index, count))
        for index, (x, y) in enumerate(kept)
    )


def _connections(
    records: Sequence[object], derivation: RoadDerivation, city: str
) -> list[LaneConnectionRecord]:
    segments = {r.identity: r for r in records if type(r) is StreetSegmentRecord}
    stated = {r.junction_identity for r in records if type(r) is LaneConnectionRecord}
    inbound: dict[str, list[LaneRecord]] = defaultdict(list)
    outbound: dict[str, list[LaneRecord]] = defaultdict(list)
    for lane in sorted((r for r in records if type(r) is LaneRecord), key=lambda r: r.identity):
        if lane.direction == "none":
            continue
        segment = segments[lane.segment_identity]
        forward = lane.direction == "forward"
        inbound[segment.end_node_identity if forward else segment.start_node_identity].append(lane)
        outbound[segment.start_node_identity if forward else segment.end_node_identity].append(lane)
    derived = []
    junctions = sorted((r for r in records if type(r) is JunctionRecord), key=lambda r: r.identity)
    for junction in junctions:
        if junction.identity in stated:
            continue
        ordinal = 0
        for source in inbound[junction.node_identity]:
            d_in = _axis(
                source.centreline_mm[-2], source.centreline_mm[-1], f"lane {source.identity}"
            )
            by_movement: dict[str, list[LaneRecord]] = defaultdict(list)
            for target in outbound[junction.node_identity]:
                if target.segment_identity == source.segment_identity:
                    continue
                d_out = _axis(
                    target.centreline_mm[0], target.centreline_mm[1], f"lane {target.identity}"
                )
                if d_out == d_in:
                    by_movement["straight"].append(target)
                elif d_out == _right_of(d_in):
                    by_movement["right"].append(target)
                elif d_out == (-d_in[1], d_in[0]):
                    by_movement["left"].append(target)
            for movement in source.turns:
                targets = by_movement.get(movement, [])
                if len(targets) != 1:
                    raise _refuse(
                        f"lane {source.identity} permits {movement} at junction "
                        f"{junction.identity}, where {len(targets)} lanes leave by that leg; "
                        "v1 derives one"
                    )
                [target] = targets
                path = _connection_path(
                    source, target, movement, derivation.arc_chords_per_quarter_turn
                )
                derived.append(
                    LaneConnectionRecord(
                        identity=_identity(city, "lane_connection", junction.identity, ordinal),
                        junction_identity=junction.identity,
                        connection_ordinal=ordinal,
                        from_lane_identity=source.identity,
                        to_lane_identity=target.identity,
                        movement=movement,
                        path_mm=path,
                        extent=_box(path),
                    )
                )
                ordinal += 1
    return derived


# -- parking --------------------------------------------------------------------------------------


def _subtract(
    allowed: tuple[int, int], forbidden: Iterable[tuple[int, int]]
) -> list[tuple[int, int]]:
    """The parts of ``allowed`` no forbidden interval touches, in order."""
    runs = [allowed]
    for low, high in sorted(forbidden):
        kept = []
        for start, end in runs:
            if high < start or end < low:
                kept.append((start, end))
                continue
            if start < low:
                kept.append((start, low - 1))
            if high < end:
                kept.append((high + 1, end))
        runs = kept
    return [(start, end) for start, end in runs if start < end]


def _forbidden(
    network: RoadNetwork, path: PathSpec, crossing_clearance: int, stop_clearance: int
) -> list[tuple[int, int]]:
    """Positions on ``path`` a space may not be reached across: up to its exit extent (its junction
    region, or its first point at a network edge), its conflict zones, each crossing band grown by
    ``crossing_clearance``, and ``stop_clearance`` before the junction it runs to."""
    # Traffic reaches no space at or before a lane's exit extent, which is 0 at a network edge.
    blocked = [(0, network.exit_extent[path.path_id])]
    for _zone, interval in network.zones_by_path.get(path.path_id, ()):
        blocked.append(interval)
    for _band, (low, high) in network.bands_by_path.get(path.path_id, ()):
        blocked.append((low - crossing_clearance, high + crossing_clearance))
    if path.end_junction is not None:
        blocked.append((path.length - stop_clearance, path.length))
    return blocked


def _circulating(network: RoadNetwork, class_key: str) -> frozenset[str]:
    """The paths of the largest set a vehicle of ``class_key`` can drive round: from each of them
    it can reach every other and come back. A space elsewhere could be driven to or from, not
    both, as on a lane starting where the records stop. Ties go to the set whose least path id is
    least."""
    carrying = sorted(
        path_id for path_id, path in network.paths.items() if class_key in path.classes
    )
    edges = {
        path_id: [
            nxt
            for nxt in network.paths[path_id].successors
            if class_key in network.paths[nxt].classes
        ]
        for path_id in carrying
    }
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[frozenset[str]] = []
    counter = 0
    for root in carrying:
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            node, child = work.pop()
            if child == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            successors = edges[node]
            if child < len(successors):
                work.append((node, child + 1))
                nxt = successors[child]
                if nxt not in index:
                    work.append((nxt, 0))
                elif nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
                continue
            if low[node] == index[node]:
                members = set()
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    members.add(member)
                    if member == node:
                        break
                components.append(frozenset(members))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    if not components:
        return frozenset()
    return sorted(components, key=lambda component: (-len(component), min(component)))[0]


def _segment_offset(lane: LaneRecord, position: int) -> int:
    """The offset along the lane's segment of a position along the lane (a straight lane)."""
    if lane.direction == "backward":
        return lane.start_offset_mm - position
    return lane.start_offset_mm + position


def _lane_position(lane: LaneRecord, offset: int) -> int:
    if lane.direction == "backward":
        return lane.start_offset_mm - offset
    return offset - lane.start_offset_mm


def _unit_scaled(vector: Point, length: int) -> Point:
    run = integer_sqrt(vector[0] * vector[0] + vector[1] * vector[1])
    return round_half_down(vector[0] * length, run), round_half_down(vector[1] * length, run)


def _rectangle(centre_a: Point, centre_b: Point, half_width: int) -> tuple[Point, ...]:
    """The rectangle of ``half_width`` either side of the line from ``centre_a`` to ``centre_b``,
    counter-clockwise."""
    along = (centre_b[0] - centre_a[0], centre_b[1] - centre_a[1])
    across = _unit_scaled((-along[1], along[0]), half_width)
    return (
        (centre_a[0] - across[0], centre_a[1] - across[1]),
        (centre_b[0] - across[0], centre_b[1] - across[1]),
        (centre_b[0] + across[0], centre_b[1] + across[1]),
        (centre_a[0] + across[0], centre_a[1] + across[1]),
    )


def _point_at(lane: LaneRecord, offset: int) -> Point:
    """The point of a straight lane's centreline at a segment offset."""
    (x0, y0, _), (x1, y1, _) = lane.centreline_mm[0], lane.centreline_mm[-1]
    span = lane.end_offset_mm - lane.start_offset_mm
    along = offset - lane.start_offset_mm
    return x0 + round_half_down((x1 - x0) * along, span), y0 + round_half_down(
        (y1 - y0) * along, span
    )


def _spaces(
    records: Sequence[object],
    network: RoadNetwork,
    catalogs: TrafficCatalogs,
    derivation: RoadDerivation,
    city_catalogs: Sequence[Catalog],
    city: str,
) -> tuple[list[ParkingSpaceRecord], list[tuple[str, str]]]:
    catalog = {item.catalog_id: item for item in city_catalogs}
    bay = entry_fields(catalog["parking-kind"], derivation.bay_parking_kind)
    stand = entry_fields(catalog["parking-kind"], derivation.stand_parking_kind)
    if (bay["placement"], stand["placement"]) != (_PLACEMENT_CARRIAGEWAY, _PLACEMENT_FOOTWAY):
        raise _refuse("the bay kind is laid in the carriageway and the stand kind on the footway")
    furniture = catalog["street-furniture"]
    stands_per_class = {
        entry.key: entry_fields(furniture, entry.key)
        for entry in furniture.entries
        if entry_fields(furniture, entry.key)["category"] == derivation.stand_furniture_category
    }
    lanes_by_segment: dict[str, list[LaneRecord]] = defaultdict(list)
    for lane in (r for r in records if type(r) is LaneRecord):
        lanes_by_segment[lane.segment_identity].append(lane)
    curbs = {(r.segment_identity, r.side): r for r in records if type(r) is CurbEdgeRecord}
    curb_of = {curb.identity: curb for curb in curbs.values()}
    stated = {r.curb_identity for r in records if type(r) is ParkingSpaceRecord}
    wanted: dict[str, list[dict[str, Any]]] = defaultdict(list)
    left_out: list[tuple[str, str]] = []

    def round_network(kind: str) -> frozenset[str]:
        # The paths a class the kind admits can drive round; a space elsewhere is not laid.
        return frozenset().union(
            *(_circulating(network, key) for key in catalogs.parking_kind(kind).classes)
        )

    bay_paths = round_network(derivation.bay_parking_kind)
    stand_paths = round_network(derivation.stand_parking_kind)

    def traffic_lanes(segment: str) -> list[LaneRecord]:
        return sorted(
            (lane for lane in lanes_by_segment[segment] if lane.direction != "none"),
            key=lambda lane: lane.lane_index,
        )

    for parking in sorted(lanes_by_segment.values(), key=lambda lanes: lanes[0].segment_identity):
        for lane in sorted(parking, key=lambda item: item.lane_index):
            if lane.lane_use != derivation.bay_lane_use:
                continue
            carrying = traffic_lanes(lane.segment_identity)
            side = _LEFT if lane.lane_index < carrying[0].lane_index else _RIGHT
            access = carrying[0] if side == _LEFT else carrying[-1]
            curb = curbs.get((lane.segment_identity, side))
            if curb is None or curb.identity in stated:
                continue
            path = network.paths[f"lane:{access.identity}"]
            if path.path_id not in bay_paths:
                left_out.append(
                    (lane.identity, "its access lane is not on the network its classes drive round")
                )
                continue
            ends = sorted(
                _lane_position(access, offset)
                for offset in (lane.start_offset_mm, lane.end_offset_mm)
            )
            reach = (max(ends[0], 0), min(ends[1], path.length))
            forbidden = _forbidden(
                network,
                path,
                derivation.bay_crossing_clearance_mm,
                derivation.bay_stop_line_clearance_mm,
            )
            length = bay["length_maximum_mm"]
            for start, end in _subtract(reach, forbidden):
                position = start
                while position + length <= end:
                    offsets = sorted(
                        _segment_offset(access, along) for along in (position, position + length)
                    )
                    wanted[curb.identity].append(
                        {"lane": lane, "access": access, "offsets": offsets, "kind": "bay"}
                    )
                    position += length
    for item in sorted(
        (r for r in records if type(r) is StreetFurnitureRecord), key=lambda r: r.identity
    ):
        if item.furniture_class not in stands_per_class or item.curb_identity in stated:
            continue
        curb = curb_of.get(item.curb_identity)
        carrying = traffic_lanes(item.segment_identity)
        if curb is None or not carrying:
            left_out.append((item.identity, "no traffic lane runs beside its curb"))
            continue
        access = carrying[0] if curb.side == _LEFT else carrying[-1]
        path = network.paths[f"lane:{access.identity}"]
        if path.path_id not in stand_paths:
            left_out.append(
                (item.identity, "its access lane is not on the network its classes drive round")
            )
            continue
        first, last = access.centreline_mm[0], access.centreline_mm[-1]
        direction = _axis(first, last, f"lane {access.identity}")
        along = (item.x_mm - first[0]) * direction[0] + (item.y_mm - first[1]) * direction[1]
        half = stand["length_minimum_mm"] // 2
        stretch = (along - half, along + half)
        blocked = _forbidden(network, path, 0, 0)
        clear = (
            stretch[0] >= 0
            and stretch[1] <= path.length
            and _subtract(stretch, blocked) == [stretch]
        )
        if not clear:
            left_out.append(
                (item.identity, "its access stretch meets a junction region, a zone or a crossing")
            )
            continue
        offsets = sorted(_segment_offset(access, at) for at in stretch)
        wanted[curb.identity].append(
            {
                "stand": item,
                "access": access,
                "offsets": offsets,
                "kind": "stand",
                "direction": direction,
                "capacity": stands_per_class[item.furniture_class]["bicycles_per_stand"],
            }
        )
    spaces = []
    for curb_identity in sorted(wanted):
        curb = curb_of[curb_identity]
        ordered = sorted(wanted[curb_identity], key=lambda item: (item["offsets"], item["kind"]))
        for ordinal, item in enumerate(ordered):
            low, high = item["offsets"]
            if item["kind"] == "bay":
                lane = item["lane"]
                z = lane.centreline_mm[0][2]
                footprint = _rectangle(
                    _point_at(lane, low), _point_at(lane, high), lane.width_mm // 2
                )
                spaces.append(
                    ParkingSpaceRecord(
                        identity=_identity(city, "parking_space", curb_identity, ordinal),
                        curb_identity=curb_identity,
                        segment_identity=curb.segment_identity,
                        space_ordinal=ordinal,
                        parking_kind=derivation.bay_parking_kind,
                        placement=_PLACEMENT_CARRIAGEWAY,
                        capacity=1,
                        footprint_mm=footprint,
                        lane_identity=(lane.identity,),
                        access_lane_identity=item["access"].identity,
                        access_start_mm=low,
                        access_end_mm=high,
                        furniture_identities=(),
                        extent=_box(footprint, (z, z)),
                    )
                )
            else:
                stand_record = item["stand"]
                direction = item["direction"]
                half = stand["length_minimum_mm"] // 2
                centre = (stand_record.x_mm, stand_record.y_mm)
                footprint = _rectangle(
                    (centre[0] - direction[0] * half, centre[1] - direction[1] * half),
                    (centre[0] + direction[0] * half, centre[1] + direction[1] * half),
                    stand["width_minimum_mm"] // 2,
                )
                z = stand_record.z_mm
                spaces.append(
                    ParkingSpaceRecord(
                        identity=_identity(city, "parking_space", curb_identity, ordinal),
                        curb_identity=curb_identity,
                        segment_identity=curb.segment_identity,
                        space_ordinal=ordinal,
                        parking_kind=derivation.stand_parking_kind,
                        placement=_PLACEMENT_FOOTWAY,
                        capacity=item["capacity"],
                        footprint_mm=footprint,
                        lane_identity=(),
                        access_lane_identity=item["access"].identity,
                        access_start_mm=low,
                        access_end_mm=high,
                        furniture_identities=(stand_record.identity,),
                        extent=_box(footprint, (z, z)),
                    )
                )
    return spaces, left_out


def derive_road_records(
    records: Sequence[object],
    catalogs: TrafficCatalogs,
    city_catalogs: Sequence[Catalog],
    *,
    city_identity: str,
    derivation_key: str = DERIVATION_KEY,
) -> DerivedRoads:
    """The connections and spaces a city's records imply, or a refusal naming the record.

    ``city_catalogs`` are the catalogs the records were generated against: the parking-kind and
    street-furniture catalogs size the spaces.
    """
    derivation = catalogs.derivation(derivation_key)
    records = tuple(records)
    connections = _connections(records, derivation, city_identity)
    with_connections = (*records, *connections)
    network = compile_network(
        road_input_from_city(with_connections, catalogs, city_identity=city_identity), catalogs
    )
    spaces, left_out = _spaces(
        with_connections, network, catalogs, derivation, city_catalogs, city_identity
    )
    return DerivedRoads(
        records=(*with_connections, *spaces),
        connections=tuple(connections),
        spaces=tuple(spaces),
        left_out=tuple(left_out),
        derivation=derivation,
    )
