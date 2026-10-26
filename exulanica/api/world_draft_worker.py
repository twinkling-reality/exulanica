"""The normal world maker, run through durable claims and the existing native draft slots."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager, suppress
from decimal import Decimal
from typing import Any

import psycopg

from exulanica.api.kind_drafts import (
    KindDraft,
    KindDraftBusy,
    KindDraftCapacity,
    KindDraftLimit,
    KindDrafts,
)
from exulanica.api.world_making import draft_notes, make_world
from exulanica.canonical import canonical_json
from exulanica.db.session import Database
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Manifest, Role
from exulanica.models.provider_catalog import ProviderPrice
from exulanica.models.spending import (
    SpendingRefused,
    SpendingRequest,
    SpendingTicket,
    spending_request_key,
)
from exulanica.models.usage import CallUsage
from exulanica.selection.calls import admitted_model_call
from exulanica.selection.world_drafting import sendable
from exulanica.world.workspace_model_bindings import _document
from exulanica.world.world_draft_contract import (
    OUTCOME_PROFILE,
    funding_of,
    reference_of,
    validate_definition,
)
from exulanica.world.world_draft_jobs import ClaimedDraft, WorldDraftRefused, WorldDraftRepository

_LOG = logging.getLogger(__name__)

FIELDS = (
    "state",
    "stage",
    "tool",
    "tool_chosen",
    "entry_id",
    "made",
    "left_out",
    "look",
    "setting",
    "land",
    "refusal",
    "model_id",
    "calls",
)


def snapshot(draft: KindDraft, *, manifest: Manifest | None = None) -> dict[str, Any]:
    doc = {key: _document(getattr(draft, key)) for key in FIELDS}
    # Kept only where the start named web notes, so a draft made from its words alone keeps the
    # document it had before notes could be named.
    if draft.references is not None:
        doc["references"] = _document(draft.references)
    doc["entry_id"] = None if draft.entry_id is None else str(draft.entry_id)
    doc["profile"] = OUTCOME_PROFILE
    if manifest is not None:
        calls = tuple(admitted_model_call(call, manifest) for call in draft.calls)
        doc["calls"] = [_document(call) for call in calls]
        if draft.model_id is not None and not any(
            call.served_model == draft.model_id for call in calls
        ):
            doc["model_id"] = None
    return doc


def manifest_sha256(client: ModelClient) -> str:
    return hashlib.sha256(canonical_json(_document(client.manifest))).hexdigest()


def limits(quote: Mapping[str, Any]) -> dict[Role, tuple[int, int]]:
    """Each stage's request bound and answer bound, as its quote priced them: the stage's request
    envelope where the quote states one, else (a quote priced before envelopes) its models' least
    context, as that quote was priced."""
    contexts = {(p["provider"], p["model_id"]): p["input_tokens_at_most"] for p in quote["prices"]}
    return {
        Role(stage["role"]): (
            stage.get("request_bytes_at_most")
            or min(contexts[m["provider"], m["model_id"]] for m in stage["models"]),
            stage["answer_tokens_at_most"],
        )
        for path in quote["paths"]
        for stage in path["stages"]
    }


def prices_of(quote: Mapping[str, Any]) -> dict[tuple[str, str], ProviderPrice]:
    return {
        (p["provider"], p["model_id"]): ProviderPrice(
            p["model_id"],
            Decimal(p["input_usd_per_mtok"]),
            Decimal(p["output_usd_per_mtok"]),
            p["input_tokens_at_most"],
            p["rate_response_sha256"],
        )
        for p in quote["prices"]
    }


class DraftSpending:
    """Every retry/fallback uses its own native reservation inside one accepted total."""

    def __init__(
        self, worker: WorldDraftWorker, claimed: ClaimedDraft, bounds: Mapping[str, uuid.UUID]
    ) -> None:
        self.worker, self.claimed = worker, claimed
        self.gates = {
            p: worker.spending.for_workspace(claimed.workspace_id).within(b)
            for p, b in bounds.items()
        }
        quote = claimed.definition["quote"]
        self.reservations = {
            (s["role"], m["provider"], m["model_id"]): Decimal(m["reservation_usd"])
            for path in quote["paths"]
            for s in path["stages"]
            for m in s["models"]
        }
        self.tickets = {}
        self.price_at = 0.0

    def _prices(self) -> None:
        if time.monotonic() - self.price_at < 30:
            return
        quoted = prices_of(self.claimed.definition["quote"])
        for provider in self.gates:
            actual = self.worker.client.provider_prices(provider)
            for (p, ident), price in quoted.items():
                if p != provider:
                    continue
                current = actual.get(ident)
                if (
                    current is None
                    or current.input_usd_per_mtok != price.input_usd_per_mtok
                    or current.output_usd_per_mtok != price.output_usd_per_mtok
                    or current.context_window_tokens < price.context_window_tokens
                ):
                    raise SpendingRefused(
                        "spending_unavailable", detail="world_draft_price_changed"
                    )
        self.price_at = time.monotonic()

    def admit(self, request: SpendingRequest) -> SpendingTicket:
        self._prices()
        cap = self.reservations.get((request.role, request.provider, request.model_id))
        if cap is None or request.usd > cap:
            raise SpendingRefused(
                "spending_unavailable", detail="world_draft_request_limit_exceeded"
            )
        gate = self.gates[request.provider]
        ticket = gate.admit(
            SpendingRequest(request.provider, request.model_id, request.role, cap, request.key)
        )
        self.tickets[ticket.reservation_id] = gate
        return ticket

    def dispatch(self, ticket: SpendingTicket) -> None:
        def guard(connection: psycopg.Connection) -> None:
            repo = WorldDraftRepository(connection, self.claimed.workspace_id)
            try:
                repo.require_claim(self.claimed)
                repo.attempt(
                    self.claimed,
                    dict(
                        kind="dispatch_authorized",
                        reservation_id=str(ticket.reservation_id),
                        reservation_usd=str(ticket.usd),
                        key=ticket.key,
                    ),
                )
            except WorldDraftRefused as failure:
                raise SpendingRefused("spending_revoked", detail=failure.code) from failure

        self.tickets[ticket.reservation_id].dispatch(ticket, guard=guard)

    def settle(self, ticket: SpendingTicket, usage: CallUsage) -> None:
        self.tickets[ticket.reservation_id].settle(ticket, usage)
        try:
            with self.worker.database.session(self.claimed.workspace_id) as connection:
                WorldDraftRepository(connection, self.claimed.workspace_id).attempt(
                    self.claimed,
                    dict(
                        kind="settled",
                        reservation_id=str(ticket.reservation_id),
                        reservation_usd=str(ticket.usd),
                        accounting=usage.as_cost_json(),
                    ),
                )
        except WorldDraftRefused:
            # Financial settlement remains authoritative after cancellation/lease loss.
            pass

    def release(self, ticket: SpendingTicket) -> None:
        self.tickets[ticket.reservation_id].release(ticket)


class Recorder:
    def __init__(self, worker: WorldDraftWorker, claimed: ClaimedDraft, holder: KindDrafts) -> None:
        self.worker, self.claimed, self.holder = worker, claimed, holder

    @property
    def closing(self) -> bool:
        return self.holder.closing

    def _record(self, draft: KindDraft) -> None:
        with self.worker.database.session(self.claimed.workspace_id) as connection:
            repo = WorldDraftRepository(connection, self.claimed.workspace_id)
            if draft.state == "drafting":
                repo.progress(self.claimed, snapshot(draft, manifest=self.worker.client.manifest))
            else:
                repo.finish(self.claimed, snapshot(draft, manifest=self.worker.client.manifest))

    def advance(self, draft: KindDraft, **fields: Any) -> None:
        self.holder.advance(draft, **fields)
        self._record(draft)

    def finish(self, draft: KindDraft, **fields: Any) -> None:
        self.holder.finish(draft, **fields)
        self._record(draft)

    def made(self, draft: KindDraft, **fields: Any) -> None:
        self.holder.made(draft, **fields)
        self._record(draft)


class WorldDraftWorker:
    def __init__(
        self,
        database: Database,
        *,
        client: ModelClient,
        spending: Any,
        holder: KindDrafts,
        store: Any,
        policy_for: Callable,
        workspaces: Callable[[], Iterable[uuid.UUID]],
        on_land: bool = False,
    ) -> None:
        self.database, self.client, self.spending = database, client, spending
        #: Whether a place made from a sentence stands on land (``EXULANICA_WORLDS_ON_LAND``).
        self.on_land = on_land
        self.holder, self.store, self.policy_for, self.workspaces = (
            holder,
            store,
            policy_for,
            workspaces,
        )
        self._watched: set[uuid.UUID] = set()
        self._lock = threading.Lock()
        self._wake = threading.Event()

    def notify(self, workspace_id: uuid.UUID) -> None:
        with self._lock:
            self._watched.add(workspace_id)
        self._wake.set()

    def close_due(self, workspace_id: uuid.UUID) -> None:
        with self.database.session(workspace_id) as connection:
            due = WorldDraftRepository(connection, workspace_id).close_due()
        for row in due:
            self.spending.close_bound(
                workspace_id, row["bound_id"], reason="The world draft ended."
            )
            with self.database.session(workspace_id) as connection:
                WorldDraftRepository(connection, workspace_id).bound_closed(
                    row["draft_id"], row["provider"]
                )

    @contextmanager
    def _opened(self, claimed: ClaimedDraft) -> Iterator[psycopg.Connection]:
        with self.database.session(claimed.workspace_id) as connection:
            with connection.transaction():
                WorldDraftRepository(connection, claimed.workspace_id).require_claim(claimed)
            connection.execute(
                "select set_config('exulanica.world_draft_claim',%s,false)",
                (str(claimed.claim_token),),
            )
            yield connection

    def _recover(self, claimed: ClaimedDraft) -> None:
        with self._opened(claimed) as connection:
            row = connection.execute(
                "select entry_id from saved_world_entry where workspace_id=%s and world_id=%s",
                (claimed.workspace_id, claimed.world_id),
            ).fetchone()
            prior = WorldDraftRepository(connection, claimed.workspace_id).get(
                claimed.actor, claimed.draft_id
            )
            doc = dict(
                profile=OUTCOME_PROFILE,
                state="ready" if row else "refused",
                stage=None,
                tool=None,
                tool_chosen=None,
                entry_id=None if row is None else str(row["entry_id"]),
                made=[],
                left_out=[],
                look=None,
                setting=None,
                model_id=None,
                calls=[],
                recovered=True,
                refusal=None
                if row
                else dict(
                    code="world_draft_interrupted",
                    detail=(
                        "The interrupted draft was not asked again. Its spending remains recorded."
                    ),
                ),
            )
            if prior["progress"]:
                previous = dict(prior["progress"])
                previous.update(
                    state=doc["state"],
                    entry_id=doc["entry_id"],
                    refusal=doc["refusal"],
                    recovered=True,
                )
                doc = previous
            WorldDraftRepository(connection, claimed.workspace_id).finish(claimed, doc)

    def funding_due(self, workspace_id: uuid.UUID) -> None:
        """Recover accepted intent/bound-open crashes without starting another request."""
        with self.database.session(workspace_id) as connection:
            due = WorldDraftRepository(connection, workspace_id).funding_due()
        for start in due:
            with self.database.session(workspace_id) as connection:
                row = WorldDraftRepository(connection, workspace_id).get(
                    start["actor_id"], start["draft_id"]
                )
            definition = row["definition"]
            quote = definition["quote"]
            try:
                # The bounds its start funded it with, which a recovery opens or matches exactly.
                for provider in funding_of(definition):
                    key = f"world-draft:{row['draft_id']}:{provider['provider']}"
                    with self.database.session(workspace_id) as connection:
                        existing = connection.execute(
                            "select grant_id,ceiling_usd,max_calls,valid_until from spending_grant "
                            "where workspace_id=%s and bound_key=%s",
                            (workspace_id, key),
                        ).fetchone()
                    if existing is not None:
                        if (
                            existing["ceiling_usd"] != Decimal(provider["ceiling_usd"])
                            or existing["max_calls"] != provider["max_calls"]
                            or existing["valid_until"]
                            != dt.datetime.fromisoformat(definition["funding_valid_until"])
                        ):
                            raise WorldDraftRefused("world_draft_funding_changed")
                        with self.database.session(workspace_id) as connection:
                            WorldDraftRepository(connection, workspace_id).attach_bound(
                                row["actor_id"],
                                row["draft_id"],
                                provider["provider"],
                                existing["grant_id"],
                            )
                if dt.datetime.now(dt.UTC) >= dt.datetime.fromisoformat(quote["expires_at"]):
                    raise WorldDraftRefused("world_draft_price_expired")
                for provider in funding_of(definition):
                    bound = self.spending.open_bound(
                        workspace_id,
                        provider=provider["provider"],
                        key=f"world-draft:{row['draft_id']}:{provider['provider']}",
                        ceiling_usd=Decimal(provider["ceiling_usd"]),
                        max_calls=provider["max_calls"],
                        valid_until=dt.datetime.fromisoformat(definition["funding_valid_until"]),
                        reason="A person confirmed this world draft operation.",
                    )
                    with self.database.session(workspace_id) as connection:
                        WorldDraftRepository(connection, workspace_id).attach_bound(
                            row["actor_id"], row["draft_id"], provider["provider"], bound
                        )
                with self.database.session(workspace_id) as connection:
                    WorldDraftRepository(connection, workspace_id).enqueue(
                        row["actor_id"], row["draft_id"]
                    )
            except (WorldDraftRefused, SpendingRefused) as failure:
                with self.database.session(workspace_id) as connection:
                    WorldDraftRepository(connection, workspace_id).end_unstarted(
                        row["actor_id"],
                        row["draft_id"],
                        getattr(failure, "code", "world_draft_funding_refused"),
                    )

    def run_once(self, workspace_id: uuid.UUID) -> bool:
        try:
            with self.holder.execution_slot():
                return self._run_once(workspace_id)
        except KindDraftCapacity:
            return False

    def _run_once(self, workspace_id: uuid.UUID) -> bool:
        self.funding_due(workspace_id)
        self.close_due(workspace_id)
        if self.holder.closing:
            return False
        # Reuse the native kind/world slot authority before claiming work.
        allowance = self.holder.allowance(workspace_id, uuid.UUID(int=0))
        if allowance.running is not None:
            return False
        with self.database.session(workspace_id) as connection:
            repo = WorldDraftRepository(connection, workspace_id)
            try:
                claimed = repo.claim()
            except WorldDraftRefused:
                return False
            if claimed is None:
                return False
            bounds = repo.bounds(claimed.draft_id)
        if claimed.recovery:
            self._recover(claimed)
            self.close_due(workspace_id)
            return True

        def work(draft: KindDraft, holder: KindDrafts) -> None:
            recorder = Recorder(self, claimed, holder)
            try:
                validate_definition(claimed.definition)
                if manifest_sha256(self.client) != claimed.definition["manifest_sha256"]:
                    raise WorldDraftRefused("world_draft_configuration_changed")
                if dt.datetime.now(dt.UTC) >= dt.datetime.fromisoformat(
                    claimed.definition["quote"]["expires_at"]
                ):
                    raise WorldDraftRefused("world_draft_price_expired")
                sender = (
                    self.client.with_prices(
                        prices_of(claimed.definition["quote"]),
                        limits=limits(claimed.definition["quote"]),
                    )
                    .with_policy(self.policy_for(workspace_id))
                    .with_spending(DraftSpending(self, claimed, bounds))
                )
                # The web notes the start named are read with the words, by the person who
                # started it: a request of anyone else's reads as unknown, and the draft is then
                # made from its words alone.
                reference = reference_of(claimed.definition)
                notes, references = None, None
                with self._opened(claimed) as connection:
                    sent = sendable(connection, workspace_id, claimed.description)
                    if reference is not None:
                        notes, references = draft_notes(
                            connection, workspace_id, claimed.actor, reference, sent
                        )
                with spending_request_key(f"world-draft:{claimed.draft_id}"):
                    make_world(
                        draft,
                        recorder,
                        client=sender,
                        opened=lambda: self._opened(claimed),
                        actor=claimed.actor,
                        sent=sent,
                        store=self.store,
                        guest=claimed.guest,
                        fixed_world_id=claimed.world_id,
                        on_land=self.on_land,
                        notes=notes,
                        references=references,
                    )
            except Exception as failure:
                if draft.state == "drafting":
                    code = getattr(failure, "code", "world_draft_failed")
                    with suppress(WorldDraftRefused):
                        recorder.finish(
                            draft,
                            state="refused",
                            refusal=dict(
                                code=code, detail="The draft ended without asking it again."
                            ),
                        )
            finally:
                self.close_due(workspace_id)

        try:
            self.holder.start(
                workspace_id,
                claimed.actor,
                claimed.description,
                work,
                deadline=claimed.definition["deadline_seconds"],
                guest=claimed.guest,
                purpose="world",
                identity=claimed.draft_id,
                admitted=True,
                reserved=True,
            )
        except (KindDraftBusy, KindDraftCapacity, KindDraftLimit) as failure:
            with self.database.session(workspace_id) as connection:
                WorldDraftRepository(connection, workspace_id).finish(
                    claimed,
                    dict(
                        profile=OUTCOME_PROFILE,
                        state="refused",
                        entry_id=None,
                        calls=[],
                        refusal=dict(
                            code="kind_draft_busy"
                            if isinstance(failure, KindDraftBusy)
                            else "kind_draft_capacity"
                            if isinstance(failure, KindDraftCapacity)
                            else "kind_draft_limit",
                            detail="The native draft slot was refused.",
                        ),
                    ),
                )
            self.close_due(workspace_id)
        return True

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            with self._lock:
                watched = set(self._watched)
            # A listing that fails costs this pass the workspaces it lists, never the worker.
            try:
                listed = set(self.workspaces())
            except Exception as failure:
                _LOG.warning(
                    "World draft worker could not list workspaces: %s", type(failure).__name__
                )
                listed = set()
            for workspace in sorted(listed | watched, key=str):
                if stop.is_set():
                    break
                try:
                    self.run_once(workspace)
                except Exception as failure:
                    _LOG.warning("World draft worker turn failed: %s", type(failure).__name__)
                    continue
            self._wake.wait(0.5)
            self._wake.clear()
