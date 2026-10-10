"""What a caller can do with its worlds now, read from the authorities that decide it.

``GET /worlds/capabilities`` says, for each kind of world, how many the workspace holds, how many
the count policy allows, and whether making one is available now. ``GET /world/versions/
{version_id}/capabilities`` says, for one version of one world, its kind, the regions an edit may
place into, the society it holds or would be brought with, and each operation the product supports
on it, with its state. Each operation is a descriptor of :mod:`exulanica.api.capabilities`: the
route that performs it, the permissions that route declares and whether this caller holds them, its
state and the code of any refusal, its stale-base tokens, and the reads that list its options.

The version's read also lists ``actions``: every offered action of the action catalog
(:mod:`exulanica.world.action_catalog`), by its stable id, with its words, what it acts on, what
it costs and destroys, how it runs (its route and bind, and the plan step where the Companion
plans it), the permissions its route declares and whether this caller holds them, and, where an
operation above projects its route, that operation's state and code (``projected``). An action
whose subject is one being or thing, or the world apart from any version, is projected by no
version operation: it says ``projected: false`` and no state, which means "ask where its subject
is read" and never "not permitted".

Neither read writes, asks a model or decides anything its domain does not. A domain's adapter
states each state from the check its own write path makes: the regions are the one check every
placement makes (``WorldObjectRepository.source_facts``), a society's operations are the engine
table's, an arrangement's are the arrangement's own (``arrangements.version_refusal``), and a model
choice is its role's host's (:mod:`exulanica.api.role_hosts`). The adapters are named in code,
below; nothing a request or a catalog states chooses one. Every mutating route of a version is
either projected by one of them or named in :data:`NOT_PROJECTED` with the reason, and a test
holds the two together.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Final

import psycopg
from fastapi import APIRouter, Request

from exulanica.api.capabilities import (
    AVAILABLE,
    Availability,
    Base,
    Effect,
    Operation,
    Preview,
    Subjects,
    VersionContext,
    describe,
    installation_facts_of,
    surface,
    unavailable,
    unknown,
    unsupported,
)
from exulanica.api.dependencies import (
    CurrentSession,
    HeldPermissions,
    ScopedConnection,
    get_services,
    holds_as_guest,
)
from exulanica.api.permissions import Permission, Requires, rule_for
from exulanica.api.role_hosts import RoleContext
from exulanica.api.routes import (
    character_appearance,
    signal_comparisons,
    society_comparisons,
    world_clock,
    world_models,
)
from exulanica.api.routes.generated_worlds import create_generated_world, recipes, specification
from exulanica.api.routes.society import (
    advance_society,
    change_society_presence,
    create_society,
    society,
    take_newcomers_in_society,
)
from exulanica.api.routes.society_actions import record_action
from exulanica.api.routes.society_control import configure_control, manual_step, read_control
from exulanica.api.routes.workspace_assets import list_workspace_assets
from exulanica.api.routes.world_arrangements import (
    arrangement_apply_route,
    arrangement_catalog_route,
    arrangement_preview_route,
)
from exulanica.api.routes.world_assets import reviewed_asset_catalog
from exulanica.api.routes.world_behaviours import reviewed_behaviours
from exulanica.api.routes.world_compositions import (
    composition_apply_route,
    composition_preview_route,
    photo_point_map_apply_route,
    photo_point_map_preview_route,
)
from exulanica.api.routes.world_entries import SAVED_WORLD_CONFLICT, create_starter_entry
from exulanica.api.routes.world_environments import (
    add_environment_instance,
    move_environment_instance,
    remove_environment_instance,
    undo_environment_edit,
)
from exulanica.api.routes.world_objects import (
    add_authored_object,
    move_authored_object,
    move_authored_object_preview,
    remove_authored_object,
    remove_authored_object_preview,
    set_authored_object_behaviour,
    undo_authored_edit,
    undo_authored_edit_preview,
)
from exulanica.api.routes.world_things import (
    add_thing,
    move_thing,
    remove_thing,
    undo_thing_edit,
)
from exulanica.api.routes.world_traffic import world_traffic
from exulanica.api.routes.world_versions import alternate_version
from exulanica.api.routes.worlds import compose_personal_source_world, personal_source_world
from exulanica.api.services import Services
from exulanica.api.society_control_worker import host_playback_refusal
from exulanica.api.society_making import engine_holding_things
from exulanica.api.world_edit import OBJECT_PROBLEMS
from exulanica.api.world_scope import WorldId
from exulanica.graph.personal_sources import personal_sources
from exulanica.selection.validation import Session
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.world import action_catalog
from exulanica.world.arrangements import version_refusal
from exulanica.world.composition_preview import SOURCE_INVALIDATED
from exulanica.world.errors import InvalidatedSourceVersion, InvalidStructuralData
from exulanica.world.generated_worlds import unreadable_reason
from exulanica.world.object_repository import WorldObjectRepository, version_holds_things
from exulanica.world.personal_composition import personal_world_plan
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.society_action_repository import ENGINE_TAKES_NO_DIRECTED_ACTIONS
from exulanica.world.society_engines import SocietyEngine, society_engine
from exulanica.world.society_grounds import (
    UnknownSocietyGround,
    created_engine,
    placed_affordance_refusal,
    society_ground_for_composer,
)
from exulanica.world.traffic_episodes import TrafficRefused
from exulanica.world.worlds import (
    AUTHORED_STARTER,
    GENERATED,
    PERSONAL_SOURCE,
    WORLD_KINDS,
    WorldKind,
    WorldLimitReached,
    WorldsReadOnly,
    current_world_count_policy,
    may_register_worlds,
    refuse_past_limit,
    require_world,
    require_world_registration,
    workspace_worlds,
    world_kind,
)

__all__ = [
    "CREATION_PROFILE",
    "NOT_PROJECTED",
    "VERSION_ADAPTERS",
    "VERSION_PROFILE",
    "router",
    "version_capabilities_document",
    "version_context",
]

router = APIRouter(tags=["world"])

CREATION_PROFILE: Final = "exulanica.world-creation/v1"
VERSION_PROFILE: Final = "exulanica.world-capabilities/v1"
#: A version with no society yet: the operations that need one are refused by this name, the
#: reason the models read gives for the same state.
_SOCIETY_UNAVAILABLE: Final = "society_unavailable"
#: The code every object and environment edit answers a version whose source was invalidated with.
_INVALIDATED: Final = next(
    code for kind, _, code in OBJECT_PROBLEMS if kind is InvalidatedSourceVersion
)


def _kind_facts(kind: WorldKind) -> dict[str, bool]:
    return {
        "takes_photographs": kind.takes_photographs,
        "draws_generated_tiles": kind.draws_generated_tiles,
        "source_independent": kind.source_independent,
    }


def _permits(endpoint: Callable[..., Any], request: Request, held: frozenset[Permission]) -> bool:
    """Whether ``held`` may use the route ``endpoint`` serves, by that route's own declaration."""
    route = surface(request.app).route(endpoint)
    rule = rule_for(route.method, route.path)
    return isinstance(rule, Requires) and rule.permissions <= held


# -- making a world -------------------------------------------------------------------------------


def _starter(
    connection: psycopg.Connection,
    session: Session,
    services: Services,
    request: Request,
    held: frozenset[Permission],
) -> Operation:
    # The early answer of the starter's own rule: a workspace holding any saved entry is refused.
    holds = SavedWorldEntryRepository(connection, session.workspace_id).holds_entry()
    if not may_register_worlds(connection):
        state = unavailable(WorldsReadOnly.code)
    else:
        state = unavailable(SAVED_WORLD_CONFLICT) if holds else AVAILABLE
    return Operation(endpoint=create_starter_entry, availability=state, subject="workspace")


def _generated(
    connection: psycopg.Connection,
    session: Session,
    services: Services,
    request: Request,
    held: frozenset[Permission],
) -> Operation:
    try:
        # The creation route's own early checks, which may be stale and are never a permission:
        # a role that cannot register a world, then the count policy.
        require_world_registration(connection)
        # Asked for the smallest world there is, one tile: whether any town can be made now.
        refuse_past_limit(
            connection, session.workspace_id, GENERATED, guest=holds_as_guest(request), tiles=1
        )
        state = AVAILABLE
    except (WorldsReadOnly, WorldLimitReached) as exc:
        state = unavailable(exc.code)
    return Operation(
        endpoint=create_generated_world,
        availability=state,
        subject="workspace",
        options=(recipes, specification),
        # A generated world is drawn only from tiles a bake worker makes: where the installation
        # does not run one, a town made here would never be drawn.
        needs=("generated_tiles",),
    )


def _personal_source(
    connection: psycopg.Connection,
    session: Session,
    services: Services,
    request: Request,
    held: frozenset[Permission],
) -> Operation:
    # The plan the preview read serves is the one the write composes against; reading it reads
    # the review state of each photograph, so a caller who may not read that is told nothing.
    if not _permits(personal_source_world, request, held):
        state = unknown()
    else:
        sources = personal_sources(
            connection, session.workspace_id, reviewed_for=session.actor, store=services.store
        )
        plan = personal_world_plan(connection, session.workspace_id, sources, store=services.store)
        if plan.refusal is not None:
            state = unavailable(plan.refusal.code)
        elif plan.action == "create_world" and not may_register_worlds(connection):
            state = unavailable(WorldsReadOnly.code)
        else:
            state = AVAILABLE
    return Operation(
        endpoint=compose_personal_source_world,
        availability=state,
        subject="workspace",
        preview=Preview(personal_source_world, required=True, token="topology_digest"),
    )


#: How each kind of world is made, by the kind's registered name. Fixed in code.
CREATORS: Final[Mapping[str, Callable[..., Operation]]] = MappingProxyType(
    {AUTHORED_STARTER: _starter, GENERATED: _generated, PERSONAL_SOURCE: _personal_source}
)


@router.get(
    "/worlds/capabilities",
    summary="Whether each kind of world can be made in this workspace now, and how.",
)
def world_creation(
    connection: ScopedConnection,
    session: CurrentSession,
    held: HeldPermissions,
    request: Request,
) -> dict[str, Any]:
    services = get_services(request)
    policy = current_world_count_policy()
    guest = holds_as_guest(request)
    counts = Counter(world.kind for world in workspace_worlds(connection, session.workspace_id))
    routes = surface(request.app)
    facts = installation_facts_of(services)
    kinds = []
    for kind in WORLD_KINDS:
        creator = CREATORS.get(kind.name)
        kinds.append(
            {
                "kind": kind.name,
                "held": counts[kind.name],
                "limit": policy.limit(kind.name, guest=guest),
                "kind_facts": _kind_facts(kind),
                "create": None
                if creator is None
                else describe(
                    creator(connection, session, services, request, held), routes, held, facts
                ),
            }
        )
    return {
        "profile": CREATION_PROFILE,
        "policy": {
            "policy_id": policy.policy_id,
            "version": policy.version,
            "sha256": policy.sha256,
        },
        "kinds": kinds,
    }


# -- one version of a world -----------------------------------------------------------------------


def _version_base() -> tuple[Base, ...]:
    return (Base("base_state_sha256", alternate_version, "state_sha256"),)


def _society_base(*, control: bool = False, clock: bool = False) -> tuple[Base, ...]:
    bases = (Base("base_revision", read_control, "revision"),) if control else ()
    # A minute may pin the world clock's revision; another is refused stale_clock_revision.
    pinned = (Base("base_clock_revision", world_clock.read_clock, "revision"),) if clock else ()
    return (
        *bases,
        Base("base_tick", society, "current_tick"),
        Base("base_state_sha256", society, "state_sha256"),
        *pinned,
    )


def _society_reach(context: VersionContext) -> tuple[Effect, ...]:
    """Whether the world's people use an object placed in it, by the ground they stand on."""
    if context.ground is None:
        return ()
    refusal = placed_affordance_refusal(context.ground)
    return (Effect("society", AVAILABLE if refusal is None else unsupported(refusal)),)


def _object_operations(context: VersionContext) -> list[Operation]:
    state = unavailable(_INVALIDATED) if context.source.invalidated else AVAILABLE
    objects = Subjects(alternate_version, "objects")
    base = _version_base()
    return [
        Operation(
            add_authored_object,
            state,
            "version",
            context.bind,
            base=base,
            options=(reviewed_asset_catalog, reviewed_behaviours),
            effects=_society_reach(context),
        ),
        Operation(
            move_authored_object,
            state,
            "object",
            context.bind,
            objects,
            base=base,
            preview=Preview(move_authored_object_preview, required=False),
        ),
        Operation(
            remove_authored_object,
            state,
            "object",
            context.bind,
            objects,
            base=base,
            preview=Preview(remove_authored_object_preview, required=False),
        ),
        Operation(
            set_authored_object_behaviour,
            state,
            "object",
            context.bind,
            objects,
            base=base,
            options=(reviewed_behaviours,),
        ),
        Operation(
            undo_authored_edit,
            state,
            "version",
            context.bind,
            base=base,
            preview=Preview(undo_authored_edit_preview, required=False),
        ),
    ]


def _environment_operations(context: VersionContext) -> list[Operation]:
    state = unavailable(_INVALIDATED) if context.source.invalidated else AVAILABLE
    instances = Subjects(alternate_version, "environment_instances")
    base = _version_base()
    return [
        Operation(add_environment_instance, state, "version", context.bind, base=base),
        Operation(
            move_environment_instance,
            state,
            "environment_instance",
            context.bind,
            instances,
            base=base,
        ),
        Operation(
            remove_environment_instance,
            state,
            "environment_instance",
            context.bind,
            instances,
            base=base,
        ),
        Operation(undo_environment_edit, state, "version", context.bind, base=base),
    ]


def _thing_operations(context: VersionContext) -> list[Operation]:
    state = unavailable(_INVALIDATED) if context.source.invalidated else AVAILABLE
    things = Subjects(alternate_version, "things")
    base = _version_base()
    return [
        Operation(add_thing, state, "version", context.bind, base=base),
        Operation(move_thing, state, "thing", context.bind, things, base=base),
        Operation(remove_thing, state, "thing", context.bind, things, base=base),
        Operation(undo_thing_edit, state, "version", context.bind, base=base),
    ]


def _composition_operations(context: VersionContext) -> list[Operation]:
    state = unavailable(SOURCE_INVALIDATED) if context.source.invalidated else AVAILABLE
    base = _version_base()
    reach = _society_reach(context)
    # The reviewed catalog and the workspace's own admitted assets are the sources an object
    # composition names (source kinds reviewed_asset and workspace_asset).
    sources = (reviewed_asset_catalog, list_workspace_assets)
    return [
        Operation(
            composition_preview_route,
            state,
            "version",
            context.bind,
            base=base,
            options=sources,
            writes=False,
        ),
        Operation(
            composition_apply_route,
            state,
            "version",
            context.bind,
            base=base,
            preview=Preview(composition_preview_route, required=False),
            options=sources,
            effects=reach,
        ),
        Operation(
            photo_point_map_preview_route, state, "version", context.bind, base=base, writes=False
        ),
        Operation(
            photo_point_map_apply_route,
            state,
            "version",
            context.bind,
            base=base,
            preview=Preview(photo_point_map_preview_route, required=False),
        ),
    ]


def _arrangement_operations(context: VersionContext) -> list[Operation]:
    refusal = version_refusal(
        source_invalidated=context.source.invalidated,
        navigation=None if context.ground is None else context.ground.navigation,
    )
    if refusal is None:
        state: Availability = AVAILABLE
    elif context.source.invalidated:
        state = unavailable(refusal)
    else:
        state = unsupported(refusal)
    base = _version_base()
    return [
        Operation(
            arrangement_preview_route,
            state,
            "version",
            context.bind,
            base=base,
            options=(arrangement_catalog_route,),
            writes=False,
        ),
        Operation(
            arrangement_apply_route,
            state,
            "version",
            context.bind,
            base=base,
            preview=Preview(arrangement_preview_route, required=False),
            options=(arrangement_catalog_route,),
            effects=_society_reach(context),
        ),
    ]


def _playback_effect(context: VersionContext) -> tuple[Effect, ...]:
    """Whether the world advances on its own once played: this host's own playback answer."""
    refusal = host_playback_refusal(
        getattr(context.request.app.state, "society_control_worker", None),
        getattr(context.request.app.state, "society_control_thread", None),
        context.session.workspace_id,
        getattr(context.request.app.state, "playback_process", None),
    )
    return (Effect("playback", AVAILABLE if refusal is None else unavailable(refusal)),)


def _take_in(context: VersionContext, composable: bool) -> Availability:
    """Whether this version's people can take in what was placed after they came (``POST
    .../society/take-in``): only a living society does, and only where the engine table gives the
    version a society of things, the test a creation makes (``engine_holding_things``, read once
    for the context: the host offers them and the version holds a placed thing its ground
    admits), and where a first input can be composed (``composable``, the creation's own
    condition: without it the making answers 424 and nothing is erased)."""
    if context.society is None:
        return unavailable(_SOCIETY_UNAVAILABLE)
    if context.engine is None or context.engine.state_family != "living":
        return unsupported("society_takes_in_already")
    if context.takes_in is None:
        return unavailable("nothing_to_take_in")
    # The society of things is composed from the version's source, as a creation's is.
    return AVAILABLE if composable else unavailable("unavailable_society_input")


def _society_operations(context: VersionContext) -> list[Operation]:
    held = context.society is not None
    engine = context.engine

    def needs(
        flag: Callable[[SocietyEngine], bool], refusal: Callable[[SocietyEngine], str]
    ) -> Availability:
        """An operation the engine table decides: never on an engine without it (the held one,
        or the one this ground's society is created with), and not before a society is brought."""
        if engine is None:
            return unavailable(_SOCIETY_UNAVAILABLE)
        if not flag(engine):
            return unsupported(refusal(engine))
        return AVAILABLE if held else unavailable(_SOCIETY_UNAVAILABLE)

    playback = needs(lambda e: e.playback, lambda e: str(e.playback_refusal))
    people = Subjects(society, "state.inhabitants")
    configured = getattr(context.request.app.state, "society_initial_input", None) is not None
    # A new society's first input is composed from the version's source, so a source a committed
    # deletion invalidated, or a host without the input adapter, gives it none: the route answers
    # 424 unavailable_society_input. A society already held is read back, not composed again.
    composable = configured and not context.source.invalidated
    return [
        Operation(
            create_society,
            AVAILABLE if held or composable else unavailable("unavailable_society_input"),
            "version",
            context.bind,
        ),
        Operation(
            take_newcomers_in_society, _take_in(context, composable), "version", context.bind
        ),
        Operation(
            advance_society,
            AVAILABLE if held else unavailable(_SOCIETY_UNAVAILABLE),
            "version",
            context.bind,
            base=_society_base(clock=True),
        ),
        Operation(
            change_society_presence,
            needs(lambda e: e.presence, lambda e: "engine_keeps_its_people"),
            "version",
            context.bind,
            base=_society_base(),
            idempotency="idempotency_key",
        ),
        Operation(
            record_action,
            needs(lambda e: e.directed_actions, lambda e: ENGINE_TAKES_NO_DIRECTED_ACTIONS),
            "person",
            context.bind,
            people,
            base=_society_base(),
            idempotency="idempotency_key",
        ),
        Operation(
            configure_control,
            playback,
            "version",
            context.bind,
            base=(
                Base("base_revision", read_control, "revision"),
                Base("base_clock_revision", world_clock.read_clock, "revision"),
            ),
            effects=_playback_effect(context) if playback.state == "available" else (),
        ),
        Operation(
            manual_step,
            playback,
            "version",
            context.bind,
            base=_society_base(control=True, clock=True),
        ),
    ]


def _role_operations(context: VersionContext) -> list[Operation]:
    return world_models.role_operations(
        RoleContext(
            context.connection,
            context.session,
            context.request,
            context.world_id,
            context.version_id,
            context.source.snapshot_id,
        ),
        spending=context.spending(),
    )


def _traffic_operations(context: VersionContext) -> list[Operation]:
    # The roads the traffic read reads, refused by the codes that read answers them with.
    try:
        context.roads()
        state = AVAILABLE
    except TrafficRefused as exc:
        state = unavailable(exc.code)
    except UnsupportedNetworkError:
        state = unavailable("roads_unavailable")
    except InvalidStructuralData as exc:
        state = unavailable(unreadable_reason(exc))
    return [Operation(world_traffic, state, "version", context.bind, writes=False)]


#: Every adapter of a version's capability read, in the order its operations are listed. Fixed in
#: code: a domain adds its operations by adding its adapter here, reviewed.
VERSION_ADAPTERS: Final[tuple[Callable[[VersionContext], list[Operation]], ...]] = (
    _object_operations,
    _environment_operations,
    _thing_operations,
    _composition_operations,
    _arrangement_operations,
    _society_operations,
    _role_operations,
    society_comparisons.capability_operations,
    character_appearance.capability_operations,
    _traffic_operations,
    world_clock.capability_operations,
    signal_comparisons.capability_operations,
)

#: Mutating routes of a version no adapter projects, each with why. A test holds this table and the
#: adapters to every mutating route under ``/world/versions/{version_id}/``.
NOT_PROJECTED: Final[Mapping[tuple[str, str], str]] = MappingProxyType(
    {
        ("POST", "/world/versions/{version_id}/models/{role_key}/budget"): (
            "sets the world's budget for its minds, which is the world's and no version's; read "
            "with the world's models (GET /world/versions/{version_id}/models, the people's "
            "role's budget), and a Companion plan step states its descriptor itself"
        ),
        ("POST", "/world/versions/{version_id}/society/decisions"): (
            "retired: every request is refused by name (society_proposals_retired)"
        ),
        ("POST", "/world/versions/{version_id}/society/models"): (
            "records the same choice as POST /world/versions/{version_id}/models/{role_key}, which "
            "is projected for every role, for existing callers"
        ),
        ("POST", "/world/versions/{version_id}/society/things/{thing_id}/look"): (
            "chosen from the thing's card (GET "
            "/world/versions/{version_id}/society/things/{thing_id}), which names the looks it "
            "may wear; its subject is a society's thing, which no version operation enumerates"
        ),
        ("POST", "/world/versions/{version_id}/society/play"): (
            "its subject is one being of a society of things, which no version operation "
            "enumerates; the being's card (GET /world/versions/{version_id}/society/things/"
            "{thing_id}) says who decides for it"
        ),
        ("POST", "/world/versions/{version_id}/society/play/{subject_id}/answer"): (
            "answers the minute GET /world/versions/{version_id}/society/play/{subject_id}/turn "
            "offers, for a being the caller plays"
        ),
        ("POST", "/world/versions/{version_id}/society/play/{subject_id}/give-back"): (
            "gives back a being the caller plays (POST /world/versions/{version_id}/society/play)"
        ),
        ("DELETE", "/world/versions/{version_id}/society"): (
            "erases the society whole, which a capability read does not offer as something to do "
            "in the world; the society read (GET /world/versions/{version_id}/society) says "
            "whether there is one"
        ),
        ("POST", "/world/versions/{version_id}/society/experiments"): (
            "experiments run over an owned district's living society, which no saved world holds"
        ),
        ("POST", "/world/versions/{version_id}/society/experiments/{experiment_id}/attempts"): (
            "experiments run over an owned district's living society, which no saved world holds"
        ),
    }
)


def version_context(
    version_id: uuid.UUID,
    connection: psycopg.Connection,
    session: Session,
    held: frozenset[Permission],
    request: Request,
    world_id: str,
) -> VersionContext:
    """One version of one world as every adapter is given it, read once for a capability read.

    Another workspace's world or version and an invented one are the same
    :class:`~exulanica.world.errors.UnknownWorldResource`.
    """
    services = get_services(request)
    world = require_world(connection, session.workspace_id, world_id)
    source = WorldObjectRepository(
        connection, session.workspace_id, world_id=world_id, store=services.store
    ).source_facts(version_id)
    try:
        ground = society_ground_for_composer(source.composer_key)
    except UnknownSocietyGround:
        ground = None
    held_society = connection.execute(
        "select society_id,engine_version from world_society "
        "where workspace_id=%s and world_id=%s and version_id=%s",
        (session.workspace_id, world_id, version_id),
    ).fetchone()
    if held_society is not None:
        engine = society_engine(held_society["engine_version"])
    elif ground is not None:
        # On a host that offers societies of things, a version holding a thing its author placed
        # is brought to life as one where the engine table says so, as its entry states.
        holding = services.societies_of_things and version_holds_things(
            connection, session.workspace_id, world_id, version_id
        )
        engine = society_engine(created_engine(ground, holding_things=holding))
    else:
        engine = None
    takes_in = None
    if held_society is not None and engine is not None and engine.state_family == "living":
        # What the take-in route itself asks before it erases anything.
        takes_in = engine_holding_things(connection, session, services, world_id, version_id)
    return VersionContext(
        request=request,
        connection=connection,
        session=session,
        services=services,
        held=held,
        world_id=world_id,
        kind=world_kind(world.kind),
        version_id=version_id,
        source=source,
        ground=ground,
        society=held_society,
        engine=engine,
        takes_in=takes_in,
    )


def _actions(operations: list[dict[str, Any]], held: frozenset[Permission]) -> list[dict[str, Any]]:
    """Every offered action of the catalog for a caller holding ``held``: what the catalog states
    of it, its route's own permissions, and the state of the operation among ``operations`` (the
    version's descriptors, as served) that projects its route and bind, where one does."""
    served = []
    for action in action_catalog.offered():
        assert action.route is not None  # an offered action names its route
        method, _, path = action.route.partition(" ")
        rule = rule_for(method, path)
        required = rule.permissions if isinstance(rule, Requires) else frozenset()
        projecting = next(
            (
                described
                for described in operations
                if described["operation"] == action.route
                and all(described["bind"].get(key) == value for key, value in action.bind.items())
            ),
            None,
        )
        served.append(
            {
                **action.view(),
                "requires": sorted(str(permission) for permission in required),
                "permitted": required <= held,
                "projected": projecting is not None,
                "state": None if projecting is None else projecting["state"],
                "code": None if projecting is None else projecting["code"],
            }
        )
    return served


def version_capabilities_document(
    version_id: uuid.UUID,
    *,
    connection: psycopg.Connection,
    session: Session,
    held: frozenset[Permission],
    request: Request,
    world_id: str,
) -> dict[str, Any]:
    """What ``GET /world/versions/{version_id}/capabilities`` answers, for a caller in the same
    process, such as the Companion's planner, that holds the request's own connection and grant."""
    context = version_context(version_id, connection, session, held, request, world_id)
    routes = surface(request.app)
    facts = installation_facts_of(context.services)
    source = context.source
    operations = [
        describe(operation, routes, held, facts)
        for adapter in VERSION_ADAPTERS
        for operation in adapter(context)
    ]
    return {
        "profile": VERSION_PROFILE,
        "world_id": world_id,
        "version_id": str(version_id),
        "kind": context.kind.name,
        "kind_facts": _kind_facts(context.kind),
        "regions": {
            "state": "unavailable" if source.invalidated else "listed",
            "code": _INVALIDATED if source.invalidated else None,
            "region_ids": [] if source.invalidated else sorted(source.region_ids),
        },
        "society": {
            "held": context.society is not None,
            "engine": None if context.engine is None else context.engine.engine,
        },
        "operations": operations,
        "actions": _actions(operations, held),
    }


@router.get(
    "/world/versions/{version_id}/capabilities",
    summary="What can be done with this version of the world now: its regions, its society and "
    "each supported operation with its state.",
)
def version_capabilities(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    held: HeldPermissions,
    request: Request,
    world_id: WorldId,
) -> dict[str, Any]:
    return version_capabilities_document(
        version_id,
        connection=connection,
        session=session,
        held=held,
        request=request,
        world_id=world_id,
    )
