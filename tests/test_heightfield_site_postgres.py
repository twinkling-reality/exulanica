"""Terrain creation uses normal saved-source authority, reopening and cold replay."""

from __future__ import annotations

import uuid

import pytest
from exulanica.world.composers import site_plan
from exulanica.world.generated_worlds import generation_receipt
from exulanica.world.kinds.worker import close_kind_worker, place_job

from test_heightfield_authoring import authoring
from test_purge import purged as purged
from test_restore_replay_search_entries import commands as commands
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


def test_terrain_normal_api_saves_reopens_and_cold_replays(made):
    response = made.post(
        "/worlds/generated/terrain", {"title": "Exact terrain", "authoring": authoring()}
    )
    assert response.status_code == 201, response.text
    entry = response.json()
    path = f"/world/versions/{entry['authored_version_id']}/site?world_id={entry['world_id']}"
    first = made.get(path)
    assert first.status_code == 200, first.text
    drawing = first.json()
    assert drawing["profile"] == "exulanica.site-drawing/v3"
    assert drawing["arrival"]["position_mm"] == [1001, 1333, -1000]
    assert drawing["terrain"]["geometry"] == authoring()["geometry"]
    assert drawing["capabilities"]["society_projection"] == "unavailable"
    assert "slots" not in drawing
    close_kind_worker()
    assert made.get(path).json() == drawing
    with made.database.session(made.repository.workspace_id) as connection:
        digest, receipt = generation_receipt(
            connection,
            made.repository.workspace_id,
            entry["world_id"],
            uuid.UUID(entry["source_snapshot_id"]),
        )
    assert receipt["composer"] == {"key": "site-plan", "version": 3}
    assert site_plan.records(receipt)[0].document() == authoring()
    unavailable = place_job(str(made.repository.workspace_id), dict(receipt), digest, "place:test")
    assert unavailable["code"] == "terrain_society_projection_unavailable"
    assert "place" not in unavailable
    # The same version cannot be reached by inventing a different world scope.
    hidden = made.get(
        f"/world/versions/{entry['authored_version_id']}/site?world_id=world:generated:invented"
    )
    assert hidden.status_code == 404, hidden.text


def test_rejected_entry_creates_no_saved_world(made):
    listing = made.get("/world-entries")
    assert listing.status_code == 200, listing.text
    before = listing.json()
    doc = authoring()
    doc["entry"]["position_mm"] = [0, 0]
    response = made.post(
        "/worlds/generated/terrain", {"title": "No unsafe entry", "authoring": doc}
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "terrain_authoring_invalid"
    assert made.get("/world-entries").json() == before


def test_database_terrain_receipt_constraint_is_closed(made):
    import copy

    import psycopg
    from exulanica.world.composers import receipt_sha256
    from psycopg.types.json import Jsonb

    response = made.post(
        "/worlds/generated/terrain", {"title": "Receipt constraint", "authoring": authoring()}
    )
    assert response.status_code == 201, response.text
    entry = response.json()
    workspace = made.repository.workspace_id
    with made.database.session(workspace) as connection:
        _, original = generation_receipt(
            connection, workspace, entry["world_id"], uuid.UUID(entry["source_snapshot_id"])
        )
        cases = []
        for field in original:
            invalid = copy.deepcopy(dict(original))
            del invalid[field]
            # A missing composer uses the old branch, which also refuses missing seed/kind.
            cases.append(invalid)
        for field in ("seed", "kind", "values", "tiles"):
            cases.append({**original, field: {}})
        for field, value in (
            ("profile", "unknown"),
            ("output_digest", "0" * 64),
            ("record_count", 2),
        ):
            cases.append({**original, field: value})
        for invalid in cases:
            with (
                pytest.raises(psycopg.errors.CheckViolation) as refused,
                connection.transaction(),
            ):
                connection.execute(
                    "insert into world_generation_receipt "
                    "(workspace_id,world_id,receipt_sha256,receipt,created_by) "
                    "values (%s,%s,%s,%s,%s)",
                    (
                        workspace,
                        entry["world_id"],
                        receipt_sha256(invalid),
                        Jsonb(invalid),
                        made.actor,
                    ),
                )
            assert refused.value.diag.constraint_name == (
                "world_generation_receipt_names_its_world"
                if "world_id" not in invalid
                else "world_generation_receipt_states_its_generation"
            )


def test_foreign_scope_and_removed_world_cannot_read_cached_terrain(made):
    from personal_world_support import OWNER_TOKEN, STRANGER_TOKEN

    response = made.post(
        "/worlds/generated/terrain", {"title": "Private terrain", "authoring": authoring()}
    )
    assert response.status_code == 201, response.text
    entry = response.json()
    assert entry["generated_site"] is None and entry["declared_floor"] is None
    assert entry["society_engine"] is None
    assert entry["generated_terrain"]["geometry_sha256"] == authoring()["geometry_sha256"]
    path = f"/world/versions/{entry['authored_version_id']}/site?world_id={entry['world_id']}"
    assert made.get(path).status_code == 200
    assert made.get(path, token=STRANGER_TOKEN).status_code == 404
    removed = made.client.delete(
        f"/worlds/{entry['world_id']}", headers={"Authorization": f"Bearer {OWNER_TOKEN}"}
    )
    assert removed.status_code == 204, removed.text
    assert made.get(path).status_code in (404, 410)
    close_kind_worker()
    assert made.get(path).status_code in (404, 410)
    with made.database.session(made.repository.workspace_id) as connection:
        assert not connection.execute(
            "select 1 from world_generation_receipt where workspace_id=%s and world_id=%s",
            (made.repository.workspace_id, entry["world_id"]),
        ).fetchall()


def test_creation_requires_world_write_permission(made):
    import dataclasses
    import json

    from exulanica.api.authorisation import load_token_directory

    token = "terrain-read-only-token-with-sufficient-entropy"
    services = made.client.app.state.services
    made.client.app.state.services = dataclasses.replace(
        services,
        tokens=load_token_directory(
            {
                "EXULANICA_API_TOKENS": json.dumps(
                    {
                        token: {
                            "workspace_id": str(made.repository.workspace_id),
                            "actor": str(made.actor),
                            "permissions": ["world.read"],
                        }
                    }
                )
            }
        ),
    )
    response = made.post(
        "/worlds/generated/terrain", {"title": "Forbidden", "authoring": authoring()}, token=token
    )
    assert response.status_code == 403, response.text


def test_real_restore_cannot_revive_removed_terrain_source(purged, commands, tmp_path):
    from exulanica.deletion.restore import verify_restore
    from exulanica.world.saved_entries import SavedWorldEntryRepository
    from exulanica.world.world_erasure import erase_world
    from exulanica.world.worlds import WorldRemoved, require_world

    from test_restore_replay import _app, _backup, _restore
    from test_restore_replay_search_entries import _seal
    from test_restore_replay_withdrawals import _replay

    app, _ = _app(purged, None)
    [session] = app.state.services.tokens.sessions.values()
    workspace, actor = session.workspace_id, session.actor
    with purged.database().session(workspace) as connection:
        entry = SavedWorldEntryRepository(connection, workspace, purged.store).create_from_terrain(
            title="Private terrain source", authoring=authoring(), created_by=actor
        )
        _, receipt = generation_receipt(
            connection, workspace, entry.world_id, entry.source_snapshot_id
        )
        assert site_plan.records(receipt)[0].document() == authoring()
    dump, blobs = _backup(purged, tmp_path)
    with purged.database().session(workspace) as connection:
        erase_world(connection, workspace, entry.world_id, erased_by=actor)
    source, marker = _seal(tmp_path)
    assert entry.title not in source.read_text()
    _restore(purged, dump, blobs)
    with purged.database().session(workspace) as connection:
        # Positive control: the backup contains the complete admitted geometry.
        _, restored = generation_receipt(
            connection, workspace, entry.world_id, entry.source_snapshot_id
        )
        assert restored["authoring"] == authoring()
    _replay(source, marker)
    verify_restore(purged.database(), marker)
    with purged.database().session(workspace) as connection:
        assert not connection.execute(
            "select 1 from world_generation_receipt where workspace_id=%s and world_id=%s",
            (workspace, entry.world_id),
        ).fetchall()
        assert not connection.execute(
            "select 1 from saved_world_entry where workspace_id=%s and world_id=%s",
            (workspace, entry.world_id),
        ).fetchall()
        with pytest.raises(WorldRemoved):
            require_world(connection, workspace, entry.world_id)
        with pytest.raises(WorldRemoved):
            SavedWorldEntryRepository(connection, workspace, purged.store).create_from_terrain(
                title="Late terrain source",
                authoring=authoring(),
                created_by=actor,
                fixed_world_id=entry.world_id,
            )
