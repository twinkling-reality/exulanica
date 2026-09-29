"""A bounded part of the process's model budget: one piece of work's bound, held at every call.

A comparison started from the application is asked through a client whose calls are reserved
against a :class:`~exulanica.models.budget.BoundedBudget` (``ModelClient.with_bound``): a part of
the process's own guard with a ceiling of its own. What is shown: a call past the part's ceiling is
refused before any request is sent, while the same call through the process's client is sent (the
positive control); what the part spends is recorded in the process's ledger too, so the process's
ceiling still holds every call; and calls admitted at once never take the part past its ceiling
together.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from exulanica.models.budget import BoundedBudget, BudgetGuard
from exulanica.models.choice import ChoiceRequest
from exulanica.models.client import ModelClient
from exulanica.models.errors import BudgetBoundExceeded, BudgetExceededError
from exulanica.models.manifest import load_manifest
from exulanica.world.society_decision_contract import person_role

from model_fakes import FakeTransport, RecordingPolicy, chat_body

MANIFEST = load_manifest()
ROLE = person_role()
SPEC = MANIFEST.offered_models(ROLE.chosen)[0]
MESSAGES = [{"role": "user", "content": "choose"}]
REQUEST = ChoiceRequest(description=ROLE.choice_description, options=("wait here", "go there"))


class _Answers(FakeTransport):
    """A model that always answers the first option, by the call it is asked with."""

    def post_json(self, url, *, headers, payload, timeout):
        import json

        from exulanica.models.transport import HttpResponse

        self.requests.append({"url": url, "payload": dict(payload)})
        body = chat_body("", model=payload["model"], finish_reason="tool_calls")
        body["choices"][0]["message"]["content"] = None
        body["choices"][0]["message"]["tool_calls"] = [
            {
                "id": "c",
                "type": "function",
                "function": {"name": "act", "arguments": json.dumps({"action": "wait here"})},
            }
        ]
        return HttpResponse(200, json.dumps(body))


def _client(budget: BudgetGuard, transport: FakeTransport) -> ModelClient:
    return ModelClient(
        api_key="test-key-not-real", manifest=MANIFEST, transport=transport, budget=budget
    ).with_policy(RecordingPolicy())


def _choose(client: ModelClient) -> None:
    mechanism = ROLE.contract().mechanism_for(SPEC)
    assert mechanism is not None
    client.choose(
        ROLE.chosen,
        SPEC.model_id,
        MESSAGES,
        REQUEST,
        mechanism=mechanism,
        prompt_version=ROLE.prompt_version,
        timeout=5,
        max_tokens=SPEC.min_max_tokens,
    )


def _one_call(budget: BudgetGuard) -> Decimal:
    """What one of these calls reserves."""
    return budget.estimate_usd(
        SPEC, prompt_chars=len(str(MESSAGES)), max_tokens=SPEC.min_max_tokens or 0
    )


def test_a_call_past_the_bound_is_refused_before_it_is_sent_and_the_process_is_not():
    process = BudgetGuard(ceiling_usd=Decimal("1"), max_calls=100)
    transport = _Answers()
    # The positive control: the process's own client sends the call.
    _choose(_client(process, transport))
    assert len(transport.requests) == 1
    bound = BoundedBudget(process, ceiling_usd=Decimal("0.00000001"), max_calls=100)
    with pytest.raises(BudgetBoundExceeded):
        _choose(_client(process, transport).with_bound(bound))
    assert len(transport.requests) == 1, "nothing was sent past the bound"
    assert bound.refusals == 1
    assert (bound.held_usd, process.held_usd) == (Decimal(0), Decimal(0))


def test_what_the_part_spends_is_the_processs_spend_and_the_process_ceiling_holds():
    process = BudgetGuard(ceiling_usd=Decimal("1"), max_calls=100)
    transport = _Answers()
    bound = BoundedBudget(process, ceiling_usd=Decimal("0.5"), max_calls=100)
    bounded = _client(process, transport).with_bound(bound)
    _choose(bounded)
    assert bound.spent_usd > 0
    assert bound.spent_usd == process.spent_usd
    assert (bound.billed_calls, process.billed_calls) == (1, 1)
    # A process whose own ceiling cannot hold the next call refuses it through the part too.
    process.ceiling_usd = process.spent_usd
    with pytest.raises(BudgetExceededError) as refused:
        _choose(bounded)
    assert not isinstance(refused.value, BudgetBoundExceeded)
    assert len(transport.requests) == 1


def test_a_bound_is_a_part_of_the_budget_its_client_spends_from():
    process = BudgetGuard(ceiling_usd=Decimal("1"), max_calls=100)
    other = BudgetGuard(ceiling_usd=Decimal("1"), max_calls=100)
    with pytest.raises(ValueError, match="part of the budget"):
        _client(process, _Answers()).with_bound(
            BoundedBudget(other, ceiling_usd=Decimal("0.5"), max_calls=10)
        )


def _reserve(budget: BudgetGuard) -> Decimal:
    return budget.reserve(
        SPEC,
        role=ROLE.chosen.role,
        prompt_chars=len(str(MESSAGES)),
        max_tokens=SPEC.min_max_tokens or 0,
    )


def test_each_part_of_a_shared_bound_says_only_what_the_bound_refused_it():
    """Runs sharing a comparison's bound each ask through a part of it, so a refusal by the bound
    is said by the run whose call it refused, never by the other, and never for the process's own
    refusal, which a receipt records in the same words."""
    process = BudgetGuard(ceiling_usd=Decimal("1"), max_calls=100)
    one = _one_call(process)
    shared = BoundedBudget(process, ceiling_usd=one * 3 / 2, max_calls=100)
    first, second = (
        BoundedBudget(shared, ceiling_usd=shared.ceiling_usd, max_calls=shared.max_calls)
        for _ in range(2)
    )
    held = _reserve(first)
    with pytest.raises(BudgetBoundExceeded):
        _reserve(second)
    assert (first.refusals, second.refusals, shared.refusals) == (0, 1, 1)
    first.release(held)
    assert (first.held_usd, second.held_usd, shared.held_usd, process.held_usd) == (0, 0, 0, 0)
    # A part of a part asks through every ceiling on its way to the process's client.
    _choose(_client(process, _Answers()).with_bound(first))
    assert first.spent_usd == shared.spent_usd == process.spent_usd > 0
    # The process's own refusal, through a bound with room to spare, is no part's.
    process.ceiling_usd = process.spent_usd
    roomy = BoundedBudget(process, ceiling_usd=Decimal("1"), max_calls=100)
    part = BoundedBudget(roomy, ceiling_usd=roomy.ceiling_usd, max_calls=roomy.max_calls)
    with pytest.raises(BudgetExceededError) as refused:
        _reserve(part)
    assert not isinstance(refused.value, BudgetBoundExceeded)
    assert (part.refusals, roomy.refusals) == (0, 0)


def test_calls_admitted_at_once_never_pass_the_bound_together():
    """Reservations are held until recorded, so calls admitted at once, from one run or two sharing
    the bound, are refused past it however they interleave."""
    import threading

    process = BudgetGuard(ceiling_usd=Decimal("1"), max_calls=100)
    one = _one_call(process)
    bound = BoundedBudget(process, ceiling_usd=one * 3, max_calls=100)
    start = threading.Barrier(10)
    admitted: list[Decimal] = []
    refused: list[BaseException] = []

    def reserve() -> None:
        start.wait()
        try:
            admitted.append(
                bound.reserve(
                    SPEC,
                    role=ROLE.chosen.role,
                    prompt_chars=len(str(MESSAGES)),
                    max_tokens=SPEC.min_max_tokens or 0,
                )
            )
        except BudgetBoundExceeded as exc:
            refused.append(exc)

    threads = [threading.Thread(target=reserve) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert (len(admitted), len(refused), bound.refusals) == (3, 7, 7)
    assert bound.held_usd == process.held_usd == one * 3
    for reserved in admitted:
        bound.release(reserved)
    assert (bound.held_usd, process.held_usd) == (Decimal(0), Decimal(0))


def test_a_part_allows_some_spend():
    with pytest.raises(ValueError, match="at least one call"):
        BoundedBudget(BudgetGuard(), ceiling_usd=Decimal(0), max_calls=1)
    assert _one_call(BudgetGuard()) > 0
