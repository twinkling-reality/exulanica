"""Authenticated saved playback controls. Importing these routes never starts a worker."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.api.world_scope import WorldId
from exulanica.selection.validation import Session
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_control_repository import SocietyControlRepository
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world/versions/{version_id}/society/control", tags=["society"])


class ConfigureBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision: Annotated[StrictInt, Field(ge=0)]
    mode: Literal["playing", "paused"]
    speed: StrictInt


class StepBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision: Annotated[StrictInt, Field(ge=0)]
    base_tick: Annotated[StrictInt, Field(ge=0)]
    base_state_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def repository(
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: str,
) -> SocietyControlRepository:
    require_world(connection, session.workspace_id, world_id)
    authorizer = getattr(request.app.state, "society_input_authorizer", None)
    return SocietyControlRepository(
        connection,
        session.workspace_id,
        world_id=world_id,
        base_tick_interval_ms=getattr(request.app.state, "society_base_tick_interval_ms", 1000),
        input_authorizer=None
        if authorizer is None
        else lambda actor, doc: authorizer(
            connection, Session(workspace_id=session.workspace_id, actor=actor), doc
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
            status_code=409, content={"code": "invalid_society_control", "detail": str(exc)}
        )


@router.get("")
def read_control(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    return call(lambda: repository(connection, session, request, world_id).read(version_id))


@router.put("")
def configure_control(
    version_id: uuid.UUID,
    body: ConfigureBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    return call(
        lambda: repository(connection, session, request, world_id).configure(
            version_id, actor=session.actor, **body.model_dump()
        )
    )


@router.post("/steps")
def manual_step(
    version_id: uuid.UUID,
    body: StepBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    return call(
        lambda: repository(connection, session, request, world_id).manual_step(
            version_id, actor=session.actor, **body.model_dump()
        )
    )


@router.get("/events")
def control_events(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    limit: Annotated[int, Query(ge=1, le=128)] = 64,
) -> Any:
    return call(
        lambda: {
            "events": repository(connection, session, request, world_id).events(
                version_id, limit=limit
            )
        }
    )
