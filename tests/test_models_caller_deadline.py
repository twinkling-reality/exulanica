"""An optional call's caller deadline in the one client: its refusal, its outcome and its charge.

A caller whose answer is already in hand without a call may give it a shorter wait than its role's
manifest timeout (``deadline_s`` on ``ModelClient.chat`` and ``ModelClient.structured``), never a
longer one. An attempt the deadline ends is recorded as ``deadline_ended`` and charged exactly as a
timeout is, its reservation; an attempt left no time to be sent is recorded as never sent, at no
cost. Every clock here is the test's own, so nothing waits and no wall time is asserted.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import TransportError
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.models.usage import CallOutcome, CostBasis
from exulanica.selection.calls import AttemptOutcome, CallCost, CallLog

from model_fakes import FakeTransport, RecordingPolicy, model_not_found

#: A role with a fallback, so one deadline can be seen to span the primary and the fallback.
ROLE = Role.ANSWER_COMPOSER
MESSAGES = [{"role": "user", "content": "Which line?"}]


class _Clock:
    """A clock that moves only when a request says it took time."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Timed(FakeTransport):
    """Each reply takes ``took`` seconds on ``clock``; a reply that would outlast the wait it was
    given raises the transport's timeout, as ``HttpxTransport`` does, after that wait."""

    def __init__(self, clock: _Clock, replies: list[tuple[float, HttpResponse]]) -> None:
        super().__init__()
        self.clock = clock
        self.replies = list(replies)
        self.waits: list[float] = []

    def post_json(self, url, *, headers, payload, timeout) -> HttpResponse:
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        self.waits.append(timeout)
        took, reply = self.replies.pop(0)
        if took > timeout:
            self.clock.now += timeout
            raise TransportError(
                f"no whole response within {timeout:g} s", timed_out=True, reached_provider=None
            )
        self.clock.now += took
        return reply


def _client(transport: _Timed, *, max_attempts: int = 1) -> tuple[ModelClient, BudgetGuard]:
    budget = BudgetGuard(ceiling_usd=Decimal("1"), max_calls=50)
    client = ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=budget,
        policy=RecordingPolicy(),
        clock=transport.clock,
        max_attempts=max_attempts,
        sleep=lambda _seconds: None,
    )
    return client, budget


def _timeout() -> float:
    return float(load_manifest()[ROLE].timeout_seconds)


def _ok() -> HttpResponse:
    return FakeTransport().post_json("", headers={}, payload={"model": "m"}, timeout=1)


def test_a_deadline_longer_than_the_role_s_timeout_is_refused_by_name_and_nothing_is_sent():
    clock = _Clock()
    transport = _Timed(clock, [(1.0, _ok())])
    client, budget = _client(transport)
    with pytest.raises(ValueError, match=r"^deadline_exceeds_role_timeout: "):
        client.chat(ROLE, MESSAGES, prompt_version="t", deadline_s=_timeout() + 1)
    with pytest.raises(ValueError, match=r"^deadline_not_positive: "):
        client.chat(ROLE, MESSAGES, prompt_version="t", deadline_s=0)
    assert transport.requests == [] and len(budget.ledger) == 0
    # Positive control: the role's own timeout is a deadline it may be given.
    client.chat(ROLE, MESSAGES, prompt_version="t", deadline_s=_timeout())
    assert transport.waits == [_timeout()]


def test_an_attempt_waits_the_time_left_of_the_deadline():
    clock = _Clock()
    transport = _Timed(clock, [(1.0, _ok()), (1.0, _ok())])
    client, _ = _client(transport)
    client.chat(ROLE, MESSAGES, prompt_version="t", deadline_s=7)
    client.chat(ROLE, MESSAGES, prompt_version="t")
    assert transport.waits == [7.0, _timeout()]


def test_an_attempt_the_deadline_ends_is_charged_exactly_as_a_timeout_is():
    """The same slow reply, once ended by the role's timeout and once by a caller's deadline: the
    same charge, the reservation, with its cost unknown; only the outcome's name differs."""
    slow = _timeout() + 1
    clock = _Clock()
    transport = _Timed(clock, [(slow, _ok())] * 4)
    client, budget = _client(transport, max_attempts=3)
    log = CallLog()
    observed = client.with_attempts(log.attempt)
    with pytest.raises(TransportError) as timed_out:
        observed.chat(ROLE, MESSAGES, prompt_version="t", use_cache=False)
    with pytest.raises(TransportError) as ended:
        observed.chat(ROLE, MESSAGES, prompt_version="t", use_cache=False, deadline_s=5)
    timeout_row, deadline_row = budget.ledger.calls[-2:]
    assert timeout_row.outcome is CallOutcome.TIMED_OUT
    assert deadline_row.outcome is CallOutcome.DEADLINE_ENDED
    assert deadline_row.cost_basis is timeout_row.cost_basis is CostBasis.UNKNOWN
    assert deadline_row.usd == timeout_row.usd > 0
    assert deadline_row.provider == timeout_row.provider
    assert ended.value.deadline_ended and not timed_out.value.deadline_ended
    # Never retried: the caller's answer is already in hand. The timeout was retried as asked.
    assert not ended.value.retryable
    assert len(transport.requests) == 3 + 1
    assert [call.outcome for call in log.calls][-1] is AttemptOutcome.DEADLINE_ENDED
    assert log.calls[-1].cost_basis is CallCost.UNKNOWN


def test_no_time_left_sends_nothing_and_records_the_attempt_as_never_sent_at_no_cost():
    """The primary is withdrawn after the whole deadline: the fallback is not sent, and its row
    says so at no cost, while the primary's attempt is charged as a sent request is."""
    clock = _Clock()
    manifest = load_manifest()
    primary = manifest[ROLE].primary.model_id
    transport = _Timed(clock, [(5.0, model_not_found(primary))])
    client, budget = _client(transport)
    log = CallLog()
    with pytest.raises(TransportError) as ended:
        client.with_attempts(log.attempt).chat(ROLE, MESSAGES, prompt_version="t", deadline_s=5)
    assert len(transport.requests) == 1
    assert ended.value.deadline_ended and ended.value.reached_provider is False
    withdrawn, unsent = budget.ledger.calls
    assert withdrawn.model_id == primary and withdrawn.usd > 0
    assert unsent.model_id == manifest[ROLE].fallback.model_id
    assert unsent.outcome is CallOutcome.DEADLINE_ENDED
    assert unsent.cost_basis is CostBasis.NOT_SENT and unsent.usd == 0
    assert budget.spent_usd == withdrawn.usd
    assert log.calls[-1].outcome is AttemptOutcome.DEADLINE_ENDED
    assert log.calls[-1].cost_basis is CallCost.NOT_SENT
