"""Composition policy with instrumented geometry predicates, not polygon evidence."""

import hashlib
import uuid
from copy import deepcopy
from dataclasses import replace

import pytest
from exulanica.world.assets import reviewed_assets
from exulanica.world.objects import (
    AlternateVersion,
    AuthoredObject,
    ObjectBehaviour,
    ObjectOrigin,
    Transform,
    delta_sha256,
)
from exulanica.world.society_composition import build_society_input
from exulanica.world.society_planner import input_sha256, validate_society_input

from society_fixtures import VERSION, society_input

ASSETS = {asset.asset_key: asset.content_sha256 for asset in reviewed_assets()}
BASE = b"SYNTHETIC instrumented geometry fixture, not an admitted source"


def registry():
    return {
        ASSETS[key]: {
            "asset_key": key,
            "affordance": action,
            "duration_ticks": duration,
            "footprint_half_extents_mm": extents,
            "blocks_navigation": blocks,
            "reach_mm": 6000,
        }
        for key, action, duration, extents, blocks in [
            ("cc0.marker-cube", "visit", 1, [250, 250], True),
            ("cc0.marker-pillar", "visit", 1, [125, 125], True),
            ("cc0.marker-plate", "rest", 3, [500, 500], False),
        ]
    }


def obj(key="cc0.marker-plate", **changes):
    value = AuthoredObject(
        "object:personal-marker",
        ASSETS[key],
        "region-a",
        Transform(40000, 0, 40000, 0, 1000),
        ObjectOrigin("authored", "personal"),
    )
    return replace(value, **changes)


def version(objects=(), **changes):
    value = AlternateVersion(
        VERSION,
        "atlas:default",
        uuid.UUID("0069bd32-851f-4f25-b9a8-9e2b38565bc1"),
        None,
        "Synthetic authored composition",
        None,
        delta_sha256(objects, ()),
        0,
        False,
        uuid.UUID("0069bd32-851f-4f25-b9a8-9e2b38565bc1"),
        "2026-09-13T12:00:00Z",
        objects=objects,
    )
    return replace(value, **changes)


class GeometryProbe:
    """A scripted obstruction tests full-segment delegation, not a second geometry model."""

    def __init__(self, block_edge=False):
        self.calls = []
        self.block_edge = block_edge

    def supports(self, a, b, radius):
        return ["fixture-sidewalk"]

    def blocked(self, a, b, ring, radius):
        self.calls.append((a, b, deepcopy(ring), radius))
        return self.block_edge and a == (0, 0) and b == (40000, 0)


def arguments(held=None):
    held = held or version((obj(),))
    source = society_input()
    document = {
        "profile": "exulanica.district-interpretation/v1",
        "district_id": source["district_id"],
        "frame": source["frame"],
        "navigation": source["navigation"],
        "base_artifact_sha256": hashlib.sha256(BASE).hexdigest(),
    }
    document["document_sha256"] = input_sha256(document)
    probe = GeometryProbe()
    return {
        "interpretation": document,
        "base_bytes": BASE,
        "version": held,
        "registration": {
            "world_id": held.world_id,
            "version_id": str(held.version_id),
            "source_snapshot_id": str(held.source_snapshot_id),
            "region_id": "region-a",
            "district_id": document["district_id"],
            "frame_name": "flatiron-local-mm",
            "translation_mm": [0, 0, 0],
            "yaw_microradians": 0,
            "scale_milli": 1000,
        },
        "input_seq": 1,
        "dependency_refs": [],
        "availability": "available",
        "unavailable_reason": None,
        "reviewed_affordances": registry(),
        "supports": probe.supports,
        "segment_blocked": probe.blocked,
    }


def test_authored_plate_preserves_identity_origin_refs_and_does_not_move_objects():
    args = arguments()
    before = deepcopy(args["interpretation"])
    result = build_society_input(**args)
    validate_society_input(result)
    assert result["availability"] == "available"
    target = next(t for t in result["targets"] if t["origin"] == "authored")
    assert target["object_id"] == "object:personal-marker"
    assert target["version_id"] == str(VERSION)
    assert target["affordance"] == "rest" and target["duration_ticks"] == 3
    assert target["node_id"] == "c"
    assert args["version"].objects[0].transform.x_mm == 40000
    assert args["interpretation"] == before
    refs = result["dependency_refs"]
    assert any(r["kind"] == "authored_object" for r in refs)
    assert any(
        r["kind"] == "reviewed_asset" and r["sha256"] == ASSETS["cc0.marker-plate"] for r in refs
    )
    assert result == build_society_input(**args)


def test_translation_is_explicit_and_not_a_nearest_node_pose_change():
    held = version((obj(transform=Transform(39000, 0, 38000, 0, 1000)),))
    args = arguments(held)
    args["registration"]["translation_mm"] = [1000, 0, 2000]
    result = build_society_input(**args)
    assert result["availability"] == "available"
    target = next(t for t in result["targets"] if t["origin"] == "authored")
    assert target["node_id"] == "c"
    assert held.objects[0].transform == Transform(39000, 0, 38000, 0, 1000)


def test_whole_edge_obstruction_is_delegated_and_pruned_with_valid_endpoints():
    args = arguments(version((obj("cc0.marker-cube"),)))
    probe = GeometryProbe(block_edge=True)
    args.update(supports=probe.supports, segment_blocked=probe.blocked)
    result = build_society_input(**args)
    assert result["availability"] == "available"
    assert "ab" not in {e["edge_id"] for e in result["navigation"]["edges"]}
    assert {"a", "b"}.issubset({n["node_id"] for n in result["navigation"]["nodes"]})
    assert any(
        a == (0, 0) and b == (40000, 0) and radius == 450 for a, b, _ring, radius in probe.calls
    )
    assert all(ring[0] == ring[-1] for _a, _b, ring, _radius in probe.calls)


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"asset_sha256": "e" * 64}, "unknown_active_asset"),
        (
            {"behaviour": ObjectBehaviour("motion.bounded-path", 1, {})},
            "unsupported_active_behaviour",
        ),
        ({"transform": Transform(0, 0, 0, 1, 1000)}, "unsupported_object_transform"),
        ({"transform": Transform(0, 0, 0, 0, 2000)}, "unsupported_object_transform"),
        ({"transform": Transform(0, 1, 0, 0, 1000)}, "unsupported_object_transform"),
        ({"region_id": "other"}, "unregistered_object_region"),
        ({"transform": Transform(1000000, 0, 0, 0, 1000)}, "authored_affordance_unreachable"),
    ],
)
def test_unknown_active_geometry_and_unreachable_affordance_fail_closed(changes, reason):
    result = build_society_input(**arguments(version((obj(**changes),))))
    assert result["availability"] == "unavailable"
    assert result["unavailable_reason"].startswith(reason)
    assert result["navigation"]["nodes"] == [] and result["targets"] == []


@pytest.mark.parametrize(
    "change",
    [
        lambda a: a.update(registration=None),
        lambda a: a["registration"].update(version_id=str(uuid.uuid4())),
        lambda a: a["registration"].update(yaw_microradians=1),
        lambda a: a["registration"].update(scale_milli=2000),
        lambda a: a.update(availability="unavailable", unavailable_reason="source_withdrawn"),
    ],
)
def test_registration_and_current_availability_fail_closed(change):
    args = arguments()
    change(args)
    result = build_society_input(**args)
    assert result["availability"] == "unavailable"
    assert result["navigation"]["edges"] == []


def test_move_remove_and_undo_have_distinct_inputs_with_stable_target_id():
    initial = version((obj(),))
    first = build_society_input(**arguments(initial))
    moved = version((obj(transform=Transform(40000, 0, 0, 0, 1000)),), edit_seq=1)
    args = arguments(moved)
    args["input_seq"] = 2
    second = build_society_input(**args)
    removed = version((obj(removed=True),), edit_seq=2)
    args = arguments(removed)
    args["input_seq"] = 3
    third = build_society_input(**args)
    restored = replace(initial, edit_seq=3)
    args = arguments(restored)
    args["input_seq"] = 4
    fourth = build_society_input(**args)

    def target(document):
        return next(t for t in document["targets"] if t["origin"] == "authored")

    assert target(first)["target_id"] == target(second)["target_id"] == target(fourth)["target_id"]
    assert target(second)["node_id"] == "b" and target(fourth)["node_id"] == "c"
    assert not any(t["origin"] == "authored" for t in third["targets"])
    assert len({d["document_sha256"] for d in (first, second, third, fourth)}) == 4
    assert first["authored_state"]["delta_sha256"] == fourth["authored_state"]["delta_sha256"]


def test_unknown_removed_object_does_not_invent_active_obstacle():
    result = build_society_input(**arguments(version((obj(asset_sha256="e" * 64, removed=True),))))
    assert result["availability"] == "available"


def test_wrong_source_delta_or_unreviewed_assignment_refuses_receipt():
    args = arguments()
    args["base_bytes"] = b"changed"
    with pytest.raises(ValueError, match="base artifact digest"):
        build_society_input(**args)
    args = arguments()
    args["version"] = replace(args["version"], state_sha256="e" * 64)
    with pytest.raises(ValueError, match="delta digest"):
        build_society_input(**args)
    args = arguments()
    args["reviewed_affordances"][ASSETS["cc0.marker-cube"]]["blocks_navigation"] = False
    with pytest.raises(ValueError, match="unreviewed"):
        build_society_input(**args)
