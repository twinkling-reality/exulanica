"""One run of a comparison, played and replayed through the real engine with no database.

``exulanica/world/society_comparison.py`` plays the same hour of a purposeful society with one arm
deciding for its people: their routine, waiting, or a model asked through the decision contract by
an asking port. A replay answers from the requests and receipts a run stored and takes no client
at all. These tests hold that a recorded run replays byte for byte, that a record differing from
what its run rebuilds is refused by name, that the waiting anchor is the wait a model may choose,
and that a person the rules leave nothing to offer is decided by the routine, as the host leaves
them.
"""

from __future__ import annotations

import dataclasses
import uuid
from copy import deepcopy

import pytest
from exulanica.world.society_comparison import (
    PlayedRun,
    ReplayMismatch,
    RunPlan,
    _wait_policy,
    play,
    replay,
)
from exulanica.world.society_decision_contract import (
    DecisionOption,
    decision_contract,
    option_goal_policy,
)
from exulanica.world.society_decisions import seal, validate_decision_request

import living_square_support as square

CONTRACT = decision_contract()
DOCUMENT = square.compose(square.square_objects())
SEED = "c3" * 32
TICKS = 30
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
    """A scripted model: the first option of the kind it is told, and the labels it is let offer."""

    def __init__(self, kind: str = "target", *, offer=None) -> None:
        self.kind = kind
        self.offer = offer
        self.asked = 0

    def offerable(self, tick, due):
        if self.offer is not None:
            return {subject: self.offer for subject in due}
        return {subject: frozenset(o.label for o in options) for subject, options in due.items()}

    def answers(self, requests):
        self.asked += len(requests)
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


def _plan(kind: str) -> RunPlan:
    return RunPlan(
        run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"play-test:{kind}"),
        society_id=square.SOCIETY,
        seed=SEED,
        population=8,
        inputs=(DOCUMENT,),
        ticks=TICKS,
        decider={"kind": kind},
        provider_config=CONFIG if kind == "model" else None,
        contract=CONTRACT,
    )


def _stored(played: PlayedRun) -> list[tuple[dict, dict]]:
    return list(zip(played.requests, played.receipts, strict=True))


@pytest.fixture(scope="module")
def recorded() -> PlayedRun:
    return play(_plan("model"), _Chooser())


def test_a_recorded_run_replays_byte_for_byte_from_what_it_stored(recorded):
    # The positive control: the model's people were asked, and their choices were applied.
    assert recorded.receipts
    assert any(
        event.document.get("disposition") == "applied"
        for event in recorded.events
        if event.kind == "decision_applied"
    )
    for request in recorded.requests:
        validate_decision_request(request)
    again = replay(_plan("model"), _stored(recorded), minute_digests=recorded.minute_digests)
    assert again.states == recorded.states
    assert again.events == recorded.events
    assert again.requests == recorded.requests
    assert again.receipts == recorded.receipts
    assert again.events_sha256 == recorded.events_sha256


def _resealed_receipt(receipt: dict, **fields) -> dict:
    changed = {**deepcopy(receipt), **fields}
    changed.pop("document_sha256")
    return seal(changed)


def test_a_stored_answer_another_than_its_run_s_is_refused_by_name(recorded):
    stored = _stored(recorded)
    index, (request, receipt) = next(
        (i, pair)
        for i, pair in enumerate(stored)
        if pair[1]["status"] == "accepted"
        and sum(1 for option in pair[0]["context"]["options"] if option["kind"] == "target") > 1
    )
    other = next(
        option
        for option in request["context"]["options"]
        if option["kind"] == "target" and option["label"] != receipt["proposal"]["label"]
    )
    forged = _resealed_receipt(receipt, proposal={"label": other["label"], "option": other})
    with pytest.raises(ReplayMismatch, match="run_replay_mismatch"):
        replay(
            _plan("model"),
            [*stored[:index], (request, forged), *stored[index + 1 :]],
            minute_digests=recorded.minute_digests,
        )


def test_a_minute_that_ends_in_another_state_is_refused_at_that_minute(recorded):
    digests = list(recorded.minute_digests)
    digests[7] = "0" * 64
    with pytest.raises(ReplayMismatch, match="at minute 8"):
        replay(_plan("model"), _stored(recorded), minute_digests=digests)


def test_a_missing_or_an_extra_stored_answer_is_refused(recorded):
    stored = _stored(recorded)
    # Without its first answer, the person it answered is offered nothing again and the routine
    # decides their turn, so the hour goes another way and a later request is not the stored one.
    with pytest.raises(ReplayMismatch, match="run_replay_mismatch"):
        replay(_plan("model"), stored[1:], minute_digests=recorded.minute_digests)
    request, receipt = stored[-1]
    extra_request = seal(
        {
            **{k: v for k, v in deepcopy(request).items() if k != "document_sha256"},
            "request_id": str(uuid.uuid4()),
            "base_tick": TICKS + 5,
        }
    )
    extra = _resealed_receipt(
        receipt,
        request_id=extra_request["request_id"],
        request_sha256=extra_request["document_sha256"],
        base_tick=TICKS + 5,
        decision_seq=len(stored) + 1,
    )
    with pytest.raises(ReplayMismatch):
        replay(
            _plan("model"),
            [*stored, (extra_request, extra)],
            minute_digests=recorded.minute_digests,
        )


def test_the_waiting_anchor_is_the_wait_a_model_may_choose(recorded):
    offered = next(
        option for option in recorded.requests[0]["context"]["options"] if option["kind"] == "wait"
    )
    # The anchor's policy is the one the wait option a model is offered applies.
    assert _wait_policy(CONTRACT) == option_goal_policy(DecisionOption.from_record(offered), None)
    waiting = play(_plan("wait"), _Chooser())
    chose_to_wait = play(_plan("model"), _Chooser("wait"))
    need = [[p["need_milli"] for p in state["inhabitants"]] for state in waiting.states]
    assert need == [
        [p["need_milli"] for p in state["inhabitants"]] for state in chose_to_wait.states
    ]
    assert all(
        person["action"]["reason"] == "validated_model_wait"
        for state in waiting.states
        for person in state["inhabitants"]
        if person["goal"] is None
    )


def test_people_the_rules_leave_nothing_to_offer_are_decided_by_their_routine():
    """A model arm whose workspace rules would change every place's words asks nobody, and its
    people's hour is the routine's, minute for minute, as the host leaves them."""
    silenced = _Chooser(offer=frozenset())
    unasked = play(_plan("model"), silenced)
    routine = play(_plan("routine"), _Chooser())
    assert silenced.asked == 0
    assert not unasked.receipts
    assert unasked.minute_digests == routine.minute_digests


def test_an_anchor_asks_nobody():
    for kind in ("routine", "wait"):
        chooser = _Chooser()
        played = play(_plan(kind), chooser)
        assert chooser.asked == 0
        assert not played.requests


def test_a_plan_states_its_decider_and_only_a_model_records_how_it_asks():
    with pytest.raises(ValueError, match="no decider"):
        dataclasses.replace(_plan("routine"), decider={"kind": "coin"})
    with pytest.raises(ValueError, match="exactly a model arm"):
        dataclasses.replace(_plan("routine"), provider_config=CONFIG)
    with pytest.raises(ValueError, match="exactly a model arm"):
        dataclasses.replace(_plan("model"), provider_config=None)
