"""Authenticated lifecycle; authoritative v2 inputs come only from the configured server adapter."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import CurrentSession, ScopedConnection, get_services
from exulanica.api.society_decision_runtime import request_decision
from exulanica.api.world_scope import WorldId
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_engines import DEFAULT_ENGINE, ENGINES, society_engine
from exulanica.world.society_planner import SocietyStartRefused
from exulanica.world.society_presence import PresenceRefused
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world", tags=["society"])
#: The profiles a society can be created with: the engine table's, in its order.
EngineProfile = Literal[tuple(engine.engine for engine in ENGINES)]  # type: ignore[valid-type]


class CreateSocietyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: Omitted when a person brings inhabitants into their own saved world: the server resolves
    #: that world's place itself, and a client never names one it did not read from the server.
    place_id: uuid.UUID | None = None
    region_id: Annotated[str, Field(min_length=1, max_length=500)]
    seed: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    #: Every engine the engine table states, and its default; nothing here restates the list.
    profile: EngineProfile = DEFAULT_ENGINE  # type: ignore[valid-type]


class AdvanceSocietyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_tick: Annotated[int, Field(ge=0)]
    base_state_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PresenceBody(AdvanceSocietyBody):
    """Send everyone away, or bring them back, against the state the person was shown."""

    idempotency_key: uuid.UUID
    presence: Literal["away", "here"]


class DecisionBody(AdvanceSocietyBody):
    idempotency_key: uuid.UUID
    subject_id: uuid.UUID


def _repository(
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: str,
) -> SocietyRepository:
    """The named world's societies. A world the workspace does not hold is an unknown resource,
    and the repository refuses a version that does not belong to the world named here."""
    require_world(connection, session.workspace_id, world_id)
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
    except SocietyStartRefused as exc:
        # The world as it is gives its people nowhere to be: named, so a caller acts on the code.
        return JSONResponse(status_code=409, content={"code": exc.code, "detail": exc.detail})
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
    world_id: WorldId,
) -> Any:
    def create() -> dict:
        repo = _repository(connection, session, request, world_id)
        # One transaction: a saved world's place, its first input and its society are made
        # together or not at all, so a refusal such as nothing reachable leaves nothing behind.
        with connection.transaction():
            document = None
            place_id = body.place_id
            if society_engine(body.profile).takes_inputs:
                provider = getattr(request.app.state, "society_initial_input", None)
                if provider is None:
                    raise UnavailableSocietyInput(
                        "purposeful society input adapter is not configured"
                    )
                if place_id is None:
                    runtime = get_services(request).society_runtime
                    if runtime is None:
                        raise UnavailableSocietyInput("saved-world society is not configured")
                    place_id = runtime.saved_world_place(connection, session, version_id)
                document = provider(connection, session, version_id, place_id, body.region_id)
            elif place_id is None:
                raise ValueError("a society without inputs needs a place_id")
            return repo.create(
                version_id,
                place_id=place_id,
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
    world_id: WorldId,
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
    world_id: WorldId,
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
    world_id: WorldId,
    places: Annotated[bool, Query()] = False,
) -> Any:
    """The current state. ``places`` adds where inhabitants can go, as its consumed input says."""
    return _call(
        lambda: _repository(connection, session, request, world_id).snapshot(
            version_id, places=places
        ),
        invalid_status=409,
    )


@router.post("/versions/{version_id}/society/steps")
def advance_society(
    version_id: uuid.UUID,
    body: AdvanceSocietyBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    return _call(
        lambda: _repository(connection, session, request, world_id).advance(
            version_id, base_tick=body.base_tick, base_state_sha256=body.base_state_sha256
        ),
        invalid_status=409,
    )


@router.post("/versions/{version_id}/society/presence")
def change_society_presence(
    version_id: uuid.UUID,
    body: PresenceBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    """One recorded minute in which everyone leaves, or the same people arrive again.

    The request names only what the person wants and the state they saw; the server resolves the
    world, the society, the rights and the minute. A refusal names what stands in the way.
    """

    def change() -> Any:
        try:
            return _repository(connection, session, request, world_id).change_presence(
                version_id,
                wanted=body.presence,
                request_id=body.idempotency_key,
                requested_by=session.actor,
                base_tick=body.base_tick,
                base_state_sha256=body.base_state_sha256,
            )
        except PresenceRefused as exc:
            return JSONResponse(
                status_code=409, content={"code": exc.code, "detail": exc.detail or exc.code}
            )

    return _call(change, invalid_status=409)


@router.get("/versions/{version_id}/society/events")
def society_events(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
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
    world_id: WorldId,
) -> Any:
    return _call(
        lambda: _repository(connection, session, request, world_id).replay(version_id),
        invalid_status=409,
    )
