"""Editing an object somebody is using never strands them, and an edit elsewhere lets them finish.

Over an input that states places, a place is a node named for its object, so an edit that moves,
turns, scales or removes the object, or gives it motion, leaves whoever stood at the old place
where no node now is. Such a person steps aside, as the minute consumes the edit, to the nearest
open lattice node nobody holds, with a ``replanned`` event (``place_moved``), and may take up the
object's activity again at its new places. A position an edit left behind never holds a place
against anybody else. Somebody resting at a place the edit left where it was keeps resting.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from exulanica.world.authored_delta import delta_sha256
from exulanica.world.objects import Transform
from exulanica.world.society_planner import (
    advance_purposeful_society,
    held_nodes,
    initial_purposeful_society,
    input_graph,
    supports,
)

import test_society_authored_ground as authored
from test_society_authored_world_postgres import (  # noqa: F401
    create_society,
    place_object,
    saved_world,
    society_repository,
)
from test_society_saved_world_objects import MOTION, PILLAR, PLATE, second, thing, world

SEED = "a" * 64
SOCIETY = uuid.UUID(int=21)
AREA = authored.endless()
TURNED = 1_570_796


def edited(*objects, seq):
    """The saved world after edit ``seq``, holding exactly ``objects``."""
    return replace(
        world(),
        objects=tuple(objects),
        state_sha256=delta_sha256(
            objects=tuple(objects),
            element_overrides=(),
            environment_instances=(),
            point_map_instances=(),
        ),
        edit_seq=seq,
    )


def resting(state):
    return [
        p
        for p in state["inhabitants"]
        if p["action"]["kind"] == "rest" and p["action"]["status"] == "active"
    ]


def two_resting():
    """A society with two people part way through resting at the two-place cushion."""
    document = second(AREA, world())
    state = initial_purposeful_society(SOCIETY, SEED, document, population=8)
    for _ in range(40):
        state, _ = advance_purposeful_society(state, SEED, [document])
        people = resting(state)
        if len(people) == 2 and all(p["action"]["remaining_ticks"] >= 2 for p in people):
            return document, state, people
    raise AssertionError("two people never rested together")


EDITS = {
    "moved": thing("object:cushion", PLATE, -3_000, 5_000),
    "turned": thing("object:cushion", PLATE, 3_000, 5_000, yaw=TURNED),
    "scaled": thing("object:cushion", PLATE, 3_000, 5_000, scale=2_000),
    "removed": None,
    "given motion": thing("object:cushion", PLATE, 3_000, 5_000, behaviour=MOTION),
}


@pytest.mark.parametrize("edit", EDITS, ids=list(EDITS))
def test_whoever_stood_at_a_place_an_edit_took_away_steps_aside_and_lives_on(edit):
    before, state, people = two_resting()
    cushion = EDITS[edit]
    after = second(AREA, edited(*([cushion] if cushion else []), seq=10), input_seq=2)
    graph = input_graph(after)
    state, events = advance_purposeful_society(state, SEED, [before, after])
    stepped = [e for e in events if e.kind == "replanned" and e.document["reason"] == "place_moved"]
    assert sorted(str(e.subject_id) for e in stepped) == sorted(p["id"] for p in people)
    assert all(e.document["outcome"] == "stepped_aside" for e in stepped)
    # Everybody stands where the new input says there is ground: the two who stepped aside may
    # already be back at the cushion's places, under the same names where the edit put them.
    assert all(supports(graph, p) for p in state["inhabitants"])
    later = []
    for _ in range(30):
        state, produced = advance_purposeful_society(state, SEED, [after])
        later.extend(produced)
        assert all(supports(graph, p) for p in state["inhabitants"])
    assert not [e for e in later if e.document["reason"] == "current_position_invalidated"]
    new_places = {n for t in after["targets"] for n in t["place_node_ids"]}
    completed = [e for e in later if e.kind == "action_completed"]
    if cushion is None or cushion.behaviour is not None:
        # The activity is gone with the object, or refused while it moves; people keep living
        # without it and nobody rests.
        assert not new_places and not completed
    else:
        # The places stand somewhere new under the same names, free to anybody: people rest
        # there again, standing where the new input puts each place.
        assert new_places and completed


def test_the_step_aside_is_the_same_on_every_run():
    first_run, second_run = [], []
    for store in (first_run, second_run):
        before, state, _ = two_resting()
        after = second(AREA, edited(EDITS["moved"], seq=10), input_seq=2)
        state, events = advance_purposeful_society(state, SEED, [before, after])
        store.append((state, [e.document for e in events]))
    assert first_run == second_run


def test_a_rest_an_edit_elsewhere_leaves_alone_goes_on_to_its_end():
    before, state, people = two_resting()
    far = thing("object:far-post", PILLAR, -9_000, -9_000)
    after = second(
        AREA, edited(thing("object:cushion", PLATE, 3_000, 5_000), far, seq=10), input_seq=2
    )
    assert after["navigation"] != before["navigation"]
    places = {p["id"]: (p["location"]["node_id"], p["action"]["remaining_ticks"]) for p in people}
    state, events = advance_purposeful_society(state, SEED, [before, after])
    assert not [e for e in events if str(e.subject_id) in places and e.kind == "replanned"]
    for person in state["inhabitants"]:
        if person["id"] in places:
            node, remaining = places[person["id"]]
            assert person["location"]["node_id"] == node
            assert person["action"]["kind"] == "rest"
            assert person["action"]["remaining_ticks"] == remaining - 1
    finished = set()
    for _ in range(4):
        state, produced = advance_purposeful_society(state, SEED, [after])
        finished |= {str(e.subject_id) for e in produced if e.kind == "action_completed"}
    assert set(places) <= finished


def test_a_position_an_edit_left_behind_holds_no_place():
    _, state, people = two_resting()
    after = second(AREA, edited(EDITS["moved"], seq=10), input_seq=2)
    somebody = next(p for p in state["inhabitants"] if p["id"] not in {q["id"] for q in people})
    stale = {p["location"]["node_id"] for p in people}
    # Read against the input they were placed in, the two hold their places; read against the
    # input that moved the cushion away from under them, they hold nothing.
    assert stale <= held_nodes(state["inhabitants"], somebody)
    assert not stale & held_nodes(state["inhabitants"], somebody, graph=input_graph(after))


@pytest.mark.postgres
def test_moving_an_occupied_cushion_through_the_repository_strands_nobody(saved_world):  # noqa: F811
    world_ = saved_world
    place_object(world_, world_["plate"], "object:cushion", 3_000, 5_000)
    society, _ = create_society(world_)
    version_id = world_["binding"].version_id
    repository = society_repository(world_)

    def step(current):
        return repository.advance(
            version_id,
            base_tick=current["current_tick"],
            base_state_sha256=current["state_sha256"],
        )

    for _ in range(40):
        society = step(society)
        if len(resting(society["state"])) == 2:
            break
    users = {p["id"] for p in resting(society["state"])}
    assert len(users) == 2
    version = world_["objects"].version(version_id)
    world_["objects"].move_object(
        version_id,
        "object:cushion",
        Transform(-3_000, 0, 5_000, 0, 1000),
        base_state_sha256=version.state_sha256,
        actor=world_["session"].actor,
    )
    society = step(society)
    moved_at = society["current_tick"]
    events = society_repository(world_).events(version_id, limit=256)
    stepped = {
        str(e["subject_id"])
        for e in events
        if e["tick"] == moved_at and e["document"]["reason"] == "place_moved"
    }
    assert stepped == users
    for _ in range(20):
        society = step(society)
    events = society_repository(world_).events(version_id, limit=256)
    assert not [e for e in events if e["document"]["reason"] == "current_position_invalidated"]
    assert [e for e in events if e["tick"] > moved_at and e["event_kind"] == "action_completed"]
    replayed = society_repository(world_).replay(version_id)
    assert replayed["replay_verified"] and replayed["state_sha256"] == society["state_sha256"]
