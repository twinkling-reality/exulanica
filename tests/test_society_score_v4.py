"""Hand-calculated living need, performed variety and same-seed anchor controls."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest
from exulanica.world import society_score_v2, society_score_v3, society_score_v4
from exulanica.world.society_catalogs import load_comparison_catalogs
from exulanica.world.society_living import input_routine
from exulanica.world.society_score import ScoreRefused

from living_town_support import town_input

ROUTINE = input_routine(town_input())
SCORE_CATALOG = load_comparison_catalogs(
    versions={
        "society-person-score": 4,
        "society-comparison-protocol": 3,
        "society-comparison-seeds": 5,
    }
)
SCORE = society_score_v4.score(SCORE_CATALOG.score)
RELIABILITY = SCORE.reliability
NEEDS = tuple(sorted(ROUTINE.needs))[:2]
ACTIVITIES = tuple(sorted(ROUTINE.activities))[:2]


def _state(tick: int, *, first: int, second: int, action: str = "idle", moving: bool = False):
    thresholds = {key: ROUTINE.needs[key].threshold for key in NEEDS}
    return {
        "tick": tick,
        "routine": ROUTINE.binding(),
        "population": {"supported_needs": list(NEEDS)},
        "inhabitants": [
            {
                "id": "person-a",
                "needs": {
                    NEEDS[0]: thresholds[NEEDS[0]] + first,
                    NEEDS[1]: thresholds[NEEDS[1]] + second,
                },
                "motion_path_mm": [[0, 0], [1000, 0]] if moving else [[0, 0]],
                "goal": {"activity": ACTIVITIES[1]},
                "action": {"kind": action, "status": "active"},
            }
        ],
    }


def _terms(*states):
    return society_score_v4.run_terms(
        states, (), people=["person-a"], choice_points=0, routine=ROUTINE, score=RELIABILITY
    )


def test_all_supported_needs_contribute_in_recorded_catalog_units():
    one = _state(1, first=10, second=20)
    two = _state(2, first=30, second=40)
    terms = _terms(one, two)
    assert terms["need_thresholds"] == {key: ROUTINE.needs[key].threshold for key in NEEDS}
    assert terms["need_unit"] == society_score_v4.NEED_UNIT
    assert terms["urgency"] == 10 + 20 + 30 + 40
    assert society_score_v4.validate_terms(terms).urgency == 100
    # Changing only the second supported need changes urgency by exactly its own difference.
    changed = _terms(_state(1, first=10, second=25), two)
    assert changed["urgency"] - terms["urgency"] == 5


def test_a_selected_goal_or_travel_is_not_a_performed_activity():
    travel = _terms(_state(1, first=0, second=0, action="move", moving=True))
    assert travel["activities"] == {"person-a": 0}
    assert travel["person_minutes"]["walking"] == 1
    performed = _terms(_state(1, first=0, second=0, action=ACTIVITIES[0]))
    assert performed["activities"] == {"person-a": 1}
    assert performed["minutes_by_activity"] == {ACTIVITIES[0]: 1}


def test_the_same_seed_anchors_keep_the_third_scores_half_and_half_math():
    base = society_score_v2.RunTerms.from_document(_terms(_state(1, first=0, second=0)))
    waiting = replace(base, urgency=100, activities=(("person-a", 0),))
    routine = replace(base, urgency=40, activities=(("person-a", 2),))
    run = replace(base, urgency=70, activities=(("person-a", 1),))
    for value, expected in ((waiting, 0), (routine, 1), (run, Fraction(1, 2))):
        found = society_score_v3.seed_score(
            value, waiting=waiting, routine=routine, score=SCORE, floor_per_person=1
        )
        assert found.excluded is None and found.score == expected
    weak = replace(routine, urgency=99)
    assert (
        society_score_v3.seed_score(
            run, waiting=waiting, routine=weak, score=SCORE, floor_per_person=2
        ).excluded
        == society_score_v2.BELOW_FLOOR
    )
    no_variety = replace(routine, activities=(("person-a", 0),))
    assert (
        society_score_v3.seed_score(
            run, waiting=waiting, routine=no_variety, score=SCORE, floor_per_person=1
        ).excluded
        == society_score_v3.NO_VARIETY
    )


def test_missing_extra_or_changed_needs_and_term_identity_are_refused():
    state = _state(1, first=10, second=20)
    state["inhabitants"][0]["needs"].pop(NEEDS[1])
    with pytest.raises(ScoreRefused, match="living_needs_mismatch"):
        _terms(state)
    stated = _terms(_state(1, first=10, second=20))
    stated["need_thresholds"][NEEDS[0]] += 1
    with pytest.raises(ScoreRefused, match="living_terms_binding"):
        society_score_v4.validate_terms({**stated, "need_unit": "another_unit"})
