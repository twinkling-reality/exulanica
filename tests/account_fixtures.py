"""Real signed OIDC responses over a fake transport, never a live Google credential."""

import secrets
import time
import uuid
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx2
import pytest
from exulanica.api import permissions
from exulanica.api.account_runtime import (
    GOOGLE_EGRESS_ORIGINS,
    AccountRuntime,
    GoogleAccountConfig,
    GoogleOIDCProvider,
)
from exulanica.api.authorisation import TokenDirectory, TokenNotAccepted
from exulanica.api.dependencies import current_session
from exulanica.api.routes import accounts, health
from exulanica.api.services import Services
from exulanica.models.egress import parse_egress_allowlist
from exulanica.models.manifest import load_manifest
from exulanica.selection.validation import Session
from exulanica.store.local import LocalContentAddressedStore
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey

from tests_support_api import scratch_database


class FakeGoogle:
    def __init__(self):
        self.key = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
        self.codes = {}
        self.calls = []
        self.overrides = {}
        self.bad_signature = False
        self.token_kind = "RS256"
        self.extra_headers = {}
        self.omit = set()
        self.before_exchange = None

    def issue(self, location, *, subject="google-subject-one"):
        query = parse_qs(urlsplit(location).query)
        assert query["code_challenge_method"] == ["S256"]
        assert query["scope"] == ["openid"]
        code = uuid.uuid4().hex
        self.codes[code] = (query, subject)
        return "/auth/google/callback?" + urlencode(
            {"code": code, "state": query["state"][0], "iss": "https://accounts.google.com"}
        )

    def handle(self, request):
        self.calls.append((request.method, str(request.url)))
        url = str(request.url)
        if url == "https://accounts.google.com/.well-known/openid-configuration":
            return httpx2.Response(
                200,
                json={
                    "issuer": "https://accounts.google.com",
                    "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_endpoint": "https://oauth2.googleapis.com/token",
                    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
                    "code_challenge_methods_supported": ["S256"],
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
                headers={"cache-control": "max-age=300"},
            )
        if url == "https://www.googleapis.com/oauth2/v3/certs":
            return httpx2.Response(
                200,
                json={"keys": [self.key.as_dict(private=False)]},
                headers={"cache-control": "max-age=300"},
            )
        assert url == "https://oauth2.googleapis.com/token"
        data = parse_qs(request.content.decode())
        if self.before_exchange:
            self.before_exchange()
        code = data.get("code", [""])[0]
        if code not in self.codes:
            return httpx2.Response(400, json={"error": "invalid_grant"})
        query, subject = self.codes.pop(code)
        from authlib.oauth2.rfc7636 import create_s256_code_challenge

        assert create_s256_code_challenge(data["code_verifier"][0]) == query["code_challenge"][0]
        assert data["redirect_uri"] == query["redirect_uri"]
        assert data["client_id"] == query["client_id"]
        claims = {
            "iss": "https://accounts.google.com",
            "sub": subject,
            "aud": "test-google-client",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
            "nonce": query["nonce"][0],
        }
        claims.update(self.overrides)
        for name in self.omit:
            claims.pop(name, None)
        key = RSAKey.generate_key(2048) if self.bad_signature else self.key
        if self.token_kind == "none":
            import base64
            import json

            def encode(value):
                return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

            encoded = encode({"alg": "none"}) + "." + encode(claims) + "."
        elif self.token_kind == "HS256":
            from joserfc.jwk import OctKey

            encoded = jwt.encode({"alg": "HS256"}, claims, OctKey.generate_key(256))
        else:
            encoded = jwt.encode(
                {"alg": "RS256", "kid": self.key.kid, **self.extra_headers}, claims, key
            )

        return httpx2.Response(
            200,
            json={
                "access_token": "synthetic-provider-access-token",
                "token_type": "Bearer",
                "expires_in": 600,
                "id_token": encoded,
            },
        )


def production_shaped_allowlist():
    """The model endpoint and the three sign-in origins, as one deployment declares them."""
    scheme, _, host, _ = load_manifest().base_url.split("/", 3)
    return parse_egress_allowlist([f"{scheme}//{host}", *GOOGLE_EGRESS_ORIGINS])


@dataclass
class AccountApi:
    client: TestClient
    runtime: AccountRuntime
    fake: FakeGoogle

    def login(self, subject="google-subject-one"):
        start = self.client.get("/auth/google/start")
        assert start.status_code == 303, start.text
        callback = self.fake.issue(start.headers["location"], subject=subject)
        response = self.client.get(callback)
        assert response.status_code == 303, response.text
        return self.client.get("/auth/session").json()


@pytest.fixture
def account_api(repository, spine_schema, account_role, tmp_path):
    _, scratch = spine_schema
    database = scratch_database(scratch)
    config = GoogleAccountConfig(
        client_id="test-google-client",
        client_secret="test-only-client-secret",
        callback_uri="https://app.test/auth/google/callback",
        return_uris=("https://app.test/world",),
        browser_origins=("https://app.test",),
    )
    fake = FakeGoogle()
    # Every provider request passes the same allowlist a deployment declares, in front of the fake.
    runtime = AccountRuntime(
        config,
        account_role,
        GoogleOIDCProvider(
            config,
            transport=httpx2.MockTransport(fake.handle),
            egress=production_shaped_allowlist(),
        ),
    )
    runtime.verify_database(database.url)
    app = FastAPI()
    app.state.services = Services(
        database=database,
        readonly_database=database,
        store=LocalContentAddressedStore(tmp_path / "account-store"),
        tokens=TokenDirectory(sessions={}),
        executor_shares_the_write_role=True,
        model_client=None,
        accounts=runtime,
    )
    app.include_router(health.router)
    app.include_router(accounts.router)

    @app.exception_handler(TokenNotAccepted)
    async def unauthenticated(_request: Request, exc: TokenNotAccepted) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"code": "unauthenticated", "detail": str(exc)},
            headers={"Cache-Control": "private, no-store"},
        )

    @app.get("/protected")
    @app.post("/protected")
    def protected(session: Annotated[Session, Depends(current_session)]):
        with database.session(session.workspace_id) as connection:
            current = connection.execute("select current_workspace() workspace_id").fetchone()
            return {"actor": str(session.actor), "workspace_id": str(current["workspace_id"])}

    declared = {
        **permissions.ROUTE_RULES,
        ("GET", "/protected"): permissions.Requires(
            frozenset({permissions.Permission.LIBRARY_READ})
        ),
        ("POST", "/protected"): permissions.Requires(
            frozenset({permissions.Permission.LIBRARY_WRITE})
        ),
    }
    with (
        pytest.MonkeyPatch.context() as patch,
        TestClient(app, base_url="https://app.test", follow_redirects=False) as client,
    ):
        patch.setattr(permissions, "ROUTE_RULES", MappingProxyType(declared))
        yield AccountApi(client, runtime, fake)


@pytest.fixture(scope="session")
def account_role(spine_schema):
    from exulanica.db.account_roles import provision_account_role
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from psycopg.rows import dict_row

    from pg_harness import open_scratch_connection

    psycopg_module, scratch = spine_schema
    role = "accounts_test_" + uuid.uuid4().hex[:16]
    password = secrets.token_urlsafe(32)
    admin = open_scratch_connection(psycopg_module, scratch)
    admin.row_factory = dict_row
    try:
        provision_account_role(admin, role=role, password=password)
        admin.commit()
        values = conninfo_to_dict(scratch_database(scratch).url)
        values.update(user=role, password=password)
        yield make_conninfo(**values)
    finally:
        admin.rollback()
        if admin.execute("select 1 from pg_roles where rolname=%s", (role,)).fetchone():
            admin.execute(sql.SQL("drop owned by {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("drop role {}").format(sql.Identifier(role)))
        admin.commit()
        admin.close()
