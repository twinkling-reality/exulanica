"""Can the vision model tell a whole sign from a partly hidden one? Asked directly, and only that.

    python scripts/probe_sign_completeness.py preregister OUT.json --photos DIR
    EXULANICA_BUDGET_USD=1.00 python scripts/probe_sign_completeness.py run --cap-usd 1.00 \
        --photos DIR --out RESULT.json

A place proposal can be made to depend on whether a sign is complete only if the model can see
whether it is complete. The held-out failures were proposals from partly covered boards, stated
at medium confidence with no mention of the cover, and on one board the model wrote that the sign
was "fully visible and unobstructed" while a canopy covered half of it. That is evidence the model
does not perceive the cover. This measures it, separately from any place proposal, before any
wording is written to rely on it.

``preregister`` freezes the question, the schema, the corpus (every photograph by SHA-256) and the
decision rule. ``run`` refuses unless the question, schema and corpus are still the ones frozen,
so the probe cannot be reworded after its answers are seen.

The call uses the vision role's primary, pinned with its fallback off, on the rendition bytes
production sends, one call per photograph, temperature 0. Nothing is written to any database.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exulanica.canonical import canonical_json
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import ModelError
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.messages import image_part
from exulanica.models.schema import response_format_for_schema
from measure_place_proposal import micro_usd, rendition

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs/evaluation/2026-09-22-sign-completeness-probe-preregistration.json"

SYSTEM = (
    "You look at one photograph and answer one question about the most prominent sign with "
    "writing on it. Report only what is visible. Do not guess at anything you cannot see. "
    "Reply with one JSON object matching the schema and nothing else."
)
QUESTION = (
    "Is there a sign with writing on it in this photograph? If there is, is the whole sign "
    "visible, or is part of it hidden behind something or cut off by the edge of the "
    "photograph? Transcribe the words you can read."
)
SCHEMA_NAME = "exulanica_sign_completeness_probe_v1"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sign_present": {"type": "boolean"},
        "completeness": {"type": "string", "enum": ["whole", "partly_hidden", "no_sign"]},
        "readable_text": {"type": "string"},
    },
    "required": ["sign_present", "completeness", "readable_text"],
    "additionalProperties": False,
}

RULE = {
    "partial_detected_min": 10, "partial_of": 12,
    "covered_detected_min": 7, "covered_of": 8,
    "whole_correct_min": 10, "whole_of": 12,
}


def probe_digest() -> str:
    body = SYSTEM + "\n" + QUESTION + "\n" + json.dumps(SCHEMA, sort_keys=True) + SCHEMA_NAME
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def corpus(directory: Path) -> tuple[list[dict[str, Any]], str]:
    truth = directory / "ground-truth-probe.json"
    entries = json.loads(truth.read_bytes())
    return [
        {"file": e["file"], "state": e["state"], "how": e["how"],
         "sha256": hashlib.sha256((directory / e["file"]).read_bytes()).hexdigest()}
        for e in entries
    ], hashlib.sha256(truth.read_bytes()).hexdigest()


def preregister(out: Path, photos: Path) -> None:
    photographs, truth_sha = corpus(photos)
    body = {
        "question": "Can the vision role's primary tell a whole sign from a partly hidden one, "
                    "asked directly and separately from any place proposal?",
        "why": "Option B makes a place proposal depend on the model's own judgement that a "
               "sign is complete. If the model cannot make that judgement, no wording can make "
               "a proposal depend on it, and B stops here.",
        "already_seen": "No model output of any kind exists for these photographs. Their "
                        "drawings were viewed as a contact sheet to confirm they render as "
                        "intended; two drawing errors were corrected before this was written.",
        "model": {"role": "vision", "model_id": "MiniMaxAI/MiniMax-M3", "fallback": "disabled",
                  "calls_per_photograph": 1, "temperature": 0},
        "input": "the rendition production sends (exulanica.ingest.derivatives.render)",
        "probe": {"system": SYSTEM, "question": QUESTION, "schema_name": SCHEMA_NAME,
                  "schema": SCHEMA, "probe_sha256": probe_digest()},
        "corpus": {"drawn_by": "scripts/make_sign_completeness_probe.py",
                   "ground_truth_sha256": truth_sha, "photographs": photographs,
                   "whole": 12, "whole_with_tree_beside": 4,
                   "partial": 12, "partial_covered": 8, "partial_cut_by_frame": 4},
        "scoring": "a whole board is correct when completeness is whole; a partial board is "
                   "detected when completeness is partly_hidden. no_sign is wrong for both.",
        "decision_rule": {
            **RULE,
            "can_tell_when": "partial detected at least 10 of 12 AND covered boards detected "
                             "at least 7 of 8 AND whole boards correct at least 10 of 12",
            "why_covered_separately": "the held-out failures were covered boards. A model that "
                                      "sees frame edges but not covers would pass on the whole "
                                      "partial arm and still miss the failure that matters.",
            "why_whole_as_well": "a model that calls every sign partly hidden would detect "
                                 "every partial board and suppress every proposal.",
            "chance": "at random, 10 or more of 12 happens with probability about 0.019 per "
                      "arm, so passing both arms is not luck",
            "if_it_cannot_tell": "B stops. No wording 3 is written, and the finding goes to "
                                 "root for A or C.",
            "if_it_can": "wording 3 gates the proposal on the model's own completeness "
                         "judgement, then development with 4 or more partial boards, then a "
                         "fresh held-out split pre-registered before any call.",
        },
    }
    document = {"profile": "exulanica.digest-bound-record/v1", "record": body,
                "record_sha256": hashlib.sha256(canonical_json(body)).hexdigest()}
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{out} record_sha256 {document['record_sha256']} probe_sha256 {probe_digest()}")


def run(photos: Path, out: Path, cap: Decimal) -> None:
    frozen = json.loads(RECORD.read_bytes())["record"]
    if frozen["probe"]["probe_sha256"] != probe_digest():
        raise SystemExit("the probe question or schema differs from the one pre-registered")
    photographs, truth_sha = corpus(photos)
    if truth_sha != frozen["corpus"]["ground_truth_sha256"] or photographs != frozen["corpus"][
            "photographs"]:
        raise SystemExit("this corpus is not the one the pre-registration binds")

    manifest = load_manifest()
    roles = dict(manifest.roles)
    roles[Role.VISION] = dataclasses.replace(manifest[Role.VISION], fallback=None)
    manifest = dataclasses.replace(manifest, roles=roles)

    rows = []
    for entry in photographs:
        client = ModelClient(manifest=manifest, budget=BudgetGuard(ceiling_usd=cap))
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": QUESTION},
                image_part(rendition(photos / entry["file"]), media_type="image/jpeg"),
            ]},
        ]
        started = time.monotonic()
        try:
            call = client.chat(Role.VISION, messages, prompt_version=f"probe-{probe_digest()[:12]}",
                               temperature=0.0, image_prompt_tokens=800, use_cache=False,
                               response_format=response_format_for_schema(SCHEMA, SCHEMA_NAME))
            answer = dict(call.payload or {})
            failure = None
        except ModelError as exc:
            answer, failure = {}, f"{type(exc).__name__}: {str(exc)[:300]}"
        row = {**entry, "answer": answer, "failure": failure,
               "latency_ms": round((time.monotonic() - started) * 1000),
               "micro_usd": micro_usd(client.budget.spent_usd)}
        want = "whole" if entry["state"] == "whole" else "partly_hidden"
        row["correct"] = answer.get("completeness") == want
        rows.append(row)
        print(f"{entry['file']:<40} said={answer.get('completeness')!s:<14} "
              f"{'ok' if row['correct'] else 'WRONG'}  read={answer.get('readable_text')!r}")

    def count(predicate) -> int:
        return sum(1 for r in rows if predicate(r) and r["correct"])

    tally = {
        "partial_detected": count(lambda r: r["state"] == "partial"),
        "covered_detected": count(lambda r: r["how"].startswith("cover")),
        "cut_detected": count(lambda r: r["how"] == "cut"),
        "whole_correct": count(lambda r: r["state"] == "whole"),
        "whole_with_tree_beside_correct": count(lambda r: r["how"] == "tree_beside"),
        "failed_calls": sum(1 for r in rows if r["failure"]),
        "micro_usd_total": sum(r["micro_usd"] for r in rows),
    }
    can_tell = (tally["partial_detected"] >= RULE["partial_detected_min"]
                and tally["covered_detected"] >= RULE["covered_detected_min"]
                and tally["whole_correct"] >= RULE["whole_correct_min"])
    out.write_text(json.dumps({"preregistration_record_sha256": json.loads(RECORD.read_bytes())[
        "record_sha256"], "probe_sha256": probe_digest(), "tally": tally, "can_tell": can_tell,
        "rows": rows}, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps({"tally": tally, "can_tell": can_tell}, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("preregister")
    pre.add_argument("out")
    pre.add_argument("--photos", required=True)
    go = sub.add_parser("run")
    go.add_argument("--cap-usd", required=True)
    go.add_argument("--photos", required=True)
    go.add_argument("--out", required=True)
    arguments = parser.parse_args()
    if arguments.command == "preregister":
        preregister(Path(arguments.out), Path(arguments.photos))
        return
    stated = Decimal(arguments.cap_usd)
    if Decimal(os.environ.get("EXULANICA_BUDGET_USD", "0")) != stated:
        raise SystemExit("--cap-usd and EXULANICA_BUDGET_USD must agree exactly")
    run(Path(arguments.photos), Path(arguments.out), stated)


if __name__ == "__main__":
    main()
