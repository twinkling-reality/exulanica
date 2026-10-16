"""The sea stack catalog: the bound of every value a sea stack states.

One reviewed file, ``assets/catalogs/stacks/sea-stack-value.vN.json``, read through the grammar's
catalog loader with the volume value schema (:func:`~exulanica.grammar.volumes.catalog.
value_schema`): each entry is ``<owner>_<value>`` with its minimum, maximum, default, whether it
must be stated, and for a value stated in words the words it may take, with a reason and a licence.
The owners are ``stack`` (the document itself), ``lean`` (how its trunk leans) and ``arch`` (the
passage through it). Its erosion and strata are a volume's own sections, bounded by the volume
catalogs, so they are not here.

A look, top look or walk word is one the volume catalog the stack's volume is read against admits,
or the catalog is refused at loading. A catalog changes only by a new version, and a later version
keeps every entry of the one before it. Read on first use, never at import, and kept for the
process.
"""

from __future__ import annotations

import dataclasses
import functools
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from exulanica.grammar.catalogs import CatalogSchema, load_catalog
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.volumes.catalog import ValueBound, value_schema, volume_catalog

__all__ = [
    "CATALOG_DIRECTORY",
    "CATALOG_VERSION",
    "CATALOG_VERSIONS",
    "OWNERS",
    "VOLUME_CATALOG_VERSION",
    "SeaStackCatalog",
    "load_sea_stack_catalog",
    "sea_stack_catalog",
    "sea_stack_schema",
]

CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[3].joinpath("assets", "catalogs", "stacks")
)
#: Every version of the sea stack catalog this code reads, and the newest, which reads new stacks.
CATALOG_VERSIONS: Final = (1,)
CATALOG_VERSION: Final = 1
#: The volume catalog version a stack's erosion and strata are bounded by and its volume is read
#: against: the version whose strata vary the beds.
VOLUME_CATALOG_VERSION: Final = 2
OWNERS: Final = ("stack", "lean", "arch")
#: The values the reader states by name; a catalog without one of them is refused at loading.
_NAMED: Final = (
    ("stack", "height_mm"),
    ("stack", "foot_mm"),
    ("stack", "base_radius_mm"),
    ("stack", "top_radius_mm"),
    ("stack", "shoulders"),
    ("stack", "look"),
    ("stack", "top_look"),
    ("stack", "walk"),
    ("lean", "tilt_mdeg"),
    ("lean", "toward_mdeg"),
    ("arch", "width_mm"),
    ("arch", "rise_mm"),
    ("arch", "floor_mm"),
    ("arch", "bearing_mdeg"),
)
#: The stack's words, each held to the volume value of the same name.
_WORDS: Final = ("look", "top_look", "walk")


@dataclass(frozen=True, slots=True)
class SeaStackCatalog:
    version: int
    #: Keyed by (owner, value).
    values: Mapping[tuple[str, str], ValueBound]

    def values_of(self, owner: str) -> dict[str, ValueBound]:
        return {value: bound for (named, value), bound in self.values.items() if named == owner}


def sea_stack_schema(version: int) -> CatalogSchema:
    """The sea stack catalog's schema at ``version``: the volume value schema's fields."""
    return dataclasses.replace(value_schema(version), catalog_id="sea-stack-value")


def load_sea_stack_catalog(
    directory: Path = CATALOG_DIRECTORY, version: int = CATALOG_VERSION
) -> SeaStackCatalog:
    if version not in CATALOG_VERSIONS:
        raise CatalogError(f"sea stack catalogs are versions {CATALOG_VERSIONS}, not {version}")
    loaded = load_catalog(
        directory.joinpath(f"sea-stack-value.v{version}.json"), sea_stack_schema(version)
    )
    values = {}
    for entry in loaded.entries:
        fields = dict(entry.values)
        owner, value = str(fields["owner"]), str(fields["value"])
        if owner not in OWNERS:
            raise CatalogError(f"sea-stack-value {entry.key} bounds an unknown owner {owner!r}")
        if entry.key != f"{owner}_{value}":
            raise CatalogError(f"sea-stack-value {entry.key} is keyed by its owner and value")
        if fields["count"] != 1:
            raise CatalogError(f"sea-stack-value {entry.key} is one number or one word")
        values[(owner, value)] = ValueBound(
            owner=owner,
            value=value,
            minimum=int(fields["minimum"]),  # type: ignore[arg-type]
            maximum=int(fields["maximum"]),  # type: ignore[arg-type]
            default=int(fields["default"]),  # type: ignore[arg-type]
            required=bool(fields["required"]),
            count=1,
            words=tuple(fields["words"]),  # type: ignore[arg-type]
        )
    missing = [f"{owner}_{value}" for owner, value in _NAMED if (owner, value) not in values]
    if missing:
        raise CatalogError(f"sea-stack-value v{version} does not bound {', '.join(missing)}")
    admitted = volume_catalog(VOLUME_CATALOG_VERSION).values_of("volume")
    for name in _WORDS:
        foreign = sorted(set(values[("stack", name)].words) - set(admitted[name].words))
        if foreign:
            raise CatalogError(
                f"sea-stack-value stack_{name} names {', '.join(foreign)}, which a volume's "
                f"{name} is not"
            )
    return SeaStackCatalog(version=version, values=values)


@functools.cache
def sea_stack_catalog(version: int = CATALOG_VERSION) -> SeaStackCatalog:
    """The shipped catalog at ``version`` (the newest unless one is named), read once per
    process."""
    return load_sea_stack_catalog(version=version)
