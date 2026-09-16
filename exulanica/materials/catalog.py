"""The published material catalog: every set accounted for, object by object.

``assets/textures/catalog.json`` indexes a content-addressed object store. For each published set
it names a bake receipt, and the receipt names what went into the bake (a maker manifest, a
library entry, a recipe, the licence text, the bake pipeline) and what came out (the container's
digest and length). :func:`verify_material_catalog` reads that graph back and refuses it unless:

- every object hashes to the name it is read under, and is canonical, portable JSON with the
  profile its role requires and exactly that profile's fields;
- the catalog describes exactly the manifest it names by digest, one row per set, in order;
- every maker manifest is well formed, and every recipe is valid for the maker it names;
- every receipt agrees with the manifest about the bytes and the licence, and with its entry
  about the recipe; and every entry agrees with its row about the set.

The reader is injected, so this module never opens a file: whoever holds the directory (or a
content-addressed store, or a package) supplies the bytes for a digest. What comes back is frozen.
A catalog can also check a recipe nobody has baked yet, against the maker it names, which is the
check a person's variant or a proposed recipe passes before anything stores it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from exulanica.materials.objects import (
    BAKE_PIPELINE,
    BAKE_RECEIPT_PROFILE,
    CATALOG_PROFILE,
    LIBRARY_ENTRY_PROFILE,
    MAKER_PROFILE,
    RECIPE_PROFILE,
    SAFE_INTEGER,
    MaterialObjectError,
    is_sha256,
    read_document,
    read_object,
    sha256_hex,
)
from exulanica.materials.recipes import manifest_problems, recipe_problems

__all__ = [
    "LibraryRecord",
    "MakerRecord",
    "MaterialCatalog",
    "ObjectReader",
    "verify_material_catalog",
]

#: Bytes for a digest, or an exception. Supplied by whoever holds the objects.
ObjectReader = Callable[[str], bytes]

_CATALOG_KEYS: Final = frozenset({"profile", "manifest_sha256", "makers", "sets"})
_MAKER_ROW_KEYS: Final = frozenset({"maker_id", "version", "object_sha256"})
_SET_ROW_KEYS: Final = frozenset({"set_id", "version", "content_sha256", "receipt_sha256"})
_ENTRY_KEYS: Final = frozenset(
    {"profile", "set_id", "version", "title", "summary", "licence_id", "recipe_sha256"}
)
_RECEIPT_KEYS: Final = frozenset(
    {
        "profile",
        "pipeline",
        "maker_sha256",
        "entry_sha256",
        "recipe_sha256",
        "licence_sha256",
        "content_sha256",
        "byte_size",
    }
)


@dataclass(frozen=True, slots=True)
class MakerRecord:
    """A maker this package has: its id, version, manifest, and the manifest's digest."""

    maker_id: str
    version: int
    sha256: str
    manifest: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class LibraryRecord:
    """A published set and every object that accounts for its bytes."""

    set_id: str
    version: int
    title: str
    summary: str
    licence_id: str
    licence_sha256: str
    content_sha256: str
    byte_size: int
    entry_sha256: str
    recipe_sha256: str
    receipt_sha256: str
    maker: MakerRecord
    recipe: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class MaterialCatalog:
    """The verified catalog: makers by (id, version) and published sets by id."""

    manifest_sha256: str
    makers: Mapping[tuple[str, int], MakerRecord]
    sets: Mapping[str, LibraryRecord]

    def object_digests(self) -> frozenset[str]:
        """Every object the catalog reaches, which is every object the directory may hold."""
        digests = {maker.sha256 for maker in self.makers.values()}
        for record in self.sets.values():
            digests |= {record.entry_sha256, record.recipe_sha256, record.receipt_sha256}
        return frozenset(digests)

    def recipe_problems(self, candidate: object) -> list[str]:
        """Why ``candidate`` is not a valid recipe for a maker this catalog has, or nothing."""
        maker = candidate.get("maker") if isinstance(candidate, Mapping) else None
        identity = (maker.get("id"), maker.get("version")) if isinstance(maker, Mapping) else None
        record = self.makers.get(identity) if _is_identity(identity) else None
        if record is None:
            return ["recipe names a maker id and version this catalog has"]
        return recipe_problems(candidate, record.manifest)


def _positive_integer(value: object) -> bool:
    """An ``int`` that is not a ``bool``, from 1 to the largest integer the baker can write."""
    return type(value) is int and 1 <= value <= SAFE_INTEGER


def _is_identity(identity: object) -> bool:
    return (
        isinstance(identity, tuple)
        and isinstance(identity[0], str)
        and _positive_integer(identity[1])
    )


def _is_text(value: object) -> bool:
    return isinstance(value, str) and value.strip(" ") != ""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MaterialObjectError(message)


def _manifest_sets(manifest_raw: bytes) -> tuple[Mapping[str, Any], ...]:
    """The manifest's set rows, read strictly, with the fields this module compares typed."""
    manifest = read_document(manifest_raw, "manifest")
    sets = manifest.get("sets") if isinstance(manifest, Mapping) else None
    _require(isinstance(sets, list), "the manifest is not a texture manifest")
    for entry in sets:
        _require(
            isinstance(entry, Mapping)
            and isinstance(entry.get("set_id"), str)
            and _positive_integer(entry.get("version"))
            and _positive_integer(entry.get("byte_size"))
            and is_sha256(entry.get("content_sha256"))
            and is_sha256(entry.get("licence_sha256"))
            and isinstance(entry.get("licence_id"), str),
            "the manifest's sets are not texture manifest entries",
        )
    return tuple(sets)


def _object(read: ObjectReader, digest: Any, profile: str, keys: frozenset[str]) -> Any:
    if not is_sha256(digest):
        raise MaterialObjectError(f"{digest!r} is not a sha256 object name")
    raw = read(digest)
    if sha256_hex(raw) != digest:
        raise MaterialObjectError(f"object {digest} does not hash to its name")
    document = read_object(raw, f"object {digest}")
    if not isinstance(document, Mapping) or document.get("profile") != profile:
        raise MaterialObjectError(f"object {digest} is not a {profile} object")
    if keys and set(document) != keys:
        raise MaterialObjectError(f"object {digest} has fields other than exactly {sorted(keys)}")
    return document


def _rows(document: Mapping[str, Any], field: str, keys: frozenset[str]) -> tuple[Any, ...]:
    rows = document[field]
    if not isinstance(rows, tuple) or not rows:
        raise MaterialObjectError(f"catalog {field} is a non-empty list")
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != keys:
            raise MaterialObjectError(f"catalog {field} rows have exactly {sorted(keys)}")
    return rows


def _makers(read: ObjectReader, document: Mapping[str, Any]) -> dict[str, MakerRecord]:
    by_digest: dict[str, MakerRecord] = {}
    previous: tuple[str, int] | None = None
    for row in _rows(document, "makers", _MAKER_ROW_KEYS):
        identity = (row["maker_id"], row["version"])
        if not _is_identity(identity) or (previous is not None and identity <= previous):
            raise MaterialObjectError("catalog makers are sorted by id and version, each once")
        previous = identity
        manifest = _object(read, row["object_sha256"], MAKER_PROFILE, frozenset())
        problems = manifest_problems(manifest)
        if problems:
            raise MaterialObjectError(
                f"maker {row['maker_id']} has a malformed manifest: {'; '.join(problems)}"
            )
        if (manifest["maker_id"], manifest["version"]) != identity:
            raise MaterialObjectError(f"catalog row {identity} names a different maker's manifest")
        by_digest[row["object_sha256"]] = MakerRecord(
            maker_id=identity[0],
            version=identity[1],
            sha256=row["object_sha256"],
            manifest=manifest,
        )
    return by_digest


def verify_material_catalog(
    catalog_raw: bytes, manifest_raw: bytes, read: ObjectReader
) -> MaterialCatalog:
    """The catalog in ``catalog_raw``, verified against ``manifest_raw`` and every object.

    ``manifest_raw`` is read strictly here too, but only for the fields compared with the
    catalog; checking it as a texture manifest is its reader's job.
    """
    document = read_object(catalog_raw, "catalog")
    if not isinstance(document, Mapping) or set(document) != _CATALOG_KEYS:
        raise MaterialObjectError(f"the catalog has exactly {sorted(_CATALOG_KEYS)}")
    if document["profile"] != CATALOG_PROFILE:
        raise MaterialObjectError(f"the catalog's profile is {CATALOG_PROFILE}")
    if document["manifest_sha256"] != sha256_hex(manifest_raw):
        raise MaterialObjectError("the catalog describes a different manifest")
    makers = _makers(read, document)
    listed = _manifest_sets(manifest_raw)
    rows = _rows(document, "sets", _SET_ROW_KEYS)
    for row in rows:
        _require(
            isinstance(row["set_id"], str)
            and _positive_integer(row["version"])
            and is_sha256(row["content_sha256"]),
            "catalog set rows name a set id, a positive integer version and a sha256",
        )
    if [(row["set_id"], row["version"], row["content_sha256"]) for row in rows] != [
        (entry["set_id"], entry["version"], entry["content_sha256"]) for entry in listed
    ]:
        raise MaterialObjectError("the catalog's sets are not the manifest's sets, in order")

    sets: dict[str, LibraryRecord] = {}
    for row, entry in zip(rows, listed, strict=True):
        set_id = row["set_id"]
        receipt = _object(read, row["receipt_sha256"], BAKE_RECEIPT_PROFILE, _RECEIPT_KEYS)
        if receipt["pipeline"] != BAKE_PIPELINE:
            raise MaterialObjectError(f"{set_id} was baked by {receipt['pipeline']!r}")
        _require(
            _positive_integer(receipt["byte_size"])
            and all(
                is_sha256(receipt[field])
                for field in ("maker_sha256", "entry_sha256", "recipe_sha256", "licence_sha256")
            ),
            f"{set_id}: the receipt's digests are sha256 and its byte_size a positive integer",
        )
        for field in ("content_sha256", "byte_size", "licence_sha256"):
            if receipt[field] != entry[field]:
                raise MaterialObjectError(f"{set_id}: the receipt's {field} is not the manifest's")
        maker = makers.get(receipt["maker_sha256"])
        if maker is None:
            raise MaterialObjectError(f"{set_id}: the receipt names a maker the catalog lacks")
        library_entry = _object(read, receipt["entry_sha256"], LIBRARY_ENTRY_PROFILE, _ENTRY_KEYS)
        _require(
            _positive_integer(library_entry["version"])
            and isinstance(library_entry["set_id"], str)
            and isinstance(library_entry["licence_id"], str),
            f"{set_id}: the entry names a set id, a positive integer version and a licence",
        )
        if (library_entry["set_id"], library_entry["version"]) != (set_id, row["version"]):
            raise MaterialObjectError(f"{set_id}: the receipt's entry names another set")
        _require(
            _is_text(library_entry["title"]) and _is_text(library_entry["summary"]),
            f"{set_id}: the entry's title and summary are text",
        )
        if library_entry["licence_id"] != entry["licence_id"]:
            raise MaterialObjectError(f"{set_id}: the entry's licence is not the manifest's")
        if library_entry["recipe_sha256"] != receipt["recipe_sha256"]:
            raise MaterialObjectError(f"{set_id}: the entry and the receipt name different recipes")
        recipe = _object(read, receipt["recipe_sha256"], RECIPE_PROFILE, frozenset())
        problems = recipe_problems(recipe, maker.manifest)
        if problems:
            raise MaterialObjectError(
                f"{set_id}: not a valid {maker.maker_id} recipe: {'; '.join(problems)}"
            )
        sets[set_id] = LibraryRecord(
            set_id=set_id,
            version=row["version"],
            title=library_entry["title"],
            summary=library_entry["summary"],
            licence_id=entry["licence_id"],
            licence_sha256=entry["licence_sha256"],
            content_sha256=row["content_sha256"],
            byte_size=entry["byte_size"],
            entry_sha256=receipt["entry_sha256"],
            recipe_sha256=receipt["recipe_sha256"],
            receipt_sha256=row["receipt_sha256"],
            maker=maker,
            recipe=recipe,
        )
    return MaterialCatalog(
        manifest_sha256=document["manifest_sha256"],
        makers=MappingProxyType(
            {(maker.maker_id, maker.version): maker for maker in makers.values()}
        ),
        sets=MappingProxyType(sets),
    )
