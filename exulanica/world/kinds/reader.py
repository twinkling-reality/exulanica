"""How a world kind's document is read: its two profiles, the refusal by name, and its fields.

:class:`KindRefused` names what is wrong with a document (a code, the place in it and a sentence)
and :class:`KindValueRefused` a person's values; the field readers refuse any key a mapping does
not state, any whole number outside its bounds, any text outside its length or in a refused
category, any list outside its length. :class:`_Reader` holds one document while it is read: the
bounds catalog, the parameters, the figures and looks it names.
:mod:`exulanica.world.kinds.document` reads a kind with these.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.grammar.errors import InvalidParameterError
from exulanica.grammar.grammars.site.plan import Look, Span
from exulanica.grammar.records import KEY_PATTERN
from exulanica.world.kinds.catalogs import KindCatalogs
from exulanica.world.society_catalogs import RoutineModel

PROFILE: Final = "exulanica.world-kind/v1"

REQUIREMENTS_PROFILE: Final = "exulanica.world-kind/v2"

_LOOK: Final = re.compile(r"([a-z]+)\.([a-z][a-z0-9_]{0,47})")


class KindRefused(ValueError):
    """A kind refused by name: its code, where in the document, and a sentence."""

    def __init__(self, code: str, detail: str, where: str = "") -> None:
        super().__init__(f"{code}: {where + ': ' if where else ''}{detail}")
        self.code = code
        self.detail = detail
        self.where = where

    def document(self) -> dict[str, str]:
        return {"code": self.code, "where": self.where, "detail": self.detail}


class KindValueRefused(ValueError):
    """A value a person or a model asked for that the kind does not offer, refused by name with
    the specification's own codes: ``specification_value_unknown`` (no such adjustable value) or
    ``specification_value_out_of_range`` (outside its range, off its step, or not a whole
    number)."""

    def __init__(self, code: str, key: str, value: object, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.key = key
        self.value = value
        self.detail = detail


def _invalid(where: str, detail: str) -> KindRefused:
    return KindRefused("kind_document_invalid", detail, where)


def _keys(where: str, raw: object, expected: frozenset[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _invalid(where, "is an object")
    unknown, missing = set(raw) - expected, expected - set(raw)
    if unknown or missing:
        raise _invalid(where, f"states unknown keys {sorted(unknown)} and lacks {sorted(missing)}")
    return raw


def _key(where: str, raw: object) -> str:
    if type(raw) is not str or KEY_PATTERN.fullmatch(raw) is None or len(raw) > 48:
        raise _invalid(where, f"is a lowercase key of at most 48 characters, not {raw!r}")
    return raw


def _int(where: str, raw: object, bounds: tuple[int, int]) -> int:
    if type(raw) is not int:
        raise _invalid(where, f"is a whole number, not {raw!r}")
    if not bounds[0] <= raw <= bounds[1]:
        raise KindRefused(
            "kind_out_of_bounds", f"is {raw}, outside {bounds[0]} to {bounds[1]}", where
        )
    return raw


#: Unicode categories text in a kind may not hold: control characters (NUL, CR and the rest),
#: format characters (bidirectional controls, zero-width joiners), surrogates, private use and
#: line and paragraph separators. A kind's words reach people and prompts as data.
_REFUSED_CATEGORIES: Final = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})


def _text(where: str, raw: object, bounds: tuple[int, int]) -> str:
    if type(raw) is not str or raw != raw.strip() or "\n" in raw:
        raise _invalid(where, "is text on one line with no surrounding space")
    if any(unicodedata.category(character) in _REFUSED_CATEGORIES for character in raw):
        raise _invalid(where, "holds no control, format or private-use characters")
    if not bounds[0] <= len(raw) <= bounds[1]:
        raise KindRefused(
            "kind_out_of_bounds",
            f"is {len(raw)} characters, outside {bounds[0]} to {bounds[1]}",
            where,
        )
    return raw


def _list(where: str, raw: object, bounds: tuple[int, int]) -> list[Any]:
    if not isinstance(raw, list):
        raise _invalid(where, "is a list")
    if not bounds[0] <= len(raw) <= bounds[1]:
        raise KindRefused(
            "kind_out_of_bounds", f"holds {len(raw)}, outside {bounds[0]} to {bounds[1]}", where
        )
    return raw


@dataclass(frozen=True, slots=True)
class _Figure:
    """A figure as written: a fixed value, a parameter's value, or a span the seed draws from."""

    value: int | None = None
    parameter: str = ""
    start: int = 0
    end: int = 0

    def resolve(self, values: Mapping[str, int], step: int) -> Span:
        if self.value is not None:
            return Span.fixed(self.value)
        if self.parameter:
            return Span.fixed(values[self.parameter])
        return Span(self.start, self.end, step)

    def fixed(self, values: Mapping[str, int]) -> int:
        span = self.resolve(values, 1)
        if span.minimum != span.maximum:
            raise InvalidParameterError("a fixed figure resolved to a span")
        return span.minimum


@dataclass(frozen=True, slots=True)
class KindParameter:
    """A value a person may change: its words, range, step and why."""

    key: str
    label: str
    minimum: int
    maximum: int
    step: int
    reason: str

    def document(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "step": self.step,
            "reason": self.reason,
        }


class _Reader:
    """Reads one document; collects every parameter use so each parameter's range is checked
    against every place it is used."""

    def __init__(
        self, raw: Mapping[str, Any], catalogs: KindCatalogs, routine: RoutineModel
    ) -> None:
        self.raw = raw
        self.catalogs = catalogs
        self.routine = routine
        self.parameters: dict[str, KindParameter] = {}
        #: (where, bound key, module or 0) for every place each parameter is used.
        self.uses: dict[str, list[tuple[str, str, int]]] = {}

    def bound(self, key: str) -> tuple[int, int]:
        return self.catalogs.bound(key)

    def limits(self, figure: _Figure) -> tuple[int, int]:
        if figure.value is not None:
            return figure.value, figure.value
        if figure.parameter:
            parameter = self.parameters[figure.parameter]
            return parameter.minimum, parameter.maximum
        return figure.start, figure.end

    def figure(
        self, where: str, raw: object, bound: str, *, module: int = 0, drawn: bool = False
    ) -> _Figure:
        """A figure: a whole number, ``{"parameter": key}`` or, where ``drawn``,
        ``{"from": a, "to": b}``; every value inside ``bound`` and, for a length the layout steps
        along, a whole number of ``module``."""
        limits = self.bound(bound)

        def aligned(value: int, at: str) -> int:
            _int(at, value, limits)
            if module and value % module:
                raise KindRefused(
                    "kind_out_of_bounds", f"{value} mm is not whole {module} mm modules", at
                )
            return value

        if type(raw) is int:
            return _Figure(value=aligned(raw, where))
        if isinstance(raw, dict) and set(raw) == {"parameter"}:
            name = raw["parameter"]
            if type(name) is not str:
                raise _invalid(where, f"names a parameter by its key, not {name!r}")
            if name not in self.parameters:
                raise KindRefused("kind_reference_unknown", f"names no parameter {name!r}", where)
            self.uses.setdefault(name, []).append((where, bound, module))
            return _Figure(parameter=name)
        if drawn and isinstance(raw, dict) and set(raw) == {"from", "to"}:
            start = aligned(raw["from"], f"{where}.from") if type(raw["from"]) is int else None
            end = aligned(raw["to"], f"{where}.to") if type(raw["to"]) is int else None
            if start is None or end is None or start > end:
                raise _invalid(where, "runs from a whole number to one no smaller")
            return _Figure(start=start, end=end)
        shapes = 'a whole number or {"parameter": key}' + (
            ' or {"from": n, "to": m}' if drawn else ""
        )
        raise _invalid(where, f"is {shapes}, not {raw!r}")

    def look(self, where: str, raw: object, families: Sequence[str]) -> Look:
        if type(raw) is not str or (found := _LOOK.fullmatch(raw)) is None:
            raise _invalid(where, f"is a look role family.leaf, not {raw!r}")
        family, leaf = found.group(1), found.group(2)
        if family not in self.catalogs.families:
            raise KindRefused("kind_role_unknown", f"names no look family {family!r}", where)
        if family not in families:
            raise KindRefused(
                "kind_role_unknown", f"is a {family} look; this takes {', '.join(families)}", where
            )
        return Look(family, leaf)
