"""A society of things made now records its world's title in its first input, as the world's saved
entry holds it then, and its people are told it where they live (``world_named``). A later rename
changes nothing a society already made records, so every request rebuilds telling the place it
told; a world with no saved entry records none.
"""

from __future__ import annotations

import pytest
from exulanica.world.saved_entries import SavedWorldEntryRepository, told_world_title
from exulanica.world.society_repository import SocietyRepository
from fastapi.testclient import TestClient

import test_society_things_postgres as things_api

saved_world = things_api.saved_world
saved_world_app = things_api.saved_world_app
world_app = things_api.world_app
pytestmark = pytest.mark.postgres
TITLE = "A cozy little town by the sea at dusk"


def _placed(client, world):
    """A well, a gate and a knight, as a society of things over the saved world needs."""
    things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
    things_api._place(client, world, "gate", "gate", 1, 0, 6_000)
    things_api._place(client, world, "knight", "knight", 1, 3_000, 3_000)


def _first_world(world):
    """What the society's first input records of its world, and the repository's read of it."""
    connection = world["connection"]
    row = connection.execute(
        "select society_id, document->'world' as world from world_society_input "
        "where workspace_id=%s and input_seq=1",
        (world["workspace"],),
    ).fetchone()
    society = SocietyRepository(connection, world["workspace"], world_id=world["world_id"])
    read = society.world_title({"society_id": row["society_id"]})
    connection.commit()
    return row["world"], read


def test_a_society_made_now_records_its_world_s_title_and_a_rename_tells_nothing_new(world_app):
    world, make_app, _, _ = world_app
    connection = world["connection"]
    style = connection.execute(
        "select version_id from world_style_version where workspace_id=%s and world_id=%s "
        "order by revision limit 1",
        (world["workspace"], world["world_id"]),
    ).fetchone()
    SavedWorldEntryRepository(connection, world["workspace"], world["store"]).create(
        world_id=world["world_id"],
        title=TITLE,
        authored_version_id=world["binding"].version_id,
        style_version_id=style["version_id"],
        created_by=world["session"].actor,
        source_kind="authored",
    )
    connection.commit()
    assert told_world_title(connection, world["workspace"], world["world_id"]) == TITLE
    with TestClient(make_app()) as client:
        _placed(client, world)
        things_api._make_society(client, world)
    assert _first_world(world) == ({"title": TITLE}, TITLE)
    # The owner renames the world: a new society would be told the new name; this one keeps its own.
    connection.execute(
        "update saved_world_entry set title=%s where workspace_id=%s and world_id=%s",
        ("Bayside", world["workspace"], world["world_id"]),
    )
    connection.commit()
    assert told_world_title(connection, world["workspace"], world["world_id"]) == "Bayside"
    assert _first_world(world) == ({"title": TITLE}, TITLE)
    # A title that is not one plain line the line rule holds is recorded as none, never changed.
    connection.execute(
        "update saved_world_entry set title=%s where workspace_id=%s and world_id=%s",
        ("Café by the bay", world["workspace"], world["world_id"]),
    )
    connection.commit()
    assert told_world_title(connection, world["workspace"], world["world_id"]) is None


def test_a_world_with_no_saved_entry_records_no_title(world_app):
    world, make_app, _, _ = world_app
    assert told_world_title(world["connection"], world["workspace"], world["world_id"]) is None
    with TestClient(make_app()) as client:
        _placed(client, world)
        things_api._make_society(client, world)
    assert _first_world(world) == (None, None)
