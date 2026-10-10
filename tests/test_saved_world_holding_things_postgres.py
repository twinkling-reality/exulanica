"""A person's saved world holding things is brought to life as a society of things, as a deployment
serves it (``creates_holding_things`` in the engine table, ``society-engines.v4.json``).

What is shown, through the routes a page reads and creates with:

*   on a host that offers societies of things, a starter world's entry and its version's capability
    read state its ground's engine while it holds no placed thing, and the engine of things once
    its author places a knight; a host that does not offer them keeps the ground's engine;
*   a new society of the ground's engine is refused by name for that world
    (``society_engine_differs``), and the one the entry states is made: the knight lives there as
    a placed being, on its routine, and nobody is asked anything until a person picks a mind;
*   a world whose society was made before a thing was placed in it keeps that society: it reads
    and replays as it was made, and asking for it again reads it back.
"""

from __future__ import annotations

import dataclasses

import pytest
from exulanica.world.starter import AUTHORED_STARTER_REGION_ID

from test_society_made_world import PLATE
from test_society_made_world import _place as place_object
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

#: The engines named here, as a person reads them on the page: the purposeful society a starter
#: world's ground is created with, and the society of things.
PURPOSEFUL = "exulanica-society/v2"
THINGS = "exulanica-society/v7"


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


def _offering(api, offered: bool) -> None:
    app = api.client.app
    app.state.services = dataclasses.replace(app.state.services, societies_of_things=offered)


def _starter(api) -> dict:
    """A starter world with a seat its people can reach, as a person's first world has."""
    made = api.post("/world-entries/starter", {"title": "A knight by the seat"})
    assert made.status_code == 200, made.text
    return place_object(api, made.json(), "object:seat", AUTHORED_STARTER_REGION_ID, PLATE)


def _read(api, entry: dict) -> dict:
    read = api.get(f"/world-entries/{entry['entry_id']}")
    assert read.status_code == 200, read.text
    return read.json()


def _scope(entry: dict) -> str:
    return f"/world/versions/{entry['authored_version_id']}"


def _query(entry: dict) -> str:
    return f"?world_id={entry['world_id']}"


def _place_knight(api, entry: dict) -> None:
    base = api.get(_scope(entry) + _query(entry)).json()["state_sha256"]
    placed = api.post(
        _scope(entry) + "/things" + _query(entry),
        {
            "base_state_sha256": base,
            "thing_id": "knight",
            "kind": {"kind": "knight", "version": 1},
            "region_id": AUTHORED_STARTER_REGION_ID,
            "pose": {"x_mm": -3_000, "y_mm": 0, "z_mm": 3_000, "yaw_microradians": 0},
            "origin_role": "fictional",
        },
    )
    assert placed.status_code == 201, placed.text


def _capability_engine(api, entry: dict) -> str | None:
    read = api.get(_scope(entry) + "/capabilities" + _query(entry))
    assert read.status_code == 200, read.text
    return read.json()["society"]["engine"]


def _make(api, entry: dict, profile: str):
    return api.post(
        _scope(entry) + "/society" + _query(entry),
        {"region_id": AUTHORED_STARTER_REGION_ID, "profile": profile},
    )


def _step(api, entry: dict, society: dict) -> dict:
    stepped = api.post(
        _scope(entry) + "/society/steps" + _query(entry),
        {"base_tick": society["current_tick"], "base_state_sha256": society["state_sha256"]},
    )
    assert stepped.status_code == 200, stepped.text
    return stepped.json()


def _asked(api, society: dict) -> tuple[int, int]:
    """How many decision requests and model choices the society holds."""
    with api.database.session(api.repository.workspace_id) as connection:
        row = connection.execute(
            "select (select count(*) from world_society_decision_request where workspace_id=%s "
            "and society_id=%s) as asked, (select count(*) from world_society_model_choice "
            "where workspace_id=%s and society_id=%s) as chosen",
            (
                api.repository.workspace_id,
                society["society_id"],
                api.repository.workspace_id,
                society["society_id"],
            ),
        ).fetchone()
    return row["asked"], row["chosen"]


def test_a_saved_world_holding_things_is_brought_to_life_as_a_society_of_things(made):
    api = made
    _offering(api, True)
    entry = _starter(api)
    assert _read(api, entry)["society_engine"] == PURPOSEFUL
    assert _capability_engine(api, entry) == PURPOSEFUL
    _place_knight(api, entry)
    # A host that offers no society of things keeps the ground's engine, the knight placed or not.
    _offering(api, False)
    assert _read(api, entry)["society_engine"] == PURPOSEFUL
    _offering(api, True)
    read = _read(api, entry)
    assert read["society_engine"] == THINGS
    assert _capability_engine(api, entry) == THINGS
    # The ground's own engine would leave the knight without life: refused by name, nothing made.
    refused = _make(api, entry, PURPOSEFUL)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "society_engine_differs"
    assert THINGS in refused.json()["detail"]
    made = _make(api, entry, read["society_engine"])
    assert made.status_code in (200, 201), made.text
    society = made.json()
    assert society["profile"] == THINGS
    [knight] = [p for p in society["state"]["inhabitants"] if p["came_by"] == "placed"]
    assert knight["placed_id"] == "knight"
    # Its beings live on their routines: three minutes ask nobody, and nobody's mind is chosen.
    for _ in range(3):
        society = _step(api, entry, society)
    assert society["current_tick"] == 3
    assert _asked(api, society) == (0, 0)


def test_a_society_made_before_its_world_held_things_keeps_its_engine_and_replays(made):
    api = made
    _offering(api, True)
    entry = _starter(api)
    made = _make(api, entry, PURPOSEFUL)
    assert made.status_code in (200, 201), made.text
    society = _step(api, entry, made.json())
    _place_knight(api, entry)
    # A new society would be one of things; the one the version holds stays as it was made.
    assert _read(api, entry)["society_engine"] == THINGS
    assert _capability_engine(api, entry) == PURPOSEFUL
    held = api.get(_scope(entry) + "/society" + _query(entry))
    assert held.status_code == 200, held.text
    assert held.json()["profile"] == PURPOSEFUL
    again = _make(api, entry, PURPOSEFUL)
    assert again.status_code == 200, again.text
    assert again.json()["society_id"] == society["society_id"]
    replayed = api.get(_scope(entry) + "/society/replay" + _query(entry))
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"] is True
