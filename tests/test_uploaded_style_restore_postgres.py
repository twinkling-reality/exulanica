"""A worn upload's revocation and workspace erasure survive actual backup/restore replay."""

from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from exulanica.deletion.restore import verify_restore
from exulanica.evidence.blob import BlobId
from exulanica.ingest.repository import IngestRepository
from exulanica.store.configured import local_content_stores
from exulanica.world import StylePackBinding, WorldStyleRepository
from exulanica.world.style_pack_admission import admit
from exulanica.world.style_pack_checks import StylePackCheckWorker, colour_table, library_palettes
from exulanica.world.style_packs import load_context
from exulanica.world.workspace_style_packs import WorkspaceStylePackRepository
from exulanica_pieces.budgets import read_budgets

from style_pack_upload_support import upload
from test_purge import _APP_PASSWORD, _APP_ROLE
from test_purge import purged as purged
from test_restore_replay import _backup, _restore
from test_restore_replay_search_entries import _seal
from test_restore_replay_search_entries import commands as commands
from test_restore_replay_withdrawals import _replay
from test_world_style_postgres import proposal, topology
from world_support import registered_world

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("erase_workspace", [False, True], ids=["withdrawal", "workspace-erasure"])
def test_a_worn_uploaded_pack_cannot_return_after_restore(
    purged, commands, tmp_path, erase_workspace
):
    runtime = purged.database(role=_APP_ROLE, password=_APP_PASSWORD)
    stores = local_content_stores(tmp_path).workspace_style_packs
    actor = uuid.uuid4()
    made = upload("maker.private-appearance")
    context = load_context(ROOT)
    made.manifest["look_family_catalog"] = {
        "version": 2,
        "sha256": context.family_catalogs[2].sha256,
    }
    budgets = read_budgets(ROOT)
    admitted = admit(
        made.declaration_bytes(),
        made.manifest_bytes,
        made.files,
        context=context,
        budgets=budgets.families,
        lod1_share_permille=budgets.lod1_share_permille,
        resolve_base=lambda _base: pytest.fail("the uploaded test pack is standalone"),
    )
    with runtime.session(purged.workspace_id) as connection:
        WorkspaceStylePackRepository(connection, purged.workspace_id, actor, stores=stores).record(
            admitted
        )
    prepared = StylePackCheckWorker(
        runtime,
        stores,
        frozenset({purged.workspace_id}),
        table=colour_table(ROOT),
        library=library_palettes,
    ).drain()
    assert (prepared.ready, prepared.errors) == (1, []), prepared
    world_id = "authored:uploaded-pack-restore"
    with runtime.session(purged.workspace_id) as connection:
        registered_world(connection, purged.workspace_id, world_id)
        styles = WorldStyleRepository(connection, purged.workspace_id, world_id=world_id)
        current = styles.register_topology(topology(world_id=world_id))
        binding = styles.requested_pack(
            StylePackBinding(admitted.pack_id, admitted.version, admitted.manifest_sha256)
        )
        preview = styles.preview(
            replace(proposal(current), style_pack_stated=True, style_pack=binding)
        )
        applied = styles.apply(
            preview.preview_id,
            base_style_version_id=current.version_id,
            base_topology_digest=current.topology_digest,
            applied_by=actor,
        )
        assert applied.style_pack.source == "workspace"
    dump, blobs = _backup(purged, tmp_path)

    def assert_source_state(*, erased, wearable):
        with runtime.session(purged.workspace_id) as connection:
            pack = connection.execute(
                "select pack_id, manifest_canonical, erased_at from workspace_style_pack_version "
                "where workspace_id=%s and manifest_sha256=%s",
                (purged.workspace_id, admitted.manifest_sha256),
            ).fetchone()
            for table in (
                "world_style_version",
                "world_style_preview",
                "world_style_proposal",
                "world_style_audit_event",
            ):
                count = connection.execute(
                    f"select count(*) as n from {table} where workspace_id=%s and world_id=%s",
                    (purged.workspace_id, world_id),
                ).fetchone()["n"]
                assert (count == 0) is erased, (table, count)
            if erased:
                assert pack["pack_id"] != admitted.pack_id
                assert pack["manifest_canonical"] is None and pack["erased_at"] is not None
            else:
                assert bytes(pack["manifest_canonical"]) == admitted.manifest_canonical
                read = WorldStyleRepository(
                    connection, purged.workspace_id, world_id=world_id
                ).current()
                assert read.style_pack.manifest_sha256 == admitted.manifest_sha256
                assert read.style_pack.wearable is wearable

    with runtime.session(purged.workspace_id) as connection:
        if erase_workspace:
            IngestRepository(connection, purged.workspace_id).insert_tombstone(
                scope="workspace", requested_by=actor, reason="erase uploaded appearance and world"
            )
        else:
            assert WorkspaceStylePackRepository(
                connection, purged.workspace_id, actor, stores=stores
            ).withdraw(admitted.manifest_sha256)
    assert_source_state(erased=erase_workspace, wearable=False)
    source, marker = _seal(tmp_path)
    _restore(purged, dump, blobs)
    assert_source_state(erased=False, wearable=True)
    _replay(source, marker)
    verify_restore(purged.database(), marker)
    assert_source_state(erased=erase_workspace, wearable=False)
    if erase_workspace:
        assert all(
            not stores.for_workspace(purged.workspace_id).exists(
                BlobId.from_hex(file.content_sha256)
            )
            for file in admitted.files
        )
