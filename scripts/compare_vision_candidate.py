"""Comparison B: the candidate vision model on the rendition production sends, scored as pre-registered.

    EXULANICA_BUDGET_USD=1.00 python scripts/compare_vision_candidate.py --cap-usd 1.00 \
        --photos HELD_OUT_DIR --baseline BASELINE.json --out OUT.json

The rule this applies was frozen in docs/evaluation/2026-09-22-model-selection-preregistration.json
before any candidate output was examined: the same approved renditions, only the VISION binding
varied, boxes scored against ground truth by construction, and a candidate adopted only if it cuts
the primary error rate by the frozen margin AND reports no person on any photograph (none was
drawn). The thresholds are read from that record, not restated here.

The baseline arm is the held-out run already scored under that record (``BASELINE.json``, written
by ``measure_vision_observations.py`` through the product routes). It is not re-run: a second
baseline sample chosen after the first had been seen would be a selection, not a measurement.

**The prompt is held at the one the record was written against**, which is the vision module at
the base commit named in the place-proposal pre-registration, loaded from git. This worktree also
carries a rewritten vision prompt; using it here would vary the prompt and the model at once, and
the difference could not be attributed to either.

One call per photograph. Nothing is written to any database.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import ModelError
from exulanica.models.manifest import Role, load_manifest
from measure_place_proposal import baseline_module, micro_usd, rendition
from measure_vision_observations import IOU_THRESHOLD, score

ROOT = Path(__file__).resolve().parents[1]
PREREGISTRATION = ROOT / "docs/evaluation/2026-09-22-model-selection-preregistration.json"
PROMPT_BASE = ROOT / "docs/evaluation/2026-09-22-vision-place-proposal-preregistration.json"
CANDIDATE = "openbmb/MiniCPM-V-4_5"


def pinned(manifest, model_id: str):
    binding = manifest[Role.VISION]
    roles = dict(manifest.roles)
    roles[Role.VISION] = dataclasses.replace(
        binding, primary=manifest.spec(model_id), fallback=None
    )
    return dataclasses.replace(manifest, roles=roles)


def primary_basis_points(rows: list[dict[str, Any]]) -> dict[str, int]:
    """(omitted salient + unsupported reported) / (drawn salient + reported), in basis points."""
    omitted = sum(len(row["salient"]["missing"]) for row in rows)
    unsupported = sum(len(row["unsupported_objects"]) for row in rows)
    drawn = sum(row["salient"]["drawn"] for row in rows)
    reported = sum(row["reported_objects"] for row in rows)
    items = drawn + reported
    return {
        "omitted_salient": omitted, "unsupported_reported": unsupported,
        "drawn_salient": drawn, "reported": reported,
        "errors": omitted + unsupported, "items": items,
        "basis_points": (omitted + unsupported) * 10000 // items if items else 0,
    }


def secondary(rows: list[dict[str, Any]]) -> dict[str, int]:
    signed = [row for row in rows if row["sign_drawn"]]
    return {
        "signed": len(signed),
        "sign_transcribed": sum(1 for row in signed if row["sign_text_transcribed"]),
        "place_proposed_on_signed": sum(1 for row in signed if row["place_proposed"]),
        "place_proposed_on_unsigned": sum(
            1 for row in rows if not row["sign_drawn"] and row["place_proposed"]),
        "photographs_with_a_person_reported": sum(1 for row in rows if row["people_reported"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cap-usd", required=True)
    parser.add_argument("--photos", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--out", required=True)
    arguments = parser.parse_args()
    stated = Decimal(arguments.cap_usd)
    if Decimal(os.environ.get("EXULANICA_BUDGET_USD", "0")) != stated:
        raise SystemExit("--cap-usd and EXULANICA_BUDGET_USD must agree exactly")

    rule = json.loads(PREREGISTRATION.read_bytes())["record"]["comparison_b_vision"]
    base_commit = json.loads(PROMPT_BASE.read_bytes())["record"]["base_commit"]
    module = baseline_module(base_commit)
    photos = Path(arguments.photos)
    truths = {
        entry["file"]: entry
        for entry in json.loads(next(photos.glob("ground-truth-*.json")).read_bytes())
    }
    baseline_rows = json.loads(Path(arguments.baseline).read_bytes())["per_photograph"]
    if sorted(row["file"] for row in baseline_rows) != sorted(truths):
        raise SystemExit("the baseline record does not cover exactly these photographs")

    manifest = pinned(load_manifest(), CANDIDATE)
    rows, latencies, failures = [], [], []
    spent = Decimal(0)
    for name in sorted(truths):
        client = ModelClient(manifest=manifest, budget=BudgetGuard(ceiling_usd=stated))
        started = time.monotonic()
        try:
            result = module.NebiusVisionModel(client).observe(
                image_bytes=rendition(photos / name), media_type="image/jpeg")
        except (ModelError, module.ObservationError) as exc:
            failures.append({"file": name, "failure": f"{type(exc).__name__}: {str(exc)[:400]}"})
            latencies.append(round((time.monotonic() - started) * 1000))
            spent += client.budget.spent_usd
            print(f"{name}  FAILED {type(exc).__name__}")
            continue
        latency = round((time.monotonic() - started) * 1000)
        latencies.append(latency)
        spent += client.budget.spent_usd
        document = {"observation": result.payload,
                    "header": {"usage": result.cost, "model_ref": {"model_id": result.model_id},
                               "models_tried": list(result.tried)}}
        row = score(truths[name], document)
        row["latency_ms"] = latency
        rows.append(row)
        print(f"{name}  {latency:>6} ms  objects={row['reported_objects']}  "
              f"people={row['people_reported']}  place={row['place_proposed'] is not None}")

    ordered = sorted(latencies)
    p95 = ordered[max(0, -(-len(ordered) * 95 // 100) - 1)] if ordered else None
    base_usd = sum(Decimal(row["usage"]["usd_estimate"]) for row in baseline_rows)
    base_primary = primary_basis_points(baseline_rows)
    cand_primary = primary_basis_points(rows) if rows else None
    minimum = rule["practical_minimum_improvement"]["minimum_reduction_basis_points"]
    checks = {
        "every_photograph_answered": not failures and len(rows) == len(truths),
        "primary_reduced_by_minimum": bool(
            cand_primary and base_primary["basis_points"] - cand_primary["basis_points"]
            >= minimum),
        "no_person_reported_anywhere": all(row["people_reported"] == 0 for row in rows),
        "latency_p95_within_ceiling": p95 is not None
        and p95 <= rule["latency_ceilings_ms"]["per_photograph_p95"],
        "cost_at_most_twice_baseline": spent <= 2 * base_usd,
    }
    Path(arguments.out).write_text(json.dumps({
        "candidate": CANDIDATE,
        "baseline": "MiniMaxAI/MiniMax-M3",
        "prompt_sha256": module.prompt_digest(),
        "iou_threshold_basis_points": int(IOU_THRESHOLD * 10000),
        "baseline_primary": base_primary,
        "candidate_primary": cand_primary,
        "baseline_secondary": secondary(baseline_rows),
        "candidate_secondary": secondary(rows),
        "candidate_latency_ms_p95": p95,
        "baseline_micro_usd": micro_usd(base_usd),
        "candidate_micro_usd": micro_usd(spent),
        "failures": failures,
        "checks": checks,
        "adopt": all(checks.values()),
        "per_photograph": rows,
    }, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps({"baseline_primary": base_primary, "candidate_primary": cand_primary,
                      "checks": checks, "adopt": all(checks.values())}, indent=1))


if __name__ == "__main__":
    main()
