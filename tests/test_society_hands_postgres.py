"""A being's hands in a society of things, through the decision host and against PostgreSQL.

The application connects as a provisioned runtime role. In a saved world a knight stands near a
sword and another knight; the world's owner chooses a model for the first knight, and the host asks
it, through a scripted model, before each minute. What is shown:

*   the society records the hands module in its first input, and the knight is offered picking the
    sword up, walking first when it stands beyond reach;
*   it walks, picks the sword up into a hand that fits it, and gives it to the other knight, who
    offers to receive it; each act is an event naming the thing, the socket and the moment within
    the minute the later walk ended;
*   nobody is offered to give the sword to a villager, whose kind does not receive;
*   replay regenerates the history from what was stored and asks no model.
"""

from __future__ import annotations

import dataclasses
import json
import time

import pytest
from exulanica.abilities.registry import HANDS
from exulanica.models.transport import HttpResponse
from exulanica.world.society_controls import LEASE_SECONDS

import test_society_person_decisions_postgres as decisions
import test_society_stay_requests_api as stays
import test_society_things_postgres as things_api
from model_fakes import FakeTransport, chat_body
from test_society_saved_world_api import OWNER, routes

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres


class _Hands(FakeTransport):
    """A scripted model that picks the sword up when it may, gives it to the knight when it may,
    and otherwise waits."""

    def post_json(self, url, *, headers, payload, timeout):
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        properties = payload["tools"][0]["function"]["parameters"]["properties"]
        labels = properties["action"]["enum"]
        chosen = next(
            # The other knight, named as the page names it: "knight 2".
            (label for label in labels if label.startswith("give the sword to knight")),
            next(
                (label for label in labels if label.startswith("pick up the sword")),
                next(label for label in labels if label.startswith(("wait", "carry on"))),
            ),
        )
        arguments = {"action": chosen, **({"line": None} if "line" in properties else {})}
        body = chat_body("", model=payload["model"], finish_reason="tool_calls")
        body["choices"][0]["message"]["content"] = None
        body["choices"][0]["message"]["tool_calls"] = [
            {
                "id": "c",
                "type": "function",
                "function": {"name": "act", "arguments": json.dumps(arguments)},
            }
        ]
        return HttpResponse(200, json.dumps(body))


def _offered(transport) -> list[str]:
    return [
        label
        for request in transport.requests
        for label in request["payload"]["tools"][0]["function"]["parameters"]["properties"][
            "action"
        ]["enum"]
    ]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_knight_picks_up_a_sword_and_gives_it_to_another_knight(app):
    world, client = app
    client.app.state.services = dataclasses.replace(
        client.app.state.services, societies_of_things=True
    )
    services = decisions._services(client)
    things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
    things_api._place(client, world, "knight", "knight", 1, 3_000, 3_000)
    things_api._place(client, world, "knight-2", "knight", 1, 6_000, 3_000)
    things_api._place(client, world, "sword", "sword", 2, 5_000, 1_000)
    snapshot = things_api._make_society(client, world)
    assert HANDS in snapshot["state"]["modules"]
    placed = {
        p["placed_id"]: p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed"
    }
    giver, taker = placed["knight"], placed["knight-2"]
    manifest, model_id = decisions._offered()
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    decisions._choose(services, world, [giver["id"]], model, manifest=manifest)
    transport = _Hands()
    host = decisions._host(world, decisions._client(manifest, transport), services, manifest)
    scope, _, society = routes(world)

    def events(kind):
        found = client.get(society + "/events", headers=OWNER, params=scope).json()["events"]
        return [e for e in found if e["event_kind"] == kind]

    for _ in range(20):
        assert host.before_minute(
            decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
        )
        snapshot = stays._step(world, client, snapshot)
        if events("gave"):
            break
    else:
        raise AssertionError("the knight never gave the sword in twenty minutes")
    [picked] = events("picked_up")
    [gave] = events("gave")
    assert picked["subject_id"] == giver["id"] and gave["subject_id"] == giver["id"]
    sword = next(t for t in snapshot["state"]["things"] if t["placed_id"] == "sword")
    assert picked["document"]["thing"]["thing"] == sword["id"]
    assert gave["document"]["thing"]["with"] == taker["id"]
    assert (sword["held_by"], sword["position_mm"]) == (taker["id"], None)
    assert sword["socket"] == gave["document"]["thing"]["socket"]
    assert 0 <= picked["document"]["at_ms"] <= 59_999
    # Nobody was offered to give it to a villager, whose kind does not receive.
    assert not [
        label for label in _offered(transport) if "(a villager)" in label and "give" in label
    ]
    # The sword stays in the other knight's hand: the author's placement of it still stands.
    snapshot = stays._step(world, client, snapshot)
    sword = next(t for t in snapshot["state"]["things"] if t["placed_id"] == "sword")
    assert sword["held_by"] == taker["id"]
    # Replay regenerates the history from what was stored, and asks no model.
    asked = transport.call_count
    replayed = client.get(society + "/replay", headers=OWNER, params=scope)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"] is True
    assert transport.call_count == asked


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_request_that_fails_its_own_check_leaves_the_others_asked(app, monkeypatch):
    """A request refused by its own check (as two held things of one kind once offered one label
    twice) is undone alone: the minute's other subjects are still reserved and asked."""
    from exulanica.world import society_decision_repository as repository_module

    world, client = app
    client.app.state.services = dataclasses.replace(
        client.app.state.services, societies_of_things=True
    )
    services = decisions._services(client)
    things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
    things_api._place(client, world, "knight", "knight", 1, 3_000, 3_000)
    things_api._place(client, world, "knight-2", "knight", 1, 6_000, 3_000)
    snapshot = things_api._make_society(client, world)
    placed = {
        p["placed_id"]: p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed"
    }
    manifest, model_id = decisions._offered()
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    decisions._choose(
        services,
        world,
        [placed["knight"]["id"], placed["knight-2"]["id"]],
        model,
        manifest=manifest,
    )
    live = repository_module.SocietyDecisionRepository.prepare_role
    refused = placed["knight"]["id"]
    attempted: list[str] = []

    def prepare_role(self, role, version_id, **kwargs):
        attempted.append(str(kwargs["subject_id"]))
        if str(kwargs["subject_id"]) == refused:
            raise ValueError("a society_decision decision offers each label once")
        return live(self, role, version_id, **kwargs)

    monkeypatch.setattr(repository_module.SocietyDecisionRepository, "prepare_role", prepare_role)
    transport = _Hands()
    host = decisions._host(world, decisions._client(manifest, transport), services, manifest)
    for _ in range(20):
        attempted.clear()
        asked = len(transport.requests)
        assert host.before_minute(
            decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
        )
        # A minute in which both were due: the first one's request failed its own check.
        if set(attempted) == {refused, placed["knight-2"]["id"]}:
            break
        snapshot = stays._step(world, client, snapshot)
    else:
        raise AssertionError("both knights were never due in one minute")
    # The second knight was asked in that minute although the first one's request was not made.
    assert len(transport.requests) == asked + 1
