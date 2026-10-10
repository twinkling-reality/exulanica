"""The Companion's steps that spend nothing, through the application and PostgreSQL.

In a saved world on a host that offers societies of things, as its owner, with the model scripted:

*   "move the well here" and "remove the well" are each one step, the things route's own request,
    planned without writing anything; sent, each is the route's own edit, which the outcome read
    credits, and a thing already taken away is blocked by the code the route answers;
*   "let me play the knight" is one step, the play route's request for that being; sent, the
    person plays it, a second ask changes nothing, and "give it back" is the route's give-back;
*   "send everyone away" and "bring them back" are each one step, the presence route's request at
    this minute; what the society already holds is refused by the name the route answers.

The drafter's option labels are read from the request the scripted model was sent
(``test_companion_things_postgres``).
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.selection.action_plan import (
    PLAY,
    PLAY_GIVE_BACK,
    PRESENCE,
    THING_MOVE,
    THING_REMOVE,
)

import test_companion_minds_postgres as minds
import test_companion_things_postgres as things
import test_society_saved_world_api as saved_world_api
from test_society_saved_world_api import OWNER, routes

companion = things.companion
saved_world = things.saved_world
saved_world_app = things.saved_world_app
pytestmark = pytest.mark.postgres


def _edit(transport, operation: str, *options: str):
    transport.responses[:] = [
        things._reply({"kind": "world_edit"}),
        things._reply({"steps": [{"operation": operation, "options": list(options)}]}),
    ]


def _simulation(transport, action: str):
    transport.responses[:] = [
        things._reply({"kind": "simulation"}),
        things._reply({"action": action, "speed": None, "minutes": None}),
    ]


def _edited(sent) -> dict:
    version = sent.json()
    return {"status": sent.status_code, **{k: version[k] for k in ("edit_seq", "state_sha256")}}


def test_a_placed_thing_is_moved_and_taken_away_by_the_things_routes(companion):
    world, client, transport = companion
    things._place(client, world, "well", "well", 2, -4_000, 2_000)
    labels = things._look(client, world, transport, "move the well here")
    well = things._label(labels, "well")
    before = things._counts(world)
    _edit(transport, "move_object", well)
    plan = things._ask(client, world, "move the well here")

    assert plan["outcome"] == "plan", things._why(plan)
    assert things._counts(world) == before, "planning wrote something"
    [step] = plan["steps"]
    assert (step["operation"], step["state"]) == (THING_MOVE, "prepared")
    assert step["bind"]["thing_id"] == "well" and step["titles"] == {"thing": "well"}
    pose = step["body"]["pose"]
    # The spot the page pointed at, 3.5 m ahead of the person, is free: the well stands there.
    assert (pose["x_mm"], pose["z_mm"]) == (things.SPOT["x_mm"], things.SPOT["z_mm"])
    sent = things._send(client, step)
    assert sent.status_code == 200, sent.text
    [moved] = [thing for thing in sent.json()["things"] if thing["thing_id"] == "well"]
    assert (moved["transform"]["x_mm"], moved["transform"]["z_mm"]) == (pose["x_mm"], pose["z_mm"])
    read = things._outcome(client, world, plan, [{**step, "answer": _edited(sent)}])
    assert read["state"] == "applied"
    assert read["steps"][0]["receipts"][0]["kind"] == "move_thing"

    labels = things._look(client, world, transport, "remove the well")
    _edit(transport, "remove_object", things._label(labels, "well"))
    removal = things._ask(client, world, "remove the well")
    assert removal["outcome"] == "plan", things._why(removal)
    [step] = removal["steps"]
    assert (step["operation"], step["bind"]["thing_id"]) == (THING_REMOVE, "well")
    gone = things._send(client, step)
    assert gone.status_code == 200, gone.text
    [removed] = [thing for thing in gone.json()["things"] if thing["thing_id"] == "well"]
    assert removed["removed"] is True
    read = things._outcome(client, world, removal, [{**step, "answer": _edited(gone)}])
    assert read["state"] == "applied"
    assert read["steps"][0]["receipts"][0]["kind"] == "remove_thing"

    # Taken away already: the route refuses a second removal, and a plan states the same code.
    scope, root, _ = routes(world)
    base = things._version(client, world)["state_sha256"]
    again = client.post(
        root + "/things/well/remove", headers=OWNER, params=scope, json={"base_state_sha256": base}
    )
    assert again.status_code == 409, again.text
    prepared = things._prepare(client, world, [{"operation": "remove_thing", "thing_id": "well"}])
    assert prepared["outcome"] == "refused"
    assert prepared["steps"][0]["code"] == again.json()["code"] == "invalid_object_state"


def test_a_being_is_played_and_given_back_by_the_play_routes(companion):
    world, client, transport = companion
    society = minds._town(client, world)
    [knight] = minds._of_kind(society, "knight")
    labels = things._look(client, world, transport, "let me play the knight")
    being = things._label(labels, "Knight", starts=True)
    before = minds._choices(world)
    _edit(transport, "play_being", being)
    plan = things._ask(client, world, "let me play the knight")

    assert plan["outcome"] == "plan", things._why(plan)
    assert plan["spends"] is False and minds._choices(world) == before
    [step] = plan["steps"]
    assert (step["operation"], step["state"]) == (PLAY, "prepared")
    assert step["body"]["subject_id"] == knight
    sent = things._send(client, step)
    assert sent.status_code == 201, sent.text
    play = sent.json()
    assert play["played_by_you"] is True
    read = things._outcome(
        client, world, plan, [{**step, "answer": {"status": 201, "choice_seq": play["choice_seq"]}}]
    )
    assert read["state"] == "applied"
    assert read["steps"][0]["receipts"][0]["subject_id"] == knight

    # Asked again while playing it: nothing to change. A mind for it is the route's own refusal.
    _edit(transport, "play_being", being)
    again = things._ask(client, world, "let me play the knight")
    assert again["outcome"] == "refused" and again["steps"][0]["code"] == "no_change"

    _edit(transport, "give_back")
    giving = things._ask(client, world, "give the knight back")
    assert giving["outcome"] == "plan", things._why(giving)
    [step] = giving["steps"]
    assert (step["operation"], step["bind"]["subject_id"]) == (PLAY_GIVE_BACK, knight)
    given = things._send(client, step)
    assert given.status_code == 200, given.text
    read = things._outcome(
        client,
        world,
        giving,
        [{**step, "answer": {"status": 200, "choice_seq": given.json()["choice_seq"]}}],
    )
    assert read["state"] == "applied"

    # Playing nobody: the route refuses a give-back by the name a plan states.
    scope, root, _ = routes(world)
    refused = client.post(
        root + f"/society/play/{knight}/give-back",
        headers=OWNER,
        params=scope,
        json={"idempotency_key": str(uuid.uuid4())},
    )
    assert refused.status_code == 409, refused.text
    _edit(transport, "give_back")
    idle = things._ask(client, world, "give the knight back")
    assert idle["outcome"] == "refused"
    assert idle["steps"][0]["code"] == refused.json()["code"] == "not_played"


def test_everyone_is_sent_away_and_brought_back_by_the_presence_route(companion):
    world, client, transport = companion
    # A society of things keeps its people; the saved world's own people may be sent away. With
    # nothing placed, bringing people in makes the engine whose people come and go.
    scope, _, society_route = routes(world)
    saved_world_api.place(client, world, "plate-1", 0, 2_000)
    saved_world_api.bring_inhabitants(client, world)
    _simulation(transport, "send_away")
    plan = things._ask(client, world, "send everyone away")

    assert plan["outcome"] == "plan", things._why(plan)
    assert plan["kind"] == "simulation" and plan["spends"] is False
    [step] = plan["steps"]
    assert (step["operation"], step["state"]) == (PRESENCE, "prepared")
    now = things._now(client, world)
    assert step["body"]["presence"] == "away"
    assert (step["body"]["base_tick"], step["body"]["base_state_sha256"]) == (
        now["current_tick"],
        now["state_sha256"],
    )
    sent = things._send(client, step)
    assert sent.status_code == 200, sent.text
    assert things._now(client, world)["state"]["presence"]["status"] == "away"
    read = things._outcome(client, world, plan, [{**step, "answer": {"status": 200}}])
    assert read["state"] == "applied"
    assert read["steps"][0]["receipts"][0]["presence"] == "away"
    unsent = things._outcome(client, world, plan, [step])
    assert unsent["steps"][0]["state"] == "not_applied"

    # Away already: the route refuses by the name a plan states.
    gone = things._now(client, world)
    refused = client.post(
        society_route + "/presence",
        headers=OWNER,
        params=scope,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "presence": "away",
            "base_tick": gone["current_tick"],
            "base_state_sha256": gone["state_sha256"],
        },
    )
    assert refused.status_code == 409, refused.text
    _simulation(transport, "send_away")
    again = things._ask(client, world, "send everyone away")
    assert again["outcome"] == "refused"
    assert again["steps"][0]["code"] == refused.json()["code"] == "nobody_to_send_away"

    _simulation(transport, "bring_back")
    back = things._ask(client, world, "bring them back")
    assert back["outcome"] == "plan", things._why(back)
    [step] = back["steps"]
    assert step["body"]["presence"] == "here"
    returned = things._send(client, step)
    assert returned.status_code == 200, returned.text
    assert things._now(client, world)["state"]["presence"]["status"] == "here"


def test_a_society_that_keeps_its_people_refuses_sending_them_away_by_the_read_s_own_code(
    companion,
):
    world, client, transport = companion
    minds._town(client, world)
    _simulation(transport, "send_away")
    refused = things._ask(client, world, "send everyone away")
    assert refused["outcome"] == "refused"
    assert refused["refusal"]["code"] == "action_unsupported"
    assert refused["refusal"]["capability"]["code"] == "engine_keeps_its_people"
    # The route answers the same request by the same name.
    scope, _, society_route = routes(world)
    now = things._now(client, world)
    sent = client.post(
        society_route + "/presence",
        headers=OWNER,
        params=scope,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "presence": "away",
            "base_tick": now["current_tick"],
            "base_state_sha256": now["state_sha256"],
        },
    )
    assert (sent.status_code, sent.json()["code"]) == (409, "engine_keeps_its_people")
