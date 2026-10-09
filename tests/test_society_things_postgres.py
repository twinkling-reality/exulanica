"""A society of things in a saved world, through the application and against PostgreSQL.

What is shown, as the world's owner through the real routes:

*   a society of things (exulanica-society/v7) is made over a saved world by name: its input is the
    things composition, its people include the being its author placed, its things the objects,
    and it advances and replays;
*   an edit that places another being reaches it: the next minute records the being arriving;
*   with a door's stream registered, a visitor crosses in through the gate, a person's request to
    send it anywhere is refused by name, it leaves when its program calls it back, every crossing is
    bound once to its own event, and the society replays from what was stored and bound, refusing
    by name a binding that no longer says what its minute did or names a minute never run;
*   the society a version holds is found by its version, for a door;
*   a society made now records the routine held to each being's kind: a lantern spirit placed
    beside a bench never rests, visits, stands or talks over an hour while others use the bench,
    and a request to send it there is refused by name.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from exulanica.abilities.registry import PURPOSEFUL_BY_KIND
from exulanica.world.crossings import (
    CROSSINGS_PER_MINUTE,
    BoundCrossing,
    ConsumedCrossing,
    register_crossing_stream,
    society_of_version,
)
from fastapi.testclient import TestClient

import test_society_authored_world_postgres as helpers
import test_society_saved_world_api as saved_world_api
from test_society_saved_world_api import OWNER, routes
from things_society_support import MemoryCrossings, arrival, departure

saved_world = helpers.saved_world
saved_world_app = saved_world_api.world_app
pytestmark = pytest.mark.postgres
V7 = "exulanica-society/v7"


@pytest.fixture
def world_app(saved_world_app):
    """The saved world's app on a host that offers societies of things
    (``EXULANICA_SOCIETY_OF_THINGS``), and the one that does not."""
    world, make_app, runtime, database = saved_world_app

    def offering(offered: bool = True):
        app = make_app()
        app.state.services = dataclasses.replace(app.state.services, societies_of_things=offered)
        return app

    return world, offering, runtime, database


@pytest.fixture
def crossings():
    stream = MemoryCrossings()
    register_crossing_stream(stream)
    try:
        yield stream
    finally:
        register_crossing_stream(None)


def _place(client, world, thing_id, kind, version, x_mm, z_mm, *, yaw=0):
    scope, root, _ = routes(world)
    base = client.get(root, headers=OWNER, params=scope).json()["state_sha256"]
    placed = client.post(
        root + "/things",
        headers=OWNER,
        params=scope,
        json={
            "base_state_sha256": base,
            "thing_id": thing_id,
            "kind": {"kind": kind, "version": version},
            "region_id": world["binding"].region_id,
            "pose": {"x_mm": x_mm, "y_mm": 0, "z_mm": z_mm, "yaw_microradians": yaw},
            "origin_role": "fictional",
        },
    )
    assert placed.status_code == 201, placed.text


def _make_society(client, world):
    scope, _, society_route = routes(world)
    made = client.post(
        society_route,
        headers=OWNER,
        params=scope,
        json={"region_id": world["binding"].region_id, "profile": V7},
    )
    assert made.status_code in (200, 201), made.text
    return made.json()


def _step(client, world, society):
    scope, _, society_route = routes(world)
    stepped = client.post(
        society_route + "/steps",
        headers=OWNER,
        params=scope,
        json={"base_tick": society["current_tick"], "base_state_sha256": society["state_sha256"]},
    )
    assert stepped.status_code == 200, stepped.text
    return stepped.json()


def _replayed(client, world):
    scope, _, society_route = routes(world)
    replay = client.get(society_route + "/replay", headers=OWNER, params=scope)
    assert replay.status_code == 200, replay.text
    return replay.json()["replay_verified"]


def _refused(client, world):
    scope, _, society_route = routes(world)
    replay = client.get(society_route + "/replay", headers=OWNER, params=scope)
    assert replay.status_code == 409, replay.text
    assert replay.json()["code"] == "invalid_society_state"
    return replay.json()["detail"]


def _events(client, world):
    scope, _, society_route = routes(world)
    read = client.get(society_route + "/events", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    return read.json()["events"]


def test_a_society_of_things_lives_in_a_saved_world_with_what_its_author_placed(world_app):
    world, make_app, _, _ = world_app
    with TestClient(make_app()) as client:
        _place(client, world, "well", "well", 2, -4_000, 2_000)
        _place(client, world, "gate", "gate", 1, 0, 6_000)
        _place(client, world, "knight", "knight", 1, 3_000, 3_000)
        society = _make_society(client, world)
        assert society["profile"] == V7
        state = society["state"]
        [knight] = [p for p in state["inhabitants"] if p["came_by"] == "placed"]
        assert (knight["placed_id"], knight["kind"]["kind"]) == ("knight", "knight")
        assert [t["placed_id"] for t in state["things"]] == ["gate", "well"]
        stored = (
            world["connection"]
            .execute(
                "select document->>'profile' as profile from world_society_input "
                "where workspace_id=%s and input_seq=1",
                (world["workspace"],),
            )
            .fetchone()
        )
        world["connection"].commit()
        assert stored["profile"] == "exulanica.society-input/authored-ground-v5"
        society = _step(client, world, society)
        assert society["current_tick"] == 1
        # An edit that places another being reaches the society: it arrives the next minute.
        _place(client, world, "knight-2", "knight", 1, -2_000, 4_000)
        society = _step(client, world, society)
        arrived = [e for e in _events(client, world) if e["event_kind"] == "thing_arrived"]
        assert [e["document"]["reason"] for e in arrived] == ["placed_by_author"]
        assert {p["display_name"] for p in society["state"]["inhabitants"]} >= {
            "Knight",
            "Knight 2",
        }
        assert _replayed(client, world)


def test_a_spirit_in_a_society_made_now_never_does_what_its_kind_does_not_list(world_app):
    world, make_app, _, _ = world_app
    with TestClient(make_app()) as client:
        _place(client, world, "bench", "bench", 1, -4_000, 2_000)
        _place(client, world, "spirit", "lantern_spirit", 1, -3_000, 3_000)
        _place(client, world, "knight", "knight", 1, 3_000, 3_000)
        society = _make_society(client, world)
        stored = (
            world["connection"]
            .execute(
                "select document->'modules' as modules from world_society_input "
                "where workspace_id=%s and input_seq=1",
                (world["workspace"],),
            )
            .fetchone()
        )
        world["connection"].commit()
        assert PURPOSEFUL_BY_KIND in stored["modules"]
        [spirit] = [p for p in society["state"]["inhabitants"] if p["placed_id"] == "spirit"]
        # Asked to send the spirit to the bench, the society refuses by name.
        scope, _, society_route = routes(world)
        places = client.get(
            society_route, headers=OWNER, params={**scope, "places": "true"}
        ).json()["places"]
        [bench] = [t for t in places["targets"] if t["origin"] == "thing"]
        asked = client.post(
            society_route + "/actions",
            headers=OWNER,
            params=scope,
            json={
                "idempotency_key": str(uuid.uuid4()),
                "base_tick": society["current_tick"],
                "base_state_sha256": society["state_sha256"],
                "subject_id": spirit["id"],
                "intent": {"kind": "go_to", "target_id": bench["target_id"]},
            },
        )
        assert asked.status_code == 409, asked.text
        assert asked.json() == {"code": "invalid_society_action", "detail": "activity_not_offered"}
        used = set()
        for _ in range(60):
            society = _step(client, world, society)
            people = society["state"]["inhabitants"]
            [held] = [p for p in people if p["id"] == spirit["id"]]
            assert (held["goal"], held["action"]["kind"]) == (None, "idle"), held["action"]
            used |= {p["action"]["kind"] for p in people if p["id"] != spirit["id"]}
        # The positive control: others rested and talked beside it over the same hour.
        assert {"rest", "talk"} <= used, used
        assert _replayed(client, world)


def test_a_visitor_crosses_in_through_the_gate_and_goes_home(world_app, crossings):
    world, make_app, _, database = world_app
    with TestClient(make_app()) as client:
        _place(client, world, "well", "well", 2, -4_000, 2_000)
        _place(client, world, "gate", "gate", 1, 0, 6_000)
        society = _make_society(client, world)
        with database.session(world["workspace"]) as connection:
            found = society_of_version(
                connection, world["workspace"], world["world_id"], world["binding"].version_id
            )
        assert found == {"society_id": uuid.UUID(society["society_id"]), "engine_version": V7}
        society_id = found["society_id"]
        crossings.hand(society_id, arrival(1))
        society = _step(client, world, society)
        [visitor] = [p for p in society["state"]["inhabitants"] if p["came_by"] == "crossed"]
        [taken] = crossings.consumed(None, world["workspace"], society_id)
        assert (taken.tick, taken.bound.disposition) == (1, "arrived")
        events = _events(client, world)
        [arrived] = [e for e in events if e["event_kind"] == "thing_arrived"]
        assert arrived["event_id"] == str(taken.bound.event_id)
        # Nobody's request sends a visitor from outside anywhere: its program decides for it.
        scope, _, society_route = routes(world)
        places = client.get(
            society_route, headers=OWNER, params={**scope, "places": "true"}
        ).json()["places"]
        [target] = [t for t in places["targets"] if t["origin"] == "thing"]
        asked = client.post(
            society_route + "/actions",
            headers=OWNER,
            params=scope,
            json={
                "idempotency_key": str(uuid.uuid4()),
                "base_tick": society["current_tick"],
                "base_state_sha256": society["state_sha256"],
                "subject_id": visitor["id"],
                "intent": {"kind": "go_to", "target_id": target["target_id"]},
            },
        )
        assert asked.status_code == 409, asked.text
        assert asked.json() == {"code": "invalid_society_action", "detail": "decided_from_outside"}
        assert _replayed(client, world)
        crossings.hand(society_id, departure(visitor["id"], 1))
        society = _step(client, world, society)
        assert not [p for p in society["state"]["inhabitants"] if p["came_by"] == "crossed"]
        left = [e for e in _events(client, world) if e["event_kind"] == "thing_departed"]
        assert [e["document"]["reason"] for e in left] == ["sent_home"]
        assert [each.bound.disposition for each in crossings.bound[society_id]] == [
            "arrived",
            "departed",
        ]
        assert _replayed(client, world)
        # A door whose bindings no longer say what the minutes did is refused by replay, by name,
        # and so is one that binds a crossing to a minute the society never ran.
        bound = crossings.bound[society_id]
        honest = list(bound)
        first = bound[0]
        bound[0] = dataclasses.replace(
            first, bound=first.bound._replace(disposition="refused", reason="visitor_limit")
        )
        assert _refused(client, world) == "society crossing replay mismatch"
        bound[:] = honest
        assert _replayed(client, world)
        extra = arrival(2)
        bound.append(
            ConsumedCrossing(
                99,
                extra,
                BoundCrossing(extra.crossing_id, "arrived", None, uuid.uuid4()),
            )
        )
        assert _refused(client, world) == "a crossing is bound to a minute the society never ran"


def test_a_host_that_does_not_offer_societies_of_things_refuses_one_by_name(world_app):
    world, offering, _, _ = world_app
    scope, _, society_route = routes(world)
    asked = {"region_id": world["binding"].region_id, "profile": V7}
    with TestClient(offering(False)) as client:
        _place(client, world, "well", "well", 2, -4_000, 2_000)
        refused = client.post(society_route, headers=OWNER, params=scope, json=asked)
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "society_engine_not_offered"
    # The positive control: a host that offers it makes the same society from the same request.
    with TestClient(offering(True)) as client:
        made = client.post(society_route, headers=OWNER, params=scope, json=asked)
        assert made.status_code in (200, 201), made.text


def test_a_minute_takes_a_bounded_number_of_crossings_and_the_rest_wait(world_app, crossings):
    world, make_app, _, _ = world_app
    with TestClient(make_app()) as client:
        _place(client, world, "well", "well", 2, -4_000, 2_000)
        _place(client, world, "gate", "gate", 1, 0, 6_000)
        society = _make_society(client, world)
        society_id = uuid.UUID(society["society_id"])
        for index in range(CROSSINGS_PER_MINUTE + 1):
            crossings.hand(society_id, arrival(index))
        society = _step(client, world, society)
        assert len(crossings.bound[society_id]) == CROSSINGS_PER_MINUTE
        _step(client, world, society)
        assert len(crossings.bound[society_id]) == CROSSINGS_PER_MINUTE + 1
        assert _replayed(client, world)


def test_a_society_that_took_crossings_replays_only_with_its_door_s_stream(world_app, crossings):
    world, make_app, _, _ = world_app
    with TestClient(make_app()) as client:
        _place(client, world, "well", "well", 2, -4_000, 2_000)
        _place(client, world, "gate", "gate", 1, 0, 6_000)
        society = _make_society(client, world)
        crossings.hand(uuid.UUID(society["society_id"]), arrival(1))
        _step(client, world, society)
        assert _replayed(client, world)  # the positive control, with the stream registered
        register_crossing_stream(None)
        assert _refused(client, world) == (
            "a society that took crossings replays only with its door's stream registered"
        )
