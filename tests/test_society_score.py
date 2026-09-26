"""A person's score is read from what the engine recorded, and from nothing a model said.

The score of the role "a person in your world" is declared in the society-person-score catalog and
computed by ``exulanica/world/society_score.py`` from a run's states and the dispositions the
engine recorded. These tests hold what that promises: the threshold is the recorded routine's, so
another routine moves the need counted; a run's answers, tokens, costs and labels change nothing
the score reads; the two anchors score 0 and 1 and anything else is shown as it is, below 0 or
above 1; a seed the routine barely helps on is excluded by name; and every disposition the engine
records is counted by exactly one term or applied, with an unknown one refused.
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
from exulanica.world.society_decision_contract import decision_contract
from exulanica.world.society_planner import routine_of
from exulanica.world.society_score import (
    APPLIED,
    BELOW_FLOOR,
    DECISION_EVENT,
    RunTerms,
    ScoreRefused,
    need_threshold,
    person_score,
    run_terms,
    seed_score,
)

import living_square_support as square

CATALOGS = load_comparison_catalogs()
SCORE = person_score(CATALOGS.score)
DOCUMENT = square.compose(square.square_objects())
SEED = "5e" * 32
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


class _FirstPlace:
    """A scripted chooser: the first place offered, and a call record it fills as it is told."""

    def __init__(self, provider: dict | None = None) -> None:
        self.provider = provider

    def offerable(self, tick, due):
        return {
            subject: frozenset(option.label for option in options)
            for subject, options in due.items()
        }

    def answers(self, requests):
        results = []
        for request in requests:
            option = next(o for o in request["context"]["options"] if o["kind"] == "target")
            results.append(
                {
                    "status": "accepted",
                    "reason": "validated_choice",
                    "proposal": {"label": option["label"], "option": option},
                    "provider": None if self.provider is None else dict(self.provider),
                }
            )
        return results


def _plan(kind: str) -> RunPlan:
    return RunPlan(
        run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"score-test:{kind}"),
        society_id=square.SOCIETY,
        seed=SEED,
        population=8,
        inputs=(DOCUMENT,),
        ticks=40,
        decider={"kind": kind},
        provider_config=CONFIG if kind == "model" else None,
        contract=CONTRACT,
    )


def _terms(played, threshold: int | None = None) -> RunTerms:
    return run_terms(
        played.states,
        played.events,
        people=[person["id"] for person in played.start["inhabitants"]],
        threshold=need_threshold(routine_of(DOCUMENT)) if threshold is None else threshold,
        score=SCORE,
    )


def _call(cost: str, tokens: int) -> dict:
    return {
        "provider": "nebius_token_factory",
        "model_id": "test/model",
        "served_model_id": "test/model-served",
        "mechanism": "tool_call",
        "prompt_version": "society-person-choice/v1",
        "messages_sha256": "1" * 64,
        "answers_asked": 1,
        "calls": [],
        "prompt_tokens": tokens,
        "completion_tokens": tokens,
        "cost_usd": cost,
        "cost_known": True,
        "latency_ms": tokens,
    }


def test_the_threshold_is_the_recorded_routine_s_and_another_routine_moves_the_need_counted():
    routine = routine_of(DOCUMENT)
    assert need_threshold(routine) == 750  # the routine's own rest preference, as recorded
    played = play(_plan("routine"), _FirstPlace())
    lower = dataclasses.replace(
        routine,
        activities={
            key: dataclasses.replace(activity, preferred_at_need=700)
            if activity.preferred_at_need == 750
            else activity
            for key, activity in routine.activities.items()
        },
    )
    assert need_threshold(lower) == 700
    at_recorded = _terms(played)
    at_lower = _terms(played, need_threshold(lower))
    # The same minutes read under a routine that prefers rest sooner count more need above it.
    assert at_lower.urgency > at_recorded.urgency > 0


def test_a_routine_that_prefers_nothing_gives_no_threshold_and_is_refused_by_name():
    routine = routine_of(DOCUMENT)
    never = dataclasses.replace(
        routine,
        activities={
            key: dataclasses.replace(activity, preferred_at_need=0)
            for key, activity in routine.activities.items()
        },
    )
    with pytest.raises(ScoreRefused, match="routine_prefers_nothing"):
        need_threshold(never)


def test_what_a_model_said_of_itself_changes_nothing_the_score_reads():
    """Two runs with the same minutes, one whose receipts say it was cheap and quick and one whose
    receipts say it was dear and slow, score the same: the score reads engine states and the
    dispositions the engine recorded, never a call record, an answer's label or its cost."""
    cheap = play(_plan("model"), _FirstPlace(_call("0.000001", 10)))
    dear = play(_plan("model"), _FirstPlace(_call("9.990000", 99_999)))
    # The positive control: the receipts differ, and so do the events that carry the model's name.
    assert cheap.receipts != dear.receipts
    assert cheap.minute_digests == dear.minute_digests
    renamed = deepcopy(dear.events)
    for event in renamed:
        if event.kind == DECISION_EVENT:
            event.document["chose"] = "a label no option has"
            event.document["model"] = {"provider": "elsewhere", "model_id": "another/model"}
            event.document["summary"] = "a summary no engine wrote"
    dear = dataclasses.replace(dear, events=renamed)
    assert _terms(cheap) == _terms(dear)
    waiting, routine = (
        _terms(play(_plan("wait"), _FirstPlace())),
        _terms(play(_plan("routine"), _FirstPlace())),
    )
    scored = [
        seed_score(_terms(run), waiting=waiting, routine=routine, score=SCORE, floor=0)
        for run in (cheap, dear)
    ]
    assert scored[0] == scored[1]
    assert scored[0].score is not None


def _anchor(
    urgency: int, *, turns: int = 0, counted=(("turns_refused", 0), ("turns_unanswered", 0))
):
    return RunTerms(
        ticks=60,
        threshold=750,
        people=("a", "b"),
        urgency=urgency,
        turns=turns,
        applied=turns - sum(count for _, count in counted),
        counted=tuple(counted),
        not_applied_reasons=(),
        person_minutes=(("doing", 60), ("waiting", 60), ("walking", 0)),
        activities=(("a", 1), ("b", 1)),
    )


def test_waiting_scores_zero_the_routine_one_and_anything_else_unclipped():
    waiting, routine = _anchor(10_000), _anchor(2_000)

    def score(urgency: int, **turns) -> Fraction | None:
        return seed_score(
            _anchor(urgency, **turns), waiting=waiting, routine=routine, score=SCORE, floor=4_600
        ).score

    assert score(10_000) == 0
    assert score(2_000) == 1
    # Worse than waiting, and better than the routine: shown exactly as they are.
    assert score(12_000) == Fraction(-1, 4)
    assert score(0) == Fraction(5, 4)
    # Every turn refused costs the whole of the relief it bought: a run whose every turn the
    # routine took scores what waiting scores.
    assert score(2_000, turns=4, counted=(("turns_refused", 4), ("turns_unanswered", 0))) == 0
    assert score(
        2_000, turns=4, counted=(("turns_refused", 1), ("turns_unanswered", 1))
    ) == Fraction(1, 2)


def test_a_seed_the_routine_barely_helps_on_is_excluded_by_name_and_still_states_its_shares():
    waiting, routine = _anchor(6_000), _anchor(2_000)
    run = _anchor(3_000, turns=2, counted=(("turns_refused", 1), ("turns_unanswered", 0)))
    kept = seed_score(run, waiting=waiting, routine=routine, score=SCORE, floor=4_000)
    below = seed_score(run, waiting=waiting, routine=routine, score=SCORE, floor=4_001)
    assert kept.excluded is None and kept.score is not None
    assert (below.excluded, below.score, below.need_relief) == (BELOW_FLOOR, None, None)
    assert below.shares == {"turns_refused": Fraction(1, 2), "turns_unanswered": Fraction(0)}


def test_anchors_of_another_window_or_threshold_are_refused():
    run = _anchor(3_000)
    other = dataclasses.replace(_anchor(6_000), threshold=700)
    with pytest.raises(ScoreRefused, match="anchor_mismatch"):
        seed_score(run, waiting=other, routine=_anchor(2_000), score=SCORE, floor=0)


def test_every_disposition_the_engine_records_is_applied_or_counted_by_exactly_one_term():
    recorded = society_model_decisions._DISPOSITIONS
    assert DECISION_EVENT == society_model_decisions.DECISION_EVENT_KIND
    assert recorded[0] == APPLIED
    assert set(SCORE.counted) | {APPLIED} == set(recorded)
    assert len(SCORE.counted) == len(recorded) - 1
    assert SCORE.counted["rejected"] == "turns_refused"


def test_turns_are_counted_by_the_disposition_the_engine_recorded_and_an_unknown_one_refused():
    played = play(_plan("model"), _FirstPlace())
    stored = [
        {"event_kind": e.kind, "subject_id": str(e.subject_id), "document": dict(e.document)}
        for e in played.events
    ]
    decided = [e for e in stored if e["event_kind"] == DECISION_EVENT]
    people = [person["id"] for person in played.start["inhabitants"]]
    before = run_terms(played.states, stored, people=people, threshold=750, score=SCORE)
    # The positive control: the engine recorded these turns, and applied some of them.
    assert before.turns == len(decided) > 2
    assert before.applied == sum(1 for e in decided if e["document"]["disposition"] == APPLIED)
    applied = [e for e in decided if e["document"]["disposition"] == APPLIED]
    applied[0]["document"].update(disposition="rejected", reason="known_target_unreachable")
    applied[1]["document"].update(disposition="unavailable", reason="model_timed_out")
    after = run_terms(played.states, stored, people=people, threshold=750, score=SCORE)
    counted = dict(before.counted)
    assert dict(after.counted) == {
        "turns_refused": counted["turns_refused"] + 1,
        "turns_unanswered": counted["turns_unanswered"] + 1,
    }
    assert after.applied == before.applied - 2
    reasons = dict(after.not_applied_reasons)
    assert (
        reasons["model_timed_out"] == dict(before.not_applied_reasons).get("model_timed_out", 0) + 1
    )
    applied[2]["document"]["disposition"] = "misplaced"
    with pytest.raises(ScoreRefused, match="disposition_not_scored"):
        run_terms(played.states, stored, people=people, threshold=750, score=SCORE)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda e: e["need_relief"].update(part="held_out", weight_milli=0), "score_terms"),
        (lambda e: e["turns_refused"].update(reads="calls", dispositions=()), "score_terms"),
        (lambda e: e["waiting_share"].update(reads="calls"), "score_measures"),
        (
            lambda e: e["turns_unanswered"].update(dispositions=("rejected", "unavailable")),
            "disposition_counted_twice",
        ),
        (lambda e: e["turns_refused"].update(dispositions=("applied",)), "counted_twice"),
    ],
    ids=["relief-unweighed", "turns-read-calls", "measure-reads-calls", "twice", "applied"],
)
def test_a_score_this_code_does_not_compute_is_refused_by_name(change, code):
    entries = {key: dict(entry) for key, entry in CATALOGS.score.items()}
    change(entries)
    with pytest.raises(ScoreRefused, match=code):
        person_score(entries)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda e: e.update(weight_milli=0), "exactly a primary term carries a weight"),
        (lambda e: e.update(dispositions=[]), "names what it counts"),
        (lambda e: e.update(reads="calls", dispositions=[]), "reads the host's record"),
    ],
    ids=["unweighed-primary", "events-count-nothing", "primary-reads-calls"],
)
def test_the_score_catalog_refuses_a_term_it_cannot_state(tmp_path, change, message):
    document = json.loads((ROUTINE_DIRECTORY / "society-person-score.v1.json").read_text())
    change(next(e for e in document["entries"] if e["key"] == "turns_refused"))
    path = tmp_path / "society-person-score.v1.json"
    path.write_text(json.dumps(document))
    with pytest.raises(CatalogError, match=message):
        load_catalog(path, SCHEMAS[("society-person-score", 1)])


def test_held_out_seeds_are_committed_apart_from_development_seeds():
    by_phase: dict[str, set[str]] = {}
    for entry in CATALOGS.seeds.values():
        by_phase.setdefault(str(entry["phase"]), set()).add(str(entry["seed_digest"]))
    assert sorted(by_phase) == ["development", "held_out"]
    assert len(by_phase["development"]) == len(by_phase["held_out"]) == 8
    assert not by_phase["development"] & by_phase["held_out"]
