"""The door end to end: a bridge decides for a saved world's person through its channel.

The application connects as a provisioned runtime role and is built with the door and no model
client. A fixture bridge, running beside the host as an adapter would, reads its grant's channel by
long-poll over the real routes and answers each ask with the first label offered. The decision host
the application composes asks the person through the door, the receipt records the bridge's answer
in the external record, the minute applies it, and replay regenerates the history with the bridge
stopped. What is shown:

*   the grant route binds a named person through the choice record in the version it names, a
    grant naming somebody the version's society does not have is refused with nothing issued, and
    the composed decision host is given the door's asker;
*   the person's turn is decided by the bridge: the receipt's record names the bridge, its adapter
    version, the grant and the digest of the answer the bridge sent, and costs nothing;
*   replay needs no bridge;
*   revoking the grant hands the person back to the routine, and a quiet bridge's person is not
    asked: its turn is recorded as ``decider_disconnected``;
*   the world's models read gives the person's latest decision under the grant (``latest``): the
    bridge's answer, a turn a connected program let pass (``no_answer_in_time``, the routine
    deciding) until a later answer replaces it, or none yet under a new grant.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
import uuid
from typing import Any

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.canonical import sha256_of_canonical
from exulanica.db.roles import provision_runtime_role
from exulanica.door.runtime import DoorRuntime
from exulanica.models.manifest import AnsweringMechanism
from exulanica.world.society_controls import LEASE_SECONDS
from exulanica.world.society_decision_contract import person_role
from fastapi.testclient import TestClient

import door_support
import test_society_authored_world_postgres as helpers
import test_society_stay_requests_api as stays
from conftest import scratch_role_database
from test_society_person_decisions_postgres import _claim, _decisions
from test_society_saved_world_api import OWNER, TOKEN, routes
from tests_support_api import EVERY_PERMISSION

saved_world = helpers.saved_world
pytestmark = pytest.mark.postgres
ROLE = "exulanica_door_outside_suite"


@pytest.fixture
def door(saved_world, spine_schema, monkeypatch):
    """The application over the saved world as the runtime role, with the door, no model client,
    and the world's workspace among those the host asks for."""
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
        # The test bridge a server declared for this workspace alone, so its owner may be given
        # its credential directly; a poll held one second.
        door=DoorRuntime(
            database=database,
            bridges=door_support.bridges(
                listed=False, workspaces=[str(world["workspace"])], hold_seconds=1
            ),
        ),
    )
    with TestClient(create_app(services, verify=False), raise_server_exceptions=False) as client:
        yield world, client, services


class _Bridge:
    """A fixture bridge: it polls its channel and answers every ask with the first label offered,
    recording the bodies it sent, until it is stopped. One that ``answers`` nothing keeps polling,
    so it stays connected, and lets every ask's deadline pass."""

    def __init__(self, client, channel: dict[str, str], cursor: str, answers: bool = True) -> None:
        self.client = client
        self.channel = channel
        self.cursor = cursor
        self.answers = answers
        self.sent: list[dict[str, Any]] = []
        self.asked: list[dict[str, Any]] = []
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> _Bridge:
        self.thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.stopped.set()
        self.thread.join(timeout=10)

    def _run(self) -> None:
        while not self.stopped.is_set():
            read = self.client.get(
                "/door/channel/frames", headers=self.channel, params={"after": self.cursor}
            )
            if read.status_code != 200:
                time.sleep(0.2)
                continue
            self.cursor = read.json()["cursor"]
            for frame in read.json()["frames"]:
                if frame["kind"] != "asked":
                    continue
                self.asked.append(frame)
                if not self.answers:
                    continue
                body = {
                    "request_id": frame["request_id"],
                    "request_sha256": frame["request_sha256"],
                    "label": frame["context"]["options"][0]["label"],
                }
                answered = self.client.post(
                    "/door/channel/answers", headers=self.channel, json=body
                )
                if answered.status_code == 202:
                    self.sent.append(body)


def _issue(world, client, person: str, key: str):
    return client.post(
        "/door/grants",
        headers=OWNER,
        params={"world_id": world["binding"].world_id},
        json={
            "idempotency_key": key,
            "bridge": "test-bridge",
            "things": [person],
            "version_id": str(world["binding"].version_id),
        },
    )


def _grant(world, client, person: str, key: str = "outside-person-grant") -> str:
    issued = _issue(world, client, person, key)
    assert issued.status_code == 201, issued.text
    return issued.json()["grant"]["grant_id"]


def _channel(client, grant_id: str) -> tuple[dict[str, str], str]:
    made = client.post(f"/door/grants/{grant_id}/channel-credentials", headers=OWNER)
    assert made.status_code == 201, made.text
    channel = {"Authorization": f"Bearer {made.json()['credential']}"}
    hello = client.post(
        "/door/channel/hello",
        headers=channel,
        json={
            "adapter_version": door_support.ADAPTER_VERSION,
            "mapping": door_support.mapping(),
            "reads": door_support.READS,
        },
    )
    assert hello.status_code == 200, hello.text
    return channel, hello.json()["cursor"]


def _until_decided(world, client, services, host, snapshot, after: int = 0) -> dict[str, Any]:
    """Minutes asked and stepped until a decision later than decision ``after`` is recorded."""
    for _ in range(30):
        assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
        if any(d["decision_seq"] > after for d in _decisions(services, world, snapshot)):
            return snapshot
        snapshot = stays._step(world, client, snapshot)
    raise AssertionError("the person reached no choice point in thirty minutes")


def _choice_of(world, client, person: str) -> dict[str, Any]:
    scope, _, society = routes(world)
    read = client.get(society + "/models", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    [choice] = [entry for entry in read.json()["choices"] if entry["subject_id"] == person]
    return choice


def _latest_of(world, client, person: str) -> dict[str, Any] | None:
    """What the world's models read says of the person's latest decision from outside."""
    scope, _, society = routes(world)
    read = client.get(society + "/models", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    [entry] = [entry for entry in read.json()["outside"] if entry["subject_id"] == person]
    return entry["latest"]


def _latest(receipt: dict[str, Any], consumed_tick: int | None = None) -> dict[str, Any]:
    """An outside entry's ``latest`` for ``receipt``, consumed at ``consumed_tick`` or not yet."""
    return {
        "decision_seq": receipt["decision_seq"],
        "base_tick": receipt["base_tick"],
        "consumed_tick": consumed_tick,
        "status": receipt["status"],
        "reason": receipt["reason"],
    }


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_bridge_decides_for_a_person_through_the_door_and_replay_needs_no_bridge(door):
    world, client, services = door
    snapshot = stays._inhabited(world, client)
    person = snapshot["state"]["inhabitants"][0]["id"]
    # A grant naming somebody this version's society does not have is refused as the choices route
    # refuses the choice, and nothing is issued.
    stranger = _issue(world, client, str(uuid.uuid4()), "outside-stranger-grant")
    assert (stranger.status_code, stranger.json()["code"]) == (422, "person_not_in_this_world")
    listed = client.get(
        "/door/grants", headers=OWNER, params={"world_id": world["binding"].world_id}
    )
    assert listed.json()["grants"] == []
    grant_id = _grant(world, client, person)
    assert _choice_of(world, client, person)["decider"] == {
        "kind": "external",
        "bridge": "test-bridge",
        "grant_id": grant_id,
    }
    host = services.decision_host()
    assert host is not None and host.external is not None
    channel, cursor = _channel(client, grant_id)
    with _Bridge(client, channel, cursor) as bridge:
        snapshot = _until_decided(world, client, services, host, snapshot)
    [receipt] = _decisions(services, world, snapshot)
    assert (receipt["status"], receipt["reason"]) == ("accepted", "validated_choice")
    assert receipt["subject_id"] == person
    [sent] = bridge.sent
    assert receipt["proposal"]["label"] == sent["label"]
    # The bridge was sent what a model is sent: the role's own rendering of the request with the
    # forced function, and the minute it was asked at.
    [asked] = bridge.asked
    role = person_role()
    assert asked["messages"] == role.adapter.messages(
        role, asked["context"], AnsweringMechanism.TOOL_CALL
    )
    assert asked["messages"][-1]["content"].endswith("Choose one by calling act.")
    assert asked["act"] == role.choice(asked["context"]).tool()
    # The function and its argument an outside agent calls by name: act, and its action.
    assert asked["act"]["function"]["name"] == "act"
    assert asked["act"]["function"]["parameters"]["properties"]["action"]["enum"] == [
        option["label"] for option in asked["context"]["options"]
    ]
    assert type(asked["minute"]) is int
    record = receipt["provider"]
    assert record == {
        "kind": "external",
        "bridge": "test-bridge",
        "adapter_version": door_support.ADAPTER_VERSION,
        "grant_id": grant_id,
        "grant_seq": 1,
        "mapping_sha256": door_support.mapping_sha256(),
        "answer_sha256": sha256_of_canonical(sent).hex(),
        "latency_ms": record["latency_ms"],
        "source_ref_sha256": None,
    }
    assert "cost_usd" not in record
    # The world's models read gives the person's latest decision from outside: the bridge's.
    assert _latest_of(world, client, person) == _latest(receipt)
    # The minute applies the bridge's choice, and replay regenerates it with the bridge stopped.
    stepped = stays._step(world, client, snapshot)
    assert _latest_of(world, client, person) == _latest(receipt, stepped["current_tick"])
    scope, _, society = routes(world)
    replayed = client.get(society + "/replay", headers=OWNER, params=scope)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"] is True


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_quiet_bridge_is_not_asked_and_revoking_hands_the_person_back(door, monkeypatch):
    world, client, services = door
    snapshot = stays._inhabited(world, client)
    person = snapshot["state"]["inhabitants"][0]["id"]
    grant_id = _grant(world, client, person, key="outside-person-quiet")
    _channel(client, grant_id)  # said hello once, then went quiet
    monkeypatch.setattr("exulanica.door.asker.presence_window", lambda _bridge: dt.timedelta(0))
    monkeypatch.setattr("exulanica.door.outside.presence_window", lambda _bridge: dt.timedelta(0))
    host = services.decision_host()
    snapshot = _until_decided(world, client, services, host, snapshot)
    [receipt] = _decisions(services, world, snapshot)
    assert (receipt["status"], receipt["reason"]) == ("unavailable", "decider_disconnected")
    assert receipt["provider"] is None
    # The world's models read names who decides for the person from outside, with what the grant
    # view says of the program; while it does, the owner's own choice for them is refused.
    scope, _, society = routes(world)
    read = client.get(society + "/models", headers=OWNER, params=scope)
    assert read.json()["outside"] == [
        {
            "subject_id": person,
            "came": "run",
            "grant_id": grant_id,
            "bridge": "test-bridge",
            "bridge_label": "A test bridge",
            "run_by": "server",
            "ai": False,
            "connected": False,
            "declared": None,
            "latest": _latest(receipt),
        }
    ]
    chosen = {"idempotency_key": str(uuid.uuid4()), "people": [person], "model": None}
    refused = client.post(society + "/models", headers=OWNER, params=scope, json=chosen)
    assert (refused.status_code, refused.json()["code"]) == (409, "decided_from_outside")
    revoked = client.post(f"/door/grants/{grant_id}/revoke", headers=OWNER)
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["grant"]["ended"] == "revoked"
    assert _choice_of(world, client, person)["decider"] == {"kind": "routine"}
    assert client.get(society + "/models", headers=OWNER, params=scope).json()["outside"] == []
    again = client.post(society + "/models", headers=OWNER, params=scope, json=chosen)
    assert again.status_code in (200, 201), again.text
    # A new grant for the person has decided nothing yet: the ended grant's receipt is not its own.
    _grant(world, client, person, key="outside-person-again")
    assert _latest_of(world, client, person) is None


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_program_that_never_answers_reads_as_missed_until_an_answer_replaces_it(door):
    world, client, services = door
    snapshot = stays._inhabited(world, client)
    person = snapshot["state"]["inhabitants"][0]["id"]
    grant_id = _grant(world, client, person, key="outside-person-silent")
    host = services.decision_host()
    channel, cursor = _channel(client, grant_id)
    # Connected and asked, the program lets the deadline pass: the routine decides that turn.
    with _Bridge(client, channel, cursor, answers=False) as silent:
        snapshot = _until_decided(world, client, services, host, snapshot)
    [missed] = _decisions(services, world, snapshot)
    assert silent.asked and silent.sent == []
    assert (missed["status"], missed["reason"]) == ("unavailable", "no_answer_in_time")
    assert _latest_of(world, client, person) == _latest(missed)
    # The program answers a later turn, and its answer is the latest.
    snapshot = stays._step(world, client, snapshot)
    with _Bridge(client, channel, silent.cursor) as answering:
        snapshot = _until_decided(
            world, client, services, host, snapshot, after=missed["decision_seq"]
        )
    answered = _decisions(services, world, snapshot)[-1]
    assert answering.sent and answered["decision_seq"] > missed["decision_seq"]
    assert (answered["status"], answered["reason"]) == ("accepted", "validated_choice")
    assert _latest_of(world, client, person) == _latest(answered)
