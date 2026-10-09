"""A visitor's arrival world is dressed with the scene the arrival list names, against PostgreSQL.

What is shown, through the guest entry's own arrival step (``accounts._arrival``) on the
application a deployment runs:

*   the shipped arrival town, dressed with its shipped scene, holds every thing of the scene, lives
    in a society on the scene's engine with the town's own people and the scene's beings, and each
    being's mind is the scene's; asking again makes no second world and places or records nothing
    more;
*   a host that does not offer the scene's engine places nothing, makes no society and says so by
    the code the society routes answer with, so no world holds beings no society seats;
*   an arrival world naming no scene is made as before, with nothing placed;
*   a dressing refused comes back by its code as an incomplete step, and the world stands.
"""

from __future__ import annotations

import dataclasses
import uuid
from types import SimpleNamespace

import pytest
from exulanica.api.arrival_dressing import dress_arrival
from exulanica.api.routes import accounts
from exulanica.api.society_making import SocietyHooks
from exulanica.selection.validation import Session
from exulanica.world import arrival_worlds
from exulanica.world.arrival_worlds import load_arrival_worlds
from exulanica.world.scenes import shipped_scenes

from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(name="baked")
def _baked(monkeypatch):
    """Every arrival tile reads baked: the tiles are not the subject here, and this database bakes
    none (tests/test_arrival_worlds.py shows a copy waits for them)."""
    monkeypatch.setattr(arrival_worlds, "arrival_tiles_baked", lambda connection, world: True)


def _offer(api, offered: bool = True) -> None:
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services, societies_of_things=offered
    )


def _enter_arrival(api):
    """The guest entry's arrival step, for the owner's workspace and actor, as routes read it."""
    return accounts._arrival(
        SimpleNamespace(app=api.client.app), api.repository.workspace_id, api.actor
    )


def _version(api, arrival: dict) -> dict:
    entry = api.entry(str(arrival["entry_id"]))
    read = api.get(f"/world/versions/{entry['authored_version_id']}?world_id={arrival['world_id']}")
    assert read.status_code == 200, read.text
    return {**read.json(), "authored_version_id": entry["authored_version_id"]}


def _things(api, arrival: dict) -> dict[str, dict]:
    return {t["thing_id"]: t for t in _version(api, arrival)["things"] if not t["removed"]}


def _society(api, arrival: dict):
    version = _version(api, arrival)["authored_version_id"]
    return api.get(f"/world/versions/{version}/society?world_id={arrival['world_id']}")


def _choices(api) -> int:
    with api.database.session(api.repository.workspace_id) as connection:
        return connection.execute(
            "select count(*) n from world_society_model_choice where workspace_id=%s",
            (api.repository.workspace_id,),
        ).fetchone()["n"]


def test_a_guest_s_arrival_town_is_dressed_with_its_scene_and_lives(made, baked):
    api = made
    _offer(api)
    (world, *_) = load_arrival_worlds()
    assert world.scene is not None
    arrival, dressing = _enter_arrival(api)
    assert dressing == []
    assert arrival is not None and arrival["world_id"] == world.world_id

    scene = world.scene.document
    things = _things(api, arrival)
    assert set(things) == {thing["thing_id"] for thing in scene["things"]}
    society = _society(api, arrival)
    assert society.status_code == 200, society.text
    body = society.json()
    assert body["profile"] == scene["engine"]
    people = body["state"]["inhabitants"]
    placed = {
        person["placed_id"]: person["id"] for person in people if person.get("came_by") == "placed"
    }
    assert set(placed) == {mind["thing_id"] for mind in scene["minds"]}
    # The town's own people live beside the scene's beings.
    assert any(person.get("came_by") == "populated" for person in people)

    version = _version(api, arrival)["authored_version_id"]
    models = api.get(f"/world/versions/{version}/society/models?world_id={arrival['world_id']}")
    assert models.status_code == 200, models.text
    chosen = {
        choice["subject_id"]: (choice["model"]["provider"], choice["model"]["model_id"])
        for choice in models.json()["choices"]
    }
    for mind in scene["minds"]:
        decider = mind["decider"]
        assert chosen[placed[mind["thing_id"]]] == (decider["provider"], decider["model_id"])

    # Asking again answers the same world and lays nothing twice.
    choices = _choices(api)
    again, dressing = _enter_arrival(api)
    assert dressing == []
    assert again == arrival
    assert _things(api, arrival).keys() == things.keys()
    assert _choices(api) == choices


def test_a_host_that_does_not_offer_the_engine_places_nothing_and_says_so(made, baked):
    api = made
    _offer(api, offered=False)
    arrival, dressing = _enter_arrival(api)
    assert arrival is not None
    assert dressing == [{"step": "scene", "code": "society_engine_not_offered"}]
    assert _things(api, arrival) == {}
    assert _society(api, arrival).status_code == 404


def test_an_arrival_world_naming_no_scene_is_made_as_before(made, baked, monkeypatch):
    api = made
    _offer(api)
    (world, *_) = load_arrival_worlds()
    bare = dataclasses.replace(world, scene=None)
    monkeypatch.setattr(arrival_worlds, "load_arrival_worlds", lambda: (bare,))
    arrival, dressing = _enter_arrival(api)
    assert arrival is not None and dressing == []
    assert _things(api, arrival) == {}


def test_a_dressing_refused_is_named_and_the_world_stands(made, baked):
    api = made
    _offer(api)
    (world, *_) = load_arrival_worlds()
    arrival, _ = _enter_arrival(api)
    starters = [scene for scene in shipped_scenes().values() if scene.ground == "starter"]
    for_a_starter = dataclasses.replace(world, scene=starters[-1])
    workspace = api.repository.workspace_id
    with api.database.session(workspace) as connection:
        problems = dress_arrival(
            SocietyHooks.of_app(api.client.app),
            connection,
            Session(workspace_id=workspace, actor=api.actor),
            uuid.UUID(str(arrival["entry_id"])),
            for_a_starter,
        )
    assert problems == [{"step": "scene", "code": "scene_ground_mismatch"}]
    assert set(_things(api, arrival)) == {
        thing["thing_id"] for thing in world.scene.document["things"]
    }
