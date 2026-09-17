"""Traffic reads the city through one converter: city version 2 road records in, a road input out.

Two record sets go through it. The synthetic traffic network, built with the city's own record
classes, converts to the lanes, classes and access positions the tests expect. The city vocabulary
lane's fixture tile, read from its committed JSON, converts record by record; the compiler then
refuses it for what it could not drive safely, a square corner no vehicle's turning radius fits and
a crosswalk walked while the straight movement across it has green, and once those two are drawn as
a traffic generator must draw them, it compiles, a van drives through its signalised junction past
a pedestrian, and its cycle stand holds four bicycles while a car bay holds one car.

Each converter refusal is shown with its reason.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from functools import cache
from pathlib import Path

import pytest
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city.districts import DistrictRecord
from exulanica.grammar.grammars.city.document import read_tile_document
from exulanica.grammar.grammars.city.roads import (
    LaneConnectionRecord,
    LaneRecord,
    ParkingSpaceRecord,
    SignalGroup,
    SignalRecord,
)
from exulanica.grammar.grammars.city.streets import CrossingRecord, StreetSegmentRecord
from exulanica.traffic.catalogs import load_traffic_catalogs
from exulanica.traffic.checks import TransitionChecker
from exulanica.traffic.city_roads import READ_KINDS, road_input_from_city
from exulanica.traffic.errors import InvalidTrafficInputError, UnsupportedNetworkError
from exulanica.traffic.inputs import (
    LOOKAHEAD_S,
    CrossingEntry,
    CrossingFeed,
    TrafficInputs,
    TripRequest,
)
from exulanica.traffic.network import compile_network
from exulanica.traffic.simulation import advance_traffic, initial_traffic

from traffic_network_fixture import CITY, build_records, dedupe, identity, quarter_arc
from traffic_scenarios import seed_for, traffic_id_for

ROOT = Path(__file__).resolve().parents[1]
V2_FIXTURE = ROOT / "tests" / "fixtures" / "city-v2" / "tile-document.json"


def _convert(records, city=CITY):
    return road_input_from_city(records, load_traffic_catalogs(), city_identity=city)


def _refused(records, fragment: str, city=CITY) -> None:
    with pytest.raises(UnsupportedNetworkError) as caught:
        _convert(records, city)
    assert fragment in str(caught.value), str(caught.value)


def _changed(records, change) -> tuple[object, ...]:
    out = []
    for record in records:
        changed = change(record)
        if changed is not None:
            out.append(changed)
    assert out != list(records), "the change touched nothing"
    return tuple(out)


# ---------------------------------------------------------------------------------------------
# The synthetic network's records


def test_the_synthetic_records_convert_to_the_traffic_they_describe():
    road = _convert(build_records())
    assert road.city == CITY and road.driving_side == "right"
    assert (len(road.nodes), len(road.segments), len(road.junctions)) == (5, 8, 5)
    # Parking lanes carry no traffic, so of 24 lanes 16 are inputs, each carrying every class.
    assert len(road.lanes) == 16
    assert {lane.classes for lane in road.lanes} == {
        ("bicycle", "city_bus", "passenger_car", "van")
    }
    assert Counter(lane.direction for lane in road.lanes) == {"forward": 8, "backward": 8}
    assert (len(road.approaches), len(road.connections), len(road.crossings)) == (16, 36, 20)
    [signal] = road.signals
    assert (signal.plan, signal.offset_s) == ("fixed_two_phase_60s", 0)
    assert Counter(crossing.control for crossing in road.crossings) == {
        "signalised": 4,
        "marked_priority": 16,
    }
    kinds = Counter(
        (space.kind, space.placement, space.capacity, space.classes) for space in road.spaces
    )
    assert kinds == {
        ("general", "carriageway", 1, ("passenger_car", "van")): 16,
        ("bus_layover", "carriageway", 1, ("city_bus",)): 8,
        ("loading", "carriageway", 1, ("van",)): 8,
        ("accessible", "carriageway", 1, ("passenger_car", "van")): 8,
        ("cycle_stand", "footway", 4, ("bicycle",)): 8,
    }
    assert [item.identity for item in road.lanes] == sorted(item.identity for item in road.lanes)


def test_an_access_stretch_along_the_segment_becomes_positions_on_its_lane():
    road = _convert(build_records())
    segment = identity("street_segment", CITY, 0)
    lanes = {lane.identity: lane for lane in road.lanes}
    by_curb = {}
    for space in road.spaces:
        if space.segment == segment:
            by_curb.setdefault(lanes[space.access_lane].direction, []).append(space)
    # The forward lane starts 20 m out and the backward lane 80 m out, so the bus bay 22 to 36 m
    # along the spoke is 2 to 16 m along the one and 44 to 58 m along the other.
    forward = {
        (space.kind, space.access_start_mm, space.access_end_mm) for space in by_curb["forward"]
    }
    backward = {
        (space.kind, space.access_start_mm, space.access_end_mm) for space in by_curb["backward"]
    }
    assert ("bus_layover", 2_000, 16_000) in forward
    assert ("bus_layover", 44_000, 58_000) in backward
    assert ("cycle_stand", 49_500, 52_500) in forward
    assert ("cycle_stand", 7_500, 10_500) in backward


def test_the_conversion_does_not_depend_on_record_order_or_on_records_traffic_ignores():
    records = build_records()
    assert _convert(tuple(reversed(records))) == _convert(records)
    # The converter ignores every city kind it does not read.
    assert all(isinstance(record, READ_KINDS) for record in records)


# ---------------------------------------------------------------------------------------------
# The city vocabulary lane's fixture tile


@cache
def _v2() -> tuple[tuple[object, ...], str]:
    document = read_tile_document(V2_FIXTURE.read_bytes())
    [grammar] = document.grammars
    return grammar.records(), grammar.subject_identity


def _v2_kind(kind: type) -> list:
    return [record for record in _v2()[0] if type(record) is kind]


def test_the_city_fixture_converts_record_by_record():
    records, city = _v2()
    road = _convert(records, city)
    assert len(records) == 180 and road.city == city
    # Eight lanes, of which two are parking lanes.
    assert len(_v2_kind(LaneRecord)) == 8 and len(road.lanes) == 6
    [junction] = road.junctions
    assert junction.policy == "signalised"
    [signal] = road.signals
    assert (signal.plan, signal.offset_s) == ("fixed_two_phase_60s", 0)
    assert [
        (group.group, len(group.connections), len(group.crossings)) for group in signal.groups
    ] == [
        ("phase_a", 4, 0),
        ("phase_b", 2, 0),
        ("walk_a", 0, 1),
        ("walk_b", 0, 1),
    ]
    assert sorted(
        (crossing.offset_mm, crossing.centre, crossing.control) for crossing in road.crossings
    ) == [
        (13_000, (60_000, 53_000), "signalised"),
        (28_000, (48_000, 40_000), "signalised"),
    ]
    assert sorted(
        (
            space.kind,
            space.placement,
            space.capacity,
            space.classes,
            space.access_start_mm,
            space.access_end_mm,
        )
        for space in road.spaces
    ) == [
        ("cycle_stand", "footway", 4, ("bicycle",), 18_000, 21_000),
        ("general", "carriageway", 1, ("passenger_car", "van"), 20_750, 26_750),
        ("loading", "carriageway", 1, ("van",), 12_000, 20_000),
    ]


def test_the_city_fixture_is_refused_for_a_corner_no_vehicle_can_turn():
    records, city = _v2()
    road = _convert(records, city)
    with pytest.raises(
        UnsupportedNetworkError, match="carries no class: its tightest corner is 875 mm"
    ):
        compile_network(road, load_traffic_catalogs())


def _unit(a, b) -> tuple[int, int]:
    return ((b[0] > a[0]) - (b[0] < a[0]), (b[1] > a[1]) - (b[1] < a[1]))


def _arced(record):
    """A square-cornered connection redrawn with the largest arc its corner fits."""
    if type(record) is not LaneConnectionRecord or len(record.path_mm) != 3:
        return record
    p, k, q = ((x, y) for x, y, _ in record.path_mm)
    d_in, d_out = _unit(p, k), _unit(k, q)
    radius = min(abs(k[0] - p[0]) + abs(k[1] - p[1]), abs(q[0] - k[0]) + abs(q[1] - k[1]))
    centre = (
        k[0] - radius * d_in[0] + radius * d_out[0],
        k[1] - radius * d_in[1] + radius * d_out[1],
    )
    arc = quarter_arc(centre, (-d_out[0], -d_out[1]), d_in, radius)
    height = record.path_mm[0][2]
    path = tuple((x, y, height) for x, y in dedupe([p, *arc, q]))
    xs, ys = [point[0] for point in path], [point[1] for point in path]
    heights = [point[2] for point in record.path_mm]
    return dataclasses.replace(
        record,
        path_mm=path,
        extent=Extent(min(xs), min(ys), min(heights), max(xs), max(ys), max(heights)),
    )


def _walks_swapped(record):
    """Each walk group moved to the crosswalk its phase's straight movement does not cross."""
    if type(record) is not SignalRecord:
        return record
    walks = {group.group: group.crossing_identities for group in record.groups}
    return dataclasses.replace(
        record,
        groups=tuple(
            SignalGroup(group.group, (), walks["walk_b" if group.group == "walk_a" else "walk_a"])
            if group.group.startswith("walk")
            else group
            for group in record.groups
        ),
    )


def test_with_arcs_the_city_fixture_is_refused_for_a_walk_across_a_green_straight():
    records, city = _v2()
    road = _convert(_changed(records, _arced), city)
    with pytest.raises(UnsupportedNetworkError, match=r"through crossing .* while it walks"):
        compile_network(road, load_traffic_catalogs())


@cache
def _drivable():
    records, city = _v2()
    catalogs = load_traffic_catalogs()
    road = _convert(_changed(records, lambda record: _walks_swapped(_arced(record))), city)
    return compile_network(road, catalogs), catalogs


def test_drawn_as_traffic_needs_the_city_fixture_compiles_with_network_edges():
    network, _ = _drivable()
    assert len(network.paths) == 12 and len(network.zones) == 11
    lanes = [path for path in network.paths.values() if path.kind == "lane"]
    # Every lane has one end at a node with no junction: the edge of the tile.
    assert all((path.start_junction is None) != (path.end_junction is None) for path in lanes)
    assert all(band.junction is not None for band in network.bands)
    assert len([gate for items in network.gates.values() for gate in items]) == 3
    # Tight corners carry what fits: the one left turn with a 7 m arc carries cars and vans.
    carried = Counter(path.classes for path in network.paths.values() if path.is_turn)
    assert carried == {("bicycle",): 3, ("bicycle", "passenger_car", "van"): 1}


def _space_of_kind(network, kind: str) -> str:
    [space] = [identity for identity, space in network.spaces.items() if space.kind == kind]
    return space


def test_a_van_crosses_the_city_fixture_junction_past_a_pedestrian_and_parks():
    network, catalogs = _drivable()
    seed, traffic_id = seed_for("v2-van"), traffic_id_for("v2-van")
    state = initial_traffic(traffic_id, seed, network, catalogs, {"van": 1})
    [van] = state["vehicles"]
    loading, general = _space_of_kind(network, "loading"), _space_of_kind(network, "general")
    # From the loading bay the only way on is straight through the junction to the general bay.
    assert van["space"] == loading
    [west] = [band for band in network.bands if band.society_crossing_id.endswith(":28000")]
    total = 600
    walker = CrossingEntry(west.society_crossing_id, 20, 60, "a slow walker")
    inputs = TrafficInputs(
        trips=(TripRequest(1, "van-trip", van["id"], 0, "space", general, -1, "test request"),),
        feeds=(CrossingFeed(1, total + LOOKAHEAD_S, (walker,)),),
    )
    checker = TransitionChecker(network, catalogs, inputs)
    events = []
    for _ in range(total):
        step = advance_traffic(state, seed, network, catalogs, inputs)
        assert checker.check(state, step.state) == []
        assert step.receipt["breaches"] == []
        events += [event["document"] for event in step.events]
        state = step.state
    kinds = [event["kind"] for event in events]
    assert "junction_entered" in kinds and "trip_arrived" in kinds
    [entered] = [event for event in events if event["kind"] == "junction_entered"]
    # The west crosswalk is on the van's way out of the junction: it waits out the walker.
    assert entered["second"] > 20 + 60 or entered["second"] < 20
    [trip] = state["trips"]
    assert (trip["status"], trip["target_space"]) == ("arrived", general)


def test_the_city_fixture_stand_holds_four_bicycles_and_its_bay_one_car():
    network, catalogs = _drivable()
    seed, traffic_id = seed_for("v2-capacity"), traffic_id_for("v2-capacity")
    state = initial_traffic(traffic_id, seed, network, catalogs, {"bicycle": 4, "passenger_car": 1})
    stand = _space_of_kind(network, "cycle_stand")
    bicycles = [vehicle for vehicle in state["vehicles"] if vehicle["vehicle_class"] == "bicycle"]
    assert {vehicle["space"] for vehicle in bicycles} == {stand}
    assert sorted(vehicle["slot"] for vehicle in bicycles) == [0, 1, 2, 3]
    with pytest.raises(InvalidTrafficInputError, match="no free space fits another bicycle"):
        initial_traffic(traffic_id, seed, network, catalogs, {"bicycle": 5})
    with pytest.raises(InvalidTrafficInputError, match="no free space fits another passenger_car"):
        initial_traffic(traffic_id, seed, network, catalogs, {"passenger_car": 2})


# ---------------------------------------------------------------------------------------------
# What the converter refuses


def _synthetic(kind: type, **match) -> object:
    return next(
        record
        for record in build_records()
        if type(record) is kind
        and all(getattr(record, key) == value for key, value in match.items())
    )


def test_anything_but_a_city_record_is_refused():
    _refused((*build_records(), object()), "traffic reads city records, not object")


def test_a_record_that_breaks_its_own_shape_is_refused():
    lane = _synthetic(LaneRecord, lane_index=1)
    _refused(
        _changed(
            build_records(),
            lambda record: dataclasses.replace(record, width_mm=900) if record is lane else record,
        ),
        f"city.lane {lane.identity}",
    )


def test_an_identity_its_rule_does_not_derive_is_refused():
    segment = _synthetic(StreetSegmentRecord, segment_ordinal=3)
    _refused(
        _changed(
            build_records(),
            lambda record: (
                dataclasses.replace(record, segment_ordinal=9) if record is segment else record
            ),
        ),
        "is not the identity its rule derives",
    )


def test_a_reference_to_a_record_that_is_not_there_is_refused():
    crossing = _synthetic(CrossingRecord, crossing_ordinal=1)
    _refused(
        _changed(
            build_records(),
            lambda record: (
                None
                if type(record) is StreetSegmentRecord
                and record.identity == crossing.segment_identity
                else record
            ),
        ),
        f"names {crossing.segment_identity}, which is no city.street_segment record here",
    )


def test_a_lane_whose_use_and_direction_disagree_is_refused():
    parking = _synthetic(LaneRecord, lane_index=0, lane_use="parking")
    _refused(
        _changed(
            build_records(),
            lambda record: (
                dataclasses.replace(record, direction="forward", turns=("straight",))
                if record is parking
                else record
            ),
        ),
        "is a parking lane, which carries no traffic, yet runs forward",
    )
    general = _synthetic(LaneRecord, lane_index=1, lane_use="general")
    _refused(
        _changed(
            build_records(),
            lambda record: (
                dataclasses.replace(
                    record,
                    direction="none",
                    turns=(),
                    start_offset_mm=record.end_offset_mm,
                    end_offset_mm=record.start_offset_mm,
                    centreline_mm=tuple(reversed(record.centreline_mm)),
                )
                if record is general
                else record
            ),
        ),
        "is a general lane, which carries traffic, and has no direction",
    )


def _signal() -> SignalRecord:
    return _synthetic(SignalRecord)


def test_a_signal_traffic_cannot_resolve_or_time_is_refused():
    signal = _signal()
    _refused(
        _changed(
            build_records(),
            lambda record: (
                dataclasses.replace(record, plan_catalog_sha256="0" * 64)
                if record is signal
                else record
            ),
        ),
        f"signal {signal.identity} names signal-plan catalog bytes {'0' * 64}",
    )
    _refused(
        _changed(
            build_records(),
            lambda record: (
                dataclasses.replace(record, offset_ms=1_500) if record is signal else record
            ),
        ),
        f"signal {signal.identity} offset 1500 ms is not whole seconds",
    )
    _refused(
        _changed(
            build_records(),
            lambda record: (
                dataclasses.replace(record, plan="fixed_three_phase")
                if record is signal
                else record
            ),
        ),
        "no signal plan 'fixed_three_phase'",
    )


def test_a_signal_on_a_mid_block_crossing_is_refused():
    signal = _signal()
    crossing = _synthetic(CrossingRecord, crossing_ordinal=1)
    mid_block = SignalRecord(
        identity("signal", crossing.identity, 0),
        crossing.identity,
        signal.plan,
        signal.plan_catalog_sha256,
        0,
        (SignalGroup("walk_a", (), (crossing.identity,)),),
        signal.heads[:1],
    )
    _refused(
        (*build_records(), mid_block),
        "controls a mid-block crossing; traffic v1 has no mid-block signals",
    )


def test_parking_reached_from_a_lane_that_carries_no_traffic_is_refused():
    space = _synthetic(ParkingSpaceRecord, parking_kind="general")
    [parking_lane] = space.lane_identity
    _refused(
        _changed(
            build_records(),
            lambda record: (
                dataclasses.replace(record, access_lane_identity=parking_lane)
                if record is space
                else record
            ),
        ),
        f"is reached from lane {parking_lane}, which carries no traffic",
    )


def test_districts_that_drive_on_different_sides_are_refused():
    district = _synthetic(DistrictRecord)
    other = dataclasses.replace(
        district, identity=identity("district", CITY, 1), district_ordinal=1, driving_side="left"
    )
    segment = _synthetic(StreetSegmentRecord, segment_ordinal=7)
    records = _changed(
        build_records(),
        lambda record: (
            dataclasses.replace(record, district_identity=other.identity)
            if record is segment
            else record
        ),
    )
    _refused((*records, other), "the segments' districts drive on different sides")


def test_a_crossing_beyond_its_segment_is_refused():
    crossing = _synthetic(CrossingRecord, crossing_ordinal=2)
    _refused(
        _changed(
            build_records(),
            lambda record: (
                dataclasses.replace(record, offset_mm=250_000) if record is crossing else record
            ),
        ),
        f"crossing {crossing.identity} offset 250000 is beyond its segment's length",
    )
