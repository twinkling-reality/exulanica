"""A line said in a society of things, through the decision host and against PostgreSQL.

The application connects as a provisioned runtime role. Two knights stand placed beside each other
in a saved world; the world's owner chooses a model for the first, and the host asks it, through a
scripted model, before a minute. What is shown:

*   the host asks under the society of things' terms (the second prompt, a choice taking a line),
    and the receipt keeps the line beside the option it chose;
*   the minute says the line: a ``said`` event names it, whom it was said to and who heard it, and
    the other knight keeps it among the lines it heard (that it is then due, whatever is under way
    for it, is shown in memory, ``test_society_things.py``);
*   replay regenerates the history from what was stored and asks no model;
*   a visitor's own program's line naming a name the account holder saved is never said
    (``line_refused_by_rules``), and the same answer naming nobody is.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import time
import uuid

import pytest
from exulanica.api import decision_host as host_module
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import IdentityRepository, rename_entity
from exulanica.models.transport import HttpResponse
from exulanica.world.crossings import register_crossing_stream
from exulanica.world.society_controls import LEASE_SECONDS
from exulanica.world.society_decision_contract import person_role

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
            # The other knight, named as the page names it: "knight 2".
            (label for label in labels if label.startswith("say something to knight")),
            None,
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
    # Asked under the terms the registry states for the society of things.
    assert (
        receipt["provider"]["prompt_version"]
        == person_role().terms("exulanica-society/v7").prompt_version
    )
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


#: The line the knight's model says, and the name the account holder saves after it was said.
HEARD = "Hello, Hazel."
NAME = "Hazel Moss"


class _Greeter(FakeTransport):
    """A scripted model that says ``HEARD`` to everyone near when it may, and otherwise waits."""

    def post_json(self, url, *, headers, payload, timeout):
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        properties = payload["tools"][0]["function"]["parameters"]["properties"]
        labels = properties["action"]["enum"]
        say = next((label for label in labels if label.startswith("say something to every")), None)
        if say is not None:
            arguments = {"action": say, "line": HEARD}
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


class _Staying(outside._Door):
    """An outside program that keeps its visitor where it is: it waits whenever it may."""

    def answer(self, workspace_id, world_id, request, ends_at):
        options = request["context"]["options"]
        wait = next((option for option in options if option["kind"] == "wait"), None)
        if wait is None:
            return super().answer(workspace_id, world_id, request, ends_at)
        found = super().answer(
            workspace_id,
            world_id,
            {**request, "context": {**request["context"], "options": [wait]}},
            ends_at,
        )
        self.asked[-1] = copy.deepcopy(request)
        return found


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_heard_line_carrying_a_name_saved_later_is_left_out_of_an_outside_ask(app, monkeypatch):
    """A visitor heard a line naming nobody the account holder had saved; the holder then saves
    the name it carries. The visitor's program is still asked every minute, and is never shown
    that line again; a model's new line carrying the name is never said."""
    world, client = app
    client.app.state.services = dataclasses.replace(
        client.app.state.services, societies_of_things=True
    )
    services = decisions._services(client)
    stream = things_support.MemoryCrossings()
    register_crossing_stream(stream)
    try:
        things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
        things_api._place(client, world, "gate", "gate", 1, 0, 6_000)
        things_api._place(client, world, "knight", "knight", 1, 2_000, 4_000)
        snapshot = things_api._make_society(client, world)
        # The knight's model is chosen before its first minute, so its routine never walks it away:
        # the scripted model says something or waits a minute. A villager's routine may still stop
        # to talk to it, which keeps it where it stands, so it is asked again once the talk ends.
        [knight] = [p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed"]
        manifest, model_id = decisions._offered()
        model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
        decisions._choose(services, world, [knight["id"]], model, manifest=manifest)
        transport = _Greeter()
        speaking = decisions._host(
            world, decisions._client(manifest, transport), services, manifest
        )
        door = _Staying()
        listening = outside._doorkeeping_host(world, services, door)

        def minute(snapshot, *, visited=True):
            claim = decisions._claim(world, snapshot)
            assert speaking.before_minute(claim, time.monotonic() + LEASE_SECONDS)
            # Before the visitor is here, its program has nobody to be asked for.
            asked = listening.before_minute(claim, time.monotonic() + LEASE_SECONDS)
            assert asked or not visited
            return stays._step(world, client, snapshot)

        stream.hand(
            uuid.UUID(snapshot["society_id"]), things_support.arrival(1, grant_id=outside.GRANT)
        )
        snapshot = minute(snapshot, visited=False)
        [visitor] = [p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "crossed"]

        def heard(snapshot):
            person = next(p for p in snapshot["state"]["inhabitants"] if p["id"] == visitor["id"])
            return [line["line"] for line in person.get("heard", ())]

        # The visitor stays by the gate, near the knight, so it hears the knight's line the minute
        # the knight is next asked, at once unless a villager's talk holds the knight a while.
        for _ in range(30):
            snapshot = minute(snapshot)
            if HEARD in heard(snapshot):
                break
        else:
            raise AssertionError("the visitor never heard the knight in thirty minutes")
        # The positive control: asked now, its program is shown the line it heard.
        door.asked.clear()
        snapshot = minute(snapshot)
        [shown] = [r for r in door.asked if r["subject_id"] == visitor["id"]]
        assert HEARD in [line["line"] for line in shown["context"]["heard"]]
        # The account holder saves the name the line carries.
        connection = world["connection"]
        identity = IdentityRepository(connection, world["workspace"])
        rename_entity(
            identity,
            AssertionWriter(connection, world["workspace"]),
            entity_id=identity.entities.create(entity_class="person"),
            display_name=NAME,
            actor=world["session"].actor,
        )
        connection.commit()
        door.asked.clear()
        before = len(transport.requests)
        # What every model ask is handed from now on: the names no line it writes may carry.
        handed: list[tuple[str, ...]] = []
        asking = host_module.ask

        def recording(client, asked, *args, **kwargs):
            handed.append(tuple(name.name for name in asked.names))
            return asking(client, asked, *args, **kwargs)

        monkeypatch.setattr(host_module, "ask", recording)
        snapshot = minute(snapshot)
        # Still asked, and never shown the line again, though the visitor still holds it.
        assert HEARD in heard(snapshot)
        [asked] = [r for r in door.asked if r["subject_id"] == visitor["id"]]
        assert HEARD not in [line["line"] for line in asked["context"]["heard"]]
        assert NAME.split()[0] not in json.dumps(asked["context"])
        # And the knight's model, asked again, may not say the name now saved: its next line
        # carrying it is refused, though the rules alone would let it through.
        for _ in range(10):
            if len(transport.requests) > before:
                break
            snapshot = minute(snapshot)
        else:
            raise AssertionError("the knight's model was never asked again in ten minutes")
        receipts = decisions._decisions(services, world, snapshot)
        latest = [r for r in receipts if r["subject_id"] == knight["id"]][-1]
        assert (latest["status"], latest["reason"]) == ("rejected", "line_refused_by_rules")
        # The host handed the knight's ask the name the account holder saved, so a line carrying it
        # is refused even where the workspace's rules would release it to the model.
        assert handed and all(NAME in names for names in handed)
    finally:
        register_crossing_stream(None)
