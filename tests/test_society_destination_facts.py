"""Destination facts distinguish outdoor work from the living engine's occupancy flag."""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

from exulanica.world.composers import composer_module
from exulanica.world.kinds.document import read_kind
from exulanica.world.society_engines import CREATES
from exulanica.world.society_living import (
    LivingPlace,
    advance_living_society,
    initial_living_society,
)
from exulanica.world.society_repository import consumed_places


def _farm():
    document = json.loads(
        (Path(__file__).parent / "fixtures/world-kinds/fixture-farm.json").read_text()
    )
    kind = read_kind(document)
    composer = composer_module("site-plan", 1)
    made = composer.compose_kind(
        kind, kind.values("small_farm"), "world:generated:00000000-0000-4000-8000-00000000f001"
    )
    place = composer.society_place("place:test", dict(made.receipt), made.records)
    routine = composer.receipt_routine(made.receipt)
    source = {
        "input_seq": 1,
        "document_sha256": "a" * 64,
        "availability": "available",
        "unavailable_reason": None,
        "navigation": {"profile": "site-walking-surfaces/v1", "clearance_mm": 340},
        "targets": [],
        "living": {"place": place},
    }
    return source, place, routine


def test_working_farmer_is_served_at_an_outdoor_destination_despite_occupancy_flag():
    source, document, routine = _farm()
    place = LivingPlace(document, routine)
    seed = "a" * 64
    state = initial_living_society(
        uuid.UUID("00000000-0000-4000-8000-00000000f001"),
        seed,
        place,
        routine,
        branch_id="branch",
        profile=CREATES["town"],
    )
    destinations = {
        row["destination_id"]: row for row in consumed_places(source)["living_destinations"]
    }
    for _ in range(360):
        state, _events = advance_living_society(state, seed, [place], routine)
        workers = [
            person
            for person in state["inhabitants"]
            if person["action"]["kind"] == "work"
            and person["action"]["status"] == "active"
            and person["role"]["key"] == "farmer"
        ]
        if workers:
            farmer = workers[0]
            assert farmer["location"]["indoors"] is True
            assert destinations[farmer["location"]["destination_id"]]["indoors"] is False
            break
    else:
        raise AssertionError("the fixed farm's farmer never reached work in the morning")
    homes = [row for row in destinations.values() if row["use_class"] == "residential"]
    assert homes and all(row["indoors"] is True for row in homes)


def test_destination_projection_keeps_disabled_places_out_and_does_not_change_input():
    source, place, _routine = _farm()
    hidden = next(row for row in place["destinations"] if row["enabled"])
    hidden["enabled"] = False
    original = copy.deepcopy(source)
    served = consumed_places(source)
    assert hidden["destination_id"] not in {
        row["destination_id"] for row in served["living_destinations"]
    }
    served["living_destinations"][0]["indoors"] = "changed by the reader"
    assert source == original


def test_nonliving_input_does_not_invent_destinations():
    source, _place, _routine = _farm()
    del source["living"]
    assert "living_destinations" not in consumed_places(source)
