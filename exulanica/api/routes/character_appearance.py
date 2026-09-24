"""Authenticated version-scoped appearance; this is not an account-global profile API.

Integration hook: optionally provide Services.character_appearance = CharacterAppearanceRuntime
and include this router. Source authorization is host-owned and mandatory.
``app.state.society_input_authorizer`` is the authority for current synthetic society inputs.

Every operation names the world its version belongs to (``world_id``, required). A workspace
holds several worlds, a saved starter world among them, and appearance history is kept per world
version, so a caller that left the world out would read or write another world's history.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field, StrictInt

from exulanica.api.dependencies import CurrentSession, ScopedConnection, get_services
from exulanica.api.world_scope import WorldId
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
from exulanica.world.character_appearance_repository import CharacterAppearanceRepository
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.society import UnavailableSocietyInput


@dataclass(frozen=True)
class CharacterAppearanceRuntime:
    families: tuple[CharacterFamily, ...]
    authorize_family: Callable[[psycopg.Connection, Session, CharacterFamily], bool]
    store: ContentAddressedStore | None = None
    #: The character catalog that catalog-derived families compose their looks from.
    catalog: Mapping[str, Any] | None = None


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
