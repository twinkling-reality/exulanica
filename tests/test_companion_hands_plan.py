"""The Companion's hands steps without a database: a being asked to pick a thing up, put it down,
give it or take it.

Read against independent sources: a society of things composed in memory, whose state says who
holds what; a step's body becomes the request the actions route builds from it, and a minute run
as the repository runs one does the act as asked. Kind labels are read from the kind catalog's
files.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import uuid
from pathlib import Path

import pytest
from exulanica.selection import action_plan as plan
from exulanica.selection import action_things as things
from exulanica.selection.action_plan import WorldEditOperation as Op
from exulanica.world.authored_delta import delta_sha256
from exulanica.world.society import society_state_sha256
from exulanica.world.society_actions import (
    ActionIntent,
    action_goal_policies,
    append_action_events,
    applied_hands,
    build_action_request,
)
from exulanica.world.society_planner import advance_purposeful_society
from exulanica.world.society_things import (
    advance_things,
    initial_things_society,
    validate_things_state,
)

import living_square_support as square
import test_companion_things_plan as cx1
from things_society_support import SEED, SOCIETY, compose, thing

KINDS = Path(__file__).resolve().parents[1] / "assets/catalogs/things/kinds"
GATE = thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593)
KNIGHT = thing("knight", "knight", 1, 3_000, 3_000)
#: Within reach of where the knight stands, as THINGS-H's tests place it.
SWORD = thing("sword", "sword", 2, 2_400, 2_600)
TRAVELLER = thing("traveller", "traveller", 2, 1_500, 3_000)
PLACED = (GATE, KNIGHT, SWORD, TRAVELLER)
ASKER = uuid.UUID(int=0xA5)


def _kind_label(kind: str, version: int) -> str:
    return json.loads((KINDS / f"{kind}.v{version}.json").read_text())["label"]


def _person(state, placed_id):
    return next(p for p in state["inhabitants"] if p["placed_id"] == placed_id)


def _thing(state, placed_id):
    return next(t for t in state["things"] if t["placed_id"] == placed_id)


def _scene():
    document = compose(PLACED)
    return initial_things_society(SOCIETY, SEED, document, population=4), document


def _world(state, document, *, asked: frozenset[str] = frozenset()) -> plan._World:
    """The reads a plan rests on, for this society's state, as the route reads them."""
    held = tuple(square.square_objects())
    version = dataclasses.replace(
        square.version(held),
        things=PLACED,
        state_sha256=delta_sha256(
            objects=held,
            element_overrides=(),
            environment_instances=(),
            point_map_instances=(),
            things=PLACED,
        ),
    )
    row = {
        "society_id": SOCIETY,
        "engine_version": "exulanica-society/v7",
        "region_id": "region:starter",
        "current_tick": state["tick"],
        "state_sha256": society_state_sha256(state),
        "state": state,
    }
    read = things.read_things(
        world_id=document["world_id"],
        version=version,
        reviewed={},
        looks={},
        society=(row, document, document["input_seq"], asked),
        elevation_mm=0,
        viewer=None,
    )
    return dataclasses.replace(cx1._world(read), world_id=document["world_id"])


def _label(choices, starts: str) -> str:
    [label] = [choice.label for choice in choices if choice.title.startswith(starts)]
    return label


def _draft(world, *steps):
    return plan._typed_from_draft(
        [{"operation": operation, "options": list(options)} for operation, *options in steps],
        world,
    )


def _recorded(state, document, body):
    """The request the actions route records for a step's body: its own builder, on its fields."""
    intent = body["intent"]
    return build_action_request(
        state,
        document,
        request_id=uuid.UUID(body["idempotency_key"]),
        requested_by=ASKER,
        subject_id=uuid.UUID(body["subject_id"]),
        intent=ActionIntent(
            kind="hands",
            target_id=intent["thing_id"],
            ability=intent["ability"],
            with_id=intent["with_id"],
        ),
    )


def _minute(state, document, requests=()):
    """One minute as the repository runs a society of things with requests and no receipts."""
    requests = list(requests)
    policies, dispositions = action_goal_policies(state, document, requests)
    planned, events = advance_purposeful_society(state, SEED, [document], goal_policy=policies)
    events = append_action_events(state, planned, document, requests, dispositions, events)
    after, events, _ = advance_things(
        state, planned, SEED, document, events, (), asked=applied_hands(requests, dispositions)
    )
    return after, events, dispositions


def _knight_holds_the_sword():
    """The scene a minute after the knight was asked to pick the sword up, and did."""
    state, document = _scene()
    world = _world(state, document)
    [action] = _draft(
        world, ("pick_up", _label(world.beings, "Knight"), _label(world.placed, "sword"))
    ).actions
    step = plan._prepared_things_step(0, action, cx1._context(), world)
    after, events, dispositions = _minute(
        state, document, [_recorded(state, document, step["body"])]
    )
    return state, after, document, step, events, dispositions


def test_a_drafted_pick_up_is_the_route_s_hands_request_and_its_minute_does_it_as_asked():
    state, after, _document, step, events, dispositions = _knight_holds_the_sword()
    knight, sword = _person(state, "knight"), _thing(state, "sword")

    assert step["action"] == {
        "operation": "direct_thing",
        "act": "pick_up",
        "subject_id": knight["id"],
        "thing_id": "sword",
        "with_id": None,
    }
    assert (step["state"], step["code"], step["operation"]) == ("prepared", None, plan.DIRECT)
    assert step["body"]["intent"] == {
        "kind": "hands",
        "ability": "pick_up",
        "thing_id": sword["id"],
        "with_id": None,
    }
    assert step["titles"] == {
        "subject": knight["display_name"],
        "act": "pick_up",
        "thing": _kind_label("sword", 2),
    }
    assert [(d.disposition, d.reason) for d in dispositions] == [("applied", "validated_user_act")]
    [picked] = [event for event in events if event.kind == "picked_up"]
    assert picked.document["reason"] == "asked_to_pick_up"
    assert _thing(after, "sword")["held_by"] == knight["id"]


def _holding():
    """The scene with the sword in the knight's hand as its asked pick-up left it, before the
    routine has moved anybody: the traveller still stands two metres from the knight."""
    state, after, document, _step, _events, _dispositions = _knight_holds_the_sword()
    state = copy.deepcopy(state)
    state["things"] = [
        copy.deepcopy(_thing(after, "sword")) if t["placed_id"] == "sword" else t
        for t in state["things"]
    ]
    validate_things_state(state)
    return state, document


@pytest.mark.parametrize("order", ["holder_first", "holder_second"])
def test_the_holder_gives_is_taken_from_and_puts_down_whatever_order_names_them(order):
    state, document = _holding()
    world = _world(state, document)
    knight, traveller = _person(state, "knight"), _person(state, "traveller")
    beings = [_label(world.beings, "Knight"), _label(world.beings, "Traveller")]
    if order == "holder_second":
        beings.reverse()
    sword = _label(world.placed, "sword")

    [give] = _draft(world, ("give", *beings, sword)).actions
    [take] = _draft(world, ("take", *beings, sword)).actions
    assert (give.subject_id, give.with_id, give.thing_id) == (
        knight["id"],
        traveller["id"],
        "sword",
    )
    assert (take.subject_id, take.with_id, take.thing_id) == (
        traveller["id"],
        knight["id"],
        "sword",
    )
    # Nothing named to put down: what the knight holds.
    [put_down] = _draft(world, ("put_down", _label(world.beings, "Knight"))).actions
    assert (put_down.subject_id, put_down.thing_id, put_down.with_id) == (
        knight["id"],
        "sword",
        None,
    )


def test_a_give_is_prepared_as_the_route_s_request_and_a_take_is_refused_by_its_name():
    state, document = _holding()
    world = _world(state, document)
    traveller = _person(state, "traveller")
    knight, other, sword = (
        _label(world.beings, "Knight"),
        _label(world.beings, "Traveller"),
        _label(world.placed, "sword"),
    )
    [give] = _draft(world, ("give", knight, other, sword)).actions
    given = plan._prepared_things_step(0, give, cx1._context(), world)
    assert (given["state"], given["code"]) == ("prepared", None)
    assert given["body"]["intent"] == {
        "kind": "hands",
        "ability": "give",
        "thing_id": _thing(state, "sword")["id"],
        "with_id": traveller["id"],
    }
    assert given["titles"]["with"] == traveller["display_name"]
    # No shipped kind lets a thing be taken from it, so a take is never offered.
    letting = [
        path.name
        for path in KINDS.glob("*.json")
        if "let_take" in json.loads(path.read_text()).get("offers", {})
    ]
    assert letting == []
    [take] = _draft(world, ("take", other, knight, sword)).actions
    taken = plan._prepared_things_step(0, take, cx1._context(), world)
    assert (taken["state"], taken["code"], taken["body"]) == ("blocked", "act_not_offered", None)


def test_a_kind_an_earlier_step_adds_names_that_thing_in_a_later_hands_step():
    state, document = _scene()
    world = _world(state, document)
    traveller = _label(world.beings, "Traveller")
    # "give the blocky one a lantern": a lantern beside the traveller, then the traveller asked
    # to pick up that lantern, by the id its first step was minted.
    placed, pick_up = _draft(
        world, ("place_thing", "lantern", traveller), ("pick_up", traveller, "lantern")
    ).actions
    assert (placed.operation, placed.kind) == (Op.PLACE_THING, "lantern")
    assert pick_up.thing_id == placed.thing_id and things.valid_minted_id(
        pick_up.thing_id, "lantern"
    )
    assert pick_up.subject_id == _person(state, "traveller")["id"]
    assert plan._titles(pick_up, world) == {
        "subject": _person(state, "traveller")["display_name"],
        "act": "pick_up",
        "thing": _kind_label("lantern", 1),
    }


def test_an_earlier_step_s_act_decides_who_holds_the_thing_for_the_steps_after_it():
    state, document = _scene()
    world = _world(state, document)
    knight, traveller = _label(world.beings, "Knight"), _label(world.beings, "Traveller")
    sword = _label(world.placed, "sword")
    assert _thing(state, "sword")["held_by"] is None
    # Nobody holds the sword yet; once the first step has the knight pick it up, the knight is
    # the one who gives it, though the traveller is named first.
    _picked, given = _draft(
        world, ("pick_up", knight, sword), ("give", traveller, knight, sword)
    ).actions
    assert (given.subject_id, given.with_id) == (
        _person(state, "knight")["id"],
        _person(state, "traveller")["id"],
    )


@pytest.mark.parametrize(
    ("change", "code"),
    [
        # The positive control: nothing changed, the pick-up is prepared.
        (None, None),
        # A thing a visitor here brought goes home with it; only the visitor hands it over.
        ("brought", "belongs_to_visitor"),
        # The society no longer holds the thing.
        ("gone", "thing_gone"),
    ],
)
def test_a_hands_step_the_route_refuses_is_blocked_by_the_route_s_own_name(change, code):
    state, document = _scene()
    state = copy.deepcopy(state)
    if change == "brought":
        _thing(state, "sword")["brought_by"] = _person(state, "traveller")["id"]
    if change == "gone":
        state["things"] = [t for t in state["things"] if t["placed_id"] != "sword"]
    world = _world(state, document)
    [action] = _draft(
        world, ("pick_up", _label(world.beings, "Knight"), _label(world.placed, "sword"))
    ).actions
    step = plan._prepared_things_step(0, action, cx1._context(), world)
    assert (step["state"], step["code"]) == (
        ("prepared", None) if code is None else ("blocked", code)
    )


def test_which_thing_is_asked_about_when_two_or_none_are_named():
    state, document = _scene()
    world = _world(state, document)
    knight = _label(world.beings, "Knight")
    two = _draft(
        world, ("pick_up", knight, _label(world.placed, "sword"), _label(world.placed, "gate"))
    )
    assert two.clarification["code"] == "thing_ambiguous"
    assert [c["value"] for c in two.clarification["candidates"]] == ["sword", "gate"]
    assert two.clarification["actions"][0]["thing_id"] is None
    [none] = _draft(world, ("pick_up", knight)).actions
    asked = plan._requirements([none], cx1._context(), world)
    assert asked["code"] == "thing_ambiguous" and asked["slot"] == "thing_id"
    assert {c["value"] for c in asked["candidates"]} == {"gate", "sword"}
