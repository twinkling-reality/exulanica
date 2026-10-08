"""The application: routers, and the one place a domain error becomes a status code.

Two things live here and nothing else does.

**The error map.** Every domain error in this codebase already says precisely what went wrong,
and the API's job is to turn that into a status code without losing the distinction or inventing
one. Three of the mappings are decisions rather than conventions:

*   ``unknown_reference`` is **404, never 403**. ``evaluation-methodology.md`` M10: "404, never
    403, so the surface is not an existence oracle. Nonexistent and foreign IDs return the
    identical code." A 403 would confirm that an id exists and belongs to somebody, which is
    exactly the thing a cross-tenant probe is looking for.
*   ``not_authorised`` **is** a 403, and that is not a contradiction. It means the session may
    not do a thing it asked to do with its own workspace's data, so there is no other tenant to
    leak the existence of.
*   A tombstoned address is **410 Gone**, not 404. The user deleted it, which is a different
    fact from it never having existed, and it is a fact they are entitled to.

**The startup check.** The application verifies at boot that the schema it is about to query is
the schema its migration files describe, and refuses to start otherwise. An edited migration is a
silent schema fork, and the failure it produces later is a wrong answer rather than an error.

**The derivative worker.** ``POST /intake`` runs the intake stage in the request thread and
queues the model stages by capture id, so an instance serving that route needs something draining
the queue. It runs on a daemon thread here, started with the application and stopped with it,
because a demonstration instance is one process. Whether it runs at all is configuration: an
instance can serve the API with the queue drained somewhere else, and that instance says so
through ``/readyz`` rather than looking identical to one whose worker is wedged.

**The body limit.** :mod:`exulanica.api.body_limit` refuses an over-large declared body before any
route sees it, which is the only place it can be refused before a multipart parser has already
written it to disk.

**Admission.** :mod:`exulanica.api.admission` sits just inside the body limit and decides, before
routing, a body, a thread or a connection, whether this process accepts a request now: 503
``capacity_exhausted`` for the process at a declared limit, 429 ``workspace_capacity_exhausted``
for a workspace at its share, both with ``Retry-After``, and 408 ``body_timeout`` for a body that
stopped arriving. The lifespan applies the thread limit those declarations are checked against, and
the photograph decode bound (:func:`exulanica.corpus.decode.configure_decode_concurrency`) is set
here, answering 503 ``capacity_exhausted`` for ``decodes`` when a decode waited out its turn.

**The permission floor.** :func:`exulanica.api.dependencies.authorise_route` is installed as an
application-level dependency, so it runs for every route before the route's own dependencies and
before any validation, and no route can leave it out. :func:`create_app` refuses to build an
application with a route :mod:`exulanica.api.permissions` does not declare, or a declaration for
a route it does not serve. A missing permission follows the error map's own rule: 404
``unknown_reference`` on a route addressed by an id, 403 ``not_authorised`` everywhere else. A
tile quota refusal is 429, like a budget ceiling, because in both cases this instance is
declining to spend rather than failing, and an egress refusal is 502 ``egress_refused``, a
dependency this instance will not reach rather than one that failed. Below the floor, a statement
the database role this instance connects as may not run is 403 ``database_privilege_refused`` on
every route, and is logged at ERROR, because a route its permissions allow reaching a write its
role may not make is a grant gap somewhere.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import threading
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Final

import anyio.to_thread
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg.errors import DeadlockDetected, InsufficientPrivilege, SerializationFailure

from exulanica.api.account_repository import AccountUnavailable
from exulanica.api.admission import (
    DECODES,
    Admission,
    AdmissionMiddleware,
    BodyTimeout,
    CapacityRefused,
    DerivativeQueueFull,
    require_capacity_declaration,
)
from exulanica.api.authorisation import TokenNotAccepted
from exulanica.api.body_limit import BodyLimit, BodyTooLarge
from exulanica.api.dependencies import authorise_route
from exulanica.api.permissions import PermissionRefused, require_complete_declaration
from exulanica.api.quotas import TileQuotaExceeded, TileQuotaUndeclared
from exulanica.api.routes import (
    accounts,
    capabilities,
    character_appearance,
    companion,
    door,
    environment_sources,
    evidence,
    formation,
    generated_worlds,
    geometry,
    graph,
    health,
    identity,
    intake,
    interaction,
    materials,
    operations,
    person_consent,
    personal_admission,
    place_name_rights,
    reconstruction_admission,
    references,
    scene_segments,
    selection,
    selection_actions,
    selection_environment,
    signal_comparisons,
    society,
    society_actions,
    society_comparisons,
    society_control,
    society_district,
    society_experiments,
    society_models,
    spending,
    style_packs,
    thing_store,
    things,
    tiles,
    workspace_assets,
    world,
    world_arrangements,
    world_assets,
    world_behaviours,
    world_clock,
    world_compositions,
    world_drafts,
    world_entries,
    world_environments,
    world_flight,
    world_generation,
    world_kinds,
    world_models,
    world_objects,
    world_projects,
    world_read,
    world_things,
    world_traffic,
    world_versions,
    world_write,
    worlds,
)
from exulanica.api.routes.selection import ModelNotConfigured, failure_extensions
from exulanica.api.services import Services, build_services
from exulanica.api.traffic_signal_controller import TrafficSignalController
from exulanica.corpus.decode import DecodeBusy, configure_decode_concurrency
from exulanica.db.migrate import verify_schema
from exulanica.db.roles import assert_runtime_role
from exulanica.deletion.restore import verify_restore
from exulanica.errors import (
    BlobNotFoundError,
    EpistemicViolation,
    IntegrityError,
    ObjectStoreError,
    ObjectStoreUnavailable,
    TombstonedError,
)
from exulanica.grammar.errors import (
    GrammarError,
    InvalidParameterError,
    InvalidRecordError,
    UnregisteredGrammarError,
)
from exulanica.identity.subjects import (
    AlreadyIdentified,
    IdentityError,
    NeverSame,
    NotUndoable,
    UnknownSubject,
)
from exulanica.models.egress import EgressRefused
from exulanica.models.errors import (
    BudgetExceededError,
    ModelError,
    ModelUnavailableError,
    NoFallbackError,
    StructuredOutputError,
    TransportError,
    TruncatedResponseError,
)
from exulanica.models.policy import HostedRequestRefused, NoHostedRequestPolicy
from exulanica.models.spending import SpendingRefused
from exulanica.selection.validation import RejectionCode, SelectionRejected
from exulanica.world import (
    ExpiredPreview,
    InvalidInteractionData,
    InvalidInteractionPreviewState,
    InvalidPreviewState,
    InvalidStyleData,
    ProtectedTopologyConflict,
    StaleInteractionPolicy,
    StaleSocietyState,
    StaleStyleVersion,
    StyleWriteBusy,
    UnavailableAsset,
    UnknownSociety,
    UnknownWorldResource,
    WorldNotConfigured,
    seed_reviewed_assets,
)
from exulanica.world.flight_input import close_flight_worker
from exulanica.world.kinds.worker import close_kind_worker
from exulanica.world.society import SocietyBytesNotRead
from exulanica.world.specification_samples import close_sample_worker
from exulanica.world.style_pack_library import style_pack_library
from exulanica.world.thing_library import thing_library
from exulanica.world.traffic_host import close_traffic_worker

__all__ = ["create_app"]

_LOG = logging.getLogger(__name__)

#: Which rejection code means which status. See the module docstring for why unknown_reference
#: is a 404 and not_authorised is a 403.
_REJECTION_STATUS: Final[dict[RejectionCode, int]] = {
    RejectionCode.MALFORMED_PLAN: 400,
    RejectionCode.COST_BOUND_EXCEEDED: 400,
    RejectionCode.UNKNOWN_REFERENCE: 404,
    RejectionCode.NOT_AUTHORISED: 403,
}


def _model_failure_detail(exc: ModelError) -> str:
    """What a model failure says in a problem body: this instance's words, never another's.

    A transport error carries the provider's answer, a withdrawn model the provider's wording,
    and a refused form an excerpt of the model's own reply; each is said here in product words,
    and what the request paid for is in the problem's ``execution`` member. Every other model
    error's text is this instance's own sentence about its own limit or configuration (a budget
    ceiling, a truncation on this side's token limit, an egress declaration), and is kept.
    """
    if isinstance(exc, TransportError):
        if exc.timed_out:
            return "a model request timed out before its reply arrived"
        if exc.reached_provider is False:
            return "a model request could not reach the model endpoint"
        return "the model endpoint could not answer a request"
    if isinstance(exc, (NoFallbackError, ModelUnavailableError)):
        return "no model the request's role can reach is available"
    if isinstance(exc, StructuredOutputError):
        return "a model's reply could not be read as the form it was asked to fill"
    return str(exc)


def _problem(
    status: int, code: str, detail: str, extensions: Mapping[str, object] | None = None
) -> JSONResponse:
    """One response shape for every failure, so a client has one thing to parse.

    ``extensions`` are further members of a problem that has more to say (RFC 9457), such as the
    execution record of a Companion request a model error ended. They never replace
    ``code`` or ``detail``.
    """
    content: dict[str, object] = {**(extensions or {}), "code": code, "detail": detail}
    return JSONResponse(status_code=status, content=content)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Refuse to serve a schema this code does not recognise, then start what drains the queue.

    In that order, and the order is the point. A worker started against a schema this code does
    not recognise would begin writing before the check that exists to stop it, and what that
    produces is a wrong artifact rather than a refusal to boot.

    Seeding the reviewed assets sits between those two for the same ordering reason. Migration
    0042 installs three registry rows that name bytes by digest, and only a process holding the
    object store can put those bytes there, so the schema check runs first and the store write
    follows it. It is here rather than in ``build_services`` because that function resolves
    configuration and returns, and because a hand-constructed ``Services`` still runs this
    lifespan: the seeding a deployment depends on is the seeding the tests exercise.
    """
    services: Services = app.state.services
    # Every synchronous route and dependency runs on this limiter, and admission's limits are
    # checked against its size, so it is set before the first request rather than left to anyio.
    anyio.to_thread.current_default_thread_limiter().total_tokens = services.admission.threads
    if app.state.verify_schema_at_boot:
        verify_schema(services.database)
        with services.database.unscoped() as connection:
            assert_runtime_role(connection)
    verify_restore(services.database, services.restore_state_path)
    # Idempotent under content addressing: three hashes of about 800 bytes on a warm start, and
    # no write. Deliberately not guarded by try/except. A store this cannot write is a store the
    # evidence path cannot write either, so it is a broken deployment rather than a degraded
    # feature, and it should say so at boot instead of at the first asset read.
    seed_reviewed_assets(services.store)
    # The committed style pack library, read and held to its digests once, here, so a library that
    # breaks its own rules stops the start with the pack and the rule named rather than refusing
    # the first page that asks for a look (exulanica.world.style_pack_library).
    style_pack_library()
    # The shipped thing library likewise: every kind, look and look container held to its pins
    # (exulanica.world.thing_library), the furniture's containers being the reviewed assets above.
    thing_library()
    traffic_signals = TrafficSignalController(
        services.database,
        services.model_client,
        services.society_control_workspaces,
        services.person_decision_policy,
    )
    app.state.traffic_signal_controller = traffic_signals
    # Played here, in a process of its own (EXULANICA_PLAYBACK_WORKER=process: that process also
    # seals coupled traffic, so this one keeps its controller for reads only), or by nobody.
    society_worker = (
        services.build_society_control_worker() if services.playback_player == "here" else None
    )
    app.state.playback_process = services.playback_process()
    society_stop = threading.Event()
    society_thread = (
        threading.Thread(
            target=society_worker.run, args=(society_stop,), name="society-playback", daemon=True
        )
        if society_worker is not None
        else None
    )
    app.state.society_control_worker = society_worker
    app.state.society_control_thread = society_thread
    # Comparisons started from the application are played here unless the configuration names
    # another player or none (EXULANICA_COMPARISON_WORKER); this process serves other work too, so
    # they keep its share.
    comparison_worker = (
        services.build_comparison_worker(keeps_share=True)
        if services.runs_comparison_worker
        else None
    )
    comparison_thread = (
        threading.Thread(
            target=comparison_worker.run, args=(society_stop,), name="comparisons", daemon=True
        )
        if comparison_worker is not None
        else None
    )
    # Reference jobs (notes on what the things in a person's words look like) are played here
    # unless the configuration sets EXULANICA_REFERENCE_WORKER off; each is short and bounded.
    reference_worker = services.build_reference_worker() if services.runs_reference_worker else None
    reference_thread = (
        threading.Thread(
            target=reference_worker.run, args=(society_stop,), name="references", daemon=True
        )
        if reference_worker is not None
        else None
    )
    app.state.reference_worker = reference_worker
    app.state.reference_thread = reference_thread
    if services.reference_adapter_for is not None:
        # Reference jobs no worker here will take are ended, and their words blanked, at every
        # start, whether or not the worker runs.
        try:
            services.sweep_references()
        except Exception as failure:
            _LOG.warning(
                "the reference sweep at startup failed", extra={"failure": type(failure).__name__}
            )
    worker = services.build_derivative_worker()
    app.state.derivative_worker = worker
    if worker is not None:
        worker.start()
    try:
        if society_thread is not None:
            society_thread.start()
        if comparison_thread is not None:
            comparison_thread.start()
        if reference_thread is not None:
            reference_thread.start()
        if services.playback_player != "process":
            traffic_signals.start()
        # What startup made lives as long as the server. A full garbage collection walks every
        # tracked object and holds the interpreter's lock while it does, so no request the server is
        # answering moves: over about 172,000 objects once the application is imported, 33 to 36 ms
        # in a development measurement, named among the earlier measurements of
        # docs/evaluation/2026-09-26-flight-worker-v3-preregistration.json. The 30.9 ms pauses two
        # timing records met are inferred to be such collections; the record timed with this freeze
        # met none (docs/evaluation/2026-09-26-flight-worker-v3.json). Collected once and frozen,
        # those objects are never walked again; collection stays automatic for everything later.
        gc.collect()
        gc.freeze()
        yield
    finally:
        gc.unfreeze()
        society_stop.set()
        if society_thread is not None:
            await asyncio.to_thread(society_thread.join)
        if comparison_thread is not None:
            await asyncio.to_thread(comparison_thread.join)
        if reference_thread is not None:
            await asyncio.to_thread(reference_thread.join)
        await asyncio.to_thread(traffic_signals.close)
        if worker is not None:
            worker.stop()
        # The flight's worker process starts at the first flight read; it stops with the server.
        await asyncio.to_thread(close_flight_worker)
        # So does the traffic's, at the first traffic read.
        await asyncio.to_thread(close_traffic_worker)
        # And the samples', at the first drafted specification.
        await asyncio.to_thread(close_sample_worker)
        await asyncio.to_thread(close_kind_worker)


def create_app(services: Services | None = None, *, verify: bool = True) -> FastAPI:
    """Build the application. ``services`` is injectable so a test does not read the environment.

    ``verify=False`` skips the boot-time schema check, and exists for the tests that build an app
    against a throwaway schema the migration runner has not recorded. Nothing in a deployment
    should pass it. It skips **only** that check: the lifespan still runs, because it also owns
    the derivative worker and those are two decisions rather than one. Whether the worker runs is
    a property of the services, and it is off for a hand-constructed one.
    """
    app = FastAPI(
        title="Exulanica",
        summary="Worlds for AI Agents. Every historical claim resolves to its source.",
        version="0.1.0",
        lifespan=_lifespan,
        # Every route, by construction. See exulanica.api.dependencies for why it is here rather
        # than in each route.
        dependencies=[Depends(authorise_route)],
    )
    app.state.services = services or build_services()
    app.state.society_base_tick_interval_ms = app.state.services.society_base_tick_interval_ms
    if app.state.services.society_runtime is not None:
        runtime = app.state.services.society_runtime
        app.state.society_initial_input = runtime.initial_input
        app.state.society_input_authorizer = runtime.authorize
        app.state.society_authored_edit = runtime.authored_edit
    app.state.verify_schema_at_boot = verify
    app.state.admission = Admission(app.state.services.admission)
    configure_decode_concurrency(app.state.services.admission.decodes)
    # Pure ASGI and just inside the body limit, so a refusal comes before routing, before any body
    # is read and before a thread or a connection is taken. Added first, because the middleware
    # added last is the outermost.
    app.add_middleware(AdmissionMiddleware, admission=app.state.admission)
    # Pure ASGI and outermost, so it runs before routing and before any body is read; a route
    # whose body is a small document states its own tighter limit beside the route.
    app.add_middleware(
        BodyLimit,
        routes=(*world_kinds.BODY_LIMITS, *door.BODY_LIMITS, *workspace_assets.BODY_LIMITS),
    )

    app.include_router(health.router)
    app.include_router(accounts.router)
    app.include_router(graph.router)
    app.include_router(geometry.router)
    app.include_router(geometry.scene_router)
    app.include_router(scene_segments.router)
    app.include_router(selection.router)
    app.include_router(selection_actions.router)
    app.include_router(selection_environment.router)
    app.include_router(society.router)
    app.include_router(society_actions.router)
    app.include_router(society_control.router)
    app.include_router(society_comparisons.router)
    app.include_router(society_models.router)
    app.include_router(society_district.router)
    app.include_router(society_experiments.router)
    app.include_router(character_appearance.router)
    app.include_router(materials.router)
    app.include_router(workspace_assets.router)
    app.include_router(tiles.router)
    app.include_router(companion.router)
    app.include_router(environment_sources.router)
    app.include_router(identity.router)
    app.include_router(evidence.router)
    app.include_router(formation.router)
    app.include_router(intake.router)
    app.include_router(operations.router)
    app.include_router(spending.router)
    app.include_router(person_consent.router)
    app.include_router(personal_admission.router)
    app.include_router(place_name_rights.router)
    app.include_router(reconstruction_admission.router)
    app.include_router(world.router)
    # The authored world under /world, in matching order: reviewed assets, the committed style pack
    # library and behaviours, versions, environment instances, objects, compositions, arrangements.
    # tests/snapshots/api-routes.json records it. The shipped thing library is under /things, and
    # a workspace's own looks and kinds beside it.
    app.include_router(world_assets.router)
    app.include_router(style_packs.router)
    app.include_router(things.router)
    app.include_router(thing_store.router)
    app.include_router(world_behaviours.router)
    app.include_router(world_versions.router)
    app.include_router(world_environments.router)
    app.include_router(world_things.router)
    app.include_router(world_objects.router)
    app.include_router(world_compositions.router)
    app.include_router(world_arrangements.router)
    app.include_router(world_entries.router)
    app.include_router(world_clock.router)
    app.include_router(world_flight.router)
    app.include_router(world_traffic.router)
    app.include_router(signal_comparisons.router)
    app.include_router(world_models.router)
    app.include_router(capabilities.router)
    app.include_router(interaction.router)
    app.include_router(world_projects.router)
    app.include_router(world_read.router)
    app.include_router(world_write.router)
    app.include_router(world_generation.router)
    app.include_router(worlds.router)
    app.include_router(generated_worlds.router)
    app.include_router(generated_worlds.tiles_router)
    app.include_router(world_kinds.router)
    app.include_router(world_kinds.site_router)
    app.include_router(references.router)
    app.include_router(world_drafts.router)
    app.include_router(door.router)
    # After the last router and before the application is handed to anybody: a route nobody
    # declared, or a declaration for a route that is gone, is a build failure with its name in it.
    require_complete_declaration(app)
    require_capacity_declaration(app)

    @app.exception_handler(BodyTooLarge)
    async def _too_large(_request: Request, exc: BodyTooLarge) -> JSONResponse:
        # Raised out of the wrapped `receive` while the body was still arriving, which is the
        # only place a request that declared no length can be stopped before it is all on disk.
        return _problem(413, "body_too_large", exc.detail)

    @app.exception_handler(BodyTimeout)
    async def _body_timeout(_request: Request, exc: BodyTimeout) -> JSONResponse:
        # Raised out of admission's wrapped `receive`; the connection ends with the answer, as it
        # does for a body that is too large, because the rest of the body is never read.
        response = _problem(408, "body_timeout", exc.detail)
        response.headers["Connection"] = "close"
        return response

    @app.exception_handler(CapacityRefused)
    async def _capacity(_request: Request, exc: CapacityRefused) -> JSONResponse:
        # A workspace at its share, found when the caller was resolved and before the route ran.
        return exc.response()

    @app.exception_handler(DecodeBusy)
    async def _decode_busy(_request: Request, _exc: DecodeBusy) -> JSONResponse:
        # A decode waited out its turn: nothing was decoded, so the request can be sent again.
        return CapacityRefused(DECODES, workspace=False).response()

    @app.exception_handler(DerivativeQueueFull)
    async def _queue_full(_request: Request, exc: DerivativeQueueFull) -> JSONResponse:
        return exc.response()

    @app.exception_handler(TokenNotAccepted)
    async def _unauthenticated(_request: Request, exc: TokenNotAccepted) -> JSONResponse:
        return _problem(401, "unauthenticated", str(exc))

    @app.exception_handler(AccountUnavailable)
    async def _account_unavailable(_request: Request, _exc: AccountUnavailable) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"code": "account_unavailable", "detail": "Account service is unavailable"},
            headers={"Cache-Control": "private, no-store"},
        )

    @app.exception_handler(PermissionRefused)
    async def _refused(_request: Request, exc: PermissionRefused) -> JSONResponse:
        # 404 on an id-addressed route and 403 elsewhere, decided in exulanica.api.permissions
        # from the route template alone, so the answer cannot depend on whether the id exists.
        return _problem(exc.status, exc.code, exc.detail)

    @app.exception_handler(InsufficientPrivilege)
    async def _database_privilege(request: Request, exc: InsufficientPrivilege) -> JSONResponse:
        # SQLSTATE 42501 reached a route: a table grant the role lacks, a row policy or a guard
        # trigger refused a statement the route's permissions let it run. A refusal rather than a
        # crash, so 403 by name instead of a bare 500. The same answer on an id-addressed route:
        # a table grant is checked before any row is read, so it cannot say whether an id exists,
        # and a policy or trigger refusal answers one status here where it answered 500 before.
        # The detail names no table; the log line keeps the database's own words for an operator.
        _LOG.error(
            "The database refused %s %s: SQLSTATE %s, %s",
            request.method,
            getattr(request.scope.get("route"), "path", request.url.path),
            exc.sqlstate,
            exc.diag.message_primary,
        )
        return _problem(
            403,
            "database_privilege_refused",
            "this instance's database role may not do what this request asked",
        )

    @app.exception_handler(SerializationFailure)
    @app.exception_handler(DeadlockDetected)
    async def _transient_conflict(request: Request, exc: Exception) -> JSONResponse:
        # SQLSTATE 40001 or 40P01: the database refused this request's statement for a moment,
        # for a conflict with another transaction (migration 0041's asset read barrier is one).
        # Transient by definition, so the same request can be sent again; "busy", as the routes
        # that meet a held lock say it. A route that knows more answers first with its own code.
        _LOG.warning(
            "A transient database conflict ended %s %s: SQLSTATE %s",
            request.method,
            getattr(request.scope.get("route"), "path", request.url.path),
            getattr(exc, "sqlstate", None),
        )
        return JSONResponse(
            status_code=409,
            content={
                "code": "busy",
                "detail": (
                    "the database refused this request for a moment, for a conflict with another "
                    "transaction; the same request can be sent again after 1 second"
                ),
                "retry_after_seconds": 1,
            },
            headers={"Retry-After": "1"},
        )

    @app.exception_handler(TileQuotaExceeded)
    async def _tile_quota(_request: Request, exc: TileQuotaExceeded) -> JSONResponse:
        return _problem(429, "tile_quota_exceeded", str(exc))

    @app.exception_handler(TileQuotaUndeclared)
    async def _tile_quota_undeclared(_request: Request, exc: TileQuotaUndeclared) -> JSONResponse:
        return _problem(429, "tile_quota_undeclared", str(exc))

    @app.exception_handler(SelectionRejected)
    async def _rejected(_request: Request, exc: SelectionRejected) -> JSONResponse:
        # A Companion request can end here after it paid for its planner and composer, so the
        # record it noted travels with the problem, as with every refusal below that can.
        return _problem(
            _REJECTION_STATUS[exc.code], str(exc.code), exc.detail, failure_extensions(exc)
        )

    @app.exception_handler(UnknownSubject)
    async def _unknown(_request: Request, exc: UnknownSubject) -> JSONResponse:
        # Same code as a nonexistent id, for the same reason: the identity surface is not an
        # existence oracle either.
        return _problem(404, "unknown_reference", str(exc))

    @app.exception_handler(AlreadyIdentified)
    async def _conflict(_request: Request, exc: AlreadyIdentified) -> JSONResponse:
        return _problem(409, "already_identified", str(exc))

    @app.exception_handler(NeverSame)
    async def _never_same(_request: Request, exc: NeverSame) -> JSONResponse:
        return _problem(409, "never_same", str(exc))

    @app.exception_handler(SocietyBytesNotRead)
    async def _society_race(_request: Request, exc: SocietyBytesNotRead) -> JSONResponse:
        # A race, not a refusal: whatever route met it, the whole request is asked again.
        return _problem(exc.status, exc.code, str(exc))

    @app.exception_handler(NotUndoable)
    async def _not_undoable(_request: Request, exc: NotUndoable) -> JSONResponse:
        return _problem(409, "not_undoable", str(exc))

    @app.exception_handler(IdentityError)
    async def _identity(_request: Request, exc: IdentityError) -> JSONResponse:
        return _problem(409, "identity_conflict", str(exc))

    @app.exception_handler(EpistemicViolation)
    async def _epistemic(_request: Request, exc: EpistemicViolation) -> JSONResponse:
        # 422 rather than 400: the request was well formed and the claim it carried was not
        # permitted under the provenance class it asked for.
        return _problem(422, "epistemic_violation", str(exc), failure_extensions(exc))

    @app.exception_handler(TombstonedError)
    async def _tombstoned(_request: Request, exc: TombstonedError) -> JSONResponse:
        return _problem(410, "tombstoned", str(exc), failure_extensions(exc))

    @app.exception_handler(BlobNotFoundError)
    async def _missing(_request: Request, exc: BlobNotFoundError) -> JSONResponse:
        return _problem(404, "unknown_reference", "no such evidence", failure_extensions(exc))

    @app.exception_handler(IntegrityError)
    async def _integrity(_request: Request, exc: IntegrityError) -> JSONResponse:
        # Deliberately loud and deliberately not a 404. Stored bytes that do not hash to the key
        # they are stored under means a citation has stopped verifying, and serving anything at
        # all here would hide it.
        return _problem(500, "integrity_failure", str(exc))

    @app.exception_handler(ObjectStoreError)
    async def _store_unavailable(_request: Request, exc: ObjectStoreError) -> JSONResponse:
        # The content store is an upstream this instance depends on: an endpoint that cannot be
        # reached, or a bucket the store refuses to trust. 503 with the store's stable reason as
        # the detail, rather than an unhandled 500, which this API keeps for `integrity_failure`.
        # The reason and not the message: the message names object keys. Retry-After only when
        # waiting can help; a refused bucket waits for its operator.
        response = _problem(503, "store_unavailable", exc.code)
        if isinstance(exc, ObjectStoreUnavailable):
            response.headers["Retry-After"] = "30"
        return response

    @app.exception_handler(ModelError)
    async def _model(_request: Request, exc: ModelError) -> JSONResponse:
        # **A question that could not be planned or answered is refused, not crashed.**
        #
        # `propose_plan` re-raises StructuredOutputError after its one repair, because there is
        # no honest default plan: an empty plan is legal and means "everything", so returning
        # one would answer a question the user did not ask. That refusal reached the boundary as
        # an unhandled exception, which is a 500 with no body and no code, and a caller cannot
        # tell it from the server falling over.
        #
        # 502 rather than 500, and it is not decoration. The models are an upstream this
        # instance depends on and does not control, so the failure is about that dependency
        # rather than about stored state, and the one 500 this API issues stays reserved for
        # `integrity_failure`, where it means a citation has stopped verifying.
        #
        # Two exceptions, and both are cases where nothing upstream failed. A budget ceiling is
        # this instance declining to spend. And a truncated response is a `max_tokens` on this
        # side that does not clear the model's reasoning overhead: `exulanica.models.errors` says
        # so in its own module docstring, that it "names a configuration mistake, not a model
        # failure, and says so, because the opposite reading has already cost this project one
        # wrong conclusion". Filing it as `model_refused` would be that reading.
        #
        # A Companion request the error ended carries what it had already paid for, the same
        # execution block a completed request returns, as a member of the problem.
        extensions = failure_extensions(exc)
        if isinstance(exc, BudgetExceededError):
            # The durable authority's refusal says which allowance refused and whether asking
            # again can succeed; the process's own fuse carries no such member.
            if isinstance(exc, SpendingRefused):
                extensions = {**extensions, "spending": exc.problem_member()}
            return _problem(429, "budget_exceeded", str(exc), extensions)
        if isinstance(exc, EgressRefused):
            return _problem(502, "egress_refused", str(exc), extensions)
        if isinstance(exc, TruncatedResponseError):
            return _problem(500, "model_output_truncated", str(exc), extensions)
        return _problem(502, "model_refused", _model_failure_detail(exc), extensions)

    @app.exception_handler(ModelNotConfigured)
    async def _no_model(_request: Request, exc: ModelNotConfigured) -> JSONResponse:
        # A route that needs a model, on an instance with no credential. 503 as it always was,
        # now with the code a capability read gives the same condition; the detail is unchanged
        # because clients recognise the sentence.
        return _problem(503, exc.code, str(exc))

    @app.exception_handler(HostedRequestRefused)
    async def _hosted_refused(_request: Request, exc: HostedRequestRefused) -> JSONResponse:
        # The account holder's rules refused a hosted request as it was leaving, and nothing was
        # sent: a photograph's model right ended after the route checked it, for instance. 409,
        # the status this API gives a privacy refusal elsewhere: the request was well formed and
        # authorised, and what refused it is the account holder's current decision, so the same
        # request is answered once that decision allows it. The detail names which rule refused.
        return _problem(409, "hosted_request_refused", str(exc), failure_extensions(exc))

    @app.exception_handler(NoHostedRequestPolicy)
    async def _no_hosted_policy(_request: Request, exc: NoHostedRequestPolicy) -> JSONResponse:
        # A route reached a model through a client nobody attached the workspace's rules to, so
        # the client refused to send and nothing left. That is a fault in this instance, not in
        # the caller's request and not upstream: 500, as a configuration mistake on this side is
        # (``model_output_truncated``), and named, so it cannot be taken for a crash or a model's
        # refusal.
        return _problem(500, "no_hosted_request_policy", str(exc), failure_extensions(exc))

    @app.exception_handler(InvalidStyleData)
    async def _invalid_style(_request: Request, exc: InvalidStyleData) -> JSONResponse:
        return _problem(422, "invalid_style_data", str(exc), failure_extensions(exc))

    @app.exception_handler(InvalidInteractionData)
    async def _invalid_interaction(_request: Request, exc: InvalidInteractionData) -> JSONResponse:
        return _problem(422, "invalid_interaction_data", str(exc))

    @app.exception_handler(StaleInteractionPolicy)
    async def _stale_interaction(_request: Request, exc: StaleInteractionPolicy) -> JSONResponse:
        return _problem(409, "stale_interaction_policy", str(exc))

    @app.exception_handler(InvalidInteractionPreviewState)
    async def _interaction_preview_state(
        _request: Request, exc: InvalidInteractionPreviewState
    ) -> JSONResponse:
        return _problem(409, "invalid_interaction_preview_state", str(exc))

    @app.exception_handler(StaleStyleVersion)
    async def _stale_style(_request: Request, exc: StaleStyleVersion) -> JSONResponse:
        return _problem(409, "stale_style_version", str(exc))

    @app.exception_handler(StyleWriteBusy)
    async def _style_busy(_request: Request, exc: StyleWriteBusy) -> JSONResponse:
        # Another writer held the world's look past the wait a write gives it; nothing was written,
        # so the same request is answered once the other write ends. "busy", as the other routes
        # that meet a held lock say it.
        return _problem(409, "busy", str(exc))

    @app.exception_handler(ProtectedTopologyConflict)
    async def _protected_topology(
        _request: Request, exc: ProtectedTopologyConflict
    ) -> JSONResponse:
        return _problem(409, "protected_topology_conflict", str(exc))

    @app.exception_handler(UnavailableAsset)
    async def _unavailable_asset(_request: Request, exc: UnavailableAsset) -> JSONResponse:
        return _problem(424, "unavailable_asset", str(exc))

    @app.exception_handler(UnknownWorldResource)
    async def _unknown_world(_request: Request, exc: UnknownWorldResource) -> JSONResponse:
        return _problem(404, "unknown_reference", "no such world resource", failure_extensions(exc))

    @app.exception_handler(UnknownSociety)
    async def _unknown_society(_request: Request, _exc: UnknownSociety) -> JSONResponse:
        return _problem(404, "unknown_reference", "no such society")

    @app.exception_handler(StaleSocietyState)
    async def _stale_society(_request: Request, exc: StaleSocietyState) -> JSONResponse:
        return _problem(409, "stale_society_state", str(exc))

    @app.exception_handler(InvalidPreviewState)
    async def _preview_state(_request: Request, exc: InvalidPreviewState) -> JSONResponse:
        return _problem(409, "invalid_preview_state", str(exc))

    @app.exception_handler(ExpiredPreview)
    async def _expired_preview(_request: Request, exc: ExpiredPreview) -> JSONResponse:
        return _problem(409, "preview_expired", str(exc))

    @app.exception_handler(WorldNotConfigured)
    async def _world_not_configured(_request: Request, exc: WorldNotConfigured) -> JSONResponse:
        return _problem(409, "world_not_configured", str(exc), failure_extensions(exc))

    # -- the generator's refusals ----------------------------------------------------------
    #
    # A REFUSAL IS THE FEATURE HERE, not a side effect. The cascade in
    # exulanica.grammar.parameters refuses an unknown parameter, an unknown level, a second
    # binding at one level and a value outside its declared range rather than ignoring any of
    # them, and each refusal names the parameter and says what was wrong with it. Before these
    # handlers existed nothing in this map mentioned any member of exulanica.grammar.errors and
    # there is no catch-all, so every one of those refusals reached a client as a bare 500
    # carrying none of it. That was a missing check rather than a wrong line: thirty-odd
    # handlers and no gap anybody could read, visible only by asking what happens to a class
    # nobody listed.
    #
    # THE LINE IS THE ONE exulanica.grammar.errors ALREADY DRAWS, in its own words: "the
    # difference between them is the difference between a caller's mistake and a data file's".
    # Mapping the base class alone would collapse the two and answer 422 for a broken reviewed
    # catalog, telling a caller to fix a request they got right.
    #
    # WHICH SIDE OF THAT LINE A CLASS FALLS ON DEPENDS ON WHAT A REQUEST CAN REACH, so it is
    # decided per class and not per hierarchy. InvalidSeedError is the example worth keeping:
    # it looks like a caller's mistake and is not one here, because
    # exulanica.api.routes.world_generation DERIVES the seed from the specification and no route
    # accepts one. A seed this codebase built and cannot parse is this codebase's fault, so it
    # falls through to the 500 below rather than getting a 422 of its own.
    @app.exception_handler(InvalidParameterError)
    async def _invalid_parameter(_request: Request, exc: InvalidParameterError) -> JSONResponse:
        # 422 rather than 400: the request parsed and the specification it carried is the problem.
        # The message is passed through verbatim because it already names the parameter, the value
        # and the bound or level that refused it. Anything summarised here would be a second
        # statement of the same fact, free to drift from the one the cascade makes.
        return _problem(422, "invalid_parameter", str(exc))

    @app.exception_handler(InvalidRecordError)
    async def _invalid_record(_request: Request, exc: InvalidRecordError) -> JSONResponse:
        # A stage refused what it was asked to emit, and a caller CAN reach this: measured on
        # 15e8198c, block_length_mm at 90000 mm is inside its declared [60000, 250000] and asks
        # for more cross streets than the street-name catalog has local_street names. That
        # refusal names no parameter, which is exactly why its own words have to survive.
        return _problem(422, "invalid_record", str(exc))

    @app.exception_handler(UnregisteredGrammarError)
    async def _unknown_grammar(_request: Request, exc: UnregisteredGrammarError) -> JSONResponse:
        # 422 and not the 404 an unknown id gets. The rule this map follows for 404 is about not
        # being an existence oracle for another tenant's rows; the grammar registry is identical
        # for every caller and holds no workspace's data, so naming a grammar that is not
        # registered leaks nothing. It is also NOT a 500: the id and version came from the body.
        return _problem(422, "unknown_grammar", str(exc))

    @app.exception_handler(GrammarError)
    async def _grammar(_request: Request, exc: GrammarError) -> JSONResponse:
        # The base class last, and it is the reason a future member of this hierarchy cannot go
        # quiet. CatalogError and UnresolvedReferenceError arrive here, which is correct and is
        # the whole point of the split: reviewed data that breaks its own schema is loud and is
        # not the caller's fault, because no request can reach a catalog file. So is
        # InvalidSeedError, for the reason given above, and so is any class added later, which
        # arrives carrying its own words and its own class name instead of an empty 500, so the
        # mapping it deserves can be decided from a real answer rather than guessed.
        return _problem(500, f"grammar_refusal_{type(exc).__name__}", str(exc))

    return app
