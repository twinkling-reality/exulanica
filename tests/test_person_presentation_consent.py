"""Default deny, three separate consents, and an outline that survives a detector re-run.

The design note this pins is ``docs/person-presentation-consent.md``. It was written because the
old gate asked a reviewer one yes-or-no question about a whole photograph, and the reviewer of the
retained bowl collection answered "no visible people" over frames containing the arms, hands and
clothing of diners at the edge. Four failures follow from that, and each has a test here:

*   **A region nobody decided about was treated as absent.** Now it resolves to ``unknown`` and
    ``unknown`` masks, and there is no argument anywhere that starts it anywhere else.
*   **Presence, naming and likeness were one bit.** A person can be present and named for years
    without ever being visible, and collapsing that is what made the coarse answer the only
    answer available.
*   **A re-run threw the reviewer's work away.** Confirmations are keyed on the evidence, not on a
    row id, so a second detector version does not resurrect a deleted false positive.
*   **Masking after the fact is not masking.** ``MASKED_STATES`` is what the derivative stage
    reads, and the temporarily hidden state is deliberately not in it.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest
from exulanica.consent.regions import Silhouette, region_key
from exulanica.consent.states import (
    MASKED_STATES,
    ConsentTransition,
    resolve_presentation,
)
from exulanica.evidence.blob import BlobId
from exulanica.evidence.region import PPM, DisplayGeometry, Rect

DISPLAY = DisplayGeometry(w=4000, h=3000)
BLOB = BlobId(bytes(range(32)))


def _decision(scope, granted, second, digest=b"\x11" * 32):
    return ConsentTransition(
        scope=scope,
        granted=granted,
        actor="reviewer",
        decided_at=dt.datetime(2026, 9, 5, tzinfo=dt.UTC) + dt.timedelta(seconds=second),
        receipt_digest=digest,
    )


def test_a_person_region_defaults_to_hidden_without_a_consent_receipt():
    resolved = resolve_presentation(())
    assert resolved.state == "unknown"
    assert resolved.masked is True
    assert resolved.drawn is False


def test_naming_consent_alone_never_reveals_likeness():
    """The bowl case: somebody may be named and still never drawn."""
    resolved = resolve_presentation((_decision("naming", True, 1),))
    assert resolved.name_permitted is True
    assert resolved.drawn is False
    assert resolved.masked is True


def test_presence_consent_alone_never_reveals_likeness():
    resolved = resolve_presentation((_decision("presence", True, 1),))
    assert resolved.state == "present"
    assert resolved.masked is True
    assert resolved.drawn is False


def test_a_temporarily_hidden_person_keeps_their_geometry():
    """The one reversible state. Masking here would rebuild the world on every toggle."""
    granted = _decision("likeness", True, 1)
    hidden = resolve_presentation((granted, _decision("temporary_hide", True, 2)))
    assert hidden.state == "hidden"
    assert hidden.drawn is False
    assert hidden.masked is False
    assert "hidden" not in MASKED_STATES
    restored = resolve_presentation(
        (granted, _decision("temporary_hide", True, 2), _decision("temporary_hide", False, 3))
    )
    assert restored.state == "shown"


def test_a_revoked_likeness_masks_again():
    resolved = resolve_presentation(
        (_decision("likeness", True, 1), _decision("likeness", False, 2))
    )
    assert resolved.state == "unknown"
    assert resolved.masked is True


def test_a_withdrawal_is_not_undone_by_a_later_grant():
    """Withdrawal reaches forward; another actor's later receipt does not restore it."""
    resolved = resolve_presentation((_decision("likeness", True, 9),), withdrawn=True)
    assert resolved.state == "withdrawn"
    assert resolved.masked is True
    assert resolved.name_permitted is False


def test_resolution_does_not_depend_on_the_order_receipts_were_read():
    grant = _decision("likeness", True, 1, digest=b"\x01" * 32)
    revoke = _decision("likeness", False, 2, digest=b"\x02" * 32)
    assert resolve_presentation((grant, revoke)) == resolve_presentation((revoke, grant))


def test_two_receipts_at_one_instant_resolve_the_same_way_everywhere():
    """Without the digest tiebreak a package replayed elsewhere could disagree."""
    early = _decision("likeness", True, 5, digest=b"\x01" * 32)
    late = _decision("likeness", False, 5, digest=b"\x02" * 32)
    assert resolve_presentation((early, late)).state == "unknown"
    assert resolve_presentation((late, early)).state == "unknown"


def test_a_consent_receipt_needs_an_offset_aware_time():
    with pytest.raises(ValueError, match="UTC offset"):
        ConsentTransition("likeness", True, "a", dt.datetime(2026, 9, 5), b"\x00" * 32)


def test_an_unknown_consent_scope_is_refused():
    with pytest.raises(ValueError, match="is not one of"):
        _decision("appearance", True, 1)


def test_a_confirmed_region_survives_a_detector_rerun():
    """Keyed on a 16x16 bucket of the box centre, so a re-tightened outline keeps its identity."""
    first = Silhouette.from_rect(Rect.from_normalised(0.30, 0.30, 0.20, 0.40))
    tightened = Silhouette.from_rect(Rect.from_normalised(0.31, 0.32, 0.18, 0.36))
    assert region_key(BLOB, first, DISPLAY) == region_key(BLOB, tightened, DISPLAY)


def test_two_people_in_one_photograph_do_not_collapse_to_one_region():
    left = Silhouette.from_rect(Rect.from_normalised(0.05, 0.30, 0.15, 0.40))
    right = Silhouette.from_rect(Rect.from_normalised(0.70, 0.30, 0.15, 0.40))
    assert region_key(BLOB, left, DISPLAY) != region_key(BLOB, right, DISPLAY)


def test_an_outline_that_encloses_no_area_is_refused():
    with pytest.raises(ValueError, match="positive area"):
        Silhouette(((0, 0), (10_000, 0), (20_000, 0)))


def test_an_outline_of_two_points_is_refused():
    with pytest.raises(ValueError, match="at least 3 points"):
        Silhouette(((0, 0), (10_000, 10_000)))


def test_an_outline_outside_the_normalised_square_is_refused():
    with pytest.raises(ValueError, match="outside the normalised square"):
        Silhouette(((0, 0), (PPM + 1, 0), (0, PPM)))


def test_containment_is_exact_integer_arithmetic_on_a_concave_outline():
    """A chevron: the notch must be outside, which an x-intercept in floats gets wrong at edges."""
    chevron = Silhouette(
        (
            (0, 0),
            (400_000, 0),
            (200_000, 300_000),
            (400_000, 600_000),
            (0, 600_000),
        )
    )
    assert chevron.contains(50_000, 300_000) is True
    assert chevron.contains(350_000, 300_000) is False


def test_a_box_outline_says_it_is_a_box():
    """Masking a box hides more than the person; calling it a silhouette would overclaim."""
    rect = Rect.from_normalised(0.1, 0.1, 0.2, 0.3)
    outline = Silhouette.from_rect(rect)
    assert outline.as_digest_input()["kind"] == "polygon"
    assert len(outline.points) == 4
    assert outline.bounding_rect() == rect


# ---------------------------------------------------------------------------------------------
# Through the database, because the rule has two implementations and only one of them is Python.


def test_a_withdrawn_persons_name_does_not_travel_to_the_browser(repository, photo_dir, tmp_path):
    """A withdrawal outranks a naming receipt, and nothing downstream would have caught it.

    Every other test in this file resolves the rule in Python. The graph payload does not: it
    asks migration 0037 directly, and ``person_consent_is_granted`` answers only "is this one
    scope's receipt held right now". It has no withdrawal check. The database composes that
    predicate rather than widening it, and ``person_region_is_masked`` is the composition
    (``person_subject_is_withdrawn`` OR no likeness); naming never got one. So this row resolved
    to ``withdrawn`` and shipped the name in the same payload. MEASURED 2026-09-07 against
    PostgreSQL, before the fix: ``state == "withdrawn"`` and ``display_name == "Julie"``.

    No layer below catches it. ``drawsName`` in ``web/packages/graph-client`` gates on the name
    having arrived rather than on the state, on the stated grounds that the server sends a name
    only when naming was consented. ``drawsSilhouette`` excludes ``withdrawn``, so the name would
    have been the one remaining trace of a person the world otherwise omits. Nor does the name go
    stale on its own: a presentation withdrawal writes a consent receipt and never touches the
    naming assertion, so migration 0002's cache trigger does not blank ``entity.display_name``.
    """
    from exulanica.epistemics.assertions import AssertionWriter
    from exulanica.graph.entities import NAME_PREDICATE, entity_rows
    from exulanica.graph.person_regions import person_regions_for_captures
    from exulanica.identity import IdentityRepository, rename_entity
    from exulanica.ingest import person_review
    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.store.local import LocalContentAddressedStore

    from conftest import iso, write_photo

    actor = uuid.uuid4()
    write_photo(photo_dir, "a.jpg", when=iso(10))
    pipeline = PhotoIngestPipeline(
        repository, LocalContentAddressedStore(tmp_path / "blobs"), detector=None
    )
    # Intake only. No derivatives, so no depth model and no privacy screening are involved: the
    # capture exists to satisfy the person_region foreign key and nothing else.
    intake = pipeline.ingest_intake((photo_dir / "a.jpg").read_bytes(), filename="a.jpg")
    assert intake.capture_id is not None, intake.error
    blob_id = repository.capture(intake.capture_id).blob_id

    identity = IdentityRepository(repository.connection, repository.workspace_id)
    entity_id = identity.entities.create(entity_class="person")
    # Through the naming assertion, because a raw insert of display_name is refused by migration
    # 0002's tg_entity_name_is_user_stated and would prove nothing about the real path.
    rename_entity(
        identity,
        AssertionWriter(repository.connection, repository.workspace_id),
        entity_id=entity_id,
        display_name="Julie",
        actor=actor,
    )

    subject_id = person_review.create_subject(repository, actor=actor, entity_id=entity_id)
    outline = Silhouette.from_rect(Rect.from_normalised(0.2, 0.2, 0.3, 0.5))
    display = DisplayGeometry(w=160, h=100)
    key = region_key(blob_id, outline, display)
    person_review.record_region_edits(
        repository,
        capture_id=intake.capture_id,
        actor=actor,
        edits=[
            {
                "region_key": key.hex(),
                "action": "add",
                "silhouette": outline.as_digest_input(),
                "subject_id": str(subject_id),
            }
        ],
    )
    person_review.record_consent(
        repository,
        subject_id=subject_id,
        actor=actor,
        consent_scope="naming",
        decision="granted",
    )

    def payload_row():
        found = person_regions_for_captures(
            repository.connection, repository.workspace_id, [intake.capture_id]
        )
        rows = found[str(intake.capture_id)]
        assert len(rows) == 1
        return rows[0]

    # The control, so the assertion below cannot pass by the name never having travelled at all.
    # Named on a silhouette is a real state and the name is supposed to reach the browser in it.
    before = payload_row()
    assert before.state == "unknown"
    assert before.display_name == "Julie"

    person_review.record_consent(
        repository,
        subject_id=subject_id,
        actor=actor,
        consent_scope="likeness",
        decision="withdrawn",
    )

    after = payload_row()
    assert after.state == "withdrawn"
    assert after.display_name is None, "a withdrawn person's name reached the browser"
    # The invariant behind the bug: the two implementations of the presentation rule agree.
    assert person_review.review_list(repository, intake.capture_id)[0]["name_permitted"] is False

    # The SECOND surface, and clearing the region row alone does not clear it. The same
    # GraphPayload carries `entities`, and an entity row's display_name had no consent filter of
    # any kind, so the withdrawn person's name shipped beside their blanked region in one
    # response. MEASURED 2026-09-07: region display_name None, entities display_name "Julie".
    # `web/packages/graph-client/src/snapshot.ts` maps that field into the client entity model, so
    # it is drawn rather than merely present.
    named = [
        row
        for row in entity_rows(repository.connection, repository.workspace_id)
        if row.entity_id == entity_id
    ]
    assert len(named) == 1, "the entity must still be in the payload; it is the name that goes"
    entity = named[0]
    assert entity.display_name is None, (
        "a withdrawn person's name reached the browser through the entity list"
    )
    # The third surface, and the one that survives blanking the other two. The naming assertion
    # keeps its row so the ledger still shows somebody was named, and loses its value.
    naming = [row for row in entity.assertions if row.predicate_key == NAME_PREDICATE]
    assert naming, "the naming assertion must survive; a withdrawal is not an erasure of the event"
    assert all(row.object_value is None for row in naming), (
        "a withdrawn person's name reached the browser through the naming assertion"
    )
    # And the fourth, inside the rename event's own payload.
    assert entity.history, "the rename event must still be in the ledger"
    assert not any("Julie" in json.dumps(row.payload) for row in entity.history), (
        "a withdrawn person's name reached the browser inside an identity event payload"
    )
    # The whole rule in one assertion, so a fifth surface added later fails here rather than
    # shipping. Serialised exactly as the route serialises it.
    assert "Julie" not in entity.model_dump_json(), (
        "a withdrawn person's name is somewhere in their entity row"
    )


def test_the_graph_reads_the_same_naming_predicate_the_writer_writes():
    """Two spellings of one predicate would silently stop redacting a withdrawn person's name.

    ``exulanica.graph.entities`` cannot import the writer's private constant, so it carries its
    own copy and this binds them. Without it, renaming the predicate in one place leaves the
    redaction looking for a key nothing writes, and the failure is silent and revealing.
    """
    from exulanica.graph.entities import NAME_PREDICATE as read_side
    from exulanica.identity.naming import _NAME_PREDICATE as write_side

    assert read_side == write_side
