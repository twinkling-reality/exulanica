"""Per-lens budgets on four axes, each refusing on its own, before the call, never retried.

Every refusal test goes through a real :class:`~exulanica.models.client.ModelClient` built by the
guard, over a scripted transport, and asserts the transport was not called for the refused
request. A refusal counted after the request left is a report, not a limit.

Each axis has its own test, and each of those asserts the other three were inside their ceilings
at the moment of refusal, so a test cannot pass because a different axis happened to fire.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from exulanica.canonical import canonical_json
from exulanica.errors import CanonicalisationError
from exulanica.models.budget import BudgetGuard
from exulanica.models.errors import BudgetExceededError, TransportError
from exulanica.models.lens_budget import (
    LENS_BUDGETS_ENV,
    LensBudget,
    LensBudgetAxis,
    LensBudgetConfigurationError,
    LensBudgetExceeded,
    LensBudgetGuard,
    budget_for,
    load_lens_budgets,
    usd_string,
)
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.usage import USD_QUANTUM

from model_fakes import FakeTransport, RecordingPolicy

LENS = "facade-proposer"
ROLE = Role.REASONING_CHEAP
MESSAGES = [{"role": "user", "content": "propose a bay rhythm"}]
MAX_TOKENS = 640
TIMEOUT_MS = 1_000

#: What ``ModelClient.chat`` sizes the prompt reservation from, and what the guard makes of it.
PROMPT_CHARS = sum(len(str(message)) for message in MESSAGES)
PROMPT_TOKENS = -(-PROMPT_CHARS // 3)
RESERVED_TOKENS = PROMPT_TOKENS + MAX_TOKENS

GENEROUS = LensBudget(
    max_tokens=1_000_000,
    max_calls=1_000,
    max_wall_clock_ms=3_600_000,
    max_cost_usd=Decimal("100.00"),
)


class Clock:
    """A monotonic nanosecond clock a test moves by hand."""

    def __init__(self) -> None:
        self.now_ns = 10**12

    def __call__(self) -> int:
        return self.now_ns

    def advance_ms(self, ms: int) -> None:
        self.now_ns += ms * 1_000_000


def _spec():
    return load_manifest()[ROLE].primary


def _reserved_usd() -> Decimal:
    return (
        _spec()
        .cost_usd(prompt_tokens=PROMPT_TOKENS, completion_tokens=MAX_TOKENS)
        .quantize(USD_QUANTUM)
    )


def _guarded(budget: LensBudget, clock: Clock | None = None, **kwargs):
    guard = LensBudgetGuard(
        LENS, budget, per_call_timeout_ms=TIMEOUT_MS, clock=clock or Clock(), **kwargs
    )
    transport = FakeTransport()
    client = guard.model_client(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=transport,
        policy=RecordingPolicy(),
    )
    return guard, transport, client


def _ask(client):
    return client.chat(
        ROLE, MESSAGES, prompt_version="lens-v1", max_tokens=MAX_TOKENS, use_cache=False
    )


def _inside(guard: LensBudgetGuard, *, except_axis: LensBudgetAxis) -> None:
    """The three axes that did not refuse had room for this call when it was refused."""
    budget = guard.lens_budget
    checks = {
        LensBudgetAxis.CALLS: guard.calls_committed + 1 <= budget.max_calls,
        LensBudgetAxis.WALL_CLOCK: guard.elapsed_ms + TIMEOUT_MS <= budget.max_wall_clock_ms,
        LensBudgetAxis.TOKENS: guard.tokens_committed + RESERVED_TOKENS <= budget.max_tokens,
        LensBudgetAxis.COST: guard.usd_committed + _reserved_usd() <= budget.max_cost_usd,
    }
    for axis, fits in checks.items():
        if axis is not except_axis:
            assert fits, (
                f"{axis} was also over budget, so this test proves nothing about {except_axis}"
            )


# -- four axes, four refusals -------------------------------------------------------------


def test_the_token_ceiling_refuses_on_its_own():
    budget = LensBudget(
        max_tokens=RESERVED_TOKENS - 1,
        max_calls=GENEROUS.max_calls,
        max_wall_clock_ms=GENEROUS.max_wall_clock_ms,
        max_cost_usd=GENEROUS.max_cost_usd,
    )
    guard, transport, client = _guarded(budget)
    with pytest.raises(LensBudgetExceeded) as refused:
        _ask(client)
    assert refused.value.axis is LensBudgetAxis.TOKENS
    assert transport.call_count == 0
    _inside(guard, except_axis=LensBudgetAxis.TOKENS)
    assert refused.value.record() == {
        "lens": LENS,
        "axis": "tokens",
        "limit": RESERVED_TOKENS - 1,
        "committed": 0,
        "requested": RESERVED_TOKENS,
    }


def test_the_call_ceiling_refuses_on_its_own():
    budget = LensBudget(
        max_tokens=GENEROUS.max_tokens,
        max_calls=1,
        max_wall_clock_ms=GENEROUS.max_wall_clock_ms,
        max_cost_usd=GENEROUS.max_cost_usd,
    )
    guard, transport, client = _guarded(budget)
    _ask(client)
    assert transport.call_count == 1
    with pytest.raises(LensBudgetExceeded) as refused:
        _ask(client)
    assert refused.value.axis is LensBudgetAxis.CALLS
    assert transport.call_count == 1
    _inside(guard, except_axis=LensBudgetAxis.CALLS)
    assert refused.value.record()["limit"] == 1


def test_the_wall_clock_ceiling_refuses_on_its_own():
    clock = Clock()
    budget = LensBudget(
        max_tokens=GENEROUS.max_tokens,
        max_calls=GENEROUS.max_calls,
        max_wall_clock_ms=5_000,
        max_cost_usd=GENEROUS.max_cost_usd,
    )
    guard, transport, client = _guarded(budget, clock)
    clock.advance_ms(3_999)
    _ask(client)  # 3999 + 1000 fits under 5000
    clock.advance_ms(2)  # 4001 + 1000 does not, although 4001 alone is under the ceiling
    with pytest.raises(LensBudgetExceeded) as refused:
        _ask(client)
    assert refused.value.axis is LensBudgetAxis.WALL_CLOCK
    assert transport.call_count == 1
    _inside(guard, except_axis=LensBudgetAxis.WALL_CLOCK)
    record = refused.value.record()
    # A clock reading never enters the record; the configured numbers do.
    assert record == {"lens": LENS, "axis": "wall_clock", "limit": 5_000, "requested": TIMEOUT_MS}
    assert refused.value.committed == 4_001


def test_the_cost_ceiling_refuses_on_its_own_and_stays_decimal():
    budget = LensBudget(
        max_tokens=GENEROUS.max_tokens,
        max_calls=GENEROUS.max_calls,
        max_wall_clock_ms=GENEROUS.max_wall_clock_ms,
        max_cost_usd=_reserved_usd() - USD_QUANTUM,
    )
    guard, transport, client = _guarded(budget)
    with pytest.raises(LensBudgetExceeded) as refused:
        _ask(client)
    assert refused.value.axis is LensBudgetAxis.COST
    assert transport.call_count == 0
    _inside(guard, except_axis=LensBudgetAxis.COST)
    record = refused.value.record()
    assert record["limit"] == f"{_reserved_usd() - USD_QUANTUM:f}"
    assert record["requested"] == f"{_reserved_usd():f}"
    assert record["committed"] == "0.00000000"
    assert all(isinstance(record[key], str) for key in ("limit", "committed", "requested"))
    assert isinstance(refused.value.limit, Decimal)
    canonical_json(record)


# -- how the refusal behaves ----------------------------------------------------------------


def test_a_refusal_is_a_budget_error_the_chain_never_retries():
    """With three attempts allowed and a transient failure first, the second attempt's
    reservation is refused and nothing is sent again."""
    budget = LensBudget(
        max_tokens=GENEROUS.max_tokens,
        max_calls=1,
        max_wall_clock_ms=GENEROUS.max_wall_clock_ms,
        max_cost_usd=GENEROUS.max_cost_usd,
    )
    guard = LensBudgetGuard(LENS, budget, per_call_timeout_ms=TIMEOUT_MS, clock=Clock())
    transport = FakeTransport([TransportError("connection reset", retryable=True)])
    client = guard.model_client(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=transport,
        max_attempts=3,
        sleep=lambda _seconds: None,
        policy=RecordingPolicy(),
    )
    with pytest.raises(LensBudgetExceeded, match="Never retry") as refused:
        _ask(client)
    assert isinstance(refused.value, BudgetExceededError)
    assert refused.value.axis is LensBudgetAxis.CALLS
    assert transport.call_count == 1


def test_a_failed_request_stays_charged_at_its_worst_case():
    guard = LensBudgetGuard(LENS, GENEROUS, per_call_timeout_ms=TIMEOUT_MS, clock=Clock())
    transport = FakeTransport([TransportError("reset after send", retryable=False)])
    client = guard.model_client(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=transport,
        policy=RecordingPolicy(),
    )
    with pytest.raises(TransportError):
        _ask(client)
    assert guard.calls_committed == 1
    assert guard.tokens_committed == RESERVED_TOKENS
    assert guard.usd_committed == _reserved_usd()


def test_a_reported_call_replaces_its_reservation_with_what_it_cost():
    guard, _transport, client = _guarded(GENEROUS)
    result = _ask(client)
    assert guard.tokens_committed == 300  # model_fakes.chat_body reports 100 in, 200 out
    assert guard.usd_committed == result.usage.usd
    assert guard.ledger.billed_calls == 1
    document = guard.usage_document()
    assert document == {
        "lens": LENS,
        "budget_sha256": GENEROUS.digest(),
        "calls": 1,
        "tokens": 300,
        "usd": f"{result.usage.usd.quantize(USD_QUANTUM):f}",
    }


def test_the_reservation_is_pessimistic_so_the_last_call_cannot_cross():
    """A ceiling that the call's real usage would fit under, but its worst case would not,
    refuses. Reserving the real usage instead would let exactly this call cross the ceiling."""
    tight = LensBudget(
        max_tokens=RESERVED_TOKENS - 1,
        max_calls=GENEROUS.max_calls,
        max_wall_clock_ms=GENEROUS.max_wall_clock_ms,
        max_cost_usd=GENEROUS.max_cost_usd,
    )
    assert tight.max_tokens > 300  # what the call would really have used fits
    _guard, transport, client = _guarded(tight)
    with pytest.raises(LensBudgetExceeded):
        _ask(client)
    assert transport.call_count == 0
    exact = LensBudget(
        max_tokens=RESERVED_TOKENS,
        max_calls=1,
        max_wall_clock_ms=TIMEOUT_MS,
        max_cost_usd=_reserved_usd(),
    )
    _guard, transport, client = _guarded(exact)
    _ask(client)
    assert transport.call_count == 1


def test_one_lens_exhausting_its_budget_leaves_another_untouched():
    spent = LensBudget(
        max_tokens=10**6, max_calls=1, max_wall_clock_ms=10**6, max_cost_usd=Decimal(1)
    )
    first, _t, first_client = _guarded(spent)
    _ask(first_client)
    with pytest.raises(LensBudgetExceeded):
        _ask(first_client)
    second = LensBudgetGuard("other-lens", spent, per_call_timeout_ms=TIMEOUT_MS, clock=Clock())
    assert second.reserve(_spec(), role=ROLE, max_tokens=MAX_TOKENS) > 0
    assert (first.calls_committed, second.calls_committed) == (1, 1)


def test_a_process_ceiling_still_applies_underneath_a_lens():
    process = BudgetGuard(ceiling_usd=Decimal("100"), max_calls=0)
    guard, transport, client = _guarded(GENEROUS, process=process)
    with pytest.raises(BudgetExceededError, match="call ceiling reached"):
        _ask(client)
    assert transport.call_count == 0
    assert guard.calls_committed == 0


def test_a_cache_hit_changes_no_ceiling():
    from exulanica.models.cache import InMemoryResponseCache

    guard = LensBudgetGuard(LENS, GENEROUS, per_call_timeout_ms=TIMEOUT_MS, clock=Clock())
    transport = FakeTransport()
    client = guard.model_client(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=transport,
        cache=InMemoryResponseCache(),
        policy=RecordingPolicy(),
    )
    client.chat(ROLE, MESSAGES, prompt_version="lens-v1", max_tokens=MAX_TOKENS)
    before = (guard.calls_committed, guard.tokens_committed, guard.usd_committed)
    hit = client.chat(ROLE, MESSAGES, prompt_version="lens-v1", max_tokens=MAX_TOKENS)
    assert hit.cache_hit
    assert (guard.calls_committed, guard.tokens_committed, guard.usd_committed) == before
    assert transport.call_count == 1


def test_the_guard_sets_its_own_budget_and_timeout_on_the_client():
    guard = LensBudgetGuard(LENS, GENEROUS, per_call_timeout_ms=TIMEOUT_MS)
    for name in ("budget", "timeout"):
        with pytest.raises(TypeError, match=name):
            guard.model_client(**{name: None})
    client = guard.model_client(api_key="k", manifest=load_manifest(), transport=FakeTransport())
    assert client.budget is guard


# -- the declaration --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"max_cost_usd": 0.5},
        {"max_cost_usd": Decimal("NaN")},
        {"max_cost_usd": Decimal("Infinity")},
        {"max_cost_usd": Decimal("-0.01")},
        {"max_cost_usd": "0.50"},
        {"max_tokens": 1.0},
        {"max_tokens": True},
        {"max_calls": -1},
        {"max_wall_clock_ms": 1.5},
    ],
)
def test_a_budget_is_integers_and_a_decimal_and_nothing_else(fields):
    values = {
        "max_tokens": 1,
        "max_calls": 1,
        "max_wall_clock_ms": 1,
        "max_cost_usd": Decimal("0.50"),
        **fields,
    }
    with pytest.raises(LensBudgetConfigurationError):
        LensBudget(**values)


def test_the_budget_digest_is_canonical_float_free_and_clockless():
    a = LensBudget(max_tokens=10, max_calls=2, max_wall_clock_ms=500, max_cost_usd=Decimal("0.5"))
    b = LensBudget(
        max_tokens=10, max_calls=2, max_wall_clock_ms=500, max_cost_usd=Decimal("0.50000000")
    )
    assert a.document() == {
        "max_tokens": 10,
        "max_calls": 2,
        "max_wall_clock_ms": 500,
        "max_cost_usd": "0.50000000",
    }
    assert a.digest() == b.digest()
    assert len(a.digest()) == 64
    assert a.digest() != LensBudget(10, 2, 500, Decimal("0.51")).digest()
    with pytest.raises(CanonicalisationError):
        canonical_json({**a.document(), "max_cost_usd": 0.5})


def test_no_clock_reaches_the_usage_document():
    clock = Clock()
    guard = LensBudgetGuard(LENS, GENEROUS, per_call_timeout_ms=TIMEOUT_MS, clock=clock)
    before = canonical_json(guard.usage_document())
    clock.advance_ms(60_000)
    assert canonical_json(guard.usage_document()) == before


@pytest.mark.parametrize(
    "environ",
    [{}, {LENS_BUDGETS_ENV: ""}],
)
def test_there_is_no_default_budget(environ):
    with pytest.raises(LensBudgetConfigurationError, match="no default"):
        load_lens_budgets(environ)


def _declared(**overrides) -> dict[str, str]:
    declared = {
        "max_tokens": 4000,
        "max_calls": 3,
        "max_wall_clock_ms": 30000,
        "max_cost_usd": "0.25",
        **overrides,
    }
    return {LENS_BUDGETS_ENV: json.dumps({LENS: declared})}


def test_a_declared_budget_loads_exactly():
    assert budget_for(LENS, _declared()) == LensBudget(4000, 3, 30000, Decimal("0.25"))


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        (_declared(max_cost_usd=0.25), "decimal string"),
        (_declared(max_cost_usd=1), "decimal string"),
        (_declared(max_cost_usd="a quarter"), "not a decimal amount"),
        (_declared(max_cost_usd="-1"), "non-negative"),
        (_declared(max_tokens=4000.0), "float"),
        (_declared(max_calls=True), "integer"),
        (_declared(extra=1), "exactly"),
        ({LENS_BUDGETS_ENV: json.dumps({LENS: {"max_tokens": 1}})}, "exactly"),
        (
            {
                LENS_BUDGETS_ENV: json.dumps(
                    {"Not A Lens": json.loads(_declared()[LENS_BUDGETS_ENV])[LENS]}
                )
            },
            "not a lens name",
        ),
        ({LENS_BUDGETS_ENV: "[]"}, "non-empty JSON object"),
        ({LENS_BUDGETS_ENV: "{"}, "not valid JSON"),
        ({LENS_BUDGETS_ENV: json.dumps({LENS: []})}, "not an object"),
    ],
)
def test_a_malformed_budget_is_refused_at_load(environ, message):
    with pytest.raises(LensBudgetConfigurationError, match=message):
        load_lens_budgets(environ)


def test_a_lens_without_a_declared_budget_may_not_call():
    with pytest.raises(LensBudgetConfigurationError, match="no budget"):
        budget_for("undeclared-lens", _declared())


def test_a_guard_needs_a_real_budget_and_a_real_timeout():
    with pytest.raises(LensBudgetConfigurationError):
        LensBudgetGuard("Bad Name", GENEROUS, per_call_timeout_ms=TIMEOUT_MS)
    with pytest.raises(LensBudgetConfigurationError):
        LensBudgetGuard(LENS, GENEROUS, per_call_timeout_ms=0)
    with pytest.raises(LensBudgetConfigurationError):
        LensBudgetGuard(LENS, GENEROUS, per_call_timeout_ms=1.5)  # type: ignore[arg-type]
    with pytest.raises(LensBudgetConfigurationError):
        LensBudgetGuard(LENS, {"max_tokens": 1}, per_call_timeout_ms=TIMEOUT_MS)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("amount", "wire"),
    [
        (Decimal(0), "0.00000000"),
        (Decimal("0.00000001"), "0.00000001"),
        (Decimal("1E-8"), "0.00000001"),
        (Decimal("5"), "5.00000000"),
        (Decimal("12345.6"), "12345.60000000"),
    ],
)
def test_a_cost_is_always_written_in_plain_decimal_notation(amount, wire):
    """``str(Decimal)`` would write ``0E-8`` and ``1E-8`` for the first three."""
    assert usd_string(amount) == wire
    budget = LensBudget(max_tokens=1, max_calls=1, max_wall_clock_ms=1, max_cost_usd=amount)
    assert budget.document()["max_cost_usd"] == wire
    assert "E" not in json.dumps(budget.document())


def test_equal_budgets_digest_equally_however_the_amount_was_spelt():
    spellings = (Decimal(0), Decimal("0.0"), Decimal("0E-8"), Decimal("-0"))
    digests = {
        LensBudget(max_tokens=1, max_calls=1, max_wall_clock_ms=1, max_cost_usd=amount).digest()
        for amount in spellings
    }
    assert len(digests) == 1
