"""The production queue consumer from source photographs through the scene rung assertion."""

from __future__ import annotations

import dataclasses
import json
import math
import os
import threading
import time
import uuid
from array import array
from pathlib import Path

import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.evidence.blob import BlobId
from exulanica.graph import read_snapshot
from exulanica.graph.geometry import point_map_descriptors, read_point_map
from exulanica.ingest.operations import reconstruction_scene_metrics
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.reconstruction_scratch import (
    ScratchSource,
    active_scene_scratch,
    cleanup_abandoned_scene_scratch,
    stage_scene_sources,
)
from exulanica.ingest.scene_reconstruction import SceneReconstructionProcessor
from exulanica.ingest.scenes import run_scene_grouping
from exulanica.ingest.spine.reconstruction_jobs import MAX_SCENE_CLAIMS
from exulanica.ingest.stages import (
    STAGES,
    artifact_id_for,
    idempotency_key,
    input_digest_of,
    scene_pose_quality_thresholds,
    stage,
)
from exulanica.reconstruction.opm import Viewpoint, encode_opm
from exulanica.reconstruction.pointmap import PointMap, Segment
from exulanica.reconstruction.pose import CommandResult
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world_package import project_world_package
from PIL import Image

from conftest import CountingVisionModel, write_photo, write_point_map

_CODE_REVISION = "a" * 40
_EXECUTION_IMAGE = "registry.example/exulanica-pose@sha256:" + "b" * 64


def _numeric_point_map(index: int, *, color: int = 128) -> bytes:
    """A known plane in a camera frame, used only to exercise production byte alignment."""
    width, height = 160 + index, 100
    focal = height / (2 * math.tan(math.radians(60) / 2))
    positions = array("f")
    for y in range(height):
        for x in range(width):
            positions.extend(
                ((x + 0.5 - width / 2) / focal * 3, -(y + 0.5 - height / 2) / focal * 3, -3)
            )
    count = width * height
    points = PointMap(
        positions,
        bytearray([color, color, color, 255] * count),
        array("H", [0, 0] * count),
        [Segment(0, "unsegmented", "unknown")],
    )
    return encode_opm(
        points,
        generator="numeric-pipeline-test",
        viewpoint=Viewpoint(60, width / height),
        source_size=(width, height),
        model_size=(width, height),
        color_alpha="support",
        metric=False,
    )


class FakeColmap:
    def __init__(
        self,
        *,
        registered: int = 2,
        crash_stage: str | None = None,
        fail_stage: str | None = None,
        delete_during=None,
        camera_spacing: float = 1,
    ) -> None:
        self.calls: list[str] = []
        self.registered = registered
        self.crash_stage = crash_stage
        self.fail_stage = fail_stage
        self.delete_during = delete_during
        self.camera_spacing = camera_spacing

    def __call__(self, command: tuple[str, ...], cwd: Path) -> CommandResult:
        stage = command[1]
        self.calls.append(stage)
        if stage == self.crash_stage:
            raise SystemExit("simulated process death")
        if stage == self.fail_stage:
            return CommandResult(9, "", "measured pose failure", 1.0)
        (cwd / "database.db").write_bytes(stage.encode())
        if self.delete_during is not None:
            callback, self.delete_during = self.delete_during, None
            callback()
        if stage == "mapper":
            source_directory = Path(command[command.index("--image_path") + 1])
            names = sorted(path.name for path in source_directory.iterdir())[: self.registered]
            model = cwd / "sparse" / "0"
            model.mkdir(parents=True)
            # One shared world plane, projected from each recovered camera. Every track
            # points at real corresponding 2D observations; no fake third-camera support.
            sizes = [Image.open(source_directory / name).size for name in names]
            pixels = [[] for _ in names]
            sparse = []
            for iy in range(11):
                for ix in range(17):
                    point_id = iy * 17 + ix + 1
                    wx, wy, wz = (
                        value * self.camera_spacing
                        for value in (-2 + ix * 0.35, -2 + iy * 0.4, 6.0)
                    )
                    track = []
                    for index, (width, height) in enumerate(sizes):
                        focal = height / (2 * math.tan(math.radians(60) / 2))
                        u = (wx - (index + 1) * self.camera_spacing) / wz * focal + width / 2
                        v = wy / wz * focal + height / 2
                        if 0 <= u < width and 0 <= v < height:
                            track.extend((index + 1, len(pixels[index])))
                            pixels[index].append((u, v, point_id))
                    sparse.append(
                        f"{point_id} {wx} {wy} {wz} 128 128 128 0.4 " + " ".join(map(str, track))
                    )
            lines = []
            for index, name in enumerate(names, 1):
                lines.extend(
                    [
                        f"{index} 1 0 0 0 {-index * self.camera_spacing} 0 0 {index} {name}",
                        " ".join(" ".join(map(str, pixel)) for pixel in pixels[index - 1]),
                    ]
                )
            (model / "images.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            (model / "points3D.txt").write_text("\n".join(sparse) + "\n", encoding="utf-8")
            (model / "cameras.txt").write_text(
                "\n".join(
                    f"{index} PINHOLE {width} {height} "
                    f"{height / (2 * math.tan(math.radians(60) / 2))} "
                    f"{height / (2 * math.tan(math.radians(60) / 2))} {width / 2} {height / 2}"
                    for index, (width, height) in enumerate(sizes, 1)
                )
                + "\n",
                encoding="utf-8",
            )
        return CommandResult(0, "ok", "", 1.0)


def _queued_scene(repository, tmp_path: Path, *, point_maps: int = 3):
    store = LocalContentAddressedStore(tmp_path / "store")
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())
    photo_directory = tmp_path / "photos"
    photo_directory.mkdir(exist_ok=True)
    captures: list[uuid.UUID] = []
    point_artifacts: list[uuid.UUID] = []
    for index in range(3):
        path = write_photo(
            photo_directory,
            f"{index}.jpg",
            when=f"2026:09:04 12:0{index}:00",
            size=(160 + index, 100),
        )
        outcome = pipeline.ingest_file(path)
        assert outcome.error is None
        assert outcome.capture_id is not None
        captures.append(outcome.capture_id)
        if index < point_maps:
            point_artifact, _content = write_point_map(
                repository,
                store,
                BlobId.of_bytes(path.read_bytes()),
                payload=_numeric_point_map(index),
            )
            point_artifacts.append(point_artifact)
    report = run_scene_grouping(repository)
    if point_maps == len(captures):
        assert len(report.reconstruction_jobs) == 1
        job_id = report.reconstruction_jobs[0]
    else:
        assert report.reconstruction_jobs == []
        job_id = None
    return store, captures, point_artifacts, job_id


def _processor(repository, store, tmp_path: Path, executor: FakeColmap):
    return SceneReconstructionProcessor(
        repository,
        store,
        tmp_path / "scratch",
        code_revision=_CODE_REVISION,
        execution_image=_EXECUTION_IMAGE,
        colmap_version="pycolmap test",
        executor=executor,
        retry_delay_seconds=0,
    )


def test_scene_group_pose_placement_gate_and_assertion_commit_together(repository, tmp_path):
    store, captures, point_artifacts, job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="test", lease_seconds=60)
    assert claimed is not None and claimed.job_id == job_id

    outcome = _processor(repository, store, tmp_path, FakeColmap(registered=2)).process(claimed)

    assert outcome.status == "succeeded"
    assert outcome.rung == 3
    assert outcome.registered_member_count == 2
    job = repository.connection.execute(
        "select status,pose_manifest_digest,pose_receipt_artifact_id,placement_artifact_id,"
        "gate_artifact_id from reconstruction_scene_job where workspace_id=%s and job_id=%s",
        (repository.workspace_id, job_id),
    ).fetchone()
    assert job is not None and job["status"] == "succeeded"
    assert bytes(job["pose_manifest_digest"])
    artifacts = repository.connection.execute(
        "select artifact_id,kind,content_sha256 from artifact where workspace_id=%s "
        "and scene_id=%s order by kind",
        (repository.workspace_id, outcome.scene_id),
    ).fetchall()
    assert {row["kind"] for row in artifacts} == {
        "pose_receipt",
        "point_map_placement",
        "scene_gate_receipt",
    }
    assert {
        job["pose_receipt_artifact_id"],
        job["placement_artifact_id"],
        job["gate_artifact_id"],
    } == {row["artifact_id"] for row in artifacts}
    members = repository.reconstruction_scene_members(outcome.scene_id)
    assert [(member.capture_id, member.registered) for member in members] == [
        (captures[0], True),
        (captures[1], True),
        (captures[2], False),
    ]
    placement_row = next(row for row in artifacts if row["kind"] == "point_map_placement")
    placement = json.loads(store.get(BlobId(bytes(placement_row["content_sha256"]))))["placement"]
    assert [member["point_map_artifact_ref"] for member in placement["placed"]] == [
        str(point_artifacts[0]),
        str(point_artifacts[1]),
    ]
    assert placement["excluded"] == [
        {
            "capture_ref": str(captures[2]),
            "reason": "pose-not-registered",
            "registered": False,
            "alignment": None,
        }
    ]
    assertion = repository.connection.execute(
        "select object_value from assertion where workspace_id=%s "
        "and subject_ref->>'id'=%s and status='active'",
        (repository.workspace_id, str(outcome.scene_id)),
    ).fetchone()
    assert assertion is not None
    assert assertion["object_value"]["rung"] == 3
    assert assertion["object_value"]["registered_member_count"] == 2
    assert "gate_digest" in assertion["object_value"]
    assert not (tmp_path / "scratch" / claimed.scratch_key).exists()

    second_report = run_scene_grouping(repository)
    assert second_report.reconstruction_jobs == [job_id]
    assert repository.claim_reconstruction_scene(worker="test", lease_seconds=60) is None
    assert (
        repository.connection.execute(
            "select count(*) as count from artifact where workspace_id=%s and scene_id=%s",
            (repository.workspace_id, outcome.scene_id),
        ).fetchone()["count"]
        == 3
    )


def test_scene_pose_manifest_uses_the_exact_quantized_stage_policy(
    repository, tmp_path, monkeypatch
):
    current = STAGES["scene_pose"]
    params = {
        "controller": "colmap-sparse-checkpointed",
        "receipt_profile": "exulanica.colmap-pose-receipt/v2",
        "min_registered_fraction_millionths": 750_000,
        "max_mean_reprojection_error_micropixels": 1_250_000,
        "min_camera_translation_microunits": 500_000,
    }
    monkeypatch.setitem(
        STAGES,
        "scene_pose",
        dataclasses.replace(current, version=current.version + 1, params=params),
    )
    store, _captures, _artifacts, job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="policy-test", lease_seconds=60)
    assert claimed is not None and claimed.job_id == job_id

    outcome = _processor(repository, store, tmp_path, FakeColmap(registered=3)).process(claimed)

    assert outcome.status == "succeeded"
    row = repository.connection.execute(
        "select content_sha256 from artifact where workspace_id=%s and scene_id=%s "
        "and kind='pose_receipt'",
        (repository.workspace_id, outcome.scene_id),
    ).fetchone()
    assert row is not None
    receipt = json.loads(store.get(BlobId(bytes(row["content_sha256"]))))
    assert receipt["manifest"]["quality_thresholds"] == {
        "min_registered_fraction": 0.75,
        "max_mean_reprojection_error_px": 1.25,
        "min_camera_translation_units": 0.5,
    }
    assert receipt["quality"]["accepted"] is True


def test_current_scene_pose_policy_is_bound_to_the_fixed_calibration_and_real_capture_runs():
    """Version 4 keeps the two synthetic/benchmark calibrations and records the real captures
    whose fully registered, sub-pixel models the version 3 floor of 9.0 units refused."""
    current = STAGES["scene_pose"]
    thresholds = scene_pose_quality_thresholds(current)
    calibration = current.params["calibration"]

    assert current.version == 4
    assert thresholds.min_registered_fraction == 0.8
    assert thresholds.max_mean_reprojection_error_px == 1.0
    assert thresholds.min_camera_translation_units == 5.0
    assert calibration["synthetic_pose_evaluation_sha256"] == (
        "dc0680b24fc85ba3ebe2ed55d3ed92a10e9ea161ded9701b73014c336808c5d7"
    )
    assert calibration["benchmark_pose_evaluation_sha256"] == (
        "68640ca95fce5adf54d8217b53139a4706edf6c6430cd6d854b58079b59408d8"
    )
    real = calibration["real_capture_observations"]
    assert [(run["photographs"], run["camera_translation_extent_microunits"]) for run in real] == [
        (40, 8_132_481),
        (51, 8_961_565),
    ]
    assert all(run["registered_fraction_millionths"] == 1_000_000 for run in real)
    assert all(run["mean_reprojection_error_micropixels"] < 1_000_000 for run in real)
    assert all(
        run["camera_translation_extent_microunits"] > thresholds.min_camera_translation_units * 1e6
        for run in real
    ), "the recorded real captures must pass the floor this version chose"
    assert all(len(run["pose_receipt_sha256"]) == 64 for run in real)


def test_stale_stage_bindings_are_refused_before_any_pose_work_runs(repository, tmp_path):
    """MEASURED 2026-09-05: a job queued under an earlier stage version ran thirty minutes of
    COLMAP before the binding check refused it. The refusal must come first."""
    import dataclasses
    import hashlib

    from exulanica.canonical import canonical_json

    store, captures, point_artifacts, job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="test", lease_seconds=60)
    assert claimed is not None and claimed.job_id == job_id
    stale_inputs = dict(claimed.build_inputs)
    stale_inputs["stages"] = [
        {**binding, "version": binding["version"] - 1} if binding["key"] == "scene_pose" else binding
        for binding in claimed.build_inputs["stages"]
    ]
    stale = dataclasses.replace(
        claimed,
        build_inputs=stale_inputs,
        build_input_digest=hashlib.sha256(canonical_json(stale_inputs)).digest(),
    )
    executor = FakeColmap(registered=2)

    outcome = _processor(repository, store, tmp_path, executor).process(stale)

    assert outcome.status == "failed"
    assert "stage bindings are no longer current" in (outcome.message or "")
    assert executor.calls == [], "no COLMAP stage may run for a job the current rules refuse"
    job = repository.reconstruction_scene_job(job_id)
    assert job is not None and job.status == "failed"


def test_a_new_point_map_build_supersedes_the_displayed_build_without_rewriting_history(
    repository, tmp_path
):
    store, captures, point_artifacts, first_job_id = _queued_scene(repository, tmp_path)
    first_claim = repository.claim_reconstruction_scene(worker="first", lease_seconds=60)
    assert first_claim is not None
    first = _processor(repository, store, tmp_path, FakeColmap(registered=2)).process(first_claim)
    assert first.status == "succeeded"

    capture = repository.capture(captures[0])
    assert capture is not None
    spec = stage("depth")
    input_digest = input_digest_of([])
    key = idempotency_key(
        capture.blob_id,
        spec,
        input_digest,
        binding={"model_id": "test/depth-model-v2"},
    )
    replacement_id = artifact_id_for(key)
    replacement = store.put_bytes(_numeric_point_map(0, color=129))
    privacy = repository.connection.execute(
        "select privacy_screening_id from artifact where workspace_id=%s and artifact_id=%s",
        (repository.workspace_id, point_artifacts[0]),
    ).fetchone()
    assert privacy is not None
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
        privacy_screening_id=privacy["privacy_screening_id"],
    )
    repository.connection.execute(
        "update artifact set superseded_by=%s where workspace_id=%s and artifact_id=%s",
        (replacement_id, repository.workspace_id, point_artifacts[0]),
    )

    report = run_scene_grouping(repository)
    assert len(report.reconstruction_jobs) == 1
    second_job_id = report.reconstruction_jobs[0]
    assert second_job_id != first_job_id
    second_claim = repository.claim_reconstruction_scene(worker="second", lease_seconds=60)
    assert second_claim is not None and second_claim.job_id == second_job_id
    second = _processor(repository, store, tmp_path, FakeColmap(registered=2)).process(second_claim)
    assert second.status == "succeeded"

    scene = repository.connection.execute(
        "select current_job_id from reconstruction_scene where workspace_id=%s and scene_id=%s",
        (repository.workspace_id, first.scene_id),
    ).fetchone()
    assert scene == {"current_job_id": second_job_id}
    jobs = repository.connection.execute(
        "select job_id,status from reconstruction_scene_job where workspace_id=%s "
        "and scene_id=%s order by created_at,job_id",
        (repository.workspace_id, first.scene_id),
    ).fetchall()
    assert {row["job_id"] for row in jobs} == {first_job_id, second_job_id}
    assert {row["status"] for row in jobs} == {"succeeded"}
    first_members = repository.reconstruction_scene_members(
        first.scene_id,
        job_id=first_job_id,
    )
    second_members = repository.reconstruction_scene_members(
        first.scene_id,
        job_id=second_job_id,
    )
    assert [member.registered for member in first_members] == [True, True, False]
    assert [member.registered for member in second_members] == [True, True, False]
    graph_scene = read_snapshot(
        repository.connection,
        repository.workspace_id,
        store,
    ).reconstruction_scenes[0]
    assert [member.registered for member in graph_scene.members] == [True, True, False]
    assert graph_scene.members[0].placement is not None
    assert graph_scene.members[0].placement.artifact_id == replacement_id
    metrics = reconstruction_scene_metrics(
        repository.connection,
        repository.workspace_id,
    )
    assert metrics["coordination"]["state"] == "ready"
    assert metrics["scenes"] == {
        "live": 1,
        "published": 1,
        "superseded_builds": 1,
    }
    assertion_counts = repository.connection.execute(
        "select count(*) as count,count(*) filter (where status='active') as active "
        "from assertion where workspace_id=%s and subject_ref->>'id'=%s",
        (repository.workspace_id, str(first.scene_id)),
    ).fetchone()
    assert assertion_counts == {"count": 2, "active": 1}
    package = project_world_package(
        repository.connection,
        workspace_id=repository.workspace_id,
        actor=uuid.uuid4(),
        output=tmp_path / "rebuilt-package",
        private_key=Ed25519PrivateKey.generate(),
    )
    reconstruction = json.loads(
        (package.output / "reconstruction/artifacts.json").read_text(encoding="utf-8")
    )
    assert len(reconstruction["rung_claims"]) == 1
    assert len([item for item in reconstruction["items"] if item["scene"] is not None]) == 3
    with (
        pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"),
        repository.connection.transaction(),
    ):
        repository.connection.execute(
            "update reconstruction_scene set current_job_id=%s "
            "where workspace_id=%s and scene_id=%s",
            (first_job_id, repository.workspace_id, first.scene_id),
        )


def test_object_store_failure_keeps_a_prepared_scene_private_and_retryable(
    repository, tmp_path, monkeypatch
):
    store, _captures, _point_artifacts, job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="first", lease_seconds=60)
    assert claimed is not None
    put_bytes = store.put_bytes

    def refuse_write(_payload: bytes) -> None:
        raise OSError("simulated object-store outage")

    monkeypatch.setattr(store, "put_bytes", refuse_write)
    failed = _processor(repository, store, tmp_path, FakeColmap(registered=2)).process(claimed)

    assert failed.status == "failed"
    job = repository.connection.execute(
        "select status,completed_at from reconstruction_scene_job "
        "where workspace_id=%s and job_id=%s",
        (repository.workspace_id, job_id),
    ).fetchone()
    assert job == {"status": "failed", "completed_at": None}
    assert (
        read_snapshot(repository.connection, repository.workspace_id, store).reconstruction_scenes
        == []
    )
    package = project_world_package(
        repository.connection,
        workspace_id=repository.workspace_id,
        actor=uuid.uuid4(),
        output=tmp_path / "prepared-package",
        private_key=Ed25519PrivateKey.generate(),
    )
    reconstruction = json.loads(
        (package.output / "reconstruction/artifacts.json").read_text(encoding="utf-8")
    )
    assert reconstruction["scenes"] == []
    assert not any(item["scene"] is not None for item in reconstruction["items"])

    monkeypatch.setattr(store, "put_bytes", put_bytes)
    retried_claim = repository.claim_reconstruction_scene(worker="second", lease_seconds=60)
    assert retried_claim is not None
    retried = _processor(repository, store, tmp_path, FakeColmap(registered=2)).process(
        retried_claim
    )

    assert retried.status == "succeeded"
    assert (
        len(
            read_snapshot(
                repository.connection, repository.workspace_id, store
            ).reconstruction_scenes
        )
        == 1
    )


def test_graph_delivers_the_validated_scene_and_exact_placed_maps(repository, tmp_path):
    store, captures, point_artifacts, _job_id = _queued_scene(repository, tmp_path)
    before_version = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).state_version
    claimed = repository.claim_reconstruction_scene(worker="test", lease_seconds=60)
    assert claimed is not None
    outcome = _processor(repository, store, tmp_path, FakeColmap(registered=2)).process(claimed)

    graph = read_snapshot(repository.connection, repository.workspace_id, store)

    assert graph.state_version == before_version + 2
    assert len(graph.reconstruction_scenes) == 1
    scene = graph.reconstruction_scenes[0]
    assert scene.scene_id == outcome.scene_id
    assert scene.recorded_rung == scene.displayed_rung == 3
    assert scene.receipt_state == "available"
    assert scene.placement_state == "available"
    assert scene.rendering_substrate == "posed_point_maps"
    assert [member.capture_id for member in scene.members] == captures
    assert [
        member.placement.artifact_id for member in scene.members if member.placement is not None
    ] == point_artifacts[:2]
    assert all(
        member.placement.reference.content_sha256 == member.placement.content_sha256
        for member in scene.members
        if member.placement is not None and member.placement.reference is not None
    )
    assert scene.members[2].exclusion_reason == "pose-not-registered"


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_graph_falls_back_to_photographs_when_a_scene_receipt_is_unusable(
    repository, tmp_path, damage
):
    store, _captures, _point_artifacts, _job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="test", lease_seconds=60)
    assert claimed is not None
    outcome = _processor(repository, store, tmp_path, FakeColmap(registered=3)).process(claimed)
    row = repository.connection.execute(
        "select a.content_sha256 from reconstruction_scene_job j join artifact a "
        "on a.workspace_id=j.workspace_id and a.artifact_id=j.placement_artifact_id "
        "where j.workspace_id=%s and j.scene_id=%s",
        (repository.workspace_id, outcome.scene_id),
    ).fetchone()
    digest = BlobId(bytes(row["content_sha256"]))
    path = store.root / store.key_for(digest)
    path.chmod(0o644)
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"not the placement receipt")

    scene = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]

    assert scene.recorded_rung == 3
    assert scene.displayed_rung == 4
    assert scene.rendering_substrate == "source_photographs"
    assert scene.receipt_state == ("missing" if damage == "missing" else "invalid")
    assert all(member.placement is None for member in scene.members)


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_graph_withholds_a_missing_alignment_input_but_preserves_healthy_members(
    repository, tmp_path, damage
):
    store, captures, point_artifacts, _job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="alignment-test", lease_seconds=60)
    assert claimed is not None
    outcome = _processor(repository, store, tmp_path, FakeColmap(registered=3)).process(claimed)
    assert outcome.status == "succeeded"
    row = repository.connection.execute(
        "select content_sha256 from artifact where workspace_id=%s and artifact_id=%s",
        (repository.workspace_id, point_artifacts[1]),
    ).fetchone()
    path = store.root / store.key_for(BlobId(bytes(row["content_sha256"])))
    path.chmod(0o644)
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"corrupt OPM input")
    scene = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert scene.recorded_rung == 3 and scene.displayed_rung == 3
    assert scene.placement_state == "partial"
    assert scene.members[0].placement is not None
    assert scene.members[1].capture_id == captures[1]
    assert scene.members[1].placement is None
    assert scene.members[1].exclusion_reason == "alignment-unavailable"
    assert scene.members[2].placement is not None


def test_deleting_one_scene_member_withdraws_it_from_the_graph(repository, tmp_path):
    store, captures, _point_artifacts, _job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="test", lease_seconds=60)
    assert claimed is not None
    _processor(repository, store, tmp_path, FakeColmap(registered=3)).process(claimed)
    before = read_snapshot(repository.connection, repository.workspace_id, store)
    assert len(before.reconstruction_scenes) == 1
    assert point_map_descriptors(repository.connection, repository.workspace_id, store) == ()

    repository.insert_tombstone(
        scope="capture",
        capture_id=captures[1],
        requested_by=uuid.uuid4(),
        reason="withdraw the complete reconstruction scene",
    )
    after = read_snapshot(repository.connection, repository.workspace_id, store)

    assert after.state_version == before.state_version + 1
    assert after.reconstruction_scenes == []
    # The old descriptor list cannot reintroduce a surviving member at the island origin after
    # the scene placement is withdrawn. Exact artifact reads remain available for surviving
    # captures, which is what lets another valid scene refer to the same immutable point map.
    assert point_map_descriptors(repository.connection, repository.workspace_id, store) == ()
    assert (
        read_point_map(
            repository.connection,
            repository.workspace_id,
            _point_artifacts[0],
            store,
        )
        is not None
    )


def test_a_process_death_resumes_from_the_last_pose_checkpoint(ingest_spine, tmp_path):
    repository, reopen = ingest_spine
    store, _captures, _point_artifacts, job_id = _queued_scene(repository, tmp_path)
    first = repository.claim_reconstruction_scene(worker="first", lease_seconds=60)
    assert first is not None
    crashing = FakeColmap(registered=3, crash_stage="exhaustive_matcher")

    with pytest.raises(SystemExit, match="simulated process death"):
        _processor(repository, store, tmp_path, crashing).process(first)
    assert crashing.calls == ["feature_extractor", "exhaustive_matcher"]
    assert (tmp_path / "scratch" / first.scratch_key).exists()
    repository.connection.execute(
        "update reconstruction_scene_job set lease_expires_at=now()-interval '1 second' "
        "where workspace_id=%s and job_id=%s",
        (repository.workspace_id, job_id),
    )
    restarted = reopen()
    second = restarted.claim_reconstruction_scene(worker="second", lease_seconds=60)
    assert second is not None and second.reclaimed
    resumed = FakeColmap(registered=3)

    outcome = _processor(restarted, store, tmp_path, resumed).process(second)

    assert outcome.status == "succeeded"
    assert resumed.calls == ["exhaustive_matcher", "mapper"]
    assert not (tmp_path / "scratch" / second.scratch_key).exists()


def test_an_expired_final_claim_becomes_terminal_and_releases_its_scratch(repository, tmp_path):
    store, _captures, _point_artifacts, job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="last", lease_seconds=60)
    assert claimed is not None and claimed.scratch_key is not None
    with active_scene_scratch(tmp_path / "scratch", claimed.scratch_key) as job_directory:
        stage_scene_sources(
            store,
            job_directory,
            [ScratchSource("000000.jpg", claimed.members[0].blob_id)],
        )
    old_time = time.time() - 7200
    os.utime(tmp_path / "scratch" / claimed.scratch_key, (old_time, old_time))
    repository.connection.execute(
        "update reconstruction_scene_job set attempts=%s, "
        "lease_expires_at=now()-interval '1 second' "
        "where workspace_id=%s and job_id=%s",
        (MAX_SCENE_CLAIMS, repository.workspace_id, job_id),
    )

    assert repository.expire_exhausted_reconstruction_scenes() == 1
    row = repository.connection.execute(
        "select status,completed_at,failure_class,claim_token from reconstruction_scene_job "
        "where workspace_id=%s and job_id=%s",
        (repository.workspace_id, job_id),
    ).fetchone()
    assert row["status"] == "failed"
    assert row["completed_at"] is not None
    assert row["failure_class"] == "claim_exhausted"
    assert row["claim_token"] is None
    assert claimed.scratch_key not in repository.active_reconstruction_scratch_keys()
    assert cleanup_abandoned_scene_scratch(
        tmp_path / "scratch",
        active_keys=repository.active_reconstruction_scratch_keys(),
        older_than_seconds=3600,
    ) == (claimed.scratch_key,)


def test_scene_object_lock_survives_row_commit_until_publication(ingest_spine):
    repository, reopen = ingest_spine
    content_id = BlobId.of_bytes(b"scene receipt")
    attempted = threading.Event()
    acquired = threading.Event()

    def purger_lock() -> None:
        contender = reopen()
        with contender.connection.transaction():
            attempted.set()
            contender.connection.execute("select purge_lock_object(%s)", (content_id.hex,))
            acquired.set()

    contender_thread = threading.Thread(target=purger_lock)
    with repository.locked_stored_objects([content_id]):
        with repository.transaction():
            repository.connection.execute("select 1")
        contender_thread.start()
        assert attempted.wait(5)
        assert not acquired.wait(0.2)

    assert acquired.wait(5)
    contender_thread.join(timeout=5)
    assert not contender_thread.is_alive()


def test_deletion_during_pose_cancels_without_scene_outputs(repository, tmp_path):
    store, captures, _point_artifacts, job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="test", lease_seconds=60)
    assert claimed is not None

    def delete_member() -> None:
        repository.insert_tombstone(
            scope="capture",
            capture_id=captures[1],
            requested_by=uuid.uuid4(),
            reason="deleted while pose recovery was running",
        )

    executor = FakeColmap(registered=3, delete_during=delete_member)
    outcome = _processor(repository, store, tmp_path, executor).process(claimed)

    assert outcome.status == "cancelled"
    row = repository.connection.execute(
        "select status from reconstruction_scene_job where workspace_id=%s and job_id=%s",
        (repository.workspace_id, job_id),
    ).fetchone()
    assert row == {"status": "cancelled"}
    assert (
        repository.connection.execute(
            "select count(*) as count from reconstruction_scene where workspace_id=%s",
            (repository.workspace_id,),
        ).fetchone()["count"]
        == 0
    )
    assert (
        repository.connection.execute(
            "select count(*) as count from artifact where workspace_id=%s and scene_id is not null",
            (repository.workspace_id,),
        ).fetchone()["count"]
        == 0
    )
    assert not (tmp_path / "scratch" / claimed.scratch_key).exists()


def test_failed_pose_is_retryable_and_its_sensitive_scratch_is_removed(repository, tmp_path):
    store, _captures, _point_artifacts, job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="test", lease_seconds=60)
    assert claimed is not None

    outcome = _processor(
        repository,
        store,
        tmp_path,
        FakeColmap(fail_stage="exhaustive_matcher"),
    ).process(claimed)

    assert outcome.status == "failed"
    row = repository.connection.execute(
        "select status,attempts,completed_at from reconstruction_scene_job "
        "where workspace_id=%s and job_id=%s",
        (repository.workspace_id, job_id),
    ).fetchone()
    assert row == {"status": "failed", "attempts": 1, "completed_at": None}
    assert not (tmp_path / "scratch" / claimed.scratch_key).exists()


def test_incomplete_point_maps_defer_pose_until_the_last_exact_input_arrives(repository, tmp_path):
    store, captures, point_artifacts, job_id = _queued_scene(repository, tmp_path, point_maps=2)
    assert job_id is None
    assert repository.claim_reconstruction_scene(worker="test", lease_seconds=60) is None
    waiting = reconstruction_scene_metrics(
        repository.connection,
        repository.workspace_id,
    )
    assert waiting["coordination"]["state"] == "blocked"
    assert waiting["depth"]["waiting_for_point_maps"] == 1
    capture = repository.capture(captures[2])
    assert capture is not None
    final_artifact, _content = write_point_map(
        repository,
        store,
        capture.blob_id,
        payload=_numeric_point_map(2),
    )
    point_artifacts.append(final_artifact)
    report = run_scene_grouping(repository)
    assert len(report.reconstruction_jobs) == 1
    claimed = repository.claim_reconstruction_scene(worker="test", lease_seconds=60)
    assert claimed is not None

    outcome = _processor(repository, store, tmp_path, FakeColmap(registered=3)).process(claimed)

    assert outcome.status == "succeeded"
    row = repository.connection.execute(
        "select content_sha256 from artifact where workspace_id=%s and scene_id=%s "
        "and kind='point_map_placement'",
        (repository.workspace_id, outcome.scene_id),
    ).fetchone()
    placement = json.loads(store.get(BlobId(bytes(row["content_sha256"]))))["placement"]
    assert placement["excluded"] == []
    assert [item["point_map_artifact_ref"] for item in placement["placed"]] == [
        str(artifact_id) for artifact_id in point_artifacts
    ]
