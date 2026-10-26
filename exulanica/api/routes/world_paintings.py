"""A world's paintings: its own views painted by an open model from its words (0226).

``GET /world/paintings?world_id=`` answers ``exulanica.world-paintings/v1``: the world's
paintings, newest first, each with the digest that fetches it, its view and camera, the words it
was painted from, its painter (each model's repository, revision and licence), the share of the
structure's edges it kept, and its label, invented appearance.
``GET /world/paintings/{sha256}?world_id=`` answers a painting's bytes by its digest: the address
names the bytes, so a browser keeps them as long as it likes.

They need ``world.read``: a painting is how the world looks, for everyone who may see the world.
Nothing here writes one; the operator's painting run keeps them
(:mod:`exulanica.world.world_paintings`), and a showcase world's copy keeps its catalog's card
paintings (``POST /worlds/showcase/{showcase}``). Another workspace's world and an id nobody
registered are one refusal (404 ``unknown_reference``).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse, Response

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection
from exulanica.api.world_scope import WorldId
from exulanica.world.world_paintings import LABEL, PAINTINGS_PROFILE, WorldPaintingRepository

__all__ = ["router"]

router = APIRouter(prefix="/world", tags=["world"])

_Digest = Annotated[str, Path(pattern="^[0-9a-f]{64}$")]


@router.get("/paintings")
def paintings(connection: ReadOnlyConnection, session: CurrentSession, world_id: WorldId) -> Any:
    """The world's paintings, newest first, without their bytes."""
    kept = WorldPaintingRepository(connection, session.workspace_id).paintings(world_id)
    return {
        "profile": PAINTINGS_PROFILE,
        "world_id": world_id,
        "label": LABEL,
        "paintings": [painting.view_record() for painting in kept],
    }


@router.get("/paintings/{sha256}")
def painting(
    sha256: _Digest,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> Response:
    """A kept painting's bytes in the world, by its digest."""
    found = WorldPaintingRepository(connection, session.workspace_id).picture(world_id, sha256)
    if found is None:
        return JSONResponse(
            status_code=404,
            content={"code": "painting_not_found", "detail": "no painting with this digest"},
        )
    media_type, data = found
    return Response(
        content=data,
        media_type=media_type,
        headers={"ETag": f'"{sha256}"', "Cache-Control": "private, max-age=31536000, immutable"},
    )
