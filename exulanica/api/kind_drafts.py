"""A kind of world drafted from a person's words, as a job the page polls.

``POST /worlds/kinds/drafts`` admits the words on the request's thread (the model credential, the
workspace's allowance and its cap on kinds, the person's starts this hour, saved names replaced)
and starts a job here; ``GET /worlds/kinds/drafts/{draft_id}`` reads the job's state, for the person
who started it only. No route waits on the model. The job drafts with
:func:`~exulanica.selection.kind_drafting.draft_kind` on the ``kind_drafter`` role, holds each
drafted kind to both stages of the kind checks in the kind worker as a creator's upload is held,
and keeps a passing kind in the workspace, origin ``drafted``, with its provenance and never the
words.

The words are held only while the draft runs. Native kind routes use the durable repository and
worker; this holder supplies bounded local execution capacity and remains a transient runner for
pure callers. Kind and whole-world workers enter it after shared database admission. Their jobs
retain identity and outcomes across process replacement without automatically repeating uncertain
paid work. Ended native-kind views are retained for :data:`KEEP_SECONDS`.

"""

from __future__ import annotations

import dataclasses
import functools
import logging
import math
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Literal, Protocol

import psycopg

from exulanica.models.client import ModelClient
from exulanica.models.errors import BudgetExceededError, ModelError, TransportError
from exulanica.models.manifest import load_manifest
from exulanica.models.spending import SpendingRefused
from exulanica.selection.calls import CallLog, ModelCall
from exulanica.selection.kind_drafting import (
    DRAFT_ATTEMPTS,
    DRAFTER_ROLE,
    KindDraftOutcome,
    KindVerdict,
    draft_kind,
    kind_drafting_prompt,
    render_instructions,
)
from exulanica.spending.status import SpendingRefusals
from exulanica.world.draft_policy import current_world_draft_policy
from exulanica.world.kinds.catalogs import load_kind_catalogs
from exulanica.world.kinds.document import KindRefused, read_kind
from exulanica.world.kinds.library import shipped_kinds
from exulanica.world.kinds.repository import KindCapReached, KindVersionExists, WorkspaceKinds
from exulanica.world.kinds.worker import CHECK_SECONDS, check_job, check_key, kind_worker

__all__ = [
    "KEEP_SECONDS",
    "KINDS_FROM_PEOPLE_NOT_OFFERED",
    "KINDS_FROM_PEOPLE_NOT_OFFERED_DETAIL",
    "KIND_DRAFT_CODES",
    "DraftAllowance",
    "KindDraft",
    "KindDraftBusy",
    "KindDraftCapacity",
    "KindDraftLimit",
    "KindDrafts",
    "Opener",
    "allowance_refusal",
    "attempt_floor_usd",
    "draft_deadline_seconds",
    "drafted_kind",
    "run_draft",
]

_LOG = logging.getLogger(__name__)

State = Literal["drafting", "ready", "refused"]
Purpose = Literal["kind", "world"]

#: How long a draft's ended state is answered after it ended, and the window a person's starts
#: are counted in.
KEEP_SECONDS: Final = 3600.0
#: How many drafts run at once in this process and in one workspace, and how many one person may
#: start in :data:`KEEP_SECONDS`, are chosen budgets of the world draft policy
#: (:mod:`exulanica.world.draft_policy`), each with its reason and a deployment's own figure in the
#: variable the policy names. They are read when a draft is asked for, never bound here.
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
#: Why a server refuses to take a kind of place from a person, drafted from their words or
#: written by them: its deployment has not stated that it keeps one
#: (``EXULANICA_KINDS_FROM_PEOPLE``).
KINDS_FROM_PEOPLE_NOT_OFFERED: Final = "kinds_from_people_not_offered"
#: What a person is told there, by every route that would keep one (answered 403).
KINDS_FROM_PEOPLE_NOT_OFFERED_DETAIL: Final = (
    "This server keeps no kind of place from a person, drafted from their words or written by "
    "them: its deployment has not turned that on."
)

KIND_DRAFT_CODES: Final = (
    (
        KINDS_FROM_PEOPLE_NOT_OFFERED,
        "This server keeps no kind of place from a person, drafted from their words or written "
        "by them.",
    ),
    (
        "not_authorised",
        "This credential may not draft: drafting needs world.write and model.invoke.",
    ),
    ("provider_credential_absent", "This server holds no model credential to draft with."),
    ("budget_exceeded", "The workspace's allowance for the drafting model is spent."),
    ("spending_suspended", "Spending on models is held closed here until an operator acts."),
    ("kind_cap_reached", "The workspace already keeps as many kinds of place as it may."),
    ("kind_draft_busy", "The workspace already has a kind of place being drafted."),
    ("kind_draft_limit", "This person has started as many drafts this hour as they may."),
    ("kind_draft_capacity", "The server is drafting as many kinds of place as it may."),
    ("kind_draft_unknown", "The server holds no draft this person started with this id."),
    ("unknown_reference", "This credential may not read drafts here: reading needs world.read."),
    ("kind_not_drafted", "No kind of place people can live, walk and work in was drafted."),
    ("kind_draft_unanswered", "The model did not answer in time."),
    ("kind_draft_ran_on", "The model's answer ran on past what a kind of place can hold."),
    (
        "kind_draft_model_failed",
        "The model's provider failed or refused the call, or could not be reached.",
    ),
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

    prompt = kind_drafting_prompt()
    catalogs = load_kind_catalogs(bounds_version=2 if prompt.version >= 7 else 1)
    return len(render_instructions(prompt, catalogs, town_routine()))


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


def budget_refusal(spent: BudgetExceededError) -> dict[str, Any]:
    """A draft the model budget ended, as its refusal: the process's own fuse by its own sentence;
    the durable authority's by its code (``spending_suspended`` while it is held closed), its own
    sentence (spent, not granted, revoked, expired, suspended or unavailable) and its ``spending``
    member, with no other workspace's figures."""
    refusal: dict[str, Any] = {
        "code": "budget_exceeded",
        "detail": "This server's own spending limit for models is reached.",
    }
    if isinstance(spent, SpendingRefused):
        refusal.update(code=spent.problem_code, detail=str(spent), spending=spent.problem_member())
    return refusal


class KindDraftBusy(Exception):
    """The workspace already has a draft running; only the person who started it is told its id,
    and only by the routes of its own purpose, which are the ones that read it."""

    def __init__(self, draft_id: uuid.UUID, actor: uuid.UUID, purpose: Purpose = "kind") -> None:
        super().__init__("a draft is already running in this workspace")
        self.draft_id = draft_id
        self.actor = actor
        self.purpose = purpose

    def told_to(self, actor: uuid.UUID, purpose: Purpose) -> dict[str, str]:
        """The running draft's id as a problem's member for the person who started it asking
        through the routes that read it, and nothing for anybody else: its words are theirs, and
        an id the asking routes answer 404 for helps nobody."""
        mine = self.actor == actor and self.purpose == purpose
        return {"draft_id": str(self.draft_id)} if mine else {}


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
    #: What the draft is of: a kind of place to keep (``kind``), or a whole world made from a
    #: sentence (``world``, :mod:`exulanica.api.world_making`). Each is read and listed by its own
    #: routes; both count toward the same budgets, since both hold a thread and spend.
    purpose: Purpose = "kind"
    #: For a world: the step its job is at while it drafts (``choosing``, ``drafting``,
    #: ``making``), the tool taken and whether a model chose it, the saved entry made, each part
    #: that was made and the phrases of the description that were left out.
    stage: str | None = None
    tool: str | None = None
    tool_chosen: bool | None = None
    entry_id: uuid.UUID | None = None
    made: tuple[Mapping[str, Any], ...] = ()
    left_out: tuple[str, ...] = ()
    #: For a world: the look and the parts of a setting the words asked for and the job took,
    #: each with the person's own words that chose it; None where none was taken.
    look: Mapping[str, Any] | None = None
    setting: Mapping[str, Any] | None = None
    #: For a world made on land: the recipe it stands on and what chose it (the person's own
    #: words, its setting or the default), and whether its layout did not fit and it was made on
    #: level ground instead; None where it was made on level ground as asked.
    land: Mapping[str, Any] | None = None
    #: For a world started with web notes: whether its drafter was handed them, as the
    #: specification route's ``references`` says it; None where the start named none.
    references: Mapping[str, Any] | None = None
    #: Content erased with the resulting world; timing remains for the starts-per-hour budget.
    erased: bool = False


@dataclass(frozen=True, slots=True)
class DraftAllowance:
    """What of the draft budgets one person has left in one workspace, now."""

    #: The draft running in the workspace, whoever started it and whatever its purpose, or None.
    running: KindDraft | None
    #: How many drafts this person may start in an hour, and how many of those are left.
    starts_an_hour: int
    starts_left: int
    #: Whole seconds until a start frees, where none is left; None while one is.
    retry_seconds: int | None


@dataclass
class KindDrafts:
    """Every draft this process holds, by id, and the threads that run them."""

    clock: Callable[[], float] = time.monotonic
    #: Each of the three budgets as this holder was told it, or None for the policy's figure,
    #: which is read at each ask so a deployment's variable is the figure in force.
    per_server: int | None = None
    per_workspace: int | None = None
    starts_per_hour: int | None = None
    keep_seconds: float = KEEP_SECONDS
    deadline_seconds: Callable[[], float] = draft_deadline_seconds
    _drafts: dict[uuid.UUID, KindDraft] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _closing: threading.Event = field(default_factory=threading.Event, repr=False)
    _reserved: int = field(default=0, repr=False)
    _erased_entries: set[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=set, repr=False)
    _active_worlds: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict, repr=False)

    @property
    def closing(self) -> bool:
        """Whether the server is stopping: a draft then starts no more checks."""
        return self._closing.is_set()

    def close(self) -> None:
        """Called as the server stops, before the kind worker closes."""
        self._closing.set()

    def _budget(self, told: int | None, budget: str, *, guest: bool = False) -> int:
        return current_world_draft_policy().figure(budget, guest=guest) if told is None else told

    @contextmanager
    def kind_start_count(self, actor: uuid.UUID) -> Iterator[int]:
        """Actor-wide native kind starts in the window, including erased timing.

        Hold the native admission lock until durable world admission finishes, so another kind
        start in this process cannot change the sampled count. Kind start timing remains local
        to this holder; durable world starts are counted by the database, never counted here.
        """
        with self._lock:
            now = self.clock()
            self._forget(now)
            yield sum(
                draft.actor == actor
                and draft.purpose == "kind"
                and now - draft.started < self.keep_seconds
                for draft in self._drafts.values()
            )

    def refusal(
        self, workspace_id: uuid.UUID, actor: uuid.UUID, *, guest: bool = False
    ) -> str | None:
        """Why this person may not start a draft here now, or None: the workspace's running draft
        or the person's starts this hour, a guest's by a guest's figure. The server's capacity
        changes from moment to moment and is answered when a draft starts."""
        with self._lock:
            now = self.clock()
            self._forget(now)
            if self._busy(workspace_id) is not None:
                return "kind_draft_busy"
            if self._retry(actor, now, guest) is not None:
                return "kind_draft_limit"
        return None

    def allowance(
        self, workspace_id: uuid.UUID, actor: uuid.UUID, *, guest: bool = False
    ) -> DraftAllowance:
        """What a start would meet now, read before anything is typed: the workspace's running
        draft and this person's starts this hour, a guest's by a guest's figure. The server's
        capacity changes from moment to moment and is answered when a draft starts."""
        with self._lock:
            now = self.clock()
            self._forget(now)
            busy = self._busy(workspace_id)
            most = self._budget(self.starts_per_hour, "starts_an_hour", guest=guest)
            started = sum(
                draft.actor == actor and now - draft.started < self.keep_seconds
                for draft in self._drafts.values()
            )
            return DraftAllowance(
                running=None if busy is None else dataclasses.replace(busy),
                starts_an_hour=most,
                starts_left=max(0, most - started),
                retry_seconds=self._retry(actor, now, guest),
            )

    @contextmanager
    def execution_slot(self) -> Iterator[None]:
        """Reserve only this process's capacity before claiming durable work."""
        with self._lock:
            self._forget(self.clock())
            active = sum(d.state == "drafting" for d in self._drafts.values())
            if self.closing or active + self._reserved >= self._budget(
                self.per_server, "drafts_at_once"
            ):
                raise KindDraftCapacity()
            self._reserved += 1
        try:
            yield
        finally:
            with self._lock:
                self._reserved -= 1

    def start(
        self,
        workspace_id: uuid.UUID,
        actor: uuid.UUID,
        description: str,
        job: Callable[[KindDraft, KindDrafts], None],
        *,
        deadline: float | None = None,
        guest: bool = False,
        purpose: Purpose = "kind",
        identity: uuid.UUID | None = None,
        admitted: bool = False,
        reserved: bool = False,
    ) -> KindDraft:
        """Start ``job`` on a thread of its own for a new draft, or refuse while the workspace,
        the person (a guest by a guest's figure) or the process already runs or started as many
        as it may."""
        if identity is not None and purpose != "world" and not admitted:
            raise ValueError("only a durably admitted draft supplies its identity")
        with self._lock:
            now = self.clock()
            self._forget(now)
            busy = None if admitted else self._busy(workspace_id)
            if busy is not None:
                raise KindDraftBusy(busy.draft_id, busy.actor, busy.purpose)
            retry = None if admitted else self._retry(actor, now, guest)
            if retry is not None:
                raise KindDraftLimit(retry)
            at_once = self._budget(self.per_server, "drafts_at_once")
            if (
                not reserved
                and sum(draft.state == "drafting" for draft in self._drafts.values())
                + self._reserved
                >= at_once
            ):
                raise KindDraftCapacity()
            draft = KindDraft(
                draft_id=identity or uuid.uuid4(),
                workspace_id=workspace_id,
                actor=actor,
                description=description,
                started_at=datetime.now(UTC),
                started=now,
                changed=now,
                deadline=deadline,
                purpose=purpose,
            )
            self._drafts[draft.draft_id] = draft
            if purpose == "world":
                self._active_worlds[draft.draft_id] = workspace_id
            snapshot = dataclasses.replace(draft)
        # A daemon holds only local execution state. Durable jobs retain identity and recover
        # under their recorded lease; transient callers retain only this process record.
        thread = threading.Thread(
            target=self._run, args=(draft, job), name=f"kind-draft-{draft.draft_id}", daemon=True
        )
        try:
            thread.start()
        except RuntimeError as failed:
            # No thread to run it on: the draft never started and holds no place.
            with self._lock:
                self._drafts.pop(draft.draft_id, None)
                self._active_worlds.pop(draft.draft_id, None)
                self._trim_erased_entries()
            raise KindDraftCapacity() from failed
        return snapshot

    def read(
        self,
        workspace_id: uuid.UUID,
        actor: uuid.UUID,
        draft_id: uuid.UUID,
        *,
        purpose: Purpose = "kind",
    ) -> KindDraft | None:
        """The draft's state, or None for an id this process holds for nobody here to read: one
        another person started, one of another workspace, one of another purpose, or none."""
        with self._lock:
            self._forget(self.clock())
            draft = self._drafts.get(draft_id)
            if (
                draft is None
                or draft.erased
                or draft.workspace_id != workspace_id
                or draft.actor != actor
                or draft.purpose != purpose
            ):
                return None
            return dataclasses.replace(draft)

    def listing(
        self, workspace_id: uuid.UUID, actor: uuid.UUID, *, purpose: Purpose = "kind"
    ) -> tuple[KindDraft, ...]:
        """The drafts of one purpose one person started in one workspace that this process still
        holds, newest first: so a reload, a second tab or a return finds a draft still running."""
        with self._lock:
            self._forget(self.clock())
            mine = [
                dataclasses.replace(draft)
                for draft in self._drafts.values()
                if draft.workspace_id == workspace_id
                and not draft.erased
                and draft.actor == actor
                and draft.purpose == purpose
            ]
        return tuple(sorted(mine, key=lambda draft: draft.started, reverse=True))

    def advance(self, draft: KindDraft, **fields: Any) -> None:
        """Say where a draft still running has got to (its stage, the tool taken): read by its
        polls, and never a way to end it or to change one that has ended."""
        with self._lock:
            if draft.erased or draft.state != "drafting":
                return
            for name, value in fields.items():
                setattr(draft, name, value)
            draft.changed = self.clock()

    def finish(self, draft: KindDraft, **fields: Any) -> None:
        """Set what the job found, once, and forget the words: a draft that ended stays as it
        ended and keeps nothing a person typed."""
        with self._lock:
            if draft.erased or draft.state != "drafting":
                return
            for name, value in fields.items():
                setattr(draft, name, value)
            draft.description = ""
            draft.changed = self.clock()
            self._forget(draft.changed)

    def made(self, draft: KindDraft, **fields: Any) -> None:
        """End a draft ``ready`` because what it was asked for now exists, whatever it was said to
        be meanwhile: a job that outlived the bound it is ended as failed by has still made its
        world, and a person is never told to say again what is already theirs."""
        with self._lock:
            entry_id = fields.get("entry_id", draft.entry_id)
            if draft.erased or (draft.workspace_id, entry_id) in self._erased_entries:
                self._erase_content(draft)
                return
            if draft.state == "ready":
                return
            for name, value in fields.items():
                setattr(draft, name, value)
            draft.state, draft.refusal = "ready", None
            draft.description = ""
            draft.changed = self.clock()
            self._forget(draft.changed)

    @staticmethod
    def _erase_content(draft: KindDraft) -> None:
        """Discard content in place, including a job's reference to this same draft object."""
        draft.erased = True
        draft.state = "refused"
        draft.description = ""
        draft.kind = draft.version = draft.entry_id = None
        draft.refusal = draft.model_id = None
        draft.stage = draft.tool = draft.tool_chosen = None
        draft.calls = draft.made = draft.left_out = ()
        draft.look = draft.setting = draft.land = None

    def erase_kind(self, workspace_id: uuid.UUID, kind: str, version: int) -> None:
        """Scrub a removed kind's drafts, including the gap between commit and finish."""
        with self._lock:
            for draft in self._drafts.values():
                if (
                    draft.workspace_id == workspace_id
                    and draft.purpose == "kind"
                    and draft.kind == kind
                    and draft.version == version
                ):
                    self._erase_content(draft)

    def erase_entries(self, workspace_id: uuid.UUID, entry_ids: set[uuid.UUID]) -> None:
        """Forget removed worlds' draft content without refunding their start allowance.

        Entry identities remain only while an in-flight world draft could report a result.
        This also covers a world removed after its database commit but before ``made`` runs.
        Other processes must check saved-entry existence before serving their local draft.
        """
        with self._lock:
            self._erased_entries.update((workspace_id, entry_id) for entry_id in entry_ids)
            for draft in self._drafts.values():
                if draft.workspace_id == workspace_id and draft.entry_id in entry_ids:
                    self._erase_content(draft)
            self._trim_erased_entries()
            self._forget(self.clock())

    def _trim_erased_entries(self) -> None:
        active = set(self._active_worlds.values())
        self._erased_entries.intersection_update(
            item for item in self._erased_entries if item[0] in active
        )

    def _run(self, draft: KindDraft, job: Callable[[KindDraft, KindDrafts], None]) -> None:
        try:
            job(draft, self)
        except Exception as failed:  # the job's own refusals are states; anything else is named
            _LOG.warning("a kind draft failed: %s", type(failed).__qualname__)
            self.finish(draft, state="refused", refusal=dict(_FAILED))
        finally:
            # A job that returned without saying how it ended has refused nothing it could name.
            self.finish(draft, state="refused", refusal=dict(_FAILED))
            with self._lock:
                self._active_worlds.pop(draft.draft_id, None)
                self._trim_erased_entries()

    def _busy(self, workspace_id: uuid.UUID) -> KindDraft | None:
        running = [
            draft
            for draft in self._drafts.values()
            if draft.workspace_id == workspace_id and draft.state == "drafting"
        ]
        at_once = self._budget(self.per_workspace, "workspace_drafts_at_once")
        return running[0] if len(running) >= at_once else None

    def _retry(self, actor: uuid.UUID, now: float, guest: bool = False) -> int | None:
        """Whole seconds until the person may start again, or None while they may now."""
        most = self._budget(self.starts_per_hour, "starts_an_hour", guest=guest)
        starts = sorted(
            draft.started
            for draft in self._drafts.values()
            if draft.actor == actor and now - draft.started < self.keep_seconds
        )
        if len(starts) < most:
            return None
        return max(1, math.ceil(starts[-most] + self.keep_seconds - now))

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


class DraftRecorder(Protocol):
    @property
    def closing(self) -> bool: ...

    def finish(self, draft: KindDraft, **fields: Any) -> None: ...


def _checked(
    workspace_id: uuid.UUID, drafts: DraftRecorder
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


def drafted_kind(
    draft: KindDraft,
    drafts: DraftRecorder,
    *,
    client: ModelClient,
    text: str,
    placeholders: Mapping[Any, str],
    log: CallLog,
    key_for: Callable[[str], str] | None,
) -> KindDraftOutcome | None:
    """Draft a kind of ``text`` and hold it to both stages of the checks: the outcome with its
    checked kind, or None after the draft was ended ``refused`` by name with every call it made.
    ``key_for`` chooses the kind's key before the checks, for a kind that will be kept; a world
    made from a sentence keeps no kind and gives none."""
    workspace_id = draft.workspace_id

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
            key_for=key_for,
        )
    except BudgetExceededError as spent:
        # Asked before ModelError, which it is: a spent allowance is not a model's silence.
        refused(budget_refusal(spent))
        return None
    except ModelError as failed:
        if isinstance(failed, TransportError) and (failed.timed_out or failed.deadline_ended):
            refused(
                {
                    "code": "kind_draft_unanswered",
                    "detail": "The model did not answer in time. Try again in a moment.",
                }
            )
        else:
            # A provider's error status, a connection that failed, or a call refused before it
            # was sent: not a model's silence, so not said as one. Logged by its class and the
            # status line alone (never the provider's body, which may quote what was sent), so
            # a drafter every call refuses is seen in the log.
            _LOG.warning(
                "the kind drafter's call failed: %s: %s",
                type(failed).__qualname__,
                str(failed).split(":", 1)[0],
            )
            refused(
                {
                    "code": "kind_draft_model_failed",
                    "detail": (
                        "The model's provider failed or refused the call, or could not be "
                        "reached. Try again in a moment."
                    ),
                }
            )
        return None
    except _ChecksUnavailable:
        refused(
            {
                "code": "kind_work_unavailable",
                "detail": "The server could not check the drafted kind. Try again in a moment.",
            }
        )
        return None
    except (KindRefused, psycopg.Error):
        # No free key, or the database while a key was chosen: after calls that were paid for.
        refused(_FAILED)
        return None
    except Exception as failed:  # anything else, named by its type, still shows what it cost
        _LOG.warning("a kind draft failed: %s", type(failed).__qualname__)
        refused(_FAILED)
        return None
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
        return None
    return outcome


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

    outcome = drafted_kind(
        draft,
        drafts,
        client=client,
        text=text,
        placeholders=placeholders,
        log=log,
        key_for=_free_key(readable, workspace_id),
    )
    if outcome is None or outcome.kind is None or outcome.report is None:
        return
    # Publish identity before commit so erasure can scrub even before finish records ready.
    drafts.advance(draft, kind=outcome.kind.kind, version=outcome.kind.version)
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
