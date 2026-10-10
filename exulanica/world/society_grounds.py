"""The grounds a society can stand on, and how many people each holds, as one catalog.

``assets/catalogs/society-ground/society-ground.v<N>.json`` states, once for each kind of ground a
saved world's society is composed over, the facts about that ground which no world states: the
structural composer whose ground it reads, what people walk on it (a lattice over an area, or the
walking surfaces the world's own records state), where a person arrives on it (the spawn the world
states, or by rule the origin of the region the society lives in), what they stand on (a ground the
world states, or a floor the society declares), the navigation profile its routes are recorded
under, the lattice spacing, the area a society declares where the ground states no edge, and how
many people a society over it holds, each with the reason for its figure. The people are a stated
figure, or the people the world's own premises house: then the entry states the most the rule may
produce, or no head count at all and, in its place, what a minute of a society over the ground was
measured to take for each engine (``minute_cost``) and the share of a host's slowest minute a
society may take (``minute_share_milli``, a chosen budget). A navigation profile names one
discretisation and one population, so two grounds that share one state the same figures, and the
catalog refuses two that do not. The society's ground builder
(:mod:`exulanica.world.society_authored_ground`) reads a ground by its navigation and floor forms,
never by its entry's name, and the spacing and declared area; the repository reads the population
when it creates a society (:func:`society_population`), and making a society admits its people by
the cost of their minute on the host that makes it (:func:`admit_people_by_cost`); nothing else
states them.

A stored input records the navigation profile, the spacing and the area it was composed with, so
replay never reads this catalog. A different figure for a ground is therefore a new entry with a
new navigation profile, and an input names which one it was composed under.

A composer or navigation profile the catalog does not state is refused by name, never read as one
it resembles. Pure: no connection and no store. The catalog is read once per process.
"""

from __future__ import annotations

import functools
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from exulanica.grammar.catalogs import CatalogSchema, integer_field, load_catalog, text_field
from exulanica.grammar.errors import CatalogError
from exulanica.world.society_composition import REVIEWED_REACH_MM
from exulanica.world.society_engines import (
    CREATES,
    CREATES_HOLDING_THINGS,
    ENGINES,
    society_engine,
)
from exulanica.world.society_input_policy import UNREACHABLE, WALKING_SURFACES_BY_FAMILY
from exulanica.world.society_minute_cost import (
    ESTIMATE,
    EngineMinuteCost,
    HostMinute,
    PeopleCeiling,
    estimated_minute,
    minute_cost_field,
    minute_costs,
    people_within,
)
from exulanica.world.society_planner import CLEARANCE_MM

__all__ = [
    "CATALOG_DIRECTORY",
    "CATALOG_ID",
    "CATALOG_VERSION",
    "GROUND_ARRIVALS",
    "GROUND_FLOORS",
    "GROUND_NAVIGATIONS",
    "PLACE_DEPENDENCIES",
    "POPULATION_RULES",
    "SocietyGroundKind",
    "SocietyPopulationRefused",
    "UnknownSocietyGround",
    "admit_people_by_cost",
    "created_engine",
    "load_society_grounds",
    "place_dependencies",
    "place_dependency_for",
    "placed_affordance_refusal",
    "record_subjects_for",
    "refuse_population_over_budget",
    "server_runs",
    "society_ground_for_composer",
    "society_ground_for_navigation",
    "society_grounds",
    "society_population",
]

CATALOG_ID: Final = "society-ground"
CATALOG_VERSION: Final = 6
CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "catalogs", CATALOG_ID)
)
#: Where a person arrives on a ground: the spawn its snapshot states, read from the world, or the
#: origin of the region the society lives in, a rule for a world that states none.
GROUND_ARRIVALS: Final = ("spawn", "region_origin")
#: What people stand on: a ground the world's own module states, or a floor the society declares
#: in every region of a world that states none.
GROUND_FLOORS: Final = ("stated", "declared")
#: What people walk: a square lattice over the area a ground states or declares, or the walking
#: surfaces the world's own records state.
GROUND_NAVIGATIONS: Final = ("lattice", "walking_surfaces")
#: How many people a society over a ground holds: the figure its entry states, or the people the
#: world's own premises house, up to the figure its entry states or, where it states none, as many
#: as the measured cost of their minute lets a host run.
POPULATION_RULES: Final = ("stated", "residents")
#: The dependency an input over a ground names the place its people walk under: none for a
#: lattice, else the kind of place the producer of the world's own surfaces makes.
PLACE_DEPENDENCIES: Final = ("none", "city_place", "site_place")
#: A figure a form states none of: a ground that walks its world's surfaces states no lattice and
#: declares no area, and one admitted by the measured cost of a minute states no head count; each
#: says so with this, which its entry check requires.
_STATES_NONE: Final = 0
#: The whole of a minute, in the thousandths a share of it is stated in.
_WHOLE_MILLI: Final = 1000
#: A positive figure with no upper bound of its own: ``_entry_check`` bounds each figure against
#: the others, the navigation clearance and the reviewed reach.
_POSITIVE = integer_field(1, sys.maxsize)


class UnknownSocietyGround(CatalogError):
    """A composer or navigation profile the ground catalog does not state."""


class SocietyPopulationRefused(ValueError):
    """A population a ground's rule derived that no society over the ground may start with."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class SocietyGroundKind:
    """One ground a society can stand on, and the figures a society over it is made with."""

    key: str
    #: The structural composer whose snapshots state this ground.
    composer_key: str
    #: The navigation profile an input composed over this ground records.
    navigation_profile: str
    #: Where a person arrives: one of :data:`GROUND_ARRIVALS`.
    arrival: str
    #: What people stand on: one of :data:`GROUND_FLOORS`.
    floor: str
    #: How many people a society over this ground holds: the stated figure, or under the
    #: ``residents`` rule the most the rule may produce; 0 where the entry states no head count
    #: and admits by ``minute_cost``.
    population: int
    lattice_mm: int
    #: The half extent of the square a society declares where the ground states no edge.
    declared_half_extent_mm: int
    #: What people walk: one of :data:`GROUND_NAVIGATIONS`. The first catalog version walks a
    #: lattice on every ground.
    navigation: str = "lattice"
    #: How the population is found: one of :data:`POPULATION_RULES`.
    population_rule: str = "stated"
    #: The dependency kind its input names its place under: one of :data:`PLACE_DEPENDENCIES`.
    place_dependency: str = "none"
    #: The kinds of the world's own records an activity in its input may name as its subject.
    record_subjects: tuple[str, ...] = ()
    #: The thing kind its population is made of, ``{kind, version, sha256}``: a shipped being the
    #: routine decides for. None below version 5, whose grounds stated no kind.
    population_kind: Mapping[str, Any] | None = None
    #: What a minute of a society over this ground was measured to take, for each engine one is
    #: made with; empty where the entry states a head count. None below version 6.
    minute_cost: tuple[EngineMinuteCost, ...] = ()
    #: The thousandths of a host's slowest minute a society over this ground may take: a chosen
    #: budget; 0 where the entry states a head count.
    minute_share_milli: int = 0


def _figure(values: Mapping[str, object], name: str) -> int:
    """A figure the schema checked is a positive integer, read as one."""
    value = values[name]
    if type(value) is not int:
        raise CatalogError(f"{CATALOG_ID}: {name} is an integer, got {value!r}")
    return value


def _choice(options: tuple[str, ...]) -> Callable[[str, object], str]:
    """A field holding one of ``options``."""

    def check(where: str, value: object) -> str:
        if value not in options:
            raise CatalogError(f"{where} is one of {options}, got {value!r}")
        return str(value)

    return check


def _entry_check(where: str, values: Mapping[str, Any]) -> None:
    saved_world = society_engine(CREATES["saved_world"])
    # Only a version whose schema lets a ground state no head count reads one; its own check
    # holds such a ground to a measured cost.
    if values["population"] != _STATES_NONE and not saved_world.holds(
        _figure(values, "population")
    ):
        raise CatalogError(
            f"{where}: population {values['population']} is outside what the engine a saved "
            f"world is created with holds ({saved_world.said()})"
        )
    if values.get("navigation", "lattice") == "walking_surfaces":
        # A ground whose world states its own walking surfaces walks them: no lattice and no
        # declared area, and a population the world's own premises imply.
        if (values["lattice_mm"], values["declared_half_extent_mm"]) != (_STATES_NONE,) * 2:
            raise CatalogError(
                f"{where}: a ground that walks its world's surfaces states no "
                "lattice and declares no area"
            )
        if values["floor"] != "stated":
            raise CatalogError(
                f"{where}: a world that states its walking surfaces states its floor"
            )
        return
    if values.get("population_rule", "stated") != "stated":
        raise CatalogError(
            f"{where}: only a ground that walks its world's surfaces finds its "
            "population in the world's premises"
        )
    lattice = _figure(values, "lattice_mm")
    if lattice < 1:
        raise CatalogError(f"{where}: a lattice has a positive spacing")
    # Every point of a lattice cell is within half its diagonal of a node, and a person reaches an
    # object from a node only within the reviewed reach.
    if lattice**2 > 2 * REVIEWED_REACH_MM**2:
        raise CatalogError(
            f"{where}: a {lattice} mm lattice leaves points farther than the reviewed reach "
            f"({REVIEWED_REACH_MM} mm) from every node"
        )
    if _figure(values, "declared_half_extent_mm") < CLEARANCE_MM + lattice:
        raise CatalogError(
            f"{where}: a declared area holds a lattice step inside the navigation clearance"
        )


#: A figure a form may state as none (:data:`_STATES_NONE`), bounded against the others by
#: ``_entry_check``.
_NON_NEGATIVE = integer_field(_STATES_NONE, sys.maxsize)


#: What version 2's entries carry, and version 3's: version 3 states the ground of a world made from
#: a world kind (``generated_site``) beside version 2's grounds, in the same fields.
_FIELDS_V2: Final = (
    ("composer_key", text_field),
    ("navigation_profile", text_field),
    ("navigation", _choice(GROUND_NAVIGATIONS)),
    ("navigation_reason", text_field),
    ("arrival", _choice(GROUND_ARRIVALS)),
    ("arrival_reason", text_field),
    ("floor", _choice(GROUND_FLOORS)),
    ("floor_reason", text_field),
    ("population_rule", _choice(POPULATION_RULES)),
    ("population", _POSITIVE),
    ("population_reason", text_field),
    ("lattice_mm", _NON_NEGATIVE),
    ("lattice_reason", text_field),
    ("declared_half_extent_mm", _NON_NEGATIVE),
    ("declared_area_reason", text_field),
    ("reason", text_field),
)


def _record_subjects(where: str, value: object) -> tuple[str, ...]:
    """Record kinds, each a family and a kind (``city.premises``), sorted, none twice."""
    if not isinstance(value, list) or not all(
        isinstance(kind, str) and _RECORD_KIND.fullmatch(kind) for kind in value
    ):
        raise CatalogError(f"{where} is a list of record kinds such as city.premises")
    if value != sorted(set(value)):
        raise CatalogError(f"{where} is sorted with no kind twice")
    return tuple(value)


_RECORD_KIND: Final = re.compile(r"[a-z]+\.[a-z][a-z_]*")


def _entry_check_v4(where: str, values: Mapping[str, Any]) -> None:
    _entry_check(where, values)
    walks_surfaces = values["navigation"] == "walking_surfaces"
    if walks_surfaces != (values["place_dependency"] != "none"):
        raise CatalogError(
            f"{where}: exactly a ground that walks its world's surfaces names the place they make"
        )
    if walks_surfaces != bool(values["record_subjects"]):
        raise CatalogError(
            f"{where}: exactly a ground that walks its world's surfaces names records people use"
        )


#: Version 4 states, for each ground, the dependency its input names its place under and the kinds
#: of the world's own records its people's activities may name, beside version 3's fields.
_FIELDS_V4: Final = (
    *_FIELDS_V2,
    ("place_dependency", _choice(PLACE_DEPENDENCIES)),
    ("place_dependency_reason", text_field),
    ("record_subjects", _record_subjects),
    ("record_subjects_reason", text_field),
)


def _population_kind(where: str, value: object) -> Mapping[str, Any]:
    """A thing kind named by key, version and digest, the shape a thing's kind reference has."""
    if (
        not isinstance(value, dict)
        or set(value) != {"kind", "version", "sha256"}
        or not isinstance(value["kind"], str)
        or type(value["version"]) is not int
        or not isinstance(value["sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
    ):
        raise CatalogError(f"{where} names a thing kind by key, version and digest")
    return dict(value)


def _entry_check_v5(where: str, values: Mapping[str, Any]) -> None:
    _entry_check_v4(where, values)
    # Read here, not at import: the thing kinds read catalogs this module's readers import.
    from exulanica.world.errors import InvalidThingPlacement
    from exulanica.world.placed_things import ThingKindReference, shipped_kind

    try:
        kind = shipped_kind(ThingKindReference(**values["population_kind"]))
    except InvalidThingPlacement as exc:
        raise CatalogError(f"{where}: population_kind: {exc}") from exc
    deciders = kind.document["deciders"]
    if kind.klass != "being" or deciders is None or "routine" not in deciders["allowed"]:
        raise CatalogError(
            f"{where}: population_kind is a being the routine decides for, not a {kind.kind}"
        )


#: Version 5 states, for each ground, the thing kind its population is made of, beside version
#: 4's fields.
_FIELDS_V5: Final = (
    *_FIELDS_V4,
    ("population_kind", _population_kind),
    ("population_kind_reason", text_field),
)


def _entry_check_v6(where: str, values: Mapping[str, Any]) -> None:
    _entry_check_v5(where, values)
    cost, share = values["minute_cost"], values["minute_share_milli"]
    if values["population"] != _STATES_NONE:
        if cost or share != _STATES_NONE:
            raise CatalogError(
                f"{where}: a ground that states a head count states no measured cost of a minute "
                "and no share of one"
            )
        return
    if values["population_rule"] != "residents":
        raise CatalogError(
            f"{where}: only a ground whose people are the world's own states no head count"
        )
    if not cost or not 1 <= share <= _WHOLE_MILLI:
        raise CatalogError(
            f"{where}: a ground that states no head count states the measured cost of a minute "
            f"and the share of a host's slowest minute a society may take, 1 to {_WHOLE_MILLI} "
            "thousandths"
        )
    # Every engine a society over a world's own walking surfaces is made with states its points,
    # so an engine added to the table is measured before a town can be made with it.
    made_with = {
        engine.engine
        for engine in ENGINES
        if engine.creatable
        and engine.saved_world
        and engine.takes_inputs
        and engine.state_family in WALKING_SURFACES_BY_FAMILY
    }
    measured = {engine["engine"] for engine in cost}
    if measured != made_with:
        raise CatalogError(
            f"{where}: minute_cost states the engines a town's society is made with, "
            f"{sorted(made_with)}, not {sorted(measured)}"
        )


#: Version 6 lets a ground whose people are the world's own state no head count (``population``
#: 0) and, in its place, the measured cost of a minute for each engine and the share of a host's
#: slowest minute a society may take, beside version 5's fields.
_FIELDS_V6: Final = (
    *((name, _NON_NEGATIVE if name == "population" else check) for name, check in _FIELDS_V5),
    ("minute_cost", minute_cost_field),
    ("minute_cost_reason", text_field),
    ("minute_share_milli", integer_field(_STATES_NONE, _WHOLE_MILLI)),
    ("minute_share_reason", text_field),
)


_SCHEMAS: Final = MappingProxyType(
    {
        1: CatalogSchema(
            CATALOG_ID,
            1,
            (
                ("composer_key", text_field),
                ("navigation_profile", text_field),
                ("arrival", _choice(GROUND_ARRIVALS)),
                ("arrival_reason", text_field),
                ("floor", _choice(GROUND_FLOORS)),
                ("floor_reason", text_field),
                ("population", _POSITIVE),
                ("population_reason", text_field),
                ("lattice_mm", _POSITIVE),
                ("lattice_reason", text_field),
                ("declared_half_extent_mm", _POSITIVE),
                ("declared_area_reason", text_field),
                ("reason", text_field),
            ),
            entry_check=_entry_check,
        ),
        2: CatalogSchema(CATALOG_ID, 2, _FIELDS_V2, entry_check=_entry_check),
        3: CatalogSchema(CATALOG_ID, 3, _FIELDS_V2, entry_check=_entry_check),
        4: CatalogSchema(CATALOG_ID, 4, _FIELDS_V4, entry_check=_entry_check_v4),
        5: CatalogSchema(CATALOG_ID, 5, _FIELDS_V5, entry_check=_entry_check_v5),
        6: CatalogSchema(CATALOG_ID, 6, _FIELDS_V6, entry_check=_entry_check_v6),
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
            arrival=str(values["arrival"]),
            floor=str(values["floor"]),
            population=_figure(values, "population"),
            lattice_mm=_figure(values, "lattice_mm"),
            declared_half_extent_mm=_figure(values, "declared_half_extent_mm"),
            navigation=str(values.get("navigation", "lattice")),
            population_rule=str(values.get("population_rule", "stated")),
            place_dependency=str(values.get("place_dependency", "none")),
            record_subjects=tuple(values.get("record_subjects", ())),
            # Read-only, since every reader of the loaded grounds shares it: a reader copies it.
            population_kind=(
                MappingProxyType(dict(values["population_kind"]))
                if "population_kind" in values
                else None
            ),
            minute_cost=minute_costs(values.get("minute_cost", [])),
            minute_share_milli=int(values.get("minute_share_milli", _STATES_NONE)),
        )
        for entry in catalog.entries
        for values in (dict(entry.values),)
    )
    composers = [ground.composer_key for ground in grounds]
    if len(set(composers)) != len(composers):
        raise CatalogError(f"{CATALOG_ID}: two grounds name the same composer_key")
    figures: dict[str, tuple[object, ...]] = {}
    for ground in grounds:
        stated = (
            ground.navigation,
            ground.population_rule,
            ground.population,
            ground.lattice_mm,
            ground.declared_half_extent_mm,
            None
            if ground.population_kind is None
            else tuple(sorted(ground.population_kind.items())),
            ground.minute_cost,
            ground.minute_share_milli,
        )
        if figures.setdefault(ground.navigation_profile, stated) != stated:
            raise CatalogError(
                f"{CATALOG_ID}: grounds sharing navigation_profile {ground.navigation_profile} "
                "state different figures for it"
            )
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
    """A ground an input with this navigation profile was composed over, or a refusal. Grounds
    that share a navigation profile state the same figures for it (the loader holds them to it),
    so any of them answers what the profile means: its population, lattice and declared area."""
    for ground in society_grounds():
        if ground.navigation_profile == navigation_profile:
            return ground
    raise UnknownSocietyGround(
        f"no society ground is stated for the navigation profile {navigation_profile!r}"
    )


def place_dependency_for(navigation_profile: str) -> str:
    """The dependency kind an input with this navigation profile names its place under, as its
    ground states it; ``none`` for a profile no ground walks its world's surfaces by."""
    for ground in society_grounds():
        if ground.navigation_profile == navigation_profile:
            return ground.place_dependency
    return "none"


def place_dependencies() -> frozenset[str]:
    """Every dependency kind a ground names a place under."""
    return frozenset(g.place_dependency for g in society_grounds()) - {"none"}


def record_subjects_for(navigation_profile: str) -> tuple[str, ...]:
    """The kinds of a world's own records an input with this navigation profile may name an
    activity of, as its ground states them; none for a profile no ground states."""
    for ground in society_grounds():
        if ground.navigation_profile == navigation_profile:
            return ground.record_subjects
    return ()


def placed_affordance_refusal(ground: SocietyGroundKind) -> str | None:
    """Why the people of a society over this ground never use an object a person places, or None.

    On the walking surfaces a world's own records state, people walk only the records' footways
    and doors, so when an input is composed every placed object with a reviewed affordance is
    recorded as refused by this code (:mod:`exulanica.world.society_walking_surfaces`). On a
    lattice, reach is decided for each object then. A capability read states it per world, by the
    world's ground, never by the name of the world's kind.
    """
    return UNREACHABLE if ground.navigation == "walking_surfaces" else None


def created_engine(ground: SocietyGroundKind, *, holding_things: bool = False) -> str:
    """The engine the engine table creates a new society with over a saved world on this ground.

    The table states one engine for a saved world whose own records state its walking surfaces
    and homes (``town``), and one for a saved world whose people walk a lattice (``saved_world``).
    ``holding_things`` says the world's version holds a thing its author placed and the host offers
    societies of things: over a ground the table's ``creates_holding_things`` names, the society is
    that engine instead, so the beings placed there live with the ground's own people; any other
    ground keeps its engine. A creation still names its engine; this is the one the table says a
    person's own world takes.
    """
    holding = CREATES_HOLDING_THINGS
    if holding_things and holding is not None and ground.key in holding.grounds:
        return holding.engine
    return CREATES["town" if ground.navigation == "walking_surfaces" else "saved_world"]


def society_population(document: Mapping[str, Any]) -> int:
    """How many people a society over a saved world's input holds, by its ground's rule.

    The ground is found by the navigation profile the input records. A stated figure is the
    entry's. Under the ``residents`` rule the input records the population its composition
    derived from the world's premises, and a world whose homes house nobody, or more people than
    the head count its ground states, starts no society rather than a different one: refused by
    name. A ground that states no head count admits its people by the cost of their minute, which
    is asked where the society is made (:func:`admit_people_by_cost`).
    """
    ground = society_ground_for_navigation(document["navigation"]["profile"])
    if ground.population_rule == "stated":
        return ground.population
    recorded = document.get("population")
    if (
        not isinstance(recorded, Mapping)
        or type(size := recorded.get("size")) is not int
        or recorded.get("rule") != ground.population_rule
    ):
        raise SocietyPopulationRefused(
            "population_not_recorded",
            f"an input over the {ground.key} ground records the population its "
            f"{ground.population_rule} rule derived",
        )
    refuse_population(size, ground)
    return size


def refuse_population(size: int, ground: SocietyGroundKind) -> None:
    """Refuse, by name, a population no society over ``ground`` may start with: nobody
    (``world_holds_no_residents``), or more than the head count the ground states
    (``population_over_tick_budget``). A world's composer asks it of each candidate, so a world
    whose society could not start is never made."""
    if size < 1:
        raise SocietyPopulationRefused(
            "world_holds_no_residents",
            "this world's premises offer no place in a home, so its society would hold nobody",
        )
    refuse_population_over_budget(size, ground)


def refuse_population_over_budget(size: int, ground: SocietyGroundKind) -> None:
    """Refuse, by name, a population past the head count ``ground`` states, the most one tick of
    a society over it was measured to hold. A ground that states no head count refuses nothing
    here: its people are admitted by the cost of their minute."""
    if ground.population != _STATES_NONE and size > ground.population:
        raise SocietyPopulationRefused(
            "population_over_tick_budget",
            f"this world's homes hold {size} people, and a society over the {ground.key} ground "
            f"holds at most {ground.population}, the most one of its ticks was measured to hold",
        )


def _engine_cost(ground: SocietyGroundKind, engine: str) -> EngineMinuteCost:
    for cost in ground.minute_cost:
        if cost.engine == engine:
            return cost
    raise SocietyPopulationRefused(
        "minute_cost_not_measured",
        f"no minute of {engine} was measured over the {ground.key} ground, so how many people "
        "this server runs there cannot be said",
    )


def server_runs(
    ground: SocietyGroundKind, engine: str, walking_nodes: int, host: HostMinute
) -> PeopleCeiling | None:
    """The most people ``host`` runs in a society of ``engine`` over a town of ``walking_nodes``
    on ``ground``: the largest population whose minute, as measured and scaled to the host's
    machine, fits the ground's share of the host's slowest minute. Its basis says whether that
    minute was read between measured points or is an estimate past the last one. None for a
    ground that states a head count."""
    if not ground.minute_cost:
        return None
    return people_within(
        _engine_cost(ground, engine),
        walking_nodes,
        host.budget_us(ground.minute_share_milli),
        scale_milli=host.cost_scale_milli,
    )


def admit_people_by_cost(document: Mapping[str, Any], engine: str, host: HostMinute) -> None:
    """Refuse, by name, the first input of a society whose minute ``host`` cannot run.

    For an input over a ground that states no head count: the people it records, over the walking
    nodes it states, are read against the measured cost of a minute of ``engine``, scaled to the
    host's machine, and refused as ``people_over_cost`` where that minute is longer than the
    ground's share of the host's slowest minute. The refusal says what the minute would take,
    what this server gives one and how many people it runs there, each estimate named as one.
    An input over any other ground, and one that states no walking graph (an unavailable one,
    which making the society refuses for its own reason), is admitted here."""
    ground = society_ground_for_navigation(document["navigation"]["profile"])
    walking_nodes = len(document["navigation"]["nodes"])
    if not ground.minute_cost or not walking_nodes:
        return
    people = society_population(document)
    cost = _engine_cost(ground, engine)
    budget_us = host.budget_us(ground.minute_share_milli)
    minute = estimated_minute(cost, people, walking_nodes, scale_milli=host.cost_scale_milli)
    if minute.microseconds <= budget_us:
        return
    runs = people_within(cost, walking_nodes, budget_us, scale_milli=host.cost_scale_milli)
    raise SocietyPopulationRefused(
        "people_over_cost",
        f"a minute of {people} people here takes "
        f"{_said(minute.document()['minute_ms'], 'ms', minute.basis)}, and this server gives a "
        f"minute {budget_us // 1000} ms; it runs {_said(runs.people, 'people', runs.basis)} here",
    )


def _said(figure: int, unit: str, basis: str) -> str:
    """A figure as a refusal says it: an estimate is named as one beside it."""
    if basis == ESTIMATE:
        return f"about {figure} {unit} (an estimate, read past the last measured point)"
    return f"{figure} {unit}"
