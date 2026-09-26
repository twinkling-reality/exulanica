"""The host's playback asking, before a purposeful society's minute, each chosen person's model.

A person in a purposeful society (``exulanica-society/v2``) whose world's owner chose a model for
them is asked of that model at the planner's own choice point, by :class:`PersonDecisionHost`:
only in a workspace the host's environment lists, within the decision contract's bounds per world
and hour, within the share of the process's model budget the contract lets people's decisions
spend, and with no connection held while a model is asked.

What the host cannot ask it decides before reserving anything, and writes nothing: a host with no
client or with its budget or share spent (:func:`host_refusal`), a person whose chosen model it
may not ask here (:func:`model_refusal`), and a question the workspace's rules would change
(:func:`question_refusal`). The models route says why, for the host and for each choice. Every
person it does reserve a request for gets a receipt, whatever happened: an answer, or the reason
there is none, and then the routine decides that turn. A request left without one, by
a host stopped between reserving and recording, is closed by name at the host's next minute.
The page never asks a model; nothing here is reachable from a route.
"""

from __future__ import annotations

import dataclasses
import logging
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, TypeVar

import psycopg

from exulanica.api.society_runtime import SocietyRuntime
from exulanica.db.session import Database
from exulanica.errors import PrivacyAdmissionError
from exulanica.models.budget import BudgetGuard
from exulanica.models.choice import ChoiceRefused
from exulanica.models.client import PROVIDER_CREDENTIAL_ABSENT, ModelClient
from exulanica.models.errors import (
    BudgetExceededError,
    BudgetShareExceeded,
    ManifestError,
    ModelError,
    ModelUnavailableError,
    ProviderRefused,
    TransportError,
)
from exulanica.models.manifest import AnsweringMechanism, Manifest, ModelSpec, Role
from exulanica.models.policy import HostedRequestPolicy, NoHostedRequestPolicy
from exulanica.models.usage import CallUsage, usd_string
from exulanica.selection.calls import CallLog
from exulanica.selection.validation import Session
from exulanica.world.society import asked_again_after_a_race, society_state_sha256
from exulanica.world.society_controls import LEASE_SECONDS, ControlClaim
from exulanica.world.society_decision_contract import (
    CHOICE_DESCRIPTION,
    INSTRUCTION,
    PROMPT_VERSION,
    DecisionContract,
    DecisionOption,
    at_choice_point,
    choice_options,
    choice_request,
    decision_contract,
    decision_messages,
)
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository
from exulanica.world.society_planner import PURPOSEFUL_PROFILE
from exulanica.world.society_repository import SocietyRepository

__all__ = [
    "HOST_REFUSALS",
    "MODEL_REFUSALS",
    "PersonAsk",
    "PersonDecisionHost",
    "answer_tokens",
    "ask_bound_usd",
    "ask_person",
    "host_refusal",
    "model_refusal",
    "question_refusal",
    "share_kept",
    "smallest_ask_usd",
    "world_hour",
]

_LOG = logging.getLogger(__name__)
_T = TypeVar("_T")
#: Why a host asks no model for a workspace's people at all, by code; the page has words for each.
HOST_REFUSALS: Final = frozenset(
    {
        "models_not_run_here",
        "provider_credential_absent",
        "process_budget_spent",
        "process_share_spent",
    }
)
#: Why a person's chosen model is not asked here while the host asks others; the page has words.
MODEL_REFUSALS: Final = frozenset(
    {
        "model_no_longer_offered",
        "provider_changed",
        "provider_not_admitted",
        "provider_credential_absent",
        "process_budget_spent",
        "process_share_spent",
        "question_changed_by_rules",
    }
)
#: What a person is told when an answer was not one of the offered actions, before the one retry.
_NOT_OFFERED: Final = (
    "That answer is not one of the offered actions. Choose exactly one of them, as it is written."
)


def _failure_reason(exc: BaseException) -> str:
    """How a failure that ended a person's call is recorded, by the error that ended it."""
    if isinstance(exc, ProviderRefused):
        return exc.reason
    if isinstance(exc, BudgetShareExceeded):
        return "process_share_spent"
    if isinstance(exc, BudgetExceededError):
        return "process_budget_spent"
    if isinstance(exc, ModelUnavailableError):
        return "model_unavailable"
    if isinstance(exc, TransportError):
        return "model_timed_out" if exc.timed_out else "model_call_failed"
    if isinstance(exc, (PrivacyAdmissionError, NoHostedRequestPolicy)):
        return "request_refused"
    if isinstance(exc, ManifestError):
        return "model_no_longer_offered"
    return "model_call_failed"


def answer_tokens(spec: ModelSpec) -> int | None:
    """The most a person's model may write in one answer: its manifest default, which leaves a
    reasoning model room to reason before it answers, and never below its floor."""
    if spec.default_max_tokens is None:
        return spec.min_max_tokens
    return max(spec.default_max_tokens, spec.min_max_tokens or 0)


def share_kept(budget: BudgetGuard, contract: DecisionContract) -> tuple[Decimal, int]:
    """The part of the process's budget people's decisions must leave for its other work."""
    percent = contract.value("process_reserve_percent")
    return (
        (budget.ceiling_usd * percent / 100).quantize(Decimal("0.000001")),
        budget.max_calls * percent // 100,
    )


def _askable(
    manifest: Manifest, contract: DecisionContract, model_id: str
) -> tuple[ModelSpec, AnsweringMechanism] | None:
    try:
        spec = manifest.offered(Role.SOCIETY_DECISION, model_id)
    except ManifestError:
        return None
    mechanism = contract.mechanism_for(spec)
    return None if mechanism is None else (spec, mechanism)


def ask_bound_usd(budget: BudgetGuard, spec: ModelSpec, contract: DecisionContract) -> Decimal:
    """The most one ask of ``spec`` may reserve, whatever the person's situation.

    Every answer the contract allows, each reserved as the client reserves a call, by the prompt's
    characters and the model's answer bound. The prompt is bounded by the instruction, the note a
    retry adds and twice the largest situation a request may carry, which covers the situation's
    rendering and each message's framing; tests/test_society_person_decisions.py holds the asks
    the small square makes under it.
    """
    prompt_chars = (
        len(INSTRUCTION) + len(_NOT_OFFERED) + 2 * contract.value("context_bytes_maximum")
    )
    return contract.value("answer_attempts_maximum") * budget.estimate_usd(
        spec, prompt_chars=prompt_chars, max_tokens=answer_tokens(spec) or 0
    )


def smallest_ask_usd(
    budget: BudgetGuard, manifest: Manifest, contract: DecisionContract
) -> Decimal | None:
    """The least that one ask of an offered model may need, the smallest ``ask_bound_usd``. A
    process whose remainder is under it can ask no person's model; None with none offered."""
    bounds = [
        ask_bound_usd(budget, spec, contract)
        for spec in manifest.offered_models(Role.SOCIETY_DECISION)
        if contract.mechanism_for(spec) is not None
    ]
    return min(bounds) if bounds else None


def _budget_refusal(budget: BudgetGuard, contract: DecisionContract, need: Decimal) -> str | None:
    """Whether what is left fits an ask needing ``need`` and every answer the contract allows.

    What is left is the ceiling less what is spent, and the call limit less the calls billed:
    never less what calls under way hold, which comes back when they are recorded. So a refusal is
    decided on money spent, whoever spent it, and spending only grows while the process runs: once
    refused, a model stays refused until the process restarts. ``process_budget_spent`` when the
    whole budget does not fit the ask; ``process_share_spent`` when it fits only by taking the part
    kept for the process's other work. A call under way can still leave an ask's own reservation
    no room, which its receipt names.
    """
    calls = contract.value("answer_attempts_maximum")
    left_usd = budget.ceiling_usd - budget.spent_usd
    left_calls = budget.max_calls - budget.billed_calls
    if left_calls < calls or left_usd < need:
        return "process_budget_spent"
    keep_usd, keep_calls = share_kept(budget, contract)
    if left_calls - keep_calls < calls or left_usd - keep_usd < need:
        return "process_share_spent"
    return None


def host_refusal(
    client: ModelClient | None, manifest: Manifest, contract: DecisionContract
) -> str | None:
    """Why this process asks no person's model at all, or None when it may ask them.

    A code from ``HOST_REFUSALS`` other than ``models_not_run_here``, which is the host's own
    listing: no client, or a budget whose remainder, by what is spent, fits no ask of any offered
    model (``smallest_ask_usd``), in the whole budget or once the part kept for the process's other
    work is set aside. Either holds until the process restarts.
    """
    if client is None:
        return PROVIDER_CREDENTIAL_ABSENT
    smallest = smallest_ask_usd(client.budget, manifest, contract)
    return None if smallest is None else _budget_refusal(client.budget, contract, smallest)


def model_refusal(
    client: ModelClient | None,
    manifest: Manifest,
    contract: DecisionContract,
    model: Mapping[str, str],
) -> str | None:
    """Why a person's chosen model is not asked here, or None when it may be.

    A code from ``MODEL_REFUSALS``: a model no longer offered or askable under the contract, a
    choice naming a provider the manifest no longer serves the model from, a provider this
    process refuses, or a budget whose remainder no longer fits one ask of this model, which
    holds until the process restarts. Each is decided before anything is reserved.
    """
    askable = _askable(manifest, contract, model["model_id"])
    if askable is None:
        return "model_no_longer_offered"
    spec, _mechanism = askable
    if spec.provider != model["provider"]:
        return "provider_changed"
    if client is None:
        return PROVIDER_CREDENTIAL_ABSENT
    refused = client.refusals.get(spec.provider)
    if refused is not None:
        return refused
    return _budget_refusal(client.budget, contract, ask_bound_usd(client.budget, spec, contract))


def question_refusal(client: ModelClient, model_id: str) -> str | None:
    """``question_changed_by_rules`` when the client's rules would change the question every
    person asked of ``model_id`` is sent, the choice's fixed description; else None.

    A saved name one of whose parts is a word of the description would, and every ask would then
    be refused as it left, every minute: so nobody is asked, nothing is written, and the models
    route names it for each choice of that model.
    """
    (kept,) = client.unchanged_by_policies(Role.SOCIETY_DECISION, model_id, [CHOICE_DESCRIPTION])
    return None if kept else "question_changed_by_rules"


def _sendable_labels(
    client: ModelClient, model_id: str, labels: Sequence[str]
) -> frozenset[str] | None:
    """The labels the client's rules send as they are for ``model_id``, judged in one pass with
    the choice's description; None when the rules would change the description.

    A place whose words a rule would change, a saved name that matches a catalog word, is left out
    rather than refusing the whole ask each minute; the person has fewer places to choose from.
    """
    kept = client.unchanged_by_policies(
        Role.SOCIETY_DECISION, model_id, [CHOICE_DESCRIPTION, *labels]
    )
    if not kept[0]:
        return None
    return frozenset(label for label, keep in zip(labels, kept[1:], strict=True) if keep)


def _only(labels: frozenset[str]) -> Callable[[Sequence[DecisionOption]], list[DecisionOption]]:
    """The options whose labels were judged sendable; one the judgement did not see is left out."""

    def offered(options: Sequence[DecisionOption]) -> list[DecisionOption]:
        return [option for option in options if option.label in labels]

    return offered


def _once_more_after_a_race(action: Callable[[], _T]) -> _T:
    """``action``, a whole transaction, asked again after a race between reading an input's
    stored bytes and taking the asset read lock (``asked_again_after_a_race``).

    A try that met it rolled back and holds nothing, and reserving and closing are each
    idempotent, so the next reads the bytes first. A race on the last try is raised, and the next
    claim closes what it left open. Recording an answer ends terminally instead (``finish``).
    """
    return asked_again_after_a_race(lambda _last_try: action())


@dataclass(frozen=True, slots=True)
class PersonAsk:
    """One reserved request, the model it asks and how: all a call needs, and no connection."""

    request: dict[str, Any]
    spec: ModelSpec
    mechanism: AnsweringMechanism


def ask_person(
    client: ModelClient,
    ask: PersonAsk,
    contract: DecisionContract,
    ends_at: float,
    *,
    keep_usd: Decimal = Decimal(0),
    keep_calls: int = 0,
) -> dict[str, Any]:
    """A person's answer, asked of the chosen model, as the result a receipt records.

    Asked by the model's own verified mechanism, at most ``answer_attempts_maximum`` times: an
    answer that is not one of the options is asked once more, telling the model so, and every
    other failure ends the ask. ``ends_at`` is the monotonic time the whole ask ends by, every
    attempt within it, however long it waited to start. ``keep_usd`` and ``keep_calls`` are the
    part of the process's budget it must leave. The record names every attempt in the execution
    record's words, whatever its outcome.
    """
    log = CallLog()
    charged: list[CallUsage] = []

    def heard(usage: CallUsage) -> None:
        log.attempt(usage)
        charged.append(usage)

    sender = client.with_attempts(heard)
    context = ask.request["context"]
    request = choice_request(context)
    first = decision_messages(context, ask.mechanism)
    messages = list(first)
    started = time.monotonic()
    status, reason, proposal, served = "rejected", "answer_not_offered", None, None
    answers = 0
    if ends_at - started <= 0:
        return _refused("no_time_to_ask")
    for _ in range(contract.value("answer_attempts_maximum")):
        remaining = ends_at - time.monotonic()
        if remaining <= 0:
            # No time left for the answer asked once more: nothing is sent for it.
            status, reason = "unavailable", "no_time_to_ask"
            break
        answers += 1
        try:
            chosen = sender.choose(
                Role.SOCIETY_DECISION,
                ask.spec.model_id,
                messages,
                request,
                mechanism=ask.mechanism,
                prompt_version=PROMPT_VERSION,
                timeout=remaining,
                max_tokens=answer_tokens(ask.spec),
                keep_usd=keep_usd,
                keep_calls=keep_calls,
            )
        except ChoiceRefused:
            messages = [*messages, {"role": "user", "content": _NOT_OFFERED}]
            continue
        except (ModelError, PrivacyAdmissionError, NoHostedRequestPolicy) as exc:
            status, reason = "unavailable", _failure_reason(exc)
            break
        except Exception:
            # Any other error ends the ask as a failed call, and every attempt it paid for stays in
            # the record rather than leaving with the exception. Never an exception's text, which
            # may carry request bytes or a credential.
            _LOG.error("A person's decision ask failed; the routine decides that turn")
            status, reason = "unavailable", "model_call_failed"
            break
        log.record(chosen.call)
        served = chosen.call.served_model_id
        option = next(o for o in context["options"] if o["label"] == chosen.label)
        status, reason = "accepted", "validated_choice"
        proposal = {"label": chosen.label, "option": option}
        break
    calls = [
        {
            key: (str(value) if isinstance(value, str) else value)
            for key, value in dataclasses.asdict(call).items()
        }
        for call in log.calls
    ]
    provider = None
    if charged:
        provider = {
            "provider": ask.spec.provider,
            "model_id": ask.spec.model_id,
            "served_model_id": served,
            "mechanism": ask.mechanism.value,
            "prompt_version": PROMPT_VERSION,
            "messages_sha256": society_state_sha256(first),
            "answers_asked": answers,
            "calls": calls,
            "prompt_tokens": sum(usage.prompt_tokens for usage in charged),
            "completion_tokens": sum(usage.completion_tokens for usage in charged),
            # What the attempts were charged: reported costs, and each unknown one at the most it
            # can have cost, which is what the world's hour of spend is counted in.
            "cost_usd": usd_string(sum((usage.usd for usage in charged), Decimal(0))),
            "cost_known": all(usage.usd_known for usage in charged),
            "latency_ms": round((time.monotonic() - started) * 1000),
        }
    return {"status": status, "reason": reason, "proposal": proposal, "provider": provider}


def _refused(reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason, "proposal": None, "provider": None}


def world_hour(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str
) -> tuple[int, Decimal]:
    """How many person decisions this world asked of models in the last hour, and their cost."""
    row = connection.execute(
        "select count(*) filter (where d.document->'provider' <> 'null'::jsonb) as asked,"
        "coalesce(sum((d.document->'provider'->>'cost_usd')::numeric) "
        "filter (where d.document->'provider' <> 'null'::jsonb),0) as spent "
        "from world_society_decision d join world_society s using(workspace_id,society_id) "
        "where d.workspace_id=%s and s.world_id=%s "
        "and d.document->>'profile'='exulanica.society-decision/v2' "
        "and d.recorded_at>clock_timestamp()-interval '1 hour'",
        (workspace_id, world_id),
    ).fetchone()
    return int(row["asked"]), Decimal(row["spent"])


@dataclass(frozen=True)
class PersonDecisionHost:
    """What the host's playback asks before a purposeful society's minute.

    ``workspaces`` are the ones the host's environment lists (``EXULANICA_SOCIETY_CONTROL_
    WORKSPACES``): no other workspace's people are asked for, whatever its owner chose.
    ``client`` is the process's model client, or ``None`` with no credential, in which case
    nothing is asked or written. ``policy_for`` attaches the workspace's rules to each ask.
    """

    database: Database
    runtime: SocietyRuntime
    client: ModelClient | None
    workspaces: frozenset[uuid.UUID]
    policy_for: Callable[[uuid.UUID], HostedRequestPolicy]
    manifest: Manifest
    manifest_sha256: str

    def before_minute(self, claim: ControlClaim, lease_ends: float) -> bool:
        """Ask every chosen person at a choice point; True when the coming minute runs alone.

        ``lease_ends`` is the monotonic time the claim's lease runs out. The asks end by the
        contract's deadline, and never later than the lease leaves for the minute to commit.
        True whenever this host may ask for somebody in this world, asked this minute or not, so
        the claim advances one minute and no later choice point of theirs passes unasked. False
        when it asks for nobody here (an unlisted workspace, no chosen person, or a host refusal):
        the claim advances as it would with no model.
        """
        if claim.workspace_id not in self.workspaces:
            return False
        contract = decision_contract()
        session = Session(workspace_id=claim.workspace_id, actor=claim.actor)
        with self.database.session(claim.workspace_id) as connection:
            society = SocietyRepository(
                connection,
                claim.workspace_id,
                world_id=claim.world_id,
                input_authorizer=lambda doc: self.runtime.authorize(connection, session, doc),
            )
            row = society._row(claim.version_id)
            if row is None or row["engine_version"] != PURPOSEFUL_PROFILE:
                return False
            choices = SocietyModelChoiceRepository(
                connection, claim.workspace_id, world_id=claim.world_id
            ).current(claim.version_id)
            chosen = {person: c for person, c in choices.items() if c["model"]}
            if not chosen:
                return False
            decisions = SocietyDecisionRepository(society)
            for request_id in decisions.unanswered_person_requests(claim.version_id):

                def close(request_id: uuid.UUID = request_id) -> None:
                    with connection.transaction():
                        decisions.close_unanswered(claim.version_id, request_id)

                _once_more_after_a_race(close)
            client = self.client
            if client is None or host_refusal(client, self.manifest, contract) is not None:
                return False
            budget = client.budget
            keep_usd, keep_calls = share_kept(budget, contract)
            ends_at = self._ends_at(contract, lease_ends)
            if ends_at <= time.monotonic():
                return True
            # Asked under the workspace's own rules, which also decide what may be offered.
            asking = client.with_policy(self.policy_for(claim.workspace_id))
            people = {person["id"]: person for person in row["state"]["inhabitants"]}
            attempts = contract.value("answer_attempts_maximum")
            due: list[tuple[str, dict[str, Any], ModelSpec, AnsweringMechanism]] = []
            for subject, choice in sorted(chosen.items()):
                person = people.get(subject)
                if person is None or not at_choice_point(person):
                    continue
                askable = _askable(self.manifest, contract, choice["model"]["model_id"])
                if (
                    askable is None
                    or model_refusal(client, self.manifest, contract, choice["model"]) is not None
                ):
                    continue
                due.append((subject, choice, *askable))
            if not due:
                return True

            def judged() -> dict[str, frozenset[str] | None]:
                """Once a minute, before anything is reserved and with no lock held: the rules
                judge the fixed description and every label anybody due could be offered, in one
                pass for each chosen model. None for a model whose question they would change."""
                latest = society._chain(row)
                document = society._inputs(row, [latest])[latest]
                labels: dict[str, set[str]] = {}
                for subject, choice, _spec, _mechanism in due:
                    labels.setdefault(choice["model"]["model_id"], set()).update(
                        option.label
                        for option in choice_options(
                            row["state"], document, subject, contract, seed=row["seed"]
                        )
                    )
                return {
                    model_id: _sendable_labels(asking, model_id, sorted(found))
                    for model_id, found in labels.items()
                }

            sendable = _once_more_after_a_race(judged)

            def reserve() -> tuple[list[PersonAsk], list[tuple[uuid.UUID, dict[str, Any]]]]:
                asks: list[PersonAsk] = []
                refused: list[tuple[uuid.UUID, dict[str, Any]]] = []
                asked, spent = world_hour(connection, claim.workspace_id, claim.world_id)
                with connection.transaction():
                    for subject, choice, spec, mechanism in due:
                        model = choice["model"]
                        offered = sendable[model["model_id"]]
                        if offered is None:
                            # The rules would change the question itself: nobody is asked it.
                            continue
                        reserved, fresh = decisions.prepare_person(
                            claim.version_id,
                            request_id=uuid.uuid5(
                                claim.society_id, f"person-decision:{subject}:{row['current_tick']}"
                            ),
                            subject_id=uuid.UUID(subject),
                            base_tick=row["current_tick"],
                            base_state_sha256=row["state_sha256"],
                            contract=contract,
                            provider_config={
                                "provider": model["provider"],
                                "model_id": model["model_id"],
                                "mechanism": mechanism.value,
                                "choice_seq": choice["choice_seq"],
                                "manifest_sha256": self.manifest_sha256,
                                "prompt_version": PROMPT_VERSION,
                                "contract": contract.binding(),
                                "deadline_ms": contract.value("decision_deadline_ms"),
                            },
                            offer=_only(offered),
                        )
                        if not fresh or reserved["request"] is None:
                            continue
                        request = reserved["request"]
                        request_id = uuid.UUID(request["request_id"])
                        messages = decision_messages(request["context"], mechanism)
                        bound = attempts * budget.estimate_usd(
                            spec,
                            prompt_chars=sum(len(str(message)) for message in messages),
                            max_tokens=answer_tokens(spec) or 0,
                        )
                        if asked >= contract.value("decisions_per_world_hour_maximum"):
                            refused.append((request_id, _refused("world_hour_decisions_spent")))
                            continue
                        if (spent + bound) * 1_000_000 > contract.value(
                            "spend_per_world_hour_microusd"
                        ):
                            refused.append((request_id, _refused("world_hour_spend_spent")))
                            continue
                        asked += 1
                        spent += bound
                        asks.append(PersonAsk(request, spec, mechanism))
                return asks, refused

            asks, refused = _once_more_after_a_race(reserve)
        # No connection from the reservations survives here: the models are asked without one.
        results = self._ask(asking, asks, contract, ends_at, keep_usd, keep_calls) if asks else []
        with self.database.session(claim.workspace_id) as connection:
            decisions = SocietyDecisionRepository(
                SocietyRepository(
                    connection,
                    claim.workspace_id,
                    world_id=claim.world_id,
                    input_authorizer=lambda doc: self.runtime.authorize(connection, session, doc),
                )
            )
            for request_id, result in [*refused, *results]:

                def finish(
                    last_try: bool,
                    request_id: uuid.UUID = request_id,
                    result: dict[str, Any] = result,
                ) -> None:
                    with connection.transaction():
                        decisions.finish(claim.version_id, request_id, result, last_try=last_try)

                # An answer a model was paid for is recorded: asked again after a race, and on the
                # last try recorded as decision_sources_unavailable rather than left open.
                asked_again_after_a_race(finish)
        return True

    @staticmethod
    def _ends_at(contract: DecisionContract, lease_ends: float) -> float:
        """When every ask of this minute ends: the contract's deadline from now, and never
        later than the lease leaves the minute to commit in."""
        commit_room = LEASE_SECONDS - contract.value("decision_deadline_ms") / 1000
        return min(
            time.monotonic() + contract.value("decision_deadline_ms") / 1000,
            lease_ends - commit_room,
        )

    def _ask(
        self,
        client: ModelClient,
        asks: list[PersonAsk],
        contract: DecisionContract,
        ends_at: float,
        keep_usd: Decimal,
        keep_calls: int,
    ) -> list[tuple[uuid.UUID, dict[str, Any]]]:
        results: list[tuple[uuid.UUID, dict[str, Any]]] = []
        workers = min(contract.value("concurrent_calls_maximum"), len(asks))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                (
                    ask,
                    pool.submit(
                        ask_person,
                        client,
                        ask,
                        contract,
                        ends_at,
                        keep_usd=keep_usd,
                        keep_calls=keep_calls,
                    ),
                )
                for ask in asks
            ]
            for ask, future in futures:
                try:
                    result = future.result()
                except Exception:
                    # Never an exception's text, which may carry request bytes or a credential.
                    _LOG.error("A person's decision ask failed; the routine decides that turn")
                    result = _refused("model_call_failed")
                results.append((uuid.UUID(ask.request["request_id"]), result))
        return results
