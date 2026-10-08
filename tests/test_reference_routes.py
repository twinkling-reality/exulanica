"""``/worlds/references``: asking for notes, reading them as they come, stopping, and when it is not
offered. The worker is not started here (the application's lifespan is not entered); its thread is
stood in for, alive or not. These are the routes, served as the runtime and read-only roles a
deployment uses, with the workspace's grant for the source issued by the spending operator. A saved
person and place are in the description, and neither may reach the job."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from exulanica.api import permissions
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.routes import references as references_route
from exulanica.api.services import Services
from exulanica.db.roles import provision_runtime_role
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.references import store
from exulanica.references.adapters import ReferenceSourceUnavailable
from exulanica.references.adapters.tavily import TavilySearch
from fastapi.testclient import TestClient
from psycopg.rows import tuple_row

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS, scratch_role_database
from model_fakes import FakeTransport
from spending_support import RUNTIME_ROLE
from spending_support import bench as spending_bench  # noqa: F401
from test_companion_saved_names import PERSON, PLACE
from test_companion_saved_names import named as saved_named  # noqa: F401
from tests_support_api import EVERY_PERMISSION

pytestmark = pytest.mark.postgres

TOKEN = "references-owner-token-at-least-32-chars"
NO_MODEL_TOKEN = "references-no-model-token-at-least-32-chars"
NO_REFERENCES_TOKEN = "references-no-grant-token-at-least-32-chars"
OTHER_ACTOR_TOKEN = "references-other-actor-token-at-least-32-chars"
STRANGER_TOKEN = "references-stranger-token-at-least-32-chars"
DESCRIPTION = f"a harbour town where {PERSON} lives beside {PLACE}"
READ_ONLY_ROLE = "exulanica_references_ro_suite"
#: The actor TOKEN and its narrower siblings name.
ACTOR = uuid.UUID("7a1c2e3d-4b5f-4a60-9c71-8d9e0f1a2b3c")


@pytest.fixture(name="named")
def _named_alias(request):
    return request.getfixturevalue("saved_named")


@pytest.fixture(name="bench")
def _bench_alias(request):
    return request.getfixturevalue("spending_bench")


class _Alive:
    """The worker's thread, as the routes ask after it."""

    def __init__(self, alive: bool = True) -> None:
        self.alive = alive

    def is_alive(self) -> bool:
        return self.alive


def _grant_tavily(bench, workspace_id: uuid.UUID, *, calls: int = 30) -> None:
    now = dt.datetime.now(dt.UTC)
    authority = bench.operator.issue(
        provider="tavily_search",
        ceiling_usd=Decimal("0.01"),
        max_calls=calls,
        valid_until=now + dt.timedelta(days=30),
        operator="test-operator",
        reason="the operator's Tavily credits, for a test",
    )
    bench.operator.grant(
        authority,
        workspace_id,
        ceiling_usd=Decimal("0.01"),
        max_calls=calls,
        valid_until=now + dt.timedelta(days=29),
        operator="test-operator",
        reason="a test grant",
    )


@pytest.fixture
def api(named, bench, spine_schema, monkeypatch):
    _psycopg, scratch = spine_schema
    repository, content_store, _session, _entities = named
    repository.connection.commit()
    workspace_id = repository.workspace_id
    grant = {"workspace_id": str(workspace_id), "actor": str(ACTOR)}
    no_model = [p for p in EVERY_PERMISSION if p != str(permissions.Permission.MODEL_INVOKE)]
    no_references = [
        p for p in EVERY_PERMISSION if p != str(permissions.Permission.REFERENCES_REQUEST)
    ]
    other_actor = {"workspace_id": str(workspace_id), "actor": str(uuid.uuid4())}
    stranger = {"workspace_id": str(uuid.uuid4()), "actor": str(uuid.uuid4())}
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {**grant, "permissions": EVERY_PERMISSION},
                NO_MODEL_TOKEN: {**grant, "permissions": no_model},
                NO_REFERENCES_TOKEN: {**grant, "permissions": no_references},
                OTHER_ACTOR_TOKEN: {**other_actor, "permissions": EVERY_PERMISSION},
                STRANGER_TOKEN: {**stranger, "permissions": EVERY_PERMISSION},
            }
        ),
    )
    provision_runtime_role(repository.connection, role=READ_ONLY_ROLE, read_only=True)
    readonly = scratch_role_database(scratch, READ_ONLY_ROLE)
    _grant_tavily(bench, workspace_id)
    services = Services(
        database=bench.runtime,
        readonly_database=readonly,
        store=content_store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=False,
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
        spending=bench.durable(),
    )

    def client(*, alive: bool = True, **changes) -> TestClient:
        app = create_app(dataclasses.replace(services, **changes), verify=False)
        app.state.reference_thread = _Alive(alive)
        return TestClient(app)

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


def test_a_request_is_read_listed_and_stopped_by_its_requester_only(api) -> None:
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
    for token in (STRANGER_TOKEN, OTHER_ACTOR_TOKEN):
        elsewhere = _get(client, path, token=token)
        assert (elsewhere.status_code, elsewhere.json()["code"]) == (404, "unknown_reference")
        stop = client.post(f"{path}/cancel", headers={"Authorization": f"Bearer {token}"})
        assert (stop.status_code, stop.json()["code"]) == (404, "unknown_reference")
    assert _get(client, "/worlds/references", token=OTHER_ACTOR_TOKEN).json()["references"] == []
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
        ({"alive": False}, "references_not_run_here"),
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


def test_web_notes_are_asked_for_explicitly_and_need_the_model_and_references_grants(api) -> None:
    client = api[0]()
    assert _post(client, web=False).status_code == 422
    assert _post(client, web=None).status_code == 422
    assert _post(client, token=NO_MODEL_TOKEN).status_code == 403
    assert _post(client, token=NO_REFERENCES_TOKEN).status_code == 403
    assert permissions.Permission.REFERENCES_REQUEST in permissions.ACCOUNT_OWNER_PERMISSIONS


def test_an_unlisted_workspace_is_told_web_notes_are_operator_only(api) -> None:
    client = api[0](reference_workspaces=())
    (capability,) = _get(client, "/worlds/references").json()["capabilities"]
    assert (capability["state"], capability["code"]) == ("unavailable", "references_operator_only")


def test_the_routes_are_served_as_the_runtime_and_read_only_roles(api, bench) -> None:
    client, _repository = api
    with bench.runtime.session(uuid.uuid4()) as connection:
        assert connection.execute("select current_user as who").fetchone()["who"] == RUNTIME_ROLE
    made = _post(client())
    assert made.status_code == 202
    assert _get(client(), f"/worlds/references/{made.json()['reference_id']}").status_code == 200


def test_without_a_grant_for_the_source_nothing_is_queued_and_the_capability_says_so(
    named, bench, spine_schema, monkeypatch
) -> None:
    # A workspace of its own, listed but never granted the source.
    repository = named[0]
    ungranted = uuid.uuid4()
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {
                    "workspace_id": str(ungranted),
                    "actor": str(uuid.uuid4()),
                    "permissions": EVERY_PERMISSION,
                }
            }
        ),
    )
    from exulanica.db.migrate import provision_workspace
    from exulanica.db.session import set_workspace

    set_workspace(repository.connection, ungranted)
    provision_workspace(repository.connection, ungranted)
    set_workspace(repository.connection, repository.workspace_id)
    services = Services(
        database=bench.runtime,
        readonly_database=bench.runtime,
        store=named[1],
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=ModelClient(
            api_key="test-key-not-real",
            transport=FakeTransport(),
            budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        ),
        runs_reference_worker=True,
        reference_workspaces=(ungranted,),
        reference_adapter_for=lambda source: TavilySearch(
            source, transport=FakeTransport(), credential="tvly-test"
        ),
        spending=bench.durable(),
    )
    app = create_app(services, verify=False)
    app.state.reference_thread = _Alive()
    client = TestClient(app)
    refused = _post(client)
    assert (refused.status_code, refused.json()["code"]) == (409, "reference_budget_unavailable")
    (capability,) = _get(client, "/worlds/references").json()["capabilities"]
    assert capability["code"] == "reference_budget_unavailable"


def test_one_requester_holds_at_most_two_open_requests(api) -> None:
    client = api[0]()
    assert [_post(client).status_code for _ in range(2)] == [202, 202]
    third = _post(client)
    assert (third.status_code, third.json()["code"]) == (429, "reference_limit_reached")
    # Another requester in the workspace is counted apart.
    assert _post(client, token=OTHER_ACTOR_TOKEN).status_code == 202


def test_a_control_character_is_refused_by_name_and_nothing_is_queued(api) -> None:
    client, repository = api
    refused = _post(client(), description="a harbour\x00town")
    assert (refused.status_code, refused.json()["code"]) == (422, "description_control_character")
    count = repository.connection.cursor(row_factory=tuple_row).execute(
        "select count(*) from reference_request"
    )
    assert count.fetchone()[0] == 0
    assert _post(client(), description="a harbour town\nwith a quay").status_code == 202


def test_a_description_that_grows_past_its_bound_once_names_are_replaced_is_refused(
    api, monkeypatch
) -> None:
    from exulanica.selection.world_drafting import SentDescription

    grown = SentDescription(
        text="x" * (store.MAX_DESCRIPTION_CHARACTERS + 1), placeholders={}, typed="", replaced=()
    )
    monkeypatch.setattr(references_route, "sendable", lambda connection, workspace, text: grown)
    refused = _post(api[0]())
    assert (refused.status_code, refused.json()["code"]) == (422, "description_too_long")


def test_a_catalog_with_no_web_source_offers_none(api, monkeypatch) -> None:
    monkeypatch.setattr(references_route, "web_source", lambda: None)
    (capability,) = _get(api[0](), "/worlds/references").json()["capabilities"]
    assert capability["code"] == "references_not_configured"


def test_the_startup_sweep_ends_the_jobs_of_a_workspace_no_longer_served(api) -> None:
    client_for, repository = api
    made = _post(client_for()).json()
    services = client_for().app.state.services
    unserving = dataclasses.replace(services, reference_workspaces=())
    assert unserving.sweep_references() == 1
    ended = store.read_request(
        repository.connection, repository.workspace_id, uuid.UUID(made["reference_id"])
    )
    assert (ended.status, ended.failure) == ("failed", "not_served")
    payload = (
        repository.connection.cursor(row_factory=tuple_row)
        .execute("select payload from job where job_id=%s", (ended.job_id,))
        .fetchone()[0]
    )
    assert payload == {"reference_id": made["reference_id"]}


def test_a_queued_request_of_a_workspace_dropped_from_the_list_ends_when_it_next_reads(
    api,
) -> None:
    client_for, repository = api
    made = _post(client_for()).json()
    _get(client_for(reference_workspaces=()), "/worlds/references")
    ended = store.read_request(
        repository.connection, repository.workspace_id, uuid.UUID(made["reference_id"])
    )
    assert (ended.status, ended.failure) == ("failed", "not_served")


# -- a person's own pictures ---------------------------------------------------------------------

PICTURE = uuid.UUID("5b1d7c2e-4a3f-4e86-9b0d-1c2e3f4a5b61")
SECOND = uuid.UUID("5b1d7c2e-4a3f-4e86-9b0d-1c2e3f4a5b62")


def _admit_every_picture(monkeypatch) -> list[uuid.UUID]:
    """Every named picture reads as screened and covered by a right; the pictures asked after."""
    asked: list[uuid.UUID] = []

    def admitted(connection, workspace_id, capture_id, requester):
        # Asked for the person making the request: the token's actor.
        assert requester == ACTOR
        asked.append(capture_id)
        return None, object(), (uuid.uuid4(),)

    monkeypatch.setattr(references_route, "picture_refusal", admitted)
    return asked


def _requests(repository) -> int:
    count = repository.connection.cursor(row_factory=tuple_row).execute(
        "select count(*) from reference_request"
    )
    return count.fetchone()[0]


def test_pictures_are_not_offered_unless_turned_on_and_the_list_says_nothing_of_their_uses(
    api,
) -> None:
    client, repository = api
    listed = _get(client(), "/worlds/references").json()
    assert listed["pictures"] == {
        "offered": False,
        "code": "reference_pictures_not_offered",
        "maximum": 4,
    }
    refused = _post(client(), pictures=[str(PICTURE)])
    assert (refused.status_code, refused.json()["code"]) == (409, "reference_pictures_not_offered")
    assert _requests(repository) == 0


def test_where_pictures_are_on_the_list_offers_exactly_the_reference_picture_uses(api) -> None:
    from exulanica.ingest.personal_admission import MODEL_RIGHT_USES_PATH

    raw = json.loads(MODEL_RIGHT_USES_PATH.read_text(encoding="utf-8"))
    declared = [use for use in raw["uses"] if use.get("offered_on") == "reference_pictures"]
    pictures = _get(api[0](reference_pictures=True), "/worlds/references").json()["pictures"]
    assert (pictures["offered"], pictures["code"], pictures["maximum"]) == (True, None, 4)
    uses = pictures["consent"]["uses"]
    assert (
        [use["role"] for use in uses] == [use["role"] for use in declared] == ["reference_vision"]
    )
    for use, stated in zip(uses, declared, strict=True):
        assert use["offered_on"] == "reference_pictures"
        assert (use["label"], use["stop"]) == (stated["label"], stated["stop"])
        assert stated["purpose"] in use["notice"]


def test_pictures_turned_on_still_follow_the_reference_offer(api) -> None:
    pictures = _get(
        api[0](reference_pictures=True, runs_reference_worker=False), "/worlds/references"
    ).json()["pictures"]
    assert (pictures["offered"], pictures["code"]) == (False, "reference_pictures_not_offered")
    assert "consent" not in pictures
    stopped = _get(api[0](reference_pictures=True, alive=False), "/worlds/references").json()
    assert (stopped["pictures"]["offered"], stopped["pictures"]["code"]) == (
        False,
        "references_not_run_here",
    )


def test_a_picture_without_a_screening_and_a_right_is_refused_and_nothing_is_queued(api) -> None:
    client, repository = api
    refused = _post(client(reference_pictures=True), pictures=[str(PICTURE)])
    assert (refused.status_code, refused.json()["code"]) == (409, "reference_picture_not_admitted")
    assert "picture_not_screened" in refused.json()["detail"]
    assert _requests(repository) == 0


def test_notes_from_pictures_alone_need_no_search_grant_or_adapter(api, monkeypatch) -> None:
    client, repository = api
    asked = _admit_every_picture(monkeypatch)
    monkeypatch.setattr(references_route, "_granted", lambda services, workspace, provider: False)
    on = {"reference_pictures": True, "reference_adapter_for": None}
    web = _post(client(**on))
    assert (web.status_code, web.json()["code"]) == (409, "reference_budget_unavailable")
    made = _post(client(**on), web=False, pictures=[str(SECOND), str(PICTURE)])
    assert made.status_code == 202, made.text
    assert (made.json()["web"], asked) == (False, [SECOND, PICTURE])
    payload = (
        repository.connection.cursor(row_factory=tuple_row)
        .execute(
            "select j.payload from job j join reference_request r on r.job_id = j.job_id "
            "where r.reference_id = %s",
            (uuid.UUID(made.json()["reference_id"]),),
        )
        .fetchone()[0]
    )
    assert payload["pictures"] == [str(SECOND), str(PICTURE)]
    # Durable spending is still needed: a picture's reading is a model call.
    spent = _post(client(**on, spending=None), web=False, pictures=[str(PICTURE)])
    assert (spent.status_code, spent.json()["code"]) == (409, "reference_budget_unavailable")


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"web": False}, "nothing_to_look_up"),
        ({"web": False, "pictures": None}, "nothing_to_look_up"),
        ({"pictures": [str(PICTURE), str(PICTURE)]}, "pictures_repeated"),
    ],
)
def test_a_request_names_something_to_look_up_and_each_picture_once(
    api, monkeypatch, body, code
) -> None:
    client, repository = api
    _admit_every_picture(monkeypatch)
    refused = _post(client(reference_pictures=True), **body)
    assert (refused.status_code, refused.json()["code"]) == (422, code)
    assert _requests(repository) == 0


@pytest.mark.parametrize("count", [0, 5])
def test_a_request_names_one_to_four_pictures(api, monkeypatch, count) -> None:
    _admit_every_picture(monkeypatch)
    named = [str(uuid.uuid4()) for _ in range(count)]
    assert _post(api[0](reference_pictures=True), pictures=named).status_code == 422


def test_an_idempotency_key_tells_requests_apart_by_their_pictures(api, monkeypatch) -> None:
    _admit_every_picture(monkeypatch)
    client = api[0](reference_pictures=True)
    key = str(uuid.uuid4())
    first = _post(client, idempotency_key=key, pictures=[str(PICTURE)])
    again = _post(client, idempotency_key=key, pictures=[str(PICTURE)])
    other = _post(client, idempotency_key=key, pictures=[str(SECOND)])
    assert (first.status_code, again.status_code) == (202, 200)
    assert (other.status_code, other.json()["code"]) == (409, "idempotency_key_reused")


def test_a_request_without_pictures_keeps_the_digest_it_had_before_pictures() -> None:
    import hashlib

    body = references_route.ReferenceBody(purpose="kind", description="a quay", web=True)
    written = '{"description":"a quay","purpose":"kind","web":true}'
    assert references_route._request_sha256(body) == hashlib.sha256(written.encode()).hexdigest()


def test_a_caller_holding_a_picture_right_is_served_its_words_while_pictures_are_off(
    api, monkeypatch
) -> None:
    # So the right can be stopped from the app whatever the offer's state.
    monkeypatch.setattr(references_route, "_holds_picture_right", lambda c, w, a: True)
    pictures = _get(api[0](), "/worlds/references").json()["pictures"]
    assert (pictures["offered"], pictures["code"]) == (False, "reference_pictures_not_offered")
    assert [use["role"] for use in pictures["consent"]["uses"]] == ["reference_vision"]
    assert all(use["stop"] and use["stop_action"] for use in pictures["consent"]["uses"])


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"reference_workspaces": ()},
        {"reference_pictures": True, "reference_workspaces": ()},
        {"reference_pictures": True, "alive": False},
        {"reference_pictures": True, "spending": None},
        {"reference_pictures": True, "runs_reference_worker": False},
    ],
)
def test_a_request_naming_a_picture_is_refused_with_the_code_the_list_states(api, changes) -> None:
    client, repository = api
    stated = _get(client(**changes), "/worlds/references").json()["pictures"]
    assert stated["offered"] is False and stated["code"] is not None
    refused = _post(client(**changes), web=False, pictures=[str(PICTURE)])
    assert (refused.status_code, refused.json()["code"]) == (409, stated["code"])
    with_web = _post(client(**changes), pictures=[str(PICTURE)])
    assert (with_web.status_code, with_web.json()["code"]) == (409, stated["code"])
    assert _requests(repository) == 0
