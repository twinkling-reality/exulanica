"""The read surface: resolve a Selection, and answer a question from one.

Both routes are thin to the point of being boring, and that is the design. A Selection arriving
from the interface and a Selection arriving from the Companion are the same object by the time
they reach :func:`exulanica.selection.validation.validate`, and neither route knows which surface
produced the plan it was handed. ADR-0005: "nothing else in the system knows where a Selection
came from."

Three things the routes do that are not delegation, each of which is a boundary rather than
logic:

*   They open a **read-only connection**, as the executor role when one is configured.
*   They take the workspace and the actor **from the session**, so no request body has a field
    for either.
*   ``POST /selection/plan`` returns a proposed Selection and does not run it, because ADR-0005
    requires that a conversational Selection is "shown to the user before it is applied". The
    caller applies it by posting it back to ``POST /selection``.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.api.composer_rights import composer_rights_check
from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.environment import (
    EnvironmentOperationDenied,
    EnvironmentRepository,
    EnvironmentResourceWithdrawn,
    UnknownEnvironmentResource,
)
from exulanica.environment.nyc_open_data import PROVIDER_KEY as NYC_OPEN_DATA_PROVIDER_KEY
from exulanica.epistemics.saved_names import redact_names, saved_names
from exulanica.models.client import ModelClient
from exulanica.selection import (
    Abstention,
    Answer,
    AnswerClause,
    ClauseType,
    ContentPageCursor,
    ContentScope,
    ContentSelector,
    Intent,
    PlaceBridgeDecision,
    PlaceBridgeRepository,
    PlaceSelector,
    SelectionPlan,
    SelectionResult,
    build_packet,
    entity_catalogue,
    execute,
    validate,
)
from exulanica.selection.environment_proposal import (
    ENVIRONMENT_PROMPT_VERSION,
    EnvironmentOperation,
    draft_environment_operation,
)
from exulanica.selection.packet import build_content_packet
from exulanica.selection.proposal import PROMPT_VERSION as PROPOSAL_PROMPT_VERSION
from exulanica.selection.proposal import propose_appearance
from exulanica.selection.question import (
    PROMPT_VERSION,
    ModelCall,
    answer_question,
    propose_plan,
    requires_model,
)
from exulanica.world import (
    EnvironmentBindingDrift,
    EnvironmentCompositionDenied,
    EnvironmentPlacement,
    EnvironmentSelection,
    EnvironmentSourceWithdrawn,
    InvalidatedSourceVersion,
    InvalidEnvironmentData,
    InvalidEnvironmentState,
    ObjectOrigin,
    SourceAnchor,
    StaleObjectBase,
    StyleReference,
    Transform,
    UnavailableAsset,
    WorldNotConfigured,
    WorldObjectRepository,
    WorldStyleRepository,
)

router = APIRouter(prefix="/selection", tags=["selection"])


class SupportView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_id: uuid.UUID
    assertion_id: uuid.UUID | None
    dimension: str
    entity_id: uuid.UUID | None


class CaptureView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capture_id: uuid.UUID
    blob: str = Field(description="The RFC 6920 ni URI of the original bytes.")
    captured_at: str | None
    support: list[SupportView]


class EntityView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: uuid.UUID
    entity_class: str
    display_name: str | None
    capture_count: int


class ContentView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_kind: str
    origin_kind: str
    content_kind: str
    authored_role: str | None
    place_relationship: str
    match_reason: str
    memory_place_entity_id: uuid.UUID
    canonical_place_id: uuid.UUID | None
    world_id: str | None
    version_id: uuid.UUID | None
    source_id: str
    lineage_ids: list[str]
    label: str | None
    availability: str
    personal_visit_evidence: bool


class SelectionView(BaseModel):
    """What a Selection resolved to.

    ``total_matched`` and ``truncated`` are separate fields on purpose. A bounded result that
    does not say it was bounded reads as "that is all there is", and the interface needs to be
    able to say "at least".
    """

    model_config = ConfigDict(extra="forbid")

    captures: list[CaptureView]
    entities: list[EntityView]
    total_matched: int
    truncated: bool
    includes_proposals: bool
    content: list[ContentView]
    next_page: ContentPageCursor | None


class PlaceBridgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_place_id: uuid.UUID
    memory_place_entity_id: uuid.UUID
    reason: Annotated[str | None, Field(min_length=1, max_length=1000)] = None


class PlaceBridgeRevocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str | None, Field(min_length=1, max_length=1000)] = None


class PlaceBridgeView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: uuid.UUID
    canonical_place_id: uuid.UUID
    memory_place_entity_id: uuid.UUID
    decision: str
    supersedes_decision_id: uuid.UUID | None
    decided_by: uuid.UUID
    reason: str | None
    decided_at: str


class CityContextRequest(BaseModel):
    """A reticle selection from the independently admitted semantic city layer."""

    model_config = ConfigDict(extra="forbid")

    admission_id: uuid.UUID
    feature_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class QuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, Field(min_length=1, max_length=1000)]
    #: A plan the user has already seen and approved. When absent the model proposes one.
    plan: SelectionPlan | None = None
    city_context: CityContextRequest | None = None


class ModelCallView(BaseModel):
    """One model call the answer path made, as the response to it reported.

    Read off the response and never off the manifest. ``requested_model`` is what the chain
    asked for and ``served_model`` is what answered; they differ exactly when ``used_fallback``
    is true, which is the case a record derived from configuration would report wrongly.
    """

    model_config = ConfigDict(extra="forbid")

    role: str
    requested_model: str
    served_model: str | None
    used_fallback: bool
    #: HTTP requests issued, retries and failover included. Zero would mean the client's cache
    #: served it; the API builds its client without one, so on this route it is at least one.
    attempts: int | None
    latency_ms: int
    #: ``null`` where the provider's usage object did not report the count. Never a stand-in zero.
    prompt_tokens: int | None
    completion_tokens: int | None
    reasoning_tokens: int | None
    usd: str | None = None


class ExecutionView(BaseModel):
    """What this answer actually cost to produce, rather than what it was configured to cost.

    ``docs/product-direction.md`` makes this a delivery gate rather than telemetry: the memory
    interaction must "record the executed model, task, latency and output", and "Nemotron use
    must be functional in that interaction if claimed, with the actual executed variant recorded
    rather than inferred from configuration". This block carries the executed identifier, latency
    and usage, so the claim is read from the response rather than off the manifest.

    ``calls`` lists the calls that RETURNED A RESULT, in order. Read it as exactly that and not
    as "every model this answer cost", because two cases separate the two:

    *   **An abstention still lists the planner.** A question asked in words carries no plan, so
        the planner ran and was recorded before the packet came back empty. What an abstention
        guarantees is that no COMPOSER call is in the list, because there is no code path from an
        empty packet to one. A caller that read an abstention's list as "no model was asked"
        would be wrong about every question asked through an interface.
    *   **A call the endpoint truncated, or answered with a body the schema refused, is
        absent.** It raises inside the client before any result reaches the route.
        ``deterministic`` and ``rejections`` are what say that one happened.
    """

    model_config = ConfigDict(extra="forbid")

    #: The version of the two system prompts this answer was composed under. It is part of the
    #: response cache key, so an answer is only comparable with another at the same value.
    prompt_version: str
    calls: list[ModelCallView]
    #: Why the composer's output was refused, in the validator's own words, or empty.
    #:
    #: Here rather than nowhere because a measurement of this path has to record WHICH rule an
    #: answer broke: "deterministic" says the model's output was discarded and says nothing about
    #: whether it invented a number, cited a token that does not exist, or made a historical
    #: claim with no citation at all, and those are three different failures with three different
    #: fixes. Non-empty with ``deterministic`` false means the first attempt was refused and the
    #: repair was accepted.
    #:
    #: Safe to return: every string is written by
    #: :func:`~exulanica.selection.answer.validate_answer` about the model's own output, and
    #: names a citation token from this response's own packet at most. None of it is corpus
    #: content and none of it is another workspace's.
    rejections: list[str]


class AnswerView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: Answer
    #: The Selection the answer rests on, or ``null``.
    #:
    #: Nullable since 2026-09-09, and only for one case: ``abstained`` is
    #: ``UNANSWERABLE_NOT_UNDERSTOOD`` and the planner never produced a runnable Selection, so
    #: there is nothing to show. It is null rather than an empty plan because an empty plan is
    #: legal and means EVERYTHING, and reporting one here would say the whole library was
    #: searched when nothing was.
    plan: SelectionPlan | None
    #: What the Selection resolved to, or ``null`` when none was run. Null is not an empty
    #: selection: an empty one is a search that found nothing.
    selection: SelectionView | None
    citations: dict[str, str] = Field(
        description="Citation token to the permalink it resolves to, for this response only."
    )
    abstained: Abstention | None
    #: True when the composer's output was discarded and the deterministic answer used instead.
    deterministic: bool
    repaired: bool
    #: Which models answered, how long they took and what they spent. Additive: nothing above
    #: changed, and a client that ignores this field sees exactly the response it saw before.
    execution: ExecutionView
    #: Each placeholder the answer text may carry, ``[person A]`` or ``[place A]``, and the entity
    #: it stands for. No saved name is sent to a hosted model, so a composed answer names a person
    #: or a place only by placeholder, and the client restores the name from the account holder's
    #: own data. Additive, and empty when the answer names nothing.
    names: dict[str, uuid.UUID] = Field(default_factory=dict)


def _society_authorizer(
    request: Request,
    connection: ReadOnlyConnection,
    session: CurrentSession,
) -> Callable[[dict[str, Any]], None] | None:
    authorize = getattr(request.app.state, "society_input_authorizer", None)
    if authorize is None:
        return None
    return lambda document: authorize(connection, session, document)


@router.post("", summary="Resolve a Selection to captures, entities and evidence.")
def resolve_selection(
    plan: SelectionPlan,
    request: Request,
    connection: ReadOnlyConnection,
    session: CurrentSession,
) -> SelectionView:
    validated = validate(connection, plan, session)
    return _view(
        execute(
            connection,
            validated,
            store=get_services(request).store,
            society_authorizer=_society_authorizer(request, connection, session),
        )
    )


@router.get("/place-bridges", summary="List confirmed canonical-to-memory place bridges.")
def place_bridges(connection: ReadOnlyConnection, session: CurrentSession) -> list[PlaceBridgeView]:
    return [
        _place_bridge_view(decision)
        for decision in PlaceBridgeRepository(connection, session.workspace_id).confirmed()
    ]


@router.post(
    "/place-bridges",
    status_code=status.HTTP_201_CREATED,
    summary="Confirm a canonical-to-memory place bridge.",
)
def confirm_place_bridge(
    body: PlaceBridgeRequest,
    connection: ScopedConnection,
    session: CurrentSession,
) -> PlaceBridgeView:
    decision = PlaceBridgeRepository(connection, session.workspace_id).confirm(
        place_id=body.canonical_place_id,
        entity_id=body.memory_place_entity_id,
        actor=session.actor,
        reason=body.reason,
    )
    return _place_bridge_view(decision)


@router.post(
    "/place-bridges/{decision_id}/revoke",
    summary="Revoke a confirmed canonical-to-memory place bridge.",
)
def revoke_place_bridge(
    decision_id: uuid.UUID,
    body: PlaceBridgeRevocationRequest,
    connection: ScopedConnection,
    session: CurrentSession,
) -> PlaceBridgeView:
    decision = PlaceBridgeRepository(connection, session.workspace_id).revoke(
        decision_id, actor=session.actor, reason=body.reason
    )
    return _place_bridge_view(decision)


@router.get("/catalogue", summary="The named entities this session may filter by.")
def catalogue(connection: ReadOnlyConnection, session: CurrentSession) -> list[EntityView]:
    """What the interface offers as filter chips, and what the planner is allowed to reference.

    Named entities only. An entity with no name is one the user has not identified, and offering
    it as a filter would be offering to filter by somebody they have never met by name.
    """
    return [
        EntityView(
            entity_id=choice.entity_id,
            entity_class=choice.entity_class,
            display_name=choice.display_name,
            capture_count=0,
        )
        for choice in entity_catalogue(connection, session.workspace_id)
    ]


@router.post("/plan", summary="Propose a Selection from a question. Does not run it.")
def plan_from_question(
    body: QuestionRequest,
    request: Request,
    connection: ReadOnlyConnection,
    session: CurrentSession,
) -> SelectionPlan:
    client = _require_model(request)
    return propose_plan(
        client,
        body.question,
        entity_catalogue(connection, session.workspace_id),
        names=saved_names(connection, session.workspace_id),
    )


@router.post("/ask", summary="Answer a question, citing evidence, or decline to answer.")
def ask(
    body: QuestionRequest,
    request: Request,
    connection: ReadOnlyConnection,
    session: CurrentSession,
) -> AnswerView:
    plan = body.plan
    city_clause: AnswerClause | None = None
    if body.city_context is not None:
        plan, city_clause = _city_selection(
            body.city_context,
            request=request,
            connection=connection,
            session=session,
            supplied_plan=plan,
        )
        if plan is None:
            return AnswerView(
                answer=Answer(
                    clauses=[
                        city_clause,
                        AnswerClause(
                            text=(
                                "Unified place retrieval was not run because this admitted NYC "
                                "place has no confirmed memory-place bridge. No memory is claimed "
                                "to belong to the selected building."
                            ),
                            type=ClauseType.META,
                        ),
                    ]
                ),
                plan=None,
                selection=None,
                citations={},
                abstained=None,
                deterministic=True,
                repaired=False,
                execution=_execution((), ()),
            )
    # A model plans a question asked in words and composes a capture answer. A CONTENT plan,
    # supplied or resolved from a city selection, is answered from its rows without one, and a
    # configured model is not asked to rephrase it either.
    client = _require_model(request) if requires_model(plan) else get_services(request).model_client
    outcome = answer_question(
        connection,
        client,
        body.question,
        session,
        plan=plan,
        store=get_services(request).store,
        society_authorizer=_society_authorizer(request, connection, session),
        before_compose=composer_rights_check(connection, session.workspace_id),
    )
    answer = outcome.answer
    if city_clause is not None:
        answer = Answer(clauses=[city_clause, *answer.clauses[:7]])
    return AnswerView(
        answer=answer,
        plan=outcome.plan,
        selection=None if outcome.result is None else _view(outcome.result),
        citations=(
            {}
            if outcome.packet is None
            else {item.token: item.uri for item in outcome.packet.items}
        ),
        abstained=outcome.abstention,
        deterministic=outcome.deterministic,
        repaired=outcome.repaired,
        execution=_execution(outcome.calls, outcome.rejections),
        names=dict(outcome.names),
    )


def _city_selection(
    context: CityContextRequest,
    *,
    request: Request,
    connection: Any,
    session: Any,
    supplied_plan: SelectionPlan | None,
) -> tuple[SelectionPlan | None, AnswerClause]:
    """Resolve semantic identity and its place bridge without consulting Google content."""
    try:
        catalog = EnvironmentRepository(
            connection, session.workspace_id, get_services(request).store
        ).read_features(context.admission_id, feature_id=context.feature_id)
    except UnknownEnvironmentResource as exc:
        raise HTTPException(status_code=404, detail="no such semantic city selection") from exc
    except EnvironmentResourceWithdrawn as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except EnvironmentOperationDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if catalog.provider_key != NYC_OPEN_DATA_PROVIDER_KEY or len(catalog.features) != 1:
        raise HTTPException(
            status_code=422,
            detail="the city selection is not admitted NYC Open Data",
        )
    feature = catalog.features[0]
    provider_feature_id = feature.get("provider_feature_id")
    properties = feature.get("semantic_properties")
    if (
        not isinstance(provider_feature_id, str)
        or re.fullmatch(r"doitt_id:[1-9][0-9]*", provider_feature_id) is None
        or not isinstance(properties, dict)
    ):
        raise HTTPException(status_code=422, detail="the semantic city feature is malformed")
    bridges = PlaceBridgeRepository(connection, session.workspace_id).confirmed()
    bridge = next((held for held in bridges if held.place_id == catalog.place_id), None)
    if bridge is None:
        if supplied_plan is not None:
            raise HTTPException(
                status_code=422,
                detail="the supplied plan cannot be verified without a confirmed place bridge",
            )
        plan = None
    else:
        if supplied_plan is not None and (
            supplied_plan.intent is not Intent.CONTENT
            or supplied_plan.place is None
            or bridge.entity_id not in supplied_plan.place.ids
        ):
            raise HTTPException(
                status_code=422,
                detail="the supplied plan does not match the selected semantic city place",
            )
        plan = supplied_plan or SelectionPlan(
            intent=Intent.CONTENT,
            place=PlaceSelector(ids=[bridge.entity_id]),
            content=ContentSelector(scope=ContentScope.RELATED),
        )
    name = properties.get("name")
    bin_value = properties.get("bin")
    label = name if isinstance(name, str) and name else "an unnamed NYC building footprint"
    bin_text = (
        bin_value.removeprefix("bin:")
        if isinstance(bin_value, str) and bin_value.startswith("bin:")
        else "not supplied"
    )
    return plan, AnswerClause(
        text=(
            f"{label} is selected from official NYC BUILDING data. Its semantic identifiers "
            f"are {provider_feature_id.upper()} and BIN {bin_text}; Google supplied no identity."
        ),
        type=ClauseType.META,
    )


@router.post("/packet", summary="The evidence a Selection would offer, without composing text.")
def packet(
    plan: SelectionPlan, request: Request, connection: ReadOnlyConnection, session: CurrentSession
) -> dict[str, Any]:
    """The deterministic half of the answer path, exposed on its own.

    Useful to the interface, which can show what a question found without spending a model call,
    and useful to an evaluation run, which needs the retrieval measured separately from the
    composition.
    """
    validated = validate(connection, plan, session)
    result = execute(
        connection,
        validated,
        store=get_services(request).store,
        society_authorizer=_society_authorizer(request, connection, session),
    )
    if result.intent is Intent.CONTENT:
        content = build_content_packet(result)
        return {
            "citable": True,
            "total_matched": content.total_matched,
            "truncated": content.total_matched > len(content.items),
            "items": [
                {
                    "token": item.token,
                    "truth_class": item.truth_class,
                    "result_kind": item.result_kind,
                    "source_id": item.source_id,
                    "lineage_ids": list(item.lineage_ids),
                    "label": item.label,
                    "personal_visit_evidence": item.personal_visit_evidence,
                }
                for item in content.items
            ],
            "values": [],
        }
    built = build_packet(connection, result, workspace_id=session.workspace_id)
    return {
        "citable": built.citable,
        "total_matched": built.total_matched,
        "truncated": built.truncated,
        "items": [
            {
                "token": item.token,
                "uri": item.uri,
                "span_id": str(item.span_id),
                "capture_id": str(item.capture_id),
                "captured_at": item.captured_at,
                "trust": item.trust,
                "text": item.text,
            }
            for item in built.items
        ],
        "values": [
            {"key": value.key, "text": value.text, "label": value.label} for value in built.values
        ],
    }


def _execution(
    calls: tuple[ModelCall, ...],
    rejections: tuple[str, ...],
    *,
    prompt_version: str = PROMPT_VERSION,
) -> ExecutionView:
    """The executed half of one request, whichever path made it.

    ``prompt_version`` is a parameter rather than the module constant because two paths
    share this block and they are versioned separately. An appearance proposal composed under
    ``proposal-1`` reported as ``selection-3`` would be a record naming a prompt that had
    nothing to do with it, and both constants are inputs to the response cache key, so the two
    are not interchangeable even when they happen to move together.
    """
    return ExecutionView(
        prompt_version=prompt_version,
        rejections=list(rejections),
        calls=[
            ModelCallView(
                role=call.role,
                requested_model=call.requested_model,
                served_model=call.served_model,
                used_fallback=call.used_fallback,
                attempts=call.attempts,
                latency_ms=call.latency_ms,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                reasoning_tokens=call.reasoning_tokens,
                usd=call.usd,
            )
            for call in calls
        ],
    )


def _require_model(request: Request) -> ModelClient:
    client = get_services(request).model_client
    if client is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "no model credential is configured on this instance. Every other endpoint "
                "works; this one needs a model and will not guess without one."
            ),
        )
    return client


def _view(result: SelectionResult) -> SelectionView:
    return SelectionView(
        captures=[
            CaptureView(
                capture_id=capture.capture_id,
                blob=capture.blob_id.ni_uri,
                captured_at=capture.captured_at,
                support=[
                    SupportView(
                        span_id=support.span_id,
                        assertion_id=support.assertion_id,
                        dimension=support.dimension,
                        entity_id=support.entity_id,
                    )
                    for support in capture.support
                ],
            )
            for capture in result.captures
        ],
        entities=[
            EntityView(
                entity_id=entity.entity_id,
                entity_class=entity.entity_class,
                display_name=entity.display_name,
                capture_count=entity.capture_count,
            )
            for entity in result.entities
        ],
        total_matched=result.total_matched,
        truncated=result.truncated,
        includes_proposals=result.includes_proposals,
        content=[
            ContentView(
                result_kind=item.result_kind,
                origin_kind=item.origin_kind,
                content_kind=item.content_kind,
                authored_role=item.authored_role,
                place_relationship=item.place_relationship,
                match_reason=item.match_reason,
                memory_place_entity_id=item.memory_place_entity_id,
                canonical_place_id=item.canonical_place_id,
                world_id=item.world_id,
                version_id=item.version_id,
                source_id=item.source_id,
                lineage_ids=list(item.lineage_ids),
                label=item.label,
                availability=item.availability,
                personal_visit_evidence=item.personal_visit_evidence,
            )
            for item in result.content
        ],
        next_page=result.next_page,
    )


def _place_bridge_view(decision: PlaceBridgeDecision) -> PlaceBridgeView:
    return PlaceBridgeView(
        decision_id=decision.decision_id,
        canonical_place_id=decision.place_id,
        memory_place_entity_id=decision.entity_id,
        decision=decision.decision,
        supersedes_decision_id=decision.supersedes_decision_id,
        decided_by=decision.decided_by,
        reason=decision.reason,
        decided_at=decision.decided_at,
    )


# --------------------------------------------------------------------------------------------
# Asking for the world to look different.
#
# On the same router as the two read routes above, because it is the same seam: a person types
# one sentence into one place, and what happens next depends on what the sentence turns out to
# be. Splitting it across two prefixes would make the browser decide that, and the browser
# cannot: deciding is the first model call.
#
# It is a READ route in the only sense that matters here. It opens the same read-only connection
# the other three do, it returns a proposal rather than applying one, and there is no code path
# from it to a write. The world style lifecycle is where a proposal becomes a preview, and that
# is `POST /world/styles/previews`, which the browser posts to itself with the provenance this
# route hands it. Two requests rather than one, deliberately: the proposal reaches the person's
# own confirmation surface between them, which is the whole guarantee.
# --------------------------------------------------------------------------------------------


class AppearanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The same bound the question route uses, because it is the same text box.
    utterance: Annotated[str, Field(min_length=1, max_length=1000)]


class AppearanceProfileView(BaseModel):
    """The complete reference a preview would be created from.

    Complete rather than a diff: `POST /world/styles/previews` takes a whole reference and the
    registry fills any control the body omits from its DEFAULT, not from the current value. A
    diff posted there would silently reset every control the request did not mention.
    ``changed`` is what a surface says out loud; ``parameters`` is what it sends.
    """

    model_config = ConfigDict(extra="forbid")

    profile_id: str
    profile_version: int
    parameters: dict[str, Any]
    #: The reviewed modules that own the changed controls. Named by the draft, checked here.
    modules: list[str]
    #: Only the controls whose value moved.
    changed: list[str]


class AppearanceProposalView(BaseModel):
    """A proposal the browser may post to the world style lifecycle, with its provenance.

    ``model_id`` and ``prompt_version`` are the two fields that make this a Companion proposal
    rather than a Settings one, and the world repository refuses an origin of ``companion``
    without both plus at least one reference id. They are returned here so the browser sends
    back what actually happened rather than what it assumed: ``model_id`` is the identifier the
    response body echoed, which differs from the configured one exactly when the fallback served.
    """

    model_config = ConfigDict(extra="forbid")

    profile: AppearanceProfileView
    #: Opaque ids naming the topology source slots that motivated the change. Never bytes.
    reference_ids: list[str]
    #: The EXECUTED identifier that drew this, read off the response and never off the manifest.
    model_id: str
    prompt_version: str
    #: What the Companion says about the change. Model output, rendered as speech, never stored
    #: as style data and never interpreted as one.
    spoken: str


class AppearanceRefusalView(BaseModel):
    """Why an appearance request produced no proposal, in a code a surface branches on.

    ``detail`` is this system's own words about its own validation. It never carries the
    utterance and never carries corpus content, so returning it is not a channel out of the
    workspace. What the person reads is a reviewed sentence the client chooses from ``code``;
    ``detail`` is for the record and for whoever has to fix it.
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    detail: str


class AppearanceView(BaseModel):
    """What one utterance produced.

    ``classification`` is ``question`` far more often than it is anything else, and that case
    carries no proposal and NO REFUSAL. A question is not a failure of this path: it is the
    path declining to take one, and the browser's next move is `POST /selection/ask`.
    """

    model_config = ConfigDict(extra="forbid")

    classification: Literal["question", "appearance"]
    proposal: AppearanceProposalView | None
    refusal: AppearanceRefusalView | None
    #: Which models were asked, how long they took and what they spent. The same block the
    #: answer route returns, from the same recorder, so one measurement can read both.
    execution: ExecutionView


@router.post(
    "/appearance",
    summary="Read one utterance as a bounded appearance proposal, or decline to.",
)
def appearance(
    body: AppearanceRequest,
    request: Request,
    connection: ReadOnlyConnection,
    session: CurrentSession,
) -> AppearanceView:
    client = _require_model(request)
    current: StyleReference | None = None
    try:
        current = WorldStyleRepository(connection, session.workspace_id).current().global_style
    except WorldNotConfigured:
        # Left as None and refused inside `propose_appearance`, rather than raised as a 409.
        # A person who asked for a warmer world on a workspace with no reviewed world is owed a
        # sentence, and `world_not_configured` on a route they did not know they were calling
        # is not one. The classifier still runs, so the answer path still gets its utterance.
        current = None
    outcome = propose_appearance(connection, client, body.utterance, session, current=current)
    return AppearanceView(
        classification=outcome.kind.value,
        proposal=(
            None
            if outcome.proposal is None
            else AppearanceProposalView(
                profile=AppearanceProfileView(
                    profile_id=outcome.proposal.profile.profile_id,
                    profile_version=outcome.proposal.profile.profile_version,
                    parameters=dict(outcome.proposal.profile.parameters),
                    modules=list(outcome.proposal.modules),
                    changed=list(outcome.proposal.changed),
                ),
                reference_ids=list(outcome.proposal.reference_ids),
                # Never null on this branch: a proposal exists only because a draft call
                # returned, and a returned call carries the identifier that served it.
                model_id=outcome.model_id or "",
                prompt_version=PROPOSAL_PROMPT_VERSION,
                spoken=outcome.proposal.spoken,
            )
        ),
        refusal=(
            None
            if outcome.refusal is None
            else AppearanceRefusalView(
                code=outcome.refusal.code.value, detail=outcome.refusal.detail
            )
        ),
        execution=_execution(outcome.calls, (), prompt_version=PROPOSAL_PROMPT_VERSION),
    )


# The NYC environment panel is already an explicitly scoped editing surface. Its utterance goes
# directly to this closed operation chooser and never through the measured appearance classifier.


class EnvironmentTransformContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x_mm: StrictInt
    y_mm: StrictInt
    z_mm: StrictInt
    yaw_microradians: StrictInt = Field(ge=0, le=6_283_185)
    scale_milli: StrictInt = Field(ge=1, le=1_000_000)


class EnvironmentProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    utterance: Annotated[str, Field(min_length=1, max_length=1000)]
    version_id: uuid.UUID
    base_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    admission_id: uuid.UUID
    selected_feature_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    region_id: str = Field(min_length=1, max_length=500)
    transform: EnvironmentTransformContext
    origin_role: Literal["fictional", "personal"]


class PlaceEnvironmentProposalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["place_selected_feature"]
    version_id: uuid.UUID
    base_state_sha256: str
    instance_id: str
    admission_id: uuid.UUID
    render_asset_id: uuid.UUID
    publication_id: uuid.UUID
    feature_id: str
    render_batch_id: int
    source_anchor_frame_name: str
    source_anchor_coordinate_scale: int
    source_anchor_coordinates: tuple[int, ...] = Field(min_length=2, max_length=3)
    region_id: str
    transform: EnvironmentTransformContext
    origin_role: Literal["fictional", "personal"]
    model_id: str | None
    prompt_version: str


class RemoveEnvironmentProposalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["remove_selected_authored_instance"]
    version_id: uuid.UUID
    base_state_sha256: str
    instance_id: str
    model_id: str | None
    prompt_version: str


class UndoEnvironmentProposalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["undo_latest_version_edit"]
    version_id: uuid.UUID
    base_state_sha256: str
    model_id: str | None
    prompt_version: str


EnvironmentTypedProposalView = (
    PlaceEnvironmentProposalView | RemoveEnvironmentProposalView | UndoEnvironmentProposalView
)


class EnvironmentProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal: EnvironmentTypedProposalView | None
    refusal: AppearanceRefusalView | None
    execution: ExecutionView


def _has_reversible_edit(version: Any) -> bool:
    undone = {edit.undone_edit_id for edit in version.edits if edit.undone_edit_id is not None}
    return any(edit.kind != "undo" and edit.edit_id not in undone for edit in version.edits)


@router.post(
    "/environment",
    summary="Propose one typed NYC environment edit without changing world state.",
)
def environment_proposal(
    body: EnvironmentProposalRequest,
    request: Request,
    connection: ReadOnlyConnection,
    session: CurrentSession,
) -> EnvironmentProposalResponse:
    client = _require_model(request)
    empty_execution = _execution((), (), prompt_version=ENVIRONMENT_PROMPT_VERSION)
    if body.selected_feature_id is None:
        return EnvironmentProposalResponse(
            proposal=None,
            refusal=AppearanceRefusalView(
                code="no_selected_feature", detail="select an NYC Open Data feature first"
            ),
            execution=empty_execution,
        )

    services = get_services(request)
    objects = WorldObjectRepository(connection, session.workspace_id, store=services.store)
    version = objects.version(body.version_id)
    if version.state_sha256 != body.base_state_sha256:
        return EnvironmentProposalResponse(
            proposal=None,
            refusal=AppearanceRefusalView(
                code="stale_version",
                detail="the alternate version changed; reload it and request a fresh proposal",
            ),
            execution=empty_execution,
        )

    try:
        catalog = EnvironmentRepository(
            connection, session.workspace_id, services.store
        ).read_features(body.admission_id, feature_id=body.selected_feature_id)
    except UnknownEnvironmentResource as exc:
        raise HTTPException(status_code=404, detail="no such environment selection") from exc
    except EnvironmentResourceWithdrawn as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except EnvironmentOperationDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if len(catalog.features) != 1:
        return EnvironmentProposalResponse(
            proposal=None,
            refusal=AppearanceRefusalView(
                code="no_selected_feature",
                detail="the selected feature is not in the current admitted publication",
            ),
            execution=empty_execution,
        )
    feature = catalog.features[0]
    provider_feature_id = feature.get("provider_feature_id")
    if (
        catalog.provider_key != NYC_OPEN_DATA_PROVIDER_KEY
        or not isinstance(provider_feature_id, str)
        or re.fullmatch(r"doitt_id:[1-9][0-9]*", provider_feature_id) is None
    ):
        return EnvironmentProposalResponse(
            proposal=None,
            refusal=AppearanceRefusalView(
                code="unsupported_source",
                detail="the selected feature is not from the admitted NYC Open Data source",
            ),
            execution=empty_execution,
        )
    instance_id = f"nyc-open-data:{provider_feature_id.replace(':', '-')}"
    bbox = feature.get("bbox")
    render_batch_id = feature.get("render_batch_id")
    frame_name = catalog.geographic_frame.get("name")
    if (
        not isinstance(bbox, list)
        or len(bbox) not in (4, 6)
        or any(isinstance(value, bool) or not isinstance(value, int) for value in bbox)
        or isinstance(render_batch_id, bool)
        or not isinstance(render_batch_id, int)
        or not isinstance(frame_name, str)
    ):
        return EnvironmentProposalResponse(
            proposal=None,
            refusal=AppearanceRefusalView(
                code="unsupported", detail="the selected feature binding is malformed"
            ),
            execution=empty_execution,
        )
    dimensions = len(bbox) // 2
    placement = EnvironmentPlacement(
        instance_id=instance_id,
        admission_id=catalog.admission_id,
        render_asset_id=catalog.render_asset_id,
        publication_id=catalog.publication_id,
        selection=EnvironmentSelection("feature", body.selected_feature_id, render_batch_id),
        source_anchor=SourceAnchor(
            frame_name,
            catalog.coordinate_scale,
            tuple((bbox[index] + bbox[index + dimensions] + 1) // 2 for index in range(dimensions)),
        ),
        region_id=body.region_id,
        transform=Transform(
            body.transform.x_mm,
            body.transform.y_mm,
            body.transform.z_mm,
            body.transform.yaw_microradians,
            body.transform.scale_milli,
        ),
        origin=ObjectOrigin("authored", body.origin_role),
    )
    selected_instance = next(
        (
            instance
            for instance in version.environment_instances
            if instance.instance_id == instance_id and not instance.removed
        ),
        None,
    )
    validated = None
    if selected_instance is None:
        try:
            validated = objects.validate_environment_placement(
                body.version_id,
                placement,
                base_state_sha256=body.base_state_sha256,
            )
        except (InvalidEnvironmentData, InvalidEnvironmentState) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (
            StaleObjectBase,
            InvalidatedSourceVersion,
            EnvironmentBindingDrift,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except EnvironmentSourceWithdrawn as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except EnvironmentCompositionDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except UnavailableAsset as exc:
            raise HTTPException(status_code=424, detail=str(exc)) from exc
    operations = [
        (
            EnvironmentOperation.REMOVE_SELECTED_AUTHORED_INSTANCE
            if selected_instance is not None
            else EnvironmentOperation.PLACE_SELECTED_FEATURE
        )
    ]
    if _has_reversible_edit(version):
        operations.append(EnvironmentOperation.UNDO_LATEST_VERSION_EDIT)
    # No saved name reaches a hosted model; the drafter needs none to pick an operation.
    utterance = redact_names(body.utterance, saved_names(connection, session.workspace_id)).text
    decision = draft_environment_operation(client, utterance, operations)
    execution = _execution(decision.calls, (), prompt_version=ENVIRONMENT_PROMPT_VERSION)
    if decision.operation is None:
        assert decision.refusal is not None
        return EnvironmentProposalResponse(
            proposal=None,
            refusal=AppearanceRefusalView(
                code=decision.refusal.code.value, detail=decision.refusal.detail
            ),
            execution=execution,
        )
    common = {
        "version_id": body.version_id,
        "base_state_sha256": body.base_state_sha256,
        "model_id": decision.model_id,
        "prompt_version": ENVIRONMENT_PROMPT_VERSION,
    }
    if decision.operation is EnvironmentOperation.REMOVE_SELECTED_AUTHORED_INSTANCE:
        proposal: EnvironmentTypedProposalView = RemoveEnvironmentProposalView(
            operation=decision.operation.value, instance_id=instance_id, **common
        )
    elif decision.operation is EnvironmentOperation.UNDO_LATEST_VERSION_EDIT:
        proposal = UndoEnvironmentProposalView(operation=decision.operation.value, **common)
    else:
        assert validated is not None
        source = validated.source
        assert source.publication_id is not None
        assert source.selection.feature_id is not None
        assert source.selection.render_batch_id is not None
        proposal = PlaceEnvironmentProposalView(
            operation=decision.operation.value,
            instance_id=validated.instance_id,
            admission_id=source.admission_id,
            render_asset_id=source.render_asset_id,
            publication_id=source.publication_id,
            feature_id=source.selection.feature_id,
            render_batch_id=source.selection.render_batch_id,
            source_anchor_frame_name=source.anchor.frame_name,
            source_anchor_coordinate_scale=source.anchor.coordinate_scale,
            source_anchor_coordinates=source.anchor.coordinates,
            region_id=validated.region_id,
            transform=EnvironmentTransformContext(
                x_mm=validated.transform.x_mm,
                y_mm=validated.transform.y_mm,
                z_mm=validated.transform.z_mm,
                yaw_microradians=validated.transform.yaw_microradians,
                scale_milli=validated.transform.scale_milli,
            ),
            origin_role=validated.origin.role,
            **common,
        )
    return EnvironmentProposalResponse(proposal=proposal, refusal=None, execution=execution)
