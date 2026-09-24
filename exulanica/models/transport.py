"""The HTTP seam.

The client never touches ``httpx`` directly. It goes through ``Transport``, a two-method
protocol, for one reason that is worth the indirection: the fallback path, the budget refusal,
the max_tokens floor and the reasoning split all have to be exercised by tests that spend no
money. A test supplies a ``Transport`` that returns canned bodies, and the code under test is
the same code that runs in production, rather than a mock of it.

The default implementation is ``httpx``. Nothing here retries: retry policy belongs with the
caller that knows whether the operation is idempotent, and a transport that silently retries a
non-idempotent call is a billing surprise.

**The egress allowlist bites here**, because this is the one place in the model path that reaches
the network. :class:`HttpxTransport` will not build a network client without an
:class:`~exulanica.models.egress.EgressAllowlist`, read from the environment when none is passed,
and it holds every call to it twice: once against the URL before the client is asked, and once
inside the client against the request it is about to send, which is the check a redirect hop
passes through as well. Redirects are not followed in any case. A refusal is raised as
:class:`~exulanica.models.egress.EgressRefused` and is never folded into ``TransportError``,
because a ``TransportError`` is retryable by default and a refused destination must not be.

**The timeout is a deadline on the whole request**, measured on the monotonic clock from the moment
the request is handed over. httpx applies one float to connect, read, write and pool separately and
has no total-request timeout, so a response that arrives one chunk inside every read timeout was
never cut off: measured on a local server, a 1 s timeout returned after 4.84 s. The request now runs
on a worker thread that streams the body and checks the deadline after every chunk, and the caller
waits for that thread no longer than the deadline, so name resolution, a slow connect and a trickled
body all end at it. A worker still reading when the caller has gone is abandoned; its next chunk, or
httpx's own per-read timeout, ends it within one more timeout.

**A failure says whether the request left.** A connection that was never made cannot have been
billed; a request that was sent and not answered in full may have been. :class:`TransportError`
carries that as ``reached_provider`` and the ledger prices the attempt from it; see
:mod:`exulanica.models.usage`.

An injected ``client`` is the seam tests use to avoid the network. A real ``httpx.Client``
passed that way still needs an allowlist, and nothing in the package passes one:
``tests/test_egress_allowlist.py`` greps for it. A test double that is not an ``httpx.Client``
reaches no network, and this seam does not police what it does.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from exulanica.models.egress import (
    EgressAllowlist,
    EgressConfigurationError,
    EgressRefused,
    load_egress_allowlist,
)
from exulanica.models.errors import TransportError

__all__ = [
    "HttpResponse",
    "HttpxTransport",
    "Transport",
    "allowlisted_httpx_client",
    "allowlisted_transport",
]


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """One HTTP response, already read. Status, headers, decoded body, raw text."""

    status_code: int
    text: str
    headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json_body(self) -> Any:
        """Decode the body, or raise ``TransportError`` naming the status.

        A non-JSON body from this endpoint is nearly always an HTML error page from something in
        front of the model, so the status code is the useful part of the message.
        """
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            excerpt = self.text[:200]
            raise TransportError(f"HTTP {self.status_code} body is not JSON: {excerpt!r}") from exc

    def error_message(self) -> str:
        """Best-effort provider error string, used to classify a 400 as model-not-found."""
        try:
            body = json.loads(self.text)
        except json.JSONDecodeError:
            return self.text[:400]
        if isinstance(body, Mapping):
            error = body.get("error")
            if isinstance(error, Mapping):
                return str(error.get("message") or error)
            if error is not None:
                return str(error)
            if "message" in body:
                return str(body["message"])
        return self.text[:400]


class Transport(Protocol):
    """What the client needs from the network, and nothing more."""

    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> HttpResponse: ...

    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse: ...


def allowlisted_transport(
    egress: EgressAllowlist, *, http: Any | None = None, inner: Any | None = None
) -> Any:
    """A transport that holds every request to ``egress`` immediately before it connects.

    ``http`` is the HTTP client module, ``httpx`` by default. ``httpx2`` has the same transport
    shape, and the Google sign-in path uses it, so one check serves both rather than two copies
    that can drift. ``inner`` is what actually sends, a real ``HTTPTransport`` by default; a test
    passes a mock, and the check still runs in front of it.
    """
    if http is None:
        import httpx as http  # imported lazily so tests never need the dependency loaded

    class _AllowlistedTransport(http.BaseTransport):
        def __init__(self, wrapped: Any) -> None:
            self._wrapped = wrapped

        def handle_request(self, request: Any) -> Any:
            url = request.url
            egress.require_parts(
                scheme=url.scheme,
                host=url.raw_host.decode("ascii"),
                port=url.port,
                userinfo=url.userinfo,
            )
            return self._wrapped.handle_request(request)

        def close(self) -> None:
            self._wrapped.close()

    return _AllowlistedTransport(inner if inner is not None else http.HTTPTransport())


def allowlisted_httpx_client(
    egress: EgressAllowlist, *, inner: Any | None = None, follow_redirects: bool = False
) -> Any:
    """An ``httpx.Client`` whose every outgoing request is held to ``egress`` before it connects.

    The check is a transport mounted inside the client, so it sees each request after httpx has
    parsed it and before a connection is opened, and it sees every hop of a redirect chain as its
    own request. ``inner`` and ``follow_redirects`` exist so a test can prove that; the defaults
    are what runs. Environment proxies are not consulted, because httpx ignores them once a
    transport is supplied, and a proxy the environment names is a destination this list does not.
    """
    import httpx  # imported lazily so tests never need the dependency loaded

    return httpx.Client(
        transport=allowlisted_transport(egress, http=httpx, inner=inner),
        follow_redirects=follow_redirects,
    )


class HttpxTransport:
    """The real transport. One pooled client, reused across calls.

    Pooling matters at ingest: a corpus pass is one call per photograph, and a fresh TLS
    handshake per photograph is latency paid for nothing.
    """

    def __init__(self, *, client: Any | None = None, egress: EgressAllowlist | None = None) -> None:
        if client is None:
            egress = egress if egress is not None else load_egress_allowlist()
            client = allowlisted_httpx_client(egress)
        elif egress is None:
            httpx = sys.modules.get("httpx")
            if httpx is not None and isinstance(client, httpx.Client):
                raise EgressConfigurationError(
                    "an httpx.Client reaches the network, so HttpxTransport needs an egress "
                    "allowlist to go with it. Pass egress=, or pass no client at all."
                )
        self._client = client
        #: None only for an injected test double, which reaches no network.
        self.egress = egress

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> HttpxTransport:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> HttpResponse:
        if self.egress is not None:
            self.egress.require(url)
        return self._within_deadline(
            "POST", url, timeout, headers=dict(headers), json=dict(payload)
        )

    def get_json(self, url: str, *, headers: Mapping[str, str], timeout: float) -> HttpResponse:
        if self.egress is not None:
            self.egress.require(url)
        return self._within_deadline("GET", url, timeout, headers=dict(headers))

    def _within_deadline(
        self, method: str, url: str, timeout: float, **request: Any
    ) -> HttpResponse:
        """One request, returned or refused by ``timeout`` seconds from now, however it stalls."""
        if not timeout > 0:
            raise ValueError(f"a request timeout must be positive, got {timeout!r}")
        deadline = time.monotonic() + timeout
        outcome: dict[str, Any] = {}

        def send() -> None:
            try:
                outcome["response"] = self._read(method, url, deadline, timeout, request)
            except BaseException as exc:  # handed to the caller's thread, which raises it
                outcome["error"] = exc

        worker = threading.Thread(target=send, name=f"model-request {method}", daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            raise _deadline_passed(method, url, timeout)
        error = outcome.get("error")
        if error is None:
            response: HttpResponse = outcome["response"]
            return response
        if isinstance(error, EgressRefused | TransportError):
            # Raised by the mounted check inside the client (not a transport failure, and not
            # retryable), or already classified by the deadline check below.
            raise error
        raise _classified(method, url, error) from error

    def _read(
        self,
        method: str,
        url: str,
        deadline: float,
        timeout: float,
        request: Mapping[str, Any],
    ) -> HttpResponse:
        with self._client.stream(method, url, timeout=timeout, **request) as response:
            chunks: list[bytes] = []
            for chunk in response.iter_bytes():
                chunks.append(chunk)
                if time.monotonic() > deadline:
                    raise _deadline_passed(method, url, timeout)
            return HttpResponse(
                status_code=int(response.status_code),
                text=b"".join(chunks).decode(response.encoding or "utf-8", errors="replace"),
                headers={k.lower(): v for k, v in response.headers.items()},
            )


def _deadline_passed(method: str, url: str, timeout: float) -> TransportError:
    return TransportError(
        f"{method} {url} timed out: no whole response within {timeout:g} s. The request was "
        "sent, so the provider may still bill for it.",
        timed_out=True,
        reached_provider=None,
    )


def _classified(method: str, url: str, exc: BaseException) -> TransportError:
    """Every httpx failure mode as one type, saying whether it timed out and whether it left.

    The caller's retry decision is the same for a timeout, a DNS failure and a reset connection,
    so they stay one type. What differs is the bill: a connection that was never made carries no
    request, and anything after it may have reached the provider.
    """
    httpx = sys.modules.get("httpx")
    never_left: tuple[type[BaseException], ...] = ()
    timeouts: tuple[type[BaseException], ...] = ()
    if httpx is not None:
        never_left = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
        timeouts = (httpx.TimeoutException,)
    return TransportError(
        f"{method} {url} failed: {exc!r}",
        timed_out=isinstance(exc, timeouts),
        reached_provider=False if isinstance(exc, never_left) else None,
    )
