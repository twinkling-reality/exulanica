"""A world version's clock: read it, couple it, read its receipts and verify what it sealed.

The clock (:mod:`exulanica.world.world_clock`) says which timeline each of a version's systems
runs on. A version keeps legacy timing until a person couples it, once: its society's tick becomes
the one authority, traffic seals each minute after the society has committed the next, and flight
moves on the same timeline. Pausing, playing, the speed and stepping stay the society's playback
controls (``/world/versions/{version_id}/society/control``); in a coupled world with roads a step
may answer 409 ``clock_lead_exhausted`` while traffic catches up.

- ``GET`` (``world.read``): ``exulanica.world-clock/v1``, what a client is shown. A legacy version
  answers revision 0 and each system's own timebase.
- ``PUT`` (``world.write``): ``{base_revision, profile: "coupled"}``, the one-way transition, with
  the society paused. Refused by name: 409 ``stale_clock_revision``, ``clock_already_coupled``,
  ``clock_requires_society``, ``clock_society_not_playable``, ``clock_tick_seconds_unsupported``,
  ``clock_transition_requires_pause``, ``clock_crossings_unsupported`` (the world states roads and
  its society records no crossing its people make), ``clock_crossings_unmapped``, or the roads' own
  refusal (``roads_unavailable``, ``roads_world_too_large``, ``generated_world_*``); 422
  ``clock_transition_unsupported`` for another profile; 503 ``traffic_worker_unavailable``.
- ``GET /events`` (``world.read``): the clock's receipts, newest first.
- ``GET /verify`` (``world.read``): replays a coupled version's minutes ``from_tick`` to
  ``to_tick`` from what was stored and checks every occupancy and sealed digest. The society is
  replayed from its genesis, the only earlier state stored, and only while its whole history is
  within the profile's ``verify_society_ticks_maximum``; traffic minutes are rebuilt from each
  episode's genesis, at most ``verify_traffic_minutes_maximum`` a call. Nothing it runs holds a
  model client.

A world the workspace does not hold, or a version the world does not hold, is 404
``unknown_reference``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.api.capabilities import (
    AVAILABLE,
    Base,
    Operation,
    VersionContext,
    unavailable,
    unsupported,
)
from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.api.world_scope import WorldId
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.generated_worlds import unreadable_reason
from exulanica.world.society_controls import utc
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.traffic_episodes import TrafficInput, TrafficRefused
from exulanica.world.traffic_host import saved_world_roads
from exulanica.world.traffic_signal_repository import SignalChoiceRefused
from exulanica.world.world_clock import (
    COUPLED,
    ClockRefused,
    clock_profile,
    crossing_edges,
    minute_occupancy,
)
from exulanica.world.world_clock_repository import RoadsFacts, WorldClockRepository
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world/versions/{version_id}/clock", tags=["world"])

#: The verification receipt's profile.
VERIFICATION_PROFILE = "exulanica.world-clock-verification/v1"
#: Refusals a caller corrects in its request.
_REQUEST_REFUSALS = frozenset(
    {"invalid_clock_request", "clock_profile_unknown", "clock_transition_unsupported"}
)


class TransitionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision: Annotated[StrictInt, Field(ge=0)]
    profile: Literal["coupled"]


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


def _refusal_code(
    error: ClockRefused
    | SignalChoiceRefused
    | TrafficRefused
    | UnsupportedNetworkError
    | InvalidStructuralData,
) -> str:
    """The code a clock route answers a refusal with."""
    if isinstance(error, UnsupportedNetworkError):
        return "roads_unavailable"
    if isinstance(error, InvalidStructuralData):
        return unreadable_reason(error)
    return error.code


def _call(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except ClockRefused as error:
        if error.code == "unknown_reference":
            return _problem(404, error.code, error.detail)
        if error.code == "traffic_worker_unavailable":
            return _problem(503, error.code, error.detail)
        return _problem(422 if error.code in _REQUEST_REFUSALS else 409, error.code, error.detail)
    except SignalChoiceRefused as error:
        return _problem(503, error.code, "The traffic worker is unavailable.")
    except TrafficRefused as error:
        return _problem(
            503 if error.code == "traffic_worker_unavailable" else 409, error.code, error.detail
        )
    except UnsupportedNetworkError as error:
        return _problem(409, "roads_unavailable", str(error))
    except InvalidStructuralData as error:
        return _problem(409, unreadable_reason(error), str(error))


def _clocks(
    connection: ScopedConnection, session: CurrentSession, world_id: str
) -> WorldClockRepository:
    require_world(connection, session.workspace_id, world_id)
    return WorldClockRepository(connection, session.workspace_id, world_id)


def _snapshot(clocks: WorldClockRepository, version_id: uuid.UUID) -> uuid.UUID:
    row = clocks.connection.execute(
        "select source_snapshot_id from world_alternate_version where workspace_id=%s "
        "and world_id=%s and version_id=%s",
        (clocks.workspace_id, clocks.world_id, version_id),
    ).fetchone()
    if row is None:
        raise ClockRefused("unknown_reference", "the world holds no such version")
    return row["source_snapshot_id"]


def _roads(
    clocks: WorldClockRepository,
    request: Request,
    snapshot: uuid.UUID,
    *,
    stated: Callable[[], TrafficInput] | None = None,
) -> RoadsFacts | None:
    """The version's roads as a transition binds them, compiled in the traffic worker, or None
    when its records state no roads. Refused by the reader's or the compiler's own code.
    ``stated`` reads the roads where a caller already holds them: a capability read reads them
    once for every adapter."""
    try:
        if stated is not None:
            value = stated()
        else:
            value = saved_world_roads(
                clocks.connection, clocks.workspace_id, clocks.world_id, snapshot
            )
    except TrafficRefused as error:
        if error.code != "roads_not_stated":
            raise
        return None
    controller = getattr(request.app.state, "traffic_signal_controller", None)
    if controller is None:
        raise ClockRefused("traffic_worker_unavailable", "no traffic worker runs here")
    return RoadsFacts(value.version_id, value.sha256, controller.bands(value))


@router.get(
    "", summary="Which timeline each of a world version's systems runs on, and where it is."
)
def read_clock(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> Any:
    return _call(lambda: _clocks(connection, session, world_id).read(version_id))


@router.put(
    "", summary="Couple a world version's clock: one timeline for its people, traffic and birds."
)
def transition_clock(
    version_id: uuid.UUID,
    body: TransitionBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    def transition() -> dict[str, Any]:
        clocks = _clocks(connection, session, world_id)
        # The roads are compiled in the pure worker before the transition's transaction takes any
        # lock.
        roads = _roads(clocks, request, _snapshot(clocks, version_id))
        return clocks.transition(
            version_id,
            actor=session.actor,
            base_revision=body.base_revision,
            profile=body.profile,
            roads=roads,
        )

    return _call(transition)


@router.get("/events", summary="A world version's clock receipts, newest first.")
def clock_events(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
    limit: Annotated[int, Query(ge=1, le=128)] = 64,
) -> Any:
    def events() -> dict[str, Any]:
        clocks = _clocks(connection, session, world_id)
        _snapshot(clocks, version_id)
        return {"events": clocks.events(version_id, limit=limit)}

    return _call(events)


@router.get(
    "/verify", summary="Replay a coupled world's minutes from what was stored and check them."
)
def verify_clock(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    from_tick: Annotated[int, Query(ge=1)],
    to_tick: Annotated[int, Query(ge=1)],
) -> Any:
    def verify() -> dict[str, Any]:
        clocks = _clocks(connection, session, world_id)
        snapshot = _snapshot(clocks, version_id)
        clock = clocks.row(version_id)
        if clock is None:
            raise ClockRefused("clock_not_coupled", "a legacy clock seals nothing to verify")
        profile = clock_profile(COUPLED)
        if not clock["era_start_tick"] < from_tick <= to_tick <= clock["society_tick"]:
            raise ClockRefused(
                "invalid_clock_request",
                f"verify committed minutes {clock['era_start_tick'] + 1} "
                f"to {clock['society_tick']}",
            )
        if to_tick - from_tick + 1 > profile.verify_traffic_minutes_maximum:
            raise ClockRefused(
                "invalid_clock_request",
                f"verify at most {profile.verify_traffic_minutes_maximum} minutes a call",
            )
        started = clocks._now()
        society: dict[str, Any] = {"replayed": False}
        if clock["society_tick"] > profile.verify_society_ticks_maximum:
            society["reason"] = "clock_verify_society_beyond_cap"
            society["ticks_maximum"] = profile.verify_society_ticks_maximum
        else:
            stored = {
                row["tick"]: row["document_sha256"]
                for row in connection.execute(
                    "select tick,document_sha256 from world_crossing_occupancy "
                    "where workspace_id=%s and world_id=%s and society_id=%s and era=%s "
                    "and tick between %s and %s",
                    (
                        session.workspace_id,
                        world_id,
                        clock["society_id"],
                        clock["era"],
                        from_tick,
                        to_tick,
                    ),
                ).fetchall()
            }
            rebuilt: dict[int, str] = {}

            def observe(before: dict, after: dict, events: list[dict], places: list[dict]) -> None:
                if from_tick <= after["tick"] <= to_tick:
                    rebuilt[after["tick"]] = minute_occupancy(
                        society_id=str(clock["society_id"]),
                        era=clock["era"],
                        before=before,
                        after=after,
                        events=events,
                        crossings_by_edge=crossing_edges(places),
                        place_sha256=places[-1]["document_sha256"],
                    )["document_sha256"]

            authorizer = getattr(request.app.state, "society_input_authorizer", None)
            if clock["roads_version"] is not None:
                replayed = SocietyRepository(
                    connection,
                    session.workspace_id,
                    world_id=world_id,
                    input_authorizer=(
                        None
                        if authorizer is None
                        else lambda doc: authorizer(connection, session, doc)
                    ),
                ).replay_living_minutes(version_id, observe)
                if rebuilt != stored:
                    raise ClockRefused(
                        "crossing_occupancy_mismatch",
                        "the replayed minutes do not make the occupancy that was stored",
                    )
                society = {
                    "replayed": True,
                    "ticks_replayed": replayed["tick"],
                    "state_sha256": replayed["state_sha256"],
                    "occupancy_checked": len(stored),
                }
            else:
                society["reason"] = "clock_verify_no_crossings"
        traffic: dict[str, Any] = {"verified": False}
        if clock["roads_version"] is not None:
            sealed_last = min(to_tick, clock["traffic_sealed_through_tick"])
            if from_tick <= sealed_last:
                controller = getattr(request.app.state, "traffic_signal_controller", None)
                if controller is None:
                    raise ClockRefused("traffic_worker_unavailable", "no traffic worker runs here")
                value = saved_world_roads(connection, session.workspace_id, world_id, snapshot)
                traffic = {
                    "verified": True,
                    **controller.verify_coupled_minutes(
                        session.workspace_id, world_id, version_id, value, from_tick, sealed_last
                    ),
                }
            else:
                traffic["reason"] = "traffic_not_yet_sealed"
        return {
            "profile": VERIFICATION_PROFILE,
            "world_id": world_id,
            "version_id": str(version_id),
            "era": clock["era"],
            "from_tick": from_tick,
            "to_tick": to_tick,
            "society": society,
            "traffic": traffic,
            "model_client": None,
            "started_at": utc(started),
            "finished_at": utc(clocks._now()),
        }

    return _call(verify)


# -- a world's capability read --------------------------------------------------------------------

#: Transition refusals no later state of the version lifts.
_NEVER: Final = frozenset(
    {"clock_society_not_playable", "clock_tick_seconds_unsupported", "clock_crossings_unsupported"}
)


def capability_operations(context: VersionContext) -> list[Operation]:
    """Coupling the version's clock, as a world's capability read lists it.

    Its state is the transition's own predicate (:meth:`WorldClockRepository.transition_refusal`):
    first without the roads, and only when that passes, with the roads compiled as the transition
    compiles them, refused by the codes the transition answers.
    """
    clocks = WorldClockRepository(
        context.connection, context.session.workspace_id, context.world_id
    )
    try:
        refusal = clocks.transition_refusal(context.version_id, roads=None)
        if refusal is None:
            roads = _roads(
                clocks, context.request, context.source.snapshot_id, stated=context.roads
            )
            if roads is not None:
                refusal = clocks.transition_refusal(context.version_id, roads=roads)
        code = None if refusal is None else refusal.code
    except (
        ClockRefused,
        SignalChoiceRefused,
        TrafficRefused,
        UnsupportedNetworkError,
        InvalidStructuralData,
    ) as error:
        code = _refusal_code(error)
    if code is None:
        state = AVAILABLE
    elif code in _NEVER:
        state = unsupported(code)
    else:
        state = unavailable(code)
    return [
        Operation(
            endpoint=transition_clock,
            availability=state,
            subject="version",
            bind=context.bind,
            base=(Base("base_revision", read_clock, "revision"),),
        )
    ]
