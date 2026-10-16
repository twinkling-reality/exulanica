"""The checks of a tile document's streets and roads: segments and their nodes, streets, curbs and
the corners they turn, camber, crossings, lanes, junctions, lane connections, signals, parking and
stop lines.

:class:`_StreetChecks` is a part of :class:`~exulanica.grammar.grammars.city.document._Checker`,
which runs them with every other check.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import (
    INSIDE,
    OUTSIDE,
    edge_run_length,
    integer_sqrt,
    point_in_ring,
    rings_disjoint,
)
from exulanica.grammar.grammars.city.common import SIDE_CODES
from exulanica.grammar.grammars.city.corners import (
    corner_box,
    frontage_corner,
    junction_fill_box,
    strip_box,
)
from exulanica.grammar.grammars.city.corners import corner_centre as _corner_centre
from exulanica.grammar.grammars.city.corners import walk_round_face as _walk_round_face
from exulanica.grammar.grammars.city.document_plan import (
    _CORNER_FOLLOWER_FROM_VERSION,
    _NORMAL_ROUNDING_MM,
    _CheckerCore,
    _counter_clockwise,
    _extent_ring,
    _fail,
    _holds,
    _in_extent_plan,
    _near_ring,
)
from exulanica.grammar.grammars.city.roads import (
    JunctionApproachRecord,
    JunctionRecord,
    LaneConnectionRecord,
    LaneRecord,
    ParkingSpaceRecord,
    SignalRecord,
)
from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord, StreetTreeRecord
from exulanica.grammar.grammars.city.streets import (
    BlockRecord,
    CrossingRecord,
    CurbEdgeRecord,
    StreetRecord,
    StreetSegmentRecord,
)


class _StreetChecks(_CheckerCore):
    """The street and road checks of :class:`~exulanica.grammar.grammars.city.document._Checker`."""

    # -- streets ---------------------------------------------------------------------------

    def check_streets(self) -> None:
        for segment in self.of(StreetSegmentRecord):
            start = self.carried(segment.start_node_identity)
            end = self.carried(segment.end_node_identity)
            if start is not None and segment.centreline_mm[0] != (
                start.x_mm,
                start.y_mm,
                start.z_mm,
            ):
                raise _fail("segment_ends", f"segment {segment.identity} starts off its node")
            if end is not None and segment.centreline_mm[-1] != (end.x_mm, end.y_mm, end.z_mm):
                raise _fail("segment_ends", f"segment {segment.identity} ends off its node")
            street = self.carried(segment.street_identity)
            if street is None:
                continue
            if segment.identity not in street.segment_identities:
                raise _fail("street_segments", f"street {street.identity} omits a segment")
            name = self.entry("street-name", street.name)
            if segment.hierarchy not in name["hierarchies"]:
                raise _fail("street_name", f"{street.name} does not suit a {segment.hierarchy}")
        for street in self.of(StreetRecord):
            if street.name_text != self.entry("street-name", street.name)["text"]:
                raise _fail("street_name", f"street {street.identity} states another name text")
            for identity in street.segment_identities:
                segment = self.carried(identity)
                if segment is not None and segment.street_identity != street.identity:
                    raise _fail("street_segments", f"a segment of {street.identity} names another")
        self._check_curbs()
        self._check_camber()
        self._check_crossings()

    def _segment_curbs(self, segment_identity: str) -> dict[str, CurbEdgeRecord]:
        return {
            curb.side: curb
            for curb in self.of(CurbEdgeRecord)
            if curb.segment_identity == segment_identity
        }

    def _check_curbs(self) -> None:
        followers: Counter[str] = Counter()
        owned = {record.identity for record in self.grammar.owned}  # type: ignore[attr-defined]
        for curb in self.of(CurbEdgeRecord):
            self.report.kerb_heights_mm += (curb.kerb_height_mm,)
            segment = self.get(curb.segment_identity)
            for point in curb.kerb_line_mm:
                if not _in_extent_plan(segment.extent, point[0], point[1]):
                    raise _fail("kerb_line", f"curb {curb.identity} leaves its segment's extent")
            if not _holds(curb.extent, strip_box(curb)):
                raise _fail(
                    "curb_extent", f"curb {curb.identity}'s extent does not hold its straight part"
                )
            for block_identity in curb.block_identity:
                block = self.carried(block_identity)
                if block is not None:
                    self._check_frontage_line(curb, block)
            for next_identity in curb.next_curb_identity:
                followers[next_identity] += 1
                follower = self.carried(next_identity)
                if follower is None:
                    # A tile draws the corner each curb it owns turns, and a rounded corner's arc
                    # ends on its follower: from version 5 a tile that owns such a curb and does
                    # not carry its follower is refused here rather than by the tessellator. A
                    # straight join (radius 0) reads nothing from its follower.
                    if (
                        self.grammar.grammar_version >= _CORNER_FOLLOWER_FROM_VERSION
                        and curb.identity in owned
                        and curb.corner_radius_mm > 0
                    ):
                        raise _fail(
                            "corner_follower",
                            f"curb {curb.identity} turns a {curb.corner_radius_mm} mm corner "
                            f"into curb {next_identity}, which the tile does not carry",
                        )
                    continue
                ends = {segment.start_node_identity, segment.end_node_identity}
                other = self.get(follower.segment_identity)
                if not ends & {other.start_node_identity, other.end_node_identity}:
                    raise _fail("curb_graph", f"curb {curb.identity} is followed across no node")
                self._check_corner(curb, follower)
                self._check_corner_extent(curb, follower)
        branching = [identity for identity, count in followers.items() if count > 1]
        if branching:
            raise _fail("curb_graph", f"curbs followed by more than one curb: {branching}")

    def _check_corner(self, curb: CurbEdgeRecord, follower: CurbEdgeRecord) -> None:
        """The tangent points of the corner from ``curb`` to ``follower`` fit its radius."""
        before, after = _walk_round_face(curb), _walk_round_face(follower)
        p, q = before[-1], after[0]
        radius = curb.corner_radius_mm
        where = f"curb {curb.identity}'s corner to {follower.identity}"
        if radius == 0:
            if p != q:
                raise _fail("corner_radius", f"{where} has no radius and {p} is not {q}")
            return
        leaving = (p[0] - before[-2][0], p[1] - before[-2][1])
        joining = (after[1][0] - q[0], after[1][1] - q[1])
        cross = leaving[0] * joining[1] - leaving[1] * joining[0]
        if cross == 0:
            raise _fail("corner_radius", f"{where} runs straight on and states a radius")
        turn = 1 if cross > 0 else -1
        from_p = _corner_centre(p, leaving, radius, turn)
        from_q = _corner_centre(q, joining, radius, turn)
        if (
            abs(from_p[0] - from_q[0]) > _NORMAL_ROUNDING_MM
            or abs(from_p[1] - from_q[1]) > _NORMAL_ROUNDING_MM
        ):
            raise _fail(
                "corner_radius",
                f"{where}: tangent points {p} and {q} find centres {from_p} and {from_q}, "
                f"not one arc of radius {radius}",
            )

    def _check_corner_extent(self, curb: CurbEdgeRecord, follower: CurbEdgeRecord) -> None:
        """The curb stating a radius owns its corner, and its extent holds the corner's box."""
        try:
            box = corner_box(curb, follower)
        except InvalidRecordError as error:
            raise _fail("corner_extent", str(error)) from error
        if box is None:
            return
        if not _holds(curb.extent, box):
            raise _fail(
                "corner_extent",
                f"curb {curb.identity}'s extent does not hold its corner to {follower.identity}, "
                f"{box}",
            )
        for block_identity in curb.block_identity:
            block = self.carried(block_identity)
            if block is not None and frontage_corner(curb, follower) not in block.boundary_mm:
                raise _fail(
                    "corner_extent",
                    f"curb {curb.identity}'s frontage corner is not a corner of block "
                    f"{block.identity}",
                )

    def _check_junction_extent(self, junction: JunctionRecord) -> None:
        """A junction owns the carriageway fill inside its kerb arcs, and its extent holds it."""
        node = self.carried(junction.node_identity)
        legs = [self.carried(identity) for identity in junction.segment_identities]
        if node is None or None in legs:
            return
        box = junction_fill_box(node, legs, self._segment_curbs, self.carried)
        if box is not None and not _holds(junction.extent, box):
            raise _fail(
                "junction_extent",
                f"junction {junction.identity}'s extent does not hold its fill inside the kerb "
                f"arcs, {box}",
            )

    def _check_frontage_line(self, curb: CurbEdgeRecord, block: BlockRecord) -> None:
        offset = curb.kerb_width_mm + curb.footway_width_mm
        sign = 1 if curb.side == "left" else -1
        for here, after in zip(curb.kerb_line_mm, curb.kerb_line_mm[1:], strict=False):
            dx, dy = after[0] - here[0], after[1] - here[1]
            length = integer_sqrt(dx * dx + dy * dy)
            if length == 0:
                continue
            middle = ((here[0] + after[0]) // 2, (here[1] + after[1]) // 2)
            point = (
                middle[0] + (sign * -dy * offset) // length,
                middle[1] + (sign * dx * offset) // length,
            )
            if not _near_ring(point, block.boundary_mm, _NORMAL_ROUNDING_MM):
                raise _fail(
                    "frontage_line",
                    f"curb {curb.identity}: kerb plus footway does not reach block "
                    f"{block.identity}'s frontage line at {point}",
                )

    def _check_camber(self) -> None:
        """On a level segment, every kerb line point lies the camber's fall below the crown."""
        for curb in self.of(CurbEdgeRecord):
            segment = self.get(curb.segment_identity)
            crowns = {point[2] for point in segment.centreline_mm}
            if len(crowns) != 1:
                continue
            crown = crowns.pop()
            fall = (segment.carriageway_width_mm // 2) * segment.camber_millionths // 1_000_000
            if any(point[2] != crown - fall for point in curb.kerb_line_mm):
                raise _fail(
                    "camber", f"curb {curb.identity} is not the camber's fall below the crown"
                )

    def _check_crossings(self) -> None:
        by_segment: dict[str, list[CrossingRecord]] = defaultdict(list)
        for crossing in self.of(CrossingRecord):
            segment = self.get(crossing.segment_identity)
            if crossing.offset_mm > segment.length_mm:
                raise _fail("crossing_offset", f"crossing {crossing.identity} is off its segment")
            kind = self.entry("crossing-type", crossing.crossing_type)
            if not kind["width_minimum_mm"] <= crossing.width_mm <= kind["width_maximum_mm"]:
                raise _fail("crossing_width", f"crossing {crossing.identity} is outside its type")
            if (kind["signal"] == "required") != bool(crossing.signal_identity):
                raise _fail(
                    "crossing_signal", f"crossing {crossing.identity} and its type disagree"
                )
            if kind["kerb"] == "flush" and crossing.kerb_upstand_mm:
                raise _fail(
                    "crossing_kerb", f"crossing {crossing.identity} is flush with an upstand"
                )
            by_segment[crossing.segment_identity].append(crossing)
        for crossings in by_segment.values():
            ordered = sorted(crossings, key=lambda item: item.crossing_ordinal)
            offsets = [item.offset_mm for item in ordered]
            if offsets != sorted(set(offsets)):
                raise _fail("crossing_order", "crossing ordinals increase with offset")

    # -- roads -----------------------------------------------------------------------------

    def _lane_end_node(self, lane: LaneRecord) -> str:
        segment = self.get(lane.segment_identity)
        return (
            segment.end_node_identity
            if lane.direction == "forward"
            else segment.start_node_identity
        )

    def _lane_start_node(self, lane: LaneRecord) -> str:
        segment = self.get(lane.segment_identity)
        return (
            segment.start_node_identity
            if lane.direction == "forward"
            else segment.end_node_identity
        )

    def check_roads(self) -> None:
        lanes_by_segment: dict[str, list[LaneRecord]] = defaultdict(list)
        for lane in self.of(LaneRecord):
            lanes_by_segment[lane.segment_identity].append(lane)
            use = self.entry("lane-use", lane.lane_use)
            if (use["traffic"] == "none") != (lane.direction == "none"):
                raise _fail("lane_use", f"lane {lane.identity} and its use disagree on traffic")
            if not use["width_minimum_mm"] <= lane.width_mm <= use["width_maximum_mm"]:
                raise _fail("lane_width", f"lane {lane.identity} is outside its use's widths")
            segment = self.get(lane.segment_identity)
            if max(lane.start_offset_mm, lane.end_offset_mm) > segment.length_mm:
                raise _fail("lane_offsets", f"lane {lane.identity} runs past its segment")
        for segment_identity, lanes in lanes_by_segment.items():
            if not self.complete(segment_identity):
                continue
            segment = self.get(segment_identity)
            indices = sorted(lane.lane_index for lane in lanes)
            if indices != list(range(len(indices))):
                raise _fail(
                    "lane_indices", f"segment {segment_identity} numbers its lanes with gaps"
                )
            curbs = self._segment_curbs(segment_identity)
            if set(curbs) == set(SIDE_CODES):
                total = sum(lane.width_mm for lane in lanes) + sum(
                    curb.gutter_width_mm for curb in curbs.values()
                )
                if total != segment.carriageway_width_mm:
                    raise _fail(
                        "carriageway_width",
                        f"segment {segment_identity}: lanes and gutters make {total}, "
                        f"not {segment.carriageway_width_mm}",
                    )
        self._check_junctions()
        self._check_connections()
        self._check_signals()
        self._check_parking()
        self._check_stop_lines()

    def _check_junctions(self) -> None:
        segments = self.of(StreetSegmentRecord)
        for junction in self.of(JunctionRecord):
            self._check_junction_extent(junction)
            node = self.carried(junction.node_identity)
            touching = {
                segment.identity
                for segment in segments
                if junction.node_identity
                in (segment.start_node_identity, segment.end_node_identity)
            }
            listed = [self.carried(identity) for identity in junction.segment_identities]
            carried_listed = {segment.identity for segment in listed if segment is not None}
            if carried_listed != touching:
                raise _fail(
                    "junction_segments", f"junction {junction.identity} lists other segments"
                )
            if node is not None and None not in listed:
                directions = []
                for segment in listed:
                    line = segment.centreline_mm
                    away = (
                        line[1]
                        if segment.start_node_identity == junction.node_identity
                        else line[-2]
                    )
                    directions.append((away[0] - node.x_mm, away[1] - node.y_mm))
                if not _counter_clockwise(directions):
                    raise _fail(
                        "junction_order", f"junction {junction.identity} is not counter-clockwise"
                    )
            control = self.entry("junction-control", junction.control)
            if (control["signal"] == "required") != bool(junction.signal_identity):
                raise _fail(
                    "junction_signal", f"junction {junction.identity} and its control disagree"
                )
            for signal_identity in junction.signal_identity:
                signal = self.carried(signal_identity)
                if signal is not None and signal.controls_identity != junction.identity:
                    raise _fail(
                        "junction_signal", f"junction {junction.identity}'s signal is elsewhere"
                    )
            inbound = {
                lane.segment_identity
                for lane in self.of(LaneRecord)
                if lane.direction != "none" and self._lane_end_node(lane) == junction.node_identity
            }
            approaches = {
                approach.segment_identity: approach
                for approach in self.of(JunctionApproachRecord)
                if approach.junction_identity == junction.identity
            }
            lane_complete = {identity for identity in approaches if self.complete(identity)}
            if not inbound <= set(approaches) or not lane_complete <= inbound:
                raise _fail(
                    "approaches",
                    f"junction {junction.identity} needs one approach per inbound segment",
                )
            for approach in approaches.values():
                if (
                    junction.segment_identities[approach.approach_ordinal]
                    != approach.segment_identity
                ):
                    raise _fail("approaches", f"approach {approach.identity} has another ordinal")
                if approach.control not in control["approach_controls"]:
                    raise _fail(
                        "approaches",
                        f"approach {approach.identity} is not a {junction.control} control",
                    )

    def _check_connections(self) -> None:
        for connection in self.of(LaneConnectionRecord):
            junction = self.get(connection.junction_identity)
            source = self.carried(connection.from_lane_identity)
            target = self.carried(connection.to_lane_identity)
            for lane in (source, target):
                if lane is not None and lane.direction == "none":
                    raise _fail(
                        "connection_lanes",
                        f"connection {connection.identity} joins a lane without traffic",
                    )
            if source is not None and self._lane_end_node(source) != junction.node_identity:
                raise _fail(
                    "connection_lanes",
                    f"connection {connection.identity}'s lane does not reach the node",
                )
            if target is not None and self._lane_start_node(target) != junction.node_identity:
                raise _fail(
                    "connection_lanes",
                    f"connection {connection.identity}'s lane does not leave the node",
                )
            if source is not None and connection.path_mm[0] != source.centreline_mm[-1]:
                raise _fail(
                    "connection_path", f"connection {connection.identity} starts off its stop line"
                )
            if target is not None and connection.path_mm[-1] != target.centreline_mm[0]:
                raise _fail(
                    "connection_path", f"connection {connection.identity} ends off its lane"
                )
            if source is not None and connection.movement not in source.turns:
                raise _fail(
                    "connection_turn",
                    f"connection {connection.identity} makes a turn its lane forbids",
                )

    def _check_signals(self) -> None:
        for signal in self.of(SignalRecord):
            controlled = self.get(signal.controls_identity)
            members = [
                identity
                for group in signal.groups
                for identity in (*group.connection_identities, *group.crossing_identities)
            ]
            if isinstance(controlled, JunctionRecord):
                junction_connections = {
                    connection.identity
                    for connection in self.of(LaneConnectionRecord)
                    if connection.junction_identity == controlled.identity
                }
                grouped = {
                    identity for group in signal.groups for identity in group.connection_identities
                }
                complete = self.complete(controlled.identity)
                if not junction_connections <= grouped or (
                    complete and grouped != junction_connections
                ):
                    raise _fail(
                        "signal_groups", f"signal {signal.identity} groups another set of movements"
                    )
                touching = set(controlled.segment_identities)
                for group in signal.groups:
                    for identity in group.crossing_identities:
                        crossing = self.carried(identity)
                        if crossing is not None and crossing.segment_identity not in touching:
                            raise _fail(
                                "signal_groups", f"signal {signal.identity} releases a far crossing"
                            )
            elif any(group.connection_identities for group in signal.groups):
                raise _fail(
                    "signal_groups", f"crossing signal {signal.identity} releases movements"
                )
            for crossing in self.of(CrossingRecord):
                if (
                    crossing.signal_identity == (signal.identity,)
                    and crossing.identity not in members
                ):
                    raise _fail(
                        "signal_groups", f"signal {signal.identity} leaves its crossing out"
                    )
            for head in signal.heads:
                furniture = self.carried(head.furniture_identity)
                if (
                    furniture is not None
                    and self.entry("street-furniture", furniture.furniture_class)["category"]
                    != "signal"
                ):
                    raise _fail("signal_heads", f"signal {signal.identity}'s head is not a signal")
                if head.serves_identity not in members:
                    raise _fail("signal_heads", f"signal {signal.identity}'s head serves no group")

    def _check_parking(self) -> None:
        for space in self.of(ParkingSpaceRecord):
            kind = self.entry("parking-kind", space.parking_kind)
            if kind["placement"] != space.placement:
                raise _fail(
                    "parking_placement", f"space {space.identity} is not where its kind goes"
                )
            curb = self.carried(space.curb_identity)
            if curb is not None and curb.segment_identity != space.segment_identity:
                raise _fail("parking_curb", f"space {space.identity}'s curb is on another segment")
            access = self.carried(space.access_lane_identity)
            if access is not None:
                if access.segment_identity != space.segment_identity or access.direction == "none":
                    raise _fail("parking_access", f"space {space.identity}'s access lane is wrong")
                low, high = sorted((access.start_offset_mm, access.end_offset_mm))
                if not low <= space.access_start_mm < space.access_end_mm <= high:
                    raise _fail(
                        "parking_access", f"space {space.identity}'s access stretch leaves its lane"
                    )
            sides = sorted(edge_run_length(space.footprint_mm, index) for index in range(4))
            if not (
                kind["width_minimum_mm"] <= sides[0] <= kind["width_maximum_mm"]
                and kind["length_minimum_mm"] <= sides[-1] <= kind["length_maximum_mm"]
            ):
                raise _fail("parking_size", f"space {space.identity} is not its kind's size")
            if space.placement == "carriageway":
                parking_lane = self.carried(space.lane_identity[0])
                if parking_lane is not None and (
                    parking_lane.segment_identity != space.segment_identity
                    or parking_lane.lane_use != "parking"
                ):
                    raise _fail("parking_lane", f"space {space.identity} is not in a parking lane")
            else:
                self._check_footway_parking(space)

    def _check_footway_parking(self, space: ParkingSpaceRecord) -> None:
        capacity = 0
        stands = [self.carried(identity) for identity in space.furniture_identities]
        for stand in stands:
            if stand is None:
                continue
            entry = self.entry("street-furniture", stand.furniture_class)
            if entry["category"] != "cycle_parking" or stand.curb_identity != space.curb_identity:
                raise _fail(
                    "cycle_parking", f"space {space.identity} lists a stand that is not its own"
                )
            if point_in_ring((stand.x_mm, stand.y_mm), space.footprint_mm) != INSIDE:
                raise _fail("cycle_parking", f"space {space.identity}'s stand stands outside it")
            capacity += entry["bicycles_per_stand"]
        if None not in stands and space.capacity > capacity:
            raise _fail(
                "cycle_parking", f"space {space.identity} holds more bicycles than its stands"
            )
        for tree in self.of(StreetTreeRecord):
            if not rings_disjoint(tree.pit_mm, space.footprint_mm):
                raise _fail("cycle_parking", f"space {space.identity} overlaps a tree pit")
        for crossing in self.of(CrossingRecord):
            if not rings_disjoint(_extent_ring(crossing.extent), space.footprint_mm):
                raise _fail("cycle_parking", f"space {space.identity} overlaps a crossing")
        for furniture in self.of(StreetFurnitureRecord):
            if furniture.identity in space.furniture_identities:
                continue
            if point_in_ring((furniture.x_mm, furniture.y_mm), space.footprint_mm) != OUTSIDE:
                raise _fail(
                    "cycle_parking", f"space {space.identity} covers furniture it does not list"
                )

    def _check_stop_lines(self) -> None:
        """No crossing band contains a stop line, and a crossing a junction's signal releases lies
        between that junction's stop lines and its node."""
        junctions = {junction.node_identity: junction for junction in self.of(JunctionRecord)}
        for crossing in self.of(CrossingRecord):
            low = crossing.offset_mm - crossing.width_mm // 2
            high = low + crossing.width_mm
            released_by = {
                signal.controls_identity
                for signal in map(self.carried, crossing.signal_identity)
                if signal is not None
            }
            for lane in self.of(LaneRecord):
                if lane.segment_identity != crossing.segment_identity or lane.direction == "none":
                    continue
                node = self._lane_end_node(lane)
                if node not in junctions:
                    continue
                stop = lane.end_offset_mm
                if low < stop < high:
                    raise _fail("stop_line", f"crossing {crossing.identity} contains a stop line")
                if junctions[node].identity not in released_by:
                    continue
                beyond = low >= stop if lane.direction == "forward" else high <= stop
                if not beyond:
                    raise _fail(
                        "stop_line",
                        f"crossing {crossing.identity} is not between lane {lane.identity}'s "
                        "stop line and its junction",
                    )
