"""The durable spending authority a hosted call must be admitted by, as the client sees it.

The process's :class:`~exulanica.models.budget.BudgetGuard` is a safety fuse: it lives in one
process's memory, every process starts it at zero and a restart refills it. It stops a runaway
loop and nothing else. The allowance that is money is kept durably, above this package, by an
operator-issued authority for each provider, a grant for each workspace under it and a bound for
one piece of work under a grant (:mod:`exulanica.spending`). This module is how the client asks
it, without knowing anything about where it is kept:

*   A :class:`SpendingSource` is attached to the client by the composition that builds it
    (``ModelClient(spending=...)``). From then on the client sends nothing without a scope: every
    request is admitted by the :class:`SpendingGate` of the workspace whose rules the request
    carries, resolved when the workspace's policy is attached, or attached explicitly with
    ``ModelClient.with_spending``. The workspace is the one composition named, never one inferred
    from anything a request carries.
*   Each attempt is admitted before anything else happens to it, then dispatched (the durable
    record that it may now leave) before it is sent, then settled by what the provider reported
    or by proof that it never left. An attempt that may have left and whose outcome is unknown
    keeps its whole reservation: the provider may bill a request nobody received an answer to.
*   A request that may be replayed safely is made inside :func:`spending_request_key`, which gives
    each of its attempts a key derived from the caller's own identity for the request, in order,
    so a replay after a crash is admitted as the same attempts and never sent twice when the
    first may have left. Outside one, every attempt gets a fresh key.

A refusal is :class:`SpendingRefused`, a :class:`~exulanica.models.errors.BudgetExceededError`,
raised before anything is sent. Never retry it: retrying is the loop a ceiling stops, and a
duplicate refusal says the request already happened.
"""

from __future__ import annotations

import contextlib
import contextvars
import itertools
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, Protocol, runtime_checkable

from exulanica.models.errors import BudgetExceededError
from exulanica.models.usage import USD_QUANTUM, CallUsage

__all__ = [
    "RETRY_AFTER_REAUTHORIZATION",
    "RETRY_LATER",
    "RETRY_NEVER",
    "SPENDING_REFUSALS",
    "SPENDING_SCOPES",
    "SUSPENSION_DETAILS",
    "SpendingGate",
    "SpendingRefused",
    "SpendingRequest",
    "SpendingSource",
    "SpendingTicket",
    "next_request_key",
    "spending_request_key",
]

#: Every reason a durable admission refuses, and nothing else.
SPENDING_REFUSALS: Final = frozenset(
    {
        # The client was composed with a spending source and this request reached it with no
        # workspace to spend for: a fault in the composition, never in the request.
        "spending_scope_missing",
        # No live grant covers this workspace and provider. Nothing is granted because a
        # workspace exists.
        "spending_not_granted",
        "spending_revoked",
        "spending_expired",
        # A ceiling of the authority, the grant or the bound would be crossed.
        "spending_limit_reached",
        # The authority is held closed until an operator acts: its witness is missing, behind or
        # diverged, or only a copy of it is installed, or its ledger is behind its live witness.
        "spending_suspended",
        # The authority could not be asked just now: its database or its witness did not answer.
        "spending_unavailable",
        # Idempotency: an attempt with this key is already admitted by another attempt (of this
        # process or another), may already have left, or has settled.
        "duplicate_request_in_flight",
        "duplicate_request_unknown",
        "duplicate_request_settled",
    }
)

#: Which level of the allowance refused.
SPENDING_SCOPES: Final = frozenset({"authority", "workspace", "bound"})

#: The detail a ``spending_suspended`` refusal names. ``witness_not_configured`` and
#: ``witness_directory_mismatch`` refuse one process (it has no witness directory, or one that is
#: not the authority's) and ``ledger_behind_witness`` refuses until a restore is reconciled, each
#: for as long as its cause holds; every other suspends the authority until an operator
#: reauthorizes it.
SUSPENSION_DETAILS: Final = frozenset(
    {
        "witness_not_configured",
        "witness_directory_mismatch",
        "ledger_behind_witness",
        "witness_missing",
        "witness_unreadable",
        "witness_behind",
        "witness_diverged",
        "witness_copy_only",
    }
)

RETRY_NEVER: Final = "never"
RETRY_AFTER_REAUTHORIZATION: Final = "after_reauthorization"
RETRY_LATER: Final = "later"

#: What an attempt key may hold, the same rule the reservation table keeps.
_KEY: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/#=-]{0,199}$")
#: How long a caller's own key may be, leaving room for the attempt counter after it.
_KEY_PREFIX_LENGTH: Final = 180


class SpendingRefused(BudgetExceededError):
    """The durable spending authority refused this attempt, and nothing was sent.

    ``reason`` is one of :data:`SPENDING_REFUSALS`; ``scope`` which level refused, where one did;
    ``detail`` narrows the reason (the unit of a ceiling, or why the authority is suspended). The
    amounts are those of the refusing level, as decimal strings, where it states them. An
    authority's own figures are every workspace's spending together, so neither the message nor
    :meth:`problem_member` states them: a workspace learns that the authority refused, and what it
    asked for, and nothing of what other workspaces committed.
    """

    def __init__(
        self,
        reason: str,
        *,
        scope: str | None = None,
        detail: str | None = None,
        limit: str | None = None,
        committed: str | None = None,
        requested: str | None = None,
        message: str | None = None,
    ) -> None:
        if reason not in SPENDING_REFUSALS:
            raise ValueError(f"{reason!r} is not a spending refusal")
        if scope is not None and scope not in SPENDING_SCOPES:
            raise ValueError(f"{scope!r} is not a spending scope")
        self.reason = reason
        self.scope = scope
        self.detail = detail
        self.limit = limit
        self.committed = committed
        self.requested = requested
        shared = scope == "authority"
        super().__init__(
            message or _sentence(reason, scope, detail, limit, committed, requested),
            spent_usd=None if shared else committed,
            ceiling_usd=None if shared else limit,
        )

    @property
    def retry(self) -> str:
        """Whether asking again can succeed, and when: never, after an operator reauthorizes the
        authority, or later, when the authority answers again."""
        if self.reason == "spending_unavailable":
            return RETRY_LATER
        if self.reason == "spending_suspended":
            return RETRY_AFTER_REAUTHORIZATION
        return RETRY_NEVER

    def problem_member(self) -> dict[str, str]:
        """The ``spending`` member of the problem an HTTP refusal carries: codes and decimal
        strings, never an account, a key or another workspace's figures."""
        member = {"reason": self.reason, "retry": self.retry}
        shared = ("limit", "committed") if self.scope == "authority" else ()
        for name in ("scope", "detail", "limit", "committed", "requested"):
            value = getattr(self, name)
            if value is not None and name not in shared:
                member[name] = value
        return member


def _sentence(
    reason: str,
    scope: str | None,
    detail: str | None,
    limit: str | None,
    committed: str | None,
    requested: str | None,
) -> str:
    where = f" ({scope})" if scope else ""
    said = {
        "spending_scope_missing": "this request reached a client that must spend for a "
        "workspace, and no workspace was attached to it",
        "spending_not_granted": "no live spending grant covers this workspace for this provider",
        "spending_revoked": "the spending allowance for this request was revoked",
        "spending_expired": "the spending allowance for this request has expired",
        "spending_limit_reached": "this attempt would cross a spending ceiling",
        "spending_suspended": "the spending authority is held closed until an operator acts",
        "spending_unavailable": "the spending authority could not be asked just now",
        "duplicate_request_in_flight": "another attempt holds this key's admission",
        "duplicate_request_unknown": "an attempt with this key may already have been sent",
        "duplicate_request_settled": "an attempt with this key has already been answered",
    }[reason]
    figures = ""
    unit = "calls" if detail == "calls" else "USD"
    if limit is not None and scope != "authority":
        # A refusal before any attempt (a comparison's start) has no amount it needs.
        needs = "" if requested is None else f", this needs {requested}"
        figures = f": {committed or '0'} {unit} committed of {limit}{needs}"
    elif requested is not None:
        figures = f": this needs {requested} {unit}"
    why = f" [{detail}]" if detail and detail not in ("usd", "calls") else ""
    return f"{said}{where}{why}{figures}. No request was sent."


@dataclass(frozen=True, slots=True)
class SpendingRequest:
    """One attempt, as the client asks for its admission."""

    provider: str
    model_id: str
    role: str
    #: The attempt's worst case, held from admission until it settles.
    usd: Decimal
    #: The attempt's idempotency key (:func:`next_request_key`).
    key: str

    def __post_init__(self) -> None:
        if not isinstance(self.usd, Decimal) or not self.usd.is_finite() or self.usd < 0:
            raise ValueError("a reservation is a finite, non-negative Decimal")
        if self.usd != self.usd.quantize(USD_QUANTUM):
            raise ValueError(f"a reservation is at most eight decimal places, got {self.usd}")
        if not _KEY.match(self.key):
            raise ValueError(f"{self.key!r} is not an attempt key")


@dataclass(frozen=True, slots=True)
class SpendingTicket:
    """An admitted attempt: what the gate needs to dispatch and settle exactly this one."""

    reservation_id: uuid.UUID
    authority_id: uuid.UUID
    workspace_id: uuid.UUID
    usd: Decimal
    key: str
    #: The admission this same attempt already held when it asked again under the same key.
    repeated: bool = False
    #: The gate's name for this one attempt, which alone may dispatch, settle or release it:
    #: another call of the same process asking under the same key is a different attempt.
    holder: str = ""


@runtime_checkable
class SpendingGate(Protocol):
    """One workspace's spending, as a client spends it. Built above this package."""

    def admit(self, request: SpendingRequest) -> SpendingTicket:
        """Hold the attempt's worst case, or raise :class:`SpendingRefused`."""
        ...

    def dispatch(self, ticket: SpendingTicket) -> None:
        """Record, before anything is sent, that the attempt may leave, or raise
        :class:`SpendingRefused`; the attempt is then never sent."""
        ...

    def settle(self, ticket: SpendingTicket, usage: CallUsage) -> None:
        """Replace the attempt's reservation with what it cost, by ``usage.cost_basis``."""
        ...

    def release(self, ticket: SpendingTicket) -> None:
        """Give back the reservation of an attempt that was never sent."""
        ...


@runtime_checkable
class SpendingSource(Protocol):
    """Where every workspace's gate comes from. Attached to a client by its composition."""

    def for_workspace(self, workspace_id: uuid.UUID) -> SpendingGate: ...


@dataclass
class _KeyedRequest:
    prefix: str
    counter: Iterator[int] = field(default_factory=lambda: itertools.count(1))


_REQUEST: contextvars.ContextVar[_KeyedRequest | None] = contextvars.ContextVar(
    "exulanica_spending_request", default=None
)


@contextlib.contextmanager
def spending_request_key(key: str) -> Iterator[None]:
    """Admit every attempt made inside as ``<key>#<n>``, n counting from one in the order the
    attempts are made, so the same request replayed is admitted as the same attempts.

    ``key`` is the caller's own identity for the request, stable across a restart: a decision
    request's id, a job's id and stage. Use it only where the caller would replay the whole
    request after a crash; a duplicate refusal then tells it the request already happened.
    """
    if not isinstance(key, str) or len(key) > _KEY_PREFIX_LENGTH or not _KEY.match(key):
        raise ValueError(f"{key!r} is not a request key")
    token = _REQUEST.set(_KeyedRequest(prefix=key))
    try:
        yield
    finally:
        _REQUEST.reset(token)


def next_request_key() -> str:
    """The next attempt's key: the enclosing request's, counted, or a fresh one."""
    keyed = _REQUEST.get()
    if keyed is None:
        return f"auto:{uuid.uuid4().hex}"
    return f"{keyed.prefix}#{next(keyed.counter)}"
