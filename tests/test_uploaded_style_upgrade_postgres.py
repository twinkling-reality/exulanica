"""0202 admits a checked upload without rewriting populated appearance history."""

from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest
from exulanica.migrations import migrations
from exulanica.store.configured import local_content_stores
from exulanica.world import StylePackBinding, WorldStyleRepository
from exulanica.world.style_pack_admission import admit
from exulanica.world.style_packs import load_context
from exulanica.world.workspace_style_packs import WorkspaceStylePackRepository
from exulanica_pieces.budgets import read_budgets
from psycopg.rows import dict_row

import pg_harness
from style_pack_upload_support import upload
from test_world_style_postgres import proposal, topology
from world_support import registered_world

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[1]


def test_upgrade_preserves_rows_and_replaces_only_the_uploaded_origin_gate(monkeypatch, tmp_path):
    every = list(migrations())
    [upgrade] = [item for item in every if item.version == "0202"]
    monkeypatch.setattr(
        pg_harness, "migrations", lambda: iter(m for m in every if m.version < "0202")
    )
    with pg_harness.migrated_schema() as (_, connection):
        connection.autocommit = True
        connection.row_factory = dict_row
        workspace, actor = uuid.uuid4(), uuid.uuid4()
        connection.execute(
            "select set_config('exulanica.workspace_id', %s, false)", (str(workspace),)
        )
        stores = local_content_stores(tmp_path).workspace_style_packs
        made = upload()
        budgets = read_budgets(ROOT)
        pack = admit(
            made.declaration_bytes(),
            made.manifest_bytes,
            made.files,
            context=load_context(ROOT),
            budgets=budgets.families,
            lod1_share_permille=budgets.lod1_share_permille,
            resolve_base=lambda _base: pytest.fail("this pack has no base"),
        )
        packs = WorkspaceStylePackRepository(connection, workspace, actor, stores=stores)
        packs.record(pack)
        claimed = packs.claim("migration-test", 60)
        assert claimed is not None
        packs.finish_ready(pack.manifest_sha256, claimed[1], {"migration_fixture": True})
        world_id = registered_world(connection, workspace)
        styles = WorldStyleRepository(connection, workspace, world_id=world_id)
        initial = styles.register_topology(topology(world_id=world_id))
        binding = styles.requested_pack(
            StylePackBinding(pack.pack_id, pack.version, pack.manifest_sha256)
        )
        preview = styles.preview(
            replace(proposal(initial), style_pack_stated=True, style_pack=binding)
        )

        def apply():
            return styles.apply(
                preview.preview_id,
                base_style_version_id=initial.version_id,
                base_topology_digest=initial.topology_digest,
                applied_by=actor,
            )

        with pytest.raises(psycopg.errors.CheckViolation, match="own_pack_not_wearable"):
            apply()

        def rows():
            return {
                table: connection.execute(
                    f"select to_jsonb(x) as row from {table} x order by to_jsonb(x)::text"
                ).fetchall()
                for table in (
                    "world_style_version",
                    "world_style_proposal",
                    "world_style_preview",
                    "workspace_style_pack_version",
                )
            }

        before = rows()
        connection.execute(upgrade.sql)
        assert rows() == before
        applied = apply()
        assert applied.style_pack.source == "workspace"
        assert applied.style_pack.manifest_sha256 == pack.manifest_sha256
        assert (
            next(
                row for row in styles.versions() if row.version_id == initial.version_id
            ).style_pack
            is None
        )
