"""The Companion's steps that spend nothing, without a database or a model: a placed thing moved or
taken away, a being played and given back, everyone sent away and brought back.

Each step is the request its own route takes, read here against that route's own body model, with
the route's checks run in process and a refusal the route's own code. What the real routes answer
is in ``tests/test_companion_free_steps_postgres.py``. The worlds are the things plan tests'
(``test_companion_things_plan``) and the action plan tests' clock (``test_companion_action_plan``).
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from exulanica.api.routes.selection_actions import PrepareRequest
from exulanica.api.routes.society import PresenceBody
from exulanica.api.routes.society_play import GiveBackBody, PlayBody
from exulanica.api.routes.world_things import MoveThingBody
from exulanica.api.world_edit import BaseStateBody
from exulanica.selection import action_plan as plan
from exulanica.selection import action_things as things
from exulanica.selection.action_plan import (
    PLAY,
    PLAY_GIVE_BACK,
    PRESENCE,
    THING_MOVE,
    THING_REMOVE,
)
from exulanica.selection.action_plan import WorldEditOperation as Op

from test_companion_action_plan import _clock, _descriptor, _simulation_world
from test_companion_things_plan import BEING, VERSION, WELL, _context, _read, _world

KNIGHT = str(uuid.UUID(int=1))
#: The knight an author placed as the thing ``knight-1``, standing where the fixture's first being
#: stands, and a villager nobody placed.
STATE = {
    "inhabitants": [
        {"id": KNIGHT, "placed_id": "knight-1", "display_name": "Traveller"},
        {"id": str(uuid.UUID(int=2)), "display_name": "Traveller 2"},
    ]
}
KNIGHT_AT = things.Footprint(3_000, -3_000, BEING)


def _town() -> plan._World:
    read = _read()
    read = dataclasses.replace(
        read,
        society=dataclasses.replace(read.society, state=STATE),
        anchors={**read.anchors, ("thing", "knight-1"): (KNIGHT_AT, "region:starter", 0)},
        taken=(*read.taken, ("knight-1", KNIGHT_AT)),
    )
    return _world(read)


def _spot(x_mm: int, z_mm: int, region: str = "region:starter") -> plan._Context:
    transform = {"x_mm": x_mm, "y_mm": 0, "z_mm": z_mm, "yaw_microradians": 0, "scale_milli": 1000}
    return _context(
        context={
            "placement": {"region_id": region, "transform": transform},
            "viewer": {"x_mm": 0, "z_mm": 0, "yaw_microradians": 0, "region_id": None},
            "selected_object_id": None,
        }
    )


def _draft(world: plan._World, operation: str, *options: str) -> plan._Verdict:
    return plan._typed_from_draft([{"operation": operation, "options": list(options)}], world)


def _planned(world, context, operation: str, *options: str) -> dict:
    return plan._world_edit_document(
        _draft(world, operation, *options), context, world, previewer=None
    )


# -- a placed thing moved or taken away ------------------------------------------------------------


def test_a_listed_thing_named_by_a_move_or_a_removal_is_the_things_route_s():
    world = _town()
    [moved] = _draft(world, "move_object", "thing-1").actions
    assert (moved.operation, moved.thing_id) == (Op.MOVE_THING, "well")
    assert moved.document() == {"operation": "move_thing", "thing_id": "well"}
    [removed] = _draft(world, "remove_object", "thing-1").actions
    assert (removed.operation, removed.thing_id) == (Op.REMOVE_THING, "well")
    # An object is still the objects routes'.
    [bench] = _draft(world, "remove_object", "object-1").actions
    assert (bench.operation, bench.object_id) == (Op.REMOVE_OBJECT, "object:bench-for-ada")


def test_a_being_an_author_placed_is_moved_as_the_thing_it_was_placed_as():
    world = _town()
    placed, unplaced = world.beings[0], world.beings[1]
    assert (placed.value, unplaced.value) == (KNIGHT, str(uuid.UUID(int=2)))
    [action] = _draft(world, "remove_object", placed.label).actions
    assert (action.operation, action.thing_id) == (Op.REMOVE_THING, "knight-1")
    # One of the world's own people is no placed thing: nothing is named, and the removal asks.
    verdict = _draft(world, "remove_object", unplaced.label)
    [nobody] = verdict.actions
    assert (nobody.operation, nobody.object_id) == (Op.REMOVE_OBJECT, None)
    asked = plan._world_edit_document(verdict, _context(), world, previewer=None)
    assert asked["clarification"]["code"] == "object_required"


def test_a_kind_or_a_place_named_in_a_move_stands_for_the_thing():
    world = _town()
    # "The well" named by its kind in the list of things that can be added, or by its place.
    [by_kind] = _draft(world, "move_object", "well").actions
    assert (by_kind.operation, by_kind.thing_id) == (Op.MOVE_THING, "well")
    place = next(choice.label for choice in world.places if choice.value == "thing:well:visit")
    [by_place] = _draft(world, "remove_object", place).actions
    assert (by_place.operation, by_place.thing_id) == (Op.REMOVE_THING, "well")
    # Named both ways at once, it is still one thing, and nothing is asked.
    both = _draft(world, "move_object", "thing-1", "well", place)
    assert both.clarification is None and both.actions[0].thing_id == "well"
    # A kind nothing here is of names nothing.
    [nothing] = _draft(world, "remove_object", "lantern").actions
    assert (nothing.operation, nothing.object_id) == (Op.REMOVE_OBJECT, None)


def test_a_removal_is_the_route_s_request_for_that_thing():
    world = _town()
    document = _planned(world, _context(), "remove_object", "thing-1")
    assert document["outcome"] == "plan", document.get("refusal")
    [step] = document["steps"]
    assert (step["operation"], step["state"]) == (THING_REMOVE, "prepared")
    assert step["bind"] == {"version_id": str(VERSION), "thing_id": "well"}
    BaseStateBody.model_validate(step["body"])
    assert step["body"]["base_state_sha256"] == world.state_sha256
    assert step["pins"] == {"base_state_sha256": world.state_sha256, "edit_seq": world.edit_seq}
    assert step["titles"] == {"thing": "well"}
    assert step["spends"] is False and step["compensation"] == {"operation": plan.THING_UNDO}


def test_a_move_goes_to_the_pointed_spot_in_the_thing_s_own_region_turned_to_the_person():
    world = _town()
    # A free spot 2 m east and 1 m north of the person, who stands at the origin.
    document = _planned(world, _spot(2_000, -1_000), "move_object", "thing-1")
    assert document["outcome"] == "plan", document.get("refusal")
    [step] = document["steps"]
    assert (step["operation"], step["state"]) == (THING_MOVE, "prepared")
    assert step["bind"] == {"version_id": str(VERSION), "thing_id": "well"}
    sent = MoveThingBody.model_validate(step["body"])
    assert (sent.pose.x_mm, sent.pose.y_mm, sent.pose.z_mm) == (2_000, 0, -1_000)
    assert sent.pose.yaw_microradians == things.facing_yaw((2_000, -1_000), (0, 0), otherwise=0)
    # Moved onto where it already stands, the thing is not in its own way.
    back = _planned(world, _spot(WELL.x_mm, WELL.z_mm), "move_object", "thing-1")
    pose = back["steps"][0]["body"]["pose"]
    assert (pose["x_mm"], pose["z_mm"]) == (WELL.x_mm, WELL.z_mm)


def test_a_move_the_route_would_refuse_is_blocked_by_its_code_and_one_with_no_spot_is_asked():
    world = _town()
    elsewhere = _planned(world, _spot(2_000, -1_000, "region:other"), "move_object", "thing-1")
    assert elsewhere["outcome"] == "refused"
    assert elsewhere["steps"][0]["code"] == "invalid_thing_placement"
    assert elsewhere["steps"][0]["body"] is None
    far = _planned(world, _spot(10**12, 0), "move_object", "thing-1")
    assert far["steps"][0]["code"] == "invalid_thing_placement"
    gone = plan._world_edit_document(
        plan._typed_from_request([{"operation": "remove_thing", "thing_id": "lantern-9"}], world),
        _context(),
        world,
        previewer=None,
    )
    assert gone["steps"][0]["code"] == "invalid_object_state"
    unpointed = _context(context={"placement": None, "viewer": None, "selected_object_id": None})
    asked = _planned(world, unpointed, "move_object", "thing-1")
    assert asked["clarification"]["code"] == "placement_required"


# -- a being played and given back -----------------------------------------------------------------


class Plays:
    """A stand-in for the play record's checks (``Play``): the answers are the test's own."""

    def __init__(self, *, code=None, playing=False, played=(), choice_seq=6):
        self.answer = {
            "code": code,
            "playing": playing,
            "played": list(played),
            "choice_seq": choice_seq,
        }
        self.asked: list[str | None] = []

    def play_preview(self, subject):
        self.asked.append(subject)
        return self.answer


def _granted(_operation: str) -> tuple[list[str], bool]:
    return ["world.write"], True


def _playable(plays: Plays, world: plan._World | None = None) -> plan._World:
    world = _town() if world is None else world
    return plan._with_play(dataclasses.replace(world, society_held=True), _granted, plays)


def test_playing_a_being_is_the_play_route_s_request_and_spends_nothing():
    plays = Plays()
    world = _playable(plays)
    document = _planned(world, _context(), "play_being", world.beings[0].label)
    assert document["outcome"] == "plan", document.get("refusal")
    [step] = document["steps"]
    assert (step["operation"], step["state"], step["confirmation"]) == (
        PLAY,
        "prepared",
        "required",
    )
    assert step["bind"] == {"version_id": str(VERSION)}
    sent = PlayBody.model_validate(step["body"])
    assert str(sent.subject_id) == KNIGHT and set(step["body"]) == set(PlayBody.model_fields)
    assert step["spends"] is False and document["spends"] is False
    assert step["titles"] == {"subject": "Traveller"}
    assert step["compensation"] == {"operation": PLAY_GIVE_BACK}
    assert step["pins"] == {"choice_seq": 6}
    assert plays.asked == [KNIGHT]
    # The same plan asks with the same key; after any other choice, with another.
    again = _planned(world, _context(), "play_being", world.beings[0].label)
    assert again["steps"][0]["body"] == step["body"]
    later = _playable(Plays(choice_seq=7))
    moved_on = _planned(later, _context(), "play_being", later.beings[0].label)
    assert moved_on["steps"][0]["body"]["idempotency_key"] != step["body"]["idempotency_key"]


@pytest.mark.parametrize(
    "code", ["engine_takes_no_play", "being_played", "decided_from_outside", "decider_not_allowed"]
)
def test_a_play_the_route_would_refuse_is_blocked_by_its_code(code):
    world = _playable(Plays(code=code))
    document = _planned(world, _context(), "play_being", world.beings[0].label)
    assert document["outcome"] == "refused"
    assert (document["steps"][0]["state"], document["steps"][0]["code"]) == ("blocked", code)
    assert document["steps"][0]["body"] is None


def test_playing_the_being_one_plays_already_changes_nothing_and_nobody_named_is_asked():
    world = _playable(Plays(playing=True, played=[KNIGHT]))
    document = _planned(world, _context(), "play_being", world.beings[0].label)
    assert document["steps"][0]["code"] == "no_change"
    nobody = _planned(world, _context(), "play_being")
    assert nobody["clarification"]["code"] == "being_required"


def test_giving_back_names_the_being_the_person_plays():
    plays = Plays(played=[KNIGHT])
    world = _playable(plays)
    document = _planned(world, _context(), "give_back")
    assert document["outcome"] == "plan", document.get("refusal")
    [step] = document["steps"]
    assert (step["operation"], step["state"]) == (PLAY_GIVE_BACK, "prepared")
    assert step["bind"] == {"version_id": str(VERSION), "subject_id": KNIGHT}
    assert set(step["body"]) == set(GiveBackBody.model_fields)
    GiveBackBody.model_validate(step["body"])
    assert step["action"] == {"operation": "give_back", "subject_id": KNIGHT}
    assert step["titles"] == {"subject": "Traveller"} and step["spends"] is False
    assert plays.asked == [None]
    # Playing nobody, there is nothing to give back: the route's own name.
    idle = _playable(Plays())
    refused = _planned(idle, _context(), "give_back")
    assert refused["steps"][0]["code"] == "not_played"


def test_without_the_route_s_object_or_a_society_playing_is_not_offered():
    bare = plan._with_play(_town(), _granted, None)
    assert PLAY not in bare.descriptors and PLAY_GIVE_BACK not in bare.descriptors
    refused = _planned(bare, _context(), "play_being", bare.beings[0].label)
    assert refused["refusal"]["code"] == "action_not_offered"
    empty = plan._with_play(dataclasses.replace(_town(), society_held=False), _granted, Plays())
    nobody = _planned(empty, _context(), "play_being", empty.beings[0].label)
    assert nobody["refusal"]["code"] == "action_unavailable"
    assert nobody["refusal"]["capability"]["code"] == "society_unavailable"
    ungranted = plan._with_play(
        dataclasses.replace(_town(), society_held=True),
        lambda _op: (["world.write"], False),
        Plays(),
    )
    denied = _planned(ungranted, _context(), "play_being", ungranted.beings[0].label)
    assert denied["refusal"]["code"] == "action_not_permitted"


# -- everyone sent away and brought back -----------------------------------------------------------

SIM = plan.SimulationAction


def _presence_world(state: dict | None = None, **descriptors) -> plan._World:
    world = _simulation_world(**{PRESENCE: _descriptor(PRESENCE), **descriptors})
    if state is None:
        return world
    read = _read()
    held = dataclasses.replace(read, society=dataclasses.replace(read.society, state=state))
    return dataclasses.replace(world, things=held)


def _presence_plan(action, world: plan._World, clock: dict | None = None) -> dict:
    return plan.simulation_document(
        plan._Simulation(action), _context(), world, clock or _clock(), plan.TimeSpending()
    )


def test_sending_everyone_away_is_the_presence_route_s_request_pinned_to_the_minute_read():
    world = _presence_world({"inhabitants": [{"id": KNIGHT}], "presence": None})
    document = _presence_plan(SIM.SEND_AWAY, world)
    assert document["outcome"] == "plan", document.get("refusal")
    assert document["kind"] == "simulation" and document["spends"] is False
    [step] = document["steps"]
    assert (step["operation"], step["state"], step["confirmation"]) == (
        PRESENCE,
        "prepared",
        "required",
    )
    sent = PresenceBody.model_validate(step["body"])
    assert set(step["body"]) == set(PresenceBody.model_fields)
    assert (sent.presence, sent.base_tick, sent.base_state_sha256) == ("away", 12, "b" * 64)
    assert step["pins"] == {"clock_revision": 0, "tick": 12, "society_state_sha256": "b" * 64}
    assert step["action"]["operation"] == "send_away"
    # The same minute asks with the same key; the next minute, and the other request, with another.
    assert _presence_plan(SIM.SEND_AWAY, world)["steps"][0]["body"] == step["body"]
    later = _presence_plan(SIM.SEND_AWAY, world, _clock(tick=13))
    back = _presence_plan(SIM.BRING_BACK, _presence_world({"presence": {"status": "away"}}))
    keys = {plan_["steps"][0]["body"]["idempotency_key"] for plan_ in (document, later, back)}
    assert len(keys) == 3
    assert back["steps"][0]["body"]["presence"] == "here"


def test_what_the_society_already_holds_is_refused_by_the_route_s_own_name():
    away = _presence_world({"inhabitants": [{"id": KNIGHT}], "presence": {"status": "away"}})
    refused = _presence_plan(SIM.SEND_AWAY, away)
    assert refused["outcome"] == "refused" and refused["refusal"]["code"] == "preview_blocked"
    assert refused["steps"][0]["code"] == "nobody_to_send_away"
    assert refused["steps"][0]["body"] is None
    here = _presence_world({"inhabitants": [{"id": KNIGHT}], "presence": None})
    assert _presence_plan(SIM.BRING_BACK, here)["steps"][0]["code"] == "already_here"


def test_an_engine_that_keeps_its_people_or_a_world_with_nobody_refuses_by_the_read_s_code():
    kept = _presence_world(
        **{PRESENCE: _descriptor(PRESENCE, state="unsupported", code="engine_keeps_its_people")}
    )
    refused = _presence_plan(SIM.SEND_AWAY, kept)
    assert refused["refusal"]["code"] == "action_unsupported"
    assert refused["refusal"]["capability"]["code"] == "engine_keeps_its_people"
    nobody = _presence_plan(SIM.SEND_AWAY, _presence_world(), _clock(society=False))
    assert nobody["refusal"]["code"] == "action_unavailable"
    unstated = _simulation_world()
    assert _presence_plan(SIM.SEND_AWAY, unstated)["refusal"]["code"] == "action_not_offered"


# -- the prepare route's body ----------------------------------------------------------------------


def test_the_prepare_route_s_body_takes_each_typed_step():
    base = {"version_id": str(VERSION), "base_state_sha256": "a" * 64}
    for action in (
        {"operation": "move_thing", "thing_id": "well"},
        {"operation": "remove_thing", "thing_id": "well"},
        {"operation": "play_being", "subject_id": KNIGHT},
        {"operation": "give_back", "subject_id": KNIGHT},
        {"operation": "send_away"},
        {"operation": "bring_back"},
    ):
        body = PrepareRequest.model_validate({**base, "actions": [action]})
        assert body.actions[0].model_dump(exclude_none=True) == action
