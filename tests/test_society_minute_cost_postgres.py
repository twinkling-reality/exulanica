"""A town's people admitted by the cost of their minute, as a deployment stores them.

Through the API and a real database: a host that cannot run a town's minute refuses its society
by name with nothing made, and the same town is peopled on a host that can; and a town whose
homes are all lived in holds more than the 512 people the schema and the engine table once
admitted, is stored, advances and replays.

Every town here is made under one fixed identity, so it is the same town on every run: what a
town's homes hold follows from its identity (550 to 742 people over 48 small towns read on
2026-10-10), and this one's hold 638, read from its own place that day.
"""

from __future__ import annotations

import dataclasses

import pytest
from exulanica.world import saved_entries, society_city_place

from test_society_made_world import made as imported_made  # noqa: F401
from test_walking_surfaces_v3_postgres import (  # noqa: F401
    V7,
    _every_town_a_test_makes_is_made,
    _made_alias,
    _offering_things,
    _place,
    _step,
)

pytestmark = pytest.mark.postgres

V5 = "exulanica-society/v5"
#: The small town every test here makes, and the people its homes hold with every home lived in.
TOWN = "world:generated:00000000-0000-4000-8000-000000000003"
HOMES_HOLD = 638


@pytest.fixture(autouse=True)
def _the_same_town_on_every_run(monkeypatch):
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: TOWN)


def _town(api, title: str) -> tuple[dict, str]:
    made_town = api.post("/worlds/generated", {"recipe": "small_town", "title": title})
    assert made_town.status_code == 201, made_town.text
    entry = made_town.json()
    assert entry["world_id"] == TOWN
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    return entry, society


def _people(api, entry: dict, society: str, profile: str) -> dict:
    created = api.post(
        society, {"region_id": entry["generated_ground"]["region_id"], "profile": profile}
    )
    assert created.status_code in (200, 201), created.text
    return created.json()


def _input(api, entry: dict, seq: int) -> dict:
    with api.database.session(api.repository.workspace_id) as connection:
        return connection.execute(
            "select i.document from world_society_input i join world_society s using "
            "(workspace_id,society_id) where s.workspace_id=%s and s.world_id=%s "
            "and s.version_id=%s and i.input_seq=%s",
            (api.repository.workspace_id, entry["world_id"], entry["authored_version_id"], seq),
        ).fetchone()["document"]


def _host(api, **settings) -> None:
    app = api.client.app
    app.state.services = dataclasses.replace(app.state.services, **settings)


def _societies(api, entry: dict) -> int:
    with api.database.session(api.repository.workspace_id) as connection:
        return connection.execute(
            "select count(*) as held from world_society where workspace_id=%s and world_id=%s",
            (api.repository.workspace_id, entry["world_id"]),
        ).fetchone()["held"]


def _inputs(api, entry: dict) -> int:
    with api.database.session(api.repository.workspace_id) as connection:
        return connection.execute(
            "select count(*) as held from world_society_input where workspace_id=%s",
            (api.repository.workspace_id,),
        ).fetchone()["held"]


def test_a_host_that_cannot_run_a_towns_minute_refuses_its_society_and_makes_nothing(made):
    api = made
    entry, society = _town(api, "A town on a slow machine")
    body = {"region_id": entry["generated_ground"]["region_id"], "profile": V5}
    # A machine a thousand times slower than the measured one: 128 people's minute, about 11 ms
    # as measured, would take over ten seconds against the 800 ms this host gives one.
    _host(api, society_minute_cost_scale_milli=1_000_000)
    refused = api.post(society, body)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "people_over_cost"
    detail = refused.json()["detail"]
    assert detail.startswith("a minute of 128 people here takes ")
    assert "this server gives a minute 800 ms" in detail
    assert (_societies(api, entry), _inputs(api, entry)) == (0, 0)
    # The same town on the measured machine is peopled, and on the slow one with a minute long
    # enough: a host's own settings decide, never the town.
    _host(api, society_minute_cost_scale_milli=1_000)
    assert len(_people(api, entry, society, V5)["state"]["inhabitants"]) == 128
    assert _societies(api, entry) == 1


def _every_home_lived_in(monkeypatch) -> None:
    """A town whose routine states no number to start with: every place in every home is lived
    in, the people its homes' floor houses."""
    spread = society_city_place._people_living

    def lived_in(premises_units, routine):
        policy = {k: v for k, v in routine.policy.items() if k != "town_people_default"}
        return spread(premises_units, dataclasses.replace(routine, policy=policy))

    monkeypatch.setattr(society_city_place, "_people_living", lived_in)


def test_a_living_town_of_more_than_512_people_is_stored_advances_and_replays(made, monkeypatch):
    api = made
    _every_home_lived_in(monkeypatch)
    entry, society = _town(api, "A town with every home lived in")
    body = _people(api, entry, society, V5)
    people = len(body["state"]["inhabitants"])
    first = _input(api, entry, 1)
    lives = sum(d["resident_capacity"] for d in first["living"]["place"]["destinations"])
    assert people == lives == first["population"]["size"] == body["population_size"]
    assert people == HOMES_HOLD > 512
    body = _step(api, entry, body)
    replayed = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/replay?world_id={entry['world_id']}"
    )
    assert replayed.status_code == 200 and replayed.json()["replay_verified"] is True


def test_a_society_of_things_over_a_town_of_more_than_512_people_is_stored_and_advances(
    made, monkeypatch
):
    api = made
    _offering_things(api)
    _every_home_lived_in(monkeypatch)
    entry, society = _town(api, "A full town with a knight")
    east, _height, south = entry["generated_ground"]["arrival_mm"]
    _place(api, entry, "knight", "knight", 1, east - 2_000, south)
    body = _people(api, entry, society, V7)
    villagers = [p for p in body["state"]["inhabitants"] if p["came_by"] == "populated"]
    first = _input(api, entry, 1)
    assert len(villagers) == first["population"]["size"] == first["people"]["population"]
    assert len(villagers) == HOMES_HOLD > 512
    # The knight came too: more beings than its people, and no arrival refused for a full society.
    assert len(body["state"]["inhabitants"]) == len(villagers) + 1
    assert body["state"].get("refused_placements", []) == []
    body = _step(api, entry, body)
    replayed = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/replay?world_id={entry['world_id']}"
    )
    assert replayed.status_code == 200 and replayed.json()["replay_verified"] is True
