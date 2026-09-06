"""Explicit training requests and checkpointed execution inside an existing scene lease."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import shutil
import signal
import struct
import subprocess
import tempfile
import time
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.errors import TombstonedError
from exulanica.ingest.stages import STAGES
from exulanica.reconstruction.gsplat_protocol import GSPLAT_REVISION
from exulanica.reconstruction.pose import CommandResult, PoseBuildManifest
from exulanica.reconstruction.splat import SplatBuildManifest


class ContainerCleanupUnconfirmed(RuntimeError):
    """The owned external worker may still hold source mounts; scratch must be retained."""


#: The stage parameter is the single source of the budget, so the value that enters stage
#: identity is the value the packager enforces.
EVALUATION_MAX_BYTES = int(STAGES["scene_splat_evaluation"].params["max_bytes"])


def evaluation_bundle(output: Path) -> bytes:
    """Retain bounded generated evaluation outputs, with no checkpoint or dataset publication."""
    paths = {"metrics.json", "runtime.json"}
    paths.update(
        name for name in ("split.json", "training/dataset.json") if (output / name).is_file()
    )
    paths.update(
        path.relative_to(output).as_posix() for path in (output / "attempts").glob("*.json")
    )
    runtime = json.loads((output / "runtime.json").read_bytes())
    expected: dict[str, str] = {}
    for relative, binding in (
        ("split.json", "split_sha256"),
        ("training/dataset.json", "prepared_dataset_receipt_sha256"),
    ):
        digest = runtime.get(binding)
        if runtime.get("profile") == "exulanica.gsplat-scene-runner/v1" or digest is not None:
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("evaluation companion requires a valid runtime digest binding")
            paths.add(relative)
            expected[relative] = digest
    metrics = json.loads((output / "metrics.json").read_bytes())
    views = metrics.get("per_view")
    if not isinstance(views, list) or not views or len(views) != metrics.get("heldout_views"):
        raise ValueError("evaluation bundle requires every declared held-out render")
    for view in views:
        relative = PurePosixPath(view["render"])
        if (
            relative.as_posix() != view["render"]
            or relative.is_absolute()
            or ".." in relative.parts
            or len(relative.parts) != 2
            or relative.parts[0] != "heldout"
            or relative.suffix != ".png"
        ):
            raise ValueError("held-out render path escapes its generated output directory")
        if str(relative) in expected:
            raise ValueError("held-out render paths must be unique")
        expected[str(relative)] = view["render_sha256"]
        paths.add(str(relative))
        if view["reference_pixels_sha256"] != view["source_sha256"]:
            name = PurePosixPath(view["source_name"])
            if name.is_absolute() or ".." in name.parts or name.as_posix() != view["source_name"]:
                raise ValueError("rectified held-out reference path is not normalized")
            reference = str(PurePosixPath("training/undistorted/images") / name)
            paths.add(reference)
            expected[reference] = view["reference_pixels_sha256"]
    if len(paths) > 10_000:
        raise ValueError("evaluation bundle exceeds its file budget")
    payloads = {}
    total = 0
    for relative in sorted(paths):
        path = output / relative
        if path.is_symlink() or any(
            parent.is_symlink() for parent in path.parents if parent.is_relative_to(output)
        ):
            raise ValueError("evaluation bundle cannot include symlinked outputs")
        if not path.is_file():
            raise ValueError(f"evaluation bundle requires generated output {relative}")
        total += path.stat().st_size
        if total > EVALUATION_MAX_BYTES:
            raise ValueError("evaluation bundle exceeds its retained-byte budget")
        data = path.read_bytes()
        if relative in expected and hashlib.sha256(data).hexdigest() != expected[relative]:
            raise ValueError(
                "retained evaluation output disagrees with its runtime or metric digest"
            )
        payloads[relative] = data
    inventory = {
        "profile": "exulanica.scene-splat-evaluation/v1",
        "notice": "Private generated evaluation artifacts; reconstruction is not evidence.",
        "files": [
            {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data)}
            for name, data in payloads.items()
        ],
    }
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in {"inventory.json": receipt_bytes(inventory), **payloads}.items():
            archive.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), data)
    if len(memory.getvalue()) > EVALUATION_MAX_BYTES:
        raise ValueError("evaluation bundle exceeds its retained-byte budget")
    return memory.getvalue()


@dataclass(frozen=True, slots=True)
class SceneSplatRequest:
    """An operator's explicit compute configuration, bound before any work is queued.

    No provider is provisioned by this request. The scene worker invokes the reviewed local
    container entrypoint on an already authorized CUDA host. A rate of zero means an explicitly
    declared zero marginal GPU rental rate, never an inferred free run.
    """

    execution_image: str
    requested_gpu: str
    dependency_inventory: tuple[str, ...]
    heldout_source_sha256: tuple[str, ...]
    max_iterations: int
    checkpoint_every: int
    gaussian_cap: int
    usd_per_gpu_hour_millionths: int
    min_psnr_millionths: int
    min_ssim_millionths: int
    max_lpips_millionths: int
    max_floaters_fraction_millionths: int
    min_coverage_fraction_millionths: int
    max_browser_bytes: int

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name in {
                "execution_image",
                "requested_gpu",
                "dependency_inventory",
                "heldout_source_sha256",
            }:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"training request {name} must be a nonnegative integer")
        if not re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", self.execution_image):
            raise ValueError("training runtime must be digest-pinned")
        if not self.requested_gpu or "gsplat" not in self.dependency_inventory:
            raise ValueError("training request must declare its GPU and gsplat dependency")
        for name in ("max_iterations", "checkpoint_every", "gaussian_cap", "max_browser_bytes"):
            if getattr(self, name) <= 0:
                raise ValueError(f"training request {name} must be positive")
        if self.checkpoint_every > self.max_iterations:
            raise ValueError("checkpoint interval exceeds training iterations")
        for name in (
            "min_ssim_millionths",
            "max_lpips_millionths",
            "max_floaters_fraction_millionths",
            "min_coverage_fraction_millionths",
        ):
            if getattr(self, name) > 1_000_000:
                raise ValueError(f"training request {name} exceeds one")
        if not self.heldout_source_sha256 or any(
            not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            for digest in self.heldout_source_sha256
        ):
            raise ValueError("training request needs exact held-out source hashes")

    def validate_sources(self, sources: tuple[str, ...]) -> None:
        heldout = set(self.heldout_source_sha256)
        if (
            len(heldout) != len(self.heldout_source_sha256)
            or not heldout < set(sources)
            or len(set(sources) - heldout) < 3
        ):
            raise ValueError("training requires a fixed held-out subset and three training sources")

    def validate_admitted_sources(self, sources: tuple[str, ...], manifests: list[object]) -> None:
        """Preserve a benchmark's prior split, or freeze generic inputs at enqueue."""
        self.validate_sources(sources)
        if not any(manifest is not None for manifest in manifests):
            return
        if len(manifests) != len(sources) or any(
            not isinstance(manifest, dict) for manifest in manifests
        ):
            raise ValueError("every admitted reference source must bind the same frozen manifest")
        if any(canonical_json(manifest) != canonical_json(manifests[0]) for manifest in manifests):
            raise ValueError("admitted reference sources disagree on their frozen manifest")
        split = manifests[0].get("evaluation_split")
        if not isinstance(split, dict):
            raise ValueError("admitted source manifest has no frozen evaluation split")
        heldout, training = split.get("heldout_sha256"), split.get("training_sha256")
        if (
            not isinstance(heldout, list)
            or not isinstance(training, list)
            or any(not isinstance(value, str) for value in [*heldout, *training])
            or len(set(heldout)) != len(heldout)
            or len(set(training)) != len(training)
            or set(heldout) != set(self.heldout_source_sha256)
            or set(training) != set(sources) - set(heldout)
        ):
            raise ValueError("training request changes the admitted frozen held-out split")

    def as_payload(self) -> dict[str, Any]:
        value = {"profile": "exulanica.scene-splat-request/v1", **asdict(self)}
        value["dependency_inventory"] = list(self.dependency_inventory)
        value["heldout_source_sha256"] = list(self.heldout_source_sha256)
        canonical_json(value)  # Reject floats or other noncanonical queue input.
        return value

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> SceneSplatRequest:
        if value.get("profile") != "exulanica.scene-splat-request/v1":
            raise ValueError("unsupported scene training request")
        arguments = {key: item for key, item in value.items() if key != "profile"}
        for key in ("dependency_inventory", "heldout_source_sha256"):
            if not isinstance(arguments.get(key), list):
                raise ValueError(f"training request {key} must be a list")
            arguments[key] = tuple(arguments[key])
        try:
            request = cls(**arguments)
        except TypeError as error:
            raise ValueError("malformed scene training request") from error
        if request.as_payload() != dict(value):
            raise ValueError("noncanonical scene training request")
        return request

    def manifest(self, pose: PoseBuildManifest) -> SplatBuildManifest:
        return SplatBuildManifest(
            scene_ref=pose.scene_ref,
            code_revision=pose.code_revision,
            pose_manifest_digest=pose.digest,
            source_sha256=tuple(frame.sha256 for frame in pose.frames),
            gsplat_revision=GSPLAT_REVISION,
            execution_image=self.execution_image,
            requested_gpu=self.requested_gpu,
            dependency_inventory=self.dependency_inventory,
            heldout_source_sha256=self.heldout_source_sha256,
            heldout_every=5,
            max_iterations=self.max_iterations,
            checkpoint_every=self.checkpoint_every,
            gaussian_cap=self.gaussian_cap,
            usd_per_gpu_hour=self.usd_per_gpu_hour_millionths / 1_000_000,
            min_psnr=self.min_psnr_millionths / 1_000_000,
            min_ssim=self.min_ssim_millionths / 1_000_000,
            max_lpips=self.max_lpips_millionths / 1_000_000,
            max_floaters_fraction=self.max_floaters_fraction_millionths / 1_000_000,
            min_coverage_fraction=self.min_coverage_fraction_millionths / 1_000_000,
            max_browser_bytes=self.max_browser_bytes,
        )


def training_dataset_directory(pose_directory: Path) -> Path:
    """One staged dataset per pose output.

    The pose job directory is named by its manifest digest, and a retried job whose pose manifest
    changed (a new code revision, for one) re-runs COLMAP and produces different sparse bytes.
    MEASURED 2026-09-05: staged under one shared directory, that second output was refused as a
    resumed dataset with changed input bytes and the job failed. Keyed by the pose output it was
    cut from, a resumed attempt of the same pose still verifies the same copy.
    """
    return pose_directory.parent.parent / "training-dataset" / pose_directory.name


def stage_training_dataset(sources: Path, sparse: Path, destination: Path) -> Path:
    """Copy only verified private job inputs, or verify an interrupted job's same copy."""
    for source, target in ((sources, destination / "images"), (sparse, destination / "sparse")):
        expected = {path.relative_to(source) for path in source.rglob("*") if path.is_file()}
        if any(path.is_symlink() for path in source.rglob("*")):
            raise ValueError("training input directories cannot contain symlinks")
        if source.is_symlink() or target.is_symlink():
            raise ValueError("training input directories cannot be symlinks")
        target.mkdir(parents=True, exist_ok=True)
        for temporary in target.rglob("*.copying"):
            if temporary.is_symlink():
                raise ValueError("training input temporary path cannot be a symlink")
            temporary.unlink()
        actual = {path.relative_to(target) for path in target.rglob("*") if path.is_file()}
        if not actual <= expected or any(path.is_symlink() for path in target.rglob("*")):
            raise ValueError("resumed training dataset has a different file inventory")
        for relative in expected:
            destination_file = target / relative
            if destination_file.exists():
                if (source / relative).read_bytes() != destination_file.read_bytes():
                    raise ValueError("resumed training dataset has changed input bytes")
            else:
                destination_file.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination_file.with_name(destination_file.name + ".copying")
                shutil.copyfile(source / relative, temporary)
                temporary.replace(destination_file)
    return destination


def cancellable_executor(
    cancelled: Callable[[], bool], stopped: Callable[[], bool] = lambda: False
) -> Callable[[tuple[str, ...], Path], CommandResult]:
    """Check scene withdrawal and lease ownership while an opaque subprocess is running."""

    def execute(command: tuple[str, ...], cwd: Path) -> CommandResult:
        if cancelled():
            raise TombstonedError("scene was withdrawn or its lease was lost before training")
        started = time.monotonic()
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stderr)
            stop_sent: float | None = None
            forced = False
            was_cancelled = False
            check_error: Exception | None = None
            while process.poll() is None:
                stop_requested = False
                if check_error is None:
                    try:
                        was_cancelled = was_cancelled or cancelled()
                        stop_requested = stopped()
                    except Exception as error:
                        check_error = error
                if (
                    was_cancelled or stop_requested or check_error is not None
                ) and stop_sent is None:
                    process.send_signal(signal.SIGTERM)
                    stop_sent = time.monotonic()
                if stop_sent is not None and time.monotonic() - stop_sent > 60:
                    output = (
                        Path(command[command.index("--output") + 1])
                        if "--output" in command
                        else cwd
                    )
                    marker = output / "container-cleanup-required.json"
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    if not marker.exists():
                        marker.write_text(
                            json.dumps(
                                {
                                    "profile": "exulanica.unconfirmed-training-process/v1",
                                    "launcher_pid": process.pid,
                                    "reason": "external worker termination remains unconfirmed",
                                }
                            )
                        )
                    forced = True
                    process.kill()
                time.sleep(0.25)
            stdout.seek(0)
            stderr.seek(0)
            result = CommandResult(
                process.returncode,
                stdout.read().decode(errors="replace"),
                stderr.read().decode(errors="replace"),
                (time.monotonic() - started) * 1000,
            )
        if forced or result.returncode == 76:
            output = Path(command[command.index("--output") + 1]) if "--output" in command else cwd
            marker = output / "container-cleanup-required.json"
            marker.parent.mkdir(parents=True, exist_ok=True)
            if not marker.exists():
                marker.write_text(
                    json.dumps({"reason": "external worker reported unconfirmed termination"})
                )
            raise ContainerCleanupUnconfirmed(
                "container termination could not be confirmed; private scratch remains protected"
            )
        if was_cancelled or cancelled():
            raise TombstonedError("scene was withdrawn or its lease was lost during training")
        if check_error is not None:
            raise check_error
        return result

    return execute


def gaussian_ply_bounds(data: bytes) -> dict[str, list[float]]:
    """Read actual Gaussian centres/scales; retain a conservative three-sigma support box."""
    terminator = b"end_header\n"
    end = data.find(terminator)
    if end < 0 or end > 1_048_576:
        raise ValueError("Gaussian PLY has no bounded header")
    lines = data[:end].decode("ascii").splitlines()
    if not lines or lines[0] != "ply" or "format binary_little_endian 1.0" not in lines:
        raise ValueError("Gaussian PLY must use binary little endian float properties")
    properties = []
    count = 0
    in_vertices = False
    for line in lines:
        parts = line.split()
        if parts[:1] == ["element"]:
            in_vertices = parts[1] == "vertex"
            if in_vertices:
                count = int(parts[2])
        elif in_vertices and parts[:1] == ["property"]:
            if len(parts) != 3 or parts[1] != "float":
                raise ValueError("Gaussian PLY has an unsupported vertex property")
            properties.append(parts[2])
    if count <= 0 or len(set(properties)) != len(properties):
        raise ValueError("Gaussian PLY has invalid vertex membership")
    required = ["x", "y", "z", "scale_0", "scale_1", "scale_2"]
    if any(key not in properties for key in required):
        raise ValueError("Gaussian PLY omits positions or Gaussian scale")
    payload = data[end + len(terminator) :]
    stride = len(properties) * 4
    if len(payload) != count * stride:
        raise ValueError("Gaussian PLY vertex bytes disagree with its header")
    indices = [properties.index(key) for key in required]
    low, high = [float("inf")] * 3, [float("-inf")] * 3
    for vertex in struct.iter_unpack("<" + "f" * len(properties), payload):
        values = [vertex[index] for index in indices]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Gaussian PLY contains nonfinite geometry")
        radius = 3 * math.exp(max(values[3:]))
        for axis in range(3):
            low[axis] = min(low[axis], values[axis] - radius)
            high[axis] = max(high[axis], values[axis] + radius)
    if not all(math.isfinite(value) for value in (*low, *high)):
        raise ValueError("Gaussian PLY support bounds overflowed")
    return {"min": low, "max": high}


def receipt_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    )
