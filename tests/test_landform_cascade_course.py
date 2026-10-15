"""A cascade's course: equal falls as before, or falls that follow the land.

On its ``follow`` course a cascade reads the land along its middle and falls where the land falls,
so no pool stands far above the land along its middle, and its last fall pours off the shore at
the waterline. Its ``equal`` course is the cascade every land made before courses existed states,
and reads exactly as it did. The land is the realizer tests' cascade land, written here as data.
"""

from __future__ import annotations

from itertools import pairwise

import pytest
from exulanica.grammar.landform import (
    CELL_MM,
    LandformRefused,
    height_at,
    landform_catalog,
    read_land_document,
    realize_region,
    water_bodies,
)
from exulanica.grammar.landform.document import PROFILE

from test_landform_realize import CASCADE_FEATURES, FALLS, FRAME, _holds, cascade_land

FOLLOW = {**FALLS, "course": "follow"}


def _channel(land, falls: dict) -> tuple[int, list[tuple[int, int]]]:  # type: ignore[no-untyped-def]
    """The channel's middle as east and each north it crosses, for a cascade running south: the
    world's middle less its offset, from its source to its end, one cell apart."""
    x = FRAME.width_mm // 2 + falls["offset_mm"]
    top = FRAME.depth_mm // 2 - falls["from_mm"]
    bottom = FRAME.depth_mm // 2 - falls["to_mm"]
    return x, [(x, y) for y in range(top, bottom - 1, -CELL_MM)]


def _bodies(land) -> tuple[list, list]:  # type: ignore[no-untyped-def]
    bodies = [body for body in water_bodies(land, FRAME) if body.id.startswith("falls")]
    return [b for b in bodies if b.kind == "pool"], [b for b in bodies if b.kind == "fall"]


def _lips(before, x: int, pools) -> list[int]:  # type: ignore[no-untyped-def]
    """How far each pool's water stands above the land before the cascade, cell by cell along its
    middle: what its lip must hold."""
    found = []
    for pool in pools:
        _x0, y0, _x1, y1 = pool.rect_mm
        for y in range(y1 // CELL_MM * CELL_MM, y0, -CELL_MM):
            found.append(pool.level_mm - height_at(before, FRAME, x, y))
    return found


def test_a_following_cascade_falls_where_the_land_falls_and_into_the_sea_at_the_shore() -> None:
    land, before = cascade_land(FOLLOW), cascade_land()
    pools, falls = _bodies(land)
    assert len(pools) == len(falls) >= 2, "it ends in the sea: every pool falls, the last into it"
    levels = [pool.level_mm for pool in pools]
    assert all(a > b for a, b in pairwise(levels))
    x, middle = _channel(land, FOLLOW)
    ground = {y: height_at(before, FRAME, x, y) for _, y in middle}
    freeboard, least_fall, step = 300, 1000, 3000
    for i, fall in enumerate(falls):
        assert 0 < fall.level_mm - fall.bottom_mm <= step, "no fall higher than the step"
        assert fall.bottom_mm == (levels[i + 1] if i + 1 < len(levels) else 0)
    for fall in falls[:-1]:
        # A fall stands where the land has fallen the least fall below the water above it.
        assert ground[fall.rect_mm[1]] - freeboard <= fall.level_mm - least_fall
    # The last fall pours off the shore: the land there is the sea's, a cell before it is dry.
    shore = falls[-1].rect_mm[1]
    assert ground[shore] <= 0 < ground[shore + CELL_MM]
    near = realize_region(land, FRAME, -40_000, -128_000, 20_000, 200_000)
    for pool in pools:
        _holds(near, pool)


def test_a_following_cascade_holds_its_pools_without_walls_an_equal_one_raises() -> None:
    before = cascade_land()
    x, _middle = _channel(before, FOLLOW)
    followed = _lips(before, x, _bodies(cascade_land(FOLLOW))[0])
    equal = _lips(before, x, _bodies(cascade_land(FALLS))[0])
    # Past its freeboard a following pool stands at most its least fall above the land along its
    # middle, but within a pool's least length of where it began, where it could not yet fall.
    assert max(followed) < max(equal)
    assert sorted(followed)[len(followed) * 9 // 10] <= 1000 + 300


def test_an_equal_course_is_the_cascade_every_earlier_land_states() -> None:
    raw = {"profile": PROFILE, "ground_mm": 8000, "features": [*CASCADE_FEATURES, FALLS]}
    earlier = read_land_document(raw, landform_catalog(2))
    stated = read_land_document(
        {**raw, "features": [*CASCADE_FEATURES, {**FALLS, "course": "equal"}]}
    )
    assert [b.document() for b in water_bodies(stated, FRAME)] == [
        b.document() for b in water_bodies(earlier, FRAME)
    ]
    one = realize_region(earlier, FRAME, -30_000, -60_000, 0, 60_000)
    other = realize_region(stated, FRAME, -30_000, -60_000, 0, 60_000)
    assert list(one.samples()) == list(other.samples())


def test_a_following_cascade_on_land_that_never_falls_is_refused_by_name() -> None:
    flat = read_land_document(
        {
            "profile": PROFILE,
            "ground_mm": 6000,
            "features": [{**FOLLOW, "from_mm": -60_000, "to_mm": -10_000}],
        }
    )
    with pytest.raises(LandformRefused) as caught:
        water_bodies(flat, FRAME)
    assert caught.value.code == "landform_cascade_rises"
