"""Reading a comparison's run asks its inputs' rights after the replay, and reads no store bytes
under the lock.

``GET .../society/comparisons/{comparison_id}/runs/{run_id}`` replays a completed run from what it
stored, which takes seconds for a town, then authorizes every input the run was planned over
through the society's own announce-then-authorize path, and only then answers. So a withdrawal
committed while the run is replayed is seen: the read is answered as unavailable rather than drawn
from geometry that lost its rights. Each request runs through the application connected as the
runtime role, and the store reads are recorded with the planted control
(``tests/asset_lock_support.py``) before an empty record is trusted.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.api.routes import society_comparisons
from exulanica.api.society_comparison_runner import ComparisonArm, SocietyComparisonRunner
from exulanica.env import env_get
from exulanica.models.manifest import load_manifest
from exulanica.orchestration.compare import comparison_body
from exulanica.world.society_decision_contract import person_role
from fastapi.testclient import TestClient

import test_society_authored_world_postgres as helpers
import test_society_saved_world_api as saved_api
import test_world_arrangements as arrangements
from asset_lock_support import recorded_store_reads
from comparison_support import SEEDS, seeded_catalogs

pytestmark = pytest.mark.postgres
saved_world = helpers.saved_world
runtime_app = arrangements.runtime_app
CURRENT_GROUND = pytest.mark.parametrize(
    "saved_world", [helpers.AUTHORED_GROUND_MODULE_VERSION], indirect=True
)


def _completed_routine_run(client, world) -> tuple[uuid.UUID, uuid.UUID]:
    """A comparison of the furnished, inhabited world whose routine run has completed: it asks
    nobody, so no model client is needed."""
    saved_api.place(client, world, "object:cushion", 3_000, 5_000)
    brought = saved_api.bring_inhabitants(client, world)
    assert brought.status_code in (200, 201), brought.text
    saved_api.place(client, world, "object:second", -3_000, 5_000, asset="pillar")
    services = client.app.state.services
    manifest = load_manifest()
    runner = SocietyComparisonRunner(
        database=services.database,
        runtime=services.society_runtime,
        client=None,
        policy_for=services.person_decision_policy,
        manifest=manifest,
        manifest_sha256="a" * 64,
        workspace_id=world["workspace"],
        world_id=world["binding"].world_id,
        actor=world["session"].actor,
        catalogs=seeded_catalogs(population_maximum=512),
    )
    model = manifest.offered_models(person_role().chosen)[0]
    comparison_id = uuid.uuid4()
    runner.define(
        world["binding"].version_id,
        comparison_id=comparison_id,
        body=comparison_body(
            runner, [ComparisonArm(model.provider, model.model_id)], SEEDS[:1], control=False
        ),
    )
    run_ids = runner.reserve_all(comparison_id, SEEDS[:1])
    with services.database.session(world["workspace"]) as connection:
        arms = {runner._repository(connection)._run(run_id)["arm"]: run_id for run_id in run_ids}
    outcome = runner.run(comparison_id, arms["routine"])
    assert outcome["status"] == "completed", outcome
    return comparison_id, arms["routine"]


def _read(client, world, comparison_id, run_id):
    scope, version, _ = saved_api.routes(world)
    return client.get(
        f"{version}/society/comparisons/{comparison_id}/runs/{run_id}",
        headers=saved_api.OWNER,
        params=scope,
    )


@CURRENT_GROUND
def test_a_withdrawal_committed_while_a_run_is_replayed_answers_the_read_as_unavailable(
    runtime_app, monkeypatch
):
    world, make_app = runtime_app
    key = world["plate"].asset_key
    connection = world["connection"]
    schema = connection.execute("select current_schema() as name").fetchone()["name"]
    licence = connection.execute(
        "select licence_sha256 from world_reviewed_asset where asset_key=%s", (key,)
    ).fetchone()["licence_sha256"]
    connection.commit()
    replay = society_comparisons.verified_replay
    withdrawn: list[str] = []

    def withdrawn_while_replayed(*args, **kwargs):
        played = replay(*args, **kwargs)
        with psycopg.connect(env_get("TEST_DATABASE_URL"), autocommit=True) as other:
            other.execute(f'set search_path to "{schema}", public')
            other.execute(
                "update world_reviewed_asset set licence_sha256=%s where asset_key=%s",
                ("0" * 64, key),
            )
        withdrawn.append(key)
        return played

    try:
        with TestClient(make_app()) as client:
            comparison_id, run_id = _completed_routine_run(client, world)
            # Positive control: the same read, with nothing withdrawn, is drawn.
            drawn = _read(client, world, comparison_id, run_id)
            assert drawn.status_code == 200, drawn.text
            assert drawn.json()["replay_verified"] is True
            with monkeypatch.context() as patch:
                patch.setattr(society_comparisons, "verified_replay", withdrawn_while_replayed)
                refused = _read(client, world, comparison_id, run_id)
        assert withdrawn == [key], "the withdrawal committed while the run was replayed"
        assert refused.status_code == 424, refused.text
        assert refused.json()["code"] == "unavailable_society_input"
    finally:
        connection.execute(
            "update world_reviewed_asset set licence_sha256=%s where asset_key=%s", (licence, key)
        )
        connection.commit()


@CURRENT_GROUND
def test_reading_a_comparison_run_reads_nothing_from_the_store_under_the_lock(
    runtime_app, monkeypatch
):
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        comparison_id, run_id = _completed_routine_run(client, world)
        reads = recorded_store_reads(
            world["connection"],
            client.app.state.services.database,
            world["workspace"],
            world["store"],
            monkeypatch,
            planted=world["plate"].content_sha256,
        )
        drawn = _read(client, world, comparison_id, run_id)
    assert drawn.status_code == 200, drawn.text
    assert reads.under_the_lock == []
    assert any("api/society_runtime.py" in where for _, where in reads.every), (
        "the read authorized its inputs, reading their bytes before the lock"
    )
