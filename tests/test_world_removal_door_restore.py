"""A carried world erasure explains missing door withdrawals only for its own world."""

import pytest
from exulanica.deletion.withdrawals import Carried, stale_withdrawals

from test_door_postgres import _issue, _world_id
from test_door_postgres import door as door
from test_door_postgres import saved_world as saved_world
from test_society_saved_world_api import OWNER

pytestmark = pytest.mark.postgres


def test_world_removal_stale_check_follows_door_parent_keys(door):
    issued = _issue(door)
    assert issued.status_code == 201, issued.text
    grant = issued.json()["grant"]["grant_id"]
    invited = door["client"].post(f"/door/grants/{grant}/invites", headers=OWNER)
    assert invited.status_code in (200, 201), invited.text
    assert (
        door["client"].post(f"/door/grants/{grant}/credentials/revoke", headers=OWNER).status_code
        == 200
    )
    assert door["client"].post(f"/door/grants/{grant}/revoke", headers=OWNER).status_code == 200
    workspace = door["world"]["workspace"]
    # A restore reads all withdrawal categories as its administrative role.
    connection = door["world"]["connection"]
    with connection.transaction():
        before = {kind for kind, _ in stale_withdrawals(connection, [])}
        assert {"door_grant", "door_secret"} <= before
        wrong = [Carried("world_erasure", {"workspace_id": str(workspace), "world_id": "other"})]
        assert {kind for kind, _ in stale_withdrawals(connection, wrong)} == before
        carried = [
            Carried("world_erasure", {"workspace_id": str(workspace), "world_id": _world_id(door)})
        ]
        assert not {kind for kind, _ in stale_withdrawals(connection, carried)} & {
            "door_grant",
            "door_secret",
        }
