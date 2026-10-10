"""A being does only the routine's activities its kind lists, in a society that records so.

A society of things records its ability modules in its first input and runs exactly those for its
whole life. A new one records ``exulanica-ability/purposeful/v2``: the routine plans, and a decider
is offered, only those of stand, talk, rest and visit that a being's kind lists, a talk only
between two beings whose kinds both list talk, and a request for another is refused
``activity_not_offered``; waiting is everybody's. A lantern spirit's kind lists none of the four,
so it waits, recorded ``nothing_its_kind_does``; a knight's and a villager's list all four. Only
resting relieves tiredness, so a being whose kind does not rest is never tired: a visitor, whose
kind talks but does not rest, stays free to talk. A society that recorded ``purposeful/v1`` plans
every activity for everybody, as every society made
before the second version does: ``fixtures/society-things-purposeful-v1.json`` was recorded by the
code before it (a spirit resting, standing, visiting and talking) and replays byte for byte.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest
from exulanica.abilities.registry import PURPOSEFUL, PURPOSEFUL_BY_KIND
from exulanica.api.thing_card import _abilities, _offers
from exulanica.canonical import canonical_json
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.world.society import society_state_sha256
from exulanica.world.society_actions import ActionIntent, build_action_request
from exulanica.world.society_decision_contract import choice_options, person_role
from exulanica.world.society_planner import (
    advance_purposeful_society,
    input_sha256,
    kind_gated_activities,
    routine_withheld,
)
from exulanica.world.society_things import THINGS_PROFILE, advance_things, initial_things_society

import test_society_hands as hands
from things_society_support import SEED, SOCIETY, arrival, compose, thing

HISTORY = Path(__file__).parent / "fixtures" / "society-things-purposeful-v1.json"
GATE = thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593)
SPIRIT = thing("spirit", "lantern_spirit", 1, -3_000, 3_000)
KNIGHT = thing("knight", "knight", 1, 3_000, 3_000)
#: What the routine plans that a kind may leave out, by the option kinds a decider is offered.
ROUTINE_OPTIONS = frozenset({"target", "stand", "talk"})
ACTOR = uuid.UUID(int=0xAC7)


def _first_version(document, modules=None):
    """The same input as a society made before the second version records it: purposeful/v1
    beside today's other modules, or exactly ``modules``, and no movement modules, which no first
    input recorded then."""
    first = dict(document)
    first.pop("movement_modules", None)
    first["modules"] = (
        list(modules)
        if modules is not None
        else sorted(
            PURPOSEFUL if module == PURPOSEFUL_BY_KIND else module for module in document["modules"]
        )
    )
    first.pop("document_sha256")
    first["document_sha256"] = input_sha256(first)
    return first


def _being(state, kind):
    return next(p for p in state["inhabitants"] if p["kind"]["kind"] == kind)


def _person(state, subject_id):
    return next(p for p in state["inhabitants"] if p["id"] == subject_id)


def _minute(state, document, crossings=()):
    planned, events = advance_purposeful_society(state, SEED, [document])
    state, events, _bound = advance_things(state, planned, SEED, document, events, crossings)
    return state, events


def _offered(state, document, subject_id):
    contract = person_role().contract_for(THINGS_PROFILE)
    return choice_options(state, document, subject_id, contract, seed=SEED)


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


def test_a_new_society_records_the_routine_held_to_each_being_s_kind():
    document = compose((GATE, SPIRIT, KNIGHT))
    assert PURPOSEFUL_BY_KIND in document["modules"] and PURPOSEFUL not in document["modules"]
    state = initial_things_society(SOCIETY, SEED, document, population=4)
    assert state["modules"] == document["modules"]
    assert kind_gated_activities() == {"stand", "talk", "rest", "visit"}
    assert routine_withheld(state, _being(state, "lantern_spirit")) == kind_gated_activities()
    assert routine_withheld(state, _being(state, "knight")) == frozenset()
    assert routine_withheld(state, _being(state, "villager")) == frozenset()
    # Only resting relieves tiredness: a being whose kind does not rest is never tired, from
    # the minute it comes, a visitor crossing in through the gate among them.
    assert _being(state, "lantern_spirit")["need_milli"] == 0
    state, _events = _minute(state, document, [arrival(1)])
    visitor = _being(state, "visitor")
    assert routine_withheld(state, visitor) == {"rest", "visit"}
    assert (visitor["need_milli"], _being(state, "lantern_spirit")["need_milli"]) == (0, 0)
    # Under the first version nobody is held to its kind, and the same beings come tired.
    first = _first_version(document)
    state = initial_things_society(SOCIETY, SEED, first, population=4)
    assert routine_withheld(state, _being(state, "lantern_spirit")) == frozenset()
    state, _events = _minute(state, first, [arrival(1)])
    assert _being(state, "lantern_spirit")["need_milli"] > 750
    assert _being(state, "visitor")["need_milli"] > 0


def test_a_spirit_is_offered_no_place_stand_or_talk_and_its_routine_leaves_it_waiting():
    document = compose((GATE, SPIRIT, KNIGHT))
    state = initial_things_society(SOCIETY, SEED, document, population=4)
    spirit = _being(state, "lantern_spirit")["id"]
    blocked = []
    for _ in range(60):
        offered = {option.kind for option in _offered(state, document, spirit)}
        assert not offered & ROUTINE_OPTIONS and "wait" in offered, offered
        state, events = _minute(state, document)
        held = _person(state, spirit)
        assert (held["goal"], held["action"]["kind"], held["action"]["status"]) == (
            None,
            "idle",
            "blocked",
        )
        assert (held["action"]["reason"], held["need_milli"]) == ("nothing_its_kind_does", 0)
        blocked += [e for e in events if e.kind == "blocked" and str(e.subject_id) == spirit]
    # It waits, said once, not every minute.
    assert len(blocked) == 1
    # The control: the same input recording the first version offers the spirit places, and its
    # routine sets it resting in the first minute.
    first = _first_version(document)
    state = initial_things_society(SOCIETY, SEED, first, population=4)
    assert {option.kind for option in _offered(state, first, spirit)} & {"target"}
    state, _events = _minute(state, first)
    assert _person(state, spirit)["action"]["kind"] == "rest"


def test_a_spirit_still_walks_to_do_what_its_kind_lists():
    """The gate holds the routine's own activities, never the walk an ability of the kind needs:
    a spirit whose decider chooses to pick up a lantern five metres away walks there and does."""
    document = compose((GATE, SPIRIT, thing("lantern", "lantern", 1, -7_000, 3_000)))
    state = initial_things_society(SOCIETY, SEED, document, population=4)
    spirit = _being(state, "lantern_spirit")
    [pick] = [o for o in _offered(state, document, spirit["id"]) if o.kind == "pick_up"]
    assert pick.label == "pick up the lantern, 5 m away"
    state, events, _bound = hands._minute(state, document, [hands._receipt(spirit, pick)])
    [lantern] = [t for t in state["things"] if t["placed_id"] == "lantern"]
    assert lantern["held_by"] == spirit["id"]
    assert [e.kind for e in events if e.kind == "picked_up"] == ["picked_up"]


def _people(state):
    """What each person does and where, without the digests that name the input it is under."""
    return [
        (p["id"], p["action"], p["goal"], p["target"], p["location"], p["position_mm"])
        for p in state["inhabitants"]
    ]


def test_a_knight_and_villagers_are_offered_and_do_exactly_what_the_first_version_gives_them():
    second = compose((GATE, KNIGHT))
    first = _first_version(second)
    state_2 = initial_things_society(SOCIETY, SEED, second, population=4)
    state_1 = initial_things_society(SOCIETY, SEED, first, population=4)
    kinds = set()
    for _ in range(60):
        for person in state_2["inhabitants"]:
            options_2 = [o.as_record() for o in _offered(state_2, second, person["id"])]
            options_1 = [o.as_record() for o in _offered(state_1, first, person["id"])]
            assert options_2 == options_1
            kinds.update(option["kind"] for option in options_2)
        state_2, events_2 = _minute(state_2, second)
        state_1, events_1 = _minute(state_1, first)
        assert _people(state_2) == _people(state_1)
        assert [(e.tick, e.kind, e.subject_id, e.object_id) for e in events_2] == [
            (e.tick, e.kind, e.subject_id, e.object_id) for e in events_1
        ]
    # The positive control: places, standing and talking were all offered along the way.
    assert kinds >= ROUTINE_OPTIONS


def test_a_villager_never_stops_to_talk_with_a_spirit():
    document = compose((GATE, SPIRIT, KNIGHT))
    for version, offered_ever in ((document, False), (_first_version(document), True)):
        state = initial_things_society(SOCIETY, SEED, version, population=4)
        spirit = _being(state, "lantern_spirit")["id"]
        offered = talked = False
        for _ in range(60):
            for person in state["inhabitants"]:
                offered |= any(
                    option.kind == "talk" and option.partner_id == spirit
                    for option in _offered(state, version, person["id"])
                )
            state, _events = _minute(state, version)
            talked |= any(
                (p["goal"] or {}).get("partner_id") == spirit for p in state["inhabitants"]
            )
        # Under the first version the spirit is somebody to talk with, and talks; never under
        # the second.
        assert (offered, talked) == (offered_ever, offered_ever)


def _request(state, document, subject_id, target_id):
    return build_action_request(
        state,
        document,
        request_id=uuid.uuid5(SOCIETY, f"{state['tick']}:{subject_id}:{target_id}"),
        requested_by=ACTOR,
        subject_id=uuid.UUID(subject_id),
        intent=ActionIntent("go_to", target_id, None),
    )


def test_a_request_for_an_activity_its_kind_does_not_list_is_refused():
    document = compose((GATE, SPIRIT, KNIGHT))
    bench = next(t["target_id"] for t in document["targets"] if t["affordance"] == "rest")
    state = initial_things_society(SOCIETY, SEED, document, population=4)
    with pytest.raises(ValueError, match=r"^activity_not_offered$"):
        _request(state, document, _being(state, "lantern_spirit")["id"], bench)
    # A knight may be sent there, and under the first version so may the spirit.
    assert _request(state, document, _being(state, "knight")["id"], bench)
    first = _first_version(document)
    state = initial_things_society(SOCIETY, SEED, first, population=4)
    assert _request(state, first, _being(state, "lantern_spirit")["id"], bench)


def test_a_stored_society_of_the_first_version_replays_as_it_ran():
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    # The input as it was stored: the same composition, recording the modules it recorded then.
    document = _first_version(compose((GATE, SPIRIT, KNIGHT)), history["modules"])
    assert PURPOSEFUL in document["modules"]
    assert document["document_sha256"] == history["input_sha256"]
    state = initial_things_society(
        uuid.UUID(history["society_id"]), history["seed"], document, population=4
    )
    spirit = _being(state, "lantern_spirit")["id"]
    for minute in history["minutes"]:
        state, events = _minute(state, document)
        assert (state["tick"], society_state_sha256(state), _events_sha256(events)) == (
            minute["tick"],
            minute["state_sha256"],
            minute["events_sha256"],
        )
        assert _person(state, spirit)["action"]["kind"] == minute["spirit_action"]
    # The positive control: the spirit rests, stands, visits and talks in the stored history.
    assert {minute["spirit_action"] for minute in history["minutes"]} >= kind_gated_activities()


def _kind(key, version=1):
    return shipped_thing_kinds()[(key, version)]


def test_a_card_says_the_routine_s_abilities_are_served_by_the_version_the_society_runs():
    second = list(compose((GATE,))["modules"])
    first = sorted(PURPOSEFUL if m == PURPOSEFUL_BY_KIND else m for m in second)
    routine = {"wait", "stand", "talk", "rest", "visit"}
    for runs, module in ((second, PURPOSEFUL_BY_KIND), (first, PURPOSEFUL)):
        knight = {entry["key"]: entry["module"] for entry in _abilities(_kind("knight"), runs)}
        assert {key: knight[key] for key in routine} == dict.fromkeys(routine, module)
        assert all(entry in runs for entry in knight.values())
        spirit = {
            entry["key"]: entry["module"] for entry in _abilities(_kind("lantern_spirit"), runs)
        }
        assert spirit["wait"] == module and not set(spirit) & (routine - {"wait"})
        bench = {entry["key"]: entry["module"] for entry in _offers(_kind("bench"), runs)}
        assert bench["rest_at"] == module
    # Nobody talks with a being whose kind does not talk, so its card offers no talk under the
    # second version; a knight's still does, and under the first version so does the spirit's.
    society = initial_things_society(SOCIETY, SEED, compose((GATE, SPIRIT, KNIGHT)), population=4)
    spirit, knight = _being(society, "lantern_spirit"), _being(society, "knight")
    offered = {
        who: {
            entry["key"] for entry in _offers(_kind(who), second, routine_withheld(society, being))
        }
        for who, being in (("lantern_spirit", spirit), ("knight", knight))
    }
    assert "talk_to" not in offered["lantern_spirit"] and "hear" in offered["lantern_spirit"]
    assert "talk_to" in offered["knight"]
    assert "talk_to" in {entry["key"] for entry in _offers(_kind("lantern_spirit"), first)}
    # A society that runs no version of a module lists none of its abilities.
    assert (
        not {entry["key"] for entry in _abilities(_kind("knight"), ["exulanica-ability/say/v1"])}
        & routine
    )
