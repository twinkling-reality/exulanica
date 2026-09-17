"""V4 living society over real PG18 and authenticated HTTP, with a synthetic rights adapter."""

import uuid

import pytest
from exulanica.world.society import StaleSocietyState, UnavailableSocietyInput
from exulanica.world.society_repository import SocietyRepository

import test_world_objects_api as object_helpers
from society_fixtures import edited, seal
from society_living_fixtures import SEEDS, grid_input

objects_api = object_helpers.objects_api

pytestmark = pytest.mark.postgres
PROFILE = "exulanica-society/v4"


@pytest.fixture
def living(objects_api, repository):
    api = objects_api
    place = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)", (repository.workspace_id, place)
    )
    repository.connection.commit()
    version_id = uuid.UUID(api.version()["version_id"])
    doc = grid_input(version_id=version_id)
    rights = {"withdrawn": False}

    def authorize(document):
        if rights["withdrawn"] and document["availability"] == "available":
            raise UnavailableSocietyInput("fixture dependency withdrawn")

    api.client.app.state.society_initial_input = lambda *_args: doc
    api.client.app.state.society_input_authorizer = lambda _conn, _session, value: authorize(value)
    route = f"/world/versions/{version_id}/society"
    body = {"place_id": str(place), "region_id": "region-a", "seed": SEEDS[4], "profile": PROFILE}
    response = api.post(route, body)
    assert response.status_code == 200, response.text
    repo = SocietyRepository(
        repository.connection, repository.workspace_id, input_authorizer=authorize
    )
    return api, repo, version_id, route, doc, rights, body


def step(api, route):
    before = api.get(route).json()
    response = api.post(
        route + "/steps",
        {"base_tick": before["current_tick"], "base_state_sha256": before["state_sha256"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_v4_persists_a_place_sized_population_with_receipts_reload_and_replay(living):
    api, repo, version, route, doc, _, body = living
    created = api.get(route).json()
    assert created["profile"] == PROFILE
    assert created["population_size"] == 30 == len(created["state"]["inhabitants"])
    assert created["state"]["population"]["rule"] == "place_sized"
    assert api.post(route, body).json() == created  # idempotent create
    assert api.post(route, body | {"profile": "exulanica-society/v2"}).status_code == 409
    for _ in range(3):
        result = step(api, route)
    assert result["current_tick"] == 3 and result["input_seq"] == 1
    disabled = edited(doc)
    next(t for t in disabled["targets"] if t["affordance"] == "rest")["enabled"] = False
    seal(disabled)
    repo.record_input(version, disabled)
    repo.connection.commit()
    result = step(api, route)
    assert result["input_seq"] == 2 and result["current_tick"] == 4
    assert api.get(route).json() == result
    stale = api.post(route + "/steps", {"base_tick": 3, "base_state_sha256": "0" * 64})
    assert stale.status_code == 409
    replay = api.get(route + "/replay")
    assert replay.status_code == 200, replay.text
    assert replay.json()["replay_verified"]
    assert replay.json()["state_sha256"] == result["state_sha256"]
    events = api.get(route + "/events").json()["events"]
    assert events and {e["document"]["profile"] for e in events} == {PROFILE}
    assert all(e["document"]["synthetic"] for e in events)
    transition = repo.connection.execute(
        "select * from world_society_transition where society_id=%s and tick=4",
        (uuid.UUID(result["society_id"]),),
    ).fetchone()
    assert (transition["from_input_seq"], transition["to_input_seq"]) == (1, 2)
    assert api.stranger_get(route).status_code == 404
    assert api.client.get(route).status_code == 401
    with pytest.raises(StaleSocietyState):
        repo.record_input(version, seal(edited(doc) | {"input_seq": 9}))


def test_v4_withdrawal_pauses_and_denies_historical_replay(living):
    api, repo, version, route, doc, rights, _ = living
    state = step(api, route)
    rights["withdrawn"] = True
    assert api.get(route).status_code == 424
    unavailable = edited(doc)
    unavailable.update(availability="unavailable", unavailable_reason="source_withdrawn")
    seal(unavailable)
    repo.record_input(version, unavailable)
    repo.connection.commit()
    response = api.post(
        route + "/steps",
        {"base_tick": state["current_tick"], "base_state_sha256": state["state_sha256"]},
    )
    assert response.status_code == 200, response.text
    paused = response.json()["state"]["inhabitants"]
    assert all(p["action"]["reason"] == "source_withdrawn" for p in paused)
    assert all(len(p["motion_path_mm"]) == 1 for p in paused)
    assert api.get(route + "/replay").status_code == 424


def test_v4_refuses_a_tampered_stored_state_and_keeps_older_population_bounds(living):
    api, repo, _, route, _, _, _ = living
    held = api.get(route).json()
    connection = repo.connection
    definition = connection.execute(
        "select pg_get_constraintdef(oid) as sql from pg_constraint "
        "where conname='world_society_population_size_check'"
    ).fetchone()["sql"]
    assert "exulanica-society/v4" in definition and "100" in definition and "512" in definition
    connection.execute(
        "update world_society set state=jsonb_set(state,'{tick}','7') where society_id=%s",
        (uuid.UUID(held["society_id"]),),
    )
    connection.commit()
    response = api.post(
        route + "/steps",
        {"base_tick": held["current_tick"], "base_state_sha256": held["state_sha256"]},
    )
    assert response.status_code == 409, response.text
