"""The conversion rules on small outlines whose right answer can be worked by hand."""

from __future__ import annotations

from fractions import Fraction

import pytest

from exulanica_lettering_tool.geometry import parts_problem, ring_problem, scale
from exulanica_lettering_tool.outline import (
    Conversion,
    OutlineRefused,
    OutlineStatistics,
    contour_segments,
    flatten,
    glyph_parts,
    merge_short_edges,
    simplify,
)

ON = 0x01


def test_scale_rounds_halves_toward_positive_infinity_on_both_sides_of_zero():
    # cap 1000 font units at 100 mm: one font unit is a tenth of a millimetre.
    assert [scale(v, 100, 1000) for v in (-15, -5, 4, 5, 15)] == [-1, 0, 0, 1, 2]
    # Two points a millimetre apart never share a millimetre, which round-half-to-zero breaks.
    assert scale(-5, 100, 1000) != scale(5, 100, 1000)


def test_a_quadratic_takes_the_fewest_steps_within_the_tolerance():
    rule = Conversion(cap_height=1200, minimum_cap_height_mm=100, maximum_cap_height_mm=1200)
    # tolerance = 1200 / 1200 = 1 font unit; a = p0 - 2 p1 + p2 = (0, -80); error <= |a| / (4 n^2).
    segments = [
        ((Fraction(0), Fraction(0)), (Fraction(40), Fraction(40)), (Fraction(80), Fraction(0)))
    ]
    points = flatten(segments, rule)
    # 80 / (4 n^2) <= 1 first holds at n = 5 (80 / 100); n = 4 gives 80 / 64 > 1.
    assert len(points) == 5
    assert points[-1] == (Fraction(80), Fraction(0))
    # B(1/5) = 16/25 p0 + 8/25 p1 + 1/25 p2.
    assert points[0] == (Fraction(16), Fraction(64, 5))


def test_implied_on_curve_points_are_exact_midpoints():
    segments = contour_segments([(0, 0), (10, 10), (21, 10), (30, 0)], [True, False, False, True])
    assert segments[0] == ((0, 0), (10, 10), (Fraction(31, 2), 10))
    assert segments[1] == ((Fraction(31, 2), 10), (21, 10), (30, 0))
    assert segments[2] == ((30, 0), (0, 0))


def test_simplify_drops_repeats_and_straight_run_vertices_only():
    assert simplify([(0, 0), (5, 0), (10, 0), (10, 0), (10, 10), (0, 10)]) == [
        (0, 0),
        (10, 0),
        (10, 10),
        (0, 10),
    ]


def test_the_shortest_edge_loses_its_flatter_end():
    # Edge 1, (100, 0) to (103, 2), is 3 long. |cross| at (100, 0) is 100 * 2 = 200; at (103, 2)
    # it is 3 * 100 - 2 * 3 = 294. So (100, 0) goes.
    ring = [(0, 0), (100, 0), (103, 2), (103, 100), (0, 100)]
    merged, removed = merge_short_edges(ring, 7)
    assert removed == 1
    assert merged == [(0, 0), (103, 2), (103, 100), (0, 100)]


def _square(
    x0: int, y0: int, size: int, clockwise: bool
) -> tuple[list[tuple[int, int]], list[int]]:
    points = [(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size)]
    if clockwise:
        points = points[::-1]
    return points, [ON] * 4


def test_a_counter_hole_becomes_a_counter_clockwise_hole_of_its_part():
    rule = Conversion(cap_height=1000, minimum_cap_height_mm=100, maximum_cap_height_mm=1200)
    contours = [_square(0, 0, 500, clockwise=True), _square(100, 100, 300, clockwise=False)]
    ((outer, holes),) = glyph_parts(contours, rule, OutlineStatistics())
    assert outer == ((0, 0), (500, 0), (500, 500), (0, 500))
    assert holes == (((100, 100), (400, 100), (400, 400), (100, 400)),)
    assert parts_problem(((outer, holes),)) is None


def test_a_filled_contour_wound_counter_clockwise_is_refused():
    rule = Conversion(cap_height=1000, minimum_cap_height_mm=100, maximum_cap_height_mm=1200)
    with pytest.raises(OutlineRefused, match="winds against"):
        glyph_parts([_square(0, 0, 500, clockwise=False)], rule, OutlineStatistics())


def test_overlapping_contours_are_refused_not_merged():
    rule = Conversion(cap_height=1000, minimum_cap_height_mm=100, maximum_cap_height_mm=1200)
    contours = [_square(0, 0, 500, clockwise=True), _square(400, 400, 500, clockwise=True)]
    with pytest.raises(OutlineRefused, match="meet"):
        glyph_parts(contours, rule, OutlineStatistics())


def test_the_ring_rule_names_a_spike_and_touching_edges():
    assert ring_problem([(0, 0), (10, 0), (5, 0), (5, 10)]) == "vertex 1 is a spike"
    bow = [(0, 0), (10, 0), (10, 10), (5, 0), (0, 10)]
    # (5, 0), where edges 2 and 3 join, lies on edge 0.
    assert ring_problem(bow) == "edges 0 and 3 meet"
