"""A comparison's durable bounds: one for each provider it asks, under the workspace's grant.

Where a durable spending authority admits a host's calls (:mod:`exulanica.spending`), a comparison
started from the application spends under bounds of its own, the use the authority's bounds were
made for (``docs/model-spending-contract.md``). A bound is one provider's: admission refuses an
attempt under a bound of another provider's grant. So a comparison holds one for each provider it
asks, found again by its key (:func:`bound_key`), on the terms its start recorded: the bound its
owner stated and the most calls it can make, valid while the grant is.

- A start is refused ``bound_exceeds_grant`` before anything is written when its bound, or the
  calls it can make, is more than the live grant of a provider it asks has left
  (:func:`bound_room_refusal`), and its plan states the same refusal by the same reading. A bound is
  never made smaller to fit: one would later stop as spent when the bound its owner set was not.
- The host that plays a start opens its bounds before the first ask, or finds those a host before
  it opened (:func:`open_comparison_bounds`), and every ask of each run is admitted under its own
  provider's bound (:class:`BoundGate`). So what the comparison commits, on every host that plays
  it, never passes its bound at the authority. Where the authority refuses to open a provider's
  bound, each ask of that provider is refused by that refusal before anything is sent.
- Every bound of a start is closed when the start is finished, whatever closed it, and when its
  owner cancels it (:func:`close_comparison_bounds`): an ask a host sends after that is refused by
  the authority, which names the bound (``spending_revoked``, scope ``bound``).

In a process no durable authority admits, none of this applies: a comparison's bound is held in
its host's process alone (:class:`~exulanica.models.budget.BoundedBudget`).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

import psycopg

from exulanica.models.spending import SpendingRefused, SpendingRequest, SpendingTicket
from exulanica.models.usage import CallUsage
from exulanica.spending import DurableSpending
from exulanica.spending.status import admission_refusal, read_workspace_status

__all__ = [
    "BOUND_EXCEEDS_GRANT",
    "BoundGate",
    "ComparisonBounds",
    "bound_key",
    "bound_room_refusal",
    "close_comparison_bounds",
    "open_comparison_bounds",
]

#: Why a start is refused when its bound, or the calls it can make, is more than the live grant of
#: a provider it asks has left.
BOUND_EXCEEDS_GRANT: Final = "bound_exceeds_grant"
#: Why a host opens a comparison's bound, and why the bound is closed, as the authority records it.
_OPENED: Final = "a comparison started from the application"
_KEY: Final = "comparison:{comparison_id}:"
#: The bounds a comparison's key names in the workspace, read as its runtime role: row-level
#: security keeps every other workspace's grants out.
_FOUND: Final = """
select g.grant_id, g.bound_key
  from spending_grant g
 where g.workspace_id = %(workspace)s and g.parent_grant_id is not null
   and starts_with(g.bound_key, %(prefix)s)
"""


def bound_key(comparison_id: uuid.UUID, provider: str) -> str:
    """The key a comparison's bound of ``provider`` is opened and found again by."""
    return _KEY.format(comparison_id=comparison_id) + provider


def bound_room_refusal(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    providers: Iterable[str],
    *,
    usd: Decimal | None,
    calls: int,
) -> tuple[str, str] | None:
    """``bound_exceeds_grant`` and why, when ``usd``, a start's bound, or ``calls``, the most calls
    it can make, is more than the live grant of one of ``providers`` has left (the first such
    provider in order); None while each grant holds both. ``usd`` None judges the calls alone, as
    a plan that names no bound is judged. Read from the workspace's own spending on
    ``connection``, scoped to it. A provider with no live grant, or none left, is the allowance's
    refusal, answered before this one (``Services.allowance_refusal``)."""
    named = sorted(set(providers))
    if not named:
        return None
    status = read_workspace_status(connection, workspace_id, providers=named)
    for entry in status["providers"]:
        if entry["grant"]["state"] != "active":
            continue
        provider, left_usd, left_calls = (
            entry["provider"],
            Decimal(entry["available_usd"]),
            int(entry["available_calls"]),
        )
        if usd is not None and usd > left_usd:
            return (
                BOUND_EXCEEDS_GRANT,
                f"the bound of ${usd} is more than the ${left_usd} this workspace's grant of "
                f"{provider} has left",
            )
        if calls > left_calls:
            return (
                BOUND_EXCEEDS_GRANT,
                f"this comparison can make {calls} calls, more than the {left_calls} this "
                f"workspace's grant of {provider} has left",
            )
    return None


@dataclass(frozen=True)
class ComparisonBounds:
    """The bounds one comparison's start is played under: by provider, the bound a host opened or
    found, or the authority's refusal to open it."""

    spending: DurableSpending
    workspace_id: uuid.UUID
    bounds: Mapping[str, uuid.UUID]
    refused: Mapping[str, SpendingRefused]

    def gate(self) -> BoundGate:
        """A run's own spending gate under these bounds."""
        return BoundGate(self)


class BoundGate:
    """One run's spending gate: each attempt admitted by the authority under its provider's bound,
    and an attempt of a provider whose bound the authority refused to open refused as it was,
    before anything is sent. Dispatch, settlement and release name the admitted reservation
    alone, so they go to the workspace's spending. It keeps the last refusal of one of the run's
    attempts by its bound itself, so the run can say why it stopped."""

    def __init__(self, bounds: ComparisonBounds) -> None:
        self.workspace_id = bounds.workspace_id
        self._bounds = bounds
        self._workspace = bounds.spending.for_workspace(bounds.workspace_id)
        #: The authority's refusal of one of this run's attempts by its bound (scope ``bound``):
        #: closed, expired, committed to its ceiling or calls, or no longer under the live grant.
        self.bound_refusal: SpendingRefused | None = None

    def __repr__(self) -> str:
        return f"BoundGate(providers={sorted(self._bounds.bounds)!r})"

    def admit(self, request: SpendingRequest) -> SpendingTicket:
        bound = self._bounds.bounds.get(request.provider)
        if bound is None:
            refused = self._bounds.refused.get(request.provider)
            if refused is None:
                # A provider the start asks none of is never asked outside a bound.
                raise SpendingRefused(
                    "spending_not_granted", scope="bound", detail="no_comparison_bound"
                )
            raise SpendingRefused(
                refused.reason,
                scope=refused.scope,
                detail=refused.detail,
                limit=refused.limit,
                committed=refused.committed,
                requested=refused.requested,
            )
        try:
            return self._workspace.within(bound).admit(request)
        except SpendingRefused as refused:
            if refused.scope == "bound":
                self.bound_refusal = refused
            raise

    def dispatch(self, ticket: SpendingTicket) -> None:
        self._workspace.dispatch(ticket)

    def settle(self, ticket: SpendingTicket, usage: CallUsage) -> None:
        self._workspace.settle(ticket, usage)

    def release(self, ticket: SpendingTicket) -> None:
        self._workspace.release(ticket)


def open_comparison_bounds(
    spending: DurableSpending,
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    comparison_id: uuid.UUID,
    providers: Iterable[str],
    *,
    usd: Decimal,
    calls: int,
) -> ComparisonBounds:
    """The start's bounds, one for each of ``providers``: the one a host before this one opened,
    found by its key whatever became of it since (admission says), or one opened now under the
    provider's live grant with the start's terms, ``usd`` and ``calls``, valid while the grant is.
    Where the workspace holds no live grant of a provider, or the authority refuses to open its
    bound, that refusal is kept for the provider's asks. ``connection`` is scoped to the
    workspace; each bound is opened in the authority's own transaction."""
    named = sorted(set(providers))
    found = _found(connection, workspace_id, comparison_id)
    missing = [provider for provider in named if provider not in found]
    entries = (
        {
            entry["provider"]: entry
            for entry in read_workspace_status(connection, workspace_id, providers=missing)[
                "providers"
            ]
        }
        if missing
        else {}
    )
    bounds = {provider: found[provider] for provider in named if provider in found}
    refused: dict[str, SpendingRefused] = {}
    for provider in missing:
        entry = entries[provider]
        grant = entry["grant"]
        if grant["state"] != "active":
            refused[provider] = admission_refusal(
                entry, witness_configured=spending.witness is not None
            ) or SpendingRefused("spending_not_granted", scope="workspace")
            continue
        try:
            bounds[provider] = spending.open_bound(
                workspace_id,
                provider=provider,
                key=bound_key(comparison_id, provider),
                ceiling_usd=usd,
                max_calls=calls,
                valid_until=dt.datetime.fromisoformat(grant["valid_until"]),
                reason=_OPENED,
            )
        except SpendingRefused as exc:
            refused[provider] = exc
    return ComparisonBounds(spending, workspace_id, bounds, refused)


def close_comparison_bounds(
    spending: DurableSpending,
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    comparison_id: uuid.UUID,
    *,
    reason: str,
) -> int:
    """Close every bound opened for the comparison, so the authority admits nothing more under
    any of them, on any host. Returns how many this closed; one already closed stays closed."""
    return sum(
        spending.close_bound(workspace_id, bound, reason=reason)
        for bound in _found(connection, workspace_id, comparison_id).values()
    )


def _found(
    connection: psycopg.Connection, workspace_id: uuid.UUID, comparison_id: uuid.UUID
) -> dict[str, uuid.UUID]:
    """The bounds opened for the comparison in the workspace, by provider."""
    prefix = _KEY.format(comparison_id=comparison_id)
    rows = connection.execute(_FOUND, {"workspace": workspace_id, "prefix": prefix}).fetchall()
    return {str(row["bound_key"])[len(prefix) :]: uuid.UUID(str(row["grant_id"])) for row in rows}
