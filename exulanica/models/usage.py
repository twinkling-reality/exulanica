"""Cost accounting from real reported usage, never from an estimate.

The project has committed to reporting actual spend rather than a projection, so every number
here comes out of the provider's own ``usage`` object. Three details decide whether the total is
right:

*   ``reasoning_tokens`` lives in ``usage.completion_tokens_details`` and is **already inside**
    ``completion_tokens`` (measured: 154 completion of which 149 reasoning). It is recorded
    separately because it is a floor on every call rather than a variable, which matters for
    latency budgets, but it is never added to the bill a second time.
*   ``prompt_cache_hit_tokens`` is reported and no discount for it is published. Cached prompt
    tokens are therefore billed at full input price. An estimate that is too low is worse than
    one that is too high, because it is the one that produces a surprise.
*   A cache hit costs nothing and is recorded with ``usd`` zero. The tokens it *would* have cost
    are kept in ``usd_avoided``, which is how the project can say what idempotency actually saved
    rather than asserting that it saves.

**A call that failed is recorded too, with a cost stated as known or unknown and never as a
default zero.** Measured at the transport before this rule existed: a request that timed out,
three retries of one, and a 500 each left the ledger empty, so ``spent_usd`` and the call ceiling
never saw them, while the provider may still have billed the work. Each attempt is now a row with
a :class:`CostBasis`:

*   ``reported``: the provider's usage object, priced by the manifest.
*   ``cached``: no request was issued; zero, and the price avoided is kept.
*   ``not_sent``: the connection was never made, so no request reached the provider; zero, known.
*   ``unknown``: the request was sent and no usable usage came back (a timeout, a dropped
    connection, an error status, or a reply without a usage object). The provider may bill it and
    this process cannot see whether it did, so the row is charged the attempt's reservation, the
    most it could have cost, and says so. The budget guard counts it at that amount.

``as_cost_json`` emits the shape ``pipeline_event.cost`` expects in migration 0001, with
``usd_estimate`` as a decimal **string**. A float would rewrite the last digits on the JSON round
trip, and a cost nobody can reconcile against an invoice is not accounting.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final

from exulanica.models.manifest import ModelSpec, Role

__all__ = ["USD_QUANTUM", "CallOutcome", "CallUsage", "CostBasis", "CostLedger", "usd_string"]

#: Eight decimal places. A single cheap call costs about $0.00005, so cents would round the
#: entire corpus pass to zero.
USD_QUANTUM: Final = Decimal("0.00000001")


def usd_string(value: Decimal) -> str:
    """A cost as a plain decimal string at the ledger's quantum: ``0.00000001``, never ``1E-8``.

    ``str(Decimal)`` switches to exponent notation for small values and for a quantised zero, so
    two equal budgets could otherwise digest differently and a record would carry a number an
    invoice never shows. One embedding query costs about two hundred-millionths of a dollar, which
    ``str`` writes as ``2E-8``.
    """
    quantised = value.quantize(USD_QUANTUM)
    # A negative zero is zero, and it must not digest as a different amount.
    return f"{quantised.copy_abs() if quantised.is_zero() else quantised:f}"


class CostBasis(StrEnum):
    """Where a row's ``usd`` comes from, and so whether it is known."""

    REPORTED = "reported"
    CACHED = "cached"
    NOT_SENT = "not_sent"
    UNKNOWN = "unknown"


class CallOutcome(StrEnum):
    """How one attempt ended."""

    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


def _is_count(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_int(value: Any) -> int:
    return int(value) if _is_count(value) else 0


@dataclass(frozen=True, slots=True)
class CallUsage:
    """What one call attempt consumed, or the most it can have, and which of the two ``usd`` is."""

    role: Role
    model_id: str
    #: The key of the provider the attempt was sent to, as the manifest names it.
    provider: str
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    cached_prompt_tokens: int
    #: What the ledger charges for this attempt: the priced report, zero when nothing was sent, or
    #: the reservation when the cost is unknown. ``cost_basis`` says which.
    usd: Decimal
    usd_avoided: Decimal = Decimal(0)
    cache_hit: bool = False
    used_fallback: bool = False
    latency_s: float = 0.0
    cost_basis: CostBasis = CostBasis.REPORTED
    outcome: CallOutcome = CallOutcome.COMPLETED
    #: Why the attempt failed, in the transport's words. Empty for a completed attempt.
    failure: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def usd_known(self) -> bool:
        return self.cost_basis is not CostBasis.UNKNOWN

    @classmethod
    def failed(
        cls,
        *,
        role: Role,
        spec: ModelSpec,
        reached_provider: bool | None,
        timed_out: bool,
        failure: str,
        usd_bound: Decimal,
        used_fallback: bool = False,
        latency_s: float = 0.0,
    ) -> CallUsage:
        """An attempt that returned no usable body.

        ``usd_bound`` is the attempt's reservation. It is charged unless the request never left,
        because only then is it known that the provider did no work: a timeout ends this side's
        wait and not the provider's generation, and an error body carries no usage to price.
        """
        not_sent = reached_provider is False
        return cls(
            role=role,
            model_id=spec.model_id,
            provider=spec.provider,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
            cached_prompt_tokens=0,
            usd=Decimal(0) if not_sent else usd_bound.quantize(USD_QUANTUM),
            used_fallback=used_fallback,
            latency_s=latency_s,
            cost_basis=CostBasis.NOT_SENT if not_sent else CostBasis.UNKNOWN,
            outcome=CallOutcome.TIMED_OUT if timed_out else CallOutcome.FAILED,
            failure=failure,
        )

    @classmethod
    def from_response(
        cls,
        *,
        role: Role,
        spec: ModelSpec,
        usage: Mapping[str, Any] | None,
        cache_hit: bool = False,
        used_fallback: bool = False,
        latency_s: float = 0.0,
        usd_bound: Decimal | None = None,
    ) -> CallUsage:
        """Build from a provider ``usage`` object.

        A count the manifest prices and the report omits makes the cost unknown rather than
        smaller: the row is charged ``usd_bound``, the attempt's reservation, and says so. An
        embedding reports no completion tokens and prices none, so it is known from its prompt
        count alone. The token fields still read zero for an omitted count, for accounting;
        :class:`exulanica.selection.calls.ModelCall` reads the raw body when absence matters.
        A cache hit issued no request, so it is charged nothing whatever its stored report says.
        A ``usage`` or its details that is not an object is absent, never a reason to raise
        before the call is recorded.
        """
        usage = usage if isinstance(usage, Mapping) else {}
        details = usage.get("completion_tokens_details")
        details = details if isinstance(details, Mapping) else {}
        prompt_tokens = _as_int(usage.get("prompt_tokens"))
        completion_tokens = _as_int(usage.get("completion_tokens"))
        cost = spec.cost_usd(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        cost = cost.quantize(USD_QUANTUM)
        priced = (
            ("prompt_tokens", spec.input_usd_per_mtok),
            ("completion_tokens", spec.output_usd_per_mtok),
        )
        reported = all(price == 0 or _is_count(usage.get(key)) for key, price in priced)
        if cache_hit:
            basis = CostBasis.CACHED
        elif reported or usd_bound is None:
            # No bound means no request was reserved for, which only a caller replaying a stored
            # body does; it is priced as reported, as it always was.
            basis = CostBasis.REPORTED
        else:
            basis = CostBasis.UNKNOWN
        if basis is CostBasis.UNKNOWN and usd_bound is not None:
            cost = max(cost, usd_bound.quantize(USD_QUANTUM))
        return cls(
            role=role,
            model_id=spec.model_id,
            provider=spec.provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=_as_int(details.get("reasoning_tokens")),
            cached_prompt_tokens=_as_int(usage.get("prompt_cache_hit_tokens")),
            usd=Decimal(0) if cache_hit else cost,
            usd_avoided=cost if cache_hit else Decimal(0),
            cache_hit=cache_hit,
            used_fallback=used_fallback,
            latency_s=latency_s,
            cost_basis=basis,
        )

    def as_cost_json(self) -> dict[str, Any]:
        """The ``pipeline_event.cost`` payload for this one call.

        ``gpu_seconds`` is absent rather than zero. Serverless inference reports none, and a zero
        would read as a measurement that was taken.
        """
        return {
            "input_tokens": self.prompt_tokens,
            "output_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_input_tokens": self.cached_prompt_tokens,
            "usd_estimate": usd_string(self.usd),
            "cost_basis": str(self.cost_basis),
            "outcome": str(self.outcome),
            "cache_hit": self.cache_hit,
            "model_id": self.model_id,
            "role": str(self.role),
        }


@dataclass
class CostLedger:
    """Every call this process made, and what it cost.

    Deliberately in-process and in-memory. Durable accounting belongs in ``pipeline_event.cost``
    where it is attributable to a stage; this exists so a script, a test, or the demo can print
    what a corpus pass really cost the moment it finishes.
    """

    calls: list[CallUsage] = field(default_factory=list)

    def record(self, usage: CallUsage) -> CallUsage:
        self.calls.append(usage)
        return usage

    def __len__(self) -> int:
        return len(self.calls)

    @property
    def total_usd(self) -> Decimal:
        """Everything charged: reported costs plus the bound of every attempt whose cost is unknown.

        One number, because the budget guard spends from it and the report prints it, and a guard
        that counted less than the report would let unknown spend through. ``usd_unknown`` is the
        part of it that is a bound rather than a report.
        """
        return sum((c.usd for c in self.calls), Decimal(0))

    @property
    def usd_unknown(self) -> Decimal:
        return sum((c.usd for c in self.calls if not c.usd_known), Decimal(0))

    @property
    def unknown_cost_calls(self) -> int:
        return sum(1 for c in self.calls if not c.usd_known)

    @property
    def failed_calls(self) -> int:
        return sum(1 for c in self.calls if c.outcome is not CallOutcome.COMPLETED)

    @property
    def usd_avoided_by_cache(self) -> Decimal:
        return sum((c.usd_avoided for c in self.calls), Decimal(0))

    @property
    def billed_calls(self) -> int:
        """Requests attempted, failed ones included: a loop of timeouts is still a loop."""
        return sum(1 for c in self.calls if not c.cache_hit)

    @property
    def cache_hits(self) -> int:
        return sum(1 for c in self.calls if c.cache_hit)

    @property
    def fallback_calls(self) -> int:
        return sum(1 for c in self.calls if c.used_fallback)

    @property
    def total_prompt_tokens(self) -> int:
        return sum(c.prompt_tokens for c in self.calls if not c.cache_hit)

    @property
    def total_completion_tokens(self) -> int:
        return sum(c.completion_tokens for c in self.calls if not c.cache_hit)

    @property
    def total_reasoning_tokens(self) -> int:
        return sum(c.reasoning_tokens for c in self.calls if not c.cache_hit)

    def by_role(self) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for call in self.calls:
            totals[str(call.role)] = totals.get(str(call.role), Decimal(0)) + call.usd
        return totals

    def by_model(self) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for call in self.calls:
            totals[call.model_id] = totals.get(call.model_id, Decimal(0)) + call.usd
        return totals

    def as_cost_json(self) -> dict[str, Any]:
        """Aggregate in the ``pipeline_event.cost`` shape, for a whole run."""
        return {
            "input_tokens": self.total_prompt_tokens,
            "output_tokens": self.total_completion_tokens,
            "reasoning_tokens": self.total_reasoning_tokens,
            "usd_estimate": usd_string(self.total_usd),
            "usd_unknown_bound": usd_string(self.usd_unknown),
            "calls": len(self.calls),
            "billed_calls": self.billed_calls,
            "failed_calls": self.failed_calls,
            "unknown_cost_calls": self.unknown_cost_calls,
            "cache_hits": self.cache_hits,
            "usd_avoided_by_cache": usd_string(self.usd_avoided_by_cache),
        }

    def summary(self) -> str:
        """One human-readable block. Used by scripts and by the end of a corpus pass."""
        lines: Sequence[str] = [
            f"calls: {len(self.calls)} ({self.billed_calls} billed, "
            f"{self.cache_hits} cached, {self.fallback_calls} on a fallback model, "
            f"{self.failed_calls} failed)",
            f"tokens: {self.total_prompt_tokens} in, {self.total_completion_tokens} out "
            f"(of which {self.total_reasoning_tokens} reasoning)",
            f"spend: ${self.total_usd.quantize(USD_QUANTUM)} "
            f"(${self.usd_avoided_by_cache.quantize(USD_QUANTUM)} avoided by cache; "
            f"${self.usd_unknown.quantize(USD_QUANTUM)} of it is the most "
            f"{self.unknown_cost_calls} calls of unknown cost can have cost)",
            *(
                f"  {role}: ${amount.quantize(USD_QUANTUM)}"
                for role, amount in sorted(self.by_role().items())
            ),
        ]
        return "\n".join(lines)
