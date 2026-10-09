"""The Companion's hands steps through the application and PostgreSQL.

In a saved world on a host that offers societies of things, as its owner, with the model scripted:
"give the knight a lantern" is a plan of two steps, a lantern placed beside the knight and the
knight asked to pick up that lantern by the id the first step was minted. Sent through the routes
the page sends them to, the second step waits for the minute that takes the lantern in, and the
minute that takes the request does the act as asked, which the outcome read credits.
"""

from __future__ import annotations

import pytest
from exulanica.selection.action_plan import DIRECT, THING_PLACE

import test_companion_things_postgres as cx1
import test_society_authored_world_postgres as helpers
import test_society_saved_world_api as saved_world_api
from test_companion_things_postgres import companion  # noqa: F401  (the fixture)
from test_society_saved_world_api import OWNER, routes

saved_world = helpers.saved_world
saved_world_app = saved_world_api.world_app
pytestmark = pytest.mark.postgres


def _events(client, world):
    scope, _, society_route = routes(world)
    read = client.get(society_route + "/events", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    return read.json()["events"]


def test_give_the_knight_a_lantern_places_it_then_asks_the_knight_to_pick_it_up(companion):  # noqa: F811
    world, client, transport = companion
    cx1._place(client, world, "well", "well", 2, -4_000, 2_000)
    cx1._place(client, world, "knight", "knight", 2, 3_000, 3_000)
    cx1._society(client, world)
    labels = cx1._look(client, world, transport, "give the knight a lantern")
    knight_label = cx1._label(labels, "Knight (kind: knight", starts=True)
    transport.responses[:] = [
        cx1._reply({"kind": "world_edit"}),
        cx1._reply(
            {
                "steps": [
                    {"operation": "place_thing", "options": ["lantern", knight_label]},
                    {"operation": "pick_up", "options": [knight_label, "lantern"]},
                ]
            }
        ),
    ]
    plan = cx1._ask(client, world, "give the knight a lantern")

    assert plan["outcome"] == "plan", cx1._why(plan)
    first, second = plan["steps"]
    knight = next(
        p for p in cx1._now(client, world)["state"]["inhabitants"] if p["placed_id"] == "knight"
    )
    assert (first["operation"], first["state"]) == (THING_PLACE, "prepared")
    assert (second["operation"], second["state"]) == (DIRECT, "pending")
    lantern_id = first["body"]["thing_id"]
    assert second["action"] == {
        "operation": "direct_thing",
        "act": "pick_up",
        "subject_id": knight["id"],
        "thing_id": lantern_id,
        "with_id": None,
    }
    assert second["titles"] == {"subject": "Knight", "act": "pick_up", "thing": "lantern"}
    assert cx1._send(client, first).status_code == 201

    # As the page does: prepared again a minute at a time while it says to wait, at most twenty.
    for _minutes in range(20):
        [prepared] = cx1._prepare(client, world, [second["action"]])["steps"]
        if prepared["state"] != "pending":
            break
        assert prepared["code"] in ("society_input_queued", "inhabitant_action_in_progress")
        cx1._minute(client, world)
    assert (prepared["state"], prepared["code"]) == ("prepared", None), prepared
    state = cx1._now(client, world)["state"]
    [lantern] = [t for t in state["things"] if t["placed_id"] == lantern_id]
    assert prepared["body"]["intent"] == {
        "kind": "hands",
        "ability": "pick_up",
        "thing_id": lantern["id"],
        "with_id": None,
    }
    sent = cx1._send(client, prepared)
    assert sent.status_code == 200, sent.text
    envelope = sent.json()

    for _minutes in range(1 + 3):
        cx1._minute(client, world)
        state = cx1._now(client, world)["state"]
        [lantern] = [t for t in state["things"] if t["placed_id"] == lantern_id]
        if lantern["held_by"] is not None:
            break
    assert lantern["held_by"] == knight["id"]
    # Only the knight has hands here, and the routine never picks anything up.
    picked = [event for event in _events(client, world) if event["event_kind"] == "picked_up"]
    assert [event["document"]["reason"] for event in picked] == ["asked_to_pick_up"]
    answer = {
        "status": 200,
        "request_id": envelope["request"]["request_id"],
        "document_sha256": envelope["request"]["document_sha256"],
    }
    read = cx1._outcome(client, world, plan, [{**prepared, "answer": answer}])
    assert read["steps"][0]["state"] == "applied", read
