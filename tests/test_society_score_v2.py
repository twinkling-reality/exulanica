"""How people fared is the score; what their model answered is reported beside it, never in it.

``exulanica/world/society_score_v2.py`` computes the second version of the score of a person in a
world (``society-person-score.v2``): need relief alone over the people a comparison scores, and,
apart, each turn of theirs by what became of it. These tests hold what that promises:

*   no answer, answer time, receipt, disposition or reason reaches the score: two runs whose states
    are the same score the same whatever their turns say;
*   a turn falls in exactly one class by the engine's disposition, whatever reason code it carries,
    so a reason the contract adds later (partner_busy, say) is counted with no change here;
*   each rate of what a model answered is read over the routine run's choice points on the same
    seed, a denominator no model's answers move, while its shares of its own turns move with them;
*   a seed on which the routine spares the group less than the floor per scored person is excluded
    by name;
*   the catalog refuses a weighed term that reads anything but states;
*   the second seed catalog holds the first's development seeds and twelve held-out seeds that are
    none of the first's.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from copy import deepcopy
from fractions import Fraction

import pytest
from exulanica.grammar.catalogs import load_catalog
from exulanica.grammar.errors import CatalogError
from exulanica.world import society_model_decisions
from exulanica.world.society_catalogs import (
    ROUTINE_DIRECTORY,
    SCHEMAS,
    load_comparison_catalogs,
)
from exulanica.world.society_comparison import RunPlan, play
from exulanica.world.society_decision_contract import DECISION_REASONS, decision_contract
from exulanica.world.society_planner import routine_of
from exulanica.world.society_score_v2 import (
    BELOW_FLOOR,
    DISPOSITIONS,
    REFUSED,
    RunTerms,
    ScoreRefused,
    need_threshold,
    person_score,
    reliability,
    run_terms,
    seed_score,
)

import living_square_support as square
from comparison_support import FIRST_VERSIONS, SECOND_SCORE_VERSIONS

CATALOGS = load_comparison_catalogs(versions=SECOND_SCORE_VERSIONS)
SCORE = person_score(CATALOGS.score)
FLOOR = int(CATALOGS.protocol["need_relief_floor_per_person"]["value"])  # type: ignore[call-overload]
DOCUMENT = square.compose(square.square_objects())
THRESHOLD = need_threshold(routine_of(DOCUMENT))
SEED = "6b" * 32
TICKS = 30
CONTRACT = decision_contract()
CONFIG = {
    "provider": "nebius_token_factory",
    "model_id": "test/model",
    "mechanism": "tool_call",
    "choice_seq": None,
    "manifest_sha256": "0" * 64,
    "prompt_version": "society-person-choice/v1",
    "contract": CONTRACT.binding(),
    "deadline_ms": 20_000,
}


class _Chooser:
    def __init__(self, kind: str = "target") -> None:
        self.kind = kind

    def offerable(self, tick, due):
        return {subject: frozenset(o.label for o in options) for subject, options in due.items()}

    def answers(self, requests):
        results = []
        for request in requests:
            option = next(o for o in request["context"]["options"] if o["kind"] == self.kind)
            results.append(
                {
                    "status": "accepted",
                    "reason": "validated_choice",
                    "proposal": {"label": option["label"], "option": option},
                    "provider": None,
                }
            )
        return results


def _plan(kind: str, group=None) -> RunPlan:
    return RunPlan(
        run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"score-v2:{kind}"),
        society_id=square.SOCIETY,
        seed=SEED,
        population=8,
        inputs=(DOCUMENT,),
        ticks=TICKS,
        decider={"kind": kind} if kind != "model" else {"kind": "model", **_model()},
        provider_config=CONFIG if kind == "model" else None,
        contract=CONTRACT,
        group=group,
    )


def _model() -> dict:
    return {"provider": CONFIG["provider"], "model_id": CONFIG["model_id"]}


def _terms(played, people) -> RunTerms:
    return run_terms(
        played.states,
        played.events,
        people=people,
        threshold=THRESHOLD,
        choice_points=sum(played.choice_points[subject] for subject in people),
        score=SCORE,
    )


@pytest.fixture(scope="module")
def runs():
    model = play(_plan("model"), _Chooser())
    routine = play(_plan("routine"), _Chooser())
    waiting = play(_plan("wait"), _Chooser())
    people = [person["id"] for person in model.start["inhabitants"]]
    return {
        name: (played, _terms(played, people))
        for name, played in (("model", model), ("routine", routine), ("wait", waiting))
    }


def test_the_score_is_need_relief_alone_and_no_turn_reaches_it(runs):
    played, terms = runs["model"]
    _, routine = runs["routine"]
    _, waiting = runs["wait"]
    # The positive control: the model's run had turns, and the minute applied some of them.
    assert terms.turns > 0 and dict(terms.classes)["answered"] > 0
    scored = seed_score(terms, waiting=waiting, routine=routine, score=SCORE, floor_per_person=0)
    assert (
        scored.score
        == scored.need_relief
        == Fraction(waiting.urgency - terms.urgency, waiting.urgency - routine.urgency)
    )
    # Every turn recast as a timeout and the answers' calls changed: the states are the same, so
    # the score is the same, and only what is reported beside it moves.
    events = deepcopy(played.events)
    for event in events:
        if event.kind == "decision_applied":
            event.document.update(disposition="unavailable", reason="model_timed_out")
    receipts = deepcopy(played.receipts)
    for receipt in receipts:
        receipt["provider"] = {"latency_ms": 20_001, "cost_usd": "1.00000000"}
    timed_out = run_terms(
        played.states,
        events,
        people=terms.people,
        threshold=THRESHOLD,
        choice_points=terms.choice_points,
        score=SCORE,
    )
    assert dict(timed_out.classes)["not_answered"] == terms.turns
    again = seed_score(timed_out, waiting=waiting, routine=routine, score=SCORE, floor_per_person=0)
    assert again == scored
    assert reliability(timed_out, routine=routine) != reliability(terms, routine=routine)


def test_the_anchors_score_zero_and_one_and_a_seed_below_the_floor_is_excluded(runs):
    _, routine = runs["routine"]
    _, waiting = runs["wait"]
    assert seed_score(
        routine, waiting=waiting, routine=routine, score=SCORE, floor_per_person=0
    ).score == Fraction(1)
    assert seed_score(
        waiting, waiting=waiting, routine=routine, score=SCORE, floor_per_person=0
    ).score == Fraction(0)
    spared = waiting.urgency - routine.urgency
    per_person = spared // len(routine.people)
    assert per_person > 0, "the positive control: the routine spared the people something"
    just = seed_score(
        routine, waiting=waiting, routine=routine, score=SCORE, floor_per_person=per_person
    )
    assert just.excluded is None
    over = seed_score(
        routine, waiting=waiting, routine=routine, score=SCORE, floor_per_person=per_person + 1
    )
    assert (over.excluded, over.score, over.need_relief) == (BELOW_FLOOR, None, None)


def test_a_rate_is_read_over_the_routines_choice_points_which_no_answer_moves(runs):
    _played, terms = runs["model"]
    _, routine = runs["routine"]
    # The positive control: the routine's run found choice points for the people.
    assert routine.choice_points > 0
    found = reliability(terms, routine=routine)
    assert found.routine_choice_points == routine.choice_points
    # The same answers over a run whose model made people choose twice as often: its own turns
    # double, so its shares halve, and the rates, over the routine's choice points, do not move.
    doubled = dataclasses.replace(
        terms,
        turns=terms.turns * 2,
        classes=tuple(
            (key, count if key != "not_applied" else count + terms.turns)
            for key, count in terms.classes
        ),
    )
    moved = reliability(doubled, routine=routine)
    assert moved.per_routine_choice["answered"] == found.per_routine_choice["answered"]
    assert moved.shares["answered"] == found.shares["answered"] / 2
    assert moved.routine_choice_points == found.routine_choice_points
    # With no routine run of the seed there is no rate at all, never one over the run's own turns.
    assert reliability(terms, routine=None).per_routine_choice is None


def test_every_disposition_and_every_reason_falls_in_exactly_one_class():
    assert tuple(society_model_decisions._DISPOSITIONS) == DISPOSITIONS
    refused = next(iter(SCORE.classes[REFUSED][1]))
    assert refused in DECISION_REASONS
    # A reason the contract states, and one it may state later, each in exactly one class.
    for disposition in DISPOSITIONS:
        for reason in [*sorted(DECISION_REASONS), "partner_busy", "no_room_to_talk"]:
            found = SCORE.turn_class(disposition, reason)
            assert found in SCORE.classes
    assert SCORE.turn_class("rejected", "answer_not_offered") == "refused"
    assert SCORE.turn_class("rejected", "partner_busy") == "not_applied"
    assert SCORE.turn_class("unavailable", "model_timed_out") == "not_answered"
    assert SCORE.turn_class("applied", "validated_choice") == "answered"
    with pytest.raises(ScoreRefused, match="turn_not_classified"):
        SCORE.turn_class("forgotten", "validated_choice")


def test_the_group_is_scored_alone_and_everybody_else_reported_apart():
    people = sorted(p["id"] for p in play(_plan("routine"), _Chooser()).start["inhabitants"])
    group = frozenset(people[:3])
    played = play(_plan("model", group), _Chooser())
    terms = _terms(played, sorted(group))
    everyone = _terms(played, people)
    assert terms.people == tuple(sorted(group))
    assert terms.others == tuple(people[3:])
    assert terms.urgency + terms.others_urgency == everyone.urgency
    # Only the group's turns are counted; everybody else was decided by their routine here.
    assert terms.turns == sum(1 for r in played.receipts if r["subject_id"] in group) > 0


@pytest.mark.parametrize(
    ("key", "change", "message"),
    [
        ("need_relief", {"reads": "events", "dispositions": ["applied"]}, "reads states alone"),
        ("need_relief", {"reads": "calls"}, "reads states alone"),
        ("answered", {"dispositions": []}, "names the dispositions it counts"),
        ("latency", {"reasons": ["model_timed_out"]}, "only a reliability term names reason"),
        ("refused", {"weight_milli": -1000}, "exactly a primary term carries a weight"),
    ],
    ids=[
        "primary-reads-events",
        "primary-reads-calls",
        "class-counts-nothing",
        "measure-names-reasons",
        "reliability-weighed",
    ],
)
def test_the_catalog_refuses_a_weighed_term_that_reads_anything_but_states(
    tmp_path, key, change, message
):
    document = json.loads((ROUTINE_DIRECTORY / "society-person-score.v2.json").read_text())
    next(e for e in document["entries"] if e["key"] == key).update(change)
    path = tmp_path / "society-person-score.v2.json"
    path.write_text(json.dumps(document))
    with pytest.raises(CatalogError, match=message):
        load_catalog(path, SCHEMAS[("society-person-score", 2)])


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda e: e["waiting_share"].update(part="primary", weight_milli=1000), "score_terms"),
        (lambda e: e.pop("not_applied"), "reliability_not_computed"),
        (lambda e: e["answered"].update(dispositions=["applied", "stale"]), "reliability_not"),
        (lambda e: e["not_answered"].update(dispositions=["unavailable", "stale"]), "twice"),
        (lambda e: e["minutes_by_activity"].update(reads="calls"), "score_measures"),
    ],
    ids=["two-weighed", "class-missing", "answered-counts-more", "twice", "measure-missing"],
)
def test_a_score_this_code_does_not_compute_is_refused_by_name(change, code):
    entries = {key: dict(entry) for key, entry in CATALOGS.score.items()}
    change(entries)
    with pytest.raises(ScoreRefused, match=code):
        person_score(entries)


def test_the_second_seeds_keep_the_first_development_seeds_and_hold_out_fresh_ones():
    first = load_comparison_catalogs(versions=FIRST_VERSIONS)
    by_phase: dict[str, list[str]] = {}
    for entry in CATALOGS.seeds.values():
        by_phase.setdefault(str(entry["phase"]), []).append(str(entry["seed_digest"]))
    first_by_phase: dict[str, list[str]] = {}
    for entry in first.seeds.values():
        first_by_phase.setdefault(str(entry["phase"]), []).append(str(entry["seed_digest"]))
    assert by_phase["development"] == first_by_phase["development"]
    assert len(by_phase["held_out"]) == len(set(by_phase["held_out"])) == 12
    every_first = {digest for digests in first_by_phase.values() for digest in digests}
    assert not set(by_phase["held_out"]) & every_first
    assert not set(by_phase["held_out"]) & set(by_phase["development"])
