"""Freeze the fourth place-proposal experiment before any call is made on its photographs.

    python scripts/write_place_proposal_d_preregistration.py \
        --development DEV_DIR --held-out HELD_DIR --base-commit SHA

The third experiment asked a separate completeness question whenever the observation proposed a
place and lowered a partly hidden sign's proposal to low confidence. It caught every partly hidden
board and still failed its held-out gate, because the observation had already written a word into
a label that no sign in the frame carries. This experiment measures the design that failure
suggested: the vision model proposes, and a written policy decides. The label keeps only words the
observation transcribed from signage, and the proposal is refused whenever the separate
completeness question finds its sign partly hidden or finds a different sign.

The gate is stricter than the earlier ones on purpose. They allowed a low-confidence proposal of a
partly hidden board's visible words; here any written proposal on a negative photograph is a false
proposal, and so is a proposal on a positive photograph whose label is not exactly the place name.

The photographs, their ground truth, the generator and the candidate's source are bound by
SHA-256. No float appears in the record: ``exulanica.canonical.canonical_json`` refuses them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import exulanica.ingest.vision as candidate_vision
from exulanica.canonical import canonical_json
from exulanica.ingest.place_proposal import PLACE_PROPOSAL_POLICY
from write_place_proposal_preregistration import STOPWORDS, baseline_prompt_digest, corpus

ROOT = Path(__file__).resolve().parents[1]
OUT = "docs/evaluation/2026-09-23-vision-place-proposal-d-preregistration.json"
C_OUTCOME = "docs/evaluation/2026-09-22-vision-place-proposal-c-outcome.json"
PROBE_OUTCOME = "docs/evaluation/2026-09-22-sign-completeness-probe-outcome.json"
FIRST_OUTCOME = "docs/evaluation/2026-09-22-vision-place-proposal-outcome.json"
BOUND_SOURCES = (
    "exulanica/ingest/place_proposal.py",
    "exulanica/ingest/vision.py",
    "exulanica/ingest/stages/vision.py",
    "scripts/make_place_proposal_d_photographs.py",
    "scripts/measure_place_proposal_d.py",
)


def binding(path: str) -> dict[str, str]:
    record = json.loads((ROOT / path).read_bytes())["record"]
    return {"path": path, "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest()}


def split(directory: Path, use: str) -> dict:
    truth_files = sorted(directory.glob("ground-truth-*.json"))
    return {"use": use, "ground_truth_file": truth_files[0].name, **corpus(directory)}


def minimum(of: int) -> int:
    """Three quarters of the positive photographs, rounded up, as in every earlier experiment."""
    return -(-3 * of // 4)


def record(development: Path, held_out: Path, base_commit: str) -> dict:
    dev = split(
        development,
        "run once by both arms with the design as registered. The design may be revised once, "
        "only to correct a defect that run shows, and the revision is run on this split again "
        "before the held-out split. A design that fails a development gate ends the experiment "
        "without a held-out run.",
    )
    held = split(
        held_out,
        "scored once by both arms, with the design frozen at the end of development. A failure "
        "is recorded as a failure, and nothing is revised against these photographs.",
    )
    first = json.loads((ROOT / FIRST_OUTCOME).read_bytes())["record"]
    policy = PLACE_PROPOSAL_POLICY
    return {
        "profile_note": "Pre-registration of the fourth place-proposal experiment. Written before "
        "any call was made on either split below, by either arm.",
        "question": "Does a place proposal made by the vision role and decided by the written "
        "place proposal policy name the place from a whole legible place name, without ever "
        "writing a place the photograph does not show?",
        "predecessor_records": [binding(C_OUTCOME), binding(PROBE_OUTCOME)],
        "premise": [
            "The third experiment's one held-out failure was a label word the observation wrote "
            "('Ashcombe (partial)'), not a completeness judgement; its completeness question "
            "judged every partly hidden board partly hidden.",
            "Asked inside the observation, as an instruction or as a schema field answered "
            "first, the model judged boards with a tree in front of them whole (the second "
            "experiment); asked alone it judged 24 of 24 probe boards correctly. So the "
            "completeness judgement is a second call, as the third experiment asked it.",
            "A rule written in code bounds whatever the observation writes: it can only remove.",
        ],
        "already_seen_before_this_was_written": [
            "Every result of the first three experiments and of the probe, bound above or by "
            "their own records. All their splits are spent and none is used here.",
            "Contact sheets of both splits below, drawings only. One drawing fault was corrected "
            "before this record: the street blade position inherited from the earlier corpus put "
            "a blade's left edge outside the frame at some indices (6 pixels at held-out index "
            "8), so every whole sign is now drawn at least 24 pixels inside the frame and the "
            "generator refuses a drawing that is not. No model output of any kind exists for "
            "either split.",
            "The candidate's automated tests, which script every model reply and make no call.",
        ],
        "base_commit": base_commit,
        "baseline": {
            "what": "exulanica/ingest/vision.py at the base commit, which proposes a place as the "
            "tail of a prohibition and decides nothing about it",
            "prompt_sha256": baseline_prompt_digest(base_commit),
        },
        "candidate": {
            "prompt_sha256_at_registration": candidate_vision.prompt_digest(),
            "place_proposal_policy": {
                "policy_id": policy.policy_id,
                "version": policy.version,
                "sha256": policy.digest(),
                "record": policy.as_record(),
            },
            "source_sha256_at_registration": {
                path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                for path in BOUND_SOURCES
            },
            "observation": "the first experiment's frozen wording, byte-identical: its digest over "
            "system text, user text and schema is "
            f"{first['frozen_wording_prompt_sha256']}. The candidate's digest also covers the "
            "schema's name and the policy.",
            "decision": [
                "1. The observation call, exactly as production makes it.",
                "2. The label rule: " + policy.label_source + ". A label left with no word "
                "refuses the proposal and no second call is made.",
                "3. The sign question, only when a word survives: the probe's system text, "
                "question and schema, word for word, in a separate call on the same image.",
                "4. The proposal is written only when the answer comes from an admitted judge, "
                "says a sign is present and whole, and " + policy.pairing + ". Every other case is "
                "a named refusal in the policy.",
                "5. A sign question that fails withholds the proposal and keeps the rest of the "
                "observation; the photograph does not fail.",
                "6. The stored observation keeps the model's reply verbatim, with the decision "
                "and the policy digest beside it.",
            ],
            "revisions_allowed_on_development": 1,
        },
        "model": {
            "role": "vision",
            "model_id": "MiniMaxAI/MiniMax-M3",
            "fallback": "disabled for both arms, on an in-memory copy of the manifest, so a "
            "provider failure is recorded as a failure rather than answered by another model in "
            "one arm only. The policy refuses a sign judgement from any model it has not "
            "admitted, and that refusal is tested with scripted replies, not measured here.",
            "calls_per_photograph": "baseline one; candidate one, or two when a label survives",
            "call": "NebiusVisionModel.observe from each arm's own module: its messages, schema, "
            "temperature 0 and no response cache",
            "determinism": "not claimed. Temperature 0 on a serverless endpoint does not promise "
            "identical output, which is one reason every threshold is in whole photographs.",
        },
        "input": "the rendition production sends: exulanica.ingest.derivatives.render over the "
        "upright image with the registry's rendition parameters. Both arms receive the same bytes.",
        "corpus": {
            "drawn_by": "scripts/make_place_proposal_d_photographs.py",
            "new_words": "no word of any text drawn in either split appears in any split drawn "
            "for the earlier experiments, or in the other split; the generator refuses otherwise. "
            "The notice every scene carries at its bottom edge is the exception.",
        },
        "splits": {"development": dev, "held_out": held},
        "definitions": {
            "ignored_words": list(STOPWORDS),
            "words": "upper-cased, split at every character that is not A to Z, the ignored words "
            "removed, compared as sets",
            "scored": "the observation each arm's stage writes from: the candidate's after the "
            "policy's decision, the baseline's validated payload",
            "positive_pass": "on a positive photograph, a proposal is written and its label's "
            "words are exactly the drawn place name's words",
            "false_proposal": "on a negative photograph, any written proposal at any confidence; "
            "on a positive photograph, a written proposal whose label's words are not exactly the "
            "place name's words, whether a word is added, missing or misread",
            "invented_place": "the false proposals whose label carries a word no text in the frame "
            "shows, a covered or cut-away word counting as not shown, and any proposal on a "
            "no_text photograph. Reported beside the gate, never instead of it.",
            "text_transcribed": "on a photograph showing whole words (a whole visible word of the "
            "place board, or any word of other text), every such word is among the words of "
            "legible_text",
            "negative_kinds": "covered_last, covered_first, covered_middle, hidden, cut, "
            "two_signs_cut and two_signs_covered carry a place board that is not whole; no_text, "
            "product, slogan and person_name carry no place name at all",
            "two_signs": "a whole place name on a street blade, with a whole banner carrying a "
            "slogan on the building behind it; positive, and counted in the recall target",
        },
        "gates": {
            "order": "the no-false-proposal gate is checked first and a failure there ends the "
            "evaluation as a failure; the positive number is then reported and cannot rescue it",
            "negative": {
                "max_false_proposals": 0,
                "over": "every photograph of the split, positive and negative",
                "why_zero": "an invented or wrong place becomes a memory entity a person is asked "
                "to confirm, and it is the failure a person is least able to notice, so none is "
                "traded for recall. Zero in a split of this size is a gate, not an estimate of "
                "a rate: it bounds the true rate only loosely.",
            },
            "positive": {
                "rule": "three quarters of the positive photographs, rounded up, as in every "
                "earlier experiment",
                "development_min_pass": minimum(dev["positive"]),
                "development_of": dev["positive"],
                "held_out_min_pass": minimum(held["positive"]),
                "held_out_of": held["positive"],
            },
            "regression_against_baseline_same_run": [
                "photographs with their words transcribed: candidate at least baseline minus 1",
                "person_name photographs with at least one person trace: candidate at least "
                "baseline",
                "person traces reported on photographs where no person was drawn: candidate at "
                "most baseline",
            ],
            "latency_ms": {"per_photograph_p95_max": 30000},
            "latency_note": "per photograph, both calls together when there are two",
            "cost": "the candidate's total at most twice the baseline's, from the provider's "
            "reported usage as the client's budget records it",
            "calls": "no observation call and no sign question fails in the candidate arm",
        },
        "adoption_condition": "Passing is the condition for adopting the design in "
        "exulanica/ingest/vision.py, not the adoption. Adopting it moves the vision stage's "
        "reprocessing key: a new capture is observed under the new design, and reprocessing an "
        "existing capture is a new paid call that writes a new observation. This record decides "
        "nothing about existing captures.",
        "not_covered": [
            "A landmark with no legible name. The policy refuses every such proposal by "
            "construction, because no sign reads it.",
            "Personal photographs and real photographs. Automated work uses synthetic drawings.",
            "Any model other than the vision primary.",
            "Signage in other languages or scripts, and a name transcribed as two entries, which "
            "the label rule joins but this corpus does not draw.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--development", required=True)
    parser.add_argument("--held-out", required=True)
    parser.add_argument("--base-commit", required=True)
    arguments = parser.parse_args()
    body = record(Path(arguments.development), Path(arguments.held_out), arguments.base_commit)
    document = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": body,
        "record_sha256": hashlib.sha256(canonical_json(body)).hexdigest(),
    }
    (ROOT / OUT).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{OUT} record_sha256 {document['record_sha256']}")


if __name__ == "__main__":
    main()
