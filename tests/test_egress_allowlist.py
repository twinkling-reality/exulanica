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
        api_key="test-key-not-real",
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
    monkeypatch.setenv(EGRESS_ALLOWLIST_ENV, json.dumps(["https://elsewhere.example"]))
    with pytest.raises(EgressConfigurationError, match=re.escape(manifest.base_url)):
        ModelClient(api_key="test-key-not-real")
    monkeypatch.delenv(EGRESS_ALLOWLIST_ENV)
    with pytest.raises(EgressConfigurationError, match="no default"):
        ModelClient(api_key="test-key-not-real")
    origin = manifest.base_url.split("/", 3)
    monkeypatch.setenv(EGRESS_ALLOWLIST_ENV, json.dumps([f"{origin[0]}//{origin[2]}"]))
    client = ModelClient(api_key="test-key-not-real")
    assert client.manifest.base_url == manifest.base_url
    # Construction opened nothing.
    assert sockets == []


def test_a_model_client_over_a_test_double_needs_no_allowlist(monkeypatch):
    monkeypatch.delenv(EGRESS_ALLOWLIST_ENV, raising=False)
    ModelClient(api_key="test-key-not-real", transport=FakeTransport())


def test_the_catalog_fetch_is_held_to_the_allowlist_too(monkeypatch, sockets):
    """The preflight builds its own transport, and the catalog is on a different host."""
    manifest = load_manifest()
    origin = manifest.base_url.split("/", 3)
    monkeypatch.setenv(EGRESS_ALLOWLIST_ENV, json.dumps([f"{origin[0]}//{origin[2]}"]))
    with pytest.raises(EgressRefused):
        fetch_catalog(manifest.catalog_url)
    assert sockets == []


# -- what the allowlist does not cover, kept true -----------------------------------------

#: Modules that reach the network without this transport. docs/security-floor.md names them as
#: uncovered; a new one fails here so the document cannot quietly become wrong.
UNCOVERED_NETWORK_MODULES = {
    "exulanica/environment/nyc_open_data.py",
    "exulanica/environment/owned_district.py",
    "exulanica/evaluation/benchmark.py",
}

_NETWORK = re.compile(
    r"\burlopen\(|\bhttpx\.(?:Client|AsyncClient|get|post|put|request|stream)\(|"
    r"^\s*import (?:requests|aiohttp|urllib3)\b|\bsocket\.create_connection\(",
    re.MULTILINE,
)


def test_the_list_of_uncovered_network_modules_is_complete():
    found = set()
    for path in sorted((ROOT / "exulanica").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if relative == "exulanica/models/transport.py":
            continue
        if _NETWORK.search(path.read_text(encoding="utf-8")):
            found.add(relative)
    assert found == UNCOVERED_NETWORK_MODULES


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
        endpoint = load_manifest().base_url.split("/", 3)
        patch.setenv(EGRESS_ALLOWLIST_ENV, json.dumps(["https://elsewhere.example"]))
        with pytest.raises(EgressConfigurationError, match="not declared"):
            build_services(environ)
        patch.setenv(EGRESS_ALLOWLIST_ENV, json.dumps([f"{endpoint[0]}//{endpoint[2]}"]))
        services = build_services(environ)
    assert services.model_client is not None
    assert sockets == []
