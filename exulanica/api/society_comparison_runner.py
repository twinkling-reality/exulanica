"""Trusted execution of a comparison: every run, minutes back to back, models asked as the host
asks them.

A comparison is defined by one path (:mod:`exulanica.api.society_comparison_start`), whether the
local command (``python -m exulanica.orchestration.compare``) defines and runs it or a world's
owner starts it from the application, which a host's comparison worker then runs
(:mod:`exulanica.api.society_comparison_worker`). The runner plays each run through
:func:`exulanica.world.society_comparison.play`, under the decision role its definition's
contract names. Every subject a model decides for, the group under a model arm and anybody outside
it whose world's owner chose a model, is asked as the host's playback asks one whose owner chose a
model, save that rules which would change a question fail the run where the host leaves those
people to their routine, and that an ask ends by the contract's deadline alone, with no lease to
end within: the workspace's rules judge the fixed description and every label once a minute before
anybody is asked, for each model in one pass, a label they would change is left out
(:func:`~exulanica.api.decision_host.sendable_labels`), and each is asked by
:func:`~exulanica.api.decision_host.ask`, through the one client, with no database connection held
while anybody is asked. Each minute's receipts are appended as they are paid for, and a run ends in
one outcome: completed, with its minutes' digests and the score's terms, or failed by name.

A seed's anchors run before any model run of it, and a model run starts only once both of its
seed's anchors completed: one refused by name while either has no outcome (``anchors_first``), and
closed as failed before anything is asked when either failed (``anchor_failed``), since its score
could never be read. The routine's run records its choice points for the group, the denominator
every rate of what a model answered on that seed is read over. Where everybody outside the group
follows their routine, as a judged comparison requires, the anchors ask nobody, so that
denominator is fixed before any model is asked and no model's answers move it; in a development
comparison with a model outside the group, the anchors ask it too, and the served result says so.

What makes a run fail rather than complete is the host, never the model: a process budget that no
longer fits one ask of the arm's model, a bound the comparison was started under that no longer
fits one ask or refused a call's reservation, a provider or credential the process refuses, a model
the manifest no longer offers, rules that would change the question itself, or a request the rules
refused. A
score that counted such turns would describe the host. The local command's whole process budget,
``EXULANICA_BUDGET_USD``, is the comparison's: it keeps none of it back for other work, as the host
keeps a share, because the command's process does nothing else. A comparison started from the
application runs under the bound its owner stated, a part of the host's process budget
(:class:`~exulanica.models.budget.BoundedBudget`), and leaves the share the contract keeps for the
host's other work. The world's hour bounds on a live world's decisions do not apply: a comparison
writes nothing the live world reads.
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

import psycopg

from exulanica.api.decision_host import RoleAsk, ask, ask_bound_usd, sendable_labels, share_kept
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.db.session import Database
from exulanica.models.budget import BoundedBudget
from exulanica.models.client import ModelClient
from exulanica.models.errors import ManifestError
from exulanica.models.manifest import AnsweringMechanism, Manifest, ModelSpec
from exulanica.models.policy import HostedRequestPolicy
from exulanica.models.usage import usd_string
from exulanica.selection.validation import Session
from exulanica.world.decision_roles import DecisionRole, RoleOption, decision_roles
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_catalogs import ComparisonCatalogs, load_comparison_catalogs
from exulanica.world.society_comparison import (
    PlayedRun,
    ReplayMismatch,
    RunPlan,
    plan_role,
    play,
)
from exulanica.world.society_comparison_drawing import (
    DrawingCorrupt,
    decode,
    drawing_sha256,
    encode,
)
from exulanica.world.society_comparison_repository import (
    SocietyComparisonRepository,
    run_id_for,
    seed_digest,
)
from exulanica.world.society_comparison_result import (
    FAILURE_PROFILE,
    REPLAY_PROFILE,
    ComparisonRefused,
    definition_version,
    protocol_value,
    replay_document,
    run_outcome,
    verified_replay,
)
from exulanica.world.society_comparison_verdict import ANCHOR_ROLES
from exulanica.world.society_decision_contract import DecisionContract
from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository
from exulanica.world.society_repository import SocietyRepository

__all__ = [
    "BOUND_BEFORE_SEED",
    "BOUND_SPENT",
    "PEOPLE",
    "RUN_FAILURE_CODES",
    "ClaimLost",
    "ComparisonArm",
    "HostStopping",
    "RunHost",
    "SocietyComparisonRunner",
    "call_facts",
]

_LOG = logging.getLogger(__name__)
#: Every code a failed run's outcome records. Each says the host, not the model, ended the run's
#: asking: a budget that no longer fits one ask, the bound a comparison was started under that no
#: longer fits one ask or refused a call, a provider or a credential the process refuses, a model
#: the manifest no longer offers, serves from another provider or asks otherwise than the definition
#: recorded, rules that would change the question itself, or a request the rules refused; a run the
#: process stopped part way, found with receipts and no outcome; a run a host could not play because
#: the society's inputs are no longer available to it; one the comparison's claims closed before it
#: was played, after hosts that claimed it kept stopping; or a model run whose seed's anchors did
#: not complete, closed before it asks. A receipt whose reason is one of them stops its run there;
#: every other reason a turn was not the model's is the model's own, and is reported beside the
#: score. The page has words for each.
RUN_FAILURE_CODES: Final = frozenset(
    {
        "anchor_failed",
        "comparison_bound_before_seed",
        "comparison_bound_spent",
        "comparison_stopped",
        "input_unavailable",
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
#: Why a seed's model runs are closed before they ask: what was left of the comparison's bound did
#: not hold what one seed like it typically costs and what its runs can hold reserved at once, so
#: the comparison stopped between seeds and kept every seed it had played.
BOUND_BEFORE_SEED: Final = "comparison_bound_before_seed"
#: Why a run failed before anybody was asked in a minute: the rules would change the question.
QUESTION_CHANGED: Final = "question_changed_by_rules"
#: Why a model run is closed before it asks: an anchor of its seed failed, so it has no score.
ANCHOR_FAILED: Final = "anchor_failed"
#: Why a run stopped: the bound its comparison was started under no longer fits one ask of the
#: dearest model due before a minute, or refused a call's reservation during one.
BOUND_SPENT: Final = "comparison_bound_spent"
#: Why a run a host could not play was closed: the society's inputs are no longer available to it.
INPUT_UNAVAILABLE: Final = "input_unavailable"
#: The word the subjects of a comparison's groups are known by: a society's people. The role a
#: comparison defines by, unless it names another, is the one registered role deciding for them.
PEOPLE: Final = "person"


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


class ClaimLost(Exception):
    """The host playing a comparison no longer holds its claim: another host took it over after
    its lease ran out. The run is left as it stands, with no outcome, for that host to close."""


class HostStopping(Exception):
    """The host playing a comparison is stopping. A run that has asked nothing yet is left with
    no outcome, for the next claim to play from its start; one that has is closed as
    ``interrupted``, since its hour cannot be played again under the receipts it holds."""


@dataclass(frozen=True)
class RunHost:
    """What the host that claimed a comparison asks of each run it plays.

    ``minute`` is called before each run and after each of its minutes: it renews the host's
    claim, and raises :class:`ClaimLost` once the host no longer holds it. ``stopping`` says the
    host is stopping (:class:`HostStopping`). ``recorded`` is called with the connection whose
    transaction records a run's outcome, before it commits, so what the host keeps of its progress
    is written with the outcome or not at all.
    """

    minute: Callable[[], None]
    stopping: Callable[[], bool]
    recorded: Callable[[psycopg.Connection], None]
    #: Whether a seed's model runs, by id, may start: asked before each seed's model runs, whose
    #: anchors have played. A seed not admitted closes it and every later seed's model runs as
    #: :data:`BOUND_BEFORE_SEED`, asking nothing. Left out, every seed is admitted.
    admit: Callable[[Sequence[uuid.UUID]], bool] = field(default=lambda _runs: True)


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
    """A run's asking, minute by minute, as the host asks a chosen subject's model: one or more
    models, each subject asked of the model that decides for them, under the run's role."""

    def __init__(
        self,
        client: ModelClient,
        manifest: Manifest,
        contract: DecisionContract,
        models: Mapping[str, tuple[ModelSpec, AnsweringMechanism]],
        model_of: Callable[[str], str],
        *,
        role: DecisionRole,
        bound: BoundedBudget | None = None,
        run_bound: BoundedBudget | None = None,
        keeps_share: bool = False,
    ) -> None:
        self.client = client
        self.manifest = manifest
        self.contract = contract
        #: Each model the run asks, by identifier, and how it is asked.
        self.models = models
        #: The model that decides for a subject a model decides for, by subject id.
        self.model_of = model_of
        self.role = role
        #: The bound a comparison started from the application runs under, or None for the local
        #: command, whose whole process budget is the comparison's.
        self.bound = bound
        #: This run's own part of that bound, which every call of the run is reserved through, so
        #: what the bound refused is known run by run, whatever the other runs sharing it do.
        self.run_bound = run_bound
        #: The part of the process's budget and calls the asks leave for its other work: the
        #: contract's share where the process does other work, nothing for the local command.
        self.keep = share_kept(client.budget, contract) if keeps_share else (Decimal(0), 0)

    def offerable(
        self, tick: int, due: Mapping[str, Sequence[RoleOption]]
    ) -> dict[str, frozenset[str]]:
        asked = sorted({self.model_of(subject) for subject in due})
        for model_id in asked:
            refused = self.client.refusals.get(self.models[model_id][0].provider)
            if refused is not None:
                raise _RunStopped(refused)
        # Room is judged as the host judges it, on what is spent: one ask of the dearest model
        # due must fit, beside the part kept for other work where the process does any.
        budget = self.client.budget
        bound_of = {
            model_id: ask_bound_usd(self.role, budget, self.models[model_id][0], self.contract)
            for model_id in asked
        }
        need = max(bound_of.values())
        calls = self.contract.value("answer_attempts_maximum")
        keep_usd, keep_calls = self.keep
        left_usd = budget.ceiling_usd - budget.spent_usd
        left_calls = budget.max_calls - budget.billed_calls
        if left_usd < need or left_calls < calls:
            raise _RunStopped("process_budget_spent")
        if left_usd - keep_usd < need or left_calls - keep_calls < calls:
            raise _RunStopped("process_share_spent")
        # The bound is judged by the same rule on what the comparison spent: a minute is asked
        # only while one ask of its dearest model fits what is left of it. Every call's
        # reservation is then held to the bound by the bound itself.
        if self.bound is not None and (
            self.bound.ceiling_usd - self.bound.spent_usd < need
            or self.bound.max_calls - self.bound.billed_calls < calls
        ):
            raise _RunStopped(BOUND_SPENT)
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
            found = sendable_labels(self.role, self.client, model_id, labels)
            if found is None:
                raise _RunStopped(QUESTION_CHANGED)
            sendable[model_id] = found
        return {subject: sendable[self.model_of(subject)] for subject in due}

    def bound_refused(self) -> bool:
        """Whether the bound refused a call of this run: a receipt says only that a budget
        refused an ask, and the bound is a part of the process's budget."""
        return self.run_bound is not None and self.run_bound.refusals > 0

    def answers(self, requests: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        ends_at = time.monotonic() + self.contract.value("decision_deadline_ms") / 1000
        workers = max(1, min(self.contract.value("concurrent_calls_maximum"), len(requests)))
        keep_usd, keep_calls = self.keep
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(
                    ask,
                    self.client,
                    RoleAsk(
                        self.role, request, *self.models[request["provider_config"]["model_id"]]
                    ),
                    self.contract,
                    ends_at,
                    keep_usd=keep_usd,
                    keep_calls=keep_calls,
                )
                for request in requests
            ]
            results = []
            for future in futures:
                try:
                    results.append(future.result())
                except Exception:
                    # An error before anything was sent: an error in an attempt is ask's, which
                    # keeps what the attempts cost. Never an exception's text, which may carry
                    # request bytes or a credential.
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

    def bound_refused(self) -> bool:
        return False


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
    #: The decision role this runner defines comparisons for: the one registered role deciding for
    #: a society's people, unless its caller names another. A run asks the role its definition's
    #: contract names (:func:`~exulanica.world.society_comparison.plan_role`), whichever this is.
    decision_role: DecisionRole = field(
        default_factory=lambda: decision_roles().deciding_for(PEOPLE)
    )
    #: The bound a comparison started from the application runs under, a part of the process's
    #: budget; None for the local command, whose whole process budget is the comparison's.
    bound: BoundedBudget | None = None
    #: Whether its asks leave the contract's share of the process's budget for other work, as a
    #: host serving the application does; the local command's process does no other work.
    keeps_share: bool = False

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
        role = self.decision_role
        contract = role.contract()
        try:
            spec = self.manifest.offered(role.chosen, arm.model_id)
        except ManifestError as exc:
            raise ValueError(
                f"{arm.model_id} is not offered for a {role.subject}'s decisions"
            ) from exc
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
            "prompt_version": role.prompt_version,
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

    def _choices(
        self, version_id: uuid.UUID, connection: Any = None
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """The version's people, by subject id, and every choice its owner made for them, in
        order, read on ``connection`` or on a session of the runner's own."""
        if connection is None:
            with self.database.session(self.workspace_id) as held:
                return self._choices(version_id, held)
        row = self._repository(connection).society._row(version_id)
        if row is None:
            raise ComparisonRefused("society_unavailable", "the version holds no society")
        choices = SocietyModelChoiceRepository(
            connection, self.workspace_id, world_id=self.world_id
        ).history(version_id, self.decision_role)
        return sorted(person["id"] for person in row["state"]["inhabitants"]), choices

    def group_of_choice(
        self, version_id: uuid.UUID, choice_seq: int, *, connection: Any = None
    ) -> dict[str, Any]:
        """The group one of the owner's choices named, as a definition's body states it."""
        _people, choices = self._choices(version_id, connection)
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

    def others_for(
        self, version_id: uuid.UUID, group: Sequence[str] | None, *, connection: Any = None
    ) -> list[dict]:
        """Everybody outside ``group`` and what decides for them in every arm: the model the
        owner's latest choice for them names, asked as the host asks it, or their routine. A model
        the owner chose that this server cannot ask as the contract asks it is refused by name,
        since every arm would ask it."""
        people, choices = self._choices(version_id, connection)
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
        connection: Any = None,
    ) -> dict[str, Any]:
        """Record ``body`` as a comparison of this version's society asking this runner's role,
        in a transaction of its own, or inside the caller's on ``connection``."""
        self._answering_held(body)
        if connection is None:
            with self.database.session(self.workspace_id) as held:
                return self.define(
                    version_id, comparison_id=comparison_id, body=body, connection=held
                )
        with connection.transaction():
            return self._repository(connection).define(
                version_id,
                comparison_id=comparison_id,
                body=body,
                created_by=self.actor,
                role=self.decision_role,
                catalogs=self.catalogs,
            )

    def _answering_held(self, body: Mapping[str, Any]) -> None:
        """Every model a definition names, an arm's or a person's outside the group, is recorded
        with the answering the contract and its manifest entry give it now: a definition that
        says otherwise could never run as it states itself (:meth:`_asking`)."""
        contract = self.decision_role.contract()
        for held in [*body["arms"].values(), *body["others"]]:
            config = held.get("provider_config")
            if config is None:
                continue
            try:
                spec = self.manifest.offered(self.decision_role.chosen, config["model_id"])
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

    def reserve_all(
        self, comparison_id: uuid.UUID, seeds: Sequence[str], *, connection: Any = None
    ) -> list[uuid.UUID]:
        """Every run of the comparison, one per arm and seed, reserved before anything is asked,
        in a transaction of its own, or inside the caller's on ``connection``."""
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

    def run_all(
        self,
        comparison_id: uuid.UUID,
        run_ids: Sequence[uuid.UUID],
        *,
        host: RunHost | None = None,
    ) -> list[dict]:
        """Play every run that has no outcome yet, the protocol's number at a time, a seed's
        anchors before its model runs, so each seed's routine run has recorded the group's choice
        points before any model is asked on that seed. Under a claiming ``host``, the seeds are
        played one after another in the order the definition commits them, and before a seed's
        runs start the host admits them or stops the comparison there (:attr:`RunHost.admit`): a
        stop keeps every seed already played, and closes that seed's runs and every later seed's
        as :data:`BOUND_BEFORE_SEED`, asking nothing. The local command plays with none, admits
        every seed, and plays every anchor, then every model run, each in one wave. Outcomes come
        back in the order ``run_ids`` names them."""
        at_once = protocol_value(self.catalogs, "runs_at_once")
        with self.database.session(self.workspace_id) as connection:
            repository = self._repository(connection)
            definition = repository._definition(comparison_id)["document"]  # type: ignore[index]
            arms = definition["arms"]
            reserved = {run_id: repository._run(run_id) for run_id in run_ids}
            # A run that holds receipts was stopped part way: it asks nothing more, and is closed
            # as interrupted when it is played, whatever the bound holds.
            resumed = {row["run_id"] for row in repository.open_runs(comparison_id) if row["asked"]}
        roles = {run_id: arms[row["arm"]]["role"] for run_id, row in reserved.items()}
        found: dict[uuid.UUID, dict] = {}

        def played(wave: Sequence[uuid.UUID]) -> None:
            with ThreadPoolExecutor(max_workers=at_once) as pool:
                found.update(
                    zip(
                        wave,
                        pool.map(lambda run_id: self.run(comparison_id, run_id, host=host), wave),
                        strict=True,
                    )
                )

        anchors: dict[str, list[uuid.UUID]] = {digest: [] for digest in definition["seeds"]}
        models: dict[str, list[uuid.UUID]] = {digest: [] for digest in definition["seeds"]}
        for run_id in run_ids:
            held = anchors if roles[run_id] in ANCHOR_ROLES else models
            held[reserved[run_id]["seed_digest"]].append(run_id)
        closing: list[uuid.UUID] = []
        if host is None:
            # The local command admits every seed, so each kind of run shares one wave.
            played([run_id for wave in anchors.values() for run_id in wave])
            played([run_id for wave in models.values() for run_id in wave])
        else:
            for digest in definition["seeds"]:
                seed = [*anchors[digest], *models[digest]]
                if not seed:
                    continue
                fresh = [run_id for run_id in seed if run_id not in resumed]
                if not closing and (not fresh or host.admit(fresh)):
                    played(anchors[digest])
                    played(models[digest])
                else:
                    played([run_id for run_id in seed if run_id in resumed])
                    closing.extend(fresh)
        if closing:
            self.fail_open(comparison_id, dict.fromkeys(closing, BOUND_BEFORE_SEED))
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

        A run that holds receipts and no outcome was stopped part way, by a crash or a killed
        process. Its hour is not played again, which would ask the models again for receipts it
        already holds: before anything is asked, it is recorded as failed, ``interrupted``, as
        the host closes what a stopped claim left open, and running it again is a new comparison.
        Under a claiming ``host``, the claim is renewed before the run and after each minute, a
        host that is stopping closes the run as ``interrupted`` at its next minute, a run whose
        society's inputs are no longer available is closed as ``input_unavailable``, and every
        outcome is recorded in a transaction the host also writes its progress in
        (:attr:`RunHost.recorded`).
        """
        if host is not None:
            if host.stopping():
                raise HostStopping
            host.minute()

        def recorded(connection: psycopg.Connection, outcome: dict) -> dict:
            """An outcome recorded on ``connection``, in its open transaction, which the claiming
            host's progress joins."""
            if host is not None:
                host.recorded(connection)
            return outcome

        with self.database.session(self.workspace_id) as connection, connection.transaction():
            repository = self._repository(connection)
            done = repository.outcome(run_id)
            if done is not None:
                return done
            if repository.stored(run_id):
                reserved = repository._run(run_id)
                definition = repository._definition(comparison_id)["document"]  # type: ignore[index]
                return recorded(
                    connection,
                    repository.finish(
                        comparison_id,
                        run_id,
                        self._failed(
                            definition, reserved["arm"], seed_digest(reserved["seed"]), INTERRUPTED
                        ),
                    ),
                )
            try:
                plan, definition = repository.plan(comparison_id, run_id)
            except UnavailableSocietyInput:
                if host is None:
                    raise
                reserved = repository._run(run_id)
                definition = repository._definition(comparison_id)["document"]  # type: ignore[index]
                return recorded(
                    connection,
                    repository.finish(
                        comparison_id,
                        run_id,
                        self._failed(
                            definition, reserved["arm"], reserved["seed_digest"], INPUT_UNAVAILABLE
                        ),
                    ),
                )
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
                    return recorded(
                        connection,
                        repository.finish(
                            comparison_id,
                            run_id,
                            self._failed(definition, arm, reserved["seed_digest"], ANCHOR_FAILED),
                        ),
                    )
        digest = seed_digest(plan.seed)

        asking: _Asking | _Anchor | None = None
        stored: list[int] = []

        def store(tick: int, requests: Sequence[dict], receipts: Sequence[dict]) -> None:
            if receipts:
                with (
                    self.database.session(self.workspace_id) as connection,
                    connection.transaction(),
                ):
                    self._repository(connection).append(comparison_id, run_id, requests, receipts)
                stored.append(tick)
            stopped = next(
                (r["reason"] for r in receipts if r["reason"] in RUN_FAILURE_CODES), None
            )
            if stopped == "process_budget_spent" and asking is not None and asking.bound_refused():
                # The bound refused one of this run's reservations: calls of this minute, or of
                # another run sharing the bound, held what was left. The receipt names a budget
                # that refused, and the run the bound it was started under.
                stopped = BOUND_SPENT
            if stopped is not None:
                raise _RunStopped(stopped)
            if host is not None:
                host.minute()
                if host.stopping():
                    if stored:
                        raise _RunStopped(INTERRUPTED)
                    raise HostStopping

        try:
            asking = self._asking(plan, _recorded_answering(definition, arm))
            played = play(plan, asking, on_minute=store)
        except _RunStopped as stop:
            outcome = self._failed(definition, arm, digest, stop.code)
        else:
            outcome = self._completed(plan, definition, arm, digest, played)
        with self.database.session(self.workspace_id) as connection, connection.transaction():
            return recorded(
                connection, self._repository(connection).finish(comparison_id, run_id, outcome)
            )

    def draw_all(
        self,
        comparison_id: uuid.UUID,
        *,
        stopping: Callable[[], bool] | None = None,
    ) -> int:
        """Draw every completed run of the comparison not drawn yet under this code
        (:meth:`draw`), one after another, whichever claim or process played it, and say how many
        are stored. Asked once a comparison's runs are played, and by a host once it has finished
        its start: a town's drawing takes a replay of seconds, which no claim's lease is held for,
        and a run left undrawn is read by a replay as before. A run that cannot be drawn is logged
        and the rest are drawn; ``stopping`` ends it between runs."""
        with self.database.session(self.workspace_id) as connection:
            completed = [
                run["run_id"]
                for run in self._repository(connection).runs(comparison_id)
                if run.get("status") == "completed"
            ]
        stored = 0
        for run_id in completed:
            if stopping is not None and stopping():
                break
            try:
                stored += self.draw(comparison_id, run_id)
            except Exception:
                _LOG.exception("A completed comparison run could not be drawn; reads replay it")
        return stored

    def draw(self, comparison_id: uuid.UUID, run_id: uuid.UUID) -> bool:
        """Replay a completed run from what it stored, verify it against its outcome, and store
        the drawing the page reads (:mod:`exulanica.world.society_comparison_drawing`), under the
        digest of the code that drew it; say whether one is stored.

        Asked once a run's outcome is recorded (:meth:`draw_all`), off the request path, so a read
        serves the drawing where it would otherwise replay the run. Its inputs are authorised
        first, as a run's are: a run whose inputs lost their rights is not drawn. A replay that
        differs from its record is logged and nothing is stored, so a read replays it and refuses
        it by name. The run's outcome stands whatever happens here."""
        drawing = drawing_sha256(REPLAY_PROFILE)
        try:
            with (
                self.database.session(self.workspace_id) as connection,
                connection.transaction(),
            ):
                repository = self._repository(connection)
                outcome = repository.outcome(run_id)
                if outcome is None or outcome["status"] != "completed":
                    return False
                found = repository.drawing(run_id, drawing)
                if found is not None:
                    try:
                        decode(found)
                    except DrawingCorrupt:
                        # Appended rows are never changed: reads replay this run instead.
                        _LOG.error("A comparison run's stored drawing is not the drawing it names")
                        return False
                    return True
                plan, definition = repository.plan(comparison_id, run_id)
                stored = repository.stored(run_id)
        except UnavailableSocietyInput:
            return False
        try:
            played = verified_replay(plan, stored, outcome)
        except ReplayMismatch:
            _LOG.error("A completed comparison run's replay differs from its record; not drawn")
            return False
        encoded = encode(
            replay_document(
                plan, definition, outcome["arm"], outcome["seed_digest"], played, model_name=str
            )
        )
        with self.database.session(self.workspace_id) as connection, connection.transaction():
            self._repository(connection).store_drawing(comparison_id, run_id, drawing, encoded)
        return True

    def fail_open(self, comparison_id: uuid.UUID, codes: Mapping[uuid.UUID, str]) -> None:
        """Record each run of ``codes`` that has no outcome yet as failed by its code, asking
        nothing: what a host closing a comparison does with the runs it will never play."""
        for code in codes.values():
            if code not in RUN_FAILURE_CODES:
                raise ValueError(f"a run fails only by a stated code, not {code!r}")
        with self.database.session(self.workspace_id) as connection, connection.transaction():
            repository = self._repository(connection)
            definition = repository._definition(comparison_id)["document"]  # type: ignore[index]
            for run_id, code in codes.items():
                if repository.outcome(run_id) is not None:
                    continue
                reserved = repository._run(run_id)
                repository.finish(
                    comparison_id,
                    run_id,
                    self._failed(definition, reserved["arm"], reserved["seed_digest"], code),
                )

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
        role = plan_role(plan)
        models: dict[str, tuple[ModelSpec, AnsweringMechanism]] = {}
        for config in configs:
            assert config is not None
            try:
                spec = self.manifest.offered(role.chosen, config["model_id"])
            except ManifestError:
                raise _RunStoppedBeforeStart("model_no_longer_offered") from None
            mechanism = plan.contract.mechanism_for(spec)
            held = recorded.get(spec.model_id)
            if (
                spec.provider != config["provider"]
                or mechanism is None
                or mechanism.value != config["mechanism"]
                or config["prompt_version"] != role.prompt_version
                or (held is not None and plan.contract.answering(spec) != dict(held))
            ):
                raise _RunStoppedBeforeStart("provider_configuration_changed")
            models[spec.model_id] = (spec, mechanism)

        def model_of(subject: str) -> str:
            _decider, config = plan.decider_for(subject)
            assert config is not None, "only a subject a model decides for is asked"
            return str(config["model_id"])

        client = self.client.with_policy(self.policy_for(self.workspace_id))
        run_bound = (
            None
            if self.bound is None
            else BoundedBudget(
                self.bound, ceiling_usd=self.bound.ceiling_usd, max_calls=self.bound.max_calls
            )
        )
        return _Asking(
            client if run_bound is None else client.with_bound(run_bound),
            self.manifest,
            plan.contract,
            models,
            model_of,
            role=role,
            bound=self.bound,
            run_bound=run_bound,
            keeps_share=self.keeps_share,
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
