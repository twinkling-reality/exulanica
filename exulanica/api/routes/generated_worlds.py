"""Worlds the server generates from a reviewed specification, and the baked tiles a generated world
draws.

``GET /worlds/specification`` serves the specification schema, its presets and every refusal as
one document (:func:`exulanica.world.world_recipes.specification_document`). A person, or an open
model drafting on a person's behalf, asks for a preset by its key with values for any of its
adjustable parameters, and nothing else; every request passes one gate
(:func:`~exulanica.world.world_recipes.town_recipe`), which refuses a value the schema does not
offer by name with its key, the value and the range. The server generates the world through the one
generation path ``POST /world-generation/worlds`` also takes, saves it as a ``generated`` world with
its receipt and its saved entry, and queues one bake per tile off the request, then names the
look it is made in: the pack of the host's library the request names, or the library's default
(:mod:`exulanica.world.creation_look`). The two doors differ in authority and metering only: this
one asks for ``world.write`` and is bounded by the world-count policy's ``generated`` limit and the
schema's ranges, which bound the tiles a world covers; the other states any specification and
charges the workspace tile quota.

A generated world's page reads each baked tile through the world it belongs to: the tile's bytes
are served only when the version's own snapshot names it, held to their digest under the final read
check, and never charged (``exulanica/api/permissions.py`` says why).
"""

from __future__ import annotations

import contextlib
import uuid
from typing import Annotated, Any

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
from exulanica.api.routes.world import StylePackBody
from exulanica.api.routes.world_entries import SavedWorldEntryView, _view
from exulanica.api.sayable import sayable
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
from exulanica.world.creation_look import name_creation_look
from exulanica.world.errors import InvalidStructuralData, StyleWriteBusy
from exulanica.world.generated_worlds import generated_tiles
from exulanica.world.models import StylePackBinding
from exulanica.world.saved_entries import InvalidSavedWorldTitle, SavedWorldEntryRepository
from exulanica.world.style_pack_library import style_pack_library
from exulanica.world.world_recipes import (
    SpecificationRefused,
    UnknownWorldRecipe,
    specification_document,
    world_recipes,
)
from exulanica.world.worlds import (
    WorldLimitReached,
    WorldsReadOnly,
    require_world,
    require_world_registration,
)

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

    #: The preset the world is made from.
    recipe: Annotated[str, Field(min_length=1, max_length=100)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    #: Values for any of the preset's adjustable parameters, by the schema's keys; each is held to
    #: its range by the gate, which refuses by name, so they are taken as the JSON sent.
    values: Annotated[dict[str, Any] | None, Field(max_length=64)] = None
    #: The look the world is made in, a pack of the host's library named exactly; absent or null,
    #: the library's default, so every world made here is made wearing a look.
    style_pack: StylePackBody | None = None


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


@router.get("/recipes", summary="The recipes a world can be generated from.")
def recipes(_connection: ReadOnlyConnection, _session: CurrentSession) -> list[WorldRecipeView]:
    """Every recipe this server generates worlds from, in catalog order."""
    return [
        WorldRecipeView(key=recipe.key, label=recipe.label, tiles=len(recipe.tiles))
        for recipe in world_recipes()
    ]


@router.get(
    "/specification",
    summary="What a generated world may be made from: every value, its range, presets, refusals.",
)
def specification(_connection: ReadOnlyConnection, _session: CurrentSession) -> dict[str, Any]:
    """The specification schema this server offers, with its presets and every refusal by name."""
    return specification_document()


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
    """Generate the preset's world with the values asked for, for a new identity, save it and its
    entry, and queue its bakes.

    An unknown preset, a value its schema does not offer (422, naming the key, the value and the
    range), a title that is empty once trimmed (422), a preset its composer does not generate, a
    specification that generates no world from any of its seed candidates, a style pack that is
    not a pack of the host's library at exactly that version and manifest digest (422
    `invalid_style_data`), and a workspace that already holds as many generated worlds as the
    count policy allows are each refused by name, and nothing is written. A deployment whose
    database role cannot register a world is refused 403 `worlds_read_only` before anything is
    generated.

    The world is made, then its look named in its appearance's next version, the entry's resume
    pointer moved with it. When that write is refused as busy, the world stays as made, naming no
    pack, which a page draws in the default look.
    """
    try:
        require_world_registration(connection)
    except WorldsReadOnly as exc:
        return _problem(403, exc.code, str(exc))
    library = style_pack_library()
    named = body.style_pack
    pack = (
        StylePackBinding(
            library.default_pack.pack_id,
            library.default_pack.version,
            library.default_pack.manifest_sha256,
        )
        if named is None
        else StylePackBinding(named.pack_id, named.version, named.manifest_sha256)
    )
    if not library.holds(pack.pack_id, pack.version, pack.manifest_sha256):
        return _problem(
            422,
            "invalid_style_data",
            f"style pack {pack.pack_id} version {pack.version} is not a pack of this host's "
            "library",
        )
    entries = SavedWorldEntryRepository(connection, session.workspace_id, services.store)
    try:
        created = entries.create_generated(
            title=body.title,
            recipe_key=body.recipe,
            created_by=session.actor,
            values=body.values,
        )
    except UnknownWorldRecipe as exc:
        return _problem(404, exc.code, str(exc))
    except InvalidSavedWorldTitle as exc:
        # The code PUT /world-entries/{entry_id} answers the same title with.
        return _problem(422, "invalid_saved_world_entry", str(exc))
    except SpecificationRefused as exc:
        # The client's own value is said back, so only as JSON and UTF-8 can carry it.
        return JSONResponse(status_code=422, content=sayable(exc.document()))
    except (GeneratedWorldRefused, UnknownWorldComposer, WorldLimitReached) as exc:
        return _problem(409, exc.code, str(exc))
    # Refused as busy, the world stays as made, naming no pack: a page draws it in the default.
    with contextlib.suppress(StyleWriteBusy):
        created = name_creation_look(entries, created, pack, session.actor)
    return _view(created, societies_of_things=services.societies_of_things)


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
