"""Authenticated saved playback controls. Importing these routes never starts a worker."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Annotated, Any, Final, Literal

import psycopg
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.api.society_control_worker import HOST_PLAYBACK_REFUSALS, host_playback_refusal
from exulanica.api.world_scope import WorldId
from exulanica.selection.validation import Session
from exulanica.world.society import UnavailableSocietyInput, served_snapshot
from exulanica.world.society_control_repository import SocietyControlRepository
from exulanica.world.society_controls import DEFAULT_BASE_TICK_INTERVAL_MS, effective_interval_ms
from exulanica.world.world_clock import ClockRefused
from exulanica.world.worlds import require_world

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/world/versions/{version_id}/society/control", tags=["society"])


class ConfigureBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision: Annotated[StrictInt, Field(ge=0)]
    mode: Literal["playing", "paused"]
    speed: StrictInt
    #: The world clock's revision the request was made against (``GET .../clock``), when the
    #: caller pins it: another revision is refused, 409 ``stale_clock_revision``.
    base_clock_revision: Annotated[StrictInt, Field(ge=0)] | None = None


class StepBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision: Annotated[StrictInt, Field(ge=0)]
    base_tick: Annotated[StrictInt, Field(ge=0)]
    base_state_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    #: As :class:`ConfigureBody`'s.
    base_clock_revision: Annotated[StrictInt, Field(ge=0)] | None = None


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
    #: Why this host does not play the world, by code (the key of ``HOST_PLAYBACK_REFUSALS``), or
    #: null while it does. ``host_playback.reason`` keeps the sentence.
    host_playback_code: (
        Literal[
            "no_playback_worker",
            "playback_worker_stopped",
            "workspace_not_played",
            "guest_towns_full",
        ]
        | None
    )
    #: Why people here who would ask an open model decide by their routines instead, by code, or
    #: null while their models may be asked. The world keeps playing either way.
    model_minds_code: Literal["spending_cap_reached"] | None
    #: The sentence for ``model_minds_code``, or null.
    model_minds_reason: str | None


#: What a reader is told when the allowance for open models is spent: the world plays on.
MODEL_MINDS_REASONS: Final = {
    "spending_cap_reached": (
        "The allowance for open models on this visit is used up, so people here now follow "
        "their own routines. The world keeps playing."
    ),
}


def model_minds_code(
    request: Request,
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    society_id: str | None = None,
) -> str | None:
    """``spending_cap_reached`` when this workspace's allowance for open models is used up: the
    workspace's own grant, or the authority every guest shares. None while it remains, or where no
    durable authority admits (the process fuse is its own refusal, at call time).

    Said when either holds:

    *   the durable authority would refuse the next attempt of every provider the workspace
        holds an allowance for (each refusal ``spending_limit_reached``, or a remainder below the
        smallest reservation any of that provider's models takes, so that the host asks none of
        them; a provider never granted is not the workspace's allowance); or
    *   the society's latest receipt was refused ``spending_limit_reached``: admission refuses
        once the remainder is below one attempt's reservation, which the spending state cannot
        foresee, so a USD allowance usually ends this way, before its calls do.
    """
    services = getattr(request.app.state, "services", None)
    if services is None:
        return None
    try:
        # A savepoint, so a failed read leaves the request's transaction usable: the control read,
        # a PUT and an already committed step answer as before, without the cap's words.
        with connection.transaction():
            refusals = services.spending_refusals(connection, workspace)
            if refusals is None:
                return None
            latest = (
                None
                if society_id is None
                else connection.execute(
                    "select document->>'reason' as reason from world_society_decision "
                    "where workspace_id = %s and society_id = %s "
                    "order by decision_seq desc limit 1",
                    (workspace, uuid.UUID(society_id)),
                ).fetchone()
            )
    except Exception as exc:
        # Never the exception's text, which may carry a connection string.
        _LOG.warning("the spending state could not be read: %s", type(exc).__qualname__)
        return None
    smallest = getattr(services, "smallest_reservation_usd", None)
    floors = smallest() if smallest is not None else {}

    def spent(provider: str, refused: Any) -> bool:
        if refused is not None:
            return refused.reason == "spending_limit_reached"
        remainder = refusals.available_usd.get(provider)
        floor = floors.get(provider)
        return remainder is not None and floor is not None and remainder < floor

    granted_providers = [
        (provider, refused)
        for provider, refused in refusals.by_provider.items()
        if refused is None or refused.reason != "spending_not_granted"
    ]
    every_spent = bool(granted_providers) and all(
        spent(provider, refused) for provider, refused in granted_providers
    )
    refused_last = latest is not None and _row_value(latest, "reason") == "spending_limit_reached"
    return "spending_cap_reached" if every_spent or refused_last else None


def _row_value(row: Any, key: str) -> Any:
    """A column of a row read as a mapping or a tuple (the scoped connection's row factory)."""
    return row[key] if isinstance(row, dict) else row[0]


def host_base_tick_interval_ms(request: Request) -> int:
    return getattr(
        request.app.state, "society_base_tick_interval_ms", DEFAULT_BASE_TICK_INTERVAL_MS
    )


def with_host_playback(
    control: dict, request: Request, workspace: uuid.UUID, connection: psycopg.Connection
) -> dict:
    """The control read with whether this host plays it: from the process's own worker, or from
    the playback process this one leaves playback to; and whether its people's open models may
    still be asked (:func:`model_minds_code`)."""
    minds = model_minds_code(request, connection, workspace, control.get("society_id"))
    refusal = host_playback_refusal(
        getattr(request.app.state, "society_control_worker", None),
        getattr(request.app.state, "society_control_thread", None),
        workspace,
        getattr(request.app.state, "playback_process", None),
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
        # The stable code beside the sentence, for a client to branch on. Beside, not inside:
        # the browser's reader of host_playback refuses a key it does not know.
        "host_playback_code": refusal,
        "model_minds_code": minds,
        "model_minds_reason": None if minds is None else MODEL_MINDS_REASONS[minds],
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
    except ClockRefused as exc:
        # A coupled world's society waits for its traffic (clock_lead_exhausted): retry later.
        return JSONResponse(status_code=409, content={"code": exc.code, "detail": exc.detail})
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
            connection,
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
            connection,
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
            "control": with_host_playback(
                result["control"], request, session.workspace_id, connection
            ),
            # The society is served as the society routes serve it: never its seed.
            "society": served_snapshot(result["society"]),
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
