"""A society of things over a generated town, as a deployment stores it: a town made through the
API, things placed in its region through the API, a society of things made over it, whose input is
the town's walking surfaces with its things (walking-surfaces-v3), advanced and replayed; and the
input checks admit the profile beside the ones they admitted."""

from __future__ import annotations

import dataclasses
import json
from types import MappingProxyType

import psycopg
import pytest
from exulanica.world import world_recipes as recipe_catalog
from exulanica.world.world_recipes import CANDIDATES_MAXIMUM

from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

V7 = "exulanica-society/v7"
V3 = "exulanica.society-input/walking-surfaces-v3"


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def _every_town_a_test_makes_is_made(monkeypatch):
    """Each town is tried with the catalog's most candidates, as tests/test_generated_worlds.py
    tries its own."""
    generous = {
        recipe.key: dataclasses.replace(recipe, candidates=CANDIDATES_MAXIMUM)
        for recipe in recipe_catalog.world_recipes()
    }
    monkeypatch.setattr(recipe_catalog, "_by_key", lambda: MappingProxyType(generous))


def _offering_things(api) -> None:
    app = api.client.app
    app.state.services = dataclasses.replace(app.state.services, societies_of_things=True)


def _place(api, entry, thing_id: str, kind: str, version: int, east: int, south: int) -> None:
    root = f"/world/versions/{entry['authored_version_id']}?world_id={entry['world_id']}"
    base = api.get(root).json()["state_sha256"]
    placed = api.post(
        f"/world/versions/{entry['authored_version_id']}/things?world_id={entry['world_id']}",
        {
            "base_state_sha256": base,
            "thing_id": thing_id,
            "kind": {"kind": kind, "version": version},
            "region_id": entry["generated_ground"]["region_id"],
            "pose": {"x_mm": east, "y_mm": 0, "z_mm": south, "yaw_microradians": 0},
            "origin_role": "fictional",
        },
    )
    assert placed.status_code == 201, placed.text


def _step(api, entry: dict, body: dict) -> dict:
    stepped = api.post(
        f"/world/versions/{entry['authored_version_id']}/society/steps?world_id={entry['world_id']}",
        {"base_tick": body["current_tick"], "base_state_sha256": body["state_sha256"]},
    )
    assert stepped.status_code == 200, stepped.text
    return stepped.json()


def test_a_society_of_things_lives_in_a_town_with_what_was_placed_in_its_streets(made):
    api = made
    _offering_things(api)
    made_town = api.post("/worlds/generated", {"recipe": "small_town", "title": "A dressed town"})
    assert made_town.status_code == 201, made_town.text
    entry = made_town.json()
    east, _height, south = entry["generated_ground"]["arrival_mm"]
    _place(api, entry, "well", "well", 2, east + 3_000, south)
    _place(api, entry, "knight", "knight", 1, east - 2_000, south)
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    created = api.post(
        society, {"region_id": entry["generated_ground"]["region_id"], "profile": V7}
    )
    assert created.status_code in (200, 201), created.text
    body = created.json()
    assert body["profile"] == V7
    state = body["state"]
    assert [t["placed_id"] for t in state["things"]] == ["well"]
    [knight] = [p for p in state["inhabitants"] if p["came_by"] == "placed"]
    assert knight["placed_id"] == "knight"
    with api.database.session(api.repository.workspace_id) as connection:
        document = connection.execute(
            "select i.document from world_society_input i join world_society s using "
            "(workspace_id,society_id) where s.workspace_id=%s and s.world_id=%s "
            "and s.version_id=%s and i.input_seq=1",
            (api.repository.workspace_id, entry["world_id"], entry["authored_version_id"]),
        ).fetchone()["document"]
    assert document["profile"] == V3
    assert [t["placed_id"] for t in document["things"]] == ["knight", "well"]
    assert document["population"]["size"] == len(
        [p for p in state["inhabitants"] if p["came_by"] == "populated"]
    )
    for _ in range(2):
        body = _step(api, entry, body)
    assert body["current_tick"] == 2
    replayed = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/replay?world_id={entry['world_id']}"
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"] is True


def test_the_input_checks_admit_v3_and_hold_its_things_and_population(made):
    """The checks are read straight from the table: a copy of a stored v3 input inserts as the
    next input, and a copy without its things or its population is refused by the check that
    guards that field. Inputs are append-only, so each copy is inserted, never updated."""
    api = made
    _offering_things(api)
    made_town = api.post("/worlds/generated", {"recipe": "small_town", "title": "A checked town"})
    entry = made_town.json()
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    created = api.post(
        society, {"region_id": entry["generated_ground"]["region_id"], "profile": V7}
    )
    assert created.status_code in (200, 201), created.text
    with api.database.session(api.repository.workspace_id) as connection:
        row = connection.execute(
            "select i.society_id, i.document from world_society_input i join world_society s "
            "using (workspace_id,society_id) where s.workspace_id=%s and s.world_id=%s "
            "and i.input_seq=1",
            (api.repository.workspace_id, entry["world_id"]),
        ).fetchone()
        assert row["document"]["profile"] == V3
        columns = [
            r["column_name"]
            for r in connection.execute(
                "select column_name from information_schema.columns where table_schema = "
                "current_schema() and table_name = 'world_society_input' order by ordinal_position"
            ).fetchall()
        ]
        chosen = ", ".join(
            "%(document)s::jsonb"
            if name == "document"
            else "input_seq + 1"
            if name == "input_seq"
            else name
            for name in columns
        )
        insert = (
            f"insert into world_society_input ({', '.join(columns)}) select {chosen} "
            "from world_society_input where workspace_id=%(workspace)s "
            "and society_id=%(society)s and input_seq=1"
        )
        # A later input states no modules: only the first records them.
        unbroken = {k: v for k, v in row["document"].items() if k != "modules"}
        unbroken["input_seq"] = 2

        def copy(document):  # type: ignore[no-untyped-def]
            connection.execute(
                insert,
                {
                    "document": json.dumps(document),
                    "workspace": api.repository.workspace_id,
                    "society": row["society_id"],
                },
            )

        # The positive control: the unbroken copy inserts, so only the missing field refuses.
        with connection.transaction() as savepoint:
            copy(unbroken)
            raise psycopg.Rollback(savepoint)
        for field, check in (
            ("things", "world_society_input_things_check"),
            ("population", "world_society_input_population_check"),
        ):
            broken = {k: v for k, v in unbroken.items() if k != field}
            with pytest.raises(psycopg.errors.CheckViolation) as raised, connection.transaction():
                copy(broken)
            assert raised.value.diag.constraint_name == check
