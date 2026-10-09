"""Erasing a world's society whole: every row that records it, under a tombstone.

A society's records are bound to each other by digest (a receipt's own digest, an event's id over
its document's digest, each minute's state digest carried by the next), so nothing in them can be
blanked in place: a line a person typed for a being they play, once said, is in the answer, the
receipt, the said event, the state's heard and said lines and later requests, and changing any of
them breaks every record after it. An erasure removes every row that records the society instead
(migration "a society is erased whole"): its records, its clock, its asks to outside programs and
its crossings, and the comparisons and experiments started from it; and it withdraws the
Companion's answers that cited the society's world version. A workspace's own tombstone erases
every society it holds the same way.
"""

from __future__ import annotations

import uuid
from typing import Final

import psycopg
from psycopg.rows import dict_row

from exulanica.world.workspace_lock import lock_workspace

__all__ = ["ERASURE_REASON", "SOCIETY_ERASURE_REFUSALS", "SocietyErasureRefused", "erase_society"]

#: What a society tombstone records as its reason.
ERASURE_REASON: Final = "a person erased a society of their world, with every record of it"
#: Why an erasure is refused, by code.
SOCIETY_ERASURE_REFUSALS: Final = {
    "society_unavailable": "this world version holds no society",
    "restore_sealed": "the installation is sealed for a restore; erase again once it is replayed",
}


class SocietyErasureRefused(ValueError):
    """An erasure refused by a code a caller can act on."""

    def __init__(self, code: str) -> None:
        super().__init__(SOCIETY_ERASURE_REFUSALS[code])
        self.code = code
        self.detail = SOCIETY_ERASURE_REFUSALS[code]


def erase_society(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    *,
    erased_by: uuid.UUID,
) -> uuid.UUID:
    """Erase the society of ``version_id`` whole, and answer the erasure's id.

    Under the workspace's lock, which a playback round and an edit take before they touch a
    society, a society tombstone, then one row naming the society, its version and that
    tombstone; the row's trigger withdraws the Companion's answers that cited the version and
    deletes, at once and as the definer owner, every row that records the society. A restore
    carries both, and its replayed tombstone withdraws those answers again. Refused by
    name: a version that holds no society (``society_unavailable``) and an installation sealed for
    a restore (``restore_sealed``, migration 0107)."""
    try:
        with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
            lock_workspace(connection, workspace_id)
            held = cursor.execute(
                "select society_id from world_society where workspace_id = %s and world_id = %s "
                "and version_id = %s",
                (workspace_id, world_id, version_id),
            ).fetchone()
            if held is None:
                raise SocietyErasureRefused("society_unavailable")
            tombstone = cursor.execute(
                "insert into tombstone (workspace_id, scope, requested_by, reason) "
                "values (%s, 'society', %s, %s) returning tombstone_id",
                (workspace_id, erased_by, ERASURE_REASON),
            ).fetchone()
            assert tombstone is not None
            row = cursor.execute(
                "insert into society_erasure (workspace_id, world_id, version_id, society_id, "
                "tombstone_id, erased_by) values (%s, %s, %s, %s, %s, %s) returning erasure_id",
                (
                    workspace_id,
                    world_id,
                    version_id,
                    held["society_id"],
                    tombstone["tombstone_id"],
                    erased_by,
                ),
            ).fetchone()
    except psycopg.errors.ObjectNotInPrerequisiteState as exc:
        raise SocietyErasureRefused("restore_sealed") from exc
    assert row is not None
    return row["erasure_id"]
