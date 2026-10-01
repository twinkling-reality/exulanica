"""The living town's replay measurement fits a line on or above every point it measured, measures
a stress town the admitted specification refuses, and writes no location of this machine."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from exulanica.world.world_recipes import SpecificationRefused, town_recipe

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import measure_living_comparison_replay as measure


def _points(line: dict[str, int], noise: dict[tuple[int, int], int]) -> list[dict]:
    points = []
    for population in (8, 16, 32, 64, 92):
        for decided in sorted({0, 4, 16, population}):
            if decided > population:
                continue
            cost = (
                line["fixed"]
                + line["person"] * population
                + (line["decided"] + line["pair"] * population) * decided
                + noise.get((population, decided), 0)
            )
            points.append(
                {
                    "graph": "g",
                    "population": population,
                    "decided": decided,
                    "read_wall_us": {"p95": cost},
                }
            )
    return points


def test_the_fit_finds_a_line_whose_pair_term_is_zero_and_no_point_lies_above_it():
    points = _points(
        {"fixed": 150_000, "person": 9_000, "decided": 12_000, "pair": 0},
        {(32, 16): 4_000, (92, 92): 9_000},
    )
    found = measure._fit(points, pairs=True)
    assert found["replay_per_decided_pair_us"] == 0
    assert all(margin["margin_us"] >= 0 for margin in found["margins"])
    assert min(margin["margin_us"] for margin in found["margins"]) < 1_000
    without = measure._fit(points, pairs=False)
    assert set(without) == {
        "replay_fixed_ms",
        "replay_per_person_us",
        "replay_per_decided_person_us",
        "margins",
    }


def test_the_fit_keeps_a_pair_term_the_points_carry():
    points = _points({"fixed": 200_000, "person": 20_000, "decided": 30_000, "pair": 100}, {})
    found = measure._fit(points, pairs=True)
    assert found["replay_per_decided_pair_us"] == 100
    assert all(margin["margin_us"] >= 0 for margin in found["margins"])


def test_the_stress_town_is_one_the_admitted_specification_refuses():
    with pytest.raises(SpecificationRefused):
        town_recipe(measure.STRESS_PRESET, {"block_length_mm": measure.STRESS_BLOCK_LENGTH_MM})
    stress = measure._stress_recipe()
    assert dict(stress.values)["block_length_mm"] == measure.STRESS_BLOCK_LENGTH_MM


def test_a_record_naming_a_location_of_this_machine_is_refused():
    with pytest.raises(SystemExit, match="refused"):
        measure._refuse_machine_paths(f"written under {Path.home()}/somewhere")
    measure._refuse_machine_paths('{"graph": "world:generated:living-replay-measured-0"}')
