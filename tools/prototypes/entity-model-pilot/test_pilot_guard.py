"""Offline private guard checks; no real services, database, or provider transport."""

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pilot_guard as pg
import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import TransportError
from exulanica.models.manifest import load_manifest


@pytest.fixture
def case(tmp_path):
    manifest = load_manifest()
    model = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    identity = pg.Identity(
        uuid4(),
        "world:private",
        uuid4(),
        uuid4(),
        "duck",
        manifest.spec(model).provider,
        model,
        "a" * 64,
        "b" * 64,
        1,
    )
    root = tmp_path / "clone"
    binding = pg.TargetBinding(
        root,
        root / "data",
        root / "data",
        root / "store",
        root / "store",
        (tmp_path / "primary",),
        "postgresql://localhost:20030/test",
        "http://localhost:20031",
        "http://localhost:20032",
        "c" * 64,
        pg.code_schema_version(),
        "durable",
        uuid4(),
        Decimal(".25"),
        100,
        tmp_path / "witness",
        tmp_path / "witness",
    )
    budget = BudgetGuard(ceiling_usd=Decimal(".25"), max_calls=100)
    baseline = pg.RequestRow(uuid4(), "duck", "accepted", identity.provider, model)
    state = SimpleNamespace(now=0.0, rows=[baseline], receipts=[])
    audit = pg.AttemptAudit(identity, budget, state.receipts.append)
    guard = pg.PilotGuard(
        identity=identity,
        binding=binding,
        read=lambda: pg.Snapshot(
            identity, 3, "d" * 64, tuple(state.rows), ("duck",), (identity.version_id,)
        ),
        audit=audit,
        sink=state.receipts.append,
        monotonic=lambda: state.now,
    )
    state.guard, state.binding, state.identity, state.budget = guard, binding, identity, budget
    return state


@pytest.mark.parametrize("relation", ["same", "child", "ancestor", "symlink"])
def test_primary_path_overlap_including_symlink_is_refused(case, tmp_path, relation):
    primary = tmp_path / "primary"
    primary.mkdir()
    target = {"same": primary, "child": primary / "nested", "ancestor": tmp_path}.get(relation)
    if relation == "symlink":
        target = tmp_path / "alias"
        target.symlink_to(primary, target_is_directory=True)
    with pytest.raises(pg.PilotStop, match="primary_path_overlap"):
        replace(case.binding, recorded_data=target, configured_data=target).validate()


@pytest.mark.parametrize(
    "field,port", [("database_url", 19950), ("api_url", 19951), ("app_url", 19952)]
)
def test_primary_endpoint_cannot_be_bound(case, field, port):
    scheme = "postgresql" if field == "database_url" else "http"
    with pytest.raises(pg.PilotStop, match="target_endpoint_not_isolated"):
        replace(case.binding, **{field: f"{scheme}://localhost:{port}/target"}).validate()


def test_target_migrated_below_the_code_is_refused(case):
    behind = pg.code_schema_version() - 1
    with pytest.raises(pg.PilotStop, match="source_preflight_missing"):
        replace(case.binding, schema_version=behind).validate()


def test_baseline_is_not_counted_and_pending_prevents_next_host(case):
    case.guard.start()
    case.guard.check()
    assert case.guard.summary()["finalized"] == 0
    case.rows.append(
        pg.RequestRow(uuid4(), "duck", None, case.identity.provider, case.identity.model_id)
    )
    case.guard.check(before_new_ask=False)
    with pytest.raises(pg.PilotStop, match="unanswered_request"):
        case.guard.check()
    case.rows[-1] = replace(case.rows[-1], status="rejected")
    case.guard.check()
    assert case.guard.summary()["finalized"] == 1
    assert case.guard.summary()["accepted"] == 0


def test_dispatch_clamps_timeout_and_never_sends_at_deadline(case):
    sent = []
    transport = SimpleNamespace(post_json=lambda *args, **kwargs: sent.append(kwargs) or "ok")
    fence = pg.DispatchFence(transport, case.guard, url="https://offline.invalid/chat/completions")
    case.guard.start()
    case.now = 599
    assert (
        fence.post_json(
            fence.url, headers={}, payload={"model": case.identity.model_id}, timeout=20
        )
        == "ok"
    )
    assert sent[0]["timeout"] == 1
    case.now = 600
    with pytest.raises(TransportError) as stopped:
        fence.post_json(
            fence.url, headers={}, payload={"model": case.identity.model_id}, timeout=20
        )
    assert not stopped.value.retryable and stopped.value.reached_provider is False
    assert len(sent) == 1


def test_client_copy_keeps_original_transport_and_shared_budget(case):
    transport = SimpleNamespace(post_json=lambda *args, **kwargs: pytest.fail("no call expected"))
    client = ModelClient(api_key="offline-placeholder", transport=transport, budget=case.budget)
    observed = pg.guarded_client(client, case.guard)
    assert observed is not client and observed._chain is not client._chain
    assert observed.budget is client.budget is case.budget
    assert client._chain._transport is transport
    assert isinstance(observed._chain._transport, pg.DispatchFence)
    assert observed._chain.spending is client._chain.spending
    # DecisionHost's later per-request observer copy must retain the dispatch fence.
    nested = observed.with_attempts(lambda _: None)
    assert nested.budget is case.budget
    assert nested._chain._transport is observed._chain._transport


def test_transaction_local_pause_cannot_claim_committed_cleanup(case):
    calls = []
    repo = SimpleNamespace(
        workspace_id=case.identity.workspace_id,
        world_id=case.identity.world_id,
        read=lambda _: {
            "society_id": str(case.identity.society_id),
            "mode": "paused",
            "revision": 4,
            "lease_expires_at": None,
        },
        configure=lambda *args, **kwargs: calls.append(kwargs),
    )
    result = pg.pause_with_fresh_revision(repo, case.identity, uuid4())
    assert calls[0]["base_revision"] == 4 and calls[0]["mode"] == "paused"
    assert result["commit_verified"] is False and "mode" not in result


def test_readiness_dispatch_is_explicitly_refused(case):
    fence = pg.DispatchFence(object(), case.guard, url="https://offline.invalid/chat/completions")
    case.guard.start()
    with pytest.raises(TransportError) as stopped:
        fence.get_json("https://offline.invalid/models", headers={}, timeout=2)
    assert stopped.value.reached_provider is False and not stopped.value.retryable
    assert case.guard.dispatch_failure == "unexpected_readiness_dispatch"


def test_mixed_primary_readonly_services_refuse_before_factory(case):
    services = SimpleNamespace(
        spending_mode="durable",
        spending=object(),
        playback_player="none",
        runs_society_control_worker=False,
        society_control_workspaces=(case.identity.workspace_id,),
        model_client=object(),
        readonly_database=SimpleNamespace(url="postgresql://localhost:19950/main"),
        build_society_control_worker=lambda: pytest.fail("factory must not run"),
    )
    with pytest.raises(pg.PilotStop, match="readonly_target_differs"):
        pg.observed_worker(services, case.guard)
