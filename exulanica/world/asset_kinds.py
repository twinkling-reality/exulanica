"""What a reviewed asset is for, stated once, and whether a person may place it as an object.

``world_reviewed_asset`` holds every reviewed container a catalog publishes. The generated marker
meshes in :mod:`exulanica.world.assets` are objects a person places in a world version. The
character catalog's bodies, worn parts and material packs are components: the character renderer
composes them into people and fetches each one by key. Both are served by the same authenticated
registry, so the registry row has to say which it is. Each row stores the kind its publisher
declared, and this module is the one place that says what a kind permits.

**Placeability is declared, never inferred.** A publisher names a kind: migration 0042's markers
are objects by migration 0101, and :func:`exulanica.world.asset_import.import_reviewed_asset`
requires one. Nothing defaults a kind, nothing reads one from a key or a title, and only a kind
this registry marks placeable is listed for placement or accepted when a placement names it. A list
of character keys to hide would say nothing about the next catalog that publishes here.

**The schema restates the kinds.** ``world_reviewed_asset_kind_check`` lists every kind below, and
``tests/test_reviewed_asset_placeability.py`` holds the two equal on the live schema. Adding a kind
is an entry here and a migration that restates the check.

What it does not decide is what an existing object keeps. A version that already holds an object
whose asset is not placeable keeps it, readable, drawable and editable; only placing that asset
again is refused, by :class:`exulanica.world.errors.AssetNotPlaceable`.

Pure: no connection and no SQL.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

__all__ = [
    "ASSET_KINDS",
    "PLACEABLE_KINDS",
    "AssetKind",
    "AssetKindDeclaration",
    "UnknownAssetKind",
    "asset_kind",
]


class AssetKind(StrEnum):
    """The kinds a reviewed asset row may declare."""

    OBJECT = "object"
    COMPONENT = "component"


@dataclass(frozen=True, slots=True)
class AssetKindDeclaration:
    """What one kind permits."""

    kind: AssetKind
    #: Whether a person may place an asset of this kind in a world version as an authored object.
    placeable: bool
    #: What an asset of this kind is, completing "it is ..." in a refusal that names one.
    summary: str


#: Every kind, with what it permits. The one statement of which kinds are placeable.
ASSET_KINDS: Final[Mapping[AssetKind, AssetKindDeclaration]] = MappingProxyType(
    {
        AssetKind.OBJECT: AssetKindDeclaration(
            AssetKind.OBJECT,
            placeable=True,
            summary="reviewed geometry a person places in a world version as an authored object",
        ),
        AssetKind.COMPONENT: AssetKindDeclaration(
            AssetKind.COMPONENT,
            placeable=False,
            summary=(
                "a reviewed container another catalog composes and fetches by key, such as a "
                "character's body, a worn part or a material pack"
            ),
        ),
    }
)

#: The kinds a placement may name, derived from the declarations above.
PLACEABLE_KINDS: Final[frozenset[AssetKind]] = frozenset(
    declaration.kind for declaration in ASSET_KINDS.values() if declaration.placeable
)


class UnknownAssetKind(ValueError):
    """A kind this registry does not declare, refused rather than read as either kind."""


def asset_kind(value: object) -> AssetKindDeclaration:
    """The declaration for a supplied or stored kind, or a refusal that names the value."""
    try:
        kind = AssetKind(value)
    except ValueError:
        raise UnknownAssetKind(f"{value!r} is not a declared reviewed asset kind") from None
    return ASSET_KINDS[kind]
