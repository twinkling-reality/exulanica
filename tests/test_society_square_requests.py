"""A person asked to go somewhere is heard during a stay under the newest routine.

Stays under the newest routine last up to twenty-five simulated minutes, so a request refused while
somebody sits would be refused most of the time. Under that routine a direct request ends the stay
under way in the minute the request is consumed, with the reason ``called_away``, and a talk ends
for both people in that same minute, even when the other is still walking over. Asked to go where
they already are, doing it now, a person is refused by name. Under the rules the society was
released with, which every stored input that records no routine is read under, a request during a
stay is refused exactly as it always was.
"""

from __future__ import annotations

import uuid
from copy import deepcopy

import pytest
from exulanica.world.society import society_state_sha256
from exulanica.world.society_actions import (
    ACTION_REQUEST_PROFILE,
    ActionIntent,
    action_goal_policies,
    action_request_sha256,
    advance_directed_purposeful_society,
    build_action_request,
)
from exulanica.world.society_planner import advance_purposeful_society, initial_purposeful_society

import living_square_support as square

ACTOR = uuid.UUID(int=7)


def _until(document: dict, seed: str, found) -> tuple[dict, object]:
    """The first minute of a square society that ``found`` picks something out of."""
    state = initial_purposeful_society(square.SOCIETY, seed, document, population=8)
    for _ in range(240):
        state, _ = advance_purposeful_society(state, seed, [document])
        picked = found(state)
        if picked is not None:
            return state, picked
    raise AssertionError("no minute had what the test looks for")


def _resting(state: dict) -> dict | None:
    return next(
        (
            person
            for person in state["inhabitants"]
            if person["action"]["kind"] == "rest"
            and person["action"]["status"] == "active"
            and person["action"]["remaining_ticks"] >= 2
        ),
        None,
    )


def _envelope(state: dict, document: dict, subject: str, target: dict) -> dict:
    """A request as the routes record it, before anything decides whether it applies."""
    request = {
        "profile": ACTION_REQUEST_PROFILE,
        "request_id": str(
            uuid.uuid5(square.SOCIETY, f"{state['tick']}:{subject}:{target['target_id']}")
        ),
        "requested_by": str(ACTOR),
        "subject_id": subject,
        "branch_id": state["branch_id"],
        "base_tick": state["tick"],
        "base_state_sha256": society_state_sha256(state),
        "input_seq": document["input_seq"],
        "input_sha256": document["document_sha256"],
        "intent": {"kind": "go_to", "target_id": target["target_id"]},
        "target": deepcopy(target),
    }
    request["document_sha256"] = action_request_sha256(request)
    return request


def _elsewhere(state: dict, document: dict, person: dict) -> dict:
    """A request sending ``person`` to the first other activity with a place free for them."""
    for target in document["targets"]:
        if target["target_id"] == (person["target"] or {}).get("target_id"):
            continue
        try:
            return build_action_request(
                state,
                document,
                request_id=uuid.uuid5(square.SOCIETY, f"{state['tick']}:{target['target_id']}"),
                requested_by=ACTOR,
                subject_id=uuid.UUID(person["id"]),
                intent=ActionIntent("go_to", target["target_id"]),
            )
        except ValueError as refused:
            assert str(refused) == "destination_full"
    raise AssertionError("every other activity is full")


def _mine(state: dict, person: dict) -> dict:
    return next(held for held in state["inhabitants"] if held["id"] == person["id"])


def test_a_request_ends_a_stay_under_the_newest_routine_in_the_minute_it_is_consumed():
    document = square.compose(square.square_objects())
    seed = square.DEVELOPMENT_SEEDS[9]
    state, person = _until(document, seed, _resting)
    request = _elsewhere(state, document, person)
    advanced, events, dispositions = advance_directed_purposeful_society(
        state, seed, [document], [request]
    )
    assert [(held.disposition, held.reason) for held in dispositions] == [
        ("applied", "validated_user_target")
    ]
    ended = [
        event
        for event in events
        if str(event.subject_id) == person["id"] and event.kind == "replanned"
    ]
    assert [(event.tick, event.document["reason"]) for event in ended] == [
        (state["tick"] + 1, "called_away")
    ]
    assert ended[0].document["action"] == {
        **person["action"],
        "status": "completed",
        "reason": "called_away",
    }
    after = _mine(advanced, person)
    assert after["goal"]["target_id"] == request["target"]["target_id"]
    assert after["goal"]["reason"] == "remembered_target_selected"
    # Left part way, the stay relieved nothing.
    assert after["need_milli"] == min(1000, person["need_milli"] + 1)
    # The same request replays to the same minute.
    assert advance_directed_purposeful_society(deepcopy(state), seed, [document], [request]) == (
        advanced,
        events,
        dispositions,
    )


def _talking(state: dict) -> tuple[dict, dict] | None:
    people = {person["id"]: person for person in state["inhabitants"]}
    for person in state["inhabitants"]:
        action = person["action"]
        if (
            action["kind"] == "talk"
            and action["status"] == "active"
            and action["reason"] == "talking"
            and action["remaining_ticks"] >= 2
        ):
            other = people[person["goal"]["partner_id"]]
            return tuple(sorted((person, other), key=lambda held: held["ordinal"]))
    return None


@pytest.mark.parametrize("asked", [0, 1], ids=["lower-ordinal-asked", "higher-ordinal-asked"])
def test_a_talk_ends_for_both_in_the_minute_one_of_them_is_asked_elsewhere(asked):
    """Whichever of the two the minute reaches first, the one not asked stops in that minute."""
    document = square.compose(square.square_objects())
    seed = square.DEVELOPMENT_SEEDS[10]
    state, pair = _until(document, seed, _talking)
    person, other = pair[asked], pair[1 - asked]
    request = _elsewhere(state, document, person)
    advanced, events, _ = advance_directed_purposeful_society(state, seed, [document], [request])
    tick = state["tick"] + 1
    assert _mine(advanced, other)["action"] == {
        **other["action"],
        "status": "completed",
        "reason": "partner_left",
    }
    said = {
        (str(event.subject_id), event.kind, event.document["reason"])
        for event in events
        if event.tick == tick
    }
    assert {
        (person["id"], "replanned", "called_away"),
        (other["id"], "action_completed", "partner_left"),
    } <= said


def test_asked_to_go_where_they_are_resting_now_a_person_is_refused_by_name():
    """Ending the rest to start the same rest again would only take its relief away."""
    document = square.compose(square.square_objects())
    seed = square.DEVELOPMENT_SEEDS[9]
    state, person = _until(document, seed, _resting)
    here = next(t for t in document["targets"] if t["target_id"] == person["target"]["target_id"])
    with pytest.raises(ValueError, match="inhabitant_already_there"):
        build_action_request(
            state,
            document,
            request_id=uuid.uuid5(square.SOCIETY, "here"),
            requested_by=ACTOR,
            subject_id=uuid.UUID(person["id"]),
            intent=ActionIntent("go_to", here["target_id"]),
        )
    # Recorded and consumed anyway, it is rejected, and the rest goes on as if nobody asked.
    request = _envelope(state, document, person["id"], here)
    policies, dispositions = action_goal_policies(state, document, [request])
    assert policies == {}
    assert [(held.disposition, held.reason) for held in dispositions] == [
        ("rejected", "inhabitant_already_there")
    ]
    asked, _, _ = advance_directed_purposeful_society(state, seed, [document], [request])
    unasked, _ = advance_purposeful_society(state, seed, [document])
    assert _mine(asked, person) == _mine(unasked, person)


def _waiting(state: dict) -> tuple[dict, dict] | None:
    """Somebody at the talk spot, waiting, and the other person still walking over to them."""
    people = {person["id"]: person for person in state["inhabitants"]}
    for person in state["inhabitants"]:
        if person["action"]["reason"] != "waiting_for_partner":
            continue
        other = people[person["goal"]["partner_id"]]
        if other["action"]["kind"] == "move":
            return person, other
    return None


def test_a_waiting_talker_asked_elsewhere_ends_the_others_walk_over_in_the_same_minute():
    """At a walking budget under a pair's walk, one arrives first and waits. Asked elsewhere, they
    go, and the other, still on the way, stops walking over in that same minute rather than
    arriving to talk with nobody."""
    document = square.compose(square.square_objects())
    seed = square.DEVELOPMENT_SEEDS[6]
    genesis = initial_purposeful_society(square.SOCIETY, seed, document, population=8)
    # A society recorded with a slow walking budget: walks take several minutes.
    genesis["movement_budget_mm_per_tick"] = 500
    state, found = genesis, None
    for _ in range(240):
        state, _ = advance_purposeful_society(state, seed, [document])
        found = _waiting(state)
        if found is not None:
            break
    assert found is not None, "nobody waited for somebody still walking over"
    waiting, walking = found
    request = _elsewhere(state, document, waiting)
    advanced, events, _ = advance_directed_purposeful_society(state, seed, [document], [request])
    tick = state["tick"] + 1
    said = {
        (str(event.subject_id), event.kind, event.document["reason"])
        for event in events
        if event.tick == tick
    }
    assert {
        (waiting["id"], "replanned", "called_away"),
        (walking["id"], "replanned", "partner_left"),
    } <= said
    after = _mine(advanced, walking)
    goal = after["goal"]
    assert goal is None or goal.get("partner_id") != waiting["id"]
    assert after["action"]["kind"] != "talk"


def test_under_the_released_rules_a_request_during_a_stay_is_refused_as_before():
    document = square.compose(square.square_objects(), v2=True)
    seed = square.DEVELOPMENT_SEEDS[9]
    state, person = _until(document, seed, _resting)
    target = next(t for t in document["targets"] if t["target_id"] != person["target"]["target_id"])
    with pytest.raises(ValueError, match="inhabitant_action_in_progress"):
        build_action_request(
            state,
            document,
            request_id=uuid.uuid5(square.SOCIETY, "released"),
            requested_by=ACTOR,
            subject_id=uuid.UUID(person["id"]),
            intent=ActionIntent("go_to", target["target_id"]),
        )
    # Recorded and consumed anyway, it is rejected, and the stay goes on as if nobody asked.
    request = _envelope(state, document, person["id"], target)
    policies, dispositions = action_goal_policies(state, document, [request])
    assert policies == {}
    assert [(held.disposition, held.reason) for held in dispositions] == [
        ("rejected", "inhabitant_action_in_progress")
    ]
    asked, events, _ = advance_directed_purposeful_society(state, seed, [document], [request])
    unasked, _ = advance_purposeful_society(state, seed, [document])
    assert _mine(asked, person) == _mine(unasked, person)
    assert not [event for event in events if event.document["reason"] == "called_away"]
