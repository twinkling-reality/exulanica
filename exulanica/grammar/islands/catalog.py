"""The sky-island catalog: the bound of every value a sky island states.

One reviewed file, ``assets/catalogs/islands/sky-island-value.vN.json``, read through the
grammar's catalog loader with the volume value schema (:func:`~exulanica.grammar.volumes.catalog.
value_schema`): each entry is ``island_<value>`` with its minimum, maximum, default, whether it
must be stated, and for a value stated in words the words it may take (its default an index into
them), and a reason and a licence. An island's erosion and strata are a volume's sections exactly,
so they are bounded by the volume catalog of the version :data:`VOLUME_CATALOGS` names, not here.

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
    "VOLUME_CATALOGS",
    "IslandCatalog",
    "island_catalog",
    "island_schema",
    "load_island_catalog",
]

CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[3].joinpath("assets", "catalogs", "islands")
)
#: Every version of the sky-island catalog this code reads, and the newest, which reads new
#: islands.
CATALOG_VERSIONS: Final = (1,)
CATALOG_VERSION: Final = 1
#: Each sky-island catalog version and the volume catalog version its islands' erosion and strata
#: are read against and its made volumes are read under.
VOLUME_CATALOGS: Final = {1: 2}
#: The values the reader states by name; a catalog without one of them is refused at loading.
_NAMED: Final = (
    "radius_mm",
    "lobes",
    "rim_mm",
    "depth_mm",
    "underside",
    "fingers",
    "look",
    "top_look",
    "walk",
)


@dataclass(frozen=True, slots=True)
class IslandCatalog:
    #: The version of the file, which an island read against it records.
    version: int
    #: Keyed by value.
    values: Mapping[str, ValueBound]
    #: The volume catalog version its erosion and strata and its made volumes are read against.
    volume_catalog_version: int


def island_schema(version: int) -> CatalogSchema:
    """The sky-island catalog's schema at ``version``: the volume value schema's fields."""
    return dataclasses.replace(value_schema(version), catalog_id="sky-island-value")


def load_island_catalog(
    directory: Path = CATALOG_DIRECTORY, version: int = CATALOG_VERSION
) -> IslandCatalog:
    if version not in CATALOG_VERSIONS:
        raise CatalogError(f"sky-island catalogs are versions {CATALOG_VERSIONS}, not {version}")
    loaded = load_catalog(
        directory.joinpath(f"sky-island-value.v{version}.json"), island_schema(version)
    )
    values = {}
    for entry in loaded.entries:
        fields = dict(entry.values)
        owner, value = str(fields["owner"]), str(fields["value"])
        if owner != "island":
            raise CatalogError(f"sky-island-value {entry.key} bounds an unknown owner {owner!r}")
        if entry.key != f"{owner}_{value}":
            raise CatalogError(f"sky-island-value {entry.key} is keyed by its owner and value")
        if int(fields["count"]) != 1:  # type: ignore[arg-type]
            raise CatalogError(f"sky-island-value {entry.key} is one number or one word")
        values[value] = ValueBound(
            owner=owner,
            value=value,
            minimum=int(fields["minimum"]),  # type: ignore[arg-type]
            maximum=int(fields["maximum"]),  # type: ignore[arg-type]
            default=int(fields["default"]),  # type: ignore[arg-type]
            required=bool(fields["required"]),
            count=1,
            words=tuple(fields["words"]),  # type: ignore[arg-type]
        )
    missing = [f"island_{value}" for value in _NAMED if value not in values]
    if missing:
        raise CatalogError(f"sky-island-value v{version} does not bound {', '.join(missing)}")
    return IslandCatalog(
        version=version, values=values, volume_catalog_version=VOLUME_CATALOGS[version]
    )


@functools.cache
def island_catalog(version: int = CATALOG_VERSION) -> IslandCatalog:
    """The shipped catalog at ``version`` (the newest unless one is named), read once per
    process."""
    return load_island_catalog(version=version)
