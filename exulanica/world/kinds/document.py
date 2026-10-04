"""A world kind: one typed, versioned, fingerprinted document, read and held to its checks.

A world kind states a kind of place a person can make worlds of (a farm, a building site, a
cafe, a harbour) as data, profile ``exulanica.world-kind/v1``: its parts in plain words with the
engine roles that say what the engine does with each, its zones and how they are laid out, its own
workplaces, shops and homes in the society's use-class form, the values a person may change with
their ranges, and named presets. A model drafts one from a person's words, a creator uploads one,
or the team authors one; whichever, the same reader holds it to the same checks, and nothing is
generated from a kind that fails them.

**This module is stage A of a kind's checks: the document itself.** :func:`read_kind` refuses,
by name (:class:`KindRefused`, with a code, the place in the document and a sentence), any key it
does not state, any float, any figure outside the bounds catalog, any reference that does not
resolve, any engine role a part's form may not take, any role whose needs the part does not state
(a seat with no seats, a workplace with no workplace use class), any use class the society's own
use-class checks refuse, and any preset outside the ranges. Stage B, building sample worlds from it
and holding each to what people need to live, walk and work there, is
:mod:`exulanica.world.kinds.samples`.

**A figure** is a whole number, a parameter's value (``{"parameter": key}``) or, where a figure is
drawn per placed thing, a span the seed draws from (``{"from": a, "to": b}``). Lengths a layout
steps along (a site's sides, a path's width, a structure's sides) are whole numbers of the site's
module: 500 mm outdoors, 100 mm indoors (the bounds catalog states both).

**Values.** A person, a model choosing values for them and an API client ask for a world the same
way: a preset and, optionally, values for its parameters. :meth:`KindDocument.values` holds each to
its parameter's range and step and refuses by name (the specification's own codes), never clamping;
:meth:`KindDocument.plan` resolves the kind with those values into the
:class:`~exulanica.grammar.grammars.site.plan.SitePlan` the site grammar generates.

Pure: no connection, no store, no clock.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, cast

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.errors import CanonicalisationError
from exulanica.grammar.catalogs import FieldValue
from exulanica.grammar.errors import CatalogError, InvalidParameterError
from exulanica.grammar.grammars.site.plan import (
    ACCESS,
    ENCLOSURES,
    FORMS,
    PATTERNS,
    PLACEMENTS,
    ROOF_FORMS,
    AreaPart,
    BoundaryPart,
    FixturePart,
    Holding,
    Look,
    PathPart,
    RoomPart,
    SitePlan,
    Span,
    StructurePart,
    ZonePlan,
)
from exulanica.grammar.records import KEY_PATTERN
from exulanica.world.kinds.catalogs import KindCatalogs, load_kind_catalogs
from exulanica.world.society_catalogs import SCHEMAS, RoutineModel
from exulanica.world.society_site_place import PartUse, SiteSociety

__all__ = [
    "GENERATOR_KEY",
    "GENERATOR_VERSION",
    "KIND_CODES",
    "LICENCES",
    "ORIGINS",
    "PROFILE",
    "KindDocument",
    "KindParameter",
    "KindRefused",
    "KindValueRefused",
    "read_kind",
]

PROFILE: Final = "exulanica.world-kind/v1"
#: The composer that generates every kind this module reads: the site grammar's.
GENERATOR_KEY: Final = "site-plan"
GENERATOR_VERSION: Final = 1
ORIGINS: Final = ("authored", "drafted", "uploaded", "imported")
#: The licences a kind may carry: the repository's own and the permissive ones the licence matrix
#: ships content under. Anything else is refused, never shipped.
LICENCES: Final = ("Apache-2.0", "CC-BY-4.0", "CC0-1.0", "MIT")
_KIND: Final = re.compile(r"[a-z][a-z0-9_]{0,31}")
_LOOK: Final = re.compile(r"([a-z]+)\.([a-z][a-z0-9_]{0,47})")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
#: The refusals a kind meets, by stage A and stage B, each with what it means.
KIND_CODES: Final = (
    (
        "kind_document_invalid",
        (
            "The document is not a world kind: a key it does not state, a float, a missing field, "
            "a malformed value."
        ),
    ),
    (
        "kind_role_unknown",
        (
            "A part names an engine role the engine does not have, or one its form may not take, "
            "or a look family that does not exist."
        ),
    ),
    (
        "kind_reference_unknown",
        (
            "A key names a part, a zone, a use class, a shift or a parameter the kind does not "
            "state."
        ),
    ),
    (
        "kind_out_of_bounds",
        ("A figure lies outside the bounds catalog, or a length is not whole modules of the site."),
    ),
    (
        "kind_role_unmet",
        (
            "A part takes a role it does not state the needs of: a seat with no seats, a "
            "workplace with no workplace use class."
        ),
    ),
    (
        "kind_generation_refused",
        (
            "A sample world could not be laid out from the kind: its parts do not fit their zones "
            "for any seed tried."
        ),
    ),
    (
        "kind_unreachable",
        (
            "In a sample world, somewhere people go cannot be reached from the entry, or a "
            "worker's home from their workplace."
        ),
    ),
    (
        "kind_population_out_of_bounds",
        (
            "A sample world houses nobody, or more people than a living society's tick was "
            "measured to hold."
        ),
    ),
    (
        "kind_capacity_short",
        (
            "A sample world has workplaces nobody can staff, or homes and workplaces that do not "
            "meet."
        ),
    ),
    (
        "kind_graph_over_budget",
        (
            "A sample world's walking graph is larger than the largest one a living society's "
            "tick was measured on."
        ),
    ),
)
_SITE_KEYS: Final = frozenset(
    {"enclosure", "width_mm", "depth_mm", "ground", "spine", "boundary", "entry_width_mm"}
)
_TOP_KEYS: Final = frozenset(
    {
        "profile",
        "kind",
        "version",
        "label",
        "summary",
        "origin",
        "provenance",
        "licence",
        "generator",
        "site",
        "society",
        "parameters",
        "presets",
        "use_classes",
        "parts",
        "zones",
    }
)
_PART_COMMON: Final = frozenset(
    {"key", "label", "description", "form", "roles", "look", "use_class"}
)
_PART_KEYS: Final = {
    "path": frozenset({"width_mm"}),
    "area": frozenset(),
    "structure": frozenset(
        {
            "width_mm",
            "depth_mm",
            "storeys",
            "storey_height_mm",
            "roof_form",
            "roof_look",
            "wall_look",
            "door_width_mm",
            "rooms",
        }
    ),
    "room": frozenset({"share", "holds"}),
    "fixture": frozenset(
        {"width_mm", "depth_mm", "height_mm", "seats", "stands", "sleepers", "blocks"}
    ),
    "boundary": frozenset({"height_mm", "thickness_mm", "gate_width_mm"}),
}
#: The look families each form's own look may name.
_FORM_LOOKS: Final = {
    "path": ("path", "road"),
    "area": ("ground", "water", "road", "path", "plant"),
    "structure": ("structure",),
    "room": ("ground",),
    "fixture": ("fixture", "prop", "plant", "vehicle", "animal"),
    "boundary": ("boundary", "wall"),
}
#: The roles that make a part somewhere the society goes, and the use-class kind each needs.
_USE_ROLES: Final = {"home": "residential", "workplace": "workplace", "shop": "workplace"}
#: The use class a seat takes when it names none: the society's bench, where people rest.
DEFAULT_SEAT_USE: Final = "bench"
#: The use class a home takes when it names none: the society's residential unit.
DEFAULT_HOME_USE: Final = "residential"


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


def _text(where: str, raw: object, bounds: tuple[int, int]) -> str:
    if type(raw) is not str or raw != raw.strip() or "\n" in raw:
        raise _invalid(where, "is text on one line with no surrounding space")
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


def _read_parameters(reader: _Reader, raw: object) -> None:
    for index, item in enumerate(_list("parameters", raw, reader.bound("parameters"))):
        where = f"parameters[{index}]"
        entry = _keys(
            where, item, frozenset({"key", "label", "minimum", "maximum", "step", "reason"})
        )
        key = _key(f"{where}.key", entry["key"])
        if key in reader.parameters:
            raise _invalid(where, f"repeats parameter {key}")
        figure = (0, 2**31 - 1)
        minimum = _int(f"{where}.minimum", entry["minimum"], figure)
        maximum = _int(f"{where}.maximum", entry["maximum"], figure)
        step = _int(f"{where}.step", entry["step"], (1, 2**31 - 1))
        if minimum >= maximum or (maximum - minimum) % step:
            raise _invalid(where, "runs from its minimum to a greater maximum in whole steps")
        reader.parameters[key] = KindParameter(
            key,
            _text(f"{where}.label", entry["label"], reader.bound("label_characters")),
            minimum,
            maximum,
            step,
            _text(f"{where}.reason", entry["reason"], (1, 400)),
        )


def _check_parameter_uses(reader: _Reader) -> None:
    for key, parameter in reader.parameters.items():
        uses = reader.uses.get(key, [])
        if not uses:
            raise KindRefused("kind_reference_unknown", "is used by no figure", f"parameter {key}")
        for where, bound, module in uses:
            low, high = reader.bound(bound)
            if parameter.minimum < low or parameter.maximum > high:
                raise KindRefused(
                    "kind_out_of_bounds",
                    f"parameter {key} runs {parameter.minimum} to {parameter.maximum} and is used "
                    f"where {low} to {high} is allowed",
                    where,
                )
            if module and (parameter.minimum % module or parameter.step % module):
                raise KindRefused(
                    "kind_out_of_bounds",
                    f"parameter {key} sets a length, so its minimum and step are whole "
                    f"{module} mm modules",
                    where,
                )


def _check_entry(
    schema_key: tuple[str, int], where: str, raw: dict[str, Any]
) -> dict[str, FieldValue]:
    """One use class held to the society's own use-class schema: every field's check and the
    schema's rule across fields, the same ones a use-class catalog file meets."""
    schema = SCHEMAS[schema_key]
    try:
        values = {name: check(f"{where}.{name}", raw[name]) for name, check in schema.fields}
        if schema.entry_check is not None:
            schema.entry_check(where, values)
    except CatalogError as exc:
        raise _invalid(where, str(exc)) from exc
    return values


_USE_CLASS_KEYS: Final = frozenset(
    {
        "key",
        "label",
        "kind",
        "role_key",
        "role_label",
        "staff_per_unit",
        "visitor_capacity",
        "resident_capacity",
        "visitor_affordances",
        "opening_minute",
        "closing_minute",
        "shifts",
    }
)


def _read_use_classes(reader: _Reader, raw: object) -> dict[str, dict[str, Any]]:
    routine = reader.routine
    affordances = {activity.affordance for activity in routine.activities.values()}
    found: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(_list("use_classes", raw, reader.bound("use_classes"))):
        where = f"use_classes[{index}]"
        entry = _keys(where, item, _USE_CLASS_KEYS)
        key = _key(f"{where}.key", entry["key"])
        if key in found or key in routine.use_classes:
            raise _invalid(where, f"use class {key} repeats one the kind or the society states")
        values = _check_entry(
            ("society-use-class", 2), where, {**entry, "reason": "stated by a world kind"}
        )
        offered = set(cast(tuple[str, ...], values["visitor_affordances"]))
        if not offered <= affordances:
            raise KindRefused(
                "kind_reference_unknown",
                f"offers {sorted(offered - affordances)}, which no activity of the society uses",
                where,
            )
        if bool(offered) != (values["visitor_capacity"] != 0):
            raise _invalid(where, "visitors need both a capacity and something to do")
        shifts = set(cast(tuple[str, ...], values["shifts"]))
        if not shifts <= set(routine.shifts):
            raise KindRefused(
                "kind_reference_unknown",
                f"names shifts {sorted(shifts - set(routine.shifts))}; the society has "
                f"{sorted(routine.shifts)}",
                where,
            )
        found[key] = {name: entry[name] for name in sorted(_USE_CLASS_KEYS)}
    return found


@dataclass(frozen=True, slots=True)
class _ReadPart:
    key: str
    label: str
    description: str
    form: str
    roles: tuple[str, ...]
    look: Look
    use_class: str
    fields: Mapping[str, Any]


def _use_kind(reader: _Reader, use_classes: Mapping[str, Mapping[str, Any]], key: str) -> str:
    if key in use_classes:
        return str(use_classes[key]["kind"])
    found = reader.routine.use_classes.get(key)
    return "" if found is None else found.kind


def _read_part(
    reader: _Reader, index: int, raw: object, module: int, use_classes: Mapping[str, Any]
) -> _ReadPart:
    where = f"parts[{index}]"
    if not isinstance(raw, dict) or raw.get("form") not in FORMS:
        raise _invalid(where, f"states a form, one of {list(FORMS)}")
    form = str(raw["form"])
    entry = _keys(where, raw, _PART_COMMON | _PART_KEYS[form])
    key = _key(f"{where}.key", entry["key"])
    roles_raw = entry["roles"]
    if not isinstance(roles_raw, list) or not all(type(r) is str for r in roles_raw):
        raise _invalid(f"{where}.roles", "is a list of engine roles")
    roles = tuple(sorted(set(roles_raw)))
    if len(roles) != len(roles_raw):
        raise _invalid(f"{where}.roles", "repeats a role")
    for role in roles:
        forms = reader.catalogs.role_forms.get(role)
        if forms is None:
            raise KindRefused("kind_role_unknown", f"no engine role {role!r}", f"{where}.roles")
        if form not in forms:
            raise KindRefused(
                "kind_role_unknown",
                f"a {form} may not take the role {role}; it takes forms {sorted(forms)}",
                f"{where}.roles",
            )
    used = [role for role in roles if role in _USE_ROLES]
    if len(used) > 1:
        raise KindRefused("kind_role_unmet", f"takes {used}; a part is one of them", where)
    if form in ("fixture", "area") and not roles:
        raise KindRefused("kind_role_unmet", f"a {form} takes at least one role", where)
    if form == "path" and "path" not in roles:
        raise KindRefused(
            "kind_role_unmet", "every path is walked, so it takes the role path", where
        )
    use_class = entry["use_class"]
    if type(use_class) is not str or (use_class and KEY_PATTERN.fullmatch(use_class) is None):
        raise _invalid(f"{where}.use_class", "is a use class key or empty")
    look = reader.look(f"{where}.look", entry["look"], _FORM_LOOKS[form])
    fields: dict[str, Any] = {}
    figure = reader.figure
    if form == "path":
        fields["width_mm"] = figure(
            f"{where}.width_mm", entry["width_mm"], "path_width_mm", module=module
        )
    elif form == "structure":
        fields["width_mm"] = figure(
            f"{where}.width_mm", entry["width_mm"], "structure_width_mm", module=module, drawn=True
        )
        fields["depth_mm"] = figure(
            f"{where}.depth_mm", entry["depth_mm"], "structure_depth_mm", module=module, drawn=True
        )
        fields["storeys"] = figure(f"{where}.storeys", entry["storeys"], "storeys", drawn=True)
        fields["storey_height_mm"] = _int(
            f"{where}.storey_height_mm", entry["storey_height_mm"], reader.bound("storey_height_mm")
        )
        if entry["roof_form"] not in ROOF_FORMS:
            raise _invalid(f"{where}.roof_form", f"is one of {list(ROOF_FORMS)}")
        fields["roof_form"] = entry["roof_form"]
        fields["roof_look"] = reader.look(f"{where}.roof_look", entry["roof_look"], ("roof",))
        fields["wall_look"] = reader.look(f"{where}.wall_look", entry["wall_look"], ("wall",))
        fields["door_width_mm"] = _int(
            f"{where}.door_width_mm", entry["door_width_mm"], reader.bound("door_width_mm")
        )
        rooms = []
        for room_index, room in enumerate(
            _list(f"{where}.rooms", entry["rooms"], reader.bound("rooms"))
        ):
            at = f"{where}.rooms[{room_index}]"
            stated = _keys(at, room, frozenset({"part", "count"}))
            rooms.append(
                (
                    _key(f"{at}.part", stated["part"]),
                    figure(f"{at}.count", stated["count"], "holding_count", drawn=True),
                )
            )
        fields["rooms"] = tuple(rooms)
    elif form == "room":
        fields["share"] = _int(f"{where}.share", entry["share"], reader.bound("room_share"))
        fields["holds"] = _holdings(reader, f"{where}.holds", entry["holds"], allow_empty=True)
    elif form == "fixture":
        for name in ("width_mm", "depth_mm", "height_mm"):
            fields[name] = _int(f"{where}.{name}", entry[name], reader.bound("fixture_size_mm"))
        for name in ("seats", "stands"):
            fields[name] = _int(f"{where}.{name}", entry[name], reader.bound("fixture_places"))
        fields["sleepers"] = _int(f"{where}.sleepers", entry["sleepers"], reader.bound("sleepers"))
        fields["blocks"] = _int(f"{where}.blocks", entry["blocks"], (0, 1))
        spacing = reader.routine.policy["standing_spacing_mm"]
        for name in ("seats", "stands"):
            if fields[name] > 1 and (fields[name] - 1) * spacing > fields["width_mm"] + spacing:
                raise KindRefused(
                    "kind_role_unmet",
                    f"{fields[name]} {name} need {(fields[name] - 1) * spacing} mm along a front "
                    f"{fields['width_mm']} mm wide, at the society's {spacing} mm standing spacing",
                    where,
                )
    elif form == "boundary":
        fields["height_mm"] = _int(
            f"{where}.height_mm", entry["height_mm"], reader.bound("boundary_height_mm")
        )
        fields["thickness_mm"] = _int(
            f"{where}.thickness_mm", entry["thickness_mm"], reader.bound("boundary_thickness_mm")
        )
        fields["gate_width_mm"] = _int(
            f"{where}.gate_width_mm", entry["gate_width_mm"], reader.bound("gate_width_mm")
        )
    _check_roles(reader, where, form, roles, use_class, fields, use_classes)
    return _ReadPart(
        key=key,
        label=_text(f"{where}.label", entry["label"], reader.bound("label_characters")),
        description=_text(
            f"{where}.description", entry["description"], reader.bound("description_characters")
        )
        if entry["description"] != ""
        else "",
        form=form,
        roles=roles,
        look=look,
        use_class=use_class,
        fields=MappingProxyType(fields),
    )


def _check_roles(
    reader: _Reader,
    where: str,
    form: str,
    roles: tuple[str, ...],
    use_class: str,
    fields: Mapping[str, Any],
    use_classes: Mapping[str, Any],
) -> None:
    """Each role's needs are stated: a use class of the kind the role needs, seats for a seat,
    standing places for a gathering spot, sleepers exactly for a bed."""
    kind = _use_kind(reader, use_classes, use_class) if use_class else ""
    if use_class and not kind:
        raise KindRefused("kind_reference_unknown", f"names no use class {use_class!r}", where)
    if form == "room":
        if use_class:
            raise KindRefused(
                "kind_role_unmet",
                "a room is part of its structure's use and names no use class of its own",
                where,
            )
        return
    needed = next((_USE_ROLES[role] for role in roles if role in _USE_ROLES), "")
    if "seat" in roles:
        if fields.get("seats", 0) < 1:
            raise KindRefused("kind_role_unmet", "a seat seats at least one", where)
        if use_class and (
            kind != "furniture" or "rest" not in _offers(reader, use_classes, use_class)
        ):
            raise KindRefused(
                "kind_role_unmet", "a seat's use class is furniture people rest at", where
            )
    if "gathering" in roles:
        if fields.get("stands", 0) < 1:
            raise KindRefused("kind_role_unmet", "a gathering spot has standing places", where)
        if kind != "furniture" or "visit" not in _offers(reader, use_classes, use_class):
            raise KindRefused(
                "kind_role_unmet", "a gathering spot's use class is furniture people visit", where
            )
    if form == "fixture" and (fields["sleepers"] > 0) != ("bed" in roles):
        raise KindRefused("kind_role_unmet", "exactly a bed has sleepers", where)
    if needed:
        if needed == "residential" and not use_class:
            return
        if kind != needed:
            raise KindRefused(
                "kind_role_unmet",
                f"takes a role needing a {needed} use class, and names {use_class or 'none'}",
                where,
            )
        if "shop" in roles and not _offers(reader, use_classes, use_class):
            raise KindRefused("kind_role_unmet", "a shop's use class admits visitors", where)
    elif use_class and not ({"seat", "gathering"} & set(roles)):
        raise KindRefused(
            "kind_role_unmet", f"names use class {use_class} and takes no role that uses one", where
        )


def _offers(reader: _Reader, use_classes: Mapping[str, Any], key: str) -> tuple[str, ...]:
    if key in use_classes:
        return tuple(use_classes[key]["visitor_affordances"])
    found = reader.routine.use_classes.get(key)
    return () if found is None else found.visitor_affordances


def _holdings(reader: _Reader, where: str, raw: object, *, allow_empty: bool) -> tuple[Any, ...]:
    low, high = reader.bound("holdings")
    items = _list(where, raw, (0 if allow_empty else low, high))
    held = []
    for index, item in enumerate(items):
        at = f"{where}[{index}]"
        stated = _keys(at, item, frozenset({"part", "count", "pattern"}))
        if stated["pattern"] not in PATTERNS:
            raise _invalid(f"{at}.pattern", f"is one of {list(PATTERNS)}")
        held.append(
            (
                _key(f"{at}.part", stated["part"]),
                reader.figure(f"{at}.count", stated["count"], "holding_count", drawn=True),
                str(stated["pattern"]),
            )
        )
    return tuple(held)


@dataclass(frozen=True, slots=True)
class _ReadZone:
    key: str
    label: str
    placement: str
    share: int
    ground: Look
    access: str
    boundary: str
    holds: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class KindDocument:
    """A world kind that passed stage A: the document as written and everything read from it."""

    document: Mapping[str, Any]
    sha256: str
    kind: str
    version: int
    label: str
    summary: str
    origin: str
    enclosure: str
    module_mm: int
    parameters: tuple[KindParameter, ...]
    presets: tuple[tuple[str, str, Mapping[str, int]], ...]
    use_classes: Mapping[str, Mapping[str, Any]]
    employment_permille: int
    parts: Mapping[str, _ReadPart]
    zones: tuple[_ReadZone, ...]
    _site: Mapping[str, Any]
    _offsite: _Figure

    def reference(self) -> dict[str, object]:
        """What a world made from this kind records of it."""
        return {
            "profile": PROFILE,
            "kind": self.kind,
            "version": self.version,
            "sha256": self.sha256,
        }

    def preset(self, key: str) -> Mapping[str, int]:
        for name, _label, values in self.presets:
            if name == key:
                return values
        raise KindValueRefused(
            "unknown_world_recipe", key, key, f"kind {self.kind} has no preset {key!r}"
        )

    def values(self, preset: str, asked: Mapping[str, object] | None = None) -> dict[str, int]:
        """The gate: the preset's values with ``asked`` in place, each held to its parameter."""
        chosen = dict(self.preset(preset))
        by_key = {parameter.key: parameter for parameter in self.parameters}
        for key in sorted(asked or {}, key=str):
            value = (asked or {})[key]
            parameter = by_key.get(key) if type(key) is str else None
            if parameter is None:
                raise KindValueRefused(
                    "specification_value_unknown",
                    str(key),
                    value,
                    f"{key}: kind {self.kind} states no value with that key",
                )
            if (
                type(value) is not int
                or not parameter.minimum <= value <= parameter.maximum
                or (value - parameter.minimum) % parameter.step
            ):
                raise KindValueRefused(
                    "specification_value_out_of_range",
                    key,
                    value,
                    f"{key} ({parameter.label.lower()}) is {value!r}; this kind admits "
                    f"{parameter.minimum} to {parameter.maximum} in steps of {parameter.step}",
                )
            chosen[key] = value
        return dict(sorted(chosen.items()))

    def offsite_residents(self, values: Mapping[str, int]) -> int:
        return self._offsite.fixed(values)

    def society(self, values: Mapping[str, int]) -> SiteSociety:
        """What a world of these values tells its society beside its records: each part's words
        and use class, the defaults a seat and a home take when they name none, and how many people
        come in from homes off the site."""
        uses = {}
        for part in self.parts.values():
            use = part.use_class
            if not use and "seat" in part.roles:
                use = DEFAULT_SEAT_USE
            if not use and "home" in part.roles:
                use = DEFAULT_HOME_USE
            uses[part.key] = PartUse(part.label, use)
        return SiteSociety(
            uses=MappingProxyType(uses), offsite_residents=self.offsite_residents(values)
        )

    def plan(self, values: Mapping[str, int]) -> SitePlan:
        """The site plan these values make: every figure resolved, every span kept for the seed."""
        module = self.module_mm
        parts: list[Any] = []
        for part in self.parts.values():
            fields = part.fields
            roles = part.roles
            if part.form == "path":
                parts.append(PathPart(part.key, roles, part.look, fields["width_mm"].fixed(values)))
            elif part.form == "area":
                parts.append(AreaPart(part.key, roles, part.look))
            elif part.form == "structure":
                parts.append(
                    StructurePart(
                        part.key,
                        roles,
                        part.look,
                        fields["width_mm"].resolve(values, module),
                        fields["depth_mm"].resolve(values, module),
                        fields["storeys"].resolve(values, 1),
                        fields["storey_height_mm"],
                        fields["roof_form"],
                        fields["roof_look"],
                        fields["wall_look"],
                        fields["door_width_mm"],
                        tuple(
                            Holding(name, count.resolve(values, 1), "row")
                            for name, count in fields["rooms"]
                        ),
                    )
                )
            elif part.form == "room":
                parts.append(
                    RoomPart(
                        part.key,
                        roles,
                        part.look,
                        fields["share"],
                        tuple(
                            Holding(name, count.resolve(values, 1), pattern)
                            for name, count, pattern in fields["holds"]
                        ),
                    )
                )
            elif part.form == "fixture":
                parts.append(
                    FixturePart(
                        part.key,
                        roles,
                        part.look,
                        fields["width_mm"],
                        fields["depth_mm"],
                        fields["height_mm"],
                        fields["seats"],
                        fields["stands"],
                        fields["sleepers"],
                        fields["blocks"],
                    )
                )
            else:
                parts.append(
                    BoundaryPart(
                        part.key,
                        part.look,
                        fields["height_mm"],
                        fields["thickness_mm"],
                        fields["gate_width_mm"],
                    )
                )
        site = self._site
        return SitePlan(
            kind=self.kind,
            enclosure=self.enclosure,
            width_mm=site["width_mm"].fixed(values),
            depth_mm=site["depth_mm"].fixed(values),
            module_mm=module,
            ground=site["ground"],
            spine=site["spine"],
            boundary=site["boundary"],
            entry_width_mm=site["entry_width_mm"].fixed(values),
            parts=tuple(parts),
            zones=tuple(
                ZonePlan(
                    zone.key,
                    zone.placement,
                    zone.share,
                    zone.ground,
                    zone.access,
                    zone.boundary,
                    tuple(
                        Holding(name, count.resolve(values, 1), pattern)
                        for name, count, pattern in zone.holds
                    ),
                )
                for zone in self.zones
            ),
        )


def _provenance(where: str, origin: str, raw: object) -> None:
    if origin == "drafted":
        entry = _keys(
            where,
            raw,
            frozenset({"role", "model", "prompt_version", "prompt_sha256", "words_sha256"}),
        )
        for name in ("prompt_sha256", "words_sha256"):
            if type(entry[name]) is not str or _HEX64.fullmatch(entry[name]) is None:
                raise _invalid(f"{where}.{name}", "is a SHA-256 in lowercase hexadecimal")
        for name in ("role", "model", "prompt_version"):
            _text(f"{where}.{name}", entry[name], (1, 200))
        return
    entry = _keys(where, raw, frozenset({"by"}))
    _text(f"{where}.by", entry["by"], (1, 120))


def read_kind(
    document: object,
    *,
    routine: RoutineModel | None = None,
    catalogs: KindCatalogs | None = None,
) -> KindDocument:
    """Read a world kind and hold it to stage A; refuse it by name (:class:`KindRefused`)."""
    if routine is None:
        from exulanica.world.society_living import town_routine

        routine = town_routine()
    catalogs = load_kind_catalogs() if catalogs is None else catalogs
    try:
        canonical_json(document)
    except (CanonicalisationError, TypeError, ValueError) as exc:
        raise _invalid("", f"is not canonical JSON: {exc}") from exc
    raw = _keys("", document, _TOP_KEYS)
    if raw["profile"] != PROFILE:
        raise _invalid("profile", f"is {PROFILE}")
    kind = raw["kind"]
    if type(kind) is not str or _KIND.fullmatch(kind) is None:
        raise _invalid("kind", "is a lowercase key of at most 32 characters")
    version = _int("version", raw["version"], (1, 9999))
    origin = raw["origin"]
    if origin not in ORIGINS:
        raise _invalid("origin", f"is one of {list(ORIGINS)}")
    _provenance("provenance", origin, raw["provenance"])
    licence = _keys("licence", raw["licence"], frozenset({"spdx", "verdict"}))
    if licence["spdx"] not in LICENCES or licence["verdict"] != "SHIP":
        raise _invalid("licence", f"is one of {list(LICENCES)} with the verdict SHIP")
    generator = _keys("generator", raw["generator"], frozenset({"key", "version"}))
    if (generator["key"], generator["version"]) != (GENERATOR_KEY, GENERATOR_VERSION):
        raise KindRefused(
            "kind_reference_unknown",
            f"names generator {generator['key']!r} {generator['version']!r}; a kind read here is "
            f"generated by {GENERATOR_KEY} {GENERATOR_VERSION}",
            "generator",
        )
    reader = _Reader(raw, catalogs, routine)
    site_raw = _keys("site", raw["site"], _SITE_KEYS)
    enclosure = site_raw["enclosure"]
    if enclosure not in ENCLOSURES:
        raise _invalid("site.enclosure", f"is one of {list(ENCLOSURES)}")
    module = catalogs.bound(f"module_{enclosure}_mm")[0]
    _read_parameters(reader, raw["parameters"])
    use_classes = _read_use_classes(reader, raw["use_classes"])
    parts: dict[str, _ReadPart] = {}
    for index, item in enumerate(_list("parts", raw["parts"], reader.bound("parts"))):
        part = _read_part(reader, index, item, module, use_classes)
        if part.key in parts:
            raise _invalid(f"parts[{index}]", f"repeats part {part.key}")
        parts[part.key] = part
    site: dict[str, Any] = {
        "width_mm": reader.figure(
            "site.width_mm", site_raw["width_mm"], "site_width_mm", module=module
        ),
        "depth_mm": reader.figure(
            "site.depth_mm", site_raw["depth_mm"], "site_depth_mm", module=module
        ),
        "entry_width_mm": reader.figure(
            "site.entry_width_mm", site_raw["entry_width_mm"], "entry_width_mm", module=module
        ),
        "ground": reader.look("site.ground", site_raw["ground"], ("ground",)),
    }
    spine = site_raw["spine"]
    if parts.get(spine) is None or parts[spine].form != "path":
        raise KindRefused("kind_reference_unknown", f"names no path part {spine!r}", "site.spine")
    site["spine"] = spine
    boundary = site_raw["boundary"]
    if boundary and (parts.get(boundary) is None or parts[boundary].form != "boundary"):
        raise KindRefused(
            "kind_reference_unknown", f"names no boundary part {boundary!r}", "site.boundary"
        )
    if enclosure == "indoor" and not boundary:
        raise KindRefused(
            "kind_role_unmet", "an indoor site's outer walls are a boundary part", "site.boundary"
        )
    site["boundary"] = boundary
    society = _keys(
        "society", raw["society"], frozenset({"employment_permille", "offsite_residents"})
    )
    employment = _int("society.employment_permille", society["employment_permille"], (1, 1000))
    offsite = reader.figure(
        "society.offsite_residents", society["offsite_residents"], "offsite_residents"
    )
    zones: list[_ReadZone] = []
    for index, item in enumerate(_list("zones", raw["zones"], reader.bound("zones"))):
        where = f"zones[{index}]"
        entry = _keys(
            where,
            item,
            frozenset(
                {"key", "label", "placement", "share", "ground", "access", "boundary", "holds"}
            ),
        )
        key = _key(f"{where}.key", entry["key"])
        if any(zone.key == key for zone in zones):
            raise _invalid(where, f"repeats zone {key}")
        if entry["placement"] not in PLACEMENTS:
            raise _invalid(f"{where}.placement", f"is one of {list(PLACEMENTS)}")
        if entry["access"] not in ACCESS:
            raise _invalid(f"{where}.access", f"is one of {list(ACCESS)}")
        zone_boundary = entry["boundary"]
        if zone_boundary and (
            parts.get(zone_boundary) is None or parts[zone_boundary].form != "boundary"
        ):
            raise KindRefused(
                "kind_reference_unknown",
                f"names no boundary part {zone_boundary!r}",
                f"{where}.boundary",
            )
        holds = _holdings(reader, f"{where}.holds", entry["holds"], allow_empty=False)
        for name, _count, pattern in holds:
            held = parts.get(name)
            if held is None or held.form not in ("area", "structure", "fixture"):
                raise KindRefused(
                    "kind_reference_unknown",
                    f"holds {name!r}, which is no area, structure or fixture of the kind",
                    f"{where}.holds",
                )
            if (pattern == "fill") != (held.form == "area"):
                raise _invalid(f"{where}.holds", f"exactly an area fills; {name} is a {held.form}")
            if held.form == "structure" and pattern != "row":
                raise _invalid(f"{where}.holds", f"structures stand in a row, not {pattern}")
            if pattern == "back_wall":
                raise _invalid(f"{where}.holds", "a zone has no back wall; a room has")
        zones.append(
            _ReadZone(
                key=key,
                label=_text(f"{where}.label", entry["label"], reader.bound("label_characters")),
                placement=str(entry["placement"]),
                share=_int(f"{where}.share", entry["share"], (1, 1000)),
                ground=reader.look(f"{where}.ground", entry["ground"], ("ground",)),
                access=str(entry["access"]),
                boundary=zone_boundary,
                holds=holds,
            )
        )
    if sum(1 for zone in zones if zone.placement == "edge_back") > 1:
        raise _invalid("zones", "at most one zone lies across the far edge")
    for part in parts.values():
        if part.form == "structure":
            for name, _count in part.fields["rooms"]:
                if parts.get(name) is None or parts[name].form != "room":
                    raise KindRefused(
                        "kind_reference_unknown", f"holds no room {name!r}", f"part {part.key}"
                    )
                if not set(parts[name].roles) <= set(part.roles):
                    raise KindRefused(
                        "kind_role_unmet",
                        f"room {name} takes {list(parts[name].roles)}, outside its structure's "
                        f"{list(part.roles)}",
                        f"part {part.key}",
                    )
        if part.form == "room":
            for name, _count, pattern in part.fields["holds"]:
                if parts.get(name) is None or parts[name].form != "fixture":
                    raise KindRefused(
                        "kind_reference_unknown", f"holds no fixture {name!r}", f"part {part.key}"
                    )
                if pattern == "fill":
                    raise _invalid(f"part {part.key}", "a room's fixtures are not laid out by fill")
    _check_parameter_uses(reader)
    presets: list[tuple[str, str, Mapping[str, int]]] = []
    for index, item in enumerate(_list("presets", raw["presets"], reader.bound("presets"))):
        where = f"presets[{index}]"
        entry = _keys(where, item, frozenset({"key", "label", "values"}))
        key = _key(f"{where}.key", entry["key"])
        if any(name == key for name, _, _ in presets):
            raise _invalid(where, f"repeats preset {key}")
        values = entry["values"]
        if not isinstance(values, dict) or set(values) != set(reader.parameters):
            raise _invalid(
                f"{where}.values", f"states every parameter: {sorted(reader.parameters)}"
            )
        for name, value in values.items():
            parameter = reader.parameters[name]
            if (
                type(value) is not int
                or not parameter.minimum <= value <= parameter.maximum
                or (value - parameter.minimum) % parameter.step
            ):
                raise KindRefused(
                    "kind_out_of_bounds",
                    f"{name} is {value!r}, outside {parameter.minimum} to {parameter.maximum} in "
                    f"steps of {parameter.step}",
                    f"{where}.values",
                )
        presets.append(
            (
                key,
                _text(f"{where}.label", entry["label"], reader.bound("label_characters")),
                MappingProxyType(dict(sorted(values.items()))),
            )
        )
    return KindDocument(
        document=MappingProxyType(dict(raw)),
        sha256=sha256_of_canonical(raw).hex(),
        kind=kind,
        version=version,
        label=_text("label", raw["label"], reader.bound("label_characters")),
        summary=_text("summary", raw["summary"], reader.bound("summary_characters")),
        origin=origin,
        enclosure=enclosure,
        module_mm=module,
        parameters=tuple(reader.parameters.values()),
        presets=tuple(presets),
        use_classes=MappingProxyType(use_classes),
        employment_permille=employment,
        parts=MappingProxyType(parts),
        zones=tuple(zones),
        _site=MappingProxyType(site),
        _offsite=offsite,
    )
