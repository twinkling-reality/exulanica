"""The rehearsal measures a real generated town, not only a claimed arrival receipt."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "rehearsal"))

from exulanica.world.generated_worlds import compose_generated_world  # noqa: E402
from exulanica.world.world_recipes import world_recipe  # noqa: E402
from steplist import load  # noqa: E402
from town_arrival_check import measure  # noqa: E402


def test_real_market_town_arrival_is_clear_and_a_different_served_pose_is_refused():
    town = compose_generated_world(world_recipe("market_town"), "world:s9-arrival-proof")
    arrival = town.receipt["arrival"]
    served = {
        "arrival_mm": [
            arrival["position_mm"][0],
            arrival["support_z_mm"],
            -arrival["position_mm"][1],
        ],
        "arrival_facing_mm": [arrival["facing_mm"][0], -arrival["facing_mm"][1]],
    }
    checked = measure(dict(town.receipt), town.records, served)
    assert checked["ok"] is True
    assert checked["occupied_count"] > 0
    assert (
        checked["nearest_object_distance_squared_mm"] >= checked["minimum_object_clearance_mm"] ** 2
    )
    moved = {**served, "arrival_mm": [served["arrival_mm"][0] + 1, *served["arrival_mm"][1:]]}
    assert measure(dict(town.receipt), town.records, moved)["ok"] is False


def test_resident_clearance_in_the_step_matches_the_pinned_town_policy():
    policy = json.loads((ROOT / "exulanica/world/composers/town-arrival.v1.json").read_text())
    step = next(item for item in load()["steps"] if item["id"] == "people-cross-tile-seams")
    assert step["parameters"]["arrival_clearance_mm"] == policy["minimum_resident_clearance_mm"]
