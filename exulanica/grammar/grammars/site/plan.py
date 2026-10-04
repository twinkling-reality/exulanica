"""What the site grammar generates from: a world kind with a person's values in place.

A world kind (``exulanica.world-kind/v1``) is read, held to its checks and resolved in the world
layer (:mod:`exulanica.world.kinds`). What reaches this grammar is a :class:`SitePlan`: every part
and zone the kind states, each figure either a whole number or a :class:`Span` the seed draws from
on a stated step, and nothing a person still has to choose. The grammar refuses a plan that is
malformed by name (:class:`~exulanica.grammar.errors.InvalidParameterError`) rather than reading
around it, so a plan built by hand in a test is held to the same rules as one resolved from a kind.

Words are closed and append-only: the forms a part takes, where a zone is placed, how a holding is
laid out, the engine roles and the look families. The look families are the ones the world kinds'
look-family catalog states (``assets/catalogs/world-kinds/look-families.v1.json``); a test holds
them equal. A part's own key and a look role's leaf are open: a kind may name a part
``milking_parlour`` and dress it as ``structure.milking_parlour``.

Pure: no catalog file, no clock and no float. A plan is its own canonical document
(:func:`plan_payload`), whose digest a world's receipt records.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.errors import InvalidParameterError
from exulanica.grammar.records import KEY_PATTERN, record_payload

__all__ = [
    "ACCESS",
    "ENCLOSURES",
    "FORMS",
    "LOOK_FAMILIES",
    "PATTERNS",
    "PLACEMENTS",
    "ROLES",
    "ROOF_FORMS",
    "AreaPart",
    "BoundaryPart",
    "FixturePart",
    "Holding",
    "Look",
    "PathPart",
    "RoomPart",
    "SitePlan",
    "Span",
    "StructurePart",
    "ZonePlan",
    "plan_payload",
    "plan_sha256",
]

#: A site is open ground (a farm, a building site, a harbour) or one building's inside (a cafe, a
#: flat): an indoor site's edge is its outer walls and its zones are rooms behind inner walls.
ENCLOSURES: Final = ("open", "indoor")
#: What a part is to the generator: how it is laid out and drawn.
FORMS: Final = ("path", "area", "structure", "room", "fixture", "boundary")
#: Where a zone lies: beside the spine near the entry (``front``), further in (``middle``,
#: ``back``), on one side of it (``left``, ``right``), or across the far edge of the site
#: (``edge_back``), which fronts a cross path.
PLACEMENTS: Final = ("front", "middle", "back", "left", "right", "edge_back")
#: How a zone or a room lays out what it holds.
PATTERNS: Final = (
    "fill",
    "row",
    "grid",
    "scatter",
    "perimeter",
    "cluster",
    "centre",
    "back_wall",
)
#: A zone people may walk into, or one they never enter (a crane's reach, a private yard).
ACCESS: Final = ("open", "closed")
ROOF_FORMS: Final = ("flat", "gable")
#: The engine roles a part may take: what the engine does with it. The kind-role catalog
#: (``assets/catalogs/world-kinds/kind-role.v1.json``) states each with the forms that may take it
#: and why; a test holds the two equal.
ROLES: Final = (
    "bed",
    "boundary",
    "decoration",
    "field",
    "gathering",
    "ground",
    "home",
    "no_go",
    "obstruction",
    "parking",
    "path",
    "road",
    "seat",
    "shop",
    "water",
    "workplace",
)
#: The look families a part's look role may name, closed and append-only.
LOOK_FAMILIES: Final = (
    "animal",
    "boundary",
    "character",
    "door",
    "fixture",
    "ground",
    "path",
    "plant",
    "prop",
    "road",
    "roof",
    "structure",
    "vehicle",
    "wall",
    "water",
    "window",
)
#: The most a single span, count or length may state: a 32-bit integer, far past any site.
_FIGURE_MAXIMUM: Final = 2_147_483_647


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidParameterError(message)


def _key(where: str, value: object) -> str:
    _require(type(value) is str and KEY_PATTERN.fullmatch(value) is not None, f"{where} is a key")
    return value  # type: ignore[return-value]


def _figure(where: str, value: object, minimum: int = 0) -> int:
    _require(
        type(value) is int and minimum <= value <= _FIGURE_MAXIMUM,  # type: ignore[operator]
        f"{where} is a whole number of at least {minimum}",
    )
    return value  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class Span:
    """A figure the seed draws: from ``minimum`` to ``maximum`` in whole steps of ``step``; a span
    whose ends meet is a fixed figure."""

    minimum: int
    maximum: int
    step: int

    def __post_init__(self) -> None:
        _figure("a span's minimum", self.minimum)
        _figure("a span's maximum", self.maximum)
        _figure("a span's step", self.step, 1)
        _require(
            self.minimum <= self.maximum and (self.maximum - self.minimum) % self.step == 0,
            f"a span runs from its minimum to its maximum in whole steps, not {self}",
        )

    @classmethod
    def fixed(cls, value: int) -> Span:
        return cls(value, value, 1)


@dataclass(frozen=True, slots=True)
class Look:
    """A look role, ``family.leaf``: what a style pack dresses, never what the engine does."""

    family: str
    leaf: str

    def __post_init__(self) -> None:
        _require(self.family in LOOK_FAMILIES, f"no look family {self.family!r}")
        _key("a look role's leaf", self.leaf)
        _require(len(self.leaf) <= 48, "a look role's leaf is at most 48 characters")

    @property
    def role(self) -> str:
        return f"{self.family}.{self.leaf}"


@dataclass(frozen=True, slots=True)
class Holding:
    """Some of one part, held by a zone, a room or a structure, laid out by ``pattern``."""

    part: str
    count: Span
    pattern: str

    def __post_init__(self) -> None:
        _key("a holding's part", self.part)
        _require(self.pattern in PATTERNS, f"no pattern {self.pattern!r}")
        _require(self.count.maximum >= 1, "a holding holds at least one, at most")


@dataclass(frozen=True, slots=True)
class PathPart:
    """A walking way (and with the road role, a driving way) of a stated width."""

    key: str
    roles: tuple[str, ...]
    look: Look
    width_mm: int

    FORM: ClassVar[str] = "path"

    @property
    def form(self) -> str:
        return self.FORM


@dataclass(frozen=True, slots=True)
class AreaPart:
    """Ground a zone is given over to: a field, a pond, a laydown yard, a car park."""

    key: str
    roles: tuple[str, ...]
    look: Look

    FORM: ClassVar[str] = "area"

    @property
    def form(self) -> str:
        return self.FORM


@dataclass(frozen=True, slots=True)
class StructurePart:
    """A building: a shell of walls under a roof, with a door when anything is done inside it and
    rooms when it holds any; a structure with no rooms and no role is solid."""

    key: str
    roles: tuple[str, ...]
    look: Look
    width_mm: Span
    depth_mm: Span
    storeys: Span
    storey_height_mm: int
    roof_form: str
    roof_look: Look
    wall_look: Look
    door_width_mm: int
    rooms: tuple[Holding, ...]

    FORM: ClassVar[str] = "structure"

    @property
    def form(self) -> str:
        return self.FORM


@dataclass(frozen=True, slots=True)
class RoomPart:
    """A room of a structure: its share of the inside, its floor and what it holds."""

    key: str
    roles: tuple[str, ...]
    look: Look
    share: int
    holds: tuple[Holding, ...]

    FORM: ClassVar[str] = "room"

    @property
    def form(self) -> str:
        return self.FORM


@dataclass(frozen=True, slots=True)
class FixturePart:
    """A thing placed on the ground or a floor: a bed, a bench, a workbench, a hay bale.

    ``seats`` people rest at it along its front, ``stands`` stand at its front, ``sleepers``
    sleep in it (a bed), and ``blocks`` is 1 when nobody walks through it.
    """

    key: str
    roles: tuple[str, ...]
    look: Look
    width_mm: int
    depth_mm: int
    height_mm: int
    seats: int
    stands: int
    sleepers: int
    blocks: int

    FORM: ClassVar[str] = "fixture"

    @property
    def form(self) -> str:
        return self.FORM


@dataclass(frozen=True, slots=True)
class BoundaryPart:
    """A fence or a wall round a zone or the site, with a gate where it meets a path."""

    key: str
    look: Look
    height_mm: int
    thickness_mm: int
    gate_width_mm: int

    FORM: ClassVar[str] = "boundary"

    @property
    def form(self) -> str:
        return self.FORM

    @property
    def roles(self) -> tuple[str, ...]:
        return ("boundary",)


Part = PathPart | AreaPart | StructurePart | RoomPart | FixturePart | BoundaryPart


@dataclass(frozen=True, slots=True)
class ZonePlan:
    """One zone: where it lies, its share of its side of the site, its ground, whether people may
    walk into it, the boundary round it ("" for none) and what it holds."""

    key: str
    placement: str
    share: int
    ground: Look
    access: str
    boundary: str
    holds: tuple[Holding, ...]


@dataclass(frozen=True, slots=True)
class SitePlan:
    """A whole site: its extent, its grid step, its ground, the path from its entry (the spine),
    the boundary round it ("" for none), its parts by key and its zones in the kind's order."""

    kind: str
    enclosure: str
    width_mm: int
    depth_mm: int
    module_mm: int
    ground: Look
    spine: str
    boundary: str
    entry_width_mm: int
    parts: tuple[Part, ...]
    zones: tuple[ZonePlan, ...]

    def __post_init__(self) -> None:
        _key("a site's kind", self.kind)
        _require(self.enclosure in ENCLOSURES, f"no enclosure {self.enclosure!r}")
        for name in ("width_mm", "depth_mm", "module_mm", "entry_width_mm"):
            _figure(f"a site's {name}", getattr(self, name), 1)
        _require(
            self.enclosure == "open" or bool(self.boundary),
            "an indoor site's outer walls are its boundary part, so it names one",
        )
        for name in ("width_mm", "depth_mm", "entry_width_mm"):
            _require(
                getattr(self, name) % self.module_mm == 0,
                f"a site's {name} is a whole number of its {self.module_mm} mm module",
            )
        keys = [part.key for part in self.parts]
        _require(len(set(keys)) == len(keys), "a site's parts have distinct keys")
        zones = [zone.key for zone in self.zones]
        _require(len(set(zones)) == len(zones), "a site's zones have distinct keys")
        by_key = self.by_key()
        spine = by_key.get(self.spine)
        _require(isinstance(spine, PathPart), f"the spine {self.spine!r} is a path part")
        _require(
            not self.boundary or isinstance(by_key.get(self.boundary), BoundaryPart),
            f"the site's boundary {self.boundary!r} is a boundary part",
        )
        _require(
            sum(1 for zone in self.zones if zone.placement == "edge_back") <= 1,
            "a site has at most one zone across its far edge",
        )
        for zone in self.zones:
            _require(zone.placement in PLACEMENTS, f"zone {zone.key}: no placement")
            _require(zone.access in ACCESS, f"zone {zone.key}: no access {zone.access!r}")
            _require(1 <= zone.share <= 1000, f"zone {zone.key}: a share is 1 to 1000")
            _require(
                not zone.boundary or isinstance(by_key.get(zone.boundary), BoundaryPart),
                f"zone {zone.key}: its boundary is a boundary part",
            )
            for holding in zone.holds:
                held = by_key.get(holding.part)
                _require(
                    isinstance(held, AreaPart | StructurePart | FixturePart),
                    f"zone {zone.key} holds {holding.part!r}, which is no area, structure or "
                    "fixture",
                )
                _require(
                    (holding.pattern == "fill") == isinstance(held, AreaPart),
                    f"zone {zone.key}: exactly an area fills, and {holding.part} is laid out by "
                    f"{holding.pattern}",
                )
                _require(
                    not isinstance(held, StructurePart) or holding.pattern == "row",
                    f"zone {zone.key}: structures stand in a row along its front",
                )
                _require(holding.pattern != "back_wall", "a zone has no back wall; a room has")
        for part in self.parts:
            if isinstance(part, StructurePart):
                for room in part.rooms:
                    _require(
                        isinstance(by_key.get(room.part), RoomPart),
                        f"structure {part.key} holds {room.part!r}, which is no room",
                    )
            if isinstance(part, RoomPart):
                for holding in part.holds:
                    _require(
                        isinstance(by_key.get(holding.part), FixturePart),
                        f"room {part.key} holds {holding.part!r}, which is no fixture",
                    )
                    _require(
                        holding.pattern not in ("fill",),
                        f"room {part.key}: a fixture is not laid out by fill",
                    )

    def by_key(self) -> Mapping[str, Part]:
        return {part.key: part for part in self.parts}


def plan_payload(plan: SitePlan) -> dict[str, object]:
    """The plan as canonical data: every field of every part and zone, with each part's form."""
    return {
        "site": record_payload(
            _SiteFields(
                plan.kind,
                plan.enclosure,
                plan.width_mm,
                plan.depth_mm,
                plan.module_mm,
                plan.ground,
                plan.spine,
                plan.boundary,
                plan.entry_width_mm,
            )
        ),
        "parts": [
            {"form": part.form, "fields": record_payload(part)}
            for part in sorted(plan.parts, key=lambda part: part.key)
        ],
        "zones": [record_payload(zone) for zone in plan.zones],
    }


@dataclass(frozen=True, slots=True)
class _SiteFields:
    kind: str
    enclosure: str
    width_mm: int
    depth_mm: int
    module_mm: int
    ground: Look
    spine: str
    boundary: str
    entry_width_mm: int


def plan_sha256(plan: SitePlan) -> str:
    """The SHA-256 of the plan's canonical JSON, the digest a world's receipt records."""
    return sha256_of_canonical(plan_payload(plan)).hex()
