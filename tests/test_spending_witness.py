"""A restored database cannot hand spent allowance back.

The spending witness lives outside the database's backup domain. These tests restore an older copy
of every spending table (as a database restore would, with the triggers a restore does not run
disabled) and hold what follows: a ledger behind its live witness admits nothing until it is carried
forward, and then what was spent stays spent; a witness that is missing, a copy, or behind its
ledger holds the authority closed until an operator reauthorizes it explicitly.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import uuid
from decimal import Decimal
from typing import Any

import pytest
from exulanica.models.spending import SpendingRefused, SpendingRequest, next_request_key
from exulanica.spending import witness as witness_module
from exulanica.spending.ledger import SettlementNotRecorded
from exulanica.spending.operator import SpendingOperationRefused
from exulanica.spending.status import workspace_status
from exulanica.spending.witness import FileSpendingWitness
from psycopg import sql
from psycopg.types.json import Jsonb

from model_fakes import FakeTransport
from spending_support import (
    MESSAGES,
    PROVIDER,
    ROLE,
    WorkspacePolicy,
    bench,
    no_usage_body,
    one_reservation,
    reported_usage,
    spending_client,
    spending_request,
)

__all__ = ["bench"]

pytestmark = pytest.mark.postgres

#: Every spending table, parents before children, as a restore writes them.
TABLES = (
    "spending_authority",
    "spending_authority_term",
    "spending_authority_state",
    "spending_authority_revocation",
    "spending_grant",
    "spending_grant_state",
    "spending_grant_revocation",
    "spending_reservation",
    "spending_event",
)


def _snapshot(bench) -> dict[str, list[dict[str, Any]]]:
    with bench.admin.unscoped() as connection:
        return {
            table: connection.execute(
                sql.SQL("select * from {}").format(sql.Identifier(table))
            ).fetchall()
            for table in TABLES
        }


def _restore(bench, snapshot: dict[str, list[dict[str, Any]]]) -> None:
    """Put the spending tables back as the snapshot held them, as restoring a backup does."""
    with bench.admin.unscoped() as connection:
        connection.execute("set local session_replication_role = replica")
        connection.execute(
            sql.SQL("truncate {}").format(sql.SQL(", ").join(sql.Identifier(t) for t in TABLES))
        )
        for table in TABLES:
            for row in snapshot[table]:
                connection.execute(
                    sql.SQL("insert into {} ({}) values ({})").format(
                        sql.Identifier(table),
                        sql.SQL(", ").join(sql.Identifier(name) for name in row),
                        sql.SQL(", ").join(sql.Placeholder() for _ in row),
                    ),
                    [
                        Jsonb(value) if isinstance(value, dict | list) else value
                        for value in row.values()
                    ],
                )


def _spend(client, workspace, times: int) -> None:
    for _ in range(times):
        client.with_policy(WorkspacePolicy(workspace)).chat(
            ROLE, MESSAGES, prompt_version="spending-witness", use_cache=False
        )


def _unknown_cost_client(bench, label="test"):
    transport = FakeTransport()
    transport.default = no_usage_body()
    return spending_client(bench.durable(label), transport), transport


def _refusal(client, workspace) -> SpendingRefused:
    with pytest.raises(SpendingRefused) as refused:
        _spend(client, workspace, 1)
    return refused.value


def _witness_record(bench, authority) -> dict[str, Any]:
    return json.loads(FileSpendingWitness(bench.witness_dir).path(authority).read_bytes())


def _terms(ceiling: Decimal = Decimal("0.01")) -> dict[str, Any]:
    return {
        "ceiling_usd": ceiling,
        "max_calls": 100,
        "valid_until": dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
        "operator": "test-operator",
        "reason": "reauthorized after the provider's balance was checked",
    }


def _current_term(bench, authority) -> dict[str, Any]:
    (row,) = bench.query(
        "select t.* from spending_authority_term t join spending_authority_state s "
        "on s.authority_id = t.authority_id and s.epoch = t.epoch where t.authority_id = %s",
        authority,
    )
    return row


def test_every_step_writes_the_witness_before_its_commit_and_confirms_it_after(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    client, _transport = _unknown_cost_client(bench)
    _spend(client, workspace, 2)
    envelope = _witness_record(bench, authority)
    record = envelope["record"]
    state = bench.state(authority)
    assert envelope["state"] == "live" and record["confirmed"] is True
    assert record["sequence"] == state["sequence"]
    assert record["head_sha256"] == state["head_sha256"].hex()
    assert Decimal(record["committed_usd"]) == state["committed_usd"] == one_reservation() * 2
    (grant,) = record["grants"]
    assert Decimal(grant["committed_usd"]) == one_reservation() * 2


def test_a_step_whose_commit_never_happened_is_read_as_one_that_never_took_effect(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    client, _transport = _unknown_cost_client(bench)
    _spend(client, workspace, 1)
    state = bench.state(authority)
    witness = FileSpendingWitness(bench.witness_dir)
    with witness.hold(authority) as held:
        record = dict(held.record)
        record.update(
            sequence=state["sequence"] + 1,
            previous_sha256=state["head_sha256"].hex(),
            head_sha256="ab" * 32,
            committed_usd="9.00000000",
        )
        held.write(record, confirmed=False)
    _spend(client, workspace, 1)
    assert bench.state(authority)["suspended_reason"] is None
    assert bench.state(authority)["committed_usd"] == one_reservation() * 2


def test_restoring_an_older_ledger_cannot_replenish_what_was_spent(bench):
    one = one_reservation()
    authority = bench.issue(ceiling=one * 10)
    workspace = uuid.uuid4()
    grant = bench.grant(authority, workspace, ceiling=one * 10)
    client, transport = _unknown_cost_client(bench)
    _spend(client, workspace, 2)
    backup = _snapshot(bench)
    _spend(client, workspace, 3)
    assert bench.state(authority)["committed_usd"] == one * 5

    _restore(bench, backup)
    assert bench.state(authority)["committed_usd"] == one * 2
    refused = _refusal(client, workspace)
    assert (refused.reason, refused.detail) == ("spending_suspended", "ledger_behind_witness")
    assert refused.retry == "after_reauthorization"

    outcome = bench.operator.reconcile_restore(
        authority, operator="test-operator", reason="restored from the nightly backup"
    )
    assert Decimal(outcome["carried_usd"]) == one * 3
    assert outcome["frozen"] == 2
    state = bench.state(authority)
    assert (state["committed_usd"], state["committed_calls"]) == (one * 5, 5)
    assert bench.grant_state(workspace, grant)["committed_usd"] == one * 5

    sent_before = transport.call_count
    _spend(client, workspace, 5)
    refused = _refusal(client, workspace)
    assert refused.reason == "spending_limit_reached"
    # Ten reservations in all, as before the restore; never the eight the restored copy offered.
    assert transport.call_count - sent_before == 5
    assert bench.operator.verify_chain(authority)["first_bad_sequence"] is None
    # What the restore carried is history: it never settles again.
    frozen = [row for row in bench.reservations(workspace) if row["frozen"]]
    assert len(frozen) == 2 and {row["state"] for row in frozen} == {"unknown"}


def test_a_revocation_after_the_backup_is_revoked_again_by_the_reconciliation(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    grant = bench.grant(authority, workspace)
    client, _transport = _unknown_cost_client(bench)
    _spend(client, workspace, 1)
    backup = _snapshot(bench)
    bench.operator.revoke(
        authority, workspace_id=workspace, grant_id=grant, operator="test-operator", reason="stop"
    )
    _restore(bench, backup)
    assert bench.query("select * from spending_grant_revocation") == []
    bench.operator.reconcile_restore(authority, operator="test-operator", reason="restored")
    assert len(bench.query("select * from spending_grant_revocation")) == 1
    assert _refusal(client, workspace).reason == "spending_revoked"


def test_a_lost_witness_suspends_the_authority_until_an_operator_reauthorizes_it(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    client, _transport = _unknown_cost_client(bench)
    _spend(client, workspace, 1)
    path = FileSpendingWitness(bench.witness_dir).path(authority)
    kept = path.read_bytes()
    path.unlink()
    refused = _refusal(client, workspace)
    assert (refused.reason, refused.detail) == ("spending_suspended", "witness_missing")
    # Putting the file back does not reopen it: an operator has to decide.
    path.write_bytes(kept)
    assert _refusal(client, workspace).detail == "witness_missing"
    (entry,) = workspace_status(bench.runtime, workspace)["providers"]
    assert (entry["authority_state"], entry["suspension"]) == ("suspended", "witness_missing")
    with pytest.raises(SpendingOperationRefused, match="suspended"):
        bench.grant(authority, uuid.uuid4())
    import datetime as dt

    epoch = bench.operator.reauthorize(
        authority,
        ceiling_usd=one_reservation() * 4,
        max_calls=10,
        valid_until=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
        operator="test-operator",
        reason="the provider's balance was checked",
    )
    assert epoch == 2
    _spend(client, workspace, 1)
    record = _witness_record(bench, authority)["record"]
    assert record["sequence"] == bench.state(authority)["sequence"]


def test_a_witness_copy_keeps_the_authority_suspended_until_it_is_reauthorized(bench, tmp_path):
    import datetime as dt

    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    client, _transport = _unknown_cost_client(bench)
    _spend(client, workspace, 1)
    witness = FileSpendingWitness(bench.witness_dir)
    custody = tmp_path / "custody.json"
    custody.write_bytes(witness.path(authority).read_bytes())
    witness.path(authority).unlink()
    bench.operator.install_witness_copy(authority, custody)
    assert _witness_record(bench, authority)["state"] == "copy"
    refused = _refusal(client, workspace)
    assert (refused.reason, refused.detail) == ("spending_suspended", "witness_copy_only")
    bench.operator.reauthorize(
        authority,
        ceiling_usd=Decimal("0.01"),
        max_calls=100,
        valid_until=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
        operator="test-operator",
        reason="restored from custody after the host was lost",
    )
    assert _witness_record(bench, authority)["state"] == "live"
    _spend(client, workspace, 1)


def test_a_witness_behind_its_ledger_suspends_the_authority(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    client, _transport = _unknown_cost_client(bench)
    _spend(client, workspace, 1)
    path = FileSpendingWitness(bench.witness_dir).path(authority)
    older = path.read_bytes()
    _spend(client, workspace, 1)
    path.write_bytes(older)
    refused = _refusal(client, workspace)
    assert (refused.reason, refused.detail) == ("spending_suspended", "witness_behind")
    assert bench.state(authority)["suspended_reason"] == "witness_behind"


def test_a_process_without_the_witness_refuses_and_suspends_nobody_else(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    blind = spending_client(bench.durable("blind", witnessed=False))
    refused = _refusal(blind, workspace)
    assert (refused.reason, refused.detail) == ("spending_suspended", "witness_not_configured")
    assert bench.state(authority)["suspended_reason"] is None
    client, _transport = _unknown_cost_client(bench)
    _spend(client, workspace, 1)


def test_an_unwitnessed_authority_spends_without_restore_protection(bench):
    authority = bench.issue(witnessed=False)
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    client = spending_client(bench.durable(witnessed=False))
    _spend(client, workspace, 1)
    assert not FileSpendingWitness(bench.witness_dir).path(authority).exists()
    (entry,) = workspace_status(bench.runtime, workspace)["providers"]
    assert entry["restore_protection"] == "none"


def test_reauthorizing_over_a_live_witness_ahead_of_the_ledger_needs_it_said(bench):
    import datetime as dt

    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    client, _transport = _unknown_cost_client(bench)
    backup = _snapshot(bench)
    _spend(client, workspace, 2)
    _restore(bench, backup)
    terms = {
        "ceiling_usd": Decimal("0.01"),
        "max_calls": 100,
        "valid_until": dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
        "operator": "test-operator",
        "reason": "reauthorized",
    }
    with pytest.raises(SpendingOperationRefused, match=r"may hold spending .* \(ahead\)"):
        bench.operator.reauthorize(authority, **terms)
    bench.operator.reauthorize(authority, discard_witness=True, **terms)
    _spend(client, workspace, 1)


def test_a_restore_is_reconciled_only_against_a_witness_ahead_of_it(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    with pytest.raises(SpendingOperationRefused, match="not behind"):
        bench.operator.reconcile_restore(authority, operator="test-operator", reason="nothing")
    gate = bench.durable().for_workspace(workspace)
    gate.admit(
        SpendingRequest(
            provider=PROVIDER,
            model_id="m",
            role=str(ROLE),
            usd=one_reservation(),
            key=next_request_key(),
        )
    )
    FileSpendingWitness(bench.witness_dir).path(authority).unlink()
    with pytest.raises(SpendingOperationRefused, match="no witness or copy"):
        bench.operator.reconcile_restore(authority, operator="test-operator", reason="lost")


def test_a_settlement_or_revocation_on_a_restored_ledger_cannot_hand_spending_back(bench):
    """Nothing is appended to a ledger behind its witness, so it stays behind it: never one that
    looks diverged, which a reauthorization would rewrite the witness from."""
    one = one_reservation()
    authority = bench.issue(ceiling=one * 10)
    workspace, other = uuid.uuid4(), uuid.uuid4()
    bench.grant(authority, workspace, ceiling=one * 10)
    other_grant = bench.grant(authority, other, ceiling=one * 10)
    gate = bench.durable("in-flight").for_workspace(workspace)
    in_flight = gate.admit(spending_request())
    gate.dispatch(in_flight)
    backup = _snapshot(bench)
    # One step the backup lacks: the restored ledger is exactly one behind its witness.
    bench.durable("later").for_workspace(workspace).admit(spending_request())
    assert bench.state(authority)["committed_usd"] == one * 2

    _restore(bench, backup)
    sequence = bench.state(authority)["sequence"]
    with pytest.raises(SettlementNotRecorded, match="witness_disagrees"):
        gate.settle(in_flight, reported_usage("0.00000001"))
    revoked = bench.operator.revoke(
        authority, workspace_id=other, grant_id=other_grant, operator="test-operator", reason="stop"
    )
    assert revoked == "revoked"
    assert bench.state(authority)["sequence"] == sequence
    (row,) = [
        r for r in bench.reservations(workspace) if r["reservation_id"] == in_flight.reservation_id
    ]
    assert row["state"] == "dispatched"
    client = spending_client(bench.durable("next"))
    refused = _refusal(client, workspace)
    assert (refused.reason, refused.detail) == ("spending_suspended", "ledger_behind_witness")
    with pytest.raises(SpendingOperationRefused, match=r"\(ahead\)"):
        bench.operator.reauthorize(authority, **_terms())

    bench.operator.reconcile_restore(authority, operator="test-operator", reason="restored")
    assert bench.state(authority)["committed_usd"] == one * 2
    assert _refusal(client, other).reason == "spending_revoked"
    assert bench.operator.verify_chain(authority)["first_bad_sequence"] is None


def test_a_custody_copy_ahead_of_a_restored_ledger_is_carried_then_reauthorized(bench, tmp_path):
    one = one_reservation()
    authority = bench.issue(ceiling=one * 10)
    workspace = uuid.uuid4()
    bench.grant(authority, workspace, ceiling=one * 10)
    client, _transport = _unknown_cost_client(bench)
    _spend(client, workspace, 1)
    backup = _snapshot(bench)
    _spend(client, workspace, 2)
    witness = FileSpendingWitness(bench.witness_dir)
    custody = tmp_path / "custody.json"
    custody.write_bytes(witness.path(authority).read_bytes())
    # The host is lost with the live witness, and the database comes back from the backup.
    witness.path(authority).unlink()
    _restore(bench, backup)
    bench.operator.install_witness_copy(authority, custody)
    with pytest.raises(SpendingOperationRefused, match=r"\(ahead\)"):
        bench.operator.reauthorize(authority, **_terms())

    outcome = bench.operator.reconcile_restore(
        authority, operator="test-operator", reason="restored from custody"
    )
    assert outcome["from_copy"] is True
    assert Decimal(outcome["carried_usd"]) == one * 2
    assert bench.state(authority)["committed_usd"] == one * 3
    # The copy may be older than the live witness it stands in for: an operator decides.
    refused = _refusal(client, workspace)
    assert (refused.reason, refused.detail) == ("spending_suspended", "witness_copy_only")
    bench.operator.reauthorize(authority, **_terms())
    _spend(client, workspace, 1)
    assert bench.state(authority)["committed_usd"] == one * 4


def test_reauthorizing_over_a_diverged_witness_needs_it_said(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    client, _transport = _unknown_cost_client(bench)
    _spend(client, workspace, 1)
    with FileSpendingWitness(bench.witness_dir).hold(authority) as held:
        record = dict(held.record)
        record["head_sha256"] = "cd" * 32
        held.write(record, confirmed=True)
    refused = _refusal(client, workspace)
    assert (refused.reason, refused.detail) == ("spending_suspended", "witness_diverged")
    with pytest.raises(SpendingOperationRefused, match=r"\(diverged\)"):
        bench.operator.reauthorize(authority, **_terms())
    bench.operator.reauthorize(authority, discard_witness=True, **_terms())
    _spend(client, workspace, 1)


def test_a_restore_that_loses_a_dispatch_keeps_the_attempt_held(bench):
    """A dispatch is on the ledger and the witness, so a restore from before it is a ledger behind
    its witness, and the attempt it lost is frozen rather than released as never sent."""
    authority = bench.issue(dispatch_seconds=1)
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    gate = bench.durable("sender").for_workspace(workspace)
    sent = gate.admit(spending_request())
    backup = _snapshot(bench)
    gate.dispatch(sent)  # the request leaves after the backup was taken
    _restore(bench, backup)
    time.sleep(1.2)  # its dispatch window passes in the restored ledger
    client = spending_client(bench.durable("next"))
    refused = _refusal(client, workspace)
    assert (refused.reason, refused.detail) == ("spending_suspended", "ledger_behind_witness")
    bench.operator.reconcile_restore(authority, operator="test-operator", reason="restored")
    _spend(client, workspace, 1)
    rows = {row["reservation_id"]: row for row in bench.reservations(workspace)}
    assert (rows[sent.reservation_id]["state"], rows[sent.reservation_id]["frozen"]) == (
        "admitted",
        True,
    )
    assert bench.state(authority)["committed_calls"] == 2


def test_a_restore_reconciliation_closes_the_bounds_a_restored_ledger_holds_open(bench):
    """Bounds are not in the witness: a restored bound would offer its spent allowance again, or
    reopen once it was closed, so the reconciliation closes every one the restore brought back."""
    one = one_reservation()
    authority = bench.issue(ceiling=one * 10)
    workspace = uuid.uuid4()
    bench.grant(authority, workspace, ceiling=one * 10)
    durable = bench.durable()
    bound = durable.open_bound(
        workspace,
        provider=PROVIDER,
        key="comparison:1",
        ceiling_usd=one * 2,
        max_calls=2,
        valid_until=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
        reason="one comparison",
    )
    gate = durable.for_workspace(workspace).within(bound)
    first = gate.admit(spending_request())
    gate.dispatch(first)
    gate.settle(first, reported_usage(str(one)))
    backup = _snapshot(bench)
    second = gate.admit(spending_request())
    gate.dispatch(second)
    gate.settle(second, reported_usage(str(one)))
    durable.close_bound(workspace, bound, reason="the comparison finished")

    _restore(bench, backup)
    outcome = bench.operator.reconcile_restore(
        authority, operator="test-operator", reason="restored"
    )
    assert outcome["closed_bounds"] == 1
    with pytest.raises(SpendingRefused) as refused:
        gate.admit(spending_request())
    assert (refused.value.reason, refused.value.scope) == ("spending_revoked", "bound")
    assert bench.state(authority)["committed_usd"] == one * 2


def test_a_restore_counts_the_step_before_one_whose_commit_never_happened(bench, monkeypatch):
    """A witness written and never confirmed keeps the step before it: a restore's carry takes the
    larger amounts and the tighter terms, never a raise that did not commit."""
    one = one_reservation()
    authority = bench.issue(ceiling=one * 10, calls=100)
    workspace = uuid.uuid4()
    bench.grant(authority, workspace, ceiling=one * 10, calls=100)
    client, _transport = _unknown_cost_client(bench)
    _spend(client, workspace, 1)
    backup = _snapshot(bench)
    until = dt.datetime.now(dt.UTC) + dt.timedelta(days=29, hours=12)
    bench.operator.adjust(
        authority,
        ceiling_usd=one * 4,
        max_calls=40,
        valid_until=until,
        operator="test-operator",
        reason="tightened",
    )
    _spend(client, workspace, 1)

    class Stopped(Exception):
        """The process stopped after writing the witness and before its commit."""

    write = witness_module._FileHandle.write

    def write_then_stop(self, record, *, confirmed):
        write(self, record, confirmed=confirmed)
        if not confirmed:
            raise Stopped

    with monkeypatch.context() as patch:
        patch.setattr(witness_module._FileHandle, "write", write_then_stop)
        with pytest.raises(Stopped):
            bench.operator.adjust(
                authority,
                ceiling_usd=one * 9,
                max_calls=90,
                valid_until=until + dt.timedelta(hours=6),
                operator="test-operator",
                reason="a raise that never committed",
            )
    record = _witness_record(bench, authority)["record"]
    assert record["confirmed"] is False
    assert Decimal(record["terms"]["ceiling_usd"]) == one * 9
    assert Decimal(record["prior"]["terms"]["ceiling_usd"]) == one * 4

    _restore(bench, backup)
    bench.operator.reconcile_restore(authority, operator="test-operator", reason="restored")
    term = _current_term(bench, authority)
    assert (term["ceiling_usd"], term["max_calls"], term["valid_until"]) == (one * 4, 40, until)
    assert term["basis"] == "restored"
    assert bench.state(authority)["committed_usd"] == one * 2
