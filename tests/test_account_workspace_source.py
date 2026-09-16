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
    assert "m.membership_role='owner'" in statement
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
