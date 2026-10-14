"""What a living session has used, and what it came to, read back.

Shown against the database with the real playback worker and decision host:

*   the control read states the society's latest session, null before any, open with what it has
    used of each limit so far, and closed with why and where it ended;
*   a session's read holds only the decisions asked for its own minutes, each with its request id
    in decision order, and measures its model decisions overall and per model; a later session's
    read holds the rest;
*   a person's answer for a being they play is among a session's decisions but never counted
    against the model decisions it may ask;
*   each provider's bound states what it committed, which is what the session used, and a call
    whose cost nobody knows stays unresolved in both.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from decimal import Decimal

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import TransportError
from exulanica.models.transport import HttpResponse
from exulanica.selection.validation import Session
from exulanica.spending.status import read_spending_refusals
from exulanica.world.society_control_repository import SocietyControlRepository
from exulanica.world.society_controls import LEASE_SECONDS
from exulanica.world.society_sessions import SESSION_CLOSED_WORDS, UNWORDED_CLOSE

import test_outside_deciders_postgres as outside
import test_society_person_decisions_postgres as person_decisions
import test_society_play_postgres as play
import test_society_stay_requests_api as stays
from model_fakes import FakeTransport, chat_body
from test_guest_model_minds_postgres import admin_rows
from test_living_session_limits_postgres import _durable, _host, _play_until_closed, _played
from test_living_session_models_postgres import LIMITS, _session

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres

ZERO = "0.00000000"


class _Answering(FakeTransport):
    """A scripted model that answers every ask: the first offered place to go, as the person
    decision tests' chooser picks, or, where a minute offers none, the first option that is not a
    conversation. These tests are about what a session's reads say of its decisions, so no ask may
    fail on which options a minute happened to offer."""

    def post_json(self, url, *, headers, payload, timeout):
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        tool = payload["tools"][0]["function"]
        offered = [
            label
            for label in tool["parameters"]["properties"]["action"]["enum"]
            if not label.startswith(person_decisions._TALK_LABEL)
        ]
        chosen = next((label for label in offered if " m away" in label), offered[0])
        body = chat_body("", model=payload["model"], finish_reason="tool_calls")
        body["choices"][0]["message"]["content"] = None
        body["choices"][0]["message"]["tool_calls"] = [
            {
                "id": "c",
                "type": "function",
                "function": {"name": tool["name"], "arguments": json.dumps({"action": chosen})},
            }
        ]
        return HttpResponse(200, json.dumps(body))


def _control(client, world) -> dict:
    params, version, _society = person_decisions.routes(world)
    read = client.get(version + "/society/control", headers=person_decisions.OWNER, params=params)
    assert read.status_code == 200, read.text
    return read.json()


def _read(client, world, session_id: str) -> dict:
    params, version, _society = person_decisions.routes(world)
    one = client.get(
        version + f"/society/control/sessions/{session_id}",
        headers=person_decisions.OWNER,
        params=params,
    )
    assert one.status_code == 200, one.text
    return one.json()


def _model_requests(services, world, snapshot) -> list[str]:
    """Every request asked of a model in the society, in decision order, from the tables."""
    with services.database.session(world["workspace"]) as connection:
        return [
            row["request_id"]
            for row in connection.execute(
                "select d.request_id::text from world_society_decision d "
                "join world_society_decision_request r using (workspace_id,society_id,request_id) "
                "where d.workspace_id=%s and d.society_id=%s "
                "and r.document->'provider_config'->>'kind' is null order by d.decision_seq",
                (world["workspace"], snapshot["society_id"]),
            ).fetchall()
        ]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_control_and_session_reads_state_each_session_s_own_decisions(app, monkeypatch):
    world, client = app
    services = person_decisions._services(client)
    manifest, model_id = person_decisions._offered()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    person_decisions._choose(services, world, people, model, manifest=manifest, open_session=False)
    transport = _Answering()
    host = _host(services, world, manifest, person_decisions._client(manifest, transport))
    worker = _played(services, world, host)
    assert _control(client, world)["session"] is None

    first = _session(client, world, limits={**LIMITS, "decisions": 2})
    now = _control(client, world)["session"]
    assert (now["session_id"], now["state"], now["limits"]) == (
        first["session_id"],
        "open",
        first["opened"]["limits"],
    )
    assert (now["start_tick"], now["end_tick"], now["closed_at"], now["closed_reason"]) == (
        first["opened"]["start_tick"],
        None,
        None,
        None,
    )
    assert {key: now["used"][key] for key in ("minutes", "decisions", "usd", "calls")} == {
        "minutes": 0,
        "decisions": 0,
        "usd": ZERO,
        "calls": 0,
    }
    assert now["used"]["unresolved"] == {"count": 0, "usd": ZERO}
    assert _play_until_closed(services, world, worker)["reason"] == "session_decisions"
    ended = _control(client, world)["session"]
    assert (ended["session_id"], ended["state"], ended["closed_reason"]) == (
        first["session_id"],
        "closed",
        "session_decisions",
    )
    assert ended["used"]["decisions"] == 2
    assert ended["used"]["minutes"] == ended["end_tick"] - ended["start_tick"] > 0
    # Why it closed, in the one wording both reads serve.
    words = SESSION_CLOSED_WORDS["session_decisions"]
    assert ended["closed_reason_words"] == words
    read_first = _read(client, world, first["session_id"])
    assert read_first["used"] == ended["used"]
    assert read_first["closed"]["words"] == words

    second = _session(client, world, limits={**LIMITS, "decisions": 3})
    # A minute's people may be asked together: two of them may be due at once.
    assert _play_until_closed(services, world, worker)["reason"] == "session_decisions"
    read_first = _read(client, world, first["session_id"])
    read_second = _read(client, world, second["session_id"])
    # What a closed session used stays as it closed, whatever plays after it.
    assert read_first["used"] == ended["used"]
    assert _control(client, world)["session"]["session_id"] == second["session_id"]

    # Holding fewer than the session asked, the read says so: its total stays every decision.
    monkeypatch.setattr("exulanica.world.society_control_repository.SESSION_DECISIONS_READ", 1)
    capped = _read(client, world, second["session_id"])
    assert capped["decisions_read"] == {"counted": 1, "maximum": 1, "total": 3}
    assert [one["request_id"] for one in capped["decisions"]] == [
        one["request_id"] for one in read_second["decisions"]
    ][-1:]
    monkeypatch.undo()

    asked = _model_requests(services, world, snapshot)
    assert len(asked) == len(transport.requests) == 5
    mine = [one["request_id"] for one in read_first["decisions"]]
    theirs = [one["request_id"] for one in read_second["decisions"]]
    # Each holds its own minutes' decisions, in decision order, and nothing of the other's.
    assert mine + theirs == asked
    assert (len(mine), len(theirs)) == (2, 3)
    for read, opened in ((read_first, first), (read_second, second)):
        start = opened["opened"]["start_tick"]
        end = read["closed"]["end_tick"]
        assert all(start <= one["base_tick"] < end for one in read["decisions"])
        assert {one["decider"] for one in read["decisions"]} == {"model"}
        assert [one["decision_seq"] for one in read["decisions"]] == sorted(
            one["decision_seq"] for one in read["decisions"]
        )
        # The whole session is held: every decision, each with how its ask ended.
        assert read["decisions_read"] == {
            "counted": len(read["decisions"]),
            "maximum": 2000,
            "total": len(read["decisions"]),
        }
        assert {(one["status"], one["reason"]) for one in read["decisions"]} == {
            ("accepted", "validated_choice")
        }
        assert read["measures"]["counts"]["decisions"] == read["used"]["decisions"]
        # Every ask was answered, so every decision is a call the measures cost.
        assert read["measures"]["counts"]["unavailable"] == 0
        assert read["measures"]["cost"]["calls"] == len(read["decisions"])
        assert [(one["provider"], one["model_id"]) for one in read["by_model"]] == [
            (model["provider"], model["model_id"])
        ]
        assert read["by_model"][0]["measures"] == read["measures"]
        # Without a spending authority no bound was opened.
        assert read["bounds"] == []


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_person_s_answer_is_a_session_decision_but_not_a_model_decision(app):
    world, client = app
    services = person_decisions._services(client)
    snapshot, knight = play._knight_society(world, client, beside=True)
    assert play._start(client, world, knight).status_code == 201
    scope, _, society = person_decisions.routes(world)
    turn = client.get(
        f"{society}/play/{knight}/turn", headers=person_decisions.OWNER, params=scope
    ).json()
    chosen = next(option for option in turn["options"] if option["takes_line"])
    answered = play._post(
        client,
        f"{society}/play/{knight}/answer",
        scope,
        {"base_tick": turn["base_tick"], "label": chosen["label"], "line": "Good evening."},
    )
    assert answered.status_code == 202, answered.text
    opened = _session(client, world)
    host = dataclasses.replace(
        outside._doorkeeping_host(world, services, None), workspaces=frozenset()
    )
    assert host.before_minute(
        person_decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
    )
    read = _read(client, world, opened["session_id"])
    assert [(one["subject_id"], one["decider"]) for one in read["decisions"]] == [
        (knight, "person")
    ]
    # Counted among every decision of the session, never among its model decisions.
    assert read["decisions_read"]["total"] == 1
    assert read["used"]["decisions"] == 0
    assert read["measures"]["counts"]["decisions"] == 0 and read["by_model"] == []
    assert _control(client, world)["session"]["used"]["decisions"] == 0
    # Pausing answers the control read with the session it closed.
    control = _control(client, world)
    params, version, _society = person_decisions.routes(world)
    paused = client.put(
        version + "/society/control",
        headers=person_decisions.OWNER,
        params=params,
        json={"base_revision": control["revision"], "mode": "paused", "speed": control["speed"]},
    )
    assert paused.status_code == 200, paused.text
    closed = paused.json()["session"]
    assert (closed["session_id"], closed["state"], closed["closed_reason"]) == (
        opened["session_id"],
        "closed",
        "paused_by_person",
    )
    assert closed["closed_reason_words"] == SESSION_CLOSED_WORDS["paused_by_person"]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_reason_without_words_still_closes_the_session_and_says_so_plainly(app, caplog):
    """A close is how a session's spending stops, so it is never refused for want of words: the
    session closes by the reason it was given, both reads say so plainly, and the missing words
    are logged."""
    world, client = app
    services = person_decisions._services(client)
    stays._inhabited(world, client)
    opened = _session(client, world)
    binding, workspace, actor = world["binding"], world["workspace"], world["session"].actor
    caplog.set_level(logging.WARNING, logger="exulanica.world.society_control_repository")
    with services.database.session(workspace) as connection:
        controls = SocietyControlRepository(
            connection,
            workspace,
            world_id=binding.world_id,
            input_authorizer=lambda who, document: services.society_runtime.authorize(
                connection, Session(workspace_id=workspace, actor=who), document
            ),
        )
        read = controls.read(binding.version_id)
        controls.configure(
            binding.version_id,
            actor=actor,
            base_revision=read["revision"],
            mode="paused",
            speed=read["speed"],
            closing_reason="a_reason_nobody_worded",
        )
    now = _control(client, world)["session"]
    assert (now["session_id"], now["state"], now["closed_reason"]) == (
        opened["session_id"],
        "closed",
        "a_reason_nobody_worded",
    )
    assert now["closed_reason_words"] == UNWORDED_CLOSE
    assert _read(client, world, opened["session_id"])["closed"]["words"] == UNWORDED_CLOSE
    assert any(
        "no words: a_reason_nobody_worded" in record.getMessage() for record in caplog.records
    )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
@pytest.mark.parametrize("ending", ["spent", "unknown"])
def test_each_bound_states_what_the_session_used_and_what_is_unresolved(
    app, spine_schema, tmp_path, ending
):
    world, client = app
    services = person_decisions._services(client)
    manifest, model_id = person_decisions._offered()
    provider = manifest.spec(model_id).provider
    admin, durable = _durable(services, world, spine_schema, tmp_path, provider)
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": provider, "model_id": model_id}
    person_decisions._choose(services, world, people, model, manifest=manifest, open_session=False)
    transport = (
        _Answering()
        if ending == "spent"
        else FakeTransport(
            [TransportError("timed out", timed_out=True, reached_provider=None)] * 10
        )
    )
    model_client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("100"), max_calls=1000),
        spending=durable,
    )
    host = _host(
        services,
        world,
        manifest,
        model_client,
        spending=durable,
        spending_refusals=lambda connection, workspace: read_spending_refusals(
            connection, workspace, witness_configured=True
        ),
    )
    calls = 1 if ending == "spent" else 100
    opened = _session(client, world, limits={**LIMITS, "calls": calls})
    worker = _played(services, world, host, spending=durable)
    _play_until_closed(services, world, worker)
    read = _read(client, world, opened["session_id"])
    [bound] = read["bounds"]
    [row] = admin_rows(
        admin,
        "select g.grant_id::text, gs.committed_usd::text, gs.committed_calls "
        "from spending_grant g join spending_grant_state gs using (workspace_id, grant_id) "
        "where g.workspace_id = %s and g.bound_key = %s",
        world["workspace"],
        f"living-session:{opened['session_id']}:{provider}",
    )
    assert (bound["provider"], bound["bound_id"], bound["state"]) == (
        provider,
        row["grant_id"],
        "closed",
    )
    assert (bound["committed_usd"], bound["committed_calls"]) == (
        row["committed_usd"],
        row["committed_calls"],
    )
    assert (bound["max_calls"], read["used"]["calls"]) == (calls, row["committed_calls"])
    assert read["used"]["usd"] == row["committed_usd"]
    unknown = admin_rows(
        admin,
        "select settled_usd::text from spending_reservation "
        "where workspace_id = %s and state = 'unknown'",
        world["workspace"],
    )
    if ending == "spent":
        assert row["committed_calls"] == 1 and unknown == []
        assert bound["unresolved"] == read["used"]["unresolved"] == {"count": 0, "usd": ZERO}
    else:
        assert len(unknown) >= 1
        assert bound["unresolved"]["count"] == read["used"]["unresolved"]["count"] == len(unknown)
    assert _control(client, world)["session"]["used"] == read["used"]
