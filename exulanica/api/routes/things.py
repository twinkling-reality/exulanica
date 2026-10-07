"""The shipped thing library over HTTP: what it holds, and its bytes by digest.

Read-only and the same for every workspace: the thing kinds, looks, body plans and look containers
this host carries in its tree (:mod:`exulanica.world.thing_library`), read and held to their digests
once, when it starts.

*   ``GET /things/library`` lists every kind with the looks it suggests, every look with its
    container, and the body plans catalog's digest (``exulanica.thing-library/v1``).
*   ``GET /things/library/{content_sha256}`` serves a kind or a look (its canonical bytes, as
    ``application/json``), the body plans catalog (its file) or a look's container (as
    ``model/gltf-binary``), named by the SHA-256 of exactly those bytes, so the address is the
    proof of what was read and the answer is cached as immutable. A digest the library does not
    hold is 404 ``unknown_reference``: the request names nothing but a digest, so no request
    reaches a path.

Both need a session (``world.read``), as the style packs do.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse, Response

from exulanica.api.dependencies import CurrentSession
from exulanica.world.committed_content import DIGEST
from exulanica.world.thing_library import thing_library

router = APIRouter(prefix="/things", tags=["things"])

_LIST_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


@router.get(
    "/library",
    summary="The shipped thing library: every kind, look and look container, by digest.",
)
def thing_library_listing(_session: CurrentSession) -> Any:
    return JSONResponse(content=thing_library().listing(), headers=_LIST_HEADERS)


@router.get(
    "/library/{content_sha256}",
    summary="One thing kind, look, the body plans catalog or a look's container, by its SHA-256.",
    responses={200: {"content": {"application/json": {}, "model/gltf-binary": {}}}},
)
def thing_library_content(
    content_sha256: Annotated[str, Path(pattern=f"^{DIGEST.pattern}$")],
    _session: CurrentSession,
) -> Any:
    item = thing_library().content.get(content_sha256)
    if item is None:
        return JSONResponse(
            status_code=404,
            content={"code": "unknown_reference", "detail": "no such thing library content"},
            headers=_LIST_HEADERS,
        )
    # The digest names these exact bytes, so the address never names other ones: immutable.
    return Response(
        content=item.data,
        media_type=item.media_type,
        headers={
            "ETag": f'"{content_sha256}"',
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
