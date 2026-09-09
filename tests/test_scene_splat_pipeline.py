"""Production scene publication with a named scripted trainer; no CUDA quality claim."""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import io
import json
import math
import struct
import uuid
import zipfile
from pathlib import Path

import pytest
from exulanica.evidence.blob import BlobId
from exulanica.graph import read_snapshot
from exulanica.graph.scene_geometry import read_scene_geometry
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.scene_reconstruction import SceneReconstructionProcessor
from exulanica.ingest.scene_selection import enqueue_exact_scene_reconstruction
from exulanica.ingest.scene_splat import (
    SceneSplatRequest,
    evaluation_bundle,
    gaussian_ply_bounds,
    stage_training_dataset,
    training_dataset_directory,
)
from exulanica.reconstruction.gsplat_runner import read_manifest
from exulanica.reconstruction.pose import CommandResult
from exulanica.reconstruction.splat import masked_training_binding
from exulanica.store.local import LocalContentAddressedStore

from conftest import CountingVisionModel, write_photo, write_point_map
from test_reconstruction_splat import FakeRunner
from test_scene_reconstruction_pipeline import FakeColmap, _numeric_point_map


def request(heldout: tuple[str, ...]) -> SceneSplatRequest:
    return SceneSplatRequest(
        execution_image="test-only-cuda@sha256:" + "f" * 64,
        requested_gpu="NVIDIA test fixture",
        dependency_inventory=("gsplat", "torch"),
        heldout_source_sha256=heldout,
        max_iterations=1000,
        checkpoint_every=500,
        gaussian_cap=1000,
        usd_per_gpu_hour_millionths=0,
        min_psnr_millionths=20_000_000,
        min_ssim_millionths=700_000,
        max_lpips_millionths=300_000,
        max_floaters_fraction_millionths=50_000,
        min_coverage_fraction_millionths=850_000,
        max_browser_bytes=2_000_000,
    )


def ply() -> bytes:
    header = (
        b"ply\nformat binary_little_endian 1.0\nelement vertex 1\n"
        b"property float x\nproperty float y\nproperty float z\n"
        b"property float scale_0\nproperty float scale_1\nproperty float scale_2\n"
        b"end_header\n"
    )
    return header + struct.pack("<6f", 1, 2, 3, math.log(0.5), math.log(0.5), math.log(0.5))


class ScriptedTrainer:
    """Exercises the real controller's receipt checks, never represents a measured GPU run."""

    def __init__(self, *, preempt_once=False, reject=False, withdraw=None, measurement_epoch=1):
        self.preempt_once = preempt_once
        self.reject = reject
        self.withdraw = withdraw
        self.runner = None
        self.calls = []
        self.measurement_epoch = measurement_epoch

    def __call__(self, command, cwd):
        self.calls.append(command)
        if command[0] == "exulanica-gsplat-scene-v1":
            manifest = read_manifest(Path(command[command.index("--manifest") + 1]))
            self.runner = FakeRunner(
                manifest, psnr=12 if self.reject else 28, preempt_once=self.preempt_once
            )
            self.preempt_once = False
            result = self.runner(command, cwd)
            if self.withdraw:
                callback, self.withdraw = self.withdraw, None
                callback()
            if result.returncode == 0:
                output = Path(command[command.index("--output") + 1])
                (output / "accepted.ply").write_bytes(ply())
                runtime = json.loads((output / "runtime.json").read_text())
                runtime["ply_sha256"] = hashlib.sha256(ply()).hexdigest()
                runtime["duration_seconds"] *= self.measurement_epoch
                dataset = Path(command[command.index("--dataset") + 1])
                (output / "training").mkdir(exist_ok=True)
                companions = {
                    "split.json": {
                        "notice": "SYNTHETIC SCRIPTED TRAINER SPLIT",
                        "heldout_source_sha256": list(manifest.heldout_source_sha256),
                        "training_source_sha256": sorted(
                            set(manifest.source_sha256) - set(manifest.heldout_source_sha256)
                        ),
                        # The real runner writes this block from the same helper, so what the
                        # retained bundle binds here is the shape production binds, not a shape
                        # the fixture invented.
                        **masked_training_binding(manifest),
                    },
                    "training/dataset.json": {
                        "notice": "SYNTHETIC SCRIPTED TRAINER PREPARATION",
                        "rectified": False,
                        "images": [
                            {
                                "name": path.name,
                                "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            }
                            for path in sorted((dataset / "images").iterdir())
                        ],
                    },
                }
                for name, companion in companions.items():
                    data = json.dumps(companion, sort_keys=True).encode()
                    (output / name).write_bytes(data)
                    binding = (
                        "split_sha256"
                        if name == "split.json"
                        else "prepared_dataset_receipt_sha256"
                    )
                    runtime[binding] = hashlib.sha256(data).hexdigest()
                (output / "runtime.json").write_text(json.dumps(runtime))
                source = next(
                    path
                    for path in (dataset / "images").iterdir()
                    if hashlib.sha256(path.read_bytes()).hexdigest()
                    == manifest.heldout_source_sha256[0]
                )
                from PIL import Image

                (output / "heldout").mkdir(exist_ok=True)
                render = output / "heldout/view-00000.png"
                with Image.open(source) as original:
                    original.convert("RGB").save(render)
                    width, height = original.size
                metrics = json.loads((output / "metrics.json").read_text())
                metrics.update(
                    heldout_views=1,
                    per_view=[
                        {
                            "source_name": source.name,
                            "source_sha256": manifest.heldout_source_sha256[0],
                            "reference_pixels_sha256": manifest.heldout_source_sha256[0],
                            "width": width,
                            "height": height,
                            "render": "heldout/view-00000.png",
                            "render_sha256": hashlib.sha256(render.read_bytes()).hexdigest(),
                            "fixture_notice": "SCRIPTED TRAINER; NO MEASURED GPU QUALITY",
                        }
                    ],
                )
                (output / "metrics.json").write_text(json.dumps(metrics))
            return result
        assert self.runner is not None
        result = self.runner(command, cwd)
        if command[-1] != "--version" and self.measurement_epoch > 1:
            output = Path(command[-1])
            output.write_bytes(output.read_bytes() + str(self.measurement_epoch).encode())
        return result


def queued(repository, tmp_path, *, frozen_split=False):
    store = LocalContentAddressedStore(tmp_path / "store")
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())
    photos = tmp_path / "photos"
    photos.mkdir()
    captures, hashes, blobs = [], [], []
    for index in range(4):
        path = write_photo(
            photos, f"{index}.jpg", when=f"2026:09:05 12:0{index}:00", size=(160 + index, 100)
        )
        outcome = pipeline.ingest_file(path)
        assert outcome.error is None and outcome.capture_id is not None
        captures.append(outcome.capture_id)
        blob = BlobId.of_bytes(path.read_bytes())
        blobs.append(blob)
        hashes.append(blob.hex)
    for index, blob in enumerate(blobs):
        screening_id = None
        if frozen_split:
            from exulanica.ingest.privacy import (
                authorize_synthetic_capture,
                record_synthetic_exemption,
            )

            authorization = authorize_synthetic_capture(
                repository,
                capture_id=captures[index],
                actor=uuid.uuid4(),
                generator_manifest={
                    "profile": "exulanica.synthetic-training-split-test/v1",
                    "notice": "SYNTHETIC TRAINING SPLIT REGRESSION",
                },
                authorization_scope={
                    "source_manifest": {
                        "profile": "exulanica.synthetic-split-test/v1",
                        "evaluation_split": {
                            "heldout_sha256": [hashes[0]],
                            "training_sha256": hashes[1:],
                        },
                    }
                },
                authorized_at=dt.datetime.now(dt.UTC),
            )
            screening_id = record_synthetic_exemption(
                repository,
                authorization_id=authorization.authorization_id,
                screened_at=dt.datetime.now(dt.UTC),
            ).screening_id
        write_point_map(
            repository,
            store,
            blob,
            payload=_numeric_point_map(index),
            privacy_screening_id=screening_id,
        )
    config = request((hashes[0],))
    selected = enqueue_exact_scene_reconstruction(
        repository,
        captures,
        actor=uuid.uuid4(),
        purpose="scripted trainer publication regression",
        authorized_at=dt.datetime.now(dt.UTC),
        splat_training=config,
    )
    assert selected is not None
    return store, captures, selected, config


def processor(repository, store, tmp_path, trainer):
    return SceneReconstructionProcessor(
        repository,
        store,
        tmp_path / "scratch",
        code_revision="a" * 40,
        execution_image="pose-test@sha256:" + "b" * 64,
        colmap_version="numeric scripted fixture",
        executor=FakeColmap(registered=4, camera_spacing=5),
        splat_executor=trainer,
        retry_delay_seconds=0,
    )


def test_training_request_roundtrips_without_implicit_spending_or_split_changes():
    config = request(("a" * 64,))
    assert SceneSplatRequest.from_payload(config.as_payload()) == config
    config.validate_sources(("a" * 64, "b" * 64, "c" * 64, "d" * 64))
    with pytest.raises(ValueError, match="subset"):
        config.validate_sources(("b" * 64, "c" * 64, "d" * 64, "e" * 64))
    with pytest.raises(ValueError, match="integer"):
        dataclasses.replace(config, usd_per_gpu_hour_millionths=0.5)


def test_admitted_split_requires_the_complete_identical_manifest():
    sources = tuple(char * 64 for char in "abcd")
    config = request((sources[0],))
    manifest = {
        "evaluation_split": {"heldout_sha256": [sources[0]], "training_sha256": list(sources[1:])}
    }
    config.validate_admitted_sources(sources, [None] * 4)
    config.validate_admitted_sources(sources, [manifest] * 4)
    with pytest.raises(ValueError, match="every admitted reference"):
        config.validate_admitted_sources(sources, [manifest] * 3 + [None])
    with pytest.raises(ValueError, match="disagree"):
        config.validate_admitted_sources(sources, [manifest] * 3 + [{**manifest, "other": True}])
    with pytest.raises(ValueError, match="frozen held-out"):
        config.validate_admitted_sources(
            sources,
            [
                {
                    "evaluation_split": {
                        "heldout_sha256": [sources[0]],
                        "training_sha256": list(sources[1:3]),
                    }
                }
            ]
            * 4,
        )


def test_unconfirmed_exit_retains_a_cleanup_guard_even_if_launcher_did_not_write_it(tmp_path):
    import sys

    from exulanica.ingest.scene_splat import ContainerCleanupUnconfirmed, cancellable_executor

    with pytest.raises(ContainerCleanupUnconfirmed):
        cancellable_executor(lambda: False)(
            (sys.executable, "-c", "raise SystemExit(76)"), tmp_path
        )
    assert (tmp_path / "container-cleanup-required.json").exists()


def test_cancellation_check_failure_stops_the_live_subprocess_before_propagating(tmp_path):
    import os
    import signal
    import sys

    from exulanica.ingest.scene_splat import cancellable_executor

    script = (
        "import os,signal,time,pathlib\n"
        "def stop(*args):\n"
        " pathlib.Path('confirmed').write_text('stopped')\n"
        " raise SystemExit(0)\n"
        "signal.signal(signal.SIGTERM,stop)\n"
        "pathlib.Path('ready').write_text(str(os.getpid()))\n"
        "while True: time.sleep(.01)\n"
    )

    def lost_database():
        if (tmp_path / "ready").exists():
            raise RuntimeError("scripted authorization connection failure")
        return False

    try:
        with pytest.raises(RuntimeError, match="authorization connection failure"):
            cancellable_executor(lost_database)((sys.executable, "-c", script), tmp_path)
        assert (tmp_path / "confirmed").exists()
    finally:
        if (tmp_path / "ready").exists() and not (tmp_path / "confirmed").exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int((tmp_path / "ready").read_text()), signal.SIGKILL)


def test_missing_authoritative_source_during_training_cannot_publish_cached_inputs(
    repository, tmp_path
):
    store, captures, _selected, _config = queued(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)

    def lose_source():
        source = repository.capture(captures[1]).blob_id
        (store.root / store.key_for(source)).unlink()

    result = processor(repository, store, tmp_path, ScriptedTrainer(withdraw=lose_source)).process(
        claimed
    )
    assert result.status == "failed" and "source is absent" in result.message
    assert not read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes


def test_dataset_copy_resumes_missing_files_but_refuses_changed_bytes(tmp_path):
    sources, sparse, target = tmp_path / "sources", tmp_path / "sparse", tmp_path / "target"
    sources.mkdir()
    sparse.mkdir()
    (sources / "a.jpg").write_bytes(b"exact image")
    (sparse / "cameras.txt").write_bytes(b"exact cameras")
    stage_training_dataset(sources, sparse, target)
    (target / "images" / "a.jpg").unlink()
    stage_training_dataset(sources, sparse, target)
    assert (target / "images" / "a.jpg").read_bytes() == b"exact image"
    (target / "sparse" / "cameras.txt").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed input bytes"):
        stage_training_dataset(sources, sparse, target)


def test_each_pose_output_stages_its_own_training_dataset(tmp_path):
    """A retried job whose pose manifest changed produces new COLMAP bytes (2026-09-05)."""
    scratch = tmp_path / "job"
    first_pose = scratch / "pose" / ("a" * 64)
    second_pose = scratch / "pose" / ("b" * 64)
    for pose, sparse_bytes in ((first_pose, b"sparse-a"), (second_pose, b"sparse-b")):
        (pose / "sparse").mkdir(parents=True)
        (pose / "sparse" / "points3D.txt").write_bytes(sparse_bytes)
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "a.jpg").write_bytes(b"source-a")
    first = training_dataset_directory(first_pose)
    second = training_dataset_directory(second_pose)
    assert first != second
    assert first.parent == second.parent == scratch / "training-dataset"
    stage_training_dataset(sources, first_pose / "sparse", first)
    # Under one shared directory this second staging refused "changed input bytes" and the job
    # failed; keyed by pose output it stages cleanly while the first copy stays verifiable.
    stage_training_dataset(sources, second_pose / "sparse", second)
    stage_training_dataset(sources, first_pose / "sparse", first)
    assert (first / "sparse" / "points3D.txt").read_bytes() == b"sparse-a"
    assert (second / "sparse" / "points3D.txt").read_bytes() == b"sparse-b"


def test_trained_bounds_are_derived_from_actual_gaussian_bytes():
    bounds = gaussian_ply_bounds(ply())
    assert bounds["min"] == pytest.approx([-0.5, 0.5, 1.5])
    assert bounds["max"] == pytest.approx([2.5, 3.5, 4.5])
    with pytest.raises(ValueError, match="vertex bytes"):
        gaussian_ply_bounds(ply()[:-1])
    anisotropic = ply()[:-24] + struct.pack("<6f", 1, 2, 3, math.log(2), -3, -4)
    bounds = gaussian_ply_bounds(anisotropic)
    assert bounds["min"] == pytest.approx([-5, -4, -3])
    assert bounds["max"] == pytest.approx([7, 8, 9])


def _evaluation_fixture(tmp_path):
    (tmp_path / "heldout").mkdir()
    rendered = tmp_path / "heldout/view-00000.png"
    from PIL import Image

    Image.new("RGB", (4, 4), "blue").save(rendered)
    (tmp_path / "runtime.json").write_text('{"notice":"SYNTHETIC TEST"}')
    metrics = {
        "heldout_views": 1,
        "per_view": [
            {
                "render": "heldout/view-00000.png",
                "render_sha256": hashlib.sha256(rendered.read_bytes()).hexdigest(),
                "source_sha256": "a" * 64,
                "reference_pixels_sha256": "a" * 64,
            }
        ],
    }
    (tmp_path / "metrics.json").write_text(json.dumps(metrics))
    (tmp_path / "checkpoints").mkdir()
    (tmp_path / "checkpoints/model.pt").write_bytes(b"private checkpoint")
    return rendered, metrics


def test_evaluation_bundle_budget_is_the_stage_parameter_and_holds_a_210_photograph_capture():
    """MEASURED 2026-09-06: 27 held-out 12 MP views overflowed the 256 MiB budget of version 1."""
    from exulanica.ingest.scene_splat import EVALUATION_MAX_BYTES
    from exulanica.ingest.stages import STAGES

    spec = STAGES["scene_splat_evaluation"]
    assert spec.version == 2
    assert spec.params["max_bytes"] == 1_073_741_824
    assert spec.params["max_bytes"] == EVALUATION_MAX_BYTES
    # 27 renders of about 9 MB and 27 rectified references of about 6 MB, with headroom.
    assert EVALUATION_MAX_BYTES > 27 * (9 + 6) * 1024 * 1024 * 2


def test_private_evaluation_bundle_retains_verified_pixels_and_excludes_scratch(tmp_path):
    rendered, metrics = _evaluation_fixture(tmp_path)
    first = evaluation_bundle(tmp_path)
    assert first == evaluation_bundle(tmp_path)
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert set(archive.namelist()) == {
            "inventory.json",
            "metrics.json",
            "runtime.json",
            "heldout/view-00000.png",
        }
        inventory = json.loads(archive.read("inventory.json"))
        for item in inventory["files"]:
            assert hashlib.sha256(archive.read(item["path"])).hexdigest() == item["sha256"]
    rendered.write_bytes(b"changed pixels")
    with pytest.raises(ValueError, match="metric digest"):
        evaluation_bundle(tmp_path)
    metrics["per_view"][0]["render"] = "../outside.png"
    (tmp_path / "metrics.json").write_text(json.dumps(metrics))
    with pytest.raises(ValueError, match="escapes"):
        evaluation_bundle(tmp_path)


@pytest.mark.parametrize("companion", ["split.json", "training/dataset.json"])
@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_evaluation_bundle_refuses_missing_or_changed_runtime_bound_companions(
    tmp_path, companion, damage
):
    _evaluation_fixture(tmp_path)
    runtime = {"profile": "exulanica.gsplat-scene-runner/v1"}
    for name, binding in (
        ("split.json", "split_sha256"),
        ("training/dataset.json", "prepared_dataset_receipt_sha256"),
    ):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text('{"notice":"SYNTHETIC COMPANION"}')
        runtime[binding] = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / "runtime.json").write_text(json.dumps(runtime))
    assert evaluation_bundle(tmp_path)
    if damage == "missing":
        (tmp_path / companion).unlink()
    else:
        (tmp_path / companion).write_text('{"notice":"CHANGED COMPANION"}')
    with pytest.raises(ValueError, match=r"requires generated output|runtime or metric digest"):
        evaluation_bundle(tmp_path)


def test_production_evaluation_bundle_requires_both_runtime_companion_bindings(tmp_path):
    _evaluation_fixture(tmp_path)
    (tmp_path / "runtime.json").write_text('{"profile":"exulanica.gsplat-scene-runner/v1"}')
    with pytest.raises(ValueError, match="valid runtime digest binding"):
        evaluation_bundle(tmp_path)


def test_nonmetric_trained_scene_uses_normal_publication_and_keeps_recorded_rung(
    repository, tmp_path
):
    store, captures, selected, _ = queued(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    assert claimed is not None and claimed.job_id == selected.job_id
    result = processor(repository, store, tmp_path, ScriptedTrainer()).process(claimed)
    assert result.status == "succeeded", result.message
    scene = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert scene.scene_id == result.scene_id and scene.recorded_rung == 3
    assert scene.rendering_substrate == "gaussian_splats"
    assert scene.trained_geometry is not None and scene.trained_geometry.state == "available"
    # The status line shows the trainer's own measured numbers, not a summary someone typed.
    quality = scene.trained_geometry.quality.model_dump()
    assert {
        key: quality[key] for key in quality if key not in ("duration_seconds", "usd_cost")
    } == {
        "heldout_views": 1,
        "psnr": 28.0,
        "ssim": 0.86,
        "lpips": 0.14,
        "coverage_fraction": 0.92,
        "floaters_fraction": 0.02,
        "iterations_completed": 1000,
        "gpu": "NVIDIA L40S serial-redacted",
    }
    assert quality["duration_seconds"] > 0 and quality["usd_cost"] >= 0
    artifact_id = scene.trained_geometry.artifact_id
    found = read_scene_geometry(repository.connection, repository.workspace_id, artifact_id, store)
    assert found is not None and found.payload == b"SOG-delivery"
    assert read_scene_geometry(repository.connection, uuid.uuid4(), artifact_id, store) is None
    evaluation = repository.connection.execute(
        "select artifact_id,content_sha256 from artifact where workspace_id=%s and scene_id=%s "
        "and kind='scene_splat_evaluation_bundle'",
        (repository.workspace_id, scene.scene_id),
    ).fetchone()
    assert evaluation is not None
    with zipfile.ZipFile(
        io.BytesIO(store.get(BlobId(bytes(evaluation["content_sha256"]))))
    ) as archive:
        assert "heldout/view-00000.png" in archive.namelist()
        assert json.loads(archive.read("metrics.json"))["heldout_views"] == 1
    assert (
        read_scene_geometry(
            repository.connection, repository.workspace_id, evaluation["artifact_id"], store
        )
        is None
    )
    assert len(captures) == 4 and scene.registered_member_count == 4
    assert not (tmp_path / "scratch" / claimed.scratch_key).exists()
    reloaded = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert reloaded.trained_geometry == scene.trained_geometry


def test_refused_training_quality_keeps_verified_point_maps(repository, tmp_path):
    store, _captures, _selected, _ = queued(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    result = processor(repository, store, tmp_path, ScriptedTrainer(reject=True)).process(claimed)
    assert result.status == "succeeded", result.message
    scene = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert scene.recorded_rung == 3 and scene.rendering_substrate == "posed_point_maps"
    assert scene.trained_geometry is None
    assert any("PSNR" in reason for reason in scene.recorded_reasons)


def test_trained_scene_keeps_recovered_camera_when_all_point_map_bytes_are_missing(
    repository, tmp_path
):
    store, _captures, _selected, _config = queued(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    result = processor(repository, store, tmp_path, ScriptedTrainer()).process(claimed)
    assert result.status == "succeeded", result.message
    scene = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    for member in scene.members:
        digest = BlobId.from_hex(member.placement.content_sha256)
        (store.root / store.key_for(digest)).unlink()
    scene = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert scene.rendering_substrate == "gaussian_splats"
    assert scene.recorded_rung == 3 and scene.placement_state == "bytes_missing"
    assert all(member.placement is None for member in scene.members)
    assert all(member.recovered_camera is not None for member in scene.members)
    first = scene.members[0].recovered_camera
    assert first.calibration.width == 160 and first.calibration.height == 100
    assert first.calibration.fy == pytest.approx(100 / (2 * math.tan(math.pi / 6)))
    assert first.scene_from_camera_row_major[3] == 5
    assert first.projection == "pinhole"


def test_training_preemption_preserves_checkpoint_and_exact_job_for_retry(repository, tmp_path):
    store, _captures, selected, _ = queued(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    trainer = ScriptedTrainer(preempt_once=True)
    result = processor(repository, store, tmp_path, trainer).process(claimed)
    assert result.status == "checkpointed", result.message
    assert list((tmp_path / "scratch" / claimed.scratch_key).rglob("step-5000.pt"))
    row = repository.connection.execute(
        "select status,failure_class,build_inputs from reconstruction_scene_job "
        "where workspace_id=%s and job_id=%s",
        (repository.workspace_id, selected.job_id),
    ).fetchone()
    assert row["status"] == "queued" and row["failure_class"] == "training_checkpointed"
    assert row["build_inputs"] == claimed.build_inputs
    assert (
        read_snapshot(repository.connection, repository.workspace_id, store).reconstruction_scenes
        == []
    )


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_trained_asset_damage_uses_point_map_fallback(repository, tmp_path, damage):
    store, _captures, _selected, _ = queued(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    result = processor(repository, store, tmp_path, ScriptedTrainer()).process(claimed)
    assert result.status == "succeeded", result.message
    scene = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    digest = BlobId.from_hex(scene.trained_geometry.content_sha256)
    path = store.root / store.key_for(digest)
    path.chmod(0o644)
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"damaged SOG")
    scene = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert scene.rendering_substrate == "posed_point_maps" and scene.recorded_rung == 3
    assert scene.trained_geometry.state == ("bytes_missing" if damage == "missing" else "invalid")
    assert scene.trained_geometry.reference is None


def test_unconfirmed_container_cleanup_marker_protects_even_abandoned_scratch(tmp_path):
    from exulanica.ingest.reconstruction_scratch import (
        active_scene_scratch,
        cleanup_abandoned_scene_scratch,
        cleanup_scene_scratch,
    )

    key = f"{uuid.uuid4()}/{uuid.uuid4()}"
    with active_scene_scratch(tmp_path, key) as directory:
        marker = directory / "splat" / "output" / "container-cleanup-required.json"
        marker.parent.mkdir(parents=True)
        marker.write_text('{"reason":"scripted daemon unavailable"}')
    assert cleanup_scene_scratch(tmp_path, key) is False
    assert (
        cleanup_abandoned_scene_scratch(
            tmp_path, active_keys=frozenset(), older_than_seconds=0, now=10**12
        )
        == ()
    )
    assert marker.exists()


def test_four_graceful_preemptions_keep_the_same_job_and_checkpoint_eligible(repository, tmp_path):
    store, _captures, selected, _ = queued(repository, tmp_path)

    class Preemptions(ScriptedTrainer):
        remaining = 4

        def __call__(self, command, cwd):
            if command[0] == "exulanica-gsplat-scene-v1" and self.remaining:
                self.remaining -= 1
                output = Path(command[command.index("--output") + 1]) / "checkpoints"
                output.mkdir(parents=True, exist_ok=True)
                (output / "step-5000.pt").write_bytes(b"scripted durable checkpoint")
                return CommandResult(75, "scripted durable stop", "", 1)
            return super().__call__(command, cwd)

    trainer = Preemptions()
    for index in range(5):
        claimed = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
        assert claimed is not None and claimed.job_id == selected.job_id
        assert claimed.attempts == 1
        result = processor(repository, store, tmp_path, trainer).process(claimed)
        assert result.status == ("checkpointed" if index < 4 else "succeeded"), result.message
        if index < 4:
            assert claimed.scratch_key in repository.active_reconstruction_scratch_keys()


def test_storage_retry_reuses_completed_training_instead_of_retraining(
    repository, tmp_path, monkeypatch
):
    store, _captures, _selected, _ = queued(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    trainer = ScriptedTrainer()
    put = store.put_bytes

    def failed_write(_content):
        raise OSError("scripted post-commit store failure")

    monkeypatch.setattr(store, "put_bytes", failed_write)
    result = processor(repository, store, tmp_path, trainer).process(claimed)
    assert result.status == "failed" and "post-commit" in result.message
    assert (tmp_path / "scratch" / claimed.scratch_key).exists()
    assert len(trainer.calls) == 3
    monkeypatch.setattr(store, "put_bytes", put)
    retry = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    assert retry is not None and retry.job_id == claimed.job_id
    result = processor(repository, store, tmp_path, trainer).process(retry)
    assert result.status == "succeeded", result.message
    assert len(trainer.calls) == 3


def test_changed_training_config_has_a_new_gate_and_unpublished_bytes_stay_hidden(
    repository, tmp_path, monkeypatch
):
    store, captures, selected, config = queued(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    result = processor(repository, store, tmp_path, ScriptedTrainer()).process(claimed)
    assert result.status == "succeeded", result.message
    original = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    second = enqueue_exact_scene_reconstruction(
        repository,
        captures,
        actor=uuid.uuid4(),
        purpose="second scripted training configuration",
        authorized_at=dt.datetime.now(dt.UTC),
        splat_training=dataclasses.replace(config, max_iterations=2000),
    )
    assert second is not None and second.job_id != selected.job_id
    claimed = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    complete = repository.complete_reconstruction_scene_job
    monkeypatch.setattr(repository, "complete_reconstruction_scene_job", lambda **kwargs: False)
    result = processor(repository, store, tmp_path, ScriptedTrainer()).process(claimed)
    assert result.status == "failed" and "claim" in result.message
    rows = repository.connection.execute(
        "select artifact_id from artifact where workspace_id=%s and scene_id=%s "
        "and kind='gaussian_splat_scene' and artifact_id<>%s",
        (repository.workspace_id, original.scene_id, original.trained_geometry.artifact_id),
    ).fetchall()
    assert len(rows) == 1
    assert (
        read_scene_geometry(
            repository.connection, repository.workspace_id, rows[0]["artifact_id"], store
        )
        is None
    )
    current = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert current.gate_digest == original.gate_digest
    monkeypatch.setattr(repository, "complete_reconstruction_scene_job", complete)
    retry = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    result = processor(repository, store, tmp_path, ScriptedTrainer()).process(retry)
    assert result.status == "succeeded", result.message
    current = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert current.gate_digest != original.gate_digest
    assert current.trained_geometry.artifact_id == rows[0]["artifact_id"]


def test_training_request_cannot_replace_the_previously_admitted_evaluation_split(
    repository, tmp_path
):
    _store, captures, _selected, config = queued(repository, tmp_path, frozen_split=True)
    other = repository.capture(captures[1]).blob_id.hex
    with pytest.raises(ValueError, match="frozen held-out split"):
        enqueue_exact_scene_reconstruction(
            repository,
            captures,
            actor=uuid.uuid4(),
            purpose="scripted attempt to move an admitted training image into evaluation",
            authorized_at=dt.datetime.now(dt.UTC),
            splat_training=dataclasses.replace(config, heldout_source_sha256=(other,)),
        )


@pytest.mark.parametrize("replace_point_map", [False, True])
def test_changed_point_map_build_gets_new_training_artifacts_with_the_same_training_config(
    repository, tmp_path, replace_point_map
):
    from exulanica.ingest.stages import artifact_id_for, idempotency_key, input_digest_of, stage

    store, captures, _selected, config = queued(repository, tmp_path)
    first_claim = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    first = processor(repository, store, tmp_path, ScriptedTrainer()).process(first_claim)
    assert first.status == "succeeded", first.message
    original = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    capture = repository.capture(captures[0])
    previous = repository.current_capture_artifacts(capture_ids=[captures[0]], kind="point_map")[
        captures[0]
    ]
    spec, input_digest = stage("depth"), input_digest_of([])
    key = idempotency_key(
        capture.blob_id, spec, input_digest, binding={"model_id": "synthetic-depth-v2"}
    )
    replacement_id = artifact_id_for(key)
    replacement = store.put_bytes(_numeric_point_map(0, color=129))
    repository.insert_artifact(
        artifact_id=replacement_id,
        kind=spec.output_kind,
        source_blob=capture.blob_id,
        stage_key=spec.key,
        stage_version=spec.version,
        params_digest=spec.params_digest,
        input_digest=input_digest,
        idempotency_key=key,
        content_sha256=replacement.blob_id.digest,
        storage_key=store.key_for(replacement.blob_id),
        byte_size=replacement.byte_size,
        produced_by_event=None,
        privacy_screening_id=previous.privacy_screening_id,
    )
    repository.connection.execute(
        "update artifact set superseded_by=%s where workspace_id=%s and artifact_id=%s",
        (
            replacement_id if replace_point_map else previous.artifact_id,
            repository.workspace_id,
            previous.artifact_id if replace_point_map else replacement_id,
        ),
    )
    enqueue_exact_scene_reconstruction(
        repository,
        captures,
        actor=uuid.uuid4(),
        purpose="scripted point-map replacement",
        authorized_at=dt.datetime.now(dt.UTC),
        splat_training=config,
    )
    second_claim = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    assert second_claim is not None and second_claim.job_id != first_claim.job_id
    assert (second_claim.build_input_digest != first_claim.build_input_digest) is replace_point_map
    assert second_claim.build_inputs["splat_training"] == first_claim.build_inputs["splat_training"]
    second = processor(repository, store, tmp_path, ScriptedTrainer(measurement_epoch=2)).process(
        second_claim
    )
    assert second.status == "succeeded", second.message
    current = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert current.trained_geometry.artifact_id != original.trained_geometry.artifact_id
    receipts = repository.connection.execute(
        "select content_sha256 from artifact where workspace_id=%s and scene_id=%s "
        "and kind='scene_splat_receipt'",
        (repository.workspace_id, current.scene_id),
    ).fetchall()
    assert len(receipts) == 2
    manifest_digests = {
        json.loads(store.get(BlobId(bytes(row["content_sha256"]))))["manifest_digest"]
        for row in receipts
    }
    assert len(manifest_digests) == 1


def test_withdrawal_during_training_prevents_all_scene_publication(repository, tmp_path):
    store, captures, _selected, _config = queued(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)

    def withdraw():
        repository.insert_tombstone(
            scope="capture",
            capture_id=captures[1],
            requested_by=uuid.uuid4(),
            reason="scripted withdrawal during training",
        )

    result = processor(repository, store, tmp_path, ScriptedTrainer(withdraw=withdraw)).process(
        claimed
    )
    assert result.status == "cancelled", result.message
    assert not (tmp_path / "scratch" / claimed.scratch_key).exists()
    assert not read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes
    assert (
        repository.connection.execute(
            "select count(*) as count from artifact where workspace_id=%s and scene_id is not null",
            (repository.workspace_id,),
        ).fetchone()["count"]
        == 0
    )


def test_withdrawal_after_publication_removes_the_whole_trained_scene(repository, tmp_path):
    store, captures, _selected, _config = queued(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    result = processor(repository, store, tmp_path, ScriptedTrainer()).process(claimed)
    assert result.status == "succeeded", result.message
    scene = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    repository.insert_tombstone(
        scope="capture",
        capture_id=captures[1],
        requested_by=uuid.uuid4(),
        reason="scripted withdrawal after training publication",
    )
    assert not read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes
    assert (
        read_scene_geometry(
            repository.connection,
            repository.workspace_id,
            scene.trained_geometry.artifact_id,
            store,
        )
        is None
    )


# --------------------------------------------------------------------------------------------
# Masked members. Everything below concerns a scene where somebody is hidden in a photograph, so
# the bytes pose, training and evaluation all read are a masked derivative rather than the
# photograph itself. The held-out split is still declared over the photographs a person reviewed,
# and the remap is the recorded, checkable statement of which derivative replaced which original.
#
# No masked scene has ever been trained on a GPU. These exercise the enqueue, manifest, staging
# and receipt boundaries with the scripted trainer, and claim nothing about appearance or cost.
# --------------------------------------------------------------------------------------------

MASK_ACTOR = uuid.UUID("00000000-0000-4000-8000-000000000001")
MASK_REGION_KEY = (b"m" * 32).hex()
MASK_SCOPE = {"purpose": "masked scene training regression"}


def _hide_a_person(repository, pipeline, capture_id):
    """Add one live unresolved region and run the real mask stage over it."""
    from exulanica.consent.regions import Silhouette
    from exulanica.ingest.person_review import record_region_edits

    record_region_edits(
        repository,
        capture_id=capture_id,
        actor=MASK_ACTOR,
        edits=[
            {
                "action": "add",
                "region_key": MASK_REGION_KEY,
                # No subject, so the region resolves "unknown" and existing policy masks it.
                "silhouette": Silhouette(
                    ((0, 0), (500_000, 0), (500_000, 500_000), (0, 500_000))
                ).as_digest_input(),
                "subject_id": None,
            }
        ],
    )
    built = pipeline.ingest_derivatives(capture_id)
    assert built.error is None, built.error
    assert "masked_source" in built.stages_run


def masked_queued(repository, tmp_path, *, masked=(0, 1), heldout_index=0):
    """A four-member scene with two hidden members, queued for training.

    Every member carries a personal authorization and a human review rather than the synthetic
    exemption ``write_point_map`` defaults to, because admission requires one corpus class and one
    authorization scope across the set, and 0040 refuses a synthetic exemption for any capture
    with live person regions at all.
    """
    from exulanica.ingest.person_review import review_list
    from exulanica.ingest.privacy import authorize_personal_capture, record_human_screening

    store = LocalContentAddressedStore(tmp_path / "store")
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())
    photos = tmp_path / "photos"
    photos.mkdir()
    captures, hashes, blobs = [], [], []
    for index in range(4):
        path = write_photo(
            photos, f"{index}.jpg", when=f"2026:09:05 12:0{index}:00", size=(160 + index, 100)
        )
        outcome = pipeline.ingest_file(path)
        assert outcome.error is None and outcome.capture_id is not None
        captures.append(outcome.capture_id)
        blob = BlobId.of_bytes(path.read_bytes())
        blobs.append(blob)
        hashes.append(blob.hex)
    for index in masked:
        _hide_a_person(repository, pipeline, captures[index])
    screenings = []
    for capture_id in captures:
        authorization = authorize_personal_capture(
            repository,
            capture_id=capture_id,
            actor=MASK_ACTOR,
            account_authority_basis="Operator generated these fixture bytes; no personal media",
            authorization_scope=dict(MASK_SCOPE),
            purpose="masked scene training regression",
        )
        screening = record_human_screening(
            repository,
            authorization_id=authorization.authorization_id,
            reviewed_by=MASK_ACTOR,
            sensitive_regions=review_list(repository, capture_id),
        )
        assert screening.eligibility_state == "eligible", screening.eligibility_state
        screenings.append(screening)
    masks = {}
    for index, blob in enumerate(blobs):
        mask = repository.current_capture_artifacts(
            capture_ids=[captures[index]], kind="masked_source"
        ).get(captures[index])
        if mask is not None:
            masks[index] = mask
        write_point_map(
            repository,
            store,
            blob,
            payload=_numeric_point_map(index),
            privacy_screening_id=screenings[index].screening_id,
            read_source_sha256=mask.content_sha256 if mask is not None else None,
        )
    assert set(masks) == set(masked)
    config = request((hashes[heldout_index],))
    selected = enqueue_exact_scene_reconstruction(
        repository,
        captures,
        actor=uuid.uuid4(),
        purpose="masked scene training regression",
        authorized_at=dt.datetime.now(dt.UTC),
        splat_training=config,
    )
    assert selected is not None
    return store, captures, selected, config, hashes, masks


def _pose(frames):
    """The smallest accepted pose manifest that carries an exact frame inventory."""
    from exulanica.reconstruction.pose import PoseBuildManifest, SourceFrame

    return PoseBuildManifest(
        scene_ref=str(uuid.uuid4()),
        code_revision="a" * 40,
        colmap_version="numeric scripted fixture",
        execution_image="pose-test@sha256:" + "b" * 64,
        frames=tuple(
            SourceFrame(
                capture_ref=capture_ref,
                filename=f"{ordinal:06d}.jpg",
                sha256=digest,
                capture_set="masked-remap-fixture",
            )
            for ordinal, (capture_ref, digest) in enumerate(frames)
        ),
        min_registered_fraction=None,
        max_mean_reprojection_error_px=None,
        min_camera_translation_units=None,
    )


def _remap_fixture():
    """One hidden member and three plain ones, in the two digest spaces the remap joins."""
    captures = [str(uuid.UUID(int=index + 1)) for index in range(4)]
    originals = [chr(ord("a") + index) * 64 for index in range(4)]
    masked = "e" * 64
    remap = [
        {
            "capture_ref": captures[0],
            "source_sha256": originals[0],
            "masked_source_sha256": masked,
        }
    ]
    return captures, originals, masked, remap


def test_masked_members_train_and_publish_against_the_derivative_they_were_masked_into(
    repository, tmp_path
):
    """The whole point: a scene with somebody hidden in it reaches a published trained scene.

    The held-out member is a masked one deliberately. Holding out a plain member would pass with
    no remap at all, because that member's pose frame digest is already its photograph's.
    """
    store, captures, selected, config, hashes, masks = masked_queued(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    assert claimed is not None and claimed.job_id == selected.job_id

    # What the operator asked for, and what the queue froze, differ by exactly the substitution.
    stored = claimed.build_inputs["splat_training"]
    assert config.heldout_source_sha256 == (hashes[0],)
    assert stored["heldout_source_sha256"] == [masks[0].content_sha256.hex()]
    assert stored["masked_source_remap"] == {
        str(captures[index]): {
            "source_sha256": hashes[index],
            "masked_source_sha256": masks[index].content_sha256.hex(),
        }
        for index in (0, 1)
    }

    result = processor(repository, store, tmp_path, ScriptedTrainer()).process(claimed)
    assert result.status == "succeeded", result.message
    scene = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert scene.rendering_substrate == "gaussian_splats"
    assert scene.trained_geometry is not None and scene.trained_geometry.state == "available"

    receipt = json.loads(
        store.get(
            BlobId(
                bytes(
                    repository.connection.execute(
                        "select content_sha256 from artifact where workspace_id=%s and scene_id=%s"
                        " and kind='scene_splat_receipt'",
                        (repository.workspace_id, scene.scene_id),
                    ).fetchone()["content_sha256"]
                )
            )
        )
    )
    parameters = receipt["manifest"]["parameters"]
    assert parameters["masked_source_remap"] == stored["masked_source_remap"]
    # The receipt withholds the derivative, and the map is what says which photograph that was.
    assert parameters["heldout_source_sha256"] == [masks[0].content_sha256.hex()]
    assert hashes[0] not in receipt["manifest"]["source_sha256"]
    assert masks[0].content_sha256.hex() in receipt["manifest"]["source_sha256"]

    evaluation = repository.connection.execute(
        "select content_sha256 from artifact where workspace_id=%s and scene_id=%s "
        "and kind='scene_splat_evaluation_bundle'",
        (repository.workspace_id, scene.scene_id),
    ).fetchone()
    with zipfile.ZipFile(
        io.BytesIO(store.get(BlobId(bytes(evaluation["content_sha256"]))))
    ) as archive:
        split = json.loads(archive.read("split.json"))
        metrics = json.loads(archive.read("metrics.json"))
    assert split["heldout_original_source_sha256"] == [hashes[0]]
    assert {item["capture_ref"] for item in split["masked_source_remap"]} == {
        str(captures[0]),
        str(captures[1]),
    }
    assert "masked-derivative-bytes-only" in split["reference_pixels"]
    # Not an echo of what the scripted trainer wrote: the hidden member's photograph digest
    # labels no measured pixel anywhere in the bundle, and appears in the split receipt only
    # inside the remap that exists to say which photograph was replaced.
    assert hashes[0] not in json.dumps(metrics)
    assert json.dumps(split).count(hashes[0]) == 2
    assert masks[0].content_sha256.hex() in json.dumps(metrics["per_view"])


def test_an_unmasked_scene_keeps_the_exact_request_and_manifest_bytes_it_had_before(
    repository, tmp_path
):
    """A corpus with no people in it must not pay for this in a changed identity."""
    store, _captures, _selected, _config = queued(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    assert "masked_source_remap" not in claimed.build_inputs["splat_training"]
    assert "masked_sources" not in claimed.build_inputs
    result = processor(repository, store, tmp_path, ScriptedTrainer()).process(claimed)
    assert result.status == "succeeded", result.message
    scene = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    receipt = json.loads(
        store.get(
            BlobId(
                bytes(
                    repository.connection.execute(
                        "select content_sha256 from artifact where workspace_id=%s and scene_id=%s"
                        " and kind='scene_splat_receipt'",
                        (repository.workspace_id, scene.scene_id),
                    ).fetchone()["content_sha256"]
                )
            )
        )
    )
    assert "masked_source_remap" not in receipt["manifest"]["parameters"]


def test_a_mask_that_went_stale_between_enqueue_and_run_is_refused_before_any_pose_work(
    repository, tmp_path
):
    """The frozen remap describes an exact derivative, and a rebuilt mask is a different one."""
    from exulanica.consent.regions import Silhouette
    from exulanica.ingest.person_review import record_region_edits

    store, captures, selected, _config, _hashes, _masks = masked_queued(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    assert claimed is not None and claimed.job_id == selected.job_id
    record_region_edits(
        repository,
        capture_id=captures[0],
        actor=MASK_ACTOR,
        edits=[
            {
                "action": "confirm",
                "region_key": MASK_REGION_KEY,
                "silhouette": Silhouette(
                    ((0, 0), (900_000, 0), (900_000, 500_000), (0, 500_000))
                ).as_digest_input(),
                "subject_id": None,
            }
        ],
    )
    trainer = ScriptedTrainer()
    result = processor(repository, store, tmp_path, trainer).process(claimed)
    assert result.status == "failed"
    assert "stale" in result.message, result.message
    assert trainer.calls == []
    assert not read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes


def test_a_masked_scene_without_a_remap_still_meets_the_unrelaxed_subset_rule():
    """The naive fix, refused. This is the control the refusal comment described.

    It guards a rule this change deliberately did not touch, so it would have passed before the
    change as well. That is the point: it fails the day somebody relaxes the subset rule to make a
    masked scene train without a map, which is the shortcut the comment was written to prevent.

    Relaxing `SplatBuildManifest`'s subset rule so an unresolved original could stand beside
    derivative sources is what would let a partially masked scene train: `load_dataset` still
    matches the plain members' held-out views, raises nothing, and the masked photographs the
    split claimed to withhold end up in training. Binding the remap resolves the split instead,
    and the subset rule is left exactly as strict as it was.
    """
    captures, originals, masked, _remap = _remap_fixture()
    unbound = request((originals[0],))
    pose = _pose(
        [(captures[0], masked), *[(captures[i], originals[i]) for i in range(1, 4)]]
    )
    with pytest.raises(ValueError, match="proper subset"):
        unbound.manifest(pose)


def test_a_swapped_derivative_digest_is_refused_against_the_pose_frames():
    """Two hidden members whose derivatives are exchanged. Digests alone cannot see this.

    Both derivatives really are training sources and neither original is, so every rule the
    manifest can state about hashes is satisfied. Only the capture each hash was recorded against
    distinguishes the honest map from the one that would score a person's render against somebody
    else's photograph, which is why the map carries a capture reference at all.
    """
    captures, originals, _masked, _remap = _remap_fixture()
    first, second = "e" * 64, "f" * 64
    bound = request((originals[0],)).bind_masked_sources(
        [
            {
                "capture_ref": captures[0],
                "source_sha256": originals[0],
                "masked_source_sha256": second,
            },
            {
                "capture_ref": captures[1],
                "source_sha256": originals[1],
                "masked_source_sha256": first,
            },
        ],
        sources=tuple(originals),
    )
    pose = _pose(
        [
            (captures[0], first),
            (captures[1], second),
            (captures[2], originals[2]),
            (captures[3], originals[3]),
        ]
    )
    with pytest.raises(ValueError, match="does not bind the derivative"):
        bound.manifest(pose)


def test_an_original_staged_for_a_masked_capture_is_refused():
    """A pose frame carrying the photograph of a member the mask inputs say must be hidden."""
    captures, originals, masked, remap = _remap_fixture()
    bound = request((originals[0],)).bind_masked_sources(remap, sources=tuple(originals))
    honest = _pose(
        [(captures[0], masked), *[(captures[i], originals[i]) for i in range(1, 4)]]
    )
    assert bound.manifest(honest).masked_source_remap == (
        (captures[0], originals[0], masked),
    )
    original_frames = _pose([(captures[i], originals[i]) for i in range(4)])
    with pytest.raises(ValueError, match="does not bind the derivative"):
        bound.manifest(original_frames)


def test_a_remap_is_derived_at_enqueue_and_never_declared_by_an_operator():
    captures, originals, masked, remap = _remap_fixture()
    bound = request((originals[0],)).bind_masked_sources(remap, sources=tuple(originals))
    assert bound.heldout_source_sha256 == (masked,)
    assert SceneSplatRequest.from_payload(bound.as_payload()) == bound
    with pytest.raises(ValueError, match="never declared"):
        bound.bind_masked_sources(remap, sources=tuple(originals))
    with pytest.raises(ValueError, match="outside this admitted scene"):
        request((originals[0],)).bind_masked_sources(
            [{**remap[0], "source_sha256": "9" * 64}], sources=tuple(originals)
        )
    # Two hidden members whose masks produced the same bytes would silently shrink the split.
    with pytest.raises(ValueError, match="collapses two held-out"):
        request((originals[0], originals[1])).bind_masked_sources(
            [
                {**remap[0], "masked_source_sha256": masked},
                {
                    "capture_ref": captures[1],
                    "source_sha256": originals[1],
                    "masked_source_sha256": masked,
                },
            ],
            sources=tuple(originals),
        )


def test_a_member_that_newly_needs_a_mask_after_enqueue_is_refused(repository, tmp_path):
    """0040's matcher decides who needs hiding now, not who needed it when the job was queued."""
    from exulanica.ingest.pipeline import PhotoIngestPipeline

    store, captures, _selected, _config, _hashes, _masks = masked_queued(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="training-test", lease_seconds=60)
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())
    _hide_a_person(repository, pipeline, captures[2])
    trainer = ScriptedTrainer()
    result = processor(repository, store, tmp_path, trainer).process(claimed)
    assert result.status == "failed"
    assert "require a declared masked source" in result.message, result.message
    assert trainer.calls == []


def test_a_derivative_rebuilt_after_enqueue_no_longer_binds_its_frozen_remap():
    """The stage-binding check on its own, with the mask rebuilt under a frozen job.

    The database-level version of this scenario above is refused earlier and harder, by
    `verify_masked_sources`, because the job's declaration still names the superseded artifact.
    This is the same drift arriving one layer later: if the declaration and the remap ever fell
    out of step, the remap is the half that still knows which bytes this build was admitted with.
    """
    captures, originals, _masked, remap = _remap_fixture()
    bound = request((originals[0],)).bind_masked_sources(remap, sources=tuple(originals))
    rebuilt = "9" * 64
    frames = _pose(
        [(captures[0], rebuilt), *[(captures[i], originals[i]) for i in range(1, 4)]]
    )
    with pytest.raises(ValueError, match="rebuild the mask and re-admit"):
        bound.manifest(frames)


@pytest.mark.parametrize(
    ("remap", "message"),
    [
        ((("not-a-capture", "a" * 64, "b" * 64),), "exact capture reference"),
        (((str(uuid.UUID(int=1)), "a" * 64, "zz" + "b" * 62),), "exact source hashes"),
        (((str(uuid.UUID(int=1)), 7, "b" * 64),), "exact source hashes"),
        (((str(uuid.UUID(int=1)), "a" * 64, "a" * 64),), "cannot be the original bytes"),
        (
            (
                (str(uuid.UUID(int=1)), "a" * 64, "b" * 64),
                (str(uuid.UUID(int=1)), "c" * 64, "d" * 64),
            ),
            "twice",
        ),
        (
            (
                (str(uuid.UUID(int=1)), "a" * 64, "b" * 64),
                (str(uuid.UUID(int=2)), "c" * 64, "b" * 64),
            ),
            "twice",
        ),
        (
            (
                (str(uuid.UUID(int=2)), "c" * 64, "d" * 64),
                (str(uuid.UUID(int=1)), "a" * 64, "b" * 64),
            ),
            "ordered by capture reference",
        ),
        (((str(uuid.UUID(int=1)), "a" * 64),), "capture and two hashes"),
    ],
)
def test_the_request_refuses_every_malformed_remap_shape(remap, message):
    """The request validator and the manifest validator are twins by necessity, not by accident.

    The layering contract forbids reconstruction from importing ingest, so the same rules are
    written out in both places. Two copies of a rule are two places for one of them to rot, which
    is why each copy carries its own controls rather than trusting the other's.
    """
    with pytest.raises(ValueError, match=message):
        dataclasses.replace(request(("f" * 64,)), masked_source_remap=remap)
