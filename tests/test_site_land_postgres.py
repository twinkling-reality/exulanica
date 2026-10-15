"""A site world made on land through the normal route: saved, drawn on its land, its chunks and
backdrop served by the digests its drawing names, regenerated from its receipt, refused by name."""

from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from exulanica.canonical import canonical_json
from exulanica.grammar.landform import read_land_chunk
from exulanica.world.composers import site_plan
from exulanica.world.generated_worlds import generation_receipt

from test_society_made_world import made as imported_made  # noqa: F401
from test_support_site import authoring, context
from test_world_kinds_postgres import _uploaded

pytestmark = pytest.mark.postgres

LAND = {
    "profile": "exulanica.landform/v1",
    "ground_mm": 8000,
    "features": [
        {"id": "tilt", "kind": "tilt", "side": "north", "grade_permille": 30},
        {"id": "sea", "kind": "shore", "side": "south", "distance_mm": 60000},
        {"id": "skyline", "kind": "range", "side": "north", "distance_mm": 2000000,
         "band_mm": 800000, "height_mm": 300000},
    ],
}  # fmt: skip


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


def _farm(api, title: str, **more):  # type: ignore[no-untyped-def]
    response = api.post("/worlds/kinds", {"document": _uploaded("farm")})
    kept = response.status_code == 409 and response.json()["code"] == "kind_version_exists"
    assert response.status_code == 201 or kept, response.text
    return api.post(
        "/worlds/kinds/fixture_farm/worlds", {"preset": "small_farm", "title": title, **more}
    )


def test_a_site_made_on_land_is_drawn_on_it_and_serves_its_land_by_digest(made):
    api = made
    response = _farm(api, "Farm on a slope", land=LAND)
    assert response.status_code == 201, response.text
    entry = response.json()
    version, world = entry["authored_version_id"], entry["world_id"]
    site = api.get(f"/world/versions/{version}/site?world_id={world}")
    assert site.status_code == 200, site.text
    drawing = site.json()
    assert drawing["profile"] == "exulanica.site-drawing/v5"
    assert site.headers["etag"] == f'"{hashlib.sha256(canonical_json(drawing)).hexdigest()}"'
    land = drawing["land"]
    assert len(land["chunks"]) == 9 and drawing["arrival"]["positionMm"][2] > 0
    for chunk in land["chunks"]:
        x, y = chunk["chunk"]
        served = api.get(f"/world/versions/{version}/land/chunks/{x}/{y}?world_id={world}")
        assert served.status_code == 200, served.text
        assert served.headers["etag"] == f'"{chunk["sha256"]}"'
        assert read_land_chunk(served.json(), chunk["sha256"]).chunk_x == x
    backdrop = api.get(f"/world/versions/{version}/land/backdrop?world_id={world}")
    assert backdrop.status_code == 200, backdrop.text
    assert backdrop.headers["etag"] == f'"{land["backdrop_sha256"]}"'
    assert hashlib.sha256(canonical_json(backdrop.json())).hexdigest() == land["backdrop_sha256"]
    assert api.get(f"/world/versions/{version}/site?world_id={world}").json() == drawing
    missing = api.get(f"/world/versions/{version}/land/chunks/40/40?world_id={world}")
    assert (missing.status_code, missing.json()["code"]) == (404, "land_chunk_unavailable")
    # The receipt the database keeps regenerates the same world, its land with it.
    with api.database.session(api.repository.workspace_id) as connection:
        _, receipt = generation_receipt(
            connection, api.repository.workspace_id, world, uuid.UUID(entry["source_snapshot_id"])
        )
    assert receipt["composer"] == {"key": "site-plan", "version": 5}
    assert receipt["land"]["ground_mm"] == 8000
    records = site_plan.records(receipt)
    place = site_plan.society_place("place:reopen", receipt, records)
    assert min(n["support_z_mm"] for n in place["nodes"]) > 0


def test_a_level_world_states_no_land(made):
    api = made
    response = _farm(api, "Level farm")
    assert response.status_code == 201, response.text
    entry = response.json()
    version, world = entry["authored_version_id"], entry["world_id"]
    assert api.get(f"/world/versions/{version}/site?world_id={world}").json()["profile"] == (
        "exulanica.site-drawing/v1"
    )
    for path in ("land/backdrop", "land/chunks/0/0"):
        answer = api.get(f"/world/versions/{version}/{path}?world_id={world}")
        assert (answer.status_code, answer.json()["code"]) == (404, "land_unavailable")


def test_land_the_catalog_refuses_or_the_route_does_not_serve_is_refused_by_name(made):
    api = made
    bad = json.loads(json.dumps(LAND))
    bad["features"][0]["grade_permille"] = 500
    refused = _farm(api, "Too steep", land=bad)
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "landform_invalid"
    assert refused.json()["path"] == "features[0].grade_permille"
    both = _farm(api, "Both", land=LAND, support=authoring(context()["base_place"]))
    assert (both.status_code, both.json()["code"]) == (422, "landform_not_served")
    town = api.post(
        "/worlds/kinds/town/worlds", {"preset": "small_town", "title": "Hill town", "land": LAND}
    )
    assert (town.status_code, town.json()["code"]) == (422, "landform_not_served")


def test_a_world_whose_land_rules_the_server_does_not_serve_is_listed_unavailable_by_name(
    made, monkeypatch
):
    """The listing runs the checks a world's drawing runs first, so it never offers a world on land
    that would refuse to open."""
    from exulanica.grammar.landform import rules

    api = made
    on_land = _farm(api, "Farm on older land rules", land=LAND)
    level = _farm(api, "Level farm beside it")
    assert on_land.status_code == 201 and level.status_code == 201, (on_land.text, level.text)
    # A server that makes and serves only the first rules version: the world was made by a later.
    monkeypatch.setattr(rules, "SERVED_LAND_RULES", {1: 1})
    monkeypatch.setattr(rules, "LAND_RULES_VERSION", 1)
    listed = {entry["entry_id"]: entry for entry in api.get("/world-entries").json()}
    refused = listed[on_land.json()["entry_id"]]
    assert (refused["availability"], refused["unavailable_reason"]) == (
        "unavailable",
        "generated_world_land_rules_changed",
    )
    assert refused["generated_site"] is None
    one = api.get(f"/world-entries/{on_land.json()['entry_id']}").json()
    assert one["unavailable_reason"] == "generated_world_land_rules_changed"
    kept = listed[level.json()["entry_id"]]
    assert kept["availability"] == "available" and kept["generated_site"] is not None
