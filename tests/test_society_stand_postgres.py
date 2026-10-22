"""Where a being put down at a point would stand, as a deployment serves the read.

On a small town made under a fixed identity, with its society of things, through the routes:

*   the read names the walking node of the society's latest input nearest the point that nobody
    stands at or is headed to, with its position and the height a thing placed there rests at (the
    town's street surface, as a placing is held to it), and a being placed at that point is then
    taken in at exactly that node: the stand drawn under a creature is where it arrives;
*   a node somebody stands at is no stand: the read asked at a resident's own node names another;
*   the read authorizes the society's inputs as the state read does, so where the installation's
    authorizer refuses one, both reads are refused alike (424) and no stand is named; with a
    placement queued and not yet taken in, the latest input is authorized too, so refusing it alone
    refuses the read;
*   a version with no society, and a point outside the read's bounds or none at all, are refused by
    name, and nothing is written.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.api.society_runtime import UnavailableSocietyInput
from exulanica.world import saved_entries
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.thing_landing_source import prepare_landing_in_region

from test_society_made_world import made as imported_made  # noqa: F401
from test_society_take_in_postgres import TOWN
from test_walking_surfaces_v3_postgres import (  # noqa: F401
    V7,
    _every_town_a_test_makes_is_made,
    _made_alias,
    _offering_things,
    _place,
    _step,
)

pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def _the_same_town_on_every_run(monkeypatch):
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: TOWN)


def _stand(api, entry: dict, x_mm: int, z_mm: int):
    return api.get(
        f"/world/versions/{entry['authored_version_id']}/society/stand"
        f"?world_id={entry['world_id']}&x_mm={x_mm}&z_mm={z_mm}"
    )


def _society_rows(api) -> tuple[int, int]:
    with api.database.session(api.repository.workspace_id) as connection:
        row = connection.execute(
            "select (select count(*) from world_society_input) as inputs, "
            "(select count(*) from world_society_event) as events"
        ).fetchone()
    return int(row["inputs"]), int(row["events"])


def test_a_being_placed_at_a_point_is_taken_in_where_the_stand_read_says(made):
    api = made
    _offering_things(api)
    made_town = api.post("/worlds/generated", {"recipe": "small_town", "title": "A stand town"})
    assert made_town.status_code == 201, made_town.text
    entry = made_town.json()
    east, _height, south = entry["generated_ground"]["arrival_mm"]
    # Before any society is made there, the version has none to stand in.
    refused = _stand(api, entry, east, south)
    assert refused.status_code == 404, refused.text
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    created = api.post(
        society, {"region_id": entry["generated_ground"]["region_id"], "profile": V7}
    )
    assert created.status_code in (200, 201), created.text
    body = created.json()
    point = (east - 2_000, south + 1_000)
    before = _society_rows(api)
    read = _stand(api, entry, *point)
    assert read.status_code == 200, read.text
    answer = read.json()
    assert answer["profile"] == "exulanica.society-stand/v1"
    stand = answer["stand"]
    assert stand is not None and set(stand) == {"node_id", "position_mm", "height_mm"}
    # The height a thing placed at the node rests at, as the placing's own landing reads it.
    with api.database.session(api.repository.workspace_id) as connection:
        landing = prepare_landing_in_region(
            WorldObjectRepository(
                connection, api.repository.workspace_id, world_id=entry["world_id"]
            ),
            uuid.UUID(entry["authored_version_id"]),
            entry["generated_ground"]["region_id"],
        )
    assert landing is not None and landing.rest_height is not None
    assert stand["height_mm"] == landing.rest_height(tuple(stand["position_mm"]))
    # Reading wrote nothing.
    assert _society_rows(api) == before
    # Nobody stands at the stand or is on the way there.
    for person in body["state"]["inhabitants"]:
        assert person["location"]["node_id"] != stand["node_id"]
    _place(api, entry, "knight", "knight", 1, *point)
    body = api.get(society).json()
    body = _step(api, entry, body)
    [knight] = [p for p in body["state"]["inhabitants"] if p.get("placed_id") == "knight"]
    assert knight["location"]["node_id"] == stand["node_id"]
    assert knight["position_mm"] == stand["position_mm"]
    # Asked again at the same point, the knight's node is held, so the stand is another.
    again = _stand(api, entry, *point).json()["stand"]
    assert again is not None and again["node_id"] != stand["node_id"]


def test_the_read_is_refused_as_the_state_read_is_where_an_input_is_not_authorized(made):
    api = made
    _offering_things(api)
    made_town = api.post("/worlds/generated", {"recipe": "small_town", "title": "A withheld town"})
    entry = made_town.json()
    east, _height, south = entry["generated_ground"]["arrival_mm"]
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    created = api.post(
        society, {"region_id": entry["generated_ground"]["region_id"], "profile": V7}
    )
    assert created.status_code in (200, 201), created.text
    app = api.client.app
    authorize, asked, refusing = app.state.society_input_authorizer, [], []

    def recorded(connection, session, document):
        asked.append(document["profile"])
        if refusing:
            raise UnavailableSocietyInput("an input this test withdrew")
        return authorize(connection, session, document)

    app.state.society_input_authorizer = recorded
    assert _stand(api, entry, east, south).status_code == 200
    # The stand read asked the authorizer about the society's input before answering.
    assert asked
    refusing.append(True)
    state = api.get(society)
    stand = _stand(api, entry, east, south)
    assert state.status_code == stand.status_code == 424, (state.text, stand.text)
    assert stand.json()["code"] == state.json()["code"] == "unavailable_society_input"
    assert "stand" not in stand.json()


def test_the_latest_input_a_placement_queued_is_authorized_before_the_stand_is_read(made):
    api = made
    _offering_things(api)
    made_town = api.post("/worlds/generated", {"recipe": "small_town", "title": "A queued town"})
    entry = made_town.json()
    east, _height, south = entry["generated_ground"]["arrival_mm"]
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    created = api.post(
        society, {"region_id": entry["generated_ground"]["region_id"], "profile": V7}
    )
    assert created.status_code in (200, 201), created.text
    # A placement writes the society's next input; no minute is played, so it waits, not taken in.
    _place(api, entry, "knight", "knight", 1, east - 2_000, south + 1_000)
    app = api.client.app
    authorize = app.state.society_input_authorizer

    def queued(document) -> bool:
        return any(thing.get("placed_id") == "knight" for thing in document.get("things", ()))

    def refusing_the_queued(connection, session, document):
        if queued(document):
            raise UnavailableSocietyInput("the queued input this test withdrew")
        return authorize(connection, session, document)

    app.state.society_input_authorizer = refusing_the_queued
    stand = _stand(api, entry, east, south)
    assert stand.status_code == 424, stand.text
    assert stand.json()["code"] == "unavailable_society_input"
    app.state.society_input_authorizer = authorize
    assert _stand(api, entry, east, south).status_code == 200


@pytest.mark.parametrize("unreadable", ["waiting", "invalid"])
def test_a_ground_that_cannot_be_read_now_leaves_the_stand_without_its_height(
    made, monkeypatch, unreadable
):
    import exulanica.api.routes.society as society_routes
    from exulanica.world.errors import InvalidStructuralData
    from exulanica.world.kinds.worker import KindWorkWaiting

    api = made
    _offering_things(api)
    made_town = api.post("/worlds/generated", {"recipe": "small_town", "title": "A cloudy town"})
    entry = made_town.json()
    east, _height, south = entry["generated_ground"]["arrival_mm"]
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    created = api.post(
        society, {"region_id": entry["generated_ground"]["region_id"], "profile": V7}
    )
    assert created.status_code in (200, 201), created.text

    def unread(*_args):
        if unreadable == "waiting":
            raise KindWorkWaiting("busy")
        raise InvalidStructuralData("an unreadable site receipt")

    monkeypatch.setattr(society_routes, "prepare_landing_in_region", unread)
    read = _stand(api, entry, east - 2_000, south + 1_000)
    assert read.status_code == 200, read.text
    stand = read.json()["stand"]
    assert stand is not None and stand["height_mm"] is None


@pytest.mark.parametrize(
    "query",
    ["", "&x_mm=0", "&z_mm=0", f"&x_mm={2**31}&z_mm=0", "&x_mm=0&z_mm=a"],
    ids=["no-point", "no-z", "no-x", "past-the-bound", "not-a-number"],
)
def test_a_point_the_read_cannot_take_is_refused_before_anything_is_read(made, query):
    api = made
    made_town = api.post("/worlds/generated", {"recipe": "small_town", "title": "A bound town"})
    entry = made_town.json()
    asked = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/stand"
        f"?world_id={entry['world_id']}{query}"
    )
    assert asked.status_code == 422, asked.text
