"""The creature rig trial's evaluation record is what its script builds from the tracked evidence,
and its verdict is the pre-registered rule applied to the items it lists."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs/evaluation/2026-10-07-creature-rig-trial.json"


def _script():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "record_creature_rig_trial", ROOT / "scripts/record_creature_rig_trial.py"
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_the_committed_record_is_the_one_the_evidence_builds() -> None:
    committed = json.loads(RECORD.read_bytes())["record"]
    assert committed == _script().build()


def test_the_verdict_is_the_rule_applied_to_the_items() -> None:
    record = json.loads(RECORD.read_bytes())["record"]
    # A creature counts when one of its items passed every check, as the rule states.
    passed = {item["creature"] for item in record["items"] if item["outcome"] == "passed"}
    counted = {name for name, creature in record["creatures"].items() if creature["counted"]}
    assert counted == passed
    assert record["totals"]["creatures_counted"] == len(counted)
    is_default = len(counted) >= record["rule"]["default_at"]
    assert record["rule"]["verdict"].startswith(
        "the plan-guided rig" if is_default else "the sketch"
    )
    # A passed item names its look; a refused one names the rule it broke, in its own words.
    for item in record["items"]:
        if item["outcome"] == "passed":
            assert item["look_sha256"] and item["refusal"] is None
        else:
            assert item["look_sha256"] is None and item["refusal"] and item["refusal_detail"]
    job = record["job"]
    assert job["upper_bound_cost_microdollars"] >= job["computed_cost_microdollars"]
