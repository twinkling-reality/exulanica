"""Checkpointed COLMAP sparse reconstruction with geometry-only promotion.

The job consumes an exact, already-authorized source directory and a versioned manifest.  It does
not discover media, infer consent, group scenes by semantic label, or copy source bytes into its
receipt.  Three COLMAP stages are independently checkpointed under a filesystem lock.  A stopped
process resumes from the last durable checkpoint; a completed manifest returns its verified report
without invoking COLMAP again.

COLMAP sparse coordinates are generally scale-ambiguous.  One connected model proves geometric
co-registration, not a metric frame.  ``shared_metric_frame`` therefore remains false unless the
manifest records a reviewed, positive measured scale and the selected model actually contains
registered images from every declared capture set.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import subprocess
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, Protocol

__all__ = [
    "CommandResult",
    "PoseBuildManifest",
    "PoseJobResult",
    "PoseQuality",
    "RecoveredCamera",
    "SourceFrame",
    "run_colmap_pose_job",
]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _hex_digest(value: str, field: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} must be lowercase SHA-256 hex")


@dataclass(frozen=True, slots=True)
class SourceFrame:
    capture_ref: str
    filename: str
    sha256: str
    capture_set: str

    def __post_init__(self) -> None:
        if not self.capture_ref or not self.capture_set:
            raise ValueError("capture_ref and capture_set are required")
        if Path(self.filename).name != self.filename or self.filename in {"", ".", ".."}:
            raise ValueError("source filenames must be non-empty basenames")
        _hex_digest(self.sha256, "source sha256")

    def as_payload(self) -> dict[str, str]:
        return {
            "capture_ref": self.capture_ref,
            "filename": self.filename,
            "sha256": self.sha256,
            "capture_set": self.capture_set,
        }


@dataclass(frozen=True, slots=True)
class PoseBuildManifest:
    scene_ref: str
    code_revision: str
    colmap_version: str
    execution_image: str
    frames: tuple[SourceFrame, ...]
    min_registered_fraction: float | None
    max_mean_reprojection_error_px: float | None
    min_camera_translation_units: float | None
    metric_scale_metres_per_unit: float | None = None
    metric_scale_method: str | None = None

    def __post_init__(self) -> None:
        if not self.scene_ref or not self.colmap_version:
            raise ValueError("scene_ref and colmap_version are required")
        if not re.fullmatch(r"[0-9a-f]{40}", self.code_revision):
            raise ValueError("code_revision must be an exact 40-character Git revision")
        if not re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", self.execution_image):
            raise ValueError("execution_image must be pinned by a sha256 digest")
        if not self.frames:
            raise ValueError("at least one source frame is required")
        if len({item.filename for item in self.frames}) != len(self.frames):
            raise ValueError("source filenames must be unique")
        if len({item.capture_ref for item in self.frames}) != len(self.frames):
            raise ValueError("capture references must be unique")
        if self.min_registered_fraction is not None and not (
            0 < self.min_registered_fraction <= 1 and math.isfinite(self.min_registered_fraction)
        ):
            raise ValueError("min_registered_fraction must be in (0, 1] or unmeasured")
        if self.max_mean_reprojection_error_px is not None and (
            self.max_mean_reprojection_error_px <= 0
            or not math.isfinite(self.max_mean_reprojection_error_px)
        ):
            raise ValueError(
                "max_mean_reprojection_error_px must be finite and positive or unmeasured"
            )
        if self.min_camera_translation_units is not None and (
            self.min_camera_translation_units < 0
            or not math.isfinite(self.min_camera_translation_units)
        ):
            raise ValueError(
                "min_camera_translation_units must be finite and non-negative or unmeasured"
            )
        has_scale = self.metric_scale_metres_per_unit is not None
        if has_scale != (self.metric_scale_method is not None):
            raise ValueError("metric scale value and method must be present together")
        if has_scale and (
            self.metric_scale_metres_per_unit is None
            or self.metric_scale_metres_per_unit <= 0
            or not math.isfinite(self.metric_scale_metres_per_unit)
            or not self.metric_scale_method
        ):
            raise ValueError("metric scale must be a positive measurement with a method")

    def as_payload(self) -> dict[str, object]:
        return {
            "profile": "exulanica.colmap-pose-build/v1",
            "scene_ref": self.scene_ref,
            "code_revision": self.code_revision,
            "colmap_version": self.colmap_version,
            "execution_image": self.execution_image,
            "frames": [item.as_payload() for item in self.frames],
            "quality_thresholds": {
                "min_registered_fraction": self.min_registered_fraction,
                "max_mean_reprojection_error_px": self.max_mean_reprojection_error_px,
                "min_camera_translation_units": self.min_camera_translation_units,
            },
            "metric_scale": (
                None
                if self.metric_scale_metres_per_unit is None
                else {
                    "metres_per_unit": self.metric_scale_metres_per_unit,
                    "method": self.metric_scale_method,
                }
            ),
        }

    @property
    def digest(self) -> str:
        return _sha256_bytes(_canonical(self.as_payload()))


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    duration_ms: float


class CommandExecutor(Protocol):
    def __call__(self, command: tuple[str, ...], cwd: Path) -> CommandResult: ...


@dataclass(frozen=True, slots=True)
class RecoveredCamera:
    """One registered COLMAP image under the convention COLMAP actually writes.

    ``camera_from_world`` means ``x_camera = R * x_world + t``. COLMAP camera coordinates are
    +X right, +Y down and +Z forward. The placement record is responsible for the explicit
    conversion from that frame to OPM's +X right, +Y up and -Z forward frame. Keeping the raw
    measured pose in this receipt makes that conversion reviewable and prevents a renderer
    convention from becoming part of the reconstruction result.
    """

    image_name: str
    quaternion_wxyz: tuple[float, float, float, float]
    translation_xyz: tuple[float, float, float]
    camera_centre_xyz: tuple[float, float, float]
    image_size: tuple[int, int] | None = None
    camera_model: str | None = None
    camera_parameters: tuple[float, ...] = ()
    # Pixel coordinates and triangulated positions, never inferred monocular scale.
    sparse_observations: tuple[tuple[int, float, float, float, float, float, float, int], ...] = ()

    def as_payload(self) -> dict[str, object]:
        return {
            "image_name": self.image_name,
            "convention": {
                "mapping": "camera_from_world",
                "camera_axes": {"right": "+X", "down": "+Y", "forward": "+Z"},
                "quaternion_order": "wxyz",
            },
            "quaternion_wxyz": list(self.quaternion_wxyz),
            "translation_xyz": list(self.translation_xyz),
            "camera_centre_xyz": list(self.camera_centre_xyz),
            "image_size": list(self.image_size) if self.image_size is not None else None,
            "calibration": (
                {"model": self.camera_model, "parameters": list(self.camera_parameters)}
                if self.camera_model is not None
                else None
            ),
            "sparse_observations": [list(item) for item in self.sparse_observations],
        }


@dataclass(frozen=True, slots=True)
class PoseQuality:
    source_count: int
    registered_images: tuple[str, ...]
    cameras: tuple[RecoveredCamera, ...]
    registered_fraction: float
    mean_reprojection_error_px: float | None
    camera_translation_extent_units: float
    connected_model: str | None
    jointly_coregistered: bool
    shared_metric_frame: bool
    metric_scale_metres_per_unit: float | None
    artifact_inventory: tuple[tuple[str, str, int], ...]
    accepted: bool
    fallback_rung: Literal[3]
    reasons: tuple[str, ...]

    def as_payload(self) -> dict[str, object]:
        return {
            "source_count": self.source_count,
            "registered_images": list(self.registered_images),
            "cameras": [camera.as_payload() for camera in self.cameras],
            "registered_fraction": self.registered_fraction,
            "mean_reprojection_error_px": self.mean_reprojection_error_px,
            "camera_translation_extent_units": self.camera_translation_extent_units,
            "connected_model": self.connected_model,
            "jointly_coregistered": self.jointly_coregistered,
            "shared_metric_frame": self.shared_metric_frame,
            "metric_scale_metres_per_unit": self.metric_scale_metres_per_unit,
            "artifact_inventory": [
                {"path": path, "sha256": digest, "byte_length": size}
                for path, digest, size in self.artifact_inventory
            ],
            "accepted": self.accepted,
            "fallback_rung": self.fallback_rung,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class PoseJobResult:
    status: Literal["completed", "failed", "cancelled"]
    manifest_digest: str
    job_directory: Path
    quality: PoseQuality | None
    reused: bool
    failed_stage: str | None = None
    failure_reason: str | None = None


def _default_executor(command: tuple[str, ...], cwd: Path) -> CommandResult:
    started = time.monotonic_ns()
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_ms=(time.monotonic_ns() - started) / 1_000_000,
    )


def _write_atomic(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    with path.open("a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def _verify_sources(source_dir: Path, frames: tuple[SourceFrame, ...]) -> None:
    expected = {item.filename: item for item in frames}
    actual = {item.name for item in source_dir.iterdir() if item.is_file()}
    if actual != set(expected):
        raise ValueError("the staged source directory does not exactly match the build manifest")
    for filename, frame in expected.items():
        path = source_dir / filename
        if path.is_symlink() or _sha256_file(path) != frame.sha256:
            raise ValueError(f"staged source does not match manifest: {filename}")


def _commands(
    job_dir: Path, source_dir: Path, executable: str
) -> tuple[tuple[str, tuple[str, ...], tuple[Path, ...]], ...]:
    database = job_dir / "database.db"
    sparse = job_dir / "sparse"
    return (
        (
            "feature_extractor",
            (
                executable,
                "feature_extractor",
                "--database_path",
                str(database),
                "--image_path",
                str(source_dir),
                "--ImageReader.single_camera",
                "0",
            ),
            (database,),
        ),
        (
            "exhaustive_matcher",
            (executable, "exhaustive_matcher", "--database_path", str(database)),
            (database,),
        ),
        (
            "mapper",
            (
                executable,
                "mapper",
                "--database_path",
                str(database),
                "--image_path",
                str(source_dir),
                "--output_path",
                str(sparse),
            ),
            (sparse,),
        ),
    )


def _quaternion_camera_centre(
    quaternion: tuple[float, float, float, float],
    translation: tuple[float, float, float],
) -> tuple[float, float, float]:
    qw, qx, qy, qz = quaternion
    rotation = (
        (1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)),
        (2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)),
        (2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)),
    )
    return tuple(
        -sum(rotation[row][column] * translation[row] for row in range(3)) for column in range(3)
    )  # type: ignore[return-value]


def _images(path: Path) -> dict[str, RecoveredCamera]:
    registered: dict[str, RecoveredCamera] = {}
    records = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(records):
        line = records[index].strip()
        if not line or line.startswith("#"):
            index += 1
            continue
        parts = line.split()
        if len(parts) < 10:
            raise ValueError(f"malformed COLMAP images.txt record in {path}")
        name = " ".join(parts[9:])
        values = tuple(float(item) for item in parts[1:8])
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"non-finite COLMAP camera pose in {path}")
        quaternion = values[:4]
        translation = values[4:]
        norm = math.sqrt(sum(value * value for value in quaternion))
        if not math.isclose(norm, 1.0, rel_tol=1e-5, abs_tol=1e-7):
            raise ValueError(f"non-unit COLMAP camera quaternion in {path}")
        registered[name] = RecoveredCamera(
            image_name=name,
            quaternion_wxyz=quaternion,
            translation_xyz=translation,
            camera_centre_xyz=_quaternion_camera_centre(quaternion, translation),
        )
        # COLMAP's second line is the POINTS2D list and may be empty. It is still part of this
        # image record and never a second image.
        index += 2
    return registered


def _alignment_observations(
    model: Path, cameras: dict[str, RecoveredCamera]
) -> dict[str, RecoveredCamera]:
    """Retain actual COLMAP tracks for digest-bound point-map alignment.

    The bounded deterministic sample limits receipt size. Point IDs are hash-ordered to avoid
    favouring a contiguous image patch or the mapper's first reconstructed surface. Older
    sparse fixtures without camera calibration remain readable but cannot support placement.
    """
    calibration = model / "cameras.txt"
    if not calibration.is_file():
        return cameras
    sizes: dict[int, tuple[int, int]] = {}
    intrinsics: dict[int, tuple[str, tuple[float, ...]]] = {}
    for line in calibration.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split()
        sizes[int(fields[0])] = (int(fields[2]), int(fields[3]))
        parameters = tuple(float(value) for value in fields[4:])
        if not parameters or not all(math.isfinite(value) for value in parameters):
            raise ValueError("COLMAP camera has invalid calibration parameters")
        intrinsics[int(fields[0])] = (fields[1], parameters)
    points: dict[int, tuple[float, float, float, float, int]] = {}
    for line in (model / "points3D.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 8 or (len(fields) - 8) % 2:
            raise ValueError("malformed COLMAP sparse point track")
        values = tuple(float(fields[index]) for index in (1, 2, 3, 7))
        if not all(math.isfinite(value) for value in values):
            raise ValueError("non-finite COLMAP sparse point")
        points[int(fields[0])] = (*values, (len(fields) - 8) // 2)
    lines = (model / "images.txt").read_text().splitlines()
    index = 0
    while index < len(lines):
        if not lines[index].strip() or lines[index].startswith("#"):
            index += 1
            continue
        fields = lines[index].split()
        name = " ".join(fields[9:])
        observations = lines[index + 1].split() if index + 1 < len(lines) else []
        if len(observations) % 3:
            raise ValueError("malformed COLMAP pixel observation list")
        selected = []
        for start in range(0, len(observations), 3):
            point_id = int(observations[start + 2])
            if point_id < 0:
                continue
            if point_id not in points:
                raise ValueError("COLMAP observation references a missing sparse point")
            x, y = float(observations[start]), float(observations[start + 1])
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("non-finite COLMAP pixel observation")
            selected.append((point_id, x, y, *points[point_id]))
        # MEASURED 2026-09-05 on the first real photograph set: COLMAP track merging can leave one
        # image observing a point at two keypoints. Such a correspondence is ambiguous for scale
        # fitting, and the placement reader refuses duplicate point IDs, so every observation of
        # that point is dropped from this image rather than choosing one keypoint arbitrarily.
        repeated = {
            point_id
            for point_id, count in Counter(item[0] for item in selected).items()
            if count > 1
        }
        selected = [item for item in selected if item[0] not in repeated]
        selected.sort(key=lambda item: hashlib.sha256(str(item[0]).encode()).digest())
        size = sizes.get(int(fields[8]))
        if size is None or min(size) <= 0:
            raise ValueError("COLMAP image references missing camera dimensions")
        cameras[name] = replace(
            cameras[name],
            image_size=size,
            sparse_observations=tuple(selected[:4096]),
            camera_model=intrinsics[int(fields[8])][0],
            camera_parameters=intrinsics[int(fields[8])][1],
        )
        index += 2
    return cameras


def _mean_error(path: Path) -> float | None:
    errors: list[float] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 8:
            raise ValueError(f"malformed COLMAP points3D.txt record in {path}")
        errors.append(float(parts[7]))
    return None if not errors else sum(errors) / len(errors)


def _translation_extent(cameras: Mapping[str, RecoveredCamera]) -> float:
    values = [camera.camera_centre_xyz for camera in cameras.values()]
    return max(
        (
            math.dist(values[left], values[right])
            for left in range(len(values))
            for right in range(left + 1, len(values))
        ),
        default=0.0,
    )


def _inventory(root: Path) -> tuple[tuple[str, str, int], ...]:
    return tuple(
        (str(path.relative_to(root)), _sha256_file(path), path.stat().st_size)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def _quality(manifest: PoseBuildManifest, sparse: Path) -> PoseQuality:
    candidates: list[tuple[Path, dict[str, RecoveredCamera], float | None]] = []
    for model in sorted(path for path in sparse.iterdir() if path.is_dir()):
        images = model / "images.txt"
        points = model / "points3D.txt"
        if images.is_file() and points.is_file():
            candidates.append((model, _images(images), _mean_error(points)))
    if not candidates:
        return PoseQuality(
            source_count=len(manifest.frames),
            registered_images=(),
            cameras=(),
            registered_fraction=0.0,
            mean_reprojection_error_px=None,
            camera_translation_extent_units=0.0,
            connected_model=None,
            jointly_coregistered=False,
            shared_metric_frame=False,
            metric_scale_metres_per_unit=manifest.metric_scale_metres_per_unit,
            artifact_inventory=_inventory(sparse),
            accepted=False,
            fallback_rung=3,
            reasons=("COLMAP produced no readable connected sparse model",),
        )
    model, registered, mean_error = sorted(
        candidates, key=lambda item: (-len(item[1]), str(item[0]))
    )[0]
    registered = _alignment_observations(model, registered)
    frames_by_name = {item.filename: item for item in manifest.frames}
    known = tuple(sorted(name for name in registered if name in frames_by_name))
    cameras = tuple(registered[name] for name in known)
    fraction = len(known) / len(manifest.frames)
    declared_sets = {item.capture_set for item in manifest.frames}
    registered_sets = {frames_by_name[name].capture_set for name in known}
    jointly_coregistered = len(declared_sets) > 1 and registered_sets == declared_sets
    metric = manifest.metric_scale_metres_per_unit is not None
    reasons: list[str] = []
    if manifest.min_registered_fraction is None:
        reasons.append("minimum registered-image fraction is unmeasured")
    elif fraction < manifest.min_registered_fraction:
        reasons.append("registered-image fraction is below the manifest threshold")
    if manifest.max_mean_reprojection_error_px is None:
        reasons.append("maximum mean reprojection error is unmeasured")
    elif mean_error is None:
        reasons.append("the sparse model contains no measured reprojection error")
    elif mean_error > manifest.max_mean_reprojection_error_px:
        reasons.append("mean reprojection error is above the manifest threshold")
    extent = _translation_extent({name: registered[name] for name in known})
    if manifest.min_camera_translation_units is None:
        reasons.append("minimum recovered camera translation is unmeasured")
    elif extent < manifest.min_camera_translation_units:
        reasons.append("recovered camera translation is below the manifest threshold")
    if len(declared_sets) > 1 and not jointly_coregistered:
        reasons.append("declared capture sets do not occur in one connected geometric model")
    if jointly_coregistered and not metric:
        reasons.append("joint reconstruction has no measured metric scale")
    return PoseQuality(
        source_count=len(manifest.frames),
        registered_images=known,
        cameras=cameras,
        registered_fraction=fraction,
        mean_reprojection_error_px=mean_error,
        camera_translation_extent_units=extent,
        connected_model=str(model.relative_to(sparse)),
        jointly_coregistered=jointly_coregistered,
        shared_metric_frame=jointly_coregistered and metric and not reasons,
        metric_scale_metres_per_unit=manifest.metric_scale_metres_per_unit,
        artifact_inventory=_inventory(sparse),
        accepted=not reasons,
        fallback_rung=3,
        reasons=tuple(reasons),
    )


def run_colmap_pose_job(
    manifest: PoseBuildManifest,
    *,
    source_dir: Path,
    jobs_root: Path,
    executable: str = "colmap",
    executor: CommandExecutor = _default_executor,
    cancellation_check: Callable[[], bool] | None = None,
) -> PoseJobResult:
    """Run or resume one exact COLMAP manifest, returning rung 3 on every quality failure.

    ``cancellation_check`` is the ingest-owned deletion boundary. It is asked before reuse and
    on both sides of every opaque executor call, so a tombstone committed while COLMAP owns the
    CPU prevents any later stage or durable acceptance. An in-process COLMAP call cannot be
    interrupted safely halfway through; its caller removes the sensitive scratch directory as
    soon as this returns ``cancelled``.
    """
    _verify_sources(source_dir, manifest.frames)
    jobs_root.mkdir(parents=True, exist_ok=True)
    job_dir = jobs_root / manifest.digest
    job_dir.mkdir(exist_ok=True)
    manifest_path = job_dir / "manifest.json"
    manifest_bytes = _canonical(manifest.as_payload()) + b"\n"
    if manifest_path.exists():
        if manifest_path.read_bytes() != manifest_bytes:
            raise ValueError("the job directory contains a different build manifest")
    else:
        _write_atomic(manifest_path, manifest_bytes)

    with _locked(job_dir / "job.lock"):
        if cancellation_check is not None and cancellation_check():
            return PoseJobResult(
                status="cancelled",
                manifest_digest=manifest.digest,
                job_directory=job_dir,
                quality=None,
                reused=False,
                failure_reason="a source photograph was deleted before pose acceptance",
            )
        receipt_path = job_dir / "receipt.json"
        if receipt_path.is_file():
            receipt = _load_json(receipt_path)
            if receipt.get("profile") != "exulanica.colmap-pose-receipt/v2":
                raise ValueError("the completed pose receipt has an unsupported profile")
            if receipt.get("manifest_digest") != manifest.digest:
                raise ValueError("the completed pose receipt names another manifest")
            if receipt.get("manifest") != manifest.as_payload():
                raise ValueError("the completed pose receipt does not carry its exact manifest")
            quality = _quality(manifest, job_dir / "sparse")
            if _sha256_bytes(_canonical(quality.as_payload())) != receipt.get("quality_digest"):
                raise ValueError("the completed pose artifacts no longer match their receipt")
            return PoseJobResult(
                status="completed",
                manifest_digest=manifest.digest,
                job_directory=job_dir,
                quality=quality,
                reused=True,
            )

        checkpoint_path = job_dir / "checkpoint.json"
        checkpoint = _load_json(checkpoint_path) if checkpoint_path.is_file() else {"stages": {}}
        stages = checkpoint.get("stages")
        if not isinstance(stages, dict):
            raise ValueError("checkpoint stages must be an object")
        (job_dir / "sparse").mkdir(exist_ok=True)
        for stage, command, required in _commands(job_dir, source_dir, executable):
            prior = stages.get(stage)
            if (
                isinstance(prior, dict)
                and prior.get("status") == "completed"
                and all(path.exists() for path in required)
            ):
                continue
            if cancellation_check is not None and cancellation_check():
                return PoseJobResult(
                    status="cancelled",
                    manifest_digest=manifest.digest,
                    job_directory=job_dir,
                    quality=None,
                    reused=False,
                    failed_stage=stage,
                    failure_reason="a source photograph was deleted during pose recovery",
                )
            result = executor(command, job_dir)
            stages[stage] = {
                "status": "completed" if result.returncode == 0 else "failed",
                "command": list(command),
                "returncode": result.returncode,
                "duration_ms": result.duration_ms,
                "stdout_sha256": _sha256_bytes(result.stdout.encode()),
                "stderr_sha256": _sha256_bytes(result.stderr.encode()),
            }
            _write_atomic(checkpoint_path, _canonical(checkpoint) + b"\n")
            if cancellation_check is not None and cancellation_check():
                return PoseJobResult(
                    status="cancelled",
                    manifest_digest=manifest.digest,
                    job_directory=job_dir,
                    quality=None,
                    reused=False,
                    failed_stage=stage,
                    failure_reason="a source photograph was deleted during pose recovery",
                )
            if result.returncode != 0:
                return PoseJobResult(
                    status="failed",
                    manifest_digest=manifest.digest,
                    job_directory=job_dir,
                    quality=None,
                    reused=False,
                    failed_stage=stage,
                    failure_reason=f"COLMAP {stage} exited {result.returncode}; rung 3 fallback",
                )
            if not all(path.exists() for path in required):
                return PoseJobResult(
                    status="failed",
                    manifest_digest=manifest.digest,
                    job_directory=job_dir,
                    quality=None,
                    reused=False,
                    failed_stage=stage,
                    failure_reason=f"COLMAP {stage} omitted its declared output; rung 3 fallback",
                )

        # Mapper writes COLMAP's binary model. Convert each connected model to the documented
        # text interchange before parsing it; the converter is checkpointed independently so a
        # preemption after a long mapper does not repeat mapping.
        sparse = job_dir / "sparse"
        for model in sorted(path for path in sparse.iterdir() if path.is_dir()):
            required = (model / "images.txt", model / "points3D.txt")
            if all(path.is_file() for path in required):
                continue
            stage = f"model_converter:{model.name}"
            prior = stages.get(stage)
            if (
                isinstance(prior, dict)
                and prior.get("status") == "completed"
                and all(path.is_file() for path in required)
            ):
                continue
            command = (
                executable,
                "model_converter",
                "--input_path",
                str(model),
                "--output_path",
                str(model),
                "--output_type",
                "TXT",
            )
            if cancellation_check is not None and cancellation_check():
                return PoseJobResult(
                    status="cancelled",
                    manifest_digest=manifest.digest,
                    job_directory=job_dir,
                    quality=None,
                    reused=False,
                    failed_stage=stage,
                    failure_reason="a source photograph was deleted during pose recovery",
                )
            result = executor(command, job_dir)
            stages[stage] = {
                "status": "completed" if result.returncode == 0 else "failed",
                "command": list(command),
                "returncode": result.returncode,
                "duration_ms": result.duration_ms,
                "stdout_sha256": _sha256_bytes(result.stdout.encode()),
                "stderr_sha256": _sha256_bytes(result.stderr.encode()),
            }
            _write_atomic(checkpoint_path, _canonical(checkpoint) + b"\n")
            if cancellation_check is not None and cancellation_check():
                return PoseJobResult(
                    status="cancelled",
                    manifest_digest=manifest.digest,
                    job_directory=job_dir,
                    quality=None,
                    reused=False,
                    failed_stage=stage,
                    failure_reason="a source photograph was deleted during pose recovery",
                )
            if result.returncode != 0 or not all(path.is_file() for path in required):
                return PoseJobResult(
                    status="failed",
                    manifest_digest=manifest.digest,
                    job_directory=job_dir,
                    quality=None,
                    reused=False,
                    failed_stage=stage,
                    failure_reason="COLMAP model conversion failed; rung 3 fallback",
                )

        quality = _quality(manifest, sparse)
        receipt = {
            "profile": "exulanica.colmap-pose-receipt/v2",
            "manifest_digest": manifest.digest,
            # The durable receipt has to remain explainable after sensitive job scratch is
            # removed. A digest alone proves equality and does not say which photographs,
            # runtime, thresholds or scale method produced it, so the exact manifest travels
            # with the receipt and its digest is checked on every reuse.
            "manifest": manifest.as_payload(),
            "quality_digest": _sha256_bytes(_canonical(quality.as_payload())),
            "quality": quality.as_payload(),
        }
        _write_atomic(receipt_path, _canonical(receipt) + b"\n")
        return PoseJobResult(
            status="completed",
            manifest_digest=manifest.digest,
            job_directory=job_dir,
            quality=quality,
            reused=False,
        )
