"""A recorded decision asked again of another model, and the comparison (migration 0216).

*   ``POST /world/versions/{version_id}/society/decisions/{request_id}/asks`` asks the chosen model
    the identical request, once, under the spending bound the body states, and answers 201 with the
    ask and its answer: what it chose and what it cost. Nothing is applied to the world.
*   ``GET /world/versions/{version_id}/society/decisions/{request_id}/asks`` answers the original
    answer and every ask beside it, each with whether its choice and its kind are the original's.

A request the workspace does not hold answers as the decision read does: an unknown resource.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.decision_asks import ModelNotAsked, ask_again
from exulanica.api.dependencies import (
    CurrentSession,
    ScopedConnection,
    ScopedSessions,
    get_services,
)
from exulanica.api.routes.society import _call, _repository
from exulanica.api.services import Services
from exulanica.api.world_scope import WorldId
from exulanica.world.society_decision_asks import (
    DecisionAskRefused,
    asks,
    comparison,
    recorded,
)

__all__ = ["router"]

router = APIRouter(prefix="/world", tags=["society"])


class ModelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=64)
    model_id: str = Field(min_length=1, max_length=200)


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The model to ask, as a person's model choice names one.
    model: ModelBody
    #: The most this ask may spend, in USD.
    bound_usd: Decimal = Field(gt=0, max_digits=12, decimal_places=8)
    idempotency_key: uuid.UUID | None = None


def _refusal(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"code": code, "detail": detail}, status_code=status)


def _view(held: Any, row: dict[str, Any]) -> dict[str, Any]:
    """One ask as the comparison states it."""
    return comparison(held, [row])["asks"][0]


@router.post("/versions/{version_id}/society/decisions/{request_id}/asks", status_code=201)
def ask_decision_again(
    version_id: uuid.UUID,
    request_id: uuid.UUID,
    body: AskBody,
    connection: ScopedConnection,
    sessions: ScopedSessions,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    services: Annotated[Services, Depends(get_services)],
) -> Any:
    """Ask another model a recorded decision again, once, never applying its answer."""

    def held() -> Any:
        with connection.transaction():
            return recorded(
                _repository(connection, session, request, world_id), version_id, request_id
            )

    found = _call(held, invalid_status=409)
    if isinstance(found, JSONResponse):
        return found
    try:
        row = ask_again(
            services,
            found,
            sessions,
            workspace_id=session.workspace_id,
            model=body.model.model_dump(),
            bound_usd=body.bound_usd,
            asked_by=session.actor,
            idempotency_key=body.idempotency_key,
            writing=sessions,
        )
    except DecisionAskRefused as refused:
        return _refusal(
            409 if refused.code != "bound_out_of_range" else 422, refused.code, refused.detail
        )
    except ModelNotAsked as refused:
        return _refusal(409, refused.code, "this model is not asked for this decision here")
    return JSONResponse(_view(found, row), status_code=201)


@router.get("/versions/{version_id}/society/decisions/{request_id}/asks")
def read_decision_asks(
    version_id: uuid.UUID,
    request_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    """The original answer of a recorded decision, and every ask beside it."""

    def read() -> Any:
        with connection.transaction():
            held = recorded(
                _repository(connection, session, request, world_id), version_id, request_id
            )
            return comparison(held, asks(connection, session.workspace_id, held))

    return _call(read, invalid_status=409)
