"""Trusted local execution of a comparison: every run, minutes back to back, models asked as the
host asks them.

A comparison is defined and run by a local command (``python -m exulanica.orchestration.compare``),
never from a route: the page only reads what a comparison recorded. The runner plays each run
through :func:`exulanica.world.society_comparison.play`. A model arm's people are asked as the
host's playback asks a person whose world's owner chose a model, save that rules which would change
a question fail the run where the host leaves those people to their routine, and that an ask ends
by the contract's deadline alone, with no lease to end within: the workspace's rules judge the
fixed description and every label once a minute before anybody is asked, a label they would
change is left out (``_sendable_labels``), and each person is asked by
:func:`~exulanica.api.society_person_decisions.ask_person`, through the one client, with no
database connection held while anybody is asked. Each minute's receipts are appended as they are
paid for, and a run ends in one outcome: completed, with its minutes' digests and the score's
terms, or failed by name.

What makes a run fail rather than complete is the host, never the model: a process budget that no
longer fits one ask of the arm's model, a provider or credential the process refuses, a model the
manifest no longer offers, rules that would change the question itself, or a request the rules
refused. A score that counted such turns would describe the host. The whole process budget,
``EXULANICA_BUDGET_USD``, is the comparison's: the runner keeps none of it back for other work, as
the host keeps a share, because a comparison's process does nothing else. The world's hour
bounds on a live world's decisions do not apply: a comparison writes nothing the live world reads.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

from exulanica.api.society_person_decisions import (
    PersonAsk,
    _sendable_labels,
    ask_bound_usd,
    ask_person,
)
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.db.session import Database
from exulanica.models.client import ModelClient
from exulanica.models.errors import ManifestError
from exulanica.models.manifest import Manifest, ModelSpec, Role
from exulanica.models.policy import HostedRequestPolicy
from exulanica.models.usage import usd_string
from exulanica.selection.validation import Session
from exulanica.world.society_catalogs import ComparisonCatalogs, load_comparison_catalogs
from exulanica.world.society_comparison import PlayedRun, RunPlan, play
from exulanica.world.society_comparison_repository import (
    SocietyComparisonRepository,
    seed_digest,
)
from exulanica.world.society_comparison_result import (
    FAILURE_PROFILE,
    protocol_value,
    run_outcome,
)
from exulanica.world.society_decision_contract import (
    PROMPT_VERSION,
    DecisionContract,
    DecisionOption,
    decision_contract,
)
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.society_score import person_score

__all__ = ["RUN_FAILURE_CODES", "ComparisonArm", "SocietyComparisonRunner", "call_facts"]

_LOG = logging.getLogger(__name__)
#: Every code a failed run's outcome records. Each says the host, not the model, ended the run's
#: asking: a budget that no longer fits one ask, a provider or a credential the process refuses, a
#: model the manifest no longer offers, serves from another provider or asks otherwise than the
#: definition recorded, rules that would change the question itself, or a request the rules
#: refused; or a run the process stopped part way, found with receipts and no outcome. A receipt
#: whose reason is one of them stops its run there; every other reason a turn was not the model's
#: is the model's own, and is scored (``turns_unanswered``). The page has words for each.
RUN_FAILURE_CODES: Final = frozenset(
    {
        "interrupted",
        "model_no_longer_offered",
        "process_budget_spent",
        "process_share_spent",
        "provider_changed",
        "provider_configuration_changed",
        "provider_credential_absent",
        "provider_not_admitted",
        "question_changed_by_rules",
        "request_refused",
    }
)
#: Why a run with receipts and no outcome is closed: the process that played it stopped part way,
#: and its hour cannot be played again under the receipts it holds.
INTERRUPTED: Final = "interrupted"
#: Why a run failed before anybody was asked in a minute: the rules would change the question.
QUESTION_CHANGED: Final = "question_changed_by_rules"


class _RunStopped(Exception):
    """A run the host cannot go on with, by the name its outcome records."""

    def __init__(self, code: str) -> None:
        if code not in RUN_FAILURE_CODES:
            raise ValueError(f"a run fails only by a stated code, not {code!r}")
        super().__init__(code)
        self.code = code


class _RunStoppedBeforeStart(_RunStopped):
    """A model arm the host cannot ask at all, found before its first minute."""


def call_facts(receipts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What a run's asking took, from the host's record of each call: never scored.

    A first answer was refused when a second was asked, or when the turn ended with no offered
    answer. A turn's latency is the whole ask's, every answer in it.
    """
    asked = [receipt for receipt in receipts if receipt["provider"] is not None]
    return {
        "asked": len(asked),
        "first_answers_refused": sum(
            1
            for receipt in asked
            if receipt["provider"]["answers_asked"] > 1 or receipt["reason"] == "answer_not_offered"
        ),
        "cost_usd": usd_string(
            sum((Decimal(receipt["provider"]["cost_usd"]) for receipt in asked), Decimal(0))
        ),
        "cost_known": all(receipt["provider"]["cost_known"] for receipt in asked),
        "latencies_ms": [int(receipt["provider"]["latency_ms"]) for receipt in asked],
    }


@dataclass(frozen=True, slots=True)
class ComparisonArm:
    """One model a comparison asks, as its command names it: provider and model id."""

    provider: str
    model_id: str


class _Asking:
    """A model arm's asking, minute by minute, as the host asks a chosen person's model."""

    def __init__(
        self,
        client: ModelClient,
        manifest: Manifest,
        contract: DecisionContract,
        spec: ModelSpec,
        config: Mapping[str, Any],
    ) -> None:
        self.client = client
        self.manifest = manifest
        self.contract = contract
        self.spec = spec
        self.config = config
        self.mechanism = contract.mechanism_for(spec)

    def offerable(
        self, tick: int, due: Mapping[str, Sequence[DecisionOption]]
    ) -> dict[str, frozenset[str]]:
        refused = self.client.refusals.get(self.spec.provider)
        if refused is not None:
            raise _RunStopped(refused)
        # Room is judged as the host judges it, on what is spent, with nothing kept back: the
        # comparison's process does no other work, so the whole budget is the comparison's.
        budget = self.client.budget
        need = ask_bound_usd(budget, self.spec, self.contract)
        calls = self.contract.value("answer_attempts_maximum")
        if budget.ceiling_usd - budget.spent_usd < need or (
            budget.max_calls - budget.billed_calls < calls
        ):
            raise _RunStopped("process_budget_spent")
        labels = sorted({option.label for options in due.values() for option in options})
        sendable = _sendable_labels(self.client, self.spec.model_id, labels)
        if sendable is None:
            raise _RunStopped(QUESTION_CHANGED)
        return {subject: sendable for subject in due}

    def answers(self, requests: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        mechanism = self.mechanism
        if mechanism is None:
            raise _RunStopped("model_no_longer_offered")
        ends_at = time.monotonic() + self.contract.value("decision_deadline_ms") / 1000
        workers = max(1, min(self.contract.value("concurrent_calls_maximum"), len(requests)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(
                    ask_person,
                    self.client,
                    PersonAsk(request, self.spec, mechanism),
                    self.contract,
                    ends_at,
                )
                for request in requests
            ]
            results = []
            for future in futures:
                try:
                    results.append(future.result())
                except Exception:
                    # An error before anything was sent: an error in an attempt is ask_person's,
                    # which keeps what the attempts cost. Never an exception's text, which may
                    # carry request bytes or a credential.
                    _LOG.error("A comparison's ask failed; the routine decides that turn")
                    results.append(
                        {
                            "status": "unavailable",
                            "reason": "model_call_failed",
                            "proposal": None,
                            "provider": None,
                        }
                    )
        return results


class _Anchor:
    """An anchor arm asks nobody."""

    def offerable(
        self, tick: int, due: Mapping[str, Sequence[DecisionOption]]
    ) -> dict[str, frozenset[str]]:
        raise AssertionError("an anchor arm asks nobody")

    def answers(self, requests: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        raise AssertionError("an anchor arm asks nobody")


@dataclass(frozen=True)
class SocietyComparisonRunner:
    """Defines and runs comparisons in one workspace and world, as ``actor``."""

    database: Database
    runtime: SocietyRuntime
    client: ModelClient | None
    policy_for: Callable[[uuid.UUID], HostedRequestPolicy]
    manifest: Manifest
    manifest_sha256: str
    workspace_id: uuid.UUID
    world_id: str
    actor: uuid.UUID
    #: The score, protocol and seed catalogs a comparison is defined and scored under.
    catalogs: ComparisonCatalogs = field(default_factory=load_comparison_catalogs)

    def _repository(self, connection: Any) -> SocietyComparisonRepository:
        session = Session(workspace_id=self.workspace_id, actor=self.actor)
        return SocietyComparisonRepository(
            SocietyRepository(
                connection,
                self.workspace_id,
                world_id=self.world_id,
                input_authorizer=lambda doc: self.runtime.authorize(connection, session, doc),
            )
        )

    # -- definitions -------------------------------------------------------------------------

    def model_arm(self, arm: ComparisonArm, role: str) -> dict[str, Any]:
        """A model arm as a definition records it: the model, how it is asked and under what."""
        contract = decision_contract()
        try:
            spec = self.manifest.offered(Role.SOCIETY_DECISION, arm.model_id)
        except ManifestError as exc:
            raise ValueError(f"{arm.model_id} is not offered for a person's decisions") from exc
        mechanism = contract.mechanism_for(spec)
        if spec.provider != arm.provider or mechanism is None:
            raise ValueError(f"{arm.provider}/{arm.model_id} is not askable under the contract")
        return {
            "role": role,
            "decider": {"kind": "model", "provider": spec.provider, "model_id": spec.model_id},
            "provider_config": {
                "provider": spec.provider,
                "model_id": spec.model_id,
                "mechanism": mechanism.value,
                # No owner's choice made this person model-run: the comparison's arm did.
                "choice_seq": None,
                "manifest_sha256": self.manifest_sha256,
                "prompt_version": PROMPT_VERSION,
                "contract": contract.binding(),
                "deadline_ms": contract.value("decision_deadline_ms"),
            },
            "description": spec.description,
        }

    def define(
        self,
        version_id: uuid.UUID,
        *,
        comparison_id: uuid.UUID,
        body: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self.database.session(self.workspace_id) as connection, connection.transaction():
            return self._repository(connection).define(
                version_id,
                comparison_id=comparison_id,
                body=body,
                created_by=self.actor,
                catalogs=self.catalogs,
            )

    # -- runs -------------------------------------------------------------------------------

    def reserve_all(self, comparison_id: uuid.UUID, seeds: Sequence[str]) -> list[uuid.UUID]:
        """Every run of the comparison, one per arm and seed, reserved before anything is asked."""
        with self.database.session(self.workspace_id) as connection, connection.transaction():
            repository = self._repository(connection)
            definition = repository._definition(comparison_id)["document"]  # type: ignore[index]
            return [
                repository.reserve(comparison_id, arm=arm, seed=seed, created_by=self.actor)
                for seed in seeds
                for arm in sorted(definition["arms"])
            ]

    def run_all(self, comparison_id: uuid.UUID, run_ids: Sequence[uuid.UUID]) -> list[dict]:
        """Play every run that has no outcome yet, the protocol's number at a time."""
        at_once = protocol_value(self.catalogs, "runs_at_once")
        with ThreadPoolExecutor(max_workers=at_once) as pool:
            return list(pool.map(lambda run_id: self.run(comparison_id, run_id), run_ids))

    def run(self, comparison_id: uuid.UUID, run_id: uuid.UUID) -> dict[str, Any]:
        """Play one reserved run and record its outcome; a run already finished is read back.

        A run that holds receipts and no outcome was stopped part way, by a crash or a killed
        process. Its hour is not played again, which would ask the models again for receipts it
        already holds: before anything is asked, it is recorded as failed, ``interrupted``, as
        the host closes what a stopped claim left open, and running it again is a new comparison.
        """
        with self.database.session(self.workspace_id) as connection, connection.transaction():
            repository = self._repository(connection)
            done = repository.outcome(run_id)
            if done is not None:
                return done
            if repository.stored(run_id):
                reserved = repository._run(run_id)
                definition = repository._definition(comparison_id)["document"]  # type: ignore[index]
                return repository.finish(
                    comparison_id,
                    run_id,
                    self._failed(
                        definition, reserved["arm"], seed_digest(reserved["seed"]), INTERRUPTED
                    ),
                )
            plan, definition = repository.plan(comparison_id, run_id)
            arm = repository._run(run_id)["arm"]
        digest = seed_digest(plan.seed)

        def store(tick: int, requests: Sequence[dict], receipts: Sequence[dict]) -> None:
            if receipts:
                with (
                    self.database.session(self.workspace_id) as connection,
                    connection.transaction(),
                ):
                    self._repository(connection).append(comparison_id, run_id, requests, receipts)
            stopped = next(
                (r["reason"] for r in receipts if r["reason"] in RUN_FAILURE_CODES), None
            )
            if stopped is not None:
                raise _RunStopped(stopped)

        try:
            played = play(plan, self._asking(plan), on_minute=store)
        except _RunStopped as stop:
            outcome = self._failed(definition, arm, digest, stop.code)
        else:
            outcome = self._completed(plan, definition, arm, digest, played)
        with self.database.session(self.workspace_id) as connection, connection.transaction():
            return self._repository(connection).finish(comparison_id, run_id, outcome)

    def _asking(self, plan: RunPlan) -> _Asking | _Anchor:
        if plan.decider["kind"] != "model":
            return _Anchor()
        config = plan.provider_config or {}
        if self.client is None:
            raise _RunStoppedBeforeStart("provider_credential_absent")
        try:
            spec = self.manifest.offered(Role.SOCIETY_DECISION, config["model_id"])
        except ManifestError:
            raise _RunStoppedBeforeStart("model_no_longer_offered") from None
        mechanism = plan.contract.mechanism_for(spec)
        if (
            spec.provider != config["provider"]
            or mechanism is None
            or mechanism.value != config["mechanism"]
            or config["prompt_version"] != PROMPT_VERSION
        ):
            raise _RunStoppedBeforeStart("provider_configuration_changed")
        return _Asking(
            self.client.with_policy(self.policy_for(self.workspace_id)),
            self.manifest,
            plan.contract,
            spec,
            config,
        )

    @staticmethod
    def _failed(definition: Mapping[str, Any], arm: str, digest: str, code: str) -> dict:
        return {
            "profile": FAILURE_PROFILE,
            "status": "failed",
            "definition_sha256": definition["document_sha256"],
            "arm": arm,
            "seed_digest": digest,
            "code": code,
        }

    def _completed(
        self, plan: RunPlan, definition: Mapping[str, Any], arm: str, digest: str, played: PlayedRun
    ) -> dict:
        calls = call_facts(played.receipts) if plan.decider["kind"] == "model" else None
        score = person_score(self.catalogs.score)
        return run_outcome(plan, definition, arm, digest, played, calls, score)
