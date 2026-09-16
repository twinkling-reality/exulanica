"""Society HTTP lifecycle on the real scratch PostgreSQL schema, synthetic data only."""

import uuid

import pytest

import test_world_objects_api as object_helpers

objects_api = object_helpers.objects_api

pytestmark = pytest.mark.postgres


def test_legacy_authenticated_reload_cas_branch_isolation(objects_api, repository):
    api = objects_api
    place = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place),
    )
    repository.connection.commit()
    version = api.version()
    route = f"/world/versions/{version['version_id']}/society"
    response = api.post(route, {"place_id": str(place), "region_id": "region-a", "seed": "7a" * 32})
    assert response.status_code == 200, response.text
    original = response.json()
    body = {"base_tick": 0, "base_state_sha256": original["state_sha256"]}
    stepped = api.post(route + "/steps", body)
    assert stepped.status_code == 200, stepped.text
    assert api.get(route).json() == stepped.json()
    assert api.post(route + "/steps", body).status_code == 409
    assert api.get(route + "/replay").json()["replay_verified"]
    assert api.stranger_get(route).status_code == 404
    assert api.stranger_post(route + "/steps", body).status_code == 404
    assert api.client.get(route).status_code == 401
    other_version = api.version("Other society branch")
    other_route = f"/world/versions/{other_version['version_id']}/society"
    other = api.post(
        other_route, {"place_id": str(place), "region_id": "region-a", "seed": "7a" * 32}
    )
    assert other.status_code == 200, other.text
    assert other.json()["society_id"] != original["society_id"]
    assert other.json()["current_tick"] == 0
    assert api.get(route).json()["current_tick"] == 1


def test_replay_rejects_extra_persisted_event_even_when_state_digest_matches(
    objects_api, repository
):
    from exulanica.world.society_repository import SocietyRepository
    from psycopg.types.json import Jsonb

    api = objects_api
    place = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place),
    )
    repository.connection.commit()
    version = api.version()
    route = f"/world/versions/{version['version_id']}/society"
    state = api.post(
        route, {"place_id": str(place), "region_id": "region-a", "seed": "7a" * 32}
    ).json()
    state = api.post(
        route + "/steps", {"base_tick": 0, "base_state_sha256": state["state_sha256"]}
    ).json()
    repository.connection.execute(
        "insert into world_society_event(workspace_id,society_id,event_id,tick,event_kind,"
        "subject_id,place_id,document,document_sha256) values(%s,%s,%s,1,%s,%s,%s,%s,%s)",
        (
            repository.workspace_id,
            uuid.UUID(state["society_id"]),
            uuid.uuid4(),
            "departed",
            uuid.UUID(state["state"]["inhabitants"][0]["id"]),
            place,
            Jsonb({"synthetic": True, "summary": "An extra event never produced by the engine."}),
            "a" * 64,
        ),
    )
    with pytest.raises(ValueError, match="events do not match"):
        SocietyRepository(repository.connection, repository.workspace_id).replay(
            uuid.UUID(version["version_id"])
        )
    repository.connection.rollback()
