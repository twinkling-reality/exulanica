"""Which of a workspace's photographs its account holder reviewed and may use in a world.

One rule, read by every writer that puts a personal photograph into a world: attaching a
reference to a saved world, adding one back after a new review, and composing the personal-source
world's topology (:mod:`exulanica.world.personal_composition`). A photograph qualifies when all
of these hold at the moment of the read:

- the capture is live: not deleted, and no tombstone blocks it or its original-image span;
- it has an exact original-image evidence span over the capture's own bytes;
- it has a personal reconstruction authorization over those bytes, granted by the person asking;
- that authorization has a human privacy review that found it eligible and names its reviewer;
- ``privacy_screening_allows_capture`` still allows it, which is where expiry is decided;
- the viewer bytes that review allows a person to see are in the store.

The last condition is reported rather than filtered (:attr:`ReviewedSource.viewer_available`),
because an attach names the photograph it asked for and says which of the two failed.

A made world reads the same rule the other way round (:func:`lapsed_personal_captures`): a
photograph that was authorized as personal and that the rule no longer admits, for anyone in the
workspace, is not drawn in a world, however it came to be one of the world's source slots.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import psycopg

from exulanica.epistemics.source_images import selected_image
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore

__all__ = ["ReviewedSource", "lapsed_personal_captures", "reviewed_personal_sources"]


@dataclass(frozen=True, slots=True)
class ReviewedSource:
    """One photograph the rule admits, with the newest review and authorization that admit it."""

    capture_id: uuid.UUID
    evidence_span_id: uuid.UUID
    source_sha256: bytes
    authorization_id: uuid.UUID
    screening_id: uuid.UUID
    authorized_at: dt.datetime
    screened_at: dt.datetime
    #: Whether the bytes the review lets a person see are present in the store now.
    viewer_available: bool


# The newest review first, then the newest authorization, so a renewed review is the one pinned.
_READ = (
    "select distinct on (c.capture_id) c.capture_id,s.span_id as evidence_span_id,"
    "c.blob_sha256 as source_sha256,a.authorization_id,p.screening_id,"
    "a.authorized_at,p.screened_at,statement_timestamp() as evaluated_at "
    "from capture c join evidence_span s on s.workspace_id=c.workspace_id "
    "and s.blob_sha256=c.blob_sha256 "
    "and s.modality='still_image' and s.track_key='img' "
    "and s.t_start_ns=0 and s.t_end_ns=1 and s.region is null and s.text_anchor is null "
    "join blob b on b.blob_sha256=c.blob_sha256 and b.media_type like 'image/%%' "
    "join capture_reconstruction_authorization a on a.workspace_id=c.workspace_id "
    "and a.capture_id=c.capture_id and a.source_sha256=c.blob_sha256 "
    "and a.corpus_class='personal' "
    "and (%(reviewed_for)s::uuid is null or a.authorized_by=%(reviewed_for)s::uuid) "
    "join reconstruction_privacy_screening p on p.workspace_id=c.workspace_id "
    "and p.authorization_id=a.authorization_id and p.capture_id=c.capture_id "
    "and p.source_sha256=c.blob_sha256 and p.screening_method='human_review' "
    "and p.eligibility_state='eligible' and p.reviewed_by is not null "
    "where c.workspace_id=%(workspace)s and c.deleted_at is null "
    "and (%(captures)s::uuid[] is null or c.capture_id=any(%(captures)s::uuid[])) "
    "and (%(span)s::uuid is null or s.span_id=%(span)s::uuid) "
    "and not tombstone_blocks_capture(c.workspace_id,c.capture_id) "
    "and not tombstone_blocks_span(c.workspace_id,s.blob_sha256,s.track_key,"
    "s.t_start_ns,s.t_end_ns) "
    "and privacy_screening_allows_capture(c.workspace_id,c.capture_id,p.screening_id) "
    "order by c.capture_id,p.screened_at desc,p.screening_id,a.authorized_at desc,"
    "a.authorization_id,s.span_id"
)


def reviewed_personal_sources(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    reviewed_for: uuid.UUID | None,
    store: ContentAddressedStore | None,
    capture_id: uuid.UUID | None = None,
    capture_ids: Sequence[uuid.UUID] | None = None,
    evidence_span_id: uuid.UUID | None = None,
) -> tuple[ReviewedSource, ...]:
    """Every photograph the rule admits for ``reviewed_for``, oldest capture id first.

    ``reviewed_for`` is the account holder whose authorization and review count; ``None`` counts
    anyone's in the workspace, which is how a world asks whether a photograph may still be drawn.

    ``capture_id`` and ``evidence_span_id`` narrow the read to one exact photograph and span, which
    is how an attach asks about the one it names; ``capture_ids`` narrows it to the photographs a
    world's slots hold. With no store, no viewer bytes are available, so none is looked for.
    """
    if capture_id is not None and capture_ids is not None:
        raise TypeError("narrow the read by capture_id or by capture_ids, not both")
    captures = [capture_id] if capture_id is not None else capture_ids
    rows = connection.execute(
        _READ,
        {
            "reviewed_for": reviewed_for,
            "workspace": workspace_id,
            "captures": list(captures) if captures is not None else None,
            "span": evidence_span_id,
        },
    ).fetchall()
    found = []
    for row in rows:
        source_sha256 = bytes(row["source_sha256"])
        selected = (
            selected_image(connection, workspace_id, source_sha256, row["evaluated_at"])
            if store is not None
            else None
        )
        found.append(
            ReviewedSource(
                capture_id=row["capture_id"],
                evidence_span_id=row["evidence_span_id"],
                source_sha256=source_sha256,
                authorization_id=row["authorization_id"],
                screening_id=row["screening_id"],
                authorized_at=row["authorized_at"],
                screened_at=row["screened_at"],
                viewer_available=(
                    selected is not None
                    and store is not None
                    and store.exists(BlobId(selected.sha256))
                ),
            )
        )
    return tuple(found)


def lapsed_personal_captures(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    capture_ids: Sequence[uuid.UUID],
) -> frozenset[uuid.UUID]:
    """Of ``capture_ids``, those authorized as personal that the rule no longer admits.

    A personal authorization, once granted, makes the photograph one this rule governs; after
    that it is drawn in a world only while the rule admits it, whether its review expired, its
    authorization ended or a changed privacy input made the review stale. A renewed review admits
    it again. Viewer bytes are not asked about here: a missing viewer is its own, separate reason.
    """
    if not capture_ids:
        return frozenset()
    personal = {
        row["capture_id"]
        for row in connection.execute(
            "select distinct capture_id from capture_reconstruction_authorization "
            "where workspace_id=%s and corpus_class='personal' and capture_id=any(%s)",
            (workspace_id, list(capture_ids)),
        ).fetchall()
    }
    if not personal:
        return frozenset()
    admitted = {
        source.capture_id
        for source in reviewed_personal_sources(
            connection, workspace_id, reviewed_for=None, store=None, capture_ids=sorted(personal)
        )
    }
    return frozenset(personal - admitted)
