"""What a curb owns: its straight kerb and footway, and the corner its radius turns.

A curb edge is the kerb, gutter and footway of one side of one segment. Its straight part runs
along its kerb line. **The curb that states ``corner_radius_mm`` also owns the corner** to the
curb that follows it: the kerb face along the arc, the kerb top, and the footway wedge, up to the
follower's tangent point. A junction owns only the carriageway fill inside the kerb arcs. So every
surface a street draws belongs to exactly one record, and that record's extent holds it.

**The measure.** Every point below is placed by the corner rule's measure, the one the tile
document's ``[corner_radius]`` check and the tessellator use: ``d`` along an integer vector ``v``
is ``floor(v * d * S / isqrt(|v|^2 * S^2))`` on each axis, with ``S = 10**6``.

**Walking round the face.** Going counter-clockwise round the face a curb bounds takes a left
curb's kerb line first point to last and a right curb's last to first, so the face (the block, or
where a block would be) is always on the walk's left, and the left normal of a direction
``(dx, dy)`` is ``(-dy, dx)``.

**The straight part** of a curb is, for each piece of its kerb line, the strip from the kerb line
to the line ``kerb_width_mm + footway_width_mm`` away on the face side: the kerb face, the kerb top
and the footway. Its box (:func:`strip_box`) is the plan box of each piece's two ends and the same
two points moved that far along the face side's normal, and in height it runs from the kerb line's
lowest point to its highest plus ``kerb_height_mm`` plus the footway's rise,
``footway_width_mm * footway_crossfall_millionths // 10**6``.

**The corner** (:func:`corner_of`). ``P`` is where the curb's walk ends and ``Q`` where its
follower's walk begins; ``leaving`` is the walk's last piece at ``P`` and ``joining`` the
follower's first piece at ``Q``. The turn is ``+1`` when ``leaving`` turns left into ``joining``
(a convex corner of the face) and ``-1`` when it turns right (a concave one). The centre ``C`` is
``P`` moved the radius along the normal toward the turn, as ``[corner_radius]`` finds it, so the
tangent points' normals meet at ``C``. Then, with ``d`` a curb's ``kerb_width_mm +
footway_width_mm``:

* the kerb face runs along the arc of radius ``r`` about ``C`` from ``P`` to ``Q``, turning the
  way the walk turns, and rises ``kerb_height_mm``;
* the kerb top lies between that arc and its back arc, ``kerb_width_mm`` further toward the face,
  radius ``r - turn * kerb_width_mm``;
* **the ground is partitioned at the tangent points' normals.** Each straight piece's strip ends
  at its tangent point's normal. The corner owns what lies between the two normals, beyond the
  kerb top's back arc on the face side, and outside the building side beyond the frontage corner
  ``F``, where the line ``d`` from ``leaving`` (this curb's widths) meets the line ``d`` from
  ``joining`` (the follower's widths). At a convex corner the building side is the quadrant
  beyond both lines; at a concave corner, where the face wraps round the corner, it is everything
  beyond either. Where the curb has a block, ``F`` is that block ring's corner, exactly;
* on a convex corner whose widths are both under ``r``, the footway wedge is the polygon from the
  back arc out to ``F_P`` on ``P``'s normal, along this curb's frontage line to ``F``, along the
  follower's to ``F_Q`` on ``Q``'s normal, and back to the arc. When either width reaches ``r``,
  the frontage lines never enter the region between the normals, and the wedge runs from the back
  arc to ``C``; the two straight strips, which would overlap beyond ``C``, meet on the mitre line
  from ``C`` to ``F``, each side belonging to its own piece (this curb's last, the follower's
  first);
* a concave corner is the same partition with the arc's side reversed: the wedge lies between the
  normals from the back arc, radius ``r + kerb_width_mm``, out to ``F_P``, ``F`` and ``F_Q``.
  The footway wedge rises by this curb's crossfall.

A degenerate corner is refused: a convex radius of at most ``kerb_width_mm``, which leaves the
kerb top no back arc, and pieces that are parallel or reversed.

**The corner's box** (:func:`corner_box`) is the plan box of ``P``, ``Q``, ``P`` and ``Q`` moved
``kerb_width_mm`` along their pieces' face-side normals, ``F`` (its rational coordinates floored
and ceiled), ``C`` plus and minus the larger of the two arc radii along each axis direction the arc
passes through from ``C -> P`` to ``C -> Q`` in the turn's sense, and then ``C`` itself when the
mitre applies, or ``F_P`` and ``F_Q`` when it does not. In height it runs from the lower of ``P``
and ``Q`` to the higher plus ``kerb_height_mm`` plus this curb's footway rise. Every point the
tessellator places on these surfaces by the same measure lies inside it, so a curb's extent that
holds its strip box and its corner box holds everything it owns; the tile document's
``[curb_extent]`` and ``[corner_extent]`` checks refuse one that does not.

**The junction's fill** (:func:`junction_fill_box`) is the carriageway inside the kerb arcs: it
reaches each leg's two kerb lines where they end nearest the node, and each corner arc between
legs. Its box is the plan box of those kerb line ends, the node, and each corner's ``P``, ``Q`` and
``C`` plus and minus ``r`` along each axis direction its arc passes through; in height, from the
lowest of those kerb line ends and the node to the highest. ``[junction_extent]`` refuses a
junction extent that does not hold it, whenever the node, every leg and both of every leg's curbs
are carried.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import Extent, integer_sqrt
from exulanica.grammar.grammars.city.common import MILLIONTHS
from exulanica.grammar.grammars.city.streets import (
    CurbEdgeRecord,
    StreetNodeRecord,
    StreetSegmentRecord,
)

__all__ = [
    "CORNER_LENGTH_SCALE",
    "Corner",
    "along",
    "corner_box",
    "corner_centre",
    "corner_of",
    "footway_rise_mm",
    "frontage_corner",
    "junction_fill_box",
    "strip_box",
    "walk_round_face",
]

#: The scale at which the corner rule measures a piece's length: millionths of a millimetre.
CORNER_LENGTH_SCALE: Final = 1_000_000
#: The four axis directions an arc's box may reach out along.
_AXES: Final = ((1, 0), (0, 1), (-1, 0), (0, -1))

Point = tuple[int, int]


def along(vector: Point, distance: int) -> Point:
    """``distance`` along ``vector``, by the corner rule's measure, each component floored."""
    dx, dy = vector
    if dx == 0 and dy == 0:
        raise InvalidRecordError("a distance is measured along a vector of some length")
    scale = CORNER_LENGTH_SCALE
    length = integer_sqrt((dx * dx + dy * dy) * scale * scale)
    return (dx * distance * scale) // length, (dy * distance * scale) // length


def _left(vector: Point) -> Point:
    return -vector[1], vector[0]


def _moved(point: Point, by: Point) -> Point:
    return point[0] + by[0], point[1] + by[1]


def _cross(a: Point, b: Point) -> int:
    return a[0] * b[1] - a[1] * b[0]


def walk_round_face(curb: CurbEdgeRecord) -> tuple[Point, ...]:
    """A kerb line in plan, in the order a counter-clockwise walk round the curb's face takes it."""
    line = tuple((x, y) for x, y, _z in curb.kerb_line_mm)
    return line if curb.side == "left" else line[::-1]


def corner_centre(point: Point, direction: Point, radius: int, turn: int) -> Point:
    """``point`` plus ``radius`` along the unit normal toward the turn, floored as stated."""
    return _moved(point, along((-turn * direction[1], turn * direction[0]), radius))


def footway_rise_mm(curb: CurbEdgeRecord) -> int:
    """How far a curb's footway rises from its kerb top to its back edge."""
    return curb.footway_width_mm * curb.footway_crossfall_millionths // MILLIONTHS


def _heights(curb: CurbEdgeRecord) -> tuple[int, int]:
    heights = [z for _x, _y, z in curb.kerb_line_mm]
    return min(heights), max(heights) + curb.kerb_height_mm + footway_rise_mm(curb)


def _box(points: list[Point], low_z: int, high_z: int) -> Extent:
    xs = [x for x, _y in points]
    ys = [y for _x, y in points]
    return Extent(min(xs), min(ys), low_z, max(xs), max(ys), high_z)


def strip_box(curb: CurbEdgeRecord) -> Extent:
    """The box a curb's straight kerb, kerb top and footway fill, as the module states."""
    reach = curb.kerb_width_mm + curb.footway_width_mm
    walk = walk_round_face(curb)
    points: list[Point] = []
    for here, after in pairwise(walk):
        direction = (after[0] - here[0], after[1] - here[1])
        if direction == (0, 0):
            raise InvalidRecordError(f"curb {curb.identity} has a kerb piece of no length")
        offset = along(_left(direction), reach)
        points += [here, after, _moved(here, offset), _moved(after, offset)]
    return _box(points, *_heights(curb))


@dataclass(frozen=True, slots=True)
class Corner:
    """The corner a curb's radius turns into its follower, as the module states it."""

    p: Point
    q: Point
    leaving: Point
    joining: Point
    turn: int
    radius: int
    centre: Point


def corner_of(curb: CurbEdgeRecord, follower: CurbEdgeRecord) -> Corner | None:
    """The corner from ``curb`` to ``follower``, or ``None`` when its radius is 0.

    Refuses a stated radius on kerbs that run straight on. Whether the follower's tangent point
    agrees with the centre is ``[corner_radius]``'s check, not this function's.
    """
    if curb.corner_radius_mm == 0:
        return None
    before, after = walk_round_face(curb), walk_round_face(follower)
    p, q = before[-1], after[0]
    leaving = (p[0] - before[-2][0], p[1] - before[-2][1])
    joining = (after[1][0] - q[0], after[1][1] - q[1])
    cross = _cross(leaving, joining)
    if cross == 0:
        raise InvalidRecordError(f"curb {curb.identity}'s corner runs straight on with a radius")
    turn = 1 if cross > 0 else -1
    radius = curb.corner_radius_mm
    return Corner(p, q, leaving, joining, turn, radius, corner_centre(p, leaving, radius, turn))


def _floor_and_ceiling(base: int, numerator: int, denominator: int) -> tuple[int, int]:
    return base + numerator // denominator, base - (-numerator) // denominator


def _reach(curb: CurbEdgeRecord) -> int:
    return curb.kerb_width_mm + curb.footway_width_mm


def _frontage_lines(
    corner: Corner, curb: CurbEdgeRecord, follower: CurbEdgeRecord
) -> tuple[Point, Point, int, int]:
    """``F_P`` and ``F_Q``, and ``F`` as ``F_P + leaving * numerator / denominator``."""
    first = _moved(corner.p, along(_left(corner.leaving), _reach(curb)))
    second = _moved(corner.q, along(_left(corner.joining), _reach(follower)))
    numerator = _cross((second[0] - first[0], second[1] - first[1]), corner.joining)
    return first, second, numerator, _cross(corner.leaving, corner.joining)


def frontage_corner(curb: CurbEdgeRecord, follower: CurbEdgeRecord) -> Point | None:
    """``F``, when the corner has a radius and ``F`` falls on whole millimetres; else ``None``."""
    corner = corner_of(curb, follower)
    if corner is None:
        return None
    first, _second, numerator, denominator = _frontage_lines(corner, curb, follower)
    x_low, x_high = _floor_and_ceiling(first[0], corner.leaving[0] * numerator, denominator)
    y_low, y_high = _floor_and_ceiling(first[1], corner.leaving[1] * numerator, denominator)
    if (x_low, y_low) != (x_high, y_high):
        return None
    return x_low, y_low


def corner_box(curb: CurbEdgeRecord, follower: CurbEdgeRecord) -> Extent | None:
    """The box of the corner ``curb`` owns up to ``follower``, or ``None`` when it has none."""
    corner = corner_of(curb, follower)
    if corner is None:
        return None
    radius, turn = corner.radius, corner.turn
    if turn > 0 and radius <= curb.kerb_width_mm:
        raise InvalidRecordError(
            f"curb {curb.identity}'s convex corner radius leaves its kerb top no back arc"
        )
    points = [
        corner.p,
        corner.q,
        _moved(corner.p, along(_left(corner.leaving), curb.kerb_width_mm)),
        _moved(corner.q, along(_left(corner.joining), curb.kerb_width_mm)),
    ]
    first, second, numerator, denominator = _frontage_lines(corner, curb, follower)
    for x in _floor_and_ceiling(first[0], corner.leaving[0] * numerator, denominator):
        for y in _floor_and_ceiling(first[1], corner.leaving[1] * numerator, denominator):
            points.append((x, y))
    points += _arc_extremes(corner, radius if turn > 0 else radius + curb.kerb_width_mm)
    if turn > 0 and max(_reach(curb), _reach(follower)) >= radius:
        points.append(corner.centre)
    else:
        points += [first, second]
    p_height = (curb.kerb_line_mm[-1] if curb.side == "left" else curb.kerb_line_mm[0])[2]
    q_height = (follower.kerb_line_mm[0] if follower.side == "left" else follower.kerb_line_mm[-1])[
        2
    ]
    return _box(
        points,
        min(p_height, q_height),
        max(p_height, q_height) + curb.kerb_height_mm + footway_rise_mm(curb),
    )


def _arc_extremes(corner: Corner, radius: int) -> list[Point]:
    start = (corner.p[0] - corner.centre[0], corner.p[1] - corner.centre[1])
    end = (corner.q[0] - corner.centre[0], corner.q[1] - corner.centre[1])
    return [
        (corner.centre[0] + axis[0] * radius, corner.centre[1] + axis[1] * radius)
        for axis in _AXES
        if corner.turn * _cross(start, axis) >= 0 and corner.turn * _cross(axis, end) >= 0
    ]


def junction_fill_box(
    node: StreetNodeRecord,
    legs: Sequence[StreetSegmentRecord],
    curbs_of: Callable[[str], Mapping[str, CurbEdgeRecord]],
    carried: Callable[[str], object | None],
) -> Extent | None:
    """The box of a junction's carriageway fill, or ``None`` when a curb it needs is not carried.

    ``curbs_of`` gives a segment's carried curbs by side, and ``carried`` the carried record an
    identity names, or ``None``.
    """
    heights = [node.z_mm]
    points: list[Point] = [(node.x_mm, node.y_mm)]
    curbs: list[CurbEdgeRecord] = []
    for segment in legs:
        sides = curbs_of(segment.identity)
        if set(sides) != {"left", "right"}:
            return None
        at_start = segment.start_node_identity == node.identity
        for curb in sides.values():
            x, y, z = curb.kerb_line_mm[0] if at_start else curb.kerb_line_mm[-1]
            points.append((x, y))
            heights.append(z)
            curbs.append(curb)
    leg_identities = {segment.identity for segment in legs}
    for curb in curbs:
        for next_identity in curb.next_curb_identity:
            follower = carried(next_identity)
            if not isinstance(follower, CurbEdgeRecord):
                return None
            if follower.segment_identity not in leg_identities:
                continue
            corner = corner_of(curb, follower)
            if corner is not None:
                points += [corner.p, corner.q, *_arc_extremes(corner, corner.radius)]
    return _box(points, min(heights), max(heights))
