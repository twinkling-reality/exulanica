"""An unshipped candidate reaches an actual fixture being through owner choice and replay.

All provider answers and rates are scripted; actual product client, PostgreSQL, durable
spending, world, role, owner routes, playback host and replay boundaries are exercised.
"""

import datetime as dt
import json
import os
import time
import uuid
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from exulanica.models.transport import HttpResponse
from exulanica.spending.ledger import DurableSpending
from exulanica.spending.operator import SpendingOperator
from exulanica.spending.witness import FileSpendingWitness
from exulanica.world import saved_entries
from exulanica.world.model_probe_worker import ModelProbeWorker
from exulanica.world.society_controls import LEASE_SECONDS, ControlClaim
from exulanica.world.workspace_models import WorkspaceModelRepository

from living_session_support import open_living_session
from model_fakes import chat_body
from personal_world_support import STRANGER_TOKEN
from spending_support import WorkspacePolicy, spending_client
from test_model_probes_postgres import ProbeTransport, _candidate
from test_site_society_of_things_postgres import (
    CREATURE,
    FARM,
    V7,
    _keep_creature,
    _place,
    _site,
    _step,
)
from test_society_made_world import made as made
from tests_support_api import scratch_database

pytestmark = pytest.mark.postgres


class Choosing(ProbeTransport):
    runtime = False

    def post_json(self, url, *, headers, payload, timeout):
        if not self.runtime:
            return super().post_json(url, headers=headers, payload=payload, timeout=timeout)
        self.requests.append({"url": url, "payload": dict(payload)})
        schema = (
            payload["response_format"]["json_schema"]["schema"]
            if "response_format" in payload
            else payload["tools"][0]["function"]["parameters"]
        )
        labels = schema["properties"]["action"]["enum"]
        label = next((s for s in labels if " m away" in s), labels[0])
        answer = {"action": label}
        if "line" in schema["properties"]:
            answer["line"] = None
        body = chat_body(json.dumps(answer), model=payload["model"])
        if "tools" in payload:
            body["choices"][0]["message"]["content"] = None
            body["choices"][0]["message"]["tool_calls"] = [
                {
                    "id": "fixture",
                    "type": "function",
                    "function": {"name": "act", "arguments": json.dumps(answer)},
                }
            ]
            body["choices"][0]["finish_reason"] = "tool_calls"
        return HttpResponse(200, json.dumps(body))


def test_verified_candidate_owner_choice_records_its_source_decision_application_and_exact_replay(
    made, tmp_path, spine_schema, monkeypatch
):
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: FARM)
    api = made
    entry, society, _records = _site(api, "farm", "fixture_farm", "small_farm")
    creature = _keep_creature(api, tmp_path)
    east, _height, south = entry["generated_site"]["arrival_mm"]
    _place(
        api, entry, CREATURE, {"source": "workspace", "sha256": creature.kind.sha256}, east, south
    )
    created = api.post(society, {"region_id": "region:generated", "profile": V7})
    assert created.status_code in (200, 201), created.text
    body = created.json()
    workspace = api.repository.workspace_id
    subject = next(p["id"] for p in body["state"]["inhabitants"] if p["came_by"] == "placed")
    base = f"/world/versions/{entry['authored_version_id']}"
    scope = f"?world_id={entry['world_id']}"
    models = base + "/society/models" + scope
    decision_root = base + "/society"
    witness = FileSpendingWitness(tmp_path / "candidate-spending")
    operator = SpendingOperator(scratch_database(spine_schema[1]), witness)
    stated = _candidate()
    transport = Choosing()
    until = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)
    authority = operator.issue(
        provider=stated.provider,
        ceiling_usd=Decimal("2"),
        max_calls=1000,
        valid_until=until,
        operator="fixture",
        reason="scripted integration",
    )
    operator.grant(
        authority,
        workspace,
        ceiling_usd=Decimal("2"),
        max_calls=1000,
        valid_until=until,
        operator="fixture",
        reason="scripted integration",
    )
    spending = DurableSpending(api.database, witness, holder="fixture-binding")
    client = spending_client(spending, transport)
    services = replace(
        api.client.app.state.services,
        model_client=client,
        spending=spending,
        admits_workspace_models=True,
        society_control_workspaces=(workspace,),
    )
    api.client.app.state.services = services
    added = api.post(
        "/models",
        {"provider": stated.provider, "model_id": stated.model_id, "request_id": str(uuid.uuid4())},
    )
    assert added.status_code == 200, added.text
    prepared = api.post(
        "/models/probes/prepare",
        {"provider": stated.provider, "model_id": stated.model_id, "request_id": str(uuid.uuid4())},
    )
    assert prepared.status_code == 200, prepared.text
    quote = prepared.json()
    probe_id = quote["probe_id"]
    api.client.app.state.services = replace(
        services, runs_model_probe_worker=True, model_probe_workspaces=(workspace,)
    )
    started = api.post(
        f"/models/probes/{probe_id}/start",
        {
            "request_id": str(uuid.uuid4()),
            "definition_sha256": quote["definition"]["document_sha256"],
            "ceiling_usd": quote["definition"]["operation_estimate"]["ceiling_usd"],
        },
    )
    assert started.status_code == 202, started.text
    worker = ModelProbeWorker(
        api.database,
        client=client,
        spending=spending,
        policy_for=WorkspacePolicy,
        workspaces=lambda: (workspace,),
    )
    assert worker.turn(workspace)
    offered = api.get(models)
    assert offered.status_code == 200, offered.text
    assert stated.model_id in {m["model_id"] for m in offered.json()["models"]}
    assert all(c["model"] is None for c in offered.json()["choices"])
    selected = api.post(
        models,
        {
            "idempotency_key": str(uuid.uuid4()),
            "people": [subject],
            "model": {"provider": stated.provider, "model_id": stated.model_id},
        },
    )
    assert selected.status_code == 200, selected.text
    open_living_session(
        services.database,
        services.society_runtime,
        workspace,
        entry["world_id"],
        uuid.UUID(entry["authored_version_id"]),
        api.actor,
    )
    transport.runtime = True
    host = services.decision_host()
    assert host
    for _ in range(60):
        claim = ControlClaim(
            workspace_id=workspace,
            world_id=entry["world_id"],
            society_id=uuid.UUID(body["society_id"]),
            version_id=uuid.UUID(entry["authored_version_id"]),
            token=uuid.uuid4(),
            revision=1,
            actor=api.actor,
        )
        assert host.before_minute(claim, time.monotonic() + LEASE_SECONDS)
        read = api.get(decision_root + "/models" + scope)
        if any(d["status"] == "accepted" for d in read.json()["latest"]):
            break
        body = _step(api, entry, body)
    else:
        pytest.fail("candidate reached no accepted decision for the actual being")
    body = _step(api, entry, body)
    events = api.get(decision_root + "/events" + scope).json()["events"]
    applied = next(
        e["document"]
        for e in events
        if e["event_kind"] == "decision_applied"
        and e["document"]["subject_id"] == subject
        and e["document"]["disposition"] == "applied"
    )
    receipt = api.get(decision_root + "/decisions/" + applied["request_id"] + scope)
    assert receipt.status_code == 200, receipt.text
    receipt = receipt.json()
    digest = receipt["request"]["provider_config"]["manifest_sha256"]
    source = api.get("/models/bindings/" + digest)
    assert source.status_code == 200, source.text
    assert source.json()["sources"][0]["probe_id"] == probe_id
    assert source.json()["manifest"]["models"][stated.model_id]["answering"]
    assert receipt["decision"]["provider"]["served_model_id"] == stated.model_id
    foreign = api.client.get(
        "/models/bindings/" + digest, headers={"Authorization": "Bearer " + STRANGER_TOKEN}
    )
    assert foreign.status_code == 404, foreign.text
    calls = transport.call_count
    replay = api.get(decision_root + "/replay" + scope)
    assert replay.status_code == 200, replay.text
    assert (
        replay.json()["replay_verified"] and replay.json()["state_sha256"] == body["state_sha256"]
    )
    assert transport.call_count == calls
    evidence_path = os.environ.get("EXULANICA_BINDING_EVIDENCE_PATH")
    if evidence_path:
        Path(evidence_path).write_text(
            json.dumps(
                {
                    "evidence_kind": "scripted_provider_real_client_private_postgres",
                    "live_provider_verified": False,
                    "actual_provider_spending": False,
                    "world": {
                        "world_id": entry["world_id"],
                        "version_id": entry["authored_version_id"],
                        "engine": V7,
                        "inhabitant_id": subject,
                        "kind_sha256": creature.kind.sha256,
                    },
                    "probe": api.get(f"/models/probes/{probe_id}").json(),
                    "owner_choice": selected.json(),
                    "binding_source": source.json(),
                    "decision": receipt,
                    "applied": applied,
                    "state_sha256": body["state_sha256"],
                    "replay": replay.json(),
                    "replay_reasked": False,
                },
                indent=2,
            )
            + "\n"
        )
    removed = api.post(
        "/models/remove",
        {"provider": stated.provider, "model_id": stated.model_id, "request_id": str(uuid.uuid4())},
    )
    assert removed.status_code == 200, removed.text
    assert api.get("/models/bindings/" + digest).json() == source.json()
    read = api.get(models).json()
    assert (
        next(c for c in read["choices"] if c["subject_id"] == subject)["refusal"]
        == "model_no_longer_offered"
    )
    with api.database.session(workspace) as connection:
        assert (
            WorkspaceModelRepository(connection, workspace)
            .state(stated.provider, stated.model_id)
            .removed
        )
