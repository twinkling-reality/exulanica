"""An authored unusual being is model-decided through normal API choices and leased playback.

The Canopy strider assets rebuild from their original recipe. Provider answers/rates are
scripted exclusively inside this private test; no review runtime is reached. Observation,
invalid-answer repair, validated speech, heard events, source identity and replay are stored
by product code. Assets and cosmetic motion are not model output.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import time
import uuid
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from exulanica.api import decision_host as decision_host_module
from exulanica.api.permissions import Permission
from exulanica.models.errors import ProviderRefused
from exulanica.models.transport import HttpResponse
from exulanica.spending.ledger import DurableSpending
from exulanica.spending.operator import SpendingOperator
from exulanica.spending.witness import FileSpendingWitness
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.world import saved_entries
from exulanica.world.model_probe_worker import ModelProbeWorker
from exulanica.world.thing_store import ThingStore
from scripts.things.author_surfaces import assemble_authored

from living_session_support import LIMITS
from model_fakes import chat_body
from personal_world_support import OWNER_TOKEN, STRANGER_TOKEN
from spending_support import WorkspacePolicy, spending_client
from test_model_probes_postgres import ProbeTransport, _candidate
from test_site_society_of_things_postgres import FARM, V7, _place, _site
from test_society_made_world import made as made
from tests_support_api import scratch_database

pytestmark = pytest.mark.postgres
ASSETS = Path(__file__).resolve().parents[1] / "assets/things/canopy-strider"
PRIMARY = "inhabitant:generated-strider"
OBSERVER = "inhabitant:nearby-observer"
GREETING = "Canopy strider, can you hear me?"
REPLY = "I heard your greeting. I can speak here, but I cannot walk or fly."


class Responding(ProbeTransport):
    """Fixture only: one invalid option, then a validated reply; another identity refuses later."""

    runtime = False
    wrong_identity = False
    missing_usage = False
    runtime_asks = 0

    def post_json(self, url, *, headers, payload, timeout):
        if not self.runtime:
            return super().post_json(url, headers=headers, payload=payload, timeout=timeout)
        self.runtime_asks += 1
        self.requests.append({"url": url, "payload": dict(payload)})
        schema = (
            payload["response_format"]["json_schema"]["schema"]
            if "response_format" in payload
            else payload["tools"][0]["function"]["parameters"]
        )
        labels = schema["properties"]["action"]["enum"]
        label = next(label for label in labels if label == "say something to everyone near you")
        answer = {
            "action": "fly across the water" if self.runtime_asks == 1 else label,
            "line": REPLY,
        }
        body = chat_body(
            json.dumps(answer),
            model="unadmitted/other-model" if self.wrong_identity else payload["model"],
        )
        if self.wrong_identity and self.missing_usage:
            body.pop("usage", None)
        if "tools" in payload:
            body["choices"][0]["message"]["content"] = None
            body["choices"][0]["message"]["tool_calls"] = [
                {
                    "id": "private-test-response",
                    "type": "function",
                    "function": {"name": "act", "arguments": json.dumps(answer)},
                }
            ]
            body["choices"][0]["finish_reason"] = "tool_calls"
        return HttpResponse(200, json.dumps(body))


def _configured(api, control_path, mode):
    read = api.get(control_path)
    assert read.status_code == 200, read.text
    result = api.put(
        control_path, {"base_revision": read.json()["revision"], "mode": mode, "speed": 1}
    )
    assert result.status_code == 200, result.text
    return result.json()


def _minute(api, worker, society, control, workspace):
    """One minute as a living session plays it: opened (which plays the society) and paused (which
    closes it). A model is asked only inside a session."""
    before = api.get(society).json()
    read = api.get(control).json()
    opened = api.post(
        control.replace("/control?", "/control/sessions?"),
        {
            "request_id": str(uuid.uuid4()),
            "base_revision": read["revision"],
            "base_tick": read["current_tick"],
            "base_state_sha256": read["state_sha256"],
            "limits": LIMITS,
        },
    )
    assert opened.status_code == 201, opened.text
    until = time.monotonic() + 10
    while (result := worker.run_once(workspace)) is None:
        assert time.monotonic() < until, "the configured playback minute never became due"
        time.sleep(0.05)
    _configured(api, control, "paused")
    after = api.get(society)
    assert after.status_code == 200, after.text
    assert after.json()["current_tick"] == before["current_tick"] + 1
    return after.json(), result


def _play(api, play_path, subject):
    response = api.post(play_path, {"idempotency_key": str(uuid.uuid4()), "subject_id": subject})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("missing_usage", [False, True], ids=["reported_usage", "unknown_cost"])
def test_generated_stationary_creature_observes_and_speaks_by_a_chosen_model_with_replay(
    made, tmp_path, spine_schema, monkeypatch, missing_usage
):
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: FARM)
    api = made
    entry, society, _records = _site(api, "farm", "fixture_farm", "small_farm")
    creature, asset_receipt = assemble_authored(json.loads((ASSETS / "authoring.json").read_text()))
    assert (
        creature.kind.sha256
        == hashlib.sha256((ASSETS / "porcelain-v3/kind.json").read_bytes()).hexdigest()
    )
    assert asset_receipt["model_receipts"] == []
    with api.database.session(api.repository.workspace_id) as connection:
        ThingStore(connection, api.repository.workspace_id, api.store).keep_creature(
            creature, created_by=api.actor
        )
    # Inside the generated farm's open yard with a nearby observer. Actual snapped positions
    # and heard events are authoritative; this proves neither giant locomotion nor body collision
    # quality. Keep margin inside the declared hearing range for the world's node snapping.
    _place(
        api, entry, PRIMARY, {"source": "workspace", "sha256": creature.kind.sha256}, 20000, -22000
    )
    knight = shipped_thing_kinds()[("knight", 1)]
    _place(
        api,
        entry,
        OBSERVER,
        {"kind": "knight", "version": 1, "sha256": knight.sha256},
        23000,
        -22000,
    )
    # A reproducible fixture population/standing choice; production still derives its own seed.
    api.client.app.state.services = replace(
        api.client.app.state.services, society_seed=lambda _workspace, _world: "7" * 64
    )
    created = api.post(society, {"region_id": "region:generated", "profile": V7})
    assert created.status_code in (200, 201), created.text
    body = created.json()
    primary = next(p for p in body["state"]["inhabitants"] if p.get("placed_id") == PRIMARY)
    observer = next(p for p in body["state"]["inhabitants"] if p.get("placed_id") == OBSERVER)
    subject, listener = primary["id"], observer["id"]
    workspace = api.repository.workspace_id
    base = f"/world/versions/{entry['authored_version_id']}"
    scope = f"?world_id={entry['world_id']}"
    root = base + "/society"
    control = root + "/control" + scope
    play = root + "/play"
    role_path = base + "/models/society_decision" + scope
    models_path = base + "/models" + scope
    services = replace(
        api.client.app.state.services,
        society_control_workspaces=(workspace,),
        society_base_tick_interval_ms=1000,
    )
    api.client.app.state.services = services
    # Match the API's startup cadence snapshot to this fixture host's declared configuration;
    # no society row, clock, claim or deadline is rewritten to make a minute due.
    api.client.app.state.society_base_tick_interval_ms = services.society_base_tick_interval_ms
    worker = services.build_society_control_worker()
    assert worker is not None
    _play(api, play + scope, listener)
    turn = api.get(play + f"/{listener}/turn" + scope).json()
    greeting = next(
        o for o in turn["options"] if o["kind"] == "say_to" and o["being_id"] == subject
    )
    answer = api.post(
        play + f"/{listener}/answer" + scope,
        {"base_tick": turn["base_tick"], "label": greeting["label"], "line": GREETING},
    )
    assert answer.status_code == 202, answer.text
    body, greeting_round = _minute(api, worker, society, control, workspace)
    primary = next(p for p in body["state"]["inhabitants"] if p["id"] == subject)
    assert any(line["line"] == GREETING and line["to"] == subject for line in primary["heard"])
    _play(api, play + scope, subject)
    primary_turn = api.get(play + f"/{subject}/turn" + scope).json()
    assert {o["kind"] for o in primary_turn["options"]} <= {"wait", "carry_on", "say_to", "say_all"}

    stated = _candidate()
    assert stated.licence_stated == "Apache 2.0 License"
    witness = FileSpendingWitness(tmp_path / "fixture-spending")
    operator = SpendingOperator(scratch_database(spine_schema[1]), witness)
    until = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)
    authority = operator.issue(
        provider=stated.provider,
        ceiling_usd=Decimal("1"),
        max_calls=64,
        valid_until=until,
        operator="private-test",
        reason="scripted normal-flow evidence",
    )
    operator.grant(
        authority,
        workspace,
        ceiling_usd=Decimal("1"),
        max_calls=64,
        valid_until=until,
        operator="private-test",
        reason="scripted normal-flow evidence",
    )
    spending = DurableSpending(api.database, witness, holder="generated-model-flow")
    transport = Responding()
    client = spending_client(spending, transport)
    services = replace(
        services,
        model_client=client,
        spending=spending,
        admits_workspace_models=True,
        runs_model_probe_worker=True,
        model_probe_workspaces=(workspace,),
    )
    api.client.app.state.services = services
    request = {
        "provider": stated.provider,
        "model_id": stated.model_id,
        "request_id": str(uuid.uuid4()),
    }
    added = api.post("/models", request)
    assert added.status_code == 200, added.text
    prepared = api.post("/models/probes/prepare", {**request, "request_id": str(uuid.uuid4())})
    assert prepared.status_code == 200, prepared.text
    quote = prepared.json()
    probe_id = quote["probe_id"]
    start = api.post(
        f"/models/probes/{probe_id}/start",
        {
            "request_id": str(uuid.uuid4()),
            "definition_sha256": quote["definition"]["document_sha256"],
            "ceiling_usd": quote["definition"]["operation_estimate"]["ceiling_usd"],
        },
    )
    assert start.status_code == 202, start.text
    prober = ModelProbeWorker(
        api.database,
        client=client,
        spending=spending,
        policy_for=WorkspacePolicy,
        workspaces=lambda: (workspace,),
    )
    assert prober.turn(workspace)
    choice = {
        "idempotency_key": str(uuid.uuid4()),
        "subjects": [subject],
        "model": {"provider": stated.provider, "model_id": stated.model_id},
    }
    still_played = api.post(role_path, choice)
    assert still_played.status_code == 409 and still_played.json()["code"] == "being_played"
    returned = api.post(
        play + f"/{subject}/give-back" + scope, {"idempotency_key": str(uuid.uuid4())}
    )
    assert returned.status_code == 200, returned.text
    owner_digest = hashlib.sha256(OWNER_TOKEN.encode()).hexdigest()
    api.client.app.state.services = replace(
        services,
        tokens=replace(
            services.tokens,
            permissions={
                **services.tokens.permissions,
                owner_digest: frozenset({Permission.WORLD_READ, Permission.WORLD_WRITE}),
            },
        ),
    )
    denied = api.post(role_path, choice)
    assert denied.status_code == 404, denied.text
    assert denied.json()["code"] == "unknown_reference"
    api.client.app.state.services = services
    foreign = api.post(role_path, choice, token=STRANGER_TOKEN)
    assert foreign.status_code == 404, foreign.text
    chosen = api.post(role_path, choice)
    assert chosen.status_code == 200, chosen.text
    offered = api.get(models_path)
    assert offered.status_code == 200, offered.text
    people_role = next(r for r in offered.json()["roles"] if r["key"] == "society_decision")
    assert (
        next(c for c in people_role["view"]["choices"] if c["subject_id"] == subject)["model"][
            "model_id"
        ]
        == stated.model_id
    )
    completed_probe = api.get(f"/models/probes/{probe_id}").json()
    current_read = people_role["view"]
    selected_view = next(c for c in current_read["choices"] if c["subject_id"] == subject)
    if output := os.environ.get("EXULANICA_GENERATED_MODEL_EVIDENCE"):
        Path(output + ".checkpoint.json").write_text(
            json.dumps(
                {
                    "phase": "before_model_playback",
                    "evidence_kind": "private_scripted_fixture_diagnostic",
                    "probe": completed_probe,
                    "selected": selected_view,
                    "offered_models": current_read["models"],
                    "host_refusal": current_read["host_refusal"],
                    "primary_after_greeting": primary,
                },
                indent=2,
            )
            + "\n"
        )
    assert completed_probe["outcome"]["verified"], completed_probe["outcome"]
    assert selected_view["refusal"] is None, selected_view
    assert stated.model_id in {m["model_id"] for m in current_read["models"]}
    transport.runtime = True
    worker = services.build_society_control_worker()
    response_rounds = []
    for _ in range(8):
        body, response_round = _minute(api, worker, society, control, workspace)
        response_rounds.append(response_round)
        events = api.get(root + "/events" + scope).json()["events"]
        said = next(
            (
                e
                for e in events
                if e["event_kind"] == "said" and e["document"].get("thing", {}).get("line") == REPLY
            ),
            None,
        )
        if said is not None:
            break
    else:
        pytest.fail(
            "the chosen stationary being reached no validated speech: "
            + json.dumps(api.get(root + "/models" + scope).json()["latest"])
        )
    assert listener in said["document"]["thing"]["heard_by"]
    applied = next(
        e
        for e in events
        if e["event_kind"] == "decision_applied"
        and e["document"]["subject_id"] == subject
        and e["document"]["disposition"] == "applied"
    )
    receipt = api.get(root + "/decisions/" + applied["document"]["request_id"] + scope)
    assert receipt.status_code == 200, receipt.text
    receipt = receipt.json()
    context = receipt["request"]["context"]
    run_form = body["state"]["kinds"][creature.kind.sha256]
    assert context["being"] == {"kind": run_form["label"], "summary": run_form["summary"]}
    assert context["subject_id"] == subject
    assert any(line["line"] == GREETING for line in context["heard"])
    assert {o["kind"] for o in context["options"]} <= {"wait", "carry_on", "say_to", "say_all"}
    assert receipt["decision"]["status"] == "accepted"
    assert receipt["decision"]["proposal"]["option"]["kind"] == "say_all"
    assert receipt["decision"]["proposal"]["line"] == REPLY
    assert transport.runtime_asks == 2
    assert any(GREETING in str(r["payload"]["messages"]) for r in transport.requests[-2:])
    assert receipt["decision"]["provider"]["served_model_id"] == stated.model_id
    digest = receipt["request"]["provider_config"]["manifest_sha256"]
    source = api.get("/models/bindings/" + digest)
    assert source.status_code == 200, source.text
    assert source.json()["sources"][0]["probe_id"] == probe_id
    assert source.json()["sources"][0]["role"] == "society_decision"
    assert (
        next(p for p in body["state"]["inhabitants"] if p["id"] == subject)["position_mm"]
        == primary["position_mm"]
    )
    # At the next choice point, a response identifying a different model is refused, never spoken.
    second_turn = api.get(play + f"/{listener}/turn" + scope).json()
    second_option = next(
        o for o in second_turn["options"] if o["kind"] == "say_to" and o["being_id"] == subject
    )
    second_answer = api.post(
        play + f"/{listener}/answer" + scope,
        {
            "base_tick": second_turn["base_tick"],
            "label": second_option["label"],
            "line": "Can you answer again from where you are?",
        },
    )
    assert second_answer.status_code == 202, second_answer.text
    observed_refusals = []
    original_failure_reason = decision_host_module._failure_reason

    def observe_refusal(exc):
        if isinstance(exc, ProviderRefused):
            observed_refusals.append(exc.reason)
        return original_failure_reason(exc)

    monkeypatch.setattr(decision_host_module, "_failure_reason", observe_refusal)
    transport.wrong_identity = True
    transport.missing_usage = missing_usage
    for _ in range(8):
        body, refusal_round = _minute(api, worker, society, control, workspace)
        latest = api.get(root + "/models" + scope).json()["latest"]
        if any(d["subject_id"] == subject and d["reason"] == "model_call_failed" for d in latest):
            break
    else:
        pytest.fail("wrong served identity was not recorded as unavailable")
    refused_event = next(
        e
        for e in api.get(root + "/events" + scope).json()["events"]
        if e["event_kind"] == "decision_applied"
        and e["document"]["subject_id"] == subject
        and e["document"].get("reason") == "model_call_failed"
    )
    refused = api.get(root + "/decisions/" + refused_event["document"]["request_id"] + scope)
    assert refused.status_code == 200, refused.text
    refused = refused.json()
    assert refused["decision"]["status"] == "unavailable"
    assert refused["decision"]["proposal"] is None
    assert refused["decision"]["provider"]["served_model_id"] is None
    assert observed_refusals == ["model_binding_identity_mismatch"]
    assert refused["decision"]["provider"]["cost_known"] is (not missing_usage)
    assert refused["decision"]["provider"]["calls"][0]["cost_basis"] == (
        "unknown" if missing_usage else "known"
    )
    assert all(
        call["outcome"] == "reply_refused" for call in refused["decision"]["provider"]["calls"]
    )
    events = api.get(root + "/events" + scope).json()["events"]
    assert (
        sum(
            e["event_kind"] == "said" and e["document"].get("thing", {}).get("line") == REPLY
            for e in events
        )
        == 1
    )
    calls = transport.call_count
    replay = api.get(root + "/replay" + scope)
    assert replay.status_code == 200 and replay.json()["replay_verified"], replay.text
    assert replay.json()["state_sha256"] == body["state_sha256"]
    assert transport.call_count == calls
    assert client.budget.billed_calls == transport.call_count
    assert client.budget.held_calls == 0
    assert client.budget.held_usd == 0
    with api.database.session(workspace) as connection:
        reservations = connection.execute(
            "select request_key,model_id,state,reserved_usd,settled_usd,cost_basis "
            "from spending_reservation where workspace_id=%s order by admitted_at",
            (workspace,),
        ).fetchall()
    assert len(reservations) == transport.call_count
    assert all(row["state"] in ("settled", "unknown") for row in reservations)
    assert reservations[-1]["cost_basis"] == ("unknown" if missing_usage else "reported")
    if missing_usage:
        assert reservations[-1]["settled_usd"] >= reservations[-1]["reserved_usd"]
    if output := os.environ.get("EXULANICA_GENERATED_MODEL_EVIDENCE"):
        evidence_file = output + (".unknown-cost.json" if missing_usage else "")
        Path(evidence_file).write_text(
            json.dumps(
                {
                    "evidence_kind": (
                        "scripted_provider_private_postgres_normal_routes_leased_worker"
                    ),
                    "live_quality_verified": False,
                    "actual_provider_spend": False,
                    "asset_generation": "original_declarative_authoring",
                    "asset_receipt": asset_receipt,
                    "world": entry,
                    "inhabitant_id": subject,
                    "observer_id": listener,
                    "model": {
                        "provider": stated.provider,
                        "model_id": stated.model_id,
                        "licence_stated": stated.licence_stated,
                    },
                    "normal_role_read": offered.json(),
                    "owner_choice": chosen.json(),
                    "probe": api.get(f"/models/probes/{probe_id}").json(),
                    "greeting_round": greeting_round,
                    "response_rounds": response_rounds,
                    "refusal_round": refusal_round,
                    "context_and_decision": receipt,
                    "refused_decision": refused,
                    "lower_level_refusals": observed_refusals,
                    "missing_usage": missing_usage,
                    "fixture_seed": "7" * 64,
                    "dispatches": transport.call_count,
                    "process_billed_attempts": client.budget.billed_calls,
                    "process_held_attempts": client.budget.held_calls,
                    "durable_reservations": [
                        {k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()}
                        for row in reservations
                    ],
                    "binding_source": source.json(),
                    "said": said,
                    "applied": applied,
                    "events": events,
                    "replay": replay.json(),
                    "authorization": {
                        "without_model_invoke": denied.status_code,
                        "foreign_workspace": foreign.status_code,
                    },
                },
                indent=2,
            )
            + "\n"
        )
