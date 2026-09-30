"""A saved arrival may keep one authorized scene build after another becomes current."""

from __future__ import annotations

import uuid

import pytest
from exulanica.api.arrival_scene_pose import scene_arrival_pose
from exulanica.api.arrival_source import (
    RetainedScenePin,
    _scene_point_bytes,
    _scene_trained_bytes,
    authorized_retained_scene,
)
from exulanica.graph.asset_read_policy import evaluation_time, scene_allowed, scene_inputs
from exulanica.graph.geometry import read_point_map
from exulanica.graph.reconstruction_scenes import reconstruction_scene_rows
from exulanica.graph.scene_geometry import read_scene_geometry

from test_scene_projection_backfill import _rebuild
from test_scene_reconstruction_pipeline import FakeColmap, _processor, _queued_scene

pytestmark = pytest.mark.postgres


def _two_builds(repository, tmp_path):
    store, captures, point_artifacts, first_job = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker="arrival-first", lease_seconds=60)
    assert claimed is not None and claimed.job_id == first_job
    first = _processor(repository, store, tmp_path, FakeColmap(registered=2)).process(claimed)
    assert first.status == "succeeded"
    second_job = _rebuild(repository, store, tmp_path, captures, point_artifacts)
    return store, captures, first.scene_id, first_job, second_job


def test_retained_build_stays_readable_after_rebuild_while_default_reads_current(
    repository, tmp_path
):
    store, _captures, scene_id, first_job, second_job = _two_builds(repository, tmp_path)
    current = reconstruction_scene_rows(
        repository.connection, repository.workspace_id, store, scene_id=scene_id
    )
    retained = reconstruction_scene_rows(
        repository.connection,
        repository.workspace_id,
        store,
        scene_id=scene_id,
        retained_job_id=first_job,
    )
    assert len(current) == len(retained) == 1
    assert current[0].pose_receipt_sha256 != retained[0].pose_receipt_sha256
    assert (
        current[0].members[0].placement.artifact_id != retained[0].members[0].placement.artifact_id
    )
    current_input = scene_inputs(repository.connection, repository.workspace_id, scene_id, store)
    old_input = scene_inputs(
        repository.connection,
        repository.workspace_id,
        scene_id,
        store,
        retained_job_id=first_job,
    )
    assert current_input[0]["job_id"] == second_job
    assert old_input[0]["job_id"] == first_job
    assert scene_allowed(
        repository.connection,
        repository.workspace_id,
        scene_id,
        old_input,
        evaluation_time(repository.connection),
        retained_job_id=first_job,
    )


def test_retained_scene_pose_uses_the_geometry_of_that_build(repository, tmp_path):
    store, _captures, scene_id, first_job, _second_job = _two_builds(repository, tmp_path)
    retained = reconstruction_scene_rows(
        repository.connection,
        repository.workspace_id,
        store,
        scene_id=scene_id,
        retained_job_id=first_job,
    )[0]

    def point_map(artifact_id):
        value = read_point_map(
            repository.connection, repository.workspace_id, uuid.UUID(artifact_id), store
        )
        return None if value is None else value.payload

    def trained(artifact_id):
        value = read_scene_geometry(
            repository.connection,
            repository.workspace_id,
            uuid.UUID(artifact_id),
            store,
            retained_job_id=first_job,
        )
        return None if value is None else value.payload

    pose = scene_arrival_pose(retained, point_map, trained)
    assert pose is not None
    assert all(abs(value) < 1000 for value in pose[0])
    assert 0.99 < sum(value * value for value in pose[1]) < 1.01


def test_writer_buffers_retained_scene_bytes_before_its_asset_lock(repository, tmp_path):
    store, _captures, scene_id, first_job, _second_job = _two_builds(repository, tmp_path)
    connection = repository.connection
    with connection.transaction():
        scene = reconstruction_scene_rows(
            connection,
            repository.workspace_id,
            store,
            scene_id=scene_id,
            retained_job_id=first_job,
        )[0]
        pose = scene_arrival_pose(
            scene,
            lambda artifact_id: _scene_point_bytes(
                connection,
                repository.workspace_id,
                scene,
                artifact_id,
                store,
            ),
            lambda artifact_id: _scene_trained_bytes(
                connection,
                repository.workspace_id,
                scene,
                artifact_id,
                first_job,
                store,
            ),
        )
        assert pose is not None
        assert all(abs(value) < 1000 for value in pose[0])


def test_retained_build_refuses_other_workspace_job_and_withdrawn_unregistered_member(
    repository, tmp_path
):
    store, captures, scene_id, first_job, _second_job = _two_builds(repository, tmp_path)
    assert (
        reconstruction_scene_rows(
            repository.connection,
            uuid.uuid4(),
            store,
            scene_id=scene_id,
            retained_job_id=first_job,
        )
        == []
    )
    assert (
        scene_inputs(
            repository.connection,
            repository.workspace_id,
            scene_id,
            store,
            retained_job_id=uuid.uuid4(),
        )
        is None
    )
    # FakeColmap registered two of three inputs. The third still supported the build's gate.
    repository.insert_tombstone(
        scope="capture",
        capture_id=captures[2],
        requested_by=uuid.uuid4(),
        reason="unregistered scene input withdrawn",
    )
    build_claim = repository.connection.execute(
        "select a.status from assertion a join predicate p using(predicate_id) "
        "where a.workspace_id=%s and p.key='reconstruction_scene_build_rung_is' "
        "and a.subject_ref->>'job_id'=%s",
        (repository.workspace_id, str(first_job)),
    ).fetchone()
    assert build_claim["status"] == "retracted"
    assert (
        reconstruction_scene_rows(
            repository.connection,
            repository.workspace_id,
            store,
            scene_id=scene_id,
            retained_job_id=first_job,
        )
        == []
    )


def test_retained_build_refuses_a_registered_member_withdrawal(repository, tmp_path):
    store, captures, scene_id, first_job, _second_job = _two_builds(repository, tmp_path)
    buffered = scene_inputs(
        repository.connection,
        repository.workspace_id,
        scene_id,
        store,
        retained_job_id=first_job,
    )
    assert buffered is not None
    repository.insert_tombstone(
        scope="capture",
        capture_id=captures[0],
        requested_by=uuid.uuid4(),
        reason="registered scene input withdrawn",
    )
    assert not scene_allowed(
        repository.connection,
        repository.workspace_id,
        scene_id,
        buffered,
        evaluation_time(repository.connection),
        retained_job_id=first_job,
    ), "a buffered pose must lose authorization after the withdrawal"
    assert (
        scene_inputs(
            repository.connection,
            repository.workspace_id,
            scene_id,
            store,
            retained_job_id=first_job,
        )
        is None
    )


def test_retained_job_cannot_be_substituted_for_another_scene(repository, tmp_path):
    store, _captures, scene_id, first_job, _second_job = _two_builds(repository, tmp_path)
    other_scene = uuid.uuid4()
    assert (
        scene_inputs(
            repository.connection,
            repository.workspace_id,
            other_scene,
            store,
            retained_job_id=first_job,
        )
        is None
    )
    assert (
        reconstruction_scene_rows(
            repository.connection,
            repository.workspace_id,
            store,
            scene_id=other_scene,
            retained_job_id=first_job,
        )
        == []
    )
    assert scene_id != other_scene


def test_scene_pin_refuses_malformed_digest_and_another_world(repository, tmp_path):
    store, _captures, scene_id, first_job, _second_job = _two_builds(repository, tmp_path)
    buffered = scene_inputs(
        repository.connection, repository.workspace_id, scene_id, store, retained_job_id=first_job
    )
    assert buffered is not None
    row = buffered[0]
    fields = {
        "profile": "exulanica.arrival-scene-pin/v1",
        "world_id": "world:unrelated",
        "version_id": uuid.uuid4(),
        "source_snapshot_id": uuid.uuid4(),
        "region_id": "region:unrelated",
        "scene_id": scene_id,
        "job_id": first_job,
        "pose_receipt_sha256": bytes(row["content_sha256"]).hex(),
        "placement_receipt_sha256": bytes(row["placement_sha256"]).hex(),
        "gate_receipt_sha256": bytes(row["gate_sha256"]).hex(),
    }
    with pytest.raises(ValueError):
        RetainedScenePin.model_validate(fields | {"gate_receipt_sha256": "invalid"})
    pin = RetainedScenePin.model_validate(fields)
    assert (
        authorized_retained_scene(repository.connection, repository.workspace_id, pin, store)
        is None
    )
