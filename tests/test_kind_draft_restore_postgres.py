"""Actual dump/restore replays native-kind erasure without restoring private draft content."""

from __future__ import annotations

import uuid

import pytest
from exulanica.deletion.restore import verify_restore
from exulanica.world.kind_draft_jobs import KindDraftRepository
from exulanica.world.kinds.erasure import erase_kind

from spending_support import bench as bench
from spending_support import reported_usage, spending_request
from test_kind_draft_durability_postgres import WORDS, checked_kind, submit_kind
from test_purge import purged as purged
from test_restore_replay import _backup, _restore
from test_restore_replay_search_entries import _seal
from test_restore_replay_search_entries import commands as commands
from test_restore_replay_withdrawals import _replay

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    ("scope", "backup_before_publication"),
    [("kind", False), ("workspace", False), ("kind", True)],
)
def test_restore_replays_native_kind_content_erasure_and_keeps_liability(
    bench, purged, commands, tmp_path, scope, backup_before_publication
):
    workspace, actor = purged.workspace_id, uuid.uuid4()
    kind, report = checked_kind()
    with bench.runtime.session(workspace) as connection:
        repo = KindDraftRepository(connection, workspace)
        completed = submit_kind(repo, actor)
        claimed = repo.claim("private-kind-restore")
        assert claimed is not None and claimed.draft_id == completed
        if not backup_before_publication:
            repo.publish(claimed, kind, report, calls=[], model_id="private/scripted")
    # With the first draft still active, a separate workspace supplies the unrelated
    # pending positive control without relaxing ordinary workspace admission limits.
    pending_workspace = uuid.uuid4() if backup_before_publication else workspace
    with bench.runtime.session(pending_workspace) as connection:
        pending = submit_kind(
            KindDraftRepository(connection, pending_workspace), actor, words=WORDS
        )
    # A real witnessed financial reservation is retained independently of draft text. This
    # is ledger authority, not a live provider call or synthetic claim of model quality.
    authority = bench.issue(ceiling="1")
    bench.grant(authority, workspace, ceiling="1")
    gate = bench.durable("native-kind-restore").for_workspace(workspace)
    ticket = gate.admit(spending_request(key=f"kind-draft:{completed}:private-restore"))
    gate.dispatch(ticket)
    gate.settle(ticket, reported_usage(str(ticket.usd)))
    liability = bench.query(
        "select reservation_id,state,reserved_usd,settled_usd "
        "from spending_reservation order by reservation_id"
    )
    starts = bench.query("select * from kind_draft_start order by draft_id")
    expected_inputs = [{"description": WORDS}] * (2 if backup_before_publication else 1)
    assert bench.query("select description from kind_draft_input") == expected_inputs
    dump, blobs = _backup(purged, tmp_path)
    with bench.runtime.session(workspace) as connection:
        if backup_before_publication:
            repo = KindDraftRepository(connection, workspace)
            # Fixture clock setup affects only this private schema's next outcome;
            # publication still crosses the unchanged live-claim and binding checks.
            with bench.admin.session(workspace) as admin:
                admin.execute(
                    "alter table kind_draft_outcome alter column completed_at "
                    "set default (statement_timestamp()-interval '2 hours')"
                )
            try:
                repo.publish(claimed, kind, report, calls=[], model_id="private/scripted")
            finally:
                with bench.admin.session(workspace) as admin:
                    admin.execute(
                        "alter table kind_draft_outcome alter column completed_at "
                        "set default statement_timestamp()"
                    )
            # The kept kind outlives the one-hour draft result. Its later erasure
            # must still identify the request in a backup predating publication.
            connection.execute(
                "update job set completed_at=clock_timestamp()-interval '2 hours' where job_id=%s",
                (claimed.job_id,),
            )
            repo.expire()
            assert connection.execute("select 1 from kind_draft_outcome").fetchall() == []
        if scope == "kind":
            erase_kind(connection, workspace, kind.sha256, erased_by=actor)
        else:
            connection.execute(
                "insert into tombstone(workspace_id,scope,requested_by,reason) "
                "values(%s,'workspace',%s,'Private native kind restore erasure')",
                (workspace, actor),
            )
    source, marker = _seal(tmp_path)
    _restore(purged, dump, blobs)
    # Positive control: the old backup restores the actual private request. A backup
    # taken before publication has no result from which to rediscover the erased draft.
    assert bench.query("select description from kind_draft_input") == expected_inputs
    assert bool(bench.query("select 1 from kind_draft_outcome")) != backup_before_publication
    _replay(source, marker)
    verify_restore(purged.database(), marker)
    with bench.runtime.session(workspace) as connection:
        repo = KindDraftRepository(connection, workspace)
        assert repo.get(actor, completed) is None
        assert connection.execute("select 1 from kind_draft_outcome").fetchall() == []
        assert connection.execute("select 1 from kind_draft_attempt").fetchall() == []
        assert connection.execute("select 1 from world_kind_version").fetchall() == []
        if scope == "workspace":
            assert repo.get(actor, pending) is None
            assert connection.execute("select 1 from kind_draft_input").fetchall() == []
    if scope == "kind":
        # Erasing one result must not cancel or expose an unrelated pending draft.
        with bench.runtime.session(pending_workspace) as connection:
            assert (
                KindDraftRepository(connection, pending_workspace).get(actor, pending)[
                    "description"
                ]
                == WORDS
            )
    assert bench.query("select * from kind_draft_start order by draft_id") == starts
    assert (
        bench.query(
            "select reservation_id,state,reserved_usd,settled_usd "
            "from spending_reservation order by reservation_id"
        )
        == liability
    )
