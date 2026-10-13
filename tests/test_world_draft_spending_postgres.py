"""Durable draft cancellation and financial dispatch share one witnessed transaction."""

import datetime as dt
import threading
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from exulanica.api.world_draft_worker import DraftSpending, prices_of
from exulanica.models.spending import SpendingRefused, SpendingRequest
from exulanica.world.workspace_lock import lock_workspace
from exulanica.world.world_draft_jobs import WorldDraftRepository, terms_sha256

from spending_support import bench as bench
from spending_support import reported_usage
from test_world_draft_jobs_postgres import definition

pytestmark = pytest.mark.postgres


@pytest.fixture
def funded(bench):
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    durable = bench.durable("private-draft-dispatch")
    defined = definition()
    until = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
    with bench.runtime.session(workspace) as connection:
        repo = WorldDraftRepository(connection, workspace)
        ident = repo.submit(
            actor=actor,
            request_id=uuid.uuid4(),
            description="a small town",
            terms_sha256=terms_sha256("a small town", None, None),
            definition=defined,
            guest=False,
            starts_maximum=12,
        )
        for provider in defined["quote"]["providers"]:
            authority = bench.operator.issue(
                provider=provider["provider"],
                ceiling_usd=Decimal("100"),
                max_calls=10000,
                valid_until=until,
                dispatch_seconds=60,
                witnessed=True,
                operator="test",
                reason="Private financial dispatch fixture",
            )
            bench.operator.grant(
                authority,
                workspace,
                ceiling_usd=Decimal("20"),
                max_calls=1000,
                valid_until=until,
                operator="test",
                reason="Private financial dispatch fixture",
            )
            bound = durable.open_bound(
                workspace,
                provider=provider["provider"],
                key=f"world-draft:{ident}:{provider['provider']}",
                ceiling_usd=Decimal(provider["ceiling_usd"]),
                max_calls=provider["max_calls"],
                valid_until=until,
                reason="Private confirmed operation",
            )
            repo.attach_bound(actor, ident, provider["provider"], bound)
        repo.enqueue(actor, ident)
        claimed = repo.claim()
        bounds = repo.bounds(ident)
    prices = prices_of(defined["quote"])
    client = SimpleNamespace(
        provider_prices=lambda p: {m: v for (provider, m), v in prices.items() if provider == p}
    )
    worker = SimpleNamespace(database=bench.runtime, spending=durable, client=client)
    gate = DraftSpending(worker, claimed, bounds)
    stage = defined["quote"]["paths"][0]["stages"][0]
    model = stage["models"][0]
    request = SpendingRequest(
        model["provider"],
        model["model_id"],
        stage["role"],
        Decimal(model["reservation_usd"]),
        f"private:{uuid.uuid4()}",
    )
    return bench, claimed, gate, gate.admit(request)


def cancel(bench, claimed):
    with bench.runtime.session(claimed.workspace_id) as connection, connection.transaction():
        lock_workspace(connection, claimed.workspace_id)
        connection.execute(
            "update job set state='cancelled',claim_token=null,"
            "lease_expires_at=null,claimed_by=null,completed_at=now() "
            "where job_id=%s",
            (claimed.job_id,),
        )


@pytest.mark.parametrize("first", ["cancel", "dispatch"])
def test_cancellation_and_dispatch_serialize_and_inflight_settlement_remains_authoritative(
    funded,
    monkeypatch,
    first,
):
    bench, claimed, gate, ticket = funded
    held, release, second_started, second_done = [threading.Event() for _ in range(4)]
    original = WorldDraftRepository.require_claim
    failures = []

    def held_claim(repo, claim):
        original(repo, claim)
        held.set()
        assert release.wait(10)

    def first_cancel():
        with bench.runtime.session(claimed.workspace_id) as connection, connection.transaction():
            lock_workspace(connection, claimed.workspace_id)
            connection.execute(
                "update job set state='cancelled',claim_token=null,"
                "lease_expires_at=null,claimed_by=null,completed_at=now() "
                "where job_id=%s",
                (claimed.job_id,),
            )
            held.set()
            assert release.wait(10)

    def dispatch():
        try:
            gate.dispatch(ticket)
        except Exception as error:
            failures.append(error)

    def second():
        second_started.set()
        if first == "dispatch":
            cancel(bench, claimed)
        else:
            dispatch()
        second_done.set()

    if first == "dispatch":
        monkeypatch.setattr(WorldDraftRepository, "require_claim", held_claim)
    a = threading.Thread(target=dispatch if first == "dispatch" else first_cancel)
    b = threading.Thread(target=second)
    a.start()
    assert held.wait(10)
    b.start()
    assert second_started.wait(10)
    assert not second_done.wait(0.1)
    release.set()
    a.join(10)
    b.join(10)
    assert not a.is_alive() and not b.is_alive()
    row = bench.query(
        "select state from spending_reservation where reservation_id=%s", ticket.reservation_id
    )[0]
    attempts = bench.query("select document from world_draft_attempt")
    if first == "cancel":
        assert len(failures) == 1 and isinstance(failures[0], SpendingRefused)
        assert row["state"] == "admitted" and attempts == []
        gate.release(ticket)
    else:
        assert failures == [] and row["state"] == "dispatched"
        assert len(attempts) == 1 and attempts[0]["document"]["kind"] == "dispatch_authorized"
        gate.settle(ticket, reported_usage("0.000001"))
        assert bench.query(
            "select state,settled_usd from spending_reservation where reservation_id=%s",
            ticket.reservation_id,
        ) == [{"state": "settled", "settled_usd": Decimal("0.000001")}]


def test_failure_after_guard_write_rolls_back_attempt_and_financial_dispatch(funded):
    bench, claimed, gate, ticket = funded

    def failing_guard(connection):
        repo = WorldDraftRepository(connection, claimed.workspace_id)
        repo.attempt(claimed, {"kind": "private_guard_write"})
        raise ValueError("private rollback")

    native = gate.tickets[ticket.reservation_id]
    with pytest.raises(ValueError, match="private rollback"):
        native.dispatch(ticket, guard=failing_guard)
    assert bench.query("select 1 from world_draft_attempt") == []
    assert bench.query(
        "select state from spending_reservation where reservation_id=%s", ticket.reservation_id
    ) == [{"state": "admitted"}]
    gate.release(ticket)
