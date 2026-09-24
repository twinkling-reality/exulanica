"""An authored edit and its society input handoff share one transaction."""

from __future__ import annotations

import pytest
from exulanica.world import InvalidObjectState, WorldObjectRepository

pytestmark = pytest.mark.postgres
pytest_plugins = ("test_world_objects_api",)


def test_observer_sees_every_authored_state_before_next_tick(objects_api):
    api = objects_api
    seen = []

    def observe(connection, session, version_id):
        version = WorldObjectRepository(
            connection, session.workspace_id, world_id=api.world_id
        ).version(version_id)
        seen.append(
            (version.edit_seq, version.state_sha256, tuple(o.object_id for o in version.objects))
        )

    api.client.app.state.society_authored_edit = observe
    version = api.version()
    added = api.add(version)
    assert added.status_code == 201, added.text
    held = added.json()
    undo = api.post(
        api.in_world(f"/world/versions/{held['version_id']}/objects/undo"),
        {
            "base_state_sha256": held["state_sha256"],
        },
    )
    assert undo.status_code == 200, undo.text
    assert [entry[0] for entry in seen] == [1, 2]
    assert seen[0][2] == ("object:lantern",)
    assert seen[1][2] == ()
    assert seen[0][1] == held["state_sha256"]
    assert seen[1][1] == undo.json()["state_sha256"]


def test_observer_failure_rolls_back_object_and_edit_history(objects_api):
    api = objects_api
    version = api.version()

    def refuse(connection, session, version_id):
        current = WorldObjectRepository(
            connection, session.workspace_id, world_id=api.world_id
        ).version(version_id)
        assert current.edit_seq == 1
        assert len(current.objects) == 1
        raise InvalidObjectState("society input could not be recorded")

    api.client.app.state.society_authored_edit = refuse
    response = api.add(version)
    assert response.status_code == 409, response.text
    reloaded = api.get(api.in_world(f"/world/versions/{version['version_id']}")).json()
    assert reloaded["state_sha256"] == version["state_sha256"]
    assert reloaded["edit_seq"] == 0
    assert reloaded["objects"] == []
    assert reloaded["edits"] == []
