"""Missing edit adapters cannot leave a purposeful society behind its authored version."""

import pytest
from exulanica.world.errors import InvalidObjectState
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import Transform
from psycopg import sql

import test_society_runtime as helpers

runtime_world = helpers.runtime_world
pytestmark = pytest.mark.postgres


def create_society(w, profile):
    b = w["binding"]
    return helpers.society(w).create(
        b.version_id,
        place_id=b.place_id,
        region_id=b.region_id,
        seed="7a" * 32,
        actor=w["session"].actor,
        profile=profile,
        initial_input=None if profile == "exulanica-society/v1" else helpers.initial(w),
    )


def recorded_rows(w):
    """Exact rows, including digests/edit IDs, catch partial writes that counts cannot."""
    tables = (
        "world_alternate_version",
        "world_alternate_object",
        "world_alternate_version_edit",
        "world_society",
        "world_society_input",
        "world_society_event",
        "world_society_transition",
    )
    return {
        table: w["connection"]
        .execute(
            sql.SQL("select * from {} where workspace_id=%s order by 1,2").format(
                sql.Identifier(table)
            ),
            (w["workspace"],),
        )
        .fetchall()
        for table in tables
    }


@pytest.mark.parametrize(
    "profile", ["exulanica-society/v2", "exulanica-society/v3", "exulanica-society/v4"]
)
@pytest.mark.parametrize("operation", ["move", "remove", "undo"])
def test_direct_edit_without_adapter_rolls_back_object_and_all_history(
    runtime_world, profile, operation
):
    w = runtime_world
    helpers.add_plate(w)
    state = create_society(w, profile)
    w["connection"].commit()
    direct = WorldObjectRepository(
        w["connection"], w["workspace"], world_id=w["version"].world_id, store=w["store"]
    )
    version = direct.version(w["binding"].version_id)
    before = recorded_rows(w)
    kwargs = {"base_state_sha256": version.state_sha256, "actor": w["session"].actor}
    with pytest.raises(InvalidObjectState, match="atomic authored-input adapter"):
        if operation == "move":
            direct.move_object(
                version.version_id,
                "object:rest-fixture",
                Transform(41000, 0, 64000, 0, 1000),
                **kwargs,
            )
        elif operation == "remove":
            direct.remove_object(version.version_id, "object:rest-fixture", **kwargs)
        else:
            direct.undo(version.version_id, **kwargs)
    # Commit after catching the error: the repository itself must have rolled back its writes.
    w["connection"].commit()
    assert direct.version(version.version_id) == version
    assert recorded_rows(w) == before
    assert helpers.society(w).snapshot(version.version_id) == state
    replay = helpers.society(w).replay(version.version_id)
    assert replay["replay_verified"] and replay["state_sha256"] == state["state_sha256"]


def test_legacy_v1_still_allows_direct_edits_without_society_inputs(runtime_world):
    w = runtime_world
    helpers.add_plate(w)
    state = create_society(w, "exulanica-society/v1")
    w["connection"].commit()
    direct = WorldObjectRepository(
        w["connection"], w["workspace"], world_id=w["version"].world_id, store=w["store"]
    )
    version = direct.version(w["binding"].version_id)
    before = recorded_rows(w)
    moved = direct.move_object(
        version.version_id,
        "object:rest-fixture",
        Transform(41000, 0, 64000, 0, 1000),
        base_state_sha256=version.state_sha256,
        actor=w["session"].actor,
    )
    w["connection"].commit()
    assert moved.edit_seq == version.edit_seq + 1
    assert moved.state_sha256 != version.state_sha256
    assert moved.objects[0].transform.x_mm == 41000
    after = recorded_rows(w)
    assert (
        len(after["world_alternate_version_edit"])
        == len(before["world_alternate_version_edit"]) + 1
    )
    assert after["world_society_input"] == before["world_society_input"] == []
    assert helpers.society(w).snapshot(version.version_id) == state
    assert helpers.society(w).replay(version.version_id)["replay_verified"]
