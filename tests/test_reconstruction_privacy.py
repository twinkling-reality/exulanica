"""Reconstruction privacy is a durable fail-closed admission boundary."""

from __future__ import annotations

import datetime as dt
import uuid

import psycopg
import pytest
from exulanica.errors import PrivacyAdmissionError
from exulanica.evidence.blob import BlobId
from exulanica.ingest.privacy import (
    admit_reconstruction_scene,
    authorize_benchmark_capture,
    authorize_synthetic_capture,
    record_human_screening,
    record_synthetic_exemption,
)
from exulanica.ingest.stages import artifact_id_for, idempotency_key, input_digest_of, stage

_ACTOR = uuid.UUID("8eb53498-71cd-5a97-ae51-0bf5ed75a0da")
_AT = dt.datetime(2026, 9, 4, 12, tzinfo=dt.UTC)
_SCOPE = {"campaign": "safe-reconstruction-validation", "purpose": "engineering evaluation"}


def _capture(repository, label: str):
    data = f"privacy source {label}".encode()
    blob = BlobId.of_bytes(data)
    repository.upsert_blob(
        blob,
        byte_size=len(data),
        media_type="image/jpeg",
        storage_key=f"sha256/{blob.hex}",
    )
    capture = repository.insert_capture(blob, device_id=None, started_at=None)
    return capture, blob


def _synthetic_screening(repository, capture_id):
    authorization = authorize_synthetic_capture(
        repository,
        capture_id=capture_id,
        actor=_ACTOR,
        generator_manifest={
            "profile": "exulanica.synthetic-multiview/v1",
            "seed": 20260904,
            "notice": "SYNTHETIC",
        },
        authorization_scope=_SCOPE,
        authorized_at=_AT,
    )
    return record_synthetic_exemption(
        repository,
        authorization_id=authorization.authorization_id,
        screened_at=_AT,
    )


def _insert_point_map(repository, blob, screening_id=None):
    spec = stage("depth")
    input_digest = input_digest_of([])
    key = idempotency_key(
        blob,
        spec,
        input_digest,
        binding={"model_id": "privacy-boundary-test"},
    )
    return repository.insert_artifact(
        artifact_id=artifact_id_for(key),
        kind="point_map",
        source_blob=blob,
        stage_key=spec.key,
        stage_version=spec.version,
        params_digest=spec.params_digest,
        input_digest=input_digest,
        idempotency_key=key,
        content_sha256=BlobId.of_bytes(b"point map").digest,
        storage_key="sha256/privacy-point-map",
        byte_size=9,
        produced_by_event=None,
        privacy_screening_id=screening_id,
    )


def test_point_map_insert_fails_closed_without_screening(repository):
    _capture_row, blob = _capture(repository, "missing")

    with (
        pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="privacy screening"),
        repository.connection.transaction(),
    ):
        _insert_point_map(repository, blob)


def test_detected_person_and_failed_or_stale_review_cannot_authorize_geometry(repository):
    capture, blob = _capture(repository, "real")
    authorization = authorize_benchmark_capture(
        repository,
        capture_id=capture.capture_id,
        actor=_ACTOR,
        official_source_url="https://benchmark.example/official",
        retrieval_date="2026-09-04",
        license_document_sha256="ab" * 32,
        permitted_use="non-commercial engineering evaluation",
        authorization_scope=_SCOPE,
        authorized_at=_AT,
    )
    detected = record_human_screening(
        repository,
        authorization_id=authorization.authorization_id,
        reviewed_by=_ACTOR,
        sensitive_regions=[{"kind": "person", "rect_ppm": [1, 2, 3, 4]}],
        screened_at=_AT,
    )
    failed = record_human_screening(
        repository,
        authorization_id=authorization.authorization_id,
        reviewed_by=_ACTOR,
        sensitive_regions=[],
        failure_reason="review input could not be decoded",
        screened_at=_AT + dt.timedelta(minutes=1),
    )
    stale = record_human_screening(
        repository,
        authorization_id=authorization.authorization_id,
        reviewed_by=_ACTOR,
        sensitive_regions=[],
        screened_at=_AT - dt.timedelta(days=2),
        valid_until=_AT - dt.timedelta(days=1),
    )

    for receipt in (detected, failed, stale):
        with (
            pytest.raises(
                psycopg.errors.IntegrityConstraintViolation,
                match="privacy screening",
            ),
            repository.connection.transaction(),
        ):
            _insert_point_map(repository, blob, receipt.screening_id)


def test_synthetic_exemption_is_impossible_for_benchmark_media(repository):
    capture, _blob = _capture(repository, "benchmark")
    authorization = authorize_benchmark_capture(
        repository,
        capture_id=capture.capture_id,
        actor=_ACTOR,
        official_source_url="https://benchmark.example/official",
        retrieval_date="2026-09-04",
        license_document_sha256="cd" * 32,
        permitted_use="non-commercial engineering evaluation",
        authorization_scope=_SCOPE,
        authorized_at=_AT,
    )

    with pytest.raises(PrivacyAdmissionError, match="cannot be applied"):
        record_synthetic_exemption(
            repository,
            authorization_id=authorization.authorization_id,
            screened_at=_AT,
        )


def test_canonical_authorization_bytes_and_digest_cannot_disagree(repository):
    capture, _blob = _capture(repository, "canonical")
    authorization = authorize_synthetic_capture(
        repository,
        capture_id=capture.capture_id,
        actor=_ACTOR,
        generator_manifest={
            "profile": "exulanica.canonical-test/v1",
            "notice": "SYNTHETIC TEST FIXTURE",
        },
        authorization_scope=_SCOPE,
        authorized_at=_AT,
    )

    with (
        pytest.raises(psycopg.errors.CheckViolation),
        repository.connection.transaction(),
    ):
        repository.connection.execute(
            "insert into capture_reconstruction_authorization "
            "select gen_random_uuid(),workspace_id,capture_id,source_sha256,corpus_class,"
            "purpose,authorization_scope,authorization_evidence,authorization_record,"
            "%s,evidence_digest,synthetic_manifest_digest,authorized_by,authorized_at,valid_until "
            "from capture_reconstruction_authorization "
            "where workspace_id=%s and authorization_id=%s",
            (b"{}", repository.workspace_id, authorization.authorization_id),
        )


def test_exact_ordered_admission_is_bound_to_the_scene_job(repository):
    captures = [_capture(repository, str(index))[0] for index in range(3)]
    screenings = [
        _synthetic_screening(repository, capture.capture_id) for capture in captures
    ]
    admission = admit_reconstruction_scene(
        repository,
        capture_ids=[capture.capture_id for capture in captures],
        screening_ids=[screening.screening_id for screening in screenings],
    )

    job_id, inserted = repository.enqueue_reconstruction_scene(
        capture_ids=[capture.capture_id for capture in captures],
        selection_policy={"profile": "exulanica.exact-set-test/v1"},
        privacy_admission_id=admission.admission_id,
        privacy_admission_digest=admission.admission_digest,
    )

    assert inserted is True
    row = repository.connection.execute(
        "select privacy_admission_id,privacy_admission_digest "
        "from reconstruction_scene_job where workspace_id=%s and job_id=%s",
        (repository.workspace_id, job_id),
    ).fetchone()
    assert row["privacy_admission_id"] == admission.admission_id
    assert bytes(row["privacy_admission_digest"]) == admission.admission_digest
    assert repository.claim_reconstruction_scene(worker="privacy-test", lease_seconds=60)


def test_missing_member_screening_persists_a_blocked_exact_set(repository):
    captures = [_capture(repository, str(index))[0] for index in range(3)]
    screening = _synthetic_screening(repository, captures[0].capture_id)

    admission = admit_reconstruction_scene(
        repository,
        capture_ids=[capture.capture_id for capture in captures],
        screening_ids=[screening.screening_id, None, None],
        admitted_at=_AT,
    )

    assert admission.eligibility_state == "blocked"
    assert admission.corpus_class == "synthetic"
    assert admission.blocking_reasons == (
        "member 1 has no screening for its exact source",
        "member 2 has no screening for its exact source",
    )
    with (
        pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="privacy admission"),
        repository.connection.transaction(),
    ):
        repository.enqueue_reconstruction_scene(
            capture_ids=[capture.capture_id for capture in captures],
            selection_policy={"profile": "exulanica.blocked-set-test/v1"},
            privacy_admission_id=admission.admission_id,
            privacy_admission_digest=admission.admission_digest,
        )
