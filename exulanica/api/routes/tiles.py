"""Baked tiles of a generated city, over HTTP. Two routes, and neither of them bakes.

*   ``GET /tiles?city_seed=<64 hex>[&lod=<int>]`` lists what is stored for one city: each tile's
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

A key nothing stored is 404 ``unknown_reference``, the same answer the permission floor gives a
credential that does not hold ``tiles.materialise``, so neither answer says whether the other one
was the reason. A key whose tile baked twice into different containers is 409 and never bytes. A
row whose bytes are not in the store is 409, because a row is written after its bytes and a
missing file is an operator's problem, not a client's. A workspace past its ceiling, or with no
ceiling declared, is 429 and never retried.

**The caller checks the bytes too.** The response carries the container digest as its ``ETag``; a
runtime must hash what it received and refuse to draw anything whose digest is not that one.
Caching is ``private, no-cache``: the bytes hold nothing personal and are named by their own
digest, so a browser may keep them and revalidate, and a 304 costs nothing.
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
    city_seed: Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")],
    lod: Annotated[int | None, Query(ge=0, le=64)] = None,
) -> JSONResponse:
    try:
        tiles = _repository(request, connection).tiles_of_city(city_seed, lod)
    except (BakedTileError, _Unavailable) as error:
        return _refused(error)
    return JSONResponse(
        status_code=200,
        content={"city_seed": city_seed, "tiles": [tile.document() for tile in tiles]},
        headers=_HEADERS,
    )


@router.get("/{baked_tile_id}/bytes")
def read_tile_bytes(
    baked_tile_id: uuid.UUID,
    request: Request,
    connection: ScopedConnection,
    session: CurrentSession,
) -> Response:
    try:
        served = _repository(request, connection).serve(session.workspace_id, baked_tile_id)
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
