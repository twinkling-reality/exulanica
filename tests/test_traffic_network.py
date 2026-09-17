"""The road network compiler: road records in, a checked network or a stated refusal out.

The fixture in ``traffic_network_fixture`` is built only from the road record shapes. This file
pins what it compiles to, that every record identity is the uuid5 of its stable tuple, that the
compiled conflict zones really contain every place two corridors meet on that geometry, and
that each thing v1 cannot simulate correctly is refused with its reason rather than approximated.
"""

from __future__ import annotations

import dataclasses
import json
import random
import shutil
import uuid
from functools import cache
from itertools import pairwise
from math import isqrt
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.traffic import provisional_records as rec
from exulanica.traffic.catalogs import CATALOG_DIRECTORY, load_traffic_catalogs
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.traffic.geometry import Polyline, convex_overlap, rectangle
from exulanica.traffic.network import NETWORK_PROFILE, compile_network

import traffic_network_fixture as fixture_module
from traffic_network_fixture import SCOPE, build_records


@cache
def _base() -> tuple[object, ...]:
    return build_records()


@cache
def _network():
    return compile_network(_base(), load_traffic_catalogs(), scope=SCOPE)


def _identity(kind: str, *parts: int | str) -> str:
    return rec.street_record_identity(SCOPE, kind, *parts)


def _of(kind: type) -> list:
    return [record for record in _base() if isinstance(record, kind)]


def _changed(change) -> tuple[object, ...]:
    """The fixture records with ``change`` applied to each; ``None`` drops a record."""
    out = []
    for record in _base():
        changed = change(record)
        if changed is not None:
            out.append(changed)
    assert out != list(_base()), "the change touched nothing"
    return tuple(out)


def _refused(records, fragment: str, catalogs=None) -> None:
    with pytest.raises(UnsupportedNetworkError) as caught:
        compile_network(records, catalogs or load_traffic_catalogs(), scope=SCOPE)
    assert fragment in str(caught.value), str(caught.value)


# ---------------------------------------------------------------------------------------------
# What the fixture compiles to


def test_the_fixture_compiles_to_the_expected_network():
    network = _network()
    lanes = [path for path in network.paths.values() if path.kind == "lane"]
    connectors = [path for path in network.paths.values() if path.kind == "connector"]
    assert (len(network.paths), len(lanes), len(connectors)) == (52, 16, 36)
    assert len(network.zones) == 88
    assert len(network.spaces) == 56
    assert {ordinal: junction.policy for ordinal, junction in network.junctions.items()} == {
        0: "signalised",
        1: "priority_two_way_stop",
        2: "all_way_stop",
        3: "priority_two_way_stop",
        4: "all_way_stop",
    }
    assert network.junctions[0].signal is not None
    assert network.junctions[0].signal.plan == "fixed_two_phase_60s"
    assert all(network.junctions[ordinal].signal is None for ordinal in (1, 2, 3, 4))
    assert network.restrictions == ()
    assert network.driving_side == "right"
    # Twelve movements at the four-way centre, six at each T junction.
    assert [len(network.junctions[ordinal].connectors) for ordinal in range(5)] == [12, 6, 6, 6, 6]


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
    assert all(band.junction == 0 and band.signal is not None for band in signalised)
    for band in network.bands:
        assert network.band_by_society_id(band.society_crossing_id) is band
        segment, offset = band.society_crossing_id.split(":")[1:]
        assert int(segment) == band.segment_ordinal and int(offset) > 0
        assert band.intervals, band.society_crossing_id
    with pytest.raises(UnsupportedNetworkError, match="no crossing"):
        network.band_by_society_id("crossing:9:1")


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
        band = network.bands[gate.target]
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
    # Lanes start 20 m out, beyond every connector corridor, so no junction region reaches onto
    # a lane in this fixture and no crossing band lies on a lane end.
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
            if path.kind == "lane" and path.start_junction == junction.ordinal
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
                    assert (connector, other) in zones, (junction.ordinal, first, second, spans)
                    low, high = zones[(connector, other)][side]
                    for start, end in spans:
                        assert low <= end and start <= high, (first, second, start, end, low, high)
    # Each movement against every other movement of its junction and every outbound lane but
    # its own: twelve movements and three such lanes at the centre, six and two at a T.
    assert pairs == 12 * (11 + 3) + 4 * 6 * (5 + 2)
    assert meetings > 1_000


# ---------------------------------------------------------------------------------------------
# Identity and digest


def test_a_record_identity_is_the_uuid5_of_scope_kind_and_its_stable_tuple():
    expected = uuid.uuid5(
        rec.STREET_IDENTITY_NAMESPACE,
        canonical_json([SCOPE, "carriageway_lane", 3, "with_segment", 0]).decode(),
    )
    assert _identity("carriageway_lane", 3, "with_segment", 0) == str(expected)
    assert _identity("carriageway_lane", 3, "with_segment", 0) != _identity(
        "carriageway_lane", 3, "against_segment", 0
    )
    lanes = {lane.lane_ordinal: lane for lane in _of(rec.CarriagewayLaneRecord)}
    for lane in lanes.values():
        assert lane.identity == _identity(
            "carriageway_lane", lane.segment_ordinal, lane.direction, lane.lane_index
        )
    for connector in _of(rec.LaneConnectorRecord):
        source, target = lanes[connector.from_lane_ordinal], lanes[connector.to_lane_ordinal]
        assert connector.identity == _identity("lane_connector", source.identity, target.identity)
    for space in _of(rec.ParkingSpaceRecord):
        assert space.identity == _identity(
            "parking_space", space.segment_ordinal, space.side, space.space_index
        )
    with pytest.raises(UnsupportedNetworkError, match="an int or a str"):
        _identity("junction", 1.5)  # type: ignore[arg-type]


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
    for records in (tuple(reversed(_base())), _shuffled(_base())):
        reordered = compile_network(records, load_traffic_catalogs(), scope=SCOPE)
        assert reordered.document == network.document
        assert reordered.digest == network.digest
    faster = _changed(
        lambda record: (
            dataclasses.replace(record, speed_limit_mm_per_h=40_000_000)
            if isinstance(record, rec.CarriagewayLaneRecord) and record.lane_ordinal == 0
            else record
        )
    )
    assert compile_network(faster, load_traffic_catalogs(), scope=SCOPE).digest != network.digest


def test_a_record_whose_identity_does_not_match_its_tuple_is_refused():
    _refused(
        _changed(
            lambda record: (
                dataclasses.replace(record, identity=_identity("junction", 3))
                if isinstance(record, rec.JunctionRecord) and record.junction_ordinal == 2
                else record
            )
        ),
        "junction (2,) has identity",
    )


def test_a_record_of_a_kind_traffic_does_not_read_is_refused():
    _refused((*_base(), object()), "traffic reads no record type object")


# ---------------------------------------------------------------------------------------------
# Refusals


def test_left_hand_traffic_is_refused():
    _refused(
        _changed(
            lambda record: (
                rec.RoadRulesRecord("left") if isinstance(record, rec.RoadRulesRecord) else record
            )
        ),
        "traffic v1 simulates right-hand traffic only",
    )
    _refused((*_base(), rec.RoadRulesRecord("right")), "exactly one road rules record, found 2")


def test_lanes_whose_corridors_meet_are_refused(monkeypatch):
    # A 40 m ring corner makes the bus's rear axle track inside far enough to meet the other lane.
    monkeypatch.setattr(fixture_module, "RING_RADIUS_MM", 40_000)
    _refused(fixture_module.build_records(), "come too close")


def test_a_junction_whose_approaches_miss_an_inbound_lane_is_refused():
    _refused(
        _changed(
            lambda record: (
                None
                if isinstance(record, rec.JunctionApproachRecord) and record.approach_ordinal == 10
                else record
            )
        ),
        "junction 1 approaches do not cover its inbound lanes once each",
    )


def test_a_u_turn_is_refused():
    lanes = _of(rec.CarriagewayLaneRecord)
    on_spoke = {lane.direction: lane for lane in lanes if lane.segment_ordinal == 0}
    forward, backward = on_spoke["with_segment"], on_spoke["against_segment"]
    records = _changed(
        lambda record: (
            dataclasses.replace(record, permitted_turns=("left", "straight", "right", "u_turn"))
            if record is forward
            else record
        )
    )
    u_turn = rec.LaneConnectorRecord(
        _identity("lane_connector", forward.identity, backward.identity),
        999,
        1,
        forward.lane_ordinal,
        backward.lane_ordinal,
        "u_turn",
        (forward.centreline_mm[-1], (0, 83_000), backward.centreline_mm[0]),
    )
    _refused((*records, u_turn), "traffic v1 does not simulate u-turns")


def test_a_crossing_on_a_curved_lane_piece_is_refused():
    [segment] = [record for record in _of(rec.StreetSegmentRecord) if record.segment_ordinal == 4]
    line = Polyline.of(segment.centreline_mm)
    middle = line.length // 2
    centre = line.point_at(middle)
    a, b = line.piece(line.piece_index(middle))
    direction = (b[0] - a[0], b[1] - a[1])
    length = isqrt(direction[0] ** 2 + direction[1] ** 2)
    across = (-direction[1] * 6_350 // length, direction[0] * 6_350 // length)
    offsets = (segment.crossing_offsets_mm[0], middle, segment.crossing_offsets_mm[1])

    def change(record):
        if record is segment:
            return dataclasses.replace(record, crossing_offsets_mm=offsets)
        if isinstance(record, rec.CrossingRecord) and (
            record.segment_ordinal,
            record.offset_index,
        ) == (4, 1):
            # The crossing at the far end moves up one offset to make room.
            return dataclasses.replace(record, offset_index=2, identity=_identity("crossing", 4, 2))
        return record

    on_the_arc = rec.CrossingRecord(
        _identity("crossing", 4, 1),
        100,
        4,
        1,
        "marked_priority",
        (
            (centre[0] - across[0], centre[1] - across[1]),
            (centre[0] + across[0], centre[1] + across[1]),
        ),
        3_000,
    )
    _refused((*_changed(change), on_the_arc), "crossing 100 lies on a curved lane piece")


def _signal_groups() -> dict[str, rec.SignalGroupRecord]:
    return {record.group: record for record in _of(rec.SignalGroupRecord)}


def test_a_plan_releasing_two_conflicting_straight_movements_together_is_refused():
    lanes = {lane.lane_ordinal: lane for lane in _of(rec.CarriagewayLaneRecord)}

    def east_west(connector) -> bool:
        a, b = lanes[connector.from_lane_ordinal].centreline_mm[-2:]
        return a[1] == b[1]

    moved = next(
        connector
        for connector in _of(rec.LaneConnectorRecord)
        if connector.junction_ordinal == 0 and connector.turn == "straight" and east_west(connector)
    )
    assert moved.connector_ordinal in _signal_groups()["phase_b"].connector_ordinals

    def change(record):
        if isinstance(record, rec.SignalGroupRecord) and record.group == "phase_a":
            ordinals = tuple(sorted((*record.connector_ordinals, moved.connector_ordinal)))
            return dataclasses.replace(record, connector_ordinals=ordinals)
        if isinstance(record, rec.SignalGroupRecord) and record.group == "phase_b":
            ordinals = tuple(o for o in record.connector_ordinals if o != moved.connector_ordinal)
            return dataclasses.replace(record, connector_ordinals=ordinals)
        return record

    _refused(_changed(change), "lets conflicting straight movements")


def test_a_straight_movement_through_a_crosswalk_that_is_walking_is_refused():
    groups = _signal_groups()

    def change(record):
        if isinstance(record, rec.SignalGroupRecord) and record.group in ("walk_a", "walk_b"):
            other = groups["walk_b" if record.group == "walk_a" else "walk_a"]
            return dataclasses.replace(record, crossing_ordinals=other.crossing_ordinals)
        return record

    _refused(_changed(change), "through crossing 0 while it walks")


def test_a_crossing_band_that_reaches_a_stop_line_is_refused():
    [segment] = [record for record in _of(rec.StreetSegmentRecord) if record.segment_ordinal == 0]
    [crossing] = [
        record
        for record in _of(rec.CrossingRecord)
        if (record.segment_ordinal, record.offset_index) == (0, 2)
    ]
    assert segment.crossing_offsets_mm == (16_500, 52_750, 83_500)

    def change(record):
        if record is segment:
            return dataclasses.replace(record, crossing_offsets_mm=(16_500, 52_750, 79_000))
        if record is crossing:
            return dataclasses.replace(
                record, line_mm=tuple((x, y - 4_500) for x, y in record.line_mm)
            )
        return record

    _refused(_changed(change), "crossing 2 reaches the stop line of lane 0")


def test_parking_reached_inside_a_junction_region_or_across_a_crossing_is_refused():
    spaces = {
        (space.segment_ordinal, space.side, space.space_index): space
        for space in _of(rec.ParkingSpaceRecord)
    }
    bus = spaces[(0, "right", 0)]
    assert (bus.access_start_mm, bus.access_end_mm) == (2_000, 16_000)
    _refused(
        _changed(
            lambda record: (
                dataclasses.replace(record, access_start_mm=0) if record is bus else record
            )
        ),
        "space 0 is reached inside a junction region",
    )
    car = spaces[(0, "right", 3)]
    assert (car.access_start_mm, car.access_end_mm) == (36_100, 42_800)
    _refused(
        _changed(
            lambda record: (
                dataclasses.replace(record, access_start_mm=33_000) if record is car else record
            )
        ),
        "space 3 is reached across crossing 1",
    )


def test_too_little_pedestrian_time_for_a_long_signalised_crossing_is_refused():
    [crossing] = [
        record
        for record in _of(rec.CrossingRecord)
        if (record.segment_ordinal, record.offset_index) == (0, 0)
    ]
    (x0, y0), (x1, y1) = crossing.line_mm
    _refused(
        _changed(
            lambda record: (
                dataclasses.replace(record, line_mm=((x0 - 9_000, y0), (x1 + 9_000, y1)))
                if record is crossing
                else record
            )
        ),
        "gives crossing 0 too little pedestrian time",
    )


def test_a_signalised_mid_block_crossing_is_refused():
    _refused(
        _changed(
            lambda record: (
                dataclasses.replace(record, control="signalised")
                if isinstance(record, rec.CrossingRecord)
                and (record.segment_ordinal, record.offset_index) == (0, 1)
                else record
            )
        ),
        "mid-block crossing 1 is signalised; v1 has no mid-block signals",
    )


def test_a_signal_junction_needs_its_controller():
    _refused(
        _changed(
            lambda record: (
                None
                if isinstance(record, rec.SignalControllerRecord | rec.SignalGroupRecord)
                else record
            )
        ),
        "junction 0: a signal controller exists exactly when the rule is signal",
    )


def test_an_uncontrolled_junction_with_conflicting_approaches_is_refused():
    def change(record):
        if isinstance(record, rec.JunctionRecord) and record.junction_ordinal == 1:
            return dataclasses.replace(record, policy="uncontrolled_continuation")
        if isinstance(record, rec.JunctionApproachRecord) and record.junction_ordinal == 1:
            return dataclasses.replace(record, control="priority", priority_rank=0)
        return record

    _refused(_changed(change), "uncontrolled junction 1 has conflicting movements")


# ---------------------------------------------------------------------------------------------
# Restrictions: classes the records allowed and the geometry cannot carry


def test_a_lane_narrower_than_a_body_drops_that_class_and_says_why():
    [lane] = [
        record
        for record in _of(rec.CarriagewayLaneRecord)
        if record.segment_ordinal == 4 and record.direction == "with_segment"
    ]
    network = compile_network(
        _changed(
            lambda record: dataclasses.replace(record, width_mm=2_500) if record is lane else record
        ),
        load_traffic_catalogs(),
        scope=SCOPE,
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
    catalogs = load_traffic_catalogs(directory)
    network = compile_network(_base(), catalogs, scope=SCOPE)
    turns = [reason for _, key, reason in network.restrictions if key == "city_bus"]
    # Every right turn in the fixture is a 13.125 m arc and left turns are wider: four right
    # turns at the centre and two at each T junction.
    assert len(turns) == 4 + 4 * 2
    assert all(reason.startswith("turn radius ") for reason in turns)
    for path_id, _, _ in network.restrictions:
        spec = network.paths[path_id]
        assert spec.turn == "right" and "city_bus" not in spec.classes
