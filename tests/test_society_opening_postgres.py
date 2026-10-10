"""A new town's society opens awake, against PostgreSQL, through the paths a deployment runs.

The town is the shipped arrival town with no scene laid, which lives on its living engine and is
made through ``make_society`` by the arrival step, as a guest's is. What is shown:

*   with the opening off the society stands at its first minute with everybody indoors, and stepped
    by hand through the steps route it first has a share of its people outdoors at a minute this
    test finds by counting ``location.indoors`` itself;
*   made again with the opening on, the same town (the same seed) stands at exactly that minute, in
    exactly that state, with every minute stored and replaying, and nothing asked of any model;
*   asking for the society again advances nothing;
*   the route a person's page asks (``POST .../society``) opens the same way;
*   a budget of minutes stops it short, and a town that lives in a society of things is left at its
    first minute;
*   set playing afterwards, the society's next minute is due at once, because the minutes it was
    opened by wrote no playback receipt, where a minute stepped through the playback control makes
    the same Play wait out an interval.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest
from exulanica.api.society_opening import OPENING_OFF, SocietyOpening
from exulanica.world import arrival_worlds
from exulanica.world.arrival_worlds import load_arrival_worlds

import personal_world_support as personal
from test_arrival_dressing_postgres import _enter_arrival, _offer, _society, _version
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

#: A share of 15 percent, an hour of minutes, and time that never runs out: time is not the subject.
OPENING = SocietyOpening(outdoors_share_milli=150, minutes_maximum=60, seconds_maximum=3600)


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(name="town")
def _town(made, monkeypatch):
    """The arrival town with no scene, its tiles read as baked, on a host that offers things."""
    monkeypatch.setattr(arrival_worlds, "arrival_tiles_baked", lambda connection, world: True)
    (world, *_) = load_arrival_worlds()
    bare = dataclasses.replace(world, scene=None)
    monkeypatch.setattr(arrival_worlds, "load_arrival_worlds", lambda: (bare,))
    _offer(made)
    return made


def _open_as(api, opening: SocietyOpening) -> None:
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services, society_opening=opening
    )


def _outdoors_milli(state: dict) -> int:
    people = state["inhabitants"]
    return 1000 * sum(1 for person in people if not person["location"]["indoors"]) // len(people)


def _paths(api, arrival: dict) -> tuple[str, str]:
    version = _version(api, arrival)["authored_version_id"]
    return f"/world/versions/{version}/society", f"world_id={arrival['world_id']}"


def _stepped_to_the_share(api, arrival: dict) -> dict:
    """The society stepped by hand, minute by minute, to the first minute the share is outdoors."""
    base, scope = _paths(api, arrival)
    body = _society(api, arrival).json()
    while _outdoors_milli(body["state"]) < OPENING.outdoors_share_milli:
        assert body["current_tick"] < OPENING.minutes_maximum, "the town never reached the share"
        stepped = api.post(
            f"{base}/steps?{scope}",
            {"base_tick": body["current_tick"], "base_state_sha256": body["state_sha256"]},
        )
        assert stepped.status_code == 200, stepped.text
        body = stepped.json()
    return body


def _model_rows(api) -> int:
    with api.database.session(api.repository.workspace_id) as connection:
        return sum(
            connection.execute(
                f"select count(*) n from {table} where workspace_id=%s",
                (api.repository.workspace_id,),
            ).fetchone()["n"]
            for table in ("world_society_decision_request", "world_society_model_choice")
        )


def test_a_town_opens_at_the_first_minute_a_share_of_its_people_is_outdoors(town):
    api = town
    _open_as(api, OPENING_OFF)
    arrival, dressing = _enter_arrival(api)
    assert arrival is not None and dressing == []
    born = _society(api, arrival).json()
    # Positive control: a living town is born with everybody at home, at its first minute.
    assert born["current_tick"] == 0 and _outdoors_milli(born["state"]) == 0
    expected = _stepped_to_the_share(api, arrival)
    assert expected["current_tick"] > 0

    # The same town made again, by the route a person's page asks, on a host that opens societies.
    base, scope = _paths(api, arrival)
    erased = api.client.delete(
        f"{base}?{scope}", headers={"Authorization": f"Bearer {personal.OWNER_TOKEN}"}
    )
    assert erased.status_code == 204, erased.text
    _open_as(api, OPENING)
    made = api.post(f"{base}?{scope}", {"region_id": born["region_id"], "profile": born["profile"]})
    assert made.status_code == 200, made.text
    opened = made.json()
    assert opened["current_tick"] == expected["current_tick"]
    assert _outdoors_milli(opened["state"]) >= OPENING.outdoors_share_milli
    assert opened["state"]["inhabitants"] == expected["state"]["inhabitants"]

    # Every minute is stored and replays; no model was asked and none was chosen.
    replay = api.get(f"{base}/replay?{scope}")
    assert replay.status_code == 200, replay.text
    assert _model_rows(api) == 0

    # Asked for again, it is read back where it stands.
    again = api.post(
        f"{base}?{scope}", {"region_id": born["region_id"], "profile": born["profile"]}
    )
    assert again.status_code == 200, again.text
    assert again.json()["current_tick"] == expected["current_tick"]
    assert again.json()["state_sha256"] == opened["state_sha256"]


def test_the_arrival_step_hands_a_guest_a_town_already_awake_and_never_wakes_it_twice(town):
    api = town
    _open_as(api, OPENING)
    arrival, dressing = _enter_arrival(api)
    assert arrival is not None and dressing == []
    opened = _society(api, arrival).json()
    assert opened["current_tick"] > 0
    assert _outdoors_milli(opened["state"]) >= OPENING.outdoors_share_milli
    again, dressing = _enter_arrival(api)
    assert again == arrival and dressing == []
    assert _society(api, arrival).json()["state_sha256"] == opened["state_sha256"]


def test_a_budget_of_minutes_stops_it_short(town):
    api = town
    # Nobody is outdoors in a living town's first two minutes, and no town is all outdoors.
    _open_as(
        api, SocietyOpening(outdoors_share_milli=1000, minutes_maximum=2, seconds_maximum=3600)
    )
    arrival, _ = _enter_arrival(api)
    opened = _society(api, arrival).json()
    assert opened["current_tick"] == 2
    assert _outdoors_milli(opened["state"]) < 1000
    # Asked for again while the share still does not hold, it is read back, not opened further.
    again, _ = _enter_arrival(api)
    assert again == arrival
    assert _society(api, arrival).json()["current_tick"] == 2
    base, scope = _paths(api, arrival)
    asked = api.post(
        f"{base}?{scope}", {"region_id": opened["region_id"], "profile": opened["profile"]}
    )
    assert asked.status_code == 200, asked.text
    assert asked.json()["current_tick"] == 2


def test_a_town_living_in_a_society_of_things_is_left_at_its_first_minute(made, monkeypatch):
    api = made
    monkeypatch.setattr(arrival_worlds, "arrival_tiles_baked", lambda connection, world: True)
    _offer(api)
    _open_as(api, OPENING)
    arrival, dressing = _enter_arrival(api)
    assert arrival is not None and dressing == []
    society = _society(api, arrival).json()
    (world, *_) = load_arrival_worlds()
    assert world.scene is not None and society["profile"] == world.scene.document["engine"]
    assert society["current_tick"] == 0


def _seconds_until_due(control: dict) -> float:
    due = datetime.fromisoformat(control["next_due_at"].replace("Z", "+00:00"))
    return (due - datetime.now(UTC)).total_seconds()


def test_play_after_the_opening_is_due_at_once_and_after_a_control_step_waits_an_interval(town):
    api = town
    _open_as(api, OPENING)
    arrival, _ = _enter_arrival(api)
    base, scope = _paths(api, arrival)
    opened = _society(api, arrival).json()
    assert opened["current_tick"] > 0
    played = api.put(f"{base}/control?{scope}", {"base_revision": 0, "mode": "playing", "speed": 1})
    assert played.status_code == 200, played.text
    control = played.json()
    interval = control["tick_interval_ms"] / 1000
    # Positive control for the comparison below: an interval is seconds, not a rounding error.
    assert interval >= 1
    assert _seconds_until_due(control) < 0.5

    # The other path, for contrast: paused again, one minute stepped through the playback control,
    # then Play: that minute is the control's last, and the next waits an interval after it.
    paused = api.put(
        f"{base}/control?{scope}",
        {"base_revision": control["revision"], "mode": "paused", "speed": 1},
    )
    assert paused.status_code == 200, paused.text
    now = _society(api, arrival).json()
    stepped = api.post(
        f"{base}/control/steps?{scope}",
        {
            "base_revision": paused.json()["revision"],
            "base_tick": now["current_tick"],
            "base_state_sha256": now["state_sha256"],
        },
    )
    assert stepped.status_code == 200, stepped.text
    revision = api.get(f"{base}/control?{scope}").json()["revision"]
    again = api.put(
        f"{base}/control?{scope}", {"base_revision": revision, "mode": "playing", "speed": 1}
    )
    assert again.status_code == 200, again.text
    assert _seconds_until_due(again.json()) > interval - 1.5
