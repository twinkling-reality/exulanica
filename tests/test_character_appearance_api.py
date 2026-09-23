"""Authenticated HTTP using the existing session and scoped connection dependencies."""

import uuid
from dataclasses import replace
from functools import partial
from urllib.parse import urlencode

import pytest
from exulanica.api.routes.character_appearance import CharacterAppearanceRuntime

from character_appearance_fixtures import family, recipe
from test_world_objects_api import objects_api as objects_api

pytestmark = pytest.mark.postgres


def appearance_path(version_id, actor, world_id, suffix="", **query):
    """An appearance route for one world version; every operation names its world."""
    return (
        f"/world/versions/{version_id}/characters/avatar/{actor}/appearance{suffix}?"
        + urlencode({"world_id": world_id, **query})
    )


@pytest.fixture
def appearance_api(objects_api):
    api = objects_api
    services = api.client.app.state.services
    runtime = CharacterAppearanceRuntime((family(),), lambda connection, session, definition: True)
    api.client.app.state.services = replace(services, character_appearance=runtime)
    version = api.version()
    return api, partial(appearance_path, version["version_id"], api.actor, version["world_id"])


def test_authenticated_save_reopen_conflict_reset_and_history(appearance_api):
    api, at = appearance_api
    body = {"base_revision": 0, "recipe": recipe().model_dump(mode="json")}
    assert api.client.get(at()).status_code == 401
    assert api.stranger_get(at()).status_code == 404
    response = api.client.put(at(), json=body, headers=api.headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert api.get(at()).json() == response.json()
    assert api.client.put(at(), json=body, headers=api.headers).status_code == 409
    reset = api.post(at("/reset"), {"base_revision": 1})
    assert reset.status_code == 200, reset.text
    assert api.get(at("/history")).json()[1] == response.json()["current"]
    assert api.get(at("/families")).json()[0]["family_sha256"] == family().sha256
    assert api.get(at("/history", limit=101)).status_code == 422
    assert api.post(at("/reset"), {"base_revision": 2, "restore_revision": 100}).status_code == 422


def test_every_operation_names_the_world_its_version_belongs_to(appearance_api):
    api, at = appearance_api
    body = {"base_revision": 0, "recipe": recipe().model_dump(mode="json")}

    def refused_for_want_of_a_world(response):
        # A request that names no world is refused, and the refusal names the missing parameter.
        assert response.status_code == 422, response.text
        assert [(e["loc"], e["type"]) for e in response.json()["detail"]] == [
            (["query", "world_id"], "missing")
        ]

    for suffix in ("", "/history", "/families"):
        refused_for_want_of_a_world(api.get(at(suffix).split("?")[0]))
        assert api.get(at(suffix)).status_code == 200, suffix
    unnamed = at().split("?")[0]
    refused_for_want_of_a_world(api.client.put(unnamed, json=body, headers=api.headers))
    refused_for_want_of_a_world(api.post(at("/reset").split("?")[0], {"base_revision": 0}))
    assert api.get(at()).json()["revision"] == 0


def test_a_saved_starter_world_keeps_its_own_appearance_history(appearance_api):
    """The version of a saved starter world lives in that world, never in the default one."""
    api, at = appearance_api
    response = api.post("/world-entries/starter", {"title": "My world"})
    assert response.status_code == 200, response.text
    entry = response.json()
    assert entry["world_id"] != "atlas:default"
    starter = partial(appearance_path, entry["authored_version_id"], api.actor, entry["world_id"])
    body = {"base_revision": 0, "recipe": recipe().model_dump(mode="json")}
    saved = api.client.put(starter(), json=body, headers=api.headers)
    assert saved.status_code == 200, saved.text
    assert api.get(starter()).json() == saved.json()
    assert [r["revision"] for r in api.get(starter("/history")).json()] == [1]
    # The same version named under another world is not there, and the other world is untouched.
    elsewhere = appearance_path(entry["authored_version_id"], api.actor, "atlas:default")
    assert api.get(elsewhere).status_code == 404
    assert api.get(at()).json() == {"revision": 0, "current": None}


def test_client_cannot_supply_actor_scope_unregistered_family_or_output(appearance_api):
    api, at = appearance_api
    path = at()
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

    api, at = appearance_api
    services = api.client.app.state.services
    runtime = _character_appearance_runtime(services.store, {})
    assert runtime is not None
    api.client.app.state.services = replace(services, character_appearance=runtime)
    served = api.get(at("/families")).json()
    assert [entry["family"]["family_id"] for entry in served] == [
        "makehuman-people/v1/feminine",
        "makehuman-people/v1/masculine",
    ]
    catalog, looks = load_character_catalog()
    feminine = next(f for f in runtime.families if f.family_id.endswith("/feminine"))
    look = designed_looks(catalog, looks)["tailored-feminine"]["look"]
    body = {"base_revision": 0, "recipe": recipe_from_look(look, feminine).model_dump(mode="json")}
    saved = api.client.put(at(), json=body, headers=api.headers)
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
    assert api.client.put(at(), json=crossed, headers=api.headers).status_code == 422
    reset = api.post(at("/reset"), {"base_revision": 1})
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
