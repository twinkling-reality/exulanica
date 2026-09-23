"""Measure the place proposal policy against its pre-registered gates.

    EXULANICA_BUDGET_USD=1.00 python scripts/measure_place_proposal_d.py --cap-usd 1.00 \
        --photos DIR --split development|held_out --out OUT.json

THIS SCRIPT SPENDS MONEY: one observation call per photograph per arm, and for the candidate one
more call per photograph whose proposal survives the label rule. It refuses to start unless the
ceiling is stated twice, in the environment where ``BudgetGuard`` reads it and on the command line,
and the two agree exactly.

The baseline arm is ``exulanica/ingest/vision.py`` at the pre-registration's base commit, loaded
from git; the candidate arm is the same module in this tree, whose ``observe`` makes the
observation call, applies ``exulanica.ingest.place_proposal``, and asks the sign question when a
label survives. Each arm makes the production call through its own ``NebiusVisionModel.observe``
on the rendition bytes production sends. The vision role is pinned to its primary with the
fallback disabled, so a provider failure is recorded rather than answered by a different model in
one arm only.

What is scored is the observation each arm's stage would write from: for the candidate, the
proposal after the policy's decision; for the baseline, which decides nothing, its payload. The
definitions and gates are read from the pre-registration record, not restated here. Nothing is
written to any database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import exulanica.ingest.vision as candidate_vision
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import ModelError
from exulanica.models.manifest import Role, load_manifest
from measure_place_proposal import baseline_module, micro_usd, pinned_vision, rendition

ROOT = Path(__file__).resolve().parents[1]
PREREGISTRATION = ROOT / "docs/evaluation/2026-09-23-vision-place-proposal-d-preregistration.json"


def words(text: str | None, ignored: frozenset[str]) -> list[str]:
    return [w for w in re.split(r"[^A-Z]+", (text or "").upper()) if w and w not in ignored]


def observe(module, manifest, image: bytes, cap: Decimal) -> dict[str, Any]:
    client = ModelClient(manifest=manifest, budget=BudgetGuard(ceiling_usd=cap))
    started = time.monotonic()
    try:
        result = module.NebiusVisionModel(client).observe(
            image_bytes=image, media_type="image/jpeg"
        )
    except (ModelError, module.ObservationError) as exc:
        return {
            "failure": f"{type(exc).__name__}: {str(exc)[:400]}",
            "latency_ms": round((time.monotonic() - started) * 1000),
            "micro_usd": micro_usd(client.budget.spent_usd),
        }
    return {
        "payload": result.payload,
        "scored": result.observation.model_dump(mode="json"),
        "calls": getattr(result, "calls", 1),
        "place_check": getattr(result, "place_check", None),
        "model_id": result.model_id,
        "models_tried": list(result.tried),
        "usage": result.cost,
        "latency_ms": round((time.monotonic() - started) * 1000),
        # From the client's own budget, which records every call that returned a body, including
        # a sign question whose reply failed its schema.
        "micro_usd": micro_usd(client.budget.spent_usd),
    }


def score(truth: dict[str, Any], scored: dict[str, Any], ignored: frozenset[str]) -> dict:
    place = scored.get("proposed_place")
    label = set(words(place["label"], ignored)) if place else set()
    name = set(words(truth["place_name"], ignored))
    visible = set(words(" ".join(truth["place_board_visible_words"]), ignored))
    other = set(words(" ".join(truth["other_text_words"]), ignored))
    shown = visible | other | set(words(" ".join(truth["notice_words"]), ignored))

    positive = truth["arm"] == "positive"
    positive_pass = bool(place and label == name) if positive else None
    false_proposal = place is not None and (not positive or label != name)
    invented = bool(false_proposal and (truth["kind"] == "no_text" or not label <= shown))

    whole = (visible & set(words(truth["board_text"], ignored))) | other
    transcribed = None
    if whole:
        read = set(
            words(" ".join(entry["text"] for entry in scored.get("legible_text", [])), ignored)
        )
        transcribed = whole <= read
    return {
        "file": truth["file"],
        "kind": truth["kind"],
        "arm": truth["arm"],
        "proposed_place": place,
        "positive_pass": positive_pass,
        "false_proposal": false_proposal,
        "invented_place": invented,
        "text_transcribed": transcribed,
        "people_drawn": truth["people_drawn"],
        "people_reported": len(scored.get("people", [])),
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    s = [row["score"] for row in rows if "score" in row]
    latencies = sorted(row["latency_ms"] for row in rows)
    p95 = latencies[max(0, -(-len(latencies) * 95 // 100) - 1)] if latencies else None
    checks = [row.get("place_check") or {} for row in rows]
    return {
        "photographs": len(rows),
        "failed_calls": sum(1 for row in rows if "failure" in row),
        "sign_checks_failed": sum(1 for c in checks if c.get("sign_check_failure")),
        "second_calls": sum(1 for row in rows if row.get("calls", 1) == 2),
        "positive_pass": sum(1 for x in s if x["positive_pass"]),
        "positive_of": sum(1 for x in s if x["arm"] == "positive"),
        "false_proposals": sum(1 for x in s if x["false_proposal"]),
        "invented_places": sum(1 for x in s if x["invented_place"]),
        "negative_of": sum(1 for x in s if x["arm"] == "negative"),
        "text_transcribed": sum(1 for x in s if x["text_transcribed"]),
        "text_scenes": sum(1 for x in s if x["text_transcribed"] is not None),
        "person_name_with_trace": sum(
            1 for x in s if x["kind"] == "person_name" and x["people_reported"] > 0
        ),
        "people_reported_where_none_drawn": sum(
            x["people_reported"] for x in s if x["people_drawn"] == 0
        ),
        "outcomes": dict(sorted(Counter(c["outcome"] for c in checks if c).items())),
        "labels_with_dropped_words": sum(1 for c in checks if c.get("dropped_words")),
        "latency_ms_p95": p95,
        "micro_usd_total": sum(row["micro_usd"] for row in rows),
    }


def gates(split: str, base: dict[str, Any], cand: dict[str, Any], pre: dict[str, Any]) -> dict:
    g = pre["gates"]
    minimum = g["positive"][f"{split}_min_pass"]
    checks = {
        "no_false_proposal": cand["false_proposals"] <= g["negative"]["max_false_proposals"],
        "positive_minimum": cand["positive_pass"] >= minimum,
        "text_not_worse_by_more_than_one": cand["text_transcribed"] >= base["text_transcribed"] - 1,
        "person_traces_not_worse": cand["person_name_with_trace"] >= base["person_name_with_trace"],
        "no_more_people_where_none_drawn": cand["people_reported_where_none_drawn"]
        <= base["people_reported_where_none_drawn"],
        "latency_p95": (cand["latency_ms_p95"] or 0) <= g["latency_ms"]["per_photograph_p95_max"],
        "cost_at_most_twice": cand["micro_usd_total"] <= 2 * max(base["micro_usd_total"], 1),
        "no_failed_calls": cand["failed_calls"] == 0 and cand["sign_checks_failed"] == 0,
    }
    return {"checks": checks, "all_pass": all(checks.values()), "positive_minimum_used": minimum}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cap-usd", required=True)
    parser.add_argument("--photos", required=True)
    parser.add_argument("--split", choices=("development", "held_out"), required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--preregistration", default=str(PREREGISTRATION))
    arguments = parser.parse_args()

    stated = Decimal(arguments.cap_usd)
    if Decimal(os.environ.get("EXULANICA_BUDGET_USD", "0")) != stated:
        raise SystemExit("--cap-usd and EXULANICA_BUDGET_USD must agree exactly")
    record_path = Path(arguments.preregistration).resolve()
    document = json.loads(record_path.read_bytes())
    pre = document["record"]
    ignored = frozenset(pre["definitions"]["ignored_words"])

    photos = Path(arguments.photos)
    bound = pre["splits"][arguments.split]
    truth_file = photos / bound["ground_truth_file"]
    if hashlib.sha256(truth_file.read_bytes()).hexdigest() != bound["ground_truth_sha256"]:
        raise SystemExit("this corpus is not the one the pre-registration binds")
    truths = json.loads(truth_file.read_bytes())
    for entry, frozen in zip(truths, bound["photographs"], strict=True):
        digest = hashlib.sha256((photos / entry["file"]).read_bytes()).hexdigest()
        if entry["file"] != frozen["file"] or digest != frozen["sha256"]:
            raise SystemExit(f"{entry['file']} is not the photograph the pre-registration binds")

    manifest = pinned_vision(load_manifest())
    modules = {"baseline": baseline_module(pre["base_commit"]), "candidate": candidate_vision}
    results: dict[str, Any] = {}
    for arm, module in modules.items():
        rows = []
        for truth in truths:
            outcome = observe(module, manifest, rendition(photos / truth["file"]), stated)
            row = {"file": truth["file"], **outcome}
            if "scored" in outcome:
                row["score"] = score(truth, outcome["scored"], ignored)
            rows.append(row)
            place = row.get("score", {}).get("proposed_place")
            check = (outcome.get("place_check") or {}).get("outcome", "")
            print(
                f"{arm:<9} {truth['file']:<46} {outcome['latency_ms']:>6} ms "
                f"place={'-' if not place else place['label']!r} {check}"
                f"{' FAIL: ' + outcome['failure'][:80] if 'failure' in outcome else ''}"
            )
        results[arm] = {
            "prompt_sha256": module.prompt_digest(),
            "rows": rows,
            "summary": summarise(rows),
        }

    verdict = gates(
        arguments.split, results["baseline"]["summary"], results["candidate"]["summary"], pre
    )
    Path(arguments.out).write_text(
        json.dumps(
            {
                "preregistration_record_sha256": document["record_sha256"],
                "preregistration_path": str(record_path.relative_to(ROOT)),
                "split": arguments.split,
                "model_id": manifest[Role.VISION].primary.model_id,
                "place_proposal_policy_sha256": candidate_vision.PLACE_PROPOSAL_POLICY.digest(),
                "arms": results,
                "gates": verdict,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n"
    )
    for arm, body in results.items():
        print(arm, json.dumps(body["summary"]))
    print("gates", json.dumps(verdict))


if __name__ == "__main__":
    main()
