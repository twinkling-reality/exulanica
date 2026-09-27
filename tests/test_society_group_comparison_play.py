"""One group's model swapped while everybody else keeps theirs, played and replayed with no call.

A comparison's arm decides for its group; everybody outside it keeps the decider the comparison
froze for them, the model their world's owner chose or their routine, the same in every arm
(``exulanica/world/society_comparison.py``). These tests hold that a group arm asks for the group
and for the owner-chosen person outside it and for nobody else, that the anchors change only who
decides for the group, that a group arm's run replays byte for byte from what it stored while
asking nothing, that the run's loop counts each person's choice points as the routine's own rule
finds them, and that a plan naming somebody twice, or a wait outside the group, is refused.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections import Counter

import pytest
from exulanica.world.society_comparison import RunPlan, genesis, play, replay
from exulanica.world.society_decision_contract import at_choice_point, decision_contract

import living_square_support as square

CONTRACT = decision_contract()
DOCUMENT = square.compose(square.square_objects())
SEED = "a7" * 32
TICKS = 40


def _config(model_id: str, choice_seq: int | None) -> dict:
    return {
        "provider": "nebius_token_factory",
        "model_id": model_id,
        "mechanism": "tool_call",
        "choice_seq": choice_seq,
        "manifest_sha256": "0" * 64,
        "prompt_version": "society-person-choice/v1",
        "contract": CONTRACT.binding(),
        "deadline_ms": 20_000,
    }


ARM_MODEL = "test/arm-model"
OWNER_MODEL = "test/owner-model"
PEOPLE = sorted(
    person["id"]
    for person in genesis(
        RunPlan(
            run_id=uuid.uuid5(uuid.NAMESPACE_URL, "group-play:people"),
            society_id=square.SOCIETY,
            seed=SEED,
            population=8,
            inputs=(DOCUMENT,),
            ticks=1,
            decider={"kind": "routine"},
            provider_config=None,
            contract=CONTRACT,
        )
    )["inhabitants"]
)
#: The group: the first half of the square's people by identity.
GROUP = frozenset(PEOPLE[:4])
#: Outside it, one person whose world's owner chose a model; everybody else on their routine.
OWNER_CHOSE = PEOPLE[4]
OTHERS = {
    OWNER_CHOSE: {
        "decider": {"kind": "model", "provider": "nebius_token_factory", "model_id": OWNER_MODEL},
        "provider_config": _config(OWNER_MODEL, 3),
    },
    **{
        subject: {"decider": {"kind": "routine"}, "provider_config": None} for subject in PEOPLE[5:]
    },
}


class _Chooser:
    """A scripted model for every model a run asks: the first place offered, and it counts who it
    was asked for and by which model."""

    def __init__(self) -> None:
        self.asked: Counter[tuple[str, str]] = Counter()

    def offerable(self, tick, due):
        return {subject: frozenset(o.label for o in options) for subject, options in due.items()}

    def answers(self, requests):
        results = []
        for request in requests:
            self.asked[(request["subject_id"], request["provider_config"]["model_id"])] += 1
            option = next(o for o in request["context"]["options"] if o["kind"] == "target")
            results.append(
                {
                    "status": "accepted",
                    "reason": "validated_choice",
                    "proposal": {"label": option["label"], "option": option},
                    "provider": None,
                }
            )
        return results


class _Refusing:
    """An asking that fails any test that reaches it: a replay asks nothing."""

    def offerable(self, tick, due):
        raise AssertionError("a replay asks nobody")

    def answers(self, requests):
        raise AssertionError("a replay asks nobody")


def _plan(kind: str) -> RunPlan:
    decider = (
        {"kind": "model", "provider": "nebius_token_factory", "model_id": ARM_MODEL}
        if kind == "model"
        else {"kind": kind}
    )
    return RunPlan(
        run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"group-play:{kind}"),
        society_id=square.SOCIETY,
        seed=SEED,
        population=8,
        inputs=(DOCUMENT,),
        ticks=TICKS,
        decider=decider,
        provider_config=_config(ARM_MODEL, None) if kind == "model" else None,
        contract=CONTRACT,
        group=GROUP,
        others=OTHERS,
    )


@pytest.fixture(scope="module")
def recorded():
    chooser = _Chooser()
    return play(_plan("model"), chooser), chooser


def test_a_group_arm_asks_its_model_for_the_group_and_the_owners_for_the_person_they_chose(
    recorded,
):
    played, chooser = recorded
    asked_for = {subject for subject, _model in chooser.asked}
    # The positive control: the group and the owner-chosen person were both asked.
    assert asked_for & GROUP and OWNER_CHOSE in asked_for
    assert asked_for <= GROUP | {OWNER_CHOSE}
    for subject, model in chooser.asked:
        assert model == (ARM_MODEL if subject in GROUP else OWNER_MODEL)
    for request in played.requests:
        expected = ARM_MODEL if request["subject_id"] in GROUP else OWNER_MODEL
        assert request["provider_config"]["model_id"] == expected
        # The owner's choice is named in what its requests record; the arm's is nobody's choice.
        assert request["provider_config"]["choice_seq"] == (
            None if request["subject_id"] in GROUP else 3
        )


def test_a_group_arm_replays_byte_for_byte_from_what_it_stored_asking_nothing(recorded):
    played, _chooser = recorded
    stored = list(zip(played.requests, played.receipts, strict=True))
    again = replay(_plan("model"), stored, minute_digests=played.minute_digests)
    assert again.states == played.states
    assert again.events == played.events
    assert again.requests == played.requests
    assert again.receipts == played.receipts
    assert again.events_sha256 == played.events_sha256
    assert again.choice_points == played.choice_points


def test_the_waiting_anchor_changes_only_who_decides_for_the_group():
    """Under the waiting anchor the group waits at every choice point, and the person the owner
    chose a model for is asked exactly as under the model arm's first minute."""
    chooser = _Chooser()
    waited = play(_plan("wait"), chooser)
    assert {subject for subject, _model in chooser.asked} == {OWNER_CHOSE}
    waiting_group = [
        person
        for state in waited.states
        for person in state["inhabitants"]
        if person["id"] in GROUP and person["goal"] is None
    ]
    assert waiting_group, "the positive control: the group had turns to wait"
    assert all(person["action"]["reason"] == "validated_model_wait" for person in waiting_group)
    routine = play(_plan("routine"), _Chooser())
    assert {r["subject_id"] for r in routine.requests} == {OWNER_CHOSE}


def test_the_loop_counts_each_persons_choice_points_as_the_routine_finds_them(recorded):
    played, _chooser = recorded
    # Derived here from the states, by the routine's own predicate, not by the loop's count.
    found: Counter[str] = Counter()
    for state in (played.start, *played.states[:-1]):
        found.update(person["id"] for person in state["inhabitants"] if at_choice_point(person))
    assert found == played.choice_points
    assert sum(played.choice_points[subject] for subject in GROUP) > 0


def test_a_plan_names_each_person_once_and_nobody_outside_the_group_waits():
    with pytest.raises(ValueError, match="outside the group is not also in it"):
        dataclasses.replace(
            _plan("routine"),
            others={PEOPLE[0]: {"decider": {"kind": "routine"}, "provider_config": None}},
        )
    with pytest.raises(ValueError, match="no decider 'wait'"):
        dataclasses.replace(
            _plan("routine"),
            others={PEOPLE[5]: {"decider": {"kind": "wait"}, "provider_config": None}},
        )
    with pytest.raises(ValueError, match="exactly a model person"):
        dataclasses.replace(
            _plan("routine"),
            others={
                PEOPLE[5]: {
                    "decider": {"kind": "model", "provider": "p", "model_id": "m"},
                    "provider_config": None,
                }
            },
        )
    with pytest.raises(ValueError, match="at least one person"):
        dataclasses.replace(_plan("routine"), group=frozenset(), others={})


def test_a_person_outside_the_group_nobody_chose_for_follows_their_routine():
    plan = dataclasses.replace(_plan("wait"), others={})
    assert plan.decider_for(PEOPLE[6]) == ({"kind": "routine"}, None)
    assert plan.decider_for(PEOPLE[0]) == ({"kind": "wait"}, None)
    assert dataclasses.replace(plan, group=None).decider_for(PEOPLE[6]) == ({"kind": "wait"}, None)
