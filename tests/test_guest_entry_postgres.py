"""A visitor enters as a guest: one request, a workspace of their own, and nothing more.

``POST /auth/guest`` (migration 0139) makes an account with no identity, a workspace, a membership
in the role ``guest`` and a cookie session, on the account role, after checking the request's
origin, the entry code where one is configured, and the day's count. Each test names a way the open
door could be wrong: anyone entering where the server asks for a code, a request from another site
entering, more guests a day than the server states, a guest reaching what only an owner may, a write
without the session's CSRF token, or a lost cookie leaving a workspace somebody else can reach.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from collections.abc import Iterator
from types import MappingProxyType, SimpleNamespace
from typing import Annotated

import psycopg
import pytest
from exulanica.api import permissions
from exulanica.api.account_repository import AccountRepository, GuestEntriesExhausted
from exulanica.api.account_runtime import SESSION_COOKIE, AccountRuntime, GuestEntryConfig
from exulanica.api.authorisation import TokenDirectory, TokenNotAccepted
from exulanica.api.dependencies import current_session
from exulanica.api.routes import accounts
from exulanica.api.services import Services
from exulanica.selection.validation import Session
from exulanica.store.local import LocalContentAddressedStore
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from account_fixtures import account_role as account_role
from tests_support_api import scratch_database

pytestmark = pytest.mark.postgres

ORIGIN = "https://app.test"
CODE = "a-code-for-the-judges"
#: The figures every test's server states, written out here.
PER_DAY = 3
SESSION_SECONDS = 7 * 24 * 60 * 60


def _app(account_role, spine_schema, tmp_path, guest: GuestEntryConfig) -> TestClient:
    _, scratch = spine_schema
    database = scratch_database(scratch)
    runtime = AccountRuntime(None, account_role, None, guest)
    runtime.verify_database(database.url)
    app = FastAPI()
    app.state.services = Services(
        database=database,
        readonly_database=database,
        store=LocalContentAddressedStore(tmp_path / "guest-store"),
        tokens=TokenDirectory(sessions={}),
        executor_shares_the_write_role=True,
        model_client=None,
        accounts=runtime,
    )
    app.include_router(accounts.router)

    @app.exception_handler(permissions.PermissionRefused)
    async def refused(_request: Request, exc: permissions.PermissionRefused) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"code": "permission_refused"})

    @app.exception_handler(TokenNotAccepted)
    async def unauthenticated(_request: Request, exc: TokenNotAccepted) -> JSONResponse:
        return JSONResponse(
            status_code=401, content={"code": "unauthenticated", "detail": str(exc)}
        )

    @app.get("/world-read")
    @app.post("/world-write")
    @app.post("/intake-write")
    def probe(session: Annotated[Session, Depends(current_session)]):
        return {"workspace_id": str(session.workspace_id)}

    declared = {
        **permissions.ROUTE_RULES,
        ("GET", "/world-read"): permissions.Requires(
            frozenset({permissions.Permission.WORLD_READ})
        ),
        ("POST", "/world-write"): permissions.Requires(
            frozenset({permissions.Permission.WORLD_WRITE})
        ),
        ("POST", "/intake-write"): permissions.Requires(
            frozenset({permissions.Permission.INTAKE_WRITE})
        ),
    }
    patch = pytest.MonkeyPatch()
    patch.setattr(permissions, "ROUTE_RULES", MappingProxyType(declared))
    client = TestClient(app, base_url=ORIGIN, follow_redirects=False)
    client.__dict__["_patch"] = patch
    return client


@pytest.fixture
def guest_app(account_role, spine_schema, tmp_path) -> Iterator:
    made: list[TestClient] = []

    def build(mode: str = "open", *, per_day: int = PER_DAY) -> TestClient:
        guest = GuestEntryConfig(
            mode=mode,
            browser_origins=(ORIGIN,),
            entries_per_day=per_day,
            session_seconds=SESSION_SECONDS,
            code_sha256=hashlib.sha256(CODE.encode()).hexdigest() if mode == "code" else None,
        )
        client = _app(account_role, spine_schema, tmp_path, guest)
        made.append(client)
        return client

    yield build
    # In reverse: each patch saved the table the one before it had set.
    for client in reversed(made):
        client.__dict__["_patch"].undo()
        client.close()


def _enter(client: TestClient, **body) -> object:
    return client.post("/auth/guest", json=body or None, headers={"Origin": ORIGIN})


def _entries_today(account_role) -> int:
    with psycopg.connect(account_role, row_factory=dict_row) as connection:
        row = connection.execute(
            "select entries from account_guest_day "
            "where entry_day = (now() at time zone 'UTC')::date"
        ).fetchone()
    return 0 if row is None else row["entries"]


def test_an_open_server_admits_a_guest_to_a_workspace_of_their_own(guest_app, account_role):
    client = guest_app(per_day=1_000_000)
    entered = _enter(client)
    assert entered.status_code == 201, entered.text
    body = entered.json()
    assert body["role"] == "guest"
    cookie = entered.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", f"Max-Age={SESSION_SECONDS}"):
        assert attribute.lower() in cookie.lower(), attribute
    session = client.get("/auth/session")
    assert session.status_code == 200
    assert session.json()["workspace_id"] == body["workspace_id"]
    assert session.json()["role"] == "guest"
    # The session's workspace is the one every request of it runs in.
    assert client.get("/world-read").json()["workspace_id"] == body["workspace_id"]


def test_a_guest_holds_the_journey_and_writes_need_the_session_s_csrf_token(guest_app):
    client = guest_app(per_day=1_000_000)
    body = _enter(client).json()
    csrf = {"Origin": ORIGIN, "X-CSRF-Token": body["csrf_token"]}
    assert client.post("/world-write", headers={"Origin": ORIGIN}).status_code == 401
    assert client.post("/world-write", headers=csrf).status_code == 200
    refused = client.post("/intake-write", headers=csrf)
    assert refused.status_code == 403, refused.text


def test_a_code_server_admits_only_the_code(guest_app):
    client = guest_app("code", per_day=1_000_000)
    for body in ({}, {"code": "not-the-code"}):
        refused = _enter(client, **body)
        assert refused.status_code == 403
        assert refused.json()["code"] == "guest_entry_code_wrong"
        assert "set-cookie" not in refused.headers
    assert _enter(client, code=CODE).status_code == 201


def test_a_request_from_another_origin_enters_nothing(guest_app, account_role):
    client = guest_app(per_day=1_000_000)
    before = _entries_today(account_role)
    for headers in ({}, {"Origin": "https://elsewhere.test"}):
        refused = client.post("/auth/guest", headers=headers)
        assert refused.status_code == 403
        assert refused.json()["code"] == "origin_not_permitted"
    assert _entries_today(account_role) == before


def test_no_accounts_configured_answer_as_every_account_route_does(
    account_role, spine_schema, tmp_path
):
    _, scratch = spine_schema
    app = FastAPI()
    app.state.services = Services(
        database=scratch_database(scratch),
        readonly_database=scratch_database(scratch),
        store=LocalContentAddressedStore(tmp_path / "s"),
        tokens=TokenDirectory(sessions={}),
        executor_shares_the_write_role=True,
        model_client=None,
        accounts=None,
    )
    app.include_router(accounts.router)
    with TestClient(app, base_url=ORIGIN) as client:
        refused = client.post("/auth/guest", headers={"Origin": ORIGIN})
    assert refused.status_code == 503
    assert refused.json()["code"] == "account_unavailable"


def test_a_day_admits_its_stated_number_and_no_more_even_raced(account_role):
    """The day's count is taken in the entry's own transaction: seven entries racing on seven
    connections are admitted exactly up to the limit, set four above the day's count so far."""
    limit = _entries_today(account_role) + 4
    admitted: list[uuid.UUID] = []
    refused: list[str] = []
    lock = threading.Lock()

    def enter() -> None:
        with psycopg.connect(account_role, autocommit=True, row_factory=dict_row) as connection:
            try:
                entry = AccountRepository(connection).enter_guest(
                    entries_per_day=limit, session_seconds=SESSION_SECONDS
                )
            except GuestEntriesExhausted as exc:
                with lock:
                    refused.append(str(exc))
            else:
                with lock:
                    admitted.append(entry.entry_id)

    threads = [threading.Thread(target=enter) for _ in range(7)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(admitted) == 4 and len(refused) == 3
    assert _entries_today(account_role) == limit


def test_a_full_day_is_refused_by_name_through_the_route(guest_app, account_role):
    client = guest_app(per_day=_entries_today(account_role) + 1)
    assert _enter(client).status_code == 201
    refused = _enter(client)
    assert refused.status_code == 429
    assert refused.json()["code"] == "guest_entries_exhausted"


def test_a_lost_cookie_leaves_nothing_anyone_else_can_reach(guest_app):
    """Two visitors, and the first loses their cookie and enters again. Every workspace is reached
    only by the session that made it: a new entry is a new workspace, the second visitor's requests
    run in theirs, and a request with no cookie, or with a cookie nobody issued, is refused."""
    first = guest_app(per_day=1_000_000)
    second = guest_app(per_day=1_000_000)
    lost = _enter(first).json()["workspace_id"]
    other = _enter(second).json()["workspace_id"]
    assert lost != other
    first.cookies.clear()
    assert first.get("/world-read").status_code == 401
    first.cookies.set(SESSION_COOKIE, "x" * 43, domain="app.test")
    assert first.get("/world-read").status_code == 401
    first.cookies.clear()
    again = _enter(first).json()["workspace_id"]
    assert again not in (lost, other)
    assert first.get("/world-read").json()["workspace_id"] == again
    assert second.get("/world-read").json()["workspace_id"] == other


def test_a_session_names_exactly_one_origin_and_its_last_use_only_moves_forward(
    guest_app, account_role
):
    client = guest_app(per_day=1_000_000)
    _enter(client)
    with psycopg.connect(account_role, autocommit=True, row_factory=dict_row) as connection:
        session = connection.execute(
            "select session_sha256, user_id, workspace_id, guest_entry_id, seen_at "
            "from account_browser_session where guest_entry_id is not null "
            "order by created_at desc limit 1"
        ).fetchone()
        assert session["seen_at"] is not None
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "insert into account_browser_session(session_sha256,user_id,workspace_id,"
                "csrf_token,expires_at) values(%s,%s,%s,%s,now()+interval '1 hour')",
                (
                    hashlib.sha256(b"neither").hexdigest(),
                    session["user_id"],
                    session["workspace_id"],
                    "c" * 43,
                ),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "update account_browser_session set seen_at = seen_at - interval '1 hour' "
                "where session_sha256 = %s",
                (session["session_sha256"],),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "update account_guest_entry set entry_day = entry_day - 1 where entry_id = %s",
                (session["guest_entry_id"],),
            )


class _FailingSpending:
    """A durable authority whose guest grant fails as a slow database would, and counts asks."""

    def __init__(self) -> None:
        self.asked: list[uuid.UUID] = []

    def grant_guest(self, workspace_id: uuid.UUID, *, provider: str) -> uuid.UUID:
        self.asked.append(workspace_id)
        raise RuntimeError("the spending database did not answer in time")


def test_an_entry_whose_later_steps_fail_still_answers_201_with_its_cookie(guest_app):
    """Once the account is committed the visitor holds it: a failed allowance and a missing
    arrival world are named in the answer, never a lost cookie and a spent slot. The next session
    read asks for the allowance again."""
    import dataclasses

    client = guest_app(per_day=1_000_000)
    spending = _FailingSpending()
    client.app.state.services = dataclasses.replace(client.app.state.services, spending=spending)
    entered = _enter(client)
    assert entered.status_code == 201, entered.text
    assert entered.headers["set-cookie"].startswith(f"{SESSION_COOKIE}=")
    body = entered.json()
    steps = {(problem["step"], problem["code"]) for problem in body["incomplete"]}
    assert ("allowance", "allowance_failed") in steps
    # This test database bakes no arrival tiles, so no arrival world is made.
    assert body["arrival"] is None and ("arrival", "arrival_not_made") in steps
    asked = len(spending.asked)
    assert asked >= 1
    session = client.get("/auth/session")
    assert session.status_code == 200
    assert len(spending.asked) > asked, "a session read asks again for an allowance not held"


def test_a_full_day_says_when_the_next_one_starts():
    import datetime as dt

    from exulanica.api.routes.accounts import _seconds_to_the_next_utc_day

    late = dt.datetime(2026, 10, 6, 23, 59, 30, tzinfo=dt.UTC)
    assert _seconds_to_the_next_utc_day(late) == 30
    assert _seconds_to_the_next_utc_day(dt.datetime(2026, 10, 6, 0, 0, tzinfo=dt.UTC)) == 86_400


def test_a_full_day_through_the_route_carries_retry_after(guest_app, account_role):
    client = guest_app(per_day=_entries_today(account_role) + 1)
    assert _enter(client).status_code == 201
    refused = _enter(client)
    assert refused.status_code == 429
    seconds = int(refused.headers["retry-after"])
    assert 1 <= seconds <= 86_400 and refused.json()["retry_after_seconds"] == seconds


def test_a_database_that_does_not_answer_is_not_told_as_no_guest_entry(tmp_path, spine_schema):
    """An entry whose account database fails says so, apart from a server with no guest entry."""
    guest = GuestEntryConfig(
        mode="open",
        browser_origins=(ORIGIN,),
        entries_per_day=PER_DAY,
        session_seconds=SESSION_SECONDS,
    )
    unreachable = "postgresql://nobody@127.0.0.1:9/none?connect_timeout=1"
    client = _app_without_check(unreachable, spine_schema, tmp_path, guest)
    refused = _enter(client)
    assert refused.status_code == 503
    assert refused.json()["code"] == "guest_entry_unavailable"
    assert refused.headers["retry-after"] == "30"
    # A runtime with no guest entry refuses by its own class, which the route answers
    # guest_entry_off; it is never the database's failure above.
    from exulanica.api.account_runtime import GuestEntryOff

    runtime = client.app.state.services.accounts
    object.__setattr__(runtime, "guest", None)
    with pytest.raises(GuestEntryOff):
        runtime.enter_guest(SimpleNamespace(headers={}, cookies={}), None)


def _app_without_check(account_url, spine_schema, tmp_path, guest) -> TestClient:
    """A server whose account database is never reached at startup, for a failure at entry."""
    _, scratch = spine_schema
    database = scratch_database(scratch)
    runtime = AccountRuntime(None, account_url, None, guest)
    app = FastAPI()
    app.state.services = Services(
        database=database,
        readonly_database=database,
        store=LocalContentAddressedStore(tmp_path / "unreached-store"),
        tokens=TokenDirectory(sessions={}),
        executor_shares_the_write_role=True,
        model_client=None,
        accounts=runtime,
    )
    app.include_router(accounts.router)
    return TestClient(app, base_url=ORIGIN, follow_redirects=False)


def test_a_session_read_asks_again_at_most_once_a_minute(guest_app, monkeypatch):
    """Each ask for a missing allowance takes the authority's witness and state locks, which every
    admission takes, so a guest reading their session in a loop asks once a minute, not each time,
    and only for the providers they hold nothing from."""
    import dataclasses

    from exulanica.api.routes import accounts as routes

    class _Clock:
        now = 1_000.0

        def __call__(self) -> float:
            return self.now

    clock = _Clock()
    monkeypatch.setattr(routes, "_GRANT_RETRIES", routes._GrantRetries(clock=clock))
    client = guest_app(per_day=1_000_000)
    spending = _FailingSpending()
    client.app.state.services = dataclasses.replace(client.app.state.services, spending=spending)
    assert _enter(client).status_code == 201
    entered = len(spending.asked)
    for _ in range(5):
        assert client.get("/auth/session").status_code == 200
    assert len(spending.asked) == entered + 1
    clock.now += routes.GRANT_RETRY_SECONDS
    client.get("/auth/session")
    assert len(spending.asked) == entered + 2


@pytest.mark.parametrize("mode", ["off", "open", "code"])
def test_the_public_api_starts_in_every_entry_mode(mode, account_role, spine_schema, tmp_path):
    """The public overlay always gives the API the account database and the origin. With the entry
    off the server must still start, closed to new guests, so turning it off never takes the
    server down."""
    from exulanica.api.services import build_services

    _, scratch = spine_schema
    environ = {
        "EXULANICA_DATABASE_URL": scratch_database(scratch).url,
        "EXULANICA_DATA_DIR": str(tmp_path),
        "EXULANICA_DERIVATIVE_WORKER": "off",
        "EXULANICA_ACCOUNT_DATABASE_URL": account_role,
        "EXULANICA_ACCOUNT_BROWSER_ORIGINS": f'["{ORIGIN}"]',
        "EXULANICA_GUEST_ENTRY": mode,
        "EXULANICA_GUEST_PLAY_SECONDS": "120",
        "EXULANICA_GUEST_PLAYING_MAXIMUM": "3",
    }
    if mode != "off":
        environ["EXULANICA_GUEST_ENTRIES_PER_DAY"] = "10"
    if mode == "code":
        environ["EXULANICA_GUEST_ENTRY_CODE_SHA256"] = hashlib.sha256(CODE.encode()).hexdigest()
    services = build_services(environ)
    assert services.accounts is not None and services.accounts.guest is not None
    assert services.accounts.guest.mode == {"off": "closed"}.get(mode, mode)
    # A closed entry keeps the play window and maximum, so the guests inside play as before.
    assert (services.accounts.guest.play_seconds, services.accounts.guest.playing_maximum) == (
        120,
        3,
    )


def test_a_closed_entry_admits_nobody_new_and_keeps_the_guests_who_entered(
    guest_app, account_role, spine_schema, tmp_path
):
    import dataclasses

    client = guest_app(per_day=1_000_000)
    entered = _enter(client)
    assert entered.status_code == 201
    runtime = client.app.state.services.accounts
    closed = dataclasses.replace(runtime.guest, mode="closed", entries_per_day=0)
    object.__setattr__(runtime, "guest", closed)
    refused = _enter(client)
    assert refused.status_code == 503 and refused.json()["code"] == "guest_entry_off"
    session = client.get("/auth/session")
    assert session.status_code == 200 and session.json()["role"] == "guest"
