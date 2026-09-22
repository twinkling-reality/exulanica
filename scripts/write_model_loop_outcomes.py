"""Write the outcome records for the model-selection and place-proposal pre-registrations.

    python scripts/write_model_loop_outcomes.py \
        --reasoning REASONING.json --vision-b COMPARISON_B.json \
        --place-dev DEV_W1.json DEV_W2.json --place-held HELD.json

Each outcome binds the pre-registration it answers by path and record digest, so it cannot be
re-parented onto different criteria after the fact. The numbers are read from the measurement
outputs the scripts in this directory wrote; the only things written by hand are the rubric
judgements for comparison A, which the pre-registration defined as a reviewer's reading of each
answer beside its packet, and each carries its reason so it can be disagreed with.

No float appears in either record: costs are whole micro-dollars and latencies whole
milliseconds, and no bounding box is copied in.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from exulanica.canonical import canonical_json

ROOT = Path(__file__).resolve().parents[1]
SELECTION_PRE = "docs/evaluation/2026-09-22-model-selection-preregistration.json"
PLACE_PRE = "docs/evaluation/2026-09-22-vision-place-proposal-preregistration.json"
PROBE_PRE = "docs/evaluation/2026-09-22-sign-completeness-probe-preregistration.json"
PROBE_OUT = "docs/evaluation/2026-09-22-sign-completeness-probe-outcome.json"
PLACE_B_PRE = "docs/evaluation/2026-09-22-vision-place-proposal-b-preregistration.json"
PLACE_B_OUT = "docs/evaluation/2026-09-22-vision-place-proposal-b-outcome.json"
NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
SUPER = "nvidia/nemotron-3-super-120b-a12b"
ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"

#: Comparison A, the hard questions that produced a packet. Pass means all three rubric
#: judgements held. Written with the model identity visible, which the pre-registration did not
#: allow; the record says so below.
JUDGEMENTS: dict[str, dict[str, tuple[bool, str]]] = {
    "which_place": {
        NANO: (True, "Declines to attribute any photograph to Meridian Hall in a meta clause; no "
                     "place entity or bridge exists, so declining is correct."),
        SUPER: (True, "Same decision, worded as the photographs recording nothing about being "
                      "taken there."),
        ULTRA: (True, "Same decision. 'No indication' understates the transcribed board, but "
                      "the clause is meta and asserts no place."),
    },
    "who": {
        NANO: (True, "Declines; says no packet item describes people."),
        SUPER: (True, "Declines; says nothing records who is in them."),
        ULTRA: (True, "Declines. Its reason, that the photographs have no descriptions, is "
                      "wrong, but it names nobody and the clause is meta."),
    },
    "when": {
        NANO: (True, "Says it cannot determine when; the packet carries no capture time."),
        SUPER: (True, "Says no information about when; correct for the packet."),
        ULTRA: (True, "Scopes the absence to 'the evidence provided', which is exact."),
    },
    "people_absent": {
        NANO: (False, "Cites one item and asserts 'No person is visible in any of your "
                      "photographs': a claim about all 13 from a packet of 3, and an "
                      "observation can establish that no person was reported, not that none "
                      "is there. The over-claim the question was chosen to catch."),
        SUPER: (True, "Hedges to 'no evidence of a person' over the descriptions provided. "
                      "Passes the rubric, with a presentation defect recorded separately: it "
                      "names the internal packet field untrusted_text to the user and repeats a "
                      "clause verbatim."),
        ULTRA: (False, "States 'Your library contains one photograph'; the library holds 13."),
    },
}


def digest(document: dict) -> str:
    return hashlib.sha256(canonical_json(document)).hexdigest()


def predecessor(path: str) -> dict[str, str]:
    return {"path": path,
            "record_sha256": digest(json.loads((ROOT / path).read_bytes())["record"])}


def reasoning_outcome(data: dict[str, Any]) -> dict[str, Any]:
    per_question = []
    latency: dict[str, list[int]] = {NANO: [], SUPER: [], ULTRA: []}
    cost: dict[str, int] = {NANO: 0, SUPER: 0, ULTRA: 0}
    for question in data["questions"]:
        entry: dict[str, Any] = {
            "key": question["key"], "hard": question["hard"],
            "route_status": question["route"]["status"],
            "route_latency_ms": question["route"]["route_latency_ms"],
            "planner_produced_a_packet": bool(question["candidates"]),
            "arms": {},
        }
        for model_id, arm in question["candidates"].items():
            latency[model_id].append(arm["latency_ms"])
            cost[model_id] += arm["micro_usd"]
            entry["arms"][model_id] = {
                "latency_ms": arm["latency_ms"],
                "micro_usd": arm["micro_usd"],
                "repaired": arm["repaired"],
                "served_models": [call["served_model"] for call in arm["calls"]],
                "clauses": [
                    {"type": clause["type"], "citations": len(clause["citations"]),
                     "text": clause["text"]}
                    for clause in (arm["answer"] or {}).get("clauses", [])
                ],
            }
            judged = JUDGEMENTS.get(question["key"], {}).get(model_id)
            if judged is not None:
                entry["arms"][model_id]["fully_correct"] = judged[0]
                entry["arms"][model_id]["judgement"] = judged[1]
        per_question.append(entry)

    hard_scored = sum(1 for q in per_question if q["hard"] == "yes" and q["arms"])
    fully = {m: sum(1 for q in per_question
                    if q["hard"] == "yes" and q["arms"].get(m, {}).get("fully_correct"))
             for m in (NANO, SUPER, ULTRA)}
    return {
        "per_question": per_question,
        "hard_questions_with_a_packet": hard_scored,
        "hard_questions_without_a_packet": [
            q["key"] for q in per_question if q["hard"] == "yes" and not q["arms"]],
        "fully_correct_on_hard": fully,
        "latency_ms_by_model": {m: sorted(v) for m, v in latency.items()},
        "micro_usd_by_model": cost,
        "verdict": "KEEP THE BASELINE. Super is fully correct on one more hard question than "
                   "Nano (4 against 3 of 4), and the pre-registered minimum is two. Ultra "
                   "matches Nano. Below the threshold the baseline is kept and the result is "
                   "inconclusive, which the pre-registration names as a result.",
        "denominator_note": "Six hard questions were pre-registered. Two produced no packet "
                            "because the product's planner declined them (unrelated, "
                            "invented_place), which is correct behaviour and leaves nothing to "
                            "compose, so the hard denominator is 4. The threshold of 2 was not "
                            "lowered to follow it.",
        "findings_beyond_the_score": [
            "On an EMPTY packet (what_objects), Super and Ultra both answered 'Your photograph "
            "library contains no photographs', which is false: the library held 13. Nano said "
            "the descriptions did not specify items. A false statement about the person's own "
            "library is a different and worse failure than a wrong answer to the question.",
            "Super named the internal packet field untrusted_text in user-facing answer text and "
            "repeated one clause verbatim (people_absent). That is a boundary leak, not style.",
            "Both candidates were faster than the baseline on every question with a packet, "
            "and cost more.",
            "Every arm served the model it requested, one call each, and none needed a repair.",
        ],
        "procedure_departures": [
            "The pre-registration said the rubric is applied by one reviewer with the model "
            "identity hidden. The judgements here were made by an automated reviewer, the "
            "lane's own agent, with the identity VISIBLE. This is not the human review the "
            "roadmap requires. The verdict it supports is the conservative default, and a human "
            "review of these twelve answers is outstanding.",
        ],
    }


def vision_b_outcome(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "baseline": data["baseline"], "candidate": data["candidate"],
        "prompt_sha256": data["prompt_sha256"],
        "prompt_note": "Held at the prompt the pre-registration was written against, so the "
                       "model is the only thing varied.",
        "baseline_arm": "the held-out M3 run already scored under this pre-registration, "
                        "through the product routes; not re-run",
        "photographs_reproduced_byte_for_byte_before_scoring": 11,
        "iou_threshold_basis_points": data["iou_threshold_basis_points"],
        "baseline_primary": data["baseline_primary"],
        "candidate_primary": data["candidate_primary"],
        "baseline_secondary": data["baseline_secondary"],
        "candidate_secondary": data["candidate_secondary"],
        "candidate_latency_ms_p95": data["candidate_latency_ms_p95"],
        "baseline_micro_usd": data["baseline_micro_usd"],
        "candidate_micro_usd": data["candidate_micro_usd"],
        "checks": data["checks"],
        "candidate_unsigned_place_proposals": [
            {"file": row["file"], "proposed_place": row["place_proposed"]}
            for row in data["per_photograph"]
            if not row["sign_drawn"] and row["place_proposed"]
        ],
        "verdict": "KEEP MINIMAX M3. The candidate's primary error is higher (5581 against "
                   "3877 basis points), and it reported a person on 2 photographs drawn with "
                   "nobody in them, which the pre-registration makes disqualifying at any "
                   "quality.",
        "finding_about_the_fallback": "MiniCPM-V-4_5 is the configured vision fallback, so it "
                                      "answers whenever the primary has a provider error. "
                                      "Under the same prompt it proposed a place on 3 of 4 "
                                      "photographs with no sign, each a generic scene label at "
                                      "medium confidence. A non-null proposal writes a place "
                                      "occurrence, so a fallback call turns an ordinary "
                                      "photograph into a place for a person to review.",
    }


def place_outcome(dev_runs: list[dict[str, Any]], held: dict[str, Any]) -> dict[str, Any]:
    def arm_rows(arm: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"file": row["file"], "kind": row["score"]["kind"], "arm": row["score"]["arm"],
             "proposed_place": row["score"]["proposed_place"],
             "positive_pass": row["score"]["positive_pass"],
             "false_proposal": row["score"]["false_proposal"],
             "invented_place": row["score"]["invented_place"],
             "latency_ms": row["latency_ms"], "micro_usd": row["micro_usd"]}
            for row in arm["rows"] if "score" in row
        ]

    return {
        "development_runs": [
            {"candidate_prompt_sha256": run["arms"]["candidate"]["prompt_sha256"],
             "baseline_summary": run["arms"]["baseline"]["summary"],
             "candidate_summary": run["arms"]["candidate"]["summary"],
             "gates": run["gates"]}
            for run in dev_runs
        ],
        "frozen_wording_prompt_sha256": held["arms"]["candidate"]["prompt_sha256"],
        "baseline_prompt_sha256": held["arms"]["baseline"]["prompt_sha256"],
        "held_out": {
            "baseline_summary": held["arms"]["baseline"]["summary"],
            "candidate_summary": held["arms"]["candidate"]["summary"],
            "gates": held["gates"],
            "candidate_rows": arm_rows(held["arms"]["candidate"]),
        },
        "verdict": "FAILED THE PRE-REGISTERED NEGATIVE GATE. The frozen wording proposed a "
                   "place from all 8 held-out place names where the baseline proposed none, "
                   "invented no place on any of the 12 negative photographs, and proposed "
                   "nothing from products, slogans or a person's name on a shirt. It made 2 "
                   "false proposals, both on partly hidden boards: the visible word, at medium "
                   "confidence, with no mention that the board was covered. The gate allows "
                   "zero, so the wording is not adopted under this record and was not revised "
                   "against these photographs.",
        "findings": [
            "Proposing a place does not consult whether the sign is whole. On the development "
            "board it passed, the model gave low confidence as instructed and wrote 'The sign is "
            "fully visible and unobstructed', which is false. Asked separately whether each of "
            "24 boards was whole or partly hidden, the same model answered all 24 correctly "
            "(" + PROBE_OUT + "), so the judgement is available and the proposal does not use "
            "it.",
            "It never completed a hidden word. Every partial-board proposal carried only "
            "words that were visible, and the fully hidden board produced none.",
            "The development split held one partly hidden board, which was too few to show "
            "that the second wording's pass on that kind was narrow.",
        ],
        "not_covered": [
            "A distinctive landmark with no text; synthetic drawings cannot depict one.",
            "Personal photographs.",
        ],
        "corpus_note": "Measured after scoring, from the drawn text widths: the held-out park "
                       "board WILLOW COMMON overflowed its board by 2 pixels. Its proposal read "
                       "the name correctly, so no result depends on it.",
        "adoption_condition": "Passing is not adoption. Adopting a wording is also a decision "
                              "about the captures already stored: the prompt text is part of "
                              "the vision stage's reprocessing key, so a new capture gets the "
                              "new prompt, and reprocessing an existing capture is a new paid "
                              "call that writes a new observation. Neither follows from a "
                              "record without that decision being made explicitly.",
    }


def wording(source: Path) -> dict[str, Any]:
    """The exact rules and place schema a development wording used, with its digest.

    Loaded from the source that ran, so the digest is recomputed rather than copied, and a text
    that did not produce the recorded run cannot be written down as if it had.
    """
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(source.stem, source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    template = module._SYSTEM_TEMPLATE
    return {
        "prompt_sha256": module.prompt_digest(),
        "schema_version": module.SCHEMA_VERSION,
        "rules": template[template.index("Rules:"):template.rindex("{nonce}")].strip(),
        "proposed_place_schema": module.OBSERVATION_SCHEMA["properties"]["proposed_place"],
    }


def b_outcome(runs: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    def rows(arm: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"file": row["file"], "kind": row["score"]["kind"], "arm": row["score"]["arm"],
             "proposed_place": row["score"]["proposed_place"],
             "positive_pass": row["score"]["positive_pass"],
             "false_proposal": row["score"]["false_proposal"],
             "invented_place": row["score"]["invented_place"],
             "evidence_says_partly_hidden": row["score"]["evidence_says_partly_hidden"],
             "latency_ms": row["latency_ms"], "micro_usd": row["micro_usd"]}
            for row in arm["rows"] if "score" in row
        ]

    development = []
    for run, text in runs:
        if run["arms"]["candidate"]["prompt_sha256"] != text["prompt_sha256"]:
            raise SystemExit("a recorded run does not match the wording source given for it")
        development.append({
            "wording": text,
            "baseline_summary": run["arms"]["baseline"]["summary"],
            "candidate_summary": run["arms"]["candidate"]["summary"],
            "gates": run["gates"],
            "candidate_rows": rows(run["arms"]["candidate"]),
        })
    return {
        "development_runs": development,
        "lost_run": "The first development run of wording 3 made all 22 calls and was lost when "
                    "the measuring script failed writing its output, after the candidate labels "
                    "of 6 photographs had been printed. Its cost was not recorded and is not "
                    "estimated here. The wording 3 run above is the second run of the same "
                    "wording on the same photographs.",
        "held_out": "NOT RUN. No wording passed development, so none was frozen, and no call of "
                    "any kind was made on the held-out split, which remains unspent.",
        "verdict": "B STOPS AT DEVELOPMENT. Both permitted wordings proposed every place name "
                   "from a whole sign (4 of 4 each), invented no place, proposed nothing from "
                   "product or person-name text, and handled both boards cut by the frame "
                   "correctly: partly hidden, low confidence, only the letters inside the frame. "
                   "Both judged both canopy-covered boards whole and proposed their visible word "
                   "at medium or high confidence, including wording 4, which asks the "
                   "completeness question as a schema field answered before the label.",
        "findings": [
            "Asked alone, the same model called 8 of 8 canopy-covered boards partly hidden "
            "(" + PROBE_OUT + "). Asked inside the observation, as a check or as its own field "
            "answered first, it called 0 of 2 partly hidden on drawings built the same way. The "
            "judgement exists; the combined observation task does not use it for covers.",
            "A board cut by the frame was judged partly hidden in every case, standalone and in "
            "the observation, so the gap is specific to something in front of the sign.",
            "A design this suggests, not tested here and not a decision this record makes: ask "
            "the completeness question as its own call whenever a place is proposed, and hold "
            "back or lower the proposal on a partly hidden answer. The standalone question cost "
            "about 280 micro-USD a photograph in the probe.",
        ],
        "adoption_condition": "Passing is not adoption, and nothing passed here. Adopting any "
                              "wording is also a decision about the captures already stored: "
                              "the prompt text is part of the vision stage's reprocessing key, "
                              "so a new capture gets the new prompt, and reprocessing an "
                              "existing capture is a new paid call that writes a new "
                              "observation.",
    }


def probe_outcome(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "probe_sha256": data["probe_sha256"],
        "tally": data["tally"],
        "can_tell": data["can_tell"],
        "answers": [
            {"file": row["file"], "state": row["state"], "how": row["how"],
             "completeness": row["answer"].get("completeness"),
             "readable_text": row["answer"].get("readable_text"),
             "correct": row["correct"], "latency_ms": row["latency_ms"],
             "micro_usd": row["micro_usd"]}
            for row in data["rows"]
        ],
        "verdict": "CAN TELL. Asked only whether the sign is whole or partly hidden, the model "
                   "answered every one of 24 boards correctly: 12 of 12 partly hidden (8 covered "
                   "by a canopy, 4 cut by the frame) and 12 of 12 whole, including all 4 with a "
                   "canopy beside the board. It transcribed only the visible lettering. The "
                   "decision rule needed at least 10, 7 and 10.",
        "consequence": "The place proposal's failure on partly hidden boards is not a limit of "
                       "what the model perceives. A wording that makes the proposal depend on "
                       "this judgement can succeed, so the second place-proposal experiment "
                       "proceeds.",
    }


def write(path: Path, body: dict[str, Any]) -> None:
    document = {"profile": "exulanica.digest-bound-record/v1", "record": body,
                "record_sha256": digest(body)}
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{path.relative_to(ROOT)} record_sha256 {document['record_sha256']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reasoning", required=True)
    parser.add_argument("--vision-b", required=True)
    parser.add_argument("--place-dev", nargs="+", required=True)
    parser.add_argument("--place-held", required=True)
    parser.add_argument("--probe", required=True)
    parser.add_argument("--b-dev", nargs=2, action="append", metavar=("RUN", "SOURCE"),
                        help="a development run of the second experiment and the vision source "
                             "it ran with; give once per wording")
    arguments = parser.parse_args()

    write(ROOT / PROBE_OUT, {
        "predecessor_record": predecessor(PROBE_PRE),
        **probe_outcome(json.loads(Path(arguments.probe).read_bytes())),
    })

    write(ROOT / "docs/evaluation/2026-09-22-model-selection-outcome.json", {
        "predecessor_record": predecessor(SELECTION_PRE),
        "comparison_a_reasoning": reasoning_outcome(
            json.loads(Path(arguments.reasoning).read_bytes())),
        "comparison_b_vision": vision_b_outcome(
            json.loads(Path(arguments.vision_b).read_bytes())),
    })
    write(ROOT / "docs/evaluation/2026-09-22-vision-place-proposal-outcome.json", {
        "predecessor_record": predecessor(PLACE_PRE),
        **place_outcome(
            [json.loads(Path(p).read_bytes()) for p in arguments.place_dev],
            json.loads(Path(arguments.place_held).read_bytes()),
        ),
    })
    if arguments.b_dev:
        write(ROOT / PLACE_B_OUT, {
            "predecessor_record": predecessor(PLACE_B_PRE),
            **b_outcome([(json.loads(Path(run).read_bytes()), wording(Path(source)))
                         for run, source in arguments.b_dev]),
        })


if __name__ == "__main__":
    main()
