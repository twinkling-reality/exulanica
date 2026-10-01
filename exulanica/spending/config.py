"""How a process is told to spend: durably, or within its own safety fuse alone.

``EXULANICA_SPENDING`` states it, and a process that holds a provider's credential must state it:

*   ``durable``: every hosted call is admitted by the durable spending authority, as well as by
    the process's fuse. ``EXULANICA_SPENDING_WITNESS_DIR`` names the directory of the authorities'
    witnesses, shared by every process of the installation on its host and kept outside the
    database's backup domain. A process without it refuses to spend under any witnessed authority.
*   ``process``: the process spends within ``EXULANICA_BUDGET_USD`` and
    ``EXULANICA_BUDGET_MAX_CALLS`` alone, as every process did before the durable authority. A
    restart, or a second process, starts that fuse again at zero; readiness says so.

Neither is a default. A process holding a credential with neither refuses to start, because
choosing one for it would either spend with no authority or refuse a deployment that meant to.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final, Literal

from exulanica.db.session import Database
from exulanica.env import env_get, env_name
from exulanica.errors import ExulanicaError
from exulanica.spending.ledger import DurableSpending, holder_label
from exulanica.spending.witness import FileSpendingWitness

__all__ = [
    "DURABLE",
    "PROCESS",
    "SPENDING_ENV",
    "WITNESS_DIR_ENV",
    "SpendingConfigurationError",
    "durable_spending_from_env",
    "spending_mode",
]

SPENDING_ENV: Final = env_name("SPENDING")
WITNESS_DIR_ENV: Final = env_name("SPENDING_WITNESS_DIR")
DURABLE: Final = "durable"
PROCESS: Final = "process"

SpendingMode = Literal["durable", "process"]


class SpendingConfigurationError(ExulanicaError, ValueError):
    """The environment does not say how this process spends, or says it wrongly."""


def spending_mode(
    environ: Mapping[str, str], *, credentials_configured: bool
) -> SpendingMode | None:
    """``durable`` or ``process`` as the environment states it; None where it states neither and
    no credential is configured, which is the no-model mode."""
    raw = env_get("SPENDING", environ)
    if raw is None:
        if credentials_configured:
            raise SpendingConfigurationError(
                f"a provider credential is configured and {SPENDING_ENV} is not set. Set it to "
                f"{DURABLE} to admit every hosted call by the durable spending authority, or to "
                f"{PROCESS} to spend within this process's budget alone, which a restart and "
                "every other process start again at zero."
            )
        return None
    value = raw.strip().lower()
    if value == DURABLE:
        return DURABLE
    if value == PROCESS:
        return PROCESS
    raise SpendingConfigurationError(f"{SPENDING_ENV} is {DURABLE} or {PROCESS}, not {raw!r}")


def durable_spending_from_env(
    environ: Mapping[str, str], database: Database, *, label: str
) -> DurableSpending:
    """This process's durable spending: its database, its witness directory where one is
    configured, and a holder name made from ``label`` (``api``, ``worker``)."""
    directory = env_get("SPENDING_WITNESS_DIR", environ)
    witness = FileSpendingWitness(Path(directory)) if directory else None
    return DurableSpending(database, witness, holder=holder_label(label))
