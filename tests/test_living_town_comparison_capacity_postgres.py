"""A generated town's whole population can be decided for by a model in one comparison.

A living town's runs are read by the line measured on the living engine (the reading catalog), so
a comparison of a generated town may give every one of its people to a model within the pair's
unchanged read budget; under the protocol's own line, measured on the purposeful engine, the same
comparison is refused by name. Through the application as deployed, as the runtime role: the plan,
the start, the host's worker playing it with a scripted model, and the model run read back from
what it stored, with no model call.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from exulanica.world import society_comparison_reading as reading
from exulanica.world.society_decision_contract import person_role

import test_society_comparison_postgres as compared
from comparison_support import SEEDS, seeded_catalogs
from test_society_living_town_postgres import (  # noqa: F401
    TOWN,
    _every_town_a_test_makes_is_made,
)
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

MANIFEST = load_manifest()
#: The model the scripted transport answers for: the first the manifest offers a person.
MODEL = MANIFEST.offered_models(person_role().chosen)[0]


@pytest.fixture(name="town")
def _town(request) -> dict[str, Any]:
    """A market town made through the application, its living society, and a host that asks a
    scripted model and whose comparisons a worker of the test's own plays."""
    api = request.getfixturevalue("imported_made")
    workspace = api.repository.workspace_id
    transport = compared._Chooser()
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services,
        model_client=ModelClient(
            api_key="test-key-not-real",
            manifest=MANIFEST,
            transport=transport,
            budget=BudgetGuard(ceiling_usd=Decimal("5"), max_calls=100_000),
        ),
        society_control_workspaces=(workspace,),
        comparison_seeds=tuple(SEEDS),
        comparison_catalogs=seeded_catalogs(),
        comparisons_played_elsewhere=True,
    )
    made = api.post("/worlds/generated", {"recipe": "market_town", "title": "A market town"})
    assert made.status_code == 201, made.text
    entry = made.json()
    scope = f"?world_id={entry['world_id']}"
    society = api.post(
        f"/world/versions/{entry['authored_version_id']}/society{scope}",
        {"region_id": "region:generated", "profile": TOWN},
    )
    assert society.status_code in (200, 201), society.text
    return {
        "api": api,
        "entry": entry,
        "population": len(society.json()["state"]["inhabitants"]),
        "transport": transport,
        "workspace": workspace,
        "comparisons": f"/world/versions/{entry['authored_version_id']}/society/comparisons",
        "scope": scope,
    }


def _plan(town: dict[str, Any]) -> dict[str, Any]:
    query = (
        f"{town['scope']}&role={person_role().key}&group=everyone"
        f"&model={MODEL.provider}/{MODEL.model_id}&seeds=1"
    )
    planned = town["api"].get(f"{town['comparisons']}/plan{query}")
    assert planned.status_code == 200, planned.text
    return planned.json()


def _protocol_line_only(monkeypatch, tmp_path: Path) -> None:
    """The reading catalog as it would be with no line measured apart from the protocol's."""
    empty = tmp_path / "society-comparison-reading.v1.json"
    empty.write_text(
        json.dumps(
            {
                "catalog_id": "society-comparison-reading",
                "catalog_version": 1,
                "source_build": "A test catalog that states no family's own line.",
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(reading, "READING_CATALOG", empty)


def test_under_the_protocols_own_line_a_whole_town_is_refused_by_name(town, monkeypatch, tmp_path):
    _protocol_line_only(monkeypatch, tmp_path)
    plan = _plan(town)
    assert plan["decided_most"] < town["population"]
    assert plan["plan_refusal"]["code"] == "decided_over_comparison_bound"
    started = town["api"].post(
        f"{town['comparisons']}{town['scope']}",
        {
            "comparison_id": str(uuid.uuid4()),
            "role": person_role().key,
            "group": {"kind": "everyone"},
            "models": [{"provider": MODEL.provider, "model_id": MODEL.model_id}],
            "control": False,
            "seeds": 1,
            "bound_usd": "1.00",
        },
    )
    assert (started.status_code, started.json()["code"]) == (409, "decided_over_comparison_bound")


def test_a_whole_town_decided_by_a_model_is_planned_started_played_and_read(town):
    api, population = town["api"], town["population"]
    plan = _plan(town)
    assert plan["plan_refusal"] is None, plan["plan_refusal"]
    assert plan["decided_most"] == population
    assert plan["plan"]["asks_most"] == 60 * population
    comparison_id = str(uuid.uuid4())
    bound = min(Decimal(plan["plan"]["most_usd"]), Decimal("1.00"))
    started = api.post(
        f"{town['comparisons']}{town['scope']}",
        {
            "comparison_id": comparison_id,
            "role": person_role().key,
            "group": {"kind": "everyone"},
            "models": [{"provider": MODEL.provider, "model_id": MODEL.model_id}],
            "control": False,
            "seeds": 1,
            "bound_usd": format(bound, "f"),
        },
    )
    assert started.status_code == 201, started.text
    worker = api.client.app.state.services.build_comparison_worker(keeps_share=True)
    assert worker.run_once(town["workspace"]) is True
    asked = len(town["transport"].requests)
    assert asked > 0, "the model arm asked the scripted model"
    result = api.get(f"{town['comparisons']}/{comparison_id}{town['scope']}")
    assert result.status_code == 200, result.text
    document = result.json()
    assert document["start"]["state"] == "finished"
    assert document["group"]["size"] == population
    (seed,) = document["seeds"]
    runs = seed["runs"]
    assert {run["status"] for run in runs.values()} == {"completed"}
    model_run = runs["model_a"]
    read = api.get(
        f"{town['comparisons']}/{comparison_id}/runs/{model_run['run_id']}{town['scope']}"
    )
    assert read.status_code == 200, read.text
    drawn = read.json()
    assert drawn["replay_verified"] is True
    decided = [person for person in drawn["people"] if person["decider"]["kind"] == "model"]
    assert len(decided) == population
    # Reading asks nothing: the run is drawn from what it stored.
    assert len(town["transport"].requests) == asked
