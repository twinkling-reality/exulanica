"""Realizing land: one pure integer function, sampled in chunks on the city's tile grid and out to
the horizon in a drawn-only backdrop."""

from __future__ import annotations

import hashlib
from fractions import Fraction
from itertools import pairwise

import pytest
from exulanica.canonical import canonical_json
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city import terrain
from exulanica.grammar.grammars.city.common import MILLIONTHS, TILE_SIZE_MM, tile_ordinal
from exulanica.grammar.landform import (
    CELL_MM,
    CHUNK_MM,
    NEAR_BOUND_MM,
    PROFILE,
    SAMPLES_PER_SIDE,
    LandformRefused,
    WorldFrame,
    height_at,
    land_heights,
    landform_catalog,
    level_land,
    near_chunks,
    read_land_chunk,
    read_land_document,
    realize_backdrop,
    realize_chunk,
    realize_region,
    water_bodies,
)
from exulanica.grammar.shapes import validate_record
from exulanica.world.landform_contact import chunk_height_at

FRAME = WorldFrame(width_mm=80_000, depth_mm=70_000, seed="a" * 64)
HILLS = read_land_document(
    {
        "profile": PROFILE,
        "ground_mm": 8000,
        "features": [
            {"id": "tilt", "kind": "tilt", "side": "north", "grade_permille": 30},
            {
                "id": "hill",
                "kind": "rise",
                "side": "north",
                "distance_mm": 20000,
                "height_mm": 24000,
                "roughness_permille": 400,
            },
            {"id": "swell", "kind": "undulation", "amplitude_mm": 900, "wavelength_mm": 30000},
            {"id": "sea", "kind": "shore", "side": "south", "distance_mm": 60000},
            {
                "id": "pond",
                "kind": "basin",
                "side": "east",
                "distance_mm": -20000,
                "radius_mm": 12000,
            },
            {
                "id": "steps",
                "kind": "terraces",
                "side": "north",
                "distance_mm": 30000,
                "depth_mm": 60000,
                "tier_height_mm": 3500,
            },
            {
                "id": "skyline",
                "kind": "range",
                "side": "north",
                "distance_mm": 2200000,
                "band_mm": 900000,
                "height_mm": 380000,
            },
        ],
    }
)


def test_the_chunk_is_the_city_tile_and_one_metre_sampling_fills_it():
    assert CHUNK_MM == TILE_SIZE_MM
    assert MILLIONTHS == 1_000_000
    assert SAMPLES_PER_SIDE == CHUNK_MM // CELL_MM + 1


def test_level_land_is_its_ground_everywhere():
    chunk = realize_chunk(level_land(1500), FRAME, 0, 0)
    assert set(chunk.height_mm) == {1500}
    assert set(chunk.slope_millionths()) == {0}


def test_the_same_document_and_seed_give_the_same_land_and_another_seed_does_not():
    xs = list(range(-40_000, 120_001, 20_000))
    ys = list(range(-60_000, 140_001, 20_000))
    first = land_heights(HILLS, FRAME, xs, ys)
    assert land_heights(HILLS, FRAME, xs, ys) == first
    assert all(type(h) is int for h in first)
    other = WorldFrame(width_mm=80_000, depth_mm=70_000, seed="b" * 64)
    assert land_heights(HILLS, other, xs, ys) != first


def test_a_known_land_realizes_to_known_bytes():
    """Golden: a change to any recipe changes every world made from it, so it must be seen."""
    chunk = realize_chunk(HILLS, FRAME, 0, 0)
    assert chunk.sha256 == hashlib.sha256(canonical_json(chunk.document())).hexdigest()
    assert chunk.sha256 == GOLDEN_CHUNK_SHA256


GOLDEN_CHUNK_SHA256 = "5cf71d21437d3c8fc152e6c821767f45f6f0544e99440e227c16b447a4a7fd22"


def test_neighbouring_chunks_share_their_edge_samples():
    here, east, north = (realize_chunk(HILLS, FRAME, *c) for c in ((0, 0), (1, 0), (0, 1)))
    n = SAMPLES_PER_SIDE
    for row in range(n):
        assert here.height_mm[row * n + n - 1] == east.height_mm[row * n]
    assert here.height_mm[(n - 1) * n : n * n] == north.height_mm[0:n]


def test_a_chunk_is_a_valid_city_terrain_record():
    for chunk in (realize_chunk(HILLS, FRAME, 0, 0), realize_chunk(HILLS, FRAME, -1, 1)):
        x0, y0 = chunk.chunk_x * CHUNK_MM, chunk.chunk_y * CHUNK_MM
        record = terrain.TerrainRecord(
            identity="d1d4b6a3-3b4c-5c2d-8e5f-0a1b2c3d4e5f",
            tile_ordinal=tile_ordinal(chunk.chunk_x, chunk.chunk_y),
            tile_x=chunk.chunk_x,
            tile_y=chunk.chunk_y,
            cell_mm=chunk.cell_mm,
            samples_per_side=chunk.samples_per_side,
            height_mm=chunk.height_mm,
            slope_millionths=chunk.slope_millionths(),
            triangulation="sw_ne",
            extent=Extent(x0, y0, min(chunk.height_mm), x0 + CHUNK_MM, y0 + CHUNK_MM,
                          max(chunk.height_mm)),
        )  # fmt: skip
        validate_record(record, terrain.SHAPE)


def test_a_point_is_the_sample_there_and_between_samples_the_triangle_it_lies_in():
    chunk = realize_chunk(HILLS, FRAME, 0, 0)
    n = SAMPLES_PER_SIDE
    for x, y in ((0, 0), (17_000, 41_000), (128_000, 128_000), (64_000, 5_000)):
        sample = chunk.height_mm[(y // CELL_MM) * n + x // CELL_MM]
        assert height_at(HILLS, FRAME, x, y) == sample == chunk_height_at(chunk, x, y)
    # Inside a cell, south-west of its diagonal: the plane through SW, SE and NE.
    sw, se = chunk.height_mm[3 * n + 7], chunk.height_mm[3 * n + 8]
    ne = chunk.height_mm[4 * n + 8]
    x, y = 7_000 + 750, 3_000 + 250
    expected = sw + (se - sw) * Fraction(3, 4) + (ne - se) * Fraction(1, 4)
    assert chunk_height_at(chunk, x, y) == expected
    assert chunk_height_at(chunk, -1, 0) is None


def test_a_tilt_holds_its_height_beyond_its_reach():
    tilt = read_land_document(
        {
            "profile": PROFILE,
            "ground_mm": 0,
            "features": [
                {
                    "id": "t",
                    "kind": "tilt",
                    "side": "north",
                    "grade_permille": 50,
                    "reach_mm": 100_000,
                }
            ],
        }
    )
    centre_y = FRAME.depth_mm // 2
    assert height_at(tilt, FRAME, 40_000, centre_y + 100_000) == 5_000
    assert height_at(tilt, FRAME, 40_000, centre_y + 900_000) == 5_000
    assert height_at(tilt, FRAME, 40_000, centre_y - 100_000) == -5_000
    assert height_at(tilt, FRAME, 40_000, centre_y + 20_000) == 1_000


def test_a_shore_ends_the_land_in_a_beach_and_a_sea_floor_below_the_datum():
    shore = read_land_document(
        {
            "profile": PROFILE,
            "ground_mm": 9000,
            "features": [
                {
                    "id": "sea",
                    "kind": "shore",
                    "side": "south",
                    "distance_mm": 50_000,
                    "wander_mm": 0,
                    "beach_mm": 20_000,
                    "beach_top_mm": 2500,
                    "coast_grade_permille": 500,
                }
            ],
        }
    )
    line = -50_000  # the world's south edge is y 0
    assert height_at(shore, FRAME, 40_000, line - 300_000) <= -2_000
    assert height_at(shore, FRAME, 40_000, line + 1_000) < 2500
    assert height_at(shore, FRAME, 40_000, line + 20_000) == 2500
    # Behind the beach the land rises at the coast grade until it meets its own level.
    profile = [height_at(shore, FRAME, 40_000, line + 20_000 + k * 1000) for k in range(20)]
    assert max(b - a for a, b in pairwise(profile)) <= 500
    assert profile[-1] == 9000
    [sea] = water_bodies(shore, FRAME)
    assert sea.kind == "sea" and sea.level_mm == 0


def _steepest_permille(near) -> int:
    """The steepest rise from a sample to its east or north neighbour, per mille."""
    rows = [near.heights[j * near.nx : (j + 1) * near.nx] for j in range(near.ny)]
    return max(
        max(abs(b - a) for row in rows for a, b in pairwise(row)),
        max(abs(b - a) for low, high in pairwise(rows) for a, b in zip(low, high, strict=True)),
    )


def test_a_shore_with_its_defaults_meets_the_land_as_a_slope_where_its_edge_wanders():
    """The waterline wanders, and the coast's slope behind the beach follows it: where the line
    bends the land must still rise no steeper than a person could walk up, never a scarp."""
    shore = read_land_document(
        {
            "profile": PROFILE,
            "ground_mm": 9000,
            "features": [{"id": "sea", "kind": "shore", "side": "south", "distance_mm": 50_000}],
        }
    )
    near = realize_region(shore, FRAME, -128_000, -128_000, 256_000, 0)
    assert min(near.heights) < 0 and max(near.heights) == 9000
    assert _steepest_permille(near) <= 600


def test_terraces_are_level_benches_joined_by_banks_not_walls():
    """On an even slope each step is a level bench and a bank: the bank takes its catalogued share
    of the tier's rise, so it is no steeper than the slope beneath divided by that share."""
    slope = read_land_document(
        {
            "profile": PROFILE,
            "ground_mm": 4000,
            "features": [
                {"id": "tilt", "kind": "tilt", "side": "north", "grade_permille": 100},
                {
                    "id": "steps",
                    "kind": "terraces",
                    "side": "north",
                    "distance_mm": 10_000,
                    "depth_mm": 80_000,
                    "width_mm": 100_000,
                    "fade_mm": 5_000,
                    "tier_height_mm": 2500,
                },
            ],
        }
    )
    share = slope.features[1].values["riser_share_permille"]
    canonical = slope.canonical()
    natural = read_land_document({**canonical, "features": canonical["features"][:1]})
    # Up the band's middle, clear of its fading edges: a column running up the slope.
    ys = [70_000 + 10_000 + 15_000 + k * 1000 for k in range(41)]
    column = [height_at(slope, FRAME, 40_000, y) for y in ys]
    beneath = [height_at(natural, FRAME, 40_000, y) for y in ys]
    rises = [b - a for a, b in pairwise(column)]
    steepest = max(b - a for a, b in pairwise(beneath))
    assert max(rises) <= steepest * 1000 // share + 2, (steepest, rises)
    # A bench is the tier's level part, several metres deep on a gentle slope.
    assert any(rises[k : k + 4] == [0, 0, 0, 0] for k in range(len(rises))), rises
    assert min(rises) >= 0, "a terrace never steps down a slope that rises"


def test_a_filled_basin_holds_its_water_at_its_rim_less_the_freeboard():
    near = realize_region(HILLS, FRAME, -20_000, -20_000, 140_000, 100_000)
    lake = next(body for body in water_bodies(HILLS, FRAME) if body.id == "pond")
    assert lake.kind == "lake"
    cx, cy, r = lake.centre_mm[0], lake.centre_mm[1], lake.radius_mm
    wet = [
        (x, y)
        for x, y, h in near.samples()
        if h < lake.level_mm and (x - cx) ** 2 + (y - cy) ** 2 < r * r
    ]
    assert wet, "the basin holds water"
    assert min(h for x, y, h in near.samples() if (x, y) in set(wet)) <= lake.level_mm - 2000
    # Every sample beside the water and outside the basin stands above the water's level.
    wet_set = set(wet)
    for x, y in wet:
        for nx_, ny_ in ((x + CELL_MM, y), (x - CELL_MM, y), (x, y + CELL_MM), (x, y - CELL_MM)):
            if (nx_, ny_) not in wet_set and (nx_ - cx) ** 2 + (ny_ - cy) ** 2 >= r * r:
                assert near.at(nx_, ny_) >= lake.level_mm, (nx_, ny_)


def test_the_backdrop_meets_the_near_land_at_its_edge_and_reaches_the_horizon():
    backdrop = realize_backdrop(HILLS, FRAME, reach_mm=2_000_000)
    x0, y0, x1, y1 = backdrop.near_mm
    assert (x0, y0) == (-CHUNK_MM, -CHUNK_MM) and (x1, y1) == (2 * CHUNK_MM, 2 * CHUNK_MM)
    for axis in (backdrop.x_mm, backdrop.y_mm):
        assert all(b > a for a, b in pairwise(axis))
    edge = [(x, y0) for x in backdrop.x_mm if x0 <= x <= x1]
    assert edge
    for x, y in edge:
        assert backdrop.height(x, y) == height_at(HILLS, FRAME, x, y)
    centre = (FRAME.width_mm // 2, FRAME.depth_mm // 2)
    assert backdrop.x_mm[0] <= centre[0] - 2_000_000 and backdrop.y_mm[-1] >= centre[1] + 2_000_000
    assert max(backdrop.height_mm) > NEAR_BOUND_MM  # the range is drawn, not held to the near bound


def test_near_land_beyond_the_sheet_bound_is_refused_by_name():
    tall = read_land_document(
        {
            "profile": PROFILE,
            "ground_mm": 30000,
            "features": [
                {
                    "id": "peak",
                    "kind": "rise",
                    "side": "north",
                    "distance_mm": 0,
                    "height_mm": 50000,
                    "roughness_permille": 0,
                }
            ],
        }
    )
    with pytest.raises(LandformRefused) as caught:
        realize_chunk(tall, FRAME, 0, 1)
    assert caught.value.code == "landform_near_out_of_bounds"
    assert "64000" in caught.value.detail


def test_a_range_that_would_rise_inside_the_walkable_land_is_refused():
    near_range = read_land_document(
        {
            "profile": PROFILE,
            "ground_mm": 0,
            "features": [
                {
                    "id": "wall",
                    "kind": "range",
                    "side": "north",
                    "distance_mm": 400_000,
                    "band_mm": 400_000,
                    "height_mm": 100_000,
                }
            ],
        }
    )
    with pytest.raises(LandformRefused) as caught:
        realize_backdrop(near_range, FRAME, reach_mm=2_000_000)
    assert caught.value.code == "landform_range_too_near" and "wall" in caught.value.detail


def test_a_chunk_document_reads_back_to_the_same_chunk():
    chunk = realize_chunk(HILLS, FRAME, 1, -1)
    again = read_land_chunk(chunk.document(), chunk.sha256)
    assert again.height_mm == chunk.height_mm and (again.chunk_x, again.chunk_y) == (1, -1)
    with pytest.raises(LandformRefused):
        read_land_chunk({**chunk.document(), "cell_mm": 2000})
    with pytest.raises(LandformRefused):
        read_land_chunk(chunk.document(), "0" * 64)


def test_near_chunks_cover_the_world_and_one_ring_round_it():
    assert near_chunks(FRAME) == tuple((x, y) for y in (-1, 0, 1) for x in (-1, 0, 1))
    town = WorldFrame(width_mm=256_000, depth_mm=128_000, seed="c" * 64)
    assert near_chunks(town) == tuple((x, y) for y in (-1, 0, 1) for x in (-1, 0, 1, 2))


# A stepped watercourse from the hill north of the world, past its west side, into the southern sea.
FALLS = {
    "id": "falls", "kind": "cascade", "side": "south", "offset_mm": -55_000,
    "from_mm": -150_000, "to_mm": 100_000,
}  # fmt: skip
CASCADE_FEATURES = [
    {"id": "tilt", "kind": "tilt", "side": "north", "grade_permille": 30},
    {"id": "hill", "kind": "rise", "side": "north", "distance_mm": 20000, "height_mm": 24000,
     "roughness_permille": 400},
    {"id": "swell", "kind": "undulation", "amplitude_mm": 900, "wavelength_mm": 30000},
    {"id": "sea", "kind": "shore", "side": "south", "distance_mm": 60000},
]  # fmt: skip


def cascade_land(*features: dict, ground_mm: int = 8000):  # type: ignore[no-untyped-def]
    return read_land_document(
        {"profile": PROFILE, "ground_mm": ground_mm, "features": [*CASCADE_FEATURES, *features]}
    )


def _holds(near, pool) -> None:  # type: ignore[no-untyped-def]
    """Every lattice sample in a pool stands below its water, and every sample beside the pool and
    outside it stands at or above the water: the pool is held."""
    x0, y0, x1, y1 = pool.rect_mm
    inside = {(x, y) for x, y, _ in near.samples() if x0 <= x <= x1 and y0 <= y <= y1}
    assert inside, pool.id
    for x, y in inside:
        assert near.at(x, y) < pool.level_mm, (pool.id, x, y)
        for nx_, ny_ in ((x + CELL_MM, y), (x - CELL_MM, y), (x, y + CELL_MM), (x, y - CELL_MM)):
            if (nx_, ny_) not in inside:
                assert near.at(nx_, ny_) >= pool.level_mm, (pool.id, nx_, ny_)


def test_a_cascade_steps_down_in_held_pools_and_falls_no_higher_than_its_step_into_the_sea():
    land = cascade_land(FALLS)
    bodies = water_bodies(land, FRAME)
    pools = [body for body in bodies if body.kind == "pool"]
    falls = [body for body in bodies if body.kind == "fall"]
    assert len(pools) == len(falls) >= 2, "it ends in the sea: every pool falls, the last into it"
    levels = [pool.level_mm for pool in pools]
    assert all(a > b for a, b in pairwise(levels))
    for i, fall in enumerate(falls):
        below = levels[i + 1] if i + 1 < len(levels) else 0
        assert (fall.level_mm, fall.bottom_mm, fall.side) == (levels[i], below, "south")
        assert 0 < fall.level_mm - fall.bottom_mm <= 3000, "no fall higher than the step"
        assert fall.rect_mm[1] == fall.rect_mm[3], "a fall is a line across the channel"
    near = realize_region(land, FRAME, -40_000, -128_000, 20_000, 200_000)
    for pool in pools:
        _holds(near, pool)
    # Each pool's floor lies its depth below its water.
    x0, y0, x1, y1 = pools[0].rect_mm
    assert near.at((x0 + x1) // 2 // CELL_MM * CELL_MM, (y0 + y1) // 2 // CELL_MM * CELL_MM) <= (
        levels[0] - 1200
    )


def test_a_cascade_ending_on_land_closes_its_last_pool():
    land = cascade_land({**FALLS, "to_mm": -20_000})
    bodies = [body for body in water_bodies(land, FRAME) if body.id.startswith("falls")]
    assert bodies[-1].kind == "pool", "the last pool on land falls nowhere"
    assert len([b for b in bodies if b.kind == "fall"]) == len(bodies) // 2
    near = realize_region(land, FRAME, -40_000, -40_000, 20_000, 200_000)
    for pool in (body for body in bodies if body.kind == "pool"):
        _holds(near, pool)


def test_land_with_a_cascade_is_still_one_function_of_each_point():
    land = cascade_land(FALLS)
    near = realize_region(land, FRAME, -40_000, -128_000, 20_000, 200_000)
    part = realize_region(land, FRAME, -30_000, -20_000, -5_000, 40_000)
    for x, y, h in part.samples():
        assert near.at(x, y) == h == height_at(land, FRAME, x, y)
    backdrop = realize_backdrop(land, FRAME, reach_mm=400_000)
    x0, y0, x1, y1 = backdrop.near_mm
    shared = [
        (x, y) for x in backdrop.x_mm for y in backdrop.y_mm if x0 <= x <= x1 and y0 <= y <= y1
    ]
    for x, y in shared:
        assert backdrop.height(x, y) == height_at(land, FRAME, x, y)
    assert [b.document() for b in backdrop.water] == [
        b.document() for b in water_bodies(land, FRAME)
    ]


def test_land_without_a_cascade_reads_the_same_under_every_catalog_version():
    raw = {"profile": PROFILE, "ground_mm": 8000, "features": CASCADE_FEATURES}
    assert read_land_document(raw, landform_catalog(1)) == read_land_document(raw)
    with pytest.raises(LandformRefused) as caught:
        read_land_document({**raw, "features": [*CASCADE_FEATURES, FALLS]}, landform_catalog(1))
    assert caught.value.path == "features[4].kind", "the first catalog version names no cascade"


@pytest.mark.parametrize(
    ("change", "code", "path"),
    [
        ({"to_mm": -150_000}, "landform_invalid", "features[4].to_mm"),
        ({"side": "south_west"}, "landform_invalid", "features[4].side"),
        ({"to_mm": 400_000}, "landform_cascade_beyond_near", "features[4]"),
        ({"side": "north", "from_mm": -150_000, "to_mm": 60_000, "offset_mm": 55_000},
         "landform_cascade_rises", ""),
        ({"from_mm": -60_000, "to_mm": -50_000, "step_mm": 500}, "landform_cascade_too_steep", ""),
    ],
)  # fmt: skip
def test_a_cascade_that_cannot_stand_is_refused_by_name(change: dict, code: str, path: str):
    with pytest.raises(LandformRefused) as caught:
        land = cascade_land({**FALLS, **change})
        realize_region(land, FRAME, -40_000, -40_000, 20_000, 40_000)
    assert (caught.value.code, caught.value.path) == (code, path)
