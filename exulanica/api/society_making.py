"""Making a version's society, the one way, and how its refusals are answered.

``POST /world/versions/{version_id}/society`` makes a version's society, or reads back the one it
holds, through :func:`make_society`; so does the scene dressing a server runs for a new world
(:mod:`exulanica.api.scene_dressing`), so both make a society with the same engine checks, the same
saved-world place, the same first input and the same seed. Every refusal a society operation raises
is answered by one table (:func:`society_refusal`): the society routes answer with it, and the scene
dressing names its society's refusal by its code.

What a society operation reads from the application it runs in is taken explicitly
(:class:`SocietyHooks`), so a caller without the application, such as an installation preparing
its arrival worlds, builds the hooks itself.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from fastapi.responses import JSONResponse

from exulanica.api.services import Services
from exulanica.world.kinds.worker import KindWorkWaiting
from exulanica.world.society import (
    SocietyLivesElsewhere,
    SocietyPlaceWaiting,
    UnavailableSocietyInput,
    served_snapshot,
)
from exulanica.world.society_engines import RetiredSocietyEngine, creatable_engine, society_engine
from exulanica.world.society_grounds import SocietyPopulationRefused
from exulanica.world.society_planner import SocietyStartRefused
from exulanica.world.society_repository import InvalidEventCursor, SocietyRepository
from exulanica.world.world_clock import ClockRefused
from exulanica.world.worlds import require_world

__all__ = [
    "SOCIETY_ENGINE_NOT_OFFERED",
    "SocietyEngineNotOffered",
    "SocietyHooks",
    "SocietyRefusal",
    "make_society",
    "society_refusal",
    "society_repository",
]

#: Why a society of things is not made here: the host does not offer it through its routes.
SOCIETY_ENGINE_NOT_OFFERED: Final = "society_engine_not_offered"


class SocietyEngineNotOffered(Exception):
    """A society of things asked of a host that does not offer it (``EXULANICA_SOCIETY_OF_THINGS``),
    refused by name before anything is read."""

    code = SOCIETY_ENGINE_NOT_OFFERED

    def __init__(self, profile: str) -> None:
        self.detail = f"this host makes no society with {profile} through its routes"
        super().__init__(self.detail)


@dataclass(frozen=True, slots=True)
class SocietyHooks:
    """What a society operation and an authored edit read from the application they run in: its
    services, the hook that tells a version's society of each authored edit, the check a society's
    inputs ask before they are read, and the adapter that composes a society's first input. Each
    hook may be absent, as on an application that configures none."""

    services: Services
    authored_edit: Callable[..., Any] | None
    input_authorizer: Callable[..., Any] | None
    initial_input: Callable[..., Any] | None

    @classmethod
    def of_app(cls, app: Any) -> SocietyHooks:
        """The hooks an application holds, as its routes read them."""
        state = app.state
        return cls(
            services=state.services,
            authored_edit=getattr(state, "society_authored_edit", None),
            input_authorizer=getattr(state, "society_input_authorizer", None),
            initial_input=getattr(state, "society_initial_input", None),
        )


@dataclass(frozen=True, slots=True)
class SocietyRefusal:
    """A society operation's refusal as its routes answer it: the status, the code, the detail and,
    for a place still being made, the seconds to wait before asking again."""

    status: int
    code: str
    detail: str
    retry_seconds: int | None = None

    def response(self) -> JSONResponse:
        retry = None if self.retry_seconds is None else {"Retry-After": str(self.retry_seconds)}
        return JSONResponse(
            status_code=self.status,
            content={"code": self.code, "detail": self.detail},
            headers=retry,
        )


def society_refusal(exc: Exception, *, invalid_status: int = 422) -> SocietyRefusal | None:
    """How a society operation's refusal is answered, in this order, or None for an exception that
    is not one: a place still being made (503, ask again later), a society of things this host
    does not offer, an input that cannot be read (424), the world giving its people nowhere to be,
    a retired engine, a society that lives elsewhere, a population the world's premises forbid, an
    event cursor that names no event, a clock that waits for its traffic, and any other invalid
    state (``invalid_status``)."""
    if isinstance(exc, KindWorkWaiting | SocietyPlaceWaiting):
        return SocietyRefusal(503, exc.code, str(exc), exc.retry_seconds)
    if isinstance(exc, SocietyEngineNotOffered):
        return SocietyRefusal(409, exc.code, exc.detail)
    if isinstance(exc, UnavailableSocietyInput):
        return SocietyRefusal(424, "unavailable_society_input", str(exc))
    if isinstance(exc, SocietyStartRefused):
        # The world as it is gives its people nowhere to be: named, so a caller acts on the code.
        return SocietyRefusal(409, exc.code, exc.detail)
    if isinstance(exc, RetiredSocietyEngine | SocietyLivesElsewhere):
        return SocietyRefusal(409, exc.code, str(exc))
    if isinstance(exc, SocietyPopulationRefused):
        # The world's own premises imply a population no society over its ground may start with.
        return SocietyRefusal(409, exc.code, exc.detail)
    if isinstance(exc, InvalidEventCursor):
        return SocietyRefusal(422, exc.code, str(exc))
    if isinstance(exc, ClockRefused):
        # A coupled world's society waits for its traffic (clock_lead_exhausted): retry later.
        return SocietyRefusal(409, exc.code, exc.detail)
    if isinstance(exc, ValueError):
        return SocietyRefusal(invalid_status, "invalid_society_state", str(exc))
    return None


def society_repository(
    connection: Any, session: Any, hooks: SocietyHooks, world_id: str
) -> SocietyRepository:
    """The named world's societies. A world the workspace does not hold is an unknown resource,
    and the repository refuses a version that does not belong to the world named here."""
    require_world(connection, session.workspace_id, world_id)
    authorizer = hooks.input_authorizer
    return SocietyRepository(
        connection,
        session.workspace_id,
        world_id=world_id,
        input_authorizer=(
            None if authorizer is None else lambda doc: authorizer(connection, session, doc)
        ),
    )


def make_society(
    hooks: SocietyHooks,
    connection: Any,
    session: Any,
    world_id: str,
    version_id: uuid.UUID,
    *,
    region_id: str,
    profile: str,
    place_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Make the version's society in ``region_id`` on the engine ``profile`` names and answer it as
    served, or answer the one the version already holds there.

    A society of things is made only where the host offers it (:class:`SocietyEngineNotOffered`
    otherwise, before anything is read). A saved world's place, its first input and its society are
    made in one transaction or not at all, so a refusal such as nothing reachable leaves nothing
    behind; every refusal is raised for the caller to answer (:func:`society_refusal`).
    """
    services = hooks.services
    if society_engine(profile).state_family == "things" and not services.societies_of_things:
        raise SocietyEngineNotOffered(profile)
    repo = society_repository(connection, session, hooks, world_id)
    runtime = services.society_runtime
    if (
        runtime is not None
        and place_id is None
        and creatable_engine(profile).takes_inputs
        and repo.held(version_id, profile=profile, region_id=region_id) is None
    ):
        # A site world's place is made in the kind worker and waited for here, before the
        # transaction and its locks; inside it the place is only read.
        runtime.prepare_saved_world(connection, session, version_id, region_id)
    with connection.transaction():
        creatable_engine(profile)
        # Asked again, the version's society is read back with nothing composed, and a
        # creation naming another region is refused by name.
        held = repo.held(version_id, profile=profile, region_id=region_id)
        if held is not None:
            return served_snapshot(held)
        document = None
        if society_engine(profile).takes_inputs:
            provider = hooks.initial_input
            if provider is None:
                raise UnavailableSocietyInput("purposeful society input adapter is not configured")
            if place_id is None:
                if runtime is None:
                    raise UnavailableSocietyInput("saved-world society is not configured")
                place_id = runtime.saved_world_place(connection, session, version_id, region_id)
            # The engine says how a world's own walking surfaces are composed for it.
            document = provider(connection, session, version_id, place_id, region_id, profile)
        elif place_id is None:
            raise ValueError("a society without inputs needs a place_id")
        return served_snapshot(
            repo.create(
                version_id,
                place_id=place_id,
                region_id=region_id,
                seed=services.society_seed(session.workspace_id, world_id),
                actor=session.actor,
                profile=profile,
                initial_input=document,
            )
        )
