"""Hosted calls end on time, cost what the ledger says, and name who served them.

The transport tests reach a real HTTP server on loopback through the real ``HttpxTransport``,
with an allowlist naming only that server: a scripted transport cannot stall, trickle or refuse a
connection the way a socket does, and those are the three behaviours at issue. Nothing here
reaches the network beyond loopback, reads a key or spends money.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.egress import parse_egress_allowlist
from exulanica.models.errors import BudgetExceededError, ManifestError, TransportError
from exulanica.models.lens_budget import LensBudget, LensBudgetGuard
from exulanica.models.manifest import MANIFEST_PATH, Role, load_manifest, parse_manifest
from exulanica.models.results import NO_MODEL_IN_RESPONSE
from exulanica.models.transport import HttpResponse, HttpxTransport
from exulanica.models.usage import CallOutcome, CallUsage, CostBasis, usd_string
from exulanica.selection.calls import CallLog

from model_fakes import FakeTransport, RecordingPolicy, chat_body

ROOT = Path(__file__).resolve().parents[1]
MESSAGES = [{"role": "user", "content": "hi"}]

#: How far past its deadline a request may return on a loaded test machine. The deadline is what
#: is tested; this is scheduling slack, and it is far below every stall the servers impose.
SLACK_S = 0.5


# -- a local endpoint ------------------------------------------------------------------------


class _Endpoint:
    """A loopback server whose next reply is chosen by the test: late, trickled, or an error."""

    def __init__(self) -> None:
        self.behaviour: Callable[[http.server.BaseHTTPRequestHandler], None] = _answer
        self.requests = 0
        endpoint = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                self.rfile.read(int(self.headers.get("content-length") or 0))
                endpoint.requests += 1
                # The client may stop waiting, which is what these tests want.
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    endpoint.behaviour(self)

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.origin = f"http://localhost:{self._server.server_port}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def _send(handler: http.server.BaseHTTPRequestHandler, status: int, body: bytes) -> None:
    handler.send_response(status)
    handler.send_header("content-type", "application/json")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _answer(handler: http.server.BaseHTTPRequestHandler) -> None:
    _send(handler, 200, json.dumps(chat_body("on time")).encode())


def _late(seconds: float) -> Callable[[http.server.BaseHTTPRequestHandler], None]:
    def behave(handler: http.server.BaseHTTPRequestHandler) -> None:
        time.sleep(seconds)
        _answer(handler)

    return behave


def _trickled(gap_s: float, pieces: int) -> Callable[[http.server.BaseHTTPRequestHandler], None]:
    """A whole, valid body, sent in ``pieces`` with ``gap_s`` between them: every gap is inside
    a per-read timeout, and the sum is not."""

    def behave(handler: http.server.BaseHTTPRequestHandler) -> None:
        body = json.dumps(chat_body("trickled")).encode()
        handler.send_response(200)
        handler.send_header("content-type", "application/json")
        handler.send_header("content-length", str(len(body)))
        handler.end_headers()
        size = -(-len(body) // pieces)
        for start in range(0, len(body), size):
            handler.wfile.write(body[start : start + size])
            handler.wfile.flush()
            time.sleep(gap_s)

    return behave


def _status(code: int) -> Callable[[http.server.BaseHTTPRequestHandler], None]:
    def behave(handler: http.server.BaseHTTPRequestHandler) -> None:
        _send(handler, code, b'{"error": {"message": "the endpoint had a bad moment"}}')

    return behave


@pytest.fixture
def endpoint() -> Iterator[_Endpoint]:
    served = _Endpoint()
    yield served
    served.close()


def _manifest_at(origin: str):
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    document["base_url"] = f"{origin}/v1"
    return parse_manifest(document)


def _transport(origin: str) -> HttpxTransport:
    return HttpxTransport(egress=parse_egress_allowlist([origin]))


def _client(origin: str, *, budget: BudgetGuard | None = None, **kwargs: Any) -> ModelClient:
    return ModelClient(
        api_key="test-key-not-real",
        manifest=_manifest_at(origin),
        transport=_transport(origin),
        budget=budget if budget is not None else BudgetGuard(),
        sleep=lambda _seconds: None,
        policy=RecordingPolicy(),
        **kwargs,
    )


def _closed_port_origin() -> str:
    """An origin on loopback where nothing listens, so a connection is refused before it forms."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://localhost:{port}"


def _timed(action: Callable[[], Any]) -> tuple[float, BaseException | None]:
    started = time.monotonic()
    try:
        action()
    except BaseException as exc:
        return time.monotonic() - started, exc
    return time.monotonic() - started, None


# -- the deadline ----------------------------------------------------------------------------


def test_a_response_inside_the_timeout_is_returned(endpoint):
    """The positive control: the deadline machinery returns a prompt answer untouched."""
    response = _transport(endpoint.origin).post_json(
        f"{endpoint.origin}/v1/chat/completions", headers={}, payload={}, timeout=2.0
    )
    assert response.status_code == 200
    assert json.loads(response.text)["choices"][0]["message"]["content"] == "on time"


def test_a_stalled_response_ends_at_the_timeout_and_says_it_may_be_billed(endpoint):
    endpoint.behaviour = _late(3.0)
    elapsed, error = _timed(
        lambda: _transport(endpoint.origin).post_json(
            f"{endpoint.origin}/v1/chat/completions", headers={}, payload={}, timeout=0.5
        )
    )
    assert isinstance(error, TransportError)
    assert error.timed_out is True
    assert error.reached_provider is None
    assert elapsed < 0.5 + SLACK_S


def test_a_trickled_response_ends_at_the_timeout_not_after_it(endpoint):
    """Measured before the deadline existed: a 1 s timeout returned after 4.84 s, because httpx
    applies the timeout to each read and every piece arrived inside one."""
    endpoint.behaviour = _trickled(gap_s=0.3, pieces=8)
    elapsed, error = _timed(
        lambda: _transport(endpoint.origin).post_json(
            f"{endpoint.origin}/v1/chat/completions", headers={}, payload={}, timeout=1.0
        )
    )
    assert isinstance(error, TransportError), f"returned after {elapsed:.2f} s"
    assert error.timed_out is True
    assert elapsed < 1.0 + SLACK_S


def test_a_refused_connection_is_known_never_to_have_left():
    origin = _closed_port_origin()
    _, error = _timed(
        lambda: _transport(origin).post_json(
            f"{origin}/v1/chat/completions", headers={}, payload={}, timeout=2.0
        )
    )
    assert isinstance(error, TransportError)
    assert error.reached_provider is False
    assert error.timed_out is False


# -- what the ledger and the guard record ------------------------------------------------------


def test_a_completed_call_is_recorded_as_reported(endpoint):
    """The positive control for the ledger rows below."""
    client = _client(endpoint.origin)
    client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v", use_cache=False)
    (row,) = client.ledger.calls
    assert row.cost_basis is CostBasis.REPORTED
    assert row.outcome is CallOutcome.COMPLETED
    assert row.usd > 0


def test_every_timed_out_attempt_is_charged_its_reservation_and_counted(endpoint):
    """Before: three timed-out attempts left the ledger empty, spent_usd 0, billed_calls 0."""
    endpoint.behaviour = _late(3.0)
    client = _client(endpoint.origin, timeout=0.3, max_attempts=3)
    reservation = client.budget.estimate_usd(
        client.manifest[Role.REASONING_CHEAP].primary,
        prompt_chars=sum(len(str(m)) for m in MESSAGES),
        max_tokens=client.manifest[Role.REASONING_CHEAP].default_max_tokens,
    )
    with pytest.raises(TransportError, match="cost is unknown") as raised:
        client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v", use_cache=False)

    rows = client.ledger.calls
    assert [row.outcome for row in rows] == [CallOutcome.TIMED_OUT] * 3
    assert all(row.cost_basis is CostBasis.UNKNOWN and not row.usd_known for row in rows)
    assert all(row.usd == reservation > 0 for row in rows)
    assert client.budget.spent_usd == 3 * reservation
    assert client.ledger.usd_unknown == 3 * reservation
    assert client.budget.billed_calls == 3
    assert usd_string(reservation) in str(raised.value)


def test_an_error_status_is_charged_as_unknown(endpoint):
    endpoint.behaviour = _status(500)
    client = _client(endpoint.origin)
    with pytest.raises(TransportError):
        client.chat(Role.STRUCTURED_EXTRACTION, MESSAGES, prompt_version="v", use_cache=False)
    (row,) = client.ledger.calls
    assert row.cost_basis is CostBasis.UNKNOWN
    assert row.outcome is CallOutcome.FAILED
    assert row.usd > 0
    assert "HTTP 500" in row.failure


def test_a_connection_never_made_is_recorded_at_a_known_zero():
    client = _client(_closed_port_origin())
    with pytest.raises(TransportError, match="cost nothing"):
        client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v", use_cache=False)
    (row,) = client.ledger.calls
    assert row.cost_basis is CostBasis.NOT_SENT
    assert row.usd_known and row.usd == 0
    assert client.budget.billed_calls == 1


def test_the_budget_spends_an_unknown_cost_before_it_allows_another_call(endpoint):
    """The guard counts the row the way the ledger states it: at its bound."""
    endpoint.behaviour = _late(3.0)
    spec = load_manifest()[Role.REASONING_CHEAP].primary
    probe = BudgetGuard()
    one = probe.estimate_usd(
        spec,
        prompt_chars=sum(len(str(m)) for m in MESSAGES),
        max_tokens=load_manifest()[Role.REASONING_CHEAP].default_max_tokens,
    )
    guard = BudgetGuard(ceiling_usd=one + one / 2)
    client = _client(endpoint.origin, budget=guard, timeout=0.3)
    with pytest.raises(TransportError):
        client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v", use_cache=False)
    endpoint.behaviour = _answer
    with pytest.raises(BudgetExceededError):
        client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v", use_cache=False)
    assert endpoint.requests == 1


def test_failed_attempts_count_toward_the_call_ceiling():
    client = _client(_closed_port_origin(), budget=BudgetGuard(max_calls=2), max_attempts=5)
    with pytest.raises(BudgetExceededError, match="call ceiling"):
        client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v", use_cache=False)
    assert client.budget.billed_calls == 2


def test_a_reply_without_usage_is_charged_its_bound_not_zero(manifest):
    body = chat_body("fine")
    del body["usage"]
    transport = FakeTransport([HttpResponse(status_code=200, text=json.dumps(body))])
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(),
        policy=RecordingPolicy(),
    )
    client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v", use_cache=False)
    (row,) = client.ledger.calls
    assert row.cost_basis is CostBasis.UNKNOWN
    assert row.outcome is CallOutcome.COMPLETED
    assert row.usd > 0


def test_a_lens_keeps_an_unknown_attempt_at_its_reservation_and_releases_one_never_sent():
    spec = load_manifest()[Role.REASONING_CHEAP].primary
    budget = LensBudget(
        max_tokens=100_000, max_calls=10, max_wall_clock_ms=600_000, max_cost_usd=Decimal("1")
    )
    guard = LensBudgetGuard("lens.test", budget, per_call_timeout_ms=1000)
    reserved = guard.reserve(spec, role=Role.REASONING_CHEAP, prompt_chars=300, max_tokens=700)
    tokens = guard.tokens_committed
    guard.record(
        CallUsage.failed(
            role=Role.REASONING_CHEAP,
            spec=spec,
            reached_provider=None,
            timed_out=True,
            failure="timed out",
            usd_bound=reserved,
        )
    )
    assert guard.usd_committed == reserved
    assert guard.tokens_committed == tokens

    guard.reserve(spec, role=Role.REASONING_CHEAP, prompt_chars=300, max_tokens=700)
    guard.record(
        CallUsage.failed(
            role=Role.REASONING_CHEAP,
            spec=spec,
            reached_provider=False,
            timed_out=False,
            failure="refused",
            usd_bound=reserved,
        )
    )
    assert guard.usd_committed == reserved
    assert guard.tokens_committed == tokens


# -- the timeout is the manifest's -----------------------------------------------------------


def test_each_role_is_sent_with_its_manifest_timeout(manifest):
    seen: list[float] = []

    class Recording(FakeTransport):
        def post_json(self, url, *, headers, payload, timeout):
            seen.append(timeout)
            return super().post_json(url, headers=headers, payload=payload, timeout=timeout)

    client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=Recording(),
        budget=BudgetGuard(),
        policy=RecordingPolicy(),
    )
    for role in (Role.REASONING_CHEAP, Role.STRUCTURED_EXTRACTION, Role.VISION):
        seen.clear()
        client.chat(role, MESSAGES, prompt_version="v", use_cache=False)
        assert seen == [float(manifest[role].timeout_seconds)], role
    assert len({manifest[role].timeout_seconds for role in Role}) > 1


def test_an_explicit_timeout_overrides_every_role(manifest):
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=FakeTransport(),
        budget=BudgetGuard(),
        policy=RecordingPolicy(),
        timeout=7.0,
    )
    assert client.worst_case_seconds(Role.EMBEDDING) == pytest.approx(7.0)


def test_every_role_timeout_follows_from_its_basis_and_the_record_it_names(manifest):
    """The basis is the survey record's own numbers, and the timeout is the rule applied to them."""
    for role in Role:
        binding = manifest[role]
        basis = binding.timeout_basis
        record = json.loads((ROOT / basis["record"]).read_text(encoding="utf-8"))["record"]
        measured = record["measured"]["roles"][str(role)]
        assert measured["primary"] == binding.primary.model_id == basis["model"]
        primary = measured["primary_measured"]
        for key in ("rows", "p50_ms", "p99_ms", "longest_ms"):
            assert basis[key] == primary[key], (role, key)
        assert binding.timeout_seconds == manifest.timeout_rule.timeout_for(basis["longest_ms"])
        assert binding.timeout_seconds * 1000 >= basis["longest_ms"]


def _document() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)


def test_a_timeout_its_basis_does_not_produce_is_refused():
    document = _document()
    document["roles"]["reasoning_cheap"]["timeout_seconds"] = 180
    with pytest.raises(ManifestError, match="may not disagree"):
        parse_manifest(document)


def test_a_basis_measured_on_another_model_is_refused():
    document = _document()
    document["roles"]["reasoning_cheap"]["timeout_basis"]["model"] = "nvidia/Nemotron-3_5-Lightning"
    with pytest.raises(ManifestError, match="rests on the model it bounds"):
        parse_manifest(document)


def test_a_role_without_a_timeout_is_refused():
    document = _document()
    del document["roles"]["embedding"]["timeout_seconds"]
    with pytest.raises(ManifestError, match="timeout_seconds"):
        parse_manifest(document)


# -- the embedding call names who served it --------------------------------------------------


def _embedding_client(manifest, body: dict[str, Any]) -> ModelClient:
    return ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=FakeTransport([HttpResponse(status_code=200, text=json.dumps(body))]),
        budget=BudgetGuard(),
        policy=RecordingPolicy(),
    )


def _embedding_body(**extra: Any) -> dict[str, Any]:
    return {
        "object": "list",
        "data": [{"object": "embedding", "index": 0, "embedding": [1.0] + [0.0] * 4095}],
        "usage": {"prompt_tokens": 2, "total_tokens": 2},
        **extra,
    }


def test_the_embedding_record_names_the_model_the_response_named(manifest):
    served = manifest[Role.EMBEDDING].primary.model_id
    result = _embedding_client(manifest, _embedding_body(model=served)).embed(
        ["sign"], use_cache=False
    )
    log = CallLog()
    log.record_embedding(result, 12)
    (call,) = log.calls
    assert call.served_model == served
    assert call.served_model_unavailable is None
    assert call.attempts == 1
    # Two prompt tokens at the embedding price, written as an invoice writes it.
    assert call.usd == "0.00000002"


def test_an_embedding_response_naming_no_model_is_recorded_with_the_reason(manifest):
    result = _embedding_client(manifest, _embedding_body()).embed(["sign"], use_cache=False)
    log = CallLog()
    log.record_embedding(result, 12)
    (call,) = log.calls
    assert call.served_model is None
    assert call.served_model_unavailable == NO_MODEL_IN_RESPONSE
    assert call.requested_model == manifest[Role.EMBEDDING].primary.model_id


def test_the_served_model_is_never_filled_from_the_request(manifest):
    """The echo is an observation: a different identifier in the body is recorded as sent."""
    result = _embedding_client(manifest, _embedding_body(model="someone/else")).embed(
        ["sign"], use_cache=False
    )
    assert result.served_model_id == "someone/else"
    assert result.model_id == manifest[Role.EMBEDDING].primary.model_id
