"""The formation stream: server-sent events for one intake batch.

``interaction-model.md`` 8.4: "Progress arrives as server-sent events per capture, each carrying
stage, stage index, counters, a message, a timestamp and an event id. The client maps events to
visual state and resumes from the last event id on reconnect."

The route validates and delegates. Everything about what an event MEANS lives in
:mod:`exulanica.ingest.formation`, which is where the ledger's vocabulary meets the interface's,
and this file decides only how that reaches a browser.

Five things it does decide, each of which is a property of streaming rather than of formation.

**It polls, and holds nothing between polls.** There is no LISTEN/NOTIFY here: that would be a
second connection held open per subscriber and a notification path that has to agree with the
query it replaces. Each poll is one read of the ledger, on a connection opened for that read and
closed after it, in a worker thread from a small limiter every stream in the process shares
(:data:`STREAM_POLLERS`). Between polls a stream is an awaited sleep. So an open stream costs a
socket and a place in the streams class of :mod:`exulanica.api.admission`, never a request thread
and never a database connection, and a client that leaves is noticed at that sleep rather than at
the next thing the stream sends.

**It ends when the batch ends.** A stream that stayed open after its terminal event would have a
client reconnecting forever to be told nothing, which is a battery cost with no viewer. The client
is built for that: the reducer holds its last state and nothing advances without an event.

**It sends a comment heartbeat.** A proxy with an idle timeout closes a quiet connection, and a
closed connection looks to the client exactly like a pipeline that stopped. The heartbeat is a
comment line rather than an event so it cannot reach the reducer.

**It resumes exactly, and refuses a token it did not issue.** A resume token is the id of an event
this stream sent: ``received``, a ledger event id, or the batch's terminal id. Resuming from the
terminal id answers 200 with no events, so a client that already has the outcome is not sent it
twice. Anything else is 422 ``invalid_resume_token`` before a stream opens.

**A stream that ends without a terminal event means "reconnect".** It does that at its time cap,
and after :data:`FAILED_POLLS` polls in a row have failed; a single failed poll sends nothing and
is tried again at the next interval. Before ending that way it sends ``retry:``, the field a
browser's ``EventSource`` reads as its reconnection delay and a reader of ``data:`` lines ignores.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Annotated, Any, Final, TypeVar

import anyio
import anyio.to_thread
import psycopg
from anyio.lowlevel import RunVar
from fastapi import APIRouter, Header, Path, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, ReadOnlySessions
from exulanica.ingest.formation import (
    FORMATION_STAGES,
    RECEIVED_TOKEN,
    FormationEvent,
    project_formation,
)

_LOG = logging.getLogger(__name__)
_T = TypeVar("_T")

router = APIRouter(prefix="/formation", tags=["formation"])

#: How often the ledger is re-read. Slow enough that a watched ingest costs one cheap indexed
#: read every two seconds, fast enough that a stage boundary is visible as it happens rather
#: than as a jump.
_POLL_SECONDS: Final = 2.0

#: A comment line every this many polls, so an idle proxy does not close a live connection.
_HEARTBEAT_EVERY: Final = 7

#: An outcome sorts after every stage, which is what makes "is this the end" a comparison rather
#: than a list of four outcome names kept in step with the projection's own list.
_TERMINAL_INDEX: Final = len(FORMATION_STAGES)

#: The stream ends after this long. Not a timeout on the pipeline: an ingest that outlives it is
#: still running and the client reconnects with its resume token. It exists so a forgotten tab
#: cannot hold a place in the streams class indefinitely.
_MAX_SECONDS: Final = 30 * 60

#: The worker threads every stream in one process polls with, and so the most database
#: connections the process's streams hold at once.
STREAM_POLLERS: Final = 4

#: A poll's statement timeout. The reads are indexed and take milliseconds; a poll that waits
#: this long is waiting on a lock, and giving it up keeps a poller free for the other streams.
_POLL_TIMEOUT_MS: Final = 5000

#: Failed polls in a row after which a stream ends without a terminal event.
FAILED_POLLS: Final = 3

#: The reconnection delay a stream suggests when it ends without a terminal event.
_RECONNECT_MS: Final = 5000

#: The terminal id :func:`exulanica.ingest.formation.project_formation` gives a batch that ended,
#: for each ending ``intake_batch.status`` allows.
_TERMINAL_TOKEN: Final = re.compile(
    r"batch:(?P<batch>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r":(?P<status>succeeded|partial|failed|cancelled)"
)

_STREAM_HEADERS: Final = {
    "Cache-Control": "no-store",
    # Nginx buffers a proxied response by default, which turns a stream into one delivery at the
    # end. This is the header it reads to stop.
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}

#: The pollers' limiter, one per event loop, the way anyio keeps its own default limiter.
_POLLERS: RunVar[anyio.CapacityLimiter] = RunVar("exulanica_formation_pollers")


def _frame(event: FormationEvent) -> str:
    """One SSE frame. The id line is what the browser sends back as ``Last-Event-ID``."""
    return f"id: {event.event_id}\ndata: {json.dumps(event.as_payload())}\n\n"


class BatchRow(BaseModel):
    """One watched intake, as the interface lists it.

    No photograph, no evidence and nothing citable: a batch is a handle for watching work happen
    and is expected to be useless once the work has happened. ``declared_size`` is null until the
    source has been counted, which is a real state and the reason a client can subscribe before a
    total exists.
    """

    model_config = ConfigDict(extra="forbid")

    batch_id: uuid.UUID
    label: str | None
    declared_size: int | None
    status: str
    started_at: str
    ended_at: str | None


@router.get("", summary="Watched intakes in this workspace, newest first.")
def batches(
    connection: ReadOnlyConnection, session: CurrentSession, limit: int = 20
) -> list[BatchRow]:
    """What there is to watch.

    Finished batches are listed as well as running ones, because a client that arrived after an
    ingest finished should still be able to read what happened rather than find nothing and
    conclude the upload was lost. The stream of a finished batch replays its history and ends,
    which is the same code path a live subscriber takes.
    """
    rows = connection.execute(
        "select batch_id, label, declared_size, status, started_at, ended_at from intake_batch "
        "where workspace_id = %s order by started_at desc limit %s",
        (session.workspace_id, min(max(limit, 1), 100)),
    ).fetchall()
    return [
        BatchRow(
            batch_id=row["batch_id"],
            label=row["label"],
            declared_size=row["declared_size"],
            status=row["status"],
            started_at=row["started_at"].isoformat(),
            ended_at=row["ended_at"].isoformat() if row["ended_at"] else None,
        )
        for row in rows
    ]


@router.get("/{batch_id}", summary="Formation progress for one intake batch, as it happens.")
async def stream(
    request: Request,
    batch_id: Annotated[uuid.UUID, Path()],
    sessions: ReadOnlySessions,
    session: CurrentSession,
    last_event_id: Annotated[str | None, Header(alias="last-event-id")] = None,
    since: Annotated[str | None, Query(max_length=200)] = None,
) -> Response:
    """Subscribe to a batch.

    Two ways to resume, and both exist for a reason. ``Last-Event-ID`` is what a browser's own
    ``EventSource`` sends on an automatic reconnect and the client never has to think about it.
    ``since`` is for a client that reconnects deliberately, having held its own token across a
    view change or a reload, which an ``EventSource`` cannot do because it is a new object with
    no memory.

    The header wins when both are present. A browser sends it only when it genuinely has an event
    to resume from, so it is the more recent of the two by construction.
    """
    resume = _resume_point(last_event_id or since, batch_id)
    if resume is None:
        return _invalid_token()
    ledger = _Ledger(sessions, session.workspace_id, batch_id)
    # Checked here rather than left to the projection, because 404 on an unknown batch and an
    # empty stream on a known one are different answers and only one of them is true. The check
    # is a workspace-scoped read, so a batch in another workspace is not found, identically to a
    # batch that never existed.
    batch = await ledger.batch()
    if batch is None:
        return JSONResponse(
            status_code=404, content={"code": "unknown_reference", "detail": "no such intake batch"}
        )
    if resume.ended_as is not None:
        if batch["ended_at"] is None or batch["status"] != resume.ended_as:
            return _invalid_token()
        return Response(status_code=200, media_type="text/event-stream", headers=_STREAM_HEADERS)
    return StreamingResponse(
        _events(ledger, resume.after, getattr(request.app.state, "admission", None)),
        media_type="text/event-stream",
        headers=_STREAM_HEADERS,
    )


@dataclass(frozen=True, slots=True)
class _Resume:
    #: What the projection is asked for events after: None, ``received`` or a ledger event id.
    after: str | None
    #: The status a terminal token names, when the token is this batch's terminal id.
    ended_as: str | None = None


def _resume_point(token: str | None, batch_id: uuid.UUID) -> _Resume | None:
    """Where a token resumes, or None when it is not a token this stream issued."""
    if token is None:
        return _Resume(None)
    if token == RECEIVED_TOKEN:
        return _Resume(RECEIVED_TOKEN)
    terminal = _TERMINAL_TOKEN.fullmatch(token)
    if terminal is not None:
        if terminal["batch"] != str(batch_id):
            return None
        return _Resume(None, terminal["status"])
    try:
        return _Resume(str(uuid.UUID(token)))
    except ValueError:
        return None


def _invalid_token() -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "invalid_resume_token",
            "detail": (
                "the resume token is not an event id this stream sent; resume from an event id it "
                "sent, or subscribe without one to receive the batch from the beginning"
            ),
        },
    )


def _pollers() -> anyio.CapacityLimiter:
    try:
        return _POLLERS.get()
    except LookupError:
        limiter = anyio.CapacityLimiter(STREAM_POLLERS)
        _POLLERS.set(limiter)
        return limiter


class _Ledger:
    """One stream's reads: each on a short connection of its own, in a poller thread."""

    def __init__(
        self, sessions: Callable[[], Any], workspace_id: uuid.UUID, batch_id: uuid.UUID
    ) -> None:
        self._sessions = sessions
        self._workspace_id = workspace_id
        self._batch_id = batch_id

    async def batch(self) -> dict[str, Any] | None:
        return await self._read(
            lambda connection: connection.execute(
                "select status, ended_at from intake_batch "
                "where workspace_id = %s and batch_id = %s",
                (self._workspace_id, self._batch_id),
            ).fetchone()
        )

    async def after(self, token: str | None) -> list[FormationEvent]:
        return await self._read(
            lambda connection: project_formation(
                connection, self._workspace_id, self._batch_id, after=token
            )
        )

    async def _read(self, work: Callable[[psycopg.Connection], _T]) -> _T:
        return await anyio.to_thread.run_sync(self._on_connection, work, limiter=_pollers())

    def _on_connection(self, work: Callable[[psycopg.Connection], _T]) -> _T:
        with self._sessions() as connection:
            connection.execute(
                "select set_config('statement_timeout', %s, false)", (f"{_POLL_TIMEOUT_MS}ms",)
            )
            return work(connection)


async def _events(ledger: _Ledger, token: str | None, admission: Any | None) -> AsyncIterator[str]:
    """Emit what has happened, then what happens next, then stop.

    Nothing is held between polls: each read opens and closes its own connection in a poller
    thread, and the wait between them is an awaited sleep, where a client that has left is noticed.
    """
    started = time.monotonic()
    polls = 0
    failed = 0

    while True:
        try:
            events = await ledger.after(token)
        except psycopg.Error as exc:
            failed += 1
            if admission is not None:
                admission.note_poll_failure()
            _LOG.warning("A formation poll failed (%d in a row): %s", failed, type(exc).__name__)
            if failed >= FAILED_POLLS:
                yield f"retry: {_RECONNECT_MS}\n\n"
                return
        else:
            failed = 0
            for event in events:
                yield _frame(event)
                token = event.event_id
            # A terminal event is the end of the stream. The phase is the batch's outcome, and
            # there is nothing after an outcome.
            if events and events[-1].stage_index >= _TERMINAL_INDEX:
                return
        if time.monotonic() - started > _MAX_SECONDS:
            yield f"retry: {_RECONNECT_MS}\n\n"
            return

        polls += 1
        if polls % _HEARTBEAT_EVERY == 0:
            # A comment. The client's EventSource ignores it and the reducer never sees it, which
            # is exactly what a keep-alive should be: visible to the proxy and to nothing else.
            yield ": keep-alive\n\n"
        await anyio.sleep(_POLL_SECONDS)
