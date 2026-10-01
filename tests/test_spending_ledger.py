"""The durable spending authority's ledger, as the runtime role and an operator reach it.

Every test here connects the runtime as a role that owns nothing and cannot bypass row-level
security, so what it may do is what a deployment's API and worker may do, and the operator as the
harness's own user.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import time
import uuid
from decimal import Decimal

import psycopg
import pytest
from exulanica.models.errors import TransportError
from exulanica.models.spending import (
    SpendingRefused,
    SpendingRequest,
    next_request_key,
    spending_request_key,
)
from exulanica.models.usage import CallUsage, CostBasis
from exulanica.spending.ledger import SettlementNotRecorded, holder_label
from exulanica.spending.operator import SpendingOperationRefused
from exulanica.spending.status import workspace_status
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
    spending_client,
)

__all__ = ["bench"]

pytestmark = pytest.mark.postgres


def _chat(client, workspace):
    return client.with_policy(WorkspacePolicy(workspace)).chat(
        ROLE, MESSAGES, prompt_version="spending-ledger", use_cache=False
    )


def _request(key: str | None = None, usd: Decimal | None = None) -> SpendingRequest:
    return SpendingRequest(
        provider=PROVIDER,
        model_id="test/model",
        role=str(ROLE),
        usd=one_reservation() if usd is None else usd,
        key=next_request_key() if key is None else key,
    )


def _usage(usd: str, basis: CostBasis = CostBasis.REPORTED) -> CallUsage:
    return CallUsage(
        role=str(ROLE),
        model_id="test/model",
        provider=PROVIDER,
        prompt_tokens=10,
        completion_tokens=20,
        reasoning_tokens=0,
        cached_prompt_tokens=0,
        usd=Decimal(usd),
        cost_basis=basis,
    )


def test_nothing_is_granted_because_a_workspace_exists(bench):
    authority = bench.issue()
    transport = FakeTransport()
    client = spending_client(bench.durable(), transport)
    with pytest.raises(SpendingRefused) as refused:
        _chat(client, uuid.uuid4())
    assert (refused.value.reason, refused.value.scope) == ("spending_not_granted", "workspace")
    assert transport.call_count == 0
    assert bench.query("select * from spending_reservation") == []
    assert bench.state(authority)["committed_usd"] == 0


def test_a_grant_is_never_larger_than_its_authority(bench):
    authority = bench.issue(ceiling="0.05", calls=10)
    workspace = uuid.uuid4()
    until = dt.datetime.now(dt.UTC) + dt.timedelta(days=60)
    for terms in ({"ceiling": "0.06"}, {"calls": 11}, {"until": until}):
        with pytest.raises(SpendingOperationRefused, match="never larger"):
            bench.grant(authority, workspace, **terms)
    # The rule is the table's, not only the operator's: a direct insert is refused as well.
    with bench.admin.unscoped() as connection, pytest.raises(psycopg.Error) as refused:
        connection.execute(
            "insert into spending_grant (workspace_id, authority_id, ceiling_usd, max_calls, "
            "valid_until, created_by, reason) values (%s, %s, 1, 1, now() + interval '1 day', "
            "'test-operator', 'too large')",
            (workspace, authority),
        )
    assert refused.value.sqlstate == "23514"
    bench.grant(authority, workspace, ceiling="0.05", calls=10)
    with pytest.raises(SpendingOperationRefused, match="already holds a live grant"):
        bench.grant(authority, workspace, ceiling="0.01")


def test_a_bound_is_never_larger_than_its_grant_and_opens_once(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace, ceiling="0.004", calls=20)
    durable = bench.durable()
    until = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
    with pytest.raises(SpendingRefused) as refused:
        durable.open_bound(
            workspace,
            provider=PROVIDER,
            key="comparison:c1",
            ceiling_usd=Decimal("0.005"),
            max_calls=5,
            valid_until=until,
            reason="a comparison",
        )
    assert (refused.value.reason, refused.value.detail) == (
        "spending_limit_reached",
        "bound_exceeds_grant",
    )
    bound = durable.open_bound(
        workspace,
        provider=PROVIDER,
        key="comparison:c1",
        ceiling_usd=Decimal("0.002"),
        max_calls=5,
        valid_until=until,
        reason="a comparison",
    )
    again = durable.open_bound(
        workspace,
        provider=PROVIDER,
        key="comparison:c1",
        ceiling_usd=Decimal("0.002"),
        max_calls=5,
        valid_until=until,
        reason="a comparison",
    )
    assert again == bound
    with pytest.raises(SpendingRefused):
        durable.open_bound(
            workspace,
            provider=PROVIDER,
            key="comparison:c1",
            ceiling_usd=Decimal("0.001"),
            max_calls=5,
            valid_until=until,
            reason="a comparison",
        )


def test_a_call_holds_every_level_until_its_report_replaces_the_reservation(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    grant = bench.grant(authority, workspace)
    result = _chat(spending_client(bench.durable()), workspace)
    (reservation,) = bench.reservations(workspace)
    assert reservation["state"] == "settled"
    assert reservation["reserved_usd"] == one_reservation()
    assert reservation["settled_usd"] == result.usage.usd
    assert (reservation["prompt_tokens"], reservation["completion_tokens"]) == (100, 200)
    assert bench.state(authority)["committed_usd"] == result.usage.usd
    assert bench.state(authority)["committed_calls"] == 1
    assert bench.grant_state(workspace, grant)["committed_usd"] == result.usage.usd
    kinds = [event["kind"] for event in bench.events(authority)]
    assert kinds == ["issued", "granted", "admitted", "dispatched", "settled"]
    assert bench.operator.verify_chain(authority) == {"verified": 5, "first_bad_sequence": None}


def test_the_grant_and_the_authority_each_refuse_at_their_own_ceiling(bench):
    one = one_reservation()
    authority = bench.issue(ceiling=one * 3)
    small, large = uuid.uuid4(), uuid.uuid4()
    bench.grant(authority, small, ceiling=one * 2)
    bench.grant(authority, large, ceiling=one * 3)
    transport = FakeTransport()
    transport.default = no_usage_body()
    client = spending_client(bench.durable(), transport)
    for _ in range(2):
        _chat(client, small)
    with pytest.raises(SpendingRefused) as refused:
        _chat(client, small)
    assert (refused.value.reason, refused.value.scope) == ("spending_limit_reached", "workspace")
    _chat(client, large)
    with pytest.raises(SpendingRefused) as refused:
        _chat(client, large)
    assert (refused.value.reason, refused.value.scope) == ("spending_limit_reached", "authority")
    # The authority's own figures are every workspace's together, and the refusal keeps them.
    assert "committed" not in refused.value.problem_member()
    assert transport.call_count == 3
    assert max(bench.committed_over_time(authority)) <= one * 3
    assert bench.state(authority)["committed_usd"] == one * 3


def test_a_report_releases_the_difference_an_unknown_keeps_it_and_a_release_returns_all(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    gate = bench.durable().for_workspace(workspace)
    reserved = one_reservation()

    first = gate.admit(_request())
    gate.dispatch(first)
    gate.settle(first, _usage("0.00000100"))
    assert bench.state(authority)["committed_usd"] == Decimal("0.00000100")

    second = gate.admit(_request())
    gate.dispatch(second)
    gate.settle(second, _usage(str(reserved), CostBasis.UNKNOWN))
    assert bench.state(authority)["committed_usd"] == Decimal("0.00000100") + reserved

    third = gate.admit(_request())
    gate.release(third)
    state = bench.state(authority)
    assert state["committed_usd"] == Decimal("0.00000100") + reserved
    assert state["committed_calls"] == 2
    states = sorted(row["state"] for row in bench.reservations(workspace))
    assert states == ["released", "settled", "unknown"]


def test_a_report_above_the_reservation_is_recorded_as_it_is_and_named(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    gate = bench.durable().for_workspace(workspace)
    ticket = gate.admit(_request(usd=Decimal("0.00000100")))
    gate.dispatch(ticket)
    gate.settle(ticket, _usage("0.00000300"))
    assert bench.state(authority)["committed_usd"] == Decimal("0.00000300")
    settled = bench.events(authority)[-1]
    assert settled["kind"] == "settled" and settled["body"]["over_reservation"] is True


def test_an_attempt_never_dispatched_in_time_is_released_and_never_sent(bench):
    authority = bench.issue(dispatch_seconds=1)
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    gate = bench.durable().for_workspace(workspace)
    stale = gate.admit(_request())
    time.sleep(1.2)
    with pytest.raises(SpendingRefused) as refused:
        gate.dispatch(stale)
    assert (refused.value.reason, refused.value.detail) == (
        "spending_unavailable",
        "dispatch_window_passed",
    )
    fresh = gate.admit(_request())
    rows = {row["reservation_id"]: row for row in bench.reservations(workspace)}
    assert rows[stale.reservation_id]["state"] == "released"
    assert rows[stale.reservation_id]["dispatched_at"] is None
    assert rows[fresh.reservation_id]["state"] == "admitted"
    state = bench.state(authority)
    assert (state["committed_usd"], state["committed_calls"]) == (one_reservation(), 1)


def test_an_attempt_key_is_admitted_once_whatever_happened_to_it(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    first = bench.durable("first").for_workspace(workspace)
    other = bench.durable("other").for_workspace(workspace)

    held = first.admit(_request("decision:1#1"))
    # Another call, of this process or another, holds nothing of an attempt it did not admit.
    for gate in (first, other):
        with pytest.raises(SpendingRefused) as refused:
            gate.admit(_request("decision:1#1"))
        assert refused.value.reason == "duplicate_request_in_flight"
    first.dispatch(held)
    with pytest.raises(SpendingRefused) as refused:
        first.admit(_request("decision:1#1"))
    assert refused.value.reason == "duplicate_request_unknown"
    first.settle(held, _usage("0.00000100"))
    with pytest.raises(SpendingRefused) as refused:
        other.admit(_request("decision:1#1"))
    assert refused.value.reason == "duplicate_request_settled"

    released = first.admit(_request("decision:2#1"))
    first.release(released)
    readmitted = other.admit(_request("decision:2#1"))
    assert readmitted.reservation_id == released.reservation_id
    state = bench.state(authority)
    assert state["committed_calls"] == 2
    assert state["committed_usd"] == Decimal("0.00000100") + one_reservation()


def test_another_call_of_the_same_process_can_neither_take_nor_release_an_attempt(bench):
    """Two calls of one process under the same key are two attempts: the second is refused, and
    a release by anything but the attempt that dispatched it is not taken."""
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    durable = bench.durable("api")
    first, second = durable.for_workspace(workspace), durable.for_workspace(workspace)
    with spending_request_key("job:7"):
        key = next_request_key()
    held = first.admit(_request(key))
    with pytest.raises(SpendingRefused) as refused:
        second.admit(_request(key))
    assert refused.value.reason == "duplicate_request_in_flight"
    first.dispatch(held)
    elsewhere = dataclasses.replace(held, holder=f"{durable.holder}:{'0' * 8}")
    with pytest.raises(SettlementNotRecorded, match="not_holder"):
        second.release(elsewhere)
    (row,) = bench.reservations(workspace)
    assert row["state"] == "dispatched"
    first.settle(held, _usage("0.00000100"))
    (row,) = bench.reservations(workspace)
    assert (row["state"], row["settled_usd"]) == ("settled", Decimal("0.00000100"))


def test_an_attempt_named_by_no_holder_is_refused_before_it_touches_a_reservation(bench):
    authority = bench.issue(witnessed=False)
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    held = bench.durable(witnessed=False).for_workspace(workspace).admit(_request())
    for statement in (
        "select spending_dispatch(%(w)s, %(r)s, null, null)",
        "select spending_settle(%(w)s, %(r)s, null, 'not_sent', 0, null, null, null)",
    ):
        with (
            bench.runtime.session(workspace) as connection,
            pytest.raises(psycopg.errors.InvalidParameterValue),
        ):
            connection.execute(statement, {"w": workspace, "r": held.reservation_id})
    (row,) = bench.reservations(workspace)
    assert row["state"] == "admitted"
    assert bench.state(authority)["committed_calls"] == 1


def test_an_admission_refused_under_a_closed_bound_still_releases_attempts_never_sent(bench):
    """An attempt admitted and never dispatched in its window can no longer leave; the next
    admission of its workspace releases it whatever that admission's own answer is."""
    authority = bench.issue(dispatch_seconds=1)
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    durable = bench.durable()
    stale = durable.for_workspace(workspace).admit(_request())
    bound = durable.open_bound(
        workspace,
        provider=PROVIDER,
        key="work:1",
        ceiling_usd=one_reservation() * 2,
        max_calls=2,
        valid_until=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
        reason="one piece of work",
    )
    assert durable.close_bound(workspace, bound, reason="the work was cancelled")
    time.sleep(1.2)  # the dispatch window: the stale admission can no longer leave
    with pytest.raises(SpendingRefused) as refused:
        durable.for_workspace(workspace).within(bound).admit(_request())
    assert (refused.value.reason, refused.value.scope) == ("spending_revoked", "bound")
    rows = {row["reservation_id"]: row for row in bench.reservations(workspace)}
    assert rows[stale.reservation_id]["state"] == "released"
    state = bench.state(authority)
    assert (state["committed_usd"], state["committed_calls"]) == (0, 0)


def test_a_request_replayed_under_its_key_is_not_sent_twice(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    transport = FakeTransport()
    client = spending_client(bench.durable(), transport)
    with spending_request_key("job:42:vision"):
        _chat(client, workspace)
    with pytest.raises(SpendingRefused) as refused, spending_request_key("job:42:vision"):
        _chat(client, workspace)
    assert refused.value.reason == "duplicate_request_settled"
    assert transport.call_count == 1
    assert bench.state(authority)["committed_calls"] == 1


def test_revoking_a_grant_or_an_authority_stops_admission_and_keeps_history(bench):
    authority = bench.issue()
    workspace, neighbour = uuid.uuid4(), uuid.uuid4()
    grant = bench.grant(authority, workspace)
    bench.grant(authority, neighbour)
    durable = bench.durable()
    gate = durable.for_workspace(workspace)
    settled = gate.admit(_request())
    gate.dispatch(settled)
    gate.settle(settled, _usage("0.00000100"))
    waiting = gate.admit(_request())

    assert (
        bench.operator.revoke(
            authority,
            workspace_id=workspace,
            grant_id=grant,
            operator="test-operator",
            reason="no more",
        )
        == "revoked"
    )
    with pytest.raises(SpendingRefused) as refused:
        gate.dispatch(waiting)
    assert (refused.value.reason, refused.value.scope) == ("spending_revoked", "workspace")
    with pytest.raises(SpendingRefused) as refused:
        gate.admit(_request())
    assert (refused.value.reason, refused.value.scope) == ("spending_revoked", "workspace")
    assert (
        bench.operator.revoke(
            authority,
            workspace_id=workspace,
            grant_id=grant,
            operator="test-operator",
            reason="no more",
        )
        == "already"
    )
    # The neighbour still spends until the authority itself is revoked.
    durable.for_workspace(neighbour).admit(_request())
    bench.operator.revoke(authority, operator="test-operator", reason="closing")
    with pytest.raises(SpendingRefused) as refused:
        durable.for_workspace(neighbour).admit(_request())
    assert refused.value.reason == "spending_revoked"
    # History stays: every reservation and every event, the revocations among them.
    assert {row["state"] for row in bench.reservations(workspace)} == {"settled", "admitted"}
    kinds = [event["kind"] for event in bench.events(authority)]
    assert kinds.count("grant_revoked") == 1 and kinds.count("authority_revoked") == 1
    assert bench.operator.verify_chain(authority)["first_bad_sequence"] is None


def test_an_expired_grant_refuses_by_name(bench):
    until = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=1.5)
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace, until=until)
    gate = bench.durable().for_workspace(workspace)
    gate.admit(_request())
    time.sleep(1.6)
    with pytest.raises(SpendingRefused) as refused:
        gate.admit(_request())
    assert (refused.value.reason, refused.value.scope) == ("spending_expired", "workspace")


def test_a_workspace_session_spends_and_reads_for_its_own_workspace_only(bench):
    authority = bench.issue()
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    bench.grant(authority, mine)
    bench.grant(authority, theirs)
    durable = bench.durable()
    durable.for_workspace(mine).admit(_request())
    durable.for_workspace(theirs).admit(_request())
    with (
        bench.runtime.session(mine) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute(
            "select spending_admit(%s, %s, %s, null, 'auto:x', 'm', 'reasoning_cheap', "
            "0.001, %s, null)",
            (theirs, authority, PROVIDER, holder_label("thief")),
        )
    with bench.runtime.session(mine) as connection:
        seen = {
            row["workspace_id"]
            for table in ("spending_reservation", "spending_grant", "spending_grant_state")
            for row in connection.execute(f"select workspace_id from {table}").fetchall()
        }
    assert seen == {mine}
    status = workspace_status(bench.runtime, mine)
    (entry,) = status["providers"]
    assert entry["grant"]["state"] == "active"
    assert entry["in_flight_usd"] == str(one_reservation())


def test_the_runtime_writes_no_spending_table_and_calls_no_operator_function(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    statements = [
        (
            "insert into spending_grant (workspace_id, authority_id, ceiling_usd, max_calls, "
            "valid_until, created_by, reason) values (%(w)s, %(a)s, 1, 1, now(), 'x', 'x')"
        ),
        "update spending_authority_state set committed_usd = 0 where authority_id = %(a)s",
        "update spending_grant_state set committed_usd = 0 where workspace_id = %(w)s",
        "delete from spending_reservation where workspace_id = %(w)s",
        ("select spending_grant_workspace(%(a)s, %(w)s, 1, 1, now(), 'x', 'x', null)"),
        "select spending_reauthorize(%(a)s, 1, 1, now(), 'x', 'x', null, true)",
        "select spending__charge(%(a)s, %(w)s, %(w)s, null, -1, -1)",
    ]
    for statement in statements:
        with (
            bench.runtime.session(workspace) as connection,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            connection.execute(statement, {"a": authority, "w": workspace})


def test_every_change_is_on_a_chain_nobody_can_rewrite(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    client = spending_client(bench.durable())
    for _ in range(3):
        _chat(client, workspace)
    events = bench.events(authority)
    assert bench.operator.verify_chain(authority) == {
        "verified": len(events),
        "first_bad_sequence": None,
    }
    assert bench.committed_over_time(authority)[-1] == bench.state(authority)["committed_usd"]
    with bench.admin.unscoped() as connection, pytest.raises(psycopg.Error, match="append-only"):
        connection.execute(
            "update spending_event set body = %s where authority_id = %s and sequence = 3",
            (Jsonb({"usd": "0"}), authority),
        )


def test_status_is_the_workspace_own_and_names_what_is_unresolved(bench):
    authority = bench.issue()
    workspace, other = uuid.uuid4(), uuid.uuid4()
    bench.grant(authority, workspace, ceiling="0.009", calls=7)
    bench.grant(authority, other)
    transport = FakeTransport([TransportError("timed out", timed_out=True, reached_provider=None)])
    client = spending_client(bench.durable(), transport)
    with pytest.raises(TransportError):
        _chat(client, workspace)
    _chat(client, workspace)
    _chat(client, other)
    (entry,) = workspace_status(bench.runtime, workspace)["providers"]
    assert entry["authority_state"] == "active"
    assert entry["restore_protection"] == "witnessed"
    assert entry["committed_calls"] == 2
    # A timeout settles unknown: its whole reservation stays held and is named as unresolved.
    (unknown,) = [row for row in bench.reservations(workspace) if row["state"] == "unknown"]
    assert entry["unresolved"] == {"count": 1, "usd": str(unknown["settled_usd"])}
    assert unknown["settled_usd"] == unknown["reserved_usd"] == one_reservation()
    assert entry["known_usage_usd"] != "0.00000000"
    assert entry["available_calls"] == 5
    none = workspace_status(bench.runtime, uuid.uuid4())["providers"][0]
    assert none["grant"] == {"state": "none"} and none["available_usd"] == "0.00000000"


def test_an_admission_refused_before_the_authority_row_releases_nothing_until_expire(bench):
    """Stated in the contract's section 12: an admission refused before it takes the authority's
    row (here, no live grant) changes nothing, so its workspace's stale admissions stay held,
    against every workspace's allowance, until an operator runs ``expire``."""
    authority = bench.issue(dispatch_seconds=1)
    workspace = uuid.uuid4()
    grant = bench.grant(authority, workspace)
    durable = bench.durable()
    stale = durable.for_workspace(workspace).admit(_request())
    bench.operator.revoke(
        authority, workspace_id=workspace, grant_id=grant, operator="test-operator", reason="stop"
    )
    time.sleep(1.2)  # the dispatch window: the admission can no longer leave
    with pytest.raises(SpendingRefused) as refused:
        durable.for_workspace(workspace).admit(_request())
    assert (refused.value.reason, refused.value.scope) == ("spending_revoked", "workspace")
    rows = {row["reservation_id"]: row for row in bench.reservations(workspace)}
    assert rows[stale.reservation_id]["state"] == "admitted"
    assert bench.state(authority)["committed_calls"] == 1
    assert bench.operator.expire(authority) == 1
    rows = {row["reservation_id"]: row for row in bench.reservations(workspace)}
    assert rows[stale.reservation_id]["state"] == "released"
    assert bench.state(authority)["committed_calls"] == 0
