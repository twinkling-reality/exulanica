"""The host's playback asking, before a society's minute, the models a world's owner chose.

Every decision role an engine hosts (:mod:`exulanica.world.decision_roles`) is asked the same way,
by :class:`DecisionHost`: only in a workspace the host's environment lists, within each role's
contract bounds per world and hour, within the share of the process's model budget the role's
contract lets its decisions spend, and with no connection held while a model is asked. A person
in a purposeful society is the first such role.

What the host cannot ask it decides before reserving anything, and writes nothing: a host with no
client or with its budget or share spent (:func:`host_refusal`), a subject whose chosen model it
may not ask here (:func:`model_refusal`), and a question the workspace's rules would change
(:func:`question_refusal`). The models route says why, for the host and for each choice. Every
subject it does reserve a request for gets a receipt, whatever happened: an answer, or the reason
there is none, and then the world's own rules decide that turn. A request left without one, by a
host stopped between reserving and recording, is closed by name at the host's next minute. The
one hosted call path of every role is :func:`ask`. The page never asks a model; nothing here is
reachable from a route.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
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
from exulanica.models.manifest import AnsweringMechanism, Manifest, ModelSpec
from exulanica.models.policy import HostedRequestPolicy, NoHostedRequestPolicy
from exulanica.models.usage import CallUsage, usd_string
from exulanica.selection.calls import CallLog
from exulanica.selection.validation import Session
from exulanica.world.decision_roles import (
    DecisionContract,
    DecisionRole,
    RoleOption,
    decision_roles,
)
from exulanica.world.society import asked_again_after_a_race, society_state_sha256
from exulanica.world.society_controls import LEASE_SECONDS, ControlClaim
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository
from exulanica.world.society_repository import SocietyRepository

__all__ = [
    "HOST_REFUSALS",
    "MODEL_REFUSALS",
    "DecisionHost",
    "RoleAsk",
    "answer_tokens",
    "ask",
    "ask_bound_usd",
    "host_refusal",
    "hour_refusal",
    "model_refusal",
    "question_refusal",
    "sendable_labels",
    "share_kept",
    "smallest_ask_usd",
    "world_hour",
]

_LOG = logging.getLogger(__name__)
_T = TypeVar("_T")
#: Why a host asks no model for a workspace's subjects at all, by code; the page has words for each.
HOST_REFUSALS: Final = frozenset(
    {
        "models_not_run_here",
        "provider_credential_absent",
        "process_budget_spent",
        "process_share_spent",
    }
)
#: Why a subject's chosen model is not asked here while the host asks others; the page has words.
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
#: What the log says when an ask ends in an error nothing names: the error's class, and nothing
#: of its text.
_ASK_FAILED: Final = "A %s decision ask failed with %s; the world decides that turn"


def _error_class(exc: BaseException) -> str:
    """An error's class by its module and name, which is code, never anything it carries."""
    kind = type(exc)
    return f"{kind.__module__}.{kind.__qualname__}"


def _failure_reason(exc: BaseException) -> str:
    """How a failure that ended a subject's call is recorded, by the error that ended it."""
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
    """The most a chosen model may write in one answer: its manifest default, which leaves a
    reasoning model room to reason before it answers, and never below its floor."""
    if spec.default_max_tokens is None:
        return spec.min_max_tokens
    return max(spec.default_max_tokens, spec.min_max_tokens or 0)


def share_kept(budget: BudgetGuard, contract: DecisionContract) -> tuple[Decimal, int]:
    """The part of the process's budget a role's decisions must leave for its other work."""
    percent = contract.value("process_reserve_percent")
    return (
        (budget.ceiling_usd * percent / 100).quantize(Decimal("0.000001")),
        budget.max_calls * percent // 100,
    )


def _askable(
    role: DecisionRole, manifest: Manifest, contract: DecisionContract, model_id: str
) -> tuple[ModelSpec, AnsweringMechanism] | None:
    try:
        spec = manifest.offered(role.chosen, model_id)
    except ManifestError:
        return None
    mechanism = contract.mechanism_for(spec)
    return None if mechanism is None else (spec, mechanism)


def ask_bound_usd(
    role: DecisionRole, budget: BudgetGuard, spec: ModelSpec, contract: DecisionContract
) -> Decimal:
    """The most one ask of ``spec`` for ``role`` may reserve, whatever the subject's situation.

    Every answer the contract allows, each reserved as the client reserves a call, by the prompt's
    characters and the model's answer bound. The prompt is bounded by the role's instruction, the
    note a retry adds and twice the largest situation a request may carry, which covers the
    situation's rendering and each message's framing; tests/test_society_person_decisions.py holds
    the asks the small square makes under it.
    """
    prompt_chars = (
        len(role.instruction) + len(role.not_offered) + 2 * contract.value("context_bytes_maximum")
    )
    return contract.value("answer_attempts_maximum") * budget.estimate_usd(
        spec, prompt_chars=prompt_chars, max_tokens=answer_tokens(spec) or 0
    )


def smallest_ask_usd(
    role: DecisionRole, budget: BudgetGuard, manifest: Manifest, contract: DecisionContract
) -> Decimal | None:
    """The least that one ask of an offered model may need, the smallest ``ask_bound_usd``. A
    process whose remainder is under it can ask no model for the role; None with none offered."""
    bounds = [
        ask_bound_usd(role, budget, spec, contract)
        for spec in manifest.offered_models(role.chosen)
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
    role: DecisionRole,
    client: ModelClient | None,
    manifest: Manifest,
    contract: DecisionContract,
) -> str | None:
    """Why this process asks no model for ``role`` at all, or None when it may ask them.

    A code from ``HOST_REFUSALS`` other than ``models_not_run_here``, which is the host's own
    listing: no client, or a budget whose remainder, by what is spent, fits no ask of any offered
    model (``smallest_ask_usd``), in the whole budget or once the part kept for the process's other
    work is set aside. Either holds until the process restarts.
    """
    if client is None:
        return PROVIDER_CREDENTIAL_ABSENT
    smallest = smallest_ask_usd(role, client.budget, manifest, contract)
    return None if smallest is None else _budget_refusal(client.budget, contract, smallest)


def model_refusal(
    role: DecisionRole,
    client: ModelClient | None,
    manifest: Manifest,
    contract: DecisionContract,
    model: Mapping[str, str],
) -> str | None:
    """Why a subject's chosen model is not asked here, or None when it may be.

    A code from ``MODEL_REFUSALS``: a model no longer offered or askable under the contract, a
    choice naming a provider the manifest no longer serves the model from, a provider this
    process refuses, or a budget whose remainder no longer fits one ask of this model, which
    holds until the process restarts. Each is decided before anything is reserved.
    """
    askable = _askable(role, manifest, contract, model["model_id"])
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
    return _budget_refusal(
        client.budget, contract, ask_bound_usd(role, client.budget, spec, contract)
    )


def question_refusal(role: DecisionRole, client: ModelClient, model_id: str) -> str | None:
    """``question_changed_by_rules`` when the client's rules would change the question every
    subject asked of ``model_id`` is sent, the role's fixed choice description; else None.

    A saved name one of whose parts is a word of the description would, and every ask would then
    be refused as it left, every minute: so nobody is asked, nothing is written, and the models
    route names it for each choice of that model.
    """
    (kept,) = client.unchanged_by_policies(role.chosen, model_id, [role.choice_description])
    return None if kept else "question_changed_by_rules"


def sendable_labels(
    role: DecisionRole, client: ModelClient, model_id: str, labels: Sequence[str]
) -> frozenset[str] | None:
    """The labels the client's rules send as they are for ``model_id``, judged in one pass with
    the role's choice description; None when the rules would change the description.

    An option whose words a rule would change, a saved name that matches a catalog word, is left
    out rather than refusing the whole ask each minute; the subject has fewer options.
    """
    kept = client.unchanged_by_policies(role.chosen, model_id, [role.choice_description, *labels])
    if not kept[0]:
        return None
    return frozenset(label for label, keep in zip(labels, kept[1:], strict=True) if keep)


def _only(labels: frozenset[str]) -> Callable[[Sequence[RoleOption]], list[RoleOption]]:
    """The options whose labels were judged sendable; one the judgement did not see is left out."""

    def offered(options: Sequence[RoleOption]) -> list[RoleOption]:
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
class RoleAsk:
    """One reserved request, the role it is asked for, the model it asks and how: all a call
    needs, and no connection."""

    role: DecisionRole
    request: dict[str, Any]
    spec: ModelSpec
    mechanism: AnsweringMechanism


def ask(
    client: ModelClient,
    asked: RoleAsk,
    contract: DecisionContract,
    ends_at: float,
    *,
    keep_usd: Decimal = Decimal(0),
    keep_calls: int = 0,
) -> dict[str, Any]:
    """A subject's answer, asked of the chosen model, as the result a receipt records: the one
    hosted call path of every role.

    Asked by the model's own verified mechanism, at most ``answer_attempts_maximum`` times: an
    answer that is not one of the options is asked once more, telling the model so in the role's
    words, and every other failure ends the ask. ``ends_at`` is the monotonic time the whole ask
    ends by, every attempt within it, however long it waited to start. ``keep_usd`` and
    ``keep_calls`` are the part of the process's budget it must leave. The record names every
    attempt in the execution record's words, whatever its outcome.
    """
    role = asked.role
    log = CallLog()
    charged: list[CallUsage] = []

    def heard(usage: CallUsage) -> None:
        log.attempt(usage)
        charged.append(usage)

    sender = client.with_attempts(heard)
    context = asked.request["context"]
    request = role.choice(context)
    first = role.adapter.messages(role, context, asked.mechanism)
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
        role_slot = _role_call_slots(role.key, contract.value("concurrent_calls_maximum"))
        if not role_slot.acquire(timeout=remaining):
            status, reason = "unavailable", "no_time_to_ask"
            break
        slot = _process_call_slots()
        remaining = ends_at - time.monotonic()
        if remaining <= 0 or not slot.acquire(timeout=remaining):
            role_slot.release()
            status, reason = "unavailable", "no_time_to_ask"
            break
        try:
            remaining = ends_at - time.monotonic()
            if remaining <= 0:
                status, reason = "unavailable", "no_time_to_ask"
                break
            chosen = sender.choose(
                role.chosen,
                asked.spec.model_id,
                messages,
                request,
                mechanism=asked.mechanism,
                prompt_version=role.prompt_version,
                timeout=remaining,
                max_tokens=answer_tokens(asked.spec),
                keep_usd=keep_usd,
                keep_calls=keep_calls,
            )
        except ChoiceRefused:
            messages = [*messages, {"role": "user", "content": role.not_offered}]
            continue
        except (ModelError, PrivacyAdmissionError, NoHostedRequestPolicy) as exc:
            status, reason = "unavailable", _failure_reason(exc)
            break
        except Exception as exc:
            # Any other error ends the ask as a failed call, and every attempt it paid for stays in
            # the record rather than leaving with the exception. Its class names the defect; never
            # its text, which may carry request bytes or a credential.
            _LOG.error(_ASK_FAILED, role.key, _error_class(exc))
            status, reason = "unavailable", "model_call_failed"
            break
        finally:
            slot.release()
            role_slot.release()
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
            "provider": asked.spec.provider,
            "model_id": asked.spec.model_id,
            "served_model_id": served,
            "mechanism": asked.mechanism.value,
            "prompt_version": role.prompt_version,
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


@cache
def _role_call_slots(role_key: str, maximum: int) -> threading.BoundedSemaphore:
    """A role's process-wide call ceiling, including calls outside a society minute."""
    return threading.BoundedSemaphore(maximum)


@cache
def _process_call_slots() -> threading.BoundedSemaphore:
    """One process ceiling for society, traffic and comparison calls sharing the client."""
    return threading.BoundedSemaphore(
        max(role.contract().value("concurrent_calls_maximum") for role in decision_roles())
    )


def _refused(reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason, "proposal": None, "provider": None}


def world_hour(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, role: DecisionRole
) -> tuple[int, Decimal]:
    """How many of ``role``'s decisions this world asked of models in the last hour, and their
    cost."""
    row = connection.execute(
        "select count(*) filter (where d.document->'provider' <> 'null'::jsonb) as asked,"
        "coalesce(sum((d.document->'provider'->>'cost_usd')::numeric) "
        "filter (where d.document->'provider' <> 'null'::jsonb),0) as spent "
        "from world_society_decision d join world_society s using(workspace_id,society_id) "
        "where d.workspace_id=%s and s.world_id=%s "
        "and d.document->>'profile'=%s "
        "and d.recorded_at>clock_timestamp()-interval '1 hour'",
        (workspace_id, world_id, role.receipt_profile),
    ).fetchone()
    return int(row["asked"]), Decimal(row["spent"])


def hour_refusal(
    asked: int, spent: Decimal, bound: Decimal, contract: DecisionContract
) -> str | None:
    """Why one more ask, needing ``bound``, is past the world's hour: ``world_hour_decisions_spent``
    once the hour holds ``decisions_per_world_hour_maximum`` asked decisions, and
    ``world_hour_spend_spent`` once its cost with this ask's bound passes
    ``spend_per_world_hour_microusd``; else None."""
    if asked >= contract.value("decisions_per_world_hour_maximum"):
        return "world_hour_decisions_spent"
    if (spent + bound) * 1_000_000 > contract.value("spend_per_world_hour_microusd"):
        return "world_hour_spend_spent"
    return None


@dataclass(frozen=True)
class DecisionHost:
    """What the host's playback asks before a society's minute, for every role its engine hosts.

    ``workspaces`` are the ones the host's environment lists (``EXULANICA_SOCIETY_CONTROL_
    WORKSPACES``): no other workspace's subjects are asked for, whatever its owner chose.
    ``client`` is the process's model client, or ``None`` with no credential, in which case
    nothing is asked or written. ``policy_for`` attaches the workspace's rules to each ask. The
    roles are the registry's (:func:`~exulanica.world.decision_roles.decision_roles`), the one
    every reader of a role's documents asks.
    """

    database: Database
    runtime: SocietyRuntime
    client: ModelClient | None
    workspaces: frozenset[uuid.UUID]
    policy_for: Callable[[uuid.UUID], HostedRequestPolicy]
    manifest: Manifest
    manifest_sha256: str

    def before_minute(self, claim: ControlClaim, lease_ends: float) -> bool:
        """Ask every chosen subject at a choice point; True when the coming minute runs alone.

        ``lease_ends`` is the monotonic time the claim's lease runs out. The asks end by each
        role's contract deadline, and never later than the lease leaves for the minute to commit.
        True whenever this host may ask for somebody in this world, asked this minute or not, so
        the claim advances one minute and no later choice point of theirs passes unasked. False
        when it asks for nobody here (an unlisted workspace, no chosen subject, or a host
        refusal): the claim advances as it would with no model.
        """
        if claim.workspace_id not in self.workspaces:
            return False
        session = Session(workspace_id=claim.workspace_id, actor=claim.actor)
        with self.database.session(claim.workspace_id) as connection:
            society = SocietyRepository(
                connection,
                claim.workspace_id,
                world_id=claim.world_id,
                input_authorizer=lambda doc: self.runtime.authorize(connection, session, doc),
            )
            row = society._row(claim.version_id)
            if row is None:
                return False
            asking_roles = []
            choice_repository = SocietyModelChoiceRepository(
                connection, claim.workspace_id, world_id=claim.world_id
            )
            for role in decision_roles().hosted_by(row["engine_version"]):
                choices = choice_repository.current(claim.version_id, role)
                chosen = {subject: c for subject, c in choices.items() if c["model"]}
                if chosen:
                    asking_roles.append((role, role.contract(), chosen))
            if not asking_roles:
                return False
            decisions = SocietyDecisionRepository(society)
            for role, _contract, _chosen in asking_roles:
                for request_id in decisions.unanswered_requests(role, claim.version_id):

                    def close(request_id: uuid.UUID = request_id) -> None:
                        with connection.transaction():
                            decisions.close_unanswered(claim.version_id, request_id)

                    _once_more_after_a_race(close)
            client = self.client
            if client is None:
                return False
            asking_roles = [
                (role, contract, chosen)
                for role, contract, chosen in asking_roles
                if host_refusal(role, client, self.manifest, contract) is None
            ]
            if not asking_roles:
                return False
            planned = []
            for role, contract, chosen in asking_roles:
                due = self._due(role, contract, chosen, row["state"], client)
                if due:
                    planned.append((role, contract, lease_ends, due))
            if not planned:
                return True
            # Asked under the workspace's own rules, which also decide what may be offered.
            asking = client.with_policy(self.policy_for(claim.workspace_id))
            # Each role's requests are reserved in a transaction of its own, asked again on its
            # own after a race: another role's committed reservations are never read again, where
            # an existing request is not fresh and would go unasked.
            reserved = []
            for role, contract, _lease_ends, due in planned:
                # A lease with no time left makes no request. The actual ask window is set
                # after reservation, so time spent reserving cannot borrow another role's time.
                if self._ends_at(contract, lease_ends) <= time.monotonic():
                    continue
                try:
                    sendable = _once_more_after_a_race(
                        lambda role=role, contract=contract, due=due: self._judged(
                            society, row, asking, [(role, contract, lease_ends, due)]
                        )
                    )
                except Exception as exc:
                    _LOG.error("A %s question failed with %s", role.key, _error_class(exc))
                    continue

                def reserve(
                    role: DecisionRole = role,
                    contract: DecisionContract = contract,
                    due: list = due,
                    sendable: dict = sendable,
                ) -> tuple[list[RoleAsk], list[tuple[uuid.UUID, dict[str, Any]]]]:
                    return self._reserved(
                        connection, claim, decisions, row, role, contract, due, sendable, client
                    )

                try:
                    asks, refused = _once_more_after_a_race(reserve)
                except Exception as exc:
                    # One role's reservation cannot cancel requests already committed for
                    # another. The transaction above rolls this role's incomplete work back.
                    _LOG.error("A %s reservation failed with %s", role.key, _error_class(exc))
                    continue
                ends_at = self._ends_at(contract, lease_ends)
                reserved.append((contract, ends_at, asks, refused))
        # No connection from the reservations survives here: the models are asked without one.
        result_groups = self._asked_by_every_role(asking, reserved)
        for role_results in result_groups:
            try:
                with self.database.session(claim.workspace_id) as connection:
                    decisions = SocietyDecisionRepository(
                        SocietyRepository(
                            connection,
                            claim.workspace_id,
                            world_id=claim.world_id,
                            input_authorizer=lambda doc: self.runtime.authorize(
                                connection, session, doc
                            ),
                        )
                    )
                    for request_id, result in role_results:

                        def finish(
                            last_try: bool,
                            request_id: uuid.UUID = request_id,
                            result: dict[str, Any] = result,
                            decisions: SocietyDecisionRepository = decisions,
                        ) -> None:
                            with connection.transaction():
                                decisions.finish(
                                    claim.version_id, request_id, result, last_try=last_try
                                )

                        # An answer a model was paid for is recorded: asked again after a race,
                        # and on the last try recorded as decision_sources_unavailable.
                        asked_again_after_a_race(finish)
            except Exception as exc:
                # A broken connection or a role-specific recording fault cannot drop another
                # role's answers. Open its own session for the next role.
                _LOG.error("A decision recording failed with %s", _error_class(exc))
        return True

    def _due(
        self,
        role: DecisionRole,
        contract: DecisionContract,
        chosen: Mapping[str, Mapping[str, Any]],
        state: Mapping[str, Any],
        client: ModelClient,
    ) -> list[tuple[str, Mapping[str, Any], ModelSpec, AnsweringMechanism]]:
        """Each chosen subject of ``role`` at a choice point whose model this host may ask."""
        present = set(role.adapter.subjects(state))
        due = []
        for subject, choice in sorted(chosen.items()):
            if subject not in present or not role.adapter.due(state, subject):
                continue
            askable = _askable(role, self.manifest, contract, choice["model"]["model_id"])
            if (
                askable is None
                or model_refusal(role, client, self.manifest, contract, choice["model"]) is not None
            ):
                continue
            due.append((subject, choice, *askable))
        return due

    @staticmethod
    def _judged(
        society: SocietyRepository,
        row: dict[str, Any],
        asking: ModelClient,
        planned: Sequence[tuple[DecisionRole, DecisionContract, float, list]],
    ) -> dict[tuple[str, str], frozenset[str] | None]:
        """Once a minute, before anything is reserved and with no lock held: the rules judge each
        role's fixed description and every label anybody due could be offered, in one pass for
        each role and chosen model. None for a model whose question they would change."""
        latest = society._chain(row)
        document = society._inputs(row, [latest])[latest]
        labels: dict[tuple[str, str], set[str]] = {}
        roles: dict[str, DecisionRole] = {}
        for role, contract, _ends_at, due in planned:
            roles[role.key] = role
            for subject, choice, _spec, _mechanism in due:
                labels.setdefault((role.key, choice["model"]["model_id"]), set()).update(
                    option.label
                    for option in role.adapter.options(
                        role, row["state"], document, subject, contract, seed=row["seed"]
                    )
                )
        return {
            (key, model_id): sendable_labels(roles[key], asking, model_id, sorted(found))
            for (key, model_id), found in labels.items()
        }

    def _reserved(
        self,
        connection: psycopg.Connection,
        claim: ControlClaim,
        decisions: SocietyDecisionRepository,
        row: dict[str, Any],
        role: DecisionRole,
        contract: DecisionContract,
        due: Sequence[tuple[str, Mapping[str, Any], ModelSpec, AnsweringMechanism]],
        sendable: Mapping[tuple[str, str], frozenset[str] | None],
        client: ModelClient,
    ) -> tuple[list[RoleAsk], list[tuple[uuid.UUID, dict[str, Any]]]]:
        """``role``'s requests reserved for this minute, in one transaction: the asks the world's
        hour admits, and each request past it with the bound it met."""
        asks: list[RoleAsk] = []
        refused: list[tuple[uuid.UUID, dict[str, Any]]] = []
        attempts = contract.value("answer_attempts_maximum")
        asked, spent = world_hour(connection, claim.workspace_id, claim.world_id, role)
        with connection.transaction():
            for subject, choice, spec, mechanism in due:
                model = choice["model"]
                offered = sendable[(role.key, model["model_id"])]
                if offered is None:
                    # The rules would change the question itself: nobody is asked it.
                    continue
                reserved, fresh = decisions.prepare_role(
                    role,
                    claim.version_id,
                    request_id=uuid.uuid5(
                        claim.society_id,
                        f"{role.subject}-decision:{subject}:{row['current_tick']}",
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
                        "prompt_version": role.prompt_version,
                        "contract": contract.binding(),
                        "deadline_ms": contract.value("decision_deadline_ms"),
                    },
                    offer=_only(offered),
                )
                if not fresh or reserved["request"] is None:
                    continue
                request = reserved["request"]
                request_id = uuid.UUID(request["request_id"])
                messages = role.adapter.messages(role, request["context"], mechanism)
                bound = attempts * client.budget.estimate_usd(
                    spec,
                    prompt_chars=sum(len(str(message)) for message in messages),
                    max_tokens=answer_tokens(spec) or 0,
                )
                refusal = hour_refusal(asked, spent, bound, contract)
                if refusal is not None:
                    refused.append((request_id, _refused(refusal)))
                    continue
                asked += 1
                spent += bound
                asks.append(RoleAsk(role, request, spec, mechanism))
        return asks, refused

    def _asked_by_every_role(
        self,
        client: ModelClient,
        reserved: Sequence[
            tuple[DecisionContract, float, list[RoleAsk], list[tuple[uuid.UUID, dict[str, Any]]]]
        ],
    ) -> list[list[tuple[uuid.UUID, dict[str, Any]]]]:
        """Every role's asks at once, each by its own deadline, so no role waits for another's;
        then each role's results, refusals first, in the order its requests were reserved."""
        # One executor bounds calls across all roles. The first pass gives each role a slot
        # before any role's second ask, so a slow role cannot consume the entire pool first.
        active = [item for item in reserved if item[2]]
        if not active:
            return [list(refused) for _contract, _ends_at, _asks, refused in reserved]
        process_limit = max(
            len(active), max(contract.value("concurrent_calls_maximum") for contract, *_ in active)
        )
        role_limits = [
            threading.Semaphore(contract.value("concurrent_calls_maximum"))
            for contract, *_ in reserved
        ]

        def bounded_ask(
            role_index: int,
            asked: RoleAsk,
            contract: DecisionContract,
            ends_at: float,
            keep_usd: Decimal,
            keep_calls: int,
        ) -> dict[str, Any]:
            with role_limits[role_index]:
                return ask(
                    client,
                    asked,
                    contract,
                    ends_at,
                    keep_usd=keep_usd,
                    keep_calls=keep_calls,
                )

        per_role: list[list[tuple[uuid.UUID, Future[dict[str, Any]]]]] = [[] for _ in reserved]
        with ThreadPoolExecutor(max_workers=process_limit) as pool:
            for index in range(max(len(asks) for _contract, _ends_at, asks, _held in reserved)):
                for role_index, (contract, ends_at, asks, _held) in enumerate(reserved):
                    if index >= len(asks):
                        continue
                    asked = asks[index]
                    keep_usd, keep_calls = share_kept(client.budget, contract)
                    future = pool.submit(
                        bounded_ask,
                        role_index,
                        asked,
                        contract,
                        ends_at,
                        keep_usd,
                        keep_calls,
                    )
                    per_role[role_index].append((uuid.UUID(asked.request["request_id"]), future))
            results = []
            for (_contract, _ends_at, _asks, role_refusals), futures in zip(
                reserved, per_role, strict=True
            ):
                role_results = list(role_refusals)
                for request_id, future in futures:
                    try:
                        result = future.result()
                    except Exception as exc:
                        _LOG.error("A decision ask failed with %s", _error_class(exc))
                        result = _refused("model_call_failed")
                    role_results.append((request_id, result))
                results.append(role_results)
        return results

    @staticmethod
    def _ends_at(contract: DecisionContract, lease_ends: float) -> float:
        """When every ask of a role this minute ends: the contract's deadline from now, and never
        later than the lease leaves the minute to commit in."""
        commit_room = LEASE_SECONDS - contract.value("decision_deadline_ms") / 1000
        return min(
            time.monotonic() + contract.value("decision_deadline_ms") / 1000,
            lease_ends - commit_room,
        )

    def _ask(
        self,
        client: ModelClient,
        asks: list[RoleAsk],
        contract: DecisionContract,
        ends_at: float,
        keep_usd: Decimal,
        keep_calls: int,
    ) -> list[tuple[uuid.UUID, dict[str, Any]]]:
        """Ask one role in isolation, retained for the single-role decision contract caller."""
        results: list[tuple[uuid.UUID, dict[str, Any]]] = []
        workers = min(contract.value("concurrent_calls_maximum"), len(asks))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                (
                    asked,
                    pool.submit(
                        ask,
                        client,
                        asked,
                        contract,
                        ends_at,
                        keep_usd=keep_usd,
                        keep_calls=keep_calls,
                    ),
                )
                for asked in asks
            ]
            for asked, future in futures:
                try:
                    result = future.result()
                except Exception as exc:
                    _LOG.error(_ASK_FAILED, asked.role.key, _error_class(exc))
                    result = _refused("model_call_failed")
                results.append((uuid.UUID(asked.request["request_id"]), result))
        return results
