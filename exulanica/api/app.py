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
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from exulanica.api.authorisation import TokenNotAccepted
from exulanica.api.body_limit import BodyLimit, BodyTooLarge
from exulanica.api.routes import (
    companion,
    environment_sources,
    evidence,
    formation,
    geometry,
    graph,
    health,
    identity,
    intake,
    interaction,
    operations,
    person_consent,
    personal_admission,
    reconstruction_admission,
    scene_segments,
    selection,
    world,
    world_read,
    world_write,
)
from exulanica.api.services import Services, build_services
from exulanica.db.migrate import verify_schema
from exulanica.db.roles import assert_runtime_role
from exulanica.deletion.restore import verify_restore
from exulanica.errors import (
    BlobNotFoundError,
    EpistemicViolation,
    IntegrityError,
    TombstonedError,
)
from exulanica.identity.subjects import (
    AlreadyIdentified,
    IdentityError,
    NeverSame,
    NotUndoable,
    UnknownSubject,
)
from exulanica.models.errors import BudgetExceededError, ModelError, TruncatedResponseError
from exulanica.selection.validation import RejectionCode, SelectionRejected
from exulanica.world import (
    InvalidInteractionData,
    InvalidInteractionPreviewState,
    InvalidPreviewState,
    InvalidStyleData,
    ProtectedTopologyConflict,
    StaleInteractionPolicy,
    StaleStyleVersion,
    UnavailableAsset,
    UnknownWorldResource,
    WorldNotConfigured,
    seed_reviewed_assets,
)

__all__ = ["create_app"]

#: Which rejection code means which status. See the module docstring for why unknown_reference
#: is a 404 and not_authorised is a 403.
_REJECTION_STATUS: Final[dict[RejectionCode, int]] = {
    RejectionCode.MALFORMED_PLAN: 400,
    RejectionCode.COST_BOUND_EXCEEDED: 400,
    RejectionCode.UNKNOWN_REFERENCE: 404,
    RejectionCode.NOT_AUTHORISED: 403,
}


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    """One response shape for every failure, so a client has one thing to parse."""
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


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
    worker = services.build_derivative_worker()
    app.state.derivative_worker = worker
    if worker is not None:
        worker.start()
    try:
        yield
    finally:
        if worker is not None:
            worker.stop()


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
        summary="A personal world memory model. Every historical claim resolves to its source.",
        version="0.1.0",
        lifespan=_lifespan,
    )
    app.state.services = services or build_services()
    app.state.verify_schema_at_boot = verify
    # Pure ASGI and outermost, so it runs before routing and before any body is read.
    app.add_middleware(BodyLimit)

    app.include_router(health.router)
    app.include_router(graph.router)
    app.include_router(geometry.router)
    app.include_router(geometry.scene_router)
    app.include_router(scene_segments.router)
    app.include_router(selection.router)
    app.include_router(companion.router)
    app.include_router(environment_sources.router)
    app.include_router(identity.router)
    app.include_router(evidence.router)
    app.include_router(formation.router)
    app.include_router(intake.router)
    app.include_router(operations.router)
    app.include_router(person_consent.router)
    app.include_router(personal_admission.router)
    app.include_router(reconstruction_admission.router)
    app.include_router(world.router)
    app.include_router(interaction.router)
    app.include_router(world_read.router)
    app.include_router(world_write.router)

    @app.exception_handler(BodyTooLarge)
    async def _too_large(_request: Request, exc: BodyTooLarge) -> JSONResponse:
        # Raised out of the wrapped `receive` while the body was still arriving, which is the
        # only place a request that declared no length can be stopped before it is all on disk.
        return _problem(413, "body_too_large", exc.detail)

    @app.exception_handler(TokenNotAccepted)
    async def _unauthenticated(_request: Request, exc: TokenNotAccepted) -> JSONResponse:
        return _problem(401, "unauthenticated", str(exc))

    @app.exception_handler(SelectionRejected)
    async def _rejected(_request: Request, exc: SelectionRejected) -> JSONResponse:
        return _problem(_REJECTION_STATUS[exc.code], str(exc.code), exc.detail)

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
        return _problem(422, "epistemic_violation", str(exc))

    @app.exception_handler(TombstonedError)
    async def _tombstoned(_request: Request, exc: TombstonedError) -> JSONResponse:
        return _problem(410, "tombstoned", str(exc))

    @app.exception_handler(BlobNotFoundError)
    async def _missing(_request: Request, _exc: BlobNotFoundError) -> JSONResponse:
        return _problem(404, "unknown_reference", "no such evidence")

    @app.exception_handler(IntegrityError)
    async def _integrity(_request: Request, exc: IntegrityError) -> JSONResponse:
        # Deliberately loud and deliberately not a 404. Stored bytes that do not hash to the key
        # they are stored under means a citation has stopped verifying, and serving anything at
        # all here would hide it.
        return _problem(500, "integrity_failure", str(exc))

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
        if isinstance(exc, BudgetExceededError):
            return _problem(429, "budget_exceeded", str(exc))
        if isinstance(exc, TruncatedResponseError):
            return _problem(500, "model_output_truncated", str(exc))
        return _problem(502, "model_refused", str(exc))

    @app.exception_handler(InvalidStyleData)
    async def _invalid_style(_request: Request, exc: InvalidStyleData) -> JSONResponse:
        return _problem(422, "invalid_style_data", str(exc))

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

    @app.exception_handler(ProtectedTopologyConflict)
    async def _protected_topology(
        _request: Request, exc: ProtectedTopologyConflict
    ) -> JSONResponse:
        return _problem(409, "protected_topology_conflict", str(exc))

    @app.exception_handler(UnavailableAsset)
    async def _unavailable_asset(_request: Request, exc: UnavailableAsset) -> JSONResponse:
        return _problem(424, "unavailable_asset", str(exc))

    @app.exception_handler(UnknownWorldResource)
    async def _unknown_world(_request: Request, _exc: UnknownWorldResource) -> JSONResponse:
        return _problem(404, "unknown_reference", "no such world resource")

    @app.exception_handler(InvalidPreviewState)
    async def _preview_state(_request: Request, exc: InvalidPreviewState) -> JSONResponse:
        return _problem(409, "invalid_preview_state", str(exc))

    @app.exception_handler(WorldNotConfigured)
    async def _world_not_configured(_request: Request, exc: WorldNotConfigured) -> JSONResponse:
        return _problem(409, "world_not_configured", str(exc))

    return app
