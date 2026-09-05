"""Actual CPU optimizer continuation and fail-closed trainer boundary tests (no DB)."""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import sys
from functools import wraps
from pathlib import Path

import pytest
from exulanica.reconstruction import gsplat_runner
from exulanica.reconstruction.gsplat_runner import (
    capture_rng,
    dataset_digest,
    load_checkpoint,
    read_manifest,
    restore_optimizers,
    save_checkpoint,
    seed_values,
    verify_runtime,
)

from test_reconstruction_splat import _manifest


def _isolated_torch(test):
    """Match worker isolation: Torch and native COLMAP use incompatible macOS OpenMP builds."""

    @wraps(test)
    def execute(*args, **kwargs):
        if os.environ.get("EXULANICA_TORCH_TEST_CHILD") == test.__name__:
            return test(*args, **kwargs)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--noconftest",
                f"{Path(__file__).resolve()}::{test.__name__}",
            ],
            env={**os.environ, "EXULANICA_TORCH_TEST_CHILD": test.__name__},
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    return execute


def _state():
    import torch

    splats = torch.nn.ParameterDict({"means": torch.nn.Parameter(torch.tensor([0.3, -0.4]))})
    optimizers = {"means": torch.optim.Adam([splats["means"]], lr=0.02)}
    scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizers["means"], gamma=0.91)
    return splats, optimizers, scheduler


def _step(splats, optimizers, scheduler, strategy):
    import numpy as np
    import torch

    # Three real RNG streams affect both samples and optimization. State restoration must
    # reproduce every one, not only parameter bytes. The strategy is deliberately stateful.
    target = torch.randn(2) + random.random() + float(np.random.random())
    loss = ((splats["means"] - target) ** 2).sum()
    loss.backward()
    optimizers["means"].step()
    optimizers["means"].zero_grad(set_to_none=True)
    scheduler.step()
    strategy["updates"] += 1
    strategy["last_target"] = target.clone()


@_isolated_torch
def test_actual_adam_resume_reproduces_uninterrupted_training_and_rng(tmp_path):
    import numpy as np
    import torch

    random.seed(71)
    np.random.seed(71)
    torch.manual_seed(71)
    splats, optimizers, scheduler = _state()
    strategy = {"updates": 0, "last_target": torch.zeros(2)}
    for _ in range(5):
        _step(splats, optimizers, scheduler, strategy)
    identity = {"manifest_digest": "a" * 64, "dataset_digest": "b" * 64}
    save_checkpoint(
        tmp_path,
        identity=identity,
        step=5,
        splats=splats,
        optimizers=optimizers,
        scheduler=scheduler,
        strategy_state=strategy,
        sampler={"order": [2, 0, 1], "cursor": 1},
        duration_seconds=1.5,
        peak_vram_bytes=0,
    )
    for _ in range(7):
        _step(splats, optimizers, scheduler, strategy)
    expected = splats["means"].detach().clone()
    expected_rng = capture_rng()
    state = load_checkpoint(tmp_path, identity=identity)
    assert state is not None and state["next_iteration"] == 5
    resumed_splats, resumed_opts, resumed_scheduler = _state()
    resumed_splats.load_state_dict(state["splats"])
    restore_optimizers(state, resumed_opts, resumed_scheduler)
    assert state["sampler"] == {"order": [2, 0, 1], "cursor": 1}
    for _ in range(7):
        _step(resumed_splats, resumed_opts, resumed_scheduler, state["strategy"])
    assert torch.equal(expected, resumed_splats["means"])
    assert state["strategy"]["updates"] == 12
    assert torch.equal(state["strategy"]["last_target"], strategy["last_target"])
    actual_rng = capture_rng()
    assert actual_rng["python"] == expected_rng["python"]
    assert actual_rng["numpy"] == expected_rng["numpy"]
    assert torch.equal(actual_rng["torch"], expected_rng["torch"])
    assert resumed_scheduler.get_last_lr() == scheduler.get_last_lr()
    assert resumed_scheduler.state_dict() == scheduler.state_dict()


def _checkpoint(path):
    splats, optimizers, scheduler = _state()
    identity = {"manifest_digest": "a" * 64, "dataset_digest": "b" * 64}
    save_checkpoint(
        path,
        identity=identity,
        step=1,
        splats=splats,
        optimizers=optimizers,
        scheduler=scheduler,
        strategy_state={"updates": 1},
        sampler={"order": [], "cursor": 0},
        duration_seconds=1,
        peak_vram_bytes=0,
    )
    return identity


@_isolated_torch
def test_resume_refuses_changed_camera_model_identity(tmp_path):
    identity = _checkpoint(tmp_path)
    with pytest.raises(ValueError, match="identity"):
        load_checkpoint(tmp_path, identity={**identity, "dataset_digest": "c" * 64})


@_isolated_torch
def test_resume_refuses_corrupt_checkpoint_bytes(tmp_path):
    identity = _checkpoint(tmp_path)
    pointer = json.loads((tmp_path / "latest.json").read_text())
    (tmp_path / pointer["file"]).write_bytes(b"not the saved optimizer")
    with pytest.raises(ValueError, match="digest"):
        load_checkpoint(tmp_path, identity=identity)


@_isolated_torch
def test_resume_refuses_evaluation_only_parameter_checkpoint(tmp_path):
    import torch

    identity = _checkpoint(tmp_path)
    pointer = json.loads((tmp_path / "latest.json").read_text())
    path = tmp_path / pointer["file"]
    state = torch.load(path, weights_only=True)
    del state["optimizers"]
    torch.save(state, path)
    pointer["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / "latest.json").write_text(json.dumps(pointer))
    with pytest.raises(ValueError, match="complete resumable"):
        load_checkpoint(tmp_path, identity=identity)


def test_dataset_checkpoint_identity_binds_sparse_model_bytes(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a.png").write_bytes(b"source")
    (tmp_path / "sparse").mkdir()
    sparse = tmp_path / "sparse" / "points3D.bin"
    sparse.write_bytes(b"first camera model")
    original = dataset_digest(tmp_path)
    sparse.write_bytes(b"another camera model")
    assert dataset_digest(tmp_path) != original


def test_manifest_refuses_changed_metric_definition_before_training(tmp_path):
    path = tmp_path / "manifest.json"
    payload = _manifest().as_payload()
    payload["training_protocol"] = {"coverage": "all-pixels-by-assertion"}
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="changed training protocol"):
        read_manifest(path)


@_isolated_torch
@_isolated_torch
def test_seed_gaussians_are_single_precision_before_any_device_transfer():
    """The first real CUDA iteration refused Double scales beside Float means (2026-09-05)."""
    import numpy as np
    import torch

    rng = np.random.default_rng(7)
    points = rng.normal(size=(64, 3)).astype(np.float64)  # what a caller may still hand over
    values = seed_values(points, _manifest(), torch)
    assert set(values) == {"means", "scales", "quats", "opacities", "sh0", "shN"}
    assert {value.dtype for value in values.values()} == {torch.float32}
    assert values["means"].shape == (64, 3) and values["scales"].shape == (64, 3)
    assert torch.isfinite(values["scales"]).all()


@_isolated_torch
def test_decoded_image_cache_returns_exact_pixels_and_decodes_each_view_once(tmp_path):
    """Per-iteration JPEG decoding starved the GPU on the first real run (2026-09-05)."""
    import numpy as np
    import torch
    from PIL import Image

    rng = np.random.default_rng(3)
    views = []
    for name in ("a", "b"):
        path = tmp_path / f"{name}.png"
        Image.fromarray(rng.integers(0, 256, size=(6, 8, 3), dtype=np.uint8)).save(path)
        views.append({"path": path})
    decodes = 0
    original = gsplat_runner.decode_rgb_uint8

    def counting(view):
        nonlocal decodes
        decodes += 1
        return original(view)

    gsplat_runner.decode_rgb_uint8 = counting
    try:
        cache = gsplat_runner.DecodedImages(torch, device="cpu")
        first = cache.pixels(views[0])
        again = cache.pixels(views[0])
        other = cache.pixels(views[1])
        expected = torch.from_numpy(original(views[0]).astype(np.float32) / 255.0).unsqueeze(0)
        assert torch.equal(first, expected) and torch.equal(again, expected)
        assert first.dtype == torch.float32 and first.shape == (1, 6, 8, 3)
        assert not torch.equal(other, expected)
        assert decodes == 2
        first.mul_(0)  # a caller mutating its tensor must not touch the cached bytes
        assert torch.equal(cache.pixels(views[0]), expected)
        uncached = gsplat_runner.DecodedImages(torch, budget_bytes=0, device="cpu")
        assert torch.equal(uncached.pixels(views[0]), expected)
        assert torch.equal(uncached.pixels(views[0]), expected)
        assert decodes == 4
    finally:
        gsplat_runner.decode_rgb_uint8 = original


def test_cpu_host_cannot_claim_cuda_runtime(monkeypatch):
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="NVIDIA CUDA GPU"):
        verify_runtime(_manifest())


def test_container_uses_exact_digest_and_only_declared_mounts(tmp_path):
    from exulanica.reconstruction.gsplat_container import container_command

    manifest = _manifest()
    command = container_command(
        manifest,
        manifest_path=tmp_path / "manifest.json",
        pose_receipt=tmp_path / "pose.json",
        dataset=tmp_path / "dataset",
        output=tmp_path / "output",
    )
    assert manifest.execution_image in command
    assert command[command.index("--network") + 1] == "none"
    mounts = [command[index + 1] for index, value in enumerate(command) if value == "--mount"]
    assert len(mounts) == 4
    assert sum(mount.endswith(",readonly") for mount in mounts) == 3
    assert command[-2:] == ("--resume", "auto")
    assert "--pose-receipt" in command
    assert "--read-only" in command
