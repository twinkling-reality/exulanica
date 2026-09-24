"""Authenticated HTTP shape for registered end-to-end society actions."""

import uuid

import pytest

import test_society_runtime as runtime_helpers
from test_society_controls_api import control_api
from test_society_controls_postgres import create

runtime_world = runtime_helpers.runtime_world

pytestmark = pytest.mark.postgres
__all__ = ["control_api", "runtime_world"]


def test_typed_action_http_authentication_reload_and_rejection(runtime_world, control_api):
    world, api = runtime_world, control_api
    snapshot = create(world, "exulanica-society/v3")
    world["connection"].commit()
    api.client.app.state.society_input_authorizer = world["runtime"].authorize
    route = f"/world/versions/{world['binding'].version_id}/society/actions"
    path = api.in_world(route)
    target = next(
        target for target in runtime_helpers.initial(world)["targets"] if target["enabled"]
    )
    body = {
        "idempotency_key": str(uuid.uuid4()),
        "base_tick": snapshot["current_tick"],
        "base_state_sha256": snapshot["state_sha256"],
        "subject_id": snapshot["state"]["inhabitants"][0]["id"],
        "intent": {"kind": "go_to", "target_id": target["target_id"]},
    }
    assert api.client.post(path, json=body).status_code == 401
    stranger = api.stranger_post(path, body)
    assert stranger.status_code == 404, stranger.text
    saved = api.post(path, body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "pending"
    stepped = api.post(
        api.in_world(f"/world/versions/{world['binding'].version_id}/society/steps"),
        {
            "base_tick": snapshot["current_tick"],
            "base_state_sha256": snapshot["state_sha256"],
        },
    )
    assert stepped.status_code == 200, stepped.text
    assert stepped.json()["state"]["inhabitants"][0]["goal"]["target_id"] == target["target_id"]
    request_id = saved.json()["request"]["request_id"]
    consumed = api.get(api.in_world(route + "/" + request_id))
    assert consumed.status_code == 200 and consumed.json()["status"] == "consumed"
    assert api.get(path).json()["events"] == [consumed.json()]
    assert api.post(path, body).json() == consumed.json()
    replay = api.get(api.in_world(f"/world/versions/{world['binding'].version_id}/society/replay"))
    assert replay.status_code == 200 and replay.json()["replay_verified"]
    for invalid in (
        {**body, "position_mm": [20, 40]},
        {**body, "intent": {**body["intent"], "text": "walk over there"}},
        {**body, "base_tick": True},
    ):
        assert api.post(path, invalid).status_code == 422
    unknown = {**body, "idempotency_key": str(uuid.uuid4())}
    unknown["intent"] = {"kind": "go_to", "target_id": "browser:pixel:20,40"}
    assert api.post(path, unknown).status_code == 409
