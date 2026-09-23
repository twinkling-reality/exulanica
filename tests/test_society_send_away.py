"""A person can send their world's inhabitants away and bring them back, and history stays whole.

Sending everyone away is one recorded minute in which each person leaves; bringing them back is
another in which the same people arrive. Neither deletes or rewrites anything: every state before
the departure is still what replay rebuilds, and the return is a new arrival rather than an undo.
The person asks; the server decides against the exact state the person saw, and names what stands
in the way.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.world.society import society_state_sha256
from exulanica.world.society_planner import advance_purposeful_society, initial_purposeful_society
from exulanica.world.society_presence import (
    AWAY,
    HERE,
    PresenceRefused,
    change_presence,
    presence,
    presence_request,
)
from fastapi.testclient import TestClient

import test_society_authored_ground as authored
import test_society_saved_world_api as api
from test_society_authored_world_postgres import (  # noqa: F401
    create_society,
    place_object,
    saved_world,
    society_repository,
)
from test_society_saved_world_objects import second, world

world_app = api.world_app
SEED = "7a" * 32
SOCIETY = uuid.UUID(int=11)
OWNER_ID = uuid.UUID(int=12)


def _ask(state, wanted):
    return presence_request(state, request_id=uuid.uuid4(), requested_by=OWNER_ID, wanted=wanted)


def _started(ticks=3):
    document = second(authored.endless(), world())
    state = initial_purposeful_society(SOCIETY, SEED, document, population=8)
    for _ in range(ticks):
        state, _ = advance_purposeful_society(state, SEED, [document])
    return document, state


def test_sending_everyone_away_is_a_minute_in_which_each_person_leaves():
    document, before = _started()
    gone, events = change_presence(before, SEED, [document], _ask(before, AWAY), population=8)
    assert gone["tick"] == before["tick"] + 1 and gone["inhabitants"] == []
    assert presence(gone) == AWAY and gone["presence"]["since_tick"] == gone["tick"]
    assert [e.kind for e in events] == ["departed"] * 8
    assert [str(e.subject_id) for e in events] == [p["id"] for p in before["inhabitants"]]
    assert all(e.document["reason"] == "sent_away" for e in events)
    # Where each person stood when they left is in their event; nothing of it is lost.
    assert [e.document["position_mm"] for e in events] == [
        p["position_mm"] for p in before["inhabitants"]
    ]
    # Time goes on while they are away, and nobody is in it.
    later, quiet = advance_purposeful_society(gone, SEED, [document])
    assert later["inhabitants"] == [] and quiet == ()


def test_bringing_them_back_is_a_new_arrival_of_the_same_people():
    document, before = _started()
    gone, _ = change_presence(before, SEED, [document], _ask(before, AWAY), population=8)
    back, events = change_presence(gone, SEED, [document], _ask(gone, HERE), population=8)
    assert presence(back) == HERE and back["presence"]["since_tick"] == back["tick"]
    assert [e.kind for e in events] == ["arrived"] * 8
    # The same identities and names as the people who left.
    assert [(p["id"], p["display_name"]) for p in back["inhabitants"]] == [
        (p["id"], p["display_name"]) for p in before["inhabitants"]
    ]
    # They arrive as people first arrive, with no goal, at spread places clear of every
    # destination: nobody is put back into the middle of what they were doing.
    genesis = initial_purposeful_society(SOCIETY, SEED, document, population=8)
    assert [p["position_mm"] for p in back["inhabitants"]] == [
        p["position_mm"] for p in genesis["inhabitants"]
    ]
    assert all(p["goal"] is None for p in back["inhabitants"])
    # And they go on living.
    _, events = advance_purposeful_society(back, SEED, [document])
    assert any(e.kind == "goal_selected" for e in events)


@pytest.mark.parametrize(
    ("wanted", "code"), [(AWAY, "nobody_to_send_away"), (HERE, "already_here")]
)
def test_a_request_the_state_cannot_honour_is_refused_by_name(wanted, code):
    document, state = _started()
    if wanted == AWAY:
        state, _ = change_presence(state, SEED, [document], _ask(state, AWAY), population=8)
    with pytest.raises(PresenceRefused) as refused:
        change_presence(state, SEED, [document], _ask(state, wanted), population=8)
    assert refused.value.code == code


def test_a_request_made_against_another_state_is_refused():
    document, state = _started()
    stale = _ask(state, AWAY)
    moved, _ = advance_purposeful_society(state, SEED, [document])
    with pytest.raises(ValueError, match="not bound to this state"):
        change_presence(moved, SEED, [document], stale, population=8)


# Through PostgreSQL: recorded, replayed and reopened.


def _step(repository, version_id, society):
    return repository.advance(
        version_id, base_tick=society["current_tick"], base_state_sha256=society["state_sha256"]
    )


def _change(repository, version_id, society, wanted, actor, request_id=None):
    return repository.change_presence(
        version_id,
        wanted=wanted,
        request_id=request_id or uuid.uuid4(),
        requested_by=actor,
        base_tick=society["current_tick"],
        base_state_sha256=society["state_sha256"],
    )


@pytest.mark.postgres
def test_replay_crosses_a_departure_and_a_return_minute_by_minute(saved_world):  # noqa: F811
    world = saved_world
    place_object(world, world["plate"], "object:cushion", 3_000, 5_000)
    society, _ = create_society(world)
    version_id, actor = world["binding"].version_id, world["session"].actor
    repository = society_repository(world)
    live = [society["state_sha256"]]
    for _ in range(3):
        society = _step(repository, version_id, society)
        live.append(society["state_sha256"])
    society = _change(repository, version_id, society, AWAY, actor)
    live.append(society["state_sha256"])
    assert society["state"]["inhabitants"] == []
    for _ in range(2):
        society = _step(repository, version_id, society)
        live.append(society["state_sha256"])
    society = _change(repository, version_id, society, HERE, actor)
    live.append(society["state_sha256"])
    for _ in range(2):
        society = _step(repository, version_id, society)
        live.append(society["state_sha256"])
    assert len(society["state"]["inhabitants"]) == 8
    replayed = society_repository(world).replay(version_id)
    assert replayed["replay_verified"] and replayed["state_sha256"] == live[-1]
    # Replay checks every transition's digest as it rebuilds it, so the stored transitions are
    # the live run's own states, minute by minute, across both changes.
    stored = [
        row["state_sha256"]
        for row in world["connection"]
        .execute(
            "select state_sha256 from world_society_transition where workspace_id=%s "
            "and society_id=%s order by tick",
            (world["workspace"], society["society_id"]),
        )
        .fetchall()
    ]
    assert stored == live[1:]
    kinds = [
        (row["tick"], row["event_kind"])
        for row in society_repository(world).events(version_id, limit=256)
        if row["event_kind"] in ("departed", "arrived")
    ]
    assert sorted({tick for tick, _ in kinds}) == [4, 7]
    assert sorted(kinds).count((4, "departed")) == 8 and sorted(kinds).count((7, "arrived")) == 8


@pytest.mark.postgres
def test_a_world_reopened_while_they_are_away_has_nobody_in_it(saved_world):  # noqa: F811
    world = saved_world
    place_object(world, world["plate"], "object:cushion", 3_000, 5_000)
    society, _ = create_society(world)
    version_id, actor = world["binding"].version_id, world["session"].actor
    request_id = uuid.uuid4()
    gone = _change(society_repository(world), version_id, society, AWAY, actor, request_id)
    # Reopened by a runtime and a repository built again from nothing.
    from exulanica.api.society_runtime import SocietyRuntime

    rebuilt = SocietyRuntime(
        store=world["store"],
        authored_bindings=[world["binding"]],
        reviewed_affordances=world["registry"],
    )
    reopened = society_repository(world, rebuilt).snapshot(version_id, places=True)
    assert reopened["state"]["inhabitants"] == [] and reopened["population_size"] == 8
    assert reopened["state"]["presence"]["status"] == AWAY
    assert reopened["state_sha256"] == gone["state_sha256"]
    # An exact retry is answered with the society as it is, and changes nothing.
    again = _change(society_repository(world), version_id, society, AWAY, actor, request_id)
    assert again["state_sha256"] == gone["state_sha256"] and again["current_tick"] == 1
    # The authored world they lived in is untouched by their leaving.
    assert world["objects"].version(version_id).objects[0].object_id == "object:cushion"


@pytest.mark.postgres
def test_the_person_sends_everyone_away_and_brings_them_back_over_http(world_app):
    saved, make_app, _, _ = world_app
    scope, _, society_route = api.routes(saved)
    with TestClient(make_app()) as client:
        api.place(client, saved, "object:cushion", 3_000, 5_000)
        society = api.bring_inhabitants(client, saved).json()

        def ask(wanted, current, key=None):
            return client.post(
                society_route + "/presence",
                headers=api.OWNER,
                params=scope,
                json={
                    "idempotency_key": str(key or uuid.uuid4()),
                    "presence": wanted,
                    "base_tick": current["current_tick"],
                    "base_state_sha256": current["state_sha256"],
                },
            )

        refused = ask("here", society)
        assert refused.status_code == 409 and refused.json()["code"] == "already_here"
        gone = ask("away", society)
        assert gone.status_code == 200, gone.text
        assert gone.json()["state"]["inhabitants"] == []
        assert ask("away", society).status_code == 409  # the state moved on: stale
        nobody = ask("away", gone.json())
        assert nobody.status_code == 409 and nobody.json()["code"] == "nobody_to_send_away"
        read = client.get(society_route, headers=api.OWNER, params=scope).json()
        assert read["state"]["inhabitants"] == [] and read["state"]["presence"]["status"] == AWAY
        back = ask("here", read)
        assert back.status_code == 200, back.text
        assert len(back.json()["state"]["inhabitants"]) == 8
        # Another person's request never reaches this world.
        stranger = client.post(
            society_route + "/presence",
            headers=api.STRANGER,
            params=scope,
            json={
                "idempotency_key": str(uuid.uuid4()),
                "presence": "away",
                "base_tick": back.json()["current_tick"],
                "base_state_sha256": back.json()["state_sha256"],
            },
        )
        assert stranger.status_code == 404
        replay = client.get(society_route + "/replay", headers=api.OWNER, params=scope)
        assert replay.status_code == 200 and replay.json()["replay_verified"]


@pytest.mark.postgres
def test_a_waiting_directed_request_holds_the_minute_for_itself(saved_world):  # noqa: F811
    from exulanica.world.society_actions import ActionIntent

    from test_society_authored_world_postgres import action_repository

    world = saved_world
    place_object(world, world["plate"], "object:cushion", 3_000, 5_000)
    society, document = create_society(world)
    version_id, actor = world["binding"].version_id, world["session"].actor
    [cushion] = document["targets"]
    action_repository(world).create(
        version_id,
        request_id=uuid.uuid4(),
        requested_by=actor,
        subject_id=uuid.UUID(society["state"]["inhabitants"][-1]["id"]),
        base_tick=society["current_tick"],
        base_state_sha256=society["state_sha256"],
        intent=ActionIntent("perform", cushion["target_id"], "rest"),
    )
    with pytest.raises(PresenceRefused) as refused:
        _change(society_repository(world), version_id, society, AWAY, actor)
    assert refused.value.code == "a_request_is_waiting"
    assert society_state_sha256(society["state"]) == society["state_sha256"]
