"""The production queue consumer from source photographs through the scene rung assertion."""

from __future__ import annotations

import dataclasses
import hashlib
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
from exulanica.graph.asset_read_policy import (
    _manifest_and_digest,
    clear_scene_inputs_memo,
    scene_inputs,
    scene_inputs_memo_frames,
    scene_inputs_memo_size,
)
from exulanica.graph.geometry import point_map_descriptors, read_point_map
from exulanica.graph.reconstruction_scenes import (
    _MEMO_MAX_MEMBERS,
    _memo,
    _memo_get,
    _memo_put,
    clear_placement_memo,
    placement_memo_members,
    placement_memo_size,
)
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
        "scene_projection",
    }
    # The projection is the one scene artifact with no column on the job row. It is found by the
    # graph through its bindings instead, which is why the job still names exactly three.
    assert {
        job["pose_receipt_artifact_id"],
        job["placement_artifact_id"],
        job["gate_artifact_id"],
    } == {row["artifact_id"] for row in artifacts if row["kind"] != "scene_projection"}
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
        == 4
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
    from exulanica.ingest.operations import reconstruction_scene_job

    store, _captures, _point_artifacts, job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="test", lease_seconds=60)
    assert claimed is not None and claimed.job_id == job_id
    stale_inputs = dict(claimed.build_inputs)
    stale_inputs["stages"] = [
        {**binding, "version": binding["version"] - 1}
        if binding["key"] == "scene_pose"
        else binding
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
    job = reconstruction_scene_job(repository.connection, repository.workspace_id, job_id)
    assert job is not None and job["status"] == "failed"


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


class _CountingStore:
    """Delegates to a real store and records which blobs were fetched, and how often.

    A proxy rather than a subclass so it stays a faithful pass-through: anything the graph reader
    calls that is not counted here reaches the real store unchanged.
    """

    def __init__(self, inner):
        self._inner = inner
        self.fetched: list[str] = []
        self.probed: list[str] = []

    def get(self, blob_id):
        self.fetched.append(blob_id.hex)
        return self._inner.get(blob_id)

    def exists(self, blob_id):
        self.probed.append(blob_id.hex)
        return self._inner.exists(blob_id)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _scene_receipt_digests(repository, job_id):
    """The pose receipt digest for a scene job, as lowercase hex."""
    row = repository.connection.execute(
        "select a.content_sha256 from reconstruction_scene_job j "
        "join artifact a on a.workspace_id=j.workspace_id "
        "and a.artifact_id=j.pose_receipt_artifact_id "
        "where j.workspace_id=%s and j.job_id=%s",
        (repository.workspace_id, job_id),
    ).fetchone()
    return bytes(row["content_sha256"]).hex()


def _binary_values(value, path="memo"):
    """Every `bytes` reachable from a value, as the path that reaches it.

    Walks tuples, lists, dicts and any object with `_fields` or `__dict__`, so it keeps working
    when the memo's value shape changes. Returns paths rather than a bool so a failure names what
    is being held.
    """
    if isinstance(value, bytes | bytearray | memoryview):
        return [path]
    if isinstance(value, str | int | float | bool | type(None)):
        return []
    if isinstance(value, dict):
        return [
            found
            for key, item in value.items()
            for found in _binary_values(key, f"{path}.<key>") + _binary_values(item, f"{path}[…]")
        ]
    if isinstance(value, list | tuple | set | frozenset):
        return [
            found
            for index, item in enumerate(value)
            for found in _binary_values(item, f"{path}[{index}]")
        ]
    fields = getattr(value, "_fields", None)
    if fields is not None:
        return [
            found
            for name in fields
            for found in _binary_values(getattr(value, name), f"{path}.{name}")
        ]
    contents = getattr(value, "__dict__", None)
    if contents is not None:
        return [
            found
            for name, item in contents.items()
            for found in _binary_values(item, f"{path}.{name}")
        ]
    return []


def _point_map_digests(repository, point_artifacts):
    return {
        bytes(
            repository.connection.execute(
                "select content_sha256 from artifact where workspace_id=%s and artifact_id=%s",
                (repository.workspace_id, artifact_id),
            ).fetchone()["content_sha256"]
        ).hex()
        for artifact_id in point_artifacts
    }


def test_a_repeated_graph_read_reuses_the_validated_placement_without_refetching_bytes(
    repository, tmp_path
):
    """The measured cost of `GET /graph` was re-reading and rebuilding what cannot have changed.

    MEASURED 2026-09-09: 50.6 s for a 210 member scene and 21.5 s for a 91 member one whose
    geometry is withheld anyway, both about 0.24 s per member, none of it in the asset-read policy.
    The pose receipt and every point map are content addressed and their digests are columns on the
    scene row, so a second read of an unchanged scene must not rebuild the placement from them.

    The pose receipt used to be read once more per scene by `scene_inputs`, which the asset-read
    policy calls from `trained_geometry_row`. That read is outside this memo and is now bounded by
    its own, in `exulanica/graph/asset_read_policy.py`; the assertions below hold either way,
    because they compare the second read against the first rather than naming a count.
    """
    clear_placement_memo()
    clear_scene_inputs_memo()
    store, _captures, point_artifacts, job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="memo-test", lease_seconds=60)
    assert claimed is not None
    assert _processor(repository, store, tmp_path, FakeColmap(registered=3)).process(claimed)

    pose_digest = _scene_receipt_digests(repository, job_id)
    point_digests = _point_map_digests(repository, point_artifacts)

    first_store = _CountingStore(store)
    first = read_snapshot(
        repository.connection, repository.workspace_id, first_store
    ).reconstruction_scenes[0]
    assert first.placement_state == "available"
    assert pose_digest in first_store.fetched
    assert point_digests <= set(first_store.fetched)

    second_store = _CountingStore(store)
    second = read_snapshot(
        repository.connection, repository.workspace_id, second_store
    ).reconstruction_scenes[0]

    # The point maps are the bulk of the bytes and none of them is fetched again.
    assert point_digests.isdisjoint(second_store.fetched)
    # The pose receipt is fetched once for the asset-read policy instead of twice.
    assert second_store.fetched.count(pose_digest) < first_store.fetched.count(pose_digest)
    assert len(second_store.fetched) < len(first_store.fetched)
    # What replaces the reads is a presence check per reference, which is a stat rather than a
    # hash. Counted so the trade is visible in the test rather than only in the comment.
    assert point_digests <= set(second_store.probed)
    assert pose_digest in second_store.probed
    assert placement_memo_size() == 1
    assert second == first


def test_the_placement_memo_never_holds_the_point_map_bytes_it_was_built_from(
    repository, tmp_path
):
    """A memoised entry must never carry the bytes it was built from.

    MEASURED 2026-09-09: one entry for a 210 member scene was 639.6 KiB; were the point maps to
    start being held it would be 780 MB. The memo used to hold a whole `PlacementRecord`, whose
    `point_map_inputs` kept their `content=None` default only because `build_placement_record`
    happened to rebuild them positionally. It now holds `_Outcome`, whose fields are strings and
    floats and which structurally cannot hold bytes at all.

    The assertion is therefore about the value rather than about one field of it: nothing
    reachable from a memo entry is a `bytes`. That survives the shape changing again, which the
    field-level version did not.
    """
    clear_placement_memo()
    store, _captures, _point_artifacts, _job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="memo-bytes", lease_seconds=60)
    assert claimed is not None
    assert _processor(repository, store, tmp_path, FakeColmap(registered=3)).process(claimed)

    read_snapshot(repository.connection, repository.workspace_id, store)
    assert placement_memo_size() == 1
    outcome, _cameras = next(iter(_memo.values()))
    assert outcome.placed, "the fixture places every member, so an empty outcome proves nothing"
    assert _binary_values(_memo) == []


def test_losing_a_point_map_after_a_memoised_read_is_still_seen(repository, tmp_path):
    """Presence is part of the key, so a purge is not served from the memo."""
    clear_placement_memo()
    store, captures, point_artifacts, _job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="memo-purge", lease_seconds=60)
    assert claimed is not None
    assert _processor(repository, store, tmp_path, FakeColmap(registered=3)).process(claimed)

    before = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert before.placement_state == "available"

    row = repository.connection.execute(
        "select content_sha256 from artifact where workspace_id=%s and artifact_id=%s",
        (repository.workspace_id, point_artifacts[1]),
    ).fetchone()
    path = store.root / store.key_for(BlobId(bytes(row["content_sha256"])))
    path.chmod(0o644)
    path.unlink()

    after = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert after.placement_state == "partial"
    assert after.members[1].capture_id == captures[1]
    assert after.members[1].placement is None
    assert after.members[1].exclusion_reason == "alignment-unavailable"


def test_losing_the_pose_receipt_after_a_memoised_read_is_still_seen(repository, tmp_path):
    """The pose receipt is no longer fetched on a hit, so its presence is checked instead."""
    clear_placement_memo()
    store, _captures, _point_artifacts, job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="memo-pose", lease_seconds=60)
    assert claimed is not None
    assert _processor(repository, store, tmp_path, FakeColmap(registered=3)).process(claimed)

    assert (
        read_snapshot(
            repository.connection, repository.workspace_id, store
        ).reconstruction_scenes[0].placement_state
        == "available"
    )

    path = store.root / store.key_for(BlobId.from_hex(_scene_receipt_digests(repository, job_id)))
    path.chmod(0o644)
    path.unlink()

    scene = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert scene.receipt_state == "missing"
    assert scene.placement_state == "bytes_missing"
    assert scene.rendering_substrate == "source_photographs"


def _key(index, members):
    refs = tuple(f"m{n}" for n in range(members))
    return (str(index), "scene", "pose", "placement", "gate", refs, (), ())


def test_the_placement_memo_is_bounded_by_members_and_clearable():
    """The bound is on members, not entries, because that is what tracks memory.

    A graph read sweeps every scene in the workspace, so the access pattern is a cycle and a bound
    shorter than the cycle would evict each entry before it is reused, giving a zero hit rate.
    """
    clear_placement_memo()
    assert placement_memo_size() == 0 and placement_memo_members() == 0

    for index in range(10):
        _memo_put(_key(index, 2_500), ("record", {}))
    assert placement_memo_members() <= _MEMO_MAX_MEMBERS
    # The oldest went first and the newest is still held.
    assert _memo_get(_key(0, 2_500)) is None
    assert _memo_get(_key(9, 2_500)) == ("record", {})

    # Many small scenes are cheap, so many more of them fit than of large ones.
    clear_placement_memo()
    for index in range(200):
        _memo_put(_key(index, 3), ("record", {}))
    assert placement_memo_size() == 200
    assert placement_memo_members() == 600

    # One scene larger than the whole bound is still held, rather than inserted and dropped on
    # every request, which would make the memo pure cost for it.
    clear_placement_memo()
    _memo_put(_key(0, _MEMO_MAX_MEMBERS * 2), ("record", {}))
    assert placement_memo_size() == 1
    assert _memo_get(_key(0, _MEMO_MAX_MEMBERS * 2)) == ("record", {})

    clear_placement_memo()
    assert placement_memo_size() == 0 and placement_memo_members() == 0


def test_a_point_map_corrupted_after_a_memoised_read_is_advertised_until_the_memo_is_cleared(
    repository, tmp_path
):
    """The one property this memo gives up, pinned so it cannot change unnoticed.

    Before the memo every graph read pulled each point map through `store.get`, which re-hashes the
    bytes, so a rotted blob became `alignment-unavailable` with no fetch reference. On a memo hit
    the only check is `store.exists`, so the member stays advertised. The bytes are still safe:
    `exulanica/api/routes/geometry.py` reads them through the store and refuses on IntegrityError.
    This test asserts the behaviour as it is, and that clearing the memo restores the old answer.
    """
    clear_placement_memo()
    store, _captures, point_artifacts, _job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="memo-corrupt", lease_seconds=60)
    assert claimed is not None
    assert _processor(repository, store, tmp_path, FakeColmap(registered=3)).process(claimed)

    before = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert before.members[1].placement is not None

    row = repository.connection.execute(
        "select content_sha256 from artifact where workspace_id=%s and artifact_id=%s",
        (repository.workspace_id, point_artifacts[1]),
    ).fetchone()
    path = store.root / store.key_for(BlobId(bytes(row["content_sha256"])))
    path.chmod(0o644)
    path.write_bytes(b"corrupt OPM input")

    warm = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert warm.members[1].placement is not None, "documented: the memo still advertises it"

    clear_placement_memo()
    cold = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert cold.members[1].placement is None
    assert cold.members[1].exclusion_reason == "alignment-unavailable"


def test_a_point_map_repaired_under_the_same_digest_is_seen_on_the_next_read(
    repository, tmp_path
):
    """A record built from a failed digest read must not be cached.

    `store.exists` cannot tell a rotted object from a sound one, so a degraded record cached under
    an unchanged key would outlive the repair that fixes it: restoring correct bytes leaves every
    key component identical. The read that produced it is therefore never memoised.
    """
    clear_placement_memo()
    store, _captures, point_artifacts, _job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="memo-repair", lease_seconds=60)
    assert claimed is not None
    assert _processor(repository, store, tmp_path, FakeColmap(registered=3)).process(claimed)

    row = repository.connection.execute(
        "select content_sha256 from artifact where workspace_id=%s and artifact_id=%s",
        (repository.workspace_id, point_artifacts[1]),
    ).fetchone()
    path = store.root / store.key_for(BlobId(bytes(row["content_sha256"])))
    path.chmod(0o644)
    sound = path.read_bytes()
    path.write_bytes(b"corrupt OPM input")

    clear_placement_memo()
    degraded = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert degraded.members[1].placement is None
    assert degraded.members[1].exclusion_reason == "alignment-unavailable"
    assert placement_memo_size() == 0, "a record built from a failed digest must not be cached"

    path.write_bytes(sound)
    repaired = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert repaired.members[1].placement is not None
    assert placement_memo_size() == 1


# -- the parsed pose manifest memo ------------------------------------------------------------


def _read_manifest(repository, store):
    """`scene_inputs` for the one scene in the fixture workspace, as the graph route calls it."""
    scene_id = repository.connection.execute(
        "select scene_id from reconstruction_scene where workspace_id=%s",
        (repository.workspace_id,),
    ).fetchone()["scene_id"]
    return scene_inputs(repository.connection, repository.workspace_id, scene_id, store)


def _built_scene(repository, tmp_path, worker):
    """A processed scene, its store and its pose receipt digest: the setup these tests share."""
    clear_placement_memo()
    clear_scene_inputs_memo()
    store, _captures, _point_artifacts, job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker=worker, lease_seconds=60)
    assert claimed is not None
    assert _processor(repository, store, tmp_path, FakeColmap(registered=3)).process(claimed)
    return store, _scene_receipt_digests(repository, job_id)


def test_a_second_scene_inputs_call_reuses_the_parsed_manifest_without_refetching_the_receipt(
    repository, tmp_path
):
    """The measured cost the placement memo left behind.

    MEASURED 2026-09-09 under cProfile: a warm `GET /graph` spent 2.060 s in `scene_inputs` over
    two calls for one scene, 1.924 s of it in `json.loads`. The two calls are `read_snapshot`
    reaching it through `trained_geometry_row` and the route buffering it again for the asset-read
    policy. Both parse the same 107,742,795 byte receipt to keep a 45,829 byte manifest.

    The manifest is a pure function of the receipt bytes and the scene, both of which are in the
    key, so the second call must not fetch the bytes again. What it must still do is check that the
    receipt is present, which is the cheap half of what `store.get` was doing.
    """
    store, pose_digest = _built_scene(repository, tmp_path, "manifest-memo")

    first_store = _CountingStore(store)
    first = _read_manifest(repository, first_store)
    assert first is not None
    assert pose_digest in first_store.fetched
    assert scene_inputs_memo_size() == 1

    second_store = _CountingStore(store)
    second = _read_manifest(repository, second_store)
    assert second is not None
    assert pose_digest not in second_store.fetched, "the receipt bytes must not be read again"
    assert pose_digest in second_store.probed, "but its presence must still be checked"
    assert second[1] == first[1], "and the manifest must be the one the first read verified"
    # The row is not memoised: it carries purged_at, needs_repair and the active rung assertion,
    # and `scene_allowed` compares a freshly read row against it under the final lock.
    assert second[0] == first[0]


def test_the_memoised_manifest_cannot_be_reached_by_a_caller(repository, tmp_path):
    """A held object a caller can mutate is a held object that will eventually be wrong.

    No caller mutates the manifest today. This exists so that none can start: each call returns its
    own deep copy, which MEASURED 2026-09-09 costs 0.327 ms against the 1,290 ms parse it replaces.
    """
    store, _pose_digest = _built_scene(repository, tmp_path, "manifest-alias")

    # The miss returns the parse it just made and keeps its own copy, so mutating this one proves
    # only that the memo did not hand out the object it stored.
    first = _read_manifest(repository, store)
    assert first is not None
    first[1]["frames"].clear()
    first[1]["scene_ref"] = "tampered from the miss"

    # The hit is the path that matters: without a copy here the caller holds the memo itself.
    second = _read_manifest(repository, store)
    assert second is not None
    assert second[1]["frames"], "the held manifest kept its frames"
    assert second[1]["scene_ref"] != "tampered from the miss"
    second[1]["frames"].clear()
    second[1]["scene_ref"] = "tampered from the hit"

    third = _read_manifest(repository, store)
    assert third is not None
    assert third[1]["frames"], "a caller mutating a hit must not empty the held manifest"
    assert third[1]["scene_ref"] != "tampered from the hit"
    assert third[1] is not second[1]


def test_losing_the_pose_receipt_after_a_memoised_parse_is_still_seen(repository, tmp_path):
    """A purge must still withhold the scene, so presence is checked on every hit."""
    store, pose_digest = _built_scene(repository, tmp_path, "manifest-purge")

    assert _read_manifest(repository, store) is not None
    assert scene_inputs_memo_size() == 1

    path = store.root / store.key_for(BlobId.from_hex(pose_digest))
    path.chmod(0o644)
    path.unlink()

    assert _read_manifest(repository, store) is None
    scene = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert scene.receipt_state == "missing"
    assert scene.rendering_substrate == "source_photographs"


def test_a_pose_receipt_corrupted_after_a_memoised_parse_is_trusted_until_the_memo_is_cleared(
    repository, tmp_path
):
    """The one property this memo gives up, pinned so it cannot change unnoticed.

    `store.get` re-hashes what it returns, so before the memo a rotted receipt failed its digest
    and the scene's geometry was withheld. On a hit the only check is `store.exists`, a bare
    `is_file()`, so the scene stays available until the entry is evicted or the memo is cleared.
    This is the same trade the placement memo already makes for point maps, and it is asserted here
    as behaviour rather than left in a comment.
    """
    store, pose_digest = _built_scene(repository, tmp_path, "manifest-corrupt")

    assert _read_manifest(repository, store) is not None

    path = store.root / store.key_for(BlobId.from_hex(pose_digest))
    path.chmod(0o644)
    sound = path.read_bytes()
    path.write_bytes(b"not the pose receipt")

    assert _read_manifest(repository, store) is not None, "documented: the memo still trusts it"

    clear_scene_inputs_memo()
    assert _read_manifest(repository, store) is None
    path.write_bytes(sound)


def test_a_pose_receipt_repaired_under_the_same_digest_is_seen_on_the_next_read(
    repository, tmp_path
):
    """A read that raised must never fill the memo.

    Restoring correct bytes leaves the scene id and the digest identical, so a cached failure would
    outlive the repair that fixed it and no request would ever see the sound receipt again.
    """
    store, pose_digest = _built_scene(repository, tmp_path, "manifest-repair")

    path = store.root / store.key_for(BlobId.from_hex(pose_digest))
    path.chmod(0o644)
    sound = path.read_bytes()
    path.write_bytes(b"not the pose receipt")

    clear_scene_inputs_memo()
    assert _read_manifest(repository, store) is None
    assert scene_inputs_memo_size() == 0, "a read that raised must not be cached"

    path.write_bytes(sound)
    assert _read_manifest(repository, store) is not None
    assert scene_inputs_memo_size() == 1


def test_the_manifest_memo_is_bounded_by_frames_and_clearable():
    """The bound is on frames, not entries, because that is what tracks memory.

    A graph read sweeps every scene in the workspace, so the access pattern is a cycle and a bound
    shorter than the cycle would evict each entry before it is reused, giving a zero hit rate.
    MEASURED 2026-09-09 on the 210 frame volcanic manifest: 114,312 bytes parsed, or 544 bytes per
    frame, so the 20,000 frame bound is about 11 MB.
    """
    from exulanica.graph.asset_read_policy import _MEMO_MAX_FRAMES, _memo_get, _memo_put

    def manifest(frames):
        return {"frames": [{"capture_ref": f"c{n}"} for n in range(frames)]}

    clear_scene_inputs_memo()
    assert scene_inputs_memo_size() == 0 and scene_inputs_memo_frames() == 0

    for index in range(10):
        _memo_put((str(index), "digest"), manifest(2_500))
    assert scene_inputs_memo_frames() <= _MEMO_MAX_FRAMES
    assert _memo_get(("0", "digest")) is None, "the oldest went first"
    assert _memo_get(("9", "digest")) is not None, "the newest is still held"

    clear_scene_inputs_memo()
    for index in range(200):
        _memo_put((str(index), "digest"), manifest(3))
    assert scene_inputs_memo_size() == 200
    assert scene_inputs_memo_frames() == 600

    # One scene larger than the whole bound is still held, rather than inserted and dropped on
    # every request, which would make the memo pure cost for it.
    clear_scene_inputs_memo()
    _memo_put(("0", "digest"), manifest(_MEMO_MAX_FRAMES * 2))
    assert scene_inputs_memo_size() == 1
    assert _memo_get(("0", "digest")) is not None

    clear_scene_inputs_memo()
    assert scene_inputs_memo_size() == 0 and scene_inputs_memo_frames() == 0


def test_the_final_check_still_re_evaluates_permission_at_the_locked_time(repository, tmp_path):
    """The memo must not reach the decision, only the buffering that precedes it.

    `scene_inputs` buffers; `scene_allowed` decides, and the route calls it a second time inside
    `final_check`, where the lock is held and the evaluation time is the locked one. What makes
    that still work is that only the parsed manifest is memoised: the `_SCENE_BINDING` row is
    re-read on every call, and it joins the rung assertion on `status='active'`. So retracting the
    assertion after the manifest is held stops the buffer resolving at all, and no memoised
    manifest can deliver geometry the permission no longer covers.
    """
    store, _pose_digest = _built_scene(repository, tmp_path, "manifest-final")

    before = read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]
    assert before.placement_state == "available"
    assert scene_inputs_memo_size() == 1

    scene_id = repository.connection.execute(
        "select scene_id from reconstruction_scene where workspace_id=%s",
        (repository.workspace_id,),
    ).fetchone()["scene_id"]
    repository.connection.execute(
        "update assertion set status='retracted' where workspace_id=%s and assertion_id="
        "(select rung_assertion_id from reconstruction_scene_job j "
        " join reconstruction_scene s on s.workspace_id=j.workspace_id "
        " and s.current_job_id=j.job_id where s.workspace_id=%s and s.scene_id=%s)",
        (repository.workspace_id, repository.workspace_id, scene_id),
    )
    repository.connection.commit()

    assert _read_manifest(repository, store) is None, (
        "the scene binding no longer resolves, so there is nothing to buffer"
    )
    after = read_snapshot(repository.connection, repository.workspace_id, store)
    assert not [
        scene
        for scene in after.reconstruction_scenes
        if scene.scene_id == scene_id and scene.placement_state == "available"
    ], "a retracted rung assertion must not leave a memoised manifest delivering geometry"


# -- the persisted scene projection ------------------------------------------------------------
#
# The memo above fixes the second graph read in a process. These fix the first, which is the one a
# visitor arriving at a freshly started API actually pays. Every test here clears both memos first,
# because a memo hit would answer before the projection is ever consulted and would prove nothing.


def _published_scene(repository, tmp_path, worker):
    """One published scene with a projection, and the pieces its bindings are made of."""
    clear_placement_memo()
    clear_scene_inputs_memo()
    store, captures, point_artifacts, job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker=worker, lease_seconds=60)
    assert claimed is not None
    outcome = _processor(repository, store, tmp_path, FakeColmap(registered=3)).process(claimed)
    assert outcome.status == "succeeded"
    return store, captures, point_artifacts, job_id, outcome.scene_id


def _projection_rows(repository, scene_id):
    return repository.connection.execute(
        "select artifact_id,content_sha256,byte_size,purged_at from artifact "
        "where workspace_id=%s and scene_id=%s and kind='scene_projection' "
        "order by created_at desc,artifact_id desc",
        (repository.workspace_id, scene_id),
    ).fetchall()


def _projection_payload(repository, store, scene_id):
    row = _projection_rows(repository, scene_id)[0]
    return json.loads(store.get(BlobId(bytes(row["content_sha256"]))))["projection"]


def _seal(payload):
    """Re-envelope an edited payload, so the reader's binding checks are what refuses it.

    The payload digest is recomputed rather than left stale, deliberately: a stale one would be
    caught by the envelope check and the binding check underneath it would never run.
    """
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    envelope = {
        "profile": "exulanica.scene-graph-projection-envelope/v1",
        "payload_sha256": hashlib.sha256(canonical).hexdigest(),
        "projection": payload,
    }
    return (
        json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        + b"\n"
    )


def _retarget_projection(repository, store, scene_id, data):
    """Point the scene's newest projection row at these bytes, as a tampered publisher would."""
    written = store.put_bytes(data)
    row = _projection_rows(repository, scene_id)[0]
    repository.connection.execute(
        "update artifact set content_sha256=%s,storage_key=%s,byte_size=%s "
        "where workspace_id=%s and artifact_id=%s",
        (
            written.blob_id.digest,
            store.key_for(written.blob_id),
            written.byte_size,
            repository.workspace_id,
            row["artifact_id"],
        ),
    )
    clear_placement_memo()


def _scene(repository, store):
    clear_placement_memo()
    clear_scene_inputs_memo()
    return read_snapshot(
        repository.connection, repository.workspace_id, store
    ).reconstruction_scenes[0]


def test_publishing_a_scene_writes_a_projection_bound_to_its_three_receipts(
    repository, tmp_path
):
    """The projection publishes with the scene, inside the same atomic acceptance."""
    store, captures, point_artifacts, job_id, scene_id = _published_scene(
        repository, tmp_path, "projection-publish"
    )
    rows = _projection_rows(repository, scene_id)
    assert len(rows) == 1
    payload = _projection_payload(repository, store, scene_id)

    assert payload["profile"] == "exulanica.scene-graph-projection/v1"
    assert payload["scene_ref"] == str(scene_id)
    receipts = repository.connection.execute(
        "select a.kind,a.content_sha256 from reconstruction_scene_job j "
        "join artifact a on a.workspace_id=j.workspace_id and a.artifact_id in "
        "(j.pose_receipt_artifact_id,j.placement_artifact_id,j.gate_artifact_id) "
        "where j.workspace_id=%s and j.job_id=%s",
        (repository.workspace_id, job_id),
    ).fetchall()
    digests = {row["kind"]: bytes(row["content_sha256"]).hex() for row in receipts}
    assert payload["bindings"]["pose_receipt_sha256"] == digests["pose_receipt"]
    assert payload["bindings"]["placement_receipt_sha256"] == digests["point_map_placement"]
    assert payload["bindings"]["gate_receipt_sha256"] == digests["scene_gate_receipt"]
    assert payload["bindings"]["member_capture_refs"] == [str(item) for item in captures]
    assert [item["artifact_ref"] for item in payload["bindings"]["point_map_inputs"]] == [
        str(item) for item in point_artifacts
    ]
    # Every member has exactly one outcome, which is what makes the reader's lookup total.
    assert {item["capture_ref"] for item in payload["placed"]} | {
        item["capture_ref"] for item in payload["excluded"]
    } == {str(item) for item in captures}


def test_a_cold_graph_read_serves_the_projection_without_rebuilding_the_placement(
    repository, tmp_path, monkeypatch
):
    """The acceptance criterion, proved by making the rebuild impossible rather than by timing.

    MEASURED 2026-09-09: a cold `GET /graph` for the 210 member volcanic scene was 47.9 s, all of
    it in the rebuild this test forbids. A stopwatch here would measure a three member fixture and
    prove nothing, so `validate_placement_record` is made to raise instead: if the read still
    produces the same scene, it did not go through the rebuild.
    """
    store, _captures, _point_artifacts, _job_id, _scene_id = _published_scene(
        repository, tmp_path, "projection-cold"
    )
    expected = _scene(repository, store)
    assert expected.placement_state == "available"

    def refuse(*args, **kwargs):
        raise AssertionError("the cold read rebuilt the placement instead of reading it")

    monkeypatch.setattr(
        "exulanica.graph.reconstruction_scenes.validate_placement_record", refuse
    )
    monkeypatch.setattr(
        "exulanica.graph.reconstruction_scenes.recovered_camera_records", refuse
    )
    assert _scene(repository, store) == expected


def test_the_projection_and_the_rebuild_produce_the_same_scene_row(repository, tmp_path):
    """Byte-identical, which is the acceptance criterion, checked on the serialised payload."""
    store, _captures, _point_artifacts, _job_id, scene_id = _published_scene(
        repository, tmp_path, "projection-identity"
    )
    projected = _scene(repository, store)

    repository.connection.execute(
        "update artifact set purged_at=now() where workspace_id=%s and scene_id=%s "
        "and kind='scene_projection'",
        (repository.workspace_id, scene_id),
    )
    rebuilt = _scene(repository, store)

    assert rebuilt.model_dump_json() == projected.model_dump_json()


@pytest.mark.parametrize(
    "binding",
    ["pose_receipt_sha256", "placement_receipt_sha256", "gate_receipt_sha256"],
)
def test_a_projection_bound_to_another_digest_is_refused(repository, tmp_path, binding):
    """A projection belonging to another build must not answer for this one."""
    store, _captures, _point_artifacts, _job_id, scene_id = _published_scene(
        repository, tmp_path, f"projection-{binding}"
    )
    expected = _scene(repository, store)

    payload = _projection_payload(repository, store, scene_id)
    payload["bindings"][binding] = "f" * 64
    _retarget_projection(repository, store, scene_id, _seal(payload))

    # Refused, and the scene is still served correctly by the rebuild it falls back to.
    assert _scene(repository, store).model_dump_json() == expected.model_dump_json()

    def refuse(*args, **kwargs):
        raise AssertionError("unreachable")

    # And proved to be the rebuild rather than a second acceptance of the same bytes.
    with pytest.raises(AssertionError):
        import exulanica.graph.reconstruction_scenes as module

        original = module.validate_placement_record
        module.validate_placement_record = refuse
        try:
            _scene(repository, store)
        finally:
            module.validate_placement_record = original


def test_withdrawing_a_member_refuses_the_projection(repository, tmp_path):
    """The member list is the one binding no digest covers, checked on both of its paths.

    Withdrawing a member for real is a capture tombstone, and `tombstone_blocks_scene` then takes
    the whole scene out of the graph, so the projection is never consulted at all. That is the
    first assertion, and it is the one a person's withdrawal actually travels down.

    The binding is still carried and still checked, because the two lists are not the same object:
    the projection is bound to the list the graph resolves from
    `reconstruction_scene_build_member`, and nothing about the three receipt digests would change
    if that list did. `reconstruction_scene_build_member` is append-only, so the disagreement
    cannot be staged through the database; it is exercised directly against the reader instead.
    """
    store, captures, _point_artifacts, _job_id, scene_id = _published_scene(
        repository, tmp_path, "projection-member"
    )
    payload = _projection_payload(repository, store, scene_id)
    assert payload["bindings"]["member_capture_refs"] == [str(item) for item in captures]
    assert _scene(repository, store).placement_state == "available"

    from exulanica.graph.reconstruction_scenes import _PointMapRef, _projected

    rows = _projection_rows(repository, scene_id)
    references = tuple(
        _PointMapRef(item["capture_ref"], item["artifact_ref"], item["content_sha256"])
        for item in payload["bindings"]["point_map_inputs"]
    )

    def read(member_refs):
        return _projected(
            store,
            [bytes(rows[0]["content_sha256"])],
            scene_id=scene_id,
            pose_digest=payload["bindings"]["pose_receipt_sha256"],
            placement_digest=payload["bindings"]["placement_receipt_sha256"],
            gate_digest=payload["bindings"]["gate_receipt_sha256"],
            member_refs=member_refs,
            references=references,
        )

    assert read(tuple(str(item) for item in captures)) is not None, "the fixture must be readable"
    assert read((str(captures[0]), str(captures[1]))) is None, "a member gone must refuse it"
    assert read(tuple(str(item) for item in reversed(captures))) is None, "so must a reordering"

    # And the path a withdrawal really takes: the scene leaves the graph, projection or not.
    clear_placement_memo()
    clear_scene_inputs_memo()
    repository.insert_tombstone(
        scope="capture",
        capture_id=captures[2],
        requested_by=uuid.uuid4(),
        reason="withdraw one member of a projected scene",
    )
    after = read_snapshot(repository.connection, repository.workspace_id, store)
    assert after.reconstruction_scenes == []


def test_purging_a_point_map_refuses_the_projection(repository, tmp_path):
    """A projection asserts geometry for the members it placed. Losing one's bytes refuses it."""
    store, captures, point_artifacts, _job_id, _scene_id = _published_scene(
        repository, tmp_path, "projection-purge"
    )
    assert _scene(repository, store).placement_state == "available"

    row = repository.connection.execute(
        "select content_sha256 from artifact where workspace_id=%s and artifact_id=%s",
        (repository.workspace_id, point_artifacts[1]),
    ).fetchone()
    path = store.root / store.key_for(BlobId(bytes(row["content_sha256"])))
    path.chmod(0o644)
    path.unlink()

    after = _scene(repository, store)
    assert after.placement_state == "partial"
    assert after.members[1].capture_id == captures[1]
    assert after.members[1].placement is None
    assert after.members[1].exclusion_reason == "alignment-unavailable"


def test_a_projection_whose_recovered_camera_is_malformed_is_refused_not_raised(
    repository, tmp_path
):
    """`SceneRecoveredCameraRow` forbids an extra key and is built outside the fallback handlers.

    So a camera the row would reject has to be refused while the projection is being read, or the
    graph raises where it used to fall back, and a bad projection becomes worse than no projection.
    """
    store, captures, _point_artifacts, _job_id, scene_id = _published_scene(
        repository, tmp_path, "projection-camera"
    )
    expected = _scene(repository, store)

    payload = _projection_payload(repository, store, scene_id)
    payload["recovered_cameras"][str(captures[0])] = {
        "scene_from_camera_row_major": [0.0] * 16,
        "calibration": {
            "model": "PINHOLE",
            "width": 160,
            "height": 100,
            "fx": 1.0,
            "fy": 1.0,
            "cx": 1.0,
            "cy": 1.0,
            "parameters": [],
        },
        "projection": "pinhole",
        "unexpected": True,
    }
    _retarget_projection(repository, store, scene_id, _seal(payload))

    assert _scene(repository, store).model_dump_json() == expected.model_dump_json()


def test_an_older_projection_still_answers_when_a_newer_one_does_not(repository, tmp_path):
    """Nothing sets `artifact.superseded_by`, so every projection a scene has had stays live.

    A backfill run after a rebuild would write the superseded build's projection, which would be
    the newest by `created_at` and would fail every binding. Offering only the newest would cost
    that scene its fast path permanently. The reader is handed several and proves each.
    """
    store, _captures, _point_artifacts, _job_id, scene_id = _published_scene(
        repository, tmp_path, "projection-stale"
    )
    expected = _scene(repository, store)
    sound = _projection_rows(repository, scene_id)[0]

    stale = _projection_payload(repository, store, scene_id)
    stale["bindings"]["pose_receipt_sha256"] = "a" * 64
    written = store.put_bytes(_seal(stale))
    repository.connection.execute(
        "insert into artifact (artifact_id,workspace_id,kind,scene_id,stage_key,stage_version,"
        "params_digest,input_digest,idempotency_key,content_sha256,storage_key,byte_size) "
        "values (%s,%s,'scene_projection',%s,'scene_projection',1,%s,%s,%s,%s,%s,%s)",
        (
            uuid.uuid4(),
            repository.workspace_id,
            scene_id,
            b"\x01" * 32,
            b"\x02" * 32,
            f"test:stale-projection:{uuid.uuid4()}",
            written.blob_id.digest,
            store.key_for(written.blob_id),
            written.byte_size,
        ),
    )
    assert len(_projection_rows(repository, scene_id)) == 2
    assert _projection_rows(repository, scene_id)[0]["artifact_id"] != sound["artifact_id"]

    def refuse(*args, **kwargs):
        raise AssertionError("a stale projection hid the sound one and forced a rebuild")

    import exulanica.graph.reconstruction_scenes as module

    original = module.validate_placement_record
    module.validate_placement_record = refuse
    try:
        assert _scene(repository, store).model_dump_json() == expected.model_dump_json()
    finally:
        module.validate_placement_record = original


def test_the_projection_carries_nothing_privacy_bearing(repository, tmp_path):
    """It carries what the response already carries, and none of what it deliberately does not.

    The source photograph digests matter most. `scene_allowed` denies a scene by comparing the pose
    manifest's frame digest against the live artifact row, and re-masking a withdrawn person moves
    `read_source_sha256`. A copy of those digests in a durable artifact would be a second, stale
    answer to a question the asset-read policy exists to ask fresh.
    """
    store, _captures, _point_artifacts, _job_id, scene_id = _published_scene(
        repository, tmp_path, "projection-privacy"
    )
    row = _projection_rows(repository, scene_id)[0]
    raw = store.get(BlobId(bytes(row["content_sha256"])))
    payload = json.loads(raw)["projection"]

    sources = {
        bytes(item["blob_sha256"]).hex()
        for item in repository.connection.execute(
            "select blob_sha256 from capture where workspace_id=%s", (repository.workspace_id,)
        ).fetchall()
    }
    assert sources, "the fixture must have source photographs for this to prove anything"
    assert not [digest for digest in sources if digest.encode() in raw], (
        "a source photograph digest reached the projection"
    )

    assert set(payload) == {
        "profile",
        "scene_ref",
        "bindings",
        "placed",
        "excluded",
        "recovered_cameras",
    }
    assert set(payload["bindings"]) == {
        "pose_receipt_sha256",
        "placement_receipt_sha256",
        "gate_receipt_sha256",
        "member_capture_refs",
        "point_map_inputs",
    }
    for field in ("frames", "quality", "manifest", "person", "region", "review", "silhouette"):
        assert field.encode() not in raw, f"{field} reached the projection"


def test_the_scene_projection_kind_is_spelled_the_same_in_all_three_places(repository):
    """The producer, the reader and the stage registry, which may not import each other.

    `exulanica.graph` and `exulanica.ingest` are siblings in the layers contract, so the reader
    cannot import the producer's constant. `POINT_MAP_KIND` is spelled twice for the same reason
    and pinned by `tests/test_geometry_delivery.py`; this is that test for this kind.
    """
    from exulanica.graph.reconstruction_scenes import SCENE_PROJECTION_KIND as reader_kind
    from exulanica.ingest.scene_projection import SCENE_PROJECTION_KIND as producer_kind
    from exulanica.ingest.scene_projection import SCENE_PROJECTION_STAGE

    assert reader_kind == producer_kind
    assert stage(SCENE_PROJECTION_STAGE).output_kind == producer_kind
    assert stage(SCENE_PROJECTION_STAGE).deterministic is True


# -- the pose receipt head parse -----------------------------------------------------------------
#
# The memo above spares the second parse of a pose receipt in a process. This spares most of the
# first, which is the one a fresh process and therefore a first visitor pays.


def test_the_manifest_is_taken_from_the_receipt_head_without_parsing_the_whole_object():
    """MEASURED 2026-09-10 on the volcanic scene's 108,267,697 byte receipt: `json.loads` of the
    whole object is 1.129 s and the manifest is 50,034 bytes of it. Decoding and `raw_decode`-ing
    only the head is 0.011 s. The two must agree exactly, or the digest check that follows would
    deny a sound scene.
    """
    manifest = {"scene_ref": str(uuid.uuid4()), "frames": [{"capture_ref": "a", "sha256": "b"}]}
    receipt = {
        "manifest": manifest,
        "manifest_digest": "d" * 64,
        "profile": "exulanica.colmap-pose-receipt/v2",
        # The half the fast path exists to skip. Large and irrelevant, as `quality` is.
        "quality": {"registered_images": [f"{index:04d}.jpg" for index in range(2000)]},
        "quality_digest": "e" * 64,
    }
    canonical = json.dumps(
        receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    assert canonical.startswith(b'{"manifest":'), "the fast path's precondition"

    assert _manifest_and_digest(canonical) == (manifest, "d" * 64)
    assert _manifest_and_digest(canonical) == (
        json.loads(canonical)["manifest"],
        json.loads(canonical)["manifest_digest"],
    )


def test_a_receipt_the_head_parse_cannot_read_falls_back_to_the_whole_object():
    """Anything not written the way `exulanica/reconstruction/pose.py` writes one still reads.

    The fast path is a shortcut through a known layout, not a new format. A receipt that is
    pretty-printed, or whose keys are in another order, must still produce the same pair, slowly.
    """
    manifest = {"scene_ref": str(uuid.uuid4()), "frames": []}
    receipt = {"manifest": manifest, "manifest_digest": "f" * 64, "quality": {"n": 1}}

    indented = json.dumps(receipt, indent=2).encode()
    assert not indented.startswith(b'{"manifest":')
    assert _manifest_and_digest(indented) == (manifest, "f" * 64)

    reordered = json.dumps(
        {"quality": {"n": 1}, "manifest": manifest, "manifest_digest": "f" * 64},
        separators=(",", ":"),
    ).encode()
    assert not reordered.startswith(b'{"manifest":')
    assert _manifest_and_digest(reordered) == (manifest, "f" * 64)


def test_a_head_that_looks_right_but_is_truncated_is_refused_rather_than_half_read():
    """A misread head must not become a manifest. It cannot: the caller checks the digest."""
    with pytest.raises(ValueError):
        _manifest_and_digest(b'{"manifest":{"scene_ref":"x"')
