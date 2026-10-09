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
*   replay regenerates the history from what was stored and asks no model;
*   the failing control: where the other knight, which the routine moves, has walked beyond the
    module's approach distance by the time the first is asked again, giving is never offered and
    no hand-over happens in twenty minutes.

The society's seed is the one input of these minutes that differs between runs: a world's own seed
derives from its id, which the fixture makes new each run. Under forty worlds' own seeds the sword
was not handed over within twenty minutes in four, so each test here chooses its seed.
"""

from __future__ import annotations

import dataclasses
import json
import math
import time

import pytest
from exulanica.abilities.registry import HANDS_FROM_OWN_SIDE
from exulanica.models.transport import HttpResponse
from exulanica.world.society_controls import LEASE_SECONDS
from exulanica.world.society_hands import approach_mm

import test_society_person_decisions_postgres as decisions
import test_society_stay_requests_api as stays
import test_society_things_postgres as things_api
from model_fakes import FakeTransport, chat_body
from society_seed_support import choose_society_seed
from test_society_saved_world_api import OWNER, routes

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres

#: A society seed under which the other knight stands within the approach distance when the first,
#: holding the sword, is next asked, so the sword is handed over in the third minute.
NEAR = "625fa188f3f60b26f3a5378131b84cac0d97602b2e655b02dd114896b5504c50"
#: A society seed under which the other knight walks toward the well while the first stands after
#: picking the sword up, and stays farther than the approach distance for twenty minutes.
FAR = "a2aaa14e5173ea468480c68fbc48005d6df31c1c3088af65110d13218f49dc96"


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


def _offered(transport, since: int = 0) -> list[str]:
    return [
        label
        for request in transport.requests[since:]
        for label in request["payload"]["tools"][0]["function"]["parameters"]["properties"][
            "action"
        ]["enum"]
    ]


def _knights(app, seed: str):
    """The saved world's society of things made from ``seed``: a well, a sword and two knights,
    the first decided by the scripted model through the host, the other by the routine."""
    world, client = app
    client.app.state.services = dataclasses.replace(
        client.app.state.services, societies_of_things=True
    )
    choose_society_seed(client.app, seed)
    services = decisions._services(client)
    things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
    things_api._place(client, world, "knight", "knight", 1, 3_000, 3_000)
    things_api._place(client, world, "knight-2", "knight", 1, 6_000, 3_000)
    things_api._place(client, world, "sword", "sword", 2, 5_000, 1_000)
    snapshot = things_api._make_society(client, world)
    assert HANDS_FROM_OWN_SIDE in snapshot["state"]["modules"]
    placed = {
        p["placed_id"]: p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed"
    }
    giver, taker = placed["knight"], placed["knight-2"]
    manifest, model_id = decisions._offered()
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    decisions._choose(services, world, [giver["id"]], model, manifest=manifest)
    transport = _Hands()
    host = decisions._host(world, decisions._client(manifest, transport), services, manifest)
    return snapshot, giver, taker, transport, host


def _events(client, world, kind):
    scope, _, society = routes(world)
    found = client.get(society + "/events", headers=OWNER, params=scope).json()["events"]
    return [e for e in found if e["event_kind"] == kind]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_knight_picks_up_a_sword_and_gives_it_to_another_knight(app):
    world, client = app
    snapshot, giver, taker, transport, host = _knights(app, NEAR)
    scope, _, society = routes(world)

    def events(kind):
        return _events(client, world, kind)

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
def test_no_hand_over_is_offered_to_a_knight_beyond_the_approach_distance(app):
    """The test above in a world whose other knight walks off: each time the first knight is asked
    holding the sword, the other stands farther than the approach distance, so giving is not
    offered, the scripted model waits, and twenty minutes pass with no hand-over."""
    world, client = app
    snapshot, giver, taker, transport, host = _knights(app, FAR)
    asked_holding = 0
    for minute in range(20):
        people = {p["id"]: p for p in snapshot["state"]["inhabitants"]}
        (gx, gz), (tx, tz) = people[giver["id"]]["position_mm"], people[taker["id"]]["position_mm"]
        holding = any(t["held_by"] == giver["id"] for t in snapshot["state"]["things"])
        before = len(transport.requests)
        assert host.before_minute(
            decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
        )
        offered = _offered(transport, before)
        if offered and holding:
            asked_holding += 1
            assert math.isqrt((gx - tx) ** 2 + (gz - tz) ** 2) > approach_mm()
            assert "put down the sword" in offered
            assert not [label for label in offered if label.startswith("give")], offered
        snapshot = stays._step(world, client, snapshot)
        # Read after each minute, while the minute's events are on the events read's first page.
        assert _events(client, world, "gave") == []
        if minute == 0:
            [picked] = _events(client, world, "picked_up")
            assert picked["subject_id"] == giver["id"]
    # Asked holding the sword in most of the twenty minutes, and still holding it.
    assert asked_holding >= 10
    sword = next(t for t in snapshot["state"]["things"] if t["placed_id"] == "sword")
    assert sword["held_by"] == giver["id"]


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


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_models_reads_judge_the_budget_by_the_terms_a_society_of_things_asks_under(app):
    """What is left fits the cheapest ask under the role's own terms only by taking the part kept
    for other work, and fits no ask under the longer terms a society of things asks its people
    under. Both models reads of a version whose society is a society of things say the whole
    budget is spent, where the role's own terms would say only the share is."""
    from decimal import Decimal

    from exulanica.api.decision_host import smallest_ask_usd
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.world.society_decision_contract import person_role

    world, client = app
    role = person_role()
    own, things = role.contract(), role.contract(role.terms("exulanica-society/v7").versions)
    manifest, _model_id = decisions._offered()
    probe = BudgetGuard(ceiling_usd=Decimal(1), max_calls=100)
    cheapest_own = smallest_ask_usd(role, probe, manifest, own)
    cheapest_things = smallest_ask_usd(role, probe, manifest, things)
    # The positive control: a ceiling between the two cheapest asks.
    assert cheapest_own < cheapest_things, (cheapest_own, cheapest_things)
    ceiling = ((cheapest_own + cheapest_things) / 2).quantize(Decimal("0.00000001"))
    model_client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=_Hands(),
        budget=BudgetGuard(ceiling_usd=ceiling, max_calls=100),
    )
    client.app.state.services = dataclasses.replace(
        client.app.state.services, societies_of_things=True
    )
    things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
    things_api._place(client, world, "knight", "knight", 1, 3_000, 3_000)
    things_api._make_society(client, world)
    listed = dataclasses.replace(
        client.app.state.services,
        model_client=model_client,
        society_control_workspaces=(world["workspace"],),
    )
    client.app.state.services = listed
    assert listed.model_host_refusal(world["workspace"], role) == "process_share_spent"
    assert (
        listed.model_host_refusal(world["workspace"], role, "exulanica-society/v7")
        == "process_budget_spent"
    )
    scope, version, society = routes(world)
    read = client.get(society + "/models", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    assert read.json()["host_refusal"] == "process_budget_spent"
    read = client.get(version + "/models", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    [person] = [entry for entry in read.json()["roles"] if entry["key"] == role.key]
    assert person["host_refusal"] == "process_budget_spent"
