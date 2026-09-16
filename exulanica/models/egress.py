"""The declared egress allowlist: the only origins this process's model transport may reach.

``docs/privacy-consent-threat-model.md`` has said since it was written that "network egress from
the inference and answer path is allowlisted", and until this module nothing in the code made
that true. This is what makes it true, and it is exactly as strong as the sentences below say
and no stronger.

**What it is.** A set of origins, each a scheme, a DNS host name and a port, read from
``EXULANICA_EGRESS_ALLOWLIST`` and validated when it loads.
:class:`exulanica.models.transport.HttpxTransport` refuses to build its network client without
one, checks every URL against it before the client is called, and mounts a transport inside that
client which checks every request again at the last point before a connection is opened, so a
redirect hop is held to the same rule as the first request.
:class:`exulanica.models.client.ModelClient` checks the manifest's ``base_url`` against it at
construction, so a deployment whose allowlist does not name its own model endpoint fails at
startup rather than at the first question.

**No default.** An absent or malformed allowlist raises, for the reason
:func:`exulanica.api.authorisation.load_token_directory` raises: a default allowlist would be a
permitted destination committed to a repository.

**Matching is exact and deliberately unclever.** A request is permitted only when its scheme,
host and port equal one declared origin. There is no suffix matching, so a subdomain of a listed
host is a different host. A port that differs, including the other scheme's default, is a
different origin. A URL carrying userinfo is refused whatever its host, because ``user@host``
is the classic place where two parsers disagree about which half is the host. A host with a
trailing dot is refused rather than normalised, because normalising is a second parser. An IP
literal is refused in the allowlist and in a request, including the shorthand forms the C
resolver accepts, because the allowlist names hosts and an address is not one. Whitespace, a
backslash or any non-ASCII character anywhere in a URL is refused, since an internationalised
host must arrive already in its ASCII form. Plain ``http`` is accepted only for ``localhost``,
because a bearer credential over plain HTTP is readable at every hop.

**What it is not.** It is a development and deployment safety rail, described as one, and it is
not a substitute for the network's own limit. It governs the one HTTP seam the model client uses
and nothing else in the process: a module that opens its own socket, calls ``urllib`` or builds
its own ``httpx.Client`` is not covered, and three of those exist outside the model path today.
It checks the name, not the address the name resolves to, so a listed host whose DNS answer
changes reaches wherever the answer points. It does not stop a compromised process, which can
simply not call it. Environment proxy settings are ignored by the client it builds, because a
proxy named by the environment is a destination this list does not name; an egress proxy belongs
at the network. ``docs/security-floor.md`` states the same limits for an operator.

**A refusal is final.** :class:`EgressRefused` is not a
:class:`~exulanica.models.errors.TransportError`, so the chain neither retries it nor fails over on
it, and it is logged as a warning before it is raised, which is the alert threat F1 scores.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import socket
import urllib.parse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, NoReturn

from exulanica.env import env_get, env_name
from exulanica.models.errors import ModelError

__all__ = [
    "EGRESS_ALLOWLIST_ENV",
    "EgressAllowlist",
    "EgressConfigurationError",
    "EgressError",
    "EgressRefused",
    "Origin",
    "load_egress_allowlist",
    "parse_egress_allowlist",
]

#: A JSON array of origins, for example ``["https://api.tokenfactory.nebius.com"]``.
EGRESS_ALLOWLIST_ENV: Final = env_name("EGRESS_ALLOWLIST")

_DEFAULT_PORTS: Final = {"https": 443, "http": 80}
_LABEL: Final = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_UNSAFE: Final = re.compile(r"[\s\\\x00-\x1f\x7f]")
_PLAIN_HTTP_HOSTS: Final = frozenset({"localhost"})

_log = logging.getLogger(__name__)


class EgressError(ModelError):
    """Base class for the allowlist's refusals."""


class EgressConfigurationError(EgressError, ValueError):
    """The allowlist is absent, malformed, or does not name what this deployment must reach."""


class EgressRefused(EgressError):
    """A request named an origin the allowlist does not declare, so it was never sent.

    Never retry it and never fail over on it. The destination will be just as undeclared on the
    next attempt, and a retry loop against a refusal is traffic this module exists to stop.
    """


def _is_ip_literal(host: str) -> bool:
    """Whether ``host`` is an address in any spelling a resolver would accept as one.

    ``inet_aton`` is pure parsing and opens nothing. It is what accepts ``127.1``, ``0x7f.1``
    and ``2130706433``, which ``ipaddress`` rejects and which ``getaddrinfo`` resolves to an
    address anyway. The last clause covers the rest of that family: no top-level domain is all
    digits or a hex number, so a name ending in one is an address being spelt as a name.
    """
    if ":" in host or host.startswith("["):
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return True
    try:
        socket.inet_aton(host)
    except (OSError, ValueError):
        pass
    else:
        return True
    last = host.rsplit(".", 1)[-1]
    return last.isdigit() or bool(re.fullmatch(r"0x[0-9a-f]*", last))


def _valid_host_name(host: str) -> bool:
    if not host or len(host) > 253 or host != host.lower() or host.endswith("."):
        return False
    labels = host.split(".")
    if len(labels) == 1 and host not in _PLAIN_HTTP_HOSTS:
        # A single label is completed by the platform's search domains, which this cannot see.
        return False
    return all(_LABEL.match(label) for label in labels)


@dataclass(frozen=True, slots=True, order=True)
class Origin:
    """A scheme, a host name and a port. Nothing narrower and nothing wider."""

    scheme: str
    host: str
    port: int

    def __str__(self) -> str:
        if self.port == _DEFAULT_PORTS[self.scheme]:
            return f"{self.scheme}://{self.host}"
        return f"{self.scheme}://{self.host}:{self.port}"


def _parse_origin(entry: object) -> Origin:
    """One allowlist entry, or ``EgressConfigurationError`` saying what is wrong with it."""
    if not isinstance(entry, str) or not entry:
        raise EgressConfigurationError(f"{EGRESS_ALLOWLIST_ENV}: {entry!r} is not an origin string")
    if _UNSAFE.search(entry) or not entry.isascii():
        raise EgressConfigurationError(
            f"{EGRESS_ALLOWLIST_ENV}: {entry!r} carries whitespace, a backslash, a control or a "
            "non-ASCII character. Write an internationalised host in its ASCII form."
        )
    parts = urllib.parse.urlsplit(entry)
    scheme = parts.scheme
    if scheme not in _DEFAULT_PORTS:
        raise EgressConfigurationError(
            f"{EGRESS_ALLOWLIST_ENV}: {entry!r} must be an http or https origin"
        )
    if "@" in parts.netloc:
        raise EgressConfigurationError(f"{EGRESS_ALLOWLIST_ENV}: {entry!r} carries userinfo")
    if parts.path not in ("", "/") or parts.query or parts.fragment or entry[-1] in "?#":
        raise EgressConfigurationError(
            f"{EGRESS_ALLOWLIST_ENV}: {entry!r} carries a path, query or fragment. An entry is an "
            "origin, and a path in it would read as a restriction this list does not enforce."
        )
    try:
        port = parts.port
    except ValueError as exc:
        raise EgressConfigurationError(f"{EGRESS_ALLOWLIST_ENV}: {entry!r}: {exc}") from exc
    host = parts.hostname or ""
    raw_host = parts.netloc.rsplit(":", 1)[0] if port is not None else parts.netloc
    if "*" in entry:
        raise EgressConfigurationError(
            f"{EGRESS_ALLOWLIST_ENV}: {entry!r} is a wildcard. Every host is listed by name."
        )
    if _is_ip_literal(host) or _is_ip_literal(raw_host):
        raise EgressConfigurationError(
            f"{EGRESS_ALLOWLIST_ENV}: {entry!r} names an address. The allowlist names hosts."
        )
    if raw_host != host or not _valid_host_name(host):
        raise EgressConfigurationError(
            f"{EGRESS_ALLOWLIST_ENV}: {entry!r} is not a lowercase DNS host name with at least "
            "two labels and no trailing dot ('localhost' is the one single-label name accepted)"
        )
    if port is None:
        port = _DEFAULT_PORTS[scheme]
    if not 0 < port < 65536:
        raise EgressConfigurationError(f"{EGRESS_ALLOWLIST_ENV}: {entry!r} has no usable port")
    if scheme == "http" and host not in _PLAIN_HTTP_HOSTS:
        raise EgressConfigurationError(
            f"{EGRESS_ALLOWLIST_ENV}: {entry!r} is plain http to a remote host. The model "
            "credential travels in a header, and plain http shows it to every hop."
        )
    return Origin(scheme=scheme, host=host, port=port)


@dataclass(frozen=True, slots=True)
class EgressAllowlist:
    """The declared origins, and the one decision made against them."""

    origins: frozenset[Origin]

    def __post_init__(self) -> None:
        if not self.origins:
            raise EgressConfigurationError(
                f"{EGRESS_ALLOWLIST_ENV} declares no origin. An empty allowlist permits nothing, "
                "which is a deployment that forgot its configuration rather than a policy."
            )

    def __str__(self) -> str:
        return ", ".join(str(origin) for origin in sorted(self.origins))

    def require_parts(
        self, *, scheme: str, host: str, port: int | None, userinfo: str | bytes = ""
    ) -> Origin:
        """Refuse unless these already-parsed parts name a declared origin.

        Takes parts rather than a string so the check inside the HTTP client can use the client's
        own parse of the request it is about to send, which is the parse that decides where the
        connection goes.
        """
        scheme = scheme.lower()
        host = host.lower()
        described = f"{scheme}://{host}" + ("" if port is None else f":{port}")
        if userinfo:
            self._refuse(described, "it carries userinfo, which is never needed and is refused")
        if scheme not in _DEFAULT_PORTS:
            self._refuse(described, f"the scheme {scheme!r} is not http or https")
        if not host.isascii() or _UNSAFE.search(host):
            self._refuse(described, "the host is not a plain ASCII name")
        if host.endswith("."):
            self._refuse(described, "a trailing-dot host is refused rather than normalised")
        if _is_ip_literal(host):
            self._refuse(described, "it names an address, and the allowlist names hosts")
        origin = Origin(
            scheme=scheme, host=host, port=_DEFAULT_PORTS[scheme] if port is None else port
        )
        if origin not in self.origins:
            self._refuse(described, "that origin is not declared")
        return origin

    def require(self, url: str) -> Origin:
        """Refuse unless ``url`` names a declared origin. Returns the origin it names."""
        if not isinstance(url, str):
            self._refuse(repr(url), "it is not a URL string")
        if _UNSAFE.search(url) or not url.isascii():
            self._refuse(
                url[:120], "it carries whitespace, a backslash, a control or non-ASCII character"
            )
        parts = urllib.parse.urlsplit(url)
        if "@" in parts.netloc:
            self._refuse(url[:120], "it carries userinfo, which is never needed and is refused")
        try:
            port = parts.port
        except ValueError:
            self._refuse(url[:120], "its port is not a port")
        host = parts.hostname
        if not host:
            self._refuse(url[:120], "it names no host")
        return self.require_parts(scheme=parts.scheme, host=host, port=port)

    def permits(self, url: str) -> bool:
        try:
            self.require(url)
        except EgressRefused:
            return False
        return True

    def _refuse(self, described: str, why: str) -> NoReturn:
        message = (
            f"egress to {described} was refused before any connection: {why}. Declared origins: "
            f"{self}. Never retry this; declare the origin in {EGRESS_ALLOWLIST_ENV} if the "
            "destination is intended."
        )
        _log.warning(message)
        raise EgressRefused(message)


def parse_egress_allowlist(entries: Iterable[object]) -> EgressAllowlist:
    """Validate a sequence of origin strings into an allowlist, refusing duplicates."""
    origins: set[Origin] = set()
    for entry in entries:
        origin = _parse_origin(entry)
        if origin in origins:
            raise EgressConfigurationError(f"{EGRESS_ALLOWLIST_ENV}: {origin} is declared twice")
        origins.add(origin)
    return EgressAllowlist(frozenset(origins))


def load_egress_allowlist(environ: Mapping[str, str] | None = None) -> EgressAllowlist:
    """Read the declared allowlist from the environment, or raise.

    Raises rather than returning a permissive default, for the same reason the token directory
    does, and raises rather than returning an empty list, which would make every model call fail
    in a way that reads as an outage rather than as a missing setting.
    """
    environ = os.environ if environ is None else environ
    raw = env_get("EGRESS_ALLOWLIST", environ)
    if not raw:
        raise EgressConfigurationError(
            f"{EGRESS_ALLOWLIST_ENV} is not set. It is a JSON array of origins the model transport "
            'may reach, for example ["https://api.tokenfactory.nebius.com"]. There is no default, '
            "because a default allowlist is a permitted destination in a repository."
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EgressConfigurationError(f"{EGRESS_ALLOWLIST_ENV} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise EgressConfigurationError(f"{EGRESS_ALLOWLIST_ENV} must be a JSON array of origins")
    return parse_egress_allowlist(parsed)
