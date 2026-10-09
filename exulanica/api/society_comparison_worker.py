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

Where a durable spending authority admits this host's calls, the bound is held at the authority as
well (:mod:`exulanica.api.comparison_spending`): before a claim's first ask it opens a bound for
each provider the comparison asks, under the workspace's grant, with the bound and the calls the
start recorded, or finds the one a host before it opened, and every ask of its runs is admitted
under its provider's bound. What every host that played the start committed never passes it, a
presumption that fell short included. A run the authority refuses by that bound fails as
``comparison_bound_spent`` where the bound is committed, as ``comparison_cancelled`` where its
owner cancelled the comparison (the cancel closes the bounds), and by the authority's own reason
otherwise; a provider whose bound the authority refused to open fails its asks by that refusal,
before anything is sent. Every bound is closed once the start is finished, whatever finished it.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any, Final

import psycopg

from exulanica.api.comparison_spending import (
    ComparisonBounds,
    close_comparison_bounds,
    open_comparison_bounds,
)
from exulanica.api.decision_host import share_kept
from exulanica.api.signal_comparison_runner import SignalComparisonRunner
from exulanica.api.signal_comparison_start import (
    signal_comparison_cost,
    stopped_signal_host_usd,
)
from exulanica.api.society_comparison_runner import (
    BOUND_BEFORE_SEED,
    BOUND_SPENT,
    CANCELLED,
    ClaimLost,
    HostStopping,
    RunHost,
    SocietyComparisonRunner,
)
from exulanica.api.society_comparison_start import (
    asked_providers,
    comparison_cost,
    stopped_host_usd,
)
from exulanica.db.session import Database
from exulanica.models.budget import BoundedBudget, BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Manifest
from exulanica.spending import DurableSpending
from exulanica.world.comparison_facts import ComparisonFacts
from exulanica.world.society_comparison_result import definition_role, run_population
from exulanica.world.society_comparison_start_repository import (
    ComparisonClaim,
    SocietyComparisonStarts,
)
from exulanica.world.society_comparison_verdict import protocol_value
from exulanica.world.society_engines import society_engine

__all__ = ["CANCELLED_REASON", "CLOSED_REASONS", "SocietyComparisonWorker"]

_LOG = logging.getLogger(__name__)

#: How often a worker with a workspace source reads it again, in seconds.
SOURCE_READ_SECONDS = 5.0

#: How often a worker with a slow source also visits every workspace it names, in seconds. Each
#: visit opens two sessions, so the account workspaces a server has ever admitted are visited this
#: rarely: a start is made only in a watched workspace, and the slow scan finds those whose
#: visitor left before the start was claimed, or while a claim lapsed.
SLOW_SCAN_SECONDS = 300.0

#: Why a host closed a start before every run was played, by name: hosts that claimed it kept
#: stopping, what was left of its bound did not hold the next seed's typical cost and what its runs
#: can hold reserved, so it stopped between seeds, its bound was spent, or this process's model
#: budget could not hold what was left of it. The page has words for each.
CLOSED_REASONS: Final = (
    "claims_spent",
    "comparison_bound_before_seed",
    "comparison_bound_spent",
    "comparison_cancelled",
    "process_budget_spent",
)
#: Why a start was closed when whoever may start one cancelled it, the code its open runs fail by
#: too, whether or not they asked.
CANCELLED_REASON: Final = CANCELLED
#: Why a start's durable bounds are closed when every run was played, as the authority records it.
_FINISHED: Final = "comparison_finished"
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
        signal_runner_for: Callable[[uuid.UUID, str, uuid.UUID], SignalComparisonRunner]
        | None = None,
        workspace_source: Callable[[], Iterable[uuid.UUID]] | None = None,
        slow_source: Callable[[], Iterable[uuid.UUID]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.database = database
        #: The runner of a workspace and world, as the actor who started the comparison.
        self.runner_for = runner_for
        #: The runner of a signal comparison, for a host that plays those too: the same claim,
        #: lease and closing rules, over migration 0132's start.
        self.signal_runner_for = signal_runner_for
        self.client = client
        self.manifest = manifest
        self.workspaces = tuple(sorted(frozenset(workspaces), key=str))
        #: Account discovery's watched workspaces, played every round beside the listed ones
        #: (where a host asks models for discovered workspaces under durable spending); read at
        #: most every :data:`SOURCE_READ_SECONDS`, and a failed read keeps the last one.
        self._workspace_source = workspace_source
        #: Every account workspace, visited once every :data:`SLOW_SCAN_SECONDS`: a comparison a
        #: visitor started finishes after they leave, within its own bound and their grant.
        self._slow_source = slow_source
        self._clock = clock
        self._sourced: tuple[float, tuple[uuid.UUID, ...]] | None = None
        self._scanned_at: float | None = None
        #: Whether its asks leave the contract's share of this process's budget for other work:
        #: in the API's process, which serves the Companion and the live world too; not in a
        #: process of its own, which does nothing else.
        self.keeps_share = keeps_share

    def played_workspaces(self) -> tuple[uuid.UUID, ...]:
        """This round's workspaces: the listed ones, the watched ones the source last named, and,
        once every :data:`SLOW_SCAN_SECONDS`, every one the slow source names."""
        played = frozenset(self.workspaces)
        now = self._clock()
        if self._workspace_source is not None:
            if self._sourced is None or now - self._sourced[0] >= SOURCE_READ_SECONDS:
                found = self._read(self._workspace_source)
                if found is None:
                    found = () if self._sourced is None else self._sourced[1]
                self._sourced = (now, found)
            played |= frozenset(self._sourced[1])
        if self._slow_source is not None and (
            self._scanned_at is None or now - self._scanned_at >= SLOW_SCAN_SECONDS
        ):
            # A failed scan waits for the next one rather than asking again every round.
            self._scanned_at = now
            played |= frozenset(self._read(self._slow_source) or ())
        return tuple(sorted(played, key=str))

    @staticmethod
    def _read(source: Callable[[], Iterable[uuid.UUID]]) -> tuple[uuid.UUID, ...] | None:
        try:
            return tuple(source())
        except Exception as exc:
            # Never the exception's text, which may carry a connection string.
            _LOG.error("Comparison workspaces could not be read: %s", type(exc).__qualname__)
            return None

    def run(self, stop: threading.Event, *, poll_seconds: float = 1.0) -> None:
        """Play the workspaces' starts until ``stop`` is set; wait ``poll_seconds`` between
        rounds in which nothing was claimed."""
        while not stop.is_set():
            played = False
            for workspace in self.played_workspaces():
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
        """Claim the workspace's oldest unfinished start, of a comparison of people's deciders
        and then of a town's signals, and play it as far as this host can; False when there was
        none to claim."""
        with self.database.session(workspace) as connection:
            claim = SocietyComparisonStarts(connection, workspace).claim()
        if claim is not None:
            self._play(claim, stop or threading.Event())
            return True
        if self.signal_runner_for is None:
            return False
        with self.database.session(workspace) as connection:
            claim = SocietyComparisonStarts(connection, workspace, "signal").claim()
        if claim is None:
            return False
        self._play_signals(claim, stop or threading.Event())
        return True

    def _starts(self, claim: ComparisonClaim) -> Callable[..., bool]:
        """Call one of the claim's own changes (``SocietyComparisonStarts`` by name) in a short
        session, and say whether the host still held it."""

        def change(name: str, **kwargs: object) -> bool:
            with self.database.session(claim.workspace_id) as connection:
                starts = SocietyComparisonStarts(connection, claim.workspace_id, claim.kind)
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
        cancelled = self._cancelled(claim)
        if not cancelled and SocietyComparisonStarts.attempts_spent(claim):
            self._close(runner, claim, open_runs, "claims_spent", change)
            return
        role = definition_role(definition)
        budget = None if self.client is None else self.client.budget
        cost = comparison_cost(
            definition,
            run_population(definition),
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
            more = stopped_host_usd(definition, runner.catalogs, budget, self.manifest, open_runs)
            if more > 0:
                if not change("presume", usd=more):
                    return
                presumed += more
        if cancelled:
            # Cancelled while no host played it, or by a host that stopped before closing it:
            # what that host may have spent is presumed above, and nothing is asked.
            self._close(runner, claim, open_runs, CANCELLED_REASON, change)
            return
        ceiling = claim.bound_usd - spent - presumed
        if ceiling <= 0:
            self._close(runner, claim, open_runs, BOUND_SPENT, change)
            return
        bound = None
        keep_usd, keep_calls = (
            share_kept(budget, role.contract(definition["contract"]["catalog_versions"]))
            if budget is not None and self.keeps_share
            else (Decimal(0), 0)
        )
        if budget is not None:
            if budget.ceiling_usd - budget.spent_usd - keep_usd < min(ceiling, cost.most_usd) or (
                budget.max_calls - budget.billed_calls - keep_calls < 1
            ):
                self._close(runner, claim, open_runs, "process_budget_spent", change)
                return
            bound = BoundedBudget(budget, ceiling_usd=ceiling, max_calls=max(1, cost.calls))
        played = dataclasses.replace(
            runner,
            bound=bound,
            keeps_share=self.keeps_share,
            spending_bounds=self._bounds(claim, asked_providers(definition)),
        )

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
        family = None if society is None else society_engine(society["engine_version"]).state_family

        def admit(runs: Sequence[uuid.UUID]) -> bool:
            """Whether what is left of the bound, and of this process's calls, holds one seed's
            runs like these: the least that lets them finish (``suggested_usd``) from the
            typical figures of this society's ground, or, where that ground has none for a
            model, the dearest any ground has; where no ground has one, what the runs can hold
            reserved at once (``held_usd``), which is logged. The calls are the most the runs can
            make, since a process that runs out of calls stops them whatever they spent."""
            with self.database.session(claim.workspace_id) as connection:
                repository = runner._repository(connection)
                left_runs = [repository._run(run_id) for run_id in runs]
                spent_now = repository.spending([claim.comparison_id]).get(
                    claim.comparison_id, Decimal(0)
                )
            seed = comparison_cost(
                definition,
                run_population(definition),
                role,
                budget if budget is not None else _ESTIMATOR,
                self.manifest,
                at_once=protocol_value(runner.catalogs, "runs_at_once"),
                navigation_profile=navigation,
                runs_left=[(row["arm"], row["seed_digest"]) for row in left_runs],
                dearest_elsewhere=True,
                family=family,
            )
            needed = seed.suggested_usd
            if needed is None:
                _LOG.warning(
                    "No typical figure covers a comparison's models; a seed is admitted only "
                    "while its bound holds what its runs can hold reserved"
                )
                needed = seed.held_usd
            money = claim.bound_usd - spent_now - presumed >= needed
            calls = budget is None or (
                budget.max_calls - budget.billed_calls - keep_calls >= seed.calls
            )
            return money and calls

        def fence(connection: psycopg.Connection) -> None:
            """Every write of a day's run is made while this host holds the start: one another
            claim took over writes nothing more."""
            if not SocietyComparisonStarts(connection, claim.workspace_id, claim.kind).holds(claim):
                raise ClaimLost

        host = RunHost(
            minute=minute,
            stopping=stop.is_set,
            recorded=recorded,
            admit=admit,
            cancelled=lambda: self._cancelled(claim),
            started=lambda run_id: self._started(claim, run_id),
            fence=fence,
        )
        order = [run["run_id"] for run in open_runs]
        try:
            played.run_all(claim.comparison_id, order, host=host)
        except HostStopping:
            change("release")
            return
        except ClaimLost:
            return
        if self._cancelled(claim):
            # Cancelled while this host played it: what it did not play closes asking nothing.
            with self.database.session(claim.workspace_id) as connection:
                left = runner._repository(connection).open_runs(claim.comparison_id)
            self._close(runner, claim, left, CANCELLED_REASON, change)
            return
        with self.database.session(claim.workspace_id) as connection:
            repository = runner._repository(connection)
            left = repository.open_runs(claim.comparison_id)
            # Why it stopped, from the outcomes stored, whichever claim recorded them.
            stopped = any(
                (run.get("outcome") or {}).get("code") == BOUND_BEFORE_SEED
                for run in repository.runs(claim.comparison_id)
            )
        if not left:
            closed_reason = BOUND_BEFORE_SEED if stopped else None
            if change("finish", closed_reason=closed_reason):
                self._close_bounds(claim, closed_reason)
            # Once the start is finished, with no lease held, each completed run not drawn yet
            # is drawn for its reads, whichever claim played it (the runner's ``draw_all``).
            runner.draw_all(claim.comparison_id, stopping=stop.is_set)

    def _cancelled(self, claim: ComparisonClaim) -> bool:
        """Whether the claimed comparison was cancelled, read in a short session of its own."""
        with self.database.session(claim.workspace_id) as connection:
            facts = ComparisonFacts(connection, claim.workspace_id, claim.world_id, claim.kind)
            return facts.cancellation(claim.comparison_id) is not None

    def _started(self, claim: ComparisonClaim, run_id: uuid.UUID) -> None:
        """Record that this host starts playing a run under its claim's lease."""
        with self.database.session(claim.workspace_id) as connection, connection.transaction():
            ComparisonFacts(connection, claim.workspace_id, claim.world_id, claim.kind).run_started(
                claim.comparison_id, run_id, claim.token
            )

    def _play_signals(self, claim: ComparisonClaim, stop: threading.Event) -> None:
        """Play a signal comparison's start under the same claim rules a society comparison's
        start is played by: claims that finish nothing, a takeover's presumed spend, a
        cancellation, the bound and this process's budget each close it by name, asking
        nothing; its runs are played one after another, each seed's fixed-timing anchor first."""
        assert self.signal_runner_for is not None
        change = self._starts(claim)
        runner = self.signal_runner_for(claim.workspace_id, claim.world_id, claim.requested_by)
        with self.database.session(claim.workspace_id) as connection:
            repository = runner._repository(connection)
            definition = repository._definition(claim.comparison_id)["document"]  # type: ignore[index]
            open_runs = repository.open_runs(claim.comparison_id)
            spent = repository.spending([claim.comparison_id]).get(claim.comparison_id, Decimal(0))
        cancelled = self._cancelled(claim)
        if not cancelled and SocietyComparisonStarts.attempts_spent(claim):
            self._close(runner, claim, open_runs, "claims_spent", change)
            return
        budget = None if self.client is None else self.client.budget
        cost = signal_comparison_cost(
            definition,
            len(definition["group"]),
            runner.role,
            budget if budget is not None else _ESTIMATOR,
            self.manifest,
            runs_left=[(run["arm"], run["seed_digest"]) for run in open_runs],
        )
        presumed = claim.presumed_usd
        if claim.took_over and open_runs:
            # The host whose lease ran out may have been asking one point and never recorded it.
            more = stopped_signal_host_usd(
                definition,
                runner.role,
                budget if budget is not None else _ESTIMATOR,
                self.manifest,
                open_runs,
            )
            if more > 0:
                if not change("presume", usd=more):
                    return
                presumed += more
        if cancelled:
            self._close(runner, claim, open_runs, CANCELLED_REASON, change)
            return
        ceiling = claim.bound_usd - spent - presumed
        if ceiling <= 0:
            self._close(runner, claim, open_runs, BOUND_SPENT, change)
            return
        bound = None
        keep_usd, keep_calls = (
            share_kept(budget, runner.role.contract())
            if budget is not None and self.keeps_share
            else (Decimal(0), 0)
        )
        if budget is not None:
            if budget.ceiling_usd - budget.spent_usd - keep_usd < min(ceiling, cost.most_usd) or (
                budget.max_calls - budget.billed_calls - keep_calls < 1
            ):
                self._close(runner, claim, open_runs, "process_budget_spent", change)
                return
            bound = BoundedBudget(budget, ceiling_usd=ceiling, max_calls=max(1, cost.calls))
        played = dataclasses.replace(
            runner,
            bound=bound,
            keeps_share=self.keeps_share,
            spending_bounds=self._bounds(claim, asked_providers(definition)),
        )

        def minute() -> None:
            if not change("renew"):
                raise ClaimLost

        def recorded(connection: psycopg.Connection) -> None:
            SocietyComparisonStarts.ran(
                connection, claim.workspace_id, claim.world_id, claim.comparison_id, claim.kind
            )

        host = RunHost(
            minute=minute,
            stopping=stop.is_set,
            recorded=recorded,
            cancelled=lambda: self._cancelled(claim),
            started=lambda run_id: self._started(claim, run_id),
        )
        try:
            played.run_all(claim.comparison_id, [run["run_id"] for run in open_runs], host=host)
        except HostStopping:
            change("release")
            return
        except ClaimLost:
            return
        with self.database.session(claim.workspace_id) as connection:
            left = runner._repository(connection).open_runs(claim.comparison_id)
        if self._cancelled(claim):
            self._close(runner, claim, left, CANCELLED_REASON, change)
            return
        if not left and change("finish", closed_reason=None):
            self._close_bounds(claim, None)

    def _close(
        self,
        runner: SocietyComparisonRunner | SignalComparisonRunner,
        claim: ComparisonClaim,
        open_runs: Sequence[Mapping[str, Any]],
        reason: str,
        change: Callable[..., bool],
    ) -> None:
        """Close the start by ``reason``: every run left open fails, one that asked something as
        ``interrupted`` and any other by ``reason``, or ``comparison_stopped`` where hosts kept
        stopping; a cancelled start's runs all fail as ``comparison_cancelled``, their receipts
        kept. Then the start is finished."""
        if reason == CANCELLED_REASON:
            codes = {run["run_id"]: CANCELLED for run in open_runs}
        else:
            never_played = _NEVER_PLAYED if reason == "claims_spent" else reason
            codes = {
                run["run_id"]: _STOPPED_PART_WAY if run["asked"] else never_played
                for run in open_runs
            }
        runner.fail_open(claim.comparison_id, codes)
        if change("finish", closed_reason=reason):
            self._close_bounds(claim, reason)

    def _spending(self) -> DurableSpending | None:
        """The durable spending authority this host's asks are admitted by, or None where none
        is: its comparisons' bounds are then held in its process alone."""
        source = None if self.client is None else self.client.spending_source
        return source if isinstance(source, DurableSpending) else None

    def _bounds(self, claim: ComparisonClaim, providers: Sequence[str]) -> ComparisonBounds | None:
        """The start's durable bounds the claim plays under, one for each of ``providers``,
        opened or found before its first ask with the bound and calls the start recorded, where
        a durable authority admits this host's calls."""
        spending = self._spending()
        if spending is None:
            return None
        with self.database.session(claim.workspace_id) as connection:
            return open_comparison_bounds(
                spending,
                connection,
                claim.workspace_id,
                claim.comparison_id,
                providers,
                usd=claim.bound_usd,
                calls=claim.bound_calls,
            )

    def _close_bounds(self, claim: ComparisonClaim, closed_reason: str | None) -> None:
        """Close the finished start's durable bounds, so the authority admits nothing more under
        them, on any host; the authority records why, by the start's closing reason where it was
        closed before every run was played."""
        spending = self._spending()
        if spending is None:
            return
        with self.database.session(claim.workspace_id) as connection:
            close_comparison_bounds(
                spending,
                connection,
                claim.workspace_id,
                claim.comparison_id,
                reason=closed_reason or _FINISHED,
            )
