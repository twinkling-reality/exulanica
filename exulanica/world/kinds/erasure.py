"""Erase unused kept world-kind versions and permanently retire their identities."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row

from exulanica.world.workspace_lock import lock_workspace

REFUSALS = {
    "unknown_world_kind": "No kept world-kind version has this digest.",
    "world_kind_erased": "This world-kind version was permanently erased.",
    "world_kind_not_yours": "Only its creator or the workspace owner can erase this kind.",
    "world_kind_in_use": "A retained world still uses this kind. Remove that world first.",
    "restore_sealed": "The installation is sealed for restore. Try again after replay.",
}


class KindErasureRefused(ValueError):
    """A named refusal leaves the kept kind intact."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.detail = REFUSALS[code]
        super().__init__(self.detail)


def _target(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    digest: str,
    actor: uuid.UUID,
    by_owner: bool,
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select kind,version,created_by from world_kind_version "
            "where workspace_id=%s and document_sha256=%s",
            (workspace_id, digest),
        ).fetchone()
        if row is None:
            erased = cursor.execute(
                "select 1 from world_kind_erasure where workspace_id=%s and document_sha256=%s",
                (workspace_id, digest),
            ).fetchone()
            raise KindErasureRefused("world_kind_erased" if erased else "unknown_world_kind")
    if row["created_by"] != actor and not by_owner:
        raise KindErasureRefused("world_kind_not_yours")
    return row


def removal_preview(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    digest: str,
    *,
    actor: uuid.UUID,
    by_owner: bool = False,
) -> dict[str, Any]:
    """Preview one version without requiring its document to still parse."""
    row = _target(connection, workspace_id, digest, actor, by_owner)
    with connection.cursor(row_factory=dict_row) as cursor:
        uses = cursor.execute(
            "select count(*) as n from world_generation_receipt where workspace_id=%s "
            "and receipt->'kind'->>'sha256'=%s",
            (workspace_id, digest),
        ).fetchone()["n"]
    return {
        "document_sha256": digest,
        "kind": row["kind"],
        "version": row["version"],
        "world_receipts": uses,
        "removable": uses == 0,
        "consequences": [
            "This kept version is erased permanently. Existing worlds must be removed first.",
            "Its document and key/version cannot be kept again, including after backup restore.",
        ],
        "retained": [
            "Removal identities, timestamps and document/key fingerprints remain for restore.",
            "Fingerprints are not anonymization. Other versions and spending records remain.",
        ],
    }


def erase_kind(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    digest: str,
    *,
    erased_by: uuid.UUID,
    by_owner: bool = False,
) -> tuple[str, int]:
    """Erase under the workspace lock; caller evicts transient content after commit."""
    try:
        with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
            lock_workspace(connection, workspace_id)
            row = _target(connection, workspace_id, digest, erased_by, by_owner)
            tombstone = cursor.execute(
                "insert into tombstone(workspace_id,scope,requested_by,reason) "
                "values(%s,'world_kind',%s,%s) returning tombstone_id",
                (workspace_id, erased_by, "a person erased an unused kept world-kind version"),
            ).fetchone()["tombstone_id"]
            cursor.execute(
                "insert into world_kind_erasure(workspace_id,document_sha256,kind_key_sha256,"
                "version,tombstone_id,erased_by) values(%s,%s,%s,%s,%s,%s)",
                (
                    workspace_id,
                    digest,
                    hashlib.sha256(row["kind"].encode()).hexdigest(),
                    row["version"],
                    tombstone,
                    erased_by,
                ),
            )
    except psycopg.errors.CheckViolation as exc:
        if exc.diag.constraint_name == "world_kind_in_use":
            raise KindErasureRefused("world_kind_in_use") from exc
        raise
    except psycopg.errors.ObjectNotInPrerequisiteState as exc:
        raise KindErasureRefused("restore_sealed") from exc
    return row["kind"], row["version"]
