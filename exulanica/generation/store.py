"""The workspace's piece requests: asking, reading back, and cancelling.

A request is written whole when asked and only its progress moves after that (the migration's
trigger refuses anything else). Asking is idempotent two ways:

- a caller's key names one ask (table ``piece_ask``): asked again it answers with the requests the
  first answer held, whether that ask made them or found them waiting, and a key naming a different
  ask is :class:`PieceAskKeyReused`;
- the same open request (one world, one request digest) is held once: an ask for a piece already
  waiting is answered with the waiting request rather than a second one.

Every ask takes the workspace's lock first (:func:`exulanica.world.workspace_lock.lock_workspace`),
so an ask and the workspace's tombstone never interleave: the ask waits for a tombstone being
written and is then refused as tombstoned (:class:`exulanica.errors.TombstonedError`), or a
tombstone sent while the ask holds the lock is refused and sent again (migration 0137), after which
it cancels the request. Before anything is written each request is held to the catalogs and to its
row: its words are the catalogs' (:func:`~exulanica.generation.requests.assert_catalog_words`), its
thing kind the shipped kind the row names, its pack the look the ask names.

A world's list names its world; a request read or cancelled by its own id (or found by the
caller's key) is addressed within the workspace and answers with the world it is for.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import psycopg
from exulanica_pieces.records import read_request
from psycopg.rows import dict_row

from exulanica.db.guards import terminal_if_tombstoned
from exulanica.errors import ExulanicaError
from exulanica.generation.requests import (
    GenerationCatalogs,
    LookReference,
    PlannedRequest,
    assert_catalog_words,
    generation_catalogs,
)
from exulanica.things.kinds import ThingKind, shipped_thing_kinds
from exulanica.world.workspace_lock import lock_workspace

__all__ = [
    "OPEN_STATES",
    "PieceAskKeyReused",
    "PieceQuotaExceeded",
    "PieceRequestNotCancellable",
    "PieceRequestRecord",
    "answer_for_key",
    "cancel_piece_request",
    "create_piece_requests",
    "list_piece_requests",
    "open_worst_case",
    "read_piece_request",
]

#: The states a request waits in; the rest are ends.
OPEN_STATES: Final = ("requested", "queued")
#: Requests one list answers with, newest first.
LIST_LIMIT: Final = 100
_COLUMNS: Final = (
    "piece_request_id, world_id, requested_by, kind_key, kind_version, kind_sha256, pack_id, "
    "pack_version, pack_manifest_sha256, look_role, variants, request_sha256, cache_scope, "
    "worst_case_usd, state, failure, requested_at, queued_at, finished_at"
)


class PieceAskKeyReused(ExulanicaError):
    """The caller's key names an earlier ask with another body."""


class PieceQuotaExceeded(ExulanicaError):
    """The workspace has made as many requests in a day, or holds as many open, as it may."""


class PieceRequestNotCancellable(ExulanicaError):
    """Only a request still waiting to be taken may be cancelled."""

    def __init__(self, state: str) -> None:
        super().__init__(f"a {state} piece request cannot be cancelled")
        self.state = state


@dataclass(frozen=True, slots=True)
class PieceRequestRecord:
    """One stored request, as the routes answer with it."""

    piece_request_id: uuid.UUID
    world_id: str
    requested_by: uuid.UUID
    kind_key: str
    kind_version: int
    kind_sha256: str
    pack_id: str
    pack_version: int
    pack_manifest_sha256: str
    look_role: str
    variants: int
    request_sha256: str
    cache_scope: str
    worst_case_usd: Decimal
    state: str
    failure: str | None
    requested_at: datetime
    queued_at: datetime | None
    finished_at: datetime | None

    def document(self) -> dict[str, Any]:
        def instant(value: datetime | None) -> str | None:
            return None if value is None else value.isoformat().replace("+00:00", "Z")

        return {
            "piece_request_id": str(self.piece_request_id),
            "world_id": self.world_id,
            "kind": {
                "key": self.kind_key,
                "version": self.kind_version,
                "sha256": self.kind_sha256,
            },
            "look": {
                "pack_id": self.pack_id,
                "version": self.pack_version,
                "manifest_sha256": self.pack_manifest_sha256,
            },
            "look_role": self.look_role,
            "variants": self.variants,
            "request_sha256": self.request_sha256,
            "cache_scope": self.cache_scope,
            "worst_case_usd": str(self.worst_case_usd),
            "state": self.state,
            "failure": self.failure,
            "requested_at": instant(self.requested_at),
            "queued_at": instant(self.queued_at),
            "finished_at": instant(self.finished_at),
        }


def _record(row: Mapping[str, Any]) -> PieceRequestRecord:
    return PieceRequestRecord(**row)


def answer_for_key(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    requested_by: uuid.UUID,
    request_id: uuid.UUID,
    ask_sha256: str,
) -> list[PieceRequestRecord] | None:
    """The requests the first ask under this key answered with, in its order, or None when the key
    names no ask yet. A key naming another body is :class:`PieceAskKeyReused`."""
    with connection.cursor(row_factory=dict_row) as cursor:
        ask = cursor.execute(
            "select ask_sha256, piece_request_ids from piece_ask where workspace_id = %s "
            "and requested_by = %s and request_id = %s",
            (workspace_id, requested_by, request_id),
        ).fetchone()
        if ask is None:
            return None
        if ask["ask_sha256"] != ask_sha256:
            raise PieceAskKeyReused("the key names an earlier ask with another body")
        rows = cursor.execute(
            f"select {_COLUMNS} from piece_request where workspace_id = %s "
            "and piece_request_id = any(%s)",
            (workspace_id, ask["piece_request_ids"]),
        ).fetchall()
    by_id = {row["piece_request_id"]: row for row in rows}
    return [_record(by_id[piece]) for piece in ask["piece_request_ids"] if piece in by_id]


def open_worst_case(connection: psycopg.Connection, workspace_id: uuid.UUID) -> Decimal:
    """What the workspace's open requests can cost at most, together."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select coalesce(sum(worst_case_usd), 0) as usd from piece_request "
            "where workspace_id = %s and state in ('requested', 'queued')",
            (workspace_id,),
        ).fetchone()
    assert row is not None
    return Decimal(row["usd"])


def _held_to_its_row(
    plan: PlannedRequest,
    look: LookReference,
    catalogs: GenerationCatalogs,
    shipped: Mapping[tuple[str, int], ThingKind],
) -> None:
    """The request's words are the catalogs', and its document names the shipped kind and the look
    its row will name. ``ValueError`` otherwise; nothing is written."""
    document = read_request(plan.request, catalogs.budgets)
    assert_catalog_words(document, catalogs)
    kind = shipped.get((plan.kind_key, plan.kind_version))
    if (
        kind is None
        or kind.sha256 != plan.kind_sha256
        or document.get("thing_kind")
        != {"key": plan.kind_key, "sha256": plan.kind_sha256, "version": plan.kind_version}
    ):
        raise ValueError("a request names the shipped kind its row names")
    pack = document["pack"]
    if (pack["id"], pack["version"], pack["sha256"]) != (
        look.pack_id,
        look.version,
        look.manifest_sha256,
    ):
        raise ValueError("a request names the look its row names")
    if plan.cache_scope != "catalog" or document["look_role"] != plan.look_role:
        raise ValueError("a request is catalog content and names its own look role")


def create_piece_requests(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    requested_by: uuid.UUID,
    world_id: str,
    look: LookReference,
    planned: Sequence[PlannedRequest],
    worst_cases: Sequence[Decimal],
    request_id: uuid.UUID | None = None,
    ask_sha256: str | None = None,
    catalogs: GenerationCatalogs | None = None,
    shipped: Mapping[tuple[str, int], ThingKind] | None = None,
) -> tuple[list[PieceRequestRecord], bool]:
    """The ask's requests, in the order planned, and whether any was made now.

    A request already open for the same world and request digest is answered rather than made
    again. Under a caller's key the ask is recorded with every request it answered with, and the
    same key asked again answers with them. A workspace over its limits is
    :class:`PieceQuotaExceeded`; a deleted workspace is :class:`~exulanica.errors.TombstonedError`.
    """
    if (request_id is None) != (ask_sha256 is None):
        raise ValueError("a key comes with the digest of the ask it names")
    if len(worst_cases) != len(planned) or not planned:
        raise ValueError("every planned request states its worst case")
    catalogs = catalogs or generation_catalogs()
    shipped = shipped if shipped is not None else shipped_thing_kinds()
    for plan in planned:
        _held_to_its_row(plan, look, catalogs, shipped)
    answered: list[PieceRequestRecord] = []
    made = False
    try:
        with (
            terminal_if_tombstoned(),
            connection.transaction(),
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            lock_workspace(connection, workspace_id)
            if request_id is not None:
                earlier = answer_for_key(
                    connection,
                    workspace_id,
                    requested_by=requested_by,
                    request_id=request_id,
                    ask_sha256=ask_sha256 or "",
                )
                if earlier is not None:
                    return earlier, False
            for plan, worst in zip(planned, worst_cases, strict=True):
                open_row = cursor.execute(
                    f"select {_COLUMNS} from piece_request where workspace_id = %s "
                    "and world_id = %s and request_sha256 = %s "
                    "and state in ('requested', 'queued')",
                    (workspace_id, world_id, plan.request_sha256),
                ).fetchone()
                if open_row is not None:
                    answered.append(_record(open_row))
                    continue
                row = cursor.execute(
                    "insert into piece_request (workspace_id, requested_by, world_id, kind_key, "
                    "kind_version, kind_sha256, pack_id, pack_version, pack_manifest_sha256, "
                    "look_role, variants, request_canonical, request_sha256, cache_scope, "
                    "worst_case_usd) "
                    "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    f"returning {_COLUMNS}",
                    (
                        workspace_id,
                        requested_by,
                        world_id,
                        plan.kind_key,
                        plan.kind_version,
                        plan.kind_sha256,
                        look.pack_id,
                        look.version,
                        look.manifest_sha256,
                        plan.look_role,
                        plan.variants,
                        plan.request.decode("ascii"),
                        plan.request_sha256,
                        plan.cache_scope,
                        worst,
                    ),
                ).fetchone()
                assert row is not None
                answered.append(_record(row))
                made = True
            if request_id is not None:
                cursor.execute(
                    "insert into piece_ask (workspace_id, requested_by, request_id, ask_sha256, "
                    "piece_request_ids) values (%s, %s, %s, %s, %s)",
                    (
                        workspace_id,
                        requested_by,
                        request_id,
                        ask_sha256,
                        [record.piece_request_id for record in answered],
                    ),
                )
    except psycopg.errors.ProgramLimitExceeded as limit:
        raise PieceQuotaExceeded(str(limit.diag.message_primary or limit)) from limit
    return answered, made


def list_piece_requests(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str
) -> list[PieceRequestRecord]:
    """A world's requests, newest first."""
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            f"select {_COLUMNS} from piece_request where workspace_id = %s and world_id = %s "
            "order by requested_at desc, piece_request_id desc limit %s",
            (workspace_id, world_id, LIST_LIMIT),
        ).fetchall()
    return [_record(row) for row in rows]


def read_piece_request(
    connection: psycopg.Connection, workspace_id: uuid.UUID, piece_request_id: uuid.UUID
) -> PieceRequestRecord | None:
    """One request of this workspace, or None (an id of another workspace reads as unknown)."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            f"select {_COLUMNS} from piece_request where workspace_id = %s "
            "and piece_request_id = %s",
            (workspace_id, piece_request_id),
        ).fetchone()
    return None if row is None else _record(row)


def cancel_piece_request(
    connection: psycopg.Connection, workspace_id: uuid.UUID, piece_request_id: uuid.UUID
) -> PieceRequestRecord | None:
    """Cancel a request no session has taken; None for an unknown id. A request already taken or
    ended is :class:`PieceRequestNotCancellable`."""
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            f"select {_COLUMNS} from piece_request where workspace_id = %s "
            "and piece_request_id = %s for update",
            (workspace_id, piece_request_id),
        ).fetchone()
        if row is None:
            return None
        if row["state"] != "requested":
            raise PieceRequestNotCancellable(row["state"])
        updated = cursor.execute(
            "update piece_request set state = 'cancelled', failure = 'cancelled_by_person', "
            "finished_at = statement_timestamp() where workspace_id = %s "
            f"and piece_request_id = %s and world_id = %s returning {_COLUMNS}",
            (workspace_id, piece_request_id, row["world_id"]),
        ).fetchone()
    assert updated is not None
    return _record(updated)
