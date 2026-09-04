"""Digest-bound pose evaluation against the deterministic synthetic camera manifest.

Production staging deliberately renames source files. The evaluator therefore joins a recovered
camera to synthetic ground truth through the exact source digest in the pose manifest, never by
assuming that a staging filename still resembles the generator filename.

The output is a canonical record with integer-quantized measurements. It is evidence that the
pose path handles one deterministic synthetic scene. It is not evidence about photographs.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from decimal import ROUND_HALF_DOWN, Decimal
from pathlib import Path
from typing import Any

from exulanica.canonical import canonical_json

__all__ = ["SyntheticPoseEvaluation", "evaluate_synthetic_pose"]

_PROFILE = "exulanica.synthetic-pose-evaluation/v1"


@dataclass(frozen=True, slots=True)
class SyntheticPoseEvaluation:
    """One reproducible, canonical synthetic pose comparison."""

    record: dict[str, Any]
    record_sha256: str

    def envelope(self) -> dict[str, Any]:
        return {
            "profile": "exulanica.digest-bound-record/v1",
            "record": self.record,
            "record_sha256": self.record_sha256,
        }

    def to_bytes(self) -> bytes:
        return canonical_json(self.envelope())


def _numpy() -> Any:
    try:
        import numpy
    except ImportError as error:  # pragma: no cover - the reconstruction extra owns numpy
        raise RuntimeError("synthetic pose evaluation needs numpy") from error
    return numpy


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object")
    return value


def _list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a JSON array")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be non-empty text")
    return value


def _json_digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _digest_bound(path: Path, field: str) -> tuple[dict[str, Any], str]:
    envelope = _object(json.loads(path.read_bytes()), field)
    if envelope.get("profile") != "exulanica.digest-bound-record/v1":
        raise ValueError(f"{field} does not use the digest-bound record profile")
    record = _object(envelope.get("record"), f"{field}.record")
    digest = hashlib.sha256(canonical_json(record)).hexdigest()
    if envelope.get("record_sha256") != digest:
        raise ValueError(f"{field} record digest does not reproduce")
    return record, digest


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _vector(np: Any, value: object, size: int, field: str) -> Any:
    items = _list(value, field)
    if len(items) != size:
        raise ValueError(f"{field} must contain {size} values")
    try:
        result = np.asarray([float(item) for item in items], dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} contains an invalid number") from error
    if not np.isfinite(result).all():
        raise ValueError(f"{field} must contain finite values")
    return result


def _matrix(np: Any, value: object, field: str) -> Any:
    rows = _list(value, field)
    if len(rows) != 3 or any(not isinstance(row, list) or len(row) != 3 for row in rows):
        raise ValueError(f"{field} must be a 3 by 3 matrix")
    try:
        result = np.asarray([[float(item) for item in row] for row in rows], dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} contains an invalid number") from error
    if not np.isfinite(result).all():
        raise ValueError(f"{field} must contain finite values")
    return result


def _rotation_from_quaternion(np: Any, value: object, field: str) -> Any:
    quaternion = _vector(np, value, 4, field)
    norm = float(np.linalg.norm(quaternion))
    if norm <= 0:
        raise ValueError(f"{field} must not be zero")
    w, x, y, z = quaternion / norm
    return np.asarray(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def _acos_degrees(cosine: float) -> float:
    bounded = min(1.0, max(-1.0, cosine))
    if math.isclose(bounded, 1.0, abs_tol=1e-15):
        return 0.0
    if math.isclose(bounded, -1.0, abs_tol=1e-15):
        return 180.0
    return math.degrees(math.acos(bounded))


def _angle_degrees(np: Any, left: Any, right: Any) -> float:
    return _acos_degrees(float((np.trace(left.T @ right) - 1) / 2))


def _chordal_mean_rotation(np: Any, rotations: list[Any]) -> Any:
    total = np.sum(np.stack(rotations), axis=0)
    left, _singular, right_t = np.linalg.svd(total)
    result = left @ right_t
    if np.linalg.det(result) < 0:
        left[:, -1] *= -1
        result = left @ right_t
    return result


def _quantize(value: float, factor: int) -> int:
    if not math.isfinite(value):
        raise ValueError("a synthetic pose measurement was not finite")
    return int((Decimal(str(value)) * factor).quantize(Decimal("1"), rounding=ROUND_HALF_DOWN))


def _mean(values: list[float]) -> float:
    if not values:
        raise ValueError("a synthetic pose comparison produced no pairwise measurements")
    return sum(values) / len(values)


def evaluate_synthetic_pose(
    *,
    source_manifest_path: Path,
    camera_manifest_path: Path,
    pose_receipt_path: Path,
) -> SyntheticPoseEvaluation:
    """Compare a production pose receipt to its exact synthetic source camera truth."""
    np = _numpy()
    source, source_digest = _digest_bound(source_manifest_path, "source manifest")
    cameras, camera_digest = _digest_bound(camera_manifest_path, "camera manifest")
    if source.get("profile") != "exulanica.synthetic-source-manifest/v1":
        raise ValueError("source manifest is not the supported synthetic profile")
    if source.get("corpus_class") != "synthetic":
        raise ValueError("source manifest is not structurally classified as synthetic")
    if cameras.get("profile") != "exulanica.synthetic-camera-manifest/v1":
        raise ValueError("camera manifest is not the supported synthetic profile")
    if source.get("camera_manifest_sha256") != camera_digest:
        raise ValueError("source manifest does not bind the supplied camera manifest")
    if source.get("scene_manifest_sha256") != cameras.get("scene_manifest_sha256"):
        raise ValueError("source and camera manifests bind different synthetic scenes")

    source_images = _list(source.get("images"), "source manifest images")
    source_name_by_digest: dict[str, str] = {}
    for index, item_value in enumerate(source_images):
        item = _object(item_value, f"source image {index}")
        name = _text(item.get("path"), f"source image {index} path")
        digest = _text(item.get("sha256"), f"source image {index} digest")
        if digest in source_name_by_digest:
            raise ValueError("synthetic source image digests must be unique")
        source_name_by_digest[digest] = name

    ground_truth_by_name: dict[str, tuple[Any, Any]] = {}
    for index, item_value in enumerate(_list(cameras.get("views"), "camera views")):
        item = _object(item_value, f"camera view {index}")
        name = _text(item.get("image"), f"camera view {index} image")
        if name in ground_truth_by_name:
            raise ValueError("synthetic camera image names must be unique")
        ground_truth_by_name[name] = (
            _vector(np, item.get("camera_center_metres"), 3, f"camera view {index} centre"),
            _matrix(np, item.get("world_from_camera_rotation"), f"camera view {index} rotation"),
        )
    if set(source_name_by_digest.values()) != set(ground_truth_by_name):
        raise ValueError("source and camera manifests do not name the same exact views")

    receipt_bytes = pose_receipt_path.read_bytes()
    receipt = _object(json.loads(receipt_bytes), "pose receipt")
    if receipt.get("profile") != "exulanica.colmap-pose-receipt/v2":
        raise ValueError("pose receipt does not use the supported profile")
    manifest = _object(receipt.get("manifest"), "pose receipt manifest")
    if receipt.get("manifest_digest") != _json_digest(manifest):
        raise ValueError("pose receipt manifest digest does not reproduce")
    quality = _object(receipt.get("quality"), "pose receipt quality")
    frames = _list(manifest.get("frames"), "pose manifest frames")
    if len(frames) != len(source_images):
        raise ValueError("pose manifest does not contain the complete synthetic source set")
    truth_by_staged_name: dict[str, tuple[str, Any, Any]] = {}
    for index, frame_value in enumerate(frames):
        frame = _object(frame_value, f"pose frame {index}")
        staged_name = _text(frame.get("filename"), f"pose frame {index} filename")
        source_digest_value = _text(frame.get("sha256"), f"pose frame {index} source digest")
        source_name = source_name_by_digest.get(source_digest_value)
        if source_name is None:
            raise ValueError("pose manifest contains a source outside the synthetic manifest")
        if staged_name in truth_by_staged_name:
            raise ValueError("pose staging filenames must be unique")
        centre, rotation = ground_truth_by_name[source_name]
        truth_by_staged_name[staged_name] = (source_digest_value, centre, rotation)
    if {item[0] for item in truth_by_staged_name.values()} != set(source_name_by_digest):
        raise ValueError("pose manifest source digests do not reproduce the exact synthetic set")

    quality_cameras = _list(quality.get("cameras"), "pose quality cameras")
    registered_names = _list(quality.get("registered_images"), "registered images")
    if set(registered_names) != {
        _object(item, "recovered camera").get("image_name") for item in quality_cameras
    }:
        raise ValueError("pose quality camera records do not match registered image names")
    if len(quality_cameras) < 3:
        raise ValueError("synthetic pose evaluation needs at least three registered cameras")

    names: list[str] = []
    source_digests: list[str] = []
    estimated_centres: list[Any] = []
    estimated_rotations: list[Any] = []
    truth_centres: list[Any] = []
    truth_rotations: list[Any] = []
    for index, camera_value in enumerate(quality_cameras):
        camera = _object(camera_value, f"recovered camera {index}")
        name = _text(camera.get("image_name"), f"recovered camera {index} image")
        truth = truth_by_staged_name.get(name)
        if truth is None:
            raise ValueError("pose receipt registered an image outside the exact source set")
        source_digest_value, truth_centre, truth_rotation = truth
        names.append(name)
        source_digests.append(source_digest_value)
        estimated_centres.append(
            _vector(np, camera.get("camera_centre_xyz"), 3, f"recovered camera {index} centre")
        )
        camera_from_world = _rotation_from_quaternion(
            np,
            camera.get("quaternion_wxyz"),
            f"recovered camera {index} quaternion",
        )
        estimated_rotations.append(camera_from_world.T)
        truth_centres.append(truth_centre)
        truth_rotations.append(truth_rotation)

    relative_rotation_errors: list[float] = []
    baseline_direction_errors: list[float] = []
    for left in range(len(names)):
        for right in range(left + 1, len(names)):
            estimated_relative = estimated_rotations[left].T @ estimated_rotations[right]
            truth_relative = truth_rotations[left].T @ truth_rotations[right]
            relative_rotation_errors.append(
                _angle_degrees(np, estimated_relative, truth_relative)
            )
            estimated_baseline = estimated_rotations[left].T @ (
                estimated_centres[right] - estimated_centres[left]
            )
            truth_baseline = truth_rotations[left].T @ (
                truth_centres[right] - truth_centres[left]
            )
            estimated_norm = float(np.linalg.norm(estimated_baseline))
            truth_norm = float(np.linalg.norm(truth_baseline))
            if estimated_norm <= 0 or truth_norm <= 0:
                raise ValueError("synthetic pose comparison contains coincident camera centres")
            cosine = float(
                (estimated_baseline / estimated_norm) @ (truth_baseline / truth_norm)
            )
            baseline_direction_errors.append(_acos_degrees(cosine))

    alignment_rotation = _chordal_mean_rotation(
        np,
        [
            truth @ estimated.T
            for truth, estimated in zip(
                truth_rotations, estimated_rotations, strict=True
            )
        ],
    )
    aligned_rotation_errors = [
        _angle_degrees(np, alignment_rotation @ estimated, truth)
        for estimated, truth in zip(estimated_rotations, truth_rotations, strict=True)
    ]
    estimated_array = np.stack(estimated_centres)
    truth_array = np.stack(truth_centres)
    rotated_estimate = (alignment_rotation @ estimated_array.T).T
    estimated_mean = rotated_estimate.mean(axis=0)
    truth_mean = truth_array.mean(axis=0)
    estimated_zero = rotated_estimate - estimated_mean
    truth_zero = truth_array - truth_mean
    denominator = float((estimated_zero**2).sum())
    if denominator <= 0:
        raise ValueError("synthetic pose comparison has no recoverable camera translation")
    scale = float((estimated_zero * truth_zero).sum() / denominator)
    if scale <= 0:
        raise ValueError("synthetic pose similarity alignment produced a non-positive scale")
    translation = truth_mean - scale * estimated_mean
    residuals = np.linalg.norm(scale * rotated_estimate + translation - truth_array, axis=1)
    truth_extent = max(
        float(np.linalg.norm(left - right)) for left in truth_centres for right in truth_centres
    )

    source_count = len(frames)
    registered_count = len(names)
    record: dict[str, Any] = {
        "profile": _PROFILE,
        "corpus_class": "synthetic",
        "notice": (
            "Synthetic plumbing and coordinate evidence only. This is not real-world "
            "reconstruction quality evidence or personal-media acceptance."
        ),
        "inputs": {
            "source_manifest_sha256": source_digest,
            "camera_manifest_sha256": camera_digest,
            "synthetic_scene_manifest_sha256": source.get("scene_manifest_sha256"),
            "pose_receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "pose_manifest_sha256": receipt.get("manifest_digest"),
        },
        "production_run": {
            "scene_ref": manifest.get("scene_ref"),
            "code_revision": manifest.get("code_revision"),
            "colmap_version": manifest.get("colmap_version"),
            "execution_image": manifest.get("execution_image"),
            "source_count": source_count,
            "registered_count": registered_count,
            "excluded_count": source_count - registered_count,
            "registered_source_sha256": source_digests,
            "pose_accepted": quality.get("accepted"),
            "pose_reasons": quality.get("reasons"),
        },
        "measured_pose": {
            "registered_fraction_millionths": _quantize(
                _number(quality.get("registered_fraction"), "registered fraction"), 1_000_000
            ),
            "mean_reprojection_error_micropixels": _quantize(
                _number(quality.get("mean_reprojection_error_px"), "mean reprojection error"),
                1_000_000,
            ),
            "camera_translation_extent_microunits": _quantize(
                _number(quality.get("camera_translation_extent_units"), "camera extent"),
                1_000_000,
            ),
        },
        "ground_truth_comparison": {
            "registered_camera_count": registered_count,
            "camera_pair_count": len(relative_rotation_errors),
            "pairwise_relative_rotation_error_microdegrees_mean": _quantize(
                _mean(relative_rotation_errors), 1_000_000
            ),
            "pairwise_relative_rotation_error_microdegrees_max": _quantize(
                max(relative_rotation_errors), 1_000_000
            ),
            "pairwise_baseline_direction_error_microdegrees_mean": _quantize(
                _mean(baseline_direction_errors), 1_000_000
            ),
            "pairwise_baseline_direction_error_microdegrees_max": _quantize(
                max(baseline_direction_errors), 1_000_000
            ),
            "rotation_error_after_alignment_microdegrees_mean": _quantize(
                _mean(aligned_rotation_errors), 1_000_000
            ),
            "rotation_error_after_alignment_microdegrees_max": _quantize(
                max(aligned_rotation_errors), 1_000_000
            ),
            "camera_similarity_scale_nanometres_per_unit": _quantize(scale, 1_000_000_000),
            "camera_centre_residual_micrometres_rms": _quantize(
                float(np.sqrt((residuals**2).mean())), 1_000_000
            ),
            "camera_centre_residual_micrometres_max": _quantize(
                float(residuals.max()), 1_000_000
            ),
            "ground_truth_camera_extent_micrometres": _quantize(
                truth_extent, 1_000_000
            ),
        },
        "measurement_convention": {
            "rotation": "geodesic angle on SO(3)",
            "baseline": "pairwise direction in each left camera frame",
            "alignment": (
                "chordal-mean global rotation followed by least-squares positive scale and "
                "translation on camera centres"
            ),
            "quantization": "nearest integer with decimal ties toward zero",
        },
        "limitations": [
            "Global rotation, translation, and scale are removed before camera-centre residuals.",
            "The deterministic synthetic render is easier than real photography.",
            "No metric scale, coverage, corridor, splat, or personal-media claim follows.",
        ],
    }
    payload = canonical_json(record)
    return SyntheticPoseEvaluation(record, hashlib.sha256(payload).hexdigest())
