"""Baked texture sets: the pinned catalog, read from ``assets/textures`` and verified byte by byte.

``web/packages/loom-texture`` bakes each set offline, from hashed integers and nothing else, into a
self-describing container, and publishes it content-addressed under ``assets/textures/`` with
``manifest.json`` as the single index. Migration 0065 pins every set's digest, the way migration
0042 pins the GLB bytes :mod:`exulanica.world.assets` generates. The bytes are committed rather
than regenerated here because the generator is the TypeScript package; its own tests rebake every
set and compare with the committed files, so a digest in this directory is still a statement about
source. What this module adds is the backend's half: every digest the manifest names is recomputed
from the bytes on disk before a single set is handed out, and every container header must say what
the manifest says about it.

**Every set is accounted for.** Beside the manifest, ``catalog.json`` names a bake receipt for each
set, and the receipt names the maker manifest, library entry and recipe the bytes were baked from,
all content-addressed under ``objects/``. :mod:`exulanica.materials` verifies that graph, and the
loader then holds each container header to its recipe: seed, resolution, extent, height range,
occlusion, family, surface, title and summary. A set whose provenance does not check out is not
loaded, so a pinned set always comes with the recipe a person or the Companion can vary.

**A material resolves to a pinned set or it does not resolve.** :func:`resolve_texture_set` has
exactly two failure modes: a material record with no texture set id raises
:class:`MissingTextureSet`, and a material record naming an id that is not pinned raises
:class:`UnpinnedTextureSet`. There is no default and no fallback. A fallback here would bring back
the seven flat hex fills the owned district shipped with, under a new name. A surface whose texture
does not resolve is an unavailable surface, and whoever draws it must say so.

**These sets are invented.** Every container states ``"truth": "invented"`` and the catalog row in
0065 carries the same, on a table of its own. Nothing here borrows a recorded artifact's truth
status.

Nothing here writes to the database. :func:`seed_texture_sets` is the one function that puts the
pinned bytes where the migration says they should be, and it is idempotent because the store is
content-addressed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.errors import ExulanicaError, IntegrityError
from exulanica.materials import (
    LibraryRecord,
    MaterialCatalog,
    MaterialObjectError,
    verify_material_catalog,
)
from exulanica.store.base import ContentAddressedStore

__all__ = [
    "CC0_LICENCE_ID",
    "TEXTURE_DIRECTORY",
    "TEXTURE_MANIFEST_PROFILE",
    "TEXTURE_SET_ID_PATTERN",
    "TEXTURE_SET_MEDIA_TYPE",
    "TEXTURE_SET_PROFILE",
    "TEXTURE_TRUTH",
    "DecodedTextureSet",
    "MissingTextureSet",
    "PinnedTextureSet",
    "TextureCatalog",
    "TextureCatalogError",
    "TextureMap",
    "TextureSetUnresolved",
    "UnpinnedTextureSet",
    "decode_texture_set",
    "load_texture_catalog",
    "resolve_texture_set",
    "seed_texture_sets",
]

TEXTURE_DIRECTORY: Final = Path(__file__).resolve().parents[2] / "assets" / "textures"
TEXTURE_MANIFEST_PROFILE: Final = "exulanica.texture-manifest/v1"
TEXTURE_SET_PROFILE: Final = "exulanica.texture-set/v1"
TEXTURE_SET_MEDIA_TYPE: Final = "application/vnd.exulanica.texture-set"
TEXTURE_TRUTH: Final = "invented"
#: Identical to ``asset_key`` in migration 0042 and ``set_id`` in migration 0065, character for
#: character; ``tests/test_texture_set_migration.py`` compares the three.
TEXTURE_SET_ID_PATTERN: Final = "^[a-z][a-z0-9.-]*$"
CC0_LICENCE_ID: Final = "CC0-1.0"

_SET_ID: Final = re.compile(TEXTURE_SET_ID_PATTERN)
_HEX64: Final = re.compile(r"^[0-9a-f]{64}$")
_MAGIC: Final = b"LTX1"
_ALIGNMENT: Final = 16
_MANIFEST: Final = "manifest.json"
_CATALOG: Final = "catalog.json"
_BLOBS: Final = "blobs"
_OBJECTS: Final = "objects"
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


class TextureCatalogError(ExulanicaError):
    """The published directory is not what its manifest, or a container's header, says it is."""


class TextureSetUnresolved(ExulanicaError):
    """A material record does not resolve to a pinned set: a schema error, never a default."""


class MissingTextureSet(TextureSetUnresolved):
    """The material record carries no texture set id."""


class UnpinnedTextureSet(TextureSetUnresolved):
    """The material record names a texture set id that no pinned set has."""


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
_LAYOUT: Final = (
    TextureMap("base_color", 3, ("red", "green", "blue"), True),
    TextureMap("normal", 3, ("normal_x", "normal_y", "normal_z"), False),
    TextureMap("orm", 3, ("occlusion", "roughness", "metalness"), False),
    TextureMap("height", 1, ("height",), False),
)


@dataclass(frozen=True, slots=True)
class PinnedTextureSet:
    """A published set whose bytes were hashed and matched its pin when the catalog was loaded.

    ``extent_u_mm`` and ``extent_v_mm`` are the physical size one tile covers. They are what lets a
    surface carry a real UV scale: a wall ``w`` mm wide repeats the tile ``w / extent_u_mm`` times.
    """

    set_id: str
    version: int
    content_sha256: str
    byte_size: int
    width: int
    height: int
    extent_u_mm: int
    extent_v_mm: int
    maps: tuple[TextureMap, ...]
    licence_id: str
    licence_sha256: str
    title: str
    summary: str
    seed: int
    height_range_mm: int
    path: Path
    #: The maker and recipe the bytes were baked from, and the receipt that says so.
    maker_id: str
    maker_version: int
    recipe_sha256: str
    receipt_sha256: str

    def pin(self) -> Mapping[str, int | str]:
        """What a resolved reference records: the stable id, its version and its content digest."""
        return MappingProxyType(
            {"set_id": self.set_id, "version": self.version, "content_sha256": self.content_sha256}
        )

    def manifest_entry(self) -> dict[str, Any]:
        """The manifest entry this set was loaded from, reconstructed field for field."""
        return {
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

    def read_bytes(self) -> bytes:
        """The container, re-verified: a file changed since the catalog loaded is refused."""
        payload = self.path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != self.content_sha256:
            raise IntegrityError(f"{self.set_id} no longer hashes to its pin {self.content_sha256}")
        return payload


@dataclass(frozen=True, slots=True)
class TextureCatalog:
    """Every pinned set by id, and the licence text they share."""

    sets: Mapping[str, PinnedTextureSet]
    licence_bytes: bytes
    licence_sha256: str
    #: Every maker, recipe, entry and receipt behind the sets, verified.
    materials: MaterialCatalog


@dataclass(frozen=True, slots=True)
class DecodedTextureSet:
    """A container's header and its maps, each map a view over the payload."""

    header: Mapping[str, Any]
    maps: Mapping[str, memoryview]


def _refuse_float(literal: str) -> Any:
    raise TextureCatalogError(f"non-integer number {literal} in a digest input")


def _refuse_constant(literal: str) -> Any:
    raise TextureCatalogError(f"{literal} is not a JSON value a digest input may hold")


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TextureCatalogError(f"key {key!r} appears twice in one object")
        result[key] = value
    return result


def _canonical_document(raw: bytes, where: str) -> Any:
    """Parse JSON that must already be in canonical form, refusing floats and repeated keys."""
    try:
        document = json.loads(
            raw.decode("utf-8"),
            parse_float=_refuse_float,
            parse_constant=_refuse_constant,
            object_pairs_hook=_unique_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TextureCatalogError(f"{where} is not JSON: {error}") from error
    if canonical_json(document) != raw:
        raise TextureCatalogError(
            f"{where} is not canonical JSON, so its bytes are not its content"
        )
    return document


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _decode(payload: bytes, where: str) -> DecodedTextureSet:
    if len(payload) < 8 or payload[:4] != _MAGIC:
        raise TextureCatalogError(f"{where} is not a texture set container")
    header_length = int.from_bytes(payload[4:8], "little")
    if 8 + header_length > len(payload):
        raise TextureCatalogError(f"{where}: the header runs past the end of the file")
    header = _canonical_document(payload[8 : 8 + header_length], f"{where} header")
    if not isinstance(header, dict) or header.get("profile") != TEXTURE_SET_PROFILE:
        raise TextureCatalogError(f"{where} does not declare {TEXTURE_SET_PROFILE}")
    resolution = header.get("resolution")
    if not (
        isinstance(resolution, dict)
        and set(resolution) == {"width", "height"}
        and _positive_int(resolution["width"])
        and _positive_int(resolution["height"])
    ):
        raise TextureCatalogError(f"{where}: resolution is a positive width and height")
    texels = resolution["width"] * resolution["height"]
    start = -(-(8 + header_length) // _ALIGNMENT) * _ALIGNMENT
    if payload[8 + header_length : start] != b" " * (start - 8 - header_length):
        raise TextureCatalogError(f"{where}: the header padding is not spaces")
    declared = header.get("maps")
    if not isinstance(declared, list) or len(declared) != len(_LAYOUT):
        raise TextureCatalogError(f"{where}: the map list is not the declared layout")
    view = memoryview(payload)
    maps: dict[str, memoryview] = {}
    cursor = start
    for entry, layout in zip(declared, _LAYOUT, strict=True):
        length = texels * layout.components
        if not (
            isinstance(entry, dict)
            and entry.get("name") == layout.name
            and entry.get("components") == layout.components
            and entry.get("holds") == list(layout.holds)
            and entry.get("srgb") is layout.srgb
            and entry.get("byte_offset") == cursor
            and entry.get("byte_length") == length
        ):
            raise TextureCatalogError(f"{where}: map {layout.name} is not packed as declared")
        maps[layout.name] = view[cursor : cursor + length]
        cursor += length
    if cursor != len(payload):
        raise TextureCatalogError(
            f"{where}: the maps end at byte {cursor}, the file at {len(payload)}"
        )
    return DecodedTextureSet(header=MappingProxyType(header), maps=MappingProxyType(maps))


def decode_texture_set(payload: bytes) -> DecodedTextureSet:
    """Read a container strictly: the reader refuses anything the baker would not have written."""
    return _decode(payload, "texture set")


def _entry_problems(entry: object, index: int) -> str | None:
    where = f"{_MANIFEST} sets[{index}]"
    if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
        return f"{where} has keys other than exactly {sorted(_ENTRY_KEYS)}"
    set_id = entry["set_id"]
    if type(set_id) is not str or _SET_ID.fullmatch(set_id) is None:
        return f"{where}: set_id {set_id!r} is not a texture set id"
    if not _positive_int(entry["version"]) or not _positive_int(entry["byte_size"]):
        return f"{where}: version and byte_size are positive integers"
    for field in ("content_sha256", "licence_sha256"):
        if type(entry[field]) is not str or _HEX64.fullmatch(entry[field]) is None:
            return f"{where}: {field} is 64 lowercase hex characters"
    if entry["licence_id"] != CC0_LICENCE_ID:
        return f"{where}: licence_id is {CC0_LICENCE_ID}"
    extent = entry["extent_mm"]
    if not (
        isinstance(extent, dict)
        and set(extent) == {"u", "v"}
        and _positive_int(extent["u"])
        and _positive_int(extent["v"])
    ):
        return f"{where}: extent_mm is a positive whole-millimetre u and v"
    return None


def _check_header(header: Mapping[str, Any], entry: Mapping[str, Any], where: str) -> None:
    expected = {
        "media_type": TEXTURE_SET_MEDIA_TYPE,
        "truth": TEXTURE_TRUTH,
        "set_id": entry["set_id"],
        "version": entry["version"],
        "resolution": entry["resolution"],
        "extent_mm": entry["extent_mm"],
        "licence": {"id": entry["licence_id"], "sha256": entry["licence_sha256"]},
    }
    for key, value in expected.items():
        if header.get(key) != value:
            raise TextureCatalogError(
                f"{where}: header {key} is {header.get(key)!r}, not {value!r}"
            )
    channels = [
        {
            "map": texture_map["name"],
            "components": texture_map["components"],
            "holds": texture_map["holds"],
            "srgb": texture_map["srgb"],
        }
        for texture_map in header["maps"]
    ]
    if channels != entry["channels"]:
        raise TextureCatalogError(f"{where}: the manifest's channels are not the header's maps")
    for key in ("seed", "height_range_mm"):
        if type(header.get(key)) is not int or header[key] < 0:
            raise TextureCatalogError(f"{where}: header {key} is a non-negative integer")
    for key in ("title", "summary"):
        if type(header.get(key)) is not str or not header[key].strip():
            raise TextureCatalogError(f"{where}: header {key} is non-empty text")


def _check_provenance(header: Mapping[str, Any], record: LibraryRecord, where: str) -> None:
    """The header says what the entry, the recipe and the maker say, field for field."""
    recipe = record.recipe
    parameters = recipe["parameters"]
    manifest = record.maker.manifest
    expected = {
        "title": record.title,
        "summary": record.summary,
        "seed": recipe["seed"],
        "resolution": dict(recipe["resolution"]),
        "extent_mm": dict(recipe["extent_mm"]),
        "family": manifest["family"],
        "height_range_mm": parameters["height_range_mm"],
        "cavity": {
            "radius_mm": parameters["occlusion_radius_mm"],
            "depth_mm": parameters["occlusion_depth_mm"],
            "strength_permille": parameters["occlusion_strength_permille"],
        },
    }
    for key, value in expected.items():
        if header.get(key) != value:
            raise TextureCatalogError(
                f"{where}: header {key} is {header.get(key)!r}, but its recipe says {value!r}"
            )
    placement = header.get("placement")
    if not isinstance(placement, Mapping) or placement.get("surface") != manifest["surface"]:
        raise TextureCatalogError(f"{where}: header placement is not its maker's surface")


def _object_reader(directory: Path) -> Callable[[str], bytes]:
    def read(digest: str) -> bytes:
        path = directory / _OBJECTS / f"{digest}.json"
        if not path.is_file():
            raise MaterialObjectError(f"object {digest} is not in {directory}")
        return path.read_bytes()

    return read


def load_texture_catalog(directory: Path = TEXTURE_DIRECTORY) -> TextureCatalog:
    """Every published set, each verified against its pin and its own header, or a refusal.

    Refuses a manifest that is not canonical, holds a float, repeats or misorders a set, or names
    a blob that is absent, has the wrong length, hashes to anything but its pin, or carries a
    header that disagrees with the manifest. The licence text every set names is verified too,
    and so is ``catalog.json``: every set's receipt, entry, recipe and maker, and the header
    against the recipe.
    """
    raw = (directory / _MANIFEST).read_bytes()
    document = _canonical_document(raw, _MANIFEST)
    if not isinstance(document, dict) or set(document) != {"profile", "sets"}:
        raise TextureCatalogError(f"{_MANIFEST} is an object with exactly profile and sets")
    if document["profile"] != TEXTURE_MANIFEST_PROFILE:
        raise TextureCatalogError(f"{_MANIFEST}: profile is {TEXTURE_MANIFEST_PROFILE!r}")
    entries = document["sets"]
    if not isinstance(entries, list) or not entries:
        raise TextureCatalogError(f"{_MANIFEST}: sets is a non-empty list")

    checked: dict[str, tuple[Mapping[str, Any], Mapping[str, Any], Path]] = {}
    licence_digests: set[str] = set()
    for index, entry in enumerate(entries):
        problem = _entry_problems(entry, index)
        if problem is not None:
            raise TextureCatalogError(problem)
        set_id = entry["set_id"]
        if set_id in checked or (checked and set_id < next(reversed(checked))):
            raise TextureCatalogError(f"{_MANIFEST}: sets are sorted by set_id, each id once")
        path = directory / _BLOBS / f"{entry['content_sha256']}.ltex"
        if not path.is_file():
            raise TextureCatalogError(f"{set_id}: {path.name} is not in {directory}")
        payload = path.read_bytes()
        if len(payload) != entry["byte_size"]:
            raise TextureCatalogError(
                f"{set_id}: {len(payload)} bytes on disk, {entry['byte_size']} pinned"
            )
        if hashlib.sha256(payload).hexdigest() != entry["content_sha256"]:
            raise TextureCatalogError(
                f"{set_id}: the bytes on disk do not hash to the pinned digest"
            )
        header = _decode(payload, set_id).header
        _check_header(header, entry, set_id)
        checked[set_id] = (entry, header, path)
        licence_digests.add(entry["licence_sha256"])

    if len(licence_digests) != 1:
        raise TextureCatalogError(
            f"the sets name {len(licence_digests)} licence texts; they share one"
        )
    (licence_sha256,) = licence_digests
    licence_path = directory / _BLOBS / f"{licence_sha256}.txt"
    if not licence_path.is_file():
        raise TextureCatalogError(f"the licence text {licence_path.name} is not in {directory}")
    licence_bytes = licence_path.read_bytes()
    if hashlib.sha256(licence_bytes).hexdigest() != licence_sha256:
        raise TextureCatalogError("the licence text does not hash to the digest the sets name")

    catalog_path = directory / _CATALOG
    if not catalog_path.is_file():
        raise TextureCatalogError(
            f"{_CATALOG} is not in {directory}; every published set is accounted for by a receipt"
        )
    try:
        materials = verify_material_catalog(
            catalog_path.read_bytes(), raw, _object_reader(directory)
        )
    except MaterialObjectError as error:
        raise TextureCatalogError(f"{_CATALOG}: {error}") from error
    sets: dict[str, PinnedTextureSet] = {}
    for set_id, (entry, header, path) in checked.items():
        record = materials.sets[set_id]
        _check_provenance(header, record, set_id)
        sets[set_id] = PinnedTextureSet(
            set_id=set_id,
            version=entry["version"],
            content_sha256=entry["content_sha256"],
            byte_size=entry["byte_size"],
            width=entry["resolution"]["width"],
            height=entry["resolution"]["height"],
            extent_u_mm=entry["extent_mm"]["u"],
            extent_v_mm=entry["extent_mm"]["v"],
            maps=_LAYOUT,
            licence_id=entry["licence_id"],
            licence_sha256=entry["licence_sha256"],
            title=header["title"],
            summary=header["summary"],
            seed=header["seed"],
            height_range_mm=header["height_range_mm"],
            path=path,
            maker_id=record.maker.maker_id,
            maker_version=record.maker.version,
            recipe_sha256=record.recipe_sha256,
            receipt_sha256=record.receipt_sha256,
        )
    return TextureCatalog(
        sets=MappingProxyType(sets),
        licence_bytes=licence_bytes,
        licence_sha256=licence_sha256,
        materials=materials,
    )


def resolve_texture_set(material: object, catalog: TextureCatalog) -> PinnedTextureSet:
    """The pinned set a material record names. Two failure modes, and no third.

    ``material`` is a record carrying ``texture_set_id``, as a mapping key or as an attribute (the
    grammar's material record is a dataclass). No id at all, ``None``, or an empty string raises
    :class:`MissingTextureSet`. Anything else that is not exactly a pinned id, whether unknown,
    malformed, differently cased or not a string, raises :class:`UnpinnedTextureSet`. The catalog
    is a required argument, so resolution never loads one implicitly and never has a third way to
    fail; and the one value returned is the catalog's own entry for that id.
    """
    if isinstance(material, Mapping):
        set_id = material.get("texture_set_id")
    else:
        set_id = getattr(material, "texture_set_id", None)
    if set_id is None or set_id == "":
        raise MissingTextureSet(
            "the material record carries no texture set id; a material with no texture is a "
            "schema error, not a default"
        )
    if type(set_id) is not str or set_id not in catalog.sets:
        raise UnpinnedTextureSet(
            f"texture set {set_id!r} is not pinned; only a set migration 0065 or a later "
            "migration pins, and the manifest publishes, can dress a surface"
        )
    return catalog.sets[set_id]


def seed_texture_sets(
    store: ContentAddressedStore, catalog: TextureCatalog | None = None
) -> TextureCatalog:
    """Write every pinned set and the licence text into the content-addressed store.

    Idempotent, because the store is content-addressed. The store's own digest of what it wrote
    is compared with the pin, so a file that changed after the catalog was loaded is refused
    rather than seeded under a key that does not name it.
    """
    catalog = load_texture_catalog() if catalog is None else catalog
    for pinned in catalog.sets.values():
        written = store.put_file(pinned.path)
        if written.blob_id.hex != pinned.content_sha256:
            raise IntegrityError(
                f"{pinned.set_id} was seeded as {written.blob_id.hex}, not its pin "
                f"{pinned.content_sha256}"
            )
    written = store.put_bytes(catalog.licence_bytes)
    if written.blob_id.hex != catalog.licence_sha256:
        raise IntegrityError("the licence text was seeded under a digest the sets do not name")
    return catalog
