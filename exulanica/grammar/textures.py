"""Published texture sets: the texture lane's manifest, read here, and the pin each set carries.

The texture lane owns ``assets/textures/manifest.json``; this module only reads it and never
writes it. A texture set id is a stable name matching ``[a-z][a-z0-9.-]*``, the rule an
authored-world asset key already follows, conventionally ``<licence>.<name>``. An id never
contains a version or a digest.

**Records carry the id; pins carry the bytes.** A material record and a catalog entry name a set
by id only. When the catalog loader resolves an id, it records the set's version and content
digest as a pin on the entry, and ``catalog_digest`` covers the pins. A rebaked set therefore
moves the catalog digest, and every tile digest that covers the catalog digest, while no record
and no catalog file changes.

**The manifest's shape**, as fixed with the texture lane before it has written one:
``{"profile": "exulanica.texture-manifest/v1", "sets": [...]}``, where ``sets`` is sorted by
``set_id`` with each id once, and each entry has exactly ``set_id``, ``version``,
``content_sha256``, ``byte_size``, ``resolution``, ``channels``, ``extent_mm``, ``licence_id``
and ``licence_sha256``, integers only. A different profile, a bare array, unsorted sets and a
repeated id are all refused. Nothing reads the manifest by default yet, because none has been
published; callers pass the published sets explicitly.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from exulanica.canonical import canonical_json
from exulanica.grammar.documents import read_json
from exulanica.grammar.errors import CatalogError

__all__ = [
    "MANIFEST_PATH",
    "MANIFEST_PROFILE",
    "TEXTURE_SET_ID",
    "TextureSet",
    "read_texture_manifest",
    "require_texture_set_id",
]

TEXTURE_SET_ID: Final = re.compile(r"[a-z][a-z0-9.-]*")
MANIFEST_PROFILE: Final = "exulanica.texture-manifest/v1"
MANIFEST_PATH: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "textures", "manifest.json")
)

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
_HEX64: Final = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class TextureSet:
    """What a resolved reference pins: the stable id, its version, and its content digest."""

    set_id: str
    version: int
    content_sha256: str

    def __post_init__(self) -> None:
        require_texture_set_id("set_id", self.set_id)
        if type(self.version) is not int or self.version < 1:
            raise CatalogError(f"{self.set_id}: version is a positive int")
        if type(self.content_sha256) is not str or _HEX64.fullmatch(self.content_sha256) is None:
            raise CatalogError(f"{self.set_id}: content_sha256 is 64 lowercase hex characters")

    def pin(self) -> Mapping[str, int | str]:
        return MappingProxyType(
            {
                "set_id": self.set_id,
                "version": self.version,
                "content_sha256": self.content_sha256,
            }
        )


def require_texture_set_id(where: str, value: object) -> str:
    if type(value) is not str or TEXTURE_SET_ID.fullmatch(value) is None:
        raise CatalogError(f"{where} is a texture set id matching [a-z][a-z0-9.-]*, got {value!r}")
    return value


def read_texture_manifest(path: Path = MANIFEST_PATH) -> Mapping[str, TextureSet]:
    """Every published set by id. A missing, malformed or ambiguous manifest is refused."""
    document = read_json(path)
    if not isinstance(document, dict) or set(document) != {"profile", "sets"}:
        raise CatalogError(f"{path.name} is an object with exactly profile and sets")
    if document["profile"] != MANIFEST_PROFILE:
        raise CatalogError(f"{path.name}: profile is {MANIFEST_PROFILE!r}")
    entries = document["sets"]
    if not isinstance(entries, list):
        raise CatalogError(f"{path.name}: sets is a list")
    sets: dict[str, TextureSet] = {}
    for index, entry in enumerate(entries):
        where = f"{path.name} sets[{index}]"
        if not isinstance(entry, dict):
            raise CatalogError(f"{where} is an object")
        if set(entry) != _ENTRY_KEYS:
            raise CatalogError(
                f"{where} has keys {sorted(entry)}, expected exactly {sorted(_ENTRY_KEYS)}"
            )
        texture_set = TextureSet(entry["set_id"], entry["version"], entry["content_sha256"])
        if type(entry["byte_size"]) is not int or entry["byte_size"] < 1:
            raise CatalogError(f"{where}.byte_size is a positive int")
        if type(entry["licence_id"]) is not str or not entry["licence_id"].strip():
            raise CatalogError(f"{where}.licence_id is non-empty text")
        licence_sha256 = entry["licence_sha256"]
        if type(licence_sha256) is not str or _HEX64.fullmatch(licence_sha256) is None:
            raise CatalogError(f"{where}.licence_sha256 is 64 lowercase hex characters")
        canonical_json(entry)
        if texture_set.set_id in sets:
            raise CatalogError(f"{where}: set {texture_set.set_id!r} is published twice")
        if sets and texture_set.set_id < next(reversed(sets)):
            raise CatalogError(f"{where}: sets are sorted by set_id")
        sets[texture_set.set_id] = texture_set
    return MappingProxyType(sets)
