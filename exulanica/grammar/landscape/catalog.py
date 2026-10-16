"""The landscape catalog: the bound of every value a landscape and its placements state.

One reviewed file, ``assets/catalogs/landscape/landscape-value.vN.json``, read through the
grammar's catalog loader with the volume value schema (:func:`~exulanica.grammar.volumes.catalog.
value_schema`): each entry is ``<owner>_<value>`` with its minimum, maximum, default, whether it
must be stated, how many whole numbers it is, and a reason and a licence. The owners are
``landscape`` (the document itself), ``placement`` (each volume it places) and, from version 2,
``site`` (a site laid out on a placed volume's top).

A catalog changes only by a new version, and a later version keeps every entry of the one before
it. Read on first use, never at import, and kept for the process.
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
from exulanica.grammar.volumes.catalog import ValueBound, value_schema

__all__ = [
    "CATALOG_DIRECTORY",
    "CATALOG_VERSION",
    "CATALOG_VERSIONS",
    "OWNERS",
    "LandscapeCatalog",
    "landscape_catalog",
    "landscape_schema",
    "load_landscape_catalog",
]

CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[3].joinpath("assets", "catalogs", "landscape")
)
#: Every version of the landscape catalog this code reads, and the newest, which reads new
#: landscapes.
CATALOG_VERSIONS: Final = (1, 2)
CATALOG_VERSION: Final = 2
OWNERS: Final = ("landscape", "placement", "site")
#: The values the reader states by name; a catalog without one of them is refused at loading.
_NAMED: Final = (
    ("landscape", "extent_mm"),
    ("landscape", "volumes"),
    ("landscape", "finest_cell_mm"),
    ("placement", "at_mm"),
    ("placement", "yaw_mdeg"),
)


@dataclass(frozen=True, slots=True)
class LandscapeCatalog:
    #: Keyed by (owner, value).
    values: Mapping[tuple[str, str], ValueBound]

    def values_of(self, owner: str) -> dict[str, ValueBound]:
        return {value: bound for (named, value), bound in self.values.items() if named == owner}


def landscape_schema(version: int) -> CatalogSchema:
    """The landscape catalog's schema at ``version``: the volume value schema's fields."""
    return dataclasses.replace(value_schema(version), catalog_id="landscape-value")


def load_landscape_catalog(
    directory: Path = CATALOG_DIRECTORY, version: int = CATALOG_VERSION
) -> LandscapeCatalog:
    if version not in CATALOG_VERSIONS:
        raise CatalogError(f"landscape catalogs are versions {CATALOG_VERSIONS}, not {version}")
    loaded = load_catalog(
        directory.joinpath(f"landscape-value.v{version}.json"), landscape_schema(version)
    )
    values = {}
    for entry in loaded.entries:
        fields = dict(entry.values)
        owner, value = str(fields["owner"]), str(fields["value"])
        if owner not in OWNERS:
            raise CatalogError(f"landscape-value {entry.key} bounds an unknown owner {owner!r}")
        if entry.key != f"{owner}_{value}":
            raise CatalogError(f"landscape-value {entry.key} is keyed by its owner and value")
        values[(owner, value)] = ValueBound(
            owner=owner,
            value=value,
            minimum=int(fields["minimum"]),  # type: ignore[arg-type]
            maximum=int(fields["maximum"]),  # type: ignore[arg-type]
            default=int(fields["default"]),  # type: ignore[arg-type]
            required=bool(fields["required"]),
            count=int(fields["count"]),  # type: ignore[arg-type]
            words=tuple(fields["words"]),  # type: ignore[arg-type]
        )
    missing = [f"{owner}_{value}" for owner, value in _NAMED if (owner, value) not in values]
    if missing:
        raise CatalogError(f"landscape-value v{version} does not bound {', '.join(missing)}")
    return LandscapeCatalog(values=values)


@functools.cache
def landscape_catalog(version: int = CATALOG_VERSION) -> LandscapeCatalog:
    """The shipped catalog at ``version`` (the newest unless one is named), read once per
    process."""
    return load_landscape_catalog(version=version)
