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

import datetime as dt
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


# ---------------------------------------------------------------------------------------------
# The review loop: propose, confirm, decide, and watch the mask lift


def _review(repository):
    from exulanica.ingest import person_review

    return person_review


def test_a_reviewer_confirming_a_person_keeps_them_masked(repository, photo_dir, tmp_path):
    """Confirming that somebody is there is not consenting on their behalf."""
    review = _review(repository)
    capture_id, _ = _ingest(repository, photo_dir, tmp_path, StubRegionDetector((A_PERSON,)))
    key = repository.current_person_regions(capture_ids=[capture_id])[capture_id][0].region_key
    review.record_region_edits(
        repository,
        capture_id=capture_id,
        actor=ACTOR,
        edits=[{"region_key": key.hex(), "action": "confirm"}],
    )
    listed = review.review_list(repository, capture_id)
    assert listed[0]["confirmed_by"] == str(ACTOR)
    assert listed[0]["state"] == "unknown", "a confirmation decides nothing about consent"
    assert listed[0]["masked"] is True


def test_consenting_to_likeness_unmasks_that_person_and_nobody_else(
    repository, photo_dir, tmp_path
):
    """The payoff. A decision recorded here changes what reconstruction is allowed to read."""
    review = _review(repository)
    capture_id, _ = _ingest(repository, photo_dir, tmp_path, StubRegionDetector((A_PERSON,)))
    key = repository.current_person_regions(capture_ids=[capture_id])[capture_id][0].region_key
    subject_id = review.create_subject(repository, actor=ACTOR)
    review.record_region_edits(
        repository,
        capture_id=capture_id,
        actor=ACTOR,
        edits=[{"region_key": key.hex(), "action": "confirm", "subject_id": str(subject_id)}],
    )
    assert review.review_list(repository, capture_id)[0]["state"] == "unknown"

    review.record_consent(
        repository,
        subject_id=subject_id,
        actor=ACTOR,
        consent_scope="likeness",
        decision="granted",
    )
    after = review.review_list(repository, capture_id)[0]
    assert after["state"] == "shown"
    assert after["masked"] is False
    requires = repository.connection.execute(
        "select capture_requires_masking(%s, %s) as required",
        (repository.workspace_id, capture_id),
    ).fetchone()
    assert requires["required"] is False, "a consented person no longer forces a mask"


def test_presence_and_naming_do_not_unmask(repository, photo_dir, tmp_path):
    """Three separate consents, and only one of them reaches the pixels."""
    review = _review(repository)
    capture_id, _ = _ingest(repository, photo_dir, tmp_path, StubRegionDetector((A_PERSON,)))
    key = repository.current_person_regions(capture_ids=[capture_id])[capture_id][0].region_key
    subject_id = review.create_subject(repository, actor=ACTOR)
    review.record_region_edits(
        repository,
        capture_id=capture_id,
        actor=ACTOR,
        edits=[{"region_key": key.hex(), "action": "confirm", "subject_id": str(subject_id)}],
    )
    for scope in ("presence", "naming"):
        review.record_consent(
            repository,
            subject_id=subject_id,
            actor=ACTOR,
            consent_scope=scope,
            decision="granted",
        )
    after = review.review_list(repository, capture_id)[0]
    assert after["state"] == "present"
    assert after["masked"] is True
    assert after["name_permitted"] is True, "named, and still not shown"


def test_revoking_likeness_masks_the_person_again(repository, photo_dir, tmp_path):
    review = _review(repository)
    capture_id, _ = _ingest(repository, photo_dir, tmp_path, StubRegionDetector((A_PERSON,)))
    key = repository.current_person_regions(capture_ids=[capture_id])[capture_id][0].region_key
    subject_id = review.create_subject(repository, actor=ACTOR)
    review.record_region_edits(
        repository,
        capture_id=capture_id,
        actor=ACTOR,
        edits=[{"region_key": key.hex(), "action": "confirm", "subject_id": str(subject_id)}],
    )
    review.record_consent(
        repository,
        subject_id=subject_id,
        actor=ACTOR,
        consent_scope="likeness",
        decision="granted",
    )
    assert review.review_list(repository, capture_id)[0]["masked"] is False
    review.record_consent(
        repository,
        subject_id=subject_id,
        actor=ACTOR,
        consent_scope="likeness",
        decision="revoked",
    )
    assert review.review_list(repository, capture_id)[0]["masked"] is True


def test_a_deleted_false_positive_stops_requiring_a_mask(repository, photo_dir, tmp_path):
    """A reviewer deleting a detector's mistake must not leave the photograph blocked forever."""
    review = _review(repository)
    capture_id, _ = _ingest(repository, photo_dir, tmp_path, StubRegionDetector((A_PERSON,)))
    key = repository.current_person_regions(capture_ids=[capture_id])[capture_id][0].region_key
    review.record_region_edits(
        repository,
        capture_id=capture_id,
        actor=ACTOR,
        edits=[{"region_key": key.hex(), "action": "delete"}],
    )
    assert review.review_list(repository, capture_id) == []
    requires = repository.connection.execute(
        "select capture_requires_masking(%s, %s) as required",
        (repository.workspace_id, capture_id),
    ).fetchone()
    assert requires["required"] is False


def test_a_reviewer_may_add_a_region_the_detector_missed(repository, photo_dir, tmp_path):
    """The bowl case: the detector finds nobody and a human sees an arm at the edge."""
    review = _review(repository)
    capture_id, _ = _ingest(repository, photo_dir, tmp_path, NoRegionDetector())
    assert review.review_list(repository, capture_id) == []
    outline = Silhouette.from_rect(Rect.from_normalised(0.8, 0.4, 0.15, 0.4))
    from exulanica.consent.regions import region_key as key_of
    from exulanica.evidence.region import DisplayGeometry

    capture = repository.capture(capture_id)
    key = key_of(capture.blob_id, outline, DisplayGeometry(w=160, h=100))
    review.record_region_edits(
        repository,
        capture_id=capture_id,
        actor=ACTOR,
        edits=[
            {
                "region_key": key.hex(),
                "action": "add",
                "shape": "polygon",
                "silhouette": outline.as_digest_input(),
            }
        ],
    )
    listed = review.review_list(repository, capture_id)
    assert len(listed) == 1
    assert listed[0]["masked"] is True
    assert listed[0]["detector_id"] is None, "a human addition names no detector"


def test_a_consent_receipt_is_always_recorded_as_the_owner(repository, photo_dir, tmp_path):
    """The owner cannot record a decision as though the photographed person had made it."""
    review = _review(repository)
    subject_id = review.create_subject(repository, actor=ACTOR)
    review.record_consent(
        repository,
        subject_id=subject_id,
        actor=ACTOR,
        consent_scope="likeness",
        decision="granted",
    )
    rows = repository.person_consent_transitions(subject_id=subject_id)
    assert [row.actor_role for row in rows] == ["owner"]
    assert [row.actor_id for row in rows] == [ACTOR]


def _screening_reasons(repository, screening):
    """The stated reasons on the stored receipt, which is where they live rather than on the row."""
    row = repository.connection.execute(
        "select blocking_reasons from reconstruction_privacy_screening "
        "where workspace_id = %s and screening_id = %s",
        (repository.workspace_id, screening.screening_id),
    ).fetchone()
    return " ".join(row["blocking_reasons"] or [])


def _human_screening(repository, capture_id, regions):
    """A named human's screening over these exact bytes, naming the people they saw."""
    from exulanica.ingest.privacy import authorize_benchmark_capture, record_human_screening

    authorization = authorize_benchmark_capture(
        repository,
        capture_id=capture_id,
        actor=ACTOR,
        official_source_url="https://example.invalid/fixture",
        retrieval_date="2026-09-07",
        license_document_sha256="0" * 64,
        permitted_use="test fixture",
        authorization_scope={"purpose": "screening rule test"},
        purpose="screening rule test",
        authorized_at=dt.datetime(2026, 9, 7, tzinfo=dt.UTC),
    )
    return record_human_screening(
        repository,
        authorization_id=authorization.authorization_id,
        reviewed_by=ACTOR,
        sensitive_regions=regions,
        screened_at=dt.datetime(2026, 9, 7, tzinfo=dt.UTC),
    )


def test_a_reviewer_may_name_an_unconsented_person_once_the_mask_exists(
    repository, photo_dir, tmp_path
):
    """The rule that made this feature reachable, and the one that keeps it honest.

    Until 2026-09-07 a screening naming anybody in a masked state was blocked outright, so a
    photograph containing somebody who had not consented could obtain no eligible screening at
    all. The only screening production could write was an empty region list, which is the
    statement "there is nobody here" that this layer exists to retire, and the masking path was
    reachable only when the screening's list and the person_region table disagreed.

    What replaced it is not the absence of a rule. A masked region is eligible only when this
    photograph has a masked_source derivative under the key today's regions and consents produce,
    which is what the old comment said the rule should become once masking was wired. Both halves
    are executed here against a real PostgreSQL, a real migration and a real on-disk store.
    """
    capture_id, _ = _ingest(repository, photo_dir, tmp_path, StubRegionDetector((A_PERSON,)))
    assert _artifacts(repository, "masked_source"), "the fixture must have produced a derivative"
    listed = _review(repository).review_list(repository, capture_id)
    assert listed[0]["state"] == "unknown", "nobody consented, so this person is masked"

    screening = _human_screening(
        repository, capture_id, [{"state": "unknown", "region_key": listed[0]["region_key"]}]
    )
    assert screening.eligibility_state == "eligible", (
        "a person who is actually masked must not block the screening that names them"
    )


def test_naming_a_person_the_pipeline_has_not_masked_still_blocks(repository, photo_dir, tmp_path):
    """The half that must not relax, and the failure it catches is the whole feature inverted.

    A reviewer sees somebody the detector missed and says so BEFORE any mask exists for them. If
    that screening were eligible, the photograph would be admitted on the strength of a mask
    nobody had built, which is worse than the version 1 rule this replaced: version 1 at least
    refused the photograph. So the region list disagreeing with the derivative blocks, and the
    reason says what would end it.
    """
    capture_id, _ = _ingest(repository, photo_dir, tmp_path, NoRegionDetector())
    assert not _artifacts(repository, "masked_source"), "nobody was detected, so nothing is masked"

    screening = _human_screening(repository, capture_id, [{"state": "unknown"}])
    assert screening.eligibility_state == "blocked"
    assert "no current masked source derivative" in _screening_reasons(repository, screening)


def test_a_mask_built_before_the_reviewer_added_a_region_is_not_current(
    repository, photo_dir, tmp_path
):
    """Present is not current, and this is the case where the difference bites.

    The derivative's key folds the confirmed region set and the resolved consent states, so a
    reviewer adding somebody the detector missed moves the key and the mask on disk stops being an
    answer. A check that asked only "does a masked_source artifact exist for this capture" would
    say yes here and admit a photograph whose newest person is not masked at all.
    """
    from exulanica.consent.regions import region_key as key_of
    from exulanica.evidence.region import DisplayGeometry

    review = _review(repository)
    capture_id, _ = _ingest(repository, photo_dir, tmp_path, StubRegionDetector((A_PERSON,)))
    assert _artifacts(repository, "masked_source"), "the detected person produced a derivative"

    outline = Silhouette.from_rect(Rect.from_normalised(0.75, 0.05, 0.15, 0.4))
    capture = repository.capture(capture_id)
    review.record_region_edits(
        repository,
        capture_id=capture_id,
        actor=ACTOR,
        edits=[
            {
                "region_key": key_of(capture.blob_id, outline, DisplayGeometry(w=160, h=100)).hex(),
                "action": "add",
                "shape": "polygon",
                "silhouette": outline.as_digest_input(),
            }
        ],
    )
    # Both regions are named and both are genuinely masked in the table, so this cannot block for
    # the unkeyed reason the test above covers. What is stale is the derivative.
    named = [
        {"state": row["state"], "region_key": row["region_key"]}
        for row in review.review_list(repository, capture_id)
    ]
    assert len(named) == 2 and all(row["state"] == "unknown" for row in named)
    screening = _human_screening(repository, capture_id, named)
    assert screening.eligibility_state == "blocked", (
        "the derivative on disk predates this region, so it does not hide the new person"
    )
    assert "no current masked source derivative" in _screening_reasons(repository, screening)


def test_a_reviewer_who_deleted_every_false_positive_has_still_looked(
    repository, photo_dir, tmp_path
):
    """The review screen must not tell the next reviewer that nobody has looked at this one.

    ``review_list`` excludes deleted regions, so a photograph whose every proposal a reviewer threw
    out comes back with an empty list. The route derived ``review_state`` from that emptiness,
    which made "nobody has looked" and "somebody looked and found nobody" the same answer: exactly
    the collapse this layer exists to undo, reappearing in the screen built to undo it.

    It also disagreed with the graph payload about the same photograph.
    ``review_states_for_captures`` asks the raw table and answers ``screened``, so the browser's
    own status line and its review panel would have contradicted each other.
    """
    from exulanica.graph.person_regions import review_states_for_captures

    review = _review(repository)
    capture_id, _ = _ingest(repository, photo_dir, tmp_path, StubRegionDetector((A_PERSON,)))
    key = repository.current_person_regions(capture_ids=[capture_id])[capture_id][0].region_key
    review.record_region_edits(
        repository,
        capture_id=capture_id,
        actor=ACTOR,
        edits=[{"region_key": key.hex(), "action": "delete"}],
    )

    assert review.review_list(repository, capture_id) == [], "the false positive is gone"
    # What the route now answers, and what the graph payload has always answered. They must be the
    # same fact asked of the same rows.
    assert repository.capture_has_person_regions(capture_id=capture_id) is True
    assert review_states_for_captures(
        repository.connection, repository.workspace_id, [capture_id]
    ) == {str(capture_id): "screened"}
