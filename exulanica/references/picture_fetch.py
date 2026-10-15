"""Fetching one picture a person picked from a picture search: the one network seam that reaches a
website nobody here chose.

The egress allowlist (:mod:`exulanica.models.egress`) names the few origins this process's model
transport may reach, and a picture lives on any website at all, so this seam is not held to it
(``docs/security-floor.md`` names it). It is held to its own rules instead, each refused by name:

*   **https only, a host by name.** The address is one a page may show
    (:func:`~exulanica.references.adapters.base.picture_address`): ``https``, a host name with a
    dot and no address literal, the default port, no user or password.
*   **A public address, and that one.** The name is resolved once, every address it resolves to
    must be public (not private, loopback, link-local, shared, multicast or reserved, an IPv4
    address mapped into IPv6 included), and the connection is made to the first of those, with
    the name as the TLS server name and the ``Host`` header, so a second lookup cannot point the
    connection elsewhere and the certificate is still checked against the name.
*   **At most :data:`MAX_REDIRECTS` redirects**, each held to every rule above again.
*   **At most :data:`MAX_PICTURE_BYTES`**, refused at a larger declared length and while reading.
*   **An image type a picture is kept in** (JPEG, PNG or WebP), by the answer's content type; the
    keeper decodes the bytes again before anything is kept.
*   **:data:`DEADLINE_SECONDS` in all**, redirects included.
*   **No proxy and no cookies**: the environment's proxy settings are ignored and nothing a website
    sets is sent back.

Nothing here writes anywhere or logs an address: a refusal states its code and never the address.
It is used only when a person keeps a picture they picked
(:mod:`exulanica.world.kept_web_pictures`), and only where picture searches are turned on.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from exulanica.errors import ExulanicaError
from exulanica.references.adapters.base import picture_address

__all__ = [
    "ACCEPTED_TYPES",
    "DEADLINE_SECONDS",
    "FETCH_REFUSALS",
    "MAX_PICTURE_BYTES",
    "MAX_REDIRECTS",
    "FetchedPicture",
    "PictureFetchRefused",
    "fetch_picture",
    "system_resolver",
]

#: The most bytes a picked picture may have.
MAX_PICTURE_BYTES: Final = 10 * 1024 * 1024
#: The most redirects one fetch follows.
MAX_REDIRECTS: Final = 3
#: The longest one fetch takes, redirects included.
DEADLINE_SECONDS: Final = 10.0
#: The content types a picture is fetched in.
ACCEPTED_TYPES: Final = ("image/jpeg", "image/png", "image/webp")
_REDIRECTS: Final = frozenset({301, 302, 303, 307, 308})
_HEADERS: Final = {
    "Accept": ", ".join(ACCEPTED_TYPES),
    "User-Agent": "Exulanica picture fetch",
}

#: Why a picture was not fetched, by code.
FETCH_REFUSALS: Final = {
    "picture_address_refused": "the picture's address is not an https address naming a host",
    "picture_host_not_public": "the picture's host is not reached at a public address",
    "picture_too_many_redirects": f"the picture is more than {MAX_REDIRECTS} redirects away",
    "picture_not_an_image": "the website did not answer with a JPEG, PNG or WebP picture",
    "picture_too_large": f"the picture is more than {MAX_PICTURE_BYTES} bytes",
    "picture_unreachable": "the website did not answer with the picture",
    "picture_timed_out": f"the picture was not fetched within {DEADLINE_SECONDS:g} seconds",
}

#: A host name's addresses, as text, in the order to try them.
Resolver = Callable[[str], Sequence[str]]


class PictureFetchRefused(ExulanicaError):
    """A picture not fetched, by code; never naming its address."""

    def __init__(self, code: str) -> None:
        if code not in FETCH_REFUSALS:
            raise ValueError(f"unknown fetch refusal {code!r}")
        super().__init__(f"{code}: {FETCH_REFUSALS[code]}")
        self.code = code


@dataclass(frozen=True, slots=True)
class FetchedPicture:
    """A fetched picture's bytes, the content type it was answered with, and how many redirects
    reached it."""

    data: bytes = field(repr=False)
    media_type: str
    redirects: int


def system_resolver(host: str) -> list[str]:
    """``host``'s addresses, as this machine's resolver answers them, each once."""
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(answer[4][0]) for answer in answers))


#: IPv6 ranges that carry or reach an IPv4 address by translation or tunnel, refused whole whatever
#: the IPv4 address they carry: Teredo, and the NAT64 prefixes, well-known and local-use. Named here
#: rather than left to ``is_global``, whose answer for them changed between Python versions.
_TRANSLATED: Final = (
    ipaddress.IPv6Network("2001::/32"),
    ipaddress.IPv6Network("64:ff9b::/96"),
    ipaddress.IPv6Network("64:ff9b:1::/48"),
)


def _public(text: str) -> bool:
    """Whether ``text`` is a public address: global, and not multicast or reserved. An IPv4 address
    mapped into IPv6, or carried in a 6to4 address, is judged as itself; a Teredo or NAT64 address
    is never public."""
    try:
        address = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if any(address in network for network in _TRANSLATED):
            return False
        carried = address.ipv4_mapped or address.sixtofour
        if carried is not None:
            address = carried
    return address.is_global and not address.is_multicast and not address.is_reserved


def _checked_address(host: str, resolver: Resolver) -> str:
    """The address to connect to for ``host``: the first it resolves to, once every one it
    resolves to is public."""
    try:
        addresses = list(resolver(host))
    except (OSError, UnicodeError) as exc:
        raise PictureFetchRefused("picture_host_not_public") from exc
    if not addresses or not all(_public(address) for address in addresses):
        raise PictureFetchRefused("picture_host_not_public")
    return addresses[0]


def fetch_picture(
    address: str,
    *,
    resolver: Resolver = system_resolver,
    transport: httpx.BaseTransport | None = None,
    clock: Callable[[], float] = time.monotonic,
    deadline_seconds: float = DEADLINE_SECONDS,
) -> FetchedPicture:
    """The picture at ``address``, under every rule of this module, or
    :class:`PictureFetchRefused`. ``resolver`` and ``transport`` stand in for the network in
    tests; the transport is httpx's own, with no retries, otherwise."""
    started = clock()
    current = address
    with httpx.Client(
        transport=transport if transport is not None else httpx.HTTPTransport(retries=0),
        trust_env=False,
        follow_redirects=False,
        headers=_HEADERS,
    ) as client:
        for redirects in range(MAX_REDIRECTS + 1):
            shown = picture_address(current)
            if shown is None:
                raise PictureFetchRefused("picture_address_refused")
            host = shown[1]
            connect_to = _checked_address(host, resolver)
            parts = urlsplit(current)
            literal = f"[{connect_to}]" if ":" in connect_to else connect_to
            target = urlunsplit(("https", literal, parts.path or "/", parts.query, ""))
            left = deadline_seconds - (clock() - started)
            if left <= 0:
                raise PictureFetchRefused("picture_timed_out")
            # Nothing a website set is sent to the next.
            client.cookies.clear()
            try:
                with client.stream(
                    "GET",
                    target,
                    headers={"Host": host},
                    extensions={"sni_hostname": host},
                    timeout=left,
                ) as response:
                    if response.status_code in _REDIRECTS:
                        location = response.headers.get("location")
                        if not location:
                            raise PictureFetchRefused("picture_unreachable")
                        current = urljoin(current, location)
                        continue
                    if response.status_code != 200:
                        raise PictureFetchRefused("picture_unreachable")
                    media_type = (
                        response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    )
                    if media_type not in ACCEPTED_TYPES:
                        raise PictureFetchRefused("picture_not_an_image")
                    declared = response.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > MAX_PICTURE_BYTES:
                        raise PictureFetchRefused("picture_too_large")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_PICTURE_BYTES:
                            raise PictureFetchRefused("picture_too_large")
                        if clock() - started > deadline_seconds:
                            raise PictureFetchRefused("picture_timed_out")
                    return FetchedPicture(bytes(body), media_type, redirects)
            except httpx.TimeoutException as exc:
                raise PictureFetchRefused("picture_timed_out") from exc
            except httpx.HTTPError as exc:
                raise PictureFetchRefused("picture_unreachable") from exc
    raise PictureFetchRefused("picture_too_many_redirects")
