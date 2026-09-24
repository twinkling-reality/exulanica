"""Authenticated HTTP preparation, reservation, and compact society experiment reads."""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.permissions import Permission
from exulanica.api.services import Services
from exulanica.api.society_experiment_runner import SocietyExperimentRunner
from exulanica.db.roles import provision_runtime_role
from exulanica.world import society_experiments as experiments
from exulanica.world.society_repository import SocietyRepository
from fastapi.testclient import TestClient

from conftest import scratch_role_database
from test_society_runtime import add_plate, initial, runtime_world

pytestmark = pytest.mark.postgres
__all__ = ["runtime_world"]

WRITER_TOKEN = "society-experiment-writer-token-long-enough"
READER_TOKEN = "society-experiment-reader-token-long-enough"
READ_ONLY_TOKEN = "society-experiment-read-only-token-long-enough"
WRITE_ONLY_TOKEN = "society-experiment-write-only-token-long-enough"
FOREIGN_TOKEN = "society-experiment-foreign-token-long-enough"
ROLE = "exulanica_experiment_api_suite"


@pytest.fixture
def experiment_api(runtime_world, spine_schema, monkeypatch):
    world = runtime_world
    binding = world["binding"]
    baseline = initial(world)
    societies = SocietyRepository(
        world["connection"],
        world["workspace"],
        world_id=world["version"].world_id,
        input_authorizer=lambda document: world["runtime"].authorize(
            world["connection"], world["session"], document
        ),
    )
    created = societies.create(
        binding.version_id,
        place_id=binding.place_id,
        region_id=binding.region_id,
        seed="7a" * 32,
        actor=world["session"].actor,
        profile="exulanica-society/v4",
        initial_input=baseline,
    )
    with world["connection"].transaction():
        add_plate(world)
    treatment = (
        world["connection"]
        .execute(
            "select document from world_society_input where workspace_id=%s and society_id=%s "
            "and input_seq=2",
            (world["workspace"], created["society_id"]),
        )
        .fetchone()["document"]
    )
    target = next(row for row in treatment["targets"] if row["origin"] == "authored")

    reader_actor = uuid.uuid4()
    permissions = {
        WRITER_TOKEN: [str(Permission.WORLD_READ), str(Permission.WORLD_WRITE)],
        READER_TOKEN: [str(Permission.WORLD_READ), str(Permission.WORLD_WRITE)],
        READ_ONLY_TOKEN: [str(Permission.WORLD_READ)],
        WRITE_ONLY_TOKEN: [str(Permission.WORLD_WRITE)],
    }
    grants = {
        token: {
            "workspace_id": str(world["workspace"]),
            "actor": str(world["session"].actor if token == WRITER_TOKEN else reader_actor),
            "permissions": held,
        }
        for token, held in permissions.items()
    }
    grants[FOREIGN_TOKEN] = {
        "workspace_id": str(uuid.uuid4()),
        "actor": str(uuid.uuid4()),
        "permissions": [str(Permission.WORLD_READ), str(Permission.WORLD_WRITE)],
    }
    monkeypatch.setenv("EXULANICA_API_TOKENS", json.dumps(grants))
    provision_runtime_role(world["connection"], role=ROLE)
    world["connection"].commit()
    _driver, scratch = spine_schema
    database = scratch_role_database(scratch, ROLE)
    services = Services(
        database=database,
        readonly_database=database,
        store=world["store"],
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
        society_runtime=world["runtime"],
    )
    with TestClient(create_app(services, verify=False)) as client:
        yield {
            "client": client,
            "world": world,
            "database": database,
            "baseline": baseline,
            "treatment": treatment,
            "target_id": target["target_id"],
            "source_society_id": created["society_id"],
        }


def _headers(token: str = WRITER_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _definition_body(case, experiment_id: uuid.UUID, **overrides):
    body = {
        "experiment_id": str(experiment_id),
        "baseline_input_seq": 1,
        "treatment_input_seq": 2,
        "intervention": {
            "kind": "add_rest_amenity",
            "target_id": case["target_id"],
        },
        "population": 3,
        "warmup_ticks": 2,
        "followup_ticks": 3,
    }
    body.update(overrides)
    return body


def test_prepare_reserve_reload_and_compact_completed_result(experiment_api, monkeypatch):
    case = experiment_api
    client = case["client"]
    version_id = case["world"]["binding"].version_id
    scope = {"world_id": case["world"]["binding"].world_id}
    route = f"/world/versions/{version_id}/society/experiments"
    experiment_id, attempt_id = uuid.uuid4(), uuid.uuid4()

    original_prepare = experiments.prepare_checkpoint
    original_execute = experiments.execute_pair
    monkeypatch.setattr(
        experiments,
        "prepare_checkpoint",
        lambda *_args, **_kwargs: pytest.fail("HTTP preparation entered simulation"),
    )
    monkeypatch.setattr(
        experiments,
        "execute_pair",
        lambda *_args, **_kwargs: pytest.fail("HTTP preparation entered execution"),
    )
    assert (
        client.post(route, params=scope, json=_definition_body(case, experiment_id)).status_code
        == 401
    )
    prepared = client.post(
        route, headers=_headers(), params=scope, json=_definition_body(case, experiment_id)
    )
    assert prepared.status_code == 200, prepared.text
    definition_view = prepared.json()
    assert definition_view["record_status"] == "recorded"
    assert definition_view["baseline_input_sha256"] == case["baseline"]["document_sha256"]
    assert definition_view["treatment_input_sha256"] == case["treatment"]["document_sha256"]
    assert definition_view["source_society_id"] == str(case["source_society_id"])
    assert (
        client.get(f"{route}/{experiment_id}", headers=_headers(READER_TOKEN), params=scope).json()
        == definition_view
    )

    seed = experiments.DEVELOPMENT_SEEDS[0]
    reserved = client.post(
        f"{route}/{experiment_id}/attempts",
        headers=_headers(),
        params=scope,
        json={"attempt_id": str(attempt_id), "seed_sha256": seed},
    )
    assert reserved.status_code == 200, reserved.text
    assert reserved.json()["reservation_status"] == "reserved"
    assert reserved.json()["status"] == "incomplete"
    assert reserved.json()["checkpoint_sha256"] is None

    monkeypatch.setattr(experiments, "prepare_checkpoint", original_prepare)
    monkeypatch.setattr(experiments, "execute_pair", original_execute)

    def authorize_execution(_connection, session, reservation):
        assert session == case["world"]["session"]
        assert reservation["attempt_id"] == attempt_id

    receipt = SocietyExperimentRunner(
        case["database"],
        runtime=case["world"]["runtime"],
        authorize_execution=authorize_execution,
    ).run_reserved(case["world"]["session"], attempt_id)
    assert receipt.status == "completed"

    completed = client.get(
        f"{route}/{experiment_id}/attempts/{attempt_id}",
        headers=_headers(READER_TOKEN),
        params=scope,
    )
    assert completed.status_code == 200, completed.text
    payload = completed.json()
    assert payload["status"] == "completed"
    assert payload["evidence_sha256"] is not None
    assert "evidence" not in payload
    assert payload["result_sha256"] == receipt.result_sha256
    assert payload["result"]["document_sha256"] == receipt.result_sha256
    assert payload["result"]["arms"]["baseline"]["high_fatigue_person_minutes"]["denominator"] == 9
    assert payload["result"]["arms"]["treatment"]["all_rest_occupancy"]["denominator"] > 0


def test_permissions_nesting_idempotency_and_bounded_request_refusals(experiment_api):
    case = experiment_api
    client = case["client"]
    version_id = case["world"]["binding"].version_id
    scope = {"world_id": case["world"]["binding"].world_id}
    route = f"/world/versions/{version_id}/society/experiments"
    experiment_id, attempt_id = uuid.uuid4(), uuid.uuid4()
    body = _definition_body(case, experiment_id)
    assert (
        client.post(route, headers=_headers(READ_ONLY_TOKEN), params=scope, json=body).status_code
        == 404
    )
    created = client.post(route, headers=_headers(), params=scope, json=body)
    assert created.status_code == 200, created.text
    assert client.post(route, headers=_headers(), params=scope, json=body).json() == created.json()
    conflict = client.post(
        route,
        headers=_headers(),
        params=scope,
        json=_definition_body(case, experiment_id, followup_ticks=4),
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "experiment_conflict"
    assert (
        client.get(
            f"{route}/{experiment_id}", headers=_headers(WRITE_ONLY_TOKEN), params=scope
        ).status_code
        == 404
    )

    seed = experiments.DEVELOPMENT_SEEDS[1]
    attempt_route = f"{route}/{experiment_id}/attempts"
    reserve_body = {"attempt_id": str(attempt_id), "seed_sha256": seed}
    assert (
        client.post(attempt_route, headers=_headers(), params=scope, json=reserve_body).status_code
        == 200
    )
    assert (
        client.post(attempt_route, headers=_headers(), params=scope, json=reserve_body).status_code
        == 200
    )
    conflicting_seed = {**reserve_body, "seed_sha256": experiments.DEVELOPMENT_SEEDS[2]}
    assert (
        client.post(
            attempt_route, headers=_headers(), params=scope, json=conflicting_seed
        ).status_code
        == 409
    )
    assert (
        client.get(
            f"{route}/{uuid.uuid4()}/attempts/{attempt_id}", headers=_headers(), params=scope
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"{route}/{experiment_id}", headers=_headers(FOREIGN_TOKEN), params=scope
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"{route}/{experiment_id}/attempts/{attempt_id}",
            headers=_headers(FOREIGN_TOKEN),
            params=scope,
        ).status_code
        == 404
    )
    wrong_version = f"/world/versions/{uuid.uuid4()}/society/experiments/{experiment_id}"
    assert client.get(wrong_version, headers=_headers(), params=scope).status_code == 404

    before = (
        case["world"]["connection"]
        .execute(
            "select count(*) as n from society_experiment_definition where workspace_id=%s",
            (case["world"]["workspace"],),
        )
        .fetchone()["n"]
    )
    invalid = _definition_body(case, uuid.uuid4(), population=257)
    assert client.post(route, headers=_headers(), params=scope, json=invalid).status_code == 422
    arbitrary = _definition_body(case, uuid.uuid4()) | {"evidence": {"invented": True}}
    assert client.post(route, headers=_headers(), params=scope, json=arbitrary).status_code == 422
    unsupported = _definition_body(case, uuid.uuid4())
    unsupported["intervention"] = {"kind": "replace_everything"}
    assert client.post(route, headers=_headers(), params=scope, json=unsupported).status_code == 422
    after = (
        case["world"]["connection"]
        .execute(
            "select count(*) as n from society_experiment_definition where workspace_id=%s",
            (case["world"]["workspace"],),
        )
        .fetchone()["n"]
    )
    assert after == before

    noop_id = uuid.uuid4()
    noop = _definition_body(
        case,
        noop_id,
        treatment_input_seq=1,
        intervention={"kind": "noop"},
    )
    noop_response = client.post(route, headers=_headers(), params=scope, json=noop)
    assert noop_response.status_code == 200, noop_response.text
    assert noop_response.json()["intervention"] == {"kind": "noop", "target_id": None}

    authorizer = client.app.state.society_input_authorizer
    del client.app.state.society_input_authorizer
    assert client.get(f"{route}/{noop_id}", headers=_headers(), params=scope).status_code == 424
    client.app.state.society_input_authorizer = authorizer


def test_current_runtime_withdrawal_gates_definition_and_attempt_reads(experiment_api):
    case = experiment_api
    client = case["client"]
    version_id = case["world"]["binding"].version_id
    scope = {"world_id": case["world"]["binding"].world_id}
    route = f"/world/versions/{version_id}/society/experiments"
    experiment_id, attempt_id = uuid.uuid4(), uuid.uuid4()
    assert (
        client.post(
            route,
            headers=_headers(),
            params=scope,
            json=_definition_body(case, experiment_id),
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{route}/{experiment_id}/attempts",
            headers=_headers(),
            params=scope,
            json={
                "attempt_id": str(attempt_id),
                "seed_sha256": experiments.DEVELOPMENT_SEEDS[3],
            },
        ).status_code
        == 200
    )
    source = case["world"]["binding"].sources[0]
    case["world"]["admissions"].withdraw("source", source.admission_id)
    assert (
        client.get(f"{route}/{experiment_id}", headers=_headers(), params=scope).status_code == 424
    )
    assert (
        client.get(
            f"{route}/{experiment_id}/attempts/{attempt_id}", headers=_headers(), params=scope
        ).status_code
        == 424
    )
