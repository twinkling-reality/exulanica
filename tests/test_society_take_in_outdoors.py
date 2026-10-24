"""A being the world's author placed has no day and never goes in, so a society that records the
purposeful planner at version 4 takes it in outdoors only: at the open node nearest where it was
put down that is no door's node, never in a shop's doorway. A society recorded before keeps its
take-ins, so it replays as it was recorded. The stand read answers by the same rule.

The walking graph here is the planner's own reading of an input (nodes, edges and their subjects): a
footway along a frontage, a shop's door reached from one of its points, and a point where a placing
lands by the door.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from exulanica.abilities.registry import (
    PURPOSEFUL,
    PURPOSEFUL_BY_KIND_WEIGHTS,
    PURPOSEFUL_OUTDOORS_TAKE_IN,
    current_modules,
)
from exulanica.world.society_planner import open_node_near, takes_in_outdoors
from exulanica.world.society_stand import stand_near


def _node(node_id: str, east: int, south: int) -> dict:
    return {"node_id": node_id, "position_mm": [east, south]}


def _edge(a: str, b: str, subject: str) -> dict:
    """An input's edge: its subject says what it is, ``premises_access`` the way to a door."""
    return {"edge_id": f"{a}|{b}", "from_node_id": a, "to_node_id": b, "subject_id": subject}


def _input(*extra_edges: dict) -> dict:
    """A frontage's footway (three points 2 m apart) and a shop's door 1 m off its middle point,
    joined to it by the way to a door; the door is the nearest node to where a placing lands."""
    return {
        "availability": "available",
        "profile": "a-street-input",
        "targets": [],
        "navigation": {
            "unavailable_reason": None,
            "nodes": [
                _node("footway:a", 0, 0),
                _node("footway:b", 2000, 0),
                _node("footway:c", 4000, 0),
                _node("entrance:shop", 2000, -1000),
            ],
            "edges": [
                _edge("footway:a", "footway:b", "footway"),
                _edge("footway:b", "footway:c", "footway"),
                _edge("footway:b", "entrance:shop", "premises_access"),
                *extra_edges,
            ],
        },
    }


#: Put down in the shop's doorway, a little in front of the door.
BY_THE_DOOR = (2000, -900)


def test_a_being_that_never_goes_in_is_never_taken_in_at_a_door():
    document = _input()
    # The rule as every society recorded before runs it: the nearest open node, the door.
    assert open_node_near(document, [], BY_THE_DOOR) == "entrance:shop"
    # Outdoors only: the nearest node that is no door's, the footway point the door is reached from.
    assert open_node_near(document, [], BY_THE_DOOR, outdoors=True) == "footway:b"


def test_a_footway_point_a_door_is_reached_from_is_no_door():
    # Only a node every edge of which is the way to a door is a door's: the footway point is open.
    document = _input()
    assert open_node_near(document, [], (2000, 100), outdoors=True) == "footway:b"
    # A node joined to the footway as well as to a door is a footway's, so it is taken.
    joined = _input(_edge("entrance:shop", "footway:c", "footway"))
    assert open_node_near(joined, [], BY_THE_DOOR, outdoors=True) == "entrance:shop"


def test_an_input_whose_edges_state_no_subject_has_no_door():
    # A ground whose input states no subject for its edges (a starter world's) has no way to a
    # door, so outdoors reads it as the rule before it did.
    document = _input()
    for edge in document["navigation"]["edges"]:
        del edge["subject_id"]
    assert open_node_near(document, [], BY_THE_DOOR, outdoors=True) == "entrance:shop"


def test_a_door_is_never_taken_even_where_it_is_the_only_open_node():
    document = _input()
    document["navigation"]["nodes"] = [
        _node("entrance:shop", 2000, -1000),
        _node("footway:b", 2000, 0),
    ]
    document["navigation"]["edges"] = [_edge("footway:b", "entrance:shop", "premises_access")]
    # The footway point is somebody's: it is held, and the door is no place to stand instead.
    standing = [
        {
            "id": "someone",
            "position_mm": [2000, 0],
            "goal": None,
            "route": None,
            "location": {"edge": None, "node_id": "footway:b", "indoors": False},
        }
    ]
    assert open_node_near(document, standing, BY_THE_DOOR) == "entrance:shop"
    assert open_node_near(document, standing, BY_THE_DOOR, outdoors=True) is None


@pytest.mark.parametrize(
    ("modules", "outdoors"),
    [
        ((), False),
        ((PURPOSEFUL,), False),
        ((PURPOSEFUL_BY_KIND_WEIGHTS,), False),
        ((PURPOSEFUL_OUTDOORS_TAKE_IN,), True),
    ],
)
def test_only_a_society_that_recorded_version_4_takes_its_placed_beings_in_outdoors(
    modules, outdoors
):
    """The rule is a version of the purposeful planner the society names in its first input: one
    recorded before replays its take-ins unchanged."""
    assert takes_in_outdoors({"modules": list(modules)}) is outdoors
    assert takes_in_outdoors({}) is False


def test_a_new_society_records_version_4():
    assert takes_in_outdoors({"modules": list(current_modules())}) is True


def test_the_stand_read_answers_by_the_rule_the_society_takes_in_by():
    document = _input()
    assert stand_near(document, [], BY_THE_DOOR)["node_id"] == "entrance:shop"
    stand = stand_near(document, [], BY_THE_DOOR, outdoors=True)
    assert stand == {"node_id": "footway:b", "position_mm": [2000, 0], "height_mm": None}


# In a town: the small town's own society input, where a shop's door is a node joined to its
# footway by the way to a door alone.


def _a_door(document: dict) -> tuple[str, tuple[int, int]]:
    """The first door of ``document`` by id: a node every edge of which is the way to a door."""
    joined: dict[str, list[dict]] = {}
    for edge in document["navigation"]["edges"]:
        for end in (edge["from_node_id"], edge["to_node_id"]):
            joined.setdefault(end, []).append(edge)
    door = min(
        node
        for node, edges in joined.items()
        if all(edge["subject_id"] == "premises_access" for edge in edges)
    )
    (position,) = (
        n["position_mm"] for n in document["navigation"]["nodes"] if n["node_id"] == door
    )
    return door, (position[0], position[1])


def _knight_at(east: int, south: int) -> Any:
    from exulanica.world.objects import ObjectOrigin, Transform
    from exulanica.world.placed_things import PlacedThing, named_kind

    import test_walking_surfaces_v3 as town

    region = town._town()[0].region_id
    return PlacedThing(
        "knight",
        named_kind("knight", 1),
        region,
        Transform(east, 0, south, 0, 1000),
        ObjectOrigin("authored", "fictional"),
        False,
    )


def _recorded(document: dict, purposeful: str) -> dict:
    """``document`` as a first input that recorded ``purposeful`` in place of today's version."""
    from exulanica.world.society_planner import input_sha256

    recorded = copy.deepcopy(document)
    recorded["modules"] = sorted(
        purposeful if module.startswith("exulanica-ability/purposeful/") else module
        for module in recorded["modules"]
    )
    recorded["document_sha256"] = input_sha256(recorded)
    return recorded


def _genesis(document: dict) -> dict:
    from exulanica.world.society_things import initial_things_society

    import test_walking_surfaces_v3 as town

    return initial_things_society(
        town.SOCIETY, town.SEED, document, population=document["population"]["size"]
    )


def _knight(state: dict) -> dict:
    return next(person for person in state["inhabitants"] if person["came_by"] == "placed")


def _footway_of(document: dict, door: str) -> str:
    """The node a door is reached from: the other end of its one way to a door."""
    (edge,) = (
        e for e in document["navigation"]["edges"] if door in (e["from_node_id"], e["to_node_id"])
    )
    return edge["to_node_id"] if edge["from_node_id"] == door else edge["from_node_id"]


def test_in_a_town_a_being_put_down_at_a_shop_s_door_is_taken_in_beside_it():
    import test_walking_surfaces_v3 as town

    door, (east, south) = _a_door(town._compose())
    document = town._compose(_knight_at(east, south))
    # A new society records version 4: the knight stands on the footway the door is reached from.
    assert PURPOSEFUL_OUTDOORS_TAKE_IN in document["modules"]
    state = _genesis(document)
    assert _knight(state)["location"]["node_id"] == _footway_of(document, door)
    # The stand read says where the society took it in.
    assert stand_near(document, [], (east, south), outdoors=True)["node_id"] == _footway_of(
        document, door
    )
    # A society recorded before keeps its take-in: the door, as it always was.
    before = _genesis(_recorded(document, PURPOSEFUL_BY_KIND_WEIGHTS))
    assert _knight(before)["location"]["node_id"] == door


def _edited(*things: Any) -> dict:
    """The town's second things input: one edit later than the first, holding ``things``, as
    the small town's own first input is composed (tests/test_walking_surfaces_v3.py)."""
    import dataclasses

    from exulanica.environment.district_geometry import segment_blocked
    from exulanica.world.authored_delta import version_delta_sha256
    from exulanica.world.society_walking_surfaces import build_walking_surfaces_input

    import test_walking_surfaces_v3 as town

    ground, place, base, standing = town._town()
    version = dataclasses.replace(base, things=tuple(things), edit_seq=base.edit_seq + 1)
    version = dataclasses.replace(version, state_sha256=version_delta_sha256(version))
    return build_walking_surfaces_input(
        ground=ground,
        version=version,
        place=place,
        input_seq=2,
        dependency_refs=[],
        availability="available",
        unavailable_reason=None,
        reviewed_affordances={},
        standing=standing,
        things=True,
        segment_blocked=segment_blocked,
        obstructions=town._obstructions(),
    )


def test_in_a_town_a_being_an_edit_moves_to_a_shop_s_door_is_put_beside_it():
    from exulanica.world.society_planner import advance_purposeful_society
    from exulanica.world.society_things import advance_things

    import test_walking_surfaces_v3 as town

    door, (east, south) = _a_door(town._compose())
    first = town._compose(_knight_at(east, south + 6_000))
    moved = _edited(_knight_at(east, south))

    def after_the_move(document: dict) -> str:
        state = _genesis(document)
        planned, events = advance_purposeful_society(state, town.SEED, [document, moved])
        state, _events, _crossings = advance_things(state, planned, town.SEED, moved, events)
        return _knight(state)["location"]["node_id"]

    assert after_the_move(first) == _footway_of(moved, door)
    assert after_the_move(_recorded(first, PURPOSEFUL_BY_KIND_WEIGHTS)) == door
