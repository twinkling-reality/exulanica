"""Per-lens budgets: tokens, calls, wall clock and cost, each a ceiling, all checked before a call.

A lens is the system's only egress point, so it is also the one place a model loop can run away.
:class:`~exulanica.models.budget.BudgetGuard` already catches that for a whole process with two
ceilings. This is the same shape with two more axes and a narrower scope: one guard per lens, so
one misbehaving lens exhausts its own allowance rather than everybody's.

**Four axes, because each catches a loop the others miss.**

*   ``max_tokens`` bounds prompt plus completion tokens. A lens that keeps growing its context is
    cheap per call at first and is caught here before the cost ceiling notices.
*   ``max_calls`` bounds requests issued, retries included, because each one reached the network.
*   ``max_wall_clock_ms`` bounds how long the lens may keep calling. Integer milliseconds on the
    monotonic clock, never a float and never the wall calendar.
*   ``max_cost_usd`` bounds spend. A :class:`~decimal.Decimal`, refused as a float, and written as a
    decimal string wherever it is recorded, because a float would rewrite the last digits on a
    JSON round trip and a cost nobody can reconcile against an invoice is not accounting.

**Every reservation is pessimistic, as** ``BudgetGuard.reserve`` **is.** Before a call the true
prompt size is unknown, so the guard reserves the caller's ``max_tokens`` plus an over-estimate
of the prompt, the call's worst-case price, one call, and the full per-call timeout on the clock.
A request that cannot fit under every ceiling at its worst is refused before it is sent. When the
provider reports real usage, the most recent open reservation is replaced by it. A reservation
that never gets a report, because its request failed after it may have been billed, stays charged
at its worst case.

**A refusal is never retried.** :class:`LensBudgetExceeded` is a
:class:`~exulanica.models.errors.BudgetExceededError`, which the chain does not catch and the API
answers with 429, and its message says so. Retrying is the loop the budget is stopping.

**Configuration comes from the environment and has no default.** ``EXULANICA_LENS_BUDGETS`` maps a
lens name to its four ceilings. A lens with no declared budget has no budget, and
:func:`budget_for` refuses it rather than inventing one.

**What the wall clock does not bound.** The reservation keeps a call from *starting* unless its
full timeout fits. It cannot stop a call that has started: httpx applies the timeout per
connect, read, write and pool operation and has no total-request timeout, so a response that
dribbles one chunk inside every timeout is never cut off. :meth:`LensBudgetGuard.model_client`
builds the client with the guard's own per-call timeout so the reservation at least describes the
client it guards.

**What it is.** A development and deployment safety rail, described as one. It is not a
substitute for the platform's own limit, and it keeps no durable ledger: the lens that records its
refusal is the lens lane's, and :meth:`LensBudgetExceeded.record` is the shape it records.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Final

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.env import env_get, env_name
from exulanica.models.budget import BudgetGuard
from exulanica.models.errors import BudgetExceededError, ModelError
from exulanica.models.manifest import ModelSpec, Role
from exulanica.models.usage import USD_QUANTUM, CallUsage, CostBasis, CostLedger, usd_string

__all__ = [
    "LENS_BUDGETS_ENV",
    "LensBudget",
    "LensBudgetAxis",
    "LensBudgetConfigurationError",
    "LensBudgetExceeded",
    "LensBudgetGuard",
    "budget_for",
    "load_lens_budgets",
    "usd_string",
]

#: A JSON object mapping a lens name to ``{"max_tokens": int, "max_calls": int,
#: "max_wall_clock_ms": int, "max_cost_usd": "<decimal string>"}``.
LENS_BUDGETS_ENV: Final = env_name("LENS_BUDGETS")

_LENS_NAME: Final = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,99}$")
_FIELDS: Final = ("max_tokens", "max_calls", "max_wall_clock_ms", "max_cost_usd")

#: Characters per token for sizing a reservation, rounded up. Deliberately low, which
#: over-estimates the prompt, which over-reserves. The provider's report is what is recorded.
_CHARS_PER_TOKEN: Final = 3

_NS_PER_MS: Final = 1_000_000


class LensBudgetConfigurationError(ModelError, ValueError):
    """A lens budget is absent, malformed, or was asked for by a lens that has none."""


class LensBudgetAxis(StrEnum):
    """Which ceiling refused."""

    TOKENS = "tokens"
    CALLS = "calls"
    WALL_CLOCK = "wall_clock"
    COST = "cost"


def _whole(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LensBudgetConfigurationError(f"{name} must be an integer, got {type(value).__name__}")
    if value < 0:
        raise LensBudgetConfigurationError(f"{name} must not be negative, got {value}")
    return value


def _amount(value: object, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise LensBudgetConfigurationError(
            f"{name} must be a Decimal, got {type(value).__name__}. A float cost cannot be "
            "reconciled against an invoice."
        )
    if not value.is_finite() or value < 0:
        raise LensBudgetConfigurationError(f"{name} must be a finite, non-negative amount")
    return value


@dataclass(frozen=True, slots=True)
class LensBudget:
    """The four ceilings one lens runs under. Integers and a Decimal, and nothing else."""

    max_tokens: int
    max_calls: int
    max_wall_clock_ms: int
    max_cost_usd: Decimal

    def __post_init__(self) -> None:
        _whole(self.max_tokens, "max_tokens")
        _whole(self.max_calls, "max_calls")
        _whole(self.max_wall_clock_ms, "max_wall_clock_ms")
        _amount(self.max_cost_usd, "max_cost_usd")

    def document(self) -> dict[str, Any]:
        """The canonical form a lens record references. Cost is a quantised decimal string."""
        document: dict[str, Any] = {
            "max_tokens": self.max_tokens,
            "max_calls": self.max_calls,
            "max_wall_clock_ms": self.max_wall_clock_ms,
            "max_cost_usd": usd_string(self.max_cost_usd),
        }
        canonical_json(document)
        return document

    def digest(self) -> str:
        """sha256 over :meth:`document`. What a lens record carries as its budget reference."""
        return sha256_of_canonical(self.document()).hex()


class LensBudgetExceeded(BudgetExceededError):
    """One of a lens's four ceilings would be crossed by this call, so the call was not sent.

    Never retry it. ``axis`` says which ceiling refused; ``limit``, ``committed`` and
    ``requested`` are in that axis's unit, and :meth:`record` renders them for an audit row with
    the cost axis as decimal strings. On the wall-clock axis ``committed`` is a clock reading, so
    it stays on the exception and in its message and never enters the record.
    """

    def __init__(
        self,
        *,
        lens: str,
        axis: LensBudgetAxis,
        limit: int | Decimal,
        committed: int | Decimal,
        requested: int | Decimal,
        spent_usd: Decimal,
        ceiling_usd: Decimal,
    ) -> None:
        unit = {
            LensBudgetAxis.TOKENS: "tokens",
            LensBudgetAxis.CALLS: "calls",
            LensBudgetAxis.WALL_CLOCK: "ms",
            LensBudgetAxis.COST: "USD",
        }[axis]
        super().__init__(
            f"lens {lens!r} refused on its {axis} budget: {committed} {unit} committed, this call "
            f"could need {requested} more, ceiling {limit}. No request was sent. Never retry a "
            "lens budget refusal; retrying is the loop the budget is stopping.",
            spent_usd=spent_usd,
            ceiling_usd=ceiling_usd,
        )
        self.lens = lens
        self.axis = axis
        self.limit = limit
        self.committed = committed
        self.requested = requested

    def record(self) -> dict[str, Any]:
        """The refusal as a canonical, float-free document for the caller to persist."""

        def wire(value: int | Decimal) -> int | str:
            return usd_string(value) if isinstance(value, Decimal) else value

        document: dict[str, Any] = {
            "lens": self.lens,
            "axis": str(self.axis),
            "limit": wire(self.limit),
            "requested": wire(self.requested),
        }
        if self.axis is not LensBudgetAxis.WALL_CLOCK:
            document["committed"] = wire(self.committed)
        canonical_json(document)
        return document


@dataclass(frozen=True, slots=True)
class _Reservation:
    tokens: int
    usd: Decimal


class LensBudgetGuard(BudgetGuard):
    """One lens's budget, shaped as a ``BudgetGuard`` so it plugs into ``ModelClient(budget=)``.

    The chain reserves against whatever guard the client holds before every attempt and the
    response path records against it after, so passing this guard is all it takes for every call
    the lens makes to be held to all four ceilings. ``process`` is an optional process-wide guard
    that is reserved and recorded as well, so a lens budget can narrow the process ceiling and
    never widen it.
    """

    def __init__(
        self,
        lens: str,
        budget: LensBudget,
        *,
        per_call_timeout_ms: int,
        clock: Callable[[], int] = time.monotonic_ns,
        process: BudgetGuard | None = None,
    ) -> None:
        if not _LENS_NAME.match(lens):
            raise LensBudgetConfigurationError(f"{lens!r} is not a lens name")
        if not isinstance(budget, LensBudget):
            raise LensBudgetConfigurationError("a lens guard needs a LensBudget")
        if _whole(per_call_timeout_ms, "per_call_timeout_ms") == 0:
            raise LensBudgetConfigurationError("per_call_timeout_ms must be positive")
        super().__init__(
            ceiling_usd=budget.max_cost_usd, max_calls=budget.max_calls, ledger=CostLedger()
        )
        self.lens = lens
        self.lens_budget = budget
        self.per_call_timeout_ms = per_call_timeout_ms
        self._clock = clock
        self._started_ns = clock()
        self._process = process
        self._calls = 0
        self._open: list[_Reservation] = []
        self._settled_tokens = 0
        self._settled_usd = Decimal(0)

    # -- what has been committed, reservations included --------------------------------------

    @property
    def calls_committed(self) -> int:
        return self._calls

    @property
    def tokens_committed(self) -> int:
        return self._settled_tokens + sum(r.tokens for r in self._open)

    @property
    def usd_committed(self) -> Decimal:
        return self._settled_usd + sum((r.usd for r in self._open), Decimal(0))

    @property
    def elapsed_ms(self) -> int:
        return (self._clock() - self._started_ns) // _NS_PER_MS

    def usage_document(self) -> dict[str, Any]:
        """What this lens has committed, canonical and float-free, with no clock reading in it."""
        document: dict[str, Any] = {
            "lens": self.lens,
            "budget_sha256": self.lens_budget.digest(),
            "calls": self.calls_committed,
            "tokens": self.tokens_committed,
            "usd": usd_string(self.usd_committed),
        }
        canonical_json(document)
        return document

    # -- the BudgetGuard protocol ---------------------------------------------------------------

    def _refuse(
        self,
        axis: LensBudgetAxis,
        limit: int | Decimal,
        committed: int | Decimal,
        requested: int | Decimal,
    ) -> LensBudgetExceeded:
        return LensBudgetExceeded(
            lens=self.lens,
            axis=axis,
            limit=limit,
            committed=committed,
            requested=requested,
            spent_usd=self.usd_committed,
            ceiling_usd=self.lens_budget.max_cost_usd,
        )

    def reserve(
        self,
        spec: ModelSpec,
        *,
        role: Role,
        prompt_chars: int = 0,
        max_tokens: int = 0,
        extra_prompt_tokens: int = 0,
    ) -> Decimal:
        """Admit one request against all four ceilings, or raise ``LensBudgetExceeded``.

        Every axis is checked before anything is committed, so a refusal on one axis leaves the
        other three exactly as they were.
        """
        budget = self.lens_budget
        if self._calls + 1 > budget.max_calls:
            raise self._refuse(LensBudgetAxis.CALLS, budget.max_calls, self._calls, 1)
        elapsed = self.elapsed_ms
        if elapsed + self.per_call_timeout_ms > budget.max_wall_clock_ms:
            raise self._refuse(
                LensBudgetAxis.WALL_CLOCK,
                budget.max_wall_clock_ms,
                elapsed,
                self.per_call_timeout_ms,
            )
        prompt_tokens = -(-max(prompt_chars, 0) // _CHARS_PER_TOKEN) + max(extra_prompt_tokens, 0)
        tokens = prompt_tokens + max(max_tokens, 0)
        if self.tokens_committed + tokens > budget.max_tokens:
            raise self._refuse(
                LensBudgetAxis.TOKENS, budget.max_tokens, self.tokens_committed, tokens
            )
        usd = spec.cost_usd(prompt_tokens=prompt_tokens, completion_tokens=max(max_tokens, 0))
        usd = usd.quantize(USD_QUANTUM)
        if self.usd_committed + usd > budget.max_cost_usd:
            raise self._refuse(LensBudgetAxis.COST, budget.max_cost_usd, self.usd_committed, usd)
        if self._process is not None:
            self._process.reserve(
                spec,
                role=role,
                prompt_chars=prompt_chars,
                max_tokens=max_tokens,
                extra_prompt_tokens=extra_prompt_tokens,
            )
        self._calls += 1
        self._open.append(_Reservation(tokens=tokens, usd=usd))
        return usd

    def record(self, usage: CallUsage) -> CallUsage:
        """Replace the most recent open reservation with what the provider reported.

        A cache hit issued no request and was never reserved, so it is recorded in the ledger
        and changes no ceiling. A failed attempt settles by its cost basis: one that never left
        costs nothing, and one whose cost is unknown stays charged at its reservation, tokens and
        dollars, because the provider may have done all of it.
        """
        if not usage.cache_hit and self._open:
            reservation = self._open.pop()
            if usage.cost_basis is CostBasis.UNKNOWN:
                self._settled_tokens += reservation.tokens
                self._settled_usd += max(reservation.usd, usage.usd)
            else:
                self._settled_tokens += usage.total_tokens
                self._settled_usd += usage.usd
        if self._process is not None:
            self._process.record(usage)
        return self.ledger.record(usage)

    @property
    def billed_calls(self) -> int:
        return self._calls

    def model_client(self, **kwargs: Any) -> Any:
        """A ``ModelClient`` that charges this guard, with one attempt and this guard's timeout.

        One attempt, because a lens's retries are its own decision to make and to pay for, and
        the guard's per-call timeout, so the wall-clock reservation describes the client.
        """
        from exulanica.models.client import ModelClient

        for name in ("budget", "timeout"):
            if name in kwargs:
                raise TypeError(f"{name} is set by the lens budget guard")
        kwargs.setdefault("max_attempts", 1)
        return ModelClient(budget=self, timeout=self.per_call_timeout_ms / 1000, **kwargs)


def _parse_budget(lens: str, raw: object) -> LensBudget:
    where = f"{LENS_BUDGETS_ENV}: lens {lens!r}"
    if not isinstance(raw, dict):
        raise LensBudgetConfigurationError(f"{where} is not an object")
    if set(raw) != set(_FIELDS):
        raise LensBudgetConfigurationError(
            f"{where} must declare exactly {', '.join(_FIELDS)}; got {', '.join(sorted(raw))}"
        )
    cost = raw["max_cost_usd"]
    if not isinstance(cost, str):
        raise LensBudgetConfigurationError(
            f'{where}: max_cost_usd must be a decimal string such as "0.50", never a JSON '
            "number, which a parser may read as a float"
        )
    try:
        amount = Decimal(cost.strip())
    except InvalidOperation as exc:
        raise LensBudgetConfigurationError(f"{where}: {cost!r} is not a decimal amount") from exc
    return LensBudget(
        max_tokens=_whole(raw["max_tokens"], f"{where} max_tokens"),
        max_calls=_whole(raw["max_calls"], f"{where} max_calls"),
        max_wall_clock_ms=_whole(raw["max_wall_clock_ms"], f"{where} max_wall_clock_ms"),
        max_cost_usd=_amount(amount, f"{where} max_cost_usd"),
    )


def load_lens_budgets(environ: Mapping[str, str] | None = None) -> Mapping[str, LensBudget]:
    """Every declared lens budget, or raise. There is no default budget."""
    environ = os.environ if environ is None else environ
    raw = env_get("LENS_BUDGETS", environ)
    if not raw:
        raise LensBudgetConfigurationError(
            f"{LENS_BUDGETS_ENV} is not set. It maps each lens name to its max_tokens, max_calls, "
            "max_wall_clock_ms and max_cost_usd. There is no default: a budget nobody declared "
            "is a number nobody chose."
        )
    try:
        # parse_float refuses a float anywhere in the document rather than reading one.
        parsed = json.loads(raw, parse_float=_no_float)
    except json.JSONDecodeError as exc:
        raise LensBudgetConfigurationError(f"{LENS_BUDGETS_ENV} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise LensBudgetConfigurationError(f"{LENS_BUDGETS_ENV} must be a non-empty JSON object")
    budgets: dict[str, LensBudget] = {}
    for lens, declared in parsed.items():
        if not _LENS_NAME.match(lens):
            raise LensBudgetConfigurationError(f"{LENS_BUDGETS_ENV}: {lens!r} is not a lens name")
        budgets[lens] = _parse_budget(lens, declared)
    return budgets


def _no_float(text: str) -> Decimal:
    raise LensBudgetConfigurationError(
        f"{LENS_BUDGETS_ENV} contains the number {text}, which JSON would read as a float. "
        "Ceilings are integers and the cost is a decimal string."
    )


def budget_for(lens: str, environ: Mapping[str, str] | None = None) -> LensBudget:
    """The declared budget for ``lens``, or raise. A lens with no budget does not run."""
    budgets = load_lens_budgets(environ)
    if lens not in budgets:
        raise LensBudgetConfigurationError(
            f"lens {lens!r} has no budget in {LENS_BUDGETS_ENV}, so it may not call a model"
        )
    return budgets[lens]
