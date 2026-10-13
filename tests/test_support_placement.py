"""Explicit support, immutable kind geometry and protected actor routes at placement admission."""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import replace

import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.world.objects import ObjectOrigin, Transform
from exulanica.world.placed_things import ThingKindReference, ThingPlacement
from exulanica.world.support_placement import (
    PlacementContext,
    PlacementSolid,
    SupportPlacementRefused,
    read_supported_placement,
    validate_supported_placement,
)
from exulanica.world.support_surfaces import SupportNetwork, seal_support_network

from test_support_surfaces import network_document


def context(document=None, **changes):
    return PlacementContext(
        world_id="world:test",
        version_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        source_snapshot_id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
        receipt_sha256="a" * 64,
        base_state_sha256="b" * 64,
        region_id="region:test",
        network=seal_support_network(network_document() if document is None else document),
        **changes,
    )


def placement(kind=None, **changes):
    kind = shipped_thing_kinds()[("lantern", 1)] if kind is None else kind
    return ThingPlacement(
        thing_id="thing:placed",
        kind=ThingKindReference(kind.kind, kind.version, kind.sha256),
        region_id="region:test",
        transform=Transform(6000, 150, 1000, 3141593, 1000),
        origin=ObjectOrigin("authored", "fictional"),
        **changes,
    )


def admitted(placed=None, ctx=None, reference=None, kind=None):
    ctx = context() if ctx is None else ctx
    kind = shipped_thing_kinds()[("lantern", 1)] if kind is None else kind
    return validate_supported_placement(
        placement(kind) if placed is None else placed,
        kind,
        ctx.reference("deck") if reference is None else reference,
        context=ctx,
    )


def test_explicit_passive_rigid_placement_replays_without_floor_inference():
    ctx = context()
    p = placement()
    outcome = admitted(p, ctx)
    assert outcome.placement == p
    receipt = outcome.document()
    assert receipt["support"] == ctx.reference("deck")
    assert receipt["placement"]["transform"]["y_mm"] == 150
    assert receipt["body"] == {
        "kind_sha256": p.kind.sha256,
        "box_mm": {"width": 180, "depth": 180, "height": 300},
        "all_yaw_radius_mm": 128,
    }
    assert (
        read_supported_placement(
            json.loads(json.dumps(receipt)), p, shipped_thing_kinds()[("lantern", 1)], context=ctx
        )
        == outcome
    )
    receipt["body"]["box_mm"]["height"] = 1
    assert outcome.document()["body"]["box_mm"]["height"] == 300
    receipt.pop("document_sha256")
    receipt["document_sha256"] = sha256_of_canonical(receipt).hex()
    with pytest.raises(SupportPlacementRefused, match="recomputed"):
        read_supported_placement(receipt, p, shipped_thing_kinds()[("lantern", 1)], context=ctx)


@pytest.mark.parametrize(
    "field,value",
    [
        ("world_id", "world:other"),
        ("source_snapshot_id", "33333333-3333-4333-8333-333333333333"),
        ("receipt_sha256", "c" * 64),
        ("network_sha256", "c" * 64),
        ("region_id", "region:other"),
        ("surface_id", "unknown"),
        ("profile", "unknown"),
    ],
)
def test_reference_cannot_substitute_world_source_network_region_or_surface(field, value):
    ctx = context()
    ref = ctx.reference("deck")
    ref[field] = value
    with pytest.raises(SupportPlacementRefused):
        admitted(ctx=ctx, reference=ref)


@pytest.mark.parametrize(
    "pose",
    [
        Transform(4010, 150, 1000, 0, 1000),  # centre supported but full footprint overhangs
        Transform(6000, 0, 1000, 0, 1000),  # wrong explicit support height
        Transform(6000, 150, 1000, 0, 2000),  # authored scaling is not a thing's body
    ],
)
def test_body_pose_and_full_footprint_are_authoritative(pose):
    with pytest.raises(SupportPlacementRefused):
        admitted(replace(placement(), transform=pose))


def test_source_solids_other_placements_unknown_proxies_and_low_ceiling_refuse():
    raw = network_document()
    raw["solids"] = [{"solid_id": "source", "box_mm": [5800, 800, 150, 6200, 1200, 500]}]
    with pytest.raises(SupportPlacementRefused, match="obstruction"):
        admitted(ctx=context(raw))
    volume = PlacementSolid("thing:other", (5800, 800, 150, 6200, 1200, 500))
    with pytest.raises(SupportPlacementRefused, match="obstruction"):
        admitted(ctx=context(other_solids=(volume,)))
    with pytest.raises(SupportPlacementRefused, match="no authoritative"):
        admitted(ctx=context(unknown_obstructions=("object:unbounded-mesh",)))
    raw = network_document()
    raw["surfaces"].append(
        {"surface_id": "overhead", "rect_mm": [5800, 800, 6200, 1200], "support_z_mm": 400}
    )
    raw["surfaces"].sort(key=lambda s: s["surface_id"])
    with pytest.raises(SupportPlacementRefused, match="height"):
        admitted(ctx=context(raw))


def test_declared_actor_poses_and_connection_interior_remain_clear():
    with pytest.raises(SupportPlacementRefused, match=r"actor\.nodes"):
        admitted(replace(placement(), transform=Transform(5000, 150, 2000, 0, 1000)))
    # This clears both deck endpoint poses, but blocks the middle of their full swept route.
    with pytest.raises(SupportPlacementRefused, match=r"actor\.connections"):
        admitted(replace(placement(), transform=Transform(6000, 150, 2000, 0, 1000)))


def test_rigid_being_is_not_a_passive_object_and_mutated_kind_is_not_admitted():
    kind = shipped_thing_kinds()[("knight", 1)]
    with pytest.raises(SupportPlacementRefused, match="passive"):
        admitted(placement(kind), kind=kind)
    kind = shipped_thing_kinds()[("lantern", 1)]
    document = copy.deepcopy(dict(kind.document))
    document["body"]["box_mm"]["height"] = 1
    with pytest.raises(SupportPlacementRefused, match="immutable"):
        admitted(kind=replace(kind, document=document))


def test_replay_binds_version_state_and_authoritative_obstruction_digest():
    ctx = context()
    outcome = admitted(ctx=ctx)
    for changed in (
        replace(ctx, version_id=uuid.uuid4()),
        replace(ctx, base_state_sha256="c" * 64),
        replace(ctx, other_solids=(PlacementSolid("far-away", (0, 0, 0, 100, 100, 100)),)),
    ):
        with pytest.raises(SupportPlacementRefused, match="recomputed"):
            read_supported_placement(
                outcome.document(),
                placement(),
                shipped_thing_kinds()[("lantern", 1)],
                context=changed,
            )
    with pytest.raises(SupportPlacementRefused, match="canonical"):
        admitted(ctx=replace(ctx, network=SupportNetwork(ctx.network.encoded, "0" * 64)))


def test_same_xy_stacked_surfaces_use_explicit_identity_and_vertical_clearance():
    raw = network_document()
    raw["surfaces"].append(
        {"surface_id": "upper", "rect_mm": [4000, 0, 8000, 4000], "support_z_mm": 3000}
    )
    raw["surfaces"].sort(key=lambda s: s["surface_id"])
    ctx = context(raw)
    # The upper plane does not silently change a lower placement's height.
    assert admitted(ctx=ctx).placement.transform.y_mm == 150
    elevated = replace(placement(), transform=Transform(6000, 3000, 1000, 0, 1000))
    assert admitted(elevated, ctx, ctx.reference("upper")).placement.transform.y_mm == 3000
    with pytest.raises(SupportPlacementRefused, match="height"):
        admitted(elevated, ctx, ctx.reference("deck"))
