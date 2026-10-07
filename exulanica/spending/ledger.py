"""The durable spending authority, as the API and worker processes spend through it.

:class:`DurableSpending` is the :class:`~exulanica.models.spending.SpendingSource` a composition
attaches to its model client; :class:`WorkspaceSpending` is one workspace's
:class:`~exulanica.models.spending.SpendingGate`. Every step is one short transaction on a
connection scoped to the workspace, through the functions migration 0124 grants the runtime:

*   **admit** holds an attempt's worst case against the authority, the workspace's grant and any
    bound, or refuses before anything is sent;
*   **dispatch** records that the attempt may now leave, before the transport is given it;
*   **settle** replaces the reservation with the reported cost, keeps it whole when the outcome is
    unknown, or gives it back when the attempt never left.

Each step is on the authority's ledger, so each runs under the authority's witness lock
(:mod:`exulanica.spending.witness`), taken before the transaction starts, hands the function the
witness it read, and writes the witness the function returns before the commit: no path takes the
authority's row before the lock. Each transaction carries a bounded lock and statement timeout. A
database or witness that does not answer refuses the admission (``spending_unavailable``); it never
lets an attempt through.

Nothing here reads a key or an account. A process is named by the label its composition gives,
its process id and a random nonce (:func:`holder_label`); each attempt it admits adds a nonce of
its own (:attr:`~exulanica.models.spending.SpendingTicket.holder`), which is all a reservation
records of either. Only that attempt dispatches, settles or releases its reservation.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
import os
import re
import secrets
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.db.session import Database
from exulanica.errors import ExulanicaError
from exulanica.models.spending import (
    SPENDING_REFUSALS,
    SpendingRefused,
    SpendingRequest,
    SpendingTicket,
)
from exulanica.models.usage import CallUsage, CostBasis, usd_string
from exulanica.spending.witness import (
    SpendingWitness,
    WitnessHandle,
    WitnessUnavailable,
    advance_record,
)

__all__ = [
    "DEFAULT_LOCK_TIMEOUT_MS",
    "DEFAULT_STATEMENT_TIMEOUT_MS",
    "DurableSpending",
    "SettlementNotRecorded",
    "WorkspaceSpending",
    "holder_label",
    "refusal_from_document",
]

_LOG = logging.getLogger(__name__)

#: How long one spending transaction waits for a row another holds, and how long any of its
#: statements may run. A step past either refuses rather than waits on.
DEFAULT_LOCK_TIMEOUT_MS: Final = 5_000
DEFAULT_STATEMENT_TIMEOUT_MS: Final = 15_000
#: How long a workspace's authority for a provider is remembered before it is asked again. A
#: change within it is caught by the admission itself (``authority_changed``).
_AUTHORITY_TTL_S: Final = 60.0
_LABEL: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def holder_label(label: str) -> str:
    """This process's name on what it reserves: its composition's label, pid and a nonce."""
    if not _LABEL.match(label):
        raise ValueError(f"{label!r} is not a process label")
    return f"{label}:{os.getpid()}:{secrets.token_hex(4)}"


class SettlementNotRecorded(ExulanicaError):
    """A settlement the authority did not take; the reservation stays as it was."""


def refusal_from_document(document: Mapping[str, Any]) -> SpendingRefused:
    """The refusal an authority function answered with, from its document."""

    def text(name: str) -> str | None:
        value = document.get(name)
        return None if value is None else str(value)

    reason = text("reason")
    if reason is None or reason not in SPENDING_REFUSALS:
        return SpendingRefused("spending_unavailable", detail="unrecognised_refusal")
    return SpendingRefused(
        reason,
        scope=text("scope"),
        detail=text("detail"),
        limit=text("limit"),
        committed=text("committed"),
        requested=text("requested"),
    )


@dataclass(frozen=True)
class _Remembered:
    authority_id: uuid.UUID
    until: float


#: Why a guest's allowance is not granted, by the reason ``spending_grant_guest`` answers.
_GUEST_REFUSALS: Final = {
    "workspace_holds_a_grant": "this workspace's allowance is not a guest's to grant",
    "guest_grants_exhausted": "the guest policy has granted as many visitors as it does today",
}


class DurableSpending:
    """Every workspace's durable spending, for one process: the source a client is composed with.

    ``witness`` is where this installation keeps its authorities' witnesses, or None in a process
    that has none, which then refuses to spend under any witnessed authority
    (``spending_suspended``, ``witness_not_configured``) and never falls back to spending without.
    """

    def __init__(
        self,
        database: Database,
        witness: SpendingWitness | None,
        *,
        holder: str,
        lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
        statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    ) -> None:
        if lock_timeout_ms <= 0 or statement_timeout_ms <= 0:
            raise ValueError("spending timeouts are positive")
        self.database = database
        self.witness = witness
        self.holder = holder
        self.lock_timeout_ms = lock_timeout_ms
        self.statement_timeout_ms = statement_timeout_ms
        self._authorities: dict[tuple[uuid.UUID, str], _Remembered] = {}
        self._guard = threading.Lock()
        #: Settlements the authority could not take, for readiness to report.
        self.unsettled = 0

    def __repr__(self) -> str:
        return f"DurableSpending(holder={self.holder!r}, witness={self.witness!r})"

    def for_workspace(self, workspace_id: uuid.UUID) -> WorkspaceSpending:
        if not isinstance(workspace_id, uuid.UUID):
            raise TypeError("a workspace's spending is named by its id")
        return WorkspaceSpending(self, workspace_id, None)

    # -- bounds -----------------------------------------------------------------------------

    def open_bound(
        self,
        workspace_id: uuid.UUID,
        *,
        provider: str,
        key: str,
        ceiling_usd: Decimal,
        max_calls: int,
        valid_until: dt.datetime,
        reason: str,
    ) -> uuid.UUID:
        """A bound for one piece of work under the workspace's live grant, or the one ``key``
        already opened with the same terms. Refuses one larger than the grant."""
        document = self._run(
            workspace_id,
            "select spending_open_bound(%s, %s, %s, %s, %s, %s, %s, %s) as document",
            (
                workspace_id,
                provider,
                key,
                ceiling_usd,
                max_calls,
                valid_until,
                self._actor(),
                reason,
            ),
        )
        if document.get("outcome") != "opened":
            raise refusal_from_document(document)
        return uuid.UUID(str(document["bound_id"]))

    def close_bound(self, workspace_id: uuid.UUID, bound_id: uuid.UUID, *, reason: str) -> bool:
        """Admit nothing more under a bound. True when this closed it, False when it was."""
        document = self._run(
            workspace_id,
            "select spending_close_bound(%s, %s, %s, %s) as document",
            (workspace_id, bound_id, self._actor(), reason),
        )
        return not bool(document.get("repeated"))

    def grant_guest(self, workspace_id: uuid.UUID, *, provider: str) -> uuid.UUID | None:
        """A guest workspace's allowance from ``provider``'s authority, by its guest policy.

        The figures are the policy's, never the caller's (migration 0139); the step is a ledger
        step taken under the authority's witness lock, as an admission is, so the witness moves
        with the ledger. Answers the grant, the same one when asked again, or None where no guest
        policy is set for ``provider``. Refused, raising :class:`SpendingRefused`, under
        ``spending_not_granted`` for a workspace that holds another grant from the authority
        (``workspace_holds_a_grant``) and a policy whose grants of the day are spent
        (``guest_grants_exhausted``); as an admission is refused by a
        suspended, revoked or expired authority; and ``spending_unavailable`` when the database
        does not answer.
        """
        for _ in range(2):
            try:
                with self.database.session(workspace_id) as connection:
                    row = connection.execute(
                        "select spending_guest_policy_authority(%s) as authority_id", (provider,)
                    ).fetchone()
            except psycopg.Error as exc:
                raise SpendingRefused(
                    "spending_unavailable",
                    detail="database_unavailable",
                    message=(
                        "the spending authority's database did not answer "
                        f"({type(exc).__name__}), so no allowance was granted"
                    ),
                ) from exc
            authority = None if row is None else row["authority_id"]
            if authority is None:
                return None
            document = self._witnessed(
                workspace_id,
                authority,
                "select spending_grant_guest(%s, %s, %s, %s, %s) as document",
                (workspace_id, provider, authority, self._actor()),
            )
            outcome = document.get("outcome")
            if outcome == "granted":
                return uuid.UUID(str(document["grant_id"]))
            if outcome == "authority_changed":
                continue
            reason = document.get("reason")
            if reason == "no_guest_policy":
                return None
            if reason in _GUEST_REFUSALS:
                raise SpendingRefused(
                    "spending_not_granted", detail=reason, message=_GUEST_REFUSALS[reason]
                )
            # Refused as an admission is: suspended, revoked or expired, by the authority's reason.
            raise refusal_from_document(document)
        raise SpendingRefused("spending_unavailable", detail="authority_changed")

    # -- the steps --------------------------------------------------------------------------

    def _actor(self) -> str:
        return self.holder

    def _authority(self, workspace_id: uuid.UUID, provider: str) -> uuid.UUID | None:
        with self._guard:
            remembered = self._authorities.get((workspace_id, provider))
        if remembered is None or remembered.until < time.monotonic():
            return None
        return remembered.authority_id

    def _remember(self, workspace_id: uuid.UUID, provider: str, authority_id: uuid.UUID) -> None:
        with self._guard:
            self._authorities[(workspace_id, provider)] = _Remembered(
                authority_id, time.monotonic() + _AUTHORITY_TTL_S
            )

    @contextlib.contextmanager
    def _held(self, authority_id: uuid.UUID | None) -> Iterator[WitnessHandle | None]:
        """The authority's witness, locked, or nothing where there is no witness or authority."""
        if authority_id is None or self.witness is None:
            yield None
            return
        with self.witness.hold(authority_id) as held:
            yield held

    def _run(
        self,
        workspace_id: uuid.UUID,
        statement: str,
        parameters: tuple[Any, ...],
        held: WitnessHandle | None = None,
    ) -> dict[str, Any]:
        """One step's transaction; the witness advanced before its commit and confirmed after."""
        pending: dict[str, Any] | None = None
        try:
            with (
                self.database.session(workspace_id) as connection,
                connection.transaction(),
            ):
                connection.execute(f"set local lock_timeout = '{self.lock_timeout_ms}ms'")
                connection.execute(f"set local statement_timeout = '{self.statement_timeout_ms}ms'")
                row = connection.execute(statement, parameters).fetchone()
                assert row is not None
                document: dict[str, Any] = row["document"]
                advance = document.get("witness")
                if advance is not None and held is not None:
                    pending = advance_record(held.record, advance)
                    held.write(pending, confirmed=False)
        except psycopg.Error as exc:
            raise SpendingRefused(
                "spending_unavailable",
                detail="database_unavailable",
                message=(
                    "the spending authority's database did not answer "
                    f"({type(exc).__name__}), so no request was sent"
                ),
            ) from exc
        except WitnessUnavailable as exc:
            raise SpendingRefused(
                "spending_unavailable",
                detail="witness_unavailable",
                message=f"the spending witness could not be written ({exc}); nothing was sent",
            ) from exc
        if pending is not None and held is not None:
            try:
                held.write(pending, confirmed=True)
            except WitnessUnavailable as exc:
                # The next step reads an unconfirmed witness at the ledger's own sequence, which
                # it accepts: the step took effect.
                _LOG.warning("the spending witness could not be confirmed: %s", exc)
        return document

    def _witnessed(
        self,
        workspace_id: uuid.UUID,
        authority_id: uuid.UUID | None,
        statement: str,
        parameters: tuple[Any, ...],
    ) -> dict[str, Any]:
        """``_run`` under the authority's witness lock, handing the function the witness read."""
        try:
            with self._held(authority_id) as held:
                document = held.document if held is not None else None
                return self._run(workspace_id, statement, (*parameters, _json(document)), held)
        except WitnessUnavailable as exc:
            raise SpendingRefused(
                "spending_unavailable",
                detail="witness_unavailable",
                message=f"the spending witness could not be used ({exc}); nothing was sent",
            ) from exc

    def status(self, workspace_id: uuid.UUID) -> dict[str, Any]:
        """The workspace's own spending, by provider. See :mod:`exulanica.spending.status`."""
        from exulanica.spending.status import workspace_status

        return workspace_status(self.database, workspace_id)


def _json(document: Mapping[str, Any] | None) -> Jsonb | None:
    return None if document is None else Jsonb(dict(document))


class WorkspaceSpending:
    """One workspace's durable spending, or a bound within it: a client's spending gate."""

    def __init__(
        self, source: DurableSpending, workspace_id: uuid.UUID, bound_id: uuid.UUID | None
    ) -> None:
        self._source = source
        self.workspace_id = workspace_id
        self.bound_id = bound_id

    def __repr__(self) -> str:
        return f"WorkspaceSpending(bound={'yes' if self.bound_id else 'no'})"

    def within(self, bound_id: uuid.UUID) -> WorkspaceSpending:
        """This workspace's spending, every attempt also held to ``bound_id``."""
        return WorkspaceSpending(self._source, self.workspace_id, bound_id)

    def admit(self, request: SpendingRequest) -> SpendingTicket:
        source = self._source
        authority = source._authority(self.workspace_id, request.provider)
        # This attempt's own name: another call of this process asking under the same key holds
        # nothing of it, and cannot dispatch, settle or release it.
        holder = f"{source.holder}:{secrets.token_hex(4)}"
        for _ in range(3):
            parameters = (
                self.workspace_id,
                authority,
                request.provider,
                self.bound_id,
                request.key,
                request.model_id,
                request.role,
                request.usd,
                holder,
            )
            statement = "select spending_admit(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) as document"
            document = source._witnessed(self.workspace_id, authority, statement, parameters)
            outcome = document.get("outcome")
            if outcome == "authority_changed":
                authority = uuid.UUID(str(document["authority_id"]))
                source._remember(self.workspace_id, request.provider, authority)
                continue
            if outcome == "admitted":
                admitted = uuid.UUID(str(document["authority_id"]))
                source._remember(self.workspace_id, request.provider, admitted)
                return SpendingTicket(
                    reservation_id=uuid.UUID(str(document["reservation_id"])),
                    authority_id=admitted,
                    workspace_id=self.workspace_id,
                    usd=Decimal(str(document["reserved_usd"])),
                    key=request.key,
                    repeated=bool(document.get("repeated")),
                    holder=holder,
                )
            raise refusal_from_document(document)
        raise SpendingRefused("spending_unavailable", detail="authority_changing")

    def dispatch(self, ticket: SpendingTicket) -> None:
        source = self._source
        document = source._witnessed(
            self.workspace_id,
            ticket.authority_id,
            "select spending_dispatch(%s, %s, %s, %s) as document",
            (self.workspace_id, ticket.reservation_id, ticket.holder or source.holder),
        )
        if document.get("outcome") != "dispatched":
            raise refusal_from_document(document)

    def settle(self, ticket: SpendingTicket, usage: CallUsage) -> None:
        basis = {
            CostBasis.REPORTED: "reported",
            CostBasis.UNKNOWN: "unknown",
            CostBasis.NOT_SENT: "not_sent",
        }.get(usage.cost_basis)
        if basis is None:
            raise SettlementNotRecorded(f"a {usage.cost_basis} attempt holds no reservation")
        self._settle(
            ticket,
            basis,
            Decimal(usd_string(usage.usd)) if basis != "not_sent" else Decimal(0),
            usage.prompt_tokens if basis == "reported" else None,
            usage.completion_tokens if basis == "reported" else None,
        )

    def release(self, ticket: SpendingTicket) -> None:
        self._settle(ticket, "not_sent", Decimal(0), None, None)

    def _settle(
        self,
        ticket: SpendingTicket,
        basis: str,
        usd: Decimal,
        prompt_tokens: int | None,
        completion_tokens: int | None,
    ) -> None:
        source = self._source
        try:
            document = source._witnessed(
                self.workspace_id,
                ticket.authority_id,
                "select spending_settle(%s, %s, %s, %s, %s, %s, %s, %s) as document",
                (
                    self.workspace_id,
                    ticket.reservation_id,
                    ticket.holder or source.holder,
                    basis,
                    usd,
                    prompt_tokens,
                    completion_tokens,
                ),
            )
        except SpendingRefused:
            source.unsettled += 1
            raise
        if document.get("outcome") != "settled":
            source.unsettled += 1
            raise SettlementNotRecorded(
                f"the authority did not take the settlement of {ticket.reservation_id}: "
                f"{document.get('outcome')}"
            )
