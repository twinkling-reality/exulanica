"""A living session ends by itself at its limits, and the worker's reaper tidies after it.

Shown against the database with the real playback worker, in this order:

*   while a session is open each claim runs one minute, and the session closes at its minute
    limit, pausing the world, with the limit as its reason and no person;
*   a session past its wall deadline closes at its next claim without running a minute, and the
    reaper closes one whose world is no longer claimed;
*   a minute asks no more models than the session's decisions have left, and the session closes
    once they are used;
*   a session whose bound is spent, or whose call may have cost what nobody knows, closes, and its
    bounds close with it.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid
from decimal import Decimal

import pytest
from exulanica.api.decision_host import DecisionHost
from exulanica.api.session_spending import SessionGate
from exulanica.api.society_control_worker import SocietyControlWorker
from exulanica.epistemics.hosted_requests import no_place_released
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import TransportError
from exulanica.spending.ledger import DurableSpending, holder_label
from exulanica.spending.operator import SpendingOperator
from exulanica.spending.status import read_spending_refusals
from exulanica.spending.witness import FileSpendingWitness

import test_society_controls_postgres as control
import test_society_person_decisions_postgres as person_decisions
import test_society_stay_requests_api as stays
from model_fakes import FakeTransport
from test_guest_model_minds_postgres import admin_rows
from test_living_session_models_postgres import LIMITS as SAVED_LIMITS
from test_living_session_models_postgres import _session
from test_society_runtime import runtime_world as runtime_world
from test_society_sessions_postgres import LIMITS, _open
from tests_support_api import scratch_database

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres
__all__ = ["runtime_world"]


def _worker(w, spine_schema, **more) -> SocietyControlWorker:
    return SocietyControlWorker(
        scratch_database(spine_schema[1]),
        runtime=w["runtime"],
        workspaces=[w["workspace"]],
        base_tick_interval_ms=control.BASE_MS,
        **more,
    )


def _session_of(w, opened) -> dict:
    return control.controls(w).session(w["binding"].version_id, uuid.UUID(opened["session_id"]))


def test_a_session_runs_one_minute_a_claim_and_closes_at_its_minute_limit(
    runtime_world, spine_schema
):
    w = runtime_world
    control.create(w)
    opened = _open(w, limits={**LIMITS, "minutes": 2})
    worker = _worker(w, spine_schema)
    for _ in range(2):
        # Owing many minutes, a claim inside a session still runs one.
        control.overdue(w, seconds=60)
        assert worker.run_once(w["workspace"])["receipt"]["executed_ticks"] == 1
    control.overdue(w, seconds=60)
    stopped = worker.run_once(w["workspace"])
    assert stopped == {"status": "session_closed", "reason": "session_minutes"}
    closed = _session_of(w, opened)
    assert closed["closed"]["reason"] == "session_minutes"
    assert closed["closed"]["closed_by"] is None
    assert closed["closed"]["end_tick"] == opened["opened"]["start_tick"] + 2
    read = control.controls(w).read(w["binding"].version_id)
    assert (read["mode"], read["reason"], read["current_tick"]) == ("paused", "session_minutes", 2)
    assert worker.run_once(w["workspace"]) is None


def test_a_session_past_its_deadline_closes_without_a_minute_and_the_reaper_closes_one_unclaimed(
    runtime_world, spine_schema
):
    w = runtime_world
    control.create(w)
    opened = _open(w, limits={**LIMITS, "wall_seconds": 2})
    worker = _worker(w, spine_schema)
    # Its first round runs the reaper, which finds nothing yet, and a minute.
    control.overdue(w, seconds=60)
    assert worker.run_once(w["workspace"])["receipt"]["executed_ticks"] == 1
    time.sleep(2.2)
    # Past the deadline, inside the reaper's interval: the claim itself closes it.
    control.overdue(w, seconds=60)
    assert worker.run_once(w["workspace"]) == {
        "status": "session_closed",
        "reason": "session_deadline",
    }
    assert _session_of(w, opened)["closed"]["end_tick"] == 1
    # Another stretch, whose world nobody claims once its deadline passes: the reaper closes it.
    read = control.controls(w).read(w["binding"].version_id)
    later = _open(w, revision=read["revision"], limits={**LIMITS, "wall_seconds": 1})
    w["connection"].execute(
        "update world_society_control set next_due_at=clock_timestamp()+interval '1 hour' "
        "where workspace_id=%s",
        (w["workspace"],),
    )
    w["connection"].commit()
    time.sleep(1.2)
    assert _worker(w, spine_schema).reap(w["workspace"]) == 1
    closed = _session_of(w, later)
    assert closed["closed"]["reason"] == "session_deadline"
    assert control.controls(w).read(w["binding"].version_id)["mode"] == "paused"


def _due(services, world) -> None:
    with services.database.session(world["workspace"]) as connection:
        connection.execute(
            "update world_society_control set next_due_at=clock_timestamp()"
            "-interval '1 minute' where workspace_id=%s and mode='playing'",
            (world["workspace"],),
        )


def _host(services, world, manifest, client, **more) -> DecisionHost:
    return DecisionHost(
        database=services.database,
        runtime=services.society_runtime,
        client=client,
        workspaces=frozenset({world["workspace"]}),
        policy_for=lambda workspace_id: services.request_policy(
            workspace_id,
            lambda: services.readonly_database.session(workspace_id),
            released_places=no_place_released,
        ),
        manifest=manifest,
        manifest_sha256="a" * 64,
        **more,
    )


def _played(services, world, host, **more) -> SocietyControlWorker:
    return SocietyControlWorker(
        services.database,
        runtime=services.society_runtime,
        workspaces=[world["workspace"]],
        base_tick_interval_ms=control.BASE_MS,
        before_minute=host.before_minute,
        **more,
    )


def _play_until_closed(services, world, worker, minutes=40) -> dict:
    for _ in range(minutes):
        _due(services, world)
        result = worker.run_once(world["workspace"])
        if result is not None and result.get("status") == "session_closed":
            return result
    raise AssertionError(f"the session did not close in {minutes} minutes")


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_minute_asks_no_more_than_the_session_s_decisions_left(app):
    world, client = app
    services = person_decisions._services(client)
    manifest, model_id = person_decisions._offered()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    person_decisions._choose(services, world, people, model, manifest=manifest, open_session=False)
    transport = person_decisions._Chooser()
    host = _host(services, world, manifest, person_decisions._client(manifest, transport))
    opened = _session(client, world, limits={**SAVED_LIMITS, "decisions": 1})
    result = _play_until_closed(services, world, _played(services, world, host))
    assert result["reason"] == "session_decisions"
    # Two people may be due in one minute: only the one decision the session had left was asked.
    assert len(transport.requests) == 1
    assert len(person_decisions._decisions(services, world, snapshot)) == 1
    params, version, _society = person_decisions.routes(world)
    one = client.get(
        version + f"/society/control/sessions/{opened['session_id']}",
        headers=person_decisions.OWNER,
        params=params,
    ).json()
    assert one["closed"]["reason"] == "session_decisions"


def _durable(services, world, spine_schema, tmp_path, provider):
    _psycopg, scratch = spine_schema
    admin = scratch_database(scratch)
    witness = FileSpendingWitness(tmp_path / "spending-witness", lock_timeout_s=5.0)
    operator = SpendingOperator(admin, witness)
    now = dt.datetime.now(dt.UTC)
    authority = operator.issue(
        provider=provider,
        ceiling_usd=Decimal("10"),
        max_calls=1000,
        valid_until=now + dt.timedelta(days=30),
        dispatch_seconds=60,
        witnessed=True,
        operator="test-operator",
        reason="the installation's allowance",
    )
    operator.grant(
        authority,
        world["workspace"],
        ceiling_usd=Decimal("5"),
        max_calls=500,
        valid_until=now + dt.timedelta(days=7),
        operator="test-operator",
        reason="the owner's allowance",
    )
    return admin, DurableSpending(services.database, witness, holder=holder_label("limits"))


@pytest.mark.parametrize("saved_world", [2], indirect=True)
@pytest.mark.parametrize("ending", ["spent", "unknown"])
def test_a_spent_or_unknown_bound_closes_the_session_and_the_reaper_closes_its_bounds(
    app, spine_schema, tmp_path, ending
):
    world, client = app
    services = person_decisions._services(client)
    manifest, model_id = person_decisions._offered()
    provider = manifest.spec(model_id).provider
    admin, durable = _durable(services, world, spine_schema, tmp_path, provider)
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": provider, "model_id": model_id}
    person_decisions._choose(services, world, people, model, manifest=manifest, open_session=False)
    transport = (
        person_decisions._Chooser()
        if ending == "spent"
        else FakeTransport(
            [TransportError("timed out", timed_out=True, reached_provider=None)] * 10
        )
    )
    model_client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("100"), max_calls=1000),
        spending=durable,
    )
    host = _host(
        services,
        world,
        manifest,
        model_client,
        spending=durable,
        spending_refusals=lambda connection, workspace: read_spending_refusals(
            connection, workspace, witness_configured=True
        ),
    )
    # One call where it is spent: once it is, the next ask is refused by the bound, not the
    # grant. Room for many where a timed-out call's cost is unknown.
    calls = 1 if ending == "spent" else 100
    opened = _session(client, world, limits={**SAVED_LIMITS, "calls": calls})
    worker = _played(services, world, host, spending=durable)
    result = _play_until_closed(services, world, worker)
    expected = "session_spending_limit" if ending == "spent" else "session_liability_unknown"
    assert result["reason"] == expected
    bounds = admin_rows(
        admin,
        "select grant_id from spending_grant where workspace_id = %s and bound_key = %s",
        world["workspace"],
        f"living-session:{opened['session_id']}:{provider}",
    )
    assert len(bounds) == 1

    def closed() -> list[dict]:
        return admin_rows(
            admin,
            "select reason from spending_grant_revocation where workspace_id = %s "
            "and grant_id = %s",
            world["workspace"],
            bounds[0]["grant_id"],
        )

    # Closed with the session, at once; the reaper finds nothing left to do.
    assert [row["reason"] for row in closed()] == ["the living session closed"]
    assert worker.reap(world["workspace"]) == 0
    assert len(closed()) == 1
    # An unknown cost stays held: closing the bound returns nothing of it.
    if ending == "unknown":
        held = admin_rows(
            admin,
            "select state from spending_reservation where workspace_id = %s",
            world["workspace"],
        )
        assert {row["state"] for row in held} == {"unknown"}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_reaper_closes_the_bound_of_a_session_a_person_stopped(app, spine_schema, tmp_path):
    world, client = app
    services = person_decisions._services(client)
    manifest, model_id = person_decisions._offered()
    provider = manifest.spec(model_id).provider
    admin, durable = _durable(services, world, spine_schema, tmp_path, provider)
    stays._inhabited(world, client)
    opened = _session(client, world)
    bound = SessionGate(
        durable,
        world["workspace"],
        {**opened["opened"], "session_id": opened["session_id"]},
        lambda: services.database.session(world["workspace"]),
    )._bound(provider)
    params, version, _society = person_decisions.routes(world)
    stopped = client.post(
        version + f"/society/control/sessions/{opened['session_id']}/stop",
        headers=person_decisions.OWNER,
        params=params,
    )
    assert stopped.status_code == 200, stopped.text

    def closures() -> list[dict]:
        return admin_rows(
            admin,
            "select reason from spending_grant_revocation where workspace_id = %s "
            "and grant_id = %s",
            world["workspace"],
            bound,
        )

    # The stop pauses the world; its bound is the reaper's to close.
    assert closures() == []
    worker = SocietyControlWorker(
        services.database,
        runtime=services.society_runtime,
        workspaces=[world["workspace"]],
        spending=durable,
    )
    worker.reap(world["workspace"])
    assert [row["reason"] for row in closures()] == ["the living session closed"]
    # A session still open keeps its bound.
    again = _session(client, world)
    kept = SessionGate(
        durable,
        world["workspace"],
        {**again["opened"], "session_id": again["session_id"]},
        lambda: services.database.session(world["workspace"]),
    )._bound(provider)
    worker.reap(world["workspace"])
    assert (
        admin_rows(
            admin,
            "select 1 from spending_grant_revocation where workspace_id = %s and grant_id = %s",
            world["workspace"],
            kept,
        )
        == []
    )
