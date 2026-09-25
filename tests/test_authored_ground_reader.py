"""A saved world's authored ground is read in one place, for the society and for arrangements.

The society runtime composes inhabitants over the ground a world's structural snapshot states,
and an arrangement is placed only on a ground the society can read. Both read it through
``read_authored_ground``: the same row, by the same rule, so the two cannot disagree about where
a world's ground is. Each keeps its own answer to a world with none: the runtime refuses by name,
and an arrangement treats it as no ground to stand on.
"""

from __future__ import annotations

import inspect
import uuid

import pytest
from exulanica.api import society_runtime
from exulanica.world import arrangements
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_authored_ground import read_authored_ground
from exulanica.world.structure_repository import WorldStructureRepository

import test_society_authored_world_postgres as helpers
from test_world_objects_postgres import apply_candidate
from world_structure_fixtures import structural_candidate
from world_support import registered_world

saved_world = helpers.saved_world


def test_neither_caller_selects_the_snapshot_row_itself():
    # The select the reader issues, in the words any copy of it would use.
    select = "from world_structure_snapshot where"
    assert select in inspect.getsource(read_authored_ground)
    for module in (arrangements, society_runtime):
        source = inspect.getsource(module)
        assert select not in source, module.__name__
        assert "read_authored_ground(" in source, module.__name__


@pytest.mark.postgres
def test_the_runtime_and_an_arrangement_read_one_ground(saved_world):
    world = saved_world
    connection, session, runtime = world["connection"], world["session"], world["runtime"]
    snapshot = world["binding"].source_snapshot_id
    ground = read_authored_ground(connection, world["workspace"], world["world_id"], snapshot)
    assert ground is not None and ground.snapshot_id == snapshot
    assert runtime._read_ground(connection, session, world["world_id"], snapshot) == ground
    assert arrangements._read_ground(world["objects"], snapshot) == ground

    # A snapshot the workspace does not hold: nothing to read, said each caller's own way.
    absent = uuid.uuid4()
    assert read_authored_ground(connection, world["workspace"], world["world_id"], absent) is None
    assert arrangements._read_ground(world["objects"], absent) is None
    with pytest.raises(UnavailableSocietyInput, match="registered structural snapshot"):
        runtime._read_ground(connection, session, world["world_id"], absent)


@pytest.mark.postgres
def test_a_ground_the_society_has_no_rule_for_is_refused_by_both(saved_world):
    world = saved_world
    connection, session, runtime = world["connection"], world["session"], world["runtime"]
    other = registered_world(connection, world["workspace"])
    structures = WorldStructureRepository(connection, world["workspace"], world_id=other)
    snapshot = apply_candidate(structures, structural_candidate()).snapshot_id
    with pytest.raises(InvalidStructuralData):
        read_authored_ground(connection, world["workspace"], other, snapshot)
    with pytest.raises(UnavailableSocietyInput, match="authored ground is unreadable"):
        runtime._read_ground(connection, session, other, snapshot)
    elsewhere = world["objects"].__class__(
        connection, world["workspace"], world_id=other, store=world["store"]
    )
    assert arrangements._read_ground(elsewhere, snapshot) is None
