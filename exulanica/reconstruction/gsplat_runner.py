"""Single-GPU gsplat trainer with complete, digest-bound optimizer checkpoints.

This is an independent training loop using the Apache-2.0 gsplat public API. It does
not call the upstream evaluation-only ``--ckpt`` path. CUDA imports are lazy so the
controller and checkpoint integrity checks remain usable on CPU-only deployments.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import random
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from exulanica.reconstruction.gsplat_protocol import (
    CHECKPOINT_PROFILE,
    GSPLAT_REVISION,
    RUNNER_PROFILE,
    TRAINING_PROTOCOL,
)
from exulanica.reconstruction.splat import (
    SplatBuildManifest,
    _canonical,
    _digest_file,
    _locked,
    _verify_dataset_sources,
    _verify_pose_receipt,
    _write_atomic,
    masked_training_binding,
    verify_masked_training_sources,
)

_PROCESS_STARTED = time.monotonic()


def _read_masked_source_remap(value: Any) -> tuple[tuple[str, str, str], ...]:
    """Read the manifest's masked-source object back into ordered tuples, or refuse it.

    Every refusal here is a ``ValueError`` on purpose: ``main`` catches those and prints one
    reason the controller records, where a ``KeyError`` out of a mapping would reach the operator
    as a traceback in a stderr tail.
    """
    if not isinstance(value, dict):
        raise ValueError("manifest masked_source_remap must be an object keyed by capture")
    entries = []
    for capture_ref, item in value.items():
        if not isinstance(item, dict) or set(item) != {"source_sha256", "masked_source_sha256"}:
            raise ValueError("a manifest masked_source_remap entry is malformed")
        entries.append((capture_ref, item["source_sha256"], item["masked_source_sha256"]))
    return tuple(sorted(entries))


def read_manifest(path: Path) -> SplatBuildManifest:
    value = json.loads(path.read_text())
    if value.get("profile") != "exulanica.gsplat-build/v1":
        raise ValueError("unsupported gsplat manifest")
    implementation = value["implementation"]
    if (
        implementation.get("repository") != "nerfstudio-project/gsplat"
        or implementation.get("license") != "Apache-2.0"
        or implementation.get("strategy") != "mcmc"
        or implementation.get("runner_profile") != RUNNER_PROFILE
    ):
        raise ValueError("unreviewed trainer implementation")
    keys = (
        "scene_ref",
        "code_revision",
        "pose_manifest_digest",
        "execution_image",
        "requested_gpu",
    )
    parameters = {
        **value["parameters"],
        "heldout_source_sha256": tuple(value["parameters"]["heldout_source_sha256"]),
    }
    if "decoded_source_lineage" in parameters:
        if not isinstance(parameters["decoded_source_lineage"], list):
            raise ValueError("manifest decoded_source_lineage must be a list")
        parameters["decoded_source_lineage"] = tuple(parameters["decoded_source_lineage"])
    if "masked_source_remap" in parameters:
        parameters["masked_source_remap"] = _read_masked_source_remap(
            parameters["masked_source_remap"]
        )
    manifest = SplatBuildManifest(
        **{key: value[key] for key in keys},
        source_sha256=tuple(value["source_sha256"]),
        gsplat_revision=implementation["revision"],
        dependency_inventory=tuple(value["dependency_inventory"]),
        **parameters,
        **value["cost_rate"],
        **value["quality_thresholds"],
    )
    if value != manifest.as_payload():
        raise ValueError("manifest contains unsupported or changed training protocol")
    return manifest


def dataset_digest(dataset: Path) -> str:
    """Bind checkpoints to exact camera/point model bytes as well as image bytes."""
    files = sorted(p for p in dataset.rglob("*") if p.is_file())
    if any(p.is_symlink() for p in dataset.rglob("*")):
        raise ValueError("training datasets may not contain symlinks")
    return hashlib.sha256(
        _canonical(
            [{"path": p.relative_to(dataset).as_posix(), "sha256": _digest_file(p)} for p in files]
        )
    ).hexdigest()


def capture_rng() -> dict[str, Any]:
    import numpy as np
    import torch

    numpy_state = np.random.get_state()
    return {
        "python": random.getstate(),
        "numpy": [numpy_state[0], numpy_state[1].tolist(), *numpy_state[2:]],
        "torch": torch.get_rng_state(),
        "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
    }


def restore_rng(state: dict[str, Any]) -> None:
    import numpy as np
    import torch

    random.setstate(state["python"])
    algorithm, keys, position, has_gauss, cached = state["numpy"]
    np.random.set_state((algorithm, np.array(keys, dtype=np.uint32), position, has_gauss, cached))
    torch.set_rng_state(state["torch"].cpu())
    if state["cuda"]:
        if len(state["cuda"]) != torch.cuda.device_count():
            raise ValueError("checkpoint CUDA device topology changed")
        torch.cuda.set_rng_state_all([item.cpu() for item in state["cuda"]])


def save_checkpoint(
    directory: Path,
    *,
    identity: dict[str, str],
    step: int,
    splats: Any,
    optimizers: dict[str, Any],
    scheduler: Any,
    strategy_state: dict[str, Any],
    sampler: dict[str, Any],
    duration_seconds: float,
    peak_vram_bytes: int,
) -> Path:
    import torch

    directory.mkdir(parents=True, exist_ok=True)
    checkpoint = directory / f"step-{step:09d}.pt"
    temporary = checkpoint.with_suffix(".tmp")
    state = {
        "profile": CHECKPOINT_PROFILE,
        "identity": identity,
        "next_iteration": step,
        "splats": splats.state_dict(),
        "optimizers": {key: opt.state_dict() for key, opt in optimizers.items()},
        "scheduler": scheduler.state_dict(),
        "strategy": strategy_state,
        "rng": capture_rng(),
        "sampler": sampler,
        "duration_seconds": duration_seconds,
        "peak_vram_bytes": peak_vram_bytes,
    }
    with temporary.open("wb") as stream:
        torch.save(state, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, checkpoint)
    # The pointer is published only after both checkpoint bytes and directory entry are durable.
    directory_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    _write_atomic(
        directory / "latest.json",
        {
            "profile": CHECKPOINT_PROFILE,
            "file": checkpoint.name,
            "sha256": _digest_file(checkpoint),
            "identity": identity,
            "next_iteration": step,
        },
    )
    directory_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return checkpoint


def load_checkpoint(directory: Path, *, identity: dict[str, str]) -> dict[str, Any] | None:
    import torch

    pointer = directory / "latest.json"
    if not pointer.exists():
        if directory.exists() and any(directory.glob("*.pt")):
            raise ValueError("checkpoint exists without a committed durable pointer")
        return None
    value = json.loads(pointer.read_text())
    name = value.get("file", "")
    if (
        value.get("profile") != CHECKPOINT_PROFILE
        or value.get("identity") != identity
        or Path(name).name != name
        or not name.endswith(".pt")
    ):
        raise ValueError("checkpoint identity or pointer is invalid")
    checkpoint = directory / name
    if checkpoint.is_symlink() or _digest_file(checkpoint) != value.get("sha256"):
        raise ValueError("checkpoint bytes do not match their digest")
    state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    required = {
        "profile",
        "identity",
        "next_iteration",
        "splats",
        "optimizers",
        "scheduler",
        "strategy",
        "rng",
        "sampler",
        "duration_seconds",
        "peak_vram_bytes",
    }
    if (
        not isinstance(state, dict)
        or not required <= state.keys()
        or state["profile"] != CHECKPOINT_PROFILE
        or state["identity"] != identity
        or state["next_iteration"] != value.get("next_iteration")
    ):
        raise ValueError("checkpoint does not contain complete resumable training state")
    if set(state["splats"]) != set(state["optimizers"]):
        raise ValueError("checkpoint optimizer membership differs from Gaussian parameters")
    return state


def restore_optimizers(state: dict[str, Any], optimizers: dict[str, Any], scheduler: Any) -> None:
    if set(optimizers) != set(state["optimizers"]):
        raise ValueError("optimizer membership changed on resume")
    for key, optimizer in optimizers.items():
        optimizer.load_state_dict(state["optimizers"][key])
    scheduler.load_state_dict(state["scheduler"])
    restore_rng(state["rng"])


def loaded_packages() -> list[str]:
    modules = {name.partition(".")[0] for name in sys.modules}
    mapping = importlib.metadata.packages_distributions()
    names = {name for module in modules for name in mapping.get(module, [])}
    # Editable gsplat distributions may not publish a top_level.txt mapping.
    if "gsplat" in modules:
        names.add("gsplat")
    return sorted(name.lower().replace("_", "-") for name in names)


def verify_runtime(manifest: SplatBuildManifest) -> dict[str, Any]:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("gsplat training requires an NVIDIA CUDA GPU; this host has none")
    if manifest.gsplat_revision != GSPLAT_REVISION:
        raise ValueError("this runner only supports its reviewed gsplat revision")
    import gsplat

    if os.environ.get("EXULANICA_BUILD_REVISION") != manifest.code_revision:
        raise ValueError("runner image Exulanica revision differs from the build manifest")
    root = Path(gsplat.__file__).resolve().parent.parent
    revision = subprocess.check_output(
        ["git", "-c", f"safe.directory={root}", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    changed = subprocess.check_output(
        [
            "git",
            "-c",
            f"safe.directory={root}",
            "-C",
            str(root),
            "status",
            "--porcelain",
            "--untracked-files=no",
        ],
        text=True,
    ).strip()
    if revision != manifest.gsplat_revision or changed:
        raise ValueError("loaded gsplat code differs from the reviewed immutable checkout")
    packages = {
        dist.metadata["Name"].lower().replace("_", "-"): dist.version
        for dist in importlib.metadata.distributions()
        if dist.metadata.get("Name")
    }
    forbidden = {"diff-gaussian-rasterization", "gaussian-splatting", "graphdeco-inria"}
    if packages.keys() & forbidden:
        raise ValueError("runtime contains a blocked INRIA rasterizer package")
    if (
        not {item.lower().replace("_", "-") for item in manifest.dependency_inventory}
        <= packages.keys()
    ):
        raise ValueError("runtime is missing manifest dependencies")
    driver = (
        subprocess.check_output(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], text=True
        )
        .splitlines()[0]
        .strip()
    )
    gpu = torch.cuda.get_device_name(0)
    if gpu != manifest.requested_gpu:
        raise ValueError(f"allocated GPU {gpu!r} differs from requested {manifest.requested_gpu!r}")
    return {
        "profile": RUNNER_PROFILE,
        "backend": "gsplat",
        "gsplat_revision": revision,
        "loaded_packages": loaded_packages(),
        "installed_packages": sorted(packages),
        "package_versions": packages,
        "gpu": gpu,
        "cuda_version": torch.version.cuda,
        "driver_version": driver,
        "torch_version": str(torch.__version__),
        "training_protocol": TRAINING_PROTOCOL,
    }


def prepare_dataset(dataset: Path, output: Path, selected_model: str | None = None) -> Path:
    """Rectify distorted sources inside job-private storage without changing pose frames."""
    import numpy as np
    import pycolmap

    if pycolmap.__version__ != "4.2.0":
        raise ValueError("the image rectification protocol requires pycolmap 4.2.0")
    sparse = dataset / "sparse"
    model = (
        sparse / selected_model
        if selected_model
        else (sparse / "0" if (sparse / "0").is_dir() else sparse)
    )
    reconstruction = pycolmap.Reconstruction(str(model))
    source_names = sorted(image.name for image in reconstruction.images.values())
    for name in source_names:
        path = dataset / "images" / name
        if not path.resolve().is_relative_to((dataset / "images").resolve()) or not path.is_file():
            raise ValueError("COLMAP image path escapes or is missing from the exact dataset")
    distorted = any(
        camera.model_name not in {"PINHOLE", "SIMPLE_PINHOLE"}
        for camera in reconstruction.cameras.values()
    )
    training = output / "training"
    training.mkdir(exist_ok=True)
    prepared = training / "undistorted"
    receipt_path = training / "dataset.json"
    source_digest = dataset_digest(dataset)
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        selected = prepared if distorted else dataset
        if (
            receipt.get("source_dataset_digest") != source_digest
            or receipt.get("prepared_dataset_digest") != dataset_digest(selected)
            or receipt.get("protocol") != TRAINING_PROTOCOL["undistortion"]
        ):
            raise ValueError("prepared dataset no longer matches its source/calibration receipt")
        return selected
    selected = dataset
    if distorted:
        if prepared.exists():
            # This directory is a private, unpublished intermediate under the runner lock.
            # A hard kill during native rectification must not poison all later retries.
            if prepared.is_symlink() or not prepared.resolve().is_relative_to(output.resolve()):
                raise ValueError(
                    "uncommitted undistortion output escapes the private job directory"
                )
            shutil.rmtree(prepared)
        pycolmap.undistort_images(
            output_path=str(prepared),
            input_path=str(model),
            image_path=str(dataset / "images"),
            image_names=source_names,
            output_type="COLMAP",
            copy_policy=pycolmap.FileCopyType.copy,
            jpeg_quality=100,
            num_threads=1,
            undistort_options=pycolmap.UndistortCameraOptions(
                blank_pixels=0.0,
                min_scale=0.2,
                max_scale=2.0,
                max_image_size=-1,
            ),
        )
        selected = prepared
        rectified = pycolmap.Reconstruction(str(prepared / "sparse"))
        if set(rectified.images) != set(reconstruction.images):
            raise ValueError("rectification changed registered image membership")
        for image_id, source in reconstruction.images.items():
            if not np.allclose(
                source.cam_from_world().matrix(),
                rectified.images[image_id].cam_from_world().matrix(),
                rtol=0,
                atol=1e-12,
            ):
                raise ValueError("rectification changed an authoritative camera pose")
        if set(rectified.points3D) != set(reconstruction.points3D) or any(
            not np.array_equal(point.xyz, rectified.points3D[point_id].xyz)
            for point_id, point in reconstruction.points3D.items()
        ):
            raise ValueError("rectification changed the authoritative sparse coordinate frame")
    _write_atomic(
        receipt_path,
        {
            "profile": "exulanica.gsplat-prepared-dataset/v1",
            "source_dataset_digest": source_digest,
            "prepared_dataset_digest": dataset_digest(selected),
            "rectified": distorted,
            "protocol": TRAINING_PROTOCOL["undistortion"],
            "coordinate_frame": "unchanged-authoritative-COLMAP-world",
            "images": [
                {
                    "name": name,
                    "source_sha256": _digest_file(dataset / "images" / name),
                    "training_pixels_sha256": _digest_file(selected / "images" / name),
                }
                for name in source_names
            ],
        },
    )
    return selected


def load_dataset(
    dataset: Path,
    heldout_every: int,
    *,
    selected_model: str | None = None,
    heldout_sources: tuple[str, ...] | None = None,
    original_dataset: Path | None = None,
) -> tuple[list[dict[str, Any]], Any]:
    """Load registered views, marking held out exactly the ones the manifest predeclared.

    ``original_dataset`` means *before rectification*, not *before masking*. On a scene with
    somebody hidden in it those staged bytes are the masked derivative, and that is the intent:
    the digests matched here, the digests in ``source_sha256`` and the pixels every metric is
    computed against are all the same masked bytes. The manifest's remap is what records which
    photograph each of them replaced.
    """
    import numpy as np
    import pycolmap

    from exulanica.corpus.decode import probe

    sparse = dataset / "sparse"
    model = (
        sparse / selected_model
        if selected_model
        else (sparse / "0" if (sparse / "0").is_dir() else sparse)
    )
    reconstruction = pycolmap.Reconstruction(str(model))
    views = []
    for index, image in enumerate(
        sorted(reconstruction.images.values(), key=lambda item: item.name)
    ):
        camera = reconstruction.cameras[image.camera_id]
        if camera.model_name not in {"PINHOLE", "SIMPLE_PINHOLE"}:
            raise ValueError("gsplat input cameras must be undistorted PINHOLE or SIMPLE_PINHOLE")
        image_path = dataset / "images" / image.name
        if not image_path.resolve().is_relative_to((dataset / "images").resolve()):
            raise ValueError("COLMAP image path escapes the exact dataset")
        if probe(image_path.read_bytes()) != (camera.width, camera.height):
            raise ValueError("COLMAP camera resolution differs from source image")
        transform = np.eye(4, dtype=np.float32)
        transform[:3] = image.cam_from_world().matrix()
        views.append(
            {
                "name": image.name,
                "path": image_path,
                "source_path": (original_dataset or dataset) / "images" / image.name,
                "viewmat": transform,
                "K": np.asarray(camera.calibration_matrix(), dtype=np.float32),
                "width": camera.width,
                "height": camera.height,
                "heldout": (
                    index % heldout_every == 0
                    if heldout_sources is None
                    else _digest_file((original_dataset or dataset) / "images" / image.name)
                    in heldout_sources
                ),
            }
        )
    if sum(not view["heldout"] for view in views) < 3 or not any(v["heldout"] for v in views):
        raise ValueError("training requires at least three train views and one held-out view")
    points = np.array([p.xyz for p in reconstruction.points3D.values()], dtype=np.float32)
    if points.ndim != 2 or points.shape[0] < 4 or not np.isfinite(points).all():
        raise ValueError("training requires at least four finite COLMAP sparse points")
    return views, points


def decode_rgb_uint8(view: dict[str, Any]) -> Any:
    """The exact training pixels of one view as an HxWx3 uint8 array."""
    import numpy as np

    from exulanica.corpus.decode import open_sensor

    with open_sensor(view["path"].read_bytes()) as source:
        return np.array(source.convert("RGB"), dtype=np.uint8)


# Enough for about 180 twelve-megapixel views as bytes; the L40S that measured this holds 46 GiB.
DEFAULT_IMAGE_CACHE_BYTES = 16 * 1024**3


class DecodedImages:
    """Exact training pixels, decoded once per view and held as bytes on the training device.

    MEASURED 2026-09-05 on the first real CUDA run: decoding each twelve-megapixel JPEG on every
    iteration held the trainer at one CPU core and the GPU at 24 percent utilization, about 2.5
    iterations per second. Held as uint8 and converted to float on the device per step, the values
    are identical to decoding afresh, so no metric or protocol changes. A byte budget bounds device
    memory; a view beyond the budget decodes as before.
    """

    def __init__(
        self, torch: Any, budget_bytes: int = DEFAULT_IMAGE_CACHE_BYTES, device: str = "cuda"
    ) -> None:
        self._torch = torch
        self._budget = budget_bytes
        self._device = device
        self._held: dict[Path, Any] = {}
        self._bytes = 0

    def pixels(self, view: dict[str, Any]) -> Any:
        key = view["path"]
        held = self._held.get(key)
        if held is None:
            held = self._torch.from_numpy(decode_rgb_uint8(view)).to(self._device)
            if self._bytes + held.numel() <= self._budget:
                self._held[key] = held
                self._bytes += held.numel()
        # A fresh float tensor each call; the cached bytes are never mutated.
        return held.to(self._torch.float32).div_(255.0).unsqueeze(0)


def _image(view: dict[str, Any], torch: Any) -> Any:
    return DecodedImages(torch, budget_bytes=0).pixels(view)


def seed_values(points: Any, manifest: SplatBuildManifest, torch: Any) -> dict[str, Any]:
    """Initial single-precision Gaussians from the sparse points, before any device transfer.

    Every tensor is float32 explicitly. MEASURED 2026-09-05 on the first real CUDA run: the
    nearest-neighbour distances SciPy returns are float64, so the seed scales reached the
    rasterizer as Double beside Float means and the first iteration refused with
    ``expected scalar type Float but found Double``.
    """
    import numpy as np
    from scipy.spatial import cKDTree

    points = np.asarray(points, dtype=np.float32)
    if len(points) > manifest.gaussian_cap:
        points = points[np.random.choice(len(points), manifest.gaussian_cap, replace=False)]
    if len(points) < 4:
        raise ValueError("gaussian_cap must allow at least four seed Gaussians")
    distances = cKDTree(points).query(points, k=4)[0][:, 1:]
    scale = np.sqrt(np.mean(distances**2, axis=-1)).clip(min=1e-7).astype(np.float32)
    n = len(points)
    values = {
        "means": torch.from_numpy(points),
        "scales": torch.from_numpy(np.log(scale)).unsqueeze(1).repeat(1, 3),
        "quats": torch.randn(n, 4),
        "opacities": torch.logit(torch.full((n,), 0.1)),
        "sh0": torch.zeros(n, 1, 3),
        "shN": torch.zeros(n, 15, 3),
    }
    for key, value in values.items():
        if value.dtype != torch.float32:
            raise ValueError(f"seed Gaussian {key} is {value.dtype}, not float32")
    return values


def _parameters(points: Any, manifest: SplatBuildManifest, restored: Any, torch: Any) -> Any:
    values = restored["splats"] if restored is not None else seed_values(points, manifest, torch)
    return torch.nn.ParameterDict(
        {key: torch.nn.Parameter(v.to("cuda")) for key, v in values.items()}
    )


def _render(splats: Any, view: dict[str, Any], step: int, torch: Any) -> Any:
    from gsplat import rasterization

    return rasterization(
        means=splats["means"],
        quats=splats["quats"],
        scales=splats["scales"].exp(),
        opacities=splats["opacities"].sigmoid(),
        colors=torch.cat([splats["sh0"], splats["shN"]], 1),
        viewmats=torch.as_tensor(view["viewmat"], device="cuda").unsqueeze(0),
        Ks=torch.as_tensor(view["K"], device="cuda").unsqueeze(0),
        width=view["width"],
        height=view["height"],
        sh_degree=min(step // 1000, 3),
        packed=False,
        rasterize_mode="classic",
        near_plane=0.01,
        far_plane=1e10,
    )


def evaluate(
    splats: Any,
    views: list[dict[str, Any]],
    points: Any,
    step: int,
    output: Path,
    images: DecodedImages | None = None,
) -> dict[str, Any]:
    import numpy as np
    import torch
    from PIL import Image
    from scipy.spatial import cKDTree
    from torchmetrics.functional.image import structural_similarity_index_measure
    from torchmetrics.image.lpip import LearnedPerceptualImagePatchSimilarity

    lpips = LearnedPerceptualImagePatchSimilarity(net_type="alex", normalize=True).to("cuda")
    rendered = output / "heldout"
    rendered.mkdir(exist_ok=True)
    rows = []
    with torch.no_grad():
        for index, view in enumerate(views):
            if not view["heldout"]:
                continue
            colors, alphas, _ = _render(splats, view, step - 1, torch)
            actual = (images.pixels(view) if images is not None else _image(view, torch)).permute(
                0, 3, 1, 2
            )
            predicted = colors.clamp(0, 1).permute(0, 3, 1, 2)
            mse = torch.mean((predicted - actual) ** 2).item()
            if mse <= 0:
                raise ValueError("held-out MSE is zero; cannot emit a finite measured PSNR")
            lpips.reset()
            path = rendered / f"view-{index:05d}.png"
            Image.fromarray((colors[0].clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)).save(path)
            rows.append(
                {
                    "source_name": view["name"],
                    "source_sha256": _digest_file(view["source_path"]),
                    "reference_pixels_sha256": _digest_file(view["path"]),
                    "width": view["width"],
                    "height": view["height"],
                    "render": str(path.relative_to(output)),
                    "render_sha256": _digest_file(path),
                    "psnr": -10 * math.log10(mse),
                    "ssim": structural_similarity_index_measure(
                        predicted, actual, data_range=1.0
                    ).item(),
                    "lpips": lpips(predicted, actual).item(),
                    "coverage_fraction": (alphas >= 0.95).float().mean().item(),
                }
            )
        tree = cKDTree(points)
        spacing = float(np.median(tree.query(points, k=2)[0][:, 1]))
        if not math.isfinite(spacing) or spacing <= 0:
            raise ValueError("sparse support has no measurable positive neighbor spacing")
        distances = tree.query(splats["means"].detach().cpu().numpy(), k=1)[0]
        weights = splats["opacities"].sigmoid().cpu().numpy()
        floaters = float(np.sum(weights * (distances > 5 * spacing)) / np.sum(weights))
    return {
        "profile": "exulanica.gsplat-quality/v1",
        "heldout_views": len(rows),
        **{
            key: float(np.mean([row[key] for row in rows]))
            for key in ("psnr", "ssim", "lpips", "coverage_fraction")
        },
        "floaters_fraction": floaters,
        "sparse_neighbor_spacing": spacing,
        "metric_definitions": TRAINING_PROTOCOL,
        "per_view": rows,
    }


def train(manifest: SplatBuildManifest, dataset: Path, output: Path, selected_model: str) -> int:
    import numpy as np
    import torch
    from gsplat import export_splats
    from gsplat.strategy import MCMCStrategy
    from torchmetrics.functional.image import structural_similarity_index_measure

    runtime = verify_runtime(manifest)
    output.mkdir(parents=True, exist_ok=True)
    identity = {"manifest_digest": manifest.digest, "dataset_digest": dataset_digest(dataset)}
    runtime.update(identity)
    with _locked(output / "runner.lock"):
        return _train_locked(
            manifest,
            dataset,
            output,
            selected_model,
            identity,
            runtime,
            np,
            torch,
            MCMCStrategy,
            structural_similarity_index_measure,
            export_splats,
        )


def _train_locked(
    manifest: SplatBuildManifest,
    dataset: Path,
    output: Path,
    selected_model: str,
    identity: dict[str, str],
    runtime: dict[str, Any],
    np: Any,
    torch: Any,
    strategy_class: Any,
    ssim: Any,
    exporter: Any,
) -> int:
    checkpoints = output / "checkpoints"
    restored = load_checkpoint(checkpoints, identity=identity)
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)
    torch.cuda.manual_seed_all(42)
    # Before rectification, not merely before the load. `prepare_dataset` decodes every staged
    # image and writes it back into the job directory, so a leaked original checked afterwards
    # would already have been re-encoded into retained scratch by the time anything refused it.
    verify_masked_training_sources(manifest, dataset)
    prepared = prepare_dataset(dataset, output, selected_model)
    views, points = load_dataset(
        prepared,
        manifest.heldout_every,
        selected_model=selected_model if prepared == dataset else None,
        heldout_sources=manifest.heldout_source_sha256,
        original_dataset=dataset,
    )
    train_indices = [index for index, view in enumerate(views) if not view["heldout"]]
    split = {
        "profile": "exulanica.gsplat-heldout-split/v1",
        **identity,
        "protocol": TRAINING_PROTOCOL,
        "training": [v["name"] for v in views if not v["heldout"]],
        "heldout": [v["name"] for v in views if v["heldout"]],
        "predeclared_heldout_source_sha256": list(manifest.heldout_source_sha256),
        "unregistered_heldout_source_sha256": sorted(
            set(manifest.heldout_source_sha256) - {_digest_file(v["source_path"]) for v in views}
        ),
        **masked_training_binding(manifest),
    }
    split_path = output / "split.json"
    if split_path.exists() and json.loads(split_path.read_text()) != split:
        raise ValueError("predeclared held-out split changed")
    _write_atomic(split_path, split)
    # No recentering or normalization changes the authoritative pose coordinate frame.
    scene_scale = float(np.linalg.norm(np.std(points, axis=0)))
    if not math.isfinite(scene_scale) or scene_scale <= 0:
        raise ValueError("COLMAP points have no finite nonzero scene extent")
    splats = _parameters(points, manifest, restored, torch)
    optimizers = {
        key: torch.optim.Adam(
            [
                {
                    "params": value,
                    "lr": TRAINING_PROTOCOL[f"{key}_lr"] * (scene_scale if key == "means" else 1.0),
                    "name": key,
                }
            ],
            eps=1e-15,
        )
        for key, value in splats.items()
    }
    scheduler = torch.optim.lr_scheduler.ExponentialLR(
        optimizers["means"], gamma=0.01 ** (1.0 / manifest.max_iterations)
    )
    strategy = strategy_class(
        cap_max=manifest.gaussian_cap,
        noise_lr=500000.0,
        refine_start_iter=500,
        refine_stop_iter=min(25000, manifest.max_iterations),
        refine_every=100,
        min_opacity=0.005,
    )
    strategy.check_sanity(splats, optimizers)
    strategy_state = strategy.initialize_state() if restored is None else restored["strategy"]
    sampler = {"order": [], "cursor": 0} if restored is None else restored["sampler"]
    step = 0 if restored is None else restored["next_iteration"]
    if not isinstance(step, int) or not 0 <= step <= manifest.max_iterations:
        raise ValueError("checkpoint iteration lies outside the declared run")
    if restored is not None:
        restore_optimizers(restored, optimizers, scheduler)
    attempts = output / "attempts"
    attempts.mkdir(exist_ok=True)
    previous = [json.loads(p.read_text()) for p in attempts.glob("*.json")]
    complete_accounting = all(item.get("finished") is True for item in previous)
    prior_duration = sum(item["duration_seconds"] for item in previous)
    peak = max([item.get("peak_vram_bytes", 0) for item in previous] or [0])
    torch.cuda.reset_peak_memory_stats()
    started = _PROCESS_STARTED
    attempt_path = attempts / f"{time.time_ns()}.json"
    preempted = False

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal preempted
        preempted = True

    handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}

    def attempt(finished: bool) -> float:
        nonlocal peak
        torch.cuda.synchronize()
        duration = time.monotonic() - started
        peak = max(peak, torch.cuda.max_memory_allocated())
        _write_atomic(
            attempt_path,
            {
                "finished": finished,
                "duration_seconds": duration,
                "peak_vram_bytes": peak,
                "next_iteration": step,
                **identity,
            },
        )
        return prior_duration + duration

    def checkpoint() -> None:
        duration = attempt(False)
        save_checkpoint(
            checkpoints,
            identity=identity,
            step=step,
            splats=splats,
            optimizers=optimizers,
            scheduler=scheduler,
            strategy_state=strategy_state,
            sampler=sampler,
            duration_seconds=duration,
            peak_vram_bytes=peak,
        )

    images = DecodedImages(torch)
    attempt(False)
    try:
        while step < manifest.max_iterations:
            if sampler["cursor"] >= len(sampler["order"]):
                sampler = {"order": random.sample(train_indices, len(train_indices)), "cursor": 0}
            view = views[sampler["order"][sampler["cursor"]]]
            sampler["cursor"] += 1
            pixels = images.pixels(view)
            colors, _, info = _render(splats, view, step, torch)
            l1 = (colors - pixels).abs().mean()
            structural = 1 - ssim(
                colors.permute(0, 3, 1, 2), pixels.permute(0, 3, 1, 2), data_range=1.0
            )
            loss = 0.8 * l1 + 0.2 * structural
            loss = loss + 0.01 * splats["opacities"].sigmoid().mean()
            loss = loss + 0.01 * splats["scales"].exp().mean()
            if not torch.isfinite(loss):
                raise ValueError("training loss became non-finite")
            loss.backward()
            for optimizer in optimizers.values():
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
            scheduler.step()
            strategy.step_post_backward(
                splats, optimizers, strategy_state, step, info, lr=scheduler.get_last_lr()[0]
            )
            step += 1
            if len(splats["means"]) > manifest.gaussian_cap:
                raise ValueError("MCMC exceeded the manifest Gaussian cap")
            if step % manifest.checkpoint_every == 0 or preempted:
                checkpoint()
            if preempted:
                return 75
        checkpoint()
        metrics = evaluate(splats, views, points, step, output, images)
        _write_atomic(output / "metrics.json", {**metrics, **identity})
        exporter(**dict(splats.items()), format="ply", save_to=str(output / "accepted.ply"))
        duration = attempt(True)
        runtime.update(
            {
                "loaded_packages": loaded_packages(),
                "iterations_completed": step,
                "gaussian_count": len(splats["means"]),
                "duration_seconds": duration,
                "peak_vram_bytes": peak,
                "duration_accounting_complete": complete_accounting,
                "duration_scope": (
                    "sum-of-measured-run-process-attempts-including-startup-and-evaluation"
                ),
                "peak_vram_scope": "torch-cuda-max-memory-allocated-across-attempts",
                "split_sha256": _digest_file(split_path),
                "prepared_dataset_receipt_sha256": _digest_file(
                    output / "training" / "dataset.json"
                ),
                "ply_sha256": _digest_file(output / "accepted.ply"),
            }
        )
        _write_atomic(output / "runtime.json", runtime)
        return 0
    finally:
        attempt(True)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["train"])
    parser.add_argument("--profile", choices=[RUNNER_PROFILE], required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pose-receipt", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", choices=["auto"], required=True)
    args = parser.parse_args(argv)
    try:
        manifest = read_manifest(args.manifest)
        _verify_dataset_sources(manifest, args.dataset)
        selected_model = _verify_pose_receipt(manifest, args.pose_receipt, args.dataset)
        # Fail before importing CUDA-only gsplat on unsupported hosts.
        verify_runtime(manifest)
        return train(manifest, args.dataset, args.output, selected_model)
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        print(f"gsplat runner refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
