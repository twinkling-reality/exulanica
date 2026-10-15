"""How a world kind's parts and zones are read and held to their roles and sizes.

A part in plain words, its form and the look that form takes, the engine roles that say what the
engine does with it and the needs each role states (a seat with no seats, a workplace with no
workplace use class), the arcade a building may open, the homes a society keeps off the site, and a
part's and a zone's size against the site and the bounds catalog. Stage A of a kind's checks, read
for :func:`~exulanica.world.kinds.document.read_kind`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from exulanica.grammar.grammars.site.layout import DOOR_HEIGHT_MM
from exulanica.grammar.grammars.site.plan import FORMS, PATTERNS, ROOF_FORMS, Look
from exulanica.grammar.records import KEY_PATTERN
from exulanica.world.kinds.catalogs import load_arcade_catalog
from exulanica.world.kinds.reader import (
    REQUIREMENTS_PROFILE,
    KindRefused,
    _Figure,
    _int,
    _invalid,
    _key,
    _keys,
    _list,
    _Reader,
    _text,
)
from exulanica.world.society_site_place import PartUse

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


@dataclass(frozen=True, slots=True)
class _StatedArcade:
    """A structure's arcade as its kind states it, with the arcade catalog version it is read by."""

    bays: int
    depth_mm: int
    sides: int | None
    use_class: str
    stands_per_bay: int | None
    version: int


#: The keys an arcade may state beyond its bays and depth, and the arcade catalog version that
#: first reads each: a kind stating none of them reads version 1, as it did before they existed.
_ARCADE_OPTIONAL: Final = {"sides": 2, "use_class": 3, "stands_per_bay": 3}


def _arcade(where: str, raw: object, module: int) -> _StatedArcade:
    """A structure's arcade: how many bays its front has, how deep its covered walk is and,
    optionally, on how many sides it runs (its front, or its front and its back), the use class
    people stand under its arches by and how many stand in each bay, each held to the arcade
    catalog version that states it (``structure-arcade.v<N>.json``); the depth a whole number of
    the site's module."""
    optional = set(raw) & set(_ARCADE_OPTIONAL) if isinstance(raw, dict) else set()
    stated = _keys(where, raw, frozenset({"bays", "depth_mm"} | optional))
    version = max((_ARCADE_OPTIONAL[key] for key in optional), default=1)
    catalog = load_arcade_catalog(version=version)
    bays = _int(f"{where}.bays", stated["bays"], catalog.bound("bays"))
    depth = _int(f"{where}.depth_mm", stated["depth_mm"], catalog.bound("depth_mm"))
    if depth % module:
        raise KindRefused(
            "kind_out_of_bounds",
            f"{depth} mm is not whole {module} mm modules",
            f"{where}.depth_mm",
        )
    figure = {
        key: _int(f"{where}.{key}", stated[key], catalog.bound(key))
        for key in ("sides", "stands_per_bay")
        if key in stated
    }
    use_class = stated.get("use_class", "")
    if "use_class" in stated and (
        type(use_class) is not str or KEY_PATTERN.fullmatch(use_class) is None
    ):
        raise _invalid(f"{where}.use_class", "is a use class key")
    if "stands_per_bay" in stated and not use_class:
        raise KindRefused(
            "kind_role_unmet",
            "people stand under the arches by a use class, so standing places name one",
            f"{where}.stands_per_bay",
        )
    return _StatedArcade(
        bays, depth, figure.get("sides"), use_class, figure.get("stands_per_bay"), version
    )


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
    shaped = reader.raw["profile"] == REQUIREMENTS_PROFILE and "shape_class" in raw
    # A structure's arcade is optional in both profiles: absent, the structure reads as before.
    arcaded = form == "structure" and "arcade" in raw
    entry = _keys(
        where,
        raw,
        _PART_COMMON
        | _PART_KEYS[form]
        | ({"shape_class"} if shaped else set())
        | ({"arcade"} if arcaded else set()),
    )
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
        if arcaded:
            fields["arcade"] = _arcade(f"{where}.arcade", entry["arcade"], module)
    elif form == "room":
        fields["share"] = _int(f"{where}.share", entry["share"], reader.bound("room_share"))
        fields["holds"] = _holdings(reader, f"{where}.holds", entry["holds"], allow_empty=True)
    elif form == "fixture":
        for name in ("width_mm", "depth_mm", "height_mm"):
            bound = (
                "fixture_height_mm"
                if (name == "height_mm" and reader.raw["profile"] == REQUIREMENTS_PROFILE)
                else "fixture_size_mm"
            )
            fields[name] = _int(f"{where}.{name}", entry[name], reader.bound(bound))
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
    if arcaded:
        walk_use = fields["arcade"].use_class
        if walk_use and (
            _use_kind(reader, use_classes, walk_use) != "furniture"
            or "visit" not in _offers(reader, use_classes, walk_use)
        ):
            raise KindRefused(
                "kind_role_unmet"
                if _use_kind(reader, use_classes, walk_use)
                else "kind_reference_unknown",
                f"people stand under the arches by furniture people visit, not {walk_use!r}",
                f"{where}.arcade.use_class",
            )
        if not roles and not fields["rooms"]:
            raise KindRefused(
                "kind_role_unmet",
                "an arcade leads to the structure's door, so the structure takes a role or rooms",
                f"{where}.arcade",
            )
        least = DOOR_HEIGHT_MM + load_arcade_catalog().bound("lintel_mm")[0]
        if fields["storey_height_mm"] < least:
            raise KindRefused(
                "kind_out_of_bounds",
                f"an arch is at least a door's {DOOR_HEIGHT_MM} mm high under its head, so an "
                f"arcaded structure's storey is at least {least} mm, not "
                f"{fields['storey_height_mm']}",
                f"{where}.arcade",
            )
    if shaped:
        from exulanica.world.kinds.shape_classes import (
            ShapeRefused,
            check_shape,
            read_shape_reference,
        )

        try:
            shape = read_shape_reference(entry["shape_class"], form)
            check_shape(shape, fields, reader.limits)
        except ShapeRefused as refused:
            raise KindRefused("kind_shape_unmet", str(refused), f"{where}.shape_class") from refused
        fields["shape_class"] = dict(entry["shape_class"])
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


def _offsite_home(
    reader: _Reader, raw: object, use_classes: Mapping[str, Mapping[str, Any]]
) -> PartUse:
    """The home at the entry of everybody who lives off the site: as the kind states it (its words
    and a residential use class), else as the ``kind-society`` catalog does."""
    if raw is None:
        default = reader.catalogs.society_defaults["offsite_home"]
        return PartUse(default.words, default.use_class)
    where = "society.offsite_home"
    stated = _keys(where, raw, frozenset({"label", "use_class"}))
    label = _text(f"{where}.label", stated["label"], reader.bound("label_characters"))
    use_class = _key(f"{where}.use_class", stated["use_class"])
    kind = _use_kind(reader, use_classes, use_class)
    if not kind:
        raise KindRefused("kind_reference_unknown", f"names no use class {use_class!r}", where)
    if kind != "residential":
        raise KindRefused(
            "kind_role_unmet", f"is a home, so its use class is residential, not {kind}", where
        )
    return PartUse(label, use_class)


def _place_words(reader: _Reader, raw: object) -> tuple[str, str]:
    """What is said of where the kind's people are (``here``: "on this farm") and walk
    (``around``: "across the farm"), as the kind states it, else as the ``kind-society`` catalog
    does: words a person reads in place of a town's ("in this town", "through town")."""
    defaults = reader.catalogs.society_defaults
    if raw is None:
        return (defaults["here"].words, defaults["around"].words)
    where = "society.place_words"
    stated = _keys(where, raw, frozenset({"here", "around"}))
    bound = reader.bound("label_characters")
    return (
        _text(f"{where}.here", stated["here"], bound),
        _text(f"{where}.around", stated["around"], bound),
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


def _most(reader: _Reader, figure: _Figure) -> int:
    """The largest value a figure can take: itself, its parameter's maximum, or its span's end."""
    if figure.value is not None:
        return figure.value
    if figure.parameter:
        return reader.parameters[figure.parameter].maximum
    return figure.end


def _check_size(
    reader: _Reader,
    parts: Mapping[str, _ReadPart],
    zones: Sequence[_ReadZone],
    site: Mapping[str, Any],
    module: int,
) -> None:
    """Refuse, before anything is generated, a kind whose site is laid on more grid points or
    which places more things than the bounds catalog allows (``grid_points``,
    ``placed_things``), each figure at its most."""
    width, depth = _most(reader, site["width_mm"]), _most(reader, site["depth_mm"])
    points = (width // module) * (depth // module)
    low, high = reader.bound("grid_points")
    if not low <= points <= high:
        raise KindRefused(
            "kind_out_of_bounds",
            f"is laid on {points} grid points at its largest, outside {low} to {high}",
            "site",
        )

    def inside(part: _ReadPart) -> int:
        if part.form == "room":
            return sum(_most(reader, count) for _name, count, _pattern in part.fields["holds"])
        if part.form == "structure":
            return sum(
                _most(reader, count) * (1 + inside(parts[name]))
                for name, count in part.fields["rooms"]
            )
        return 0

    placed = sum(
        _most(reader, count) * (1 + inside(parts[name]))
        for zone in zones
        for name, count, _pattern in zone.holds
    )
    low, high = reader.bound("placed_things")
    if not low <= placed <= high:
        raise KindRefused(
            "kind_out_of_bounds",
            f"places {placed} things at its most, outside {low} to {high}",
            "zones",
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
