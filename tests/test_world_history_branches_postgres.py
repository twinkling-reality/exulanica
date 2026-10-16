"""Another model's answers to a moment's decision, read as its branches in History (private
PostgreSQL).

A person on a saved world's square goes somewhere a scripted model chose for them, and the minute
that applies it records the going as a moment. The same decision is then asked again of another
model through the routes, once answered and once never answered, and a refused answer is kept beside
them. History's read gives the moment the answered ask alone as a branch, naming whose decision it
answers and saying whether it chose the same: an ask not answered, or answered and refused, is no
other model's answer. People who set off for the same place in that minute make one going, which
keeps the branch.
"""

from __future__ import annotations

import dataclasses
import uuid
from decimal import Decimal

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest

import test_society_stay_requests_api as stays
from test_society_decision_asks_postgres import ASKED, _ask, _recorded, _Silent, _Waiter
from test_society_person_decisions_postgres import _callers, _services
from test_society_person_decisions_postgres import app as app
from test_society_person_decisions_postgres import saved_world as saved_world
from test_society_saved_world_api import routes

pytestmark = pytest.mark.postgres

REFUSED = '{"status": "rejected", "reason": "invalid_choice"}'


def _asking(client, transport) -> None:
    client.app.state.services = dataclasses.replace(
        _services(client),
        model_client=ModelClient(
            api_key="test-key-not-real",
            manifest=load_manifest(),
            transport=transport,
            budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=100),
        ),
    )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_moment_s_branches_are_the_answered_asks_of_its_own_decision(app) -> None:
    world, client = app
    _services_before, snapshot, receipt = _recorded(world, client, _Waiter())
    # The minute that applies the receipt records the going as a moment.
    stays._step(world, client, snapshot)
    owner = _callers(client, world, listed=True)["owner"][0]
    scope, version, society = routes(world)
    request_id = receipt["request_id"]
    answered = _ask(client, society, request_id, owner, scope, idempotency_key=str(uuid.uuid4()))
    assert answered.status_code == 201, answered.text
    assert answered.json()["status"] == "accepted"
    _asking(client, _Silent())
    unanswered = _ask(client, society, request_id, owner, scope, idempotency_key=str(uuid.uuid4()))
    assert unanswered.status_code == 201, unanswered.text
    assert unanswered.json()["status"] != "accepted", "the positive control: an ask not answered"
    # An answer refused as the host refuses one it cannot apply: a proposal kept, but no branch.
    with _services(client).database.session(world["workspace"]) as connection:
        connection.execute(
            "insert into world_society_decision_ask(workspace_id,society_id,request_id,asked_by,"
            "idempotency_key,provider,model_id,mechanism,prompt_version,messages_sha256,"
            "request_messages_sha256,bound_id,bound_usd,status,reason,document) "
            "select workspace_id,society_id,request_id,asked_by,%s,provider,model_id,mechanism,"
            "prompt_version,messages_sha256,request_messages_sha256,bound_id,bound_usd,'rejected',"
            "'invalid_choice',document || %s::jsonb "
            "from world_society_decision_ask where ask_id=%s",
            (uuid.uuid4(), REFUSED, uuid.UUID(answered.json()["ask_id"])),
        )

    body = client.get(version + "/history/moments", headers=owner, params=scope).json()
    # The going the model chose, alone or made with someone, carries the answered ask alone.
    branched = [m for m in body["moments"] if m["branches"]]
    assert [m["kind"] for m in branched] == ["went"]
    [moment] = branched
    [branch] = moment["branches"]
    assert branch["ask_id"] == answered.json()["ask_id"]
    assert branch["by"] in moment["subjects"]
    assert branch["model"]["model_id"] == ASKED["model_id"]
    assert branch["same_choice"] is (answered.json()["chose"] == receipt["proposal"]["label"])
