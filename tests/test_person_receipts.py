"""Receipts, and the digest chain that makes a consent change a new build rather than a mutation.

The design note asks for two things these pin. First, "every consent transition is an immutable
receipt with actor, time and scope", which is only true if the record refuses to be built without
them. Second, "the derivative digest enters the scene build inputs, so a later consent change
produces a new build rather than mutating one" -- which is a property of the digests below, not a
promise made in prose.

Everything here is canonical JSON of integers, strings, booleans and nulls, because a verifier
reading a World Memory Package has to reach the same state offline and a float would not survive
the trip.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from exulanica.canonical import canonical_json
from exulanica.consent.regions import DetectedPerson, Silhouette
from exulanica.consent.states import ResolvedPresentation
from exulanica.evidence.region import Rect
from exulanica.ingest.person_receipts import (
    consent_receipt,
    consent_state_digest,
    masked_source_manifest,
    person_region_list,
    region_edit_receipt,
    region_set_digest,
)

WORKSPACE = uuid.UUID("bdba4f95-07e3-4ff6-8c5b-eb8989ab63cb")
CAPTURE = uuid.UUID("d3e3db87-1fa6-5591-9981-d4247a5d6f59")
ACTOR = uuid.UUID("11111111-2222-3333-4444-555555555555")
SUBJECT = uuid.UUID("66666666-7777-8888-9999-aaaaaaaaaaaa")
SOURCE = "a" * 64
WHEN = dt.datetime(2026, 9, 5, 12, 0, tzinfo=dt.UTC)
OUTLINE = Silhouette.from_rect(Rect.from_normalised(0.2, 0.2, 0.3, 0.5))
KEY_A = b"\xaa" * 32
KEY_B = b"\xbb" * 32


def _edit(**overrides):
    fields = dict(
        workspace_id=WORKSPACE,
        capture_id=CAPTURE,
        source_sha256=SOURCE,
        region_key=KEY_A,
        sequence=1,
        action="confirmed",
        shape="box",
        silhouette=OUTLINE,
        subject_id=SUBJECT,
        actor=ACTOR,
        detector_id=None,
        confidence="high",
        recorded_at=WHEN,
    )
    fields.update(overrides)
    return region_edit_receipt(**fields)


def _consent(**overrides):
    fields = dict(
        workspace_id=WORKSPACE,
        subject_id=SUBJECT,
        region_key=None,
        consent_scope="likeness",
        decision="granted",
        sequence=1,
        actor=ACTOR,
        actor_role="owner",
        effective_at=WHEN,
    )
    fields.update(overrides)
    return consent_receipt(**fields)


def test_every_receipt_is_canonical_json_with_no_float():
    for _, record, canonical, digest in (_edit(), _consent()):
        assert canonical_json(record) == canonical
        assert len(digest) == 32


def test_a_detection_is_not_a_decision_and_may_not_name_an_actor():
    with pytest.raises(ValueError, match="not somebody's decision"):
        _edit(action="detected", actor=ACTOR)


def test_a_human_edit_must_name_the_human_who_made_it():
    with pytest.raises(ValueError, match="must name the human"):
        _edit(action="confirmed", actor=None)


def test_an_unknown_region_action_is_refused():
    with pytest.raises(ValueError, match="is not one of"):
        _edit(action="approved")


def test_a_consent_receipt_records_actor_time_and_scope():
    _, record, _, _ = _consent()
    assert record["actor_id"] == str(ACTOR)
    assert record["effective_at"] == "2026-09-05T12:00:00Z"
    assert record["consent_scope"] == "likeness"
    assert record["decision"] == "granted"


def test_a_naive_time_is_refused_so_a_receipt_cannot_be_ambiguous():
    with pytest.raises(ValueError, match="UTC offset"):
        _consent(effective_at=dt.datetime(2026, 9, 5, 12, 0))


def test_a_withdrawal_may_only_be_recorded_against_likeness():
    """Withdrawing 'naming' would leave the pixels showing."""
    with pytest.raises(ValueError, match="reaches pixels"):
        _consent(consent_scope="naming", decision="withdrawn")


def test_an_actor_role_outside_the_vocabulary_is_refused():
    with pytest.raises(ValueError, match="is not one of"):
        _consent(actor_role="reviewer")


def test_the_subject_is_a_representable_actor_even_though_no_route_writes_one():
    _, record, _, _ = _consent(actor_role="subject")
    assert record["actor_role"] == "subject"


def test_a_receipt_id_is_a_function_of_its_content():
    first, _, _, _ = _consent()
    again, _, _, _ = _consent()
    different, _, _, _ = _consent(decision="revoked")
    assert first == again
    assert first != different


def test_a_detected_region_list_confirms_nobody():
    found = DetectedPerson(OUTLINE, "box", "medium", "fixed-region-double")
    record = person_region_list(
        source_sha256=SOURCE,
        detector_id="fixed-region-double",
        stage_version=1,
        detections=[(KEY_A, found)],
        unlocated_people=0,
    )
    assert record["regions"][0]["confirmed_by"] is None


def test_a_region_list_is_ordered_by_key_not_by_discovery_order():
    """Two workers resolving in different orders must produce one digest."""
    a = DetectedPerson(OUTLINE, "box", "low", "d")
    b = DetectedPerson(
        Silhouette.from_rect(Rect.from_normalised(0.6, 0.1, 0.2, 0.2)), "box", "low", "d"
    )
    forward = person_region_list(
        source_sha256=SOURCE,
        detector_id="d",
        stage_version=1,
        detections=[(KEY_A, a), (KEY_B, b)],
        unlocated_people=0,
    )
    backward = person_region_list(
        source_sha256=SOURCE,
        detector_id="d",
        stage_version=1,
        detections=[(KEY_B, b), (KEY_A, a)],
        unlocated_people=0,
    )
    assert forward == backward


def test_the_region_set_digest_ignores_the_order_regions_were_read_in():
    other = Silhouette.from_rect(Rect.from_normalised(0.6, 0.1, 0.2, 0.2))
    assert region_set_digest(
        capture_id=CAPTURE, source_sha256=SOURCE, regions={KEY_A: OUTLINE, KEY_B: other}
    ) == region_set_digest(
        capture_id=CAPTURE, source_sha256=SOURCE, regions={KEY_B: other, KEY_A: OUTLINE}
    )


def test_a_corrected_outline_moves_the_region_set_digest():
    tighter = Silhouette.from_rect(Rect.from_normalised(0.21, 0.21, 0.28, 0.48))
    assert region_set_digest(
        capture_id=CAPTURE, source_sha256=SOURCE, regions={KEY_A: OUTLINE}
    ) != region_set_digest(capture_id=CAPTURE, source_sha256=SOURCE, regions={KEY_A: tighter})


def test_a_consent_change_moves_the_state_digest_and_therefore_the_build():
    """This is the whole 'a new build rather than mutating one' guarantee, as one assertion."""
    hidden = {KEY_A: ResolvedPresentation("unknown", False)}
    shown = {KEY_A: ResolvedPresentation("shown", False)}
    assert consent_state_digest(
        capture_id=CAPTURE, source_sha256=SOURCE, resolved=hidden
    ) != consent_state_digest(capture_id=CAPTURE, source_sha256=SOURCE, resolved=shown)


def test_granting_a_name_alone_still_moves_the_state_digest():
    """Naming does not unmask, but it changes what the world may draw, so it is a new state."""
    plain = {KEY_A: ResolvedPresentation("present", False)}
    named = {KEY_A: ResolvedPresentation("present", True)}
    assert consent_state_digest(
        capture_id=CAPTURE, source_sha256=SOURCE, resolved=plain
    ) != consent_state_digest(capture_id=CAPTURE, source_sha256=SOURCE, resolved=named)


def test_a_masked_manifest_names_which_person_each_mask_belongs_to():
    _, record, _, _ = masked_source_manifest(
        workspace_id=WORKSPACE,
        capture_id=CAPTURE,
        source_sha256=SOURCE,
        masked_sha256="b" * 64,
        stage_version=1,
        dilation_millionths=8000,
        masks=[(KEY_A, SUBJECT, "present"), (KEY_B, None, "unknown")],
    )
    assert [mask["region_key"] for mask in record["masks"]] == [KEY_A.hex(), KEY_B.hex()]
    assert record["masks"][0]["subject_id"] == str(SUBJECT)
    assert record["masks"][1]["subject_id"] is None


def test_a_masked_manifest_states_that_nothing_was_generated():
    """Masked areas are neutral, and the record says so rather than leaving it to be assumed."""
    _, record, _, _ = masked_source_manifest(
        workspace_id=WORKSPACE,
        capture_id=CAPTURE,
        source_sha256=SOURCE,
        masked_sha256="b" * 64,
        stage_version=1,
        dilation_millionths=8000,
        masks=[(KEY_A, SUBJECT, "present")],
    )
    assert record["generative_fill"] is False
    assert record["fill"] == "neutral-flat"
