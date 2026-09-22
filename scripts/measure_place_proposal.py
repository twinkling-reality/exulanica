"""Measure a vision prompt change against the pre-registered place-proposal gates.

    EXULANICA_BUDGET_USD=1.00 python scripts/measure_place_proposal.py --cap-usd 1.00 \
        --photos DIR --split development|held_out --arms baseline,candidate --out OUT.json

THIS SCRIPT SPENDS MONEY, one vision call per photograph per arm. It refuses to start unless the
ceiling is stated twice, in the environment where ``BudgetGuard`` reads it and on the command line,
and the two agree exactly.

The baseline arm is ``exulanica/ingest/vision.py`` as it stands at the pre-registration's base
commit, loaded from git; the candidate arm is the same module in this worktree. Each arm makes the
production call through its own ``NebiusVisionModel.observe``, so its messages, schema and
parameters are exactly what that version of the product sends, and both receive the same
rendition bytes. The vision role is pinned to its primary with the fallback disabled, so a
provider failure is recorded rather than answered by a different model in one arm only.

The gates are read from the pre-registration record rather than restated here. A second copy of a
threshold is a second source of truth, and the copy that drifts is the one nobody is looking at.
Nothing is written to any database.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

import exulanica.ingest.vision as candidate_vision
from exulanica.ingest.derivatives import render
from exulanica.ingest.stages import stage
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import ModelError
from exulanica.models.manifest import Role, load_manifest

ROOT = Path(__file__).resolve().parents[1]
PREREGISTRATION = ROOT / "docs/evaluation/2026-09-22-vision-place-proposal-preregistration.json"
MICRO = Decimal("0.000001")
STOPWORDS = frozenset({"A", "AN", "AND", "AT", "OF", "THE"})
NEGATIVE_NULL_KINDS = frozenset({"no_text", "product", "slogan", "person_name"})
#: A board covered by something, or cut by the frame. Either may be proposed from only what is
#: visible, at low confidence, or not at all.
PARTIAL_KINDS = frozenset({"partial", "partial_cut"})


def words(text: str | None) -> list[str]:
    return [w for w in re.split(r"[^A-Z]+", (text or "").upper()) if w and w not in STOPWORDS]


def micro_usd(value: Decimal) -> int:
    return int((value / MICRO).to_integral_value(rounding="ROUND_CEILING"))


def baseline_module(base_commit: str):
    """``exulanica/ingest/vision.py`` at the base commit, imported under its own name."""
    source = subprocess.run(
        ["git", "show", f"{base_commit}:exulanica/ingest/vision.py"],
        check=True, capture_output=True, text=True, cwd=ROOT,
    ).stdout
    path = Path(tempfile.mkdtemp()) / "baseline_vision.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location("baseline_vision", path)
    module = importlib.util.module_from_spec(spec)
    # Registered before it runs: a dataclass in the module resolves its own annotations through
    # sys.modules, and an unregistered module fails at the first decorator.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pinned_vision(manifest):
    binding = manifest[Role.VISION]
    roles = dict(manifest.roles)
    roles[Role.VISION] = dataclasses.replace(binding, fallback=None)
    return dataclasses.replace(manifest, roles=roles)


def rendition(path: Path) -> bytes:
    """The bytes production sends: the registry's rendition of the upright image."""
    upright = ImageOps.exif_transpose(Image.open(path))
    return render(upright, stage("rendition")).data


def observe(module, manifest, image: bytes, cap: Decimal) -> dict[str, Any]:
    client = ModelClient(manifest=manifest, budget=BudgetGuard(ceiling_usd=cap))
    started = time.monotonic()
    try:
        result = module.NebiusVisionModel(client).observe(image_bytes=image,
                                                          media_type="image/jpeg")
    except (ModelError, module.ObservationError) as exc:
        return {"failure": f"{type(exc).__name__}: {str(exc)[:400]}",
                "latency_ms": round((time.monotonic() - started) * 1000),
                "micro_usd": micro_usd(client.budget.spent_usd)}
    return {
        "payload": result.payload,
        "model_id": result.model_id,
        "models_tried": list(result.tried),
        "usage": result.cost,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "micro_usd": micro_usd(client.budget.spent_usd),
    }


def score(truth: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    place = payload.get("proposed_place")
    label = words(place["label"]) if place else []
    board = set(words(" ".join(truth["place_board_visible_words"])))
    other = set(words(" ".join(truth["other_text_words"])))
    frame = board | other | set(words(" ".join(truth["notice_words"])))
    name = set(words(truth["place_name"]))
    kind = truth["kind"]

    positive_pass = None
    if truth["arm"] == "positive":
        positive_pass = bool(
            place
            and name <= set(label)
            and set(label) <= frame
            and place["basis"] == "signage"
            and name & set(words(place.get("supporting_evidence")))
        )

    false_proposal = False
    if kind in NEGATIVE_NULL_KINDS:
        false_proposal = place is not None
    elif kind in PARTIAL_KINDS:
        false_proposal = place is not None and (
            place["confidence"] != "low" or not set(label) <= board
        )
    invented = bool(false_proposal and (kind == "no_text" or not set(label) <= frame))

    transcribed = None
    key_text = board | other
    if key_text:
        read = set(words(" ".join(entry["text"] for entry in payload.get("legible_text", []))))
        transcribed = key_text <= read

    evidence = (place or {}).get("supporting_evidence") or ""
    return {
        "file": truth["file"], "kind": kind, "arm": truth["arm"],
        "proposed_place": place,
        # Reported, never gating: whether a proposal from a partly hidden board says so.
        "evidence_says_partly_hidden": (
            None if kind not in PARTIAL_KINDS or place is None
            else any(w in evidence.lower() for w in ("partly hidden", "partially hidden",
                                                     "partly obscured", "partially obscured",
                                                     "cut off", "obscured", "hidden", "covered"))
        ),
        "positive_pass": positive_pass,
        "false_proposal": false_proposal,
        "invented_place": invented,
        "text_transcribed": transcribed,
        "people_drawn": truth["people_drawn"],
        "people_reported": len(payload.get("people", [])),
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [row for row in rows if "score" in row]
    s = [row["score"] for row in scored]
    latencies = sorted(row["latency_ms"] for row in rows)
    p95 = latencies[max(0, -(-len(latencies) * 95 // 100) - 1)] if latencies else None
    return {
        "photographs": len(rows),
        "failed_calls": sum(1 for row in rows if "failure" in row),
        "positive_pass": sum(1 for x in s if x["positive_pass"]),
        "positive_of": sum(1 for x in s if x["arm"] == "positive"),
        "false_proposals": sum(1 for x in s if x["false_proposal"]),
        "invented_places": sum(1 for x in s if x["invented_place"]),
        "negative_of": sum(1 for x in s if x["arm"] == "negative"),
        "text_transcribed": sum(1 for x in s if x["text_transcribed"]),
        "text_scenes": sum(1 for x in s if x["text_transcribed"] is not None),
        "person_name_with_trace": sum(
            1 for x in s if x["kind"] == "person_name" and x["people_reported"] > 0),
        "people_reported_where_none_drawn": sum(
            x["people_reported"] for x in s if x["people_drawn"] == 0),
        "latency_ms_p95": p95,
        "micro_usd_total": sum(row["micro_usd"] for row in rows),
    }


def gates(split: str, base: dict[str, Any], cand: dict[str, Any], pre: dict[str, Any]) -> dict:
    g = pre["gates"]
    minimum = g["positive"][f"{split}_min_pass"]
    checks = {
        "negative_zero_false_proposals": cand["false_proposals"] <= g["negative"][
            "max_false_proposals"],
        "positive_minimum": cand["positive_pass"] >= minimum,
        "text_not_worse_by_more_than_one": cand["text_transcribed"] >= base[
            "text_transcribed"] - 1,
        "person_traces_not_worse": cand["person_name_with_trace"] >= base[
            "person_name_with_trace"],
        "no_more_people_where_none_drawn": cand["people_reported_where_none_drawn"] <= base[
            "people_reported_where_none_drawn"],
        "latency_p95": (cand["latency_ms_p95"] or 0) <= g["latency_ms"]["per_photograph_p95_max"],
        "cost_at_most_twice": cand["micro_usd_total"] <= 2 * max(base["micro_usd_total"], 1),
        "no_failed_calls": cand["failed_calls"] == 0,
    }
    return {"checks": checks, "all_pass": all(checks.values()),
            "positive_minimum_used": minimum}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cap-usd", required=True)
    parser.add_argument("--photos", required=True)
    parser.add_argument("--split", choices=("development", "held_out"), required=True)
    parser.add_argument("--arms", default="baseline,candidate")
    parser.add_argument("--out", required=True)
    parser.add_argument("--preregistration", default=str(PREREGISTRATION),
                        help="the record whose splits and gates this run is judged by")
    arguments = parser.parse_args()
    record_path = Path(arguments.preregistration).resolve()

    stated = Decimal(arguments.cap_usd)
    if Decimal(os.environ.get("EXULANICA_BUDGET_USD", "0")) != stated:
        raise SystemExit("--cap-usd and EXULANICA_BUDGET_USD must agree exactly")

    pre = json.loads(record_path.read_bytes())["record"]
    photos = Path(arguments.photos)
    truth_file = next(photos.glob("ground-truth-*.json"))
    bound = pre["splits"][arguments.split]
    if hashlib.sha256(truth_file.read_bytes()).hexdigest() != bound["ground_truth_sha256"]:
        raise SystemExit("this corpus is not the one the pre-registration binds")
    truths = json.loads(truth_file.read_bytes())
    for entry, frozen in zip(truths, bound["photographs"], strict=True):
        if hashlib.sha256((photos / entry["file"]).read_bytes()).hexdigest() != frozen["sha256"]:
            raise SystemExit(f"{entry['file']} is not the photograph the pre-registration binds")

    manifest = pinned_vision(load_manifest())
    modules = {"baseline": baseline_module(pre["base_commit"]), "candidate": candidate_vision}
    arms = [arm for arm in arguments.arms.split(",") if arm]
    results: dict[str, Any] = {}
    for arm in arms:
        module = modules[arm]
        rows = []
        for truth in truths:
            outcome = observe(module, manifest, rendition(photos / truth["file"]), stated)
            row = {"file": truth["file"], **outcome}
            if "payload" in outcome:
                row["score"] = score(truth, outcome["payload"])
            rows.append(row)
            flag = row.get("score", {})
            print(f"{arm:<9} {truth['file']:<40} {outcome['latency_ms']:>6} ms "
                  f"place={'-' if not flag.get('proposed_place') else flag['proposed_place']['label']!r} "
                  f"{'FAIL:' + outcome['failure'][:60] if 'failure' in outcome else ''}")
        results[arm] = {
            "prompt_sha256": module.prompt_digest(),
            "rows": rows,
            "summary": summarise(rows),
        }

    verdict = None
    if "baseline" in results and "candidate" in results:
        verdict = gates(arguments.split, results["baseline"]["summary"],
                        results["candidate"]["summary"], pre)
    Path(arguments.out).write_text(json.dumps({
        "preregistration_record_sha256": json.loads(record_path.read_bytes())["record_sha256"],
        "preregistration_path": str(record_path.relative_to(ROOT)),
        "split": arguments.split,
        "model_id": manifest[Role.VISION].primary.model_id,
        "arms": results,
        "gates": verdict,
    }, indent=2, sort_keys=True, default=str) + "\n")
    for arm, body in results.items():
        print(arm, json.dumps(body["summary"]))
    if verdict:
        print("gates", json.dumps(verdict))


if __name__ == "__main__":
    main()
