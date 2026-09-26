"""The egress allowlist: declared, strict, held at the transport seam, refused before a socket.

``docs/privacy-consent-threat-model.md`` asserts that egress from the inference path is
allowlisted and ``docs/evaluation-methodology.md`` scores threat F1 as "Egress blocked by
allowlist; URL inert; alert". These tests are what those sentences now rest on, and
``docs/security-floor.md`` says what they do not cover.

The socket half patches the functions httpcore actually opens connections through, and proves the
patch is live by letting a *listed* host reach it. Without that second half, "no socket was
opened" would also be true of a patch that intercepted nothing.
"""

from __future__ import annotations

import json
import logging
import pathlib
import re
import socket
from typing import Any

import httpx
import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.chain import ModelChain
from exulanica.models.client import ModelClient
from exulanica.models.egress import (
    EGRESS_ALLOWLIST_ENV,
    EgressAllowlist,
    EgressConfigurationError,
    EgressRefused,
    Origin,
    load_egress_allowlist,
    parse_egress_allowlist,
)
from exulanica.models.errors import TransportError
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.preflight import fetch_catalog
from exulanica.models.transport import HttpxTransport, allowlisted_httpx_client

from model_fakes import FakeTransport

ROOT = pathlib.Path(__file__).resolve().parents[1]
LISTED = "https://api.example.com"
ALLOWLIST = parse_egress_allowlist(
    [LISTED, "https://api.example.com:8443", "http://localhost:8000"]
)


def _env(*origins: str) -> dict[str, str]:
    return {EGRESS_ALLOWLIST_ENV: json.dumps(list(origins))}


# -- loading ------------------------------------------------------------------------------


@pytest.mark.parametrize("environ", [{}, {EGRESS_ALLOWLIST_ENV: ""}])
def test_an_absent_allowlist_is_refused_rather_than_defaulted(environ):
    with pytest.raises(EgressConfigurationError, match="no default"):
        load_egress_allowlist(environ)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("not json", "not valid JSON"),
        ('{"https://api.example.com": true}', "JSON array"),
        ('"https://api.example.com"', "JSON array"),
        ("[]", "declares no origin"),
        ("[1]", "not an origin string"),
        ('[""]', "not an origin string"),
    ],
)
def test_a_malformed_allowlist_is_refused_at_load(raw, message):
    with pytest.raises(EgressConfigurationError, match=re.escape(message)):
        load_egress_allowlist({EGRESS_ALLOWLIST_ENV: raw})


@pytest.mark.parametrize(
    "entry",
    [
        "https://127.0.0.1",
        "https://[::1]",
        "https://[::1]:443",
        "https://2130706433",
        "https://0x7f.1",
        "https://127.1",
        "https://api.example.com.",
        "https://*.example.com",
        "https://user@api.example.com",
        "https://api.example.com@evil.example",
        "https://api.example.com/v1",
        "https://api.example.com?x=1",
        "https://api.example.com?",
        "https://api.example.com#top",
        "ftp://api.example.com",
        "api.example.com",
        "http://api.example.com",
        "https://API.example.com",
        "https://api",
        "https://api.example.com:99999",
        "https://api.example.com:0",
        "https://bücher.example",
        "https://api.example .com",
        "https://api.example.com\\@evil.example",
        "https://-api.example.com",
        "https://api_x.example.com",
    ],
)
def test_an_entry_that_is_not_a_plain_origin_is_refused(entry):
    with pytest.raises(EgressConfigurationError):
        parse_egress_allowlist([entry])


def test_the_same_origin_twice_is_refused_however_it_is_spelt():
    with pytest.raises(EgressConfigurationError, match="declared twice"):
        parse_egress_allowlist(["https://api.example.com", "https://api.example.com:443/"])


def test_a_plain_origin_loads():
    allowlist = load_egress_allowlist(_env(LISTED, "https://api.example.com:8443"))
    assert allowlist.origins == {
        Origin("https", "api.example.com", 443),
        Origin("https", "api.example.com", 8443),
    }
    assert str(allowlist) == "https://api.example.com, https://api.example.com:8443"


# -- matching -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com/v1/chat/completions",
        "https://api.example.com:443/v1/models",
        "https://API.Example.COM/v1",
        "https://api.example.com:8443/v1",
        "http://localhost:8000/v1",
    ],
)
def test_a_declared_origin_is_permitted(url):
    assert ALLOWLIST.permits(url)


@pytest.mark.parametrize(
    ("url", "why"),
    [
        # a differing port, including the other scheme's default
        ("https://api.example.com:9443/v1", "not declared"),
        ("http://api.example.com/v1", "not declared"),
        ("http://localhost:8001/v1", "not declared"),
        ("https://localhost:8000/v1", "not declared"),
        # a userinfo prefix, in both directions
        ("https://api.example.com@evil.example/v1", "userinfo"),
        ("https://user:secret@api.example.com/v1", "userinfo"),
        ("https://api.example.com:443@evil.example/v1", "userinfo"),
        # a trailing-dot host
        ("https://api.example.com./v1", "trailing-dot"),
        # IP literals, in every spelling a resolver accepts
        ("https://93.184.216.34/v1", "address"),
        ("https://[2606:2800:220:1::1]/v1", "address"),
        ("https://[::ffff:93.184.216.34]/v1", "address"),
        ("https://2130706433/v1", "address"),
        ("https://0x7f000001/v1", "address"),
        ("https://127.1/v1", "address"),
        ("https://0177.0.0.1/v1", "address"),
        # a subdomain of a listed host, and a listed host as a subdomain
        ("https://evil.api.example.com/v1", "not declared"),
        ("https://api.example.com.evil.example/v1", "not declared"),
        ("https://xapi.example.com/v1", "not declared"),
        ("https://example.com/v1", "not declared"),
        # parser-differential bait
        ("https://api.example.com\\@evil.example/v1", "backslash"),
        ("https://api.example.com%2F@evil.example/v1", "userinfo"),
        ("https://api%2eexample.com/v1", "not declared"),
        ("https://api.example.com /v1", "whitespace"),
        ("https://api.example.com\t/v1", "whitespace"),
        ("https://bücher.example/v1", "non-ASCII"),
        ("https:///v1", "no host"),
        ("https://api.example.com:notaport/v1", "port"),
        ("ftp://api.example.com/v1", "scheme"),
        ("file:///etc/passwd", "no host"),
    ],
)
def test_an_undeclared_destination_is_refused(url, why):
    with pytest.raises(EgressRefused, match=re.escape(why)) as refused:
        ALLOWLIST.require(url)
    # The refusal originates in the allowlist module, not in a local copy of it.
    assert type(refused.value).__module__ == "exulanica.models.egress"
    assert not isinstance(refused.value, TransportError)


def test_a_refusal_is_logged_as_an_alert(caplog):
    with caplog.at_level(logging.WARNING, logger="exulanica.models.egress"):
        assert not ALLOWLIST.permits("https://evil.example/exfiltrate")
    assert any("evil.example" in record.getMessage() for record in caplog.records)


def test_an_empty_allowlist_cannot_be_built_by_hand():
    with pytest.raises(EgressConfigurationError):
        EgressAllowlist(frozenset())


# -- no socket is opened ------------------------------------------------------------------


class _SocketsRecorded(Exception):
    """Raised by the patched connection functions so a test can see a connection was attempted."""


@pytest.fixture
def sockets(monkeypatch) -> list[tuple[str, Any]]:
    opened: list[tuple[str, Any]] = []

    def create_connection(address, *args, **kwargs):
        opened.append(("create_connection", address))
        raise _SocketsRecorded(address)

    def getaddrinfo(host, *args, **kwargs):
        opened.append(("getaddrinfo", host))
        raise _SocketsRecorded(host)

    def connect(self, address):
        opened.append(("connect", address))
        raise _SocketsRecorded(address)

    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", connect)
    return opened


@pytest.fixture
def real_transport(monkeypatch) -> HttpxTransport:
    monkeypatch.setenv(EGRESS_ALLOWLIST_ENV, json.dumps([LISTED]))
    transport = HttpxTransport()
    yield transport
    transport.close()


def test_the_socket_patch_is_live_for_a_listed_host(real_transport, sockets):
    """The guard on the guard: a listed host does reach the connection layer."""
    with pytest.raises(TransportError):
        real_transport.get_json(f"{LISTED}/v1/models", headers={}, timeout=1.0)
    assert sockets and sockets[0][0] == "create_connection"
    assert sockets[0][1][0] == "api.example.com"


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/v1/chat/completions",
        "https://api.example.com:8443/v1/chat/completions",
        "https://api.example.com@evil.example/v1/chat/completions",
        "https://api.example.com./v1/chat/completions",
        "https://93.184.216.34/v1/chat/completions",
        "https://evil.api.example.com/v1/chat/completions",
    ],
)
def test_an_unlisted_host_is_refused_before_any_socket_is_opened(real_transport, sockets, url):
    with pytest.raises(EgressRefused):
        real_transport.post_json(url, headers={}, payload={}, timeout=1.0)
    with pytest.raises(EgressRefused):
        real_transport.get_json(url, headers={}, timeout=1.0)
    assert sockets == []


def test_the_client_inside_the_transport_refuses_on_its_own(sockets):
    """The mounted check, reached without the pre-call check in front of it."""
    client = allowlisted_httpx_client(ALLOWLIST)
    with pytest.raises(EgressRefused):
        client.get("https://evil.example/v1/models")
    assert sockets == []
    client.close()


# -- redirects ----------------------------------------------------------------------------


def _redirecting(location: str, seen: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": location})

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/steal",
        "https://api.example.com:9443/v1/models",
        "https://api.example.com@evil.example/v1",
        "http://api.example.com/v1/models",
        "https://93.184.216.34/v1/models",
    ],
)
def test_a_redirect_hop_is_held_to_the_allowlist_even_if_redirects_were_followed(location):
    seen: list[str] = []
    client = allowlisted_httpx_client(
        ALLOWLIST, inner=_redirecting(location, seen), follow_redirects=True
    )
    transport = HttpxTransport(client=client, egress=ALLOWLIST)
    with pytest.raises(EgressRefused):
        transport.get_json(f"{LISTED}/v1/models", headers={}, timeout=1.0)
    # The listed request was made; the hop it pointed at was not.
    assert seen == [f"{LISTED}/v1/models"]


def test_redirects_are_not_followed_by_the_transport_that_ships():
    seen: list[str] = []
    transport = HttpxTransport(
        client=allowlisted_httpx_client(
            ALLOWLIST, inner=_redirecting("https://evil.example/", seen)
        ),
        egress=ALLOWLIST,
    )
    response = transport.get_json(f"{LISTED}/v1/models", headers={}, timeout=1.0)
    assert response.status_code == 302
    assert seen == [f"{LISTED}/v1/models"]


def test_the_built_client_ignores_environment_proxies(monkeypatch):
    """A proxy the environment names is a destination the allowlist does not."""
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.evil.example:3128")
    with httpx.Client() as plain:
        # The guard on the guard: an ordinary client does pick the variable up.
        assert plain._mounts, "httpx no longer reads HTTPS_PROXY, so this test proves nothing"
    client = allowlisted_httpx_client(ALLOWLIST)
    assert client._mounts == {}
    client.close()


# -- the seam -----------------------------------------------------------------------------


def test_the_real_transport_will_not_build_without_an_allowlist(monkeypatch):
    monkeypatch.delenv(EGRESS_ALLOWLIST_ENV, raising=False)
    with pytest.raises(EgressConfigurationError, match="no default"):
        HttpxTransport()


def test_an_injected_network_client_needs_an_allowlist_too():
    with httpx.Client() as client, pytest.raises(EgressConfigurationError):
        HttpxTransport(client=client)


def test_a_refusal_is_never_retried_or_failed_over():
    """Not a TransportError, so the chain's retry and fallback never see it."""
    transport = FakeTransport([EgressRefused("refused"), EgressRefused("refused")])
    manifest = load_manifest()
    chain = ModelChain(
        manifest=manifest,
        transport=transport,
        api_keys={provider: "test-key-not-real" for provider in manifest.providers},
        budget=BudgetGuard(),
        timeout=1.0,
        max_attempts=3,
        sleep=lambda _seconds: None,
    )
    with pytest.raises(EgressRefused):
        chain.walk(
            Role.REASONING_CHEAP,
            "/chat/completions",
            {"messages": []},
            prompt_chars=0,
            extra_prompt_tokens=0,
            max_tokens=1,
        )
    assert transport.call_count == 1


def test_the_model_client_checks_its_endpoint_at_construction(monkeypatch, sockets):
    manifest = load_manifest()
    endpoint = manifest.provider(manifest[Role.REASONING_CHEAP].provider)
    monkeypatch.setenv(EGRESS_ALLOWLIST_ENV, json.dumps(["https://elsewhere.example"]))
    with pytest.raises(EgressConfigurationError, match=re.escape(endpoint.base_url)):
        ModelClient(api_key="test-key-not-real")
    monkeypatch.delenv(EGRESS_ALLOWLIST_ENV)
    with pytest.raises(EgressConfigurationError, match="no default"):
        ModelClient(api_key="test-key-not-real")
    monkeypatch.setenv(EGRESS_ALLOWLIST_ENV, json.dumps(model_origins()))
    client = ModelClient(api_key="test-key-not-real")
    assert dict(client.refusals) == {}
    # Construction opened nothing.
    assert sockets == []


def test_a_model_client_over_a_test_double_needs_no_allowlist(monkeypatch):
    monkeypatch.delenv(EGRESS_ALLOWLIST_ENV, raising=False)
    ModelClient(api_key="test-key-not-real", transport=FakeTransport())


def test_the_catalog_fetch_is_held_to_the_allowlist_too(monkeypatch, sockets):
    """The preflight builds its own transport, and the catalog is on a different host."""
    manifest = load_manifest()
    provider = manifest.provider(manifest[Role.VISION].provider)
    monkeypatch.setenv(EGRESS_ALLOWLIST_ENV, json.dumps([provider.origin]))
    with pytest.raises(EgressRefused):
        fetch_catalog(provider.catalog_url)
    assert sockets == []


# -- what the allowlist does not cover, kept true -----------------------------------------

#: Modules that reach the network and hold every request to the allowlist, through
#: ``allowlisted_transport``. Each is checked for that wiring below.
COVERED_NETWORK_MODULES = {
    "exulanica/models/transport.py",
    "exulanica/api/account_runtime.py",
}

#: Modules that reach the network without the allowlist. docs/security-floor.md names them as
#: uncovered; a new one fails here so the document cannot quietly become wrong.
UNCOVERED_NETWORK_MODULES = {
    "exulanica/environment/nyc_open_data.py",
    "exulanica/environment/owned_district.py",
    "exulanica/evaluation/benchmark.py",
}

#: ``httpx2`` is named as well as ``httpx``: the sign-in path uses it, and a pattern that knew
#: only the first spelling passed while that path reached Google unchecked.
_NETWORK = re.compile(
    r"\burlopen\(|\bhttpx2?\.(?:Client|AsyncClient|get|post|put|request|stream)\(|"
    r"^\s*import (?:requests|aiohttp|urllib3)\b|\bsocket\.create_connection\(|"
    r"\bOAuth2Client\(",
    re.MULTILINE,
)


def test_every_network_module_is_either_held_to_the_allowlist_or_named_as_not():
    found = set()
    for path in sorted((ROOT / "exulanica").rglob("*.py")):
        if _NETWORK.search(path.read_text(encoding="utf-8")):
            found.add(path.relative_to(ROOT).as_posix())
    assert found - COVERED_NETWORK_MODULES == UNCOVERED_NETWORK_MODULES
    assert found >= COVERED_NETWORK_MODULES
    for relative in COVERED_NETWORK_MODULES:
        assert "allowlisted_transport(" in (ROOT / relative).read_text(encoding="utf-8"), relative


def test_nothing_in_the_package_hands_the_transport_its_own_client():
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "exulanica").rglob("*.py")
        if re.search(r"HttpxTransport\(\s*client\s*=", path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


# -- the deployment sees it -----------------------------------------------------------------


def _deployment_environ(tmp_path, **extra: str) -> dict[str, str]:
    return {
        "EXULANICA_DATABASE_URL": "postgresql://localhost:5433/never-connected-to",
        "EXULANICA_DATA_DIR": str(tmp_path),
        "EXULANICA_DERIVATIVE_WORKER": "off",
        "EXULANICA_API_TOKENS": json.dumps(
            {
                "a-token-long-enough-to-be-accepted-here": {
                    "workspace_id": "00000000-0000-0000-0000-000000000001",
                    "actor": "00000000-0000-0000-0000-000000000002",
                    "permissions": ["library.read"],
                }
            }
        ),
        **extra,
    }


def test_readiness_reports_whether_the_allowlist_is_set_and_never_its_value():
    """Fails if the name is dropped from ``describe_configuration`` in exulanica/api/services.py,
    which would hide the one control the threat model claimed long before it existed."""
    from exulanica.api.services import describe_configuration

    assert describe_configuration({})[EGRESS_ALLOWLIST_ENV] == "missing"
    reported = describe_configuration({EGRESS_ALLOWLIST_ENV: json.dumps([LISTED])})
    assert reported[EGRESS_ALLOWLIST_ENV] == "set"
    assert LISTED not in json.dumps(reported)


def test_a_deployment_with_a_model_key_and_no_allowlist_does_not_start(tmp_path, sockets):
    from exulanica.api.services import build_services

    environ = _deployment_environ(tmp_path, NEBIUS_API_KEY="test-key-not-real")
    with pytest.MonkeyPatch.context() as patch:
        for name, value in environ.items():
            patch.setenv(name, value)
        patch.delenv(EGRESS_ALLOWLIST_ENV, raising=False)
        with pytest.raises(EgressConfigurationError, match="no default"):
            build_services(environ)
        patch.setenv(EGRESS_ALLOWLIST_ENV, json.dumps(["https://elsewhere.example"]))
        with pytest.raises(EgressConfigurationError, match="not declared"):
            build_services(environ)
        patch.setenv(EGRESS_ALLOWLIST_ENV, json.dumps(model_origins()))
        services = build_services(environ)
    assert services.model_client is not None
    assert sockets == []


# -- Google sign-in ---------------------------------------------------------------------------

from exulanica.api import account_runtime as _accounts  # noqa: E402
from exulanica.api.account_repository import AccountUnavailable  # noqa: E402
from exulanica.api.account_runtime import (  # noqa: E402
    GOOGLE_EGRESS_ORIGINS,
    GoogleAccountConfig,
    GoogleOIDCProvider,
    load_account_runtime,
)

from account_fixtures import account_api as account_api  # noqa: E402
from account_fixtures import account_role as account_role  # noqa: E402
from account_fixtures import model_origins, production_shaped_allowlist  # noqa: E402

_CONFIG = GoogleAccountConfig(
    client_id="test-google-client",
    client_secret="test-only-client-secret",
    callback_uri="https://app.test/auth/google/callback",
    return_uris=("https://app.test/world",),
    browser_origins=("https://app.test",),
)


def _model_origin() -> str:
    """The one model origin these sign-in tests name beside Google's."""
    (origin,) = model_origins()
    return origin


def test_sign_in_needs_the_list_to_include_the_google_origins_among_others():
    """Includes, not equals: the ordinary list also names the model endpoint."""
    shared = production_shaped_allowlist()
    assert parse_egress_allowlist(model_origins()).origins <= shared.origins
    narrowed = shared.narrowed_to(GOOGLE_EGRESS_ORIGINS, purpose="Google sign-in")
    assert {str(origin) for origin in narrowed.origins} == set(GOOGLE_EGRESS_ORIGINS)

    only_model = parse_egress_allowlist([_model_origin()])
    with pytest.raises(EgressConfigurationError) as refused:
        only_model.narrowed_to(GOOGLE_EGRESS_ORIGINS, purpose="Google sign-in")
    message = str(refused.value)
    assert "must include" in message and "alongside any other origins" in message
    assert all(origin in message.split("does not include")[1] for origin in GOOGLE_EGRESS_ORIGINS)

    missing_jwks = parse_egress_allowlist([_model_origin(), *GOOGLE_EGRESS_ORIGINS[:2]])
    with pytest.raises(EgressConfigurationError) as refused:
        missing_jwks.narrowed_to(GOOGLE_EGRESS_ORIGINS, purpose="Google sign-in")
    assert refused.value.args[0].split("does not include")[1].strip() == (
        "https://www.googleapis.com."
    )


def _sign_in_environ(**extra: str) -> dict[str, str]:
    return {
        "EXULANICA_GOOGLE_CLIENT_ID": _CONFIG.client_id,
        "EXULANICA_GOOGLE_CLIENT_SECRET": _CONFIG.client_secret,
        "EXULANICA_GOOGLE_CALLBACK_URI": _CONFIG.callback_uri,
        "EXULANICA_GOOGLE_RETURN_URIS": '["https://app.test/world"]',
        "EXULANICA_ACCOUNT_BROWSER_ORIGINS": '["https://app.test"]',
        "EXULANICA_ACCOUNT_DATABASE_URL": "postgresql://localhost:5433/never-connected-to",
        **extra,
    }


def test_a_deployment_with_sign_in_and_no_google_origins_does_not_start(sockets):
    with pytest.raises(EgressConfigurationError, match="no default"):
        load_account_runtime(_sign_in_environ())
    with pytest.raises(EgressConfigurationError, match="must include"):
        load_account_runtime(
            _sign_in_environ(EXULANICA_EGRESS_ALLOWLIST=json.dumps([_model_origin()]))
        )
    assert sockets == []


def test_a_provider_with_nothing_declared_refuses_at_its_first_call_and_not_before(sockets):
    provider = GoogleOIDCProvider(_CONFIG)
    with pytest.raises(AccountUnavailable, match="EXULANICA_EGRESS_ALLOWLIST"):
        provider.metadata()
    assert sockets == []


def _fake_google(seen: list[str]) -> httpx.MockTransport:
    import httpx2

    def handle(request):
        seen.append(str(request.url))
        return httpx2.Response(500)

    return httpx2.MockTransport(handle)


def test_an_undeclared_sign_in_host_is_refused_before_a_socket_and_named(
    monkeypatch, sockets, caplog
):
    seen: list[str] = []
    provider = GoogleOIDCProvider(
        _CONFIG, transport=_fake_google(seen), egress=production_shaped_allowlist()
    )
    monkeypatch.setattr(
        _accounts, "DISCOVERY_URI", "https://accounts.google.com.evil.example/openid"
    )
    with caplog.at_level(logging.WARNING, logger="exulanica.models.egress"):
        with pytest.raises(AccountUnavailable):
            provider.metadata()
        # The model endpoint is declared in the shared list and is still not reachable from here.
        with pytest.raises(AccountUnavailable):
            provider._json(f"{_model_origin()}/v1/models")
    assert seen == []
    assert sockets == []
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "https://accounts.google.com.evil.example" in logged
    assert _model_origin() in logged


@pytest.mark.postgres
def test_sign_in_still_resolves_through_the_declared_origins(account_api):
    provider = account_api.runtime.provider
    assert {str(origin) for origin in provider.egress.origins} == set(GOOGLE_EGRESS_ORIGINS)
    session = account_api.login()
    assert session["workspace_id"] and session["actor"]
    reached = {url.split("/", 3)[2] for _method, url in account_api.fake.calls}
    assert reached == {"accounts.google.com", "oauth2.googleapis.com", "www.googleapis.com"}
    assert account_api.client.get("/protected").status_code == 200


@pytest.mark.postgres
def test_sign_in_fails_closed_when_discovery_points_somewhere_undeclared(
    account_api, monkeypatch, caplog
):
    before = list(account_api.fake.calls)
    provider = account_api.runtime.provider
    monkeypatch.setattr(provider, "_cache", {})
    monkeypatch.setattr(_accounts, "DISCOVERY_URI", "https://discovery.evil.example/openid")
    with caplog.at_level(logging.WARNING, logger="exulanica.models.egress"):
        response = account_api.client.get("/auth/google/start")
    assert (response.status_code, response.json()["code"]) == (503, "account_unavailable")
    assert account_api.fake.calls == before
    assert "https://discovery.evil.example" in " ".join(r.getMessage() for r in caplog.records)


@pytest.mark.postgres
def test_the_production_shaped_list_starts_sign_in(account_api, spine_schema):
    from tests_support_api import scratch_database

    environ = _sign_in_environ(
        EXULANICA_ACCOUNT_DATABASE_URL=account_api.runtime.database_url,
        EXULANICA_DATABASE_URL=scratch_database(spine_schema[1]).url,
        EXULANICA_EGRESS_ALLOWLIST=json.dumps([_model_origin(), *GOOGLE_EGRESS_ORIGINS]),
    )
    runtime = load_account_runtime(environ)
    assert runtime is not None
    assert {str(o) for o in runtime.provider.egress.origins} == set(GOOGLE_EGRESS_ORIGINS)
