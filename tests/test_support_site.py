"""Actual site records, source-bound supports, preserved activities and replay."""

from __future__ import annotations

import copy
import json

import pytest
from exulanica.world.composers import site_plan
from exulanica.world.kinds.document import read_kind
from exulanica.world.site_drawing import site_drawing
from exulanica.world.support_site import AUTHORING_PROFILE, attach_site_support, read_site_support
from exulanica.world.support_surfaces import SupportRefused

from kind_briefs import fixture_kind
from test_support_surfaces import destination


def context():
    kind = read_kind(fixture_kind("farm"))
    world = site_plan.compose_kind(
        kind, kind.values(kind.presets[0][0]), "world:generated:support", place_id="place:test"
    )
    return {
        "world_id": world.receipt["world_id"],
        "records": world.records,
        "drawing": site_drawing(
            world_id=world.receipt["world_id"],
            receipt=world.receipt,
            receipt_sha256=world.receipt_sha256,
            records=world.records,
        ),
        "base_place": world.place,
        "routine": site_plan.receipt_routine(world.receipt),
    }


def authoring(base):
    entry = next(n for n in base["nodes"] if n["node_id"] == "entry")
    x, y = entry["position_mm"]
    return {
        "profile": AUTHORING_PROFILE,
        "network_id": "network:authored",
        "actor": {"radius_mm": 340, "height_mm": 1800, "maximum_step_mm": 180},
        "surfaces": [
            {
                "surface_id": "deck",
                "rect_mm": [x + 2000, -y - 6000, x + 4000, -y - 4000],
                "support_z_mm": 150,
            }
        ],
        "nodes": [
            {"node_id": "approach", "surface_id": "base-ground", "position_mm": [x, -y - 3000]},
            {
                "node_id": "corner",
                "surface_id": "base-ground",
                "position_mm": [x + 3000, -y - 3000],
            },
            {"node_id": "view", "surface_id": "deck", "position_mm": [x + 3000, -y - 5000]},
        ],
        "connections": [
            {
                "connection_id": "approach",
                "from_node_id": "source-entry",
                "to_node_id": "approach",
                "kind": "walk",
            },
            {
                "connection_id": "corner",
                "from_node_id": "approach",
                "to_node_id": "corner",
                "kind": "walk",
            },
            {
                "connection_id": "step",
                "from_node_id": "corner",
                "to_node_id": "view",
                "kind": "step",
            },
        ],
        "destinations": [destination("view")],
        "spots": {"spot:rest": "view"},
    }


def test_actual_geometry_attaches_replays_and_preserves_source_destinations():
    ctx = context()
    input_ = authoring(ctx["base_place"])
    pre = copy.deepcopy(input_)
    support = attach_site_support(input_, **ctx)
    assert input_ == pre
    place = support.projection.place()
    original = {d["destination_id"] for d in ctx["base_place"]["destinations"]}
    assert original < {d["destination_id"] for d in place["destinations"]}
    assert (
        support.network.document()["source"]["geometry_sha256"]
        == ctx["base_place"]["source"]["document_sha256"]
    )
    assert {n["support_z_mm"] for n in place["nodes"]} == {0, 150}
    assert (
        read_site_support(json.loads(json.dumps(support.document())), **ctx).document()
        == support.document()
    )
    assert support.adapter_document()["node_surfaces"]
    assert (
        support.adapter_document()["entry_node_id"] in support.adapter_document()["node_surfaces"]
    )


def test_source_seat_keeps_its_posture_but_not_new_ceilings_or_other_solids():
    ctx = context()
    spec = authoring(ctx["base_place"])
    support = attach_site_support(spec, **ctx)
    seat = next(s for s in ctx["base_place"]["spots"] if ":seat:" in s["spot_id"])
    assert seat["spot_id"] in {s["spot_id"] for s in support.projection.place()["spots"]}
    x, y = seat["position_mm"]
    spec["surfaces"].append(
        {
            "surface_id": "low-ceiling",
            "rect_mm": [x - 400, -y - 400, x + 400, -y + 400],
            "support_z_mm": 1000,
        }
    )
    with pytest.raises(SupportRefused, match="headroom"):
        attach_site_support(spec, **ctx)
    # A second actual source obstruction at the seat cannot inherit the bench exception.
    ctx["drawing"]["walk"]["keepOutMm"].append([x - 100, y - 100, x + 100, y + 100])
    with pytest.raises(SupportRefused, match="solid"):
        attach_site_support(authoring(ctx["base_place"]), **ctx)


def test_larger_actor_does_not_inherit_human_seat_posture_exemption():
    ctx = context()
    spec = authoring(ctx["base_place"])
    spec["actor"]["height_mm"] = 2000
    with pytest.raises(SupportRefused):
        attach_site_support(spec, **ctx)


def test_replay_refuses_client_rehash_of_missing_actual_obstacle():
    ctx = context()
    support = attach_site_support(authoring(ctx["base_place"]), **ctx)
    raw = support.document()
    raw["network"]["solids"] = []
    from exulanica.world.support_surfaces import seal_support_network

    raw["network"] = seal_support_network(raw["network"]).document()
    with pytest.raises(SupportRefused, match="regenerated"):
        read_site_support(raw, **ctx)


def test_disconnected_added_destination_is_refused_before_any_persistence():
    ctx = context()
    spec = authoring(ctx["base_place"])
    spec["connections"] = []
    with pytest.raises(SupportRefused, match="reachable"):
        attach_site_support(spec, **ctx)
