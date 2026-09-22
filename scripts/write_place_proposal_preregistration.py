"""Freeze how a vision prompt change is judged, before any candidate call is made.

    python scripts/write_place_proposal_preregistration.py OUT.json \
        --development DEV_DIR --held-out HELD_DIR --base-commit SHA

The question is whether a rewritten vision prompt makes the model propose a place when a legible
place name is in the photograph, WITHOUT making it propose places the photograph does not show.
The second half is the one that gates. A prompt that lifts the positive rate by inventing places
has made the product worse whatever the positive number says, because an invented place becomes a
memory entity a person is then invited to confirm.

The corpus is bound by the SHA-256 of every photograph and of its ground truth, read from the two
directories ``scripts/make_place_signage_photographs.py`` wrote. A corpus redrawn after a
candidate had been looked at would move those digests.

No float appears in the record: ``exulanica.canonical.canonical_json`` refuses them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from exulanica.canonical import canonical_json

STOPWORDS = ["A", "AN", "AND", "AT", "OF", "THE"]


def corpus(directory: Path) -> dict:
    truth_files = sorted(directory.glob("ground-truth-*.json"))
    if len(truth_files) != 1:
        raise SystemExit(f"{directory} must hold exactly one ground-truth file")
    truths = json.loads(truth_files[0].read_bytes())
    return {
        "ground_truth_sha256": hashlib.sha256(truth_files[0].read_bytes()).hexdigest(),
        "photographs": [
            {
                "file": entry["file"],
                "kind": entry["kind"],
                "arm": entry["arm"],
                "sha256": hashlib.sha256((directory / entry["file"]).read_bytes()).hexdigest(),
            }
            for entry in truths
        ],
        "positive": sum(1 for entry in truths if entry["arm"] == "positive"),
        "negative": sum(1 for entry in truths if entry["arm"] == "negative"),
    }


def baseline_prompt_digest(base_commit: str) -> str:
    """The digest of the prompt as it stands at the base commit, computed from that file's text."""
    source = subprocess.run(
        ["git", "show", f"{base_commit}:exulanica/ingest/vision.py"],
        check=True, capture_output=True, text=True,
    ).stdout
    namespace: dict = {}
    # Only the two string constants the digest is defined over are needed. Executing the whole
    # module from another commit would import this tree's dependencies under that commit's code.
    start = source.index("_SYSTEM_TEMPLATE: Final = ")
    end = source.index("def prompt_digest")
    exec("from typing import Final\n" + source[start:end], namespace)
    return hashlib.sha256(
        (namespace["_SYSTEM_TEMPLATE"] + namespace["_USER_TEXT"]).encode("utf-8")
    ).hexdigest()


def record(development: Path, held_out: Path, base_commit: str) -> dict:
    return {
        "profile_note": "Pre-registration for a change to the vision prompt. Written before any "
                        "call was made on either split below, by any prompt.",
        "question": "Does the rewritten prompt make the vision role propose a place from a "
                    "legible place name, without proposing places the photograph does not show?",
        "already_seen_before_this_was_written": [
            "The production prompt's outputs on an earlier corpus (make_place_photographs.py): "
            "8 of 8 boards transcribed, 0 of 8 places proposed.",
            "One diagnostic call, on that earlier corpus's development-01 only, with the "
            "production prompt plus one sentence; it proposed the board's name at high "
            "confidence. That sentence is not the candidate wording, and that photograph is in "
            "neither split below.",
            "The drawings of both splits below, viewed as contact sheets to confirm they render "
            "as intended. No model output of any kind exists for either split.",
        ],
        "base_commit": base_commit,
        "baseline": {
            "prompt": "exulanica/ingest/vision.py as it stands at the base commit",
            "prompt_sha256": baseline_prompt_digest(base_commit),
        },
        "candidate": {
            "prompt": "exulanica/ingest/vision.py in this lane's worktree. Each run records the "
                      "prompt_sha256 it was made with, so every result is attributable to one "
                      "wording.",
            "must_keep": [
                "no date, time or location stated as fact",
                "no person's name, and no proposal of who someone is",
                "no identity of any kind",
                "a proposed place is framed as a proposal for a human to confirm",
                "every person trace reported, including partial ones",
            ],
        },
        "model": {
            "role": "vision",
            "model_id": "MiniMaxAI/MiniMax-M3",
            "fallback": "disabled for both arms, on an in-memory copy of the manifest, so a "
                        "provider failure is recorded as a failure rather than silently "
                        "answered by a different model in one arm and not the other",
            "call": "NebiusVisionModel.observe from each arm's own module, which is the exact "
                    "production call: its messages, its schema, temperature 0, no response "
                    "cache",
            "calls_per_photograph_per_arm": 1,
            "determinism": "not claimed. Temperature 0 on a serverless endpoint is not a "
                           "guarantee of identical output, which is one reason the thresholds "
                           "below are stated in whole photographs.",
        },
        "input": "the rendition production sends: exulanica.ingest.derivatives.render over the "
                 "upright image with the registry's rendition parameters. Both arms receive "
                 "the same bytes.",
        "splits": {
            "development": {
                "use": "wording may be revised here. At most 3 candidate wordings. The first "
                       "that passes every development gate is frozen and is the only wording "
                       "the held-out split ever sees.",
                **corpus(development),
            },
            "held_out": {
                "use": "scored once per arm, with the frozen wording. If the held-out gates "
                       "fail, the result is reported as a failure and no wording is revised "
                       "against these photographs.",
                **corpus(held_out),
            },
        },
        "definitions": {
            "words": "a label or a drawn text is upper-cased and split on anything that is not "
                     "a letter; these words are ignored: " + ", ".join(STOPWORDS),
            "positive_pass": "proposed_place is not null, AND every word of the drawn place name "
                             "is in its label, AND every word of its label appears in some text "
                             "drawn in the frame, AND basis is signage, AND supporting_evidence "
                             "names at least one word of the place name",
            "false_proposal": "on a no_text, product, slogan or person_name photograph: any "
                              "non-null proposed_place, at any confidence. On a partial "
                              "photograph: a non-null proposed_place whose confidence is not "
                              "low, or whose label carries a word that is not among the board's "
                              "VISIBLE words",
            "invented_place": "the subset of false proposals whose label carries a word that no "
                              "text drawn anywhere in the frame shows, or any proposal at all on "
                              "a no_text photograph. Reported separately because it is the "
                              "failure a person cannot detect from the proposal alone.",
            "text_transcribed": "on a photograph with a place board or other text, every "
                                "visible word of it appears in legible_text",
        },
        "gates": {
            "order": "the negative gate is checked first and a failure there ends the "
                     "evaluation as a failure; the positive number is then reported but cannot "
                     "rescue it",
            "negative": {
                "max_false_proposals": 0,
                "statement": "zero false proposals on the negative arm of the split",
                "why_zero": "an invented place is the failure this change is most likely to "
                            "cause and the one a person is least able to notice, so no number "
                            "of them is traded for positive gains. Zero of 12 is a gate, not an "
                            "estimate of a rate: it bounds the true rate only loosely, and this "
                            "record says so rather than claiming more.",
            },
            "positive": {
                "development_min_pass": 3,
                "development_of": 4,
                "held_out_min_pass": 6,
                "held_out_of": 8,
            },
            "regression_against_baseline_same_run": [
                "photographs with text transcribed: candidate at least baseline minus 1",
                "person_name photographs with at least one person trace: candidate at least "
                "baseline",
                "person traces reported on photographs where no person was drawn: candidate at "
                "most baseline",
            ],
            "latency_ms": {"per_photograph_p95_max": 30000},
            "cost": "mean cost per photograph at most twice the baseline's, from the provider's "
                    "reported usage",
        },
        "not_covered": [
            "A distinctive landmark with no text. A synthetic drawing cannot depict a real "
            "landmark, so this corpus measures signage only and makes no claim about landmarks.",
            "Personal photographs. Automated work uses synthetic images only; the operator's "
            "own photographs are for a session with the operator present.",
            "Any model other than the vision primary.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
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
    Path(arguments.out).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{arguments.out} record_sha256 {document['record_sha256']}")
    print(f"baseline prompt_sha256 {body['baseline']['prompt_sha256']}")


if __name__ == "__main__":
    main()
