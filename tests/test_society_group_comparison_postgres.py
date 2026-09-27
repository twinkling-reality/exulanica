"""One group's model swapped while everybody else keeps theirs, recorded, scored and read, deployed.

The application connects as a provisioned runtime role over a saved world whose purposeful
society holds its people. The world's owner chooses a model for a group of them and another model
for one person outside it, through the People panel's route. A comparison is defined from that
choice by the runner the local command builds, every arm deciding for the group alone, and run
with two declared models behind a scripted transport. What is shown:

*   the group and everybody else are recorded as the owner's choices name them: a group taken from
    a choice is exactly its people, and the person outside it keeps the model the owner chose, asked
    in every arm, anchors included, while nobody else outside it is asked;
*   a definition whose group is not the choice it names, or whose person outside the group does not
    keep the owner's choice, is refused by name;
*   a seed's anchors run first; a model run waits for both of them, refused by name while either
    has no outcome and closed as failed before it asks when either failed;
*   a model outside the group, which a development comparison may have, is asked in every arm, the
    anchors included, and the served result says so;
*   every model a definition asks is asked under the definition's terms, and a person outside the
    group as the owner's choice it names;
*   a comparison this code cannot read is answered by name, never as a server error;
*   the served result names the group, its source and every other person's decider by the
    manifest's name, and serves what each arm's model answered beside its score;
*   a run of the group arm is read by replaying it from what it stored with no model call, naming
    who decides for each person;
*   a comparison's definition and runs announce every input before the first is authorized.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from exulanica.models.manifest import Role, load_manifest
from exulanica.orchestration.compare import comparison_body
from exulanica.world.society_comparison_repository import SocietyComparisonRepository
from exulanica.world.society_comparison_result import ComparisonRefused
from fastapi.testclient import TestClient

import test_society_authored_world_postgres as helpers
import test_society_comparison_postgres as compared
import test_society_saved_world_api as saved_api
import test_society_stay_requests_api as stays
import test_society_store_reads_under_the_asset_lock as asset_lock
import test_world_arrangements as arrangements
from comparison_support import SEEDS
from test_society_saved_world_api import OWNER

saved_world = helpers.saved_world
app = stays.app
runtime_app = arrangements.runtime_app
pytestmark = pytest.mark.postgres
MANIFEST = load_manifest()
#: The group's documents as served, for the page's parsers
#: (web/packages/app/test/society-comparison-api.test.ts). Rewrite them with
#: EXULANICA_COMPARISON_DOCUMENTS=write and review the diff.
DOCUMENTS = (
    Path(__file__).resolve().parent / "snapshots" / "society-group-comparison-documents.json"
)


def _choose(world, client, people: list[str], model: dict[str, str] | None) -> dict[str, Any]:
    """The world's owner chooses who decides for ``people``, as the People panel does."""
    chosen = client.post(
        f"/world/versions/{world['binding'].version_id}/society/models",
        headers=OWNER,
        params=compared._scope(world),
        json={"idempotency_key": str(uuid.uuid4()), "people": people, "model": model},
    )
    assert chosen.status_code in (200, 201), chosen.text
    return chosen.json()


def _grouped(world, client):
    """People in the world, a group the owner chose the first model for, and one person outside
    it the owner chose the second model for."""
    snapshot = stays._inhabited(world, client)
    people = sorted(person["id"] for person in snapshot["state"]["inhabitants"])
    first, second = compared._models()
    _choose(world, client, people[:2], {"provider": first.provider, "model_id": first.model_id})
    _choose(world, client, [people[2]], {"provider": second.provider, "model_id": second.model_id})
    services = client.app.state.services
    transport = compared._Chooser()
    runner = compared._runner(world, services, transport)
    version = world["binding"].version_id
    group = runner.group_of_choice(version, 1)
    others = runner.others_for(version, group["people"])
    return runner, transport, people, group, others


def _outcome_terms(world, client, comparison_id, arm: str) -> dict[str, Any]:
    """One completed run's recorded terms, read from its outcome as stored."""
    services = client.app.state.services
    with services.database.session(world["workspace"]) as connection:
        row = connection.execute(
            "select document from society_comparison_outcome where workspace_id=%s "
            "and world_id=%s and comparison_id=%s and document->>'arm'=%s",
            (world["workspace"], world["binding"].world_id, comparison_id, arm),
        ).fetchone()
    return row["document"]["terms"]


def _arms(world, client, comparison_id) -> dict[str, uuid.UUID]:
    services = client.app.state.services
    with services.database.session(world["workspace"]) as connection:
        return {
            row["arm"]: row["run_id"]
            for row in connection.execute(
                "select arm, run_id from society_comparison_run where workspace_id=%s "
                "and world_id=%s and comparison_id=%s",
                (world["workspace"], world["binding"].world_id, comparison_id),
            ).fetchall()
        }


def _defined(world, client, *, seeds=SEEDS[:1]):
    runner, transport, people, group, others = _grouped(world, client)
    comparison_id = uuid.uuid4()
    runner.define(
        world["binding"].version_id,
        comparison_id=comparison_id,
        body=comparison_body(
            runner, compared._models(), seeds, control=False, group=group, others=others
        ),
    )
    return runner, transport, people, comparison_id


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_group_is_the_owners_choice_and_everybody_else_keeps_theirs(app):
    world, client = app
    runner, transport, people, comparison_id = _defined(world, client)
    runner.run_all(comparison_id, runner.reserve_all(comparison_id, SEEDS[:1]))
    first, second = compared._models()
    asked = [(r["payload"]["model"], r["payload"]) for r in transport.requests]
    # The positive control: both models were asked.
    assert {model for model, _ in asked} == {first.model_id, second.model_id}
    read = client.get(
        compared._route(world, f"/{comparison_id}"), headers=OWNER, params=compared._scope(world)
    )
    assert read.status_code == 200, read.text
    compared._no_seed(read.text)
    result = read.json()
    assert result["score_version"] == 2
    assert [person["id"] for person in result["group"]["people"]] == people[:2]
    assert result["group"]["source"]["kind"] == "owner_choice"
    assert result["group"]["source"]["choice_seq"] == 1
    others = {other["id"]: other for other in result["others"]}
    assert sorted(others) == people[2:]
    kept = others[people[2]]["decider"]
    assert (kept["model_id"], kept["name"]) == (
        second.model_id,
        MANIFEST.model_name(second.model_id),
    )
    assert others[people[2]]["choice"]["choice_seq"] == 2
    assert all(others[p]["decider"] == {"kind": "routine"} for p in people[3:])
    # Every run completed, and each arm's score is served with what its model answered.
    [seed] = result["seeds"]
    assert {run["status"] for run in seed["runs"].values()} == {"completed"}
    routine = _outcome_terms(world, client, comparison_id, "routine")
    for key in ("model_a", "model_b"):
        reliability = seed["runs"][key]["reliability"]
        assert reliability["turns"] > 0
        # The rates' denominator is the routine run's own count of the group's choice points.
        assert reliability["routine_choice_points"] == routine["choice_points"] > 0
        assert result["summaries"][key]["reliability"]["shares"] is not None
    # The person outside the group was asked of the owner's model in every arm, the anchors too,
    # and the result says so.
    assert result["others_asked"] is True
    runs_asking_second = {
        run["run_id"]
        for run in seed["runs"].values()
        if run["others_calls"] is not None and run["others_calls"]["asked"] > 0
    }
    assert runs_asking_second == {run["run_id"] for run in seed["runs"].values()}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_group_run_is_replayed_with_no_call_naming_each_persons_decider(app):
    world, client = app
    runner, transport, people, comparison_id = _defined(world, client)
    runner.run_all(comparison_id, runner.reserve_all(comparison_id, SEEDS[:1]))
    result = client.get(
        compared._route(world, f"/{comparison_id}"), headers=OWNER, params=compared._scope(world)
    ).json()
    run_id = result["seeds"][0]["runs"]["model_b"]["run_id"]
    calls = len(transport.requests)
    replayed = client.get(
        compared._route(world, f"/{comparison_id}/runs/{run_id}"),
        headers=OWNER,
        params=compared._scope(world),
    )
    assert replayed.status_code == 200, replayed.text
    assert len(transport.requests) == calls, "a replay asks nothing"
    document = replayed.json()
    compared._no_seed(replayed.text)
    deciders = {person["id"]: person for person in document["people"]}
    _first, second = compared._models()
    for subject in people[:2]:
        assert deciders[subject]["in_group"] is True
        assert deciders[subject]["decider"]["model_id"] == second.model_id
    assert deciders[people[2]]["in_group"] is False
    assert deciders[people[2]]["decider"]["model_id"] == second.model_id
    assert all(deciders[p]["decider"] == {"kind": "routine"} for p in people[3:])
    served = {
        "listing": client.get(
            compared._route(world), headers=OWNER, params=compared._scope(world)
        ).json(),
        "result": result,
        "run": document,
    }
    if os.environ.get("EXULANICA_COMPARISON_DOCUMENTS") == "write":
        golden = {**served, "run": compared._cut(document)}
        DOCUMENTS.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    golden = json.loads(DOCUMENTS.read_text(encoding="utf-8"))
    for name, value in served.items():
        assert compared._keys(value) == compared._keys(golden[name]), name


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_group_or_an_owners_choice_the_world_does_not_hold_is_refused_by_name(app):
    world, client = app
    runner, _transport, people, group, others = _grouped(world, client)
    version = world["binding"].version_id
    models = compared._models()
    # The positive control: the choice's own group and the owner's choices are accepted.
    runner.define(
        version,
        comparison_id=uuid.uuid4(),
        body=comparison_body(runner, models, SEEDS[:1], control=False, group=group, others=others),
    )
    wrong_group = {**group, "people": people[:3]}
    with pytest.raises(ComparisonRefused, match="group_not_the_choice"):
        runner.define(
            version,
            comparison_id=uuid.uuid4(),
            body=comparison_body(
                runner,
                models,
                SEEDS[:1],
                control=False,
                group=wrong_group,
                others=[o for o in others if o["id"] != people[2]],
            ),
        )
    forgotten = [
        {**other, "decider": {"kind": "routine"}, "provider_config": None}
        if other["id"] == people[2]
        else other
        for other in others
    ]
    with pytest.raises(ComparisonRefused, match="others_not_the_owners_choice"):
        runner.define(
            version,
            comparison_id=uuid.uuid4(),
            body=comparison_body(
                runner, models, SEEDS[:1], control=False, group=group, others=forgotten
            ),
        )
    # A person outside the group said to keep another of the owner's choices: not the latest.
    earlier = [
        {**other, "choice": {**other["choice"], "choice_seq": 1}}
        if other["id"] == people[2]
        else other
        for other in others
    ]
    with pytest.raises(ComparisonRefused, match="others_not_the_owners_choice"):
        runner.define(
            version,
            comparison_id=uuid.uuid4(),
            body=comparison_body(
                runner, models, SEEDS[:1], control=False, group=group, others=earlier
            ),
        )
    # The owner's model outside the group, asked under another choice's number: not the choice.
    renumbered = [
        {**other, "provider_config": {**other["provider_config"], "choice_seq": 1}}
        if other["id"] == people[2]
        else other
        for other in others
    ]
    with pytest.raises(ComparisonRefused, match="others_not_the_owners_choice"):
        runner.define(
            version,
            comparison_id=uuid.uuid4(),
            body=comparison_body(
                runner, models, SEEDS[:1], control=False, group=group, others=renumbered
            ),
        )
    # And asked under other terms than the definition's: each refused by name.
    for change in (
        {"prompt_version": "society-person-choice/v0"},
        {"deadline_ms": 1},
        {"manifest_sha256": "b" * 64},
        {"contract": {"catalog_versions": {}, "sha256": "0" * 64}},
    ):
        changed = [
            {**other, "provider_config": {**other["provider_config"], **change}}
            if other["id"] == people[2]
            else other
            for other in others
        ]
        with pytest.raises(ComparisonRefused, match="asking_not_the_definitions"):
            runner.define(
                version,
                comparison_id=uuid.uuid4(),
                body=comparison_body(
                    runner, models, SEEDS[:1], control=False, group=group, others=changed
                ),
            )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_model_run_waits_for_both_anchors_of_its_seed_to_complete(app):
    world, client = app
    runner, transport, _people, comparison_id = _defined(world, client)
    run_ids = runner.reserve_all(comparison_id, SEEDS[:1])
    arms = _arms(world, client, comparison_id)
    assert set(arms.values()) == set(run_ids)
    with pytest.raises(ComparisonRefused, match="anchors_first"):
        runner.run(comparison_id, arms["model_a"])
    assert not transport.requests, "nothing was asked for a run refused before it started"
    # Either anchor alone is not enough: the score needs both.
    assert runner.run(comparison_id, arms["wait"])["status"] == "completed"
    asked = len(transport.requests)
    with pytest.raises(ComparisonRefused, match="anchors_first"):
        runner.run(comparison_id, arms["model_a"])
    assert len(transport.requests) == asked
    assert runner.run(comparison_id, arms["routine"])["status"] == "completed"
    assert runner.run(comparison_id, arms["model_a"])["status"] == "completed"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_failed_anchor_closes_its_seeds_model_runs_before_they_ask(app):
    """With no model client, the anchors fail before their first minute, since they ask the model
    the owner chose for somebody outside the group; every model run of the seed is then closed as
    failed, anchor_failed, and asks nothing."""
    world, client = app
    runner, transport, _people, comparison_id = _defined(world, client)
    unasked = dataclasses.replace(runner, client=None)
    outcomes = unasked.run_all(comparison_id, unasked.reserve_all(comparison_id, SEEDS[:1]))
    by_arm = {outcome["arm"]: outcome for outcome in outcomes}
    # The positive control: the anchors did fail, and for the host's reason.
    assert {by_arm[key]["code"] for key in ("routine", "wait")} == {"provider_credential_absent"}
    assert {by_arm[key]["code"] for key in ("model_a", "model_b")} == {"anchor_failed"}
    assert not transport.requests
    result = client.get(
        compared._route(world, f"/{comparison_id}"), headers=OWNER, params=compared._scope(world)
    ).json()
    assert result["verdict"]["code"] == "incomplete"
    assert result["seeds"][0]["runs"]["model_a"]["failure"] == "anchor_failed"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
@pytest.mark.parametrize(
    ("route", "plant", "code"),
    [
        ("result", lambda d: d["scoring"].update(profile="x/binding/v9"), "binding_unknown"),
        (
            "result",
            lambda d: d["scoring"]["catalogs"]["versions"].update({"society-person-score": 9}),
            "catalogs_unavailable",
        ),
        (
            "listing",
            lambda d: d.update(profile="exulanica.society-comparison/v9"),
            "definition_unknown",
        ),
    ],
    ids=["binding", "catalogs", "definition"],
)
def test_a_comparison_this_code_cannot_read_is_answered_by_name(
    app, monkeypatch, route, plant, code
):
    world, client = app
    _runner, _transport, _people, comparison_id = _defined(world, client)
    path = compared._route(world, "" if route == "listing" else f"/{comparison_id}")
    # The positive control: the comparison as recorded is read.
    assert client.get(path, headers=OWNER, params=compared._scope(world)).status_code == 200

    def planted(rows):
        for row in rows:
            plant(row["document"])
        return rows

    read_one = SocietyComparisonRepository.definition
    read_all = SocietyComparisonRepository.definitions
    monkeypatch.setattr(
        SocietyComparisonRepository,
        "definition",
        lambda self, *args: planted([copy.deepcopy(read_one(self, *args))])[0],
    )
    monkeypatch.setattr(
        SocietyComparisonRepository,
        "definitions",
        lambda self, *args: planted(copy.deepcopy(read_all(self, *args))),
    )
    answered = client.get(path, headers=OWNER, params=compared._scope(world))
    assert answered.status_code == 409, answered.text
    assert answered.json()["code"] == code


@asset_lock.CURRENT_GROUND
def test_a_group_comparison_over_two_inputs_reads_nothing_under_the_lock(
    runtime_app, monkeypatch, caplog
):
    """A group comparison's definition authorizes its frozen input, and each of its runs every
    input from the first to the one it froze, in one transaction. The second input names an asset
    the first does not, so every input is announced and read first, and none is unannounced."""
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        saved_api.place(client, world, "object:cushion", 3_000, 5_000)
        brought = saved_api.bring_inhabitants(client, world)
        assert brought.status_code in (200, 201), brought.text
        saved_api.place(client, world, "object:second", -3_000, 5_000, asset="pillar")
        people = sorted(
            person["id"] for person in asset_lock._state(client, world)["state"]["inhabitants"]
        )
        services = client.app.state.services
        runner = dataclasses.replace(
            compared._runner(world, services, compared._Chooser()), client=None
        )
        group = {"people": people[:2], "source": {"kind": "named"}}
        others = runner.others_for(world["binding"].version_id, group["people"])
        reads = asset_lock._reads(world, client, monkeypatch)
        comparison_id = uuid.uuid4()
        with caplog.at_level(logging.ERROR):
            runner.define(
                world["binding"].version_id,
                comparison_id=comparison_id,
                body=comparison_body(
                    runner,
                    [
                        compared.ComparisonArm(spec.provider, spec.model_id)
                        for spec in MANIFEST.offered_models(Role.SOCIETY_DECISION)[:1]
                    ],
                    SEEDS[:1],
                    control=False,
                    group=group,
                    others=others,
                ),
            )
            run_ids = runner.reserve_all(comparison_id, SEEDS[:1])
            # The anchors ask nobody here; a model arm with no client fails before its first
            # minute. Each run is planned in one transaction over both inputs.
            outcomes = runner.run_all(comparison_id, run_ids)
    assert {outcome["status"] for outcome in outcomes} == {"completed", "failed"}
    with services.database.session(world["workspace"]) as connection:
        plan, _definition = runner._repository(connection).plan(comparison_id, run_ids[0])
    assert len(plan.inputs) == 2, "the runs are planned over both inputs"
    assert caplog.records == [], [record.getMessage() for record in caplog.records]
    assert reads.under_the_lock == []
    assert asset_lock._society_read_its_bytes(reads)
