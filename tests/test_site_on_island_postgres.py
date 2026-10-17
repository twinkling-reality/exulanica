"""A world made on a sky island's top through the normal route: kept by the database under the
receipt check every site world meets, drawn as ``exulanica.site-drawing/v6``, its graded top served
by the digest its drawing names and no land chunk or backdrop, its landscape drawn round it as
``exulanica.landscape-drawing/v2`` with the ground below served by digest, and refused by name for a
kind whose people come from homes off the site; and the shipped island hamlet made from its card,
with no landscape in the making, on its setting's island."""

from __future__ import annotations

import uuid

import pytest
from exulanica.world.generated_worlds import generation_receipt
from exulanica.world.site_top import SITE_TOP_PROFILE

from test_site_land_postgres import LAND, _farm
from test_site_on_island import LANDSCAPE
from test_society_made_world import made as imported_made  # noqa: F401
from test_world_kinds_postgres import _uploaded

pytestmark = pytest.mark.postgres


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


def _on_island(api, name: str, preset: str, title: str):  # type: ignore[no-untyped-def]
    response = api.post("/worlds/kinds", {"document": _uploaded(name)})
    kept = response.status_code == 409 and response.json()["code"] == "kind_version_exists"
    assert response.status_code == 201 or kept, response.text
    return api.post(
        f"/worlds/kinds/fixture_{name}/worlds",
        {"preset": preset, "title": title, "landscape": LANDSCAPE},
    )


def test_a_world_made_on_an_islands_top_is_kept_drawn_and_serves_its_top_by_digest(made):
    api = made
    response = _on_island(api, "hamlet", "small_hamlet", "Hamlet on the island")
    assert response.status_code == 201, response.text
    entry = response.json()
    version, world = entry["authored_version_id"], entry["world_id"]
    with api.database.session(api.repository.workspace_id) as connection:
        _, receipt = generation_receipt(
            connection, api.repository.workspace_id, world, uuid.UUID(entry["source_snapshot_id"])
        )
    assert receipt["composer"] == {"key": "site-plan", "version": 7}
    assert receipt["landscape"]["site"]["on"] == "isle"
    site = api.get(f"/world/versions/{version}/site?world_id={world}")
    assert site.status_code == 200, site.text
    drawing = site.json()
    assert drawing["profile"] == "exulanica.site-drawing/v6" and "land" not in drawing
    top = api.get(f"/world/versions/{version}/land/top?world_id={world}")
    assert top.status_code == 200, top.text
    assert top.headers["etag"] == f'"{drawing["top"]["top_sha256"]}"'
    assert top.json()["profile"] == SITE_TOP_PROFILE
    for path in ("land/backdrop", "land/chunks/0/0"):
        answer = api.get(f"/world/versions/{version}/{path}?world_id={world}")
        assert answer.status_code == 404, answer.text
        assert answer.json()["code"] in ("land_unavailable", "land_chunk_unavailable")
    served = api.get(f"/world/versions/{version}/landscape?world_id={world}")
    assert served.status_code == 200, served.text
    landscape = served.json()
    assert landscape["profile"] == "exulanica.landscape-drawing/v2"
    assert landscape["site_drawing_sha256"] == site.headers["etag"].strip('"')
    assert landscape["top_sha256"] == drawing["top"]["top_sha256"]
    ground = landscape["ground"]
    for digest in [chunk["sha256"] for chunk in ground["chunks"]] + [ground["backdrop_sha256"]]:
        body = api.get(
            f"/world/versions/{version}/landscape/ground?sha256={digest}&world_id={world}"
        )
        assert body.status_code == 200, body.text
        assert body.headers["etag"] == f'"{digest}"'
    missing = api.get(
        f"/world/versions/{version}/landscape/ground?sha256={'0' * 64}&world_id={world}"
    )
    assert (missing.status_code, missing.json()["code"]) == (404, "landscape_document_unavailable")


def test_a_world_on_land_has_no_top_to_serve(made):
    api = made
    response = _farm(api, "Farm on the slope", land=LAND)
    assert response.status_code == 201, response.text
    entry = response.json()
    top = api.get(
        f"/world/versions/{entry['authored_version_id']}/land/top?world_id={entry['world_id']}"
    )
    assert (top.status_code, top.json()["code"]) == (404, "land_unavailable")


def test_a_kind_whose_people_come_from_off_the_site_is_refused_on_a_top(made):
    api = made
    refused = _on_island(api, "cafe", "quiet_cafe", "Cafe on the island")
    assert refused.status_code == 422, refused.text
    assert (refused.json()["code"], refused.json()["path"]) == (
        "landscape_site_offsite_homes",
        "landscape.site",
    )


def test_the_shipped_island_hamlet_is_made_on_its_island_as_its_card_makes_it(made):
    api = made
    listed = {kind["kind"]: kind for kind in api.get("/worlds/kinds").json()["kinds"]}
    card = listed["island_hamlet"]
    assert (card["label"], card["source"]) == ("Hamlet on a sky island", "shipped")
    # As Create a world's card makes it: its first preset, its label for the title, no landscape.
    response = api.post(
        "/worlds/kinds/island_hamlet/worlds",
        {"version": card["version"], "preset": card["presets"][0]["key"], "title": card["label"]},
    )
    assert response.status_code == 201, response.text
    entry = response.json()
    with api.database.session(api.repository.workspace_id) as connection:
        _, receipt = generation_receipt(
            connection,
            api.repository.workspace_id,
            entry["world_id"],
            uuid.UUID(entry["source_snapshot_id"]),
        )
    assert receipt["composer"] == {"key": "site-plan", "version": 7}
    assert receipt["landscape"]["site"]["on"] == "isle"
