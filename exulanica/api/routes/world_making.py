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
draft's state lives in this API process, as a kind's draft does: one a process restart lost is
answered 404 ``world_draft_unknown``, and a world it had already made is among the person's
worlds.
"""

from __future__ import annotations

import functools
import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from exulanica.api.dependencies import (
    CurrentSession,
    HeldPermissions,
    ReadOnlyConnection,
    get_services,
    holds_as_guest,
)
from exulanica.api.kind_drafts import (
    KIND_DRAFT_CODES,
    KINDS_FROM_PEOPLE_NOT_OFFERED,
    KINDS_FROM_PEOPLE_NOT_OFFERED_DETAIL,
    KindDraft,
    KindDraftBusy,
    KindDraftCapacity,
    KindDraftLimit,
    allowance_refusal,
    draft_deadline_seconds,
)
from exulanica.api.permissions import Permission
from exulanica.api.routes.selection import ExecutionView, ModelNotConfigured, _execution
from exulanica.api.routes.world_entries import SavedWorldEntryView, _view
from exulanica.api.sayable import sayable
from exulanica.api.services import Services
from exulanica.api.world_making import WORLD_DRAFT_CODES, calls_at_most, make_world
from exulanica.epistemics.hosted_requests import no_place_released
from exulanica.models.manifest import load_manifest
from exulanica.selection.tool_choosing import chooser_prompt
from exulanica.selection.world_drafting import sendable
from exulanica.world.saved_entries import SavedWorldEntryRepository
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
DRAFT_BODY_MAXIMUM: Final = 16_384
#: How often the page asks after a draft, in seconds: choosing takes a few seconds, a town's
#: draft about ten and a place's twenty or more.
DRAFT_POLL_SECONDS: Final = 3
BODY_LIMITS: Final = (("POST", "/worlds/drafts", DRAFT_BODY_MAXIMUM),)


class DraftWorldBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Annotated[str, Field(min_length=1, max_length=DESCRIPTION_CHARACTERS)]

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
    state: Literal["choosing", "drafting", "making", "ready", "refused"]
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
            found = None
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
        refusal=None if draft.refusal is None else WorldDraftRefusalView(**draft.refusal),
        model_name=None if draft.model_id is None else load_manifest().model_name(draft.model_id),
        execution=_execution(draft.calls, (), prompt_version=prompt_version)
        if draft.calls
        else None,
        refusals=_codes(),
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
    budgets. A body over 16,384 bytes is refused 413 before it is read. Saved names are replaced
    in the words before the job starts.
    """
    workspace_id = session.workspace_id
    no = _unstartable(services, connection, workspace_id, guest=guest)
    if no is not None:
        if no.raised is not None:
            raise no.raised
        return _problem(no.status, no.code, no.detail)
    assert services.model_client is not None
    sent = sendable(connection, workspace_id, body.description)

    def readable() -> Any:
        return services.readonly_database.session(workspace_id)

    def opened() -> Any:
        return services.database.session(workspace_id)

    # Describing a world is no use a place-name right offers, so no grant reaches these requests;
    # the policy opens its own connection for each judgement, since the request's is gone by then.
    client = services.model_client.with_policy(
        services.request_policy(workspace_id, readable, released_places=no_place_released)
    )
    try:
        draft = services.kind_drafts.start(
            workspace_id,
            session.actor,
            body.description,
            functools.partial(
                make_world,
                client=client,
                opened=opened,
                actor=session.actor,
                sent=sent,
                store=services.store,
                guest=guest,
            ),
            deadline=draft_deadline_seconds(client),
            guest=guest,
            purpose="world",
        )
    except KindDraftBusy as busy:
        # The running draft's id is told only to the person who started it, and only where it is
        # a world's: a kind's draft is read by the kinds' own route.
        return _problem(409, "kind_draft_busy", str(busy), **busy.told_to(session.actor, "world"))
    except KindDraftLimit as limit:
        return _problem(
            429,
            "kind_draft_limit",
            str(limit),
            headers={"Retry-After": str(limit.retry_seconds)},
        )
    except KindDraftCapacity:
        return _problem(
            503,
            "kind_draft_capacity",
            "The server is drafting as many worlds as it may. Try again in a moment.",
            headers={"Retry-After": "30"},
        )
    return _draft_view(draft, connection, services, services.kind_drafts.clock())


@router.get(
    "",
    response_model=WorldDraftOfferView,
    summary="Whether a draft of a world would be taken now, and what one may spend.",
)
def read_world_draft_offer(
    connection: ReadOnlyConnection,
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
    running = allowance.running
    mine = running is not None and running.actor == session.actor and running.purpose == "world"
    code: str | None
    detail: str | None
    if not {Permission.WORLD_WRITE, Permission.MODEL_INVOKE} <= held:
        code, detail = "not_authorised", dict(KIND_DRAFT_CODES)["not_authorised"]
    else:
        no = _unstartable(services, connection, workspace_id, guest=guest)
        if no is not None:
            code, detail = no.code, no.detail
        elif running is not None:
            code, detail = "kind_draft_busy", "A draft is already running in this workspace."
        elif allowance.starts_left == 0:
            code = "kind_draft_limit"
            detail = "As many drafts as one person may start in an hour were started."
        else:
            code, detail = None, None
    return WorldDraftOfferView(
        offered=code is None,
        code=code,
        detail=None if detail is None else sayable(detail),
        calls_at_most=calls_at_most(),
        starts=DraftStartsView(
            an_hour=allowance.starts_an_hour,
            left=allowance.starts_left,
            retry_after_seconds=allowance.retry_seconds,
        ),
        description_characters=DESCRIPTION_CHARACTERS,
        running_draft_id=running.draft_id if mine and running is not None else None,
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
    draft = services.kind_drafts.read(
        session.workspace_id, session.actor, draft_id, purpose="world"
    )
    if draft is None:
        return _problem(
            404,
            "world_draft_unknown",
            "The server holds no draft of yours with this id. If it restarted while your world "
            "was being drafted, look among your worlds, and say it again if it is not there.",
        )
    return _draft_view(draft, connection, services, services.kind_drafts.clock())
