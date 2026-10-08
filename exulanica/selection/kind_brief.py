"""A kind of world as a model drafts it: a brief with no keys, compiled into a kind document.

A model writes what a place holds, nested as a person would say it: zones holding structures,
areas and fixtures, structures holding rooms and rooms holding fixtures, each part used as a home,
a workplace or a shop stating that use where it stands. It names nothing twice, so nothing it
names can be missing. The compiler (:func:`compile_brief`) makes the kind document:

*   **keys and references** from the labels, each once, so every part a zone, a structure or a
    room holds, every use class a part names, the spine and the boundary are the document's own;
*   **use classes** from each part's own use: a workplace's staff, hours and shifts, a shop's
    visitors, a home's residents where no bed in it says them, a gathering spot's furniture (a
    seat's too where it is also a gathering spot); a use stated twice in the same words is one
    class; a fixture stated as a seat or a gathering spot stays one, and is not also a workplace
    or a shop;
*   **figures** keep their meaning and the document's shape: a span runs least first, a length
    the layout steps along is whole modules, a fixture's seats and standing places are as many as
    fit along its front at the society's standing spacing (at least one where its role needs
    them), a bed sleeps one or two and nothing else sleeps anyone, a workplace open no minute of
    the day is open all of it, the entry is as wide as the spine, and a zone holding anything
    people use is open to them;
*   **who comes in**: where nobody lives on the site and the brief says nobody comes in, the
    people who work there come in from homes off it;
*   **the size**: the site is at least as deep as the layout's own need function
    (:func:`~exulanica.grammar.grammars.site.layout._need`, read there, never copied) says its
    zones need along the spine, then the kind's sample worlds are built as the checks build them
    (:func:`~exulanica.world.kinds.samples.check_samples`): where the layout says the site or a
    structure is too small, by its own figures, it is grown by them; where the walking graph is
    over budget the site is shrunk, never to a size the layout found too small; where the people
    there are out of bounds or nobody would work, the people coming in are changed within the
    bounds; where a place indoors is unreached, the walls round its zones become an inner wall of
    their own, thinner; and once the samples pass, a site holding no area is trimmed to room to
    spare round the smallest that passes.

The kind checks still decide whether the kind is kept: the compiler changes only what this
docstring lists, and a kind its samples refuse for any other reason is handed on as it is. Pure:
nothing is read from a connection and nothing is written.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from exulanica.grammar.errors import InvalidParameterError, InvalidRecordError
from exulanica.grammar.grammars.site.plan import (
    ACCESS,
    ENCLOSURES,
    PATTERNS,
    PLACEMENTS,
    ROOF_FORMS,
)
from exulanica.world.kinds.catalogs import KindCatalogs, load_kind_catalogs
from exulanica.world.kinds.document import GENERATOR_KEY, GENERATOR_VERSION, PROFILE, KindRefused
from exulanica.world.society_catalogs import RoutineModel

__all__ = [
    "COMPILED_ROLES",
    "DRAFTED_PRESET",
    "FORM_LOOKS",
    "ROOM_FIXTURE_PATTERNS",
    "USE_ROLES",
    "ZONE_FIXTURE_PATTERNS",
    "Compiled",
    "brief_form",
    "brief_where",
    "compile_brief",
]

_KEY: Final = r"[a-z][a-z0-9_]{0,47}"
#: The one preset a drafted kind states: the world its description asks for.
DRAFTED_PRESET: Final = {"key": "as_described", "label": "As described", "values": {}}
#: The look families each form's own look may name, as the kind reader holds them.
FORM_LOOKS: Final = {
    "path": ("path", "road"),
    "area": ("ground", "water", "road", "path", "plant"),
    "structure": ("structure",),
    "room": ("ground",),
    "fixture": ("fixture", "prop", "plant", "vehicle", "animal"),
    "boundary": ("boundary", "wall"),
}
#: What a part is used as: a part takes at most one, asked as one choice beside its other roles.
USE_ROLES: Final = ("home", "shop", "workplace")
#: The roles the compiler gives the spine and the boundary, which the brief never lists.
COMPILED_ROLES: Final = ("path", "road", "boundary")
#: The roles of the things people use, which keep the zone holding them open to them.
_USED_ROLES: Final = frozenset({"home", "shop", "workplace", "seat", "gathering", "bed"})
#: The patterns a zone lays its fixtures out by (an area fills, structures stand in a row), and a
#: room its fixtures (along its back wall too).
ZONE_FIXTURE_PATTERNS: Final = tuple(p for p in PATTERNS if p not in ("fill", "back_wall"))
ROOM_FIXTURE_PATTERNS: Final = tuple(p for p in PATTERNS if p != "fill")
#: A use class's fields where its kind states none: no role, nobody, open all day.
_USE_NONE: Final = {
    "role_key": "none",
    "role_label": "none",
    "staff_per_unit": 0,
    "visitor_capacity": 0,
    "resident_capacity": 0,
    "visitor_affordances": [],
    "opening_minute": 0,
    "closing_minute": 1440,
    "shifts": [],
}
#: How many times the samples are built while sizing, at most; and, once they pass, how many
#: halvings look for the smallest site that passes, each way, and for the smallest each structure
#: sizing grew may be. Sizing answers a quarter at a time, and a structure grown for its rooms
#: usually needs the site answered twice more (a side too short, a zone too shallow), so one
#: structure grown from the least the bounds allow to the most takes 16 growths and about 48
#: rounds. Drafted kinds measured needing 18 and 26 rounds were refused at 16; a round builds the
#: samples once, at most 0.13 s on those kinds.
_SIZING_STEPS: Final = 64
_TRIM_STEPS: Final = 6
#: The most a drafted site holding no area is, each way, of the smallest that passes: room to
#: spare round what it holds, never a small place lost on a large empty lot. A site holding areas
#: keeps its size, which they fill. The hand-written cafe and building site lie at 1.9 and 1.86
#: of their smallest each way; a small bakery was drafted at 3.16.
_ROOM_TO_SPARE: Final = (2, 1)
#: The layout's own sentences (:mod:`~exulanica.grammar.grammars.site.layout`) that say by how
#: much a site is too small, read for their figures; and the sample checks' about its people.
_SIDE_SHORT: Final = re.compile(r"is (\d+) mm long and its zones need (\d+) mm")
_LOT_SHALLOW: Final = re.compile(
    r"zone ([a-z][a-z0-9_]*) is (\d+) mm deep and a structure \d+ mm deep needs (\d+) mm"
)
_AREAS_SHALLOW: Final = re.compile(
    r"zone ([a-z][a-z0-9_]*) leaves (-?\d+) mm for its areas, under (\d+) mm"
)
_EDGE_TAKES: Final = re.compile(
    r"zone ([a-z][a-z0-9_]*) takes (-?\d+) mm of a site \d+ mm deep, leaving the rest (-?\d+) mm"
)
_IN_ROOM: Final = re.compile(r" room ([a-z][a-z0-9_]*) holding \d+: ")
_ROOMS_TIGHT: Final = re.compile(
    r": ([a-z][a-z0-9_]*) is \d+ mm (?:along its front and its \d+ rooms leave|deep, too shallow)"
)
_HOUSES: Final = re.compile(r"it houses (\d+) people; a world houses (\d+) to (\d+)")
_NOBODY_WORKS: Final = re.compile(r"and (\d+) residents of whom (\d+) per mille work")


# -- the form -------------------------------------------------------------------------------------


def _model(name: str, fields: Mapping[str, Any]) -> type[BaseModel]:
    return create_model(  # type: ignore[call-overload,no-any-return]
        name, __config__=ConfigDict(extra="forbid"), **dict(fields)
    )


def _text(bounds: tuple[int, int]) -> Any:
    return Annotated[str, Field(min_length=bounds[0], max_length=bounds[1])]


def _whole(bounds: tuple[int, int]) -> Any:
    return Annotated[int, Field(ge=bounds[0], le=bounds[1])]


def _look(families: Sequence[str]) -> Any:
    return Annotated[str, Field(pattern=f"^({'|'.join(families)})\\.{_KEY}$")]


def _other_roles(form: str, catalogs: KindCatalogs) -> Any:
    """The roles a part of ``form`` may list besides its use role and the compiler's own."""
    allowed = tuple(
        sorted(
            role
            for role, forms in catalogs.role_forms.items()
            if form in forms and role not in USE_ROLES and role not in COMPILED_ROLES
        )
    )
    return list[Literal[allowed]]  # type: ignore[valid-type]


def _use_role(form: str, catalogs: KindCatalogs) -> Any:
    """What a part of ``form`` is used as: one of the use roles that form may take, or none."""
    allowed = tuple(r for r in USE_ROLES if form in catalogs.role_forms.get(r, ()))
    return Literal[("", *allowed)]  # type: ignore[valid-type]


#: Forms already built, by the digests of the catalogs and the routine they were built from.
_BRIEFS: Final[dict[tuple[object, ...], type[BaseModel]]] = {}


def brief_form(
    catalogs: KindCatalogs | None = None, routine: RoutineModel | None = None
) -> type[BaseModel]:
    """The brief a model fills: what the place holds, nested, with no keys and no references;
    every closed word a list to choose from, and each object's arrays last."""
    catalogs = load_kind_catalogs() if catalogs is None else catalogs
    if routine is None:
        from exulanica.world.society_living import town_routine

        routine = town_routine()
    built = (tuple(sorted(catalogs.sha256.items())), routine.sha256)
    found = _BRIEFS.get(built)
    if found is None:
        found = _BRIEFS[built] = _build(catalogs, routine)
    return found


def _build(catalogs: KindCatalogs, routine: RoutineModel) -> type[BaseModel]:
    bound = catalogs.bound
    label = _text(bound("label_characters"))
    description = _text(bound("description_characters"))
    minute = _whole((0, 1440))
    holdings = bound("holdings")[1]

    def span(name: str, bounds: tuple[int, int]) -> type[BaseModel]:
        return _model(name, {"from": (_whole(bounds), ...), "to": (_whole(bounds), ...)})

    def listed(item: type[BaseModel], most: int, least: int = 0) -> Any:
        return Annotated[list[item], Field(min_length=least, max_length=most)]  # type: ignore[valid-type]

    count = span("Count", (1, bound("holding_count")[1]))
    affordances = tuple(sorted({a.affordance for a in routine.activities.values()}))
    shifts = tuple(sorted(routine.shifts))
    work = _model(
        "Work",
        {
            "role_label": (label, ...),
            "staff_per_unit": (_whole((1, 64)), ...),
            "opening_minute": (minute, ...),
            "closing_minute": (minute, ...),
            "shifts": (listed(Literal[shifts], len(shifts), 1), ...),  # type: ignore[valid-type]
        },
    )
    visit = _model(
        "Visit",
        {
            "visitor_capacity": (_whole((1, 128)), ...),
            "visitor_affordances": (
                listed(Literal[affordances], len(affordances), 1),  # type: ignore[valid-type]
                ...,
            ),
        },
    )
    sizes = bound("fixture_size_mm")
    places = bound("fixture_places")

    def fixture(name: str, patterns: tuple[str, ...]) -> type[BaseModel]:
        return _model(
            name,
            {
                "label": (label, ...),
                "description": (description, ...),
                "look": (_look(FORM_LOOKS["fixture"]), ...),
                "count": (count, ...),
                "pattern": (Literal[patterns], ...),
                "width_mm": (_whole(sizes), ...),
                "depth_mm": (_whole(sizes), ...),
                "height_mm": (_whole(sizes), ...),
                "seats": (_whole(places), ...),
                "stands": (_whole(places), ...),
                "sleepers": (_whole(bound("sleepers")), ...),
                "blocks": (bool, ...),
                "use_role": (_use_role("fixture", catalogs), ...),
                "roles": (_other_roles("fixture", catalogs), ...),
                "work": (listed(work, 1), ...),
                "visit": (listed(visit, 1), ...),
            },
        )

    room_fixture = fixture("RoomFixture", ROOM_FIXTURE_PATTERNS)
    room = _model(
        "Room",
        {
            "label": (label, ...),
            "description": (description, ...),
            "look": (_look(FORM_LOOKS["room"]), ...),
            "count": (count, ...),
            "share": (_whole(bound("room_share")), ...),
            "fixtures": (listed(room_fixture, holdings), ...),
        },
    )
    structure = _model(
        "Structure",
        {
            "label": (label, ...),
            "description": (description, ...),
            "look": (_look(FORM_LOOKS["structure"]), ...),
            "count": (count, ...),
            "width_mm": (span("Width", bound("structure_width_mm")), ...),
            "depth_mm": (span("Depth", bound("structure_depth_mm")), ...),
            "storeys": (span("Storeys", bound("storeys")), ...),
            "storey_height_mm": (_whole(bound("storey_height_mm")), ...),
            "roof_form": (Literal[ROOF_FORMS], ...),
            "roof_look": (_look(("roof",)), ...),
            "wall_look": (_look(("wall",)), ...),
            "door_width_mm": (_whole(bound("door_width_mm")), ...),
            "use_role": (_use_role("structure", catalogs), ...),
            "residents": (_whole((0, bound("residents")[1])), ...),
            "work": (listed(work, 1), ...),
            "visit": (listed(visit, 1), ...),
            "rooms": (listed(room, bound("rooms")[1]), ...),
        },
    )
    area = _model(
        "Area",
        {
            "label": (label, ...),
            "description": (description, ...),
            "look": (_look(FORM_LOOKS["area"]), ...),
            "count": (count, ...),
            "use_role": (_use_role("area", catalogs), ...),
            "roles": (_other_roles("area", catalogs), ...),
            "work": (listed(work, 1), ...),
        },
    )
    zone_fixture = fixture("ZoneFixture", ZONE_FIXTURE_PATTERNS)
    zone = _model(
        "Zone",
        {
            "label": (label, ...),
            "placement": (Literal[PLACEMENTS], ...),
            "share": (_whole((1, 1000)), ...),
            "ground": (_look(("ground",)), ...),
            "access": (Literal[ACCESS], ...),
            "fenced": (bool, ...),
            "structures": (listed(structure, holdings), ...),
            "areas": (listed(area, holdings), ...),
            "fixtures": (listed(zone_fixture, holdings), ...),
        },
    )
    spine = _model(
        "Spine",
        {
            "label": (label, ...),
            "look": (_look(FORM_LOOKS["path"]), ...),
            "width_mm": (_whole(bound("path_width_mm")), ...),
            "road": (bool, ...),
        },
    )
    boundary = _model(
        "Boundary",
        {
            "label": (label, ...),
            "look": (_look(FORM_LOOKS["boundary"]), ...),
            "height_mm": (_whole(bound("boundary_height_mm")), ...),
            "thickness_mm": (_whole(bound("boundary_thickness_mm")), ...),
            "gate_width_mm": (_whole(bound("gate_width_mm")), ...),
        },
    )
    words = _model("PlaceWords", {"here": (label, ...), "around": (label, ...)})
    return _model(
        "WorldKindBrief",
        {
            "kind": (Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")], ...),
            "label": (label, ...),
            "summary": (_text(bound("summary_characters")), ...),
            "enclosure": (Literal[ENCLOSURES], ...),
            "site_width_mm": (_whole(bound("site_width_mm")), ...),
            "site_depth_mm": (_whole(bound("site_depth_mm")), ...),
            "ground": (_look(("ground",)), ...),
            "site_fenced": (bool, ...),
            "employment_permille": (_whole((1, 1000)), ...),
            "offsite_residents": (_whole(bound("offsite_residents")), ...),
            "offsite_home": (label, ...),
            "place_words": (words, ...),
            "spine": (spine, ...),
            "boundary": (boundary, ...),
            "zones": (listed(zone, bound("zones")[1], 1), ...),
        },
    )


# -- the compiler ---------------------------------------------------------------------------------


def _words(text: str) -> str:
    """A label as words a person reads: a model's underscores read as spaces."""
    said = " ".join(text.replace("_", " ").split())
    return said or text


def _slug(label: str, fallback: str) -> str:
    """A key from a label: its words in lowercase ASCII joined by underscores."""
    plain = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii").lower()
    words = re.sub(r"[^a-z0-9]+", "_", plain).strip("_")
    if not words:
        return fallback
    if not words[0].isalpha():
        words = f"{fallback}_{words}"
    return words[:40].rstrip("_")


@dataclass
class _Keys:
    """Keys made from labels, each once among those already taken."""

    taken: set[str] = field(default_factory=set)

    def take(self, label: str, fallback: str) -> str:
        base = _slug(label, fallback)
        key, number = base, 2
        while key in self.taken:
            key, number = f"{base}_{number}", number + 1
        self.taken.add(key)
        return key


def _modules(value: int, module: int) -> int:
    """A length in whole modules, up to the next: a figure a little off the grid means the length
    it nearly states, never a refusal."""
    return -(-value // module) * module


def _span(raw: Mapping[str, int], module: int = 1) -> Any:
    """A figure the seed draws per placed thing: least first, one value where it spans none."""
    low, high = sorted((_modules(raw["from"], module), _modules(raw["to"], module)))
    return low if low == high else {"from": low, "to": high}


@dataclass(frozen=True, slots=True)
class Compiled:
    """A kind document compiled from a brief, with where in the brief each of its parts, use
    classes and zone holdings came from, for telling the model where a check refused it, and what
    sizing changed."""

    document: dict[str, Any]
    #: For each of the document's parts, where it is in the brief (``zones[0].structures[1]``).
    parts: tuple[str, ...]
    #: For each use class, the part in the brief whose use it is.
    uses: tuple[str, ...]
    #: For each zone, for each thing it holds, where it is in the brief.
    holds: tuple[tuple[str, ...], ...]
    #: Each change sizing made, in order.
    sizing: tuple[str, ...] = ()
    #: For each of the document's zones, which of the brief's it is.
    zones: tuple[str, ...] = ()


class _Compiler:
    def __init__(
        self, brief: Mapping[str, Any], catalogs: KindCatalogs, routine: RoutineModel
    ) -> None:
        self.brief = brief
        self.catalogs = catalogs
        self.module = _module(catalogs, str(brief["enclosure"]))
        self.spacing = int(routine.policy["standing_spacing_mm"])
        self.keys = _Keys()
        self.use_keys = _Keys(set(routine.use_classes))
        self.parts: list[dict[str, Any]] = []
        self.origins: list[str] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        self.uses: list[dict[str, Any]] = []
        self.use_origins: list[str] = []
        self.stated_uses: dict[str, str] = {}

    def _use(self, label: str, where: str, content: Mapping[str, Any]) -> str:
        """The key of the use class ``content`` states, made once for the same words."""
        entry = {"label": label, **_USE_NONE, **content}
        said = json.dumps(entry, sort_keys=True)
        found = self.stated_uses.get(said)
        if found is not None:
            return found
        key = self.use_keys.take(label, "use")
        self.uses.append({"key": key, **entry})
        self.use_origins.append(where)
        self.stated_uses[said] = key
        return key

    @staticmethod
    def _work(raw: Mapping[str, Any]) -> dict[str, Any]:
        work = next(iter(raw.get("work") or ()), None) or {}
        opening = int(work.get("opening_minute", 0))
        closing = int(work.get("closing_minute", 1440))
        if opening == closing:
            # Open no minute of the day says nothing; a workplace is open all of it.
            opening, closing = 0, 1440
        role_label = _words(str(work.get("role_label") or "worker"))
        return {
            "kind": "workplace",
            "role_key": _slug(role_label, "worker"),
            "role_label": role_label,
            "staff_per_unit": max(1, int(work.get("staff_per_unit", 1))),
            "opening_minute": opening,
            "closing_minute": closing,
            "shifts": sorted(set(work.get("shifts") or ("day",))),
        }

    @staticmethod
    def _visit(raw: Mapping[str, Any], shop: bool) -> dict[str, Any]:
        visit = next(iter(raw.get("visit") or ()), None)
        if visit is None and not shop:
            return {}
        visit = visit or {}
        return {
            "visitor_capacity": max(1, int(visit.get("visitor_capacity", 4))),
            "visitor_affordances": sorted(set(visit.get("visitor_affordances") or ("shop",))),
        }

    def _part(self, part: dict[str, Any], where: str) -> str:
        self.parts.append(part)
        self.origins.append(where)
        self.by_key[part["key"]] = part
        return str(part["key"])

    def _common(self, raw: Mapping[str, Any], form: str) -> dict[str, Any]:
        label = _words(raw["label"])
        return {
            "key": self.keys.take(label, form),
            "label": label,
            "description": raw.get("description", ""),
            "form": form,
            "look": raw["look"],
        }

    def fixture(self, raw: Mapping[str, Any], where: str) -> str:
        part = self._common(raw, "fixture")
        use_role = raw["use_role"]
        roles = set(raw["roles"])
        if (
            use_role
            and roles & {"seat", "gathering"}
            and not (use_role == "workplace" and raw["work"])
        ):
            # A fixture stated as a seat or a gathering spot stays one when it is drafted as a shop
            # or as a workplace nobody works at: deck chairs and benches are what people rest or
            # meet at, whatever work the brief states for them. A seat someone works at for the
            # people who sit in it (a dentist's chair, a barber's chair) is that workplace.
            use_role = ""
        if use_role:
            roles -= {"seat", "gathering"}
            roles.add(use_role)
        if not roles:
            roles.add("decoration")
        width = int(raw["width_mm"])
        fit = (width + self.spacing) // self.spacing + 1
        seats = stands = 0
        if "seat" in roles:
            seats = min(int(raw["seats"]) or 2, fit)
        if "gathering" in roles:
            stands = min(int(raw["stands"]) or 2, fit)
        elif roles & {"shop", "workplace"}:
            stands = min(int(raw["stands"]), fit)
        use_class = ""
        if use_role:
            use_class = self._use(
                part["label"], where, {**self._work(raw), **self._visit(raw, use_role == "shop")}
            )
        elif "gathering" in roles:
            use_class = self._use(
                part["label"],
                where,
                {
                    "kind": "furniture",
                    "visitor_capacity": stands,
                    "visitor_affordances": ["rest", "visit"] if "seat" in roles else ["visit"],
                },
            )
        part.update(
            roles=sorted(roles),
            use_class=use_class,
            width_mm=width,
            depth_mm=int(raw["depth_mm"]),
            height_mm=int(raw["height_mm"]),
            seats=seats,
            stands=stands,
            sleepers=min(2, max(1, int(raw["sleepers"]))) if "bed" in roles else 0,
            blocks=1 if raw["blocks"] else 0,
        )
        return self._part(part, where)

    def room(self, raw: Mapping[str, Any], where: str, use_role: str) -> str:
        """A room, which is part of its structure's use: it takes the structure's use role."""
        part = self._common(raw, "room")
        holds = [
            {
                "part": self.fixture(held, f"{where}.fixtures[{index}]"),
                "count": _span(held["count"]),
                "pattern": held["pattern"],
            }
            for index, held in enumerate(raw["fixtures"])
        ]
        part.update(
            roles=[use_role] if use_role else [],
            use_class="",
            share=int(raw["share"]),
            holds=holds,
        )
        return self._part(part, where)

    def structure(self, raw: Mapping[str, Any], where: str) -> str:
        part = self._common(raw, "structure")
        rooms = [
            {
                "part": self.room(held, f"{where}.rooms[{index}]", raw["use_role"]),
                "count": _span(held["count"]),
            }
            for index, held in enumerate(raw["rooms"])
        ]
        use_role = raw["use_role"]
        use_class = ""
        if use_role in ("workplace", "shop"):
            use_class = self._use(
                part["label"], where, {**self._work(raw), **self._visit(raw, use_role == "shop")}
            )
        elif use_role == "home" and int(raw["residents"]) > 0:
            beds = any(
                self.by_key[held["part"]]["sleepers"]
                for room in rooms
                for held in self.by_key[room["part"]]["holds"]
            )
            if not beds:
                use_class = self._use(
                    part["label"],
                    where,
                    {
                        "kind": "residential",
                        "role_key": "resident",
                        "role_label": "resident",
                        "resident_capacity": int(raw["residents"]),
                    },
                )
        part.update(
            roles=[use_role] if use_role else [],
            use_class=use_class,
            width_mm=_span(raw["width_mm"], self.module),
            depth_mm=_span(raw["depth_mm"], self.module),
            storeys=_span(raw["storeys"]),
            storey_height_mm=int(raw["storey_height_mm"]),
            roof_form=raw["roof_form"],
            roof_look=raw["roof_look"],
            wall_look=raw["wall_look"],
            door_width_mm=int(raw["door_width_mm"]),
            rooms=rooms,
        )
        return self._part(part, where)

    def area(self, raw: Mapping[str, Any], where: str) -> str:
        part = self._common(raw, "area")
        roles = set(raw["roles"])
        if raw["use_role"]:
            roles.add(raw["use_role"])
        if not roles:
            roles.add("ground")
        use_class = ""
        if raw["use_role"] == "workplace":
            use_class = self._use(part["label"], where, self._work(raw))
        part.update(roles=sorted(roles), use_class=use_class)
        return self._part(part, where)

    @staticmethod
    def _unused(raw: Mapping[str, Any]) -> dict[str, Any]:
        """A fixture or an area held where nobody may go, kept to be seen: its uses dropped, so
        nothing in it waits for a worker, a resident or a visitor who cannot reach it."""
        return {
            **raw,
            "use_role": "",
            "roles": [role for role in raw["roles"] if role not in _USED_ROLES],
            "work": [],
            "visit": [],
        }

    def zone(
        self, raw: Mapping[str, Any], where: str, keys: _Keys, boundary: str
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        holds: list[dict[str, Any]] = []
        origins: list[str] = []
        # A zone the brief states closed stays closed: the words said nobody goes there, so what
        # it holds is kept to be seen and nothing in it is used. A structure is entered by its
        # door, so a zone holding one is opened where anything in it is used.
        closed = raw["access"] == "closed" and not raw["structures"]
        for index, held in enumerate(raw["structures"]):
            at = f"{where}.structures[{index}]"
            holds.append(
                {"part": self.structure(held, at), "count": _span(held["count"]), "pattern": "row"}
            )
            origins.append(at)
        for index, held in enumerate(raw["areas"]):
            at = f"{where}.areas[{index}]"
            area = self._unused(held) if closed else held
            holds.append(
                {"part": self.area(area, at), "count": _span(held["count"]), "pattern": "fill"}
            )
            origins.append(at)
        for index, held in enumerate(raw["fixtures"]):
            at = f"{where}.fixtures[{index}]"
            fixture = self._unused(held) if closed else held
            holds.append(
                {
                    "part": self.fixture(fixture, at),
                    "count": _span(held["count"]),
                    "pattern": held["pattern"],
                }
            )
            origins.append(at)
        used = any(_USED_ROLES & set(self.by_key[held["part"]]["roles"]) for held in holds)
        zone = {
            "key": keys.take(_words(raw["label"]), "zone"),
            "label": _words(raw["label"]),
            "placement": raw["placement"],
            "share": int(raw["share"]),
            "ground": raw["ground"],
            "access": "open" if used else raw["access"],
            "boundary": boundary if raw["fenced"] else "",
            "holds": holds,
        }
        return zone, tuple(origins)

    def compile(self, *, version: int, provenance: Mapping[str, Any], licence: str) -> Compiled:
        brief = self.brief
        spine = brief["spine"]
        width = _modules(int(spine["width_mm"]), self.module)
        spine_key = self._part(
            {
                "key": self.keys.take(_words(spine["label"]), "path"),
                "label": _words(spine["label"]),
                "description": "",
                "form": "path",
                "look": spine["look"],
                "roles": ["path", "road"] if spine["road"] else ["path"],
                "use_class": "",
                "width_mm": width,
            },
            "spine",
        )
        walled = brief["site_fenced"] or brief["enclosure"] == "indoor"
        boundary = ""
        if walled or any(zone["fenced"] for zone in brief["zones"]):
            raw = brief["boundary"]
            boundary = self._part(
                {
                    "key": self.keys.take(_words(raw["label"]), "boundary"),
                    "label": _words(raw["label"]),
                    "description": "",
                    "form": "boundary",
                    "look": raw["look"],
                    "roles": ["boundary"],
                    "use_class": "",
                    "height_mm": int(raw["height_mm"]),
                    "thickness_mm": int(raw["thickness_mm"]),
                    "gate_width_mm": int(raw["gate_width_mm"]),
                },
                "boundary",
            )
        zone_keys = _Keys()
        zones: list[dict[str, Any]] = []
        holds: list[tuple[str, ...]] = []
        stated: list[str] = []
        holding = [
            index
            for index, raw in enumerate(brief["zones"])
            if raw["structures"] or raw["areas"] or raw["fixtures"]
        ]
        for index, raw in enumerate(brief["zones"]):
            if holding and index not in holding:
                continue  # a zone that holds nothing has no lot to lay out
            zone, origins = self.zone(raw, f"zones[{index}]", zone_keys, boundary)
            if zone["placement"] == "edge_back" and any(
                other["placement"] == "edge_back" for other in zones
            ):
                zone["placement"] = "back"  # one zone at most lies across the far edge
            zones.append(zone)
            holds.append(origins)
            stated.append(f"zones[{index}]")
        offsite = int(brief["offsite_residents"])
        homes = any("home" in p["roles"] for p in self.parts if p["form"] == "structure")
        if not homes and offsite == 0:
            # Nobody lives here and the brief says nobody comes in: who works here comes in.
            staff = sum(int(use["staff_per_unit"]) for use in self.uses)
            offsite = min(self.catalogs.bound("offsite_residents")[1], max(4, staff))
        document = {
            "profile": PROFILE,
            "kind": brief["kind"],
            "version": version,
            "label": _words(brief["label"]),
            "summary": brief["summary"],
            "origin": "drafted",
            "provenance": dict(provenance),
            "licence": {"spdx": licence, "verdict": "SHIP"},
            "generator": {"key": GENERATOR_KEY, "version": GENERATOR_VERSION},
            "site": {
                "enclosure": brief["enclosure"],
                "width_mm": _modules(int(brief["site_width_mm"]), self.module),
                "depth_mm": _modules(int(brief["site_depth_mm"]), self.module),
                "ground": brief["ground"],
                "spine": spine_key,
                "boundary": boundary if walled else "",
                "entry_width_mm": width,
            },
            "society": {
                "employment_permille": int(brief["employment_permille"]),
                "offsite_residents": offsite,
                "offsite_home": {
                    "label": _words(brief["offsite_home"]),
                    "use_class": "residential",
                },
                "place_words": {key: _words(said) for key, said in brief["place_words"].items()},
            },
            "parameters": [],
            "presets": [copy.deepcopy(DRAFTED_PRESET)],
            "use_classes": self.uses,
            "parts": self.parts,
            "zones": zones,
        }
        return Compiled(
            document,
            tuple(self.origins),
            tuple(self.use_origins),
            tuple(holds),
            zones=tuple(stated),
        )


def _module(catalogs: KindCatalogs, enclosure: str) -> int:
    return catalogs.bound("module_indoor_mm" if enclosure == "indoor" else "module_open_mm")[0]


# -- sizing ---------------------------------------------------------------------------------------


@dataclass
class _Sizing:
    """The site and its structures as sizing changes them, with the most each dimension was when
    the layout found it too small: the floor a shrink keeps above."""

    document: dict[str, Any]
    catalogs: KindCatalogs
    floor: dict[str, int] = field(default_factory=lambda: {"width_mm": 0, "depth_mm": 0})

    @property
    def site(self) -> dict[str, Any]:
        return self.document["site"]  # type: ignore[no-any-return]

    @property
    def module(self) -> int:
        return _module(self.catalogs, self.site["enclosure"])

    def grow(self, by: Mapping[str, int]) -> str | None:
        """The site grown by ``by`` in each dimension it names, kept within the bounds."""
        grown = []
        for name, more in by.items():
            self.floor[name] = max(self.floor[name], self.site[name])
            high = self.catalogs.bound(f"site_{name}")[1]
            value = min(high, _modules(self.site[name] + max(more, self.module), self.module))
            if value != self.site[name]:
                grown.append(f"site {name} {self.site[name]} to {value}")
                self.site[name] = value
        return "; ".join(grown) or None

    def quarter(self, *names: str) -> str | None:
        return self.grow({name: self.site[name] // 4 for name in names})

    def shrink(self) -> str | None:
        """The site a fifth smaller each way, never to a size the layout found too small."""
        shrunk = []
        for name in ("width_mm", "depth_mm"):
            low = max(self.catalogs.bound(f"site_{name}")[0], self.floor[name] + self.module)
            value = max(low, _modules(self.site[name] * 4 // 5, self.module))
            if value < self.site[name]:
                shrunk.append(f"site {name} {self.site[name]} to {value}")
                self.site[name] = value
        return "; ".join(shrunk) or None

    def structures(self, keys: set[str]) -> str | None:
        """The structures named grown a quarter each way, within the bounds."""
        grown = []
        for part in self.document["parts"]:
            if part["key"] not in keys or part["form"] != "structure":
                continue
            for name in ("width_mm", "depth_mm"):
                high = self.catalogs.bound(f"structure_{name}")[1]
                figure = part[name]
                low, top = (
                    (figure["from"], figure["to"]) if isinstance(figure, dict) else (figure,) * 2
                )
                low, top = (min(high, _modules(v + v // 4, self.module)) for v in (low, top))
                value = low if low == top else {"from": low, "to": top}
                if value != figure:
                    grown.append(f"structure {part['key']} {name} {figure} to {value}")
                    part[name] = value
        return "; ".join(grown) or None

    def people(self, change: int) -> str | None:
        """The people coming in changed by ``change``, within the bounds."""
        society = self.document["society"]
        low, high = self.catalogs.bound("offsite_residents")
        value = min(high, max(low, int(society["offsite_residents"]) + change))
        if value == society["offsite_residents"]:
            return None
        said = f"offsite_residents {society['offsite_residents']} to {value}"
        society["offsite_residents"] = value
        return said

    def answer(self, refusals: Sequence[Mapping[str, Any]]) -> str | None:
        """The change the first refusal sizing can answer asks for, made; None when none can."""
        for refusal in refusals:
            code, said = str(refusal.get("code", "")), str(refusal.get("refusal", ""))
            if code in ("kind_generation_refused", "kind_layout_over_budget"):
                # A structure too small for its rooms, or a room for its fixtures: the site's
                # size does not help, the structure's does.
                tight = _ROOMS_TIGHT.search(said)
                room = _IN_ROOM.search(said)
                keys: set[str] = set()
                if tight is not None:
                    keys = {tight.group(1)}
                elif room is not None:
                    keys = self._holding(room.group(1))
                if tight is not None or room is not None:
                    change = self.structures(keys)
                    if change is not None:
                        return change
                    continue
            change = self._answer(code, said)
            if change is not None:
                return change
        return None

    def inner_walls(self) -> str | None:
        """Indoors, the walls round its zones made an inner wall of their own, half as thick: a
        zone's walks run in the narrow verge inside its walls, which thick walls close."""
        fenced = [zone for zone in self.document["zones"] if zone["boundary"]]
        if self.site["enclosure"] != "indoor" or not fenced:
            return None
        parts = self.document["parts"]
        walls = next(part for part in parts if part["key"] == fenced[0]["boundary"])
        thinner = max(self.catalogs.bound("boundary_thickness_mm")[0], walls["thickness_mm"] // 2)
        if thinner >= walls["thickness_mm"]:
            return None
        if walls["key"] == self.site["boundary"]:
            # The outer walls stay as stated; the zones take an inner wall of their own.
            keys = {part["key"] for part in parts}
            key, number = "inner_wall", 2
            while key in keys:
                key, number = f"inner_wall_{number}", number + 1
            walls = {**copy.deepcopy(walls), "key": key, "label": "inner wall"}
            parts.append(walls)
            for zone in fenced:
                zone["boundary"] = key
        said = f"inner wall {walls['key']} thickness_mm {walls['thickness_mm']} to {thinner}"
        walls["thickness_mm"] = thinner
        return said

    def edge_share(self, key: str) -> str | None:
        """The zone across the far edge given twice its share of the site's depth, at least 100
        and at most 900 per thousand; where it has the most already, the site a quarter deeper. A
        model states shares as small weights, which the far edge reads per thousand."""
        zone = next((zone for zone in self.document["zones"] if zone["key"] == key), None)
        if zone is None:
            return None
        share = int(zone["share"])
        more = min(900, max(2 * share, 100))
        if more <= share:
            return self.quarter("depth_mm")
        zone["share"] = more
        return f"zone {key} share {share} to {more}"

    def _placement(self, key: str) -> str:
        return next(
            (str(zone["placement"]) for zone in self.document["zones"] if zone["key"] == key), ""
        )

    def _holding(self, room: str) -> set[str]:
        return {
            part["key"]
            for part in self.document["parts"]
            if part["form"] == "structure" and any(held["part"] == room for held in part["rooms"])
        }

    def _answer(self, code: str, said: str) -> str | None:
        if code == "kind_generation_refused":
            found = _SIDE_SHORT.search(said)
            if found is not None:
                return self.grow({"depth_mm": int(found[2]) - int(found[1])})
            found = _EDGE_TAKES.search(said)
            if found is not None:
                # The zone across the far edge takes too little of the depth, or leaves the
                # rest too little.
                if int(found[2]) < int(found[3]):
                    return self.edge_share(found[1])
                return self.quarter("depth_mm")
            found = _LOT_SHALLOW.search(said) or _AREAS_SHALLOW.search(said)
            if found is not None:
                if self._placement(found[1]) == "edge_back":
                    # Its lot is as deep as its share of the site's depth, not the width.
                    return self.edge_share(found[1])
                return self.grow({"width_mm": 2 * (int(found[3]) - int(found[2]))})
            if "sides of the spine are too narrow" in said:
                return self.quarter("width_mm")
            if "do not fit" in said:
                return self.quarter("width_mm", "depth_mm")
            return None
        if code == "kind_layout_over_budget":
            return self.quarter("width_mm", "depth_mm")
        if code == "kind_graph_over_budget":
            return self.shrink()
        if code == "kind_population_out_of_bounds":
            found = _HOUSES.search(said)
            if found is not None:
                houses, low, high = int(found[1]), int(found[2]), int(found[3])
                return self.people(high - houses if houses > high else low - houses)
            return None
        if code == "kind_capacity_short":
            found = _NOBODY_WORKS.search(said)
            if found is not None:
                residents, permille = int(found[1]), int(found[2])
                return self.people(-(-1000 // max(1, permille)) - residents)
        if code == "kind_unreachable":
            return self.inner_walls()
        return None


def _deep_enough(document: dict[str, Any], catalogs: KindCatalogs) -> str | None:
    """The site made at least as deep as the layout's need function says its zones need along
    the spine: the largest one zone needs, and half of what they all need, since two sides hold
    them, with a ring of boundary at each end."""
    from exulanica.grammar.grammars.site.layout import _need
    from exulanica.world.kinds.document import read_kind

    try:
        kind = read_kind(document)
        plan = kind.plan(kind.values(DRAFTED_PRESET["key"]))
    except (KindRefused, InvalidParameterError, InvalidRecordError):
        return None  # the checks refuse it by name; nothing sizes what does not read
    needs = [_need(plan, zone) for zone in plan.zones if zone.placement != "edge_back"]
    if not needs:
        return None
    site = document["site"]
    module = plan.module_mm
    ring = 0
    if site["boundary"]:
        walls = next(p for p in document["parts"] if p["key"] == site["boundary"])
        ring = 2 * _modules(int(walls["thickness_mm"]), module)
    least = max(max(needs), -(-sum(needs) // 2)) + ring
    high = catalogs.bound("site_depth_mm")[1]
    deep = min(high, _modules(least, module))
    if deep <= site["depth_mm"]:
        return None
    said = f"site depth_mm {site['depth_mm']} to {deep}"
    site["depth_mm"] = deep
    return said


def _passes(document: dict[str, Any]) -> bool:
    from exulanica.world.kinds.document import read_kind
    from exulanica.world.kinds.samples import check_samples

    try:
        check_samples(read_kind(document))
    except KindRefused:
        return False
    return True


def _trimmed(document: dict[str, Any], catalogs: KindCatalogs) -> list[str]:
    """A site whose samples pass and that holds no area made no larger, each way, than room to
    spare round the smallest that passes (:data:`_ROOM_TO_SPARE`), found by halving; kept as it
    was where that does not pass."""
    if any(part["form"] == "area" for part in document["parts"]):
        return []
    site = document["site"]
    module = _module(catalogs, site["enclosure"])
    more, of = _ROOM_TO_SPARE
    trail = []
    for name in ("depth_mm", "width_mm"):
        stated = site[name]
        low, passing = catalogs.bound(f"site_{name}")[0], stated
        for _ in range(_TRIM_STEPS):
            middle = _modules((low + passing) // 2, module)
            if not low < middle < passing:
                break
            site[name] = middle
            if _passes(document):
                passing = middle
            else:
                low = middle
        site[name] = final = min(stated, _modules(passing * more // of, module))
        if final != stated:
            if _passes(document):
                trail.append(f"site {name} {stated} to {final}")
            else:
                site[name] = stated
    return trail


def _structures_trimmed(
    document: dict[str, Any], stated: Mapping[str, Mapping[str, Any]], catalogs: KindCatalogs
) -> list[str]:
    """Each structure dimension sizing grew made no larger than the smallest that passes between
    what the brief stated and what it grew to, found by halving: growth goes a quarter each way at
    a time, though a room usually lacks room one way only."""
    module = _module(catalogs, document["site"]["enclosure"])
    trail = []
    for part in document["parts"]:
        if part["form"] != "structure" or part["key"] not in stated:
            continue
        for name in ("width_mm", "depth_mm"):
            low, grown = stated[part["key"]][name], part[name]
            if not (isinstance(low, int) and isinstance(grown, int)) or grown <= low:
                continue
            passing = grown
            for _ in range(_TRIM_STEPS):
                middle = _modules((low + passing) // 2, module)
                if not low < middle < passing:
                    break
                part[name] = middle
                if _passes(document):
                    passing = middle
                else:
                    low = middle
            part[name] = passing
            if passing != grown:
                trail.append(f"structure {part['key']} {name} {grown} to {passing}")
    return trail


def _sized(document: dict[str, Any], catalogs: KindCatalogs) -> tuple[str, ...]:
    """Sizing: the site deep enough for its zones' needs, then the samples built as the checks
    build them and answered while they refuse something sizing can answer, then, once they
    pass, each structure sizing grew trimmed to the smallest that passes and the site trimmed to
    room to spare round the smallest that passes."""
    from exulanica.world.kinds.document import read_kind
    from exulanica.world.kinds.samples import check_samples

    stated = {
        part["key"]: {name: part[name] for name in ("width_mm", "depth_mm")}
        for part in document["parts"]
        if part["form"] == "structure"
    }
    sizing = _Sizing(document, catalogs)
    first = _deep_enough(document, catalogs)
    trail = [first] if first else []
    sizing.floor["depth_mm"] = document["site"]["depth_mm"] - sizing.module if first else 0
    seen: set[str] = set()
    for _ in range(_SIZING_STEPS):
        try:
            kind = read_kind(document)
        except KindRefused as refused:
            # Stage A refuses by name; only a site laid on more grid points than the bounds allow
            # is sizing's to answer.
            grid = (refused.code, refused.where) == ("kind_out_of_bounds", "site")
            change = sizing.shrink() if grid else None
        else:
            try:
                check_samples(kind)
            except KindRefused as refused:
                report = getattr(refused, "report", None) or {}
                change = sizing.answer((report.get("failed") or {}).get("refusals") or ())
            else:
                return (
                    *trail,
                    *_structures_trimmed(document, stated, catalogs),
                    *_trimmed(document, catalogs),
                )
        state = json.dumps(
            [document["site"], document["society"], document["parts"], document["zones"]]
        )
        if change is None or state in seen:
            break
        seen.add(state)
        trail.append(change)
    return tuple(trail)


def compile_brief(
    brief: Mapping[str, Any],
    *,
    provenance: Mapping[str, Any],
    version: int = 1,
    licence: str = "CC0-1.0",
    catalogs: KindCatalogs | None = None,
    routine: RoutineModel | None = None,
    size: bool = True,
) -> Compiled:
    """The kind document a brief states, at ``version`` with ``provenance`` and ``licence``: its
    keys, references, use classes and figures made here and, with ``size``, its site sized by its
    sample worlds. Nothing here decides whether the kind is kept."""
    catalogs = load_kind_catalogs() if catalogs is None else catalogs
    if routine is None:
        from exulanica.world.society_living import town_routine

        routine = town_routine()
    compiled = _Compiler(brief, catalogs, routine).compile(
        version=version, provenance=provenance, licence=licence
    )
    if not size:
        return compiled
    return dataclasses.replace(compiled, sizing=_sized(compiled.document, catalogs))


# -- where a check refused it, in the brief -------------------------------------------------------

#: How a refusal's place outside the parts, the uses and the zones' holdings reads in the brief.
_DOCUMENT_WHERE: Final = {
    "site.enclosure": "enclosure",
    "site.width_mm": "site_width_mm",
    "site.depth_mm": "site_depth_mm",
    "site.entry_width_mm": "spine.width_mm",
    "site.ground": "ground",
    "site.spine": "spine",
    "site.boundary": "boundary",
    "site": "site_width_mm and site_depth_mm",
    "society.employment_permille": "employment_permille",
    "society.offsite_residents": "offsite_residents",
    "society.offsite_home": "offsite_home",
    "society.place_words": "place_words",
    "use_classes": "the parts used as a workplace, a shop, a home or a gathering spot",
    "parts": "every spine, boundary, structure, room, area and fixture",
    "zones": "zones",
}
#: Where a use class's fields come from in the part whose use it is.
_USE_FIELDS: Final = {
    "role_key": "work[0].role_label",
    "role_label": "work[0].role_label",
    "staff_per_unit": "work[0].staff_per_unit",
    "opening_minute": "work[0].opening_minute",
    "closing_minute": "work[0].closing_minute",
    "shifts": "work[0].shifts",
    "visitor_capacity": "visit[0].visitor_capacity",
    "visitor_affordances": "visit[0].visitor_affordances",
    "resident_capacity": "residents",
}
_PARTS_AT: Final = re.compile(r"^parts\[(\d+)\]")
_USES_AT: Final = re.compile(r"^use_classes\[(\d+)\]\.?([a-z_]*)")
_HOLDS_AT: Final = re.compile(r"^zones\[(\d+)\]\.holds\[(\d+)\]")
_ZONE_AT: Final = re.compile(r"^zones\[(\d+)\]")
_PART_NAMED: Final = re.compile(r"^part ([a-z][a-z0-9_]*)")


def brief_where(where: str, compiled: Compiled) -> str:
    """Where a check refused a compiled kind, as the place in the brief the model filled."""
    found = _PARTS_AT.match(where)
    if found is not None and int(found.group(1)) < len(compiled.parts):
        at = compiled.parts[int(found.group(1))]
        rest = where[found.end() :]
        if at.rsplit(".", 1)[-1].startswith("rooms["):
            # A room's holdings are its fixtures in the brief.
            rest = rest.replace(".holds[", ".fixtures[", 1)
        return f"{at}{rest}"
    found = _USES_AT.match(where)
    if found is not None and int(found.group(1)) < len(compiled.uses):
        at = compiled.uses[int(found.group(1))]
        name = found.group(2)
        return f"{at}.{_USE_FIELDS[name]}" if name in _USE_FIELDS else at
    found = _HOLDS_AT.match(where)
    if found is not None:
        zone, held = int(found.group(1)), int(found.group(2))
        if zone < len(compiled.holds) and held < len(compiled.holds[zone]):
            return f"{compiled.holds[zone][held]}{where[found.end() :]}"
        if zone < len(compiled.zones):
            return f"{compiled.zones[zone]}"
    found = _ZONE_AT.match(where)
    if found is not None and int(found.group(1)) < len(compiled.zones):
        rest = where[found.end() :]
        if rest == ".holds":
            rest = " (its structures, areas and fixtures together)"
        return f"{compiled.zones[int(found.group(1))]}{rest}"
    found = _PART_NAMED.match(where)
    if found is not None:
        keys = [part["key"] for part in compiled.document["parts"]]
        if found.group(1) in keys and len(compiled.parts) == len(keys):
            return f"{compiled.parts[keys.index(found.group(1))]}{where[found.end() :]}"
    if where.startswith("sample "):
        return "a sample world of the kind"
    for stated, said in sorted(_DOCUMENT_WHERE.items(), key=lambda pair: -len(pair[0])):
        if where == stated or where.startswith(f"{stated}."):
            return said + where[len(stated) :]
    return where
