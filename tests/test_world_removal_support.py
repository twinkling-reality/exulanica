"""Saved multilevel support is erased with its world, including across an older restore."""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.world.composers import site_plan
from exulanica.world.errors import WorldRemoved
from exulanica.world.generated_worlds import generation_receipt
from exulanica.world.kinds.document import read_kind
from exulanica.world.kinds.repository import WorkspaceKinds
from exulanica.world.kinds.samples import check_samples
from exulanica.world.kinds.worker import WorkerComposer, close_kind_worker, kind_worker
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.support_surfaces import read_support_network
from exulanica.world.worlds import require_world
from fastapi.testclient import TestClient

from test_purge import purged as purged
from test_restore_replay import _app, _backup, _restore
from test_restore_replay_search_entries import _seal
from test_restore_replay_search_entries import commands as commands
from test_restore_replay_withdrawals import _replay
from test_support_site import authoring
from test_world_kinds_postgres import _uploaded

pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def _end_worker():
    yield
    close_kind_worker()


@pytest.mark.parametrize("keep_library_kind", [False, True], ids=["receipt-only", "kept-library"])
def test_removal_and_real_restore_erase_saved_support_and_caches_keep_library(
    purged, commands, tmp_path, keep_library_kind
):
    app, headers = _app(purged, None)
    [session] = app.state.services.tokens.sessions.values()
    workspace, actor = session.workspace_id, session.actor
    kind = read_kind(_uploaded("farm"))
    values = kind.values("small_farm")
    worker = kind_worker()

    def make(title):
        world = f"world:generated:{uuid.uuid4()}"
        baseline = site_plan.compose_kind(kind, values, world, place_id="place:removal-base")
        composer = WorkerComposer(workspace, support=authoring(baseline.place))
        with purged.database().session(workspace) as connection:
            entry = SavedWorldEntryRepository(connection, workspace, purged.store).create_from_kind(
                title=title,
                kind=kind,
                values=values,
                created_by=actor,
                fixed_world_id=world,
                compose=composer,
            )
        composer.keep()
        assert composer.drawn and composer.placed
        assert worker.drawings.get(composer.drawn[0]) is not None
        assert worker.places.get(composer.placed[0]) is not None
        return entry, composer

    with purged.database().session(workspace) as connection:
        if keep_library_kind:
            WorkspaceKinds(connection, workspace).append(
                kind, check_samples(kind), created_by=actor
            )
        library_before = connection.execute(
            "select to_jsonb(k) as row from world_kind_version k where workspace_id=%s",
            (workspace,),
        ).fetchall()
    assert bool(library_before) is keep_library_kind
    entry, composer = make("A supported world to remove")
    kept, kept_composer = make("Another supported world stays")
    with purged.database().session(workspace) as connection:
        digest, receipt = generation_receipt(
            connection, workspace, entry.world_id, entry.source_snapshot_id
        )
        assert receipt["composer"]["version"] == 2
        records = site_plan.records(receipt)
        reopened = site_plan.society_place("place:removal-proof", receipt, records)
        assert {n["support_z_mm"] for n in reopened["nodes"]} == {0, 150}
    drawing = json.loads(worker.drawings.get(composer.drawn[0])["body"])
    assert drawing["profile"] == "exulanica.site-drawing/v2"
    network = read_support_network(drawing["support"]["network"])
    assert network.document()["source"]["world_id"] == entry.world_id
    assert network.document()["surfaces"]
    dump, blobs = _backup(purged, tmp_path)
    site_path = f"/world/versions/{entry.authored_version_id}/site?world_id={entry.world_id}"

    def erased():
        with purged.database().session(workspace) as connection:
            for table in (
                "world_generation_receipt",
                "world_alternate_version",
                "saved_world_entry",
            ):
                assert not connection.execute(
                    f"select 1 from {table} where workspace_id=%s and world_id=%s",
                    (workspace, entry.world_id),
                ).fetchone()
            for table in (
                "world_structure_snapshot",
                "world_structure_snapshot_element",
                "world_structure_snapshot_region",
            ):
                assert not connection.execute(
                    f"select 1 from {table} where workspace_id=%s and snapshot_id=%s",
                    (workspace, entry.source_snapshot_id),
                ).fetchone()
            assert (
                connection.execute(
                    "select to_jsonb(k) as row from world_kind_version k where workspace_id=%s",
                    (workspace,),
                ).fetchall()
                == library_before
            )
            erasure = connection.execute(
                "select to_jsonb(e) as row from world_erasure e "
                "where workspace_id=%s and world_id=%s",
                (workspace, entry.world_id),
            ).fetchone()["row"]
            for content in (entry.title, digest, "support", "network:authored", network.sha256):
                assert content not in json.dumps(erasure)
            with pytest.raises(WorldRemoved):
                require_world(connection, workspace, entry.world_id)
            # The surviving world's durable support and source remain exactly readable.
            _, other = generation_receipt(
                connection, workspace, kept.world_id, kept.source_snapshot_id
            )
            assert other["composer"]["version"] == 2
            assert site_plan.records(other)

    with TestClient(app) as client:
        response = client.get(site_path, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json() == drawing
        response = client.delete(f"/worlds/{entry.world_id}", headers=headers)
        assert response.status_code == 204, response.text
        assert client.get(site_path, headers=headers).status_code == 410
        assert worker.drawings.get(composer.drawn[0]) is None
        assert worker.places.get(composer.placed[0]) is None
        # Even a composition retained by a caller cannot republish its pre-erasure generation.
        composer.keep()
        assert worker.drawings.get(composer.drawn[0]) is None
        assert worker.places.get(composer.placed[0]) is None
        assert worker.drawings.get(kept_composer.drawn[0]) is not None
        assert worker.places.get(kept_composer.placed[0]) is not None
        erased()
    source, marker = _seal(tmp_path)
    for content in (entry.title, digest, network.sha256, "network:authored"):
        assert content not in source.read_text()
    _restore(purged, dump, blobs)
    with purged.database().session(workspace) as connection:
        # Actual older backup contains the support again before the product's withdrawal replay.
        _, restored = generation_receipt(
            connection, workspace, entry.world_id, entry.source_snapshot_id
        )
        assert dict(restored) == dict(receipt)
    _replay(source, marker)
    erased()
    restored_app, restored_headers = _app(purged, marker)
    with TestClient(restored_app) as client:
        assert client.get(site_path, headers=restored_headers).status_code == 410
