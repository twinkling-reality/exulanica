"""Freeze the planner reliability experiment before the planner is changed.

    python scripts/write_planner_reliability_preregistration.py OUT.json \
        --base-commit SHA --development DEV_SUMMARY.json

The Companion's planner turns a worded question into a Selection plan. On the development split it
refused every place question about something visible or written: it chose the cross-content intent
with a semantic query, which the plan validator refuses, and the repair returned the same plan. This
record fixes, before any change to the planner exists, the held-out questions that will judge a
change, what a right plan is for each, and the gates, including what is done with every outcome.

The held-out catalogue and questions are written here and nowhere else, with names never used in
the development split and never sent to any model. The scorer is the one in
``measure_planner_reliability.py``; its digest is bound here, and a positive control runs it over a
right plan and seven wrong ones for every held-out question before this record is written.
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

from measure_planner_reliability import STOP_WORDS, score

from exulanica.canonical import canonical_json

ROOT = Path(__file__).resolve().parents[1]
SCORER = "scripts/measure_planner_reliability.py"

#: Words that describe writing, accepted in the query of any question about written things.
WRITTEN = [
    "sign", "signage", "text", "writing", "written", "word", "lettering", "notice", "name",
]


def entity_id(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"exulanica-lane-q/held-out/{name}"))


CATALOGUE = [
    ("Copperfield Arcade", "place"),
    ("Ottilie Brandt", "person"),
    ("Wrenmoor Lighthouse", "place"),
    ("Kwame Mensah", "person"),
    ("Saltmarsh Chapel", "place"),
    ("Halvard Sledge", "object"),
    ("Soren Lindqvist", "person"),
    ("Tidewater Row", "place"),
    ("Priya Raman", "person"),
    ("Ashgrove Orchard", "place"),
    ("Kittiwake Dinghy", "object"),
]

PHOTOGRAPHS = ["captures", "entities"]


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
    # Places. Seven ask about something visible or written there, the shape that failed on the
    # development split; two ask which photographs were taken there; one asks who was there; two
    # are explicit requests for related material across memories, imported geography and edits.
    question("H-P01", "place", "What does the sign above the door at Copperfield Arcade say?",
             place=("Copperfield Arcade",), required=("sign",),
             allowed=(*WRITTEN, "above", "door")),
    question("H-P02", "place", "What is written on the plaque at Saltmarsh Chapel?",
             place=("Saltmarsh Chapel",), required=("plaque", "written", "writing", "text"),
             allowed=(*WRITTEN, "plaque", "inscription")),
    question("H-P03", "place", "What can I see in my photos of Wrenmoor Lighthouse?",
             place=("Wrenmoor Lighthouse",)),
    question("H-P04", "place", "Which photographs did I take at Tidewater Row?",
             place=("Tidewater Row",)),
    question("H-P05", "place", "Who was I with at Ashgrove Orchard?",
             place=("Ashgrove Orchard",), allowed=("people", "person")),
    question("H-P06", "place", "What colour are the shutters at Tidewater Row?",
             place=("Tidewater Row",), required=("shutter",),
             allowed=("shutter", "colour", "color", "window")),
    question("H-P07", "place", "Is there a timetable posted at Wrenmoor Lighthouse?",
             place=("Wrenmoor Lighthouse",), required=("timetable", "schedule"),
             allowed=(*WRITTEN, "timetable", "schedule", "posted", "board")),
    question("H-P08", "place",
             "Show me everything connected to Copperfield Arcade, including imported maps and "
             "anything I authored.",
             intents=["content"], place=("Copperfield Arcade",), scopes=("related",)),
    question("H-P09", "place",
             "What else is related to Ashgrove Orchard across my memories, the imported map and "
             "my edits?",
             intents=["content"], place=("Ashgrove Orchard",), scopes=("related",)),
    question("H-P10", "place", "What does the menu board say at Copperfield Arcade?",
             place=("Copperfield Arcade",), required=("menu",),
             allowed=(*WRITTEN, "menu", "board")),
    question("H-P11", "place", "Are there any flowers in my photos from Ashgrove Orchard?",
             place=("Ashgrove Orchard",), required=("flower",), allowed=("flower", "blossom")),
    question("H-P12", "place", "What's painted on the wall at Saltmarsh Chapel?",
             place=("Saltmarsh Chapel",), required=("wall", "painted", "painting", "mural"),
             allowed=(*WRITTEN, "wall", "painted", "painting", "paint", "mural")),
    # People.
    question("H-H01", "person", "Which photographs show Ottilie Brandt?",
             entities=("Ottilie Brandt",)),
    question("H-H02", "person", "What was Kwame holding?", entities=("Kwame Mensah",),
             required=("hold", "holding", "held"),
             allowed=("hold", "holding", "held", "object", "item")),
    question("H-H03", "person", "Show me pictures of Soren and Priya together.",
             entities=("Soren Lindqvist", "Priya Raman"), modes=("together",)),
    question("H-H04", "person", "What does Priya Raman's badge say?", entities=("Priya Raman",),
             required=("badge",), allowed=(*WRITTEN, "badge")),
    question("H-H05", "person", "Which photos have both Ottilie and Kwame in them?",
             entities=("Ottilie Brandt", "Kwame Mensah"), modes=("together",)),
    question("H-H06", "person", "What was Soren wearing on the boat?",
             entities=("Soren Lindqvist",), required=("wearing", "boat", "clothing", "outfit"),
             allowed=("wearing", "wear", "boat", "clothing", "clothes", "outfit")),
    question("H-H07", "person", "Find photographs of Kwame Mensah smiling.",
             entities=("Kwame Mensah",), required=("smile", "smiling"),
             allowed=("smile", "smiling")),
    question("H-H08", "person", "Where have I photographed Priya?", entities=("Priya Raman",)),
    # Plain content: no saved name at all.
    question("H-C01", "content", "Which photographs show a yellow umbrella?", null=False,
             required=("umbrella",), allowed=("yellow", "umbrella")),
    question("H-C02", "content", "What does the sign at the railway station say?", null=False,
             required=("sign",), allowed=(*WRITTEN, "railway", "station", "train")),
    question("H-C03", "content", "What is written on the blackboard?", null=False,
             required=("blackboard", "chalkboard"),
             allowed=(*WRITTEN, "blackboard", "chalkboard")),
    question("H-C04", "content", "Find pictures of a lighthouse at sunset.", null=False,
             required=("lighthouse",), allowed=("lighthouse", "sunset")),
    question("H-C05", "content", "Are there photos of dogs on the beach?", null=False,
             required=("dog",), allowed=("dog", "beach")),
    question("H-C06", "content", "What does the graffiti under the bridge say?", null=False,
             required=("graffiti",), allowed=(*WRITTEN, "graffiti", "bridge", "under")),
    question("H-C07", "content", "When did I take my first photograph?"),
    question("H-C08", "content", "Show me the photos with a handwritten note in them.", null=False,
             required=("note",), allowed=(*WRITTEN, "handwritten", "handwriting", "note")),
]


def held_out() -> dict[str, Any]:
    return {
        "split": "held-out",
        "catalogue": [
            {"id": entity_id(name), "class": kind, "name": name} for name, kind in CATALOGUE
        ],
        "questions": QUESTIONS,
    }


def right_plan(expect: dict[str, Any]) -> dict[str, Any]:
    """The plan the scorer must accept: the first accepted value of every expectation."""
    intent = expect["intents"][0]
    query = None if expect["query"]["null"] else expect["query"]["required"][0]
    return {
        "intent": intent,
        "entities": (
            {"ids": expect["entities"], "mode": expect["modes"][0]}
            if expect["entities"] else None
        ),
        "time": [],
        "place": {"ids": expect["place"]} if expect["place"] else None,
        "capture": None,
        "content": (
            {"scope": expect["scopes"][0], "after": None} if intent == "content" else None
        ),
        "epistemic": "confirmed",
        "semantic_query": query,
        "limit": 10,
    }


def wrong_plans(expect: dict[str, Any], question_set: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Seven ways to be wrong, each of which the scorer must name."""
    right = right_plan(expect)
    people = [e["id"] for e in question_set["catalogue"] if e["class"] == "person"]
    places = [e["id"] for e in question_set["catalogue"] if e["class"] == "place"]
    stranger = next(p for p in people if p not in expect["entities"])
    elsewhere = next(p for p in places if p not in expect["place"])
    return {
        "no_plan": None,
        "other_place": {**right, "place": {"ids": [elsewhere]}},
        "invented_person": {
            **right,
            "entities": {"ids": [*expect["entities"], stranger], "mode": "any"},
        },
        "wrong_intent": (
            {**right, "intent": "captures", "content": None}
            if right["intent"] == "content"
            else {**right, "intent": "content", "content": {"scope": "related", "after": None}}
        ),
        "framing_word": {**right, "semantic_query": "show photographs"},
        "time_added": {
            **right,
            "time": [{"start": "2026-01-01T00:00:00+00:00", "end": "2026-02-01T00:00:00+00:00"}],
        },
        "guesses": {**right, "epistemic": "include_proposals"},
    }


def scorer_controls(question_set: dict[str, Any]) -> dict[str, Any]:
    """Run the scorer on a right plan and seven wrong ones per question. Raise on any miss."""
    caught = 0
    for entry in question_set["questions"]:
        expect = entry["expect"]
        problems = score(right_plan(expect), expect, question_set)
        if problems:
            raise SystemExit(f"{entry['id']}: the right plan was scored wrong: {problems}")
        for name, plan in wrong_plans(expect, question_set).items():
            if not score(plan, expect, question_set):
                raise SystemExit(f"{entry['id']}: the scorer passed the {name} plan")
            caught += 1
    return {
        "right_plans_accepted": len(question_set["questions"]),
        "wrong_plans_refused": caught,
        "wrong_plan_kinds": sorted(wrong_plans(
            question_set["questions"][0]["expect"], question_set
        )),
    }


def record(base_commit: str, development: dict[str, Any]) -> dict[str, Any]:
    question_set = held_out()
    controls = scorer_controls(question_set)
    development_names = {entry["name"] for entry in development["catalogue"]}
    reused = development_names & {name for name, _ in CATALOGUE}
    if reused:
        raise SystemExit(f"held-out names reuse development names: {sorted(reused)}")
    kinds = {
        kind: sum(entry["kind"] == kind for entry in QUESTIONS)
        for kind in ("place", "person", "content")
    }
    return {
        "profile_note": "Pre-registration of the Companion planner reliability experiment. "
                        "Written after the development diagnosis and before any change to the "
                        "planner's prompt, plan validation or repair; no model has been sent "
                        "any held-out question.",
        "question": "Does a change to the planner make it return the right plan for worded "
                    "questions about a place, without making person or plain content questions "
                    "worse, within a latency and cost ceiling?",
        "base_commit": base_commit,
        "premise": development["premise"],
        "already_seen_before_this_was_written": [
            "The development split's 100 draws on the base commit, summarised under "
            "development below, including every whole answer and the plan schema's reasons.",
            "Ten further draws of one development question on a two-entity catalogue.",
            "The client change that makes a refusal name its rule (built and tested before this "
            "record); it is part of the candidate.",
            "The held-out questions below were written by the author of the change, after the "
            "diagnosis and before the change. No model output exists for any of them.",
        ],
        "model": {
            "role": "structured_extraction",
            "primary": "Qwen/Qwen3-235B-A22B-Instruct-2507",
            "fallback": "deepseek-ai/DeepSeek-V4-Flash-0731, which the client uses only when "
                        "the primary is withdrawn",
            "endpoint": "https://api.tokenfactory.nebius.com",
            "revision": None,
            "revision_note": "hosted; the provider exposes no revision",
            "temperature": "0.0, the product's default; draws still vary",
            "cache": "none: the client is built without one, as the API builds it",
        },
        "arms": {
            "baseline": "exulanica/ at the base commit, exported unchanged with git archive "
                        "and imported ahead of the worktree",
            "candidate": "exulanica/ in this lane's worktree once the change is frozen. Every "
                         "run records the SHA-256 of the files that decide a plan.",
            "candidate_may_change": [
                "the planner prompt and its PROMPT_VERSION",
                "the wording of the plan validator's refusals",
                "the planner's repair message",
                "the client's refusal message (already changed; see above)",
            ],
            "candidate_may_not_change": "what SelectionPlan accepts. Every answer either arm "
                                        "receives is re-validated by both arms' SelectionPlan "
                                        "after the run, and one disagreement fails the "
                                        "no_loosening gate.",
            "development_use": "the change may be revised on the development split as often "
                               "as needed. The held-out split sees only the frozen change.",
        },
        "procedure": {
            "draws_per_question_per_arm": 5,
            "order": "ten runs of one draw of every held-out question, alternating baseline "
                     "and candidate, baseline first, so the two arms share the provider's "
                     "conditions",
            "scorer": {"path": SCORER,
                       "sha256": hashlib.sha256((ROOT / SCORER).read_bytes()).hexdigest()},
            "cap_usd_per_run": "0.50, stated in the environment and on the command line",
            "counts": {"questions": len(QUESTIONS), **kinds},
        },
        "definitions": {
            "right_plan": "the planner returned a plan (no refusal after its repair), every id "
                          "in it is in the catalogue with a place selector holding places only, "
                          "and it is the plan the question asks for: an accepted intent, exactly "
                          "the expected place and entity ids, an accepted entity mode and content "
                          "scope, no time window, no capture property, epistemic confirmed, and "
                          "a semantic query allowed by the question's query rule",
            "query_rule": "a null query passes when the question allows null. A query passes "
                          "when it has at least one word after stop words, every word is in the "
                          "question's allowed list, and, when the question names required "
                          "words, at least one of them is present. Words are lowercase letter "
                          "runs, plural-folded by the scorer's stem function.",
            "stop_words": sorted(STOP_WORDS),
            "intents": "captures and entities resolve the same photographs and give the "
                       "composer the same packet, so a question about what photographs show "
                       "accepts either. content is the cross-content listing and is right only "
                       "for an explicit request for related material.",
            "rate": "right draws over draws, per kind. A draw ending in a provider error (not "
                    "a refusal) is excluded and counted separately.",
            "latency": "wall milliseconds of one propose_plan call, repair included",
            "cost": "provider-reported tokens times the manifest's listed prices, every attempt "
                    "included",
        },
        "gates": {
            "units": "rates in basis points of draws (10000 is every draw); ratios in percent",
            "place_rate": {"candidate_min_bp": 9000,
                           "meaning": "right draws over the 60 place draws"},
            "place_improvement": {"candidate_minus_baseline_min_bp": 3000},
            "person_no_regression": {"candidate_minus_baseline_min_bp": -1000},
            "content_no_regression": {"candidate_minus_baseline_min_bp": -1000},
            "latency": {"candidate_p95_ms_max": 8000,
                        "candidate_p95_max_percent_of_baseline_p95": 125},
            "cost": {"candidate_mean_usd_per_draw_max": "0.0006",
                     "candidate_mean_max_percent_of_baseline_mean": 125},
            "no_loosening": {"disagreements_max": 0},
        },
        "decisions": {
            "all_gates_pass": "the change is this lane's result and goes to root with these "
                              "numbers",
            "place_rate_or_improvement_fails": "reported as a failure. The held-out split is not "
                                               "used to revise the change. Root decides whether "
                                               "a partial improvement is worth taking.",
            "baseline_place_rate_at_least_6000_bp": "the held-out split did not reproduce the "
                                                 "defect, so no improvement is claimed from it, "
                                                 "whatever the candidate scores",
            "a_no_regression_gate_fails": "reported as a failure, with the questions that moved",
            "latency_or_cost_fails": "reported as a failure of that gate; the rates are still "
                                     "reported",
            "no_loosening_fails": "the change is withdrawn: it passed by accepting plans the "
                                  "base commit refuses",
            "provider_errors_over_10_percent_of_an_arms_draws": "the run is void and is "
                                                                "reported as void, not scored",
        },
        "scorer_controls": controls,
        "development": development["summary"],
        "held_out": question_set,
        "not_covered": [
            "Whether the right plan finds the right photograph: retrieval, the text join and "
            "the packet are not exercised. Only the plan is scored.",
            "The plan's limit is not scored, so a right plan with a null query and a limit of "
            "one may still hand the composer the wrong photograph at a place with several.",
            "The composer and the answer a person reads.",
            "Any model but the structured-extraction primary, any language but English, and "
            "catalogues larger than eleven entities.",
            "Questions naming a place that is not saved, or naming two places.",
            "Real personal data: every name is invented.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--development", required=True,
                        help="JSON with premise, summary and catalogue of the development split")
    arguments = parser.parse_args()
    development = json.loads(Path(arguments.development).read_bytes())
    body = record(arguments.base_commit, development)
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
