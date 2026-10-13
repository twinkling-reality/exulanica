"""Durable candidate probes, with the actual client and spending authority, no network."""

from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal

import psycopg
import pytest
from exulanica.models import provider_catalog
from exulanica.models.manifest import load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.world.model_admission import add_model, prepare_probe, start_probe
from exulanica.world.model_probe_contract import replay_outcome
from exulanica.world.model_probe_worker import ModelProbeWorker
from exulanica.world.model_probes import ModelProbeRefused, ModelProbeRepository
from exulanica.world.workspace_lock import lock_workspace
from exulanica.world.workspace_models import WorkspaceModelRepository
from psycopg.types.json import Jsonb

from model_fakes import FakeTransport, chat_body
from spending_support import WorkspacePolicy, spending_client
from spending_support import bench as bench
from test_model_probe_contract import successful_receipts

pytestmark = pytest.mark.postgres


def _candidate():
    manifest = load_manifest()
    return next(
        model
        for model in provider_catalog.provider_models().values()
        if model.model_id not in manifest.models
        and model.provider in manifest.providers
        and provider_catalog.licence_class(model.provider, model.model_id)
        == provider_catalog.ACCEPTED
        and provider_catalog.decision_capable(model, ("text",))
    )


class ProbeTransport(FakeTransport):
    def __init__(self, *, fail=False):
        super().__init__()
        self.fail = fail

    def get_json(self, url, *, headers, timeout):
        self.gets.append(url)
        return HttpResponse(
            status_code=200,
            text=json.dumps(
                {
                    "data": [
                        {
                            "id": spec.model_id,
                            "context_length": spec.context_window_tokens,
                            "pricing": {
                                "prompt": str(spec.input_usd_per_mtok),
                                "completion": str(spec.output_usd_per_mtok),
                            },
                        }
                        for spec in load_manifest().models.values()
                    ]
                    + [
                        {
                            "id": _candidate().model_id,
                            "context_length": 32000,
                            "pricing": {"prompt": "0.1", "completion": "0.3"},
                        }
                    ]
                }
            ),
        )

    def post_json(self, url, *, headers, payload, timeout):
        self.requests.append({"url": url, "payload": dict(payload)})
        if self.fail:
            return HttpResponse(status_code=500, text='{"error":{"message":"unavailable"}}')
        schema = (
            payload["response_format"]["json_schema"]["schema"]
            if "response_format" in payload
            else payload["tools"][0]["function"]["parameters"]
        )
        answer = {"action": schema["properties"]["action"]["enum"][0]}
        if "line" in schema["properties"]:
            answer["line"] = "Let us see what lies ahead."
        body = chat_body(json.dumps(answer), model=payload["model"])
        if "tools" in payload:
            body["choices"][0]["message"]["content"] = None
            body["choices"][0]["message"]["tool_calls"] = [
                {
                    "id": "synthetic",
                    "type": "function",
                    "function": {"name": "act", "arguments": json.dumps(answer)},
                }
            ]
            body["choices"][0]["finish_reason"] = "tool_calls"
        return HttpResponse(status_code=200, text=json.dumps(body))


def _prepared(bench, workspace=None, transport=None):
    workspace = workspace or uuid.uuid4()
    actor = uuid.uuid4()
    spec = _candidate()
    transport = transport or ProbeTransport()
    spending = bench.durable()
    client = spending_client(spending, transport, max_attempts=3)
    with bench.runtime.session(workspace) as connection:
        add_model(connection, workspace, actor, spec.provider, spec.model_id, uuid.uuid4())
        found = prepare_probe(
            connection, workspace, actor, spec.provider, spec.model_id, uuid.uuid4(), client
        )
    return workspace, actor, found, client, spending, transport


def _started(bench, *, transport=None):
    workspace, actor, found, client, spending, transport = _prepared(bench, transport=transport)
    ceiling = Decimal(found["definition"]["operation_estimate"]["ceiling_usd"])
    authority = bench.issue(ceiling=ceiling * 2)
    bench.grant(authority, workspace, ceiling=ceiling)
    with bench.runtime.session(workspace) as connection:
        started = start_probe(
            connection,
            workspace,
            actor,
            uuid.UUID(found["probe_id"]),
            uuid.uuid4(),
            found["definition"]["document_sha256"],
            ceiling,
            spending,
            True,
        )
    worker = ModelProbeWorker(
        bench.runtime,
        client=client,
        spending=spending,
        policy_for=WorkspacePolicy,
        workspaces=lambda: (workspace,),
    )
    return workspace, actor, started, worker, transport


def test_preparation_is_inspectable_and_cannot_dispatch_without_a_bounded_start(bench):
    workspace, _actor, found, _client, _spending, transport = _prepared(bench)
    assert found["state"] == "prepared" and not found["execution_admitted"]
    assert transport.gets and transport.call_count == 0
    with bench.runtime.session(workspace) as connection:
        assert ModelProbeRepository(connection, workspace).claim("worker") is None
    with (
        bench.runtime.session(uuid.uuid4()) as connection,
        pytest.raises(ModelProbeRefused, match="not_found"),
    ):
        ModelProbeRepository(connection, uuid.uuid4()).get(uuid.UUID(found["probe_id"]))
    assert bench.query("select count(*) as n from spending_reservation")[0]["n"] == 0


def test_worker_records_actual_served_identity_and_replays_without_asking_again(bench):
    workspace, _actor, found, worker, transport = _started(bench)
    assert worker.turn(workspace)
    with bench.runtime.session(workspace) as connection:
        finished = ModelProbeRepository(connection, workspace).view(uuid.UUID(found["probe_id"]))
        model = WorkspaceModelRepository(connection, workspace).state(
            found["definition"]["provider"], found["definition"]["model_id"]
        )
    assert finished["state"] == "done", finished["outcome"]
    assert finished["outcome"]["verified"] and model.verified
    assert len(finished["receipts"]) == transport.call_count == 44
    replayed = replay_outcome(finished["definition"], finished["receipts"])
    assert (
        replayed["verified"]
        and replayed["receipt_sha256s"] == finished["outcome"]["receipt_sha256s"]
    )
    assert not worker.turn(workspace)
    assert transport.call_count == 44
    assert not finished["execution_admitted"]


def test_provider_failure_records_no_verdict_and_the_probe_does_not_retry_paid_attempts(bench):
    workspace, _actor, found, worker, transport = _started(
        bench, transport=ProbeTransport(fail=True)
    )
    assert worker.turn(workspace)
    with bench.runtime.session(workspace) as connection:
        finished = ModelProbeRepository(connection, workspace).view(uuid.UUID(found["probe_id"]))
    assert finished["state"] == "failed"
    assert finished["outcome"]["code"] == "not_finished"
    assert not finished["outcome"]["verified"]
    assert transport.call_count == 1
    assert finished["receipts"][0]["calls"][0]["served_model"] is None


def test_old_lease_and_readding_cannot_publish_a_current_verdict(bench):
    workspace, actor, found, _worker, _transport = _started(bench)
    probe_id = uuid.UUID(found["probe_id"])
    with bench.runtime.session(workspace) as connection:
        repository = ModelProbeRepository(connection, workspace)
        claimed = repository.claim("first")
        assert claimed is not None
        wrong = replace(claimed, claim_token=uuid.uuid4())
        assert not repository.append(wrong, successful_receipts(found["definition"])[0])
        assert not repository.finish(wrong)
        WorkspaceModelRepository(connection, workspace).record(
            found["definition"]["provider"],
            found["definition"]["model_id"],
            request_id=uuid.uuid4(),
            kind="added",
            facts={"new": True},
            recorded_by=actor,
        )
        assert repository.finish(claimed)
        assert repository.view(probe_id)["outcome"]["code"] == "stale"
        assert (
            not WorkspaceModelRepository(connection, workspace)
            .state(found["definition"]["provider"], found["definition"]["model_id"])
            .verified
        )


def test_probe_tables_are_immutable_and_erased_with_their_workspace(bench):
    workspace, actor, found, _worker, _transport = _started(bench)
    other, _, other_found, _, _, _ = _prepared(bench)
    with bench.runtime.session(workspace) as connection:
        repository = ModelProbeRepository(connection, workspace)
        claimed = repository.claim("worker")
        assert repository.append(claimed, successful_receipts(found["definition"])[0])
        assert repository.cancel(uuid.UUID(found["probe_id"]))
        for table in (
            "model_probe",
            "model_probe_start",
            "model_probe_receipt",
            "model_probe_outcome",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                connection.execute(f"update {table} set workspace_id=workspace_id")
        connection.execute(
            "insert into tombstone(workspace_id,scope,requested_by,reason) "
            "values(%s,'workspace',%s,'the workspace is erased')",
            (workspace, actor),
        )
    for table in ("model_probe", "model_probe_start", "model_probe_receipt", "model_probe_outcome"):
        assert (
            bench.query(f"select count(*) as n from {table} where workspace_id=%s", workspace)[0][
                "n"
            ]
            == 0
        )
    with bench.runtime.session(other) as connection:
        assert (
            ModelProbeRepository(connection, other).view(uuid.UUID(other_found["probe_id"]))[
                "state"
            ]
            == "prepared"
        )


def test_the_database_insertion_boundary_serializes_with_workspace_erasure(bench):
    workspace, actor, found, _worker, _transport = _started(bench)
    receipt = successful_receipts(found["definition"])[0]
    entered = threading.Event()
    pid = []

    def insert_after_erase():
        with bench.runtime.session(workspace) as connection:
            pid.append(connection.info.backend_pid)
            entered.set()
            with pytest.raises(psycopg.errors.CheckViolation, match="erased workspace"):
                connection.execute(
                    "insert into model_probe_receipt("
                    "workspace_id,probe_id,case_seq,document,document_sha256) "
                    "values(%s,%s,1,%s,%s)",
                    (
                        workspace,
                        uuid.UUID(found["probe_id"]),
                        Jsonb(receipt),
                        receipt["document_sha256"],
                    ),
                )

    with ThreadPoolExecutor(max_workers=1) as executor:
        with bench.admin.session(workspace) as connection, connection.transaction():
            lock_workspace(connection, workspace)
            future = executor.submit(insert_after_erase)
            assert entered.wait(5)
            for _ in range(100):
                rows = bench.query("select wait_event from pg_stat_activity where pid=%s", pid[0])
                if rows and rows[0]["wait_event"] == "advisory":
                    break
                time.sleep(0.02)
            else:
                pytest.fail("receipt insert never waited on the workspace lock")
            connection.execute(
                "insert into tombstone(workspace_id,scope,requested_by,reason) "
                "values(%s,'workspace',%s,'the workspace is erased')",
                (workspace, actor),
            )
        future.result(timeout=10)
    assert (
        bench.query(
            "select count(*) as n from model_probe_receipt where workspace_id=%s", workspace
        )[0]["n"]
        == 0
    )


def test_a_crash_after_dispatch_never_pays_to_repeat_the_missing_receipt(bench, monkeypatch):
    workspace, _actor, found, worker, transport = _started(bench)

    class LostProcess(BaseException):
        pass

    original = ModelProbeRepository.append

    def crash(*args, **kwargs):
        raise LostProcess()

    monkeypatch.setattr(ModelProbeRepository, "append", crash)
    with pytest.raises(LostProcess):
        worker.turn(workspace)
    assert transport.call_count == 1
    assert len(bench.reservations(workspace)) == 1
    monkeypatch.setattr(ModelProbeRepository, "append", original)
    with bench.runtime.session(workspace) as connection:
        connection.execute(
            "update job set lease_expires_at=now()-interval '1 second' "
            "where workspace_id=%s and kind='model_probe'",
            (workspace,),
        )
    assert worker.turn(workspace)
    with bench.runtime.session(workspace) as connection:
        finished = ModelProbeRepository(connection, workspace).view(uuid.UUID(found["probe_id"]))
    assert transport.call_count == 1 and not finished["outcome"]["verified"]
    assert finished["outcome"]["code"] == "not_finished"


def test_a_terminal_bound_close_survives_a_host_crash_and_is_retried(bench):
    workspace, _actor, found, worker, _transport = _started(bench)
    with bench.runtime.session(workspace) as connection:
        repository = ModelProbeRepository(connection, workspace)
        repository.cancel(uuid.UUID(found["probe_id"]))
        assert repository.bound_close_due()
    assert worker.close_due(workspace)
    assert not worker.close_due(workspace)


def test_exhausted_leases_and_changed_role_inputs_end_without_an_asserted_verdict(
    bench, monkeypatch
):
    workspace, _actor, found, _worker, _transport = _started(bench)
    with bench.runtime.session(workspace) as connection:
        repository = ModelProbeRepository(connection, workspace)
        assert repository.claim("first") is not None
        connection.execute(
            "update job set attempts=2,lease_expires_at=now()-interval '1 second' "
            "where workspace_id=%s and kind='model_probe'",
            (workspace,),
        )

        def unavailable(*args, **kwargs):
            raise ValueError("model_probe_contract_changed")

        monkeypatch.setattr("exulanica.world.model_probes.replay_outcome", unavailable)
        assert repository.sweep() == 1
        end = repository.view(uuid.UUID(found["probe_id"]))["outcome"]
        assert not end["finished"] and not end["verified"]
        assert end["reason"] == "model_probe_replay_unavailable"
