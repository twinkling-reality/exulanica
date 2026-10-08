"""The reference worker: takes a reference request's job and turns it into a reference bundle.

One job, in steps the page reads as they happen:

1.  **plan**: the planner drafts at most three search subjects from the person's description
    (:func:`exulanica.references.drafting.plan_subjects`), once the source is known to be
    configured, so an unconfigured source costs no model call;
2.  **search**: each subject passes the boundary
    (:func:`~exulanica.references.boundary.admit_query`), is admitted against the source's
    spending (Tavily credits, one call each, through the durable authority) and sent by the
    source's adapter; our record of each search is kept, nothing it returned is;
3.  **read**: the reader drafts notes from what the searches found
    (:func:`~exulanica.references.drafting.read_notes`), and only notes that copy no run of a
    source's words and carry nothing personal are kept
    (:func:`~exulanica.references.notes.keep_notes`);
4.  **read_picture**, once for each of the person's own pictures the request names, before the web
    steps: the picture source hands over the picture's rendition only under a current right for
    the picture role's chain (:class:`~exulanica.references.pictures.ReferencePicture`), one reading
    writes its notes or refuses the picture by reason
    (:func:`~exulanica.references.pictures.read_picture`), and only notes that pass the picture
    checks are kept (:func:`~exulanica.references.pictures.screen_picture_notes`);
5.  **bundle**: the notes become a reference bundle, complete or partial with the steps it missed.

A request that did not ask for web notes skips plan, search and read; one that names no picture has
no picture step. Every step checks the deadline,
whether the person asked to stop and whether the process is shutting down; each model call is given
what is left of the deadline as its own. Past the deadline, or at shutdown, the job ends partial
with what it has, so the person is never left waiting on a source. What the searches returned lives
only in this function's locals and is gone when it returns.

Spending is keyed by the job alone, so a job taken again after a crash is admitted under the same
keys and the authority refuses what already happened rather than paying for it twice. A source whose
reported cost differs from its catalog entry is stopped for the life of this process; the catalog is
reviewed before it is offered again.

The planner and reader calls go through the workspace's own policied client and are charged to
Nebius Token Factory through the durable authority like every model call; each is recorded in the
bundle with its provider, tokens and USD.
"""

from __future__ import annotations

import collections
import dataclasses
import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Protocol

import psycopg

from exulanica.epistemics.saved_names import SavedName, saved_names
from exulanica.errors import ExulanicaError
from exulanica.models.client import ModelClient
from exulanica.models.errors import ModelError
from exulanica.models.policy import HostedRequest, HostedRequestPolicy, HostedRequestRefused
from exulanica.models.results import ChatResult
from exulanica.models.spending import (
    SpendingRefused,
    SpendingRequest,
    SpendingSource,
    SpendingTicket,
    spending_request_key,
)
from exulanica.models.usage import CallUsage, usd_string
from exulanica.references import drafting, store
from exulanica.references.adapters.base import (
    Leads,
    ReferenceAdapter,
    ReferenceSourceUnavailable,
)
from exulanica.references.boundary import SEARCH_ROLE, AdmittedQuery, QueryRefused, admit_query
from exulanica.references.bundle import (
    MAX_NOTES,
    BundleCall,
    BundleNote,
    BundlePicture,
    ReferenceBundle,
)
from exulanica.references.catalogs import ReferenceSource, web_source
from exulanica.references.notes import keep_notes
from exulanica.references.pictures import (
    PICTURE_ROLE,
    REFUSALS,
    PictureRead,
    PictureUnavailable,
    ReferencePicture,
    read_picture,
    screen_picture_notes,
)

__all__ = ["DEADLINE_SECONDS", "PROCESS_RESERVE_PERCENT", "STEPS", "ReferenceWorker"]

_LOG = logging.getLogger(__name__)

#: The longest a request runs before it ends partial with what it has.
DEADLINE_SECONDS: Final = 30.0
STEPS: Final = ("plan", "search", "read", "bundle")
#: A picture step's name: one per picture a request names, each with its capture id.
PICTURE_STEP: Final = "read_picture"
#: The share of the process's model budget (its USD fuse and its call count) reference jobs leave
#: for every other feature: a job starts its planner only while more than this share remains, so a
#: loop of reference requests can never spend the process's fuse down for the Companion or a world.
PROCESS_RESERVE_PERCENT: Final = 50
#: Outcomes of a search that never left: refused before sending, so nothing is recorded of it and
#: no further search is tried. The duplicate refusals are a job taken again after a crash meeting
#: the searches it already made.
_NOT_SENT: Final = frozenset(
    {
        "reference_budget_unavailable",
        "reference_source_rate_limited_here",
        "spending_scope_missing",
        "spending_not_granted",
        "spending_revoked",
        "spending_expired",
        "spending_limit_reached",
        "spending_suspended",
        "spending_unavailable",
        "duplicate_request_in_flight",
        "duplicate_request_unknown",
        "duplicate_request_settled",
    }
)
#: The window the catalog's calls_per_minute is counted over, in this process.
_RATE_WINDOW_SECONDS: Final = 60.0


class _Database(Protocol):
    def session(self, workspace_id: uuid.UUID) -> AbstractContextManager[psycopg.Connection]: ...


class _Stopped(ExulanicaError):
    """The deadline passed, the person asked to stop, the process is shutting down, or the claim
    was lost."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


class _Admitted:
    """The workspace's request policy for one picture's reading. As the reading is sent it also asks
    the picture's own re-check (exactly the rights it was read under still current, no person found
    since), and it notes whether the request carrying the picture went through, so a picture is
    named in the bundle even when no answer came back."""

    def __init__(
        self, policy: HostedRequestPolicy, picture: ReferencePicture, capture_id: uuid.UUID
    ) -> None:
        self._policy = policy
        self._picture = picture
        self._capture_id = capture_id
        self.workspace_id = getattr(policy, "workspace_id", None)
        self.admitted = False

    def admit(self, request: HostedRequest) -> Sequence[str]:
        texts = self._policy.admit(request)
        if self._capture_id in request.photographs:
            try:
                reason = self._picture.recheck()
            except (psycopg.Error, OSError) as failure:
                # The check could not be asked: nothing is sent, and the step is missed.
                _LOG.warning("a picture's send-time check failed: %s", type(failure).__name__)
                reason = "picture_unreadable"
            if reason is not None:
                raise PictureUnavailable(reason)
            self.admitted = True
        return texts


class _Steps:
    """The steps as the page reads them: each waiting, running, done, skipped or missed, and a
    picture step refused with the reason its reading gave."""

    def __init__(self, web: bool, pictures: tuple[uuid.UUID, ...] = ()) -> None:
        self.items: list[dict[str, Any]] = [
            {"step": step, "state": "waiting" if web or step == "bundle" else "skipped"}
            for step in STEPS
        ]
        # Each picture's step sits before the bundle's.
        self.items[-1:-1] = [
            {"step": PICTURE_STEP, "capture_id": str(picture), "state": "waiting"}
            for picture in pictures
        ]

    def picture(self, capture_id: uuid.UUID, state: str, **facts: Any) -> None:
        for item in self.items:
            if item["step"] == PICTURE_STEP and item["capture_id"] == str(capture_id):
                item.clear()
                item.update(
                    {"step": PICTURE_STEP, "capture_id": str(capture_id), "state": state, **facts}
                )

    def set(self, step: str, state: str, **facts: Any) -> None:
        for item in self.items:
            if item["step"] == step:
                item.clear()
                item.update({"step": step, "state": state, **facts})

    def miss_the_rest(self, reason: str) -> None:
        for item in self.items:
            if item["state"] in ("waiting", "running") and item["step"] != "bundle":
                item.update(state="missed", reason=reason)

    def missed(self) -> tuple[str, ...]:
        missed = [
            item["step"]
            for item in self.items
            if item["state"] == "missed" and item["step"] in ("plan", "search", "read")
        ]
        if any(item["step"] == PICTURE_STEP and item["state"] == "missed" for item in self.items):
            missed.append("pictures")
        return tuple(missed)


def _call(call: ChatResult) -> BundleCall:
    usage: CallUsage = call.usage
    return BundleCall(
        provider=usage.provider,
        role=str(usage.role),
        model_id=usage.model_id,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        usd=usd_string(usage.usd),
    )


def _reason(failure: BaseException) -> str:
    """A missed step's reason, as a code: never the failure's own words."""
    if isinstance(failure, SpendingRefused):
        return failure.reason
    if isinstance(failure, HostedRequestRefused):
        return "policy_refused"
    if isinstance(failure, ModelError):
        return "model_unavailable"
    return "failed"


@dataclasses.dataclass(frozen=True, slots=True)
class _Reserved:
    """A search's admitted spending, held until the search is dispatched or released."""

    gate: Any
    ticket: SpendingTicket


class _Rate:
    """The catalog's calls_per_minute for one source, counted in this process."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._sent: dict[str, collections.deque[float]] = {}
        self._lock = threading.Lock()

    def take(self, source: ReferenceSource) -> bool:
        now = self._clock()
        with self._lock:
            sent = self._sent.setdefault(source.key, collections.deque())
            while sent and now - sent[0] >= _RATE_WINDOW_SECONDS:
                sent.popleft()
            if len(sent) >= source.calls_per_minute:
                return False
            sent.append(now)
            return True


class ReferenceWorker:
    """Plays the reference jobs of the workspaces it is given, one at a time per workspace."""

    def __init__(
        self,
        database: _Database,
        *,
        client: ModelClient,
        policy_for: Callable[[uuid.UUID], HostedRequestPolicy],
        spending: SpendingSource | None,
        adapter_for: Callable[[ReferenceSource], ReferenceAdapter],
        workspaces: Callable[[], Iterable[uuid.UUID]],
        picture_source: Callable[[uuid.UUID, uuid.UUID, uuid.UUID, datetime], ReferencePicture]
        | None = None,
        worker: str = "references",
        deadline_seconds: float = DEADLINE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        stop: threading.Event | None = None,
    ) -> None:
        self._database = database
        self._client = client
        self._policy_for = policy_for
        self._spending = spending
        self._adapter_for = adapter_for
        self._workspaces = workspaces
        #: A person's own picture by workspace and capture, or a refusal by code; None where no
        #: picture is read in this process.
        self._picture_source = picture_source
        self._worker = worker
        self._deadline_seconds = deadline_seconds
        self._clock = clock
        self._stop = stop if stop is not None else threading.Event()
        self._rate = _Rate(clock)
        #: Sources stopped for the life of this process, with the reason.
        self._stopped: dict[str, str] = {}

    def run(self, stop: threading.Event, *, poll_seconds: float = 1.0) -> None:
        """Play every workspace's reference jobs until ``stop`` is set; a job in progress ends
        partial at its next step once it is."""
        self._stop = stop
        while not stop.is_set():
            played = False
            for workspace_id in sorted(self._workspaces()):
                if stop.is_set():
                    return
                try:
                    played = self.run_once(workspace_id) is not None or played
                except Exception as failure:  # one workspace's failure never stops the others
                    _LOG.warning("reference job failed", extra={"failure": type(failure).__name__})
            if not played:
                stop.wait(poll_seconds)

    def run_once(self, workspace_id: uuid.UUID) -> str | None:
        """Play one claimable job of ``workspace_id``; its request's final status, or None."""
        with self._database.session(workspace_id) as connection:
            store.abandon_stranded(connection, workspace_id)
            store.expire_unclaimed(connection, workspace_id)
            claimed = store.claim(connection, workspace_id, worker=self._worker)
        if claimed is None:
            return None
        # Keyed by the job alone: a job taken again replays the same keys.
        with spending_request_key(f"reference:{claimed.job_id}"):
            return self._play(claimed)

    def _remaining(self, started: float) -> float:
        return self._deadline_seconds - (self._clock() - started)

    def _check(self, claimed: store.ClaimedRequest, steps: _Steps, started: float) -> None:
        if self._stop.is_set():
            raise _Stopped("shutdown")
        if self._remaining(started) <= 0:
            raise _Stopped("deadline")
        with self._database.session(claimed.workspace_id) as connection:
            if not store.record_steps(connection, claimed, steps.items):
                raise _Stopped("claim_lost")
            if store.cancel_requested(connection, claimed):
                raise _Stopped("cancelled")

    def _play(self, claimed: store.ClaimedRequest) -> str:
        started = self._clock()
        request = claimed.request
        steps = _Steps(request.web, claimed.pictures)
        calls: list[BundleCall] = []
        notes: list[BundleNote] = []
        lookups: list[uuid.UUID] = []
        pictures: list[BundlePicture] = []
        try:
            names = self._saved_names(claimed)
            for capture_id in claimed.pictures:
                self._picture(claimed, steps, calls, notes, pictures, started, capture_id, names)
            if request.web:
                self._web(claimed, steps, calls, notes, lookups, started)
        except _Stopped as stopped:
            if stopped.why == "claim_lost":
                return "claim_lost"
            if stopped.why == "cancelled":
                return self._finish(claimed, steps, status="cancelled")
            # The deadline or a shutdown: what is done stands, and the rest is missed.
            steps.miss_the_rest(stopped.why)
        missed = steps.missed()
        status = "partial" if missed else "complete"
        steps.set("bundle", "done", notes=len(notes))
        bundle = ReferenceBundle(
            purpose=request.purpose,
            workspace_id=claimed.workspace_id,
            world_id=None,
            notes=tuple(notes[:MAX_NOTES]),
            lookups=tuple(lookups),
            pictures=tuple(pictures),
            model_calls=tuple(calls),
            outcome=status,
            missed=missed,
        )
        return self._finish(
            claimed,
            steps,
            status=status,
            bundle=bundle.document(),
            bundle_sha256=bundle.digest,
        )

    def _picture(
        self,
        claimed: store.ClaimedRequest,
        steps: _Steps,
        calls: list[BundleCall],
        notes: list[BundleNote],
        pictures: list[BundlePicture],
        started: float,
        capture_id: uuid.UUID,
        names: tuple[SavedName, ...] | None,
    ) -> None:
        """Read one of the person's own pictures into notes, or say why not. ``names`` are the
        workspace's saved names, read before any picture is sent; None when they could not be."""
        self._check(claimed, steps, started)
        if self._picture_source is None:
            steps.picture(capture_id, "missed", reason="pictures_not_read_here")
            return
        if names is None:
            steps.picture(capture_id, "missed", reason="saved_names_unread")
            return
        if not self._process_has_room():
            steps.picture(capture_id, "missed", reason="process_budget_spent")
            return
        steps.picture(capture_id, "running")
        try:
            picture = self._picture_source(
                claimed.workspace_id,
                capture_id,
                claimed.request.owner_actor_id,
                claimed.request.created_at,
            )
        except PictureUnavailable as unavailable:
            # A person the product already found is the reader's own refusal, made before sending.
            state = "refused" if unavailable.reason in REFUSALS else "missed"
            steps.picture(capture_id, state, reason=unavailable.reason)
            return
        except Exception as failure:  # any other failure is a step the job missed
            _LOG.warning("a picture could not be read: %s", type(failure).__name__)
            steps.picture(capture_id, "missed", reason="picture_unreadable")
            return
        policy = _Admitted(self._policy_for(claimed.workspace_id), picture, capture_id)
        client = self._client.with_policy(policy)
        try:
            read = read_picture(
                client, picture.image, capture_id=capture_id, deadline_s=self._remaining(started)
            )
        except PictureUnavailable as unavailable:
            # Refused as it was being sent: nothing went, so the bundle does not name it.
            state = "refused" if unavailable.reason in REFUSALS else "missed"
            steps.picture(capture_id, state, reason=unavailable.reason)
            return
        except (ModelError, SpendingRefused, ExulanicaError) as failure:
            read = PictureRead(refused=_reason(failure))
        if read.call is not None:
            calls.append(_call(read.call))
        if read.call is not None or policy.admitted:
            # Named once the workspace's policy let it through, whatever the reading answered, and
            # by the role's model when no answer came back to say which one read it.
            model = (
                (read.call.usage.provider, str(PICTURE_ROLE), read.call.usage.model_id)
                if read.call is not None
                else self._picture_model()
            )
            pictures.append(BundlePicture(capture_id, picture.right_ids, model))
        if read.refused in REFUSALS:
            steps.picture(capture_id, "refused", reason=read.refused)
            return
        if read.refused is not None:
            steps.picture(capture_id, "missed", reason=read.refused)
            return
        screened = screen_picture_notes(
            read.notes, withheld_words=claimed.withheld_words, saved=names
        )
        notes.extend(
            BundleNote(note.aspect, note.text, "own_picture", capture_id) for note in screened.kept
        )
        steps.picture(
            capture_id, "done", kept=len(screened.kept), dropped=sum(screened.dropped.values())
        )

    def _saved_names(self, claimed: store.ClaimedRequest) -> tuple[SavedName, ...] | None:
        """The workspace's saved names, read once before any picture is sent, or None when they
        could not be read (each picture is then a missed step, and nothing is sent)."""
        if not claimed.pictures or self._picture_source is None:
            return ()
        try:
            with self._database.session(claimed.workspace_id) as connection:
                return saved_names(connection, claimed.workspace_id)
        except (psycopg.Error, OSError) as failure:
            _LOG.warning("saved names could not be read: %s", type(failure).__name__)
            return None

    def _picture_model(self) -> tuple[str, str, str]:
        """The picture role's model as the manifest names it: the provider and its primary."""
        binding = self._client.manifest[PICTURE_ROLE]
        return (binding.primary.provider, str(PICTURE_ROLE), binding.primary.model_id)

    def _finish(self, claimed: store.ClaimedRequest, steps: _Steps, **outcome: Any) -> str:
        with self._database.session(claimed.workspace_id) as connection:
            ended = store.finish(connection, claimed, steps=steps.items, **outcome)
        return "claim_lost" if ended is None else ended

    def _source(self, source: ReferenceSource) -> tuple[ReferenceAdapter | None, str | None]:
        """The source's adapter, or why it is not offered now (stopped here or not configured)."""
        if source.key in self._stopped:
            return None, self._stopped[source.key]
        if self._spending is None:
            return None, "reference_budget_unavailable"
        try:
            return self._adapter_for(source), None
        except ReferenceSourceUnavailable as failure:
            return None, failure.code

    def _web(
        self,
        claimed: store.ClaimedRequest,
        steps: _Steps,
        calls: list[BundleCall],
        notes: list[BundleNote],
        lookups: list[uuid.UUID],
        started: float,
    ) -> None:
        source = web_source()
        if source is None:
            steps.set("plan", "missed", reason="source_unavailable")
            steps.set("search", "missed", reason="references_not_configured")
            steps.set("read", "missed", reason="nothing_found")
            return
        adapter, unavailable = self._source(source)
        if adapter is None:
            steps.set("plan", "missed", reason="source_unavailable")
            steps.set("search", "missed", reason=unavailable)
            steps.set("read", "missed", reason="nothing_found")
            return
        try:
            self._with_adapter(claimed, steps, calls, notes, lookups, started, source, adapter)
        finally:
            adapter.close()

    def _with_adapter(
        self,
        claimed: store.ClaimedRequest,
        steps: _Steps,
        calls: list[BundleCall],
        notes: list[BundleNote],
        lookups: list[uuid.UUID],
        started: float,
        source: ReferenceSource,
        adapter: ReferenceAdapter,
    ) -> None:
        # Everything that could refuse a search is asked before the planner is paid: the process's
        # share of its model budget, the source's rate here, and the workspace's grant for it, by
        # admitting the first search now.
        if not self._process_has_room():
            steps.set("plan", "missed", reason="process_budget_spent")
            steps.set("search", "missed", reason="nothing_planned")
            steps.set("read", "missed", reason="nothing_planned")
            return
        first, refusal = self._reserve(claimed, source, 0)
        if first is None:
            steps.set("plan", "missed", reason="source_unavailable")
            steps.set("search", "missed", reason=refusal)
            steps.set("read", "missed", reason="nothing_found")
            return
        pending: list[_Reserved] = [first]
        try:
            self._plan_search_read(
                claimed, steps, calls, notes, lookups, started, source, adapter, pending
            )
        finally:
            for reserved in pending:
                self._release(reserved.gate, reserved.ticket)

    def _process_has_room(self) -> bool:
        budget = self._client.budget
        keep_usd = budget.ceiling_usd * PROCESS_RESERVE_PERCENT / 100
        keep_calls = budget.max_calls * PROCESS_RESERVE_PERCENT // 100
        # Two calls: the planner and the reader.
        return (
            budget.ceiling_usd - budget.spent_usd - keep_usd > 0
            and budget.max_calls - budget.billed_calls - keep_calls >= 2
        )

    def _plan_search_read(
        self,
        claimed: store.ClaimedRequest,
        steps: _Steps,
        calls: list[BundleCall],
        notes: list[BundleNote],
        lookups: list[uuid.UUID],
        started: float,
        source: ReferenceSource,
        adapter: ReferenceAdapter,
        pending: list[_Reserved],
    ) -> None:
        policy = self._policy_for(claimed.workspace_id)
        client = self._client.with_policy(policy)

        steps.set("plan", "running")
        self._check(claimed, steps, started)
        try:
            planned = drafting.plan_subjects(
                client,
                claimed.description,
                purpose=claimed.request.purpose,
                deadline_s=self._remaining(started),
            )
        except (ModelError, SpendingRefused, ExulanicaError) as failure:
            planned = drafting.Drafted(refused=_reason(failure))
        if planned.call is not None:
            calls.append(_call(planned.call))
        if planned.refused is not None:
            steps.set("plan", "missed", reason=planned.refused)
            steps.set("search", "missed", reason="nothing_planned")
            steps.set("read", "missed", reason="nothing_planned")
            return
        steps.set("plan", "done", subjects=len(planned.subjects))

        queries: list[AdmittedQuery] = []
        refused = 0
        for subject in planned.subjects:
            try:
                queries.append(
                    admit_query(
                        subject,
                        source=source,
                        policy=policy,
                        withheld_words=claimed.withheld_words,
                    )
                )
            except QueryRefused:
                refused += 1
        steps.set("search", "running", sent=0, of=len(queries), withheld=refused)
        leads: list[Leads] = []
        unavailable: str | None = None
        for index, query in enumerate(queries):
            self._check(claimed, steps, started)
            reserved = pending.pop() if index == 0 and pending else None
            outcome, credits, count, provider_id, lead = self._search(
                claimed, source, adapter, query, index, reserved
            )
            if outcome in _NOT_SENT:
                unavailable = outcome
                break
            with self._database.session(claimed.workspace_id) as connection:
                lookups.append(
                    store.record_lookup(
                        connection,
                        claimed,
                        source=source.key,
                        aspect=query.aspect,
                        query=query.text,
                        outcome=outcome,
                        credits=credits,
                        result_count=count,
                        provider_request_id=provider_id,
                    )
                )
            if lead is not None:
                leads.append(lead)
            else:
                unavailable = outcome
                if outcome == "reference_cost_changed":
                    break
            steps.set("search", "running", sent=len(lookups), of=len(queries), withheld=refused)
        if not leads:
            steps.set("search", "missed", reason=unavailable or "nothing_admitted", of=len(queries))
            steps.set("read", "missed", reason="nothing_found")
            return
        steps.set("search", "done", sent=len(lookups), found=len(leads), withheld=refused)

        steps.set("read", "running")
        self._check(claimed, steps, started)
        try:
            read = drafting.read_notes(client, leads, deadline_s=self._remaining(started))
        except (ModelError, SpendingRefused, ExulanicaError) as failure:
            read = drafting.Drafted(refused=_reason(failure))
        if read.call is not None:
            calls.append(_call(read.call))
        if read.refused is not None:
            steps.set("read", "missed", reason=read.refused)
            return
        screened = keep_notes(
            read.notes,
            # The queries too: a note that repeats one carries what was asked, not what was found.
            sources=[
                text
                for lead in leads
                for text in (lead.query.text, *lead.passages, *lead.picture_descriptions)
            ],
            withheld_words=claimed.withheld_words,
        )
        steps.set("read", "done", kept=len(screened.kept), dropped=sum(screened.dropped.values()))
        notes.extend(
            BundleNote(note.aspect, note.text, "web_description", None) for note in screened.kept
        )

    def _reserve(
        self, claimed: store.ClaimedRequest, source: ReferenceSource, index: int
    ) -> tuple[_Reserved | None, str | None]:
        """A search's rate slot taken and its spending admitted (not yet dispatched), or why not."""
        if self._spending is None:
            return None, "reference_budget_unavailable"
        if not self._rate.take(source):
            return None, "reference_source_rate_limited_here"
        gate = self._spending.for_workspace(claimed.workspace_id)
        try:
            ticket = gate.admit(
                SpendingRequest(
                    provider=source.key,
                    model_id=source.key,
                    role=SEARCH_ROLE,
                    usd=Decimal(0),
                    key=f"reference:{claimed.job_id}:search:{index}",
                )
            )
        except SpendingRefused as refusal:
            return None, refusal.reason
        return _Reserved(gate, ticket), None

    def _settle(self, gate: Any, ticket: SpendingTicket, usage: CallUsage) -> None:
        """Settle as the model chain does: a settlement the authority could not take leaves the
        reservation held, the conservative side, and never ends the job."""
        try:
            gate.settle(ticket, usage)
        except Exception as failure:
            _LOG.warning(
                "the durable settlement of a reference search failed; its reservation stays held",
                extra={"failure": type(failure).__name__},
            )

    def _release(self, gate: Any, ticket: SpendingTicket) -> None:
        try:
            gate.release(ticket)
        except Exception as failure:
            _LOG.warning(
                "the release of a reference search's reservation failed",
                extra={"failure": type(failure).__name__},
            )

    def _search(
        self,
        claimed: store.ClaimedRequest,
        source: ReferenceSource,
        adapter: ReferenceAdapter,
        query: AdmittedQuery,
        index: int,
        reserved: _Reserved | None = None,
    ) -> tuple[str, int, int, str | None, Leads | None]:
        """One search, admitted against the source's spending: outcome, credits, results, id."""
        if reserved is None:
            reserved, refusal = self._reserve(claimed, source, index)
            if reserved is None:
                return refusal or "reference_budget_unavailable", 0, 0, None, None
        gate, ticket = reserved.gate, reserved.ticket
        try:
            gate.dispatch(ticket)
        except SpendingRefused as refusal:
            self._release(gate, ticket)
            return refusal.reason, 0, 0, None, None
        except BaseException:
            self._release(gate, ticket)
            raise
        usage = CallUsage(
            role=SEARCH_ROLE,
            model_id=source.key,
            provider=source.key,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
            cached_prompt_tokens=0,
            usd=Decimal(0),
        )
        try:
            lead = adapter.search(query)
        except ReferenceSourceUnavailable as failure:
            if failure.charged:
                self._settle(gate, ticket, usage)
            else:
                self._release(gate, ticket)
            if failure.code == "reference_cost_changed":
                self._stopped[source.key] = failure.code
            if failure.credits is not None:
                credits = failure.credits
            else:
                credits = source.cost_per_call if failure.charged else 0
            return failure.code, credits, 0, None, None
        except BaseException:
            self._settle(gate, ticket, usage)
            raise
        self._settle(gate, ticket, usage)
        return "answered", lead.credits, lead.result_count, lead.request_id, lead
