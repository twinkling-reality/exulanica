"""Why a running instance refuses to start a comparison or to spend on a workspace's behalf.

The refusals :class:`~exulanica.api.services.Services` answers from its own fields: whether the
comparisons started here are played, and where; how much of the process's model budget a comparison
may use; and what the durable spending authority would answer a workspace's next ask. Services
inherits them, so each is read as ``services.comparison_refusal(...)`` as before. The refusals that
judge a model against the manifest stay in :mod:`exulanica.api.services` beside the manifest they
read.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from decimal import Decimal
from typing import Final

import psycopg

from exulanica.api.comparison_spending import bound_room_refusal
from exulanica.api.decision_host import share_kept
from exulanica.api.installation import installation_facts
from exulanica.models.client import PROVIDER_CREDENTIAL_ABSENT
from exulanica.models.spending import SpendingRefused
from exulanica.spending.status import SpendingRefusals, read_spending_refusals
from exulanica.world.decision_roles import DecisionRole

#: The states of the installation's ``comparison`` component, as its facts state it, in which a
#: process that leaves its comparisons to another refuses every start (``comparisons_not_played``):
#: the installation's profile declares that process not installed, or unavailable here.
_COMPARISON_PROCESS_ABSENT: Final = frozenset({"not_installed", "unavailable"})
#: How the facts of a process with no profile state a component it cannot see: never a reason to
#: refuse, since that process cannot tell whether another one runs it.
_UNDECLARED: Final = "undeclared_installation"


class ServiceRefusals:
    """The refusals above, mixed into :class:`~exulanica.api.services.Services`, whose fields they
    read."""

    __slots__ = ()

    def signal_comparison_refusal(self, workspace_id: uuid.UUID) -> str | None:
        """Why this server starts no signal comparison for a workspace, or None when it may: the
        same host facts a comparison of people is refused by, its seeds the signal catalog's."""
        if not (self.runs_comparison_worker or self.comparisons_played_elsewhere):
            return "comparisons_not_played"
        if not self.asks_models_for(workspace_id):
            return "comparisons_not_run_here"
        if self.model_client is None:
            return PROVIDER_CREDENTIAL_ABSENT
        if self.comparison_process_absent():
            return "comparisons_not_played"
        return None

    def comparison_refusal(self, workspace_id: uuid.UUID) -> str | None:
        """Why this server starts no comparison for a workspace, or None when it may: its seed
        catalog commits no development seed's text (``comparisons_not_set_up``), nothing plays the
        comparisons started here (``comparisons_not_played``), it asks no model for the workspace
        (``comparisons_not_run_here``, :meth:`asks_models_for`), it has no model client, or it
        leaves them to another process the installation does not run
        (:meth:`comparison_process_absent`), which nothing plays either
        (``comparisons_not_played``)."""
        if not self.comparison_seeds:
            return "comparisons_not_set_up"
        if not (self.runs_comparison_worker or self.comparisons_played_elsewhere):
            return "comparisons_not_played"
        if not self.asks_models_for(workspace_id):
            return "comparisons_not_run_here"
        if self.model_client is None:
            return PROVIDER_CREDENTIAL_ABSENT
        if self.comparison_process_absent():
            return "comparisons_not_played"
        return None

    def comparison_process_absent(self) -> bool:
        """Whether this process leaves its comparisons to another one (``process`` in
        :data:`COMPARISON_WORKER_ENV`) that the installation's profile declares not installed or
        unavailable, read from the installation's facts as a capability read reads them
        (:func:`~exulanica.api.installation.installation_facts`): a start would wait for a process
        the installation does not run. Never where this process plays them itself, whatever its
        profile declares, nor in a process composed with no installation, nor where a process with
        no profile cannot see the component."""
        if self.runs_comparison_worker or not self.comparisons_played_elsewhere:
            return False
        if self.installation is None:
            return False
        component = next(
            (
                entry
                for entry in installation_facts(self)["components"]
                if entry["component"] == "comparison"
            ),
            None,
        )
        return (
            component is not None
            and component["state"] in _COMPARISON_PROCESS_ABSENT
            and component.get("reason") != _UNDECLARED
        )

    def comparison_room(self, role: DecisionRole) -> Decimal | None:
        """What this process's model budget has left for a comparison it plays itself, beside
        the share ``role``'s contract keeps for other work; None where another process plays them,
        whose budget this one cannot see."""
        if not self.runs_comparison_worker or self.model_client is None:
            return None
        budget = self.model_client.budget
        keep_usd, _keep_calls = share_kept(budget, role.contract())
        return budget.ceiling_usd - budget.spent_usd - keep_usd

    def comparison_call_room(self, role: DecisionRole) -> int | None:
        """How many calls this process's model budget has left for a comparison it plays itself,
        beside the calls ``role``'s contract keeps for other work; None where another process
        plays them. A comparison can stop at this as it stops at its bound, whatever it spent."""
        if not self.runs_comparison_worker or self.model_client is None:
            return None
        budget = self.model_client.budget
        _keep_usd, keep_calls = share_kept(budget, role.contract())
        return budget.max_calls - budget.billed_calls - keep_calls

    def provider_refusal(self, provider: str) -> str | None:
        """Why this process asks no model a provider serves, or None when it may ask them."""
        client = self.decision_client
        if client is None:
            return PROVIDER_CREDENTIAL_ABSENT
        return client.refusals.get(provider)

    def spending_refusals(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID
    ) -> SpendingRefusals | None:
        """What the durable spending authority would answer a workspace's next attempt, by
        provider, from one read of the workspace's own spending on ``connection``
        (:func:`~exulanica.spending.status.admission_refusal`); None in a process no durable
        authority admits, which spends within its fuse alone (:meth:`model_host_refusal`).

        A provider's refusal is every ask's of a model it serves: an ask goes to its chosen
        model's provider alone (``ModelClient.choose`` walks one model with no fallback), and
        ``ModelChain.walk`` falls back only on ``ModelUnavailableError``, never on a refusal.
        """
        if self.spending is None:
            return None
        return read_spending_refusals(
            connection, workspace_id, witness_configured=self.spending.witness is not None
        )

    def allowance_refusal(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, providers: Iterable[str]
    ) -> SpendingRefused | None:
        """The refusal admission would give the first ask of the first of ``providers`` whose
        allowance is spent (:meth:`spending_refusals`), or None while each has allowance left, or
        in a process no durable authority admits. A plan states it and a start raises it, so the
        two never differ."""
        refusals = self.spending_refusals(connection, workspace_id)
        return None if refusals is None else refusals.first(providers)

    def require_allowance(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, providers: Iterable[str]
    ) -> None:
        """Raise :meth:`allowance_refusal`'s refusal, before anything is written; return while
        each of ``providers`` has allowance left, or in a process no durable authority admits."""
        refused = self.allowance_refusal(connection, workspace_id, providers)
        if refused is not None:
            raise refused

    def bound_room_refusal(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        providers: Iterable[str],
        *,
        usd: Decimal | None,
        calls: int,
    ) -> tuple[str, str] | None:
        """``bound_exceeds_grant`` and why, where a comparison's bound ``usd`` or the ``calls`` it
        can make are more than the live grant of one of ``providers`` has left
        (:func:`~exulanica.api.comparison_spending.bound_room_refusal`); None while each grant
        holds both, or in a process no durable authority admits, where no bound is opened. A plan
        states it and a start is refused by it, after the allowance."""
        if self.spending is None:
            return None
        return bound_room_refusal(connection, workspace_id, providers, usd=usd, calls=calls)
