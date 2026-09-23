"""Resting inhabitants never stand inside one another, and everybody gets a turn.

An input that states places (``exulanica.society-input/authored-ground-v2``) gives each activity
the places its occupants stand at, one person to a place, a standing spacing apart. A person never
takes up again, unasked, the activity whose place it stands at; with nothing else to do it walks
to the nearest node where nobody stands, is headed or would be in the way. An input that states no
places takes exactly the path it always took, and the v2 policy's figures are pinned through a
completed rest so a changed need threshold or relief cannot pass unnoticed.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter

import pytest
from exulanica.world import society_planner
from exulanica.world.society import society_state_sha256
from exulanica.world.society_actions import ActionIntent, action_goal_policies, build_action_request
from exulanica.world.society_planner import (
    advance_purposeful_society,
    initial_purposeful_society,
    standing_exclusions,
)

import test_society_authored_ground as authored
from test_society_saved_world_objects import STANDING, first, second, thing, world

SEEDS = ("a" * 64, "b" * 64, "c" * 64)
SOCIETY = uuid.UUID(int=7)
ONE_PLATE = world()  # the cushion at (3000, 5000): two places
BUSY = world(thing("object:post", authored.PILLAR, -4_000, 1_000))


def run(document, seed, ticks, population=8):
    state = initial_purposeful_society(SOCIETY, seed, document, population=population)
    states, events = [state], []
    for _ in range(ticks):
        state, produced = advance_purposeful_society(state, seed, [document])
        states.append(state)
        events.extend(produced)
    return states, events


def stationary(state):
    return [p for p in state["inhabitants"] if p["location"]["edge"] is None]


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("version", [ONE_PLATE, BUSY], ids=["one-plate", "plate-and-post"])
def test_nobody_standing_still_is_within_a_spacing_of_anybody_else(version, seed):
    document = second(authored.endless(), version)
    states, _ = run(document, seed, 240)
    for state in states[1:]:
        people = stationary(state)
        for index, a in enumerate(people):
            for b in people[index + 1 :]:
                distance = math.dist(a["position_mm"], b["position_mm"])
                assert distance >= STANDING.spacing_mm, (state["tick"], a["id"], b["id"], distance)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_destination_holds_no_more_than_its_places_and_everybody_gets_a_turn(seed):
    document = second(authored.endless(), ONE_PLATE)
    [cushion] = document["targets"]
    places = set(cushion["place_node_ids"])
    states, events = run(document, seed, 240)
    for state in states:
        holding = [
            p
            for p in state["inhabitants"]
            if p["route"] is not None and p["route"]["destination_node_id"] in places
        ]
        assert len(holding) <= len(places)
        resting = [p for p in state["inhabitants"] if p["action"]["kind"] == "rest"]
        assert all(
            p["location"]["node_id"] in places for p in resting if p["location"]["edge"] is None
        )
    rests = Counter(e.document["subject_id"] for e in events if e.kind == "action_completed")
    # Eight people and a two-place cushion: every one of them rests, and nobody rests twice as
    # often as anybody else.
    assert len(rests) == 8
    assert max(rests.values()) <= 2 * min(rests.values())


def test_the_same_world_without_places_still_piles_everybody_onto_the_access_node():
    # The positive control for everything above: the first composition states no places, and the
    # v2 policy over it sends every idle person to the one access node, as it always did.
    document = first(authored.endless(), ONE_PLATE)
    states, _ = run(document, SEEDS[0], 12)
    [target] = document["targets"]
    access = next(n for n in document["navigation"]["nodes"] if n["node_id"] == target["node_id"])
    assert all(p["position_mm"] == access["position_mm"] for p in states[-1]["inhabitants"])


def test_somebody_who_has_finished_makes_room_and_waits_clear_of_every_place():
    document = second(authored.endless(), ONE_PLATE)
    crowded = standing_exclusions(document)
    states, events = run(document, SEEDS[0], 60)
    made = [
        e for e in events if e.kind == "route_progressed" and e.document["reason"] == "made_room"
    ]
    assert made
    by_tick = {state["tick"]: state for state in states}
    for event in made:
        person = next(
            p for p in by_tick[event.tick]["inhabitants"] if p["id"] == str(event.subject_id)
        )
        assert person["location"]["node_id"] not in crowded
        assert person["goal"]["kind"] == "make_room" and person["target"] is None


def test_nobody_starts_on_a_place_where_it_joins_the_lattice_or_beside_one():
    document = second(authored.endless(), BUSY)
    crowded = standing_exclusions(document)
    [state], _ = run(document, SEEDS[1], 0)
    starts = [p["location"]["node_id"] for p in state["inhabitants"]]
    assert len(set(starts)) == 8 and not set(starts) & crowded
    places = {n for t in document["targets"] for n in t["place_node_ids"]}
    assert places < crowded


def _holders(state, target):
    return {
        p["id"]
        for p in state["inhabitants"]
        if p["route"] is not None and p["route"]["destination_node_id"] in target["place_node_ids"]
    }


def _idle(state):
    return [
        p
        for p in state["inhabitants"]
        if p["goal"] is None or p["action"]["status"] in ("completed", "blocked")
    ]


def test_a_person_asked_to_rest_where_there_is_no_room_is_told_so():
    document = second(authored.endless(), ONE_PLATE)
    [cushion] = document["targets"]
    states, _ = run(document, SEEDS[0], 1)
    state = states[-1]
    holders = _holders(state, cushion)
    assert len(holders) == len(cushion["place_node_ids"])
    waiting = next(p for p in _idle(state) if p["id"] not in holders)
    with pytest.raises(ValueError, match="destination_full"):
        build_action_request(
            state,
            document,
            request_id=uuid.uuid4(),
            requested_by=uuid.uuid4(),
            subject_id=uuid.UUID(waiting["id"]),
            intent=ActionIntent("perform", cushion["target_id"], "rest"),
        )


def test_a_person_sent_to_a_place_gets_it_before_anybody_choosing_freely():
    document = second(authored.endless(), ONE_PLATE)
    [cushion] = document["targets"]
    first_place = cushion["place_node_ids"][0]
    [state], _ = run(document, SEEDS[0], 0)
    # Unasked, the first person in the minute takes the first place.
    unasked, _ = advance_purposeful_society(state, SEEDS[0], [document])
    [taker] = [
        p["id"]
        for p in unasked["inhabitants"]
        if p["route"] is not None and p["route"]["destination_node_id"] == first_place
    ]
    sent = state["inhabitants"][-1]
    assert sent["id"] != taker
    request = build_action_request(
        state,
        document,
        request_id=uuid.uuid4(),
        requested_by=uuid.uuid4(),
        subject_id=uuid.UUID(sent["id"]),
        intent=ActionIntent("perform", cushion["target_id"], "rest"),
    )
    policies, [disposition] = action_goal_policies(state, document, [request])
    assert disposition.disposition == "applied"
    assert policies[sent["id"]]["place_node_id"] == first_place
    asked, _ = advance_purposeful_society(state, SEEDS[0], [document], goal_policy=policies)
    assert [
        p["id"]
        for p in asked["inhabitants"]
        if p["route"] is not None and p["route"]["destination_node_id"] == first_place
    ] == [sent["id"]]


def test_an_advance_walks_at_the_budget_its_own_state_recorded(monkeypatch):
    document = second(authored.endless(), BUSY)
    state = initial_purposeful_society(SOCIETY, SEEDS[2], document, population=8)
    slow = dict(state, movement_budget_mm_per_tick=1_000)
    walked, _ = advance_purposeful_society(slow, SEEDS[2], [document])
    moved = [
        sum(
            math.dist(a, b)
            for a, b in zip(p["motion_path_mm"], p["motion_path_mm"][1:], strict=False)
        )
        for p in walked["inhabitants"]
    ]
    assert (
        max(moved)
        <= 1_000
        < max(
            sum(
                math.dist(a, b)
                for a, b in zip(p["motion_path_mm"], p["motion_path_mm"][1:], strict=False)
            )
            for p in advance_purposeful_society(state, SEEDS[2], [document])[0]["inhabitants"]
        )
    )
    # The module figure is what a new society records, and nothing a stored one reads.
    monkeypatch.setattr(society_planner, "MOVEMENT_BUDGET_MM", 1)
    assert advance_purposeful_society(slow, SEEDS[2], [document])[0] == walked


#: Twelve ticks of the first saved-world composition over one reachable cushion, far enough for 24
#: activities to complete: every v2 figure (the rest threshold, both reliefs, the durations and the
#: budget) is inside these bytes. Produced by main e9dee3c2's own code, before places existed.
V2_THROUGH_A_COMPLETED_REST = "faca5b8b6784b633b4626fc1f6f6a8dc13c99024497f620be727b53d79cd4190"


def test_the_v2_policy_through_a_completed_rest_is_pinned():
    document = first(authored.endless(), ONE_PLATE)
    states, events = run(document, SEEDS[0], 12)
    assert any(e.kind == "action_completed" for e in events)
    assert society_state_sha256(states[-1]) == V2_THROUGH_A_COMPLETED_REST
