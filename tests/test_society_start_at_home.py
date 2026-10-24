"""A town's residents starting by their own home's door under the fifth purposeful version.

A society of things over a generated town whose first input records
:data:`~exulanica.abilities.registry.PURPOSEFUL_AT_HOME` starts each resident, in ordinal order, at
the node nearest their own home's door of those anybody new may start at that nobody stands at yet
(:func:`~exulanica.world.society_planner.start_at_home`). A society recording an earlier version
starts its people where genesis spread them, as it always did, and replays so.
"""

from __future__ import annotations

import dataclasses
import math
import uuid

import pytest
from exulanica.abilities import registry
from exulanica.abilities.registry import PURPOSEFUL_AT_HOME, PURPOSEFUL_OUTDOORS_TAKE_IN
from exulanica.environment.district_geometry import segment_blocked
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.society import society_state_sha256
from exulanica.world.society_authored_ground import StandingPolicy, authored_ground_from_snapshot
from exulanica.world.society_city_place import city_obstructions
from exulanica.world.society_living import town_routine_of
from exulanica.world.society_planner import initial_purposeful_society, spawn_nodes
from exulanica.world.society_things import initial_things_society
from exulanica.world.society_walking_surfaces import (
    build_walking_surfaces_input,
    walking_surfaces_place,
)
from exulanica.world.town_people import people_frame
from exulanica.world.world_recipes import town_recipe

from living_town_support import version_of

SEED = "6" * 64
SOCIETY = uuid.uuid5(uuid.NAMESPACE_URL, "start-at-home-tests")
TOWN = "world:generated:00000000-0000-4000-8000-000000000012"
#: A made town's head count: fewer people than places to start, as a town made from words has.
POPULATION = 128


def _town_input() -> dict:
    """The first things input of a generated small town of :data:`POPULATION` residents, with the
    people it is made from and no resident day, as a town made from words is lived in."""
    composed = compose_generated_world(town_recipe("small_town"), TOWN)
    snapshot_id = uuid.uuid5(uuid.NAMESPACE_URL, composed.receipt_sha256)
    ground = authored_ground_from_snapshot(
        world_id=TOWN,
        snapshot_id=snapshot_id,
        snapshot_sha256=composed.receipt_sha256,
        composer_key=composed.candidate.composer_key,
        composer_version=composed.candidate.composer_version,
        topology=composed.candidate.topology,
        placement=composed.candidate.placement,
    )
    routine = town_routine_of(composed.receipt)
    full = dataclasses.replace(
        routine, policy={k: v for k, v in routine.policy.items() if k != "town_people_default"}
    )
    place = walking_surfaces_place(ground.place_id, composed.records, full)
    return build_walking_surfaces_input(
        ground=ground,
        version=version_of(TOWN, snapshot_id),
        place=place,
        input_seq=1,
        dependency_refs=[],
        availability="available",
        unavailable_reason=None,
        reviewed_affordances={},
        standing=StandingPolicy(
            full.policy["standing_spacing_mm"], full.policy["standing_radius_mm"]
        ),
        things=True,
        segment_blocked=segment_blocked,
        obstructions=city_obstructions(composed.records),
        people=people_frame(place, full, population=POPULATION),
    )


@pytest.fixture(scope="module")
def town() -> dict:
    return _town_input()


@pytest.fixture(scope="module")
def town_before() -> dict:
    """The same town's first input as a society made under the fourth version recorded it."""
    current = registry.current_modules
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            registry,
            "current_modules",
            lambda *, day=False: tuple(
                sorted(
                    PURPOSEFUL_OUTDOORS_TAKE_IN
                    if module.startswith("exulanica-ability/purposeful/")
                    else module
                    for module in current(day=day)
                )
            ),
        )
        return _town_input()


def _genesis(document: dict) -> dict:
    return initial_things_society(SOCIETY, SEED, document, population=POPULATION)


def _doors(document: dict, state: dict) -> dict[str, list[int]]:
    """Each resident's own home's door, by their id, where the walking graph has it."""
    nodes = {node["node_id"]: node["position_mm"] for node in document["navigation"]["nodes"]}
    by_subject = {row["subject_id"]: row["node_id"] for row in document["people"]["premises"]}
    premises = state["people"]["premises"]
    doors = {}
    for person in state["inhabitants"]:
        subject = premises[person["resident"]["home"]["premises"]]["subject_id"]
        doors[person["id"]] = nodes[by_subject[subject]]
    return doors


def test_a_town_society_made_now_starts_each_resident_by_their_own_door(town):
    assert PURPOSEFUL_AT_HOME in town["modules"]
    state = _genesis(town)
    nodes = {node["node_id"]: node["position_mm"] for node in town["navigation"]["nodes"]}
    allowed = set(spawn_nodes(dict(town)))
    doors = _doors(town, state)
    people = sorted(state["inhabitants"], key=lambda person: person["ordinal"])
    assert len(people) == POPULATION and all(person["came_by"] == "populated" for person in people)
    held = [person["location"]["node_id"] for person in people]
    # Nobody starts where a person arrives, at a destination or where somebody else starts.
    assert set(held) <= allowed and len(set(held)) == len(held)
    taken: set[str] = set()
    for person in people:
        door = doors[person["id"]]
        node = person["location"]["node_id"]
        # The nearest place to their own door that nobody before them in ordinal order took.
        nearest = min(math.dist(nodes[other], door) for other in allowed - taken)
        assert math.dist(nodes[node], door) == nearest, person["ordinal"]
        assert person["position_mm"] == nodes[node] and person["motion_path_mm"] == [nodes[node]]
        taken.add(node)
    # Most of the town's people start within a few doors of home, not spread over its streets.
    near = sum(math.dist(person["position_mm"], doors[person["id"]]) <= 20_000 for person in people)
    assert near > POPULATION // 2


def test_a_society_recording_an_earlier_version_starts_where_genesis_spread_it(town_before):
    assert PURPOSEFUL_AT_HOME not in town_before["modules"]
    state = _genesis(town_before)
    spread = initial_purposeful_society(SOCIETY, SEED, town_before, population=POPULATION)
    where = {person["id"]: person["position_mm"] for person in spread["inhabitants"]}
    assert all(person["position_mm"] == where[person["id"]] for person in state["inhabitants"])


def test_the_starts_at_home_replay_from_the_first_input(town):
    assert society_state_sha256(_genesis(town)) == society_state_sha256(_genesis(town))
