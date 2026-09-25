"""The reviewed asset registry: what may be placed, its bytes and the licence they carry.

Read-only. Every asset is a reviewed CC0 container named by content digest, and each answer says
whether its bytes are present in this instance's store, because a client must not offer to place an
asset nothing could draw. The registry is the same for every world, so these routes take no world.

The list answers what a person may place, so it holds only assets whose declared kind is placeable
(:mod:`exulanica.world.asset_kinds`). The one-key reads serve every reviewed asset, because the
character renderer fetches its bodies, worn parts and material packs by key from here, and their
answer says whether the asset is placeable.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response

from exulanica.api.dependencies import ReadOnlyConnection, get_services
from exulanica.api.world_version_document import PlaceableAssetView, placeable_asset_view
from exulanica.evidence.blob import BlobId
from exulanica.world import GLB_MEDIA_TYPE, UnavailableAsset
from exulanica.world.reviewed_catalog import ReviewedCatalog

router = APIRouter(prefix="/world", tags=["world"])


def reviewed_catalog(connection: ReadOnlyConnection) -> ReviewedCatalog:
    return ReviewedCatalog(connection)


ReadCatalog = Annotated[ReviewedCatalog, Depends(reviewed_catalog)]


@router.get(
    "/assets",
    response_model=list[PlaceableAssetView],
    summary="The reviewed assets a person may place as objects, with real byte availability and "
    "what inhabitants do with each.",
)
def reviewed_asset_catalog(catalog: ReadCatalog, request: Request) -> list[PlaceableAssetView]:
    store = get_services(request).store
    return [placeable_asset_view(asset) for asset in catalog.placeable_assets(store)]


@router.get(
    "/assets/{asset_key}",
    response_model=PlaceableAssetView,
    summary="One reviewed asset of any kind, whether it may be placed and whether its bytes exist.",
)
def reviewed_asset(
    asset_key: Annotated[str, Path(max_length=200)],
    catalog: ReadCatalog,
    request: Request,
) -> PlaceableAssetView:
    return placeable_asset_view(catalog.asset(asset_key, get_services(request).store))


@router.get(
    "/assets/{asset_key}/bytes",
    summary="The reviewed geometry itself. Never a citation target and never evidence.",
    responses={200: {"content": {GLB_MEDIA_TYPE: {}}}},
)
def reviewed_asset_bytes(
    asset_key: Annotated[str, Path(max_length=200)],
    catalog: ReadCatalog,
    request: Request,
) -> Response:
    store = get_services(request).store
    asset = catalog.asset(asset_key, store)
    if asset.availability != "available":
        # The same code and the same honesty as `/world/source-media`, reached through the same
        # application handler rather than a second 424 written out here: the row survived and the
        # bytes did not, and nothing substitutes a different mesh for the one that is gone.
        raise UnavailableAsset("the reviewed asset row exists and its bytes do not")
    payload = store.get(BlobId.from_hex(asset.content_sha256))
    return Response(
        content=payload,
        media_type=asset.media_type,
        headers={
            "ETag": f'"{asset.content_sha256}"',
            # NOT the point map's `no-store`, and the difference is the reasoning. That route
            # serves a personal derivative a tombstone has to be able to reach, so a cached copy
            # is a copy deletion cannot clear. A reviewed CC0 mesh is global reviewed data that
            # holds nothing personal, so it is cacheable.
            #
            # Cacheable, but NOT `immutable`. The bytes are immutable under content addressing;
            # this URL is not, because it is keyed by `asset_key` and a migration could point
            # that key at a different digest. `immutable` tells the browser never to revalidate,
            # which would make the ETag below unable to correct it. An hour, and a validator.
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
            "Accept-Ranges": "none",
        },
    )


@router.get(
    "/assets/{asset_key}/licence",
    summary="The licence text the reviewed bytes are published under.",
    responses={200: {"content": {"text/plain": {}}}},
)
def reviewed_asset_licence(
    asset_key: Annotated[str, Path(max_length=200)],
    catalog: ReadCatalog,
    request: Request,
) -> Response:
    store = get_services(request).store
    asset = catalog.asset(asset_key, store)
    licence = BlobId.from_hex(asset.licence_sha256)
    if not store.exists(licence):
        raise UnavailableAsset("the licence text for this asset is not in the store")
    return Response(
        content=store.get(licence),
        media_type="text/plain; charset=utf-8",
        headers={
            "ETag": f'"{asset.licence_sha256}"',
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
            "Accept-Ranges": "none",
        },
    )
