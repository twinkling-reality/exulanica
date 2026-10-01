"""An operator's decisions about spending: issue, adjust, grant, revoke, reconcile, reauthorize.

Each is administrative. It connects with a complete view of every workspace (a role with
SUPERUSER or BYPASSRLS, as the restore checkpoint requires), takes the authority's witness lock
before its transaction, runs the migration's function for it, and writes the witness before the
commit, as a runtime step does. None of these grants money because a workspace exists, and none is
reachable from the application: the runtime roles may not execute these functions.

What each is for:

*   :meth:`SpendingOperator.issue` an authority for one provider: its ceiling, call limit,
    validity and dispatch window, and whether a witness protects it from a restore (always, in an
    installation; ``witnessed=False`` is for development and tests).
*   :meth:`SpendingOperator.adjust` its terms as a new epoch; :meth:`SpendingOperator.grant` a
    workspace an allowance under it, never larger than its terms.
*   :meth:`SpendingOperator.revoke` an authority, a grant or a bound: nothing more is admitted
    under it, and its history stays.
*   :meth:`SpendingOperator.reconcile` one attempt whose outcome is unknown to an amount evidence
    shows: a source, a reference and when it was observed; never a key or an account.
*   :meth:`SpendingOperator.reconcile_restore` a restored ledger to its witness, live or a copy
    from custody, carrying forward what the witness says was committed;
    :meth:`SpendingOperator.reauthorize` an authority whose witness was lost or cannot be trusted,
    with explicit new terms. A witness that may hold spending the ledger lacks is discarded only
    with ``discard_witness``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from exulanica.db.session import Database
from exulanica.errors import ExulanicaError
from exulanica.spending.witness import SpendingWitness, WitnessHandle, advance_record

__all__ = ["SpendingOperationRefused", "SpendingOperator"]


class SpendingOperationRefused(ExulanicaError):
    """The database refused the operation, and said why; nothing changed."""


class SpendingOperator:
    """An operator's spending decisions, on an administrative connection."""

    def __init__(self, database: Database, witness: SpendingWitness | None) -> None:
        self.database = database
        self.witness = witness

    def _step(
        self,
        authority_id: uuid.UUID,
        statement: str,
        parameters: tuple[Any, ...],
        *,
        witnessed: bool,
        pass_witness: bool = True,
    ) -> dict[str, Any]:
        """One administrative step under the authority's witness lock."""
        if witnessed and self.witness is None:
            raise SpendingOperationRefused(
                "this authority is witnessed and no witness directory is configured "
                "(EXULANICA_SPENDING_WITNESS_DIR)"
            )
        if not witnessed or self.witness is None:
            return self._transaction(
                statement, (*parameters, None) if pass_witness else parameters, None
            )
        with self.witness.hold(authority_id) as held:
            document = held.document
            return self._transaction(
                statement,
                (*parameters, Jsonb(document) if document is not None else None)
                if pass_witness
                else parameters,
                held,
            )

    def _transaction(
        self, statement: str, parameters: tuple[Any, ...], held: WitnessHandle | None
    ) -> dict[str, Any]:
        pending: dict[str, Any] | None = None
        try:
            # An unscoped connection is one transaction, committed as the block closes: the
            # witness is written before that commit and confirmed after it.
            with self.database.unscoped() as connection:
                connection.execute("set local lock_timeout = '5000ms'")
                connection.execute("set local statement_timeout = '60000ms'")
                row = connection.execute(statement, parameters).fetchone()
                assert row is not None
                document: dict[str, Any] = row["document"]
                advance = document.get("witness")
                if advance is not None and held is not None:
                    pending = advance_record(held.record, advance)
                    held.write(pending, confirmed=False)
        except psycopg.Error as exc:
            message = getattr(getattr(exc, "diag", None), "message_primary", None) or str(exc)
            raise SpendingOperationRefused(message) from exc
        if pending is not None and held is not None:
            held.write(pending, confirmed=True)
        return document

    def _witnessed(self, authority_id: uuid.UUID) -> bool:
        with self.database.unscoped() as connection:
            row = connection.execute(
                "select witnessed from spending_authority where authority_id = %s",
                (authority_id,),
            ).fetchone()
        if row is None:
            raise SpendingOperationRefused(f"no spending authority {authority_id}")
        return bool(row["witnessed"])

    # -- the decisions ----------------------------------------------------------------------

    def issue(
        self,
        *,
        provider: str,
        ceiling_usd: Decimal,
        max_calls: int,
        valid_until: dt.datetime,
        operator: str,
        reason: str,
        dispatch_seconds: int = 60,
        witnessed: bool = True,
    ) -> uuid.UUID:
        authority_id = uuid.uuid4()
        self._step(
            authority_id,
            "select spending_issue(%s, %s, %s, %s, %s, %s, %s, %s, %s) as document",
            (
                authority_id,
                provider,
                ceiling_usd,
                max_calls,
                valid_until,
                dispatch_seconds,
                witnessed,
                operator,
                reason,
            ),
            witnessed=witnessed,
            pass_witness=False,
        )
        return authority_id

    def adjust(
        self,
        authority_id: uuid.UUID,
        *,
        ceiling_usd: Decimal,
        max_calls: int,
        valid_until: dt.datetime,
        operator: str,
        reason: str,
    ) -> int:
        document = self._step(
            authority_id,
            "select spending_adjust(%s, %s, %s, %s, %s, %s, %s) as document",
            (authority_id, ceiling_usd, max_calls, valid_until, operator, reason),
            witnessed=self._witnessed(authority_id),
        )
        return int(document["epoch"])

    def grant(
        self,
        authority_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        ceiling_usd: Decimal,
        max_calls: int,
        valid_until: dt.datetime,
        operator: str,
        reason: str,
    ) -> uuid.UUID:
        document = self._step(
            authority_id,
            "select spending_grant_workspace(%s, %s, %s, %s, %s, %s, %s, %s) as document",
            (authority_id, workspace_id, ceiling_usd, max_calls, valid_until, operator, reason),
            witnessed=self._witnessed(authority_id),
        )
        return uuid.UUID(str(document["grant_id"]))

    def revoke(
        self,
        authority_id: uuid.UUID,
        *,
        operator: str,
        reason: str,
        workspace_id: uuid.UUID | None = None,
        grant_id: uuid.UUID | None = None,
    ) -> str:
        """Revoke the authority, or with ``grant_id`` one of its grants or bounds in
        ``workspace_id``. Returns ``revoked``, or ``already`` when it was."""
        if (workspace_id is None) != (grant_id is None):
            raise ValueError("a grant is revoked in its workspace: name both or neither")
        document = self._step(
            authority_id,
            "select spending_revoke(%s, %s, %s, %s, %s, %s) as document",
            (authority_id, workspace_id, grant_id, operator, reason),
            witnessed=self._witnessed(authority_id),
        )
        return str(document["outcome"])

    def reconcile(
        self,
        workspace_id: uuid.UUID,
        reservation_id: uuid.UUID,
        *,
        usd: Decimal,
        source: str,
        reference: str,
        observed_at: dt.datetime,
        operator: str,
    ) -> None:
        with self.database.unscoped() as connection:
            row = connection.execute(
                "select authority_id from spending_reservation "
                "where workspace_id = %s and reservation_id = %s",
                (workspace_id, reservation_id),
            ).fetchone()
        if row is None:
            raise SpendingOperationRefused(f"no reservation {reservation_id} in that workspace")
        authority_id = row["authority_id"]
        evidence = {
            "source": source,
            "reference": reference,
            "observed_at": observed_at.isoformat(),
        }
        self._step(
            authority_id,
            "select spending_reconcile(%s, %s, %s, %s, %s, %s) as document",
            (workspace_id, reservation_id, usd, Jsonb(evidence), operator),
            witnessed=self._witnessed(authority_id),
        )

    def reconcile_restore(
        self, authority_id: uuid.UUID, *, operator: str, reason: str
    ) -> dict[str, Any]:
        """Carry a restored ledger forward to the authority's witness: the live one, or a copy
        installed from custody (after which the authority stays suspended until reauthorized)."""
        if self.witness is None:
            raise SpendingOperationRefused("a restore is reconciled against the witness")
        with self.witness.hold(authority_id) as held:
            document = held.document
            if document is None or document.get("status") not in ("live", "copy"):
                raise SpendingOperationRefused(
                    "no witness or copy to reconcile against: reauthorize the authority instead"
                )
            return self._transaction(
                "select spending_reconcile_restore(%s, %s, %s, %s) as document",
                (authority_id, Jsonb(document), operator, reason),
                held,
            )

    def reauthorize(
        self,
        authority_id: uuid.UUID,
        *,
        ceiling_usd: Decimal,
        max_calls: int,
        valid_until: dt.datetime,
        operator: str,
        reason: str,
        discard_witness: bool = False,
    ) -> int:
        """A new epoch with explicit terms, which clears a suspension and writes the witness whole
        from the ledger. A witness or copy ahead of the ledger, diverged from it, or another
        authority's is refused unless ``discard_witness``: reconcile a restore instead."""
        witnessed = self._witnessed(authority_id)
        if witnessed and self.witness is None:
            raise SpendingOperationRefused("a witnessed authority is reauthorized with its witness")
        if not witnessed or self.witness is None:
            document = self._transaction(
                "select spending_reauthorize(%s, %s, %s, %s, %s, %s, %s, %s) as document",
                (
                    authority_id,
                    ceiling_usd,
                    max_calls,
                    valid_until,
                    operator,
                    reason,
                    None,
                    discard_witness,
                ),
                None,
            )
            return int(document["epoch"])
        with self.witness.hold(authority_id) as held:
            document_read = held.document
            document = self._transaction(
                "select spending_reauthorize(%s, %s, %s, %s, %s, %s, %s, %s) as document",
                (
                    authority_id,
                    ceiling_usd,
                    max_calls,
                    valid_until,
                    operator,
                    reason,
                    Jsonb(document_read) if document_read is not None else None,
                    discard_witness,
                ),
                _Fresh(held),
            )
        return int(document["epoch"])

    def expire(self, authority_id: uuid.UUID, *, limit: int = 1000) -> int:
        """Release every workspace's attempts admitted and never dispatched in time."""
        document = self._step(
            authority_id,
            "select spending_expire(%s, %s, %s) as document",
            (authority_id, limit),
            witnessed=self._witnessed(authority_id),
        )
        return int(document.get("count", 0))

    def verify_chain(self, authority_id: uuid.UUID) -> dict[str, Any]:
        with self.database.unscoped() as connection:
            row = connection.execute(
                "select spending_verify_chain(%s) as document", (authority_id,)
            ).fetchone()
        assert row is not None
        return dict(row["document"])

    def install_witness_copy(self, authority_id: uuid.UUID, source: Any) -> None:
        if self.witness is None or not hasattr(self.witness, "install_copy"):
            raise SpendingOperationRefused("no witness directory to install a copy into")
        self.witness.install_copy(authority_id, source)


class _Fresh:
    """A witness handle whose next record replaces the old one whole: after a reauthorization the
    ledger is the only authority left, so nothing of the record it replaces is kept."""

    def __init__(self, held: WitnessHandle) -> None:
        self._held = held

    @property
    def document(self) -> dict[str, Any] | None:
        return self._held.document

    @property
    def record(self) -> dict[str, Any] | None:
        return None

    def write(self, record: Any, *, confirmed: bool) -> None:
        self._held.write(record, confirmed=confirmed)
