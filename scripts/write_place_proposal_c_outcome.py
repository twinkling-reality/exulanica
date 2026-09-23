"""Write option C's outcome record, bound to its pre-registration.

    python scripts/write_place_proposal_c_outcome.py --development DEV.json --held-out HELD.json

The numbers are read from the two runs ``measure_place_proposal.py`` wrote under C's
pre-registration. Each row carries the adjusted proposal the stage would write, and the second
call's completeness answer verbatim, so the one failure and the one false alarm can be read in the
record itself. No float appears in it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from exulanica.canonical import canonical_json

ROOT = Path(__file__).resolve().parents[1]
C_PRE = "docs/evaluation/2026-09-22-vision-place-proposal-c-preregistration.json"
C_OUT = "docs/evaluation/2026-09-22-vision-place-proposal-c-outcome.json"


def _rows(run: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "file": row["file"],
            "kind": row["score"]["kind"],
            "arm": row["score"]["arm"],
            "proposed_place": row["score"]["proposed_place"],
            "completeness": (row.get("completeness") or {}).get("completeness"),
            "calls": row.get("calls", 1),
            "positive_pass": row["score"]["positive_pass"],
            "false_proposal": row["score"]["false_proposal"],
            "invented_place": row["score"]["invented_place"],
            "latency_ms": row["latency_ms"],
            "micro_usd": row["micro_usd"],
        }
        for row in run["arms"]["candidate"]["rows"]
        if "score" in row
    ]


def _run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_prompt_sha256": run["arms"]["candidate"]["prompt_sha256"],
        "baseline_prompt_sha256": run["arms"]["baseline"]["prompt_sha256"],
        "baseline_summary": run["arms"]["baseline"]["summary"],
        "candidate_summary": run["arms"]["candidate"]["summary"],
        "gates": run["gates"],
        "candidate_rows": _rows(run),
    }


def record(development: dict[str, Any], held_out: dict[str, Any]) -> dict[str, Any]:
    pre = json.loads((ROOT / C_PRE).read_bytes())["record"]
    return {
        "predecessor_record": {
            "path": C_PRE,
            "record_sha256": hashlib.sha256(canonical_json(pre)).hexdigest(),
        },
        "development": _run(development),
        "held_out": _run(held_out),
        "verdict": "FAILED THE PRE-REGISTERED NEGATIVE GATE, on one photograph. Development "
                   "passed every gate. On the held-out split C proposed a place from all 8 "
                   "place names, proposed nothing from products, slogans or a person's name, "
                   "gave nothing for the fully hidden board, and lowered every proposal from a "
                   "partly hidden board to low confidence. One of those, from a board cut by "
                   "the frame, carried the label 'Ashcombe (partial)': the word 'partial' is in "
                   "no text in the frame, so under the word rule this record inherits it is a "
                   "false proposal and an invented place. The gate allows none, so C is not "
                   "adopted under this record, and no part of it is revised against these "
                   "photographs, which are now spent.",
        "findings": [
            "The completeness question, asked on its own, caught both boards with a tree in "
            "front of them that two wordings inside the observation had judged whole, on the "
            "development split, and every partly hidden board on the held-out split.",
            "The failing label came from the observation call, not the completeness call: the "
            "observation wrote '(partial)' into the label where its instruction asked for it in "
            "the supporting evidence. Lowering the confidence afterwards cannot remove a word "
            "the label already carries.",
            "One whole street sign, Chestnut Road, was judged partly hidden and its correct "
            "proposal lowered to low confidence. The probe measured 12 of 12 whole nameplates; "
            "this was a street blade, a kind it did not include. The positive gate counts the "
            "proposal, not its confidence, so this is reported here rather than scored.",
            "A rule this suggests, not tested here and not a decision this record makes: keep "
            "in a proposal's label only words the observation itself transcribed from that "
            "sign. It is deterministic, so it would hold whatever the model writes, and it would "
            "drop a descriptive word like 'partial' as surely as a completed hidden one. Judging "
            "it needs a fresh held-out split; the second experiment's is spent.",
        ],
        "cost_micro_usd": {
            "development": development["arms"]["baseline"]["summary"]["micro_usd_total"]
            + development["arms"]["candidate"]["summary"]["micro_usd_total"],
            "held_out": held_out["arms"]["baseline"]["summary"]["micro_usd_total"]
            + held_out["arms"]["candidate"]["summary"]["micro_usd_total"],
        },
        "adoption_condition": pre["adoption_condition"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--development", required=True)
    parser.add_argument("--held-out", required=True)
    arguments = parser.parse_args()
    body = record(
        json.loads(Path(arguments.development).read_bytes()),
        json.loads(Path(arguments.held_out).read_bytes()),
    )
    document = {"profile": "exulanica.digest-bound-record/v1", "record": body,
                "record_sha256": hashlib.sha256(canonical_json(body)).hexdigest()}
    (ROOT / C_OUT).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{C_OUT} record_sha256 {document['record_sha256']}")


if __name__ == "__main__":
    main()
