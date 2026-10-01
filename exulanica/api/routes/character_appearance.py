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

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field, StrictInt

from exulanica.api.capabilities import AVAILABLE, Base, Operation, VersionContext, unavailable
from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.api.world_scope import WorldId
from exulanica.canonical import canonical_json
from exulanica.selection.validation import Session
from exulanica.store.base import ContentAddressedStore
from exulanica.world.character_appearance import (
    AppearanceUnavailable,
    CharacterFamily,
    CharacterRecipe,
    CharacterSubject,
    Record,
    StaleAppearance,
)
from exulanica.world.character_appearance_repository import (
    CharacterAppearanceRepository,
    CharacterPreparations,
)
from exulanica.world.character_catalogs import CatalogRegistry
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.society import UnavailableSocietyInput


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
    #: The workspace's prepared bodies, read through the preparation queue.
    preparations: Callable[[psycopg.Connection, Session], CharacterPreparations] | None = None


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


def capability_operations(context: VersionContext) -> list[Operation]:
    """Saving and resetting a character's appearance, as a world's capability read lists them.

    Unavailable, as every appearance write answers (``appearance_unavailable``), where this host
    configured no character runtime or serves no family a look may be made from: a family the
    host registered itself, or one a served catalog publication derives. A subject's own
    dependencies are decided when one is named; the families read lists what a look may be made
    from, and the catalog reads what those families draw with.
    """
    runtime = getattr(context.services, "character_appearance", None)
    state = (
        AVAILABLE
        if runtime is not None and _serves_a_family(runtime, context.connection)
        else unavailable("appearance_unavailable")
    )
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
    ]


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
