"""The society engines and what each can do, stated once, as data.

The newest ``society-engines.v<N>.json`` beside this module is the one statement of which engine
profiles
exist and which capabilities each has: whether a society may still be created with it, whether it
consumes authorised inputs, whether the playback worker may play it, whether it takes directed
actions, model decisions or experiments, whether the world's owner may choose a model for one of
its people, whether a comparison of the models that decide for its people may run it, whether it
can stand on a saved world's own ground, which state shape it writes and how many people it may
hold. It also states which engine a new society over each kind of ground is created with, and,
from its third version, which engine a saved world takes instead where its version holds a thing
its author placed and the host offers societies of things (``creates_holding_things``). From its
fourth version an engine may state no maximum population: the engines a town's society is made
with state none, because how many people a town holds is its homes', admitted by the measured
cost of their minute on the host that makes the society (the society ground catalog).
Everything that used to restate a list of engines derives it from here: the runtime's edit hook,
the repositories, the routes, the selection query's bound parameters and, through a generated
module, the browser's parser. Where a copy cannot derive, because a migration's CHECK or trigger
body is fixed SQL, a test reads the live schema and compares it with this table. A module that
asks what an engine can do asks the table; ``tests/test_society_engine_capabilities.py`` fails a
module that compares an engine's identity where a capability decides.

Every earlier version stays beside it, because evaluation records, the comparison drawing of
their day and the societies made under them name them; tests hold each to this one's rows.
:func:`load_engine_table` reads every version from the second on by its number: what a table may
state is what its version had come to state (an engine for a world holding things from the third,
no maximum population from the fourth), so a new version is a new file and nothing here changes
unless it states something new.

An engine that is not in the table is refused by name everywhere it is looked up, never guessed
to behave like one that is.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from exulanica.world.society import SocietyError

__all__ = [
    "ACTION_ENGINES",
    "COMPARISON_ENGINES",
    "CREATABLE_ENGINES",
    "CREATES",
    "CREATES_HOLDING_THINGS",
    "DECISION_ENGINES",
    "DEFAULT_ENGINE",
    "ENGINES",
    "ENGINES_PATH",
    "EXPERIMENT_ENGINES",
    "INPUT_ENGINES",
    "LEGACY_ENGINES",
    "OWNER_MODEL_CHOICE_ENGINES",
    "PLAYABLE_ENGINES",
    "PRESENCE_ENGINES",
    "SAVED_WORLD_ENGINES",
    "GroundKind",
    "HoldingThings",
    "RetiredSocietyEngine",
    "SocietyEngine",
    "UnknownSocietyEngine",
    "creatable_engine",
    "society_engine",
]

_TABLE_FILE: Final = re.compile(r"society-engines\.v([1-9][0-9]*)\.json")
_TABLE_PROFILE: Final = re.compile(r"exulanica\.society-engines/v([1-9][0-9]*)")
#: The first version this module reads (the first table's shape is held to this one by a test),
#: the first that may state an engine for a world holding things, and the first in which an
#: engine may state no maximum population.
_READ_SINCE: Final = 2
_HOLDING_SINCE: Final = 3
_NO_MAXIMUM_SINCE: Final = 4


def _newest_table() -> tuple[int, Path]:
    """The table this host reads: the highest version among the files beside this module."""
    found = {
        int(match[1]): path
        for path in Path(__file__).parent.glob("society-engines.v*.json")
        if (match := _TABLE_FILE.fullmatch(path.name)) is not None
    }
    version = max(found)
    return version, found[version]


TABLE_VERSION, ENGINES_PATH = _newest_table()
TABLE_PROFILE: Final = f"exulanica.society-engines/v{TABLE_VERSION}"


def _profile_version(profile: object) -> int | None:
    """The version a table's profile names, where this module reads it: from the second up to
    the table this host reads."""
    match = _TABLE_PROFILE.fullmatch(profile) if isinstance(profile, str) else None
    version = None if match is None else int(match[1])
    return version if version is not None and _READ_SINCE <= version <= TABLE_VERSION else None


StateFamily = Literal["legacy", "purposeful", "living", "things"]
_STATE_FAMILIES: Final = ("legacy", "purposeful", "living", "things")
#: The kinds of ground a new society is created over, each with the engine the table names for it:
#: an owned district, a saved world's own ground, and a saved world whose own records state its
#: walking surfaces and homes (a town generated from a recipe).
GroundKind = Literal["district", "saved_world", "town"]
_GROUND_KINDS: Final = ("district", "saved_world", "town")
#: The grounds that are a saved world's own, whose engine must stand on a saved world.
_SAVED_WORLD_GROUNDS: Final = ("saved_world", "town")
_CAPABILITIES: Final = (
    "comparisons",
    "creatable",
    "directed_actions",
    "experiments",
    "model_decisions",
    "owner_model_choice",
    "playback",
    "presence",
    "saved_world",
    "takes_inputs",
)
#: The largest maximum population any engine may state: the living society's bound since
#: migration 0075. An engine that states no maximum states none.
_POPULATION_CEILING: Final = 65_536
#: A society ground's key, as the society ground catalog states one.
_GROUND_KEY: Final = re.compile(r"[a-z][a-z0-9_]*")


class UnknownSocietyEngine(SocietyError, ValueError):
    """An engine profile the table does not state. Named, never treated as a known one."""


class RetiredSocietyEngine(SocietyError, ValueError):
    """An engine the table states but creates nothing with; a stored society of it still reads."""

    code: Final = "society_engine_retired"


@dataclass(frozen=True, slots=True)
class SocietyEngine:
    engine: str
    #: A new society may be created with it. A retired engine's stored societies still read,
    #: advance and replay; nothing new is made with it.
    creatable: bool
    takes_inputs: bool
    playback: bool
    playback_refusal: str | None
    directed_actions: bool
    #: Its history may hold validated model decisions (the schema's decision triggers admit it).
    model_decisions: bool
    #: The world's owner may choose a model that decides for one of its people at the planner's
    #: choice points: the choice is recorded, the host asks it, and a comparison may run it.
    owner_model_choice: bool
    experiments: bool
    #: A comparison may run its people's hour with each of several deciders, models among them.
    comparisons: bool
    #: The person whose world it lives in may send its people away and bring them back.
    presence: bool
    saved_world: bool
    state_family: StateFamily
    population_minimum: int
    #: The most people it may hold; None where the table states no maximum.
    population_maximum: int | None

    def holds(self, population: int) -> bool:
        """Whether this engine may hold a population of this size."""
        return population >= self.population_minimum and (
            self.population_maximum is None or population <= self.population_maximum
        )

    def said(self) -> str:
        """Its population bounds in a refusal's words."""
        if self.population_maximum is None:
            return f"{self.population_minimum} or more"
        return f"{self.population_minimum} to {self.population_maximum}"


def _engine(row: Any, *, unbounded: bool = False) -> SocietyEngine:
    """One row, checked. ``unbounded`` says the table's version lets an engine state no maximum
    population (from the fourth); absent, the maximum is none."""
    fields = {"engine", "population", "playback_refusal", "reason", "state_family", *_CAPABILITIES}
    if not isinstance(row, dict) or set(row) != fields:
        raise ValueError("a society engine row states exactly its capabilities and a reason")
    population = row["population"]
    if (
        not isinstance(row["engine"], str)
        or not row["engine"].startswith("exulanica-society/v")
        or any(type(row[key]) is not bool for key in _CAPABILITIES)
        or row["state_family"] not in _STATE_FAMILIES
        or not isinstance(row["reason"], str)
        or not row["reason"].strip()
        or not isinstance(population, dict)
        or not {"minimum"} <= set(population) <= {"minimum", "maximum"}
        or ("maximum" not in population and not unbounded)
        or type(population["minimum"]) is not int
        or type(population.get("maximum", population["minimum"])) is not int
        or not 1
        <= population["minimum"]
        <= population.get("maximum", population["minimum"])
        <= _POPULATION_CEILING
        or (row["playback"] == (row["playback_refusal"] is not None))
        or (row["playback_refusal"] is not None and not isinstance(row["playback_refusal"], str))
        or (row["saved_world"] and not row["takes_inputs"])
        or (
            (row["directed_actions"] or row["model_decisions"] or row["presence"])
            and not row["takes_inputs"]
        )
        or (row["owner_model_choice"] and not row["model_decisions"])
        or (row["comparisons"] and not row["owner_model_choice"])
    ):
        raise ValueError(f"invalid society engine row {row.get('engine')!r}")
    return SocietyEngine(
        engine=row["engine"],
        creatable=row["creatable"],
        takes_inputs=row["takes_inputs"],
        playback=row["playback"],
        playback_refusal=row["playback_refusal"],
        directed_actions=row["directed_actions"],
        model_decisions=row["model_decisions"],
        owner_model_choice=row["owner_model_choice"],
        experiments=row["experiments"],
        comparisons=row["comparisons"],
        presence=row["presence"],
        saved_world=row["saved_world"],
        state_family=row["state_family"],
        population_minimum=population["minimum"],
        population_maximum=population.get("maximum"),
    )


def _creates(document: Any, engines: Mapping[str, SocietyEngine]) -> dict[GroundKind, str]:
    """Which engine a new society over each kind of ground is created with, and why."""
    if not isinstance(document, dict) or set(document) != set(_GROUND_KINDS):
        raise ValueError(f"creates names exactly the grounds {_GROUND_KINDS}")
    created: dict[GroundKind, str] = {}
    for ground in _GROUND_KINDS:
        row = document[ground]
        if (
            not isinstance(row, dict)
            or set(row) != {"engine", "reason"}
            or not isinstance(row["reason"], str)
            or not row["reason"].strip()
        ):
            raise ValueError(f"creates.{ground} states an engine and a reason")
        engine = engines.get(row["engine"])
        if engine is None or not engine.creatable:
            raise ValueError(f"creates.{ground} names an engine the table creates with")
        if ground in _SAVED_WORLD_GROUNDS and not engine.saved_world:
            raise ValueError(f"creates.{ground} names an engine that stands on a saved world")
        created[ground] = engine.engine  # type: ignore[index]
    return created


@dataclass(frozen=True, slots=True)
class HoldingThings:
    """The engine a saved world's new society takes instead of its ground's where its version holds
    a thing its author placed and the host offers societies of things, over the society grounds
    named here (the society ground catalog's keys): the ones a society of things stands on."""

    engine: str
    grounds: tuple[str, ...]


def _holding_things(document: Any, engines: Mapping[str, SocietyEngine]) -> HoldingThings:
    """The table's ``creates_holding_things``: a creatable engine of things that stands on a saved
    world, the grounds it is created over (lowercase keys, each once, in order) and a reason."""
    if (
        not isinstance(document, dict)
        or set(document) != {"engine", "grounds", "reason"}
        or not isinstance(document["reason"], str)
        or not document["reason"].strip()
    ):
        raise ValueError("creates_holding_things states an engine, its grounds and a reason")
    engine = engines.get(document["engine"])
    if (
        engine is None
        or not engine.creatable
        or not engine.saved_world
        or engine.state_family != "things"
    ):
        raise ValueError(
            "creates_holding_things names a creatable engine of things that stands on a saved world"
        )
    grounds = document["grounds"]
    if (
        not isinstance(grounds, list)
        or not grounds
        or not all(isinstance(key, str) and _GROUND_KEY.fullmatch(key) for key in grounds)
        or grounds != sorted(set(grounds))
    ):
        raise ValueError("creates_holding_things names its grounds once each, in order")
    return HoldingThings(engine=engine.engine, grounds=tuple(grounds))


def load_engine_table(
    path: Path = ENGINES_PATH,
) -> tuple[tuple[SocietyEngine, ...], str, Mapping[GroundKind, str], HoldingThings | None]:
    """Read and check the table: every engine once, in order, a default that exists and may be
    created with, an engine for each kind of ground a new society is created over and, where the
    table states it (from its third version it may), the engine a saved world holding things
    takes."""
    document = json.loads(path.read_text(encoding="utf-8"))
    keys = {"profile", "creates", "default_engine", "engines"}
    version = _profile_version(document.get("profile")) if isinstance(document, dict) else None
    if (
        version is None
        or not keys <= set(document)
        or not set(document) - keys
        <= ({"creates_holding_things"} if version >= _HOLDING_SINCE else set())
        or not isinstance(document["engines"], list)
        or not document["engines"]
    ):
        raise ValueError(
            f"{path.name} is not a society engine table of versions {_READ_SINCE} to "
            f"{TABLE_VERSION}"
        )
    unbounded = version >= _NO_MAXIMUM_SINCE
    engines = tuple(_engine(row, unbounded=unbounded) for row in document["engines"])
    names = [engine.engine for engine in engines]
    if names != sorted(set(names)):
        raise ValueError("society engines are listed once each, in order")
    by_name = {engine.engine: engine for engine in engines}
    default = by_name.get(document["default_engine"])
    if default is None or not default.creatable:
        raise ValueError("the default society engine is not in the table or is retired")
    holding = document.get("creates_holding_things")
    return (
        engines,
        default.engine,
        _creates(document["creates"], by_name),
        None if holding is None else _holding_things(holding, by_name),
    )


ENGINES, DEFAULT_ENGINE, CREATES, CREATES_HOLDING_THINGS = load_engine_table()
_BY_NAME: Final[Mapping[str, SocietyEngine]] = {engine.engine: engine for engine in ENGINES}


def society_engine(name: object) -> SocietyEngine:
    """The engine with this profile, or a refusal that names what was asked for."""
    engine = _BY_NAME.get(name) if isinstance(name, str) else None
    if engine is None:
        raise UnknownSocietyEngine(f"unknown society engine {name!r}")
    return engine


def creatable_engine(name: object) -> SocietyEngine:
    """The engine a new society may be created with, or a refusal naming why it may not be."""
    engine = society_engine(name)
    if not engine.creatable:
        raise RetiredSocietyEngine(f"{engine.engine} is retired: no new society is created with it")
    return engine


def _where(capability: str) -> tuple[str, ...]:
    return tuple(engine.engine for engine in ENGINES if getattr(engine, capability))


#: Engines that consume ordered, authorised inputs and record transition receipts.
INPUT_ENGINES: Final = _where("takes_inputs")
#: Engines that read no input: their state and events are visible without input authorisation.
LEGACY_ENGINES: Final = tuple(engine.engine for engine in ENGINES if not engine.takes_inputs)
#: Engines a new society may be created with.
CREATABLE_ENGINES: Final = _where("creatable")
PLAYABLE_ENGINES: Final = _where("playback")
ACTION_ENGINES: Final = _where("directed_actions")
DECISION_ENGINES: Final = _where("model_decisions")
#: Engines whose world's owner may choose a model for one of its people.
OWNER_MODEL_CHOICE_ENGINES: Final = _where("owner_model_choice")
EXPERIMENT_ENGINES: Final = _where("experiments")
COMPARISON_ENGINES: Final = _where("comparisons")
SAVED_WORLD_ENGINES: Final = _where("saved_world")
PRESENCE_ENGINES: Final = _where("presence")
