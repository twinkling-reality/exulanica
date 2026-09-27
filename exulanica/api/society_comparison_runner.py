"""Trusted local execution of a comparison: every run, minutes back to back, models asked as the
host asks them.

A comparison is defined and run by a local command (``python -m exulanica.orchestration.compare``),
never from a route: the page only reads what a comparison recorded. The runner plays each run
through :func:`exulanica.world.society_comparison.play`. Every person a model decides for, the
group under a model arm and anybody outside it whose world's owner chose a model, is asked as the
host's playback asks a person whose owner chose a model, save that rules which would change a
question fail the run where the host leaves those people to their routine, and that an ask ends
by the contract's deadline alone, with no lease to end within: the workspace's rules judge the
fixed description and every label once a minute before anybody is asked, for each model in one
pass, a label they would change is left out (``_sendable_labels``), and each person is asked by
:func:`~exulanica.api.society_person_decisions.ask_person`, through the one client, with no
database connection held while anybody is asked. Each minute's receipts are appended as they are
paid for, and a run ends in one outcome: completed, with its minutes' digests and the score's
terms, or failed by name.

A seed's anchors run before any model run of it, and a model run starts only once both of its
seed's anchors completed: one refused by name while either has no outcome (``anchors_first``), and
closed as failed before anything is asked when either failed (``anchor_failed``), since its score
could never be read. The routine's run records its choice points for the group, the denominator
every rate of what a model answered on that seed is read over. Where everybody outside the group
follows their routine, as a judged comparison requires, the anchors ask nobody, so that
denominator is fixed before any model is asked and no model's answers move it; in a development
comparison with a model outside the group, the anchors ask it too, and the served result says so.

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
from exulanica.models.manifest import AnsweringMechanism, Manifest, ModelSpec
from exulanica.models.policy import HostedRequestPolicy
from exulanica.models.usage import usd_string
from exulanica.selection.validation import Session
from exulanica.world.decision_roles import RoleOption
from exulanica.world.society_catalogs import ComparisonCatalogs, load_comparison_catalogs
from exulanica.world.society_comparison import PlayedRun, RunPlan, play
from exulanica.world.society_comparison_repository import (
    SocietyComparisonRepository,
    run_id_for,
    seed_digest,
)
from exulanica.world.society_comparison_result import (
    FAILURE_PROFILE,
    ComparisonRefused,
    definition_version,
    protocol_value,
    run_outcome,
)
from exulanica.world.society_comparison_verdict import ANCHOR_ROLES
from exulanica.world.society_decision_contract import (
    PROMPT_VERSION,
    DecisionContract,
    decision_contract,
    person_role,
)
from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository
from exulanica.world.society_repository import SocietyRepository

__all__ = ["RUN_FAILURE_CODES", "ComparisonArm", "SocietyComparisonRunner", "call_facts"]

_LOG = logging.getLogger(__name__)
#: Every code a failed run's outcome records. Each says the host, not the model, ended the run's
#: asking: a budget that no longer fits one ask, a provider or a credential the process refuses, a
#: model the manifest no longer offers, serves from another provider or asks otherwise than the
#: definition recorded, rules that would change the question itself, or a request the rules
#: refused; a run the process stopped part way, found with receipts and no outcome; or a model run
#: whose seed's anchors did not complete, closed before it asks. A receipt whose reason is one of
#: them stops its run there; every other reason a turn was not the model's is the model's own, and
#: is reported beside the score. The page has words for each.
RUN_FAILURE_CODES: Final = frozenset(
    {
        "anchor_failed",
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
#: Why a model run is closed before it asks: an anchor of its seed failed, so it has no score.
ANCHOR_FAILED: Final = "anchor_failed"


def _recorded_answering(
    definition: Mapping[str, Any], arm: str
) -> dict[str, Mapping[str, Any] | None]:
    """Each model's answering as ``definition`` records it for a run of ``arm``, by model id: the
    arm's model and every model the owner chose for somebody outside the group. A definition
    recorded before answering was recorded names none, and its runs are held to the mechanism
    alone."""
    held: dict[str, Mapping[str, Any] | None] = {}
    deciders = [definition["arms"][arm], *definition.get("others", ())]
    for decider in deciders:
        config = decider.get("provider_config")
        if config is not None and decider.get("answering") is not None:
            held[config["model_id"]] = decider["answering"]
    return held


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
    """A run's asking, minute by minute, as the host asks a chosen person's model: one or more
    models, each person asked of the model that decides for them."""

    def __init__(
        self,
        client: ModelClient,
        manifest: Manifest,
        contract: DecisionContract,
        models: Mapping[str, tuple[ModelSpec, AnsweringMechanism]],
        model_of: Callable[[str], str],
    ) -> None:
        self.client = client
        self.manifest = manifest
        self.contract = contract
        #: Each model the run asks, by identifier, and how it is asked.
        self.models = models
        #: The model that decides for a person a model decides for, by subject id.
        self.model_of = model_of

    def offerable(
        self, tick: int, due: Mapping[str, Sequence[RoleOption]]
    ) -> dict[str, frozenset[str]]:
        asked = sorted({self.model_of(subject) for subject in due})
        for model_id in asked:
            refused = self.client.refusals.get(self.models[model_id][0].provider)
            if refused is not None:
                raise _RunStopped(refused)
        # Room is judged as the host judges it, on what is spent, with nothing kept back: the
        # comparison's process does no other work, so the whole budget is the comparison's. One
        # ask of the dearest model due must fit.
        budget = self.client.budget
        need = max(ask_bound_usd(budget, self.models[m][0], self.contract) for m in asked)
        calls = self.contract.value("answer_attempts_maximum")
        if budget.ceiling_usd - budget.spent_usd < need or (
            budget.max_calls - budget.billed_calls < calls
        ):
            raise _RunStopped("process_budget_spent")
        sendable: dict[str, frozenset[str]] = {}
        for model_id in asked:
            labels = sorted(
                {
                    option.label
                    for subject, options in due.items()
                    if self.model_of(subject) == model_id
                    for option in options
                }
            )
            found = _sendable_labels(self.client, model_id, labels)
            if found is None:
                raise _RunStopped(QUESTION_CHANGED)
            sendable[model_id] = found
        return {subject: sendable[self.model_of(subject)] for subject in due}

    def answers(self, requests: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        ends_at = time.monotonic() + self.contract.value("decision_deadline_ms") / 1000
        workers = max(1, min(self.contract.value("concurrent_calls_maximum"), len(requests)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(
                    ask_person,
                    self.client,
                    PersonAsk(request, *self.models[request["provider_config"]["model_id"]]),
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
        self, tick: int, due: Mapping[str, Sequence[RoleOption]]
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

    def _model(
        self, arm: ComparisonArm, choice_seq: int | None
    ) -> tuple[dict, dict, dict, ModelSpec]:
        """A model as a definition records it: the decider, what its requests record of how it is
        asked and under what, as the host records it for a person whose owner chose it, and its
        answering (the order it is asked in and whose order that is,
        :meth:`~exulanica.world.society_decision_contract.DecisionContract.answering`), since the
        mechanism a model answers by changes what it chooses, not only how long it takes."""
        contract = decision_contract()
        try:
            spec = self.manifest.offered(person_role().chosen, arm.model_id)
        except ManifestError as exc:
            raise ValueError(f"{arm.model_id} is not offered for a person's decisions") from exc
        mechanism = contract.mechanism_for(spec)
        answering = contract.answering(spec)
        if spec.provider != arm.provider or mechanism is None or answering is None:
            raise ValueError(f"{arm.provider}/{arm.model_id} is not askable under the contract")
        decider = {"kind": "model", "provider": spec.provider, "model_id": spec.model_id}
        config = {
            "provider": spec.provider,
            "model_id": spec.model_id,
            "mechanism": mechanism.value,
            "choice_seq": choice_seq,
            "manifest_sha256": self.manifest_sha256,
            "prompt_version": PROMPT_VERSION,
            "contract": contract.binding(),
            "deadline_ms": contract.value("decision_deadline_ms"),
        }
        return decider, config, answering, spec

    def model_arm(self, arm: ComparisonArm, role: str) -> dict[str, Any]:
        """A model arm as a definition records it: the model, how it is asked and under what."""
        # No owner's choice made the group model-run: the comparison's arm did.
        decider, config, answering, spec = self._model(arm, None)
        return {
            "role": role,
            "decider": decider,
            "provider_config": config,
            "answering": answering,
            "description": spec.description,
        }

    def _choices(self, version_id: uuid.UUID) -> tuple[list[str], list[dict[str, Any]]]:
        """The version's people, by subject id, and every choice its owner made, in order."""
        with self.database.session(self.workspace_id) as connection:
            row = self._repository(connection).society._row(version_id)
            if row is None:
                raise ComparisonRefused("society_unavailable", "the version holds no society")
            choices = SocietyModelChoiceRepository(
                connection, self.workspace_id, world_id=self.world_id
            ).history(version_id, person_role())
        return sorted(person["id"] for person in row["state"]["inhabitants"]), choices

    def group_of_choice(self, version_id: uuid.UUID, choice_seq: int) -> dict[str, Any]:
        """The group one of the owner's choices named, as a definition's body states it."""
        _people, choices = self._choices(version_id)
        choice = next((held for held in choices if held["choice_seq"] == choice_seq), None)
        if choice is None:
            raise ComparisonRefused("choice_unknown", f"no choice {choice_seq} in this world")
        return {
            "people": sorted(choice["people"]),
            "source": {
                "kind": "owner_choice",
                "choice_seq": choice["choice_seq"],
                "document_sha256": choice["document_sha256"],
            },
        }

    def others_for(self, version_id: uuid.UUID, group: Sequence[str] | None) -> list[dict]:
        """Everybody outside ``group`` and what decides for them in every arm: the model the
        owner's latest choice for them names, asked as the host asks it, or their routine. A model
        the owner chose that this server cannot ask as the contract asks it is refused by name,
        since every arm would ask it."""
        people, choices = self._choices(version_id)
        if group is None:
            return []
        latest: dict[str, dict[str, Any]] = {}
        for made in choices:
            for subject in made["people"]:
                latest[subject] = made
        others = []
        for subject in sorted(set(people) - set(group)):
            choice = latest.get(subject)
            decider: dict[str, Any] = {"kind": "routine"}
            config: dict[str, Any] | None = None
            answering: dict[str, Any] | None = None
            if choice is not None and choice["model"] is not None:
                model = choice["model"]
                try:
                    decider, config, answering, _spec = self._model(
                        ComparisonArm(model["provider"], model["model_id"]), choice["choice_seq"]
                    )
                except ValueError as exc:
                    raise ComparisonRefused("owner_choice_not_askable", str(exc)) from exc
            others.append(
                {
                    "id": subject,
                    "decider": decider,
                    "provider_config": config,
                    "answering": answering,
                    "choice": None
                    if choice is None
                    else {
                        "choice_seq": choice["choice_seq"],
                        "document_sha256": choice["document_sha256"],
                    },
                }
            )
        return others

    def define(
        self,
        version_id: uuid.UUID,
        *,
        comparison_id: uuid.UUID,
        body: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._answering_held(body)
        with self.database.session(self.workspace_id) as connection, connection.transaction():
            return self._repository(connection).define(
                version_id,
                comparison_id=comparison_id,
                body=body,
                created_by=self.actor,
                catalogs=self.catalogs,
            )

    def _answering_held(self, body: Mapping[str, Any]) -> None:
        """Every model a definition names, an arm's or a person's outside the group, is recorded
        with the answering the contract and its manifest entry give it now: a definition that
        says otherwise could never run as it states itself (:meth:`_asking`)."""
        contract = decision_contract()
        for held in [*body["arms"].values(), *body["others"]]:
            config = held.get("provider_config")
            if config is None:
                continue
            try:
                spec = self.manifest.offered(person_role().chosen, config["model_id"])
            except ManifestError as exc:
                raise ComparisonRefused(
                    "answering_not_the_models", f"{config['model_id']} is not offered"
                ) from exc
            if held.get("answering") != contract.answering(spec):
                raise ComparisonRefused(
                    "answering_not_the_models",
                    f"{config['model_id']} is recorded with the order the contract and its "
                    "manifest entry ask it in",
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
        """Play every run that has no outcome yet, the protocol's number at a time: every
        anchor first, so each seed's routine run has recorded the group's choice points before any
        model is asked on that seed. Outcomes come back in the order ``run_ids`` names them."""
        at_once = protocol_value(self.catalogs, "runs_at_once")
        with self.database.session(self.workspace_id) as connection:
            repository = self._repository(connection)
            arms = repository._definition(comparison_id)["document"]["arms"]  # type: ignore[index]
            roles = {run_id: arms[repository._run(run_id)["arm"]]["role"] for run_id in run_ids}
        found: dict[uuid.UUID, dict] = {}
        for first in (True, False):
            wave = [run_id for run_id in run_ids if (roles[run_id] in ANCHOR_ROLES) == first]
            with ThreadPoolExecutor(max_workers=at_once) as pool:
                found.update(
                    zip(
                        wave,
                        pool.map(lambda run_id: self.run(comparison_id, run_id), wave),
                        strict=True,
                    )
                )
        return [found[run_id] for run_id in run_ids]

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
            reserved = repository._run(run_id)
            arm = reserved["arm"]
            if definition_version(definition) == 2:
                anchors = self._anchor_statuses(repository, comparison_id, definition, reserved)
                if None in anchors:
                    raise ComparisonRefused(
                        "anchors_first",
                        "a model run starts once both anchors of its seed have completed",
                    )
                if any(status != "completed" for status in anchors):
                    return repository.finish(
                        comparison_id,
                        run_id,
                        self._failed(definition, arm, reserved["seed_digest"], ANCHOR_FAILED),
                    )
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
            played = play(
                plan, self._asking(plan, _recorded_answering(definition, arm)), on_minute=store
            )
        except _RunStopped as stop:
            outcome = self._failed(definition, arm, digest, stop.code)
        else:
            outcome = self._completed(plan, definition, arm, digest, played)
        with self.database.session(self.workspace_id) as connection, connection.transaction():
            return self._repository(connection).finish(comparison_id, run_id, outcome)

    @staticmethod
    def _anchor_statuses(
        repository: SocietyComparisonRepository,
        comparison_id: uuid.UUID,
        definition: Mapping[str, Any],
        reserved: Mapping[str, Any],
    ) -> tuple[str | None, ...]:
        """The status of each anchor run of this run's seed, None where it has no outcome yet; an
        anchor run itself waits for nothing, and reads as nothing to wait for."""
        arms = definition["arms"]
        if arms[reserved["arm"]]["role"] in ANCHOR_ROLES:
            return ()
        statuses = []
        for key in sorted(key for key, arm in arms.items() if arm["role"] in ANCHOR_ROLES):
            outcome = repository.outcome(run_id_for(comparison_id, key, reserved["seed_digest"]))
            statuses.append(None if outcome is None else outcome["status"])
        return tuple(statuses)

    def _asking(
        self, plan: RunPlan, recorded: Mapping[str, Mapping[str, Any] | None]
    ) -> _Asking | _Anchor:
        """What a run asks: nobody where no model decides for anybody in it, else every model
        that does, each checked against the manifest as the definition recorded it, its answering
        included where the definition records one (``recorded``, by model id): a model the
        contract and manifest would now ask in another order, or by another mechanism, is not the
        model the definition names, and the run stops before it asks anything."""
        deciders = [
            (plan.decider, plan.provider_config),
            *((held["decider"], held["provider_config"]) for held in plan.others.values()),
        ]
        configs = [config for decider, config in deciders if decider["kind"] == "model"]
        if not configs:
            return _Anchor()
        if self.client is None:
            raise _RunStoppedBeforeStart("provider_credential_absent")
        models: dict[str, tuple[ModelSpec, AnsweringMechanism]] = {}
        for config in configs:
            assert config is not None
            try:
                spec = self.manifest.offered(person_role().chosen, config["model_id"])
            except ManifestError:
                raise _RunStoppedBeforeStart("model_no_longer_offered") from None
            mechanism = plan.contract.mechanism_for(spec)
            held = recorded.get(spec.model_id)
            if (
                spec.provider != config["provider"]
                or mechanism is None
                or mechanism.value != config["mechanism"]
                or config["prompt_version"] != PROMPT_VERSION
                or (held is not None and plan.contract.answering(spec) != dict(held))
            ):
                raise _RunStoppedBeforeStart("provider_configuration_changed")
            models[spec.model_id] = (spec, mechanism)

        def model_of(subject: str) -> str:
            _decider, config = plan.decider_for(subject)
            assert config is not None, "only a person a model decides for is asked"
            return str(config["model_id"])

        return _Asking(
            self.client.with_policy(self.policy_for(self.workspace_id)),
            self.manifest,
            plan.contract,
            models,
            model_of,
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

    def _catalogs_for(self, definition: Mapping[str, Any]) -> ComparisonCatalogs:
        """The catalogs a run of ``definition`` is scored under: the runner's own when they are
        the versions the definition recorded, else those versions as committed."""
        versions = definition["scoring"]["catalogs"]["versions"]
        if dict(self.catalogs.versions) == dict(versions):
            return self.catalogs
        return load_comparison_catalogs(versions=versions)

    def _completed(
        self, plan: RunPlan, definition: Mapping[str, Any], arm: str, digest: str, played: PlayedRun
    ) -> dict:
        # What the group's asking took, and apart, what asking everybody else took.
        grouped = [
            receipt
            for receipt in played.receipts
            if plan.group is None or receipt["subject_id"] in plan.group
        ]
        outside = [
            receipt
            for receipt in played.receipts
            if plan.group is not None and receipt["subject_id"] not in plan.group
        ]
        calls = call_facts(grouped) if plan.decider["kind"] == "model" else None
        others_calls = call_facts(outside) if outside else None
        return run_outcome(
            plan,
            definition,
            arm,
            digest,
            played,
            calls,
            self._catalogs_for(definition),
            others_calls=others_calls,
        )
