"""A coupled starter world's birds keep its people's time: they stop when the people stop.

A starter world states no roads, so its clock couples its society and its flight only, with no
lead. Its flight answers ``exulanica.flight-window/v2`` on the world's own timeline: the step it
presents moves when a minute of its society is committed and at no other time, and a window the
world has not reached by more than a minute is refused. The flight itself is the same function of
its step: what a coupled window holds is the legacy flight at that step.
"""

from __future__ import annotations

import pytest
from exulanica.movement.flight import FLIGHT_MODULE, flight_window
from fastapi.testclient import TestClient

import test_society_saved_world_api as saved_api
import test_world_arrangements as arrangements
from test_world_flight_api import _flight, _in_process, _pinned_clock, _square  # noqa: F401

pytestmark = pytest.mark.postgres
saved_world = arrangements.saved_world
runtime_app = arrangements.runtime_app
WINDOW = FLIGHT_MODULE.value("max_steps_per_request")
V2 = "exulanica-society/v2"


def test_a_coupled_starter_world_s_birds_move_only_with_its_people(runtime_app):
    world, make_app = runtime_app
    scope, version, society = saved_api.routes(world)
    with TestClient(make_app()) as client:
        _square(client, world)
        created = client.post(
            society,
            headers=saved_api.OWNER,
            params=scope,
            json={"region_id": world["binding"].region_id, "profile": V2},
        )
        assert created.status_code in (200, 201), created.text
        body = created.json()
        coupled = client.put(
            version + "/clock",
            headers=saved_api.OWNER,
            params=scope,
            json={"base_revision": 0, "profile": "coupled"},
        )
        assert coupled.status_code == 200, coupled.text
        clock = coupled.json()
        # No roads: the society and the flight, and nothing to lead.
        assert clock["traffic"] is None and clock["crossings_fed"] is False
        assert clock["timebases"]["flight"] == "world"
        origin = clock["era_mapping"]["timeline_origin_second"]
        # Before its first minute is committed the world presents the step that begins its era,
        # and a read that names no step starts there rather than before the era.
        early = _flight(client, world)
        assert early.status_code == 200, early.text
        assert (early.json()["clock_step"], early.json()["from_step"]) == (origin * 10, origin * 10)
        stepped = client.post(
            version + "/society/steps",
            headers=saved_api.OWNER,
            params=scope,
            json={"base_tick": body["current_tick"], "base_state_sha256": body["state_sha256"]},
        )
        assert stepped.status_code == 200, stepped.text
        served = _flight(client, world)
        assert served.status_code == 200, served.text
        window = served.json()
        # Paused, the world presents the same step however long a page waits.
        still = _flight(client, world)
        beyond = _flight(client, world, from_step=(origin + 90) * 10, steps=WINDOW)
    assert (window["profile"], window["timebase"]) == ("exulanica.flight-window/v2", "world")
    assert window["clock_step"] == (origin + 60) * 10 == still.json()["clock_step"]
    assert (window["from_step"], window["steps"]) == (origin * 10, WINDOW)
    assert [row["kind"] for row in window["flyers"]] == ["small_bird"] * 3
    flight = _in_process(world)
    assert window["flyers"] == flight_window(flight, origin * 10, WINDOW)["flyers"]
    assert beyond.status_code == 422 and beyond.json()["code"] == "flight_step_out_of_range"
