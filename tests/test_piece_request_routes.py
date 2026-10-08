"""``/world/piece-requests``: asking for a world's pieces, reading them, cancelling, and the
refusals. Served as the runtime and read-only roles a deployment uses, with the workspace's
``nebius_ai_cloud_gpu`` allowance issued by the spending operator. The estimate's figures are
worked by hand from the compute catalog's rate (USD 1.80 an hour; 8 s typical, 30 s bound)."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.routes import piece_requests as route
from exulanica.api.services import Services
from exulanica.db.roles import provision_runtime_role
from exulanica.generation.requests import GPU_PROVIDER
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world.style_pack_library import style_pack_library
from fastapi.testclient import TestClient

from conftest import scratch_role_database
from spending_support import bench as spending_bench  # noqa: F401
from tests_support_api import EVERY_PERMISSION
from world_support import FIXTURE_WORLD_ID, registered_world

pytestmark = pytest.mark.postgres

TOKEN = "pieces-owner-token-at-least-32-characters"
STRANGER_TOKEN = "pieces-stranger-token-at-least-32-characters"
READ_ONLY_ROLE = "exulanica_pieces_ro_suite"


@pytest.fixture(name="bench")
def _bench_alias(request):
    return request.getfixturevalue("spending_bench")


def _grant_gpu(bench, workspace_id: uuid.UUID, ceiling: str) -> None:
    now = dt.datetime.now(dt.UTC)
    authority = bench.operator.issue(
        provider=GPU_PROVIDER,
        ceiling_usd=Decimal("1.00"),
        max_calls=1000,
        valid_until=now + dt.timedelta(days=30),
        operator="test-operator",
        reason="the operator's Nebius AI Cloud GPU time, for a test",
    )
    bench.operator.grant(
        authority,
        workspace_id,
        ceiling_usd=Decimal(ceiling),
        max_calls=1000,
        valid_until=now + dt.timedelta(days=29),
        operator="test-operator",
        reason="a test grant",
    )


@pytest.fixture
def api(repository, bench, spine_schema, tmp_path, monkeypatch):
    _psycopg, scratch = spine_schema
    workspace_id = repository.workspace_id
    actor = uuid.uuid4()
    registered_world(repository.connection, workspace_id, actor=actor)
    repository.connection.commit()
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {
                    "workspace_id": str(workspace_id),
                    "actor": str(actor),
                    "permissions": EVERY_PERMISSION,
                },
                STRANGER_TOKEN: {
                    "workspace_id": str(uuid.uuid4()),
                    "actor": str(uuid.uuid4()),
                    "permissions": EVERY_PERMISSION,
                },
            }
        ),
    )
    provision_runtime_role(repository.connection, role=READ_ONLY_ROLE, read_only=True)
    services = Services(
        database=bench.runtime,
        readonly_database=scratch_role_database(scratch, READ_ONLY_ROLE),
        store=LocalContentAddressedStore(tmp_path / "blobs"),
        tokens=load_token_directory(),
        executor_shares_the_write_role=False,
        model_client=None,
        spending=bench.durable(),
    )

    def client(*, granted: str | None = "0.50") -> TestClient:
        if granted is not None:
            _grant_gpu(bench, workspace_id, granted)
        return TestClient(create_app(dataclasses.replace(services), verify=False))

    return client


def _look() -> dict:
    pack = style_pack_library().default_pack
    return {
        "pack_id": pack.pack_id,
        "version": pack.version,
        "manifest_sha256": pack.manifest_sha256,
    }


def _ask(client: TestClient, kinds=(("well", 1), ("gate", 1)), token: str = TOKEN, **changes):
    body = {
        "world_id": FIXTURE_WORLD_ID,
        "look": _look(),
        "kinds": [{"key": key, "version": version} for key, version in kinds],
        **changes,
    }
    return client.post(
        "/world/piece-requests", json=body, headers={"Authorization": f"Bearer {token}"}
    )


def _call(client: TestClient, method: str, path: str, token: str = TOKEN):
    return client.request(method, path, headers={"Authorization": f"Bearer {token}"})


def test_an_ask_answers_at_once_with_its_requests_and_their_estimate(api) -> None:
    client = api()
    answered = _ask(client)
    assert answered.status_code == 202, answered.text
    view = answered.json()
    assert [r["kind"]["key"] for r in view["piece_requests"]] == ["well", "gate"]
    assert {r["state"] for r in view["piece_requests"]} == {"requested"}
    assert view["session"]["state"] == "off"
    # 2 kinds of 4 variants: 16 s to both first variants, 64 s to all; USD 0.032 typical and
    # USD 0.12 at worst; 680 s more when no session is running.
    assert view["estimate"] == {
        "items": 8,
        "first_seconds_warm": 16,
        "all_seconds_warm": 64,
        "cold_start_seconds": 680,
        "usd_typical": "0.03200000",
        "usd_worst_case": "0.12000000",
        "provider": "nebius_ai_cloud_gpu",
    }
    # The same ask while both wait answers with the same requests.
    again = _ask(client)
    assert again.status_code == 200
    assert [r["piece_request_id"] for r in again.json()["piece_requests"]] == [
        r["piece_request_id"] for r in view["piece_requests"]
    ]


def test_a_world_s_requests_are_read_and_cancelled_by_their_workspace_only(api) -> None:
    client = api()
    made = _ask(client).json()["piece_requests"]
    listed = _call(client, "GET", f"/world/piece-requests?world_id={FIXTURE_WORLD_ID}")
    assert listed.status_code == 200
    assert {r["piece_request_id"] for r in listed.json()["piece_requests"]} == {
        r["piece_request_id"] for r in made
    }
    one = made[0]["piece_request_id"]
    assert _call(client, "GET", f"/world/piece-requests/{one}").json()["state"] == "requested"
    stranger = _call(client, "GET", f"/world/piece-requests/{one}", STRANGER_TOKEN)
    assert (stranger.status_code, stranger.json()["code"]) == (404, "unknown_piece_request")
    assert (
        _call(client, "DELETE", f"/world/piece-requests/{one}", STRANGER_TOKEN).status_code == 404
    )
    cancelled = _call(client, "DELETE", f"/world/piece-requests/{one}")
    assert (cancelled.status_code, cancelled.json()["state"]) == (200, "cancelled")
    again = _call(client, "DELETE", f"/world/piece-requests/{one}")
    assert (again.status_code, again.json()["code"], again.json()["state"]) == (
        409,
        "piece_request_not_cancellable",
        "cancelled",
    )


@pytest.mark.parametrize(
    ("changes", "status", "code"),
    [
        ({"kinds": (("knight", 1),)}, 422, "kind_without_piece"),
        ({"kinds": (("well", 9),)}, 422, "kind_unknown"),
        ({"look": {**_look(), "manifest_sha256": "0" * 64}}, 422, "look_not_served"),
        ({"world_id": "a-world-nobody-made"}, 404, "unknown_world"),
    ],
)
def test_an_ask_that_cannot_be_built_is_refused_by_name(api, changes, status, code) -> None:
    answered = _ask(api(), **changes)
    assert (answered.status_code, answered.json().get("code")) == (status, code), answered.text


def test_an_ask_beyond_the_allowance_is_refused_and_records_nothing(api) -> None:
    # USD 0.10 covers two kinds at worst (0.12 is over), and no grant covers nothing.
    client = api(granted="0.10")
    over = _ask(client)
    assert (over.status_code, over.json()["code"]) == (429, "budget_exceeded")
    assert over.json()["spending"]["reason"] == "spending_limit_reached"
    assert over.json()["spending"]["requested"] == "0.12000000"
    listed = _call(client, "GET", f"/world/piece-requests?world_id={FIXTURE_WORLD_ID}")
    assert listed.json()["piece_requests"] == []
    assert _ask(client, kinds=(("well", 1),)).status_code == 202


def test_an_ask_with_no_allowance_is_refused(api) -> None:
    refused = _ask(api(granted=None))
    assert (refused.status_code, refused.json()["code"]) == (429, "budget_exceeded")
    assert refused.json()["spending"]["reason"] == "spending_not_granted"


def test_a_key_naming_another_ask_is_refused(api) -> None:
    client = api()
    key = str(uuid.uuid4())
    assert _ask(client, idempotency_key=key).status_code == 202
    assert _ask(client, idempotency_key=key).status_code == 200
    reused = _ask(client, kinds=(("lantern", 1),), idempotency_key=key)
    assert (reused.status_code, reused.json()["code"]) == (409, "idempotency_key_reused")


def test_only_a_guest_s_browser_session_is_a_guest() -> None:
    """A guest asks only while a session runs; nothing else is held to it."""

    def caller(role: str, header: str | None):
        request = SimpleNamespace(headers={} if header is None else {"authorization": header})
        accounts = SimpleNamespace(browser_session=lambda _request: SimpleNamespace(role=role))
        return request, SimpleNamespace(accounts=accounts)

    assert route._is_guest(*caller("guest", None))
    assert not route._is_guest(*caller("owner", None))
    assert not route._is_guest(*caller("guest", "Bearer a-token"))
    request, _ = caller("guest", None)
    assert not route._is_guest(request, SimpleNamespace(accounts=None))


def test_more_kinds_than_an_ask_holds_are_refused_by_name(api) -> None:
    kinds = tuple((f"kind_{n}", 1) for n in range(17))
    answered = _ask(api(), kinds=kinds)
    assert (answered.status_code, answered.json()["code"]) == (422, "too_many_kinds")


def test_the_allowance_is_weighed_net_of_the_open_requests(api) -> None:
    # USD 0.15 covers two kinds at worst (0.12); with those open, one more (0.06) is over.
    client = api(granted="0.15")
    assert _ask(client).status_code == 202
    over = _ask(client, kinds=(("lantern", 1),))
    assert (over.status_code, over.json()["code"]) == (429, "budget_exceeded")
    assert over.json()["spending"]["reason"] == "spending_limit_reached"
    assert over.json()["spending"]["requested"] == "0.06000000"


def test_a_key_replay_answers_before_the_allowance_is_weighed(api) -> None:
    client = api(granted="0.12")
    key = str(uuid.uuid4())
    first = _ask(client, idempotency_key=key)
    assert first.status_code == 202
    # The allowance is now fully held by the open requests; the replay still answers them.
    again = _ask(client, idempotency_key=key)
    assert again.status_code == 200
    assert [r["piece_request_id"] for r in again.json()["piece_requests"]] == [
        r["piece_request_id"] for r in first.json()["piece_requests"]
    ]


def test_an_ask_in_a_deleted_workspace_answers_410(api, repository) -> None:
    client = api()
    repository.connection.execute(
        "insert into tombstone (workspace_id, scope, requested_by, reason) "
        "values (%s, 'workspace', %s, 'the person left')",
        (repository.workspace_id, uuid.uuid4()),
    )
    repository.connection.commit()
    answered = _ask(client)
    assert (answered.status_code, answered.json()["code"]) == (410, "tombstoned")
