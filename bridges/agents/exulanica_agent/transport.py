"""Requests to one world's door with an agent's key: JSON in and out, refusals kept whole.

Standard library only. Every request carries ``Authorization: Bearer <key>`` and nothing else about
the agent, so what it may do is exactly what its grant allows. The key lives in one header of each
request and nowhere else: never in a message, an exception or a ``repr``.

Two refusals are made here rather than by the server, because both would put the key at risk
before any server could refuse: a plain ``http://`` address is accepted only for a loopback host,
and a redirect is never followed, since urllib would copy the ``Authorization`` header to wherever
the redirect points. An answer larger than :data:`ANSWER_BYTES_MAXIMUM` is refused unread.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, Final

__all__ = [
    "ANSWER_BYTES_MAXIMUM",
    "AgentError",
    "Door",
    "DoorRefusal",
]

#: The most bytes one answer of the door may hold: a poll's answer stops adding asked frames past
#: 256 KiB, and outcomes and the grant come on top.
ANSWER_BYTES_MAXIMUM: Final = 1024 * 1024
#: Seconds an ordinary request may wait for the door.
REQUEST_SECONDS: Final = 30.0
_LOOPBACK_NAMES: Final = frozenset({"localhost"})

Opener = Callable[[urllib.request.Request, float], Any]


class AgentError(Exception):
    """The door could not be asked, or its answer could not be read: an unsafe address, no
    answer, a redirect, an answer too large or not JSON. Says what, never with the key."""


class DoorRefusal(Exception):
    """The door answered with a refusal: its status, its ``code`` and ``detail`` unaltered, and
    how long to wait before asking again when it said."""

    def __init__(self, status: int, code: str, detail: str, retry_after_s: float | None) -> None:
        super().__init__(f"{status} {code}: {detail}")
        self.status = status
        self.code = code
        self.detail = detail
        self.retry_after_s = retry_after_s


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        raise AgentError(
            f"the door redirected {req.get_method()} to another address; a redirect is not "
            "followed, because it would carry the agent's key there"
        )


def _is_loopback(host: str) -> bool:
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def checked_url(url: str) -> str:
    """``url`` without a trailing slash, if the key may be sent to it; else :class:`AgentError`."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise AgentError(f"{url!r} is not an http or https address")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AgentError("a world's address carries no user, password, query or fragment")
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
        raise AgentError(
            f"{url!r} would send the agent's key unencrypted to another machine; use https, or "
            "plain http only for this machine"
        )
    return url.rstrip("/")


def _opener() -> Opener:
    build = urllib.request.build_opener(_RefuseRedirects())
    return lambda request, timeout: build.open(request, timeout=timeout)


def _read(response: Any) -> bytes:
    data = response.read(ANSWER_BYTES_MAXIMUM + 1)
    if len(data) > ANSWER_BYTES_MAXIMUM:
        raise AgentError(f"the door's answer is larger than {ANSWER_BYTES_MAXIMUM} bytes")
    return data


def _json(data: bytes) -> dict[str, Any]:
    if not data:
        return {}
    try:
        value = json.loads(data)
    except ValueError as exc:
        raise AgentError("the door's answer is not JSON") from exc
    if not isinstance(value, dict):
        raise AgentError("the door's answer is not a JSON object")
    return value


def _retry_after(problem: Mapping[str, Any]) -> float | None:
    seconds = problem.get("retry_after_s")
    if isinstance(seconds, int | float) and not isinstance(seconds, bool) and seconds >= 0:
        return float(seconds)
    millis = problem.get("retry_after_ms")
    if isinstance(millis, int | float) and not isinstance(millis, bool) and millis >= 0:
        return millis / 1000
    return None


class Door:
    """One world's door, reached with one agent key. ``opener`` replaces the network, for tests
    and for a caller with its own transport; it is called with a request and a timeout."""

    def __init__(self, url: str, key: str, *, opener: Opener | None = None) -> None:
        if not isinstance(key, str) or not key.strip():
            raise AgentError("an agent key is required")
        if any(character.isspace() for character in key) or len(key) > 200:
            raise AgentError("an agent key is one word of at most 200 characters")
        self.url = checked_url(url)
        self.__key = key
        self._opener = opener or _opener()

    def __repr__(self) -> str:
        return f"Door(url={self.url!r})"

    def call(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        query: Mapping[str, str] | None = None,
        timeout: float = REQUEST_SECONDS,
    ) -> dict[str, Any]:
        """The door's answer to one request, or :class:`DoorRefusal` with its code, or
        :class:`AgentError` when there is no answer to read."""
        url = self.url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.__key}")
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self._opener(request, timeout) as response:
                return _json(_read(response))
        except urllib.error.HTTPError as error:
            try:
                problem = _json(_read(error))
            except AgentError:
                problem = {}
            code = problem.get("code")
            detail = problem.get("detail")
            raise DoorRefusal(
                error.code,
                code if isinstance(code, str) else "",
                detail if isinstance(detail, str) else "",
                _retry_after(problem),
            ) from None
        except AgentError:
            raise
        except (TimeoutError, urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise AgentError(
                f"no answer from the door for {method} {path}: {type(reason).__name__}"
            ) from None
