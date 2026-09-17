"""Integer plane geometry that record validators share: rings, extents and exact tests.

Everything here is exact integer arithmetic, so a Python validator and a TypeScript reader that
agree on the integers agree on every answer. A ring is a tuple of ``(x, y)`` integer pairs,
counter-clockwise, not closed by repeating its first point. Edge ``i`` runs from vertex ``i`` to
vertex ``i + 1``, wrapping at the end, and that index is how a record names an edge. The run
length of an edge is ``isqrt(dx * dx + dy * dy)``, the floor of its true length; a layout
measured along an edge is measured in that integer.

**A ring is refused rather than repaired** when it has fewer than three vertices, a zero-length
edge (which includes closing it by repeating the first vertex), a spike (an edge that doubles
back along the one before it), a clockwise or zero area, or two edges that touch anywhere except
at the vertex adjacent edges share.

**The centroid rule** is the polygon centroid with each coordinate floored:
``floor(sum((x_i + x_j) * c_i) / (3 * A2))``, where ``c_i`` is the cross product of vertex ``i``
and its successor ``j`` and ``A2`` is twice the signed area. Records that need a centroid carry
it as a field, so a reader never has to repeat this arithmetic at magnitudes a double cannot hold.

The package forbids ``math``, so the square root below is Newton's method on integers.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.records import require_integer

__all__ = [
    "BOUNDARY",
    "INSIDE",
    "OUTSIDE",
    "Extent",
    "edge_run_length",
    "extent_contains_point",
    "extent_contains_ring",
    "integer_sqrt",
    "point_in_ring",
    "polyline_run_length",
    "require_extent",
    "require_ring",
    "ring_centroid",
    "ring_inside_ring",
    "ring_is_convex",
    "ring_twice_area",
    "ring_within_ring",
    "rings_disjoint",
    "segments_cross",
    "segments_intersect",
]

INSIDE: Final = "inside"
OUTSIDE: Final = "outside"
BOUNDARY: Final = "boundary"

Point = tuple[int, int]
Ring = tuple[Point, ...]


@dataclass(frozen=True, slots=True)
class Extent:
    """An axis-aligned box in integer millimetres, both corners inclusive.

    It bounds everything a record generates. A reader may draw it, pick with it or test a
    tessellation against it; it is never a measurement.
    """

    min_x_mm: int
    min_y_mm: int
    min_z_mm: int
    max_x_mm: int
    max_y_mm: int
    max_z_mm: int


def require_extent(name: str, value: object) -> Extent:
    if type(value) is not Extent:
        raise InvalidRecordError(f"{name} is an Extent, got {type(value).__name__}")
    for axis in ("x", "y", "z"):
        low = require_integer(f"{name}.min_{axis}_mm", getattr(value, f"min_{axis}_mm"))
        high = require_integer(f"{name}.max_{axis}_mm", getattr(value, f"max_{axis}_mm"))
        if low > high:
            raise InvalidRecordError(f"{name}: min_{axis}_mm is above max_{axis}_mm")
    return value


def extent_contains_point(extent: Extent, x: int, y: int, z: int | None = None) -> bool:
    inside = extent.min_x_mm <= x <= extent.max_x_mm and extent.min_y_mm <= y <= extent.max_y_mm
    if z is None:
        return inside
    return inside and extent.min_z_mm <= z <= extent.max_z_mm


def extent_contains_ring(extent: Extent, ring: Ring) -> bool:
    return all(extent_contains_point(extent, x, y) for x, y in ring)


def integer_sqrt(value: int) -> int:
    """The floor of the square root of a non-negative ``int``, exactly."""
    if type(value) is not int or value < 0:
        raise InvalidRecordError(f"a square root is taken of a non-negative int, got {value!r}")
    if value < 2:
        return value
    estimate = 1 << ((value.bit_length() + 1) >> 1)
    while True:
        better = (estimate + value // estimate) >> 1
        if better >= estimate:
            return estimate
        estimate = better


def _cross(origin: Point, a: Point, b: Point) -> int:
    return (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0])


def _on_segment(point: Point, a: Point, b: Point) -> bool:
    return (
        _cross(a, b, point) == 0
        and min(a[0], b[0]) <= point[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= point[1] <= max(a[1], b[1])
    )


def segments_intersect(p1: Point, p2: Point, q1: Point, q2: Point) -> bool:
    """Whether two closed segments share any point, touching included."""
    d1 = _cross(q1, q2, p1)
    d2 = _cross(q1, q2, p2)
    d3 = _cross(p1, p2, q1)
    d4 = _cross(p1, p2, q2)
    if ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4)):
        return True
    return (
        (d1 == 0 and _on_segment(p1, q1, q2))
        or (d2 == 0 and _on_segment(p2, q1, q2))
        or (d3 == 0 and _on_segment(q1, p1, p2))
        or (d4 == 0 and _on_segment(q2, p1, p2))
    )


def segments_cross(p1: Point, p2: Point, q1: Point, q2: Point) -> bool:
    """Whether two segments cross at a single point inside both, touching excluded."""
    d1 = _cross(q1, q2, p1)
    d2 = _cross(q1, q2, p2)
    d3 = _cross(p1, p2, q1)
    d4 = _cross(p1, p2, q2)
    return ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4))


def ring_twice_area(ring: Ring) -> int:
    """Twice the signed area: positive for a counter-clockwise ring."""
    count = len(ring)
    return sum(
        ring[index][0] * ring[(index + 1) % count][1]
        - ring[(index + 1) % count][0] * ring[index][1]
        for index in range(count)
    )


def _require_points(name: str, value: object, minimum_count: int) -> Ring:
    if not isinstance(value, tuple) or len(value) < minimum_count:
        raise InvalidRecordError(f"{name} is a tuple of at least {minimum_count} integer pairs")
    for index, point in enumerate(value):
        if not isinstance(point, tuple) or len(point) != 2:
            raise InvalidRecordError(f"{name}[{index}] is an (x, y) pair")
        require_integer(f"{name}[{index}][0]", point[0])
        require_integer(f"{name}[{index}][1]", point[1])
    return value


def require_ring(name: str, value: object, *, minimum_count: int = 3) -> Ring:
    """A simple counter-clockwise ring, or ``InvalidRecordError`` naming what is wrong."""
    ring = _require_points(name, value, max(3, minimum_count))
    count = len(ring)
    for index in range(count):
        if ring[index] == ring[(index + 1) % count]:
            raise InvalidRecordError(
                f"{name}: edge {index} has zero length; a ring is not closed by repetition"
            )
    for index in range(count):
        before, here, after = ring[index - 1], ring[index], ring[(index + 1) % count]
        dot = (here[0] - before[0]) * (after[0] - here[0]) + (here[1] - before[1]) * (
            after[1] - here[1]
        )
        if _cross(before, here, after) == 0 and dot < 0:
            raise InvalidRecordError(f"{name}: vertex {index} is a spike")
    if ring_twice_area(ring) <= 0:
        raise InvalidRecordError(f"{name} is counter-clockwise with a positive area")
    for first in range(count):
        for second in range(first + 2, count):
            if first == 0 and second == count - 1:
                continue
            if segments_intersect(
                ring[first], ring[(first + 1) % count], ring[second], ring[(second + 1) % count]
            ):
                raise InvalidRecordError(f"{name}: edges {first} and {second} intersect")
    return ring


def edge_run_length(ring: Ring, ordinal: int) -> int:
    """The integer run length of edge ``ordinal``: the floor of its true length."""
    if type(ordinal) is not int or not 0 <= ordinal < len(ring):
        raise InvalidRecordError(f"edge {ordinal!r} is not an edge of a {len(ring)}-vertex ring")
    (x0, y0), (x1, y1) = ring[ordinal], ring[(ordinal + 1) % len(ring)]
    return integer_sqrt((x1 - x0) * (x1 - x0) + (y1 - y0) * (y1 - y0))


def polyline_run_length(points: tuple[tuple[int, ...], ...]) -> int:
    """The sum of the integer run lengths of each piece, in plan (the first two coordinates)."""
    total = 0
    for here, after in pairwise(points):
        dx, dy = after[0] - here[0], after[1] - here[1]
        total += integer_sqrt(dx * dx + dy * dy)
    return total


def point_in_ring(point: Point, ring: Ring) -> str:
    """``INSIDE``, ``OUTSIDE`` or ``BOUNDARY``, exactly."""
    count = len(ring)
    for index in range(count):
        if _on_segment(point, ring[index], ring[(index + 1) % count]):
            return BOUNDARY
    inside = False
    px, py = point
    for index in range(count):
        (ax, ay), (bx, by) = ring[index], ring[(index + 1) % count]
        if (ay > py) != (by > py):
            left = (px - ax) * (by - ay)
            right = (py - ay) * (bx - ax)
            if (by > ay and left < right) or (by < ay and left > right):
                inside = not inside
    return INSIDE if inside else OUTSIDE


def _edges_meet(first: Ring, second: Ring) -> bool:
    for a in range(len(first)):
        for b in range(len(second)):
            if segments_intersect(
                first[a],
                first[(a + 1) % len(first)],
                second[b],
                second[(b + 1) % len(second)],
            ):
                return True
    return False


def ring_inside_ring(inner: Ring, outer: Ring) -> bool:
    """Whether ``inner`` lies strictly inside ``outer``, touching nowhere."""
    if any(point_in_ring(point, outer) != INSIDE for point in inner):
        return False
    return not _edges_meet(inner, outer)


def ring_within_ring(inner: Ring, outer: Ring) -> bool:
    """Whether ``inner`` lies inside ``outer`` or on its boundary, never outside it.

    Every vertex and every edge midpoint of ``inner`` is inside or on ``outer``, and no edge of
    one crosses an edge of the other. Midpoints are tested on both rings doubled, so the test
    stays exact.
    """
    doubled_outer = tuple((2 * x, 2 * y) for x, y in outer)
    for index in range(len(inner)):
        (x0, y0), (x1, y1) = inner[index], inner[(index + 1) % len(inner)]
        if point_in_ring((2 * x0, 2 * y0), doubled_outer) == OUTSIDE:
            return False
        if point_in_ring((x0 + x1, y0 + y1), doubled_outer) == OUTSIDE:
            return False
    for a in range(len(inner)):
        for b in range(len(outer)):
            if segments_cross(
                inner[a], inner[(a + 1) % len(inner)], outer[b], outer[(b + 1) % len(outer)]
            ):
                return False
    return True


def ring_is_convex(ring: Ring) -> bool:
    """Whether every vertex of a counter-clockwise ring turns left, strictly."""
    count = len(ring)
    return all(
        _cross(ring[index - 1], ring[index], ring[(index + 1) % count]) > 0
        for index in range(count)
    )


def rings_disjoint(first: Ring, second: Ring) -> bool:
    """Whether two rings share no point at all, boundaries included."""
    if _edges_meet(first, second):
        return False
    if any(point_in_ring(point, second) != OUTSIDE for point in first):
        return False
    return all(point_in_ring(point, first) == OUTSIDE for point in second)


def ring_centroid(ring: Ring) -> Point:
    """The centroid with each coordinate floored; see the module docstring for the rule."""
    twice_area = ring_twice_area(ring)
    if twice_area <= 0:
        raise InvalidRecordError("a centroid is taken of a counter-clockwise ring")
    count = len(ring)
    sum_x = 0
    sum_y = 0
    for index in range(count):
        (x0, y0), (x1, y1) = ring[index], ring[(index + 1) % count]
        cross = x0 * y1 - x1 * y0
        sum_x += (x0 + x1) * cross
        sum_y += (y0 + y1) * cross
    return sum_x // (3 * twice_area), sum_y // (3 * twice_area)
