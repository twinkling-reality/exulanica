"""Authenticated lifecycle for one deterministic society per authored version."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.world import SocietyRepository

router = APIRouter(prefix="/world", tags=["society"])


class CreateSocietyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_id: uuid.UUID
    region_id: Annotated[str, Field(min_length=1, max_length=500)]
    seed: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class AdvanceSocietyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_tick: Annotated[int, Field(ge=0)]
    base_state_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _repository(connection: ScopedConnection, session: CurrentSession) -> SocietyRepository:
    return SocietyRepository(connection, session.workspace_id)


@router.post("/versions/{version_id}/society")
def create_society(
    version_id: uuid.UUID,
    body: CreateSocietyBody,
    connection: ScopedConnection,
    session: CurrentSession,
) -> dict:
    return _repository(connection, session).create(
        version_id,
        place_id=body.place_id,
        region_id=body.region_id,
        seed=body.seed,
        actor=session.actor,
    )


@router.get("/versions/{version_id}/society")
def society(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
) -> dict:
    return _repository(connection, session).snapshot(version_id)


@router.post("/versions/{version_id}/society/steps")
def advance_society(
    version_id: uuid.UUID,
    body: AdvanceSocietyBody,
    connection: ScopedConnection,
    session: CurrentSession,
) -> dict:
    return _repository(connection, session).advance(
        version_id,
        base_tick=body.base_tick,
        base_state_sha256=body.base_state_sha256,
    )


@router.get("/versions/{version_id}/society/events")
def society_events(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    limit: Annotated[int, Query(ge=1, le=256)] = 256,
) -> dict:
    return {"events": _repository(connection, session).events(version_id, limit=limit)}


@router.get("/versions/{version_id}/society/replay")
def replay_society(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
) -> dict:
    return _repository(connection, session).replay(version_id)
