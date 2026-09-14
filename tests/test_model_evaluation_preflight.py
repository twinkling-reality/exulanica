"""Synthetic model evaluation planning makes no GPU or model-quality claim."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.evaluation.model_preflight import (
    REQUEST_PROFILE,
    RESULT_PROFILE,
    SUPPORTED_TASKS,
    inspect_request,
    inspect_results,
    read_preflight,
)
from exulanica.ingest.stages.segmentation import local_model_roles
from exulanica.models.manifest import MANIFEST_PATH
from scripts.prepare_model_evaluation import main as preflight_main


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": path.name, "sha256": _sha(data), "bytes": len(data)}


def _authority(root: Path, name: str, *, valid_until="2026-09-16T00:00:00Z"):
    receipt = root / f"{name}-authority.json"
    receipt.write_text('{"synthetic":"not real authority"}')
    return {
        "state": "authorized",
        "basis": "Synthetic test fixture only",
        "scope": "model evaluation preflight test",
        "recheck": "reference_inputs",
        "checked_at": "2026-09-14T12:00:00Z",
        "valid_until": valid_until,
        "receipt_path": receipt.name,
        "receipt_sha256": _sha(receipt.read_bytes()),
    }


def _candidate(kind: str, suffix: str) -> dict[str, object]:
    return {
        "candidate_id": f"{kind}-{suffix}",
        "model_id": f"test/{kind}-{suffix}",
        "revision": {"kind": "git_commit", "value": suffix * 40},
        "license": "TEST-ONLY",
        "task_kinds": [kind],
        "selection": {
            "kind": "evaluation_only",
            "source": "Synthetic local candidate; not production selected",
        },
    }


def _rubric(kind: str) -> dict[str, object]:
    return {
        "scale_min": 0,
        "scale_max": 4,
        "minimum": 3,
        "blinded": True,
        "protocol": f"Inspect the same synthetic {kind} output without candidate labels.",
        "dimensions": [
            {"key": "task_fidelity", "prompt": f"Does the output satisfy {kind}?"},
            {"key": "artifact_integrity", "prompt": "Are visible failures disclosed?"},
        ],
    }


def _request(root: Path, *, all_tasks: bool = False) -> dict[str, object]:
    source = _write(root / "source.bin", b"synthetic benchmark bytes, not production input")
    source["artifact_id"] = "source"
    source["kind"] = "synthetic_fixture"
    source["authority"] = _authority(root, "source")
    kinds = list(SUPPORTED_TASKS) if all_tasks else ["scene_geometry"]
    candidates = [_candidate(kind, suffix) for kind in kinds for suffix in ("a", "b")]
    tasks = [
        {
            "task_id": kind,
            "kind": kind,
            "candidate_ids": [f"{kind}-b", f"{kind}-a"],
            "input_artifact_ids": ["source"],
            "runs_per_candidate": 3,
            "metrics": [
                {
                    "key": "task_score_millionths",
                    "unit": "millionths",
                    "direction": "higher",
                    "aggregation": "median_and_range",
                    "acceptance": {"operator": "gte", "value": 700000},
                },
                {
                    "key": "runtime_milliseconds",
                    "unit": "milliseconds",
                    "direction": "lower",
                    "aggregation": "median_and_range",
                    "acceptance": {"operator": "lte", "value": 5000},
                },
            ],
            "rubric": _rubric(kind),
            "output_kinds": ["candidate_output"],
        }
        for kind in kinds
    ]
    slot_count = len(kinds) * 2 * 3
    return {
        "profile": REQUEST_PROFILE,
        "evaluation_id": "synthetic-model-preflight",
        "prepared_at": "2026-09-14T13:00:00Z",
        "candidates": candidates,
        "input_artifacts": [source],
        "tasks": tasks,
        "runtime_budget": {
            "max_wall_seconds_per_run": 10,
            "max_total_gpu_seconds": slot_count * 10,
            "max_total_cost_microusd": 1000000,
            "max_output_bytes_per_run": 10000,
            "scratch_bytes": 100000,
            "max_parallel_runs": 1,
        },
        "execution_environment": {
            "provider": {
                "name": "synthetic-provider",
                "service": "offline-fixture",
                "region": "test-only",
                "quote_reference": "No commercial quote; synthetic fixture",
                "quote_checked_at": "2026-09-14T12:00:00Z",
            },
            "hardware": {
                "accelerator_vendor": "Synthetic",
                "accelerator_model": "No accelerator",
                "accelerator_count": 1,
                "min_vram_bytes": 1,
                "min_host_ram_bytes": 1,
            },
            "runtime": {
                "execution_image": "test.invalid/evaluator@sha256:" + "c" * 64,
                "driver": "synthetic-driver",
                "framework": "synthetic-framework",
                "entrypoint_revision": {"kind": "git_commit", "value": "d" * 40},
            },
        },
        "output": {"root": ".exulanica/model-evaluation-results"},
    }


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): _sha(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }


def test_preflight_is_read_only_symmetric_and_binds_every_existing_interface(tmp_path):
    request = _request(tmp_path, all_tasks=True)
    before = _snapshot(tmp_path)
    first = inspect_request(request, source_root=tmp_path)
    assert first == inspect_request(request, source_root=tmp_path)
    assert first["status"] == "ready" and first["blockers"] == []
    assert {task["interface"] for task in first["tasks"]} == set(SUPPORTED_TASKS.values())
    assert len(first["result_slots"]) == 24
    assert all(slot["result"]["status"] == "unavailable" for slot in first["result_slots"])
    assert first["comparison"] == {
        "status": "unavailable",
        "claimable": False,
        "winner": None,
        "reason": "Frozen run slots do not yet contain complete authorized results.",
    }
    assert first["allocation_authorized"] is False
    assert first["execution_authorized"] is False
    assert first["publication_authorized"] is False
    assert all(
        candidate["selection"]["production_selected"] is False for candidate in first["candidates"]
    )
    assert first["model_manifest"]["sha256"] == _sha(MANIFEST_PATH.read_bytes())
    assert _snapshot(tmp_path) == before
    assert read_preflight(first) == first


def test_cli_prints_the_frozen_plan_without_creating_run_artifacts(tmp_path, capsys):
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request(tmp_path)))
    before = _snapshot(tmp_path)
    assert (
        preflight_main(["plan", "--request", str(request_path), "--source-root", str(tmp_path)])
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ready"
    assert report["execution_authorized"] is False
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize(
    ("mutate", "status", "message"),
    [
        (
            lambda request: request["candidates"][0].update(
                revision={"kind": "git_commit", "value": "main"}
            ),
            "unavailable",
            "exact lowercase Git commit",
        ),
        (
            lambda request: request["runtime_budget"].update(max_total_gpu_seconds=59),
            "unavailable",
            "cannot cover",
        ),
        (
            lambda request: request["output"].update(root="docs/evaluation/new-run"),
            "failed",
            "immutable",
        ),
        (
            lambda request: request["input_artifacts"][0]["authority"].update(
                valid_until="2026-09-14T12:30:00Z"
            ),
            "unavailable",
            "expired",
        ),
    ],
)
def test_preconditions_fail_closed_with_an_explicit_result(tmp_path, mutate, status, message):
    request = _request(tmp_path)
    mutate(request)
    report = inspect_request(request, source_root=tmp_path)
    assert report["status"] == status
    assert report["comparison"]["claimable"] is False
    assert report["comparison"]["winner"] is None
    assert message in report["blockers"][0]["detail"]


def test_changed_input_or_authority_receipt_is_a_failure_not_a_ready_plan(tmp_path):
    request = _request(tmp_path)
    (tmp_path / "source.bin").write_bytes(b"changed")
    report = inspect_request(request, source_root=tmp_path)
    assert report["status"] == "failed"
    assert "bytes changed" in report["blockers"][0]["detail"]
    request = _request(tmp_path)
    (tmp_path / "source-authority.json").write_text('{"changed":true}')
    report = inspect_request(request, source_root=tmp_path)
    assert report["status"] == "failed"
    assert "receipt bytes changed" in report["blockers"][0]["detail"]


def test_local_manifest_candidate_must_exactly_match_role_revision_and_license(tmp_path):
    request = _request(tmp_path)
    document = json.loads(MANIFEST_PATH.read_bytes())
    role_name, binding = next(iter(local_model_roles(document).items()))
    task_kind = "mask" if role_name == "object_segmentation" else "grounded_detection"
    candidate = request["candidates"][0]
    candidate.update(
        model_id=binding.primary.repo_id,
        revision={"kind": "git_commit", "value": binding.primary.revision},
        license=binding.primary.license,
        task_kinds=[task_kind],
        selection={"kind": "manifest_local_role", "role": role_name, "position": "primary"},
    )
    request["tasks"][0].update(
        kind=task_kind,
        candidate_ids=[candidate["candidate_id"], request["candidates"][1]["candidate_id"]],
    )
    request["candidates"][1]["task_kinds"] = [task_kind]
    report = inspect_request(request, source_root=tmp_path)
    assert report["status"] == "ready"
    resolved = next(
        item for item in report["candidates"] if item["candidate_id"] == candidate["candidate_id"]
    )
    assert resolved["selection"]["production_selected"] is True
    candidate["revision"]["value"] = "e" * 40
    assert inspect_request(request, source_root=tmp_path)["status"] == "failed"


def test_hosted_manifest_role_with_no_provider_revision_is_explicitly_unavailable(tmp_path):
    request = _request(tmp_path)
    document = json.loads(MANIFEST_PATH.read_bytes())
    role_name, role = next(iter(document["roles"].items()))
    model_id = role["primary"]
    candidate = request["candidates"][0]
    candidate.update(
        model_id=model_id,
        license=document["models"][model_id]["catalog_license"],
        selection={"kind": "manifest_hosted_role", "role": role_name, "position": "primary"},
    )
    report = inspect_request(request, source_root=tmp_path)
    assert report["status"] == "unavailable"
    assert "exposes no immutable model revision" in report["blockers"][0]["detail"]


def _success_result(
    root: Path, plan: dict[str, object], slot: dict[str, object]
) -> dict[str, object]:
    task = next(item for item in plan["tasks"] if item["task_id"] == slot["task_id"])
    candidate = next(
        item for item in plan["candidates"] if item["candidate_id"] == slot["candidate_id"]
    )
    output_path = root / (slot["slot_id"] + ".bin")
    output = _write(output_path, ("synthetic " + slot["slot_id"]).encode())
    allocation = root / (slot["slot_id"] + "-allocation.json")
    execution = root / (slot["slot_id"] + "-execution.json")
    recheck = root / (slot["slot_id"] + "-input-recheck.json")
    notes = root / (slot["slot_id"] + "-review.txt")
    measurement = root / (slot["slot_id"] + "-measurement.json")
    allocation.write_text('{"synthetic":"allocation"}')
    execution.write_text('{"synthetic":"execution"}')
    recheck.write_text('{"synthetic":"input recheck"}')
    notes.write_text("Synthetic review notes, not a real quality judgment.")
    measurement.write_text('{"synthetic":"measurement receipt"}')
    inputs = [
        {
            "artifact_id": item["artifact_id"],
            "sha256": item["sha256"],
            "authority_receipt_sha256": item["authority"]["receipt_sha256"],
        }
        for item in plan["input_artifacts"]
        if item["artifact_id"] in task["input_artifact_ids"]
    ]
    return {
        "profile": RESULT_PROFILE,
        "plan_sha256": plan["document_sha256"],
        "slot_id": slot["slot_id"],
        "candidate_id": candidate["candidate_id"],
        "candidate_revision": candidate["revision"],
        "task_id": task["task_id"],
        "run_index": slot["run_index"],
        "status": "succeeded",
        "input_artifacts": inputs,
        "execution_environment_sha256": plan["execution_environment_sha256"],
        "authorization": {
            "input_rechecks": [
                {
                    "artifact_id": "source",
                    "boundary": "reference_inputs",
                    "checked_at": "2026-09-14T14:00:00Z",
                    "receipt": {"path": recheck.name, "sha256": _sha(recheck.read_bytes())},
                }
            ],
            "allocation_receipt": {
                "path": allocation.name,
                "sha256": _sha(allocation.read_bytes()),
            },
            "execution_receipt": {
                "path": execution.name,
                "sha256": _sha(execution.read_bytes()),
            },
        },
        "runtime": {"wall_seconds": 2, "gpu_seconds": 2, "cost_microusd": 100},
        "outputs": [
            {
                "kind": "candidate_output",
                "path": output["path"],
                "sha256": output["sha256"],
                "bytes": output["bytes"],
            }
        ],
        "measurement_receipt": {
            "path": measurement.name,
            "sha256": _sha(measurement.read_bytes()),
        },
        "metrics": {"task_score_millionths": 800000, "runtime_milliseconds": 2000},
        "rubric": {
            "reviewer": "Synthetic Reviewer",
            "reviewed_at": "2026-09-14T14:05:00Z",
            "scores": {"task_fidelity": 3, "artifact_integrity": 4},
            "notes": {"path": notes.name, "sha256": _sha(notes.read_bytes())},
        },
        "failure": None,
    }


def test_results_remain_unavailable_until_every_slot_succeeds_and_no_winner_is_chosen(tmp_path):
    plan = inspect_request(_request(tmp_path), source_root=tmp_path)
    empty = inspect_results(plan, [], artifact_root=tmp_path)
    assert empty["status"] == "unavailable" and empty["claimable"] is False
    assert len(empty["blockers"]) == 6
    assert all(item["result"]["status"] == "unavailable" for item in empty["results"])
    results = [_success_result(tmp_path, plan, slot) for slot in plan["result_slots"]]
    complete = inspect_results(plan, results, artifact_root=tmp_path)
    assert complete["status"] == "complete" and complete["claimable"] is True
    assert complete["winner"] is None
    assert complete["comparison"]["winner"] is None
    assert complete["comparison"]["selection"].startswith("requires a separate reviewed")
    candidates = complete["comparison"]["tasks"][0]["candidates"]
    assert [item["candidate_id"] for item in candidates] == [
        "scene_geometry-a",
        "scene_geometry-b",
    ]
    assert candidates[0]["metrics"][0]["sample"] == {
        "observations": 3,
        "median_numerator": 800000,
        "median_denominator": 1,
        "range_min": 800000,
        "range_max": 800000,
    }
    assert candidates[0]["accepted"] is True


def test_explicit_failed_result_and_tampered_output_block_comparison(tmp_path):
    plan = inspect_request(_request(tmp_path), source_root=tmp_path)
    results = [_success_result(tmp_path, plan, slot) for slot in plan["result_slots"]]
    slot = plan["result_slots"][0]
    results[0] = {
        "profile": RESULT_PROFILE,
        "plan_sha256": plan["document_sha256"],
        "slot_id": slot["slot_id"],
        "status": "failed",
        "failure": {
            "stage": "candidate_run",
            "code": "synthetic_failure",
            "detail": "Synthetic failure retained instead of dropping the run.",
        },
    }
    failed = inspect_results(plan, results, artifact_root=tmp_path)
    assert failed["claimable"] is False
    assert failed["blockers"][0]["code"] == "result_failed"
    results[0] = _success_result(tmp_path, plan, slot)
    Path(tmp_path / results[0]["outputs"][0]["path"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="bytes changed"):
        inspect_results(plan, results, artifact_root=tmp_path)


def test_preflight_digest_and_candidate_order_cannot_be_rewritten(tmp_path):
    plan = inspect_request(_request(tmp_path), source_root=tmp_path)
    changed = deepcopy(plan)
    changed["candidates"].reverse()
    with pytest.raises(ValueError, match="digest"):
        read_preflight(changed)


def test_rehashed_preflight_still_cannot_grant_execution_authority(tmp_path):
    plan = inspect_request(_request(tmp_path), source_root=tmp_path)
    changed = deepcopy(plan)
    changed["execution_authorized"] = True
    changed.pop("document_sha256")
    changed["document_sha256"] = _sha(canonical_json(changed))
    with pytest.raises(ValueError, match="cannot grant"):
        read_preflight(changed)
