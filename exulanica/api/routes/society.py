"""Authenticated lifecycle; authoritative v2 inputs come only from the configured server adapter.

Every society these routes return is served by :func:`~exulanica.world.society.served_snapshot`
and every event by :func:`~exulanica.world.society.served_events`: a response carries the seed's
digest (``seed_digest``), never the seed. That is presentation, not secrecy: the seed is derived
from the workspace and world a caller already names (``world_society_seed``), so a client that
knows them can compute it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.api.society_making import (
    SocietyHooks,
    make_society,
    society_refusal,
    society_repository,
)
from exulanica.api.world_scope import WorldId
from exulanica.world.society import (
    served_events,
    served_snapshot,
)
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_engines import (
    DEFAULT_ENGINE,
    ENGINES,
)
from exulanica.world.society_erasure import SocietyErasureRefused, erase_society
from exulanica.world.society_presence import PresenceRefused
from exulanica.world.society_repository import (
    EVENTS_READ_MAXIMUM,
    SocietyRepository,
)
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world", tags=["society"])
#: The profiles a creation may name: the engine table's, in its order. A retired one is refused
#: by name when it is asked for, rather than read as a malformed request.
EngineProfile = Literal[tuple(engine.engine for engine in ENGINES)]  # type: ignore[valid-type]
#: Why a request for a model's proposal is refused: the one engine that took such requests is
#: retired, and a model decides for a person only as the world's owner chose.
PROPOSALS_RETIRED: Final = "society_proposals_retired"
#: What one input's provenance read answers: its identity and the authored state it followed.
INPUT_PROVENANCE_PROFILE: Final = "exulanica.society-input-provenance/v1"


class CreateSocietyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: Omitted when a person brings inhabitants into their own saved world: the server resolves
    #: that world's place itself, and a client never names one it did not read from the server.
    place_id: uuid.UUID | None = None
    region_id: Annotated[str, Field(min_length=1, max_length=500)]
    #: Every engine the engine table states, and its default; nothing here restates the list. No
    #: seed: the server derives the world's own (``Services.society_seed``).
    profile: EngineProfile = DEFAULT_ENGINE  # type: ignore[valid-type]


class AdvanceSocietyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_tick: Annotated[int, Field(ge=0)]
    base_state_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class StepSocietyBody(AdvanceSocietyBody):
    """A minute, against the state the person was shown and, when pinned, the world clock's
    revision (``GET .../clock``): another revision is refused, 409 ``stale_clock_revision``."""

    base_clock_revision: Annotated[int, Field(ge=0)] | None = None


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
    """The named world's societies (:func:`~exulanica.api.society_making.society_repository`)."""
    return society_repository(connection, session, SocietyHooks.of_app(request.app), world_id)


def _call(operation: Callable[[], Any], *, invalid_status: int = 422) -> Any:
    """``operation``'s answer, or its refusal answered by the society table
    (:func:`~exulanica.api.society_making.society_refusal`)."""
    try:
        return operation()
    except Exception as exc:
        refusal = society_refusal(exc, invalid_status=invalid_status)
        if refusal is None:
            raise
        return refusal.response()


@router.post("/versions/{version_id}/society")
def create_society(
    version_id: uuid.UUID,
    body: CreateSocietyBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    # A society of things is made through the routes only where the host offers it
    # (EXULANICA_SOCIETY_OF_THINGS); elsewhere it is refused by name before anything is read.
    # Made as a server's scene dressing makes one (exulanica.api.society_making).
    return _call(
        lambda: make_society(
            SocietyHooks.of_app(request.app),
            connection,
            session,
            world_id,
            version_id,
            region_id=body.region_id,
            profile=body.profile,
            place_id=body.place_id,
        )
    )


@router.post("/versions/{version_id}/society/decisions")
def propose_decision(
    version_id: uuid.UUID,
    body: DecisionBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    """Refused by name for every society: explicitly requested model proposals are retired.

    They were the retired ``exulanica-society/v3`` engine's, and no host was ever configured to
    answer them. A model decides for a person only as the world's owner chose, at the planner's
    own choice point. The world and its society are resolved first, so a stranger learns nothing
    from the refusal that an unknown version would not tell them; a stored request still reads.
    """

    def refuse() -> JSONResponse:
        _repository(connection, session, request, world_id).snapshot(version_id)
        return JSONResponse(
            status_code=409,
            content={
                "code": PROPOSALS_RETIRED,
                "detail": "a model decides for a person only as the world's owner chose",
            },
        )

    with connection.transaction():
        return _call(refuse, invalid_status=409)


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
        lambda: served_snapshot(
            _repository(connection, session, request, world_id).snapshot(version_id, places=places)
        ),
        invalid_status=409,
    )


@router.delete("/versions/{version_id}/society", status_code=204)
def erase_society_records(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> Response:
    """Erase this world version's society whole, under a society tombstone: every row that records
    it (what its people said among them), its clock, its asks to outside programs and its
    crossings, and the comparisons and experiments started from it; the Companion's answers that
    cited the version are withdrawn. Refused ``society_unavailable`` (404) where the version holds
    no society, and ``restore_sealed`` (409) while the installation is sealed for a restore."""
    require_world(connection, session.workspace_id, world_id)
    try:
        erase_society(
            connection, session.workspace_id, world_id, version_id, erased_by=session.actor
        )
    except SocietyErasureRefused as exc:
        return JSONResponse(
            status_code=404 if exc.code == "society_unavailable" else 409,
            content={"code": exc.code, "detail": exc.detail},
        )
    return Response(status_code=204)


@router.post("/versions/{version_id}/society/steps")
def advance_society(
    version_id: uuid.UUID,
    body: StepSocietyBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    return _call(
        lambda: served_snapshot(
            _repository(connection, session, request, world_id).advance(
                version_id,
                base_tick=body.base_tick,
                base_state_sha256=body.base_state_sha256,
                base_clock_revision=body.base_clock_revision,
                actor=session.actor,
            )
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
            return served_snapshot(
                _repository(connection, session, request, world_id).change_presence(
                    version_id,
                    wanted=body.presence,
                    request_id=body.idempotency_key,
                    requested_by=session.actor,
                    base_tick=body.base_tick,
                    base_state_sha256=body.base_state_sha256,
                )
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
    limit: Annotated[int, Query(ge=1, le=EVENTS_READ_MAXIMUM)] = EVENTS_READ_MAXIMUM,
    before: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
) -> Any:
    def page() -> dict[str, Any]:
        events, following = _repository(connection, session, request, world_id).events_page(
            version_id, limit=limit, before=before
        )
        return {"events": served_events(events), "next": following}

    return _call(page, invalid_status=409)


@router.get("/versions/{version_id}/society/inputs/{input_seq}")
def society_input_provenance(
    version_id: uuid.UUID,
    input_seq: Annotated[int, Path(ge=1, le=2**31 - 1)],
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    """One stored input of the version's society: its identity and the authored state it was
    composed after, the version's ``edit_seq`` and state digest as the input records them, never
    the input itself. An event names its input by ``input_seq``, so this read joins an event to the
    edit in the version's history that it followed. Its rights are asked as the events read asks
    them."""
    return _call(
        lambda: {
            "profile": INPUT_PROVENANCE_PROFILE,
            **_repository(connection, session, request, world_id).input_provenance(
                version_id, input_seq
            ),
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
        lambda: served_snapshot(
            _repository(connection, session, request, world_id).replay(version_id)
        ),
        invalid_status=409,
    )
