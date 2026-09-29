"""The road records traffic derives from a city's streets, checked from the records and the network.

Every derived connection follows a permitted turn from a stop line to the lane it leaves by; every
bay stands in its parking lane, clear of every junction region, conflict zone, crossing and stop
line the network compiles, and every space is one a vehicle can drive to and leave again. Each
fact is measured here from the records or the compiled network, by code of its own, never by
asking the derivation, except the reach rule, stated with numbers on a lane of its own: on the
corridor every junction region ends at a crosswalk, whose clearance already covers the region.
"""

from __future__ import annotations

import dataclasses
from collections import Counter, deque
from types import SimpleNamespace

import pytest
from exulanica.grammar.grammars.city.catalogs import entry_fields, load_city_catalogs
from exulanica.grammar.grammars.city.generation.corridor import CORRIDOR_CITY_IDENTITY
from exulanica.grammar.grammars.city.roads import (
    JunctionRecord,
    LaneConnectionRecord,
    LaneRecord,
    ParkingSpaceRecord,
)
from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord
from exulanica.grammar.grammars.city.streets import StreetSegmentRecord
from exulanica.traffic import city_derivation
from exulanica.traffic.catalogs import load_traffic_catalogs
from exulanica.traffic.city_derivation import derive_road_records
from exulanica.traffic.city_roads import road_input_from_city
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.traffic.network import compile_network

import traffic_corridor_support as corridor


@pytest.fixture(scope="module")
def network():
    catalogs = load_traffic_catalogs()
    return compile_network(
        road_input_from_city(
            corridor.derived().records, catalogs, city_identity=CORRIDOR_CITY_IDENTITY
        ),
        catalogs,
    )


def _of(records, kind):
    return [record for record in records if type(record) is kind]


def test_every_permitted_turn_is_one_connection_from_its_stop_line_to_the_lane_it_leaves_by():
    records = corridor.derived().records
    lanes = {lane.identity: lane for lane in _of(records, LaneRecord)}
    segments = {segment.identity: segment for segment in _of(records, StreetSegmentRecord)}
    junction_nodes = {junction.node_identity for junction in _of(records, JunctionRecord)}
    connections = _of(records, LaneConnectionRecord)
    assert connections == list(corridor.derived().connections)
    made = Counter(
        (connection.from_lane_identity, connection.movement) for connection in connections
    )
    wanted = Counter()
    for lane in lanes.values():
        if lane.direction == "none":
            continue
        segment = segments[lane.segment_identity]
        flows_to = (
            segment.end_node_identity
            if lane.direction == "forward"
            else segment.start_node_identity
        )
        if flows_to in junction_nodes:
            wanted.update((lane.identity, movement) for movement in lane.turns)
    assert made == wanted and len(connections) == 96
    for connection in connections:
        source, target = lanes[connection.from_lane_identity], lanes[connection.to_lane_identity]
        assert connection.path_mm[0] == source.centreline_mm[-1]
        assert connection.path_mm[-1] == target.centreline_mm[0]
        assert source.segment_identity != target.segment_identity


def test_a_junction_the_city_states_connections_for_gets_none_derived():
    """The city's statement stands: its connections are kept and none is added beside them."""
    records = corridor.records()
    junction = corridor.derived().connections[0].junction_identity
    stated = [c for c in corridor.derived().connections if c.junction_identity == junction]
    derived = derive_road_records(
        (*records, *stated),
        load_traffic_catalogs(),
        load_city_catalogs(grammar_version=corridor.VERSION),
        city_identity=CORRIDOR_CITY_IDENTITY,
    )
    assert all(item.junction_identity != junction for item in derived.connections)
    assert len(derived.connections) == len(corridor.derived().connections) - len(stated)
    kept = [r for r in derived.records if type(r) is LaneConnectionRecord]
    assert len(kept) == len(corridor.derived().connections)


def test_every_bay_stands_in_its_parking_lane_clear_of_regions_zones_crossings_and_stop_lines(
    network,
):
    catalogs = load_traffic_catalogs()
    rule = catalogs.derivation("city_streets")
    kinds = next(c for c in load_city_catalogs(grammar_version=4) if c.catalog_id == "parking-kind")
    length = entry_fields(kinds, rule.bay_parking_kind)["length_maximum_mm"]
    records = corridor.derived().records
    lanes = {lane.identity: lane for lane in _of(records, LaneRecord)}
    bays = [s for s in _of(records, ParkingSpaceRecord) if s.placement == "carriageway"]
    assert bays and all(space.parking_kind == rule.bay_parking_kind for space in bays)
    for space in bays:
        [parking] = space.lane_identity
        lane = lanes[parking]
        assert lane.lane_use == rule.bay_lane_use
        assert space.access_end_mm - space.access_start_mm == length
        assert (
            lane.start_offset_mm
            <= space.access_start_mm
            < space.access_end_mm
            <= lane.end_offset_mm
        )
        sides = sorted(
            abs(a[0] - b[0]) + abs(a[1] - b[1])
            for a, b in zip(
                space.footprint_mm, space.footprint_mm[1:] + space.footprint_mm[:1], strict=True
            )
        )
        assert sides == [lane.width_mm, lane.width_mm, length, length]
        spec = network.spaces[space.identity]
        path = network.paths[spec.access_path]
        low, high = spec.access_start, spec.access_end
        assert low > network.exit_extent[path.path_id]
        for _zone, (start, end) in network.zones_by_path.get(path.path_id, ()):
            assert high < start or end < low
        for _band, (start, end) in network.bands_by_path.get(path.path_id, ()):
            assert (
                high < start - rule.bay_crossing_clearance_mm
                or end + rule.bay_crossing_clearance_mm < low
            )
        if path.end_junction is not None:
            assert high < path.length - rule.bay_stop_line_clearance_mm


def test_a_space_is_reached_only_beyond_the_region_and_clear_of_zones_crossings_and_stop_line():
    # A lane 100 m long leaving a junction whose region ends 8 m along it, with a conflict zone at
    # 20 to 22 m and a crossing band at 50 to 53 m, running to another junction.
    network = SimpleNamespace(
        exit_extent={"lane:a": 8_000},
        zones_by_path={"lane:a": [("zone", (20_000, 22_000))]},
        bands_by_path={"lane:a": [("band", (50_000, 53_000))]},
    )
    lane = SimpleNamespace(path_id="lane:a", length=100_000, end_junction="j")
    reach = city_derivation._subtract(
        (0, lane.length), city_derivation._forbidden(network, lane, 6_096, 9_144)
    )
    assert reach == [(8_001, 19_999), (22_001, 43_903), (59_097, 90_855)]
    # The same lane where the records stop at both ends: its first point is still not reached.
    network.exit_extent["lane:a"] = 0
    edge = SimpleNamespace(path_id="lane:a", length=100_000, end_junction=None)
    reach = city_derivation._subtract(
        (0, edge.length), city_derivation._forbidden(network, edge, 0, 0)
    )
    assert reach == [(1, 19_999), (22_001, 49_999), (53_001, 100_000)]


def test_a_cycle_space_holds_the_bicycles_its_stand_takes_and_contains_its_stand():
    records = corridor.derived().records
    furniture = next(
        c for c in load_city_catalogs(grammar_version=4) if c.catalog_id == "street-furniture"
    )
    stands = {item.identity: item for item in _of(records, StreetFurnitureRecord)}
    spaces = [s for s in _of(records, ParkingSpaceRecord) if s.placement == "footway"]
    assert len(spaces) == 10
    for space in spaces:
        [stand_id] = space.furniture_identities
        stand = stands[stand_id]
        assert (
            space.capacity == entry_fields(furniture, stand.furniture_class)["bicycles_per_stand"]
        )
        xs = [x for x, _ in space.footprint_mm]
        ys = [y for _, y in space.footprint_mm]
        assert min(xs) < stand.x_mm < max(xs) and min(ys) < stand.y_mm < max(ys)


def _reachable(network, start, class_key, forward=True):
    """Paths a class reaches from ``start`` (or that reach it), breadth first, on its own."""
    seen = {start}
    queue = deque([start])
    back = {}
    if not forward:
        for path_id, path in network.paths.items():
            for successor in path.successors:
                back.setdefault(successor, []).append(path_id)
    while queue:
        here = queue.popleft()
        onward = network.paths[here].successors if forward else back.get(here, [])
        for nxt in onward:
            if nxt not in seen and class_key in network.paths[nxt].classes:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def test_every_space_can_be_driven_to_and_left_by_a_class_it_admits(network):
    for space in network.spaces.values():
        assert space.classes, space.identity
        key = space.classes[0]
        out = _reachable(network, space.access_path, key)
        back = _reachable(network, space.access_path, key, forward=False)
        others = {other.access_path for other in network.spaces.values() if key in other.classes}
        assert (out & back & others) - {space.access_path}, space.identity


def test_the_network_compiles_with_every_derived_space_usable(network):
    assert len(network.spaces) == 69
    restricted = [row for row in network.restrictions if row[0] in network.spaces]
    assert restricted == []
    assert {space.kind for space in network.spaces.values()} == {"general", "cycle_stand"}
    assert corridor.derived().document()["left_out"], "the parking lanes off the round network"


def test_a_leg_off_the_plan_axes_is_refused_by_name():
    records = list(corridor.records())
    index = next(
        i for i, r in enumerate(records) if type(r) is LaneRecord and r.direction == "forward"
    )
    lane = records[index]
    (x0, y0, z0), (x1, y1, z1) = lane.centreline_mm[0], lane.centreline_mm[-1]
    bent = ((x0, y0, z0), (x1 + (1 if x0 == x1 else 0), y1 + (1 if y0 == y1 else 0), z1))
    records[index] = dataclasses.replace(lane, centreline_mm=bent)
    with pytest.raises(UnsupportedNetworkError, match="does not run along a plan axis"):
        derive_road_records(
            records,
            load_traffic_catalogs(),
            load_city_catalogs(grammar_version=4),
            city_identity=CORRIDOR_CITY_IDENTITY,
        )
