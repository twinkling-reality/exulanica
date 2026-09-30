"""All hosted roles share one call pool while keeping their own bounds and receipts."""

from __future__ import annotations

import dataclasses
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace

import exulanica.api.decision_host as host_module
from exulanica.api.decision_host import DecisionHost, RoleAsk, share_kept
from exulanica.models.budget import BudgetGuard
from exulanica.models.manifest import AnsweringMechanism, load_manifest
from exulanica.world.decision_roles import decision_roles


def _asks(role, count):
    spec = next(iter(load_manifest().models.values()))
    return [
        RoleAsk(
            role,
            {"request_id": str(uuid.uuid4())},
            spec,
            AnsweringMechanism.TOOL_CALL,
        )
        for _ in range(count)
    ]


def test_roles_share_one_pool_and_keep_differing_contracts(monkeypatch):
    role_a = decision_roles().role("society_decision")
    role_b = dataclasses.replace(role_a, key="second_role")
    base = role_a.contract()
    contract_a = dataclasses.replace(
        base, policy={**base.policy, "concurrent_calls_maximum": 1, "process_reserve_percent": 25}
    )
    contract_b = dataclasses.replace(
        base, policy={**base.policy, "concurrent_calls_maximum": 2, "process_reserve_percent": 50}
    )
    budget = BudgetGuard(ceiling_usd=Decimal("1"), max_calls=100)
    client = SimpleNamespace(budget=budget)
    active = 0
    peak = 0
    by_role = {role_a.key: 0, role_b.key: 0}
    role_peak = dict(by_role)
    lock = threading.Lock()
    release = threading.Event()
    seen = []

    def fake_ask(_client, asked, contract, ends_at, *, keep_usd, keep_calls):
        nonlocal active, peak
        with lock:
            active += 1
            by_role[asked.role.key] += 1
            peak = max(peak, active)
            role_peak[asked.role.key] = max(role_peak[asked.role.key], by_role[asked.role.key])
            seen.append((asked.role.key, contract, ends_at, keep_usd, keep_calls))
        assert release.wait(2), "the pool did not release its first calls"
        with lock:
            active -= 1
            by_role[asked.role.key] -= 1
        return {"status": "accepted", "reason": "validated_choice"}

    monkeypatch.setattr(host_module, "ask", fake_ask)
    timer = threading.Timer(0.1, release.set)
    timer.start()
    try:
        result = DecisionHost._asked_by_every_role(
            None,
            client,
            [
                (contract_a, 10.0, _asks(role_a, 2), []),
                (contract_b, 20.0, _asks(role_b, 2), []),
            ],
        )
    finally:
        release.set()
        timer.join()
    assert [len(group) for group in result] == [2, 2]
    assert peak == 2, "the contracts' limits must not add to a process-wide pool"
    assert role_peak[role_a.key] == 1
    assert 1 <= role_peak[role_b.key] <= 2
    assert {
        (key, ends_at, keep_usd, keep_calls)
        for key, contract, ends_at, keep_usd, keep_calls in seen
        if contract in (contract_a, contract_b)
    } == {
        (role_a.key, 10.0, *share_kept(budget, contract_a)),
        (role_b.key, 20.0, *share_kept(budget, contract_b)),
    }


def test_a_failed_ask_in_one_role_keeps_another_roles_answer(monkeypatch):
    role_a = decision_roles().role("society_decision")
    role_b = dataclasses.replace(role_a, key="second_role")
    contract = role_a.contract()
    client = SimpleNamespace(budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=100))

    def fake_ask(_client, asked, _contract, _ends_at, *, keep_usd, keep_calls):
        if asked.role.key == role_a.key:
            raise RuntimeError("one role's ask failed")
        return {"status": "accepted", "reason": "validated_choice"}

    monkeypatch.setattr(host_module, "ask", fake_ask)
    results = DecisionHost._asked_by_every_role(
        None,
        client,
        [(contract, 10.0, _asks(role_a, 1), []), (contract, 20.0, _asks(role_b, 1), [])],
    )
    assert results[0][0][1]["reason"] == "model_call_failed"
    assert results[1][0][1]["reason"] == "validated_choice"


def test_direct_traffic_asks_obey_the_role_ceiling_beside_society_asks():
    traffic = decision_roles().deciding_for("signal")
    person = decision_roles().deciding_for("person")
    roles = [traffic] * 4 + [person] * 2
    spec = next(iter(load_manifest().models.values()))
    lock = threading.Lock()
    release = threading.Event()
    entered = threading.Event()
    active = {traffic.key: 0, person.key: 0}
    peak = dict(active)

    class Client:
        def with_attempts(self, _heard):
            return self

        def choose(self, _chosen, _model_id, messages, _request, **_kwargs):
            key = messages[0]["content"]
            with lock:
                active[key] += 1
                peak[key] = max(peak[key], active[key])
                if (
                    active[traffic.key] == traffic.contract().value("concurrent_calls_maximum")
                    and active[person.key] >= 1
                ):
                    entered.set()
            assert release.wait(20)
            with lock:
                active[key] -= 1
            raise RuntimeError("controlled failure")

    def one(role):
        contract = role.contract()
        adapter = SimpleNamespace(
            messages=lambda held, _context, _mechanism: [{"role": "user", "content": held.key}]
        )
        held = dataclasses.replace(role, adapter=adapter)
        asked = RoleAsk(
            held,
            {"context": {"options": [{"label": "one"}, {"label": "two"}]}},
            spec,
            AnsweringMechanism.TOOL_CALL,
        )
        return host_module.ask(Client(), asked, contract, time.monotonic() + 20)

    with ThreadPoolExecutor(max_workers=len(roles)) as pool:
        futures = [pool.submit(one, role) for role in roles]
        ready = entered.wait(2)
        release.set()
        outcomes = [future.result() for future in futures]
        assert ready, (peak, outcomes)
        assert all(result["status"] == "unavailable" for result in outcomes)
    assert peak[traffic.key] == traffic.contract().value("concurrent_calls_maximum")
    assert peak[person.key] >= 1
