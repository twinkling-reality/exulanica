"""A refused upload reaches a client that is still sending as the refusal, not as a reset.

A client that writes its whole body before it reads (httpx, and the harness that measured the
runtime envelope) meets a reset when the server closes a connection with body bytes unread: the
operating system answers those bytes with RST and drops the answer it had already received. So
these run the application's admission in a real uvicorn on a loopback port and send a real body
through a socket, which an in-process ASGI exchange cannot show.

*   **The control first:** with the drain switched off (its byte bound at zero), a 32 MiB refused
    body is reset. Without that, a passing drain test would prove nothing about the drain.
*   **The drain:** the same body is answered 503 ``capacity_exhausted`` in full and counted
    ``drained``.
*   **Its bounds:** a body declared over the bound, a body without a declared length that passes
    it, and a refusal past the drain slots are each closed at once and counted.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn
from exulanica.api import admission as admission_module
from exulanica.api.admission import UPLOADS, Admission, AdmissionMiddleware, AdmissionSettings

_BODY_BYTES = 32 * 1024 * 1024
_PIECE = b"\0" * (256 * 1024)


async def _never(scope: Any, receive: Any, send: Any) -> None:  # pragma: no cover - never admitted
    raise AssertionError("a refused request reached the application")


class _Server:
    """Admission in front of an application it never admits to, in uvicorn's own h11 protocol."""

    def __init__(self) -> None:
        self.admission = Admission(AdmissionSettings(uploads=1, workspace_uploads=1))
        # The one upload slot is held for the whole test, so every upload is refused.
        assert self.admission.try_acquire(UPLOADS) is not None
        app = AdmissionMiddleware(_never, admission=self.admission)
        config = uvicorn.Config(
            app, host="127.0.0.1", port=0, http="h11", lifespan="off", log_level="warning"
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> _Server:
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            assert time.monotonic() < deadline, "uvicorn did not start"
            time.sleep(0.01)
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.should_exit = True
        self.thread.join(10)

    @property
    def port(self) -> int:
        return self.server.servers[0].sockets[0].getsockname()[1]

    def drains(self) -> dict[str, Any]:
        return self.admission.snapshot()["refusal_drains"]


@pytest.fixture
def served() -> Iterator[_Server]:
    with _Server() as server:
        yield server


def _upload(port: int, *, chunked: bool = False, length: int = _BODY_BYTES) -> dict[str, Any]:
    """Send a whole body, then read: what a client that reads only after sending receives."""
    with socket.create_connection(("127.0.0.1", port), timeout=20) as connection:
        framing = b"transfer-encoding: chunked" if chunked else f"content-length: {length}".encode()
        connection.sendall(
            b"POST /intake HTTP/1.1\r\nhost: test\r\n"
            b"content-type: application/octet-stream\r\n" + framing + b"\r\n\r\n"
        )
        try:
            sent = 0
            while sent < length:
                piece = _PIECE[: min(len(_PIECE), length - sent)]
                connection.sendall(b"%x\r\n%s\r\n" % (len(piece), piece) if chunked else piece)
                sent += len(piece)
            if chunked:
                connection.sendall(b"0\r\n\r\n")
            received = b""
            while chunk := connection.recv(65536):
                received += chunk
        except (ConnectionResetError, BrokenPipeError) as reset:
            return {"reset": type(reset).__name__}
    head, _, body = received.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1])
    headers = dict(
        (name.strip().lower().decode(), value.strip().decode())
        for name, _, value in (line.partition(b":") for line in head.split(b"\r\n")[1:])
    )
    return {"status": status, "headers": headers, "body": json.loads(body)}


def test_control_without_the_drain_a_refused_upload_is_reset(served, monkeypatch):
    monkeypatch.setattr(admission_module, "DRAIN_BYTES", 0)
    answer = _upload(served.port)
    assert "reset" in answer, answer
    assert served.drains()["closed"] == 1


def test_a_refused_upload_is_drained_and_its_client_reads_the_refusal(served):
    answer = _upload(served.port)
    assert answer.get("status") == 503, answer
    assert answer["body"]["code"] == "capacity_exhausted"
    assert answer["body"]["capacity"] == "uploads"
    assert answer["headers"]["retry-after"] == "10"
    assert answer["headers"]["connection"] == "close"
    drains = served.drains()
    assert (drains["drained"], drains["in_flight"], drains["peak"]) == (1, 0, 1)


def test_a_body_declared_over_the_bound_is_closed_at_once(served, monkeypatch):
    monkeypatch.setattr(admission_module, "DRAIN_BYTES", _BODY_BYTES - 1)
    _upload(served.port)
    drains = served.drains()
    assert (drains["closed"], drains["drained"], drains["peak"]) == (1, 0, 0)


def test_an_undeclared_body_is_cut_where_it_passes_the_bound(served, monkeypatch):
    monkeypatch.setattr(admission_module, "DRAIN_BYTES", 1024 * 1024)
    _upload(served.port, chunked=True)
    drains = served.drains()
    assert (drains["cut"], drains["drained"], drains["in_flight"]) == (1, 0, 0)


def test_an_undeclared_body_within_the_bound_is_drained(served):
    answer = _upload(served.port, chunked=True, length=4 * 1024 * 1024)
    assert answer.get("status") == 503, answer
    assert served.drains()["drained"] == 1


def test_a_refusal_past_the_drain_slots_is_closed_at_once(served, monkeypatch):
    monkeypatch.setattr(admission_module, "DRAIN_SLOTS", 0)
    _upload(served.port, length=1024)
    drains = served.drains()
    assert (drains["closed"], drains["drained"]) == (1, 0)
