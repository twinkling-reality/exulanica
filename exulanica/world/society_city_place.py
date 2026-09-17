"""The generated city as a society place: a pure function from city grammar records to the contract.

Only the city grammar's version 2 record classes are read, never a generator, so a generated
city's tile documents drop in unchanged. :func:`place_from_city_documents` holds each tile document
to every check the grammar defines, then derives the place from the records the tiles own;
:func:`place_from_city_records` is the derivation itself, over records that each pass their own
shape. Everything is integer geometry in the grammar's ``city_local`` frame:

- **Footways.** A curb's footway runs beside its kerb line, offset into the footway by the kerb
  top's width and half the footway's width, with a standing station every catalogued spacing. A
  station is named by its distance along the kerb line from the line's first point, and a point on
  a vertex takes its offset from the piece arriving there (the first point from the first piece).
- **Corners.** Walking counter-clockwise round the face a curb bounds, its footway joins the
  footway of the curb its record names as next, round the offset of the corner arc between them,
  so footways meet only round one block's corner and never across a carriageway. The arc is
  followed closely enough that no straight piece cuts more than :data:`CORNER_TOLERANCE_MM` inside
  it; where the footway is wider than the corner is round, the two footway lines meet at a point.
- **Crossings.** A carriageway is crossed only on a crossing record, between the footway points
  beside the two ends of its line. The place's crossing keeps the record's identity and signal.
- **What supports a person.** The city descriptor's navigation table, read as data
  (:func:`city_navigation`), is the only source of what a person may stand on: footways need
  curbs to be support, a crossing or a door is walked only when its kind is support, and a place
  whose curbs are not support is refused.
- **Entrances.** A premises unit is an indoor destination reached through the first of its
  entrances that opens onto a footway in the place: a premises-access edge runs from the footway
  point nearest the threshold to the threshold. A door onto a lot reaches no footway; a unit with
  no door onto a footway in the place is stated as unsupported and is never given one.
- **Furniture.** Street furniture whose furniture class has a use-class entry (a bench) is an
  outdoor destination with one seat per catalogued visitor, side by side along the record's
  direction vector, which is its local ``+x`` and runs along its seat.
- **Streets.** A footway, entrance or furniture node names its segment's street by the street's
  identity, and a corner node names none. A street's name is presentation, never identity:
  :func:`city_street_names` reads names from the city's own street records for a label, and no
  name is copied into the place, so restyling a street never changes a society's input.

Standing spots keep two standing radii apart, and keep the nav envelope's capsule radius clear of
everything the navigation table says obstructs: a building's base ring, and each furniture or tree
part whose bottom is below the capsule height, as a box in its object's frame. A seat is clear of
every obstruction but its own bench. A footway station that fails either is walked through, not
stood on. Walking lines are not yet routed round obstructions: the place counts every footway or
door piece that passes within a capsule radius of a low part, and says so. A premises unit whose
use class the routine does not know is listed as unsupported, never guessed.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.grammar import shapes
from exulanica.grammar.catalogs import Catalog
from exulanica.grammar.geometry import OUTSIDE, point_in_ring
from exulanica.grammar.grammars.city import CITY_GRAMMAR, CITY_SHAPES_BY_TYPE
from exulanica.grammar.grammars.city.common import FormPart
from exulanica.grammar.grammars.city.document import TileDocument, validate_city_document
from exulanica.grammar.grammars.city.facade import EntranceRecord
from exulanica.grammar.grammars.city.massing import MassingRecord
from exulanica.grammar.grammars.city.parcels import ParcelRecord
from exulanica.grammar.grammars.city.premises import PremisesRecord
from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord, StreetTreeRecord
from exulanica.grammar.grammars.city.streets import (
    CrossingRecord,
    CurbEdgeRecord,
    StreetRecord,
    StreetSegmentRecord,
)
from exulanica.grammar.records import canonical_record
from exulanica.world.society_catalogs import RoutineModel
from exulanica.world.society_place import PLACE_PROFILE, ceil_distance, seal_place

__all__ = [
    "CITY_RECORDS_PROFILE",
    "CORNER_TOLERANCE_MM",
    "READ_KINDS",
    "CityNavigation",
    "city_navigation",
    "city_street_names",
    "place_from_city_documents",
    "place_from_city_records",
]

CITY_RECORDS_PROFILE: Final = "exulanica.city-records/v2"
#: The record kinds a place is derived from, and so the kinds its input digest covers.
READ_KINDS: Final = (
    StreetSegmentRecord,
    CurbEdgeRecord,
    CrossingRecord,
    ParcelRecord,
    MassingRecord,
    PremisesRecord,
    EntranceRecord,
    StreetFurnitureRecord,
    StreetTreeRecord,
)
#: How far, in millimetres, a straight piece of a corner's footway may cut inside its arc.
CORNER_TOLERANCE_MM: Final = 250
_CORNER_DEPTH: Final = 8
#: Plan coordinates in an object's frame are kept in millionths of a millimetre.
_E6: Final = 10**6
#: The side of a cell in the obstruction index, in millimetres.
_CELL_MM: Final = 4_000

Point = tuple[int, int]


def _round_div(numerator: int, denominator: int) -> int:
    """Integer division rounded half away from zero; the same on every platform."""
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    quotient, remainder = divmod(abs(numerator), denominator)
    if 2 * remainder >= denominator:
        quotient += 1
    return quotient if numerator >= 0 else -quotient


def _scaled(vector: Point, distance: int) -> Point:
    """``vector`` at ``distance`` millimetres long; the length is taken in millionths of a mm."""
    length = math.isqrt((vector[0] * vector[0] + vector[1] * vector[1]) * 10**12)
    return (
        _round_div(vector[0] * distance * 10**6, length),
        _round_div(vector[1] * distance * 10**6, length),
    )


def _left(vector: Point) -> Point:
    return (-vector[1], vector[0])


def _add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1])


def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


class _Kerb:
    """One curb's kerb line in plan, and the footway beside it."""

    def __init__(self, curb: CurbEdgeRecord, segment: StreetSegmentRecord) -> None:
        points: list[Point] = []
        for x, y, _ in curb.kerb_line_mm:
            if not points or points[-1] != (x, y):
                points.append((x, y))
        if len(points) < 2:
            raise ValueError(f"curb {curb.identity} has a kerb line of no length")
        self.curb = curb
        self.segment = segment
        self.points = points
        self.key = f"{segment.segment_ordinal}:{curb.side}"
        self.offset = curb.kerb_width_mm + curb.footway_width_mm // 2
        self.pieces: list[tuple[int, int, Point, Point]] = []
        along = 0
        for a, b in pairwise(points):
            length = ceil_distance(a, b)
            self.pieces.append((along, length, a, b))
            along += length
        self.length = along

    def footway(self, along: int) -> Point:
        """The footway point beside the kerb line ``along`` millimetres from its first point."""
        along = max(0, min(self.length, along))
        start, length, a, b = next(
            (piece for piece in self.pieces if along <= piece[0] + piece[1]), self.pieces[-1]
        )
        t = along - start
        base = (
            a[0] + _round_div((b[0] - a[0]) * t, length),
            a[1] + _round_div((b[1] - a[1]) * t, length),
        )
        normal = _left(_sub(b, a))
        if self.curb.side == "right":
            normal = (-normal[0], -normal[1])
        return _add(base, _scaled(normal, self.offset))

    def project(self, point: Point) -> tuple[int, int]:
        """``(squared gap, along)`` of the kerb line point nearest ``point``, the first on a tie."""
        best: tuple[int, int] | None = None
        for start, length, a, b in self.pieces:
            dx, dy = b[0] - a[0], b[1] - a[1]
            px, py = point[0] - a[0], point[1] - a[1]
            squared = dx * dx + dy * dy
            t = max(0, min(squared, px * dx + py * dy))
            foot = (a[0] + _round_div(dx * t, squared), a[1] + _round_div(dy * t, squared))
            candidate = (
                (point[0] - foot[0]) ** 2 + (point[1] - foot[1]) ** 2,
                start + _round_div(length * t, squared),
            )
            if best is None or candidate < best:
                best = candidate
        assert best is not None
        return best

    def walk_end(self) -> tuple[int, Point, Point]:
        """Where a counter-clockwise walk round the face leaves this curb: along, point, heading."""
        if self.curb.side == "left":
            return self.length, self.points[-1], _sub(self.points[-1], self.points[-2])
        return 0, self.points[0], _sub(self.points[0], self.points[1])

    def walk_start(self) -> tuple[int, Point, Point]:
        """Where a counter-clockwise walk round the face joins this curb: along, point, heading."""
        if self.curb.side == "left":
            return 0, self.points[0], _sub(self.points[1], self.points[0])
        return self.length, self.points[-1], _sub(self.points[-2], self.points[-1])


def _meet(p: Point, heading: Point, q: Point, other: Point) -> Point | None:
    """Where the line through ``p`` along ``heading`` meets the line through ``q`` along ``other``.

    ``None`` when they are parallel.
    """
    denominator = heading[0] * other[1] - heading[1] * other[0]
    if denominator == 0:
        return None
    w = _sub(q, p)
    t = w[0] * other[1] - w[1] * other[0]
    return (
        p[0] + _round_div(heading[0] * t, denominator),
        p[1] + _round_div(heading[1] * t, denominator),
    )


def _arc(centre: Point, radius: int, first: Point, last: Point, depth: int) -> list[Point]:
    """Points on the circle round ``centre`` strictly between two directions, finely enough."""
    a = _add(centre, _scaled(first, radius))
    b = _add(centre, _scaled(last, radius))
    twice = _sub(_add(a, b), _add(centre, centre))
    middle = _add(first, last)
    if (
        depth >= _CORNER_DEPTH
        or middle == (0, 0)
        or 2 * radius - math.isqrt(twice[0] * twice[0] + twice[1] * twice[1])
        <= 2 * CORNER_TOLERANCE_MM
    ):
        return []
    return [
        *_arc(centre, radius, first, middle, depth + 1),
        _add(centre, _scaled(middle, radius)),
        *_arc(centre, radius, middle, last, depth + 1),
    ]


def _corner(kerb: _Kerb, follower: _Kerb) -> list[Point]:
    """The footway points strictly between one curb's walk end and the next curb's walk start."""
    end_along, p, incoming = kerb.walk_end()
    start_along, q, outgoing = follower.walk_start()
    start, finish = kerb.footway(end_along), follower.footway(start_along)
    turn = incoming[0] * outgoing[1] - incoming[1] * outgoing[0]
    if start == finish or turn == 0:
        return []
    radius = kerb.curb.corner_radius_mm
    offset = (kerb.offset + follower.offset) // 2
    footway_radius = radius - offset if turn > 0 else radius + offset
    if radius == 0 or footway_radius <= 0:
        # The footway is wider than the corner is round: its two lines meet at one point.
        meeting = _meet(start, incoming, finish, outgoing)
        return [] if meeting is None or meeting in (start, finish) else [meeting]
    toward = _left(incoming) if turn > 0 else (incoming[1], -incoming[0])
    centre = _add(p, _scaled(toward, radius))
    return _arc(centre, footway_radius, _sub(p, centre), _sub(q, centre), 0)


@dataclass(frozen=True, slots=True)
class CityNavigation:
    """What the city grammar says a walking person stands on and keeps clear of, read as data.

    ``ground`` and ``obstruction`` map each record kind to its navigation row's words, and the
    capsule is the nav envelope's ``capsule_clearance`` measures.
    """

    ground: Mapping[str, str]
    obstruction: Mapping[str, str]
    capsule_radius_mm: int
    capsule_height_mm: int


def city_navigation() -> CityNavigation:
    """The city descriptor's navigation table and its nav envelope's capsule measures."""
    measures = next(
        dict(row.measures)
        for row in CITY_GRAMMAR.projection("nav_envelope").preserved
        if row.property == "capsule_clearance"
    )
    return CityNavigation(
        ground={row.kind: row.ground for row in CITY_GRAMMAR.navigation},
        obstruction={row.kind: row.obstruction for row in CITY_GRAMMAR.navigation},
        capsule_radius_mm=measures["radius_mm"],
        capsule_height_mm=measures["height_mm"],
    )


def _segment_gap_squared_below(c: Point, a: Point, b: Point, limit: int) -> bool:
    """Whether ``c`` lies closer than ``limit`` to the segment from ``a`` to ``b``, exactly."""
    s = _sub(b, a)
    w = _sub(c, a)
    length = s[0] * s[0] + s[1] * s[1]
    along = w[0] * s[0] + w[1] * s[1]
    if length == 0 or along <= 0:
        return w[0] * w[0] + w[1] * w[1] < limit * limit
    if along >= length:
        e = _sub(c, b)
        return e[0] * e[0] + e[1] * e[1] < limit * limit
    return (w[0] * w[0] + w[1] * w[1]) * length - along * along < limit * limit * length


def _crosses(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Whether the closed segments ``ab`` and ``cd`` meet, by exact orientation tests."""

    def side(p: Point, q: Point, r: Point) -> int:
        value = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (value > 0) - (value < 0)

    def within(p: Point, q: Point, r: Point) -> bool:
        return min(p[0], q[0]) <= r[0] <= max(p[0], q[0]) and min(p[1], q[1]) <= r[1] <= max(
            p[1], q[1]
        )

    d1, d2, d3, d4 = side(c, d, a), side(c, d, b), side(a, b, c), side(a, b, d)
    if d1 * d2 < 0 and d3 * d4 < 0:
        return True
    return (
        (d1 == 0 and within(c, d, a))
        or (d2 == 0 and within(c, d, b))
        or (d3 == 0 and within(a, b, c))
        or (d4 == 0 and within(a, b, d))
    )


class _LowPart:
    """One form part below the capsule height, as a box in its object's turned frame."""

    def __init__(self, owner: str, origin: Point, direction: Point, part: FormPart) -> None:
        self.owner = owner
        self.origin = origin
        self.unit = _scaled(direction, _E6)
        half_x, half_y = (part.size_x_mm + 1) // 2, (part.size_y_mm + 1) // 2
        self.low = ((part.offset_x_mm - half_x) * _E6, (part.offset_y_mm - half_y) * _E6)
        self.high = ((part.offset_x_mm + half_x) * _E6, (part.offset_y_mm + half_y) * _E6)
        # Every point of the box lies within this many millimetres of the origin on each axis.
        self.reach = abs(part.offset_x_mm) + abs(part.offset_y_mm) + half_x + half_y

    def _local(self, point: Point) -> Point:
        dx, dy = point[0] - self.origin[0], point[1] - self.origin[1]
        return (dx * self.unit[0] + dy * self.unit[1], -dx * self.unit[1] + dy * self.unit[0])

    def near_point(self, point: Point, radius: int) -> bool:
        u, v = self._local(point)
        du = max(self.low[0] - u, 0, u - self.high[0])
        dv = max(self.low[1] - v, 0, v - self.high[1])
        return du * du + dv * dv < (radius * _E6) ** 2

    def near_segment(self, a: Point, b: Point, radius: int) -> bool:
        la, lb = self._local(a), self._local(b)
        corners = (
            self.low,
            (self.high[0], self.low[1]),
            self.high,
            (self.low[0], self.high[1]),
        )
        limit = radius * _E6
        if self.near_point(a, radius) or self.near_point(b, radius):
            return True
        if any(
            _crosses(la, lb, p, q) for p, q in zip(corners, corners[1:] + corners[:1], strict=True)
        ):
            return True
        return any(_segment_gap_squared_below(corner, la, lb, limit) for corner in corners)


class _Obstructions:
    """Everything a standing capsule keeps its radius clear of, indexed by plan cell."""

    def __init__(self, radius: int) -> None:
        self.radius = radius
        self.parts: dict[tuple[int, int], list[_LowPart]] = {}
        self.rings: dict[tuple[int, int], list[tuple[tuple[int, int], ...]]] = {}

    def _cells(self, low: Point, high: Point) -> Iterable[tuple[int, int]]:
        for cx in range(low[0] // _CELL_MM, high[0] // _CELL_MM + 1):
            for cy in range(low[1] // _CELL_MM, high[1] // _CELL_MM + 1):
                yield (cx, cy)

    def add_part(self, part: _LowPart) -> None:
        reach = part.reach + self.radius
        low = (part.origin[0] - reach, part.origin[1] - reach)
        high = (part.origin[0] + reach, part.origin[1] + reach)
        for cell in self._cells(low, high):
            self.parts.setdefault(cell, []).append(part)

    def add_ring(self, ring: tuple[tuple[int, int], ...]) -> None:
        low = (min(p[0] for p in ring) - self.radius, min(p[1] for p in ring) - self.radius)
        high = (max(p[0] for p in ring) + self.radius, max(p[1] for p in ring) + self.radius)
        for cell in self._cells(low, high):
            self.rings.setdefault(cell, []).append(ring)

    def blocks_standing(self, point: Point, exempt: str | None = None) -> bool:
        cell = (point[0] // _CELL_MM, point[1] // _CELL_MM)
        for part in self.parts.get(cell, ()):
            if part.owner != exempt and part.near_point(point, self.radius):
                return True
        for ring in self.rings.get(cell, ()):
            if point_in_ring(point, ring) != OUTSIDE or any(
                _segment_gap_squared_below(point, p, q, self.radius)
                for p, q in zip(ring, ring[1:] + ring[:1], strict=True)
            ):
                return True
        return False

    def blocks_walking(self, a: Point, b: Point) -> bool:
        low = (min(a[0], b[0]), min(a[1], b[1]))
        high = (max(a[0], b[0]), max(a[1], b[1]))
        seen: set[int] = set()
        for cell in self._cells(low, high):
            for part in self.parts.get(cell, ()):
                if id(part) not in seen:
                    seen.add(id(part))
                    if part.near_segment(a, b, self.radius):
                        return True
        return False


def _validated(records: Iterable[object]) -> list[Any]:
    held = []
    for record in records:
        shape = CITY_SHAPES_BY_TYPE.get(type(record))
        if shape is None:
            raise ValueError(f"{type(record).__name__} is not a city grammar record")
        shapes.validate_record(record, shape)
        held.append(record)
    return held


def city_street_names(records: Iterable[object]) -> dict[str, dict[str, str]]:
    """Each carried street's name key and text, by street identity: presentation for a label."""
    return {
        record.identity: {"name": record.name, "name_text": record.name_text}
        for record in _validated(records)
        if isinstance(record, StreetRecord)
    }


def place_from_city_documents(
    *,
    place_id: str,
    documents: Sequence[TileDocument],
    routine: RoutineModel,
    catalogs: Sequence[Catalog],
    input_seq: int = 1,
    navigation: CityNavigation | None = None,
) -> dict[str, Any]:
    """Derive the place a set of one city's tile documents supports, each document checked first.

    The place is what the tiles own. A halo record belongs to the tile that owns it, and a place
    that needs it includes that tile.
    """
    if not documents:
        raise ValueError("a city place needs at least one tile document")
    owned: dict[str, Any] = {}
    cities = set()
    for document in documents:
        validate_city_document(document, catalogs=catalogs)
        for grammar in document.grammars:
            cities.add(grammar.subject_identity)
            for record in grammar.owned:
                if record.identity in owned:  # type: ignore[attr-defined]
                    raise ValueError(f"two tiles own record {record.identity}")  # type: ignore[attr-defined]
                owned[record.identity] = record  # type: ignore[attr-defined]
    if len(cities) != 1:
        raise ValueError("a city place's tile documents all belong to one city")
    return place_from_city_records(
        place_id=place_id,
        records=list(owned.values()),
        routine=routine,
        input_seq=input_seq,
        navigation=navigation,
    )


def place_from_city_records(
    *,
    place_id: str,
    records: Sequence[object],
    routine: RoutineModel,
    input_seq: int = 1,
    navigation: CityNavigation | None = None,
) -> dict[str, Any]:
    """Derive the place these city records support. Each record is held to its own shape first.

    ``navigation`` defaults to the city descriptor's table and capsule, :func:`city_navigation`.
    """
    navigation = navigation if navigation is not None else city_navigation()
    by_type: dict[type, list[Any]] = {kind: [] for kind in READ_KINDS}
    for record in _validated(records):
        if type(record) in by_type:
            by_type[type(record)].append(record)
    segments = {r.identity: r for r in by_type[StreetSegmentRecord]}
    if not segments:
        raise ValueError("a city place needs street segments")
    supports = {kind for kind, ground in navigation.ground.items() if ground == "support"}
    if CurbEdgeRecord.RECORD_KIND not in supports:
        raise ValueError("the city's navigation table lets nobody stand on a curb's footway")
    kerbs: dict[str, _Kerb] = {}
    for curb in sorted(by_type[CurbEdgeRecord], key=lambda r: r.identity):
        segment = segments.get(curb.segment_identity)
        if segment is None:
            raise ValueError(f"curb {curb.identity} stands on a segment outside the place")
        kerbs[curb.identity] = _Kerb(curb, segment)
    if not kerbs:
        raise ValueError("a city place needs curb edges: every footway runs beside a kerb")
    by_side = {(k.segment.identity, k.curb.side): k for k in kerbs.values()}
    policy = routine.policy
    spacing = policy["footway_station_spacing_mm"]
    unsupported: set[str] = set()

    positions: dict[str, Point] = {}
    streets: dict[str, str | None] = {}
    stations: dict[str, dict[int, str]] = {curb: {} for curb in kerbs}
    joins: list[tuple[str, str, str]] = []

    def station(kerb: _Kerb, along: int) -> str:
        along = max(0, min(kerb.length, along))
        held = stations[kerb.curb.identity].get(along)
        if held is None:
            held = f"footway:{kerb.key}:{along}"
            stations[kerb.curb.identity][along] = held
            positions[held] = kerb.footway(along)
            streets[held] = kerb.segment.street_identity
        return held

    def node(name: str, point: Point, street: str | None) -> str:
        positions[name] = point
        streets[name] = street
        return name

    for kerb in kerbs.values():
        count = max(1, kerb.length // spacing)
        for index in range(count + 1):
            station(kerb, kerb.length * index // count)

    outside = 0
    for kerb in sorted(kerbs.values(), key=lambda k: k.key):
        if not kerb.curb.next_curb_identity:
            continue
        follower = kerbs.get(kerb.curb.next_curb_identity[0])
        if follower is None:
            outside += 1
            continue
        path = [station(kerb, kerb.walk_end()[0])]
        for index, point in enumerate(_corner(kerb, follower), start=1):
            path.append(node(f"corner:{kerb.key}:{index}", point, None))
        path.append(station(follower, follower.walk_start()[0]))
        joins.extend((a, b, "footway") for a, b in pairwise(path))
    if outside:
        unsupported.add(f"footway corners that continue outside the place ({outside})")

    crossing_stops = []
    outside = 0
    walked_crossings = by_type[CrossingRecord] if CrossingRecord.RECORD_KIND in supports else []
    if by_type[CrossingRecord] and not walked_crossings:
        unsupported.add("crossings (the city's navigation table lets nobody stand on one)")
    for crossing in sorted(walked_crossings, key=lambda r: r.identity):
        ends = []
        for x, y, _ in crossing.line_mm:
            nearest = sorted(
                (*kerb.project((x, y)), side)
                for side in ("left", "right")
                if (kerb := by_side.get((crossing.segment_identity, side))) is not None
            )
            ends.append(nearest[0] if nearest else None)
        if None in ends or ends[0][2] == ends[1][2]:  # type: ignore[index]
            outside += 1
            continue
        stops = [
            station(by_side[(crossing.segment_identity, side)], along)
            for _, along, side in ends  # type: ignore[misc]
        ]
        crossing_stops.append((crossing, stops[0], stops[1]))
    if outside:
        unsupported.add(f"crossings that do not join two footways in the place ({outside})")

    entrances = {r.identity: r for r in by_type[EntranceRecord]}
    if entrances and EntranceRecord.RECORD_KIND not in supports:
        unsupported.add("entrances (the city's navigation table lets nobody stand on one)")
        entrances = {}
    lot_doors = sum(1 for r in entrances.values() if not r.approach_curb_identity)
    if lot_doors:
        unsupported.add(f"entrances onto a lot, not a footway ({lot_doors})")
    doors: dict[str, tuple[str, int]] = {}
    access: dict[str, tuple[str, int]] = {}
    unknown_uses: dict[str, int] = {}
    premises_units = sorted(by_type[PremisesRecord], key=lambda r: r.identity)
    for premises in premises_units:
        use = routine.use_classes.get(premises.use_class)
        if use is None or use.kind == "furniture":
            unknown_uses[premises.use_class] = unknown_uses.get(premises.use_class, 0) + 1
            continue
        for identity in premises.entrance_identities:
            entrance = entrances.get(identity)
            kerb = (
                kerbs.get(entrance.approach_curb_identity[0])
                if entrance is not None and entrance.approach_curb_identity
                else None
            )
            if entrance is None or kerb is None:
                continue
            if identity not in doors:
                threshold = (entrance.threshold_x_mm, entrance.threshold_y_mm)
                name = node(f"entrance:{identity}", threshold, kerb.segment.street_identity)
                joins.append((station(kerb, kerb.project(threshold)[1]), name, "premises_access"))
                doors[identity] = (name, kerb.segment.segment_ordinal)
            access[premises.identity] = doors[identity]
            break
        else:
            unsupported.add(
                f"premises {premises.identity} has no entrance onto a footway in the place"
            )
    for key, count in sorted(unknown_uses.items()):
        unsupported.add(f"premises use class {key} ({count} units) has no routine mapping")

    benches = []
    for item in sorted(by_type[StreetFurnitureRecord], key=lambda r: r.identity):
        use = routine.use_classes.get(item.furniture_class)
        if use is None or use.kind != "furniture":
            continue
        kerb = kerbs.get(item.curb_identity)
        if kerb is None:
            unsupported.add(f"street furniture {item.identity} stands beside no curb in the place")
            continue
        point = (item.x_mm, item.y_mm)
        name = node(f"furniture:{item.identity}", point, kerb.segment.street_identity)
        joins.append((station(kerb, kerb.project(point)[1]), name, "furniture_access"))
        benches.append((item, use, name, kerb))

    for chain in stations.values():
        joins.extend((chain[a], chain[b], "footway") for a, b in pairwise(sorted(chain)))
    # One node per distinct position; the lexicographically first name wins.
    canonical: dict[Point, str] = {}
    for name in sorted(positions):
        canonical.setdefault(positions[name], name)
    alias = {name: canonical[point] for name, point in positions.items()}
    nodes = {name: point for point, name in canonical.items()}
    edges: dict[frozenset[str], dict[str, Any]] = {}

    def connect(a: str, b: str, kind: str) -> str | None:
        a, b = alias[a], alias[b]
        if a == b:
            return None
        key = frozenset((a, b))
        if key not in edges:
            low, high = sorted((a, b))
            edges[key] = {
                "edge_id": f"{low}|{high}",
                "from_node_id": low,
                "to_node_id": high,
                "length_mm": ceil_distance(nodes[low], nodes[high]),
                "kind": kind,
            }
        elif kind == "crossing":
            edges[key]["kind"] = "crossing"
        return edges[key]["edge_id"]

    for a, b, kind in joins:
        connect(a, b, kind)
    crossings = []
    for crossing, a, b in crossing_stops:
        edge_id = connect(a, b, "crossing")
        if edge_id is None or any(c["edge_id"] == edge_id for c in crossings):
            unsupported.add(f"crossing {crossing.identity} shares its footway points with another")
            continue
        crossings.append(
            {
                "crossing_id": crossing.identity,
                "edge_id": edge_id,
                "street_segment_ordinal": segments[crossing.segment_identity].segment_ordinal,
                "offset_mm": crossing.offset_mm,
                "signal_id": crossing.signal_identity[0] if crossing.signal_identity else None,
            }
        )

    obstructions = _Obstructions(navigation.capsule_radius_mm)
    for kind in (StreetFurnitureRecord, StreetTreeRecord):
        if navigation.obstruction.get(kind.RECORD_KIND) != "low_parts":
            continue
        for record in by_type[kind]:
            direction = (
                (record.facing_dx_mm, record.facing_dy_mm)
                if kind is StreetFurnitureRecord
                else (1, 0)
            )
            for part in record.parts:
                if part.offset_z_mm < navigation.capsule_height_mm:
                    obstructions.add_part(
                        _LowPart(record.identity, (record.x_mm, record.y_mm), direction, part)
                    )
    if navigation.obstruction.get(MassingRecord.RECORD_KIND) == "base_ring":
        for building in by_type[MassingRecord]:
            obstructions.add_ring(building.tiers[0].ring_mm)
    read = {
        StreetFurnitureRecord.RECORD_KIND: "low_parts",
        StreetTreeRecord.RECORD_KIND: "low_parts",
        MassingRecord.RECORD_KIND: "base_ring",
    }
    for kind, region in sorted(navigation.obstruction.items()):
        if region != "none" and read.get(kind) != region:
            unsupported.add(f"obstructions of {kind} by {region}, which this place does not read")
    crowded = sum(
        1
        for edge in edges.values()
        if edge["kind"] in ("footway", "premises_access")
        and obstructions.blocks_walking(nodes[edge["from_node_id"]], nodes[edge["to_node_id"]])
    )
    if crowded:
        unsupported.add(
            f"walking pieces that pass within a capsule radius of an obstruction ({crowded})"
        )

    radius = policy["standing_radius_mm"]
    spots: dict[str, dict[str, Any]] = {}
    standing: dict[Point, list[Point]] = {}

    def keeps_apart(point: Point, apart: int) -> bool:
        """No standing spot within ``apart`` millimetres (1 means only the same point)."""
        cell = (point[0] // (2 * radius), point[1] // (2 * radius))
        return all(
            ceil_distance(point, held) >= apart
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for held in standing.get((cell[0] + dx, cell[1] + dy), ())
        )

    def stand(point: Point) -> None:
        standing.setdefault((point[0] // (2 * radius), point[1] // (2 * radius)), []).append(point)

    destinations = []
    for item, use, name, kerb in benches:
        if alias[name] != name:
            unsupported.add(f"street furniture {item.identity} stands on a footway station")
            continue
        along = (item.facing_dx_mm, item.facing_dy_mm)
        seats = []
        for seat in range(use.visitor_capacity):
            step = (2 * seat - (use.visitor_capacity - 1)) * policy["standing_spacing_mm"]
            point = _add((item.x_mm, item.y_mm), _scaled(along, _round_div(step, 2)))
            if not keeps_apart(point, 1) or obstructions.blocks_standing(point, item.identity):
                continue
            spot_id = f"{name}:seat:{seat}"
            spots[spot_id] = {
                "spot_id": spot_id,
                "node_id": name,
                "position_mm": list(point),
                "destination_ids": [name],
            }
            stand(point)
            seats.append(spot_id)
        destinations.append(
            {
                "destination_id": name,
                "subject_id": f"city.street_furniture:{item.identity}",
                "node_id": name,
                "origin": "furniture",
                "object_id": None,
                "affordances": sorted(use.visitor_affordances),
                "duration_ticks": None,
                "indoors": False,
                "enabled": True,
                "visitor_capacity": len(seats),
                "spot_ids": sorted(seats),
                "use_class": use.key,
                "label": use.label,
                "address_number": None,
                "street_segment_ordinal": kerb.segment.segment_ordinal,
                "staff_capacity": 0,
                "resident_capacity": 0,
                "role": None,
                "shift": None,
            }
        )
    clearance = min(k.curb.footway_width_mm // 2 for k in kerbs.values())
    if clearance >= radius:
        for name in sorted(nodes):
            point = nodes[name]
            if (
                name.startswith("footway:")
                and keeps_apart(point, 2 * radius)
                and not obstructions.blocks_standing(point)
            ):
                spots[name] = {
                    "spot_id": name,
                    "node_id": name,
                    "position_mm": list(point),
                    "destination_ids": [],
                }
                stand(point)
    else:
        unsupported.add("standing spots (footways are narrower than two standing radii)")

    massing = {r.identity: r for r in by_type[MassingRecord]}
    parcels = {r.identity: r for r in by_type[ParcelRecord]}
    for premises in premises_units:
        if premises.identity not in access:
            continue
        use = routine.use_classes[premises.use_class]
        door_node, frontage = access[premises.identity]
        building = massing.get(premises.building_identity)
        parcel = parcels.get(building.parcel_identity) if building is not None else None
        destinations.append(
            {
                "destination_id": f"premises:{premises.identity}",
                "subject_id": f"city.premises:{premises.identity}",
                "node_id": alias[door_node],
                "origin": "premises",
                "object_id": None,
                "affordances": sorted(use.visitor_affordances),
                "duration_ticks": None,
                "indoors": True,
                "enabled": True,
                "visitor_capacity": use.visitor_capacity,
                "spot_ids": [],
                "use_class": use.key,
                "label": use.label,
                "address_number": parcel.address_number if parcel is not None else None,
                "street_segment_ordinal": frontage,
                "staff_capacity": use.staff_per_unit,
                "resident_capacity": use.resident_capacity,
                "role": {"key": use.role_key, "label": use.role_label},
                "shift": {"start_minute": use.shift_start, "minutes": use.shift_minutes}
                if use.kind == "workplace"
                else None,
            }
        )
    # The input digest covers exactly the records read, whatever order they were handed over in.
    records_digest = sha256_of_canonical(
        sorted(
            [type(r).RECORD_KIND, canonical_record(r).decode("utf-8")]
            for kind in READ_KINDS
            for r in by_type[kind]
        )
    ).hex()
    for spot in spots.values():
        spot["destination_ids"] = sorted(spot["destination_ids"])
    place = {
        "profile": PLACE_PROFILE,
        "place_id": place_id,
        "source": {
            "kind": "city-records",
            "profile": CITY_RECORDS_PROFILE,
            "input_seq": input_seq,
            "document_sha256": records_digest,
        },
        "frame": {"name": "city_local", "axis_order": ["x", "y"], "horizontal_unit": "millimetre"},
        "routine_sha256": routine.sha256,
        "clearance_mm": clearance,
        "nodes": [
            {"node_id": name, "position_mm": list(point), "street_id": streets[name]}
            for name, point in sorted(nodes.items())
        ],
        "edges": sorted(edges.values(), key=lambda e: e["edge_id"]),
        "spots": [spots[k] for k in sorted(spots)],
        "crossings": sorted(crossings, key=lambda c: c["crossing_id"]),
        "destinations": sorted(destinations, key=lambda d: d["destination_id"]),
        "unavailable_destinations": [],
        "unsupported": sorted(unsupported),
        "availability": "available",
        "unavailable_reason": None,
    }
    return seal_place(place)
