"""The worlds a person may make: a specification schema, its presets, and the one gate every
specification passes.

``assets/catalogs/world-recipes/`` holds three kinds of file, each a versioned data object:

* ``world-specification.v<N>.json``, a **specification schema**: every value a world's
  specification states, keyed by the grammar's own parameter name, or by ``grammar_id`` and
  ``grammar_version``, the specification's own fields. Each states a label in plain words, the
  range a person may choose from (``minimum``, ``maximum`` and ``step`` for a number,
  ``choices`` for a key; a number states no choices and a key no range) and the measured or
  authored reason for it. A value whose range holds one value is fixed. A value may also state
  when another narrows it (``requires``: while that value lies from one figure to another, this
  one lies in a narrower range, and why), so two values that cannot make a world together are
  never offered together. The kind and unit of each value are the grammar descriptor's own, and
  every range lies inside the descriptor's, both checked when the schema is read, so a schema never
  admits a value the grammar would refuse as undeclared.
* ``world-recipe.v<N>.json``, the **presets**: each a named point in a schema, stating the value of
  every adjustable parameter, the composer that builds it (a module of
  :mod:`exulanica.world.composers`, named by the key a structural snapshot records, and the version
  of it the preset was reviewed under) and how many seed candidates a world tries, with why. Version
  1's recipes each named a specification file under ``specifications/``, pinned by its digest; they
  are read for the receipts of the worlds made from them and are no longer offered.
* ``specifications/``, the files version 1's recipes name.

**The gate.** A person, an open model drafting a specification on a person's behalf and an API
client all ask for a world the same way: a preset's key and, optionally, values for its adjustable
parameters. :func:`town_recipe` checks every value against the preset's schema and refuses by name
(:class:`SpecificationRefused`): a key the schema does not state, or states fixed
(``specification_value_unknown``), a value outside its range, off its step or of another kind
(``specification_value_out_of_range``), each naming the key, the value and the range, and two
values the schema does not admit together (``specification_values_disagree``), naming both keys and
the narrowed range. What passes
is a :class:`WorldRecipe` whose specification is the schema's fixed values with the preset's and the
asker's, bound at the grammar's top cascade level; the composer then generates it or refuses it by
name. :func:`specification_document` is every schema value, preset and refusal as one document:
what ``GET /worlds/specification`` serves and a page renders.

Pure: no connection and no store.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import itertools
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, cast

from exulanica.grammar.catalogs import (
    CatalogSchema,
    FieldValue,
    ReferenceField,
    integer_field,
    key_list_field,
    load_catalog,
    text_field,
)
from exulanica.grammar.documents import read_json
from exulanica.grammar.errors import (
    CatalogError,
    InvalidParameterError,
    UnregisteredGrammarError,
)
from exulanica.grammar.grammars.city.catalogs import entry_fields, load_city_catalogs
from exulanica.grammar.grammars.specified import REGISTRY, Specification, specification
from exulanica.grammar.parameters import CLOSED_VOCABULARY
from exulanica.world.society_controls import DEFAULT_BASE_TICK_INTERVAL_MS, SPEEDS

__all__ = [
    "CANDIDATES_MAXIMUM",
    "CATALOG_DIRECTORY",
    "CATALOG_ID",
    "CATALOG_VERSION",
    "REFUSALS",
    "SCHEMA_ID",
    "SPECIFICATION_FIELDS",
    "SPECIFICATION_PROFILE",
    "TILES_MAXIMUM",
    "Requirement",
    "SpecificationRefused",
    "SpecificationSchema",
    "SpecificationValue",
    "UnknownWorldRecipe",
    "WorldRecipe",
    "load_specification_schemas",
    "load_world_recipes",
    "read_specification",
    "specification_document",
    "specification_tiles",
    "tick_budget_ms",
    "town_recipe",
    "world_recipe",
    "world_recipes",
]

CATALOG_ID: Final = "world-recipe"
#: The presets a running server offers.
CATALOG_VERSION: Final = 4
#: The specification schemas' catalog: what a preset's values, and a person's, are checked against.
SCHEMA_ID: Final = "world-specification"
#: The newest schema the directory holds; every earlier one stays for the presets that name it.
SCHEMA_VERSION: Final = 2
#: The profile of the document :func:`specification_document` builds.
SPECIFICATION_PROFILE: Final = "exulanica.world-specification/v1"
CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "catalogs", "world-recipes")
)
SPECIFICATIONS: Final = "specifications"
#: The specification's own fields a schema states beside the grammar's parameters: the grammar
#: and its version, which name the descriptor every other value is checked against.
SPECIFICATION_FIELDS: Final = ("grammar_id", "grammar_version")
#: The cascade level a schema's values are bound at: the top one, so each holds for every
#: district, block, lot and building of the world.
BINDING_LEVEL: Final = "city"
#: How a specification file is named, without its ``.json``: a key and a version.
_SPECIFICATION_NAME: Final = re.compile(r"[a-z][a-z0-9-]*\.v[1-9][0-9]*")
#: How a schema is named where a preset cites it: its catalog id and version.
_SCHEMA_NAME: Final = re.compile(rf"{SCHEMA_ID}\.v[1-9][0-9]*")
#: How a composer is named: the key a snapshot records, which names its module with ``-`` read as
#: ``_``.
_COMPOSER_NAME: Final = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")
#: The most tiles a recipe may state. A workspace holds at most the world-count policy's limit of
#: generated worlds and no route deletes one, so that limit times this figure bounds every tile
#: bake a workspace can cause (``world-count-policy.v2.json`` says so beside the limit). Four is a
#: town of two tiles by two: one bake of the one-tile town took 13.3 s on the development machine,
#: so four keep one world's bakes near a minute of one worker's time.
TILES_MAXIMUM: Final = 4
#: The most seed candidates one world may try. Generation runs in the request that makes a
#: world, so each recipe states its own count and why its worst case fits a request; this bound
#: only keeps a mistaken entry from turning one request into an unbounded search.
CANDIDATES_MAXIMUM: Final = 16
#: The largest figure a schema's range may state: a 32-bit integer, which covers every declared
#: parameter's range.
_FIGURE_MAXIMUM: Final = 2**31 - 1
#: How much of the shortest wait between a town society's ticks at play one tick may take, as the
#: divisor of that wait: a tenth, so a tick leaves nine tenths of its interval to everything else
#: the application's process does while the town plays at its fastest speed.
TICK_SHARE_DIVISOR: Final = 10
#: Why the specification's ranges hold every town inside the tick budget, as measured.
TICK_BUDGET_REASON: Final = (
    "Measured with scripts/measure_generated_world.py inside the machine-wide quiet slot, over 8 "
    "market towns three tiles long with cross streets 140 m apart, two to four storeys, one high "
    "street, local cross streets and every share even, the values whose towns held the most places "
    "over this schema's sweep (walking graphs of up to 962 nodes in those towns): one purposeful "
    "tick of the most people its society ground admits, 128, took 130 ms at the median and 159 ms "
    "at the 95th percentile on the largest graph, and the most people any of those towns held, "
    "90, took 90 and 131 ms."
)
#: Every refusal a request for a world can meet, with its status and what it means: the codes a
#: page, a model and an API client act on, served in :func:`specification_document`.
REFUSALS: Final = (
    ("unknown_world_recipe", 404, "No preset has this key."),
    (
        "specification_value_unknown",
        422,
        "The schema states no adjustable value with this key: it is not a value a world states, "
        "or the schema fixes it (its reason says why).",
    ),
    (
        "specification_value_out_of_range",
        422,
        "The value is outside the range the schema states for its key, off its step, or not the "
        "kind of value the key takes; the refusal names the key, the value and the range.",
    ),
    (
        "specification_values_disagree",
        422,
        "Two values the schema does not admit together: while one lies in a stated range, the "
        "other's range narrows (its ``requires`` says when and why). The refusal names both keys, "
        "both values and the narrowed range.",
    ),
    (
        "generated_world_refused",
        409,
        "No seed candidate made a world from these values: the grammar refused each, or its homes "
        "held nobody or more people than one tick of its society holds. Every candidate's refusal "
        "is named.",
    ),
    (
        "world_limit_reached",
        409,
        "The workspace already holds as many generated worlds as the world-count policy allows.",
    ),
)


def _shown(value: object) -> str:
    """A value as a refusal shows it: as JSON writes it, the form the request carried it in."""
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)


class UnknownWorldRecipe(CatalogError):
    """A recipe key the catalog does not state."""

    code: Final = "unknown_world_recipe"


class SpecificationRefused(ValueError):
    """A value a specification may not state, refused by name with its key, the value and the
    range the schema states for it (none for a key the schema does not state)."""

    def __init__(
        self,
        code: str,
        key: str,
        value: object,
        detail: str,
        allowed: SpecificationValue | None,
        *,
        other: tuple[str, object] | None = None,
        narrowed: Requirement | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.key = key
        self.value = value
        self.detail = detail
        self.allowed = allowed
        #: For values that disagree: the other key and its value, and the requirement it narrows by.
        self.other = other
        self.narrowed = narrowed

    def document(self) -> dict[str, Any]:
        """What a caller is told: the code, the sentence, the key, the value and the range, and for
        values that disagree the other key and value and the narrowed range."""
        stated: dict[str, Any] = {
            "code": self.code,
            "detail": self.detail,
            "key": self.key,
            "value": self.value,
            "range": None if self.allowed is None else self.allowed.range_document(),
        }
        if self.other is not None and self.narrowed is not None and self.allowed is not None:
            stated["with"] = {"key": self.other[0], "value": self.other[1]}
            stated["range"] = {
                "minimum": self.narrowed.minimum,
                "maximum": self.narrowed.maximum,
                "step": self.allowed.step,
            }
        return stated


@dataclass(frozen=True, slots=True)
class Requirement:
    """While the value ``when`` lies from ``start`` to ``end``, the value that states this lies from
    ``minimum`` to ``maximum`` (on its own step), for ``reason``."""

    when: str
    start: int
    end: int
    minimum: int
    maximum: int
    reason: str

    def applies(self, values: Mapping[str, object]) -> bool:
        other = values.get(self.when)
        return type(other) is int and self.start <= other <= self.end

    def document(self) -> dict[str, Any]:
        return {
            "when": self.when,
            "from": self.start,
            "to": self.end,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class SpecificationValue:
    """One value a specification states: its words, its range in a schema and why."""

    key: str
    label: str
    #: ``integer`` or ``choice``, and the unit it is stated in: the grammar descriptor's.
    kind: str
    unit: str
    #: A number's range: every value from ``minimum`` to ``maximum`` in steps of ``step``.
    minimum: int
    maximum: int
    step: int
    #: A key's range: the keys it may take.
    choices: tuple[str, ...]
    reason: str
    #: When another value narrows this one's range, and why.
    requires: tuple[Requirement, ...] = ()
    #: Each choice in words, in the choices' order: its label in the catalog the grammar's
    #: vocabulary for it names; empty for a choice whose options only its descriptor lists.
    choice_labels: tuple[str, ...] = ()

    @property
    def adjustable(self) -> bool:
        """Whether its range holds more than one value."""
        if self.kind == "choice":
            return len(self.choices) > 1
        return self.minimum < self.maximum

    def fixed(self) -> int | str:
        """The one value a fixed range holds."""
        if self.adjustable:
            raise ValueError(f"{self.key} is adjustable")
        return self.choices[0] if self.kind == "choice" else self.minimum

    def range_words(self) -> str:
        """The range in words, as a refusal states it."""
        if self.kind == "choice":
            return "one of " + ", ".join(self.choices)
        if not self.adjustable:
            return f"{self.minimum} {self.unit}, fixed"
        return f"{self.minimum} to {self.maximum} {self.unit} in steps of {self.step}"

    def range_document(self) -> dict[str, Any]:
        if self.kind == "choice":
            return {"choices": list(self.choices)}
        return {"minimum": self.minimum, "maximum": self.maximum, "step": self.step}

    def refused(self, value: object) -> SpecificationRefused | None:
        """Why ``value`` is outside this range, by name, or None when it is inside."""
        if self.kind == "choice":
            inside = type(value) is str and value in self.choices
        else:
            inside = (
                type(value) is int
                and self.minimum <= value <= self.maximum
                and (value - self.minimum) % self.step == 0
            )
        if inside:
            return None
        return SpecificationRefused(
            "specification_value_out_of_range",
            self.key,
            value,
            f"{self.key} ({self.label.lower()}) is {_shown(value)}; this schema admits "
            f"{self.range_words()}",
            self,
        )

    def document(self) -> dict[str, Any]:
        """What a page, a model and an API client read of it."""
        stated: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "unit": self.unit,
            "adjustable": self.adjustable,
            **self.range_document(),
            "requires": [requirement.document() for requirement in self.requires],
            "reason": self.reason,
        }
        if self.choice_labels:
            stated["choice_labels"] = list(self.choice_labels)
        if not self.adjustable:
            stated["value"] = self.fixed()
        return stated


#: How each grammar's vocabularies are read, by grammar id: every catalog a version reads, by
#: catalog id. A choice whose vocabulary is a catalog is served with each key's label from it.
_VOCABULARY_CATALOGS: Final = {
    "city": lambda version: {
        catalog.catalog_id: catalog for catalog in load_city_catalogs(grammar_version=version)
    },
}


def _choice_labels(
    grammar_id: str, grammar_version: int, vocabulary: str, choices: tuple[str, ...]
) -> tuple[str, ...]:
    """Each choice's label in the catalog ``vocabulary`` names, or none for a closed one."""
    if vocabulary == CLOSED_VOCABULARY or not choices:
        return ()
    reader = _VOCABULARY_CATALOGS.get(grammar_id)
    if reader is None:
        raise CatalogError(f"no reader states the words for {grammar_id}'s vocabulary {vocabulary}")
    catalog = reader(grammar_version)[vocabulary]
    return tuple(str(entry_fields(catalog, choice)["label"]) for choice in choices)


@dataclass(frozen=True, slots=True)
class SpecificationSchema:
    """One version of the specification schema: its grammar and every value it states."""

    #: How presets cite it: ``world-specification.v<N>``.
    name: str
    catalog_version: int
    #: The SHA-256 of the schema file's bytes, the pin every preset and receipt carries.
    sha256: str
    grammar_id: str
    grammar_version: int
    #: Every grammar parameter it states, in the catalog's order.
    values: tuple[SpecificationValue, ...]
    #: The two specification fields, as the schema states them.
    fields: tuple[SpecificationValue, ...]

    def value(self, key: str) -> SpecificationValue | None:
        return next((value for value in self.values if value.key == key), None)

    def adjustable(self) -> tuple[SpecificationValue, ...]:
        return tuple(value for value in self.values if value.adjustable)

    def reference(self) -> dict[str, object]:
        return {"catalog_id": SCHEMA_ID, "catalog_version": self.catalog_version}

    def check(self, values: Mapping[str, object], *, complete: bool) -> dict[str, int | str]:
        """``values``, each held to its range, or the first refusal by name, in key order.

        ``complete`` asks for every adjustable value, as a preset states them; a person's values
        change only the ones they name.
        """
        if not isinstance(values, Mapping):
            raise SpecificationRefused(
                "specification_value_unknown", "", values, "values are named by key", None
            )
        for key in sorted(values, key=str):
            stated = self.value(key) if type(key) is str else None
            if stated is None or not stated.adjustable:
                reason = (
                    "this schema states no value with that key"
                    if stated is None
                    else f"this schema fixes it at {_shown(stated.fixed())}: {stated.reason}"
                )
                raise SpecificationRefused(
                    "specification_value_unknown", str(key), values[key], f"{key}: {reason}", stated
                )
            refusal = stated.refused(values[key])
            if refusal is not None:
                raise refusal
        if complete:
            missing = [value.key for value in self.adjustable() if value.key not in values]
            if missing:
                raise CatalogError(f"a preset states every adjustable value, and not {missing}")
        return {key: cast(int | str, values[key]) for key in sorted(values)}

    def check_together(self, values: Mapping[str, object]) -> None:
        """Refuse, by name, the first pair of ``values`` the schema does not admit together: a value
        outside the range another value narrows it to (``specification_values_disagree``). Each
        value is held to its own range first (:meth:`check`); this reads the values a world would
        be made with, a preset's with the asker's in place."""
        for stated in self.values:
            for requirement in stated.requires:
                if not requirement.applies(values):
                    continue
                chosen = values.get(stated.key)
                if type(chosen) is int and requirement.minimum <= chosen <= requirement.maximum:
                    continue
                other = self.value(requirement.when)
                label = other.label.lower() if other is not None else requirement.when
                raise SpecificationRefused(
                    "specification_values_disagree",
                    stated.key,
                    chosen,
                    f"{stated.key} ({stated.label.lower()}) is {_shown(chosen)} and "
                    f"{requirement.when} ({label}) is {_shown(values[requirement.when])}; with "
                    f"that value this schema admits {requirement.minimum} to "
                    f"{requirement.maximum} {stated.unit} in steps of {stated.step}: "
                    f"{requirement.reason}",
                    stated,
                    other=(requirement.when, values[requirement.when]),
                    narrowed=requirement,
                )

    def specification(self, values: Mapping[str, int | str]) -> dict[str, Any]:
        """The specification ``values`` make with the schema's fixed values, in the shape
        ``POST /world-generation/worlds`` accepts, every value bound at the top cascade level."""
        bound = {
            value.key: values[value.key] if value.adjustable else value.fixed()
            for value in self.values
        }
        return {
            "grammar_id": self.grammar_id,
            "grammar_version": self.grammar_version,
            "bindings": [{"level": BINDING_LEVEL, "values": dict(sorted(bound.items()))}],
        }


@dataclass(frozen=True, slots=True)
class WorldRecipe:
    """One kind of world a person may make, and what the server makes it from."""

    key: str
    label: str
    #: The structural composer that builds a world of this recipe: the key its snapshot records.
    composer_key: str
    composer_version: int
    #: The specification's name and SHA-256: for a version 1 recipe its file under
    #: ``specifications/``; for a preset, the schema it is a point in and that schema's file.
    specification_name: str
    specification_sha256: str
    #: The specification, in the shape ``POST /world-generation/worlds`` accepts.
    specification: Any
    #: How many seed candidates a world of this recipe tries, in order, before it is refused.
    candidates: int
    #: The tiles a world of this recipe covers, as its specification's coverage rule counts them.
    tiles: tuple[tuple[int, int], ...]
    #: The catalog version the recipe was read from; a world records it.
    catalog_version: int
    #: A preset's adjustable values, the preset's own or those a request made it with; None for a
    #: version 1 recipe, which names a whole specification file instead.
    values: Mapping[str, int | str] | None = None

    def reference(self) -> dict[str, object]:
        """What a world made from this recipe records of it; a world's seed is drawn from it, so
        two worlds made from one preset with other values are other worlds."""
        stated: dict[str, object] = {
            "catalog_id": CATALOG_ID,
            "catalog_version": self.catalog_version,
            "key": self.key,
            "specification": self.specification_name,
            "specification_sha256": self.specification_sha256,
        }
        if self.values is not None:
            stated["values"] = dict(self.values)
        return stated


def specification_tiles(document: Any) -> tuple[tuple[int, int], ...]:
    """The tiles a specification covers, counted by its grammar's coverage rule from the values its
    bindings state, before anything is generated; one that leaves a counted value unbound is
    refused by name."""
    if not isinstance(document, dict) or set(document) != {
        "grammar_id",
        "grammar_version",
        "bindings",
    }:
        raise CatalogError("a specification states grammar_id, grammar_version and bindings only")
    spec = read_specification(document)
    values: dict[str, object] = {}
    for binding in spec.bindings:
        values.update(binding.values)
    unbound = [name for name in spec.coverage.reads if name not in values]
    if unbound:
        raise CatalogError(f"a recipe's specification binds {', '.join(unbound)} itself")
    return tuple(spec.coverage.tiles(values))  # type: ignore[arg-type]


def read_specification(document: Any) -> Specification:
    """A specification file read against the registered grammar it names."""
    try:
        return specification(
            document["grammar_id"],
            document["grammar_version"],
            [(binding["level"], binding["values"]) for binding in document["bindings"]],
        )
    except (KeyError, TypeError) as exc:
        raise CatalogError(f"a specification is malformed: {exc}") from exc


def _pins(directory: Path, pattern: re.Pattern[str], glob: str) -> dict[str, dict[str, str]]:
    """Every file ``glob`` finds, named without ``.json`` and pinned by its bytes' SHA-256."""
    pins: dict[str, dict[str, str]] = {}
    for path in sorted(directory.glob(glob)):
        name = path.name.removesuffix(".json")
        if pattern.fullmatch(name) is None:
            raise CatalogError(f"{path.name} is not named <key>.v<N>.json")
        pins[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return pins


def _composer(where: str, value: object) -> str:
    name = str(text_field(where, value))
    if _COMPOSER_NAME.fullmatch(name) is None:
        raise CatalogError(
            f"{where} names a composer by its lowercase hyphenated key, not {name!r}"
        )
    return name


def _values_field(where: str, value: object) -> FieldValue:
    """A preset's values: each adjustable value's key and what it is, held to the schema later."""
    if not isinstance(value, dict) or not value:
        raise CatalogError(f"{where} is an object naming values by key")
    for key, item in value.items():
        if type(item) not in (int, str):
            raise CatalogError(f"{where}.{key} is a whole number or a key")
    return cast(FieldValue, dict(value))


#: What a requirement states, each by the name it is written with.
_REQUIREMENT_KEYS: Final = frozenset({"when", "from", "to", "minimum", "maximum", "reason"})


def _requires_field(where: str, value: object) -> FieldValue:
    """A value's requirements: while another value lies from one figure to another, this one lies
    in a narrower range, and why. Held to the values they name once every value is read."""
    if not isinstance(value, list):
        raise CatalogError(f"{where} is a list of requirements")
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != _REQUIREMENT_KEYS:
            raise CatalogError(f"{where}[{index}] states exactly {sorted(_REQUIREMENT_KEYS)}")
        for name in ("from", "to", "minimum", "maximum"):
            if type(item[name]) is not int:
                raise CatalogError(f"{where}[{index}].{name} is a whole number")
        text_field(f"{where}[{index}].reason", item["reason"])
        text_field(f"{where}[{index}].when", item["when"])
    return cast(FieldValue, list(value))


def _requirements(
    where: str, stated: SpecificationValue, raw: object, by_key: Mapping[str, SpecificationValue]
) -> tuple[Requirement, ...]:
    """``stated``'s requirements, each naming another adjustable number, a span inside that
    number's range and a narrower range inside ``stated``'s own, on both steps; two spans of one
    number never meet, so at most one requirement is in force for any values, as a page reads it."""
    found = []
    for index, item in enumerate(cast(list[dict[str, Any]], raw)):
        at = f"{where} requires[{index}]"
        other = by_key.get(item["when"])
        if other is None or other.key == stated.key or not other.adjustable:
            raise CatalogError(f"{at} names {item['when']!r}, which is no other adjustable value")
        if "choice" in (other.kind, stated.kind):
            raise CatalogError(f"{at}: a requirement narrows one number by another")

        def inside(value: SpecificationValue, low: int, high: int) -> bool:
            return (
                value.minimum <= low <= high <= value.maximum
                and (low - value.minimum) % value.step == 0
                and (high - value.minimum) % value.step == 0
            )

        if not inside(other, item["from"], item["to"]):
            raise CatalogError(f"{at} spans {item['when']} outside its range or step")
        if not inside(stated, item["minimum"], item["maximum"]):
            raise CatalogError(f"{at} narrows {stated.key} outside its range or step")
        found.append(
            Requirement(
                when=item["when"],
                start=item["from"],
                end=item["to"],
                minimum=item["minimum"],
                maximum=item["maximum"],
                reason=item["reason"],
            )
        )
    for first, second in itertools.combinations(found, 2):
        if first.when == second.when and first.start <= second.end and second.start <= first.end:
            raise CatalogError(
                f"{where} states two requirements in force together when {first.when} is "
                f"{max(first.start, second.start)}"
            )
    return tuple(found)


def _schema_entry_check(where: str, values: dict[str, FieldValue]) -> None:
    """A value states a range of numbers or a list of keys, never both."""
    minimum, maximum, step = (
        int(cast(int, values[name])) for name in ("minimum", "maximum", "step")
    )
    choices = values["choices"]
    if choices:
        if (minimum, maximum, step) != (0, 0, 0):
            raise CatalogError(f"{where} states choices, so its minimum, maximum and step are 0")
        return
    if step < 1 or minimum > maximum or (maximum - minimum) % step:
        raise CatalogError(
            f"{where} states a range from its minimum to its maximum in whole steps of at least 1"
        )


def _schema_catalog(version: int) -> CatalogSchema:
    figure = integer_field(0, _FIGURE_MAXIMUM)
    return CatalogSchema(
        SCHEMA_ID,
        version,
        (
            ("label", text_field),
            ("minimum", figure),
            ("maximum", figure),
            ("step", figure),
            ("choices", key_list_field),
            ("requires", _requires_field),
            ("reason", text_field),
        ),
        entry_check=_schema_entry_check,
    )


def _read_schema(directory: Path, version: int, sha256: str) -> SpecificationSchema:
    """A schema file, read and held to the grammar descriptor it names."""
    catalog = load_catalog(
        directory.joinpath(f"{SCHEMA_ID}.v{version}.json"), _schema_catalog(version)
    )
    stated = []
    requires: dict[str, object] = {}
    for entry in catalog.entries:
        fields = dict(entry.values)
        requires[entry.key] = fields["requires"]
        stated.append(
            (
                entry.key,
                str(fields["label"]),
                int(cast(int, fields["minimum"])),
                int(cast(int, fields["maximum"])),
                int(cast(int, fields["step"])),
                tuple(cast(tuple[str, ...], fields["choices"])),
                str(fields["reason"]),
            )
        )
    by_key = {row[0]: row for row in stated}
    missing = [name for name in SPECIFICATION_FIELDS if name not in by_key]
    if missing:
        raise CatalogError(f"{SCHEMA_ID}.v{version} states no {', '.join(missing)}")
    grammar_id_row, version_row = by_key["grammar_id"], by_key["grammar_version"]
    if len(grammar_id_row[5]) != 1 or version_row[5] or version_row[2] != version_row[3]:
        raise CatalogError(f"{SCHEMA_ID}.v{version} fixes its grammar and that grammar's version")
    grammar_id, grammar_version = grammar_id_row[5][0], version_row[2]
    try:
        grammar = REGISTRY.get(grammar_id, grammar_version)
    except UnregisteredGrammarError as exc:
        raise CatalogError(
            f"{SCHEMA_ID}.v{version} names grammar {grammar_id} version {grammar_version}, which "
            f"this server does not register: {exc}"
        ) from exc
    fields_stated: list[SpecificationValue] = []
    values: list[SpecificationValue] = []
    for key, label, minimum, maximum, step, choices, reason in stated:
        if key in SPECIFICATION_FIELDS:
            kind, unit = ("choice", "key") if key == "grammar_id" else ("integer", "count")
            fields_stated.append(
                SpecificationValue(key, label, kind, unit, minimum, maximum, step, choices, reason)
            )
            continue
        try:
            declared = grammar.parameters.get(key)
        except InvalidParameterError as exc:
            raise CatalogError(f"{SCHEMA_ID}.v{version} {key}: {exc}") from exc
        where = f"{SCHEMA_ID}.v{version} {key}"
        if declared.kind == "choice":
            if not choices or not set(choices) <= set(declared.options):
                raise CatalogError(
                    f"{where} is a choice of {list(declared.options)}, and states {list(choices)}"
                )
        elif choices or not declared.minimum <= minimum <= maximum <= declared.maximum:
            raise CatalogError(
                f"{where} is a number from {declared.minimum} to {declared.maximum}, and states "
                f"{minimum} to {maximum}"
            )
        values.append(
            SpecificationValue(
                key,
                label,
                declared.kind,
                declared.unit,
                minimum,
                maximum,
                step,
                choices,
                reason,
                choice_labels=_choice_labels(
                    grammar_id, grammar_version, declared.vocabulary, choices
                ),
            )
        )
    by_key = {value.key: value for value in values}
    for field in fields_stated:
        if requires[field.key]:
            raise CatalogError(f"{SCHEMA_ID}.v{version} {field.key} is fixed and requires nothing")
    values = [
        dataclasses.replace(
            value,
            requires=_requirements(
                f"{SCHEMA_ID}.v{version} {value.key}", value, requires[value.key], by_key
            ),
        )
        for value in values
    ]
    return SpecificationSchema(
        name=f"{SCHEMA_ID}.v{version}",
        catalog_version=version,
        sha256=sha256,
        grammar_id=grammar_id,
        grammar_version=grammar_version,
        values=tuple(values),
        fields=tuple(fields_stated),
    )


def load_specification_schemas(
    directory: Path = CATALOG_DIRECTORY,
) -> MappingProxyType[str, SpecificationSchema]:
    """Every schema the directory holds, by the name a preset cites it by."""
    pins = _pins(directory, _SCHEMA_NAME, f"{SCHEMA_ID}.v*.json")
    return MappingProxyType(
        {
            name: _read_schema(directory, int(name.rsplit(".v", 1)[1]), pin["sha256"])
            for name, pin in pins.items()
        }
    )


def _recipe_catalog(version: int, pins: Mapping[str, Mapping[str, str]]) -> CatalogSchema:
    if version == 1:
        cited: tuple[tuple[str, Any], ...] = (
            ("specification", ReferenceField("a world specification", _SPECIFICATION_NAME, pins)),
        )
    else:
        cited = (
            ("specification", ReferenceField("a specification schema", _SCHEMA_NAME, pins)),
            ("values", _values_field),
        )
    return CatalogSchema(
        CATALOG_ID,
        version,
        (
            ("label", text_field),
            ("composer", _composer),
            ("composer_version", integer_field(1, 1_000)),
            *cited,
            ("candidates", integer_field(1, CANDIDATES_MAXIMUM)),
            ("candidates_reason", text_field),
            ("tiles", integer_field(1, TILES_MAXIMUM)),
            ("reason", text_field),
        ),
    )


def _claimed_files(directory: Path, catalog_version: int) -> None:
    """The directory holds the catalogs this module reads and nothing it does not."""
    present = {path.name for path in directory.glob("*.json")}
    claimed = {f"{CATALOG_ID}.v{n}.json" for n in range(1, CATALOG_VERSION + 1)} | {
        f"{SCHEMA_ID}.v{n}.json" for n in range(1, SCHEMA_VERSION + 1)
    }
    wanted = f"{CATALOG_ID}.v{catalog_version}.json"
    if not present <= claimed or wanted not in present:
        raise CatalogError(
            f"{directory}: files with no schema {sorted(present - claimed)}, and "
            f"{wanted} {'is' if wanted in present else 'is not'} present"
        )


def load_world_recipes(
    directory: Path = CATALOG_DIRECTORY, *, catalog_version: int = CATALOG_VERSION
) -> tuple[WorldRecipe, ...]:
    """Read one version of the recipe catalog and what it names, each held to its pinned digest:
    version 1's specification files, or a preset's schema, whose ranges hold its values."""
    _claimed_files(directory, catalog_version)
    schemas = load_specification_schemas(directory) if catalog_version > 1 else {}
    pins = (
        _pins(directory.joinpath(SPECIFICATIONS), _SPECIFICATION_NAME, "*.json")
        if catalog_version == 1
        else {name: {"sha256": schema.sha256} for name, schema in schemas.items()}
    )
    catalog = load_catalog(
        directory.joinpath(f"{CATALOG_ID}.v{catalog_version}.json"),
        _recipe_catalog(catalog_version, pins),
    )
    recipes = []
    for entry in catalog.entries:
        values = dict(entry.values)
        name = str(values["specification"])
        preset: dict[str, int | str] | None = None
        if catalog_version == 1:
            document = read_json(directory.joinpath(SPECIFICATIONS, f"{name}.json"))
        else:
            schema = schemas[name]
            try:
                preset = schema.check(cast(Mapping[str, object], values["values"]), complete=True)
                schema.check_together(preset)
            except SpecificationRefused as exc:
                raise CatalogError(f"preset {entry.key}: {exc}") from exc
            document = schema.specification(preset)
        tiles = specification_tiles(document)
        if len(tiles) != values["tiles"]:
            raise CatalogError(
                f"recipe {entry.key} states {values['tiles']} tiles and its specification "
                f"{name} covers {len(tiles)}"
            )
        recipes.append(
            WorldRecipe(
                key=entry.key,
                label=str(values["label"]),
                composer_key=str(values["composer"]),
                composer_version=int(cast(int, values["composer_version"])),
                specification_name=name,
                specification_sha256=pins[name]["sha256"],
                specification=document,
                candidates=int(cast(int, values["candidates"])),
                tiles=tiles,
                catalog_version=catalog.catalog_version,
                values=None if preset is None else MappingProxyType(preset),
            )
        )
    return tuple(recipes)


@functools.cache
def _by_key() -> MappingProxyType[str, WorldRecipe]:
    return MappingProxyType({recipe.key: recipe for recipe in load_world_recipes()})


@functools.cache
def _schemas() -> MappingProxyType[str, SpecificationSchema]:
    return load_specification_schemas()


def world_recipes() -> tuple[WorldRecipe, ...]:
    """The presets a running server offers, read once."""
    return tuple(_by_key().values())


def world_recipe(key: str) -> WorldRecipe:
    """The preset of that key, with its own values, or a refusal naming it."""
    recipe = _by_key().get(key)
    if recipe is None:
        raise UnknownWorldRecipe(f"no world recipe is named {key!r}")
    return recipe


def town_recipe(key: str, values: Mapping[str, object] | None = None) -> WorldRecipe:
    """The gate every request for a world passes: the preset ``key`` with ``values`` in place of
    its own, each held to the preset's schema.

    An unknown preset is :class:`UnknownWorldRecipe`; a value the schema does not offer is a
    :class:`SpecificationRefused` naming its key, the value and the range. Nothing is generated
    here: what passes is a recipe the composer generates or refuses by name.
    """
    preset = world_recipe(key)
    if preset.values is None:
        raise UnknownWorldRecipe(f"world recipe {key!r} is not a preset of a specification schema")
    schema = _schemas()[preset.specification_name]
    asked = schema.check(values or {}, complete=False)
    chosen = {**preset.values, **asked}
    schema.check_together(chosen)
    document = schema.specification(chosen)
    return WorldRecipe(
        key=preset.key,
        label=preset.label,
        composer_key=preset.composer_key,
        composer_version=preset.composer_version,
        specification_name=preset.specification_name,
        specification_sha256=preset.specification_sha256,
        specification=document,
        candidates=preset.candidates,
        tiles=specification_tiles(document),
        catalog_version=preset.catalog_version,
        values=MappingProxyType(dict(sorted(chosen.items()))),
    )


def tick_budget_ms() -> int:
    """The longest a town society's tick may take, at the 95th percentile: the shortest wait between
    its ticks at play (the default base interval at the fastest speed) over
    :data:`TICK_SHARE_DIVISOR`."""
    return DEFAULT_BASE_TICK_INTERVAL_MS // max(SPEEDS) // TICK_SHARE_DIVISOR


def specification_document() -> dict[str, Any]:
    """Every schema value, preset and refusal a request for a world meets, as one document.

    What ``GET /worlds/specification`` serves and the page renders, so a person, an open model
    drafting for them and an API client read one statement of what may be asked for: each value's
    key (the grammar's own parameter name), words, kind, unit, range and reason; the values each
    preset sets; the bounds a world is also held to (its society's people, the workspace's count);
    and every refusal by name.
    """
    from exulanica.world.society_grounds import society_ground_for_composer
    from exulanica.world.worlds import GENERATED, current_world_count_policy

    presets = world_recipes()
    named = sorted({recipe.specification_name for recipe in presets})
    schemas = _schemas()
    if len(named) != 1:
        raise CatalogError(f"the offered presets cite one schema, not {named}")
    schema = schemas[named[0]]
    composers = sorted({recipe.composer_key for recipe in presets})
    grounds = [society_ground_for_composer(key) for key in composers]
    policy = current_world_count_policy()
    return {
        "profile": SPECIFICATION_PROFILE,
        "schema": {**schema.reference(), "sha256": schema.sha256},
        "presets_catalog": {"catalog_id": CATALOG_ID, "catalog_version": CATALOG_VERSION},
        "grammar": {"grammar_id": schema.grammar_id, "grammar_version": schema.grammar_version},
        "values": [value.document() for value in (*schema.fields, *schema.values)],
        "presets": [
            {
                "key": recipe.key,
                "label": recipe.label,
                "values": dict(recipe.values or {}),
                "tiles": len(recipe.tiles),
            }
            for recipe in presets
        ],
        "bounds": {
            "tiles_maximum": TILES_MAXIMUM,
            "people": [
                {"ground": ground.key, "composer": ground.composer_key, "most": ground.population}
                for ground in grounds
            ],
            "generated_worlds_per_workspace": policy.limit(GENERATED),
            "world_count_policy": policy.reference(),
            "tick": {
                "budget_ms_p95": tick_budget_ms(),
                "fastest_interval_ms": DEFAULT_BASE_TICK_INTERVAL_MS // max(SPEEDS),
                "share_divisor": TICK_SHARE_DIVISOR,
                "reason": TICK_BUDGET_REASON,
            },
        },
        "refusals": [
            {"code": code, "status": status, "meaning": meaning}
            for code, status, meaning in REFUSALS
        ],
    }
