"""Shared deployment boundaries, rather than isolated feature compositions."""

from __future__ import annotations

import asyncio
import dataclasses
import threading
import uuid
from types import SimpleNamespace

import pytest
from exulanica.api import account_runtime
from exulanica.api.account_repository import AccountRepository
from exulanica.api.app import _lifespan
from exulanica.api.authorisation import TokenDirectory, TokenNotAccepted
from exulanica.api.routes.health import _society_check
from exulanica.api.services import (
    SOCIETY_CONTROL_WORKER_ENV,
    Services,
    _explicitly_enabled,
    build_services,
    describe_configuration,
)
from exulanica.db.session import Database
from exulanica.selection.validation import Session
from exulanica.store.local import LocalContentAddressedStore
from starlette.requests import Request


def services(tmp_path, **kwargs):
    return Services(
        database=Database(url="postgresql://unused"),
        readonly_database=Database(url="postgresql://unused"),
        store=LocalContentAddressedStore(tmp_path),
        tokens=TokenDirectory(sessions={}),
        executor_shares_the_write_role=True,
        model_client=None,
        **kwargs,
    )


def test_account_only_startup_never_replaces_explicit_bad_tokens(monkeypatch, tmp_path):
    runtime = object()
    monkeypatch.setattr("exulanica.api.services.load_account_runtime", lambda _: runtime)
    environ = {"EXULANICA_DATABASE_URL": "postgresql://unused", "EXULANICA_DATA_DIR": str(tmp_path)}
    assert len(build_services(environ).tokens) == 0
    assert build_services(
        {**environ, SOCIETY_CONTROL_WORKER_ENV: "true"}
    ).runs_society_control_worker
    with pytest.raises(ValueError, match=SOCIETY_CONTROL_WORKER_ENV):
        build_services({**environ, SOCIETY_CONTROL_WORKER_ENV: "automatic"})
    for value in ("", "{}", "invalid json"):
        with pytest.raises(TokenNotAccepted):
            build_services({**environ, "EXULANICA_API_TOKENS": value})
    monkeypatch.setattr("exulanica.api.services.load_account_runtime", lambda _: None)
    with pytest.raises(TokenNotAccepted):
        build_services(environ)
    report = describe_configuration({"EXULANICA_GOOGLE_CLIENT_SECRET": "must-not-appear"})
    assert report["EXULANICA_GOOGLE_CLIENT_SECRET"] == "set"
    assert "must-not-appear" not in str(report)


def test_playback_is_explicit_and_requires_current_input_runtime(tmp_path):
    empty = services(tmp_path)
    assert empty.build_society_control_worker() is None
    configured = dataclasses.replace(empty, society_control_workspaces=(uuid.uuid4(),))
    with pytest.raises(ValueError, match="current-input"):
        configured.build_society_control_worker()


def test_account_workspace_query_matches_current_membership_and_revocation_authority():
    first, second = uuid.uuid4(), uuid.uuid4()

    class Result:
        def fetchall(self):
            return [{"workspace_id": second}, {"workspace_id": first}]

    class Connection:
        statement = ""

        def execute(self, statement):
            self.statement = statement
            return Result()

    connection = Connection()
    assert AccountRepository(connection).active_owned_workspaces() == frozenset({first, second})
    assert "u.disabled_at is null" in connection.statement
    assert "w.disabled_at is null" in connection.statement
    assert "m.revoked_at is null" in connection.statement
    assert "m.membership_role='owner'" in connection.statement
    assert "m.user_id=w.owner_user_id" in connection.statement
    assert "account_browser_session" not in connection.statement


def test_account_repository_connections_bound_connect_and_statement_time(monkeypatch):
    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, statement, parameters=None):
            calls.append((statement, parameters))

    def connect(url, **kwargs):
        calls.append((url, kwargs))
        return Connection()

    monkeypatch.setattr(account_runtime.psycopg, "connect", connect)
    runtime = SimpleNamespace(database_url="account-secret-url")
    with account_runtime.AccountRuntime.repository(runtime) as repository:
        assert isinstance(repository, AccountRepository)

    assert calls[0][0] == "account-secret-url"
    assert calls[0][1]["connect_timeout"] == 5
    assert calls[-1] == (
        "select set_config('statement_timeout', %s, false)",
        ("5s",),
    )


def test_worker_discovery_is_role_separated_and_society_requires_explicit_opt_in(
    monkeypatch, tmp_path
):
    token_workspace, account_workspace = uuid.uuid4(), uuid.uuid4()
    runtime = SimpleNamespace(active_owned_workspaces=lambda: frozenset({account_workspace}))
    token = TokenDirectory(
        sessions={"configured-digest": Session(workspace_id=token_workspace, actor=uuid.uuid4())}
    )
    captured = {}

    class Derivatives:
        def __init__(self, *args, **kwargs):
            captured["derivative_static"] = args[2]
            captured["derivative_source"] = kwargs["workspace_source"]

    class Playback:
        def __init__(self, *args, **kwargs):
            captured["society_static"] = frozenset(kwargs["workspaces"])
            captured["society_source"] = kwargs["workspace_source"]

    monkeypatch.setattr("exulanica.api.services.DerivativeWorker", Derivatives)
    monkeypatch.setattr("exulanica.api.services.SocietyControlWorker", Playback)
    configured = dataclasses.replace(
        services(tmp_path),
        tokens=token,
        accounts=runtime,
        runs_derivative_worker=True,
        society_runtime=object(),
    )

    configured.build_derivative_worker()
    assert captured["derivative_static"] == frozenset({token_workspace})
    assert captured["derivative_source"]() == frozenset({account_workspace})
    assert configured.build_society_control_worker() is None

    dynamic = dataclasses.replace(configured, runs_society_control_worker=True)
    dynamic.build_society_control_worker()
    assert captured["society_static"] == frozenset()
    assert captured["society_source"]() == frozenset({account_workspace})

    without_accounts = dataclasses.replace(dynamic, accounts=None)
    with pytest.raises(ValueError, match="configured accounts"):
        without_accounts.build_society_control_worker()


def test_account_wide_society_switch_is_strict_and_absent_is_off():
    assert _explicitly_enabled(None) is False
    assert _explicitly_enabled("off") is False
    assert _explicitly_enabled("YES") is True
    with pytest.raises(ValueError, match=SOCIETY_CONTROL_WORKER_ENV):
        _explicitly_enabled("sometimes")


def test_shutdown_waits_for_active_playback_batch_without_blocking_event_loop(
    monkeypatch, tmp_path
):
    started, stopping, release = threading.Event(), threading.Event(), threading.Event()

    class Worker:
        def run(self, stop):
            started.set()
            stop.wait()
            stopping.set()
            assert release.wait(5), "test failed to release active batch"

    monkeypatch.setattr(Services, "build_society_control_worker", lambda _: Worker())
    monkeypatch.setattr("exulanica.api.app.verify_restore", lambda *_: None)
    monkeypatch.setattr("exulanica.api.app.seed_reviewed_assets", lambda *_: None)
    app = SimpleNamespace(
        state=SimpleNamespace(services=services(tmp_path), verify_schema_at_boot=False)
    )

    async def scenario():
        context = _lifespan(app)
        await context.__aenter__()
        assert await asyncio.to_thread(started.wait, 1)
        closing = asyncio.create_task(context.__aexit__(None, None, None))
        try:
            assert await asyncio.to_thread(stopping.wait, 1)
            assert not closing.done()
            assert app.state.society_control_thread.is_alive()
        finally:
            release.set()
            await asyncio.wait_for(closing, 2)
        assert not app.state.society_control_thread.is_alive()

    asyncio.run(scenario())


def test_playback_readiness_reports_failed_round_and_recovery(tmp_path):
    configured = services(tmp_path, society_control_workspaces=(uuid.uuid4(),))
    worker = SimpleNamespace(health={"failed_rounds": 1, "last_round_failed": True})
    app = SimpleNamespace(
        state=SimpleNamespace(
            society_control_worker=worker,
            society_control_thread=SimpleNamespace(is_alive=lambda: True),
        )
    )
    request = Request({"type": "http", "app": app})
    assert _society_check(request, configured)["ok"] is False
    worker.health = {"failed_rounds": 1, "last_round_failed": False}
    assert _society_check(request, configured)["ok"] is True
    app.state.society_control_thread = None
    assert _society_check(request, configured)["ok"] is False


def test_dynamic_playback_opt_in_participates_in_readiness(tmp_path):
    configured = services(
        tmp_path,
        accounts=object(),
        society_runtime=object(),
        runs_society_control_worker=True,
    )
    app = SimpleNamespace(
        state=SimpleNamespace(society_control_worker=None, society_control_thread=None)
    )
    result = _society_check(Request({"type": "http", "app": app}), configured)
    assert result == {
        "ok": False,
        "configured": True,
        "running": False,
        "failed_rounds": 0,
        "last_round_failed": False,
        "proves": "worker liveness and last round status; no promised simulation delivery rate",
    }
