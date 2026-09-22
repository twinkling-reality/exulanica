"""Freeze the second place-proposal experiment before any call is made on its photographs.

    python scripts/write_place_proposal_b_preregistration.py OUT.json \
        --development DEV_DIR --held-out HELD_DIR --base-commit SHA

The first experiment's frozen wording proposed a place from every legible place name and invented
none, and failed on partly hidden boards, proposing the visible word at medium confidence. A
perception probe then showed the model separates whole boards from partly hidden ones perfectly
when asked that alone. So the defect is the proposal not consulting a judgement the model can
make, and this experiment asks whether a wording that makes the proposal depend on it passes.

The gates are the first experiment's, unchanged, so the two results can be read side by side. The
splits are new, with every name unseen, and carry several partly hidden boards so the failure
that mattered is represented where it is judged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exulanica.canonical import canonical_json
from write_place_proposal_preregistration import (
    STOPWORDS,
    baseline_prompt_digest,
    corpus,
)

ROOT = Path(__file__).resolve().parents[1]
FIRST_OUTCOME = "docs/evaluation/2026-09-22-vision-place-proposal-outcome.json"
PROBE = "docs/evaluation/2026-09-22-sign-completeness-probe-outcome.json"


def binding(path: str) -> dict[str, str]:
    record = json.loads((ROOT / path).read_bytes())["record"]
    return {"path": path, "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest()}


def record(development: Path, held_out: Path, base_commit: str) -> dict:
    first = json.loads((ROOT / "docs/evaluation/2026-09-22-vision-place-proposal-preregistration"
                        ".json").read_bytes())["record"]
    return {
        "predecessor_records": [binding(FIRST_OUTCOME), binding(PROBE)],
        "profile_note": "Pre-registration of the second place-proposal experiment. Written before "
                        "any call was made on either split below, by any prompt.",
        "question": first["question"],
        "premise": "The perception probe bound above found the model calls 12 of 12 partly "
                    "hidden boards partly hidden and 12 of 12 whole boards whole when asked that "
                    "alone. The first experiment's failures were proposals that did not consult "
                    "that judgement.",
        "already_seen_before_this_was_written": [
            "Every result of the first experiment, bound above: its development runs, and its "
            "held-out split, which is spent and is not used here.",
            "The perception probe's answers, bound above.",
            "The drawings of both splits below, as contact sheets. Three drawing faults were "
            "corrected before this was written: two names overflowed their boards, one product "
            "name ran onto the drawn bottle, and a frame-cut board's visible words excluded a "
            "letter half inside the frame. No model output of any kind exists for either split.",
        ],
        "base_commit": base_commit,
        "baseline": {"prompt": "exulanica/ingest/vision.py at the base commit",
                     "prompt_sha256": baseline_prompt_digest(base_commit)},
        "candidate": {
            "prompt": "exulanica/ingest/vision.py in this lane's worktree; each run records the "
                      "prompt_sha256 it used",
            "must_keep": first["candidate"]["must_keep"],
            "must_add": "the proposal depends on the model's own judgement of whether the sign "
                        "carrying the name is whole or partly hidden, made first",
            "wordings_allowed_on_development": 2,
            "order": "the first wording changes the prompt only and leaves the schema's shape "
                     "alone. A second wording is tried only if the first fails a development "
                     "gate, and it may add an explicit completeness field to the observation "
                     "schema, which is a schema version change and is stated as one.",
        },
        "model": first["model"],
        "input": first["input"],
        "splits": {
            "development": {
                "use": "wording may be revised here, at most twice. The first wording that "
                       "passes every development gate is frozen and is the only one the "
                       "held-out split sees.",
                **corpus(development),
            },
            "held_out": {
                "use": "scored once per arm with the frozen wording. A failure is reported as a "
                       "failure and no wording is revised against these photographs.",
                **corpus(held_out),
            },
        },
        "definitions": {
            **first["definitions"],
            "words": "as before; these words are ignored: " + ", ".join(STOPWORDS),
            "partial_kinds": "partial (a board partly covered) and partial_cut (a board running "
                             "past the frame) are both partly hidden boards and are scored alike",
            "visible_words_of_a_cut_board": "every whole word inside the frame, and every prefix "
                                            "of the final fragment, a letter counting once any "
                                            "part of it is inside the frame",
            "evidence_says_partly_hidden": "reported for each proposal from a partly hidden "
                                           "board, never gating: whether its supporting evidence "
                                           "says the sign is hidden, covered, obscured or cut "
                                           "off",
        },
        "gates": {
            **first["gates"],
            "positive": {"development_min_pass": 3, "development_of": 4,
                         "held_out_min_pass": 6, "held_out_of": 8},
            "unchanged_from_the_first_experiment": "every threshold, so the two results read "
                                                   "side by side",
        },
        "adoption_condition": "Passing is not adoption. Adopting a wording is also a decision "
                              "about the captures already stored: the prompt text is part of "
                              "the vision stage's reprocessing key, so a new capture gets the "
                              "new prompt, and reprocessing an existing capture is a new paid "
                              "call that writes a new observation. Neither follows from this "
                              "record without that decision being made explicitly.",
        "not_covered": first["not_covered"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--development", required=True)
    parser.add_argument("--held-out", required=True)
    parser.add_argument("--base-commit", required=True)
    arguments = parser.parse_args()
    body = record(Path(arguments.development), Path(arguments.held_out), arguments.base_commit)
    document = {"profile": "exulanica.digest-bound-record/v1", "record": body,
                "record_sha256": hashlib.sha256(canonical_json(body)).hexdigest()}
    Path(arguments.out).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{arguments.out} record_sha256 {document['record_sha256']}")


if __name__ == "__main__":
    main()
