"""Opt-in residents live a recorded day without changing earlier societies' replay."""

from __future__ import annotations

import dataclasses
import json
import uuid
from copy import deepcopy

import pytest
from exulanica.abilities.registry import DAY, current_modules
from exulanica.environment.district_geometry import segment_blocked
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.kinds.worker import _placed
from exulanica.world.society import society_state_sha256
from exulanica.world.society_authored_ground import StandingPolicy, authored_ground_from_snapshot
from exulanica.world.society_city_place import city_obstructions
from exulanica.world.society_decision_contract import decision_context, hearers
from exulanica.world.society_follow import approach_node as follow_node
from exulanica.world.society_hands import acts_open
from exulanica.world.society_living import town_routine_of
from exulanica.world.society_planner import advance_purposeful_society, held_nodes, input_sha256
from exulanica.world.society_resident_day import inside, routine_of, validate_frame
from exulanica.world.society_site_place import site_obstructions
from exulanica.world.society_things import advance_things, initial_things_society
from exulanica.world.society_walking_surfaces import (
    build_walking_surfaces_input,
    walking_surfaces_place,
)
from exulanica.world.town_people import people_frame
from exulanica.world.world_recipes import town_recipe

from living_town_support import version_of
from test_site_society_of_things import SITE, _composed, _resealed, _things_input

SEED = "5" * 64
SOCIETY = uuid.uuid5(uuid.NAMESPACE_URL, "resident-day-tests")
TOWN = "world:generated:00000000-0000-4000-8000-000000000003"


def _input(*, town=False, day=True, input_seq=1, available=True):
    world_id, composed = (
        (TOWN, compose_generated_world(town_recipe("small_town"), TOWN))
        if town
        else _composed("farm")
    )
    snapshot_id = uuid.uuid5(uuid.NAMESPACE_URL, composed.receipt_sha256)
    ground = authored_ground_from_snapshot(
        world_id=world_id,
        snapshot_id=snapshot_id,
        snapshot_sha256=composed.receipt_sha256,
        composer_key=composed.candidate.composer_key,
        composer_version=composed.candidate.composer_version,
        topology=composed.candidate.topology,
        placement=composed.candidate.placement,
    )
    if town:
        routine = town_routine_of(composed.receipt)
        full = dataclasses.replace(
            routine, policy={k: v for k, v in routine.policy.items() if k != "town_people_default"}
        )
        place = walking_surfaces_place(ground.place_id, composed.records, full)
        obstacles = city_obstructions(composed.records)
    else:
        routine = SITE.receipt_routine(composed.receipt)
        answer = _placed(ground.place_id, composed.receipt, composed.records)
        place, obstacles = answer["place"], site_obstructions(answer["blocked"])
    return build_walking_surfaces_input(
        ground=ground,
        version=version_of(world_id, snapshot_id),
        place=place,
        input_seq=input_seq,
        dependency_refs=[],
        availability="available" if available else "unavailable",
        unavailable_reason=None if available else "source_unavailable",
        reviewed_affordances={},
        standing=StandingPolicy(
            routine.policy["standing_spacing_mm"], routine.policy["standing_radius_mm"]
        ),
        things=True,
        segment_blocked=segment_blocked,
        obstructions=obstacles,
        people=people_frame(place, routine),
        day_place=place if day else None,
        day_routine=routine if day else None,
    )


@pytest.fixture(scope="module")
def farm():
    return _input()


def _initial(document):
    return initial_things_society(
        SOCIETY, SEED, document, population=document["population"]["size"]
    )


def _step(state, document, *, inputs=None, policies=None):
    planned, events = advance_purposeful_society(
        state, SEED, inputs or [document], goal_policy=policies
    )
    return advance_things(state, planned, SEED, document, events)[:2]


def test_only_explicit_composition_records_a_day(farm):
    old, _ = _things_input("farm")
    assert DAY not in current_modules() and DAY in current_modules(day=True)
    assert "day" not in old and "day_context" not in _initial(old)
    assert DAY in farm["modules"] and _initial(farm)["day_context"] == farm["day"]
    assert "day" not in _input(day=False, input_seq=2)
    with pytest.raises(ValueError, match="available first"):
        _input(input_seq=2)


def test_a_farm_lives_and_replays_from_retained_inputs_and_checkpoint(farm, monkeypatch):
    state = _initial(farm)
    routine = routine_of(farm["day"])
    destinations = {d["destination_id"]: d for d in farm["day"]["destinations"]}
    checkpoint, events_after = None, []
    field_work, indoor_stay, relief = False, False, False
    for tick in range(720):
        before = state
        state, events = _step(state, farm)
        for person, prior in zip(state["inhabitants"], before["inhabitants"], strict=True):
            stay = person["day"]
            if stay:
                dest = destinations.get(stay["destination_id"])
                field_work |= stay["activity"] == "work" and dest["use_class"] == "crop_field"
                if dest is not None:
                    assert inside(person) == dest["indoors"]
                indoor_stay |= (
                    inside(person) and routine.activities[stay["activity"]].setting == "home"
                )
            relief |= any(person["needs"][k] < prior["needs"][k] for k in person["needs"])
        if tick == 359:
            checkpoint = json.loads(json.dumps(state))
        elif tick > 359:
            events_after.extend((e.kind, e.document) for e in events)
    assert field_work and indoor_stay and relief
    # New defaults may point elsewhere; replay reads only the versions the input retained.
    from exulanica.world import society_catalogs

    monkeypatch.setattr(society_catalogs, "ROUTINE_VERSIONS", {"society-policy": 999})
    monkeypatch.setattr(society_catalogs, "TOWN_ROUTINE_VERSIONS", {"society-policy": 999})
    again = checkpoint
    repeated = []
    retained = json.loads(json.dumps(farm))
    for _ in range(360):
        again, events = _step(again, retained)
        repeated.extend((e.kind, e.document) for e in events)
    assert again == state and repeated == events_after


def test_a_full_town_leaves_homes_without_reserving_shared_doorways():
    document = _input(town=True)
    state = _initial(document)
    assert len(state["inhabitants"]) == 638
    assert all(inside(p) for p in state["inhabitants"])
    assert held_nodes(state["inhabitants"], state["inhabitants"][0]) == set()
    for _ in range(90):
        state, _ = _step(state, document)
    assert any(p["action"]["kind"] == "work" for p in state["inhabitants"])
    assert any(not inside(p) for p in state["inhabitants"])
    occupied = [
        p["location"]["node_id"] for p in state["inhabitants"] if not inside(p) and p["day"]
    ]
    assert len(occupied) == len(set(occupied))


def test_explicit_walk_overrides_a_home_stay_but_wait_does_not_teleport_outside(farm):
    state = _initial(farm)
    person = state["inhabitants"][0]
    waited, _ = _step(
        state, farm, policies={person["id"]: {"allowed_target_ids": [], "wait": True}}
    )
    assert waited["inhabitants"][0]["day"] is None
    assert inside(waited["inhabitants"][0])
    target = next(t for t in farm["targets"] if t["enabled"])
    walked, _ = _step(
        state,
        farm,
        policies={
            person["id"]: {
                "allowed_target_ids": [target["target_id"]],
                "preferred_target_id": target["target_id"],
            }
        },
    )
    assert walked["inhabitants"][0]["day"] is None
    assert not inside(walked["inhabitants"][0])


def test_unavailable_input_blocks_movement_while_stays_can_finish(farm):
    unavailable = _input(day=False, input_seq=2, available=False)
    state = _initial(farm)
    initial_positions = [p["position_mm"] for p in state["inhabitants"]]
    state, _ = _step(state, unavailable, inputs=[farm, unavailable])
    for _ in range(50):
        state, _ = _step(state, unavailable)
    assert all(p["day"] is None for p in state["inhabitants"])
    assert all(p["action"]["status"] == "blocked" for p in state["inhabitants"])
    assert [p["position_mm"] for p in state["inhabitants"]] == initial_positions
    recovered = _input(day=False, input_seq=3)
    state, _ = _step(state, recovered, inputs=[unavailable, recovered])
    assert state["clock"]["minute_of_day"] == 360 + state["tick"]


def test_people_at_the_same_door_do_not_see_hear_follow_or_reach_through_walls(farm):
    state = _initial(farm)
    one, other = state["inhabitants"]
    assert hearers(state, one, 10000)
    other["day"] = None
    other["location"].update(indoors=False, destination_id=None)
    assert not hearers(state, one, 10000) and not hearers(state, other, 10000)
    assert follow_node(state, farm, other, one, 10000) is None
    assert acts_open(state, one, farm) == []
    for person in (one, other):
        context = decision_context(state, farm, person["id"], [])
        assert context["surroundings"]["beings"] == []
        assert context["surroundings"]["more_beings"] == 0
        assert context["indoors"] == inside(person)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["day"].update(start_minute_of_day=1),
        lambda d: d["day"]["destinations"][0].update(indoors="yes"),
        lambda d: d["day"]["destinations"][0].update(visitor_capacity=-1),
        lambda d: d["day"]["destinations"][0].update(duration_ticks=0),
        lambda d: d["day"]["destinations"][0].update(affordances=["invented"]),
        lambda d: d["day"]["destinations"][0].update(standing_nodes=["absent"]),
    ],
)
def test_a_resealed_input_still_refuses_invalid_day_facts(farm, mutation):
    document = deepcopy(farm)
    mutation(document)
    frame = document["day"]
    frame["document_sha256"] = society_state_sha256(
        {k: v for k, v in frame.items() if k != "document_sha256"}
    )
    with pytest.raises(ValueError):
        _resealed(document)


def test_day_requires_its_module_and_immutable_context_digest(farm):
    document = deepcopy(farm)
    document["modules"].remove(DAY)
    with pytest.raises(ValueError, match="recorded module"):
        _resealed(document)
    document = deepcopy(farm)
    document["day"]["start_minute_of_day"] += 1
    with pytest.raises(ValueError, match="digest"):
        validate_frame(document["day"])
    assert farm["document_sha256"] == input_sha256(farm)


def test_an_edit_cannot_move_an_interior_resident_to_an_unrelated_street_node(farm):
    state = _initial(farm)
    person = deepcopy(state["inhabitants"][0])
    removed = person["location"]["node_id"]
    edited = _input(day=False, input_seq=2)
    edited["navigation"]["nodes"] = [
        n for n in edited["navigation"]["nodes"] if n["node_id"] != removed
    ]
    edited["navigation"]["edges"] = [
        e
        for e in edited["navigation"]["edges"]
        if removed not in (e["from_node_id"], e["to_node_id"])
    ]
    edited = _resealed(edited)
    state, _ = _step(state, edited, inputs=[farm, edited])
    after = state["inhabitants"][0]
    assert after["location"] == person["location"]
    assert after["position_mm"] == person["position_mm"]
    assert after["action"]["status"] == "blocked"
    assert after["action"]["reason"] == "current_position_invalidated"


def test_a_pending_follow_stops_by_name_when_the_target_is_indoors(farm):
    from exulanica.world.society_decision_contract import DecisionOption

    from test_society_hands import _receipt

    state = _initial(farm)
    actor, target = state["inhabitants"]
    actor["day"] = None
    actor["location"].update(indoors=False, destination_id=None)
    actor["following"] = {
        "being": target["id"],
        "kind": dict(target["kind"]),
        "number": target["ordinal"] + 1,
        "since": 0,
        "lost": 0,
    }
    option = DecisionOption("Keep following", "carry_on", "carry_on", None, None, None)
    planned, events = advance_purposeful_society(
        state, SEED, [farm], goal_policy={actor["id"]: {"allowed_target_ids": [], "wait": True}}
    )
    result, events, _ = advance_things(
        state, planned, SEED, farm, events, decisions=[_receipt(actor, option)]
    )
    assert "following" not in result["inhabitants"][0]
    assert any(
        e.kind == "stopped_following" and e.document["reason"] == "target_inside" for e in events
    )
