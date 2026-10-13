"""An uploaded pack follows the ordinary preview/apply path with workspace authority."""

from __future__ import annotations

import uuid
from urllib.parse import urlencode

import pytest
from exulanica.world import TopologyContract, WorldStyleRepository
from exulanica.world.style_packs import load_context

from style_pack_upload_support import upload
from test_workspace_style_packs_api_postgres import ROOT, PacksApi
from test_workspace_style_packs_api_postgres import api as api
from world_support import registered_world

pytestmark = pytest.mark.postgres


@pytest.fixture
def worlds(api):
    world_id = "authored:pack-preview-test"
    for workspace in (api.owner, api.stranger):
        with api.database.session(workspace) as connection:
            registered_world(connection, workspace, world_id)
            WorldStyleRepository(connection, workspace, world_id=world_id).register_topology(
                TopologyContract("pack-preview-topology", (), world_id=world_id)
            )
    return world_id


def _path(path, world_id):
    return f"{path}?{urlencode({'world_id': world_id})}"


def _preview(api, world_id, pack, *, who="owner"):
    current = api.get(_path("/world/styles/current", world_id), who).json()
    body = {
        "proposal_id": str(uuid.uuid4()),
        "origin": "settings",
        "origin_reference": "appearance-panel",
        "scope": {"kind": "global"},
        "base_style_version_id": current["current"]["version_id"],
        "base_topology_digest": current["current_topology_digest"],
        "profile": {
            "profile_id": "origin-landscape",
            "profile_version": 1,
            "parameters": {"vitality": 0.25},
        },
        "style_pack": pack,
    }
    return api.client.post(
        _path("/world/styles/previews", world_id), headers=api.headers(who), json=body
    ), body


def _apply(api, world_id, preview_id, body):
    return api.client.post(
        _path(f"/world/styles/previews/{preview_id}/apply", world_id),
        headers=api.headers(),
        json={key: body[key] for key in ("base_style_version_id", "base_topology_digest")},
    )


def _pack(api, *, ready=True):
    made = upload()
    made.manifest["look_family_catalog"] = {
        "version": 2,
        "sha256": load_context(ROOT).family_catalogs[2].sha256,
    }
    admitted = api.send(made)
    assert admitted.status_code == 201, admitted.text
    if ready:
        checked = api.check()
        assert (checked.ready, checked.errors) == (1, []), checked
    return {
        "pack_id": made.manifest["pack_id"],
        "version": made.manifest["version"],
        "manifest_sha256": admitted.json()["manifest_sha256"],
    }


def test_standalone_workspace_pack_previews_applies_and_reopens_with_its_setting(
    api: PacksApi, worlds
):
    pack = _pack(api)
    preview, body = _preview(api, worlds, {**pack, "setting_parts": {"sky": "overcast"}})
    assert preview.status_code == 201, preview.text
    candidate = preview.json()["candidate"]["style_pack"]
    assert {key: candidate[key] for key in pack} == pack
    assert candidate["source"] == "workspace"
    assert candidate.get("base") is None
    assert candidate["wearable"] is True
    assert candidate["setting"]["parts"] == [{"axis": "sky", "key": "overcast"}]
    applied = _apply(api, worlds, preview.json()["preview_id"], body)
    assert applied.status_code == 200, applied.text
    assert applied.json()["style_pack"] == candidate
    current = api.get(_path("/world/styles/current", worlds)).json()
    assert current["current"]["style_pack"] == candidate
    assert current["current_topology_digest"] == body["base_topology_digest"]


def test_unready_wrong_and_other_workspace_identities_are_not_appearance_choices(
    api: PacksApi, worlds
):
    pack = _pack(api, ready=False)
    pending, _ = _preview(api, worlds, pack)
    assert (pending.status_code, pending.json()["code"]) == (422, "invalid_style_data")
    checked = api.check()
    assert (checked.ready, checked.errors) == (1, []), checked
    for change in ({"pack_id": "maker.other"}, {"version": 2}, {"manifest_sha256": "0" * 64}):
        wrong, _ = _preview(api, worlds, {**pack, **change})
        assert (wrong.status_code, wrong.json()["code"]) == (422, "invalid_style_data")
    foreign, _ = _preview(api, worlds, pack, who="stranger")
    missing, _ = _preview(api, worlds, {**pack, "manifest_sha256": "0" * 64}, who="stranger")
    assert foreign.status_code == missing.status_code == 422
    assert foreign.json()["code"] == missing.json()["code"] == "invalid_style_data"
    assert (
        foreign.json()["detail"].replace(pack["manifest_sha256"], "0" * 64)
        == missing.json()["detail"]
    )
    assert api.get(_path("/world/styles/current", worlds)).json()["current"]["style_pack"] is None


def test_apply_rechecks_a_pack_withdrawn_after_preview(api: PacksApi, worlds):
    pack = _pack(api)
    preview, body = _preview(api, worlds, pack)
    assert preview.status_code == 201, preview.text
    withdrawal = api.client.post(
        f"/workspace-style-packs/{pack['manifest_sha256']}/withdraw", headers=api.headers()
    )
    assert withdrawal.status_code == 200, withdrawal.text
    applied = _apply(api, worlds, preview.json()["preview_id"], body)
    assert (applied.status_code, applied.json()["code"]) == (422, "invalid_style_data"), (
        applied.text
    )
    assert api.get(_path("/world/styles/current", worlds)).json()["current"]["style_pack"] is None
