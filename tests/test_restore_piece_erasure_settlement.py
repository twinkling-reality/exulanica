"""A real backup restore retains content-free generation recovery and exact measured spend."""

from __future__ import annotations

from decimal import Decimal

import psycopg
import pytest
from exulanica.generation import batches, entries

from spending_support import bench as bench
from test_piece_generation_worker_postgres import Played, _queued
from test_purge import purged as purged
from test_restore_replay import _backup, _restore
from test_restore_replay_search_entries import _seal
from test_restore_replay_search_entries import commands as commands
from test_restore_replay_withdrawals import _replay

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("progress_before_backup", [False, True])
def test_restore_carries_measured_erasure_decision_and_settles_once(
    purged, commands, repository, bench, tmp_path, progress_before_backup
):
    played = Played(repository, bench, tmp_path, "0.50")
    entry = _queued(played)
    workspace = played.workspace_id
    assert workspace == purged.workspace_id
    if not progress_before_backup:
        dump, blobs = _backup(purged, tmp_path)
    # The batch has a measured failure, but its spending settlement has not run yet.
    with bench.runtime.session(workspace) as connection:
        [batch] = batches.batches_in_flight(connection, workspace)
        batches.end_batch(
            connection,
            workspace,
            batch,
            state="refused",
            refusal="test_measured_failure",
            ended_at=played.now,
            settlements={
                r.piece_request_id: ("reported", Decimal("0.012345")) for r in batch.requests
            },
        )
    played.tombstone()
    [obligation] = played.rows("select * from piece_erasure_settlement")
    assert (obligation["basis"], obligation["usd"]) == ("reported", Decimal("0.012345"))
    assert played.rows("select 1 from piece_request") == []
    if progress_before_backup:
        # An older backup can already contain the obligation, while source progress comes later.
        dump, blobs = _backup(purged, tmp_path)
        entries.write_withdrawn(played.bucket, entry, played.now)
        with bench.runtime.session(workspace) as connection:
            batches.mark_erasure_withdrawn(connection, workspace, batch.piece_batch_id, played.now)
            batches.decide_cancelled(connection, workspace)
    source, marker = _seal(tmp_path)
    with (
        pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="sealed"),
        bench.runtime.session(workspace) as connection,
    ):
        batches.mark_erasure_withdrawn(connection, workspace, batch.piece_batch_id, played.now)
    _restore(purged, dump, blobs)
    _replay(source, marker)
    [restored] = played.rows("select * from piece_erasure_settlement")
    assert restored == obligation
    assert played.rows("select 1 from piece_request") == []
    played.worker.run_once()
    [reservation] = played.reservations()
    assert reservation["state"] == "settled"
    assert Decimal(reservation["settled_usd"]) == Decimal("0.012345")
    events = played.rows("select * from piece_erasure_settlement_event order by kind")
    assert {row["kind"] for row in events} == {"withdrawn", "decided", "settled"}
    [decision] = [row for row in events if row["kind"] == "decided"]
    assert (decision["basis"], decision["usd"]) == ("reported", Decimal("0.012345"))
    played.worker.run_once()
    assert played.reservations() == [reservation]
    assert played.rows("select * from piece_erasure_settlement_event order by kind") == events
    assert played.bucket.get(f"withdrawn/{entry}.json")


def test_restore_keeps_obligation_pending_when_backup_has_no_reservation(
    purged, commands, repository, bench, tmp_path
):
    played = Played(repository, bench, tmp_path, "0.50")
    dump, blobs = _backup(purged, tmp_path)
    entry = _queued(played)
    played.tombstone()
    [obligation] = played.rows("select * from piece_erasure_settlement")
    source, marker = _seal(tmp_path)
    _restore(purged, dump, blobs)
    _replay(source, marker)
    assert played.reservations() == []
    played.worker.run_once()
    assert played.rows("select * from piece_erasure_settlement") == [obligation]
    assert played.rows("select 1 from piece_erasure_settlement_event where kind='settled'") == []
    [decision] = played.rows(
        "select basis,usd from piece_erasure_settlement_event where kind='decided'"
    )
    assert (decision["basis"], decision["usd"]) == ("unknown", obligation["worst_case_usd"])
    assert played.bucket.get(f"withdrawn/{entry}.json")
    played.worker.run_once()
    assert played.rows("select 1 from piece_erasure_settlement_event where kind='settled'") == []
    assert played.reservations() == []
