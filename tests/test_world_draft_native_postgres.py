"""Direct and Companion world drafting share durable jobs, native makers and financial records.

Provider answers/rates and all data are private fixtures. No live model or review world is used.
"""

import time
import uuid
from dataclasses import replace

import pytest
from exulanica.api.app import create_app
from exulanica.models.client import ModelClient
from exulanica.models.provider_catalog import ProviderPrice
from fastapi.testclient import TestClient

import test_world_making_postgres as native
from spending_support import bench as bench
from test_kind_drafts_postgres import NEIGHBOUR_TOKEN, OTHER_TOKEN, TOKEN
from test_world_making_postgres import (  # noqa: F401
    _drafts_alias,
    _named_alias,
    imported_drafts,
    saved_named,
)

pytestmark = pytest.mark.postgres
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def native_draft(drafts, bench, monkeypatch):
    factory, transport = drafts
    client = factory()
    services = client.app.state.services
    workspace = services.tokens.session_for(TOKEN).workspace_id

    def price_read(model_client, provider):
        return {
            s.model_id: ProviderPrice(
                s.model_id,
                s.input_usd_per_mtok,
                s.output_usd_per_mtok,
                s.context_window_tokens,
                "f" * 64,
            )
            for s in model_client.manifest.models.values()
            if s.provider == provider
        }

    monkeypatch.setattr(ModelClient, "provider_prices", price_read)
    services = replace(services, database=bench.runtime, readonly_database=bench.runtime)
    with TestClient(create_app(services, verify=False), raise_server_exceptions=True) as running:
        yield running, transport, bench, workspace, services


def done(client, ident):
    end = time.monotonic() + 120
    while time.monotonic() < end:
        response = client.get(f"/worlds/drafts/{ident}", headers=HEADERS)
        assert response.status_code == 200, response.text
        if response.json()["state"] in ("ready", "refused"):
            return response.json()
        time.sleep(0.05)
    raise AssertionError("the private draft did not finish")


def test_companion_proposal_is_readonly_yes_uses_native_job_and_same_key_replays_after_restart(
    native_draft,
):
    client, transport, bench, _workspace, services = native_draft
    transport.responses.extend(
        [
            native._tool("town", native.TOWN_WORDS),
            native._json(native._town_form()),
            *native._plain(),
        ]
    )
    key = str(uuid.uuid4())
    before = len(transport.requests)
    prepared = client.post(
        "/selection/world-drafts/prepare",
        headers=HEADERS,
        json={"description": native.TOWN_WORDS, "idempotency_key": key},
    )
    assert prepared.status_code == 200, prepared.text
    plan = prepared.json()
    assert plan["outcome"] == "plan", plan
    assert len(transport.requests) == before
    assert bench.query("select count(*) as n from job where kind='world_draft'")[0]["n"] == 0
    (step,) = plan["steps"]
    assert step["confirmation"] == "required"
    assert step["body"]["maximum_usd"] == step["cost"]["maximum_usd"]
    started = client.post("/worlds/drafts", headers=HEADERS, json=step["body"])
    assert started.status_code == 202, started.text
    ident = started.json()["draft_id"]
    result = done(client, ident)
    assert result["state"] == "ready", result
    assert result["entry"]["world_id"] == f"world:generated:{ident}"
    assert result["accounting"]["reported_usd"] != "0"
    assert result["accounting"]["unknown_liability_usd"] == "0"
    # The draft's input is forgotten, and the world it made keeps the sentence (0222).
    assert result["description"] == native.TOWN_WORDS
    assert bench.query("select 1 from world_draft_input") == []
    assert bench.query("select world_id, sentence from world_made_from") == [
        {"world_id": f"world:generated:{ident}", "sentence": native.TOWN_WORDS}
    ]
    outcome = client.post("/selection/world-drafts/outcome", headers=HEADERS, json={"plan": plan})
    assert outcome.status_code == 200, outcome.text
    assert outcome.json()["state"] == "ready"
    asked = len(transport.requests)
    retry = client.post("/worlds/drafts", headers=HEADERS, json=step["body"])
    assert retry.status_code == 202 and retry.json()["draft_id"] == ident, retry.text
    assert len(transport.requests) == asked
    foreign = client.get(
        f"/worlds/drafts/{ident}", headers={"Authorization": f"Bearer {OTHER_TOKEN}"}
    )
    other_actor = client.get(
        f"/worlds/drafts/{ident}", headers={"Authorization": f"Bearer {NEIGHBOUR_TOKEN}"}
    )
    assert foreign.status_code == other_actor.status_code == 404
    from exulanica.api.kind_drafts import KindDrafts

    restarted = replace(services, kind_drafts=KindDrafts())
    with TestClient(create_app(restarted, verify=False)) as another:
        read = another.get(f"/worlds/drafts/{ident}", headers=HEADERS)
        assert read.status_code == 200, read.text
        assert read.json()["entry"]["entry_id"] == result["entry"]["entry_id"]
        assert read.json()["accounting"] == result["accounting"]
        assert len(transport.requests) == asked


def ready_draft(native_draft):
    client, transport, _bench, _workspace, _services = native_draft
    transport.responses.extend(
        [
            native._tool("town", native.TOWN_WORDS),
            native._json(native._town_form()),
            *native._plain(),
        ]
    )
    prepared = client.post(
        "/selection/world-drafts/prepare", headers=HEADERS, json={"description": native.TOWN_WORDS}
    ).json()
    body = prepared["steps"][0]["body"]
    start = client.post("/worlds/drafts", headers=HEADERS, json=body)
    assert start.status_code == 202, start.text
    result = done(client, start.json()["draft_id"])
    assert result["state"] == "ready", result
    return body, result


def test_saved_before_outcome_crash_recovers_without_a_second_model_request(
    native_draft, monkeypatch
):
    from exulanica.world.world_draft_jobs import WorldDraftRefused, WorldDraftRepository

    client, transport, bench, workspace, _services = native_draft
    original = WorldDraftRepository.finish

    def crash_before_outcome(self, claimed, document):
        raise WorldDraftRefused("private_crash_before_outcome")

    monkeypatch.setattr(WorldDraftRepository, "finish", crash_before_outcome)
    transport.responses.extend(
        [
            native._tool("town", native.TOWN_WORDS),
            native._json(native._town_form()),
            *native._plain(),
        ]
    )
    start = client.post(
        "/worlds/drafts",
        headers=HEADERS,
        json={"description": native.TOWN_WORDS, "idempotency_key": str(uuid.uuid4())},
    )
    assert start.status_code == 202, start.text
    ident = start.json()["draft_id"]
    until = time.monotonic() + 30
    while time.monotonic() < until:
        held = client.app.state.services.kind_drafts.read(
            workspace,
            client.app.state.services.tokens.session_for(TOKEN).actor,
            uuid.UUID(ident),
            purpose="world",
        )
        if held and held.state == "ready":
            break
        time.sleep(0.02)
    assert held is not None and held.state == "ready"
    assert bench.query(
        "select entry_id from saved_world_entry where world_id=%s", f"world:generated:{ident}"
    )
    assert bench.query("select 1 from world_draft_outcome") == []
    asked = len(transport.requests)
    monkeypatch.setattr(WorldDraftRepository, "finish", original)
    # Only a job still running holds a lease to expire: under load its own lease can lapse and the
    # job recover before this line, and a finished job may not hold one.
    bench.query(
        "update job set lease_expires_at=now()-interval '1 second' "
        "where kind='world_draft' and state='running' returning job_id"
    )
    result = done(client, ident)
    assert result["state"] == "ready" and result["recovered"] is True, result
    assert result["entry"]["entry_id"] == str(held.entry_id)
    assert result["accounting"]["reported_usd"] != "0"
    assert len(transport.requests) == asked


@pytest.mark.parametrize("scope", ["world", "workspace"])
def test_erasure_forgets_content_hides_key_and_keeps_financial_ids(native_draft, scope):
    from exulanica.world.world_erasure import erase_world

    client, transport, bench, workspace, services = native_draft
    body, result = ready_draft(native_draft)
    actor = services.tokens.session_for(TOKEN).actor
    ident = result["draft_id"]
    liabilities = bench.query(
        "select reservation_id,state,reserved_usd,settled_usd "
        "from spending_reservation order by reservation_id"
    )
    before = len(transport.requests)
    assert bench.query("select 1 from world_made_from")  # Positive control: the world kept it.
    with bench.runtime.session(workspace) as connection:
        if scope == "world":
            erase_world(connection, workspace, result["entry"]["world_id"], erased_by=actor)
        else:
            connection.execute(
                "insert into tombstone(workspace_id,scope,requested_by,reason) "
                "values(%s,'workspace',%s,'private fixture erasure')",
                (workspace, actor),
            )
        for table in (
            "world_draft_request",
            "world_draft_input",
            "world_draft_progress",
            "world_draft_attempt",
            "world_draft_outcome",
            "world_made_from",
        ):
            assert connection.execute(f"select 1 from {table}").fetchall() == []
        (anchor,) = connection.execute("select * from world_draft_start").fetchall()
        assert "terms_sha256" not in anchor and anchor["draft_id"] == uuid.UUID(ident)
        assert connection.execute("select 1 from world_draft_bound").fetchall()
        assert (
            connection.execute("select payload from job where kind='world_draft'").fetchone()[
                "payload"
            ]
            == {}
        )
    assert client.get(f"/worlds/drafts/{ident}", headers=HEADERS).status_code == 404
    retried = client.post("/worlds/drafts", headers=HEADERS, json=body)
    assert retried.status_code == 404, retried.text
    assert len(transport.requests) == before
    assert (
        bench.query(
            "select reservation_id,state,reserved_usd,settled_usd "
            "from spending_reservation order by reservation_id"
        )
        == liabilities
    )


def test_unconfirmed_changed_or_malformed_operation_never_starts_a_native_job(native_draft):
    from copy import deepcopy

    client, transport, bench, _workspace, _services = native_draft
    prepared = client.post(
        "/selection/world-drafts/prepare", headers=HEADERS, json={"description": native.TOWN_WORDS}
    ).json()
    step = prepared["steps"][0]
    before = client.post(
        "/selection/world-drafts/outcome", headers=HEADERS, json={"plan": prepared}
    )
    assert before.status_code == 200 and before.json()["state"] == "not_started"
    forged = deepcopy(step["body"])
    forged["operation"]["maximum_usd"] = "0.000001"
    refused = client.post("/worlds/drafts", headers=HEADERS, json=forged)
    assert refused.status_code == 409 and refused.json()["code"] == "world_draft_operation_changed"
    malformed = deepcopy(step["body"])
    malformed["operation"]["maximum_usd"] = 1.1
    assert client.post("/worlds/drafts", headers=HEADERS, json=malformed).status_code == 422
    bad_plan = deepcopy(prepared)
    bad_plan["unsupported_float"] = 1.1
    assert (
        client.post(
            "/selection/world-drafts/outcome", headers=HEADERS, json={"plan": bad_plan}
        ).status_code
        == 422
    )
    assert bench.query("select 1 from job where kind='world_draft'") == []
    assert transport.requests == []
