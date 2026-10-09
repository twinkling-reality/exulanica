"""The committed style pack library over HTTP: what it holds, and its bytes by digest.

Read-only and the same for every workspace: the packs this host carries in its tree
(:mod:`exulanica.world.style_pack_library`), read and held to their digests once, when it starts.

*   ``GET /world/style-packs`` lists every pack: its id, version and manifest digest, its title,
    description and tags, its origin, its licence with the attribution it requires, and its authors,
    each with ``source`` ``library``; then, under ``workspace_packs``, this workspace's own versions
    that may be worn now, each with ``source`` ``workspace``
    (:mod:`exulanica.api.routes.workspace_style_packs`), whose bytes are served by their own routes.
*   ``GET /world/style-packs/{content_sha256}`` serves one pack's manifest (its canonical bytes,
    as ``application/json``) or one file a manifest lists (as the media type the manifest states),
    named by the SHA-256 of exactly those bytes, so the address is the proof of what was read and
    the answer is cached as immutable. A digest the library does not hold is 404
    ``unknown_reference``: the request names nothing but a digest, so no request reaches a path.

Both need a session (``world.read``), as the character catalogs do.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response

from exulanica.api.dependencies import CurrentSession, ScopedSessions, get_services
from exulanica.api.routes.workspace_style_packs import workspace_listing
from exulanica.world.committed_content import DIGEST
from exulanica.world.style_pack_library import style_pack_library

router = APIRouter(prefix="/world", tags=["world"])

_LIST_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


@router.get(
    "/style-packs",
    summary="The committed style packs this host serves: each pack's identity, licence and origin.",
)
def style_packs(request: Request, sessions: ScopedSessions, session: CurrentSession) -> Any:
    listing = style_pack_library().listing()
    listing["packs"] = [{**pack, "source": "library"} for pack in listing["packs"]]
    listing["workspace_packs"] = []
    # An instance started without workspace style pack namespaces lists the library alone and
    # opens no connection for it.
    if getattr(get_services(request), "workspace_style_packs", None) is not None:
        with sessions() as connection:
            listing["workspace_packs"] = workspace_listing(request, connection, session)
    return JSONResponse(content=listing, headers=_LIST_HEADERS)


@router.get(
    "/style-packs/{content_sha256}",
    summary="One style pack manifest or listed file, as the bytes its SHA-256 names.",
    responses={200: {"content": {"application/json": {}, "model/gltf-binary": {}}}},
)
def style_pack_content(
    content_sha256: Annotated[str, Path(pattern=f"^{DIGEST.pattern}$")],
    _session: CurrentSession,
) -> Any:
    item = style_pack_library().content.get(content_sha256)
    if item is None:
        return JSONResponse(
            status_code=404,
            content={"code": "unknown_reference", "detail": "no such style pack content"},
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
