"""A generated world is made wearing a look: the pack ``POST /worlds/generated`` names, or the host
library's default, named in its appearance's second version with its entry pointing there.

Made through the API as a deployment runs it (the runtime role, under row-level security). The
expected packs are read from the committed files, never from the library under test.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

import pytest
from exulanica.world import world_recipes as recipe_catalog
from exulanica.world.world_recipes import CANDIDATES_MAXIMUM
from exulanica.world.worlds import workspace_worlds

from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

STYLE_PACKS = Path(__file__).resolve().parents[1] / "assets" / "style-packs"


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def _every_town_a_test_makes_is_made(monkeypatch):
    """Each town is tried with the catalog's most candidates, as test_generated_worlds' are."""
    generous = {
        recipe.key: dataclasses.replace(recipe, candidates=CANDIDATES_MAXIMUM)
        for recipe in recipe_catalog.world_recipes()
    }
    monkeypatch.setattr(recipe_catalog, "_by_key", lambda: MappingProxyType(generous))


def _committed(pack_id: str) -> dict[str, object]:
    text = (STYLE_PACKS / "packs" / pack_id / "manifest.json").read_bytes()
    return {
        "pack_id": pack_id,
        "version": json.loads(text)["version"],
        "manifest_sha256": hashlib.sha256(text[:-1]).hexdigest(),
    }


def _default() -> str:
    return json.loads((STYLE_PACKS / "library.v1.json").read_text("utf-8"))["default"]


def _make(api, **more):
    return api.post("/worlds/generated", {"recipe": "small_town", "title": "Our town", **more})


def _styles(api, entry: dict) -> tuple[dict, list[dict]]:
    world = f"world_id={entry['world_id']}"
    current = api.get(f"/world/styles/current?{world}")
    versions = api.get(f"/world/styles/versions?{world}")
    assert current.status_code == 200 and versions.status_code == 200
    return current.json()["current"], versions.json()


def test_a_world_is_made_wearing_the_pack_it_names_in_its_second_version(made):
    toon = _committed("exulanica.toon-town")
    response = _make(made, style_pack=toon)
    assert response.status_code == 201, response.text
    entry = response.json()

    current, versions = _styles(made, entry)
    assert current["style_pack"] == toon
    assert entry["style_version_id"] == current["version_id"]
    first, second = sorted(versions, key=lambda version: version["revision"])
    assert first["style_pack"] is None
    assert second["style_pack"] == toon and second["parent_version_id"] == first["version_id"]
    assert second["provenance"]["origin"] == "user"
    assert second["provenance"]["origin_reference"] == "world-creation"
    # The look is all the version changes: its values are the first version's.
    assert second["global_style"] == first["global_style"]


@pytest.mark.parametrize("stated", [{}, {"style_pack": None}], ids=["absent", "null"])
def test_a_world_naming_no_pack_is_made_in_the_librarys_default(made, stated):
    response = _make(made, **stated)
    assert response.status_code == 201, response.text
    current, versions = _styles(made, response.json())
    assert current["style_pack"] == _committed(_default())
    assert len(versions) == 2


@pytest.mark.parametrize(
    "change",
    [{"pack_id": "exulanica.nowhere-town"}, {"version": 99}, {"manifest_sha256": "0" * 64}],
    ids=["unknown-pack", "other-version", "other-manifest"],
)
def test_a_pack_the_library_does_not_hold_is_refused_and_nothing_is_made(made, change):
    workspace = made.repository.workspace_id
    with made.database.session(workspace) as connection:
        before = workspace_worlds(connection, workspace)
    response = _make(made, style_pack={**_committed("exulanica.toon-town"), **change})
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_style_data"
    with made.database.session(workspace) as connection:
        assert workspace_worlds(connection, workspace) == before


def test_rolling_back_to_the_first_version_returns_the_world_to_naming_no_pack(made):
    response = _make(made, style_pack=_committed("exulanica.toon-town"))
    assert response.status_code == 201, response.text
    entry = response.json()
    current, versions = _styles(made, entry)
    first = min(versions, key=lambda version: version["revision"])
    rolled = made.post(
        f"/world/styles/rollback?world_id={entry['world_id']}",
        {
            "target_version_id": first["version_id"],
            "base_style_version_id": current["version_id"],
            "base_topology_digest": current["topology_digest"],
            "origin": "user",
        },
    )
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["style_pack"] is None
