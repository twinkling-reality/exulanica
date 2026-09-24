"""The reviewed asset and behaviour registries, which are the same for every world.

``world_reviewed_asset`` and ``world_object_behaviour_registry`` are registry tables
(:data:`exulanica.db.registries.REGISTRY_TABLES`): migrations fill them, no workspace owns them and
no world holds them. Reading them takes a connection and nothing else, so a route that serves them
takes no world, and an authored-object repository asks this module rather than restating the
queries.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

import psycopg

from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore
from exulanica.world.asset_kinds import ASSET_KINDS, PLACEABLE_KINDS, asset_kind
from exulanica.world.errors import AssetNotPlaceable, UnknownWorldResource

__all__ = ["ReviewedAssetRow", "ReviewedCatalog"]

#: Every column a reviewed asset read selects, in one place for the list, one-key and placeable
#: reads alike.
_ASSET_COLUMNS: Final = (
    "asset_key,title,summary,media_type,content_sha256,byte_size,licence_id,licence_sha256,kind"
)


class ReviewedAssetRow:
    """One reviewed asset as the registry holds it, plus whether its bytes are actually present."""

    __slots__ = (
        "asset_key",
        "availability",
        "byte_size",
        "content_sha256",
        "kind",
        "licence_id",
        "licence_sha256",
        "media_type",
        "summary",
        "title",
    )

    def __init__(self, row: Mapping[str, Any], availability: str) -> None:
        self.asset_key = row["asset_key"]
        self.title = row["title"]
        self.summary = row["summary"]
        self.media_type = row["media_type"]
        self.content_sha256 = row["content_sha256"]
        self.byte_size = row["byte_size"]
        self.licence_id = row["licence_id"]
        self.licence_sha256 = row["licence_sha256"]
        self.kind = asset_kind(row["kind"]).kind
        self.availability = availability

    @property
    def placeable(self) -> bool:
        """Whether a person may place this asset as an object, as its declared kind says."""
        return ASSET_KINDS[self.kind].placeable

    def require_placeable(self) -> None:
        """Refuse placing this asset, by name, unless its kind is placeable.

        The one rule every placement goes through: ``add_object`` and composition preview and
        apply. Existing objects are never re-checked against it, so a version that already
        holds a component keeps reading, drawing and editing as it did.
        """
        if not self.placeable:
            raise AssetNotPlaceable(
                f"{self.asset_key} is not an object a person can place: it is "
                f"{ASSET_KINDS[self.kind].summary}"
            )


class ReviewedCatalog:
    """The reviewed registries, read through any connection."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def assets(self, store: ContentAddressedStore | None = None) -> tuple[ReviewedAssetRow, ...]:
        """The reviewed catalog, every kind. With a store, each row also reports its bytes.

        Without a store the availability is ``unknown`` rather than an optimistic ``available``.
        Saying "present" about bytes nobody looked for is the failure the source-media contract
        exists to prevent, and it would be the same failure here.
        """
        rows = self.connection.execute(
            f"select {_ASSET_COLUMNS} from world_reviewed_asset order by asset_key"
        ).fetchall()
        return tuple(ReviewedAssetRow(row, _availability(row, store)) for row in rows)

    def placeable_assets(
        self, store: ContentAddressedStore | None = None
    ) -> tuple[ReviewedAssetRow, ...]:
        """The reviewed assets a person may place as objects: those of a placeable kind."""
        rows = self.connection.execute(
            f"select {_ASSET_COLUMNS} from world_reviewed_asset where kind = any(%s) "
            "order by asset_key",
            (sorted(kind.value for kind in PLACEABLE_KINDS),),
        ).fetchall()
        return tuple(ReviewedAssetRow(row, _availability(row, store)) for row in rows)

    def asset(self, asset_key: str, store: ContentAddressedStore | None = None) -> ReviewedAssetRow:
        row = self.connection.execute(
            f"select {_ASSET_COLUMNS} from world_reviewed_asset where asset_key=%s",
            (asset_key,),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such reviewed asset")
        return ReviewedAssetRow(row, _availability(row, store))

    def behaviours(self) -> dict[tuple[str, int], Mapping[str, Any]]:
        """Every reviewed behaviour, keyed by behaviour key and version, with its parameters."""
        rows = self.connection.execute(
            "select behaviour_key,behaviour_version,parameters from world_object_behaviour_registry"
        ).fetchall()
        return {(r["behaviour_key"], r["behaviour_version"]): r["parameters"] for r in rows}


def _availability(row: Mapping[str, Any], store: ContentAddressedStore | None) -> str:
    if store is None:
        return "unknown"
    return (
        "available" if store.exists(BlobId.from_hex(row["content_sha256"])) else "unavailable_asset"
    )
