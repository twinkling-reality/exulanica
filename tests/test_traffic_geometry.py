"""Integer geometry for traffic, checked against slower exact arithmetic written apart from it.

The collision rule rests on three things this file pins. The exact predicates (segment contact,
distance within a radius) agree with a rational brute force. A corridor rectangle reaches at least
its stated half-widths after rounding. And ``near_interval``, which decides which vehicles may
never be inside a zone together, returns a superset of every position whose corridor really meets
the other corridor.

Random cases come from a fixed ``random.Random`` seed, so every run checks the same cases.
"""

from __future__ import annotations

import random
from fractions import Fraction

import pytest
from exulanica.traffic.geometry import (
    Polyline,
    ceil_length,
    circumradius_at_least,
    circumradius_floor,
    convex_overlap,
    corridor_piece,
    near_interval,
    offtracking_mm,
    point_segment_within,
    rectangle,
    segments_intersect,
    segments_within,
)

SEED = 20260917


def _exact_distance_squared(p, a, b) -> Fraction:
    ab = (b[0] - a[0], b[1] - a[1])
    length_squared = ab[0] * ab[0] + ab[1] * ab[1]
    if length_squared == 0:
        t = Fraction(0)
    else:
        t = Fraction((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1], length_squared)
        t = min(max(t, Fraction(0)), Fraction(1))
    closest = (a[0] + t * ab[0], a[1] + t * ab[1])
    return (p[0] - closest[0]) ** 2 + (p[1] - closest[1]) ** 2


def _exact_intersect(a, b, c, d) -> bool:
    """Solve ``a + s (b - a) = c + t (d - c)`` in rationals; collinear cases by containment."""
    r = (b[0] - a[0], b[1] - a[1])
    q = (d[0] - c[0], d[1] - c[1])
    denominator = r[0] * q[1] - r[1] * q[0]
    ac = (c[0] - a[0], c[1] - a[1])
    if denominator != 0:
        s = Fraction(ac[0] * q[1] - ac[1] * q[0], denominator)
        t = Fraction(ac[0] * r[1] - ac[1] * r[0], denominator)
        return 0 <= s <= 1 and 0 <= t <= 1
    if ac[0] * r[1] - ac[1] * r[0] != 0:
        return False
    return any(
        _exact_distance_squared(point, *segment) == 0
        for point, segment in ((a, (c, d)), (b, (c, d)), (c, (a, b)), (d, (a, b)))
    )


def _point(rng: random.Random, span: int) -> tuple[int, int]:
    return (rng.randint(-span, span), rng.randint(-span, span))


# ---------------------------------------------------------------------------------------------
# Lengths, radii, off-tracking


def test_ceil_length_is_the_ceiling_of_the_true_length():
    rng = random.Random(SEED)
    for _ in range(5_000):
        a, b = _point(rng, 90_000), _point(rng, 90_000)
        squared = (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2
        length = ceil_length(a, b)
        assert length * length >= squared
        assert length == 0 or (length - 1) ** 2 < squared


def test_offtracking_is_the_rear_axle_track_rounded_up():
    for radius in range(1, 30_000, 97):
        for wheelbase in (1_780, 3_350, 7_620):
            tracked = offtracking_mm(radius, wheelbase)
            if radius <= wheelbase:
                assert tracked == radius
                continue
            inner = radius - tracked
            # The rear axle runs on sqrt(radius^2 - wheelbase^2); inner is that root floored.
            assert inner * inner <= radius * radius - wheelbase * wheelbase < (inner + 1) ** 2


def test_the_circumradius_floor_is_consistent_with_the_exact_comparison():
    rng = random.Random(SEED + 1)
    checked = 0
    for _ in range(3_000):
        a, b, c = _point(rng, 50_000), _point(rng, 50_000), _point(rng, 50_000)
        floor = circumradius_floor(a, b, c)
        if floor is None:
            assert circumradius_at_least(a, b, c, 10**12)
            continue
        assert circumradius_at_least(a, b, c, floor)
        assert not circumradius_at_least(a, b, c, floor + 1)
        checked += 1
    assert checked > 2_900


# ---------------------------------------------------------------------------------------------
# Exact predicates


def test_segment_intersection_agrees_with_rational_brute_force():
    rng = random.Random(SEED + 2)
    hits = 0
    for _ in range(20_000):
        # Small coordinates make touching, collinear and degenerate cases common.
        a, b, c, d = (_point(rng, 4) for _ in range(4))
        expected = _exact_intersect(a, b, c, d)
        assert segments_intersect(a, b, c, d) == expected, (a, b, c, d)
        hits += expected
    assert 2_000 < hits < 18_000


def test_distance_within_a_radius_agrees_with_rational_brute_force():
    rng = random.Random(SEED + 3)
    for _ in range(20_000):
        p, a, b = _point(rng, 30), _point(rng, 30), _point(rng, 30)
        radius = rng.randint(0, 40)
        expected = _exact_distance_squared(p, a, b) <= radius * radius
        assert point_segment_within(p, a, b, radius) == expected, (p, a, b, radius)


def test_segments_within_a_radius_agrees_with_rational_brute_force():
    rng = random.Random(SEED + 4)
    for _ in range(10_000):
        a, b, c, d = (_point(rng, 25) for _ in range(4))
        radius = rng.randint(0, 20)
        if _exact_intersect(a, b, c, d):
            expected = True
        else:
            # Apart segments are closest at an endpoint of one of them.
            expected = (
                min(
                    _exact_distance_squared(a, c, d),
                    _exact_distance_squared(b, c, d),
                    _exact_distance_squared(c, a, b),
                    _exact_distance_squared(d, a, b),
                )
                <= radius * radius
            )
        assert segments_within(a, b, c, d, radius) == expected, (a, b, c, d, radius)


def test_convex_overlap_is_interior_overlap_for_axis_aligned_rectangles():
    def box(x0, y0, x1, y1):
        return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))

    rng = random.Random(SEED + 5)
    for _ in range(20_000):
        x0, x1 = sorted(rng.sample(range(0, 12), 2))
        y0, y1 = sorted(rng.sample(range(0, 12), 2))
        u0, u1 = sorted(rng.sample(range(0, 12), 2))
        v0, v1 = sorted(rng.sample(range(0, 12), 2))
        expected = max(x0, u0) < min(x1, u1) and max(y0, v0) < min(y1, v1)
        first, second = box(x0, y0, x1, y1), box(u0, v0, u1, v1)
        assert convex_overlap(first, second) == expected
        assert convex_overlap(second, first) == expected


def test_convex_overlap_on_rotated_shapes():
    diamond = ((0, -10), (10, 0), (0, 10), (-10, 0))
    assert convex_overlap(diamond, ((4, 4), (20, 4), (20, 20), (4, 20)))
    # The corner (5, 5) of this square is on the diamond's edge, so the two only touch.
    assert not convex_overlap(diamond, ((5, 5), (20, 5), (20, 20), (5, 20)))
    # Sharing only an edge segment or a corner is not overlap.
    assert not convex_overlap(diamond, ((5, 5), (15, 15), (5, 25), (-5, 15)))
    assert not convex_overlap(diamond, ((10, 0), (20, -10), (30, 0), (20, 10)))
    assert convex_overlap(diamond, ((-1, -1), (1, -1), (1, 1), (-1, 1)))


# ---------------------------------------------------------------------------------------------
# Paths and corridors


def test_a_polyline_measures_with_ceiling_lengths_and_maps_positions_to_points():
    line = Polyline.of([(0, 0), (3, 4), (3, 10)])
    assert line.offsets == (0, 5, 11)
    assert line.point_at(0) == (0, 0)
    assert line.point_at(5) == (3, 4)
    assert line.point_at(11) == (3, 10)
    assert line.point_at(-7) == (0, 0) and line.point_at(99) == (3, 10)
    assert [line.piece_index(position) for position in (0, 4, 5, 10, 11)] == [0, 0, 1, 1, 1]
    assert line.span(2, 8) == [(0, line.point_at(2), (3, 4)), (1, (3, 4), line.point_at(8))]
    with pytest.raises(ValueError, match="at least two points"):
        Polyline.of([(0, 0)])
    with pytest.raises(ValueError, match="zero-length"):
        Polyline.of([(0, 0), (0, 0), (1, 1)])


def test_a_corridor_rectangle_reaches_at_least_its_half_widths():
    rng = random.Random(SEED + 6)
    for _ in range(5_000):
        a = _point(rng, 100_000)
        b = _point(rng, 100_000)
        if a == b:
            continue
        left, right = rng.randint(0, 5_000), rng.randint(0, 5_000)
        corners = rectangle(a, b, left, right)
        assert corners is not None
        direction = (b[0] - a[0], b[1] - a[1])
        length_squared = direction[0] ** 2 + direction[1] ** 2
        for corner, origin, reach, sign in (
            (corners[0], a, right, -1),
            (corners[1], b, right, -1),
            (corners[2], b, left, 1),
            (corners[3], a, left, 1),
        ):
            offset = (corner[0] - origin[0], corner[1] - origin[1])
            across = direction[0] * offset[1] - direction[1] * offset[0]
            # The signed distance to the left of the piece is across / |direction|.
            assert sign * across >= 0 or reach == 0
            assert across * across >= reach * reach * length_squared
            # And by no more than the rounding of the two components, even on a short piece.
            assert across * across <= (reach + 2) ** 2 * length_squared
            along = direction[0] * offset[0] + direction[1] * offset[1]
            # The ends stay flat to within the one millimetre of rounding.
            assert along * along <= length_squared
    assert rectangle((5, 5), (5, 5), 10, 10) is None


def _inside_exact_rectangle(point, a, b, left, right) -> bool:
    direction = (b[0] - a[0], b[1] - a[1])
    offset = (point[0] - a[0], point[1] - a[1])
    length_squared = direction[0] ** 2 + direction[1] ** 2
    along = direction[0] * offset[0] + direction[1] * offset[1]
    across = direction[0] * offset[1] - direction[1] * offset[0]
    reach = left if across >= 0 else right
    return 0 <= along <= length_squared and across * across <= reach * reach * length_squared


def test_a_shifted_corridor_piece_covers_the_asymmetric_rectangle():
    """Every integer point of the true corridor, corners included, is inside the capsule."""
    rng = random.Random(SEED + 7)
    checked = 0
    for _ in range(2_000):
        a = _point(rng, 60_000)
        b = (a[0] + rng.randint(-20_000, 20_000), a[1] + rng.randint(-20_000, 20_000))
        if a == b:
            continue
        left, right = rng.randint(0, 4_070), rng.randint(0, 4_070)
        c, d, half = corridor_piece(a, b, left, right)
        corners = rectangle(a, b, left, right)
        assert corners is not None
        candidates = [
            (corner[0] + dx, corner[1] + dy)
            for corner in corners
            for dx in range(-2, 3)
            for dy in range(-2, 3)
        ]
        xs = [corner[0] for corner in corners]
        ys = [corner[1] for corner in corners]
        candidates += [
            (rng.randint(min(xs), max(xs)), rng.randint(min(ys), max(ys))) for _ in range(40)
        ]
        for point in candidates:
            if _inside_exact_rectangle(point, a, b, left, right):
                checked += 1
                assert point_segment_within(point, c, d, half), (a, b, left, right, point)
    assert checked > 10_000


def _random_path(rng: random.Random) -> tuple[Polyline, tuple[tuple[int, int], ...]]:
    # Paths start close together, so their corridors meet in most cases.
    start = _point(rng, 3_000)
    points = [start]
    for _ in range(rng.randint(1, 3)):
        # Short pieces with lopsided corridors are where rounding would show first.
        reach = 400 if rng.randint(0, 1) else 9_000
        step = (rng.randint(-reach, reach), rng.randint(-reach, reach))
        following = (points[-1][0] + step[0], points[-1][1] + step[1])
        if following != points[-1]:
            points.append(following)
    if len(points) < 2:
        points.append((start[0] + 1_000, start[1]))
    line = Polyline.of(points)
    extents = tuple(
        (rng.randint(300, 4_070), rng.randint(300, 4_070)) for _ in range(line.piece_count)
    )
    return line, extents


def _corridor_pieces(line, extents, start, end):
    shapes = []
    for index, a, b in line.span(start, end):
        shape = rectangle(a, b, *extents[index])
        if shape is not None:
            shapes.append(shape)
    return shapes


def test_near_interval_is_a_superset_of_every_position_whose_corridor_meets_the_other():
    """The soundness of every conflict zone: a meeting outside the interval would be a crash."""
    rng = random.Random(SEED + 8)
    step = 200
    met = 0
    for _ in range(240):
        path, path_extents = _random_path(rng)
        other, other_extents = _random_path(rng)
        interval = near_interval(path, path_extents, other, other_extents)
        whole_other = _corridor_pieces(other, other_extents, 0, other.length)
        for start in range(0, path.length, step):
            end = min(start + step, path.length)
            if not any(
                convex_overlap(mine, theirs)
                for mine in _corridor_pieces(path, path_extents, start, end)
                for theirs in whole_other
            ):
                continue
            met += 1
            assert interval is not None, (path, other)
            assert interval[0] <= end and start <= interval[1], (start, end, interval)
    assert met > 2_000


def test_near_interval_is_none_for_corridors_far_apart_and_checks_its_extents():
    line = Polyline.of([(0, 0), (10_000, 0)])
    far = Polyline.of([(0, 20_000), (10_000, 20_000)])
    assert near_interval(line, ((1_000, 1_000),), far, ((1_000, 1_000),)) is None
    crossing = Polyline.of([(5_000, -5_000), (5_000, 5_000)])
    low, high = near_interval(line, ((1_000, 1_000),), crossing, ((1_500, 1_500),))
    # A perpendicular corridor 1.5 m either side, met by a body 1 m either side: 2.5 m each way,
    # plus the two millimetres of slack and the rounding, and no more.
    assert 5_000 - 2_510 <= low <= 5_000 - 2_500
    assert 5_000 + 2_500 <= high <= 5_000 + 2_510
    with pytest.raises(ValueError, match="one extent pair per piece"):
        near_interval(line, (), far, ((1, 1),))
