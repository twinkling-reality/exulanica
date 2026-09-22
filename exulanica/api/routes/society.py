"""Authenticated lifecycle; authoritative v2 inputs come only from the configured server adapter."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.api.society_decision_runtime import request_decision
from exulanica.world.models import DEFAULT_WORLD_ID
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_repository import SocietyRepository

router = APIRouter(prefix="/world", tags=["society"])

#: Which saved world the authored version belongs to. A person's own world is not the default
#: one, and the repository refuses a version that does not belong to the world named here, so a
#: wrong or absent value reads as an unavailable version rather than reaching another world.
WorldId = Annotated[str, Query(min_length=1, max_length=200)]


class CreateSocietyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    place_id: uuid.UUID
    region_id: Annotated[str, Field(min_length=1, max_length=500)]
    seed: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    profile: Literal[
        "exulanica-society/v1",
        "exulanica-society/v2",
        "exulanica-society/v3",
        "exulanica-society/v4",
    ] = "exulanica-society/v1"


class AdvanceSocietyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_tick: Annotated[int, Field(ge=0)]
    base_state_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class DecisionBody(AdvanceSocietyBody):
    idempotency_key: uuid.UUID
    subject_id: uuid.UUID


def _repository(
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: str = DEFAULT_WORLD_ID,
) -> SocietyRepository:
    authorizer = getattr(request.app.state, "society_input_authorizer", None)
    return SocietyRepository(
        connection,
        session.workspace_id,
        world_id=world_id,
        input_authorizer=(
            None if authorizer is None else lambda doc: authorizer(connection, session, doc)
        ),
    )


def _call(operation: Callable[[], Any], *, invalid_status: int = 422) -> Any:
    try:
        return operation()
    except UnavailableSocietyInput as exc:
        return JSONResponse(
            status_code=424, content={"code": "unavailable_society_input", "detail": str(exc)}
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=invalid_status,
            content={"code": "invalid_society_state", "detail": str(exc)},
        )


@router.post("/versions/{version_id}/society")
def create_society(
    version_id: uuid.UUID,
    body: CreateSocietyBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId = DEFAULT_WORLD_ID,
) -> Any:
    def create() -> dict:
        repo = _repository(connection, session, request, world_id)
        document = None
        if body.profile in ("exulanica-society/v2", "exulanica-society/v3", "exulanica-society/v4"):
            provider = getattr(request.app.state, "society_initial_input", None)
            if provider is None:
                raise UnavailableSocietyInput("purposeful society input adapter is not configured")
            document = provider(connection, session, version_id, body.place_id, body.region_id)
        return repo.create(
            version_id,
            place_id=body.place_id,
            region_id=body.region_id,
            seed=body.seed,
            actor=session.actor,
            profile=body.profile,
            initial_input=document,
        )

    return _call(create)


@router.post("/versions/{version_id}/society/decisions")
def propose_decision(
    version_id: uuid.UUID,
    body: DecisionBody,
    session: CurrentSession,
    request: Request,
    world_id: WorldId = DEFAULT_WORLD_ID,
) -> Any:
    return _call(
        lambda: request_decision(
            request,
            session,
            version_id,
            world_id=world_id,
            request_id=body.idempotency_key,
            subject_id=body.subject_id,
            base_tick=body.base_tick,
            base_state_sha256=body.base_state_sha256,
        ),
        invalid_status=409,
    )


@router.get("/versions/{version_id}/society/decisions/{request_id}")
def read_decision(
    version_id: uuid.UUID,
    request_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId = DEFAULT_WORLD_ID,
) -> Any:
    with connection.transaction():
        return _call(
            lambda: SocietyDecisionRepository(
                _repository(connection, session, request, world_id)
            ).read(version_id, request_id),
            invalid_status=409,
        )


@router.get("/versions/{version_id}/society")
def society(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId = DEFAULT_WORLD_ID,
) -> Any:
    return _call(
        lambda: _repository(connection, session, request, world_id).snapshot(version_id),
        invalid_status=409,
    )


@router.post("/versions/{version_id}/society/steps")
def advance_society(
    version_id: uuid.UUID,
    body: AdvanceSocietyBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId = DEFAULT_WORLD_ID,
) -> Any:
    return _call(
        lambda: _repository(connection, session, request, world_id).advance(
            version_id, base_tick=body.base_tick, base_state_sha256=body.base_state_sha256
        ),
        invalid_status=409,
    )


@router.get("/versions/{version_id}/society/events")
def society_events(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId = DEFAULT_WORLD_ID,
    limit: Annotated[int, Query(ge=1, le=256)] = 256,
) -> Any:
    return _call(
        lambda: {
            "events": _repository(connection, session, request, world_id).events(
                version_id, limit=limit
            )
        },
        invalid_status=409,
    )


@router.get("/versions/{version_id}/society/replay")
def replay_society(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId = DEFAULT_WORLD_ID,
) -> Any:
    return _call(
        lambda: _repository(connection, session, request, world_id).replay(version_id),
        invalid_status=409,
    )
