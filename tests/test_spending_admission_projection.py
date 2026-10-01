"""What the durable authority would answer a workspace's next attempt, read without making one.

:func:`~exulanica.spending.status.admission_refusal` projects the workspace's own spending onto the
refusal ``spending_admit`` gives. A comparison's start and the capability reads say a spent
allowance with it, before anything is defined or sent. Each case brings the allowance to one state
through the operator and real admissions, reads the projection, then asks admission itself, and
holds the two to one answer: the reason, scope, detail and retry, and the grant's figures. Two
figures are admission's alone, since the projection makes no attempt: the attempt's own amount, and
for an exhausted authority which of its limits ran out.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from decimal import Decimal

import pytest
from exulanica.models.spending import SpendingRefused
from exulanica.spending.ledger import DurableSpending
from exulanica.spending.status import read_spending_refusals
from exulanica.spending.witness import FileSpendingWitness

from spending_support import (
    PROVIDER,
    SpendingBench,
    bench,
    one_reservation,
    reported_usage,
    spending_request,
)

__all__ = ["bench"]

pytestmark = pytest.mark.postgres

_PAST = dt.timedelta(minutes=1)


def _spend(durable: DurableSpending, workspace: uuid.UUID, usd: Decimal | None = None) -> None:
    """One attempt admitted, sent and settled at what it reserved."""
    gate = durable.for_workspace(workspace)
    ticket = gate.admit(spending_request(usd=usd))
    gate.dispatch(ticket)
    gate.settle(ticket, reported_usage(str(ticket.usd)))


def _remaining(bench: SpendingBench, workspace: uuid.UUID) -> DurableSpending:
    bench.grant(bench.issue(), workspace, calls=5)
    return bench.durable()


def _not_granted(bench: SpendingBench, workspace: uuid.UUID) -> DurableSpending:
    bench.issue()
    return bench.durable()


def _grant_revoked(bench: SpendingBench, workspace: uuid.UUID) -> DurableSpending:
    authority = bench.issue()
    grant = bench.grant(authority, workspace)
    bench.operator.revoke(
        authority, workspace_id=workspace, grant_id=grant, operator="test-operator", reason="a test"
    )
    return bench.durable()


def _grant_expired(bench: SpendingBench, workspace: uuid.UUID) -> DurableSpending:
    bench.grant(bench.issue(), workspace, until=dt.datetime.now(dt.UTC) - _PAST)
    return bench.durable()


def _authority_revoked(bench: SpendingBench, workspace: uuid.UUID) -> DurableSpending:
    authority = bench.issue()
    bench.grant(authority, workspace)
    bench.operator.revoke(authority, operator="test-operator", reason="a test")
    return bench.durable()


def _both_revoked(bench: SpendingBench, workspace: uuid.UUID) -> DurableSpending:
    authority = bench.issue()
    grant = bench.grant(authority, workspace)
    bench.operator.revoke(
        authority, workspace_id=workspace, grant_id=grant, operator="test-operator", reason="a test"
    )
    bench.operator.revoke(authority, operator="test-operator", reason="a test")
    return bench.durable()


def _authority_suspended(bench: SpendingBench, workspace: uuid.UUID) -> DurableSpending:
    authority = bench.issue()
    bench.grant(authority, workspace)
    durable = bench.durable()
    FileSpendingWitness(bench.witness_dir).path(authority).unlink()
    # The first admission that finds the witness gone suspends the authority, and says so.
    with pytest.raises(SpendingRefused):
        durable.for_workspace(workspace).admit(spending_request())
    return durable


def _no_witness_here(bench: SpendingBench, workspace: uuid.UUID) -> DurableSpending:
    bench.grant(bench.issue(), workspace)
    return bench.durable(witnessed=False)


def _authority_expired(bench: SpendingBench, workspace: uuid.UUID) -> DurableSpending:
    authority = bench.issue()
    bench.grant(authority, workspace)
    bench.operator.adjust(
        authority,
        ceiling_usd=Decimal("0.01"),
        max_calls=1000,
        valid_until=dt.datetime.now(dt.UTC) - _PAST,
        operator="test-operator",
        reason="a test",
    )
    return bench.durable()


def _authority_exhausted(bench: SpendingBench, workspace: uuid.UUID) -> DurableSpending:
    authority = bench.issue(calls=1)
    neighbour = uuid.uuid4()
    bench.grant(authority, workspace, calls=1)
    bench.grant(authority, neighbour, calls=1)
    durable = bench.durable()
    # Another workspace spends the authority's last call, leaving this one's grant untouched.
    _spend(durable, neighbour)
    return durable


def _grant_calls_spent(bench: SpendingBench, workspace: uuid.UUID) -> DurableSpending:
    bench.grant(bench.issue(), workspace, calls=1)
    durable = bench.durable()
    _spend(durable, workspace)
    return durable


def _grant_money_spent(bench: SpendingBench, workspace: uuid.UUID) -> DurableSpending:
    ceiling = one_reservation()
    bench.grant(bench.issue(), workspace, ceiling=ceiling, calls=5)
    durable = bench.durable()
    _spend(durable, workspace, usd=ceiling)
    return durable


#: Each state, how it is reached, and the members only admission states.
STATES: dict[str, tuple[Callable[[SpendingBench, uuid.UUID], DurableSpending], frozenset[str]]] = {
    "allowance left": (_remaining, frozenset()),
    "no grant": (_not_granted, frozenset()),
    "grant revoked": (_grant_revoked, frozenset()),
    "grant expired": (_grant_expired, frozenset()),
    "authority revoked": (_authority_revoked, frozenset()),
    "grant and its authority revoked": (_both_revoked, frozenset()),
    "authority suspended": (_authority_suspended, frozenset()),
    "no witness directory here": (_no_witness_here, frozenset()),
    "authority expired": (_authority_expired, frozenset()),
    "authority exhausted": (_authority_exhausted, frozenset({"detail", "requested"})),
    "grant's calls spent": (_grant_calls_spent, frozenset()),
    "grant's money spent": (_grant_money_spent, frozenset({"requested"})),
}


@pytest.mark.parametrize("state", list(STATES))
def test_the_projection_answers_as_admission_does(bench, state):
    reach, admissions_alone = STATES[state]
    workspace = uuid.uuid4()
    durable = reach(bench, workspace)
    with bench.runtime.session(workspace) as connection:
        projected = read_spending_refusals(
            connection, workspace, witness_configured=durable.witness is not None
        ).by_provider[PROVIDER]
    gate = durable.for_workspace(workspace)
    try:
        ticket = gate.admit(spending_request())
    except SpendingRefused as refused:
        assert projected is not None, f"admission refused {refused.problem_member()}"
        admitted = refused.problem_member()
        assert projected.problem_member() == {
            name: value for name, value in admitted.items() if name not in admissions_alone
        }
        assert admissions_alone <= set(admitted)
    else:
        gate.release(ticket)
        assert projected is None, projected.problem_member()
