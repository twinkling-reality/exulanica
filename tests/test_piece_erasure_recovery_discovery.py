"""Revoked accounts drain erased obligations without regaining runtime authority."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from exulanica.db.account_workspaces import AccountWorkspaceSource
from exulanica.generation import command
from exulanica.ingest.repository import IngestRepository

from account_fixtures import account_api as account_api
from account_fixtures import account_role as account_role
from spending_support import bench as bench
from test_piece_generation_worker_postgres import Played, _queued

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("revocation", ["user", "membership", "workspace"])
@pytest.mark.parametrize("erased", [True, False])
def test_recovery_discovery_drains_only_erased_work_and_leaves_revocation_in_force(
    account_api, repository, bench, tmp_path, monkeypatch, revocation, erased
):
    api = account_api
    account = api.login()
    workspace = uuid.UUID(account["workspace_id"])
    p = Played(IngestRepository(repository.connection, workspace), bench, tmp_path, "0.50")
    entry = _queued(p)
    if erased:
        p.tombstone()
    else:
        # A completed provider result is available, but revocation must prevent normal follow-up.
        p.run_the_entry()
    source = AccountWorkspaceSource(api.runtime.database_url, bench.runtime.url).verify()
    monkeypatch.setattr(command, "bucket_from_environment", lambda environ: p.bucket)
    monkeypatch.setattr(
        command, "durable_spending_from_env", lambda *args, **kwargs: bench.durable()
    )
    clock = p.worker.now
    p.worker = command.build(
        SimpleNamespace(workspace=[]),
        {
            "EXULANICA_DATABASE_URL": bench.runtime.url,
            "EXULANICA_ACCOUNT_DATABASE_URL": api.runtime.database_url,
            "EXULANICA_DATA_DIR": str(tmp_path / "command-store"),
        },
    )
    p.worker.now = clock
    with api.runtime.repository() as repo:
        if revocation == "user":
            repo.disable_account(uuid.UUID(account["user_id"]))
        elif revocation == "membership":
            repo.connection.execute(
                "update account_membership set revoked_at=now() where workspace_id=%s",
                (workspace,),
            )
        else:
            repo.connection.execute(
                "update account_workspace set disabled_at=now() where workspace_id=%s",
                (workspace,),
            )
    assert workspace not in source()
    assert workspace in source.recovery_candidates()
    assert api.client.get("/protected").status_code == 401
    assert not api.runtime.owned_workspace_active(workspace)
    forbidden = []

    def ordinary_work(*args, **kwargs):
        forbidden.append(True)
        raise AssertionError("recovery discovery must never authorize ordinary work")

    monkeypatch.setattr(p.worker, "_follow", ordinary_work)
    monkeypatch.setattr(p.worker, "_queue", ordinary_work)
    p.worker.looks = SimpleNamespace(run=ordinary_work)
    p.worker.run_once()
    assert forbidden == []
    if erased:
        assert p.rows("select 1 from piece_request") == []
        assert p.reservations()[0]["state"] == "unknown"
        assert p.rows("select 1 from piece_erasure_settlement_event where kind='settled'")
        assert p.bucket.get(f"withdrawn/{entry}.json")
    else:
        assert p.rows("select state from piece_request") == [{"state": "queued"}]
        assert p.reservations()[0]["state"] == "dispatched"
        assert p.rows("select 1 from piece_settlement") == []
        assert p.bucket.keys("withdrawn/") == []
    assert api.client.get("/protected").status_code == 401
    assert not api.runtime.owned_workspace_active(workspace)
    assert workspace not in source()
