"""A model-run person stops to talk, as the deployed database and the host take it.

The host's decision phase asks a scripted model behind the real client, as playback asks before
a minute, and the minute is taken through the steps route (``test_society_person_decisions_
postgres`` builds the world, the choices and the host). What is shown:

*   a model's choice to talk with somebody is applied, both people talk, the models route reads
    what it chose, and replay regenerates the history with no model call;
*   a conversation the workspace's rules would change is left out of what is offered, never sent
    and never rewritten, and the person is asked the rest;
*   no simulated person's name reaches a model: the other person is a number.
"""

from __future__ import annotations

import json
import re
import time

import pytest
from exulanica.world.society_controls import LEASE_SECONDS
from exulanica.world.society_decision_contract import decision_contract

import test_society_person_decisions_postgres as pg
from model_fakes import FakeTransport, chat_body

saved_world = pg.saved_world
app = pg.app
pytestmark = pytest.mark.postgres

#: How a conversation's label begins, read from the contract's own words.
TALK = pg._TALK_LABEL


class _Talker(FakeTransport):
    """A scripted model that stops to talk whenever it may, and otherwise goes somewhere."""

    def post_json(self, url, *, headers, payload, timeout):
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        enum = payload["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
        chosen = next((a for a in enum if a.startswith(TALK)), None) or next(
            a for a in enum if a != decision_contract().words["wait"]
        )
        body = chat_body("", model=payload["model"], finish_reason="tool_calls")
        body["choices"][0]["message"]["content"] = None
        body["choices"][0]["message"]["tool_calls"] = [
            {
                "id": "c",
                "type": "function",
                "function": {"name": "act", "arguments": json.dumps({"action": chosen})},
            }
        ]
        return pg.HttpResponse(200, json.dumps(body))


def _played(world, client, services, manifest, transport, *, minutes, rules=None):
    """The square with everybody run by the scripted model for ``minutes`` minutes."""
    snapshot = pg.stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model_id = manifest_model(manifest)
    pg._choose(
        services,
        world,
        people,
        {"provider": manifest.spec(model_id).provider, "model_id": model_id},
        manifest=manifest,
    )
    host = pg._host(world, pg._client(manifest, transport), services, manifest)
    if rules is not None:
        host = pg.dataclasses.replace(host, policy_for=lambda workspace_id: rules)
    for _ in range(minutes):
        host.before_minute(pg._claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
        snapshot = pg.stays._step(world, client, snapshot)
    return snapshot


def manifest_model(manifest):
    return next(spec.model_id for spec in manifest.offered_models(pg.Role.SOCIETY_DECISION))


def _sent_labels(transport):
    return [
        label
        for request in transport.requests
        for label in request["payload"]["tools"][0]["function"]["parameters"]["properties"][
            "action"
        ]["enum"]
    ]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_model_s_choice_to_talk_is_applied_both_talk_and_replay_asks_nothing(app):
    world, client = app
    services = pg._services(client)
    manifest, _model = pg._offered()
    transport = _Talker()
    snapshot = _played(world, client, services, manifest, transport, minutes=8)
    scope, _, society = pg.routes(world)
    events = client.get(society + "/events", headers=pg.OWNER, params=scope)
    events = events.json()["events"]
    chose_talk = [
        e
        for e in events
        if e["event_kind"] == "decision_applied"
        and e["document"]["disposition"] == "applied"
        and (e["document"]["chose"] or "").startswith(TALK)
    ]
    assert chose_talk, "no model's choice to talk was applied in eight minutes"
    people = {p["id"]: p for p in snapshot["state"]["inhabitants"]}
    # The goal the minute gave the chooser is a talk with the person the label numbers.
    goals = [
        e
        for e in events
        if e["event_kind"] == "goal_selected"
        and e["document"]["reason"] == "chosen_by_their_model"
        and (e["document"]["goal"] or {}).get("kind") == "talk"
    ]
    assert goals
    for event in goals:
        partner = people[event["document"]["goal"]["partner_id"]]
        applied = next(
            e
            for e in chose_talk
            if e["tick"] == event["tick"] and e["subject_id"] == event["subject_id"]
        )
        assert applied["document"]["chose"].startswith(f"{TALK}{partner['ordinal'] + 1},")
    started = [e for e in events if e["document"]["outcome"] == "talk_started"]
    assert started, "nobody a model chose a talk for ever began talking"
    # The receipt the decisions route reads back holds the conversation as the model chose it.
    read = client.get(
        society + "/decisions/" + chose_talk[0]["document"]["request_id"],
        headers=pg.OWNER,
        params=scope,
    )
    assert read.status_code == 200, read.text
    option = read.json()["decision"]["proposal"]["option"]
    assert option["kind"] == "talk" and option["partner_id"] in people
    assert option["label"] == chose_talk[0]["document"]["chose"]
    asked = transport.call_count
    replayed = client.get(society + "/replay", headers=pg.OWNER, params=scope)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"] is True
    assert transport.call_count == asked


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_conversation_the_workspace_rules_would_change_is_left_out_and_the_rest_asked(app):
    world, client = app
    services = pg._services(client)
    manifest, _model = pg._offered()
    transport = _Talker()
    rules = pg._Changing(TALK.strip())
    snapshot = _played(world, client, services, manifest, transport, minutes=6, rules=rules)
    # The rules were shown the conversations, and would have changed them.
    assert any(text.startswith(TALK) for text in rules.shown), "no conversation was offered"
    sent = _sent_labels(transport)
    assert sent, "nobody was asked the rest"
    assert not any(label.startswith(TALK) for label in sent)
    # Everybody reserved was asked the rest and answered: nobody was refused at the boundary for
    # an option the rules would change, which would have left them to the routine.
    receipts = pg._decisions(services, world, snapshot)
    assert receipts and {r["reason"] for r in receipts} == {"validated_choice"}
    assert transport.call_count == len(receipts)
    # Nothing sent was rewritten: every label is one the rules left as it was.
    assert not any("[place A]" in label for label in sent)
    for request in transport.requests:
        assert "[place A]" not in json.dumps(request["payload"]["messages"])


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_no_simulated_person_s_name_reaches_a_model(app):
    world, client = app
    services = pg._services(client)
    manifest, _model = pg._offered()
    transport = _Talker()
    snapshot = _played(world, client, services, manifest, transport, minutes=6)
    parts = sorted(
        {
            part
            for person in snapshot["state"]["inhabitants"]
            for part in person["display_name"].split()
            if part.isalpha()
        }
    )

    def named(text: str) -> list[str]:
        return [
            part for part in parts if re.search(rf"(?<![a-z]){part}(?![a-z])", text, re.IGNORECASE)
        ]

    # A positive control: the search finds a name where one is.
    assert named(f"talk with {parts[0].lower()}, 4 m away") == [parts[0]]
    sent = [json.dumps(request["payload"]) for request in transport.requests]
    assert sent and any(TALK in text for text in sent), "no conversation was offered to a model"
    assert [named(text) for text in sent] == [[] for _ in sent]
