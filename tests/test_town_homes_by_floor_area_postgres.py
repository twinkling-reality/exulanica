"""A town's homes by floor area, and the routine a town keeps, as a deployment stores them.

A town made through the API today starts with the people its routine's policy states, each home
housing them by the floor its premises record holds; a town made while towns were made under the
earlier routine and peopled today keeps that routine and its two people a home, read from the
routine its own receipt pins; and a society of things over a new town is as many villagers, every
input of it stating that population.

Each town here is made under one fixed identity, so it is the same town on every run: a town made
through the API otherwise takes a fresh identity, and what its homes hold and its premises offer
follows from that."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from exulanica.world import saved_entries, society_catalogs

from test_society_made_world import made as imported_made  # noqa: F401
from test_walking_surfaces_v3_postgres import (  # noqa: F401
    V3,
    V7,
    _every_town_a_test_makes_is_made,
    _made_alias,
    _offering_things,
    _place,
    _step,
)

pytestmark = pytest.mark.postgres

V5 = "exulanica-society/v5"
CATALOGS = Path(__file__).resolve().parents[1] / "assets" / "catalogs" / "society"


#: The small town every test here makes. Its homes hold 638 people by the floor their records
#: state, read from its own place on 2026-10-10, so the 128 a new town starts with are housed.
TOWN = "world:generated:00000000-0000-4000-8000-000000000003"


@pytest.fixture(autouse=True)
def _the_same_town_on_every_run(monkeypatch):
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: TOWN)


def _stated(name: str, key: str) -> dict:
    stated = json.loads((CATALOGS / name).read_text(encoding="utf-8"))
    return next(entry for entry in stated["entries"] if entry["key"] == key)


def _input(api, entry: dict, seq: int) -> dict:
    with api.database.session(api.repository.workspace_id) as connection:
        return connection.execute(
            "select i.document from world_society_input i join world_society s using "
            "(workspace_id,society_id) where s.workspace_id=%s and s.world_id=%s "
            "and s.version_id=%s and i.input_seq=%s",
            (api.repository.workspace_id, entry["world_id"], entry["authored_version_id"], seq),
        ).fetchone()["document"]


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


def test_a_town_made_today_starts_with_its_routine_s_people_housed_by_floor(made):
    api = made
    entry, society = _town(api, "A town of today")
    body = _people(api, entry, society, V5)
    state = body["state"]
    budget = _stated("society-policy.v3.json", "town_people_default")["value"]
    assert len(state["inhabitants"]) == budget == 128
    assert state["routine"]["catalog_versions"]["society-use-class"] == 3
    assert state["routine"]["catalog_versions"]["society-policy"] == 3
    # Each home houses the people the place its input carries says live there, and they differ:
    # a home with more floor houses more.
    place = _input(api, entry, 1)["living"]["place"]
    lives = {
        d["destination_id"]: d["resident_capacity"]
        for d in place["destinations"]
        if d["resident_capacity"]
    }
    housed: dict[str, int] = {}
    for person in state["inhabitants"]:
        home = person["home"]["destination_id"]
        housed[home] = housed.get(home, 0) + 1
    assert housed == lives and sum(lives.values()) == budget
    assert max(lives.values()) > min(lives.values())
    body = _step(api, entry, body)
    replayed = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/replay?world_id={entry['world_id']}"
    )
    assert replayed.status_code == 200 and replayed.json()["replay_verified"] is True


def test_a_town_made_under_the_earlier_routine_keeps_it_and_its_people(made, monkeypatch):
    api = made
    before = dict(society_catalogs.TOWN_ROUTINE_VERSIONS_BEFORE_FLOOR_AREA)
    with monkeypatch.context() as earlier:
        # Made while towns were made under the earlier routine: its receipt pins that one.
        earlier.setattr(society_catalogs, "TOWN_ROUTINE_VERSIONS", before)
        entry, society = _town(api, "A town made before")
    # Peopled today.
    assert before != society_catalogs.TOWN_ROUTINE_VERSIONS
    body = _people(api, entry, society, V5)
    state = body["state"]
    assert state["routine"]["catalog_versions"] == before
    place = _input(api, entry, 1)["living"]["place"]
    homes = [d for d in place["destinations"] if d["resident_capacity"]]
    two = _stated("society-use-class.v2.json", "residential")["resident_capacity"]
    assert {d["resident_capacity"] for d in homes} == {two}
    assert len(state["inhabitants"]) == two * len(homes) < 128


def test_a_society_of_things_over_a_town_of_today_is_as_many_people_in_every_input(made):
    api = made
    _offering_things(api)
    entry, society = _town(api, "A town of today with a knight")
    east, _height, south = entry["generated_ground"]["arrival_mm"]
    _place(api, entry, "knight", "knight", 1, east - 2_000, south)
    body = _people(api, entry, society, V7)
    villagers = [p for p in body["state"]["inhabitants"] if p["came_by"] == "populated"]
    first = _input(api, entry, 1)
    assert first["profile"] == V3
    assert len(villagers) == first["population"]["size"] == first["people"]["population"] == 128
    assert first["people"]["routine"]["catalog_versions"]["society-use-class"] == 3
    # A home with more floor houses more of them.
    homes = [row["homes"] for row in first["people"]["premises"] if row["homes"]]
    assert sum(homes) == 128 and max(homes) > min(homes)
    # A thing placed after is a later input: the same population, and no frame again.
    _place(api, entry, "well", "well", 2, east + 3_000, south)
    for _ in range(2):
        body = _step(api, entry, body)
    later = _input(api, entry, 2)
    assert later["population"] == first["population"] and "people" not in later
    replayed = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/replay?world_id={entry['world_id']}"
    )
    assert replayed.status_code == 200 and replayed.json()["replay_verified"] is True
