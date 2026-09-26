"""A comparison's asking, as its runner judges room for it before each minute.

The playback host keeps part of the process's model budget back for the process's other work, the
Companion and ingestion among them. A comparison runs in a process of its own that does nothing
else, so its runner judges room on the whole budget, still on what is spent: a model is asked while
one ask of it fits, and a run the budget no longer fits stops by name. The words a failed run is
read with are held to the codes it may fail by.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from exulanica.api.society_comparison_runner import (
    RUN_FAILURE_CODES,
    _Asking,
    _RunStopped,
)
from exulanica.api.society_person_decisions import ask_bound_usd, model_refusal
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.usage import CallUsage
from exulanica.world.society_decision_contract import DecisionOption, decision_contract

from comparison_support import model_arm
from model_fakes import FakeTransport, RecordingPolicy

MANIFEST = load_manifest()
CONTRACT = decision_contract()
ARM = model_arm("candidate")
SPEC = MANIFEST.offered(Role.SOCIETY_DECISION, ARM["decider"]["model_id"])
DUE = {
    "someone": (
        DecisionOption("resting on a bench, 5 m away", "target", "go", "t", "rest", 5000),
        DecisionOption(CONTRACT.words["wait"], "wait", "wait", None, None, None),
    )
}


def _spend(budget: BudgetGuard, usd: Decimal) -> None:
    budget.record(
        CallUsage(
            role=Role.SOCIETY_DECISION,
            model_id=SPEC.model_id,
            provider=SPEC.provider,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
            cached_prompt_tokens=0,
            usd=usd,
        )
    )


def test_a_comparison_asks_on_the_whole_budget_where_the_host_keeps_part_back():
    budget = BudgetGuard(ceiling_usd=Decimal("0.02"), max_calls=100)
    client = ModelClient(
        api_key="test-key-not-real", manifest=MANIFEST, transport=FakeTransport(), budget=budget
    )
    need = ask_bound_usd(budget, SPEC, CONTRACT)
    # What is left fits one ask, but not above the part the host keeps for other work.
    _spend(budget, budget.ceiling_usd - need - Decimal("0.00001"))
    model = {"provider": SPEC.provider, "model_id": SPEC.model_id}
    # The positive control: the host's own rule refuses this model now.
    assert model_refusal(client, MANIFEST, CONTRACT, model) == "process_share_spent"
    asking = _Asking(
        client.with_policy(RecordingPolicy()), MANIFEST, CONTRACT, SPEC, ARM["provider_config"]
    )
    assert asking.offerable(0, DUE) == {"someone": frozenset(o.label for o in DUE["someone"])}
    _spend(budget, Decimal("0.00002"))
    with pytest.raises(_RunStopped) as stopped:
        asking.offerable(1, DUE)
    assert stopped.value.code == "process_budget_spent"


def test_a_run_fails_only_by_a_stated_code():
    assert "process_budget_spent" in RUN_FAILURE_CODES
    with pytest.raises(ValueError, match="stated code"):
        _RunStopped("model_was_slow")
