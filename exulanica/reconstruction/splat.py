"""Preemptible per-scene gsplat job controller and appearance quality gate.

The controller is intentionally narrower than a trainer.  It invokes a digest-pinned execution
image's reviewed ``exulanica-gsplat-scene-v1`` entrypoint, validates the actual runtime and quality
receipts that entrypoint writes, resumes only through its declared checkpoint protocol, and runs
the selected PlayCanvas compressor.  This repository does not silently substitute upstream
``simple_trainer.py``: its ``--ckpt`` mode skips training and evaluates only, so calling that
"resume" would be false.

Only ``nerfstudio-project/gsplat`` under Apache-2.0 is accepted.  Common INRIA package names are a
hard manifest refusal rather than a warning.  Training state stays outside the delivery inventory;
only the accepted SOG and versioned receipts are publication outputs. Appearance acceptance
never independently promotes a recorded scene rung; scale and coverage gates remain separate.
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
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, Protocol

from exulanica.reconstruction.gsplat_protocol import TRAINING_PROTOCOL
from exulanica.reconstruction.pose import CommandResult

__all__ = [
    "SplatBuildManifest",
    "SplatJobResult",
    "SplatQuality",
    "run_gsplat_job",
]

_RUNNER_PROFILE = "exulanica.gsplat-scene-runner/v1"
_QUALITY_PROFILE = "exulanica.gsplat-quality/v1"
_BLOCKED_DEPENDENCIES = frozenset(
    {
        "diff-gaussian-rasterization",
        "gaussian-splatting",
        "graphdeco-inria",
    }
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha(value: str, field: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{field} must be lowercase SHA-256 hex")


def _positive(value: float, field: str, *, allow_zero: bool = False) -> None:
    if not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{field} must be finite and {qualifier}")


@dataclass(frozen=True, slots=True)
class SplatBuildManifest:
    scene_ref: str
    code_revision: str
    pose_manifest_digest: str
    source_sha256: tuple[str, ...]
    gsplat_revision: str
    execution_image: str
    dependency_inventory: tuple[str, ...]
    requested_gpu: str
    max_iterations: int
    checkpoint_every: int
    gaussian_cap: int
    heldout_every: int
    heldout_source_sha256: tuple[str, ...]
    usd_per_gpu_hour: float
    min_psnr: float
    min_ssim: float
    max_lpips: float
    max_floaters_fraction: float
    min_coverage_fraction: float
    max_browser_bytes: int

    def __post_init__(self) -> None:
        if not self.scene_ref or not self.requested_gpu:
            raise ValueError("scene_ref and requested_gpu are required")
        if not re.fullmatch(r"[0-9a-f]{40}", self.code_revision):
            raise ValueError("code_revision must be an exact 40-character Git revision")
        _sha(self.pose_manifest_digest, "pose_manifest_digest")
        if not self.source_sha256 or len(set(self.source_sha256)) != len(self.source_sha256):
            raise ValueError("source_sha256 must be a non-empty unique source set")
        for digest in self.source_sha256:
            _sha(digest, "source digest")
        if not re.fullmatch(r"[0-9a-f]{40}", self.gsplat_revision):
            raise ValueError("gsplat_revision must be an exact Git revision")
        if not re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", self.execution_image):
            raise ValueError("execution_image must be pinned by a sha256 digest")
        normalized = {item.strip().lower().replace("_", "-") for item in self.dependency_inventory}
        blocked = sorted(normalized & _BLOCKED_DEPENDENCIES)
        if blocked:
            raise ValueError(f"blocked INRIA rasterizer dependency: {', '.join(blocked)}")
        if "gsplat" not in normalized:
            raise ValueError("the reviewed Apache-2.0 gsplat dependency is required")
        for field in ("max_iterations", "checkpoint_every", "gaussian_cap", "heldout_every"):
            if getattr(self, field) <= 0:
                raise ValueError(f"{field} must be positive")
        if self.checkpoint_every > self.max_iterations:
            raise ValueError("checkpoint_every cannot exceed max_iterations")
        if (
            not self.heldout_source_sha256
            or len(set(self.heldout_source_sha256)) != len(self.heldout_source_sha256)
            or not set(self.heldout_source_sha256) < set(self.source_sha256)
        ):
            raise ValueError(
                "heldout_source_sha256 must be a unique proper subset of source hashes"
            )
        _positive(self.usd_per_gpu_hour, "usd_per_gpu_hour", allow_zero=True)
        _positive(self.min_psnr, "min_psnr", allow_zero=True)
        if not 0 <= self.min_ssim <= 1:
            raise ValueError("min_ssim must be between zero and one")
        if not 0 <= self.max_lpips <= 1:
            raise ValueError("max_lpips must be between zero and one")
        if not 0 <= self.max_floaters_fraction <= 1:
            raise ValueError("max_floaters_fraction must be between zero and one")
        if not 0 <= self.min_coverage_fraction <= 1:
            raise ValueError("min_coverage_fraction must be between zero and one")
        if self.max_browser_bytes <= 0:
            raise ValueError("max_browser_bytes must be positive")

    def as_payload(self) -> dict[str, object]:
        return {
            "profile": "exulanica.gsplat-build/v1",
            "scene_ref": self.scene_ref,
            "code_revision": self.code_revision,
            "pose_manifest_digest": self.pose_manifest_digest,
            "source_sha256": list(self.source_sha256),
            "implementation": {
                "repository": "nerfstudio-project/gsplat",
                "revision": self.gsplat_revision,
                "license": "Apache-2.0",
                "strategy": "mcmc",
                "runner_profile": _RUNNER_PROFILE,
            },
            "training_protocol": TRAINING_PROTOCOL,
            "execution_image": self.execution_image,
            "dependency_inventory": list(self.dependency_inventory),
            "requested_gpu": self.requested_gpu,
            "parameters": {
                "max_iterations": self.max_iterations,
                "checkpoint_every": self.checkpoint_every,
                "gaussian_cap": self.gaussian_cap,
                "heldout_every": self.heldout_every,
                "heldout_source_sha256": list(self.heldout_source_sha256),
            },
            "cost_rate": {"usd_per_gpu_hour": self.usd_per_gpu_hour},
            "quality_thresholds": {
                "min_psnr": self.min_psnr,
                "min_ssim": self.min_ssim,
                "max_lpips": self.max_lpips,
                "max_floaters_fraction": self.max_floaters_fraction,
                "min_coverage_fraction": self.min_coverage_fraction,
                "max_browser_bytes": self.max_browser_bytes,
            },
        }

    @property
    def digest(self) -> str:
        return _digest_bytes(_canonical(self.as_payload()))


@dataclass(frozen=True, slots=True)
class SplatQuality:
    heldout_views: int
    psnr: float
    ssim: float
    lpips: float
    floaters_fraction: float
    coverage_fraction: float
    iterations_completed: int
    duration_seconds: float
    usd_cost: float
    gpu: str
    cuda_version: str
    driver_version: str
    peak_vram_bytes: int
    browser_bytes: int | None
    delivery_sha256: str | None
    accepted: bool
    fallback_rung: Literal[3]
    reasons: tuple[str, ...]

    def as_payload(self) -> dict[str, object]:
        return {
            "profile": _QUALITY_PROFILE,
            "acceptance_scope": "image-quality-and-byte-budget-only; recorded-rung-is-independent",
            "heldout_views": self.heldout_views,
            "psnr": self.psnr,
            "ssim": self.ssim,
            "lpips": self.lpips,
            "floaters_fraction": self.floaters_fraction,
            "coverage_fraction": self.coverage_fraction,
            "iterations_completed": self.iterations_completed,
            "duration_seconds": self.duration_seconds,
            "usd_cost": self.usd_cost,
            "gpu": self.gpu,
            "cuda_version": self.cuda_version,
            "driver_version": self.driver_version,
            "peak_vram_bytes": self.peak_vram_bytes,
            "browser_bytes": self.browser_bytes,
            "delivery_sha256": self.delivery_sha256,
            "accepted": self.accepted,
            "fallback_rung": self.fallback_rung,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class SplatJobResult:
    status: Literal["completed", "checkpointed", "failed"]
    manifest_digest: str
    job_directory: Path
    quality: SplatQuality | None
    reused: bool
    reason: str | None = None


class CommandExecutor(Protocol):
    def __call__(self, command: tuple[str, ...], cwd: Path) -> CommandResult: ...


def _execute(command: tuple[str, ...], cwd: Path) -> CommandResult:
    started = time.monotonic_ns()
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    return CommandResult(
        completed.returncode,
        completed.stdout,
        completed.stderr,
        (time.monotonic_ns() - started) / 1_000_000,
    )


def _write_atomic(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = _canonical(value) + b"\n"
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


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite measured number")
    return float(value)


def _runtime_and_metrics(
    manifest: SplatBuildManifest, output: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    runtime = _object(output / "runtime.json")
    metrics = _object(output / "metrics.json")
    if runtime.get("profile") != _RUNNER_PROFILE or metrics.get("profile") != _QUALITY_PROFILE:
        raise ValueError("the gsplat runner returned an unsupported receipt profile")
    if (
        runtime.get("backend") != "gsplat"
        or runtime.get("gsplat_revision") != manifest.gsplat_revision
    ):
        raise ValueError("the runner did not use the manifest's reviewed gsplat revision")
    for field in ("gpu", "cuda_version", "driver_version"):
        if not isinstance(runtime.get(field), str) or not runtime[field]:
            raise ValueError(f"runtime.{field} must record the actual execution environment")
    if (
        runtime.get("manifest_digest") != manifest.digest
        or metrics.get("manifest_digest") != manifest.digest
    ):
        raise ValueError("runner receipts do not bind the exact build manifest")
    if runtime.get("duration_accounting_complete") is not True:
        raise ValueError("runner duration is incomplete after an unclean interruption")
    if runtime.get("training_protocol") != TRAINING_PROTOCOL:
        raise ValueError("runner training and metric protocol differs from the manifest")
    if runtime.get("ply_sha256") != _digest_file(output / "accepted.ply"):
        raise ValueError("runner PLY bytes do not match their measured receipt")
    imports = runtime.get("loaded_packages")
    if not isinstance(imports, list):
        raise ValueError("runtime.loaded_packages must be an exact array")
    normalized = {str(item).lower().replace("_", "-") for item in imports}
    if "gsplat" not in normalized:
        raise ValueError("runtime package inventory omits gsplat")
    if normalized & _BLOCKED_DEPENDENCIES:
        raise ValueError("the runtime loaded a blocked INRIA rasterizer")
    return runtime, metrics


def _verify_pose_receipt(manifest: SplatBuildManifest, path: Path, dataset_dir: Path) -> str:
    receipt = _object(path)
    if receipt.get("manifest_digest") != manifest.pose_manifest_digest:
        raise ValueError("the pose receipt does not match the splat manifest")
    pose_manifest = receipt.get("manifest")
    if (
        receipt.get("profile") != "exulanica.colmap-pose-receipt/v2"
        or not isinstance(pose_manifest, dict)
        or _digest_bytes(_canonical(pose_manifest)) != manifest.pose_manifest_digest
    ):
        raise ValueError("the carried pose manifest does not match its digest")
    quality = receipt.get("quality")
    if not isinstance(quality, dict):
        raise ValueError("the pose receipt has no quality payload")
    if receipt.get("quality_digest") != _digest_bytes(_canonical(quality)):
        raise ValueError("the pose quality payload does not match its digest")
    if quality.get("accepted") is not True:
        raise ValueError("the pose quality gate did not accept this scene")
    scale = quality.get("metric_scale_metres_per_unit")
    if scale is not None and (
        isinstance(scale, bool)
        or not isinstance(scale, int | float)
        or not math.isfinite(scale)
        or scale <= 0
    ):
        raise ValueError("rung 1 requires a measured metric pose scale")
    if (
        scale is not None
        and quality.get("jointly_coregistered") is True
        and quality.get("shared_metric_frame") is not True
    ):
        raise ValueError("joint capture sets have not earned a shared metric frame")

    frames = pose_manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("the carried pose manifest has no exact source frame inventory")
    declared = {item.get("filename"): item.get("sha256") for item in frames}
    actual = {
        path.relative_to(dataset_dir / "images").as_posix(): _digest_file(path)
        for path in (dataset_dir / "images").rglob("*")
        if path.is_file()
    }
    if len(declared) != len(frames) or declared != actual:
        raise ValueError(
            "dataset filenames and source hashes differ from the accepted pose manifest"
        )
    selected = quality.get("connected_model")
    if not isinstance(selected, str) or not selected or Path(selected).name != selected:
        raise ValueError("pose receipt does not select one valid connected sparse model")
    inventory = quality.get("artifact_inventory")
    if not isinstance(inventory, list) or not inventory:
        raise ValueError("pose receipt has no measured sparse artifact inventory")
    expected = {
        item.get("path"): (item.get("sha256"), item.get("byte_length")) for item in inventory
    }
    sparse = dataset_dir / "sparse"
    if any(path.is_symlink() for path in sparse.rglob("*")):
        raise ValueError("pose sparse artifacts may not be symlinks")
    observed = {
        path.relative_to(sparse).as_posix(): (_digest_file(path), path.stat().st_size)
        for path in sparse.rglob("*")
        if path.is_file()
    }
    if len(expected) != len(inventory) or observed != expected or not (sparse / selected).is_dir():
        raise ValueError(
            "dataset sparse model bytes differ from the accepted pose artifact inventory"
        )
    return selected


def _verify_dataset_sources(manifest: SplatBuildManifest, dataset_dir: Path) -> None:
    images = dataset_dir / "images"
    if not images.is_dir() or not (dataset_dir / "sparse").is_dir():
        raise ValueError("the gsplat dataset must contain COLMAP images and sparse directories")
    paths = sorted(path for path in images.rglob("*") if path.is_file())
    if any(path.is_symlink() for path in paths):
        raise ValueError("the gsplat source image set may not contain symlinks")
    actual = tuple(sorted(_digest_file(path) for path in paths))
    if actual != tuple(sorted(manifest.source_sha256)):
        raise ValueError("the gsplat dataset source bytes do not match the manifest")


def _quality(
    manifest: SplatBuildManifest,
    output: Path,
    *,
    delivery: Path | None,
) -> SplatQuality:
    runtime, metrics = _runtime_and_metrics(manifest, output)
    heldout = metrics.get("heldout_views")
    iterations = runtime.get("iterations_completed")
    peak_vram = runtime.get("peak_vram_bytes")
    if isinstance(heldout, bool) or not isinstance(heldout, int) or heldout <= 0:
        raise ValueError("heldout_views must be a positive measured count")
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 0:
        raise ValueError("iterations_completed must be a measured non-negative integer")
    if isinstance(peak_vram, bool) or not isinstance(peak_vram, int) or peak_vram < 0:
        raise ValueError("peak_vram_bytes must be a measured non-negative integer")
    psnr = _finite(metrics.get("psnr"), "psnr")
    ssim = _finite(metrics.get("ssim"), "ssim")
    lpips = _finite(metrics.get("lpips"), "lpips")
    floaters = _finite(metrics.get("floaters_fraction"), "floaters_fraction")
    coverage = _finite(metrics.get("coverage_fraction"), "coverage_fraction")
    duration = _finite(runtime.get("duration_seconds"), "duration_seconds")
    if duration <= 0:
        raise ValueError("runtime duration must be positive")
    fractions = (
        (ssim, "ssim"),
        (lpips, "lpips"),
        (floaters, "floaters"),
        (coverage, "coverage"),
    )
    for value, field in fractions:
        if not 0 <= value <= 1:
            raise ValueError(f"{field} must be between zero and one")
    reasons: list[str] = []
    if iterations != manifest.max_iterations:
        reasons.append("the declared optimization iteration count was not completed")
    if psnr < manifest.min_psnr:
        reasons.append("held-out PSNR is below the manifest threshold")
    if ssim < manifest.min_ssim:
        reasons.append("held-out SSIM is below the manifest threshold")
    if lpips > manifest.max_lpips:
        reasons.append("held-out LPIPS is above the manifest threshold")
    if floaters > manifest.max_floaters_fraction:
        reasons.append("floater fraction is above the manifest threshold")
    if coverage < manifest.min_coverage_fraction:
        reasons.append("coverage is below the manifest threshold")
    browser_bytes = delivery.stat().st_size if delivery is not None and delivery.is_file() else None
    delivery_digest = (
        _digest_file(delivery) if delivery is not None and delivery.is_file() else None
    )
    if browser_bytes is not None and browser_bytes > manifest.max_browser_bytes:
        reasons.append("the PlayCanvas delivery artifact exceeds the manifest byte budget")
    accepted = not reasons and browser_bytes is not None and delivery_digest is not None
    return SplatQuality(
        heldout_views=heldout,
        psnr=psnr,
        ssim=ssim,
        lpips=lpips,
        floaters_fraction=floaters,
        coverage_fraction=coverage,
        iterations_completed=iterations,
        duration_seconds=duration,
        usd_cost=duration * manifest.usd_per_gpu_hour / 3600,
        gpu=str(runtime.get("gpu", "")),
        cuda_version=str(runtime.get("cuda_version", "")),
        driver_version=str(runtime.get("driver_version", "")),
        peak_vram_bytes=peak_vram,
        browser_bytes=browser_bytes,
        delivery_sha256=delivery_digest,
        accepted=accepted,
        fallback_rung=3,
        reasons=tuple(reasons),
    )


def run_gsplat_job(
    manifest: SplatBuildManifest,
    *,
    dataset_dir: Path,
    pose_receipt: Path,
    jobs_root: Path,
    runner_executable: str = "exulanica-gsplat-scene-v1",
    compressor_executable: str = "splat-transform",
    compressor_gpu: str = "cpu",
    executor: CommandExecutor = _execute,
) -> SplatJobResult:
    """Run/resume scene optimization, then compress only a quality-accepted PLY to SOG."""
    if not dataset_dir.is_dir():
        raise ValueError("the authorized COLMAP dataset directory does not exist")
    _verify_dataset_sources(manifest, dataset_dir)
    _verify_pose_receipt(manifest, pose_receipt, dataset_dir)
    jobs_root.mkdir(parents=True, exist_ok=True)
    job = jobs_root / manifest.digest
    job.mkdir(exist_ok=True)
    manifest_path = job / "manifest.json"
    manifest_bytes = _canonical(manifest.as_payload()) + b"\n"
    if manifest_path.exists() and manifest_path.read_bytes() != manifest_bytes:
        raise ValueError("the gsplat job directory contains another manifest")
    if not manifest_path.exists():
        _write_atomic(manifest_path, manifest.as_payload())

    with _locked(job / "job.lock"):
        output = job / "output"
        output.mkdir(exist_ok=True)
        receipt = job / "receipt.json"
        delivery = output / "scene.sog"
        if receipt.is_file():
            recorded = _object(receipt)
            quality = _quality(manifest, output, delivery=delivery)
            if recorded.get("quality_digest") != _digest_bytes(_canonical(quality.as_payload())):
                raise ValueError("the gsplat outputs no longer match their receipt")
            return SplatJobResult("completed", manifest.digest, job, quality, True)

        train_command = (
            runner_executable,
            "train",
            "--profile",
            _RUNNER_PROFILE,
            "--manifest",
            str(manifest_path),
            "--pose-receipt",
            str(pose_receipt),
            "--dataset",
            str(dataset_dir),
            "--output",
            str(output),
            "--resume",
            "auto",
        )
        trained = executor(train_command, job)
        _write_atomic(
            job / "train-attempt.json",
            {
                "command": list(train_command),
                "returncode": trained.returncode,
                "duration_ms": trained.duration_ms,
                "stdout_sha256": _digest_bytes(trained.stdout.encode()),
                "stderr_sha256": _digest_bytes(trained.stderr.encode()),
                # A digest alone left the first real failure nameless; the tail is what an operator
                # needs, bounded so a runaway log cannot bloat the private attempt record.
                "stderr_tail": trained.stderr[-4000:],
            },
        )
        if trained.returncode == 75:
            checkpoints = tuple((output / "checkpoints").glob("*.pt"))
            if not checkpoints:
                return SplatJobResult(
                    "failed", manifest.digest, job, None, False, "preemption produced no checkpoint"
                )
            return SplatJobResult(
                "checkpointed", manifest.digest, job, None, False, "preempted; resume is durable"
            )
        if trained.returncode != 0:
            last_line = next(
                (line.strip() for line in reversed(trained.stderr.splitlines()) if line.strip()),
                "",
            )[:300]
            detail = f": {last_line}" if last_line else ""
            return SplatJobResult(
                "failed",
                manifest.digest,
                job,
                None,
                False,
                f"gsplat runner exited {trained.returncode}{detail}; rung 3 fallback",
            )
        ply = output / "accepted.ply"
        if not ply.is_file():
            return SplatJobResult(
                "failed", manifest.digest, job, None, False, "runner produced no accepted PLY"
            )
        # Evaluate before compression so a rejected scene never receives a rung-1 delivery asset.
        preliminary = _quality(manifest, output, delivery=None)
        non_delivery_reasons = tuple(
            reason for reason in preliminary.reasons if "delivery" not in reason
        )
        if non_delivery_reasons:
            quality = replace(preliminary, accepted=False, reasons=non_delivery_reasons)
            _write_atomic(
                receipt,
                {
                    "manifest_digest": manifest.digest,
                    "quality_digest": _digest_bytes(_canonical(quality.as_payload())),
                    "quality": quality.as_payload(),
                },
            )
            return SplatJobResult("completed", manifest.digest, job, quality, False)

        version_command = (compressor_executable, "--version")
        version = executor(version_command, job)
        expected_version = TRAINING_PROTOCOL["compressor"]["version"]
        # MEASURED 2026-09-05: splat-transform 3.3.3 prints its banner on stderr. Reading stdout
        # alone refused the first accepted real training after two hours on the card.
        if version.returncode != 0 or not re.search(
            rf"\bv{re.escape(expected_version)}\b", f"{version.stdout}\n{version.stderr}"
        ):
            return SplatJobResult(
                "failed",
                manifest.digest,
                job,
                None,
                False,
                "SOG compressor does not match the manifest protocol version",
            )
        # MEASURED 2026-09-06 on one million degree-3 Gaussians: the compressor's k-means over
        # 65536 clusters of 45 SH coefficients ran for hours on one CPU core and finished in
        # under a minute on the L40S through Vulkan. The device is an operator setting; the
        # output format and every SH band are unchanged either way.
        compress_command = (
            compressor_executable,
            "--no-tty",
            "--overwrite",
            "-g",
            compressor_gpu,
            str(ply),
            str(delivery),
        )
        compressed = executor(compress_command, job)
        _write_atomic(
            job / "compression-attempt.json",
            {
                "command": list(compress_command),
                "gpu_device": compressor_gpu,
                "version_output": f"{version.stdout}{version.stderr}".strip(),
                "protocol": TRAINING_PROTOCOL["compressor"],
                "returncode": compressed.returncode,
                "duration_ms": compressed.duration_ms,
                "stdout_sha256": _digest_bytes(compressed.stdout.encode()),
                "stderr_sha256": _digest_bytes(compressed.stderr.encode()),
            },
        )
        if compressed.returncode != 0 or not delivery.is_file():
            return SplatJobResult(
                "failed",
                manifest.digest,
                job,
                None,
                False,
                "SOG compression failed; rung 3 fallback",
            )
        quality = _quality(manifest, output, delivery=delivery)
        _write_atomic(
            receipt,
            {
                "manifest_digest": manifest.digest,
                "quality_digest": _digest_bytes(_canonical(quality.as_payload())),
                "quality": quality.as_payload(),
                "delivery": {
                    "path": "output/scene.sog",
                    "sha256": quality.delivery_sha256,
                    "byte_length": quality.browser_bytes,
                },
                "default_package_exclusions": ["output/checkpoints", "output/training"],
            },
        )
        return SplatJobResult("completed", manifest.digest, job, quality, False)
