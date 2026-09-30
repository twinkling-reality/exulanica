"""A generated world whose identity none of its preset's seed candidates generate is drawn again.

``POST /worlds/generated`` draws a fresh identity and composes the world for it before its
transaction. When the composer refuses every candidate of that identity, the server draws another,
up to ``GENERATED_WORLD_DRAWS``; when it refuses every identity drawn, the request is refused by
name with each identity's refusals, and nothing is written.
"""

from __future__ import annotations

import dataclasses
from types import MappingProxyType

import pytest
from exulanica.world import generated_worlds as generated_worlds_module
from exulanica.world import world_recipes as recipe_catalog
from exulanica.world.composers import GeneratedWorldRefused
from exulanica.world.generated_worlds import BAKE_JOB_KIND
from exulanica.world.saved_entries import GENERATED_WORLD_DRAWS
from exulanica.world.world_recipes import CANDIDATES_MAXIMUM
from exulanica.world.worlds import workspace_worlds

from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


@pytest.fixture(autouse=True)
def _a_composed_identity_is_composed(monkeypatch):
    """The identity a test lets the composer generate is tried with the catalog's most candidates,
    so that identity is not itself refused now and then and drawn past."""
    generous = {
        recipe.key: dataclasses.replace(recipe, candidates=CANDIDATES_MAXIMUM)
        for recipe in recipe_catalog.world_recipes()
    }
    monkeypatch.setattr(recipe_catalog, "_by_key", lambda: MappingProxyType(generous))


def _refusal(recipe, world_id: str) -> GeneratedWorldRefused:
    """What the composer raises for an identity none of whose candidates generate."""
    return GeneratedWorldRefused(
        recipe.key,
        [
            {"candidate": candidate, "refusal": f"refusal {candidate} of {world_id}"}
            for candidate in range(recipe.candidates)
        ],
    )


def _written(repository) -> tuple[object, ...]:
    """Everything a made world writes that this workspace holds: its worlds, entries and bakes."""
    connection, workspace = repository.connection, repository.workspace_id
    entries = connection.execute(
        "select count(*) as n from saved_world_entry where workspace_id=%s", (workspace,)
    ).fetchone()["n"]
    jobs = connection.execute(
        "select count(*) as n from job where workspace_id=%s and kind=%s",
        (workspace, BAKE_JOB_KIND),
    ).fetchone()["n"]
    return (workspace_worlds(connection, workspace), entries, jobs)


def test_a_world_whose_first_identity_is_refused_is_made_for_another(
    objects_api, repository, monkeypatch
):
    drawn: list[str] = []
    compose = generated_worlds_module.compose_generated_world

    def first_refused(recipe, world_id):
        drawn.append(world_id)
        if len(drawn) == 1:
            raise _refusal(recipe, world_id)
        return compose(recipe, world_id)

    monkeypatch.setattr(generated_worlds_module, "compose_generated_world", first_refused)
    response = objects_api.post("/worlds/generated", {"recipe": "small_town", "title": "Drawn"})
    assert response.status_code == 201, response.text
    assert len(drawn) == 2 and drawn[0] != drawn[1]
    assert response.json()["world_id"] == drawn[1]
    held = {world.world_id for world in _written(repository)[0]}
    assert drawn[1] in held and drawn[0] not in held


def test_a_world_refused_for_every_identity_drawn_is_refused_by_name_and_nothing_is_written(
    objects_api, repository, monkeypatch
):
    drawn: list[str] = []

    def refused(recipe, world_id):
        drawn.append(world_id)
        raise _refusal(recipe, world_id)

    monkeypatch.setattr(generated_worlds_module, "compose_generated_world", refused)
    before = _written(repository)
    response = objects_api.post("/worlds/generated", {"recipe": "small_town", "title": "Refused"})
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "generated_world_refused"
    detail = response.json()["detail"]
    assert f"any of the {GENERATED_WORLD_DRAWS} identities drawn" in detail
    assert len(set(drawn)) == len(drawn) == GENERATED_WORLD_DRAWS
    candidates = recipe_catalog.world_recipe("small_town").candidates
    for world_id in drawn:
        for candidate in range(candidates):
            assert f"candidate {candidate}: refusal {candidate} of {world_id}" in detail
    assert _written(repository) == before
