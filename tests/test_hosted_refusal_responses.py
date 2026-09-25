"""A hosted request the boundary stops reaches the route's caller as a named problem.

Two refusals can stop a request after a route has decided to send it, and neither is a model's
answer. The account holder's rules can refuse it as it leaves
(:class:`~exulanica.models.policy.HostedRequestRefused`), and a client nobody attached the
workspace's rules to refuses to send at all
(:class:`~exulanica.models.policy.NoHostedRequestPolicy`). Each reaches the caller in the
application's ``{code, detail}`` shape with a status that says what happened, never as the
unnamed 500 an unhandled exception is. Each is driven through a real route of the real
application, and each run shows that nothing reached the transport.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.migrate import provision_workspace
from exulanica.errors import PrivacyAdmissionError
from exulanica.models.client import ModelClient
from exulanica.selection.plan import Intent, SelectionPlan
from fastapi.testclient import TestClient

from model_fakes import FakeTransport
from test_companion_saved_names import named
from tests_support_api import EVERY_PERMISSION, scratch_database
from world_support import registered_world

pytestmark = pytest.mark.postgres

__all__ = ["named"]

OWNER = "hosted-refusal-owner-token-that-is-long-enough-to-be-accepted"
AUTH = {"Authorization": f"Bearer {OWNER}"}


@dataclass
class Site:
    http: TestClient
    transport: FakeTransport
    #: The world the Companion is asked in.
    world_id: str


@pytest.fixture
def site(named, spine_schema, tmp_path, monkeypatch) -> Iterator[Site]:
    """The application over one named photograph, with a model whose every request is recorded.

    Built with ``raise_server_exceptions=False``, so an unhandled exception is answered as a caller
    would see it rather than raised into the test.
    """
    repository, store, session, _ = named
    provision_workspace(repository.connection, repository.workspace_id)
    world_id = registered_world(repository.connection, repository.workspace_id)
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                OWNER: {
                    "workspace_id": str(repository.workspace_id),
                    "actor": str(session.actor),
                    "permissions": EVERY_PERMISSION,
                }
            }
        ),
    )
    transport = FakeTransport()
    database = scratch_database(spine_schema[1])
    services = Services(
        database=database,
        readonly_database=database,
        store=store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=ModelClient(api_key="test-key-not-real", transport=transport),
    )
    with TestClient(create_app(services, verify=False), raise_server_exceptions=False) as http:
        yield Site(http, transport, world_id)


def test_a_request_the_account_holders_rules_refuse_as_it_leaves_is_a_named_conflict(
    site, monkeypatch
):
    """The composer's request is refused at the boundary, after the route's own check passed.

    That is the order of a right that ends while a question is being answered: the route asks
    before it composes and the boundary asks again as the request leaves. The boundary's check is
    made to find the right ended; the route's check is the product's and passes.
    """
    import exulanica.api.services as services_module

    def ended(connection, workspace_id, captures, handoff):
        raise PrivacyAdmissionError("the personal model right for this photograph has ended")

    monkeypatch.setattr(services_module, "photograph_text_right", ended)
    plan = SelectionPlan(intent=Intent.CAPTURES, semantic_query="running club")

    response = site.http.post(
        f"/selection/ask?world_id={site.world_id}",
        headers=AUTH,
        json={
            "question": "Where does the running club meet?",
            "plan": plan.model_dump(mode="json"),
        },
    )

    assert response.status_code == 409, response.text
    body = response.json()
    # The execution record says the question paid for nothing: the refused request never left.
    assert set(body) == {"code", "detail", "execution"}
    assert body["execution"]["calls"] == []
    assert body["code"] == "hosted_request_refused"
    assert "reasoning_cheap" in body["detail"] and "has ended" in body["detail"]
    assert site.transport.requests == [], "a refused request reached the transport"


def test_a_route_sending_through_a_client_with_no_policy_is_a_named_fault(site, monkeypatch):
    """A route whose client carries no policy: the fault a missing binding would be.

    ``Services.hosted_model`` is made to hand the route the process's client as it is built,
    without the workspace's rules, which is what a route that skipped the binding would send
    through.
    """
    monkeypatch.setattr(
        Services, "hosted_model", lambda self, connection, workspace_id: self.model_client
    )

    response = site.http.post("/selection/plan", headers=AUTH, json={"question": "where was I?"})

    assert response.status_code == 500, response.text
    body = response.json()
    assert set(body) == {"code", "detail"}
    assert body["code"] == "no_hosted_request_policy"
    assert "no hosted-request policy" in body["detail"]
    assert site.transport.requests == [], "a client with no policy sent something"
