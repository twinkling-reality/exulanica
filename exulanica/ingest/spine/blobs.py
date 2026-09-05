"""The registry of exact bytes, and the lock that keeps an ingest out of a purge.

``blob`` is keyed on the content hash and has no ``workspace_id``: the same photograph imported
by two people is one row and one stored object. That is what makes the lock below necessary
rather than tidy, because it is also what makes a purge for one workspace destroy bytes another
is using.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from exulanica.evidence.blob import BlobId
from exulanica.ingest.spine.scope import WorkspaceScope

__all__ = ["lock_stored_object", "locked_stored_objects", "upsert"]


def lock_stored_object(scope: WorkspaceScope, blob_id: BlobId) -> None:
    """Take the transaction lock over one stored object, keyed on its content hash.

    The same lock ``exulanica.deletion`` takes before it asks whether an object may be destroyed
    and then destroys it. Both sides have to take it or neither is serialised: with only the
    purger taking it, a purger and an ingest can interleave so that the ingest commits a live
    capture for bytes the purger is in the middle of removing, and under content addressing that
    ingest writes nothing to the store because the object was already there. Measured; migration
    0015's sibling comment in ``orimera/ingest/stages/intake.py`` has the observed sequence.

    Named for what it locks rather than for who else takes it. The SQL function is called
    ``purge_lock_object`` because the purger is where it was first needed; renaming a shipped
    function would be a migration for a word.
    """
    scope.connection.execute("select purge_lock_object(%s)", (blob_id.hex,))


@contextmanager
def locked_stored_objects(
    scope: WorkspaceScope, blob_ids: Sequence[BlobId]
) -> Iterator[None]:
    """Hold session locks across row commit, byte flush, and final publication.

    The purger takes the transaction-scoped version of the same advisory keys. Session locks are
    required here because committed object writes intentionally happen after the row transaction.
    Sorting prevents two scene workers from deadlocking when they share receipt bytes.
    """
    refs = sorted({blob_id.hex for blob_id in blob_ids})
    held: list[str] = []
    try:
        for ref in refs:
            scope.connection.execute(
                "select pg_advisory_lock(hashtextextended(%s, 0))", (ref,)
            )
            held.append(ref)
        yield
    finally:
        for ref in reversed(held):
            row = scope.connection.execute(
                "select pg_advisory_unlock(hashtextextended(%s, 0)) as unlocked", (ref,)
            ).fetchone()
            if row is None or row["unlocked"] is not True:
                raise RuntimeError("a stored-object advisory lock was not held")


def upsert(
    scope: WorkspaceScope, blob_id: BlobId, *, byte_size: int, media_type: str, storage_key: str
) -> bool:
    """Register or restore bytes. Returns True for a new row or a purged row made live."""
    cursor = scope.connection.execute(
        "insert into blob (blob_sha256, byte_size, media_type, storage_key) "
        "values (%s, %s, %s, %s) on conflict (blob_sha256) do update set "
        "byte_size=excluded.byte_size,media_type=excluded.media_type,"
        "storage_key=excluded.storage_key,purged_at=null "
        "where blob.purged_at is not null",
        (blob_id.digest, byte_size, media_type, storage_key),
    )
    return cursor.rowcount > 0
