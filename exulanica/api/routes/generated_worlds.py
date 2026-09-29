"""Worlds the server generates from a reviewed recipe, and the baked tiles a generated world draws.

A person asks for a recipe by its key and nothing else (:mod:`exulanica.world.world_recipes`); the
server generates the world through the one generation path ``POST /world-generation/worlds`` also
takes, saves it as a ``generated`` world with its receipt and its saved entry, and queues one bake
per tile off the request. The two doors differ in authority and metering only: this one asks for
``world.write`` and is bounded by the world-count policy's ``generated`` limit and the recipes'
stated tile counts; the other states any specification and charges the workspace tile quota.

A generated world's page reads each baked tile through the world it belongs to: the tile's bytes
are served only when the version's own snapshot names it, held to their digest under the final read
check, and never charged (``exulanica/api/permissions.py`` says why).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.api.routes.world_entries import SavedWorldEntryView, _view
from exulanica.api.services import Services
from exulanica.api.world_scope import WorldId
from exulanica.world.baked_tiles import (
    TILE_MEDIA_TYPE,
    BakedTileError,
    BakedTileFaulted,
    BakedTileRepository,
    TileBytesMissing,
    UnknownBakedTile,
)
from exulanica.world.composers import GeneratedWorldRefused, UnknownWorldComposer
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.generated_worlds import generated_tiles
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.world_recipes import UnknownWorldRecipe, world_recipes
from exulanica.world.worlds import WorldLimitReached, require_world

__all__ = ["router", "tiles_router"]

router = APIRouter(prefix="/worlds", tags=["world"])
tiles_router = APIRouter(prefix="/world", tags=["world"])

#: Named by their own digest and holding nothing personal, so a browser may keep and revalidate.
_HEADERS = {"Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"}


class WorldRecipeView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    #: How many tiles a world of this recipe covers, each baked once.
    tiles: int


class CreateGeneratedWorldBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe: Annotated[str, Field(min_length=1, max_length=100)]
    title: Annotated[str, Field(min_length=1, max_length=200)]


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


@router.get("/recipes", summary="The recipes a world can be generated from.")
def recipes(_connection: ReadOnlyConnection, _session: CurrentSession) -> list[WorldRecipeView]:
    """Every recipe this server generates worlds from, in catalog order."""
    return [
        WorldRecipeView(key=recipe.key, label=recipe.label, tiles=len(recipe.tiles))
        for recipe in world_recipes()
    ]


@router.post(
    "/generated",
    response_model=SavedWorldEntryView,
    status_code=201,
    summary="Generate a world from a recipe and save it as yours.",
    responses={409: {"description": "Refused by name; nothing was written."}},
)
def create_generated_world(
    body: CreateGeneratedWorldBody,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> SavedWorldEntryView | JSONResponse:
    """Generate the recipe's world for a new identity, save it and its entry, and queue its bakes.

    An unknown recipe, a recipe its composer does not generate, a recipe that generates no world
    from any of its seed candidates, and a workspace that already holds as many generated worlds
    as the count policy allows are each refused by name, and nothing is written.
    """
    try:
        created = SavedWorldEntryRepository(
            connection, session.workspace_id, services.store
        ).create_generated(title=body.title, recipe_key=body.recipe, created_by=session.actor)
    except UnknownWorldRecipe as exc:
        return _problem(404, exc.code, str(exc))
    except (GeneratedWorldRefused, UnknownWorldComposer, WorldLimitReached) as exc:
        return _problem(409, exc.code, str(exc))
    return _view(created)


@tiles_router.get(
    "/versions/{version_id}/tiles/{baked_tile_id}/bytes",
    summary="One baked tile of a generated world, for the world that names it.",
)
def read_world_tile_bytes(
    version_id: uuid.UUID,
    baked_tile_id: uuid.UUID,
    request: Request,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> Response:
    """A baked tile's bytes, served only when the version's own snapshot names the tile."""
    require_world(connection, session.workspace_id, world_id)
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select source_snapshot_id from world_alternate_version where workspace_id=%s "
            "and world_id=%s and version_id=%s",
            (session.workspace_id, world_id, version_id),
        ).fetchone()
    if row is None:
        return _problem(404, "unknown_reference", "no such world version")
    try:
        tiles = generated_tiles(
            connection, session.workspace_id, world_id, row["source_snapshot_id"]
        )
    except InvalidStructuralData as exc:
        return _problem(409, "generated_world_unreadable", str(exc))
    if not any(tile.baked_tile_id == baked_tile_id for tile in tiles):
        return _problem(404, "unknown_reference", "this world names no such baked tile")
    store = getattr(get_services(request), "tiles", None)
    if store is None:
        return _problem(503, "tiles_unavailable", "this instance serves no baked tiles")
    try:
        served = BakedTileRepository(connection=connection, store=store).serve_to_its_world(
            baked_tile_id
        )
    except UnknownBakedTile:
        return _problem(404, "unknown_reference", "no such baked tile")
    except BakedTileFaulted as exc:
        return _problem(409, "nondeterminism_detected", str(exc))
    except TileBytesMissing as exc:
        return _problem(409, "bytes_missing", str(exc))
    except BakedTileError:
        raise
    return Response(
        content=served.data,
        media_type=TILE_MEDIA_TYPE,
        headers={
            **_HEADERS,
            "ETag": f'"{served.tile.container_sha256}"',
            "Accept-Ranges": "none",
            "X-Exulanica-Tile-Inputs-Digest": served.tile.tile_inputs_digest,
        },
    )
