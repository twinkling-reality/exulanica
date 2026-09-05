"""The program's retained conclusions must agree with its independently retained evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from exulanica.canonical import canonical_json
from exulanica.evaluation.metrics import METRICS
from exulanica.ingest.stages import STAGES

ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / "docs/evaluation/2026-09-05-unblocked-backend-program.json"


def _read(path):
    envelope = json.loads(path.read_bytes())
    assert envelope["record_sha256"] == hashlib.sha256(
        canonical_json(envelope["record"])
    ).hexdigest()
    return envelope


def test_program_goals_are_complete_bound_records_with_checkable_decisions():
    program = _read(PROGRAM)["record"]
    assert [goal["goal"] for goal in program["goal_records"]] == ["A", "C", "B", "D"]
    predecessor = "docs/evaluation/2026-09-04-semantic-answers-and-memory-lifecycle.json"
    for goal in program["goal_records"]:
        envelope = _read(ROOT / goal["path"])
        assert envelope["record_sha256"] == goal["record_sha256"]
        record = envelope["record"]
        assert record["goal"] == goal["goal"]
        assert record["predecessor_record"] == {
            "path": predecessor, "record_sha256": _read(ROOT / predecessor)["record_sha256"],
        }
        assert record["negative_controls"]
        for decision in record["decisions"]:
            for field in ("invariant", "rationale", "canonical_representation",
                          "compatibility_impact", "failure_behaviour"):
                assert decision[field], (goal["goal"], field)
            assert set(decision["affected_surfaces"]) == {
                "schemas", "migrations", "workers", "evidence", "apis", "exports",
                "deletion_paths", "browser_consumers",
            }
            for test in decision["tests"]:
                path, _, node = test.partition("::")
                assert (ROOT / path).is_file()
                if node:
                    assert node.split("[", 1)[0] in (ROOT / path).read_text()
        predecessor = goal["path"]
    for path, expected in program["frozen_migrations"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected
    assert len(program["frozen_migrations"]) == 35
    assert {item["id"] for item in program["still_open"]} >= {"P-1", "A-8", "OGC-1"}


def test_program_measurements_do_not_outgrow_their_observed_scope():
    program = _read(PROGRAM)["record"]
    records = {goal["goal"]: _read(ROOT / goal["path"])["record"]
               for goal in program["goal_records"]}
    measured = records["B"]["measurement"]
    assert hashlib.sha256((ROOT / records["B"]["report_artifact"]).read_bytes()).hexdigest() == (
        measured["report_sha256"]
    )
    assert hashlib.sha256((ROOT / measured["experiment_script"]).read_bytes()).hexdigest() == (
        measured["experiment_script_sha256"]
    )
    assert measured["synthetic"] is True and measured["corpus_id"] == "SYNTH-1"
    components = {f"{item.metric}.{item.key}": item for item in METRICS}
    for key, count in measured["components"].items():
        if count is not None:
            assert components[key].blocked_on is None, key
            assert count["corpus_id"] == measured["corpus_id"]
            assert count["n"] == len(count["cases"])
            assert count["k"] == sum(case["passed"] for case in count["cases"])
    closure = records["D"]["closure_observation"]
    before = canonical_json(closure["baseline_exemplar_payload"])
    after = canonical_json(closure["rebuilt_exemplar_payload"])
    assert closure["canonical_exemplar_payload_identical"] == (before == after)
    assert closure["canonical_exemplar_payload_sha256"] == hashlib.sha256(after).hexdigest()
    assert closure["scene_group_projection_identical"] == (
        closure["scene_groups_before"] == closure["scene_groups_after"]
    )
    assert closure["historical_generation_identical"] == (
        closure["baseline_generation_id"] == closure["rebuilt_generation_id"]
    )
    assert closure["vision_or_depth_exactness_claim"] is False
    assert records["D"]["excluded_model_stages"] == sorted(
        key for key, spec in STAGES.items() if spec.model_role is not None
    )
    pose = records["D"]["pose_observation"]
    left, right = pose["runs"]
    for run in pose["runs"]:
        receipt_bytes = (ROOT / run["receipt_artifact"]).read_bytes()
        assert hashlib.sha256(receipt_bytes).hexdigest() == run["receipt_sha256"]
        receipt = json.loads(receipt_bytes)
        assert receipt["quality_digest"] == run["quality_sha256"]
        assert receipt["manifest_digest"] == pose["pose_manifest_sha256"]
        assert receipt["quality"]["registered_images"] == run["registered_images"]
        assert receipt["quality"]["accepted"] == run["accepted"]
    assert len(left["registered_images"]) >= 3 and len(right["registered_images"]) >= 3
    assert left["reused"] is False and right["reused"] is False
    assert pose["receipt_bytes_identical"] == (left["receipt_sha256"] == right["receipt_sha256"])
    assert pose["quality_bytes_identical"] == (left["quality_sha256"] == right["quality_sha256"])
