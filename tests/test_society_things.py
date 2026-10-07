"""The society of things, exulanica-society/v7, in memory: what it holds and what a minute does.

What is shown here, with no database:

*   genesis: the purposeful genesis's people, each a villager, then each being the author placed, at
    the open node nearest where it was placed; the placed objects are the state's things, and no
    look reaches the state;
*   a minute with no placed being to reconcile and no crossing is the purposeful planner's minute:
    the same people in the same places doing the same things, its events the same documents but
    for the engine they name;
*   placed beings follow the latest input: one an edit places arrives, one it moves is put where the
    edit says, one it removes leaves, and an unavailable input changes nobody;
*   crossings, in the order the door wrote them: a visitor arrives at the open node nearest a gate's
    arrival point, holding what it carried in, and leaves when its program calls it back, taking
    what it holds; each refusal is named, and every crossing gets an event of its own;
*   the same minute twice gives the same state and the same event ids;
*   the state check holds every person to its kind and how it came, and admits the movement fields
    agreed for v7 only where they apply.
"""

from __future__ import annotations

import copy
import json
import uuid

import pytest
from exulanica.world.crossings import CrossingRefused
from exulanica.world.deciders import arrival_deciders
from exulanica.world.society import society_state_sha256
from exulanica.world.society_planner import advance_purposeful_society, initial_purposeful_society
from exulanica.world.society_things import (
    THING_NAMESPACE,
    THINGS_PROFILE,
    VISITORS_MAXIMUM,
    advance_things,
    initial_things_society,
    validate_things_state,
)

import things_society_support as support
from things_society_support import SEED, SOCIETY, arrival, compose, departure, reference, thing

GATE = thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593)
WELL = thing("well", "well", 2, -4_000, 2_000)
SWORD = thing("sword", "sword", 2, 3_500, 3_000)
KNIGHT = thing("knight", "knight", 1, 3_000, 3_000)
POPULATION = 6
#: How many edits the starter's square took: the next edit is one more.
EDITS = len(support.square.square_objects())


def _genesis(*things):
    return initial_things_society(SOCIETY, SEED, compose(things), population=POPULATION)


def _minute(state, document, crossings=()):
    planned, events = advance_purposeful_society(state, SEED, [document])
    return advance_things(state, planned, SEED, document, events, crossings)


def _person(state, **match):
    return next(p for p in state["inhabitants"] if all(p.get(k) == v for k, v in match.items()))


def test_genesis_is_the_purposeful_people_as_villagers_then_each_placed_being():
    document = compose((GATE, WELL, SWORD, KNIGHT))
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    purposeful = initial_purposeful_society(SOCIETY, SEED, document, population=POPULATION)
    assert state["profile"] == THINGS_PROFILE
    villagers = [p for p in state["inhabitants"] if p["came_by"] == "populated"]
    assert [(p["id"], p["display_name"], p["position_mm"]) for p in villagers] == [
        (p["id"], p["display_name"], p["position_mm"]) for p in purposeful["inhabitants"]
    ]
    assert {p["kind"]["kind"] for p in villagers} == {"villager"}
    knight = _person(state, came_by="placed")
    assert knight["id"] == str(uuid.uuid5(THING_NAMESPACE, f"{document['world_id']}:knight"))
    assert (knight["display_name"], knight["placed_id"], knight["placed_at_mm"]) == (
        "Knight",
        "knight",
        [3_000, 3_000],
    )
    assert knight["kind"] == reference("knight", 1)
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    assert knight["position_mm"] == nodes[knight["location"]["node_id"]]
    # The placed objects are its things, in id order, each by its kind and where it stands.
    assert [(t["placed_id"], t["kind"]["kind"], t["held_by"]) for t in state["things"]] == [
        ("gate", "gate", None),
        ("sword", "sword", None),
        ("well", "well", None),
    ]
    assert "look" not in json.dumps(state)
    validate_things_state(state)


def test_a_minute_with_nothing_to_reconcile_and_no_crossing_is_the_planner_s_minute():
    document = compose((GATE, WELL))
    things = _genesis(GATE, WELL)
    purposeful = initial_purposeful_society(SOCIETY, SEED, document, population=POPULATION)
    for _ in range(12):
        things, thing_events, bound = _minute(things, document)
        purposeful, events = advance_purposeful_society(purposeful, SEED, [document])
        assert bound == ()
        assert [(e.kind, e.subject_id) for e in thing_events] == [
            (e.kind, e.subject_id) for e in events
        ]
        for mine, theirs in zip(thing_events, events, strict=True):
            assert mine.document["profile"] == THINGS_PROFILE
            assert {k: v for k, v in mine.document.items() if k not in ("profile",)} == {
                k: v
                for k, v in theirs.document.items()
                if k not in ("profile", "previous_state_sha256")
            } | {"previous_state_sha256": mine.document["previous_state_sha256"]}
        for mine, theirs in zip(things["inhabitants"], purposeful["inhabitants"], strict=True):
            assert (mine["position_mm"], mine["action"], mine["goal"]) == (
                theirs["position_mm"],
                theirs["action"],
                theirs["goal"],
            )


def test_placed_beings_follow_the_latest_input_and_an_unavailable_one_changes_nobody():
    state = _genesis(GATE)
    placed = compose((GATE, KNIGHT), input_seq=2, edit_seq=EDITS + 1)
    planned, events = advance_purposeful_society(state, SEED, [compose((GATE,)), placed])
    state, events, _ = advance_things(state, planned, SEED, placed, events)
    arrived = [e for e in events if e.kind == "thing_arrived"]
    assert [(e.document["reason"], e.document["thing"]["placed_id"]) for e in arrived] == [
        ("placed_by_author", "knight")
    ]
    assert arrived[0].document["at_ms"] == 0
    moved_knight = thing("knight", "knight", 1, -2_000, 4_000)
    moved = compose((GATE, moved_knight), input_seq=3, edit_seq=EDITS + 2)
    planned, events = advance_purposeful_society(state, SEED, [placed, moved])
    state, events, _ = advance_things(state, planned, SEED, moved, events)
    [event] = [e for e in events if e.kind == "thing_moved"]
    assert (event.document["reason"], event.document["outcome"]) == (
        "moved_by_author",
        "put_elsewhere",
    )
    knight = _person(state, came_by="placed")
    assert knight["placed_at_mm"] == [-2_000, 4_000]
    assert (knight["goal"], knight["action"]["reason"]) == (None, "moved_by_author")
    removed = compose((GATE,), input_seq=4, edit_seq=EDITS + 3)
    planned, events = advance_purposeful_society(state, SEED, [moved, removed])
    state, events, _ = advance_things(state, planned, SEED, removed, events)
    [event] = [e for e in events if e.kind == "thing_departed"]
    assert (event.document["reason"], event.document["outcome"]) == (
        "removed_by_author",
        "departed",
    )
    assert all(p["came_by"] == "populated" for p in state["inhabitants"])
    # An unavailable input places, moves and removes nobody.
    unavailable = copy.deepcopy(compose((GATE, KNIGHT), input_seq=5, edit_seq=EDITS + 4))
    before = copy.deepcopy(state)
    planned = copy.deepcopy(state)
    planned["tick"] += 1
    unavailable.update(availability="unavailable", unavailable_reason="authored_source_invalidated")
    after, events, _ = advance_things(before, planned, SEED, unavailable, ())
    assert [p["id"] for p in after["inhabitants"]] == [p["id"] for p in state["inhabitants"]]
    assert events == ()


def test_a_visitor_arrives_at_the_gate_holding_what_it_carried_and_leaves_with_it():
    document = compose((GATE, WELL))
    state = _genesis(GATE, WELL)
    carried = [{"thing_id": str(uuid.UUID(int=0xC0)), "kind": reference("sword", 2)}]
    state, events, bound = _minute(state, document, [arrival(1, carried=carried)])
    [arrived] = [e for e in events if e.kind == "thing_arrived"]
    visitor = _person(state, came_by="crossed")
    assert visitor["id"] == arrived.document["subject_id"]
    assert (visitor["display_name"], visitor["kind"]) == ("Visitor", reference("visitor", 1))
    assert visitor["crossing"] == {
        "arrival_id": str(arrival(1).crossing_id),
        "bridge": support.BRIDGE,
        "grant_id": str(support.GRANT),
    }
    gate_point = document["things"][0]["arrival_mm"]
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    nearest = min(
        nodes.values(), key=lambda p: (p[0] - gate_point[0]) ** 2 + (p[1] - gate_point[1]) ** 2
    )
    distance = (nearest[0] - gate_point[0]) ** 2 + (nearest[1] - gate_point[1]) ** 2
    assert (visitor["position_mm"][0] - gate_point[0]) ** 2 + (
        visitor["position_mm"][1] - gate_point[1]
    ) ** 2 == distance
    [sword] = [t for t in state["things"] if t["held_by"] == visitor["id"]]
    assert sword["kind"] == reference("sword", 2)
    assert [(b.disposition, b.reason) for b in bound] == [("arrived", None)]
    assert bound[0].event_id == arrived.event_id
    # Its program decides for it, read from its arrival.
    assert arrival_deciders(state) == {
        visitor["id"]: {
            "kind": "external",
            "bridge": support.BRIDGE,
            "grant_id": str(support.GRANT),
        }
    }
    state, events, bound = _minute(state, document, [departure(visitor["id"], 1)])
    [left] = [e for e in events if e.kind == "thing_departed"]
    assert (left.document["reason"], left.document["thing"]["carried"]) == (
        "sent_home",
        [{"id": sword["id"], "kind": sword["kind"]}],
    )
    assert all(t["held_by"] is None for t in state["things"])
    assert [(b.disposition, b.event_id) for b in bound] == [("departed", left.event_id)]
    validate_things_state(state)


def test_each_crossing_that_cannot_happen_is_refused_by_name_with_an_event_of_its_own():
    document = compose((GATE, WELL))
    state = _genesis(GATE, WELL)
    state, _, _ = _minute(state, document, [arrival(1)])
    visitor = _person(state, came_by="crossed")
    cases = [
        (arrival(2, kind=reference("sword", 2)), "refused", "unknown_kind", "arrival_refused"),
        (
            arrival(3, kind=reference("knight", 1) | {"sha256": "a" * 64}),
            "refused",
            "unknown_kind",
            "arrival_refused",
        ),
        (arrival(4, gate="no-such-gate"), "refused", "no_arrival_place", "arrival_refused"),
        (arrival(1), "refused", "already_here", "arrival_refused"),
        (departure(str(uuid.UUID(int=0xDE)), 9), "not_here", "not_here", "departure_refused"),
        (departure(visitor["id"], 10, reason="grant_ended"), "departed", None, "thing_departed"),
    ]
    for crossing, disposition, reason, kind in cases:
        _, events, bound = _minute(state, document, [crossing])
        [(taken)] = bound
        assert (taken.disposition, taken.reason) == (disposition, reason), crossing
        [event] = [e for e in events if e.event_id == taken.event_id]
        assert event.kind == kind
    # A world with no gate takes no visitor.
    bare = compose((WELL,))
    _, _, bound = _minute(_genesis(WELL), bare, [arrival(5)])
    assert [(b.disposition, b.reason) for b in bound] == [("refused", "no_arrival_place")]
    # A malformed crossing is refused before anything is decided.
    broken = arrival(6)
    broken.document["profile"] = "exulanica.thing-arrival/v9"
    with pytest.raises(CrossingRefused):
        _minute(state, document, [broken])


def test_a_society_takes_a_bounded_number_of_visitors():
    document = compose((GATE,))
    state = _genesis(GATE)
    crossings = [arrival(index) for index in range(VISITORS_MAXIMUM + 1)]
    state, _, bound = _minute(state, document, crossings)
    assert [b.disposition for b in bound] == ["arrived"] * VISITORS_MAXIMUM + ["refused"]
    assert bound[-1].reason == "visitor_limit"


def test_the_same_minute_twice_is_the_same_state_and_the_same_events():
    document = compose((GATE, WELL, KNIGHT))
    crossings = [arrival(1), departure(str(uuid.UUID(int=1)), 1)]
    first = _minute(_genesis(GATE, WELL, KNIGHT), document, crossings)
    second = _minute(_genesis(GATE, WELL, KNIGHT), document, crossings)
    assert society_state_sha256(first[0]) == society_state_sha256(second[0])
    assert [e.event_id for e in first[1]] == [e.event_id for e in second[1]]
    assert first[2] == second[2]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda p: p.pop("came_by"), "states its kind"),
        (lambda p: p.update(came_by="flew_in"), "stated way"),
        (lambda p: p.update(crossing={"arrival_id": "x"}), "placement and crossing"),
        (lambda p: p.update(mode="swimming"), "mode a module serves"),
        (lambda p: p.update(height_mm=1_000), "height while it flies"),
        (lambda p: p.update(mode="flight"), "height while it flies"),
        (lambda p: p.update(size_class_mm=450), "size class"),
        (lambda p: p.update(size_class_mm=8_500), "size class"),
        (lambda p: p.update(velocity_mm_s=[0, 0, 0]), "velocity only while it flies"),
        (
            lambda p: p.update(mode="flight", height_mm=6_000, velocity_mm_s=[0, 100_001, 0]),
            "velocity only while it flies",
        ),
        (
            lambda p: p.update(mode="flight", height_mm=6_000, velocity_mm_s=[1, 2]),
            "velocity only while it flies",
        ),
    ],
)
def test_the_state_check_holds_each_person_to_its_kind_and_its_movement(change, message):
    state = _genesis(GATE, KNIGHT)
    # The positive control: the fields agreed for a flyer pass where they apply.
    flyer = copy.deepcopy(state)
    flyer["inhabitants"][0].update(mode="flight", height_mm=6_000, size_class_mm=4_000)
    validate_things_state(flyer)
    flyer["inhabitants"][0].update(velocity_mm_s=[-100_000, 0, 100_000])
    validate_things_state(flyer)
    broken = copy.deepcopy(state)
    change(broken["inhabitants"][0])
    with pytest.raises(ValueError, match=message):
        validate_things_state(broken)
