"""Independent offline execution-boundary checks with the actual playback worker."""

from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pilot_guard as pg
import pytest
from exulanica.api.society_control_worker import SocietyControlWorker
from exulanica.models.budget import BudgetGuard
from exulanica.models.usage import CallOutcome, CallUsage, CostBasis
from exulanica.world.society_controls import ControlClaim


@pytest.fixture
def rig(tmp_path, monkeypatch):
    identity = pg.Identity(
        uuid4(),
        "world:isolated",
        uuid4(),
        uuid4(),
        "duck",
        "nebius_token_factory",
        "admitted-nano",
        "a" * 64,
        "b" * 64,
        1,
    )
    root = tmp_path / "clone"
    binding = pg.TargetBinding(
        root,
        root / "pg",
        root / "pg",
        root / "store",
        root / "store",
        (tmp_path / "primary",),
        "postgresql://localhost:20030/pilot",
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
    value = SimpleNamespace(
        now=0.0,
        host_calls=0,
        told=0,
        executed=[],
        cleanup=[],
        rows=[],
        tick=3,
        read_error=False,
        read_advance=0.0,
        erasure="clear",
        host_error=False,
        host_false=False,
        host_advance=0.0,
        sink_error=False,
        finalize=True,
        final_status="accepted",
        cleanup_failure=None,
        observer_failure=False,
    )
    value.claim = ControlClaim(
        identity.workspace_id,
        identity.world_id,
        identity.society_id,
        identity.version_id,
        uuid4(),
        1,
        uuid4(),
    )

    def sink(row):
        if value.sink_error:
            raise OSError("private error must not be rendered")

    audit = pg.AttemptAudit(identity, budget, sink)

    def read():
        if value.read_error:
            raise RuntimeError("private read error")
        value.now += value.read_advance
        return pg.Snapshot(
            identity,
            value.tick,
            "d" * 64,
            tuple(value.rows),
            (identity.subject_id,),
            (identity.version_id,),
        )

    guard = pg.PilotGuard(
        identity=identity,
        binding=binding,
        read=read,
        audit=audit,
        sink=sink,
        monotonic=lambda: value.now,
    )

    @contextmanager
    def session(_workspace):
        yield object()

    def claim(*args, **kwargs):
        return value.claim

    monkeypatch.setattr(
        "exulanica.api.society_control_worker.SocietyControlRepository.claim_in_workspace", claim
    )
    # No living session is open in this world, and the worker's reaper finds nothing to close: the
    # guard's checks are what these tests are about, not a session's limits.
    monkeypatch.setattr(
        "exulanica.api.society_control_worker.open_session_receipt", lambda *args: None
    )

    def host(_claim, lease_end):
        value.host_calls += 1
        if value.host_error:
            raise ValueError("private host error")
        value.now += value.host_advance
        if value.observer_failure:
            value.sink_error = True
            usage = CallUsage(
                "being", identity.model_id, identity.provider, 1, 1, 0, 0, Decimal(".000001")
            )
            budget.record(usage)
            audit.observe(usage)
            value.sink_error = False
        if value.finalize:
            value.rows.append(
                pg.RequestRow(
                    uuid4(),
                    identity.subject_id,
                    value.final_status,
                    identity.provider,
                    identity.model_id,
                )
            )
        return not value.host_false

    worker = SocietyControlWorker(
        SimpleNamespace(session=session, url=binding.database_url),
        runtime=object(),
        workspaces=(identity.workspace_id,),
        before_minute=host,
    )

    def tell(*args):
        value.told += 1
        return value.erasure

    def execute(claim, *, max_ticks, untold):
        value.executed.append((claim.world_id, max_ticks, untold))
        value.tick += max_ticks if max_ticks is not None else 3
        return {"status": "advanced"}

    worker._tell_of_erased_kinds = tell
    worker.reap = lambda workspace: 0
    worker._repository = lambda *args, **kwargs: SimpleNamespace(execute=execute)

    def cleanup(name, result):
        value.cleanup.append(name)
        if value.cleanup_failure == name:
            raise RuntimeError("private cleanup detail")
        return result

    def run():
        return pg.run_guarded(
            worker,
            guard,
            pause=lambda: cleanup("pause", {"mode": "paused", "lease_expires_at": None}),
            revoke=lambda: cleanup(
                "revoke",
                {
                    "revoked": True,
                    "authority_id": str(binding.authority_id),
                    "workspace_id": str(identity.workspace_id),
                },
            ),
            close=lambda: cleanup("close", None),
            sleep=lambda _: None,
        )

    value.identity, value.binding, value.budget = identity, binding, budget
    value.audit, value.guard, value.worker, value.run = audit, guard, worker, run
    return value


def test_no_eleventh_finalized_request_even_rejected_and_host_false(rig):
    rig.host_false = True
    rig.final_status = "rejected"
    result = rig.run()
    assert result["reason"] == "decision_limit_reached"
    assert result["finalized"] == 10 and result["accepted"] == 0
    assert rig.host_calls == 10 and len(rig.executed) == 10
    assert all(max_ticks == 1 and not untold for _, max_ticks, untold in rig.executed)
    assert rig.cleanup == ["pause", "revoke", "close"]
    assert result["safe_stopped"]


@pytest.mark.parametrize("erasure", ["clear", "told", "untold"])
def test_wrong_world_claim_never_told_asked_or_executed(rig, erasure):
    rig.claim = replace(rig.claim, world_id="world:unrelated")
    rig.erasure = erasure
    result = rig.run()
    assert result["reason"] == "unexpected_claim"
    assert rig.told == rig.host_calls == 0 and not rig.executed


@pytest.mark.parametrize("erasure", ["told", "leaving", "untold"])
def test_nonclear_erasure_cannot_bypass_guard_with_routine_minute(rig, erasure):
    rig.erasure = erasure
    result = rig.run()
    assert result["reason"] == "erasure_not_clear"
    assert rig.told == 1 and rig.host_calls == 0 and not rig.executed


def test_host_exception_never_falls_through_to_production_routine(rig):
    rig.host_error = True
    # Make a buggy routine fallback finite; an execute would move the clock to deadline.
    repository = rig.worker._repository

    def marked_repository(*args, **kwargs):
        actual = repository(*args, **kwargs)

        def execute(*args, **kwargs):
            rig.now = 600
            return actual.execute(*args, **kwargs)

        return SimpleNamespace(execute=execute)

    rig.worker._repository = marked_repository
    result = rig.run()
    assert not rig.executed
    assert rig.host_calls == 1
    assert result["reason"] != "decision_limit_reached"
    assert rig.cleanup == ["pause", "revoke", "close"]


def test_state_reader_exception_escapes_worker_fallback(rig):
    original_tell = rig.worker._tell_of_erased_kinds

    def tell(*args):
        answer = original_tell(*args)
        rig.read_error = True
        return answer

    rig.worker._tell_of_erased_kinds = tell
    result = rig.run()
    assert result["reason"] == "state_read_failed"
    assert rig.told == 1 and rig.host_calls == 0 and not rig.executed


def test_post_host_deadline_does_not_execute_completed_decision(rig):
    rig.host_advance = 600
    result = rig.run()
    assert result["reason"] == "wall_deadline"
    assert len(rig.rows) == 1 and not rig.executed
    assert rig.cleanup == ["pause", "revoke", "close"]


def test_observer_write_failure_stops_before_execute_without_resetting_cost(rig):
    rig.observer_failure = True
    result = rig.run()
    assert result["reason"] == "attempt_receipt_failed"
    assert rig.host_calls == 1 and not rig.executed
    assert rig.budget.billed_calls == 1 and rig.budget.spent_usd == Decimal(".000001")
    assert rig.cleanup == ["pause", "revoke", "close"]


@pytest.mark.parametrize("failed", ["pause", "revoke", "close"])
def test_each_cleanup_failure_preserves_other_attempts_and_reports_failure(rig, failed):
    rig.claim = replace(rig.claim, world_id="world:unrelated")
    rig.cleanup_failure = failed
    result = rig.run()
    assert rig.cleanup == ["pause", "revoke", "close"]
    assert result["cleanup"][failed] == "failed" and not result["safe_stopped"]
    assert {"phase": failed, "type": "RuntimeError"} in result["failures"]
    assert "private cleanup detail" not in str(result)


def test_uncertain_liability_preserved_and_same_guard_cannot_resume(rig):
    usage = CallUsage(
        "being",
        rig.identity.model_id,
        rig.identity.provider,
        0,
        0,
        0,
        0,
        Decimal(".03"),
        cost_basis=CostBasis.UNKNOWN,
        outcome=CallOutcome.TIMED_OUT,
    )
    rig.budget.record(usage)
    rig.audit.observe(usage)
    durable = {"dispatched": Decimal(".03"), "revoked": False}

    def revoke():
        durable["revoked"] = True
        return {
            "revoked": True,
            "authority_id": str(rig.binding.authority_id),
            "workspace_id": str(rig.identity.workspace_id),
        }

    result = pg.run_guarded(
        rig.worker,
        rig.guard,
        pause=lambda: {"mode": "paused", "lease_expires_at": None},
        revoke=revoke,
        close=lambda: None,
    )
    assert result["reason"] == "unknown_provider_liability"
    assert rig.budget.spent_usd == Decimal(".03") and rig.budget.billed_calls == 1
    assert durable == {"dispatched": Decimal(".03"), "revoked": True}
    with pytest.raises(pg.PilotStop, match="pilot_cannot_restart"):
        rig.guard.start()
    assert not rig.executed and rig.host_calls == 0


def test_invalid_primary_binding_never_runs_mutating_cleanup(rig):
    rig.guard.binding = replace(rig.binding, database_url="postgresql://localhost:19950/primary")
    result = rig.run()
    assert result["reason"] == "target_endpoint_not_isolated"
    assert "pause" not in rig.cleanup and "revoke" not in rig.cleanup
    assert not rig.executed and rig.host_calls == rig.told == 0


def test_deadline_crossed_during_state_read_prevents_tell(rig):
    original = rig.guard.read
    calls = 0

    def read():
        nonlocal calls
        calls += 1
        snapshot = original()
        # start, outer pre-pump, then pre-tell claim check.
        if calls == 3:
            rig.now = 600
        return snapshot

    rig.guard.read = read
    result = rig.run()
    assert result["reason"] == "wall_deadline"
    assert rig.told == rig.host_calls == 0 and not rig.executed


def test_real_model_client_repair_dispatch_refuses_after_observer_failure(rig):
    import json

    from exulanica.models.choice import ChoiceRefused, ChoiceRequest
    from exulanica.models.client import ModelClient
    from exulanica.models.errors import TransportError
    from exulanica.models.manifest import AnsweringMechanism, ChosenRoleBinding, load_manifest
    from exulanica.models.spending import SpendingTicket
    from exulanica.models.transport import HttpResponse

    manifest = load_manifest()
    identity = replace(rig.identity, model_id="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
    rig.guard.identity = rig.audit.identity = identity
    original_read = rig.guard.read
    rig.guard.read = lambda: replace(original_read(), identity=identity)
    rig.guard.start()
    events = []

    class Gate:
        def admit(self, request):
            events.append("admit")
            return SpendingTicket(
                uuid4(), rig.binding.authority_id, identity.workspace_id, request.usd, request.key
            )

        def dispatch(self, ticket):
            events.append("dispatch")

        def settle(self, ticket, usage):
            events.append(("settle", usage.cost_basis, usage.usd))

        def release(self, ticket):
            events.append("release")

    gate = Gate()

    class Source:
        def for_workspace(self, workspace):
            assert workspace == identity.workspace_id
            return gate

    class Policy:
        workspace_id = identity.workspace_id

        def admit(self, request):
            return request.texts

    class Transport:
        sends = 0

        def post_json(self, url, **kwargs):
            self.sends += 1
            return HttpResponse(
                status_code=200,
                text=json.dumps(
                    {
                        "model": identity.model_id,
                        "choices": [
                            {"finish_reason": "stop", "message": {"content": "invalid choice"}}
                        ],
                        "usage": {"prompt_tokens": 2, "completion_tokens": 2},
                    }
                ),
            )

    transport = Transport()
    client = ModelClient(
        api_key={identity.provider: "offline-not-a-real-key"},
        manifest=manifest,
        transport=transport,
        budget=rig.budget,
        spending=Source(),
        max_attempts=1,
    )
    observed = pg.guarded_client(client, rig.guard).with_policy(Policy())
    assert observed.budget is rig.budget and observed._chain.spending is gate
    chosen = ChosenRoleBinding(
        role="offline_choice", required_use_cases=("text",), rationale="Offline guard regression"
    )

    def ask():
        return observed.choose(
            chosen,
            identity.model_id,
            [{"role": "user", "content": "Choose wait."}],
            ChoiceRequest(description="Choose.", options=("wait",)),
            mechanism=AnsweringMechanism.JSON_SCHEMA,
            prompt_version="offline-guard-v1",
            timeout=20,
        )

    rig.sink_error = True
    with pytest.raises(ChoiceRefused):
        ask()
    assert transport.sends == 1 and rig.audit.failure == "attempt_receipt_failed"
    charged = rig.budget.spent_usd
    assert charged > 0 and rig.budget.billed_calls == 1
    rig.sink_error = False
    with pytest.raises(TransportError) as error:
        ask()
    assert error.value.reached_provider is False and not error.value.retryable
    assert transport.sends == 1
    assert rig.budget.spent_usd == charged and not rig.budget.held_calls
    assert events.count("dispatch") == 2 and events[-1] == "release"
    assert sum(isinstance(event, tuple) and event[0] == "settle" for event in events) == 1
    # Durable admission precedes the local transport fence; the never-sent second reservation
    # releases normally. The earlier reported liability remains, and no guard is rebuilt.


def test_actual_worker_primary_database_never_mutates_or_cleans_up(rig):
    rig.worker.database.url = "postgresql://localhost:19950/primary"
    result = rig.run()
    assert result["reason"] == "worker_target_differs"
    assert not rig.cleanup and not rig.executed
    assert rig.host_calls == rig.told == 0
