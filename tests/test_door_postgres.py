"""The door against the deployed database, through the application as the runtime role runs it.

Every request goes through the real routes of an application connected as a provisioned runtime
role over a saved world, so migration 0149's triggers, row-level security and grants are what
answer. What is shown:

*   an owner issues a grant, a repeated issue answers with it, and a reused key is refused; who runs
    a bridge decides how its grants open (invites for a server, a direct credential for a program
    its owner runs or a server declared for this workspace alone); a grant keeps at most eight
    invites waiting, and its owner can end every credential without ending the grant;
*   an invite opens its grant once, for its own bridge, and every other redemption gets one
    refusal; a requester past ten failures in a minute is refused unread, and only that requester;
*   a bridge says hello only under a standing grant, with an adapter version and a mapping the
    deployment pins, a fractional number refused by name, its program's declaration allowed words
    only; at most six hellos a minute; it polls only after hello; once it has read that its grant
    ended, its polls and hellos are refused; a revoked credential, or a bridge the deployment no
    longer declares, opens nothing, and the asker leaves that bridge's things to the routine;
*   the decision host's asker writes an ask over a really reserved request, the bridge reads the
    request in an ``asked`` frame and answers one offered label, and the asker returns the
    receipt's result naming the adapter and declaration that answered; an answer under another
    mapping than the request's is not accepted; an answer not offered, a second answer and an
    answer after the turn is decided are refused; no answer by the deadline, a revoked grant and a
    quiet bridge each say so; an answer stored before a revocation committed is not accepted
    after it, and the database refuses one written after it;
*   the tables keep their own rules whoever writes: append-only, presence forward only, a secret
    gains only the times it was used and revoked, deletes only past retention and only through
    ``door_prune``, no workspace sees another's rows; bodies past their bounds are refused before
    they are read.
"""

from __future__ import annotations

import itertools
import json
import threading
import time
import uuid
from typing import Any

import psycopg
import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.canonical import sha256_of_canonical
from exulanica.db.roles import provision_runtime_role
from exulanica.door.asker import DoorAsker
from exulanica.door.bridges import load_bridge_directory
from exulanica.door.credentials import credential_sha256
from exulanica.door.grants import SECRETS_WAITING_MAXIMUM, GrantRepository, Scope
from exulanica.door.notices import Notices
from exulanica.door.protocol import DEADLINE_MS_DEFAULT, Cursor
from exulanica.door.runtime import DoorRuntime
from exulanica.world.role_decisions import role_request, seal
from exulanica.world.society_decision_contract import person_role
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

import door_support
import test_society_authored_world_postgres as helpers
import test_society_stay_requests_api as stays
from conftest import scratch_role_database
from test_society_saved_world_api import OWNER, TOKEN
from tests_support_api import EVERY_PERMISSION

saved_world = helpers.saved_world
pytestmark = pytest.mark.postgres
ROLE = "exulanica_door_suite"
BRIDGE = {"Authorization": f"Bearer {door_support.BRIDGE_CREDENTIAL}"}
OTHER = {"Authorization": f"Bearer {door_support.OTHER_CREDENTIAL}"}
#: Who typed a code at a bridge, as digests the bridge derives.
SOMEONE = "a" * 64
SOMEONE_ELSE = "b" * 64


def _bridges(workspace: uuid.UUID, **figures: int):
    """The test bridge a server declared for this workspace alone (a poll held one second), another
    server listed for everyone, and a program each owner runs, offered here."""
    return door_support.bridges(
        listed=False,
        workspaces=[str(workspace)],
        owner_workspaces=[str(workspace)],
        **{"hold_seconds": 1, **figures},
    )


@pytest.fixture
def door(saved_world, spine_schema, monkeypatch):
    """The application over the saved world as the runtime role, with the test bridges admitted."""
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

    def application(bridges) -> tuple[TestClient, DoorRuntime]:
        runtime = DoorRuntime(database=database, bridges=bridges)
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
            door=runtime,
        )
        return TestClient(
            create_app(services, verify=False), raise_server_exceptions=False
        ), runtime

    client, runtime = application(_bridges(world["workspace"]))
    with client:
        yield {
            "world": world,
            "client": client,
            "runtime": runtime,
            "database": database,
            "application": application,
        }


def _world_id(door) -> str:
    return door["world"]["binding"].world_id


def _issue(door, key: str = "grant-key-0001", **scope: Any) -> Any:
    body = {"idempotency_key": key, "bridge": "test-bridge", "visitors_maximum": 1}
    body["kinds"] = ["player"]
    body.update(scope)
    return door["client"].post(
        "/door/grants", headers=OWNER, params={"world_id": _world_id(door)}, json=body
    )


def _grant_for(door, *subjects: str) -> uuid.UUID:
    """A grant naming some of the world's people, bound in its version through the choice record,
    issued as the grant route issues it."""
    world = door["world"]
    with door["database"].session(world["workspace"]) as connection:
        grant, _ = GrantRepository(connection, world["workspace"], world["session"].actor).issue(
            world_id=_world_id(door),
            bridge=door["runtime"].bridges.get("test-bridge"),
            scope=Scope(things=subjects, version_id=str(world["binding"].version_id)),
            minutes=60,
            idempotency_key=f"things-{'-'.join(sorted(subjects))}"[:128],
        )
    return grant.grant_id


def _credential(door, grant_id) -> dict[str, str]:
    made = door["client"].post(f"/door/grants/{grant_id}/channel-credentials", headers=OWNER)
    assert made.status_code == 201, made.text
    return {"Authorization": f"Bearer {made.json()['credential']}"}


def _hello(door, channel, **change: Any) -> Any:
    body = {
        "adapter_version": door_support.ADAPTER_VERSION,
        "mapping": door_support.mapping(),
        "reads": door_support.READS,
    }
    body.update(change)
    return door["client"].post("/door/channel/hello", headers=channel, json=body)


def _frames(door, channel, cursor: str | None = None) -> Any:
    params = {} if cursor is None else {"after": cursor}
    return door["client"].get("/door/channel/frames", headers=channel, params=params)


def _mapping(version: int) -> dict[str, Any]:
    return door_support.mapping(version)


def _redeem(door, headers, code: str, requester: str = SOMEONE) -> Any:
    return door["client"].post(
        "/door/invites/redeem", headers=headers, json={"code": code, "requester": requester}
    )


# -- grants and invites ----------------------------------------------------------------------


def test_an_owner_issues_a_grant_and_a_repeat_answers_with_the_same_one(door):
    issued = _issue(door)
    assert issued.status_code == 201, issued.text
    grant = issued.json()["grant"]
    assert (grant["state"], grant["grant_seq"], grant["bridge"]) == ("active", 1, "test-bridge")
    assert grant["scope"]["visitors_maximum"] == 1 and grant["connected"] is False
    again = _issue(door)
    assert again.status_code == 200 and again.json()["grant"]["grant_id"] == grant["grant_id"]
    reused = _issue(door, visitors_maximum=2)
    assert (reused.status_code, reused.json()["code"]) == (409, "idempotency_key_reused")
    listed = door["client"].get("/door/grants", headers=OWNER, params={"world_id": _world_id(door)})
    assert [g["grant_id"] for g in listed.json()["grants"]] == [grant["grant_id"]]


def test_a_grant_names_a_bridge_offered_here_a_registered_world_and_no_unbound_thing(door):
    unknown = _issue(door, bridge="no-such-bridge")
    assert (unknown.status_code, unknown.json()["code"]) == (422, "bridge_not_offered")
    elsewhere = door["client"].post(
        "/door/grants",
        headers=OWNER,
        params={"world_id": "world:authored:nobody-registered-this"},
        json={
            "idempotency_key": "grant-key-0002",
            "bridge": "test-bridge",
            "kinds": ["player"],
            "visitors_maximum": 1,
        },
    )
    assert (elsewhere.status_code, elsewhere.json()["code"]) == (404, "unknown_world")
    # A named thing is bound in the version the grant names, so a grant naming one names it, and
    # binds only one of that version's people (the choice record's own refusal).
    unbound = _issue(door, things=[str(uuid.uuid4())])
    assert (unbound.status_code, unbound.json()["code"]) == (422, "invalid_scope")
    stranger = _issue(
        door,
        key="grant-key-0003",
        things=[str(uuid.uuid4())],
        version_id=str(door["world"]["binding"].version_id),
    )
    # Nobody lives in the version yet: the choice record finds no society to bind in, and the whole
    # grant is refused with it, so no grant exists that names a thing it cannot decide for.
    assert (stranger.status_code, stranger.json()["code"]) == (404, "unknown_reference")
    listed = door["client"].get("/door/grants", headers=OWNER, params={"world_id": _world_id(door)})
    assert all(grant["scope"]["things"] == [] for grant in listed.json()["grants"])
    nothing = _issue(door, visitors_maximum=0, kinds=[])
    assert (nothing.status_code, nothing.json()["code"]) == (422, "invalid_scope")


def test_an_invite_opens_its_grant_once_for_its_own_bridge_and_nothing_else(door):
    grant_id = _issue(door).json()["grant"]["grant_id"]
    invited = door["client"].post(f"/door/grants/{grant_id}/invites", headers=OWNER)
    assert invited.status_code == 201, invited.text
    code = invited.json()["code"]
    assert len(code) == 19 and code.count("-") == 3

    refused = {
        "code": "invite_not_redeemable",
        "detail": "this invite opens nothing for this bridge",
    }
    other = _redeem(door, OTHER, code)
    assert (other.status_code, other.json()) == (404, refused)
    redeemed = _redeem(door, BRIDGE, code.lower())
    assert redeemed.status_code == 201, redeemed.text
    assert redeemed.json()["grant"]["grant_id"] == grant_id
    channel = {"Authorization": f"Bearer {redeemed.json()['credential']}"}
    assert _hello(door, channel).status_code == 200
    for typed in (code, "NOT-A-CODE", "0000-0000-0000-0000"):
        again = _redeem(door, BRIDGE, typed)
        assert (again.status_code, again.json()) == (404, refused), typed

    # An account's token is no bridge credential, and a channel credential is no bridge's either.
    for headers in (OWNER, channel):
        stranger = _redeem(door, headers, code)
        assert (stranger.status_code, stranger.json()["code"]) == (401, "unauthenticated")


def test_a_revoked_grant_s_unused_invites_open_nothing(door):
    grant_id = _issue(door).json()["grant"]["grant_id"]
    code = door["client"].post(f"/door/grants/{grant_id}/invites", headers=OWNER).json()["code"]
    revoked = door["client"].post(f"/door/grants/{grant_id}/revoke", headers=OWNER)
    assert revoked.json()["grant"]["state"] == "revoked"
    assert revoked.json()["grant"]["ended"] == "revoked"
    redeemed = _redeem(door, BRIDGE, code)
    assert (redeemed.status_code, redeemed.json()["code"]) == (404, "invite_not_redeemable")
    again = door["client"].post(f"/door/grants/{grant_id}/invites", headers=OWNER)
    assert (again.status_code, again.json()["code"]) == (409, "grant_ended")
    assert door["client"].post(f"/door/grants/{grant_id}/revoke", headers=OWNER).status_code == 200


def test_a_requester_past_ten_failures_in_a_minute_is_refused_unread_and_nobody_else(door):
    for attempt in range(10):
        failed = _redeem(door, BRIDGE, f"0000-0000-0000-{attempt:04d}")
        assert failed.status_code == 404
    grant_id = _issue(door).json()["grant"]["grant_id"]
    code = door["client"].post(f"/door/grants/{grant_id}/invites", headers=OWNER).json()["code"]
    limited = _redeem(door, BRIDGE, code)
    assert (limited.status_code, limited.json()["code"]) == (429, "too_many_redemptions")
    assert limited.json()["retry_after_s"] == 60
    # Refused unread and not recorded, so the lockout ends a minute after the last real failure.
    with door["world"]["connection"].cursor() as cursor:
        counted = cursor.execute(
            "select bridge, requester_sha256, count(*) as n from door_redemption_refusal "
            "group by bridge, requester_sha256 order by bridge, requester_sha256"
        ).fetchall()
    assert counted == [{"bridge": "test-bridge", "requester_sha256": SOMEONE, "n": 10}]
    # Another person typing at the same bridge is not held up by the first one's guesses.
    redeemed = _redeem(door, BRIDGE, code, requester=SOMEONE_ELSE)
    assert redeemed.status_code == 201, redeemed.text


# -- hello and frames -------------------------------------------------------------------------


def test_hello_takes_only_what_the_deployment_pins_and_a_poll_only_after_it(door):
    grant_id = _issue(door).json()["grant"]["grant_id"]
    channel = _credential(door, grant_id)
    before = _frames(door, channel)
    assert (before.status_code, before.json()["code"]) == (409, "hello_first")

    version = _hello(door, channel, adapter_version="9.9.9")
    assert (version.status_code, version.json()["code"]) == (422, "adapter_version_not_admitted")
    pinned = _hello(door, channel, mapping=door_support.mapping(3))
    assert (pinned.status_code, pinned.json()["code"]) == (422, "mapping_not_admitted")
    incomplete = _hello(door, channel, reads=[*door_support.READS, "hunger"])
    assert (incomplete.status_code, incomplete.json()["code"]) == (422, "mapping_refused")
    assert "hunger" in incomplete.json()["detail"]
    fractional = _hello(door, channel, mapping={**door_support.mapping(), "version": 1.5})
    assert (fractional.status_code, fractional.json()["code"]) == (422, "mapping_refused")
    linked = _hello(door, channel, declared={"name": "Scout", "maker": "see acme.ai"})
    assert (linked.status_code, linked.json()["code"]) == (422, "declared_refused")

    hello = _hello(door, channel)
    assert hello.status_code == 200, hello.text
    assert hello.json()["grant"]["grant_id"] == grant_id
    first = _frames(door, channel, hello.json()["cursor"])
    assert first.status_code == 200, first.text
    assert [frame["kind"] for frame in first.json()["frames"]] == ["grant"]
    assert first.json()["frames"][0]["scope"]["visitors_maximum"] == 1
    started = time.monotonic()
    held = _frames(door, channel, first.json()["cursor"])
    assert held.status_code == 200 and held.json()["frames"] == []
    assert held.json()["cursor"] == first.json()["cursor"]
    assert time.monotonic() - started >= 0.9  # it waited for the hold, then answered empty
    stored = (
        door["world"]["connection"]
        .execute(
            "select mapping_sha256 from door_mapping where workspace_id = %s",
            (door["world"]["workspace"],),
        )
        .fetchall()
    )
    assert stored == [{"mapping_sha256": door_support.mapping_sha256()}]


def test_a_channel_credential_opens_its_own_grant_and_no_other_route(door):
    grant_id = _issue(door).json()["grant"]["grant_id"]
    channel = _credential(door, grant_id)
    assert (
        door["client"]
        .get("/door/grants", headers=channel, params={"world_id": _world_id(door)})
        .status_code
        == 401
    )
    unknown = {"Authorization": "Bearer " + "x" * 43}
    assert _frames(door, unknown).json()["code"] == "unauthenticated"
    assert _frames(door, OWNER).json()["code"] == "unauthenticated"


# -- the asker --------------------------------------------------------------------------------


def _person_requests(door, count: int) -> list[tuple[dict[str, Any], str]]:
    """Requests really reserved for people of the world's society, one each, as the host reserves
    them, asked under an external decider: built by the role's own request builder."""
    world = door["world"]
    stays._inhabited(world, door["client"])
    connection = world["connection"]
    society = connection.execute(
        "select society_id, seed, state from world_society where workspace_id = %s and "
        "world_id = %s",
        (world["workspace"], world["binding"].world_id),
    ).fetchone()
    society_id, seed, state = society["society_id"], society["seed"], society["state"]
    source = connection.execute(
        "select document from world_society_input where workspace_id = %s and society_id = %s "
        "order by input_seq desc limit 1",
        (world["workspace"], society_id),
    ).fetchone()["document"]
    role = person_role()
    contract = role.contract()
    model_shaped = {
        "provider": "test",
        "model_id": "test",
        "mechanism": "tool_call",
        "choice_seq": 1,
        "manifest_sha256": "0" * 64,
        "prompt_version": role.prompt_version,
        "contract": contract.binding(),
        "deadline_ms": DEADLINE_MS_DEFAULT,
    }
    found = []
    for person in sorted(p["id"] for p in state["inhabitants"]):
        if not role.adapter.due(state, person):
            continue
        request, _status = role_request(
            role,
            state,
            source,
            person,
            request_id=uuid.uuid4(),
            contract=contract,
            seed=seed,
            provider_config=model_shaped,
        )
        if request is not None:
            found.append((request, person))
        if len(found) == count:
            return found
    pytest.fail(f"fewer than {count} people in the fixture society are at a choice point")


def _person_request(door) -> tuple[dict[str, Any], str]:
    [found] = _person_requests(door, 1)
    return found


def _store_external(door, request: dict[str, Any], grant_id: uuid.UUID) -> dict[str, Any]:
    world = door["world"]
    asker = door["runtime"].asker()
    config, refusal = asker.configuration(
        world["workspace"],
        _world_id(door),
        request["subject_id"],
        {"kind": "external", "bridge": "test-bridge", "grant_id": str(grant_id)},
    )
    assert refusal is None, refusal
    external = {key: value for key, value in request.items() if key != "document_sha256"}
    external["provider_config"] = {**config, "contract": request["provider_config"]["contract"]}
    external = seal(external)
    society_id = (
        world["connection"]
        .execute(
            "select society_id from world_society where workspace_id = %s and world_id = %s",
            (world["workspace"], _world_id(door)),
        )
        .fetchone()["society_id"]
    )
    world["connection"].execute(
        "insert into world_society_decision_request(workspace_id, society_id, request_id, "
        "subject_id, base_tick, input_seq, document, document_sha256) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            world["workspace"],
            society_id,
            external["request_id"],
            external["subject_id"],
            external["base_tick"],
            external["input_seq"],
            Jsonb(external),
            external["document_sha256"],
        ),
    )
    world["connection"].commit()
    return external


def _asked(door, channel, cursor: str) -> tuple[dict[str, Any], str]:
    for _ in range(20):
        read = _frames(door, channel, cursor).json()
        cursor = read["cursor"]
        asked = [frame for frame in read["frames"] if frame["kind"] == "asked"]
        if asked:
            return asked[0], cursor
    pytest.fail("no asked frame reached the bridge")


def _ask_in_background(door, request, *, seconds: float = 8.0) -> dict[str, Any]:
    result: dict[str, Any] = {}
    asker = door["runtime"].asker()
    world = door["world"]

    def run() -> None:
        result.update(
            asker.answer(world["workspace"], _world_id(door), request, time.monotonic() + seconds)
        )

    thread = threading.Thread(target=run)
    thread.start()
    result["_thread"] = thread
    return result


def test_the_asker_asks_the_bridge_and_returns_its_answer_as_the_receipt_records_it(door):
    request, person = _person_request(door)
    grant_id = _grant_for(door, person)
    channel = _credential(door, grant_id)
    cursor = _hello(door, channel).json()["cursor"]
    external = _store_external(door, request, grant_id)

    waiting = _ask_in_background(door, external)
    asked, cursor = _asked(door, channel, cursor)
    assert asked["request_id"] == external["request_id"]
    assert asked["request_sha256"] == external["document_sha256"]
    assert asked["context"] == external["context"]  # byte for byte what a model reads
    role = person_role()
    assert (asked["instruction"], asked["choice_description"]) == (
        role.instruction,
        role.choice_description,
    )
    assert asked["deadline_ms"] == DEADLINE_MS_DEFAULT
    label = asked["context"]["options"][0]["label"]

    not_offered = door["client"].post(
        "/door/channel/answers",
        headers=channel,
        json={
            "request_id": asked["request_id"],
            "request_sha256": asked["request_sha256"],
            "label": "fly to the moon",
        },
    )
    assert (not_offered.status_code, not_offered.json()["code"]) == (422, "answer_not_offered")
    body = {
        "request_id": asked["request_id"],
        "request_sha256": asked["request_sha256"],
        "label": label,
    }
    answered = door["client"].post("/door/channel/answers", headers=channel, json=body)
    assert answered.status_code == 202, answered.text
    twice = door["client"].post("/door/channel/answers", headers=channel, json=body)
    assert (twice.status_code, twice.json()["code"]) == (409, "answer_already_given")

    waiting["_thread"].join(timeout=10)
    result = {key: value for key, value in waiting.items() if key != "_thread"}
    assert result["status"] == "accepted" and result["reason"] == "validated_choice"
    assert result["proposal"]["label"] == label
    assert result["proposal"]["option"] == asked["context"]["options"][0]
    provider = result["provider"]
    assert provider == {
        "kind": "external",
        "bridge": "test-bridge",
        "adapter_version": door_support.ADAPTER_VERSION,
        "grant_id": str(grant_id),
        "grant_seq": 1,
        "mapping_sha256": door_support.mapping_sha256(),
        "answer_sha256": sha256_of_canonical(body).hex(),
        "latency_ms": provider["latency_ms"],
        "source_ref_sha256": None,
    }
    assert 0 <= provider["latency_ms"] < 10_000


def test_no_answer_by_the_deadline_and_a_revoked_grant_each_say_so(door):
    request, person = _person_request(door)
    grant_id = _grant_for(door, person)
    channel = _credential(door, grant_id)
    _hello(door, channel)
    external = _store_external(door, request, grant_id)
    world = door["world"]
    asker = door["runtime"].asker()
    silent = asker.answer(world["workspace"], _world_id(door), external, time.monotonic() + 0.5)
    assert silent == {
        "status": "unavailable",
        "reason": "no_answer_in_time",
        "proposal": None,
        "provider": None,
    }
    door["client"].post(f"/door/grants/{grant_id}/revoke", headers=OWNER)
    config, refusal = asker.configuration(
        world["workspace"],
        _world_id(door),
        person,
        {"kind": "external", "bridge": "test-bridge", "grant_id": str(grant_id)},
    )
    # A revocation is its own record, not a revision: the revision stays the one asked under.
    assert refusal == "grant_revoked" and config["grant_seq"] == 1
    late = door["client"].post(
        "/door/channel/answers",
        headers=channel,
        json={
            "request_id": external["request_id"],
            "request_sha256": external["document_sha256"],
            "label": external["context"]["options"][0]["label"],
        },
    )
    assert (late.status_code, late.json()["code"]) == (410, "grant_ended")
    # The database takes no answer under an ended grant either, whoever writes it: a well-formed
    # answer to the open ask, written straight into the inbox as the runtime role, is refused.
    with door["database"].session(world["workspace"]) as connection:
        ask = connection.execute(
            "select ask_seq from door_ask where grant_id = %s and request_id = %s",
            (grant_id, external["request_id"]),
        ).fetchone()
        document = {
            "request_id": external["request_id"],
            "request_sha256": external["document_sha256"],
            "label": external["context"]["options"][0]["label"],
        }
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="grant that stands"),
            connection.transaction(),
        ):
            connection.execute(
                "insert into door_answer (workspace_id, request_id, grant_id, ask_seq, "
                "adapter_version, mapping_sha256, document, answer_sha256) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    world["workspace"],
                    external["request_id"],
                    grant_id,
                    ask["ask_seq"],
                    door_support.ADAPTER_VERSION,
                    door_support.mapping_sha256(),
                    Jsonb(document),
                    sha256_of_canonical(document).hex(),
                ),
            )
    # The channel may still read that its grant ended, and is told once.
    read = _frames(door, channel).json()
    assert [frame["kind"] for frame in read["frames"]][-1] == "grant_ended"
    assert read["frames"][-1]["reason"] == "revoked"
    assert Cursor.decode(read["cursor"]).ended is True


def test_configuration_names_a_quiet_bridge_a_thing_the_grant_no_longer_names_and_its_end(
    door, monkeypatch
):
    _request, person = _person_request(door)
    grant_id = _grant_for(door, person)
    world = door["world"]
    asker = door["runtime"].asker()
    decider = {"kind": "external", "bridge": "test-bridge", "grant_id": str(grant_id)}
    config, refusal = asker.configuration(world["workspace"], _world_id(door), person, decider)
    assert refusal == "decider_disconnected"  # never said hello
    pinned = sorted([door_support.mapping_sha256(), door_support.mapping_sha256(_mapping(2))])
    assert config == {
        "kind": "external",
        "bridge": "test-bridge",
        "grant_id": str(grant_id),
        "grant_seq": 1,
        # Before any hello, the first digest the grant pins; after one, the mapping presented.
        "mapping_sha256": pinned[0],
        "deadline_ms": DEADLINE_MS_DEFAULT,
    }
    _hello(door, _credential(door, grant_id), mapping=_mapping(2))
    config, refusal = asker.configuration(world["workspace"], _world_id(door), person, decider)
    assert refusal is None and config["mapping_sha256"] == door_support.mapping_sha256(_mapping(2))
    stranger = str(uuid.uuid4())
    assert asker.configuration(world["workspace"], _world_id(door), stranger, decider)[1] == (
        "grant_revoked"
    )
    with pytest.raises(LookupError):
        asker.configuration(
            world["workspace"], _world_id(door), person, {**decider, "bridge": "other-bridge"}
        )
    # Once its end passes, a grant that was never revoked still binds the person, and is not asked.
    with door["runtime"].database.session(world["workspace"]) as connection:
        grant = GrantRepository(connection, world["workspace"], world["session"].actor).current(
            grant_id
        )
    assert grant is not None
    monkeypatch.setattr(GrantRepository, "now", lambda _self: grant.expires_at)
    assert asker.configuration(world["workspace"], _world_id(door), person, decider)[1] == (
        "grant_expired"
    )


def test_one_poll_stops_adding_asked_frames_past_its_byte_bound(door, monkeypatch):
    (first, one), (second, two) = _person_requests(door, 2)
    grant_id = _grant_for(door, one, two)
    channel = _credential(door, grant_id)
    cursor = _hello(door, channel).json()["cursor"]
    asked_first = _store_external(door, first, grant_id)
    asked_second = _store_external(door, second, grant_id)
    world = door["world"]
    asker = door["runtime"].asker()
    for external in (asked_first, asked_second):
        asker._write_ask(world["workspace"], grant_id, uuid.UUID(external["request_id"]))
    # A bound smaller than any frame: the first asked frame always goes, and the next waits.
    monkeypatch.setattr("exulanica.door.channel.ASKED_BYTES_MAXIMUM", 1)
    read = _frames(door, channel, cursor).json()
    assert [f["request_id"] for f in read["frames"] if f["kind"] == "asked"] == [
        asked_first["request_id"]
    ]
    again = _frames(door, channel, read["cursor"]).json()
    assert [f["request_id"] for f in again["frames"] if f["kind"] == "asked"] == [
        asked_second["request_id"]
    ]


def test_an_answer_after_the_turn_is_decided_is_too_late_and_outcomes_follow_in_order(door):
    request, person = _person_request(door)
    grant_id = _grant_for(door, person)
    channel = _credential(door, grant_id)
    cursor = _hello(door, channel).json()["cursor"]
    external = _store_external(door, request, grant_id)
    waiting = _ask_in_background(door, external, seconds=0.5)
    asked, cursor = _asked(door, channel, cursor)
    waiting["_thread"].join(timeout=5)
    # The host records the turn's receipt (the world's routine decided it); then the answer is late.
    world = door["world"]
    society_id = (
        world["connection"]
        .execute(
            "select society_id from world_society where workspace_id = %s and world_id = %s",
            (world["workspace"], _world_id(door)),
        )
        .fetchone()["society_id"]
    )
    receipt = person_role().receipt_profile
    world["connection"].execute(
        "insert into world_society_decision(workspace_id, society_id, decision_seq, request_id, "
        "document, document_sha256) values (%s, %s, 1, %s, %s, %s)",
        (
            world["workspace"],
            society_id,
            external["request_id"],
            Jsonb(_closed(external, receipt)),
            _closed(external, receipt)["document_sha256"],
        ),
    )
    world["connection"].commit()
    late = door["client"].post(
        "/door/channel/answers",
        headers=channel,
        json={
            "request_id": asked["request_id"],
            "request_sha256": asked["request_sha256"],
            "label": asked["context"]["options"][0]["label"],
        },
    )
    assert (late.status_code, late.json()["code"]) == (409, "answer_too_late")
    read = _frames(door, channel, cursor).json()
    assert [frame["kind"] for frame in read["frames"]] == ["outcome"]
    assert (read["frames"][0]["status"], read["frames"][0]["reason"]) == (
        "unavailable",
        "no_answer_in_time",
    )


def _closed(request: dict[str, Any], profile: str) -> dict[str, Any]:
    from exulanica.world.role_decisions import sealed_receipt

    return sealed_receipt(
        profile,
        request,
        1,
        {
            "status": "unavailable",
            "reason": "no_answer_in_time",
            "proposal": None,
            "provider": None,
        },
    )


# -- the tables' own rules ---------------------------------------------------------------------


def test_the_door_tables_keep_their_rules_whoever_writes(door):
    grant_id = _issue(door).json()["grant"]["grant_id"]
    channel = _credential(door, grant_id)
    _hello(door, channel)
    code = door["client"].post(f"/door/grants/{grant_id}/invites", headers=OWNER).json()["code"]
    door["client"].post(f"/door/grants/{grant_id}/revoke", headers=OWNER)
    world = door["world"]
    connection = world["connection"]  # the owner's administrative connection
    for statement in (
        "update door_grant_revision set recorded_by = gen_random_uuid()",
        "delete from door_grant_revision",
        "update door_grant_revocation set revoked_at = revoked_at - interval '1 day'",
        "delete from door_grant_revocation",
        "update door_presence set polled_at = polled_at - interval '1 hour'",
        "delete from door_presence",
        "update door_secret set expires_at = expires_at + interval '1 day'",
        "delete from door_secret",
    ):
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(statement)
    invite = credential_sha256(code.replace("-", ""))
    with connection.transaction():
        connection.execute(
            "update door_secret set used_at = statement_timestamp() where secret_sha256 = %s",
            (invite,),
        )
    with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
        connection.execute(
            "update door_secret set used_at = statement_timestamp() + interval '1 second' "
            "where secret_sha256 = %s",
            (invite,),
        )
    # A revoked grant is not revised again, and nothing is asked under it.
    with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
        connection.execute(
            "insert into door_grant_revision (workspace_id, grant_id, grant_seq, document, "
            "document_sha256, recorded_by) select workspace_id, grant_id, 2, "
            "jsonb_set(document, '{grant_seq}', '2'), repeat('0', 64), recorded_by "
            "from door_grant_revision where grant_id = %s",
            (grant_id,),
        )


def test_another_workspace_sees_no_grant_and_the_runtime_may_change_a_secret_only_when_used(door):
    _issue(door)
    database = door["database"]
    with database.session(uuid.uuid4()) as connection:
        for table in ("door_grant", "door_grant_revision", "door_presence", "door_ask"):
            assert connection.execute(f"select count(*) from {table}").fetchone()["count"] == 0
    with database.session(door["world"]["workspace"]) as connection:
        privileges = connection.execute(
            "select has_table_privilege(current_user, 'door_secret', 'UPDATE') as table_update, "
            "has_column_privilege(current_user, 'door_secret', 'used_at', 'UPDATE') as used, "
            "has_column_privilege(current_user, 'door_secret', 'revoked_at', 'UPDATE') as revoked, "
            "has_column_privilege(current_user, 'door_secret', 'expires_at', 'UPDATE') as ends, "
            "has_table_privilege(current_user, 'door_secret', 'DELETE') as deletes, "
            "has_table_privilege(current_user, 'door_redemption_refusal', 'DELETE') as forgets, "
            "has_function_privilege(current_user, 'door_prune(integer)', 'EXECUTE') as prunes"
        ).fetchone()
    assert privileges == {
        "table_update": False,
        "used": True,
        "revoked": True,
        "ends": False,
        "deletes": False,
        "forgets": False,
        "prunes": True,
    }


def test_an_idle_held_poll_opens_about_one_short_connection_a_second(door, monkeypatch):
    """A held poll keeps no connection while it waits: it opens one for its presence, one per
    head read, about once a second, and none between them (the credential lookup opens one more).
    The bound is the contract's; the measured figures are in the package report."""
    grant_id = _issue(door).json()["grant"]["grant_id"]
    channel = _credential(door, grant_id)
    cursor = _frames(door, channel, _hello(door, channel).json()["cursor"]).json()["cursor"]
    client, _runtime = door["application"](_bridges(door["world"]["workspace"], hold_seconds=3))
    door = {**door, "client": client}
    import exulanica.db.session as session_module

    opened = []
    connect = session_module.psycopg.connect

    def counting(*args, **kwargs):
        opened.append(time.monotonic())
        return connect(*args, **kwargs)

    monkeypatch.setattr(session_module.psycopg, "connect", counting)
    started = time.monotonic()
    idle = _frames(door, channel, cursor)
    elapsed = time.monotonic() - started
    assert idle.status_code == 200 and idle.json()["frames"] == []
    # One for the credential, one for the poll's first read (its presence and head together), and
    # a head read about once a second after it.
    assert 3 <= len(opened) <= 2 + int(elapsed) + 1, (len(opened), elapsed)
    gaps = [later - earlier for earlier, later in itertools.pairwise(opened[2:])]
    assert all(gap >= 0.8 for gap in gaps), gaps


# -- who runs a bridge, and its credentials --------------------------------------------------


def test_who_runs_a_bridge_decides_how_its_grants_open(door):
    offered = door["client"].get("/door/bridges", headers=OWNER).json()["bridges"]
    assert {(b["bridge"], b["run_by"], b["ai"]) for b in offered} == {
        ("test-bridge", "server", False),
        ("other-bridge", "server", False),
        ("owned-bridge", "owner", True),
    }
    # A listed server serves strangers: its grants open by invites, never by a credential handed
    # to the owner, and asking for one issues nothing.
    direct = _issue(door, key="listed-direct", bridge="other-bridge", channel_credential=True)
    assert (direct.status_code, direct.json()["code"]) == (422, "direct_credential_not_offered")
    listed = door["client"].get("/door/grants", headers=OWNER, params={"world_id": _world_id(door)})
    assert listed.json()["grants"] == []
    served = _issue(door, key="listed-server", bridge="other-bridge").json()["grant"]
    assert (served["bridge_label"], served["run_by"], served["ai"]) == (
        "Another bridge",
        "server",
        False,
    )
    credential = door["client"].post(
        f"/door/grants/{served['grant_id']}/channel-credentials", headers=OWNER
    )
    assert (credential.status_code, credential.json()["code"]) == (
        422,
        "direct_credential_not_offered",
    )
    invited = door["client"].post(f"/door/grants/{served['grant_id']}/invites", headers=OWNER)
    assert invited.status_code == 201
    # A program the owner runs takes no invites and is given its credential directly.
    owned = _issue(door, key="owned-program", bridge="owned-bridge", channel_credential=True)
    assert owned.status_code == 201, owned.text
    assert owned.json()["channel_credential"]["shown"] == "once"
    owned_id = owned.json()["grant"]["grant_id"]
    no_invite = door["client"].post(f"/door/grants/{owned_id}/invites", headers=OWNER)
    assert (no_invite.status_code, no_invite.json()["code"]) == (422, "invites_not_offered")
    channel = {"Authorization": f"Bearer {owned.json()['channel_credential']['credential']}"}
    assert _hello(door, channel).status_code == 200


def test_a_grant_keeps_at_most_eight_invites_waiting(door):
    grant_id = _issue(door).json()["grant"]["grant_id"]
    for _ in range(SECRETS_WAITING_MAXIMUM):
        made = door["client"].post(f"/door/grants/{grant_id}/invites", headers=OWNER)
        assert made.status_code == 201
    more = door["client"].post(f"/door/grants/{grant_id}/invites", headers=OWNER)
    assert (more.status_code, more.json()["code"]) == (409, "too_many_secrets")


def test_an_owner_ends_a_grant_s_credentials_without_ending_the_grant(door):
    grant_id = _issue(door).json()["grant"]["grant_id"]
    channel = _credential(door, grant_id)
    assert _hello(door, channel).status_code == 200
    code = door["client"].post(f"/door/grants/{grant_id}/invites", headers=OWNER).json()["code"]
    ended = door["client"].post(f"/door/grants/{grant_id}/credentials/revoke", headers=OWNER)
    assert ended.status_code == 200, ended.text
    assert ended.json()["revoked"] == 2
    assert (ended.json()["grant"]["state"], ended.json()["grant"]["ended"]) == ("active", None)
    assert _frames(door, channel).json()["code"] == "unauthenticated"
    assert _redeem(door, BRIDGE, code).json()["code"] == "invite_not_redeemable"
    # The grant stands: a new credential opens it, and the ended ones stay ended.
    fresh = _credential(door, grant_id)
    assert _hello(door, fresh).status_code == 200
    assert _hello(door, channel).json()["code"] == "unauthenticated"
    stranger = door["client"].post(f"/door/grants/{uuid.uuid4()}/credentials/revoke", headers=OWNER)
    assert (stranger.status_code, stranger.json()["code"]) == (404, "unknown_reference")


def test_once_a_bridge_has_read_that_its_grant_ended_its_polls_and_hellos_are_refused(door):
    grant_id = _issue(door).json()["grant"]["grant_id"]
    channel = _credential(door, grant_id)
    cursor = _hello(door, channel).json()["cursor"]
    door["client"].post(f"/door/grants/{grant_id}/revoke", headers=OWNER)
    # The end is sent once, at once, with no hold; then nothing more is read or said.
    started = time.monotonic()
    read = _frames(door, channel, cursor)
    assert read.status_code == 200 and time.monotonic() - started < 1.0
    assert [frame["kind"] for frame in read.json()["frames"]][-1] == "grant_ended"
    after = _frames(door, channel, read.json()["cursor"])
    assert (after.status_code, after.json()["code"]) == (410, "grant_ended")
    again = _hello(door, channel)
    assert (again.status_code, again.json()["code"]) == (410, "grant_ended")


def test_a_bridge_the_deployment_removed_opens_nothing_and_is_not_asked(door):
    _request, person = _person_request(door)
    grant_id = _grant_for(door, person)
    channel = _credential(door, grant_id)
    assert _hello(door, channel).status_code == 200
    entries = [
        entry
        for entry in json.loads(
            door_support.bridges_setting(listed=False, workspaces=[str(door["world"]["workspace"])])
        )
        if entry["bridge"] != "test-bridge"
    ]
    removed = load_bridge_directory({"EXULANICA_DOOR_BRIDGES": json.dumps(entries)})
    client, runtime = door["application"](removed)
    with client:
        assert client.get("/door/channel/frames", headers=channel).json()["code"] == (
            "unauthenticated"
        )
        # Refused at the credential, before any route's own reading of the bridge.
        answered = client.post(
            "/door/channel/answers",
            headers=channel,
            json={"request_id": str(uuid.uuid4()), "request_sha256": "0" * 64, "label": "wait"},
        )
        assert (answered.status_code, answered.json()["code"]) == (401, "unauthenticated")
        decider = {"kind": "external", "bridge": "test-bridge", "grant_id": str(grant_id)}
        world = door["world"]
        _config, refusal = runtime.asker().configuration(
            world["workspace"], _world_id(door), person, decider
        )
        assert refusal == "decider_disconnected"
        view = client.get(f"/door/grants/{grant_id}", headers=OWNER).json()["grant"]
        assert (view["bridge_label"], view["connected"]) == (None, False)


def test_at_most_six_hellos_a_grant_a_minute(door):
    channel = _credential(door, _issue(door).json()["grant"]["grant_id"])
    assert [_hello(door, channel).status_code for _ in range(6)] == [200] * 6
    seventh = _hello(door, channel)
    assert (seventh.status_code, seventh.json()["code"]) == (429, "too_many_hellos")
    assert seventh.json()["retry_after_s"] == 60


# -- who answered ----------------------------------------------------------------------------


def _answer(door, channel, asked) -> Any:
    return door["client"].post(
        "/door/channel/answers",
        headers=channel,
        json={
            "request_id": asked["request_id"],
            "request_sha256": asked["request_sha256"],
            "label": asked["context"]["options"][0]["label"],
        },
    )


def _slow_asker(door, external, monkeypatch) -> dict[str, Any]:
    """An asker that this process does not wake and that reads its inbox every two seconds, so
    whatever a test does right after answering lands before the asker reads the answer."""
    monkeypatch.setattr("exulanica.door.asker._READ_EVERY_SECONDS", 2.0)
    asker = DoorAsker(database=door["database"], notices=Notices(), bridges=door["runtime"].bridges)
    world = door["world"]
    result: dict[str, Any] = {}

    def run() -> None:
        result.update(
            asker.answer(world["workspace"], _world_id(door), external, time.monotonic() + 8)
        )

    result["_thread"] = threading.Thread(target=run)
    result["_thread"].start()
    return result


def test_an_answer_names_the_adapter_and_declaration_that_gave_it(door, monkeypatch):
    request, person = _person_request(door)
    grant_id = _grant_for(door, person)
    channel = _credential(door, grant_id)
    first = {"name": "Scout", "maker": "Acme"}
    cursor = _hello(door, channel, declared=first).json()["cursor"]
    external = _store_external(door, request, grant_id)
    waiting = _slow_asker(door, external, monkeypatch)
    asked, cursor = _asked(door, channel, cursor)
    assert _answer(door, channel, asked).status_code == 202
    # The program restarts with a newer adapter and new words after answering, before the asker
    # reads the answer: the receipt still names the adapter that answered.
    second = {"name": "Scout", "maker": "Acme", "mind": "Qwen/Qwen3-235B-A22B-Instruct-2507"}
    newer = _hello(
        door, channel, adapter_version=door_support.NEWER_ADAPTER_VERSION, declared=second
    )
    assert newer.status_code == 200, newer.text
    waiting["_thread"].join(timeout=10)
    assert waiting["status"] == "accepted", waiting
    assert waiting["provider"]["adapter_version"] == door_support.ADAPTER_VERSION
    stored = (
        door["world"]["connection"]
        .execute(
            "select w.adapter_version, w.declared_sha256, d.document as declared "
            "from door_answer w join door_declaration d using (workspace_id, declared_sha256) "
            "where w.request_id = %s",
            (external["request_id"],),
        )
        .fetchone()
    )
    assert stored == {
        "adapter_version": door_support.ADAPTER_VERSION,
        "declared_sha256": sha256_of_canonical(first).hex(),
        "declared": first,
    }
    # The owner's view shows what the program says it is now.
    view = door["client"].get(f"/door/grants/{grant_id}", headers=OWNER).json()["grant"]
    assert view["declared"] == second


def test_an_answer_given_under_another_mapping_than_its_request_is_not_accepted(door):
    request, person = _person_request(door)
    grant_id = _grant_for(door, person)
    channel = _credential(door, grant_id)
    cursor = _hello(door, channel).json()["cursor"]
    external = _store_external(door, request, grant_id)
    assert external["provider_config"]["mapping_sha256"] == door_support.mapping_sha256()
    waiting = _ask_in_background(door, external)
    asked, cursor = _asked(door, channel, cursor)
    assert _hello(door, channel, mapping=door_support.mapping(2)).status_code == 200
    assert _answer(door, channel, asked).status_code == 202
    waiting["_thread"].join(timeout=10)
    assert (waiting["status"], waiting["reason"]) == ("unavailable", "decider_disconnected")


def test_no_answer_counts_after_its_grant_is_revoked_whoever_writes_it(door, monkeypatch):
    request, person = _person_request(door)
    grant_id = _grant_for(door, person)
    channel = _credential(door, grant_id)
    cursor = _hello(door, channel).json()["cursor"]
    external = _store_external(door, request, grant_id)
    # The answer and the revocation both land before the asker reads.
    result = _slow_asker(door, external, monkeypatch)
    asked, cursor = _asked(door, channel, cursor)
    assert _answer(door, channel, asked).status_code == 202
    door["client"].post(f"/door/grants/{grant_id}/revoke", headers=OWNER)
    result["_thread"].join(timeout=10)
    assert (result["status"], result["reason"]) == ("unavailable", "grant_revoked")


# -- retention and bounds --------------------------------------------------------------------


def test_only_door_prune_removes_global_rows_and_only_past_their_retention(door):
    grant_id = _issue(door).json()["grant"]["grant_id"]
    channel = _credential(door, grant_id)
    world = door["world"]
    admin = world["connection"]
    with admin.transaction():
        admin.execute(
            "select set_config('exulanica.workspace_id', %s, true)", (str(world["workspace"]),)
        )
        admin.execute(
            "insert into door_secret (secret_sha256, kind, bridge, workspace_id, grant_id, "
            "created_at, expires_at) values (%s, 'channel', 'test-bridge', %s, %s, "
            "statement_timestamp() - interval '40 days', "
            "statement_timestamp() - interval '31 days')",
            ("1" * 64, world["workspace"], grant_id),
        )
        admin.execute(
            "insert into door_redemption_refusal (bridge, requester_sha256, refused_at) "
            "values ('test-bridge', %s, statement_timestamp() - interval '2 days'), "
            "('test-bridge', %s, statement_timestamp())",
            (SOMEONE, SOMEONE),
        )
    with door["database"].session(world["workspace"]) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute("delete from door_redemption_refusal")
        pruned = connection.execute("select door_prune(100) as pruned").fetchone()["pruned"]
    assert pruned == 2
    left = admin.execute(
        "select (select count(*) from door_secret where secret_sha256 = %s) as old_secret, "
        "(select count(*) from door_redemption_refusal) as refusals",
        ("1" * 64,),
    ).fetchone()
    assert left == {"old_secret": 0, "refusals": 1}
    # The live credential was kept, and still opens its channel.
    assert _hello(door, channel).status_code == 200


def test_a_body_past_its_route_s_bound_is_refused_before_it_is_read(door):
    channel = _credential(door, _issue(door).json()["grant"]["grant_id"])
    answers = door["client"].post(
        "/door/channel/answers",
        headers=channel,
        content=json.dumps({"label": "x" * 5000}),
    )
    assert (answers.status_code, answers.json()["code"]) == (413, "body_too_large")
    hello = door["client"].post(
        "/door/channel/hello",
        headers=channel,
        content=json.dumps({"mapping": {"padding": "x" * 70_000}}),
    )
    assert (hello.status_code, hello.json()["code"]) == (413, "body_too_large")
