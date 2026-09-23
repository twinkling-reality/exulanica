"""Freeze the second planner reliability experiment before its change is written.

    python scripts/write_planner_reliability_2_preregistration.py OUT.json --base-commit SHA

The first experiment passed every gate it had and still found two faults in the change it
measured: a person question whose redacted name reached the semantic query without its brackets in
4 draws of 5, where the base commit left the query empty, and a cross-content plan that ran on in
whitespace to the token limit in 2 draws of 5, which the product turns into an error. Its held-out
split is spent. This record fixes a fresh split, with names used nowhere before, the same gates,
and one more gate the first experiment showed was missing: a question the base commit answers
reliably may not collapse, whatever the aggregate says.

The scorer is the first experiment's, unchanged, and its digest is bound again here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure_planner_reliability import STOP_WORDS
from write_planner_reliability_preregistration import (
    CATALOGUE as FIRST_CATALOGUE,
)
from write_planner_reliability_preregistration import (
    PHOTOGRAPHS,
    SCORER,
    WRITTEN,
    scorer_controls,
)

from exulanica.canonical import canonical_json

ROOT = Path(__file__).resolve().parents[1]
FIRST_PREREGISTRATION = "docs/evaluation/2026-09-22-companion-planner-preregistration.json"
FIRST_OUTCOME = "docs/evaluation/2026-09-22-companion-planner-outcome.json"


def entity_id(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"exulanica-lane-q/held-out-2/{name}"))


CATALOGUE = [
    ("Brackenfield Market", "place"),
    ("Ilse Marchetti", "person"),
    ("Hollowmere Station", "place"),
    ("Tobias Achterberg", "person"),
    ("Silverbirch Quay", "place"),
    ("Juniper Tandem", "object"),
    ("Nadia Okonkwo", "person"),
    ("Foxglove Terrace", "place"),
    ("Rafael Quintero", "person"),
    ("Cinder Lane Baths", "place"),
    ("Ostrander Kite", "object"),
]


def question(
    qid: str,
    kind: str,
    text: str,
    *,
    intents: list[str] = PHOTOGRAPHS,
    place: tuple[str, ...] = (),
    entities: tuple[str, ...] = (),
    modes: tuple[str, ...] = ("any",),
    scopes: tuple[str, ...] = (),
    null: bool = True,
    required: tuple[str, ...] = (),
    allowed: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": qid,
        "kind": kind,
        "text": text,
        "expect": {
            "intents": list(intents),
            "place": [entity_id(name) for name in place],
            "entities": [entity_id(name) for name in entities],
            "modes": list(modes),
            "scopes": list(scopes),
            "query": {"null": null, "required": list(required), "allowed": list(allowed)},
        },
    }


QUESTIONS = [
    # Places: seven about something visible or written there, two which-photographs, one who,
    # two explicit requests for related material, the first split's proportions.
    question("S-P01", "place", "What does the notice by the entrance to Brackenfield Market say?",
             place=("Brackenfield Market",), required=("notice",),
             allowed=(*WRITTEN, "notice", "entrance")),
    question("S-P02", "place", "What is written above the platform at Hollowmere Station?",
             place=("Hollowmere Station",), required=("written", "writing", "text", "platform"),
             allowed=(*WRITTEN, "platform", "above")),
    question("S-P03", "place", "What do my pictures from Silverbirch Quay show?",
             place=("Silverbirch Quay",)),
    question("S-P04", "place", "Which of my photos were taken at Foxglove Terrace?",
             place=("Foxglove Terrace",)),
    question("S-P05", "place", "Who did I meet at Cinder Lane Baths?",
             place=("Cinder Lane Baths",), allowed=("people", "person")),
    question("S-P06", "place", "What colour is the awning at Brackenfield Market?",
             place=("Brackenfield Market",), required=("awning",),
             allowed=("awning", "colour", "color")),
    question("S-P07", "place", "Is there a map on the wall at Hollowmere Station?",
             place=("Hollowmere Station",), required=("map",), allowed=("map", "wall")),
    question("S-P08", "place",
             "Find everything linked to Silverbirch Quay across my memories, imported maps and my "
             "authored changes.",
             intents=["content"], place=("Silverbirch Quay",), scopes=("related",)),
    question("S-P09", "place",
             "Show me all related material for Foxglove Terrace, including imported geography and "
             "my edits.",
             intents=["content"], place=("Foxglove Terrace",), scopes=("related",)),
    question("S-P10", "place", "What does the street sign say at Foxglove Terrace?",
             place=("Foxglove Terrace",), required=("sign",), allowed=(*WRITTEN, "street")),
    question("S-P11", "place", "Are there any boats in my photos of Silverbirch Quay?",
             place=("Silverbirch Quay",), required=("boat",), allowed=("boat",)),
    question("S-P12", "place", "What's on the menu at Cinder Lane Baths?",
             place=("Cinder Lane Baths",), required=("menu",), allowed=(*WRITTEN, "menu")),
    # People, including the two shapes the first experiment found faults in.
    question("S-H01", "person", "Which photographs show Ilse Marchetti?",
             entities=("Ilse Marchetti",)),
    question("S-H02", "person", "What was Tobias carrying?", entities=("Tobias Achterberg",),
             required=("carry", "carrying", "carried"),
             allowed=("carry", "carrying", "carried", "object", "item")),
    question("S-H03", "person", "Show me photos of Nadia and Rafael together.",
             entities=("Nadia Okonkwo", "Rafael Quintero"), modes=("together",)),
    question("S-H04", "person", "What does Rafael Quintero's T-shirt say?",
             entities=("Rafael Quintero",), required=("shirt", "tshirt"),
             allowed=(*WRITTEN, "t", "shirt", "tshirt")),
    question("S-H05", "person", "Which pictures have both Ilse and Tobias in them?",
             entities=("Ilse Marchetti", "Tobias Achterberg"), modes=("together",)),
    question("S-H06", "person", "What was Nadia wearing at the wedding?",
             entities=("Nadia Okonkwo",), required=("wearing", "wedding", "outfit", "dress"),
             allowed=("wearing", "wear", "wedding", "clothes", "clothing", "outfit", "dress")),
    question("S-H07", "person", "Find photos of Rafael laughing.", entities=("Rafael Quintero",),
             required=("laugh", "laughing"), allowed=("laugh", "laughing")),
    question("S-H08", "person", "Where have I photographed Tobias?",
             entities=("Tobias Achterberg",)),
    # Plain content: no saved name at all.
    question("S-C01", "content", "Which photographs show a green tent?", null=False,
             required=("tent",), allowed=("green", "tent")),
    question("S-C02", "content", "What does the banner over the road say?", null=False,
             required=("banner",), allowed=(*WRITTEN, "banner", "road")),
    question("S-C03", "content", "What is written on the whiteboard?", null=False,
             required=("whiteboard",), allowed=(*WRITTEN, "whiteboard", "board")),
    question("S-C04", "content", "Find pictures of a waterfall in winter.", null=False,
             required=("waterfall",), allowed=("waterfall", "winter", "snow")),
    question("S-C05", "content", "Are there photos of cats on a windowsill?", null=False,
             required=("cat",), allowed=("cat", "windowsill", "window", "sill")),
    question("S-C06", "content", "What does the plaque on the statue say?", null=False,
             required=("plaque",), allowed=(*WRITTEN, "plaque", "statue")),
    question("S-C07", "content", "How many photos are in my library?"),
    question("S-C08", "content", "Show me photos with a hand-painted sign.", null=False,
             required=("sign",), allowed=(*WRITTEN, "hand", "painted", "handpainted", "paint")),
]


def binding(path: str) -> dict[str, str]:
    record = json.loads((ROOT / path).read_bytes())["record"]
    return {"path": path, "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest()}


def record(base_commit: str) -> dict[str, Any]:
    question_set = {
        "split": "held-out-2",
        "catalogue": [
            {"id": entity_id(name), "class": kind, "name": name} for name, kind in CATALOGUE
        ],
        "questions": QUESTIONS,
    }
    first = json.loads((ROOT / FIRST_PREREGISTRATION).read_bytes())["record"]
    used = {entry["name"] for entry in first["held_out"]["catalogue"]} | {
        entry["name"] for entry in first["development"]["question_set"]["catalogue"]
    } | {name for name, _ in FIRST_CATALOGUE}
    reused = used & {name for name, _ in CATALOGUE}
    if reused:
        raise SystemExit(f"this split reuses names: {sorted(reused)}")
    earlier_texts = {entry["text"] for entry in first["held_out"]["questions"]} | {
        entry["text"] for entry in first["development"]["question_set"]["questions"]
    }
    repeated = earlier_texts & {entry["text"] for entry in QUESTIONS}
    if repeated:
        raise SystemExit(f"this split repeats questions: {sorted(repeated)}")
    kinds = {
        kind: sum(entry["kind"] == kind for entry in QUESTIONS)
        for kind in ("place", "person", "content")
    }
    gates = dict(first["gates"])
    gates["per_question_no_collapse"] = {
        "meaning": "no question the baseline gets right in at least 4 of its 5 draws may be right "
                   "in at most 1 of the candidate's 5",
        "baseline_min_right": 4,
        "candidate_max_right_counted_as_collapse": 1,
    }
    return {
        "predecessor_records": [binding(FIRST_OUTCOME)],
        "profile_note": "Pre-registration of the second Companion planner reliability "
                        "experiment. Written after the first experiment's outcome and before the "
                        "second change exists; no model has been sent any question below.",
        "question": first["question"],
        "premise": "The first experiment, bound above, passed every gate and found two faults "
                   "in its candidate: on 'Which photographs show' a person, the redacted name "
                   "reached the semantic query without its brackets in 4 of 5 draws where the "
                   "base commit left it null, which the aggregate person gate did not show; and "
                   "a cross-content plan ran on in whitespace to the token limit in 2 of 5 draws, "
                   "which answer_question does not catch.",
        "already_seen_before_this_was_written": [
            "Every result of the first experiment, bound above. Its held-out split is spent.",
            "The development split's results for the first candidate's five versions.",
            "The questions below were written by the author of the change, after the first "
            "outcome and before the second change. No model output exists for any of them.",
        ],
        "base_commit": base_commit,
        "model": first["model"],
        "arms": {
            **first["arms"],
            "candidate_may_change": [
                *first["arms"]["candidate_may_change"],
                "the planner's removal of placeholders from the semantic query, to cover the "
                "spellings of the placeholders assigned in that request with or without brackets",
                "the planner's handling of a reply cut off at the token limit",
            ],
            "development_use": "the development split may be used as a smoke test of the change; "
                               "it is not evidence. The held-out split below sees only the "
                               "frozen change.",
        },
        "procedure": {
            **first["procedure"],
            "scorer": {"path": SCORER,
                       "sha256": hashlib.sha256((ROOT / SCORER).read_bytes()).hexdigest()},
            "counts": {"questions": len(QUESTIONS), **kinds},
        },
        "definitions": {
            **first["definitions"],
            "stop_words": sorted(STOP_WORDS),
            "rate": "right draws over draws, per kind. A reply cut off at the token limit is a "
                    "failed draw. A draw ending in a transport or provider error is excluded "
                    "and counted separately.",
        },
        "gates": gates,
        "decisions": {
            **first["decisions"],
            "per_question_no_collapse_fails": "reported as a failure, naming the question",
        },
        "scorer_controls": scorer_controls(question_set),
        "held_out": question_set,
        "not_covered": first["not_covered"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--base-commit", required=True)
    arguments = parser.parse_args()
    body = record(arguments.base_commit)
    document = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": body,
        "record_sha256": hashlib.sha256(canonical_json(body)).hexdigest(),
    }
    Path(arguments.out).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{arguments.out} record_sha256 {document['record_sha256']}")
    print(json.dumps(body["scorer_controls"]))


if __name__ == "__main__":
    main()
