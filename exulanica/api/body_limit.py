"""Refuse an over-large request body before any of it is read.

**Why this is middleware and not a check in a route.** A route function runs after the body has
been received: FastAPI reads and parses it, then resolves dependencies, then calls the handler.
By the time an upload route could look at the size, a multipart parser has already spooled every
part to a temporary file. A check there bounds what reaches the store, which matters and is
where the intake route does it, and it does not bound the disk. This runs before the application
sees the request at all, so an over-large body is refused with nothing written anywhere.

**Two bounds, because one header is not enough.** A declared ``Content-Length`` over the limit is
refused before a byte is read. A request that declares no length, which is what
``Transfer-Encoding: chunked`` produces, is **counted as it arrives** and cut off the moment the
running total crosses the limit. The second is what makes the first more than a courtesy: without
it, omitting one header walks past the whole thing.

Counting costs at most one chunk past the limit, not the whole body, which is the objection to
counting and the reason it is answered by cutting off rather than by draining. A proxy in front
is still better, because it refuses before the application is involved at all, and
``docs/deployment.md`` section 5.1.2 says so.

**This runs before authentication and that is the point.** FastAPI receives and parses the body
before it resolves dependencies, so an unauthenticated request has already had its multipart
parts spooled to temporary files by the time the bearer token is looked at. Starlette bounds
``max_part_size`` for non-file parts only, so file parts are unbounded there. Middleware is
upstream of all of it.

It applies to every route rather than to the upload route alone, deliberately. A limit that has
to be remembered per route is a limit the next route will not have.
"""

from __future__ import annotations

import json
from typing import Any, Final

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["MAX_BODY_BYTES", "BodyLimit", "BodyTooLarge"]

#: The largest request body this application will accept. Large enough for a phone's worth of
#: photographs in one upload, small enough that a mistaken video does not fill a disk.
MAX_BODY_BYTES: Final = 512 * 1024 * 1024


class BodyLimit:
    """Pure ASGI, so it runs ahead of routing and ahead of any body parsing."""

    def __init__(self, app: ASGIApp, *, limit: int | None = None) -> None:
        self._app = app
        # Resolved at construction rather than bound as a default argument, so the module
        # constant is read when an application is built rather than when this file is imported.
        # A default argument would freeze it at import and a test could not vary it without
        # reaching inside the instance, which is a test asserting against a name nothing reads.
        self._limit = MAX_BODY_BYTES if limit is None else limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        declared = _declared_length(scope)
        if declared is not None and declared > self._limit:
            await _refuse(send, declared, self._limit)
            return
        await self._app(scope, _counted(receive, self._limit), send)


def _declared_length(scope: Scope) -> int | None:
    """The declared body size, or None when the client declared none or declared nonsense.

    A malformed ``Content-Length`` is None rather than zero and rather than an error. It is a
    header this middleware only reads to refuse on, so an unreadable one means "no grounds to
    refuse here"; the request is then handled by whatever else would have handled it.
    """
    raw = Headers(scope=scope).get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


class BodyTooLarge(HTTPException):
    """Raised into the application when a body outgrows the limit while it is being read.

    An exception rather than a truncated stream, because a parser handed a short body reports a
    malformed request, and "you sent too much" and "what you sent was broken" are different
    answers to give somebody.

    **An ``HTTPException`` subclass, and that is load bearing rather than convenient.** FastAPI
    reads and parses the body inside a ``try`` whose final clause turns everything into
    ``400 There was an error parsing the body``, with one explicit exemption: ``except
    HTTPException: raise``, commented in its own source as "If a middleware raises an
    HTTPException, it should be raised again". Any other base class arrives at the client as a
    400 about a malformed request, which is the wrong answer and hides the limit that produced
    it. Measured, before this base class was chosen.

    :func:`exulanica.api.app.create_app` registers a handler for this exact class, so the response
    carries the same ``{"code", "detail"}`` shape every other refusal in this API uses rather
    than Starlette's bare ``{"detail"}``.
    """

    def __init__(self, read: int, limit: int) -> None:
        super().__init__(status_code=413, detail=f"the request body exceeded {limit} bytes")
        self.read = read
        self.limit = limit


def _counted(receive: Receive, limit: int) -> Receive:
    """Wrap ``receive`` so the body is bounded even when no length was declared.

    The count is over what has actually arrived, so the overshoot is one chunk rather than the
    whole body: the moment the running total crosses the limit this raises, and nothing further
    is read. A ``more_body`` stream that is never drained is fine here, because the connection is
    closed with the refusal.
    """
    read = 0

    async def counted() -> Message:
        nonlocal read
        message = await receive()
        if message["type"] == "http.request":
            read += len(message.get("body", b""))
            if read > limit:
                raise BodyTooLarge(read, limit)
        return message

    return counted


async def _refuse(send: Send, declared: int, limit: int) -> None:
    """The same problem shape every other refusal in this API uses."""
    body: dict[str, Any] = {
        "code": "body_too_large",
        "detail": (
            f"the request declares {declared} bytes and this instance accepts at most {limit}"
        ),
    }
    payload = json.dumps(body).encode("utf-8")
    start: Message = {
        "type": "http.response.start",
        "status": 413,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode("ascii")),
            # The connection is closed rather than drained. Reading a body only to discard it is
            # doing the work the refusal exists to avoid.
            (b"connection", b"close"),
        ],
    }
    await send(start)
    await send({"type": "http.response.body", "body": payload})
