"""A comparison of a saved world's society of things, defined, run and read against PostgreSQL.

Two knights and a sword are placed in a saved world whose society of things runs the hands module.
Until a reading line is measured for a society of things, a comparison of one is refused by name
(``no_reading_line``) where it is defined and where the application plans or starts one. With a
line in the reading catalog (a test's), a development comparison of the knights is defined under
the sixth score and the terms the society of things asks its people under, run through the
product's client against a scripted model, and read: the routine scores one, waiting zero, the
model's runs record the acts its knights did, and a run is read by replaying what it stored with
no model call.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from exulanica.api.society_comparison_runner import ComparisonArm
from exulanica.models.manifest import load_manifest
from exulanica.orchestration.compare import comparison_body
from exulanica.world import society_comparison_reading as reading
from exulanica.world.crossings import register_crossing_stream
from exulanica.world.society_comparison_verdict import ComparisonRefused
from exulanica.world.society_decision_contract import person_role
from exulanica.world.society_things import THINGS_PROFILE

import test_outside_deciders_postgres as outside
import test_society_comparison_postgres as compared
import test_society_stay_requests_api as stays
import test_society_things_postgres as things_api
import things_society_support as things_support
from comparison_support import SEEDS
from model_fakes import FakeTransport, chat_body
from test_society_saved_world_api import OWNER

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres


class _Handing(FakeTransport):
    """A scripted model that picks the sword up or hands it over when it may, else says one line,
    else goes to the first place offered."""

    def post_json(self, url, *, headers, payload, timeout):
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        properties = payload["tools"][0]["function"]["parameters"]["properties"]
        labels = properties["action"]["enum"]
        chosen = next(
            (
                label
                for label in labels
                if label.startswith(("pick up the sword", "give the sword"))
            ),
            next(
                (label for label in labels if label.startswith("say something to every")),
                next((label for label in labels if " m away" in label), labels[0]),
            ),
        )
        arguments: dict[str, Any] = {"action": chosen}
        if "line" in properties:
            arguments["line"] = "Fine weather for it." if chosen.startswith("say") else None
        body = chat_body("", model=payload["model"], finish_reason="tool_calls")
        body["choices"][0]["message"]["content"] = None
        body["choices"][0]["message"]["tool_calls"] = [
            {
                "id": "c",
                "type": "function",
                "function": {"name": "act", "arguments": json.dumps(arguments)},
            }
        ]
        return compared.HttpResponse(200, json.dumps(body))


def _knights(client, world, *, gate: bool = False) -> list[str]:
    client.app.state.services = dataclasses.replace(
        client.app.state.services, societies_of_things=True
    )
    things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
    things_api._place(client, world, "knight", "knight", 1, 3_000, 3_000)
    things_api._place(client, world, "knight-2", "knight", 1, 5_000, 3_000)
    things_api._place(client, world, "sword", "sword", 2, 3_400, 2_600)
    if gate:
        things_api._place(client, world, "gate", "gate", 1, 0, 6_000)
    snapshot = things_api._make_society(client, world)
    return sorted(p["id"] for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed")


def _model() -> ComparisonArm:
    [spec] = load_manifest().offered_models(person_role().chosen)[:1]
    return ComparisonArm(spec.provider, spec.model_id)


def _runner(world, client, transport):
    runner = compared._runner(world, client.app.state.services, transport)
    return dataclasses.replace(runner, engine=THINGS_PROFILE)


def _group(knights: list[str]) -> dict[str, Any]:
    return {"people": knights, "source": {"kind": "named"}}


def _things_line(tmp_path: Path) -> Path:
    """The shipped reading catalog with a test's line for a society of things beside its own."""
    document = json.loads(reading.READING_CATALOG.read_text(encoding="utf-8"))
    living = next(entry for entry in document["entries"] if entry["key"] == "living")
    document["entries"].append({**living, "key": "things", "state_family": "things"})
    path = tmp_path / "society-comparison-reading.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_society_of_things_is_not_compared_until_a_reading_line_is_measured(app):
    world, client = app
    knights = _knights(client, world)
    runner = _runner(world, client, _Handing())
    with pytest.raises(ComparisonRefused) as refused:
        runner.define(
            world["binding"].version_id,
            comparison_id=uuid.uuid4(),
            body=comparison_body(
                runner, [_model()], SEEDS[:1], control=False, group=_group(knights)
            ),
        )
    assert refused.value.code == reading.NO_READING_LINE
    # The application's plan names the refusal for the hour, and a start meets it.
    plan = client.get(
        compared._route(world, "/plan"),
        headers=OWNER,
        params={**compared._scope(world), "model": f"{_model().provider}/{_model().model_id}"},
    )
    assert plan.status_code == 200, plan.text
    hour = next(window for window in plan.json()["windows"] if window["window"] == "hour")
    assert hour["refusal"]["code"] == reading.NO_READING_LINE


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_development_comparison_of_a_society_of_things_runs_and_reads(app, monkeypatch, tmp_path):
    world, client = app
    monkeypatch.setattr(reading, "READING_CATALOG", _things_line(tmp_path))
    knights = _knights(client, world)
    transport = _Handing()
    runner = _runner(world, client, transport)
    comparison_id = uuid.uuid4()
    definition = runner.define(
        world["binding"].version_id,
        comparison_id=comparison_id,
        body=comparison_body(
            runner,
            [_model()],
            SEEDS,
            control=False,
            group=_group(knights),
            others=runner.others_for(world["binding"].version_id, knights),
        ),
    )
    document = definition.get("document", definition)
    assert document["scoring"]["profile"] == "exulanica.society-comparison-binding/v6"
    role = person_role()
    asked = role.contract(role.terms(THINGS_PROFILE).versions).binding()
    assert document["contract"] == asked
    runner.run_all(comparison_id, runner.reserve_all(comparison_id, SEEDS))
    # The positive control: the model was asked, through the product's client.
    assert transport.requests
    read = client.get(
        compared._route(world, f"/{comparison_id}"), headers=OWNER, params=compared._scope(world)
    )
    assert read.status_code == 200, read.text
    result = read.json()
    summaries = result["summaries"]
    assert (summaries["routine"]["mean_score"], summaries["wait"]["mean_score"]) == (
        "1.0000",
        "0.0000",
    )
    assert summaries["model_a"]["mean_score"] is not None
    # A run is read by replaying what it stored, with no model call.
    before = len(transport.requests)
    run = next(iter(result["seeds"]))["runs"]["model_a"]
    drawn = client.get(
        compared._route(world, f"/{comparison_id}/runs/{run['run_id']}"),
        headers=OWNER,
        params=compared._scope(world),
    )
    assert drawn.status_code == 200, drawn.text
    assert len(transport.requests) == before


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_visitor_is_never_in_a_comparison(app, monkeypatch, tmp_path):
    """A run starts at the society's genesis, where nobody has crossed in, so the plan lists only
    the world's own beings and a group naming a visitor is refused by name."""
    world, client = app
    monkeypatch.setattr(reading, "READING_CATALOG", _things_line(tmp_path))
    knights = _knights(client, world, gate=True)
    stream = things_support.MemoryCrossings()
    register_crossing_stream(stream)
    try:
        scope = compared._scope(world)
        listed = client.get(
            f"/world/versions/{world['binding'].version_id}/society", headers=OWNER, params=scope
        ).json()
        stream.hand(
            uuid.UUID(listed["society_id"]), things_support.arrival(1, grant_id=outside.GRANT)
        )
        snapshot = stays._step(world, client, listed)
        [visitor] = [p["id"] for p in snapshot["state"]["inhabitants"] if p["came_by"] == "crossed"]
    finally:
        register_crossing_stream(None)
    plan = client.get(compared._route(world, "/plan"), headers=OWNER, params=scope)
    assert plan.status_code == 200, plan.text
    people = {person["id"] for person in plan.json()["people"]}
    assert set(knights) <= people and visitor not in people
    runner = _runner(world, client, _Handing())
    with pytest.raises(ComparisonRefused) as refused:
        runner.define(
            world["binding"].version_id,
            comparison_id=uuid.uuid4(),
            body=comparison_body(
                runner,
                [_model()],
                SEEDS[:1],
                control=False,
                group=_group(sorted([*knights, visitor])),
                others=runner.others_for(world["binding"].version_id, sorted([*knights, visitor])),
            ),
        )
    assert refused.value.code == "group_visitor"
