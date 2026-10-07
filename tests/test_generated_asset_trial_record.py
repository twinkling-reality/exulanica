"""The Nebius trial's evaluation record is what its script builds from the tracked evidence."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs/evaluation/2026-10-07-nebius-generated-assets-trial.json"


def _script():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "record_generated_asset_trial", ROOT / "scripts/record_generated_asset_trial.py"
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_the_committed_record_is_the_one_the_evidence_builds() -> None:
    committed = json.loads(RECORD.read_bytes())["record"]
    assert committed == _script().build()


def test_every_job_s_upper_bound_covers_its_computed_cost_and_the_totals_add_up() -> None:
    record = json.loads(RECORD.read_bytes())["record"]
    for job in record["jobs"]:
        assert job["upper_bound_cost_microdollars"] >= job["computed_cost_microdollars"], job
    totals = record["totals"]
    assert totals["computed_cost_microdollars"] == sum(
        j["computed_cost_microdollars"] for j in record["jobs"]
    )
    assert totals["pieces_with_receipts"] == sum(j["pieces"] for j in record["jobs"])
