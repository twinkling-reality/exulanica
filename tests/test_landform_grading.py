"""Grading: what a layout does to the land so it can stand on it and walk it."""

from __future__ import annotations

from dataclasses import replace

import pytest
from exulanica.grammar.landform import (
    CELL_MM,
    PROFILE,
    Basin,
    Corridor,
    GradingPlan,
    LandformRefused,
    NearLand,
    Pad,
    RetainingWall,
    WorldFrame,
    grade_land,
    read_land_document,
    realize_region,
    water_bodies,
)

FRAME = WorldFrame(width_mm=60_000, depth_mm=60_000, seed="e" * 64)


def land(*features: dict, ground_mm: int = 6000):
    return read_land_document(
        {"profile": PROFILE, "ground_mm": ground_mm, "features": list(features)}
    )


SLOPE = land({"id": "tilt", "kind": "tilt", "side": "north", "grade_permille": 60})
STEEP = land({"id": "tilt", "kind": "tilt", "side": "north", "grade_permille": 120})


def region(document=SLOPE):
    return realize_region(document, FRAME, -10_000, -10_000, 70_000, 70_000)


SPINE = Corridor(id="spine", rect_mm=(28_000, 0, 32_000, 60_000), axis="y", grade_permille=40)


def plan(**changes) -> GradingPlan:
    base = dict(corridors=(SPINE,), pads=(), basins=(), entry_mm=(30_000, 0))
    base.update(changes)
    return GradingPlan(**base)


def test_a_corridor_never_climbs_faster_than_its_grade_and_is_level_across():
    graded = grade_land(region(), plan())
    for y in range(0, 60_000, CELL_MM):
        across = {graded.near.at(x, y) for x in range(28_000, 32_001, CELL_MM)}
        assert len(across) == 1, y
        assert abs(graded.near.at(30_000, y + CELL_MM) - graded.near.at(30_000, y)) <= 40
    # The land rises at 60 per mille, the corridor at 40 at most, so it cuts in toward the top.
    assert graded.near.at(30_000, 60_000) < region().at(30_000, 60_000)
    assert graded.report["max_corridor_grade_permille"] <= 40


def test_crossing_corridors_share_their_crossing():
    cross = Corridor(id="cross", rect_mm=(0, 28_000, 60_000, 32_000), axis="x", grade_permille=40)
    graded = grade_land(region(), plan(corridors=(SPINE, cross)))
    level = graded.near.at(30_000, 30_000)
    assert {graded.near.at(x, 30_000) for x in range(28_000, 32_001, CELL_MM)} == {level}
    for x in range(0, 60_000, CELL_MM):
        assert abs(graded.near.at(x + CELL_MM, 30_000) - graded.near.at(x, 30_000)) <= 40


def test_a_pad_is_level_at_its_door_on_the_path_and_banked_into_the_land():
    hall = Pad(id="hall", rect_mm=(10_000, 20_000, 26_000, 36_000), door_mm=(28_000, 28_000))
    graded = grade_land(region(), plan(pads=(hall,)))
    [(pad_id, level)] = graded.pads
    assert pad_id == "hall" and level == graded.near.at(28_000, 28_000)
    assert {
        graded.near.at(x, y)
        for x in range(10_000, 26_001, CELL_MM)
        for y in range(20_000, 36_001, CELL_MM)
    } == {level}
    # Around the pad no bank is steeper than the bank grade (1 in 2 by default).
    for x in range(2_000, 10_000, CELL_MM):
        assert abs(graded.near.at(x + CELL_MM, 28_000) - graded.near.at(x, 28_000)) <= 500


def test_a_corridor_that_cannot_join_two_levels_within_its_grade_is_refused_by_name():
    top = Pad(id="top", rect_mm=(28_000, 0, 32_000, 2_000), level_mm=8000)
    foot = Pad(id="foot", rect_mm=(28_000, 56_000, 32_000, 60_000), level_mm=4000)
    gentle = Corridor(id="ramp", rect_mm=(28_000, 0, 32_000, 60_000), axis="y", grade_permille=10)
    with pytest.raises(LandformRefused) as caught:
        grade_land(region(), plan(pads=(top, foot), corridors=(gentle,)))
    assert caught.value.code == "landform_corridor_too_steep"
    assert "ramp" in caught.value.detail and "10" in caught.value.detail


def test_a_cut_deeper_than_the_bound_is_refused_with_the_figure():
    flat_path = Corridor(
        id="spine", rect_mm=(28_000, 0, 32_000, 60_000), axis="y", grade_permille=1
    )
    with pytest.raises(LandformRefused) as caught:
        grade_land(region(STEEP), plan(corridors=(flat_path,), cut_fill_most_mm=3000))
    assert caught.value.code == "landform_cut_too_deep"
    assert "spine" in caught.value.detail and "3000" in caught.value.detail


def test_two_pads_closer_than_a_bank_allows_are_parted_by_a_wall():
    low = Pad(id="low", rect_mm=(10_000, 10_000, 20_000, 20_000), level_mm=6000)
    high = Pad(id="high", rect_mm=(22_000, 10_000, 26_000, 20_000), level_mm=9000)
    graded = grade_land(region(), plan(pads=(low, high), corridors=(), entry_mm=(15_000, 15_000)))
    assert graded.walls, "a 3 m step over 2 m needs a wall"
    # Walls stand in the gap and round the corners where the two pads meet, nowhere else.
    assert all(
        17_000 <= wall.x_mm <= 25_000 and 7_000 <= wall.y_mm <= 23_000 for wall in graded.walls
    )
    in_gap = [
        wall for wall in graded.walls if wall.x_mm == 21_000 and 10_000 <= wall.y_mm <= 20_000
    ]
    assert len(in_gap) == 11 and min(wall.height_mm for wall in in_gap) >= 2000


def test_a_pond_is_carved_below_its_level_which_is_its_rim_less_the_freeboard():
    pond = Basin(
        id="pond",
        rect_mm=(36_000, 36_000, 56_000, 52_000),
        depth_mm=2500,
        shelf_mm=2000,
        freeboard_mm=300,
    )
    graded = grade_land(region(), plan(basins=(pond,)))
    [water] = graded.water
    assert water.id == "pond" and water.kind == "pond"
    wet = [
        (x, y)
        for x, y, h in graded.near.samples()
        if 36_000 <= x <= 56_000 and 36_000 <= y <= 52_000 and h < water.level_mm
    ]
    assert len(wet) > 100
    assert min(graded.near.at(x, y) for x, y in wet) <= water.level_mm - 2000
    # The water holds: every dry sample beside a wet one stands at or above the water's level.
    wet_set = set(wet)
    for x, y in wet:
        for side in ((x + CELL_MM, y), (x - CELL_MM, y), (x, y + CELL_MM), (x, y - CELL_MM)):
            if side not in wet_set:
                assert graded.near.at(*side) >= water.level_mm, side


def test_every_door_must_be_reachable_from_the_entry():
    # A pad raised 6 m with no path to it: its banks are steeper than open ground is walked.
    tower = Pad(
        id="tower",
        rect_mm=(10_000, 40_000, 16_000, 46_000),
        level_mm=13_000,
        door_mm=(13_000, 40_000),
    )
    with pytest.raises(LandformRefused) as caught:
        grade_land(region(land(ground_mm=6000)), plan(pads=(tower,)))
    assert caught.value.code == "landform_unreachable" and "tower" in caught.value.detail
    over = Basin(
        id="moat",
        rect_mm=(26_000, 20_000, 34_000, 30_000),
        depth_mm=2000,
        shelf_mm=1000,
        freeboard_mm=300,
    )
    with pytest.raises(LandformRefused) as caught:
        grade_land(region(), plan(basins=(over,)))
    assert caught.value.code == "landform_basin_over_locked" and "moat" in caught.value.detail


def test_grading_is_deterministic_and_never_changes_the_land_it_was_given():
    before = region()
    heights = list(before.heights)
    hall = Pad(id="hall", rect_mm=(10_000, 20_000, 26_000, 36_000), door_mm=(28_000, 28_000))
    first = grade_land(before, plan(pads=(hall,)))
    second = grade_land(before, plan(pads=(hall,)))
    assert first.near.heights == second.near.heights and first.walls == second.walls
    assert list(before.heights) == heights


FLAT = land()


def _seam(upper_mm: int):
    """Two pads side by side on level land, one row apart: the south one at the land's level, the
    north one ``upper_mm`` above it."""
    low = Pad(id="low", rect_mm=(10_000, 10_000, 20_000, 20_000), level_mm=6000)
    high = Pad(id="high", rect_mm=(10_000, 21_000, 20_000, 30_000), level_mm=6000 + upper_mm)
    return plan(pads=(low, high), corridors=(), entry_mm=(15_000, 15_000), retaining_walls=True)


def test_two_pads_meeting_at_levels_a_bank_cannot_join_list_one_retaining_wall():
    graded = grade_land(region(FLAT), _seam(1200))
    assert graded.retaining == (
        RetainingWall(from_mm=(10_000, 20_000), to_mm=(20_000, 20_000), high="north"),
    ), "one run on the low pad's edge, the land rising north to the upper pad"
    assert grade_land(region(FLAT), _seam(400)).retaining == (), "a bank's step lists none"
    assert graded.retaining[0].document() == {
        "from_mm": [10_000, 20_000],
        "to_mm": [20_000, 20_000],
        "high": "north",
    }


def test_a_pad_meeting_a_sloping_corridor_lists_a_wall_only_where_the_difference_passes_a_bank():
    yard = Pad(id="yard", rect_mm=(16_000, 10_000, 27_000, 50_000), door_mm=(30_000, 30_000))
    graded = grade_land(region(), plan(pads=(yard,), retaining_walls=True))
    near = graded.near
    seam = [w for w in graded.retaining if w.from_mm[0] in (27_000, 28_000)]
    walled = {
        (wall.from_mm[0], y)
        for wall in seam
        for y in range(wall.from_mm[1], wall.to_mm[1] + 1, CELL_MM)
    }
    assert {wall.high for wall in seam} == {"east", "west"}, "the path climbs past the yard's level"
    for y in range(10_000, 50_001, CELL_MM):
        yard_side, path_side = near.at(27_000, y), near.at(28_000, y)
        low_line = 27_000 if yard_side < path_side else 28_000
        assert ((low_line, y) in walled) == (abs(path_side - yard_side) > 500), y
    for wall in seam:
        assert wall.from_mm[0] == wall.to_mm[0] and wall.from_mm[1] < wall.to_mm[1]
        assert wall.high == ("east" if wall.from_mm[0] == 27_000 else "west")


def test_a_pond_carved_into_its_pad_lists_no_retaining_wall():
    yard = Pad(
        id="yard",
        rect_mm=(4_000, 20_000, 26_000, 40_000),
        door_mm=(28_000, 30_000),
        water_allowed=True,
    )
    pond = Basin(
        id="pond", rect_mm=(8_000, 24_000, 22_000, 36_000), depth_mm=2500, shelf_mm=2000,
        freeboard_mm=300,
    )  # fmt: skip
    graded = grade_land(region(FLAT), plan(pads=(yard,), basins=(pond,), retaining_walls=True))
    assert min(graded.near.at(x, 30_000) for x in range(8_000, 22_001, CELL_MM)) < 4000
    assert graded.retaining == ()


@pytest.mark.parametrize("which", ["seam", "path"])
def test_retaining_walls_move_no_height_and_none_are_listed_unless_asked(which: str):
    yard = Pad(id="yard", rect_mm=(16_000, 10_000, 27_000, 50_000), door_mm=(30_000, 30_000))
    asked = _seam(1200) if which == "seam" else plan(pads=(yard,), retaining_walls=True)
    near = region(FLAT) if which == "seam" else region()
    on = grade_land(near, asked)
    off = grade_land(near, replace(asked, retaining_walls=False))
    assert on.retaining and off.retaining is None
    assert on.near.heights == off.near.heights
    assert (on.pads, on.water, on.walls, on.report) == (off.pads, off.water, off.walls, off.report)


# Water stepping east down the slope's foot, clear of the spine at x 28 to 32 m.
CASCADE = land(
    {"id": "tilt", "kind": "tilt", "side": "north", "grade_permille": 60},
    {"id": "falls", "kind": "cascade", "side": "south", "offset_mm": -18_000,
     "from_mm": -60_000, "to_mm": 0, "step_mm": 1000, "width_mm": 4000},
)  # fmt: skip


def test_a_layout_beside_a_cascade_grades_and_its_pools_stay_held():
    water = water_bodies(CASCADE, FRAME)
    assert {body.kind for body in water} == {"pool", "fall"}
    graded = grade_land(region(CASCADE), plan(), water=water)
    for pool in (body for body in water if body.kind == "pool"):
        x0, y0, x1, y1 = pool.rect_mm
        wet = [
            (x, y)
            for x, y, h in graded.near.samples()
            if x0 <= x <= x1 and y0 <= y <= y1 and h < pool.level_mm
        ]
        assert wet, pool.id


def test_a_layout_crossing_a_cascade_is_refused_by_name():
    water = water_bodies(CASCADE, FRAME)
    yard = Pad(id="yard", rect_mm=(4_000, 20_000, 26_000, 36_000), door_mm=(28_000, 28_000))
    with pytest.raises(LandformRefused) as caught:
        grade_land(region(CASCADE), plan(pads=(yard,)), water=water)
    assert caught.value.code == "landform_cascade_crossed" and "yard" in str(caught.value)


def _hill(grade_permille: int) -> NearLand:
    """Level ground at 6 m, and north of y = 40 m a hill climbing at ``grade_permille``, steeper
    than a bank: a terrace below it banks into it more the further the bank runs."""
    xs, ys = range(-10_000, 70_001, CELL_MM), range(-10_000, 70_001, CELL_MM)
    heights = tuple(6000 + max(0, y - 40_000) * grade_permille // 1000 for y in ys for _x in xs)
    return NearLand(-10_000, -10_000, len(xs), len(ys), heights)


TERRACE = Pad(id="terrace", rect_mm=(20_000, 20_000, 40_000, 40_000), level_mm=6000)


def _terrace(held_most_mm: int) -> GradingPlan:
    return GradingPlan(
        pads=(TERRACE,), entry_mm=(30_000, 30_000), held_most_mm=held_most_mm, retaining_walls=True
    )


def test_a_terrace_under_a_hill_steeper_than_its_bank_stands_in_a_wall_instead_of_refused():
    near = _hill(800)
    with pytest.raises(LandformRefused) as refused:
        grade_land(near, _terrace(0))
    assert refused.value.code == "landform_cut_too_deep" and "terrace" in str(refused.value)
    graded = grade_land(near, _terrace(3000))
    assert graded.pads == (("terrace", 6000),), "the terrace stands at its own level"
    assert max(abs(g - n) for g, n in zip(graded.near.heights, near.heights, strict=True)) <= 8000
    assert graded.retaining is not None
    assert RetainingWall(from_mm=(20_000, 40_000), to_mm=(40_000, 40_000), high="north") in (
        graded.retaining
    ), "the wall stands along the terrace's north edge"
    assert graded.near.at(30_000, 41_000) == near.at(30_000, 41_000), "the land behind it stays"


def test_a_terrace_holds_no_more_than_the_most_a_wall_holds():
    with pytest.raises(LandformRefused) as refused:
        grade_land(_hill(900), _terrace(3000))
    assert refused.value.code == "landform_cut_too_deep"


def test_a_corridor_holds_no_wall():
    # On the steep slope a bank of 60 per mille from the spine fills past 2.5 m beside it.
    gentle = plan(bank_grade_permille=60, cut_fill_most_mm=2500, held_most_mm=3000)
    with pytest.raises(LandformRefused) as refused:
        grade_land(region(STEEP), gentle)
    assert refused.value.code == "landform_cut_too_deep" and "spine" in str(refused.value)


@pytest.mark.parametrize("which", ["hill", "slope"])
def test_a_plan_within_the_bound_grades_the_same_land_whether_or_not_a_wall_could_be_held(
    which: str,
):
    yard = Pad(id="yard", rect_mm=(16_000, 10_000, 27_000, 50_000), door_mm=(30_000, 30_000))
    near = _hill(700) if which == "hill" else region()
    asked = _terrace(0) if which == "hill" else plan(pads=(yard,), retaining_walls=True)
    assert grade_land(near, asked) == grade_land(near, replace(asked, held_most_mm=3000))
