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
from exulanica.api.society_opening import open_awake
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.kinds.worker import KindWorkWaiting
from exulanica.world.object_repository import WorldObjectRepository, version_holds_things
from exulanica.world.society import (
    SocietyLivesElsewhere,
    SocietyPlaceWaiting,
    UnavailableSocietyInput,
    served_snapshot,
)
from exulanica.world.society_engines import RetiredSocietyEngine, creatable_engine, society_engine
from exulanica.world.society_erasure import SocietyErasureRefused, erase_society
from exulanica.world.society_grounds import (
    SocietyPopulationRefused,
    UnknownSocietyGround,
    created_engine,
    society_ground_for_composer,
)
from exulanica.world.society_planner import SocietyStartRefused
from exulanica.world.society_repository import InvalidEventCursor, SocietyRepository
from exulanica.world.workspace_lock import lock_workspace
from exulanica.world.world_clock import ClockRefused
from exulanica.world.worlds import require_world

__all__ = [
    "SOCIETY_ENGINE_DIFFERS",
    "SOCIETY_ENGINE_NOT_OFFERED",
    "TAKE_IN_REFUSALS",
    "SocietyEngineDiffers",
    "SocietyEngineNotOffered",
    "SocietyHooks",
    "SocietyRefusal",
    "SocietyTakeInRefused",
    "engine_holding_things",
    "make_society",
    "society_refusal",
    "society_repository",
    "take_newcomers_in",
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


#: Why a society is not made with the engine asked for: on this host the engine table gives the
#: world a society of things, since its version holds a thing its author placed.
SOCIETY_ENGINE_DIFFERS: Final = "society_engine_differs"


#: Why a town's people do not take the newcomers in, by code.
TAKE_IN_REFUSALS: Final = {
    "society_unavailable": "this world version holds no society",
    "society_takes_in_already": (
        "this version's society is not a living town's: only a living town's people take in what "
        "was placed after they came"
    ),
    "nothing_to_take_in": (
        "nothing placed in this world asks for another society here: the host offers no society "
        "of things, or the version holds no thing its ground gives one"
    ),
    "restore_sealed": ("the installation is sealed for a restore; ask again once it is replayed"),
}


class SocietyTakeInRefused(Exception):
    """A take-in refused by a code a caller can act on, with nothing erased or made. Not a
    ``ValueError``, so no table of a creation's refusals answers it as an invalid state."""

    def __init__(self, code: str) -> None:
        super().__init__(TAKE_IN_REFUSALS[code])
        self.code = code
        self.detail = TAKE_IN_REFUSALS[code]


class SocietyEngineDiffers(Exception):
    """A new society of another engine asked for a saved world the engine table gives a society of
    things (its version holds a thing its author placed, on a ground the table names, and the host
    offers societies of things), refused by name before anything is composed: made with the other
    engine, the beings placed there would never live. The detail names the engine to ask for."""

    code = SOCIETY_ENGINE_DIFFERS

    def __init__(self, profile: str, engine: str) -> None:
        self.engine = engine
        self.detail = (
            f"this world holds things its author placed, so its society is made with {engine}, "
            f"not {profile}"
        )
        super().__init__(self.detail)


def engine_holding_things(
    connection: Any,
    session: Any,
    services: Services,
    world_id: str,
    version_id: uuid.UUID,
) -> str | None:
    """The engine of things the engine table gives this version's new society on this host, or
    None: where the host offers societies of things, the version holds a thing its author placed and
    its ground is one the table names for it. A district's version, a ground the table does not
    name, and a version holding no placed thing answer None, as an unknown version does here (its
    own refusal comes from the creation)."""
    if not services.societies_of_things:
        return None
    try:
        source = WorldObjectRepository(
            connection, session.workspace_id, world_id=world_id, store=services.store
        ).source_facts(version_id)
        ground = society_ground_for_composer(source.composer_key)
    except (UnknownSocietyGround, UnknownWorldResource):
        return None
    engine = created_engine(ground, holding_things=True)
    if society_engine(engine).state_family != "things":
        return None
    held = version_holds_things(connection, session.workspace_id, world_id, version_id)
    return engine if held else None


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
    if isinstance(exc, SocietyEngineNotOffered | SocietyEngineDiffers):
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
    prepared: bool = False,
) -> dict[str, Any]:
    """Make the version's society in ``region_id`` on the engine ``profile`` names and answer it as
    served, or answer the one the version already holds there. ``prepared`` says the caller made
    the saved world ready before a transaction of its own (``prepare_saved_world``), which this
    then runs inside.

    A society of things is made only where the host offers it (:class:`SocietyEngineNotOffered`
    otherwise, before anything is read), and there a new society of another engine over a world the
    engine table gives a society of things, since its version holds a thing its author placed, is
    refused before anything is composed (:class:`SocietyEngineDiffers`). A saved world's place,
    its first input and its society are made in one transaction or not at all, so a refusal such
    as nothing reachable leaves nothing behind; every refusal is raised for the caller to answer
    (:func:`society_refusal`).

    A society this call makes is then opened awake, as the host's opening says
    (:func:`exulanica.api.society_opening.open_awake`): advanced by ordinary recorded minutes until
    a share of its people is outdoors. One read back is answered as it stands.
    """
    services = hooks.services
    if society_engine(profile).state_family == "things" and not services.societies_of_things:
        raise SocietyEngineNotOffered(profile)
    repo = society_repository(connection, session, hooks, world_id)
    if society_engine(profile).state_family != "things":
        # A new society that would leave the beings placed in the world without life is refused;
        # the one a version already holds is read back as it always is.
        engine = engine_holding_things(connection, session, services, world_id, version_id)
        if engine is not None and repo.held(version_id, profile=profile, region_id=None) is None:
            raise SocietyEngineDiffers(profile, engine)
    runtime = services.society_runtime
    if (
        runtime is not None
        and not prepared
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
        created = repo.create(
            version_id,
            place_id=place_id,
            region_id=region_id,
            seed=services.society_seed(session.workspace_id, world_id),
            actor=session.actor,
            profile=profile,
            initial_input=document,
        )
    # Made and committed: now opened awake, as this host's opening says (a town's people are on
    # its streets when it is first shown). A minute refused there never undoes the creation.
    return served_snapshot(
        open_awake(repo, version_id, created, services.society_opening, actor=session.actor)
    )


def take_newcomers_in(
    hooks: SocietyHooks,
    connection: Any,
    session: Any,
    world_id: str,
    version_id: uuid.UUID,
) -> dict[str, Any]:
    """A living town's people take in what was placed in their world after they came: the
    version's living society is ended and a society of things made on the same version, in one
    transaction, and answered as served.

    The living society is erased by the erasure a person's own erasing uses
    (:func:`~exulanica.world.society_erasure.erase_society`: a society tombstone, and every row
    that records the society removed with it), and the society of things is made as a creation
    makes one (:func:`make_society`), on the engine the engine table gives this version. A
    society's identity and seed derive from its world and version alone, and a society of things
    over a town is the town's own people, so they are the same people: their identities, homes,
    jobs, roles and shifts. Their day so far is not kept. Where the making refuses, the erasure is
    undone with it, so a version is never left with nobody.

    Refused by name with nothing erased or made (:class:`SocietyTakeInRefused`): a version that
    holds no society, one whose society is not a living one, one the engine table gives no
    society of things (the host offers none, or nothing its ground admits is placed there), and
    an installation sealed for a restore, which the erasure itself refuses."""
    services = hooks.services
    require_world(connection, session.workspace_id, world_id)
    runtime = services.society_runtime
    if runtime is not None:
        # What a creation readies before its transaction, readied before this one: a making
        # inside it holds the transaction's locks and waits for nothing.
        runtime.prepare_saved_world(connection, session, version_id, None)
    with connection.transaction():
        # The lock an erasure, a playback round and an edit take before they touch a society.
        lock_workspace(connection, session.workspace_id)
        held = connection.execute(
            "select engine_version, region_id from world_society "
            "where workspace_id = %s and world_id = %s and version_id = %s",
            (session.workspace_id, world_id, version_id),
        ).fetchone()
        if held is None:
            raise SocietyTakeInRefused("society_unavailable")
        if society_engine(held["engine_version"]).state_family != "living":
            raise SocietyTakeInRefused("society_takes_in_already")
        engine = engine_holding_things(connection, session, services, world_id, version_id)
        if engine is None:
            raise SocietyTakeInRefused("nothing_to_take_in")
        # The making's place first, as a creation makes it: what its first input reads is read
        # ahead and the asset read lock taken in the creation's order, before the erasure's
        # tombstone takes that lock's shared side. So the lock is never asked for after the
        # tombstone, and a town is never generated again while it is held.
        place_id = (
            None
            if runtime is None
            else runtime.saved_world_place(connection, session, version_id, held["region_id"])
        )
        try:
            erase_society(
                connection, session.workspace_id, world_id, version_id, erased_by=session.actor
            )
        except SocietyErasureRefused as exc:
            # Named here: the erasure's refusal is a ValueError, which a creation's table of
            # refusals would answer as an invalid state.
            raise SocietyTakeInRefused(exc.code) from exc
        return make_society(
            hooks,
            connection,
            session,
            world_id,
            version_id,
            region_id=held["region_id"],
            profile=engine,
            place_id=place_id,
            prepared=True,
        )
