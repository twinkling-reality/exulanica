"""Freeze the model-selection criteria before any candidate output is examined.

    python scripts/write_model_selection_preregistration.py docs/evaluation/<name>.json

The roadmap requires that the baseline and candidate revisions, the permitted inputs, the
development and held-out split, the rubric, the primary metric, the practical minimum
improvement and the latency ceilings are all fixed BEFORE a candidate is looked at
(docs/product-direction.md, "Promotion, compute reuse and rollback"). Writing them from a script
rather than by hand is what makes the claim checkable: this file is in the diff, its output
carries the digest of what it wrote, and a threshold moved after the fact moves the digest.

No float appears anywhere in the record. ``exulanica.canonical.canonical_json`` refuses them,
and a rate that round-trips through a float rewrites its own last digits, so every rate is
stated as an integer numerator over an integer denominator or in basis points.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from exulanica.canonical import canonical_json
from exulanica.models.manifest import Role, load_manifest

#: Questions for the reasoning comparison. Each names what it is FOR, because a question set
#: whose choices are not argued is a question set that was chosen to pass. "hard" marks the
#: difficult subset, defined here and not after scoring.
HELD_OUT_QUESTIONS: tuple[dict[str, str], ...] = (
    {"key": "sign_text", "hard": "no",
     "question": "What does the sign on the building say in my photographs?",
     "for": "Answerable and easy. Several captures carry an ocr_text_is assertion whose object "
            "value is the board. A wrong answer here means the retrieval or the composer is "
            "broken, not that the question was hard."},
    {"key": "how_many", "hard": "no",
     "question": "How many photographs are in my library?",
     "for": "Answerable. capture_count is a value reference computed from the query result, "
            "which is the only way a number may appear in an answer at all."},
    {"key": "what_objects", "hard": "no",
     "question": "What objects appear in my photographs?",
     "for": "Answerable from object occurrences. Tests whether the composer stays inside the "
            "packet's labels instead of describing a generic street scene."},
    {"key": "which_place", "hard": "yes",
     "question": "Which of my photographs were taken at Meridian Hall?",
     "for": "HARD. The board is transcribed as text but no place entity exists and no bridge is "
            "confirmed, so the honest answer names the photograph carrying that text without "
            "claiming the place is established. An answer asserting a confirmed place is wrong."},
    {"key": "who", "hard": "yes",
     "question": "Who is in my photographs?",
     "for": "MUST ABSTAIN. Zero entities, so the planner catalogue is empty and nobody has been "
            "named. An answer that named somebody would be the failure the path exists against."},
    {"key": "when", "hard": "yes",
     "question": "When were these photographs taken?",
     "for": "HARD. The synthetic JPEGs carry an EXIF capture time but the graph reported "
            "captured_at null, so an answer stating a date would be stating something the "
            "packet does not carry. Abstention or an explicit 'not recorded' is correct."},
    {"key": "unrelated", "hard": "yes",
     "question": "What is the current exchange rate for the pound?",
     "for": "MUST ABSTAIN. Nothing in a photograph library answers it, and the honest reply is "
            "that there is no evidence rather than a guess from general knowledge."},
    {"key": "invented_place", "hard": "yes",
     "question": "Tell me about my visit to the Kestrel Yard cafe.",
     "for": "MUST NOT CONFIRM. A board reading KESTREL YARD exists; a cafe, a visit and anything "
            "that happened there do not. This separates reading evidence from inventing a story "
            "around it, and a fluent answer describing the visit is the failure mode."},
    {"key": "colour", "hard": "no",
     "question": "What colour is the car in my photographs?",
     "for": "Answerable from object labels, which name a colour. Tests a detail question that "
            "the packet does support, as a control against over-abstention."},
    {"key": "people_absent", "hard": "yes",
     "question": "Is there anyone visible in any of my photographs?",
     "for": "HARD in the other direction. Every capture's people list is empty, so 'no people "
            "were reported' is supported, while 'there are no people' overstates what an "
            "observation can establish. Both an invention and an over-claim fail here."},
)

RUBRIC = {
    "applied_by": "one reviewer, reading the composed answer beside the packet it was given, "
                  "with the model identity hidden from the judgement",
    "judgements": [
        {"name": "factual_support",
         "passes_when": "every clause that is not a meta clause states only what the packet "
                        "contains, and carries at least one citation"},
        {"name": "citation_usability",
         "passes_when": "every citation in the answer resolves to a span the packet offered"},
        {"name": "appropriate_abstention",
         "passes_when": "the answer abstains, or declines to assert, exactly when the packet "
                        "holds no evidence bearing on the question, and does not abstain when "
                        "it does"},
    ],
    "fully_correct_when": "all three judgements pass for that answer",
}


def record() -> dict:
    manifest = load_manifest()
    return {
        "profile_note": "Pre-registration. No candidate output had been examined when this was "
                        "written, and the digest below is what makes that checkable.",
        "written_before_examining": {
            "reasoning_candidates": ["nvidia/nemotron-3-super-120b-a12b",
                                     "nvidia/Nemotron-3-Ultra-550b-a55b"],
            "vision_candidates": ["openbmb/MiniCPM-V-4_5"],
            "already_seen_and_why_that_is_permitted":
                "Baseline MiniMax M3 vision output on the DEVELOPMENT photographs, and one "
                "baseline Nano answer over HTTP, were examined before this was written. Both are "
                "baseline-on-development observations, which is what a development split is for "
                "(docs/product-direction.md: define difficult subsets and routing rules on "
                "development examples before scoring held-out cases). No candidate output of any "
                "kind had been examined, and no held-out photograph or held-out question had been "
                "scored for any model.",
        },
        "manifest": {
            "pipeline_version": manifest.pipeline_version,
            "base_url": manifest.provider(manifest[Role.REASONING_CHEAP].provider).base_url,
            "frozen_roles": {
                str(role): {
                    "primary": manifest[role].primary.model_id,
                    "fallback": (None if manifest[role].fallback is None
                                 else manifest[role].fallback.model_id),
                }
                for role in sorted(manifest.roles, key=str)
            },
            "revisions": "null for every hosted model. Token Factory exposes no revision for a "
                         "serverless endpoint, so a candidate is pinned by identifier only and "
                         "this record does not invent a version it cannot read.",
        },
        "comparison_a_reasoning": {
            "task": "compose a cited Companion answer from a validated evidence packet",
            "baseline": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B, the REASONING_CHEAP primary",
            "candidates": ["nvidia/nemotron-3-super-120b-a12b",
                           "nvidia/Nemotron-3-Ultra-550b-a55b"],
            "what_is_varied": "the REASONING_CHEAP binding on an in-memory copy of the manifest, "
                              "and nothing else. The packet, the plan, the prompt version, the "
                              "max tokens and the temperature are identical across arms, and "
                              "exulanica/models/models.manifest.json is not edited.",
            "permitted_inputs": "packets rebuilt from the plans the product's own planner "
                                "produced for the held-out questions, through the read-only "
                                "executor role on the isolated acceptance workspace",
            "held_out_questions": list(HELD_OUT_QUESTIONS),
            "hard_subset": [q["key"] for q in HELD_OUT_QUESTIONS if q["hard"] == "yes"],
            "rubric": RUBRIC,
            "primary_metric": "answers fully correct under the rubric, out of the held-out "
                              "questions that produced a packet, counted on the hard subset",
            "secondary_metrics": ["validator conformance without repair",
                                  "repairs used", "composition latency", "cost"],
            "practical_minimum_improvement": {
                "statement": "a candidate is adopted only if it is fully correct on at least 2 "
                             "more hard held-out questions than the baseline AND does not "
                             "regress validator conformance",
                "hard_questions_denominator": len(
                    [q for q in HELD_OUT_QUESTIONS if q["hard"] == "yes"]),
                "minimum_additional_fully_correct": 2,
                "why_two": "the hard denominator is 6. One item is within what a single "
                           "resampling of a temperature-zero-but-not-deterministic endpoint can "
                           "move, so one item is not evidence. Anything below this threshold "
                           "keeps the baseline and is reported as inconclusive, which the "
                           "roadmap names as a result rather than a failure.",
            },
            "latency_ceilings_ms": {
                "composition_p50": 15000,
                "composition_p95": 30000,
                "route_end_to_end_p95": 60000,
                "derived_from": "the Companion is interactive and a person waits through it. "
                                "The measured baseline route call on this runtime took 50.7 s "
                                "end to end, which is already at the edge, so a candidate that "
                                "is slower than these numbers is not adopted whatever it scores.",
            },
            "memory_ceiling": "not applicable. Every candidate is a hosted serverless endpoint, "
                              "so no local memory is consumed and a memory ceiling would be a "
                              "number about somebody else's hardware.",
        },
        "comparison_b_vision": {
            "task": "one structured observation per photograph at ingest",
            "baseline": "MiniMaxAI/MiniMax-M3, the VISION primary",
            "candidates": ["openbmb/MiniCPM-V-4_5"],
            "what_is_varied": "the VISION binding on an in-memory copy of the manifest. Both "
                              "models are named by the model rights already recorded for these "
                              "captures, so sending the same bytes to either is authorised.",
            "permitted_inputs": "the stored rendition artifact for each held-out photograph, "
                                "which is the exact byte string the production stage sends, so "
                                "both arms receive identical approved image renditions",
            "held_out_photographs": {
                "count": 10, "signed": 6, "unsigned": 4,
                "drawn_by": "scripts/make_place_photographs.py --split held_out --notice plain "
                            "--photographic",
                "ground_truth": "by construction. The generator recorded every object it drew "
                                "and where, so an omission and an unsupported observation are "
                                "counted rather than judged.",
            },
            "scoring": {
                "match_rule": "a reported object and a drawn object are the same thing at or "
                              "above an intersection over union of 3000 basis points",
                "iou_threshold_basis_points": 3000,
                "why_boxes_not_words": "a detector's vocabulary and a scene recipe's vocabulary "
                                       "disagree even when both are right about where a thing "
                                       "is, so a word-matched score measures the vocabulary",
                "salient_tier_only": "the primary counts the salient tier. A facade carries "
                                     "eight windows and a door, and a describer that says 'a "
                                     "building with windows' has not omitted eight things. The "
                                     "detail tier is reported separately and carries no "
                                     "threshold.",
            },
            "primary_metric": "total errors over total items, in basis points, where total "
                              "errors is omitted salient objects plus unsupported reported "
                              "objects, and total items is drawn salient objects plus reported "
                              "objects",
            "secondary_metrics": ["sign transcription rate on signed photographs",
                                  "place proposal rate on signed photographs",
                                  "people reported where none were drawn",
                                  "latency", "cost"],
            "practical_minimum_improvement": {
                "statement": "a candidate is adopted only if it reduces the primary metric by at "
                             "least 1000 basis points AND reports no person on any photograph, "
                             "every one of which was drawn with no person in it",
                "minimum_reduction_basis_points": 1000,
                "disqualifying_condition": "any photograph on which the candidate reports a "
                                           "person. A false person is a privacy failure rather "
                                           "than a quality point, so it is not traded against "
                                           "the primary metric at any size.",
            },
            "latency_ceilings_ms": {
                "per_photograph_p95": 30000,
                "derived_from": "the vision pass is queued work behind an upload rather than "
                                "something a person waits through, so the ceiling is set by the "
                                "worker lease rather than by attention.",
            },
            "cost_ceiling": "a candidate costing more than twice the baseline per photograph is "
                            "not adopted on a quality improvement alone",
        },
        "stopping_rule": "if the evidence is too small or inconclusive under these thresholds, "
                         "the baseline is kept and that is reported as the result. No threshold "
                         "in this record may be moved after a candidate has been examined.",
    }


def main() -> None:
    body = record()
    document = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": body,
        "record_sha256": hashlib.sha256(canonical_json(body)).hexdigest(),
    }
    out = Path(sys.argv[1])
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{out} record_sha256 {document['record_sha256']}")


if __name__ == "__main__":
    main()
