"""The queue between the two halves of an ingest. It holds capture ids and never bytes.

**Why that is the whole design.** An upload has to put the photograph somewhere before the
pipeline can hash it, and there is nowhere safe to put it. An evidence address is a content hash
of the original bytes, a track key and a time interval; the bytes behind one live in the
content-addressed store, and the deletion cascade reaches exactly two things, the rows under the
nine tombstone guards and the objects in that store. Bytes staged anywhere else, a spool
directory or a queue payload or a scratch prefix, are reachable by neither. A tombstone written
while a file sits there finds nothing to cascade to, and every test of the cascade still passes,
because they look at the database and at the store. That is a deletion hole the suite is
structurally blind to, which is why the resolution is a shape rather than a sweep.

So the request thread runs the intake stage to completion, the bytes land in the store through
``committed_writes`` after the transaction that ran the tombstone guard commits, and what is
queued is the identifier of the capture that now owns them.

**A queued capture that is deleted before the worker runs is the ordinary path, not a hole.**
Migration 0011 refuses a derivative of tombstoned bytes, so the artifact row is refused and,
because the store write is deferred past the commit, the bytes are refused with it. The run is
cancelled rather than failed, and the orphan bytes left behind are the orphans any cancelled
ingest produces, in the store, which is the one place deletion reaches.

**A claim is a lease, and a lease is not a timestamp.** A worker that died leaves its row in
``running`` where no ``state = 'queued'`` predicate can see it, which is what R20 recorded. The
recovery is not "reclaim anything claimed a while ago": measured, a worker eight captures into a
job it is actively working on is indistinguishable from a dead one by ``claimed_at``, and every
reclaim that mistake produces pays for a model call a second time. So a claimant is believed
until ``lease_expires_at``, pushes that forward with :func:`heartbeat` between captures, and
:func:`claim` takes a ``running`` row only once the claimant has stopped saying anything.

**The lease is a heuristic and :data:`QueuedDerivatives.claim_token` is what makes a wrong one
cheap.** Nothing bounds the gap between two beats exactly: the model call has a computable
budget, the rendition and ``run_continuity`` in the same gap have none. Every write a claimant
makes to its own row therefore carries the token its claim issued, and a reclaim rotates it. A
worker whose lease was taken finds out at its next heartbeat and withdraws. Without that, measured
with two real processes: the reclaiming worker closed the batch `succeeded` at 17:58:13.896531 and
the original rewrote the same batch as `failed` with a fresh `ended_at` at 17:58:18.428698, and the
second terminal event arrived after the client's stream had already ended on the first.

**Four verbs, and each is a different fact about one lease.** :func:`claim` takes the next job,
whether it was queued or was left running by a claimant that stopped saying anything.
:func:`heartbeat` says the claimant is still here, and answers False rather than raising when it
is not. :func:`finish` closes a job the caller still holds. :func:`abandon` takes a job stranded
:data:`MAX_CLAIMS` times to a terminal state so the batch watching it can be closed. Nothing here
exposes the two columns, because a caller reading ``lease_expires_at`` would be deciding for
itself what an expired one means.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

__all__ = [
    "DERIVATIVES",
    "MAX_CLAIMS",
    "AbandonedDerivatives",
    "QueuedDerivatives",
    "abandon",
    "claim",
    "enqueue",
    "finish",
    "heartbeat",
    "record_capture",
    "record_lease_lost",
    "record_worker_event",
    "retry",
]

#: The ``job.kind`` of a queued derivative run. One string, in one place, because ``kind`` is
#: free text and a second spelling would be a queue nothing drains.
DERIVATIVES: Final = "intake_derivatives"

#: How many times one job may be claimed before :func:`abandon` ends it instead of a fourth
#: worker reclaiming it. Three: the first claim and two recoveries. Each claim past the first is
#: a full re-run of the captures that had not committed, which for a configured instance is a
#: paid model call apiece, so this bounds a bill as well as a loop.
#:
#: **This bound outruns the formation stream's cap, and it is not a wall-clock bound.** With the
#: deployed lease of 720 seconds and no other work ahead of it, a job stranded on every claim
#: reaches its terminal event after about 3 x 720 = 2160 seconds; queued work can make it later.
#: ``exulanica/api/routes/formation`` gives up at 1800. What a client sees then is what it sees for
#: any ingest that outlives the cap: the stream ends without a terminal event, the client
#: reconnects with its resume token, and missed events are replayed from the ledger rather than
#: recomputed. Only the FIRST strand is guaranteed to be visible inside one stream, and a sentence
#: claiming otherwise would be true of the first reclaim and false of the rest.
MAX_CLAIMS: Final = 3


@dataclass(frozen=True, slots=True)
class QueuedDerivatives:
    """One claimed job: which batch it finishes and which captures it has left to process."""

    job_id: uuid.UUID
    batch_id: uuid.UUID | None
    capture_ids: tuple[uuid.UUID, ...]
    #: How many times this job has been claimed, including this one. Recorded rather than
    #: inferred, so a job that keeps failing says how often rather than looking like a new one.
    attempts: int
    #: What this claim was issued. Carried back into :func:`heartbeat` and :func:`finish` and
    #: never inspected: a caller that read it would be deciding for itself whether it still holds
    #: the job, and the database is the only thing that can answer that.
    claim_token: uuid.UUID
    #: True when the claim recovered an expired running row rather than taking queued work.
    reclaimed: bool = False


@dataclass(frozen=True, slots=True)
class AbandonedDerivatives:
    """One job that was stranded too many times to claim again, and the batch still watching it."""

    job_id: uuid.UUID
    batch_id: uuid.UUID | None
    attempts: int


def enqueue(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    batch_id: uuid.UUID,
    capture_ids: list[uuid.UUID],
) -> uuid.UUID:
    """Queue the derivative stages for captures whose intake has already committed.

    Raises on an empty list rather than writing a job with nothing to do. A queued job is a
    promise that something is still coming, and a client watching a batch reads an open job as
    exactly that; one that will never produce an event is a stream that never ends.

    Called after the intakes commit, in the request that performed them. A process that dies in
    the window between the last intake and this insert returns no 202 either, so the client
    knows the upload did not complete; re-uploading the same bytes is free under content
    addressing and queues the work. That is the recovery, and it is the ordinary retry rather
    than a state anything has to repair.
    """
    if not capture_ids:
        raise ValueError("a derivative job needs at least one capture; queueing none is a lie")
    row = connection.execute(
        "insert into job (workspace_id, kind, payload, batch_id, progress_total) "
        "values (%s, %s, %s, %s, %s) "
        "returning job_id",
        (
            workspace_id,
            DERIVATIVES,
            Jsonb({"capture_ids": [str(capture_id) for capture_id in capture_ids]}),
            batch_id,
            len(capture_ids),
        ),
    ).fetchone()
    assert row is not None
    return row["job_id"]


def claim(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    worker: str,
    lease_seconds: float,
) -> QueuedDerivatives | None:
    """Take the next job for this workspace, or None when there is nothing to do.

    Two arms, as two queries. An expired ``running`` row is tried first so recovery is not starved
    by new uploads; a ``queued`` row whose ``run_after`` has passed is tried otherwise. Combining
    them with OR made PostgreSQL discard the queued arm's ordering index: measured on 55,000 jobs
    across twenty workspaces, it read 905 buffers and took 17.3 ms. The separate queued lookup
    reads four index buffers and stops at the first eligible row.

    A reclaimed row comes back with ``attempts`` incremented rather than reset, so it says it was
    claimed twice rather than looking like a new job. A row that has used every one of its
    :data:`MAX_CLAIMS` is passed over here and belongs to :func:`abandon`.

    ``for update skip locked`` inside the subquery is what makes two workers safe: the second
    passes over the row the first is holding rather than blocking on it. Measured with three
    processes racing one stranded row: one claimed it and two saw nothing. The row is moved to
    ``running`` in the same statement, so a claim is never observable as a read that has not yet
    become a write.

    ``lease_seconds`` is a value rather than a constant here because the only thing that can
    compute it is the caller that knows what the claimant will be doing between two beats. See
    :func:`exulanica.ingest.worker.lease_seconds_for`.
    """
    reclaimed = False
    with connection.transaction():
        row = connection.execute(
            "update job set state = 'running', claimed_by = %s, claimed_at = now(), "
            "  attempts = attempts + 1, claim_token = gen_random_uuid(), "
            "  lease_expires_at = now() + make_interval(secs => %s) "
            "where job_id = ("
            "  select job_id from job "
            "   where workspace_id = %s and kind = %s and state = 'running' "
            "     and lease_expires_at < now() and attempts < %s "
            "   order by priority, job_id for update skip locked limit 1) "
            "returning job_id, batch_id, payload, attempts, claim_token",
            (worker, lease_seconds, workspace_id, DERIVATIVES, MAX_CLAIMS),
        ).fetchone()
        if row is not None:
            reclaimed = True
        else:
            row = connection.execute(
                "update job set state = 'running', claimed_by = %s, claimed_at = now(), "
                "  attempts = attempts + 1, claim_token = gen_random_uuid(), "
                "  lease_expires_at = now() + make_interval(secs => %s) "
                "where job_id = ("
                "  select job_id from job "
                "   where workspace_id = %s and kind = %s and state = 'queued' "
                "     and run_after <= now() "
                "   order by priority, job_id for update skip locked limit 1) "
                "returning job_id, batch_id, payload, attempts, claim_token",
                (worker, lease_seconds, workspace_id, DERIVATIVES),
            ).fetchone()
        if row is None:
            return None
        _event(
            connection,
            workspace_id,
            worker=worker,
            event_type="claim_reclaimed" if reclaimed else "claim_acquired",
            job_id=row["job_id"],
            claim_token=row["claim_token"],
            attempt=row["attempts"],
        )
    payload = row["payload"] or {}
    return QueuedDerivatives(
        job_id=row["job_id"],
        batch_id=row["batch_id"],
        capture_ids=tuple(uuid.UUID(value) for value in payload.get("capture_ids", ())),
        attempts=row["attempts"],
        claim_token=row["claim_token"],
        reclaimed=reclaimed,
    )


def heartbeat(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    job_id: uuid.UUID,
    claim_token: uuid.UUID,
    lease_seconds: float,
    worker: str = "unknown",
) -> bool:
    """Push this claimant's lease forward. False means the job is no longer theirs.

    False rather than an exception, because losing a lease is not an error: it is one of the two
    ordinary outcomes of a beat, and the caller's response to it is to stop, not to unwind. The
    two cases it covers are a reclaim, which rotated the token, and an abandon, which moved the
    row out of ``running`` altogether. A caller that gets False must not finish the job and must
    not close its batch: something else now owns both.
    """
    with connection.transaction():
        row = connection.execute(
            "update job set lease_expires_at = now() + make_interval(secs => %s) "
            "where job_id = %s and workspace_id = %s and state = 'running' and claim_token = %s "
            "returning attempts",
            (lease_seconds, job_id, workspace_id, claim_token),
        ).fetchone()
        if row is None:
            return False
        _event(
            connection,
            workspace_id,
            worker=worker,
            event_type="lease_renewed",
            job_id=job_id,
            claim_token=claim_token,
            attempt=row["attempts"],
        )
        return True


def finish(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    job_id: uuid.UUID,
    state: str,
    claim_token: uuid.UUID,
    error: str | None = None,
    failure_class: str | None = None,
    cost: dict[str, Any] | None = None,
    progress_completed: int | None = None,
    worker: str = "unknown",
) -> bool:
    """Close a claimed job with what happened. False means the caller no longer held it.

    ``done``, ``failed`` and ``cancelled`` are three different facts and the column already
    distinguishes them. ``cancelled`` is what a tombstone produces: the user deleted the
    photographs and the work stopped, which is the system working rather than a fault to retry.

    **The token in the WHERE clause is the whole of the reclaim's safety.** Without it a worker
    whose lease was taken overwrites the state a second worker has already written, and then goes
    on to close the batch a second time; measured, that produced two terminal events for one
    batch 4.5 seconds apart, the second contradicting the first. The return value is what the
    caller checks before it closes anything.

    The lease is cleared as the row leaves ``running``: a terminal row holding a token would be a
    second opinion about who owns work that is over.
    """
    if state not in ("done", "failed", "cancelled", "missing", "unavailable"):
        raise ValueError(f"a claimed job cannot be closed as {state!r}")
    event_type = {
        "done": "job_succeeded",
        "failed": "job_failed",
        "cancelled": "job_cancelled",
        "missing": "job_missing",
        "unavailable": "job_unavailable",
    }[state]
    with connection.transaction():
        held = connection.execute(
            "select cost from job where job_id = %s and workspace_id = %s "
            "and state = 'running' and claim_token = %s for update",
            (job_id, workspace_id, claim_token),
        ).fetchone()
        if held is None:
            return False
        cumulative_cost = _merge_cost(held["cost"], cost)
        row = connection.execute(
            "update job set state = %s, last_error = %s, failure_class = %s, cost = %s, "
            "  completed_at = now(), "
            "  duration_ms = greatest(0, "
            "    (extract(epoch from (now() - created_at)) * 1000)::bigint), "
            "  progress_completed = greatest("
            "    progress_completed, coalesce(%s, progress_completed)), "
            "  lease_expires_at = null, claim_token = null "
            "where job_id = %s and workspace_id = %s and state = 'running' and claim_token = %s "
            "returning attempts, duration_ms, progress_completed, progress_total",
            (
                state,
                error,
                failure_class,
                Jsonb(cumulative_cost) if cumulative_cost else None,
                progress_completed,
                job_id,
                workspace_id,
                claim_token,
            ),
        ).fetchone()
        if row is None:
            return False
        _event(
            connection,
            workspace_id,
            worker=worker,
            event_type=event_type,
            job_id=job_id,
            claim_token=claim_token,
            attempt=row["attempts"],
            duration_ms=row["duration_ms"],
            progress_completed=row["progress_completed"],
            progress_total=row["progress_total"],
            cost=cumulative_cost,
            failure_class=failure_class,
            message=error,
        )
        return True


def retry(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    job_id: uuid.UUID,
    claim_token: uuid.UUID,
    delay_seconds: float,
    error: str,
    failure_class: str,
    worker: str,
    cost: dict[str, Any] | None = None,
) -> bool:
    """Release a held claim back to the queue after a measured, retryable failure."""
    with connection.transaction():
        held = connection.execute(
            "select cost from job where job_id = %s and workspace_id = %s "
            "and state = 'running' and claim_token = %s for update",
            (job_id, workspace_id, claim_token),
        ).fetchone()
        if held is None:
            return False
        cumulative_cost = _merge_cost(held["cost"], cost)
        row = connection.execute(
            "update job set state = 'queued', run_after = now() + make_interval(secs => %s), "
            "  last_error = %s, failure_class = %s, cost = %s, claimed_by = null, "
            "  lease_expires_at = null, claim_token = null "
            "where job_id = %s and workspace_id = %s and state = 'running' and claim_token = %s "
            "returning attempts, progress_completed, progress_total",
            (
                delay_seconds,
                error,
                failure_class,
                Jsonb(cumulative_cost) if cumulative_cost else None,
                job_id,
                workspace_id,
                claim_token,
            ),
        ).fetchone()
        if row is None:
            return False
        _event(
            connection,
            workspace_id,
            worker=worker,
            event_type="retry_scheduled",
            job_id=job_id,
            claim_token=claim_token,
            attempt=row["attempts"],
            progress_completed=row["progress_completed"],
            progress_total=row["progress_total"],
            cost=cost,
            failure_class=failure_class,
            message=error,
        )
        return True


def _merge_cost(previous: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, Any]:
    """Add measured attempt cost without inventing values for fields no provider returned."""
    if not previous and not current:
        return {}
    merged: dict[str, Any] = dict(previous or {})
    current = current or {}
    for key in ("model_calls", "input_tokens", "output_tokens"):
        if key in merged or key in current:
            merged[key] = int(merged.get(key, 0)) + int(current.get(key, 0))
    if "usd_estimate" in merged or "usd_estimate" in current:
        merged["usd_estimate"] = str(
            Decimal(str(merged.get("usd_estimate", "0")))
            + Decimal(str(current.get("usd_estimate", "0")))
        )
    for key, value in current.items():
        if key not in {"model_calls", "input_tokens", "output_tokens", "usd_estimate"}:
            merged[key] = value
    return merged


def abandon(
    connection: psycopg.Connection, workspace_id: uuid.UUID, *, worker: str = "unknown"
) -> AbandonedDerivatives | None:
    """End one job that has been stranded :data:`MAX_CLAIMS` times, or None when there is none.

    **Something has to call this or the bound is a leak rather than a limit.** A job at the bound
    is passed over by :func:`claim` for ever, and while it sits in ``running`` it holds
    ``job_one_live_job_per_batch`` against its batch, so that batch can never acquire another job
    and never gets a terminal event. That is the original R20 symptom with a different cause, and
    reaching it by fixing R20 would be a poor trade. :meth:`exulanica.ingest.worker.DerivativeWorker
    .drain` runs this on the pass where it claims nothing, and closes the batch this returns.

    ``failed`` rather than ``cancelled``: the work did not happen and nobody withdrew it.
    """
    with connection.transaction():
        row = connection.execute(
            "update job set state = 'failed', lease_expires_at = null, claim_token = null, "
            "  completed_at = now(), failure_class = 'retry_exhausted_after_process_death', "
            "  duration_ms = greatest("
            "    0, (extract(epoch from (now() - created_at)) * 1000)::bigint), "
            "  last_error = 'claimed ' || attempts || ' times and stranded every time; the lease "
            "expired with no worker saying anything and the job has used every claim it is "
            "allowed' "
            "where job_id = ("
            "  select job_id from job "
            "   where workspace_id = %s and kind = %s and state = 'running' "
            "     and lease_expires_at < now() and attempts >= %s "
            "   order by priority, job_id for update skip locked limit 1) "
            "returning job_id, batch_id, attempts, duration_ms, progress_completed, "
            "progress_total, last_error",
            (workspace_id, DERIVATIVES, MAX_CLAIMS),
        ).fetchone()
        if row is None:
            return None
        _event(
            connection,
            workspace_id,
            worker=worker,
            event_type="job_failed",
            job_id=row["job_id"],
            attempt=row["attempts"],
            duration_ms=row["duration_ms"],
            progress_completed=row["progress_completed"],
            progress_total=row["progress_total"],
            failure_class="retry_exhausted_after_process_death",
            message=row["last_error"],
        )
    return AbandonedDerivatives(
        job_id=row["job_id"], batch_id=row["batch_id"], attempts=row["attempts"]
    )


def record_worker_event(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    worker: str,
    event_type: str,
    message: str | None = None,
) -> None:
    """Record a process lifecycle fact once per workspace the worker is allowed to drain."""
    if event_type not in ("worker_started", "shutdown_requested", "worker_stopped"):
        raise ValueError(f"{event_type!r} is not a worker lifecycle event")
    _event(
        connection,
        workspace_id,
        worker=worker,
        event_type=event_type,
        message=message,
    )


def record_capture(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    worker: str,
    claimed: QueuedDerivatives,
    capture_id: uuid.UUID,
    event_type: str,
    progress_completed: int,
    progress_total: int,
    duration_ms: int | None = None,
    cost: dict[str, Any] | None = None,
    failure_class: str | None = None,
    message: str | None = None,
) -> bool:
    """Record capture-level progress only while this claimant still owns the delivery."""
    allowed = {
        "capture_started",
        "capture_succeeded",
        "capture_failed",
        "capture_cancelled",
        "capture_missing",
        "capture_unavailable",
    }
    if event_type not in allowed:
        raise ValueError(f"{event_type!r} is not a capture progress event")
    with connection.transaction():
        held = connection.execute(
            "select 1 from job where job_id = %s and workspace_id = %s and state = 'running' "
            "and claim_token = %s for update",
            (claimed.job_id, workspace_id, claimed.claim_token),
        ).fetchone()
        if held is None:
            return False
        connection.execute(
            "update job set progress_completed = greatest(progress_completed, %s) "
            "where job_id = %s",
            (progress_completed, claimed.job_id),
        )
        _event(
            connection,
            workspace_id,
            worker=worker,
            event_type=event_type,
            job_id=claimed.job_id,
            claim_token=claimed.claim_token,
            attempt=claimed.attempts,
            capture_id=capture_id,
            progress_completed=progress_completed,
            progress_total=progress_total,
            duration_ms=duration_ms,
            cost=cost,
            failure_class=failure_class,
            message=message,
        )
        return True


def record_lease_lost(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    worker: str,
    claimed: QueuedDerivatives,
    message: str,
) -> None:
    """Record withdrawal after a token mismatch without touching the new claimant's job row."""
    _event(
        connection,
        workspace_id,
        worker=worker,
        event_type="lease_lost",
        job_id=claimed.job_id,
        claim_token=claimed.claim_token,
        attempt=claimed.attempts,
        failure_class="lease_lost",
        message=message,
    )


def _event(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    worker: str,
    event_type: str,
    job_id: uuid.UUID | None = None,
    claim_token: uuid.UUID | None = None,
    attempt: int | None = None,
    capture_id: uuid.UUID | None = None,
    progress_completed: int | None = None,
    progress_total: int | None = None,
    duration_ms: int | None = None,
    cost: dict[str, Any] | None = None,
    failure_class: str | None = None,
    message: str | None = None,
) -> None:
    """Append one delivery fact. Callers own any transaction that must include a state change."""
    connection.execute(
        "insert into derivative_job_event (workspace_id, job_id, worker_id, event_type, "
        "claim_token, attempt, capture_id, progress_completed, progress_total, duration_ms, "
        "cost, failure_class, message) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
        "%s, %s, %s)",
        (
            workspace_id,
            job_id,
            worker,
            event_type,
            claim_token,
            attempt,
            capture_id,
            progress_completed,
            progress_total,
            duration_ms,
            Jsonb(cost) if cost else None,
            failure_class,
            message[:2000] if message else None,
        ),
    )
