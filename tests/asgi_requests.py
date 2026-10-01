"""Requests driven straight into an ASGI application, several at once, in one event loop.

Starlette's ``TestClient`` sends one request and returns only when the whole response has arrived,
so it cannot hold a stream open while another request is made, stall a body half way, or leave
before the response ends. These tests of capacity need all three. :class:`Exchange` is one
request: it can send its body in pieces, stop sending, disconnect, and be read while it runs.
"""

from __future__ import annotations

import json
from typing import Any

import anyio

__all__ = ["Exchange"]


class Exchange:
    """One HTTP request into ``app``, run with :meth:`run` inside a task group."""

    def __init__(
        self,
        app: Any,
        method: str,
        path: str,
        *,
        query: str = "",
        headers: list[tuple[bytes, bytes]] | None = None,
        body: list[bytes] | None = None,
        hold_body: bool = False,
    ) -> None:
        self.app = app
        self.method = method
        self.path = path
        self.query = query
        self.headers = headers or []
        #: Body pieces sent one per ``receive``; with ``hold_body`` the last one says more follows
        #: and the exchange then waits, as a client whose upload stalled does.
        self.body = list(body or [b""])
        self.hold_body = hold_body
        self.status: int | None = None
        self.response_headers: dict[str, str] = {}
        self.chunks: list[bytes] = []
        self.started = anyio.Event()
        self.done = anyio.Event()
        self.error: BaseException | None = None
        self._leave = anyio.Event()
        self._sent = 0

    def leave(self) -> None:
        """The client goes away: the next ``receive`` is a disconnect."""
        self._leave.set()

    async def receive(self) -> dict[str, Any]:
        if self._sent < len(self.body):
            piece = self.body[self._sent]
            self._sent += 1
            more = self._sent < len(self.body) or self.hold_body
            return {"type": "http.request", "body": piece, "more_body": more}
        await self._leave.wait()
        return {"type": "http.disconnect"}

    async def send(self, message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.response_headers = {
                key.decode("latin-1"): value.decode("latin-1")
                for key, value in message.get("headers", [])
            }
            self.started.set()
        elif message["type"] == "http.response.body":
            self.chunks.append(message.get("body", b""))

    async def run(self) -> None:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": self.method,
            "scheme": "http",
            "path": self.path,
            "raw_path": self.path.encode(),
            "query_string": self.query.encode(),
            "root_path": "",
            "headers": list(self.headers),
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
        try:
            await self.app(scope, self.receive, self.send)
        except BaseException as exc:  # recorded for the test to assert on
            self.error = exc
        finally:
            self.done.set()

    @property
    def text(self) -> str:
        return b"".join(self.chunks).decode("utf-8", "replace")

    def json(self) -> Any:
        return json.loads(self.text)

    def frames(self) -> list[dict[str, Any]]:
        """The ``data:`` payloads of a server-sent event stream, in order."""
        return [
            json.loads(line[len("data: ") :])
            for line in self.text.splitlines()
            if line.startswith("data: ")
        ]
