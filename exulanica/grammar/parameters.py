"""Parameters, and the cascade that resolves them from coarse scope to fine.

**A closed schema.** A grammar declares every parameter it reads: its name, whether it is an
integer range or a choice among keys, and what happens when nothing sets it. There are exactly
two answers to that last question. ``draw`` means the value comes from the seed, in the domain
``<grammar_id>.parameters.<name>``, so an unset parameter is generated and says so. ``required``
means the grammar refuses to run. There is no third answer, and in particular no default value:
a constant that silently stands in for a missing input is how a generated world starts carrying
facts nobody chose.

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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, TypeAlias

from exulanica.grammar.draw import draw_integer
from exulanica.grammar.errors import InvalidParameterError
from exulanica.grammar.records import KEY_PATTERN

__all__ = [
    "DRAWN",
    "PARAMETER_KINDS",
    "WHEN_UNSET",
    "CascadeBinding",
    "ParameterCascade",
    "ParameterSchema",
    "ParameterSpec",
    "ResolvedParameters",
]

PARAMETER_KINDS: Final = ("integer", "choice")
WHEN_UNSET: Final = ("draw", "required")
#: The source recorded for a value that no binding set and the seed produced.
DRAWN: Final = "draw"

ParameterValue: TypeAlias = int | str


def _require_name(what: str, value: object) -> str:
    if type(value) is not str or KEY_PATTERN.fullmatch(value) is None:
        raise InvalidParameterError(f"{what} is a lowercase key, got {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """One declared parameter. Integer bounds are inclusive; choice options are ordered."""

    name: str
    kind: str
    when_unset: str
    minimum: int = 0
    maximum: int = 0
    options: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_name("a parameter name", self.name)
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

    @classmethod
    def from_document(cls, document: object) -> ParameterSchema:
        if not isinstance(document, list):
            raise InvalidParameterError("parameters is a list")
        specs = []
        for index, entry in enumerate(document):
            if not isinstance(entry, dict):
                raise InvalidParameterError(f"parameters[{index}] is an object")
            unknown = set(entry) - _SPEC_KEYS
            if unknown:
                raise InvalidParameterError(
                    f"parameters[{index}] has unknown keys {sorted(unknown)}"
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
                )
            )
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
    values: tuple[tuple[str, ParameterValue], ...]
    sources: tuple[tuple[str, str], ...]

    def as_mapping(self) -> Mapping[str, ParameterValue]:
        return MappingProxyType(dict(self.values))


@dataclass(frozen=True, slots=True)
class ParameterCascade:
    """The ordered scope levels a grammar declares, coarsest first."""

    levels: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.levels or len(set(self.levels)) != len(self.levels):
            raise InvalidParameterError("a cascade declares at least one level and no repeats")
        for level in self.levels:
            _require_name("a cascade level", level)
        if DRAWN in self.levels:
            raise InvalidParameterError(f"{DRAWN!r} is reserved as a value source")

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
                values[name] = schema.get(name).check(value)
                sources[name] = level
        for spec in schema.parameters:
            if spec.name in values:
                continue
            if spec.when_unset == "required":
                raise InvalidParameterError(f"{spec.name} is required and no level sets it")
            values[spec.name] = spec.draw(seed, f"{domain_prefix}.parameters.{spec.name}")
            sources[spec.name] = DRAWN
        return ResolvedParameters(
            values=tuple(sorted(values.items())), sources=tuple(sorted(sources.items()))
        )
