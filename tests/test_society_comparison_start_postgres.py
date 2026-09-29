"""A comparison a world's owner starts from the application, played by a host, as deployed.

The application connects as a provisioned runtime role over a saved world whose purposeful society
holds its people, with a model client behind a scripted transport, the tests' development seeds and
the workspace listed as one this host asks models for. What is shown:

*   the plan route serves the role, groups and models a comparison may be given and, for a
    selection, its runs, the most it can cost, derived from the manifest's prices, and what one
    like it typically cost, writing nothing;
*   a start defines the comparison, reserves every run and records its start in one transaction;
    the same start sent again is answered with it, another body under its id is a conflict, and a
    world plays one started comparison at a time;
*   every refusal of a start is named, and a refused start records nothing;
*   only a caller holding both ``world.write`` and ``model.invoke``, the world's owner in a
    browser, starts one;
*   a comparison id is keyed within its workspace: another workspace naming the same id starts a
    comparison of its own, and neither learns of the other's;
*   the host's worker plays a start to its end, and the reads serve its progress and its spend;
*   the bound the owner stated stops a run by name before a minute it no longer fits;
*   a host that stops part way is closed by the next claim, which records the run it left as
    interrupted and asks nothing again; claims that keep finishing nothing close the start, and a
    host that finished a run before it stopped, however it stopped, never counts as one of them;
*   a claim that takes over a lease that ran out counts the minute the stopped host may have been
    asking and never recorded against the bound, and keeps what it presumed, which only grows;
*   a server that plays no comparison, here or in a process of its own, starts none.
"""

from __future__ import annotations

import dataclasses
import json
import os
import threading
import uuid
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.decision_host import ask_bound_usd
from exulanica.api.services import Services
from exulanica.api.society_comparison_start import typical_per_person_hour
from exulanica.api.society_runtime import AuthoredWorldSocietyBinding, SocietyRuntime
from exulanica.db.roles import provision_runtime_role
from exulanica.db.session import set_workspace
from exulanica.ingest.repository import IngestRepository
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from exulanica.world.society_comparison_start_repository import SocietyComparisonStarts
from exulanica.world.society_controls import MAX_CLAIM_ATTEMPTS
from exulanica.world.society_decision_contract import person_role
from exulanica.world.starter import AUTHORED_GROUND_MODULE_VERSION, AUTHORED_STARTER_REGION_ID
from fastapi.testclient import TestClient

import test_society_authored_world_postgres as helpers
import test_society_comparison_postgres as compared
import test_society_stay_requests_api as stays
from comparison_support import SEEDS, seeded_catalogs
from conftest import open_scratch_connection, scratch_role_database
from test_society_saved_world_api import FACING_THE_PERSON, OWNER, TOKEN
from tests_support_api import EVERY_PERMISSION

saved_world = helpers.saved_world
pytestmark = pytest.mark.postgres
ROLE = "exulanica_comparison_start_suite"
WRITER_TOKEN = "comparison-start-writer-without-models-token-long-enough"
READER_TOKEN = "comparison-start-reader-token-long-enough-for-grants"
OTHER_TOKEN = "comparison-start-other-workspace-token-long-enough"
WRITER = {"Authorization": f"Bearer {WRITER_TOKEN}"}
READER = {"Authorization": f"Bearer {READER_TOKEN}"}
OTHER = {"Authorization": f"Bearer {OTHER_TOKEN}"}
MANIFEST = load_manifest()
#: The model the scripted transport answers for: the first the manifest offers a person.
MODEL = MANIFEST.offered_models(person_role().chosen)[0]
#: The bound every start here states unless it says otherwise: well above what the scripted
#: model's asks cost, and below what the hour could cost at most.
BOUND = "0.05"


def _second_world(spine_schema, store, registry) -> dict[str, Any]:
    """A saved world of another workspace, as the saved_world fixture makes one."""
    psycopg, scratch = spine_schema
    connection = open_scratch_connection(psycopg, scratch)
    workspace = uuid.uuid4()
    repository = IngestRepository(connection, workspace)
    actor = uuid.uuid4()
    world_id = f"world:authored:{uuid.uuid4()}"
    with connection.transaction():
        snapshot_id, version_id = helpers.make_starter(
            connection, workspace, actor, world_id, AUTHORED_GROUND_MODULE_VERSION
        )
    place = uuid.uuid4()
    connection.execute("insert into place(workspace_id,place_id) values(%s,%s)", (workspace, place))
    connection.commit()
    binding = AuthoredWorldSocietyBinding(
        binding_id="comparison-start-second-world-v1",
        workspace_id=workspace,
        world_id=world_id,
        version_id=version_id,
        source_snapshot_id=snapshot_id,
        place_id=place,
        region_id=AUTHORED_STARTER_REGION_ID,
    )
    return {
        "connection": repository.connection,
        "workspace": workspace,
        "actor": actor,
        "world_id": world_id,
        "binding": binding,
        "store": store,
        "registry": registry,
    }


@pytest.fixture
def started(saved_world, spine_schema, monkeypatch):
    """The application over the saved world and another workspace's, as the runtime role, with a
    scripted model, the tests' seeds and both workspaces listed."""
    world = saved_world
    world["connection"].commit()
    _psycopg, scratch = spine_schema
    provision_runtime_role(world["connection"], role=ROLE)
    database = scratch_role_database(scratch, ROLE)
    other = _second_world(spine_schema, world["store"], world["registry"])
    grants = {
        TOKEN: (world["workspace"], world["session"].actor, EVERY_PERMISSION),
        WRITER_TOKEN: (
            world["workspace"],
            world["session"].actor,
            [p for p in EVERY_PERMISSION if p != "model.invoke"],
        ),
        READER_TOKEN: (world["workspace"], world["session"].actor, ["world.read"]),
        OTHER_TOKEN: (other["workspace"], other["actor"], EVERY_PERMISSION),
    }
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                token: {"workspace_id": str(ws), "actor": str(actor), "permissions": held}
                for token, (ws, actor, held) in grants.items()
            }
        ),
    )
    runtime = SocietyRuntime(
        store=world["store"], authored_bindings=[], reviewed_affordances=world["registry"]
    )
    transport = compared._Chooser()
    services = Services(
        database=database,
        readonly_database=database,
        store=world["store"],
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=ModelClient(
            api_key="test-key-not-real",
            manifest=MANIFEST,
            transport=transport,
            budget=BudgetGuard(ceiling_usd=Decimal("5"), max_calls=100_000),
        ),
        society_runtime=runtime,
        society_control_workspaces=(world["workspace"], other["workspace"]),
        comparison_seeds=tuple(SEEDS),
        comparison_catalogs=seeded_catalogs(),
        # The tests play each start with their own worker, as a process of its own would.
        comparisons_played_elsewhere=True,
    )
    with TestClient(create_app(services, verify=False), raise_server_exceptions=False) as client:
        yield {"world": world, "other": other, "client": client, "transport": transport}
    other["connection"].close()


def _comparisons(world: dict[str, Any]) -> str:
    return f"/world/versions/{world['binding'].version_id}/society/comparisons"


def _scope(world: dict[str, Any]) -> dict[str, str]:
    return {"world_id": world["binding"].world_id}


def _body(**changes: Any) -> dict[str, Any]:
    body = {
        "comparison_id": str(uuid.uuid4()),
        "role": person_role().key,
        "group": {"kind": "everyone"},
        "models": [{"provider": MODEL.provider, "model_id": MODEL.model_id}],
        "control": False,
        "seeds": 1,
        "bound_usd": BOUND,
    }
    return {**body, **changes}


def _start(held: dict[str, Any], body: dict[str, Any], headers=OWNER, world=None):
    world = world or held["world"]
    return held["client"].post(
        _comparisons(world), headers=headers, params=_scope(world), json=body
    )


def _counts(world: dict[str, Any]) -> dict[str, int]:
    """How many definitions, runs and starts the world's workspace holds, read as its owner."""
    connection = world["connection"]
    set_workspace(connection, world["workspace"])
    return {
        table: connection.execute(
            f"select count(*) as n from {table} where workspace_id=%s and world_id=%s",
            (world["workspace"], world["binding"].world_id),
        ).fetchone()["n"]
        for table in ("society_comparison", "society_comparison_run", "society_comparison_start")
    }


def _listing(held: dict[str, Any], world=None, headers=OWNER) -> list[dict[str, Any]]:
    world = world or held["world"]
    read = held["client"].get(_comparisons(world), headers=headers, params=_scope(world))
    assert read.status_code == 200, read.text
    return read.json()["comparisons"]


def _worker(held: dict[str, Any]):
    return held["client"].app.state.services.build_comparison_worker(keeps_share=True)


def _population(held: dict[str, Any]) -> int:
    world = held["world"]
    society = held["client"].get(
        f"/world/versions/{world['binding'].version_id}/society",
        headers=OWNER,
        params=_scope(world),
    )
    return len(society.json()["state"]["inhabitants"])


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_plan_offers_what_a_start_takes_and_writes_nothing(started):
    world, client = started["world"], started["client"]
    stays._inhabited(world, client)
    offered = client.get(_comparisons(world) + "/plan", headers=READER, params=_scope(world))
    assert offered.status_code == 200, offered.text
    document = offered.json()
    assert document["refusal"] is None and document["running"] is None
    assert document["seeds_available"] == len(SEEDS) and document["plan"] is None
    (role,) = document["roles"]
    assert (role["key"], role["subject"]) == (person_role().key, "person")
    # Nothing of what this process's budget has left, which every workspace's spend moves: only a
    # caller who may start one learns it, from a start whose bound exceeds it.
    assert set(role) == {"key", "subject", "groups", "models"}
    population = _population(started)
    assert role["groups"][0] == {
        "kind": "everyone",
        "choice_seq": None,
        "size": population,
        "people": None,
        "model": None,
    }
    models = {model["model_id"]: model for model in role["models"]}
    assert models[MODEL.model_id]["refusal"] is None
    typical = typical_per_person_hour()
    assert models[MODEL.model_id]["typical_usd_per_person_hour"] == format(
        typical[MODEL.model_id], "f"
    )
    planned = client.get(
        _comparisons(world) + "/plan",
        headers=READER,
        params={
            **_scope(world),
            "role": person_role().key,
            "group": "everyone",
            "model": f"{MODEL.provider}/{MODEL.model_id}",
            "seeds": 2,
        },
    ).json()
    assert planned["plan_refusal"] is None
    plan = planned["plan"]
    # The routine, waiting and the model on each of two seeds; only the model's runs ask.
    bound = ask_bound_usd(
        person_role(), BudgetGuard(ceiling_usd=Decimal(1)), MODEL, person_role().contract()
    )
    assert plan["runs"] == 6
    assert plan["asks_most"] == 2 * 60 * population
    assert Decimal(plan["most_usd"]) == 2 * 60 * population * bound
    assert Decimal(plan["typical_usd"]) == (2 * population * typical[MODEL.model_id]).quantize(
        Decimal("0.00000001")
    )
    assert _counts(world) == {
        "society_comparison": 0,
        "society_comparison_run": 0,
        "society_comparison_start": 0,
    }


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_start_is_defined_reserved_and_recorded_once(started):
    world = started["world"]
    stays._inhabited(world, started["client"])
    body = _body()
    first = _start(started, body)
    assert first.status_code == 201, first.text
    (listed,) = first.json()["comparisons"]
    assert listed["comparison_id"] == body["comparison_id"]
    assert (listed["runs"], listed["runs_finished"]) == (3, 0)
    assert listed["start"]["state"] == "waiting"
    assert Decimal(listed["start"]["bound_usd"]) == Decimal(BOUND)
    counts = _counts(world)
    assert counts == {
        "society_comparison": 1,
        "society_comparison_run": 3,
        "society_comparison_start": 1,
    }
    again = _start(started, body)
    assert again.status_code == 200, again.text
    assert again.json()["comparisons"][0]["comparison_id"] == body["comparison_id"]
    assert _counts(world) == counts
    other_bound = _start(started, {**body, "bound_usd": "0.04"})
    assert (other_bound.status_code, other_bound.json()["code"]) == (409, "comparison_conflict")
    running = _start(started, _body())
    assert (running.status_code, running.json()["code"]) == (409, "comparison_running")
    assert _counts(world) == counts


def _refused_bodies(people: list[str]) -> dict[str, tuple[dict[str, Any], int, str]]:
    """Each refusal a start of this world meets, by its code, with the body that meets it."""
    model = {"provider": MODEL.provider, "model_id": MODEL.model_id}
    return {
        "role_not_registered": (_body(role="nobody_decides"), 422, "role_not_registered"),
        "model_not_offered": (
            _body(models=[{"provider": MODEL.provider, "model_id": "no/such-model"}]),
            422,
            "model_not_offered",
        ),
        "model_named_twice": (_body(models=[model, model]), 422, "model_named_twice"),
        "group_empty": (_body(group={"kind": "named", "people": []}), 422, "group_empty"),
        "group_person_unknown": (
            _body(group={"kind": "named", "people": [str(uuid.uuid4())]}),
            422,
            "group_person_unknown",
        ),
        "choice_unknown": (
            _body(group={"kind": "owner_choice", "choice_seq": 99}),
            422,
            "choice_unknown",
        ),
        "seeds_out_of_range": (_body(seeds=len(SEEDS) + 1), 422, "seeds_out_of_range"),
        "bound_out_of_range": (_body(bound_usd="100000"), 422, "bound_out_of_range"),
        "bound_zero": (_body(bound_usd="0"), 422, "bound_out_of_range"),
        "named_group_of_people_here": (
            _body(group={"kind": "named", "people": people[:1]}),
            201,
            "",
        ),
    }


@pytest.mark.parametrize(
    "case",
    [
        "role_not_registered",
        "model_not_offered",
        "model_named_twice",
        "group_empty",
        "group_person_unknown",
        "choice_unknown",
        "seeds_out_of_range",
        "bound_out_of_range",
        "bound_zero",
        "named_group_of_people_here",
    ],
)
@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_each_refusal_of_a_start_is_named_and_records_nothing(started, case):
    world = started["world"]
    snapshot = stays._inhabited(world, started["client"])
    people = sorted(person["id"] for person in snapshot["state"]["inhabitants"])
    body, status, code = _refused_bodies(people)[case]
    answered = _start(started, body)
    assert answered.status_code == status, answered.text
    if status == 201:
        # The positive control: a body the refusals do not cover is started.
        assert _counts(world)["society_comparison_start"] == 1
        return
    assert answered.json()["code"] == code
    assert _counts(world) == {
        "society_comparison": 0,
        "society_comparison_run": 0,
        "society_comparison_start": 0,
    }


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_server_not_set_up_or_asking_no_model_here_starts_nothing(started):
    world, client = started["world"], started["client"]
    stays._inhabited(world, client)
    services = client.app.state.services
    client.app.state.services = dataclasses.replace(services, comparison_seeds=())
    unset = _start(started, _body())
    assert (unset.status_code, unset.json()["code"]) == (409, "comparisons_not_set_up")
    client.app.state.services = dataclasses.replace(services, society_control_workspaces=())
    unlisted = _start(started, _body())
    assert (unlisted.status_code, unlisted.json()["code"]) == (409, "comparisons_not_run_here")
    # The process budget of a host playing comparisons itself, with a bound it cannot hold.
    client.app.state.services = dataclasses.replace(
        services,
        runs_comparison_worker=True,
        model_client=ModelClient(
            api_key="test-key-not-real",
            manifest=MANIFEST,
            transport=started["transport"],
            budget=BudgetGuard(ceiling_usd=Decimal("0.02"), max_calls=100_000),
        ),
    )
    over = _start(started, _body(bound_usd="0.015"))
    assert (over.status_code, over.json()["code"]) == (409, "bound_over_budget")
    client.app.state.services = services
    assert _counts(world)["society_comparison_start"] == 0
    assert _start(started, _body()).status_code == 201


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_only_a_caller_that_may_ask_models_starts_one(started):
    world, client = started["world"], started["client"]
    stays._inhabited(world, client)
    for headers in (WRITER, READER):
        # A route addressed by an id answers a credential that may not use it as it answers an
        # unknown id, so the surface is no existence oracle.
        refused = _start(started, _body(), headers=headers)
        assert (refused.status_code, refused.json()["code"]) == (404, "unknown_reference")
    planned = client.get(_comparisons(world) + "/plan", headers=READER, params=_scope(world))
    assert planned.status_code == 200, planned.text
    assert _counts(world)["society_comparison_start"] == 0
    assert _start(started, _body()).status_code == 201


def _inhabit_other(started: dict[str, Any]) -> None:
    """Places to go and people brought into the other workspace's world, as its owner does."""
    other, client = started["other"], started["client"]
    version = f"/world/versions/{other['binding'].version_id}"
    for index, (x_mm, z_mm) in enumerate(((3_000, 5_000), (-3_000, 5_000), (0, 9_000))):
        base = client.get(version, headers=OTHER, params=_scope(other)).json()["state_sha256"]
        placed = client.post(
            version + "/objects",
            headers=OTHER,
            params=_scope(other),
            json={
                "base_state_sha256": base,
                "object_id": f"object:plate-{index}",
                "asset_sha256": started["world"]["plate"].content_sha256,
                "region_id": other["binding"].region_id,
                "transform": {
                    "x_mm": x_mm,
                    "y_mm": 0,
                    "z_mm": z_mm,
                    "yaw_microradians": FACING_THE_PERSON,
                    "scale_milli": 1000,
                },
                "origin_role": "fictional",
            },
        )
        assert placed.status_code == 201, placed.text
    created = client.post(
        f"/world/versions/{other['binding'].version_id}/society",
        headers=OTHER,
        params=_scope(other),
        json={"region_id": other["binding"].region_id, "profile": "exulanica-society/v2"},
    )
    assert created.status_code in (200, 201), created.text


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_another_workspaces_comparison_id_neither_conflicts_nor_reveals(started):
    world, other = started["world"], started["other"]
    stays._inhabited(world, started["client"])
    _inhabit_other(started)
    body = _body()
    assert _start(started, body).status_code == 201
    theirs = _start(started, body, headers=OTHER, world=other)
    assert theirs.status_code == 201, theirs.text
    (listed,) = theirs.json()["comparisons"]
    assert listed["comparison_id"] == body["comparison_id"]
    assert listed["start"]["state"] == "waiting"
    ours = _listing(started)
    assert [entry["comparison_id"] for entry in ours] == [body["comparison_id"]]
    assert _listing(started, world=other, headers=OTHER)[0]["created_at"] != ours[0]["created_at"]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_worker_plays_a_start_to_its_end_and_the_reads_serve_its_progress(started):
    world = started["world"]
    stays._inhabited(world, started["client"])
    body = _body()
    assert _start(started, body).status_code == 201
    worker = _worker(started)
    assert worker.run_once(world["workspace"]) is True
    assert worker.run_once(world["workspace"]) is False
    (listed,) = _listing(started)
    assert (listed["runs"], listed["runs_finished"], listed["runs_completed"]) == (3, 3, 3)
    assert listed["start"]["state"] == "finished" and listed["start"]["closed_reason"] is None
    assert Decimal(listed["start"]["spent_usd"]) > 0
    assert started["transport"].requests, "the model arm asked the scripted model"
    result = (
        started["client"]
        .get(_comparisons(world) + f"/{body['comparison_id']}", headers=OWNER, params=_scope(world))
        .json()
    )
    assert result["start"]["state"] == "finished"
    assert {seed["runs"]["model_a"]["status"] for seed in result["seeds"]} == {"completed"}


def _one_ask() -> Decimal:
    """The most one ask of the scripted model can cost, as the runner and the bound judge it."""
    return ask_bound_usd(
        person_role(), BudgetGuard(ceiling_usd=Decimal(1)), MODEL, person_role().contract()
    )


def _model_run(started: dict[str, Any], comparison_id: str) -> tuple[dict, dict]:
    world = started["world"]
    result = (
        started["client"]
        .get(_comparisons(world) + f"/{comparison_id}", headers=OWNER, params=_scope(world))
        .json()
    )
    (seed,) = result["seeds"]
    return seed["runs"]["model_a"], result


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_bound_that_holds_no_ask_stops_the_run_before_it_asks(started):
    world = started["world"]
    stays._inhabited(world, started["client"])
    body = _body(bound_usd=format((_one_ask() / 2).quantize(Decimal("0.00000001")), "f"))
    assert _start(started, body).status_code == 201, body
    assert _worker(started).run_once(world["workspace"]) is True
    run, result = _model_run(started, body["comparison_id"])
    assert (run["status"], run["failure"]) == ("failed", "comparison_bound_spent")
    assert {result["seeds"][0]["runs"][arm]["status"] for arm in ("routine", "wait")} == {
        "completed"
    }
    assert result["start"]["state"] == "finished"
    assert not started["transport"].requests, "nothing was asked past the bound"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_what_a_comparison_spends_stays_within_its_bound(started):
    world = started["world"]
    stays._inhabited(world, started["client"])
    bound = (_one_ask() * 3).quantize(Decimal("0.00000001"))
    body = _body(bound_usd=format(bound, "f"))
    assert _start(started, body).status_code == 201, body
    assert _worker(started).run_once(world["workspace"]) is True
    run, result = _model_run(started, body["comparison_id"])
    # The scripted model's asks cost less than their bounds, so the run asks for a while, and the
    # bound stops it by name before what it spent passes the bound.
    assert (run["status"], run["failure"]) == ("failed", "comparison_bound_spent")
    assert started["transport"].requests
    assert Decimal(0) < Decimal(result["start"]["spent_usd"]) <= bound


def _expire_the_lease(world: dict[str, Any], comparison_id: str) -> None:
    """What a host that stopped leaves: a lease that has run out."""
    connection = world["connection"]
    set_workspace(connection, world["workspace"])
    with connection.transaction():
        connection.execute(
            "update society_comparison_start set lease_expires_at=clock_timestamp()-interval '1 "
            "second',claimed_at=clock_timestamp()-interval '31 seconds' where workspace_id=%s "
            "and world_id=%s and comparison_id=%s",
            (world["workspace"], world["binding"].world_id, comparison_id),
        )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_host_that_stops_part_way_is_closed_by_the_next_claim(started, monkeypatch):
    world = started["world"]
    stays._inhabited(world, started["client"])
    body = _body()
    assert _start(started, body).status_code == 201
    renewals = []
    renew = SocietyComparisonStarts.renew

    def stops_after_some_minutes(self, claim):
        # The host stops a few minutes into the model's run, after its first receipts.
        renewals.append(claim.token)
        return len(renewals) <= 2 * 61 + 5 and renew(self, claim)

    monkeypatch.setattr(SocietyComparisonStarts, "renew", stops_after_some_minutes)
    assert _worker(started).run_once(world["workspace"]) is True
    asked = len(started["transport"].requests)
    assert asked > 0
    (listed,) = _listing(started)
    assert listed["runs_finished"] == 2 and listed["start"]["state"] == "running"
    monkeypatch.setattr(SocietyComparisonStarts, "renew", renew)
    _expire_the_lease(world, body["comparison_id"])
    assert _worker(started).run_once(world["workspace"]) is True
    assert len(started["transport"].requests) == asked, "nothing is asked again"
    result = (
        started["client"]
        .get(_comparisons(world) + f"/{body['comparison_id']}", headers=OWNER, params=_scope(world))
        .json()
    )
    (seed,) = result["seeds"]
    assert (seed["runs"]["model_a"]["status"], seed["runs"]["model_a"]["failure"]) == (
        "failed",
        "interrupted",
    )
    assert result["start"]["state"] == "finished"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_claims_that_keep_finishing_nothing_close_the_start(started):
    world = started["world"]
    stays._inhabited(world, started["client"])
    body = _body()
    assert _start(started, body).status_code == 201
    connection = world["connection"]
    set_workspace(connection, world["workspace"])
    with connection.transaction():
        connection.execute(
            "update society_comparison_start set claim_attempts=%s where workspace_id=%s "
            "and world_id=%s and comparison_id=%s",
            (
                MAX_CLAIM_ATTEMPTS,
                world["workspace"],
                world["binding"].world_id,
                body["comparison_id"],
            ),
        )
    assert _worker(started).run_once(world["workspace"]) is True
    (listed,) = _listing(started)
    assert listed["start"]["state"] == "closed"
    assert listed["start"]["closed_reason"] == "claims_spent"
    assert listed["runs_finished"] == 3 and listed["runs_completed"] == 0
    result = (
        started["client"]
        .get(_comparisons(world) + f"/{body['comparison_id']}", headers=OWNER, params=_scope(world))
        .json()
    )
    (seed,) = result["seeds"]
    assert {run["failure"] for run in seed["runs"].values()} == {"comparison_stopped"}
    assert not started["transport"].requests


def _set_attempts(world: dict[str, Any], comparison_id: str, attempts: int) -> None:
    """How many claims in a row the start has had finish no run, as a host's claims leave it."""
    connection = world["connection"]
    set_workspace(connection, world["workspace"])
    with connection.transaction():
        connection.execute(
            "update society_comparison_start set claim_attempts=%s where workspace_id=%s "
            "and world_id=%s and comparison_id=%s",
            (attempts, world["workspace"], world["binding"].world_id, comparison_id),
        )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
@pytest.mark.parametrize("stopping", ["releases its lease", "loses its lease"])
def test_a_host_that_finished_a_run_before_it_stopped_never_counts_as_finishing_none(
    started, monkeypatch, stopping
):
    world = started["world"]
    stays._inhabited(world, started["client"])
    # A bound a takeover's presumed minutes leave the run room in, within the half of this
    # process's $5 budget its comparisons may spend beside the share it keeps for other work.
    most = (60 * _population(started) * _one_ask()).quantize(Decimal("0.00000001"))
    body = _body(bound_usd=format(min(most, Decimal(2)), "f"))
    assert _start(started, body).status_code == 201, body
    # One claim short of closing: a claim that finishes nothing more would close the start.
    _set_attempts(world, body["comparison_id"], MAX_CLAIM_ATTEMPTS - 1)
    stop, lost = threading.Event(), threading.Event()
    ran, renew = SocietyComparisonStarts.ran, SocietyComparisonStarts.renew

    def stops_after_an_outcome(connection, workspace_id, world_id, comparison_id):
        ran(connection, workspace_id, world_id, comparison_id)
        # A redeploy stops the host, which lets its lease go; a killed or stalled one keeps it
        # until it runs out.
        (stop if stopping == "releases its lease" else lost).set()

    def renews_until_lost(self, claim):
        return not lost.is_set() and renew(self, claim)

    monkeypatch.setattr(SocietyComparisonStarts, "ran", staticmethod(stops_after_an_outcome))
    monkeypatch.setattr(SocietyComparisonStarts, "renew", renews_until_lost)
    assert _worker(started).run_once(world["workspace"], stop) is True
    (listed,) = _listing(started)
    assert 1 <= listed["runs_finished"] < listed["runs"]
    assert listed["start"]["state"] == ("waiting" if stop.is_set() else "running")
    monkeypatch.setattr(SocietyComparisonStarts, "ran", staticmethod(ran))
    monkeypatch.setattr(SocietyComparisonStarts, "renew", renew)
    if lost.is_set():
        _expire_the_lease(world, body["comparison_id"])
    assert _worker(started).run_once(world["workspace"]) is True
    (listed,) = _listing(started)
    assert (listed["start"]["state"], listed["start"]["closed_reason"]) == ("finished", None)
    assert listed["runs_completed"] == listed["runs"]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_takeover_counts_the_minute_a_stopped_host_may_have_been_asking(started, monkeypatch):
    world = started["world"]
    stays._inhabited(world, started["client"])
    # The most one minute of the model's run can cost: every person asked once.
    minute = (_population(started) * _one_ask()).quantize(
        Decimal("0.00000001"), rounding=ROUND_CEILING
    )
    body = _body(bound_usd=format(minute, "f"))
    assert _start(started, body).status_code == 201, body
    anchors, lost = [], threading.Event()
    ran, renew = SocietyComparisonStarts.ran, SocietyComparisonStarts.renew

    def counts(connection, workspace_id, world_id, comparison_id):
        ran(connection, workspace_id, world_id, comparison_id)
        anchors.append(comparison_id)
        if len(anchors) == 2:
            lost.set()

    def renews_until_lost(self, claim):
        return not lost.is_set() and renew(self, claim)

    # The host plays both anchors and stops as the model's run begins, its lease still set: what
    # a host killed in the run's first minute leaves, before it recorded anything it asked.
    monkeypatch.setattr(SocietyComparisonStarts, "ran", staticmethod(counts))
    monkeypatch.setattr(SocietyComparisonStarts, "renew", renews_until_lost)
    assert _worker(started).run_once(world["workspace"]) is True
    monkeypatch.setattr(SocietyComparisonStarts, "ran", staticmethod(ran))
    monkeypatch.setattr(SocietyComparisonStarts, "renew", renew)
    _expire_the_lease(world, body["comparison_id"])
    assert _worker(started).run_once(world["workspace"]) is True
    # The takeover counts that minute as spent, which leaves the bound nothing, so it asks nothing.
    assert not started["transport"].requests
    run, result = _model_run(started, body["comparison_id"])
    assert (run["status"], run["failure"]) == ("failed", "comparison_bound_spent")
    assert result["start"]["closed_reason"] == "comparison_bound_spent"
    assert result["start"]["presumed_usd"] == format(minute, "f")
    assert result["start"]["spent_usd"] == "0.00000000"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_what_a_start_presumed_spent_only_grows(started):
    world = started["world"]
    stays._inhabited(world, started["client"])
    body = _body()
    assert _start(started, body).status_code == 201
    connection = world["connection"]
    set_workspace(connection, world["workspace"])
    change = (
        "update society_comparison_start set presumed_usd=%s where workspace_id=%s "
        "and world_id=%s and comparison_id=%s"
    )
    ids = (world["workspace"], world["binding"].world_id, body["comparison_id"])
    with connection.transaction():
        connection.execute(change, (Decimal("0.001"), *ids))
    with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
        connection.execute(change, (Decimal("0.0005"), *ids))


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_server_that_plays_no_comparison_starts_none(started):
    world, client = started["world"], started["client"]
    stays._inhabited(world, client)
    services = client.app.state.services
    client.app.state.services = dataclasses.replace(services, comparisons_played_elsewhere=False)
    planned = client.get(_comparisons(world) + "/plan", headers=OWNER, params=_scope(world))
    assert planned.json()["refusal"]["code"] == "comparisons_not_played"
    refused = _start(started, _body())
    assert (refused.status_code, refused.json()["code"]) == (409, "comparisons_not_played")
    assert _counts(world)["society_comparison_start"] == 0
    # The positive control: this process playing them, as the API's thread does.
    client.app.state.services = dataclasses.replace(
        services, comparisons_played_elsewhere=False, runs_comparison_worker=True
    )
    assert _start(started, _body()).status_code == 201


def test_who_plays_comparisons_is_named_or_startup_refuses():
    from exulanica.api.services import SocietySettingRefused, _comparison_player

    spelled = (None, "", " on ", "process", " Process ", "OFF", "0", "no")
    assert [_comparison_player(value) for value in spelled] == [
        "here",
        "here",
        "here",
        "process",
        "process",
        "none",
        "none",
        "none",
    ]
    with pytest.raises(SocietySettingRefused) as refused:
        _comparison_player("elsewhere")
    assert refused.value.code == "comparison_worker_not_recognised"


def test_every_way_a_host_closes_a_start_fails_its_runs_by_a_stated_code():
    from exulanica.api.society_comparison_runner import BOUND_SPENT, RUN_FAILURE_CODES
    from exulanica.api.society_comparison_worker import CLOSED_REASONS

    assert BOUND_SPENT in CLOSED_REASONS
    assert set(CLOSED_REASONS) - {"claims_spent"} <= RUN_FAILURE_CODES
    assert {"interrupted", "comparison_stopped"} <= RUN_FAILURE_CODES


#: The plan, a start and a finished start's reads as the server serves them, for the page's
#: parsers (web/packages/app/test/society-comparison-start.test.ts). Rewrite with
#: EXULANICA_COMPARISON_DOCUMENTS=write and review the diff; only their shape is held here.
START_DOCUMENTS = (
    Path(__file__).resolve().parent / "snapshots" / "society-comparison-start-documents.json"
)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_page_reads_the_start_documents_the_server_serves(started):
    world, client = started["world"], started["client"]
    stays._inhabited(world, client)
    offered = client.get(_comparisons(world) + "/plan", headers=OWNER, params=_scope(world)).json()
    planned = client.get(
        _comparisons(world) + "/plan",
        headers=OWNER,
        params={
            **_scope(world),
            "role": person_role().key,
            "group": "everyone",
            "model": f"{MODEL.provider}/{MODEL.model_id}",
        },
    ).json()
    body = _body()
    begun = _start(started, body).json()
    assert _worker(started).run_once(world["workspace"]) is True
    served = {
        "plan": offered,
        "planned": planned,
        "started": begun,
        "finished": client.get(_comparisons(world), headers=OWNER, params=_scope(world)).json(),
        "result": client.get(
            _comparisons(world) + f"/{body['comparison_id']}", headers=OWNER, params=_scope(world)
        ).json(),
    }
    if os.environ.get("EXULANICA_COMPARISON_DOCUMENTS") == "write":
        START_DOCUMENTS.write_text(
            json.dumps(served, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    golden = json.loads(START_DOCUMENTS.read_text(encoding="utf-8"))
    for name, document in served.items():
        assert compared._keys(document) == compared._keys(golden[name]), name
