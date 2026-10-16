"""A site world made on a landscape through the normal route: kept by the database under the
receipt check every site world meets, its site drawn on its land, its landscape drawn beside it
by a kind worker job of its own and every chunk and top it names served by digest, and refused by
name where it does not fit."""

from __future__ import annotations

import hashlib
import json
import time
import uuid

import pytest
from exulanica.canonical import canonical_json
from exulanica.grammar.volumes import read_volume_chunk, read_volume_sheet
from exulanica.world.generated_worlds import generation_receipt

from test_landscape_document import ROCK
from test_site_land_postgres import LAND, _farm
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


def _landscape(api, **placement: object) -> dict:  # type: ignore[no-untyped-def]
    """The farm's land, its extent read from a farm made on that land, and a stack in the sea
    beyond its south edge."""
    level = _farm(api, "Farm to measure", land=LAND)
    assert level.status_code == 201, level.text
    entry = level.json()
    drawing = api.get(
        f"/world/versions/{entry['authored_version_id']}/site?world_id={entry['world_id']}"
    ).json()
    width, depth = drawing["extent"]["widthMm"], drawing["extent"]["depthMm"]
    stack = {"id": "stack", "volume": ROCK, "at_mm": [width // 2, -60000, -3000], **placement}
    return {
        "profile": "exulanica.landscape/v1",
        "extent_mm": [width, depth],
        "land": LAND,
        "volumes": [stack],
    }


def test_a_site_made_on_a_landscape_is_kept_drawn_and_serves_its_volumes_by_digest(made):
    api = made
    response = _farm(api, "Farm by the stacks", landscape=_landscape(api))
    assert response.status_code == 201, response.text
    entry = response.json()
    version, world = entry["authored_version_id"], entry["world_id"]
    # The database kept the receipt under the check every site world meets: no new migration.
    with api.database.session(api.repository.workspace_id) as connection:
        _, receipt = generation_receipt(
            connection, api.repository.workspace_id, world, uuid.UUID(entry["source_snapshot_id"])
        )
    assert receipt["composer"] == {"key": "site-plan", "version": 6}
    assert receipt["landscape"]["volumes"][0]["id"] == "stack"
    site = api.get(f"/world/versions/{version}/site?world_id={world}")
    assert site.status_code == 200, site.text
    assert site.json()["profile"] == "exulanica.site-drawing/v5"
    chunk = site.json()["land"]["chunks"][0]["chunk"]
    land = api.get(f"/world/versions/{version}/land/chunks/{chunk[0]}/{chunk[1]}?world_id={world}")
    assert land.status_code == 200, land.text
    served = api.get(f"/world/versions/{version}/landscape?world_id={world}")
    assert served.status_code == 200, served.text
    landscape = served.json()
    assert served.headers["etag"] == f'"{hashlib.sha256(canonical_json(landscape)).hexdigest()}"'
    assert landscape["profile"] == "exulanica.landscape-drawing/v1"
    assert landscape["site_drawing_sha256"] == site.headers["etag"].strip('"')
    (stack,) = landscape["volumes"]
    for named in stack["chunks"]:
        body = api.get(
            f"/world/versions/{version}/landscape/chunk?sha256={named['sha256']}&world_id={world}"
        )
        assert body.status_code == 200, body.text
        assert body.headers["etag"] == f'"{named["sha256"]}"'
        assert read_volume_chunk(body.json(), named["sha256"]).cell_mm == named["cell_mm"]
    for named in stack["tops"]:
        body = api.get(
            f"/world/versions/{version}/landscape/top?sha256={named['sha256']}&world_id={world}"
        )
        assert body.status_code == 200, body.text
        assert read_volume_sheet(body.json(), named["sha256"]).surface == named["surface"]
    # A chunk's digest asked of the tops, and a digest the drawing does not name, are not served.
    wrong = api.get(
        f"/world/versions/{version}/landscape/top?sha256={stack['chunks'][0]['sha256']}"
        f"&world_id={world}"
    )
    assert (wrong.status_code, wrong.json()["code"]) == (404, "landscape_document_unavailable")
    unknown = api.get(
        f"/world/versions/{version}/landscape/chunk?sha256={'0' * 64}&world_id={world}"
    )
    assert (unknown.status_code, unknown.json()["code"]) == (404, "landscape_document_unavailable")
    assert api.get(f"/world/versions/{version}/landscape?world_id={world}").json() == landscape


def test_a_landscape_drawn_past_its_limit_is_read_when_asked_again(made, monkeypatch):
    from exulanica.api.routes import world_kinds

    api = made
    response = _farm(api, "Farm by a slow stack", landscape=_landscape(api))
    assert response.status_code == 201, response.text
    entry = response.json()
    path = f"/world/versions/{entry['authored_version_id']}/landscape?world_id={entry['world_id']}"
    # Made without its landscape's drawing, which its own job makes once asked: past its limit the
    # route says so, and the finished drawing is read when asked again.
    monkeypatch.setattr(world_kinds, "LANDSCAPE_SECONDS", 0.001)
    first = api.get(path)
    assert (first.status_code, first.json()["code"]) == (503, "kind_work_overran"), first.text
    assert first.headers["retry-after"] == "2"
    for _ in range(600):
        served = api.get(path)
        if served.status_code != 503:
            break
        time.sleep(0.1)
    assert served.status_code == 200, served.text
    landscape = served.json()
    assert landscape["profile"] == "exulanica.landscape-drawing/v1"
    assert served.headers["etag"] == f'"{hashlib.sha256(canonical_json(landscape)).hexdigest()}"'


def test_a_world_on_no_landscape_has_none_to_serve(made):
    api = made
    response = _farm(api, "Farm on plain land", land=LAND)
    entry = response.json()
    version, world = entry["authored_version_id"], entry["world_id"]
    for path in ("landscape", f"landscape/chunk?sha256={'0' * 64}&"):
        joiner = "" if path.endswith("&") else "?"
        answer = api.get(f"/world/versions/{version}/{path}{joiner}world_id={world}")
        assert (answer.status_code, answer.json()["code"]) == (404, "landscape_unavailable")


def test_a_landscape_that_does_not_fit_its_site_is_refused_by_name_and_path(made):
    api = made
    onto = _landscape(api)
    width, depth = onto["extent_mm"]
    onto["volumes"][0]["at_mm"] = [width // 2, depth // 2, 0]
    refused = _farm(api, "Rock on the farm", landscape=onto)
    assert refused.status_code == 422, refused.text
    assert (refused.json()["code"], refused.json()["path"]) == (
        "landscape_volume_on_site",
        "landscape.volumes[0]",
    )
    inner = json.loads(json.dumps(_landscape(api)))
    inner["volumes"][0]["volume"]["parts"][0]["height_mm"] = 500
    refused = _farm(api, "Tiny rock", landscape=inner)
    assert (refused.status_code, refused.json()["path"]) == (
        422,
        "landscape.volumes[0].volume.parts[0].height_mm",
    )
    both = _farm(api, "Both", land=LAND, landscape=_landscape(api))
    assert (both.status_code, both.json()["code"]) == (422, "landscape_not_served")
    town = api.post(
        "/worlds/kinds/town/worlds",
        {"preset": "small_town", "title": "Town by the sea", "landscape": _landscape(api)},
    )
    assert (town.status_code, town.json()["code"]) == (422, "landscape_not_served")
