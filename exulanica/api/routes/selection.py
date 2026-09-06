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
from typing import Annotated, Any

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
from exulanica.selection.question import answer_question, propose_plan

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


class AnswerView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: Answer
    plan: SelectionPlan
    selection: SelectionView
    citations: dict[str, str] = Field(
        description="Citation token to the permalink it resolves to, for this response only."
    )
    abstained: Abstention | None
    #: True when the composer's output was discarded and the deterministic answer used instead.
    deterministic: bool
    repaired: bool


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
        selection=_view(outcome.result),
        citations={item.token: item.uri for item in outcome.packet.items},
        abstained=outcome.abstention,
        deterministic=outcome.deterministic,
        repaired=outcome.repaired,
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
