"""Write the fourth place-proposal experiment's outcome record, bound to its pre-registration.

    python scripts/write_place_proposal_d_outcome.py \
        --development RUN.json --development-photos DIR --held-out RUN.json --held-out-photos DIR

The numbers are read from the two runs ``measure_place_proposal_d.py`` wrote. The writer refuses
unless each run was made under the pre-registration it names, with the candidate prompt digest and
policy digest that record registered, and on the photographs it binds.

Beside the scored runs it derives three counterfactuals from the recorded replies, without a model
call: what would have been written with no policy (the observation's own proposal), with the
label rule alone (no sign question), and with every check except the pairing of the judged sign
to the name. They are computed from the recorded outcome codes and the policy's own label rule,
never from a second copy of the rule, and they are scored by the same function as the runs. The
pairing counterfactual rests on one fact about the policy: pairing is the last check ``decide``
applies, so a proposal it refused had passed every other check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exulanica.canonical import canonical_json
from exulanica.ingest.place_proposal import (
    JUDGED_SIGN_DOES_NOT_CARRY_THE_NAME,
    NO_WORD_READ_FROM_A_SIGN,
    NOTHING_PROPOSED,
    SIGN_PARTLY_HIDDEN,
    WRITTEN,
    read_label,
)
from measure_place_proposal import micro_usd
from measure_place_proposal_d import score

ROOT = Path(__file__).resolve().parents[1]
PRE = "docs/evaluation/2026-09-23-vision-place-proposal-d-preregistration.json"
OUT = "docs/evaluation/2026-09-23-vision-place-proposal-d-outcome.json"
SELECTION_OUTCOME = "docs/evaluation/2026-09-22-model-selection-outcome.json"


def _checked(run: dict[str, Any], pre_document: dict[str, Any], split: str) -> None:
    candidate = pre_document["record"]["candidate"]
    if run["preregistration_record_sha256"] != pre_document["record_sha256"]:
        raise SystemExit(f"the {split} run names another pre-registration")
    if run["split"] != split:
        raise SystemExit(f"the {split} file holds the {run['split']} split")
    if run["arms"]["candidate"]["prompt_sha256"] != candidate["prompt_sha256_at_registration"]:
        raise SystemExit(f"the {split} run's candidate is not the registered design")
    if run["place_proposal_policy_sha256"] != candidate["place_proposal_policy"]["sha256"]:
        raise SystemExit(f"the {split} run's policy is not the registered policy")


def _truths(directory: Path, bound: dict[str, Any]) -> list[dict[str, Any]]:
    truth_file = directory / bound["ground_truth_file"]
    if hashlib.sha256(truth_file.read_bytes()).hexdigest() != bound["ground_truth_sha256"]:
        raise SystemExit(f"{directory} is not the corpus the pre-registration binds")
    return json.loads(truth_file.read_bytes())


def _rows(run: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in run["arms"]["candidate"]["rows"]:
        check = row.get("place_check") or {}
        judged = check.get("sign_judgement")
        proposal = row["payload"].get("proposed_place")
        rows.append(
            {
                "file": row["file"],
                "kind": row["score"]["kind"],
                "arm": row["score"]["arm"],
                "proposed_label": proposal["label"] if proposal else None,
                "proposed_confidence": proposal["confidence"] if proposal else None,
                "outcome": check.get("outcome"),
                "written_label": check.get("written_label"),
                "dropped_words": check.get("dropped_words", []),
                "sign_judgement": (
                    {
                        "completeness": judged["completeness"],
                        "readable_text": judged["readable_text"],
                    }
                    if judged
                    else None
                ),
                "positive_pass": row["score"]["positive_pass"],
                "false_proposal": row["score"]["false_proposal"],
                "invented_place": row["score"]["invented_place"],
                "calls": row["calls"],
                "latency_ms": row["latency_ms"],
                "micro_usd": row["micro_usd"],
            }
        )
    return rows


def _counterfactual(
    run: dict[str, Any], truths: list[dict[str, Any]], ignored: frozenset[str], variant: str
) -> dict[str, Any]:
    tallies = {"positive_pass": 0, "false_proposals": 0, "invented_places": 0}
    differs = []
    for row, truth in zip(run["arms"]["candidate"]["rows"], truths, strict=True):
        payload, check = row["payload"], row.get("place_check") or {}
        proposal = payload.get("proposed_place")
        signs = [entry["text"] for entry in payload["legible_text"] if entry["is_signage"]]
        reading = read_label(proposal["label"], signs) if proposal else None
        written = row["scored"].get("proposed_place")
        if variant == "observation_alone":
            written = proposal
        elif variant == "label_rule_alone":
            written = {**proposal, "label": reading.label} if reading and reading.label else None
        elif variant == "without_pairing":
            if check.get("outcome") == JUDGED_SIGN_DOES_NOT_CARRY_THE_NAME.code:
                written = {**proposal, "label": reading.label}
        else:
            raise ValueError(f"no counterfactual named {variant!r}")
        scored = score(truth, {**row["scored"], "proposed_place": written}, ignored)
        tallies["positive_pass"] += bool(scored["positive_pass"])
        tallies["false_proposals"] += scored["false_proposal"]
        tallies["invented_places"] += scored["invented_place"]
        if (written or {}).get("label") != check.get("written_label"):
            differs.append(
                {
                    "file": row["file"],
                    "written_label": (written or {}).get("label"),
                    "positive_pass": scored["positive_pass"],
                    "false_proposal": scored["false_proposal"],
                }
            )
    return {**tallies, "photographs_that_differ_from_the_run": differs}


def _split(
    run: dict[str, Any], truths: list[dict[str, Any]], ignored: frozenset[str]
) -> dict[str, Any]:
    candidate_rows = run["arms"]["candidate"]["rows"]
    sign_usd = sum(
        micro_usd(Decimal(row["place_check"]["sign_usage"]["usd_estimate"]))
        for row in candidate_rows
        if (row.get("place_check") or {}).get("sign_usage")
    )
    return {
        "baseline_prompt_sha256": run["arms"]["baseline"]["prompt_sha256"],
        "candidate_prompt_sha256": run["arms"]["candidate"]["prompt_sha256"],
        "baseline_summary": run["arms"]["baseline"]["summary"],
        "candidate_summary": run["arms"]["candidate"]["summary"],
        "gates": run["gates"],
        "candidate_rows": _rows(run),
        "sign_question_micro_usd_from_reported_usage": sign_usd,
        "counterfactuals_on_recorded_replies": {
            variant: _counterfactual(run, truths, ignored, variant)
            for variant in ("observation_alone", "label_rule_alone", "without_pairing")
        },
    }


def _fallback_labels() -> dict[str, Any]:
    """The three generic places the fallback proposed on unsigned photographs, under the rule."""
    comparison = json.loads((ROOT / SELECTION_OUTCOME).read_bytes())["record"]
    proposals = comparison["comparison_b_vision"]["candidate_unsigned_place_proposals"]
    # The most any observation of those frames could have transcribed as signage: every text
    # drawn in them, which on an unsigned photograph of that corpus is its bottom-edge notice.
    drawn = ["SYNTHETIC TEST IMAGE"]
    return {
        "source": SELECTION_OUTCOME,
        "assumed_signage": "every text drawn in those frames, transcribed as signage: the "
        "bottom-edge notice. The record holds no transcription, so a sign the fallback "
        "invented is not covered.",
        "labels": [
            {
                "file": item["file"],
                "label": item["proposed_place"]["label"],
                "written_label": read_label(item["proposed_place"]["label"], drawn).label,
            }
            for item in proposals
        ],
    }


def _findings(splits: dict[str, dict[str, Any]]) -> list[str]:
    """The findings, each computed from the rows and refused if the rows do not bear it out."""
    held, dev = splits["held_out"], splits["development"]
    rows = held["candidate_rows"]
    misses = [r for r in rows if r["arm"] == "positive" and not r["positive_pass"]]
    by_pairing = [r for r in misses if r["outcome"] == JUDGED_SIGN_DOES_NOT_CARRY_THE_NAME.code]
    banner = [r for r in by_pairing if r["kind"] == "two_signs"]
    misread = [r for r in by_pairing if r["kind"] != "two_signs"]
    if len(by_pairing) != len(misses) or len(misread) != 1:
        raise SystemExit("the held-out misses are not the ones these findings describe")
    (read_wrong,) = misread
    judged_as = read_wrong["sign_judgement"]["readable_text"]
    if read_wrong["proposed_label"].upper() == judged_as.upper():
        raise SystemExit("the misread finding does not hold on these rows")

    refused_by_rule = [r for r in rows if r["outcome"] == NO_WORD_READ_FROM_A_SIGN.code]
    dropped = [
        r
        for r in rows + dev["candidate_rows"]
        if r["dropped_words"] and r["outcome"] != NO_WORD_READ_FROM_A_SIGN.code
    ]
    if any(r["outcome"] == WRITTEN.code for r in dropped):
        raise SystemExit("a label that lost words was written; the finding below does not hold")
    proposing_negatives = {
        name: [
            r
            for r in body["candidate_rows"]
            if r["arm"] == "negative"
            and r["outcome"] not in (NOTHING_PROPOSED.code, NO_WORD_READ_FROM_A_SIGN.code)
        ]
        for name, body in splits.items()
    }
    for name, judged in proposing_negatives.items():
        if any(r["outcome"] != SIGN_PARTLY_HIDDEN.code for r in judged):
            raise SystemExit(f"a {name} negative was refused by something other than the judgement")
    silent = sorted(
        {
            r["kind"]
            for r in rows
            if r["arm"] == "negative" and r["outcome"] == NOTHING_PROPOSED.code
        }
    )
    text_gap = (
        held["baseline_summary"]["text_transcribed"] - held["candidate_summary"]["text_transcribed"]
    )
    return [
        f"Of {len(misses)} held-out misses, {len(banner)} are scenes with a slogan banner behind "
        "the street blade, where the sign question judged the banner, the most prominent sign, "
        "and the pairing check refused the name it did not read. The other is a nameplate the "
        f"observation read as '{read_wrong['proposed_label']}', in its transcription and its "
        f"label, where the sign question read '{judged_as}'. The pairing check refused it "
        "because the judged sign does not carry every word of the label. Without that check the "
        "misread name is written, and the no-false-proposal gate allows none "
        "(counterfactuals_on_recorded_replies.without_pairing).",
        f"The label rule refused {len(refused_by_rule)} held-out proposal outright, "
        + ", ".join(f"'{r['proposed_label']}' ({r['kind']})" for r in refused_by_rule)
        + ". Across both splits it removed words no transcription carries from "
        + "; ".join(f"'{r['proposed_label']}' ({', '.join(r['dropped_words'])})" for r in dropped)
        + ". The sign question then refused each of those.",
        "The sign question judged partly hidden every negative on which the observation's "
        f"proposal survived the label rule: {len(proposing_negatives['held_out'])} on the "
        f"held-out split and {len(proposing_negatives['development'])} on development. No "
        "refusal came from a failed call.",
        "The observation proposed no place on these held-out negative kinds: "
        + ", ".join(silent)
        + ".",
        f"The candidate transcribed {text_gap} held-out photograph's text worse than the "
        "baseline, the misread above. The gate allows one.",
    ]


def _verdict(held: dict[str, Any], pre: dict[str, Any]) -> str:
    """The verdict, read from the gates the run computed, never written ahead of them."""
    cand, base = held["candidate_summary"], held["baseline_summary"]
    photographs = cand["photographs"]
    minimum = pre["gates"]["positive"]["held_out_min_pass"]
    if not held["gates"]["all_pass"]:
        failed = sorted(name for name, ok in held["gates"]["checks"].items() if not ok)
        return (
            f"FAILED the pre-registered held-out gates {', '.join(failed)}, scored once. "
            f"{cand['false_proposals']} false proposals in {photographs} photographs; "
            f"{cand['positive_pass']} of {cand['positive_of']} place names written exactly."
        )
    return (
        "PASSED every pre-registered gate on the held-out split, scored once. "
        f"{cand['false_proposals']} of {photographs} photographs received a written proposal it "
        f"should not have: none of the {cand['negative_of']} negatives, and no wrong name on a "
        f"positive. {cand['positive_pass']} of {cand['positive_of']} whole place names were "
        f"written exactly, against a registered minimum of {minimum}. The baseline wrote "
        f"{base['positive_pass']} of the {base['positive_of']}."
    )


def record(runs: dict[str, dict[str, Any]], photos: dict[str, Path]) -> dict[str, Any]:
    pre_document = json.loads((ROOT / PRE).read_bytes())
    pre = pre_document["record"]
    ignored = frozenset(pre["definitions"]["ignored_words"])
    splits = {}
    for split, run in runs.items():
        _checked(run, pre_document, split)
        splits[split] = _split(run, _truths(photos[split], pre["splits"][split]), ignored)
    held = splits["held_out"]
    cost = {
        split: {
            "baseline": body["baseline_summary"]["micro_usd_total"],
            "candidate": body["candidate_summary"]["micro_usd_total"],
            "candidate_sign_questions": body["sign_question_micro_usd_from_reported_usage"],
        }
        for split, body in splits.items()
    }
    return {
        "predecessor_record": {"path": PRE, "record_sha256": pre_document["record_sha256"]},
        "design_as_run": {
            "candidate_prompt_sha256": held["candidate_prompt_sha256"],
            "place_proposal_policy_sha256": runs["held_out"]["place_proposal_policy_sha256"],
            "matches_registration": True,
            "revisions_on_development": [],
            "why_no_revision": "the development run passed every gate and showed no defect: "
            "every check refused what it exists to refuse",
        },
        "development": splits["development"],
        "held_out": held,
        "fallback_generic_labels_under_the_label_rule": _fallback_labels(),
        "cost_micro_usd": {
            **cost,
            "total": sum(c["baseline"] + c["candidate"] for c in cost.values()),
        },
        "verdict": _verdict(held, pre),
        "findings": _findings(splits),
        "adoption": "Adopted in exulanica/ingest/vision.py for every photograph observed after "
        "this change. The vision stage's reprocessing key moves with it. A derivative job is "
        "queued only by intake, personal admission and reference admission, so no stored "
        "observation is re-run by the change itself; re-admitting an existing capture is a new "
        "paid call per photograph that writes a new observation, and is a separate decision.",
        "not_established": [
            "Recall on real photographs, where a place name often shares the frame with other "
            "signs: every scene here with a more prominent second sign lost its place name.",
            "Any rate. Zero false proposals in 44 photographs bounds the true rate loosely, and "
            "the photographs are synthetic drawings of one style.",
            "The fallback model's sign judgement, which the policy refuses by name and which "
            "was never exercised: the fallback was disabled in both arms.",
            "Landmarks, signage in other languages or scripts, and names split across two "
            "transcriptions.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--development", required=True)
    parser.add_argument("--development-photos", required=True)
    parser.add_argument("--held-out", required=True)
    parser.add_argument("--held-out-photos", required=True)
    arguments = parser.parse_args()
    runs = {
        "development": json.loads(Path(arguments.development).read_bytes()),
        "held_out": json.loads(Path(arguments.held_out).read_bytes()),
    }
    photos = {
        "development": Path(arguments.development_photos),
        "held_out": Path(arguments.held_out_photos),
    }
    body = record(runs, photos)
    document = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": body,
        "record_sha256": hashlib.sha256(canonical_json(body)).hexdigest(),
    }
    (ROOT / OUT).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{OUT} record_sha256 {document['record_sha256']}")


if __name__ == "__main__":
    main()
