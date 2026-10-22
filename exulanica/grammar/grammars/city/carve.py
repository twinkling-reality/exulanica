"""The integer planar carve: a ring of a plan less the rings standing on it, as convex walks with
integer corners, as the tessellator carves it (loom-tess ``piece-carve.ts`` and
``plan-arrangement.ts``), so a rule read here meets the page's own triangles.

* **Obstructions.** Each ring standing on the piece is cut into counter-clockwise triangles by the
  ring rule (:func:`ring_triangles`), and those triangles are the obstructions.
* **Rows.** The heights (plan ``y``) of the obstruction vertices that lie in the closed piece. The
  uncovered part turns inward only at such a vertex, so cut along those rows every face is convex.
* **The plan arrangement.** The piece's edges, every obstruction's edges and the rows (horizontal
  across the piece's span) are split at every point any two meet, exactly, as rational points. A
  segment records the rings it bounds as a parity (the piece is owner 0, obstruction ``i`` owner
  ``i + 1``, a row ``-1``). Around every vertex the segments are ordered by angle and each face is
  traced with itself on the left; each connected group of segments has one face of negative area,
  its outside. Groups are labelled largest outside first (ties by their first vertex's key), from
  the smallest bounded face already labelled that holds one of their vertices, and crossing a
  segment toggles its owners. A bounded face whose label holds the piece and no obstruction is kept.
* **Hulls.** Each kept face becomes the convex hull of the integer points round its vertices (each
  coordinate floored, and ceiled where it is not whole), kept only where they lie in the region the
  caller holds to, keeping the points along the hull's edges so neighbours meet vertex to vertex.

A convex piece is carved whole; a piece that turns in is cut into triangles by the ring rule first.
With nothing standing on it, a piece is its own triangles. Every test is an integer sign: nothing
here rounds but the hull, as the tessellator's does.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cmp_to_key
from itertools import pairwise

__all__ = ["open_regions", "ring_triangles"]

Plan = tuple[int, int]


@dataclass(frozen=True, slots=True)
class _Point:
    """A plan point ``(x / w, y / w)``, ``w`` positive and the three in lowest terms."""

    x: int
    y: int
    w: int

    def key(self) -> str:
        return f"{self.x} {self.y} {self.w}"


@dataclass(frozen=True, slots=True)
class _Fraction:
    """``n / d`` with ``d`` positive."""

    n: int
    d: int


def _divisor(a: int, b: int) -> int:
    p, q = abs(a), abs(b)
    while q:
        p, q = q, p % q
    return p


def _rational(x: int, y: int, w: int) -> _Point:
    if w == 0:
        raise ValueError("a carve places a point at infinity")
    divisor = _divisor(_divisor(x, y), w)
    sign = -1 if w < 0 else 1
    return _Point(sign * x // divisor, sign * y // divisor, sign * w // divisor)


def _cross(u: Plan, v: Plan) -> int:
    return u[0] * v[1] - u[1] * v[0]


def _dot(u: Plan, v: Plan) -> int:
    return u[0] * v[0] + u[1] * v[1]


def _twice_area(a: Sequence[int], b: Sequence[int], c: Sequence[int]) -> int:
    """Twice the signed area of ``a, b, c``: positive when they turn left."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _side(a: _Point, b: _Point, p: _Point) -> int:
    """The sign of ``cross(b - a, p - a)``: positive when ``p`` is left of ``a -> b``."""
    along = (b.x * a.w - a.x * b.w, b.y * a.w - a.y * b.w)
    toward = (p.x * a.w - a.x * p.w, p.y * a.w - a.y * p.w)
    value = _cross(along, toward)
    return 1 if value > 0 else -1 if value < 0 else 0


def _meetings(a: Plan, b: Plan, c: Plan, d: Plan) -> list[_Point]:
    """The points of segment ``a b`` where segment ``c d`` meets it, all four ends integers."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    q = (c[0] - a[0], c[1] - a[1])
    denominator = _cross(r, s)
    if denominator != 0:
        along_first, along_second = _cross(q, s), _cross(q, r)
        if denominator < 0:
            denominator, along_first, along_second = -denominator, -along_first, -along_second
        if not 0 <= along_first <= denominator or not 0 <= along_second <= denominator:
            return []
        return [
            _rational(
                a[0] * denominator + r[0] * along_first,
                a[1] * denominator + r[1] * along_first,
                denominator,
            )
        ]
    if _cross(r, q) != 0:
        return []
    length = _dot(r, r)
    return [
        _Point(end[0], end[1], 1)
        for end in (c, d)
        if 0 <= _dot((end[0] - a[0], end[1] - a[1]), r) <= length
    ]


def _compare_along(a: Plan, direction: Plan, p: _Point, q: _Point) -> int:
    reach_p = _dot((p.x - a[0] * p.w, p.y - a[1] * p.w), direction) * q.w
    reach_q = _dot((q.x - a[0] * q.w, q.y - a[1] * q.w), direction) * p.w
    return -1 if reach_p < reach_q else 1 if reach_p > reach_q else 0


def _add(a: _Fraction, b: _Fraction) -> _Fraction:
    n, d = a.n * b.d + b.n * a.d, a.d * b.d
    divisor = _divisor(n, d)
    return _Fraction(0, 1) if divisor == 0 else _Fraction(n // divisor, d // divisor)


def _less(a: _Fraction, b: _Fraction) -> bool:
    return a.n * b.d < b.n * a.d


def _circuit_twice_area(circuit: Sequence[_Point]) -> _Fraction:
    total = _Fraction(0, 1)
    for index, here in enumerate(circuit):
        after = circuit[(index + 1) % len(circuit)]
        total = _add(total, _Fraction(here.x * after.y - here.y * after.x, here.w * after.w))
    return total


def _inside_circuit(p: _Point, circuit: Sequence[_Point]) -> bool:
    """Whether ``p`` is inside a circuit it is not on, by crossings of a ray toward +x."""
    inside = False
    for index, a in enumerate(circuit):
        b = circuit[(index + 1) % len(circuit)]
        a_above, b_above = a.y * p.w > p.y * a.w, b.y * p.w > p.y * b.w
        if a_above == b_above:
            continue
        side = _side(a, b, p)
        if (b_above and side > 0) or (a_above and side < 0):
            inside = not inside
    return inside


def _upper_half(d: Plan) -> bool:
    """Whether direction ``d`` lies from angle 0 inclusive to pi exclusive."""
    return d[1] > 0 or (d[1] == 0 and d[0] > 0)


@dataclass(slots=True)
class _Segment:
    start: _Point
    end: _Point
    owners: set[int]


@dataclass(slots=True)
class _HalfEdge:
    start: str
    end: str
    segment: int
    twin: int
    face: int


@dataclass(frozen=True, slots=True)
class _Face:
    edges: tuple[int, ...]
    circuit: tuple[_Point, ...]
    area: _Fraction


def _uncovered(
    piece: Sequence[Plan], coverings: Sequence[Sequence[Plan]], rows: Sequence[int]
) -> list[tuple[tuple[_Point, ...], list[tuple[_Point, ...]]]]:
    """The regions of a counter-clockwise convex ``piece`` no counter-clockwise walk of
    ``coverings`` covers, each its outer circuit and its holes, by the plan arrangement rule."""
    inputs: list[tuple[Plan, Plan, int]] = []
    for owner, ring in enumerate((piece, *coverings)):
        for index, point in enumerate(ring):
            inputs.append((tuple(point), tuple(ring[(index + 1) % len(ring)]), owner))  # type: ignore[arg-type]
    west, east = min(point[0] for point in piece), max(point[0] for point in piece)
    inputs += [((west, row), (east, row), -1) for row in rows]
    spans = [
        ((min(a[0], b[0]), min(a[1], b[1])), (max(a[0], b[0]), max(a[1], b[1])))
        for a, b, _ in inputs
    ]

    def apart(first: int, second: int) -> bool:
        (p_low, p_high), (q_low, q_high) = spans[first], spans[second]
        return (
            p_high[0] < q_low[0]
            or q_high[0] < p_low[0]
            or p_high[1] < q_low[1]
            or q_high[1] < p_low[1]
        )

    # Split every segment where any other meets it, and merge the pieces by their ends.
    merged: dict[str, _Segment] = {}
    for index, (a, b, owner) in enumerate(inputs):
        direction = (b[0] - a[0], b[1] - a[1])
        points = [_Point(a[0], a[1], 1), _Point(b[0], b[1], 1)]
        for second, (c, d, _) in enumerate(inputs):
            if second != index and not apart(index, second):
                points += _meetings(a, b, c, d)
        points.sort(
            key=cmp_to_key(
                lambda p, q, a=a, direction=direction: _compare_along(a, direction, p, q)
            )
        )
        distinct: list[_Point] = []
        for point in points:
            if not distinct or point.key() != distinct[-1].key():
                distinct.append(point)
        for p, q in pairwise(distinct):
            low, high = (p, q) if p.key() < q.key() else (q, p)
            key = f"{low.key()}|{high.key()}"
            segment = merged.setdefault(key, _Segment(low, high, set()))
            segment.owners ^= {owner}
    segments = [segment for segment in merged.values() if segment.owners]

    # Half-edges, ordered by angle round each vertex, traced into faces.
    where: dict[str, _Point] = {}
    edges: list[_HalfEdge] = []
    for index, segment in enumerate(segments):
        start, end = segment.start.key(), segment.end.key()
        where[start], where[end] = segment.start, segment.end
        edges.append(_HalfEdge(start, end, index, len(edges) + 1, -1))
        edges.append(_HalfEdge(end, start, index, len(edges) - 1, -1))
    leaving: dict[str, list[int]] = {}
    for index, edge in enumerate(edges):
        leaving.setdefault(edge.start, []).append(index)

    def direction_of(edge: _HalfEdge) -> Plan:
        u, v = where[edge.start], where[edge.end]
        return (v.x * u.w - u.x * v.w, v.y * u.w - u.y * v.w)

    def around(first: int, second: int) -> int:
        d1, d2 = direction_of(edges[first]), direction_of(edges[second])
        upper1, upper2 = _upper_half(d1), _upper_half(d2)
        if upper1 != upper2:
            return -1 if upper1 else 1
        turn = _cross(d1, d2)
        return -1 if turn > 0 else 1 if turn < 0 else 0

    position: dict[int, int] = {}
    for listed in leaving.values():
        listed.sort(key=cmp_to_key(around))
        for at, edge_index in enumerate(listed):
            position[edge_index] = at

    def next_of(index: int) -> int:
        edge = edges[index]
        listed = leaving[edge.end]
        return listed[(position[edge.twin] - 1) % len(listed)]

    faces: list[_Face] = []
    for start in range(len(edges)):
        if edges[start].face >= 0:
            continue
        traced: list[int] = []
        at = start
        while edges[at].face < 0:
            edges[at].face = len(faces)
            traced.append(at)
            at = next_of(at)
        if at != start:
            raise ValueError("a carve's face did not close on itself")
        circuit = tuple(where[edges[edge].start] for edge in traced)
        faces.append(_Face(tuple(traced), circuit, _circuit_twice_area(circuit)))

    # Groups of connected segments, each with one outside face, labelled outside in.
    group = {key: key for key in where}

    def find(key: str) -> str:
        root = key
        while group[root] != root:
            root = group[root]
        while key != root:
            following = group[key]
            group[key] = root
            key = following
        return root

    for edge in edges:
        group[find(edge.start)] = find(edge.end)
    outsides: dict[str, int] = {}
    for index, face in enumerate(faces):
        if face.area.n >= 0:
            continue
        root = find(edges[face.edges[0]].start)
        if root in outsides:
            raise ValueError("a carve's group of segments has two outsides")
        outsides[root] = index

    def largest_first(first: tuple[str, int], second: tuple[str, int]) -> int:
        area_first, area_second = faces[first[1]].area, faces[second[1]].area
        if _less(area_first, area_second):
            return -1
        if _less(area_second, area_first):
            return 1
        return -1 if first[0] < second[0] else 1

    labels: list[set[int] | None] = [None] * len(faces)
    containing: dict[int, int] = {}
    labelled: list[int] = []
    for _, outside in sorted(outsides.items(), key=cmp_to_key(largest_first)):
        probe = faces[outside].circuit[0]
        best: int | None = None
        for candidate in labelled:
            face = faces[candidate]
            if face.area.n <= 0 or not _inside_circuit(probe, face.circuit):
                continue
            if best is None or _less(face.area, faces[best].area):
                best = candidate
        start_label: set[int] = set()
        if best is not None:
            start_label = set(labels[best] or ())
            containing[outside] = best
        labels[outside] = start_label
        queue = deque([outside])
        while queue:
            face_index = queue.popleft()
            labelled.append(face_index)
            for edge in faces[face_index].edges:
                across = edges[edges[edge].twin].face
                if labels[across] is not None:
                    continue
                labels[across] = (
                    set(labels[face_index] or ()) ^ segments[edges[edge].segment].owners
                )
                queue.append(across)

    # The kept faces, each with the outsides of the groups it holds as holes.
    kept: list[tuple[tuple[_Point, ...], list[tuple[_Point, ...]]]] = []
    for index, face in enumerate(faces):
        label = labels[index] or set()
        if face.area.n <= 0 or 0 not in label or any(owner > 0 for owner in label):
            continue
        holes = [
            faces[outside].circuit for outside, holder in containing.items() if holder == index
        ]
        kept.append((face.circuit, holes))
    return kept


def _in_piece(piece: Sequence[Plan], point: Plan) -> bool:
    """Whether an integer point lies in a closed counter-clockwise convex piece."""
    return all(
        _twice_area(corner, piece[(index + 1) % len(piece)], point) >= 0
        for index, corner in enumerate(piece)
    )


def _hull_keeping_edges(points: Sequence[Plan]) -> list[Plan]:
    """The convex hull of integer points, counter-clockwise from the least, keeping every point that
    lies along an edge of it."""
    ordered = sorted(set(points))
    if len(ordered) < 3:
        return []

    def chain(run: Sequence[Plan]) -> list[Plan]:
        out: list[Plan] = []
        for point in run:
            while len(out) >= 2 and _twice_area(out[-2], out[-1], point) < 0:
                out.pop()
            out.append(point)
        return out

    lower, upper = chain(ordered), chain(ordered[::-1])
    # With every point collinear the two chains are the same line: no hull with area.
    if len(lower) == len(ordered) and len(upper) == len(ordered):
        return []
    return lower[:-1] + upper[:-1]


def _face_hull(face: Sequence[_Point], hold: Sequence[Plan] | None) -> list[Plan]:
    corners: list[Plan] = []
    for vertex in face:
        low_x, low_y = vertex.x // vertex.w, vertex.y // vertex.w
        xs = [low_x] if low_x * vertex.w == vertex.x else [low_x, low_x + 1]
        ys = [low_y] if low_y * vertex.w == vertex.y else [low_y, low_y + 1]
        corners += [(x, y) for x in xs for y in ys if hold is None or _in_piece(hold, (x, y))]
    return _hull_keeping_edges(corners)


def _convex(face: Sequence[_Point]) -> bool:
    return all(
        _side(face[index - 1], here, face[(index + 1) % len(face)]) >= 0
        for index, here in enumerate(face)
    )


def _carved_piece(
    piece: Sequence[Plan], obstructions: Sequence[Sequence[Plan]], hold: Sequence[Plan] | None
) -> list[list[Plan]]:
    rows = sorted({point[1] for walk in obstructions for point in walk if _in_piece(piece, point)})
    walks: list[list[Plan]] = []
    for outer, holes in _uncovered(piece, obstructions, rows):
        if holes:
            raise ValueError("a face cut along its rows still holds a hole")
        if not _convex(outer):
            raise ValueError("a face cut along its rows is not convex")
        hull = _face_hull(outer, hold)
        if len(hull) >= 3:
            walks.append(hull)
    return walks


def _segments_meet(p1: Plan, p2: Plan, q1: Plan, q2: Plan) -> bool:
    def sign(value: int) -> int:
        return 1 if value > 0 else -1 if value < 0 else 0

    def on(point: Plan, a: Plan, b: Plan) -> bool:
        return (
            _twice_area(a, b, point) == 0
            and min(a[0], b[0]) <= point[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= point[1] <= max(a[1], b[1])
        )

    d1, d2 = sign(_twice_area(q1, q2, p1)), sign(_twice_area(q1, q2, p2))
    d3, d4 = sign(_twice_area(p1, p2, q1)), sign(_twice_area(p1, p2, q2))
    if d1 * d2 < 0 and d3 * d4 < 0:
        return True
    return (
        (d1 == 0 and on(p1, q1, q2))
        or (d2 == 0 and on(p2, q1, q2))
        or (d3 == 0 and on(q1, p1, p2))
        or (d4 == 0 and on(q2, p1, p2))
    )


def _require_simple(ring: Sequence[Plan]) -> None:
    """A ring the ring rule takes: three vertices or more, no zero edge, no spike, counter-clockwise
    with a positive area, and no two edges meeting but neighbours'."""
    count = len(ring)
    if count < 3:
        raise ValueError("a ring has fewer than three vertices")
    for index in range(count):
        before, here, after = ring[index - 1], ring[index], ring[(index + 1) % count]
        if here == after:
            raise ValueError(f"a ring's edge {index} has zero length")
        incoming = (here[0] - before[0], here[1] - before[1])
        outgoing = (after[0] - here[0], after[1] - here[1])
        if _twice_area(before, here, after) == 0 and _dot(incoming, outgoing) < 0:
            raise ValueError(f"a ring's vertex {index} is a spike")
    area = sum(
        here[0] * ring[(index + 1) % count][1] - ring[(index + 1) % count][0] * here[1]
        for index, here in enumerate(ring)
    )
    if area <= 0:
        raise ValueError("a ring is not counter-clockwise with a positive area")
    for first in range(count):
        for second in range(first + 2, count):
            if first == 0 and second == count - 1:
                continue
            if _segments_meet(
                ring[first], ring[(first + 1) % count], ring[second], ring[(second + 1) % count]
            ):
                raise ValueError(f"a ring's edges {first} and {second} meet")


def ring_triangles(ring: Sequence[Sequence[int]]) -> list[tuple[int, int, int]]:
    """The ring rule: a simple counter-clockwise ring cut into counter-clockwise triangles by ear
    clipping, the first ear in remaining order each time, as indices into ``ring``. A vertex at a
    candidate ear's corner does not stop it."""
    plan = [(int(point[0]), int(point[1])) for point in ring]
    _require_simple(plan)

    def inside(point: Plan, a: Plan, b: Plan, c: Plan) -> bool:
        return (
            _twice_area(a, b, point) >= 0
            and _twice_area(b, c, point) >= 0
            and _twice_area(c, a, point) >= 0
        )

    remaining = list(range(len(plan)))
    triangles: list[tuple[int, int, int]] = []
    while len(remaining) > 3:
        count = len(remaining)
        for position, b in enumerate(remaining):
            a, c = remaining[position - 1], remaining[(position + 1) % count]
            if _twice_area(plan[a], plan[b], plan[c]) <= 0:
                continue
            corners = {plan[a], plan[b], plan[c]}
            if not any(
                plan[other] not in corners and inside(plan[other], plan[a], plan[b], plan[c])
                for other in remaining
            ):
                triangles.append((a, b, c))
                del remaining[position]
                break
        else:
            raise ValueError("a ring has no ear left to cut")
    a, b, c = remaining
    if _twice_area(plan[a], plan[b], plan[c]) <= 0:
        raise ValueError("a ring leaves a last triangle with no area")
    triangles.append((a, b, c))
    return triangles


def _turns_only_left(ring: Sequence[Plan]) -> bool:
    return all(
        _twice_area(ring[index - 1], here, ring[(index + 1) % len(ring)]) >= 0
        for index, here in enumerate(ring)
    )


def open_regions(ring: Sequence[Plan], standing: Sequence[Sequence[Plan]]) -> list[list[Plan]]:
    """``ring`` (counter-clockwise) less every ring in ``standing`` (each counter-clockwise), as
    convex counter-clockwise walks with integer corners. A ring that turns only left is carved
    whole and holds its hulls to itself; one that turns in is cut into triangles first, each carved
    and held to itself; with nothing standing on it, the ring is its own triangles."""
    obstructions: list[list[Plan]] = []
    for other in standing:
        plan = [(int(point[0]), int(point[1])) for point in other]
        obstructions += [[plan[a], plan[b], plan[c]] for a, b, c in ring_triangles(plan)]
    if obstructions and _turns_only_left(ring):
        return _carved_piece(ring, obstructions, ring)
    pieces = [[ring[a], ring[b], ring[c]] for a, b, c in ring_triangles(ring)]
    if not obstructions:
        return pieces
    return [walk for piece in pieces for walk in _carved_piece(piece, obstructions, piece)]
