"""A world kind: one typed, versioned, fingerprinted document, read and held to its checks.

A world kind states a kind of place a person can make worlds of (a farm, a building site, a
cafe, a harbour) as data, profiles ``exulanica.world-kind/v1`` and ``exulanica.world-kind/v2``:
its parts in plain words with the engine roles that say what the engine does with each, its zones
and how they are laid out, its own
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

Pure: no connection, no store, no clock. The field reader is :mod:`exulanica.world.kinds.reader`'s,
and a kind's parts and zones are read by :mod:`exulanica.world.kinds.parts`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, cast

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.errors import CanonicalisationError
from exulanica.grammar.catalogs import FieldValue
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.grammars.site.plan import (
    ACCESS,
    ENCLOSURES,
    PLACEMENTS,
    Arcade,
    AreaPart,
    BoundaryPart,
    FixturePart,
    Holding,
    PathPart,
    RoomPart,
    SitePlan,
    StructurePart,
    ZonePlan,
)
from exulanica.world.kinds.catalogs import KindCatalogs, load_arcade_catalog, load_kind_catalogs
from exulanica.world.kinds.parts import (
    _check_size,
    _holdings,
    _offsite_home,
    _place_words,
    _read_part,
    _ReadPart,
    _ReadZone,
)
from exulanica.world.kinds.reader import (
    PROFILE,
    REQUIREMENTS_PROFILE,
    KindParameter,
    KindRefused,
    KindValueRefused,
    _Figure,
    _int,
    _invalid,
    _key,
    _keys,
    _list,
    _Reader,
    _text,
)
from exulanica.world.society_catalogs import SCHEMAS, RoutineModel
from exulanica.world.society_site_place import ArcadeUse, PartUse, SiteSociety

__all__ = [
    "GENERATOR_KEY",
    "GENERATOR_VERSION",
    "KIND_CODES",
    "LICENCES",
    "ORIGINS",
    "PROFILE",
    "REQUIREMENTS_PROFILE",
    "KindDocument",
    "KindParameter",
    "KindRefused",
    "KindValueRefused",
    "bounds_version_of",
    "read_kind",
]

#: The kind bounds each profile is read with when the kind names none, so a kind written before a
#: later bounds version reads exactly as it always did.
PROFILE_BOUNDS: Final = {PROFILE: 1, REQUIREMENTS_PROFILE: 2}
#: The bounds versions a kind may name in its optional ``bounds``: 3, version 2's bounds with
#: taller structures (the bounds catalog states how tall and why).
NAMED_BOUNDS: Final = (3,)
#: The composer that generates every kind this module reads: the site grammar's.
GENERATOR_KEY: Final = "site-plan"
GENERATOR_VERSION: Final = 1
ORIGINS: Final = ("authored", "drafted", "uploaded", "imported")
#: The licences a kind may carry: the repository's own and the permissive ones the licence matrix
#: ships content under. Anything else is refused, never shipped.
LICENCES: Final = ("Apache-2.0", "CC-BY-4.0", "CC0-1.0", "MIT")
_KIND: Final = re.compile(r"[a-z][a-z0-9_]{0,31}")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
#: The refusals a kind meets, by stage A and stage B, each with what it means.
KIND_CODES: Final = (
    ("kind_requirement_unmet", "A declared requirement does not match its placed parts."),
    ("kind_shape_unmet", "A part does not meet its pinned structural class."),
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
        "kind_layout_over_budget",
        (
            "Laying out a sample world would try more placements than the bounds catalog allows: "
            "the kind asks for parts where they seldom fit, or for more searching than a world may "
            "take."
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
        for name in ("label", "role_label"):
            _text(f"{where}.{name}", entry[name], reader.bound("label_characters"))
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
    #: What the society reads where the kind states nothing, resolved once as the kind is read: the
    #: use class a seat and a home take when they name none (``kind-society`` catalog), and the
    #: home at the entry of everybody who lives off the site, as the kind states it or as the
    #: catalog does.
    _seat_use: str
    _home_use: str
    _offsite_home: PartUse
    #: The words said of where its people are and walk (``here``, ``around``), as the kind states
    #: them or as the catalog does.
    _place_words: tuple[str, str]

    def reference(self) -> dict[str, object]:
        """What a world made from this kind records of it."""
        return {
            "profile": self.document["profile"],
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
                use = self._seat_use
            if not use and "home" in part.roles:
                use = self._home_use
            uses[part.key] = PartUse(part.label, use)
        stood = [
            part
            for part in self.parts.values()
            if "arcade" in part.fields and part.fields["arcade"].use_class
        ]
        # Standing places per bay where a kind names none: the least the catalog allows.
        least = load_arcade_catalog(version=3).bound("stands_per_bay")[0] if stood else 0
        arcades = {
            part.key: ArcadeUse(
                part.fields["arcade"].use_class, part.fields["arcade"].stands_per_bay or least
            )
            for part in stood
        }
        return SiteSociety(
            uses=MappingProxyType(uses),
            offsite_residents=self.offsite_residents(values),
            offsite_home=self._offsite_home,
            here=self._place_words[0],
            around=self._place_words[1],
            arcades=MappingProxyType(arcades),
        )

    @property
    def arcaded(self) -> bool:
        """Whether a structure of this kind states an arcade, so its worlds read the arcade
        catalog."""
        return any("arcade" in part.fields for part in self.parts.values())

    @property
    def arcade_version(self) -> int:
        """The arcade catalog version this kind's arcades are laid out by: the newest any of its
        arcades needs (each version states every figure of the one before unchanged), 1 for
        arcades of bays and depth alone; 0 for a kind with no arcade."""
        return max(
            (
                part.fields["arcade"].version
                for part in self.parts.values()
                if "arcade" in part.fields
            ),
            default=0,
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
        arcade = load_arcade_catalog(version=self.arcade_version) if self.arcaded else None
        arcades = tuple(
            Arcade(
                part.key,
                part.fields["arcade"].bays,
                part.fields["arcade"].depth_mm,
                arcade.bound("pier_mm")[0],
                part.fields["storey_height_mm"] - arcade.bound("lintel_mm")[0],
                arcade.bound("least_opening_mm")[0],
                part.fields["arcade"].sides or 1,
            )
            for part in self.parts.values()
            if arcade is not None and "arcade" in part.fields
        )
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
            arcades=arcades,
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


def _strings(node: object, where: str = "") -> Iterator[tuple[str, str]]:
    """Every string a JSON document holds, its keys included, each with where it is, in document
    order."""
    if isinstance(node, str):
        yield where, node
    elif isinstance(node, dict):
        for key, value in node.items():
            at = f"{where}.{key}" if where else str(key)
            if isinstance(key, str):
                yield at, key
            yield from _strings(value, at)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _strings(value, f"{where}[{index}]")


def bounds_version_of(document: object) -> int:
    """The kind bounds version ``document`` is read with: the version its optional ``bounds``
    names, else its profile's own (``PROFILE_BOUNDS``). A statement that is not one of
    ``NAMED_BOUNDS`` is left to :func:`read_kind` to refuse by name; until then it chooses
    nothing."""
    if not isinstance(document, Mapping):
        return 1
    stated = document.get("bounds")
    if isinstance(stated, Mapping) and set(stated) == {"version"}:
        version = stated["version"]
        if type(version) is int and version in NAMED_BOUNDS:
            return version
    profile = document.get("profile")
    return PROFILE_BOUNDS.get(profile, 1) if isinstance(profile, str) else 1


def read_kind(
    document: object,
    *,
    routine: RoutineModel | None = None,
    catalogs: KindCatalogs | None = None,
) -> KindDocument:
    """Read a world kind and hold it to stage A; refuse it by name (:class:`KindRefused`)."""
    for where, text in _strings(document):
        if "\x00" in text:
            # Not text a kind may hold anywhere, and not text the database's JSON can keep.
            raise _invalid(where, "holds no control, format or private-use characters")
    if routine is None:
        from exulanica.world.society_living import town_routine

        routine = town_routine()
    profile = document.get("profile") if isinstance(document, dict) else None
    catalogs = (
        load_kind_catalogs(bounds_version=bounds_version_of(document))
        if catalogs is None
        else catalogs
    )
    try:
        canonical_json(document)
    except (CanonicalisationError, TypeError, ValueError) as exc:
        raise _invalid("", f"is not canonical JSON: {exc}") from exc
    raw = _keys(
        "",
        document,
        _TOP_KEYS
        | ({"requirement_source", "requirements"} if profile == REQUIREMENTS_PROFILE else set())
        | ({"bounds"} if isinstance(document, dict) and "bounds" in document else set()),
    )
    if raw["profile"] not in (PROFILE, REQUIREMENTS_PROFILE):
        raise _invalid("profile", f"is {PROFILE} or {REQUIREMENTS_PROFILE}")
    if "bounds" in raw:
        # Optional in both profiles: absent, a kind reads with its profile's own bounds, as every
        # kind written before it did. Named, the kind is read, sampled and regenerated with it.
        stated = _keys("bounds", raw["bounds"], frozenset({"version"}))
        if type(stated["version"]) is not int or stated["version"] not in NAMED_BOUNDS:
            raise _invalid("bounds.version", f"is one of {list(NAMED_BOUNDS)}")
        if catalogs.bounds_version != stated["version"]:
            raise _invalid(
                "bounds.version",
                f"names bounds {stated['version']}, and this reader was given bounds "
                f"{catalogs.bounds_version}",
            )
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
    if type(spine) is not str or parts.get(spine) is None or parts[spine].form != "path":
        raise KindRefused("kind_reference_unknown", f"names no path part {spine!r}", "site.spine")
    site["spine"] = spine
    boundary = site_raw["boundary"]
    if type(boundary) is not str:
        raise _invalid("site.boundary", "is a boundary part's key, or empty for none")
    if boundary and (parts.get(boundary) is None or parts[boundary].form != "boundary"):
        raise KindRefused(
            "kind_reference_unknown", f"names no boundary part {boundary!r}", "site.boundary"
        )
    if enclosure == "indoor" and not boundary:
        raise KindRefused(
            "kind_role_unmet", "an indoor site's outer walls are a boundary part", "site.boundary"
        )
    site["boundary"] = boundary
    stated_society = raw["society"]
    optional = (
        set(stated_society) & {"offsite_home", "place_words"}
        if isinstance(stated_society, dict)
        else set()
    )
    society = _keys(
        "society",
        stated_society,
        frozenset({"employment_permille", "offsite_residents", *optional}),
    )
    employment = _int("society.employment_permille", society["employment_permille"], (1, 1000))
    offsite = reader.figure(
        "society.offsite_residents", society["offsite_residents"], "offsite_residents"
    )
    offsite_home = _offsite_home(reader, society.get("offsite_home"), use_classes)
    place_words = _place_words(reader, society.get("place_words"))
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
        if type(zone_boundary) is not str:
            raise _invalid(f"{where}.boundary", "is a boundary part's key, or empty for none")
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
    _check_size(reader, parts, zones, site, module)
    if profile == REQUIREMENTS_PROFILE:
        from exulanica.world.kinds.requirements import check_requirements

        check_requirements(raw, parts, zones, site, reader)
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
        _seat_use=reader.catalogs.society_defaults["seat"].use_class,
        _home_use=reader.catalogs.society_defaults["home"].use_class,
        _offsite_home=offsite_home,
        _place_words=place_words,
    )
