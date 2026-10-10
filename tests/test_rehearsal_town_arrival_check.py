"""The rehearsal measures a real generated town, not only a claimed arrival receipt.

Its row for a town's first society (``residentsClearOfArrival`` in
``scripts/rehearsal/handlers.mjs``, run here in Node) is held to societies written by hand, whose
distances are worked in the comments, and to a real town's first hour, minute by minute.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "rehearsal"))

from exulanica.world.generated_worlds import compose_generated_world  # noqa: E402
from exulanica.world.society_living import (  # noqa: E402
    LIVING_TOWN_PROFILE,
    advance_living_society,
    initial_living_society,
    input_routine,
    living_places,
)
from exulanica.world.world_recipes import world_recipe  # noqa: E402
from steplist import load  # noqa: E402
from town_arrival_check import measure  # noqa: E402

from living_town_support import SEED, town_input  # noqa: E402

HANDLERS = ROOT / "scripts" / "rehearsal" / "handlers.mjs"
OPENING_POLICY = json.loads(
    (ROOT / "exulanica/world/society-opening-policy.v2.json").read_text(encoding="utf-8")
)
ARRIVAL_POLICY = json.loads(
    (ROOT / "exulanica/world/composers/town-arrival.v1.json").read_text(encoding="utf-8")
)

EVALUATE = """
import { readFileSync } from 'node:fs';
const { residentsClearOfArrival } = await import(process.argv[1]);
const cases = JSON.parse(readFileSync(0, 'utf8'));
const clear = (c) => residentsClearOfArrival(c.society, c.arrival, c.clearance, c.most);
console.log(JSON.stringify(cases.map(clear)));
"""


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


def test_opening_minutes_in_the_step_match_the_opening_policy():
    step = next(item for item in load()["steps"] if item["id"] == "people-cross-tile-seams")
    assert (
        step["parameters"]["opening_minutes_maximum"] == OPENING_POLICY["values"]["minutes_maximum"]
    )
    assert step["parameters"]["opening_minutes_reason"].strip()


def _clear(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH")
    completed = subprocess.run(
        [node, "--input-type=module", "-e", EVALUATE, HANDLERS.as_uri()],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return json.loads(completed.stdout)


#: Where a person arrives in the hand-written societies: 10 m east, 20 m north (south is negative).
ARRIVAL = [10_000, -20_000]
HOME = {"destination_id": "premises:home"}


def _person(name: str, east: int, south: int, where: str) -> dict[str, Any]:
    """Someone ``east`` and ``south`` millimetres from the arrival, in one of the four places."""
    location = {
        "home": {"edge": None, "indoors": True, "destination_id": "premises:home"},
        "indoors": {"edge": None, "indoors": True, "destination_id": "premises:shop"},
        "standing": {"edge": None, "indoors": False, "destination_id": None},
        "walking": {"edge": {"edge_id": "a|b"}, "indoors": False, "destination_id": None},
    }[where]
    return {
        "id": name,
        "home": HOME,
        "location": location,
        "position_mm": [ARRIVAL[0] + east, ARRIVAL[1] + south],
    }


def _case(tick: Any, people: list[dict[str, Any]], arrival: Any = ARRIVAL) -> dict[str, Any]:
    return {
        "society": {"current_tick": tick, "state": {"inhabitants": people}},
        "arrival": arrival,
        "clearance": 2_000,
        "most": 60,
    }


def test_the_first_society_of_a_town_is_held_clear_of_the_arrival_whether_or_not_it_opened_awake():
    at_home = _person("at-home", 3_000, 4_000, "home")  # 5 m away
    edge_of_clear = _person("on-the-line", 0, 2_000, "standing")  # exactly the clearance
    passing = _person("passing", 500, 0, "walking")  # half a metre, on an edge
    in_a_shop = _person("in-a-shop", 0, -100, "indoors")  # its door is right behind the arrival
    cases = {
        # Born at its first minute with everybody at home: as before a society opened awake.
        "born": _case(0, [at_home]),
        # Opened at minute 17: a walker passes, a shopper is indoors, and who stands is clear.
        "awake": _case(17, [at_home, edge_of_clear, passing, in_a_shop]),
        "the last minute an opening may reach": _case(60, [at_home]),
        # Refused: somebody standing a millimetre inside the clearance, and somebody at home there.
        "stands near": _case(17, [at_home, _person("near", 0, 1_999, "standing")]),
        "stands on it": _case(17, [_person("on-it", 0, 0, "standing")]),
        "lives on it": _case(0, [_person("lives-near", 1_000, 0, "home")]),
        # Refused: a minute no opening reaches, no minute, nobody, nobody placed, no arrival.
        "too late": _case(61, [at_home]),
        "before the first": _case(-1, [at_home]),
        "no minute": _case(None, [at_home]),
        "nobody": _case(0, []),
        "unplaced": _case(0, [at_home, {**at_home, "id": "nowhere", "position_mm": None}]),
        "no arrival": _case(0, [at_home], arrival=None),
        # The frame is east and south: the same point with north for south is 40 m from the
        # arrival, so whoever stands there is clear, and they are near an arrival mirrored there.
        "mirrored": _case(17, [_person("mirror", 0, 40_000, "standing")]),
        "mirrored arrival": _case(
            17, [_person("mirror", 0, 40_000, "standing")], arrival=[10_000, 20_000]
        ),
    }
    results = dict(zip(cases, _clear(list(cases.values())), strict=True))
    assert {name: result["ok"] for name, result in results.items()} == {
        "born": True,
        "awake": True,
        "the last minute an opening may reach": True,
        "stands near": False,
        "stands on it": False,
        "lives on it": False,
        "too late": False,
        "before the first": False,
        "no minute": False,
        "nobody": False,
        "unplaced": False,
        "no arrival": False,
        "mirrored": True,
        "mirrored arrival": False,
    }
    awake = results["awake"]
    assert (awake["tick"], awake["resident_count"]) == (17, 4)
    assert awake["passing"] == ["passing"] and awake["held_near"] == []
    # Of those held to the clearance (at home 5 m off, standing 2 m off) the nearest is 2 m.
    assert awake["nearest_held_squared_mm"] == 2_000**2
    assert results["stands near"]["held_near"] == ["near"]
    assert results["lives on it"]["held_near"] == ["lives-near"]


def test_a_real_town_stands_clear_of_its_arrival_through_every_minute_an_opening_may_reach():
    """The rule the row states is the town's own: on a real town's first hour, minute by minute,
    nobody at home and nobody standing outdoors is within the pinned clearance of the arrival the
    town's input states, in the frame its people's positions are in."""
    document = town_input()
    routine = input_routine(document)
    [place] = living_places([document], routine, {})
    state = initial_living_society(
        uuid.UUID(int=12),
        SEED,
        place,
        routine,
        branch_id=document["version_id"],
        population=document["population"]["size"],
        profile=LIVING_TOWN_PROFILE,
    )
    most = OPENING_POLICY["values"]["minutes_maximum"]
    clearance = ARRIVAL_POLICY["minimum_resident_clearance_mm"]
    arrival = list(document["navigation"]["arrival_mm"])
    states = [state]
    for _ in range(most):
        state, _events = advance_living_society(state, SEED, [place], routine)
        states.append(state)
    # Positive control: by the hour's end people are out of their homes and some are walking.
    last = states[-1]["inhabitants"]
    assert any(not person["location"]["indoors"] for person in last)
    assert any(person["location"]["edge"] for one in states for person in one["inhabitants"])
    results = _clear(
        [
            {
                "society": {"current_tick": one["tick"], "state": one},
                "arrival": arrival,
                "clearance": clearance,
                "most": most,
            }
            for one in states
        ]
    )
    assert [result["tick"] for result in results] == list(range(most + 1))
    assert all(result["ok"] for result in results), [r for r in results if not r["ok"]][:3]
    assert all(result["nearest_held_squared_mm"] >= clearance**2 for result in results)
