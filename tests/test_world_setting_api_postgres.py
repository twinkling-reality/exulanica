"""A world's setting over HTTP: chosen by named parts or stated outright in a preview, applied,
read back, refused by name, and worn by a generated world from the moment it is made.

Each expected setting is composed here from the committed parts for the committed pack, read from
their files, never read back from the server under test.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from exulanica.world import world_recipes as recipe_catalog
from exulanica.world import world_settings as ws
from exulanica.world.style_packs import canonical_json, load_context
from exulanica.world.world_recipes import CANDIDATES_MAXIMUM
from exulanica.world.worlds import workspace_worlds

from test_society_made_world import made as imported_made  # noqa: F401
from test_world_api import world_api as world_api

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "assets" / "style-packs" / "packs"
CONTEXT = load_context(ROOT)


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture
def _every_town_is_made(monkeypatch):
    """Each town is tried with the catalog's most candidates, as test_generated_worlds' are."""
    generous = {
        recipe.key: dataclasses.replace(recipe, candidates=CANDIDATES_MAXIMUM)
        for recipe in recipe_catalog.world_recipes()
    }
    monkeypatch.setattr(recipe_catalog, "_by_key", lambda: MappingProxyType(generous))


def committed(pack_id: str) -> dict[str, Any]:
    text = (PACKS / pack_id / "manifest.json").read_bytes()
    return {
        "pack_id": pack_id,
        "version": json.loads(text)["version"],
        "manifest_sha256": hashlib.sha256(text[:-1]).hexdigest(),
    }


def composed(pack_id: str, chosen: dict[str, str]) -> dict[str, Any]:
    """What the answer states for ``pack_id`` drawn in the ``chosen`` parts: the setting and the
    SHA-256 of its canonical bytes."""
    manifest = json.loads((PACKS / pack_id / "manifest.json").read_text("utf-8"))
    setting = ws.compose_setting(chosen, ws.resolve_chain([manifest]), CONTEXT, ws.setting_parts())
    return {
        "setting": setting,
        "setting_sha256": hashlib.sha256(canonical_json(setting).encode("ascii")).hexdigest(),
    }


def test_named_parts_are_composed_previewed_applied_and_read_back(world_api):
    cozy = committed("exulanica.cozy-town")
    chosen = {"sky": "dusk", "ground": "sea"}
    body = world_api.preview_body()
    body["stylePack"] = {
        "packId": cozy["pack_id"],
        "version": cozy["version"],
        "manifestSha256": cozy["manifest_sha256"],
        "settingParts": chosen,
    }
    preview = world_api.post("/world/styles/previews", body)
    assert preview.status_code == 201, preview.text
    expected = {**cozy, **composed("exulanica.cozy-town", chosen)}
    assert preview.json()["candidate"]["style_pack"] == expected
    assert expected["setting"]["parts"] == [
        {"axis": "sky", "key": "dusk"},
        {"axis": "ground", "key": "sea"},
    ]
    applied = world_api.post(
        f"/world/styles/previews/{preview.json()['preview_id']}/apply",
        {
            "base_style_version_id": body["base_style_version_id"],
            "base_topology_digest": body["base_topology_digest"],
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["style_pack"] == expected
    assert world_api.current()["current"]["style_pack"] == expected
    # A proposal that names no pack keeps the pack and the setting drawn over it.
    kept = world_api.post("/world/styles/previews", world_api.preview_body())
    assert kept.json()["candidate"]["style_pack"] == expected
    # The pack named again with no setting is drawn as it states: the answer is the pack alone.
    plain = world_api.post("/world/styles/previews", world_api.preview_body(style_pack=cozy))
    assert plain.status_code == 201, plain.text
    assert plain.json()["candidate"]["style_pack"] == cozy


def test_a_setting_stated_outright_is_taken_as_the_document_it_is(world_api):
    toon = committed("exulanica.toon-town")
    stated = composed("exulanica.toon-town", {"sky": "overcast"})
    asked = world_api.post(
        "/world/styles/previews",
        world_api.preview_body(style_pack={**toon, "setting": stated["setting"]}),
    )
    assert asked.status_code == 201, asked.text
    assert asked.json()["candidate"]["style_pack"] == {**toon, **stated}


@pytest.mark.parametrize(
    ("setting", "said"),
    [
        ({"setting_parts": {"sky": "aurora"}}, "parts.sky"),
        ({"setting_parts": {"weather": "night"}}, "parts.weather"),
        (
            {
                "setting": {
                    "profile": "exulanica.world-setting/v1",
                    "origin": "authored",
                    "provenance": {"kind": "authored"},
                    "parts": [],
                    "light": {"from": "day", "changes": {"sun.shadow": {"filter": "pcf1"}}},
                    "surfaces": {},
                    "up": {},
                    "swatches": {},
                    "edge": None,
                }
            },
            "light.changes.sun.shadow",
        ),
    ],
)
def test_a_setting_the_pack_cannot_be_drawn_in_is_refused_by_name(world_api, setting, said):
    body = world_api.preview_body(style_pack={**committed("exulanica.cozy-town"), **setting})
    response = world_api.post("/world/styles/previews", body)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_style_data"
    assert said in response.json()["detail"]
    assert world_api.current()["current"]["style_pack"] is None


def _stated(**over):
    return {
        "profile": "exulanica.world-setting/v1",
        "origin": "authored",
        "provenance": {"kind": "authored"},
        "parts": [],
        "light": None,
        "surfaces": {},
        "up": {},
        "swatches": {},
        "edge": None,
        **over,
    }


_DRAFTED = {
    "kind": "drafted",
    "model_id": "example/model",
    "prompt_version": "setting-drafting-1",
    "execution_id": "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b",
}


@pytest.mark.parametrize(
    ("setting", "said"),
    [
        # A caller cannot say a model drafted its setting: only the host's own step states that.
        (_stated(origin="drafted", provenance=_DRAFTED), "origin"),
        # Nor hide a digest of words, or words, in a name of a part.
        (_stated(parts=[{"axis": "sky", "key": "a" * 32}]), "parts[0].key"),
        (_stated(parts=[{"axis": "my_own_words", "key": "dusk"}]), "parts[0].axis"),
    ],
)
def test_a_request_states_no_drafted_setting_and_no_part_the_host_does_not_list(
    world_api, setting, said
):
    body = world_api.preview_body(
        style_pack={**committed("exulanica.cozy-town"), "setting": setting}
    )
    response = world_api.post("/world/styles/previews", body)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_style_data"
    assert f"refused: {said}: " in response.json()["detail"], response.json()["detail"]


def test_a_request_states_a_setting_or_its_parts_and_not_both(world_api):
    cozy = committed("exulanica.cozy-town")
    both = {
        **cozy,
        "setting": composed("exulanica.cozy-town", {"sky": "dusk"})["setting"],
        "setting_parts": {"sky": "dusk"},
    }
    response = world_api.post("/world/styles/previews", world_api.preview_body(style_pack=both))
    assert response.status_code == 422, response.text
    assert world_api.current()["current"]["style_pack"] is None


def test_a_town_is_made_in_the_setting_its_request_names(made, _every_town_is_made):
    toon = committed("exulanica.toon-town")
    chosen = {"sky": "night", "cover": "snow"}
    response = made.post(
        "/worlds/generated",
        {
            "recipe": "small_town",
            "title": "Our town",
            "style_pack": {**toon, "setting_parts": chosen},
        },
    )
    assert response.status_code == 201, response.text
    entry = response.json()
    current = made.get(f"/world/styles/current?world_id={entry['world_id']}").json()["current"]
    assert current["style_pack"] == {**toon, **composed("exulanica.toon-town", chosen)}
    assert entry["style_version_id"] == current["version_id"]


def test_a_refused_setting_makes_no_town(made, _every_town_is_made):
    workspace = made.repository.workspace_id
    with made.database.session(workspace) as connection:
        before = workspace_worlds(connection, workspace)
    response = made.post(
        "/worlds/generated",
        {
            "recipe": "small_town",
            "title": "Our town",
            "style_pack": {**committed("exulanica.toon-town"), "setting_parts": {"sky": "aurora"}},
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_style_data"
    assert "parts.sky" in response.json()["detail"]
    with made.database.session(workspace) as connection:
        assert workspace_worlds(connection, workspace) == before
