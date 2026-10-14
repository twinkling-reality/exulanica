"""Grading: what a layout does to the land so it can stand on it and walk it."""

from __future__ import annotations

import pytest
from exulanica.grammar.landform import (
    CELL_MM,
    PROFILE,
    Basin,
    Corridor,
    GradingPlan,
    LandformRefused,
    Pad,
    WorldFrame,
    grade_land,
    read_land_document,
    realize_region,
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
