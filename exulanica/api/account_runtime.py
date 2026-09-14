"""Google OIDC and revocable browser sessions; no provider tokens are retained.

The host configures a separate auth-role URL for the same deployment database/schema. Provider
HTTP runs outside database transactions. Every downstream workspace session is resolved from a
current account membership, never a callback or browser-supplied workspace identifier.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx2
import psycopg
from authlib.common.errors import AuthlibBaseError
from authlib.integrations.httpx_client import OAuth2Client
from authlib.oidc.core import CodeIDToken
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from psycopg.rows import dict_row
from starlette.requests import Request

from exulanica.api.account_repository import (
    ISSUER,
    AccountRejected,
    AccountRepository,
    AccountSession,
    AccountUnavailable,
)
from exulanica.api.authorisation import TokenNotAccepted
from exulanica.db.account_workspaces import (
    AccountWorkspaceSource,
    AccountWorkspaceUnavailable,
)
from exulanica.env import env_get
from exulanica.selection.validation import Session

SESSION_COOKIE = "__Host-exulanica-session"
LOGIN_COOKIE = "__Host-exulanica-login"
DISCOVERY_URI = "https://accounts.google.com/.well-known/openid-configuration"
_DATABASE_TIMEOUT_SECONDS = 5


def origin(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or "\\" in url
        or any(ord(c) < 33 for c in url)
    ):
        raise ValueError("account URLs require HTTPS without credentials/fragments")
    # Force validation of malformed ports, including overflow.
    _ = parsed.port
    return f"{parsed.scheme}://{parsed.netloc}"


@dataclass(frozen=True)
class GoogleAccountConfig:
    client_id: str
    client_secret: str = field(repr=False)
    callback_uri: str
    return_uris: tuple[str, ...]
    browser_origins: tuple[str, ...]
    issuer: str = ISSUER
    session_seconds: int = 8 * 60 * 60

    def __post_init__(self) -> None:
        if self.issuer != ISSUER or not self.client_id or not self.client_secret:
            raise ValueError("Google issuer/client configuration is required")
        if not self.return_uris or not self.browser_origins:
            raise ValueError("exact callback and browser redirect allowlists are required")
        for value in self.browser_origins:
            if origin(value) != value:
                raise ValueError("browser origins cannot contain a path or query")
        for value in self.return_uris:
            if origin(value) not in self.browser_origins:
                raise ValueError("return URI is outside the browser origin allowlist")
        if (
            urlsplit(self.callback_uri).path != "/auth/google/callback"
            or urlsplit(self.callback_uri).query
        ):
            raise ValueError("callback must be the exact /auth/google/callback HTTPS endpoint")
        origin(self.callback_uri)
        if type(self.session_seconds) is not int or not 60 <= self.session_seconds <= 86400:
            raise ValueError("session lifetime must be between one minute and one day")

    @property
    def fingerprint(self) -> str:
        # Client-secret rotation invalidates pending attempts without retaining the secret.
        value = [
            self.issuer,
            self.client_id,
            self.callback_uri,
            self.return_uris,
            self.browser_origins,
            hashlib.sha256(self.client_secret.encode()).hexdigest(),
        ]
        return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


class GoogleOIDCProvider:
    """Maintained OAuth/OIDC/JOSE libraries perform protocol and cryptographic validation.

    Injectable HTTP transport supports a signed fake provider, without a verification bypass.
    Discovery/JWKS addresses are pinned to Google's HTTPS authority, never token jku/x5u headers.
    """

    def __init__(
        self, config: GoogleAccountConfig, *, transport: httpx2.BaseTransport | None = None
    ) -> None:
        self.config, self.transport = config, transport
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def _json(self, url: str, *, refresh: bool = False) -> dict:
        with self._lock:
            cached = self._cache.get(url)
            if not refresh and cached and cached[0] > time.monotonic():
                return cached[1]
        try:
            with httpx2.Client(
                transport=self.transport, timeout=10, follow_redirects=False
            ) as client:
                response = client.get(url, headers={"Accept": "application/json"})
                response.raise_for_status()
                if len(response.content) > 1024 * 1024:
                    raise ValueError("OIDC document exceeds bound")
                value = response.json()
            if not isinstance(value, dict):
                raise ValueError("invalid OIDC document")
        except (httpx2.HTTPError, ValueError) as exc:
            raise AccountUnavailable("Google metadata is unavailable") from exc
        ttl = 0
        directives = response.headers.get("cache-control", "").lower().split(",")
        if not any(d.strip() in ("no-store", "no-cache") for d in directives):
            for directive in directives:
                if directive.strip().startswith("max-age="):
                    with suppress(ValueError):
                        ttl = max(0, min(300, int(directive.strip().split("=", 1)[1])))
        with self._lock:
            self._cache[url] = (time.monotonic() + ttl, value)
        return value

    def metadata(self) -> dict:
        value = self._json(DISCOVERY_URI)
        if (
            value.get("issuer") != self.config.issuer
            or "S256" not in value.get("code_challenge_methods_supported", [])
            or "RS256" not in value.get("id_token_signing_alg_values_supported", [])
        ):
            raise AccountUnavailable("Google OIDC metadata does not support the configured flow")
        expected = {
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_endpoint": "https://oauth2.googleapis.com/token",
            "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
        }
        if any(value.get(key) != url for key, url in expected.items()):
            raise AccountUnavailable("Google endpoint declaration changed; review configuration")
        return value

    def _client(self) -> OAuth2Client:
        return OAuth2Client(
            self.config.client_id,
            self.config.client_secret,
            scope="openid",
            redirect_uri=self.config.callback_uri,
            code_challenge_method="S256",
            token_endpoint_auth_method="client_secret_post",
            transport=self.transport,
            timeout=10,
            follow_redirects=False,
        )

    def authorization_url(self, *, state: str, nonce: str, verifier: str) -> str:
        metadata = self.metadata()
        with self._client() as client:
            url, _ = client.create_authorization_url(
                metadata["authorization_endpoint"],
                state=state,
                nonce=nonce,
                code_verifier=verifier,
                response_type="code",
            )
            return url

    def verify_code(self, code: str, attempt: dict) -> tuple[str, str]:
        if not code or len(code) > 4096:
            raise AccountRejected("invalid authorization code")
        metadata = self.metadata()
        try:
            with self._client() as client:
                token = client.fetch_token(
                    metadata["token_endpoint"],
                    grant_type="authorization_code",
                    code=code,
                    code_verifier=attempt["verifier"],
                )
            encoded = token.get("id_token")
            if not isinstance(encoded, str) or len(encoded) > 32768:
                raise AccountRejected("missing or oversized ID token")
            # A rotated key gets one fresh JWKS lookup; no key is selected from token URLs.
            for fresh in (False, True):
                keys = KeySet.import_key_set(self._json(metadata["jwks_uri"], refresh=fresh))
                try:
                    decoded = jwt.decode(encoded, keys, algorithms=["RS256"])
                    break
                except JoseError:
                    if fresh:
                        raise
            claims = CodeIDToken(
                decoded.claims,
                decoded.header,
                options={
                    "iss": {"essential": True, "values": [ISSUER, "accounts.google.com"]},
                    "aud": {"essential": True, "value": self.config.client_id},
                },
                params={
                    "nonce": attempt["nonce"],
                    "client_id": self.config.client_id,
                    "access_token": token.get("access_token"),
                },
            )
            claims.validate(leeway=0)
            subject = claims.get("sub")
            if not isinstance(subject, str) or not subject or len(subject) > 255:
                raise AccountRejected("invalid provider subject")
            return ISSUER, subject
        except AccountUnavailable:
            raise
        except (
            JoseError,
            AuthlibBaseError,
            ValueError,
            TypeError,
            KeyError,
            httpx2.HTTPError,
        ) as exc:
            raise AccountRejected("provider response was not accepted") from exc


@dataclass(frozen=True)
class AccountRuntime:
    config: GoogleAccountConfig
    database_url: str = field(repr=False)
    provider: GoogleOIDCProvider

    def __post_init__(self) -> None:
        if self.provider.config != self.config:
            raise ValueError("OIDC provider and account runtime must use the same configuration")

    @contextmanager
    def repository(self) -> Iterator[AccountRepository]:
        # Distinct dedicated auth connection, never a fake pre-auth workspace or app connection.
        try:
            with psycopg.connect(
                self.database_url,
                autocommit=True,
                row_factory=dict_row,
                connect_timeout=_DATABASE_TIMEOUT_SECONDS,
            ) as connection:
                connection.execute("set time zone 'UTC'")
                connection.execute(
                    "select set_config('statement_timeout', %s, false)",
                    (f"{_DATABASE_TIMEOUT_SECONDS}s",),
                )
                yield AccountRepository(connection)
        except psycopg.Error as exc:
            raise AccountUnavailable("account persistence is unavailable") from exc

    def verify_database(self, application_database_url: str) -> None:
        try:
            AccountWorkspaceSource(self.database_url, application_database_url).verify()
        except AccountWorkspaceUnavailable as exc:
            raise AccountUnavailable(str(exc)) from exc

    def active_owned_workspaces(self) -> frozenset[uuid.UUID]:
        """Resolve current worker scope through the account role, without retaining authority."""
        with self.repository() as repository:
            return repository.active_owned_workspaces()

    def start(self, return_uri: str | None = None) -> tuple[str, str]:
        target = return_uri or self.config.return_uris[0]
        if target not in self.config.return_uris:
            raise AccountRejected("unregistered return URI")
        state, browser, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
        url = self.provider.authorization_url(state=state, nonce=nonce, verifier=verifier)
        with self.repository() as repo:
            repo.begin_login(
                state=state,
                browser=browser,
                nonce=nonce,
                verifier=verifier,
                config_sha256=self.config.fingerprint,
                callback_uri=self.config.callback_uri,
                return_uri=target,
            )
        return url, browser

    def callback(
        self,
        *,
        state: str,
        browser: str,
        code: str,
        response_issuer: str | None = None,
        previous_token: str | None = None,
    ) -> tuple[str, str, AccountSession]:
        with self.repository() as repo:
            attempt = repo.claim_login(state, browser, self.config.fingerprint)
        try:
            if response_issuer is not None and response_issuer != self.config.issuer:
                raise AccountRejected("authorization response issuer mismatch")
            issuer, subject = self.provider.verify_code(code, attempt)
            with self.repository() as repo:
                token, session = repo.finish_login(
                    attempt,
                    issuer=issuer,
                    subject=subject,
                    session_seconds=self.config.session_seconds,
                    previous_token=previous_token,
                )
            return attempt["return_uri"], token, session
        except Exception:
            with self.repository() as repo:
                repo.fail_login(attempt["state_sha256"])
            raise

    def browser_session(self, request: Request) -> AccountSession:
        try:
            with self.repository() as repo:
                account = repo.session(request.cookies.get(SESSION_COOKIE))
            if request.method.upper() not in ("GET", "HEAD", "OPTIONS"):
                if request.headers.get("origin") not in self.config.browser_origins:
                    raise AccountRejected("untrusted request origin")
                supplied = request.headers.get("x-csrf-token", "")
                if not secrets.compare_digest(supplied.encode(), account.csrf_token.encode()):
                    raise AccountRejected("invalid CSRF token")
            return account
        except AccountRejected as exc:
            raise TokenNotAccepted("browser session was not accepted") from exc

    def authenticate_request(self, request: Request) -> Session:
        return self.browser_session(request).session

    def logout(self, request: Request) -> None:
        self.browser_session(request)
        with self.repository() as repo:
            repo.logout(request.cookies[SESSION_COOKIE])


def load_account_runtime(environ: Mapping[str, str]) -> AccountRuntime | None:
    """Absent configuration disables Google explicitly; partial configuration is a boot error."""
    names = (
        "EXULANICA_GOOGLE_CLIENT_ID",
        "EXULANICA_GOOGLE_CLIENT_SECRET",
        "EXULANICA_GOOGLE_CALLBACK_URI",
        "EXULANICA_GOOGLE_RETURN_URIS",
        "EXULANICA_ACCOUNT_BROWSER_ORIGINS",
        "EXULANICA_ACCOUNT_DATABASE_URL",
    )
    if not any(environ.get(name) for name in names):
        return None
    if not all(environ.get(name) for name in names):
        raise AccountUnavailable("Google account configuration is incomplete")
    try:
        returns = json.loads(environ[names[3]])
        origins = json.loads(environ[names[4]])
        if (
            not isinstance(returns, list)
            or not isinstance(origins, list)
            or not all(isinstance(v, str) for v in [*returns, *origins])
        ):
            raise ValueError("allowlists must be JSON string arrays")
        config = GoogleAccountConfig(
            client_id=environ[names[0]],
            client_secret=environ[names[1]],
            callback_uri=environ[names[2]],
            return_uris=tuple(returns),
            browser_origins=tuple(origins),
        )
    except (ValueError, TypeError) as exc:
        raise AccountUnavailable("Google account configuration is invalid") from exc
    runtime = AccountRuntime(config, environ[names[5]], GoogleOIDCProvider(config))
    application_url = env_get("DATABASE_URL", environ)
    if not application_url:
        raise AccountUnavailable(
            "application database configuration is required for account mapping"
        )
    runtime.verify_database(application_url)
    return runtime
