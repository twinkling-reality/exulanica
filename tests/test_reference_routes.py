"""``/worlds/references``: asking for notes, reading them as they come, stopping, and when it is not
offered. The worker is not started here (the application's lifespan is not entered); these are the
routes. A saved person and place are in the description, and neither may reach the job."""

from __future__ import annotations

import dataclasses
import json
import uuid
from types import SimpleNamespace

import pytest
from exulanica.api import permissions
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.references import store
from exulanica.references.adapters import ReferenceSourceUnavailable
from exulanica.references.adapters.tavily import TavilySearch
from fastapi.testclient import TestClient
from psycopg.rows import tuple_row

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from model_fakes import FakeTransport
from test_companion_saved_names import PERSON, PLACE
from test_companion_saved_names import named as saved_named  # noqa: F401
from tests_support_api import EVERY_PERMISSION, scratch_database

pytestmark = pytest.mark.postgres

TOKEN = "references-owner-token-at-least-32-chars"
NO_MODEL_TOKEN = "references-no-model-token-at-least-32-chars"
STRANGER_TOKEN = "references-stranger-token-at-least-32-chars"
DESCRIPTION = f"a harbour town where {PERSON} lives beside {PLACE}"


@pytest.fixture(name="named")
def _named_alias(request):
    return request.getfixturevalue("saved_named")


@pytest.fixture
def api(named, spine_schema, monkeypatch):
    _psycopg, scratch = spine_schema
    repository, content_store, _session, _entities = named
    repository.connection.commit()
    workspace_id = repository.workspace_id
    grant = {"workspace_id": str(workspace_id), "actor": str(uuid.uuid4())}
    no_model = [p for p in EVERY_PERMISSION if p != str(permissions.Permission.MODEL_INVOKE)]
    stranger = {"workspace_id": str(uuid.uuid4()), "actor": str(uuid.uuid4())}
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {**grant, "permissions": EVERY_PERMISSION},
                NO_MODEL_TOKEN: {**grant, "permissions": no_model},
                STRANGER_TOKEN: {**stranger, "permissions": EVERY_PERMISSION},
            }
        ),
    )
    database = scratch_database(scratch)
    services = Services(
        database=database,
        readonly_database=database,
        store=content_store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=ModelClient(
            api_key="test-key-not-real",
            transport=FakeTransport(),
            budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        ),
        runs_reference_worker=True,
        reference_workspaces=(workspace_id,),
        reference_adapter_for=lambda source: TavilySearch(
            source, transport=FakeTransport(), credential="tvly-test"
        ),
        spending=SimpleNamespace(for_workspace=lambda workspace: None),
    )

    def client(**changes) -> TestClient:
        return TestClient(create_app(dataclasses.replace(services, **changes), verify=False))

    return client, repository


def _post(client: TestClient, token: str = TOKEN, **body):
    payload = {"purpose": "kind", "description": DESCRIPTION, "web": True, **body}
    return client.post(
        "/worlds/references", json=payload, headers={"Authorization": f"Bearer {token}"}
    )


def _get(client: TestClient, path: str, token: str = TOKEN):
    return client.get(path, headers={"Authorization": f"Bearer {token}"})


def test_a_request_is_queued_at_once_with_no_saved_name_in_its_job(api) -> None:
    client, repository = api
    answered = _post(client())
    assert answered.status_code == 202
    view = answered.json()
    assert (view["status"], view["steps"], view["notes"]) == ("queued", [], [])
    payload = (
        repository.connection.cursor(row_factory=tuple_row)
        .execute(
            "select j.payload from job j join reference_request r on r.job_id = j.job_id "
            "where r.reference_id = %s",
            (uuid.UUID(view["reference_id"]),),
        )
        .fetchone()[0]
    )
    assert PERSON not in payload["description"] and PLACE not in payload["description"]
    assert payload["description"].startswith("a harbour town where [person ")


def test_an_idempotency_key_answers_with_the_first_request_or_refuses_another_body(api) -> None:
    client = api[0]()
    key = str(uuid.uuid4())
    first = _post(client, idempotency_key=key)
    again = _post(client, idempotency_key=key)
    other = _post(client, idempotency_key=key, description="a mountain village")
    assert (first.status_code, again.status_code) == (202, 200)
    assert first.json()["reference_id"] == again.json()["reference_id"]
    assert (other.status_code, other.json()["code"]) == (409, "idempotency_key_reused")


def test_a_request_is_read_listed_and_stopped_in_its_own_workspace_only(api) -> None:
    client = api[0]()
    made = _post(client).json()
    path = f"/worlds/references/{made['reference_id']}"
    assert _get(client, path).json()["status"] == "queued"
    listed = _get(client, "/worlds/references").json()
    assert [view["reference_id"] for view in listed["references"]] == [made["reference_id"]]
    (capability,) = listed["capabilities"]
    assert (capability["operation"], capability["state"], capability["code"]) == (
        "POST /worlds/references",
        "available",
        None,
    )
    assert capability["spends"] and capability["idempotency"] == "idempotency_key"
    stranger = _get(client, path, token=STRANGER_TOKEN)
    assert (stranger.status_code, stranger.json()["code"]) == (404, "reference_not_found")
    stopped = client.post(f"{path}/cancel", headers={"Authorization": f"Bearer {TOKEN}"})
    assert stopped.json()["status"] == "cancelled"
    assert _get(client, f"/worlds/references/{uuid.uuid4()}").status_code == 404


def test_a_request_serves_our_search_record_and_never_the_query_text(api) -> None:
    client, repository = api
    made = _post(client()).json()
    connection = repository.connection
    claimed = store.claim(connection, repository.workspace_id, worker="test")
    store.record_lookup(
        connection,
        claimed,
        source="tavily_search",
        aspect="buildings",
        query="whitewashed island houses",
        outcome="answered",
        credits=1,
        result_count=5,
        provider_request_id="123e4567-e89b-12d3-a456-426614174111",
    )
    served = _get(client(), f"/worlds/references/{made['reference_id']}")
    (search,) = served.json()["searches"]
    assert set(search) == {"source", "outcome", "result_count", "credits", "sent_at"}
    assert (search["source"], search["credits"]) == ("tavily_search", 1)
    assert "whitewashed island houses" not in served.text
    assert "123e4567" not in served.text


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"reference_workspaces": ()}, "references_operator_only"),
        (
            {"installation": SimpleNamespace(profile=SimpleNamespace(id="public"))},
            "references_operator_only",
        ),
        ({"runs_reference_worker": False}, "references_not_run_here"),
        ({"model_client": None}, "references_not_run_here"),
        ({"spending": None}, "reference_budget_unavailable"),
        ({"reference_adapter_for": None}, "references_not_configured"),
    ],
)
def test_where_web_notes_are_not_offered_nothing_is_queued_and_the_reason_is_named(
    api, changes, code
) -> None:
    client, repository = api
    refused = _post(client(**changes))
    assert (refused.status_code, refused.json()["code"]) == (409, code)
    count = repository.connection.cursor(row_factory=tuple_row).execute(
        "select count(*) from reference_request"
    )
    assert count.fetchone()[0] == 0


def test_a_source_without_its_configuration_is_named_not_configured(api) -> None:
    def unconfigured(source):
        raise ReferenceSourceUnavailable("references_not_configured", "no key", charged=False)

    client = api[0](reference_adapter_for=unconfigured)
    listed = _get(client, "/worlds/references").json()
    (capability,) = listed["capabilities"]
    assert (capability["state"], capability["code"]) == ("unavailable", "references_not_configured")


def test_web_notes_are_asked_for_explicitly_and_need_the_model_grant(api) -> None:
    client = api[0]()
    assert _post(client, web=False).status_code == 422
    assert _post(client, web=None).status_code == 422
    assert _post(client, token=NO_MODEL_TOKEN).status_code == 403


def test_an_unlisted_workspace_is_told_web_notes_are_operator_only(api) -> None:
    client = api[0](reference_workspaces=())
    (capability,) = _get(client, "/worlds/references").json()["capabilities"]
    assert (capability["state"], capability["code"]) == ("unavailable", "references_operator_only")
