"""A workspace's kept web pictures over HTTP (migration 0215).

A picture a person picked from a picture search and kept for their own world
(:mod:`exulanica.world.kept_web_pictures`), kept apart from their own photographs:

*   ``GET /worlds/web-pictures`` lists the pictures the workspace keeps, newest first: each where it
    came from, what was kept and the answer it was kept with.
*   ``GET /worlds/web-pictures/{picture_id}`` answers one of them.
*   ``GET /worlds/web-pictures/{picture_id}/bytes`` answers its kept bytes, verified against their
    digest, for the workspace's own page; never cached by anything shared.
*   ``DELETE /worlds/web-pictures/{picture_id}`` erases it: its record at once, its bytes by the
    purge. Asked by the person who kept it, or an owner of the workspace.

A picture another workspace keeps answers exactly as one nobody keeps. Nothing here sends a picture
anywhere: no hosted provider model ever receives one (``docs/reference-notes-contract.md``).
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlySessions,
    ScopedConnection,
    get_services,
)
from exulanica.api.routes.references import kept_picture_view
from exulanica.api.routes.thing_store import _owns_workspace
from exulanica.world.kept_web_pictures import KeptPictureRefused, KeptWebPictures

__all__ = ["router"]

router = APIRouter(prefix="/worlds", tags=["world"])

_UNKNOWN: Final = "unknown_web_picture"
_UNKNOWN_DETAIL: Final = "this workspace keeps no such picture"


def _absent() -> JSONResponse:
    return JSONResponse({"code": _UNKNOWN, "detail": _UNKNOWN_DETAIL}, status_code=404)


@router.get("/web-pictures", summary="The pictures this workspace keeps from picture searches.")
def list_web_pictures(sessions: ReadOnlySessions, session: CurrentSession) -> Any:
    with sessions() as connection:
        kept = KeptWebPictures(connection, session.workspace_id, None).list()
    return {"pictures": [kept_picture_view(picture) for picture in kept]}


@router.get("/web-pictures/{picture_id}", summary="One picture this workspace keeps.")
def read_web_picture(
    picture_id: uuid.UUID, sessions: ReadOnlySessions, session: CurrentSession
) -> Any:
    with sessions() as connection:
        kept = KeptWebPictures(connection, session.workspace_id, None).read(picture_id)
    if kept is None:
        return _absent()
    return kept_picture_view(kept)


@router.get(
    "/web-pictures/{picture_id}/bytes",
    summary="The kept bytes of one picture this workspace keeps.",
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}}}},
)
def read_web_picture_bytes(
    picture_id: uuid.UUID, request: Request, sessions: ReadOnlySessions, session: CurrentSession
) -> Any:
    stores = get_services(request).content_stores
    if stores is None:
        return JSONResponse(
            {"code": "web_picture_store_unavailable", "detail": "this server keeps no pictures"},
            status_code=503,
        )
    with sessions() as connection:
        held = KeptWebPictures(
            connection,
            session.workspace_id,
            stores.web_pictures.for_workspace(session.workspace_id),
        ).read_bytes(picture_id)
    if held is None:
        return _absent()
    kept, data = held
    return Response(
        content=data,
        media_type=kept.media_type,
        headers={
            "ETag": f'"{kept.content_sha256}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete(
    "/web-pictures/{picture_id}",
    summary="Erase one picture this workspace keeps.",
    status_code=204,
)
def erase_web_picture(
    picture_id: uuid.UUID, request: Request, connection: ScopedConnection, session: CurrentSession
) -> Response:
    try:
        KeptWebPictures(connection, session.workspace_id, None).erase(
            picture_id, erased_by=session.actor, by_owner=_owns_workspace(request, session)
        )
    except KeptPictureRefused as refused:
        if refused.code == "picture_unknown":
            return _absent()
        status = 403 if refused.code == "picture_not_yours" else 409
        return JSONResponse({"code": refused.code, "detail": refused.detail}, status_code=status)
    return Response(status_code=204)
