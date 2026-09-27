"""The grounds a society can stand on, and how many people each starts with, as one catalog.

``assets/catalogs/society-ground/society-ground.v<N>.json`` states, once for each kind of ground a
saved world's society is composed over, the facts about that ground which no world states: the
structural composer whose ground it reads, the navigation profile its route lattice is recorded
under, the lattice spacing, the area a society declares where the ground states no edge, and how
many people a society over it starts with, each with the reason for its figure. The society's
ground builder (:mod:`exulanica.world.society_authored_ground`) reads the spacing and the declared
area, and the repository reads the population when it creates a society; nothing else states them.

A stored input records the navigation profile, the spacing and the area it was composed with, so
replay never reads this catalog. A different figure for a ground is therefore a new entry with a
new navigation profile, and an input names which one it was composed under.

A composer or navigation profile the catalog does not state is refused by name, never read as one
it resembles. Pure: no connection and no store. The catalog is read once per process.
"""

from __future__ import annotations

import functools
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from exulanica.grammar.catalogs import CatalogSchema, integer_field, load_catalog, text_field
from exulanica.grammar.errors import CatalogError
from exulanica.world.society_composition import REVIEWED_REACH_MM
from exulanica.world.society_engines import CREATES, society_engine
from exulanica.world.society_planner import CLEARANCE_MM

__all__ = [
    "CATALOG_DIRECTORY",
    "CATALOG_ID",
    "CATALOG_VERSION",
    "SocietyGroundKind",
    "UnknownSocietyGround",
    "load_society_grounds",
    "society_ground_for_composer",
    "society_ground_for_navigation",
    "society_grounds",
]

CATALOG_ID: Final = "society-ground"
CATALOG_VERSION: Final = 1
CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "catalogs", CATALOG_ID)
)
#: A positive figure with no upper bound of its own: ``_entry_check`` bounds each figure against
#: the others, the navigation clearance and the reviewed reach.
_POSITIVE = integer_field(1, sys.maxsize)


class UnknownSocietyGround(CatalogError):
    """A composer or navigation profile the ground catalog does not state."""


@dataclass(frozen=True, slots=True)
class SocietyGroundKind:
    """One ground a society can stand on, and the figures a society over it is made with."""

    key: str
    #: The structural composer whose snapshots state this ground.
    composer_key: str
    #: The navigation profile an input composed over this ground records.
    navigation_profile: str
    #: How many people a new society over this ground starts with.
    population: int
    lattice_mm: int
    #: The half extent of the square a society declares where the ground states no edge.
    declared_half_extent_mm: int


def _entry_check(where: str, values: Mapping[str, Any]) -> None:
    saved_world = society_engine(CREATES["saved_world"])
    if not saved_world.holds(int(values["population"])):
        raise CatalogError(
            f"{where}: population {values['population']} is outside what the engine a saved "
            f"world is created with holds ({saved_world.population_minimum} to "
            f"{saved_world.population_maximum})"
        )
    lattice = int(values["lattice_mm"])
    # Every point of a lattice cell is within half its diagonal of a node, and a person reaches an
    # object from a node only within the reviewed reach.
    if lattice**2 > 2 * REVIEWED_REACH_MM**2:
        raise CatalogError(
            f"{where}: a {lattice} mm lattice leaves points farther than the reviewed reach "
            f"({REVIEWED_REACH_MM} mm) from every node"
        )
    if int(values["declared_half_extent_mm"]) < CLEARANCE_MM + lattice:
        raise CatalogError(
            f"{where}: a declared area holds a lattice step inside the navigation clearance"
        )


_SCHEMAS: Final = MappingProxyType(
    {
        1: CatalogSchema(
            CATALOG_ID,
            1,
            (
                ("composer_key", text_field),
                ("navigation_profile", text_field),
                ("population", _POSITIVE),
                ("population_reason", text_field),
                ("lattice_mm", _POSITIVE),
                ("lattice_reason", text_field),
                ("declared_half_extent_mm", _POSITIVE),
                ("declared_area_reason", text_field),
                ("reason", text_field),
            ),
            entry_check=_entry_check,
        )
    }
)


def load_society_grounds(
    directory: Path = CATALOG_DIRECTORY, version: int = CATALOG_VERSION
) -> tuple[SocietyGroundKind, ...]:
    """Read one version of the catalog: each composer and navigation profile named once."""
    claimed = {f"{CATALOG_ID}.v{number}.json" for number in _SCHEMAS}
    present = {path.name for path in directory.glob("*.json")}
    if present != claimed:
        raise CatalogError(
            f"{directory}: files with no schema {sorted(present - claimed)}, "
            f"schemas with no file {sorted(claimed - present)}"
        )
    schema = _SCHEMAS.get(version)
    if schema is None:
        raise CatalogError(f"{CATALOG_ID} v{version} has no schema")
    catalog = load_catalog(directory.joinpath(f"{CATALOG_ID}.v{version}.json"), schema)
    grounds = tuple(
        SocietyGroundKind(
            key=entry.key,
            composer_key=str(values["composer_key"]),
            navigation_profile=str(values["navigation_profile"]),
            population=int(values["population"]),
            lattice_mm=int(values["lattice_mm"]),
            declared_half_extent_mm=int(values["declared_half_extent_mm"]),
        )
        for entry in catalog.entries
        for values in (dict(entry.values),)
    )
    for field in ("composer_key", "navigation_profile"):
        named = [getattr(ground, field) for ground in grounds]
        if len(set(named)) != len(named):
            raise CatalogError(f"{CATALOG_ID}: two grounds name the same {field}")
    return grounds


@functools.cache
def society_grounds() -> tuple[SocietyGroundKind, ...]:
    """The catalog a running host reads, once."""
    return load_society_grounds()


def society_ground_for_composer(composer_key: str) -> SocietyGroundKind:
    """The ground a snapshot made by this composer states, or a refusal naming the composer."""
    for ground in society_grounds():
        if ground.composer_key == composer_key:
            return ground
    raise UnknownSocietyGround(f"no society ground is stated for the composer {composer_key!r}")


def society_ground_for_navigation(navigation_profile: str) -> SocietyGroundKind:
    """The ground an input with this navigation profile was composed over, or a refusal."""
    for ground in society_grounds():
        if ground.navigation_profile == navigation_profile:
            return ground
    raise UnknownSocietyGround(
        f"no society ground is stated for the navigation profile {navigation_profile!r}"
    )
