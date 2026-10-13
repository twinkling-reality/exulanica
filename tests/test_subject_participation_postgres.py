"""An invitation never expands the selected-subject workspace read surface."""

import uuid

import pytest

import test_participation_postgres as participation

invited_world = participation.invited_world
_made_alias = participation._made_alias
_the_same_site_on_every_run = participation._the_same_site_on_every_run
imported_made = participation.imported_made

pytestmark = pytest.mark.postgres


def test_invitation_reads_only_through_its_grant_and_cannot_open_owner_subjects(invited_world):
    api, entry, _sessions = invited_world
    invite = participation._issue(api, entry)
    assert participation._redeem(api, invite).status_code == 200
    version = entry["authored_version_id"]
    route = f"/world/versions/{version}/subjects/world"
    query = {"world_id": entry["world_id"]}
    owner = api.client.get(route, params=query)
    assert owner.status_code == 200, owner.text
    headers = {"x-test-user": "visitor"}
    foreign = api.client.get(route, params=query, headers=headers)
    invented = api.client.get(
        f"/world/versions/{uuid.uuid4()}/subjects/world", params=query, headers=headers
    )
    assert foreign.status_code == invented.status_code == 404
    assert foreign.json()["code"] == invented.json()["code"] == "unknown_reference"
    grant = "/participation/" + invite["grant_id"]
    limited = api.client.get(grant + "/society", headers=headers)
    assert limited.status_code == 200, limited.text
    assert limited.json()["inhabitants"]
