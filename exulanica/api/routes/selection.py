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

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, get_services
from exulanica.models.client import ModelClient
from exulanica.selection import (
    Abstention,
    Answer,
    SelectionPlan,
    SelectionResult,
    build_packet,
    entity_catalogue,
    execute,
    validate,
)
from exulanica.selection.proposal import PROMPT_VERSION as PROPOSAL_PROMPT_VERSION
from exulanica.selection.proposal import propose_appearance
from exulanica.selection.question import PROMPT_VERSION, ModelCall, answer_question, propose_plan
from exulanica.world import StyleReference, WorldNotConfigured, WorldStyleRepository

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


class QuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, Field(min_length=1, max_length=1000)]
    #: A plan the user has already seen and approved. When absent the model proposes one.
    plan: SelectionPlan | None = None


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
    rather than inferred from configuration". Before this block the response carried no executed
    identifier, no latency and no usage at all, so the claim could only be read off the manifest.

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


@router.post("", summary="Resolve a Selection to captures, entities and evidence.")
def resolve_selection(
    plan: SelectionPlan, connection: ReadOnlyConnection, session: CurrentSession
) -> SelectionView:
    validated = validate(connection, plan, session)
    return _view(execute(connection, validated))


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
    return propose_plan(client, body.question, entity_catalogue(connection, session.workspace_id))


@router.post("/ask", summary="Answer a question, citing evidence, or decline to answer.")
def ask(
    body: QuestionRequest,
    request: Request,
    connection: ReadOnlyConnection,
    session: CurrentSession,
) -> AnswerView:
    client = _require_model(request)
    outcome = answer_question(connection, client, body.question, session, plan=body.plan)
    return AnswerView(
        answer=outcome.answer,
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
    )


@router.post("/packet", summary="The evidence a Selection would offer, without composing text.")
def packet(
    plan: SelectionPlan, connection: ReadOnlyConnection, session: CurrentSession
) -> dict[str, Any]:
    """The deterministic half of the answer path, exposed on its own.

    Useful to the interface, which can show what a question found without spending a model call,
    and useful to an evaluation run, which needs the retrieval measured separately from the
    composition.
    """
    validated = validate(connection, plan, session)
    result = execute(connection, validated)
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

    ``prompt_version`` is a parameter rather than the module constant because two paths now
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
    path declining to take one, and the browser's next move is `POST /selection/ask`, exactly
    as before this route existed.
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
