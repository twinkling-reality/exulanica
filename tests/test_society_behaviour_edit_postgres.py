"""A behaviour given to a placed object, and taken away again, reaches a saved world's society.

Placed objects feed the society's authored input, and that input re-derives the version's state
digest from the objects it reads. A behaviour is inside that digest, so an edit that changes only
a behaviour is exactly the edit a digest assembled from fixed parts would miss. Every edit here
must append one input in the edit's own transaction, on the bounded and the endless ground alike.
"""

from __future__ import annotations

import pytest
from exulanica.world.objects import ObjectBehaviour

from test_society_authored_world_postgres import (  # noqa: F401
    create_society,
    place_object,
    saved_world,
    society_repository,
)

pytestmark = pytest.mark.postgres

MOTION = ObjectBehaviour(
    "motion.bounded-path",
    1,
    {"travel_mm": 2_000, "period_milliseconds": 4_000, "axis": "x", "easing": "linear"},
)


def test_a_behaviour_edit_and_its_undo_each_recompose_the_society(saved_world):  # noqa: F811
    world = saved_world
    placed = place_object(world, world["plate"], "object:cushion", 3_000, 5_000)
    society, first = create_society(world)
    assert first["availability"] == "available"
    assert [target["object_id"] for target in first["targets"]] == ["object:cushion"]

    objects, actor = world["objects"], world["session"].actor
    moving = objects.set_object_behaviour(
        placed.version_id,
        "object:cushion",
        MOTION,
        base_state_sha256=placed.state_sha256,
        actor=actor,
    )
    cleared = objects.set_object_behaviour(
        placed.version_id,
        "object:cushion",
        None,
        base_state_sha256=moving.state_sha256,
        actor=actor,
    )
    brought_back = objects.undo(
        placed.version_id, base_state_sha256=cleared.state_sha256, actor=actor
    )
    taken_back = objects.undo(
        placed.version_id, base_state_sha256=brought_back.state_sha256, actor=actor
    )

    documents = [
        row["document"]
        for row in world["connection"]
        .execute(
            "select document from world_society_input where workspace_id=%s and society_id=%s "
            "order by input_seq",
            (world["workspace"], society["society_id"]),
        )
        .fetchall()
    ]
    assert [d["input_seq"] for d in documents] == [1, 2, 3, 4, 5]
    assert [d["authored_state"]["delta_sha256"] for d in documents] == [
        placed.state_sha256,
        moving.state_sha256,
        cleared.state_sha256,
        brought_back.state_sha256,
        taken_back.state_sha256,
    ]
    assert [d["authored_state"]["edit_seq"] for d in documents] == [1, 2, 3, 4, 5]
    # An object that moves is not somewhere an inhabitant can rest, so the composition says so by
    # name against that object's own activity and the rest of the world stays usable; without the
    # motion the same cushion is a target again.
    assert [d["availability"] for d in documents] == ["available"] * 5
    for moving_input in (documents[1], documents[3]):
        assert moving_input["targets"] == []
        assert [
            (record["object_id"], record["reason"])
            for record in moving_input["unavailable_affordances"]
        ] == [("object:cushion", "authored_object_moves")]
    assert documents[2]["targets"] == documents[4]["targets"] == first["targets"]
    assert society_repository(world).replay(world["binding"].version_id)["replay_verified"]
