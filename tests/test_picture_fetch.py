"""Fetching a picked picture: every rule the seam holds, each refusal by name, on a fake resolver
and a fake network. Nothing here reaches a network."""

from __future__ import annotations

import httpx
import pytest
from exulanica.references.picture_fetch import (
    MAX_PICTURE_BYTES,
    MAX_REDIRECTS,
    PictureFetchRefused,
    fetch_picture,
)
from exulanica.world.kept_web_pictures import MAX_PICTURE_BYTES as KEPT_MAXIMUM

PUBLIC = "93.184.216.34"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _resolver(table: dict[str, list[str]]):
    asked: list[str] = []

    def resolve(host: str) -> list[str]:
        asked.append(host)
        return table[host]

    resolve.asked = asked  # type: ignore[attr-defined]
    return resolve


def _network(handler):
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.MockTransport(handle), seen


def _picture(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)


def _refused(code: str, address: str, **kwargs) -> None:
    with pytest.raises(PictureFetchRefused) as refused:
        fetch_picture(address, **kwargs)
    assert refused.value.code == code
    assert address not in str(refused.value)


def test_a_6to4_address_carrying_a_public_address_is_public() -> None:
    transport, seen = _network(_picture)
    fetch_picture(
        "https://pictures.example/duck.png",
        resolver=_resolver({"pictures.example": ["2002:5db8:d822::1"]}),
        transport=transport,
    )
    [request] = seen
    assert request.url.host == "2002:5db8:d822::1"


def test_a_picture_is_fetched_from_the_checked_address_under_its_own_name() -> None:
    transport, seen = _network(_picture)
    fetched = fetch_picture(
        "https://pictures.example/a/duck.png?size=large",
        resolver=_resolver({"pictures.example": [PUBLIC]}),
        transport=transport,
    )
    assert (fetched.data, fetched.media_type, fetched.redirects) == (PNG, "image/png", 0)
    [request] = seen
    # The connection goes to the address that was checked; the name is the TLS server name and
    # the Host header, so the certificate is checked against the name.
    assert request.url.host == PUBLIC and request.url.scheme == "https"
    assert request.url.path == "/a/duck.png" and request.url.query == b"size=large"
    assert request.headers["host"] == "pictures.example"
    assert request.extensions["sni_hostname"] == "pictures.example"
    assert "cookie" not in request.headers


@pytest.mark.parametrize(
    "addresses",
    [
        ["10.0.0.5"],
        ["127.0.0.1"],
        ["169.254.169.254"],
        ["100.64.0.1"],
        ["::1"],
        ["fd00::1"],
        ["::ffff:192.168.1.4"],
        # A 6to4 address carrying 10.0.0.1, a Teredo address and the NAT64 prefixes.
        ["2002:0a00:0001::1"],
        ["2001:0:4136:e378:8000:63bf:3fff:fdd2"],
        ["64:ff9b::a00:1"],
        ["64:ff9b::5db8:d822"],
        ["64:ff9b:1::a00:1"],
        [PUBLIC, "192.168.1.4"],
        [],
    ],
)
def test_a_host_that_is_not_reached_at_a_public_address_is_refused(addresses) -> None:
    transport, seen = _network(_picture)
    _refused(
        "picture_host_not_public",
        "https://pictures.example/duck.png",
        resolver=_resolver({"pictures.example": addresses}),
        transport=transport,
    )
    assert seen == []


@pytest.mark.parametrize(
    "address",
    [
        "http://pictures.example/duck.png",
        "https://10.0.0.5/duck.png",
        "https://someone:secret@pictures.example/duck.png",
        "https://pictures.example:8443/duck.png",
        "https://localhost/duck.png",
    ],
)
def test_an_address_that_is_not_https_naming_a_host_is_refused_before_any_lookup(address) -> None:
    resolver = _resolver({})
    transport, seen = _network(_picture)
    _refused("picture_address_refused", address, resolver=resolver, transport=transport)
    assert resolver.asked == [] and seen == []


def test_a_redirect_to_a_private_address_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://inside.example/secret.png"})

    transport, seen = _network(handler)
    _refused(
        "picture_host_not_public",
        "https://pictures.example/duck.png",
        resolver=_resolver({"pictures.example": [PUBLIC], "inside.example": ["192.168.1.4"]}),
        transport=transport,
    )
    assert len(seen) == 1


def test_a_redirect_to_plain_http_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"location": "http://pictures.example/duck.png"})

    transport, _ = _network(handler)
    _refused(
        "picture_address_refused",
        "https://pictures.example/duck.png",
        resolver=_resolver({"pictures.example": [PUBLIC]}),
        transport=transport,
    )


def test_redirects_are_followed_and_checked_again_up_to_three_with_no_cookie_sent_on() -> None:
    hops = iter(range(1, 10))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/final.png":
            return _picture(request)
        hop = next(hops)
        target = "/final.png" if hop == MAX_REDIRECTS else f"/hop-{hop}.png"
        return httpx.Response(
            302, headers={"location": target, "set-cookie": f"tracker=hop{hop}; Path=/"}
        )

    transport, seen = _network(handler)
    fetched = fetch_picture(
        "https://pictures.example/duck.png",
        resolver=_resolver({"pictures.example": [PUBLIC]}),
        transport=transport,
    )
    assert fetched.redirects == MAX_REDIRECTS
    assert all("cookie" not in request.headers for request in seen)


def test_more_than_three_redirects_are_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again.png"})

    transport, seen = _network(handler)
    _refused(
        "picture_too_many_redirects",
        "https://pictures.example/duck.png",
        resolver=_resolver({"pictures.example": [PUBLIC]}),
        transport=transport,
    )
    assert len(seen) == MAX_REDIRECTS + 1


@pytest.mark.parametrize(
    "content_type", ["text/html", "image/svg+xml", "image/gif", "application/octet-stream", ""]
)
def test_an_answer_that_is_not_a_kept_image_type_is_refused(content_type) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": content_type}, content=b"<html/>")

    transport, _ = _network(handler)
    _refused(
        "picture_not_an_image",
        "https://pictures.example/duck.png",
        resolver=_resolver({"pictures.example": [PUBLIC]}),
        transport=transport,
    )


def test_an_oversize_body_is_refused_by_its_declared_length_and_while_reading() -> None:
    assert MAX_PICTURE_BYTES == KEPT_MAXIMUM

    def declared(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "image/png", "content-length": str(MAX_PICTURE_BYTES + 1)},
            content=b"",
        )

    def streamed(request: httpx.Request) -> httpx.Response:
        chunks = (b"\x00" * 1024 * 1024 for _ in range(11))
        return httpx.Response(200, headers={"content-type": "image/png"}, content=chunks)

    for handler in (declared, streamed):
        transport, _ = _network(handler)
        _refused(
            "picture_too_large",
            "https://pictures.example/duck.png",
            resolver=_resolver({"pictures.example": [PUBLIC]}),
            transport=transport,
        )


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        (httpx.ConnectError("refused"), "picture_unreachable"),
        (httpx.ReadTimeout("slow"), "picture_timed_out"),
    ],
)
def test_a_network_failure_is_refused_by_name(raised, code) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise raised

    transport, _ = _network(handler)
    _refused(
        code,
        "https://pictures.example/duck.png",
        resolver=_resolver({"pictures.example": [PUBLIC]}),
        transport=transport,
    )


def test_an_answer_other_than_ok_is_refused() -> None:
    transport, _ = _network(lambda request: httpx.Response(404))
    _refused(
        "picture_unreachable",
        "https://pictures.example/duck.png",
        resolver=_resolver({"pictures.example": [PUBLIC]}),
        transport=transport,
    )


def test_the_whole_fetch_is_held_to_its_deadline() -> None:
    times = iter([0.0, 11.0])
    transport, seen = _network(_picture)
    _refused(
        "picture_timed_out",
        "https://pictures.example/duck.png",
        resolver=_resolver({"pictures.example": [PUBLIC]}),
        transport=transport,
        clock=lambda: next(times),
    )
    assert seen == []
