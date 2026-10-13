"""A world made from a person's words: started as a job, read by polling.

``POST /worlds/drafts`` takes a description in the person's own words and answers at once, 202
with a draft's id; it never waits on a model. A job (:mod:`exulanica.api.world_making`) chooses
the tool that can make the place, drafts with that tool's drafter and makes the world, so the
person meets no kind, preset or value on the way in. ``GET /worlds/drafts/{draft_id}`` reads where
it has got to, for the person who started it only: ``choosing``, ``drafting``, ``making``, then
``ready`` with the saved world, each part that was made and the words that were left out, or
``refused`` by name; either way with what it cost. ``GET /worlds/drafts`` says, before a word is
typed, whether a draft would be taken from this person now and what one may spend: the most times
it asks a model, how many of the hour's starts are left, and the person's own draft still running.

Starting one needs ``world.write`` and ``model.invoke``, since a draft spends on models and ends
by writing a world; reading one, or what a draft would take, needs ``world.read``. A server keeps
a kind of place from a person only where its deployment says so (``EXULANICA_KINDS_FROM_PEOPLE``):
elsewhere starting is refused 403 ``kinds_from_people_not_offered`` and the offer says so. A
draft's request, progress and result live in the durable job authority. Reads and same-key retries
survive a process restart without inference. An interrupted worker recovers an already saved
world or records a named interruption without asking again.

"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from exulanica.api.dependencies import (
    CurrentSession,
    HeldPermissions,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
    holds_as_guest,
)
from exulanica.api.kind_drafts import (
    KIND_DRAFT_CODES,
    KINDS_FROM_PEOPLE_NOT_OFFERED,
    KINDS_FROM_PEOPLE_NOT_OFFERED_DETAIL,
    KindDraft,
    allowance_refusal,
    draft_deadline_seconds,
)
from exulanica.api.permissions import Permission
from exulanica.api.routes.selection import ExecutionView, ModelNotConfigured, _execution
from exulanica.api.routes.world_entries import SavedWorldEntryView, _view
from exulanica.api.sayable import sayable
from exulanica.api.services import Services
from exulanica.api.world_draft_offer import (
    WorldDraftOfferRefused,
    confirm_operation,
    read_operation_sheet,
    stages,
)
from exulanica.api.world_draft_worker import manifest_sha256
from exulanica.api.world_making import WORLD_DRAFT_CODES, calls_at_most
from exulanica.canonical import canonical_json
from exulanica.models.manifest import load_manifest
from exulanica.selection.calls import AttemptOutcome, CallCost, ModelCall
from exulanica.selection.tool_choosing import chooser_prompt
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.world_draft_contract import DEFINITION_PROFILE
from exulanica.world.world_draft_jobs import WorldDraftRefused, WorldDraftRepository, terms_sha256
from exulanica.world.worlds import (
    GENERATED,
    UnknownWorldResource,
    WorldLimitReached,
    WorldsReadOnly,
    refuse_past_limit,
    require_world_registration,
)

__all__ = ["BODY_LIMITS", "router"]

router = APIRouter(prefix="/worlds/drafts", tags=["world"])

#: The longest description a draft reads: the kind drafter's and the specification drafter's own.
DESCRIPTION_CHARACTERS: Final = 1000
#: The body asking for a draft may carry: a description of at most that many characters, at most
#: four bytes each as UTF-8, with its envelope.
DRAFT_BODY_MAXIMUM: Final = 131_072
#: How often the page asks after a draft, in seconds: choosing takes a few seconds, a town's
#: draft about ten and a place's twenty or more.
DRAFT_POLL_SECONDS: Final = 3
BODY_LIMITS: Final = (("POST", "/worlds/drafts", DRAFT_BODY_MAXIMUM),)


class DraftWorldBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Annotated[str, Field(min_length=1, max_length=DESCRIPTION_CHARACTERS)]
    idempotency_key: uuid.UUID | None = None
    operation: dict[str, Any] | None = None
    maximum_usd: str | None = Field(default=None, pattern=r"^[0-9]{1,6}(\.[0-9]{1,8})?$")

    @field_validator("operation")
    @classmethod
    def _canonical_operation(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        try:
            canonical_json(value)
        except TypeError as failure:
            raise ValueError(
                "operation terms must have a deterministic representation"
            ) from failure
        return value

    @field_validator("description")
    @classmethod
    def _says_something(cls, value: str) -> str:
        # A description of nothing but spaces would still cost a paid call.
        if not value.strip():
            raise ValueError("a description says in words what world is wanted")
        return value


class MadePartView(BaseModel):
    """One part of the world that was made, in the document's own words."""

    key: str
    label: str
    #: How the generator lays the part out and draws it: path, area, structure, room, fixture or
    #: boundary.
    form: str
    #: What a style pack dresses, ``family.leaf``.
    look: str
    #: How many slots the world's drawing draws for the part; none for a town's, whose records
    #: the city grammar generates.
    drawn: int | None
    #: The largest box among those slots, width, depth and height in millimetres; none where the
    #: part is not drawn as a thing of its own.
    box_mm: list[int] | None


class DraftToolView(BaseModel):
    #: The world tool catalog's key of the tool that drafts and makes the world.
    key: str
    #: ``model`` where the chooser named it; ``unsure`` where it answered none, was refused or
    #: failed and the catalog's tool for an unsure choice was taken.
    chosen_by: Literal["model", "unsure"]


class TakenLookView(BaseModel):
    """The look the made world is drawn in because the words asked for it."""

    pack_id: str
    title: str
    #: The person's own words that chose it.
    words: list[str]


class TakenPartView(BaseModel):
    #: The setting's axis (``sky``, ``ground``, ``cover``) and the key of its named part.
    axis: str
    key: str
    title: str


class TakenSettingView(BaseModel):
    """The named parts of a setting the made world stands in because the words asked for them."""

    parts: list[TakenPartView]
    #: The person's own words that chose them, in the description's order.
    words: list[str]


class WorldDraftRefusalView(BaseModel):
    code: str
    detail: str
    check: str | None = None
    where: str | None = None
    #: For ``budget_exceeded`` from the durable authority: the problem's ``spending`` member.
    spending: dict[str, str] | None = None


class CodeView(BaseModel):
    code: str
    meaning: str


class MadeWorldDraftView(BaseModel):
    draft_id: uuid.UUID
    request_id: uuid.UUID | None = None
    operation: dict[str, Any] | None = None
    recovered: bool = False
    accounting: dict[str, Any] | None = None
    state: Literal["queued", "choosing", "drafting", "making", "ready", "refused"]
    #: The whole sentence, while the draft runs; a draft that ended keeps none of it here. (The
    #: phrases of ``left_out`` are the person's own words too, and stay while the draft is read.)
    description: str
    started_at: datetime
    elapsed_seconds: int
    poll_after_seconds: int | None
    deadline_seconds: int
    tool: DraftToolView | None
    #: The saved world, once it is made.
    entry: SavedWorldEntryView | None
    made: list[MadePartView]
    #: The parts of the description nothing in the made world says, each the person's own words.
    left_out: list[str]
    #: What the job took from the words for how the world is drawn and where it stands, each
    #: with the words that chose it; null where the words asked for none. Taken, not offered:
    #: a person changes either afterwards in the world's look.
    look: TakenLookView | None = None
    setting: TakenSettingView | None = None
    refusal: WorldDraftRefusalView | None
    model_name: str | None
    execution: ExecutionView | None
    #: Every code a draft's routes and its job answer with, and what each means.
    refusals: list[CodeView]


class DraftStartsView(BaseModel):
    """This person's starts of a draft in this workspace, counted over the last hour."""

    #: How many drafts one person may start in an hour here (a guest by a guest's figure).
    an_hour: int
    left: int
    #: Whole seconds until a start frees, where none is left.
    retry_after_seconds: int | None


class WorldDraftOfferView(BaseModel):
    """Whether a draft of a world would be taken from this person now, and what one may spend:
    read before a word is typed, and shown before the words are sent."""

    offered: bool
    #: Why not, by a code of ``refusals``, where a start would be refused now; ``detail`` says it
    #: in a sentence.
    code: str | None
    detail: str | None
    #: The most times one draft asks a model. Each call is reserved against the workspace's
    #: spending allowance before it is made.
    calls_at_most: int
    starts: DraftStartsView
    #: The longest description a draft reads, in characters.
    description_characters: int
    #: This person's own draft of a world still running here, to follow instead of starting one.
    running_draft_id: uuid.UUID | None
    refusals: list[CodeView]
    operation: dict[str, Any] | None = None


def _problem(status: int, code: str, detail: str, **extra: Any) -> JSONResponse:
    headers = extra.pop("headers", None)
    return JSONResponse(
        {"code": code, "detail": sayable(detail), **extra}, status_code=status, headers=headers
    )


def _codes() -> list[CodeView]:
    listed = dict(KIND_DRAFT_CODES)
    listed.update(dict(WORLD_DRAFT_CODES))
    listed["world_draft_unknown"] = "The server holds no draft this person started with this id."
    listed["kind_draft_busy"] = "The workspace already has a draft running."
    listed.update(
        {
            "world_draft_price_unavailable": "No fresh provider rates cover this operation.",
            "world_draft_price_expired": "The accepted operation sheet expired before dispatch.",
            "world_draft_operation_changed": "Read changed operation terms before confirming.",
            "world_draft_bound_too_small": "The confirmed ceiling cannot cover this operation.",
            "world_draft_key_reused": "The request key already holds different terms.",
            "world_draft_worker_not_running": "This host is not running its world draft worker.",
            "world_draft_spending_not_durable": "Durable spending authority is required.",
            "world_draft_configuration_changed": "The accepted model configuration changed.",
            "world_draft_funding_refused": "Durable provider bounds could not be opened.",
            "world_draft_interrupted": "The interrupted draft was not asked again.",
        }
    )
    return [CodeView(code=code, meaning=meaning) for code, meaning in sorted(listed.items())]


@dataclass(frozen=True, slots=True)
class _No:
    """Why a draft would not be started, known before any model is asked."""

    status: int
    code: str
    detail: str
    #: The refusal as the application's own handler answers it for every model route, where it is
    #: one of those (no credential, a spent allowance): raised by the start, said by the offer.
    raised: Exception | None = None


def _unstartable(
    services: Services, connection: Any, workspace_id: uuid.UUID, *, guest: bool
) -> _No | None:
    """The first reason this workspace's person could not start a draft, in the order the start
    asks them, or None: every one of them is known before a model is asked, so nobody is charged
    to be told no. A server that keeps no kind from a person; no model credential; an allowance
    that admits no attempt; a workspace already holding as many generated worlds as it may; a
    database role that cannot register a world."""
    if not services.kinds_from_people:
        return _No(403, KINDS_FROM_PEOPLE_NOT_OFFERED, KINDS_FROM_PEOPLE_NOT_OFFERED_DETAIL)
    if services.model_client is None:
        absent = ModelNotConfigured()
        return _No(503, absent.code, str(absent), absent)
    spent = allowance_refusal(
        services.spending_refusals(connection, workspace_id), services.model_client
    )
    if spent is not None:
        return _No(429, "budget_exceeded", str(spent), spent)
    try:
        # Asked again under the workspace's lock when the world is registered, where the answer
        # is the one that holds; asked here so a workspace at its limit pays for no draft.
        refuse_past_limit(connection, workspace_id, GENERATED, guest=guest)
    except WorldLimitReached as full:
        return _No(409, full.code, str(full))
    try:
        # The request's own connection is the read-only role's: the role that would write is asked.
        with services.database.session(workspace_id) as writing:
            require_world_registration(writing)
    except WorldsReadOnly as read_only:
        return _No(403, read_only.code, str(read_only))
    return None


def _draft_view(
    draft: KindDraft, connection: Any, services: Services, now: float
) -> MadeWorldDraftView:
    ended = draft.state != "drafting"
    entry = None
    if draft.state == "ready" and draft.entry_id is not None:
        try:
            found = SavedWorldEntryRepository(connection, draft.workspace_id, services.store).entry(
                draft.entry_id
            )
        except UnknownWorldResource:
            services.kind_drafts.erase_entries(draft.workspace_id, {draft.entry_id})
            raise
        entry = (
            None
            if found is None
            else _view(found, societies_of_things=services.societies_of_things)
        )
    prompt_version = chooser_prompt().prompt_version
    return MadeWorldDraftView(
        draft_id=draft.draft_id,
        state=draft.state if ended else (draft.stage or "choosing"),  # type: ignore[arg-type]
        description=draft.description,
        started_at=draft.started_at,
        elapsed_seconds=round((draft.changed if ended else now) - draft.started),
        poll_after_seconds=None if ended else DRAFT_POLL_SECONDS,
        deadline_seconds=math.ceil(
            draft_deadline_seconds() if draft.deadline is None else draft.deadline
        ),
        tool=None
        if draft.tool is None
        else DraftToolView(key=draft.tool, chosen_by="model" if draft.tool_chosen else "unsure"),
        entry=entry,
        made=[MadePartView(**part) for part in draft.made],
        left_out=list(draft.left_out),
        look=None if draft.look is None else TakenLookView(**draft.look),
        setting=None if draft.setting is None else TakenSettingView(**draft.setting),
        refusal=None if draft.refusal is None else WorldDraftRefusalView(**draft.refusal),
        model_name=None if draft.model_id is None else load_manifest().model_name(draft.model_id),
        execution=_execution(draft.calls, (), prompt_version=prompt_version)
        if draft.calls
        else None,
        refusals=_codes(),
    )


def _durable_view(row: dict[str, Any], connection: Any, services: Services) -> MadeWorldDraftView:
    doc = row["outcome"] or row["progress"] or {}
    now = services.kind_drafts.clock()
    age = max(0, (datetime.now(UTC) - row["started_at"]).total_seconds())
    draft = KindDraft(
        draft_id=row["draft_id"],
        workspace_id=row["workspace_id"],
        actor=row["actor_id"],
        description=row["description"] or "",
        started_at=row["started_at"],
        started=now - age,
        changed=now,
        purpose="world",
        deadline=row["definition"]["deadline_seconds"],
        state="drafting" if row["state"] in ("queued", "running") else doc.get("state", "refused"),
    )
    for field in (
        "stage",
        "tool",
        "tool_chosen",
        "made",
        "left_out",
        "look",
        "setting",
        "refusal",
        "model_id",
    ):
        if field in doc:
            setattr(draft, field, doc[field])
    draft.entry_id = None if not doc.get("entry_id") else uuid.UUID(doc["entry_id"])
    draft.calls = tuple(
        ModelCall(
            **dict(
                call,
                outcome=AttemptOutcome(call["outcome"]),
                cost_basis=CallCost(call["cost_basis"]),
            )
        )
        for call in doc.get("calls", ())
    )
    view = _draft_view(draft, connection, services, now)
    return view.model_copy(
        update={
            "state": "queued" if row["state"] == "queued" else view.state,
            "request_id": row["request_id"],
            "operation": row["definition"]["quote"],
            "recovered": bool(doc.get("recovered")),
            "accounting": WorldDraftRepository(connection, row["workspace_id"]).accounting(
                row["actor_id"], row["draft_id"]
            ),
        }
    )


@router.post(
    "",
    response_model=MadeWorldDraftView,
    status_code=202,
    summary="Make a world from a description, as a job the page polls.",
)
def start_world_draft(
    body: DraftWorldBody,
    connection: ReadOnlyConnection,
    scoped: ScopedConnection,
    request: Request,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
    guest: Annotated[bool, Depends(holds_as_guest)],
) -> MadeWorldDraftView | JSONResponse:
    """Admit the words and start the draft; answer at once, never waiting on a model.

    403 ``kinds_from_people_not_offered`` on a server whose deployment has not turned kinds from
    people on; 503 without a model credential; 429 ``budget_exceeded`` with its ``spending``
    member when the workspace's allowance admits no attempt; 409 ``world_limit_reached`` when the
    workspace holds as many generated worlds as it may; 403 ``worlds_read_only`` where the
    database role cannot register a world: each before anything is spent, and each said by
    ``GET /worlds/drafts`` before anything is typed. 409 ``kind_draft_busy`` while a draft runs in
    this workspace, with its ``draft_id`` when the caller started it as a world's draft; 429
    ``kind_draft_limit`` with a ``Retry-After`` when the caller has started as many drafts this
    hour as one person may; 503 ``kind_draft_capacity`` with a ``Retry-After`` when the server
    runs as many drafts as it may. The three figures are the world draft policy's
    budgets. A body over 131,072 bytes, including quote metadata, is refused 413 before it is read.
    Saved names are replaced in the words before the job starts.
    """
    workspace_id = session.workspace_id
    key = body.idempotency_key or uuid.uuid4()
    terms = terms_sha256(body.description, body.operation, body.maximum_usd)
    repository = WorldDraftRepository(scoped, workspace_id)
    prior = repository.by_request(session.actor, key)
    if prior is not None:
        try:
            row = repository.get(session.actor, prior["draft_id"])
        except WorldDraftRefused:
            return _problem(
                404, "world_draft_unknown", "That draft is no longer held for this person."
            )
        if row["terms_sha256"] != terms:
            return _problem(409, "world_draft_key_reused", "That request key has different terms.")
        return _durable_view(row, connection, services)
    no = _unstartable(services, connection, workspace_id, guest=guest)
    if no is not None:
        if no.raised is not None:
            raise no.raised
        return _problem(no.status, no.code, no.detail)
    if services.spending is None:
        return _problem(
            503,
            "world_draft_spending_not_durable",
            "Durable spending authority is required.",
        )
    worker = getattr(request.app.state, "world_draft_worker", None)
    thread = getattr(request.app.state, "world_draft_thread", None)
    if worker is None or thread is None or not thread.is_alive() or services.kind_drafts.closing:
        return _problem(
            503,
            "world_draft_worker_not_running",
            "This host is not running its world draft worker.",
        )
    client = services.model_client
    assert client is not None
    try:
        quote = confirm_operation(client, body.operation)
        if body.maximum_usd is not None and Decimal(body.maximum_usd) < Decimal(
            quote["maximum_usd"]
        ):
            raise WorldDraftOfferRefused("world_draft_bound_too_small")
        native = services.kind_drafts.allowance(workspace_id, session.actor, guest=guest)
        durable = repository.allowance(session.actor, native.starts_an_hour)
        if durable["running_count"] >= services.kind_drafts._budget(
            services.kind_drafts.per_workspace, "workspace_drafts_at_once"
        ):
            own = durable["running"]
            extra = (
                {"draft_id": str(own["draft_id"])}
                if own is not None
                and own["actor_id"] == session.actor
                and own["purpose"] == "world"
                else {"draft_id": str(native.running.draft_id)}
                if native.running is not None
                and native.running.actor == session.actor
                and native.running.purpose == "world"
                else {}
            )
            return _problem(409, "kind_draft_busy", "A draft is already running here.", **extra)
        if durable["left"] == 0:
            raise WorldDraftRefused("kind_draft_limit", durable["retry_after_seconds"])
        now = datetime.now(UTC)
        deadline = math.ceil(
            sum(
                attempts * client.worst_case_seconds(role)
                for role, attempts in max(
                    stages().values(),
                    key=lambda rows: sum(
                        attempts * client.worst_case_seconds(role) for role, attempts in rows
                    ),
                )
            )
            + draft_deadline_seconds(client)
            + 120
        )
        definition = dict(
            profile=DEFINITION_PROFILE,
            quote=quote,
            manifest_sha256=manifest_sha256(client),
            deadline_seconds=deadline,
            funding_valid_until=(now + timedelta(seconds=deadline + 120)).isoformat(),
        )
        ident = repository.submit(
            actor=session.actor,
            request_id=key,
            description=body.description,
            terms_sha256=terms,
            definition=definition,
            guest=guest,
            starts_maximum=native.starts_an_hour,
            workspace_maximum=services.kind_drafts._budget(
                services.kind_drafts.per_workspace, "workspace_drafts_at_once"
            ),
        )
        stored = repository.get(session.actor, ident)
        definition = stored["definition"]
        quote = definition["quote"]
        try:
            for provider in quote["providers"]:
                bound = services.spending.open_bound(
                    workspace_id,
                    provider=provider["provider"],
                    key=f"world-draft:{ident}:{provider['provider']}",
                    ceiling_usd=Decimal(provider["ceiling_usd"]),
                    max_calls=provider["max_calls"],
                    valid_until=datetime.fromisoformat(definition["funding_valid_until"]),
                    reason="A person confirmed this world draft operation.",
                )
                repository.attach_bound(session.actor, ident, provider["provider"], bound)
            repository.enqueue(session.actor, ident)
        except Exception:
            repository.end_unstarted(session.actor, ident, "world_draft_funding_refused")
            raise
        worker = getattr(request.app.state, "world_draft_worker", None)
        if worker is not None:
            worker.notify(workspace_id)
        return _durable_view(repository.get(session.actor, ident), connection, services)
    except WorldDraftOfferRefused as failure:
        return _problem(409, failure.code, "Read the operation sheet again before confirming.")
    except WorldDraftRefused as failure:
        return _problem(
            404
            if failure.code == "world_draft_unknown"
            else 429
            if failure.code == "kind_draft_limit"
            else 409,
            failure.code,
            "The world draft was refused before another start.",
            headers=None
            if failure.retry_after_seconds is None
            else {"Retry-After": str(failure.retry_after_seconds)},
        )


@router.get(
    "",
    response_model=WorldDraftOfferView,
    summary="Whether a draft of a world would be taken now, and what one may spend.",
)
def read_world_draft_offer(
    connection: ReadOnlyConnection,
    request: Request,
    session: CurrentSession,
    held: HeldPermissions,
    services: Annotated[Services, Depends(get_services)],
    guest: Annotated[bool, Depends(holds_as_guest)],
) -> WorldDraftOfferView:
    """What starting a draft would meet, for this person in this workspace, before a word is
    typed: ``offered`` or the first refusal a start would give, by code and sentence, in the
    order the start asks them; the most times one draft asks a model (``calls_at_most``); this
    person's starts this hour, how many are left and when the next frees; and their own draft of
    a world still running here, by id. Nothing is said of anybody else: another person's running
    draft is ``kind_draft_busy`` with no id. The server's own capacity changes from moment to
    moment and is answered when a draft starts."""
    workspace_id = session.workspace_id
    allowance = services.kind_drafts.allowance(workspace_id, session.actor, guest=guest)
    durable = WorldDraftRepository(connection, workspace_id).allowance(
        session.actor, allowance.starts_an_hour
    )
    live = durable["running"]
    own_running = (
        live["draft_id"]
        if live and live["actor_id"] == session.actor and live["purpose"] == "world"
        else None
    )
    quote = None
    code: str | None
    detail: str | None
    if not services.kinds_from_people:
        # First, as the kinds library answers it: what the server takes is true for everybody.
        code, detail = KINDS_FROM_PEOPLE_NOT_OFFERED, KINDS_FROM_PEOPLE_NOT_OFFERED_DETAIL
    elif not {Permission.WORLD_WRITE, Permission.MODEL_INVOKE} <= held:
        code, detail = "not_authorised", dict(KIND_DRAFT_CODES)["not_authorised"]
    else:
        no = _unstartable(services, connection, workspace_id, guest=guest)
        if no is not None:
            code, detail = no.code, no.detail
        elif services.spending is None:
            code, detail = (
                "world_draft_spending_not_durable",
                "Durable spending authority is required.",
            )
        elif durable["running_count"] >= services.kind_drafts._budget(
            services.kind_drafts.per_workspace, "workspace_drafts_at_once"
        ):
            code, detail = "kind_draft_busy", "A draft is already running in this workspace."
        elif durable["left"] == 0:
            code = "kind_draft_limit"
            detail = "As many drafts as one person may start in an hour were started."
        else:
            try:
                quote = read_operation_sheet(services.model_client)
                code, detail = None, None
            except WorldDraftOfferRefused as failure:
                code, detail = failure.code, "A current operation sheet is unavailable."
    if code is None:
        worker = getattr(request.app.state, "world_draft_worker", None)
        thread = getattr(request.app.state, "world_draft_thread", None)
        if (
            worker is None
            or thread is None
            or not thread.is_alive()
            or services.kind_drafts.closing
        ):
            code, detail = (
                "world_draft_worker_not_running",
                "This host is not running its world draft worker.",
            )
    return WorldDraftOfferView(
        offered=code is None,
        code=code,
        detail=None if detail is None else sayable(detail),
        calls_at_most=calls_at_most() if quote is None else quote["calls_at_most"],
        operation=quote,
        starts=DraftStartsView(
            an_hour=allowance.starts_an_hour,
            left=durable["left"],
            retry_after_seconds=durable["retry_after_seconds"],
        ),
        description_characters=DESCRIPTION_CHARACTERS,
        running_draft_id=own_running,
        refusals=_codes(),
    )


@router.get(
    "/{draft_id}",
    response_model=MadeWorldDraftView,
    summary="Where a draft of a world has got to, for the person who started it.",
)
def read_world_draft(
    draft_id: uuid.UUID,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> MadeWorldDraftView | JSONResponse:
    """The draft's state: choosing, drafting, making, ready with the saved world, or refused by
    name. 404 ``world_draft_unknown`` for an id the server holds for nobody here to read:
    another person's, another workspace's, a kind's draft, one a restart lost, or none."""
    try:
        row = WorldDraftRepository(connection, session.workspace_id).get(session.actor, draft_id)
    except WorldDraftRefused:
        return _problem(
            404, "world_draft_unknown", "The server holds no world draft for this person."
        )
    return _durable_view(row, connection, services)
