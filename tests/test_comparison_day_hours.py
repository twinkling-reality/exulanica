"""A run longer than an hour is played, replayed and resumed one hour at a time, with no database.

``exulanica/world/society_comparison.py`` plays a day's run hour by hour, each hour on from the
state the hour before it ended in, numbering its receipts on from the last one before it. These
tests hold that the hours played in turn are the run played whole, minute for minute and receipt
for receipt, for a living town and for a purposeful society whose inputs change after its first;
that an hour replays from its start state and its stored receipts alone and is held to its record;
and that an hour a host stopped part way through goes on asking only the minutes it did not
record, while a stored request it does not rebuild stops it by name.
"""

from __future__ import annotations

import dataclasses
import uuid
from copy import deepcopy

import pytest
from exulanica.world.role_decisions import stored_through
from exulanica.world.society_comparison import (
    HOUR_TICKS,
    HourStart,
    PlayedRun,
    ReplayMismatch,
    RunPlan,
    first_hour,
    hours_of,
    play,
    play_hour,
    replay_hour,
    resume_hour,
)
from exulanica.world.society_decision_contract import decision_contract
from exulanica.world.society_living import LIVING_TOWN_PROFILE

import living_square_support as square
from living_town_support import town_input

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
MODEL = {"kind": "model", "provider": "nebius_token_factory", "model_id": "test/model"}


class _Choosing:
    """A scripted model choosing, for each request, the option its digest picks, counting what it
    is asked by minute."""

    def __init__(self) -> None:
        self.asked: list[int] = []

    def offerable(self, _tick, due):
        return {subject: frozenset(o.label for o in options) for subject, options in due.items()}

    def answers(self, requests):
        results = []
        for request in requests:
            self.asked.append(int(request["base_tick"]))
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


def _town_plan(ticks: int) -> RunPlan:
    source = town_input()
    return RunPlan(
        run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"day-hours:town:{ticks}"),
        society_id=uuid.uuid5(uuid.NAMESPACE_URL, "day-hours:town"),
        seed="day-hours-development",
        population=12,
        inputs=(source,),
        ticks=ticks,
        decider=MODEL,
        provider_config=CONFIG,
        contract=CONTRACT,
        engine_profile=LIVING_TOWN_PROFILE,
    )


def _square_plan(ticks: int) -> RunPlan:
    """The purposeful square over two inputs, the second an edit that took one object away: the
    minute that leaves the genesis consumes both, every later one the last alone."""
    objects = square.square_objects()
    first = square.compose(objects)
    second = square.compose(objects[:-1], input_seq=2, edit_seq=len(objects) + 1)
    return RunPlan(
        run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"day-hours:square:{ticks}"),
        society_id=square.SOCIETY,
        seed="c3" * 32,
        population=8,
        inputs=(first, second),
        ticks=ticks,
        decider=MODEL,
        provider_config=CONFIG,
        contract=CONTRACT,
    )


def _by_hours(plan: RunPlan) -> list[tuple[HourStart, PlayedRun]]:
    """Every hour of ``plan`` played in turn, each on from the state the hour before ended in."""
    start = first_hour(plan)
    hours = []
    for hour in range(hours_of(plan)):
        played = play_hour(plan, _Choosing(), start=start)
        hours.append((start, played))
        start = HourStart(hour + 1, played.states[-1], start.first_sequence + len(played.receipts))
    return hours


@pytest.mark.parametrize("make", [_town_plan, _square_plan], ids=["living-town", "purposeful"])
def test_a_run_played_hour_by_hour_is_the_run_played_whole(make):
    plan = make(3 * HOUR_TICKS)
    whole = play(plan, _Choosing())
    hours = _by_hours(plan)
    assert whole.receipts, "the run asks the model, so its receipts are numbered across hours"
    assert [d for _start, run in hours for d in run.minute_digests] == whole.minute_digests
    assert [r for _start, run in hours for r in run.receipts] == whole.receipts
    assert [r for _start, run in hours for r in run.requests] == whole.requests
    assert [e for _start, run in hours for e in run.events] == whole.events
    # Receipts are numbered on across hours, not from one in each.
    sequences = [r["decision_seq"] for _start, run in hours for r in run.receipts]
    assert sequences == list(range(1, len(sequences) + 1))
    assert any(run.receipts for _start, run in hours[1:])


def test_an_hour_replays_from_its_start_state_and_is_held_to_its_record():
    plan = _town_plan(2 * HOUR_TICKS)
    [_first, (start, played)] = _by_hours(plan)
    stored = list(zip(played.requests, played.receipts, strict=True))
    again = replay_hour(plan, stored, start=start, minute_digests=played.minute_digests)
    assert again.minute_digests == played.minute_digests
    assert again.receipts == played.receipts
    # A minute recorded in another state, a receipt changed, or receipts numbered from elsewhere:
    # each is refused by name, never shown.
    digests = list(played.minute_digests)
    digests[7] = "0" * 64
    with pytest.raises(ReplayMismatch, match="another state"):
        replay_hour(plan, stored, start=start, minute_digests=digests)
    tampered = deepcopy(stored)
    tampered[0][1]["document_sha256"] = "0" * 64
    with pytest.raises(ReplayMismatch, match="not the one its request rebuilds"):
        replay_hour(plan, tampered, start=start, minute_digests=played.minute_digests)
    shifted = dataclasses.replace(start, first_sequence=start.first_sequence + 1)
    with pytest.raises(ReplayMismatch):
        replay_hour(plan, stored, start=shifted, minute_digests=played.minute_digests)


def test_a_stopped_hour_goes_on_asking_only_the_minutes_it_did_not_record():
    plan = _town_plan(2 * HOUR_TICKS)
    [_first, (start, played)] = _by_hours(plan)
    asked_ticks = sorted({int(request["base_tick"]) for request in played.requests})
    assert len(asked_ticks) >= 4, "the hour asks in several minutes"
    # The host stopped after recording the minutes through the third one it asked in: whole
    # minutes, since a minute's receipts are recorded together.
    through = asked_ticks[2]
    stored = [
        (request, receipt)
        for request, receipt in zip(played.requests, played.receipts, strict=True)
        if int(request["base_tick"]) <= through
    ]
    assert stored_through(stored) == through
    live = _Choosing()
    resumed = resume_hour(plan, stored, live, start=start)
    assert resumed.minute_digests == played.minute_digests
    assert resumed.receipts == played.receipts
    # Nothing it recorded is asked again; every later minute that asks is asked live.
    assert live.asked and min(live.asked) > through
    assert sorted(set(live.asked)) == [tick for tick in asked_ticks if tick > through]


def _whole_minutes(played: PlayedRun, minutes: int) -> list:
    """The requests and receipts of an hour's first ``minutes`` minutes that asked anything."""
    asked = sorted({int(request["base_tick"]) for request in played.requests})[:minutes]
    return [
        deepcopy(pair)
        for pair in zip(played.requests, played.receipts, strict=True)
        if int(pair[0]["base_tick"]) in asked
    ]


def test_a_stopped_hour_whose_stored_records_it_does_not_rebuild_cannot_go_on():
    plan = _town_plan(2 * HOUR_TICKS)
    [_first, (start, played)] = _by_hours(plan)
    # A stored request the hour does not ask with the same bytes.
    stored = _whole_minutes(played, 2)
    stored[0][0]["context"]["options"] = stored[0][0]["context"]["options"][:-1]
    with pytest.raises(ReplayMismatch, match="not the one stored"):
        resume_hour(plan, stored, _Choosing(), start=start)
    # A stored receipt its request does not rebuild to the same bytes.
    stored = _whole_minutes(played, 2)
    stored[-1][1]["document_sha256"] = "0" * 64
    with pytest.raises(ReplayMismatch, match="not the one its request rebuilds"):
        resume_hour(plan, stored, _Choosing(), start=start)
    # A stored receipt no minute of the hour asks for: it is not the receipt the hour rebuilds in
    # its place.
    stored = _whole_minutes(played, 2)
    request, receipt = deepcopy(stored[0])
    request["subject_id"] = "not-a-person-of-this-run"
    receipt["request_id"] = request["request_id"] = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(ReplayMismatch, match="not the one its request rebuilds"):
        resume_hour(plan, [*stored, (request, receipt)], _Choosing(), start=start)


def test_an_hour_starts_at_its_own_first_minute_inside_the_window():
    plan = _town_plan(2 * HOUR_TICKS)
    start = first_hour(plan)
    with pytest.raises(ValueError, match="its own first minute"):
        play_hour(plan, _Choosing(), start=dataclasses.replace(start, hour=1))
    with pytest.raises(ValueError, match="hour_not_in_window"):
        play_hour(plan, _Choosing(), start=dataclasses.replace(start, hour=2))
    with pytest.raises(ValueError, match="whole number of hours"):
        hours_of(dataclasses.replace(plan, ticks=90))
