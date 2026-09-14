"""Read-only preflight contracts. Fixture bytes are not reconstruction/visual acceptance."""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from dataclasses import replace

import pytest
from exulanica.evaluation.reference_inputs import envelope
from exulanica.orchestration import scene_run_preflight as preflight
from exulanica.orchestration.scene_run_preflight import RunResources, inspect_local_run
from exulanica.reconstruction.gsplat_protocol import (
    CHECKPOINT_PROFILE,
    GSPLAT_REVISION,
    TRAINING_PROTOCOL,
)
from exulanica.reconstruction.gsplat_runner import dataset_digest
from exulanica.reconstruction.splat import _canonical, _quality

from test_reconstruction_splat import FakeRunner, _dataset, _pose_receipt
from test_reconstruction_splat import _manifest as _base_manifest


def _manifest(**changes):
    return _base_manifest(**{"gsplat_revision": GSPLAT_REVISION, **changes})


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value))


@pytest.fixture
def run(tmp_path):
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    _write(manifest_path, manifest.as_payload())
    dataset = _dataset(tmp_path / "dataset")
    pose = _pose_receipt(tmp_path / "pose.json", manifest)
    value = json.loads(pose.read_bytes())
    value["quality"]["registered_images"] = ["a.jpg", "b.jpg"]
    value["quality_digest"] = _sha(_canonical(value["quality"]))
    _write(pose, value)
    source_manifest = tmp_path / "inputs.json"
    _write(
        source_manifest,
        envelope(
            {
                "profile": "exulanica.reference-inputs/v1",
                "files": [
                    {
                        "path": f["filename"],
                        "sha256": f["sha256"],
                        "bytes": 8,
                        "width": 1,
                        "height": 1,
                    }
                    for f in value["manifest"]["frames"]
                ],
                "evaluation_split": {
                    "heldout_sha256": list(manifest.heldout_source_sha256),
                    "training_sha256": [manifest.source_sha256[1]],
                },
            }
        ),
    )
    return dict(
        scene_ref=manifest.scene_ref,
        current_pose_sha256=_sha(pose.read_bytes()),
        current_pose_manifest_digest=manifest.pose_manifest_digest,
        current_sources=list(manifest.source_sha256),
        manifest_path=manifest_path,
        dataset=dataset,
        pose_receipt=pose,
        output=tmp_path / "job" / "output",
        source_manifest=source_manifest,
        resources=RunResources(
            "test-provider",
            "fixture quote, no actual offer",
            "2026-09-13T00:00:00Z",
            749000,
            1000,
            20000,
            3600,
            1000000,
            2000000,
            10000000,
        ),
    )


def _snapshot(root):
    return {str(p.relative_to(root)): _sha(p.read_bytes()) for p in root.rglob("*") if p.is_file()}


def test_plan_is_deterministic_read_only_and_not_execution_authority(run, tmp_path):
    before = _snapshot(tmp_path)
    first = inspect_local_run(**run)
    assert first == inspect_local_run(**run)
    assert first["status"] == "plan_ready"
    assert first["blockers"] == []
    assert first["run"]["cost_ceiling_microusd"] == 770000
    assert first["run"]["managed_trainer_argv"][:3] == [
        "python",
        "-m",
        "exulanica.reconstruction.gsplat_container",
    ]
    assert first["run"]["manifest"]["training_protocol"] == TRAINING_PROTOCOL
    assert first["allocation_authorized"] is False
    assert first["execution_authorized"] is False
    assert first["acceptance"]["accepted"] is False
    assert _snapshot(tmp_path) == before
    assert not run["output"].exists()
    digest = first.pop("document_sha256")
    assert digest == _sha(_canonical(first))


@pytest.mark.parametrize(
    "change,stage",
    [
        ({"current_sources": ["e" * 64]}, "input"),
        ({"current_pose_sha256": "f" * 64}, "pose"),
        ({"current_pose_manifest_digest": "e" * 64}, "pose"),
        ({"resources": None}, "resources"),
        ({"source_manifest": None}, "input_coverage"),
        ({"scene_ref": "another-scene"}, "training"),
    ],
)
def test_missing_or_stale_bindings_are_stage_specific(run, change, stage):
    report = inspect_local_run(**{**run, **change})
    assert report["blockers"][0]["stage"] == stage
    assert report["run"] is None


def test_source_bytes_changed_and_pose_sparse_bytes_changed(run):
    image = run["dataset"] / "images" / "a.jpg"
    image.write_bytes(b"changed")
    assert inspect_local_run(**run)["blockers"][0]["stage"] == "input"
    image.write_bytes(b"source-a")
    (run["dataset"] / "sparse" / "0" / "cameras.bin").write_bytes(b"changed")
    assert inspect_local_run(**run)["blockers"][0]["stage"] == "pose"


def test_source_split_cannot_be_changed_after_pose(run):
    payload = json.loads(run["source_manifest"].read_bytes())["record"]
    split = payload["evaluation_split"]
    split["training_sha256"], split["heldout_sha256"] = (
        split["heldout_sha256"],
        split["training_sha256"],
    )
    _write(run["source_manifest"], envelope(payload))
    report = inspect_local_run(**run)
    assert report["blockers"][0]["stage"] == "input_coverage"
    assert "split differs" in report["blockers"][0]["detail"]


def test_unregistered_heldout_is_coverage_blocker(run):
    pose = json.loads(run["pose_receipt"].read_bytes())
    pose["quality"]["registered_images"] = ["b.jpg"]
    pose["quality_digest"] = _sha(_canonical(pose["quality"]))
    _write(run["pose_receipt"], pose)
    run["current_pose_sha256"] = _sha(run["pose_receipt"].read_bytes())
    assert inspect_local_run(**run)["blockers"][0]["stage"] == "input_coverage"


def test_unknown_schema_and_changed_protocol_are_refused(run):
    value = json.loads(run["manifest_path"].read_bytes())
    value["training_protocol"]["seed"] = 99
    _write(run["manifest_path"], value)
    assert inspect_local_run(**run)["blockers"][0]["stage"] == "training"


def test_old_unmasked_manifest_retains_its_identity(run):
    report = inspect_local_run(**run)
    manifest = _manifest()
    assert "masked_source_remap" not in manifest.as_payload()["parameters"]
    assert report["bindings"]["manifest_digest"] == manifest.digest


def test_mask_boundary_failure_stops_before_checkpoint_or_gpu(run, monkeypatch):
    def refused(*args):
        raise ValueError("a required masked derivative is unavailable")

    monkeypatch.setattr(preflight, "verify_masked_training_sources", refused)
    assert inspect_local_run(**run)["blockers"][0]["stage"] == "mask"


def _pointer(run, **changes):
    identity = {
        "manifest_digest": _manifest().digest,
        "dataset_digest": dataset_digest(run["dataset"]),
    }
    path = run["output"] / "checkpoints" / "step-000005000.pt"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"fixture-not-a-real-checkpoint")
    value = {
        "profile": CHECKPOINT_PROFILE,
        "identity": identity,
        "file": path.name,
        "sha256": _sha(path.read_bytes()),
        "next_iteration": 5000,
        **changes,
    }
    _write(path.parent / "latest.json", value)
    return path


@pytest.mark.parametrize(
    "changes",
    [
        {"identity": {"manifest_digest": "f" * 64, "dataset_digest": "e" * 64}},
        {"next_iteration": 30001},
        {"next_iteration": True},
        {"file": "../elsewhere.pt"},
        {"sha256": "e" * 64},
    ],
)
def test_stale_or_corrupt_checkpoints_rejected_before_deserialization(run, monkeypatch, changes):
    _pointer(run, **changes)

    def forbidden(*args, **kwargs):
        pytest.fail("stale checkpoint must not be deserialized")

    monkeypatch.setattr(preflight, "load_checkpoint", forbidden)
    assert inspect_local_run(**run)["blockers"][0]["stage"] == "checkpoint"


def test_pointer_alone_is_not_complete_resume_proof(run, monkeypatch):
    _pointer(run)

    def refused(*args, **kwargs):
        raise ValueError("optimizer state missing")

    monkeypatch.setattr(preflight, "load_checkpoint", refused)
    assert inspect_local_run(**run)["blockers"][0]["stage"] == "checkpoint"


def test_validated_checkpoint_is_reused_even_with_partial_runtime(run, monkeypatch):
    _pointer(run)
    _write(run["output"] / "runtime.json", {"interrupted": True})
    calls = []

    def validated(*args, **kwargs):
        calls.append(kwargs)
        return {"next_iteration": 5000}

    monkeypatch.setattr(preflight, "load_checkpoint", validated)
    result = inspect_local_run(**run)
    assert result["status"] == "plan_ready"
    assert result["reuse"][-1]["kind"] == "checkpoint"
    assert calls[0]["identity"]["dataset_digest"] == dataset_digest(run["dataset"])


def test_cleanup_uncertain_and_symlink_outputs_refused(run, tmp_path):
    _write(run["output"] / "container-cleanup-required.json", {"owner": "test"})
    assert inspect_local_run(**run)["blockers"][0]["stage"] == "checkpoint"
    (run["output"] / "container-cleanup-required.json").unlink()
    (run["output"] / "leak").symlink_to(tmp_path / "pose.json")
    assert inspect_local_run(**run)["blockers"][0]["stage"] == "input"


def test_resources_must_be_complete_and_match_manifest(run):
    with pytest.raises(ValueError):
        replace(run["resources"], gpu_hour_microusd=True)
    with pytest.raises(ValueError):
        replace(run["resources"], quote_reference="")
    for change in ({"gpu_hour_microusd": 1}, {"scratch_budget_bytes": 1}):
        result = inspect_local_run(**{**run, "resources": replace(run["resources"], **change)})
        assert result["blockers"][0]["stage"] == "resources"


def _completed(run, *, psnr=28.0, delivery=False):
    output = run["output"]
    output.mkdir(parents=True)
    manifest = _manifest()
    FakeRunner(manifest, psnr=psnr)(
        ("exulanica-gsplat-scene-v1", "--output", str(output)), output.parent
    )
    identity = {
        "manifest_digest": manifest.digest,
        "dataset_digest": dataset_digest(run["dataset"]),
    }
    split = {
        "profile": "exulanica.gsplat-heldout-split/v1",
        **identity,
        "predeclared_heldout_source_sha256": list(manifest.heldout_source_sha256),
        "unregistered_heldout_source_sha256": [],
        "training": ["b.jpg"],
        "heldout": ["a.jpg"],
    }
    _write(output / "split.json", split)
    _write(
        output / "training" / "dataset.json",
        {
            "profile": "exulanica.gsplat-prepared-dataset/v1",
            "source_dataset_digest": identity["dataset_digest"],
            "prepared_dataset_digest": identity["dataset_digest"],
            "rectified": False,
            "protocol": TRAINING_PROTOCOL["undistortion"],
        },
    )
    (output / "heldout").mkdir()
    render = output / "heldout" / "a.png"
    render.write_bytes(b"fixture-render")
    metrics = json.loads((output / "metrics.json").read_bytes())
    metrics.update(identity)
    metrics.update(
        heldout_views=1,
        per_view=[
            {
                "render": "heldout/a.png",
                "render_sha256": _sha(render.read_bytes()),
                "source_sha256": manifest.heldout_source_sha256[0],
                "reference_pixels_sha256": manifest.heldout_source_sha256[0],
            }
        ],
    )
    _write(output / "metrics.json", metrics)
    runtime = json.loads((output / "runtime.json").read_bytes())
    runtime.update(identity)
    runtime.update(
        split_sha256=_sha((output / "split.json").read_bytes()),
        prepared_dataset_receipt_sha256=_sha((output / "training" / "dataset.json").read_bytes()),
    )
    _write(output / "runtime.json", runtime)
    if delivery:
        sog = output / "scene.sog"
        sog.write_bytes(b"fixture-sog")
        quality = _quality(manifest, output, delivery=sog)
        _write(
            output.parent / "receipt.json",
            {
                "manifest_digest": manifest.digest,
                "quality_digest": _sha(_canonical(quality.as_payload())),
            },
        )


@pytest.mark.parametrize(
    "psnr,delivery,expected",
    [(1, False, "training"), (28, False, "conversion"), (28, True, "display")],
)
def test_training_conversion_and_display_are_separate_without_retraining(
    run, psnr, delivery, expected
):
    _completed(run, psnr=psnr, delivery=delivery)
    report = inspect_local_run(**run)
    assert report["blockers"][0]["stage"] == expected
    assert report["run"] is None
    assert report["acceptance"]["accepted"] is False
    if expected != "training":
        assert any(r["kind"] == "trained_ply" for r in report["reuse"])


def test_cached_render_tamper_is_not_reusable_training(run):
    _completed(run)
    (run["output"] / "heldout" / "a.png").write_bytes(b"changed")
    assert inspect_local_run(**run)["blockers"][0]["stage"] == "training"


class _Connection:
    @contextmanager
    def transaction(self):
        yield

    def execute(self, sql):
        assert "read only" in sql


@pytest.mark.parametrize("allowed", [[False], [True, False], [True, True]])
def test_live_read_rights_checked_before_and_after_inspection(monkeypatch, allowed):
    pose = {"manifest_digest": "d" * 64, "quality": {"accepted": False, "registered_images": []}}
    pose["quality_digest"] = _sha(_canonical(pose["quality"]))
    row = {"content_sha256": bytes.fromhex("e" * 64), "job_id": uuid.uuid4()}
    manifest = {"frames": [{"sha256": c * 64} for c in "abc"]}
    monkeypatch.setattr(preflight, "scene_inputs", lambda *a: (row, manifest))
    states = iter(allowed)
    monkeypatch.setattr(preflight, "scene_allowed", lambda *a: next(states))
    monkeypatch.setattr(preflight, "evaluation_time", lambda *a: None)
    monkeypatch.setattr(preflight, "_verified", lambda *a: _canonical(pose))

    @contextmanager
    def check(*args):
        yield None

    monkeypatch.setattr(preflight, "final_check", check)
    result = preflight.prepare_current_scene_run(
        _Connection(), None, workspace=uuid.uuid4(), scene=uuid.uuid4()
    )
    assert result["blockers"][0]["stage"] == ("pose" if allowed == [True, True] else "rights")
    assert result["run"] is None
    if allowed != [True, True]:
        assert "bindings" not in result


def test_masked_original_split_maps_to_exact_derivative_without_original_reads(run):
    original = "9" * 64
    derivative = _manifest().source_sha256[0]
    manifest = _manifest(masked_source_remap=((str(uuid.UUID(int=1)), original, derivative),))
    _write(run["manifest_path"], manifest.as_payload())
    frozen = json.loads(run["source_manifest"].read_bytes())["record"]
    frozen["files"][0]["sha256"] = original
    frozen["evaluation_split"]["heldout_sha256"] = [original]
    _write(run["source_manifest"], envelope(frozen))
    result = inspect_local_run(**run)
    assert result["status"] == "plan_ready"
    assert result["run"]["manifest"]["parameters"]["masked_source_remap"]
    assert result["bindings"]["heldout_source_sha256"] == [derivative]
    assert not any(original in p.name for p in run["dataset"].rglob("*"))


def test_unsupported_runner_revision_is_a_tool_blocker(run):
    _write(run["manifest_path"], _manifest(gsplat_revision="e" * 40).as_payload())
    assert inspect_local_run(**run)["blockers"][0]["stage"] == "tool"


def test_actual_cpu_checkpoint_passes_existing_complete_state_validator(run):
    torch = pytest.importorskip("torch")
    pytest.importorskip("numpy")
    from exulanica.reconstruction.gsplat_runner import save_checkpoint

    parameters = torch.nn.ParameterDict({"means": torch.nn.Parameter(torch.tensor([0.2]))})
    optimizers = {"means": torch.optim.Adam([parameters["means"]], lr=0.01)}
    scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizers["means"], gamma=0.9)
    identity = {
        "manifest_digest": _manifest().digest,
        "dataset_digest": dataset_digest(run["dataset"]),
    }
    save_checkpoint(
        run["output"] / "checkpoints",
        identity=identity,
        step=0,
        splats=parameters,
        optimizers=optimizers,
        scheduler=scheduler,
        strategy_state={},
        sampler={},
        duration_seconds=1,
        peak_vram_bytes=0,
    )
    result = inspect_local_run(**run)
    assert result["status"] == "plan_ready"
    assert result["reuse"][-1]["kind"] == "checkpoint"
    assert result["reuse"][-1]["next_iteration"] == 0


def test_unreadable_serialized_checkpoint_is_a_blocker(run, monkeypatch):
    import pickle

    _pointer(run)

    def invalid(*args, **kwargs):
        raise pickle.UnpicklingError("checkpoint state is not readable")

    monkeypatch.setattr(preflight, "load_checkpoint", invalid)
    result = inspect_local_run(**run)
    assert result["blockers"][0]["stage"] == "checkpoint"
    assert result["run"] is None


def test_non_object_manifest_is_schema_rejection(run):
    run["manifest_path"].write_text("[]")
    result = inspect_local_run(**run)
    assert result["blockers"][0]["stage"] == "training"
    assert result["run"] is None
