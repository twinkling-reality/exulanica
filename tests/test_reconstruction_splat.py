from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from exulanica.reconstruction.gsplat_protocol import TRAINING_PROTOCOL
from exulanica.reconstruction.pose import CommandResult
from exulanica.reconstruction.splat import SplatBuildManifest, run_gsplat_job

_SPARSE_FILES = {
    "0/cameras.bin": b"test-camera-model",
    "0/images.bin": b"test-image-poses",
    "0/points3D.bin": b"test-sparse-geometry",
}


def _pose_payload():
    return {
        "profile": "exulanica.colmap-pose-build/v1",
        "scene_ref": "room-1",
        "frames": [
            {"filename": "a.jpg", "sha256": hashlib.sha256(b"source-a").hexdigest()},
            {"filename": "b.jpg", "sha256": hashlib.sha256(b"source-b").hexdigest()},
        ],
    }


def _manifest(**changes) -> SplatBuildManifest:
    source_a = hashlib.sha256(b"source-a").hexdigest()
    source_b = hashlib.sha256(b"source-b").hexdigest()
    values = {
        "scene_ref": "room-1",
        "code_revision": "a" * 40,
        "pose_manifest_digest": hashlib.sha256(
            json.dumps(_pose_payload(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "source_sha256": (source_a, source_b),
        "gsplat_revision": "e" * 40,
        "execution_image": "registry.example/gsplat@sha256:" + "f" * 64,
        "dependency_inventory": ("gsplat", "torch"),
        "requested_gpu": "NVIDIA L40S",
        "max_iterations": 30_000,
        "checkpoint_every": 5_000,
        "gaussian_cap": 1_000_000,
        "heldout_every": 8,
        "heldout_source_sha256": (source_a,),
        "usd_per_gpu_hour": 0.749,
        "min_psnr": 20.0,
        "min_ssim": 0.7,
        "max_lpips": 0.3,
        "max_floaters_fraction": 0.05,
        "min_coverage_fraction": 0.85,
        "max_browser_bytes": 2_000_000,
    }
    values.update(changes)
    return SplatBuildManifest(**values)


class FakeRunner:
    def __init__(
        self,
        manifest: SplatBuildManifest,
        *,
        psnr: float = 28.0,
        preempt_once: bool = False,
    ):
        self.manifest = manifest
        self.psnr = psnr
        self.preempt_once = preempt_once
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command: tuple[str, ...], cwd: Path) -> CommandResult:
        self.calls.append(command)
        if command[0] == "exulanica-gsplat-scene-v1":
            output = Path(command[command.index("--output") + 1])
            if self.preempt_once:
                self.preempt_once = False
                checkpoint = output / "checkpoints"
                checkpoint.mkdir(parents=True)
                (checkpoint / "step-5000.pt").write_bytes(b"checkpoint")
                return CommandResult(75, "checkpointed", "", 10.0)
            (output / "accepted.ply").write_bytes(b"ply\n")
            (output / "runtime.json").write_text(
                json.dumps(
                    {
                        "profile": "exulanica.gsplat-scene-runner/v1",
                        "backend": "gsplat",
                        "manifest_digest": self.manifest.digest,
                        "duration_accounting_complete": True,
                        "training_protocol": TRAINING_PROTOCOL,
                        "ply_sha256": hashlib.sha256(b"ply\n").hexdigest(),
                        "gsplat_revision": self.manifest.gsplat_revision,
                        "loaded_packages": ["gsplat", "torch"],
                        "iterations_completed": self.manifest.max_iterations,
                        "duration_seconds": 3600.0,
                        "gpu": "NVIDIA L40S serial-redacted",
                        "cuda_version": "12.4",
                        "driver_version": "550.54",
                        "peak_vram_bytes": 8_000_000_000,
                    }
                ),
                encoding="utf-8",
            )
            (output / "metrics.json").write_text(
                json.dumps(
                    {
                        "profile": "exulanica.gsplat-quality/v1",
                        "manifest_digest": self.manifest.digest,
                        "heldout_views": 4,
                        "psnr": self.psnr,
                        "ssim": 0.86,
                        "lpips": 0.14,
                        "floaters_fraction": 0.02,
                        "coverage_fraction": 0.92,
                    }
                ),
                encoding="utf-8",
            )
            return CommandResult(0, "trained", "", 12.0)
        if command[-1] == "--version":
            return CommandResult(0, "splat-transform v3.3.3 (test fixture)", "", 1.0)
        Path(command[-1]).write_bytes(b"SOG-delivery")
        return CommandResult(0, "compressed", "", 2.0)


def _dataset(path: Path) -> Path:
    path.mkdir()
    images = path / "images"
    images.mkdir()
    (images / "a.jpg").write_bytes(b"source-a")
    (images / "b.jpg").write_bytes(b"source-b")
    (path / "sparse" / "0").mkdir(parents=True)
    for name, data in _SPARSE_FILES.items():
        (path / "sparse" / name).write_bytes(data)
    return path


def _pose_receipt(path: Path, manifest: SplatBuildManifest) -> Path:
    quality = {
        "accepted": True,
        "connected_model": "0",
        "artifact_inventory": [
            {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "byte_length": len(data)}
            for name, data in _SPARSE_FILES.items()
        ],
        "metric_scale_metres_per_unit": 0.25,
        "jointly_coregistered": True,
        "shared_metric_frame": True,
    }
    canonical = json.dumps(quality, sort_keys=True, separators=(",", ":")).encode()
    path.write_text(
        json.dumps(
            {
                "profile": "exulanica.colmap-pose-receipt/v2",
                "manifest": _pose_payload(),
                "manifest_digest": manifest.pose_manifest_digest,
                "quality_digest": hashlib.sha256(canonical).hexdigest(),
                "quality": quality,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_accepted_scene_is_compressed_once_and_reused_from_its_receipt(tmp_path):
    manifest = _manifest()
    fake = FakeRunner(manifest)
    dataset = _dataset(tmp_path / "dataset")
    first = run_gsplat_job(
        manifest,
        dataset_dir=dataset,
        pose_receipt=_pose_receipt(tmp_path / "pose.json", manifest),
        jobs_root=tmp_path / "jobs",
        executor=fake,
    )
    second = run_gsplat_job(
        manifest,
        dataset_dir=dataset,
        pose_receipt=tmp_path / "pose.json",
        jobs_root=tmp_path / "jobs",
        executor=fake,
    )
    assert first.status == "completed" and first.reused is False
    assert second.status == "completed" and second.reused is True
    assert first.quality is not None and first.quality.accepted is True
    assert first.quality.usd_cost == pytest.approx(0.749)
    assert first.quality.delivery_sha256 is not None
    assert len(fake.calls) == 3
    assert fake.calls[1][0] == "splat-transform"


def test_quality_failure_keeps_rung_three_and_never_builds_a_delivery_asset(tmp_path):
    manifest = _manifest()
    fake = FakeRunner(manifest, psnr=12.0)
    result = run_gsplat_job(
        manifest,
        dataset_dir=_dataset(tmp_path / "dataset"),
        pose_receipt=_pose_receipt(tmp_path / "pose.json", manifest),
        jobs_root=tmp_path / "jobs",
        executor=fake,
    )
    assert result.quality is not None and result.quality.accepted is False
    assert result.quality.fallback_rung == 3
    assert any("PSNR" in reason for reason in result.quality.reasons)
    assert len(fake.calls) == 1
    assert not (result.job_directory / "output" / "scene.sog").exists()


def test_preemption_is_distinct_from_failure_and_the_next_call_resumes(tmp_path):
    manifest = _manifest()
    fake = FakeRunner(manifest, preempt_once=True)
    dataset = _dataset(tmp_path / "dataset")
    interrupted = run_gsplat_job(
        manifest,
        dataset_dir=dataset,
        pose_receipt=_pose_receipt(tmp_path / "pose.json", manifest),
        jobs_root=tmp_path / "jobs",
        executor=fake,
    )
    resumed = run_gsplat_job(
        manifest,
        dataset_dir=dataset,
        pose_receipt=tmp_path / "pose.json",
        jobs_root=tmp_path / "jobs",
        executor=fake,
    )
    assert interrupted.status == "checkpointed"
    assert resumed.status == "completed"
    train_commands = [
        command for command in fake.calls if command[0] == "exulanica-gsplat-scene-v1"
    ]
    assert len(train_commands) == 2
    assert all(command[-1] == "auto" for command in train_commands)


@pytest.mark.parametrize(
    "blocked", ["diff-gaussian-rasterization", "diff_gaussian_rasterization", "gaussian-splatting"]
)
def test_the_blocked_inria_rasterizer_is_a_manifest_refusal(blocked):
    with pytest.raises(ValueError, match="blocked INRIA"):
        _manifest(dependency_inventory=("gsplat", blocked))


def test_runtime_package_inventory_is_checked_again_after_execution(tmp_path):
    manifest = _manifest()

    def tainted(command: tuple[str, ...], cwd: Path) -> CommandResult:
        result = FakeRunner(manifest)(command, cwd)
        if command[0] == "exulanica-gsplat-scene-v1":
            output = Path(command[command.index("--output") + 1])
            runtime = json.loads((output / "runtime.json").read_text(encoding="utf-8"))
            runtime["loaded_packages"].append("diff-gaussian-rasterization")
            (output / "runtime.json").write_text(json.dumps(runtime), encoding="utf-8")
        return result

    with pytest.raises(ValueError, match="blocked INRIA"):
        run_gsplat_job(
            manifest,
            dataset_dir=_dataset(tmp_path / "dataset"),
            pose_receipt=_pose_receipt(tmp_path / "pose.json", manifest),
            jobs_root=tmp_path / "jobs",
            executor=tainted,
        )


def test_a_declared_pose_digest_without_an_accepted_metric_receipt_cannot_start_training(tmp_path):
    manifest = _manifest()
    pose = _pose_receipt(tmp_path / "pose.json", manifest)
    receipt = json.loads(pose.read_text(encoding="utf-8"))
    receipt["quality"]["metric_scale_metres_per_unit"] = None
    pose.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="digest"):
        run_gsplat_job(
            manifest,
            dataset_dir=_dataset(tmp_path / "dataset"),
            pose_receipt=pose,
            jobs_root=tmp_path / "jobs",
            executor=FakeRunner(manifest),
        )


@pytest.mark.parametrize(
    ("key", "changed", "message"),
    [
        ("manifest_digest", "0" * 64, "exact build manifest"),
        ("duration_accounting_complete", False, "unclean interruption"),
        ("training_protocol", {}, "protocol differs"),
        ("ply_sha256", "0" * 64, "PLY bytes"),
        ("loaded_packages", ["torch"], "omits gsplat"),
        ("duration_seconds", -1, "duration must be positive"),
    ],
)
def test_runner_receipts_cannot_claim_unbound_or_incomplete_results(
    tmp_path, key, changed, message
):
    manifest = _manifest()

    def altered(command: tuple[str, ...], cwd: Path) -> CommandResult:
        result = FakeRunner(manifest)(command, cwd)
        if command[0] == "exulanica-gsplat-scene-v1":
            output = Path(command[command.index("--output") + 1])
            path = output / "runtime.json"
            runtime = json.loads(path.read_text())
            runtime[key] = changed
            path.write_text(json.dumps(runtime))
        return result

    with pytest.raises(ValueError, match=message):
        run_gsplat_job(
            manifest,
            dataset_dir=_dataset(tmp_path / "dataset"),
            pose_receipt=_pose_receipt(tmp_path / "pose.json", manifest),
            jobs_root=tmp_path / "jobs",
            executor=altered,
        )


def test_nonfinite_metric_scale_cannot_start_training(tmp_path):
    manifest = _manifest()
    path = _pose_receipt(tmp_path / "pose.json", manifest)
    receipt = json.loads(path.read_text())
    receipt["quality"]["metric_scale_metres_per_unit"] = float("inf")
    canonical = json.dumps(receipt["quality"], sort_keys=True, separators=(",", ":")).encode()
    receipt["quality_digest"] = hashlib.sha256(canonical).hexdigest()
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="measured metric"):
        run_gsplat_job(
            manifest,
            dataset_dir=_dataset(tmp_path / "dataset"),
            pose_receipt=path,
            jobs_root=tmp_path / "jobs",
            executor=FakeRunner(manifest),
        )


def test_valid_pose_receipt_cannot_authorize_another_sparse_camera_model(tmp_path):
    manifest = _manifest()
    dataset = _dataset(tmp_path / "dataset")
    pose = _pose_receipt(tmp_path / "pose.json", manifest)
    (dataset / "sparse/0/images.bin").write_bytes(b"alternate camera poses")
    with pytest.raises(ValueError, match="accepted pose artifact inventory"):
        run_gsplat_job(
            manifest, dataset_dir=dataset, pose_receipt=pose, jobs_root=tmp_path / "jobs"
        )


def test_changed_carried_pose_manifest_is_refused_before_training(tmp_path):
    manifest = _manifest()
    dataset = _dataset(tmp_path / "dataset")
    pose = _pose_receipt(tmp_path / "pose.json", manifest)
    receipt = json.loads(pose.read_text())
    receipt["manifest"]["frames"][0]["filename"] = "changed.jpg"
    pose.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="carried pose manifest"):
        run_gsplat_job(
            manifest, dataset_dir=dataset, pose_receipt=pose, jobs_root=tmp_path / "jobs"
        )


def test_original_hashes_under_other_filenames_cannot_change_pose_camera_correspondence(tmp_path):
    manifest = _manifest()
    dataset = _dataset(tmp_path / "dataset")
    pose = _pose_receipt(tmp_path / "pose.json", manifest)
    (dataset / "images/a.jpg").rename(dataset / "images/other.jpg")
    with pytest.raises(ValueError, match="filenames and source hashes"):
        run_gsplat_job(
            manifest, dataset_dir=dataset, pose_receipt=pose, jobs_root=tmp_path / "jobs"
        )


def test_nonmetric_optimization_acceptance_does_not_promote_recorded_rung(tmp_path):
    manifest = _manifest()
    dataset = _dataset(tmp_path / "dataset")
    pose = _pose_receipt(tmp_path / "pose.json", manifest)
    receipt = json.loads(pose.read_text())
    receipt["quality"]["metric_scale_metres_per_unit"] = None
    receipt["quality"]["jointly_coregistered"] = False
    receipt["quality"]["shared_metric_frame"] = False
    canonical = json.dumps(receipt["quality"], sort_keys=True, separators=(",", ":")).encode()
    receipt["quality_digest"] = hashlib.sha256(canonical).hexdigest()
    pose.write_text(json.dumps(receipt))
    result = run_gsplat_job(
        manifest,
        dataset_dir=dataset,
        pose_receipt=pose,
        jobs_root=tmp_path / "jobs",
        executor=FakeRunner(manifest),
    )
    assert result.quality.accepted is True
    assert result.quality.fallback_rung == 3
    assert "recorded-rung-is-independent" in result.quality.as_payload()["acceptance_scope"]


def test_heldout_split_must_name_predeclared_original_source_hashes():
    with pytest.raises(ValueError, match="proper subset"):
        _manifest(heldout_source_sha256=("f" * 64,))


def test_wrong_compressor_version_cannot_publish_delivery(tmp_path):
    manifest = _manifest()
    fake = FakeRunner(manifest)

    def wrong_version(command, cwd):
        if command[-1] == "--version":
            return CommandResult(0, "splat-transform v0.0.1", "", 1)
        return fake(command, cwd)

    result = run_gsplat_job(
        manifest,
        dataset_dir=_dataset(tmp_path / "dataset"),
        pose_receipt=_pose_receipt(tmp_path / "pose.json", manifest),
        jobs_root=tmp_path / "jobs",
        executor=wrong_version,
    )
    assert result.status == "failed"
    assert "compressor" in result.reason
    assert not (result.job_directory / "output/scene.sog").exists()
