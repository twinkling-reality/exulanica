"""An operator's spending decisions: the command, its evidence rules, and its locks.

An operator's command takes the authority's witness lock and then its row, as every runtime step
does, so it can run while processes are spending: nothing waits in a cycle, and a revocation that
has returned is one no later dispatch gets past.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
import uuid
from decimal import Decimal

import pytest
from exulanica.models.errors import TransportError
from exulanica.models.spending import SpendingRefused, SpendingRequest, next_request_key
from exulanica.models.usage import CallUsage, CostBasis
from exulanica.spending.__main__ import main
from exulanica.spending.operator import SpendingOperationRefused

from model_fakes import FakeTransport
from spending_support import (
    MESSAGES,
    PROVIDER,
    ROLE,
    WorkspacePolicy,
    bench,
    one_reservation,
    spending_client,
)

__all__ = ["bench"]

pytestmark = pytest.mark.postgres


def _command(bench, capsys, *arguments: str) -> tuple[int, dict]:
    environ = {
        "EXULANICA_DATABASE_URL": bench.admin.url,
        "EXULANICA_SPENDING_WITNESS_DIR": str(bench.witness_dir),
    }
    code = main(list(arguments), environ=environ)
    captured = capsys.readouterr()
    return code, json.loads(captured.out if code == 0 else captured.err)


def _request() -> SpendingRequest:
    return SpendingRequest(
        provider=PROVIDER,
        model_id="test/model",
        role=str(ROLE),
        usd=one_reservation(),
        key=next_request_key(),
    )


def test_the_operator_command_issues_grants_reports_revokes_and_verifies(bench, capsys):
    until = (dt.datetime.now(dt.UTC) + dt.timedelta(days=7)).isoformat()
    code, issued = _command(
        bench,
        capsys,
        "issue",
        "--provider",
        PROVIDER,
        "--ceiling-usd",
        "0.5",
        "--max-calls",
        "100",
        "--valid-until",
        until,
        "--operator",
        "ops",
        "--reason",
        "the installation's allowance",
    )
    assert code == 0
    authority = issued["authority_id"]
    workspace = str(uuid.uuid4())
    code, granted = _command(
        bench,
        capsys,
        "grant",
        "--authority",
        authority,
        "--workspace",
        workspace,
        "--ceiling-usd",
        "0.1",
        "--max-calls",
        "10",
        "--valid-until",
        until,
        "--operator",
        "ops",
        "--reason",
        "a workspace that may ask models",
    )
    assert code == 0
    code, status = _command(bench, capsys, "status", "--workspace", workspace)
    assert code == 0
    (entry,) = status["providers"]
    assert entry["grant"]["grant_id"] == granted["grant_id"]
    assert entry["available_usd"] == "0.10000000" and entry["available_calls"] == 10
    code, revoked = _command(
        bench,
        capsys,
        "revoke",
        "--authority",
        authority,
        "--workspace",
        workspace,
        "--grant",
        granted["grant_id"],
        "--operator",
        "ops",
        "--reason",
        "no longer",
    )
    assert (code, revoked) == (0, {"outcome": "revoked"})
    code, verified = _command(bench, capsys, "verify", "--authority", authority)
    assert (code, verified) == (0, {"verified": 3, "first_bad_sequence": None})


@pytest.mark.parametrize("label", ["someone@example.com", "Operator", "two words", ""])
def test_an_operator_label_that_could_carry_an_identity_is_refused(bench, capsys, label):
    until = (dt.datetime.now(dt.UTC) + dt.timedelta(days=7)).isoformat()
    code, refused = _command(
        bench,
        capsys,
        "issue",
        "--provider",
        PROVIDER,
        "--ceiling-usd",
        "0.5",
        "--max-calls",
        "100",
        "--valid-until",
        until,
        "--operator",
        label,
        "--reason",
        "x",
        "--unwitnessed",
    )
    assert code == 1 and "refused" in refused
    assert bench.query("select * from spending_authority") == []


def test_an_unknown_outcome_is_reconciled_only_to_what_evidence_shows(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    transport = FakeTransport([TransportError("timed out", timed_out=True, reached_provider=None)])
    client = spending_client(bench.durable(), transport)
    with pytest.raises(TransportError):
        client.with_policy(WorkspacePolicy(workspace)).chat(
            ROLE, MESSAGES, prompt_version="spending-operator", use_cache=False
        )
    (unknown,) = bench.reservations(workspace)
    assert unknown["state"] == "unknown"
    observed = dt.datetime.now(dt.UTC)
    for source, reference in (("provider-usage", "req one"), ("someone@example.com", "r1")):
        with pytest.raises(SpendingOperationRefused, match="evidence"):
            bench.operator.reconcile(
                workspace,
                unknown["reservation_id"],
                usd=Decimal("0.0001"),
                source=source,
                reference=reference,
                observed_at=observed,
                operator="ops",
            )
    bench.operator.reconcile(
        workspace,
        unknown["reservation_id"],
        usd=Decimal("0.00012000"),
        source="provider-usage-export",
        reference="chatcmpl-0a1b2c",
        observed_at=observed,
        operator="ops",
    )
    (reconciled,) = bench.reservations(workspace)
    assert reconciled["state"] == "reconciled"
    assert reconciled["settled_usd"] == Decimal("0.00012000")
    assert reconciled["reconciliation"]["evidence"]["reference"] == "chatcmpl-0a1b2c"
    assert bench.state(authority)["committed_usd"] == Decimal("0.00012000")
    with pytest.raises(SpendingOperationRefused, match="only an unknown"):
        bench.operator.reconcile(
            workspace,
            unknown["reservation_id"],
            usd=Decimal(0),
            source="provider-usage-export",
            reference="chatcmpl-0a1b2c",
            observed_at=observed,
            operator="ops",
        )


def test_the_operator_releases_every_workspaces_attempts_never_dispatched(bench):
    authority = bench.issue(dispatch_seconds=1)
    first, second = uuid.uuid4(), uuid.uuid4()
    bench.grant(authority, first)
    bench.grant(authority, second)
    durable = bench.durable()
    durable.for_workspace(first).admit(_request())
    durable.for_workspace(second).admit(_request())
    assert bench.state(authority)["committed_calls"] == 2
    time.sleep(1.2)
    assert bench.operator.expire(authority) == 2
    state = bench.state(authority)
    assert (state["committed_usd"], state["committed_calls"]) == (0, 0)


def test_operator_commands_during_runtime_admissions_neither_deadlock_nor_let_one_past(bench):
    authority = bench.issue(ceiling="1", calls=100_000)
    spending, other = uuid.uuid4(), uuid.uuid4()
    grant = bench.grant(authority, spending, ceiling="1", calls=100_000)
    stop = threading.Event()
    outcomes: dict[str, int] = {}
    lock = threading.Lock()

    def spend(label: str) -> None:
        gate = bench.durable(label).for_workspace(spending)
        while not stop.is_set():
            try:
                ticket = gate.admit(_request())
                gate.dispatch(ticket)
                gate.settle(
                    ticket,
                    CallUsage(
                        role=str(ROLE),
                        model_id="test/model",
                        provider=PROVIDER,
                        prompt_tokens=1,
                        completion_tokens=1,
                        reasoning_tokens=0,
                        cached_prompt_tokens=0,
                        usd=Decimal("0.00000100"),
                        cost_basis=CostBasis.REPORTED,
                    ),
                )
                reason = "sent"
            except SpendingRefused as refused:
                reason = refused.reason
            with lock:
                outcomes[reason] = outcomes.get(reason, 0) + 1

    threads = [threading.Thread(target=spend, args=(f"thread-{n}",), daemon=True) for n in range(4)]
    for thread in threads:
        thread.start()
    try:
        time.sleep(0.4)
        until = dt.datetime.now(dt.UTC) + dt.timedelta(days=40)
        started = time.monotonic()
        bench.operator.adjust(
            authority,
            ceiling_usd=Decimal("2"),
            max_calls=200_000,
            valid_until=until,
            operator="ops",
            reason="a larger allowance",
        )
        bench.grant(authority, other)
        bench.operator.revoke(
            authority, workspace_id=spending, grant_id=grant, operator="ops", reason="stop"
        )
        # Four threads spending in a loop with no pause did not hold the operator out: each
        # command waited its turn behind them, never a lock timeout.
        assert time.monotonic() - started < 5
        dispatched_at_revocation = len(
            bench.query("select 1 from spending_reservation where dispatched_at is not null")
        )
        time.sleep(0.4)
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads), "a spending thread kept waiting"
    dispatched_after = len(
        bench.query("select 1 from spending_reservation where dispatched_at is not null")
    )
    # Nothing was dispatched once the revocation had returned, and nothing waited past a timeout.
    assert dispatched_after == dispatched_at_revocation
    assert outcomes.get("sent", 0) > 0
    assert outcomes.get("spending_revoked", 0) > 0
    assert "spending_unavailable" not in outcomes, outcomes
    assert bench.operator.verify_chain(authority)["first_bad_sequence"] is None
    assert bench.committed_over_time(authority)[-1] == bench.state(authority)["committed_usd"]


def test_threads_of_one_process_take_the_witness_in_the_order_they_asked():
    from exulanica.spending.witness import _TurnLock

    turn = _TurnLock()
    assert turn.acquire(timeout=1)
    order: list[object] = []

    def wait(n: int) -> None:
        time.sleep(0.05 * n)  # ask in the order 0, 1, 2
        assert turn.acquire(timeout=5)
        order.append(n)
        turn.release()

    waiters = [threading.Thread(target=wait, args=(n,), daemon=True) for n in range(3)]
    for waiter in waiters:
        waiter.start()
    time.sleep(0.3)
    turn.release()
    for waiter in waiters:
        waiter.join(timeout=5)
    assert order == [0, 1, 2]
    # A wait that ends unserved leaves the queue as it was.
    assert turn.acquire(timeout=1)
    late = threading.Thread(target=lambda: order.append(turn.acquire(timeout=0.05)))
    late.start()
    late.join()
    assert order[-1] is False
    turn.release()
    assert turn.acquire(timeout=0.05)


def test_every_authority_state_reads_without_a_workspace_or_a_writer(bench, capsys):
    from exulanica.spending.status import authority_states

    active = bench.issue()
    revoked = bench.issue(witnessed=False)
    bench.operator.revoke(revoked, operator="ops", reason="closing")
    states = {entry["authority_id"]: entry for entry in authority_states(bench.runtime)}
    assert states[str(active)]["state"] == "active"
    assert states[str(active)]["restore_protection"] == "witnessed"
    assert states[str(revoked)] == {
        "authority_id": str(revoked),
        "provider": states[str(revoked)]["provider"],
        "state": "revoked",
        "restore_protection": "none",
        "epoch": 1,
    }
    code, document = _command(bench, capsys, "status", "--authorities")
    assert code == 0 and len(document["authorities"]) == 2
