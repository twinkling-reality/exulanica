"""Authenticated HTTP using the existing session and scoped connection dependencies."""

import uuid
from dataclasses import replace

import pytest
from exulanica.api.routes.character_appearance import CharacterAppearanceRuntime

from character_appearance_fixtures import family, recipe
from test_world_objects_api import objects_api as objects_api

pytestmark = pytest.mark.postgres


@pytest.fixture
def appearance_api(objects_api):
    api = objects_api
    services = api.client.app.state.services
    runtime = CharacterAppearanceRuntime((family(),), lambda connection, session, definition: True)
    api.client.app.state.services = replace(services, character_appearance=runtime)
    version = api.version()
    path = f"/world/versions/{version['version_id']}/characters/avatar/{api.actor}/appearance"
    return api, path


def test_authenticated_save_reopen_conflict_reset_and_history(appearance_api):
    api, path = appearance_api
    body = {"base_revision": 0, "recipe": recipe().model_dump(mode="json")}
    assert api.client.get(path).status_code == 401
    assert api.stranger_get(path).status_code == 404
    response = api.client.put(path, json=body, headers=api.headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert api.get(path).json() == response.json()
    assert api.client.put(path, json=body, headers=api.headers).status_code == 409
    reset = api.post(path + "/reset", {"base_revision": 1})
    assert reset.status_code == 200, reset.text
    assert api.get(path + "/history").json()[1] == response.json()["current"]
    assert api.get(path + "/families").json()[0]["family_sha256"] == family().sha256
    assert api.get(path + "/history?limit=101").status_code == 422
    assert (
        api.post(path + "/reset", {"base_revision": 2, "restore_revision": 100}).status_code == 422
    )


def test_client_cannot_supply_actor_scope_unregistered_family_or_output(appearance_api):
    api, path = appearance_api
    base = {"base_revision": 0, "recipe": recipe().model_dump(mode="json")}
    for body in (
        {**base, "actor": str(uuid.uuid4())},
        {**base, "workspace_id": str(uuid.uuid4())},
        {**base, "base_revision": False},
        {
            **base,
            "recipe": {
                **base["recipe"],
                "parameters": {"height": "175", "clothing": "shirt", "color": "#eeeeee"},
            },
        },
        {**base, "recipe": {**base["recipe"], "representation_id": "injected"}},
    ):
        assert api.client.put(path, json=body, headers=api.headers).status_code == 422
    unknown = {**base, "recipe": {**base["recipe"], "family_sha256": "9" * 64}}
    assert api.client.put(path, json=unknown, headers=api.headers).status_code == 424
    other = path.replace(str(api.actor), str(uuid.uuid4()))
    assert api.get(other).status_code == 404
    assert api.client.put(other, json=base, headers=api.headers).status_code == 404
    assert api.get(path).json()["revision"] == 0
    api.client.app.state.services = replace(
        api.client.app.state.services, character_appearance=None
    )
    assert api.get(path).status_code == 424
