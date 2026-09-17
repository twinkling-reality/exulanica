"""The road network compiler: city records in through the converter, a checked network or a refusal.

The fixture in ``traffic_network_fixture`` is built only from city grammar version 2 records. This
file pins what it compiles to, that the network names every path, junction, crossing and space by
the identity of the city record it came from, that the compiled conflict zones really contain
every place two corridors meet on that geometry, and that each thing v1 cannot simulate correctly
is refused with its reason rather than approximated.
"""

from __future__ import annotations

import dataclasses
import json
import random
import shutil
from collections import Counter
from functools import cache
from itertools import pairwise
from math import isqrt
from pathlib import Path

import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city.districts import DistrictRecord
from exulanica.grammar.grammars.city.roads import (
    JunctionApproachRecord,
    JunctionRecord,
    LaneConnectionRecord,
    LaneRecord,
    ParkingSpaceRecord,
    SignalGroup,
    SignalRecord,
)
from exulanica.grammar.grammars.city.streets import CrossingRecord, StreetSegmentRecord
from exulanica.traffic.catalogs import CATALOG_DIRECTORY, load_traffic_catalogs
from exulanica.traffic.city_roads import road_input_from_city
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.traffic.geometry import Polyline, convex_overlap, rectangle
from exulanica.traffic.network import NETWORK_PROFILE, compile_network

import traffic_network_fixture as fixture_module
from traffic_network_fixture import CITY, NODES, build_records, identity


def _compile(records, catalogs=None):
    catalogs = catalogs or load_traffic_catalogs()
    return compile_network(road_input_from_city(records, catalogs, city_identity=CITY), catalogs)


@cache
def _network():
    return _compile(build_records())


def _of(kind: type) -> list:
    return [record for record in build_records() if type(record) is kind]


def _changed(change) -> tuple[object, ...]:
    """The fixture records with ``change`` applied to each; ``None`` drops a record."""
    out = []
    for record in build_records():
        changed = change(record)
        if changed is not None:
            out.append(changed)
    assert out != list(build_records()), "the change touched nothing"
    return tuple(out)


def _refused(records, fragment: str, catalogs=None) -> None:
    with pytest.raises(UnsupportedNetworkError) as caught:
        _compile(records, catalogs)
    assert fragment in str(caught.value), str(caught.value)


def _segment(ordinal: int) -> StreetSegmentRecord:
    [segment] = [record for record in _of(StreetSegmentRecord) if record.segment_ordinal == ordinal]
    return segment


def _lane(segment: int, index: int) -> LaneRecord:
    owner = _segment(segment).identity
    [lane] = [
        record
        for record in _of(LaneRecord)
        if record.segment_identity == owner and record.lane_index == index
    ]
    return lane


def _node(name: str) -> str:
    return identity("street_node", CITY, NODES[name])


def _junction(name: str) -> JunctionRecord:
    return next(record for record in _of(JunctionRecord) if record.node_identity == _node(name))


def _crossing(segment: int, ordinal: int) -> CrossingRecord:
    owner = _segment(segment).identity
    return next(
        record
        for record in _of(CrossingRecord)
        if record.segment_identity == owner and record.crossing_ordinal == ordinal
    )


# ---------------------------------------------------------------------------------------------
# What the fixture compiles to


def test_the_fixture_compiles_to_the_expected_network():
    network = _network()
    lanes = [path for path in network.paths.values() if path.kind == "lane"]
    connectors = [path for path in network.paths.values() if path.kind == "connector"]
    # 24 lane records, of which the 8 parking lanes carry no traffic and are no path.
    assert len(_of(LaneRecord)) == 24
    assert (len(network.paths), len(lanes), len(connectors)) == (52, 16, 36)
    assert len(network.zones) == 88
    assert Counter((space.kind, space.capacity) for space in network.spaces.values()) == {
        ("general", 1): 16,
        ("bus_layover", 1): 8,
        ("loading", 1): 8,
        ("accessible", 1): 8,
        ("cycle_stand", 4): 8,
    }
    policies = {junction.node: junction.policy for junction in network.junctions.values()}
    assert policies == {_node(name): control for name, control in fixture_module.CONTROLS.items()}
    signalised = network.junctions[_junction("C").identity]
    assert signalised.signal is not None and signalised.signal.plan == "fixed_two_phase_60s"
    assert sum(junction.signal is not None for junction in network.junctions.values()) == 1
    assert network.restrictions == ()
    assert network.driving_side == "right" and network.city == CITY
    # Twelve movements at the four-way centre, six at each T junction.
    assert sorted(len(junction.connectors) for junction in network.junctions.values()) == [
        6,
        6,
        6,
        6,
        12,
    ]
    assert network.segment_ordinals == {
        segment.identity: segment.segment_ordinal for segment in _of(StreetSegmentRecord)
    }


def test_the_network_names_everything_by_the_identity_of_its_city_record():
    network = _network()
    traffic_lanes = {record.identity for record in _of(LaneRecord) if record.direction != "none"}
    lanes = {path.identity for path in network.paths.values() if path.kind == "lane"}
    assert lanes == traffic_lanes
    assert {path.identity for path in network.paths.values() if path.kind == "connector"} == {
        record.identity for record in _of(LaneConnectionRecord)
    }
    assert all(path_id.endswith(path.identity) for path_id, path in network.paths.items())
    assert set(network.junctions) == {record.identity for record in _of(JunctionRecord)}
    assert {band.identity for band in network.bands} == {
        record.identity for record in _of(CrossingRecord)
    }
    assert set(network.spaces) == {record.identity for record in _of(ParkingSpaceRecord)}


def test_crossings_are_bands_at_junctions_and_mid_block():
    network = _network()
    assert len(network.bands) == 20
    junction_bands = [band for band in network.bands if band.junction is not None]
    mid_block = [band for band in network.bands if band.junction is None]
    assert len(junction_bands) == 16 and len(mid_block) == 4
    assert sorted(band.society_crossing_id for band in mid_block) == [
        f"crossing:{segment}:52750" for segment in range(4)
    ]
    signalised = [band for band in network.bands if band.control == "signalised"]
    assert len(signalised) == 4
    centre = _junction("C").identity
    assert all(band.junction == centre and band.signal is not None for band in signalised)
    for band in network.bands:
        assert network.band_by_society_id(band.society_crossing_id) is band
        assert network.band(band.identity) is band
        segment, offset = band.society_crossing_id.split(":")[1:]
        assert int(segment) == network.segment_ordinals[band.segment] and int(offset) > 0
        assert band.intervals, band.society_crossing_id
    with pytest.raises(UnsupportedNetworkError, match="no crossing"):
        network.band_by_society_id("crossing:9:1")


def test_a_crossing_on_a_lane_holds_exactly_the_positions_under_its_band():
    network = _network()
    [band] = [band for band in network.bands if band.society_crossing_id == "crossing:0:52750"]
    forward = f"lane:{_lane(0, 2).identity}"
    # The forward lane starts 20 m out, so the 3 m band centred 52.75 m out spans 31.25 to 34.25
    # m along it, and a millimetre each way.
    assert (forward, 31_249, 34_251) in band.intervals


def test_gates_sit_at_stop_lines_and_mid_block_crossings_far_enough_apart():
    network = _network()
    gates = [gate for items in network.gates.values() for gate in items]
    junction_gates = [gate for gate in gates if gate.kind == "junction"]
    band_gates = [gate for gate in gates if gate.kind == "band"]
    assert (len(junction_gates), len(band_gates)) == (16, 8)
    for gate in junction_gates:
        path = network.paths[gate.path_id]
        assert path.kind == "lane" and gate.position == path.length
        assert gate.target == path.end_junction
    for gate in band_gates:
        band = network.band(gate.target)
        assert band.junction is None
        assert (gate.path_id, gate.position) in {(path, low) for path, low, _ in band.intervals}
    for path_id, items in network.gates.items():
        path = network.paths[path_id]
        for first, second in pairwise(items):
            assert second.position - first.position >= path.longest_body_mm + path.widest_gap_mm


def test_zones_joints_and_exit_extents_stay_on_their_paths():
    network = _network()
    for zone in network.zones:
        for path_id, (low, high) in (
            (zone.first, zone.first_interval),
            (zone.second, zone.second_interval),
        ):
            path = network.paths[path_id]
            assert 0 <= low <= high <= path.length
            assert zone.junction in (path.end_junction, path.start_junction)
        assert network.paths[zone.first].kind == "connector"
    for (first, second), extent in network.joint_extent.items():
        assert second in network.paths[first].successors
        assert 0 <= extent <= network.paths[second].length
    # Lanes start 20 m out, beyond every connection corridor, so no junction region reaches onto
    # a lane in this fixture, and no crossing band lies on a lane end.
    assert set(network.exit_extent.values()) == {0}


@cache
def _corridor(path_id: str, start: int, end: int) -> tuple[tuple[tuple[int, int], ...], ...]:
    path = _network().paths[path_id]
    shapes = []
    for index, a, b in path.line.span(start, end):
        shape = rectangle(a, b, *path.extents[index])
        if shape is not None:
            shapes.append(shape)
    return tuple(shapes)


def _box(shapes) -> tuple[int, int, int, int]:
    xs = [point[0] for shape in shapes for point in shape]
    ys = [point[1] for shape in shapes for point in shape]
    return min(xs), min(ys), max(xs), max(ys)


def _meeting_spans(path_id: str, other_id: str, step: int) -> list[tuple[int, int]]:
    """The spans of ``path_id``, ``step`` long, whose corridor meets the whole of ``other_id``."""
    network = _network()
    other = _corridor(other_id, 0, network.paths[other_id].length)
    other_box = _box(other)
    found = []
    for start in range(0, network.paths[path_id].length, step):
        end = min(start + step, network.paths[path_id].length)
        mine = _corridor(path_id, start, end)
        box = _box(mine)
        if (
            box[2] < other_box[0]
            or other_box[2] < box[0]
            or box[3] < other_box[1]
            or other_box[3] < box[1]
        ):
            continue
        if any(convex_overlap(shape, theirs) for shape in mine for theirs in other):
            found.append((start, end))
    return found


def test_every_place_two_movements_meet_lies_inside_their_conflict_zone():
    """The collision rule on the fixture's own geometry: no meeting outside a zone interval."""
    network = _network()
    zones = {}
    for zone in network.zones:
        zones[(zone.first, zone.second)] = (zone.first_interval, zone.second_interval)
        zones[(zone.second, zone.first)] = (zone.second_interval, zone.first_interval)
    pairs = 0
    meetings = 0
    for junction in network.junctions.values():
        outbound = [
            path.path_id
            for path in network.paths.values()
            if path.kind == "lane" and path.start_junction == junction.identity
        ]
        for connector in junction.connectors:
            others = [other for other in junction.connectors if other != connector]
            others += [lane for lane in outbound if lane not in network.paths[connector].successors]
            for other in others:
                pairs += 1
                for side, first, second in ((0, connector, other), (1, other, connector)):
                    spans = _meeting_spans(first, second, 250)
                    if not spans:
                        continue
                    meetings += len(spans)
                    assert (connector, other) in zones, (junction.identity, first, second, spans)
                    low, high = zones[(connector, other)][side]
                    for start, end in spans:
                        assert low <= end and start <= high, (first, second, start, end, low, high)
    # Each movement against every other movement of its junction and every outbound lane but
    # its own: twelve movements and three such lanes at the centre, six and two at a T.
    assert pairs == 12 * (11 + 3) + 4 * 6 * (5 + 2)
    assert meetings > 1_000


# ---------------------------------------------------------------------------------------------
# Digest


def _shuffled(records: tuple[object, ...]) -> tuple[object, ...]:
    shuffled = list(records)
    random.Random(19).shuffle(shuffled)
    assert shuffled != list(records)
    return tuple(shuffled)


def test_the_digest_is_the_canonical_document_and_ignores_record_order():
    network = _network()
    assert network.document["profile"] == NETWORK_PROFILE
    assert network.digest == sha256_of_canonical(network.document).hex()
    assert network.catalog_sha256 == load_traffic_catalogs().digest
    for records in (tuple(reversed(build_records())), _shuffled(build_records())):
        reordered = _compile(records)
        assert reordered.document == network.document
        assert reordered.digest == network.digest
    faster = _changed(
        lambda record: (
            dataclasses.replace(record, speed_limit_mm_s=11_111)
            if type(record) is StreetSegmentRecord and record.segment_ordinal == 0
            else record
        )
    )
    assert _compile(faster).digest != network.digest


# ---------------------------------------------------------------------------------------------
# Refusals


def test_left_hand_traffic_is_refused():
    _refused(
        _changed(
            lambda record: (
                dataclasses.replace(record, driving_side="left")
                if type(record) is DistrictRecord
                else record
            )
        ),
        "traffic v1 simulates right-hand traffic only",
    )


def test_lanes_whose_corridors_meet_are_refused(monkeypatch):
    # A 30 m ring corner makes the bus's rear axle track inside far enough to meet the other lane.
    monkeypatch.setattr(fixture_module, "RING_RADIUS_MM", 30_000)
    _refused(fixture_module.build_records.__wrapped__(), "come too close")


def test_a_junction_whose_approaches_miss_an_inbound_lane_is_refused():
    junction = _junction("N").identity
    _refused(
        _changed(
            lambda record: (
                None
                if type(record) is JunctionApproachRecord
                and record.junction_identity == junction
                and record.approach_ordinal == 0
                else record
            )
        ),
        f"junction {junction} approaches do not cover its inbound lanes once each",
    )


def test_a_u_turn_is_refused():
    forward, backward = _lane(0, 2), _lane(0, 1)
    junction = _junction("N").identity
    records = _changed(
        lambda record: (
            dataclasses.replace(record, turns=("left", "straight", "right", "u_turn"))
            if record is forward
            else record
        )
    )
    u_turn = LaneConnectionRecord(
        identity("lane_connection", junction, 99),
        junction,
        99,
        forward.identity,
        backward.identity,
        "u_turn",
        (forward.centreline_mm[-1], (0, 83_000, 0), backward.centreline_mm[0]),
        Extent(-1_875, 80_000, 0, 1_875, 83_000, 0),
    )
    _refused((*records, u_turn), "traffic v1 does not simulate u-turns")


def _straight_from(lane: LaneRecord, movement: str) -> LaneConnectionRecord:
    [connection] = [
        record
        for record in _of(LaneConnectionRecord)
        if record.from_lane_identity == lane.identity and record.movement == movement
    ]
    return connection


def _with_path(connection: LaneConnectionRecord, path) -> tuple[object, ...]:
    xs, ys = [point[0] for point in path], [point[1] for point in path]
    extent = Extent(min(xs), min(ys), 0, max(xs), max(ys), 0)
    return _changed(
        lambda record: (
            dataclasses.replace(record, path_mm=path, extent=extent)
            if record is connection
            else record
        )
    )


def test_a_turn_sharper_than_a_right_angle_at_one_vertex_is_refused():
    # The north spoke's southbound lane runs straight through the centre.
    straight = _straight_from(_lane(0, 1), "straight")
    (x0, y0, _), (x1, y1, _) = straight.path_mm
    kinked = ((x0, y0, 0), (x0, y0 + 8_000, 0), (x0 - 3_000, y0 + 4_000, 0), (x1, y1, 0))
    _refused(
        _with_path(straight, kinked),
        f"connection {straight.identity} turns by more than a right angle",
    )


def test_a_connection_whose_corner_no_class_can_drive_is_refused():
    right = _straight_from(_lane(0, 2), "right")
    start, end = right.path_mm[0], right.path_mm[-1]
    # A square corner a metre before the far lane: a tangent arc there is under 500 mm.
    squared = (start, (start[0], end[1] - 1_000, 0), (end[0], end[1] - 1_000, 0), end)
    _refused(
        _with_path(right, squared),
        f"connection {right.identity} carries no class: its tightest corner is",
    )


def test_a_crossing_on_a_curved_lane_piece_is_refused():
    segment = _segment(4)
    line = Polyline.of(tuple((x, y) for x, y, _ in segment.centreline_mm))
    middle = segment.length_mm // 2
    centre = line.point_at(middle)
    a, b = line.piece(line.piece_index(middle))
    direction = (b[0] - a[0], b[1] - a[1])
    length = isqrt(direction[0] ** 2 + direction[1] ** 2)
    across = (-direction[1] * 6_350 // length, direction[0] * 6_350 // length)
    ends = (
        (centre[0] - across[0], centre[1] - across[1], 0),
        (centre[0] + across[0], centre[1] + across[1], 0),
    )
    xs, ys = [end[0] for end in ends], [end[1] for end in ends]
    crossing = CrossingRecord(
        identity("crossing", segment.identity, 7),
        segment.identity,
        7,
        "zebra",
        middle,
        3_000,
        ends,
        6,
        (),
        Extent(min(xs), min(ys), 0, max(xs), max(ys), 0),
    )
    _refused(
        (*build_records(), crossing), f"crossing {crossing.identity} lies on a curved lane piece"
    )


def _signal() -> SignalRecord:
    [signal] = _of(SignalRecord)
    return signal


def _with_groups(groups) -> tuple[object, ...]:
    signal = _signal()
    return _changed(
        lambda record: dataclasses.replace(record, groups=groups) if record is signal else record
    )


def test_a_plan_releasing_two_conflicting_straight_movements_together_is_refused():
    groups = {group.group: group for group in _signal().groups}
    moved = _straight_from(_lane(1, 1), "straight").identity
    assert moved in groups["phase_b"].connection_identities
    changed = (
        SignalGroup(
            "phase_a", tuple(sorted((*groups["phase_a"].connection_identities, moved))), ()
        ),
        SignalGroup(
            "phase_b",
            tuple(item for item in groups["phase_b"].connection_identities if item != moved),
            (),
        ),
        groups["walk_a"],
        groups["walk_b"],
    )
    _refused(_with_groups(changed), "lets conflicting straight movements")


def test_a_straight_movement_through_a_crosswalk_that_is_walking_is_refused():
    groups = {group.group: group for group in _signal().groups}
    swapped = (
        groups["phase_a"],
        groups["phase_b"],
        SignalGroup("walk_a", (), groups["walk_b"].crossing_identities),
        SignalGroup("walk_b", (), groups["walk_a"].crossing_identities),
    )
    _refused(_with_groups(swapped), "while it walks")


def _move_far_crossing(offset: int) -> tuple[object, ...]:
    crossing = _crossing(0, 2)
    assert crossing.offset_mm == 83_500
    shift = offset - crossing.offset_mm
    return _changed(
        lambda record: (
            dataclasses.replace(
                record,
                offset_mm=offset,
                line_mm=tuple((x, y + shift, z) for x, y, z in record.line_mm),
                extent=dataclasses.replace(
                    record.extent,
                    min_y_mm=record.extent.min_y_mm + shift,
                    max_y_mm=record.extent.max_y_mm + shift,
                ),
            )
            if record is crossing
            else record
        )
    )


def test_a_crossing_band_that_reaches_a_stop_line_is_refused():
    _refused(
        _move_far_crossing(79_000),
        f"crossing {_crossing(0, 2).identity} reaches the stop line of lane",
    )


def test_a_stop_line_four_feet_before_the_crosswalk_compiles():
    """A stop line 4 ft (1219 mm) before the crosswalk's near edge, as MUTCD practice places it."""
    network = _compile(_move_far_crossing(80_000 + 1_219 + 1_500))
    band = network.band(_crossing(0, 2).identity)
    assert all(path.startswith("connector:") for path, _, _ in band.intervals)


def _bay(segment: int, side: str, ordinal: int) -> ParkingSpaceRecord:
    curb = identity("curb_edge", _segment(segment).identity, 1 if side == "right" else 0)
    return next(
        record
        for record in _of(ParkingSpaceRecord)
        if record.curb_identity == curb and record.space_ordinal == ordinal
    )


def _with_access(space: ParkingSpaceRecord, start: int, end: int) -> tuple[object, ...]:
    return _changed(
        lambda record: (
            dataclasses.replace(record, access_start_mm=start, access_end_mm=end)
            if record is space
            else record
        )
    )


def test_parking_reached_inside_a_junction_region_or_across_a_crossing_is_refused():
    bus = _bay(0, "right", 0)
    assert (bus.parking_kind, bus.access_start_mm, bus.access_end_mm) == (
        "bus_layover",
        22_000,
        36_000,
    )
    _refused(_with_access(bus, 20_000, 36_000), f"space {bus.identity} is reached inside")
    loading = _bay(0, "right", 3)
    assert (loading.parking_kind, loading.access_start_mm) == ("loading", 56_100)
    _refused(
        _with_access(loading, 53_000, 62_800),
        f"space {loading.identity} is reached across crossing {_crossing(0, 1).identity}",
    )


def test_too_little_pedestrian_time_for_a_long_signalised_crossing_is_refused():
    crossing = _crossing(0, 0)
    (x0, y0, z0), (x1, y1, z1) = crossing.line_mm
    longer = ((x0 - 9_000, y0, z0), (x1 + 9_000, y1, z1))
    _refused(
        _changed(
            lambda record: (
                dataclasses.replace(
                    record,
                    line_mm=longer,
                    extent=dataclasses.replace(
                        record.extent,
                        min_x_mm=record.extent.min_x_mm - 9_000,
                        max_x_mm=record.extent.max_x_mm + 9_000,
                    ),
                )
                if record is crossing
                else record
            )
        ),
        f"gives crossing {crossing.identity} too little pedestrian time",
    )


def test_a_signalised_mid_block_crossing_is_refused():
    crossing = _crossing(0, 1)
    _refused(
        _changed(
            lambda record: (
                dataclasses.replace(record, signal_identity=(_signal().identity,))
                if record is crossing
                else record
            )
        ),
        f"mid-block crossing {crossing.identity} is signalised; v1 has no mid-block signals",
    )


def test_a_signal_junction_needs_its_signal():
    signal = _signal().identity

    def unsignal(record):
        if type(record) is SignalRecord:
            return None
        if type(record) in (JunctionRecord, CrossingRecord) and record.signal_identity == (signal,):
            return dataclasses.replace(record, signal_identity=())
        return record

    _refused(
        _changed(unsignal),
        f"junction {_junction('C').identity}: a signal exists exactly when the rule is signal",
    )


def test_an_uncontrolled_junction_with_conflicting_approaches_is_refused():
    junction = _junction("N").identity

    def change(record):
        if type(record) is JunctionRecord and record.identity == junction:
            return dataclasses.replace(record, control="uncontrolled_continuation")
        if type(record) is JunctionApproachRecord and record.junction_identity == junction:
            return dataclasses.replace(record, control="priority", priority_rank=0)
        return record

    _refused(_changed(change), f"uncontrolled junction {junction} has conflicting movements")


def test_ranks_at_a_signalised_junction_are_read_by_no_rule():
    junction = _junction("C").identity
    network = _compile(
        _changed(
            lambda record: (
                dataclasses.replace(record, priority_rank=1)
                if type(record) is JunctionApproachRecord
                and record.junction_identity == junction
                and record.approach_ordinal == 0
                else record
            )
        )
    )
    assert network.junctions[junction].policy == "signalised"


# ---------------------------------------------------------------------------------------------
# Restrictions: classes the records allowed and the geometry cannot carry


def test_a_lane_narrower_than_a_body_drops_that_class_and_says_why():
    lane = _lane(4, 1)
    network = _compile(
        _changed(
            lambda record: dataclasses.replace(record, width_mm=2_500) if record is lane else record
        )
    )
    path_id = f"lane:{lane.identity}"
    assert network.restrictions == ((path_id, "city_bus", "body wider than the lane"),)
    assert network.paths[path_id].classes == ("bicycle", "passenger_car", "van")
    for connector in network.paths[path_id].successors + network.paths[path_id].predecessors:
        assert "city_bus" not in network.paths[connector].classes


def test_a_turn_tighter_than_a_class_minimum_drops_that_class_on_the_turn(tmp_path: Path):
    directory = tmp_path / "traffic"
    shutil.copytree(CATALOG_DIRECTORY, directory)
    path = directory / "vehicle-class.v1.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    [bus] = [entry for entry in document["entries"] if entry["key"] == "city_bus"]
    bus["minimum_turning_radius_mm"] = 14_000
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    network = _compile(build_records(), load_traffic_catalogs(directory))
    turns = [reason for _, key, reason in network.restrictions if key == "city_bus"]
    # Every right turn in the fixture is a 13.125 m arc and left turns are wider: four right
    # turns at the centre and two at each T junction.
    assert len(turns) == 4 + 4 * 2
    assert all(reason.startswith("turn radius ") for reason in turns)
    for path_id, _, _ in network.restrictions:
        spec = network.paths[path_id]
        assert spec.turn == "right" and "city_bus" not in spec.classes
