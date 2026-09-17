"""Exact integer tests on rings, the same tests tess's ring rule applies.

A point is ``(x, y)`` in integers. Every test is a sign of an integer product, so nothing here
rounds. The ring rule is ``exulanica.grammar.geometry.require_ring`` and
``web/packages/loom-tess/src/core/ring-triangulation.ts``: at least three vertices, no zero-length
edge, no spike, a positive twice area (counter-clockwise), and no two edges touching anywhere
except the vertex adjacent edges share. This tool cannot import either, so it states them again;
``exulanica.lettering.geometry`` states them a third time for the product, and the shared cases
hold that copy to the TypeScript one.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

Point = tuple[int, int]
Ring = Sequence[Point]


def cross(o: Point, a: Point, b: Point) -> int:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def twice_area(ring: Ring) -> int:
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
    """Whether the closed segments share any point."""
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


Edge = tuple[Point, Point, int]


def edges(ring: Ring) -> list[Edge]:
    count = len(ring)
    return [(ring[i], ring[(i + 1) % count], i) for i in range(count)]


def _candidate_pairs(first: list[Edge], second: list[Edge] | None) -> Iterator[tuple[Edge, Edge]]:
    """Edge pairs whose bounding boxes overlap, found by a sweep in x. Order does not matter."""
    tagged = [(edge, 0) for edge in first]
    if second is not None:
        tagged += [(edge, 1) for edge in second]
    tagged.sort(key=lambda item: (min(item[0][0][0], item[0][1][0]), item[1], item[0][2]))
    active: list[tuple[int, int, int, Edge, int]] = []
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


def ring_problem(ring: Ring) -> str | None:
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
    for one, two in _candidate_pairs(edges(ring), None):
        low, high = sorted((one[2], two[2]))
        if high - low < 2 or (low == 0 and high == count - 1):
            continue
        if segments_meet(one[0], one[1], two[0], two[1]):
            return f"edges {low} and {high} meet"
    return None


def point_in_ring(point: Point, ring: Ring) -> str:
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


def rings_meet(first: Ring, second: Ring) -> bool:
    """Whether any edge of one ring shares a point with any edge of the other."""
    return any(
        segments_meet(one[0], one[1], two[0], two[1])
        for one, two in _candidate_pairs(edges(first), edges(second))
    )


Part = tuple[tuple[Point, ...], tuple[tuple[Point, ...], ...]]


def parts_problem(parts: Sequence[Part]) -> str | None:
    """The first way a glyph's parts break the rule tess triangulates by, in words, or None.

    Each part is an outer ring and its holes, all counter-clockwise. A hole lies strictly inside
    its outer ring, two holes share no point, and two parts share no point; a part may sit inside
    another part's hole.
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
    for index, (outer, holes) in enumerate(parts):
        for other_index in range(index + 1, len(parts)):
            other_outer, other_holes = parts[other_index]
            if any(rings_meet(a, b) for a in (outer, *holes) for b in (other_outer, *other_holes)):
                return f"parts {index} and {other_index} meet"
            if not _apart(other_outer[0], outer, holes) or not _apart(
                outer[0], other_outer, other_holes
            ):
                return f"parts {index} and {other_index} overlap"
    return None


def _apart(point: Point, outer: Ring, holes: Sequence[Ring]) -> bool:
    """Whether a vertex of another part, whose edges meet none of this part's, lies off its area."""
    where = point_in_ring(point, outer)
    if where == "outside":
        return True
    return where == "inside" and any(point_in_ring(point, hole) == "inside" for hole in holes)


def scale(value: int, cap_height_mm: int, cap_height: int) -> int:
    """Font units to whole millimetres at a cap height: nearest, halves toward +infinity."""
    return (2 * value * cap_height_mm + cap_height) // (2 * cap_height)
