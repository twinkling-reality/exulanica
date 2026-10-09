"""The generation worker's rows: the open session, its batches, how each ends, and its settlements.

The worker reads the operator's register of sessions (``generation_session``, written only by the
operator's command) and writes a workspace's batches, outputs, requests' ends and settlements, each
in the workspace's own session (row-level security keyed on it) and each under the workspace's lock
(:func:`exulanica.world.workspace_lock.lock_workspace`), taken first, as an ask and a deletion take
it, so none of these interleaves with the workspace's tombstone.

A batch is recorded before anything of it reaches the bucket (:func:`record_batch`), and ends once:

- **done**: the session ran the entry. Each item kept is recorded (``piece_output``, and the
  installation's index ``generated_piece``), and each request ends ``made`` when at least one of its
  variants passed every check, ``refused`` when none did;
- **refused**: the session refused the entry before running it, its markers or outputs did not read
  as this entry's, or the entry never reached the bucket; its requests end ``failed`` with the code;
- **expired**: no session took the entry before its ``not_after``, or a session took it and never
  said it had ended by the time the job's own stop allowed; its requests end ``failed``
  ``session_ended``.

Each request a batch held gets its settlement decided in the same transaction as the batch's end
(``piece_settlement``): what it measured, at most its reservation, when the entry ran; ``not_sent``
when no session took it or it never reached the bucket; ``unknown`` when a session took it and
said nothing more. The worker settles each decided one with the spending authority afterwards and
marks it settled (:func:`mark_settled`), retrying on every pass until it is. A request a
workspace's deletion cancelled while queued is decided by its reservation: ``not_sent`` while it was
only admitted, ``unknown`` once dispatched (:func:`decide_cancelled`), and its entry is withdrawn.

``ready.json`` is written only while the batch is still queued, under the workspace's lock
(:func:`while_queued`), so a deletion either comes before it, and no entry is ever offered, or after
it, and the entry is withdrawn.

One generation worker runs per installation; the rowcount checks below refuse a second writer's
change rather than rely on that.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import psycopg
from exulanica_pieces.queue import read_session
from psycopg.rows import dict_row

from exulanica.errors import ExulanicaError
from exulanica.generation.entries import Output
from exulanica.world.workspace_lock import lock_workspace

__all__ = [
    "BATCH_REQUESTS",
    "BatchInFlight",
    "BatchNotOpen",
    "KeptOutput",
    "OpenSession",
    "PieceRequestNotWaiting",
    "QueuedRequest",
    "QueuedReservation",
    "Settlement",
    "answer_from_cache",
    "batches_in_flight",
    "cached_pieces",
    "cancelled_batches",
    "decide_cancelled",
    "end_batch",
    "fail_unreadable",
    "mark_settled",
    "open_session",
    "record_batch",
    "record_claim",
    "session_by_id",
    "unsettled",
    "waiting_requests",
    "while_queued",
]

#: The most requests one queue entry holds: an ask's most kinds.
BATCH_REQUESTS: Final = 16


class PieceRequestNotWaiting(ExulanicaError):
    """A request the worker meant to queue was cancelled or taken meanwhile."""


class BatchNotOpen(ExulanicaError):
    """A batch the worker meant to end had already ended, or is not the workspace's."""


@dataclass(frozen=True, slots=True)
class OpenSession:
    """A registered session whose window has not ended and which is not closed."""

    generation_session_id: uuid.UUID
    session_sha256: str
    route: str
    code_sha256: str
    components_sha256: str
    container: str
    compute_key: str
    window_ends_at: datetime
    #: The session record's hard stop, in seconds from its start.
    stop_seconds: int


@dataclass(frozen=True, slots=True)
class QueuedRequest:
    """A request a batch holds, with what the worker needs to end it and settle it."""

    piece_request_id: uuid.UUID
    request_sha256: str
    request_canonical: str
    reservation_id: uuid.UUID
    reservation_authority_id: uuid.UUID
    reservation_holder: str
    worst_case_usd: Decimal
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class BatchInFlight:
    """A batch still queued: its entry, its job, its deadlines and the requests it holds."""

    piece_batch_id: uuid.UUID
    job_sha256: str
    job_canonical: str
    generation_session_id: uuid.UUID
    queued_at: datetime
    not_after: datetime
    claimed_at: datetime | None
    requests: tuple[QueuedRequest, ...]


@dataclass(frozen=True, slots=True)
class QueuedReservation:
    """A request the worker queues, with the spending reservation it admitted for it."""

    piece_request_id: uuid.UUID
    reservation_id: uuid.UUID
    authority_id: uuid.UUID
    holder: str


@dataclass(frozen=True, slots=True)
class KeptOutput:
    """An output admitted at the shared store's boundary, with the cache key it was kept under."""

    output: Output
    cache_key: str
    components_sha256: str
    postprocess_version: str


@dataclass(frozen=True, slots=True)
class Settlement:
    """A decided settlement still to be taken by the spending authority."""

    piece_request_id: uuid.UUID
    reservation_id: uuid.UUID
    reservation_authority_id: uuid.UUID
    reservation_holder: str
    basis: str
    usd: Decimal


_SESSION_COLUMNS: Final = (
    "generation_session_id, session_sha256, session_canonical, route, code_sha256, "
    "components_sha256, container, compute_key, window_ends_at"
)


def _session(row: Mapping[str, Any] | None) -> OpenSession | None:
    if row is None:
        return None
    values = dict(row)
    canonical = values.pop("session_canonical")
    stop = int(read_session(canonical.encode("ascii"))["stop_seconds"])
    return OpenSession(**values, stop_seconds=stop)


def open_session(connection: psycopg.Connection, now: datetime) -> OpenSession | None:
    """The session the worker serves: the latest registered one still open at ``now``."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            f"select {_SESSION_COLUMNS} from generation_session "
            "where closed_at is null and window_ends_at > %s and opened_at <= %s "
            "order by opened_at desc, generation_session_id desc limit 1",
            (now, now),
        ).fetchone()
    return _session(row)


def session_by_id(
    connection: psycopg.Connection, generation_session_id: uuid.UUID
) -> OpenSession | None:
    """A registered session by its id, open or closed: a batch follows the session it went to."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            f"select {_SESSION_COLUMNS} from generation_session where generation_session_id = %s",
            (generation_session_id,),
        ).fetchone()
    return _session(row)


def waiting_requests(
    connection: psycopg.Connection, workspace_id: uuid.UUID
) -> list[dict[str, Any]]:
    """The workspace's oldest requests waiting for a session, at most one batch's worth."""
    with connection.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            "select piece_request_id, request_canonical, request_sha256, worst_case_usd, "
            "variants, requested_at from piece_request "
            "where workspace_id = %s and state = 'requested' "
            "order by requested_at, piece_request_id limit %s",
            (workspace_id, BATCH_REQUESTS),
        ).fetchall()


def batches_in_flight(
    connection: psycopg.Connection, workspace_id: uuid.UUID
) -> list[BatchInFlight]:
    """The workspace's batches still queued, oldest first, each with its requests."""
    with connection.cursor(row_factory=dict_row) as cursor:
        batches = cursor.execute(
            "select piece_batch_id, job_sha256, job_canonical, generation_session_id, queued_at, "
            "not_after, claimed_at from piece_batch "
            "where workspace_id = %s and state = 'queued' order by queued_at, piece_batch_id",
            (workspace_id,),
        ).fetchall()
        found = []
        for batch in batches:
            requests = cursor.execute(
                "select piece_request_id, request_sha256, request_canonical, reservation_id, "
                "reservation_authority_id, reservation_holder, worst_case_usd, requested_at "
                "from piece_request where workspace_id = %s and piece_batch_id = %s "
                "order by requested_at, piece_request_id",
                (workspace_id, batch["piece_batch_id"]),
            ).fetchall()
            found.append(
                BatchInFlight(**batch, requests=tuple(QueuedRequest(**row) for row in requests))
            )
    return found


def record_batch(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    generation_session_id: uuid.UUID,
    job_raw: bytes,
    queued_at: datetime,
    not_after: datetime,
    queued: Sequence[QueuedReservation],
) -> uuid.UUID:
    """Record a batch and move its requests to queued, naming the batch and each request's
    reservation, in one transaction under the workspace's lock, before anything reaches the bucket.
    A request no longer waiting (:class:`PieceRequestNotWaiting`) leaves nothing written. Returns
    the batch's id, which names its entry."""
    if not queued:
        raise ValueError("a batch queues at least one request")
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        lock_workspace(connection, workspace_id)
        row = cursor.execute(
            "insert into piece_batch (workspace_id, generation_session_id, job_canonical, "
            "job_sha256, queued_at, not_after) values (%s, %s, %s, %s, %s, %s) "
            "returning piece_batch_id",
            (
                workspace_id,
                generation_session_id,
                job_raw.decode("ascii"),
                hashlib.sha256(job_raw).hexdigest(),
                queued_at,
                not_after,
            ),
        ).fetchone()
        assert row is not None
        for item in queued:
            moved = cursor.execute(
                "update piece_request set state = 'queued', queued_at = statement_timestamp(), "
                "piece_batch_id = %s, reservation_id = %s, reservation_authority_id = %s, "
                "reservation_holder = %s where workspace_id = %s and piece_request_id = %s "
                "and state = 'requested'",
                (
                    row["piece_batch_id"],
                    item.reservation_id,
                    item.authority_id,
                    item.holder,
                    workspace_id,
                    item.piece_request_id,
                ),
            )
            if moved.rowcount != 1:
                raise PieceRequestNotWaiting("a request in the batch is no longer waiting")
    return row["piece_batch_id"]


def record_claim(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    piece_batch_id: uuid.UUID,
    claimed_at: datetime,
) -> bool:
    """The session took the batch's entry at ``claimed_at`` (its claim marker's instant). False
    when the batch had its claim already or is no longer queued."""
    with connection.transaction():
        lock_workspace(connection, workspace_id)
        moved = connection.execute(
            "update piece_batch set claimed_at = %s where workspace_id = %s "
            "and piece_batch_id = %s and state = 'queued' and claimed_at is null",
            (claimed_at, workspace_id, piece_batch_id),
        )
    return moved.rowcount == 1


def end_batch(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    batch: BatchInFlight,
    *,
    state: str,
    ended_at: datetime,
    settlements: Mapping[uuid.UUID, tuple[str, Decimal]],
    outputs: Sequence[KeptOutput] = (),
    refusal: str | None = None,
) -> Mapping[uuid.UUID, str]:
    """End a batch, every request it holds and each request's settlement decision, in one
    transaction under the workspace's lock; returns each request's end.

    ``done``: records ``outputs`` (each in the installation's index too) and ends each request made
    or refused by its outputs' verdicts; ``refused`` (with ``refusal``) and ``expired``: fails each
    request with the code. ``settlements`` maps every request to its basis and amount. A batch no
    longer queued is :class:`BatchNotOpen` and nothing is written; a request a deletion cancelled
    keeps its end and still gets its settlement."""
    if state not in ("done", "refused", "expired"):
        raise ValueError("a batch ends done, refused or expired")
    if (state == "refused") != (refusal is not None):
        raise ValueError("a refused batch names its refusal, and only a refused one")
    if set(settlements) != {request.piece_request_id for request in batch.requests}:
        raise ValueError("every request of the batch has its settlement decided")
    by_digest: dict[str, list[QueuedRequest]] = {}
    for request in batch.requests:
        by_digest.setdefault(request.request_sha256, []).append(request)
    ends: dict[uuid.UUID, str] = {}
    with connection.transaction(), connection.cursor() as cursor:
        lock_workspace(connection, workspace_id)
        moved = cursor.execute(
            "update piece_batch set state = %s, refusal = %s, ended_at = %s "
            "where workspace_id = %s and piece_batch_id = %s and state = 'queued'",
            (state, refusal, ended_at, workspace_id, batch.piece_batch_id),
        )
        if moved.rowcount != 1:
            raise BatchNotOpen("the batch has ended already")
        within = {request.piece_request_id: False for request in batch.requests}
        for kept in outputs if state == "done" else ():
            holders = by_digest.get(kept.output.request_sha256)
            if not holders:
                raise ValueError("an output names a request the batch did not hold")
            _record_generated(cursor, kept)
            for request in holders:
                _record_output(cursor, workspace_id, request.piece_request_id, kept, batch)
                within[request.piece_request_id] |= kept.output.within
        for request in batch.requests:
            if state == "done":
                end, failure = ("made" if within[request.piece_request_id] else "refused"), None
            else:
                end, failure = "failed", refusal if state == "refused" else "session_ended"
            cursor.execute(
                "update piece_request set state = %s, failure = %s, finished_at = %s "
                "where workspace_id = %s and piece_request_id = %s and state = 'queued'",
                (end, failure, ended_at, workspace_id, request.piece_request_id),
            )
            ends[request.piece_request_id] = end
            basis, usd = settlements[request.piece_request_id]
            cursor.execute(
                "insert into piece_settlement (workspace_id, piece_request_id, reservation_id, "
                "basis, usd) values (%s, %s, %s, %s, %s)",
                (workspace_id, request.piece_request_id, request.reservation_id, basis, usd),
            )
    return ends


def _record_generated(cursor: psycopg.Cursor, kept: KeptOutput) -> None:
    verdict = kept.output.document["verdict"]
    cursor.execute(
        "insert into generated_piece (cache_key, variant, request_sha256, components_sha256, "
        "postprocess_version, receipt_canonical, receipt_sha256, piece_sha256, piece_bytes, "
        "within, over_checks) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "on conflict (cache_key, variant) do nothing",
        (
            kept.cache_key,
            kept.output.variant,
            kept.output.request_sha256,
            kept.components_sha256,
            kept.postprocess_version,
            kept.output.receipt.decode("ascii"),
            kept.output.receipt_sha256,
            kept.output.piece_sha256,
            len(kept.output.piece),
            bool(verdict["within"]),
            list(verdict.get("over", [])),
        ),
    )


def _record_output(
    cursor: psycopg.Cursor,
    workspace_id: uuid.UUID,
    piece_request_id: uuid.UUID,
    kept: KeptOutput,
    batch: BatchInFlight | None,
) -> None:
    verdict = kept.output.document["verdict"]
    cursor.execute(
        "insert into piece_output (workspace_id, piece_request_id, variant, piece_batch_id, "
        "cache_key, receipt_canonical, receipt_sha256, piece_sha256, within, over_checks) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            workspace_id,
            piece_request_id,
            kept.output.variant,
            None if batch is None else batch.piece_batch_id,
            kept.cache_key,
            kept.output.receipt.decode("ascii"),
            kept.output.receipt_sha256,
            kept.output.piece_sha256,
            bool(verdict["within"]),
            list(verdict.get("over", [])),
        ),
    )


def cached_pieces(connection: psycopg.Connection, cache_key: str) -> list[dict[str, Any]]:
    """The installation's kept pieces under ``cache_key``, by variant."""
    with connection.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            "select variant, receipt_canonical, receipt_sha256, piece_sha256, within, over_checks "
            "from generated_piece where cache_key = %s order by variant",
            (cache_key,),
        ).fetchall()


def answer_from_cache(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    piece_request_id: uuid.UUID,
    *,
    cache_key: str,
    cached: Sequence[Mapping[str, Any]],
) -> str | None:
    """Answer a waiting request from the installation's kept pieces, with no batch, no GPU run and
    no charge: each variant's output names its kept receipt, and the request ends made or refused
    by their verdicts. None when the request is no longer waiting."""
    with connection.transaction(), connection.cursor() as cursor:
        lock_workspace(connection, workspace_id)
        moved = cursor.execute(
            "update piece_request set state = 'queued', queued_at = statement_timestamp() "
            "where workspace_id = %s and piece_request_id = %s and state = 'requested'",
            (workspace_id, piece_request_id),
        )
        if moved.rowcount != 1:
            return None
        for row in cached:
            cursor.execute(
                "insert into piece_output (workspace_id, piece_request_id, variant, "
                "piece_batch_id, cache_key, receipt_canonical, receipt_sha256, piece_sha256, "
                "within, over_checks) values (%s, %s, %s, null, %s, %s, %s, %s, %s, %s)",
                (
                    workspace_id,
                    piece_request_id,
                    row["variant"],
                    cache_key,
                    row["receipt_canonical"],
                    row["receipt_sha256"],
                    row["piece_sha256"],
                    row["within"],
                    list(row["over_checks"]),
                ),
            )
        end = "made" if any(row["within"] for row in cached) else "refused"
        cursor.execute(
            "update piece_request set state = %s, finished_at = statement_timestamp() "
            "where workspace_id = %s and piece_request_id = %s and state = 'queued'",
            (end, workspace_id, piece_request_id),
        )
    return end


_CANCELLED: Final = (
    "from piece_request p left join spending_reservation r on r.workspace_id = p.workspace_id "
    "and r.reservation_id = p.reservation_id "
    "where p.workspace_id = %s and p.reservation_id is not null "
    "and p.state = 'cancelled' and not exists "
    "(select 1 from piece_settlement s where s.workspace_id = p.workspace_id "
    "and s.piece_request_id = p.piece_request_id) "
)


def cancelled_batches(connection: psycopg.Connection, workspace_id: uuid.UUID) -> list[uuid.UUID]:
    """The batches of requests a deletion cancelled while queued and not yet decided: the entries
    the worker withdraws before it decides them."""
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            f"select distinct p.piece_batch_id {_CANCELLED}", (workspace_id,)
        ).fetchall()
    return sorted((row["piece_batch_id"] for row in rows), key=str)


def decide_cancelled(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    unsent: frozenset[uuid.UUID] | set[uuid.UUID] = frozenset(),
) -> list[uuid.UUID]:
    """Decide each request a deletion cancelled while it was queued, by its reservation: one only
    admitted, one the ledger already released (it lapsed while queued, so it was never dispatched),
    or one in a batch the worker knows it never offered (``unsent``), never reached a session
    (``not_sent``); one dispatched may have (``unknown``: its whole reservation stays charged until
    an administrator reconciles it), since its batch is erased with the workspace. Returns the
    batches decided."""
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        lock_workspace(connection, workspace_id)
        rows = cursor.execute(
            "select p.piece_request_id, p.reservation_id, p.piece_batch_id, p.worst_case_usd, "
            f"r.state as reservation_state {_CANCELLED}"
            "order by p.requested_at, p.piece_request_id",
            (workspace_id,),
        ).fetchall()
        for row in rows:
            admitted = (
                row["reservation_state"] in ("admitted", "released")
                or row["piece_batch_id"] in unsent
            )
            cursor.execute(
                "insert into piece_settlement (workspace_id, piece_request_id, reservation_id, "
                "basis, usd) values (%s, %s, %s, %s, %s)",
                (
                    workspace_id,
                    row["piece_request_id"],
                    row["reservation_id"],
                    "not_sent" if admitted else "unknown",
                    Decimal(0) if admitted else row["worst_case_usd"],
                ),
            )
    return sorted({row["piece_batch_id"] for row in rows}, key=str)


def fail_unreadable(
    connection: psycopg.Connection, workspace_id: uuid.UUID, piece_request_id: uuid.UUID
) -> bool:
    """End a waiting request ``failed`` ``request_unreadable``: it no longer reads under the
    catalogs this server deploys (its budgets digest), so no session could make it."""
    with connection.transaction():
        lock_workspace(connection, workspace_id)
        moved = connection.execute(
            "update piece_request set state = 'failed', failure = 'request_unreadable', "
            "finished_at = statement_timestamp() where workspace_id = %s "
            "and piece_request_id = %s and state = 'requested'",
            (workspace_id, piece_request_id),
        )
    return moved.rowcount == 1


@contextmanager
def while_queued(
    connection: psycopg.Connection, workspace_id: uuid.UUID, piece_batch_id: uuid.UUID
) -> Iterator[bool]:
    """Hold the workspace's lock and say whether the batch is still queued: what is done inside
    happens before any deletion of the workspace or after it, never during."""
    with connection.transaction():
        lock_workspace(connection, workspace_id)
        row = connection.execute(
            "select 1 from piece_batch where workspace_id = %s and piece_batch_id = %s "
            "and state = 'queued'",
            (workspace_id, piece_batch_id),
        ).fetchone()
        yield row is not None


def unsettled(connection: psycopg.Connection, workspace_id: uuid.UUID) -> list[Settlement]:
    """The workspace's decided settlements the spending authority has not yet taken."""
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "select s.piece_request_id, s.reservation_id, p.reservation_authority_id, "
            "p.reservation_holder, s.basis, s.usd from piece_settlement s "
            "join piece_request p on p.workspace_id = s.workspace_id "
            "and p.piece_request_id = s.piece_request_id "
            "where s.workspace_id = %s and s.settled_at is null "
            "order by s.decided_at, s.piece_request_id",
            (workspace_id,),
        ).fetchall()
    return [Settlement(**row) for row in rows]


def mark_settled(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    piece_request_id: uuid.UUID,
    settled_at: datetime,
) -> None:
    """The spending authority took the request's settlement (or had already)."""
    with connection.transaction():
        lock_workspace(connection, workspace_id)
        connection.execute(
            "update piece_settlement set settled_at = %s where workspace_id = %s "
            "and piece_request_id = %s and settled_at is null",
            (settled_at, workspace_id, piece_request_id),
        )
