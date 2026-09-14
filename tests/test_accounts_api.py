"""Browser OIDC/session boundary on actual PostgreSQL and signed fake provider responses."""

import concurrent.futures
import dataclasses
import secrets
import time
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from exulanica.api.account_repository import AccountRejected, secret_digest
from exulanica.api.account_runtime import (
    LOGIN_COOKIE,
    SESSION_COOKIE,
    AccountRuntime,
    load_account_runtime,
)
from fastapi.testclient import TestClient

from account_fixtures import account_api as account_api
from account_fixtures import account_role as account_role

pytestmark = pytest.mark.postgres


def test_sign_in_reopen_csrf_logout_and_server_owned_scope(account_api):
    api = account_api
    assert api.client.get("/auth/session").status_code == 401
    account = api.login()
    assert set(account) == {"user_id", "actor", "workspace_id", "expires_at", "csrf_token"}
    cookie = api.client.cookies.get(SESSION_COOKIE)
    assert cookie and cookie not in str(account)
    with TestClient(
        api.client.app, base_url="https://app.test", follow_redirects=False
    ) as reopened:
        reopened.cookies.set(SESSION_COOKIE, cookie, domain="app.test", path="/")
        assert reopened.get("/auth/session").json() == account
        assert reopened.get("/protected").json()["workspace_id"] == account["workspace_id"]
    assert api.client.post("/protected").status_code == 401
    assert (
        api.client.post(
            "/protected",
            headers={"Origin": "https://evil.test", "X-CSRF-Token": account["csrf_token"]},
        ).status_code
        == 401
    )
    assert (
        api.client.post(
            "/protected", headers={"Origin": "https://app.test", "X-CSRF-Token": "wrong"}
        ).status_code
        == 401
    )
    headers = {"Origin": "https://app.test", "X-CSRF-Token": account["csrf_token"]}
    assert (
        api.client.post(
            "/protected", headers=headers, json={"workspace_id": str(uuid.uuid4())}
        ).json()["workspace_id"]
        == account["workspace_id"]
    )
    response = api.client.post("/auth/logout", headers=headers)
    assert response.status_code == 200
    assert (
        "Secure" in response.headers["set-cookie"] and "HttpOnly" in response.headers["set-cookie"]
    )
    api.client.cookies.set(SESSION_COOKIE, cookie, domain="app.test", path="/")
    assert api.client.get("/auth/session").status_code == 401


def test_cookie_rotation_same_identity_and_no_email_linking(account_api):
    api = account_api
    first = api.login()
    old = api.client.cookies.get(SESSION_COOKIE)
    api.fake.overrides = {"email": "same@example.invalid", "email_verified": True}
    again = api.login()
    assert (again["user_id"], again["actor"], again["workspace_id"]) == (
        first["user_id"],
        first["actor"],
        first["workspace_id"],
    )
    with api.runtime.repository() as repo, pytest.raises(AccountRejected):
        repo.session(old)
    other = api.login("unrelated-google-subject")
    assert other["user_id"] != first["user_id"] and other["workspace_id"] != first["workspace_id"]
    with api.runtime.repository() as repo:
        assert (
            repo.connection.execute("select count(*) n from account_identity").fetchone()["n"] == 2
        )
        columns = repo.connection.execute(
            "select column_name from information_schema.columns "
            "where table_schema=current_schema() and table_name='account_user'"
        ).fetchall()
        assert not {"email", "name", "picture"}.intersection(r["column_name"] for r in columns)


@pytest.mark.parametrize(
    "case",
    [
        "state",
        "browser",
        "replay",
        "nonce",
        "issuer",
        "audience",
        "azp",
        "signature",
        "expired",
        "missing",
        "future",
        "unsigned",
        "hmac",
    ],
)
def test_forged_or_replayed_login_is_refused(account_api, case):
    api = account_api
    start = api.client.get("/auth/google/start")
    assert start.status_code == 303
    assert "HttpOnly" in start.headers["set-cookie"] and "Secure" in start.headers["set-cookie"]
    callback = api.fake.issue(start.headers["location"])
    if case == "state":
        callback = callback.replace("state=", "state=wrong")
    if case == "browser":
        api.client.cookies.clear()
    if case == "nonce":
        api.fake.overrides = {"nonce": "wrong"}
    if case == "issuer":
        api.fake.overrides = {"iss": "https://evil.test"}
    if case == "audience":
        api.fake.overrides = {"aud": "other-client"}
    if case == "azp":
        api.fake.overrides = {"azp": "other-client"}
    if case == "signature":
        api.fake.bad_signature = True
    if case == "expired":
        api.fake.overrides = {"exp": int(time.time()) - 1}
    if case == "future":
        api.fake.overrides = {"iat": int(time.time()) + 3600}
    if case == "missing":
        api.fake.omit = {"exp"}
    if case == "unsigned":
        api.fake.token_kind = "none"
    if case == "hmac":
        api.fake.token_kind = "HS256"
    if case == "replay":
        assert api.client.get(callback).status_code == 303
    response = api.client.get(callback)
    assert response.status_code == 401, response.text
    assert "no-store" in response.headers["cache-control"]
    with api.runtime.repository() as repo:
        count = repo.connection.execute("select count(*) n from account_user").fetchone()["n"]
        assert count == (1 if case == "replay" else 0)


def test_callback_commits_claim_before_provider_exchange_and_rejects_parallel_replay(account_api):
    api = account_api
    start = api.client.get("/auth/google/start")
    params = parse_qs(urlsplit(api.fake.issue(start.headers["location"])).query)
    state, code = params["state"][0], params["code"][0]
    browser = api.client.cookies.get(LOGIN_COOKIE)

    def during_exchange():
        with api.runtime.repository() as repo:
            row = repo.connection.execute(
                "select outcome,nonce,verifier from account_login_attempt where state_sha256=%s",
                (secret_digest(state),),
            ).fetchone()
            assert row == {"outcome": "claimed", "nonce": None, "verifier": None}

    api.fake.before_exchange = during_exchange

    def callback(_):
        try:
            return api.runtime.callback(state=state, browser=browser, code=code)[2].user_id
        except AccountRejected:
            return "rejected"

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(callback, range(2)))
    assert result.count("rejected") == 1
    assert sum(method == "POST" for method, _ in api.fake.calls) == 1


def test_parallel_distinct_logins_create_one_identity_and_workspace(account_api):
    api = account_api
    attempts = []
    for _ in range(2):
        url, browser = api.runtime.start()
        callback = api.fake.issue(url)
        params = parse_qs(urlsplit(callback).query)
        attempts.append(dict(state=params["state"][0], browser=browser, code=params["code"][0]))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda attempt: api.runtime.callback(**attempt)[2], attempts))
    assert results[0].user_id == results[1].user_id
    assert results[0].session == results[1].session
    with api.runtime.repository() as repo:
        for table in (
            "account_user",
            "account_workspace",
            "account_membership",
            "account_identity",
        ):
            assert repo.connection.execute(f"select count(*) n from {table}").fetchone()["n"] == 1


def test_stale_configuration_and_expired_attempt_refuse_before_exchange(account_api):
    api = account_api
    url, browser = api.runtime.start()
    params = parse_qs(urlsplit(api.fake.issue(url)).query)
    replacement = dataclasses.replace(api.runtime.config, client_secret="rotated-secret")
    with pytest.raises(ValueError):
        AccountRuntime(replacement, api.runtime.database_url, api.runtime.provider)
    changed = AccountRuntime(
        replacement,
        api.runtime.database_url,
        type(api.runtime.provider)(replacement, transport=api.runtime.provider.transport),
    )
    with pytest.raises(AccountRejected):
        changed.callback(state=params["state"][0], browser=browser, code=params["code"][0])
    expired = secrets.token_urlsafe(32)
    with api.runtime.repository() as repo:
        repo.connection.execute(
            "insert into account_login_attempt(state_sha256,browser_sha256,config_sha256,"
            "nonce,verifier,callback_uri,return_uri,created_at,expires_at) "
            "values(%s,%s,%s,%s,%s,%s,%s,now()-interval '20 minutes',"
            "now()-interval '10 minutes')",
            (
                secret_digest(expired),
                secret_digest(browser),
                api.runtime.config.fingerprint,
                expired,
                expired,
                api.runtime.config.callback_uri,
                api.runtime.config.return_uris[0],
            ),
        )
    with pytest.raises(AccountRejected):
        api.runtime.callback(state=expired, browser=browser, code="stale")
    assert not any(method == "POST" for method, _ in api.fake.calls)


def test_disabled_account_and_membership_refuse_use_without_rebinding_actor(account_api):
    api = account_api
    account = api.login()
    with api.runtime.repository() as repo:
        repo.disable_account(uuid.UUID(account["user_id"]))
    assert api.client.get("/auth/session").status_code == 401
    start = api.client.get("/auth/google/start")
    assert api.client.get(api.fake.issue(start.headers["location"])).status_code == 401
    with api.runtime.repository() as repo:
        assert (
            str(repo.connection.execute("select actor_id from account_user").fetchone()["actor_id"])
            == account["actor"]
        )
    new = api.login("another-subject")
    with api.runtime.repository() as repo:
        repo.connection.execute(
            "update account_membership set revoked_at=now() where user_id=%s", (new["user_id"],)
        )
    assert api.client.get("/auth/session").status_code == 401


def test_worker_workspace_discovery_tracks_owner_authority_not_browser_sessions(account_api):
    api = account_api
    first = api.login("worker-owner-one")
    first_token = api.client.cookies.get(SESSION_COOKIE)
    first_workspace = uuid.UUID(first["workspace_id"])
    assert api.runtime.active_owned_workspaces() == frozenset({first_workspace})

    # Logout revokes one browser credential, not the underlying account-owned workspace.
    with api.runtime.repository() as repo:
        repo.logout(first_token)
    assert api.runtime.active_owned_workspaces() == frozenset({first_workspace})

    second = api.login("worker-owner-two")
    second_workspace = uuid.UUID(second["workspace_id"])
    assert api.runtime.active_owned_workspaces() == frozenset({first_workspace, second_workspace})

    with api.runtime.repository() as repo:
        repo.connection.execute(
            "update account_membership set revoked_at=now() where user_id=%s",
            (first["user_id"],),
        )
        repo.connection.execute(
            "update account_workspace set disabled_at=now() where workspace_id=%s",
            (second_workspace,),
        )
    assert api.runtime.active_owned_workspaces() == frozenset()


def test_session_expiry_is_database_authority(account_api):
    api = account_api
    api.login()
    token = api.client.cookies.get(SESSION_COOKIE)
    # New test login receipt permits an explicitly backdated session without editing history.
    state = secrets.token_urlsafe(32)
    browser = secrets.token_urlsafe(32)
    expired = secrets.token_urlsafe(32)
    with api.runtime.repository() as repo:
        repo.begin_login(
            state=state,
            browser=browser,
            nonce=state,
            verifier=state,
            config_sha256=api.runtime.config.fingerprint,
            callback_uri=api.runtime.config.callback_uri,
            return_uri=api.runtime.config.return_uris[0],
        )
        repo.connection.execute(
            "insert into account_browser_session(session_sha256,user_id,workspace_id,csrf_token,"
            "login_state_sha256,created_at,expires_at) select %s,user_id,workspace_id,csrf_token,"
            "%s,now()-interval '2 hours',now()-interval '1 hour' "
            "from account_browser_session where session_sha256=%s",
            (secret_digest(expired), secret_digest(state), secret_digest(token)),
        )
        with pytest.raises(AccountRejected):
            repo.session(expired)


def test_configuration_is_explicit_and_redirects_are_not_browser_authority(account_api):
    api = account_api
    assert load_account_runtime({}) is None
    from exulanica.api.account_repository import AccountUnavailable

    with pytest.raises(AccountUnavailable):
        load_account_runtime({"EXULANICA_GOOGLE_CLIENT_ID": "x"})
    assert api.client.get("/auth/google/start?return_uri=https://evil.test").status_code == 401
    for bad in (
        "http://app.test/auth/google/callback",
        "https://app.test@evil.test/auth/google/callback",
        "https://app.test/auth/google/callback?target=elsewhere",
    ):
        with pytest.raises(ValueError):
            dataclasses.replace(api.runtime.config, callback_uri=bad)
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services, accounts=None
    )
    assert api.client.get("/auth/google/start").status_code == 503


def test_provider_error_consumes_attempt_and_unknown_session_is_refused(account_api):
    api = account_api
    start = api.client.get("/auth/google/start")
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    browser = api.client.cookies.get(LOGIN_COOKIE)
    assert (
        api.client.get(
            "/auth/google/callback", params={"state": state, "error": "access_denied"}
        ).status_code
        == 401
    )
    with api.runtime.repository() as repo:
        row = repo.connection.execute(
            "select outcome,nonce,verifier from account_login_attempt where state_sha256=%s",
            (secret_digest(state),),
        ).fetchone()
        assert row == {"outcome": "failed", "nonce": None, "verifier": None}
    with pytest.raises(AccountRejected):
        api.runtime.callback(state=state, browser=browser, code="reuse")
    api.client.cookies.set(SESSION_COOKIE, secrets.token_urlsafe(32), domain="app.test", path="/")
    assert api.client.get("/auth/session").status_code == 401


def test_provider_workspace_claims_are_ignored_and_foreign_csrf_is_rejected(account_api):
    api = account_api
    foreign_workspace, foreign_actor = uuid.uuid4(), uuid.uuid4()
    api.fake.overrides = {"workspace_id": str(foreign_workspace), "actor": str(foreign_actor)}
    first = api.login()
    assert first["workspace_id"] != str(foreign_workspace) and first["actor"] != str(foreign_actor)
    second = api.login("separate-subject")
    assert (
        api.client.post(
            "/protected",
            headers={"Origin": "https://app.test", "X-CSRF-Token": first["csrf_token"]},
        ).status_code
        == 401
    )
    assert (
        api.client.post(
            "/protected",
            headers={"Origin": "https://app.test", "X-CSRF-Token": second["csrf_token"]},
        ).status_code
        == 200
    )


def test_key_rotation_refreshes_jwks_without_accepting_token_key_urls(account_api):
    from joserfc.jwk import RSAKey

    api = account_api
    first = api.login()
    api.fake.key = RSAKey.generate_key(2048, parameters={"kid": "rotated-test-key"})
    again = api.login()
    assert again["user_id"] == first["user_id"]
    assert sum(url.endswith("/certs") for _, url in api.fake.calls) == 2


def test_identity_membership_and_session_bindings_are_immutable(account_api):
    import psycopg

    api = account_api
    api.login()
    for statement in (
        "update account_user set actor_id=gen_random_uuid()",
        "update account_identity set subject=subject || '-replacement'",
        "update account_workspace set owner_user_id=gen_random_uuid()",
        "update account_membership set user_id=gen_random_uuid()",
        "update account_browser_session set workspace_id=gen_random_uuid()",
    ):
        with (
            api.runtime.repository() as repo,
            pytest.raises(psycopg.errors.CheckViolation),
            repo.connection.transaction(),
        ):
            repo.connection.execute(statement)


def test_secret_cleanup_and_deployment_validation(account_api, spine_schema):
    from exulanica.api.account_repository import AccountUnavailable

    from tests_support_api import scratch_database

    api = account_api
    config = api.runtime.config
    env = {
        "EXULANICA_GOOGLE_CLIENT_ID": config.client_id,
        "EXULANICA_GOOGLE_CLIENT_SECRET": config.client_secret,
        "EXULANICA_GOOGLE_CALLBACK_URI": config.callback_uri,
        "EXULANICA_GOOGLE_RETURN_URIS": '["https://app.test/world"]',
        "EXULANICA_ACCOUNT_BROWSER_ORIGINS": '["https://app.test"]',
        "EXULANICA_ACCOUNT_DATABASE_URL": api.runtime.database_url,
        "EXULANICA_DATABASE_URL": scratch_database(spine_schema[1]).url,
    }
    assert load_account_runtime(env) is not None
    with pytest.raises(AccountUnavailable):
        api.runtime.verify_database("postgresql://localhost:5433/wrong_test_database")
    with pytest.raises(AccountUnavailable):
        load_account_runtime(
            {**env, "EXULANICA_ACCOUNT_DATABASE_URL": env["EXULANICA_DATABASE_URL"]}
        )
    state = secrets.token_urlsafe(32)
    with api.runtime.repository() as repo:
        repo.connection.execute(
            "insert into account_login_attempt(state_sha256,browser_sha256,config_sha256,"
            "nonce,verifier,callback_uri,return_uri,created_at,expires_at) "
            "values(%s,%s,%s,%s,%s,%s,%s,now()-interval '20 minutes',"
            "now()-interval '10 minutes')",
            (
                secret_digest(state),
                secret_digest(state),
                config.fingerprint,
                state,
                state,
                config.callback_uri,
                config.return_uris[0],
            ),
        )
    api.runtime.start()
    with api.runtime.repository() as repo:
        row = repo.connection.execute(
            "select outcome,nonce,verifier from account_login_attempt where state_sha256=%s",
            (secret_digest(state),),
        ).fetchone()
        assert row == {"outcome": "expired", "nonce": None, "verifier": None}


@pytest.mark.parametrize("authorization", ["", "Basic ignored", "Bearer invalid-token-value"])
def test_explicit_invalid_bearer_cannot_fall_back_to_browser_cookie(account_api, authorization):
    account_api.login()
    assert account_api.client.get("/protected").status_code == 200
    response = account_api.client.get("/protected", headers={"Authorization": authorization})
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


def test_readiness_reports_account_store_outage_without_leaking_connection(account_api):
    api = account_api
    assert api.client.get("/readyz").json()["checks"]["accounts"]["ok"] is True
    broken = dataclasses.replace(
        api.runtime, database_url="postgresql://no_secret@localhost:1/unavailable"
    )
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services, accounts=broken
    )
    response = api.client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"]["accounts"]["ok"] is False
    assert "no_secret" not in response.text
