"""Looking for the people in a photograph is a different permission from reconstructing it.

Version 2 of the privacy policy created a loop with no honest way in. A screening is eligible when
a human has confirmed a region list with a consent state per person; producing that list means
looking at the photograph; and looking means showing it to a detector, which needs a screening. A
collection like the retained bowl photographs, which contains diners nobody can ask, could
therefore never be looked at at all. Masking does not help, because the detector reads the
original.

``person_detection_only`` is the way out, and these tests exist to keep it narrow. Every one of
them is about the same risk: that a permission to LOOK quietly becomes a permission to BUILD.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.privacy import (
    authorize_benchmark_capture,
    record_person_detection_screening,
    require_observation_screening,
    require_privacy_screening,
)
from exulanica.store.local import LocalContentAddressedStore

from conftest import iso, write_photo

ACTOR = uuid.UUID("a244f9d0-9bd9-5f55-a133-2712cd05d720")


@pytest.fixture
def detectable(repository, photo_dir, tmp_path):
    """One capture whose bytes may be looked at and may not be reconstructed."""
    write_photo(photo_dir, "a.jpg", when=iso(10))
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store)
    intake = pipeline.ingest_intake((photo_dir / "a.jpg").read_bytes(), filename="a.jpg")
    assert intake.capture_id is not None, intake.error
    authorization = authorize_benchmark_capture(
        repository,
        capture_id=intake.capture_id,
        actor=ACTOR,
        official_source_url="https://example.invalid/dataset",
        retrieval_date="2026-09-06",
        license_document_sha256="c" * 64,
        permitted_use="detection test",
        authorization_scope={"purpose": "detection test"},
    )
    screening = record_person_detection_screening(
        repository,
        authorization_id=authorization.authorization_id,
        authorized_by=ACTOR,
        purpose="find the people in this photograph so they can be hidden",
    )
    return intake.capture_id, screening, store


def test_a_detection_receipt_permits_looking(detectable, repository):
    capture_id, screening, _store = detectable
    assert require_observation_screening(repository, capture_id, screening.screening_id)


def test_a_detection_receipt_never_permits_geometry(detectable, repository):
    """The whole point. A permission to look must not become a permission to build."""
    capture_id, screening, _store = detectable
    with pytest.raises(PrivacyAdmissionError, match="failed, blocked, stale, or withdrawn"):
        require_privacy_screening(repository, capture_id, screening.screening_id)
    assert repository.privacy_screening_allows(capture_id, screening.screening_id) is False


def test_the_database_refuses_a_point_map_on_a_detection_receipt(detectable, repository):
    """Enforced below Python, so a future caller cannot route around the check above."""
    capture_id, screening, _store = detectable
    capture = repository.capture(capture_id)
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        repository.insert_artifact(
            artifact_id=uuid.uuid4(),
            kind="point_map",
            source_blob=capture.blob_id,
            stage_key="depth",
            stage_version=99,
            params_digest=b"\x00" * 32,
            input_digest=b"\x01" * 32,
            idempotency_key="a-point-map-on-a-detection-receipt",
            content_sha256=b"\x02" * 32,
            storage_key="sha-256/02/02/" + "02" * 32,
            byte_size=10,
            produced_by_event=None,
            privacy_screening_id=screening.screening_id,
        )


def test_a_detection_receipt_is_recorded_as_blocked_and_says_why(detectable):
    _capture_id, screening, _store = detectable
    assert screening.eligibility_state == "blocked"


def test_the_receipt_does_not_claim_a_human_reviewed_the_photograph(detectable, repository):
    """Nobody looked at the image. Somebody authorized a detector to. Those are different."""
    _capture_id, screening, _store = detectable
    row = repository.connection.execute(
        "select screening_method, human_review_required, reviewed_by, receipt_record "
        "from reconstruction_privacy_screening where screening_id = %s",
        (screening.screening_id,),
    ).fetchone()
    assert row["screening_method"] == "person_detection_only"
    assert row["human_review_required"] is False
    assert row["reviewed_by"] == ACTOR
    assert row["receipt_record"]["sensitive_regions"] == []


def test_the_reason_records_the_purpose_the_photograph_was_looked_at_for(detectable, repository):
    """Read from the stored row, not rebuilt from the expected string.

    The first version of this test constructed the sentence it then asserted on, which would have
    passed with nothing recorded at all.
    """
    _capture_id, screening, _store = detectable
    row = repository.connection.execute(
        "select blocking_reasons from reconstruction_privacy_screening where screening_id = %s",
        (screening.screening_id,),
    ).fetchone()
    reasons = " ".join(row["blocking_reasons"])
    assert "detection only" in reasons
    assert "find the people in this photograph so they can be hidden" in reasons


def test_a_detection_authorization_needs_a_stated_purpose(repository, photo_dir, tmp_path):
    write_photo(photo_dir, "b.jpg", when=iso(11))
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store)
    intake = pipeline.ingest_intake((photo_dir / "b.jpg").read_bytes(), filename="b.jpg")
    authorization = authorize_benchmark_capture(
        repository,
        capture_id=intake.capture_id,
        actor=ACTOR,
        official_source_url="https://example.invalid/dataset",
        retrieval_date="2026-09-06",
        license_document_sha256="c" * 64,
        permitted_use="detection test",
        authorization_scope={"purpose": "detection test"},
    )
    with pytest.raises(PrivacyAdmissionError, match="records why"):
        record_person_detection_screening(
            repository,
            authorization_id=authorization.authorization_id,
            authorized_by=ACTOR,
            purpose="   ",
        )


def test_an_eligible_receipt_still_permits_both(repository, photo_dir, tmp_path):
    """A capture admitted for geometry has cleared the higher bar and may also be looked at."""
    from exulanica.ingest.privacy import authorize_synthetic_capture, record_synthetic_exemption

    write_photo(photo_dir, "c.jpg", when=iso(12))
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store)
    intake = pipeline.ingest_intake((photo_dir / "c.jpg").read_bytes(), filename="c.jpg")
    authorization = authorize_synthetic_capture(
        repository,
        capture_id=intake.capture_id,
        actor=ACTOR,
        generator_manifest={"profile": "exulanica.synthetic/v1", "notice": "SYNTHETIC"},
        authorization_scope={"purpose": "test"},
    )
    screening = record_synthetic_exemption(
        repository, authorization_id=authorization.authorization_id
    )
    assert require_observation_screening(repository, intake.capture_id, screening.screening_id)
    assert require_privacy_screening(repository, intake.capture_id, screening.screening_id)
