"""Integer plane geometry for road paths and vehicle footprints.

Everything here is exact integer arithmetic on millimetre coordinates. The only irrational
quantity, a Euclidean length, goes through :func:`ceil_length`, the society engine's rule
(the ceiling of the true length), and every place that needs one says which way it rounds so a
bound can only get more conservative.

**Paths.** A :class:`Polyline` is a path a vehicle follows. A position on it is an integer
distance from its start, measured with ceiling piece lengths. :meth:`Polyline.point_at` maps a
position to an integer point with ``round_half_down``, so two callers always agree on it.

**Footprints.** A body on a path is the union of one flat-ended rectangle per piece it covers,
each ``half_width`` either side of the piece. :func:`rectangle` rounds the corners outward, so a
rectangle never shrinks by rounding. :func:`convex_overlap` is the separating axis test on
integer polygons, which is exact.

**Near sets.** :func:`near_interval` gives, for one path, an interval of positions whose point
is within a radius of another polyline. It is a superset of the true set, built from exact
predicates and outward rounding, because it is used to decide which vehicles must not be in two
places at once.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from math import isqrt
from typing import Final

from exulanica.canonical import round_half_down

__all__ = [
    "SUBDIVISION_MM",
    "Point",
    "Polyline",
    "ceil_length",
    "circumradius_at_least",
    "circumradius_floor",
    "convex_overlap",
    "corridor_piece",
    "cross",
    "dot",
    "near_interval",
    "offtracking_mm",
    "point_segment_within",
    "rectangle",
    "segments_intersect",
    "segments_within",
]

Point = tuple[int, int]

#: Near sets are refined on pieces of the other polyline no longer than this. A superset
#: either way; shorter pieces only make it tighter.
SUBDIVISION_MM: Final = 500


def dot(a: Point, b: Point) -> int:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Point, b: Point) -> int:
    return a[0] * b[1] - a[1] * b[0]


def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def ceil_sqrt(value: int) -> int:
    root = isqrt(value)
    return root if root * root == value else root + 1


def ceil_length(a: Point, b: Point) -> int:
    """The ceiling of the Euclidean distance between two integer points."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    return ceil_sqrt(dx * dx + dy * dy)


def offtracking_mm(radius_mm: int, wheelbase_mm: int) -> int:
    """How far a rigid wheelbase's rear axle tracks inside its front axle on a circle, rounded up.

    The front axle centre runs on ``radius``; the rear axle centre, whose velocity points along the
    body, runs on ``sqrt(radius**2 - wheelbase**2)``. This is geometry, not a parameter. A radius
    no longer than the wheelbase cannot be driven at all and returns the whole radius.
    """
    if radius_mm <= wheelbase_mm:
        return radius_mm
    inner_squared = radius_mm * radius_mm - wheelbase_mm * wheelbase_mm
    return radius_mm - isqrt(inner_squared)


def circumradius_at_least(a: Point, b: Point, c: Point, radius_mm: int) -> bool:
    """Whether the circle through three points has at least ``radius``. Collinear is infinite.

    ``R = |ab| |bc| |ca| / (2 |cross|)``, compared squared, in integers.
    """
    turn = cross(_sub(b, a), _sub(c, b))
    if turn == 0:
        return True
    ab, bc, ca = _sub(b, a), _sub(c, b), _sub(a, c)
    return dot(ab, ab) * dot(bc, bc) * dot(ca, ca) >= 4 * radius_mm * radius_mm * turn * turn


def circumradius_floor(a: Point, b: Point, c: Point) -> int | None:
    """The circumradius rounded down, or ``None`` for collinear points."""
    turn = cross(_sub(b, a), _sub(c, b))
    if turn == 0:
        return None
    ab, bc, ca = _sub(b, a), _sub(c, b), _sub(a, c)
    numerator = dot(ab, ab) * dot(bc, bc) * dot(ca, ca)
    denominator = 4 * turn * turn
    return isqrt(numerator // denominator)


def _orientation(a: Point, b: Point, c: Point) -> int:
    value = cross(_sub(b, a), _sub(c, a))
    return (value > 0) - (value < 0)


def _on_segment(a: Point, b: Point, p: Point) -> bool:
    return min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    o1, o2 = _orientation(a, b, c), _orientation(a, b, d)
    o3, o4 = _orientation(c, d, a), _orientation(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and _on_segment(a, b, c))
        or (o2 == 0 and _on_segment(a, b, d))
        or (o3 == 0 and _on_segment(c, d, a))
        or (o4 == 0 and _on_segment(c, d, b))
    )


def point_segment_within(p: Point, a: Point, b: Point, radius: int) -> bool:
    """Whether ``p`` is within ``radius`` of the closed segment ``ab``. Exact."""
    ab, ap = _sub(b, a), _sub(p, a)
    along = dot(ap, ab)
    squared_limit = radius * radius
    if along <= 0:
        return dot(ap, ap) <= squared_limit
    length_squared = dot(ab, ab)
    if along >= length_squared:
        bp = _sub(p, b)
        return dot(bp, bp) <= squared_limit
    across = cross(ab, ap)
    return across * across <= squared_limit * length_squared


def segments_within(a: Point, b: Point, c: Point, d: Point, radius: int) -> bool:
    """Whether two closed segments come within ``radius`` of each other. Exact."""
    if segments_intersect(a, b, c, d):
        return True
    return (
        point_segment_within(a, c, d, radius)
        or point_segment_within(b, c, d, radius)
        or point_segment_within(c, a, b, radius)
        or point_segment_within(d, a, b, radius)
    )


def _lerp(a: Point, b: Point, numerator: int, denominator: int) -> Point:
    return (
        a[0] + round_half_down((b[0] - a[0]) * numerator, denominator),
        a[1] + round_half_down((b[1] - a[1]) * numerator, denominator),
    )


@dataclass(frozen=True, slots=True)
class Polyline:
    points: tuple[Point, ...]
    #: ``offsets[i]`` is where piece ``i`` starts; the last entry is the length.
    offsets: tuple[int, ...]

    @classmethod
    def of(cls, points: Sequence[Point]) -> Polyline:
        if len(points) < 2:
            raise ValueError("a polyline has at least two points")
        offsets = [0]
        for a, b in pairwise(points):
            if a == b:
                raise ValueError("a polyline has no zero-length piece")
            offsets.append(offsets[-1] + ceil_length(a, b))
        return cls(tuple(points), tuple(offsets))

    @property
    def length(self) -> int:
        return self.offsets[-1]

    @property
    def piece_count(self) -> int:
        return len(self.points) - 1

    def piece(self, index: int) -> tuple[Point, Point]:
        return self.points[index], self.points[index + 1]

    def piece_direction(self, index: int) -> Point:
        a, b = self.piece(index)
        return _sub(b, a)

    def piece_index(self, position: int) -> int:
        """The piece holding ``position``; a vertex belongs to the piece that starts there."""
        if position <= 0:
            return 0
        if position >= self.length:
            return self.piece_count - 1
        return bisect_right(self.offsets, position) - 1

    def point_at(self, position: int) -> Point:
        position = min(max(position, 0), self.length)
        index = self.piece_index(position)
        a, b = self.piece(index)
        start, end = self.offsets[index], self.offsets[index + 1]
        return _lerp(a, b, position - start, end - start)

    def span(self, start: int, end: int) -> list[tuple[int, Point, Point]]:
        """``(piece index, from, to)`` for every piece the closed interval covers, clamped."""
        start = min(max(start, 0), self.length)
        end = min(max(end, 0), self.length)
        if end < start:
            return []
        first, last = self.piece_index(start), self.piece_index(end)
        if end == self.offsets[last] and last > first:
            last -= 1
        pieces = []
        for index in range(first, last + 1):
            a = self.point_at(max(start, self.offsets[index]))
            b = self.point_at(min(end, self.offsets[index + 1]))
            if a != b or start == end:
                pieces.append((index, a, b))
        return pieces


def rectangle(a: Point, b: Point, left: int, right: int) -> tuple[Point, ...] | None:
    """The flat-ended rectangle reaching ``left`` and ``right`` of ``ab``, corners rounded outward.

    ``None`` for a degenerate piece, which a caller treats as a point body. The corners run
    counter-clockwise.
    """
    direction = _sub(b, a)
    length_squared = dot(direction, direction)
    if length_squared == 0:
        return None
    length = isqrt(length_squared)

    def away(value: int) -> int:
        # Divide by the floored length and round away from zero, so no side comes out short.
        magnitude = -(-abs(value) // length)
        return magnitude if value >= 0 else -magnitude

    lx, ly = away(-direction[1] * left), away(direction[0] * left)
    rx, ry = away(direction[1] * right), away(-direction[0] * right)
    return (
        (a[0] + rx, a[1] + ry),
        (b[0] + rx, b[1] + ry),
        (b[0] + lx, b[1] + ly),
        (a[0] + lx, a[1] + ly),
    )


def _projection(polygon: Sequence[Point], axis: Point) -> tuple[int, int]:
    values = [dot(point, axis) for point in polygon]
    return min(values), max(values)


def convex_overlap(first: Sequence[Point], second: Sequence[Point]) -> bool:
    """Whether two convex integer polygons share interior points. Touching is not overlap."""
    for polygon in (first, second):
        count = len(polygon)
        for index in range(count):
            edge = _sub(polygon[(index + 1) % count], polygon[index])
            axis = (-edge[1], edge[0])
            if axis == (0, 0):
                continue
            low_a, high_a = _projection(first, axis)
            low_b, high_b = _projection(second, axis)
            if high_a <= low_b or high_b <= low_a:
                return False
    return True


def _subdivide(a: Point, b: Point) -> list[tuple[Point, Point]]:
    length = ceil_length(a, b)
    count = max(1, -(-length // SUBDIVISION_MM))
    points = [_lerp(a, b, step, count) for step in range(count + 1)]
    return list(pairwise(points))


def _box(a: Point, b: Point) -> tuple[int, int, int, int]:
    return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])


def _boxes_within(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int], reach: int
) -> bool:
    return not (
        first[2] + reach < second[0]
        or second[2] + reach < first[0]
        or first[3] + reach < second[1]
        or second[3] + reach < first[1]
    )


def corridor_piece(a: Point, b: Point, left: int, right: int) -> tuple[Point, Point, int]:
    """A piece whose corridor reaches ``left`` and ``right`` of it, as a shifted symmetric one.

    Returns the piece moved sideways by half the difference and the half-width that, with the
    1 mm the rounded shift can lose, still covers both sides.
    """
    if left == right:
        return a, b, left
    direction = _sub(b, a)
    length = isqrt(dot(direction, direction))
    shift = left - right
    # Twice the shift over twice the length keeps the halving exact until the final rounding.
    sx = round_half_down(-direction[1] * shift, 2 * length)
    sy = round_half_down(direction[0] * shift, 2 * length)
    half = -(-(left + right) // 2) + 2
    return (a[0] + sx, a[1] + sy), (b[0] + sx, b[1] + sy), half


def near_interval(
    path: Polyline,
    path_extents: Sequence[tuple[int, int]],
    other: Polyline,
    other_extents: Sequence[tuple[int, int]],
) -> tuple[int, int] | None:
    """A superset of the positions on ``path`` whose corridor meets the corridor of ``other``.

    Piece ``i`` of ``path`` reaches ``path_extents[i] = (left, right)`` either side of itself, and
    likewise for ``other``. Each corridor piece becomes a shifted symmetric one
    (:func:`corridor_piece`). For each piece of ``path``, every short chunk of ``other`` whose
    capsule meets the piece's contributes the projection of its capsule onto the piece, rounded
    outward. A sideways shift does not move a projection, so positions stay those of ``path``.
    The union is closed into one interval; ``None`` when nothing meets.
    """
    if len(path_extents) != path.piece_count or len(other_extents) != other.piece_count:
        raise ValueError("one extent pair per piece")
    chunks = []
    for index in range(other.piece_count):
        c0, d0, radius = corridor_piece(*other.piece(index), *other_extents[index])
        for chunk in _subdivide(c0, d0):
            chunks.append((radius, chunk, _box(*chunk)))
    low: int | None = None
    high: int | None = None
    for index in range(path.piece_count):
        a, b, own_radius = corridor_piece(*path.piece(index), *path_extents[index])
        piece_box = _box(a, b)
        direction = _sub(b, a)
        squared = dot(direction, direction)
        root = ceil_sqrt(squared)
        piece_length = path.offsets[index + 1] - path.offsets[index]
        for other_radius, (c, d), chunk_box in chunks:
            reach = own_radius + other_radius + 2
            if not _boxes_within(piece_box, chunk_box, reach):
                continue
            if not segments_within(a, b, c, d, reach):
                continue
            first = dot(_sub(c, a), direction)
            second = dot(_sub(d, a), direction)
            lower = min(first, second) - reach * root
            upper = max(first, second) + reach * root
            # Positions on the piece run to its ceiling length, so scale by piece_length/squared
            # (parameter per unit of projection), flooring the lower and ceiling the upper.
            start = max(0, (lower * piece_length) // squared)
            end = min(piece_length, -((-upper * piece_length) // squared))
            if end < start:
                continue
            start += path.offsets[index]
            end += path.offsets[index]
            low = start if low is None else min(low, start)
            high = end if high is None else max(high, end)
    if low is None or high is None:
        return None
    return low, high
