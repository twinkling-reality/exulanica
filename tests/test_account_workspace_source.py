"""Dedicated worker account discovery role and database-binding boundaries."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from exulanica.db import account_workspaces
from exulanica.db.account_workspaces import (
    AccountWorkspaceSource,
    AccountWorkspaceUnavailable,
    active_owned_workspaces,
)


class Result:
    def __init__(self, *, one=None, all_rows=()):
        self.one = one
        self.all_rows = all_rows

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.all_rows


class Connection:
    def __init__(self, database, schema="world"):
        self.database = database
        self.schema = schema
        self.info = SimpleNamespace(host="database", port=5432, dbname=database)
        self.statements = []
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))
        if "current_database()" in statement:
            return Result(
                one={
                    "database_name": self.database,
                    "schema_name": self.schema,
                    "search_path": f"{self.schema}, public",
                    "server_address": "127.0.0.1",
                    "server_port": 5432,
                }
            )
        if "from account_workspace" in statement:
            return Result(all_rows=self.rows)
        return Result()


def test_current_workspace_query_uses_membership_revocation_not_browser_sessions():
    first, second = uuid.uuid4(), uuid.uuid4()
    connection = Connection("accounts")
    connection.rows = [{"workspace_id": second}, {"workspace_id": first}]

    assert active_owned_workspaces(connection) == frozenset({first, second})
    statement = connection.statements[-1][0]
    assert "u.disabled_at is null" in statement
    assert "w.disabled_at is null" in statement
    assert "m.revoked_at is null" in statement
    assert "m.membership_role in ('owner','guest')" in statement
    assert "m.user_id=w.owner_user_id" in statement
    assert "account_browser_session" not in statement


def test_source_verifies_both_roles_resolve_to_one_database_and_bounds_io(monkeypatch):
    account, application = Connection("world"), Connection("world")
    connections = iter((account, application))
    calls = []

    def connect(url, **kwargs):
        calls.append((url, kwargs))
        return next(connections)

    monkeypatch.setattr(account_workspaces.psycopg, "connect", connect)
    monkeypatch.setattr(account_workspaces, "assert_account_role", lambda value: value is account)
    source = AccountWorkspaceSource("account-secret-url", "application-secret-url")

    assert source.verify() is source
    assert "secret" not in repr(source)
    assert [call[0] for call in calls] == ["account-secret-url", "application-secret-url"]
    assert all(call[1]["connect_timeout"] == 5 for call in calls)
    assert all(
        any("statement_timeout" in statement for statement, _ in connection.statements)
        for connection in (account, application)
    )


def test_source_rejects_a_different_world_database_without_exposing_urls(monkeypatch):
    connections = iter((Connection("accounts"), Connection("world")))
    monkeypatch.setattr(
        account_workspaces.psycopg, "connect", lambda *_args, **_kwargs: next(connections)
    )
    monkeypatch.setattr(account_workspaces, "assert_account_role", lambda _connection: None)
    source = AccountWorkspaceSource("account-secret-url", "application-secret-url")

    with pytest.raises(AccountWorkspaceUnavailable, match="same database/schema") as failure:
        source.verify()
    assert "secret" not in str(failure.value)


def test_a_paced_source_names_the_workspaces_there_each_pass_and_every_one_now_and_then():
    """Every pass reads who is there; every SLOW_SCAN_SECONDS, everyone; a guest who is not there
    costs a pass nothing between scans."""
    from exulanica.db.account_workspaces import SLOW_SCAN_SECONDS, PacedWorkspaces

    there, everyone = (
        frozenset({uuid.UUID(int=1)}),
        frozenset({uuid.UUID(int=n) for n in (1, 2, 3)}),
    )
    asked: list[str] = []

    class Source:
        def recent(self, guest_seconds):
            asked.append(f"recent {guest_seconds}")
            return there

        def __call__(self):
            asked.append("every")
            return everyone

    now = [1_000.0]
    paced = PacedWorkspaces(Source(), guest_seconds=900, clock=lambda: now[0])  # type: ignore[arg-type]
    assert paced() == everyone
    assert paced() == there
    now[0] += SLOW_SCAN_SECONDS - 1
    assert paced() == there
    now[0] += 1
    assert paced() == everyone
    assert asked == ["recent 900", "every", "recent 900", "recent 900", "recent 900", "every"]


def test_a_paced_source_takes_the_play_window_from_the_environment(monkeypatch):
    from exulanica.db import account_workspaces

    class Source:
        def __init__(self, account_url, application_url):
            pass

        def verify(self):
            return self

    monkeypatch.setattr(account_workspaces, "AccountWorkspaceSource", Source)
    assert account_workspaces.paced_account_source(None, "app", {}) is None
    paced = account_workspaces.paced_account_source("account", "app", {})
    assert paced is not None and paced.guest_seconds == 900
    window = {account_workspaces.GUEST_PLAY_SECONDS_ENV: "600"}
    assert account_workspaces.paced_account_source("account", "app", window).guest_seconds == 600
    with pytest.raises(ValueError):
        account_workspaces.paced_account_source(
            "account", "app", {account_workspaces.GUEST_PLAY_SECONDS_ENV: "30"}
        )


@pytest.mark.parametrize(
    "command",
    [
        "exulanica/ingest/generated_tiles_command.py",
        "exulanica/ingest/worker_command.py",
        "exulanica/world/asset_preparation_command.py",
        "exulanica/world/material_bake_command.py",
    ],
)
def test_every_worker_command_reads_its_account_workspaces_paced(command):
    """A worker that drained every account workspace each pass would cost every admitted guest a
    session per pass for good; each builds its source with paced_account_source."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / command).read_text(encoding="utf-8")
    assert "paced_account_source(" in text
    assert "AccountWorkspaceSource(" not in text


def test_the_apis_own_derivative_worker_reads_its_account_workspaces_paced():
    """The API can run the derivative worker in its own process (EXULANICA_DERIVATIVE_WORKER);
    its account workspaces are paced like the worker commands'."""
    from pathlib import Path

    from exulanica.api.services import _RuntimeAccounts

    text = (Path(__file__).resolve().parents[1] / "exulanica/api/services.py").read_text(
        encoding="utf-8"
    )
    builder = text.split("return DerivativeWorker(", 1)[1].split("lease_seconds=", 1)[0]
    assert "PacedWorkspaces(" in builder and "_RuntimeAccounts(self.accounts)" in builder

    asked: list[object] = []

    class Accounts:
        def active_owned_workspaces(self):
            asked.append("every")
            return frozenset({uuid.UUID(int=1), uuid.UUID(int=2)})

        def recent_workspaces(self, guest_seconds):
            asked.append(guest_seconds)
            return frozenset({uuid.UUID(int=1)})

    source = _RuntimeAccounts(Accounts())  # type: ignore[arg-type]
    assert source() == frozenset({uuid.UUID(int=1), uuid.UUID(int=2)})
    assert source.recent(900) == frozenset({uuid.UUID(int=1)})
    assert asked == ["every", 900]
