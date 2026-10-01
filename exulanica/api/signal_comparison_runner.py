"""Trusted execution of a signal comparison: every run one episode of a saved town's traffic, its
group of signals decided by the run's arm, the model asked as the live controller asks it.

A signal comparison is defined over a saved world version's roads as they are (:meth:`define`),
every run reserved before anything is asked (:meth:`reserve_all`), and played off the request path
by a host's comparison worker (:mod:`exulanica.api.society_comparison_worker`), the fixed-timing
anchor of each seed before its model runs. A model run probes its episode to each choice point of
the group's signals (:func:`~exulanica.world.signal_comparison.play`), asks the arm's model through
the one hosted call path every role is asked by (:func:`~exulanica.api.decision_host.ask`), with no
database connection held while it asks, and appends the receipt in a transaction of its own before
the episode goes on, so a host that stops never loses an answer it paid for. A choice point the
model answers late, wrongly or not at all is the plan's switch, with its receipt saying why.

What makes a run fail rather than complete is the host, never the model: the comparison's bound or
the process's budget no longer fitting one ask, a provider or credential the process refuses, a
model no longer offered or asked otherwise than the definition recorded, rules that would change
the question, the comparison cancelled, the roads changed or unavailable. The run's outcome names
the code; its receipts stay recorded and counted. A comparison writes nothing the live world
reads: not its traffic, its signal choices or its sealed minutes.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

import psycopg

from exulanica.api.decision_host import (
    RoleAsk,
    ask,
    ask_bound_usd,
    question_refusal,
    share_kept,
)
from exulanica.api.society_comparison_runner import (
    CANCELLED,
    ComparisonArm,
    HostStopping,
    RunHost,
)
from exulanica.api.society_comparison_runner import (
    RUN_FAILURE_CODES as PERSON_RUN_FAILURE_CODES,
)
from exulanica.db.session import Database
from exulanica.models.budget import BoundedBudget
from exulanica.models.client import ModelClient
from exulanica.models.errors import ManifestError
from exulanica.models.manifest import AnsweringMechanism, Manifest, ModelSpec
from exulanica.models.policy import HostedRequestPolicy
from exulanica.traffic.signal_actuation import signal_actuation
from exulanica.world.decision_roles import DecisionRole, decision_roles
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.signal_comparison import (
    OBSERVATION_PROFILE,
    PlayedSignalRun,
    ReplayMismatch,
    SignalRunPlan,
    play,
    replay,
)
from exulanica.world.signal_comparison_repository import (
    DEFINITION_PROFILE,
    SignalComparisonRefused,
    SignalComparisonRepository,
    run_id_for,
)
from exulanica.world.signal_comparison_result import (
    SignalCatalogs,
    check_definition,
    failure_outcome,
    run_outcome,
    signal_catalogs,
)
from exulanica.world.society import seed_digest
from exulanica.world.traffic_episodes import (
    EPISODE,
    TrafficInput,
    TrafficRefused,
    compute_signal_catalog,
    wire,
)

__all__ = [
    "FIXED_ARM",
    "RUN_FAILURE_CODES",
    "ReplayMismatch",
    "SignalComparisonRunner",
]

_LOG = logging.getLogger(__name__)
#: The fixed-timing arm every signal comparison runs, by key: the measure's baseline.
FIXED_ARM: Final = "fixed"
#: Every code a failed signal run's outcome records: the person runner's, the reasons a host ends
#: a run's asking, and two of traffic's own: the roads a comparison recorded are no longer the
#: version's, or no longer readable.
RUN_FAILURE_CODES: Final = frozenset({*PERSON_RUN_FAILURE_CODES, "roads_changed"})
_BOUND_SPENT: Final = "comparison_bound_spent"
_INTERRUPTED: Final = "interrupted"
_INPUT_UNAVAILABLE: Final = "input_unavailable"
_ANCHOR_FAILED: Final = "anchor_failed"
_QUESTION_CHANGED: Final = "question_changed_by_rules"


class _RunStopped(Exception):
    """A run the host cannot go on with, by the name its outcome records."""

    def __init__(self, code: str) -> None:
        if code not in RUN_FAILURE_CODES:
            raise ValueError(f"a run fails only by a stated code, not {code!r}")
        super().__init__(code)
        self.code = code


class _Fixed:
    """The fixed-timing arm asks nobody: its group has no choice point."""

    def answer(self, request: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("a fixed-timing run asks nobody")


class _Asking:
    """A model run's asking, one choice point at a time, as the live controller asks a chosen
    signal's model: the host's room judged on what is spent before each ask, the comparison's
    cancellation read before each dispatch."""

    def __init__(
        self,
        client: ModelClient,
        role: DecisionRole,
        spec: ModelSpec,
        mechanism: AnsweringMechanism,
        *,
        bound: BoundedBudget | None,
        run_bound: BoundedBudget | None,
        keeps_share: bool,
        cancelled: Callable[[], bool],
    ) -> None:
        self.client, self.role, self.spec, self.mechanism = client, role, spec, mechanism
        self.contract = role.contract()
        self.bound, self.run_bound = bound, run_bound
        self.keep = share_kept(client.budget, self.contract) if keeps_share else (Decimal(0), 0)
        self.cancelled = cancelled

    def answer(self, request: dict[str, Any]) -> dict[str, Any]:
        # The last point before an ask is sent: a cancelled comparison sends none.
        if self.cancelled():
            raise _RunStopped(CANCELLED)
        refused = self.client.refusals.get(self.spec.provider)
        if refused is not None:
            raise _RunStopped(refused)
        budget = self.client.budget
        need = ask_bound_usd(self.role, budget, self.spec, self.contract)
        calls = self.contract.value("answer_attempts_maximum")
        keep_usd, keep_calls = self.keep
        left_usd, left_calls = (
            budget.ceiling_usd - budget.spent_usd,
            budget.max_calls - (budget.billed_calls),
        )
        if left_usd < need or left_calls < calls:
            raise _RunStopped("process_budget_spent")
        if left_usd - keep_usd < need or left_calls - keep_calls < calls:
            raise _RunStopped("process_share_spent")
        if self.bound is not None and (
            self.bound.ceiling_usd - self.bound.spent_usd < need
            or self.bound.max_calls - self.bound.billed_calls < calls
        ):
            raise _RunStopped(_BOUND_SPENT)
        ends_at = time.monotonic() + self.contract.value("decision_deadline_ms") / 1000
        try:
            return ask(
                self.client,
                RoleAsk(self.role, request, self.spec, self.mechanism),
                self.contract,
                ends_at,
                keep_usd=keep_usd,
                keep_calls=keep_calls,
            )
        except Exception:
            # An error before anything was sent: an error in an attempt is ask's, which keeps
            # what the attempts cost. Never an exception's text, which may carry request bytes.
            _LOG.error("A signal comparison's ask failed; the plan's switch decides that point")
            return {
                "status": "unavailable",
                "reason": "model_call_failed",
                "proposal": None,
                "provider": None,
            }

    def bound_refused(self) -> bool:
        return self.run_bound is not None and self.run_bound.refusals > 0


@dataclass(frozen=True)
class SignalComparisonRunner:
    """Defines and runs signal comparisons in one workspace and world, as ``actor``."""

    database: Database
    client: ModelClient | None
    policy_for: Callable[[uuid.UUID], HostedRequestPolicy]
    manifest: Manifest
    manifest_sha256: str
    workspace_id: uuid.UUID
    world_id: str
    actor: uuid.UUID
    catalogs: SignalCatalogs = field(default_factory=signal_catalogs)
    role: DecisionRole = field(default_factory=lambda: decision_roles().deciding_for("signal"))
    #: The bound a comparison started from the application runs under, a part of the process's
    #: budget; None where the caller holds no bound.
    bound: BoundedBudget | None = None
    #: Whether its asks leave the contract's share of the process's budget for other work.
    keeps_share: bool = False

    def _repository(self, connection: Any) -> SignalComparisonRepository:
        return SignalComparisonRepository(connection, self.workspace_id, self.world_id)

    # -- definitions -----------------------------------------------------------------------------

    def model_arm(self, arm: ComparisonArm, role: str) -> dict[str, Any]:
        """A model arm as a definition records it: the model, how it is asked and under what."""
        contract = self.role.contract()
        try:
            spec = self.manifest.offered(self.role.chosen, arm.model_id)
        except ManifestError as exc:
            raise SignalComparisonRefused(
                "model_not_offered", f"{arm.model_id} is not offered for a signal's decisions"
            ) from exc
        mechanism = contract.mechanism_for(spec)
        answering = contract.answering(spec)
        if spec.provider != arm.provider or mechanism is None or answering is None:
            raise SignalComparisonRefused(
                "model_not_offered", f"{arm.provider}/{arm.model_id} is not askable"
            )
        return {
            "role": role,
            "decider": {"kind": "model", "provider": spec.provider, "model_id": spec.model_id},
            "provider_config": {
                "provider": spec.provider,
                "model_id": spec.model_id,
                "mechanism": mechanism.value,
                "choice_seq": None,
                "manifest_sha256": self.manifest_sha256,
                "prompt_version": self.role.prompt_version,
                "contract": contract.binding(),
                "deadline_ms": contract.value("decision_deadline_ms"),
            },
            "answering": answering,
            "description": spec.description,
        }

    def body(
        self,
        models: Sequence[ComparisonArm],
        seeds: Sequence[str],
        *,
        control: bool,
        group: Sequence[str] | None,
    ) -> dict[str, Any]:
        """What a definition states that the roads do not: the arms, the claim, the seeds by
        digest and the group, every signal of the roads where ``group`` is None."""
        arms: dict[str, dict[str, Any]] = {
            FIXED_ARM: {
                "role": "one",
                "decider": {"kind": "fixed"},
                "provider_config": None,
                "answering": None,
                "description": "The signal plan's fixed timing",
            }
        }
        keys = []
        for index, model in enumerate(models):
            key = f"model_{chr(ord('a') + index)}"
            arms[key] = self.model_arm(model, "candidate")
            keys.append(key)
        control_pair = None
        if control:
            arms[f"{keys[0]}_again"] = self.model_arm(models[0], "control")
            control_pair = [keys[0], f"{keys[0]}_again"]
        family = [[FIXED_ARM, key] for key in keys]
        primary = family[0]
        if len(keys) >= 2:
            primary = [keys[0], keys[1]]
            family = [primary, *family]
        return {
            "phase": "development",
            "seeds": [seed_digest(seed) for seed in seeds],
            "group": None if group is None else sorted(set(group)),
            "arms": arms,
            "claim": {"primary": primary, "family": family, "control": control_pair},
            "preregistration": None,
        }

    def define(
        self,
        version_id: uuid.UUID,
        *,
        comparison_id: uuid.UUID,
        body: Mapping[str, Any],
        connection: Any = None,
    ) -> dict[str, Any]:
        """Record ``body`` as a signal comparison of this version's roads as they are, in a
        transaction of its own, or inside the caller's on ``connection``."""
        if connection is None:
            with self.database.session(self.workspace_id) as held:
                return self.define(
                    version_id, comparison_id=comparison_id, body=body, connection=held
                )
        repository = self._repository(connection)
        roads = repository.roads(version_id)
        document = self.definition(
            version_id, roads, compute_signal_catalog(wire(roads)), body=body
        )
        with connection.transaction():
            return repository.define(comparison_id, document, created_by=self.actor)

    def definition(
        self,
        version_id: uuid.UUID,
        roads: TrafficInput,
        signals: Sequence[Mapping[str, Any]],
        *,
        body: Mapping[str, Any],
    ) -> dict[str, Any]:
        """The definition ``body`` makes over ``roads`` and the ``signals`` they place, checked
        and not yet recorded: every signal of the roads where the body names no group."""
        signals = sorted((dict(row) for row in signals), key=lambda row: row["signal_id"])
        known = {row["signal_id"] for row in signals}
        if not known:
            raise SignalComparisonRefused("signals_absent", "these roads place no signal")
        group = sorted(known) if body["group"] is None else list(body["group"])
        if not set(group) <= known:
            raise SignalComparisonRefused(
                "signal_not_in_world", "the group names a signal not here"
            )
        timing_plan = signal_actuation().plan
        document = {
            "profile": DEFINITION_PROFILE,
            "world_id": self.world_id,
            "version_id": str(version_id),
            "roads": {
                "roads_version": roads.version_id,
                "input_sha256": roads.sha256,
                "city_identity": roads.city_identity,
                "grammar_version": roads.grammar_version,
                "timebase": "legacy",
                "crossings_fed": False,
            },
            "timing": {"plan": timing_plan},
            "episode_seconds": EPISODE,
            "observation_profile": OBSERVATION_PROFILE,
            "phase": body["phase"],
            "seeds": list(body["seeds"]),
            "group": group,
            "signals": signals,
            "arms": {key: dict(arm) for key, arm in sorted(body["arms"].items())},
            "claim": body["claim"],
            "preregistration": body["preregistration"],
            "contract": self.role.contract().binding(),
            "catalogs": dict(sorted(self.catalogs.versions.items())),
            "measure": {
                "profile": "exulanica.signal-comparison-terms/v1",
                "meaning": (
                    "mean delay per entry at the group's signalled junctions, in milliseconds: "
                    "the traffic step's own delay of each vehicle from reaching the junction's "
                    "approach lane to crossing its stop line, less its free-flow time; lower is "
                    "less waiting. Trips are reported beside it, never folded into it. Cars in "
                    "these episodes do not see walkers."
                ),
            },
        }
        check_definition(document, self.catalogs)
        return document

    def reserve_all(
        self, comparison_id: uuid.UUID, seeds: Sequence[str], *, connection: Any = None
    ) -> list[uuid.UUID]:
        """Every run of the comparison, one per arm and seed, reserved before anything is asked."""
        if connection is None:
            with self.database.session(self.workspace_id) as held:
                return self.reserve_all(comparison_id, seeds, connection=held)
        with connection.transaction():
            repository = self._repository(connection)
            definition = repository._definition(comparison_id)["document"]  # type: ignore[index]
            return [
                repository.reserve(comparison_id, arm=arm, seed=seed, created_by=self.actor)
                for seed in seeds
                for arm in sorted(definition["arms"])
            ]

    # -- runs ------------------------------------------------------------------------------------

    def run_all(
        self,
        comparison_id: uuid.UUID,
        run_ids: Sequence[uuid.UUID],
        *,
        host: RunHost | None = None,
    ) -> list[dict[str, Any]]:
        """Play every run that has no outcome yet, one after another, each seed's fixed-timing
        anchor before its model runs; a seed a claiming ``host`` does not admit closes its runs
        and every later seed's as ``comparison_bound_before_seed``, asking nothing."""
        with self.database.session(self.workspace_id) as connection:
            repository = self._repository(connection)
            definition = repository._definition(comparison_id)["document"]  # type: ignore[index]
            reserved = {run_id: repository._run(run_id) for run_id in run_ids}
        found: dict[uuid.UUID, dict[str, Any]] = {}
        closing: list[uuid.UUID] = []
        for digest in definition["seeds"]:
            seed = [run_id for run_id in run_ids if reserved[run_id]["seed_digest"] == digest]
            anchors = [run_id for run_id in seed if reserved[run_id]["arm"] == FIXED_ARM]
            models = [run_id for run_id in seed if reserved[run_id]["arm"] != FIXED_ARM]
            if closing or (host is not None and models and not host.admit(models)):
                closing.extend(seed)
                continue
            for run_id in [*anchors, *models]:
                found[run_id] = self.run(comparison_id, run_id, host=host)
        if closing:
            self.fail_open(comparison_id, dict.fromkeys(closing, "comparison_bound_before_seed"))
            with self.database.session(self.workspace_id) as connection:
                repository = self._repository(connection)
                for run_id in closing:
                    closed = repository.outcome(run_id)
                    assert closed is not None, "a closed run has its outcome"
                    found[run_id] = closed
        return [found[run_id] for run_id in run_ids]

    def run(
        self, comparison_id: uuid.UUID, run_id: uuid.UUID, *, host: RunHost | None = None
    ) -> dict[str, Any]:
        """Play one reserved run and record its outcome; a run already finished is read back.

        Under a claiming ``host``, the claim is renewed before the run and after each answered
        choice point, a host that is stopping leaves a run that has asked nothing for the next
        claim and closes one that has as ``interrupted``, and a cancelled comparison stops before
        its next ask."""
        if host is not None:
            if host.stopping():
                raise HostStopping
            host.minute()

        def recorded(connection: psycopg.Connection, outcome: dict[str, Any]) -> dict[str, Any]:
            if host is not None:
                host.recorded(connection)
            return outcome

        with self.database.session(self.workspace_id) as connection, connection.transaction():
            repository = self._repository(connection)
            done = repository.outcome(run_id)
            if done is not None:
                return done
            reserved = repository._run(run_id)
            definition = repository._definition(comparison_id)["document"]  # type: ignore[index]
            arm, digest = reserved["arm"], reserved["seed_digest"]

            def failed(code: str) -> dict[str, Any]:
                return recorded(
                    connection,
                    repository.finish(
                        comparison_id, run_id, failure_outcome(definition, arm, digest, code)
                    ),
                )

            if host is not None and host.cancelled():
                return failed(CANCELLED)
            if repository.stored(run_id):
                return failed(_INTERRUPTED)
            if arm != FIXED_ARM:
                anchor = repository.outcome(run_id_for(comparison_id, FIXED_ARM, digest))
                if anchor is None:
                    raise SignalComparisonRefused(
                        "anchors_first", "a model run starts once its seed's fixed run completed"
                    )
                if anchor["status"] != "completed":
                    return failed(_ANCHOR_FAILED)
            try:
                plan, _definition = repository.plan(comparison_id, run_id, self.role)
            except SignalComparisonRefused as exc:
                if exc.code != "roads_changed":
                    raise
                return failed("roads_changed")
            except (TrafficRefused, InvalidStructuralData):
                return failed(_INPUT_UNAVAILABLE)
        if host is not None:
            host.started(run_id)
        asking: _Asking | _Fixed | None = None

        def store(request: dict[str, Any], receipt: dict[str, Any]) -> None:
            with self.database.session(self.workspace_id) as held, held.transaction():
                self._repository(held).append(comparison_id, run_id, request, receipt)
            reason = receipt["reason"]
            if reason in RUN_FAILURE_CODES:
                if (
                    reason == "process_budget_spent"
                    and isinstance(asking, _Asking)
                    and asking.bound_refused()
                ):
                    reason = _BOUND_SPENT
                raise _RunStopped(reason)
            if host is not None:
                host.minute()
                if host.stopping():
                    raise _RunStopped(_INTERRUPTED)

        try:
            asking = self._asking(plan, definition["arms"][arm], host)
            played = play(plan, asking, on_point=store)
        except _RunStopped as stop:
            outcome = failure_outcome(definition, arm, digest, stop.code)
        else:
            outcome = run_outcome(plan, definition, arm, digest, played)
        with self.database.session(self.workspace_id) as connection, connection.transaction():
            return recorded(
                connection, self._repository(connection).finish(comparison_id, run_id, outcome)
            )

    def _asking(
        self, plan: SignalRunPlan, arm: Mapping[str, Any], host: RunHost | None
    ) -> _Asking | _Fixed:
        """What a run asks: nobody under fixed timing, else its arm's model, checked against the
        manifest and the contract as the definition recorded it."""
        if arm["decider"]["kind"] == "fixed":
            return _Fixed()
        if self.client is None:
            raise _RunStopped("provider_credential_absent")
        config = arm["provider_config"]
        try:
            spec = self.manifest.offered(self.role.chosen, config["model_id"])
        except ManifestError:
            raise _RunStopped("model_no_longer_offered") from None
        mechanism = plan.contract.mechanism_for(spec)
        if (
            spec.provider != config["provider"]
            or mechanism is None
            or mechanism.value != config["mechanism"]
            or config["prompt_version"] != self.role.prompt_version
            or plan.contract.answering(spec) != dict(arm["answering"] or {})
        ):
            raise _RunStopped("provider_configuration_changed")
        client = self.client.with_policy(self.policy_for(self.workspace_id))
        if question_refusal(self.role, client, spec.model_id) is not None:
            raise _RunStopped(_QUESTION_CHANGED)
        run_bound = (
            None
            if self.bound is None
            else BoundedBudget(
                self.bound, ceiling_usd=self.bound.ceiling_usd, max_calls=self.bound.max_calls
            )
        )
        return _Asking(
            client if run_bound is None else client.with_bound(run_bound),
            self.role,
            spec,
            mechanism,
            bound=self.bound,
            run_bound=run_bound,
            keeps_share=self.keeps_share,
            cancelled=host.cancelled if host is not None else (lambda: False),
        )

    def fail_open(
        self,
        comparison_id: uuid.UUID,
        codes: Mapping[uuid.UUID, str],
        *,
        connection: Any = None,
    ) -> None:
        """Record each run of ``codes`` that has no outcome yet as failed by its code, asking
        nothing, inside the caller's transaction on ``connection`` or one of its own."""
        for code in codes.values():
            if code not in RUN_FAILURE_CODES:
                raise ValueError(f"a run fails only by a stated code, not {code!r}")
        if connection is None:
            with self.database.session(self.workspace_id) as held, held.transaction():
                self.fail_open(comparison_id, codes, connection=held)
            return
        with connection.transaction():
            repository = self._repository(connection)
            definition = repository._definition(comparison_id)["document"]  # type: ignore[index]
            for run_id, code in codes.items():
                if repository.outcome(run_id) is not None:
                    continue
                reserved = repository._run(run_id)
                repository.finish(
                    comparison_id,
                    run_id,
                    failure_outcome(definition, reserved["arm"], reserved["seed_digest"], code),
                )

    def replay(self, comparison_id: uuid.UUID, run_id: uuid.UUID) -> PlayedSignalRun:
        """A completed run played again from what it stored, asking nothing, held to its record:
        refused as :class:`~exulanica.world.signal_comparison.ReplayMismatch` where it differs."""
        with self.database.session(self.workspace_id) as connection:
            repository = self._repository(connection)
            outcome = repository.outcome(run_id)
            if outcome is None or outcome["status"] != "completed":
                raise SignalComparisonRefused(
                    "run_not_completed", "this run has no completed episode"
                )
            plan, _definition = repository.plan(comparison_id, run_id, self.role)
            stored = repository.stored(run_id)
        return replay(
            plan,
            stored,
            continuation_sha256=outcome["continuation_sha256"],
            terms=outcome["terms"],
        )
