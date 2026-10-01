"""The durable spending authority at the API: the workspace's status, and a refusal's problem.

``GET /spending`` reads the caller's own workspace, named by its grant, with ``operations.read``:
a monitoring token sees spending without being able to spend. A route that asks a model for a
workspace with no allowance answers 429 ``budget_exceeded`` as a process ceiling always has, with
a ``spending`` member saying which allowance refused and whether asking again can succeed, and
nothing reaches the transport.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.models.client import ModelClient
from exulanica.models.usage import usd_string
from exulanica.orchestration.judge_seed import JUDGE_ROLE, mint_judge_token, provision_judge_role
from exulanica.spending.ledger import DurableSpending
from exulanica.store.local import LocalContentAddressedStore
from fastapi.testclient import TestClient
from psycopg import sql

from conftest import scratch_role_database
from model_fakes import FakeTransport
from spending_support import (
    MESSAGES,
    ROLE,
    WorkspacePolicy,
    bench,
    no_usage_body,
    one_reservation,
    spending_client,
)
from tests_support_api import EVERY_PERMISSION

__all__ = ["bench"]

pytestmark = pytest.mark.postgres

OWNER = "spending-route-owner-token-long-enough-to-be-accepted-here"
MONITOR = "spending-route-monitor-token-long-enough-to-be-accepted-too"
NEIGHBOUR = "spending-route-neighbour-token-long-enough-to-be-accepted-as"
READER = "spending-route-reader-token-long-enough-to-be-accepted-as-well"


@dataclass
class Site:
    http: TestClient
    transport: FakeTransport
    workspace: uuid.UUID
    neighbour: uuid.UUID
    durable: DurableSpending


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def site(bench, tmp_path) -> Iterator[Site]:
    workspace, neighbour = uuid.uuid4(), uuid.uuid4()
    grants = {
        OWNER: {"workspace_id": str(workspace), "permissions": EVERY_PERMISSION},
        MONITOR: {"workspace_id": str(workspace), "permissions": ["operations.read"]},
        NEIGHBOUR: {"workspace_id": str(neighbour), "permissions": ["operations.read"]},
        READER: {"workspace_id": str(workspace), "permissions": ["world.read"]},
    }
    for grant in grants.values():
        grant["actor"] = str(uuid.uuid4())
    transport = FakeTransport()
    durable = bench.durable("api")
    services = Services(
        database=bench.runtime,
        readonly_database=bench.runtime,
        store=LocalContentAddressedStore(tmp_path / "blobs"),
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)}),
        executor_shares_the_write_role=True,
        model_client=ModelClient(
            api_key="test-key-not-real", transport=transport
        ).with_spending_source(durable),
        spending_mode="durable",
        spending=durable,
    )
    with TestClient(create_app(services, verify=False), raise_server_exceptions=False) as http:
        yield Site(http, transport, workspace, neighbour, durable)


def test_the_status_is_the_callers_workspace_own_with_operations_read(site, bench):
    authority = bench.issue()
    bench.grant(authority, site.workspace, ceiling="0.004", calls=7)
    bench.grant(authority, site.neighbour, ceiling="0.009", calls=9)
    response = site.http.get("/spending", headers=_auth(MONITOR))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "durable"
    assert body["workspace_id"] == str(site.workspace)
    (entry,) = body["providers"]
    assert entry["grant"]["ceiling_usd"] == "0.00400000"
    assert entry["available_calls"] == 7
    assert "0.009" not in response.text
    neighbour = site.http.get("/spending", headers=_auth(NEIGHBOUR)).json()
    assert neighbour["providers"][0]["grant"]["ceiling_usd"] == "0.00900000"
    refused = site.http.get("/spending", headers=_auth(READER))
    assert (refused.status_code, refused.json()["code"]) == (403, "not_authorised")


def test_a_route_asking_a_model_without_an_allowance_is_refused_by_name(site, bench):
    bench.issue()
    response = site.http.post(
        "/selection/plan", headers=_auth(OWNER), json={"question": "where was I?"}
    )
    assert response.status_code == 429, response.text
    body = response.json()
    assert body["code"] == "budget_exceeded"
    assert body["spending"] == {
        "reason": "spending_not_granted",
        "scope": "workspace",
        "retry": "never",
    }
    assert "No request was sent" in body["detail"]
    assert site.transport.requests == [], "a refused request reached the transport"


def test_a_judge_deployment_reads_its_workspace_spending(bench, tmp_path):
    """A judge deployment's API connects as the role ``provision_judge_role`` makes, and a judge
    token holds ``operations.read``: its status reads the authority's state through the facts
    function, as the runtime's does, and answers."""
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    role = f"{JUDGE_ROLE}_spending_{uuid.uuid4().hex[:8]}"
    with bench.admin.unscoped() as connection:
        provision_judge_role(connection, role=role)
    try:
        judge = scratch_role_database(bench.scratch, role)
        token = f"judge-{uuid.uuid4().hex}{uuid.uuid4().hex}"
        directory = mint_judge_token(workspace_id=workspace, actor=uuid.uuid4(), token=token)
        services = Services(
            database=judge,
            readonly_database=judge,
            store=LocalContentAddressedStore(tmp_path / "judge-blobs"),
            tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(directory)}),
            executor_shares_the_write_role=True,
            model_client=None,
        )
        with TestClient(create_app(services, verify=False), raise_server_exceptions=False) as http:
            response = http.get("/spending", headers=_auth(token))
        assert response.status_code == 200, response.text
        (entry,) = response.json()["providers"]
        assert (entry["grant"]["state"], entry["authority_state"]) == ("active", "active")
    finally:
        with bench.admin.unscoped() as connection:
            connection.execute(sql.SQL("drop owned by {}").format(sql.Identifier(role)))
            connection.execute(sql.SQL("drop role {}").format(sql.Identifier(role)))


def test_no_answer_to_a_workspace_states_the_authority_figures(bench, tmp_path):
    """An authority's ceiling and what it has committed are every workspace's spending together.
    The process that admits receives them, for its witness; no HTTP answer states them: not a
    refusal by the authority, not the workspace's status, not readiness."""
    one = one_reservation()
    ceiling = one * 2 + Decimal("0.00000011")
    authority = bench.issue(ceiling=ceiling, calls=100)
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    bench.grant(authority, mine, ceiling=one * 2 - Decimal("0.00000005"), calls=40)
    bench.grant(authority, theirs, ceiling=ceiling, calls=40)
    spent = FakeTransport()
    spent.default = no_usage_body()
    theirs_client = spending_client(bench.durable("theirs"), spent)
    for _ in range(2):
        theirs_client.with_policy(WorkspacePolicy(theirs)).chat(
            ROLE, MESSAGES, prompt_version="authority-figures", use_cache=False
        )
    committed = bench.state(authority)["committed_usd"]
    assert committed == one * 2
    figures = {usd_string(ceiling), usd_string(committed)}

    token = "spending-figures-owner-token-long-enough-to-be-accepted"
    grants = {
        token: {
            "workspace_id": str(mine),
            "actor": str(uuid.uuid4()),
            "permissions": EVERY_PERMISSION,
        }
    }
    transport = FakeTransport()
    durable = bench.durable("api")
    services = Services(
        database=bench.runtime,
        readonly_database=bench.runtime,
        store=LocalContentAddressedStore(tmp_path / "figures-blobs"),
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)}),
        executor_shares_the_write_role=True,
        model_client=ModelClient(
            api_key="test-key-not-real", transport=transport
        ).with_spending_source(durable),
        spending_mode="durable",
        spending=durable,
    )
    with TestClient(create_app(services, verify=False), raise_server_exceptions=False) as http:
        answers = [
            http.post("/selection/plan", headers=_auth(token), json={"question": "where was I?"}),
            http.get("/spending", headers=_auth(token)),
            http.get("/readyz"),
        ]
    refused = answers[0]
    assert refused.status_code == 429, refused.text
    assert (refused.json()["spending"]["reason"], refused.json()["spending"]["scope"]) == (
        "spending_limit_reached",
        "authority",
    )
    assert transport.call_count == 0
    assert answers[1].status_code == 200, answers[1].text
    for answer in answers:
        said = answer.text + json.dumps(dict(answer.headers))
        for figure in figures:
            assert figure not in said, (str(answer.request.url), figure)
