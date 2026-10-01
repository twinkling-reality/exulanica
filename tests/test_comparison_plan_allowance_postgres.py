"""A comparison's plan states the spending refusal its start would meet, by the start's predicate.

Where a durable spending authority admits the host's calls, a start that would ask a provider
whose allowance is spent is refused before anything is defined (429 ``budget_exceeded`` with the
authority's ``spending`` member; tests/test_comparison_start_allowance_postgres.py). The plan of
the same selection says so first: its ``plan_refusal`` carries that code, detail and member, read
by the predicate the start's check raises (``Services.allowance_refusal``), and writes nothing.
With allowance left the plan plans and the start starts. Shown for comparisons of a world's people
and of a town's signals.

A comparison of people also asks, in every arm, the model an owner chose for somebody outside its
group. The manifest offers one provider, so these tests serve a second one from a manifest of
their own: an outside person's model from a provider the workspace holds no grant of refuses the
plan and the start although the arm's provider has allowance left, and a grant of it lets both
through. A start or a plan that read only the arms' providers would let it through.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
from exulanica.models import manifest as manifest_module
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient

import test_signal_comparison_postgres as signals
import test_society_comparison_start_postgres as people
import test_society_stay_requests_api as stays
from test_comparison_start_allowance_postgres import SPENT, _durable
from test_signal_comparison_postgres import _presets_try_every_candidate, town
from test_society_comparison_start_postgres import saved_world, started

__all__ = ["_presets_try_every_candidate", "saved_world", "started", "town"]

pytestmark = pytest.mark.postgres

SECOND_PROVIDER = "second_test_provider"
SECOND_MODEL = "test/second-provider-person-model"


def _plan_people(held: dict[str, Any], **query: Any):
    world = held["world"]
    return held["client"].get(
        people._comparisons(world) + "/plan",
        headers=people.OWNER,
        params={
            **people._scope(world),
            "role": people._body()["role"],
            "group": "everyone",
            "model": f"{people.MODEL.provider}/{people.MODEL.model_id}",
            **query,
        },
    )


def _plan_signals(held: dict[str, Any]):
    named = f"&model={signals.MODEL.provider}/{signals.MODEL.model_id}&seeds=2"
    return held["api"].get(signals._path(held, "/plan") + named)


def _refused_alike(plan: Any, start: Any, spending: dict[str, str]) -> None:
    """The plan names the refusal the start is answered with: the same code, detail and member."""
    assert plan.status_code == 200, plan.text
    assert start.status_code == 429, start.text
    stated = plan.json()
    assert stated["plan"] is None
    assert stated["plan_refusal"] == {
        "code": "budget_exceeded",
        "detail": start.json()["detail"],
        "spending": spending,
    }
    assert start.json()["code"] == "budget_exceeded"
    assert start.json()["spending"] == spending


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_plan_of_people_states_a_spent_allowance_as_its_start_meets_it(
    started, spine_schema, tmp_path
):
    world = started["world"]
    stays._inhabited(world, started["client"])
    allowance = _durable(started["client"].app, spine_schema, tmp_path, world["workspace"])
    allowance.grant(calls=1)
    allowance.spend()
    plan = _plan_people(started)
    _refused_alike(plan, people._start(started, people._body()), SPENT)
    assert people._counts(world) == {
        "society_comparison": 0,
        "society_comparison_run": 0,
        "society_comparison_start": 0,
    }
    assert started["transport"].requests == []


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_plan_of_people_with_allowance_left_plans_and_its_start_starts(
    started, spine_schema, tmp_path
):
    world = started["world"]
    stays._inhabited(world, started["client"])
    allowance = _durable(started["client"].app, spine_schema, tmp_path, world["workspace"])
    allowance.grant(calls=1000)
    plan = _plan_people(started)
    assert plan.status_code == 200, plan.text
    assert plan.json()["plan_refusal"] is None
    assert plan.json()["plan"]["runs"] > 0
    assert people._start(started, people._body()).status_code == 201


def test_a_plan_of_signals_states_a_spent_allowance_as_its_start_meets_it(
    town, spine_schema, tmp_path
):
    workspace = town["repository"].workspace_id
    allowance = _durable(town["api"].client.app, spine_schema, tmp_path, workspace)
    allowance.grant(calls=1)
    allowance.spend()
    plan = _plan_signals(town)
    _refused_alike(plan, signals._start(town, signals._body()), SPENT)
    assert signals._count(town, "signal_comparison") == 0
    assert town["transport"].requests == []


def test_a_plan_of_signals_with_allowance_left_plans_and_its_start_starts(
    town, spine_schema, tmp_path
):
    workspace = town["repository"].workspace_id
    allowance = _durable(town["api"].client.app, spine_schema, tmp_path, workspace)
    allowance.grant(calls=1000)
    plan = _plan_signals(town)
    assert plan.status_code == 200, plan.text
    assert plan.json()["plan_refusal"] is None
    assert plan.json()["plan"]["runs"] == 4
    assert signals._start(town, signals._body()).status_code == 201


@pytest.fixture
def second_provider(tmp_path):
    """The manifest with a second provider serving a copy of the first person model, read by
    every process-wide load while a test runs, and the first manifest again after it."""
    document = json.loads(manifest_module.MANIFEST_PATH.read_text(encoding="utf-8"))
    document["providers"][SECOND_PROVIDER] = {
        **document["providers"][people.MODEL.provider],
        "api_key_env": "SECOND_TEST_PROVIDER_API_KEY",
        "base_url": "https://second-test-provider.invalid/v1",
        "catalog_url": "https://second-test-provider.invalid/models",
        "description": "A second provider, served only in this test's manifest.",
    }
    document["models"][SECOND_MODEL] = {
        **document["models"][people.MODEL.model_id],
        "provider": SECOND_PROVIDER,
        "description": "The first person model, served by the second test provider.",
    }
    path = tmp_path / "models.manifest.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(manifest_module, "MANIFEST_PATH", path)
        manifest_module.load_manifest.cache_clear()
        yield manifest_module.load_manifest()
    manifest_module.load_manifest.cache_clear()


def _choose(held: dict[str, Any], people_ids: list[str], model: dict[str, str]) -> None:
    world = held["world"]
    chosen = held["client"].post(
        f"/world/versions/{world['binding'].version_id}/society/models",
        headers=people.OWNER,
        params=people._scope(world),
        json={"idempotency_key": str(uuid.uuid4()), "people": people_ids, "model": model},
    )
    assert chosen.status_code in (200, 201), chosen.text


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_outside_persons_provider_without_allowance_refuses_plan_and_start(
    started, spine_schema, tmp_path, second_provider
):
    world, client = started["world"], started["client"]
    app = client.app
    snapshot = stays._inhabited(world, client)
    # The host's client serves both providers, as a deployment's would from this manifest.
    app.state.services = dataclasses.replace(
        app.state.services,
        model_client=ModelClient(
            api_key={
                people.MODEL.provider: "test-key-not-real",
                SECOND_PROVIDER: "test-key-not-real",
            },
            manifest=second_provider,
            transport=started["transport"],
            budget=BudgetGuard(ceiling_usd=Decimal("5"), max_calls=100_000),
        ),
    )
    allowance = _durable(app, spine_schema, tmp_path, world["workspace"])
    allowance.grant(calls=1000)
    group = sorted(person["id"] for person in snapshot["state"]["inhabitants"])
    first = {"provider": people.MODEL.provider, "model_id": people.MODEL.model_id}
    _choose(started, group[:2], first)
    _choose(started, [group[2]], {"provider": SECOND_PROVIDER, "model_id": SECOND_MODEL})
    owner_group = {"kind": "owner_choice", "choice_seq": 1}
    body = people._body(group=owner_group)
    # The arm's provider has allowance; the outside person's provider has no grant at all.
    plan = _plan_people(started, group="owner_choice", choice_seq=1)
    _refused_alike(
        plan,
        people._start(started, body),
        {"reason": "spending_not_granted", "scope": "workspace", "retry": "never"},
    )
    assert people._counts(world)["society_comparison"] == 0
    assert started["transport"].requests == []
    # The positive control: a grant of the second provider lets the same selection through.
    second = allowance.operator.issue(
        provider=SECOND_PROVIDER,
        ceiling_usd=Decimal("1"),
        max_calls=1000,
        valid_until=dt.datetime.now(dt.UTC) + dt.timedelta(days=30),
        operator="test-operator",
        reason="a test authority",
    )
    allowance.operator.grant(
        second,
        world["workspace"],
        ceiling_usd=Decimal("1"),
        max_calls=1000,
        valid_until=dt.datetime.now(dt.UTC) + dt.timedelta(days=29),
        operator="test-operator",
        reason="a test grant",
    )
    again = _plan_people(started, group="owner_choice", choice_seq=1)
    assert again.status_code == 200, again.text
    assert again.json()["plan_refusal"] is None
    assert people._start(started, body).status_code == 201
