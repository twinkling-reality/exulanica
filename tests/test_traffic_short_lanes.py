"""A lane too short for a class keeps the classes that fit it, and one too short for any is refused.

A vehicle is admitted into a junction region only with room beyond it for its whole body and gap,
so the compiler leaves a class off a lane that leaves a junction without that room, and says so in
the network's restrictions. The corridor's cross streets at city version 4 are where it happens.
"""

from __future__ import annotations

import dataclasses

import pytest
from exulanica.grammar.grammars.city.generation.corridor import CORRIDOR_CITY_IDENTITY
from exulanica.traffic.catalogs import load_traffic_catalogs
from exulanica.traffic.city_roads import road_input_from_city
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.traffic.network import compile_network

import traffic_corridor_support as corridor

_SHORT = "body and gap do not fit beyond the junction region it leaves"


@pytest.fixture(scope="module")
def road():
    # The records the derivation made, less its spaces: the lanes and connections alone.
    records = [r for r in corridor.derived().records if r not in corridor.derived().spaces]
    return road_input_from_city(
        records, load_traffic_catalogs(), city_identity=CORRIDOR_CITY_IDENTITY
    )


def test_every_lane_leaving_a_junction_holds_the_longest_class_it_keeps_beyond_its_region(road):
    catalogs = load_traffic_catalogs()
    network = compile_network(road, catalogs)
    short = [row for row in network.restrictions if row[2] == _SHORT]
    assert short, "the corridor's short cross streets leave some classes off"
    assert {key for _path, key, _why in short} == {"city_bus", "passenger_car", "van"}
    for path in network.paths.values():
        if path.kind != "lane" or path.start_junction is None:
            continue
        kept = [catalogs.vehicle_class(key) for key in path.classes]
        room = path.length - network.exit_extent[path.path_id]
        assert all(vehicle.length_mm + vehicle.minimum_gap_mm <= room for vehicle in kept)
        left = {key for lane, key, why in short if lane == path.path_id}
        assert not left & set(path.classes)


def test_a_lane_too_short_for_the_one_class_it_carries_is_refused_by_name(road):
    catalogs = load_traffic_catalogs()
    network = compile_network(road, catalogs)
    [lane_path] = sorted(
        {
            lane
            for lane, key, why in network.restrictions
            if why == _SHORT and key == "passenger_car"
        }
    )[:1]
    identity = lane_path.removeprefix("lane:")
    lanes = tuple(
        dataclasses.replace(lane, classes=("city_bus",)) if lane.identity == identity else lane
        for lane in road.lanes
    )
    with pytest.raises(
        UnsupportedNetworkError, match="too short to leave its junction region for any class"
    ):
        compile_network(dataclasses.replace(road, lanes=lanes), catalogs)
