"""Comparisons started from the application, claimed and played by a host off the request path.

The start route records a comparison's start (:mod:`exulanica.world.society_comparison_start_
repository`); this worker plays it, by the claim-and-lease pattern the playback worker plays a
society by (:mod:`exulanica.api.society_control_worker`), and by no queue of its own. For each
workspace its host asks models for, it claims the oldest unfinished start whose lease is free or
has run out, and plays the start's runs without an outcome through the comparison's runner
(:meth:`~exulanica.api.society_comparison_runner.SocietyComparisonRunner.run_all`), the anchors
first, with no connection held while a model is asked, renewing its lease before each run and after
each minute. Where it runs is configuration (``EXULANICA_COMPARISON_WORKER``): absent, the API's
lifespan starts it in a thread; ``process``, ``python -m exulanica.orchestration.comparison_worker``
runs the same worker in a process of its own and the API only serves starts; off, nothing plays
them and the API refuses every start (``comparisons_not_played``).

What a claim plays under is the bound its owner stated, less what the comparison's receipts say it
spent, less what claims that took the start over presumed spent and unrecorded. A host whose lease
ran out may have been asking a minute of each run it played, the protocol's ``runs_at_once`` at a
time, and may never record them, whether it was killed or stalled until another host took over:
a claim that takes over a lease that ran out presumes the most one minute can cost for each of as
many open runs, and keeps it on the start, so every later claim deducts it too. That is a part of
this process's model budget (:class:`~exulanica.models.budget.BoundedBudget`) every call of the
comparison is reserved against, and a claim plays it only when it fits what is left of the
process's budget, beside the share the decision contract keeps for other work where this process
does any.

What closes a start, by name: every run given an outcome finishes it. A host that stops part way
leaves its lease to run out and at most ``runs_at_once`` runs with receipts and no outcome; the
next claim records each as failed ``interrupted`` (the runner's rule) and plays the rest. A claim
past ``MAX_CLAIM_ATTEMPTS`` claims in a row that finished no run closes the start instead
(``claims_spent``): runs with receipts fail ``interrupted``, the rest ``comparison_stopped``. The
count is set back in the transaction that records a run's outcome, so a host that finished runs
before it stopped, released its lease or was killed, never counts as one that finished none. A
claim whose bound is spent, or does not fit the process's budget, closes the start with every open
run failed by that name (``comparison_bound_spent``, ``process_budget_spent``), asking nothing.

Between seeds, a claim stops rather than start runs the bound cannot finish. Every ask is held at
its model's most until its usage is recorded, so a bound near what a comparison typically spends
would otherwise stop runs part way and keep nothing of them. Before a seed's model runs start, the
claim admits them only while what is left of the bound holds what runs like them typically cost on
this society's ground and what they can hold reserved at once (``suggested_usd``); otherwise it
closes that seed's and every later seed's model runs as ``comparison_bound_before_seed``, asking
nothing, and closes the start by that name, keeping every seed already played. A seed with no
measured figure is admitted, and its asks stay held to the bound one by one. The bound itself is
unchanged: no ask is ever admitted past it.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import uuid
from collections.abc import Callable, Iterable, Sequence
from decimal import ROUND_CEILING, Decimal
from typing import Final

import psycopg

from exulanica.api.decision_host import share_kept
from exulanica.api.society_comparison_runner import (
    BOUND_BEFORE_SEED,
    BOUND_SPENT,
    ClaimLost,
    HostStopping,
    RunHost,
    SocietyComparisonRunner,
)
from exulanica.api.society_comparison_start import comparison_cost
from exulanica.db.session import Database
from exulanica.models.budget import BoundedBudget, BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Manifest
from exulanica.models.usage import USD_QUANTUM
from exulanica.world.society_comparison_result import definition_role
from exulanica.world.society_comparison_start_repository import (
    ComparisonClaim,
    SocietyComparisonStarts,
)
from exulanica.world.society_comparison_verdict import protocol_value

__all__ = ["CLOSED_REASONS", "SocietyComparisonWorker"]

_LOG = logging.getLogger(__name__)
#: Why a host closed a start before every run was played, by name: hosts that claimed it kept
#: stopping, what was left of its bound did not hold the next seed's typical cost and what its runs
#: can hold reserved, so it stopped between seeds, its bound was spent, or this process's model
#: budget could not hold what was left of it. The page has words for each.
CLOSED_REASONS: Final = (
    "claims_spent",
    "comparison_bound_before_seed",
    "comparison_bound_spent",
    "process_budget_spent",
)
#: How a run a closed start left open fails: one that asked something was stopped part way;
#: one that asked nothing was never played.
_STOPPED_PART_WAY = "interrupted"
_NEVER_PLAYED = "comparison_stopped"
#: What prices a model's asks where this process has no client to ask with: estimating reads the
#: manifest's prices, never a ceiling.
_ESTIMATOR = BudgetGuard(ceiling_usd=Decimal(0), max_calls=0)


class SocietyComparisonWorker:
    """Claims and plays comparisons started from the application, one at a time."""

    def __init__(
        self,
        database: Database,
        *,
        runner_for: Callable[[uuid.UUID, str, uuid.UUID], SocietyComparisonRunner | None],
        client: ModelClient | None,
        manifest: Manifest,
        workspaces: Iterable[uuid.UUID],
        keeps_share: bool,
    ) -> None:
        self.database = database
        #: The runner of a workspace and world, as the actor who started the comparison.
        self.runner_for = runner_for
        self.client = client
        self.manifest = manifest
        self.workspaces = tuple(sorted(frozenset(workspaces), key=str))
        #: Whether its asks leave the contract's share of this process's budget for other work:
        #: in the API's process, which serves the Companion and the live world too; not in a
        #: process of its own, which does nothing else.
        self.keeps_share = keeps_share

    def run(self, stop: threading.Event, *, poll_seconds: float = 1.0) -> None:
        """Play the workspaces' starts until ``stop`` is set; wait ``poll_seconds`` between
        rounds in which nothing was claimed."""
        while not stop.is_set():
            played = False
            for workspace in self.workspaces:
                if stop.is_set():
                    break
                try:
                    played = self.run_once(workspace, stop) or played
                except Exception as exc:
                    # Its lease runs out and a later claim takes it over. Never the exception's
                    # text, which may carry request bytes or a credential.
                    _LOG.error("A comparison claim failed with %s", type(exc).__qualname__)
            if not played:
                stop.wait(poll_seconds)

    def run_once(self, workspace: uuid.UUID, stop: threading.Event | None = None) -> bool:
        """Claim the workspace's oldest unfinished start and play it as far as this host can;
        False when there was none to claim."""
        with self.database.session(workspace) as connection:
            claim = SocietyComparisonStarts(connection, workspace).claim()
        if claim is None:
            return False
        self._play(claim, stop or threading.Event())
        return True

    def _starts(self, claim: ComparisonClaim) -> Callable[..., bool]:
        """Call one of the claim's own changes (``SocietyComparisonStarts`` by name) in a short
        session, and say whether the host still held it."""

        def change(name: str, **kwargs: object) -> bool:
            with self.database.session(claim.workspace_id) as connection:
                starts = SocietyComparisonStarts(connection, claim.workspace_id)
                return bool(getattr(starts, name)(claim, **kwargs))

        return change

    def _play(self, claim: ComparisonClaim, stop: threading.Event) -> None:
        change = self._starts(claim)
        runner = self.runner_for(claim.workspace_id, claim.world_id, claim.requested_by)
        if runner is None:
            _LOG.error("A comparison was claimed where no society runtime is configured")
            return
        with self.database.session(claim.workspace_id) as connection:
            repository = runner._repository(connection)
            definition = repository._definition(claim.comparison_id)["document"]  # type: ignore[index]
            open_runs = repository.open_runs(claim.comparison_id)
            spent = repository.spending([claim.comparison_id]).get(claim.comparison_id, Decimal(0))
        if SocietyComparisonStarts.attempts_spent(claim):
            self._close(runner, claim, open_runs, "claims_spent", change)
            return
        role = definition_role(definition)
        budget = None if self.client is None else self.client.budget
        cost = comparison_cost(
            definition,
            int(definition["population"]),
            role,
            budget if budget is not None else _ESTIMATOR,
            self.manifest,
            at_once=protocol_value(runner.catalogs, "runs_at_once"),
            navigation_profile=None,
            runs_left=[(run["arm"], run["seed_digest"]) for run in open_runs],
        )
        presumed = claim.presumed_usd
        if claim.took_over and open_runs:
            # The host whose lease ran out may have been asking a minute of each run it played,
            # the protocol's number at a time, and may never record them.
            in_flight = min(protocol_value(runner.catalogs, "runs_at_once"), len(open_runs))
            more = (in_flight * cost.minute_usd).quantize(USD_QUANTUM, rounding=ROUND_CEILING)
            if more > 0:
                if not change("presume", usd=more):
                    return
                presumed += more
        ceiling = claim.bound_usd - spent - presumed
        if ceiling <= 0:
            self._close(runner, claim, open_runs, BOUND_SPENT, change)
            return
        bound = None
        if budget is not None:
            keep_usd, keep_calls = (
                share_kept(budget, role.contract()) if self.keeps_share else (Decimal(0), 0)
            )
            if budget.ceiling_usd - budget.spent_usd - keep_usd < min(ceiling, cost.most_usd) or (
                budget.max_calls - budget.billed_calls - keep_calls < 1
            ):
                self._close(runner, claim, open_runs, "process_budget_spent", change)
                return
            bound = BoundedBudget(budget, ceiling_usd=ceiling, max_calls=max(1, cost.calls))
        played = dataclasses.replace(runner, bound=bound, keeps_share=self.keeps_share)

        def minute() -> None:
            if not change("renew"):
                raise ClaimLost

        def recorded(connection: psycopg.Connection) -> None:
            SocietyComparisonStarts.ran(
                connection, claim.workspace_id, claim.world_id, claim.comparison_id
            )

        with self.database.session(claim.workspace_id) as connection:
            repository = runner._repository(connection)
            society = repository.society._row(uuid.UUID(definition["version_id"]))
            navigation = None if society is None else repository.navigation_profile(society)

        def admit(runs: Sequence[uuid.UUID]) -> bool:
            """Whether what is left of the bound holds what one seed's model runs like these
            typically cost and what they can hold reserved at once: the least that lets them
            finish (``suggested_usd``), from the typical figures of this society's ground. A seed
            with no typical figure is admitted, and its asks stay held to the bound one by one."""
            with self.database.session(claim.workspace_id) as connection:
                repository = runner._repository(connection)
                left_runs = [repository._run(run_id) for run_id in runs]
                spent_now = repository.spending([claim.comparison_id]).get(
                    claim.comparison_id, Decimal(0)
                )
            seed = comparison_cost(
                definition,
                int(definition["population"]),
                role,
                budget if budget is not None else _ESTIMATOR,
                self.manifest,
                at_once=protocol_value(runner.catalogs, "runs_at_once"),
                navigation_profile=navigation,
                runs_left=[(row["arm"], row["seed_digest"]) for row in left_runs],
            )
            needed = seed.suggested_usd
            return needed is None or claim.bound_usd - spent_now - presumed >= needed

        host = RunHost(minute=minute, stopping=stop.is_set, recorded=recorded, admit=admit)
        order = [run["run_id"] for run in open_runs]
        try:
            outcomes = played.run_all(claim.comparison_id, order, host=host)
        except HostStopping:
            change("release")
            return
        except ClaimLost:
            return
        with self.database.session(claim.workspace_id) as connection:
            left = runner._repository(connection).open_runs(claim.comparison_id)
        if not left:
            stopped = any(
                outcome.get("code") == BOUND_BEFORE_SEED for outcome in outcomes if outcome
            )
            change("finish", closed_reason=BOUND_BEFORE_SEED if stopped else None)
            # Once the start is finished, with no lease held, each completed run is drawn for its
            # reads (the runner's ``draw``): a town's drawing takes seconds a lease is not held for.
            runner.draw_all(claim.comparison_id, order)

    def _close(
        self,
        runner: SocietyComparisonRunner,
        claim: ComparisonClaim,
        open_runs: list[dict],
        reason: str,
        change: Callable[..., bool],
    ) -> None:
        """Close the start by ``reason``: every run left open fails, one that asked something as
        ``interrupted`` and any other by ``reason``, or ``comparison_stopped`` where hosts kept
        stopping; then the start is finished."""
        never_played = _NEVER_PLAYED if reason == "claims_spent" else reason
        runner.fail_open(
            claim.comparison_id,
            {
                run["run_id"]: _STOPPED_PART_WAY if run["asked"] else never_played
                for run in open_runs
            },
        )
        change("finish", closed_reason=reason)
