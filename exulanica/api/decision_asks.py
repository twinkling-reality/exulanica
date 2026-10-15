"""Asking another model a recorded decision again, as the host would have asked it, and keeping the
answer beside the original (:mod:`exulanica.world.society_decision_asks`, migration 0216).

One ask is one live ask (:func:`exulanica.api.decision_host.ask`, its retries and line rules
included) of the chosen model, through the workspace's own request rules for a person's decisions
(:meth:`~exulanica.api.services.Services.person_decision_policy`), under the bound the person states
(at most :data:`~exulanica.world.society_decision_asks.MAX_BOUND_USD`): a part of the process's
budget always, and under durable spending a bound of the workspace's grant too, keyed
``decision-ask:<ask_id>``, so it never meets the society's own keys. The model is held to what a
person may choose for the role, as the choice route holds it, and every option the request offered
must be sent to it as it was. Nothing is applied: the answer is recorded and read, never consumed by
a minute.

The model is asked outside any transaction: the request is read and proved first, then asked, then
the answer recorded, under its request's foreign key, which waits for or fails against a society
being erased meanwhile.

:func:`ask_again_offer` states what asking a person's recorded decisions again would be, asking and
writing nothing: for each, the least bound an ask of the chosen model and an ask of the model that
answered it need, by the same checks an ask makes before it reserves (:func:`_asking`), and their
sum, the most the comparison can cost.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any, Final

import psycopg

from exulanica.api.decision_host import (
    RoleAsk,
    ask,
    ask_bound_usd,
    model_refusal,
    question_refusal,
    sendable_labels,
)
from exulanica.epistemics.saved_names import saved_names
from exulanica.models.budget import BoundedBudget
from exulanica.models.manifest import AnsweringMechanism, ModelSpec, load_manifest
from exulanica.models.spending import spending_request_key
from exulanica.models.usage import USD_QUANTUM, usd_string
from exulanica.world.society import society_state_sha256
from exulanica.world.society_decision_asks import (
    ASK_AGAIN_MOST,
    MAX_BOUND_USD,
    DecisionAskRefused,
    Recorded,
    Reproduced,
    earlier_ask,
    record,
    reproduced,
)

__all__ = ["ModelNotAsked", "ask_again", "ask_again_offer"]

#: How long an ask's bound stays open: one ask's deadline, with room.
_BOUND_MINUTES = 10


class ModelNotAsked(ValueError):
    """The chosen model is not asked for this role here, by the code a choice is refused with."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


#: Refusals of a model that depend on one decision's recorded contract (whether the contract can ask
#: the model at all, and whether one ask under it still fits the budget): an offer records them on
#: that decision, so a person whose decisions span two contracts is offered those that can be asked.
_CONTRACT_REFUSALS: Final = frozenset(
    {"model_no_longer_offered", "process_budget_spent", "process_share_spent"}
)


def _bound(value: Decimal) -> Decimal:
    """A least bound at the ledger's quantum, rounded up, so the bound an offer names is never
    below what the ask needs."""
    return value.quantize(USD_QUANTUM, rounding=ROUND_CEILING)


@dataclass(frozen=True, slots=True)
class _Asking:
    """An ask of one model, proved sendable: the model, the mechanism it answers by, the client
    under the workspace's request rules, and the least the ask's bound may be."""

    spec: ModelSpec
    mechanism: AnsweringMechanism
    policed: Any
    least: Decimal


def _asking(
    services: Any,
    held: Recorded,
    proved: Reproduced,
    connection: Any,
    workspace_id: uuid.UUID,
    model: Mapping[str, str],
) -> _Asking:
    """Every check an ask of ``model`` makes before anything is reserved: a model the role may not
    be asked by here (:class:`ModelNotAsked`), and a request it would not be sent whole
    (``not_the_same_request``)."""
    role, contract = proved.role, proved.contract
    client = services.decision_client
    if client is None:
        raise ModelNotAsked("provider_not_admitted")
    manifest = services.workspace_choice_manifest(connection, workspace_id, held.engine)
    spec = manifest.models.get(model["model_id"])
    if spec is None:
        raise ModelNotAsked("model_not_declared")
    if spec.provider != model["provider"]:
        raise ModelNotAsked("provider_changed")
    if model["model_id"] not in load_manifest().models:
        client = client.with_chosen_manifest(
            manifest,
            {
                key: (role.key, role.terms(held.engine).prompt_version)
                for key in manifest.models.keys() - load_manifest().models.keys()
            },
        )
    refusal = model_refusal(role, client, manifest, contract, model)
    policed = client.with_policy(services.person_decision_policy(workspace_id))
    if refusal is None:
        refusal = question_refusal(role, policed, model["model_id"], held.engine)
    if refusal is not None:
        raise ModelNotAsked(refusal)
    mechanism = contract.mechanism_for(spec)
    if mechanism is None:
        raise ModelNotAsked("model_no_longer_offered")
    labels = [option["label"] for option in held.request["context"]["options"]]
    sendable = sendable_labels(role, policed, model["model_id"], labels, held.engine)
    if sendable is None or set(sendable) != set(labels):
        raise DecisionAskRefused("not_the_same_request")
    return _Asking(spec, mechanism, policed, ask_bound_usd(role, policed.budget, spec, contract))


def ask_again(
    services: Any,
    held: Recorded,
    reading: Callable[[], Any],
    *,
    workspace_id: uuid.UUID,
    model: Mapping[str, str],
    bound_usd: Decimal,
    asked_by: uuid.UUID,
    idempotency_key: uuid.UUID | None,
    writing: Callable[[], Any],
) -> dict[str, Any]:
    """Ask ``model`` the request ``held`` names, and record its answer beside the original.

    ``reading`` opens a short connection for the checks, and ``writing`` one for the record and the
    idempotency read. Refused by name before anything is reserved: the request not reproducible
    (:class:`~exulanica.world.society_decision_asks.DecisionAskRefused`), a model the role may not
    be asked by here (:class:`ModelNotAsked`), and a bound out of range. A repeated idempotency key
    answers the ask it first made, and asks nothing."""
    if idempotency_key is not None:
        with writing() as connection:
            earlier = earlier_ask(
                connection, workspace_id, held.society_id, asked_by, idempotency_key
            )
        if earlier is not None:
            return earlier
    proved = reproduced(held)
    role, contract = proved.role, proved.contract
    context = held.request["context"]
    with reading() as connection:
        asking = _asking(services, held, proved, connection, workspace_id, model)
        names = saved_names(connection, workspace_id)
    spec, mechanism, policed, least = asking.spec, asking.mechanism, asking.policed, asking.least
    if not (bound_usd.is_finite() and least <= bound_usd <= MAX_BOUND_USD):
        raise DecisionAskRefused(
            "bound_out_of_range", f"an ask of this model needs {least} to {MAX_BOUND_USD} USD"
        )
    ask_id = uuid.uuid4()
    calls = contract.value("answer_attempts_maximum")
    # The stated bound as a part of the process's own budget, which holds in every spending mode;
    # under durable spending, as a bound of the workspace's grant too.
    bounded = policed.with_bound(
        BoundedBudget(policed.budget, ceiling_usd=bound_usd, max_calls=calls)
    )
    durable = services.spending
    bound_id = None
    if durable is not None:
        bound_id = durable.open_bound(
            workspace_id,
            provider=spec.provider,
            key=f"decision-ask:{ask_id}",
            ceiling_usd=bound_usd,
            max_calls=calls,
            valid_until=dt.datetime.now(dt.UTC) + dt.timedelta(minutes=_BOUND_MINUTES),
            reason="A person asks another model a recorded decision again, never applied.",
        )
        bounded = bounded.with_spending(durable.for_workspace(workspace_id).within(bound_id))
    try:
        ends_at = time.monotonic() + contract.value("decision_deadline_ms") / 1000
        with spending_request_key(f"decision-ask:{ask_id}"):
            # The live ask's body, under this ask's own key rather than the request's.
            answer = ask.__wrapped__(
                bounded, RoleAsk(role, held.request, spec, mechanism, names), contract, ends_at
            )
    finally:
        if durable is not None and bound_id is not None:
            durable.close_bound(workspace_id, bound_id, reason="the ask ended")
    messages = society_state_sha256(role.adapter.messages(role, context, mechanism))
    with writing() as connection:
        try:
            return record(
                connection,
                workspace_id,
                held,
                ask_id=ask_id,
                asked_by=asked_by,
                idempotency_key=idempotency_key,
                spec=spec,
                mechanism=mechanism,
                prompt_version=proved.terms.prompt_version,
                messages_sha256=messages,
                request_messages_sha256=proved.messages_sha256,
                bound_id=bound_id,
                bound_usd=bound_usd,
                answer=answer,
            )
        except psycopg.errors.UniqueViolation:
            # The same key asked twice at once: the first to record is the ask; this answer, paid
            # for under its own bound, is not kept.
            connection.rollback()
            assert idempotency_key is not None
            earlier = earlier_ask(
                connection, workspace_id, held.society_id, asked_by, idempotency_key
            )
            assert earlier is not None
            return earlier


def ask_again_offer(
    services: Any,
    found: Sequence[Recorded],
    reading: Callable[[], Any],
    *,
    workspace_id: uuid.UUID,
    model: Mapping[str, str],
) -> dict[str, Any]:
    """What asking ``found`` again would be, asking and writing nothing.

    Each recorded decision, oldest first, with what it chose and said and the model that answered
    it, and either the least bound of an ask of ``model`` and of an ask once more of its own model
    (``ask_usd``; ``again`` is None where its own model is no longer asked here, with why in
    ``again_refusal``), or why it cannot be asked again (``refusal``: the request no longer sent as
    it was, or a refusal of ``model`` that depends on that decision's contract). ``most_usd`` is the
    sum of every bound offered: the most the comparison can cost. Where ``model`` itself may not be
    asked here whatever the decision, the offer's ``refusal`` names why and nothing is offered."""
    decisions: list[dict[str, Any]] = []
    refusal: str | None = None
    most = Decimal(0)
    with reading() as connection:
        for held in found:
            answer = held.decision or {}
            said_provider, said_proposal = answer.get("provider"), answer.get("proposal")
            provider = said_provider if isinstance(said_provider, Mapping) else {}
            proposal = said_proposal if isinstance(said_proposal, Mapping) else {}
            own = {"provider": provider.get("provider"), "model_id": provider.get("model_id")}
            entry: dict[str, Any] = {
                "request_id": str(held.request["request_id"]),
                "base_tick": held.request.get("base_tick"),
                "provider": own["provider"],
                "model_id": own["model_id"],
                "chose": proposal.get("label"),
                "line": proposal.get("line"),
                "ask_usd": None,
                "refusal": None,
                "again_refusal": None,
            }
            try:
                proved = reproduced(held)
                chosen = _asking(services, held, proved, connection, workspace_id, model)
            except DecisionAskRefused as refused:
                entry["refusal"] = refused.code
                decisions.append(entry)
                continue
            except ModelNotAsked as refused:
                if refused.code in _CONTRACT_REFUSALS:
                    entry["refusal"] = refused.code
                    decisions.append(entry)
                    continue
                refusal = refused.code
                break
            again: Decimal | None = None
            if isinstance(own["provider"], str) and isinstance(own["model_id"], str):
                try:
                    again = _bound(
                        _asking(services, held, proved, connection, workspace_id, own).least
                    )
                except (ModelNotAsked, DecisionAskRefused) as refused:
                    entry["again_refusal"] = refused.code
            least = _bound(chosen.least)
            entry["ask_usd"] = {
                "chosen": usd_string(least),
                "again": None if again is None else usd_string(again),
            }
            most += least + (again or Decimal(0))
            decisions.append(entry)
    if refusal is not None:
        decisions, most = [], Decimal(0)
    return {
        "most": ASK_AGAIN_MOST,
        "model": {"provider": model["provider"], "model_id": model["model_id"]},
        "refusal": refusal,
        "decisions": decisions,
        "askable": sum(1 for entry in decisions if entry["ask_usd"] is not None),
        "most_usd": usd_string(most),
    }
