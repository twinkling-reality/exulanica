"""The database and the society agree on whom a direct request may send somewhere.

``may_be_directed`` (``exulanica/world/society_actions.py``) decides whether a request can apply;
``society_person_may_be_directed`` (migration 0108) is what the database's request binding asks
before it records one. Were they to disagree, a request the society would take could not be
recorded, or one it refuses could be. Both are asked of the same people, under an input that records
the newest routine and one that records none: somebody free, each kind of stay the routine has,
under way, a talker waiting for the other, a stay just over, somebody blocked, and somebody walking.
"""

from __future__ import annotations

from typing import Any

import pytest
from exulanica.world.society_actions import may_be_directed
from exulanica.world.society_planner import _off_object, routine_of
from psycopg.types.json import Jsonb

import living_square_support as square
from pg_harness import open_scratch_connection

pytestmark = pytest.mark.postgres

AT_A_NODE = {"node_id": "ground:+00000000:+00002000", "edge": None}
ON_AN_EDGE = {
    "node_id": None,
    "edge": {
        "edge_id": "ground:+00000000:+00000000|ground:+00000000:+00002000",
        "from_node_id": "ground:+00000000:+00000000",
        "to_node_id": "ground:+00000000:+00002000",
        "from_position_mm": [0, 0],
        "to_position_mm": [0, 2000],
        "length_mm": 2000,
        "progress_mm": 700,
    },
}


def _person(kind: str, status: str, *, goal: bool = True, where: dict = AT_A_NODE) -> dict:
    return {
        "id": "person-0",
        "goal": {"kind": kind, "target_id": None, "reason": "stopping_a_while"} if goal else None,
        "location": where,
        "action": {
            "kind": kind,
            "status": status,
            "target_id": None,
            "remaining_ticks": 2 if status == "active" else 0,
            "reason": "standing_a_while",
        },
    }


def _people(stays: list[str]) -> dict[str, dict[str, Any]]:
    waiting = _person("talk", "active")
    waiting["action"]["reason"] = "waiting_for_partner"
    return {
        "free": _person("idle", "active", goal=False),
        **{f"{kind} under way": _person(kind, "active") for kind in stays},
        "a talker waiting for the other": waiting,
        "a stay just over": _person(stays[0], "completed"),
        "blocked": _person("idle", "blocked"),
        "walking, at a node on the way": _person("move", "active"),
        "walking, part way along an edge": _person("move", "active", where=ON_AN_EDGE),
        # Never recorded, since a stay happens at a node; held here so the rule's node clause is
        # asked of both sides too.
        "a stay kind on an edge": _person(stays[0], "active", where=ON_AN_EDGE),
    }


@pytest.fixture(scope="module")
def inputs() -> dict[str, dict]:
    objects = square.square_objects()
    return {
        "the newest routine": square.compose(objects),
        "no routine": square.compose(objects, v2=True),
    }


def test_the_database_admits_exactly_whom_the_society_may_direct(spine_schema, inputs):
    psycopg, scratch = spine_schema
    newest = routine_of(inputs["the newest routine"])
    stays = sorted({*newest.affordances, *(activity.key for activity in _off_object(newest))})
    # A positive control: the newest routine has every kind of stay this file means to ask about.
    assert stays == ["rest", "stand", "talk", "visit"]
    people = _people(stays)
    answers: dict[tuple[str, str], bool] = {}
    connection = open_scratch_connection(psycopg, scratch)
    try:
        for read_under, document in inputs.items():
            for who, person in people.items():
                row = connection.execute(
                    "select society_person_may_be_directed(%s, %s)",
                    (Jsonb(person), Jsonb(document)),
                ).fetchone()
                assert row is not None
                assert row[0] is may_be_directed(person, document), (read_under, who)
                answers[read_under, who] = row[0]
    finally:
        connection.close()
    # What the two agree on: a stay under way is ended by a request only under a routine, a walk
    # never is, and anybody not busy may always be sent.
    for kind in stays:
        assert answers["the newest routine", f"{kind} under way"] is True
        assert answers["no routine", f"{kind} under way"] is False
    for read_under in inputs:
        assert answers[read_under, "free"] is True
        assert answers[read_under, "a stay just over"] is True
        assert answers[read_under, "blocked"] is True
        assert answers[read_under, "walking, at a node on the way"] is False
        assert answers[read_under, "walking, part way along an edge"] is False
        assert answers[read_under, "a stay kind on an edge"] is False
    assert answers["the newest routine", "a talker waiting for the other"] is True
    assert answers["no routine", "a talker waiting for the other"] is False
