"""The Companion's world actions: a plan from words, a step prepared, and what was recorded.

Three routes, none of which changes the world. ``POST /selection/actions`` reads one utterance and
answers with a plan whose steps are the exact requests a direct client sends to the routes that
already change the world, each with that route's own preview, or for simulated time, the clock
read every base comes from (:mod:`exulanica.selection.action_plan`).
``POST /selection/actions/prepare`` does the same for typed actions with no model: a
clarification answered, or the next step of a compound request against the state the previous
step left. ``POST /selection/actions/outcome`` reads back what the authorities recorded for a
plan's steps (:mod:`exulanica.selection.action_outcome`).

Confirmation is not here. The person confirms a step and the client sends its request to the route
the step names, which applies the same permission, validation, transaction and refusal as it does
for any caller, so the Companion's path to an effect is the direct path.

Three boundaries these routes hold themselves:

*   **Descriptors are read, never re-derived.** The version's capability read
    (``exulanica.api.routes.capabilities``) says what is available and permitted, on the connection
    role that read uses.
*   **A preview connection opens only for a caller who may use the preview route.** It is opened
    after the caller's held grant satisfies that preview route's declaration in
    ``exulanica.api.permissions``, and its transaction is read only before anything runs in it.
*   **The actor, the workspace and the grant come from the session.** No body has a field for any
    of them, and a request field or a remembered conversation never makes a step permitted.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from psycopg import pq
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from exulanica.api.dependencies import (
    CurrentSession,
    HeldPermissions,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.api.permissions import Permission, Requires, rule_for
from exulanica.api.routes.capabilities import version_capabilities_document
from exulanica.api.routes.selection import ExecutionView, _execution, _require_model
from exulanica.api.routes.world_arrangements import ViewerBody
from exulanica.api.services import Services
from exulanica.api.world_edit import SavedEntryAdvanceBody, TransformBody
from exulanica.api.world_scope import WorldId
from exulanica.generation.offer import world_pieces
from exulanica.selection.action_outcome import InvalidOutcomeStep, action_outcome
from exulanica.selection.action_plan import (
    ACTION_PROMPT_VERSION,
    MAX_MINUTES,
    MAX_PLAN_STEPS,
    MAX_STEPS,
    ClockReader,
    Grant,
    Previewer,
    SocietyReader,
    plan_action,
    prepare_action,
)
from exulanica.selection.validation import Session
from exulanica.world.object_edit_preview import read_only_snapshot
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import OBJECT_ID_PATTERN
from exulanica.world.placed_things import PLACED_THING_ID_PATTERN
from exulanica.world.society import UnavailableSocietyInput, UnknownSociety
from exulanica.world.society_action_repository import SocietyActionRepository
from exulanica.world.society_controls import SPEEDS
from exulanica.world.world_clock_repository import WorldClockRepository
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/selection", tags=["selection"])

_SHA256 = r"^[0-9a-f]{64}$"


class PlacementContextBody(BaseModel):
    """Where the person is pointing: the region and the region-local transform, as supplied."""

    model_config = ConfigDict(extra="forbid")

    region_id: str = Field(min_length=1, max_length=500)
    transform: TransformBody


class ActionContextBody(BaseModel):
    """What the page shows the person, carried into the steps' bodies exactly as supplied."""

    model_config = ConfigDict(extra="forbid")

    placement: PlacementContextBody | None = None
    #: Where the person stands and faces, as an arrangement preview takes it.
    viewer: ViewerBody | None = None
    selected_object_id: str | None = Field(default=None, max_length=200, pattern=OBJECT_ID_PATTERN)


class CompanionSavedEntryBody(SavedEntryAdvanceBody):
    """The saved world the page edits. ``style_version_id`` is needed only by an appearance
    plan's apply step, whose saved-entry body names the style it advances from."""

    style_version_id: uuid.UUID | None = None


class ActionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: uuid.UUID
    #: The version state the page shows: a plan is refused ``stale_version`` when it moved.
    base_state_sha256: str = Field(pattern=_SHA256)
    #: The person's own choice for anything added, never inferred; null asks them.
    origin_role: Literal["fictional", "personal"] | None = None
    context: ActionContextBody = Field(default_factory=ActionContextBody)
    saved_entry: CompanionSavedEntryBody | None = None


class ActionRequest(ActionBase):
    #: The same bound the question and appearance routes use: it is the same text box.
    utterance: Annotated[str, Field(min_length=1, max_length=1000)]
    #: What an appearance change may be drawn from, chosen by the caller: the world's evidence
    #: (the default) or an authored design choice that cites none.
    appearance_basis: Literal["evidence", "authored_design"] = "evidence"


class TypedActionBody(BaseModel):
    """One typed change, as a plan's clarification or pending step states it."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal[
        "place_object",
        "move_object",
        "remove_object",
        "undo_last_edit",
        "place_arrangement",
        "place_thing",
        "direct_thing",
    ]
    asset_key: str | None = Field(default=None, max_length=200, pattern=r"^[a-z][a-z0-9.-]*$")
    object_id: str | None = Field(default=None, max_length=200, pattern=OBJECT_ID_PATTERN)
    arrangement_key: str | None = Field(default=None, max_length=200, pattern=r"^[a-z][a-z0-9_]*$")
    arrangement_version: int | None = Field(default=None, ge=1)
    #: A thing to add: its kind and version, the id its plan minted, and what it goes beside
    #: (``thing:``, ``object:``, ``being:`` or ``newest-object:`` and an id or key).
    kind: str | None = Field(default=None, max_length=48, pattern=r"^[a-z][a-z0-9_]{0,47}$")
    kind_version: int | None = Field(default=None, ge=1, le=10_000)
    thing_id: str | None = Field(default=None, max_length=200, pattern=PLACED_THING_ID_PATTERN)
    near: str | None = Field(default=None, min_length=1, max_length=300)
    #: A being asked to act: what it is asked, the being and the place, by the society's ids; for
    #: a hands act, the thing by its placed id (``thing_id``) and, to give or take, the other being.
    act: Literal["go_to", "use", "pick_up", "put_down", "give", "take"] | None = None
    subject_id: str | None = Field(default=None, max_length=200)
    target_id: str | None = Field(default=None, max_length=1000)
    with_id: str | None = Field(default=None, max_length=200)


class TypedSimulationBody(BaseModel):
    """One typed simulation request, as a plan's clarification states it, its slot filled."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["play", "pause", "set_speed", "advance", "bring_people"]
    #: A listed speed, as an integer or as the clarification candidate's value says it.
    speed: Literal[SPEEDS] | None = None  # type: ignore[valid-type]
    #: Simulated minutes to move forward: the server takes 1 to 10, and refuses any other count.
    minutes: Annotated[int, Field(ge=1, le=MAX_MINUTES)] | None = None
    region_id: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("speed", mode="before")
    @classmethod
    def _candidate_speed(cls, value: Any) -> Any:
        """A ``speed_required`` candidate's value is the speed written as text, and a client
        fills the open slot with it; it means the same listed speed."""
        return int(value) if isinstance(value, str) and value in {str(v) for v in SPEEDS} else value


class PrepareRequest(ActionBase):
    #: A plan's typed actions sent back with an answer (where its things come from, a slot
    #: filled): as many as one request may ask for, the drafter's own bound.
    actions: list[
        Annotated[TypedActionBody | TypedSimulationBody, Field(discriminator="operation")]
    ] = Field(min_length=1, max_length=MAX_STEPS)

    @model_validator(mode="after")
    def _simulation_alone(self) -> PrepareRequest:
        if len(self.actions) > 1 and any(
            isinstance(action, TypedSimulationBody) for action in self.actions
        ):
            raise ValueError("a simulation request is prepared alone")
        return self


#: The route keys a plan's steps name: the matrix's edits, the style lifecycle's two requests,
#: the playback controls and the creation of a version's people.
OutcomeOperation = Literal[
    "POST /world/versions/{version_id}/compositions/apply",
    "POST /world/versions/{version_id}/objects/{object_id}/move",
    "POST /world/versions/{version_id}/objects/{object_id}/remove",
    "POST /world/versions/{version_id}/objects/undo",
    "POST /world/versions/{version_id}/arrangements/apply",
    "POST /world/versions/{version_id}/things",
    "POST /world/versions/{version_id}/society/actions",
    "POST /world/styles/previews",
    "POST /world/styles/previews/{preview_id}/apply",
    "PUT /world/versions/{version_id}/society/control",
    "POST /world/versions/{version_id}/society/control/steps",
    "POST /world/versions/{version_id}/society",
    "POST /world/piece-requests",
]


class OutcomePinsBody(BaseModel):
    """A step's pins as the plan stated them."""

    model_config = ConfigDict(extra="forbid")

    base_state_sha256: str | None = Field(default=None, pattern=_SHA256)
    edit_seq: int | None = Field(default=None, ge=0)
    base_style_version_id: uuid.UUID | None = None
    base_topology_digest: str | None = Field(default=None, max_length=256)
    #: A simulation plan's first step: the clock read its bases came from.
    clock_revision: int | None = Field(default=None, ge=0)
    control_revision: int | None = Field(default=None, ge=0)
    tick: int | None = Field(default=None, ge=0)
    society_state_sha256: str | None = Field(default=None, pattern=_SHA256)


class OutcomeAnswerBody(BaseModel):
    """What one sent step's own request was answered with: its status and the identity that
    answer named. The read credits a step only with the record its answer names; a step sent back
    without one, or with a refusal, is never applied. Each identity field is the response's own,
    by the step's route: ``edit_seq`` and ``state_sha256`` for an edit (an arrangement's from its
    ``version``), ``event_seq`` and ``document_sha256`` for a control step (from its ``receipt``),
    ``revision`` and ``last_event_seq`` for a configuration, ``society_id`` for people brought in;
    a style step and a refused request send only ``status`` and ``code``."""

    model_config = ConfigDict(extra="forbid")

    status: int = Field(ge=100, le=599)
    #: The problem body's ``code`` when the request was refused.
    code: str | None = Field(default=None, max_length=200)
    edit_seq: int | None = Field(default=None, ge=0)
    state_sha256: str | None = Field(default=None, pattern=_SHA256)
    event_seq: int | None = Field(default=None, ge=0)
    document_sha256: str | None = Field(default=None, pattern=_SHA256)
    revision: int | None = Field(default=None, ge=0)
    last_event_seq: int | None = Field(default=None, ge=0)
    society_id: uuid.UUID | None = None
    #: A direct request's own id, as the actions route's envelope names it under ``request``.
    request_id: uuid.UUID | None = None
    #: The piece requests an ask for new pieces was answered with, by their ids, in its order.
    piece_request_ids: list[uuid.UUID] | None = Field(default=None, max_length=16)


class OutcomeStepBody(BaseModel):
    """One step as a plan gives it. The fields the read does not use are accepted and ignored,
    so a client can send the plan's steps back as they came."""

    model_config = ConfigDict(extra="ignore")

    index: int | None = None
    operation: OutcomeOperation
    state: Literal["prepared", "pending", "blocked", "not_permitted"] = "prepared"
    bind: dict[str, str | None] = Field(default_factory=dict)
    pins: OutcomePinsBody | None = None
    body: dict[str, JsonValue] | None = None
    preview: dict[str, JsonValue] | None = None
    #: What this step's own request was answered with; absent for a step not sent.
    answer: OutcomeAnswerBody | None = None


class OutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: uuid.UUID
    #: Echoed back unverified: any client can name any digest.
    plan_sha256: str | None = Field(default=None, pattern=_SHA256)
    #: The plan's steps as it gave them. Used only to decide what to read.
    steps: list[OutcomeStepBody] = Field(min_length=1, max_length=MAX_PLAN_STEPS)


class ActionRefusalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    detail: str
    step: int | None
    #: The route key of the operation refused, when one is.
    operation: str | None
    #: That operation's capability descriptor, when the capability read states one.
    capability: dict[str, JsonValue] | None
    #: What the same request could ask for instead, by code (``authored_design`` for a world
    #: holding no evidence), never words.
    alternatives: list[str]


class ClarificationCandidateView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    #: The catalog's title for a kind or an arrangement, or an object's kind; empty for a role.
    title: str
    selected: bool


class ActionClarificationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    step: int
    #: The action field the answer fills, or null when the answer is page context or a role.
    slot: str | None
    candidates: list[ClarificationCandidateView]
    #: The typed actions as drafted, the open slot null: sent to ``/selection/actions/prepare``
    #: with it filled.
    actions: list[dict[str, JsonValue]]


class ActionStepView(BaseModel):
    """One step: the exact request, what it requires, its pins and the authority's preview."""

    model_config = ConfigDict(extra="forbid")

    index: int
    action: dict[str, JsonValue]
    state: Literal["prepared", "pending", "blocked", "not_permitted"]
    #: For a blocked step, the preview's own ``blocked_reason``.
    code: str | None
    #: The route key the request is sent to, ``"METHOD /path/template"``.
    operation: str
    bind: dict[str, str | None]
    #: A path value taken from an earlier step's receipt, where one is.
    bind_from: dict[str, dict[str, JsonValue]] | None = None
    query: dict[str, str]
    body: dict[str, JsonValue] | None
    #: Body values taken from the response to an earlier step, by its index and a dotted field
    #: path into that response, where the body states them null.
    body_from: dict[str, dict[str, JsonValue]] | None = None
    requires: list[str]
    permitted: bool
    #: Whether sending the step can lead to a hosted model call: its descriptor's own spending,
    #: or a chosen model the time it moves on asks (a person's while the world plays, a light's
    #: for each minute a coupled world with traffic seals).
    spends: bool = False
    preview: dict[str, JsonValue] | None
    pins: dict[str, JsonValue] | None
    effects: list[dict[str, JsonValue]]
    #: ``chained``: the first step's confirmation covers this one; each is still its own commit,
    #: and a refusal stops the chain where it is.
    confirmation: Literal["required", "chained"]
    #: For a thing step, what it names as the reads label it (``kind`` and ``near``; ``subject``,
    #: ``place``, ``affordance`` and ``act``; or ``subject``, ``act``, ``thing`` and ``with``), for
    #: the page's words; absent otherwise.
    titles: dict[str, str] | None = None
    #: For new pieces of the world's look, what they will take before the person confirms: the
    #: route's own estimate (items, seconds warm and from a start, US dollars typically and at
    #: most, the provider and where the figures come from); absent otherwise.
    estimate: dict[str, JsonValue] | None = None
    replay: str
    receipt: str
    compensation: dict[str, str] | None


class ActionPlanView(BaseModel):
    """``exulanica.companion-action-plan/v1``: what one request asks for, as the routes take it."""

    model_config = ConfigDict(extra="forbid")

    profile: Literal["exulanica.companion-action-plan/v1"]
    outcome: Literal["plan", "clarify", "refused", "capabilities", "question"]
    kind: Literal["question", "appearance", "world_edit", "simulation", "capabilities"]
    world_id: str
    version_id: uuid.UUID
    plan_sha256: str
    #: True only for one step the authority commits all at once (an arrangement).
    atomic: bool
    steps: list[ActionStepView]
    #: Whether any step can lead to a hosted model call, said before the one confirmation, and
    #: the decision roles whose chosen models the plan's steps can ask.
    spends: bool = False
    spends_by: list[str] = Field(default_factory=list)
    clarification: ActionClarificationView | None
    refusal: ActionRefusalView | None
    capabilities: list[dict[str, JsonValue]] | None
    #: The appearance drafter's own sentence about a proposal: model output about a change not
    #: made, never a statement that anything happened.
    proposal_speech: str | None
    #: A simulation plan's clock read (``exulanica.world-clock/v1``), which every base it sends
    #: came from; null for any other plan.
    clock: dict[str, JsonValue] | None = None
    execution: ExecutionView
    names: dict[str, uuid.UUID] = Field(default_factory=dict)


class ActionOutcomeStepView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int | None
    operation: str | None
    state: Literal["applied", "not_applied", "superseded", "pending"]
    #: A refused style proposal's own status (``rejected``, ``stale``), or null.
    code: str | None
    receipts: list[dict[str, JsonValue]]
    repeats: list[dict[str, JsonValue]]
    matches_preview: bool | None


class ActionOutcomeView(BaseModel):
    """``exulanica.companion-action-outcome/v1``: what the authorities recorded, read back."""

    model_config = ConfigDict(extra="forbid")

    profile: Literal["exulanica.companion-action-outcome/v1"]
    world_id: str
    version_id: uuid.UUID
    plan_sha256: str | None
    state: Literal["applied", "partial", "not_applied", "superseded", "pending"]
    current: dict[str, JsonValue]
    steps: list[ActionOutcomeStepView]
    #: What the person could ask for next, by code: ``play`` when a chain that paused the world
    #: stopped before playing it again. Nothing is resumed on its own.
    alternatives: list[str] = Field(default_factory=list)


def _declaration(operation: str) -> Requires | None:
    method, path = operation.split(" ", 1)
    rule = rule_for(method, path)
    return rule if isinstance(rule, Requires) else None


def _grant(held: frozenset[Permission]) -> Grant:
    """For a route key, what its declaration requires and whether ``held`` covers it."""

    def grant(operation: str) -> tuple[list[str], bool]:
        rule = _declaration(operation)
        if rule is None:
            return [], False
        return sorted(permission.value for permission in rule.permissions), (
            rule.permissions <= held
        )

    return grant


@contextmanager
def open_preview_connection(services: Services, session: Session) -> Iterator[psycopg.Connection]:
    """A connection on the role the preview routes use, its transaction read only from the start.

    The one place a preview connection is opened, so a test can see whether one was.
    """
    with (
        services.database.session(session.workspace_id) as connection,
        connection.transaction(),
    ):
        connection.execute("set transaction isolation level repeatable read, read only")
        yield connection


def _previewer(
    request: Request, session: Session, held: frozenset[Permission], world_id: str
) -> Previewer:
    """A preview repository per preview route, for a caller the route's declaration admits."""
    services = get_services(request)

    @contextmanager
    def preview(operation: str) -> Iterator[WorldObjectRepository | None]:
        rule = _declaration(operation)
        if rule is None or not rule.permissions <= held:
            yield None
            return
        with open_preview_connection(services, session) as connection:
            require_world(connection, session.workspace_id, world_id)
            yield WorldObjectRepository(
                connection, session.workspace_id, world_id=world_id, store=services.store
            )

    return preview


def _capabilities(
    version_id: uuid.UUID,
    scoped: psycopg.Connection,
    session: Session,
    held: frozenset[Permission],
    request: Request,
    world_id: str,
) -> dict[str, Any]:
    """The capability read, on the role it reads with, in a read-only transaction: these routes
    write nothing by construction, whatever an adapter does."""
    with read_only_snapshot(scoped):
        return version_capabilities_document(
            version_id,
            connection=scoped,
            session=session,
            held=held,
            request=request,
            world_id=world_id,
        )


def _clock_reader(
    connection: psycopg.Connection, session: Session, world_id: str, version_id: uuid.UUID
) -> ClockReader:
    """The version's clock read, as ``GET .../clock`` answers it, taken on the read-only role
    when a plan asks for it: the read takes no lock and writes nothing."""

    def read() -> dict[str, Any]:
        return WorldClockRepository(connection, session.workspace_id, world_id).read(version_id)

    return read


@contextmanager
def _read_committed(connection: psycopg.Connection) -> Iterator[None]:
    """A read-only transaction at read committed, the isolation authorizing a society's inputs
    needs (migration 0041's asset read barrier refuses any other), or a savepoint in the caller's
    own transaction."""
    if connection.info.transaction_status != pq.TransactionStatus.IDLE:
        with connection.transaction():
            yield
        return
    with connection.transaction():
        connection.execute("set transaction read only")
        yield


def _society_reader(
    request: Request,
    scoped: psycopg.Connection,
    session: Session,
    world_id: str,
    version_id: uuid.UUID,
) -> SocietyReader:
    """What a direct request made now would be made against, read as the actions route reads it
    (``SocietyActionRepository.request_context``) on the role that route uses, in a read-only
    transaction; None for a version with no society, or one whose engine takes no request."""

    def read() -> tuple[dict[str, Any], dict[str, Any], int] | None:
        authorizer = getattr(request.app.state, "society_input_authorizer", None)
        repository = SocietyActionRepository(
            scoped,
            session.workspace_id,
            world_id=world_id,
            input_authorizer=(
                None if authorizer is None else lambda doc: authorizer(scoped, session, doc)
            ),
        )
        try:
            with _read_committed(scoped):
                return repository.request_context(version_id)
        except (UnknownSociety, UnavailableSocietyInput, ValueError):
            return None

    return read


def _view(document: dict[str, Any], execution: ExecutionView, names: Any) -> ActionPlanView:
    return ActionPlanView.model_validate({**document, "execution": execution, "names": names})


@router.post(
    "/actions",
    response_model=ActionPlanView,
    summary="Read one utterance as a plan of exact world requests, or decline to. Changes nothing.",
)
def plan_actions(
    body: ActionRequest,
    request: Request,
    connection: ReadOnlyConnection,
    scoped: ScopedConnection,
    session: CurrentSession,
    held: HeldPermissions,
    world_id: WorldId,
) -> ActionPlanView:
    client = _require_model(request, connection, session)
    require_world(connection, session.workspace_id, world_id)
    planned = plan_action(
        connection,
        client,
        body.model_dump(mode="json"),
        session,
        world_id=world_id,
        capabilities=_capabilities(body.version_id, scoped, session, held, request, world_id),
        store=get_services(request).store,
        previewer=_previewer(request, session, held, world_id),
        grant=_grant(held),
        clock=_clock_reader(connection, session, world_id, body.version_id),
        society=_society_reader(request, scoped, session, world_id, body.version_id),
        pieces=world_pieces(connection, session.workspace_id, world_id),
    )
    return _view(
        planned.document,
        _execution(planned.calls, (), prompt_version=planned.prompt_version),
        dict(planned.names),
    )


@router.post(
    "/actions/prepare",
    response_model=ActionPlanView,
    summary="Prepare typed actions as a plan, with no model. Changes nothing.",
)
def prepare_actions(
    body: PrepareRequest,
    request: Request,
    connection: ReadOnlyConnection,
    scoped: ScopedConnection,
    session: CurrentSession,
    held: HeldPermissions,
    world_id: WorldId,
) -> ActionPlanView:
    require_world(connection, session.workspace_id, world_id)
    document = prepare_action(
        connection,
        body.model_dump(mode="json"),
        session,
        world_id=world_id,
        capabilities=_capabilities(body.version_id, scoped, session, held, request, world_id),
        store=get_services(request).store,
        previewer=_previewer(request, session, held, world_id),
        clock=_clock_reader(connection, session, world_id, body.version_id),
        society=_society_reader(request, scoped, session, world_id, body.version_id),
    )
    return _view(document, _execution((), (), prompt_version=ACTION_PROMPT_VERSION), {})


@router.post(
    "/actions/outcome",
    response_model=ActionOutcomeView,
    summary="What the authorities recorded for a plan's steps, read back. Changes nothing.",
)
def action_outcomes(
    body: OutcomeRequest,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> ActionOutcomeView | JSONResponse:
    require_world(connection, session.workspace_id, world_id)
    try:
        read = action_outcome(
            connection,
            body.model_dump(mode="json"),
            session,
            world_id=world_id,
            clock=_clock_reader(connection, session, world_id, body.version_id),
        )
    except InvalidOutcomeStep as exc:
        return JSONResponse(status_code=422, content={"code": exc.code, "detail": str(exc)})
    return ActionOutcomeView.model_validate(read)
