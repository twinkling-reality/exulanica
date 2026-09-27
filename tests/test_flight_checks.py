"""The independent flight checker: its positive controls, its independence, and a planted error.

The checker (``exulanica.world.flight_checks``) derives the world it checks from the placed objects
and the catalogs on its own. Its controls come first, so a check that could pass by finding nothing
is shown to find something; then a placement error planted in the flight's own composer, which the
flight agrees with and the checker does not; then the rule that keeps the two apart.
"""

from __future__ import annotations

import ast
import copy
import math
from pathlib import Path

import exulanica.world.flight_checks as checker_module
import pytest
from exulanica.movement import air
from exulanica.movement.fixed import ONE
from exulanica.movement.flight import FLIGHT_MODULE, flight_window
from exulanica.world.flight_checks import (
    _segment_meets_cell,
    check_window,
    check_windows,
)
from exulanica.world.flight_input import _boxes
from exulanica.world.object_catalog import world_object_catalog
from exulanica.world.objects import Transform
from scripts.measure_flight_bounds import compose

from flight_support import (
    DEVELOPMENT_SEEDS,
    check,
    checked_world_of,
    homes,
    seeded,
    square_flight,
    trees_flight,
)

EPISODE = FLIGHT_MODULE.value("episode_steps")
WINDOW = FLIGHT_MODULE.value("max_steps_per_request")
SQUARE = "small_square"


def _episode(flight):
    return [flight_window(flight, start, WINDOW) for start in range(0, EPISODE, WINDOW)]


def _flying_sample(window):
    """The first flyer and step at which it is flying, and not at a window edge."""
    flying = window["states"].index("flying")
    for row in window["flyers"]:
        for index in range(1, len(row["state"]) - 1):
            if row["state"][index] == flying and row["state"][index + 1] == flying:
                return row, index
    raise AssertionError("nobody flies in this window")


def _one(flight, window, before=None):
    return check_window(checked_world_of(SQUARE), homes(flight), window, before=before)


def _rules(check) -> set[str]:
    return {violation["rule"] for violation in check.violations}


def _solid_centre(world):
    """The centre of some solid cell of the checker's own grid that is no perch object's."""
    perched = {perch.object_id for perch in world.perches.values()}
    cell = min(cell for cell, owners in world.solid.items() if not owners & perched)
    low = world.cell_low(cell)
    return [value + world.cell_mm // 2 for value in low]


# -- positive controls ----------------------------------------------------------------------------


def test_a_true_flight_passes_and_a_flyer_placed_in_a_solid_cell_is_found():
    flight = square_flight()
    window = flight_window(flight, 0, WINDOW)
    assert _one(flight, window).violations == []
    planted = copy.deepcopy(window)
    row, index = _flying_sample(planted)
    row["position_mm"][3 * index : 3 * index + 3] = _solid_centre(checked_world_of(SQUARE))
    assert "entered_solid_cell" in _rules(_one(flight, planted))


def test_the_checker_finds_a_jump_and_a_flyer_out_of_its_band():
    flight = square_flight()
    planted = copy.deepcopy(flight_window(flight, 0, WINDOW))
    row, index = _flying_sample(planted)
    x, _y, z = row["position_mm"][3 * index : 3 * index + 3]
    row["position_mm"][3 * index : 3 * index + 3] = [x, flight.volume.ground_mm + 1_000, z]
    assert {"out_of_bounds", "moved_too_far"} <= _rules(_one(flight, planted))


def test_the_exact_segment_test_keeps_a_cell_half_open():
    low, size = (5_000, 5_000, 5_000), 500
    high = [value + size for value in low]
    inside = [value + size // 2 for value in low]
    beside = [high[0] + 10, inside[1], inside[2]]
    # A segment ending exactly on the cell's low face touches it; one ending on its high face
    # does not, because the face belongs to the next cell.
    assert _segment_meets_cell([low[0] - 100, inside[1], inside[2]], low, low, size)
    assert not _segment_meets_cell(beside, [high[0], inside[1], inside[2]], low, size)
    assert _segment_meets_cell(beside, inside, low, size)
    # A segment lying in the cell's high face belongs to the next cell; one in its low face here.
    assert not _segment_meets_cell(
        [high[0], low[1] + 10, inside[2]], [high[0], high[1] - 10, inside[2]], low, size
    )
    assert _segment_meets_cell(
        [low[0], low[1] + 10, inside[2]], [low[0], high[1] - 10, inside[2]], low, size
    )
    # Crossing the cell's high edge diagonally touches only the edge's points, which belong to
    # the neighbouring cells, so the segment never lies in this one.
    assert not _segment_meets_cell(
        [high[0] - 100, high[1] + 100, inside[2]],
        [high[0] + 100, high[1] - 100, inside[2]],
        low,
        size,
    )


def test_the_move_that_joins_two_windows_is_checked_too():
    """A window's first step ends the move from the last window's last step; only a join sees it."""
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[0])
    windows = copy.deepcopy(_episode(flight)[:2])
    assert check(SQUARE, flight, windows).violations == []
    first = windows[1]["from_step"]
    windows[1]["flyers"][0]["position_mm"][0] += 5_000

    def too_far(found):
        return {v["step"] for v in found.violations if v["rule"] == "moved_too_far"}

    assert first not in too_far(_one(flight, windows[1]))
    assert first in too_far(_one(flight, windows[1], before=windows[0]))
    assert first in too_far(check(SQUARE, flight, windows))


def test_the_checker_finds_a_flyer_not_home_when_its_episode_ends():
    """A flyer moved off its perch at an episode's last step is named late, the window is named
    for not saying so, and its jump home into the next episode is a move."""
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[1])
    last = flight_window(flight, EPISODE - WINDOW, WINDOW)
    following = flight_window(flight, EPISODE, WINDOW)
    assert check(SQUARE, flight, [last, following]).violations == []
    planted = copy.deepcopy(last)
    row = planted["flyers"][0]
    end = 3 * (WINDOW - 1)
    home = list(row["position_mm"][end : end + 3])
    # Two metres to the side of home and a metre up, flying: its way home crosses the crown.
    row["position_mm"][end : end + 3] = [home[0] + 2_000, home[1] + 1_000, home[2]]
    row["state"][WINDOW - 1] = planted["states"].index("flying")
    alone = _one(flight, planted)
    assert alone.late_home == 1
    assert {"not_home_at_episode_end", "late_home_misreported"} <= _rules(alone)
    into = _rules(_one(flight, following, before=planted))
    assert {"moved_too_far", "entered_solid_cell"} <= into


def test_a_landing_on_what_no_catalog_declares_a_perch_is_off_column_and_enters_the_solid():
    """A flyer landing straight down onto a bench, which declares no perch: no perch's object is
    spared, so the move into the bench's cells is found as well as the landing off any column."""
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[2])
    world = checked_world_of(SQUARE)
    _object_id, (low, high) = next(part for part in world.parts if "bench" in part[0])
    x, z = (low[0] + high[0]) // 2, (low[2] + high[2]) // 2
    planted = copy.deepcopy(flight_window(flight, 0, WINDOW))
    row = planted["flyers"][0]
    landing = planted["states"].index("landing")
    for index, height in enumerate((1_500, 1_000, 500, high[1])):
        row["position_mm"][3 * index : 3 * index + 3] = [x, high[1] + height, z]
        row["state"][index] = landing
    found = _rules(_one(flight, planted))
    assert {"off_column", "entered_solid_cell", "body_meets_solid"} <= found


def test_the_checker_finds_a_body_touching_a_part():
    """A flying flyer a hand's width from a crown's side, its point clear of every part but its
    body not, is found."""
    flight = square_flight()
    world = checked_world_of(SQUARE)
    window = copy.deepcopy(flight_window(flight, 0, WINDOW))
    _object_id, (low, high) = max(
        (part for part in world.parts if "tree" in part[0]), key=lambda part: part[1][1][1]
    )
    half = math.ceil(world.kinds["small_bird"]["body_span_mm"] / 2)
    point = [high[0] + half // 2, (low[1] + high[1]) // 2, (low[2] + high[2]) // 2]
    row, index = _flying_sample(window)
    row["position_mm"][3 * index : 3 * index + 3] = point
    row["position_mm"][3 * index + 3 : 3 * index + 6] = point
    assert "body_meets_solid" in _rules(_one(flight, window))


def test_a_perching_flyer_a_few_millimetres_off_its_point_is_found():
    flight = square_flight()
    window = copy.deepcopy(flight_window(flight, 0, WINDOW))
    row = window["flyers"][0]
    assert window["states"][row["state"][0]] == "perching"
    # Three millimetres above its perch: still on the perch's column, not on its point.
    row["position_mm"][1] += 3
    assert _rules(_one(flight, window)) >= {"perched_off_point"}
    # Three millimetres across: on no perch's column at all.
    row["position_mm"][1] -= 3
    row["position_mm"][0] += 3
    assert {"off_column", "genesis_not_home"} <= _rules(_one(flight, window))


def test_a_home_no_catalog_declares_is_named():
    flight = square_flight()
    window = flight_window(flight, 0, 2)
    named = {**homes(flight), flight.flyers[0].flyer_id: "nowhere:perch:0"}
    found = check_window(checked_world_of(SQUARE), named, window)
    assert "home_not_declared" in _rules(found)


# -- a placement error the flight agrees with and the checker does not ----------------------------


def test_a_part_the_flight_places_wrongly_is_found_here_and_agreed_with_by_the_flight(monkeypatch):
    """Plant an error in the flight's own placement: parts and perches are not turned by their
    object's yaw. The flight composes, flies and agrees with itself (every flying point in a free
    cell of its own grid, every other on one of its own perch columns, nobody late), and the
    checker, placing the same objects on its own, finds birds perching where no tree has a perch."""
    world = checked_world_of("eight_trees")
    assert check("eight_trees", trees_flight(), _episode(trees_flight())[:1]).violations == []
    monkeypatch.setattr(air, "turn", lambda yaw_microradians: (ONE, 0))
    planted = compose("eight_trees")
    assert planted.occupancy.sha256 != trees_flight().occupancy.sha256
    windows = _episode(planted)
    points = {tuple(perch.point_mm) for perch in planted.perches}
    for window in windows:
        assert window["late_home"] == []
        for row in window["flyers"]:
            for index, code in enumerate(row["state"]):
                position = tuple(row["position_mm"][3 * index : 3 * index + 3])
                if window["states"][code] == "flying":
                    assert not planted.occupancy.is_solid(planted.volume.cell_of(position))
                else:
                    assert any(p[0] == position[0] and p[2] == position[2] for p in points)
    found = check_windows(world, homes(planted), windows)
    assert {"genesis_not_home", "off_column"} <= _rules(found)


# -- independence ---------------------------------------------------------------------------------

#: What the checker may import from this package, and nothing else: the module table's data, the
#: flight kind catalog's location, the object catalog, the meshes the renderer draws, and the
#: placed object's type. Neither the flight's air, arithmetic, step, episodes, worker nor composer.
ALLOWED = {
    "exulanica.movement.registry": {"FLIGHT", "movement_module"},
    "exulanica.world.flight_kinds": {"CATALOG_DIRECTORY", "CATALOG_ID", "CATALOG_VERSION"},
    "exulanica.world.object_catalog": {
        "MarkerRecipe",
        "WorldObjectCatalog",
        "world_object_catalog",
    },
    "exulanica.world.object_meshes": {"parts_extent"},
    "exulanica.world.objects": {"AuthoredObject"},
}


def test_the_checker_imports_nothing_of_the_flight():
    tree = ast.parse(Path(checker_module.__file__).read_text(encoding="utf-8"))
    imported: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.setdefault(alias.name, set())
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.setdefault(node.module, set()).update(alias.name for alias in node.names)
    ours = {module: names for module, names in imported.items() if module.startswith("exulanica")}
    assert set(ours) <= set(ALLOWED), sorted(set(ours) - set(ALLOWED))
    for module, names in ours.items():
        assert names <= ALLOWED[module], (module, sorted(names - ALLOWED[module]))


# -- the two placements agree where both are right ------------------------------------------------

YAWS = tuple(range(0, 6_283_185, 6_283_185 // 48))
SCALES = (250, 1000, 1600)


@pytest.mark.parametrize("scale", SCALES, ids=[f"scale_{scale}" for scale in SCALES])
def test_both_placements_put_every_perch_within_a_millimetre_and_the_flight_covers_every_part(
    scale,
):
    """Every catalog kind at every yaw of a sweep: the flight's placed perch point is the
    checker's to within the millimetre it rounds to, and the flight's box of each part holds the
    checker's box of what is drawn, so the flight's air covers everything drawn."""
    for kind in world_object_catalog().kinds:
        for yaw in YAWS:
            transform = Transform(1_234, 250, -5_678, yaw, scale)
            placement = air.Placement(1_234, 250, -5_678, yaw, scale)
            for perch in kind.perches:
                ours = air.placed_point(perch.position_mm, placement)
                theirs = checker_module._placed(perch.position_mm, transform)
                assert all(abs(a - b) <= 1 for a, b in zip(ours, theirs, strict=True)), kind.key
            boxes = _boxes(kind)
            drawn = checker_module._part_boxes(kind, transform, (0, 0, 0))
            assert len(boxes) == len(drawn)
            for box, (low, high) in zip(boxes, drawn, strict=True):
                flight_low, flight_high = air._solid_bounds(air.Solid("x", box, placement))
                assert all(a <= b for a, b in zip(flight_low, low, strict=True)), kind.key
                assert all(a >= b for a, b in zip(flight_high, high, strict=True)), kind.key
