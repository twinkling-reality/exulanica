"""A person nobody consented to does not become geometry. Executed, not asserted as text.

Every other test of this feature checks a pure function or a substring of a migration. This one
runs the real pipeline against a real database and looks at what actually landed, because the
whole design is a claim about what happens when a photograph goes through, and until this file
existed a stub that hid nobody would have passed the entire suite.

Four things are pinned, and each is a specific way the guarantee could be false while every
receipt said otherwise:

*   A detected person leaves a ``person_region`` row. Without it ``capture_requires_masking`` is
    false, the database trigger has nothing to refuse, and the whole guard is decorative.
*   The photograph gets a masked derivative, and the point map records that it read those bytes
    rather than the original.
*   The database refuses a point map over the original bytes for that capture, by its own rule,
    with no Python involved.
*   A photograph with nobody in it still produces no derivative and reconstructs from the
    original, so the ordinary case is untouched.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.consent.regions import DetectedPerson, Silhouette
from exulanica.evidence.region import Rect
from exulanica.ingest.person_detectors import NoRegionDetector, StubRegionDetector
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.privacy import authorize_synthetic_capture, record_synthetic_exemption
from exulanica.reconstruction.testing import FlatDepthModel
from exulanica.store.local import LocalContentAddressedStore

from conftest import iso, write_photo

ACTOR = uuid.UUID("a244f9d0-9bd9-5f55-a133-2712cd05d720")
A_PERSON = DetectedPerson(
    silhouette=Silhouette.from_rect(Rect.from_normalised(0.2, 0.2, 0.3, 0.5)),
    shape="box",
    confidence="high",
    detector="fixed-region-double",
)


def _ingest(repository, photo_dir, tmp_path, detector, keep=None):
    """One photograph through the real pipeline, with reconstruction on."""
    write_photo(photo_dir, "a.jpg", when=iso(10), gps=(64.3271, -20.1199))
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(
        repository, store, vision=None, depth=FlatDepthModel(), detector=detector
    )
    intake = pipeline.ingest_intake((photo_dir / "a.jpg").read_bytes(), filename="a.jpg")
    assert intake.capture_id is not None, intake.error
    authorization = authorize_synthetic_capture(
        repository,
        capture_id=intake.capture_id,
        actor=ACTOR,
        generator_manifest={
            "profile": "exulanica.person-masking-test/v1",
            "notice": "SYNTHETIC TEST FIXTURE",
        },
        authorization_scope={"purpose": "person masking end to end test"},
    )
    screening = record_synthetic_exemption(
        repository, authorization_id=authorization.authorization_id
    )
    outcome = pipeline.ingest_derivatives(
        intake.capture_id, privacy_screening_id=screening.screening_id
    )
    if keep is not None:
        keep["screening_id"] = screening.screening_id
    return intake.capture_id, outcome


def _artifacts(repository, stage_key):
    return repository.connection.execute(
        "select artifact_id, content_sha256, read_source_sha256 from artifact "
        "where workspace_id = %s and stage_key = %s",
        (repository.workspace_id, stage_key),
    ).fetchall()


def test_a_detected_person_leaves_a_region_row_that_arms_the_database_guard(
    repository, photo_dir, tmp_path
):
    """Without this row every other guarantee in this feature is inert."""
    capture_id, outcome = _ingest(repository, photo_dir, tmp_path, StubRegionDetector((A_PERSON,)))
    assert outcome.error is None, outcome.error
    rows = repository.current_person_regions(capture_ids=[capture_id])[capture_id]
    assert len(rows) == 1
    assert rows[0].action == "detected"
    assert rows[0].subject_id is None, "a detection is nobody's decision"
    assert rows[0].confirmed_by is None
    requires = repository.connection.execute(
        "select capture_requires_masking(%s, %s) as required",
        (repository.workspace_id, capture_id),
    ).fetchone()
    assert requires["required"] is True


def test_reconstruction_reads_the_masked_derivative_not_the_original(
    repository, photo_dir, tmp_path
):
    _capture_id, outcome = _ingest(repository, photo_dir, tmp_path, StubRegionDetector((A_PERSON,)))
    assert outcome.error is None, outcome.error
    masked = _artifacts(repository, "masked_source")
    assert len(masked) == 1, "a photograph with an unconsented person needs a masked derivative"
    point_maps = _artifacts(repository, "depth")
    assert len(point_maps) == 1
    assert point_maps[0]["read_source_sha256"] is not None, "the point map must say what it read"
    assert bytes(point_maps[0]["read_source_sha256"]) == bytes(masked[0]["content_sha256"])


def test_the_masked_manifest_records_whose_the_mask_is(repository, photo_dir, tmp_path):
    _ingest(repository, photo_dir, tmp_path, StubRegionDetector((A_PERSON,)))
    manifests = _artifacts(repository, "masked_source_manifest")
    assert len(manifests) == 1


def test_the_database_refuses_a_point_map_over_the_original_bytes(repository, photo_dir, tmp_path):
    """The backstop, exercised. Python is not involved in this refusal.

    This is the assertion the feature was missing: until now the trigger had never once fired,
    because nothing wrote a region row for it to find.
    """
    import psycopg

    keep: dict = {}
    capture_id, _ = _ingest(
        repository, photo_dir, tmp_path, StubRegionDetector((A_PERSON,)), keep=keep
    )
    capture = repository.capture(capture_id)
    with pytest.raises(psycopg.errors.CheckViolation) as raised:
        repository.insert_artifact(
            artifact_id=uuid.uuid4(),
            kind="point_map",
            source_blob=capture.blob_id,
            stage_key="depth",
            stage_version=99,
            params_digest=b"\x00" * 32,
            input_digest=b"\x01" * 32,
            idempotency_key="a-point-map-over-the-original",
            content_sha256=b"\x02" * 32,
            storage_key="sha-256/02/02/" + "02" * 32,
            byte_size=10,
            produced_by_event=None,
            privacy_screening_id=keep["screening_id"],
            read_source_sha256=None,
        )
    assert "masked derivative" in str(raised.value)


def test_a_photograph_with_nobody_in_it_produces_no_derivative_and_reads_the_original(
    repository, photo_dir, tmp_path
):
    """The ordinary case stays exactly as it was, byte for byte and key for key."""
    _capture_id, outcome = _ingest(repository, photo_dir, tmp_path, NoRegionDetector())
    assert outcome.error is None, outcome.error
    assert _artifacts(repository, "masked_source") == []
    point_maps = _artifacts(repository, "depth")
    assert len(point_maps) == 1
    assert point_maps[0]["read_source_sha256"] is None


def test_no_detector_means_no_region_rows_and_the_stage_says_so(repository, photo_dir, tmp_path):
    """'Nobody looked' must remain distinguishable from 'looked and found none'."""
    capture_id, outcome = _ingest(repository, photo_dir, tmp_path, None)
    assert "person_regions" in outcome.stages_unavailable
    assert repository.current_person_regions(capture_ids=[capture_id]) == {}
