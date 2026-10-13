"""Private PostgreSQL and scripted transport, with no actual provider or paid calls."""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import psycopg
import pytest
from exulanica.api.services import Services
from exulanica.models.errors import ProviderRefused
from exulanica.models.manifest import AnsweringMechanism, load_manifest
from exulanica.world.decision_roles import decision_roles
from exulanica.world.model_probe_contract import case_book
from exulanica.world.workspace_lock import lock_workspace
from exulanica.world.workspace_model_bindings import BindingSnapshotRepository, proven_bindings
from exulanica.world.workspace_models import REMOVED, WorkspaceModelRepository
from psycopg.types.json import Jsonb

from spending_support import WorkspacePolicy
from spending_support import bench as bench
from test_model_probes_postgres import _candidate, _started

pytestmark = pytest.mark.postgres


def running(bench):
    workspace, actor, found, worker, transport = _started(bench)
    assert worker.turn(workspace)
    services = Services(
        database=bench.runtime,
        readonly_database=bench.runtime,
        store=None,
        tokens=None,
        executor_shares_the_write_role=True,
        model_client=worker.client,
        spending=worker.spending,
        admits_workspace_models=True,
    )
    engine = found["definition"]["engine"]
    return workspace, actor, engine, services, transport


def test_bindings_need_full_current_proof_fresh_rates_scope_and_durable_spending(bench):
    workspace, actor, engine, services, transport = running(bench)
    model = _candidate().model_id
    with bench.runtime.session(workspace) as connection:
        bindings = proven_bindings(connection, workspace, engine, load_manifest())
        assert [b.spec.model_id for b in bindings] == [model]
        assert not proven_bindings(connection, uuid.uuid4(), engine, load_manifest())
        assert model in services.workspace_choice_manifest(connection, workspace, engine).models
        assert (
            model
            not in replace(services, admits_workspace_models=False)
            .workspace_choice_manifest(connection, workspace, engine)
            .models
        )
        assert (
            model
            not in services.workspace_choice_manifest(
                connection, workspace, "exulanica-society/v6"
            ).models
        )
    source = services.workspace_execution_source(workspace, engine, frozenset({model}))
    assert source
    client, _manifest, digest = source
    with bench.runtime.session(workspace) as connection:
        document = BindingSnapshotRepository(connection, workspace).read(digest)
        assert document["manifest"]["models"][model]["input_usd_per_mtok"] == "0.1"
        assert document["manifest"]["models"][model]["answering"]
    with bench.runtime.session(uuid.uuid4()) as connection:
        assert BindingSnapshotRepository(connection, uuid.uuid4()).read(digest) is None
    role = decision_roles().role(bindings[0].role)
    book, _ = case_book()
    context = book["cases"][0]
    scoped = client.with_policy(WorkspacePolicy(workspace))
    with pytest.raises(ProviderRefused, match="did not probe"):
        scoped.choose(
            role.chosen,
            model,
            role.adapter.messages(role, context, AnsweringMechanism.JSON_SCHEMA),
            role.choice(context),
            mechanism=AnsweringMechanism.JSON_SCHEMA,
            prompt_version="another",
            timeout=1,
            max_tokens=2048,
        )
    calls = transport.call_count
    with bench.runtime.session(workspace) as connection:
        WorkspaceModelRepository(connection, workspace).record(
            _candidate().provider,
            model,
            request_id=uuid.uuid4(),
            kind=REMOVED,
            facts={},
            recorded_by=actor,
        )
        assert BindingSnapshotRepository(connection, workspace).read(digest) == document
    with pytest.raises(ProviderRefused, match="currently executable"):
        scoped.choose(
            role.chosen,
            model,
            role.adapter.messages(role, context, AnsweringMechanism.JSON_SCHEMA),
            role.choice(context),
            mechanism=AnsweringMechanism.JSON_SCHEMA,
            prompt_version=bindings[0].prompt_version,
            timeout=1,
            max_tokens=2048,
        )
    assert transport.call_count == calls
    assert services.workspace_execution_source(workspace, engine, frozenset({model})) is None
    assert not replace(services, spending=None).workspace_execution_source(
        workspace, engine, frozenset({model})
    )


def test_incomplete_restore_refuses_execution_and_snapshot_append_but_history_stays(bench):
    workspace, _actor, engine, services, transport = running(bench)
    model = _candidate().model_id
    source = services.workspace_execution_source(workspace, engine, frozenset({model}))
    assert source
    _client, _manifest, digest = source
    with bench.admin.unscoped() as connection:
        connection.execute(
            "insert into restore_control(checkpoint_id,checkpoint_sha256,state) "
            "values(%s,%s,'sealed')",
            (uuid.uuid4(), "a" * 64),
        )
    try:
        gets = len(transport.gets)
        assert services.workspace_execution_source(workspace, engine, frozenset({model})) is None
        assert len(transport.gets) == gets
        with bench.runtime.session(workspace) as connection:
            repository = BindingSnapshotRepository(connection, workspace)
            document = repository.read(digest)
            assert document
            with pytest.raises(ValueError, match="restore_not_complete"):
                repository.record(document)
    finally:
        with bench.admin.unscoped() as connection:
            connection.execute("delete from restore_control")


def test_snapshot_is_immutable_and_direct_insert_waits_for_workspace_erasure(bench):
    workspace, actor, engine, services, _transport = running(bench)
    source = services.workspace_execution_source(
        workspace, engine, frozenset({_candidate().model_id})
    )
    assert source
    digest = source[2]
    with bench.runtime.session(workspace) as connection:
        document = BindingSnapshotRepository(connection, workspace).read(digest)
        for query in [
            "update workspace_model_binding_snapshot set document=document",
            "delete from workspace_model_binding_snapshot",
        ]:
            with pytest.raises(psycopg.Error):
                connection.execute(query)
    entered = threading.Event()
    pid = []

    def insert_after_erase():
        with bench.runtime.session(workspace) as connection:
            pid.append(connection.info.backend_pid)
            entered.set()
            with pytest.raises(psycopg.errors.CheckViolation, match="erased workspace"):
                connection.execute(
                    "insert into workspace_model_binding_snapshot"
                    "(workspace_id,binding_sha256,document) values(%s,%s,%s) "
                    "on conflict do nothing",
                    (workspace, digest, Jsonb(document)),
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
                pytest.fail("binding insert did not wait on880024")
            connection.execute(
                "insert into tombstone(workspace_id,scope,requested_by,reason) "
                "values(%s,'workspace',%s,'workspace erased')",
                (workspace, actor),
            )
        future.result(timeout=10)
    assert (
        bench.query(
            "select count(*) as n from workspace_model_binding_snapshot where workspace_id=%s",
            workspace,
        )[0]["n"]
        == 0
    )


def test_fresh_price_read_failure_and_wrong_served_identity_do_not_answer(bench, monkeypatch):
    import json

    from exulanica.models.transport import HttpResponse

    workspace, _actor, engine, services, transport = running(bench)
    model = _candidate().model_id
    with bench.runtime.session(workspace) as connection:
        binding = proven_bindings(connection, workspace, engine, load_manifest())[0]
    original = services.model_client.provider_prices
    monkeypatch.setattr(services.model_client, "provider_prices", lambda provider: {})
    assert services.workspace_execution_source(workspace, engine, frozenset({model})) is None
    monkeypatch.setattr(services.model_client, "provider_prices", original)
    source = services.workspace_execution_source(workspace, engine, frozenset({model}))
    assert source
    client = source[0].with_policy(WorkspacePolicy(workspace))
    original_post = transport.post_json

    def mismatched(*args, **kwargs):
        response = original_post(*args, **kwargs)
        body = json.loads(response.text)
        body["model"] = "another/variant"
        return HttpResponse(200, json.dumps(body))

    monkeypatch.setattr(transport, "post_json", mismatched)
    role = decision_roles().role(binding.role)
    book, _ = case_book()
    context = book["cases"][0]
    calls = transport.call_count
    with pytest.raises(ProviderRefused, match="did not identify"):
        client.choose(
            role.chosen,
            model,
            role.adapter.messages(role, context, AnsweringMechanism.JSON_SCHEMA),
            role.choice(context),
            mechanism=AnsweringMechanism.JSON_SCHEMA,
            prompt_version=binding.prompt_version,
            timeout=1,
            max_tokens=2048,
        )
    assert transport.call_count == calls + 1
