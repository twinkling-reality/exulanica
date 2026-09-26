"""The process's budget holds each call it admits until the call's usage is recorded.

A reservation that is only checked, never held, lets two calls admitted at once each see room for
itself and together cross the ceiling. Held under one lock, the second sees the first.
"""

from __future__ import annotations

import copy
import json
import threading
from decimal import Decimal

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.egress import EgressRefused
from exulanica.models.errors import BudgetExceededError, BudgetShareExceeded, TransportError
from exulanica.models.lens_budget import LensBudget, LensBudgetGuard
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.policy import BenchmarkInputs
from exulanica.models.transport import HttpResponse
from exulanica.models.usage import CallUsage

from model_fakes import FakeTransport, chat_body

ROLE = Role.REASONING_CHEAP
PROMPT_CHARS = 3000
MAX_TOKENS = 640


def _spec():
    return load_manifest()[ROLE].primary


def _one_call() -> Decimal:
    return BudgetGuard(ceiling_usd=Decimal(1), max_calls=10).estimate_usd(
        _spec(), prompt_chars=PROMPT_CHARS, max_tokens=MAX_TOKENS
    )


def _reserve_together(guard: BudgetGuard, **keep) -> list[object]:
    """Two reservations started at the same moment, and what each came to."""
    barrier = threading.Barrier(2)
    outcomes: list[object] = []
    lock = threading.Lock()

    def call() -> None:
        barrier.wait()
        try:
            outcome: object = guard.reserve(
                _spec(), role=ROLE, prompt_chars=PROMPT_CHARS, max_tokens=MAX_TOKENS, **keep
            )
        except BudgetExceededError as refused:
            outcome = type(refused).__name__
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


def test_two_calls_admitted_at_once_with_room_for_one_admit_one():
    one = _one_call()
    guard = BudgetGuard(ceiling_usd=one * Decimal("1.5"), max_calls=100)
    outcomes = _reserve_together(guard)
    assert sorted(map(str, outcomes)) == sorted([str(one), "BudgetExceededError"])
    assert (guard.held_usd, guard.held_calls) == (one, 1)


def test_two_calls_admitted_at_once_with_one_call_left_admit_one():
    guard = BudgetGuard(ceiling_usd=Decimal(10), max_calls=1)
    outcomes = _reserve_together(guard)
    assert sorted(map(str, outcomes)) == sorted([str(_one_call()), "BudgetExceededError"])
    assert guard.held_calls == 1


def test_a_recorded_call_gives_its_reservation_back_and_charges_what_it_cost():
    one = _one_call()
    guard = BudgetGuard(ceiling_usd=one * Decimal("1.5"), max_calls=100)
    reserved = guard.reserve(_spec(), role=ROLE, prompt_chars=PROMPT_CHARS, max_tokens=MAX_TOKENS)
    usage = CallUsage.failed(
        role=ROLE,
        spec=_spec(),
        reached_provider=False,
        timed_out=False,
        failure="refused before it left",
        usd_bound=reserved,
        used_fallback=False,
        latency_s=0.0,
    )
    guard.record(usage, released=reserved)
    assert (guard.held_usd, guard.held_calls) == (Decimal(0), 0)
    # The positive control: with nothing held, the next call fits again.
    assert guard.reserve(_spec(), role=ROLE, prompt_chars=PROMPT_CHARS, max_tokens=MAX_TOKENS)


def test_a_share_kept_for_other_work_refuses_by_its_own_name_and_leaves_the_rest_usable():
    one = _one_call()
    guard = BudgetGuard(ceiling_usd=one * 3, max_calls=100)
    keep = {"keep_usd": one * 2, "keep_calls": 0}
    guard.reserve(_spec(), role=ROLE, prompt_chars=PROMPT_CHARS, max_tokens=MAX_TOKENS, **keep)
    with pytest.raises(BudgetShareExceeded):
        guard.reserve(_spec(), role=ROLE, prompt_chars=PROMPT_CHARS, max_tokens=MAX_TOKENS, **keep)
    # Work that keeps nothing still has the part the share left untouched.
    assert guard.reserve(_spec(), role=ROLE, prompt_chars=PROMPT_CHARS, max_tokens=MAX_TOKENS)


class _RefusingTransport:
    """A transport that refuses every request before it leaves, as the allowlist does."""

    def __init__(self) -> None:
        self.call_count = 0

    def post_json(self, url, *, headers, payload, timeout):
        self.call_count += 1
        raise EgressRefused("https://nowhere.example.com", "not declared in this test")


def test_a_request_refused_before_it_leaves_gives_its_reservation_back():
    guard = BudgetGuard(ceiling_usd=Decimal(1), max_calls=100)
    transport = _RefusingTransport()
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=transport,
        budget=guard,
        policy=BenchmarkInputs("a fixed test sentence"),
    )
    with pytest.raises(EgressRefused):
        client.chat(ROLE, [{"role": "user", "content": "Hello."}], prompt_version="v1")
    assert transport.call_count == 1
    assert (guard.held_usd, guard.held_calls, guard.billed_calls) == (Decimal(0), 0, 0)


# -- a reply that came back is recorded, whatever it holds -----------------------------------------


def _reply_client(guard: BudgetGuard, *bodies: object, cache: object = None) -> ModelClient:
    replies = [HttpResponse(200, json.dumps(body)) for body in bodies]
    return ModelClient(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=FakeTransport(replies),
        budget=guard,
        policy=BenchmarkInputs("a fixed test sentence"),
        **({} if cache is None else {"cache": cache}),
    )


def _returned_and_charged(guard: BudgetGuard) -> None:
    """The reservation is given back and the attempt is in the ledger, at no less than a cost."""
    assert (guard.held_usd, guard.held_calls) == (Decimal(0), 0)
    assert guard.billed_calls == 1 and guard.spent_usd > 0


def test_a_reply_whose_usage_is_not_an_object_is_charged_its_bound_and_holds_nothing():
    guard = BudgetGuard(ceiling_usd=Decimal(1), max_calls=10)
    body = chat_body("Hello.", model=load_manifest()[ROLE].primary.model_id)
    body["usage"] = ["not", "an", "object"]
    result = _reply_client(guard, body).chat(
        ROLE, [{"role": "user", "content": "Hello."}], prompt_version="v1", use_cache=False
    )
    _returned_and_charged(guard)
    # Absent counts leave the cost unknown, so the call is charged its whole reservation.
    assert result.usage.usd == guard.spent_usd and str(result.usage.cost_basis) == "unknown"


@pytest.mark.parametrize("usage", [["a", "list"], "text", {"completion_tokens_details": "x"}])
def test_a_usage_that_is_not_an_object_reads_as_absent_for_any_caller(usage):
    """Any caller building a call's usage, a script's streamed call among them, gets a row it can
    record: what is not an object is absent, so the cost is unknown and charged at the bound."""
    bound = Decimal("0.00123400")
    row = CallUsage.from_response(role=ROLE, spec=_spec(), usage=usage, usd_bound=bound)
    assert row.usd == bound and str(row.cost_basis) == "unknown"


def test_a_reply_that_is_not_an_object_is_refused_after_it_is_recorded():
    guard = BudgetGuard(ceiling_usd=Decimal(1), max_calls=10)
    with pytest.raises(TransportError, match="expected an object"):
        _reply_client(guard, ["a", "list"]).chat(
            ROLE, [{"role": "user", "content": "Hello."}], prompt_version="v1", use_cache=False
        )
    _returned_and_charged(guard)


def _embedding_body(rows: list[object]) -> dict[str, object]:
    return {"data": rows, "usage": {"prompt_tokens": 3, "total_tokens": 3}, "model": "m"}


def test_an_embedding_row_that_is_not_a_vector_is_refused_after_it_is_recorded():
    guard = BudgetGuard(ceiling_usd=Decimal(1), max_calls=10)
    with pytest.raises(TransportError, match="not a list of number vectors"):
        _reply_client(guard, _embedding_body([None])).embed(["hello"], use_cache=False)
    _returned_and_charged(guard)


class _UnwritableCache:
    """A response cache whose every write fails, as a full disk does."""

    def get(self, key):
        return None

    def put(self, key, entry):
        raise OSError("no space left on the device")


def test_an_embedding_whose_cache_cannot_be_written_is_recorded_first():
    guard = BudgetGuard(ceiling_usd=Decimal(1), max_calls=10)
    dimensions = load_manifest()[Role.EMBEDDING].primary.embedding_dimensions or 8
    body = _embedding_body([{"embedding": [0.0] * dimensions}])
    client = _reply_client(guard, body, cache=_UnwritableCache())
    with pytest.raises(OSError, match="no space left"):
        client.embed(["hello"])
    _returned_and_charged(guard)


def test_a_shallow_copy_of_a_guard_is_a_guard_of_its_own():
    """A copy shares neither the ledger nor the holds, so no call is counted in one and not the
    other; the original keeps what it holds."""
    guard = BudgetGuard(ceiling_usd=Decimal(1), max_calls=10)
    reserved = guard.reserve(_spec(), role=ROLE, prompt_chars=PROMPT_CHARS, max_tokens=MAX_TOKENS)
    twin = copy.copy(guard)
    assert twin.ledger is not guard.ledger
    assert (twin.held_usd, twin.held_calls) == (guard.held_usd, guard.held_calls)
    twin.release(reserved)
    assert (guard.held_usd, guard.held_calls) == (reserved, 1)
    # The positive control: the original still gives its own hold back.
    guard.release(reserved)
    assert (guard.held_usd, guard.held_calls) == (Decimal(0), 0)


def test_a_copy_of_a_guard_that_wraps_another_holds_to_the_same_one():
    """A request's observed guard and a lens's guard each wrap a guard; a copy of either holds
    against that same guard, never a second ceiling."""
    process = BudgetGuard(ceiling_usd=Decimal(1), max_calls=10)
    client = ModelClient(api_key="test-key-not-real", transport=FakeTransport(), budget=process)
    observed = client.with_attempts(lambda usage: None)._recorder
    twin = copy.copy(observed)
    reserved = twin.reserve(_spec(), role=ROLE, prompt_chars=PROMPT_CHARS, max_tokens=MAX_TOKENS)
    assert (process.held_usd, process.held_calls) == (reserved, 1)
    twin.release(reserved)
    lens = LensBudgetGuard(
        "companion",
        LensBudget(
            max_tokens=1_000_000,
            max_calls=100,
            max_wall_clock_ms=3_600_000,
            max_cost_usd=Decimal(1),
        ),
        per_call_timeout_ms=1_000,
        process=process,
    )
    copied = copy.copy(lens)
    assert copied._process is process and copied.ledger is not lens.ledger
    copied.reserve(_spec(), role=ROLE, prompt_chars=PROMPT_CHARS, max_tokens=MAX_TOKENS)
    assert process.held_calls == 1
