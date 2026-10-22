"""Where a thing may stand when it is moved or placed, by the world's own reading of its ground.

A move or a placing used to be held only to its record: a well could be put into a pond, inside a
barn's walls, past the edge of the world or a metre into the air, and the edit was stored. This is
the rule that refuses those, read from the same figures the world's society reads, so where a thing
may be put and what the world's people can reach never disagree:

* **The world's edge**: the society's walkable area (:class:`WalkableArea`), when the world's own
  ground states it. An endless ground, or an area the society only declared, has no edge here. A
  site on a volume's top is walked past its area, over the open top out to the rim
  (:mod:`~exulanica.world.site_top_ground`): there a thing stands on the top's land, and is told
  it is in the water where the top's own water stands.
* **Resting on the ground**: the society's own rule for how high a thing stands above the surface
  under it (``height_above``: the ground plane's, or the walking surfaces' nearest line,
  :func:`exulanica.world.society_walking_surfaces.surface_height_above`). One it would read as
  off the ground is refused.
* **What blocks**: the parts of the world people cannot walk through, named so a person can be told
  which (a site's structures, water and other areas, walls, blocking fixtures and closed zones; a
  town's buildings, street furniture and trees; the version's other placed objects that block
  walking). A thing's footprint, its kind's box turned with it, may touch a part's face but not
  overlap it. A being has no box here: its centre is held to the same parts.

Each refusal is a :class:`~exulanica.world.errors.ThingLandingRefused` with one code per kind of
refusal, what refused it (``where``) and a sentence a person reads, its words read as data
(:func:`landing_words`: ``assets/catalogs/landing-words``). Nothing here reads the database:
:mod:`exulanica.world.thing_landing_source` prepares a world's :class:`LandingGround` before a
write's transaction, as support placement prepares its source.

Pure and exact: footprints are integer millimetres, a turned town part is held in fractions, and
overlap is a positive area of the two shapes' common part, so touching a face never refuses.
"""

from __future__ import annotations

import functools
import string
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from exulanica.grammar.catalogs import CatalogSchema, FieldValue, load_catalog, text_field
from exulanica.grammar.errors import CatalogError
from exulanica.world.errors import InvalidThingPlacement, ThingLandingRefused
from exulanica.world.placed_things import PlacedThing, ThingKindReference, shipped_kind
from exulanica.world.society_composition import footprint_ring

if TYPE_CHECKING:
    from exulanica.world.society_authored_ground import WalkableArea

__all__ = [
    "LANDING_CODES",
    "LANDING_WORDS_DIRECTORY",
    "PART_KINDS",
    "SENTENCE_SLOTS",
    "BlockedPart",
    "LandingGround",
    "LandingWords",
    "blocking_things",
    "footprint_half_extents",
    "footprint_points",
    "landing_refusal",
    "landing_words",
    "plane_height",
    "resting_height",
    "rests_on_footprint",
    "rests_on_plane",
    "step_words",
]

Number = int | Fraction
Point = tuple[Number, Number]

#: What a blocked part is, in the order a refusal names the first one a thing meets.
PART_KINDS: Final = (
    "water",
    "structure",
    "building",
    "wall",
    "closed",
    "fixture",
    "furniture",
    "tree",
    "area",
    "thing",
    "blocked",
)
PartKind = Literal[
    "water",
    "structure",
    "building",
    "wall",
    "closed",
    "fixture",
    "furniture",
    "tree",
    "area",
    "thing",
    "blocked",
]

OUTSIDE_WORLD: Final = "thing_landing_outside"
OFF_GROUND: Final = "thing_landing_off_ground"
BLOCKED: Final = "thing_landing_blocked"
#: Every code a landing refusal answers with. Stable: codes are added, never renamed.
LANDING_CODES: Final = frozenset({OUTSIDE_WORLD, OFF_GROUND, BLOCKED})

_PRECEDENCE: Final = {kind: index for index, kind in enumerate(PART_KINDS)}


@dataclass(frozen=True, slots=True)
class BlockedPart:
    """One part of a world nothing may be moved onto, as a ring in the region's frame (east and
    south, millimetres), with what it is and the words that name it ("" where it has none)."""

    kind: PartKind
    label: str
    ring: tuple[Point, ...]


#: The water standing on the open ground past a world's area (:attr:`LandingGround.beyond`): it is
#: no part of the world's records, so it has no ring and no words of its own.
_OPEN_WATER: Final = BlockedPart("water", "", ())


@dataclass(frozen=True, slots=True)
class LandingGround:
    """A world's ground as a move reads it: its edge (None where it has none), how high a thing
    stands above the surface under it (None where it rests on it), and what blocks; and, where the
    ground states it, the height a thing rests at, at a point of the region (east and south,
    millimetres), which a placing's preview answers so the page stands it there."""

    region_id: str
    area: WalkableArea | None
    height_above: Callable[[PlacedThing], int | None]
    parts: tuple[BlockedPart, ...]
    rest_height: Callable[[tuple[int, int]], int] | None = None
    #: Where a thing rests on the highest of ``rest_height`` under its footprint (a town's surface,
    #: whose kerbs are steps), not at its centre alone.
    rests_on_footprint: bool = False
    #: Where the ground runs on past ``area`` (a site on a volume's top: the open top round it out
    #: to the rim), what a point of the region past it is: ``"land"``, ``"water"``, or None past
    #: the ground's edge.
    beyond: Callable[[tuple[int, int]], Literal["land", "water"] | None] | None = None

    def resting_y(self, thing: PlacedThing) -> int | None:
        """The height ``thing`` rests at where it is posed, where the ground states one: under its
        footprint (:func:`resting_height`) where the ground rests things so, else at its centre."""
        if self.rest_height is None:
            return None
        if self.rests_on_footprint:
            return resting_height(self.rest_height, thing)
        return self.rest_height((thing.transform.x_mm, thing.transform.z_mm))


def rests_on_plane(elevation_mm: int) -> Callable[[PlacedThing], int | None]:
    """The plane rule a society of things reads a lattice ground by
    (``society_authored_ground._height_above_plane``): a thing rests on the plane exactly at its
    elevation, and stands its difference above it otherwise. ``tests/test_thing_landing.py`` holds
    the two to the same answers."""

    def height(thing: PlacedThing) -> int | None:
        above = thing.transform.y_mm - elevation_mm
        return None if above == 0 else above

    return height


def plane_height(elevation_mm: int) -> Callable[[tuple[int, int]], int]:
    """The height a thing rests at on a plane ground: its elevation, wherever it stands
    (``rests_on_plane``'s rule)."""
    return lambda _point: elevation_mm


def landing_refusal(
    ground: LandingGround,
    thing: PlacedThing,
    half_extents_mm: tuple[int, int] | None,
    others: Sequence[BlockedPart] = (),
) -> ThingLandingRefused | None:
    """Why ``thing`` may not stand where it is posed, or None where it may.

    ``half_extents_mm`` is its kind's box, half its width and depth, turned by its yaw; None for a
    being, which is held by its centre. ``others`` are the version's other blocking things. The
    edge is asked first, then the ground, then what blocks, so a thing past the edge and in the air
    is told about the edge.
    """
    centre = (thing.transform.x_mm, thing.transform.z_mm)
    shape: tuple[Point, ...] = (
        (centre,)
        if half_extents_mm is None
        else tuple(footprint_ring(centre, half_extents_mm, thing.transform.yaw_microradians)[:-1])
    )
    past = (
        []
        if ground.area is None
        else [
            None if ground.beyond is None else ground.beyond(point)
            for point in shape
            if not _within(point, ground.area)
        ]
    )
    if None in past:
        return ThingLandingRefused(OUTSIDE_WORLD, {"part": None}, _said("outside"))
    above = ground.height_above(thing)
    if above is not None:
        # Said as the ground's step, not as the thing buried or floating: what to do is plain.
        side = _said("side_lower" if above > 0 else "side_higher")
        return ThingLandingRefused(
            OFF_GROUND,
            {"height_above_mm": above},
            _said("off_ground", step=step_words(abs(above)), side=side),
        )
    met = [
        part
        for part in (*ground.parts, *others)
        if (_inside(centre, part.ring) if len(shape) == 1 else _overlaps(shape, part.ring))
    ]
    if "water" in past:
        met.append(_OPEN_WATER)
    if not met:
        return None
    first = min(met, key=lambda part: (_PRECEDENCE[part.kind], part.label))
    return ThingLandingRefused(
        BLOCKED, {"part": first.kind, "label": first.label}, _blocked_words(first)
    )


#: Where a landing refusal's words are read from: ``landing-sentence.v1.json``, its sentences by
#: key, and ``landing-part.v1.json``, each part kind's own name and the sentence it is said with.
LANDING_WORDS_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2] / "assets" / "catalogs" / "landing-words"
)
#: The slots the rule fills in each sentence: one the catalog states with any other is refused.
SENTENCE_SLOTS: Final[Mapping[str, frozenset[str]]] = {
    "outside": frozenset(),
    "off_ground": frozenset({"step", "side"}),
    "side_lower": frozenset(),
    "side_higher": frozenset(),
    "step_centimetres": frozenset({"centimetres"}),
    "step_metres": frozenset({"metres", "tenths"}),
    "in_part": frozenset({"name"}),
    "inside_part": frozenset({"name"}),
    "on_part": frozenset({"name"}),
    "unnamed_part": frozenset(),
}
#: The sentences a part kind may be said with.
PART_SENTENCES: Final = ("in_part", "inside_part", "on_part", "unnamed_part")


def _sentence_words(where: str, value: object) -> FieldValue:
    return text_field(where, value)


def _part_name(where: str, value: object) -> FieldValue:
    """A part kind's own name, or "" for a kind with no words of its own."""
    return value if value == "" else text_field(where, value)


def _part_sentence(where: str, value: object) -> FieldValue:
    if value not in PART_SENTENCES:
        raise CatalogError(f"{where} is one of {list(PART_SENTENCES)}, got {value!r}")
    return str(value)


_SENTENCE: Final = CatalogSchema(
    "landing-sentence", 1, (("words", _sentence_words), ("reason", text_field))
)
_PART: Final = CatalogSchema(
    "landing-part",
    1,
    (("name", _part_name), ("sentence", _part_sentence), ("reason", text_field)),
)


@dataclass(frozen=True, slots=True)
class LandingWords:
    """What a landing refusal says: its sentences by key, and each part kind's own name and the
    sentence it is said with."""

    sentences: Mapping[str, str]
    parts: Mapping[str, tuple[str, str]]


@functools.cache
def landing_words(directory: Path = LANDING_WORDS_DIRECTORY) -> LandingWords:
    """The landing refusals' words, read from the two catalogs in ``directory``: refused by name
    where a sentence the rule says is missing or fills other slots than :data:`SENTENCE_SLOTS`,
    where a part kind of :data:`PART_KINDS` is not named exactly once, or where a kind said by its
    name has none (only an unnamed kind has no name)."""
    sentences = {
        entry.key: str(dict(entry.values)["words"])
        for entry in load_catalog(directory / "landing-sentence.v1.json", _SENTENCE).entries
    }
    if set(sentences) != set(SENTENCE_SLOTS):
        raise CatalogError(
            f"landing-sentence states {sorted(sentences)}, the rule says {sorted(SENTENCE_SLOTS)}"
        )
    for key, words in sentences.items():
        slots = {field for _text, field, _spec, _conversion in string.Formatter().parse(words)}
        slots.discard(None)
        if slots != SENTENCE_SLOTS[key]:
            raise CatalogError(
                f"landing-sentence {key} fills {sorted(slots)}, "
                f"the rule fills {sorted(SENTENCE_SLOTS[key])}"
            )
    parts = {
        entry.key: (str(dict(entry.values)["name"]), str(dict(entry.values)["sentence"]))
        for entry in load_catalog(directory / "landing-part.v1.json", _PART).entries
    }
    if set(parts) != set(PART_KINDS):
        raise CatalogError(f"landing-part names {sorted(parts)}, a part is one of {PART_KINDS}")
    for kind, (name, sentence) in parts.items():
        if (name == "") != (sentence == "unnamed_part"):
            raise CatalogError(
                f"landing-part {kind}: a part said by its name has one, "
                "and only an unnamed one has none"
            )
    return LandingWords(sentences, parts)


def _said(key: str, **slots: object) -> str:
    return landing_words().sentences[key].format(**slots)


def step_words(step_mm: int) -> str:
    """A refusing step's height in words: under a metre in whole centimetres, from a metre in
    metres to one place, each rounded up, so a refused step never reads as one a thing would rest
    across ("25 cm", "1.3 m")."""
    centimetres = -(-step_mm // 10)
    if centimetres < 100:
        return _said("step_centimetres", centimetres=centimetres)
    metres, tenths = divmod(-(-step_mm // 100), 10)
    return _said("step_metres", metres=metres, tenths=tenths)


def _blocked_words(part: BlockedPart) -> str:
    """What a part says it refuses with: its own words or its kind's name, in its kind's sentence;
    a kind with no name is somewhere people cannot walk through, whatever its words."""
    kind_name, sentence = landing_words().parts[part.kind]
    return _said(sentence, name=part.label or kind_name)


def _within(point: Point, area: WalkableArea) -> bool:
    return (
        abs(point[0] - area.centre_x_mm) <= area.half_width_mm
        and abs(point[1] - area.centre_z_mm) <= area.half_depth_mm
    )


def _cross(o: Point, a: Point, b: Point) -> Number:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _twice_area(ring: Sequence[Point]) -> Number:
    count = len(ring)
    return sum(
        ring[i][0] * ring[(i + 1) % count][1] - ring[(i + 1) % count][0] * ring[i][1]
        for i in range(count)
    )


def _inside(point: Point, ring: Sequence[Point]) -> bool:
    """Whether ``point`` lies strictly inside ``ring``: on an edge is not inside."""
    count = len(ring)
    for i in range(count):
        a, b = ring[i], ring[(i + 1) % count]
        if (
            _cross(a, b, point) == 0
            and min(a[0], b[0]) <= point[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= point[1] <= max(a[1], b[1])
        ):
            return False
    inside = False
    for i in range(count):
        (ax, ay), (bx, by) = ring[i], ring[(i + 1) % count]
        if (ay > point[1]) != (by > point[1]):
            x = ax + (point[1] - ay) * Fraction(bx - ax) / (by - ay)
            if point[0] < x:
                inside = not inside
    return inside


def _overlaps(convex: Sequence[Point], ring: Sequence[Point]) -> bool:
    """Whether a convex shape and any simple ring share a part of positive area.

    The ring is clipped by each edge of the convex shape in turn (Sutherland and Hodgman, exact in
    fractions); what is left is their common part, and a common part of no area (a shared face or
    corner) is no overlap.
    """
    orientation = 1 if _twice_area(convex) > 0 else -1
    kept: list[Point] = list(ring)
    count = len(convex)
    for i in range(count):
        a, b = convex[i], convex[(i + 1) % count]
        if not kept:
            return False
        source, kept = kept, []
        for j, here in enumerate(source):
            before = source[j - 1]
            here_in = orientation * _cross(a, b, here) >= 0
            before_in = orientation * _cross(a, b, before) >= 0
            if here_in:
                if not before_in:
                    kept.append(_meet(before, here, a, b))
                kept.append(here)
            elif before_in:
                kept.append(_meet(before, here, a, b))
    return len(kept) >= 3 and _twice_area(kept) != 0


def _meet(p: Point, q: Point, a: Point, b: Point) -> Point:
    """Where segment ``p``-``q`` crosses the line through ``a`` and ``b``, exactly."""
    d1 = _cross(a, b, p)
    d2 = _cross(a, b, q)
    t = Fraction(d1) / (d1 - d2)
    return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)


def footprint_half_extents(thing: PlacedThing) -> tuple[int, int] | None:
    """Half the width and depth of a placed object's kind box, rounded up as the society rounds
    them; None for a being or a kind its workspace keeps, which is held by its centre."""
    if not isinstance(thing.kind, ThingKindReference):
        return None
    try:
        semantics = shipped_kind(thing.kind).semantics()
    except InvalidThingPlacement:
        return None
    if semantics["class"] != "object":
        return None
    box = semantics["body"]["box_mm"]
    return (-(-box["width"] // 2), -(-box["depth"] // 2))


def footprint_points(thing: PlacedThing) -> tuple[tuple[int, int], ...]:
    """Where a placed thing meets its ground (east and south, millimetres): its centre and, for an
    object, its kind box's four corners turned with it (:func:`footprint_half_extents`); a being,
    or a kind its workspace keeps, by its centre alone."""
    centre = (thing.transform.x_mm, thing.transform.z_mm)
    half = footprint_half_extents(thing)
    if half is None:
        return (centre,)
    corners = footprint_ring(centre, half, thing.transform.yaw_microradians)[:-1]
    return (centre, *((int(x), int(z)) for x, z in corners))


def resting_height(rest: Callable[[tuple[int, int]], int], thing: PlacedThing) -> int:
    """The height ``thing`` rests at on a ground whose height at a point is ``rest``: the highest
    under its footprint (:func:`footprint_points`), so no foot of it sinks into a step under it;
    an end over a lower surface stands clear of it, as a bench across a kerb does."""
    return max(rest(point) for point in footprint_points(thing))


def rests_on_footprint(
    rest: Callable[[tuple[int, int]], int], within_mm: int
) -> Callable[[PlacedThing], int | None]:
    """How high a placed thing stands above the highest of ``rest`` under its footprint
    (:func:`resting_height`), or None where it rests there, within ``within_mm``."""

    def height_above(thing: PlacedThing) -> int | None:
        above = thing.transform.y_mm - resting_height(rest, thing)
        return None if abs(above) <= within_mm else above

    return height_above


def blocking_things(things: Sequence[PlacedThing], moving: str) -> tuple[BlockedPart, ...]:
    """The version's other placed objects whose kinds block walking, each its footprint turned
    with it, named by its kind's label: what a moved thing may not be stood on."""
    parts = []
    for thing in things:
        if (
            thing.removed
            or thing.thing_id == moving
            or not isinstance(thing.kind, ThingKindReference)
        ):
            continue
        try:
            kind = shipped_kind(thing.kind)
        except InvalidThingPlacement:
            continue
        semantics = kind.semantics()
        if semantics["class"] != "object" or not semantics["body"]["blocks_walking"]:
            continue
        half = footprint_half_extents(thing)
        assert half is not None
        ring = footprint_ring(
            (thing.transform.x_mm, thing.transform.z_mm), half, thing.transform.yaw_microradians
        )
        label = str(kind.document.get("label") or kind.kind.replace("_", " "))
        parts.append(BlockedPart("thing", label, tuple(ring[:-1])))
    return tuple(parts)
