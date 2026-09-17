"""The published texture manifest: one reader and one rule for every module that reads it.

``assets/textures/manifest.json`` indexes the library ``web/packages/loom-texture`` publishes. Its
shape was fixed with the grammar lane before the first set was published:
``{"profile": "exulanica.texture-manifest/v1", "sets": [...]}``, with at least one set, ``sets``
sorted by ``set_id`` and each id once. :func:`read_texture_manifest` is the only reader. It reads
the bytes as every material object is read, strictly and in canonical form, holds every entry to
the rule below, and hands the sets out frozen, by id. :mod:`exulanica.world.texture_assets` then
checks each container against its entry and :mod:`exulanica.grammar.textures` keeps the pin a
catalog entry carries; neither states a rule of its own that could drift from this one.

A v1 entry has exactly nine fields, and:

- ``set_id`` matches :data:`SET_ID_PATTERN`, the rule an authored-world asset key follows;
- ``version`` and ``byte_size`` are positive integers;
- ``content_sha256`` and ``licence_sha256`` are 64 lowercase hex characters;
- ``resolution`` is a positive ``width`` and ``height``, and ``extent_mm`` a positive
  whole-millimetre ``u`` and ``v``;
- ``channels`` is :data:`CONTAINER_LAYOUT`, the packing every v1 container declares, map for map;
- ``licence_id`` is :data:`PUBLISHED_LICENCE_ID`. The manifest is the published library, so a set
  under any other licence cannot be listed in it, and that includes a workspace's private bakes.

``exulanica.texture-manifest/v2`` adds two fields to each entry, ``container_profile`` and
``material_class`` (:mod:`exulanica.materials.classes`), and its ``channels`` must be one of the
layouts that pair allows. A v1 container is ``opaque``, and every entry of a v1 manifest is one.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from exulanica.materials.classes import (
    MATERIAL_CLASSES,
    TEXTURE_SET_PROFILE_V1,
    TEXTURE_SET_PROFILES,
    V1_LAYOUT,
    TextureMap,
    allowed_channels,
    class_layout,
)
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
    "MANIFEST_PROFILES",
    "MANIFEST_PROFILE_V2",
    "PUBLISHED_LICENCE_ID",
    "SET_ID",
    "SET_ID_PATTERN",
    "ManifestEntry",
    "TextureMap",
    "read_texture_manifest",
]

MANIFEST_NAME: Final = "manifest.json"
#: The profile of the manifest this repository publishes today.
MANIFEST_PROFILE: Final = "exulanica.texture-manifest/v1"
MANIFEST_PROFILE_V2: Final = "exulanica.texture-manifest/v2"
MANIFEST_PROFILES: Final = (MANIFEST_PROFILE, MANIFEST_PROFILE_V2)
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
_V2_ENTRY_KEYS: Final = _ENTRY_KEYS | {"container_profile", "material_class"}

#: The packing every v1 container declares, in the order its maps are stored.
CONTAINER_LAYOUT: Final = V1_LAYOUT


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
    container_profile: str
    material_class: str
    #: The layout ``channels`` lists, map for map.
    maps: tuple[TextureMap, ...]

    def as_entry(self, profile: str = MANIFEST_PROFILE) -> dict[str, Any]:
        """The entry exactly as a manifest of ``profile`` holds it."""
        entry: dict[str, Any] = {
            "set_id": self.set_id,
            "version": self.version,
            "content_sha256": self.content_sha256,
            "byte_size": self.byte_size,
            "resolution": {"width": self.width, "height": self.height},
            "channels": [texture_map.as_channel() for texture_map in self.maps],
            "extent_mm": {"u": self.extent_u_mm, "v": self.extent_v_mm},
            "licence_id": self.licence_id,
            "licence_sha256": self.licence_sha256,
        }
        if profile != MANIFEST_PROFILE:
            entry["container_profile"] = self.container_profile
            entry["material_class"] = self.material_class
        return entry


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


def _layout_of(
    channels: object, container_profile: str, material_class: str
) -> tuple[TextureMap, ...]:
    """The layout ``channels`` lists, if it is one this profile and class allow."""
    candidates = (
        [V1_LAYOUT]
        if container_profile == TEXTURE_SET_PROFILE_V1
        else [
            class_layout(material_class, kind, normal=normal, height=height)
            for kind in ("procedural", "model")
            for normal in (False, True)
            for height in (False, True)
        ]
    )
    for layout in candidates:
        if identical(channels, [texture_map.as_channel() for texture_map in layout]):
            return layout
    raise LookupError


def _entry(entry: object, where: str, profile: str) -> ManifestEntry:
    keys = _ENTRY_KEYS if profile == MANIFEST_PROFILE else _V2_ENTRY_KEYS
    if not isinstance(entry, dict) or set(entry) != keys:
        raise MaterialObjectError(f"{where} has keys other than exactly {sorted(keys)}")
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
    if entry["licence_id"] != PUBLISHED_LICENCE_ID:
        raise MaterialObjectError(
            f"{where}: licence_id is {PUBLISHED_LICENCE_ID}; the manifest lists published sets only"
        )
    container_profile, material_class = TEXTURE_SET_PROFILE_V1, "opaque"
    if profile != MANIFEST_PROFILE:
        container_profile, material_class = entry["container_profile"], entry["material_class"]
        if container_profile not in TEXTURE_SET_PROFILES:
            raise MaterialObjectError(
                f"{where}: container_profile is one of {', '.join(TEXTURE_SET_PROFILES)}"
            )
        if material_class not in MATERIAL_CLASSES:
            raise MaterialObjectError(
                f"{where}: material_class is one of {', '.join(MATERIAL_CLASSES)}"
            )
        if not allowed_channels(container_profile, material_class):
            raise MaterialObjectError(
                f"{where}: a container of profile {container_profile} is opaque, never "
                f"{material_class}"
            )
    try:
        maps = _layout_of(entry["channels"], container_profile, material_class)
    except LookupError:
        raise MaterialObjectError(
            f"{where}: channels are not a container layout of profile {container_profile} and "
            f"class {material_class}, map for map"
        ) from None
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
        container_profile=container_profile,
        material_class=material_class,
        maps=maps,
    )


def read_texture_manifest(raw: bytes, where: str = MANIFEST_NAME) -> Mapping[str, ManifestEntry]:
    """Every set ``raw`` lists, by id and in order, or a :class:`MaterialObjectError` saying why."""
    document = read_document(raw, where)
    if not isinstance(document, dict) or set(document) != _MANIFEST_KEYS:
        raise MaterialObjectError(f"{where} is an object with exactly profile and sets")
    profile = document["profile"]
    if profile not in MANIFEST_PROFILES:
        raise MaterialObjectError(f"{where}: profile is one of {', '.join(MANIFEST_PROFILES)}")
    entries = document["sets"]
    if not isinstance(entries, list) or not entries:
        raise MaterialObjectError(f"{where}: sets is a non-empty list")
    sets: dict[str, ManifestEntry] = {}
    for index, candidate in enumerate(entries):
        entry = _entry(candidate, f"{where} sets[{index}]", profile)
        if sets and entry.set_id <= next(reversed(sets)):
            raise MaterialObjectError(f"{where}: sets are sorted by set_id, each id once")
        sets[entry.set_id] = entry
    return MappingProxyType(sets)
