"""Authenticated saved playback controls. Importing these routes never starts a worker."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.api.society_control_worker import HOST_PLAYBACK_REFUSALS, host_playback_refusal
from exulanica.api.world_scope import WorldId
from exulanica.selection.validation import Session
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_control_repository import SocietyControlRepository
from exulanica.world.society_controls import DEFAULT_BASE_TICK_INTERVAL_MS, effective_interval_ms
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


class HostPlayback(BaseModel):
    """Whether this host advances this world on its own, and how often it would."""

    model_config = ConfigDict(extra="forbid")
    #: This host's playback worker is alive and plays this workspace. Independent of the saved
    #: mode: a paused society in a played workspace is one Play would advance.
    running: bool
    #: The effective wait between batches: the saved base divided by the speed while playing,
    #: and the host's base divided by the speed while paused, which is what Play adopts.
    interval_ms: int
    #: Null while running; otherwise the words a person reads for why this host does not.
    reason: str | None


class LastBatchExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_seq: int
    receipt_sha256: str
    executed_ticks: int
    execution_duration_ms: int
    completed_at: str


class ControlRead(BaseModel):
    """``exulanica.society-control/v1`` as the routes return it. Undeclared keys fail loudly."""

    model_config = ConfigDict(extra="forbid")
    profile: Literal["exulanica.society-control/v1"]
    society_id: str
    branch_id: str
    persisted: bool
    revision: int
    mode: Literal["playing", "paused"]
    speed: int
    base_tick_interval_ms: int
    tick_interval_ms: int
    interval_semantics: Literal["minimum_wait_after_batch_completion"]
    last_batch_execution: LastBatchExecution | None
    simulated_seconds_per_tick: int
    max_catchup_ticks: int
    next_due_at: str | None
    reason: str | None
    lease_expires_at: str | None
    last_event_seq: int
    current_tick: int
    state_sha256: str
    play_ineligible_reason: str | None
    play_eligible: bool
    host_playback: HostPlayback


def host_base_tick_interval_ms(request: Request) -> int:
    return getattr(
        request.app.state, "society_base_tick_interval_ms", DEFAULT_BASE_TICK_INTERVAL_MS
    )


def with_host_playback(control: dict, request: Request, workspace: uuid.UUID) -> dict:
    """The control read with whether this host plays it, from the process's own worker."""
    refusal = host_playback_refusal(
        getattr(request.app.state, "society_control_worker", None),
        getattr(request.app.state, "society_control_thread", None),
        workspace,
    )
    base = (
        control["base_tick_interval_ms"]
        if control["mode"] == "playing"
        else host_base_tick_interval_ms(request)
    )
    return {
        **control,
        "host_playback": {
            "running": refusal is None,
            "interval_ms": effective_interval_ms(base, control["speed"]),
            "reason": None if refusal is None else HOST_PLAYBACK_REFUSALS[refusal],
        },
    }


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
        base_tick_interval_ms=host_base_tick_interval_ms(request),
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


@router.get("", response_model=ControlRead)
def read_control(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    return call(
        lambda: with_host_playback(
            repository(connection, session, request, world_id).read(version_id),
            request,
            session.workspace_id,
        )
    )


@router.put("", response_model=ControlRead)
def configure_control(
    version_id: uuid.UUID,
    body: ConfigureBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    return call(
        lambda: with_host_playback(
            repository(connection, session, request, world_id).configure(
                version_id, actor=session.actor, **body.model_dump()
            ),
            request,
            session.workspace_id,
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
    def step() -> dict:
        result = repository(connection, session, request, world_id).manual_step(
            version_id, actor=session.actor, **body.model_dump()
        )
        return {
            **result,
            "control": with_host_playback(result["control"], request, session.workspace_id),
        }

    return call(step)


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
