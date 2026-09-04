"""Ground-truth comparison for a production synthetic pose receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.evaluation.synthetic_pose import evaluate_synthetic_pose


def _write_envelope(path: Path, record: dict) -> str:
    payload = canonical_json(record)
    digest = hashlib.sha256(payload).hexdigest()
    path.write_bytes(
        canonical_json(
            {
                "profile": "exulanica.digest-bound-record/v1",
                "record": record,
                "record_sha256": digest,
            }
        )
    )
    return digest


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    digests = [hashlib.sha256(f"source {index}".encode()).hexdigest() for index in range(3)]
    names = [f"view_{index:02d}.jpg" for index in range(3)]
    scene_digest = "1" * 64
    camera_record = {
        "profile": "exulanica.synthetic-camera-manifest/v1",
        "scene_manifest_sha256": scene_digest,
        "views": [
            {
                "image": name,
                "camera_center_metres": [str(index), str(index % 2), "0"],
                "world_from_camera_rotation": [["1", "0", "0"], ["0", "1", "0"], ["0", "0", "1"]],
            }
            for index, name in enumerate(names)
        ],
    }
    camera_path = tmp_path / "camera.json"
    camera_digest = _write_envelope(camera_path, camera_record)
    source_record = {
        "profile": "exulanica.synthetic-source-manifest/v1",
        "corpus_class": "synthetic",
        "scene_manifest_sha256": scene_digest,
        "camera_manifest_sha256": camera_digest,
        "images": [
            {"path": name, "sha256": digest, "bytes": 8}
            for name, digest in zip(names, digests, strict=True)
        ],
    }
    source_path = tmp_path / "source.json"
    _write_envelope(source_path, source_record)
    manifest = {
        "profile": "exulanica.colmap-pose-build/v1",
        "scene_ref": "synthetic-scene",
        "code_revision": "a" * 40,
        "colmap_version": "pycolmap 4.2.0",
        "execution_image": "pose@sha256:" + "b" * 64,
        "frames": [
            {
                "capture_ref": f"capture-{index}",
                "capture_set": "synthetic-scene",
                "filename": f"{index:06d}.jpg",
                "sha256": digest,
            }
            for index, digest in enumerate(digests)
        ],
        "quality_thresholds": {
            "min_registered_fraction": None,
            "max_mean_reprojection_error_px": None,
            "min_camera_translation_units": None,
        },
        "metric_scale": None,
    }
    quality = {
        "registered_images": [f"{index:06d}.jpg" for index in range(3)],
        "registered_fraction": 1.0,
        "mean_reprojection_error_px": 0.25,
        "camera_translation_extent_units": 2.0,
        "accepted": False,
        "reasons": ["thresholds are unmeasured"],
        "cameras": [
            {
                "image_name": f"{index:06d}.jpg",
                "camera_centre_xyz": [index, index % 2, 0],
                "quaternion_wxyz": [1, 0, 0, 0],
            }
            for index in range(3)
        ],
    }
    receipt = {
        "profile": "exulanica.colmap-pose-receipt/v2",
        "manifest": manifest,
        "manifest_digest": hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "quality": quality,
    }
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return source_path, camera_path, receipt_path


def test_exact_pose_receipt_joins_by_digest_and_recovers_zero_error(tmp_path):
    source, cameras, receipt = _fixture(tmp_path)

    result = evaluate_synthetic_pose(
        source_manifest_path=source,
        camera_manifest_path=cameras,
        pose_receipt_path=receipt,
    )

    assert result.record["corpus_class"] == "synthetic"
    assert result.record["production_run"]["registered_count"] == 3
    assert result.record["measured_pose"] == {
        "registered_fraction_millionths": 1_000_000,
        "mean_reprojection_error_micropixels": 250_000,
        "camera_translation_extent_microunits": 2_000_000,
    }
    comparison = result.record["ground_truth_comparison"]
    assert comparison["camera_pair_count"] == 3
    assert comparison["pairwise_relative_rotation_error_microdegrees_max"] == 0
    assert comparison["pairwise_baseline_direction_error_microdegrees_max"] == 0
    assert comparison["camera_centre_residual_micrometres_max"] == 0
    assert comparison["camera_similarity_scale_nanometres_per_unit"] == 1_000_000_000
    envelope = json.loads(result.to_bytes())
    assert envelope["record_sha256"] == hashlib.sha256(
        canonical_json(envelope["record"])
    ).hexdigest()


def test_mismatched_source_and_camera_manifests_are_refused(tmp_path):
    source, cameras, receipt = _fixture(tmp_path)
    envelope = json.loads(source.read_bytes())
    envelope["record"]["camera_manifest_sha256"] = "f" * 64
    _write_envelope(source, envelope["record"])

    with pytest.raises(ValueError, match="does not bind"):
        evaluate_synthetic_pose(
            source_manifest_path=source,
            camera_manifest_path=cameras,
            pose_receipt_path=receipt,
        )


def test_staging_name_is_not_used_as_synthetic_ground_truth_identity(tmp_path):
    source, cameras, receipt = _fixture(tmp_path)
    document = json.loads(receipt.read_bytes())
    document["manifest"]["frames"][0]["sha256"] = "e" * 64
    document["manifest_digest"] = hashlib.sha256(
        json.dumps(document["manifest"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    receipt.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="outside the synthetic manifest"):
        evaluate_synthetic_pose(
            source_manifest_path=source,
            camera_manifest_path=cameras,
            pose_receipt_path=receipt,
        )
