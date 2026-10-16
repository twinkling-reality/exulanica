"""The first creature picture trial's evaluation record is what its script builds from the tracked
evidence, and its verdict is the pre-registered rule applied to the held-out items and the blind
answers it lists."""

from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs/evaluation/2026-10-15-creature-picture-trial.json"


def _script():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "record_creature_picture_trial", ROOT / "scripts/record_creature_picture_trial.py"
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _record() -> dict:
    return json.loads(RECORD.read_bytes())["record"]


def test_the_committed_record_is_the_one_the_evidence_builds() -> None:
    assert _record() == _script().build()


def test_the_verdict_is_the_rule_applied_to_the_held_out_items_and_answers() -> None:
    record = _record()
    items = {item["item"]: item for item in record["items"]}
    # An item passes when its fit passed every rig check and some bone of the plan moved; a
    # refused item names the rule it broke, in its own words.
    for item in items.values():
        if item["passes"]:
            assert item["outcome"] == "passed" and item["refusal"] is None
            assert item["moving_bones"] > 0
        else:
            assert item["refusal"] and item["refusal_detail"]
    # A held-out creature counts when one of its items passes and its blind answer is yes; one
    # never made has no item, no letter and no answer, and does not count.
    counted = set()
    for creature in record["creatures"]:
        own = [items[number] for number in creature["items"]]
        assert all(item["role"] == "held_out" for item in own)
        assert creature["passing"] == any(item["passes"] for item in own)
        assert creature["counted"] == (creature["passing"] and creature["answer"] == "yes")
        if not own:
            assert creature["letter"] is None and creature["answer"] is None
        else:
            # The judge was shown the item the rule names: the first passing one by seed, else
            # the first made.
            assert creature["judged_item"] == creature["judged_item_by_the_rule"]
        if creature["counted"]:
            counted.add(creature["description"])
    assert record["totals"]["creatures_counted"] == len(counted)
    assert record["totals"]["creatures"] == len(record["creatures"])
    is_default = len(counted) >= record["rule"]["default_at"]
    assert record["rule"]["verdict"].startswith(
        "the picture-led route" if is_default else "the sketch"
    )


def test_the_development_rows_are_reported_and_never_counted() -> None:
    record = _record()
    development = [item for item in record["items"] if item["role"] == "development"]
    counted_items = {number for creature in record["creatures"] for number in creature["items"]}
    assert development and not counted_items & {item["item"] for item in development}
    assert record["totals"]["development_items_passed"] == sum(
        item["passes"] for item in development
    )
    assert set(record["development"]) == {item["body"] for item in development}


def test_the_spend_is_bounded_by_rate_over_a_window_holding_the_job() -> None:
    spend = _record()["spend"]
    gpu = spend["gpu"]
    assert gpu["upper_bound_holds_the_service_window"] is True
    assert gpu["upper_bound_milliseconds"] >= gpu["container_milliseconds"]
    assert gpu["upper_bound_cost_microdollars"] >= gpu["container_cost_microdollars"]
    assert Decimal(spend["drafts"]["usd"]) > 0 and spend["drafts"]["calls"] > 0
