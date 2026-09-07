"""What a reviewer does to a person region, and what a person's decision is recorded as.

The design note replaces one free-text sentence ("there are no visible people") with a confirmed
region list and a state per person. This module is the writing half of that: it turns a reviewer's
edits and a consent decision into the immutable receipts migration 0037 stores, and it refuses
anything it cannot record honestly.

**The actor is never taken from the request.** Every function here takes the authenticated actor
and writes it into the receipt. A body that could name its own actor would let the owner record a
decision as though the photographed person had made it, which is the difference between consent
and a note saying consent was given.

**``actor_role`` is likewise not a parameter a caller chooses.** These functions record ``owner``,
because the only credential this system has is the account holder's. The column admits
``subject`` so that a genuine subject-facing route can be added later without a schema change, and
nothing here may write that value: a receipt claiming to be the subject's own decision, written by
the owner's token, would be worse than no receipt at all. Until that route exists the design note's
own word for this layer is theater, and lying about the actor is how theater becomes fraud.

**A detection is not an edit.** ``confirm``, ``add`` and ``delete`` all name the human who made
them. The ``detected`` action belongs to the stage and cannot be written here.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Final

from exulanica.consent.regions import Silhouette
from exulanica.consent.states import CONSENT_SCOPES
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest.person_receipts import consent_receipt, region_edit_receipt
from exulanica.ingest.person_state import region_state_for_capture
from exulanica.ingest.repository import IngestRepository

__all__ = [
    "REVIEW_ACTIONS",
    "create_subject",
    "record_consent",
    "record_region_edits",
    "review_list",
]

#: What a human may do to a region. ``detected`` is deliberately absent: it is what a detector
#: proposed, and a reviewer confirming it writes ``confirmed`` rather than rewriting the proposal.
REVIEW_ACTIONS: Final[frozenset[str]] = frozenset({"confirm", "add", "delete"})

_ACTION_TO_RECORD: Final[dict[str, str]] = {
    "confirm": "confirmed",
    "add": "added",
    "delete": "deleted",
}


def _live_capture(repository: IngestRepository, capture_id: uuid.UUID) -> Any:
    capture = repository.capture(capture_id)
    if capture is None or capture.deleted_at is not None:
        # Checked before anything is written. Without it a foreign or deleted capture reaches a
        # foreign-key violation on write and an empty list on read, and an empty list is
        # indistinguishable from a real photograph nobody has screened.
        raise PrivacyAdmissionError(f"capture {capture_id} is absent or deleted")
    return capture


def review_list(repository: IngestRepository, capture_id: uuid.UUID) -> list[dict[str, Any]]:
    """Every live region on one photograph, with the state that holds for each right now.

    This is what a reviewer is shown. It carries the detector's own confidence and whether a
    human has confirmed the region, because "a model proposed this" and "somebody agreed" are
    different claims and a review screen that blurred them would collect agreement to the wrong
    thing.
    """
    _live_capture(repository, capture_id)
    rows = repository.current_person_regions(capture_ids=[capture_id]).get(capture_id, [])
    state = region_state_for_capture(repository, capture_id)
    return [
        {
            "region_key": row.region_key.hex(),
            "action": row.action,
            "shape": row.shape,
            "part": row.part,
            "silhouette": row.silhouette,
            "detector_id": row.detector_id,
            "confidence": row.confidence,
            "confirmed_by": str(row.confirmed_by) if row.confirmed_by else None,
            "subject_id": str(row.subject_id) if row.subject_id else None,
            "state": state.resolved[row.region_key].state,
            "masked": state.resolved[row.region_key].masked,
            "name_permitted": state.resolved[row.region_key].name_permitted,
        }
        for row in rows
    ]


def create_subject(
    repository: IngestRepository, *, actor: uuid.UUID, entity_id: uuid.UUID | None = None
) -> uuid.UUID:
    """Create somebody a decision can be about.

    ``entity_id`` stays null for a person nobody has named, which is the ordinary case and the one
    the old gate could not express. Linking to an entity is how naming reaches an actual name, and
    that link is a human act like every other one here.
    """
    subject_id = uuid.uuid4()
    repository.insert_person_subject(subject_id=subject_id, entity_id=entity_id, created_by=actor)
    return subject_id


def record_region_edits(
    repository: IngestRepository,
    *,
    capture_id: uuid.UUID,
    actor: uuid.UUID,
    edits: list[dict[str, Any]],
    recorded_at: dt.datetime | None = None,
) -> list[str]:
    """Apply a reviewer's confirmations, additions and deletions, each as its own receipt."""
    capture = _live_capture(repository, capture_id)
    when = recorded_at or dt.datetime.now(dt.UTC)
    written: list[str] = []
    for edit in edits:
        action = str(edit.get("action", ""))
        if action not in REVIEW_ACTIONS:
            raise PrivacyAdmissionError(f"{action!r} is not one of {sorted(REVIEW_ACTIONS)}")
        try:
            key = bytes.fromhex(str(edit["region_key"]))
        except (KeyError, ValueError) as exc:
            raise PrivacyAdmissionError("a region edit needs a hexadecimal region key") from exc
        if len(key) != 32:
            raise PrivacyAdmissionError("a region key is 32 bytes")
        outline = _outline_for(repository, capture_id, key, edit)
        subject_id = edit.get("subject_id")
        sequence = repository.next_person_region_sequence(capture_id=capture_id, region_key=key)
        if action != "add" and sequence == 0:
            raise PrivacyAdmissionError(
                f"region {key.hex()} has no proposal to {action}; add it explicitly instead"
            )
        edit_id, record, canonical, digest = region_edit_receipt(
            workspace_id=repository.workspace_id,
            capture_id=capture_id,
            source_sha256=capture.blob_id.hex,
            region_key=key,
            sequence=sequence,
            action=_ACTION_TO_RECORD[action],
            shape=str(edit.get("shape", "polygon")),
            # A human drawing a region is under no obligation to classify it.
            part=None,
            silhouette=outline,
            subject_id=uuid.UUID(str(subject_id)) if subject_id else None,
            actor=actor,
            detector_id=None,
            confidence=None,
            recorded_at=when,
        )
        repository.insert_person_region_edit(
            region_edit_id=edit_id,
            capture_id=capture_id,
            source_sha256=capture.blob_id,
            region_key=key,
            sequence=sequence,
            action=_ACTION_TO_RECORD[action],
            shape=str(edit.get("shape", "polygon")),
            part=None,
            silhouette=outline.as_digest_input(),
            subject_id=uuid.UUID(str(subject_id)) if subject_id else None,
            detector_id=None,
            confidence=None,
            confirmed_by=actor,
            recorded_at=when,
            region_record=record,
            region_canonical=canonical,
            region_digest=digest,
        )
        written.append(edit_id.hex)
    return written


def _outline_for(
    repository: IngestRepository,
    capture_id: uuid.UUID,
    key: bytes,
    edit: dict[str, Any],
) -> Silhouette:
    """The outline this edit applies to: the supplied one, or the one already recorded.

    A confirmation or a deletion does not have to restate the outline, and should not have to:
    making a reviewer round-trip the polygon to agree with it is how a transcription error becomes
    a mask in the wrong place.
    """
    supplied = edit.get("silhouette")
    if supplied is not None:
        try:
            return Silhouette.from_digest_input(supplied)
        except (TypeError, ValueError) as exc:
            raise PrivacyAdmissionError(f"the supplied outline is not usable: {exc}") from exc
    for row in repository.current_person_regions(capture_ids=[capture_id]).get(capture_id, []):
        if row.region_key == key:
            return Silhouette.from_digest_input(row.silhouette)
    raise PrivacyAdmissionError(
        f"region {key.hex()} is not recorded on this photograph, so an outline must be supplied"
    )


def record_consent(
    repository: IngestRepository,
    *,
    subject_id: uuid.UUID,
    actor: uuid.UUID,
    consent_scope: str,
    decision: str,
    region_key: bytes | None = None,
    valid_until: dt.datetime | None = None,
    effective_at: dt.datetime | None = None,
) -> uuid.UUID:
    """Record one consent transition as the account holder.

    ``actor_role`` is fixed at ``owner`` here and is not a parameter. See the module docstring:
    the only credential this system has is the account holder's, and a receipt that claimed to be
    the photographed person's own decision would be a false statement about who agreed.
    """
    if consent_scope not in CONSENT_SCOPES:
        raise PrivacyAdmissionError(f"{consent_scope!r} is not one of {sorted(CONSENT_SCOPES)}")
    sequence = repository.next_person_consent_sequence(
        subject_id=subject_id, consent_scope=consent_scope, region_key=region_key
    )
    try:
        consent_id, record, canonical, digest = consent_receipt(
            workspace_id=repository.workspace_id,
            subject_id=subject_id,
            region_key=region_key,
            consent_scope=consent_scope,
            decision=decision,
            sequence=sequence,
            actor=actor,
            actor_role="owner",
            effective_at=effective_at or dt.datetime.now(dt.UTC),
            valid_until=valid_until,
        )
    except ValueError as exc:
        raise PrivacyAdmissionError(str(exc)) from exc
    repository.insert_person_consent(
        consent_id=consent_id,
        subject_id=subject_id,
        region_key=region_key,
        consent_scope=consent_scope,
        decision=decision,
        sequence=sequence,
        actor_id=actor,
        actor_role="owner",
        effective_at=effective_at or dt.datetime.now(dt.UTC),
        valid_until=valid_until,
        consent_record=record,
        consent_canonical=canonical,
        consent_digest=digest,
    )
    return consent_id
