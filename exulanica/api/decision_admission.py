"""What a decision host admits before it reserves anything or lets anything be said.

Whether it may ask at all: :func:`host_refusal` says why a process asks no model for a role and
:func:`model_refusal` why a subject's chosen model is not asked here, each by a code from
:data:`HOST_REFUSALS` or :data:`MODEL_REFUSALS` that the page has words for, and both rest on what
one ask may reserve (:func:`ask_bound_usd`, :func:`smallest_ask_usd`), the most a model may write
in one answer (:func:`answer_tokens`) and the share of the process's budget a role's decisions
leave for its other work (:func:`share_kept`). What may be sent and said, judged against the
names the account holder saved: a question the client's rules would change
(:func:`question_refusal`), the option labels a model or an outside program may be sent
(:func:`sendable_labels`, :func:`outside_sendable_labels`), an outside program's observation and
context (:func:`without_named_lines`, :func:`outside_context_sendable`) and a line a model wrote.
:mod:`exulanica.api.decision_host` asks.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from decimal import Decimal
from typing import Any, Final

from exulanica.epistemics.saved_names import SavedName, recognised_spans
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import PROVIDER_CREDENTIAL_ABSENT, ModelClient
from exulanica.models.errors import ManifestError
from exulanica.models.manifest import AnsweringMechanism, Manifest, ModelSpec
from exulanica.things.lines import LineRefused, check_line
from exulanica.world.decision_envelopes import request_bytes_at_most
from exulanica.world.decision_roles import DecisionContract, DecisionRole

#: Why a host asks no model for a workspace's subjects at all, by code; the page has words for each.
HOST_REFUSALS: Final = frozenset(
    {
        "models_not_run_here",
        "provider_credential_absent",
        "process_budget_spent",
        "process_share_spent",
        # The durable spending authority held closed until an operator acts, for every provider the
        # workspace spends with (Services.model_host_refusal): paused, not spent.
        "spending_suspended",
    }
)

#: Why a subject's chosen model is not asked here while the host asks others; the page has words.
MODEL_REFUSALS: Final = frozenset(
    {
        "model_no_longer_offered",
        "provider_changed",
        "provider_not_admitted",
        "provider_credential_absent",
        "provider_not_running",
        "process_budget_spent",
        "process_share_spent",
        "question_changed_by_rules",
    }
)


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


def _asked_terms(role: DecisionRole, contract: DecisionContract) -> list[Any]:
    """The terms asked under ``contract``: those naming its versions, else every terms the role
    states."""
    return [
        terms for terms in role.every_terms() if dict(terms.versions) == dict(contract.versions)
    ] or list(role.every_terms())


def request_tokens_at_most(role: DecisionRole, contract: DecisionContract) -> int | None:
    """The largest request one ask of ``role`` may send under ``contract``: the envelope of the
    terms asked, each byte a token (:mod:`exulanica.world.decision_envelopes`), or None where a
    terms the catalog names no envelope for is asked. What :func:`ask_bound_usd` reserves by, and
    what a models read says a model's context is measured against (G2)."""
    envelopes = [
        request_bytes_at_most(role.key, terms.prompt_version)
        for terms in _asked_terms(role, contract)
    ]
    stated = [envelope for envelope in envelopes if envelope is not None]
    return max(stated) if stated and len(stated) == len(envelopes) else None


def ask_bound_usd(
    role: DecisionRole, budget: BudgetGuard, spec: ModelSpec, contract: DecisionContract
) -> Decimal:
    """The most one ask of ``spec`` for ``role`` may reserve, whatever the subject's situation.

    Every answer the contract allows, each at the model's answer bound and the most its request may
    send: the envelope of the terms asked under this contract (every terms the role states where
    none names its versions), each byte a token (:mod:`exulanica.world.decision_envelopes`), so
    one engine's longer prompt never raises what an ask of another engine's holds. A terms the
    catalog names no envelope for is reserved as before, by the prompt's characters: its
    instruction, the note a retry adds and twice the largest situation a request may carry;
    tests/test_society_person_decisions.py holds the asks the small square makes under either.
    """
    asked = _asked_terms(role, contract)
    attempts = contract.value("answer_attempts_maximum")
    answer = answer_tokens(spec) or 0
    envelope = request_tokens_at_most(role, contract)
    if envelope is not None:
        return attempts * budget.estimate_usd(spec, extra_prompt_tokens=envelope, max_tokens=answer)
    prompt_chars = max(
        len(terms.instruction) + len(terms.not_offered) for terms in asked
    ) + 2 * contract.value("context_bytes_maximum")
    return attempts * budget.estimate_usd(spec, prompt_chars=prompt_chars, max_tokens=answer)


def smallest_ask_usd(
    role: DecisionRole,
    budget: BudgetGuard,
    manifest: Manifest,
    contract: DecisionContract,
    *,
    refused: Collection[str] = (),
) -> Decimal | None:
    """The least that one ask of an offered model may need, the smallest ``ask_bound_usd``. A
    process whose remainder is under it can ask no model for the role; None with none offered.
    ``refused`` names providers the asking client refuses, whose models it can never ask: a model
    on this computer that costs nothing is no ask a process whose allowlist refuses it can make."""
    bounds = [
        ask_bound_usd(role, budget, spec, contract)
        for spec in manifest.offered_models(role.chosen)
        if contract.mechanism_for(spec) is not None and spec.provider not in refused
    ]
    return min(bounds) if bounds else None


def offered_providers(
    role: DecisionRole, manifest: Manifest, contract: DecisionContract
) -> tuple[str, ...]:
    """The billed providers an ask for ``role`` can reach: those serving the models the manifest
    offers it and its contract can ask, each once, in the order the manifest offers them, whose
    allowance a durable authority spends. An ask reaches its chosen model's provider alone. A
    provider on this computer is left out: it takes no credential and its asks cost nothing, so
    no allowance of it is ever spent, and its being offered never keeps a role whose every billed
    allowance is spent from reading as spent."""
    return tuple(
        dict.fromkeys(
            spec.provider
            for spec in manifest.offered_models(role.chosen)
            if contract.mechanism_for(spec) is not None
            and manifest.provider(spec.provider).takes_credential
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
    listing, and ``spending_suspended``, the durable authority's (``Services.model_host_refusal``):
    no client, or a budget whose remainder, by what is spent, fits no ask of any offered
    model the client does not refuse (``smallest_ask_usd``), in the whole budget or once the part
    kept for the process's other work is set aside. Either holds until the process restarts. A
    model on this computer costs nothing, so while its provider is admitted only the call limit
    can refuse the host.
    """
    if client is None:
        return PROVIDER_CREDENTIAL_ABSENT
    smallest = smallest_ask_usd(
        role, client.budget, manifest, contract, refused=frozenset(client.refusals)
    )
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


def question_refusal(
    role: DecisionRole, client: ModelClient, model_id: str, engine: str | None = None
) -> str | None:
    """``question_changed_by_rules`` when the client's rules would change a question a subject
    asked of ``model_id`` is sent, one of the role's fixed choice descriptions; else None.
    ``engine`` names the society's engine, whose description alone is judged, as the host judges
    it; with none (a role no society hosts, such as a signal's controller), every description.

    A saved name one of whose parts is a word of a description would, and every ask would then be
    refused as it left, every minute: so nobody is asked, nothing is written, and the models route
    names it for each choice of that model.
    """
    descriptions = _descriptions(role, engine)
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


def without_named_lines(
    names: Sequence[SavedName],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """An observation for an outside program without the heard lines that carry a name the account
    holder saved, in the line or in who said it, nor the lines the being said that carry one, in
    the line or in whom it was said to: a name saved after a line was said, or one a
    right released to the speaker's model, never reaches a program outside the policy boundary,
    and one such line no longer stops the program being asked."""

    def withhold(context: dict[str, Any]) -> dict[str, Any]:
        heard = context.get("heard") or []
        said = context.get("said") or []
        kept = [
            line
            for line in heard
            if not recognised_spans(line["line"], names)
            and not recognised_spans(line["from"], names)
        ]
        # And the lines the being said itself, by the line or the one it was said to.
        own = [
            line
            for line in said
            if not recognised_spans(line["line"], names)
            and not (line["to"] is not None and recognised_spans(line["to"], names))
        ]
        if len(kept) == len(heard) and len(own) == len(said):
            return context
        withheld = {**context, "heard": kept}
        if "said" in context:
            if own:
                withheld["said"] = own
            else:
                withheld.pop("said")
        return withheld

    return withhold


def outside_context_sendable(names: Sequence[SavedName], context: Mapping[str, Any]) -> bool:
    """Whether a request's whole context may be sent to an outside program as it is: no text in
    any of its fields carries a name the account holder saved. A model's request passes the
    policy boundary, which redacts; an outside program's passes none, so one that would carry a
    name is not sent at all."""
    return not any(recognised_spans(text, names) for text in _texts(context))
