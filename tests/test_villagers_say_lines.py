"""A society of things' own people may answer a line said to them.

Every ground peoples a society of things with villagers, and from the eighth ground catalog with
the villager's second version, which lists saying beside what the first did. So a villager a model
or the world's owner decides for, within hearing of another being, is offered to say something to
it and to everyone near, and, asked the minute after a line was said to it whatever is under way,
it may say one back. A society whose first input recorded the first villager keeps offering its
people no line, as it always did; and a society no model decides for lives the same, minute by
minute, whichever villager its input records.
"""

from __future__ import annotations

import copy
import math

from exulanica.things.kinds import shipped_thing_kinds
from exulanica.world import society_grounds
from exulanica.world.roles.person import due
from exulanica.world.society_decision_contract import choice_options, hearers
from exulanica.world.society_planner import advance_purposeful_society
from exulanica.world.society_things import advance_things, initial_things_society

from test_society_recollection import GATE, KNIGHT, _contract, _receipt, _say
from things_society_support import SEED, SOCIETY, compose

LINES = ("say_to", "say_all")


def _villager_reference(version: int) -> dict:
    return dict(shipped_thing_kinds()[("villager", version)].reference())


def _square():
    """The small square with the knight and its people, and the villager nearest the knight, as
    they stand, within hearing of each other."""
    document = compose((GATE, KNIGHT))
    state = copy.deepcopy(initial_things_society(SOCIETY, SEED, document, population=6))
    knight = next(p for p in state["inhabitants"] if p["placed_id"] == "knight")
    villager = min(
        (p for p in state["inhabitants"] if p["came_by"] == "populated"),
        key=lambda p: math.dist(p["position_mm"], knight["position_mm"]),
    )
    assert math.dist(villager["position_mm"], knight["position_mm"]) <= _reach()
    return state, document, knight, villager


def _reach() -> int:
    return _contract().value("hearing_reach_mm")


def _being(state, being):
    return next(p for p in state["inhabitants"] if p["id"] == being["id"])


def _lines(state, document, being) -> set[tuple[str, str | None]]:
    offered = choice_options(state, document, being["id"], _contract(), seed=SEED)
    return {(option.kind, option.addressee_id) for option in offered if option.kind in LINES}


def test_a_villager_beside_the_knight_is_offered_a_line_to_it_and_to_everyone_near():
    state, document, knight, villager = _square()
    assert document["population_kind"] == _villager_reference(2)
    assert {("say_to", knight["id"]), ("say_all", None)} <= _lines(state, document, villager)


def test_a_villager_the_knight_speaks_to_is_asked_the_next_minute_and_may_answer():
    state, document, knight, villager = _square()
    said = [_receipt(knight, _say(state, document, knight, to=villager), line="May I rest here?")]
    planned, events = advance_purposeful_society(state, SEED, [document])
    state, events, _ = advance_things(state, planned, SEED, document, events, (), decisions=said)
    # Walking on, it is asked because a line was said to it, and may say one to everyone near,
    # whom the knight, still within hearing, is among. A line by name goes to the nearest who
    # hear, at most the policy's ways of saying something less one, so the knight is named only
    # where fewer stand nearer.
    assert due(state, villager["id"])
    assert ("say_all", None) in _lines(state, document, villager)
    heard_by = {other["id"] for _, other in hearers(state, _being(state, villager), _reach())}
    assert knight["id"] in heard_by


def test_a_society_that_recorded_the_first_villager_offers_its_people_no_line(monkeypatch):
    seventh = {
        ground.navigation_profile: ground
        for ground in society_grounds.load_society_grounds(version=7)
    }
    # Composed as under the seventh catalog, which named the first villager.
    monkeypatch.setattr(society_grounds, "society_ground_for_navigation", seventh.__getitem__)
    state, document, knight, villager = _square()
    assert document["population_kind"] == _villager_reference(1)
    assert _lines(state, document, villager) == set()
    # The knight's own kind still lists saying, so it is offered a line to the villager.
    assert ("say_to", villager["id"]) in _lines(state, document, knight)


def test_a_society_no_model_decides_for_lives_the_same_with_either_villager(monkeypatch):
    """Saying is offered only to a being a model or the world's owner decides for, so the routine
    walks the same people the same way, minute by minute, under either catalog's villager."""

    def lives(version: int) -> list:
        read = {
            g.navigation_profile: g for g in society_grounds.load_society_grounds(version=version)
        }
        monkeypatch.setattr(society_grounds, "society_ground_for_navigation", read.__getitem__)
        document = compose((GATE, KNIGHT))
        assert document["population_kind"] == _villager_reference({7: 1, 8: 2}[version])
        state = copy.deepcopy(initial_things_society(SOCIETY, SEED, document, population=12))
        seen = []
        for _ in range(20):
            planned, events = advance_purposeful_society(state, SEED, [document])
            state, events, _ = advance_things(state, planned, SEED, document, events, ())
            people = [
                (p["id"], p["position_mm"], (p.get("route") or {}).get("node_ids"))
                for p in state["inhabitants"]
            ]
            seen.append(
                (people, [(e.kind, e.subject_id, e.document.get("summary")) for e in events])
            )
        return seen

    assert lives(7) == lives(8)
