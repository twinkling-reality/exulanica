"""A model is asked for a world's beings only inside an open living session, under its own bound.

Shown against the database, through the runtime role, with a scripted model behind the real client:

*   the positive control first: inside an open session the chosen model is asked; without one,
    in the same listed workspace, it is never asked, and stopping the session stops the asking;
*   under the durable spending authority every ask of a session is admitted under the session's
    own bound of its provider, opened under the workspace's grant at the lower of the session's
    limits and what the grant has left, and keyed by the decision request it answers, so the
    session's call limit stops the asking while the grant still holds more;
*   a guest's Play opens a session for the guest, recorded as opened for that reason.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid
from decimal import Decimal

import pytest
from exulanica.api.decision_host import DecisionHost
from exulanica.api.routes import society_control as control_route
from exulanica.api.session_spending import SessionGate
from exulanica.epistemics.hosted_requests import no_place_released
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.spending.ledger import DurableSpending, holder_label
from exulanica.spending.operator import SpendingOperator
from exulanica.spending.status import read_spending_refusals
from exulanica.spending.witness import FileSpendingWitness
from exulanica.world.society_controls import LEASE_SECONDS
from exulanica.world.society_sessions import SESSION_MAXIMA

import test_society_person_decisions_postgres as person_decisions
import test_society_stay_requests_api as stays
from test_guest_model_minds_postgres import admin_rows
from tests_support_api import scratch_database

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres

LIMITS = {"wall_seconds": 3600, "minutes": 60, "decisions": 100, "usd": "1", "calls": 100}


def _session(client, world, limits=LIMITS) -> dict:
    """Open a living session over the society through its route, at the society's pins."""
    params, version, _society = person_decisions.routes(world)
    route = version + "/society/control"
    read = client.get(route, headers=person_decisions.OWNER, params=params).json()
    opened = client.post(
        route + "/sessions",
        headers=person_decisions.OWNER,
        params=params,
        json={
            "request_id": str(uuid.uuid4()),
            "base_revision": read["revision"],
            "base_tick": read["current_tick"],
            "base_state_sha256": read["state_sha256"],
            "limits": limits,
        },
    )
    assert opened.status_code == 201, opened.text
    return opened.json()


def _stop(client, world, session_id: str) -> None:
    params, version, _society = person_decisions.routes(world)
    stopped = client.post(
        version + f"/society/control/sessions/{session_id}/stop",
        headers=person_decisions.OWNER,
        params=params,
    )
    assert stopped.status_code == 200, stopped.text


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_chosen_model_is_asked_only_inside_an_open_living_session(app):
    world, client = app
    services = person_decisions._services(client)
    manifest, model_id = person_decisions._offered()
    transport = person_decisions._Chooser()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    person_decisions._choose(services, world, people, model, manifest=manifest, open_session=False)
    host = person_decisions._host(
        world, person_decisions._client(manifest, transport), services, manifest
    )

    def minutes(count: int) -> None:
        nonlocal snapshot
        for _ in range(count):
            host.before_minute(
                person_decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
            )
            snapshot = stays._step(world, client, snapshot)

    # The positive control: inside a session the listed world's chosen model is asked.
    opened = _session(client, world)
    for _ in range(30):
        minutes(1)
        if transport.requests:
            break
    assert transport.requests, "nobody was asked inside the session in thirty minutes"
    asked = len(transport.requests)
    # Stopped, the same host in the same listed workspace asks nobody, and writes no request.
    _stop(client, world, opened["session_id"])
    requests = len(person_decisions._decisions(services, world, snapshot))
    minutes(10)
    assert len(transport.requests) == asked
    assert len(person_decisions._decisions(services, world, snapshot)) == requests


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_each_ask_of_a_session_is_admitted_under_its_own_bound_and_keyed_by_its_request(
    app, spine_schema, tmp_path
):
    world, client = app
    services = person_decisions._services(client)
    workspace = world["workspace"]
    manifest, model_id = person_decisions._offered()
    provider = manifest.spec(model_id).provider
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
    grant = operator.grant(
        authority,
        workspace,
        ceiling_usd=Decimal("5"),
        max_calls=500,
        valid_until=now + dt.timedelta(days=7),
        operator="test-operator",
        reason="the owner's allowance",
    )
    durable = DurableSpending(services.database, witness, holder=holder_label("session-minds"))
    transport = person_decisions._Chooser()
    model_client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("100"), max_calls=1000),
        spending=durable,
    )
    host = DecisionHost(
        database=services.database,
        runtime=services.society_runtime,
        client=model_client,
        workspaces=frozenset({workspace}),
        policy_for=lambda workspace_id: services.request_policy(
            workspace_id,
            lambda: services.readonly_database.session(workspace_id),
            released_places=no_place_released,
        ),
        manifest=manifest,
        manifest_sha256="a" * 64,
        spending_refusals=lambda connection, workspace: read_spending_refusals(
            connection, workspace, witness_configured=True
        ),
        spending=durable,
    )
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    person_decisions._choose(
        services,
        world,
        people,
        {"provider": provider, "model_id": model_id},
        manifest=manifest,
        open_session=False,
    )
    # The session states two calls; the grant holds 500: the session's limit is the bound's.
    opened = _session(client, world, limits={**LIMITS, "calls": 2})
    for _ in range(40):
        host.before_minute(
            person_decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
        )
        snapshot = stays._step(world, client, snapshot)
    assert len(transport.requests) == 2
    [bound] = admin_rows(
        admin,
        "select grant_id, parent_grant_id, bound_key, ceiling_usd, max_calls, valid_until "
        "from spending_grant where workspace_id = %s and parent_grant_id is not null",
        workspace,
    )
    assert bound["parent_grant_id"] == grant
    assert bound["bound_key"] == f"living-session:{opened['session_id']}:{provider}"
    assert (bound["ceiling_usd"], bound["max_calls"]) == (Decimal("1"), 2)
    assert bound["valid_until"] <= dt.datetime.fromisoformat(opened["opened"]["ends_by"])
    reservations = admin_rows(
        admin,
        "select request_key, bound_id, grant_id, state from spending_reservation "
        "where workspace_id = %s order by admitted_at",
        workspace,
    )
    assert [(r["bound_id"], r["grant_id"], r["state"]) for r in reservations] == [
        (bound["grant_id"], grant, "settled")
    ] * 2
    requests = {r["request_id"] for r in person_decisions._decisions(services, world, snapshot)}
    assert {r["request_key"] for r in reservations} <= {f"decision:{rid}#1" for rid in requests}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_bound_asks_no_more_than_the_grant_has_left(app, spine_schema, tmp_path):
    world, client = app
    services = person_decisions._services(client)
    workspace = world["workspace"]
    manifest, model_id = person_decisions._offered()
    provider = manifest.spec(model_id).provider
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
        workspace,
        ceiling_usd=Decimal("0.5"),
        max_calls=1,
        valid_until=now + dt.timedelta(days=7),
        operator="test-operator",
        reason="the owner's allowance",
    )
    durable = DurableSpending(services.database, witness, holder=holder_label("session-room"))
    stays._inhabited(world, client)
    opened = _session(client, world)
    gate = SessionGate(
        durable,
        workspace,
        {**opened["opened"], "session_id": opened["session_id"]},
        lambda: services.database.session(workspace),
    )
    bound = gate._bound(provider)
    [row] = admin_rows(
        admin,
        "select ceiling_usd, max_calls from spending_grant where workspace_id = %s "
        "and grant_id = %s",
        workspace,
        bound,
    )
    assert (row["ceiling_usd"], row["max_calls"]) == (Decimal("0.5"), 1)
    # Found again by its key, the next minute's gate opens no second bound.
    again = SessionGate(
        durable,
        workspace,
        {**opened["opened"], "session_id": opened["session_id"]},
        lambda: services.database.session(workspace),
    )
    assert again._bound(provider) == bound


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_guest_s_play_opens_a_session_recorded_for_the_guest(app, monkeypatch):
    world, client = app
    stays._inhabited(world, client)
    params, version, _society = person_decisions.routes(world)
    monkeypatch.setattr(control_route, "holds_as_guest", lambda _request: True)
    route = version + "/society/control"
    read = client.get(route, headers=person_decisions.OWNER, params=params).json()
    played = client.put(
        route,
        headers=person_decisions.OWNER,
        params=params,
        json={"base_revision": read["revision"], "mode": "playing", "speed": 1},
    )
    assert played.status_code == 200, played.text
    assert played.json()["mode"] == "playing"
    [session] = client.get(
        route + "/sessions", headers=person_decisions.OWNER, params=params
    ).json()["sessions"]
    assert session["state"] == "open"
    assert session["opened"]["reason"] == "guest_pressed_play"
    assert session["opened"]["opened_by"] == str(world["session"].actor)
    assert session["opened"]["limits"]["calls"] == SESSION_MAXIMA["calls"]
    # Play again while it plays opens no other session.
    again = client.put(
        route,
        headers=person_decisions.OWNER,
        params=params,
        json={"base_revision": played.json()["revision"], "mode": "playing", "speed": 2},
    )
    assert again.status_code == 200, again.text
    listed = client.get(route + "/sessions", headers=person_decisions.OWNER, params=params).json()
    assert [one["session_id"] for one in listed["sessions"]] == [session["session_id"]]
