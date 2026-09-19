"""Baked tiles of a generated city, over HTTP. Two routes, and neither of them bakes.

*   ``GET /tiles?city_seed=<64 hex>[&lod=<int>]`` lists what is stored for one WORLD: each tile's
    key, coordinate, level of detail, container digest and size, its two triangle digests and its
    state. Metadata only, and no tile quota is spent on it.
*   ``GET /tiles/{baked_tile_id}/bytes`` serves one container. The bytes come from the ``tiles``
    store, are held to the digest the row records, and the row is read again under the 0041 asset
    read lock before they are delivered. The first delivery of a tile to a workspace spends one of
    its migration 0062 tile quota, in the same statement as the ledger row migration 0072 keys on
    ``(workspace, tile)``; delivering the same tile to the same workspace again is free, because
    the ceiling limits how many distinct tiles a workspace materialises, not how often a walk
    reloads one.

Both routes require ``tiles.materialise``. Nothing is granted that permission by default: a
generated world reaches no person's world until the governance decision is accepted in writing, so
only a token whose grant names the permission is served a generated tile.

A key nothing stored is 404 ``unknown_reference``, and so is every key when the caller's grant does
not hold ``tiles.materialise``: the permission floor refuses an id-addressed route as a missing id.
The two are the same status and the same code and not the same bytes, since the floor's refusal is
raised before this route runs and carries its own detail and none of these headers. What the rule
is for still holds: a credential without the permission is told the same thing about every id, so
it cannot learn which ids exist. It can tell that its own grant is short, which it knows already.

A key whose tile baked twice into different containers is 409 and never bytes. A
row whose bytes are not in the store is 409, because a row is written after its bytes and a
missing file is an operator's problem, not a client's. A workspace past its ceiling, or with no
ceiling declared, is 429 and never retried.

**The caller checks the bytes too.** The response carries the container digest as its ``ETag``; a
runtime must hash what it received and refuse to draw anything whose digest is not that one.
Caching is ``private, no-cache``: the bytes hold nothing personal and are named by their own
digest, so a browser may keep them and revalidate.

**THE WIRE SAYS ``city_seed`` AND EVERYTHING BEHIND IT SAYS ``world_seed``, DELIBERATELY.** The
identity of a generated world instance is ``world_seed`` (migration 0081 argues it): a city is one
kind of world, and generic code composing a world out of neighbouring tiles cannot ask a row for
an identity each grammar spells after itself. The column, the repository and this module's own
names moved. The two public spellings did not, because they are a different object with a
different cost: ``web/packages/atlas-react/.../generated-tile/tile-route.ts`` builds
``?city_seed=`` and two web tests assert that literal URL, so renaming the wire is a coordinated
release in a package this change does not touch. The response's own top-level key is a third case
and is kept for the same reason rather than a weaker one: nothing reads it at all, since the
client takes ten keys out of each ``tiles`` entry and never looks at the body's own key, so
renaming it would have been free and half a renamed wire is harder to read than either whole one.

The route was NOT made to accept both spellings. A parameter admitting two names is a gate that
enumerates, and a reader here refuses an unrecognised name rather than widening to admit it.
``tests/test_corridor_tile_route.py`` holds both spellings, so this paragraph is checked rather
than merely written: the wire rename is then a deliberate edit to that test rather than something
a careless change can do by accident.

**A revalidation is answered here, not by the framework.** ``If-None-Match`` naming the tile's
digest (or ``*``) is answered 304 with the same ``ETag`` and no body, and spends no tile of the
quota, because nothing was delivered. Starlette's plain ``Response`` does no conditional handling
of its own, so a route that did not say this would answer 200 with the whole container to every
revalidation; the lane building the loader read this file rather than trusting the header, and
found exactly that.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from exulanica.api.dependencies import CurrentSession, ScopedConnection, get_services
from exulanica.world.baked_tiles import (
    TILE_MEDIA_TYPE,
    BakedTileError,
    BakedTileFaulted,
    BakedTileRepository,
    TileBytesMissing,
    TileQuotaRefused,
    UnknownBakedTile,
)

__all__ = ["router"]

router = APIRouter(prefix="/tiles", tags=["tiles"])
#: Named by their own digest and holding nothing personal, so a browser may keep and revalidate.
_HEADERS = {"Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"}


class _Unavailable(Exception):
    """This deployment was started without a tile store."""


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"code": code, "detail": detail}, headers=_HEADERS
    )


def _refused(error: Exception) -> JSONResponse:
    if isinstance(error, _Unavailable):
        return _problem(503, "tiles_unavailable", "this instance serves no baked tiles")
    if isinstance(error, UnknownBakedTile):
        return _problem(404, "unknown_reference", "no such baked tile")
    if isinstance(error, BakedTileFaulted):
        return _problem(409, "nondeterminism_detected", str(error))
    if isinstance(error, TileBytesMissing):
        return _problem(409, "bytes_missing", str(error))
    if isinstance(error, TileQuotaRefused):
        return _problem(429, "tile_quota_exceeded", str(error))
    raise error


def _repository(request: Request, connection: ScopedConnection) -> BakedTileRepository:
    store = getattr(get_services(request), "tiles", None)
    if store is None:
        raise _Unavailable
    return BakedTileRepository(connection=connection, store=store)


@router.get("")
def list_tiles(
    request: Request,
    connection: ScopedConnection,
    session: CurrentSession,
    # The alias is the wire name and the parameter is the concept. Spelled as an alias rather
    # than as the parameter's own name so the disagreement is visible here, where a reader meets
    # it, instead of being inferred from a name that happens not to have moved.
    world_seed: Annotated[str, Query(alias="city_seed", pattern=r"^[0-9a-f]{64}$")],
    lod: Annotated[int | None, Query(ge=0, le=64)] = None,
) -> JSONResponse:
    try:
        tiles = _repository(request, connection).tiles_of_world(world_seed, lod)
    except (BakedTileError, _Unavailable) as error:
        return _refused(error)
    return JSONResponse(
        status_code=200,
        # Answered under the wire's spelling, which the module docstring argues and
        # `tests/test_corridor_tile_route.py` holds. Nothing reads this key today.
        content={"city_seed": world_seed, "tiles": [tile.document() for tile in tiles]},
        headers=_HEADERS,
    )


def _revalidates(header: str | None, digest: str) -> bool:
    """Whether ``If-None-Match`` names what this tile's bytes are, by RFC 9110's weak comparison."""
    if header is None:
        return False
    for candidate in header.split(","):
        tag = candidate.strip()
        if tag == "*":
            return True
        if tag.startswith("W/"):
            tag = tag[2:]
        if tag.strip('"') == digest:
            return True
    return False


@router.get("/{baked_tile_id}/bytes")
def read_tile_bytes(
    baked_tile_id: uuid.UUID,
    request: Request,
    connection: ScopedConnection,
    session: CurrentSession,
) -> Response:
    try:
        repository = _repository(request, connection)
        tile = repository.servable(baked_tile_id)
        if _revalidates(request.headers.get("if-none-match"), tile.container_sha256):
            # Nothing is delivered, so nothing is charged.
            return Response(
                status_code=304,
                headers={
                    **_HEADERS,
                    "ETag": f'"{tile.container_sha256}"',
                    "X-Exulanica-Tile-Inputs-Digest": tile.tile_inputs_digest,
                },
            )
        served = repository.serve(session.workspace_id, baked_tile_id)
    except (BakedTileError, _Unavailable) as error:
        return _refused(error)
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
