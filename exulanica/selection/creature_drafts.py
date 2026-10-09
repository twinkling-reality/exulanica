"""A creature drafted from a person's words: a request kept as a row, played by a job (0184).

``POST /things/creatures`` queues a draft (:func:`create_draft`) and answers at once; a worker in
the API process (:class:`CreatureDraftWorker`) claims the draft's job, asks the creature drafter
(:func:`exulanica.selection.creature_drafting.draft_creature`, role ``creature_drafter``) and keeps
a creature the checks pass in the workspace's own store
(:meth:`exulanica.world.thing_store.ThingStore.keep_creature`); ``GET
/things/creatures/drafts/{draft_id}`` reads the draft as it goes.

The job is claimed as a reference job is (:mod:`exulanica.references.store`): ``for update skip
locked``, a lease and a claim token, at most :data:`MAXIMUM_CLAIMS` claims, and every write that
ends a draft names its claim token, so a worker that lost its lease ends nothing. A job stranded
every time it was claimed, or queued and never taken for :data:`QUEUED_EXPIRY_SECONDS`, is ended as
failed. Every path that locks both rows locks the job's first, then the draft's.

The job's payload holds what the work needs and nothing more: the draft's id, and the person's words
as they are sent, every saved name already replaced, with the placeholders that replaced them. Every
end of a draft blanks the words, and the draft keeps nothing of them, not even their digest: a
digest of a short sentence is the sentence. A kept draft names its kind by the digest of the kind's
document alone, so erasing the creature (``thing_erasure``) leaves the draft naming a kind nobody
holds, and a refused draft names a code and a field of the drafter's form, never a sentence: a
person reads the code's fixed sentence (:func:`refusal_sentence`), as a check's own sentence may
quote the drafted label. A draft is queued only for a workspace a worker here serves, and at most
:data:`MAX_OPEN_PER_ACTOR` unfinished and :data:`MAX_PER_ACTOR_HOUR` in an hour for any one
requester, since each spends model calls. Only its requester reads a draft through the routes.
Spending is keyed by the job, so under durable spending a job taken again after a crash is admitted
under the same key and the authority refuses what already happened rather than paying for it
twice; under process spending the key is not checked, and a job taken again may pay again, once
for each of its at most :data:`MAXIMUM_CLAIMS` claims. Every API process of an installation carries
the same creature settings, since each ends at startup the drafts of the workspaces it knows but
does not serve (:func:`end_unserved`).

A workspace tombstone ends the workspace's unfinished drafts in its own transaction (a trigger on
``tombstone``): each queued or running job is cancelled with its words blanked, and its draft ends
``cancelled``, failure ``workspace_deleted``. A draft is asked under the workspace's lock and never
once that tombstone is written (:func:`create_draft`). A worker that drafted for a cancelled draft
reads that its claim is gone and keeps nothing; a call it already sent finishes at the provider, and
its answer is discarded.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Callable, Collection, Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.env import env_name
from exulanica.errors import ExulanicaError, TombstonedError
from exulanica.models.client import ModelClient
from exulanica.models.errors import ModelError
from exulanica.models.manifest import Role
from exulanica.models.policy import HostedRequestPolicy, HostedRequestRefused
from exulanica.models.spending import SpendingRefused, spending_request_key
from exulanica.selection.calls import CallLog
from exulanica.selection.creature_drafting import (
    CHECK_SENTENCES,
    NOT_DRAFTED_SENTENCE,
    CreatureDraftRefusalCode,
    draft_creature,
    draft_form,
)
from exulanica.store.base import ContentAddressedStore
from exulanica.things.bodies import body_grammar
from exulanica.things.lines import check_line
from exulanica.world.thing_store import STORE_CODES, ThingStore, ThingStoreRefused
from exulanica.world.workspace_lock import lock_workspace

__all__ = [
    "CANCELLATION_CODES",
    "CREATURE_WORKER_ENV",
    "CREATURE_WORKSPACES_ENV",
    "FAILURE_CODES",
    "FINISHED",
    "JOB_KIND",
    "LEASE_SECONDS",
    "LISTED",
    "MAXIMUM_CLAIMS",
    "MAX_OPEN_PER_ACTOR",
    "MAX_PER_ACTOR_HOUR",
    "MAX_WORDS_CHARACTERS",
    "OFFER_REFUSALS",
    "QUEUED_EXPIRY_SECONDS",
    "ClaimedDraft",
    "CreatureDraft",
    "CreatureDraftWorker",
    "CreatureSettingRefused",
    "DraftLimitReached",
    "DraftNotOffered",
    "abandon_stranded",
    "claim",
    "create_draft",
    "creature_workspaces",
    "end_unserved",
    "expire_unclaimed",
    "finish",
    "kind_erased",
    "list_drafts",
    "plays_creatures_here",
    "read_draft",
    "refusal_codes",
    "refusal_field",
    "refusal_sentence",
    "refusal_sentences",
]

_LOG = logging.getLogger(__name__)

JOB_KIND: Final = "creature_draft"
#: A draft is a form and at most one repair, each bounded by the creature drafter's timeout; the
#: lease outlasts both twice over, so a slow call never loses the claim, and a dead worker's job is
#: taken again within the lease.
LEASE_SECONDS: Final = 900
MAXIMUM_CLAIMS: Final = 2
#: A queued draft no worker has taken in this long is ended as failed (``expired``): a worker polls
#: every second, so ten minutes untaken means none is coming.
QUEUED_EXPIRY_SECONDS: Final = 600
#: A person's words for one creature: a line, as the drafter's form states its own.
MAX_WORDS_CHARACTERS: Final = 400
#: One requester's unfinished drafts, and drafts in the last hour: each spends up to two model
#: calls, so one requester cannot queue without end.
MAX_OPEN_PER_ACTOR: Final = 1
MAX_PER_ACTOR_HOUR: Final = 20
FINISHED: Final = ("kept", "refused", "failed", "cancelled")
#: How a worker ends a draft; only a workspace tombstone cancels one (a trigger on ``tombstone``).
_ENDS: Final = ("kept", "refused", "failed")
#: Why a draft was cancelled, by code: its workspace was erased, which ends every unfinished draft.
CANCELLATION_CODES: Final = ("workspace_deleted",)
#: Why a draft could not be made, by code: the drafter did not answer, the spending authority or the
#: workspace's rules refused the request, or no worker took the draft (queued too long, stranded,
#: or its workspace not served here).
FAILURE_CODES: Final = (
    "drafter_unavailable",
    "expired",
    "not_served",
    "request_refused",
    "spending_refused",
    "stranded",
)
#: Why a workspace may not ask for a creature here, by code: no worker here drafts its creatures, or
#: this process has no model client to draft them with.
OFFER_REFUSALS: Final = ("creatures_not_run_here", "models_not_configured")
#: The most drafts a listing answers, newest first.
LISTED: Final = 20
_JOB_STATE: Final = {"kept": "done", "refused": "done", "failed": "failed"}
#: The lock seed that counts one requester's drafts, so two racing requests see each other.
_REQUESTER_LOCK_SEED: Final = 880160
_DURATION: Final = (
    "duration_ms=greatest(0, (extract(epoch from (now() - created_at)) * 1000)::bigint)"
)
#: The payload a job keeps once its draft has ended: the draft's id and nothing of the words.
_BLANKED: Final = "payload=jsonb_build_object('draft_id', payload->'draft_id')"
_COLUMNS: Final = (
    "draft_id, owner_actor_id, job_id, status, kind_sha256, refusal_code, refusal_field, failure, "
    "model_id, created_at, started_at, finished_at"
)
#: The code whose fixed sentence says only that a movement is not built; the grammar states each
#: movement's own sentence, which a refusal naming that movement's field reads instead.
_MOVEMENT_UNBUILT: Final = "creature_movement_unbuilt"


def refusal_sentences() -> Mapping[str, str]:
    """Every code a refused draft may name, with the fixed sentence a person reads for it: a
    check's (the drafter tells the model each one), the store's, and the drafter's own when no check
    is named. Closed: a refusal outside it is carried as ``creature_not_drafted``."""
    return {
        **CHECK_SENTENCES,
        **STORE_CODES,
        CreatureDraftRefusalCode.NOT_DRAFTED.value: NOT_DRAFTED_SENTENCE,
    }


def refusal_codes() -> tuple[str, ...]:
    """Every code a refused draft may name, in order."""
    return tuple(sorted(refusal_sentences()))


def refusal_field(where: str) -> str | None:
    """The field of the drafter's form a check refused, or None where the refusal names no one
    field (the whole creature, or several fields): only the form's own field names are kept."""
    return where if where in draft_form().model_fields else None


def refusal_sentence(code: str, field: str | None = None) -> str:
    """The sentence a person reads for a refused draft, from its code and field alone, never from
    the request: a movement this world has not built yet in the grammar's own sentence for that
    movement, and every other code in its check's, the store's or the drafter's sentence."""
    if code == _MOVEMENT_UNBUILT and field is not None and field.startswith("moves_"):
        spec = body_grammar().movements.get(field.removeprefix("moves_"))
        if spec is not None and spec.get("refusal"):
            return str(spec["refusal"])
    return refusal_sentences().get(code, NOT_DRAFTED_SENTENCE)


#: Absent or on, this process plays creature drafts in a thread; ``off`` (or ``0``, ``false``,
#: ``no``), nobody does, and a draft is refused before it is queued.
CREATURE_WORKER_ENV: Final = env_name("CREATURE_WORKER")
#: A JSON array of the workspace ids whose people may draft creatures here. Absent, none may: each
#: draft spends model calls on the installation's account.
CREATURE_WORKSPACES_ENV: Final = env_name("CREATURE_WORKSPACES")


class CreatureSettingRefused(ValueError):
    """A creature setting this process will not start with, named by code and variable."""

    def __init__(self, code: str, variable: str) -> None:
        super().__init__(f"{code}: {variable}")
        self.code = code
        self.variable = variable


def plays_creatures_here(value: str | None) -> bool:
    """Whether this process plays creature drafts (``EXULANICA_CREATURE_WORKER``)."""
    normalized = (value or "").strip().lower()
    if normalized in ("", "1", "true", "on", "yes", "here"):
        return True
    if normalized in ("0", "false", "off", "no"):
        return False
    raise CreatureSettingRefused("creature_worker_not_recognised", CREATURE_WORKER_ENV)


def creature_workspaces(value: str | None) -> tuple[uuid.UUID, ...]:
    """The workspaces whose people may draft creatures (``EXULANICA_CREATURE_WORKSPACES``), or a
    named refusal of a list half read."""
    if value is None or not value.strip():
        return ()
    try:
        document = json.loads(value)
    except json.JSONDecodeError:
        raise CreatureSettingRefused(
            "creature_workspaces_not_json", CREATURE_WORKSPACES_ENV
        ) from None
    if not isinstance(document, list):
        raise CreatureSettingRefused("creature_workspaces_not_array", CREATURE_WORKSPACES_ENV)
    workspaces: list[uuid.UUID] = []
    for entry in document:
        try:
            if not isinstance(entry, str):
                raise ValueError(entry)
            workspaces.append(uuid.UUID(entry))
        except ValueError:
            raise CreatureSettingRefused(
                "creature_workspaces_not_uuid", CREATURE_WORKSPACES_ENV
            ) from None
    return tuple(sorted(set(workspaces)))


class DraftNotOffered(ExulanicaError):
    """Creatures are not drafted for this workspace here, so no draft is queued for it."""


class DraftLimitReached(ExulanicaError):
    """This requester already has as many drafts open, or made this hour, as one may."""


@dataclass(frozen=True, slots=True)
class CreatureDraft:
    draft_id: uuid.UUID
    owner_actor_id: uuid.UUID
    job_id: uuid.UUID
    status: str
    #: The digest of the kept kind's document; the kind itself may since have been erased.
    kind_sha256: str | None
    refusal_code: str | None
    refusal_field: str | None
    failure: str | None
    model_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @property
    def finished(self) -> bool:
        return self.status in FINISHED


def _draft(row: Mapping[str, Any]) -> CreatureDraft:
    return CreatureDraft(**{name: row[name] for name in CreatureDraft.__slots__})


def kind_erased(connection: psycopg.Connection, workspace_id: uuid.UUID, kind_sha256: str) -> bool:
    """Whether the workspace erased the creature whose kind has this digest (``thing_erasure``)."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select exists (select 1 from thing_erasure where workspace_id=%s and sha256=%s) "
            "as erased",
            (workspace_id, kind_sha256),
        ).fetchone()
    return bool(row and row["erased"])


def read_draft(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    draft_id: uuid.UUID,
    *,
    owner_actor_id: uuid.UUID | None = None,
) -> CreatureDraft | None:
    """The draft, or None. With ``owner_actor_id``, only that requester's: anyone else's reads as
    one that does not exist."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            f"select {_COLUMNS} from creature_draft where workspace_id=%s and draft_id=%s "
            "and (%s::uuid is null or owner_actor_id=%s::uuid)",
            (workspace_id, draft_id, owner_actor_id, owner_actor_id),
        ).fetchone()
    return None if row is None else _draft(row)


def list_drafts(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    owner_actor_id: uuid.UUID,
    limit: int = LISTED,
) -> tuple[CreatureDraft, ...]:
    """A requester's drafts, newest first, at most ``limit``: a reload or a second tab finds one
    still running."""
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            f"select {_COLUMNS} from creature_draft where workspace_id=%s and owner_actor_id=%s "
            "order by created_at desc, draft_id limit %s",
            (workspace_id, owner_actor_id, limit),
        ).fetchall()
    return tuple(_draft(row) for row in rows)


def create_draft(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    offered_to: Collection[uuid.UUID],
    owner_actor_id: uuid.UUID,
    words: str,
    sent: str,
    placeholders: Mapping[Any, str],
) -> CreatureDraft:
    """A new draft and its queued job.

    ``words`` are the person's as typed, held to the line rule and never kept, ``sent`` the same
    words with every saved name replaced and ``placeholders`` the record of those replacements,
    which the job hands the boundary. ``offered_to`` is every workspace a worker here takes
    creature drafts for; a draft for any other is :class:`DraftNotOffered`, so its words are never
    queued for nobody. The workspace's lock is taken first, and a workspace being erased (a
    ``workspace`` tombstone) drafts nothing more (:class:`TombstonedError`): a draft and its
    workspace's tombstone never interleave, so the tombstone either finds the draft committed and
    cancels it, or the draft finds the tombstone and no job holds the words."""
    if workspace_id not in offered_to:
        raise DraftNotOffered("creatures are not drafted for this workspace here")
    check_line(words, maximum=MAX_WORDS_CHARACTERS)
    draft_id = uuid.uuid4()
    payload = {
        "draft_id": str(draft_id),
        "sent": sent,
        "placeholders": {str(entity): label for entity, label in placeholders.items()},
    }
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        lock_workspace(connection, workspace_id)
        if cursor.execute(
            "select 1 from tombstone where workspace_id=%s and scope='workspace' limit 1",
            (workspace_id,),
        ).fetchone():
            raise TombstonedError(
                "tombstoned: the workspace has been deleted and drafts nothing more"
            )
        cursor.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, %s))",
            (f"{workspace_id}:{owner_actor_id}", _REQUESTER_LOCK_SEED),
        )
        counts = cursor.execute(
            "select count(*) filter (where finished_at is null) as open, "
            "count(*) filter (where created_at > now() - interval '1 hour') as hour "
            "from creature_draft where workspace_id=%s and owner_actor_id=%s",
            (workspace_id, owner_actor_id),
        ).fetchone()
        assert counts is not None
        if counts["open"] >= MAX_OPEN_PER_ACTOR or counts["hour"] >= MAX_PER_ACTOR_HOUR:
            raise DraftLimitReached("this requester has as many creature drafts as one may")
        job = cursor.execute(
            "insert into job (workspace_id, kind, payload) values (%s, %s, %s) returning job_id",
            (workspace_id, JOB_KIND, Jsonb(payload)),
        ).fetchone()
        assert job is not None
        row = cursor.execute(
            "insert into creature_draft (workspace_id, draft_id, owner_actor_id, job_id) "
            f"values (%s, %s, %s, %s) returning {_COLUMNS}",
            (workspace_id, draft_id, owner_actor_id, job["job_id"]),
        ).fetchone()
        assert row is not None
    return _draft(row)


@dataclass(frozen=True, slots=True)
class ClaimedDraft:
    """A claimed job and its draft: what the worker needs, and the token every write names. The
    words are left out of the repr, so they never reach a log line by way of one."""

    workspace_id: uuid.UUID
    job_id: uuid.UUID
    claim_token: uuid.UUID
    attempts: int
    draft: CreatureDraft
    sent: str = field(repr=False)
    placeholders: Mapping[uuid.UUID, str] = field(repr=False)


def _fail_orphan(cursor: psycopg.Cursor[Any], job_id: uuid.UUID) -> None:
    """End a creature job that names no draft of its workspace, so it never blocks the queue."""
    cursor.execute(
        "update job set state='failed', lease_expires_at=null, claim_token=null, "
        "completed_at=now(), failure_class='creature_draft_missing', "
        "last_error='the job names no creature draft of its workspace', "
        + _DURATION
        + ", "
        + _BLANKED
        + " where job_id=%s",
        (job_id,),
    )


def claim(
    connection: psycopg.Connection, workspace_id: uuid.UUID, *, worker: str
) -> ClaimedDraft | None:
    """Take the next queued creature job of this workspace, or None when there is none. A job
    naming no draft of its workspace is failed and the next one taken."""
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
                draft_id = uuid.UUID(str(payload["draft_id"]))
                sent = str(payload["sent"])
                placeholders = {
                    uuid.UUID(entity): str(label)
                    for entity, label in payload["placeholders"].items()
                }
            except (AttributeError, KeyError, TypeError, ValueError):
                _fail_orphan(cursor, job["job_id"])
                continue
            row = cursor.execute(
                "update creature_draft set status='running', started_at=coalesce(started_at, "
                "now()) where workspace_id=%s and draft_id=%s "
                f"and job_id=%s and status in ('queued', 'running') returning {_COLUMNS}",
                (workspace_id, draft_id, job["job_id"]),
            ).fetchone()
            if row is None:
                _fail_orphan(cursor, job["job_id"])
                continue
        return ClaimedDraft(
            workspace_id=workspace_id,
            job_id=job["job_id"],
            claim_token=job["claim_token"],
            attempts=int(job["attempts"]),
            draft=_draft(row),
            sent=sent,
            placeholders=placeholders,
        )


def _claim_held(connection: psycopg.Connection, claimed: ClaimedDraft) -> bool:
    """Whether the worker still holds the draft's claim, read without a lock: a draft cancelled
    while it was drafted (its workspace erased) is no longer the worker's to keep."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select 1 as held from job where job_id=%s and claim_token=%s and state='running'",
            (claimed.job_id, claimed.claim_token),
        ).fetchone()
    return row is not None


def _holds(cursor: psycopg.Cursor[Any], claimed: ClaimedDraft) -> bool:
    row = cursor.execute(
        "select 1 from job where job_id=%s and claim_token=%s and state='running' for update",
        (claimed.job_id, claimed.claim_token),
    ).fetchone()
    return row is not None


def finish(
    connection: psycopg.Connection,
    claimed: ClaimedDraft,
    *,
    status: str,
    kind_sha256: str | None = None,
    refusal: tuple[str, str | None] | None = None,
    failure: str | None = None,
    model_id: str | None = None,
) -> bool:
    """End the draft and its job, blanking the words; False when the claim was lost.

    ``kind_sha256`` (the kind document's digest) for a kept creature, ``refusal`` (a code and the
    form's field, or None) for one the checks refused, ``failure`` (a code) for one that could not
    be made."""
    if status not in _ENDS:
        raise ValueError(f"a worker ends a draft as one of {_ENDS}")
    code, where = refusal if refusal is not None else (None, None)
    with connection.transaction(), connection.cursor() as cursor:
        if not _holds(cursor, claimed):
            return False
        cursor.execute(
            "update creature_draft set status=%s, kind_sha256=%s, refusal_code=%s, "
            "refusal_field=%s, failure=%s, model_id=%s, finished_at=now() where workspace_id=%s "
            "and draft_id=%s and status='running'",
            (
                status,
                kind_sha256,
                code,
                where,
                failure,
                model_id,
                claimed.workspace_id,
                claimed.draft.draft_id,
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
                None if failure is None else f"creature_{failure}"[:64],
                claimed.job_id,
                claimed.claim_token,
            ),
        )
    return True


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
        (f"creature_{failure}", error, workspace_id, JOB_KIND),
    ).fetchall()
    for job in jobs:
        cursor.execute(
            "update creature_draft set status='failed', failure=%s, finished_at=now() "
            "where workspace_id=%s and job_id=%s and status in ('queued', 'running')",
            (failure, workspace_id, job["job_id"]),
        )
    return len(jobs)


def abandon_stranded(connection: psycopg.Connection, workspace_id: uuid.UUID) -> int:
    """End every creature job of this workspace stranded :data:`MAXIMUM_CLAIMS` times, and its
    draft as failed, blanking the words. Returns how many were ended."""
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        return _end_jobs(
            cursor,
            workspace_id,
            f"state='running' and lease_expires_at<now() and attempts>={MAXIMUM_CLAIMS}",
            "stranded",
            "claimed every time it was allowed and stranded every time",
        )


def expire_unclaimed(connection: psycopg.Connection, workspace_id: uuid.UUID) -> int:
    """End every creature job of this workspace queued and untaken for
    :data:`QUEUED_EXPIRY_SECONDS`, and its draft as failed (``expired``), blanking the words."""
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        return _end_jobs(
            cursor,
            workspace_id,
            f"state='queued' and created_at < now() - interval '{QUEUED_EXPIRY_SECONDS} seconds'",
            "expired",
            "queued and never taken",
        )


def end_unserved(connection: psycopg.Connection, workspace_id: uuid.UUID) -> int:
    """End every unfinished creature job of a workspace this installation does not serve, and its
    draft as failed (``not_served``), blanking the words."""
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        return _end_jobs(
            cursor,
            workspace_id,
            "state in ('queued', 'running')",
            "not_served",
            "the installation does not draft creatures for this workspace",
        )


class _Database(Protocol):
    def session(self, workspace_id: uuid.UUID) -> AbstractContextManager[psycopg.Connection]: ...


class CreatureDraftWorker:
    """Plays the creature drafts of the workspaces it is given, one at a time per workspace."""

    def __init__(
        self,
        database: _Database,
        *,
        client: ModelClient,
        policy_for: Callable[[uuid.UUID], HostedRequestPolicy],
        looks_for: Callable[[uuid.UUID], ContentAddressedStore],
        workspaces: Callable[[], Iterable[uuid.UUID]],
        worker: str = "creatures",
    ) -> None:
        self._database = database
        self._client = client
        self._policy_for = policy_for
        self._looks_for = looks_for
        self._workspaces = workspaces
        self._worker = worker

    def run(self, stop: threading.Event, *, poll_seconds: float = 1.0) -> None:
        """Play every workspace's creature drafts until ``stop`` is set."""
        while not stop.is_set():
            played = False
            for workspace_id in sorted(self._workspaces()):
                if stop.is_set():
                    return
                try:
                    played = self.run_once(workspace_id) is not None or played
                except Exception as failure:  # one workspace's failure never stops the others
                    _LOG.warning("creature draft failed", extra={"failure": type(failure).__name__})
            if not played:
                stop.wait(poll_seconds)

    def run_once(self, workspace_id: uuid.UUID) -> str | None:
        """Play one claimable draft of ``workspace_id``; its final status, or None."""
        with self._database.session(workspace_id) as connection:
            abandon_stranded(connection, workspace_id)
            expire_unclaimed(connection, workspace_id)
            claimed = claim(connection, workspace_id, worker=self._worker)
        if claimed is None:
            return None
        # Keyed by the job alone: a job taken again replays the same key.
        with spending_request_key(f"creature:{claimed.job_id}"):
            return self._play(claimed)

    def _play(self, claimed: ClaimedDraft) -> str:
        workspace_id = claimed.workspace_id
        client = self._client.with_policy(self._policy_for(workspace_id))
        with self._database.session(workspace_id) as connection:
            taken = frozenset(
                row["key"]
                for row in connection.execute(
                    "select distinct key from thing_kind_version where workspace_id=%s",
                    (workspace_id,),
                ).fetchall()
            )
        status = "failed"
        kind_sha256: str | None = None
        refusal: tuple[str, str | None] | None = None
        failure: str | None = None
        model_id: str | None = None
        try:
            outcome = draft_creature(
                client,
                claimed.sent,
                role=Role.CREATURE_DRAFTER,
                taken=taken,
                placeholders=claimed.placeholders,
                log=CallLog(),
            )
            model_id = outcome.model_id
            if outcome.creature is not None:
                with self._database.session(workspace_id) as connection:
                    # A cancelled draft keeps nothing: its claim is read first, without holding a
                    # lock across the keep, and a keep that races the workspace's tombstone is
                    # refused by the store or erased with the workspace (migration 0161).
                    if not _claim_held(connection, claimed):
                        return "lost"
                    ThingStore(
                        connection, workspace_id, self._looks_for(workspace_id)
                    ).keep_creature(outcome.creature, created_by=claimed.draft.owner_actor_id)
                status = "kept"
                kind_sha256 = outcome.creature.kind.sha256
            else:
                assert outcome.refusal is not None
                check = outcome.refusal.check
                status = "refused"
                # The refusing check's code and the form's field it refused; never its sentence,
                # which may quote the drafted label.
                refusal = (
                    (str(outcome.refusal.code), None)
                    if check is None
                    else (check[0], refusal_field(check[1]))
                )
        except ThingStoreRefused as refused:
            status, refusal = "refused", (refused.code, None)
        except SpendingRefused:
            failure = "spending_refused"
        except HostedRequestRefused:
            failure = "request_refused"
        except ModelError:
            failure = "drafter_unavailable"
        if failure is not None:
            status = "failed"
        if refusal is not None and refusal[0] not in refusal_codes():
            # The lists are closed: a refusal outside them is carried under the drafter's own code.
            refusal = ("creature_not_drafted", None)
        with self._database.session(workspace_id) as connection:
            finished = finish(
                connection,
                claimed,
                status=status,
                kind_sha256=kind_sha256,
                refusal=refusal,
                failure=failure,
                model_id=model_id,
            )
        return status if finished else "lost"
