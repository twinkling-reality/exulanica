"""A town on its land: level junctions, streets within the step their people walk, every lot
level at its own door, and level land graded to level ground exactly."""

from __future__ import annotations

import dataclasses
import functools
from itertools import pairwise

import pytest
from exulanica.grammar.grammars.city.land import (
    ROUNDING_MARGIN_MM,
    TownGrading,
    grade_town,
    town_frame,
    town_grading_plan,
)
from exulanica.grammar.grammars.city.streets import CurbEdgeRecord
from exulanica.grammar.landform import (
    BANK_GRADE_PERMILLE,
    CELL_MM,
    CUT_FILL_MOST_MM,
    LandformRefused,
    land_recipes,
    read_land_document,
    realize_near,
)
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.society_living import town_routine
from exulanica.world.society_place import STEP_LIMIT_MM
from exulanica.world.world_recipes import town_recipe

SEED = "e" * 64
#: The town's figures as their sources state them: the routine's station spacing, the place
#: contract's step, and the land's bank grade and cut and fill bound.
FIGURES = TownGrading(
    station_mm=town_routine().policy["footway_station_spacing_mm"],
    step_mm=STEP_LIMIT_MM,
    bank_grade_permille=BANK_GRADE_PERMILLE,
    cut_fill_most_mm=CUT_FILL_MOST_MM,
)
SWELL = read_land_document(
    {
        "profile": "exulanica.landform/v1",
        "ground_mm": 8000,
        "features": [
            {"id": "tilt", "kind": "tilt", "side": "north", "grade_permille": 30},
            {"id": "swell", "kind": "undulation", "amplitude_mm": 1500, "wavelength_mm": 80000},
        ],
    }
)


@functools.cache
def town(name: str = "small_town"):  # type: ignore[no-untyped-def]
    world = compose_generated_world(town_recipe(name), f"world:generated:city-land-{name}")
    return world.records, tuple(world.receipt["arrival"]["position_mm"])


def graded(land=SWELL, name: str = "small_town", figures: TownGrading = FIGURES):  # type: ignore[no-untyped-def]
    records, arrival = town(name)
    return grade_town(land, records, SEED, arrival, figures)


def _inside(rect, x: int, y: int) -> bool:  # type: ignore[no-untyped-def]
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def test_level_land_grades_to_level_ground_exactly() -> None:
    level = read_land_document(
        {"profile": "exulanica.landform/v1", "ground_mm": 6000, "features": []}
    )
    land = graded(level)
    assert set(land.near.heights) == {6000}
    assert {height for _, height in land.pads} == {6000}
    assert land.report["max_cut_mm"] == land.report["max_fill_mm"] == 0


def test_every_junction_and_lot_is_level_and_every_street_climbs_within_its_grade() -> None:
    records, arrival = town()
    near = realize_near(SWELL, town_frame(records, SEED))
    plan = town_grading_plan(records, arrival, FIGURES, near)
    land = grade_town(SWELL, records, SEED, arrival, FIGURES)
    levels = dict(land.pads)
    streets = [corridor.rect_mm for corridor in plan.corridors]
    junctions = [pad for pad in plan.pads if pad.id.startswith("junction")]
    lots = [pad for pad in plan.pads if pad.id.startswith("lot")]
    assert junctions and lots and land.report["max_cut_mm"] > 0, "the land is not level"
    samples = list(land.near.samples())
    for pad in junctions:
        assert {h for x, y, h in samples if _inside(pad.rect_mm, x, y)} == {pad.level_mm}
    for pad in lots:
        # A lot stands level at its door's height, but for its cells under a street or a junction,
        # which keep theirs.
        own = {
            h
            for x, y, h in samples
            if _inside(pad.rect_mm, x, y)
            and not any(_inside(rect, x, y) for rect in streets)
            and not any(_inside(j.rect_mm, x, y) for j in junctions)
        }
        assert own == {levels[pad.id]}, pad.id
        assert levels[pad.id] == land.near.at(*pad.door_mm)
    for corridor in plan.corridors:
        x0, y0, x1, y1 = corridor.rect_mm
        if corridor.axis == "x":
            y = (y0 + y1) // 2 // CELL_MM * CELL_MM
            line = [land.near.at(x, y) for x in range(-(-x0 // CELL_MM) * CELL_MM, x1 + 1, CELL_MM)]
        else:
            x = (x0 + x1) // 2 // CELL_MM * CELL_MM
            line = [land.near.at(x, y) for y in range(-(-y0 // CELL_MM) * CELL_MM, y1 + 1, CELL_MM)]
        steepest = max(abs(b - a) for a, b in pairwise(line))
        assert steepest <= corridor.grade_permille * CELL_MM // 1000, corridor.id


def _along(land, x: int, y: int, along_y: bool) -> int:  # type: ignore[no-untyped-def]
    """The graded land at a point of a kerb line, read between the two lattice samples either
    side of it along the kerb (a street is level across, so the cross axis is floored)."""
    if along_y:
        low, x = y // CELL_MM * CELL_MM, x // CELL_MM * CELL_MM
        a, b = land.near.at(x, low), land.near.at(x, low + CELL_MM)
        return a + (b - a) * (y - low) // CELL_MM
    low, y = x // CELL_MM * CELL_MM, y // CELL_MM * CELL_MM
    a, b = land.near.at(low, y), land.near.at(low + CELL_MM, y)
    return a + (b - a) * (x - low) // CELL_MM


def test_every_footway_station_edge_climbs_no_more_than_one_step() -> None:
    records, _arrival = town()
    land = graded()
    for curb in (r for r in records if isinstance(r, CurbEdgeRecord)):
        (ax, ay, _), (bx, by, _) = curb.kerb_line_mm[0], curb.kerb_line_mm[-1]
        length = abs(bx - ax) + abs(by - ay)
        count = max(1, length // FIGURES.station_mm)
        stations = [
            _along(land, ax + (bx - ax) * i // count, ay + (by - ay) * i // count, ax == bx)
            for i in range(count + 1)
        ]
        assert max(abs(b - a) for a, b in pairwise(stations)) <= FIGURES.step_mm, curb.identity


@pytest.mark.parametrize("key", ["coast", "lakeside", "valley", "upland", "hillside", "rolling"])
def test_a_small_town_takes_every_land_recipe(key: str) -> None:
    recipe = next(recipe for recipe in land_recipes() if recipe.key == key)
    land = graded(read_land_document(dict(recipe.land)))
    bound = (FIGURES.step_mm - ROUNDING_MARGIN_MM) * 1000 // FIGURES.station_mm
    assert 0 < land.report["max_corridor_grade_permille"] <= bound


def test_the_street_grade_is_the_caller_s_figure_and_steep_land_is_refused_by_name() -> None:
    records, arrival = town()
    near = realize_near(SWELL, town_frame(records, SEED))
    wider = dataclasses.replace(FIGURES, station_mm=2 * FIGURES.station_mm)
    narrow = {
        c.id: c.grade_permille for c in town_grading_plan(records, arrival, FIGURES, near).corridors
    }
    wide = {
        c.id: c.grade_permille for c in town_grading_plan(records, arrival, wider, near).corridors
    }
    assert all(wide[key] < narrow[key] for key in narrow), "stations further apart allow less"
    steep = read_land_document(
        {
            "profile": "exulanica.landform/v1",
            "ground_mm": 20000,
            "features": [
                {"id": "tilt", "kind": "tilt", "side": "north", "grade_permille": 120},
                {"id": "swell", "kind": "undulation", "amplitude_mm": 6000, "wavelength_mm": 40000},
            ],
        }
    )
    with pytest.raises(LandformRefused) as caught:
        graded(steep)
    assert caught.value.code.startswith("landform_")
