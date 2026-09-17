"""The corner a curb owns, held to its stated partition point by point.

``exulanica.grammar.grammars.city.corners`` says which ground a curb's corner owns (between the
tangent points' normals, beyond the kerb face on the face side, outside the building quadrant) and
states a box that must hold it. These tests do not trust the box's own reasoning: they sample
every integer point near a corner, decide membership from the partition's definition in exact
rational arithmetic, and require each owned point to lie in the box. The corners cover a convex
corner with footways under the radius, a convex corner mitred at its centre, a concave corner and
corners whose pieces are not axis aligned.
"""

from __future__ import annotations

import dataclasses
from fractions import Fraction

import pytest
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city.corners import (
    along,
    corner_box,
    corner_of,
    frontage_corner,
    strip_box,
)
from exulanica.grammar.grammars.city.streets import CurbEdgeRecord

_OWNER = "00000000-0000-5000-8000-000000000001"
_FOLLOWER = "00000000-0000-5000-8000-000000000002"
_SEGMENT = "00000000-0000-5000-8000-000000000003"


def _curb(identity: str, line: tuple[tuple[int, int], ...], **widths: int) -> CurbEdgeRecord:
    xs = [x for x, _y in line]
    ys = [y for _x, y in line]
    return CurbEdgeRecord(
        identity=identity,
        segment_identity=_SEGMENT,
        side="left",
        block_identity=(),
        kerb_line_mm=tuple((x, y, 0) for x, y in line),
        kerb_height_mm=150,
        kerb_width_mm=widths.get("kerb", 200),
        gutter_width_mm=300,
        footway_width_mm=widths["footway"],
        footway_crossfall_millionths=20_000,
        next_curb_identity=(_FOLLOWER,) if identity == _OWNER else (),
        corner_radius_mm=widths.get("radius", 0),
        extent=Extent(min(xs), min(ys), 0, max(xs), max(ys), 0),
    )


def _pair(
    leaving: tuple[int, int],
    joining: tuple[int, int],
    turn: int,
    radius: int,
    footways: tuple[int, int],
) -> tuple[CurbEdgeRecord, CurbEdgeRecord]:
    """Two left curbs meeting on an arc of ``radius`` about the origin's neighbourhood."""
    centre = (40_000, 40_000)
    to_p = along((turn * leaving[1], -turn * leaving[0]), radius)
    to_q = along((turn * joining[1], -turn * joining[0]), radius)
    p = (centre[0] + to_p[0], centre[1] + to_p[1])
    q = (centre[0] + to_q[0], centre[1] + to_q[1])
    back = along(leaving, 30_000)
    ahead = along(joining, 30_000)
    owner = _curb(_OWNER, ((p[0] - back[0], p[1] - back[1]), p), footway=footways[0], radius=radius)
    follower = _curb(_FOLLOWER, (q, (q[0] + ahead[0], q[1] + ahead[1])), footway=footways[1])
    return owner, follower


def _cross(a, b) -> Fraction:
    return Fraction(a[0]) * b[1] - Fraction(a[1]) * b[0]


def _beyond(point, origin, direction, reach: int) -> bool:
    """Whether ``point`` is more than ``reach`` from the line, on its left (the face side)."""
    offset = (point[0] - origin[0], point[1] - origin[1])
    side = _cross(direction, offset)
    return side > 0 and side * side > Fraction(reach * reach) * (
        direction[0] * direction[0] + direction[1] * direction[1]
    )


def _owned(point, owner: CurbEdgeRecord, follower: CurbEdgeRecord) -> bool:
    corner = corner_of(owner, follower)
    assert corner is not None
    c, turn = corner.centre, corner.turn
    start = (corner.p[0] - c[0], corner.p[1] - c[1])
    end = (corner.q[0] - c[0], corner.q[1] - c[1])
    here = (point[0] - c[0], point[1] - c[1])
    if turn * _cross(start, here) < 0 or turn * _cross(here, end) < 0:
        return False
    distance = here[0] * here[0] + here[1] * here[1]
    radius = corner.radius
    if (turn > 0 and distance > radius * radius) or (turn < 0 and distance < radius * radius):
        return False
    reach_owner = owner.kerb_width_mm + owner.footway_width_mm
    reach_follower = follower.kerb_width_mm + follower.footway_width_mm
    first = _beyond(point, corner.p, corner.leaving, reach_owner)
    second = _beyond(point, corner.q, corner.joining, reach_follower)
    # The building side beyond F: past both frontage lines at a convex corner, past either at a
    # concave one, where the face wraps round the corner.
    return not ((first and second) if turn > 0 else (first or second))


def _in_plan(box: Extent, point) -> bool:
    return box.min_x_mm <= point[0] <= box.max_x_mm and box.min_y_mm <= point[1] <= box.max_y_mm


_CORNERS = {
    "convex, footways under the radius": ((1, 0), (0, 1), 1, 6_000, (3_000, 2_500)),
    "convex, a footway reaching the radius": ((1, 0), (0, 1), 1, 3_000, (4_500, 4_500)),
    "convex, one footway past the radius": ((1, 0), (0, 1), 1, 4_000, (2_000, 4_200)),
    "convex, slanted pieces": ((3, 1), (-1, 4), 1, 7_000, (2_800, 3_300)),
    "convex, a shallow turn": ((5, 1), (4, 3), 1, 9_000, (3_000, 3_000)),
    "concave": ((1, 0), (0, -1), -1, 5_000, (2_500, 3_000)),
    "concave, slanted pieces": ((2, 1), (1, -3), -1, 6_000, (2_000, 2_600)),
}


@pytest.mark.parametrize("case", sorted(_CORNERS))
def test_every_point_a_corner_owns_lies_in_its_box(case):
    leaving, joining, turn, radius, footways = _CORNERS[case]
    owner, follower = _pair(leaving, joining, turn, radius, footways)
    corner = corner_of(owner, follower)
    assert corner is not None and corner.turn == turn
    box = corner_box(owner, follower)
    assert box is not None
    reach = 20_000
    step = 97
    owned = 0
    for x in range(corner.centre[0] - reach, corner.centre[0] + reach, step):
        for y in range(corner.centre[1] - reach, corner.centre[1] + reach, step):
            if _owned((x, y), owner, follower):
                owned += 1
                assert _in_plan(box, (x, y)), (case, (x, y), box)
    assert owned > 100, (case, owned)


def test_the_box_holds_the_arc_the_tangent_points_and_the_centre_when_mitred():
    owner, follower = _pair((1, 0), (0, 1), 1, 3_000, (4_500, 4_500))
    corner = corner_of(owner, follower)
    box = corner_box(owner, follower)
    assert corner is not None and box is not None
    for point in (corner.p, corner.q, corner.centre):
        assert _in_plan(box, point)
    assert box.min_z_mm == 0
    assert box.max_z_mm == 150 + 4_500 * 20_000 // 1_000_000


def test_a_corner_with_footways_under_its_radius_does_not_reach_its_centre():
    owner, follower = _pair((1, 0), (0, 1), 1, 6_000, (3_000, 2_500))
    corner = corner_of(owner, follower)
    box = corner_box(owner, follower)
    assert corner is not None and box is not None
    assert not _in_plan(box, (corner.centre[0] - 1, corner.centre[1] + 1))
    assert frontage_corner(owner, follower) == (
        corner.q[0] - 200 - 2_500,
        corner.p[1] + 200 + 3_000,
    )


def test_a_convex_radius_no_wider_than_the_kerb_is_refused():
    owner, follower = _pair((1, 0), (0, 1), 1, 200, (3_000, 3_000))
    with pytest.raises(InvalidRecordError, match="no back arc"):
        corner_box(owner, follower)


def test_kerbs_that_run_straight_on_with_a_radius_are_refused():
    owner = _curb(_OWNER, ((0, 0), (10_000, 0)), footway=3_000, radius=4_000)
    follower = _curb(_FOLLOWER, ((10_000, 0), (20_000, 0)), footway=3_000)
    with pytest.raises(InvalidRecordError, match="straight on"):
        corner_box(owner, follower)


def test_a_curb_with_no_radius_owns_no_corner():
    owner = _curb(_OWNER, ((0, 0), (10_000, 0)), footway=3_000)
    follower = _curb(_FOLLOWER, ((10_000, 0), (10_000, 10_000)), footway=3_000)
    assert corner_box(owner, follower) is None
    assert frontage_corner(owner, follower) is None


def test_a_straight_strip_box_reaches_the_frontage_line_on_the_face_side():
    left = _curb(_OWNER, ((0, 0), (10_000, 0)), footway=3_000)
    assert strip_box(left) == Extent(0, 0, 0, 10_000, 3_200, 210)
    right = dataclasses.replace(left, side="right")
    assert strip_box(right) == Extent(0, -3_200, 0, 10_000, 0, 210)
