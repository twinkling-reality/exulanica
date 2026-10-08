"""The host's playback asking, before a society's minute, the models a world's owner chose.

Every decision role an engine hosts (:mod:`exulanica.world.decision_roles`) is asked the same way,
by :class:`DecisionHost`: only in a workspace the host's environment lists or, under durable
spending, one account discovery watches, within each role's
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
import unicodedata
import uuid
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from typing import Any, Final, TypeVar

import psycopg

from exulanica.api.external_asking import REFUSALS_BEFORE_ASKING, ExternalAsker
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.db.session import Database
from exulanica.epistemics.saved_names import SavedName, recognised_spans, saved_names
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
from exulanica.models.spending import SpendingRefused
from exulanica.models.usage import CallUsage, usd_string
from exulanica.selection.calls import CallLog
from exulanica.selection.validation import Session
from exulanica.spending.status import SpendingRefusals
from exulanica.things.lines import LineRefused, check_line
from exulanica.world.deciders import arrival_deciders, check_external_config
from exulanica.world.decision_roles import (
    GENERIC_REASONS,
    DecisionContract,
    DecisionRole,
    RoleOption,
    decision_roles,
)
from exulanica.world.role_decisions import check_role_result
from exulanica.world.society import asked_again_after_a_race, society_state_sha256
from exulanica.world.society_controls import LEASE_SECONDS, ControlClaim
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository
from exulanica.world.society_repository import SocietyRepository

__all__ = [
    "HOST_REFUSALS",
    "MODEL_REFUSALS",
    "DecisionHost",
    "OutsideAsk",
    "RoleAsk",
    "answer_tokens",
    "ask",
    "ask_bound_usd",
    "host_refusal",
    "hour_refusal",
    "model_refusal",
    "offered_providers",
    "outside_context_sendable",
    "outside_sendable_labels",
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
#: The most outside programs asked at once in one minute: each ask waits on its door for at most
#: its deadline, so this bounds the host's threads, not the number of subjects asked.
_OUTSIDE_ASKS_AT_ONCE: Final = 16
#: What a door states about the program it serves when a request is reserved: everything a request
#: records of it but the contract, which the host adds.
_DOOR_STATES: Final = frozenset(
    {"kind", "bridge", "grant_id", "grant_seq", "mapping_sha256", "deadline_ms"}
)
#: What a door's answer states: what a receipt records of any answer.
_ANSWER_KEYS: Final = frozenset({"status", "reason", "proposal", "provider"})
#: The statuses a door may answer with; ``stale`` is the host's to record, never a program's.
_ANSWER_STATUSES: Final = frozenset({"accepted", "rejected", "unavailable"})


def _error_class(exc: BaseException) -> str:
    """An error's class by its module and name, which is code, never anything it carries."""
    kind = type(exc)
    return f"{kind.__module__}.{kind.__qualname__}"


def _failure_reason(exc: BaseException) -> str:
    """How a failure that ended a subject's call is recorded, by the error that ended it."""
    if isinstance(exc, ProviderRefused):
        return exc.reason
    if isinstance(exc, SpendingRefused):
        # The durable authority's own reason. The host asks under no request key, so an
        # idempotency refusal cannot reach here; it would still be named for what it is not.
        return exc.reason if exc.reason in GENERIC_REASONS else "spending_unavailable"
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
    prompt_chars = max(
        len(terms.instruction) + len(terms.not_offered) for terms in role.every_terms()
    ) + 2 * contract.value("context_bytes_maximum")
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


def offered_providers(
    role: DecisionRole, manifest: Manifest, contract: DecisionContract
) -> tuple[str, ...]:
    """The providers an ask for ``role`` can reach: those serving the models the manifest offers
    it and its contract can ask, each once, in the order the manifest offers them. An ask reaches
    its chosen model's provider alone."""
    return tuple(
        dict.fromkeys(
            spec.provider
            for spec in manifest.offered_models(role.chosen)
            if contract.mechanism_for(spec) is not None
        )
    )


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


def _line_refusal(
    client: ModelClient,
    role: DecisionRole,
    model_id: str,
    line: object,
    maximum: int,
    names: Sequence[SavedName],
) -> str | None:
    """Why a line a model wrote may not be said in the world, or None: ``line_out_of_bounds`` when
    it breaks the line rule at the request's bound, ``line_refused_by_rules`` when the workspace's
    rules would change it, as they would a saved name, or when it carries any name the account
    holder saved, whatever right releases that name to this model: a line said is read again by
    every later decider, an outside program among them, which no right releases a name to."""
    try:
        checked = check_line(line, maximum=maximum)
    except LineRefused:
        return "line_out_of_bounds"
    if recognised_spans(checked, names):
        return "line_refused_by_rules"
    (kept,) = client.unchanged_by_policies(role.chosen, model_id, [checked])
    return None if kept else "line_refused_by_rules"


def _descriptions(role: DecisionRole, engine: str | None = None) -> list[str]:
    """The fixed choice description ``engine``'s people are asked by, the terms it states or the
    role's own; with no engine named, every one the role asks by: its own, then each engine's."""
    if engine is not None:
        return [role.terms(engine).choice_description]
    return [terms.choice_description for terms in role.every_terms()]


def question_refusal(role: DecisionRole, client: ModelClient, model_id: str) -> str | None:
    """``question_changed_by_rules`` when the client's rules would change a question a subject
    asked of ``model_id`` is sent, one of the role's fixed choice descriptions; else None.

    A saved name one of whose parts is a word of a description would, and every ask would then be
    refused as it left, every minute: so nobody is asked, nothing is written, and the models route
    names it for each choice of that model.
    """
    descriptions = _descriptions(role)
    kept = client.unchanged_by_policies(role.chosen, model_id, descriptions)
    return None if all(kept) else "question_changed_by_rules"


def sendable_labels(
    role: DecisionRole,
    client: ModelClient,
    model_id: str,
    labels: Sequence[str],
    engine: str | None = None,
) -> frozenset[str] | None:
    """The labels the client's rules send as they are for ``model_id``, judged in one pass with
    the choice description ``engine``'s people are asked by (every one the role states, with no
    engine named); None when the rules would change the description.

    An option whose words a rule would change, a saved name that matches a catalog word, is left
    out rather than refusing the whole ask each minute; the subject has fewer options.
    """
    descriptions = _descriptions(role, engine)
    kept = client.unchanged_by_policies(role.chosen, model_id, [*descriptions, *labels])
    if not all(kept[: len(descriptions)]):
        return None
    return frozenset(
        label for label, keep in zip(labels, kept[len(descriptions) :], strict=True) if keep
    )


def outside_sendable_labels(
    names: Sequence[SavedName],
    role: DecisionRole,
    labels: Sequence[str],
    engine: str | None = None,
) -> frozenset[str] | None:
    """The labels an outside program may be sent as they are, judged with the fixed description
    ``engine``'s people are asked by: none of them may carry a name the account holder saved, of
    any kind, since no right releases a name to a program outside the policy boundary; None when
    the description itself carries one, and then nobody is asked it."""
    if any(recognised_spans(description, names) for description in _descriptions(role, engine)):
        return None
    return frozenset(label for label in labels if not recognised_spans(label, names))


def _texts(value: object) -> Iterator[str]:
    """Every text a JSON value states, its objects' keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, held in value.items():
            yield str(key)
            yield from _texts(held)
    elif isinstance(value, list | tuple):
        for held in value:
            yield from _texts(held)


def _line_out_of_bounds(asked: OutsideAsk, result: Mapping[str, Any]) -> bool:
    """Whether an outside program accepted one of the options its request offered, by its label,
    with a line where it says nothing, none where it says something, or one that breaks the line
    rule at the request's bound."""
    proposal = result["proposal"]
    context = asked.request["context"]
    if result["status"] != "accepted" or not isinstance(proposal, Mapping):
        return False
    option = proposal.get("option")
    if (
        not isinstance(option, Mapping)
        or option not in context["options"]
        or proposal.get("label") != option["label"]
        or not set(proposal) <= {"label", "option", "line"}
    ):
        return False
    takes_line = option.get("kind") in getattr(asked.role.adapter, "LINE_KINDS", frozenset())
    line = proposal.get("line")
    if not takes_line:
        return line is not None
    try:
        return check_line(line, maximum=context["line_characters_maximum"]) != line
    except LineRefused:
        return True


def without_named_lines(
    names: Sequence[SavedName],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """An observation for an outside program without the heard lines that carry a name the account
    holder saved, in the line or in who said it: a name saved after a line was said, or one a
    right released to the speaker's model, never reaches a program outside the policy boundary,
    and one such line no longer stops the program being asked."""

    def withhold(context: dict[str, Any]) -> dict[str, Any]:
        heard = context.get("heard")
        if not heard:
            return context
        kept = [
            line
            for line in heard
            if not recognised_spans(line["line"], names)
            and not recognised_spans(line["from"], names)
        ]
        return context if len(kept) == len(heard) else {**context, "heard": kept}

    return withhold


def outside_context_sendable(names: Sequence[SavedName], context: Mapping[str, Any]) -> bool:
    """Whether a request's whole context may be sent to an outside program as it is: no text in
    any of its fields carries a name the account holder saved. A model's request passes the
    policy boundary, which redacts; an outside program's passes none, so one that would carry a
    name is not sent at all."""
    return not any(recognised_spans(text, names) for text in _texts(context))


def _door_statement(
    contract: DecisionContract,
    described: Mapping[str, Any],
    told: object,
    refusal: object,
) -> tuple[dict[str, Any], str | None]:
    """A door's statement about the program a choice names, held to its one shape, with the
    contract the host adds, and the refusal it may give before asking; or ValueError."""
    if not isinstance(told, Mapping) or set(told) != _DOOR_STATES:
        raise ValueError(f"a door states exactly {sorted(_DOOR_STATES)}")
    config = {**told, "contract": contract.binding()}
    check_external_config(config)
    if config["deadline_ms"] > contract.value("decision_deadline_ms"):
        raise ValueError("a door's deadline outlasts the contract's")
    if (config["bridge"], config["grant_id"]) != (described["bridge"], described["grant_id"]):
        raise ValueError("a door stated another program than the choice names")
    if refusal is not None and refusal not in REFUSALS_BEFORE_ASKING:
        raise ValueError("a door refused an ask for a reason it may not give")
    return dict(config), None if refusal is None else str(refusal)


class _NotSendable(Exception):
    """A reserved request whose context would carry a saved name: undone, and nobody asked."""


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
    #: The names the account holder saved, which no line the model writes may carry: a line is
    #: said into the world, where every later reader, an outside program among them, reads it.
    names: tuple[SavedName, ...] = ()


@dataclass(frozen=True, slots=True)
class OutsideAsk:
    """One reserved request an outside program is asked, under the role it is asked for: all its
    door needs, and no connection. It is asked by the sooner of its door's own deadline from the
    moment it is asked and ``latest``, the end the playback lease leaves its role's asks."""

    role: DecisionRole
    request: dict[str, Any]
    deadline_ms: int
    latest: float
    #: The names the account holder saved, which no line the program sends may carry.
    names: tuple[SavedName, ...] = ()

    def ends_at(self, now: float) -> float:
        return min(now + self.deadline_ms / 1000, self.latest)


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
    terms = role.terms_of(context)
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
                prompt_version=terms.prompt_version,
                timeout=remaining,
                max_tokens=answer_tokens(asked.spec),
                keep_usd=keep_usd,
                keep_calls=keep_calls,
            )
        except ChoiceRefused:
            messages = [*messages, {"role": "user", "content": terms.not_offered}]
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
        takes_line = option.get("kind") in getattr(role.adapter, "LINE_KINDS", frozenset())
        if takes_line != bool(chosen.line):
            # A line for an option that says nothing, or none for one that says something, is
            # not an answer to this choice: asked once more, as an option not offered is.
            messages = [*messages, {"role": "user", "content": terms.not_offered}]
            continue
        proposal = {"label": chosen.label, "option": option}
        status, reason = "accepted", "validated_choice"
        if takes_line:
            # A model's line in another normal form is the same line: it is said composed (NFC),
            # as the line rule holds every line, rather than refused for its encoding.
            line = (
                unicodedata.normalize("NFC", chosen.line)
                if isinstance(chosen.line, str)
                else chosen.line
            )
            try:
                refused = _line_refusal(
                    client,
                    role,
                    asked.spec.model_id,
                    line,
                    context["line_characters_maximum"],
                    asked.names,
                )
            except Exception as exc:
                # The rules failing on a line end the ask as a failed call, every attempt it paid
                # for on the record, as any other failure after the call does.
                _LOG.error(_ASK_FAILED, role.key, _error_class(exc))
                status, reason, proposal = "unavailable", "model_call_failed", None
                break
            if refused is not None:
                status, reason, proposal = "rejected", refused, None
                break
            proposal["line"] = check_line(line, maximum=context["line_characters_maximum"])
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
            "prompt_version": terms.prompt_version,
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
    cost. An outside program's answers are not counted: they spend nothing, and their own grant
    bounds how often they are asked."""
    row = connection.execute(
        "select count(*) filter (where d.document->'provider' <> 'null'::jsonb "
        "and d.document->'provider'->>'kind' is null) as asked,"
        "coalesce(sum((d.document->'provider'->>'cost_usd')::numeric) "
        "filter (where d.document->'provider' <> 'null'::jsonb "
        "and d.document->'provider'->>'kind' is null),0) as spent "
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
    WORKSPACES``), and ``discovered``, where given, reads the ones account discovery adds under
    durable spending (:meth:`~exulanica.api.services.Services.asks_models_for`): no other
    workspace's subjects are asked for, whatever its owner chose.
    ``client`` is the process's model client, or ``None`` with no credential, in which case no
    model is asked and nothing is written for a subject a model runs. ``policy_for`` attaches the
    workspace's rules to each ask. ``external`` is the outside programs' door the application
    registers, or ``None``, in which case no outside program is asked and nothing is written for
    a subject one decides for; it needs no model client. Outside programs are asked for the same
    workspaces as models, discovered ones included; a guest holds no ``door.grant``, so only an
    owner's grant lets one in. ``spending_refusals``, where given, reads once a claim what the
    durable authority would answer the workspace's next attempt, by provider: a subject whose
    model's provider would be refused is not reserved for, and decides by its routine, so a spent
    allowance takes no admission lock. The roles are the registry's
    (:func:`~exulanica.world.decision_roles.decision_roles`), the one every reader of a role's
    documents asks.
    """

    database: Database
    runtime: SocietyRuntime
    client: ModelClient | None
    workspaces: frozenset[uuid.UUID]
    policy_for: Callable[[uuid.UUID], HostedRequestPolicy]
    manifest: Manifest
    manifest_sha256: str
    external: ExternalAsker | None = None
    discovered: Callable[[], frozenset[uuid.UUID]] | None = None
    spending_refusals: Callable[[psycopg.Connection, uuid.UUID], SpendingRefusals | None] | None = (
        None
    )

    def before_minute(self, claim: ControlClaim, lease_ends: float) -> bool:
        """Ask every chosen subject at a choice point; True when the coming minute runs alone.

        ``lease_ends`` is the monotonic time the claim's lease runs out. The asks end by each
        role's contract deadline, and never later than the lease leaves for the minute to commit.
        True whenever this host may ask for somebody in this world, asked this minute or not, so
        the claim advances one minute and no later choice point of theirs passes unasked. False
        when it asks for nobody here (an unlisted workspace, no chosen subject, or a host
        refusal): the claim advances as it would with no model. A subject an outside program
        decides for is asked through ``external``, beside the models, with no model client.
        """
        if claim.workspace_id not in self.workspaces and (
            self.discovered is None or claim.workspace_id not in self.discovered()
        ):
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
            chosen_roles = []
            choice_repository = SocietyModelChoiceRepository(
                connection, claim.workspace_id, world_id=claim.world_id
            )
            for role in decision_roles().hosted_by(row["engine_version"]):
                # Asked under the terms the society's engine states, or the role's own; a gate's
                # travellers are decided for by its group choice within the contract's bound.
                terms = role.terms(row["engine_version"])
                contract = role.contract(terms.versions)
                choices = choice_repository.deciding(claim.version_id, role, contract)
                chosen = {subject: c for subject, c in choices.items() if c["model"]}
                outside = {
                    subject: c
                    for subject, c in choices.items()
                    if c["decider"]["kind"] == "external" and self.external is not None
                }
                if self.external is not None:
                    # A visitor from outside is decided for by the program that sent it, as its
                    # arrival recorded: nobody records a choice for it. Only a role whose subjects
                    # it is asks for it.
                    subjects = set(role.adapter.subjects(row["state"]))
                    for subject, described in arrival_deciders(row["state"]).items():
                        if subject in subjects:
                            outside.setdefault(subject, {"decider": described, "model": None})
                if chosen or outside:
                    chosen_roles.append((role, contract, chosen, outside))
            if not chosen_roles:
                return False
            decisions = SocietyDecisionRepository(society)
            for role, _contract, _chosen, _outside in chosen_roles:
                for request_id in decisions.unanswered_requests(role, claim.version_id):

                    def close(request_id: uuid.UUID = request_id) -> None:
                        with connection.transaction():
                            decisions.close_unanswered(claim.version_id, request_id)

                    _once_more_after_a_race(close)
            client = self.client
            asking_roles = [
                (role, contract, chosen)
                for role, contract, chosen, _outside in chosen_roles
                if chosen
                and client is not None
                and host_refusal(role, client, self.manifest, contract) is None
            ]
            outside_roles = [
                (role, contract, outside)
                for role, contract, _chosen, outside in chosen_roles
                if outside
            ]
            if not asking_roles and not outside_roles:
                return False
            planned = []
            spent = self._spent_providers(connection, claim.workspace_id) if asking_roles else ()
            for role, contract, chosen in asking_roles:
                assert client is not None
                due = self._due(role, contract, chosen, row["state"], client, spent)
                if due:
                    planned.append((role, contract, lease_ends, due))
            outside_planned = []
            for role, contract, outside in outside_roles:
                present = set(role.adapter.subjects(row["state"]))
                # An adapter may ask an outside program more often than a model.
                outside_due = getattr(role.adapter, "due_from_outside", role.adapter.due)
                due_outside = [
                    subject
                    for subject in sorted(outside)
                    if subject in present and outside_due(row["state"], subject)
                ]
                if due_outside:
                    outside_planned.append((role, contract, due_outside, outside))
            if not planned and not outside_planned:
                return True
            # Asked under the workspace's own rules, which also decide what may be offered.
            asking = (
                None
                if client is None or not planned
                else client.with_policy(self.policy_for(claim.workspace_id))
            )
            # Outside programs' requests are reserved first, each door's statement waited for no
            # later than its role's asks may end, so no door's time is taken from a model's ask
            # window, which is set after its own reservation below.
            outside_reserved = []
            for role, contract, due_outside, outside in outside_planned:
                if self._ends_at(contract, lease_ends) <= time.monotonic():
                    continue
                try:
                    outside_asks, outside_refused = self._outside_reserved(
                        connection,
                        claim,
                        society,
                        decisions,
                        row,
                        role,
                        contract,
                        due_outside,
                        outside,
                        lease_ends,
                    )
                except Exception as exc:
                    _LOG.error(
                        "A %s outside reservation failed with %s", role.key, _error_class(exc)
                    )
                    continue
                outside_reserved.append((outside_asks, outside_refused))
            # Each role's requests are reserved in a transaction of its own, asked again on its
            # own after a race: another role's committed reservations are never read again, where
            # an existing request is not fresh and would go unasked.
            reserved = []
            for role, contract, _lease_ends, due in planned:
                # A lease with no time left makes no request. The actual ask window is set
                # after reservation, so time spent reserving cannot borrow another role's time.
                if self._ends_at(contract, lease_ends) <= time.monotonic():
                    continue
                assert asking is not None and client is not None
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
                    assert client is not None
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
        # No connection from the reservations survives here: models and outside programs are
        # asked without one.
        result_groups = self._asked_by_every_role(asking, reserved, claim, outside_reserved)
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
                        # and on the last try recorded as decision_sources_unavailable. One
                        # answer that cannot be recorded costs its own subject alone; the next
                        # minute closes its request as unanswered.
                        try:
                            asked_again_after_a_race(finish)
                        except psycopg.OperationalError:
                            raise
                        except Exception as exc:
                            _LOG.error("A decision recording failed with %s", _error_class(exc))
            except Exception as exc:
                # A broken connection cannot drop another role's answers. Open its own session
                # for the next role.
                _LOG.error("A decision recording failed with %s", _error_class(exc))
        return True

    def _outside_reserved(
        self,
        connection: psycopg.Connection,
        claim: ControlClaim,
        society: SocietyRepository,
        decisions: SocietyDecisionRepository,
        row: dict[str, Any],
        role: DecisionRole,
        contract: DecisionContract,
        due: Sequence[str],
        outside: Mapping[str, Mapping[str, Any]],
        lease_ends: float,
    ) -> tuple[list[OutsideAsk], list[tuple[uuid.UUID, dict[str, Any]]]]:
        """``role``'s requests of outside programs for this minute: each due subject's request,
        reserved over the options the account holder's saved names leave sendable, with what its
        door states about the program; a subject its door refuses before asking is answered at
        once with that refusal, and the rest are asked. Nothing is reserved for a question a saved
        name would change, and a subject is left unasked this minute, the routine deciding, when
        its door's statement is malformed or comes after its role's asks must end, or when any
        text of its request would carry a saved name."""
        names = saved_names(connection, claim.workspace_id)
        latest = society._chain(row)
        document = society._inputs(row, [latest])[latest]
        labels = sorted(
            {
                option.label
                for subject in due
                for option in role.adapter.options(
                    role, row["state"], document, subject, contract, seed=row["seed"]
                )
            }
        )
        sendable = outside_sendable_labels(names, role, labels, row["engine_version"])
        if sendable is None:
            return [], []
        stated = self._stated(
            claim, role, contract, due, outside, self._ends_at(contract, lease_ends)
        )

        def reserve() -> tuple[list[OutsideAsk], list[tuple[uuid.UUID, dict[str, Any]]]]:
            asks: list[OutsideAsk] = []
            refused: list[tuple[uuid.UUID, dict[str, Any]]] = []
            with connection.transaction():
                for subject in due:
                    if subject not in stated:
                        continue
                    config, refusal = stated[subject]
                    try:
                        # A savepoint: a request that would carry a saved name is undone alone.
                        with connection.transaction():
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
                                provider_config=config,
                                offer=_only(sendable),
                                withhold=without_named_lines(names),
                            )
                            request = reserved["request"]
                            if (
                                fresh
                                and request is not None
                                and refusal is None
                                and not outside_context_sendable(names, request["context"])
                            ):
                                raise _NotSendable
                    except _NotSendable:
                        continue
                    if not fresh or request is None:
                        continue
                    request_id = uuid.UUID(request["request_id"])
                    if refusal is not None:
                        refused.append((request_id, _refused(refusal)))
                        continue
                    asks.append(
                        OutsideAsk(
                            role,
                            request,
                            config["deadline_ms"],
                            self._latest(contract, lease_ends),
                            tuple(names),
                        )
                    )
            return asks, refused

        return _once_more_after_a_race(reserve)

    def _stated(
        self,
        claim: ControlClaim,
        role: DecisionRole,
        contract: DecisionContract,
        due: Sequence[str],
        outside: Mapping[str, Mapping[str, Any]],
        ends_at: float,
    ) -> dict[str, tuple[dict[str, Any], str | None]]:
        """What each due subject's door states about its program, asked at once with no lock
        held and waited for no later than ``ends_at``. A statement that is malformed, names
        another program, gives a deadline past the contract's, raises or comes late leaves its own
        subject unasked this minute, and no other."""
        external = self.external
        assert external is not None
        if not due or ends_at <= time.monotonic():
            return {}
        pool = ThreadPoolExecutor(max_workers=min(len(due), _OUTSIDE_ASKS_AT_ONCE))
        try:
            futures = [
                (
                    subject,
                    pool.submit(
                        external.configuration,
                        claim.workspace_id,
                        claim.world_id,
                        subject,
                        outside[subject]["decider"],
                    ),
                )
                for subject in due
            ]
            stated: dict[str, tuple[dict[str, Any], str | None]] = {}
            for subject, future in futures:
                try:
                    told, refusal = future.result(timeout=max(0.0, ends_at - time.monotonic()))
                    stated[subject] = _door_statement(
                        contract, outside[subject]["decider"], told, refusal
                    )
                except TimeoutError:
                    _LOG.error("A %s door stated nothing before its asks had to end", role.key)
                except Exception as exc:
                    _LOG.error(
                        "A %s door's statement was refused with %s", role.key, _error_class(exc)
                    )
            return stated
        finally:
            # A door that does not return in time is not waited for: its statement is dropped.
            pool.shutdown(wait=False, cancel_futures=True)

    def _due(
        self,
        role: DecisionRole,
        contract: DecisionContract,
        chosen: Mapping[str, Mapping[str, Any]],
        state: Mapping[str, Any],
        client: ModelClient,
        spent: Collection[str] = (),
    ) -> list[tuple[str, Mapping[str, Any], ModelSpec, AnsweringMechanism]]:
        """Each chosen subject of ``role`` at a choice point whose model this host may ask, and
        whose provider's allowance (``spent``, the providers admission would refuse) remains."""
        present = set(role.adapter.subjects(state))
        due = []
        for subject, choice in sorted(chosen.items()):
            if subject not in present or not role.adapter.due(state, subject):
                continue
            if choice["model"]["provider"] in spent:
                continue
            askable = _askable(role, self.manifest, contract, choice["model"]["model_id"])
            if (
                askable is None
                or model_refusal(role, client, self.manifest, contract, choice["model"]) is not None
            ):
                continue
            due.append((subject, choice, *askable))
        return due

    def _spent_providers(
        self, connection: psycopg.Connection, workspace: uuid.UUID
    ) -> frozenset[str]:
        """The providers the durable authority would refuse the workspace's next attempt of, read
        once for the claim; none where nothing reads it or the read fails (admission still
        refuses each attempt, as before)."""
        if self.spending_refusals is None:
            return frozenset()
        try:
            with connection.transaction():
                refusals = self.spending_refusals(connection, workspace)
        except Exception as exc:
            # Never the exception's text, which may carry a connection string.
            _LOG.warning("the spending state could not be read: %s", type(exc).__qualname__)
            return frozenset()
        if refusals is None:
            return frozenset()
        return frozenset(
            provider for provider, refused in refusals.by_provider.items() if refused is not None
        )

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
            (key, model_id): sendable_labels(
                roles[key], asking, model_id, sorted(found), row["engine_version"]
            )
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
        # The names no line may carry, read once for the role's asks of this minute.
        names = tuple(saved_names(connection, claim.workspace_id))
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
                        "prompt_version": role.terms(row["engine_version"]).prompt_version,
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
                asks.append(
                    RoleAsk(
                        role,
                        request,
                        spec,
                        mechanism,
                        names if role.takes_line(request["context"]) else (),
                    )
                )
        return asks, refused

    def _asked_by_every_role(
        self,
        client: ModelClient | None,
        reserved: Sequence[
            tuple[DecisionContract, float, list[RoleAsk], list[tuple[uuid.UUID, dict[str, Any]]]]
        ],
        claim: ControlClaim | None = None,
        outside: Sequence[tuple[list[OutsideAsk], list[tuple[uuid.UUID, dict[str, Any]]]]] = (),
    ) -> list[list[tuple[uuid.UUID, dict[str, Any]]]]:
        """Every role's asks at once, each by its own deadline, so no role waits for another's;
        then each role's results, refusals first, in the order its requests were reserved: the
        models' groups first, then the outside programs' groups, which their own threads ask
        beside the models' with no model client."""
        outside_asks = [asked for asks, _refused in outside for asked in asks]
        outside_futures: list[tuple[float, Future[dict[str, Any]]]] = []
        outside_pool = (
            ThreadPoolExecutor(max_workers=min(len(outside_asks), _OUTSIDE_ASKS_AT_ONCE))
            if outside_asks
            else None
        )
        try:
            if outside_pool is not None:
                assert claim is not None
                now = time.monotonic()
                for asked in outside_asks:
                    ends_at = asked.ends_at(now)
                    outside_futures.append(
                        (ends_at, outside_pool.submit(self._outside_answer, claim, asked, ends_at))
                    )
            results = DecisionHost._models_asked(client, reserved)
            answered = iter(outside_futures)
            for asks, refused in outside:
                group = list(refused)
                for asked in asks:
                    ends_at, future = next(answered)
                    try:
                        result = future.result(timeout=max(0.0, ends_at - time.monotonic()))
                    except TimeoutError:
                        result = _refused("no_answer_in_time")
                    except Exception as exc:
                        _LOG.error("An outside decision ask failed with %s", _error_class(exc))
                        result = _refused("decider_disconnected")
                    group.append((uuid.UUID(asked.request["request_id"]), result))
                results.append(group)
            return results
        finally:
            if outside_pool is not None:
                # A door that ignores its deadline is not waited for: its late answer is dropped.
                outside_pool.shutdown(wait=False, cancel_futures=True)

    def _outside_answer(
        self, claim: ControlClaim, asked: OutsideAsk, ends_at: float
    ) -> dict[str, Any]:
        """An outside program's answer through its door, held to what a receipt records of it:
        one offered label or none, for a reason the role records, with the program's own record.
        ``no_answer_in_time`` when no time was left to ask or the answer came after ``ends_at``;
        ``decider_disconnected`` when the answer is not one a receipt may record, so a malformed
        answer costs its own subject alone."""
        external = self.external
        assert external is not None
        if ends_at <= time.monotonic():
            return _refused("no_answer_in_time")
        answered = external.answer(claim.workspace_id, claim.world_id, asked.request, ends_at)
        if time.monotonic() > ends_at:
            return _refused("no_answer_in_time")
        try:
            if not isinstance(answered, Mapping) or set(answered) != _ANSWER_KEYS:
                raise ValueError("an answer states exactly status, reason, proposal and provider")
            result = dict(answered)
            if result["status"] not in _ANSWER_STATUSES:
                raise ValueError("an answer is accepted, rejected or unavailable")
            if _line_out_of_bounds(asked, result):
                # An offered option answered with a line that breaks the line rule, or with none
                # where it says something, is the program's answer, rejected by name: never a
                # quiet minute, which only no connection or no answer in time is.
                result = {**result, "status": "rejected", "reason": "line_out_of_bounds"}
                result["proposal"] = None
            check_role_result(asked.role, result, asked.request)
        except Exception as exc:
            _LOG.error("A %s outside answer was refused with %s", asked.role.key, _error_class(exc))
            return _refused("decider_disconnected")
        line = (result["proposal"] or {}).get("line")
        if line is not None and recognised_spans(line, asked.names):
            # A program's line carrying a name the account holder saved is not said: no right
            # releases a saved name to the world from outside. Its answer stays on the record.
            return {
                **result,
                "status": "rejected",
                "reason": "line_refused_by_rules",
                "proposal": None,
            }
        return result

    @staticmethod
    def _models_asked(
        client: ModelClient | None,
        reserved: Sequence[
            tuple[DecisionContract, float, list[RoleAsk], list[tuple[uuid.UUID, dict[str, Any]]]]
        ],
    ) -> list[list[tuple[uuid.UUID, dict[str, Any]]]]:
        """Every role's model asks at once, each by its own deadline; then each role's results,
        refusals first, in the order its requests were reserved."""
        # One executor bounds calls across all roles. The first pass gives each role a slot
        # before any role's second ask, so a slow role cannot consume the entire pool first.
        active = [item for item in reserved if item[2]]
        if not active or client is None:
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
        return min(
            time.monotonic() + contract.value("decision_deadline_ms") / 1000,
            DecisionHost._latest(contract, lease_ends),
        )

    @staticmethod
    def _latest(contract: DecisionContract, lease_ends: float) -> float:
        """The latest any ask of a role may end: what the lease leaves the minute to commit in."""
        return lease_ends - (LEASE_SECONDS - contract.value("decision_deadline_ms") / 1000)

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
