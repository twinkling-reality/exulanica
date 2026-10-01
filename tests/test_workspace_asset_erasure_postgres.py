"""A workspace tombstone erases its own admitted assets and prepared outputs (migration 0126).

Withdrawal hides an admission and destroys nothing (``tests/test_workspace_assets_postgres.py``);
erasing the workspace destroys every object in its asset namespace through the one purge
machinery, as the purge role, and the tombstone is complete only once they are gone. The
``purged`` fixture supplies a workspace, the purge role and the runtime role.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from pathlib import Path

import pytest
from exulanica.deletion import queue
from exulanica.deletion.worker import PurgeWorker
from exulanica.evidence.blob import BlobId
from exulanica.store.namespaces import LocalWorkspaceStores
from exulanica.world.asset_preparation import AssetPreparationWorker
from exulanica.world.workspace_assets import WorkspaceAssetRepository

from static_glb_builder import cube, png
from test_purge import _PURGE_PASSWORD, _PURGE_ROLE
from test_purge import purged as purged
from workspace_asset_support import declaration

pytestmark = pytest.mark.postgres


class Assets:
    """Admissions, preparations and the purge over the ``purged`` fixture's workspace."""

    def __init__(self, purged, tmp_path: Path) -> None:
        self.purged = purged
        self.workspace_id = purged.workspace_id
        self.stores = LocalWorkspaceStores(tmp_path / "workspace-assets")
        self.actor = uuid.uuid4()
        self.owner = purged.database()
        self._sessions = contextlib.ExitStack()
        self.connection = self._sessions.enter_context(self.owner.session(self.workspace_id))

    def close(self) -> None:
        self._sessions.close()

    def rows(self, sql: str, *params):
        return self.connection.execute(sql, params).fetchall()

    def admitted(self, payload: bytes, *, prepare: bool) -> list[str]:
        """Admit ``payload`` and, when asked, prepare it; the namespace objects it recorded."""
        WorkspaceAssetRepository(
            self.connection, self.workspace_id, self.actor, stores=self.stores
        ).admit(json.dumps(declaration(payload)).encode(), payload)
        if prepare:
            outcome = AssetPreparationWorker(
                self.owner, self.stores, frozenset({self.workspace_id})
            ).drain()
            assert (outcome.prepared, outcome.errors) == (1, []), outcome
        return [
            row["content_sha256"]
            for row in self.rows("select content_sha256 from workspace_asset_blob")
        ]

    def in_namespace(self, digest: str) -> bool:
        return self.stores.for_workspace(self.workspace_id).exists(BlobId.from_hex(digest))

    def purge_worker(self, *, with_namespaces: bool = True) -> PurgeWorker:
        return PurgeWorker(
            self.purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD),
            self.purged.store,
            frozenset({self.workspace_id}),
            name="test-workspace-asset-purge",
            workspace_asset_stores=self.stores if with_namespaces else None,
        )

    def erase_workspace(self) -> uuid.UUID:
        return self.purged.repository.insert_tombstone(
            scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
        )


@pytest.fixture
def assets(purged, tmp_path):
    made = Assets(purged, tmp_path)
    yield made
    made.close()


def test_a_workspace_tombstone_destroys_every_asset_object_and_completion_waits_for_it(assets):
    assets.admitted(cube().build(), prepare=True)
    objects = assets.admitted(cube(texture=png(4, 4)).build(), prepare=False)
    assert len(objects) == 3  # one input and its output, and one input waiting
    tombstone = assets.erase_workspace()

    jobs = assets.rows(
        "select target_ref from purge_job where tombstone_id = %s "
        "and target_kind = 'workspace_asset' order by target_ref",
        tombstone,
    )
    assert [job["target_ref"] for job in jobs] == sorted(objects)
    states = {
        (row["state"], row["failure_class"])
        for row in assets.rows("select state, failure_class from workspace_preparation")
    }
    assert states == {("prepared", None), ("cancelled", "deleted")}
    assert not queue.is_purge_complete(assets.connection, tombstone)

    outcome = assets.purge_worker().drain()
    assert outcome.failed == 0 and outcome.blocked is None, outcome
    # The tombstone erases the fixture's photograph too; these are the asset namespace's jobs.
    done = assets.rows(
        "select state from purge_job where tombstone_id = %s and target_kind = 'workspace_asset'",
        tombstone,
    )
    assert [row["state"] for row in done] == ["done", "done", "done"]
    assert not any(assets.in_namespace(digest) for digest in objects)
    assert all(
        row["purged_at"] is not None
        for row in assets.rows("select purged_at from workspace_asset_blob")
    )
    assert queue.is_purge_complete(assets.connection, tombstone)
    assert tombstone in outcome.completed_tombstones


def test_a_worker_without_the_asset_namespaces_leaves_the_tombstone_open(assets):
    objects = assets.admitted(cube().build(), prepare=True)
    tombstone = assets.erase_workspace()
    assets.purge_worker(with_namespaces=False).drain()
    assert all(assets.in_namespace(digest) for digest in objects)
    assert not queue.is_purge_complete(assets.connection, tombstone)
    assets.purge_worker().drain()
    assert queue.is_purge_complete(assets.connection, tombstone)


def test_only_a_workspace_tombstone_may_destroy_the_namespace(assets):
    objects = assets.admitted(cube().build(), prepare=True)
    capture_id = assets.purged.rows("select capture_id from capture")[0]["capture_id"]
    capture_tombstone = assets.purged.tombstone_the_capture(capture_id)
    assert not assets.rows(
        "select workspace_asset_purge_is_authorized(%s, %s, %s) as allowed",
        assets.workspace_id,
        capture_tombstone,
        objects[0],
    )[0]["allowed"]
    # A capture tombstone queues nothing here, and a forged job under it is never claimed.
    assert not assets.rows(
        "select 1 from purge_job where target_kind = 'workspace_asset' and tombstone_id = %s",
        capture_tombstone,
    )
    assets.connection.execute(
        "insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref) "
        "values (%s, %s, 'workspace_asset', %s)",
        (capture_tombstone, assets.workspace_id, objects[0]),
    )
    assets.purge_worker().drain()
    assert all(assets.in_namespace(digest) for digest in objects)
    # Nor is the question answered for a workspace the session is not in.
    with assets.owner.session(uuid.uuid4()) as foreign:
        assert not foreign.execute(
            "select workspace_asset_purge_is_authorized(%s, %s, %s) as allowed",
            (assets.workspace_id, capture_tombstone, objects[0]),
        ).fetchone()["allowed"]


def test_the_purge_role_holds_exactly_the_asset_privileges_it_needs(assets):
    columns = assets.rows(
        "select privilege_type, column_name from information_schema.column_privileges "
        "where grantee = %s and table_schema = current_schema() "
        "  and table_name = 'workspace_asset_blob' "
        "order by privilege_type, column_name",
        _PURGE_ROLE,
    )
    assert [(row["privilege_type"], row["column_name"]) for row in columns] == [
        ("SELECT", "content_sha256"),
        ("SELECT", "purged_at"),
        ("SELECT", "workspace_id"),
        ("UPDATE", "purged_at"),
    ]
    tables = assets.rows(
        "select table_name, privilege_type from information_schema.table_privileges "
        "where grantee = %s and table_schema = current_schema() "
        "  and table_name like 'workspace%%'",
        _PURGE_ROLE,
    )
    assert tables == []
    signature = "workspace_asset_purge_is_authorized(uuid,uuid,text)"
    assert assets.rows(
        "select has_function_privilege(%s, %s, 'execute') as allowed", _PURGE_ROLE, signature
    )[0]["allowed"]
    assert not assets.rows(
        "select has_function_privilege('public', %s, 'execute') as allowed", signature
    )[0]["allowed"]
