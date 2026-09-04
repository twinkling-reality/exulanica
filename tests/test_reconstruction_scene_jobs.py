"""Durable reconstruction selection, leases, completion and deletion cancellation."""

from __future__ import annotations

import datetime as dt
import uuid

import psycopg
import pytest
from exulanica.evidence.blob import BlobId
from exulanica.evidence.scene import scene_id_for, scene_member_digest
from exulanica.ingest.operations import (
    reconstruction_scene_job,
    reconstruction_scene_metrics,
    retry_reconstruction_scene_job,
)
from exulanica.ingest.privacy import (
    admit_reconstruction_scene,
    authorize_synthetic_capture,
    record_synthetic_exemption,
)
from exulanica.ingest.scene_selection import enqueue_scene_reconstructions
from exulanica.ingest.scenes import SceneGroup
from exulanica.store.local import LocalContentAddressedStore

from conftest import write_point_map


def _captures(repository, count: int = 3) -> list[uuid.UUID]:
    capture_ids: list[uuid.UUID] = []
    for index in range(count):
        blob = BlobId.of_bytes(f"scene input {index}".encode())
        repository.upsert_blob(
            blob,
            byte_size=len(f"scene input {index}"),
            media_type="image/jpeg",
            storage_key=f"sha256/{blob.hex}",
        )
        capture_ids.append(
            repository.insert_capture(
                blob,
                device_id=None,
                started_at=f"2026-09-04T12:0{index}:00+00:00",
            ).capture_id
        )
    return capture_ids


def _policy() -> dict[str, object]:
    return {
        "profile": "exulanica.scene-group-pose-selection/v1",
        "minimum_member_count": 3,
        "ordering": "scene-group-presentation-order",
    }


def _enqueue(repository, captures, *, build_inputs=None):
    screening_ids = []
    for capture_id in captures:
        authorization = authorize_synthetic_capture(
            repository,
            capture_id=capture_id,
            actor=uuid.UUID("f0a03490-8b8a-5260-89e9-77ad3cc814b2"),
            generator_manifest={
                "profile": "exulanica.scene-job-test/v1",
                "notice": "SYNTHETIC TEST FIXTURE",
            },
            authorization_scope={"purpose": "scene job test"},
            authorized_at=dt.datetime(2026, 9, 4, tzinfo=dt.UTC),
        )
        screening_ids.append(
            record_synthetic_exemption(
                repository,
                authorization_id=authorization.authorization_id,
                screened_at=dt.datetime(2026, 9, 4, tzinfo=dt.UTC),
            ).screening_id
        )
    admission = admit_reconstruction_scene(
        repository,
        capture_ids=captures,
        screening_ids=screening_ids,
    )
    return repository.enqueue_reconstruction_scene(
        capture_ids=captures,
        selection_policy=_policy(),
        privacy_admission_id=admission.admission_id,
        privacy_admission_digest=admission.admission_digest,
        build_inputs=build_inputs,
    )


def test_enqueue_is_deterministic_and_a_restart_claims_the_exact_order(ingest_spine):
    repository, reopen = ingest_spine
    captures = _captures(repository)

    job_id, inserted = _enqueue(repository, captures)
    same_id, inserted_again = _enqueue(repository, captures)

    assert inserted is True
    assert inserted_again is False
    assert same_id == job_id
    claimed = reopen().claim_reconstruction_scene(worker="after-restart", lease_seconds=60)
    assert claimed is not None
    assert claimed.job_id == job_id
    assert claimed.scene_id == scene_id_for(captures)
    assert claimed.member_digest == scene_member_digest(captures)
    assert [member.capture_id for member in claimed.members] == captures
    assert claimed.attempts == 1
    assert claimed.reclaimed is False


def test_the_initial_policy_waits_for_every_point_map_and_binds_exact_inputs(repository, tmp_path):
    captures = _captures(repository, 5)
    groups = [
        SceneGroup(ordinal=0, capture_ids=captures[:2]),
        SceneGroup(ordinal=1, capture_ids=captures[2:]),
    ]

    assert enqueue_scene_reconstructions(repository, groups) == []
    store = LocalContentAddressedStore(tmp_path / "store")
    for index, capture_id in enumerate(captures[2:]):
        capture = repository.capture(capture_id)
        assert capture is not None
        write_point_map(
            repository,
            store,
            capture.blob_id,
            payload=f"point map {index}".encode(),
        )

    selections = enqueue_scene_reconstructions(repository, groups)

    selected_groups = [
        (selection.scene_group_ordinal, selection.member_count) for selection in selections
    ]
    assert selected_groups == [(1, 3)]
    row = repository.connection.execute(
        "select selection_policy,build_inputs from reconstruction_scene_job where workspace_id=%s",
        (repository.workspace_id,),
    ).fetchone()
    assert row is not None
    assert row["selection_policy"]["source"] == {
        "kind": "scene_group",
        "group_key": groups[1].key,
        "group_ordinal": 1,
        "stage_version": 1,
        "stage_params_sha256": row["selection_policy"]["source"]["stage_params_sha256"],
    }
    assert "not been validated" in row["selection_policy"]["limitations"][0]
    assert row["build_inputs"]["profile"] == "exulanica.reconstruction-scene-build-input/v1"
    assert [item["capture_ref"] for item in row["build_inputs"]["point_maps"]] == [
        str(capture_id) for capture_id in captures[2:]
    ]


def test_two_claimants_do_not_receive_the_same_scene(ingest_spine):
    repository, reopen = ingest_spine
    _enqueue(repository, _captures(repository))

    first = reopen().claim_reconstruction_scene(worker="first", lease_seconds=60)
    second = reopen().claim_reconstruction_scene(worker="second", lease_seconds=60)

    assert first is not None
    assert second is None


def test_scene_operations_report_exact_inputs_and_only_accelerate_retryable_failures(repository):
    job_id, _inserted = _enqueue(repository, _captures(repository))
    claimed = repository.claim_reconstruction_scene(worker="operator-test", lease_seconds=60)
    assert claimed is not None
    repository.fail_reconstruction_scene_job(
        job_id=job_id,
        claim_token=claimed.claim_token,
        failure_class="measured_failure",
        failure_message="retry later",
        retry_delay_seconds=3600,
    )

    metrics = reconstruction_scene_metrics(repository.connection, repository.workspace_id)
    assert metrics["depth"] == {
        "queued": 0,
        "running": 0,
        "retryable": 1,
        "waiting_for_point_maps": 0,
    }
    assert metrics["coordination"]["state"] == "building"
    assert metrics["states"] == {"succeeded": 0, "failed": 1, "cancelled": 0}
    detail = reconstruction_scene_job(
        repository.connection,
        repository.workspace_id,
        job_id,
    )
    assert detail is not None
    assert detail["job_id"] == str(job_id)
    assert detail["status"] == "failed"
    assert detail["failure_class"] == "measured_failure"
    assert detail["current"] is False
    assert len(detail["members"]) == 3

    with repository.transaction():
        assert (
            retry_reconstruction_scene_job(
                repository.connection,
                repository.workspace_id,
                job_id,
            )
            == "retryable"
        )
    assert repository.claim_reconstruction_scene(worker="retry", lease_seconds=60) is not None
    assert (
        retry_reconstruction_scene_job(
            repository.connection,
            repository.workspace_id,
            uuid.uuid4(),
        )
        is None
    )


def test_expired_claim_rotates_the_token_and_stale_completion_is_refused(ingest_spine):
    repository, reopen = ingest_spine
    job_id, _ = _enqueue(repository, _captures(repository))
    first_repository = reopen()
    first = first_repository.claim_reconstruction_scene(worker="first", lease_seconds=60)
    assert first is not None
    repository.connection.execute(
        "update reconstruction_scene_job set lease_expires_at=now()-interval '1 second' "
        "where workspace_id=%s and job_id=%s",
        (repository.workspace_id, job_id),
    )

    second = reopen().claim_reconstruction_scene(worker="second", lease_seconds=60)

    assert second is not None
    assert second.reclaimed is True
    assert second.attempts == 2
    assert second.claim_token != first.claim_token
    assert (
        first_repository.complete_reconstruction_scene_job(
            job_id=job_id,
            claim_token=first.claim_token,
            scratch_key="old",
            pose_manifest_digest=b"\x01" * 32,
            pose_receipt_artifact_id=uuid.uuid4(),
            placement_artifact_id=uuid.uuid4(),
            gate_artifact_id=uuid.uuid4(),
            rung_assertion_id=uuid.uuid4(),
        )
        is False
    )


def test_completion_records_partial_registration_once(ingest_spine):
    repository, _reopen = ingest_spine
    captures = _captures(repository)
    scene_id = scene_id_for(captures)
    digest = scene_member_digest(captures)
    registrations = [(captures[0], True), (captures[1], False), (captures[2], True)]

    with repository.transaction():
        assert repository.insert_completed_reconstruction_scene(
            scene_id=scene_id, member_digest=digest, scene_members=registrations
        )
    with repository.transaction():
        assert not repository.insert_completed_reconstruction_scene(
            scene_id=scene_id, member_digest=digest, scene_members=registrations
        )

    members = repository.reconstruction_scene_members(scene_id)
    assert [(member.capture_id, member.registered) for member in members] == registrations
    with (
        pytest.raises(ValueError, match="disagrees"),
        repository.transaction(),
    ):
        repository.insert_completed_reconstruction_scene(
            scene_id=scene_id,
            member_digest=digest,
            scene_members=[(capture_id, True) for capture_id in captures],
        )


def test_deleting_any_pending_member_cancels_the_job(ingest_spine):
    repository, _reopen = ingest_spine
    captures = _captures(repository)
    job_id, _ = _enqueue(repository, captures)
    claimed = repository.claim_reconstruction_scene(worker="pose", lease_seconds=60)
    assert claimed is not None

    repository.insert_tombstone(
        scope="capture",
        capture_id=captures[1],
        requested_by=uuid.uuid4(),
        reason="delete one of the pending inputs",
    )

    row = repository.connection.execute(
        "select status,claim_token,completed_at from reconstruction_scene_job "
        "where workspace_id=%s and job_id=%s",
        (repository.workspace_id, job_id),
    ).fetchone()
    assert row is not None
    assert row["status"] == "cancelled"
    assert row["claim_token"] is None
    assert row["completed_at"] is not None
    assert repository.reconstruction_scene_cancelled_or_lost(
        job_id=job_id, claim_token=claimed.claim_token
    )


def test_job_membership_cannot_be_changed_after_enqueue(repository):
    captures = _captures(repository)
    job_id, _ = _enqueue(repository, captures)

    with (
        pytest.raises(psycopg.errors.IntegrityConstraintViolation),
        repository.connection.transaction(),
    ):
        repository.connection.execute(
            "update reconstruction_scene_job_member set ordinal=7 "
            "where workspace_id=%s and job_id=%s and capture_id=%s",
            (repository.workspace_id, job_id, captures[0]),
        )
    with (
        pytest.raises(psycopg.errors.IntegrityConstraintViolation),
        repository.connection.transaction(),
    ):
        repository.connection.execute(
            "update reconstruction_scene_job set build_inputs='{}'::jsonb "
            "where workspace_id=%s and job_id=%s",
            (repository.workspace_id, job_id),
        )
