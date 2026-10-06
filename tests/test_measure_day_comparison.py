"""The judged day's harness in ``scripts/measure_day_comparison.py``, without a server.

These hold what the harness decides by itself: which models it compares, which held-out seeds it
plays, the least bound a judged day may be registered with, what a comparison going on may still
spend, when a first hour of provider failures stops it, and that a rehearsal refuses to start
where a provider could be reached. Running it against a stack is the measurement.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "measure_day_comparison.py"
PLAN = ROOT / "scripts" / "acceptance" / "plans" / "comparisons.json"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exulanica_measure_day_comparison", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


H = _load()
NANO = "nebius_token_factory/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
QWEN = "nebius_token_factory/Qwen/Qwen3-235B-A22B-Instruct-2507"


def test_a_judged_day_compares_exactly_two_different_models_in_the_order_named():
    assert H.models_named([NANO, QWEN]) == [
        ("nebius_token_factory", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"),
        ("nebius_token_factory", "Qwen/Qwen3-235B-A22B-Instruct-2507"),
    ]
    for named in ([NANO], [NANO, NANO], [NANO, QWEN, NANO], [NANO, "no-model-id"]):
        with pytest.raises(SystemExit):
            H.models_named(named)


def test_the_seeds_played_are_the_committed_ones_in_their_order_and_all_of_them():
    texts = ["first held-out seed", "second held-out seed", "a seed nobody committed"]
    digests = [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts]
    file = "# a comment line\n" + "\n".join(reversed(texts)) + "\n\n"
    assert H.seeds_from(file, digests[:2]) == texts[:2]
    assert H.seeds_from(file, [digests[1], digests[0]]) == [texts[1], texts[0]]
    with pytest.raises(SystemExit, match="no seed for 1"):
        H.seeds_from("first held-out seed\n", digests[:2])


def test_answer_times_are_read_at_their_nearest_rank():
    twenty = list(range(20, 0, -1))
    assert H.nearest_rank(twenty, 500) == 10
    assert H.nearest_rank(twenty, 950) == 19
    assert H.nearest_rank([7], 950) == 7
    assert H.nearest_rank([], 500) is None


def test_the_least_judged_bound_admits_the_last_seed_and_holds_the_development_day():
    # One seed of the design needs 1.22622176 left to be admitted (the plan's suggested_usd), so
    # the eighth seed needs it on top of seven seeds' spend: 0.10 x 1.25 x 7 + 1.22622176.
    cheap = H.least_bound("1.22622176", "0.10", 8)
    assert Decimal(cheap["projected_from_development_usd"]) == Decimal("1.00")
    assert Decimal(cheap["last_seed_admitted_usd"]) == Decimal("2.10122176")
    assert Decimal(cheap["least_usd"]) == Decimal("2.10122176")
    # 0.50 x 1.25 x 7 + 1.22622176.
    dear = H.least_bound("1.22622176", "0.50", 8)
    assert Decimal(dear["projected_from_development_usd"]) == Decimal("5.00")
    assert Decimal(dear["least_usd"]) == Decimal("5.60122176")
    # Where one seed's admission is under its share of the projection, the projection binds:
    # 1.00 x 1.25 x 8 = 10.00 against 1.00 x 1.25 x 7 + 0.50 = 9.25.
    assert Decimal(H.least_bound("0.50", "1.00", 8)["least_usd"]) == Decimal("10.00")


def test_a_development_comparison_is_the_design_when_its_stored_group_names_the_same_people():
    # A definition stores its group's people by id and name, ordered by id.
    stored = [
        {"id": "1df5539c-d53c-5e3e-b7f2-6027d5d38f0b", "name": "Resident 16"},
        {"id": "37a9ddaa-ef4d-589a-b58c-c58fb3fdd8db", "name": "Resident 1"},
    ]
    ids = ["37a9ddaa-ef4d-589a-b58c-c58fb3fdd8db", "1df5539c-d53c-5e3e-b7f2-6027d5d38f0b"]
    assert H.same_group(stored, ids) is True
    assert H.same_group(stored, ids[:1]) is False
    assert H.same_group(stored[:1], ids) is False


def test_the_process_states_that_it_spends_within_its_own_bound(monkeypatch):
    from exulanica.spending.config import spending_mode

    monkeypatch.setattr(H.os, "environ", {})
    state = {
        "database": {"runtime_url": "postgresql://exulanica_app@127.0.0.1:1/x"},
        "data_dir": "/nonexistent",
        "workspace_id": "00000000-0000-0000-0000-000000000001",
        "actor": "00000000-0000-0000-0000-000000000002",
    }
    H._environment(state, "4.00", 10)
    assert spending_mode(H.os.environ, credentials_configured=True) == "process"
    assert H.os.environ["EXULANICA_BUDGET_USD"] == "4.00"


def test_a_comparison_going_on_keeps_what_it_spent_and_one_minute_presumed_out_of_its_bound():
    minutes = [
        {"arm": "model_a", "decided": 12, "ask_bound_usd": "0.00196020"},
        {"arm": "model_b", "decided": 12, "ask_bound_usd": "0.00571480"},
    ]
    # 12 - 3.5 spent - 2 runs x 12 people x the dearest ask, 0.0057148.
    assert H.resumed_bound(Decimal("12"), "3.5", minutes) == Decimal("8.3628448")


def test_a_first_hour_stops_the_run_only_when_provider_failures_outnumber_answers():
    assert H.provider_failed(10, 6) is True
    assert H.provider_failed(10, 5) is False
    assert H.provider_failed(0, 0) is False


def test_a_rehearsal_refuses_to_start_where_a_provider_could_be_reached(monkeypatch):
    for name in list(H.os.environ):
        if name.startswith(("NEBIUS_", "OPENAI_", "ANTHROPIC_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")
    with pytest.raises(SystemExit, match="could reach a provider: ANTHROPIC_BASE_URL"):
        H._services(PLAN)
