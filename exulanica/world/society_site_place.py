"""The place a site world hands its society: the walking graph, spots and destinations its records
state, as ``exulanica.society-place/v2``.

The society's place contract is producer-neutral (:mod:`exulanica.world.society_place`): this
module is its second producer from generated records, beside the city's
(:mod:`exulanica.world.society_city_place`). It reads the site grammar's records
(:mod:`exulanica.grammar.grammars.site`) and what a world's kind says each part is for
(:class:`SiteSociety`, carried in the world's receipt), and publishes:

* **Nodes**, on the level ground every site stands on (height 0), or, for a site on land, each at
  the height of the graded land under it (the ``ground`` a caller passes): stations every
  ``footway_station_spacing_mm`` (the routine policy's) along each path; a lattice over each zone
  people may walk into, at that spacing outdoors and at :data:`INDOOR_LATTICE_MM` inside; a node at
  each zone's gate, in front of each structure's door, at each area's access point and in front of
  each fixture people use; and the entry, where a kind whose people come in from homes off the
  site has their home. Behind a structure's arcade, a line of nodes along the middle of its covered
  walk (``site.loggia``) at :data:`INDOOR_LATTICE_MM`, and a node on each side of each arch, so
  people walk along the walk and in and out through any arch to the door at its back.
* **Edges** between nodes whose straight way is clear of everything a walker keeps clear of, by
  the walking capsule's radius: structures (less a covered walk behind an arcade), areas, blocking
  fixtures, closed zones and walls (a wall's gates, doors and arches are gaps in it). On land, no
  walking edge climbs more than one kerb step
  (:data:`~exulanica.world.society_place.STEP_LIMIT_MM`): a join that would is not made. Paths
  and yards are ``footway``; the way to a door is ``premises_access``; to a fixture,
  ``furniture_access``.
* **Destinations**: each structure with a home, workplace or shop role at its door, indoors, its
  capacities from its use class (a home's residents from the sleepers of the beds in its rooms
  where it has any); each area with a workplace role at its access point; each fixture with a seat
  or gathering role, outdoors, with a seat or a standing place per person along its front; and the
  off-site home.

Inhabitants enter a structure at its door and are indoors from there: the place states no level
and no room, so nobody walks a structure's rooms but the person exploring the world, and the place
says so in ``unsupported``.

Pure: no connection and no store.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import pairwise
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.grammars.site.layout import SPACING
from exulanica.grammar.grammars.site.records import (
    SiteAreaRecord,
    SiteExtentRecord,
    SiteFixtureRecord,
    SiteLoggiaRecord,
    SitePathRecord,
    SiteRoomRecord,
    SiteStructureRecord,
    SiteWallRecord,
    SiteZoneRecord,
)
from exulanica.grammar.records import canonical_record
from exulanica.world.society_catalogs import RoutineModel
from exulanica.world.society_place import (
    PLACE_PROFILE_V2,
    STEP_LIMIT_MM,
    STEPPED_KINDS,
    ceil_distance,
    seal_place,
)

if TYPE_CHECKING:
    from exulanica.world.society_city_place import CityObstructions

__all__ = [
    "CAPSULE_RADIUS_MM",
    "INDOOR_LATTICE_MM",
    "OFFSITE_HOME_ID",
    "SITE_RECORDS_PROFILE",
    "ArcadeUse",
    "GraphOverBudget",
    "PartUse",
    "SiteSociety",
    "place_from_site_records",
    "place_residents",
    "site_blocked_boxes",
    "site_blocked_parts",
    "site_obstructions",
]

SITE_RECORDS_PROFILE: Final = "exulanica.site-records/v1"
#: The walking capsule's radius, the city grammar's navigation envelope measure (340 mm), which
#: every walker keeps clear of whatever it does not walk through.
CAPSULE_RADIUS_MM: Final = 340
#: The lattice a zone inside a building is walked on: rooms are a few metres across, so the
#: outdoor station spacing would leave most of them with one place to stand.
INDOOR_LATTICE_MM: Final = 1_200
#: How far in front of a door, an area's access point or a fixture its node stands.
APPROACH_MM: Final = 600
#: How far a special node looks for a walkable node to join, and how many it joins.
JOIN_REACH_MM: Final = 9_000
JOIN_COUNT: Final = 3
OFFSITE_HOME_ID: Final = "home:offsite"


@dataclass(frozen=True, slots=True)
class PartUse:
    """What a world's kind says one part is for: its words and the use class people use it by
    ("" where it is used by nobody)."""

    label: str
    use_class: str


@dataclass(frozen=True, slots=True)
class ArcadeUse:
    """What a world's kind says people do under a structure's arches: the use class they stand
    there by, and how many stand in each bay of each covered walk."""

    use_class: str
    stands_per_bay: int


@dataclass(frozen=True, slots=True)
class SiteSociety:
    """What a site's society reads beside its records: each part's use by key, how many people
    live off the site and come in through its entry, and the words and use class of the home they
    have there. The kind's reader resolves each default once (the ``kind-society`` catalog); this
    module reads what it resolved and states none of its own."""

    uses: Mapping[str, PartUse]
    offsite_residents: int
    offsite_home: PartUse
    #: What is said of where its people are ("on this farm") and walk ("across the farm").
    here: str
    around: str
    #: The structures, by part key, whose covered walks people stand in, and by what; none for
    #: every kind that names no such use, whose society document reads as it did before.
    arcades: Mapping[str, ArcadeUse] = field(default_factory=lambda: MappingProxyType({}))

    def document(self) -> dict[str, object]:
        stood = (
            {
                "arcades": {
                    key: {"use_class": use.use_class, "stands_per_bay": use.stands_per_bay}
                    for key, use in sorted(self.arcades.items())
                }
            }
            if self.arcades
            else {}
        )
        return {
            "uses": {
                key: {"label": use.label, "use_class": use.use_class}
                for key, use in sorted(self.uses.items())
            },
            "offsite_residents": self.offsite_residents,
            "offsite_home": {
                "label": self.offsite_home.label,
                "use_class": self.offsite_home.use_class,
            },
            "place_words": {"here": self.here, "around": self.around},
            **stood,
        }

    @classmethod
    def read(cls, document: Mapping[str, Any]) -> SiteSociety:
        """A society as a receipt records it. A receipt written before kinds stated the off-site
        home and their place words records neither, and reads the ``kind-society`` catalog's."""
        from exulanica.world.kinds.catalogs import load_kind_catalogs

        defaults = load_kind_catalogs().society_defaults
        home = document.get("offsite_home")
        if home is None:
            default = defaults["offsite_home"]
            offsite_home = PartUse(default.words, default.use_class)
        else:
            offsite_home = PartUse(str(home["label"]), str(home["use_class"]))
        words = document.get("place_words") or {
            "here": defaults["here"].words,
            "around": defaults["around"].words,
        }
        return cls(
            uses={
                str(key): PartUse(str(value["label"]), str(value["use_class"]))
                for key, value in document["uses"].items()
            },
            offsite_residents=int(document["offsite_residents"]),
            offsite_home=offsite_home,
            here=str(words["here"]),
            around=str(words["around"]),
            arcades=MappingProxyType(
                {
                    str(key): ArcadeUse(str(value["use_class"]), int(value["stands_per_bay"]))
                    for key, value in document.get("arcades", {}).items()
                }
            ),
        )


Point = tuple[int, int]


@dataclass(frozen=True, slots=True)
class _Box:
    x0: int
    y0: int
    x1: int
    y1: int

    def contains(self, point: Point) -> bool:
        return self.x0 < point[0] < self.x1 and self.y0 < point[1] < self.y1

    def inflated(self, by: int) -> _Box:
        return _Box(self.x0 - by, self.y0 - by, self.x1 + by, self.y1 + by)


def _blocks(box: _Box, a: Point, b: Point) -> bool:
    """Whether the segment from a to b passes through the box's open interior: exact clipping
    (Liang and Barsky) in fractions, so a way that only runs along a box's face or touches its
    corner is clear, and one that enters it by a millimetre is not."""
    if (
        max(a[0], b[0]) <= box.x0
        or min(a[0], b[0]) >= box.x1
        or max(a[1], b[1]) <= box.y0
        or min(a[1], b[1]) >= box.y1
    ):
        return False
    enter, leave = Fraction(0), Fraction(1)
    for low, high, start, delta in (
        (box.x0, box.x1, a[0], b[0] - a[0]),
        (box.y0, box.y1, a[1], b[1] - a[1]),
    ):
        if delta == 0:
            if not low < start < high:
                return False
            continue
        first, second = Fraction(low - start, delta), Fraction(high - start, delta)
        if first > second:
            first, second = second, first
        enter, leave = max(enter, first), min(leave, second)
        if enter >= leave:
            return False
    return enter < leave


def _fixture_box(record: SiteFixtureRecord) -> _Box:
    along_x, along_y = (
        (record.width_mm, record.depth_mm)
        if record.yaw_quarter_turns % 2 == 0
        else (record.depth_mm, record.width_mm)
    )
    return _Box(
        record.x_mm - along_x // 2,
        record.y_mm - along_y // 2,
        record.x_mm - along_x // 2 + along_x,
        record.y_mm - along_y // 2 + along_y,
    )


#: A fixture's front, a unit vector in the site frame, by its quarter turns: a slot's front is +y.
_FRONT: Final = {0: (0, 1), 1: (-1, 0), 2: (0, -1), 3: (1, 0)}
_FACING: Final = {"north": (0, 1), "east": (1, 0), "south": (0, -1), "west": (-1, 0)}


def _wall_boxes(record: SiteWallRecord) -> list[_Box]:
    """The wall as boxes round each solid piece between its openings."""
    half = record.thickness_mm // 2
    along_x = record.start_y_mm == record.end_y_mm
    length = (record.end_x_mm - record.start_x_mm) + (record.end_y_mm - record.start_y_mm)
    pieces = []
    reached = 0
    for opening in record.openings:
        pieces.append((reached, opening.offset_mm))
        reached = opening.offset_mm + opening.width_mm
    pieces.append((reached, length))
    boxes = []
    for start, end in pieces:
        if end <= start:
            continue
        if along_x:
            boxes.append(
                _Box(
                    record.start_x_mm + start,
                    record.start_y_mm - half,
                    record.start_x_mm + end,
                    record.start_y_mm + half,
                )
            )
        else:
            boxes.append(
                _Box(
                    record.start_x_mm - half,
                    record.start_y_mm + start,
                    record.start_x_mm + half,
                    record.start_y_mm + end,
                )
            )
    return boxes


class GraphOverBudget(ValueError):
    """A site's walking graph grew past the most places it may hold, while it was being built."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"its walking graph grew past {limit} places")
        self.limit = limit


class _Cells:
    """Boxes indexed by the square cells they overlap, so a point or a short way asks only the boxes
    near it: a box that holds a point overlaps the point's cell, and one a way passes through
    overlaps a cell of the way's bounding rectangle, so the answers are the ones asking every box
    gives."""

    CELL: Final = 8_000

    def __init__(self, boxes: Sequence[_Box]) -> None:
        self.boxes = list(boxes)
        self.cells: dict[tuple[int, int], list[int]] = {}
        cell = self.CELL
        for index, box in enumerate(self.boxes):
            for cx in range(box.x0 // cell, box.x1 // cell + 1):
                for cy in range(box.y0 // cell, box.y1 // cell + 1):
                    self.cells.setdefault((cx, cy), []).append(index)

    def holding(self, point: Point) -> list[_Box]:
        cell = self.CELL
        return [self.boxes[i] for i in self.cells.get((point[0] // cell, point[1] // cell), ())]

    def near(self, a: Point, b: Point) -> list[_Box]:
        cell = self.CELL
        found: set[int] = set()
        for cx in range(min(a[0], b[0]) // cell, max(a[0], b[0]) // cell + 1):
            for cy in range(min(a[1], b[1]) // cell, max(a[1], b[1]) // cell + 1):
                found.update(self.cells.get((cx, cy), ()))
        return [self.boxes[i] for i in sorted(found)]


class _Graph:
    def __init__(
        self,
        blocked: Sequence[_Box],
        node_limit: int | None = None,
        ground: Callable[[int, int], int] | None = None,
    ) -> None:
        self.blocked = _Cells([box.inflated(CAPSULE_RADIUS_MM) for box in blocked])
        self.nodes: dict[str, Point] = {}
        self.edges: dict[tuple[str, str], dict[str, Any]] = {}
        self.node_limit = node_limit
        self.ground = ground

    def height(self, point: Point) -> int:
        return 0 if self.ground is None else self.ground(point[0], point[1])

    def free(self, point: Point) -> bool:
        return not any(box.contains(point) for box in self.blocked.holding(point))

    def clear(self, a: Point, b: Point) -> bool:
        return not any(_blocks(box, a, b) for box in self.blocked.near(a, b))

    def add(self, name: str, point: Point) -> None:
        if (
            self.node_limit is not None
            and name not in self.nodes
            and len(self.nodes) >= self.node_limit
        ):
            raise GraphOverBudget(self.node_limit)
        self.nodes[name] = point

    def join(self, a: str, b: str, kind: str) -> bool:
        if a == b:
            return False
        pair = (a, b) if a < b else (b, a)
        if pair in self.edges:
            return True
        pa, pb = self.nodes[a], self.nodes[b]
        if pa == pb or not self.clear(pa, pb):
            return False
        if (
            self.ground is not None
            and kind not in STEPPED_KINDS
            and abs(self.height(pa) - self.height(pb)) > STEP_LIMIT_MM
        ):
            return False
        self.edges[pair] = {
            "edge_id": f"{pair[0]}|{pair[1]}",
            "from_node_id": pair[0],
            "to_node_id": pair[1],
            "length_mm": ceil_distance(list(pa), list(pb)),
            "kind": kind,
        }
        return True

    def join_nearest(self, name: str, among: Iterable[str], kind: str) -> int:
        """Join a node to up to :data:`JOIN_COUNT` of the nearest of ``among`` within
        :data:`JOIN_REACH_MM` whose ways are clear; how many it joined."""
        here = self.nodes[name]
        ranked = sorted(
            ((self.nodes[other][0] - here[0]) ** 2 + (self.nodes[other][1] - here[1]) ** 2, other)
            for other in among
            if other != name
        )
        joined = 0
        for distance_squared, other in ranked:
            if distance_squared > JOIN_REACH_MM * JOIN_REACH_MM or joined == JOIN_COUNT:
                break
            if self.join(name, other, kind):
                joined += 1
        return joined


def _lattice(box: _Box, spacing: int) -> list[Point]:
    points = []
    x = box.x0 + spacing // 2
    while x < box.x1:
        y = box.y0 + spacing // 2
        while y < box.y1:
            points.append((x, y))
            y += spacing
        x += spacing
    return points


def _steps(start: int, end: int, step: int) -> list[int]:
    """Evenly spaced figures from ``start`` to ``end``, both kept, at most ``step`` apart."""
    if end <= start:
        return [start]
    count = max(1, -(-(end - start) // step))
    return [start + (end - start) * index // count for index in range(count + 1)]


@dataclass(frozen=True, slots=True)
class _ZoneFrame:
    """A zone's own frame, as its layout was laid in: ``u`` along its front, ``v`` into it."""

    zone: SiteZoneRecord

    @property
    def length(self) -> int:
        z = self.zone
        return (
            (z.max_y_mm - z.min_y_mm)
            if z.frontage in ("east", "west")
            else (z.max_x_mm - z.min_x_mm)
        )

    @property
    def depth(self) -> int:
        z = self.zone
        return (
            (z.max_x_mm - z.min_x_mm)
            if z.frontage in ("east", "west")
            else (z.max_y_mm - z.min_y_mm)
        )

    def point(self, u: int, v: int) -> Point:
        z = self.zone
        if z.frontage == "east":
            return z.max_x_mm - v, z.min_y_mm + u
        if z.frontage == "west":
            return z.min_x_mm + v, z.max_y_mm - u
        if z.frontage == "south":
            return z.min_x_mm + u, z.min_y_mm + v
        return z.max_x_mm - u, z.max_y_mm - v

    def local(self, x: int, y: int) -> tuple[int, int]:
        z = self.zone
        if z.frontage == "east":
            return y - z.min_y_mm, z.max_x_mm - x
        if z.frontage == "west":
            return z.max_y_mm - y, x - z.min_x_mm
        if z.frontage == "south":
            return x - z.min_x_mm, y - z.min_y_mm
        return z.max_x_mm - x, z.max_y_mm - y


def _line(
    graph: _Graph,
    prefix: str,
    at_point: dict[Point, str],
    corridor: list[str],
    walkable: list[str],
    kind: str,
    points: Sequence[Point],
) -> None:
    """Lay one corridor of a zone as a line of nodes, a node already at a point reused, each
    joined to the next."""
    names = []
    for index, point in enumerate(points):
        name = at_point.get(point)
        if name is None:
            name = f"{prefix}:{kind}:{index:03d}"
            graph.add(name, point)
            at_point[point] = name
            walkable.append(name)
            corridor.append(name)
        names.append(name)
    for a, b in pairwise(names):
        graph.join(a, b, "footway")


def place_residents(place: Mapping[str, Any]) -> int:
    """How many people a site's place houses: the residents of every destination."""
    return sum(int(dest["resident_capacity"]) for dest in place["destinations"])


_OPPOSITE: Final = {"north": "south", "south": "north", "east": "west", "west": "east"}


def _body(structure: SiteStructureRecord, walks: Sequence[SiteLoggiaRecord]) -> _Box:
    """What a walker keeps out of a structure: its footprint, or with an arcade the part of it
    between its covered walks, front (ordinal 0) and back (ordinal 1) (the arcades' piers and the
    end walls beside the walks are walls)."""
    s = structure
    box = _Box(s.min_x_mm, s.min_y_mm, s.max_x_mm, s.max_y_mm)
    for walk in walks:
        side = s.door_facing if walk.ordinal == 0 else _OPPOSITE[s.door_facing]
        if side == "south":
            box = _Box(box.x0, walk.max_y_mm, box.x1, box.y1)
        elif side == "north":
            box = _Box(box.x0, box.y0, box.x1, walk.min_y_mm)
        elif side == "west":
            box = _Box(walk.max_x_mm, box.y0, box.x1, box.y1)
        else:
            box = _Box(box.x0, box.y0, walk.min_x_mm, box.y1)
    return box


def _blocked_parts(
    records: Sequence[object], uses: Mapping[str, PartUse] | None = None
) -> list[tuple[str, str, _Box]]:
    """What a walker keeps out of on a site, from its records, each with what it is and the words
    that name it: every structure (less a covered walk behind its arcade), every area (water where
    its roles say so), every fixture that blocks inside a zone, every closed zone and every wall's
    pieces, in that order. A part's words are its kind's (``uses``) where they are given, else its
    key's."""
    zones = [r for r in records if isinstance(r, SiteZoneRecord)]
    zone_ids = {zone.identity for zone in zones}
    walks: dict[str, list[SiteLoggiaRecord]] = {}
    for walk in records:
        if isinstance(walk, SiteLoggiaRecord):
            walks.setdefault(walk.structure_identity, []).append(walk)

    def words(key: str) -> str:
        use = None if uses is None else uses.get(key)
        return use.label if use is not None and use.label else key.replace("_", " ")

    parts = [
        ("structure", words(s.part_key), _body(s, walks.get(s.identity, ())))
        for s in records
        if isinstance(s, SiteStructureRecord)
    ]
    parts += [
        (
            "water" if "water" in a.roles else "area",
            words(a.part_key),
            _Box(a.min_x_mm, a.min_y_mm, a.max_x_mm, a.max_y_mm),
        )
        for a in records
        if isinstance(a, SiteAreaRecord)
    ]
    parts += [
        ("fixture", words(f.part_key), _fixture_box(f))
        for f in records
        if isinstance(f, SiteFixtureRecord) and f.blocks and f.owner_identity in zone_ids
    ]
    parts += [
        ("closed", words(z.zone_key), _Box(z.min_x_mm, z.min_y_mm, z.max_x_mm, z.max_y_mm))
        for z in zones
        if z.access == "closed"
    ]
    for wall in records:
        if isinstance(wall, SiteWallRecord):
            parts += [("wall", "wall", box) for box in _wall_boxes(wall)]
    return parts


def _blocked(records: Sequence[object]) -> list[_Box]:
    """What a walker keeps out of on a site, from its records: every structure, every area, every
    fixture that blocks inside a zone, every closed zone and every wall's pieces
    (:func:`_blocked_parts`, without their names)."""
    return [box for _kind, _words, box in _blocked_parts(records)]


def site_blocked_boxes(records: Sequence[object]) -> list[list[int]]:
    """A site's blocked boxes as plain figures, ``[x0, y0, x1, y1]`` in the site's own frame (east
    and north, millimetres): the list the place's walking graph is laid clear of, in the order the
    place builder reads them. What a society of things keeps a placed thing's standing places
    clear of on a site (:func:`site_obstructions`), handed over with the place by whoever holds
    the records."""
    return [[box.x0, box.y0, box.x1, box.y1] for box in _blocked(records)]


def site_blocked_parts(
    records: Sequence[object], uses: Mapping[str, PartUse] | None = None
) -> list[dict[str, Any]]:
    """A site's blocked boxes as :func:`site_blocked_boxes` states them, in the same order, each
    with what it is (``structure``, ``water``, ``area``, ``fixture``, ``closed`` or ``wall``) and
    the words that name it: what a move of a placed thing is kept off, and told about by name
    (:mod:`exulanica.world.thing_landing`)."""
    return [
        {"part": kind, "label": label, "box": [box.x0, box.y0, box.x1, box.y1]}
        for kind, label, box in _blocked_parts(records, uses)
    ]


def site_obstructions(boxes: Iterable[Sequence[int]]) -> CityObstructions:
    """The obstructions a site's blocked boxes make, in the shape a town's have and in the site's
    frame (east, north), by the tests the site's own walking graph is laid with: each box grown by
    the walking capsule's radius, a point free where no box holds it and a step clear where it
    passes through none."""
    from exulanica.world.society_city_place import CityObstructions

    cells = _Cells([_Box(*(int(v) for v in box)).inflated(CAPSULE_RADIUS_MM) for box in boxes])

    def stands(point: Point) -> bool:
        return not any(box.contains(point) for box in cells.holding(point))

    def steps(a: Point, b: Point) -> bool:
        return not any(_blocks(box, a, b) for box in cells.near(a, b))

    return CityObstructions(stands=stands, steps=steps)


@dataclass(frozen=True, slots=True)
class _Arcade:
    """A covered walk as it is walked: the points along its middle and, for each arch, the point
    in front of it outside and the point on the walk's middle behind it."""

    walk: SiteLoggiaRecord
    part_key: str
    middle: tuple[Point, ...]
    arches: tuple[tuple[Point, Point], ...]
    #: The unit step along the walk, from its lesser end.
    along: Point


def _arcades(
    structures: Sequence[SiteStructureRecord],
    walls: Sequence[SiteWallRecord],
    walks: Sequence[SiteLoggiaRecord],
) -> dict[str, list[_Arcade]]:
    """Each zone's covered walks, by zone identity, in the order of their identities. A walk faces
    its structure's front (ordinal 0) or its back (ordinal 1), and its arches are those of the
    arcaded wall on that side."""
    by_identity = {s.identity: s for s in structures}
    found: dict[str, list[_Arcade]] = {}
    for walk in sorted(walks, key=lambda w: w.identity):
        structure = by_identity[walk.structure_identity]
        side = structure.door_facing if walk.ordinal == 0 else _OPPOSITE[structure.door_facing]
        edge = {
            "south": walk.min_y_mm,
            "north": walk.max_y_mm,
            "west": walk.min_x_mm,
            "east": walk.max_x_mm,
        }[side]
        front = min(
            (
                wall
                for wall in walls
                if wall.owner_identity == structure.identity
                and any(opening.kind == "arch" for opening in wall.openings)
            ),
            key=lambda wall: abs(
                (wall.start_y_mm if side in ("north", "south") else wall.start_x_mm) - edge
            ),
        )
        dx, dy = _FACING[side]
        along_x = side in ("north", "south")
        middle_at = (
            (walk.min_y_mm + walk.max_y_mm) // 2
            if along_x
            else (walk.min_x_mm + walk.max_x_mm) // 2
        )
        low, high = (walk.min_x_mm, walk.max_x_mm) if along_x else (walk.min_y_mm, walk.max_y_mm)
        out = front.thickness_mm // 2 + APPROACH_MM
        arches = []
        for opening in front.openings:
            if opening.kind != "arch":
                continue
            centre = opening.offset_mm + opening.width_mm // 2
            if along_x:
                at = (front.start_x_mm + centre, front.start_y_mm)
                inside = (at[0], middle_at)
            else:
                at = (front.start_x_mm, front.start_y_mm + centre)
                inside = (middle_at, at[1])
            arches.append(((at[0] + dx * out, at[1] + dy * out), inside))
        figures = set(_steps(low + APPROACH_MM, high - APPROACH_MM, INDOOR_LATTICE_MM))
        figures |= {inside[0] if along_x else inside[1] for _, inside in arches}
        middle = tuple(
            (figure, middle_at) if along_x else (middle_at, figure) for figure in sorted(figures)
        )
        found.setdefault(structure.zone_identity, []).append(
            _Arcade(walk, structure.part_key, middle, tuple(arches), (1, 0) if along_x else (0, 1))
        )
    return found


def place_from_site_records(
    *,
    place_id: str,
    records: Sequence[object],
    society: SiteSociety,
    routine: RoutineModel,
    input_seq: int = 1,
    node_limit: int | None = None,
    ground: Callable[[int, int], int] | None = None,
) -> dict[str, Any]:
    """Derive the place a site's records and its society's uses support, sealed by its digest.

    With ``node_limit``, building stops with :class:`GraphOverBudget` as soon as the walking graph
    would hold more places than that, rather than after the whole graph is built. With ``ground``
    (a site on land), every node and spot stands at the height it gives in millimetres above the
    land's datum, and no walking edge climbs more than one kerb step; without it the place is the
    level site's, byte for byte."""
    extent = next(r for r in records if isinstance(r, SiteExtentRecord))
    paths = [r for r in records if isinstance(r, SitePathRecord)]
    zones = [r for r in records if isinstance(r, SiteZoneRecord)]
    structures = [r for r in records if isinstance(r, SiteStructureRecord)]
    areas = [r for r in records if isinstance(r, SiteAreaRecord)]
    fixtures = [r for r in records if isinstance(r, SiteFixtureRecord)]
    rooms = [r for r in records if isinstance(r, SiteRoomRecord)]
    zone_ids = {zone.identity for zone in zones}
    arcades = _arcades(
        structures,
        [r for r in records if isinstance(r, SiteWallRecord)],
        [r for r in records if isinstance(r, SiteLoggiaRecord)],
    )
    policy = routine.policy
    spacing = policy["standing_spacing_mm"]
    station = policy["footway_station_spacing_mm"]
    # Corridors are laid at the station spacing; the lattice over the rest of a zone's ground,
    # which only adds places to stand and ways round, at twice it outdoors.
    corridor_step = station if extent.enclosure == "open" else INDOOR_LATTICE_MM
    lattice = 2 * station if extent.enclosure == "open" else INDOOR_LATTICE_MM
    graph = _Graph(_blocked(records), node_limit, ground)
    walkable: list[str] = []
    spots: dict[str, dict[str, Any]] = {}
    destinations: list[dict[str, Any]] = []
    unsupported = {"inhabitants do not walk a structure's rooms: they are indoors from its door"}

    # Paths: stations along each path's long axis, joined in order.
    path_stations: list[list[str]] = []
    for path in sorted(paths, key=lambda p: p.ordinal):
        along_y = (path.max_y_mm - path.min_y_mm) >= (path.max_x_mm - path.min_x_mm)
        middle = (
            (path.min_x_mm + path.max_x_mm) // 2
            if along_y
            else (path.min_y_mm + path.max_y_mm) // 2
        )
        low, high = (path.min_y_mm, path.max_y_mm) if along_y else (path.min_x_mm, path.max_x_mm)
        count = max(1, (high - low) // station)
        names = []
        for index in range(count + 1):
            at = low + (high - low) * index // count
            at = min(max(at, low + CAPSULE_RADIUS_MM), high - CAPSULE_RADIUS_MM)
            point = (middle, at) if along_y else (at, middle)
            name = f"path:{path.ordinal}:{index:03d}"
            graph.add(name, point)
            names.append(name)
            walkable.append(name)
        for a, b in pairwise(names):
            graph.join(a, b, "footway")
        path_stations.append(names)
    every_station = [name for names in path_stations for name in names]
    for names in path_stations[1:]:
        for name in names:
            graph.join_nearest(name, path_stations[0], "footway")

    # Zones people walk into. Each has corridors the layout keeps clear by construction (along
    # its front, down both its sides, and across the lane in front of its areas), laid as lines of
    # nodes; a lattice over the rest of its ground, each lattice node joined to its neighbours and,
    # near a corridor, to it; and a gate joined to the corridor and to the nearest path station.
    spacing_of = SPACING[extent.enclosure]
    lattice_of: dict[str, list[str]] = {}
    #: Each covered walk's node behind each of its arches, by the walk's identity.
    behind_arches: dict[str, list[str]] = {}
    for zone in sorted(zones, key=lambda z: z.ordinal):
        if zone.access == "closed":
            continue
        frame = _ZoneFrame(zone)
        prefix = f"zone:{zone.ordinal:02d}"
        at_point: dict[Point, str] = {}
        corridor: list[str] = []

        half_side, front = spacing_of.side_margin // 2, spacing_of.verge // 2
        last_u, back_v = frame.length - half_side, frame.depth - spacing_of.side_margin
        line = functools.partial(_line, graph, prefix, at_point, corridor, walkable)
        line("front", [frame.point(u, front) for u in _steps(half_side, last_u, corridor_step)])
        line("low", [frame.point(half_side, v) for v in _steps(front, back_v, corridor_step)])
        line("high", [frame.point(last_u, v) for v in _steps(front, back_v, corridor_step)])
        lanes = sorted(
            {
                frame.local(a.access_x_mm, a.access_y_mm)[1]
                for a in areas
                if a.zone_identity == zone.identity
            }
        )
        for index, lane_v in enumerate(lanes):
            line(
                f"lane{index}",
                [frame.point(u, lane_v) for u in _steps(half_side, last_u, corridor_step)],
            )
        # Each covered walk: a line along its middle, and a node in front of each arch joined
        # through it to the point behind it on that line.
        walks = arcades.get(zone.identity, [])
        open_ground = len(corridor)
        outside: list[str] = []
        for index, arcade in enumerate(walks):
            line(f"loggia{index}", arcade.middle)
            behind_arches[arcade.walk.identity] = [at_point[inside] for _, inside in arcade.arches]
            for arch, (out, inside) in enumerate(arcade.arches):
                if not graph.free(out):
                    continue
                name = f"{prefix}:loggia{index}:arch{arch:02d}"
                graph.add(name, out)
                walkable.append(name)
                outside.append(name)
                graph.join(name, at_point[inside], "footway")
        covered = [
            _Box(a.walk.min_x_mm, a.walk.min_y_mm, a.walk.max_x_mm, a.walk.max_y_mm) for a in walks
        ]
        box = _Box(zone.min_x_mm, zone.min_y_mm, zone.max_x_mm, zone.max_y_mm)
        yard = []
        for point in _lattice(box, lattice):
            if not graph.free(point) or point in at_point:
                continue
            if any(walk.contains(point) for walk in covered):
                continue
            name = f"{prefix}:yard:{point[0]:07d}:{point[1]:07d}"
            graph.add(name, point)
            yard.append(name)
            walkable.append(name)
        by_point = {graph.nodes[name]: name for name in yard}
        for name in yard:
            x, y = graph.nodes[name]
            for neighbour in ((x + lattice, y), (x, y + lattice)):
                other = by_point.get(neighbour)
                if other is not None:
                    graph.join(name, other, "footway")
        # Each lattice node near a corridor joins it, so no clear pocket of ground is left apart.
        reach = lattice * lattice
        for name in yard:
            x, y = graph.nodes[name]
            near = [
                c
                for c in corridor
                if (graph.nodes[c][0] - x) ** 2 + (graph.nodes[c][1] - y) ** 2 <= reach
            ]
            if near:
                graph.join_nearest(name, near, "footway")
        dx, dy = _FACING[zone.frontage]
        gate = f"{prefix}:gate"
        graph.add(gate, (zone.gate_x_mm - dx * APPROACH_MM, zone.gate_y_mm - dy * APPROACH_MM))
        threshold = f"{prefix}:gate:out"
        graph.add(threshold, (zone.gate_x_mm + dx * APPROACH_MM, zone.gate_y_mm + dy * APPROACH_MM))
        graph.join(gate, threshold, "footway")
        graph.join_nearest(threshold, every_station, "footway")
        graph.join_nearest(gate, corridor, "footway")
        # The node in front of each arch joins the zone's ground, as a lattice node does.
        for name in outside:
            graph.join_nearest(name, corridor[:open_ground] + yard, "footway")
        lattice_of[zone.identity] = corridor + outside + yard + [gate]

    def join_into_zone(name: str, zone_identity: str, kind: str) -> None:
        among = lattice_of.get(zone_identity, [])
        if graph.join_nearest(name, among, kind) == 0:
            graph.join_nearest(name, every_station, kind)

    by_zone_structure = {s.identity: s.zone_identity for s in structures}
    room_structure = {room.identity: room.structure_identity for room in rooms}
    sleepers: dict[str, int] = {}
    for fixture in fixtures:
        owner = room_structure.get(fixture.owner_identity)
        if owner is not None and fixture.sleepers:
            sleepers[owner] = sleepers.get(owner, 0) + fixture.sleepers

    def use_of(part_key: str) -> PartUse:
        return society.uses.get(part_key, PartUse(part_key.replace("_", " "), ""))

    def destination(
        name: str,
        subject: str,
        node: str,
        origin: str,
        use_key: str,
        label: str,
        *,
        indoors: bool,
        spot_ids: Sequence[str] = (),
        residents: int | None = None,
    ) -> None:
        use = routine.use_classes[use_key]
        workplace = use.kind == "workplace"
        destinations.append(
            {
                "destination_id": name,
                "subject_id": subject,
                "node_id": node,
                "origin": origin,
                "object_id": None,
                "affordances": sorted(use.visitor_affordances),
                "duration_ticks": None,
                "indoors": indoors,
                "enabled": True,
                "visitor_capacity": use.visitor_capacity if indoors else len(spot_ids),
                "spot_ids": sorted(spot_ids),
                "use_class": use.key,
                "label": label,
                "address_number": None,
                "street_segment_ordinal": None,
                "staff_capacity": use.staff_per_unit,
                "resident_capacity": use.resident_capacity if residents is None else residents,
                "role": None
                if use.kind == "furniture"
                else {"key": use.role_key, "label": use.role_label},
                "shift": {"start_minute": use.shift_start, "minutes": use.shift_minutes}
                if workplace
                else None,
            }
        )

    for structure in sorted(structures, key=lambda s: s.identity):
        part = use_of(structure.part_key)
        roles = set(structure.roles)
        if structure.door_width_mm == 0 or not roles & {"home", "workplace", "shop"}:
            continue
        dx, dy = _FACING[structure.door_facing]
        name = f"door:{structure.identity}"
        graph.add(
            name, (structure.door_x_mm + dx * APPROACH_MM, structure.door_y_mm + dy * APPROACH_MM)
        )
        join_into_zone(name, by_zone_structure[structure.identity], "premises_access")
        use_key = part.use_class
        residents = None
        if "home" in roles and structure.identity in sleepers:
            residents = sleepers[structure.identity]
        destination(
            f"structure:{structure.identity}",
            f"site.structure:{structure.identity}",
            name,
            "premises",
            use_key,
            part.label,
            indoors=True,
            residents=residents,
        )
    # People standing under the arches: for each covered walk of a structure whose kind names a use
    # for it, one destination, its places along the walk's middle at each arch, the routine's
    # standing spacing apart.
    for zone_walks in arcades.values():
        for arcade in zone_walks:
            stood = society.arcades.get(arcade.part_key)
            names = behind_arches.get(arcade.walk.identity)
            if stood is None or names is None:
                continue
            name = f"loggia:{arcade.walk.identity}"
            made = []
            for arch, ((_, inside), node) in enumerate(zip(arcade.arches, names, strict=True)):
                for index in range(stood.stands_per_bay):
                    offset = (2 * index - (stood.stands_per_bay - 1)) * spacing // 2
                    point = (
                        inside[0] + arcade.along[0] * offset,
                        inside[1] + arcade.along[1] * offset,
                    )
                    if not graph.free(point):
                        continue
                    spot_id = f"{name}:stand:{arch:02d}:{index}"
                    spots[spot_id] = {
                        "spot_id": spot_id,
                        "node_id": node,
                        "position_mm": [point[0], point[1]],
                        "support_z_mm": graph.height(point),
                        "destination_ids": [name],
                    }
                    made.append(spot_id)
            destination(
                name,
                f"site.loggia:{arcade.walk.identity}",
                names[len(names) // 2],
                "furniture",
                stood.use_class,
                routine.use_classes[stood.use_class].label,
                indoors=False,
                spot_ids=made,
            )
    for area in sorted(areas, key=lambda a: a.identity):
        part = use_of(area.part_key)
        if not set(area.roles) & {"workplace", "shop"} or not part.use_class:
            continue
        name = f"access:{area.identity}"
        graph.add(name, (area.access_x_mm, area.access_y_mm))
        join_into_zone(name, area.zone_identity, "premises_access")
        destination(
            f"area:{area.identity}",
            f"site.area:{area.identity}",
            name,
            "premises",
            part.use_class,
            part.label,
            indoors=False,
        )
    for fixture in sorted(fixtures, key=lambda f: f.identity):
        if fixture.owner_identity not in zone_ids:
            continue
        roles = set(fixture.roles)
        places = (
            fixture.seats
            if "seat" in roles
            else fixture.stands
            if roles & {"gathering", "shop", "workplace"}
            else 0
        )
        if not places:
            continue
        part = use_of(fixture.part_key)
        use_key = part.use_class
        if not use_key:
            continue
        front = _FRONT[fixture.yaw_quarter_turns]
        half_depth = fixture.depth_mm // 2
        reach = half_depth + APPROACH_MM + (spacing if "seat" not in roles else 0)
        # Approached from its front, or from its back where the layout set something nearer its
        # front than the approach (it keeps only its clearance round a fixture); its places then
        # face its back. Where both are blocked it is approached from its front, unreached.
        fx, fy = next(
            (
                (dx, dy)
                for dx, dy in (front, (-front[0], -front[1]))
                if graph.free((fixture.x_mm + dx * reach, fixture.y_mm + dy * reach))
            ),
            front,
        )
        across = (-fy, fx)
        node = f"fixture:{fixture.identity}"
        graph.add(node, (fixture.x_mm + fx * reach, fixture.y_mm + fy * reach))
        join_into_zone(node, fixture.owner_identity, "furniture_access")
        places_at = half_depth - 200 if "seat" in roles else half_depth + spacing
        made = []
        for index in range(places):
            offset = (2 * index - (places - 1)) * spacing // 2
            point = (
                fixture.x_mm + fx * places_at + across[0] * offset,
                fixture.y_mm + fy * places_at + across[1] * offset,
            )
            spot_id = f"{node}:{'seat' if 'seat' in roles else 'stand'}:{index}"
            spots[spot_id] = {
                "spot_id": spot_id,
                "node_id": node,
                "position_mm": [point[0], point[1]],
                "support_z_mm": graph.height(point),
                "destination_ids": [f"fixture:{fixture.identity}"],
            }
            made.append(spot_id)
        destination(
            f"fixture:{fixture.identity}",
            f"site.fixture:{fixture.identity}",
            node,
            "furniture",
            use_key,
            part.label,
            indoors=False,
            spot_ids=made,
        )

    # The entry, and the home of everybody who lives off the site, beyond it.
    entry = "entry"
    graph.add(entry, (extent.entry_x_mm, CAPSULE_RADIUS_MM))
    graph.join_nearest(entry, path_stations[0], "footway")
    if society.offsite_residents:
        # Everybody who lives off the site has their home at its entry: they come in through it
        # and are not drawn once they have gone back out.
        destination(
            OFFSITE_HOME_ID,
            "site.extent:offsite",
            entry,
            "premises",
            society.offsite_home.use_class,
            society.offsite_home.label,
            indoors=True,
            residents=society.offsite_residents,
        )

    # Standing spots: on paths and yards, two standing radii apart and clear of everything. A spot
    # closer than two radii to another lies in its square of side two radii or a neighbouring one.
    radius = policy["standing_radius_mm"]
    apart = 2 * radius
    taken: dict[tuple[int, int], list[Point]] = {}

    def take(point: Point) -> None:
        taken.setdefault((point[0] // apart, point[1] // apart), []).append(point)

    def crowded(point: Point) -> bool:
        cx, cy = point[0] // apart, point[1] // apart
        return any(
            (point[0] - p[0]) ** 2 + (point[1] - p[1]) ** 2 < apart * apart
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for p in taken.get((cx + dx, cy + dy), ())
        )

    for spot in spots.values():
        take((spot["position_mm"][0], spot["position_mm"][1]))
    for name in sorted(walkable):
        point = graph.nodes[name]
        if not graph.free(point):
            continue
        if crowded(point):
            continue
        spots[name] = {
            "spot_id": name,
            "node_id": name,
            "position_mm": [point[0], point[1]],
            "support_z_mm": graph.height(point),
            "destination_ids": [],
        }
        take(point)

    records_digest = sha256_of_canonical(
        sorted(
            [type(r).RECORD_KIND, canonical_record(r).decode("utf-8")]  # type: ignore[attr-defined]
            for r in records
        )
    ).hex()
    paths_half = min(
        (min(p.max_x_mm - p.min_x_mm, p.max_y_mm - p.min_y_mm) // 2 for p in paths), default=0
    )
    place = {
        "profile": PLACE_PROFILE_V2,
        "place_id": place_id,
        "source": {
            "kind": "site-records",
            "profile": SITE_RECORDS_PROFILE,
            "input_seq": input_seq,
            "document_sha256": records_digest,
        },
        "frame": {
            "name": "site_local",
            "axis_order": ["x", "y"],
            "horizontal_unit": "millimetre",
            "vertical_unit": "millimetre",
            "datum": (
                "site_local z, the level ground every site stands on"
                if ground is None
                else "site_local z, above the land's datum, the sea's level"
            ),
        },
        "routine_sha256": routine.sha256,
        "clearance_mm": paths_half,
        "nodes": [
            {
                "node_id": name,
                "position_mm": [point[0], point[1]],
                "support_z_mm": graph.height(point),
                "street_id": None,
            }
            for name, point in sorted(graph.nodes.items())
        ],
        "edges": sorted(graph.edges.values(), key=lambda edge: edge["edge_id"]),
        "spots": [spots[key] for key in sorted(spots)],
        "crossings": [],
        "destinations": sorted(destinations, key=lambda d: d["destination_id"]),
        "unavailable_destinations": [],
        "unsupported": sorted(unsupported),
        "availability": "available",
        "unavailable_reason": None,
        # What is said of where its people are and walk, in the kind's words, read where a town
        # says "in this town" and "through town".
        "words": {"here": society.here, "around": society.around},
    }
    return seal_place(place)
