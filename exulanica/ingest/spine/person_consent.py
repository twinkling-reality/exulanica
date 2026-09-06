"""Who is in a photograph and what they agreed to, written down so nothing has to be inferred.

Three append-only tables and one view, all created by migration 0037. Every function here takes a
:class:`~exulanica.ingest.spine.scope.WorkspaceScope` first, like everything else in this package,
so no path reaches these rows without a declared workspace: the policies on all three are
``workspace_id = current_workspace()`` under FORCE row-level security, and a connection that named
no workspace sees nothing rather than seeing everybody.

**Nothing here decides anything.** These are writers and readers. Whether a person is masked is
resolved by ``person_region_is_masked`` in the database and by
:func:`exulanica.consent.states.resolve_presentation` in Python, and both read what this module
records. That separation is deliberate: a writer that also decided would be a second place for the
rule to live, and the two would drift.

**Sequence numbers are allocated inside the transaction that writes.** They are what orders a
receipt chain, and ordering by timestamp would be wrong for the reason
:mod:`exulanica.consent.states` records: two receipts in the same second are common and a
serialised timestamp does not order them stably. ``next_region_sequence`` and
``next_consent_sequence`` take the maximum under the same lock the insert runs in.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from psycopg.types.json import Jsonb

from exulanica.evidence.blob import BlobId
from exulanica.ingest.spine.scope import WorkspaceScope

__all__ = [
    "ConsentTransitionRow",
    "PersonRegionRow",
    "consent_transitions",
    "current_regions",
    "insert_consent",
    "insert_region_edit",
    "insert_subject",
    "next_consent_sequence",
    "next_region_sequence",
    "subject_for_region",
]


@dataclass(frozen=True, slots=True)
class PersonRegionRow:
    """The live state of one region: the last edit that touched its key."""

    capture_id: uuid.UUID
    region_key: bytes
    action: str
    shape: str
    silhouette: dict[str, Any]
    subject_id: uuid.UUID | None
    detector_id: str | None
    confidence: str | None
    confirmed_by: uuid.UUID | None
    region_digest: bytes


@dataclass(frozen=True, slots=True)
class ConsentTransitionRow:
    """One recorded decision, as the state resolver needs it."""

    consent_id: uuid.UUID
    subject_id: uuid.UUID
    region_key: bytes | None
    consent_scope: str
    decision: str
    sequence: int
    actor_id: uuid.UUID
    actor_role: str
    effective_at: dt.datetime
    valid_until: dt.datetime | None
    consent_digest: bytes


def insert_subject(
    scope: WorkspaceScope,
    *,
    subject_id: uuid.UUID,
    entity_id: uuid.UUID | None,
    created_by: uuid.UUID,
) -> uuid.UUID:
    """Create a person, or return the identical existing one.

    ``entity_id`` is null for somebody nobody has named, which is the ordinary case and the one
    the old yes-or-no gate could not represent: the two people at the edge of the bowl
    photographs are real, are owed a decision, and have no name.
    """
    scope.connection.execute(
        "insert into person_subject (subject_id,workspace_id,entity_id,created_by) "
        "values (%s,%s,%s,%s) on conflict (subject_id) do nothing",
        (subject_id, scope.workspace_id, entity_id, created_by),
    )
    return subject_id


def next_region_sequence(scope: WorkspaceScope, *, capture_id: uuid.UUID, region_key: bytes) -> int:
    """The next edit number for one region. Zero when nobody has touched it."""
    row = scope.connection.execute(
        "select coalesce(max(sequence) + 1, 0) as next from person_region "
        "where workspace_id=%s and capture_id=%s and region_key=%s",
        (scope.workspace_id, capture_id, region_key),
    ).fetchone()
    assert row is not None
    return int(row["next"])


def insert_region_edit(
    scope: WorkspaceScope,
    *,
    region_edit_id: uuid.UUID,
    capture_id: uuid.UUID,
    source_sha256: BlobId,
    region_key: bytes,
    sequence: int,
    action: str,
    shape: str,
    silhouette: dict[str, Any],
    subject_id: uuid.UUID | None,
    detector_id: str | None,
    confidence: str | None,
    confirmed_by: uuid.UUID | None,
    recorded_at: dt.datetime,
    region_record: dict[str, Any],
    region_canonical: bytes,
    region_digest: bytes,
) -> uuid.UUID:
    """Append one edit, or verify that the identical one is already recorded.

    The row is immutable and the table refuses UPDATE and DELETE, so a second write of the same
    receipt is either the same bytes or a disagreement worth raising. Detections come through
    here as ``action='detected'`` with no actor, which is what arms default deny: a detected
    region has no subject, ``person_region_is_masked`` returns true for a null subject, and the
    photograph requires masking from that moment until somebody decides otherwise.
    """
    scope.connection.execute(
        "insert into person_region (region_edit_id,workspace_id,capture_id,source_sha256,"
        "region_key,sequence,action,shape,silhouette,subject_id,detector_id,confidence,"
        "confirmed_by,recorded_at,region_record,region_canonical,region_digest) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "on conflict (region_edit_id) do nothing",
        (
            region_edit_id,
            scope.workspace_id,
            capture_id,
            source_sha256.digest,
            region_key,
            sequence,
            action,
            shape,
            Jsonb(silhouette),
            subject_id,
            detector_id,
            confidence,
            confirmed_by,
            recorded_at,
            Jsonb(region_record),
            region_canonical,
            region_digest,
        ),
    )
    row = scope.connection.execute(
        "select region_digest from person_region where workspace_id=%s and region_edit_id=%s",
        (scope.workspace_id, region_edit_id),
    ).fetchone()
    if row is None or bytes(row["region_digest"]) != region_digest:
        raise ValueError("an existing person region edit disagrees with this receipt")
    return region_edit_id


def current_regions(
    scope: WorkspaceScope, *, capture_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[PersonRegionRow]]:
    """Every live region on these photographs, deleted ones excluded, ordered by key.

    Ordered so that two workers reading the same corpus build the same digest; the masking stage
    hashes this set and an unordered read would move the key for no reason.
    """
    if not capture_ids:
        return {}
    rows = scope.connection.execute(
        "select capture_id,region_key,action,shape,silhouette,subject_id,detector_id,"
        "confidence,confirmed_by,region_digest from person_region_current "
        "where workspace_id=%s and capture_id=any(%s::uuid[]) and action <> 'deleted' "
        "order by capture_id,region_key",
        (scope.workspace_id, capture_ids),
    ).fetchall()
    found: dict[uuid.UUID, list[PersonRegionRow]] = {}
    for row in rows:
        found.setdefault(row["capture_id"], []).append(
            PersonRegionRow(
                capture_id=row["capture_id"],
                region_key=bytes(row["region_key"]),
                action=row["action"],
                shape=row["shape"],
                silhouette=dict(row["silhouette"]),
                subject_id=row["subject_id"],
                detector_id=row["detector_id"],
                confidence=row["confidence"],
                confirmed_by=row["confirmed_by"],
                region_digest=bytes(row["region_digest"]),
            )
        )
    return found


def subject_for_region(
    scope: WorkspaceScope, *, capture_id: uuid.UUID, region_key: bytes
) -> uuid.UUID | None:
    row = scope.connection.execute(
        "select subject_id from person_region_current "
        "where workspace_id=%s and capture_id=%s and region_key=%s",
        (scope.workspace_id, capture_id, region_key),
    ).fetchone()
    return None if row is None else row["subject_id"]


def next_consent_sequence(
    scope: WorkspaceScope, *, subject_id: uuid.UUID, consent_scope: str, region_key: bytes | None
) -> int:
    """The next number in one consent chain. Chains are per subject, scope and region."""
    row = scope.connection.execute(
        "select coalesce(max(sequence) + 1, 0) as next from person_presentation_consent "
        "where workspace_id=%s and subject_id=%s and consent_scope=%s "
        "and region_key is not distinct from %s",
        (scope.workspace_id, subject_id, consent_scope, region_key),
    ).fetchone()
    assert row is not None
    return int(row["next"])


def insert_consent(
    scope: WorkspaceScope,
    *,
    consent_id: uuid.UUID,
    subject_id: uuid.UUID,
    region_key: bytes | None,
    consent_scope: str,
    decision: str,
    sequence: int,
    actor_id: uuid.UUID,
    actor_role: str,
    effective_at: dt.datetime,
    valid_until: dt.datetime | None,
    consent_record: dict[str, Any],
    consent_canonical: bytes,
    consent_digest: bytes,
) -> uuid.UUID:
    """Append one consent transition, or verify the identical one is already recorded."""
    scope.connection.execute(
        "insert into person_presentation_consent (consent_id,workspace_id,subject_id,region_key,"
        "consent_scope,decision,sequence,actor_id,actor_role,effective_at,valid_until,"
        "consent_record,consent_canonical,consent_digest) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "on conflict (consent_id) do nothing",
        (
            consent_id,
            scope.workspace_id,
            subject_id,
            region_key,
            consent_scope,
            decision,
            sequence,
            actor_id,
            actor_role,
            effective_at,
            valid_until,
            Jsonb(consent_record),
            consent_canonical,
            consent_digest,
        ),
    )
    row = scope.connection.execute(
        "select consent_digest from person_presentation_consent "
        "where workspace_id=%s and consent_id=%s",
        (scope.workspace_id, consent_id),
    ).fetchone()
    if row is None or bytes(row["consent_digest"]) != consent_digest:
        raise ValueError("an existing consent receipt disagrees with this record")
    return consent_id


def consent_transitions(
    scope: WorkspaceScope, *, subject_id: uuid.UUID
) -> list[ConsentTransitionRow]:
    """Every recorded decision for one person, oldest first.

    The whole chain rather than the current answer, because the caller folding it is the same
    pure function an offline verifier runs over a World Memory Package. A reader that returned a
    resolved state here would be a second implementation of the rule.
    """
    rows = scope.connection.execute(
        "select consent_id,subject_id,region_key,consent_scope,decision,sequence,actor_id,"
        "actor_role,effective_at,valid_until,consent_digest from person_presentation_consent "
        "where workspace_id=%s and subject_id=%s order by consent_scope,sequence",
        (scope.workspace_id, subject_id),
    ).fetchall()
    return [
        ConsentTransitionRow(
            consent_id=row["consent_id"],
            subject_id=row["subject_id"],
            region_key=None if row["region_key"] is None else bytes(row["region_key"]),
            consent_scope=row["consent_scope"],
            decision=row["decision"],
            sequence=int(row["sequence"]),
            actor_id=row["actor_id"],
            actor_role=row["actor_role"],
            effective_at=row["effective_at"],
            valid_until=row["valid_until"],
            consent_digest=bytes(row["consent_digest"]),
        )
        for row in rows
    ]
