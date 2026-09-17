"""Parameters, and the cascade that resolves them from coarse scope to fine.

**A closed schema.** A grammar declares every parameter it reads: its name, whether it is an
integer range or a choice among keys, and what happens when nothing sets it. There are exactly
three answers to that last question, and none of them is a default value, because a constant that
silently stands in for a missing input is how a generated world starts carrying facts nobody
chose.

* ``draw``: one value comes from the seed, in the domain ``<grammar_id>.parameters.<name>``, so an
  unset parameter is generated and says so.
* ``derive``: the stage that reads the parameter derives a value for each subject it makes, from
  the seed and the catalogs, and the record it emits states that value. The resolved set records
  the source ``derive`` and no value, because no single value exists: one draw for a whole world
  would make every subject alike and record a number no stage used.
* ``required``: the grammar refuses to run.

**A declared parameter** (descriptor schema 2) also states its unit, the cascade level it belongs
to, the one stage that reads it, the vocabulary a choice's options come from, and the basis of its
range. A binding may set it at its own level or any coarser one, never finer: a parameter of a
whole scope is not restyled one subject at a time.

**The cascade.** Each grammar declares its own scope levels, coarsest first. This module knows
nothing about what the levels mean; it only knows their order. A caller passes at most one
binding per level, being the bindings that actually enclose the subject being generated, and the
finest binding that sets a parameter wins. So restyling a whole scope is one binding, not one
per subject. Every resolved value records where it came from: the level that set it, or
``draw``.

Unknown parameters, unknown levels, a second binding at one level, and out-of-range values are
all refused. None of them is ignored.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, TypeAlias

from exulanica.grammar.draw import draw_integer
from exulanica.grammar.errors import InvalidParameterError
from exulanica.grammar.records import KEY_PATTERN

__all__ = [
    "CLOSED_VOCABULARY",
    "DERIVED",
    "DRAWN",
    "PARAMETER_KINDS",
    "PARAMETER_UNITS",
    "WHEN_UNSET",
    "CascadeBinding",
    "ParameterBinding",
    "ParameterCascade",
    "ParameterSchema",
    "ParameterSpec",
    "ResolvedParameters",
    "require_parameter_bindings",
]

PARAMETER_KINDS: Final = ("integer", "choice")
WHEN_UNSET: Final = ("draw", "required", "derive")
#: The source recorded for a value that no binding set and the seed produced.
DRAWN: Final = "draw"
#: The source recorded for a parameter whose value each reading stage derives per subject.
DERIVED: Final = "derive"
#: The units a declared parameter may state. ``key`` is the unit of every choice and only of one.
PARAMETER_UNITS: Final = ("mm", "count", "millionths", "urad", "ms", "mm_per_s", "key")
#: The vocabulary of a choice whose options exist only in the descriptor that lists them.
CLOSED_VOCABULARY: Final = "closed"

_VOCABULARY_ID: Final = re.compile(r"[a-z][a-z0-9-]*")

ParameterValue: TypeAlias = int | str


def _require_name(what: str, value: object) -> str:
    if type(value) is not str or KEY_PATTERN.fullmatch(value) is None:
        raise InvalidParameterError(f"{what} is a lowercase key, got {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """One declared parameter. Integer bounds are inclusive; choice options are ordered.

    ``unit``, ``level``, ``stage``, ``vocabulary`` and ``basis`` are empty for a descriptor of
    schema 1 and all stated for schema 2; a spec with some of them and not others is refused.
    """

    name: str
    kind: str
    when_unset: str
    minimum: int = 0
    maximum: int = 0
    options: tuple[str, ...] = ()
    unit: str = ""
    level: str = ""
    stage: str = ""
    vocabulary: str = ""
    basis: str = ""

    @property
    def declared(self) -> bool:
        return bool(self.unit or self.level or self.stage or self.vocabulary or self.basis)

    def __post_init__(self) -> None:
        _require_name("a parameter name", self.name)
        for label in ("unit", "level", "stage", "vocabulary", "basis"):
            if type(getattr(self, label)) is not str:
                raise InvalidParameterError(f"{self.name}: {label} is a str")
        if self.kind not in PARAMETER_KINDS:
            raise InvalidParameterError(
                f"{self.name}: kind {self.kind!r} is not one of {PARAMETER_KINDS}"
            )
        if self.when_unset not in WHEN_UNSET:
            raise InvalidParameterError(
                f"{self.name}: when_unset {self.when_unset!r} is not one of {WHEN_UNSET}"
            )
        if type(self.minimum) is not int or type(self.maximum) is not int:
            raise InvalidParameterError(f"{self.name}: bounds are ints")
        if self.kind == "integer":
            if self.minimum > self.maximum:
                raise InvalidParameterError(f"{self.name}: minimum is above maximum")
            if self.options:
                raise InvalidParameterError(f"{self.name}: an integer parameter has no options")
        else:
            if not self.options or len(set(self.options)) != len(self.options):
                raise InvalidParameterError(f"{self.name}: a choice needs distinct options")
            for option in self.options:
                _require_name(f"{self.name} option", option)
            if self.minimum or self.maximum:
                raise InvalidParameterError(f"{self.name}: a choice parameter has no bounds")
        if self.declared:
            self._check_declaration()
        elif self.when_unset == DERIVED:
            raise InvalidParameterError(f"{self.name}: a derived parameter names its stage")

    def _check_declaration(self) -> None:
        if self.unit not in PARAMETER_UNITS:
            raise InvalidParameterError(
                f"{self.name}: unit {self.unit!r} is not one of {PARAMETER_UNITS}"
            )
        if (self.kind == "choice") != (self.unit == "key"):
            raise InvalidParameterError(
                f"{self.name}: a choice, and only a choice, is measured in keys"
            )
        _require_name(f"{self.name} level", self.level)
        _require_name(f"{self.name} stage", self.stage)
        if self.kind == "choice":
            if self.vocabulary != CLOSED_VOCABULARY and not _VOCABULARY_ID.fullmatch(
                self.vocabulary
            ):
                raise InvalidParameterError(
                    f"{self.name}: a choice names the vocabulary its options come from"
                )
        elif self.vocabulary != "":
            raise InvalidParameterError(f"{self.name}: an integer parameter has no vocabulary")
        if not self.basis.strip() or self.basis != self.basis.strip():
            raise InvalidParameterError(f"{self.name}: basis is non-empty text")

    def check(self, value: object) -> ParameterValue:
        if self.kind == "integer":
            if type(value) is not int:
                raise InvalidParameterError(f"{self.name} is an int, got {type(value).__name__}")
            if not self.minimum <= value <= self.maximum:
                raise InvalidParameterError(
                    f"{self.name} is {value}, outside [{self.minimum}, {self.maximum}]"
                )
            return value
        if type(value) is not str or value not in self.options:
            raise InvalidParameterError(f"{self.name} is one of {self.options}, got {value!r}")
        return value

    def draw(self, seed: str, domain: str) -> ParameterValue:
        if self.kind == "integer":
            return draw_integer(seed, domain, 0, self.minimum, self.maximum)
        return self.options[draw_integer(seed, domain, 0, 0, len(self.options) - 1)]


_SPEC_KEYS: Final = frozenset({"name", "kind", "when_unset", "minimum", "maximum", "options"})
_DECLARED_KEYS: Final = frozenset(
    {"name", "kind", "unit", "level", "stage", "when_unset", "vocabulary", "basis"}
)
_KIND_KEYS: Final = {"integer": frozenset({"minimum", "maximum"}), "choice": frozenset({"options"})}


@dataclass(frozen=True, slots=True)
class ParameterSchema:
    parameters: tuple[ParameterSpec, ...]

    def __post_init__(self) -> None:
        names = [spec.name for spec in self.parameters]
        if len(set(names)) != len(names):
            raise InvalidParameterError(f"duplicate parameter names in {names}")

    def get(self, name: str) -> ParameterSpec:
        for spec in self.parameters:
            if spec.name == name:
                return spec
        raise InvalidParameterError(f"{name!r} is not a declared parameter")

    def names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.parameters)

    def for_stage(self, stage_id: str) -> tuple[ParameterSpec, ...]:
        """The parameters one stage reads, in declaration order."""
        return tuple(spec for spec in self.parameters if spec.stage == stage_id)

    @classmethod
    def from_document(cls, document: object, *, schema_version: int = 1) -> ParameterSchema:
        if not isinstance(document, list):
            raise InvalidParameterError("parameters is a list")
        if schema_version not in (1, 2):
            raise InvalidParameterError(f"no parameter form for schema {schema_version!r}")
        specs = []
        for index, entry in enumerate(document):
            if not isinstance(entry, dict):
                raise InvalidParameterError(f"parameters[{index}] is an object")
            if schema_version == 1:
                unknown = set(entry) - _SPEC_KEYS
                if unknown:
                    raise InvalidParameterError(
                        f"parameters[{index}] has unknown keys {sorted(unknown)}"
                    )
            else:
                expected = _DECLARED_KEYS | _KIND_KEYS.get(entry.get("kind"), frozenset())
                if set(entry) != expected:
                    raise InvalidParameterError(
                        f"parameters[{index}] has keys {sorted(entry)}, expected {sorted(expected)}"
                    )
            options = entry.get("options", [])
            if not isinstance(options, list):
                raise InvalidParameterError(f"parameters[{index}].options is a list")
            specs.append(
                ParameterSpec(
                    name=entry.get("name"),
                    kind=entry.get("kind"),
                    when_unset=entry.get("when_unset"),
                    minimum=entry.get("minimum", 0),
                    maximum=entry.get("maximum", 0),
                    options=tuple(options),
                    unit=entry.get("unit", ""),
                    level=entry.get("level", ""),
                    stage=entry.get("stage", ""),
                    vocabulary=entry.get("vocabulary", ""),
                    basis=entry.get("basis", ""),
                )
            )
        if schema_version == 2 and not all(spec.declared for spec in specs):
            raise InvalidParameterError("every parameter of a schema 2 descriptor is declared")
        return cls(tuple(specs))


@dataclass(frozen=True, slots=True)
class CascadeBinding:
    """The values one enclosing scope sets. Built with :meth:`of`, stored sorted by name."""

    level: str
    values: tuple[tuple[str, ParameterValue], ...]

    @classmethod
    def of(cls, level: str, values: Mapping[str, ParameterValue]) -> CascadeBinding:
        _require_name("a cascade level", level)
        for name in values:
            _require_name("a bound parameter name", name)
        return cls(level=level, values=tuple(sorted(values.items())))


@dataclass(frozen=True, slots=True)
class ResolvedParameters:
    """Every parameter's source, and a value for each one that has a single value.

    A ``derive`` parameter appears in ``sources`` and not in ``values``.
    """

    values: tuple[tuple[str, ParameterValue], ...]
    sources: tuple[tuple[str, str], ...]

    def as_mapping(self) -> Mapping[str, ParameterValue]:
        return MappingProxyType(dict(self.values))


@dataclass(frozen=True, slots=True)
class ParameterBinding:
    """One resolved parameter as a durable record carries it: its name, value and source.

    The source is the cascade level whose binding set the value, ``draw``, or ``derive`` for a
    value the stage derived for this subject. Checked by :func:`require_parameter_bindings`.
    """

    name: str
    value: ParameterValue
    source: str


@dataclass(frozen=True, slots=True)
class ParameterCascade:
    """The ordered scope levels a grammar declares, coarsest first."""

    levels: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.levels or len(set(self.levels)) != len(self.levels):
            raise InvalidParameterError("a cascade declares at least one level and no repeats")
        for level in self.levels:
            _require_name("a cascade level", level)
        for reserved in (DRAWN, DERIVED):
            if reserved in self.levels:
                raise InvalidParameterError(f"{reserved!r} is reserved as a value source")

    def admits(self, spec: ParameterSpec, level: str) -> bool:
        """Whether a binding at ``level`` may set ``spec``: its own level or a coarser one."""
        if level not in self.levels:
            return False
        if not spec.level:
            return True
        if spec.level not in self.levels:
            raise InvalidParameterError(
                f"{spec.name}: level {spec.level!r} is not in {self.levels}"
            )
        return self.levels.index(level) <= self.levels.index(spec.level)

    def resolve(
        self,
        schema: ParameterSchema,
        bindings: Sequence[CascadeBinding],
        *,
        seed: str,
        domain_prefix: str,
    ) -> ResolvedParameters:
        by_level: dict[str, CascadeBinding] = {}
        for binding in bindings:
            if binding.level not in self.levels:
                raise InvalidParameterError(
                    f"{binding.level!r} is not a level of this cascade {self.levels}"
                )
            if binding.level in by_level:
                raise InvalidParameterError(f"two bindings at level {binding.level!r}")
            by_level[binding.level] = binding
        values: dict[str, ParameterValue] = {}
        sources: dict[str, str] = {}
        for level in self.levels:
            binding = by_level.get(level)
            if binding is None:
                continue
            for name, value in binding.values:
                spec = schema.get(name)
                if not self.admits(spec, level):
                    raise InvalidParameterError(
                        f"{name} belongs to level {spec.level!r} and cannot be set at {level!r}"
                    )
                values[name] = spec.check(value)
                sources[name] = level
        for spec in schema.parameters:
            if spec.name in values:
                continue
            if spec.when_unset == "required":
                raise InvalidParameterError(f"{spec.name} is required and no level sets it")
            if spec.when_unset == DERIVED:
                sources[spec.name] = DERIVED
                continue
            values[spec.name] = spec.draw(seed, f"{domain_prefix}.parameters.{spec.name}")
            sources[spec.name] = DRAWN
        return ResolvedParameters(
            values=tuple(sorted(values.items())), sources=tuple(sorted(sources.items()))
        )


def require_parameter_bindings(
    name: str,
    bindings: object,
    schema: ParameterSchema,
    cascade: ParameterCascade,
    *,
    stage: str,
) -> tuple[ParameterBinding, ...]:
    """The parameters ``stage`` reads, each once, sorted by name, valid, with a valid source.

    A value set by a level must be one the cascade admits there; ``draw`` and ``derive`` are
    accepted only for a parameter whose ``when_unset`` says so. The record states every parameter
    its stage reads and no other, so a durable record cannot quietly omit one.
    """
    if not isinstance(bindings, tuple):
        raise InvalidParameterError(f"{name} is a tuple of ParameterBinding")
    expected = sorted(spec.name for spec in schema.for_stage(stage))
    seen = []
    for index, binding in enumerate(bindings):
        if type(binding) is not ParameterBinding:
            raise InvalidParameterError(f"{name}[{index}] is a ParameterBinding")
        spec = schema.get(binding.name)
        spec.check(binding.value)
        source = binding.source
        if source in (DRAWN, DERIVED):
            if spec.when_unset != source:
                raise InvalidParameterError(
                    f"{name}[{index}]: {spec.name} is not a {source!r} parameter"
                )
        elif type(source) is not str or not cascade.admits(spec, source):
            raise InvalidParameterError(
                f"{name}[{index}]: {spec.name} cannot have been set at {source!r}"
            )
        seen.append(binding.name)
    if seen != expected:
        raise InvalidParameterError(
            f"{name} states exactly the parameters {stage} reads, sorted: expected {expected}"
        )
    return bindings
