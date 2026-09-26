"""The same hour of a saved world run by two models, recorded, scored and read back, as deployed.

The application connects as a provisioned runtime role over a saved world whose purposeful
society holds its people. A comparison is defined and run by the runner the local command builds
(:class:`~exulanica.api.society_comparison_runner.SocietyComparisonRunner`), asking two declared
models behind a scripted transport exactly as the host's playback asks: the workspace's rules,
the contract's request and ``ask_person``. What is shown:

*   every run of every arm is recorded and completed, the anchors score 0 and 1 exactly, and the
    read of a development comparison says it is not judged, by name;
*   a run is read back by replaying it from what it stored, with no model call, and no response
    carries a seed;
*   the records are appended and never changed, by the grants and by the triggers;
*   a caller of another world, and an unknown comparison, read the same answer;
*   a host with no client fails a model's runs by name, and the comparison reads incomplete;
*   a run a process stopped part way is closed as interrupted, and nothing is asked again;
*   a comparison id another world of the workspace holds is refused as a conflict by name.
"""

from __future__ import annotations

import json
import os
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from exulanica.api.society_comparison_runner import ComparisonArm, SocietyComparisonRunner
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.orchestration.compare import comparison_body
from exulanica.world.society_comparison_repository import (
    ComparisonConflict,
    SocietyComparisonRepository,
)

import test_society_stay_requests_api as stays
from comparison_support import SEEDS, seeded_catalogs
from model_fakes import FakeTransport, chat_body
from test_society_saved_world_api import OWNER

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres


class _Chooser(FakeTransport):
    """A scripted model that picks the first offered place to go every time it is asked."""

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
                    "arguments": json.dumps({"action": next(a for a in enum if " m away" in a)}),
                },
            }
        ]
        return HttpResponse(200, json.dumps(body))


def _runner(world, services, transport, *, client=True) -> SocietyComparisonRunner:
    manifest = load_manifest()
    return SocietyComparisonRunner(
        database=services.database,
        runtime=services.society_runtime,
        client=ModelClient(
            api_key="test-key-not-real",
            manifest=manifest,
            transport=transport,
            budget=BudgetGuard(ceiling_usd=Decimal("5"), max_calls=100_000),
        )
        if client
        else None,
        policy_for=services.person_decision_policy,
        manifest=manifest,
        manifest_sha256="a" * 64,
        workspace_id=world["workspace"],
        world_id=world["binding"].world_id,
        actor=world["session"].actor,
        catalogs=seeded_catalogs(),
    )


def _models() -> list[ComparisonArm]:
    offered = load_manifest().offered_models(Role.SOCIETY_DECISION)
    return [ComparisonArm(spec.provider, spec.model_id) for spec in offered[:2]]


def _route(world, suffix: str = "") -> str:
    return f"/world/versions/{world['binding'].version_id}/society/comparisons{suffix}"


def _scope(world) -> dict[str, str]:
    return {"world_id": world["binding"].world_id}


def _compared(world, client, *, runner_client=True) -> tuple[uuid.UUID, _Chooser]:
    stays._inhabited(world, client)
    services = client.app.state.services
    transport = _Chooser()
    runner = _runner(world, services, transport, client=runner_client)
    comparison_id = uuid.uuid4()
    runner.define(
        world["binding"].version_id,
        comparison_id=comparison_id,
        body=comparison_body(runner, _models(), SEEDS, control=False),
    )
    runner.run_all(comparison_id, runner.reserve_all(comparison_id, SEEDS))
    return comparison_id, transport


def _no_seed(text: str) -> None:
    for seed in SEEDS:
        assert seed not in text


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_two_models_run_the_same_hour_and_the_page_reads_their_scores(app):
    world, client = app
    comparison_id, transport = _compared(world, client)
    # The positive control: both models were asked, through the product's client.
    asked = {request["payload"]["model"] for request in transport.requests}
    assert asked == {model.model_id for model in _models()}
    listed = client.get(_route(world), headers=OWNER, params=_scope(world))
    assert listed.status_code == 200, listed.text
    [comparison] = listed.json()["comparisons"]
    assert comparison["comparison_id"] == str(comparison_id)
    assert comparison["runs"] == comparison["runs_completed"] == comparison["runs_expected"] == 8
    read = client.get(_route(world, f"/{comparison_id}"), headers=OWNER, params=_scope(world))
    assert read.status_code == 200, read.text
    result = read.json()
    _no_seed(read.text)
    assert result["verdict"] == {
        "code": "not_judged",
        "higher": None,
        "reason": "development_seeds",
    }
    summaries = result["summaries"]
    assert summaries["routine"]["mean_score"] == "1.0000"
    assert summaries["wait"]["mean_score"] == "0.0000"
    for key in ("model_a", "model_b"):
        assert summaries[key]["mean_score"] is not None
        assert summaries[key]["cost_usd_per_hour"] is not None
        assert summaries[key]["latency_ms"]["p50"] is not None
    assert summaries["routine"]["cost_usd_per_hour"] is None
    # Differences are shown, and a development comparison claims none of them.
    assert [(d["first"], d["second"]) for d in result["differences"]] == [
        ("model_a", "model_b"),
        ("routine", "model_a"),
        ("routine", "model_b"),
    ]
    assert all(seed["name"] in ("test_1", "test_2", None) for seed in result["seeds"])
    # Both documents name each model an arm asks by the manifest's one rule.
    manifest = load_manifest()
    for arms in (comparison["arms"], result["arms"]):
        named = {
            arm["decider"]["model_id"]: arm["decider"]["name"]
            for arm in arms
            if "name" in arm["decider"]
        }
        assert named == {model.model_id: manifest.model_name(model.model_id) for model in _models()}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_run_is_read_by_replaying_what_it_stored_with_no_model_call(app):
    world, client = app
    comparison_id, transport = _compared(world, client)
    result = client.get(_route(world, f"/{comparison_id}"), headers=OWNER, params=_scope(world))
    run_id = result.json()["seeds"][0]["runs"]["model_a"]["run_id"]
    calls = len(transport.requests)
    replayed = client.get(
        _route(world, f"/{comparison_id}/runs/{run_id}"), headers=OWNER, params=_scope(world)
    )
    assert replayed.status_code == 200, replayed.text
    assert len(transport.requests) == calls
    document = replayed.json()
    _no_seed(replayed.text)
    assert document["replay_verified"] is True
    assert document["arm"] == "model_a"
    assert len(document["minutes"]) == result.json()["window_ticks"] + 1
    assert document["decisions"]
    assert any(decision["disposition"] == "applied" for decision in document["decisions"])
    assert {person["id"] for person in document["people"]} == {
        person["id"] for person in document["minutes"][0]["people"]
    }


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_comparison_records_are_appended_and_never_changed(app):
    world, client = app
    comparison_id, _transport = _compared(world, client)
    services = client.app.state.services
    for table in (
        "society_comparison",
        "society_comparison_run",
        "society_comparison_decision",
        "society_comparison_outcome",
    ):
        with (
            services.database.session(world["workspace"]) as connection,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            connection.execute(
                f"delete from {table} where workspace_id=%s and world_id=%s",
                (world["workspace"], world["binding"].world_id),
            )
    owner = world["connection"]
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="appended, never changed"),
        owner.transaction(),
    ):
        owner.execute(
            "update society_comparison_outcome set status=status "
            "where workspace_id=%s and world_id=%s and comparison_id=%s",
            (world["workspace"], world["binding"].world_id, comparison_id),
        )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_another_world_and_an_unknown_comparison_read_the_same(app):
    world, client = app
    comparison_id, _transport = _compared(world, client)
    unknown = client.get(_route(world, f"/{uuid.uuid4()}"), headers=OWNER, params=_scope(world))
    elsewhere = client.get(
        _route(world, f"/{comparison_id}"),
        headers=OWNER,
        params={"world_id": f"world:authored:{uuid.uuid4()}"},
    )
    assert unknown.status_code == elsewhere.status_code == 404
    assert unknown.json()["code"] == elsewhere.json()["code"] == "unknown_reference"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_host_with_no_client_fails_the_model_runs_by_name(app):
    world, client = app
    comparison_id, transport = _compared(world, client, runner_client=False)
    assert not transport.requests
    result = client.get(_route(world, f"/{comparison_id}"), headers=OWNER, params=_scope(world))
    body: dict[str, Any] = result.json()
    assert body["verdict"]["code"] == "incomplete"
    statuses = {
        arm: {seed["runs"][arm]["status"] for seed in body["seeds"]} for arm in body["summaries"]
    }
    assert statuses == {
        "model_a": {"failed"},
        "model_b": {"failed"},
        "routine": {"completed"},
        "wait": {"completed"},
    }
    services = client.app.state.services
    with services.database.session(world["workspace"]) as connection:
        codes = {
            row["code"]
            for row in connection.execute(
                "select document->>'code' as code from society_comparison_outcome "
                "where workspace_id=%s and world_id=%s and status='failed'",
                (world["workspace"], world["binding"].world_id),
            ).fetchall()
        }
    assert codes == {"provider_credential_absent"}


def _defined(world, client, seeds=SEEDS) -> tuple[SocietyComparisonRunner, uuid.UUID, _Chooser]:
    stays._inhabited(world, client)
    transport = _Chooser()
    runner = _runner(world, client.app.state.services, transport)
    comparison_id = uuid.uuid4()
    runner.define(
        world["binding"].version_id,
        comparison_id=comparison_id,
        body=comparison_body(runner, _models(), seeds, control=False),
    )
    return runner, comparison_id, transport


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_run_stopped_part_way_is_closed_as_interrupted_and_nothing_is_asked_again(
    app, monkeypatch
):
    """A process that stops in the middle of a run (here the database fails on a minute's
    receipts) leaves receipts and no outcome. Running it again asks nobody: before anything is
    asked it is recorded as failed, interrupted, and the comparison reads it by that name."""
    world, client = app
    runner, comparison_id, transport = _defined(world, client, SEEDS[:1])
    run_ids = runner.reserve_all(comparison_id, SEEDS[:1])
    services = client.app.state.services
    with services.database.session(world["workspace"]) as connection:
        arms = {
            row["arm"]: row["run_id"]
            for row in connection.execute(
                "select arm, run_id from society_comparison_run where workspace_id=%s "
                "and world_id=%s and comparison_id=%s",
                (world["workspace"], world["binding"].world_id, comparison_id),
            ).fetchall()
        }
    assert set(arms.values()) == set(run_ids)
    appended = SocietyComparisonRepository.append
    minutes: list[int] = []

    def stops_on_the_second(self, *args, **kwargs):
        minutes.append(1)
        if len(minutes) > 1:
            raise psycopg.OperationalError("the database went away")
        return appended(self, *args, **kwargs)

    monkeypatch.setattr(SocietyComparisonRepository, "append", stops_on_the_second)
    with pytest.raises(psycopg.OperationalError):
        runner.run(comparison_id, arms["model_a"])
    monkeypatch.setattr(SocietyComparisonRepository, "append", appended)
    asked = transport.call_count
    assert asked > 0, "the model was asked before the process stopped"
    with services.database.session(world["workspace"]) as connection:
        repository = runner._repository(connection)
        assert repository.stored(arms["model_a"]), "the stopped run holds receipts"
        assert repository.outcome(arms["model_a"]) is None
    outcome = runner.run(comparison_id, arms["model_a"])
    assert (outcome["status"], outcome["code"]) == ("failed", "interrupted")
    assert transport.call_count == asked, "nothing is asked again"
    assert runner.run(comparison_id, arms["model_a"]) == outcome, "read back, not closed twice"
    result = client.get(_route(world, f"/{comparison_id}"), headers=OWNER, params=_scope(world))
    assert result.status_code == 200, result.text
    [seed] = result.json()["seeds"]
    assert (seed["runs"]["model_a"]["status"], seed["runs"]["model_a"]["failure"]) == (
        "failed",
        "interrupted",
    )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_comparison_id_another_world_of_the_workspace_holds_is_a_conflict(app, monkeypatch):
    """The key is the workspace's, and a world's own read does not see another world's
    definitions, so the id is taken all the same: it is refused as a conflict by name, not as a
    database error. The other world's definition is stood in for by this world's own, with this
    world's read made to miss it."""
    world, client = app
    runner, comparison_id, _transport = _defined(world, client)
    body = comparison_body(runner, _models(), SEEDS, control=False)
    # The positive control: the same id and body is the stored definition, read back.
    runner.define(world["binding"].version_id, comparison_id=comparison_id, body=body)
    monkeypatch.setattr(SocietyComparisonRepository, "_definition", lambda *_args, **_kwargs: None)
    with pytest.raises(ComparisonConflict) as refused:
        runner.define(world["binding"].version_id, comparison_id=comparison_id, body=body)
    cause = refused.value.__cause__
    assert isinstance(cause, psycopg.errors.UniqueViolation)
    assert cause.diag.constraint_name == "society_comparison_pkey"


#: The documents the page parses, as the server served them in this file's comparison, with long
#: lists cut short. web/packages/app/test/society-comparison-api.test.ts parses this file with the
#: page's own parsers; this test holds every document the server serves to its keys. Rewrite it
#: with EXULANICA_COMPARISON_DOCUMENTS=write and review the diff.
DOCUMENTS = Path(__file__).resolve().parent / "snapshots" / "society-comparison-documents.json"
#: How many entries of a long list the golden keeps: enough for a parser to read each shape.
KEPT = 3


def _keys(value: Any) -> Any:
    """A document's shape: every object's keys, recursively, and a list's by its first entry."""
    if isinstance(value, dict):
        return {key: _keys(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_keys(value[0])] if value and isinstance(value[0], dict | list) else []
    return None


def _cut(document: dict[str, Any]) -> dict[str, Any]:
    place = document["place"]
    kept_nodes = {node["id"] for node in place["nodes"][: KEPT * 4]}
    return {
        **document,
        "place": {
            "nodes": place["nodes"][: KEPT * 4],
            "edges": [edge for edge in place["edges"] if set(edge) <= kept_nodes][: KEPT * 4],
            "targets": place["targets"][:KEPT],
        },
        "minutes": document["minutes"][:KEPT],
        "decisions": document["decisions"][:KEPT],
        "events": document["events"][:KEPT],
    }


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_page_reads_the_documents_the_server_serves(app):
    world, client = app
    comparison_id, _transport = _compared(world, client)
    listing = client.get(_route(world), headers=OWNER, params=_scope(world)).json()
    result = client.get(
        _route(world, f"/{comparison_id}"), headers=OWNER, params=_scope(world)
    ).json()
    run_id = result["seeds"][0]["runs"]["model_a"]["run_id"]
    replay = client.get(
        _route(world, f"/{comparison_id}/runs/{run_id}"), headers=OWNER, params=_scope(world)
    ).json()
    served = {"listing": listing, "result": result, "run": replay}
    if os.environ.get("EXULANICA_COMPARISON_DOCUMENTS") == "write":
        golden = {**served, "run": _cut(replay)}
        DOCUMENTS.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    golden = json.loads(DOCUMENTS.read_text(encoding="utf-8"))
    for name, document in served.items():
        assert _keys(document) == _keys(golden[name]), name
