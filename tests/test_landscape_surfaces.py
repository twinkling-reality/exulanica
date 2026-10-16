"""A landscape's walkable surfaces: the ground and each placed volume's tops named, a join found
wherever two surfaces' walkable points lie within a cell on the world plan and the place contract's
step in height, a turned top compared where it falls on that plan, and every top nothing reaches
from the arrival listed as reached only by flight; the same document in every interpreter."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from exulanica.grammar.landform import CELL_MM as LAND_CELL_MM
from exulanica.grammar.landscape import (
    SURFACES_PROFILE,
    LandscapeRefused,
    LandscapeSurfaces,
    compose_volumes,
    landscape_surfaces,
    read_landscape_document,
)
from exulanica.grammar.landscape import surfaces as surfaces_module
from exulanica.grammar.landscape.surfaces import CELL_MM, GROUND, STEP_MM
from exulanica.grammar.stacks import make_sea_stack, read_sea_stack_document
from exulanica.grammar.volumes import TURN_ONE
from exulanica.world.society_place import STEP_LIMIT_MM

ROOT = Path(__file__).resolve().parents[1]
SEED = "landscape surfaces test"
LAND_SEED = "landscape surfaces test land"
#: Level dry land 2 m above the sea's level, with no water.
LEVEL = {"profile": "exulanica.landform/v1", "ground_mm": 2000, "features": []}
#: Land 7 m up falling to a bay along the south edge: sea beyond a beach 6 m south of the world.
SHORE = {
    "profile": "exulanica.landform/v1",
    "ground_mm": 7000,
    "features": [
        {"id": "bay", "kind": "shore", "side": "south", "distance_mm": 6000, "beach_mm": 10000,
         "beach_top_mm": 2000, "sea_depth_mm": 18000, "wander_mm": 8000},
    ],
}  # fmt: skip
GROUND_MM = 2000


def slab(name: str, size_mm: tuple[int, int, int]) -> dict:
    """A sharp, unweathered box: level top ``size_mm[2]`` above its origin, centred across it."""
    return {
        "profile": "exulanica.volume/v1",
        "id": name,
        "parts": [{"id": "body", "shape": "box", "size_mm": list(size_mm)}],
    }


def placed(name: str, volume: dict, at_mm: tuple[int, int, int], yaw_mdeg: int = 0) -> dict:
    return {"id": name, "volume": volume, "at_mm": list(at_mm), "yaw_mdeg": yaw_mdeg}


def shelf(name: str, east_mm: int, north_mm: int, above_ground_mm: int) -> dict:
    """A 10 m square slab whose top stands ``above_ground_mm`` over the level land."""
    return placed(
        name,
        slab(name, (10000, 10000, 1100)),
        (east_mm, north_mm, GROUND_MM + above_ground_mm - 1100),
    )


def surfaces_of(
    *placements: dict, land: dict = LEVEL, arrival_mm: tuple[int, int] | None = None
) -> LandscapeSurfaces:
    landscape = read_landscape_document(
        {
            "profile": "exulanica.landscape/v1",
            "extent_mm": [128000, 128000],
            "land": land,
            "finest_cell_mm": 4000,
            "volumes": list(placements),
        }
    )
    return landscape_surfaces(landscape, compose_volumes(landscape, SEED), LAND_SEED, arrival_mm)


def joined(surfaces: LandscapeSurfaces) -> set[tuple[str, str]]:
    return {join.surfaces for join in surfaces.joins}


def test_the_step_and_the_lattice_are_the_place_contracts_and_the_lands():
    assert STEP_MM == STEP_LIMIT_MM
    assert CELL_MM == LAND_CELL_MM


def test_a_sea_stack_whose_top_stands_far_above_the_water_is_reached_only_by_flight():
    stack = read_sea_stack_document(
        {"profile": "exulanica.sea-stack/v1", "id": "stack", "height_mm": 30000,
         "foot_mm": 18000, "base_radius_mm": 8000, "top_radius_mm": 9000, "walk": "tops"}
    )  # fmt: skip
    volume = make_sea_stack(stack, b"landscape surfaces stack").canonical()
    surfaces = surfaces_of(placed("stack", volume, (64000, -60000, 0)), land=SHORE)
    ground, top = surfaces.surfaces
    assert (ground.surface, top.surface) == (GROUND, "volume:stack/top:0")
    assert top.cells > 50
    assert top.height_mm is not None and top.height_mm[0] >= 25000
    # The ground round its foot is sea, so no ground near it is walked, and nothing joins it.
    assert ground.cells == 0
    assert surfaces.joins == ()
    assert surfaces.reached == (GROUND,)
    assert surfaces.flight_only == ("volume:stack/top:0",)


@pytest.mark.parametrize(("above_mm", "reached"), [(100, True), (180, True), (181, False)])
def test_a_low_shelf_beside_dry_land_is_reached_through_a_ground_join_within_a_step(
    above_mm, reached
):
    surfaces = surfaces_of(shelf("shelf", 50000, 50000, above_mm))
    name = "volume:shelf/top:0"
    assert ((GROUND, name) in joined(surfaces)) is reached
    assert (name in surfaces.reached) is reached
    assert (name in surfaces.flight_only) is not reached
    if reached:
        (join,) = surfaces.joins
        assert join.document()["climb_mm"] == above_mm
        assert join.from_mm[2] == GROUND_MM
        assert join.pairs > 40  # every edge of the shelf, and the land under it


@pytest.mark.parametrize(("step_mm", "reached"), [(150, True), (200, False)])
def test_two_volume_tops_stepping_150_mm_apart_join_and_200_mm_apart_do_not(step_mm, reached):
    # The low shelf joins the ground; the higher one abuts it on the east, too high to join the
    # ground itself, so only a join between the two tops reaches it.
    surfaces = surfaces_of(
        shelf("low", 50000, 50000, 100), shelf("high", 60000, 50000, 100 + step_mm)
    )
    low, high = "volume:low/top:0", "volume:high/top:0"
    assert (GROUND, high) not in joined(surfaces)
    assert ((low, high) in joined(surfaces)) is reached
    assert (high in surfaces.reached) is reached
    if reached:
        join = next(join for join in surfaces.joins if join.surfaces == (low, high))
        assert join.document()["climb_mm"] == step_mm
        # On the face where they meet, from the lowest point of the low shelf within a cell of it.
        assert (join.from_mm[0], join.to_mm[0]) == (55000 - CELL_MM, 55000)


#: A slab 20 m long east to west and 4 m wide, its top 150 mm over the low shelf. Turned a quarter
#: at 15 m north of the shelf's middle, it runs north from the shelf's north edge; unturned, it
#: lies 8 m clear of it.
LONG = placed("long", slab("long", (20000, 4000, 1100)), (50000, 65000, GROUND_MM + 250 - 1100))


def test_a_turned_placements_join_is_found_on_the_world_plan():
    surfaces = surfaces_of(shelf("low", 50000, 50000, 100), {**LONG, "yaw_mdeg": 90000})
    low, long = "volume:low/top:0", "volume:long/top:0"
    join = next(join for join in surfaces.joins if join.surfaces == (low, long))
    # The long slab's south end, turned onto the shelf's north edge, from a cell inside it.
    assert (join.from_mm[1], join.to_mm[1]) == (55000 - CELL_MM, 55000)
    assert 48000 <= join.to_mm[0] <= 52000
    assert long in surfaces.reached
    top = surfaces.surfaces[-1]
    assert (top.at_mm, top.yaw_mdeg) == ((50000, 65000, 1150), 90000)


def test_ignoring_the_turn_misses_the_join(monkeypatch):
    """The mutant: a sheet placed by its origin alone, unturned, lies clear of the shelf."""
    monkeypatch.setattr(surfaces_module, "sin_cos", lambda mdeg: (0, TURN_ONE))
    surfaces = surfaces_of(shelf("low", 50000, 50000, 100), {**LONG, "yaw_mdeg": 90000})
    assert ("volume:low/top:0", "volume:long/top:0") not in joined(surfaces)
    assert surfaces.flight_only == ("volume:long/top:0",)


def test_an_arrival_is_stated_on_walkable_ground_or_refused_by_name():
    on_land = surfaces_of(shelf("shelf", 50000, 50000, 100), arrival_mm=(10500, 10500))
    assert on_land.document()["arrival_mm"] == [10500, 10500]
    assert on_land.reached == (GROUND, "volume:shelf/top:0")
    for arrival in ((60000, -60000), (-500000, 10000)):  # the sea; beyond the land near the world
        with pytest.raises(LandscapeRefused) as caught:
            surfaces_of(shelf("shelf", 50000, 50000, 100), land=SHORE, arrival_mm=arrival)
        assert (caught.value.code, caught.value.path) == (
            "landscape_arrival_not_ground",
            "arrival_mm",
        )


def _turned_bay() -> LandscapeSurfaces:
    """The shelf and a slab turned by a third of a quarter, by the shore."""
    return surfaces_of(
        shelf("low", 50000, 40000, 100),
        {**LONG, "at_mm": [50000, 52000, 7000 + 250 - 1100], "yaw_mdeg": 30000},
        land=SHORE,
    )


_REPLAY = """
import sys
import exulanica
sys.path.insert(0, sys.argv[1])
from test_landscape_surfaces import _turned_bay
print(exulanica.__file__)
print(_turned_bay().sha256)
"""


def test_the_document_and_its_digest_are_the_same_in_every_interpreter():
    surfaces = _turned_bay()
    document = surfaces.document()
    assert document["profile"] == SURFACES_PROFILE
    assert [entry["surface"] for entry in document["surfaces"]] == [
        GROUND,
        "volume:low/top:0",
        "volume:long/top:0",
    ]
    assert json.loads(json.dumps(document)) == document
    assert _turned_bay().sha256 == surfaces.sha256
    for hash_seed in ("1", "4294967295"):
        result = subprocess.run(
            [sys.executable, "-c", _REPLAY, str(ROOT / "tests")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(ROOT)},
            check=False,
        )
        assert result.returncode == 0, result.stderr
        module_path, digest = result.stdout.split()
        assert Path(module_path).resolve().is_relative_to(ROOT), module_path
        assert digest == surfaces.sha256
