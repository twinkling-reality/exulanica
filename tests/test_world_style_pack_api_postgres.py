"""A world's style pack over HTTP: named in a preview, applied, read back, and refused by name.

The pack is read from the committed manifest file (its canonical JSON and one newline), not from
the library the server loads.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest

from test_world_api import world_api as world_api

pytestmark = pytest.mark.postgres

PACKS = Path(__file__).resolve().parents[1] / "assets" / "style-packs" / "packs"


def committed(pack_id: str) -> dict[str, object]:
    text = (PACKS / pack_id / "manifest.json").read_bytes()
    return {
        "pack_id": pack_id,
        "version": json.loads(text)["version"],
        "manifest_sha256": hashlib.sha256(text[:-1]).hexdigest(),
    }


def test_a_pack_named_in_camel_case_is_previewed_applied_and_read_back(world_api):
    cozy = committed("exulanica.cozy-town")
    body = world_api.preview_body()
    body["stylePack"] = {
        "packId": cozy["pack_id"],
        "version": cozy["version"],
        "manifestSha256": cozy["manifest_sha256"],
    }
    preview = world_api.post("/world/styles/previews", body)
    assert preview.status_code == 201, preview.text
    assert preview.json()["candidate"]["style_pack"] == cozy
    proposal = world_api.get(f"/world/styles/proposals/{body['proposal_id']}").json()
    assert (proposal["style_pack_stated"], proposal["style_pack"]) == (True, cozy)
    applied = world_api.post(
        f"/world/styles/previews/{preview.json()['preview_id']}/apply",
        {
            "base_style_version_id": body["base_style_version_id"],
            "base_topology_digest": body["base_topology_digest"],
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["style_pack"] == cozy
    assert world_api.current()["current"]["style_pack"] == cozy
    assert [
        version["style_pack"] for version in world_api.get("/world/styles/versions").json()
    ] == [
        None,
        cozy,
    ]
    # A proposal that names no pack keeps it, and says it named none.
    kept = world_api.post("/world/styles/previews", world_api.preview_body())
    assert kept.json()["candidate"]["style_pack"] == cozy
    read = world_api.get(f"/world/styles/proposals/{kept.json()['proposal_id']}").json()
    assert (read["style_pack_stated"], read["style_pack"]) == (False, None)
    # One that names none, in snake case, clears it.
    cleared = world_api.post("/world/styles/previews", world_api.preview_body(style_pack=None))
    assert cleared.status_code == 201, cleared.text
    assert cleared.json()["candidate"]["style_pack"] is None


@pytest.mark.parametrize(
    ("change", "status", "code"),
    [
        ({"pack_id": "exulanica.nowhere-town"}, 422, "invalid_style_data"),
        # A version the library does not hold: the committed one's next.
        ({"version": committed("exulanica.cozy-town")["version"] + 1}, 422, "invalid_style_data"),
        ({"manifest_sha256": "0" * 64}, 422, "invalid_style_data"),
        # Malformed before any lookup: the body's own shape refuses it.
        ({"manifest_sha256": "not-a-digest"}, 422, None),
        ({"pack_id": "Cozy Town"}, 422, None),
    ],
)
def test_a_pack_the_host_does_not_hold_is_refused_by_name(world_api, change, status, code):
    asked = {**committed("exulanica.cozy-town"), **change}
    body = world_api.preview_body(style_pack=asked)
    response = world_api.post("/world/styles/previews", body)
    assert response.status_code == status, response.text
    if code is not None:
        assert response.json()["code"] == code
        assert asked["pack_id"] in response.json()["detail"]
    assert world_api.current()["current"]["style_pack"] is None


def test_a_regional_proposal_naming_a_pack_is_refused(world_api):
    body = world_api.preview_body(
        scope={"kind": "region", "region_id": "region-a"},
        style_pack=committed("exulanica.toon-town"),
        proposal_id=str(uuid.uuid4()),
    )
    response = world_api.post("/world/styles/previews", body)
    assert response.status_code == 422, response.text
    assert "a regional proposal names none" in response.json()["detail"]
