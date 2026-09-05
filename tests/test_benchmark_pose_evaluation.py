"""Ground-truth comparison for a production licensed-benchmark pose receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from exulanica.canonical import canonical_json
from exulanica.evaluation.benchmark_pose import evaluate_benchmark_pose


def _write(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def test_benchmark_pose_joins_exact_sources_to_colmap_camera_truth(tmp_path):
    root = tmp_path / "benchmark"
    names = [f"view_{index}.jpg" for index in range(3)]
    centres = ((0, 0, 0), (1, 0, 0), (0, 1, 0))
    image_entries = []
    digests = []
    for index, name in enumerate(names):
        payload = f"benchmark source {index}".encode()
        relative = f"scene/images/{name}"
        digest = _write(root / relative, payload)
        digests.append(digest)
        image_entries.append({"path": relative, "sha256": digest, "bytes": len(payload)})
    camera_lines = ["# COLMAP camera model"]
    for index, (name, centre) in enumerate(zip(names, centres, strict=True), 1):
        translation = tuple(-value for value in centre)
        camera_lines.extend(
            [
                f"{index} 1 0 0 0 {translation[0]} {translation[1]} "
                f"{translation[2]} 0 images/{name}",
                "0 0 -1",
            ]
        )
    camera_payload = ("\n".join(camera_lines) + "\n").encode()
    camera_relative = "scene/calibration/images.txt"
    camera_digest = _write(root / camera_relative, camera_payload)
    manifest_record = {
        "profile": "exulanica.benchmark-source-manifest/v1",
        "corpus_class": "benchmark",
        "image_count": 3,
        "calibration_directory": "scene/calibration",
        "files": [
            {"path": camera_relative, "sha256": camera_digest, "bytes": len(camera_payload)},
            *image_entries,
        ],
    }
    manifest_payload = canonical_json(manifest_record)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(
        canonical_json(
            {
                "profile": "exulanica.digest-bound-record/v1",
                "record": manifest_record,
                "record_sha256": hashlib.sha256(manifest_payload).hexdigest(),
            }
        )
    )
    pose_manifest = {
        "profile": "exulanica.colmap-pose-build/v1",
        "scene_ref": "benchmark-scene",
        "code_revision": "a" * 40,
        "colmap_version": "pycolmap 4.2.0",
        "execution_image": "pose@sha256:" + "b" * 64,
        "frames": [
            {
                "capture_ref": f"capture-{index}",
                "capture_set": "benchmark-scene",
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
                "camera_centre_xyz": list(centre),
                "quaternion_wxyz": [1, 0, 0, 0],
            }
            for index, centre in enumerate(centres)
        ],
    }
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(
        json.dumps(
            {
                "profile": "exulanica.colmap-pose-receipt/v2",
                "manifest": pose_manifest,
                "manifest_digest": hashlib.sha256(
                    json.dumps(
                        pose_manifest, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest(),
                "quality": quality,
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_benchmark_pose(
        benchmark_root=root,
        pose_receipt_path=receipt_path,
        manifest_path=manifest_path,
    )

    assert result.record["corpus_class"] == "benchmark"
    assert result.record["measured_pose"] == {
        "registered_fraction_millionths": 1_000_000,
        "mean_reprojection_error_micropixels": 250_000,
        "camera_translation_extent_microunits": 2_000_000,
    }
    comparison = result.record["ground_truth_comparison"]
    assert comparison["camera_pair_count"] == 3
    assert comparison["pairwise_relative_rotation_error_microdegrees_max"] == 0
    assert comparison["pairwise_baseline_direction_error_microdegrees_max"] == 0
    assert comparison["camera_centre_residual_microunits_max"] == 0
    assert result.record_sha256 == hashlib.sha256(
        canonical_json(result.record)
    ).hexdigest()
