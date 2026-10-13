"""Support identities, footprint clearance and exact traversal survive projection/replay."""

from __future__ import annotations

import json

import pytest
from exulanica.world.society_living import town_routine
from exulanica.world.society_place import validate_place
from exulanica.world.support_place import project_support_place
from exulanica.world.support_surfaces import (
    PROFILE,
    SupportRefused,
    read_support_network,
    seal_support_network,
)


def network_document():
    return {
        "profile": PROFILE,
        "network_id": "network:test",
        "source": {
            "world_id": "world:test",
            "geometry_profile": "exulanica.site-records/v1",
            "geometry_sha256": "1" * 64,
        },
        "frame": {
            "name": "region:test",
            "axis_order": ["east", "south"],
            "horizontal_unit": "millimetre",
            "vertical_unit": "millimetre",
            "datum": "region-origin",
        },
        "actor": {"radius_mm": 340, "height_mm": 1800, "maximum_step_mm": 180},
        "surfaces": [
            {"surface_id": "deck", "rect_mm": [4000, 0, 8000, 4000], "support_z_mm": 150},
            {"surface_id": "ground", "rect_mm": [0, 0, 4000, 4000], "support_z_mm": 0},
        ],
        "solids": [],
        "nodes": [
            {"node_id": "deck-end", "surface_id": "deck", "position_mm": [7000, 2000]},
            {"node_id": "deck-start", "surface_id": "deck", "position_mm": [5000, 2000]},
            {"node_id": "entry", "surface_id": "ground", "position_mm": [1000, 2000]},
            {"node_id": "ground-end", "surface_id": "ground", "position_mm": [3000, 2000]},
        ],
        "connections": [
            {
                "connection_id": "deck",
                "from_node_id": "deck-start",
                "to_node_id": "deck-end",
                "kind": "walk",
            },
            {
                "connection_id": "ground",
                "from_node_id": "entry",
                "to_node_id": "ground-end",
                "kind": "walk",
            },
            {
                "connection_id": "step",
                "from_node_id": "ground-end",
                "to_node_id": "deck-start",
                "kind": "step",
            },
        ],
        "entry_node_id": "entry",
    }


def test_step_route_and_surface_queries_replay_exactly():
    network = seal_support_network(network_document())
    assert network.reachable() == frozenset(n["node_id"] for n in network.document()["nodes"])
    assert network.support_at("deck", (5000, 2000)) == 150
    assert network.support_at("ground", (3000, 2000)) == 0
    with pytest.raises(SupportRefused):
        network.support_at("deck", (3000, 2000))
    replay = read_support_network(
        json.loads(json.dumps(network.document())), source=network.document()["source"]
    )
    assert replay == network
    projection = project_support_place(network, town_routine(), place_id="place:test")
    validate_place(projection.place(), town_routine())
    assert {n["support_z_mm"] for n in projection.place()["nodes"]} == {0, 150}
    assert projection.adapter_document()["node_surfaces"]
    assert (
        project_support_place(replay, town_routine(), place_id="place:test").encoded
        == projection.encoded
    )


def test_projected_crossing_never_creates_adjacency():
    raw = network_document()
    raw["surfaces"][0].update(rect_mm=[0, 0, 4000, 4000], support_z_mm=3000)
    raw["nodes"] = [
        {"node_id": "entry", "surface_id": "ground", "position_mm": [1000, 2000]},
        {"node_id": "upper", "surface_id": "deck", "position_mm": [1000, 2000]},
    ]
    raw["connections"] = []
    network = seal_support_network(raw)
    assert network.support_at("ground", (1000, 2000)) == 0
    assert network.support_at("deck", (1000, 2000)) == 3000
    assert network.reachable() == {"entry"}
    projection = project_support_place(network, town_routine(), place_id="place:stacked")
    nodes = projection.place()["nodes"]
    assert len({n["node_id"] for n in nodes}) == 2
    assert nodes[0]["position_mm"] == nodes[1]["position_mm"]
    assert projection.place()["edges"] == []
    raw["connections"] = [
        {"connection_id": "fake", "from_node_id": "entry", "to_node_id": "upper", "kind": "step"}
    ]
    with pytest.raises(SupportRefused, match="vertical teleport"):
        seal_support_network(raw)


@pytest.mark.parametrize("change", ["rise", "gap", "crosswalk", "diagonal", "radius", "headroom"])
def test_unsafe_connection_or_actor_geometry_is_refused(change):
    raw = network_document()
    if change == "rise":
        raw["surfaces"][0]["support_z_mm"] = 181
    elif change == "gap":
        raw["surfaces"][0]["rect_mm"][0] = 4500
    elif change == "crosswalk":
        raw["connections"][2]["kind"] = "walk"
    elif change == "diagonal":
        raw["nodes"][0]["position_mm"][1] = 2500
    elif change == "radius":
        raw["actor"]["radius_mm"] = 1500
    elif change == "headroom":
        raw["solids"] = [{"solid_id": "ceiling", "box_mm": [4000, 0, 1800, 8000, 4000, 2000]}]
    with pytest.raises(SupportRefused):
        seal_support_network(raw)


def test_swept_clearance_catches_obstacle_between_valid_nodes():
    raw = network_document()
    raw["solids"] = [{"solid_id": "wall", "box_mm": [1800, 1800, 0, 2200, 2200, 2000]}]
    with pytest.raises(SupportRefused, match="headroom"):
        seal_support_network(raw)


def test_large_body_cannot_inherit_human_route_clearance():
    raw = network_document()
    raw["actor"].update(radius_mm=10000, height_mm=8000)
    with pytest.raises(SupportRefused, match="footprint"):
        seal_support_network(raw)
    raw["surfaces"] = [{"surface_id": "apron", "rect_mm": [0, 0, 24000, 20000], "support_z_mm": 0}]
    raw["nodes"] = [
        {"node_id": "entry", "surface_id": "apron", "position_mm": [10000, 10000]},
        {"node_id": "end", "surface_id": "apron", "position_mm": [14000, 10000]},
    ]
    raw["nodes"].sort(key=lambda n: n["node_id"])
    raw["connections"] = [
        {
            "connection_id": "clear-route",
            "from_node_id": "entry",
            "to_node_id": "end",
            "kind": "walk",
        }
    ]
    network = seal_support_network(raw)
    assert network.reachable() == {"entry", "end"}
    assert network.support_at("apron", (12000, 10000)) == 0


def destination(node):
    return {
        "destination_id": "destination:rest",
        "subject_id": "subject:bench",
        "node_id": node,
        "origin": "authored",
        "object_id": None,
        "affordances": ["rest"],
        "duration_ticks": None,
        "indoors": False,
        "enabled": True,
        "visitor_capacity": 1,
        "spot_ids": ["spot:rest"],
        "use_class": None,
        "label": "Rest",
        "address_number": None,
        "street_segment_ordinal": None,
        "staff_capacity": 0,
        "resident_capacity": 0,
        "role": None,
        "shift": None,
    }


def test_activity_binding_requires_reachable_destination_and_standing_surface():
    network = seal_support_network(network_document())
    projection = project_support_place(
        network,
        town_routine(),
        place_id="place:activity",
        destinations=[destination("deck-end")],
        spots={"spot:rest": "deck-end"},
    )
    place = projection.place()
    assert place["spots"][0]["support_z_mm"] == 150
    assert place["destinations"][0]["node_id"] in projection.adapter_document()["node_surfaces"]
    raw = network_document()
    raw["connections"] = raw["connections"][:2]
    disconnected = seal_support_network(raw)
    with pytest.raises(SupportRefused, match="not reachable"):
        project_support_place(
            disconnected,
            town_routine(),
            place_id="place:activity",
            destinations=[destination("deck-end")],
            spots={"spot:rest": "deck-end"},
        )


def test_mutated_geometry_or_wrong_saved_source_is_refused_on_replay():
    network = seal_support_network(network_document())
    changed = network.document()
    changed["surfaces"][0]["support_z_mm"] = 100
    with pytest.raises(SupportRefused, match="canonical declaration"):
        read_support_network(changed)
    wrong = {**network.document()["source"], "geometry_sha256": "0" * 64}
    with pytest.raises(SupportRefused, match="caller"):
        read_support_network(network.document(), source=wrong)
    changed = network.document()
    changed["actor"]["radius_mm"] = True
    with pytest.raises(SupportRefused):
        read_support_network(changed)
    changed = network.document()
    changed["nodes"][0]["position_mm"][0] = 0.5
    with pytest.raises(SupportRefused):
        read_support_network(changed)


def test_explicit_step_query_supports_straddling_footprint_without_floor_snap():
    network = seal_support_network(network_document())
    # Each single-surface query conservatively refuses a footprint across its edge.
    with pytest.raises(SupportRefused):
        network.support_at("ground", (3950, 2000))
    assert network.connection_at("step", "ground", (3950, 2000)) == ("ground", 0)
    assert network.connection_at("step", "ground", (4050, 2000)) == ("deck", 150)
    assert network.connection_at("step", "deck", (3950, 2000)) == ("ground", 0)
    with pytest.raises(SupportRefused):
        network.connection_at("missing", "ground", (4000, 2000))
    with pytest.raises(SupportRefused):
        network.connection_at("step", "ground", (4000, 50))
    with pytest.raises(SupportRefused):
        network.connection_at("step", "ground", (1000, 2000))


def test_free_surface_motion_cannot_jump_through_solid_between_clear_endpoints():
    raw = network_document()
    raw["connections"] = []
    raw["solids"] = [{"solid_id": "wall", "box_mm": [1800, 1800, 0, 2200, 2200, 2000]}]
    network = seal_support_network(raw)
    assert network.support_at("ground", (1000, 2000)) == 0
    assert network.support_at("ground", (3000, 2000)) == 0
    with pytest.raises(SupportRefused):
        network.motion_on_surface("ground", (1000, 2000), (3000, 2000))
