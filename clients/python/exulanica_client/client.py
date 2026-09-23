"""The HTTP layer: one bearer token, JSON in and out, and the server's refusals kept whole.

Standard library only. Every request carries ``Authorization: Bearer <token>`` and nothing else
about the caller, so what this client may do is exactly what the token's grant allows. The token is
never written anywhere: it lives in one header of each request and in no exchange this module
reports.

Two refusals are made here rather than by the server, because both would put the credential at
risk before any server could refuse. A plain ``http://`` address is accepted only for a loopback
host, and a redirect is never followed, since urllib would copy the ``Authorization`` header to
wherever the redirect points.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = ["ApiRefusal", "ClientError", "Exchange", "WorldClient"]

#: Hosts a plain-http address may name: the credential never leaves the machine.
_LOOPBACK_NAMES = frozenset({"localhost"})
#: Seconds a request may wait for the server before the client gives up on it.
DEFAULT_TIMEOUT_SECONDS = 30.0


class ClientError(Exception):
    """The client could not make or finish a request: no answer, a redirect, an unsafe address."""


class ApiRefusal(Exception):
    """The server answered with a failure. ``code`` and ``detail`` are its own words, unaltered."""

    def __init__(self, method: str, path: str, status: int, body: object) -> None:
        self.method = method
        self.path = path
        self.status = status
        problem = body if isinstance(body, dict) else {}
        self.code: str | None = (
            problem.get("code") if isinstance(problem.get("code"), str) else None
        )
        detail = problem.get("detail", body)
        self.detail = detail if isinstance(detail, str) else json.dumps(detail, sort_keys=True)
        super().__init__(f"{method} {path} answered {status} {self.code or ''}: {self.detail}")


@dataclass(frozen=True)
class Exchange:
    """One request and its answer, as a transcript records it. Holds no credential."""

    method: str
    path: str
    query: Mapping[str, str]
    status: int
    request_body: object
    response_body: object


@dataclass
class _Answer:
    status: int
    body: object
    headers: Mapping[str, str] = field(default_factory=dict)


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
        raise ClientError(
            f"the server redirected {req.get_method()} {req.full_url} to {newurl}; a redirect is "
            "not followed, because it would carry the bearer token to another address"
        )


def _checked_base_url(base_url: str) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ClientError(f"{base_url!r} is not an http or https address")
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
        raise ClientError(
            f"{base_url!r} would send the bearer token unencrypted to another machine; use https, "
            "or plain http only for a loopback address"
        )
    return base_url.rstrip("/")


def _is_loopback(host: str) -> bool:
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class WorldClient:
    """Authenticated requests to one Exulanica API, and the reads and edits a world client needs.

    ``on_exchange`` is called with every :class:`Exchange`, refusals included, which is how a caller
    keeps a transcript. ``opener`` replaces the urllib opener, for a caller that routes requests
    through its own transport.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        on_exchange: Callable[[Exchange], None] | None = None,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        if not token:
            raise ClientError("a bearer token is required")
        self.base_url = _checked_base_url(base_url)
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self._timeout = timeout
        self._on_exchange = on_exchange
        self._opener = opener or urllib.request.build_opener(_RefuseRedirects())

    # -- transport ------------------------------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: object = None,
    ) -> tuple[int, object]:
        """Send one request and return ``(status, decoded body)`` whatever the status is."""
        query = dict(query or {})
        url = self.base_url + path + (f"?{urllib.parse.urlencode(query)}" if query else "")
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = dict(self._headers)
        if data is not None:
            headers["Content-Type"] = "application/json"
        prepared = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(prepared, timeout=self._timeout) as response:
                answer = _Answer(response.status, _decode(response.read()), dict(response.headers))
        except urllib.error.HTTPError as refused:
            answer = _Answer(refused.code, _decode(refused.read()), dict(refused.headers))
        except urllib.error.URLError as unreachable:
            raise ClientError(f"{method} {url} got no answer: {unreachable.reason}") from None
        if self._on_exchange is not None:
            self._on_exchange(Exchange(method, path, query, answer.status, body, answer.body))
        return answer.status, answer.body

    def get(self, path: str, *, query: Mapping[str, str] | None = None) -> Any:
        """A read that must succeed, or an :class:`ApiRefusal` carrying the server's reason."""
        status, body = self.request("GET", path, query=query)
        if status != 200:
            raise ApiRefusal("GET", path, status, body)
        return body

    def post(self, path: str, body: object, *, query: Mapping[str, str] | None = None) -> Any:
        """An edit that must be accepted, or an :class:`ApiRefusal` carrying the server's reason."""
        status, answer = self.request("POST", path, query=query, body=body)
        if status not in (200, 201):
            raise ApiRefusal("POST", path, status, answer)
        return answer

    # -- the reads ------------------------------------------------------------------------------

    def openapi(self) -> dict[str, Any]:
        """The server's own description of every route it serves. Public: no grant is needed."""
        return self.get("/openapi.json")

    def saved_worlds(self) -> list[dict[str, Any]]:
        """The saved worlds of the token's workspace: each names the version it opens at."""
        return self.get("/world-entries")

    def saved_world(self, entry_id: str) -> dict[str, Any]:
        return self.get(f"/world-entries/{_segment(entry_id)}")

    def version(self, version_id: str, *, world_id: str) -> dict[str, Any]:
        """One authored version with its objects, edit history and ``state_sha256``."""
        return self.get(f"/world/versions/{_segment(version_id)}", query={"world_id": world_id})

    def assets(self) -> list[dict[str, Any]]:
        """The reviewed assets an object may be made from, each with whether its bytes exist."""
        return self.get("/world/assets")

    def behaviours(self) -> list[dict[str, Any]]:
        """The reviewed behaviours an object may be given, with each parameter's bounds."""
        return self.get("/world/behaviours")

    # -- the edits ------------------------------------------------------------------------------

    def place_object(
        self,
        version: Mapping[str, Any],
        *,
        object_id: str,
        asset_sha256: str,
        region_id: str,
        transform: Mapping[str, int],
        origin_role: str,
        saved_entry: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add one object against the version state the caller read. Returns the new version."""
        body: dict[str, Any] = {
            "base_state_sha256": version["state_sha256"],
            "object_id": object_id,
            "asset_sha256": asset_sha256,
            "region_id": region_id,
            "transform": dict(transform),
            "origin_role": origin_role,
        }
        if saved_entry is not None:
            body["saved_entry"] = _resume_point(saved_entry)
        return self.post(
            f"/world/versions/{_segment(version['version_id'])}/objects",
            body,
            query={"world_id": version["world_id"]},
        )

    def set_behaviour(
        self,
        version: Mapping[str, Any],
        object_id: str,
        behaviour: Mapping[str, Any] | None,
        *,
        saved_entry: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Give an object a reviewed behaviour, or clear it with ``None``. Returns the version."""
        body: dict[str, Any] = {
            "base_state_sha256": version["state_sha256"],
            "behaviour": None if behaviour is None else dict(behaviour),
        }
        if saved_entry is not None:
            body["saved_entry"] = _resume_point(saved_entry)
        return self.post(
            f"/world/versions/{_segment(version['version_id'])}/objects/"
            f"{_segment(object_id)}/behaviour",
            body,
            query={"world_id": version["world_id"]},
        )


def _resume_point(entry: Mapping[str, Any]) -> dict[str, Any]:
    """The saved world's resume point, so the edit and the saved world advance together or not."""
    return {
        "entry_id": entry["entry_id"],
        "base_revision": entry["revision"],
        "authored_state_sha256": entry["authored_state_sha256"],
        "authored_edit_seq": entry["authored_edit_seq"],
    }


def _segment(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


def _decode(payload: bytes) -> object:
    if not payload:
        return None
    try:
        return json.loads(payload)
    except ValueError:
        return payload.decode("utf-8", errors="replace")
