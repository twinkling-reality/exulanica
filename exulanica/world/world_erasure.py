"""Permanent removal of a generated world, retaining identifiers and creation budget only."""

from __future__ import annotations

import uuid

import psycopg
from psycopg.rows import dict_row

from exulanica.world.workspace_lock import lock_workspace
from exulanica.world.worlds import GENERATED, WorldIdentity, require_world

ERASURE_REASON = "a person removed a generated world with every record of it"
REFUSALS = {
    "world_not_yours": "A world is removed by its creator or an owner of its workspace.",
    "world_kind_not_removable": "Only generated worlds can be removed through this route.",
    "generation_pending": "This world has generation work or spending settlement still pending.",
    "restore_sealed": "The installation is sealed for restore. Try again after replay.",
}


class WorldErasureRefused(ValueError):
    """A named refusal leaves the world intact."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.detail = REFUSALS[code]
        super().__init__(self.detail)


def _allowed(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    actor: uuid.UUID,
    by_owner: bool,
) -> WorldIdentity:
    world = require_world(connection, workspace_id, world_id)
    if world.created_by != actor and not by_owner:
        raise WorldErasureRefused("world_not_yours")
    if world.kind != GENERATED:
        raise WorldErasureRefused("world_kind_not_removable")
    return world


def removal_preview(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    *,
    actor: uuid.UUID,
    by_owner: bool = False,
) -> dict:
    """Read the removal's scope. Counts are informational; removal rechecks authority."""
    _allowed(connection, workspace_id, world_id, actor, by_owner)
    with connection.cursor(row_factory=dict_row) as cursor:
        entry = cursor.execute(
            "select title from saved_world_entry where workspace_id=%s and world_id=%s "
            "order by created_at limit 1",
            (workspace_id, world_id),
        ).fetchone()
        counts = {}
        # Closed table names owned by this module, never user input.
        for label, table in (
            ("saved_entries", "saved_world_entry"),
            ("versions", "world_alternate_version"),
            ("societies", "world_society"),
            ("door_grants", "door_grant"),
            ("projects", "world_project"),
            ("notes", "world_project_item"),
        ):
            row = cursor.execute(
                f"select count(*) as n from {table} where workspace_id=%s and world_id=%s",
                (workspace_id, world_id),
            ).fetchone()
            counts[label] = row["n"]
    return {
        "world_id": world_id,
        "title": None if entry is None else entry["title"],
        "counts": counts,
        "consequences": [
            "The world, saved entries, edits, inhabitants and their history "
            "are permanently removed.",
            "Programs lose access through this world's doors.",
            "A restore from a backup removes this world again. This cannot be undone.",
        ],
        "retained": [
            "Removal identifiers and creation budget figures, without the world's words.",
            "Library kinds, shared generated tiles and spending records.",
            "Content already sent to an outside model provider is not recalled.",
        ],
    }


def erase_world(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    *,
    erased_by: uuid.UUID,
    by_owner: bool = False,
) -> tuple[uuid.UUID, tuple[uuid.UUID, ...], frozenset[str]]:
    """Atomically record removal, cancel tile jobs and erase the world's persistent rows.

    The caller invalidates local caches after its outer transaction commits. Returned entry
    identifiers let it discard corresponding draft memory without retaining typed content.
    """
    try:
        with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
            lock_workspace(connection, workspace_id)
            world = _allowed(connection, workspace_id, world_id, erased_by, by_owner)
            pending = cursor.execute(
                "select 1 from piece_request p where workspace_id=%s and world_id=%s and "
                "(state in ('requested','queued') or (reservation_id is not null and not exists "
                "(select 1 from piece_settlement s where s.workspace_id=p.workspace_id "
                "and s.piece_request_id=p.piece_request_id and s.settled_at is not null))) limit 1",
                (workspace_id, world_id),
            ).fetchone()
            if pending:
                raise WorldErasureRefused("generation_pending")
            entries = cursor.execute(
                "select entry_id from saved_world_entry where workspace_id=%s and world_id=%s",
                (workspace_id, world_id),
            ).fetchall()
            receipts = cursor.execute(
                "select receipt_sha256 from world_generation_receipt "
                "where workspace_id=%s and world_id=%s",
                (workspace_id, world_id),
            ).fetchall()
            tiles = cursor.execute(
                "select coalesce(max(jsonb_array_length(receipt->'tiles')),0) as n "
                "from world_generation_receipt where workspace_id=%s and world_id=%s "
                "and jsonb_typeof(receipt->'tiles')='array'",
                (workspace_id, world_id),
            ).fetchone()["n"]
            tombstone = cursor.execute(
                "insert into tombstone (workspace_id,scope,requested_by,reason) "
                "values (%s,'world',%s,%s) returning tombstone_id",
                (workspace_id, erased_by, ERASURE_REASON),
            ).fetchone()["tombstone_id"]
            erasure = cursor.execute(
                "insert into world_erasure "
                "(workspace_id,world_id,tombstone_id,erased_by,made_at,tiles) "
                "values (%s,%s,%s,%s,%s,%s) returning erasure_id",
                (workspace_id, world_id, tombstone, erased_by, world.created_at, tiles),
            ).fetchone()["erasure_id"]
    except psycopg.errors.ObjectNotInPrerequisiteState as exc:
        raise WorldErasureRefused("restore_sealed") from exc
    return (
        erasure,
        tuple(row["entry_id"] for row in entries),
        frozenset(row["receipt_sha256"] for row in receipts),
    )
