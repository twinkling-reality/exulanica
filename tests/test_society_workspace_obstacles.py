"""A person's own placed asset stands in a society as the obstacle its preparation measured.

Pure tests of the composers with ``workspace_obstacles``. The runtime's reading of preparation
rows into these obstacles is held by ``tests/test_workspace_asset_placement_postgres.py``.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from exulanica.environment.district_geometry import segment_blocked
from exulanica.world.object_catalog import NO_ACTIVITY
from exulanica.world.objects import AuthoredObject, ObjectOrigin, Transform
from exulanica.world.society_authored_ground import build_authored_ground_society_input
from exulanica.world.society_composition import (
    WORKSPACE_OBSTACLE_PREFIX,
    validate_workspace_obstacles,
    workspace_obstacle,
)
from exulanica.world.society_planner import validate_society_input

import test_society_authored_ground as authored
from test_society_turned_objects import UNTURNED

PREPARATION = uuid.UUID("5d1c0e7a-2f43-4b8e-9d6a-1a2b3c4d5e6f")
#: The prepared output's digest. It equals a reviewed asset's digest on purpose in one test below.
OUTPUT = "a" * 64
#: A measured bench: 1801 mm wide and 603 mm deep.
MEASURED = {str(PREPARATION): workspace_obstacle(PREPARATION, 1_801, 603)}


def custom(object_id: str, x_mm: int, z_mm: int, **changes) -> AuthoredObject:
    obj = AuthoredObject(
        object_id=object_id,
        asset_sha256=OUTPUT,
        region_id="region:starter",
        transform=Transform(x_mm=x_mm, y_mm=0, z_mm=z_mm, yaw_microradians=0, scale_milli=1000),
        origin=ObjectOrigin("authored", "fictional"),
        workspace_preparation_id=PREPARATION,
    )
    return dataclasses.replace(obj, **changes)


def compose(area, world_version, obstacles):
    return build_authored_ground_society_input(
        ground=area,
        version=world_version,
        input_seq=1,
        dependency_refs=(),
        availability="available",
        unavailable_reason=None,
        reviewed_affordances=authored.REGISTRY,
        segment_blocked=segment_blocked,
        workspace_obstacles=obstacles,
    )


def node_ids(document) -> set[str]:
    return {node["node_id"] for node in document["navigation"]["nodes"]}


def test_the_obstacle_is_the_measure_rounded_up_and_offers_nothing():
    row = workspace_obstacle(PREPARATION, 1_801, 603)
    assert row == {
        "asset_key": f"{WORKSPACE_OBSTACLE_PREFIX}{PREPARATION}",
        "affordance": NO_ACTIVITY,
        "footprint_half_extents_mm": [901, 302],
        "blocks_navigation": True,
    }
    validate_workspace_obstacles(MEASURED)


@pytest.mark.parametrize(
    "change",
    [
        {"affordance": "rest"},
        {"blocks_navigation": False},
        {"asset_key": "cc0.marker-pillar"},
        {"footprint_half_extents_mm": [-1, 2]},
        {"reach_mm": 600},
    ],
    ids=["activity", "walkable", "reviewed-key", "negative", "extra-field"],
)
def test_an_obstacle_that_is_not_exactly_the_measure_is_refused(change):
    row = {**MEASURED[str(PREPARATION)], **change}
    with pytest.raises(ValueError, match="invalid workspace asset obstacle"):
        validate_workspace_obstacles({str(PREPARATION): row})


def test_a_placed_custom_object_blocks_walking_where_it_stands_and_is_bound_to_its_preparation():
    world = authored.version(custom("object:bench", 4_000, 4_000))
    document = compose(authored.ground(), world, MEASURED)
    validate_society_input(document)
    assert document["availability"] == "available", document["unavailable_reason"]
    empty = compose(authored.ground(), authored.version(), {})
    assert "ground:+00004000:+00004000" in node_ids(empty)
    assert "ground:+00004000:+00004000" not in node_ids(document)
    # An obstacle only: nobody uses it, and it records no refused activity either.
    assert document["targets"] == []
    assert document["unavailable_affordances"] == []
    assert {
        "kind": "workspace_asset",
        "identity": str(PREPARATION),
        "sha256": OUTPUT,
    } in document["dependency_refs"]
    assert not [ref for ref in document["dependency_refs"] if ref["kind"] == "reviewed_asset"]


def test_two_placements_of_one_preparation_are_two_obstacles_and_one_binding():
    world = authored.version(
        custom("object:bench-a", 4_000, 4_000), custom("object:bench-b", -4_000, -4_000)
    )
    document = compose(authored.ground(), world, MEASURED)
    validate_society_input(document)
    assert {"ground:+00004000:+00004000", "ground:-00004000:-00004000"}.isdisjoint(
        node_ids(document)
    )
    bindings = [ref for ref in document["dependency_refs"] if ref["kind"] == "workspace_asset"]
    assert bindings == [{"kind": "workspace_asset", "identity": str(PREPARATION), "sha256": OUTPUT}]


def test_a_removed_custom_object_stands_nowhere():
    world = authored.version(custom("object:bench", 4_000, 4_000, removed=True))
    document = compose(authored.ground(), world, MEASURED)
    assert document["availability"] == "available"
    assert "ground:+00004000:+00004000" in node_ids(document)
    assert not [ref for ref in document["dependency_refs"] if ref["kind"] == "workspace_asset"]


def test_a_custom_object_is_never_read_through_the_reviewed_registry():
    """Even when its prepared digest is a reviewed asset's, only its own measure stands for it."""
    world = authored.version(
        custom("object:bench", 4_000, 4_000, asset_sha256=authored.PILLAR.content_sha256)
    )
    document = compose(authored.ground(), world, {})
    assert document["availability"] == "unavailable"
    assert document["unavailable_reason"] == "unknown_active_asset:object:bench"


@pytest.mark.parametrize(
    ("area", "digest"),
    [
        (authored.ground(), "205099b240299d9833241d67789e1524de051648f1afe1c9cb518595013c7956"),
        (authored.endless(), "b496b4d0eb430ffbe9b9d6640230c97c050a1398513aca1990238831be48ea5a"),
    ],
    ids=["bounded", "endless"],
)
@pytest.mark.parametrize("obstacles", [None, {}, MEASURED], ids=["none", "empty", "unused"])
def test_a_world_without_custom_objects_composes_to_its_pinned_bytes(area, digest, obstacles):
    """The digests ``tests/test_society_turned_objects.py`` pins, whatever the runtime passes."""
    assert compose(area, UNTURNED, obstacles)["document_sha256"] == digest
