"""A living session's spending: each model ask of an open session admitted under its own bound.

The host asks a model for a society's beings only while a living session is open
(:mod:`exulanica.world.society_sessions`), and each attempt it makes then is admitted by the
durable spending authority under the session's bound of the attempt's provider: a bound opened
under the workspace's live grant the first time the session asks that provider, found again by its
key (``living-session:<session_id>:<provider>``) every minute after. Its ceiling, calls and validity
are each the lower of the session's own limit and what the grant has left, so a bound never asks
the authority for more than its grant holds, and the session never spends more than it states.

A provider whose grant is not live, or has nothing left, is refused before anything is sent, with
the authority's own reason, as a comparison's bound is (:mod:`exulanica.api.comparison_spending`).
"""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from decimal import Decimal
from typing import Any, Final

import psycopg

from exulanica.models.spending import SpendingRefused, SpendingRequest, SpendingTicket
from exulanica.models.usage import CallUsage
from exulanica.spending import DurableSpending
from exulanica.spending.status import admission_refusal, read_workspace_status

__all__ = ["SessionGate", "bound_key"]

#: Why a host opens a session's bound, as the authority records it.
_OPENED: Final = "a living session asked a model of this provider"
_KEY: Final = "living-session:{session_id}:"
#: The bounds a session's key names in the workspace, read as its runtime role: row-level security
#: keeps every other workspace's grants out.
_FOUND: Final = """
select g.grant_id, g.bound_key
  from spending_grant g
 where g.workspace_id = %(workspace)s and g.parent_grant_id is not null
   and starts_with(g.bound_key, %(prefix)s)
"""


def bound_key(session_id: str, provider: str) -> str:
    """The key a session's bound of ``provider`` is opened and found again by."""
    return _KEY.format(session_id=session_id) + provider


def _when(stamp: str) -> dt.datetime:
    return dt.datetime.fromisoformat(stamp)


class SessionGate:
    """One minute's spending gate for an open living session's asks.

    Each attempt is admitted by the authority under its provider's session bound, which is found
    by its key or opened on the first ask; dispatch, settlement and release name the admitted
    reservation alone, so they go to the workspace's spending. A provider the authority refused a
    bound to stays refused for the rest of the minute, without asking again.
    """

    def __init__(
        self,
        spending: DurableSpending,
        workspace_id: uuid.UUID,
        session: Mapping[str, Any],
        connect: Callable[[], AbstractContextManager[psycopg.Connection]],
    ) -> None:
        self.workspace_id = workspace_id
        self._spending = spending
        self._session = session
        self._connect = connect
        self._workspace = spending.for_workspace(workspace_id)
        self._bounds: dict[str, uuid.UUID] = {}
        self._refused: dict[str, SpendingRefused] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"SessionGate(session={self._session['session_id']!r})"

    def _terms(self, provider: str) -> tuple[uuid.UUID | None, dict[str, Any] | None]:
        """The session's bound of ``provider`` where one was opened, else the terms to open it."""
        prefix = _KEY.format(session_id=self._session["session_id"])
        with self._connect() as connection:
            for row in connection.execute(
                _FOUND, {"workspace": self.workspace_id, "prefix": prefix}
            ).fetchall():
                if str(row["bound_key"])[len(prefix) :] == provider:
                    return uuid.UUID(str(row["grant_id"])), None
            [entry] = read_workspace_status(connection, self.workspace_id, providers=[provider])[
                "providers"
            ]
        grant = entry["grant"]
        if grant["state"] != "active":
            raise admission_refusal(
                entry, witness_configured=self._spending.witness is not None
            ) or SpendingRefused("spending_not_granted", scope="workspace")
        limits = self._session["limits"]
        usd = min(Decimal(limits["usd"]), Decimal(entry["available_usd"]))
        calls = min(int(limits["calls"]), int(entry["available_calls"]))
        if usd <= 0 or calls <= 0:
            raise SpendingRefused("spending_limit_reached", scope="workspace")
        return None, {
            "ceiling_usd": usd,
            "max_calls": calls,
            "valid_until": min(_when(self._session["ends_by"]), _when(grant["valid_until"])),
        }

    def _bound(self, provider: str) -> uuid.UUID:
        with self._lock:
            if provider in self._bounds:
                return self._bounds[provider]
            if provider in self._refused:
                raise self._refused[provider]
            try:
                found, terms = self._terms(provider)
                if found is None:
                    assert terms is not None
                    found = self._spending.open_bound(
                        self.workspace_id,
                        provider=provider,
                        key=bound_key(self._session["session_id"], provider),
                        reason=_OPENED,
                        **terms,
                    )
            except SpendingRefused as refused:
                self._refused[provider] = refused
                raise
            self._bounds[provider] = found
            return found

    def admit(self, request: SpendingRequest) -> SpendingTicket:
        return self._workspace.within(self._bound(request.provider)).admit(request)

    def dispatch(self, ticket: SpendingTicket) -> None:
        self._workspace.dispatch(ticket)

    def settle(self, ticket: SpendingTicket, usage: CallUsage) -> None:
        self._workspace.settle(ticket, usage)

    def release(self, ticket: SpendingTicket) -> None:
        self._workspace.release(ticket)
