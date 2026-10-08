"""A being's hands in a society of things, in memory: what it is offered, and what a held thing
does as the author edits the world and as visitors come and go.

The society records the hands module in its first input (``exulanica-ability/hands/v1``), so its
things state where their author placed them and, while held, the socket they are in. The tests
drive the hands step directly with receipts, as the minute consumes them, and read what the state
and the events say.
"""

from __future__ import annotations

import copy
import hashlib
import math
import uuid
from pathlib import Path

import pytest
from exulanica.abilities.registry import HANDS
from exulanica.world.role_decisions import DecisionDisposition
from exulanica.world.society_decision_contract import (
    DecisionOption,
    at_choice_point,
    choice_options,
    person_role,
)
from exulanica.world.society_hands import hand_over_mm, reach_mm
from exulanica.world.society_model_decisions import hands_goal_policy
from exulanica.world.society_planner import advance_purposeful_society
from exulanica.world.society_things import (
    advance_things,
    initial_things_society,
    validate_things_state,
)

import things_society_support as support
from things_society_support import SEED, SOCIETY, arrival, compose, departure, thing

GATE = thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593)
KNIGHT = thing("knight", "knight", 1, 3_000, 3_000)
#: Within reach of the knight's standing node (2,000 mm, 2,000 mm, the lattice node nearest where
#: it was placed), so it picks the sword up where it stands.
SWORD = thing("sword", "sword", 2, 2_400, 2_600)
POPULATION = 6
#: How many edits the starter's square took: the next edit is one more.
EDITS = len(support.square.square_objects())


def _contract():
    role = person_role()
    return role.contract(role.terms("exulanica-society/v7").versions)


def _knight(state):
    return next(p for p in state["inhabitants"] if p["came_by"] == "placed")


def _sword(state):
    return next(t for t in state["things"] if t["placed_id"] == "sword")


def _minute(state, document, decisions=(), crossings=(), *, previous=None):
    """One minute as the host and the playback run it: each applied hands choice's goal policy
    for the planner (waiting within reach, or walking to reach), then the things phase."""
    policies = {}
    for receipt, _disposition in decisions:
        option = DecisionOption.from_record(receipt["proposal"]["option"])
        policy = hands_goal_policy(state, document, receipt["subject_id"], option, set())
        assert not isinstance(policy, str), policy
        policies[receipt["subject_id"]] = policy
    inputs = [document] if previous is None else [previous, document]
    planned, events = advance_purposeful_society(state, SEED, inputs, goal_policy=policies)
    return advance_things(state, planned, SEED, document, events, crossings, decisions=decisions)


def _distance(a, b) -> int:
    return math.isqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _beside(state, being, point):
    moved = copy.deepcopy(state)
    person = next(p for p in moved["inhabitants"] if p["id"] == being["id"])
    person["position_mm"] = list(point)
    return moved


def _receipt(person, option):
    receipt = {
        "subject_id": person["id"],
        "request_id": f"r-{person['id']}-{option.kind}",
        "status": "accepted",
        "reason": "validated_choice",
        "proposal": {"label": option.label, "option": option.as_record()},
        "provider": {"provider": "test", "model_id": "m"},
    }
    return receipt, DecisionDisposition(
        decision_seq=1,
        request_id=receipt["request_id"],
        subject_id=person["id"],
        disposition="applied",
        reason="validated_choice",
        decision_sha256="0" * 64,
    )


def _picked_up(document):
    """The knight, standing beside the sword, picks it up."""
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    assert HANDS in state["modules"]
    knight = _knight(state)
    options = choice_options(state, document, knight["id"], _contract(), seed=SEED)
    [pick] = [o for o in options if o.kind == "pick_up"]
    assert pick.label.startswith("pick up the sword") and pick.target_id == _sword(state)["id"]
    after, events, _ = _minute(state, document, [_receipt(knight, pick)])
    return after, events


def test_a_being_beside_a_thing_picks_it_up_into_a_hand_that_fits_it():
    document = compose((GATE, KNIGHT, SWORD))
    after, events = _picked_up(document)
    [picked] = [e for e in events if e.kind == "picked_up"]
    sword = _sword(after)
    assert (sword["held_by"], sword["position_mm"]) == (_knight(after)["id"], None)
    assert sword["socket"] == picked.document["thing"]["socket"] == "hand.right"
    assert sword["placed_at_mm"] == [2_400, 2_600]
    # Standing within reach as the minute began, it acts as the minute begins.
    assert picked.document["at_ms"] == 0
    validate_things_state(after)
    # The next minute it still holds it: the author's placement still stands.
    later, _, _ = _minute(after, document)
    assert _sword(later)["held_by"] == _knight(later)["id"]


def test_an_author_s_move_or_removal_takes_a_held_thing_out_of_its_hand():
    document = compose((GATE, KNIGHT, SWORD))
    after, _ = _picked_up(document)
    moved = compose(
        (GATE, KNIGHT, thing("sword", "sword", 2, -2_000, 1_000)),
        input_seq=2,
        edit_seq=EDITS + 1,
    )
    later, _, _ = _minute(after, moved, previous=document)
    sword = _sword(later)
    assert (sword["held_by"], sword["position_mm"]) == (None, [-2_000, 1_000])
    assert "socket" not in sword
    removed = compose((GATE, KNIGHT), input_seq=2, edit_seq=EDITS + 1)
    later, _, _ = _minute(after, removed, previous=document)
    assert not [t for t in later["things"] if t["placed_id"] == "sword"]
    validate_things_state(later)


def test_beings_on_neighbouring_nodes_hand_a_thing_over_where_they_stand():
    """The walking graph spaces its nodes farther apart than the module's reach, so two beings on
    joined nodes stand as near as beings ever do: they hand over without walking."""
    document = compose((GATE, KNIGHT, thing("knight-2", "knight", 1, 9_000, 3_000), SWORD))
    assert hand_over_mm(document) > reach_mm()
    after, _ = _picked_up(document)
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    here = _knight(after)["position_mm"]
    # The other knight steps onto a node joined to the one the first stands on.
    there = next(
        nodes[b]
        for e in document["navigation"]["edges"]
        for a, b in ((e["from_node_id"], e["to_node_id"]), (e["to_node_id"], e["from_node_id"]))
        if nodes[a] == here and math.dist(nodes[a], nodes[b]) == hand_over_mm(document)
    )
    other = next(p for p in after["inhabitants"] if p["placed_id"] == "knight-2")
    after = _beside(after, other, there)
    knight = _knight(after)
    options = choice_options(after, document, knight["id"], _contract(), seed=SEED)
    [give] = [o for o in options if o.kind == "give" and o.addressee_id == other["id"]]
    after, events, _ = _minute(after, document, [_receipt(knight, give)])
    [gave] = [e for e in events if e.kind == "gave"]
    assert gave.document["at_ms"] == 0
    assert _sword(after)["held_by"] == other["id"]
    validate_things_state(after)


@pytest.mark.parametrize("kind", ["villager"])
def test_a_thing_is_offered_only_to_a_being_whose_kind_receives_it(kind):
    document = compose((GATE, KNIGHT, SWORD))
    after, _ = _picked_up(document)
    knight = _knight(after)
    other = next(p for p in after["inhabitants"] if p["kind"]["kind"] == kind)
    after = _beside(after, other, knight["position_mm"])
    options = choice_options(after, document, knight["id"], _contract(), seed=SEED)
    assert not [o for o in options if o.kind == "give" and o.addressee_id == other["id"]]
    # The positive control: it may still put the sword down.
    assert [o for o in options if o.kind == "put_down"]


def test_a_visitor_leaves_the_world_s_things_behind_and_takes_what_it_brought():
    """No arrival records a right to carry the world's things out, so a visitor going home puts a
    placed thing it holds down where it stood, and takes only what it carried in."""
    document = compose((GATE, KNIGHT, SWORD))
    after, _ = _picked_up(document)
    brought = str(uuid.uuid5(SOCIETY, "brought lantern"))
    after, _, _ = _minute(
        after,
        document,
        crossings=[
            arrival(
                1,
                kind=_traveller(),
                carried=[{"thing_id": brought, "kind": support.reference("lantern", 1)}],
            )
        ],
    )
    visitor = next(p for p in after["inhabitants"] if p["came_by"] == "crossed")
    knight = _knight(after)
    after = _beside(after, visitor, knight["position_mm"])
    knight = _knight(after)
    options = choice_options(after, document, knight["id"], _contract(), seed=SEED)
    [give] = [o for o in options if o.kind == "give" and o.addressee_id == visitor["id"]]
    after, events, _ = _minute(after, document, [_receipt(knight, give)])
    assert [e for e in events if e.kind == "gave"]
    after, events, _ = _minute(after, document, crossings=[departure(visitor["id"], 1)])
    [left] = [e for e in events if e.kind == "thing_departed"]
    stood = left.document["position_mm"]
    assert [held["id"] for held in left.document["thing"]["carried"]] == [brought]
    assert left.document["thing"]["left"] == [_sword_id(document)]
    sword = _sword(after)
    assert (sword["held_by"], sword["position_mm"], "socket" in sword) == (None, stood, False)
    assert brought not in {t["id"] for t in after["things"]}
    assert "carried_away" not in after
    validate_things_state(after)


def _two_visitors(document, lanterns=1):
    """Visitor A arrives carrying ``lanterns`` lanterns and visitor B carrying nothing; B stands
    beside A."""
    brought = [str(uuid.uuid5(SOCIETY, f"lantern {n}")) for n in range(lanterns)]
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    state, _, _ = _minute(
        state,
        document,
        crossings=[
            arrival(
                1,
                kind=_traveller(),
                carried=[{"thing_id": b, "kind": support.reference("lantern", 1)} for b in brought],
            ),
            arrival(2, kind=_traveller()),
        ],
    )
    a, b = sorted(
        (p for p in state["inhabitants"] if p["came_by"] == "crossed"),
        key=lambda p: p["crossing"]["arrival_id"] != str(uuid.uuid5(support.GRANT, "arrival:1")),
    )
    return _beside(state, b, a["position_mm"]), a["id"], b["id"], brought


def _person(state, identity):
    return next(p for p in state["inhabitants"] if p["id"] == identity)


def _give(state, document, giver, to):
    person = _person(state, giver)
    options = choice_options(state, document, giver, _contract(), seed=SEED)
    give = next(o for o in options if o.kind == "give" and o.addressee_id == to)
    after, events, _ = _minute(state, document, [_receipt(person, give)])
    assert [e for e in events if e.kind == "gave"], [e.kind for e in events]
    return after


def test_a_visitor_takes_home_only_what_it_brought_and_what_it_brought_goes_home_with_it():
    """A gives its lantern to B, and B is sent home: B never brought it, so B puts it down where it
    stood. Then A is sent home: its lantern, on the ground, goes home with it."""
    document = compose((GATE, KNIGHT, SWORD))
    state, a, b, [lantern] = _two_visitors(document)
    assert next(t for t in state["things"] if t["id"] == lantern)["brought_by"] == a
    state = _give(state, document, a, b)
    state, events, _ = _minute(state, document, crossings=[departure(b, 1)])
    [left] = [e for e in events if e.kind == "thing_departed"]
    assert left.document["thing"]["carried"] == []
    assert left.document["thing"]["left"] == [lantern]
    found = next(t for t in state["things"] if t["id"] == lantern)
    assert (found["held_by"], found["position_mm"]) == (None, left.document["position_mm"])
    validate_things_state(state)
    state, events, _ = _minute(state, document, crossings=[departure(a, 2)])
    [gone] = [e for e in events if e.kind == "thing_departed"]
    assert [held["id"] for held in gone.document["thing"]["carried"]] == [lantern]
    assert lantern not in {t["id"] for t in state["things"]}
    validate_things_state(state)


def test_a_thing_a_being_here_holds_stays_until_it_is_put_down_after_its_bringer_left():
    """A gives its lantern to B, then A goes home: B still holds it, so it stays. When B goes home
    too it puts the lantern down, and with its bringer gone the lantern goes home as well."""
    document = compose((GATE, KNIGHT, SWORD))
    state, a, b, [lantern] = _two_visitors(document)
    state = _give(state, document, a, b)
    state, events, _ = _minute(state, document, crossings=[departure(a, 1)])
    [gone] = [e for e in events if e.kind == "thing_departed"]
    assert gone.document["thing"]["carried"] == []
    assert next(t for t in state["things"] if t["id"] == lantern)["held_by"] == b
    validate_things_state(state)
    state, events, _ = _minute(state, document, crossings=[departure(b, 2)])
    [left] = [e for e in events if e.kind == "thing_departed"]
    assert left.document["thing"]["returned"] == [lantern] and "left" not in left.document["thing"]
    assert lantern not in {t["id"] for t in state["things"]}
    validate_things_state(state)


def test_a_thing_put_down_after_its_bringer_left_goes_home_to_it():
    """A gives its lantern to the knight and goes home; the knight keeps it while it holds it, and
    when it puts the lantern down, the lantern goes home to A."""
    document = compose((GATE, KNIGHT, SWORD))
    state, a, _b, [lantern] = _two_visitors(document)
    state = _beside(state, _knight(state), _person(state, a)["position_mm"])
    state = _give(state, document, a, _knight(state)["id"])
    state, _, _ = _minute(state, document, crossings=[departure(a, 1)])
    knight = _knight(state)
    assert next(t for t in state["things"] if t["id"] == lantern)["held_by"] == knight["id"]
    options = choice_options(state, document, knight["id"], _contract(), seed=SEED)
    put = next(o for o in options if o.kind == "put_down" and o.target_id == lantern)
    state, events, _ = _minute(state, document, [_receipt(knight, put)])
    [done] = [e for e in events if e.kind == "put_down"]
    assert done.document["thing"]["returned"] is True
    assert lantern not in {t["id"] for t in state["things"]}
    validate_things_state(state)


def test_visitors_coming_and_going_leave_no_things_behind():
    """An outside program sending a visitor with sixteen things, handing one to another visitor and
    sending both home, leaves the society's things as many as its author placed."""
    document = compose((GATE, KNIGHT, SWORD))
    placed = len(initial_things_society(SOCIETY, SEED, document, population=POPULATION)["things"])
    state, a, b, brought = _two_visitors(document, lanterns=16)
    assert len(state["things"]) == placed + 16
    state = _give(state, document, a, b)
    state, events, _ = _minute(state, document, crossings=[departure(a, 1)])
    [gone] = [e for e in events if e.kind == "thing_departed"]
    assert len(gone.document["thing"]["carried"]) == 15
    state, events, _ = _minute(state, document, crossings=[departure(b, 2)])
    [left] = [e for e in events if e.kind == "thing_departed"]
    assert len(left.document["thing"]["returned"]) == 1
    assert len(state["things"]) == placed
    assert not set(brought) & {t["id"] for t in state["things"]}
    validate_things_state(state)


def test_the_state_check_refuses_a_brought_thing_its_bringer_left_behind():
    document = compose((GATE, KNIGHT, SWORD))
    state, a, _b, [lantern] = _two_visitors(document)
    stray = copy.deepcopy(state)
    stray["inhabitants"] = [p for p in stray["inhabitants"] if p["id"] != a]
    thing = next(t for t in stray["things"] if t["id"] == lantern)
    thing.update(held_by=None, position_mm=[0, 0])
    thing.pop("socket")
    with pytest.raises(ValueError, match="bringer"):
        validate_things_state(stray)
    unmarked = copy.deepcopy(state)
    next(t for t in unmarked["things"] if t["id"] == lantern).pop("brought_by")
    with pytest.raises(ValueError, match="visitor that brought it"):
        validate_things_state(unmarked)


def test_a_society_whose_carried_in_thing_names_no_bringer_is_refused_by_name():
    """A hands society stored before bringers were recorded: its visitor leaving would find no
    bringer for the lantern it carried in. The minute refuses it by name before doing anything."""
    document = compose((GATE, KNIGHT, SWORD))
    state, a, _b, [lantern] = _two_visitors(document)
    next(t for t in state["things"] if t["id"] == lantern).pop("brought_by")
    with pytest.raises(ValueError, match="made before bringers were recorded"):
        _minute(state, document, crossings=[departure(a, 1)])


def test_an_act_chosen_while_walking_is_done_where_both_stood_as_the_minute_began():
    """A knight walking somewhere is offered the sword lying where it stands, chooses to pick it
    up, and walks on in that minute: the act is done as the minute began, not missed."""
    document = compose((GATE, KNIGHT, SWORD))
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    # At a slow pace, so a walk takes minutes.
    state["movement_budget_mm_per_tick"] = 2_500
    # A minute in which the knight, with something under way, walks on out of reach of where it
    # stood, so the minute's end alone would find the sword out of reach.
    for _ in range(60):
        knight = _knight(state)
        walks_on, _ = advance_purposeful_society(state, SEED, [document], goal_policy={})
        if not at_choice_point(knight) and (
            _distance(_knight(walks_on)["position_mm"], knight["position_mm"]) > reach_mm()
        ):
            break
        state, _, _ = _minute(state, document)
    else:
        raise AssertionError("the knight never walked out of reach with something under way")
    # The sword lies where the knight stands, mid-walk.
    sword = _sword(state)
    sword["position_mm"] = list(knight["position_mm"])
    options = choice_options(state, document, knight["id"], _contract(), seed=SEED)
    [pick] = [o for o in options if o.kind == "pick_up"]
    # Under way, the planner reads no new goal: the knight walks on, and the hands step acts.
    planned, events = advance_purposeful_society(state, SEED, [document], goal_policy={})
    after, events, _ = advance_things(
        state, planned, SEED, document, events, (), decisions=[_receipt(knight, pick)]
    )
    walked = _knight(after)
    # It ended the minute out of reach of where the sword lay.
    assert _distance(walked["position_mm"], knight["position_mm"]) > reach_mm()
    [done] = [e for e in events if e.kind == "picked_up"]
    assert done.document["at_ms"] == 0
    assert _sword(after)["held_by"] == knight["id"]
    validate_things_state(after)


def test_a_placed_being_removed_puts_down_what_it_holds():
    document = compose((GATE, KNIGHT, SWORD))
    after, _ = _picked_up(document)
    removed = compose((GATE, SWORD), input_seq=2, edit_seq=EDITS + 1)
    later, events, _ = _minute(after, removed, previous=document)
    [left] = [e for e in events if e.kind == "thing_departed"]
    assert left.document["thing"]["left"] == [_sword(after)["id"]]
    # Put down where the knight stood as it left, at the end of the minute's walk.
    sword = _sword(later)
    assert (sword["held_by"], sword["position_mm"]) == (None, left.document["position_mm"])
    validate_things_state(later)


def test_two_things_of_one_kind_are_offered_apart():
    """Holding two swords, a being is offered to put each down under a label of its own, so the
    request it is asked by offers each label once."""
    document = compose((GATE, KNIGHT, SWORD, thing("sword-2", "sword", 2, 2_400, 3_400)))
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    knight = _knight(state)
    for placed in ("sword", "sword-2"):
        held = next(t for t in state["things"] if t["placed_id"] == placed)
        held.update(held_by=knight["id"], position_mm=None)
    state["things"][-2]["socket"] = "hand.right"
    state["things"][-1]["socket"] = "hand.left"
    options = choice_options(state, document, knight["id"], _contract(), seed=SEED)
    downs = sorted(o.label for o in options if o.kind == "put_down")
    assert downs == ["put down the sword", "put down the sword (2)"]
    labels = [o.label for o in options]
    assert len(labels) == len(set(labels))


def test_an_author_s_turn_applies_to_a_thing_nobody_moved():
    document = compose((GATE, KNIGHT, SWORD))
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    turned = compose(
        (GATE, KNIGHT, thing("sword", "sword", 2, 2_400, 2_600, yaw=1_570_796)),
        input_seq=2,
        edit_seq=EDITS + 1,
    )
    later, _, _ = _minute(state, turned, previous=document)
    assert _sword(later)["yaw_microradians"] == 1_570_796
    validate_things_state(later)


def test_an_author_s_height_applies_to_a_thing_nobody_moved():
    document = compose((GATE, KNIGHT, SWORD))
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    raised = compose(
        (GATE, KNIGHT, thing("sword", "sword", 2, 2_400, 2_600, y_mm=800)),
        input_seq=2,
        edit_seq=EDITS + 1,
    )
    later, _, _ = _minute(state, raised, previous=document)
    assert _sword(later)["height_mm"] == 800
    lowered = compose((GATE, KNIGHT, SWORD), input_seq=3, edit_seq=EDITS + 2)
    again, _, _ = _minute(later, lowered, previous=raised)
    assert "height_mm" not in _sword(again)
    validate_things_state(again)


def test_two_things_carried_in_are_held_in_two_sockets():
    from exulanica.world.society_hands import socket_of_held

    document = compose((GATE, KNIGHT, SWORD))
    state, _a, _b, brought = _two_visitors(document, lanterns=2)
    held = [t for t in state["things"] if t["id"] in brought]
    sockets = [socket_of_held(state, thing) for thing in held]
    assert None not in sockets and len(set(sockets)) == 2, sockets


def _traveller():
    from things_society_support import reference

    return reference("traveller", 1)


def _sword_id(document):
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    return _sword(state)["id"]


#: The data a hands society's minutes are replayed by, by its file's digest: the module's figures
#: (reach, approach, minutes of walking) and the body plans whose sockets hold things. A recorded
#: module version means these bytes; a change is a new version beside them.
HANDS_DATA = {
    "exulanica/abilities/ability-modules.v1.json": (
        "97791a777aab8eef9b73b8b40c7ee76068d26341d44bc270512e4a8d22856e94"
    ),
    "assets/catalogs/things/body-plans.v1.json": (
        "7b18374f2a13803a29765571e833e645089bb6d708d418eaca040ce37246f781"
    ),
}


@pytest.mark.parametrize("path", sorted(HANDS_DATA))
def test_the_data_hands_replay_by_keeps_its_bytes(path):
    root = Path(__file__).resolve().parents[1]
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == HANDS_DATA[path]


def test_a_being_with_something_under_way_is_offered_only_acts_within_reach():
    """The planner reads no new goal while something is under way, so an act the being would have
    to walk to is offered only at its choice point."""
    document = compose((GATE, KNIGHT, thing("sword", "sword", 2, -3_000, 2_600)))
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    knight = _knight(state)
    walking = [
        o
        for o in choice_options(state, document, knight["id"], _contract(), seed=SEED)
        if o.kind == "pick_up"
    ]
    assert walking and walking[0].walk_mm > 0
    busy = copy.deepcopy(state)
    being = next(p for p in busy["inhabitants"] if p["id"] == knight["id"])
    being["goal"] = being["goal"] or {"kind": "stand"}
    being["action"] = {**being["action"], "status": "active"}
    options = choice_options(busy, document, knight["id"], _contract(), seed=SEED)
    assert not [o for o in options if o.kind == "pick_up"]


@pytest.mark.parametrize(
    "intent",
    [
        {"ability": "juggle", "thing": "t", "with": None, "since": 0},
        {"ability": "pick_up", "thing": "t", "with": None},
        {"ability": "pick_up", "thing": "t", "with": None, "since": 99},
    ],
    ids=["unknown-act", "missing-field", "from-the-future"],
)
def test_the_state_check_holds_a_hands_intent_to_its_shape(intent):
    document = compose((GATE, KNIGHT, SWORD))
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    good = copy.deepcopy(state)
    _knight_in(good)["hands"] = {"ability": "pick_up", "thing": "t", "with": None, "since": 0}
    validate_things_state(good)
    _knight_in(state)["hands"] = intent
    with pytest.raises(ValueError, match="hands act"):
        validate_things_state(state)


def _knight_in(state):
    return next(p for p in state["inhabitants"] if p["came_by"] == "placed")
