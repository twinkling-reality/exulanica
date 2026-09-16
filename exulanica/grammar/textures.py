"""Published texture sets: the texture lane's manifest, read here, and the pin each set carries.

The texture lane owns ``assets/textures/manifest.json``; this module only reads it and never
writes it, and it reads it through :func:`exulanica.materials.manifest.read_texture_manifest`, the
one reader and the one rule every module shares. A texture set id is a stable name matching
``[a-z][a-z0-9.-]*``, the rule an authored-world asset key already follows, conventionally
``<licence>.<name>``. An id never contains a version or a digest.

**Records carry the id; pins carry the bytes.** A material record and a catalog entry name a set
by id only. When the catalog loader resolves an id, it records the set's version and content
digest as a pin on the entry, and ``catalog_digest`` covers the pins. A rebaked set therefore
moves the catalog digest, and every tile digest that covers the catalog digest, while no record
and no catalog file changes.

**The manifest's shape**, as fixed with the texture lane before it wrote one:
``{"profile": "exulanica.texture-manifest/v1", "sets": [...]}``, where ``sets`` lists at least one
set, sorted by ``set_id`` with each id once, and each entry has exactly ``set_id``, ``version``,
``content_sha256``, ``byte_size``, ``resolution``, ``channels``, ``extent_mm``, ``licence_id``
and ``licence_sha256``. The file is canonical JSON with integers only, and each field has the
form :mod:`exulanica.materials.manifest` states. A different profile, a bare array, unsorted sets,
a repeated id, a malformed field and bytes in any other form are all refused, as
:class:`~exulanica.grammar.errors.CatalogError`. The manifest is published, and callers still pass
the published sets explicitly; nothing here reads it by default.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from exulanica.grammar.errors import CatalogError
from exulanica.materials.manifest import MANIFEST_PROFILE as _MANIFEST_PROFILE
from exulanica.materials.manifest import SET_ID
from exulanica.materials.manifest import read_texture_manifest as _read_manifest
from exulanica.materials.objects import MaterialObjectError, is_sha256

__all__ = [
    "MANIFEST_PATH",
    "MANIFEST_PROFILE",
    "TEXTURE_SET_ID",
    "TextureSet",
    "read_texture_manifest",
    "require_texture_set_id",
]

TEXTURE_SET_ID: Final = SET_ID
MANIFEST_PROFILE: Final = _MANIFEST_PROFILE
MANIFEST_PATH: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "textures", "manifest.json")
)


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
        if not is_sha256(self.content_sha256):
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
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise CatalogError(f"cannot read {path}: {error}") from error
    try:
        entries = _read_manifest(raw, path.name)
    except MaterialObjectError as error:
        raise CatalogError(str(error)) from error
    return MappingProxyType(
        {
            set_id: TextureSet(entry.set_id, entry.version, entry.content_sha256)
            for set_id, entry in entries.items()
        }
    )
