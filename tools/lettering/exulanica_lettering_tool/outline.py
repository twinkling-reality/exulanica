"""One TrueType glyph to integer rings: flattening, the minimum edge, winding and nesting.

Every step is exact. Control points are integers, an implied on-curve point is the midpoint of two
of them and so a rational, and a flattened point is a rational until it is rounded. Nothing is
repaired quietly: a glyph whose rings break the ring rule after these steps refuses the catalog,
naming the glyph.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import floor, isqrt

from exulanica_lettering_tool.geometry import (
    Point,
    cross,
    point_in_ring,
    ring_problem,
    rings_meet,
    twice_area,
)

#: A TrueType glyf point flag: the point is on the curve.
_ON_CURVE = 0x01
#: SIMPLE_GLYPH overlap flag: the font says its contours may overlap.
_OVERLAP_SIMPLE = 0x40
#: glyf version 1 cubic flag.
_CUBIC = 0x80

RationalPoint = tuple[Fraction, Fraction]


class OutlineRefused(Exception):
    """A glyph this tool will not convert, and why."""


@dataclass(frozen=True, slots=True)
class Conversion:
    """The two rule parameters, both fixed by the promised cap-height range in millimetres."""

    cap_height: int
    minimum_cap_height_mm: int
    maximum_cap_height_mm: int

    @property
    def minimum_edge(self) -> int:
        """ceil(cap / minimum mm): one millimetre at the smallest promised cap height."""
        return -(-self.cap_height // self.minimum_cap_height_mm)

    def within_tolerance(self, ax: Fraction, ay: Fraction, steps: int) -> bool:
        """|a|^2 <= 16 n^4 t^2 with t = cap / maximum mm, compared without division."""
        squared = ax * ax + ay * ay
        return squared * self.maximum_cap_height_mm**2 <= 16 * steps**4 * self.cap_height**2


@dataclass(slots=True)
class OutlineStatistics:
    vertices_removed: int = 0
    #: The largest squared distance, in font units, from a pre-merge vertex to its final ring.
    largest_shift_squared: Fraction = Fraction(0)

    @property
    def largest_shift(self) -> int:
        """The shift rounded up to a whole font unit."""
        numerator = self.largest_shift_squared.numerator
        denominator = self.largest_shift_squared.denominator
        root = isqrt(numerator // denominator)
        while root * root * denominator < numerator:
            root += 1
        return root


def round_half_up(value: Fraction) -> int:
    return floor(value + Fraction(1, 2))


def contour_segments(
    points: list[tuple[int, int]], on_curve: list[bool]
) -> list[tuple[RationalPoint, ...]]:
    """A closed TrueType contour as lines ``(p0, p1)`` and quadratics ``(p0, c, p1)``.

    The contour starts at its first on-curve point in the font's own order; a contour with no
    on-curve point starts at the implied midpoint of its first two points.
    """
    count = len(points)
    exact = [(Fraction(x), Fraction(y)) for x, y in points]
    if not any(on_curve):
        first, second = exact[0], exact[1 % count]
        start = ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
        sequence = [(start, True)] + [(exact[(1 + i) % count], False) for i in range(count)]
    else:
        begin = on_curve.index(True)
        sequence = [
            (exact[(begin + i) % count], on_curve[(begin + i) % count]) for i in range(count)
        ]
    expanded: list[tuple[RationalPoint, bool]] = []
    for index, (point, is_on) in enumerate(sequence):
        expanded.append((point, is_on))
        following, following_on = sequence[(index + 1) % len(sequence)]
        if not is_on and not following_on:
            midpoint = ((point[0] + following[0]) / 2, (point[1] + following[1]) / 2)
            expanded.append((midpoint, True))
    segments: list[tuple[RationalPoint, ...]] = []
    total = len(expanded)
    index = 0
    while index < total:
        start_point = expanded[index][0]
        middle, middle_on = expanded[(index + 1) % total]
        if middle_on:
            segments.append((start_point, middle))
            index += 1
        else:
            segments.append((start_point, middle, expanded[(index + 2) % total][0]))
            index += 2
    return segments


def flatten(segments: list[tuple[RationalPoint, ...]], rule: Conversion) -> list[RationalPoint]:
    """Each segment's end, and for a quadratic the points B(k/n), n the fewest steps in tolerance."""
    out: list[RationalPoint] = []
    for segment in segments:
        if len(segment) == 2:
            out.append(segment[1])
            continue
        p0, p1, p2 = segment
        ax = p0[0] - 2 * p1[0] + p2[0]
        ay = p0[1] - 2 * p1[1] + p2[1]
        steps = 1
        while not rule.within_tolerance(ax, ay, steps):
            steps += 1
        for k in range(1, steps + 1):
            rest = steps - k
            denominator = steps * steps
            x = (rest * rest * p0[0] + 2 * k * rest * p1[0] + k * k * p2[0]) / denominator
            y = (rest * rest * p0[1] + 2 * k * rest * p1[1] + k * k * p2[1]) / denominator
            out.append((x, y))
    return out


def simplify(ring: list[Point]) -> list[Point]:
    """Drop repeated vertices and exactly collinear same-direction ones, which changes no shape."""
    current = list(ring)
    changed = True
    while changed:
        changed = False
        count = len(current)
        for index in range(count):
            if count > 1 and current[index] == current[(index + 1) % count]:
                del current[index]
                changed = True
                break
        if changed:
            continue
        for index in range(count):
            a, b, c = current[index - 1], current[index], current[(index + 1) % count]
            forward = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1])
            if count > 3 and cross(a, b, c) == 0 and forward > 0:
                del current[index]
                changed = True
                break
    return current


def _chebyshev(a: Point, b: Point) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def merge_short_edges(ring: list[Point], minimum_edge: int) -> tuple[list[Point], int]:
    """Remove vertices until every edge's Chebyshev length is at least ``minimum_edge``.

    The shortest edge goes first (ties by squared length, then position); of its two ends, the one
    with the smaller |cross product| with its neighbours is removed, the later one on a tie.
    """
    current = list(ring)
    removed = 0
    while True:
        count = len(current)
        if count < 3:
            raise OutlineRefused("a contour collapses under the minimum edge")
        short = []
        for index in range(count):
            a, b = current[index], current[(index + 1) % count]
            length = _chebyshev(a, b)
            if length < minimum_edge:
                squared = (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
                short.append((length, squared, index))
        if not short:
            return current, removed
        _, _, index = min(short)
        following = (index + 1) % count

        def cost(position: int, ring: list[Point] = current, count: int = count) -> int:
            return abs(cross(ring[position - 1], ring[position], ring[(position + 1) % count]))

        victim = index if cost(index) < cost(following) else following
        del current[victim]
        removed += 1
        current = simplify(current)


def _distance_squared(point: Point, a: Point, b: Point) -> Fraction:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    t = Fraction((point[0] - a[0]) * dx + (point[1] - a[1]) * dy, length)
    t = max(Fraction(0), min(Fraction(1), t))
    x = a[0] + t * dx - point[0]
    y = a[1] + t * dy - point[1]
    return x * x + y * y


def _shift_squared(before: list[Point], after: list[Point]) -> Fraction:
    count = len(after)
    return max(
        min(_distance_squared(point, after[i], after[(i + 1) % count]) for i in range(count))
        for point in before
    )


def _canonical_start(ring: list[Point]) -> tuple[Point, ...]:
    start = min(range(len(ring)), key=lambda i: (ring[i][1], ring[i][0]))
    return tuple(ring[start:] + ring[:start])


GlyphParts = tuple[tuple[tuple[Point, ...], tuple[tuple[Point, ...], ...]], ...]


def glyph_parts(
    contours: list[tuple[list[tuple[int, int]], list[int]]],
    rule: Conversion,
    statistics: OutlineStatistics,
) -> GlyphParts:
    """A glyph's contours (points and their glyf flags) as counter-clockwise parts and holes."""
    rings: list[list[Point]] = []
    for points, flags in contours:
        if any(flag & _CUBIC for flag in flags):
            raise OutlineRefused("a contour has cubic points")
        if flags and flags[0] & _OVERLAP_SIMPLE:
            raise OutlineRefused("the font marks its contours as overlapping")
        flat = flatten(contour_segments(points, [bool(f & _ON_CURVE) for f in flags]), rule)
        before = simplify([(round_half_up(x), round_half_up(y)) for x, y in flat])
        after, removed = merge_short_edges(before, rule.minimum_edge)
        if removed:
            statistics.vertices_removed += removed
            statistics.largest_shift_squared = max(
                statistics.largest_shift_squared, _shift_squared(before, after)
            )
        if twice_area(after) == 0:
            raise OutlineRefused("a contour has no area")
        rings.append(after)
    oriented = [ring if twice_area(ring) > 0 else ring[::-1] for ring in rings]
    for index, ring in enumerate(oriented):
        problem = ring_problem(ring)
        if problem:
            raise OutlineRefused(f"contour {index} {problem}")
    for index, ring in enumerate(oriented):
        for other in range(index + 1, len(oriented)):
            if rings_meet(ring, oriented[other]):
                raise OutlineRefused(f"contours {index} and {other} meet")
    depth: list[int] = []
    parent: list[int | None] = []
    for index, ring in enumerate(oriented):
        containers = [
            other
            for other, candidate in enumerate(oriented)
            if other != index and point_in_ring(ring[0], candidate) == "inside"
        ]
        depth.append(len(containers))
        parent.append(
            min(containers, key=lambda other: twice_area(oriented[other])) if containers else None
        )
    for index, ring in enumerate(rings):
        filled = depth[index] % 2 == 0
        clockwise = twice_area(ring) < 0
        if filled != clockwise:
            raise OutlineRefused(
                f"contour {index} winds against TrueType's clockwise fill for its nesting"
            )
    outers = [index for index in range(len(oriented)) if depth[index] % 2 == 0]
    parts = []
    for outer in outers:
        holes = sorted(
            (
                _canonical_start(oriented[index])
                for index in range(len(oriented))
                if depth[index] % 2 == 1 and parent[index] == outer
            ),
            key=lambda ring: (ring[0][1], ring[0][0]),
        )
        parts.append((_canonical_start(oriented[outer]), tuple(holes)))
    parts.sort(key=lambda part: (part[0][0][1], part[0][0][0]))
    return tuple(parts)
