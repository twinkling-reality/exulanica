"""Compare a production pose receipt with an exact licensed benchmark camera model."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.evaluation.benchmark import (
    BENCHMARK_MANIFEST_PATH,
    load_benchmark_manifest,
    verify_benchmark_tree,
)
from exulanica.evaluation.synthetic_pose import (
    _acos_degrees,
    _angle_degrees,
    _chordal_mean_rotation,
    _mean,
    _number,
    _numpy,
    _object,
    _quantize,
    _rotation_from_quaternion,
    _text,
    _vector,
)

__all__ = ["BenchmarkPoseEvaluation", "evaluate_benchmark_pose"]

_PROFILE = "exulanica.benchmark-pose-evaluation/v1"


@dataclass(frozen=True, slots=True)
class BenchmarkPoseEvaluation:
    """One canonical comparison against licensed benchmark camera truth."""

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


def _json_digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _ground_truth_cameras(path: Path) -> dict[str, tuple[Any, Any]]:
    """Read the two-line COLMAP images text format without trusting filenames as paths."""
    np = _numpy()
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.startswith("#")
    ]
    cameras: dict[str, tuple[Any, Any]] = {}
    index = 0
    while index < len(lines):
        header = lines[index]
        index += 1
        if not header:
            continue
        fields = header.split(maxsplit=9)
        if len(fields) != 10:
            raise ValueError("benchmark camera header does not use COLMAP images text format")
        try:
            quaternion = [float(value) for value in fields[1:5]]
            translation = np.asarray([float(value) for value in fields[5:8]], dtype=np.float64)
        except ValueError as error:
            raise ValueError("benchmark camera header contains an invalid number") from error
        rotation = _rotation_from_quaternion(np, quaternion, "benchmark quaternion")
        name = Path(fields[9]).name
        if name in cameras:
            raise ValueError("benchmark camera names must be unique")
        cameras[name] = (-rotation.T @ translation, rotation.T)
        if index >= len(lines):
            raise ValueError("benchmark camera header has no points line")
        index += 1
    if len(cameras) < 3:
        raise ValueError("benchmark pose evaluation needs at least three ground-truth cameras")
    return cameras


def evaluate_benchmark_pose(
    *,
    benchmark_root: Path,
    pose_receipt_path: Path,
    manifest_path: Path = BENCHMARK_MANIFEST_PATH,
) -> BenchmarkPoseEvaluation:
    """Compare a production reconstruction with the manifest-bound benchmark cameras."""
    np = _numpy()
    manifest, manifest_digest = load_benchmark_manifest(manifest_path)
    verify_benchmark_tree(benchmark_root, manifest)
    if manifest.get("corpus_class") != "benchmark":
        raise ValueError("pose evaluation input is not classified as benchmark")

    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        raise ValueError("benchmark manifest has no file inventory")
    image_entries = [
        _object(item, "benchmark image")
        for item in raw_files
        if isinstance(item, dict)
        and str(item.get("path", "")).lower().endswith((".jpg", ".jpeg", ".png"))
    ]
    if len(image_entries) != manifest.get("image_count"):
        raise ValueError("benchmark image count does not match its manifest")
    source_name_by_digest: dict[str, str] = {}
    for item in image_entries:
        digest = _text(item.get("sha256"), "benchmark image digest")
        name = Path(_text(item.get("path"), "benchmark image path")).name
        if digest in source_name_by_digest or name in source_name_by_digest.values():
            raise ValueError("benchmark image names and digests must be unique")
        source_name_by_digest[digest] = name

    calibration_relative = _text(
        manifest.get("calibration_directory"), "benchmark calibration directory"
    )
    calibration_path = benchmark_root / calibration_relative / "images.txt"
    calibration_entry = next(
        (
            item
            for item in raw_files
            if isinstance(item, dict)
            and item.get("path") == f"{calibration_relative}/images.txt"
        ),
        None,
    )
    if calibration_entry is None:
        raise ValueError("benchmark manifest does not bind its camera calibration")
    ground_truth = _ground_truth_cameras(calibration_path)
    if set(ground_truth) != set(source_name_by_digest.values()):
        raise ValueError("benchmark source and camera manifests name different image sets")

    receipt_bytes = pose_receipt_path.read_bytes()
    receipt = _object(json.loads(receipt_bytes), "pose receipt")
    if receipt.get("profile") != "exulanica.colmap-pose-receipt/v2":
        raise ValueError("pose receipt does not use the supported profile")
    pose_manifest = _object(receipt.get("manifest"), "pose receipt manifest")
    if receipt.get("manifest_digest") != _json_digest(pose_manifest):
        raise ValueError("pose receipt manifest digest does not reproduce")
    quality = _object(receipt.get("quality"), "pose receipt quality")
    frames = pose_manifest.get("frames")
    if not isinstance(frames, list) or len(frames) != len(image_entries):
        raise ValueError("pose manifest does not contain the complete benchmark image set")

    truth_by_staged_name: dict[str, tuple[str, Any, Any]] = {}
    for frame_value in frames:
        frame = _object(frame_value, "pose frame")
        staged_name = _text(frame.get("filename"), "pose frame filename")
        digest = _text(frame.get("sha256"), "pose frame source digest")
        source_name = source_name_by_digest.get(digest)
        if source_name is None or staged_name in truth_by_staged_name:
            raise ValueError("pose manifest does not reproduce the exact benchmark set")
        centre, rotation = ground_truth[source_name]
        truth_by_staged_name[staged_name] = (digest, centre, rotation)

    recovered = quality.get("cameras")
    if not isinstance(recovered, list) or len(recovered) < 3:
        raise ValueError("pose receipt has fewer than three recovered cameras")
    registered_names = quality.get("registered_images")
    recovered_names = {
        _object(item, "recovered camera").get("image_name") for item in recovered
    }
    if not isinstance(registered_names, list) or set(registered_names) != recovered_names:
        raise ValueError("pose receipt camera records disagree with registered images")

    source_digests: list[str] = []
    estimated_centres: list[Any] = []
    estimated_rotations: list[Any] = []
    truth_centres: list[Any] = []
    truth_rotations: list[Any] = []
    for camera_value in recovered:
        camera = _object(camera_value, "recovered camera")
        name = _text(camera.get("image_name"), "recovered camera image")
        truth = truth_by_staged_name.get(name)
        if truth is None:
            raise ValueError("pose receipt registered an image outside the benchmark")
        digest, truth_centre, truth_rotation = truth
        source_digests.append(digest)
        estimated_centres.append(
            _vector(np, camera.get("camera_centre_xyz"), 3, "recovered camera centre")
        )
        estimated_rotations.append(
            _rotation_from_quaternion(
                np, camera.get("quaternion_wxyz"), "recovered camera quaternion"
            ).T
        )
        truth_centres.append(truth_centre)
        truth_rotations.append(truth_rotation)

    relative_rotation_errors: list[float] = []
    baseline_direction_errors: list[float] = []
    for left in range(len(recovered)):
        for right in range(left + 1, len(recovered)):
            relative_rotation_errors.append(
                _angle_degrees(
                    np,
                    estimated_rotations[left].T @ estimated_rotations[right],
                    truth_rotations[left].T @ truth_rotations[right],
                )
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
                raise ValueError("benchmark comparison contains coincident camera centres")
            baseline_direction_errors.append(
                _acos_degrees(
                    float(
                        (estimated_baseline / estimated_norm)
                        @ (truth_baseline / truth_norm)
                    )
                )
            )

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
        for estimated, truth in zip(
            estimated_rotations, truth_rotations, strict=True
        )
    ]
    estimated_array = np.stack(estimated_centres)
    truth_array = np.stack(truth_centres)
    rotated_estimate = (alignment_rotation @ estimated_array.T).T
    estimated_zero = rotated_estimate - rotated_estimate.mean(axis=0)
    truth_zero = truth_array - truth_array.mean(axis=0)
    denominator = float((estimated_zero**2).sum())
    if denominator <= 0:
        raise ValueError("benchmark comparison has no recoverable camera translation")
    scale = float((estimated_zero * truth_zero).sum() / denominator)
    if scale <= 0:
        raise ValueError("benchmark similarity alignment produced a non-positive scale")
    translation = truth_array.mean(axis=0) - scale * rotated_estimate.mean(axis=0)
    residuals = np.linalg.norm(scale * rotated_estimate + translation - truth_array, axis=1)
    truth_extent = max(
        float(np.linalg.norm(left - right))
        for left in truth_centres
        for right in truth_centres
    )

    source_count = len(frames)
    registered_count = len(recovered)
    record: dict[str, Any] = {
        "profile": _PROFILE,
        "corpus_class": "benchmark",
        "notice": (
            "Licensed benchmark engineering evidence only. This is not personal-media "
            "acceptance."
        ),
        "inputs": {
            "source_manifest_sha256": manifest_digest,
            "camera_calibration_sha256": _text(
                calibration_entry.get("sha256"), "camera calibration digest"
            ),
            "pose_receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "pose_manifest_sha256": receipt.get("manifest_digest"),
        },
        "production_run": {
            "scene_ref": pose_manifest.get("scene_ref"),
            "code_revision": pose_manifest.get("code_revision"),
            "colmap_version": pose_manifest.get("colmap_version"),
            "execution_image": pose_manifest.get("execution_image"),
            "source_count": source_count,
            "registered_count": registered_count,
            "excluded_count": source_count - registered_count,
            "registered_source_sha256": source_digests,
            "pose_accepted": quality.get("accepted"),
            "pose_reasons": quality.get("reasons"),
        },
        "measured_pose": {
            "registered_fraction_millionths": _quantize(
                _number(quality.get("registered_fraction"), "registered fraction"),
                1_000_000,
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
            "camera_similarity_scale_nanounits_per_unit": _quantize(
                scale, 1_000_000_000
            ),
            "camera_centre_residual_microunits_rms": _quantize(
                float(np.sqrt((residuals**2).mean())), 1_000_000
            ),
            "camera_centre_residual_microunits_max": _quantize(
                float(residuals.max()), 1_000_000
            ),
            "ground_truth_camera_extent_microunits": _quantize(
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
            "Global rotation, translation, and scale are removed before centre residuals.",
            "One indoor benchmark scene cannot establish broad photograph acceptance.",
            "No metric scale, coverage, corridor, splat, or personal-media claim follows.",
        ],
    }
    payload = canonical_json(record)
    return BenchmarkPoseEvaluation(record, hashlib.sha256(payload).hexdigest())
