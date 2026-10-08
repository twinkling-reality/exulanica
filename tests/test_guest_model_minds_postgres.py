"""A guest's town asks the model its people were given, and the guest's own grant pays for it.

A guest's workspace is found by account discovery, never listed in the environment; a host that
asked models only for listed workspaces played a guest's town by routine alone, with the chosen
model never asked and the allowance never moved. Shown here against the database, through the
runtime role and the durable spending authority:

*   the positive control: a host that lists nothing and discovers nothing asks no model;
*   the same host given the guest's workspace by discovery asks the chosen model, and each attempt
    is reserved, settled and committed to that workspace's grant under the authority;
*   once the grant's calls are used up nothing more is sent, and the town keeps advancing.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid
from decimal import Decimal

import pytest
from exulanica.api.decision_host import DecisionHost
from exulanica.epistemics.hosted_requests import no_place_released
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.spending.ledger import DurableSpending, holder_label
from exulanica.spending.operator import SpendingOperator
from exulanica.spending.status import read_spending_refusals
from exulanica.spending.witness import FileSpendingWitness
from exulanica.world.society_controls import LEASE_SECONDS

import test_society_person_decisions_postgres as person_decisions
import test_society_stay_requests_api as stays
from tests_support_api import scratch_database

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres

#: The guest's grant in calls: small, so the test reaches its end.
GRANT_CALLS = 2


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_discovered_guest_workspace_asks_its_chosen_model_and_its_grant_pays(
    app, spine_schema, tmp_path
):
    world, client = app
    services = client.app.state.services
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
        reason="the installation's allowance for guests",
    )
    operator.set_guest_policy(
        authority,
        ceiling_usd=Decimal("1"),
        max_calls=GRANT_CALLS,
        valid_for_days=7,
        grants_per_day=1_000,
        operator="test-operator",
        reason="each guest's allowance",
    )
    # The runtime role spends, as the API does under EXULANICA_SPENDING=durable, and the grant is
    # the one a guest's entry takes under the guest policy.
    durable = DurableSpending(services.database, witness, holder=holder_label("guest-minds"))
    grant = durable.grant_guest(workspace, provider=provider)
    assert grant is not None
    transport = person_decisions._Chooser()
    model_client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("100"), max_calls=1000),
        spending=durable,
    )

    def policy_for(workspace_id):
        return services.request_policy(
            workspace_id,
            lambda: services.readonly_database.session(workspace_id),
            released_places=no_place_released,
        )

    def host(discovered: frozenset[uuid.UUID]) -> DecisionHost:
        return DecisionHost(
            database=services.database,
            runtime=services.society_runtime,
            client=model_client,
            workspaces=frozenset(),
            discovered=lambda: discovered,
            policy_for=policy_for,
            manifest=manifest,
            manifest_sha256="a" * 64,
            spending_refusals=lambda connection, workspace: read_spending_refusals(
                connection, workspace, witness_configured=True
            ),
        )

    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    person_decisions._choose(
        services, world, people, {"provider": provider, "model_id": model_id}, manifest=manifest
    )

    def minute(chosen: DecisionHost) -> None:
        nonlocal snapshot
        chosen.before_minute(
            person_decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
        )
        snapshot = stays._step(world, client, snapshot)

    # The control: neither listed nor discovered, the chosen model is never asked.
    for _ in range(5):
        minute(host(frozenset()))
    assert transport.requests == []

    played = host(frozenset({workspace}))
    for _ in range(30):
        minute(played)
        if len(transport.requests) >= GRANT_CALLS:
            break
    else:
        raise AssertionError(f"{len(transport.requests)} asks in 30 minutes")
    assert {request["payload"]["model"] for request in transport.requests} == {model_id}

    reservations = admin_rows(
        admin,
        "select state, settled_usd, grant_id, authority_id, model_id from spending_reservation "
        "where workspace_id = %s",
        workspace,
    )
    assert len(reservations) == len(transport.requests) == GRANT_CALLS
    assert {(r["state"], r["grant_id"], r["authority_id"]) for r in reservations} == {
        ("settled", grant, authority)
    }
    (state,) = admin_rows(
        admin,
        "select committed_usd, committed_calls from spending_grant_state "
        "where workspace_id = %s and grant_id = %s",
        workspace,
        grant,
    )
    assert state["committed_calls"] == GRANT_CALLS
    # What each settled call cost, from the fake's reported tokens (100 prompt, 200 completion,
    # tests/model_fakes.py) and the manifest's prices per million, not from the ledger.
    spec = manifest.spec(model_id)
    each = (100 * spec.input_usd_per_mtok + 200 * spec.output_usd_per_mtok) / Decimal(1_000_000)
    expected = (GRANT_CALLS * each).quantize(Decimal("0.00000001"))
    assert expected > 0
    assert state["committed_usd"] == expected
    assert {r["settled_usd"] for r in reservations} == {each.quantize(Decimal("0.00000001"))}

    # The grant's calls are used up: nothing more is sent, nobody is reserved for (so no
    # admission takes the authority's lock), and the town plays on by routine.
    tick, prepared = snapshot["current_tick"], _requests(admin, workspace)
    for _ in range(5):
        minute(played)
    assert len(transport.requests) == GRANT_CALLS
    assert _requests(admin, workspace) == prepared
    assert snapshot["current_tick"] > tick


def admin_rows(admin, statement: str, *parameters) -> list[dict]:
    with admin.unscoped() as connection:
        return connection.execute(statement, parameters).fetchall()


def _requests(admin, workspace: uuid.UUID) -> int:
    (row,) = admin_rows(
        admin,
        "select count(*) as n from world_society_decision_request where workspace_id = %s",
        workspace,
    )
    return row["n"]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
@pytest.mark.parametrize("above_floor", [False, True], ids=["below-floor", "below-reservation"])
def test_an_allowance_too_small_for_one_ask_is_not_spent_and_the_control_read_says_so(
    app, spine_schema, tmp_path, above_floor
):
    """A USD remainder above zero that fits no attempt's reservation. Below the smallest one
    (the chosen model's answer bound with no prompt) the host reserves nobody and the control read
    says the cap at once. Above it but below what the ask's prompt adds, the ask is made, admission
    refuses it, the receipt says spending_limit_reached and the control read says the cap from
    it. Nothing is sent either way."""
    from types import SimpleNamespace

    from exulanica.api.decision_host import answer_tokens
    from exulanica.api.routes.society_control import model_minds_code

    world, client = app
    services = client.app.state.services
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
        reason="the installation's allowance for guests",
    )
    budget = BudgetGuard(ceiling_usd=Decimal("100"), max_calls=1000)
    spec = manifest.spec(model_id)
    floor = budget.estimate_usd(spec, max_tokens=answer_tokens(spec) or 0)
    ceiling = (
        (floor + Decimal("0.00000001")).quantize(Decimal("0.00000001"), rounding="ROUND_CEILING")
        if above_floor
        else Decimal("0.00000001")
    )
    assert (ceiling >= floor) is above_floor
    operator.grant(
        authority,
        workspace,
        ceiling_usd=ceiling,
        max_calls=200,
        valid_until=now + dt.timedelta(days=7),
        operator="test-operator",
        reason="an allowance below one ask",
    )

    def refusals(connection, workspace_id):
        return read_spending_refusals(connection, workspace_id, witness_configured=True)

    durable = DurableSpending(services.database, witness, holder=holder_label("guest-minds"))
    transport = person_decisions._Chooser()
    host = DecisionHost(
        database=services.database,
        runtime=services.society_runtime,
        client=ModelClient(
            api_key="test-key-not-real",
            manifest=manifest,
            transport=transport,
            budget=budget,
            spending=durable,
        ),
        workspaces=frozenset(),
        discovered=lambda: frozenset({workspace}),
        policy_for=lambda workspace_id: services.request_policy(
            workspace_id,
            lambda: services.readonly_database.session(workspace_id),
            released_places=no_place_released,
        ),
        manifest=manifest,
        manifest_sha256="a" * 64,
        spending_refusals=refusals,
    )
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    person_decisions._choose(
        services, world, people, {"provider": provider, "model_id": model_id}, manifest=manifest
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                services=SimpleNamespace(
                    spending_refusals=refusals, smallest_ask_usd=lambda: {provider: floor}
                )
            )
        )
    )

    def code() -> str | None:
        with services.database.session(workspace) as connection:
            return model_minds_code(request, connection, workspace, snapshot["society_id"])

    if not above_floor:
        # Nothing could be admitted: said before any ask, and nobody is reserved for.
        assert code() == "spending_cap_reached"
        for _ in range(10):
            host.before_minute(
                person_decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
            )
            snapshot = stays._step(world, client, snapshot)
        assert _requests(admin, workspace) == 0
        assert person_decisions._decisions(services, world, snapshot) == []
        assert transport.requests == []
        return
    assert code() is None
    for _ in range(30):
        host.before_minute(
            person_decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
        )
        snapshot = stays._step(world, client, snapshot)
        if person_decisions._decisions(services, world, snapshot):
            break
    receipts = person_decisions._decisions(services, world, snapshot)
    assert receipts and {r["reason"] for r in receipts} == {"spending_limit_reached"}
    assert transport.requests == []
    assert code() == "spending_cap_reached"
