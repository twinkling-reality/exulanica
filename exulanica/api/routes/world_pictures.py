"""The pictures of a world's History: a picture of each moment and a portrait of each look (0223).

``PUT /world/versions/{version_id}/history/moments/{moment_id}/picture?world_id=&recipe=`` keeps the
picture a page drew of a moment of that version by a framing recipe; the body is the picture itself,
typed by ``Content-Type``. ``PUT /world/portraits?world_id=&look_sha256=&recipe=`` keeps a look's
portrait in the world. Each name keeps its first picture: another answers 409 ``picture_kept`` with
the one kept, so a page that raced another shows that one. Refused by name as a saved world's
picture is: another type (415), a larger one (413), one with anything but the picture in it or of
another size (422), one of a world that holds a photograph (422), a recipe that is not a name and a
version (422); a world full of pictures (409 ``pictures_full``).

``GET /world/portraits?world_id=&looks=&recipe=`` answers ``exulanica.world-look-portraits/v1``:
for each look asked, its kept portrait by the recipe, or null.
``GET /world/pictures/{sha256}?world_id=``
answers a kept History picture's bytes by its digest: the address names the bytes, so a browser
keeps them as long as it likes.

They need ``world.write``, as History's other reads: only a person who may change the world draws
its pictures and reads its History. Another workspace's world, a version the world does not hold and
an id nobody registered are one refusal (404 ``unknown_reference``).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Final

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, ScopedConnection
from exulanica.api.world_scope import WorldId
from exulanica.world.moment_pictures import (
    PORTRAIT_MAX_BYTES,
    MomentPictureRepository,
    PictureKept,
)
from exulanica.world.saved_entry_pictures import (
    PICTURE_MAX_BYTES,
    PICTURE_MEDIA_TYPES,
    PictureRefused,
)

__all__ = ["BODY_LIMITS", "LOOKS_ASKED_AT_MOST", "PORTRAITS_PROFILE", "router"]

router = APIRouter(prefix="/world", tags=["world"])

PORTRAITS_PROFILE: Final = "exulanica.world-look-portraits/v1"
#: The most looks one portraits read asks: a History shows a few dozen people at most.
LOOKS_ASKED_AT_MOST: Final = 64
#: The recipes a read assumes where none is named: the page's own today.
DEFAULT_PORTRAIT_RECIPE: Final = "portrait/v1"

_MOMENT_PICTURE: Final = "/world/versions/{version_id}/history/moments/{moment_id}/picture"
_PORTRAIT: Final = "/world/portraits"
BODY_LIMITS: Final = (
    ("PUT", _MOMENT_PICTURE, PICTURE_MAX_BYTES + 1024),
    ("PUT", _PORTRAIT, PORTRAIT_MAX_BYTES + 1024),
)

_PICTURE_BODY: Final[dict[str, Any]] = {
    "requestBody": {
        "required": True,
        "content": {
            media_type: {"schema": {"type": "string", "contentMediaType": media_type}}
            for media_type in PICTURE_MEDIA_TYPES
        },
    }
}

_Recipe = Annotated[str, Query(min_length=4, max_length=56)]
_Digest = Annotated[str, Path(pattern="^[0-9a-f]{64}$")]


def _refused(exc: PictureRefused) -> JSONResponse:
    content: dict[str, Any] = {"code": exc.code, "detail": str(exc)}
    if isinstance(exc, PictureKept):
        content["kept"] = exc.kept.view()
    return JSONResponse(status_code=exc.status, content=content)


def _media_type(request: Request) -> str:
    return request.headers.get("content-type", "").split(";")[0].strip().lower()


@router.put(_MOMENT_PICTURE.removeprefix("/world"), openapi_extra=_PICTURE_BODY)
async def put_moment_picture(
    version_id: Annotated[uuid.UUID, Path()],
    moment_id: Annotated[uuid.UUID, Path()],
    request: Request,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
    recipe: _Recipe,
) -> Any:
    """Keep the picture a page drew of a moment of this version, unless one is kept already."""
    data = await request.body()
    try:
        kept = MomentPictureRepository(connection, session.workspace_id).keep_moment(
            world_id, version_id, moment_id, recipe, data, _media_type(request), session.actor
        )
    except PictureRefused as exc:
        return _refused(exc)
    return kept.view()


@router.put(_PORTRAIT.removeprefix("/world"), openapi_extra=_PICTURE_BODY)
async def put_portrait(
    request: Request,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
    look_sha256: Annotated[str, Query(pattern="^[0-9a-f]{64}$")],
    recipe: _Recipe,
) -> Any:
    """Keep a look's portrait in the world, unless one is kept already. A look is named by its
    digest, not owned: any look may have a portrait in a world the caller holds."""
    data = await request.body()
    try:
        kept = MomentPictureRepository(connection, session.workspace_id).keep_portrait(
            world_id, look_sha256, recipe, data, _media_type(request), session.actor
        )
    except PictureRefused as exc:
        return _refused(exc)
    return kept.view()


@router.get("/portraits")
def portraits(
    connection: ReadOnlyConnection,
    session: CurrentSession,
    world_id: WorldId,
    looks: Annotated[str, Query(min_length=64, max_length=65 * LOOKS_ASKED_AT_MOST)],
    recipe: _Recipe = DEFAULT_PORTRAIT_RECIPE,
) -> Any:
    """For each look asked (comma separated digests), its kept portrait by the recipe, or null."""
    asked = [one for one in looks.split(",") if one]
    if (
        not asked
        or len(asked) > LOOKS_ASKED_AT_MOST
        or any(len(one) != 64 or any(c not in "0123456789abcdef" for c in one) for one in asked)
    ):
        return JSONResponse(
            status_code=422,
            content={
                "code": "portraits_asked",
                "detail": f"looks are 1 to {LOOKS_ASKED_AT_MOST} sha256 digests, comma separated",
            },
        )
    repository = MomentPictureRepository(connection, session.workspace_id)
    repository.held_world(world_id)
    kept = repository.portraits(world_id, asked, recipe)
    return {
        "profile": PORTRAITS_PROFILE,
        "recipe": recipe,
        "portraits": {look: (kept[look].view() if look in kept else None) for look in asked},
    }


@router.get("/pictures/{sha256}")
def picture(
    sha256: _Digest,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> Response:
    """A kept History picture's bytes in the world, by its digest."""
    found = MomentPictureRepository(connection, session.workspace_id).picture(world_id, sha256)
    if found is None:
        return JSONResponse(
            status_code=404,
            content={"code": "picture_not_found", "detail": "no picture with this digest"},
        )
    media_type, data = found
    return Response(
        content=data,
        media_type=media_type,
        headers={"ETag": f'"{sha256}"', "Cache-Control": "private, max-age=31536000, immutable"},
    )
