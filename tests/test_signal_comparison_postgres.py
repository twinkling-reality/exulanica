"""A town's signals compared through the application: started, played, read, replayed, cancelled.

Through the application as a deployment runs it, as the runtime role under row-level security,
with a scripted model deciding signals: a generated small town whose roads the traffic drives is
made through ``POST /worlds/generated``, a comparison of a model with the plan's fixed timing is
started over its roads, and the host's comparison worker plays it, each seed's fixed-timing run
before its model run. The reads serve each run's measure and asking, replay a run from its receipts
asking nothing, and never return a seed; the live world's traffic, signal choices and sealed
minutes are untouched. A start is refused by name, a cancelled one stops before its next ask, and
roads that changed since the comparison recorded them are never played.
"""

from __future__ import annotations

import dataclasses
import json
import re
import threading
import uuid
from collections.abc import Iterator
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.db.roles import provision_runtime_role
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import signal_comparison_repository as repository_module
from exulanica.world import world_recipes as recipe_catalog
from exulanica.world.assets import seed_reviewed_assets
from exulanica.world.comparison_facts import ComparisonFacts
from exulanica.world.decision_roles import decision_roles
from exulanica.world.signal_comparison_result import signal_catalogs
from exulanica.world.society_comparison_start_repository import SocietyComparisonStarts
from exulanica.world.society_composition import reviewed_affordance_registry
from exulanica.world.world_recipes import CANDIDATES_MAXIMUM, world_recipes
from fastapi.testclient import TestClient

import personal_world_support as personal
from conftest import scratch_role_database
from model_fakes import FakeTransport, chat_body
from test_world_traffic_route import _driven, _identity, _made
from tests_support_api import EVERY_PERMISSION

pytestmark = pytest.mark.postgres

WRITER_TOKEN = "signal-comparison-writer-without-models-token-long-enough"
READER_TOKEN = "signal-comparison-reader-token-long-enough-for-grants"
ROLE = decision_roles().deciding_for("signal")
MODEL = load_manifest().offered_models(ROLE.chosen)[0]
#: Above what the scripted model's asks cost and below the most two runs of a small town can.
BOUND = "0.50"


class _SignalModel(FakeTransport):
    """A scripted model deciding signals: it keeps a green whose elapsed seconds are even and
    lets any other end. Every ask is recorded."""

    def __init__(self) -> None:
        super().__init__()
        self.lock = threading.Lock()

    def post_json(self, url, *, headers, payload, timeout):
        with self.lock:
            self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        tool = payload["tools"][0]["function"]
        offered = tool["parameters"]["properties"]["action"]["enum"]
        elapsed = int(
            re.search(r"Green elapsed: (\d+) seconds", payload["messages"][-1]["content"])[1]
        )
        words = ROLE.contract().words
        chosen = words["keep"] if elapsed % 2 == 0 and words["keep"] in offered else words["switch"]
        body = chat_body("", model=payload["model"], finish_reason="tool_calls")
        body["choices"][0]["message"]["content"] = None
        body["choices"][0]["message"]["tool_calls"] = [
            {
                "id": "c",
                "type": "function",
                "function": {"name": tool["name"], "arguments": json.dumps({"action": chosen})},
            }
        ]
        return HttpResponse(200, json.dumps(body))


@pytest.fixture(autouse=True)
def _presets_try_every_candidate(monkeypatch):
    generous = {
        recipe.key: dataclasses.replace(recipe, candidates=CANDIDATES_MAXIMUM)
        for recipe in world_recipes()
    }
    monkeypatch.setattr(recipe_catalog, "_by_key", lambda: MappingProxyType(generous))


@pytest.fixture
def town(tmp_path, repository, spine_schema, monkeypatch) -> Iterator[dict[str, Any]]:
    """The application over one generated small town, as the runtime role, with a scripted model
    deciding signals and the workspace listed for comparisons; the tests play each start with the
    host's own worker, as a process of its own would."""
    _psycopg, scratch = spine_schema
    provision_runtime_role(repository.connection, role=personal.RUNTIME_ROLE)
    provision_runtime_role(repository.connection, role=personal.READER_ROLE, read_only=True)
    database = scratch_role_database(scratch, personal.RUNTIME_ROLE)
    actor = uuid.uuid4()
    workspace = str(repository.workspace_id)
    grants = {
        personal.OWNER_TOKEN: {
            "workspace_id": workspace,
            "actor": str(actor),
            "permissions": EVERY_PERMISSION,
        },
        WRITER_TOKEN: {
            "workspace_id": workspace,
            "actor": str(actor),
            "permissions": [p for p in EVERY_PERMISSION if p != "model.invoke"],
        },
        READER_TOKEN: {
            "workspace_id": workspace,
            "actor": str(actor),
            "permissions": ["world.read"],
        },
        personal.STRANGER_TOKEN: {
            "workspace_id": str(uuid.uuid4()),
            "actor": str(uuid.uuid4()),
            "permissions": EVERY_PERMISSION,
        },
    }
    store = LocalContentAddressedStore(tmp_path / "blobs")
    seed_reviewed_assets(store)
    transport = _SignalModel()
    services = Services(
        database=database,
        readonly_database=scratch_role_database(scratch, personal.READER_ROLE),
        store=store,
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)}),
        executor_shares_the_write_role=False,
        model_client=ModelClient(
            api_key="test-key-not-real",
            manifest=load_manifest(),
            transport=transport,
            budget=BudgetGuard(ceiling_usd=Decimal("5"), max_calls=100_000),
        ),
        society_runtime=SocietyRuntime(
            store=store, authored_bindings=[], reviewed_affordances=reviewed_affordance_registry()
        ),
        society_control_workspaces=(repository.workspace_id,),
        comparisons_played_elsewhere=True,
    )
    with TestClient(create_app(services, verify=False), raise_server_exceptions=False) as client:
        api = personal.Api(client, repository, store, actor, database)
        _identity(monkeypatch, _driven()[0])
        entry = _made(api, "Compared")
        yield {"api": api, "entry": entry, "transport": transport, "repository": repository}


def _path(held: dict[str, Any], suffix: str = "") -> str:
    entry = held["entry"]
    return (
        f"/world/versions/{entry['authored_version_id']}/traffic/comparisons{suffix}"
        f"?world_id={entry['world_id']}"
    )


def _body(**changes: Any) -> dict[str, Any]:
    body = {
        "comparison_id": str(uuid.uuid4()),
        "models": [{"provider": MODEL.provider, "model_id": MODEL.model_id}],
        "seeds": 2,
        "bound_usd": BOUND,
    }
    return {**body, **changes}


def _start(held: dict[str, Any], body: dict[str, Any], token: str = personal.OWNER_TOKEN):
    return held["api"].post(_path(held), body, token=token)


def _read(held: dict[str, Any], comparison_id: str, suffix: str = "", token=personal.OWNER_TOKEN):
    return held["api"].get(_path(held, f"/{comparison_id}{suffix}"), token=token)


def _cancel(held: dict[str, Any], comparison_id: str, token: str = personal.OWNER_TOKEN):
    return held["api"].post(_path(held, f"/{comparison_id}/cancel"), {}, token=token)


def _worker(held: dict[str, Any]):
    return held["api"].client.app.state.services.build_comparison_worker(keeps_share=True)


def _play(held: dict[str, Any]) -> bool:
    return _worker(held).run_once(held["repository"].workspace_id)


def _runs(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {run["run_id"]: run for seed in result["seeds"] for run in seed["runs"].values()}


def _count(held: dict[str, Any], table: str) -> int:
    connection = held["repository"].connection
    row = connection.execute(
        f"select count(*) as n from {table} where workspace_id=%s",
        (held["repository"].workspace_id,),
    ).fetchone()
    connection.commit()
    return int(row["n"] if isinstance(row, dict) else row[0])


def _no_seed(text: str) -> None:
    for seed in signal_catalogs().development_seeds():
        assert seed not in text


def test_a_started_comparison_plays_fixed_timing_then_the_model_and_reads_back(town):
    started = _start(town, _body())
    assert started.status_code == 201, started.text
    (listed,) = started.json()["comparisons"]
    comparison_id = listed["comparison_id"]
    assert (listed["runs"], listed["start"]["state"]) == (4, "waiting")
    assert _play(town) is True
    read = _read(town, comparison_id)
    assert read.status_code == 200, read.text
    result = read.json()
    _no_seed(read.text)
    assert result["start"]["state"] == "finished"
    runs = _runs(result)
    assert {run["status"] for run in runs.values()} == {"completed"}
    assert all(run["progress"] is None for run in runs.values())
    by_arm: dict[str, list[dict[str, Any]]] = {}
    for seed in result["seeds"]:
        for arm, run in seed["runs"].items():
            by_arm.setdefault(arm, []).append(run)
    assert set(by_arm) == {"fixed", "model_a"}
    # The positive control: the model was asked, kept some greens and let others end; the fixed
    # timing asked nobody.
    assert all(run["calls"]["points"] == 0 for run in by_arm["fixed"])
    for run in by_arm["model_a"]:
        assert run["calls"]["asked"] == run["calls"]["points"] > 0
        assert run["calls"]["kept"] > 0 and run["calls"]["let_end"] > 0
        assert run["measure"]["entries"] > 0
    asked = sum(run["calls"]["asked"] for run in by_arm["model_a"])
    assert len(town["transport"].requests) == asked
    # Two development seeds: the difference is read, and never judged.
    assert [(d["first"], d["second"], d["seeds"]) for d in result["differences"]] == [
        ("fixed", "model_a", 2)
    ]
    assert result["verdict"] == {"code": "not_judged", "reason": "development_seeds"}
    spent = sum(Decimal(run["calls"]["cost_usd"]) for run in by_arm["model_a"])
    assert Decimal(result["start"]["spent_usd"]) == spent > 0
    # Nothing of the live world was written: no choice, request, decision or sealed minute.
    for table in (
        "world_traffic_signal_choice",
        "world_traffic_signal_decision_request",
        "world_traffic_signal_decision",
        "world_traffic_signal_segment",
    ):
        assert _count(town, table) == 0, table


def test_a_run_reads_its_receipts_and_replays_from_them_asking_nothing(town):
    started = _start(town, _body(seeds=1))
    assert started.status_code == 201, started.text
    comparison_id = started.json()["comparisons"][0]["comparison_id"]
    assert _play(town) is True
    (model_run,) = [
        run
        for seed in _read(town, comparison_id).json()["seeds"]
        for arm, run in seed["runs"].items()
        if arm == "model_a"
    ]
    run_read = _read(town, comparison_id, f"/runs/{model_run['run_id']}")
    assert run_read.status_code == 200, run_read.text
    _no_seed(run_read.text)
    receipts = run_read.json()["receipts"]
    assert len(receipts) == model_run["calls"]["points"]
    assert {receipt["chose"] for receipt in receipts} == {"keep", "switch"}
    assert all(receipt["provider"]["latency_ms"] >= 0 for receipt in receipts)
    asked = len(town["transport"].requests)
    replayed = _read(town, comparison_id, f"/runs/{model_run['run_id']}/replay")
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["reproduced"] is True
    assert replayed.json()["points"] == len(receipts)
    assert replayed.json()["terms"] == run_read.json()["outcome"]["terms"]
    assert len(town["transport"].requests) == asked, "a replay asks no model"


def test_the_plan_names_what_a_start_would_do_and_writes_nothing(town):
    tables = ("signal_comparison", "signal_comparison_run", "signal_comparison_start")
    before = {table: _count(town, table) for table in tables}
    plain = town["api"].get(_path(town, "/plan"))
    assert plain.status_code == 200, plain.text
    document = plain.json()
    assert document["refusal"] is None and document["plan"] is None
    signals = [row["signal_id"] for row in document["signals"]]
    assert signals and document["seeds_available"] == len(signal_catalogs().development_seeds())
    assert any(model["model_id"] == MODEL.model_id for model in document["models"])
    named = f"&model={MODEL.provider}/{MODEL.model_id}&seeds=2"
    planned = town["api"].get(_path(town, "/plan") + named).json()
    assert planned["plan"]["runs"] == 4
    assert planned["plan"]["asks_most"] == 2 * len(signals) * document["points_most_per_signal"]
    assert Decimal(planned["plan"]["most_usd"]) > Decimal(BOUND)
    one = town["api"].get(_path(town, "/plan") + named + f"&signal={signals[0]}").json()
    assert one["plan"]["asks_most"] == 2 * document["points_most_per_signal"]
    for query, code in (
        ("&signal=not-a-signal", "signal_not_in_world"),
        ("&seeds=9", "seeds_out_of_range"),
    ):
        refused = town["api"].get(_path(town, "/plan") + named + query).json()
        assert refused["plan_refusal"]["code"] == code, query
    assert {table: _count(town, table) for table in tables} == before


def test_a_start_is_refused_by_name_and_the_same_start_again_is_its_answer(town):
    too_much = _start(town, _body(bound_usd="900"))
    assert (too_much.status_code, too_much.json()["code"]) == (422, "bound_out_of_range")
    unknown = _start(town, _body(signals=["not-a-signal"]))
    assert (unknown.status_code, unknown.json()["code"]) == (422, "signal_not_in_world")
    twice = _start(
        town, _body(models=[{"provider": MODEL.provider, "model_id": MODEL.model_id}] * 2)
    )
    assert (twice.status_code, twice.json()["code"]) == (422, "model_named_twice")
    body = _body()
    first = _start(town, body)
    assert first.status_code == 201, first.text
    again = _start(town, body)
    assert again.status_code == 200, again.text
    assert again.json() == first.json()
    other = _start(town, _body())
    assert (other.status_code, other.json()["code"]) == (409, "comparison_running")
    moved = _start(town, {**body, "bound_usd": "0.40"})
    assert (moved.status_code, moved.json()["code"]) == (409, "comparison_conflict")
    # A route addressed by an id answers a credential that may not use it as it answers an
    # unknown id, so the surface is no existence oracle; another workspace learns nothing.
    for token in (WRITER_TOKEN, READER_TOKEN):
        refused = _start(town, _body(), token=token)
        assert (refused.status_code, refused.json()["code"]) == (404, "unknown_reference")
    assert _read(town, body["comparison_id"], token=personal.STRANGER_TOKEN).status_code == 404
    assert _read(town, str(uuid.uuid4())).json()["code"] == "unknown_reference"


def test_a_cancelled_start_closes_and_a_playing_host_stops_before_its_next_ask(town):
    waiting = _start(town, _body()).json()["comparisons"][0]["comparison_id"]
    answered = _cancel(town, waiting)
    assert answered.status_code == 200, answered.text
    start = answered.json()["comparisons"][0]["start"]
    assert (start["state"], start["closed_reason"]) == ("closed", "comparison_cancelled")
    assert {run["failure"] for run in _runs(_read(town, waiting).json()).values()} == {
        "comparison_cancelled"
    }
    assert _cancel(town, waiting).json() == answered.json()
    assert town["transport"].requests == []
    assert _play(town) is False
    # A start a host is playing: cancelled while the host's first ask is in flight.
    playing = _start(town, _body(seeds=1)).json()["comparisons"][0]["comparison_id"]
    transport, post = town["transport"], town["transport"].post_json
    once = threading.Lock()
    cancelled: list[int] = []

    def cancelling(url, *, headers, payload, timeout):
        with once:
            if not cancelled:
                cancelled.append(1)
                connection = town["repository"].connection
                ComparisonFacts(
                    connection,
                    town["repository"].workspace_id,
                    town["entry"]["world_id"],
                    "signal",
                ).cancel(uuid.UUID(playing), uuid.uuid4())
                connection.commit()
        return post(url, headers=headers, payload=payload, timeout=timeout)

    transport.post_json = cancelling
    assert _play(town) is True
    result = _read(town, playing).json()
    runs = {arm: run for seed in result["seeds"] for arm, run in seed["runs"].items()}
    assert runs["fixed"]["status"] == "completed"
    assert (runs["model_a"]["status"], runs["model_a"]["failure"]) == (
        "failed",
        "comparison_cancelled",
    )
    # The one ask in flight was answered and recorded; nothing was asked after it.
    receipts = _read(town, playing, f"/runs/{runs['model_a']['run_id']}").json()["receipts"]
    assert len(receipts) == len(transport.requests) == 1
    assert (result["start"]["state"], result["start"]["closed_reason"]) == (
        "closed",
        "comparison_cancelled",
    )


def test_a_start_whose_host_lease_ran_out_is_cancelled_with_the_ask_it_may_have_paid(town):
    comparison_id = _start(town, _body(seeds=1)).json()["comparisons"][0]["comparison_id"]
    connection = town["repository"].connection
    claim = SocietyComparisonStarts(connection, town["repository"].workspace_id, "signal").claim()
    assert claim is not None and str(claim.comparison_id) == comparison_id
    connection.execute(
        "update signal_comparison_start set lease_expires_at=clock_timestamp()-interval '1 second' "
        "where workspace_id=%s and comparison_id=%s",
        (town["repository"].workspace_id, uuid.UUID(comparison_id)),
    )
    connection.commit()
    answered = _cancel(town, comparison_id)
    assert answered.status_code == 200, answered.text
    start = answered.json()["comparisons"][0]["start"]
    assert (start["state"], start["closed_reason"]) == ("closed", "comparison_cancelled")
    # The host whose lease ran out may have been asking one point of its model run.
    assert Decimal(start["presumed_usd"]) > 0
    assert town["transport"].requests == []


def test_roads_that_changed_since_the_comparison_recorded_them_are_never_played(town, monkeypatch):
    comparison_id = _start(town, _body(seeds=1)).json()["comparisons"][0]["comparison_id"]
    recorded = repository_module.saved_world_roads

    def moved(*args, **kwargs):
        roads = recorded(*args, **kwargs)
        return dataclasses.replace(roads, sha256="0" * 64)

    monkeypatch.setattr(repository_module, "saved_world_roads", moved)
    assert _play(town) is True
    seed = _read(town, comparison_id).json()["seeds"][0]
    # The seed's fixed timing finds the roads changed; its model run, with no anchor, never starts.
    assert {arm: run["failure"] for arm, run in seed["runs"].items()} == {
        "fixed": "roads_changed",
        "model_a": "anchor_failed",
    }
    assert town["transport"].requests == []
