"""Authenticated typed society action requests over canonical simulation targets."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.api.world_scope import WorldId
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_action_repository import SocietyActionRepository
from exulanica.world.society_actions import ActionIntent
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world/versions/{version_id}/society/actions", tags=["society"])


class GoToIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["go_to"]
    target_id: Annotated[str, Field(min_length=1, max_length=1000)]


class PerformIntent(GoToIntent):
    kind: Literal["perform"]
    affordance: Literal["visit", "rest"]


class SocietyActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: uuid.UUID
    base_tick: Annotated[StrictInt, Field(ge=0)]
    base_state_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    subject_id: uuid.UUID
    intent: GoToIntent | PerformIntent


def repository(
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: str,
) -> SocietyActionRepository:
    require_world(connection, session.workspace_id, world_id)
    authorizer = getattr(request.app.state, "society_input_authorizer", None)
    return SocietyActionRepository(
        connection,
        session.workspace_id,
        world_id=world_id,
        input_authorizer=(
            None if authorizer is None else lambda doc: authorizer(connection, session, doc)
        ),
    )


def call(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except UnavailableSocietyInput as exc:
        return JSONResponse(
            status_code=424, content={"code": "unavailable_society_input", "detail": str(exc)}
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=409, content={"code": "invalid_society_action", "detail": str(exc)}
        )


@router.post("")
def record_action(
    version_id: uuid.UUID,
    body: SocietyActionBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    intent = ActionIntent(**body.intent.model_dump())
    return call(
        lambda: repository(connection, session, request, world_id).create(
            version_id,
            request_id=body.idempotency_key,
            requested_by=session.actor,
            subject_id=body.subject_id,
            intent=intent,
            base_tick=body.base_tick,
            base_state_sha256=body.base_state_sha256,
        )
    )


@router.get("")
def action_events(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    limit: Annotated[int, Query(ge=1, le=128)] = 64,
) -> Any:
    return call(
        lambda: {
            "events": repository(connection, session, request, world_id).history(
                version_id, limit=limit
            )
        }
    )


@router.get("/{request_id}")
def read_action(
    version_id: uuid.UUID,
    request_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    return call(
        lambda: repository(connection, session, request, world_id).read(version_id, request_id)
    )
