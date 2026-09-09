"""Durable Companion memory: read it back, correct it, delete it.

The Companion's memory of what it asked, which escapes were taken and what was said has lived in
one browser session and been lost on reload. `product-direction.md` makes the durable half a
delivery gate on the Companion continuity row: "Persist approved memory, retrieve it across
sessions, and support correction and deletion; this is not model weight training." These four
routes are the retrieve, the correct and the delete; migration 0043 is the persist.

**Nothing here is a write to the graph.** `interaction-model.md` 4.3 fixes that "NO FREE-TEXT
ANSWER AND NO CHOICE EVER MUTATES THE GRAPH DIRECTLY", and a surface that stored conversation
would be a tempting place to break it. There is no `ProposalDraft` in this module, no
`ProposalGate`, and no path from a stored answer to one: what is recorded here is what the person
was already shown, after they were shown it.

**And nothing here reaches the interaction-policy plane.** `WorldInteractionPolicyRepository`
refuses a proposal whose input carries `conversation`, `messages`, `raw_utterance`, `transcript`
or `prompt_text`. This module imports no interaction type at all, which is the same guarantee
stated structurally rather than promised.

The actor is never in a body. It comes from the resolved session, like every other surface in this
package, and it is the scope rather than the provenance: two people sharing a workspace have not
had the same conversation.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, ScopedConnection
from exulanica.world.companion_memory import (
    DEFAULT_RECENT_LIMIT,
    MAX_RECENT_LIMIT,
    AnswerCitation,
    AnswerOrigin,
    CompanionAnswer,
    CompanionEscape,
    CompanionMemoryRepository,
    EscapeKind,
    InvalidCompanionMemory,
    RecordedAnswer,
    RecordedEscape,
    UnknownCompanionMemory,
)

router = APIRouter(prefix="/companion/memory", tags=["companion"])

_MAX_QUESTION = 2000
_MAX_ANSWER = 8000
_MAX_NOTE = 2000
#: One chip per photograph, and the rail that renders them is not unbounded either.
_MAX_CITATIONS = 64


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    """The one failure shape this package answers with.

    Copied rather than imported, as `geometry.py`, `world_read.py` and `world_write.py` each copy
    it. A bare `HTTPException` would answer `{"detail": ...}` with no `code`, and the web client's
    `toApiError` then synthesises `http_404` and loses the branch the caller needs.
    """
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


# -- what a caller sends ------------------------------------------------------------------


class CitationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_id: uuid.UUID
    capture_id: uuid.UUID
    ordinal: Annotated[int, Field(ge=0, le=4096)]


class AnswerBody(BaseModel):
    """An answer that has already rendered, handed back so a reload can show it again.

    Every model field is what the response said, never what the manifest says.
    `companion-question.md` 4: a record derived from configuration reports a fallback wrongly and
    silently, and this is the record.
    """

    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, Field(min_length=1, max_length=_MAX_QUESTION)]
    answer_text: Annotated[str, Field(max_length=_MAX_ANSWER)]
    abstained: (
        Annotated[
            str,
            Field(
                pattern=r"^UNANSWERABLE_(NOT_CAPTURED|AMBIGUOUS|NOT_IN_MODALITY|NOT_UNDERSTOOD)$"
            ),
        ]
        | None
    ) = None
    deterministic: bool = False
    repaired: bool = False
    served_model: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    planned_by: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    prompt_version: Annotated[str, Field(min_length=1, max_length=64)]
    latency_ms: Annotated[int, Field(ge=0)]
    citations: Annotated[list[CitationBody], Field(max_length=_MAX_CITATIONS)] = Field(
        default_factory=list
    )


class EscapeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    escape: EscapeKind
    intent: Annotated[str, Field(min_length=1, max_length=64)]
    entity_id: uuid.UUID | None = None
    turn_id: Annotated[str, Field(min_length=1, max_length=128)]


class CorrectionBody(BaseModel):
    """The person's own words. `answer_text` is what stands afterwards.

    `correction_note` is why they corrected it, which is a different sentence from the correction
    and is the one a later reader needs to understand what the system got wrong.
    """

    model_config = ConfigDict(extra="forbid")

    answer_text: Annotated[str, Field(min_length=1, max_length=_MAX_ANSWER)]
    correction_note: Annotated[str, Field(max_length=_MAX_NOTE)] | None = None


# -- what a caller receives ---------------------------------------------------------------


class CitationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_id: uuid.UUID
    capture_id: uuid.UUID
    ordinal: int


class AnswerView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_id: uuid.UUID
    asked_at: dt.datetime
    question: str
    answer_text: str
    abstained: str | None
    deterministic: bool
    repaired: bool
    served_model: str | None
    planned_by: str | None
    prompt_version: str
    latency_ms: int
    origin: AnswerOrigin
    supersedes: uuid.UUID | None
    correction_note: str | None
    citations: list[CitationView]


class EscapeView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    escape_id: uuid.UUID
    taken_at: dt.datetime
    escape: EscapeKind
    intent: str
    entity_id: uuid.UUID | None
    turn_id: str


class MemoryView(BaseModel):
    """One read, because a session open needs both halves and two requests would race."""

    model_config = ConfigDict(extra="forbid")

    answers: list[AnswerView]
    escapes: list[EscapeView]


def read_memory(
    connection: ReadOnlyConnection, session: CurrentSession
) -> CompanionMemoryRepository:
    return CompanionMemoryRepository(connection, session.workspace_id, session.actor)


def write_memory(
    connection: ScopedConnection, session: CurrentSession
) -> CompanionMemoryRepository:
    return CompanionMemoryRepository(connection, session.workspace_id, session.actor)


ReadMemory = Annotated[CompanionMemoryRepository, Depends(read_memory)]
WriteMemory = Annotated[CompanionMemoryRepository, Depends(write_memory)]


@router.get(
    "/recent",
    response_model=MemoryView,
    summary="What this Companion asked you, what it answered, and what you told it to leave alone.",
)
def recent(
    repository: ReadMemory,
    limit: Annotated[int, Query(ge=1, le=MAX_RECENT_LIMIT)] = DEFAULT_RECENT_LIMIT,
) -> MemoryView:
    snapshot = repository.recent(limit=limit)
    return MemoryView(
        answers=[_answer_view(answer) for answer in snapshot.answers],
        escapes=[_escape_view(escape) for escape in snapshot.escapes],
    )


@router.post(
    "/answers",
    response_model=AnswerView,
    status_code=201,
    summary="Keep an answer that has already been shown, so a reload does not ask again.",
)
def record_answer(body: AnswerBody, repository: WriteMemory) -> AnswerView | JSONResponse:
    try:
        answer = repository.record_answer(
            RecordedAnswer(
                question=body.question,
                answer_text=body.answer_text,
                abstained=body.abstained,
                deterministic=body.deterministic,
                repaired=body.repaired,
                served_model=body.served_model,
                planned_by=body.planned_by,
                prompt_version=body.prompt_version,
                latency_ms=body.latency_ms,
                citations=tuple(
                    AnswerCitation(
                        span_id=citation.span_id,
                        capture_id=citation.capture_id,
                        ordinal=citation.ordinal,
                    )
                    for citation in body.citations
                ),
            )
        )
    except InvalidCompanionMemory as exc:
        return _problem(422, "invalid_companion_memory", str(exc))
    return _answer_view(answer)


@router.post(
    "/escapes",
    response_model=EscapeView,
    status_code=201,
    summary="Keep an escape, so its cooldown outlives the page it was taken on.",
)
def record_escape(body: EscapeBody, repository: WriteMemory) -> EscapeView | JSONResponse:
    try:
        escape = repository.record_escape(
            RecordedEscape(
                escape=body.escape,
                intent=body.intent,
                entity_id=body.entity_id,
                turn_id=body.turn_id,
            )
        )
    except InvalidCompanionMemory as exc:
        return _problem(422, "invalid_companion_memory", str(exc))
    return _escape_view(escape)


@router.post(
    "/answers/{answer_id}/corrections",
    response_model=AnswerView,
    status_code=201,
    summary="Say what the answer should have been. The old one is superseded, never rewritten.",
)
def correct_answer(
    answer_id: Annotated[uuid.UUID, Path()],
    body: CorrectionBody,
    repository: WriteMemory,
) -> AnswerView | JSONResponse:
    try:
        answer = repository.correct(
            answer_id,
            answer_text=body.answer_text,
            correction_note=body.correction_note,
        )
    except UnknownCompanionMemory as exc:
        # Absent, withdrawn, another person's or another workspace's are one code, deliberately.
        # `app.py` records the rule: answering differently would let the difference between a
        # refusal and a 404 be read as an existence oracle.
        return _problem(404, "unknown_reference", str(exc))
    except InvalidCompanionMemory as exc:
        return _problem(409, "companion_memory_already_corrected", str(exc))
    return _answer_view(answer)


@router.delete(
    "/answers/{answer_id}",
    status_code=204,
    summary="Delete one memory, and every correction of it, for good.",
)
def delete_answer(
    answer_id: Annotated[uuid.UUID, Path()], repository: WriteMemory
) -> Response:
    # `Response` rather than `Response | JSONResponse`, because FastAPI reads a union return
    # annotation as a response model and refuses to build one for a 204. `JSONResponse` is a
    # `Response`, so the 404 branch below still returns what it says it returns.
    try:
        repository.withdraw(answer_id)
    except UnknownCompanionMemory as exc:
        return _problem(404, "unknown_reference", str(exc))
    return Response(status_code=204)


def _answer_view(answer: CompanionAnswer) -> AnswerView:
    return AnswerView(
        answer_id=answer.answer_id,
        asked_at=answer.asked_at,
        question=answer.question,
        answer_text=answer.answer_text,
        abstained=answer.abstained,
        deterministic=answer.deterministic,
        repaired=answer.repaired,
        served_model=answer.served_model,
        planned_by=answer.planned_by,
        prompt_version=answer.prompt_version,
        latency_ms=answer.latency_ms,
        origin=answer.origin,
        supersedes=answer.supersedes,
        correction_note=answer.correction_note,
        citations=[
            CitationView(
                span_id=citation.span_id,
                capture_id=citation.capture_id,
                ordinal=citation.ordinal,
            )
            for citation in answer.citations
        ],
    )


def _escape_view(escape: CompanionEscape) -> EscapeView:
    return EscapeView(
        escape_id=escape.escape_id,
        taken_at=escape.taken_at,
        escape=escape.escape,
        intent=escape.intent,
        entity_id=escape.entity_id,
        turn_id=escape.turn_id,
    )
