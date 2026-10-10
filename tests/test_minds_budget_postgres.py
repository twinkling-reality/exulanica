"""A world's budget for its minds, through the application and PostgreSQL.

What is shown, as the world's owner through the real routes:

*   a world nobody set a budget for reads the two figures its role's policy catalog states, and
    says nobody set them;
*   a budget set is one appended record under the caller's key, naming who set it: the same
    request asked again answers that record, the key with other figures is refused by name, a
    new request appends the next, and the newest is the budget the read and a mind step's cost
    line state;
*   a budget is set for the role that decides for people alone, in a world and a version that
    exist, and its row can be neither changed nor deleted;
*   the playback host weighs the world's budget before each ask: with a budget of one decision
    an hour it asks one model and writes every other receipt of the minute as past the hour, and
    another world of the workspace is not bounded by it; with a budget of nothing it asks nobody;
*   a budget is never above what the host allows: with the largest budget a row can hold, the
    process's budget, the part of it kept for other work and the workspace's allowance each
    still refuse, by their own names, and no model is asked;
*   two settings at once are taken one after the other, and a retry racing its original answers
    the record the original made;
*   a guest may set their world's budget; a caller who may not ask models may not.

Expected figures are read from the catalog files and from the requests the test itself sends.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
import uuid
from decimal import Decimal

import psycopg
import pytest
from exulanica.api.decision_host import host_refusal, hour_refusal, smallest_ask_usd
from exulanica.api.permissions import GUEST_PERMISSIONS, Permission
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.spending.status import SpendingRefusals
from exulanica.world.decision_roles import decision_roles
from exulanica.world.minds_budget import (
    DECISIONS_MAXIMUM,
    PROFILE,
    USD_MAXIMUM,
    MindsBudget,
    MindsBudgetRefused,
    MindsBudgetRepository,
    default_budget,
)
from exulanica.world.society_controls import LEASE_SECONDS
from fastapi.testclient import TestClient

import test_companion_minds_postgres as minds
import test_companion_things_postgres as things
import test_society_person_decisions_postgres as decisions
import test_society_stay_requests_api as stays
from test_society_saved_world_api import OWNER, TOKEN, routes
from tests_support_api import EVERY_PERMISSION

companion = things.companion
saved_world = things.saved_world
saved_world_app = things.saved_world_app
app = stays.app
pytestmark = pytest.mark.postgres


def _budget_path(world, role_key: str) -> tuple[dict, str]:
    scope, root, _ = routes(world)
    return scope, root + f"/models/{role_key}/budget"


def _set(client, world, usd: str, decisions: int, *, key: str | None = None, role=None):
    scope, path = _budget_path(world, role or minds._people_entry()["key"])
    return client.post(
        path,
        headers=OWNER,
        params=scope,
        json={
            "idempotency_key": key or str(uuid.uuid4()),
            "usd_per_hour": usd,
            "decisions_per_hour": decisions,
        },
    )


def _rows(world) -> list[dict]:
    return (
        world["connection"]
        .execute(
            "select world_id, role_key, budget_seq, document, set_by from world_minds_budget "
            "order by world_id, budget_seq"
        )
        .fetchall()
    )


def _catalog_budget() -> tuple[Decimal, int]:
    """The two figures the people's policy catalog states, read from its file."""
    entry = minds._people_entry()
    version = entry["policy_version"]
    return (
        Decimal(minds._catalog_value(version, "spend_per_world_hour_microusd")) / 1_000_000,
        minds._catalog_value(version, "decisions_per_world_hour_maximum"),
    )


def test_a_world_nobody_set_a_budget_for_has_its_catalog_s_figures(companion):
    world, client, _transport = companion
    minds._town(client, world)
    people = minds._models_read(client, world)
    usd, decisions_an_hour = _catalog_budget()
    assert people["budget"] == {
        "profile": PROFILE,
        "usd_per_hour": f"{usd:.6f}",
        "decisions_per_hour": decisions_an_hour,
        "hour": "real_time",
        "set_by_a_person": False,
        "budget_seq": None,
        "set_by": None,
        "recorded_at": None,
        "document_sha256": None,
    }
    assert people["hour_so_far"] == {"decisions": 0, "usd": "0.000000"}
    assert _rows(world) == []
    # A role whose asks no budget bounds carries none.
    scope, root, _ = routes(world)
    every = client.get(root + "/models", headers=OWNER, params=scope).json()["roles"]
    assert [role.get("budget") for role in every if role["subject"] != "person"] == [
        None for role in every if role["subject"] != "person"
    ]


def test_a_budget_is_one_appended_record_under_its_key_and_the_newest_is_the_budget(companion):
    world, client, _transport = companion
    society = minds._town(client, world)
    key = str(uuid.uuid4())
    first = _set(client, world, "0.5", 1200, key=key)
    assert first.status_code == 200, first.text
    answered = first.json()
    assert answered["role_key"] == minds._people_entry()["key"]
    budget = answered["budget"]
    assert (budget["usd_per_hour"], budget["decisions_per_hour"]) == ("0.500000", 1200)
    assert budget["set_by_a_person"] is True and budget["budget_seq"] == 1
    assert budget["set_by"] == str(world["session"].actor)
    [row] = _rows(world)
    assert (row["world_id"], row["budget_seq"]) == (world["binding"].world_id, 1)
    assert row["document"]["profile"] == PROFILE
    assert row["document"]["document_sha256"] == budget["document_sha256"]

    # The same request again answers the record it made; nothing is appended.
    again = _set(client, world, "0.5", 1200, key=key)
    assert again.status_code == 200 and again.json()["budget"] == budget
    assert len(_rows(world)) == 1
    # The same figures written another way are the same request.
    same = _set(client, world, "0.500000", 1200, key=key)
    assert same.status_code == 200 and len(_rows(world)) == 1
    # The key with other figures is refused by name.
    other = _set(client, world, "0.75", 1200, key=key)
    assert (other.status_code, other.json()["code"]) == (409, "budget_key_reused")
    assert len(_rows(world)) == 1

    # A new request appends the next, and the newest is the budget every read states.
    second = _set(client, world, "0", 0)
    assert second.status_code == 200, second.text
    assert second.json()["budget"]["budget_seq"] == 2
    assert [row["budget_seq"] for row in _rows(world)] == [1, 2]
    read = minds._models_read(client, world)["budget"]
    assert (read["usd_per_hour"], read["decisions_per_hour"], read["budget_seq"]) == (
        "0.000000",
        0,
        2,
    )
    third = _set(client, world, "0.5", 1200)
    assert third.json()["budget"]["budget_seq"] == 3

    # A mind step's cost line states the world's own budget as its ceilings.
    [knight] = minds._of_kind(society, "knight")
    offered = minds._models_read(client, world)["view"]["models"][0]
    mind = f"model:{offered['provider']}/{offered['model_id']}"
    prepared = things._prepare(
        client, world, [{"operation": "choose_mind", "whom": f"being:{knight}", "mind": mind}]
    )
    assert prepared["outcome"] == "plan", things._why(prepared)
    assert prepared["steps"][0]["cost"]["ceilings"] == {
        "usd_per_world_hour": "0.500000",
        "decisions_per_world_hour": 1200,
        "set_by_a_person": True,
    }


def test_a_budget_is_for_the_people_s_role_in_a_world_and_a_version_that_exist(companion):
    world, client, _transport = companion
    minds._town(client, world)
    signals = [role.key for role in decision_roles() if role.subject != "person"]
    assert signals, "the registry states no role beside the people's"
    refused = _set(client, world, "0.5", 10, role=signals[0])
    assert (refused.status_code, refused.json()["code"]) == (409, "budget_not_for_this_role")
    unknown = _set(client, world, "0.5", 10, role="no_such_role")
    assert unknown.status_code == 404
    scope, root, _ = routes(world)
    elsewhere = root.replace(str(world["binding"].version_id), str(uuid.uuid4()))
    missing = client.post(
        elsewhere + f"/models/{minds._people_entry()['key']}/budget",
        headers=OWNER,
        params=scope,
        json={"idempotency_key": str(uuid.uuid4()), "usd_per_hour": "1", "decisions_per_hour": 1},
    )
    assert (missing.status_code, missing.json()["code"]) == (404, "unknown_reference")
    for usd, decisions_an_hour in (("1.1234567", 1), ("-1", 1), ("one", 1), ("1", -1)):
        bad = _set(client, world, usd, decisions_an_hour)
        assert bad.status_code == 422, (usd, decisions_an_hour, bad.text)
    assert _rows(world) == []

    # A recorded budget is never changed or deleted, whoever asks the database.
    assert _set(client, world, "0.5", 10).status_code == 200
    connection = world["connection"]
    for statement in (
        "update world_minds_budget set budget_seq = budget_seq",
        "delete from world_minds_budget",
    ):
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(statement)
    assert len(_rows(world)) == 1


def test_the_hour_is_refused_at_the_world_s_budget_and_the_catalog_s_where_none_is_set():
    """Pure: a world's budget replaces the contract's two figures, each by its own refusal."""
    [role] = [found for found in decision_roles() if found.subject == "person"]
    contract = role.contract()
    usd, decisions_an_hour = _catalog_budget()
    stated = default_budget(contract)
    assert (stated.usd_per_hour, stated.decisions_per_hour) == (usd, decisions_an_hour)
    assert stated.set_by_a_person is False
    bound = Decimal("0.01")
    # Without a budget, and with the catalog's own, the same asks are refused.
    for budget in (None, stated):
        assert hour_refusal(decisions_an_hour - 1, Decimal(0), bound, contract, budget) is None
        assert (
            hour_refusal(decisions_an_hour, Decimal(0), bound, contract, budget)
            == "world_hour_decisions_spent"
        )
        assert hour_refusal(0, usd - bound, bound, contract, budget) is None
        assert (
            hour_refusal(0, usd - bound + Decimal("0.000001"), bound, contract, budget)
            == "world_hour_spend_spent"
        )
    # A smaller budget refuses sooner, a larger one later, a budget of nothing at once.
    small = MindsBudget(Decimal("0.02"), 3)
    assert hour_refusal(2, Decimal("0.01"), bound, contract, small) is None
    assert hour_refusal(3, Decimal(0), bound, contract, small) == "world_hour_decisions_spent"
    assert hour_refusal(0, Decimal("0.011"), bound, contract, small) == "world_hour_spend_spent"
    large = MindsBudget(usd * 10, decisions_an_hour * 10)
    assert hour_refusal(decisions_an_hour, usd, bound, contract, large) is None
    nothing = MindsBudget(Decimal(0), 0)
    assert hour_refusal(0, Decimal(0), bound, contract, nothing) == "world_hour_decisions_spent"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_host_asks_one_model_under_a_budget_of_one_decision_an_hour(app, monkeypatch):
    """Everybody is at a choice point in the first minute. The catalog would let the host ask for
    all of them; the world's budget of one decision an hour lets it ask one, and every other
    receipt of the minute says the hour's decisions are spent."""
    world, client = app
    services = decisions._services(client)
    manifest, model_id = decisions._offered()
    transport = decisions._Chooser()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    assert len(people) >= 2
    decisions._choose(
        services,
        world,
        people,
        {"provider": manifest.spec(model_id).provider, "model_id": model_id},
        manifest=manifest,
    )
    role = decisions.person_role()
    with services.database.session(world["workspace"]) as connection:
        recorded = MindsBudgetRepository(
            connection, world["workspace"], world_id=world["binding"].world_id
        ).record(
            role,
            request_id=uuid.uuid4(),
            usd_per_hour="5",
            decisions_per_hour=1,
            set_by=world["session"].actor,
        )
        # Another world of the workspace has no budget of its own, whatever this one set.
        elsewhere = MindsBudgetRepository(
            connection, world["workspace"], world_id="world:another"
        ).current(role, decisions.decision_contract())
    assert recorded.decisions_per_hour == 1 and recorded.set_by_a_person
    assert elsewhere.set_by_a_person is False
    model_client = decisions._client(manifest, transport)
    host = decisions._host(world, model_client, services, manifest)
    assert host.before_minute(decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    receipts = decisions._decisions(services, world, snapshot)
    asked = [receipt for receipt in receipts if receipt["provider"] is not None]
    spent = [receipt for receipt in receipts if receipt["reason"] == "world_hour_decisions_spent"]
    assert len(asked) == 1 and transport.call_count == 1
    assert len(spent) == len(receipts) - 1 >= 1
    assert all(r["status"] == "unavailable" and r["provider"] is None for r in spent)


def _minded_square(app):
    """The square with people brought in and one model chosen for all of them."""
    world, client = app
    services = decisions._services(client)
    manifest, model_id = decisions._offered()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    assert len(people) >= 2
    decisions._choose(
        services,
        world,
        people,
        {"provider": manifest.spec(model_id).provider, "model_id": model_id},
        manifest=manifest,
    )
    return world, services, manifest, model_id, snapshot


def _budget(services, world, usd, decisions_an_hour, *, key=None) -> MindsBudget:
    with services.database.session(world["workspace"]) as connection:
        return MindsBudgetRepository(
            connection, world["workspace"], world_id=world["binding"].world_id
        ).record(
            decisions.person_role(),
            request_id=key or uuid.uuid4(),
            usd_per_hour=usd,
            decisions_per_hour=decisions_an_hour,
            set_by=world["session"].actor,
        )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_budget_of_nothing_asks_no_model_and_every_receipt_says_the_hour_is_spent(app):
    world, services, manifest, _model_id, snapshot = _minded_square(app)
    _budget(services, world, "0", 0)
    transport = decisions._Chooser()
    host = decisions._host(world, decisions._client(manifest, transport), services, manifest)
    assert host.before_minute(decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    receipts = decisions._decisions(services, world, snapshot)
    assert transport.call_count == 0
    assert receipts and {receipt["reason"] for receipt in receipts} == {
        "world_hour_decisions_spent"
    }
    assert all(receipt["provider"] is None for receipt in receipts)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
@pytest.mark.parametrize("held_back", ["process_budget_spent", "process_share_spent"])
def test_the_largest_budget_leaves_the_process_s_budget_and_its_reserve_refusing(app, held_back):
    """A world whose budget is the largest a row can hold is asked nothing by a process whose own
    budget fits no ask, or fits one only by taking the part kept for its other work: the host's
    refusal names which, no model is called and no receipt claims an ask."""
    world, services, manifest, _model_id, snapshot = _minded_square(app)
    recorded = _budget(services, world, str(USD_MAXIMUM), DECISIONS_MAXIMUM)
    assert (recorded.usd_per_hour, recorded.decisions_per_hour) == (USD_MAXIMUM, DECISIONS_MAXIMUM)
    role = decisions.person_role()
    contract = decisions.decision_contract()
    need = smallest_ask_usd(
        role, BudgetGuard(ceiling_usd=Decimal(1), max_calls=10), manifest, contract
    )
    assert need is not None and need > 0
    # Under one ask's need the whole budget fits none; at one and a half it fits one only by
    # taking the half the contract keeps back.
    ceiling = need / 2 if held_back == "process_budget_spent" else need * Decimal("1.5")
    transport = decisions._Chooser()
    poor = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=ceiling, max_calls=1000),
    )
    assert host_refusal(role, poor, manifest, contract) == held_back
    host = decisions._host(world, poor, services, manifest)
    host.before_minute(decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    assert transport.call_count == 0
    assert [r for r in decisions._decisions(services, world, snapshot) if r["provider"]] == []


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_largest_budget_leaves_a_workspace_s_allowance_refusing(app):
    """The workspace's allowance under the spending authority has almost nothing left. The
    world's budget is the largest a row can hold; every ask is still refused by the allowance's
    own name, before anything is sent."""
    world, services, manifest, model_id, snapshot = _minded_square(app)
    _budget(services, world, str(USD_MAXIMUM), DECISIONS_MAXIMUM)
    provider = manifest.spec(model_id).provider
    transport = decisions._Chooser()
    host = dataclasses.replace(
        decisions._host(world, decisions._client(manifest, transport), services, manifest),
        spending_refusals=lambda _connection, _workspace: SpendingRefusals(
            {provider: None}, {provider: Decimal("0.000001")}
        ),
    )
    assert host.before_minute(decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    receipts = decisions._decisions(services, world, snapshot)
    assert transport.call_count == 0
    assert receipts and {receipt["reason"] for receipt in receipts} == {"spending_limit_reached"}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_two_settings_at_once_are_taken_in_turn_and_a_racing_retry_answers_its_record(app):
    """One setter holds its transaction open after recording. A second setter and a retry of the
    first's own request both wait for it: the second then records the next budget, and the retry
    answers the record the original made. Neither fails."""
    world, client = app
    services = decisions._services(client)
    key = uuid.uuid4()
    recorded, release = threading.Event(), threading.Event()
    answers: dict[str, object] = {}

    def first() -> None:
        with services.database.session(world["workspace"]) as connection, connection.transaction():
            answers["first"] = MindsBudgetRepository(
                connection, world["workspace"], world_id=world["binding"].world_id
            ).record(
                decisions.person_role(),
                request_id=key,
                usd_per_hour="0.5",
                decisions_per_hour=100,
                set_by=world["session"].actor,
            )
            recorded.set()
            assert release.wait(30)

    def later(name: str, request: uuid.UUID, usd: str) -> None:
        try:
            answers[name] = _budget(services, world, usd, 100, key=request)
        except Exception as exc:  # the failure is the test's finding
            answers[name] = exc

    holder = threading.Thread(target=first)
    holder.start()
    assert recorded.wait(30)
    second = threading.Thread(target=later, args=("second", uuid.uuid4(), "0.75"))
    retry = threading.Thread(target=later, args=("retry", key, "0.5"))
    second.start()
    retry.start()
    time.sleep(0.7)
    # Both wait for the first setter's transaction: neither has answered or failed.
    assert "second" not in answers and "retry" not in answers
    release.set()
    for thread in (holder, second, retry):
        thread.join(30)
    first_record, second_record, retried = answers["first"], answers["second"], answers["retry"]
    assert isinstance(second_record, MindsBudget), second_record
    assert isinstance(retried, MindsBudget), retried
    assert first_record.recorded["budget_seq"] == 1
    assert second_record.recorded["budget_seq"] == 2
    assert retried.recorded == first_record.recorded
    assert [row["budget_seq"] for row in _rows(world)] == [1, 2]


def test_a_signed_zero_is_no_figure_and_a_late_retry_answers_the_record_it_made(companion):
    world, client, _transport = companion
    minds._town(client, world)
    with (
        client.app.state.services.database.session(world["workspace"]) as connection,
        pytest.raises(MindsBudgetRefused) as refused,
    ):
        MindsBudgetRepository(
            connection, world["workspace"], world_id=world["binding"].world_id
        ).record(
            next(role for role in decision_roles() if role.subject == "person"),
            request_id=uuid.uuid4(),
            usd_per_hour="-0",
            decisions_per_hour=1,
            set_by=world["session"].actor,
        )
    assert refused.value.code == "budget_usd_not_a_figure"
    assert _rows(world) == []
    # An old key asked again after another budget was set answers the record that key made.
    key = str(uuid.uuid4())
    first = _set(client, world, "0.5", 10, key=key).json()["budget"]
    newer = _set(client, world, "2", 20).json()["budget"]
    late = _set(client, world, "0.5", 10, key=key)
    assert late.status_code == 200 and late.json()["budget"] == first
    assert (first["budget_seq"], newer["budget_seq"]) == (1, 2)
    assert minds._models_read(client, world)["budget"]["budget_seq"] == 2


def test_a_guest_sets_their_world_s_budget_and_a_caller_who_may_ask_no_model_does_not(
    saved_world_app, monkeypatch
):
    world, make_app, _runtime, _database = saved_world_app
    guest, writer = "a-guest-token-long-enough-to-be-one", "a-writer-token-long-enough-to-be-one"
    guest_actor = uuid.uuid4()
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {
                    "workspace_id": str(world["workspace"]),
                    "actor": str(world["session"].actor),
                    "permissions": EVERY_PERMISSION,
                },
                guest: {
                    "workspace_id": str(world["workspace"]),
                    "actor": str(guest_actor),
                    "permissions": sorted(permission.value for permission in GUEST_PERMISSIONS),
                },
                writer: {
                    "workspace_id": str(world["workspace"]),
                    "actor": str(uuid.uuid4()),
                    "permissions": [Permission.WORLD_READ.value, Permission.WORLD_WRITE.value],
                },
            }
        ),
    )
    with TestClient(make_app()) as client:
        scope, path = _budget_path(world, minds._people_entry()["key"])
        body = {
            "idempotency_key": str(uuid.uuid4()),
            "usd_per_hour": "1.5",
            "decisions_per_hour": 2400,
        }
        refused = client.post(
            path, headers={"Authorization": f"Bearer {writer}"}, params=scope, json=body
        )
        # A caller who lacks a permission the route needs is told nothing is there, as on every
        # route (the existence rule): never that a budget could be set with more rights.
        assert (refused.status_code, refused.json()["code"]) == (404, "unknown_reference")
        assert _rows(world) == []
        answered = client.post(
            path, headers={"Authorization": f"Bearer {guest}"}, params=scope, json=body
        )
        assert answered.status_code == 200, answered.text
        budget = answered.json()["budget"]
        assert (budget["usd_per_hour"], budget["decisions_per_hour"]) == ("1.500000", 2400)
        assert budget["set_by"] == str(guest_actor)
