"""The durable spending authority: one allowance of money every process shares.

``exulanica.models.budget.BudgetGuard`` is each process's safety fuse, in its memory, started again
at every restart. This package is the allowance that survives both: an operator-issued authority
for each provider, grants an operator gives workspaces under it, and bounds one piece of work opens
under a grant, kept in the database (migration 0124) and admitted, dispatched and settled attempt
by attempt through the functions that migration grants the runtime. A witness outside the
database's backup domain keeps a restored database from handing spent allowance back.

The model client knows none of this: it asks through :mod:`exulanica.models.spending`, whose
source and gate this package implements (:class:`DurableSpending`, :class:`WorkspaceSpending`).
Compositions build one with :func:`durable_spending_from_env`; operators decide with
:class:`SpendingOperator` or ``python -m exulanica.spending``. ``docs/model-spending-contract.md``
is the contract.
"""

from __future__ import annotations

from exulanica.spending.config import (
    DURABLE,
    PROCESS,
    SPENDING_ENV,
    WITNESS_DIR_ENV,
    SpendingConfigurationError,
    durable_spending_from_env,
    spending_mode,
)
from exulanica.spending.ledger import (
    DurableSpending,
    SettlementNotRecorded,
    WorkspaceSpending,
    holder_label,
)
from exulanica.spending.operator import SpendingOperationRefused, SpendingOperator
from exulanica.spending.status import workspace_status
from exulanica.spending.witness import FileSpendingWitness, WitnessUnavailable

__all__ = [
    "DURABLE",
    "PROCESS",
    "SPENDING_ENV",
    "WITNESS_DIR_ENV",
    "DurableSpending",
    "FileSpendingWitness",
    "SettlementNotRecorded",
    "SpendingConfigurationError",
    "SpendingOperationRefused",
    "SpendingOperator",
    "WitnessUnavailable",
    "WorkspaceSpending",
    "durable_spending_from_env",
    "holder_label",
    "spending_mode",
    "workspace_status",
]
