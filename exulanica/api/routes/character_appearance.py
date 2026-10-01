"""Authenticated version-scoped appearance; this is not an account-global profile API.

Integration hook: optionally provide Services.character_appearance = CharacterAppearanceRuntime
and include this router. Source authorization is host-owned and mandatory.
``app.state.society_input_authorizer`` is the authority for current synthetic society inputs.

Every operation names the world its version belongs to (``world_id``, required). A workspace
holds several worlds, a saved starter world among them, and appearance history is kept per world
version, so a caller that left the world out would read or write another world's history.

The character catalogs the host publishes are read here too (``/world/character-catalogs``), with
no world: every workspace is served the same publications, and a publication is addressed by the
SHA-256 of its canonical document, so its bytes are the proof of what was read.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Final, Literal

import psycopg
from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field, StrictInt

from exulanica.api.capabilities import (
    AVAILABLE,
    Base,
    Effect,
    Operation,
    VersionContext,
    unavailable,
    unknown,
)
from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.api.world_scope import WorldId
from exulanica.canonical import canonical_json
from exulanica.errors import IntegrityError
from exulanica.selection.validation import Session
from exulanica.store.base import ContentAddressedStore
from exulanica.world.character_appearance import (
    AppearanceUnavailable,
    CharacterFamily,
    CharacterRecipe,
    CharacterSubject,
    PreparationNotApplicable,
    Record,
    RepresentationNotPrepared,
    StaleAppearance,
)
from exulanica.world.character_appearance_repository import (
    CharacterAppearanceRepository,
    PreparationPlan,
)
from exulanica.world.character_body_preparations import (
    PREPARATION_VIEW_PROFILE,
    QueuedCharacterPreparations,
    preparation_view,
    representation_id,
    requested_inputs,
)
from exulanica.world.character_catalogs import CatalogRegistry
from exulanica.world.character_parametric import PREPARER_ID, PREPARER_VERSION
from exulanica.world.character_preparation import CharacterBodyPreparer, PreparerUnavailable
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.workspace_preparations import (
    PreparationBlocked,
    PreparationError,
    PreparationFinished,
    PreparationNotReady,
    PreparedBytesMissing,
    UnknownPreparation,
    WorkspaceAssetBusy,
    WorkspaceAssetQuotaExceeded,
    WorkspaceAssetsReadOnly,
)


@dataclass(frozen=True)
class CharacterAppearanceRuntime:
    families: tuple[CharacterFamily, ...]
    authorize_family: Callable[[psycopg.Connection, Session, CharacterFamily], bool]
    store: ContentAddressedStore | None = None
    #: The character catalog that catalog-derived families compose their looks from.
    catalog: Mapping[str, Any] | None = None
    #: The catalogs this host publishes (migration 0131). Families they derive are served while a
    #: publication that derives them is not withdrawn.
    catalogs: CatalogRegistry | None = None
    #: The workspace's prepared bodies, read and requested through the preparation queue.
    preparations: Callable[[psycopg.Connection, Session], QueuedCharacterPreparations] | None = None
    #: This process's view of the body preparer: whether its pinned inputs verify here, and the
    #: identity a request pins. The queue's worker runs its own instance.
    preparer: CharacterBodyPreparer | None = None


class SaveBody(Record):
    base_revision: Annotated[StrictInt, Field(ge=0, lt=2**63 - 1)]
    recipe: CharacterRecipe


class ResetBody(Record):
    base_revision: Annotated[StrictInt, Field(ge=0, lt=2**63 - 1)]
    restore_revision: Annotated[StrictInt, Field(ge=1, lt=2**63 - 1)] | None = None


router = APIRouter(prefix="/world", tags=["character-appearance"])
_PATH = "/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance"
_HEADERS = {"Cache-Control": "private, no-store"}
Kind = Literal["avatar", "synthetic-inhabitant"]


def _repo(
    request: Request, connection: psycopg.Connection, session: Session, world_id: str
) -> CharacterAppearanceRepository:
    runtime = getattr(get_services(request), "character_appearance", None)
    if runtime is None:
        raise AppearanceUnavailable("character appearance runtime is not configured")
    authorizer = getattr(request.app.state, "society_input_authorizer", None)
    return CharacterAppearanceRepository(
        connection,
        session.workspace_id,
        session.actor,
        families=runtime.families,
        authorize_family=lambda family: runtime.authorize_family(connection, session, family),
        society_input_authorizer=None
        if authorizer is None
        else lambda doc: authorizer(connection, session, doc),
        store=runtime.store,
        catalog=runtime.catalog,
        world_id=world_id,
        served=None if runtime.catalogs is None else runtime.catalogs.served(connection),
        preparations=None
        if runtime.preparations is None
        else runtime.preparations(connection, session),
    )


def _call(
    request: Request,
    connection: psycopg.Connection,
    session: Session,
    world_id: str,
    kind: Kind,
    subject_id: uuid.UUID,
    society_id: uuid.UUID | None,
    operation: Callable,
) -> Any:
    from fastapi.encoders import jsonable_encoder

    try:
        subject = CharacterSubject(kind=kind, subject_id=subject_id, society_id=society_id)
        result = operation(_repo(request, connection, session, world_id), subject)
        return JSONResponse(content=jsonable_encoder(result), headers=_HEADERS)
    except UnknownWorldResource:
        status, code, detail = 404, "unknown_reference", "no such authorized character appearance"
    except StaleAppearance:
        status, code, detail = 409, "stale_appearance", "appearance changed; reload before saving"
    except RepresentationNotPrepared:
        status, code, detail = (
            409,
            "representation_not_prepared",
            "the body this look names is still being prepared; save it once it is prepared",
        )
    except PreparationNotApplicable as exc:
        status, code, detail = 422, "preparation_not_applicable", str(exc)
    except (AppearanceUnavailable, UnavailableSocietyInput):
        status, code, detail = (
            424,
            "appearance_unavailable",
            "current character or family dependencies are unavailable",
        )
    except ValueError:
        status, code, detail = (
            422,
            "invalid_appearance",
            "appearance does not match the declared family or revision",
        )
    return JSONResponse(
        status_code=status, content={"code": code, "detail": detail}, headers=_HEADERS
    )


@router.get(_PATH)
def read(
    version_id: uuid.UUID,
    subject_kind: Kind,
    subject_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    society_id: uuid.UUID | None = None,
) -> Any:
    return _call(
        request,
        connection,
        session,
        world_id,
        subject_kind,
        subject_id,
        society_id,
        lambda repo, subject: repo.read(version_id, subject),
    )


@router.put(_PATH)
def save(
    version_id: uuid.UUID,
    subject_kind: Kind,
    subject_id: uuid.UUID,
    body: SaveBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    society_id: uuid.UUID | None = None,
) -> Any:
    return _call(
        request,
        connection,
        session,
        world_id,
        subject_kind,
        subject_id,
        society_id,
        lambda repo, subject: repo.save(
            version_id, subject, body.recipe, base_revision=body.base_revision
        ),
    )


@router.post(_PATH + "/reset")
def reset(
    version_id: uuid.UUID,
    subject_kind: Kind,
    subject_id: uuid.UUID,
    body: ResetBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    society_id: uuid.UUID | None = None,
) -> Any:
    return _call(
        request,
        connection,
        session,
        world_id,
        subject_kind,
        subject_id,
        society_id,
        lambda repo, subject: repo.reset(
            version_id,
            subject,
            base_revision=body.base_revision,
            restore_revision=body.restore_revision,
        ),
    )


@router.get(_PATH + "/history")
def history(
    version_id: uuid.UUID,
    subject_kind: Kind,
    subject_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    society_id: uuid.UUID | None = None,
    before_revision: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Any:
    return _call(
        request,
        connection,
        session,
        world_id,
        subject_kind,
        subject_id,
        society_id,
        lambda repo, subject: repo.history(
            version_id, subject, before_revision=before_revision, limit=limit
        ),
    )


@router.get(_PATH + "/families")
def families(
    version_id: uuid.UUID,
    subject_kind: Kind,
    subject_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    society_id: uuid.UUID | None = None,
) -> Any:
    return _call(
        request,
        connection,
        session,
        world_id,
        subject_kind,
        subject_id,
        society_id,
        lambda repo, subject: repo.available_families(version_id, subject),
    )


#: Whether a requested body is prepared depends on a preparation process this server cannot see,
#: as for a workspace asset (``exulanica/api/routes/workspace_assets.py``): the installation facts
#: state it (their ``preparation`` component), and where a process has none the effect's state is
#: not known.
_PREPARATION_EFFECT: Final = Effect("preparation", unknown(), component="preparation")


def capability_operations(context: VersionContext) -> list[Operation]:
    """Saving and resetting a character's appearance, and requesting and cancelling a prepared
    body, as a world's capability read lists them.

    Unavailable, as every appearance write answers (``appearance_unavailable``), where this host
    configured no character runtime or serves no family a look may be made from: a family the
    host registered itself, or one a served catalog publication derives. A subject's own
    dependencies are decided when one is named; the families read lists what a look may be made
    from, and the catalog reads what those families draw with.

    A body is requested for a recipe over a served parametric family. Beyond the appearance's own
    state, a request is unavailable as it answers (``preparer_unavailable``) where this host has no
    preparation queue, no preparer, or no inputs that verify for any parametric family it serves;
    whether the named subject and family take a prepared body is decided when they are named. A
    request needs the installation's ``preparation`` component, which a capability read takes from
    the installation's facts. A cancel acts on one preparation, which the request's answer names,
    and needs the queue.
    """
    runtime = getattr(context.services, "character_appearance", None)
    state = (
        AVAILABLE
        if runtime is not None and _serves_a_family(runtime, context.connection)
        else unavailable("appearance_unavailable")
    )
    if state != AVAILABLE:
        requesting = state
    elif not _prepares_a_body(runtime, context.connection):
        requesting = unavailable("preparer_unavailable")
    else:
        requesting = AVAILABLE
    if runtime is None:
        cancelling = unavailable("appearance_unavailable")
    elif getattr(runtime, "preparations", None) is None:
        cancelling = unavailable("preparer_unavailable")
    else:
        cancelling = AVAILABLE
    base = (Base("base_revision", read, "revision"),)
    return [
        Operation(
            endpoint=save,
            availability=state,
            subject="character",
            bind=context.bind,
            base=base,
            options=(families, character_catalogs),
        ),
        Operation(
            endpoint=reset,
            availability=state,
            subject="character",
            bind=context.bind,
            base=base,
            options=(history,),
        ),
        Operation(
            endpoint=request_preparation,
            availability=requesting,
            subject="character",
            bind=context.bind,
            options=(families,),
            effects=(_PREPARATION_EFFECT,),
            needs=("preparation",),
        ),
        Operation(
            endpoint=cancel_preparation,
            availability=cancelling,
            subject="preparation",
            bind=context.bind,
        ),
    ]


def _prepares_a_body(runtime: object, connection: psycopg.Connection) -> bool:
    """Whether a body can be queued here: a queue, a preparer, and inputs that verify for a
    parametric family this host serves. The identity is the one a request pins, which the
    preparer reuses for a few minutes, so a capability read does not hash the inputs each time."""
    preparer = getattr(runtime, "preparer", None)
    catalogs = getattr(runtime, "catalogs", None)
    if getattr(runtime, "preparations", None) is None or preparer is None or catalogs is None:
        return False
    for publication in catalogs.served(connection).publications:
        if publication.kind != "parametric-body":
            continue
        for family in publication.families:
            with contextlib.suppress(PreparerUnavailable):
                preparer.identity_sha256(family.family_id)
                return True
    return False


def _serves_a_family(runtime: object, connection: psycopg.Connection) -> bool:
    """Whether a look can be made here at all: a registered family or a served publication."""
    if getattr(runtime, "families", ()):
        return True
    catalogs = getattr(runtime, "catalogs", None)
    return catalogs is not None and bool(catalogs.served(connection).families)


_CATALOG_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"code": code, "detail": detail}, headers=_CATALOG_HEADERS
    )


@router.get(
    "/character-catalogs",
    summary="The character catalogs this host serves: each publication's identity and state.",
)
def character_catalogs(connection: ReadOnlyConnection, request: Request) -> Any:
    from fastapi.encoders import jsonable_encoder

    runtime = getattr(get_services(request), "character_appearance", None)
    if runtime is None or runtime.catalogs is None:
        return _problem(424, "appearance_unavailable", "no character catalogs are served here")
    served = runtime.catalogs.served(connection)
    return JSONResponse(
        content=jsonable_encoder(
            {"profile": "exulanica.character-catalog-list/v1", "publications": served.listing()}
        ),
        headers=_CATALOG_HEADERS,
    )


@router.get(
    "/character-catalogs/{catalog_sha256}",
    summary="One published character catalog, as the canonical document its digest names.",
    responses={200: {"content": {"application/json": {}}}},
)
def character_catalog(
    catalog_sha256: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")],
    connection: ReadOnlyConnection,
    request: Request,
) -> Any:
    runtime = getattr(get_services(request), "character_appearance", None)
    if runtime is None or runtime.catalogs is None:
        return _problem(424, "appearance_unavailable", "no character catalogs are served here")
    publication, withdrawn = runtime.catalogs.document(connection, catalog_sha256)
    if publication is None and not withdrawn:
        return _problem(404, "unknown_reference", "no such character catalog")
    if withdrawn:
        return _problem(410, "withdrawn", "this character catalog was withdrawn")
    # The digest names these exact bytes, so the address never names other ones: immutable.
    return Response(
        content=canonical_json(publication.document),
        media_type="application/json",
        headers={
            "ETag": f'"{catalog_sha256}"',
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


# -- prepared bodies ------------------------------------------------------------------------------
#
# A parametric family's reviewed bodies are published with it. Any other recipe over it is fitted
# per workspace in the one preparation queue (exulanica.world.workspace_preparations), by the
# character body preparer; these routes request, read and cancel such a preparation and deliver
# its bytes, scoped to a subject the caller may act for. A body is for a person's own avatar.

_PREPARATIONS = _PATH + "/preparations"


class PreparationBody(Record):
    recipe: CharacterRecipe


class _NoPreparations(Exception):
    """This instance prepares no bodies: no queue, or no verified preparer."""


def _preparations(
    request: Request, connection: psycopg.Connection, session: Session
) -> QueuedCharacterPreparations:
    runtime = getattr(get_services(request), "character_appearance", None)
    if runtime is None or runtime.preparations is None:
        raise _NoPreparations
    return runtime.preparations(connection, session)


def _refused(error: Exception) -> JSONResponse:
    """A refusal of a preparation operation, as the character routes answer it."""
    headers = dict(_HEADERS)
    if isinstance(error, _NoPreparations | PreparerUnavailable):
        status, code, detail = 503, "preparer_unavailable", "bodies are not prepared here"
    elif isinstance(error, UnknownWorldResource | UnknownPreparation):
        status, code, detail = 404, "unknown_reference", "no such character preparation"
    elif isinstance(error, PreparationBlocked):
        status, code, detail = 410, "withdrawn", "this preparation is no longer current"
    elif isinstance(error, PreparationNotReady):
        status, code, detail = 409, "preparation_not_ready", "this body is not prepared"
    elif isinstance(error, PreparedBytesMissing):
        status, code, detail = 409, "prepared_bytes_missing", "request this body again"
    elif isinstance(error, IntegrityError):
        status, code, detail = (
            409,
            "prepared_bytes_corrupt",
            "the stored body does not hash to the digest recorded for it",
        )
    elif isinstance(error, PreparationFinished):
        status, code, detail = 409, "preparation_finished", "this body is already prepared"
    elif isinstance(error, WorkspaceAssetQuotaExceeded):
        status, code, detail = 429, "workspace_asset_quota_exceeded", str(error)
    elif isinstance(error, WorkspaceAssetsReadOnly):
        status, code, detail = 403, "workspace_assets_read_only", "preparations are read-only here"
    elif isinstance(error, WorkspaceAssetBusy):
        status, code, detail = 503, "retry", "a delivery was in progress; ask again"
        headers["Retry-After"] = "1"
    elif isinstance(error, PreparationNotApplicable):
        status, code, detail = 422, "preparation_not_applicable", str(error)
    elif isinstance(error, AppearanceUnavailable | UnavailableSocietyInput):
        status, code, detail = (
            424,
            "appearance_unavailable",
            "current character or family dependencies are unavailable",
        )
    elif isinstance(error, ValueError):
        status, code, detail = (
            422,
            "invalid_appearance",
            "appearance does not match the declared family or revision",
        )
    else:
        raise error
    return JSONResponse(
        status_code=status, content={"code": code, "detail": detail}, headers=headers
    )


_REFUSALS = (
    _NoPreparations,
    IntegrityError,
    PreparerUnavailable,
    UnknownWorldResource,
    PreparationError,
    AppearanceUnavailable,
    UnavailableSocietyInput,
    ValueError,
)


def _reviewed_view(plan: PreparationPlan) -> dict[str, Any]:
    """The answer when the family's publication already reviews a body for these values."""
    body = next(
        r for r in plan.family_document["representations"] if r["representationId"] == plan.reviewed
    )
    return {
        "profile": PREPARATION_VIEW_PROFILE,
        "preparation_id": None,
        "state": "prepared",
        "representation_id": plan.reviewed,
        "family_id": plan.family.family_id,
        "family_sha256": plan.family.sha256,
        "values": body["values"],
        "catalog_sha256": plan.publication.catalog_sha256,
        "attempts": 0,
        "requested_at": None,
        "prepared_at": None,
        "output": {
            "sha256": body["asset"]["contentSha256"],
            "byte_size": body["asset"]["byteSize"],
            "present": None,
        },
        "descriptor": body["descriptor"],
        "failure": None,
    }


def _subject(kind: Kind, subject_id: uuid.UUID, society_id: uuid.UUID | None) -> CharacterSubject:
    return CharacterSubject(kind=kind, subject_id=subject_id, society_id=society_id)


@router.post(
    _PREPARATIONS,
    status_code=202,
    summary="Prepare a body for a recipe over a parametric family, or answer the one prepared.",
)
def request_preparation(
    version_id: uuid.UUID,
    subject_kind: Kind,
    subject_id: uuid.UUID,
    body: PreparationBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    society_id: uuid.UUID | None = None,
) -> Any:
    from fastapi.encoders import jsonable_encoder

    try:
        subject = _subject(subject_kind, subject_id, society_id)
        plan = _repo(request, connection, session, world_id).preparation_plan(
            version_id, subject, body.recipe
        )
        if plan.reviewed is not None:
            return JSONResponse(content=jsonable_encoder(_reviewed_view(plan)), headers=_HEADERS)
        runtime = get_services(request).character_appearance
        if runtime is None or runtime.preparer is None:
            raise _NoPreparations
        identity = runtime.preparer.identity_sha256(plan.family.family_id)
        bodies = _preparations(request, connection, session)
        record = bodies.queue.request(
            input_kind="character_recipe",
            preparer_id=PREPARER_ID,
            preparer_version=PREPARER_VERSION,
            parameters={
                "family_id": plan.family.family_id,
                "family_sha256": plan.family.sha256,
                "values": dict(body.recipe.parameters),
                "seed": body.recipe.seed,
            },
            inputs=requested_inputs(
                plan.publication.catalog_sha256, identity, plan.family_document
            ),
        )
        present = None if record.output_sha256 is None else bodies.queue.output_present(record)
    except _REFUSALS as error:
        return _refused(error)
    return JSONResponse(
        status_code=202 if record.state in ("requested", "running") else 200,
        content=jsonable_encoder(preparation_view(record, output_present=present)),
        headers=_HEADERS,
    )


def _character_record(
    request: Request,
    connection: psycopg.Connection,
    session: Session,
    world_id: str,
    version_id: uuid.UUID,
    subject: CharacterSubject,
    preparation_id: uuid.UUID,
) -> tuple[QueuedCharacterPreparations, Any]:
    """The subject checked, then one character preparation of this workspace, else 404."""
    _repo(request, connection, session, world_id).authorize(version_id, subject)
    bodies = _preparations(request, connection, session)
    record = bodies.record(representation_id(preparation_id))
    if record is None:
        raise UnknownPreparation(f"no character preparation {preparation_id} here")
    return bodies, record


@router.get(
    _PREPARATIONS + "/{preparation_id}",
    summary="One character body preparation: its state, its body once prepared, or its failure.",
)
def read_preparation(
    version_id: uuid.UUID,
    subject_kind: Kind,
    subject_id: uuid.UUID,
    preparation_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    society_id: uuid.UUID | None = None,
) -> Any:
    from fastapi.encoders import jsonable_encoder

    try:
        bodies, record = _character_record(
            request,
            connection,
            session,
            world_id,
            version_id,
            _subject(subject_kind, subject_id, society_id),
            preparation_id,
        )
        present = None if record.output_sha256 is None else bodies.queue.output_present(record)
    except _REFUSALS as error:
        return _refused(error)
    return JSONResponse(
        content=jsonable_encoder(preparation_view(record, output_present=present)),
        headers=_HEADERS,
    )


@router.post(
    _PREPARATIONS + "/{preparation_id}/cancel",
    summary="Stop a character body preparation that has not finished.",
)
def cancel_preparation(
    version_id: uuid.UUID,
    subject_kind: Kind,
    subject_id: uuid.UUID,
    preparation_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    society_id: uuid.UUID | None = None,
) -> Any:
    from fastapi.encoders import jsonable_encoder

    try:
        bodies, _record = _character_record(
            request,
            connection,
            session,
            world_id,
            version_id,
            _subject(subject_kind, subject_id, society_id),
            preparation_id,
        )
        record = bodies.queue.cancel(preparation_id)
    except _REFUSALS as error:
        return _refused(error)
    return JSONResponse(
        content=jsonable_encoder(preparation_view(record, output_present=None)),
        headers=_HEADERS,
    )


@router.get(
    _PREPARATIONS + "/{preparation_id}/bytes",
    summary="A prepared character body's bytes, while the family it was prepared over is served.",
    responses={200: {"content": {"model/gltf-binary": {}}}},
)
def read_preparation_bytes(
    version_id: uuid.UUID,
    subject_kind: Kind,
    subject_id: uuid.UUID,
    preparation_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    society_id: uuid.UUID | None = None,
) -> Any:
    try:
        bodies, record = _character_record(
            request,
            connection,
            session,
            world_id,
            version_id,
            _subject(subject_kind, subject_id, society_id),
            preparation_id,
        )
        runtime = get_services(request).character_appearance
        registry = runtime.catalogs if runtime is not None else None
        if registry is None:
            raise AppearanceUnavailable("no character catalogs are served here")
        catalog, family = (
            record.inputs.get("catalog_sha256"),
            record.parameters.get("family_sha256"),
        )
        output = bodies.queue.read_output(
            preparation_id,
            still_current=lambda current: registry.served(current).derives(
                str(catalog), str(family)
            ),
        )
    except _REFUSALS as error:
        return _refused(error)
    # The output digest names these exact bytes and the queue never rewrites them: immutable.
    return Response(
        content=output.data,
        media_type=output.media_type,
        headers={
            "ETag": f'"{output.content_sha256}"',
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
