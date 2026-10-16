"""People brought into a person's own world may speak before anything is placed there, as a
deployment serves it (``needs_a_placed_thing`` false in ``society-engines.v6.json``).

What is shown, through the routes a page reads and creates with, on a starter world and on a small
town, neither holding a placed thing:

*   on a host that offers societies of things, the saved entry and the version's capability read
    state the engine of things, and the society the entry's engine makes is one: its people are
    the villager's second version, which may say a line, and it replays as it was made;
*   a host that does not offer them states, and makes, the ground's own engine.
"""

from __future__ import annotations

import pytest
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.world.society_engines import CREATES
from exulanica.world.starter import AUTHORED_STARTER_REGION_ID

from test_saved_world_holding_things_postgres import (
    THINGS,
    _capability_engine,
    _offering,
    _read,
    _starter,
)
from test_society_made_world import made as imported_made  # noqa: F401
from test_walking_surfaces_v3_postgres import (  # noqa: F401
    _every_town_a_test_makes_is_made,
    _made_alias,
    _step,
)

pytestmark = pytest.mark.postgres

WORLDS = ("starter", "town")


def _world(api, world: str) -> dict:
    if world == "starter":
        return _starter(api)
    made = api.post("/worlds/generated", {"recipe": "small_town", "title": "A town of talkers"})
    assert made.status_code == 201, made.text
    return made.json()


def _bring_in(api, entry: dict, engine: str) -> dict:
    ground = entry.get("generated_ground")
    made = api.post(
        f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}",
        {
            "region_id": AUTHORED_STARTER_REGION_ID if ground is None else ground["region_id"],
            "profile": engine,
        },
    )
    assert made.status_code in (200, 201), made.text
    return made.json()


@pytest.mark.parametrize("world", WORLDS)
def test_people_brought_into_a_world_holding_nothing_placed_may_speak(made, world):
    api = made
    _offering(api, True)
    entry = _world(api, world)
    read = _read(api, entry)
    assert read["society_engine"] == THINGS
    assert _capability_engine(api, entry) == THINGS
    society = _bring_in(api, entry, read["society_engine"])
    assert society["profile"] == THINGS
    villager = shipped_thing_kinds()[("villager", 2)]
    assert "say" in {ability["key"] for ability in villager.document["abilities"]}
    people = [p for p in society["state"]["inhabitants"] if p["came_by"] == "populated"]
    assert people and all(p["kind"] == dict(villager.reference()) for p in people)
    assert not [p for p in society["state"]["inhabitants"] if p["came_by"] == "placed"]
    _step(api, entry, society)
    replayed = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/replay?world_id={entry['world_id']}"
    )
    assert replayed.status_code == 200 and replayed.json()["replay_verified"] is True


@pytest.mark.parametrize("world", WORLDS)
def test_a_host_that_offers_no_society_of_things_brings_in_the_ground_s_engine(made, world):
    api = made
    _offering(api, False)
    entry = _world(api, world)
    engine = CREATES["saved_world" if world == "starter" else "town"]
    assert _read(api, entry)["society_engine"] == engine
    assert _capability_engine(api, entry) == engine
    assert _bring_in(api, entry, engine)["profile"] == engine
