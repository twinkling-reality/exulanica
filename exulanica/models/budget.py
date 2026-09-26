"""The budget guard: a ceiling on what one process may spend before it refuses to call.

What this is honestly for. Token Factory is prepaid and the balance is $25, so spend physically
cannot exceed the balance and this guard cannot prevent a real overrun. What it catches is a
runaway loop: a retry that does not back off, a recursive agent step, a test that accidentally
points at the live endpoint. Those burn a prepaid balance in minutes, and the balance is the
whole demo. So the guard is a development safety rail, described as one, and it is not a
substitute for the platform's own limit.

Two ceilings, because the two failure modes look different:

*   ``ceiling_usd`` catches an expensive loop, for example a vision pass that never terminates.
*   ``max_calls`` catches a cheap loop. Ten thousand calls at $0.00005 is only fifty cents, so a
    dollar ceiling would never fire, but ten thousand calls is unambiguously a bug.

The reservation is deliberately pessimistic. Before a call, the true prompt-token count is
unknown, so the guard reserves the caller's ``max_tokens`` at the output price plus an estimate
of the prompt at the input price. Reserving less than the call can cost would let the very last
call cross the ceiling, which is the one thing the guard exists to prevent.

A reservation is held until the call's usage is recorded, or released when no request left, under
one lock: two calls admitted at once each see the other's reservation, so together they never
take the process past a ceiling one of them alone could not cross. A caller may also name a part
of the budget its call must leave untouched (``keep_usd``, ``keep_calls``), so work that is
bounded by a share of the process's budget stops at its share and the rest stays for everything
else; that refusal is :class:`BudgetShareExceeded`.
"""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from exulanica.env import env_get, env_name
from exulanica.models.errors import BudgetExceededError, BudgetShareExceeded
from exulanica.models.manifest import ModelSpec, Role
from exulanica.models.usage import USD_QUANTUM, CallUsage, CostLedger

__all__ = ["DEFAULT_CEILING_USD", "DEFAULT_MAX_CALLS", "BudgetGuard", "BudgetShareExceeded"]

#: A full corpus pass was measured at roughly $0.41, and twenty development iterations at about
#: $10. Five dollars is generous for one process and small against a $25 prepaid balance, so a
#: runaway is caught while normal work never notices.
DEFAULT_CEILING_USD: Final = Decimal("5.00")

#: A corpus is around 150 photographs plus a few hundred reasoning turns. Two thousand calls in
#: one process is not a workload, it is a loop.
DEFAULT_MAX_CALLS: Final = 2000

_CEILING_ENV: Final = env_name("BUDGET_USD")
_MAX_CALLS_ENV: Final = env_name("BUDGET_MAX_CALLS")

#: Characters per token, used only to size a reservation. Deliberately low, which over-estimates
#: the token count, which over-reserves. Never used for accounting: reported usage is.
_CHARS_PER_TOKEN: Final = Decimal(3)


def _env_decimal(name: str, default: Decimal) -> Decimal:
    suffix = name.removeprefix("EXULANICA_")
    raw = env_get(suffix)
    if raw is None or not raw.strip():
        return default
    try:
        value = Decimal(raw.strip())
    except InvalidOperation as exc:
        raise ValueError(f"{name}={raw!r} is not a decimal amount") from exc
    if value < 0:
        raise ValueError(f"{name}={raw!r} is negative")
    return value


def _env_int(name: str, default: int) -> int:
    suffix = name.removeprefix("EXULANICA_")
    raw = env_get(suffix)
    if raw is None or not raw.strip():
        return default
    value = int(raw.strip())
    if value < 0:
        raise ValueError(f"{name}={raw!r} is negative")
    return value


@dataclass
class BudgetGuard:
    """Refuses a call that could take cumulative spend past the ceiling.

    Holds the ledger, so ``spent`` and ``remaining`` are always the same numbers the cost report
    prints. A guard with its own private counter would eventually disagree with the report, and
    then neither number would be trustworthy.
    """

    ceiling_usd: Decimal = field(
        default_factory=lambda: _env_decimal(_CEILING_ENV, DEFAULT_CEILING_USD)
    )
    max_calls: int = field(default_factory=lambda: _env_int(_MAX_CALLS_ENV, DEFAULT_MAX_CALLS))
    ledger: CostLedger = field(default_factory=CostLedger)
    #: What the calls admitted and not yet recorded may cost, and how many they are.
    _held_usd: Decimal = field(default=Decimal(0), init=False, repr=False, compare=False)
    _held_calls: int = field(default=0, init=False, repr=False, compare=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    def __getstate__(self) -> dict[str, Any]:
        # A lock belongs to the guard that made it: a deepcopy or an unpickled guard takes its
        # own (``__setstate__``), and a lock cannot be copied at all.
        state = dict(self.__dict__)
        state.pop("_lock", None)
        return state

    def __copy__(self) -> BudgetGuard:
        # A copy is a guard of its own, as a deepcopy is: a shallow one would share the ledger and
        # not the holds, and so count a call's spend in both but its reservation in one.
        return copy.deepcopy(self)

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)
        self._lock = threading.Lock()

    @property
    def spent_usd(self) -> Decimal:
        return self.ledger.total_usd

    @property
    def remaining_usd(self) -> Decimal:
        return self.ceiling_usd - self.spent_usd

    @property
    def billed_calls(self) -> int:
        return self.ledger.billed_calls

    @property
    def held_usd(self) -> Decimal:
        """What the calls admitted and not yet recorded may cost."""
        return self._held_usd

    @property
    def held_calls(self) -> int:
        """How many calls are admitted and not yet recorded."""
        return self._held_calls

    @property
    def available_usd(self) -> Decimal:
        """What a new call may still reserve: the ceiling less what is spent and what is held."""
        return self.ceiling_usd - self.spent_usd - self._held_usd

    @property
    def available_calls(self) -> int:
        """How many more calls may be admitted: the limit less those billed and those held."""
        return self.max_calls - self.billed_calls - self._held_calls

    def estimate_usd(
        self,
        spec: ModelSpec,
        *,
        prompt_chars: int = 0,
        max_tokens: int = 0,
        extra_prompt_tokens: int = 0,
    ) -> Decimal:
        """Worst-case cost of a call that has not happened yet.

        ``extra_prompt_tokens`` carries image cost, which characters cannot express: a 768px
        image was measured at 772 prompt tokens with almost no accompanying text.
        """
        prompt_tokens = int(Decimal(max(prompt_chars, 0)) / _CHARS_PER_TOKEN) + extra_prompt_tokens
        return spec.cost_usd(
            prompt_tokens=prompt_tokens, completion_tokens=max(max_tokens, 0)
        ).quantize(USD_QUANTUM)

    def reserve(
        self,
        spec: ModelSpec,
        *,
        role: Role,
        prompt_chars: int = 0,
        max_tokens: int = 0,
        extra_prompt_tokens: int = 0,
        keep_usd: Decimal = Decimal(0),
        keep_calls: int = 0,
    ) -> Decimal:
        """Admit this call and hold its reservation, or raise ``BudgetExceededError``.

        ``keep_usd`` and ``keep_calls`` are the part of the budget this call must leave
        untouched; a call that fits the budget but not the part left above them raises
        :class:`BudgetShareExceeded`. Never retry a ``BudgetExceededError``. Retrying is the loop
        the guard is stopping.
        """
        projected = self.estimate_usd(
            spec,
            prompt_chars=prompt_chars,
            max_tokens=max_tokens,
            extra_prompt_tokens=extra_prompt_tokens,
        )
        with self._lock:
            committed_calls = self.billed_calls + self._held_calls
            if committed_calls >= self.max_calls:
                raise BudgetExceededError(
                    f"call ceiling reached: {committed_calls} calls billed or under way in this "
                    f"process, limit {self.max_calls}. This is a runaway loop, not a workload. "
                    f"Raise {_MAX_CALLS_ENV} only after establishing why.",
                    spent_usd=self.spent_usd,
                    ceiling_usd=self.ceiling_usd,
                )
            committed = self.spent_usd + self._held_usd
            if committed + projected > self.ceiling_usd:
                raise BudgetExceededError(
                    f"budget ceiling would be crossed: spent or held "
                    f"${committed.quantize(USD_QUANTUM)}, this {role} call could cost up to "
                    f"${projected}, ceiling ${self.ceiling_usd}. No request was sent. Raise "
                    f"{_CEILING_ENV} deliberately if this is real work.",
                    spent_usd=self.spent_usd,
                    ceiling_usd=self.ceiling_usd,
                )
            if (
                committed_calls >= self.max_calls - keep_calls
                or committed + projected > self.ceiling_usd - keep_usd
            ):
                raise BudgetShareExceeded(
                    f"this {role} call would take the process into the part of its budget kept "
                    f"for other work: ${keep_usd} and {keep_calls} calls of ${self.ceiling_usd} "
                    f"and {self.max_calls}. No request was sent.",
                    spent_usd=self.spent_usd,
                    ceiling_usd=self.ceiling_usd,
                )
            self._held_usd += projected
            self._held_calls += 1
        return projected

    def release(self, reserved: Decimal) -> None:
        """Give back a reservation whose request never left, with nothing to record."""
        with self._lock:
            self._settle(reserved)

    def record(self, usage: CallUsage, *, released: Decimal | None = None) -> CallUsage:
        """Record what the call actually cost, replacing its reservation with the real number.

        ``released`` is the reservation the call was admitted under, given back as its usage is
        recorded; a record with none, a cache hit, held nothing.
        """
        with self._lock:
            if released is not None:
                self._settle(released)
            return self.ledger.record(usage)

    def _settle(self, reserved: Decimal) -> None:
        self._held_usd = max(Decimal(0), self._held_usd - reserved)
        self._held_calls = max(0, self._held_calls - 1)
