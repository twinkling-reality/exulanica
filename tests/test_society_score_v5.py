"""A day's terms, assembled from its hours, are the fourth score's over the whole day.

``exulanica/world/society_score_v5.py`` keeps an hour's fourth-score terms with each scored
person's kinds, and unites a day's: every count summed, each person's kinds counted once in the
day. These tests hold the assembly to the fourth score's terms over every minute at once, on a
living town's run that a model decided for and on its routine; that the union is what makes them
equal, since the same kind in two hours counts once; that an hour whose kinds are not the ones it
counted, or a day whose hours score other people, is refused by name; and that the fifth catalog
is the fourth's weights and classes exactly.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from exulanica.world import society_score_v4, society_score_v5
from exulanica.world.society_catalogs import load_comparison_catalogs
from exulanica.world.society_comparison import HOUR_TICKS, HourStart, RunPlan, first_hour, play_hour
from exulanica.world.society_decision_contract import decision_contract
from exulanica.world.society_living import LIVING_TOWN_PROFILE, input_routine
from exulanica.world.society_score import ScoreRefused

from living_town_support import town_input

CONTRACT = decision_contract()
SOURCE = town_input()
ROUTINE = input_routine(SOURCE)
HOURS = 4
DAY_CATALOGS = load_comparison_catalogs(
    versions={
        "society-person-score": 5,
        "society-comparison-protocol": 3,
        "society-comparison-seeds": 5,
    }
)
FOURTH_CATALOGS = load_comparison_catalogs(
    versions={
        "society-person-score": 4,
        "society-comparison-protocol": 3,
        "society-comparison-seeds": 5,
    }
)
SCORE = society_score_v5.score(DAY_CATALOGS.score).reliability


class _Choosing:
    def offerable(self, _tick, due):
        return {subject: frozenset(o.label for o in options) for subject, options in due.items()}

    def answers(self, requests):
        results = []
        for request in requests:
            options = request["context"]["options"]
            option = options[int(request["document_sha256"][:8], 16) % len(options)]
            results.append(
                {
                    "status": "accepted",
                    "reason": "validated_choice",
                    "proposal": {"label": option["label"], "option": option},
                    "provider": None,
                }
            )
        return results


class _Nobody:
    def offerable(self, _tick, _due):
        raise AssertionError("the routine asks nobody")

    def answers(self, _requests):
        raise AssertionError("the routine asks nobody")


def _played(kind: str):
    """Every hour of a four-hour run of a living town, a model deciding for its first six people
    or the routine for everybody, each hour's states and events, and the people it scores."""
    decider = (
        {"kind": "model", "provider": "nebius_token_factory", "model_id": "test/model"}
        if kind == "model"
        else {"kind": "routine"}
    )
    plan = RunPlan(
        run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"score-v5:{kind}"),
        society_id=uuid.uuid5(uuid.NAMESPACE_URL, "score-v5"),
        seed="score-v5-development",
        population=12,
        inputs=(SOURCE,),
        ticks=HOURS * HOUR_TICKS,
        decider=decider,
        provider_config=(
            {
                "provider": "nebius_token_factory",
                "model_id": "test/model",
                "mechanism": "tool_call",
                "choice_seq": None,
                "manifest_sha256": "0" * 64,
                "prompt_version": "society-person-choice/v1",
                "contract": CONTRACT.binding(),
                "deadline_ms": 20_000,
            }
            if kind == "model"
            else None
        ),
        contract=CONTRACT,
        engine_profile=LIVING_TOWN_PROFILE,
    )
    everybody = sorted(person["id"] for person in first_hour(plan).state["inhabitants"])
    group = everybody[:6] if kind == "model" else everybody
    if kind == "model":
        plan = dataclasses.replace(plan, group=frozenset(group))
    start = first_hour(plan)
    hours = []
    for hour in range(HOURS):
        played = play_hour(plan, _Choosing() if kind == "model" else _Nobody(), start=start)
        hours.append(played)
        start = HourStart(hour + 1, played.states[-1], start.first_sequence + len(played.receipts))
    return hours, group


@pytest.mark.parametrize("kind", ["model", "routine"])
def test_a_days_terms_assembled_from_its_hours_are_the_fourth_scores_over_every_minute(kind):
    hours, people = _played(kind)
    assembled = society_score_v5.day_terms(
        [
            society_score_v5.hour_terms(
                played.states,
                played.events,
                people=people,
                choice_points=sum(played.choice_points[p] for p in people),
                routine=ROUTINE,
                score=SCORE,
            )
            for played in hours
        ]
    )
    whole = society_score_v4.run_terms(
        [state for played in hours for state in played.states],
        [event for played in hours for event in played.events],
        people=people,
        choice_points=sum(played.choice_points[p] for played in hours for p in people),
        routine=ROUTINE,
        score=society_score_v4.score(FOURTH_CATALOGS.score).reliability,
    )
    assert assembled == whole
    assert assembled["ticks"] == HOURS * HOUR_TICKS
    society_score_v5.validate_terms(assembled)


def test_a_kind_done_in_two_hours_counts_once_in_the_day():
    hours, people = _played("routine")
    terms = [
        society_score_v5.hour_terms(
            played.states,
            played.events,
            people=people,
            choice_points=sum(played.choice_points[p] for p in people),
            routine=ROUTINE,
            score=SCORE,
        )
        for played in hours
    ]
    day = society_score_v5.day_terms(terms)
    summed = sum(sum(hour["activities"].values()) for hour in terms)
    # The positive control: these hours repeat kinds, so a day that summed its hours' counts would
    # count more than the day's own variety.
    assert sum(day["activities"].values()) < summed
    for subject in people:
        united = set().union(*(set(hour[society_score_v5.KINDS][subject]) for hour in terms))
        assert day["activities"][subject] == len(united)


def test_an_hour_whose_kinds_are_not_the_ones_it_counted_is_refused(monkeypatch):
    hours, people = _played("routine")
    played = hours[1]
    real = society_score_v5._kinds

    def fewer(states, members, routine):
        found = real(states, members, routine)
        subject = next(subject for subject, held in found.items() if held)
        found[subject] = set(sorted(found[subject])[1:])
        return found

    monkeypatch.setattr(society_score_v5, "_kinds", fewer)
    with pytest.raises(ScoreRefused, match="hour_kinds_not_counted"):
        society_score_v5.hour_terms(
            played.states,
            played.events,
            people=people,
            choice_points=0,
            routine=ROUTINE,
            score=SCORE,
        )


def test_a_day_whose_hours_score_other_people_is_refused():
    hours, people = _played("routine")
    terms = [
        society_score_v5.hour_terms(
            played.states,
            played.events,
            people=group,
            choice_points=0,
            routine=ROUTINE,
            score=SCORE,
        )
        for played, group in ((hours[0], people), (hours[1], people[:-1]))
    ]
    with pytest.raises(ScoreRefused, match="day_hours_differ"):
        society_score_v5.day_terms(terms)
    # The same people under another need's threshold: an hour scored another way.
    same = terms[0]
    other = {**same, "need_thresholds": {**same["need_thresholds"], "sleep": 1}}
    with pytest.raises(ScoreRefused, match="day_hours_differ"):
        society_score_v5.day_terms([same, other])
    with pytest.raises(ScoreRefused, match="no_minutes"):
        society_score_v5.day_terms([])


def test_the_fifth_catalog_is_the_fourths_weights_and_classes_exactly():
    fifth = DAY_CATALOGS.score
    fourth = FOURTH_CATALOGS.score
    assert set(fifth) == set(fourth)
    for key, entry in fifth.items():
        assert {name: value for name, value in entry.items() if name != "reason"} == {
            name: value for name, value in fourth[key].items() if name != "reason"
        }
    assert society_score_v5.score(fifth) == society_score_v4.score(fourth)
