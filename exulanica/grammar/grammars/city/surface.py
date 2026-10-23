"""The city's street surface at a point: the height a person stands at, from the town's records.

The tessellator draws a street's surfaces from its records (:mod:`~exulanica.grammar.grammars.city.
streets` states the geometry, :mod:`~exulanica.grammar.grammars.city.corners` who owns a corner),
and the page stands a person on the highest of them over a plan point. :func:`city_surface_z_at`
answers the same height from the same records, in integer millimetres, without drawing anything,
so a thing placed on a street rests on the surface people walk on. Every point is placed by the
records' own fields and the corner rule's measure; nothing is measured from a drawing.

* **A kerb top** is the kerb line's height at the point plus ``kerb_height_mm``, from the kerb line
  out ``kerb_width_mm``. The kerb line itself belongs to the kerb top: where the kerb face stands,
  the higher surface is the one a person is on.
* **A footway** piece is the tessellator's ring for it: from the kerb top's back edge, at the kerb
  top's height, out to the frontage line, risen by ``footway_width_mm`` of crossfall. Where the
  piece meets a mitred corner (a width reaches the corner's radius) the ring gives way on the
  mitre, through the corner's centre and frontage corner at the corner's own level. Where that
  piece's kerb line climbs or falls, the strip stands on its own heights up to a ramp into the
  mitre, as long as the stretch the mitre takes, and the ramp is its own ring, as the tessellator
  draws it. A ring is cut into triangles by the ring rule (ear clipping, in the order the
  tessellator cuts), and a point's height is its triangle's.
* **A carriageway and its gutters** lie on the camber plane from the crown line down to each kerb
  line, between the strip's two ends (:mod:`~exulanica.grammar.grammars.city.streets`, the
  segment's step 1). A crossing's band is drawn on that carriageway and states no surface of its
  own, and its kerb upstand draws nothing, so a crossing answers the carriageway's height.
* **A corner's kerb top** runs along the corner's arc, the fillet arc rule's points from ``P`` to
  ``Q``, as many as keep each chord within the navigation contract's resolution of the circle, out
  to the back arc ``kerb_width_mm`` nearer the centre, at the arc's heights plus the kerb's.
* **A corner's footway wedge** is the slice from that back arc in to the arc's centre, less the
  blocks the curb names and, unless the corner mitres, the quadrilateral its two frontage lines cut
  off toward the centre, carved as the tessellator carves it
  (:mod:`~exulanica.grammar.grammars.city.carve`) and cut by the ring rule. A point of the carve on
  the back arc stands at the kerb top's height there, the centre at the crossfall of its own
  distance above the apex (the kerb top's height at the arc's mean end height), and every other
  point at a footway's rise above the apex.
* **A junction's fill** is the junction rule's ring: each leg's mouth (the segment rule's five
  points across its strip's end at the node), back along its kerb line, and round each corner's
  arc to the next leg, cut by the ring rule.

Where surfaces overlap, the highest is the answer, as on the page. A corner's wedge the carve or
the ring rule refuses, and a curb's straight footway the ring rule refuses, is not stated by this
version: it answers ``None`` there, as it does where the records state no street surface at all (a
lot, a building, open land). The caller keeps its own ground for ``None``.

Heights are exact ratios of integers, rounded half away from zero once at the end. A reading
indexes its pieces (each straight kerb top, footway triangle, carriageway strip, corner kerb-top
triangle, corner wedge triangle and junction fill triangle) by square plan cells once, and a read
asks only the pieces whose bounds reach its point's cell, in the order the rules above list them,
so where two answer the same height the earlier still answers.
``tests/fixtures/city-surface-table.json`` holds every answer to the page's own walk surface on
the conformance tile, a generated town on level ground and a generated town on land.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from exulanica.grammar.geometry import integer_sqrt
from exulanica.grammar.grammars.city import CITY_GRAMMAR
from exulanica.grammar.grammars.city.carve import open_regions, ring_triangles
from exulanica.grammar.grammars.city.corners import CORNER_LENGTH_SCALE, footway_rise_mm
from exulanica.grammar.grammars.city.corners import along as _along
from exulanica.grammar.grammars.city.roads import JunctionRecord
from exulanica.grammar.grammars.city.streets import (
    BlockRecord,
    CurbEdgeRecord,
    StreetNodeRecord,
    StreetSegmentRecord,
)

__all__ = [
    "CARRIAGEWAY",
    "FOOTWAY",
    "KERB_TOP",
    "city_surface_reading",
    "city_surface_z_at",
]

Plan = tuple[int, int]
Space = tuple[int, int, int]
Triangle = tuple[Space, Space, Space]

#: Lengths are taken in millionths of a millimetre, as the corner rule takes them.
_SCALE: Final = CORNER_LENGTH_SCALE

#: The side of the square plan cells a reading indexes its pieces by, in millimetres: a read asks
#: only the pieces whose bounds reach its point's cell.
_CELL_MM: Final = 4_000
#: How far a piece's indexed bounds reach past its own points, in millimetres: more than the
#: rounding of any point a piece answers for, so the index never leaves out a piece that answers.
_BOUNDS_MARGIN_MM: Final = 100

#: The surfaces a height is answered from.
KERB_TOP: Final = "kerb_top"
FOOTWAY: Final = "footway"
CARRIAGEWAY: Final = "carriageway"


@dataclass(frozen=True, slots=True)
class _Ratio:
    """An exact height between integer points: ``over / under``, ``under`` positive."""

    over: int
    under: int = 1

    @staticmethod
    def of(over: int, under: int) -> _Ratio:
        return _Ratio(-over, -under) if under < 0 else _Ratio(over, under)

    def __add__(self, other: _Ratio | int) -> _Ratio:
        other = _Ratio(other) if isinstance(other, int) else other
        return _Ratio(self.over * other.under + other.over * self.under, self.under * other.under)

    def __sub__(self, other: _Ratio | int) -> _Ratio:
        other = _Ratio(other) if isinstance(other, int) else other
        return self + _Ratio(-other.over, other.under)

    def times(self, over: int, under: int = 1) -> _Ratio:
        return _Ratio.of(self.over * over, self.under * under)

    def key(self, other: _Ratio) -> int:
        """Positive when this is higher than ``other``, negative when lower, zero when equal."""
        return self.over * other.under - other.over * self.under

    def floor(self) -> int:
        return self.over // self.under

    def rounded(self) -> int:
        """To the nearest integer, half away from zero."""
        whole, part = divmod(abs(self.over), self.under)
        if 2 * part >= self.under:
            whole += 1
        return whole if self.over >= 0 else -whole


def _sub(a: Sequence[int], b: Sequence[int]) -> Plan:
    return (a[0] - b[0], a[1] - b[1])


def _dot(a: Plan, b: Plan) -> int:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: Plan, b: Plan) -> int:
    return a[0] * b[1] - a[1] * b[0]


def _turn(origin: Sequence[int], a: Sequence[int], b: Sequence[int]) -> int:
    """Twice the signed area of ``origin, a, b``: positive when they turn left."""
    return _cross(_sub(a, origin), _sub(b, origin))


def _moved(point: Sequence[int], by: Plan) -> Plan:
    return (point[0] + by[0], point[1] + by[1])


def _left(vector: Plan) -> Plan:
    return (-vector[1], vector[0])


@dataclass(frozen=True, slots=True)
class _Line:
    """A record's line, straight in plan, read along ``direction`` as every street rule reads it."""

    points: tuple[Space, ...]
    direction: Plan

    def position(self, point: Sequence[int]) -> int:
        """``point``'s position along the direction from the line's first point, unscaled."""
        return _dot(_sub(point, self.points[0]), self.direction)

    def height(self, point: Sequence[int]) -> _Ratio:
        """The height at ``point``'s position: on the piece it falls in (the end piece past either
        end), linear between that piece's two points."""
        at = 0
        for index in range(1, len(self.points) - 1):
            if _dot(_sub(point, self.points[index]), self.direction) >= 0:
                at = index
        near, far = self.points[at], self.points[at + 1]
        end = _dot(_sub(far, near), self.direction)
        return (
            _Ratio.of((far[2] - near[2]) * _dot(_sub(point, near), self.direction), end) + near[2]
        )


def _line(points: Sequence[Sequence[int]], direction: Plan) -> _Line | None:
    """A record's line read along ``direction``, or None where it bends in plan or runs any other
    way: the tessellator draws such a street as its ``bent_street`` waiting state, not at all."""
    line = tuple((int(x), int(y), int(z)) for x, y, z in points)
    if len(line) < 2:
        return None
    for a, b in pairwise(line):
        piece = _sub(b, a)
        if _cross(direction, piece) != 0 or _dot(direction, piece) <= 0:
            return None
    return _Line(line, direction)


def _ears(ring: Sequence[Space]) -> list[Triangle]:
    """The ring rule: a simple counter-clockwise ring cut into triangles by ear clipping, the first
    ear in remaining order each time, as the tessellator cuts it."""

    def inside(point: Space, a: Space, b: Space, c: Space) -> bool:
        return _turn(a, b, point) >= 0 and _turn(b, c, point) >= 0 and _turn(c, a, point) >= 0

    remaining = list(ring)
    triangles: list[Triangle] = []
    while len(remaining) > 3:
        count = len(remaining)
        for position, b in enumerate(remaining):
            a, c = remaining[position - 1], remaining[(position + 1) % count]
            if _turn(a, b, c) <= 0:
                continue
            corners = {a[:2], b[:2], c[:2]}
            if not any(other[:2] not in corners and inside(other, a, b, c) for other in remaining):
                triangles.append((a, b, c))
                del remaining[position]
                break
        else:
            raise ValueError("a footway ring has no ear left to cut")
    triangles.append((remaining[0], remaining[1], remaining[2]))
    return triangles


def _on_triangle(point: Plan, triangle: Triangle) -> _Ratio | None:
    """The height at ``point`` on ``triangle``'s plane, or None outside it (its edges inside)."""
    a, b, c = triangle
    area = _turn(a, b, c)
    if area <= 0:
        return None
    wa, wb, wc = _turn(point, b, c), _turn(point, c, a), _turn(point, a, b)
    if wa < 0 or wb < 0 or wc < 0:
        return None
    return _Ratio.of(wa * a[2] + wb * b[2] + wc * c[2], area)


@dataclass(frozen=True, slots=True)
class _Mitre:
    """Where two straight footways give way to each other at a mitred corner."""

    centre: Space
    frontage: Space


def _walk(curb: CurbEdgeRecord) -> tuple[Space, ...]:
    """The kerb line in the order a counter-clockwise walk round the curb's face takes it."""
    line = tuple((int(x), int(y), int(z)) for x, y, z in curb.kerb_line_mm)
    return line if curb.side == "left" else line[::-1]


def _mitre(curb: CurbEdgeRecord, follower: CurbEdgeRecord) -> _Mitre | None:
    """The mitre of the corner ``curb`` turns into ``follower`` (the tessellator's
    ``cornerMitre``), or None unless it turns left with a radius one of their widths reaches."""
    radius = curb.corner_radius_mm
    if radius == 0:
        return None
    walk, following = _walk(curb), _walk(follower)
    p, q = walk[-1], following[0]
    into, out = _sub(p, walk[-2]), _sub(following[1], q)
    turning = _cross(into, out)
    if turning <= 0:
        return None
    reach = curb.kerb_width_mm + curb.footway_width_mm
    other = follower.kerb_width_mm + follower.footway_width_mm
    if reach < radius and other < radius:
        return None
    apex = (p[2] + q[2]) // 2 + curb.kerb_height_mm
    # The arc's centre found from each tangent point, the two floored to their middle.
    from_p = _moved(p, _along(_left(into), radius))
    from_q = _moved(q, _along(_left(out), radius))
    centre = ((from_p[0] + from_q[0]) // 2, (from_p[1] + from_q[1]) // 2)
    frontage = _frontage(p, into, q, out, reach, other)
    crossfall = curb.footway_crossfall_millionths
    return _Mitre(
        (*centre, apex + (radius - curb.kerb_width_mm) * crossfall // _SCALE),
        (*frontage, apex + footway_rise_mm(curb)),
    )


def _frontage(p: Space, into: Plan, q: Space, out: Plan, reach: int, other: int) -> Plan:
    """The frontage corner: where the frontage line ``reach`` to the left of the piece arriving at
    ``p`` meets the one ``other`` to the left of the piece leaving ``q``, each axis floored."""
    first = _moved(p, _along(_left(into), reach))
    second = _moved(q, _along(_left(out), other))
    numerator = _cross(_sub(second, first), out)
    turning = _cross(into, out)
    return (
        first[0] + into[0] * numerator // turning,
        first[1] + into[1] * numerator // turning,
    )


#: How far, in millimetres, a point the corner rule places may lie inside its circle: the diagonal
#: of one millimetre, which the fillet arc rule's chord test allows for (``filletSegmentsWithin``).
_CORNER_ROUNDING_MM: Final = 2


def _fillet_centre(p: Space, into: Plan, q: Space, out: Plan, radius: int) -> Plan:
    """The fillet arc rule's centre: the floored middle of the two centres the corner rule finds
    from each tangent point, the radius along its piece's normal toward the turn."""
    turn = 1 if _cross(into, out) > 0 else -1
    from_p = _moved(p, _along((-turn * into[1], turn * into[0]), radius))
    from_q = _moved(q, _along((-turn * out[1], turn * out[0]), radius))
    return ((from_p[0] + from_q[0]) // 2, (from_p[1] + from_q[1]) // 2)


def _fillet_arc(
    p: Space, into: Plan, q: Space, out: Plan, radius: int, segments: int
) -> tuple[Plan, list[Space]]:
    """The fillet arc rule's points from ``p`` to ``q``: each halves the gap between two placed
    points, the radius from the centre along the sum of their vectors, at their floored mean
    height; and the centre."""
    centre = _fillet_centre(p, into, q, out, radius)
    points: list[Space | None] = [None] * (segments + 1)
    points[0], points[segments] = p, q
    gap = segments
    while gap > 1:
        for start in range(0, segments, gap):
            first, last = points[start], points[start + gap]
            assert first is not None and last is not None
            toward = (
                first[0] - centre[0] + last[0] - centre[0],
                first[1] - centre[1] + last[1] - centre[1],
            )
            x, y = _moved(centre, _along(toward, radius))
            points[start + gap // 2] = (x, y, (first[2] + last[2]) // 2)
        gap //= 2
    return centre, [point for point in points if point is not None]


def _fillet_segments(
    p: Space, into: Plan, q: Space, out: Plan, radius: int, sagitta_mm: int
) -> int:
    """The least power of two, up to the least at or above the radius, whose every chord keeps
    within ``sagitta_mm`` of the circle and the corner rule's own rounding."""
    centre = _fillet_centre(p, into, q, out, radius)
    reach = radius - sagitta_mm - _CORNER_ROUNDING_MM
    if reach <= 0:
        return 1
    least = 4 * reach * reach
    bound = 1
    while bound < radius:
        bound *= 2
    segments = 1
    while segments <= bound:
        _centre, points = _fillet_arc(p, into, q, out, radius, segments)
        sums = (
            (a[0] - centre[0] + b[0] - centre[0], a[1] - centre[1] + b[1] - centre[1])
            for a, b in pairwise(points)
        )
        if all(_dot(one, one) >= least for one in sums):
            return segments
        segments *= 2
    raise ValueError("a corner arc needs more segments than its radius allows")


def _corner_arc(
    curb: CurbEdgeRecord, follower: CurbEdgeRecord, sagitta_mm: int
) -> tuple[Plan, list[Space]] | None:
    """The arc of the corner ``curb`` turns into ``follower``, from its walk's end ``P`` to the
    follower's start ``Q``, or None where it turns right (a concave corner) or has no radius."""
    radius = curb.corner_radius_mm
    if radius == 0:
        return None
    walk, following = _walk(curb), _walk(follower)
    p, q = walk[-1], following[0]
    into, out = _sub(p, walk[-2]), _sub(following[1], q)
    if _cross(into, out) <= 0:
        return None
    segments = _fillet_segments(p, into, q, out, radius, sagitta_mm)
    return _fillet_arc(p, into, q, out, radius, segments)


def _kerb_top_arc(curb: CurbEdgeRecord, arc: tuple[Plan, list[Space]]) -> tuple[Triangle, ...]:
    """A corner's kerb top: for each chord of the arc, the quad from it to the back arc, the radius
    less the kerb's width from the centre, both at the arc's heights plus the kerb's."""
    centre, points = arc
    height, inner = curb.kerb_height_mm, curb.corner_radius_mm - curb.kerb_width_mm
    back = [
        (*_moved(centre, _along(_sub(point, centre), inner)), point[2] + height) for point in points
    ]
    triangles: list[Triangle] = []
    for (a, b), (back_a, back_b) in zip(pairwise(points), pairwise(back), strict=True):
        top_a, top_b = (a[0], a[1], a[2] + height), (b[0], b[1], b[2] + height)
        triangles += [(top_a, top_b, back_b), (top_a, back_b, back_a)]
    return tuple(triangles)


def _corner_wedge(
    curb: CurbEdgeRecord,
    follower: CurbEdgeRecord,
    arc: tuple[Plan, list[Space]],
    blocks: Sequence[Sequence[Sequence[int]]],
) -> tuple[Triangle, ...]:
    """A corner's footway wedge: the slice from its back arc in to the arc's centre, less
    ``blocks`` (the rings of the blocks the curb names) and, unless the corner mitres, the
    quadrilateral from its frontage lines to the centre, carved and cut as the tessellator does."""
    centre, points = arc
    walk, following = _walk(curb), _walk(follower)
    p, q = walk[-1], following[0]
    into, out = _sub(p, walk[-2]), _sub(following[1], q)
    height, inner = curb.kerb_height_mm, curb.corner_radius_mm - curb.kerb_width_mm
    back = [
        (*_moved(centre, _along(_sub(point, centre), inner)), point[2] + height) for point in points
    ]
    on_back = {(x, y): z for x, y, z in back}
    apex = (p[2] + q[2]) // 2 + height
    at_centre = apex + inner * curb.footway_crossfall_millionths // _SCALE
    raised = apex + footway_rise_mm(curb)
    taken = [[(int(x), int(y)) for x, y in block] for block in blocks]
    if _mitre(curb, follower) is None:
        reach = curb.kerb_width_mm + curb.footway_width_mm
        other = follower.kerb_width_mm + follower.footway_width_mm
        taken.append(
            [
                _moved(p, _along(_left(into), reach)),
                _frontage(p, into, q, out, reach, other),
                _moved(q, _along(_left(out), other)),
                centre,
            ]
        )
    triangles: list[Triangle] = []
    for carved in open_regions([*((x, y) for x, y, _ in back), centre], taken):
        ring = [
            (x, y, on_back.get((x, y), at_centre if (x, y) == centre else raised))
            for x, y in carved
        ]
        triangles += [(ring[a], ring[b], ring[c]) for a, b, c in ring_triangles(ring)]
    return tuple(triangles)


def _height_on(line: Sequence[Space], direction: Plan, point: Sequence[int]) -> int:
    """A line's height at ``point`` as the segment rule places a point on it, floored."""
    at = 0
    for index in range(1, len(line) - 1):
        if _dot(_sub(point, line[index]), direction) >= 0:
            at = index
    near, far = line[at], line[at + 1]
    end = _dot(_sub(far, near), direction)
    return near[2] + (far[2] - near[2]) * _dot(_sub(point, near), direction) // end


def _strip_ends(
    segment: StreetSegmentRecord, left: CurbEdgeRecord, right: CurbEdgeRecord
) -> tuple[tuple[Space, ...], tuple[Space, ...]] | None:
    """The segment rule's five points across each end of a strip, left kerb point to right, or None
    where the strip waits (a bent line, or kerbs that leave no strip)."""
    direction = _sub(segment.centreline_mm[-1], segment.centreline_mm[0])
    lines = [
        _line(points, direction)
        for points in (segment.centreline_mm, left.kerb_line_mm, right.kerb_line_mm)
    ]
    if any(line is None for line in lines):
        return None
    centre, left_line, right_line = (line.points for line in lines if line is not None)
    origin, width = centre[0], segment.carriageway_width_mm
    to_left, to_right = _left(direction), (direction[1], -direction[0])

    def position(point: Sequence[int]) -> int:
        return _dot(_sub(point, origin), direction)

    def ends(left_point: Space, right_point: Space, later_wins: bool) -> tuple[Space, Space]:
        left_first = position(left_point) > position(right_point)
        if left_first if later_wins else not left_first:
            across = _moved(left_point, _along(to_right, width))
            return left_point, (*across, _height_on(right_line, direction, across))
        across = _moved(right_point, _along(to_left, width))
        return (*across, _height_on(left_line, direction, across)), right_point

    def across(left_point: Space, right_point: Space) -> tuple[Space, ...]:
        middle = ((left_point[0] + right_point[0]) // 2, (left_point[1] + right_point[1]) // 2)
        crown = (*middle, _height_on(centre, direction, middle))

        def gutter(kerb: Space, toward: Plan, width_mm: int) -> Space:
            at = _moved(kerb, _along(toward, width_mm))
            return (*at, kerb[2] + (crown[2] - kerb[2]) * 2 * width_mm // width)

        return (
            left_point,
            gutter(left_point, to_right, left.gutter_width_mm),
            crown,
            gutter(right_point, to_left, right.gutter_width_mm),
            right_point,
        )

    left0, right0 = ends(left_line[0], right_line[0], True)
    left1, right1 = ends(left_line[-1], right_line[-1], False)
    low, high = position(left0), position(left1)
    if low >= high:
        return None
    for line in (centre, left_line, right_line):
        if any(low < position(point) < high for point in line[1:-1]):
            return None
    return across(left0, right0), across(left1, right1)


def _junction_fill(
    junction: JunctionRecord,
    nodes: dict[str, StreetNodeRecord],
    segments: dict[str, StreetSegmentRecord],
    sides: dict[tuple[str, str], CurbEdgeRecord],
    sagitta_mm: int,
) -> tuple[Triangle, ...]:
    """The junction rule's carriageway fill: for each leg, its mouth's five points from
    outward-right to outward-left, back along its outward-left kerb line to ``Q``, then round the
    corner the next leg's outward-right curb turns, from ``Q`` back to ``P``; cut by the ring rule.
    None of it where a leg, curb or node is not among the records."""
    node = nodes.get(junction.node_identity)
    if node is None:
        return ()
    legs: list[tuple[tuple[Space, ...], CurbEdgeRecord, CurbEdgeRecord]] = []
    for identity in junction.segment_identities:
        segment = segments.get(identity)
        left, right = sides.get((identity, "left")), sides.get((identity, "right"))
        if segment is None or left is None or right is None:
            return ()
        ends = _strip_ends(segment, left, right)
        if ends is None:
            return ()
        first, last = segment.centreline_mm[0], segment.centreline_mm[-1]
        at_start = (first[0], first[1]) == (node.x_mm, node.y_mm)
        if at_start == ((last[0], last[1]) == (node.x_mm, node.y_mm)):
            return ()
        if at_start:
            legs.append((tuple(reversed(ends[0])), left, right))
        else:
            legs.append((ends[1], right, left))
    ring: list[Space] = []

    def push(point: Space) -> None:
        if not ring or ring[-1] != point:
            ring.append(point)

    for index, (mouth, outward_left, _right) in enumerate(legs):
        _mouth, _left_curb, next_right = legs[(index + 1) % len(legs)]
        for point in mouth:
            push(point)
        walk_a, walk_b = _walk(outward_left), _walk(next_right)
        q, p = walk_a[0], walk_b[-1]
        push(q)
        if (
            not next_right.next_curb_identity
            or next_right.next_curb_identity[0] != outward_left.identity
        ):
            return ()
        radius = next_right.corner_radius_mm
        if radius == 0:
            if p != q:
                return ()
            continue
        into, out = _sub(p, walk_b[-2]), _sub(walk_a[1], q)
        segments_count = _fillet_segments(p, into, q, out, radius, sagitta_mm)
        _centre, arc = _fillet_arc(p, into, q, out, radius, segments_count)
        for step in range(segments_count - 1, 0, -1):
            push(arc[step])
        push(p)
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    return tuple(_ears(ring))


def _ramp_start(near: Space, far: Space, frontage: Space) -> Plan | None:
    """Where a footway whose kerb line climbs or falls begins its ramp into the mitred corner at
    ``far``: the point of the kerb line from ``near`` to ``far`` (a piece along x or along y, walked
    toward ``far``) as far before the mitre's frontage corner as ``far`` lies beyond it, so the ramp
    is as long as the stretch of strip the mitre gives the corner; None where the piece runs along
    neither axis or that point does not lie strictly between ``near`` and the frontage corner."""
    axis = 0 if near[1] == far[1] else 1 if near[0] == far[0] else None
    if axis is None:
        return None
    start = 2 * frontage[axis] - far[axis]
    inside = (
        near[axis] < start < frontage[axis]
        if near[axis] < frontage[axis]
        else frontage[axis] < start < near[axis]
    )
    if not inside:
        return None
    return (start, near[1]) if axis == 0 else (near[0], start)


def _before(near: Space, far: Space, first: Plan, second: Plan) -> bool:
    """Whether, walking a piece along x or along y from ``near`` to ``far``, ``first`` comes
    before ``second``."""
    axis = 0 if near[1] == far[1] else 1
    return first[axis] < second[axis] if near[axis] < far[axis] else second[axis] < first[axis]


def _footway(
    curb: CurbEdgeRecord, line: _Line, outward: Plan, turned: _Mitre | None, met: _Mitre | None
) -> tuple[Triangle, ...]:
    """A curb's footway rings, piece by piece along its kerb line, cut into triangles. Where a
    sloping kerb line meets a mitred corner, the strip stands on its own heights up to a ramp into
    that corner: each ramp is its own ring, and so is the strip between them, as the tessellator
    draws it; a level kerb line, or a strip whose two ramps would cross, keeps its one ring."""
    points = line.points
    sloping = any(point[2] != points[0][2] for point in points)
    height, kerb_width = curb.kerb_height_mm, curb.kerb_width_mm
    reach, rise = kerb_width + curb.footway_width_mm, footway_rise_mm(curb)

    def out(point: Space, distance: int, up: int) -> Space:
        return (*_moved(point, _along(outward, distance)), point[2] + up)

    def across(on_kerb: Plan) -> tuple[Space, Space]:
        # The kerb top's back and the footway's far edge, across the strip from a kerb line point.
        kerb = (on_kerb[0], on_kerb[1], _height_on(points, line.direction, on_kerb))
        return out(kerb, kerb_width, height), out(kerb, reach, height + rise)

    # A left curb is walked first point to last, a right one last to first: the walk's end piece
    # meets the corner this curb turns, its start piece the corner that turns into it.
    on_left = curb.side == "left"
    start, end = (0, 1) if on_left else (1, 0)
    pieces = len(points) - 1
    triangles: list[Triangle] = []

    def ring_of(ring: list[Space]) -> None:
        triangles.extend(_ears([point for at, point in enumerate(ring) if point != ring[at - 1]]))

    for index in range(pieces):
        ends = (points[index], points[index + 1])
        backs = [out(point, kerb_width, height) for point in ends]
        fronts = [out(point, reach, height + rise) for point in ends]
        turned_here = turned if index == (pieces - 1 if on_left else 0) else None
        met_here = met if index == (0 if on_left else pieces - 1) else None
        walk_from, walk_to = ends[start], ends[end]
        end_ramp = (
            _ramp_start(walk_from, walk_to, turned_here.frontage)
            if sloping and turned_here is not None
            else None
        )
        start_ramp = (
            _ramp_start(walk_to, walk_from, met_here.frontage)
            if sloping and met_here is not None
            else None
        )
        if (
            end_ramp is not None
            and start_ramp is not None
            and not _before(walk_from, walk_to, start_ramp, end_ramp)
        ):
            end_ramp = start_ramp = None
        start_edge = None if start_ramp is None else across(start_ramp)
        end_edge = None if end_ramp is None else across(end_ramp)
        if start_edge is not None and met_here is not None:
            ring_of([backs[start], *start_edge, met_here.frontage, met_here.centre])
        if end_edge is not None and turned_here is not None:
            ring_of(
                [end_edge[0], backs[end], turned_here.centre, turned_here.frontage, end_edge[1]]
            )
        ring = [
            backs[start] if start_edge is None else start_edge[0],
            backs[end] if end_edge is None else end_edge[0],
        ]
        if end_edge is not None:
            ring.append(end_edge[1])
        elif turned_here is None:
            ring.append(fronts[end])
        else:
            ring += [turned_here.centre, turned_here.frontage]
        if start_edge is not None:
            ring.append(start_edge[1])
        elif met_here is None:
            ring.append(fronts[start])
        else:
            ring += [met_here.frontage, met_here.centre]
        ring_of(ring)
    return tuple(triangles)


@dataclass(frozen=True, slots=True)
class _Strip:
    """A segment's carriageway and gutters, between its two kerb lines, crown line in the middle:
    from each kerb line across its gutter to the gutter line, then on to the crown, each a plane."""

    centre: _Line
    left: _Line
    right: _Line
    low: int
    high: int
    width: int
    gutters: tuple[int, int]

    def height(self, point: Plan) -> _Ratio | None:
        if not self.low <= self.centre.position(point) <= self.high:
            return None
        direction, origin = self.centre.direction, self.centre.points[0]
        across = _cross(direction, _sub(point, origin))
        left_kerb, right_kerb = self.left.points[0], self.right.points[0]
        left = _cross(direction, _sub(left_kerb, origin))
        right = _cross(direction, _sub(right_kerb, origin))
        if not right <= across <= left:
            return None
        # The crown is the floored middle of the two kerb points across the strip, and each
        # gutter line its kerb's point moved its gutter's width toward the crown, its height
        # floored on the camber plane, as the segment rule places them.
        across_left = _moved(left_kerb, _along((direction[1], -direction[0]), self.width))
        middle = ((left_kerb[0] + across_left[0]) // 2, (left_kerb[1] + across_left[1]) // 2)
        crown = _cross(direction, _sub(middle, origin))
        on_left = across >= crown
        kerb, line, gutter = (
            (left, self.left, self.gutters[0]) if on_left else (right, self.right, self.gutters[1])
        )
        toward = (direction[1], -direction[0]) if on_left else _left(direction)
        kerb_point = left_kerb if on_left else right_kerb
        gutter_across = _cross(direction, _sub(_moved(kerb_point, _along(toward, gutter)), origin))
        z_kerb, z_crown = line.height(point), self.centre.height(point)
        z_gutter = z_kerb + (z_crown - z_kerb).times(2 * gutter, self.width).floor()
        if gutter and (across - kerb) * (gutter_across - across) >= 0:
            return z_kerb + (z_gutter - z_kerb).times(across - kerb, gutter_across - kerb)
        if crown == gutter_across:
            return z_crown
        return z_gutter + (z_crown - z_gutter).times(across - gutter_across, crown - gutter_across)


@dataclass(frozen=True, slots=True)
class _Curb:
    """A curb's straight part: its kerb top out from its kerb line, and its footway's triangles."""

    line: _Line
    outward: Plan
    kerb_height: int
    kerb_width: int
    footway: tuple[Triangle, ...]

    def kerb_top_bounds(self) -> tuple[Plan, ...]:
        """The points the kerb top spans: its kerb line and that line moved out to the back."""
        back = _along(self.outward, self.kerb_width)
        return tuple(
            point for each in self.line.points for point in ((each[0], each[1]), _moved(each, back))
        )

    def kerb_top(self, point: Plan) -> _Ratio | None:
        position = self.line.position(point)
        if not 0 <= position <= self.line.position(self.line.points[-1]):
            return None
        length = integer_sqrt(_dot(self.outward, self.outward) * _SCALE * _SCALE)
        out = _dot(_sub(point, self.line.points[0]), self.outward) * _SCALE
        if not 0 <= out <= self.kerb_width * length:
            return None
        return self.line.height(point) + self.kerb_height


def city_surface_z_at(records: Iterable[object]) -> Callable[[Plan], int | None]:
    """The town's street surface: a point of the ``city_local`` plan (x east, y north, integer
    millimetres) to the height a person stands at there, integer millimetres of ``city_local`` z,
    or None where this version states no street surface. Built once over ``records``: any city
    records, of which the street segments and curb edges are read."""
    reading = city_surface_reading(records)

    def surface(point: Plan) -> int | None:
        answer = reading(point)
        return None if answer is None else answer[0]

    return surface


def city_surface_reading(records: Iterable[object]) -> Callable[[Plan], tuple[int, str] | None]:
    """:func:`city_surface_z_at` with the surface that answered: :data:`KERB_TOP`, :data:`FOOTWAY`
    or :data:`CARRIAGEWAY`."""
    segments: dict[str, StreetSegmentRecord] = {}
    curbs: dict[str, CurbEdgeRecord] = {}
    nodes: dict[str, StreetNodeRecord] = {}
    junctions: list[JunctionRecord] = []
    blocks: dict[str, tuple[tuple[int, int], ...]] = {}
    for record in records:
        if isinstance(record, StreetSegmentRecord):
            segments[record.identity] = record
        elif isinstance(record, CurbEdgeRecord):
            curbs[record.identity] = record
        elif isinstance(record, StreetNodeRecord):
            nodes[record.identity] = record
        elif isinstance(record, JunctionRecord):
            junctions.append(record)
        elif isinstance(record, BlockRecord):
            blocks[record.identity] = record.boundary_mm
    # The walk surface's resolution, as the city grammar's navigation contract states it: how far
    # a chord of a corner's arc may stand from its circle.
    sagitta = CITY_GRAMMAR.projection("nav_envelope").resolution_mm
    sides = {(curb.segment_identity, curb.side): curb for curb in curbs.values()}
    # The curb whose corner ends at a curb's start: the first, in record order, naming it next.
    owners: dict[str, CurbEdgeRecord] = {}
    for curb in curbs.values():
        for identity in curb.next_curb_identity:
            owners.setdefault(identity, curb)

    strips: list[_Strip] = []
    straight: list[_Curb] = []
    for segment in segments.values():
        direction = _sub(segment.centreline_mm[-1], segment.centreline_mm[0])
        centre = _line(segment.centreline_mm, direction)
        if centre is None:
            continue
        lines: dict[str, _Line] = {}
        for side, outward in (("left", _left(direction)), ("right", (direction[1], -direction[0]))):
            curb = sides.get((segment.identity, side))
            line = None if curb is None else _line(curb.kerb_line_mm, direction)
            if curb is None or line is None:
                continue
            lines[side] = line
            followers = [
                curbs[identity] for identity in curb.next_curb_identity if identity in curbs
            ]
            turned = _mitre(curb, followers[0]) if followers else None
            owner = owners.get(curb.identity)
            met = None if owner is None else _mitre(owner, curb)
            # A footway the ring rule refuses is one the tessellator refuses too (that tile alone),
            # and only that curb's footway goes unstated: its kerb top and the rest of the town
            # still answer.
            try:
                footway = _footway(curb, line, outward, turned, met)
            except ValueError:
                footway = ()
            straight.append(_Curb(line, outward, curb.kerb_height_mm, curb.kerb_width_mm, footway))
        if len(lines) == 2:
            left, right = lines["left"], lines["right"]
            low = max(centre.position(left.points[0]), centre.position(right.points[0]))
            high = min(centre.position(left.points[-1]), centre.position(right.points[-1]))
            if low < high:
                gutters = (
                    sides[(segment.identity, "left")].gutter_width_mm,
                    sides[(segment.identity, "right")].gutter_width_mm,
                )
                strips.append(
                    _Strip(centre, left, right, low, high, segment.carriageway_width_mm, gutters)
                )
    tops: list[Triangle] = []
    wedges: list[Triangle] = []
    for curb in curbs.values():
        followers = [curbs[identity] for identity in curb.next_curb_identity if identity in curbs]
        arc = None if not followers else _corner_arc(curb, followers[0], sagitta)
        if arc is not None:
            tops += _kerb_top_arc(curb, arc)
            named = [blocks[identity] for identity in curb.block_identity if identity in blocks]
            # A corner the carve or the ring rule refuses is one the tessellator refuses too, and
            # only that corner's wedge goes unstated: the rest of the town still answers.
            with suppress(ValueError):
                wedges += _corner_wedge(curb, followers[0], arc, named)
    fills: list[Triangle] = []
    for junction in junctions:
        fills += _junction_fill(junction, nodes, segments, sides, sagitta)

    # Every piece in the order the rules list them, with the points its bounds are taken from.
    pieces: list[tuple[Callable[[Plan], _Ratio | None], str, Sequence[Sequence[int]]]] = []
    for curb in straight:
        pieces.append((curb.kerb_top, KERB_TOP, curb.kerb_top_bounds()))
        pieces += [(_triangle_height(one), FOOTWAY, one) for one in curb.footway]
    for strip in strips:
        bounds = (*strip.centre.points, *strip.left.points, *strip.right.points)
        pieces.append((strip.height, CARRIAGEWAY, bounds))
    for surface, triangles in ((KERB_TOP, tops), (FOOTWAY, wedges), (CARRIAGEWAY, fills)):
        pieces += [(_triangle_height(one), surface, one) for one in triangles]
    cell = _CELL_MM
    cells: dict[Plan, list[int]] = {}
    for index, (_, _, points) in enumerate(pieces):
        low_x, low_y, high_x, high_y = _cells_of(points, cell)
        for cell_x in range(low_x, high_x + 1):
            for cell_y in range(low_y, high_y + 1):
                cells.setdefault((cell_x, cell_y), []).append(index)

    def reading(point: Plan) -> tuple[int, str] | None:
        height: _Ratio | None = None
        surface = ""
        for index in cells.get((point[0] // cell, point[1] // cell), ()):
            answer, named, _ = pieces[index]
            on = answer(point)
            if on is not None and (height is None or on.key(height) > 0):
                height, surface = on, named
        return None if height is None else (height.rounded(), surface)

    return reading


def _triangle_height(triangle: Triangle) -> Callable[[Plan], _Ratio | None]:
    return lambda point: _on_triangle(point, triangle)


def _cells_of(points: Sequence[Sequence[int]], cell: int) -> tuple[int, int, int, int]:
    """The lowest and highest cells of side ``cell``, east and north, that ``points``' bounds
    reach, the margin added."""
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (
        (min(xs) - _BOUNDS_MARGIN_MM) // cell,
        (min(ys) - _BOUNDS_MARGIN_MM) // cell,
        (max(xs) + _BOUNDS_MARGIN_MM) // cell,
        (max(ys) + _BOUNDS_MARGIN_MM) // cell,
    )
