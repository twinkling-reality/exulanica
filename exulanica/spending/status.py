"""What one workspace may still spend, from its own rows alone.

Read on a connection scoped to the workspace, as its runtime role: row-level security keeps every
other workspace's grants and reservations out, and nothing here states an authority's committed
total, which is every workspace's spending together. An authority is described by its state
alone, through ``spending_authority_facts``, which states no amount: the runtime roles cannot read
the authority tables or the ledger themselves. Amounts are decimal strings at the ledger's eight
places.

"Known usage" is the provider's reported token counts priced by the manifest. It is not billing:
only a reconciled amount, which an operator recorded with evidence, comes from the provider's side.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

import psycopg

from exulanica.db.session import Database
from exulanica.models.manifest import load_manifest
from exulanica.models.spending import SpendingRefused
from exulanica.models.usage import usd_string

__all__ = [
    "STATUS_PROFILE",
    "UNRESOLVED_AFTER",
    "SpendingRefusals",
    "admission_refusal",
    "authority_states",
    "read_spending_refusals",
    "read_workspace_status",
    "workspace_status",
]

STATUS_PROFILE: Final = "exulanica.workspace-spending/v1"

#: A dispatched attempt with no settlement after this long is reported as unresolved: it may have
#: been billed and nobody recorded what it cost. Longer than any role's timeout with its retries.
UNRESOLVED_AFTER: Final = dt.timedelta(minutes=15)

_GRANTS: Final = """
select g.grant_id, g.authority_id, f.provider, f.witnessed, g.ceiling_usd, g.max_calls,
       g.valid_until, g.created_at, gs.committed_usd, gs.committed_calls,
       exists (select 1 from spending_grant_revocation v
                where v.workspace_id = g.workspace_id and v.grant_id = g.grant_id) as revoked,
       f.revoked as authority_revoked, f.suspended_reason,
       f.valid_until as authority_valid_until, f.exhausted as authority_exhausted
  from spending_grant g
  join spending_grant_state gs on gs.workspace_id = g.workspace_id and gs.grant_id = g.grant_id
  join spending_authority_facts() f on f.authority_id = g.authority_id
 where g.workspace_id = %(workspace)s and g.parent_grant_id is null
 order by f.provider, g.created_at desc, g.grant_id desc
"""

_RESERVATIONS: Final = """
select x.grant_id,
       coalesce(sum(x.reserved_usd) filter (
         where x.state = 'admitted'
            or (x.state = 'dispatched' and x.dispatched_at > %(horizon)s)), 0) as in_flight_usd,
       count(*) filter (
         where x.state = 'unknown'
            or (x.state = 'dispatched' and x.dispatched_at <= %(horizon)s)) as unresolved_count,
       coalesce(sum(case when x.state = 'unknown' then x.settled_usd
                         when x.state = 'dispatched' and x.dispatched_at <= %(horizon)s
                         then x.reserved_usd end), 0) as unresolved_usd,
       coalesce(sum(x.settled_usd) filter (where x.state = 'settled'), 0) as known_usage_usd,
       coalesce(sum(x.settled_usd) filter (where x.state = 'reconciled'), 0) as reconciled_usd
  from spending_reservation x
 where x.workspace_id = %(workspace)s
 group by x.grant_id
"""


def workspace_status(
    database: Database,
    workspace_id: uuid.UUID,
    *,
    providers: Iterable[str] | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """The workspace's spending document: one entry per provider the manifest names."""
    with database.session(workspace_id) as connection:
        return read_workspace_status(connection, workspace_id, providers=providers, now=now)


def read_workspace_status(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    providers: Iterable[str] | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """:func:`workspace_status` on a connection already scoped to the workspace."""
    entries = _entries(connection, workspace_id, providers, now, held=True)
    return {"profile": STATUS_PROFILE, "workspace_id": str(workspace_id), "providers": entries}


def _entries(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    providers: Iterable[str] | None,
    now: dt.datetime | None,
    *,
    held: bool,
) -> list[dict[str, Any]]:
    """One entry per provider. Without ``held`` the workspace's reservations are not read, and
    what they hold (in flight, unresolved, known usage, reconciled) is stated as nothing: what is
    left, and every state, comes from the grants alone."""
    names = sorted(load_manifest().providers) if providers is None else sorted(providers)
    row = connection.execute("select statement_timestamp() as t").fetchone()
    assert row is not None
    instant = now or row["t"]
    parameters = {"workspace": workspace_id, "horizon": instant - UNRESOLVED_AFTER}
    grants = connection.execute(_GRANTS, parameters).fetchall()
    reservations = (
        {row["grant_id"]: row for row in connection.execute(_RESERVATIONS, parameters)}
        if held
        else {}
    )
    entries = []
    for provider in names:
        mine = [row for row in grants if row["provider"] == provider]
        live = [row for row in mine if _grant_state(row, instant) == "active"]
        chosen = (live or mine or [None])[0]
        entries.append(_entry(provider, chosen, reservations, instant))
    return entries


def _grant_state(row: dict[str, Any], instant: dt.datetime) -> str:
    if row["revoked"]:
        return "revoked"
    if row["valid_until"] <= instant:
        return "expired"
    return "active"


def _authority_state(row: dict[str, Any], instant: dt.datetime) -> str:
    if row["authority_revoked"]:
        return "revoked"
    if row["suspended_reason"] is not None:
        return "suspended"
    if row["authority_valid_until"] <= instant:
        return "expired"
    if row["authority_exhausted"]:
        return "exhausted"
    return "active"


def _entry(
    provider: str,
    row: dict[str, Any] | None,
    reservations: dict[uuid.UUID, dict[str, Any]],
    instant: dt.datetime,
) -> dict[str, Any]:
    zero = usd_string(Decimal(0))
    if row is None:
        return {
            "provider": provider,
            "grant": {"state": "none"},
            "authority_state": "none",
            "restore_protection": "none",
            "committed_usd": zero,
            "committed_calls": 0,
            "in_flight_usd": zero,
            "unresolved": {"count": 0, "usd": zero},
            "known_usage_usd": zero,
            "reconciled_usd": zero,
            "available_usd": zero,
            "available_calls": 0,
        }
    grant_state = _grant_state(row, instant)
    authority_state = _authority_state(row, instant)
    held = reservations.get(row["grant_id"], {})
    spendable = grant_state == "active" and authority_state == "active"
    available_usd = max(Decimal(0), row["ceiling_usd"] - row["committed_usd"]) if spendable else 0
    available_calls = max(0, row["max_calls"] - row["committed_calls"]) if spendable else 0
    entry: dict[str, Any] = {
        "provider": provider,
        "grant": {
            "grant_id": str(row["grant_id"]),
            "ceiling_usd": usd_string(row["ceiling_usd"]),
            "max_calls": row["max_calls"],
            "valid_until": row["valid_until"].isoformat(),
            "state": grant_state,
        },
        "authority_state": authority_state,
        "restore_protection": "witnessed" if row["witnessed"] else "none",
        "committed_usd": usd_string(row["committed_usd"]),
        "committed_calls": row["committed_calls"],
        "in_flight_usd": usd_string(held.get("in_flight_usd", Decimal(0))),
        "unresolved": {
            "count": int(held.get("unresolved_count", 0)),
            "usd": usd_string(held.get("unresolved_usd", Decimal(0))),
        },
        "known_usage_usd": usd_string(held.get("known_usage_usd", Decimal(0))),
        "reconciled_usd": usd_string(held.get("reconciled_usd", Decimal(0))),
        "available_usd": usd_string(Decimal(available_usd)),
        "available_calls": available_calls,
    }
    if authority_state == "suspended":
        entry["suspension"] = row["suspended_reason"]
    return entry


_AUTHORITIES: Final = """
select f.authority_id, f.provider, f.witnessed, f.epoch, f.suspended_reason, f.valid_until,
       f.revoked, f.exhausted
  from spending_authority_facts() f
 order by f.provider, f.created_at, f.authority_id
"""


def authority_states(database: Database) -> list[dict[str, Any]]:
    """Every authority's state, for an installation's facts: its provider, whether it is active,
    suspended (and why), expired, revoked or exhausted, whether a witness protects it, and its
    epoch.

    Reads ``spending_authority_facts``, which holds no workspace's rows and states no amount, on a
    connection that names no workspace, so the runtime or the read-only role can ask.
    """
    with database.unscoped() as connection:
        instant = connection.execute("select statement_timestamp() as t").fetchone()["t"]
        rows = connection.execute(_AUTHORITIES).fetchall()
    states = []
    for row in rows:
        if row["revoked"]:
            state = "revoked"
        elif row["suspended_reason"] is not None:
            state = "suspended"
        elif row["valid_until"] <= instant:
            state = "expired"
        elif row["exhausted"]:
            state = "exhausted"
        else:
            state = "active"
        entry = {
            "authority_id": str(row["authority_id"]),
            "provider": row["provider"],
            "state": state,
            "restore_protection": "witnessed" if row["witnessed"] else "none",
            "epoch": row["epoch"],
        }
        if state == "suspended":
            entry["suspension"] = row["suspended_reason"]
        states.append(entry)
    return states


def admission_refusal(
    entry: Mapping[str, Any], *, witness_configured: bool
) -> SpendingRefused | None:
    """The refusal ``spending_admit`` gives the workspace's next attempt of the entry's provider,
    as far as the workspace's own spending states it, or None while one may be admitted.

    ``entry`` is one provider's entry of :func:`read_workspace_status`; ``witness_configured``
    whether the asking process has a witness directory. The reason and scope are admission's, in
    its order. With no live grant, the state of the workspace's latest grant
    (``spending__refusal_without_grant``), its authority first. With one, the authority suspended,
    a witnessed authority asked by a process with no witness directory, the authority expired or
    exhausted, then the grant's calls and money. The grant's figures are stated as admission
    states them.

    What it cannot foresee is refused at request time: a remainder above zero that one attempt's
    reservation does not fit, an authority whose own remainder (every workspace's spending
    together, which no workspace reads) does not fit it, and a witness directory that is not the
    authority's. Since no attempt is made, it states no requested amount, and for an exhausted
    authority neither unit.
    """
    grant = entry["grant"]
    authority = entry["authority_state"]
    if grant["state"] == "none":
        return SpendingRefused("spending_not_granted", scope="workspace")
    if grant["state"] != "active" or authority == "revoked":
        if authority == "revoked":
            return SpendingRefused("spending_revoked", scope="authority")
        if grant["state"] == "revoked":
            return SpendingRefused("spending_revoked", scope="workspace")
        return SpendingRefused("spending_expired", scope="workspace")
    if authority == "suspended":
        return SpendingRefused("spending_suspended", scope="authority", detail=entry["suspension"])
    if entry["restore_protection"] == "witnessed" and not witness_configured:
        return SpendingRefused(
            "spending_suspended", scope="authority", detail="witness_not_configured"
        )
    if authority == "expired":
        return SpendingRefused("spending_expired", scope="authority")
    if authority == "exhausted":
        return SpendingRefused("spending_limit_reached", scope="authority")
    if entry["available_calls"] < 1:
        return SpendingRefused(
            "spending_limit_reached",
            scope="workspace",
            detail="calls",
            limit=str(grant["max_calls"]),
            committed=str(entry["committed_calls"]),
            requested="1",
        )
    if Decimal(entry["available_usd"]) <= 0:
        return SpendingRefused(
            "spending_limit_reached",
            scope="workspace",
            detail="usd",
            limit=grant["ceiling_usd"],
            committed=entry["committed_usd"],
        )
    return None


@dataclass(frozen=True, slots=True)
class SpendingRefusals:
    """What admission would answer a workspace's next attempt, by provider: its refusal
    (:func:`admission_refusal`), or None while that provider's allowance remains; and, where read,
    each provider's remaining USD (``available_usd``), against which a caller can tell that no
    attempt's reservation fits before asking."""

    by_provider: Mapping[str, SpendingRefused | None]
    available_usd: Mapping[str, Decimal] = field(default_factory=dict)

    def first(self, providers: Iterable[str]) -> SpendingRefused | None:
        """The refusal of the first of ``providers`` whose allowance is spent, or None."""
        for provider in providers:
            refused = self.by_provider.get(provider)
            if refused is not None:
                return refused
        return None

    def every(self, providers: Iterable[str]) -> SpendingRefused | None:
        """The first provider's refusal when the allowance of every one of ``providers`` is
        spent; None when one has allowance left, or none is named."""
        found = [self.by_provider.get(provider) for provider in providers]
        return found[0] if found and all(refused is not None for refused in found) else None


def read_spending_refusals(
    connection: psycopg.Connection, workspace_id: uuid.UUID, *, witness_configured: bool
) -> SpendingRefusals:
    """:func:`admission_refusal` for every provider the manifest names, read on ``connection``,
    scoped to the workspace, from its grants alone: admission compares what is committed with
    each ceiling, so what its reservations hold is not read."""
    entries = _entries(connection, workspace_id, None, None, held=False)
    return SpendingRefusals(
        {
            entry["provider"]: admission_refusal(entry, witness_configured=witness_configured)
            for entry in entries
        },
        {entry["provider"]: Decimal(entry["available_usd"]) for entry in entries},
    )
