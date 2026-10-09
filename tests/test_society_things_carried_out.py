"""A visitor carries a world's things out of a society of things, in memory.

A visitor whose arrival let it carry the world's things out (``may_carry_out``) picks a placed sword
up. Leaving by its own choice, or called home by its player, it takes the sword: the departure names
it with its placement, the sword is gone from the society, and while the author's placement stands
it is never put back, so it is never in two places. Sent away by the world's owner, its grant
ended, or with no such right, it puts the sword down where it stood. One grant carries at most
eight placed things out in any sixty minutes; one past that stays. Where its arrival names the
kinds its program can take, it carries out only those, and puts the rest down. An author who moves
the placement makes a new one, and the sword is placed again.
"""

from __future__ import annotations

import copy

import pytest
from exulanica.world.crossings import CrossingRefused, check_crossing
from exulanica.world.society_decision_contract import choice_options
from exulanica.world.society_things import (
    CARRY_OUT_MAXIMUM,
    CARRY_OUT_WINDOW_TICKS,
    initial_things_society,
    validate_things_state,
)

import test_society_hands as hands
import test_society_things as things
from things_society_support import GRANT, SEED, SOCIETY, arrival, compose, departure, thing

GATE = thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593)
SWORD = thing("sword", "sword", 2, 2_400, 2_600)
KNIGHT = thing("knight", "knight", 1, 3_000, 3_000)
POPULATION = 6
EDITS = len(things.support.square.square_objects())


def _visitor(state):
    return next(p for p in state["inhabitants"] if p["came_by"] == "crossed")


def _sword(state):
    return next((t for t in state["things"] if t["placed_id"] == "sword"), None)


def _holding(document, *, may_carry_out=True, carries_out=None):
    """The visitor arrives, the sword is laid where it stands, and it picks the sword up."""
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    state, _, _ = hands._minute(
        state,
        document,
        crossings=[arrival(1, may_carry_out=may_carry_out, carries_out=carries_out)],
    )
    visitor = _visitor(state)
    assert visitor["crossing"].get("may_carry_out", False) is may_carry_out
    _sword(state)["position_mm"] = list(visitor["position_mm"])
    options = choice_options(state, document, visitor["id"], hands._contract(), seed=SEED)
    [pick] = [o for o in options if o.kind == "pick_up" and o.target_id == _sword(state)["id"]]
    state, events, _ = hands._minute(state, document, [hands._receipt(visitor, pick)])
    assert [e.kind for e in events if e.kind == "picked_up"] == ["picked_up"]
    assert _sword(state)["held_by"] == visitor["id"]
    validate_things_state(state)
    return state


def _departed(events):
    [left] = [e for e in events if e.kind == "thing_departed"]
    return left.document


def test_a_visitor_called_home_by_its_player_carries_the_sword_out_and_it_stays_out():
    document = compose((GATE, KNIGHT, SWORD))
    state = _holding(document)
    sword = _sword(state)
    state, events, _ = hands._minute(
        state, document, crossings=[departure(_visitor(state)["id"], 1, called_by="player")]
    )
    gone = _departed(events)
    assert gone["reason"] == "sent_home" and gone["thing"]["called_by"] == "player"
    assert gone["thing"]["carried"] == [
        {"id": sword["id"], "kind": sword["kind"], "placed_id": "sword"}
    ]
    assert "left" not in gone["thing"] and "carry_out_limited" not in gone["thing"]
    assert _sword(state) is None
    assert state["carried_out"] == [
        {
            "placed_id": "sword",
            "kind": sword["kind"],
            "placed_at_mm": sword["placed_at_mm"],
            "grant_id": str(GRANT),
            "tick": state["tick"],
        }
    ]
    validate_things_state(state)
    # The author's placement still stands: later minutes never put the sword back.
    for _ in range(3):
        state, _, _ = hands._minute(state, document)
        assert _sword(state) is None
    # The same minute twice is the same state and the same events.
    again, events_again, _ = hands._minute(state, document)
    once, events_once, _ = hands._minute(state, document)
    assert (again, [e.document for e in events_again]) == (
        once,
        [e.document for e in events_once],
    )


def test_a_visitor_leaving_by_its_own_choice_carries_the_sword_out():
    document = compose((GATE, KNIGHT, SWORD))
    state = _holding(document)
    visitor = _visitor(state)
    contract = things._things_contract()
    leave = next(
        o
        for o in choice_options(state, document, visitor["id"], contract, seed=SEED)
        if o.kind == "leave"
    )
    state, events, _ = things._decided_minute(state, document, [things._receipt(visitor, leave)])
    gone = _departed(events)
    assert gone["reason"] == "chose_to_leave"
    assert [held.get("placed_id") for held in gone["thing"]["carried"]] == ["sword"]
    assert _sword(state) is None and len(state["carried_out"]) == 1
    validate_things_state(state)


@pytest.mark.parametrize(
    ("reason", "called_by", "may_carry_out"),
    [
        ("sent_away", None, True),  # the world's owner sends it away
        ("grant_ended", None, True),
        ("sent_away", "player", False),  # called home, but its arrival gave it no such right
    ],
    ids=["owner_sends_it_away", "grant_ended", "no_right"],
)
def test_a_visitor_keeps_the_world_s_sword_behind_otherwise(reason, called_by, may_carry_out):
    document = compose((GATE, KNIGHT, SWORD))
    state = _holding(document, may_carry_out=may_carry_out)
    sword = _sword(state)
    state, events, _ = hands._minute(
        state,
        document,
        crossings=[departure(_visitor(state)["id"], 1, reason=reason, called_by=called_by)],
    )
    gone = _departed(events)
    assert gone["thing"]["carried"] == [] and gone["thing"]["left"] == [sword["id"]]
    put = _sword(state)
    assert (put["held_by"], put["position_mm"]) == (None, gone["position_mm"])
    assert "carried_out" not in state
    validate_things_state(state)


def test_a_visitor_whose_program_is_lost_keeps_the_world_s_sword_behind():
    document = compose((GATE, KNIGHT, SWORD))
    state = _holding(document)
    visitor = _visitor(state)
    quiet = things._receipt(visitor, None, status="unavailable", reason="no_answer_in_time")
    for _ in range(10):
        state, events, _ = things._decided_minute(state, document, [quiet])
        if [e for e in events if e.kind == "thing_departed"]:
            break
    gone = _departed(events)
    assert gone["reason"] == "decider_lost" and gone["thing"]["carried"] == []
    assert _sword(state)["held_by"] is None and "carried_out" not in state


def test_one_grant_carries_out_at_most_eight_things_an_hour():
    document = compose((GATE, KNIGHT, SWORD))
    state = _holding(document)
    grant = _visitor(state)["crossing"]["grant_id"]
    full = copy.deepcopy(state)
    full["carried_out"] = [
        {
            "placed_id": f"elsewhere-{n}",
            "kind": _sword(state)["kind"],
            "placed_at_mm": [0, 0],
            "grant_id": grant,
            "tick": state["tick"],
        }
        for n in range(CARRY_OUT_MAXIMUM)
    ]
    validate_things_state(full)
    after, events, _ = hands._minute(
        full, document, crossings=[departure(_visitor(full)["id"], 1, called_by="player")]
    )
    gone = _departed(events)
    assert gone["thing"]["carry_out_limited"] is True
    assert gone["thing"]["carried"] == [] and gone["thing"]["left"] == [_sword(full)["id"]]
    assert _sword(after)["held_by"] is None
    # An hour later the bound has room again.
    later = copy.deepcopy(full)
    for entry in later["carried_out"]:
        entry["tick"] = state["tick"] - CARRY_OUT_WINDOW_TICKS
    after, events, _ = hands._minute(
        later, document, crossings=[departure(_visitor(later)["id"], 1, called_by="player")]
    )
    assert [held.get("placed_id") for held in _departed(events)["thing"]["carried"]] == ["sword"]


def test_an_author_who_moves_the_carried_out_placement_places_the_sword_again():
    document = compose((GATE, KNIGHT, SWORD))
    state = _holding(document)
    state, _, _ = hands._minute(
        state, document, crossings=[departure(_visitor(state)["id"], 1, called_by="player")]
    )
    assert _sword(state) is None
    moved = compose(
        (GATE, KNIGHT, thing("sword", "sword", 2, -2_000, 2_600)),
        input_seq=2,
        edit_seq=EDITS + 1,
    )
    state, _, _ = hands._minute(state, moved, previous=document)
    sword = _sword(state)
    assert sword is not None and sword["placed_at_mm"][0] == -2_000 and sword["held_by"] is None
    validate_things_state(state)


@pytest.mark.parametrize(
    ("listed", "carried"),
    [(["sword"], True), (["lantern", "shield"], False), ([], False)],
    ids=["its-kind-listed", "other-kinds-listed", "nothing-listed"],
)
def test_a_visitor_carries_out_only_the_kinds_its_program_can_take(listed, carried):
    """Its arrival names the kinds of the world's things its program can take: called home by its
    player, it carries the sword out only where the list names the sword's kind, and otherwise puts
    it down where it stood, named as left and as not let out, carrying nothing out of the world."""
    document = compose((GATE, KNIGHT, SWORD))
    state = _holding(document, carries_out=listed)
    assert _visitor(state)["crossing"]["carries_out"] == listed
    sword = _sword(state)
    state, events, _ = hands._minute(
        state, document, crossings=[departure(_visitor(state)["id"], 1, called_by="player")]
    )
    departed = _departed(events)
    gone = departed["thing"]
    if carried:
        assert [held.get("placed_id") for held in gone["carried"]] == ["sword"]
        assert "not_let_out" not in gone and _sword(state) is None
        assert [entry["placed_id"] for entry in state["carried_out"]] == ["sword"]
    else:
        assert gone["carried"] == [] and "carry_out_limited" not in gone
        assert gone["left"] == gone["not_let_out"] == [sword["id"]]
        stayed = _sword(state)
        assert (stayed["held_by"], stayed["position_mm"]) == (None, departed["position_mm"])
        assert "carried_out" not in state
    validate_things_state(state)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"may_carry_out": False}, "may_carry_out is true, or absent"),
        ({"may_carry_out": "yes"}, "may_carry_out is true, or absent"),
        ({"may_carry_out": None, "carries_out": ["sword"]}, "carries_out only beside"),
        ({"carries_out": ["sword", "lantern"]}, "sorted list"),
        ({"carries_out": ["sword", "sword"]}, "sorted list"),
        ({"carries_out": ["Sword"]}, "sorted list"),
        ({"carries_out": "sword"}, "sorted list"),
        ({"carries_out": [f"kind_{n:02d}" for n in range(65)]}, "at most 64"),
    ],
    ids=[
        "false",
        "not-a-boolean",
        "kinds-without-the-right",
        "unsorted",
        "repeated",
        "not-a-key",
        "not-a-list",
        "too-many",
    ],
)
def test_an_arrival_states_its_right_to_carry_out_only_as_true(change, message):
    crossing = arrival(1, may_carry_out=True)
    crossing.document.update(change)
    if crossing.document.get("may_carry_out") is None:
        del crossing.document["may_carry_out"]
    with pytest.raises(CrossingRefused, match=message):
        check_crossing(crossing)


@pytest.mark.parametrize(
    ("reason", "called_by"),
    [("grant_ended", "player"), ("sent_away", "owner"), ("sent_away", None)],
)
def test_a_departure_names_its_player_only_beside_sent_away(reason, called_by):
    crossing = departure("00000000-0000-0000-0000-000000000001", 1, reason=reason)
    crossing.document["called_by"] = called_by
    with pytest.raises(CrossingRefused, match="called_by is player, beside sent_away only"):
        check_crossing(crossing)


def test_the_state_check_holds_the_new_fields_to_their_shapes():
    document = compose((GATE, KNIGHT, SWORD))
    state = _holding(document)
    wrong = copy.deepcopy(state)
    _visitor(wrong)["crossing"]["may_carry_out"] = False
    with pytest.raises(ValueError, match="may carry the world's things out"):
        validate_things_state(wrong)
    wrong = copy.deepcopy(state)
    _visitor(wrong)["crossing"].update(carries_out=["sword"])
    del _visitor(wrong)["crossing"]["may_carry_out"]
    with pytest.raises(ValueError, match="may carry the world's things out, and which"):
        validate_things_state(wrong)
    wrong = copy.deepcopy(state)
    wrong["carried_out"] = [{"placed_id": "sword"}]
    with pytest.raises(ValueError, match="what visitors carried out"):
        validate_things_state(wrong)


def test_a_traveller_of_the_second_version_may_choose_to_go_home():
    """The second traveller is the first with leave: one that crossed in is offered to go home,
    and so carries the sword out by its own choice; the first is not offered it, and neither is a
    traveller its author placed."""
    from things_society_support import reference

    document = compose((GATE, KNIGHT, SWORD, thing("walker", "traveller", 2, -3_000, 3_000)))
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    for version in (1, 2):
        state, _, _ = hands._minute(
            state,
            document,
            crossings=[arrival(version, kind=reference("traveller", version), may_carry_out=True)],
        )
    contract = things._things_contract()
    offered = {
        (person["kind"]["version"], person["came_by"]): {
            option.kind
            for option in choice_options(state, document, person["id"], contract, seed=SEED)
        }
        for person in state["inhabitants"]
        if person["kind"]["kind"] == "traveller"
    }
    assert "leave" in offered[(2, "crossed")]
    assert "leave" not in offered[(1, "crossed")] and "leave" not in offered[(2, "placed")]
