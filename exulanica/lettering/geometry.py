"""Exact integer tests on rings: tess's ring rule, holes, parts, and whether two glyphs touch.

Every test is the sign of an integer product, so nothing rounds. The ring rule is
``exulanica.grammar.geometry.require_ring`` and ``loom-tess``'s ``requireSimpleRing``: at least
three vertices, no zero-length edge, no spike, a positive twice area (counter-clockwise), and no two
edges touching anywhere except the vertex adjacent edges share. This package sits below the grammar
and cannot import it, so the tests are stated again here; ``loom-lettering``'s ``geometry.ts`` is
the TypeScript copy, and the shared cases hold the two together.

The ring tests find candidate edge pairs by a sweep in x before testing them exactly. The sweep only
skips pairs whose bounding boxes cannot overlap, so it changes which pair is reported first, never
whether one is.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

__all__ = [
    "Part",
    "Point",
    "Ring",
    "cross",
    "glyphs_touch",
    "on_segment",
    "parts_problem",
    "point_in_ring",
    "ring_problem",
    "rings_meet",
    "segments_meet",
    "twice_area",
]

Point = tuple[int, int]
Ring = tuple[Point, ...]
#: An outer ring and its holes, all counter-clockwise.
Part = tuple[Ring, tuple[Ring, ...]]
_Edge = tuple[Point, Point, int]


def cross(o: Point, a: Point, b: Point) -> int:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def twice_area(ring: Sequence[Point]) -> int:
    count = len(ring)
    return sum(
        ring[i][0] * ring[(i + 1) % count][1] - ring[(i + 1) % count][0] * ring[i][1]
        for i in range(count)
    )


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


def on_segment(p: Point, a: Point, b: Point) -> bool:
    if cross(a, b, p) != 0:
        return False
    return min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def segments_meet(p1: Point, p2: Point, q1: Point, q2: Point) -> bool:
    """Whether the closed segments ``p1 p2`` and ``q1 q2`` share any point."""
    d1 = _sign(cross(q1, q2, p1))
    d2 = _sign(cross(q1, q2, p2))
    d3 = _sign(cross(p1, p2, q1))
    d4 = _sign(cross(p1, p2, q2))
    if d1 * d2 < 0 and d3 * d4 < 0:
        return True
    if d1 == 0 and on_segment(p1, q1, q2):
        return True
    if d2 == 0 and on_segment(p2, q1, q2):
        return True
    if d3 == 0 and on_segment(q1, p1, p2):
        return True
    return d4 == 0 and on_segment(q2, p1, p2)


def _edges(ring: Sequence[Point]) -> list[_Edge]:
    count = len(ring)
    return [(ring[i], ring[(i + 1) % count], i) for i in range(count)]


def _candidate_pairs(
    first: list[_Edge], second: list[_Edge] | None
) -> Iterator[tuple[_Edge, _Edge]]:
    """Edge pairs whose closed bounding boxes overlap: within ``first``, or across the two."""
    tagged = [(edge, 0) for edge in first]
    if second is not None:
        tagged += [(edge, 1) for edge in second]
    tagged.sort(key=lambda item: (min(item[0][0][0], item[0][1][0]), item[1], item[0][2]))
    active: list[tuple[int, int, int, _Edge, int]] = []
    for edge, tag in tagged:
        (ax, ay), (bx, by), _ = edge
        x_low, x_high = min(ax, bx), max(ax, bx)
        y_low, y_high = min(ay, by), max(ay, by)
        active = [item for item in active if item[0] >= x_low]
        for _, other_y_low, other_y_high, other, other_tag in active:
            if second is not None and other_tag == tag:
                continue
            if other_y_low <= y_high and y_low <= other_y_high:
                yield other, edge
        active.append((x_high, y_low, y_high, edge, tag))


def ring_problem(ring: Sequence[Point]) -> str | None:
    """The first ring-rule test ``ring`` fails, in words, or None."""
    count = len(ring)
    if count < 3:
        return "has fewer than three vertices"
    for i in range(count):
        if ring[i] == ring[(i + 1) % count]:
            return f"edge {i} has zero length"
    for i in range(count):
        a, b, c = ring[i - 1], ring[i], ring[(i + 1) % count]
        forward = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1])
        if cross(a, b, c) == 0 and forward < 0:
            return f"vertex {i} is a spike"
    if twice_area(ring) <= 0:
        return "is not counter-clockwise with a positive area"
    for one, two in _candidate_pairs(_edges(ring), None):
        low, high = sorted((one[2], two[2]))
        if high - low < 2 or (low == 0 and high == count - 1):
            continue
        if segments_meet(one[0], one[1], two[0], two[1]):
            return f"edges {low} and {high} meet"
    return None


def point_in_ring(point: Point, ring: Sequence[Point]) -> str:
    """``inside``, ``outside`` or ``boundary``: ``exulanica.grammar.geometry.point_in_ring``."""
    count = len(ring)
    for i in range(count):
        if on_segment(point, ring[i], ring[(i + 1) % count]):
            return "boundary"
    inside = False
    for i in range(count):
        a, b = ring[i], ring[(i + 1) % count]
        if (a[1] > point[1]) != (b[1] > point[1]):
            left = (point[0] - a[0]) * (b[1] - a[1])
            right = (point[1] - a[1]) * (b[0] - a[0])
            if b[1] > a[1] and left < right:
                inside = not inside
            if b[1] < a[1] and left > right:
                inside = not inside
    return "inside" if inside else "outside"


def rings_meet(first: Sequence[Point], second: Sequence[Point]) -> bool:
    """Whether any edge of one ring shares a point with any edge of the other."""
    return any(
        segments_meet(one[0], one[1], two[0], two[1])
        for one, two in _candidate_pairs(_edges(first), _edges(second))
    )


def _off_part(point: Point, part: Part) -> bool:
    """Whether a vertex of another part, whose edges meet none of this part's, lies off its area."""
    outer, holes = part
    where = point_in_ring(point, outer)
    if where == "outside":
        return True
    return where == "inside" and any(point_in_ring(point, hole) == "inside" for hole in holes)


def _parts_meet(first: Part, second: Part) -> bool:
    rings_first = (first[0], *first[1])
    rings_second = (second[0], *second[1])
    if any(rings_meet(a, b) for a in rings_first for b in rings_second):
        return True
    return not _off_part(second[0][0], first) or not _off_part(first[0][0], second)


def parts_problem(parts: Sequence[Part]) -> str | None:
    """The first way a glyph's parts break the rule tess triangulates by, in words, or None.

    Every ring passes the ring rule, a hole lies strictly inside its outer ring, two holes of a
    part share no point, and two parts share no point (a part may sit inside another's hole).
    """
    for index, (outer, holes) in enumerate(parts):
        problem = ring_problem(outer)
        if problem:
            return f"part {index} outer ring {problem}"
        for hole_index, hole in enumerate(holes):
            problem = ring_problem(hole)
            if problem:
                return f"part {index} hole {hole_index} {problem}"
            if rings_meet(hole, outer) or any(point_in_ring(v, outer) != "inside" for v in hole):
                return f"part {index} hole {hole_index} is not strictly inside its outer ring"
        for hole_index, hole in enumerate(holes):
            for other_index in range(hole_index + 1, len(holes)):
                other = holes[other_index]
                if (
                    rings_meet(hole, other)
                    or point_in_ring(hole[0], other) != "outside"
                    or point_in_ring(other[0], hole) != "outside"
                ):
                    return f"part {index} holes {hole_index} and {other_index} meet"
    for index, part in enumerate(parts):
        for other_index in range(index + 1, len(parts)):
            if _parts_meet(part, parts[other_index]):
                return f"parts {index} and {other_index} meet"
    return None


def _box(parts: Sequence[Part]) -> tuple[int, int, int, int]:
    xs = [x for outer, _ in parts for x, _ in outer]
    ys = [y for outer, _ in parts for _, y in outer]
    return min(xs), min(ys), max(xs), max(ys)


def glyphs_touch(first: Sequence[Part], second: Sequence[Part]) -> bool:
    """Whether two placed glyphs share any point: an edge in common or an area overlapping."""
    a = _box(first)
    b = _box(second)
    if a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1]:
        return False
    return any(_parts_meet(one, two) for one in first for two in second)
