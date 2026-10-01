"""A comparison spends under a durable bound for each provider it asks, held by the authority.

Where a durable spending authority admits the host's calls, the host that plays a comparison opens,
before its first ask, a bound under the workspace's grant for each provider the comparison asks,
with the bound its owner stated and the most calls it can make, and admits every ask under its own
provider's bound (exulanica/api/comparison_spending.py). These tests hold, on private PostgreSQL as
the runtime role with a scripted model:

- a start whose bound, or whose calls, the live grant cannot hold is refused
  ``bound_exceeds_grant`` before anything is written, and its plan states the same refusal;
- a comparison asking two providers asks each under its own provider's bound, and both are closed
  when it is finished;
- a takeover is held to the bound at the authority when spending its host never recorded passes
  what the takeover presumes; the positive control, the same takeover without durable bounds,
  spends past the bound;
- a cancel closes the bounds, so a minute's asks sent after the host's last check are refused by
  the authority, nothing is sent, and the run is named cancelled;
- a grant revoked before the host opens the bound, or replaced while the comparison runs, fails the
  model's asks by the authority's reason before anything is sent, never with a server error;
- a comparison of a town's signals spends under its model's provider's bound, closed when it is
  finished, and its cancel closes it.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import pytest
from exulanica.api import society_comparison_runner as runner_module
from exulanica.api import society_comparison_worker as worker_module
from exulanica.api.comparison_spending import open_comparison_bounds
from exulanica.api.society_comparison_worker import SocietyComparisonWorker
from exulanica.db.session import set_workspace
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.world.society_comparison_start_repository import SocietyComparisonStarts

import test_signal_comparison_postgres as signals
import test_society_comparison_start_postgres as people
import test_society_stay_requests_api as stays
from spending_support import reported_usage, spending_request
from test_comparison_plan_allowance_postgres import (
    SECOND_MODEL,
    SECOND_PROVIDER,
    _choose,
    _plan_people,
    second_provider,
)
from test_comparison_start_allowance_postgres import ROOMY_CALLS, Allowance, _durable
from test_signal_comparison_postgres import _presets_try_every_candidate, town
from test_society_comparison_start_postgres import saved_world, started

__all__ = ["_presets_try_every_candidate", "saved_world", "second_provider", "started", "town"]

pytestmark = pytest.mark.postgres

BOUND = Decimal(people.BOUND)
_EMPTY = {"society_comparison": 0, "society_comparison_run": 0, "society_comparison_start": 0}


def _grant(allowance: Allowance, *, usd: str, calls: int) -> uuid.UUID:
    """The workspace's grant of the comparisons' provider, ``usd`` and ``calls`` large."""
    return allowance.operator.grant(
        allowance.authority,
        allowance.workspace,
        ceiling_usd=Decimal(usd),
        max_calls=calls,
        valid_until=dt.datetime.now(dt.UTC) + dt.timedelta(days=29),
        operator="test-operator",
        reason="a test grant",
    )


def _ledger(allowance: Allowance, statement: str, *parameters: Any) -> list[dict[str, Any]]:
    """Rows of the authority's ledger, read as the operator reads it."""
    with allowance.operator.database.unscoped() as connection:
        return list(connection.execute(statement, parameters).fetchall())


def _bounds(allowance: Allowance, comparison_id: str) -> dict[str, dict[str, Any]]:
    """The comparison's bounds by provider: their grant, terms, what they committed, and
    whether they are closed."""
    rows = _ledger(
        allowance,
        "select g.grant_id, g.bound_key, g.parent_grant_id, g.ceiling_usd, g.max_calls, "
        "s.committed_usd, exists (select 1 from spending_grant_revocation v "
        "where v.workspace_id = g.workspace_id and v.grant_id = g.grant_id) as closed "
        "from spending_grant g join spending_grant_state s "
        "on s.workspace_id = g.workspace_id and s.grant_id = g.grant_id "
        "where g.workspace_id = %s and g.bound_key like %s",
        allowance.workspace,
        f"comparison:{comparison_id}:%",
    )
    return {str(row["bound_key"]).rsplit(":", 1)[1]: row for row in rows}


def _reservations(allowance: Allowance) -> list[dict[str, Any]]:
    return _ledger(
        allowance,
        "select provider, bound_id, state, settled_usd from spending_reservation "
        "where workspace_id = %s",
        allowance.workspace,
    )


def _committed(allowance: Allowance) -> Decimal:
    """What the workspace's grants committed at the authority, a bound's attempts included."""
    (row,) = _ledger(
        allowance,
        "select coalesce(sum(s.committed_usd), 0) as usd from spending_grant g "
        "join spending_grant_state s on s.workspace_id = g.workspace_id "
        "and s.grant_id = g.grant_id where g.workspace_id = %s and g.parent_grant_id is null",
        allowance.workspace,
    )
    return Decimal(row["usd"])


def _result(held: dict[str, Any], comparison_id: str) -> dict[str, Any]:
    world = held["world"]
    read = held["client"].get(
        people._comparisons(world) + f"/{comparison_id}",
        headers=people.OWNER,
        params=people._scope(world),
    )
    assert read.status_code == 200, read.text
    return read.json()


def _seed_runs(result: dict[str, Any], seed: int) -> dict[str, tuple[str, str | None]]:
    return {
        arm: (run["status"], run.get("failure"))
        for arm, run in result["seeds"][seed]["runs"].items()
    }


def _reasons(held: dict[str, Any], comparison_id: str) -> set[str]:
    """Every reason the comparison's stored receipts give, read as the world's owner."""
    world = held["world"]
    connection = world["connection"]
    set_workspace(connection, world["workspace"])
    rows = connection.execute(
        "select receipt->>'reason' as reason from society_comparison_decision "
        "where workspace_id=%s and comparison_id=%s",
        (world["workspace"], uuid.UUID(comparison_id)),
    ).fetchall()
    connection.commit()
    return {str(row["reason"]) for row in rows if row["reason"] is not None}


def _cancel(held: dict[str, Any], comparison_id: str):
    world = held["world"]
    return held["client"].post(
        people._comparisons(world) + f"/{comparison_id}/cancel",
        headers=people.OWNER,
        params=people._scope(world),
    )


def _stopped_part_way(held: dict[str, Any], comparison_id: str) -> int:
    """A host plays the first seed's anchors and five minutes of its model run, then stops and
    leaves its lease to run out, as a host that was killed leaves it. Returns what it asked."""
    world = held["world"]
    renewals: list[uuid.UUID] = []
    renew = SocietyComparisonStarts.renew

    def stops_after_some_minutes(self, claim):
        renewals.append(claim.token)
        return len(renewals) <= 2 * 61 + 5 and renew(self, claim)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(SocietyComparisonStarts, "renew", stops_after_some_minutes)
        assert people._worker(held).run_once(world["workspace"]) is True
    people._expire_the_lease(world, comparison_id)
    asked = len(held["transport"].requests)
    assert asked > 0
    return asked


def _roomy_bound(held: dict[str, Any], seeds: int) -> Decimal:
    """A bound with room beside what a host that stopped part way recorded and what a takeover
    presumes of it, so a takeover's in-process bound lets its runs ask, and what stops them is
    the authority: the most the comparison can cost, at most what the test grant holds."""
    plan = _plan_people(held, seeds=seeds)
    assert plan.status_code == 200, plan.text
    return min(Decimal(plan.json()["plan"]["most_usd"]), Decimal("0.90"))


def _admits_every_seed(monkeypatch) -> None:
    """The host admits every seed whatever it needs, so the bound alone stops a run, as the
    in-process bound is shown ask by ask in tests/test_society_comparison_start_postgres.py."""
    real = worker_module.comparison_cost

    def admits_anything(*args, **kwargs):
        return dataclasses.replace(
            real(*args, **kwargs), typical_usd=Decimal(0), held_usd=Decimal(0)
        )

    monkeypatch.setattr(worker_module, "comparison_cost", admits_anything)


def _unrecorded(allowance: Allowance, usd: Decimal, bound: uuid.UUID | None) -> None:
    """What a host spent at the authority and never recorded in the comparison: one attempt of
    ``usd``, admitted, sent and settled, under ``bound`` where there is one."""
    gate = allowance.durable.for_workspace(allowance.workspace)
    if bound is not None:
        gate = gate.within(bound)
    ticket = gate.admit(spending_request(usd=usd))
    gate.dispatch(ticket)
    gate.settle(ticket, reported_usage(format(usd, "f")))


# -- the grant must hold the bound ---------------------------------------------------------------


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_start_whose_bound_its_grant_cannot_hold_is_refused_and_its_plan_says_so(
    started, spine_schema, tmp_path
):
    world = started["world"]
    stays._inhabited(world, started["client"])
    allowance = _durable(started["client"].app, spine_schema, tmp_path, world["workspace"])
    _grant(allowance, usd="0.05", calls=ROOMY_CALLS)
    plan = _plan_people(started, bound_usd=people.BOUND)
    body = people._body()
    start = people._start(started, body)
    assert start.status_code == 409, start.text
    assert start.json()["code"] == "bound_exceeds_grant"
    assert plan.status_code == 200, plan.text
    assert plan.json()["plan"] is None
    assert plan.json()["plan_refusal"] == {
        "code": "bound_exceeds_grant",
        "detail": start.json()["detail"],
    }
    assert people._counts(world) == _EMPTY
    assert _bounds(allowance, body["comparison_id"]) == {}
    # A plan naming no bound judges the calls alone, which the grant holds; a bound the grant
    # holds plans, and starts.
    assert _plan_people(started).json()["plan_refusal"] is None
    assert _plan_people(started, bound_usd="0.04").json()["plan_refusal"] is None
    assert people._start(started, people._body(bound_usd="0.04")).status_code == 201


def test_a_signal_start_whose_calls_its_grant_cannot_hold_is_refused_and_its_plan_says_so(
    town, spine_schema, tmp_path
):
    workspace = town["repository"].workspace_id
    allowance = _durable(town["api"].client.app, spine_schema, tmp_path, workspace)
    # Two seeds of the town's signals can make 2080 calls.
    allowance.grant(calls=1000)
    named = f"&model={signals.MODEL.provider}/{signals.MODEL.model_id}&seeds=2"
    plan = town["api"].get(signals._path(town, "/plan") + named)
    start = signals._start(town, signals._body())
    assert start.status_code == 409, start.text
    assert start.json()["code"] == "bound_exceeds_grant"
    assert "calls" in start.json()["detail"]
    assert plan.json()["plan_refusal"] == {
        "code": "bound_exceeds_grant",
        "detail": start.json()["detail"],
    }
    assert signals._count(town, "signal_comparison") == 0
    # A bound above the most it can cost is refused by the plan as the start refuses it.
    above = town["api"].get(signals._path(town, "/plan") + named + "&bound_usd=999")
    assert above.json()["plan_refusal"]["code"] == "bound_out_of_range"


# -- one bound for each provider, closed at the end ----------------------------------------------


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_each_provider_is_asked_under_its_own_bound_and_both_close_at_the_end(
    started, spine_schema, tmp_path, second_provider
):
    world, client = started["world"], started["client"]
    app = client.app
    snapshot = stays._inhabited(world, client)
    app.state.services = dataclasses.replace(
        app.state.services,
        model_client=ModelClient(
            api_key={
                people.MODEL.provider: "test-key-not-real",
                SECOND_PROVIDER: "test-key-not-real",
            },
            manifest=second_provider,
            transport=started["transport"],
            budget=BudgetGuard(ceiling_usd=Decimal("5"), max_calls=100_000),
        ),
    )
    allowance = _durable(app, spine_schema, tmp_path, world["workspace"])
    first_grant = _grant(allowance, usd="1", calls=ROOMY_CALLS)
    second = allowance.operator.issue(
        provider=SECOND_PROVIDER,
        ceiling_usd=Decimal("1"),
        max_calls=100_000,
        valid_until=dt.datetime.now(dt.UTC) + dt.timedelta(days=30),
        operator="test-operator",
        reason="a test authority",
    )
    second_grant = allowance.operator.grant(
        second,
        world["workspace"],
        ceiling_usd=Decimal("1"),
        max_calls=ROOMY_CALLS,
        valid_until=dt.datetime.now(dt.UTC) + dt.timedelta(days=29),
        operator="test-operator",
        reason="a test grant",
    )
    group = sorted(person["id"] for person in snapshot["state"]["inhabitants"])
    _choose(
        started, group[:2], {"provider": people.MODEL.provider, "model_id": people.MODEL.model_id}
    )
    _choose(started, [group[2]], {"provider": SECOND_PROVIDER, "model_id": SECOND_MODEL})
    body = people._body(group={"kind": "owner_choice", "choice_seq": 1})
    assert people._start(started, body).status_code == 201
    assert people._worker(started).run_once(world["workspace"]) is True

    result = _result(started, body["comparison_id"])
    assert result["start"]["state"] == "finished"
    assert {status for status, _failure in _seed_runs(result, 0).values()} == {"completed"}
    bounds = _bounds(allowance, body["comparison_id"])
    assert set(bounds) == {people.MODEL.provider, SECOND_PROVIDER}
    assert bounds[people.MODEL.provider]["parent_grant_id"] == first_grant
    assert bounds[SECOND_PROVIDER]["parent_grant_id"] == second_grant
    for bound in bounds.values():
        assert (Decimal(bound["ceiling_usd"]), bound["closed"]) == (BOUND, True)
        assert Decimal(bound["committed_usd"]) <= BOUND
    # Every attempt was admitted under its own provider's bound, and both providers were asked:
    # the group's model in the model arm, the outside person's in every arm.
    reservations = _reservations(allowance)
    assert {row["provider"] for row in reservations} == {people.MODEL.provider, SECOND_PROVIDER}
    for row in reservations:
        assert row["bound_id"] == bounds[row["provider"]]["grant_id"], row


# -- a takeover held at the authority ------------------------------------------------------------


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_positive_control_without_durable_bounds_a_takeover_spends_past_the_bound(
    started, spine_schema, tmp_path, monkeypatch
):
    """The positive control: as before durable bounds, the takeover's own bound is what the
    comparison recorded and presumed. Spending a host made at the authority and never recorded
    past that is invisible to it, and the comparison commits more than its bound."""
    world = started["world"]
    stays._inhabited(world, started["client"])
    allowance = _durable(started["client"].app, spine_schema, tmp_path, world["workspace"])
    allowance.grant(calls=ROOMY_CALLS)
    monkeypatch.setattr(SocietyComparisonWorker, "_bounds", lambda self, claim, providers: None)
    _admits_every_seed(monkeypatch)
    bound = _roomy_bound(started, seeds=2)
    body = people._body(seeds=2, bound_usd=format(bound, "f"))
    assert people._start(started, body).status_code == 201
    asked = _stopped_part_way(started, body["comparison_id"])
    _unrecorded(allowance, bound - _committed(allowance), None)
    assert people._worker(started).run_once(world["workspace"]) is True
    assert len(started["transport"].requests) > asked, "the takeover asked again"
    assert _committed(allowance) > bound
    assert _bounds(allowance, body["comparison_id"]) == {}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_takeover_is_held_to_the_bound_at_the_authority(
    started, spine_schema, tmp_path, monkeypatch
):
    world = started["world"]
    stays._inhabited(world, started["client"])
    allowance = _durable(started["client"].app, spine_schema, tmp_path, world["workspace"])
    allowance.grant(calls=ROOMY_CALLS)
    _admits_every_seed(monkeypatch)
    stated = _roomy_bound(started, seeds=2)
    body = people._body(seeds=2, bound_usd=format(stated, "f"))
    assert people._start(started, body).status_code == 201
    asked = _stopped_part_way(started, body["comparison_id"])
    (bound,) = _bounds(allowance, body["comparison_id"]).values()
    assert not bound["closed"]
    _unrecorded(allowance, stated - Decimal(bound["committed_usd"]), bound["grant_id"])
    assert people._worker(started).run_once(world["workspace"]) is True
    assert len(started["transport"].requests) == asked, "the authority refused the takeover's asks"
    result = _result(started, body["comparison_id"])
    assert _seed_runs(result, 0)["model_a"] == ("failed", "interrupted")
    assert _seed_runs(result, 1)["model_a"] == ("failed", "comparison_bound_spent")
    # The authority refused the takeover's ask by the bound, not the host's own part of it.
    assert "spending_limit_reached" in _reasons(started, body["comparison_id"])
    (after,) = _bounds(allowance, body["comparison_id"]).values()
    assert after["grant_id"] == bound["grant_id"], "the takeover found the same bound"
    assert (Decimal(after["committed_usd"]), after["closed"]) == (stated, True)
    assert _committed(allowance) == stated


# -- a cancel closes the bounds ------------------------------------------------------------------


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_cancel_after_the_hosts_last_check_is_refused_at_the_authority(
    started, spine_schema, tmp_path, monkeypatch
):
    world = started["world"]
    stays._inhabited(world, started["client"])
    allowance = _durable(started["client"].app, spine_schema, tmp_path, world["workspace"])
    allowance.grant(calls=ROOMY_CALLS)
    body = people._body()
    assert people._start(started, body).status_code == 201
    offerable = runner_module._Asking.offerable
    cancelled: list[int] = []

    def then_cancelled(self, tick, due):
        # The host checks the comparison is not cancelled, then its owner cancels it, before the
        # minute's asks are sent.
        offered = offerable(self, tick, due)
        if not cancelled:
            cancelled.append(tick)
            assert _cancel(started, body["comparison_id"]).status_code == 200
        return offered

    monkeypatch.setattr(runner_module._Asking, "offerable", then_cancelled)
    assert people._worker(started).run_once(world["workspace"]) is True
    assert cancelled, "the model run reached its first minute"
    assert started["transport"].requests == [], "nothing was sent after the cancel"
    result = _result(started, body["comparison_id"])
    assert _seed_runs(result, 0)["model_a"] == ("failed", "comparison_cancelled")
    # The authority refused the minute's asks by the closed bound; the run says it was cancelled.
    assert "spending_revoked" in _reasons(started, body["comparison_id"])
    assert (result["start"]["state"], result["start"]["closed_reason"]) == (
        "closed",
        "comparison_cancelled",
    )
    (bound,) = _bounds(allowance, body["comparison_id"]).values()
    assert (Decimal(bound["committed_usd"]), bound["closed"]) == (Decimal(0), True)
    assert _committed(allowance) == 0


# -- the authority refuses the bound -------------------------------------------------------------


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_grant_revoked_before_the_bound_is_opened_fails_the_asks_by_its_reason(
    started, spine_schema, tmp_path
):
    world = started["world"]
    stays._inhabited(world, started["client"])
    allowance = _durable(started["client"].app, spine_schema, tmp_path, world["workspace"])
    grant = _grant(allowance, usd="1", calls=ROOMY_CALLS)
    body = people._body()
    assert people._start(started, body).status_code == 201
    allowance.operator.revoke(
        allowance.authority,
        operator="test-operator",
        reason="a test revocation",
        workspace_id=world["workspace"],
        grant_id=grant,
    )
    assert people._worker(started).run_once(world["workspace"]) is True
    result = _result(started, body["comparison_id"])
    runs = _seed_runs(result, 0)
    assert runs["model_a"] == ("failed", "spending_revoked")
    assert {runs[arm][0] for arm in runs if arm != "model_a"} == {"completed"}
    assert result["start"]["state"] == "finished"
    assert started["transport"].requests == []
    assert _bounds(allowance, body["comparison_id"]) == {}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_grant_replaced_while_it_runs_fails_the_asks_under_the_old_bound(
    started, spine_schema, tmp_path, monkeypatch
):
    world = started["world"]
    stays._inhabited(world, started["client"])
    allowance = _durable(started["client"].app, spine_schema, tmp_path, world["workspace"])
    first = _grant(allowance, usd="1", calls=ROOMY_CALLS)
    _admits_every_seed(monkeypatch)
    body = people._body(seeds=2, bound_usd=format(_roomy_bound(started, seeds=2), "f"))
    assert people._start(started, body).status_code == 201
    asked = _stopped_part_way(started, body["comparison_id"])
    allowance.operator.revoke(
        allowance.authority,
        operator="test-operator",
        reason="a test revocation",
        workspace_id=world["workspace"],
        grant_id=first,
    )
    _grant(allowance, usd="1", calls=ROOMY_CALLS)
    assert people._worker(started).run_once(world["workspace"]) is True
    assert len(started["transport"].requests) == asked
    result = _result(started, body["comparison_id"])
    assert _seed_runs(result, 1)["model_a"] == ("failed", "spending_not_granted")
    assert "spending_not_granted" in _reasons(started, body["comparison_id"])
    assert result["start"]["state"] == "finished"
    (bound,) = _bounds(allowance, body["comparison_id"]).values()
    assert (bound["parent_grant_id"], bound["closed"]) == (first, True)


# -- a town's signals ----------------------------------------------------------------------------


def test_a_signal_comparison_spends_under_its_providers_bound_and_closes_it(
    town, spine_schema, tmp_path
):
    workspace = town["repository"].workspace_id
    allowance = _durable(town["api"].client.app, spine_schema, tmp_path, workspace)
    allowance.grant(calls=ROOMY_CALLS)
    body = signals._body()
    assert signals._start(town, body).status_code == 201
    assert signals._play(town) is True
    result = signals._read(town, body["comparison_id"]).json()
    assert {run["status"] for run in signals._runs(result).values()} == {"completed"}
    (bound,) = _bounds(allowance, body["comparison_id"]).values()
    assert (Decimal(bound["ceiling_usd"]), bound["closed"]) == (Decimal(signals.BOUND), True)
    reservations = _reservations(allowance)
    assert reservations and all(row["bound_id"] == bound["grant_id"] for row in reservations)
    assert Decimal(bound["committed_usd"]) == _committed(allowance) > 0


def test_a_signal_comparisons_cancel_closes_its_bound(town, spine_schema, tmp_path):
    workspace = town["repository"].workspace_id
    allowance = _durable(town["api"].client.app, spine_schema, tmp_path, workspace)
    allowance.grant(calls=ROOMY_CALLS)
    body = signals._body()
    assert signals._start(town, body).status_code == 201
    # A host opened the bound and stopped before asking anything.
    with town["api"].database.session(workspace) as connection:
        opened = open_comparison_bounds(
            allowance.durable,
            connection,
            workspace,
            uuid.UUID(body["comparison_id"]),
            [signals.MODEL.provider],
            usd=Decimal(signals.BOUND),
            calls=ROOMY_CALLS // 10,
        )
    assert set(opened.bounds) == {signals.MODEL.provider}
    assert signals._cancel(town, body["comparison_id"]).status_code == 200
    (bound,) = _bounds(allowance, body["comparison_id"]).values()
    assert bound["closed"] is True
