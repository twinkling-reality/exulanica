"""A workspace's own material recipes and bakes, over HTTP.

Routes validate and delegate: every rule is in :mod:`exulanica.world.material_recipes` and in
migration 0066. What this module decides is the shape of an answer.

*   ``GET /materials/makers`` and ``GET /materials/library`` describe what may be varied: every
    published maker's manifest, and every published set with its recipe. A client builds a
    person's recipe from these, and the server checks it again whatever the client did.
*   ``POST /materials/recipes`` stores a recipe a person authored and the published maker
    accepts, or answers 422 with every reason. A client can only state ``authored``: a proposal or
    a photo-derived recipe carries the model that made it, and only the service that records that
    model may write one, so either origin is a 422 here.
*   ``POST /materials/recipes/{recipe_id}/withdraw`` hides a recipe and its bake at once.
*   ``POST /materials/recipes/{recipe_id}/bake`` queues a bake and answers 202. The bake is made
    by the bake worker, never in this request, and a request past the workspace's quota is 429.
*   ``GET /materials/recipes/{recipe_id}/bake/bytes`` serves the container after the 0041 final
    check, marked private and never cached, with the licence that says it stays in the workspace.

A recipe that never existed here is 404; one that was withdrawn or reached by a deletion is 410,
so another workspace's recipe and an invented id answer alike. A deployment whose database role
may not write material tables (the judge deployment) answers every write 403, whatever the id.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.api.dependencies import CurrentSession, ScopedConnection, get_services
from exulanica.materials import thaw
from exulanica.selection.validation import Session
from exulanica.world.material_recipes import (
    BakeBytesMissing,
    BakeNotReady,
    BakeQuotaExceeded,
    BakeRecord,
    InvalidRecipe,
    MaterialBusy,
    MaterialError,
    MaterialReadOnly,
    MaterialRepository,
    MaterialRuntime,
    MaterialWithdrawn,
    RecipeRecord,
    UnknownMaterial,
)

__all__ = ["router"]

router = APIRouter(prefix="/materials", tags=["materials"])
_PRIVATE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PublishedSet(_Body):
    set_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9.-]*$", max_length=200)]
    version: Annotated[StrictInt, Field(ge=1, lt=2**31)]


class RecipeBody(_Body):
    recipe: dict[str, Any]
    #: What a client may say about where a recipe came from: that a person authored it.
    origin: Literal["authored"] = "authored"
    based_on: PublishedSet | None = None
    label: Annotated[str, Field(max_length=400)] | None = None


class _Unavailable(Exception):
    """This instance was started without the published material catalog."""


def _runtime(request: Request) -> MaterialRuntime:
    runtime = getattr(get_services(request), "materials", None)
    if runtime is None:
        raise _Unavailable
    return runtime


def _repository(
    request: Request, connection: psycopg.Connection, session: Session
) -> MaterialRepository:
    runtime = _runtime(request)
    return MaterialRepository(
        connection,
        session.workspace_id,
        session.actor,
        catalog=runtime.catalog,
        stores=runtime.stores,
    )


def _problem(status: int, code: str, detail: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"code": code, "detail": detail, **extra}, headers=_PRIVATE
    )


def _refused(error: Exception) -> JSONResponse:
    if isinstance(error, _Unavailable):
        return _problem(
            503, "materials_unavailable", "this instance has no published material catalog"
        )
    if isinstance(error, InvalidRecipe):
        return _problem(
            422,
            "invalid_recipe",
            "the published maker refuses this recipe",
            problems=list(error.problems),
        )
    if isinstance(error, UnknownMaterial):
        return _problem(404, "unknown_reference", "no such recipe")
    if isinstance(error, MaterialWithdrawn):
        return _problem(410, "withdrawn", "this recipe was withdrawn or deleted")
    if isinstance(error, BakeNotReady):
        return _problem(409, "bake_not_ready", "this recipe has no finished bake")
    if isinstance(error, BakeBytesMissing):
        return _problem(
            409, "bake_bytes_missing", "the bake's bytes are missing; request the bake again"
        )
    if isinstance(error, BakeQuotaExceeded):
        return _problem(429, "bake_quota_exceeded", str(error))
    if isinstance(error, MaterialReadOnly):
        return _problem(
            403, "materials_read_only", "this deployment keeps material recipes read-only"
        )
    if isinstance(error, MaterialBusy):
        response = _problem(503, "retry", "a delivery was in progress; ask again")
        response.headers["Retry-After"] = "1"
        return response
    raise error


def _recipe_view(record: RecipeRecord, bake: BakeRecord | None = None) -> dict[str, Any]:
    return {
        "recipe_id": str(record.recipe_id),
        "origin": record.origin,
        "maker": {
            "id": record.maker_id,
            "version": record.maker_version,
            "sha256": record.maker_sha256,
        },
        "recipe_sha256": record.recipe_sha256,
        "recipe": thaw(record.recipe),
        "based_on": None
        if record.based_on is None
        else {"set_id": record.based_on[0], "version": record.based_on[1]},
        "label": record.label,
        "created_at": record.created_at.isoformat(),
        "bake": None if bake is None else _bake_view(bake),
    }


def _bake_view(bake: BakeRecord) -> dict[str, Any]:
    return {
        "bake_id": str(bake.bake_id),
        "set_id": bake.set_id,
        "state": bake.state,
        "attempts": bake.attempts,
        "requested_at": bake.requested_at.isoformat(),
        "content_sha256": bake.content_sha256,
        "byte_size": bake.byte_size,
        "licence_id": bake.licence_id,
        "receipt": None if bake.receipt is None else thaw(bake.receipt),
        "baked_at": None if bake.baked_at is None else bake.baked_at.isoformat(),
        "failure": None
        if bake.failure_class is None
        else {"class": bake.failure_class, "message": bake.failure_message},
    }


def _json(content: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status, content=content, headers=_PRIVATE)


@router.get("/makers")
def makers(request: Request, session: CurrentSession) -> JSONResponse:
    del session
    try:
        catalog = _runtime(request).catalog
    except _Unavailable as error:
        return _refused(error)
    return _json(
        {
            "makers": [
                {
                    "maker_id": maker.maker_id,
                    "version": maker.version,
                    "sha256": maker.sha256,
                    "manifest": thaw(maker.manifest),
                }
                for _, maker in sorted(catalog.makers.items())
            ]
        }
    )


@router.get("/library")
def library(request: Request, session: CurrentSession) -> JSONResponse:
    del session
    try:
        catalog = _runtime(request).catalog
    except _Unavailable as error:
        return _refused(error)
    return _json(
        {
            "sets": [
                {
                    "set_id": record.set_id,
                    "version": record.version,
                    "title": record.title,
                    "summary": record.summary,
                    "licence_id": record.licence_id,
                    "content_sha256": record.content_sha256,
                    "maker": {"id": record.maker.maker_id, "version": record.maker.version},
                    "recipe_sha256": record.recipe_sha256,
                    "recipe": thaw(record.recipe),
                }
                for record in catalog.sets.values()
            ]
        }
    )


@router.get("/recipes")
def list_recipes(
    request: Request, connection: ScopedConnection, session: CurrentSession
) -> JSONResponse:
    try:
        repository = _repository(request, connection, session)
        views = [_recipe_view(record) for record in repository.recipes()]
    except (MaterialError, _Unavailable) as error:
        return _refused(error)
    return _json({"recipes": views})


@router.post("/recipes")
def create_recipe(
    body: RecipeBody, request: Request, connection: ScopedConnection, session: CurrentSession
) -> JSONResponse:
    based_on = None if body.based_on is None else (body.based_on.set_id, body.based_on.version)
    try:
        record = _repository(request, connection, session).create_recipe(
            body.recipe, origin=body.origin, based_on=based_on, label=body.label
        )
    except (MaterialError, _Unavailable) as error:
        return _refused(error)
    return _json(_recipe_view(record), status=201)


@router.get("/recipes/{recipe_id}")
def read_recipe(
    recipe_id: uuid.UUID, request: Request, connection: ScopedConnection, session: CurrentSession
) -> JSONResponse:
    try:
        repository = _repository(request, connection, session)
        record = repository.recipe(recipe_id)
        bake = repository.bake(recipe_id)
    except (MaterialError, _Unavailable) as error:
        return _refused(error)
    return _json(_recipe_view(record, bake))


@router.post("/recipes/{recipe_id}/withdraw")
def withdraw_recipe(
    recipe_id: uuid.UUID, request: Request, connection: ScopedConnection, session: CurrentSession
) -> JSONResponse:
    try:
        _repository(request, connection, session).withdraw_recipe(recipe_id)
    except (MaterialError, _Unavailable) as error:
        return _refused(error)
    return _json({"recipe_id": str(recipe_id), "withdrawn": True})


@router.post("/recipes/{recipe_id}/bake")
def request_bake(
    recipe_id: uuid.UUID, request: Request, connection: ScopedConnection, session: CurrentSession
) -> JSONResponse:
    try:
        bake = _repository(request, connection, session).request_bake(recipe_id)
    except (MaterialError, _Unavailable) as error:
        return _refused(error)
    return _json(_bake_view(bake), status=200 if bake.state == "baked" else 202)


@router.get("/recipes/{recipe_id}/bake")
def read_bake(
    recipe_id: uuid.UUID, request: Request, connection: ScopedConnection, session: CurrentSession
) -> JSONResponse:
    try:
        bake = _repository(request, connection, session).bake(recipe_id)
    except (MaterialError, _Unavailable) as error:
        return _refused(error)
    if bake is None:
        return _problem(404, "no_bake", "nobody has asked for this recipe to be baked")
    return _json(_bake_view(bake))


@router.get("/recipes/{recipe_id}/bake/bytes")
def read_bake_bytes(
    recipe_id: uuid.UUID, request: Request, connection: ScopedConnection, session: CurrentSession
) -> Response:
    try:
        authorized = _repository(request, connection, session).read_bake(recipe_id)
    except (MaterialError, _Unavailable) as error:
        return _refused(error)
    return Response(
        content=authorized.data,
        media_type=authorized.media_type,
        headers={
            **_PRIVATE,
            "ETag": f'"{authorized.content_sha256}"',
            "Accept-Ranges": "none",
            "X-Exulanica-Set-Id": authorized.set_id,
            "X-Exulanica-Licence": authorized.licence_id,
        },
    )
