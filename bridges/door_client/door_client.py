"""A reference client for the door's channel, standard library only.

An adapter redeems an invite once with its bridge's own credential, says hello with its adapter's
version and mapping, then loops: read frames by long-poll, act on each, answer the asks it can. The
cursor each poll returns is the adapter's to keep, in whatever storage its host offers, so a restart
reads on from where it stopped. Everything is in response bodies; nothing here reads a header.

Credentials travel only where they were sent: the client speaks HTTPS, or plain HTTP to a loopback
address for development, and never follows a redirect, so no credential is carried to another host.

This file is the reference for adapters in other languages: each request it makes is one call of
:class:`DoorClient`, with the path, body and answer the door contract states.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

__all__ = ["DoorClient", "DoorRefused", "redeem"]

#: How long a request may take before the door says how long it holds a poll: the longest hold a
#: bridge may declare, 25 seconds, and ten more.
TIMEOUT_SECONDS = 35.0
#: How much longer than the door's hold a poll may take to come back.
_HOLD_MARGIN_SECONDS = 10.0

Opener = Callable[[urllib.request.Request, float], Any]


class DoorRefused(Exception):
    """The door answered with a refusal: its status, code and detail."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(f"{status} {code}: {detail}")
        self.status = status
        self.code = code
        self.detail = detail


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect, so a credential is never sent on to wherever one points."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _open(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)


def _checked(base_url: str) -> str:
    """``base_url`` without its trailing slash if it is HTTPS, or HTTP to a loopback address."""
    parts = urllib.parse.urlsplit(base_url)
    if parts.scheme == "https" and parts.hostname:
        return base_url.rstrip("/")
    if parts.scheme == "http" and parts.hostname:
        host = parts.hostname
        try:
            loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if loopback:
            return base_url.rstrip("/")
    raise ValueError("the door is reached over HTTPS, or plain HTTP to this machine only")


def _call(
    opener: Opener,
    base_url: str,
    credential: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
    timeout: float = TIMEOUT_SECONDS,
) -> dict[str, Any]:
    url = _checked(base_url) + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {credential}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with opener(request, timeout) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        answer = json.loads(error.read() or b"{}")
        raise DoorRefused(
            error.code, str(answer.get("code", "")), str(answer.get("detail", ""))
        ) from None


def redeem(
    base_url: str, bridge_credential: str, code: str, requester: str, *, opener: Opener = _open
) -> dict[str, Any]:
    """Redeem one invite, as the bridge whose credential this is, for the person who typed it
    (``requester``: a SHA-256 hex digest the bridge derives for them, never their name): the grant
    and its channel credential, shown once."""
    return _call(
        opener,
        base_url,
        bridge_credential,
        "POST",
        "/door/invites/redeem",
        {"code": code, "requester": requester},
    )


@dataclass
class DoorClient:
    """One grant's channel."""

    base_url: str
    credential: str = field(repr=False)
    cursor: str | None = None
    hold_seconds: float | None = None
    opener: Opener = field(default=_open, repr=False)

    def hello(
        self,
        adapter_version: str,
        mapping: dict[str, Any],
        reads: list[str],
        declared: dict[str, str] | None = None,
    ) -> dict:
        """Present the adapter and its mapping, and what the program says it is; keep the cursor
        and the hold the door answers with."""
        body: dict[str, Any] = {"adapter_version": adapter_version, "mapping": mapping}
        body["reads"] = reads
        if declared is not None:
            body["declared"] = declared
        answer = _call(
            self.opener, self.base_url, self.credential, "POST", "/door/channel/hello", body
        )
        self.cursor = answer["cursor"]
        self.hold_seconds = float(answer["hold_seconds"])
        return answer

    def frames(self) -> list[dict[str, Any]]:
        """The frames after the kept cursor, waiting up to the door's hold; keep the new cursor."""
        query = {} if self.cursor is None else {"after": self.cursor}
        timeout = (
            TIMEOUT_SECONDS
            if self.hold_seconds is None
            else self.hold_seconds + _HOLD_MARGIN_SECONDS
        )
        answer = _call(
            self.opener,
            self.base_url,
            self.credential,
            "GET",
            "/door/channel/frames",
            None,
            query,
            timeout,
        )
        self.cursor = answer["cursor"]
        return answer["frames"]

    def answer(self, asked: dict[str, Any], label: str, line: str | None = None) -> dict:
        """Answer one ``asked`` frame with one of the labels its context offered."""
        body: dict[str, Any] = {
            "request_id": asked["request_id"],
            "request_sha256": asked["request_sha256"],
            "label": label,
        }
        if line is not None:
            body["line"] = line
        return _call(
            self.opener, self.base_url, self.credential, "POST", "/door/channel/answers", body
        )

    @staticmethod
    def offered(asked: dict[str, Any]) -> list[str]:
        """The labels an ``asked`` frame offers, in its order."""
        return [option["label"] for option in asked["context"]["options"]]
