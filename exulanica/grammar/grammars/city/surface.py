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
  mitre, through the corner's centre and frontage corner at the corner's own level. The ring is cut
  into triangles by the ring rule (ear clipping, in the order the tessellator cuts), and a point's
  height is its triangle's.
* **A carriageway and its gutters** lie on the camber plane from the crown line down to each kerb
  line, between the strip's two ends (:mod:`~exulanica.grammar.grammars.city.streets`, the
  segment's step 1). A crossing's band is drawn on that carriageway and states no surface of its
  own, and its kerb upstand draws nothing, so a crossing answers the carriageway's height.

Where surfaces overlap, the highest is the answer, as on the page. A **corner's kerb top and
footway wedge**, a **junction's fill**, and a footway piece whose sloping kerb line ramps into a
mitred corner are not stated by this version: it answers ``None`` there, as it does where the
records state no street surface at all (a lot, a building, open land). The caller keeps its own
ground for ``None``.

Heights are exact ratios of integers, rounded half away from zero once at the end.
``tests/fixtures/city-surface-table.json`` holds every answer to the page's own walk surface on
the conformance tile and a generated tile.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from exulanica.grammar.geometry import integer_sqrt
from exulanica.grammar.grammars.city.corners import CORNER_LENGTH_SCALE, footway_rise_mm
from exulanica.grammar.grammars.city.corners import along as _along
from exulanica.grammar.grammars.city.streets import CurbEdgeRecord, StreetSegmentRecord

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
    # The frontage corner: where the two frontage lines meet, each axis floored.
    first = _moved(p, _along(_left(into), reach))
    second = _moved(q, _along(_left(out), other))
    numerator = _cross(_sub(second, first), out)
    frontage = (
        first[0] + into[0] * numerator // turning,
        first[1] + into[1] * numerator // turning,
    )
    crossfall = curb.footway_crossfall_millionths
    return _Mitre(
        (*centre, apex + (radius - curb.kerb_width_mm) * crossfall // _SCALE),
        (*frontage, apex + footway_rise_mm(curb)),
    )


def _footway(
    curb: CurbEdgeRecord, line: _Line, outward: Plan, turned: _Mitre | None, met: _Mitre | None
) -> tuple[Triangle, ...]:
    """A curb's footway rings, piece by piece along its kerb line, cut into triangles; none where
    a sloping kerb line ramps into a mitre, which this version does not state."""
    points = line.points
    if any(point[2] != points[0][2] for point in points) and (turned or met):
        return ()
    height, kerb_width = curb.kerb_height_mm, curb.kerb_width_mm
    reach, rise = kerb_width + curb.footway_width_mm, footway_rise_mm(curb)

    def out(point: Space, distance: int, up: int) -> Space:
        return (*_moved(point, _along(outward, distance)), point[2] + up)

    # A left curb is walked first point to last, a right one last to first: the walk's end piece
    # meets the corner this curb turns, its start piece the corner that turns into it.
    on_left = curb.side == "left"
    start, end = (0, 1) if on_left else (1, 0)
    pieces = len(points) - 1
    triangles: list[Triangle] = []
    for index in range(pieces):
        ends = (points[index], points[index + 1])
        backs = [out(point, kerb_width, height) for point in ends]
        fronts = [out(point, reach, height + rise) for point in ends]
        turned_here = turned if index == (pieces - 1 if on_left else 0) else None
        met_here = met if index == (0 if on_left else pieces - 1) else None
        ring = [backs[start], backs[end]]
        ring += [fronts[end]] if turned_here is None else [turned_here.centre, turned_here.frontage]
        ring += [fronts[start]] if met_here is None else [met_here.frontage, met_here.centre]
        triangles += _ears([point for at, point in enumerate(ring) if point != ring[at - 1]])
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

    def kerb_top(self, point: Plan) -> _Ratio | None:
        position = self.line.position(point)
        if not 0 <= position <= self.line.position(self.line.points[-1]):
            return None
        length = integer_sqrt(_dot(self.outward, self.outward) * _SCALE * _SCALE)
        out = _dot(_sub(point, self.line.points[0]), self.outward) * _SCALE
        if not 0 <= out <= self.kerb_width * length:
            return None
        return self.line.height(point) + self.kerb_height

    def footway_height(self, point: Plan) -> _Ratio | None:
        best: _Ratio | None = None
        for one in self.footway:
            height = _on_triangle(point, one)
            if height is not None and (best is None or height.key(best) > 0):
                best = height
        return best


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
    for record in records:
        if isinstance(record, StreetSegmentRecord):
            segments[record.identity] = record
        elif isinstance(record, CurbEdgeRecord):
            curbs[record.identity] = record
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
            footway = _footway(curb, line, outward, turned, met)
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

    def reading(point: Plan) -> tuple[int, str] | None:
        found: list[tuple[_Ratio, str]] = []
        for curb in straight:
            if (top := curb.kerb_top(point)) is not None:
                found.append((top, KERB_TOP))
            if (footway := curb.footway_height(point)) is not None:
                found.append((footway, FOOTWAY))
        for strip in strips:
            if (level := strip.height(point)) is not None:
                found.append((level, CARRIAGEWAY))
        if not found:
            return None
        height, surface = found[0]
        for other, named in found[1:]:
            if other.key(height) > 0:
                height, surface = other, named
        return height.rounded(), surface

    return reading
