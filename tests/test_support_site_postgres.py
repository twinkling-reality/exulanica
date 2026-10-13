"""Optional support authoring uses normal admission, saving, reopen and replay paths."""

from __future__ import annotations

import copy
import json
import os
import uuid
from pathlib import Path

import pytest
from exulanica.world.composers import site_plan
from exulanica.world.generated_worlds import generation_receipt
from exulanica.world.support_surfaces import read_support_network

from test_society_made_world import made as imported_made  # noqa: F401
from test_support_site import authoring, context
from test_world_kinds_postgres import _uploaded

pytestmark = pytest.mark.postgres


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


def test_normal_api_saves_reopens_and_replays_source_bound_support(made):
    api = made
    response = api.post("/worlds/kinds", {"document": _uploaded("farm")})
    assert response.status_code == 201, response.text
    request = {
        "preset": "small_farm",
        "title": "Supported route",
        "support": authoring(context()["base_place"]),
    }
    response = api.post("/worlds/kinds/fixture_farm/worlds", request)
    assert response.status_code == 201, response.text
    entry = response.json()
    path = f"/world/versions/{entry['authored_version_id']}/site?world_id={entry['world_id']}"
    first = api.get(path)
    assert first.status_code == 200, first.text
    drawing = first.json()
    assert drawing["profile"] == "exulanica.site-drawing/v2"
    adapter = drawing["support"]
    assert adapter["network"]["source"]["world_id"] == entry["world_id"]
    network = read_support_network(adapter["network"])
    assert (
        network.support_at(
            "deck",
            tuple(
                next(n for n in network.document()["nodes"] if n["node_id"] == "view")[
                    "position_mm"
                ]
            ),
        )
        == 150
    )
    assert api.get(path).json() == drawing
    with api.database.session(api.repository.workspace_id) as connection:
        _, receipt = generation_receipt(
            connection,
            api.repository.workspace_id,
            entry["world_id"],
            uuid.UUID(entry["source_snapshot_id"]),
        )
    assert receipt["composer"]["version"] == 2
    records = site_plan.records(receipt)
    place = site_plan.society_place("place:reopen", receipt, records)
    assert {n["support_z_mm"] for n in place["nodes"]} == {0, 150}
    assert any(t["destination_id"] == "destination:rest" for t in place["destinations"])
    assert len(adapter["node_surfaces"]) == len(place["nodes"])
    assert adapter["entry_node_id"] in adapter["node_surfaces"]
    evidence_path = os.environ.get("EXULANICA_SUPPORT_EVIDENCE")
    if evidence_path:
        Path(evidence_path).write_text(
            json.dumps(
                {
                    "origin": "normal API, authored deterministic fixture; no model evidence",
                    "request": request,
                    "entry": entry,
                    "receipt": dict(receipt),
                    "drawing": drawing,
                    "place": place,
                },
                indent=2,
            )
            + "\n"
        )
    # A declared unavailable connection fails before any saved world is appended.
    invalid = copy.deepcopy(request)
    invalid["support"]["connections"] = []
    response = api.post("/worlds/kinds/fixture_farm/worlds", invalid)
    assert response.status_code == 422 and response.json()["code"] == "support_network_invalid"


def test_bad_support_shapes_and_town_support_are_named_refusals(made):
    api = made
    response = api.post("/worlds/kinds", {"document": _uploaded("farm")})
    assert response.status_code == 201, response.text
    for invalid in ({}, {"profile": "unknown"}, {"nodes": [{"node_id": []}]}):
        response = api.post(
            "/worlds/kinds/fixture_farm/worlds",
            {"preset": "small_farm", "title": "Bad", "support": invalid},
        )
        assert response.status_code == 422, response.text
    response = api.post(
        "/worlds/kinds/town/worlds", {"preset": "small_town", "title": "Bad", "support": {}}
    )
    assert response.status_code == 422, response.text
