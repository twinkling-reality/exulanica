"""End-to-end PostgreSQL and FastAPI tests for ``/society/trajectories``.

Records real society decisions and counterfactual model asks in PostgreSQL, queries the
authenticated FastAPI endpoint across JSON and JSONL formats, and verifies SFT records,
DPO counterfactual pairs, distillation metrics, and tenant isolation.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.canonical import canonical_json
from exulanica.world.trajectories import TRAJECTORY_PROFILE, assert_no_floats

from test_society_decision_asks_postgres import _ask, _recorded, _Waiter
from test_society_person_decisions_postgres import _callers
from test_society_person_decisions_postgres import app as app
from test_society_person_decisions_postgres import saved_world as saved_world
from test_society_saved_world_api import routes

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_society_trajectories_endpoint_exports_sft_dpo_and_metrics_from_postgres(app) -> None:
    world, client = app
    transport = _Waiter()
    _services, _snapshot, receipt = _recorded(world, client, transport)
    callers = _callers(client, world, listed=True)
    owner = callers["owner"][0]
    reader = callers["reader"][0]
    stranger = callers["stranger"][0]
    scope, _version, society = routes(world)
    request_id = receipt["request_id"]

    # Record a counterfactual ask on the same decision in PostgreSQL.
    asked = _ask(
        client,
        society,
        request_id,
        owner,
        scope,
        idempotency_key=str(uuid.uuid4()),
    )
    assert asked.status_code == 201, asked.text
    ask_view = asked.json()

    # 1. Stranger gets 404 (no existence oracle).
    stranger_res = client.get(f"{society}/trajectories", headers=stranger, params=scope)
    assert stranger_res.status_code == 404

    # 2. Reader with `world.read` can fetch the canonical `exulanica.world-trajectory/v1` bundle.
    response = client.get(f"{society}/trajectories", headers=reader, params=scope)
    assert response.status_code == 200, response.text
    bundle = response.json()
    assert_no_floats(bundle)
    assert bundle["profile"] == TRAJECTORY_PROFILE
    assert bundle["world_id"] == world["binding"].world_id
    assert bundle["version_id"] == str(world["binding"].version_id)
    assert len(bundle["bundle_sha256"]) == 64

    metrics = bundle["metrics"]
    assert metrics["total_decisions"] >= 1
    assert metrics["applied_count"] >= 1
    assert metrics["evaluated_branches"] == 1

    sft_by_req = {rec["request_id"]: rec for rec in bundle["sft_records"]}
    assert request_id in sft_by_req
    sft_rec = sft_by_req[request_id]
    assert sft_rec["profile"] == TRAJECTORY_PROFILE
    assert sft_rec["record_kind"] == "sft"
    assert sft_rec["subject_id"] == receipt["subject_id"]
    assert sft_rec["chosen_action"]["label"] == receipt["proposal"]["label"]
    # Exact message digest parity with the provider receipt stored in PostgreSQL
    assert sft_rec["messages_sha256"] == receipt["provider"]["messages_sha256"]

    if not ask_view["same_choice"]:
        assert metrics["counterfactual_pairs"] >= 1
        dpo_by_req = [p for p in bundle["dpo_pairs"] if p["request_id"] == request_id]
        assert len(dpo_by_req) == 1
        dpo_pair = dpo_by_req[0]
        assert dpo_pair["record_kind"] == "dpo"
        assert dpo_pair["pair_kind"] == "counterfactual_branch"
        assert dpo_pair["chosen_valid_action"]["label"] == receipt["proposal"]["label"]
        assert dpo_pair["rejected_or_alternative_action"]["label"] == ask_view["chose"]
    else:
        assert metrics["agreed_branches"] == 1
        assert metrics["agreement_rate_permille"] == 1000

    # 3. Query parameter support: `?format=jsonl`, `?format=openai`, `?format=openenv`, `?kind=sft`
    jsonl_res = client.get(
        f"{society}/trajectories",
        headers=owner,
        params={**scope, "format": "jsonl"},
    )
    assert jsonl_res.status_code == 200
    assert jsonl_res.headers["content-type"].startswith("application/x-ndjson")
    lines = [line for line in jsonl_res.text.splitlines() if line.strip()]
    assert len(lines) == len(bundle["sft_records"]) + len(bundle["dpo_pairs"])
    for line in lines:
        parsed = json.loads(line)
        assert parsed["profile"] == TRAJECTORY_PROFILE
        assert_no_floats(parsed)
        assert canonical_json(parsed).decode("utf-8") == line

    openai_res = client.get(
        f"{society}/trajectories",
        headers=owner,
        params={**scope, "format": "openai", "kind": "sft"},
    )
    assert openai_res.status_code == 200
    openai_rows = [json.loads(line) for line in openai_res.text.splitlines() if line.strip()]
    assert len(openai_rows) == len(bundle["sft_records"])
    assert openai_rows[0]["format"] == "openai_tool_call"

    openenv_res = client.get(
        f"{society}/trajectories",
        headers=owner,
        params={**scope, "format": "openenv"},
    )
    assert openenv_res.status_code == 200
    openenv_rows = [json.loads(line) for line in openenv_res.text.splitlines() if line.strip()]
    assert len(openenv_rows) == len(bundle["sft_records"])
    assert openenv_rows[-1]["done"] is True
