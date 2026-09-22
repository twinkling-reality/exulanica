"""Attach, detach and rebind as membership events on a saved world's reference photographs.

Migration ``0090_saved_world_source_membership_events.sql`` stores the events and a pointer per
photograph naming the attachment the world currently uses. The pointer is derived: the database
moves it from the attachment and detach insert triggers, and the runtime role cannot write it.
This module holds the pure half: the ledger a world's history reads back as, the current set
that ledger implies, the checks a detach or rebind must pass before it is written, and the
digest that makes an operation identity name one exact client request.

Nothing here deletes media, rewrites a pinned authorization or screening, or composes a
photograph into a scene. A detach vacates membership; a rebind is a new membership after a new
human review.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exulanica.canonical import sha256_of_canonical

__all__ = [
    "DetachEvent",
    "MembershipEventConflict",
    "MembershipEventRefused",
    "MembershipLedger",
    "OperationKind",
    "PinnedMembership",
    "RecordedOperation",
    "current_memberships",
    "detach_request_sha256",
    "rebind_request_sha256",
    "require_detachable",
    "require_rebindable",
]

OperationKind = Literal["attach", "rebind", "detach"]


class MembershipEventConflict(Exception):
    """An operation identity already names a different request, kind or saved world."""


class MembershipEventRefused(Exception):
    """A detach or rebind was refused. ``code`` is stable; ``detail`` is for people."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class PinnedMembership:
    """One attachment row: a photograph in a world under the receipts pinned when it joined."""

    attachment_id: uuid.UUID
    operation_id: uuid.UUID
    kind: Literal["attach", "rebind"]
    capture_id: uuid.UUID
    evidence_span_id: uuid.UUID
    source_sha256: str
    authorization_id: uuid.UUID
    screening_id: uuid.UUID
    attached_entry_revision: int
    attached_by: uuid.UUID
    attached_at: dt.datetime


@dataclass(frozen=True, slots=True)
class DetachEvent:
    operation_id: uuid.UUID
    attachment_id: uuid.UUID
    capture_id: uuid.UUID
    detached_entry_revision: int
    detached_by: uuid.UUID
    detached_at: dt.datetime


@dataclass(frozen=True, slots=True)
class RecordedOperation:
    operation_id: uuid.UUID
    kind: OperationKind
    request_sha256: bytes
    base_entry_revision: int
    result_entry_revision: int


@dataclass(frozen=True, slots=True)
class MembershipLedger:
    """A saved world's complete reference history, oldest first, as its rows record it."""

    entry_id: uuid.UUID
    revision: int
    memberships: tuple[PinnedMembership, ...]
    detach_events: tuple[DetachEvent, ...]
    operations: tuple[RecordedOperation, ...]


def current_memberships(ledger: MembershipLedger) -> tuple[PinnedMembership, ...]:
    """The memberships no detach event names: which photographs the world uses now.

    Replaying the events gives the same set the stored pointer holds, and the tests compare the
    two. The pointer exists so reads and uniqueness do not replay history; this is the check.
    """

    detached = {event.attachment_id for event in ledger.detach_events}
    return tuple(member for member in ledger.memberships if member.attachment_id not in detached)


def require_detachable(
    ledger: MembershipLedger, attachment_ids: Iterable[uuid.UUID]
) -> tuple[PinnedMembership, ...]:
    """The current memberships a detach names, or a refusal naming why none may be detached.

    Detach reduces use, so it is allowed whatever the pinned receipts now say: an expired review
    or a deleted source does not keep a photograph in a world.
    """

    selected = list(attachment_ids)
    if not 1 <= len(selected) <= 200:
        raise MembershipEventRefused(
            "invalid_detach", "remove between 1 and 200 reference photographs"
        )
    if len(set(selected)) != len(selected):
        raise MembershipEventRefused(
            "invalid_detach", "each reference photograph can be removed once per request"
        )
    current = {member.attachment_id: member for member in current_memberships(ledger)}
    chosen = []
    for attachment_id in selected:
        member = current.get(attachment_id)
        if member is None:
            raise MembershipEventRefused(
                "membership_unavailable",
                "a selected reference photograph is not part of this world",
            )
        chosen.append(member)
    return tuple(chosen)


def require_rebindable(
    ledger: MembershipLedger,
    capture_id: uuid.UUID,
    *,
    authorization_id: uuid.UUID,
    screening_id: uuid.UUID,
    authorized_at: dt.datetime,
    screened_at: dt.datetime,
) -> None:
    """Refuse a rebind unless the photograph was removed and a review answers that removal.

    A review answers the removal when it was recorded after it. Without that, a review recorded
    while the photograph was still in the world would bring it back, and the person would have
    made no decision after choosing to remove it, which is what the drawer promises they do.

    Receipts any earlier membership of this photograph on this world pinned are refused as well,
    and every membership is compared rather than the newest alone: comparing the newest let an
    older membership's receipts be pinned again once a later review expired.
    """

    history = [member for member in ledger.memberships if member.capture_id == capture_id]
    if not history:
        raise MembershipEventRefused(
            "membership_unavailable",
            "this photograph was never part of this world; attach it instead",
        )
    if any(member.capture_id == capture_id for member in current_memberships(ledger)):
        raise MembershipEventRefused(
            "membership_current", "this photograph is already part of this world"
        )
    if any(
        member.authorization_id == authorization_id or member.screening_id == screening_id
        for member in history
    ):
        raise MembershipEventRefused(
            "review_required",
            "adding a photograph back needs a new human review; "
            "its current review was already used by this world",
        )
    removed_at = max(
        (event.detached_at for event in ledger.detach_events if event.capture_id == capture_id),
        default=None,
    )
    if removed_at is None:
        raise MembershipEventRefused(
            "membership_unavailable",
            "this photograph was never removed from this world",
        )
    if authorized_at <= removed_at or screened_at <= removed_at:
        raise MembershipEventRefused(
            "review_required",
            "adding a photograph back needs a human review recorded after it was removed; "
            "its current review is older than the removal",
        )


def _cursor(
    *,
    entry_id: uuid.UUID,
    operation_id: uuid.UUID,
    base_revision: int,
    authored_version_id: uuid.UUID,
    authored_state_sha256: str,
    authored_edit_seq: int,
    style_version_id: uuid.UUID,
    actor: uuid.UUID,
) -> dict[str, object]:
    return {
        "entry_id": str(entry_id),
        "operation_id": str(operation_id),
        "base_revision": base_revision,
        "authored_version_id": str(authored_version_id),
        "authored_state_sha256": authored_state_sha256,
        "authored_edit_seq": authored_edit_seq,
        "style_version_id": str(style_version_id),
        "actor": str(actor),
    }


def detach_request_sha256(
    *,
    entry_id: uuid.UUID,
    operation_id: uuid.UUID,
    base_revision: int,
    authored_version_id: uuid.UUID,
    authored_state_sha256: str,
    authored_edit_seq: int,
    style_version_id: uuid.UUID,
    attachment_ids: Iterable[uuid.UUID],
    actor: uuid.UUID,
) -> bytes:
    """The digest of exactly what the client sent, cursor included, and who sent it."""

    return sha256_of_canonical(
        {
            "kind": "detach",
            **_cursor(
                entry_id=entry_id,
                operation_id=operation_id,
                base_revision=base_revision,
                authored_version_id=authored_version_id,
                authored_state_sha256=authored_state_sha256,
                authored_edit_seq=authored_edit_seq,
                style_version_id=style_version_id,
                actor=actor,
            ),
            "selections": [{"attachment_id": str(value)} for value in attachment_ids],
        }
    )


def rebind_request_sha256(
    *,
    entry_id: uuid.UUID,
    operation_id: uuid.UUID,
    base_revision: int,
    authored_version_id: uuid.UUID,
    authored_state_sha256: str,
    authored_edit_seq: int,
    style_version_id: uuid.UUID,
    sources: Iterable[tuple[uuid.UUID, uuid.UUID]],
    actor: uuid.UUID,
) -> bytes:
    """The digest of the client's rebind body.

    The receipts the server resolves are not part of it: a retry after a newer review or after
    the pinned review expired is still the same request and returns the recorded result.
    """

    return sha256_of_canonical(
        {
            "kind": "rebind",
            **_cursor(
                entry_id=entry_id,
                operation_id=operation_id,
                base_revision=base_revision,
                authored_version_id=authored_version_id,
                authored_state_sha256=authored_state_sha256,
                authored_edit_seq=authored_edit_seq,
                style_version_id=style_version_id,
                actor=actor,
            ),
            "sources": [
                {"capture_id": str(capture_id), "evidence_span_id": str(span_id)}
                for capture_id, span_id in sources
            ],
        }
    )
