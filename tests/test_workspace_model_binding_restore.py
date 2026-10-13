"""An actual pg_dump/psql restore retains source identity and replays later erasure."""

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from exulanica.deletion.restore import RestoreRefused, verify_restore
from exulanica.models.manifest import load_manifest
from exulanica.models.provider_catalog import ProviderPrice
from exulanica.orchestration.restore import main as restore_command
from exulanica.world.workspace_model_bindings import (
    BindingSnapshotRepository,
    priced_snapshot,
    proof,
    proven_bindings,
)

from test_purge import purged as purged
from test_restore_replay import _backup, _restore
from test_restore_replay_search_entries import _seal
from test_restore_replay_search_entries import commands as commands
from test_workspace_model_bindings import evidence

pytestmark = pytest.mark.postgres


def test_backup_retains_exact_snapshot_and_restore_replays_later_workspace_erasure(
    purged, commands, tmp_path
):
    state, found, receipts, outcome = evidence()
    binding = proof(
        state, found, receipts, outcome, engine=found["engine"], manifest=load_manifest()
    )
    _, document = priced_snapshot(
        load_manifest(),
        [binding],
        {
            state.model_id: ProviderPrice(
                state.model_id, Decimal(".2"), Decimal(".6"), 64000, "d" * 64
            )
        },
        read_at=dt.datetime.now(dt.UTC),
    )
    workspace = purged.workspace_id
    with purged.database().session(workspace) as connection:
        digest = BindingSnapshotRepository(connection, workspace).record(document)
        assert not proven_bindings(connection, workspace, found["engine"], load_manifest())
    dump, blobs = _backup(purged, tmp_path)
    with purged.database().session(workspace) as connection:
        connection.execute(
            "insert into tombstone(workspace_id,scope,requested_by,reason) "
            "values(%s,'workspace',%s,'workspace erased after backup')",
            (workspace, uuid.uuid4()),
        )
        assert BindingSnapshotRepository(connection, workspace).read(digest) is None
    source, marker = _seal(tmp_path)
    _restore(purged, dump, blobs)
    with purged.database().session(workspace) as connection:
        repository = BindingSnapshotRepository(connection, workspace)
        assert repository.read(digest) == document
        assert not proven_bindings(connection, workspace, found["engine"], load_manifest())
    with pytest.raises(RestoreRefused, match="pending"):
        verify_restore(purged.database(), marker)
    assert restore_command(["replay", "--checkpoint", str(source), "--marker", str(marker)]) == 0
    verify_restore(purged.database(), marker)
    with purged.database().session(workspace) as connection:
        assert BindingSnapshotRepository(connection, workspace).read(digest) is None
