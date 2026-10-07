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

import ast
import copy
import json
import uuid
from pathlib import Path

import pytest
from exulanica.world import society_things
from exulanica.world.crossings import CrossingRefused, check_crossing
from exulanica.world.deciders import arrival_deciders
from exulanica.world.role_decisions import DecisionDisposition
from exulanica.world.roles import person as person_adapter
from exulanica.world.society import society_state_sha256
from exulanica.world.society_decision_contract import (
    choice_options,
    hearers,
    observed_context,
    person_role,
)
from exulanica.world.society_planner import (
    advance_purposeful_society,
    initial_purposeful_society,
    input_sha256,
)
from exulanica.world.society_things import (
    THING_NAMESPACE,
    THING_OUTCOMES,
    THING_REASONS,
    THINGS_PROFILE,
    VISITORS_MAXIMUM,
    advance_things,
    initial_things_society,
    kind_allows,
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


def test_genesis_makes_its_people_of_the_kind_its_input_names():
    # The input records the kind its ground's catalog entry named when it was composed, and genesis
    # reads it there: an input naming another being makes the same people, of that kind.
    document = compose((GATE,))
    named = copy.deepcopy(document)
    named["population_kind"] = reference("traveller", 1)
    named["document_sha256"] = input_sha256(named)
    state = initial_things_society(SOCIETY, SEED, named, population=POPULATION)
    villagers = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    assert [(p["id"], p["display_name"], p["kind"]["kind"]) for p in state["inhabitants"]] == [
        (p["id"], p["display_name"], "traveller") for p in villagers["inhabitants"]
    ]
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
    # A crossing the society cannot read is refused and bound, never stopping the minute: its event
    # names its crossing and nothing from its document.
    broken = arrival(6)
    broken.document["profile"] = "exulanica.thing-arrival/v9"
    lost = departure(visitor["id"], 11)
    lost.document["reason"] = "wandered_off"
    for crossing, kind in ((broken, "arrival_refused"), (lost, "departure_refused")):
        with pytest.raises(CrossingRefused):
            check_crossing(crossing)  # the positive control: its check does refuse it
        after, events, bound = _minute(state, document, [crossing])
        assert [(b.disposition, b.reason) for b in bound] == [("refused", "malformed_crossing")]
        [event] = [e for e in events if e.event_id == bound[0].event_id]
        assert (event.kind, str(event.subject_id)) == (kind, str(crossing.crossing_id))
        assert event.document["thing"] == {"crossing_id": str(crossing.crossing_id)}
        validate_things_state(after)
    # A visitor, or a thing it carries, whose id is already somebody's or something's here.
    villager = _person(state, came_by="populated")
    well = next(t for t in state["things"] if t["placed_id"] == "well")
    sword = reference("sword", 2)
    for colliding in (
        arrival(7, carried=[{"thing_id": villager["id"], "kind": sword}]),
        arrival(8, carried=[{"thing_id": well["id"], "kind": sword}]),
    ):
        _, _, bound = _minute(state, document, [colliding])
        assert [(b.disposition, b.reason) for b in bound] == [("refused", "already_here")]


def test_a_placed_being_whose_id_a_visitor_holds_is_refused_by_name_until_it_moves():
    state = _genesis(GATE)
    document = compose((GATE,))
    held = str(uuid.uuid5(THING_NAMESPACE, f"{document['world_id']}:knight"))
    taken = arrival(1)
    taken.document["thing_id"] = held
    state, _, bound = _minute(state, document, [taken])
    assert [b.disposition for b in bound] == ["arrived"]
    placed = compose((GATE, KNIGHT), input_seq=2, edit_seq=EDITS + 1)
    planned, events = advance_purposeful_society(state, SEED, [document, placed])
    state, events, _ = advance_things(state, planned, SEED, placed, events)
    [refused] = [e for e in events if e.kind == "arrival_refused"]
    assert (refused.document["reason"], refused.document["thing"]["placed_id"]) == (
        "id_taken",
        "knight",
    )
    assert [r["reason"] for r in state["refused_placements"]] == ["id_taken"]
    # The refusal holds while the placement does: the next minute says nothing more.
    planned, events = advance_purposeful_society(state, SEED, [placed])
    state, events, _ = advance_things(state, planned, SEED, placed, events)
    assert not [e for e in events if e.kind == "arrival_refused"]
    # Moved, it is a new placement, tried again.
    moved = compose(
        (GATE, thing("knight", "knight", 1, -2_000, 4_000)), input_seq=3, edit_seq=EDITS + 2
    )
    planned, events = advance_purposeful_society(state, SEED, [placed, moved])
    state, events, _ = advance_things(state, planned, SEED, moved, events)
    assert [e.document["reason"] for e in events if e.kind == "arrival_refused"] == ["id_taken"]
    assert [r["placed_at_mm"] for r in state["refused_placements"]] == [[-2_000, 4_000]]


def test_a_being_refused_for_a_full_society_waits_silently_and_comes_when_there_is_room(
    monkeypatch,
):
    import exulanica.world.society_things as engine

    full = {"now": True}
    monkeypatch.setattr(engine._Minute, "full", lambda self: full["now"])
    state = _genesis(GATE)
    document = compose((GATE,))
    placed = compose((GATE, KNIGHT), input_seq=2, edit_seq=EDITS + 1)
    planned, events = advance_purposeful_society(state, SEED, [document, placed])
    state, events, _ = advance_things(state, planned, SEED, placed, events)
    assert [e.document["reason"] for e in events if e.kind == "arrival_refused"] == ["society_full"]
    planned, events = advance_purposeful_society(state, SEED, [placed])
    state, events, _ = advance_things(state, planned, SEED, placed, events)
    assert not [e for e in events if e.kind in ("arrival_refused", "thing_arrived")]
    full["now"] = False
    planned, events = advance_purposeful_society(state, SEED, [placed])
    state, events, _ = advance_things(state, planned, SEED, placed, events)
    assert [e.document["reason"] for e in events if e.kind == "thing_arrived"] == [
        "placed_by_author"
    ]
    assert state["refused_placements"] == []


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
        (lambda p: p.update(mode="walking"), "a walker states no mode"),
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


WORDS = Path(__file__).resolve().parents[1] / (
    "assets/catalogs/society-words/society-inhabitant-words.v1.json"
)


def _emitted() -> tuple[set[str], set[str]]:
    """Every reason and outcome the things phase's source passes to an ``emit`` as text."""
    reasons: set[str] = set()
    outcomes: set[str] = set()

    def texts(node: ast.AST) -> list[str]:
        if isinstance(node, ast.IfExp):
            return [*texts(node.body), *texts(node.orelse)]
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        return []

    tree = ast.parse(Path(society_things.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "emit"
            and len(node.args) >= 4
        ):
            reasons.update(texts(node.args[2]))
            outcomes.update(texts(node.args[3]))
    return reasons, outcomes


def test_every_reason_and_outcome_the_things_phase_records_is_stated_and_has_words():
    reasons, outcomes = _emitted()
    # The positive control: the scan reads the reasons and outcomes the phase writes as text.
    assert {"placed_by_author", "crossed_in"} <= reasons and {"arrived", "not_arrived"} <= outcomes
    assert reasons <= THING_REASONS
    assert outcomes <= set(THING_OUTCOMES)
    codes = {(entry["kind"], entry["code"]) for entry in json.loads(WORDS.read_text())["entries"]}
    assert sorted(r for r in THING_REASONS if ("event_reason", r) not in codes) == []
    assert sorted(o for o in THING_OUTCOMES if ("outcome", o) not in codes) == []


def test_only_the_deciders_a_kind_allows_may_decide_for_its_beings():
    state = _genesis(GATE, KNIGHT)
    state, _, _ = _minute(state, compose((GATE, KNIGHT)), [arrival(1)])
    villager = _person(state, came_by="populated")
    knight = _person(state, came_by="placed")
    visitor = _person(state, came_by="crossed")
    allowed = {
        name: {
            kind
            for kind in ("routine", "model", "person", "external")
            if kind_allows(state, person["id"], kind)
        }
        for name, person in (("villager", villager), ("knight", knight), ("visitor", visitor))
    }
    assert allowed == {
        "villager": {"routine", "model", "person"},
        "knight": {"routine", "model", "person", "external"},
        "visitor": {"external"},
    }
    # A society whose people state no kind leaves the choice to its own rules.
    purposeful = initial_purposeful_society(SOCIETY, SEED, compose(()), population=POPULATION)
    assert kind_allows(purposeful, purposeful["inhabitants"][0]["id"], "external")


# -- lines, going on and leaving (3a3) -----------------------------------------------------------


def _things_contract():
    role = person_role()
    return role.contract(role.terms(THINGS_PROFILE).versions)


def _beside(state, mover, anchor, dx_mm=2_000):
    """``state`` with ``mover`` standing ``dx_mm`` east of ``anchor``."""
    moved = copy.deepcopy(state)
    target = next(p for p in moved["inhabitants"] if p["id"] == mover["id"])
    target["position_mm"] = [anchor["position_mm"][0] + dx_mm, anchor["position_mm"][1]]
    return moved


def _under_way(state, person_id):
    """``state`` with something under way for ``person_id``: a goal and an active action."""
    busy = copy.deepcopy(state)
    person = next(p for p in busy["inhabitants"] if p["id"] == person_id)
    person["goal"] = person["goal"] or {"kind": "stand"}
    person["action"] = {**person["action"], "status": "active"}
    return busy


def _receipt(person, option, *, line=None, status="accepted", reason="validated_choice"):
    proposal = None
    if status == "accepted":
        proposal = {"label": option.label, "option": option.as_record()}
        if line is not None:
            proposal["line"] = line
    receipt = {
        "subject_id": person["id"],
        "request_id": str(uuid.uuid4()),
        "status": status,
        "reason": reason,
        "proposal": proposal,
        "provider": None if status != "accepted" else {"provider": "test", "model_id": "m"},
    }
    disposition = DecisionDisposition(
        decision_seq=1,
        request_id=receipt["request_id"],
        subject_id=person["id"],
        disposition="applied" if status == "accepted" else status,
        reason=reason,
        decision_sha256="0" * 64,
    )
    return receipt, disposition


def _decided_minute(state, document, decisions):
    planned, events = advance_purposeful_society(state, SEED, [document])
    return advance_things(state, planned, SEED, document, events, (), decisions=decisions)


def near_of(state, speaker, contract):
    return hearers(state, speaker, contract.value("hearing_reach_mm"))


def test_a_being_that_can_say_something_is_offered_to_say_it_to_whoever_hears_it():
    document = compose((GATE, KNIGHT))
    state = _genesis(GATE, KNIGHT)
    knight = _person(state, came_by="placed")
    villager = _person(state, came_by="populated")
    state = _beside(state, villager, knight)
    contract = _things_contract()
    options = choice_options(state, document, knight["id"], contract, seed=SEED)
    said = sorted(
        (o for o in options if o.kind == "say_to"),
        key=lambda o: [p["id"] for _d, p in near_of(state, knight, contract)].index(o.addressee_id),
    )
    near = near_of(state, knight, contract)
    assert villager["id"] in {p["id"] for _d, p in near}
    # The nearest who hear, at most the policy's ways of saying something less one, nearest first.
    assert [o.addressee_id for o in said] == [
        p["id"] for _d, p in near[: contract.value("say_options_maximum") - 1]
    ]
    for option, (distance, other) in zip(said, near, strict=False):
        assert option.label == (
            f"say something to the villager (person {other['ordinal'] + 1}), "
            f"{round(distance / 1000)} m away"
        )
    assert "say_all" in {o.kind for o in options}
    assert "leave" not in {o.kind for o in options}
    # Under the role's own contract, as every other engine's people are asked, nothing is said.
    plain = choice_options(state, document, knight["id"], person_role().contract(), seed=SEED)
    assert not {o.kind for o in plain} & {"say_to", "say_all", "carry_on", "leave"}
    # A villager's kind cannot say anything, so it is offered no line.
    theirs = choice_options(state, document, villager["id"], contract, seed=SEED)
    assert not {o.kind for o in theirs} & {"say_to", "say_all"}


def test_a_being_with_something_under_way_may_go_on_say_something_or_leave():
    document = compose((GATE, KNIGHT))
    state = _genesis(GATE, KNIGHT)
    state, _, _ = _minute(state, document, [arrival(1)])
    knight = _person(state, came_by="placed")
    visitor = _person(state, came_by="crossed")
    state = _beside(state, visitor, knight)
    contract = _things_contract()
    busy = _under_way(state, knight["id"])
    kinds = {o.kind for o in choice_options(busy, document, knight["id"], contract, seed=SEED)}
    assert "carry_on" in kinds and "say_to" in kinds and "wait" not in kinds
    assert not kinds & {"target", "stand", "talk"}
    away = _under_way(state, visitor["id"])
    kinds = {o.kind for o in choice_options(away, document, visitor["id"], contract, seed=SEED)}
    assert {"carry_on", "leave"} <= kinds
    # A program deciding from outside is asked every minute; a model, only at a choice point.
    assert person_adapter.due_from_outside(away, visitor["id"])
    assert not person_adapter.due(away, visitor["id"])
    # Somebody with nothing to say and no way to leave is not asked while something is under way.
    villager = _person(state, came_by="populated")
    idle = _under_way(state, villager["id"])
    assert choice_options(idle, document, villager["id"], contract, seed=SEED) == ()


def test_a_line_is_heard_within_reach_and_makes_the_one_it_was_said_to_due():
    document = compose((GATE, KNIGHT))
    state = _genesis(GATE, KNIGHT)
    knight = _person(state, came_by="placed")
    villagers = [p for p in state["inhabitants"] if p["came_by"] == "populated"]
    near, far = villagers[0], villagers[1]
    state = _beside(state, near, knight)
    state = _beside(state, far, knight, dx_mm=20_000)
    contract = _things_contract()
    options = choice_options(state, document, knight["id"], contract, seed=SEED)
    (to_near,) = [o for o in options if o.kind == "say_to" and o.addressee_id == near["id"]]
    after, events, _ = _decided_minute(
        state, document, [_receipt(knight, to_near, line="good morning")]
    )
    [said] = [e for e in events if e.kind == "said"]
    assert said.document["thing"]["line"] == "good morning"
    assert said.document["thing"]["to"] == near["id"]
    assert near["id"] in said.document["thing"]["heard_by"]
    assert far["id"] not in said.document["thing"]["heard_by"]
    assert said.document["thing"]["decider"] == "model"
    # The event names the speaker and the one it was said to by kind and number, as the minute
    # began, so it is worded without the state.
    assert (said.document["thing"]["from_kind"], said.document["thing"]["from_number"]) == (
        knight["kind"],
        knight["ordinal"] + 1,
    )
    assert (said.document["thing"]["to_kind"], said.document["thing"]["to_number"]) == (
        near["kind"],
        near["ordinal"] + 1,
    )
    # Said to everyone near, it names no one it was said to.
    (to_all,) = [o for o in options if o.kind == "say_all"]
    [aloud] = [
        e
        for e in _decided_minute(state, document, [_receipt(knight, to_all, line="hello all")])[1]
        if e.kind == "said"
    ]
    assert [aloud.document["thing"][key] for key in ("to", "to_kind", "to_number")] == [None] * 3
    assert aloud.document["thing"]["from_number"] == knight["ordinal"] + 1
    heard = _person(after, id=near["id"])["heard"]
    assert heard[-1] == {
        "tick": after["tick"],
        "from": knight["id"],
        "from_kind": knight["kind"],
        "from_number": knight["ordinal"] + 1,
        "to": near["id"],
        "line": "good morning",
    }
    assert "heard" not in _person(after, id=far["id"])
    validate_things_state(after)
    # The one it was said to is asked the next minute, whatever is under way for them.
    busy = _under_way(after, near["id"])
    assert person_adapter.due(busy, near["id"])
    # Every line kept is among the last the contract keeps, the oldest dropped first.
    current = state
    kept = _things_contract().value("lines_heard_maximum")
    for index in range(kept + 1):
        receipt = _receipt(knight, to_near, line=f"line {index}")
        current = _decided_minute(current, document, [receipt])[0]
        # Beside the knight where it now stands, so the next line carries to them too.
        knight = _person(current, id=knight["id"])
        current = _beside(current, near, knight)
    lines = [entry["line"] for entry in _person(current, id=near["id"])["heard"]]
    assert lines == [f"line {index}" for index in range(1, kept + 1)]
    # The positive control: somebody busy that nobody spoke to is not.
    other = next(p for p in villagers if p["id"] not in (near["id"], far["id"]))
    assert not person_adapter.due(_under_way(after, other["id"]), other["id"])
    # What they heard is in their next request's context, quoted, and named by kind and number.
    seen = observed_context(busy, document, near["id"], (), profile="p")["heard"]
    assert seen[-1]["from"] == f"the knight (person {knight['ordinal'] + 1})"
    assert seen[-1]["to_you"] is True


def test_a_visitor_leaves_when_it_chooses_and_when_its_program_stays_quiet():
    document = compose((GATE, KNIGHT))
    state = _genesis(GATE, KNIGHT)
    state, _, _ = _minute(state, document, [arrival(1)])
    visitor = _person(state, came_by="crossed")
    contract = _things_contract()
    leave = next(
        o
        for o in choice_options(state, document, visitor["id"], contract, seed=SEED)
        if o.kind == "leave"
    )
    after, events, _ = _decided_minute(state, document, [_receipt(visitor, leave)])
    [left] = [e for e in events if e.kind == "thing_departed"]
    assert left.document["reason"] == "chose_to_leave"
    assert not [p for p in after["inhabitants"] if p["came_by"] == "crossed"]
    # Quiet minutes: a program that does not answer, five minutes in a row, sends it home; a pass
    # is an answer and starts the count again.
    quiet = _receipt(visitor, None, status="unavailable", reason="no_answer_in_time")
    passed = _receipt(visitor, None, status="unavailable", reason="decider_passed")
    current = state
    for minute in range(4):
        current, events, _ = _decided_minute(current, document, [quiet])
        assert _person(current, came_by="crossed")["quiet_minutes"] == minute + 1
    current, events, _ = _decided_minute(current, document, [passed])
    assert "quiet_minutes" not in _person(current, came_by="crossed")
    for _ in range(4):
        current, events, _ = _decided_minute(current, document, [quiet])
    current, events, _ = _decided_minute(current, document, [quiet])
    assert [e.document["reason"] for e in events if e.kind == "thing_departed"] == ["decider_lost"]
    assert not [p for p in current["inhabitants"] if p["came_by"] == "crossed"]
