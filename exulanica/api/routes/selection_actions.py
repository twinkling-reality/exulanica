"""The Companion's world actions: a plan from words, a step prepared, and what was recorded.

Three routes, none of which changes the world. ``POST /selection/actions`` reads one utterance and
answers with a plan whose steps are the exact requests a direct client sends to the routes that
already change the world, each with that route's own preview
(:mod:`exulanica.selection.action_plan`). ``POST /selection/actions/prepare`` does the same for
typed actions with no model: a clarification answered, or the next step of a compound request
against the state the previous step left. ``POST /selection/actions/outcome`` reads back what the
authorities recorded for a plan's steps (:mod:`exulanica.selection.action_outcome`).

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
from pydantic import BaseModel, ConfigDict, Field, JsonValue

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
from exulanica.selection.action_outcome import InvalidOutcomeStep, action_outcome
from exulanica.selection.action_plan import (
    ACTION_PROMPT_VERSION,
    Grant,
    Previewer,
    plan_action,
    prepare_action,
)
from exulanica.selection.validation import Session
from exulanica.world.object_edit_preview import read_only_snapshot
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import OBJECT_ID_PATTERN
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
        "place_object", "move_object", "remove_object", "undo_last_edit", "place_arrangement"
    ]
    asset_key: str | None = Field(default=None, max_length=200, pattern=r"^[a-z][a-z0-9.-]*$")
    object_id: str | None = Field(default=None, max_length=200, pattern=OBJECT_ID_PATTERN)
    arrangement_key: str | None = Field(default=None, max_length=200, pattern=r"^[a-z][a-z0-9_]*$")
    arrangement_version: int | None = Field(default=None, ge=1)


class PrepareRequest(ActionBase):
    actions: list[TypedActionBody] = Field(min_length=1, max_length=3)


#: The route keys a plan's steps name: the matrix's edits and the style lifecycle's two requests.
OutcomeOperation = Literal[
    "POST /world/versions/{version_id}/compositions/apply",
    "POST /world/versions/{version_id}/objects/{object_id}/move",
    "POST /world/versions/{version_id}/objects/{object_id}/remove",
    "POST /world/versions/{version_id}/objects/undo",
    "POST /world/versions/{version_id}/arrangements/apply",
    "POST /world/styles/previews",
    "POST /world/styles/previews/{preview_id}/apply",
]


class OutcomePinsBody(BaseModel):
    """A step's pins as the plan stated them."""

    model_config = ConfigDict(extra="forbid")

    base_state_sha256: str | None = Field(default=None, pattern=_SHA256)
    edit_seq: int | None = Field(default=None, ge=0)
    base_style_version_id: uuid.UUID | None = None
    base_topology_digest: str | None = Field(default=None, max_length=256)


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


class OutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: uuid.UUID
    #: Echoed back unverified: any client can name any digest.
    plan_sha256: str | None = Field(default=None, pattern=_SHA256)
    #: The plan's steps as it gave them. Used only to decide what to read.
    steps: list[OutcomeStepBody] = Field(min_length=1, max_length=3)


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
    requires: list[str]
    permitted: bool
    preview: dict[str, JsonValue] | None
    pins: dict[str, JsonValue] | None
    effects: list[dict[str, JsonValue]]
    confirmation: Literal["required"]
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
    clarification: ActionClarificationView | None
    refusal: ActionRefusalView | None
    capabilities: list[dict[str, JsonValue]] | None
    #: The appearance drafter's own sentence about a proposal: model output about a change not
    #: made, never a statement that anything happened.
    proposal_speech: str | None
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
        read = action_outcome(connection, body.model_dump(mode="json"), session, world_id=world_id)
    except InvalidOutcomeStep as exc:
        return JSONResponse(status_code=422, content={"code": exc.code, "detail": str(exc)})
    return ActionOutcomeView.model_validate(read)
