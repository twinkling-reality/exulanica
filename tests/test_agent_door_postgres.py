"""An outside agent through the real door: the agent library against the deployed database.

The application runs as a provisioned runtime role over a saved world, with the agents' bridge
declared exactly as ``bridges/agents/examples/bridge-entry.json`` declares it (a poll held one
second for the test). The agent library's own requests reach the real routes through the
application's test client, so migration 0149's triggers, row-level security and the door's checks
are what answer. What is shown:

*   a world's owner lets an agent in with a grant and a key the owner mints (a program its owner
    runs), and the agent says hello with the agents' mapping, its library version and its
    declaration, which the owner then reads in the grant's view beside the bridge's words, who runs
    it and that its deciders are AI; the door keeps the declaration by its digest;
*   a declaration naming a host is refused by name, before any hello is stored;
*   revoking the grant ends the agent's turns and tells it in words, and a new key for the grant
    ends the earlier one, which tells its agent why;
*   the agent's tools over the real door answer with the permission and the rules, and decide a
    person's turn as an MCP client's model would, waiting for a turn and acting on it;
*   an agent given one of the world's own people decides that person's turn: its mind is handed
    exactly the messages and the function one of the world's own models is shown for the stored
    request, the host's receipt names the agents' bridge, the library's version, the grant and
    the mapping, the door keeps which declaration answered, the agent reads that its answer was
    taken, and the world replays with the agent gone;
*   an agent brings a body of its own in through a society of things' gate with the MCP tool: it
    arrives at the next minute wearing the first look the agents' mapping offers, the agent takes
    its body's turns, and when its program stops and starts again with the same key the body stays
    and its turns come to the new program; the world's models read names it as decided from
    outside by what the agent declared, and when its owner sends it home the agent reads why and
    acknowledges the departure once; the world replays with the agent gone.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.canonical import sha256_of_canonical
from exulanica.db.roles import provision_runtime_role
from exulanica.door.bridges import load_bridge_directory
from exulanica.door.channel import declared_sha256
from exulanica.door.crossings import DoorCrossings
from exulanica.door.runtime import DoorRuntime
from exulanica.models.manifest import AnsweringMechanism
from exulanica.world.crossings import register_crossing_stream
from exulanica.world.roles.person import LINE_KINDS
from exulanica.world.society_controls import LEASE_SECONDS
from exulanica.world.society_decision_contract import person_role
from exulanica.world.thing_library import shipped_looks
from fastapi.testclient import TestClient

import test_society_authored_world_postgres as helpers
import test_society_stay_requests_api as stays
from agent_support import PACKAGE, AgentError, Body, agent, agents_bridge, app_opener, facade
from conftest import scratch_role_database
from test_society_person_decisions_postgres import _claim, _decisions
from test_society_saved_world_api import OWNER, TOKEN, routes
from test_society_things_postgres import _make_society, _place, _replayed
from test_society_things_postgres import _step as _minute
from tests_support_api import EVERY_PERMISSION

saved_world = helpers.saved_world
pytestmark = pytest.mark.postgres
ROLE = "exulanica_agents_door_suite"
DECLARED = {"name": "Scout", "maker": "Acme", "mind": "Qwen/Qwen3-235B-A22B-Instruct-2507"}


def until(condition: Callable[[], bool], seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


@pytest.fixture
def door(saved_world, spine_schema, monkeypatch):
    """The application over the saved world as the runtime role, admitting outside agents, with
    the world's workspace among those the decision host asks for."""
    world = saved_world
    world["connection"].commit()
    _psycopg, scratch = spine_schema
    provision_runtime_role(world["connection"], role=ROLE)
    database = scratch_role_database(scratch, ROLE)
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {
                    "workspace_id": str(world["workspace"]),
                    "actor": str(world["session"].actor),
                    "permissions": EVERY_PERMISSION,
                }
            }
        ),
    )
    bridges = load_bridge_directory(
        {"EXULANICA_DOOR_BRIDGES": json.dumps([agents_bridge(hold_seconds=1)])}
    )
    services = Services(
        database=database,
        readonly_database=database,
        store=world["store"],
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
        society_runtime=SocietyRuntime(
            store=world["store"], authored_bindings=[], reviewed_affordances=world["registry"]
        ),
        society_control_workspaces=(world["workspace"],),
        door=DoorRuntime(database=database, bridges=bridges),
        # A body of the agent's own crosses into a society of things, which a host makes only when
        # it offers them.
        societies_of_things=True,
    )
    with TestClient(create_app(services, verify=False), raise_server_exceptions=False) as client:
        yield world, client, database, services


@pytest.fixture
def crossings():
    """The door's crossings handed to every society of things this process plays."""
    register_crossing_stream(DoorCrossings())
    try:
        yield
    finally:
        register_crossing_stream(None)


def _key(world: dict[str, Any], client: TestClient, **scope: Any) -> tuple[str, str]:
    """A grant letting an agent bring one body of its own, with ``scope`` (such as the gate it comes
    through) over it, and the key its owner mints for it."""
    issued = client.post(
        "/door/grants",
        headers=OWNER,
        params={"world_id": world["binding"].world_id},
        json={
            "idempotency_key": f"agent-{uuid.uuid4()}",
            "bridge": "agents",
            "visitors_maximum": 1,
            "kinds": ["agent"],
            # The version its visitor would arrive in; nothing asks for a society until one does.
            "version_id": str(world["binding"].version_id),
            "channel_credential": True,
            **scope,
        },
    )
    assert issued.status_code == 201, issued.text
    answer = issued.json()
    return answer["grant"]["grant_id"], answer["channel_credential"]["credential"]


def _named_key(world: dict[str, Any], client: TestClient, person: str) -> tuple[str, str]:
    """A grant letting an agent decide for one of the world's own people, and its key."""
    issued = client.post(
        "/door/grants",
        headers=OWNER,
        params={"world_id": world["binding"].world_id},
        json={
            "idempotency_key": f"agent-person-{uuid.uuid4()}",
            "bridge": "agents",
            "things": [person],
            "version_id": str(world["binding"].version_id),
            "channel_credential": True,
        },
    )
    assert issued.status_code == 201, issued.text
    answer = issued.json()
    return answer["grant"]["grant_id"], answer["channel_credential"]["credential"]


def _until_decided(world, client, services, snapshot) -> dict[str, Any]:
    """The world stepped, its host asking before each minute, until a person's turn is recorded."""
    host = services.decision_host()
    for _ in range(30):
        assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
        if _decisions(services, world, snapshot):
            return snapshot
        snapshot = stays._step(world, client, snapshot)
    raise AssertionError("the person reached no choice point in thirty minutes")


def _connect(client: TestClient, key: str, **declared: str) -> Body:
    return Body.connect(
        "http://127.0.0.1:9",
        key,
        **(declared or DECLARED),
        opener=app_opener(client),
    )


def test_an_agent_says_hello_and_its_owner_reads_who_it_says_it_is(door):
    world, client, database, _services = door
    grant_id, key = _key(world, client)
    body = _connect(client, key)
    try:
        assert body.permission["visitors_maximum"] == 1
        assert body.permission["may_speak"] is True
        assert body.permission["ended"] is None
        view = client.get(f"/door/grants/{grant_id}", headers=OWNER)
        assert view.status_code == 200, view.text
        grant = view.json()["grant"]
        entry = agents_bridge()
        assert (grant["bridge_label"], grant["run_by"], grant["ai"]) == (
            entry["label"],
            "owner",
            True,
        )
        assert grant["declared"] == DECLARED
        assert grant["adapter_version"] in entry["adapter_versions"]
        with database.session(world["workspace"]) as connection:
            stored = connection.execute(
                "select document from door_declaration where workspace_id = %s "
                "and declared_sha256 = %s",
                (world["workspace"], declared_sha256(DECLARED)),
            ).fetchone()
        assert stored is not None and stored["document"] == DECLARED
    finally:
        body.close(wait_seconds=5)


def test_a_declaration_naming_a_host_is_refused_by_name(door):
    world, client, _database, _services = door
    grant_id, key = _key(world, client)
    with pytest.raises(AgentError, match="declared"):
        _connect(client, key, name="Scout", maker="acme.ai")
    grant = client.get(f"/door/grants/{grant_id}", headers=OWNER).json()["grant"]
    assert grant["declared"] is None and grant["adapter_version"] is None


def test_revoking_the_grant_ends_the_agents_turns_and_tells_it(door):
    world, client, _database, _services = door
    grant_id, key = _key(world, client)
    body = _connect(client, key)
    try:
        revoked = client.post(f"/door/grants/{grant_id}/revoke", headers=OWNER)
        assert revoked.status_code == 200, revoked.text
        assert list(body.turns()) == []
        assert body.ended == "revoked"
        assert until(lambda: any(h.what == "permission_ended" for h in body.recent()))
        [ended] = [h for h in body.recent() if h.what == "permission_ended"]
        assert "the world's owner ended it" in ended.words
    finally:
        body.close(wait_seconds=5)


def test_the_agents_tools_answer_over_the_real_door(door):
    world, client, _database, _services = door
    _grant_id, key = _key(world, client)
    body = _connect(client, key)
    try:
        tools = facade.Facade(body)
        rules = tools.call("world_rules", {})
        assert not rules.is_error
        assert "You may bring in 1 body of your own" in rules.structured["rules"]
        assert rules.structured["permission"]["visitors_maximum"] == 1
        waited = tools.call("wait_for_turn", {"wait_seconds": 1})
        assert waited.structured["turn"] is None
    finally:
        body.close(wait_seconds=5)


def test_a_new_key_for_the_grant_ends_the_earlier_one_and_its_agent_reads_why(door):
    world, client, _database, _services = door
    grant_id, key = _key(world, client)
    body = _connect(client, key)
    try:
        made = client.post(f"/door/grants/{grant_id}/channel-credentials", headers=OWNER)
        assert made.status_code == 201, made.text
        assert until(lambda: body.ended is not None)
        assert body.ended == "unauthenticated"
        [stopped] = [h for h in body.recent() if h.what == "connection_ended"]
        assert "a new key from the world's owner ends the earlier one" in stopped.words
        assert key not in stopped.words
    finally:
        body.close(wait_seconds=5)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_agent_decides_for_a_person_and_the_world_replays_without_it(door):
    world, client, database, services = door
    snapshot = stays._inhabited(world, client)
    person = snapshot["state"]["inhabitants"][0]["id"]
    grant_id, key = _named_key(world, client, person)
    body = _connect(client, key)
    seen: list[Any] = []

    def mind() -> None:
        # A scripted mind: the first action offered, keeping what it was handed.
        for turn in body.turns():
            seen.append(turn)
            turn.act(turn.options[0].action)

    thread = threading.Thread(target=mind, daemon=True)
    thread.start()
    try:
        snapshot = _until_decided(world, client, services, snapshot)
        assert until(lambda: any(h.what == "answer_taken" for h in body.recent()))
    finally:
        body.close(wait_seconds=5)
        thread.join(5)
    [receipt] = _decisions(services, world, snapshot)
    assert (receipt["status"], receipt["reason"]) == ("accepted", "validated_choice")
    assert receipt["subject_id"] == person
    [turn] = seen
    assert receipt["proposal"]["label"] == turn.options[0].action
    with database.session(world["workspace"]) as connection:
        request = connection.execute(
            "select document from world_society_decision_request where workspace_id = %s "
            "and request_id = %s",
            (world["workspace"], turn.turn),
        ).fetchone()["document"]
        answer = connection.execute(
            "select declared_sha256 from door_answer where workspace_id = %s and request_id = %s",
            (world["workspace"], turn.turn),
        ).fetchone()
    # The agent's mind was handed exactly what one of the world's own models is shown.
    role = person_role()
    assert turn.messages == role.adapter.messages(
        role, request["context"], AnsweringMechanism.TOOL_CALL
    )
    assert turn.tool == role.choice(request["context"]).tool()
    assert turn.minute == request["base_tick"]
    record = receipt["provider"]
    assert (record["kind"], record["bridge"], record["adapter_version"], record["grant_id"]) == (
        "external",
        "agents",
        agent.VERSION,
        grant_id,
    )
    # The mapping this library version presents, pinned by the agents' bridge.
    presented = json.loads((PACKAGE / "outside-agents.v2.json").read_text(encoding="utf-8"))
    assert record["mapping_sha256"] == sha256_of_canonical(presented).hex()
    assert record["mapping_sha256"] in agents_bridge()["mapping_sha256"]
    assert "cost_usd" not in record
    assert answer["declared_sha256"] == declared_sha256(DECLARED)
    [taken] = [h for h in body.recent() if h.what == "answer_taken"]
    assert taken.thing == person and turn.options[0].action in taken.words
    # The minute applies the agent's choice, and replay regenerates the world with the agent gone.
    stays._step(world, client, snapshot)
    scope, _, society = routes(world)
    replayed = client.get(society + "/replay", headers=OWNER, params=scope)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"] is True


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_agents_tools_decide_a_persons_turn_over_the_real_door(door):
    world, client, _database, services = door
    snapshot = stays._inhabited(world, client)
    person = snapshot["state"]["inhabitants"][0]["id"]
    _grant_id, key = _named_key(world, client, person)
    body = _connect(client, key)
    tools = facade.Facade(body)
    acted: list[Any] = []

    def mind() -> None:
        # What an MCP client's model does: wait for a turn, then act with an offered action.
        while not acted and body.ended is None:
            waited = tools.call("wait_for_turn", {"wait_seconds": 2})
            turn = waited.structured["turn"]
            if turn is not None:
                first = turn["options"][0]["action"]
                acted.append((first, tools.call("act", {"turn": turn["turn"], "action": first})))

    thread = threading.Thread(target=mind, daemon=True)
    thread.start()
    try:
        snapshot = _until_decided(world, client, services, snapshot)
        thread.join(5)
    finally:
        body.close(wait_seconds=5)
    [(action, result)] = acted
    assert not result.is_error, result.text
    assert result.structured["received"] is True
    [receipt] = _decisions(services, world, snapshot)
    assert (receipt["status"], receipt["reason"]) == ("accepted", "validated_choice")
    assert receipt["subject_id"] == person and receipt["proposal"]["label"] == action


def test_an_agents_own_body_comes_in_takes_its_turns_and_goes_home(door, crossings):
    world, client, database, services = door
    # A society of things needs somewhere to go (a well) and a gate its visitors come through.
    _place(client, world, "well", "well", 2, -4_000, 2_000)
    _place(client, world, "gate", "gate", 1, 0, 6_000)
    society = _make_society(client, world)
    grant_id, key = _key(world, client, gate="gate")
    body = _connect(client, key)
    seen: list[Any] = []

    def mind() -> None:
        # A scripted mind: for whatever turn comes, the first action that says nothing and does
        # not take the body out of the world. Which kinds speak is the person role's own word,
        # for a door that does not yet name the actions carrying a line on the frame.
        for turn in body.turns():
            seen.append(turn)
            quiet = [
                o
                for o in turn.options
                if not o.says_line and o.kind != "leave" and o.kind not in LINE_KINDS
            ]
            turn.act(quiet[0].action)

    thread = threading.Thread(target=mind, daemon=True)
    thread.start()
    host = services.decision_host()

    def minute(society: dict[str, Any]) -> dict[str, Any]:
        assert host.before_minute(_claim(world, society), time.monotonic() + LEASE_SECONDS)
        return _minute(client, world, society)

    def answered(society: dict[str, Any]) -> dict[str, Any]:
        for _ in range(10):
            if any(h.what == "answer_taken" for h in body.recent()):
                break
            society = minute(society)
        assert until(lambda: any(h.what == "answer_taken" for h in body.recent()))
        return society

    try:
        entered = facade.Facade(body).call("enter_world", {})
        assert not entered.is_error, entered.text
        society = _minute(client, world, society)
        [visitor] = [p for p in society["state"]["inhabitants"] if p["came_by"] == "crossed"]
        assert until(lambda: any(h.what == "arrived" for h in body.recent()))
        [arrived] = [h for h in body.recent() if h.what == "arrived"]
        assert arrived.thing == visitor["id"]
        # The agent takes its own body's turns, as one of the world's models would.
        society = answered(society)
        [taken, *_] = [h for h in body.recent() if h.what == "answer_taken"]
        assert taken.thing == visitor["id"] and seen[0].thing == visitor["id"]
        # Its program stops and starts again with the same key, as a toolkit's run does: the body
        # stays, its turns come to the new program, which knows it as its own.
        body.close(wait_seconds=5)
        thread.join(5)
        body = _connect(client, key)
        seen.clear()
        thread = threading.Thread(target=mind, daemon=True)
        thread.start()
        society = answered(society)
        assert seen[0].thing == visitor["id"]
        again = facade.Facade(body).call("enter_world", {})
        assert again.is_error and "already in the world" in again.text
        [receipt, *_] = _decisions(services, world, society)
        assert (receipt["subject_id"], receipt["status"]) == (visitor["id"], "accepted")
        assert (receipt["provider"]["bridge"], receipt["provider"]["grant_id"]) == (
            "agents",
            grant_id,
        )
        # It wears the first look the agents' mapping offers: the thing library's mannequin.
        mannequin = shipped_looks()[("kaykit-mannequin", 1)]
        looks = client.get(
            f"/world/versions/{world['binding'].version_id}/thing-looks",
            headers=OWNER,
            params={"world_id": world["binding"].world_id},
        ).json()["looks"]
        [worn] = [look for look in looks if look["thing_id"] == visitor["id"]]
        assert (worn["chosen_by"], worn["look"]) == (
            "crossing",
            {"look": mannequin.look, "version": mannequin.version, "sha256": mannequin.sha256},
        )
        # Who decides for it, as its card reads it: an outside agent, by what the agent declared.
        scope, _, society_route = routes(world)
        models = client.get(society_route + "/models", headers=OWNER, params=scope).json()
        assert models["outside"] == [
            {
                "subject_id": visitor["id"],
                "came": "crossed",
                "grant_id": grant_id,
                "bridge": "agents",
                "bridge_label": agents_bridge()["label"],
                "run_by": "owner",
                "ai": True,
                "connected": True,
                "declared": DECLARED,
            }
        ]
        # Its owner sends it home: the agent reads why and acknowledges the departure once.
        sent = client.post(
            f"/door/grants/{grant_id}/send-away", headers=OWNER, json={"thing_id": visitor["id"]}
        )
        assert sent.status_code == 202, sent.text
        society = minute(society)
        assert until(lambda: any(h.what == "left" for h in body.recent()))
        [left] = [h for h in body.recent() if h.what == "left"]
        assert left.thing == visitor["id"]
        assert "the world's owner sent your body home" in left.words

        def acknowledged() -> list[Any]:
            with database.session(world["workspace"]) as connection:
                return connection.execute(
                    "select thing_id from door_delivery where workspace_id = %s and grant_id = %s",
                    (world["workspace"], uuid.UUID(grant_id)),
                ).fetchall()

        assert until(lambda: len(acknowledged()) == 1)
        assert [str(row["thing_id"]) for row in acknowledged()] == [visitor["id"]]
    finally:
        body.close(wait_seconds=5)
        thread.join(5)
    # The world replays with the agent gone.
    assert _replayed(client, world)
