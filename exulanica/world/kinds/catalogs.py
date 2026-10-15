"""The world kinds' own catalogs: look families, engine roles and the bounds every kind is held to.

``assets/catalogs/world-kinds/`` holds each as a versioned, licensed catalog in the house envelope
(:mod:`exulanica.grammar.catalogs`):

* ``look-family.v1.json``: the sixteen look families a part's look role may name, each with how a
  style pack's asset is fitted to a slot (``contain``, ``fill``, ``tile`` or ``surface``), what
  dresses it (a module, a surface material, both, the character catalogs, or the engine's
  primitive) and, for a filled module, how far each axis may stretch. The browser's style-pack
  resolver embeds this file's exact bytes; this module and that resolver read one statement.
* ``kind-role.v1.json``: the engine roles a part may take, each with the part forms that may take
  it and what the engine does with it.
* ``kind-bound.v1.json``: every figure a kind is held to, each with its least and greatest value
  and why; ``kind-bound.v2.json`` the bounds a kind with requirements is read with, and
  ``kind-bound.v3.json`` version 2 with taller structures, for a kind that names it
  (:func:`~exulanica.world.kinds.document.bounds_version_of`).
* ``kind-society.v1.json``: what a kind's society reads where the kind states nothing: the use
  class a seat and a home take when they name none, the words and use class of the home at the
  entry of everybody who lives off the site, and the words said of where its people are and walk.

The site grammar's closed words (:mod:`exulanica.grammar.grammars.site.plan`) and these catalogs
state the same vocabularies; :func:`load_kind_catalogs` refuses them if they differ.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Final, cast

from exulanica.grammar.catalogs import (
    CatalogSchema,
    FieldCheck,
    FieldValue,
    integer_field,
    key_list_field,
    load_catalog,
    text_field,
)
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.grammars.site.plan import FORMS, LOOK_FAMILIES, ROLES

__all__ = [
    "BOUNDS_VERSIONS",
    "CATALOG_DIRECTORY",
    "DRESSINGS",
    "FITS",
    "SOCIETY_DEFAULTS",
    "KindCatalogs",
    "LookFamily",
    "SocietyDefault",
    "load_arcade_catalog",
    "load_kind_catalogs",
]

#: The kind bounds versions this code reads: 1 and 2, each a profile's own, and 3, version 2 with
#: taller structures, read only for a kind that names it.
BOUNDS_VERSIONS: Final = (1, 2, 3)
CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[3].joinpath("assets", "catalogs", "world-kinds")
)
#: How a pack's asset meets a slot, by family.
FITS: Final = ("contain", "fill", "tile", "surface")
#: What dresses a family's slots.
DRESSINGS: Final = ("module", "surface", "both", "catalog", "primitive")


def _choice(values: tuple[str, ...]) -> FieldCheck:
    def check(where: str, value: object) -> FieldValue:
        if value not in values:
            raise CatalogError(f"{where} is one of {list(values)}, got {value!r}")
        return cast(FieldValue, value)

    return check


def _fill_bounds(where: str, values: dict[str, FieldValue]) -> None:
    filled = values["fit"] == "fill"
    low, high = values["fill_minimum_permille"], values["fill_maximum_permille"]
    if filled != (low != 0 or high != 0):
        raise CatalogError(f"{where}: exactly a filled family states how far it may stretch")
    if filled and not 0 < cast(int, low) <= 1000 <= cast(int, high):
        raise CatalogError(f"{where}: a filled module stretches round its authored size")


def _role_forms(where: str, value: object) -> FieldValue:
    forms = key_list_field(where, value)
    if not forms or not set(cast(tuple[str, ...], forms)) <= set(FORMS):
        raise CatalogError(f"{where} names part forms among {list(FORMS)}")
    return forms


def _words(where: str, value: object) -> FieldValue:
    """A default's words or use class: one line of at most 60 characters, or none where a part's
    own are read (or, for words alone, no use class)."""
    if type(value) is not str or value != value.strip() or "\n" in value or len(value) > 60:
        raise CatalogError(f"{where} is one line of at most 60 characters")
    return value


#: What a kind's society reads where the kind states nothing, by these keys: words said of where
#: its people are and walk (``here``, ``around``), and the use class (and words) of a home, the
#: home off the site and a seat.
SOCIETY_DEFAULTS: Final = ("around", "here", "home", "offsite_home", "seat")


def _bound(where: str, values: dict[str, FieldValue]) -> None:
    if cast(int, values["minimum"]) > cast(int, values["maximum"]):
        raise CatalogError(f"{where}: a bound's minimum is at most its maximum")


_FIGURE = integer_field(0, 2**31 - 1)

_SCHEMAS: Final = {
    "look-family": CatalogSchema(
        "look-family",
        1,
        (
            ("fit", _choice(FITS)),
            ("dressing", _choice(DRESSINGS)),
            ("fill_minimum_permille", integer_field(0, 1000)),
            ("fill_maximum_permille", integer_field(0, 4000)),
            ("reason", text_field),
        ),
        entry_check=_fill_bounds,
    ),
    "kind-role": CatalogSchema(
        "kind-role",
        1,
        (("forms", _role_forms), ("reason", text_field)),
    ),
    "kind-bound": CatalogSchema(
        "kind-bound",
        1,
        (("minimum", _FIGURE), ("maximum", _FIGURE), ("reason", text_field)),
        entry_check=_bound,
    ),
    "kind-society": CatalogSchema(
        "kind-society",
        1,
        (("use_class", _words), ("words", _words), ("reason", text_field)),
    ),
}


#: The structure arcade catalog: an arcade's bounds and the figures every arch is drawn with. It is
#: read only for a kind whose structure states an arcade, so it is none of the four catalogs a
#: kind is always read with and no world without an arcade names it.
_ARCADE_SCHEMA: Final = CatalogSchema(
    "structure-arcade",
    1,
    (("minimum", _FIGURE), ("maximum", _FIGURE), ("reason", text_field)),
    entry_check=_bound,
)
ARCADE_FIGURES: Final = ("bays", "depth_mm", "pier_mm", "lintel_mm", "least_opening_mm")


@dataclass(frozen=True, slots=True)
class ArcadeCatalog:
    """The arcade catalog as read: each figure's least and greatest value, and the file's digest."""

    bounds: Mapping[str, tuple[int, int]]
    sha256: str

    def bound(self, key: str) -> tuple[int, int]:
        return self.bounds[key]


@functools.cache
def load_arcade_catalog(directory: Path = CATALOG_DIRECTORY) -> ArcadeCatalog:
    """Read ``structure-arcade.v1.json`` and hold it to the figures an arcade is laid out by."""
    import hashlib

    path = directory.joinpath("structure-arcade.v1.json")
    catalog = load_catalog(path, _ARCADE_SCHEMA)
    read = {entry.key: dict(entry.values) for entry in catalog.entries}
    bounds = {
        key: (cast(int, values["minimum"]), cast(int, values["maximum"]))
        for key, values in read.items()
    }
    if tuple(sorted(bounds)) != tuple(sorted(ARCADE_FIGURES)):
        raise CatalogError(
            f"the arcade catalog states {sorted(bounds)}, not {list(ARCADE_FIGURES)}"
        )
    return ArcadeCatalog(
        bounds=MappingProxyType(bounds), sha256=hashlib.sha256(path.read_bytes()).hexdigest()
    )


@dataclass(frozen=True, slots=True)
class LookFamily:
    key: str
    fit: str
    dressing: str
    fill_minimum_permille: int
    fill_maximum_permille: int


@dataclass(frozen=True, slots=True)
class SocietyDefault:
    """What a kind's society reads where the kind states nothing: a use class, words, or both."""

    use_class: str
    words: str


@dataclass(frozen=True, slots=True)
class KindCatalogs:
    """The four catalogs as read, and the digest of each file's bytes."""

    families: Mapping[str, LookFamily]
    role_forms: Mapping[str, frozenset[str]]
    bounds: Mapping[str, tuple[int, int]]
    sha256: Mapping[str, str]
    society_defaults: Mapping[str, SocietyDefault]
    bounds_version: int = 1

    def bound(self, key: str) -> tuple[int, int]:
        found = self.bounds.get(key)
        if found is None:
            raise CatalogError(f"the kind bounds state no {key!r}")
        return found


def _read(directory: Path, catalog_id: str, version: int = 1) -> dict[str, dict[str, FieldValue]]:
    schema = replace(_SCHEMAS[catalog_id], catalog_version=version)
    catalog = load_catalog(directory.joinpath(f"{catalog_id}.v{version}.json"), schema)
    return {entry.key: dict(entry.values) for entry in catalog.entries}


@functools.cache
def load_kind_catalogs(
    directory: Path = CATALOG_DIRECTORY, *, bounds_version: int = 1
) -> KindCatalogs:
    """Read the four catalogs and hold them to the site grammar's closed words."""
    import hashlib

    families = _read(directory, "look-family")
    if tuple(sorted(families)) != tuple(sorted(LOOK_FAMILIES)):
        raise CatalogError(
            f"the look-family catalog states {sorted(families)}, the site grammar "
            f"{sorted(LOOK_FAMILIES)}"
        )
    roles = _read(directory, "kind-role")
    if tuple(sorted(roles)) != tuple(sorted(ROLES)):
        raise CatalogError(
            f"the kind-role catalog states {sorted(roles)}, the site grammar {ROLES}"
        )
    if bounds_version not in BOUNDS_VERSIONS:
        raise CatalogError(f"unknown kind-bound version {bounds_version}")
    bounds = _read(directory, "kind-bound", bounds_version)
    defaults = _read(directory, "kind-society")
    if tuple(sorted(defaults)) != SOCIETY_DEFAULTS:
        raise CatalogError(
            f"the kind-society catalog states {sorted(defaults)}, not {list(SOCIETY_DEFAULTS)}"
        )
    return KindCatalogs(
        families=MappingProxyType(
            {
                key: LookFamily(
                    key,
                    str(values["fit"]),
                    str(values["dressing"]),
                    cast(int, values["fill_minimum_permille"]),
                    cast(int, values["fill_maximum_permille"]),
                )
                for key, values in sorted(families.items())
            }
        ),
        role_forms=MappingProxyType(
            {
                key: frozenset(cast(tuple[str, ...], values["forms"]))
                for key, values in sorted(roles.items())
            }
        ),
        bounds=MappingProxyType(
            {
                key: (cast(int, values["minimum"]), cast(int, values["maximum"]))
                for key, values in sorted(bounds.items())
            }
        ),
        sha256=MappingProxyType(
            {
                name: hashlib.sha256(
                    directory.joinpath(
                        f"{name}.v{bounds_version if name == 'kind-bound' else 1}.json"
                    ).read_bytes()
                ).hexdigest()
                for name in sorted(_SCHEMAS)
            }
        ),
        society_defaults=MappingProxyType(
            {
                key: SocietyDefault(str(values["use_class"]), str(values["words"]))
                for key, values in sorted(defaults.items())
            }
        ),
        bounds_version=bounds_version,
    )
