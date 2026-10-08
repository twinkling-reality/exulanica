"""A kind of world drafted from a person's words, as a job the page polls.

``POST /worlds/kinds/drafts`` admits the words on the request's thread (the model credential, the
workspace's allowance and its cap on kinds, the person's starts this hour, saved names replaced)
and starts a job here; ``GET /worlds/kinds/drafts/{draft_id}`` reads the job's state, for the person
who started it only. No route waits on the model. The job drafts with
:func:`~exulanica.selection.kind_drafting.draft_kind` on the ``kind_drafter`` role, holds each
drafted kind to both stages of the kind checks in the kind worker as a creator's upload is held,
and keeps a passing kind in the workspace, origin ``drafted``, with its provenance and never the
words.

The words are held only while the draft runs: a draft that ends forgets them, as a reference
request does. The state lives in this API process, which a deployment runs one of for drafting, or
routes each person to one of (``docs/deployment.md`` section 5.4). A ready draft's result is the
kept kind itself, which outlives the process; a draft's ended state is answered for
:data:`KEEP_SECONDS`. A draft still running when the process stops is lost, and what it had spent
stands: the page then reads ``kind_draft_unknown`` and offers to start again.
"""

from __future__ import annotations

import dataclasses
import functools
import logging
import math
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Literal

import psycopg

from exulanica.models.client import ModelClient
from exulanica.models.errors import BudgetExceededError, ModelError
from exulanica.models.manifest import load_manifest
from exulanica.models.spending import SpendingRefused
from exulanica.selection.calls import CallLog, ModelCall
from exulanica.selection.kind_drafting import (
    DRAFT_ATTEMPTS,
    DRAFTER_ROLE,
    KindVerdict,
    draft_kind,
    kind_drafting_prompt,
    render_instructions,
)
from exulanica.spending.status import SpendingRefusals
from exulanica.world.kinds.catalogs import load_kind_catalogs
from exulanica.world.kinds.document import KindRefused, read_kind
from exulanica.world.kinds.library import shipped_kinds
from exulanica.world.kinds.repository import KindCapReached, KindVersionExists, WorkspaceKinds
from exulanica.world.kinds.worker import CHECK_SECONDS, check_job, check_key, kind_worker

__all__ = [
    "KEEP_SECONDS",
    "KIND_DRAFT_CODES",
    "SERVER_DRAFTS",
    "STARTS_PER_HOUR",
    "KindDraft",
    "KindDraftBusy",
    "KindDraftCapacity",
    "KindDraftLimit",
    "KindDrafts",
    "allowance_refusal",
    "attempt_floor_usd",
    "draft_deadline_seconds",
    "run_draft",
]

_LOG = logging.getLogger(__name__)

State = Literal["drafting", "ready", "refused"]

#: How long a draft's ended state is answered after it ended, and the window a person's starts
#: are counted in.
KEEP_SECONDS: Final = 3600.0
#: Drafts running at once in this process. Each holds a thread while the model reasons, a call of
#: up to the role's timeout; two keep the process's other work and its spend rate in reach.
SERVER_DRAFTS: Final = 2
#: Drafts one workspace may have running at once.
WORKSPACE_DRAFTS: Final = 1
#: Drafts one person may start in an hour, as reference requests are bounded: a few tries at
#: describing a place, never a loop.
STARTS_PER_HOUR: Final = 12
#: How long past its deadline a draft still drafting is ended as failed: the margin the kind
#: worker's own bound and a slow database take beyond it.
STALE_MARGIN_SECONDS: Final = 120.0
#: The longest a kind's key may be (the kind document's pattern) and how many keys a draft tries
#: for one the workspace does not hold.
_KEY_MAXIMUM: Final = 32
_KEY_TRIES: Final = 99
_FAILED: Final = {
    "code": "kind_draft_failed",
    "detail": "The draft stopped before a kind was made. Start it again.",
}


#: Every code a draft's routes and its job answer with, and what it means: a closed list the page
#: keeps one words table for. A kind's own refusals while it is checked are the kind checks' codes
#: (``KIND_CODES``), which a refused draft names as its last check.
KIND_DRAFT_CODES: Final = (
    (
        "not_authorised",
        "This credential may not draft: drafting needs world.write and model.invoke.",
    ),
    ("provider_credential_absent", "This server holds no model credential to draft with."),
    ("budget_exceeded", "The workspace's allowance for the drafting model is spent."),
    ("kind_cap_reached", "The workspace already keeps as many kinds of place as it may."),
    ("kind_draft_busy", "The workspace already has a kind of place being drafted."),
    ("kind_draft_limit", "This person has started as many drafts this hour as they may."),
    ("kind_draft_capacity", "The server is drafting as many kinds of place as it may."),
    ("kind_draft_unknown", "The server holds no draft this person started with this id."),
    ("unknown_reference", "This credential may not read drafts here: reading needs world.read."),
    ("kind_not_drafted", "No kind of place people can live, walk and work in was drafted."),
    ("kind_draft_unanswered", "The model did not answer in time."),
    ("kind_work_unavailable", "The server could not check the drafted kind of place."),
    ("kind_draft_failed", "The draft stopped before a kind of place was made."),
    ("kind_version_exists", "The workspace already keeps this kind of place."),
)


def draft_deadline_seconds(client: ModelClient | None = None) -> float:
    """The longest a draft takes: each attempt's call, as long as the longest the client drafting
    can take for the role (its timeouts and retries; the role's timeout without a client), and its
    checks."""
    call = (
        load_manifest()[DRAFTER_ROLE].timeout_seconds
        if client is None
        else client.worst_case_seconds(DRAFTER_ROLE)
    )
    return DRAFT_ATTEMPTS * (call + CHECK_SECONDS)


@functools.cache
def _instructions_characters() -> int:
    from exulanica.world.society_living import town_routine

    return len(render_instructions(kind_drafting_prompt(), load_kind_catalogs(), town_routine()))


def attempt_floor_usd(client: ModelClient) -> dict[str, Decimal]:
    """By provider, the least one attempt of the drafter role reserves: its answer bound and its
    instructions at its model's prices. The description, the form and the repairs are not counted,
    so an allowance below it admits no attempt, and one above it may still meet a ceiling."""
    role = load_manifest()[DRAFTER_ROLE]
    answer = 0 if role.max_tokens is None else role.max_tokens.value
    floors: dict[str, Decimal] = {}
    for spec in role.chain:
        usd = client.budget.estimate_usd(
            spec, prompt_chars=_instructions_characters(), max_tokens=answer
        )
        floors[spec.provider] = min(usd, floors.get(spec.provider, usd))
    return floors


def allowance_refusal(
    refusals: SpendingRefusals | None, client: ModelClient
) -> SpendingRefused | None:
    """The refusal a draft's first attempt would meet from the durable authority, before it is
    started: a drafter provider's own refusal, or its remaining USD below one attempt's floor
    (:func:`attempt_floor_usd`), which admission refuses though the allowance is not spent to zero
    (as a society's model minds are read). None in a process no durable authority admits."""
    if refusals is None:
        return None
    for provider, floor in sorted(attempt_floor_usd(client).items()):
        refused = refusals.by_provider.get(provider)
        if refused is not None:
            return refused
        remainder = refusals.available_usd.get(provider)
        if remainder is not None and remainder < floor:
            return SpendingRefused(
                "spending_limit_reached", scope="workspace", detail="usd", requested=str(floor)
            )
    return None


class KindDraftBusy(Exception):
    """The workspace already has a draft running; only the person who started it is told its id."""

    def __init__(self, draft_id: uuid.UUID, actor: uuid.UUID) -> None:
        super().__init__("a kind is already being drafted in this workspace")
        self.draft_id = draft_id
        self.actor = actor


class KindDraftCapacity(Exception):
    """The process already runs as many drafts as it may."""


class KindDraftLimit(Exception):
    """The person has started as many drafts this hour as they may."""

    def __init__(self, retry_seconds: int) -> None:
        super().__init__("as many drafts as one person may start in an hour were started")
        self.retry_seconds = retry_seconds


@dataclass
class KindDraft:
    """One draft's state, as its job left it last. ``description`` is empty once it has ended."""

    draft_id: uuid.UUID
    workspace_id: uuid.UUID
    actor: uuid.UUID
    description: str
    started_at: datetime
    started: float
    state: State = "drafting"
    changed: float = 0.0
    kind: str | None = None
    version: int | None = None
    refusal: Mapping[str, Any] | None = None
    calls: tuple[ModelCall, ...] = ()
    model_id: str | None = None
    #: The longest this draft takes (:func:`draft_deadline_seconds` of its client), where known.
    deadline: float | None = None


@dataclass
class KindDrafts:
    """Every draft this process holds, by id, and the threads that run them."""

    clock: Callable[[], float] = time.monotonic
    per_server: int = SERVER_DRAFTS
    per_workspace: int = WORKSPACE_DRAFTS
    starts_per_hour: int = STARTS_PER_HOUR
    keep_seconds: float = KEEP_SECONDS
    deadline_seconds: Callable[[], float] = draft_deadline_seconds
    _drafts: dict[uuid.UUID, KindDraft] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _closing: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def closing(self) -> bool:
        """Whether the server is stopping: a draft then starts no more checks."""
        return self._closing.is_set()

    def close(self) -> None:
        """Called as the server stops, before the kind worker closes."""
        self._closing.set()

    def refusal(self, workspace_id: uuid.UUID, actor: uuid.UUID) -> str | None:
        """Why this person may not start a draft here now, or None: the workspace's running draft
        or the person's starts this hour. The server's capacity changes from moment to moment and
        is answered when a draft starts."""
        with self._lock:
            now = self.clock()
            self._forget(now)
            if self._busy(workspace_id) is not None:
                return "kind_draft_busy"
            if self._retry(actor, now) is not None:
                return "kind_draft_limit"
        return None

    def start(
        self,
        workspace_id: uuid.UUID,
        actor: uuid.UUID,
        description: str,
        job: Callable[[KindDraft, KindDrafts], None],
        *,
        deadline: float | None = None,
    ) -> KindDraft:
        """Start ``job`` on a thread of its own for a new draft, or refuse while the workspace,
        the person or the process already runs or started as many as it may."""
        with self._lock:
            now = self.clock()
            self._forget(now)
            busy = self._busy(workspace_id)
            if busy is not None:
                raise KindDraftBusy(busy.draft_id, busy.actor)
            retry = self._retry(actor, now)
            if retry is not None:
                raise KindDraftLimit(retry)
            if sum(draft.state == "drafting" for draft in self._drafts.values()) >= self.per_server:
                raise KindDraftCapacity()
            draft = KindDraft(
                draft_id=uuid.uuid4(),
                workspace_id=workspace_id,
                actor=actor,
                description=description,
                started_at=datetime.now(UTC),
                started=now,
                changed=now,
                deadline=deadline,
            )
            self._drafts[draft.draft_id] = draft
            snapshot = dataclasses.replace(draft)
        # A daemon: a draft still running when the process stops is lost, never waited for.
        thread = threading.Thread(
            target=self._run, args=(draft, job), name=f"kind-draft-{draft.draft_id}", daemon=True
        )
        try:
            thread.start()
        except RuntimeError as failed:
            # No thread to run it on: the draft never started and holds no place.
            with self._lock:
                self._drafts.pop(draft.draft_id, None)
            raise KindDraftCapacity() from failed
        return snapshot

    def read(
        self, workspace_id: uuid.UUID, actor: uuid.UUID, draft_id: uuid.UUID
    ) -> KindDraft | None:
        """The draft's state, or None for an id this process holds for nobody here to read: one
        another person started, one of another workspace, or none."""
        with self._lock:
            self._forget(self.clock())
            draft = self._drafts.get(draft_id)
            if draft is None or draft.workspace_id != workspace_id or draft.actor != actor:
                return None
            return dataclasses.replace(draft)

    def listing(self, workspace_id: uuid.UUID, actor: uuid.UUID) -> tuple[KindDraft, ...]:
        """The drafts one person started in one workspace that this process still holds, newest
        first: so a reload, a second tab or a return finds a draft still running."""
        with self._lock:
            self._forget(self.clock())
            mine = [
                dataclasses.replace(draft)
                for draft in self._drafts.values()
                if draft.workspace_id == workspace_id and draft.actor == actor
            ]
        return tuple(sorted(mine, key=lambda draft: draft.started, reverse=True))

    def finish(self, draft: KindDraft, **fields: Any) -> None:
        """Set what the job found, once, and forget the words: a draft that ended stays as it
        ended and keeps nothing a person typed."""
        with self._lock:
            if draft.state != "drafting":
                return
            for name, value in fields.items():
                setattr(draft, name, value)
            draft.description = ""
            draft.changed = self.clock()
            self._forget(draft.changed)

    def _run(self, draft: KindDraft, job: Callable[[KindDraft, KindDrafts], None]) -> None:
        try:
            job(draft, self)
        except Exception as failed:  # the job's own refusals are states; anything else is named
            _LOG.warning("a kind draft failed: %s", type(failed).__qualname__)
            self.finish(draft, state="refused", refusal=dict(_FAILED))
        finally:
            # A job that returned without saying how it ended has refused nothing it could name.
            self.finish(draft, state="refused", refusal=dict(_FAILED))

    def _busy(self, workspace_id: uuid.UUID) -> KindDraft | None:
        running = [
            draft
            for draft in self._drafts.values()
            if draft.workspace_id == workspace_id and draft.state == "drafting"
        ]
        return running[0] if len(running) >= self.per_workspace else None

    def _retry(self, actor: uuid.UUID, now: float) -> int | None:
        """Whole seconds until the person may start again, or None while they may now."""
        starts = sorted(
            draft.started
            for draft in self._drafts.values()
            if draft.actor == actor and now - draft.started < self.keep_seconds
        )
        if len(starts) < self.starts_per_hour:
            return None
        return max(1, math.ceil(starts[-self.starts_per_hour] + self.keep_seconds - now))

    def _forget(self, now: float) -> None:
        """End as failed a draft still drafting well past its deadline (a job that can no longer
        finish), and drop drafts that ended over :attr:`keep_seconds` ago. A draft is kept while it
        counts toward its person's starts, which are counted from when it started."""
        fallback = self.deadline_seconds()
        for draft_id, draft in list(self._drafts.items()):
            if draft.state == "drafting":
                deadline = fallback if draft.deadline is None else draft.deadline
                # Ended without its calls: the job's own log is out of reach here.
                if now - draft.started > deadline + STALE_MARGIN_SECONDS:
                    draft.state, draft.refusal = "refused", dict(_FAILED)
                    draft.description, draft.changed = "", now
            elif now - draft.changed > self.keep_seconds:
                del self._drafts[draft_id]


Opener = Callable[[], AbstractContextManager[psycopg.Connection]]


def _free_key(opened: Opener, workspace_id: uuid.UUID) -> Callable[[str], str]:
    """A kind's key the workspace keeps no kind under, whether it reads or not, and the product
    ships none under: the key the brief states, or that key with the first number free after it."""

    def key_for(stated: str) -> str:
        with opened() as connection:
            taken = set(WorkspaceKinds(connection, workspace_id).kind_keys())
        taken |= {kind.kind for kind in shipped_kinds()} | {"town"}
        if stated not in taken:
            return stated
        for number in range(2, _KEY_TRIES + 1):
            suffix = f"_{number}"
            key = f"{stated[: _KEY_MAXIMUM - len(suffix)]}{suffix}"
            if key not in taken:
                return key
        raise KindRefused("kind_document_invalid", "no key is free for this kind", "kind")

    return key_for


class _ChecksUnavailable(Exception):
    """The kind worker could not check a drafted kind: the server's state, never the model's."""


def _checked(
    workspace_id: uuid.UUID, drafts: KindDrafts
) -> Callable[[dict[str, Any]], KindVerdict]:
    """Both stages of the kind checks, stage B in the kind worker, as an upload is checked."""

    # The worker as the draft starts: once its server closes it, it starts no process again.
    worker = kind_worker()

    def check(document: dict[str, Any]) -> KindVerdict:
        try:
            kind = read_kind(document)
        except KindRefused as refused:
            return KindVerdict(False, code=refused.code, where=refused.where, detail=refused.detail)
        if drafts.closing:
            # The server is stopping and its kind worker with it.
            raise _ChecksUnavailable("closing")
        outcome = worker.run(
            check_key(str(workspace_id), kind.sha256),
            CHECK_SECONDS,
            check_job,
            dict(kind.document),
            workspace=str(workspace_id),
            kept=worker.checks,
        )
        if outcome.status != "done" or outcome.value is None:
            # A refusal here would be told to the model as its own; the draft stops instead.
            raise _ChecksUnavailable(outcome.status)
        answer = outcome.value
        if answer["status"] == "refused":
            return KindVerdict(
                False, code=answer["code"], where=answer["where"], detail=answer["detail"]
            )
        return KindVerdict(True, kind, answer["report"])

    return check


def run_draft(
    draft: KindDraft,
    drafts: KindDrafts,
    *,
    client: ModelClient,
    opened: Opener,
    readable: Opener,
    actor: uuid.UUID,
    text: str,
    placeholders: Mapping[Any, str],
) -> None:
    """Draft a kind of ``text`` (the words as sent, every saved name replaced), check it and keep
    it, leaving the draft ``ready`` with the kept kind or ``refused`` by name, with every call it
    made either way.

    ``opened`` opens a connection scoped to the draft's workspace that may write, ``readable``
    one that reads; neither is held while the model runs."""
    workspace_id = draft.workspace_id
    log = CallLog()

    def refused(refusal: Mapping[str, Any]) -> None:
        drafts.finish(draft, state="refused", refusal=dict(refusal), calls=log.calls)

    try:
        outcome = draft_kind(
            client.with_attempts(log.attempt),
            text,
            role=DRAFTER_ROLE,
            check=_checked(workspace_id, drafts),
            placeholders=placeholders,
            log=log,
            key_for=_free_key(readable, workspace_id),
        )
    except BudgetExceededError as spent:
        # Asked before ModelError, which it is: a spent allowance is not a model's silence.
        refusal: dict[str, Any] = {
            "code": "budget_exceeded",
            "detail": "This server's own spending limit for models is reached.",
        }
        if isinstance(spent, SpendingRefused):
            # The authority's own sentence: spent, not granted, revoked, expired, suspended or
            # unavailable, with no other workspace's figures.
            refusal["detail"] = str(spent)
            refusal["spending"] = spent.problem_member()
        refused(refusal)
        return
    except ModelError:
        refused(
            {
                "code": "kind_draft_unanswered",
                "detail": "The model did not answer in time. Try again in a moment.",
            }
        )
        return
    except _ChecksUnavailable:
        refused(
            {
                "code": "kind_work_unavailable",
                "detail": "The server could not check the drafted kind. Try again in a moment.",
            }
        )
        return
    except (KindRefused, psycopg.Error):
        # No free key, or the database while a key was chosen: after calls that were paid for.
        refused(_FAILED)
        return
    except Exception as failed:  # anything else, named by its type, still shows what it cost
        _LOG.warning("a kind draft failed: %s", type(failed).__qualname__)
        refused(_FAILED)
        return
    if outcome.document is None or outcome.kind is None or outcome.report is None:
        last = outcome.refusal
        check = None if last is None else last.check
        refused(
            {
                "code": "kind_not_drafted" if last is None else str(last.code.value),
                # The last check's own sentence, which the page shows after its own words.
                "detail": "" if last is None else (last.sentence or last.detail),
                "check": None if check is None else check[0],
                "where": None if check is None else check[1],
            }
        )
        return
    try:
        with opened() as connection:
            kept = WorkspaceKinds(connection, workspace_id).append(
                outcome.kind, outcome.report, created_by=actor
            )
    except (KindCapReached, KindVersionExists) as stopped:
        refused({"code": stopped.code, "detail": str(stopped)})
        return
    except Exception as failed:  # the database or anything else, after paid calls
        _LOG.warning("a kind draft could not be kept: %s", type(failed).__qualname__)
        refused(_FAILED)
        return
    drafts.finish(
        draft,
        state="ready",
        kind=kept.kind.kind,
        version=kept.kind.version,
        calls=log.calls,
        model_id=outcome.model_id,
    )
