"""The compact multi-view source generator and its durable provenance."""

from __future__ import annotations

import hashlib
import json

from exulanica.canonical import canonical_json
from exulanica.evaluation.synthetic_multiview import (
    SyntheticFixtureParameters,
    generate_synthetic_multiview,
)
from PIL import Image


def _record(path):
    envelope = json.loads(path.read_bytes())
    assert envelope["record_sha256"] == hashlib.sha256(
        canonical_json(envelope["record"])
    ).hexdigest()
    return envelope["record"]


def test_generation_is_byte_deterministic_and_every_frame_marks_itself_synthetic(tmp_path):
    params = SyntheticFixtureParameters(width=400, height=300, view_count=3)
    first = generate_synthetic_multiview(tmp_path / "first", params)
    second = generate_synthetic_multiview(tmp_path / "second", params)

    assert first.source_manifest_digest == second.source_manifest_digest
    assert first.camera_manifest_digest == second.camera_manifest_digest
    assert first.scene_manifest_digest == second.scene_manifest_digest
    source = _record(first.source_manifest_path)
    assert source["corpus_class"] == "synthetic"
    assert "NOT PERSONAL" in source["notice"]
    for item in source["images"]:
        left = (first.image_directory / item["path"]).read_bytes()
        right = (second.image_directory / item["path"]).read_bytes()
        assert left == right
        assert hashlib.sha256(left).hexdigest() == item["sha256"]
        with Image.open(first.image_directory / item["path"]) as image:
            assert image.getexif()[270] == "SYNTHETIC EXULANICA MULTI-VIEW FIXTURE"


def test_camera_manifest_binds_known_intrinsics_extrinsics_and_scene(tmp_path):
    fixture = generate_synthetic_multiview(
        tmp_path / "fixture",
        SyntheticFixtureParameters(width=400, height=300, view_count=4),
    )
    cameras = _record(fixture.camera_manifest_path)
    scene = _record(fixture.scene_manifest_path)
    assert cameras["scene_manifest_sha256"] == fixture.scene_manifest_digest
    assert len(cameras["views"]) == 4
    assert len({tuple(view["camera_center_metres"]) for view in cameras["views"]}) == 4
    assert all(len(view["world_from_camera_rotation"]) == 3 for view in cameras["views"])
    assert scene["seed"] == 20260904
    assert scene["surface_count"] == 8
