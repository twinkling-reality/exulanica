"""The integer planar carve (:mod:`exulanica.grammar.grammars.city.carve`) cuts a ring as the
tessellator's ``openRegions`` does: the same walks, corner for corner and in the same order, so a
corner's footway wedge read on the server is the one the page draws.

Each case's walks are loom-tess's own output for the same ring and standing rings, recorded from
``web/packages/loom-tess/src/core/piece-carve.ts``. The city surface's parity table
(``tests/test_city_surface.py``) holds the carve on real corners too.
"""

from __future__ import annotations

from typing import Final

import pytest
from exulanica.grammar.grammars.city.carve import open_regions, ring_triangles

Plan = tuple[int, int]

SQUARE: Final[list[Plan]] = [(0, 0), (10, 0), (10, 10), (0, 10)]
#: Each case: the ring, the rings standing on it, and the tessellator's walks for them.
CASES: Final[dict[str, tuple[list[Plan], list[list[Plan]], list[list[Plan]]]]] = {
    "nothing_standing": (
        SQUARE,
        [],
        [[(0, 10), (0, 0), (10, 0)], [(10, 0), (10, 10), (0, 10)]],
    ),
    "half_covered": (
        SQUARE,
        [[(5, -5), (15, -5), (15, 15), (5, 15)]],
        [[(0, 0), (5, 0), (5, 10), (0, 10)]],
    ),
    "hole_cut_along_rows": (
        SQUARE,
        [[(3, 3), (7, 3), (7, 7), (3, 7)]],
        [
            [(0, 0), (10, 0), (10, 3), (7, 3), (3, 3), (0, 3)],
            [(7, 3), (10, 3), (10, 7), (7, 7)],
            [(0, 7), (3, 7), (7, 7), (10, 7), (10, 10), (0, 10)],
            [(0, 3), (3, 3), (3, 7), (0, 7)],
        ],
    ),
    "sloped_edge_rounds": (
        SQUARE,
        [[(0, -1), (11, -1), (11, 2)]],
        [[(0, 0), (3, 0), (4, 0), (10, 1), (10, 2), (10, 10), (0, 10)]],
    ),
    "turning_in": (
        [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)],
        [[(2, 2), (12, 2), (12, 3), (2, 3)]],
        [
            [(0, 0), (10, 0), (10, 2), (5, 2)],
            [(8, 3), (10, 3), (10, 4)],
            [(0, 0), (5, 2), (2, 2)],
            [(3, 3), (7, 3), (10, 4), (4, 4)],
            [(0, 3), (2, 3), (3, 3), (4, 4), (0, 10)],
            [(0, 2), (2, 2), (2, 3), (0, 3)],
            [(0, 0), (2, 2), (0, 2)],
            [(0, 10), (4, 4), (4, 10)],
        ],
    ),
    "covered_whole": (SQUARE, [[(-1, -1), (11, -1), (11, 11), (-1, 11)]], []),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_ring_is_carved_as_the_tessellator_carves_it(name: str) -> None:
    ring, standing, walks = CASES[name]
    assert open_regions(ring, standing) == walks


def _twice_area(walk: list[Plan]) -> int:
    return sum(
        here[0] * walk[(index + 1) % len(walk)][1] - walk[(index + 1) % len(walk)][0] * here[1]
        for index, here in enumerate(walk)
    )


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_walk_turns_left_with_area_and_the_exact_cuts_keep_the_uncovered_area(
    name: str,
) -> None:
    """Every walk is convex, counter-clockwise and has area; where every cut meets on integer points
    the walks hold exactly the uncovered area, and where one does not they hold at least it."""
    ring, standing, _ = CASES[name]
    for walk in open_regions(ring, standing):
        assert _twice_area(walk) > 0
        for index, here in enumerate(walk):
            before, after = walk[index - 1], walk[(index + 1) % len(walk)]
            turn = (here[0] - before[0]) * (after[1] - here[1]) - (here[1] - before[1]) * (
                after[0] - here[0]
            )
            assert turn >= 0, (name, walk)
    kept = sum(_twice_area(walk) for walk in open_regions(ring, standing))
    exact = {"half_covered": 100, "hole_cut_along_rows": 168, "covered_whole": 0}
    if name in exact:
        assert kept == exact[name]
    if name == "sloped_edge_rounds":
        # The triangle takes 2 x 5.47 square millimetres of the square, so the uncovered part is
        # 189.06 twice over, and a hull that holds it is at least 190.
        assert kept >= 190


def test_the_ring_rule_cuts_the_first_ear_each_time_and_refuses_a_ring_that_turns_clockwise() -> (
    None
):
    assert ring_triangles(SQUARE) == [(3, 0, 1), (1, 2, 3)]
    with pytest.raises(ValueError, match="counter-clockwise"):
        ring_triangles(SQUARE[::-1])
    with pytest.raises(ValueError, match="spike"):
        ring_triangles([(0, 0), (10, 0), (5, 0), (5, 5)])
    with pytest.raises(ValueError, match="counter-clockwise"):
        open_regions(SQUARE, [[(5, 15), (15, 15), (15, -5), (5, -5)]])
