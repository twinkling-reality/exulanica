"""The land round a town made on its land, served the way a site's is: its section names every chunk
and its backdrop by digest, made in the kind worker and kept by the town's receipt; a town on level
ground has none, and a site states its land in its drawing instead."""

from __future__ import annotations

import dataclasses
import hashlib
import time
import uuid

import pytest
from exulanica.grammar.landform import land_recipes, read_land_document
from exulanica.world import generated_worlds
from exulanica.world.composers import GeneratedWorldRefused
from exulanica.world.generated_worlds import generation_receipt
from exulanica.world.world_recipes import preset_land

from test_society_made_world import made as imported_made  # noqa: F401
from test_world_kinds_postgres import _uploaded

pytestmark = pytest.mark.postgres

[ROLLING] = [recipe for recipe in land_recipes() if recipe.key == "rolling"]
#: How many times a land document is asked for while the kind worker is still making it: each ask
#: waits as long as a request does, so this bounds a slow machine's wait at a few minutes.
ASKS = 12


@pytest.fixture(name="made")
def _made_alias(request):  # type: ignore[no-untyped-def]
    return request.getfixturevalue("imported_made")


def _town(api, **more):  # type: ignore[no-untyped-def]
    services = api.client.app.state.services
    api.client.app.state.services = dataclasses.replace(services, worlds_on_land=True)
    try:
        response = api.post(
            "/worlds/kinds/town/worlds", {"preset": "small_town", "title": "A town", **more}
        )
    finally:
        api.client.app.state.services = services
    assert response.status_code == 201, response.text
    return response.json()


def _read(api, path: str):  # type: ignore[no-untyped-def]
    """A land document, asked again while the worker is still making it, after the wait its answer
    names, as the route asks: the finished work is kept and read."""
    response = api.get(path)
    for _ in range(ASKS - 1):
        if response.status_code != 503:
            break
        time.sleep(min(int(response.headers.get("retry-after", "1")), 5))
        response = api.get(path)
    return response


def test_a_town_on_land_serves_its_land_section_and_every_chunk_and_its_backdrop_by_digest(made):
    api = made
    entry = _town(api, land=dict(ROLLING.land))
    version, world = entry["authored_version_id"], entry["world_id"]
    land_sha256 = read_land_document(dict(ROLLING.land)).sha256
    assert entry["generated_ground"]["land_sha256"] == land_sha256
    answer = _read(api, f"/world/versions/{version}/land?world_id={world}")
    assert answer.status_code == 200, answer.text
    assert answer.headers["etag"] == f'"{hashlib.sha256(answer.content).hexdigest()}"'
    section = answer.json()
    assert section["profile"] == "exulanica.town-land/v1"
    assert section["world_id"] == world
    assert section["land"]["land_sha256"] == land_sha256
    tiles = {(tile["tile_x"], tile["tile_y"]) for tile in entry["generated_ground"]["tiles"]}
    named = {tuple(chunk["chunk"]): chunk["sha256"] for chunk in section["land"]["chunks"]}
    assert tiles < set(named), "the near land rings the town's tiles"
    for (x, y), digest in named.items():
        chunk = _read(api, f"/world/versions/{version}/land/chunks/{x}/{y}?world_id={world}")
        assert chunk.status_code == 200, chunk.text
        assert chunk.headers["etag"] == f'"{digest}"'
        assert hashlib.sha256(chunk.content).hexdigest() == digest
    backdrop = _read(api, f"/world/versions/{version}/land/backdrop?world_id={world}")
    assert backdrop.headers["etag"] == f'"{section["land"]["backdrop_sha256"]}"'
    missing = api.get(f"/world/versions/{version}/land/chunks/900/900?world_id={world}")
    assert (missing.status_code, missing.json()["code"]) == (404, "land_chunk_unavailable")


def test_a_town_on_level_ground_and_a_site_answer_by_name(made):
    api = made
    level = _town(api)
    assert level["generated_ground"]["land_sha256"] is None
    version, world = level["authored_version_id"], level["world_id"]
    for path in ("land", "land/backdrop", "land/chunks/0/0"):
        answer = api.get(f"/world/versions/{version}/{path}?world_id={world}")
        assert (answer.status_code, answer.json()["code"]) == (404, "land_unavailable"), path
    response = api.post("/worlds/kinds", {"document": _uploaded("farm")})
    assert response.status_code == 201 or response.json()["code"] == "kind_version_exists"
    farm = api.post("/worlds/kinds/fixture_farm/worlds", {"preset": "small_farm", "title": "Farm"})
    assert farm.status_code == 201, farm.text
    site = farm.json()
    answer = api.get(
        f"/world/versions/{site['authored_version_id']}/land?world_id={site['world_id']}"
    )
    assert (answer.status_code, answer.json()["code"]) == (404, "unknown_reference")


def test_a_town_made_from_its_card_stands_on_its_presets_land_where_worlds_are_made_on_land(made):
    """POST /worlds/generated, what a town's card sends, lays the town on its preset's land where
    the deployment makes worlds on land, and on level ground where it does not."""
    api = made

    def card(on_land: bool):  # type: ignore[no-untyped-def]
        services = api.client.app.state.services
        api.client.app.state.services = dataclasses.replace(services, worlds_on_land=on_land)
        try:
            response = api.post("/worlds/generated", {"recipe": "small_town", "title": "A town"})
        finally:
            api.client.app.state.services = services
        assert response.status_code == 201, response.text
        return response.json()

    land = preset_land("small_town")
    assert land is not None
    on = card(True)
    assert on["generated_ground"]["land_sha256"] == read_land_document(dict(land.land)).sha256
    assert card(False)["generated_ground"]["land_sha256"] is None


def test_a_card_town_its_land_refuses_is_made_level_and_its_receipt_says_which_land_and_why(
    made, monkeypatch
):
    """A town's card never meets a refusal for its land: where no layout of the town fits its
    preset's land, the town is made on level ground and its receipt's recipe names that land and
    the refusal."""
    api = made
    composed = generated_worlds.compose_generated_world

    def refusing_land(recipe, world_id):  # type: ignore[no-untyped-def]
        if recipe.land is not None:
            raise GeneratedWorldRefused(recipe.key, [{"candidate": 0, "refusal": "no fit"}])
        return composed(recipe, world_id)

    monkeypatch.setattr(generated_worlds, "compose_generated_world", refusing_land)
    services = api.client.app.state.services
    api.client.app.state.services = dataclasses.replace(services, worlds_on_land=True)
    try:
        response = api.post("/worlds/generated", {"recipe": "market_town", "title": "A town"})
    finally:
        api.client.app.state.services = services
    assert response.status_code == 201, response.text
    entry = response.json()
    assert entry["generated_ground"]["land_sha256"] is None
    land = preset_land("market_town")
    assert land is not None
    with api.database.session(api.repository.workspace_id) as connection:
        _, receipt = generation_receipt(
            connection,
            api.repository.workspace_id,
            entry["world_id"],
            uuid.UUID(entry["source_snapshot_id"]),
        )
    assert "land" not in receipt
    assert receipt["recipe"]["land_refused"] == {
        "recipe": land.key,
        "land_sha256": land.land_sha256,
        "code": "generated_world_refused",
    }
