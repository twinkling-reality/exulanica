"""The two stages, at the points where a mistake would reveal somebody.

Both stages are mostly plumbing over parts tested elsewhere. What is tested here is the handful of
decisions that are theirs alone, and every one of them is a place where the safe answer and the
convenient answer differ:

*   A detection is read from the schema that produced it, not re-parsed by hand, so the clamping
    the vision module already documents cannot drift.
*   A person with no usable box is counted as unlocated rather than skipped, and an unlocated
    person masks the whole photograph.
*   A region whose state nobody recorded is masked. A dictionary lookup that fell through to
    "not masked" would reveal exactly the person nobody had decided about.
*   A photograph where everybody consented produces no derivative at all, so reconstruction reads
    the original and the store does not fill with re-encoded copies.
*   An unlocated person keeps a region key of their own. The identity key buckets on the centre
    of a bounding box, and the centre of the whole frame is a body standing centre-frame, so
    these two collided into one row and the whole-frame mask was the one lost.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.consent.regions import DetectedPerson, Silhouette, region_key
from exulanica.consent.states import ResolvedPresentation
from exulanica.evidence.blob import BlobId
from exulanica.evidence.region import DisplayGeometry, Rect
from exulanica.identity.keys import region_bucket
from exulanica.ingest.person_detectors import StubRegionDetector, whole_image_silhouette
from exulanica.ingest.person_state import region_state_for_capture
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.privacy import authorize_synthetic_capture, record_synthetic_exemption
from exulanica.ingest.stages import stage
from exulanica.ingest.stages.masked_source import hidden_outlines
from exulanica.ingest.stages.person_regions import located_people, unlocated_people
from exulanica.reconstruction.testing import FlatDepthModel
from exulanica.store.local import LocalContentAddressedStore

from conftest import iso, write_photo

KEY_A = b"\xaa" * 32
KEY_B = b"\xbb" * 32
OUTLINE_A = Silhouette.from_rect(Rect.from_normalised(0.1, 0.1, 0.2, 0.2))
OUTLINE_B = Silhouette.from_rect(Rect.from_normalised(0.6, 0.6, 0.2, 0.2))


def _document(objects):
    return {
        "observation": {
            "scene_description": "a room",
            "objects": objects,
            "legible_text": [],
            "proposed_place": None,
        }
    }


def _person(box, label="person", confidence="high"):
    entry = {"label": label, "salience": "primary", "confidence": confidence}
    entry["box"] = box
    return entry


def test_a_located_person_becomes_a_clamped_box():
    found = located_people(_document([_person({"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4})]))
    assert len(found) == 1
    assert (found[0].x, found[0].y, found[0].w, found[0].h) == (0.1, 0.2, 0.3, 0.4)
    assert found[0].confidence == "high"
    # A version 1 observation says only that somebody is there, so the trace is a whole body.
    assert found[0].part == "full_body"


def test_a_box_running_off_the_frame_is_clamped_rather_than_refused():
    """Models routinely emit 1.02 for an edge; refusing would unmask the person."""
    found = located_people(_document([_person({"x": 0.8, "y": 0.8, "w": 0.5, "h": 0.5})]))
    assert len(found) == 1
    assert found[0].x + found[0].w <= 1.0
    assert found[0].y + found[0].h <= 1.0


def test_a_person_with_no_box_is_counted_as_unlocated():
    document = _document([_person(None)])
    assert located_people(document) == []
    assert unlocated_people(document) == 1


def test_a_degenerate_box_is_unlocated_rather_than_a_zero_area_mask():
    """Masking an empty rectangle would leave the person beside it visible."""
    document = _document([_person({"x": 0.5, "y": 0.5, "w": 0.0, "h": 0.0})])
    assert located_people(document) == []
    assert unlocated_people(document) == 1


def test_a_non_person_object_is_not_a_person():
    document = _document([_person({"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, label="bicycle")])
    assert located_people(document) == []
    assert unlocated_people(document) == 0


def test_several_person_labels_all_count_as_people():
    document = _document(
        [
            _person({"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}, label="woman"),
            _person({"x": 0.3, "y": 0.1, "w": 0.1, "h": 0.1}, label="man"),
        ]
    )
    assert len(located_people(document)) == 2


def test_a_region_with_no_resolved_state_is_masked():
    """Default deny at the one place a lookup miss would reveal somebody."""
    assert hidden_outlines({KEY_A: OUTLINE_A}, {}) == (OUTLINE_A,)


def test_a_shown_person_is_not_masked():
    resolved = {KEY_A: ResolvedPresentation("shown", False)}
    assert hidden_outlines({KEY_A: OUTLINE_A}, resolved) == ()


def test_a_temporarily_hidden_person_is_not_masked_in_the_derivative():
    resolved = {KEY_A: ResolvedPresentation("hidden", False)}
    assert hidden_outlines({KEY_A: OUTLINE_A}, resolved) == ()


@pytest.mark.parametrize("state", ["unknown", "present", "withdrawn"])
def test_every_unconsented_state_is_masked(state):
    resolved = {KEY_A: ResolvedPresentation(state, False)}
    assert hidden_outlines({KEY_A: OUTLINE_A}, resolved) == (OUTLINE_A,)


def test_one_hidden_person_beside_one_shown_person_masks_only_the_hidden_one():
    resolved = {
        KEY_A: ResolvedPresentation("shown", False),
        KEY_B: ResolvedPresentation("present", False),
    }
    assert hidden_outlines({KEY_A: OUTLINE_A, KEY_B: OUTLINE_B}, resolved) == (OUTLINE_B,)


def test_outlines_are_ordered_by_region_key_not_by_dictionary_order():
    regions = {KEY_B: OUTLINE_B, KEY_A: OUTLINE_A}
    assert hidden_outlines(regions, {}) == (OUTLINE_A, OUTLINE_B)


def test_the_region_stage_declares_a_detector_contract_rather_than_one_detector():
    """A single pinned name refused every detector but one, including this suite's own doubles.

    The property that matters is that swapping a detector regenerates rather than silently reusing
    the previous regions, and that lives in the stage's input digest, per photograph. See
    ``test_a_different_detector_produces_a_different_key``.
    """
    spec = stage("person_regions")
    assert spec.params["detector_contract"] == "exulanica.person-detector/v1"
    assert "detector" not in spec.params
    assert spec.model_role is None
    assert spec.deterministic is True


def test_a_different_detector_produces_a_different_key():
    """Swapping a detector must not reuse the regions the previous one proposed."""
    from exulanica.canonical import sha256_digest
    from exulanica.ingest.stages import input_digest_of

    upstream = b"\x01" * 32
    first = input_digest_of([upstream, sha256_digest(b"recorded-vision-observation/v1")])
    second = input_digest_of([upstream, sha256_digest(b"a-future-segmenter/v1")])
    assert first != second


def test_the_region_stage_declares_that_it_stores_no_template():
    assert stage("person_regions").params["biometric_template"] == "never"
    assert stage("person_regions").params["scope"] == "whole-silhouette-not-face"


def test_an_unlocated_person_masks_the_whole_image_by_policy():
    assert stage("person_regions").params["unlocated_person_policy"] == "mask-whole-image"


def test_the_masked_stage_declares_a_neutral_non_generative_fill():
    spec = stage("masked_source")
    assert spec.params["fill"] == "neutral-flat"
    assert spec.params["fill_srgb"] == [128, 128, 128]
    assert spec.deterministic is True
    assert spec.model_role is None


def test_the_masked_stage_grows_the_mask_before_filling():
    assert stage("masked_source").params["dilation_millionths"] > 0


# -- an unlocated person must not be swallowed by a located one ---------------------------


CENTRED_BOX = Silhouette.from_rect(Rect.from_normalised(0.4, 0.4, 0.2, 0.2))


def _ingest_two_people(repository, photo_dir, tmp_path, detections):
    """One synthetic photograph through the real pipeline, carrying these detections."""
    actor = uuid.UUID("a244f9d0-9bd9-5f55-a133-2712cd05d720")
    write_photo(photo_dir, "a.jpg", when=iso(10), gps=(64.3271, -20.1199))
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(
        repository,
        store,
        vision=None,
        depth=FlatDepthModel(),
        detector=StubRegionDetector(detections),
    )
    intake = pipeline.ingest_intake((photo_dir / "a.jpg").read_bytes(), filename="a.jpg")
    assert intake.capture_id is not None, intake.error
    authorization = authorize_synthetic_capture(
        repository,
        capture_id=intake.capture_id,
        actor=actor,
        generator_manifest={
            "profile": "exulanica.person-masking-test/v1",
            "notice": "SYNTHETIC TEST FIXTURE",
        },
        authorization_scope={"purpose": "unlocated person region collision test"},
    )
    screening = record_synthetic_exemption(
        repository, authorization_id=authorization.authorization_id
    )
    outcome = pipeline.ingest_derivatives(
        intake.capture_id, privacy_screening_id=screening.screening_id
    )
    assert outcome.error is None, outcome.error
    return intake.capture_id


def test_a_whole_frame_region_does_not_key_to_the_centre_cell():
    """The collision itself, in two lines and no database.

    ``region_bucket`` buckets on the centre. A whole-frame outline's bounding box is
    (0, 0, 1000000, 1000000) and its centre is (500000, 500000); a box at (0.4, 0.4, 0.2, 0.2)
    has the same centre. Both land in grid cell 8:8, so before ``located`` existed these two
    produced the identical 32 bytes.
    """
    blob = BlobId(b"\x11" * 32)
    display = DisplayGeometry(w=4000, h=3000)
    whole = whole_image_silhouette()
    assert region_bucket(whole.bounding_rect()) == region_bucket(CENTRED_BOX.bounding_rect())
    assert region_key(blob, whole, display, located=False) != region_key(blob, CENTRED_BOX, display)
    # And a located whole-frame body is still keyed as the body it is, not as an absence.
    assert region_key(blob, whole, display) == region_key(blob, whole, display, located=True)


def test_two_unlocated_people_share_one_whole_frame_region():
    """Deliberate, and pinned so nobody later "fixes" it into two fabricated identities.

    Two people the observation named without saying where are indistinguishable: they mask the
    same pixels and no recorded fact separates them. Minting a second key would invent a second
    person for a reviewer to decide about. The count survives as the artifact's
    ``unlocated_people`` field, which is where it belongs.
    """
    blob = BlobId(b"\x11" * 32)
    display = DisplayGeometry(w=4000, h=3000)
    first = region_key(blob, whole_image_silhouette(), display, located=False)
    second = region_key(blob, whole_image_silhouette(), display, located=False)
    assert first == second


def test_an_unlocated_person_is_not_swallowed_by_a_centred_located_one(
    repository, photo_dir, tmp_path
):
    """The live hole, through the real pipeline: a person who was masked nowhere.

    MEASURED 2026-09-07 against this database before the fix: one ``person_region`` row, one
    masked outline, both the centred box, and the whole frame not masked at all. The whole-frame
    region lost because a detector reports located people first, so the located key was inserted
    first and the unlocated one was read as an already-edited region and skipped.

    Real PostgreSQL, real migrations through 0037, real on-disk store, real ingest pipeline, real
    consent fold. Not real: the detections are handed in rather than found, depth is flat, and no
    vision model, COLMAP, CUDA or gsplat runs anywhere near this.
    """
    detections = (
        DetectedPerson(CENTRED_BOX, "box", "high", "fixed-region-double", part="full_body"),
        DetectedPerson(
            whole_image_silhouette(),
            "box",
            "low",
            "fixed-region-double",
            part="partial_body",
            located=False,
        ),
    )
    capture_id = _ingest_two_people(repository, photo_dir, tmp_path, detections)
    rows = repository.current_person_regions(capture_ids=[capture_id])[capture_id]
    assert len(rows) == 2, "both regions must survive the distinct-on view"
    state = region_state_for_capture(repository, capture_id)
    masked = hidden_outlines(state.outlines, state.resolved)
    assert len(masked) == 2
    assert whole_image_silhouette() in masked
    assert CENTRED_BOX in masked
