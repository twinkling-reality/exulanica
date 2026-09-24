"""Real PG18 + authenticated HTTP with an explicit synthetic input/rights adapter."""

import uuid
from copy import deepcopy

import pytest
from exulanica.world.society import StaleSocietyState, UnavailableSocietyInput
from exulanica.world.society_repository import SocietyRepository
from psycopg.types.json import Jsonb

import test_world_objects_api as object_helpers
from society_fixtures import SEED, edited, seal, society_input

objects_api = object_helpers.objects_api

pytestmark = pytest.mark.postgres


@pytest.fixture
def purposeful(objects_api, repository):
    api = objects_api
    place = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)", (repository.workspace_id, place)
    )
    repository.connection.commit()
    version = api.version()
    version_id = uuid.UUID(version["version_id"])
    doc = society_input(version_id)
    rights = {"withdrawn": False}

    def authorize(document):
        if rights["withdrawn"] and document["availability"] == "available":
            raise UnavailableSocietyInput("fixture dependency withdrawn")

    api.client.app.state.society_initial_input = lambda *_args: doc
    api.client.app.state.society_input_authorizer = lambda _conn, _session, value: authorize(value)
    route = f"/world/versions/{version_id}/society"
    response = api.post(
        api.in_world(route),
        {
            "place_id": str(place),
            "region_id": "region-a",
            "seed": SEED,
            "profile": "exulanica-society/v2",
        },
    )
    assert response.status_code == 200, response.text
    repo = SocietyRepository(
        repository.connection,
        repository.workspace_id,
        world_id=api.world_id,
        input_authorizer=authorize,
    )
    return api, repo, version_id, route, doc, rights


def step(api, route):
    before = api.get(api.in_world(route)).json()
    response = api.post(
        api.in_world(route + "/steps"),
        {"base_tick": before["current_tick"], "base_state_sha256": before["state_sha256"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_v2_changed_inputs_ordered_events_authenticated_reload_and_replay(purposeful):
    api, repo, version, route, doc, _ = purposeful
    first = step(api, route)
    before_events = api.get(api.in_world(route + "/events")).json()
    moved = edited(doc)
    moved["targets"][0]["node_id"] = "a"
    seal(moved)
    disabled = edited(moved)
    disabled["targets"][0]["enabled"] = False
    seal(disabled)
    restored = edited(disabled)
    restored["targets"][0] = deepcopy(doc["targets"][0])
    seal(restored)
    for document in (moved, disabled, restored):
        repo.record_input(version, document)
    repo.connection.commit()
    result = step(api, route)
    assert result["input_seq"] == 4
    assert result["current_tick"] == 2
    path = api.in_world(route)
    assert api.get(path).json() == result  # Each HTTP call gets a fresh scoped DB connection.
    assert (
        api.post(
            api.in_world(route + "/steps"),
            {"base_tick": 1, "base_state_sha256": first["state_sha256"]},
        ).status_code
        == 409
    )
    response = api.get(api.in_world(route + "/replay"))
    assert response.status_code == 200, response.text
    assert response.json()["replay_verified"]
    assert response.json()["state_sha256"] == result["state_sha256"]
    assert api.stranger_get(path).status_code == 404
    assert api.stranger_get(api.in_world(route + "/events")).status_code == 404
    assert api.stranger_get(api.in_world(route + "/replay")).status_code == 404
    assert api.client.get(path).status_code == 401
    assert len(result["state"]["inhabitants"]) == 128
    transition = repo.connection.execute(
        "select * from world_society_transition where society_id=%s and tick=2",
        (uuid.UUID(result["society_id"]),),
    ).fetchone()
    assert transition["from_input_seq"] == 1 and transition["to_input_seq"] == 4
    assert transition["previous_state_sha256"] == first["state_sha256"]
    assert len(transition["event_ids"]) > 24
    stored = repo.connection.execute(
        "select count(*) as n from world_society_input where society_id=%s",
        (uuid.UUID(result["society_id"]),),
    ).fetchone()
    assert stored["n"] == 4
    assert before_events["events"]
    with pytest.raises(StaleSocietyState):
        repo.record_input(version, moved)
    assert api.get(api.in_world(route + "/replay")).json()["replay_verified"]


def test_withdrawal_blocks_historical_reads_but_unavailable_input_can_record_pause(purposeful):
    api, repo, version, route, doc, rights = purposeful
    state = step(api, route)
    rights["withdrawn"] = True
    replay = api.in_world(route + "/replay")
    assert api.get(api.in_world(route)).status_code == 424
    assert api.get(replay).status_code == 424
    unavailable = edited(doc)
    unavailable.update(availability="unavailable", unavailable_reason="source_withdrawn")
    seal(unavailable)
    repo.record_input(version, unavailable)
    repo.connection.commit()
    response = api.post(
        api.in_world(route + "/steps"),
        {"base_tick": state["current_tick"], "base_state_sha256": state["state_sha256"]},
    )
    assert response.status_code == 200, response.text
    paused = response.json()
    assert all(p["action"]["reason"] == "source_withdrawn" for p in paused["state"]["inhabitants"])
    # Historical replay still cannot resurrect withdrawn geometry.
    assert api.get(replay).status_code == 424
    restored = edited(unavailable)
    restored["authored_state"]["delta_sha256"] = doc["authored_state"]["delta_sha256"]
    seal(restored)
    repo.record_input(version, restored)
    repo.connection.commit()
    assert api.get(replay).status_code == 424


def test_missing_adapter_and_forged_input_json_fail_closed(objects_api, repository):
    api = objects_api
    version = api.version()
    path = api.in_world(f"/world/versions/{version['version_id']}/society")
    body = {
        "place_id": str(uuid.uuid4()),
        "region_id": "region-a",
        "seed": SEED,
        "profile": "exulanica-society/v2",
    }
    assert api.post(path, body).status_code == 424
    assert api.post(path, body | {"initial_input": society_input()}).status_code == 422


def test_replay_rejects_event_forgery_with_unchanged_snapshot(purposeful):
    api, repo, version, route, _doc, _ = purposeful
    state = step(api, route)
    event = api.get(api.in_world(route + "/events")).json()["events"][0]
    document = deepcopy(event["document"])
    document["order"] = 99999
    document["summary"] = "Forged event inconsistent with deterministic history."
    repo.connection.execute(
        "insert into "
        "world_society_event(workspace_id,society_id,event_id,tick,event_kind,"
        "subject_id,place_id,document,document_sha256) "
        "values(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            repo.workspace_id,
            uuid.UUID(state["society_id"]),
            uuid.uuid4(),
            1,
            "blocked",
            uuid.UUID(event["subject_id"]),
            uuid.UUID(state["place_id"]),
            Jsonb(document),
            "e" * 64,
        ),
    )
    with pytest.raises(ValueError, match="events do not match"):
        repo.replay(version)
    repo.connection.rollback()


def test_v2_branch_isolation_and_legacy_upgrade_refusal(purposeful):
    api, repo, version, route, doc, _ = purposeful
    original = step(api, route)
    other = api.version("Another synthetic branch")
    other_id = uuid.UUID(other["version_id"])
    other_doc = society_input(other_id)
    second = repo.create(
        other_id,
        place_id=uuid.UUID(original["place_id"]),
        region_id="region-a",
        seed=SEED,
        actor=api.actor,
        profile="exulanica-society/v2",
        initial_input=other_doc,
    )
    assert second["branch_id"] != original["branch_id"]
    assert second["current_tick"] == 0
    with pytest.raises(ValueError, match="another world or branch"):
        repo.record_input(other_id, seal(edited(doc)))
    with pytest.raises(StaleSocietyState, match="immutable"):
        repo.create(
            version,
            place_id=uuid.UUID(original["place_id"]),
            region_id="region-a",
            seed=SEED,
            actor=api.actor,
        )
    repo.connection.commit()
    assert api.get(api.in_world(route)).json() == original
