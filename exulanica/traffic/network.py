"""The road network compiler: road records and catalogs in, a checked simulation network out.

:func:`compile_network` refuses a network it cannot simulate correctly, with the reason, rather
than approximating it. It reads the provisional road records (until the city vocabulary lane
lands the real ones) and the three traffic catalogs, and produces a :class:`RoadNetwork`.

**Paths.** Every lane and every lane connector is a :class:`PathSpec`: a polyline a vehicle's
front follows, the classes allowed on it, a speed limit, and a corridor half-width per piece.
A lane piece's half-width is the widest permitted body plus the rear-axle off-tracking of its
wheelbase on the piece's curve. A connector piece that is not collinear with the connector's
first or last piece uses the design vehicle's turning envelope from the catalog instead.

**Zones.** Two paths through one junction whose corridors meet form a :class:`Zone`: an
interval on each. Vehicles on opposite sides of a zone may never be inside their intervals at
the same time; that is the collision rule for crossing, merging and diverging movements, and
it is conservative because the intervals are supersets. A lane and the connector that follows
it touch only at their joint, which car following handles.

**Regions.** Crossing a junction stop line means reserving a region: the connector and the
start of the lane it leads to, up to the lane's *exit extent*. The vehicle may not stop until
it has left the region, so it is only admitted when there is room beyond it.

**Bands.** A pedestrian crossing is a :class:`Band` with an interval on every path it meets.
A band on a connector or at the start of a lane belongs to its junction's region; a band
further along a lane is a mid-block band with its own gate.

**What v1 refuses**, each with a message: lane changes between junctions (lanes are chosen only
through connectors), a lane end or a lane start that another junction path comes near other than
by its own joint, two lanes whose corridors meet, a crossing or a parking access interval on a
curved lane piece, a signal plan that lets two conflicting movements of equal turn rank go
together, a straight movement crossing a walking crosswalk, a priority junction with more than
one inbound lane on a major approach or with a u-turn, and a left-hand network.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.errors import GrammarError
from exulanica.grammar.records import require_identity
from exulanica.traffic import provisional_records as rec
from exulanica.traffic.catalogs import TrafficCatalogs, VehicleClass
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.traffic.geometry import (
    Point,
    Polyline,
    circumradius_floor,
    convex_overlap,
    cross,
    dot,
    near_interval,
    offtracking_mm,
    point_segment_within,
    segments_intersect,
    segments_within,
)

__all__ = [
    "NETWORK_PROFILE",
    "Band",
    "Gate",
    "JunctionSpec",
    "PathSpec",
    "RoadNetwork",
    "SignalSpec",
    "SpaceSpec",
    "Zone",
    "compile_network",
]

NETWORK_PROFILE: Final = "exulanica.traffic-network/v1"
_MS_PER_SECOND: Final = 1000
_MS_PER_HOUR: Final = 3_600_000


def _refuse(message: str) -> UnsupportedNetworkError:
    return UnsupportedNetworkError(message)


@dataclass(frozen=True, slots=True)
class PathSpec:
    path_id: str
    kind: str
    identity: str
    ordinal: int
    line: Polyline
    classes: tuple[str, ...]
    speed_limit_mm_per_s: int
    #: ``(left, right)`` reach of the corridor either side of each piece.
    extents: tuple[tuple[int, int], ...]
    successors: tuple[str, ...]
    predecessors: tuple[str, ...]
    #: Lanes: the junction the lane flows into and the one it leaves. Connectors: their junction.
    end_junction: int | None
    start_junction: int | None
    turn: str = ""
    segment_ordinal: int = -1
    #: The largest body length and minimum gap of any class allowed, for region sizing.
    longest_body_mm: int = 0
    widest_gap_mm: int = 0

    @property
    def length(self) -> int:
        return self.line.length

    @property
    def is_turn(self) -> bool:
        return self.kind == "connector" and self.turn != "straight"


@dataclass(frozen=True, slots=True)
class Zone:
    zone_id: int
    junction: int
    first: str
    first_interval: tuple[int, int]
    second: str
    second_interval: tuple[int, int]

    def side(self, path_id: str) -> tuple[str, tuple[int, int], str, tuple[int, int]] | None:
        """``(this path, its interval, other path, other interval)`` or ``None``."""
        if path_id == self.first:
            return self.first, self.first_interval, self.second, self.second_interval
        if path_id == self.second:
            return self.second, self.second_interval, self.first, self.first_interval
        return None


@dataclass(frozen=True, slots=True)
class Band:
    band_id: int
    identity: str
    ordinal: int
    society_crossing_id: str
    segment_ordinal: int
    control: str
    line: tuple[Point, Point]
    width_mm: int
    length_mm: int
    #: ``(path, lower, upper)``: the positions on each path whose corridor meets the band.
    intervals: tuple[tuple[str, int, int], ...]
    #: The junction whose region holds this band, or ``None`` for a mid-block band.
    junction: int | None
    #: ``(controller junction, pedestrian group)`` for a signalised crossing.
    signal: tuple[int, str] | None


@dataclass(frozen=True, slots=True)
class Gate:
    """A point on a path a vehicle may not pass without a reservation."""

    path_id: str
    position: int
    kind: str
    #: The junction for a junction gate, the band for a band gate.
    target: int


@dataclass(frozen=True, slots=True)
class SignalSpec:
    controller_identity: str
    plan: str
    offset_s: int
    #: ``(connector path, group)`` for every connector of the junction.
    connector_groups: tuple[tuple[str, str], ...]
    #: ``(band id, group)`` for every signalised crossing the controller governs.
    band_groups: tuple[tuple[int, str], ...]

    def group_of(self, path_id: str) -> str:
        return dict(self.connector_groups)[path_id]


@dataclass(frozen=True, slots=True)
class ApproachSpec:
    segment_ordinal: int
    identity: str
    control: str
    rank: int
    inbound_lanes: tuple[str, ...]
    #: The travel direction at the stop line of its first inbound lane.
    direction: Point


@dataclass(frozen=True, slots=True)
class JunctionSpec:
    ordinal: int
    identity: str
    node_ordinal: int
    position: Point
    policy: str
    rule: str
    approaches: tuple[ApproachSpec, ...]
    connectors: tuple[str, ...]
    signal: SignalSpec | None
    #: ``(connector, connector)`` pairs, sorted, whose regions share a zone.
    conflicts: tuple[tuple[str, str], ...]

    def approach_of_lane(self, lane_id: str) -> ApproachSpec:
        for approach in self.approaches:
            if lane_id in approach.inbound_lanes:
                return approach
        raise _refuse(f"lane {lane_id} is not an approach of junction {self.ordinal}")


@dataclass(frozen=True, slots=True)
class SpaceSpec:
    identity: str
    ordinal: int
    segment_ordinal: int
    layout: str
    footprint: tuple[Point, ...]
    access_path: str
    access_start: int
    access_end: int
    classes: tuple[str, ...]


@dataclass(frozen=True)
class RoadNetwork:
    scope: str
    driving_side: str
    paths: Mapping[str, PathSpec]
    junctions: Mapping[int, JunctionSpec]
    zones: tuple[Zone, ...]
    bands: tuple[Band, ...]
    spaces: Mapping[str, SpaceSpec]
    #: Per lane: how far from its start the region of its start junction reaches.
    exit_extent: Mapping[str, int]
    #: Per path, gates sorted by position.
    gates: Mapping[str, tuple[Gate, ...]]
    #: Per path, ``(zone id, own interval)`` sorted.
    zones_by_path: Mapping[str, tuple[tuple[int, tuple[int, int]], ...]]
    #: Per path, ``(band id, interval)`` sorted.
    bands_by_path: Mapping[str, tuple[tuple[int, tuple[int, int]], ...]]
    #: Per successor pair ``(a, b)``: how far into ``b`` its corridor still meets ``a``'s.
    joint_extent: Mapping[tuple[str, str], int]
    #: Classes the records allowed and the geometry could not carry, with the reason.
    restrictions: tuple[tuple[str, str, str], ...]
    catalog_sha256: str
    document: Mapping[str, Any] = field(repr=False)
    digest: str = ""

    def band(self, band_id: int) -> Band:
        return self.bands[band_id]

    def band_by_society_id(self, crossing_id: str) -> Band:
        for band in self.bands:
            if band.society_crossing_id == crossing_id:
                return band
        raise _refuse(f"no crossing {crossing_id!r} in this network")


def _unique(records: Iterable[Any], attribute: str, what: str) -> dict[int, Any]:
    by_ordinal: dict[int, Any] = {}
    for record in records:
        key = getattr(record, attribute)
        if key in by_ordinal:
            raise _refuse(f"two {what} records share {attribute} {key}")
        by_ordinal[key] = record
    return by_ordinal


def _check_identity(scope: str, record: Any, kind: str, *parts: int | str) -> None:
    expected = rec.street_record_identity(scope, kind, *parts)
    if record.identity != expected:
        raise _refuse(f"{kind} {parts} has identity {record.identity}, expected {expected}")


def _collinear(first: Point, second: Point) -> bool:
    return cross(first, second) == 0 and dot(first, second) > 0


def _lane_extents(line: Polyline, classes: Sequence[VehicleClass]) -> tuple[tuple[int, int], ...]:
    radii: list[int | None] = [None] * len(line.points)
    for index in range(1, len(line.points) - 1):
        radii[index] = circumradius_floor(
            line.points[index - 1], line.points[index], line.points[index + 1]
        )
    extents = []
    for index in range(line.piece_count):
        bends = [radius for radius in (radii[index], radii[index + 1]) if radius is not None]
        widest = 0
        for vehicle in classes:
            extra = max(
                (offtracking_mm(radius, vehicle.wheelbase_mm) for radius in bends), default=0
            )
            widest = max(widest, vehicle.half_width_mm + extra)
        extents.append((widest, widest))
    return tuple(extents)


def _connector_extents(
    line: Polyline, classes: Sequence[VehicleClass], turn: str
) -> tuple[tuple[int, int], ...]:
    """Straight pieces carry the widest body; turning pieces the design vehicles' swept path.

    Off-tracking is inward, so a turning piece reaches the inward extent on the inside of the
    turn and the outward extent on the outside.
    """
    base = max(vehicle.half_width_mm for vehicle in classes)
    if turn == "straight":
        return ((base, base),) * line.piece_count
    inward = max(
        max(vehicle.turning_inward_extent_mm, vehicle.half_width_mm) for vehicle in classes
    )
    outward = max(
        max(vehicle.turning_outward_extent_mm, vehicle.half_width_mm) for vehicle in classes
    )
    first = line.piece_direction(0)
    last = line.piece_direction(line.piece_count - 1)
    turning = (outward, inward) if turn == "right" else (inward, outward)
    return tuple(
        (base, base)
        if _collinear(line.piece_direction(index), first)
        or _collinear(line.piece_direction(index), last)
        else turning
        for index in range(line.piece_count)
    )


def _min_radius(line: Polyline) -> int | None:
    radii = [
        circumradius_floor(line.points[i - 1], line.points[i], line.points[i + 1])
        for i in range(1, len(line.points) - 1)
    ]
    finite = [radius for radius in radii if radius is not None]
    return min(finite) if finite else None


def _polygon_area2(points: Sequence[Point]) -> int:
    return sum(cross(points[i], points[(i + 1) % len(points)]) for i in range(len(points)))


def _point_in_convex(point: Point, polygon: Sequence[Point]) -> bool:
    count = len(polygon)
    for index in range(count):
        a, b = polygon[index], polygon[(index + 1) % count]
        if cross((b[0] - a[0], b[1] - a[1]), (point[0] - a[0], point[1] - a[1])) < 0:
            return False
    return True


def _straight_at(line: Polyline, start: int, end: int) -> bool:
    return line.piece_index(max(start, 0)) == line.piece_index(max(min(end, line.length) - 1, 0))


def compile_network(
    records: Sequence[object], catalogs: TrafficCatalogs, *, scope: str
) -> RoadNetwork:
    """Check the records and build the network, or raise :class:`UnsupportedNetworkError`."""
    require_identity("scope", scope)
    by_type: dict[type, list[Any]] = {}
    for record in records:
        try:
            rec.validate_record(record)
        except GrammarError as error:
            raise _refuse(f"{type(record).__name__}: {error}") from error
        by_type.setdefault(type(record), []).append(record)

    rules = by_type.get(rec.RoadRulesRecord, [])
    if len(rules) != 1:
        raise _refuse(f"a network has exactly one road rules record, found {len(rules)}")
    driving_side = rules[0].driving_side
    if driving_side != "right":
        raise _refuse(
            "traffic v1 simulates right-hand traffic only; this network drives on the left"
        )

    nodes = _unique(by_type.get(rec.StreetNodeRecord, []), "node_ordinal", "street node")
    segments = _unique(by_type.get(rec.StreetSegmentRecord, []), "segment_ordinal", "segment")
    for segment in segments.values():
        for node in (segment.start_node, segment.end_node):
            if node not in nodes:
                raise _refuse(f"segment {segment.segment_ordinal} names missing node {node}")
    junction_records = _unique(by_type.get(rec.JunctionRecord, []), "junction_ordinal", "junction")
    junction_at_node: dict[int, int] = {}
    for junction in junction_records.values():
        if junction.node_ordinal not in nodes:
            raise _refuse(f"junction {junction.junction_ordinal} names missing node")
        if junction.node_ordinal in junction_at_node:
            raise _refuse(f"node {junction.node_ordinal} has two junctions")
        junction_at_node[junction.node_ordinal] = junction.junction_ordinal
        _check_identity(scope, junction, "junction", junction.node_ordinal)
        policy = catalogs.policy(junction.policy)
        if driving_side not in policy.driving_sides:
            raise _refuse(f"policy {policy.key} does not apply to {driving_side}-hand traffic")

    classes_by_key = {vehicle.key: vehicle for vehicle in catalogs.vehicle_classes}
    restrictions: list[tuple[str, str, str]] = []

    # Lanes.
    lane_records = _unique(by_type.get(rec.CarriagewayLaneRecord, []), "lane_ordinal", "lane")
    lane_slots: set[tuple[int, str, int]] = set()
    lanes: dict[int, dict[str, Any]] = {}
    for lane in lane_records.values():
        segment = segments.get(lane.segment_ordinal)
        if segment is None:
            raise _refuse(f"lane {lane.lane_ordinal} names missing segment {lane.segment_ordinal}")
        slot = (lane.segment_ordinal, lane.direction, lane.lane_index)
        if slot in lane_slots:
            raise _refuse(f"lane slot {slot} is used twice")
        lane_slots.add(slot)
        _check_identity(
            scope, lane, "carriageway_lane", lane.segment_ordinal, lane.direction, lane.lane_index
        )
        try:
            line = Polyline.of(lane.centreline_mm)
        except ValueError as error:
            raise _refuse(f"lane {lane.lane_ordinal}: {error}") from error
        start_node, end_node = nodes[segment.start_node], nodes[segment.end_node]
        axis = (end_node.x_mm - start_node.x_mm, end_node.y_mm - start_node.y_mm)
        travel = (line.points[-1][0] - line.points[0][0], line.points[-1][1] - line.points[0][1])
        along = dot(axis, travel)
        forward = lane.direction == "with_segment"
        if (along > 0) != forward or along == 0:
            raise _refuse(f"lane {lane.lane_ordinal} is digitised against its direction")
        to_node = segment.end_node if forward else segment.start_node
        from_node = segment.start_node if forward else segment.end_node
        unknown = set(lane.permitted_classes) - set(classes_by_key)
        if unknown:
            raise _refuse(f"lane {lane.lane_ordinal} permits unknown classes {sorted(unknown)}")
        allowed = [classes_by_key[key] for key in lane.permitted_classes]
        fitting = []
        for vehicle in allowed:
            if vehicle.width_mm > lane.width_mm:
                restrictions.append(
                    (f"lane:{lane.identity}", vehicle.key, "body wider than the lane")
                )
                continue
            fitting.append(vehicle)
        if not fitting:
            raise _refuse(f"lane {lane.lane_ordinal} carries no permitted class")
        if to_node not in junction_at_node or from_node not in junction_at_node:
            raise _refuse(
                f"lane {lane.lane_ordinal} must start and end at junctions; v1 has no network edge"
            )
        lanes[lane.lane_ordinal] = {
            "record": lane,
            "line": line,
            "classes": fitting,
            "to_junction": junction_at_node[to_node],
            "from_junction": junction_at_node[from_node],
            "limit": lane.speed_limit_mm_per_h * _MS_PER_SECOND // _MS_PER_HOUR,
        }

    # Connectors.
    connector_records = _unique(
        by_type.get(rec.LaneConnectorRecord, []), "connector_ordinal", "lane connector"
    )
    connectors: dict[int, dict[str, Any]] = {}
    seen_pairs: set[tuple[int, int]] = set()
    for connector in connector_records.values():
        if connector.junction_ordinal not in junction_records:
            raise _refuse(f"connector {connector.connector_ordinal} names a missing junction")
        source = lanes.get(connector.from_lane_ordinal)
        target = lanes.get(connector.to_lane_ordinal)
        if source is None or target is None:
            raise _refuse(f"connector {connector.connector_ordinal} names a missing lane")
        if source["to_junction"] != connector.junction_ordinal:
            raise _refuse(
                f"connector {connector.connector_ordinal}: its from lane does not flow in"
            )
        if target["from_junction"] != connector.junction_ordinal:
            raise _refuse(f"connector {connector.connector_ordinal}: its to lane does not flow out")
        pair = (connector.from_lane_ordinal, connector.to_lane_ordinal)
        if pair in seen_pairs:
            raise _refuse(f"lanes {pair} are connected twice")
        seen_pairs.add(pair)
        _check_identity(
            scope,
            connector,
            "lane_connector",
            source["record"].identity,
            target["record"].identity,
        )
        if connector.turn not in source["record"].permitted_turns:
            raise _refuse(f"connector {connector.connector_ordinal} makes a turn its lane forbids")
        if connector.turn == "u_turn":
            raise _refuse("traffic v1 does not simulate u-turns")
        try:
            line = Polyline.of(connector.path_mm)
        except ValueError as error:
            raise _refuse(f"connector {connector.connector_ordinal}: {error}") from error
        if (
            line.points[0] != source["line"].points[-1]
            or line.points[-1] != target["line"].points[0]
        ):
            raise _refuse(f"connector {connector.connector_ordinal} does not meet its lane ends")
        path_id = f"connector:{connector.identity}"
        allowed = [
            vehicle
            for vehicle in source["classes"]
            if vehicle.key in {other.key for other in target["classes"]}
        ]
        radius = _min_radius(line) if connector.turn != "straight" else None
        fitting = []
        for vehicle in allowed:
            if radius is not None and radius < vehicle.minimum_turning_radius_mm:
                restrictions.append(
                    (path_id, vehicle.key, f"turn radius {radius} mm below the class minimum")
                )
                continue
            fitting.append(vehicle)
        if not fitting:
            raise _refuse(f"connector {connector.connector_ordinal} carries no class")
        connectors[connector.connector_ordinal] = {
            "record": connector,
            "line": line,
            "classes": fitting,
            "limit": min(source["limit"], target["limit"]),
            "path_id": path_id,
        }

    # Paths.
    lane_path = {ordinal: f"lane:{data['record'].identity}" for ordinal, data in lanes.items()}
    successors: dict[str, list[str]] = {path: [] for path in lane_path.values()}
    predecessors: dict[str, list[str]] = {path: [] for path in lane_path.values()}
    for data in connectors.values():
        record = data["record"]
        successors[lane_path[record.from_lane_ordinal]].append(data["path_id"])
        predecessors[lane_path[record.to_lane_ordinal]].append(data["path_id"])
    paths: dict[str, PathSpec] = {}
    for ordinal, data in lanes.items():
        record = data["record"]
        path_id = lane_path[ordinal]
        if not successors[path_id]:
            raise _refuse(
                f"lane {ordinal} flows into junction {data['to_junction']} and goes nowhere"
            )
        paths[path_id] = PathSpec(
            path_id=path_id,
            kind="lane",
            identity=record.identity,
            ordinal=ordinal,
            line=data["line"],
            classes=tuple(sorted(vehicle.key for vehicle in data["classes"])),
            speed_limit_mm_per_s=data["limit"],
            extents=_lane_extents(data["line"], data["classes"]),
            successors=tuple(sorted(successors[path_id])),
            predecessors=tuple(sorted(predecessors[path_id])),
            end_junction=data["to_junction"],
            start_junction=data["from_junction"],
            segment_ordinal=record.segment_ordinal,
            longest_body_mm=max(vehicle.length_mm for vehicle in data["classes"]),
            widest_gap_mm=max(vehicle.minimum_gap_mm for vehicle in data["classes"]),
        )
    for ordinal, data in connectors.items():
        record = data["record"]
        path_id = data["path_id"]
        paths[path_id] = PathSpec(
            path_id=path_id,
            kind="connector",
            identity=record.identity,
            ordinal=ordinal,
            line=data["line"],
            classes=tuple(sorted(vehicle.key for vehicle in data["classes"])),
            speed_limit_mm_per_s=data["limit"],
            extents=_connector_extents(data["line"], data["classes"], record.turn),
            successors=(lane_path[record.to_lane_ordinal],),
            predecessors=(lane_path[record.from_lane_ordinal],),
            end_junction=record.junction_ordinal,
            start_junction=record.junction_ordinal,
            turn=record.turn,
            longest_body_mm=max(vehicle.length_mm for vehicle in data["classes"]),
            widest_gap_mm=max(vehicle.minimum_gap_mm for vehicle in data["classes"]),
        )
    ordered_paths = dict(sorted(paths.items()))

    # Lanes on one segment, and lanes meeting at a node, must keep their corridors apart.
    lane_ids = [lane_path[ordinal] for ordinal in sorted(lanes)]
    for index, first_id in enumerate(lane_ids):
        first = paths[first_id]
        for second_id in lane_ids[index + 1 :]:
            second = paths[second_id]
            related = first.segment_ordinal == second.segment_ordinal or {
                first.start_junction,
                first.end_junction,
            } & {second.start_junction, second.end_junction}
            if not related:
                continue
            if near_interval(first.line, first.extents, second.line, second.extents):
                raise _refuse(f"lanes {first.ordinal} and {second.ordinal} come too close")

    # Junction approaches.
    approach_records = _unique(
        by_type.get(rec.JunctionApproachRecord, []), "approach_ordinal", "approach"
    )
    approaches_by_junction: dict[int, list[Any]] = {}
    for approach in approach_records.values():
        junction = junction_records.get(approach.junction_ordinal)
        if junction is None:
            raise _refuse(f"approach {approach.approach_ordinal} names a missing junction")
        segment = segments.get(approach.segment_ordinal)
        if segment is None or junction.node_ordinal not in (segment.start_node, segment.end_node):
            raise _refuse(f"approach {approach.approach_ordinal} is not on a leg of its junction")
        _check_identity(
            scope, approach, "junction_approach", junction.node_ordinal, approach.segment_ordinal
        )
        approaches_by_junction.setdefault(approach.junction_ordinal, []).append(approach)

    # Joints and zones.
    joint_extent: dict[tuple[str, str], int] = {}
    for path in paths.values():
        for successor_id in path.successors:
            successor = paths[successor_id]
            on_first = near_interval(path.line, path.extents, successor.line, successor.extents)
            on_second = near_interval(successor.line, successor.extents, path.line, path.extents)
            reach = 2 * (
                max(max(pair) for pair in path.extents)
                + max(max(pair) for pair in successor.extents)
                + 2
            )
            if on_first is None or on_second is None:
                raise _refuse(f"{path.path_id} and {successor_id} do not meet")
            if on_first[0] < path.length - reach or on_second[1] > reach:
                raise _refuse(
                    f"{path.path_id} and its successor {successor_id} "
                    "come close away from their joint"
                )
            joint_extent[(path.path_id, successor_id)] = on_second[1]

    zones: list[Zone] = []
    junction_paths: dict[int, list[str]] = {}
    for path in paths.values():
        if path.kind == "connector":
            junction_paths.setdefault(path.end_junction, []).append(path.path_id)
    exit_extent: dict[str, int] = {path_id: 0 for path_id in lane_ids}
    for junction_ordinal in sorted(junction_records):
        members = sorted(junction_paths.get(junction_ordinal, []))
        inbound = sorted(
            path_id for path_id in lane_ids if paths[path_id].end_junction == junction_ordinal
        )
        outbound = sorted(
            path_id for path_id in lane_ids if paths[path_id].start_junction == junction_ordinal
        )
        for index, first_id in enumerate(members):
            first = paths[first_id]
            for second_id in members[index + 1 :]:
                second = paths[second_id]
                on_first = near_interval(first.line, first.extents, second.line, second.extents)
                on_second = near_interval(second.line, second.extents, first.line, first.extents)
                if on_first is None or on_second is None:
                    continue
                zones.append(
                    Zone(len(zones), junction_ordinal, first_id, on_first, second_id, on_second)
                )
            for lane_id in inbound:
                if lane_id in first.predecessors:
                    continue
                lane = paths[lane_id]
                if near_interval(lane.line, lane.extents, first.line, first.extents):
                    raise _refuse(
                        f"connector {first.ordinal} comes near the stop line of lane {lane.ordinal}"
                    )
            for lane_id in outbound:
                if lane_id in first.successors:
                    continue
                lane = paths[lane_id]
                on_lane = near_interval(lane.line, lane.extents, first.line, first.extents)
                on_connector = near_interval(first.line, first.extents, lane.line, lane.extents)
                if on_lane is None or on_connector is None:
                    continue
                if on_lane[0] > lane.longest_body_mm:
                    raise _refuse(
                        f"connector {first.ordinal} comes near lane {lane.ordinal} "
                        "away from its start"
                    )
                zones.append(
                    Zone(len(zones), junction_ordinal, first_id, on_connector, lane_id, on_lane)
                )
                exit_extent[lane_id] = max(exit_extent[lane_id], on_lane[1])

    # Crossings.
    crossing_records = _unique(by_type.get(rec.CrossingRecord, []), "crossing_ordinal", "crossing")
    covered: set[tuple[int, int]] = set()
    bands: list[Band] = []
    band_of_crossing: dict[int, int] = {}
    for crossing in sorted(crossing_records.values(), key=lambda item: item.crossing_ordinal):
        segment = segments.get(crossing.segment_ordinal)
        if segment is None:
            raise _refuse(f"crossing {crossing.crossing_ordinal} names a missing segment")
        if crossing.offset_index >= len(segment.crossing_offsets_mm):
            raise _refuse(f"crossing {crossing.crossing_ordinal} names a missing crossing offset")
        slot = (crossing.segment_ordinal, crossing.offset_index)
        if slot in covered:
            raise _refuse(f"crossing offset {slot} has two crossing records")
        covered.add(slot)
        _check_identity(
            scope, crossing, "crossing", crossing.segment_ordinal, crossing.offset_index
        )
        offset = segment.crossing_offsets_mm[crossing.offset_index]
        centreline = Polyline.of(segment.centreline_mm)
        centre = centreline.point_at(offset)
        a, b = crossing.line_mm
        if not point_segment_within(centre, a, b, crossing.width_mm // 2 + 1):
            raise _refuse(f"crossing {crossing.crossing_ordinal} does not sit at its offset")
        line = Polyline.of([a, b])
        intervals: list[tuple[str, int, int]] = []
        junction_owner: int | None = None
        end_nodes = {segment.start_node, segment.end_node}
        nearby = [
            path
            for path in paths.values()
            if path.segment_ordinal == crossing.segment_ordinal
            or (
                path.kind == "connector"
                and junction_records[path.end_junction].node_ordinal in end_nodes
            )
        ]
        for path in sorted(nearby, key=lambda item: item.path_id):
            half_band = -(-crossing.width_mm // 2)
            interval = near_interval(path.line, path.extents, line, ((half_band, half_band),))
            if interval is None:
                continue
            if path.kind == "lane" and interval[1] >= path.length - 1 and interval[0] > 0:
                raise _refuse(
                    f"crossing {crossing.crossing_ordinal} reaches the stop line "
                    f"of lane {path.ordinal}"
                )
            if path.kind == "lane" and not _straight_at(path.line, interval[0], interval[1]):
                raise _refuse(f"crossing {crossing.crossing_ordinal} lies on a curved lane piece")
            if path.kind == "lane":
                direction = path.line.piece_direction(path.line.piece_index(interval[0]))
                if dot(direction, (b[0] - a[0], b[1] - a[1])) != 0:
                    raise _refuse(
                        f"crossing {crossing.crossing_ordinal} is not perpendicular "
                        f"to lane {path.ordinal}"
                    )
            intervals.append((path.path_id, interval[0], interval[1]))
            if path.kind == "connector":
                junction_owner = path.end_junction
        for path_id, low, _ in intervals:
            path = paths[path_id]
            if (
                path.kind == "lane"
                and low <= exit_extent[path_id] + path.longest_body_mm + path.widest_gap_mm
            ):
                if junction_owner not in (None, path.start_junction):
                    raise _refuse(f"crossing {crossing.crossing_ordinal} belongs to two junctions")
                junction_owner = path.start_junction
        if junction_owner is not None:
            for path_id, low, high in intervals:
                path = paths[path_id]
                if path.kind == "lane":
                    if path.start_junction != junction_owner or low > (
                        exit_extent[path_id] + path.longest_body_mm + path.widest_gap_mm
                    ):
                        raise _refuse(
                            f"crossing {crossing.crossing_ordinal} is part junction band, "
                            "part mid-block"
                        )
                    exit_extent[path_id] = max(exit_extent[path_id], high)
        band_of_crossing[crossing.crossing_ordinal] = len(bands)
        bands.append(
            Band(
                band_id=len(bands),
                identity=crossing.identity,
                ordinal=crossing.crossing_ordinal,
                society_crossing_id=f"crossing:{crossing.segment_ordinal}:{offset}",
                segment_ordinal=crossing.segment_ordinal,
                control=crossing.control,
                line=(a, b),
                width_mm=crossing.width_mm,
                length_mm=line.length,
                intervals=tuple(intervals),
                junction=junction_owner,
                signal=None,
            )
        )
    for segment in segments.values():
        for index in range(len(segment.crossing_offsets_mm)):
            if (segment.segment_ordinal, index) not in covered:
                raise _refuse(
                    f"segment {segment.segment_ordinal} crossing offset {index} "
                    "has no crossing record"
                )

    # Signals.
    controllers = _unique(
        by_type.get(rec.SignalControllerRecord, []), "controller_ordinal", "signal controller"
    )
    controller_of_junction: dict[int, Any] = {}
    for controller in controllers.values():
        junction = junction_records.get(controller.junction_ordinal)
        if junction is None:
            raise _refuse(f"controller {controller.controller_ordinal} names a missing junction")
        if controller.junction_ordinal in controller_of_junction:
            raise _refuse(f"junction {controller.junction_ordinal} has two controllers")
        controller_of_junction[controller.junction_ordinal] = controller
        _check_identity(scope, controller, "signal_controller", junction.node_ordinal)
        plan = catalogs.plan(controller.plan)
        if any(interval.duration_ms % _MS_PER_SECOND for interval in plan.intervals):
            raise _refuse(f"plan {plan.key} has an interval that is not whole seconds")
        if controller.offset_s * _MS_PER_SECOND >= plan.cycle_ms:
            raise _refuse(
                f"controller {controller.controller_ordinal} offset is not below its cycle"
            )
    group_records = by_type.get(rec.SignalGroupRecord, [])
    groups_by_controller: dict[int, dict[str, Any]] = {}
    for group in group_records:
        controller = controllers.get(group.controller_ordinal)
        if controller is None:
            raise _refuse(f"signal group {group.group} names a missing controller")
        junction = junction_records[controller.junction_ordinal]
        _check_identity(scope, group, "signal_group", junction.node_ordinal, group.group)
        owned = groups_by_controller.setdefault(group.controller_ordinal, {})
        if group.group in owned:
            raise _refuse(f"controller {group.controller_ordinal} lists group {group.group} twice")
        owned[group.group] = group

    # Parking.
    space_records = _unique(
        by_type.get(rec.ParkingSpaceRecord, []), "space_ordinal", "parking space"
    )
    spaces: dict[str, SpaceSpec] = {}
    stalls: list[tuple[str, tuple[Point, ...]]] = []
    space_slots: set[tuple[int, str, int]] = set()
    for space in space_records.values():
        slot = (space.segment_ordinal, space.side, space.space_index)
        if slot in space_slots:
            raise _refuse(f"parking slot {slot} is used twice")
        space_slots.add(slot)
        _check_identity(
            scope, space, "parking_space", space.segment_ordinal, space.side, space.space_index
        )
        lane = lanes.get(space.access_lane_ordinal)
        if lane is None or lane["record"].segment_ordinal != space.segment_ordinal:
            raise _refuse(f"space {space.space_ordinal} is not reached from a lane of its segment")
        path = paths[lane_path[space.access_lane_ordinal]]
        if space.access_end_mm > path.length:
            raise _refuse(f"space {space.space_ordinal} access interval runs off its lane")
        if not _straight_at(path.line, space.access_start_mm, space.access_end_mm):
            raise _refuse(f"space {space.space_ordinal} is reached from a curved lane piece")
        footprint = tuple(space.footprint_mm)
        if _polygon_area2(footprint) <= 0:
            raise _refuse(f"space {space.space_ordinal} footprint is not counter-clockwise")
        edges = sorted(
            {
                (footprint[i][0] - footprint[(i + 1) % 4][0]) ** 2
                + (footprint[i][1] - footprint[(i + 1) % 4][1]) ** 2
                for i in range(4)
            }
        )
        stall_width_squared, stall_length_squared = edges[0], edges[-1]
        access = space.access_end_mm - space.access_start_mm
        fitting = []
        for key in space.permitted_classes:
            vehicle = classes_by_key.get(key)
            if vehicle is None:
                raise _refuse(f"space {space.space_ordinal} permits unknown class {key}")
            if key not in path.classes:
                restrictions.append(
                    (space.identity, key, "its access lane does not carry the class")
                )
                continue
            if (
                vehicle.width_mm**2 > stall_width_squared
                or vehicle.length_mm**2 > stall_length_squared
                or vehicle.length_mm > access
            ):
                restrictions.append((space.identity, key, "the stall is too small"))
                continue
            fitting.append(key)
        for other_id, other in stalls:
            if convex_overlap(footprint, other):
                raise _refuse(f"space {space.space_ordinal} overlaps space {other_id}")
        for other in paths.values():
            if other.kind == "lane" and other.segment_ordinal != space.segment_ordinal:
                continue
            for index in range(other.line.piece_count):
                a, b = other.line.piece(index)
                reach = max(other.extents[index])
                inside = _point_in_convex(a, footprint) or _point_in_convex(b, footprint)
                touching = any(
                    segments_within(a, b, footprint[i], footprint[(i + 1) % 4], reach)
                    for i in range(4)
                )
                if inside or touching:
                    raise _refuse(f"space {space.space_ordinal} intrudes on {other.path_id}")
        for zone_id, interval in (
            (zone.zone_id, zone.side(path.path_id)[1]) for zone in zones if zone.side(path.path_id)
        ):
            if interval[0] <= space.access_end_mm and space.access_start_mm <= interval[1]:
                raise _refuse(f"space {space.space_ordinal} is reached inside zone {zone_id}")
        if space.access_start_mm <= exit_extent[path.path_id]:
            raise _refuse(f"space {space.space_ordinal} is reached inside a junction region")
        for band in bands:
            for band_path, low, high in band.intervals:
                if (
                    band_path == path.path_id
                    and low <= space.access_end_mm
                    and space.access_start_mm <= high
                ):
                    raise _refuse(
                        f"space {space.space_ordinal} is reached across crossing {band.ordinal}"
                    )
        stalls.append((space.identity, footprint))
        if not fitting:
            restrictions.append((space.identity, "*", "no class can use the space"))
        spaces[space.identity] = SpaceSpec(
            identity=space.identity,
            ordinal=space.space_ordinal,
            segment_ordinal=space.segment_ordinal,
            layout=space.layout,
            footprint=footprint,
            access_path=path.path_id,
            access_start=space.access_start_mm,
            access_end=space.access_end_mm,
            classes=tuple(fitting),
        )

    # Junction specs, conflicts, signal plans.
    zones_by_path: dict[str, list[tuple[int, tuple[int, int]]]] = {}
    for zone in zones:
        zones_by_path.setdefault(zone.first, []).append((zone.zone_id, zone.first_interval))
        zones_by_path.setdefault(zone.second, []).append((zone.zone_id, zone.second_interval))
    bands_by_path: dict[str, list[tuple[int, tuple[int, int]]]] = {}
    for band in bands:
        for path_id, low, high in band.intervals:
            bands_by_path.setdefault(path_id, []).append((band.band_id, (low, high)))

    def region_paths(connector_id: str) -> set[str]:
        return {connector_id, paths[connector_id].successors[0]}

    def region_zone_ids(connector_id: str) -> set[int]:
        found = {zone_id for zone_id, _ in zones_by_path.get(connector_id, [])}
        exit_lane = paths[connector_id].successors[0]
        found |= {
            zone_id
            for zone_id, interval in zones_by_path.get(exit_lane, [])
            if interval[0] <= exit_extent[exit_lane]
        }
        return found

    junctions: dict[int, JunctionSpec] = {}
    gates: dict[str, list[Gate]] = {}
    for ordinal in sorted(junction_records):
        record = junction_records[ordinal]
        policy = catalogs.policy(record.policy)
        members = sorted(junction_paths.get(ordinal, []))
        node = nodes[record.node_ordinal]
        conflicts = []
        region_of = {member: region_zone_ids(member) for member in members}
        for index, first_id in enumerate(members):
            for second_id in members[index + 1 :]:
                shared = region_of[first_id] & region_of[second_id]
                touching = [
                    zones[zone_id]
                    for zone_id in shared
                    if {zones[zone_id].first, zones[zone_id].second} & region_paths(first_id)
                    and {zones[zone_id].first, zones[zone_id].second} & region_paths(second_id)
                ]
                if touching:
                    conflicts.append((first_id, second_id))
        inbound = sorted(path_id for path_id in lane_ids if paths[path_id].end_junction == ordinal)
        approach_list = []
        for approach in sorted(
            approaches_by_junction.get(ordinal, []), key=lambda item: item.approach_ordinal
        ):
            lanes_in = tuple(
                path_id
                for path_id in inbound
                if paths[path_id].segment_ordinal == approach.segment_ordinal
            )
            if not lanes_in:
                raise _refuse(f"approach {approach.approach_ordinal} has no inbound lane")
            if approach.control not in policy.approach_controls:
                raise _refuse(
                    f"approach {approach.approach_ordinal} control breaks policy {policy.key}"
                )
            first_lane = paths[lanes_in[0]].line
            approach_list.append(
                ApproachSpec(
                    segment_ordinal=approach.segment_ordinal,
                    identity=approach.identity,
                    control=approach.control,
                    rank=approach.priority_rank,
                    inbound_lanes=lanes_in,
                    direction=first_lane.piece_direction(first_lane.piece_count - 1),
                )
            )
        covered_lanes = sorted(
            lane for approach in approach_list for lane in approach.inbound_lanes
        )
        if covered_lanes != inbound or len(set(covered_lanes)) != len(covered_lanes):
            raise _refuse(f"junction {ordinal} approaches do not cover its inbound lanes once each")
        approach_of = {
            lane: approach for approach in approach_list for lane in approach.inbound_lanes
        }
        ranks = sorted({approach.rank for approach in approach_list})
        if policy.rule == "priority":
            if len(ranks) < 2:
                raise _refuse(f"priority junction {ordinal} has no minor approach")
            for approach in approach_list:
                major = approach.rank == ranks[0]
                if major and approach.control != "priority":
                    raise _refuse(
                        f"junction {ordinal}: a major approach is stop or yield controlled"
                    )
                if not major and approach.control not in ("stop", "yield"):
                    raise _refuse(
                        f"junction {ordinal}: a minor approach has no stop or yield control"
                    )
                if major and len(approach.inbound_lanes) > 1:
                    raise _refuse(
                        f"junction {ordinal}: v1 has headways for a two-lane major street only"
                    )
        elif len(ranks) > 1:
            raise _refuse(f"junction {ordinal}: only a priority junction ranks its approaches")
        if policy.rule == "uncontrolled":
            for first_id, second_id in conflicts:
                if (
                    approach_of[paths[first_id].predecessors[0]]
                    != approach_of[paths[second_id].predecessors[0]]
                ):
                    raise _refuse(
                        f"uncontrolled junction {ordinal} has conflicting movements "
                        "from two approaches"
                    )
        signal = None
        controller = controller_of_junction.get(ordinal)
        if (policy.rule == "signal") != (controller is not None):
            raise _refuse(
                f"junction {ordinal}: a signal controller exists exactly when the rule is signal"
            )
        if controller is not None:
            plan = catalogs.plan(controller.plan)
            owned = groups_by_controller.get(controller.controller_ordinal, {})
            connector_groups: dict[str, str] = {}
            band_groups: dict[int, str] = {}
            for group in owned.values():
                kind = plan.group_kind(group.group)
                if kind == "vehicle" and group.crossing_ordinals:
                    raise _refuse(f"vehicle group {group.group} lists crossings")
                if kind == "pedestrian" and group.connector_ordinals:
                    raise _refuse(f"pedestrian group {group.group} lists connectors")
                for connector_ordinal in group.connector_ordinals:
                    data = connectors.get(connector_ordinal)
                    if data is None or data["record"].junction_ordinal != ordinal:
                        raise _refuse(f"group {group.group} lists a connector of another junction")
                    if data["path_id"] in connector_groups:
                        raise _refuse(f"connector {connector_ordinal} is in two groups")
                    connector_groups[data["path_id"]] = group.group
                for crossing_ordinal in group.crossing_ordinals:
                    band_id = band_of_crossing.get(crossing_ordinal)
                    if band_id is None or bands[band_id].junction != ordinal:
                        raise _refuse(
                            f"group {group.group} lists a crossing outside junction {ordinal}"
                        )
                    if bands[band_id].control != "signalised":
                        raise _refuse(
                            f"crossing {crossing_ordinal} is signalled but marked priority"
                        )
                    if band_id in band_groups:
                        raise _refuse(f"crossing {crossing_ordinal} is in two groups")
                    band_groups[band_id] = group.group
            if sorted(connector_groups) != members:
                raise _refuse(
                    f"junction {ordinal}: every connector is in exactly one vehicle group"
                )
            for band in bands:
                if (
                    band.junction == ordinal
                    and band.control == "signalised"
                    and band.band_id not in band_groups
                ):
                    raise _refuse(f"signalised crossing {band.ordinal} is in no group")
            # Conflicting movements may share right of way only when one yields by turn rank.
            for first_id, second_id in conflicts:
                first_group, second_group = connector_groups[first_id], connector_groups[second_id]
                together = any(
                    {first_group, second_group}
                    <= set(interval.vehicle_green) | set(interval.vehicle_amber)
                    for interval in plan.intervals
                )
                if not together:
                    continue
                if (
                    first_group == second_group
                    and approach_of[paths[first_id].predecessors[0]]
                    == approach_of[paths[second_id].predecessors[0]]
                ):
                    continue
                if policy.turn_rank(paths[first_id].turn) == policy.turn_rank(
                    paths[second_id].turn
                ):
                    raise _refuse(
                        f"plan {plan.key} lets conflicting {paths[first_id].turn} movements "
                        f"{paths[first_id].ordinal} and {paths[second_id].ordinal} go together"
                    )
            for band_id, group in band_groups.items():
                band = bands[band_id]
                clearance = _pedestrian_windows(plan, group)
                for walk_ms, clearance_ms in clearance:
                    need_clear = -(
                        -band.length_mm * _MS_PER_SECOND // plan.pedestrian_clearance_speed_mm_per_s
                    )
                    need_total = -(
                        -(band.length_mm + plan.pedestrian_total_extra_mm)
                        * _MS_PER_SECOND
                        // plan.pedestrian_total_speed_mm_per_s
                    )
                    if clearance_ms < need_clear or walk_ms + clearance_ms < need_total:
                        raise _refuse(
                            f"plan {plan.key} gives crossing {band.ordinal} "
                            "too little pedestrian time"
                        )
                walking = [
                    interval
                    for interval in plan.intervals
                    if group in interval.pedestrian_walk or group in interval.pedestrian_clearance
                ]
                for path_id, _, _ in band.intervals:
                    path = paths[path_id]
                    if path.kind != "connector" or path.turn != "straight":
                        continue
                    moving = connector_groups[path_id]
                    if any(moving in interval.vehicle_green for interval in walking):
                        raise _refuse(
                            f"plan {plan.key} sends straight connector {path.ordinal} "
                            f"through crossing {band.ordinal} while it walks"
                        )
                bands[band_id] = _replace_signal(band, (ordinal, group))
            signal = SignalSpec(
                controller_identity=controller.identity,
                plan=plan.key,
                offset_s=controller.offset_s,
                connector_groups=tuple(sorted(connector_groups.items())),
                band_groups=tuple(sorted(band_groups.items())),
            )
        for band in bands:
            if band.junction == ordinal and band.control == "signalised" and signal is None:
                raise _refuse(f"crossing {band.ordinal} is signalised at an unsignalled junction")
        junctions[ordinal] = JunctionSpec(
            ordinal=ordinal,
            identity=record.identity,
            node_ordinal=record.node_ordinal,
            position=(node.x_mm, node.y_mm),
            policy=policy.key,
            rule=policy.rule,
            approaches=tuple(approach_list),
            connectors=tuple(members),
            signal=signal,
            conflicts=tuple(sorted(conflicts)),
        )
        for lane_id in inbound:
            gates.setdefault(lane_id, []).append(
                Gate(lane_id, paths[lane_id].length, "junction", ordinal)
            )
    for band in bands:
        if band.junction is not None:
            continue
        if band.control == "signalised":
            raise _refuse(
                f"mid-block crossing {band.ordinal} is signalised; v1 has no mid-block signals"
            )
        for path_id, low, _ in band.intervals:
            gates.setdefault(path_id, []).append(Gate(path_id, low, "band", band.band_id))
    for path_id, path_gates in gates.items():
        path_gates.sort(key=lambda gate: (gate.position, gate.kind, gate.target))
        for first, second in pairwise(path_gates):
            if (
                second.position - first.position
                < paths[path_id].longest_body_mm + paths[path_id].widest_gap_mm
            ):
                raise _refuse(f"two gates on {path_id} are closer than one vehicle and its gap")
    for lane_id in lane_ids:
        path = paths[lane_id]
        need = exit_extent[lane_id] + path.longest_body_mm + path.widest_gap_mm
        if need > path.length:
            raise _refuse(f"lane {path.ordinal} is too short to leave its junction region")

    catalog_sha256 = catalogs.digest
    document = _document(
        scope,
        driving_side,
        ordered_paths,
        junctions,
        zones,
        bands,
        spaces,
        exit_extent,
        joint_extent,
        restrictions,
        catalog_sha256,
    )
    network = RoadNetwork(
        scope=scope,
        driving_side=driving_side,
        paths=ordered_paths,
        junctions=junctions,
        zones=tuple(zones),
        bands=tuple(bands),
        spaces=dict(sorted(spaces.items())),
        exit_extent=exit_extent,
        gates={path_id: tuple(items) for path_id, items in sorted(gates.items())},
        zones_by_path={key: tuple(sorted(value)) for key, value in zones_by_path.items()},
        bands_by_path={key: tuple(sorted(value)) for key, value in bands_by_path.items()},
        joint_extent=joint_extent,
        restrictions=tuple(sorted(restrictions)),
        catalog_sha256=catalog_sha256,
        document=document,
        digest=sha256_of_canonical(document).hex(),
    )
    return network


def _replace_signal(band: Band, signal: tuple[int, str]) -> Band:
    return Band(
        band_id=band.band_id,
        identity=band.identity,
        ordinal=band.ordinal,
        society_crossing_id=band.society_crossing_id,
        segment_ordinal=band.segment_ordinal,
        control=band.control,
        line=band.line,
        width_mm=band.width_mm,
        length_mm=band.length_mm,
        intervals=band.intervals,
        junction=band.junction,
        signal=signal,
    )


def _pedestrian_windows(plan: Any, group: str) -> list[tuple[int, int]]:
    """``(walk ms, clearance ms)`` for every walk run of ``group``, following the cycle round."""
    count = len(plan.intervals)
    windows = []
    for index, interval in enumerate(plan.intervals):
        previous = plan.intervals[index - 1]
        if group not in interval.pedestrian_walk or group in previous.pedestrian_walk:
            continue
        walk = 0
        step = index
        while group in plan.intervals[step % count].pedestrian_walk and walk < plan.cycle_ms:
            walk += plan.intervals[step % count].duration_ms
            step += 1
        clearance = 0
        while (
            group in plan.intervals[step % count].pedestrian_clearance
            and walk + clearance < plan.cycle_ms
        ):
            clearance += plan.intervals[step % count].duration_ms
            step += 1
        windows.append((walk, clearance))
    return windows


def _document(
    scope: str,
    driving_side: str,
    paths: Mapping[str, PathSpec],
    junctions: Mapping[int, JunctionSpec],
    zones: Sequence[Zone],
    bands: Sequence[Band],
    spaces: Mapping[str, SpaceSpec],
    exit_extent: Mapping[str, int],
    joint_extent: Mapping[tuple[str, str], int],
    restrictions: Sequence[tuple[str, str, str]],
    catalog_sha256: str,
) -> dict[str, Any]:
    """The canonical description a network digest covers. Everything the simulation reads."""
    return {
        "profile": NETWORK_PROFILE,
        "scope": scope,
        "driving_side": driving_side,
        "catalog_sha256": catalog_sha256,
        "paths": [
            {
                "path_id": path.path_id,
                "kind": path.kind,
                "points": [list(point) for point in path.line.points],
                "classes": list(path.classes),
                "speed_limit_mm_per_s": path.speed_limit_mm_per_s,
                "extents": [list(pair) for pair in path.extents],
                "successors": list(path.successors),
                "turn": path.turn,
                "exit_extent_mm": exit_extent.get(path.path_id, 0),
            }
            for path in paths.values()
        ],
        "joints": [
            {"from": first, "to": second, "extent_mm": extent}
            for (first, second), extent in sorted(joint_extent.items())
        ],
        "junctions": [
            {
                "ordinal": junction.ordinal,
                "identity": junction.identity,
                "policy": junction.policy,
                "approaches": [
                    {
                        "identity": approach.identity,
                        "control": approach.control,
                        "rank": approach.rank,
                        "inbound_lanes": list(approach.inbound_lanes),
                    }
                    for approach in junction.approaches
                ],
                "conflicts": [list(pair) for pair in junction.conflicts],
                "signal": None
                if junction.signal is None
                else {
                    "plan": junction.signal.plan,
                    "offset_s": junction.signal.offset_s,
                    "connector_groups": [list(pair) for pair in junction.signal.connector_groups],
                    "band_groups": [list(pair) for pair in junction.signal.band_groups],
                },
            }
            for junction in junctions.values()
        ],
        "zones": [
            {
                "zone_id": zone.zone_id,
                "first": zone.first,
                "first_interval": list(zone.first_interval),
                "second": zone.second,
                "second_interval": list(zone.second_interval),
            }
            for zone in zones
        ],
        "bands": [
            {
                "band_id": band.band_id,
                "identity": band.identity,
                "society_crossing_id": band.society_crossing_id,
                "control": band.control,
                "line": [list(point) for point in band.line],
                "width_mm": band.width_mm,
                "intervals": [list(item) for item in band.intervals],
                "junction": band.junction,
                "signal": None if band.signal is None else list(band.signal),
            }
            for band in bands
        ],
        "spaces": [
            {
                "identity": space.identity,
                "footprint": [list(point) for point in space.footprint],
                "access_path": space.access_path,
                "access": [space.access_start, space.access_end],
                "classes": list(space.classes),
            }
            for space in spaces.values()
        ],
        "restrictions": [list(item) for item in sorted(restrictions)],
    }


def segments_cross(first: Polyline, second: Polyline) -> bool:
    """Whether two polylines share a point. Used by tests of the fixture."""
    return any(
        segments_intersect(*first.piece(i), *second.piece(j))
        for i in range(first.piece_count)
        for j in range(second.piece_count)
    )
