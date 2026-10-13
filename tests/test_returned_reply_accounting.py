"""A returned body is priced and releases its reservation before its identity is believed."""

from decimal import Decimal

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.response import record_reply_usage
from exulanica.models.usage import CostBasis


@pytest.mark.parametrize("body", [None, {"usage": "malformed"}, {"usage": {"prompt_tokens": True}}])
def test_unpriced_returned_body_keeps_the_existing_bound_and_releases_the_hold(body):
    spec = load_manifest()[Role.REASONING_MID].primary
    budget = BudgetGuard(ceiling_usd=Decimal("1"), max_calls=2)
    reserved = budget.reserve(spec, role=Role.REASONING_MID, prompt_chars=200, max_tokens=2048)
    usage = record_reply_usage(
        budget,
        role=Role.REASONING_MID,
        spec=spec,
        body=body,
        cache_hit=False,
        used_fallback=False,
        latency_s=0.1,
        usd_bound=reserved,
    )
    assert usage.cost_basis is CostBasis.UNKNOWN
    assert usage.usd >= reserved
    assert budget.billed_calls == 1 and budget.held_calls == 0
    assert budget.held_usd == 0


def test_priced_body_is_counted_once_without_reading_the_untrusted_answer():
    spec = load_manifest()[Role.REASONING_MID].primary
    budget = BudgetGuard(ceiling_usd=Decimal("1"), max_calls=2)
    reserved = budget.reserve(spec, role=Role.REASONING_MID, prompt_chars=200, max_tokens=2048)
    usage = record_reply_usage(
        budget,
        role=Role.REASONING_MID,
        spec=spec,
        body={
            "model": "unexpected/variant",
            "choices": "malformed",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        },
        cache_hit=False,
        used_fallback=False,
        latency_s=0.1,
        usd_bound=reserved,
    )
    assert usage.cost_basis is CostBasis.REPORTED
    assert usage.prompt_tokens == 10 and usage.completion_tokens == 20
    assert budget.billed_calls == 1 and budget.held_calls == 0
    assert budget.held_usd == 0
