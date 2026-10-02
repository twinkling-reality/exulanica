"""How much work one API process accepts at once, decided before any of it starts.

An API process runs out of request threads, database connections, decode memory and open streams,
and every one of those is taken by work the process has already accepted
(``docs/deployment.md`` section 5.4). So the only place to bound all of them is before a request is
accepted, and this module is that place: pure ASGI middleware, like
:mod:`exulanica.api.body_limit`, that sorts each request into a class by its route and admits it
or refuses it at once.

**Refused before anything is spent.** The middleware runs before routing, before the body is
parsed, before a threadpool token and before a database connection. A refused request is answered
503 ``capacity_exhausted`` with ``Retry-After``, and nothing of the route ran, so sending the same
request again after that wait is always safe.

**A refusal reaches a client that is still sending.** A connection closed with body bytes unread
is reset by the operating system, and a client still writing its upload reads that reset instead
of the answer. So a refused request that declares a body is answered at once and its body is then
read and discarded, up to :data:`DRAIN_BYTES` and :data:`DRAIN_SECONDS`, before the connection
closes, with at most :data:`DRAIN_SLOTS` of them at a time in one process. A drain holds no slot,
thread or database connection; its cost is a socket and what the server buffers for it, which
pauses reading at 64 KiB. A body declared over the byte bound, a client waiting for ``100
Continue`` (which has sent no body) and a refusal past the drain slots are closed at once.

**There is no queue here.** Admission is a try-acquire under a lock. A request over the limit is
refused rather than parked, because a parked request is a held socket and an unanswered person, and
because a queue in front of a bounded pool only moves the unbounded part somewhere nobody measures.

**Released where it was taken.** The slot is released in the middleware's own ``finally``, around
the whole ASGI call including a streamed response. Acquisition and release are in one frame, so a
response that is built and never iterated cannot keep a slot, and a client that disconnects gives
its slot back when the response task ends.

**A workspace's share.** Each class also bounds how much of it one workspace may hold, so one
workspace's burst cannot refuse every other workspace. The workspace is not known until the caller
is resolved, so :func:`exulanica.api.dependencies.authorise_route` claims it on the ticket this
middleware leaves in the scope, after the permission check and before the tile charge and the
route's own dependencies, and the release here covers both counts. The share is counted in this
process's memory and never reaches a database. Over the share the answer is 429
``workspace_capacity_exhausted``, which names no other workspace.

**Who may read the counts.** Readiness is unauthenticated, so it reports only the declared limits
(:meth:`Admission.limits`); how much of each class is in use, which is other workspaces' activity,
is read through ``GET /operations/capacity`` with ``operations.read`` (:meth:`Admission.snapshot`).

**Bodies have deadlines.** A body that stops arriving would otherwise hold its slot until the
client gave up. While a request's body is incomplete, a gap of :data:`BODY_IDLE_SECONDS` or a total
past the class's :data:`BODY_SECONDS` ends it with 408 ``body_timeout``.

**Everything here bounds one process.** Several API processes behind one database hold several
times each limit, and a workspace can hold its share in each of them.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Any, Final

import anyio
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.routing import compile_path
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from exulanica.api.body_limit import MAX_BODY_BYTES
from exulanica.api.routes import routable_paths
from exulanica.env import env_get, env_name
from exulanica.errors import ExulanicaError

__all__ = [
    "ADMISSION_SETTING_REFUSALS",
    "CAPACITY_ROUTES",
    "DECODES",
    "EXEMPT",
    "REQUESTS",
    "STREAMS",
    "TICKET_SCOPE_KEY",
    "UPLOADS",
    "Admission",
    "AdmissionMiddleware",
    "AdmissionSettingRefused",
    "AdmissionSettings",
    "BodyTimeout",
    "CapacityDeclarationError",
    "CapacityRefused",
    "DerivativeQueueFull",
    "claim_workspace",
    "require_capacity_declaration",
]

#: The classes. A route not named in :data:`CAPACITY_ROUTES` is an ordinary request.
EXEMPT: Final = "exempt"
REQUESTS: Final = "requests"
UPLOADS: Final = "uploads"
STREAMS: Final = "streams"
#: Not an admission class: the photograph decode bound in :mod:`exulanica.corpus.decode`, named
#: here because its refusal takes the same shape as the three above.
DECODES: Final = "decodes"

#: Every route that is not an ordinary request, keyed as the permission declarations are
#: (:data:`exulanica.api.permissions.ROUTE_RULES`). Liveness and readiness are never refused: a
#: probe that a busy instance refuses is a probe that restarts a working instance.
#: :func:`require_capacity_declaration` refuses an application in which a key here names no route,
#: so a renamed route cannot fall back to ``requests`` unnoticed.
CAPACITY_ROUTES: Final[Mapping[tuple[str, str], str]] = MappingProxyType(
    {
        ("GET", "/healthz"): EXEMPT,
        ("GET", "/readyz"): EXEMPT,
        ("GET", "/formation/{batch_id}"): STREAMS,
        ("POST", "/intake"): UPLOADS,
        ("POST", "/workspace-assets"): UPLOADS,
    }
)

#: What ``Retry-After`` says for each refusal, in whole seconds. An upload is sent again whole, so
#: its wait is longer than a small read's.
RETRY_AFTER_SECONDS: Final[Mapping[str, int]] = MappingProxyType(
    {REQUESTS: 1, UPLOADS: 10, STREAMS: 5, DECODES: 5}
)

#: The longest gap between two pieces of an incomplete body.
BODY_IDLE_SECONDS: Final = 15.0

#: The longest a class's body may take to arrive in total. 600 seconds is a 512 MB upload, the
#: body limit, at about 0.9 MB/s.
BODY_SECONDS: Final[Mapping[str, float]] = MappingProxyType(
    {REQUESTS: 60.0, UPLOADS: 600.0, STREAMS: 60.0}
)

#: The most of a refused request's body read and discarded so that the refusal, not a reset,
#: reaches its client: the body limit itself, so every body the application would accept is
#: drained whole. Reading costs the event loop a copy of each piece and holds nothing.
DRAIN_BYTES: Final = MAX_BODY_BYTES

#: The longest one refusal's drain may take, the uploads class's ``Retry-After``: a client that
#: needs longer to send its body (a whole 512 MiB body at under about 54 MB/s) is closed on, as
#: before.
DRAIN_SECONDS: Final = 10.0

#: How many refusals one process drains at once. At about 320 KiB buffered each (uvicorn pauses
#: reading at 64 KiB, plus one 256 KiB socket read) the set holds about 5 MiB.
DRAIN_SLOTS: Final = 16

#: Threads kept free of admitted requests for the short work around them: multipart spooling and a
#: stream resolving its caller before it starts.
THREAD_HEADROOM: Final = 4

#: Where the middleware leaves the ticket for the request's own admission. Set by server code only.
TICKET_SCOPE_KEY: Final = "exulanica.admission"

_NOUNS: Final[Mapping[str, str]] = MappingProxyType(
    {
        REQUESTS: "requests",
        UPLOADS: "uploads",
        STREAMS: "progress streams",
        DECODES: "photograph decodes",
    }
)


# -- settings ---------------------------------------------------------------------------------

#: Every way a capacity setting is refused at startup, by the name the refusal carries.
ADMISSION_SETTING_REFUSALS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "admission_setting_not_integer": "must be a whole number",
        "admission_setting_out_of_bounds": "is outside the bounds this process accepts",
        "admission_share_exceeds_limit": "is larger than the limit of its class",
        "admission_threads_too_few": (
            f"must be at least EXULANICA_API_REQUESTS + EXULANICA_API_UPLOADS + {THREAD_HEADROOM}, "
            "so an admitted request never waits for a thread while it holds a connection"
        ),
    }
)


class AdmissionSettingRefused(ValueError):
    """A capacity setting that startup refuses, named by ``code`` and ``variable``."""

    def __init__(self, code: str, variable: str) -> None:
        super().__init__(f"{code}: {variable} {ADMISSION_SETTING_REFUSALS[code]}")
        self.code = code
        self.variable = variable


#: Each setting's environment suffix and inclusive bounds, in field order.
_SETTINGS: Final[Mapping[str, tuple[str, int, int]]] = MappingProxyType(
    {
        "threads": ("API_THREADS", 8, 1024),
        "requests": ("API_REQUESTS", 1, 1024),
        "uploads": ("API_UPLOADS", 1, 64),
        "streams": ("API_STREAMS", 1, 8192),
        "workspace_requests": ("API_WORKSPACE_REQUESTS", 1, 1024),
        "workspace_uploads": ("API_WORKSPACE_UPLOADS", 1, 64),
        "workspace_streams": ("API_WORKSPACE_STREAMS", 1, 8192),
        "decodes": ("API_DECODES", 1, 64),
        "intake_queued_jobs": ("INTAKE_QUEUED_JOBS", 1, 1000),
    }
)


@dataclass(frozen=True, slots=True)
class AdmissionSettings:
    """The declared limits of one API process. The defaults are the measured supported envelope.

    Checked on construction, so a hand-built value in a test is held to the same rules as one read
    from the environment.
    """

    threads: int = 40
    requests: int = 24
    uploads: int = 2
    streams: int = 128
    workspace_requests: int = 12
    workspace_uploads: int = 1
    workspace_streams: int = 8
    decodes: int = 2
    intake_queued_jobs: int = 4

    def __post_init__(self) -> None:
        for name, (suffix, low, high) in _SETTINGS.items():
            value = getattr(self, name)
            if type(value) is not int:
                raise AdmissionSettingRefused("admission_setting_not_integer", env_name(suffix))
            if not low <= value <= high:
                raise AdmissionSettingRefused("admission_setting_out_of_bounds", env_name(suffix))
        for share, limit in (
            ("workspace_requests", "requests"),
            ("workspace_uploads", "uploads"),
            ("workspace_streams", "streams"),
        ):
            if getattr(self, share) > getattr(self, limit):
                raise AdmissionSettingRefused(
                    "admission_share_exceeds_limit", env_name(_SETTINGS[share][0])
                )
        if self.requests + self.uploads + THREAD_HEADROOM > self.threads:
            raise AdmissionSettingRefused("admission_threads_too_few", env_name("API_THREADS"))

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> AdmissionSettings:
        """The settings the environment names; an absent one keeps its default."""
        values: dict[str, int] = {}
        for name, (suffix, _low, _high) in _SETTINGS.items():
            raw = env_get(suffix, environ)
            if raw is None or not raw.strip():
                continue
            text = raw.strip()
            if not text.isascii() or not text.isdigit():
                raise AdmissionSettingRefused("admission_setting_not_integer", env_name(suffix))
            values[name] = int(text)
        return cls(**values)

    @staticmethod
    def variables() -> tuple[str, ...]:
        """Every setting's environment name, for ``describe_configuration``."""
        return tuple(env_name(suffix) for suffix, _low, _high in _SETTINGS.values())

    def as_document(self) -> dict[str, int]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


# -- refusals ---------------------------------------------------------------------------------


class CapacityRefused(ExulanicaError):
    """A request refused for capacity before any of its work started.

    ``workspace`` distinguishes the two answers: False is the whole process at a declared limit
    (503 ``capacity_exhausted``), True is the caller's own workspace at its share (429
    ``workspace_capacity_exhausted``).
    """

    def __init__(self, capacity: str, *, workspace: bool) -> None:
        self.capacity = capacity
        self.workspace = workspace
        self.retry_after = RETRY_AFTER_SECONDS[capacity]
        noun = _NOUNS[capacity]
        who = (
            "this workspace already has as many " + noun + " in progress as one workspace may"
            if workspace
            else "this server is handling as many " + noun + " as it accepts at once"
        )
        super().__init__(
            f"{who}; nothing was started, so the same request can be sent again after "
            f"{_seconds(self.retry_after)}"
        )

    @property
    def status(self) -> int:
        return 429 if self.workspace else 503

    @property
    def code(self) -> str:
        return "workspace_capacity_exhausted" if self.workspace else "capacity_exhausted"

    def body(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "detail": str(self),
            "capacity": self.capacity,
            "retry_after_seconds": self.retry_after,
        }

    def headers(self) -> dict[str, str]:
        return {"Retry-After": str(self.retry_after), "Cache-Control": "no-store"}

    def response(self) -> JSONResponse:
        """The answer the application's exception handler sends."""
        return JSONResponse(status_code=self.status, content=self.body(), headers=self.headers())


class DerivativeQueueFull(ExulanicaError):
    """An upload refused because its workspace's earlier uploads are still being processed.

    Checked before the upload opens a batch, so nothing was written. The bound is per workspace
    (``EXULANICA_INTAKE_QUEUED_JOBS``), counted over the derivative jobs queued or running, and
    exact for one API process; ``docs/deployment.md`` section 5.4 says how far concurrent uploads
    in several processes can pass it.
    """

    RETRY_AFTER: Final = 30

    def __init__(self, bound: int) -> None:
        self.bound = bound
        super().__init__(
            f"this workspace already has {bound} {'upload' if bound == 1 else 'uploads'} whose "
            "photographs are still being processed; nothing was written, so the upload can be "
            f"sent again after {_seconds(self.RETRY_AFTER)}"
        )

    def response(self) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "code": "derivative_queue_full",
                "detail": str(self),
                "retry_after_seconds": self.RETRY_AFTER,
            },
            headers={"Retry-After": str(self.RETRY_AFTER), "Cache-Control": "no-store"},
        )


class BodyTimeout(HTTPException):
    """A body that stopped arriving, or took longer in total than its class allows.

    An ``HTTPException`` for the reason :class:`exulanica.api.body_limit.BodyTooLarge` is one:
    FastAPI's body parser turns every other exception raised while it reads into a 400 about a
    malformed body.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=408, detail=detail, headers={"Connection": "close"})


class CapacityDeclarationError(ExulanicaError):
    """:data:`CAPACITY_ROUTES` names a route the application does not serve."""


def require_capacity_declaration(
    app: object, routes: Mapping[tuple[str, str], str] = CAPACITY_ROUTES
) -> None:
    """Refuse an application in which a declared capacity route does not exist."""
    served = set(routable_paths(app))
    if stale := sorted(key for key in routes if key not in served):
        raise CapacityDeclarationError(
            "these capacity declarations name routes the application does not serve: "
            + ", ".join(f"{method} {path}" for method, path in stale)
        )


# -- the counts -------------------------------------------------------------------------------


@dataclass
class _Class:
    limit: int
    share: int
    in_flight: int = 0
    peak: int = 0
    admitted: int = 0
    refused: int = 0
    refused_workspace: int = 0
    body_timeouts: int = 0


#: How a refused request with a body ended: its body read to the end (``drained``), the client
#: gone first (``left``), a bound reached first (``cut``), or no drain at all (``closed``).
DRAIN_OUTCOMES: Final = ("drained", "left", "cut", "closed")


class Ticket:
    """One admitted request's hold on its class, and on its workspace's share once claimed."""

    __slots__ = ("admission", "capacity", "released", "workspace")

    def __init__(self, admission: Admission, capacity: str) -> None:
        self.admission = admission
        self.capacity = capacity
        self.workspace: uuid.UUID | None = None
        self.released = False


class Admission:
    """The counts for one application. Safe to call from the event loop and from worker threads."""

    def __init__(self, settings: AdmissionSettings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._classes: dict[str, _Class] = {
            REQUESTS: _Class(settings.requests, settings.workspace_requests),
            UPLOADS: _Class(settings.uploads, settings.workspace_uploads),
            STREAMS: _Class(settings.streams, settings.workspace_streams),
        }
        self._workspaces: dict[tuple[str, uuid.UUID], int] = {}
        self._poll_failures = 0
        self._drains_in_flight = 0
        self._drains_peak = 0
        self._drain_outcomes = dict.fromkeys(DRAIN_OUTCOMES, 0)

    def try_acquire(self, capacity: str) -> Ticket | None:
        """A ticket for one request of ``capacity``, or None when the class is full."""
        with self._lock:
            held = self._classes[capacity]
            if held.in_flight >= held.limit:
                held.refused += 1
                return None
            held.in_flight += 1
            held.admitted += 1
            held.peak = max(held.peak, held.in_flight)
        return Ticket(self, capacity)

    def claim_workspace(self, ticket: Ticket, workspace_id: uuid.UUID) -> None:
        """Count ``ticket`` against its workspace's share, or raise :class:`CapacityRefused`."""
        with self._lock:
            if ticket.released or ticket.workspace == workspace_id:
                return
            if ticket.workspace is not None:
                raise RuntimeError("an admitted request was claimed for a second workspace")
            held = self._classes[ticket.capacity]
            key = (ticket.capacity, workspace_id)
            if self._workspaces.get(key, 0) >= held.share:
                held.refused_workspace += 1
                raise CapacityRefused(ticket.capacity, workspace=True)
            self._workspaces[key] = self._workspaces.get(key, 0) + 1
            ticket.workspace = workspace_id

    def release(self, ticket: Ticket) -> None:
        """Give back everything ``ticket`` holds. Idempotent."""
        with self._lock:
            if ticket.released:
                return
            ticket.released = True
            self._classes[ticket.capacity].in_flight -= 1
            if ticket.workspace is not None:
                key = (ticket.capacity, ticket.workspace)
                remaining = self._workspaces[key] - 1
                if remaining:
                    self._workspaces[key] = remaining
                else:
                    del self._workspaces[key]

    def note_body_timeout(self, capacity: str) -> None:
        with self._lock:
            self._classes[capacity].body_timeouts += 1

    def try_drain(self) -> bool:
        """A place to drain one refused body, or False (counted ``closed``) when all are taken."""
        with self._lock:
            if self._drains_in_flight >= DRAIN_SLOTS:
                self._drain_outcomes["closed"] += 1
                return False
            self._drains_in_flight += 1
            self._drains_peak = max(self._drains_peak, self._drains_in_flight)
            return True

    def end_drain(self, outcome: str) -> None:
        """Give back a place :meth:`try_drain` gave, and count how its drain ended."""
        with self._lock:
            self._drains_in_flight -= 1
            self._drain_outcomes[outcome] += 1

    def note_closed(self) -> None:
        """A refused body that was not drained: declared over the bound, or awaiting 100."""
        with self._lock:
            self._drain_outcomes["closed"] += 1

    def note_poll_failure(self) -> None:
        with self._lock:
            self._poll_failures += 1

    def limits(self) -> dict[str, Any]:
        """The declared limits alone: configuration, which readiness may show to anyone."""
        return {
            "per_process": True,
            "threads": self.settings.threads,
            "classes": {
                name: {"limit": held.limit, "workspace_share": held.share}
                for name, held in self._classes.items()
            },
        }

    def snapshot(self, workspace_id: uuid.UUID | None = None) -> dict[str, Any]:
        """Limits and this process's counts, for an authenticated operator. Never a workspace id.

        ``workspace_id`` adds how much of each class's share that one workspace holds now.
        """
        with self._lock:
            document: dict[str, Any] = {
                **self.limits(),
                "classes": {
                    name: {
                        "limit": held.limit,
                        "workspace_share": held.share,
                        "in_flight": held.in_flight,
                        "peak": held.peak,
                        "admitted": held.admitted,
                        "refused": held.refused,
                        "refused_workspace": held.refused_workspace,
                        "body_timeouts": held.body_timeouts,
                    }
                    for name, held in self._classes.items()
                },
                "stream_poll_failures": self._poll_failures,
                "refusal_drains": {
                    "limit_bytes": DRAIN_BYTES,
                    "limit_seconds": DRAIN_SECONDS,
                    "slots": DRAIN_SLOTS,
                    "in_flight": self._drains_in_flight,
                    "peak": self._drains_peak,
                    **self._drain_outcomes,
                },
            }
            if workspace_id is not None:
                document["workspace_in_flight"] = {
                    name: self._workspaces.get((name, workspace_id), 0) for name in self._classes
                }
            return document


def claim_workspace(scope: Scope, workspace_id: uuid.UUID) -> None:
    """Claim the caller's workspace for the request this scope belongs to, if it was admitted.

    A scope with no ticket is a request this middleware did not admit: an exempt route, or an
    application built without it. Neither has a share to hold.
    """
    ticket = scope.get(TICKET_SCOPE_KEY)
    if isinstance(ticket, Ticket):
        ticket.admission.claim_workspace(ticket, workspace_id)


# -- the middleware ---------------------------------------------------------------------------


class AdmissionMiddleware:
    """Pure ASGI, inside the body limit and ahead of routing."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        admission: Admission,
        routes: Mapping[tuple[str, str], str] = CAPACITY_ROUTES,
    ) -> None:
        self._app = app
        self._admission = admission
        self._routes: tuple[tuple[str, re.Pattern[str], str], ...] = tuple(
            (method, compile_path(path)[0], capacity) for (method, path), capacity in routes.items()
        )

    def classify(self, scope: Scope) -> str:
        method = scope["method"].upper()
        method = "GET" if method == "HEAD" else method
        path = _route_path(scope)
        for declared, pattern, capacity in self._routes:
            if declared == method and pattern.fullmatch(path):
                return capacity
        return REQUESTS

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        capacity = self.classify(scope)
        if capacity == EXEMPT:
            await self._app(scope, receive, send)
            return
        ticket = self._admission.try_acquire(capacity)
        if ticket is None:
            await self._refuse(scope, receive, send, CapacityRefused(capacity, workspace=False))
            return
        scope[TICKET_SCOPE_KEY] = ticket
        try:
            await self._app(scope, self._deadlined(receive, capacity), send)
        finally:
            self._admission.release(ticket)

    async def _refuse(
        self, scope: Scope, receive: Receive, send: Send, refused: CapacityRefused
    ) -> None:
        """The refusal, sent from here because nothing of the application runs for it.

        A request with a body ends its connection with the answer, as the body limit's does: an
        unread body must never be read as the next request on the connection. Its answer is sent
        first, so a client that reads before it has finished sending has it at once, and its body
        is then drained within the bounds, so a client that reads only after sending meets the
        answer rather than a reset.
        """
        payload = json.dumps(refused.body()).encode("utf-8")
        has_body = _has_body(scope)
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode("ascii")),
            *(
                (key.lower().encode("ascii"), value.encode("ascii"))
                for key, value in refused.headers().items()
            ),
        ]
        if has_body:
            headers.append((b"connection", b"close"))
        await send({"type": "http.response.start", "status": refused.status, "headers": headers})
        if not has_body:
            await send({"type": "http.response.body", "body": payload})
            return
        if not _drainable(scope):
            self._admission.note_closed()
            await send({"type": "http.response.body", "body": payload})
            return
        if not self._admission.try_drain():
            await send({"type": "http.response.body", "body": payload})
            return
        outcome = "cut"
        try:
            await send({"type": "http.response.body", "body": payload, "more_body": True})
            outcome = await _drain(receive)
        finally:
            self._admission.end_drain(outcome)
        await send({"type": "http.response.body", "body": b""})

    def _deadlined(self, receive: Receive, capacity: str) -> Receive:
        """``receive``, bounded while the body is incomplete and passed through after it.

        After the last body message a call to ``receive`` is a wait for the client to leave, which
        a stream makes for its whole life, so it is not timed.
        """
        started = time.monotonic()
        total = BODY_SECONDS[capacity]
        complete = False
        admission = self._admission

        async def deadlined() -> Message:
            nonlocal complete
            if complete:
                return await receive()
            remaining = total - (time.monotonic() - started)
            wait = min(BODY_IDLE_SECONDS, remaining)
            message: Message | None = None
            if wait > 0:
                with anyio.move_on_after(wait):
                    message = await receive()
            if message is None:
                admission.note_body_timeout(capacity)
                raise BodyTimeout(
                    f"the request body stopped arriving: {_seconds(BODY_IDLE_SECONDS)} between "
                    f"pieces, or {_seconds(total)} in total, is the most this server waits"
                )
            if message["type"] != "http.request" or not message.get("more_body", False):
                complete = True
            return message

        return deadlined


def _seconds(value: float) -> str:
    return f"{value:g} second" + ("" if value == 1 else "s")


def _route_path(scope: Scope) -> str:
    """The path routing matches, without the root path a proxy mounted the application under."""
    path: str = scope["path"]
    root = scope.get("root_path", "")
    if root and path.startswith(root) and (len(path) == len(root) or path[len(root)] == "/"):
        return path[len(root) :] or "/"
    return path


def _has_body(scope: Scope) -> bool:
    for name, value in scope.get("headers", ()):
        if name == b"transfer-encoding":
            return True
        if name == b"content-length":
            return value.strip() not in (b"", b"0")
    return False


def _drainable(scope: Scope) -> bool:
    """Whether a refused body is worth reading: not declared over :data:`DRAIN_BYTES`, and not
    held back by a client that waits for ``100 Continue``, which the answer already replaces."""
    for name, value in scope.get("headers", ()):
        if name == b"expect" and value.strip().lower() == b"100-continue":
            return False
        if name == b"content-length":
            text = value.strip()
            if text.isdigit() and int(text) > DRAIN_BYTES:
                return False
    return True


async def _drain(receive: Receive) -> str:
    """Read and discard a refused body, within :data:`DRAIN_BYTES` and :data:`DRAIN_SECONDS`.

    Returns the outcome :data:`DRAIN_OUTCOMES` names. Every piece is dropped as it arrives, so the
    drain holds no more of the body than the server buffers for any connection.
    """
    read = 0
    with anyio.move_on_after(DRAIN_SECONDS):
        while True:
            try:
                message = await receive()
            except HTTPException:
                # The body limit outside this middleware cut a body without a declared length.
                return "cut"
            if message["type"] != "http.request":
                return "left"
            read += len(message.get("body", b""))
            if not message.get("more_body", False):
                return "drained"
            if read > DRAIN_BYTES:
                return "cut"
    return "cut"
