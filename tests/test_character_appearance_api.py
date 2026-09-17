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


def test_the_host_serves_saved_looks_over_the_committed_character_catalog(appearance_api):
    from exulanica.api.services import _character_appearance_runtime
    from exulanica.world.character_appearance import (
        designed_looks,
        load_character_catalog,
        recipe_from_look,
    )

    api, path = appearance_api
    services = api.client.app.state.services
    runtime = _character_appearance_runtime(services.store, {})
    assert runtime is not None
    api.client.app.state.services = replace(services, character_appearance=runtime)
    served = api.get(path + "/families").json()
    assert [entry["family"]["family_id"] for entry in served] == [
        "makehuman-people/v1/feminine",
        "makehuman-people/v1/masculine",
    ]
    catalog, looks = load_character_catalog()
    feminine = next(f for f in runtime.families if f.family_id.endswith("/feminine"))
    look = designed_looks(catalog, looks)["tailored-feminine"]["look"]
    body = {"base_revision": 0, "recipe": recipe_from_look(look, feminine).model_dump(mode="json")}
    saved = api.client.put(path, json=body, headers=api.headers)
    assert saved.status_code == 200, saved.text
    # Nothing is published in this test's registry, and the status says so.
    assert saved.json()["current"]["render_status"] == "asset_withdrawn_or_unreviewed"
    recipe = body["recipe"]
    crossed = {
        "base_revision": 1,
        "recipe": {
            **recipe,
            "parameters": {**recipe["parameters"], "outfit": "masculine/outfit/male_worksuit01"},
        },
    }
    assert api.client.put(path, json=crossed, headers=api.headers).status_code == 422
    reset = api.post(path + "/reset", {"base_revision": 1})
    assert reset.status_code == 200, reset.text
    default = designed_looks(catalog, looks)[looks["defaults"]["bases"]["feminine"]]["look"]
    assert reset.json()["current"]["document"]["recipe"] == recipe_from_look(
        default, feminine
    ).model_dump(mode="json")


def test_a_missing_character_catalog_is_an_absence_and_a_disagreeing_one_stops_startup(tmp_path):
    import json
    from pathlib import Path

    from exulanica.api.authorisation import TokenDirectory
    from exulanica.api.services import Services, _character_appearance_runtime
    from exulanica.store.local import LocalContentAddressedStore

    store = LocalContentAddressedStore(tmp_path / "blobs")
    missing = {"EXULANICA_CHARACTER_DIRECTORY": str(tmp_path / "nothing-here")}
    assert _character_appearance_runtime(store, missing) is None
    services = Services(
        database=None,
        readonly_database=None,
        store=store,
        tokens=TokenDirectory(sessions={}),
        executor_shares_the_write_role=False,
        model_client=None,
    )
    assert any("character catalog" in note for note in services.warnings)

    committed = Path(__file__).parents[1] / "assets/characters"
    directory = tmp_path / "characters"
    directory.mkdir()
    (directory / "catalog.json").write_bytes((committed / "catalog.json").read_bytes())
    looks = json.loads((committed / "looks.json").read_text())
    looks["defaults"]["player"] = "nobody"
    (directory / "looks.json").write_text(json.dumps(looks))
    disagreeing = {"EXULANICA_CHARACTER_DIRECTORY": str(directory)}
    with pytest.raises(ValueError, match="unknown looks"):
        _character_appearance_runtime(store, disagreeing)
