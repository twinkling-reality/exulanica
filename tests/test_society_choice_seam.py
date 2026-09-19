"""The seam between the living society's rule and anything else allowed to answer a choice.

Pure fixtures. No database, no network, no provider: every model here is a stub written in this
file, so nothing in this module can reach an endpoint even if one were configured.

The controls matter more than the features, and they are the first four tests. A seam that
quietly changed the society would be a finding before any experiment ran, and a seam nothing
reaches would let every other test in this file pass without proving anything.
"""

from __future__ import annotations

import json

import pytest
from exulanica.world.society import society_state_sha256
from exulanica.world.society_choice import (
    MODEL,
    RULE,
    ChoiceAnswer,
    ChoiceCounters,
    DeterministicChoices,
    ModelChoices,
    RecordedChoices,
)
from exulanica.world.society_living import (
    LivingPlace,
    advance_living_society,
    initial_living_society,
)
from exulanica.world.society_place import place_from_society_input

from society_living_fixtures import GRID_SOCIETY, grid_input, grid_place, routine

SEED = "5e" * 32

# Measured on main 15e8198c, BEFORE this seam existed, by
# `python -m scripts.record_living_society --ticks 180`, which uses the committed Flatiron
# district. The recording's frame 180 carries this digest. It is pinned here rather than
# recomputed because a value this file produced from the code this file tests could not
# contradict it: the point of the number is that it came from the tree without the seam.
PRE_SEAM_FLATIRON_TICK_180 = "cef36ee95a7c99359bf882b323e709c2dc219575e97ccd0fdb4dec496d2e898c"
PRE_SEAM_FLATIRON_TICK_12 = "c5c3d35c415755ad1503d88c0f0c28238b84dc6e67e115bac026e79bdf8d88b4"


class Raises:
    """A provider that is unreachable in the harshest way available: it raises on every call."""

    records = True

    def __init__(self) -> None:
        self.calls = 0

    def answer(self, questions):
        self.calls += 1
        raise ConnectionError("no route to the provider")


class Answers:
    """Answers with the LAST option the rule would rank, so taking it is visible in the state."""

    def __init__(self, confidence_milli: int) -> None:
        self.confidence_milli = confidence_milli
        self.seen: list[dict] = []

    def answer(self, questions):
        out = {}
        for index, question in enumerate(questions):
            self.seen.append(question.payload())
            keys = question.option_keys
            if keys:
                out[index] = ChoiceAnswer(keys[-1], self.confidence_milli)
        return out


class Invents:
    """Answers with an option key that is not in the closed set."""

    def answer(self, questions):
        return {index: ChoiceAnswer("no-such-option", 1000) for index in range(len(questions))}


def _society(place_document=None):
    place = LivingPlace(place_document or grid_place(), routine())
    state = initial_living_society(
        GRID_SOCIETY, SEED, place, routine(), branch_id=str(grid_input()["version_id"])
    )
    return state, place


def _world(state):
    """The state with the event identifiers stripped: where everybody is and what they are doing.

    ``memory`` and ``explanation.event_ids`` name the events of this run. A run that consulted a
    provider writes who was asked into those events, so their identifiers differ from a run that
    consulted nothing even when every person did exactly the same thing. Stripping them is how a
    claim about BEHAVIOUR is separated from a claim about the record, and
    ``test_an_unreachable_provider_is_visible_in_the_record_and_nowhere_else`` pins that the two
    identifier fields are the only things that differ.
    """
    return {
        **state,
        "inhabitants": [{**p, "memory": None, "explanation": None} for p in state["inhabitants"]],
    }


def _run(ticks: int, choices=None, place_document=None):
    state, place = _society(place_document)
    events = []
    for _ in range(ticks):
        state, produced = advance_living_society(state, SEED, [place], routine(), choices)
        events.extend(produced)
    return state, events


def _flatiron_run(ticks: int, choices=None):
    """The recorder's own society, built with the recorder's own identity, seed and input.

    Every constant comes from ``scripts.record_living_society`` rather than being retyped, so
    this reproduces the recording the pinned digests above were read from, or it fails.
    """
    from scripts.record_living_society import SEED as RECORDER_SEED
    from scripts.record_living_society import SOCIETY_ID, flatiron_input

    document = flatiron_input()
    place_document = place_from_society_input(document, routine())
    place = LivingPlace(place_document, routine())
    state = initial_living_society(
        SOCIETY_ID, RECORDER_SEED, place, routine(), branch_id=document["version_id"]
    )
    digests = [society_state_sha256(state)]
    for _ in range(ticks):
        state, _events = advance_living_society(state, RECORDER_SEED, [place], routine(), choices)
        digests.append(society_state_sha256(state))
    return digests


# --- the controls -------------------------------------------------------------------------


def test_the_rule_alone_reproduces_the_tree_that_had_no_seam():
    """The positive control. The digests come from a recording made before this module existed."""
    digests = _flatiron_run(180)
    assert digests[12] == PRE_SEAM_FLATIRON_TICK_12
    assert digests[180] == PRE_SEAM_FLATIRON_TICK_180


def test_the_engine_actually_reaches_the_seam():
    """Break the call, not the callee. A source that raises must take the whole tick down.

    Without this, every other test here could pass against an engine that never consulted the
    seam at all, and the positive control above would be the loudest of the false positives.
    """

    class Explodes:
        records = False

        def decide(self, question, deterministic):
            raise AssertionError("the seam was reached")

    with pytest.raises(AssertionError, match="the seam was reached"):
        _run(1, Explodes())


def test_the_rule_answers_every_choice_when_no_provider_is_configured():
    counters = ChoiceCounters()
    _run(60, DeterministicChoices(counters))
    assert counters.asked > 0
    assert counters.fallback == counters.asked
    assert counters.not_the_rule == 0
    assert counters.below_threshold == 0


def test_a_provider_that_raises_changes_nothing_about_the_world():
    """Nothing is load bearing on the model: an unreachable one leaves today's world exactly."""
    provider = Raises()
    counters = ChoiceCounters()
    with_provider, _ = _run(60, ModelChoices(provider, 1, counters))
    without, _ = _run(60, DeterministicChoices())
    assert provider.calls > 0
    assert counters.not_the_rule == 0
    assert counters.provider_silent == counters.asked
    assert society_state_sha256(_world(with_provider)) == society_state_sha256(_world(without))


def test_an_unreachable_provider_is_visible_in_the_record_and_nowhere_else():
    """What an outage costs, stated rather than assumed: two identifier fields, and nothing else.

    A provider that raises leaves every position, goal, action, need and route identical, and
    changes only the identifiers of the events that say it was asked. That is the property the
    caution wants, the right way round: an outage is recorded, and it is not hidden.
    """
    with_provider, _ = _run(60, ModelChoices(Raises(), 1))
    without, _ = _run(60, DeterministicChoices())
    assert society_state_sha256(with_provider) != society_state_sha256(without)
    differing = set()
    for left, right in zip(with_provider["inhabitants"], without["inhabitants"], strict=True):
        differing |= {key for key in left if left[key] != right[key]}
    assert differing == {"memory", "explanation"}
    assert with_provider["tick"] == without["tick"]


# --- the threshold ------------------------------------------------------------------------


def test_an_answer_above_the_bar_is_taken_and_moves_the_world():
    counters = ChoiceCounters()
    taken, _ = _run(60, ModelChoices(Answers(1000), 900, counters))
    ruled, _ = _run(60, DeterministicChoices())
    assert counters.not_the_rule > 0
    assert counters.not_the_rule + counters.fallback == counters.asked
    # If the stub answered with the rule's own pick this assertion could not fail, so the stub
    # answers with the last-ranked option instead and the states must differ.
    assert society_state_sha256(_world(taken)) != society_state_sha256(_world(ruled))


def test_an_answer_below_the_bar_falls_through_to_the_rule():
    counters = ChoiceCounters()
    below, _ = _run(60, ModelChoices(Answers(899), 900, counters))
    assert counters.answered_outside_the_set == 0
    ruled, _ = _run(60, DeterministicChoices())
    assert counters.asked > 0
    assert counters.not_the_rule == 0
    assert counters.below_threshold == counters.asked
    assert society_state_sha256(_world(below)) == society_state_sha256(_world(ruled))


def test_the_bar_starts_nearly_closed():
    """At 1000 the model must be certain. A stub one milli short decides nothing at all."""
    counters = ChoiceCounters()
    _run(30, ModelChoices(Answers(999), 1000, counters))
    assert counters.asked > 0
    assert counters.not_the_rule == 0


def test_an_answer_outside_the_closed_set_is_refused_not_repaired():
    counters = ChoiceCounters()
    invented, _ = _run(30, ModelChoices(Invents(), 0, counters))
    ruled, _ = _run(30, DeterministicChoices())
    assert counters.asked > 0
    assert counters.not_the_rule == 0
    assert society_state_sha256(_world(invented)) == society_state_sha256(_world(ruled))
    # An answer outside the set and an answer below the bar are different failures, and a run
    # that reported only "the model did not decide" could not tell an operator which is happening.
    assert counters.answered_outside_the_set == counters.asked
    assert counters.below_threshold == 0
    assert counters.provider_silent == 0


def test_the_threshold_is_bounded():
    with pytest.raises(ValueError, match="threshold"):
        ModelChoices(Answers(1000), 1001)
    with pytest.raises(ValueError, match="confidence"):
        ChoiceAnswer("k", 1001)


# --- the record ---------------------------------------------------------------------------


def test_a_model_run_records_who_chose_every_time_including_the_fallen_through():
    _state, events = _run(40, ModelChoices(Answers(500), 400))
    selected = [e for e in events if e.kind == "goal_selected"]
    assert selected
    assert all("decision" in e.document for e in selected)
    assert {e.document["decision"]["decided_by"] for e in selected} == {MODEL}
    _state, mixed = _run(40, ModelChoices(Answers(500), 600))
    selected = [e for e in mixed if e.kind == "goal_selected"]
    assert selected
    assert all(e.document["decision"]["decided_by"] == RULE for e in selected)
    assert all(e.document["decision"]["rejected_confidence_milli"] == 500 for e in selected)


def test_a_rule_run_records_nothing_new_so_stored_histories_keep_verifying():
    _state, events = _run(40, DeterministicChoices())
    selected = [e for e in events if e.kind == "goal_selected"]
    assert selected
    assert all("decision" not in e.document for e in selected)


def test_a_replay_reproduces_the_live_session_and_never_calls_a_provider():
    provider = Answers(1000)
    live_state, live_events = _run(40, ModelChoices(provider, 900))
    recorded = tuple(e.document["decision"] for e in live_events if e.kind == "goal_selected")
    assert recorded
    calls_before = len(provider.seen)
    replay_state, replay_events = _run(40, RecordedChoices(recorded))
    assert len(provider.seen) == calls_before
    assert society_state_sha256(replay_state) == society_state_sha256(live_state)
    assert [e.event_id for e in replay_events] == [e.event_id for e in live_events]


def test_a_replay_holds_no_provider_at_all():
    """A replay cannot call a model because it has nothing to call. Not a flag: no field."""
    assert "provider" not in {f for f in RecordedChoices(()).__dataclass_fields__}


def test_a_replay_refuses_a_record_that_does_not_fit_this_place():
    _state, live = _run(20, ModelChoices(Answers(1000), 900))
    recorded = [e.document["decision"] for e in live if e.kind == "goal_selected"]
    recorded[0] = {**recorded[0], "option_key": "district:nowhere:visit|"}
    with pytest.raises(ValueError, match="not offered by this place"):
        _run(20, RecordedChoices(tuple(recorded)))


def test_a_replay_refuses_a_record_that_runs_out():
    _state, live = _run(20, ModelChoices(Answers(1000), 900))
    recorded = [e.document["decision"] for e in live if e.kind == "goal_selected"]
    with pytest.raises(ValueError, match="fewer decisions"):
        _run(20, RecordedChoices(tuple(recorded[:2])))


# --- what a provider may see ----------------------------------------------------------------


def test_a_provider_is_shown_generated_world_state_and_nothing_else():
    provider = Answers(1000)
    _run(5, ModelChoices(provider, 1000))
    assert provider.seen
    for payload in provider.seen:
        # Serialisable at all, which the engine objects in `outcome` are not.
        json.dumps(payload)
        assert set(payload) == {
            "subject_ordinal",
            "tick",
            "minute_of_day",
            "day",
            "needs",
            "options",
        }
        for option in payload["options"]:
            assert "outcome" not in option
            assert set(option) <= {
                "option_key",
                "activity",
                "destination_id",
                "spot_id",
                "cost_mm",
                "load_milli",
                "urgency",
                "because",
            }


def test_the_counters_name_five_different_sets():
    counters = ChoiceCounters()
    _run(40, ModelChoices(Answers(700), 600, counters))
    assert counters.asked == counters.not_the_rule + counters.fallback
    assert counters.asked == (
        sum(counters.by_destination.values())
        + counters.without_destination
        + counters.nothing_possible
    )


# --- what a better chooser could win, which is the experiment's premise ----------------------


def test_the_four_flatiron_destinations_leave_almost_nothing_for_a_chooser_to_win():
    """The premise, measured. This is the test that should fail when the premise reopens.

    A destination whose visitor capacity is one can be held by one person in one tick, so
    capacity times ticks is every person-tick of destination occupancy that exists to be won.
    On the committed Flatiron place the deterministic chooser already takes about 98% of it, and
    what is left is under one part in a thousand of the population's time. No chooser, model or
    otherwise, can win what is not there.

    If a lane gives this place more destinations or more room, the headroom grows and this test
    fails. That is the point of it: the finding stops being true and somebody is told.
    """
    from scripts.measure_society_choice import measure, occupancy

    run = measure("6b" * 32, 1440)
    assert run["people"] == 46
    assert len(run["destinations"]) == 4
    assert set(run["destination_capacity"].values()) == {1}
    row = occupancy([run])["per_run"][0]
    assert row["ceiling_person_ticks"] == 4 * 1440
    assert row["headroom_person_ticks"] < row["ceiling_person_ticks"] // 40
    assert row["headroom_share_of_person_ticks_milli"] <= 1
    assert run["distinct_positions_final_tick"] == run["people"]
