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
"""

from __future__ import annotations

import datetime as dt
import time
import uuid
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

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
from exulanica.models.manifest import load_manifest
from exulanica.models.spending import spending_request_key
from exulanica.world.society import society_state_sha256
from exulanica.world.society_decision_asks import (
    MAX_BOUND_USD,
    DecisionAskRefused,
    Recorded,
    earlier_ask,
    record,
    reproduced,
)

__all__ = ["ModelNotAsked", "ask_again"]

#: How long an ask's bound stays open: one ask's deadline, with room.
_BOUND_MINUTES = 10


class ModelNotAsked(ValueError):
    """The chosen model is not asked for this role here, by the code a choice is refused with."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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
    client = services.decision_client
    if client is None:
        raise ModelNotAsked("provider_not_admitted")
    with reading() as connection:
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
        labels = [option["label"] for option in context["options"]]
        sendable = sendable_labels(role, policed, model["model_id"], labels, held.engine)
        if sendable is None or set(sendable) != set(labels):
            raise DecisionAskRefused("not_the_same_request")
        names = saved_names(connection, workspace_id)
    least = ask_bound_usd(role, policed.budget, spec, contract)
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
