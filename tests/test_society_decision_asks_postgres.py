"""A recorded decision asked again of another model, beside the original, never applied
(migration 0216).

On a saved world's square, a chosen person's decision is recorded as the host asks it, answered by a
scripted model behind the real client. The same request is then asked of another model through the
routes, its answer scripted too, so nothing is paid and nothing reaches a network. What is shown:

*   the ask is sent the identical request (the options the original model was offered, by the
    role and terms it was asked under) and its answer is recorded beside the original, with both
    models, what each chose and what each cost; the society's state, inputs, requests, receipts
    and transitions are untouched;
*   a repeated idempotency key answers the first ask and asks nothing;
*   an answer that never came is recorded with its reason;
*   a request whose messages no longer digest as recorded, an undeclared model, a bound out of
    range, an unknown request, a stranger and a reader who may not ask models are each refused by
    name, asking nothing;
*   the asks go with their society when it is erased.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from decimal import Decimal

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.world import society_decision_asks

from model_fakes import FakeTransport, chat_body
from test_society_person_decisions_postgres import (
    _callers,
    _Chooser,
    _choosing,
    _decisions,
    _offered,
    _services,
)
from test_society_person_decisions_postgres import app as app
from test_society_person_decisions_postgres import saved_world as saved_world
from test_society_saved_world_api import routes

pytestmark = pytest.mark.postgres

ASKED = {"provider": "nebius_token_factory", "model_id": "Qwen/Qwen3-235B-A22B-Instruct-2507"}


class _Waiter(FakeTransport):
    """A scripted model that takes the last offered place every time it is asked."""

    def post_json(self, url, *, headers, payload, timeout):
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        enum = payload["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
        body = chat_body("", model=payload["model"], finish_reason="tool_calls")
        body["choices"][0]["message"]["content"] = None
        body["choices"][0]["message"]["tool_calls"] = [
            {
                "id": "c",
                "type": "function",
                "function": {
                    "name": "act",
                    "arguments": json.dumps({"action": [a for a in enum if " m away" in a][-1]}),
                },
            }
        ]
        return HttpResponse(200, json.dumps(body))


class _Silent(FakeTransport):
    """A model that never answers."""

    def post_json(self, url, *, headers, payload, timeout):
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        return HttpResponse(503, "{}")


def _recorded(world, client, transport):
    """A recorded decision answered by a scripted model, and the services asking ``transport``."""
    services = _services(client)
    manifest, model_id = _offered()
    snapshot, _host = _choosing(world, client, services, manifest, model_id, _Chooser())
    receipt = _decisions(services, world, snapshot)[0]
    client.app.state.services = dataclasses.replace(
        _services(client),
        model_client=ModelClient(
            api_key="test-key-not-real",
            manifest=load_manifest(),
            transport=transport,
            budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=100),
        ),
    )
    return services, snapshot, receipt


def _counts(services, world, society_id) -> dict[str, int]:
    with services.database.session(world["workspace"]) as connection:
        return {
            table: connection.execute(
                f"select count(*) as n from {table} where workspace_id=%s and society_id=%s",
                (world["workspace"], society_id),
            ).fetchone()["n"]
            for table in (
                "world_society_input",
                "world_society_transition",
                "world_society_decision_request",
                "world_society_decision",
                "world_society_transition_decision",
                "world_society_decision_ask",
            )
        }


def _ask(client, society, request_id, headers, scope, **body):
    payload = {"model": ASKED, "bound_usd": "0.05", **body}
    return client.post(
        f"{society}/decisions/{request_id}/asks", json=payload, headers=headers, params=scope
    )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_ask_is_recorded_beside_the_original_and_never_applied(app) -> None:
    world, client = app
    transport = _Waiter()
    services, snapshot, receipt = _recorded(world, client, transport)
    owner = _callers(client, world, listed=True)["owner"][0]
    scope, _version, society = routes(world)
    request_id = receipt["request_id"]
    state = client.get(society, headers=owner, params=scope).json()["state_sha256"]
    before = _counts(services, world, snapshot["society_id"])
    key = str(uuid.uuid4())

    asked = _ask(client, society, request_id, owner, scope, idempotency_key=key)
    assert asked.status_code == 201, asked.text
    view = asked.json()
    assert (view["provider"], view["model_id"], view["mechanism"]) == (
        ASKED["provider"],
        ASKED["model_id"],
        "tool_call",
    )
    assert view["status"] == "accepted" and view["chose"] is not None and view["kind"] is not None
    assert view["same_messages"] is True
    assert view["cost_usd"] is not None
    sent = transport.requests[0]["payload"]
    offered = sent["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
    with services.database.session(world["workspace"]) as connection:
        request = connection.execute(
            "select document from world_society_decision_request where request_id=%s",
            (uuid.UUID(request_id),),
        ).fetchone()["document"]
    assert sorted(offered) == sorted(option["label"] for option in request["context"]["options"])

    # Nothing of the world moved: one row more, in the asks alone.
    after = _counts(services, world, snapshot["society_id"])
    assert after == {
        **before,
        "world_society_decision_ask": before["world_society_decision_ask"] + 1,
    }
    assert client.get(society, headers=owner, params=scope).json()["state_sha256"] == state

    # The same key answers the first ask and asks nothing.
    again = _ask(client, society, request_id, owner, scope, idempotency_key=key)
    assert again.status_code == 201 and again.json()["ask_id"] == view["ask_id"]
    assert len(transport.requests) == 1

    compared = client.get(f"{society}/decisions/{request_id}/asks", headers=owner, params=scope)
    assert compared.status_code == 200, compared.text
    body = compared.json()
    original = body["original"]
    assert original["model_id"] == receipt["provider"]["model_id"]
    assert original["chose"] == receipt["proposal"]["label"]
    [beside] = body["asks"]
    assert beside["ask_id"] == view["ask_id"]
    assert beside["same_choice"] is (beside["chose"] == original["chose"])
    assert beside["same_kind"] is (beside["kind"] == original["kind"])


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_answer_that_never_came_is_recorded_with_its_reason(app) -> None:
    world, client = app
    _, _, receipt = _recorded(world, client, _Silent())
    owner = _callers(client, world, listed=True)["owner"][0]
    scope, _version, society = routes(world)
    asked = _ask(client, society, receipt["request_id"], owner, scope)
    assert asked.status_code == 201, asked.text
    assert asked.json()["status"] == "unavailable" and asked.json()["chose"] is None


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_ask_is_refused_by_name_and_asks_nothing(app, monkeypatch) -> None:
    world, client = app
    transport = _Waiter()
    services, snapshot, receipt = _recorded(world, client, transport)
    callers = _callers(client, world, listed=True)
    owner = callers["owner"][0]
    scope, _version, society = routes(world)
    request_id = receipt["request_id"]

    refusals = [
        (_ask(client, society, str(uuid.uuid4()), owner, scope), 404, None),
        (_ask(client, society, request_id, callers["stranger"][0], scope), 404, None),
        # A credential that may not ask models learns nothing more than a stranger.
        (_ask(client, society, request_id, callers["reader"][0], scope), 404, None),
        (
            _ask(client, society, request_id, owner, scope, model={**ASKED, "model_id": "no/such"}),
            409,
            "model_not_declared",
        ),
        (
            _ask(client, society, request_id, owner, scope, bound_usd="0.5"),
            422,
            "bound_out_of_range",
        ),
    ]
    for answer, status, code in refusals:
        assert answer.status_code == status, answer.text
        if code is not None:
            assert answer.json()["code"] == code

    monkeypatch.setattr(society_decision_asks, "society_state_sha256", lambda state: "0" * 64)
    changed = _ask(client, society, request_id, owner, scope)
    assert (changed.status_code, changed.json()["code"]) == (409, "decision_not_reproducible")
    assert transport.requests == []
    assert _counts(services, world, snapshot["society_id"])["world_society_decision_ask"] == 0


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_asks_go_with_their_society(app) -> None:
    world, client = app
    services, _, receipt = _recorded(world, client, _Waiter())
    owner = _callers(client, world, listed=True)["owner"][0]
    scope, _version, society = routes(world)
    assert _ask(client, society, receipt["request_id"], owner, scope).status_code == 201
    erased = client.delete(society, headers=owner, params=scope)
    assert erased.status_code in (200, 202, 204), erased.text
    with services.database.session(world["workspace"]) as connection:
        left = connection.execute(
            "select count(*) as n from world_society_decision_ask where workspace_id=%s",
            (world["workspace"],),
        ).fetchone()["n"]
    assert left == 0
