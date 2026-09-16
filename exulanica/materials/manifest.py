"""The published texture manifest: one reader and one rule for every module that reads it.

``assets/textures/manifest.json`` indexes the library ``web/packages/loom-texture`` publishes. Its
shape was fixed with the grammar lane before the first set was published:
``{"profile": "exulanica.texture-manifest/v1", "sets": [...]}``, with at least one set, ``sets``
sorted by ``set_id`` and each id once. :func:`read_texture_manifest` is the only reader. It reads
the bytes as every material object is read, strictly and in canonical form, holds every entry to
the rule below, and hands the sets out frozen, by id. :mod:`exulanica.world.texture_assets` then
checks each container against its entry and :mod:`exulanica.grammar.textures` keeps the pin a
catalog entry carries; neither states a rule of its own that could drift from this one.

An entry has exactly nine fields, and:

- ``set_id`` matches :data:`SET_ID_PATTERN`, the rule an authored-world asset key follows;
- ``version`` and ``byte_size`` are positive integers;
- ``content_sha256`` and ``licence_sha256`` are 64 lowercase hex characters;
- ``resolution`` is a positive ``width`` and ``height``, and ``extent_mm`` a positive
  whole-millimetre ``u`` and ``v``;
- ``channels`` is :data:`CONTAINER_LAYOUT`, the packing every container declares, map for map;
- ``licence_id`` is :data:`PUBLISHED_LICENCE_ID`. The manifest is the published library, so a set
  under any other licence cannot be listed in it, and that includes a workspace's private bakes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from exulanica.materials.objects import (
    SAFE_INTEGER,
    MaterialObjectError,
    identical,
    is_sha256,
    read_document,
)

__all__ = [
    "CONTAINER_LAYOUT",
    "MANIFEST_NAME",
    "MANIFEST_PROFILE",
    "PUBLISHED_LICENCE_ID",
    "SET_ID",
    "SET_ID_PATTERN",
    "ManifestEntry",
    "TextureMap",
    "read_texture_manifest",
]

MANIFEST_NAME: Final = "manifest.json"
MANIFEST_PROFILE: Final = "exulanica.texture-manifest/v1"
#: A texture set id: a stable name, never a version or a digest. Identical, character for
#: character, to ``asset_key`` in migration 0042 and ``set_id`` in migration 0065.
SET_ID_PATTERN: Final = "^[a-z][a-z0-9.-]*$"
#: The same rule, compiled for ``fullmatch``, which needs no anchors and refuses a trailing newline.
SET_ID: Final = re.compile(SET_ID_PATTERN.removeprefix("^").removesuffix("$"))
#: The one licence a published set is under.
PUBLISHED_LICENCE_ID: Final = "CC0-1.0"

_MANIFEST_KEYS: Final = frozenset({"profile", "sets"})
_ENTRY_KEYS: Final = frozenset(
    {
        "set_id",
        "version",
        "content_sha256",
        "byte_size",
        "resolution",
        "channels",
        "extent_mm",
        "licence_id",
        "licence_sha256",
    }
)


@dataclass(frozen=True, slots=True)
class TextureMap:
    """One map in a set, and exactly how its channels are packed."""

    name: str
    components: int
    holds: tuple[str, ...]
    srgb: bool

    def as_channel(self) -> dict[str, Any]:
        return {
            "map": self.name,
            "components": self.components,
            "holds": list(self.holds),
            "srgb": self.srgb,
        }


#: The packing every container declares, in the order its maps are stored.
CONTAINER_LAYOUT: Final = (
    TextureMap("base_color", 3, ("red", "green", "blue"), True),
    TextureMap("normal", 3, ("normal_x", "normal_y", "normal_z"), False),
    TextureMap("orm", 3, ("occlusion", "roughness", "metalness"), False),
    TextureMap("height", 1, ("height",), False),
)
_CHANNELS: Final = tuple(texture_map.as_channel() for texture_map in CONTAINER_LAYOUT)


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One published set, as the manifest lists it."""

    set_id: str
    version: int
    content_sha256: str
    byte_size: int
    width: int
    height: int
    extent_u_mm: int
    extent_v_mm: int
    licence_id: str
    licence_sha256: str

    def as_entry(self) -> dict[str, Any]:
        """The entry exactly as the manifest holds it."""
        return {
            "set_id": self.set_id,
            "version": self.version,
            "content_sha256": self.content_sha256,
            "byte_size": self.byte_size,
            "resolution": {"width": self.width, "height": self.height},
            "channels": [texture_map.as_channel() for texture_map in CONTAINER_LAYOUT],
            "extent_mm": {"u": self.extent_u_mm, "v": self.extent_v_mm},
            "licence_id": self.licence_id,
            "licence_sha256": self.licence_sha256,
        }


def _positive(value: object) -> bool:
    """An ``int`` that is not a ``bool``, from 1 to the largest integer the baker can write."""
    return type(value) is int and 1 <= value <= SAFE_INTEGER


def _pair(value: object, first: str, second: str) -> tuple[int, int] | None:
    if (
        isinstance(value, dict)
        and set(value) == {first, second}
        and _positive(value[first])
        and _positive(value[second])
    ):
        return value[first], value[second]
    return None


def _entry(entry: object, where: str) -> ManifestEntry:
    if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
        raise MaterialObjectError(f"{where} has keys other than exactly {sorted(_ENTRY_KEYS)}")
    set_id = entry["set_id"]
    if type(set_id) is not str or SET_ID.fullmatch(set_id) is None:
        raise MaterialObjectError(f"{where}: set_id {set_id!r} is not a texture set id")
    if not _positive(entry["version"]) or not _positive(entry["byte_size"]):
        raise MaterialObjectError(f"{where}: version and byte_size are positive integers")
    for field in ("content_sha256", "licence_sha256"):
        if not is_sha256(entry[field]):
            raise MaterialObjectError(f"{where}: {field} is 64 lowercase hex characters")
    resolution = _pair(entry["resolution"], "width", "height")
    if resolution is None:
        raise MaterialObjectError(f"{where}: resolution is a positive width and height")
    extent = _pair(entry["extent_mm"], "u", "v")
    if extent is None:
        raise MaterialObjectError(f"{where}: extent_mm is a positive whole-millimetre u and v")
    if not identical(entry["channels"], _CHANNELS):
        raise MaterialObjectError(f"{where}: channels are not the container layout, map for map")
    if entry["licence_id"] != PUBLISHED_LICENCE_ID:
        raise MaterialObjectError(
            f"{where}: licence_id is {PUBLISHED_LICENCE_ID}; the manifest lists published sets only"
        )
    return ManifestEntry(
        set_id=set_id,
        version=entry["version"],
        content_sha256=entry["content_sha256"],
        byte_size=entry["byte_size"],
        width=resolution[0],
        height=resolution[1],
        extent_u_mm=extent[0],
        extent_v_mm=extent[1],
        licence_id=entry["licence_id"],
        licence_sha256=entry["licence_sha256"],
    )


def read_texture_manifest(raw: bytes, where: str = MANIFEST_NAME) -> Mapping[str, ManifestEntry]:
    """Every set ``raw`` lists, by id and in order, or a :class:`MaterialObjectError` saying why."""
    document = read_document(raw, where)
    if not isinstance(document, dict) or set(document) != _MANIFEST_KEYS:
        raise MaterialObjectError(f"{where} is an object with exactly profile and sets")
    if document["profile"] != MANIFEST_PROFILE:
        raise MaterialObjectError(f"{where}: profile is {MANIFEST_PROFILE!r}")
    entries = document["sets"]
    if not isinstance(entries, list) or not entries:
        raise MaterialObjectError(f"{where}: sets is a non-empty list")
    sets: dict[str, ManifestEntry] = {}
    for index, candidate in enumerate(entries):
        entry = _entry(candidate, f"{where} sets[{index}]")
        if sets and entry.set_id <= next(reversed(sets)):
            raise MaterialObjectError(f"{where}: sets are sorted by set_id, each id once")
        sets[entry.set_id] = entry
    return MappingProxyType(sets)
