"""A comparison of a society of things: its runs, its sixth score's terms and its refusals.

Two knights and a sword are placed in a starter world whose society of things runs the hands
module. A comparison plays an hour of it from genesis for the knights, as each arm decides for
them: the routine (the score's one), waiting at every choice point (its zero), and a model that
says something to the nearest being and picks the sword up when it can. Each run plays as the
society's own minutes do, its things phase included, and replays from what it stored byte for
byte. The sixth score counts each person's kinds once, a line said and a hands act among them, and
reports the acts, the lines and their near repeats beside the terms; the third score's anchored
math reads them unchanged. Until a reading line is measured for a society of things, a comparison
of one is refused by name.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from exulanica.world.society_catalogs import comparison_catalogs_for_engine
from exulanica.world.society_comparison import RunPlan, play, replay
from exulanica.world.society_comparison_reading import (
    NO_READING_LINE,
    measured_line,
    population_maximum,
    reading_bound,
)
from exulanica.world.society_comparison_result import (
    check_definition_body,
    run_outcome,
    scoring_binding,
)
from exulanica.world.society_comparison_verdict import ComparisonRefused
from exulanica.world.society_decision_contract import person_role
from exulanica.world.society_engines import society_engine
from exulanica.world.society_score import _minute_class
from exulanica.world.society_score_v2 import RunTerms
from exulanica.world.society_score_v3 import seed_score
from exulanica.world.society_score_v6 import (
    ACT_KINDS,
    near_repeat,
    run_terms,
    score,
    validate_terms,
)
from exulanica.world.society_things import THINGS_PROFILE

from comparison_support import development_body
from things_society_support import compose, thing

ROLE = person_role()
#: The terms a society of things asks its people under: lines and hands among its options.
CONTRACT = ROLE.contract_for(THINGS_PROFILE)
#: A development seed's text, as the seeds catalog commits it.
SEED = "349d43ff977100b3b7bfee1d1de606aa949b5ad2ba7d1c7d8f99cf87af19ae34"
SOURCE = compose(
    (
        thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593),
        thing("knight", "knight", 1, 3_000, 3_000),
        thing("knight-2", "knight", 1, 5_000, 3_000),
        thing("sword", "sword", 2, 2_400, 2_600),
    )
)
MODEL = {"kind": "model", "provider": "nebius_token_factory", "model_id": "test/model"}
#: Lines that share few words with each other, said in turn.
VARIED: tuple[str, ...] = (
    "Good morning.",
    "Is that your sword?",
    "The well looks deep today.",
    "Shall we walk to the gate together?",
    "I have not seen you here before.",
    "Rain may come later this afternoon.",
    "Who built this square?",
    "My armour needs polishing again.",
    "Have you eaten anything yet?",
    "Listen, someone is singing nearby.",
    "Tell me about your travels.",
    "This bench was made of oak.",
    "Watch your step on those stones.",
    "Our horses rest beyond the wall.",
    "Bread smells wonderful from the bakery.",
    "Count the towers with me.",
)
#: The kinds a decider chooses first, in this order, where they are offered.
FIRST = ("pick_up", "give", "say_to", "say_all")


class _Choosing:
    """A model that picks a thing up or hands it over where it can, else says something, each
    line different, else goes to the first place offered."""

    def __init__(self, lines: tuple[str, ...] = ()) -> None:
        self.lines = lines or VARIED
        self.said = 0

    def offerable(self, _tick: int, due: dict[str, Any]) -> dict[str, frozenset[str]]:
        return {
            subject: frozenset(option.label for option in options)
            for subject, options in due.items()
        }

    def answers(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results = []
        for request in requests:
            options = request["context"]["options"]
            option = next(
                (o for kind in FIRST for o in options if o["kind"] == kind),
                next((o for o in options if o["kind"] == "target"), options[0]),
            )
            proposal = {"label": option["label"], "option": option}
            if option["kind"] in ("say_to", "say_all"):
                proposal["line"] = self.lines[self.said % len(self.lines)]
                self.said += 1
            results.append(
                {
                    "status": "accepted",
                    "reason": "validated_choice",
                    "proposal": proposal,
                    "provider": None,
                }
            )
        return results


def _config() -> dict[str, Any]:
    return {
        "provider": MODEL["provider"],
        "model_id": MODEL["model_id"],
        "mechanism": "tool_call",
        "choice_seq": None,
        "manifest_sha256": "0" * 64,
        "prompt_version": ROLE.terms(THINGS_PROFILE).prompt_version,
        "contract": CONTRACT.binding(),
        "deadline_ms": 20_000,
    }


def _knights() -> frozenset[str]:
    start = play(_plan("routine", group=None, ticks=1), _Choosing()).start
    return frozenset(p["id"] for p in start["inhabitants"] if p["came_by"] == "placed")


def _plan(kind: str, *, group: frozenset[str] | None = None, ticks: int = 60) -> RunPlan:
    return RunPlan(
        run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"things-comparison:{kind}"),
        society_id=uuid.uuid5(uuid.NAMESPACE_URL, "things-comparison:society"),
        seed=SEED,
        population=6,
        inputs=(SOURCE,),
        ticks=ticks,
        decider=MODEL if kind == "model" else {"kind": kind},
        provider_config=_config() if kind == "model" else None,
        contract=CONTRACT,
        group=group,
        engine_profile=THINGS_PROFILE,
    )


def _terms(kind: str, asking: _Choosing | None = None) -> tuple[RunTerms, dict[str, Any]]:
    plan = _plan(kind, group=_knights())
    played = play(plan, asking or _Choosing())
    catalogs = comparison_catalogs_for_engine(THINGS_PROFILE)
    outcome = run_outcome(
        plan,
        {"profile": "exulanica.society-comparison/v2", "document_sha256": "0" * 64},
        kind,
        "f" * 64,
        played,
        None,
        catalogs,
    )
    return validate_terms(outcome["terms"]), outcome["terms"]


def test_a_things_run_plays_its_lines_and_hands_and_replays_byte_for_byte():
    plan = _plan("model", group=_knights(), ticks=20)
    played = play(plan, _Choosing())
    kinds = {event.kind for event in played.events}
    assert {"said", "picked_up", "decision_applied"} <= kinds
    assert played.start["profile"] == THINGS_PROFILE
    # No visitor in a comparison: a run starts at genesis and nobody crosses in.
    assert all(p["came_by"] != "crossed" for state in played.states for p in state["inhabitants"])
    again = replay(
        plan,
        list(zip(played.requests, played.receipts, strict=True)),
        minute_digests=played.minute_digests,
    )
    assert (again.states, again.events, again.receipts) == (
        played.states,
        played.events,
        played.receipts,
    )


def test_the_sixth_score_counts_each_kind_once_with_the_acts_and_anchors_on_the_routine():
    waiting, _ = _terms("wait")
    routine, _ = _terms("routine")
    run, document = _terms("model")
    # A line said and a hands act are kinds beside the activities; the routine never does either.
    assert document["acts"]["said"] > 1 and document["acts"]["picked_up"] == 1
    assert document["lines"]["said"] == document["acts"]["said"]
    scored = score(comparison_catalogs_for_engine(THINGS_PROFILE).score)

    def anchored(terms):
        return seed_score(
            terms, waiting=waiting, routine=routine, score=scored, floor_per_person=575
        )

    # The anchors score 0 and 1 on their own seed, and nothing is clipped: a model whose knights
    # also spoke and handed the sword over did more kinds than the routine's.
    assert (anchored(waiting).score, anchored(routine).score) == (0, 1)
    found = anchored(run)
    assert found.excluded is None and found.variety > 1
    # However many lines a knight said, saying counts once for it.
    many, _ = _terms("model", _Choosing(("Hello.", "Good day.")))
    assert dict(many.activities) == dict(run.activities)


def test_lines_that_nearly_repeat_are_reported_never_weighed():
    _, varied = _terms("model")
    _, same = _terms("model", _Choosing(("The sword is here.",)))
    assert varied["lines"]["near_repeats"] < same["lines"]["near_repeats"]
    # Every line but each knight's first repeats one it said or heard.
    assert same["lines"]["near_repeats"] >= same["lines"]["said"] - len(_knights())
    assert near_repeat("The sword is here.", ["the sword is HERE"])
    assert not near_repeat("Good morning, knight.", ["The sword is here."])
    # Exactly half of all words shared (two of four) is a near repeat; less is not.
    assert near_repeat("the sword shines", ["the sword rusts"])
    assert not near_repeat("the sword shines", ["the shield rusts"])
    # Reported, not weighed: the variety a run counts is the same either way.
    assert varied["activities"] == same["activities"]


def test_stored_terms_that_do_not_report_acts_are_refused():
    _, document = _terms("routine")
    validate_terms(document)
    with pytest.raises(Exception, match="things_terms_binding"):
        validate_terms({**document, "acts": {}})
    with pytest.raises(Exception, match="things_terms_binding"):
        validate_terms({**document, "lines": {"said": 1, "near_repeats": 2}})


def test_only_the_scored_people_s_acts_are_counted():
    plan = _plan("model", group=_knights(), ticks=20)
    played = play(plan, _Choosing())
    knight = sorted(_knights())[0]
    one = run_terms(
        played.states,
        played.events,
        people=[knight],
        threshold=0,
        choice_points=0,
        score=score(comparison_catalogs_for_engine(THINGS_PROFILE).score).reliability,
    )
    said = sum(1 for e in played.events if e.kind == "said" and str(e.subject_id) == knight)
    assert one["acts"]["said"] == one["lines"]["said"] == said
    # Each kind once: the knight's activities and acts as a set, however many times each.
    kinds = {
        str(person["action"]["kind"])
        for state in played.states
        for person in state["inhabitants"]
        if person["id"] == knight and _minute_class(person) == "doing"
    } | {e.kind for e in played.events if str(e.subject_id) == knight and e.kind in ACT_KINDS}
    assert said > 1 and one["activities"] == {knight: len(kinds)}


def test_a_society_of_things_is_compared_under_the_sixth_score_and_its_own_binding():
    catalogs = comparison_catalogs_for_engine(THINGS_PROFILE)
    assert catalogs.versions["society-person-score"] == 6
    binding = scoring_binding(catalogs)
    assert binding["profile"] == "exulanica.society-comparison-binding/v6"
    assert "exulanica.world.society_score_v6" in binding["modules"]
    assert society_engine(THINGS_PROFILE).comparisons


def test_a_things_comparison_waits_for_its_reading_line_while_the_others_keep_theirs():
    catalogs = comparison_catalogs_for_engine(THINGS_PROFILE)
    assert measured_line("things") is None
    with pytest.raises(ComparisonRefused) as refused:
        reading_bound(catalogs)
    assert refused.value.code == NO_READING_LINE
    # The purposeful family reads the protocol's own line; the living family its measured one.
    purposeful = comparison_catalogs_for_engine("exulanica-society/v2")
    living = comparison_catalogs_for_engine("exulanica-society/v5")
    assert population_maximum(purposeful) > 0
    assert measured_line("living") is not None and population_maximum(living) > 0
    assert reading_bound(living).per_person_us == measured_line("living")["replay_per_person_us"]


def test_a_judged_comparison_of_a_society_of_things_waits_for_its_own_held_out_seeds():
    catalogs = comparison_catalogs_for_engine(THINGS_PROFILE)
    body = development_body(catalogs)
    held_out = sorted(
        str(entry["seed_digest"])
        for entry in catalogs.seeds.values()
        if entry["phase"] == "held_out"
    )
    with pytest.raises(ComparisonRefused) as refused:
        check_definition_body({**body, "phase": "held_out", "seeds": held_out[:1]}, catalogs)
    assert refused.value.code == "held_out_seeds_not_drawn"
    # A development comparison of it is defined on the development seeds every version commits.
    development = sorted(
        str(entry["seed_digest"])
        for entry in catalogs.seeds.values()
        if entry["phase"] == "development"
    )
    check_definition_body({**body, "seeds": development[:2]}, catalogs)
