"""Dressed terrain follows ordinary saved-world creation and exact cold replay."""

from __future__ import annotations

import copy
import uuid

import pytest
from exulanica.world.composers.site_plan import receipt_terrain
from exulanica.world.generated_worlds import generation_receipt
from exulanica.world.kinds.worker import close_kind_worker
from exulanica.world.terrain_authoring import TerrainAuthoringRefused, read_terrain_authoring

from test_purge import purged as purged
from test_restore_replay_search_entries import commands as commands
from test_terrain_dressing_authority_postgres import dressed as dressed
from test_terrain_dressing_authority_postgres import imported_made as imported_made

pytestmark = pytest.mark.postgres


def test_saved_dressed_terrain_reopens_and_cold_replays_exact_source(dressed):
    api = dressed.api
    response = dressed.create()
    assert response.status_code == 201, response.text
    entry = response.json()
    assert entry["generated_site"] is None
    assert entry["generated_terrain"]["contact_sha256"] == dressed.document["contact_sha256"]
    assert "dressing_sha256" not in entry["generated_terrain"]
    drawing_path, proof_path = dressed.paths(entry)
    first = api.get(drawing_path)
    assert first.status_code == 200, first.text
    drawing = first.json()
    assert drawing["profile"] == "exulanica.site-drawing/v4"
    assert drawing["terrain"]["dressing"] == dressed.document["dressing"]
    assert drawing["terrain"]["contact"] == dressed.document["contact"]
    assert drawing["composer"] == {"key": "site-plan", "version": 4}
    assert "slots" not in drawing
    proof = api.get(proof_path)
    assert proof.status_code == 200, proof.text
    assert proof.headers["Cache-Control"] == "private, no-store"
    assert proof.json()["profile"] == "exulanica.terrain-source-proof/v2"
    assert proof.json()["status"] == "verified"
    assert proof.json()["dressing_sha256"] == dressed.document["dressing_sha256"]
    assert proof.json()["receipt_sha256"] == drawing["receipt_sha256"]
    close_kind_worker()
    assert api.get(drawing_path).json() == drawing
    assert api.get(proof_path).json() == proof.json()
    reopened = api.get(f"/world-entries/{entry['entry_id']}")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["generated_terrain"] == entry["generated_terrain"]
    with api.database.session(api.repository.workspace_id) as connection:
        digest, receipt = generation_receipt(
            connection,
            api.repository.workspace_id,
            entry["world_id"],
            uuid.UUID(entry["source_snapshot_id"]),
        )
    assert digest == drawing["receipt_sha256"]
    assert receipt_terrain(receipt).document() == dressed.document
    for path in (drawing_path, proof_path):
        hidden = api.get(path.replace(entry["world_id"], "world:generated:invented"))
        assert hidden.status_code == 404, hidden.text


def test_incomplete_contact_or_legacy_profile_cannot_publish_dressing(dressed):
    api = dressed.api
    before = api.get("/world-entries").json()
    original = copy.deepcopy(dressed.document)
    doc = dressed.document
    doc["profile"] = "exulanica.terrain-authoring/v1"
    with pytest.raises(TerrainAuthoringRefused):
        read_terrain_authoring(doc)
    refused = dressed.create()
    assert refused.status_code == 422, refused.text
    doc.clear()
    doc.update(original)
    from exulanica.canonical import sha256_of_canonical

    doc["contact"]["obstructions"] = []
    doc["contact_sha256"] = sha256_of_canonical(doc["contact"]).hex()
    refused = dressed.create()
    assert refused.status_code == 422, refused.text
    assert api.get("/world-entries").json() == before


def test_dressed_reads_are_authorized_and_world_removal_evicts_cached_sources(dressed):
    import dataclasses
    import json

    from exulanica.api.authorisation import load_token_directory

    from personal_world_support import OWNER_TOKEN, STRANGER_TOKEN

    api = dressed.api
    created = dressed.create()
    assert created.status_code == 201, created.text
    entry = created.json()
    paths = dressed.paths(entry)
    for path in paths:
        assert api.get(path).status_code == 200
        assert api.get(path, token=STRANGER_TOKEN).status_code == 404
    services = api.client.app.state.services
    token = "dressed-terrain-reader-token-with-sufficient-entropy"
    api.client.app.state.services = dataclasses.replace(
        services,
        tokens=load_token_directory(
            {
                "EXULANICA_API_TOKENS": json.dumps(
                    {
                        token: {
                            "workspace_id": str(api.repository.workspace_id),
                            "actor": str(api.actor),
                            "permissions": ["world.read"],
                        }
                    }
                )
            }
        ),
    )
    try:
        for path in paths:
            result = api.get(path, token=token)
            assert result.status_code == 200, result.text
        assert (
            api.post(
                "/worlds/generated/terrain",
                {
                    "title": "No reader creation",
                    "authoring": dressed.document,
                },
                token=token,
            ).status_code
            == 403
        )
    finally:
        api.client.app.state.services = services
    removed = api.client.delete(
        f"/worlds/{entry['world_id']}", headers={"Authorization": f"Bearer {OWNER_TOKEN}"}
    )
    assert removed.status_code == 204, removed.text
    for path in paths:
        assert api.get(path).status_code in (404, 410)
    close_kind_worker()
    for path in paths:
        assert api.get(path).status_code in (404, 410)
    with api.database.session(api.repository.workspace_id) as connection:
        assert (
            connection.execute(
                "select 1 from world_generation_receipt where workspace_id=%s and world_id=%s",
                (api.repository.workspace_id, entry["world_id"]),
            ).fetchone()
            is None
        )


def test_real_restore_does_not_revive_removed_dressed_source(dressed, purged, commands, tmp_path):
    from exulanica.deletion.restore import verify_restore
    from exulanica.world.saved_entries import SavedWorldEntryRepository
    from exulanica.world.world_erasure import erase_world
    from exulanica.world.worlds import WorldRemoved, require_world

    from static_glb_builder import cube
    from test_restore_replay import _app, _backup, _restore
    from test_restore_replay_search_entries import _seal
    from test_restore_replay_withdrawals import _replay
    from test_reviewed_asset_import import imported_fixture

    # Registry rows share this private schema; retain their exact component bytes in the
    # restore fixture's own store, so its backup contains the actual admitted source.
    _, payload, licence = imported_fixture(cube().build())
    purged.store.put_bytes(payload)
    purged.store.put_bytes(licence)
    app, _ = _app(purged, None)
    [session] = app.state.services.tokens.sessions.values()
    workspace, actor = session.workspace_id, session.actor
    with purged.database().session(workspace) as connection:
        entry = SavedWorldEntryRepository(connection, workspace, purged.store).create_from_terrain(
            title="Restorable dressed terrain",
            authoring=dressed.document,
            created_by=actor,
        )
    dump, blobs = _backup(purged, tmp_path)
    with purged.database().session(workspace) as connection:
        erase_world(connection, workspace, entry.world_id, erased_by=actor)
    source, marker = _seal(tmp_path)
    assert entry.title not in source.read_text()
    _restore(purged, dump, blobs)
    with purged.database().session(workspace) as connection:
        _, restored = generation_receipt(
            connection, workspace, entry.world_id, entry.source_snapshot_id
        )
        assert restored["composer"] == {"key": "site-plan", "version": 4}
        assert restored["authoring"] == dressed.document
    _replay(source, marker)
    verify_restore(purged.database(), marker)
    close_kind_worker()
    with purged.database().session(workspace) as connection:
        assert (
            connection.execute(
                "select 1 from world_generation_receipt where workspace_id=%s and world_id=%s",
                (workspace, entry.world_id),
            ).fetchone()
            is None
        )
        with pytest.raises(WorldRemoved):
            require_world(connection, workspace, entry.world_id)
        with pytest.raises(WorldRemoved):
            SavedWorldEntryRepository(connection, workspace, purged.store).create_from_terrain(
                title="Late dressed terrain",
                authoring=dressed.document,
                created_by=actor,
                fixed_world_id=entry.world_id,
            )
