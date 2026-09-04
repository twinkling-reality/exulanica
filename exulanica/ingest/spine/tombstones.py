"""What the user asked to have gone, and whether a write is covered by it.

This module owns ``_multirange``, the adapter from a sequence of half-open nanosecond intervals
to the ``int8multirange`` the schema stores, and ``occurrences`` imports it from here. Three
choices, each of which had a plausible alternative:

*   **Not a module of its own.** A file whose whole content is a two-line driver adapter that
    two siblings both need is a helpers module wearing a domain-sounding name.
*   **Here rather than in ``occurrences``.** ``tombstone.interval_ns`` is the one column in this
    data layer whose entire content *is* an interval set: an interval redaction is nothing but a
    statement about a range of time, while ``occurrence.presence`` is, in migration 0001's own
    words, a "union of span intervals".
*   **Shared rather than written out twice.** The ``[)`` bound is not a style choice. Migration
    0001 line 925 matches ``interval_ns`` against
    ``int8multirange(int8range(p_start_ns, p_end_ns, '[)'))``, so a presence written under any
    other convention would be measured by this guard under a convention it does not use, and two
    copies of the expression are two places for that to drift.

It stays private because the rule this package holds is about its public surface: every public
function takes a :class:`~exulanica.ingest.spine.scope.WorkspaceScope` first, and a pure value
adapter that never sees a connection would be the sole exception to a rule better kept without
any.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from psycopg.types.multirange import Multirange
from psycopg.types.range import Range

from exulanica.errors import TombstonedError
from exulanica.evidence import EvidenceAddress
from exulanica.evidence.blob import BlobId
from exulanica.ingest.spine.scope import WorkspaceScope

__all__ = ["blocks", "insert", "refuse_ingest_if_tombstoned"]


def _multirange(intervals: Sequence[tuple[int, int]]) -> Multirange:
    """Half-open nanosecond intervals, as the schema's ``int8multirange``."""
    return Multirange([Range(start, end, "[)") for start, end in intervals])


def insert(
    scope: WorkspaceScope,
    *,
    scope_name: str,
    requested_by: uuid.UUID,
    capture_id: uuid.UUID | None = None,
    track_key: str | None = None,
    interval_ns: Sequence[tuple[int, int]] | None = None,
    entity_id: uuid.UUID | None = None,
    assertion_id: uuid.UUID | None = None,
    reason: str | None = None,
    blocklist_hash: bool = False,
) -> uuid.UUID:
    """Record the deletion request. ``scope_name`` is the tombstone's own scope column.

    Named ``scope_name`` rather than ``scope`` only because the first parameter of every
    function in this package is the workspace scope, and one word cannot mean both.
    """
    row = scope.connection.execute(
        "insert into tombstone (workspace_id, scope, capture_id, track_key, interval_ns, "
        "entity_id, assertion_id, blocklist_hash, requested_by, reason) "
        "values (%s, %s, %s, %s, %s::int8multirange, %s, %s, %s, %s, %s) "
        "returning tombstone_id",
        (
            scope.workspace_id,
            scope_name,
            capture_id,
            track_key,
            _multirange(interval_ns) if interval_ns else None,
            entity_id,
            assertion_id,
            blocklist_hash,
            requested_by,
            reason,
        ),
    ).fetchone()
    assert row is not None
    return row["tombstone_id"]


def blocks(
    scope: WorkspaceScope,
    blob_id: BlobId,
    track_key: str,
    t_start_ns: int,
    t_end_ns: int,
    *,
    assume_live_capture: bool = False,
) -> bool:
    """Ask the database the question its own write guards ask.

    ``tombstone_blocks_span`` is the function the ``before insert`` triggers call, so this cannot
    disagree with what the database will do; there is one implementation of the rule and it is in
    SQL.

    ``assume_live_capture`` selects the admission variant, ``tombstone_admits_new_capture``,
    which answers the question an ingest has to ask *before* it writes anything: "given that I am
    about to register a live capture for these bytes, will the span write be refused?" Without it
    the answer would be a false yes for every deliberate re-import, because at that instant no
    live capture exists yet.
    """
    function = (
        "not tombstone_admits_new_capture" if assume_live_capture else "tombstone_blocks_span"
    )
    row = scope.connection.execute(
        f"select {function}(%s, %s, %s, %s, %s) as blocked",
        (scope.workspace_id, blob_id.digest, track_key, t_start_ns, t_end_ns),
    ).fetchone()
    assert row is not None
    return bool(row["blocked"])


def refuse_ingest_if_tombstoned(scope: WorkspaceScope, address: EvidenceAddress) -> None:
    """The admission check an ingest runs **before it writes a single byte anywhere**.

    The object store is not in the database transaction, so a refusal discovered on the way out
    is not a refusal: the rows roll back and the bytes stay. Purged content would be resurrected
    by the very import that was correctly cancelled. The only ordering that makes the guarantee
    true is to ask first and write nothing until the answer is no.

    It asks the same question the ``before insert`` trigger on ``evidence_span`` will ask later,
    under the assumption this ingest will register a live capture for these bytes, which it will.
    The two therefore agree: this never refuses an import the trigger would have allowed, and
    never allows one it would have refused. The trigger is not redundant, because a tombstone may
    be committed in between; it is the one that closes the race, and this one is what keeps the
    store clean in the overwhelmingly common case where there is no race at all.
    """
    if blocks(
        scope,
        address.blob_id,
        address.track_key,
        address.interval.start_ns,
        address.interval.end_ns,
        assume_live_capture=True,
    ):
        raise TombstonedError(
            f"a committed tombstone covers {address.blob_id.ni_uri} "
            f"{address.track_key} {address.interval}. This is terminal: the job is "
            "cancelled, not retried."
        )
