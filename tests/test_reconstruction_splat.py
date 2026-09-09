from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from exulanica.reconstruction.gsplat_protocol import TRAINING_PROTOCOL
from exulanica.reconstruction.pose import CommandResult
from exulanica.reconstruction.splat import (
    SplatBuildManifest,
    masked_training_binding,
    run_gsplat_job,
    verify_masked_training_sources,
)

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
            # The real 3.3.3 CLI writes its banner to stderr; the fixture does the same.
            return CommandResult(0, "", "splat-transform v3.3.3 (test fixture)", 1.0)
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
    # Every SH band is delivered; the device defaults to the CPU path the tests can run.
    assert fake.calls[2][:5] == ("splat-transform", "--no-tty", "--overwrite", "-g", "cpu")
    assert "-H" not in fake.calls[2]


def test_the_compressor_device_is_passed_verbatim_and_recorded(tmp_path):
    """MEASURED 2026-09-06: k-means over one million Gaussians took hours on a CPU core and
    under a minute on the training GPU; the operator's device choice must be auditable."""
    manifest = _manifest()
    fake = FakeRunner(manifest)

    result = run_gsplat_job(
        manifest,
        dataset_dir=_dataset(tmp_path / "dataset"),
        pose_receipt=_pose_receipt(tmp_path / "pose.json", manifest),
        jobs_root=tmp_path / "jobs",
        compressor_gpu="0",
        executor=fake,
    )

    assert result.status == "completed" and result.quality is not None
    assert fake.calls[2][3:5] == ("-g", "0")
    attempt = json.loads((result.job_directory / "compression-attempt.json").read_text())
    assert attempt["gpu_device"] == "0"
    assert attempt["command"][3:5] == ["-g", "0"]
    assert "v3.3.3" in attempt["version_output"]


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


def test_a_failed_runner_names_its_last_stderr_line_and_retains_the_tail(tmp_path):
    """A digest of stderr left the first real failure nameless; the operator needs the words."""
    manifest = _manifest()
    stderr = (
        "Traceback (most recent call last):\n  ...\n"
        "gsplat runner refused: expected scalar type Float but found Double\n"
    )
    calls: list[tuple[str, ...]] = []

    def failing(command: tuple[str, ...], cwd: Path) -> CommandResult:
        calls.append(command)
        return CommandResult(1, "", stderr, 5.0)

    result = run_gsplat_job(
        manifest,
        dataset_dir=_dataset(tmp_path / "dataset"),
        pose_receipt=_pose_receipt(tmp_path / "pose.json", manifest),
        jobs_root=tmp_path / "jobs",
        executor=failing,
    )
    assert result.status == "failed"
    assert result.reason == (
        "gsplat runner exited 1: gsplat runner refused: expected scalar type Float but found "
        "Double; rung 3 fallback"
    )
    attempt = json.loads((result.job_directory / "train-attempt.json").read_text())
    assert attempt["returncode"] == 1
    assert attempt["stderr_tail"].endswith("found Double\n")
    assert attempt["stderr_sha256"] == hashlib.sha256(stderr.encode()).hexdigest()
    assert len(calls) == 1 and calls[0][0] == "exulanica-gsplat-scene-v1"


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


# --------------------------------------------------------------------------------------------
# The masked-source remap, at the one layer that can check it with no database anywhere near.
# `source_sha256` here is the masked space: the bytes the dataset holds and the trainer reads.
# The remap says which photograph each of those replaced, and every rule below exists because
# some way of getting that wrong would otherwise reach a render without anything noticing.
# --------------------------------------------------------------------------------------------

_CAPTURE = "00000000-0000-4000-8000-000000000001"


def _masked_manifest(**changes) -> SplatBuildManifest:
    """One member hidden: its photograph is `original`, and the dataset holds `masked` instead."""
    original = hashlib.sha256(b"the-photograph").hexdigest()
    masked = hashlib.sha256(b"source-a").hexdigest()
    values = {
        "masked_source_remap": ((_CAPTURE, original, masked),),
        "heldout_source_sha256": (masked,),
    }
    values.update(changes)
    return _manifest(**values)


def test_a_masked_build_withholds_the_derivative_and_records_the_photograph_it_replaced():
    manifest = _masked_manifest()
    original = hashlib.sha256(b"the-photograph").hexdigest()
    assert manifest.heldout_original_source_sha256 == (original,)
    parameters = manifest.as_payload()["parameters"]
    assert parameters["masked_source_remap"] == {
        _CAPTURE: {
            "source_sha256": original,
            "masked_source_sha256": hashlib.sha256(b"source-a").hexdigest(),
        }
    }
    # A build with nobody hidden keeps the payload, and therefore the digest, it always had.
    plain = _manifest()
    assert "masked_source_remap" not in plain.as_payload()["parameters"]
    assert plain.heldout_original_source_sha256 == plain.heldout_source_sha256
    assert masked_training_binding(plain) == {}


def test_an_original_among_the_training_sources_is_refused():
    """The failure this exists to prevent: a hidden person's photograph reaching the trainer."""
    with pytest.raises(ValueError, match="original bytes are among the training sources"):
        _masked_manifest(
            masked_source_remap=(
                (
                    _CAPTURE,
                    hashlib.sha256(b"source-b").hexdigest(),
                    hashlib.sha256(b"source-a").hexdigest(),
                ),
            ),
            heldout_source_sha256=(hashlib.sha256(b"source-a").hexdigest(),),
        )


def test_a_derivative_outside_the_training_sources_is_refused():
    with pytest.raises(ValueError, match="not among the training sources"):
        _masked_manifest(masked_source_remap=((_CAPTURE, "c" * 64, "d" * 64),))


@pytest.mark.parametrize(
    ("remap", "message"),
    [
        ((("not-a-capture", "c" * 64, hashlib.sha256(b"source-a").hexdigest()),), "capture ref"),
        (((_CAPTURE, "c" * 64, "c" * 64),), "cannot be the original bytes"),
        (
            (
                (_CAPTURE, "c" * 64, hashlib.sha256(b"source-a").hexdigest()),
                (_CAPTURE, "d" * 64, hashlib.sha256(b"source-b").hexdigest()),
            ),
            "twice",
        ),
        (
            (
                ("00000000-0000-4000-8000-000000000002", "d" * 64, hashlib.sha256(b"source-b")
                 .hexdigest()),
                (_CAPTURE, "c" * 64, hashlib.sha256(b"source-a").hexdigest()),
            ),
            "ordered by capture reference",
        ),
    ],
)
def test_a_malformed_remap_is_refused_by_the_manifest(remap, message):
    with pytest.raises(ValueError, match=message):
        _masked_manifest(masked_source_remap=remap)


def test_the_staged_dataset_is_re_derived_before_a_view_is_loaded(tmp_path):
    """Hash agreement is not file agreement, and this is the last point that can tell them apart."""
    manifest = _masked_manifest()
    dataset = _dataset(tmp_path / "dataset")
    verify_masked_training_sources(manifest, dataset)
    (dataset / "images" / "a.jpg").write_bytes(b"the-photograph")
    with pytest.raises(ValueError, match="holds an original"):
        verify_masked_training_sources(manifest, dataset)
    (dataset / "images" / "a.jpg").write_bytes(b"neither one nor the other")
    with pytest.raises(ValueError, match="declared masked derivative is not among the staged"):
        verify_masked_training_sources(manifest, dataset)


def test_a_masked_manifest_round_trips_through_the_runner_reader(tmp_path):
    from exulanica.reconstruction.gsplat_runner import read_manifest

    manifest = _masked_manifest()
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest.as_payload()))
    assert read_manifest(path) == manifest
    payload = manifest.as_payload()
    payload["parameters"]["masked_source_remap"][_CAPTURE].pop("source_sha256")
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="remap entry is malformed"):
        read_manifest(path)


def test_a_masked_build_runs_through_the_controller_and_binds_its_remap(tmp_path):
    """The controller's existing source check is already what forbids a staged original.

    `_verify_dataset_sources` proves the dataset bytes are exactly `source_sha256`, and the
    manifest has already refused any remap whose originals appear there, so the two together
    leave no way for a hidden member's photograph to be in this directory. The runner repeats the
    statement against files immediately before loading a view; that repetition is deliberate.
    """
    manifest = _masked_manifest()
    result = run_gsplat_job(
        manifest,
        dataset_dir=_dataset(tmp_path / "dataset"),
        pose_receipt=_pose_receipt(tmp_path / "pose.json", manifest),
        jobs_root=tmp_path / "jobs",
        executor=FakeRunner(manifest),
    )
    assert result.status == "completed" and result.quality.accepted is True
    recorded = json.loads((result.job_directory / "manifest.json").read_bytes())
    assert recorded["parameters"]["masked_source_remap"][_CAPTURE]["masked_source_sha256"] == (
        hashlib.sha256(b"source-a").hexdigest()
    )
    assert result.manifest_digest != _manifest().digest


def test_the_staged_check_runs_before_rectification_and_before_any_view_is_loaded():
    """An ordering guard, read out of the source rather than executed.

    `_train_locked` needs torch, numpy and pycolmap in one process, which this host cannot give
    it, so the ordering that makes the check meaningful has no executable test here. Reading the
    call sites is weaker than running them and stronger than nothing.

    Both comparisons matter and the first is the one worth having. `prepare_dataset` decodes every
    staged image and writes it back into the job directory, so a check that ran after it would let
    a leaked original be re-encoded into retained scratch before anything refused the build. The
    split receipt binding is asserted here for the same reason: the runner's own call site is
    unexecuted on this host, so its absence would otherwise be invisible.
    """
    import inspect

    from exulanica.reconstruction import gsplat_runner

    body = inspect.getsource(gsplat_runner._train_locked)
    check = body.index("verify_masked_training_sources(manifest, dataset)")
    assert check < body.index("prepare_dataset(")
    assert check < body.index("load_dataset(")
    assert "masked_training_binding(manifest)" in body


def test_a_remap_that_collapses_or_duplicates_is_refused_by_the_manifest():
    """Two hidden members must not share an original or a derivative.

    Sharing a derivative would silently shrink the held-out set; sharing an original would mean
    one photograph was masked into two different sets of bytes, which no selection can produce.
    """
    second = "00000000-0000-4000-8000-000000000002"
    source_a = hashlib.sha256(b"source-a").hexdigest()
    source_b = hashlib.sha256(b"source-b").hexdigest()
    for remap in (
        ((_CAPTURE, "c" * 64, source_a), (second, "c" * 64, source_b)),
        ((_CAPTURE, "c" * 64, source_a), (second, "d" * 64, source_a)),
    ):
        with pytest.raises(ValueError, match="twice"):
            _masked_manifest(masked_source_remap=remap, heldout_source_sha256=(source_a,))


def test_a_non_string_digest_in_a_remap_is_a_refusal_and_not_a_traceback():
    """The runner's `main` catches ValueError; a TypeError would reach an operator as a trace."""
    with pytest.raises(ValueError, match="capture and two hashes"):
        _masked_manifest(masked_source_remap=((_CAPTURE, 7, hashlib.sha256(b"source-a")
                                               .hexdigest()),))


def test_a_held_out_source_missing_from_the_staged_dataset_is_refused(tmp_path):
    """The third clause: the split may not withhold bytes the dataset does not contain."""
    manifest = _masked_manifest(
        heldout_source_sha256=(hashlib.sha256(b"source-b").hexdigest(),),
    )
    dataset = _dataset(tmp_path / "dataset")
    verify_masked_training_sources(manifest, dataset)
    (dataset / "images" / "b.jpg").write_bytes(b"some other training image")
    with pytest.raises(ValueError, match="held-out source does not resolve"):
        verify_masked_training_sources(manifest, dataset)


def test_an_unmasked_build_does_no_staged_work_at_all(tmp_path, monkeypatch):
    """The claim that a corpus with nobody in it pays nothing for this, made checkable."""
    from exulanica.reconstruction import splat

    def refuse(_path):
        raise AssertionError("an unmasked build hashed a staged image")

    monkeypatch.setattr(splat, "_digest_file", refuse)
    verify_masked_training_sources(_manifest(), tmp_path / "absent")
