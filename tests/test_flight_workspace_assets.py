"""A person's own placed asset is solid in a world's flight, as the box its preparation measured.

Pure tests of :func:`exulanica.world.flight_input.compose_flight_input` with ``workspace_bounds``.
The route reads the measure from the preparation row
(``tests/test_workspace_asset_placement_postgres.py``).
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from exulanica.movement.air import PartBox
from exulanica.movement.flight import FlightRefused
from exulanica.world.authored_delta import AlternateVersion, delta_sha256
from exulanica.world.flight_input import compose_flight_input
from scripts.measure_flight_bounds import VERSION_ID, WORLD_ID, _assets, _placed, ground

PREPARATION = uuid.UUID("5d1c0e7a-2f43-4b8e-9d6a-1a2b3c4d5e6f")
#: A measured bench: 1801 mm wide, 452 mm high and 603 mm deep.
MEASURED = {str(PREPARATION): (1_801, 452, 603)}


def bench(**changes):
    obj = dataclasses.replace(
        _placed("bench", "cc0.planter-tree", 6_000, 6_000, 0, 1000),
        asset_sha256="a" * 64,
        workspace_preparation_id=PREPARATION,
    )
    return dataclasses.replace(obj, **changes)


def flight(*objects, bounds=None):
    version = AlternateVersion(
        version_id=VERSION_ID,
        world_id=WORLD_ID,
        source_snapshot_id=uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.invalid/bench"),
        parent_version_id=None,
        title="a bench beside a tree",
        style_version_id=None,
        state_sha256=delta_sha256(
            objects=objects,
            element_overrides=(),
            environment_instances=(),
            point_map_instances=(),
            things=(),
        ),
        edit_seq=len(objects),
        source_invalidated=False,
        created_by=uuid.UUID(int=1),
        created_at="2026-09-30T00:00:00+00:00",
        objects=objects,
    )
    keys = {digest: key for key, digest in _assets().items()}
    return compose_flight_input(
        world_id=WORLD_ID,
        version=version,
        ground=ground(),
        asset_keys=keys,
        workspace_bounds=bounds,
    )


TREE = _placed("tree", "cc0.planter-tree", 0, 0, 0, 1000)


def test_a_placed_custom_object_is_one_solid_box_and_hosts_nothing():
    alone = flight(TREE)
    beside = flight(TREE, bench(), bounds=MEASURED)
    [solid] = [solid for solid in beside.solids if solid.object_id == "bench"]
    assert solid.box == PartBox(-901, 901, -302, 302, 0, 452)
    assert solid.travel_mm == (0, 0, 0)
    assert not [perch for perch in beside.perches if perch.object_id == "bench"]
    # Far from the tree, it takes nothing from the tree's birds.
    assert [flyer.flyer_id for flyer in beside.flyers] == [flyer.flyer_id for flyer in alone.flyers]
    assert beside.unplaced == alone.unplaced


def test_a_custom_object_without_its_measure_is_refused_by_name():
    with pytest.raises(FlightRefused) as refused:
        flight(TREE, bench(), bounds={})
    assert (refused.value.code, refused.value.detail) == (
        "flight_unavailable",
        "unknown_object_geometry:bench",
    )


def test_a_custom_object_is_never_read_through_the_reviewed_registry():
    """Even when its prepared digest is a reviewed asset's, only its own measure stands for it."""
    tree_digest = _assets()["cc0.planter-tree"]
    with pytest.raises(FlightRefused):
        flight(bench(asset_sha256=tree_digest), bounds={})
    measured = flight(bench(asset_sha256=tree_digest), bounds=MEASURED)
    assert [solid.box for solid in measured.solids] == [PartBox(-901, 901, -302, 302, 0, 452)]
    assert not measured.flyers


def test_a_removed_custom_object_is_not_solid():
    assert not [
        solid
        for solid in flight(TREE, bench(removed=True), bounds={}).solids
        if solid.object_id == "bench"
    ]


def test_a_world_without_custom_objects_composes_the_same_input_whatever_is_passed():
    assert flight(TREE) == flight(TREE, bounds={}) == flight(TREE, bounds=MEASURED)
