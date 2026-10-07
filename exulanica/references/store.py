"""Reference requests, their jobs and our record of each search, kept in the workspace's database.

A request is a row of ``reference_request`` (migration 0148) and a job of kind
:data:`JOB_KIND` on the generic ``job`` table, claimed the way the tile bake claims its own
(``exulanica.ingest.generated_tiles``): ``for update skip locked``, a lease and a claim token, at
most :data:`MAXIMUM_CLAIMS` claims, and a stranded job ended as failed. Every write that moves a
request names its claim token, so a worker that lost its lease moves nothing; our record of a search
that was sent is written whoever holds the job. Every path that locks both rows locks the job's
first, then the request's.

The job's payload holds what the work needs and nothing more: the request's id, the person's
description as it is sent (saved names already replaced) and any words of the account's own the
caller asks to be screened (the route passes none: it does not know them). Every end of a request
(finished, cancelled, stranded, or expired after
:data:`QUEUED_EXPIRY_SECONDS` unclaimed) blanks the description and the words and clears the
digest of the request an idempotency key named, so after a request ends nothing of the person's
words is kept; only our planned queries are, in ``reference_lookup``. A request is accepted only
for a workspace the caller says is offered references, so no job waits for a worker that will
never take it, and at most :data:`MAX_OPEN_PER_ACTOR` unfinished and :data:`MAX_PER_ACTOR_HOUR`
in an hour for any one requester. Only the requester reads or stops a request through the routes.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.errors import ExulanicaError

__all__ = [
    "FINISHED",
    "JOB_KIND",
    "LEASE_SECONDS",
    "MAXIMUM_CLAIMS",
    "MAX_DESCRIPTION_CHARACTERS",
    "MAX_WITHHELD_WORDS",
    "QUEUED_EXPIRY_SECONDS",
    "ClaimedRequest",
    "ReferenceRequest",
    "RequestKeyReused",
    "RequestLimitReached",
    "RequestNotOffered",
    "abandon_stranded",
    "cancel_requested",
    "claim",
    "create_request",
    "end_unserved",
    "expire_unclaimed",
    "finish",
    "read_request",
    "record_lookup",
    "record_steps",
    "request_cancel",
]

JOB_KIND: Final = "reference_bundle"
#: A reference job ends within its deadline (the worker's, 30 s by default); the lease outlasts it
#: four times over so a slow model call never loses the claim, and a dead worker's job is taken
#: again within two minutes.
LEASE_SECONDS: Final = 120
MAXIMUM_CLAIMS: Final = 3
#: A queued job no worker has taken in this long is ended as failed (``expired``) and blanked: a
#: worker polls every second, so ten minutes unclaimed means none is coming.
QUEUED_EXPIRY_SECONDS: Final = 600
#: The same ceiling the world drafter's description carries (reference-prompts.v1.json).
MAX_DESCRIPTION_CHARACTERS: Final = 1000
MAX_WITHHELD_WORDS: Final = 16
#: One requester's unfinished requests, and requests in the last hour: a request spends up to three
#: of the operator's source credits and two model calls, so one requester cannot queue without end.
MAX_OPEN_PER_ACTOR: Final = 2
MAX_PER_ACTOR_HOUR: Final = 20
_MAX_WITHHELD_CHARACTERS: Final = 64
FINISHED: Final = ("complete", "partial", "failed", "cancelled")
_JOB_STATE: Final = {
    "complete": "done",
    "partial": "done",
    "failed": "failed",
    "cancelled": "cancelled",
}
#: How long a job took, written as the tile bake writes it.
_DURATION: Final = (
    "duration_ms=greatest(0, (extract(epoch from (now() - created_at)) * 1000)::bigint)"
)
#: The payload a job keeps once its request has ended: the request's id and nothing of the words.
_BLANKED: Final = "payload=jsonb_build_object('reference_id', payload->'reference_id')"
_COLUMNS: Final = (
    "reference_id, owner_actor_id, purpose, web, status, steps, bundle, bundle_sha256, failure, "
    "cancel_requested_at, created_at, finished_at, request_sha256, job_id, prompts_sha256"
)


class RequestKeyReused(ExulanicaError):
    """The idempotency key names an earlier request with a different body."""


class RequestNotOffered(ExulanicaError):
    """References are not offered to this workspace here, so no request is queued for it."""


class RequestLimitReached(ExulanicaError):
    """This requester already has as many requests open, or made this hour, as one may."""


@dataclass(frozen=True, slots=True)
class ReferenceRequest:
    reference_id: uuid.UUID
    owner_actor_id: uuid.UUID
    purpose: str
    web: bool
    status: str
    steps: tuple[Mapping[str, Any], ...]
    bundle: Mapping[str, Any] | None
    bundle_sha256: str | None
    failure: str | None
    cancel_requested_at: datetime | None
    created_at: datetime
    finished_at: datetime | None
    job_id: uuid.UUID
    prompts_sha256: str

    @property
    def finished(self) -> bool:
        return self.status in FINISHED


def _request(row: Mapping[str, Any]) -> ReferenceRequest:
    return ReferenceRequest(
        reference_id=row["reference_id"],
        owner_actor_id=row["owner_actor_id"],
        purpose=row["purpose"],
        web=row["web"],
        status=row["status"],
        steps=tuple(row["steps"]),
        bundle=row["bundle"],
        bundle_sha256=row["bundle_sha256"],
        failure=row["failure"],
        cancel_requested_at=row["cancel_requested_at"],
        created_at=row["created_at"],
        finished_at=row["finished_at"],
        job_id=row["job_id"],
        prompts_sha256=row["prompts_sha256"],
    )


def read_request(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    reference_id: uuid.UUID,
    *,
    owner_actor_id: uuid.UUID | None = None,
) -> ReferenceRequest | None:
    """The request, or None. With ``owner_actor_id``, only that requester's: anyone else's reads as
    one that does not exist."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            f"select {_COLUMNS} from reference_request where workspace_id=%s and reference_id=%s "
            "and (%s::uuid is null or owner_actor_id=%s::uuid)",
            (workspace_id, reference_id, owner_actor_id, owner_actor_id),
        ).fetchone()
    return None if row is None else _request(row)


def _by_key(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    owner_actor_id: uuid.UUID,
    request_id: uuid.UUID,
) -> Mapping[str, Any] | None:
    with connection.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            f"select {_COLUMNS} from reference_request where workspace_id=%s "
            "and owner_actor_id=%s and request_id=%s",
            (workspace_id, owner_actor_id, request_id),
        ).fetchone()


def _earlier(earlier: Mapping[str, Any], request_sha256: str | None) -> ReferenceRequest:
    """The request a repeated key names. While it runs its body must match; once it has ended its
    digest is cleared, and the key answers with it whatever was sent."""
    if earlier["request_sha256"] is not None and earlier["request_sha256"] != request_sha256:
        raise RequestKeyReused("the key names an earlier request with another body")
    return _request(earlier)


def create_request(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    offered_to: Collection[uuid.UUID],
    owner_actor_id: uuid.UUID,
    purpose: str,
    web: bool,
    description: str,
    withheld_words: Sequence[str],
    prompts_sha256: str,
    request_id: uuid.UUID | None = None,
    request_sha256: str | None = None,
) -> tuple[ReferenceRequest, bool]:
    """A new request and its queued job, or the earlier one its idempotency key names.

    ``offered_to`` is every workspace a worker here takes reference jobs for; a request for any
    other is :class:`RequestNotOffered`, so its words are never queued for nobody. Returns the
    request and whether it was made now. A key naming a running request with another body is
    :class:`RequestKeyReused`.
    """
    if workspace_id not in offered_to:
        raise RequestNotOffered("references are not offered to this workspace here")
    if (request_id is None) != (request_sha256 is None):
        raise ValueError("an idempotency key comes with the digest of the request it names")
    if not 0 < len(description) <= MAX_DESCRIPTION_CHARACTERS:
        raise ValueError(f"a description is 1 to {MAX_DESCRIPTION_CHARACTERS} characters")
    if len(withheld_words) > MAX_WITHHELD_WORDS or any(
        not isinstance(word, str) or len(word) > _MAX_WITHHELD_CHARACTERS for word in withheld_words
    ):
        raise ValueError(
            f"at most {MAX_WITHHELD_WORDS} withheld words of at most "
            f"{_MAX_WITHHELD_CHARACTERS} characters"
        )
    if request_id is not None:
        earlier = _by_key(connection, workspace_id, owner_actor_id, request_id)
        if earlier is not None:
            return _earlier(earlier, request_sha256), False
    reference_id = uuid.uuid4()
    payload = {
        "reference_id": str(reference_id),
        "description": description,
        "withheld_words": list(withheld_words),
    }
    try:
        with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
            # One requester at a time is counted, so two requests racing see each other.
            cursor.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 880148))",
                (f"{workspace_id}:{owner_actor_id}",),
            )
            counts = cursor.execute(
                "select count(*) filter (where finished_at is null) as open, "
                "count(*) filter (where created_at > now() - interval '1 hour') as hour "
                "from reference_request where workspace_id=%s and owner_actor_id=%s",
                (workspace_id, owner_actor_id),
            ).fetchone()
            assert counts is not None
            if counts["open"] >= MAX_OPEN_PER_ACTOR or counts["hour"] >= MAX_PER_ACTOR_HOUR:
                raise RequestLimitReached("this requester has as many requests as one may")
            job = cursor.execute(
                "insert into job (workspace_id, kind, payload) values (%s, %s, %s) "
                "returning job_id",
                (workspace_id, JOB_KIND, Jsonb(payload)),
            ).fetchone()
            assert job is not None
            row = cursor.execute(
                "insert into reference_request (workspace_id, reference_id, owner_actor_id, "
                "purpose, web, request_id, request_sha256, job_id, prompts_sha256) "
                f"values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning {_COLUMNS}",
                (
                    workspace_id,
                    reference_id,
                    owner_actor_id,
                    purpose,
                    web,
                    request_id,
                    request_sha256,
                    job["job_id"],
                    prompts_sha256,
                ),
            ).fetchone()
            assert row is not None
    except psycopg.errors.UniqueViolation as race:
        if race.diag.constraint_name != "reference_request_key" or request_id is None:
            raise
        earlier = _by_key(connection, workspace_id, owner_actor_id, request_id)
        if earlier is None:
            raise
        return _earlier(earlier, request_sha256), False
    return _request(row), True


@dataclass(frozen=True, slots=True)
class ClaimedRequest:
    """A claimed job and its request: what the worker needs, and the token every write names.

    The person's description and the account's words are left out of the repr, so neither reaches
    a log line by way of one.
    """

    workspace_id: uuid.UUID
    job_id: uuid.UUID
    claim_token: uuid.UUID
    attempts: int
    request: ReferenceRequest
    description: str = field(repr=False)
    withheld_words: tuple[str, ...] = field(repr=False)


def _fail_orphan(cursor: psycopg.Cursor[Any], job_id: uuid.UUID) -> None:
    """End a reference job that names no request of its workspace, so it never blocks the queue."""
    cursor.execute(
        "update job set state='failed', lease_expires_at=null, claim_token=null, "
        "completed_at=now(), failure_class='reference_request_missing', "
        "last_error='the job names no reference request of its workspace', "
        + _DURATION
        + ", "
        + _BLANKED
        + " where job_id=%s",
        (job_id,),
    )


def claim(
    connection: psycopg.Connection, workspace_id: uuid.UUID, *, worker: str
) -> ClaimedRequest | None:
    """Take the next queued reference job of this workspace, or None when there is none. A job
    naming no request of its workspace is failed and the next one taken."""
    while True:
        with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
            job = cursor.execute(
                "update job set state='running', claimed_by=%s, claimed_at=now(), "
                "attempts=attempts+1, claim_token=gen_random_uuid(), "
                "lease_expires_at=now()+make_interval(secs => %s) "
                "where job_id=(select job_id from job where workspace_id=%s and kind=%s "
                "and ((state='queued' and run_after<=now()) "
                "or (state='running' and lease_expires_at<now() and attempts<%s)) "
                "order by priority, job_id for update skip locked limit 1) "
                "returning job_id, payload, claim_token, attempts",
                (worker, LEASE_SECONDS, workspace_id, JOB_KIND, MAXIMUM_CLAIMS),
            ).fetchone()
            if job is None:
                return None
            payload = job["payload"]
            try:
                reference_id = uuid.UUID(str(payload["reference_id"]))
                description = str(payload["description"])
                withheld = tuple(str(word) for word in payload["withheld_words"])
            except (KeyError, TypeError, ValueError):
                _fail_orphan(cursor, job["job_id"])
                continue
            row = cursor.execute(
                "update reference_request set status='running' where workspace_id=%s "
                "and reference_id=%s and job_id=%s and status in ('queued', 'running') "
                f"returning {_COLUMNS}",
                (workspace_id, reference_id, job["job_id"]),
            ).fetchone()
            if row is None:
                _fail_orphan(cursor, job["job_id"])
                continue
        return ClaimedRequest(
            workspace_id=workspace_id,
            job_id=job["job_id"],
            claim_token=job["claim_token"],
            attempts=int(job["attempts"]),
            request=_request(row),
            description=description,
            withheld_words=withheld,
        )


def _holds(cursor: psycopg.Cursor[Any], claimed: ClaimedRequest) -> bool:
    row = cursor.execute(
        "select 1 from job where job_id=%s and claim_token=%s and state='running' for update",
        (claimed.job_id, claimed.claim_token),
    ).fetchone()
    return row is not None


def record_steps(
    connection: psycopg.Connection, claimed: ClaimedRequest, steps: Sequence[Mapping[str, Any]]
) -> bool:
    """Write the request's steps as the page reads them; False when the claim was lost."""
    with connection.transaction(), connection.cursor() as cursor:
        if not _holds(cursor, claimed):
            return False
        cursor.execute(
            "update reference_request set steps=%s where workspace_id=%s and reference_id=%s "
            "and status='running'",
            (Jsonb(list(steps)), claimed.workspace_id, claimed.request.reference_id),
        )
    return True


def cancel_requested(connection: psycopg.Connection, claimed: ClaimedRequest) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select cancel_requested_at is not null as asked from reference_request "
            "where workspace_id=%s and reference_id=%s",
            (claimed.workspace_id, claimed.request.reference_id),
        ).fetchone()
    return bool(row and row["asked"])


def record_lookup(
    connection: psycopg.Connection,
    claimed: ClaimedRequest,
    *,
    source: str,
    aspect: str,
    query: str,
    outcome: str,
    credits: int,
    result_count: int,
    provider_request_id: str | None,
) -> uuid.UUID:
    """Our record of one search the request sent, answered or not.

    It does not check the claim: a search that left is recorded whoever holds the job now, since
    the source counted it either way.
    """
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "insert into reference_lookup (workspace_id, reference_id, source, aspect, query, "
            "outcome, credits, result_count, provider_request_id) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning lookup_id",
            (
                claimed.workspace_id,
                claimed.request.reference_id,
                source,
                aspect,
                query,
                outcome,
                credits,
                result_count,
                provider_request_id,
            ),
        ).fetchone()
    assert row is not None
    return row["lookup_id"]


def finish(
    connection: psycopg.Connection,
    claimed: ClaimedRequest,
    *,
    status: str,
    steps: Sequence[Mapping[str, Any]],
    bundle: Mapping[str, Any] | None = None,
    bundle_sha256: str | None = None,
    failure: str | None = None,
) -> bool:
    """End the request and its job, blanking the person's words and clearing the request's digest;
    False when the claim was lost."""
    if status not in FINISHED:
        raise ValueError(f"a request finishes as one of {FINISHED}")
    with connection.transaction(), connection.cursor() as cursor:
        if not _holds(cursor, claimed):
            return False
        cursor.execute(
            "update reference_request set status=%s, steps=%s, bundle=%s, bundle_sha256=%s, "
            "failure=%s, request_sha256=null, finished_at=now() where workspace_id=%s "
            "and reference_id=%s and status='running'",
            (
                status,
                Jsonb(list(steps)),
                None if bundle is None else Jsonb(dict(bundle)),
                bundle_sha256,
                failure,
                claimed.workspace_id,
                claimed.request.reference_id,
            ),
        )
        cursor.execute(
            "update job set state=%s, last_error=%s, failure_class=%s, completed_at=now(), "
            + _DURATION
            + ", lease_expires_at=null, claim_token=null, "
            + _BLANKED
            + " where job_id=%s and claim_token=%s and state='running'",
            (
                _JOB_STATE[status],
                failure,
                None if failure is None else f"reference_{failure}"[:64],
                claimed.job_id,
                claimed.claim_token,
            ),
        )
    return True


def request_cancel(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    reference_id: uuid.UUID,
    *,
    owner_actor_id: uuid.UUID | None = None,
) -> ReferenceRequest | None:
    """Ask a request to stop. A queued one is cancelled at once; a running one at its next step.
    With ``owner_actor_id``, only that requester's request: anyone else's is None, as an unknown
    one is.

    The job's row is locked before the request's, as every other path that takes both does.
    """
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        named = cursor.execute(
            "select job_id from reference_request where workspace_id=%s and reference_id=%s "
            "and (%s::uuid is null or owner_actor_id=%s::uuid)",
            (workspace_id, reference_id, owner_actor_id, owner_actor_id),
        ).fetchone()
        if named is None:
            return None
        job = cursor.execute(
            "select state from job where job_id=%s for update", (named["job_id"],)
        ).fetchone()
        row = cursor.execute(
            "select status from reference_request where workspace_id=%s and reference_id=%s "
            "for update",
            (workspace_id, reference_id),
        ).fetchone()
        assert row is not None
        if row["status"] == "queued" and job is not None and job["state"] == "queued":
            cursor.execute(
                "update job set state='cancelled', completed_at=now(), "
                + _DURATION
                + ", "
                + _BLANKED
                + " where job_id=%s",
                (named["job_id"],),
            )
            cursor.execute(
                "update reference_request set status='cancelled', cancel_requested_at=now(), "
                "request_sha256=null, finished_at=now() where workspace_id=%s "
                "and reference_id=%s",
                (workspace_id, reference_id),
            )
        elif row["status"] == "running":
            cursor.execute(
                "update reference_request set cancel_requested_at=coalesce(cancel_requested_at, "
                "now()) where workspace_id=%s and reference_id=%s",
                (workspace_id, reference_id),
            )
    return read_request(connection, workspace_id, reference_id, owner_actor_id=owner_actor_id)


def _end_jobs(
    cursor: psycopg.Cursor[Any], workspace_id: uuid.UUID, where: str, failure: str, error: str
) -> int:
    jobs = cursor.execute(
        "update job set state='failed', lease_expires_at=null, claim_token=null, "
        "completed_at=now(), failure_class=%s, last_error=%s, "
        + _DURATION
        + ", "
        + _BLANKED
        + " where workspace_id=%s and kind=%s and "
        + where
        + " returning job_id",
        (f"reference_{failure}", error, workspace_id, JOB_KIND),
    ).fetchall()
    for job in jobs:
        cursor.execute(
            "update reference_request set status='failed', failure=%s, request_sha256=null, "
            "finished_at=now() where workspace_id=%s and job_id=%s "
            "and status in ('queued', 'running')",
            (failure, workspace_id, job["job_id"]),
        )
    return len(jobs)


def abandon_stranded(connection: psycopg.Connection, workspace_id: uuid.UUID) -> int:
    """End every reference job of this workspace stranded :data:`MAXIMUM_CLAIMS` times, and its
    request as failed, blanking the person's words. Returns how many were ended."""
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        return _end_jobs(
            cursor,
            workspace_id,
            f"state='running' and lease_expires_at<now() and attempts>={MAXIMUM_CLAIMS}",
            "stranded",
            "claimed every time it was allowed and stranded every time",
        )


def expire_unclaimed(connection: psycopg.Connection, workspace_id: uuid.UUID) -> int:
    """End every reference job of this workspace queued and untaken for
    :data:`QUEUED_EXPIRY_SECONDS`, and its request as failed (``expired``), blanking the words."""
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        return _end_jobs(
            cursor,
            workspace_id,
            f"state='queued' and created_at < now() - interval '{QUEUED_EXPIRY_SECONDS} seconds'",
            "expired",
            "queued and never taken",
        )


def end_unserved(connection: psycopg.Connection, workspace_id: uuid.UUID) -> int:
    """End every unfinished reference job of a workspace this installation does not serve, and its
    request as failed (``not_served``), blanking the words. Run where no worker will take them: at
    startup for every workspace the installation knows that it does not serve."""
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        return _end_jobs(
            cursor,
            workspace_id,
            "state in ('queued', 'running')",
            "not_served",
            "the installation does not serve references to this workspace",
        )
