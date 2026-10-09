"""Following in a society of things, in memory: ``exulanica-ability/follow/v2``.

A society made now records the follow module in its first input; one made before replays as it ran
(``fixtures/society-things-before-follow.json``, recorded by main before the module was built). The
tests drive whole minutes as the host and the playback run them: the minute's goal policies from
its receipts (:func:`model_goal_policies`, where a follower's walk is planned), the planner, then
the things phase (where following begins and ends), and read what the state and the events say.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import uuid
from pathlib import Path

import pytest
from exulanica.abilities.registry import FOLLOW_KEEPING_NEAR, current_modules
from exulanica.canonical import canonical_json
from exulanica.world.society import society_state_sha256
from exulanica.world.society_decision_contract import (
    at_choice_point,
    choice_options,
    person_role,
)
from exulanica.world.society_model_decisions import model_goal_policies
from exulanica.world.society_planner import advance_purposeful_society, input_sha256
from exulanica.world.society_play import play_contract
from exulanica.world.society_things import (
    THINGS_PROFILE,
    advance_things,
    initial_things_society,
)

import things_society_support as support
from things_society_support import SEED, SOCIETY, compose, thing

HISTORY = Path(__file__).parent / "fixtures" / "society-things-before-follow.json"
#: The things the fixture's society was composed with, and its population.
RECORDED = (
    thing("well", "well", 2, -4_000, 2_000),
    thing("knight", "knight", 1, 3_000, 3_000),
    thing("spirit", "lantern_spirit", 1, -3_000, 3_000),
    thing("lantern", "lantern", 1, 3_400, 2_600),
)
WELL = thing("well", "well", 2, -4_000, 2_000)
KNIGHT = thing("knight", "knight", 1, 3_000, 3_000)
SQUIRE = thing("squire", "knight", 1, -3_000, 3_000)
POPULATION = 6
#: How many edits the starter's square took: the next edit is one more.
EDITS = len(support.square.square_objects())
#: The follow module's distance, as its row states it, and the minutes a follower may be lost.
WITHIN_MM = 2_000
LOST_AFTER = 3


def _events_sha256(events) -> str:
    return hashlib.sha256(
        canonical_json(
            [
                {
                    "event_id": str(e.event_id),
                    "tick": e.tick,
                    "kind": e.kind,
                    "subject_id": str(e.subject_id),
                    "object_id": None if e.object_id is None else str(e.object_id),
                    "document": e.document,
                }
                for e in events
            ]
        )
    ).hexdigest()


def _minute(state, document, receipts=(), *, seed=SEED, previous=None):
    """One minute: the receipts' goal policies and each follower's, the planner, then the things
    phase."""
    policies, dispositions = model_goal_policies(state, document, list(receipts), {})
    inputs = [document] if previous is None else [previous, document]
    planned, events = advance_purposeful_society(state, seed, inputs, goal_policy=policies)
    return advance_things(
        state,
        planned,
        seed,
        document,
        events,
        decisions=list(zip(receipts, dispositions, strict=True)),
    )


def _placed(state, placed_id):
    return next(p for p in state["inhabitants"] if p.get("placed_id") == placed_id)


def _distance(a, b) -> int:
    return math.isqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _played():
    """The contract a person playing a being answers under, which states following."""
    return play_contract(person_role(), THINGS_PROFILE)


def _receipt(state, document, person, option, sequence=1):
    """A receipt as the host seals it for the coming minute, choosing ``option``."""
    receipt = {
        "profile": person_role().receipt_profile,
        "decision_seq": sequence,
        "request_id": str(uuid.uuid5(SOCIETY, f"{state['tick']}:{person['id']}:{option.label}")),
        "subject_id": person["id"],
        "base_tick": state["tick"],
        "base_state_sha256": society_state_sha256(state),
        "input_sha256": document["document_sha256"],
        "branch_id": state["branch_id"],
        "status": "accepted",
        "reason": "validated_choice",
        "proposal": {"label": option.label, "option": option.as_record()},
        "provider": {"provider": "test", "model_id": "m"},
    }
    receipt["document_sha256"] = input_sha256(receipt)
    return receipt


def _option(state, document, person, kind, addressee=None):
    [found] = [
        option
        for option in choice_options(state, document, person["id"], _played(), seed=SEED)
        if option.kind == kind and (addressee is None or option.addressee_id == addressee)
    ]
    return found


def _kept(state, document, kind="carry_on"):
    """The knight's receipt for the coming minute as a person playing it gives one each minute:
    carrying on (what a minute with no answer takes) unless ``kind`` names another option."""
    knight = _placed(state, "knight")
    return [_receipt(state, document, knight, _option(state, document, knight, kind))]


def _following(document):
    """A society where the knight has chosen to follow the squire, 6 m away: the minute after."""
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    knight, squire = _placed(state, "knight"), _placed(state, "squire")
    follow = _option(state, document, knight, "follow", squire["id"])
    assert follow.label.startswith("follow knight 2")
    state, events, _ = _minute(state, document, [_receipt(state, document, knight, follow)])
    [began] = [e for e in events if e.kind == "followed"]
    assert began.document["reason"] == "chose_to_follow"
    assert began.document["thing"]["with"] == squire["id"]
    return state


def test_a_society_made_before_follow_was_built_replays_as_it_ran():
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    document = compose(RECORDED)
    # The positive control: a society composed now records the module the stored one did not.
    assert FOLLOW_KEEPING_NEAR in document["modules"] and FOLLOW_KEEPING_NEAR in current_modules()
    document["modules"] = history["modules"]
    document["document_sha256"] = input_sha256(document)
    assert document["document_sha256"] == history["input_sha256"]
    state = initial_things_society(
        uuid.UUID(history["society_id"]), history["seed"], document, population=6
    )
    assert FOLLOW_KEEPING_NEAR not in state["modules"]
    for minute in history["minutes"]:
        state, events, _ = _minute(state, document, seed=history["seed"])
        assert (state["tick"], society_state_sha256(state), _events_sha256(events)) == (
            minute["tick"],
            minute["state_sha256"],
            minute["events_sha256"],
        )


def test_follow_is_offered_only_to_a_being_whose_kind_follows_toward_one_offered_to_be_followed():
    document = compose((WELL, KNIGHT, SQUIRE))
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    assert FOLLOW_KEEPING_NEAR in state["modules"]
    knight, squire = _placed(state, "knight"), _placed(state, "squire")
    villagers = [p for p in state["inhabitants"] if p["came_by"] == "populated"]
    offered = choice_options(state, document, knight["id"], _played(), seed=SEED)
    # Knight 2 offers to be followed; no villager does, whoever stands near.
    assert {o.addressee_id for o in offered if o.kind == "follow"} == {squire["id"]}
    # A villager's kind does not follow, and the engine's own terms, which models are asked
    # under, state no following at all.
    for villager in villagers:
        assert not [
            o
            for o in choice_options(state, document, villager["id"], _played(), seed=SEED)
            if o.kind in ("follow", "stop_following")
        ]
    role = person_role()
    asked = role.contract(role.terms(THINGS_PROFILE).versions)
    assert not [
        o
        for o in choice_options(state, document, knight["id"], asked, seed=SEED)
        if o.kind in ("follow", "stop_following")
    ]


def test_a_follower_keeps_near_the_one_it_follows_as_it_is_moved():
    document = compose((WELL, KNIGHT, SQUIRE))
    state = _following(document)
    # Its player carries on each minute: at the follower's choice point too, where carrying on is
    # offered while it follows, so a minute with no answer keeps it following.
    free = 0
    for _ in range(12):
        free += at_choice_point(_placed(state, "knight"))
        state, _events, _ = _minute(state, document, _kept(state, document))
    assert free > 0
    knight, squire = _placed(state, "knight"), _placed(state, "squire")
    assert knight["following"]["being"] == squire["id"]
    assert _distance(knight["position_mm"], squire["position_mm"]) <= WITHIN_MM
    # The author moves the squire across the square: the knight, standing by it, walks after it.
    moved = compose(
        (WELL, KNIGHT, thing("squire", "knight", 1, 3_000, -6_000)),
        input_seq=2,
        edit_seq=EDITS + 1,
    )
    state, _events, _ = _minute(state, moved, _kept(state, moved), previous=document)
    for _ in range(4):
        state, _events, _ = _minute(state, moved, _kept(state, moved))
    knight, squire = _placed(state, "knight"), _placed(state, "squire")
    assert squire["position_mm"][1] < -4_000
    assert knight["following"]["being"] == squire["id"]
    assert _distance(knight["position_mm"], squire["position_mm"]) <= WITHIN_MM


@pytest.mark.parametrize(
    "reason",
    ["chose_to_stop_following", "chose_otherwise", "not_kept", "target_gone", "lost_target"],
)
def test_a_follower_stops_by_name(reason):
    document = compose((WELL, KNIGHT, SQUIRE))
    state = _following(document)
    squire = _placed(state, "squire")
    now, previous, minutes = document, None, 1
    if reason == "chose_otherwise":
        # Waiting is offered at the follower's choice point: once its walk and stand are done.
        for _ in range(12):
            if at_choice_point(_placed(state, "knight")):
                break
            state, _events, _ = _minute(state, document, _kept(state, document))
    elif reason == "target_gone":
        now, previous = compose((WELL, KNIGHT), input_seq=2, edit_seq=EDITS + 1), document
    elif reason == "lost_target":
        # The squire stands where no node of the walking graph is near: the knight can come near
        # it nowhere, minute after minute.
        state = copy.deepcopy(state)
        _placed(state, "squire")["position_mm"] = [90_000, 90_000]
        minutes = LOST_AFTER
    first = {
        "chose_to_stop_following": "stop_following",
        "chose_otherwise": "wait",
        "not_kept": None,
    }.get(reason, "carry_on")
    stopped = []
    for minute in range(minutes):
        kind = first if minute == 0 else "carry_on"
        receipts = [] if kind is None else _kept(state, now, kind)
        state, events, _ = _minute(state, now, receipts, previous=previous)
        previous = None
        stopped += [e for e in events if e.kind == "stopped_following"]
        if minute < minutes - 1:
            assert _placed(state, "knight")["following"]["lost"] == minute + 1
    [ended] = stopped
    assert (ended.document["reason"], ended.document["thing"]["with"]) == (reason, squire["id"])
    assert "following" not in _placed(state, "knight")
