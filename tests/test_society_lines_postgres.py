"""A line said in a society of things, through the decision host and against PostgreSQL.

The application connects as a provisioned runtime role. Two knights stand placed beside each other
in a saved world; the world's owner chooses a model for the first, and the host asks it, through a
scripted model, before a minute. What is shown:

*   the host asks under the society of things' terms (the second prompt, a choice taking a line),
    and the receipt keeps the line beside the option it chose;
*   the minute says the line: a ``said`` event names it, whom it was said to and who heard it, the
    other knight keeps it among the lines it heard, and it is asked the next minute, whatever is
    under way for it;
*   replay regenerates the history from what was stored and asks no model;
*   a visitor's own program's line naming a name the account holder saved is never said
    (``line_refused_by_rules``), and the same answer naming nobody is.
"""

from __future__ import annotations

import dataclasses
import json
import time
import uuid

import pytest
from exulanica.api import decision_host as host_module
from exulanica.models.transport import HttpResponse
from exulanica.world.crossings import register_crossing_stream
from exulanica.world.society_controls import LEASE_SECONDS

import test_outside_deciders_postgres as outside
import test_society_person_decisions_postgres as decisions
import test_society_stay_requests_api as stays
import test_society_things_postgres as things_api
import things_society_support as things_support
from model_fakes import FakeTransport, chat_body
from test_society_saved_world_api import OWNER, routes

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres
LINE = "Good morning to you."


class _Speaker(FakeTransport):
    """A scripted model that says ``LINE`` to the other knight when it may, and otherwise waits."""

    def post_json(self, url, *, headers, payload, timeout):
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        properties = payload["tools"][0]["function"]["parameters"]["properties"]
        labels = properties["action"]["enum"]
        say = next(
            (label for label in labels if label.startswith("say something to the knight")), None
        )
        if say is not None:
            arguments = {"action": say, "line": LINE}
        else:
            wait = next(label for label in labels if label.startswith("wait"))
            arguments = {"action": wait, **({"line": None} if "line" in properties else {})}
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


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_line_a_model_chose_is_said_heard_and_replayed_without_asking(app):
    world, client = app
    client.app.state.services = dataclasses.replace(
        client.app.state.services, societies_of_things=True
    )
    services = decisions._services(client)
    things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
    things_api._place(client, world, "knight", "knight", 1, 3_000, 3_000)
    things_api._place(client, world, "knight-2", "knight", 1, 5_000, 3_000)
    snapshot = things_api._make_society(client, world)
    placed = {
        p["placed_id"]: p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed"
    }
    speaker, listener = placed["knight"], placed["knight-2"]
    manifest, model_id = decisions._offered()
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    decisions._choose(services, world, [speaker["id"]], model, manifest=manifest)
    transport = _Speaker()
    host = decisions._host(world, decisions._client(manifest, transport), services, manifest)
    for _ in range(10):
        assert host.before_minute(
            decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
        )
        receipts = decisions._decisions(services, world, snapshot)
        said = [r for r in receipts if (r["proposal"] or {}).get("line")]
        if said:
            break
        snapshot = stays._step(world, client, snapshot)
    else:
        raise AssertionError("the knight's model was never offered to say something in ten minutes")
    [receipt] = said
    assert receipt["provider"]["prompt_version"] == "society-person-choice/v2"
    assert receipt["proposal"]["line"] == LINE
    assert receipt["proposal"]["option"]["addressee_id"] == listener["id"]
    (tool,) = transport.requests[-1]["payload"]["tools"]
    assert "line" in tool["function"]["parameters"]["properties"]
    after = stays._step(world, client, snapshot)
    scope, _, society = routes(world)
    events = client.get(society + "/events", headers=OWNER, params=scope).json()["events"]
    [line] = [e for e in events if e["event_kind"] == "said"]
    assert line["subject_id"] == speaker["id"]
    assert line["document"]["thing"]["line"] == LINE
    assert line["document"]["thing"]["to"] == listener["id"]
    assert listener["id"] in line["document"]["thing"]["heard_by"]
    assert line["document"]["thing"]["decider"] == "model"
    heard = next(p for p in after["state"]["inhabitants"] if p["id"] == listener["id"])["heard"]
    assert heard[-1]["line"] == LINE and heard[-1]["from"] == speaker["id"]
    # Replay regenerates the same history from what was stored, and asks no model.
    asked = transport.call_count
    replayed = client.get(society + "/replay", headers=OWNER, params=scope)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"] is True
    assert transport.call_count == asked


class _SayingDoor(outside._Door):
    """An outside program's door whose player says ``self.line`` to everyone near when it may."""

    def __init__(self, line: str) -> None:
        super().__init__()
        self.line = line

    def answer(self, workspace_id, world_id, request, ends_at):
        result = super().answer(workspace_id, world_id, request, ends_at)
        options = request["context"]["options"]
        say = next((o for o in options if o["kind"] == "say_all"), None)
        if say is None:
            return result
        return {**result, "proposal": {"label": say["label"], "option": say, "line": self.line}}


def _visitor_says(world, client, line, monkeypatch):
    """A visitor crossed in beside a knight, its program saying ``line``; its receipts."""
    client.app.state.services = dataclasses.replace(
        client.app.state.services, societies_of_things=True
    )
    services = decisions._services(client)
    # The account holder's saved names, as the host reads them: here, one standing for any.
    monkeypatch.setattr(
        host_module,
        "recognised_spans",
        lambda text, names: [(0, len(text))] if SAVED in text else [],
    )
    stream = things_support.MemoryCrossings()
    register_crossing_stream(stream)
    try:
        things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
        things_api._place(client, world, "gate", "gate", 1, 0, 6_000)
        snapshot = things_api._make_society(client, world)
        stream.hand(
            uuid.UUID(snapshot["society_id"]), things_support.arrival(1, grant_id=outside.GRANT)
        )
        snapshot = stays._step(world, client, snapshot)
        host = outside._doorkeeping_host(world, services, _SayingDoor(line))
        for _ in range(5):
            assert host.before_minute(
                decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
            )
            receipts = decisions._decisions(services, world, snapshot)
            if receipts:
                return receipts
            snapshot = stays._step(world, client, snapshot)
    finally:
        register_crossing_stream(None)
    raise AssertionError("the visitor's program was never asked in five minutes")


#: A word standing for a name the account holder saved.
SAVED = "Ashworth"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_outside_program_s_line_carrying_a_saved_name_is_never_said(app, monkeypatch):
    world, client = app
    [receipt] = _visitor_says(world, client, f"Hello from {SAVED}.", monkeypatch)
    assert (receipt["status"], receipt["reason"], receipt["proposal"]) == (
        "rejected",
        "line_refused_by_rules",
        None,
    )
    assert receipt["provider"]["kind"] == "external"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_outside_program_s_line_naming_nobody_is_taken(app, monkeypatch):
    # The positive control for the refusal above: the same answer with a line naming nobody.
    world, client = app
    [receipt] = _visitor_says(world, client, "Hello, everyone.", monkeypatch)
    assert (receipt["status"], receipt["proposal"]["line"]) == ("accepted", "Hello, everyone.")
