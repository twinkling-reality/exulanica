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
all content-addressed under ``objects/``. The catalog's own digest is pinned here as
:data:`TEXTURE_CATALOG_SHA256`, which pins every object it reaches, so a directory that differs from
the reviewed one in any object does not load however consistent it is with itself; and
:data:`PUBLISHED_MAKER_MANIFESTS` pins each maker version to one manifest forever.
:mod:`exulanica.materials` verifies the graph, and the loader then holds each container header to
its recipe: seed, resolution, extent, height range, occlusion, family, surface, title, summary, and
every stated parameter that is one of the maker's integer controls. A set whose provenance does not
check out is not loaded, so a pinned set always comes with the recipe a person or the Companion can
vary.

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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from exulanica.errors import ExulanicaError, IntegrityError
from exulanica.materials import (
    MaterialCatalog,
    MaterialObjectError,
    read_document,
    thaw,
    verify_material_catalog,
)
from exulanica.materials.classes import (
    MAKER_KINDS,
    MATERIAL_CLASSES,
    TEXTURE_SET_PROFILE_V1,
    TEXTURE_SET_PROFILE_V2,
    TEXTURE_SET_PROFILES,
    V1_LAYOUT,
    V2_HEADER_KEYS,
    class_layout,
    class_parameters,
    coverage_permille,
    relief_keys,
)
from exulanica.materials.manifest import (
    MANIFEST_NAME,
    MANIFEST_PROFILE,
    PUBLISHED_LICENCE_ID,
    SET_ID_PATTERN,
    ManifestEntry,
    TextureMap,
    read_texture_manifest,
)
from exulanica.materials.objects import identical
from exulanica.store.base import ContentAddressedStore

__all__ = [
    "CC0_LICENCE_ID",
    "PUBLISHED_MAKER_MANIFESTS",
    "TEXTURE_CATALOG_SHA256",
    "TEXTURE_DIRECTORY",
    "TEXTURE_MANIFEST_PROFILE",
    "TEXTURE_SET_ID_PATTERN",
    "TEXTURE_SET_MEDIA_TYPE",
    "TEXTURE_SET_PROFILE",
    "TEXTURE_SET_PROFILE_V2",
    "TEXTURE_TRUTH",
    "DecodedTextureSet",
    "MissingTextureSet",
    "PinnedTextureSet",
    "TextureCatalog",
    "TextureCatalogError",
    "TextureMap",
    "TextureSetRefused",
    "TextureSetUnresolved",
    "UnpinnedTextureSet",
    "decode_texture_set",
    "load_material_catalog",
    "load_texture_catalog",
    "read_texture_set",
    "resolve_texture_set",
    "seed_texture_sets",
    "verify_container",
]

TEXTURE_DIRECTORY: Final = Path(__file__).resolve().parents[2] / "assets" / "textures"
TEXTURE_MANIFEST_PROFILE: Final = MANIFEST_PROFILE
#: The profile of every set published before material classes.
TEXTURE_SET_PROFILE: Final = TEXTURE_SET_PROFILE_V1
TEXTURE_SET_MEDIA_TYPE: Final = "application/vnd.exulanica.texture-set"
TEXTURE_TRUTH: Final = "invented"
#: Identical to ``asset_key`` in migration 0042 and ``set_id`` in migration 0065, character for
#: character; ``tests/test_texture_set_migration.py`` compares the three.
TEXTURE_SET_ID_PATTERN: Final = SET_ID_PATTERN
CC0_LICENCE_ID: Final = PUBLISHED_LICENCE_ID
#: The reviewed published library: the sha256 of ``assets/textures/catalog.json``. The catalog
#: names every maker manifest and every receipt by digest, and each receipt names its entry and
#: recipe, so this one digest pins every object in the directory. A rebake that changes any object
#: changes it, and updates it here in the same commit; the package's
#: ``test/published.test.ts`` compares it with the committed catalog so the web suite says so first.
TEXTURE_CATALOG_SHA256: Final = "c6343f4cd3a1794e95bdbf9f4ef9843e26cf212002d9e119980bce85c24e8c9e"
#: Every published maker manifest, by maker id and version. Rows are appended, never edited or
#: removed: a recipe names a maker by id and version, so a published version names one manifest
#: forever, and a change to a maker's controls, rules or wording is a new version and a new row.
PUBLISHED_MAKER_MANIFESTS: Final[Mapping[tuple[str, int], str]] = MappingProxyType(
    {
        ("loom.ashlar", 1): "f689a79667f18cccc577b007fb74e9c6c831482a4afac29222153d3cb6ad2cff",
        ("loom.asphalt", 1): "a1b1a9435744a6cb5bd9c046109a63a0b41b41bcd8e162562a1d91109ad67a88",
        ("loom.brick", 1): "50ae89003097a3b3a68f78490c1344278477a3351ef63b6dde59e06d1435f5c6",
        ("loom.concrete", 1): "4215979b6d8dc40bc86605ca020070583892c2094042aebd1c02bb692d803fae",
        ("loom.kerb", 1): "838d4404a523e2080005f75bb673baa23d4c15e333f415741f13943f80b408f7",
        ("loom.metal", 1): "63c5080a4a150d5da0199cbf81e354512cae9ee27004209e8025826935d62635",
        ("loom.paving", 1): "e1d8bf41461217f50d3880e75298056c22dc869cc86aa652afb3d99c565fbbb0",
        ("loom.render", 1): "ebe23d3b8dc98ac86531788499137d7196a81c96717b80e1d80752add8118245",
    }
)

_MAGIC: Final = b"LTX1"
_ALIGNMENT: Final = 16
_MANIFEST: Final = MANIFEST_NAME
_CATALOG: Final = "catalog.json"
_BLOBS: Final = "blobs"
_OBJECTS: Final = "objects"


class TextureCatalogError(ExulanicaError):
    """The published directory is not what its manifest, or a container's header, says it is."""


class TextureSetRefused(TextureCatalogError):
    """A container this reader will not read, and which of the shared reasons refused it.

    ``reason`` is one of ``byte-size`` and ``digest`` (the bytes are not the ones the entry pins),
    ``container`` (the file's framing) and ``header`` (what the header says, including where it
    disagrees with the entry): the reasons ``web/packages/loom-texture/test/texture-set-cases.json``
    holds every reader to. A manifest the reader refuses is a :class:`MaterialObjectError`.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class TextureSetUnresolved(ExulanicaError):
    """A material record does not resolve to a pinned set: a schema error, never a default."""


class MissingTextureSet(TextureSetUnresolved):
    """The material record carries no texture set id."""


class UnpinnedTextureSet(TextureSetUnresolved):
    """The material record names a texture set id that no pinned set has."""


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
    container_profile: str
    material_class: str
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
        return ManifestEntry(
            set_id=self.set_id,
            version=self.version,
            content_sha256=self.content_sha256,
            byte_size=self.byte_size,
            width=self.width,
            height=self.height,
            extent_u_mm=self.extent_u_mm,
            extent_v_mm=self.extent_v_mm,
            licence_id=self.licence_id,
            licence_sha256=self.licence_sha256,
            container_profile=self.container_profile,
            material_class=self.material_class,
            maps=self.maps,
        ).as_entry()

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
    profile: str
    material_class: str
    maker_kind: str
    layout: tuple[TextureMap, ...]


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _decode(payload: bytes, where: str) -> DecodedTextureSet:
    if len(payload) < 8 or payload[:4] != _MAGIC:
        raise TextureSetRefused("container", f"{where} is not a texture set container")
    header_length = int.from_bytes(payload[4:8], "little")
    if 8 + header_length > len(payload):
        raise TextureSetRefused("container", f"{where}: the header runs past the end of the file")
    try:
        header = read_document(payload[8 : 8 + header_length], f"{where} header")
    except MaterialObjectError as error:
        raise TextureSetRefused("header", str(error)) from error
    profile = header.get("profile") if isinstance(header, dict) else None
    if type(profile) is not str or profile not in TEXTURE_SET_PROFILES:
        raise TextureSetRefused(
            "header",
            f"{where} does not declare {TEXTURE_SET_PROFILE_V1} or {TEXTURE_SET_PROFILE_V2}",
        )
    resolution = header.get("resolution")
    if not (
        isinstance(resolution, dict)
        and set(resolution) == {"width", "height"}
        and _positive_int(resolution["width"])
        and _positive_int(resolution["height"])
    ):
        raise TextureSetRefused("header", f"{where}: resolution is a positive width and height")
    texels = resolution["width"] * resolution["height"]
    start = -(-(8 + header_length) // _ALIGNMENT) * _ALIGNMENT
    if payload[8 + header_length : start] != b" " * (start - 8 - header_length):
        raise TextureSetRefused("container", f"{where}: the header padding is not spaces")
    declared = header.get("maps")
    if not isinstance(declared, list):
        raise TextureSetRefused("header", f"{where}: the map list is not the declared layout")

    material_class, maker_kind, layout = "opaque", "procedural", V1_LAYOUT
    if profile == TEXTURE_SET_PROFILE_V2:
        material_class, maker_kind = header.get("material_class"), header.get("maker_kind")
        if type(material_class) is not str or material_class not in MATERIAL_CLASSES:
            raise TextureSetRefused(
                "header", f"{where}: material_class is one of {', '.join(MATERIAL_CLASSES)}"
            )
        if type(maker_kind) is not str or maker_kind not in MAKER_KINDS:
            raise TextureSetRefused(
                "header", f"{where}: maker_kind is one of {', '.join(MAKER_KINDS)}"
            )

        def named(name: str) -> bool:
            return any(isinstance(entry, dict) and entry.get("name") == name for entry in declared)

        layout = class_layout(
            material_class, maker_kind, normal=named("normal"), height=named("height")
        )
        keys = V2_HEADER_KEYS | relief_keys(
            material_class, maker_kind, ships_height=named("height")
        )
        if set(header) != keys:
            raise TextureSetRefused(
                "header",
                f"{where}: a header of maker kind {maker_kind} and class {material_class} has "
                f"exactly {', '.join(sorted(keys))}",
            )

    if len(declared) != len(layout):
        raise TextureSetRefused("header", f"{where}: the map list is not the declared layout")
    view = memoryview(payload)
    maps: dict[str, memoryview] = {}
    cursor = start
    for entry, texture_map in zip(declared, layout, strict=True):
        length = texels * texture_map.components
        if profile == TEXTURE_SET_PROFILE_V1:
            packing = {
                "name": texture_map.name,
                "components": texture_map.components,
                "holds": list(texture_map.holds),
                "srgb": texture_map.srgb,
                "byte_offset": cursor,
                "byte_length": length,
            }
            # A v1 map may also describe itself (the baker writes how to decode it); what it may
            # not do is state its packing any other way, and `true` is not `1` here.
            packed = isinstance(entry, dict) and all(
                identical(entry.get(key), value) for key, value in packing.items()
            )
        else:
            # A v2 map states exactly its descriptor: a decode or convention in other words is
            # another claim about the same bytes.
            packed = identical(
                entry, {**texture_map.as_descriptor(), "byte_offset": cursor, "byte_length": length}
            )
        if not packed:
            raise TextureSetRefused(
                "header", f"{where}: map {texture_map.name} is not packed as declared"
            )
        maps[texture_map.name] = view[cursor : cursor + length]
        cursor += length
    if cursor != len(payload):
        raise TextureSetRefused(
            "container", f"{where}: the maps end at byte {cursor}, the file at {len(payload)}"
        )

    if profile == TEXTURE_SET_PROFILE_V2:
        colour = maps.get("base_color_coverage")
        stated = class_parameters(
            material_class, None if colour is None else coverage_permille(colour)
        )
        if not identical(header.get("class"), stated):
            raise TextureSetRefused(
                "header",
                f"{where}: class is {header.get('class')!r}, but a set of class {material_class} "
                f"with these maps states {stated!r}",
            )
        if "height_range_mm" in header and not _positive_int(header["height_range_mm"]):
            raise TextureSetRefused("header", f"{where}: height_range_mm is a positive integer")
        if "cavity" in header:
            cavity = header["cavity"]
            if not (
                isinstance(cavity, dict)
                and set(cavity) == {"radius_mm", "depth_mm", "strength_permille"}
                and _positive_int(cavity["radius_mm"])
                and _positive_int(cavity["depth_mm"])
                and type(cavity["strength_permille"]) is int
                and cavity["strength_permille"] >= 0
            ):
                raise TextureSetRefused(
                    "header",
                    f"{where}: cavity is a positive radius_mm and depth_mm and a strength_permille",
                )
    return DecodedTextureSet(
        header=MappingProxyType(header),
        maps=MappingProxyType(maps),
        profile=profile,
        material_class=material_class,
        maker_kind=maker_kind,
        layout=layout,
    )


def decode_texture_set(payload: bytes) -> DecodedTextureSet:
    """Read a container strictly: the reader refuses anything the baker would not have written."""
    return _decode(payload, "texture set")


def _check_header(decoded: DecodedTextureSet, entry: ManifestEntry, where: str) -> None:
    """The header says what the manifest entry says. Its maps were held to the layout on decode."""
    header = decoded.header
    expected = {
        "media_type": TEXTURE_SET_MEDIA_TYPE,
        "truth": TEXTURE_TRUTH,
        "set_id": entry.set_id,
        "version": entry.version,
        "resolution": {"width": entry.width, "height": entry.height},
        "extent_mm": {"u": entry.extent_u_mm, "v": entry.extent_v_mm},
        "licence": {"id": entry.licence_id, "sha256": entry.licence_sha256},
    }
    for key, value in expected.items():
        if not identical(header.get(key), value):
            raise TextureSetRefused(
                "header", f"{where}: header {key} is {header.get(key)!r}, not {value!r}"
            )
    if decoded.profile != entry.container_profile:
        raise TextureSetRefused(
            "header",
            f"{where}: the container is {decoded.profile}; the manifest says "
            f"{entry.container_profile}",
        )
    if decoded.material_class != entry.material_class:
        raise TextureSetRefused(
            "header",
            f"{where}: the container is {decoded.material_class}; the manifest says "
            f"{entry.material_class}",
        )
    if decoded.layout != entry.maps:
        raise TextureSetRefused(
            "header", f"{where}: the manifest's channels are not the header's maps"
        )
    # Every v1 header states a height range; a v2 header states one only when its layout has relief.
    relief = decoded.profile == TEXTURE_SET_PROFILE_V1 or "height_range_mm" in header
    for key in ("seed", "height_range_mm") if relief else ("seed",):
        if type(header.get(key)) is not int or header[key] < 0:
            raise TextureSetRefused("header", f"{where}: header {key} is a non-negative integer")
    for key in ("title", "summary"):
        if type(header.get(key)) is not str or not header[key].strip():
            raise TextureSetRefused("header", f"{where}: header {key} is non-empty text")


def read_texture_set(payload: bytes, entry: ManifestEntry) -> DecodedTextureSet:
    """One container held to its manifest entry: its length, its digest, its framing, its header.

    Each refusal is a :class:`TextureSetRefused` naming the shared reason, in this order: the byte
    count must be the pinned one; the sha256 must be the pinned one; the container must be exactly
    what the baker writes; and its header must say what the entry says.
    """
    where = entry.set_id
    if len(payload) != entry.byte_size:
        raise TextureSetRefused(
            "byte-size", f"{where}: {len(payload)} bytes, {entry.byte_size} expected"
        )
    if hashlib.sha256(payload).hexdigest() != entry.content_sha256:
        raise TextureSetRefused("digest", f"{where}: the bytes do not hash to the expected digest")
    decoded = _decode(payload, where)
    _check_header(decoded, entry, where)
    return decoded


def _check_provenance(
    header: Mapping[str, Any],
    *,
    title: str,
    summary: str,
    recipe: Mapping[str, Any],
    manifest: Mapping[str, Any],
    where: str,
) -> None:
    """The header says what the identity, the recipe and the maker say, field for field."""
    parameters = recipe["parameters"]
    expected = {
        "title": title,
        "summary": summary,
        "seed": recipe["seed"],
        "resolution": thaw(recipe["resolution"]),
        "extent_mm": thaw(recipe["extent_mm"]),
        "family": manifest["family"],
        "height_range_mm": parameters["height_range_mm"],
        "cavity": {
            "radius_mm": parameters["occlusion_radius_mm"],
            "depth_mm": parameters["occlusion_depth_mm"],
            "strength_permille": parameters["occlusion_strength_permille"],
        },
    }
    for key, value in expected.items():
        if not identical(header.get(key), value):
            raise TextureCatalogError(
                f"{where}: header {key} is {header.get(key)!r}, but its recipe says {value!r}"
            )
    placement = header.get("placement")
    if not isinstance(placement, Mapping) or placement.get("surface") != manifest["surface"]:
        raise TextureCatalogError(f"{where}: header placement is not its maker's surface")
    # A maker may state a control under that control's own key only with the recipe's value, which
    # loom-texture's makers test holds every maker to. Derived values stated under other keys are
    # the maker's to compute, and the package's rebake is what checks those.
    stated = header.get("parameters")
    if not isinstance(stated, Mapping):
        raise TextureCatalogError(f"{where}: header parameters is an object")
    integers = {control["key"] for control in manifest["controls"] if control["kind"] == "integer"}
    for key, value in stated.items():
        if key in integers and (type(value) is not int or value != parameters[key]):
            raise TextureCatalogError(
                f"{where}: header parameter {key} is {value!r}, but its recipe says "
                f"{parameters[key]!r}"
            )


def verify_container(
    payload: bytes,
    *,
    expected: ManifestEntry,
    title: str,
    summary: str,
    recipe: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> DecodedTextureSet:
    """One container, held to everything a published set is held to, or a refusal.

    The bytes must hash to ``expected.content_sha256`` and have its length, decode strictly, and
    carry a header that says what ``expected`` says (set id, version, resolution, extent, licence)
    and what the recipe and maker say (title, summary, seed, family, surface, height range,
    occlusion, stated integer controls). The published loader asks exactly this of each set; the
    workspace bake worker asks it of every container the baker hands back, and stores nothing that
    fails it.
    """
    decoded = read_texture_set(payload, expected)
    _check_provenance(
        decoded.header,
        title=title,
        summary=summary,
        recipe=recipe,
        manifest=manifest,
        where=expected.set_id,
    )
    return decoded


def _object_reader(directory: Path) -> Callable[[str], bytes]:
    def read(digest: str) -> bytes:
        path = directory / _OBJECTS / f"{digest}.json"
        if not path.is_file():
            raise MaterialObjectError(f"object {digest} is not in {directory}")
        return path.read_bytes()

    return read


def _verified_materials(
    directory: Path,
    manifest_raw: bytes,
    *,
    catalog_sha256: str,
    makers: Mapping[tuple[str, int], str],
) -> MaterialCatalog:
    catalog_path = directory / _CATALOG
    if not catalog_path.is_file():
        raise TextureCatalogError(
            f"{_CATALOG} is not in {directory}; every published set is accounted for by a receipt"
        )
    catalog_raw = catalog_path.read_bytes()
    catalog_digest = hashlib.sha256(catalog_raw).hexdigest()
    if catalog_digest != catalog_sha256:
        raise TextureCatalogError(
            f"{_CATALOG} hashes to {catalog_digest}, not the reviewed pin {catalog_sha256}; a "
            "rebake that changes any object updates TEXTURE_CATALOG_SHA256 in the same commit"
        )
    try:
        materials = verify_material_catalog(catalog_raw, manifest_raw, _object_reader(directory))
    except MaterialObjectError as error:
        raise TextureCatalogError(f"{_CATALOG}: {error}") from error
    published = {key: record.sha256 for key, record in materials.makers.items()}
    if published != dict(makers):
        changed = sorted(
            f"{maker_id} version {version}"
            for maker_id, version in set(published) | set(makers)
            if published.get((maker_id, version)) != makers.get((maker_id, version))
        )
        raise TextureCatalogError(
            f"{_CATALOG}: {', '.join(changed)} is not the published maker manifest; a published "
            "maker version names one manifest forever, and a changed maker is a new version"
        )
    return materials


def load_material_catalog(
    directory: Path = TEXTURE_DIRECTORY,
    *,
    catalog_sha256: str = TEXTURE_CATALOG_SHA256,
    makers: Mapping[tuple[str, int], str] = PUBLISHED_MAKER_MANIFESTS,
) -> MaterialCatalog:
    """The published makers and recipes, verified against both pins, without reading a blob.

    Everything :func:`load_texture_catalog` checks about the object graph, and nothing about the
    containers: what a process needs to judge a person's recipe, or to hold a bake to its maker,
    when it has ``manifest.json``, ``catalog.json`` and ``objects/`` but not the sets themselves.
    """
    raw = (directory / _MANIFEST).read_bytes()
    try:
        read_texture_manifest(raw, _MANIFEST)
    except MaterialObjectError as error:
        raise TextureCatalogError(str(error)) from error
    return _verified_materials(directory, raw, catalog_sha256=catalog_sha256, makers=makers)


def load_texture_catalog(
    directory: Path = TEXTURE_DIRECTORY,
    *,
    catalog_sha256: str = TEXTURE_CATALOG_SHA256,
    makers: Mapping[tuple[str, int], str] = PUBLISHED_MAKER_MANIFESTS,
) -> TextureCatalog:
    """Every published set, each verified against its pin and its own header, or a refusal.

    Refuses a manifest that is not canonical, holds a float, repeats or misorders a set, or names
    a blob that is absent, has the wrong length, hashes to anything but its pin, or carries a
    header that disagrees with the manifest. The licence text every set names is verified too,
    and so is ``catalog.json``: its digest against ``catalog_sha256``, its makers against
    ``makers``, every set's receipt, entry, recipe and maker, and the header against the recipe.
    The two pins default to the reviewed library; a caller verifying another directory names
    that directory's own.
    """
    raw = (directory / _MANIFEST).read_bytes()
    try:
        entries = read_texture_manifest(raw, _MANIFEST)
    except MaterialObjectError as error:
        raise TextureCatalogError(str(error)) from error

    checked: dict[str, tuple[ManifestEntry, Mapping[str, Any], Path]] = {}
    licence_digests: set[str] = set()
    for set_id, entry in entries.items():
        path = directory / _BLOBS / f"{entry.content_sha256}.ltex"
        if not path.is_file():
            raise TextureCatalogError(f"{set_id}: {path.name} is not in {directory}")
        payload = path.read_bytes()
        if len(payload) != entry.byte_size:
            raise TextureSetRefused(
                "byte-size", f"{set_id}: {len(payload)} bytes on disk, {entry.byte_size} pinned"
            )
        if hashlib.sha256(payload).hexdigest() != entry.content_sha256:
            raise TextureSetRefused(
                "digest", f"{set_id}: the bytes on disk do not hash to the pinned digest"
            )
        decoded = _decode(payload, set_id)
        _check_header(decoded, entry, set_id)
        header = decoded.header
        checked[set_id] = (entry, header, path)
        licence_digests.add(entry.licence_sha256)

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

    materials = _verified_materials(directory, raw, catalog_sha256=catalog_sha256, makers=makers)
    sets: dict[str, PinnedTextureSet] = {}
    for set_id, (entry, header, path) in checked.items():
        record = materials.sets[set_id]
        _check_provenance(
            header,
            title=record.title,
            summary=record.summary,
            recipe=record.recipe,
            manifest=record.maker.manifest,
            where=set_id,
        )
        sets[set_id] = PinnedTextureSet(
            set_id=set_id,
            version=entry.version,
            content_sha256=entry.content_sha256,
            byte_size=entry.byte_size,
            width=entry.width,
            height=entry.height,
            extent_u_mm=entry.extent_u_mm,
            extent_v_mm=entry.extent_v_mm,
            container_profile=entry.container_profile,
            material_class=entry.material_class,
            maps=entry.maps,
            licence_id=entry.licence_id,
            licence_sha256=entry.licence_sha256,
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
