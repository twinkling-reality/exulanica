"""A prepared output is sent a chunk at a time from its checked copy, which is closed however the
response ends: sent whole, or left by its client part way through.

The route tests (``tests/test_workspace_assets_postgres.py``) hold what is sent; these hold the
response alone, driven as an ASGI server drives it, with no database.
"""

from __future__ import annotations

import io
import uuid

import anyio
import pytest
from exulanica.api.verified_body import VerifiedBodyResponse
from exulanica.world.workspace_preparations import (
    DELIVERY_CHUNK_BYTES,
    MEDIA_TYPE,
    AuthorizedOutput,
)
from starlette.requests import ClientDisconnect

#: Two whole chunks and part of a third, so a chunk boundary is crossed twice.
PAYLOAD = bytes(range(256)) * ((2 * DELIVERY_CHUNK_BYTES + 12345) // 256)


def _output() -> AuthorizedOutput:
    return AuthorizedOutput(
        body=io.BytesIO(PAYLOAD),
        byte_size=len(PAYLOAD),
        content_sha256="0" * 64,
        preparation_id=uuid.uuid4(),
    )


def _scope(spec_version: str) -> dict[str, object]:
    return {"type": "http", "method": "GET", "asgi": {"spec_version": spec_version}}


def test_the_whole_output_is_sent_in_chunks_with_its_length_and_the_copy_is_closed() -> None:
    output = _output()
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    response = VerifiedBodyResponse(output, headers={"ETag": '"etag"'})
    anyio.run(response, _scope("2.4"), receive, send)

    start, *bodies = sent
    headers = dict(start["headers"])  # type: ignore[arg-type]
    assert start["status"] == 200
    assert headers[b"content-length"] == str(len(PAYLOAD)).encode()
    assert headers[b"content-type"] == MEDIA_TYPE.encode()
    assert headers[b"etag"] == b'"etag"'
    chunks = [message["body"] for message in bodies]
    assert b"".join(chunks) == PAYLOAD  # type: ignore[arg-type]
    assert max(len(chunk) for chunk in chunks) <= DELIVERY_CHUNK_BYTES  # type: ignore[arg-type]
    assert bodies[-1]["more_body"] is False
    assert output.body.closed


def test_a_client_that_leaves_part_way_closes_the_copy() -> None:
    """ASGI 2.4: the server raises from ``send`` once its client has gone."""
    output = _output()
    bodies = 0

    async def receive() -> dict[str, object]:
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    async def send(message: dict[str, object]) -> None:
        nonlocal bodies
        if message["type"] == "http.response.body":
            bodies += 1
            if bodies == 2:
                raise OSError("the client went away")

    with pytest.raises(ClientDisconnect):
        anyio.run(VerifiedBodyResponse(output, headers={}), _scope("2.4"), receive, send)
    assert bodies == 2
    assert output.body.closed


def test_a_disconnect_an_older_server_reports_closes_the_copy() -> None:
    """Before ASGI 2.4 the response listens for ``http.disconnect`` and stops streaming."""
    output = _output()

    async def receive() -> dict[str, object]:
        return {"type": "http.disconnect"}

    async def send(_message: dict[str, object]) -> None:
        await anyio.sleep(0.01)

    anyio.run(VerifiedBodyResponse(output, headers={}), _scope("2.3"), receive, send)
    assert output.body.closed
