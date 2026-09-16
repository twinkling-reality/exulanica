"""Catalogs: versioned JSON vocabularies with a licence on every entry, and a digest over them.

A catalog is data, not code. Grammar vocabulary written as Python constants is the renderer's
loop moved to another language, so every vocabulary a grammar reads lives in a reviewed file
named ``<catalog_id>.v<version>.json``. This module reads such a file against a schema the
consuming grammar supplies; it knows nothing about what any catalog contains.

**Envelope.** ``schema_version``, ``catalog_id``, ``catalog_version`` and ``entries``, and
nothing else. The id and version inside must match the file name.

**Entries.** Each entry has a ``key``, exactly the fields its schema declares, and a
``licence``. An unknown field is refused, a missing one is refused, and a repeated key is
refused. A field that names something elsewhere, such as a texture set, is a
:class:`ReferenceField`: the caller passes what currently exists, a name that does not resolve
raises :class:`~exulanica.grammar.errors.UnresolvedReferenceError` and is never defaulted, and a
name that does resolve carries its referent's pin into the digest while the file keeps the name.

**Licence.** Stated the way ``docs/license-matrix.md`` states one: a verdict plus the primary
source that was read. Only the two shippable verdicts are accepted in a shipped catalog. An
``original`` entry is authored in this repository and takes its licence, Apache-2.0, read from
``LICENSE``. A ``derived`` entry takes its real source's licence and names that source; it may not
cite this repository's licence file as the licence it was read from.

**Registration is not here.** Reading a catalog is not registering it. A running process may
propose a registered value and can never register one, and this package cannot open the
database where registration would happen.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.grammar.documents import read_json, split_versioned_name
from exulanica.grammar.errors import CatalogError, UnresolvedReferenceError
from exulanica.grammar.records import KEY_PATTERN

__all__ = [
    "LICENCE_ORIGINS",
    "LICENCE_VERDICTS",
    "REPOSITORY_LICENCE",
    "REPOSITORY_LICENCE_FILE",
    "Catalog",
    "CatalogEntry",
    "CatalogSchema",
    "Licence",
    "ReferenceField",
    "catalog_digest",
    "integer_field",
    "key_list_field",
    "load_catalog",
    "load_catalog_directory",
    "text_field",
]

#: The two verdicts in ``docs/license-matrix.md`` that permit shipping in this repository.
LICENCE_VERDICTS: Final = ("SHIP", "SHIP-ATTRIB")
LICENCE_ORIGINS: Final = ("original", "derived")
REPOSITORY_LICENCE: Final = "Apache-2.0"
REPOSITORY_LICENCE_FILE: Final = "LICENSE"

FieldValue: TypeAlias = int | str | tuple[str, ...]
FieldCheck: TypeAlias = Callable[[str, object], FieldValue]

_ENVELOPE_KEYS: Final = frozenset({"schema_version", "catalog_id", "catalog_version", "entries"})
_LICENCE_KEYS: Final = frozenset({"spdx", "verdict", "origin", "licence_source", "content_source"})
_RESERVED_FIELDS: Final = frozenset({"key", "licence"})
_SPDX: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")


def _text(where: str, value: object) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise CatalogError(f"{where} is non-empty text with no surrounding space")
    return value


def text_field(where: str, value: object) -> FieldValue:
    return _text(where, value)


def integer_field(minimum: int, maximum: int) -> FieldCheck:
    def check(where: str, value: object) -> FieldValue:
        if type(value) is not int or not minimum <= value <= maximum:
            raise CatalogError(f"{where} is an int in [{minimum}, {maximum}], got {value!r}")
        return value

    return check


def key_list_field(where: str, value: object) -> FieldValue:
    if not isinstance(value, list):
        raise CatalogError(f"{where} is a list of keys")
    for index, item in enumerate(value):
        if type(item) is not str or KEY_PATTERN.fullmatch(item) is None:
            raise CatalogError(f"{where}[{index}] is a lowercase key, got {item!r}")
    if len(set(value)) != len(value):
        raise CatalogError(f"{where} repeats a key")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class ReferenceField:
    """A field naming a ``what`` that must exist, and the pin it carries into the digest.

    ``pins`` maps every name that exists to what the name currently resolves to, such as a
    version and a content digest. The file and the loaded value keep the stable name only; the
    pin is recorded beside the entry and covered by :func:`catalog_digest`, so a referent that
    changes under an unchanged name still moves the digest.
    """

    what: str
    pattern: re.Pattern[str]
    pins: Mapping[str, Mapping[str, int | str]]

    def __call__(self, where: str, value: object) -> FieldValue:
        name = _text(where, value)
        if self.pattern.fullmatch(name) is None:
            raise CatalogError(f"{where} names {self.what} {name!r}, which is not a valid name")
        if name not in self.pins:
            raise UnresolvedReferenceError(
                f"{where} names {self.what} {name!r}, which does not exist; "
                "a missing reference is a schema error, not a default"
            )
        return name


@dataclass(frozen=True, slots=True)
class CatalogSchema:
    """What one catalog's entries carry, besides ``key`` and ``licence``. Supplied by a grammar."""

    catalog_id: str
    catalog_version: int
    fields: tuple[tuple[str, FieldCheck], ...]
    #: A check across one entry's checked fields, for rules no single field can state.
    entry_check: Callable[[str, dict[str, FieldValue]], None] | None = None

    def __post_init__(self) -> None:
        names = [name for name, _ in self.fields]
        if len(set(names)) != len(names) or _RESERVED_FIELDS & set(names):
            raise CatalogError(f"{self.catalog_id}: field names repeat or reuse key or licence")


@dataclass(frozen=True, slots=True)
class Licence:
    spdx: str
    verdict: str
    origin: str
    licence_source: str
    content_source: str

    @classmethod
    def read(cls, where: str, value: object) -> Licence:
        if not isinstance(value, dict):
            raise CatalogError(f"{where} is an object; every entry carries a licence")
        if set(value) != _LICENCE_KEYS:
            raise CatalogError(
                f"{where} has keys {sorted(value)}, expected exactly {sorted(_LICENCE_KEYS)}"
            )
        licence = cls(
            **{name: _text(f"{where}.{name}", value[name]) for name in sorted(_LICENCE_KEYS)}
        )
        if _SPDX.fullmatch(licence.spdx) is None:
            raise CatalogError(f"{where}.spdx is an SPDX identifier, got {licence.spdx!r}")
        if licence.verdict not in LICENCE_VERDICTS:
            raise CatalogError(f"{where}.verdict {licence.verdict!r} may not ship")
        if licence.origin not in LICENCE_ORIGINS:
            raise CatalogError(f"{where}.origin is one of {LICENCE_ORIGINS}")
        if licence.origin == "original":
            if (licence.spdx, licence.licence_source) != (
                REPOSITORY_LICENCE,
                REPOSITORY_LICENCE_FILE,
            ):
                raise CatalogError(
                    f"{where}: an original entry is {REPOSITORY_LICENCE}, "
                    f"read from {REPOSITORY_LICENCE_FILE}"
                )
        elif licence.licence_source == REPOSITORY_LICENCE_FILE:
            raise CatalogError(
                f"{where}: a derived entry names its source's licence, not this repository's"
            )
        return licence


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    key: str
    values: tuple[tuple[str, FieldValue], ...]
    licence: Licence
    #: ``(field, pin)`` for every reference field, sorted by field. Digested, never written back.
    pins: tuple[tuple[str, Mapping[str, int | str]], ...] = ()


@dataclass(frozen=True, slots=True)
class Catalog:
    catalog_id: str
    catalog_version: int
    entries: tuple[CatalogEntry, ...]

    def keys(self) -> tuple[str, ...]:
        return tuple(entry.key for entry in self.entries)

    def payload(self) -> dict[str, object]:
        return {
            "catalog_id": self.catalog_id,
            "catalog_version": self.catalog_version,
            "entries": [
                {
                    "key": entry.key,
                    "fields": {name: _plain(value) for name, value in entry.values},
                    "licence": {
                        name: getattr(entry.licence, name) for name in sorted(_LICENCE_KEYS)
                    },
                    "pins": {field: dict(pin) for field, pin in entry.pins},
                }
                for entry in self.entries
            ],
        }


def _plain(value: FieldValue) -> object:
    return list(value) if isinstance(value, tuple) else value


def load_catalog(path: Path, schema: CatalogSchema) -> Catalog:
    stem, version = split_versioned_name(path)
    if (stem, version) != (schema.catalog_id, schema.catalog_version):
        raise CatalogError(f"{path.name} is not {schema.catalog_id}.v{schema.catalog_version}.json")
    document = read_json(path)
    if not isinstance(document, dict) or set(document) != _ENVELOPE_KEYS:
        raise CatalogError(f"{path.name}: the envelope is exactly {sorted(_ENVELOPE_KEYS)}")
    if document["schema_version"] != 1:
        raise CatalogError(f"{path.name}: schema_version is 1")
    if (document["catalog_id"], document["catalog_version"]) != (stem, version):
        raise CatalogError(
            f"{path.name} declares {document['catalog_id']!r} "
            f"v{document['catalog_version']!r}, which is not its file name"
        )
    raw_entries = document["entries"]
    if not isinstance(raw_entries, list):
        raise CatalogError(f"{path.name}: entries is a list")
    expected = {"key", "licence"} | {name for name, _ in schema.fields}
    entries: list[CatalogEntry] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_entries):
        where = f"{path.name} entries[{index}]"
        if not isinstance(raw, dict):
            raise CatalogError(f"{where} is an object")
        unknown = set(raw) - expected
        missing = expected - set(raw)
        if unknown:
            raise CatalogError(f"{where} has unknown keys {sorted(unknown)}")
        if missing:
            raise CatalogError(f"{where} is missing {sorted(missing)}")
        key = raw["key"]
        if type(key) is not str or KEY_PATTERN.fullmatch(key) is None:
            raise CatalogError(f"{where}.key is a lowercase key, got {key!r}")
        if key in seen:
            raise CatalogError(f"{where}.key {key!r} repeats")
        seen.add(key)
        values = tuple((name, check(f"{where}.{name}", raw[name])) for name, check in schema.fields)
        if schema.entry_check is not None:
            schema.entry_check(where, dict(values))
        pins = tuple(
            sorted(
                (
                    (name, check.pins[value])  # type: ignore[index]
                    for (name, check), (_, value) in zip(schema.fields, values, strict=True)
                    if isinstance(check, ReferenceField)
                ),
                key=lambda pair: pair[0],
            )
        )
        entries.append(
            CatalogEntry(
                key=key,
                values=values,
                licence=Licence.read(f"{where}.licence", raw["licence"]),
                pins=pins,
            )
        )
    catalog = Catalog(schema.catalog_id, schema.catalog_version, tuple(entries))
    canonical_json(catalog.payload())
    return catalog


def load_catalog_directory(
    directory: Path, schemas: Sequence[CatalogSchema]
) -> tuple[Catalog, ...]:
    """Every schema has exactly one file, and every file has a schema. Sorted by id."""
    by_name = {f"{schema.catalog_id}.v{schema.catalog_version}.json": schema for schema in schemas}
    if len(by_name) != len(schemas):
        raise CatalogError("two schemas claim the same catalog file")
    present = sorted(path.name for path in directory.glob("*.json"))
    unexpected = sorted(set(present) - set(by_name))
    absent = sorted(set(by_name) - set(present))
    if unexpected or absent:
        raise CatalogError(
            f"{directory}: files with no schema {unexpected}, schemas with no file {absent}"
        )
    return tuple(load_catalog(directory.joinpath(name), by_name[name]) for name in sorted(by_name))


def catalog_digest(catalogs: Sequence[Catalog]) -> str:
    """SHA-256 over the canonical JSON of every catalog, ordered by id then version. Hex."""
    ordered = sorted(catalogs, key=lambda catalog: (catalog.catalog_id, catalog.catalog_version))
    return sha256_of_canonical([catalog.payload() for catalog in ordered]).hex()
