"""What an ask of a model mind typically costs: the catalog against the record it is read from.

The catalog (``assets/catalogs/society-minds-cost``) states counts and names an immutable
evaluation record; the reader works a price and a rate out of the counts. Held here against the
record's own file, read as bytes and as JSON, never through the reader under test: the record's
digest reproduces, each entry's digest of its source is the file's, each entry's counts and classes
are its arm's, and the figures the reader serves are the ones those counts make by hand.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.world import minds_typical
from exulanica.world.minds_typical import ESTIMATE, MEASURED, typical_ask

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "assets/catalogs/society-minds-cost/society-minds-typical-cost.v1.json"
NANO = ("nebius_token_factory", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
LIVING, THINGS = "exulanica-society/v5", "exulanica-society/v7"


def _entries() -> list[dict]:
    return json.loads(CATALOG.read_text())["entries"]


def test_the_record_reproduces_its_digest_and_says_what_it_is_not():
    [source] = {entry["source"] for entry in _entries()}
    envelope = json.loads((ROOT / source).read_text())
    assert envelope["profile"] == "exulanica.digest-bound-record/v1"
    record = envelope["record"]
    assert hashlib.sha256(canonical_json(record)).hexdigest() == envelope["record_sha256"]
    # One model, no comparison, and nothing about the service that served it, in its own fields.
    assert record["what_this_is_not"]["models_measured"] == 1
    assert record["what_this_is_not"]["compares_models"] is False
    assert record["what_this_is_not"]["measures_the_provider"] is False
    arms = record["arms"]
    assert (arms["living_town"]["status"], arms["living_town"]["rate_class"]) == (
        "valid",
        "measured",
    )
    # The cut arm is called cut, and its rate an estimate; the void run is used for nothing.
    assert (arms["society_of_things"]["status"], arms["society_of_things"]["rate_class"]) == (
        "cut",
        "estimate",
    )
    first = arms["society_of_things_first_run"]
    assert first["status"] == "void" and first["machine_slept_inside"] is True
    assert (first["rate_class"], first["price_class"]) == ("not_used", "not_used")
    # What ended an arm is named by what its rule counts, and every failed ask by what failed:
    # the model's own answer at the answer bound, or a call this machine never sent. Nothing in
    # the record calls a failed ask the provider's.
    cut = arms["society_of_things"]
    assert cut["ended_by"] == first["ended_by"] == "its stop rule for failed asks"
    assert "provider error" not in json.dumps(record)
    failed = (
        "asks_that_failed",
        "answers_refused_at_the_answer_bound",
        "asks_whose_call_was_not_sent",
    )
    assert [cut[name] for name in failed] == [5, 5, 0]
    assert [first[name] for name in failed] == [12, 2, 10]
    assert "10 were calls that were never sent" in first["status_reason"]
    # The second run's billed calls are its asks and one more for the one ask answered in two.
    again = record["price_seen_again"]
    assert again["billed_calls"] == again["asks"] + again["asks_answered_in_two_calls"] == 361
    for arm in arms.values():
        assert arm["asks"] == (
            arm["answers_taken"] + arm["answers_not_among_the_offered"] + arm["asks_that_failed"]
        )


def test_each_entry_is_one_arm_of_the_record_it_names_by_digest():
    entries = _entries()
    assert [entry["arm"] for entry in entries] == ["living_town", "society_of_things"]
    for entry in entries:
        source = ROOT / entry["source"]
        assert entry["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        record = json.loads(source.read_text())["record"]
        arm = record["arms"][entry["arm"]]
        assert (entry["provider"], entry["model_id"]) == (
            record["model"]["provider"],
            record["model"]["model_id"],
        )
        assert entry["engine"] == arm["engine"]
        assert (entry["asks"], entry["beings"], entry["simulated_minutes"], entry["usd"]) == (
            arm["asks"],
            arm["beings_with_the_model"],
            arm["simulated_minutes"],
            arm["usd"],
        )
        assert entry["beings_in_the_world"] == arm["beings_in_the_world"]
        assert (entry["rate_class"], entry["price_class"]) == (
            arm["rate_class"],
            arm["price_class"],
        )
        assert len(entry["reason"].split()) >= 5


def test_the_reader_serves_the_figures_the_counts_make_each_with_its_class():
    # A living town: 43 asks of 8 people in 120 minutes for 0.00494160 dollars.
    living = typical_ask(LIVING, *NANO)
    assert living is not None
    assert living.usd_per_ask == Decimal("0.00494160") / 43
    assert living.asks_per_being_minute == Decimal(43) / (8 * 120)
    assert (living.rate_class, living.price_class) == (MEASURED, MEASURED)
    assert living.rate_is_an_estimate is False
    assert living.view()["usd_per_ask"] == "0.00011492"
    assert living.view()["asks_per_being_minute"] == "0.044792"
    # A society of things: 91 asks of 8 beings in 44 minutes for 0.02562756 dollars, a cut arm.
    things = typical_ask(THINGS, *NANO)
    assert things is not None
    assert things.usd_per_ask == Decimal("0.02562756") / 91
    assert things.asks_per_being_minute == Decimal(91) / (8 * 44)
    assert things.rate_is_an_estimate is True
    view = things.view()
    assert (view["rate_class"], view["price_class"]) == (ESTIMATE, MEASURED)
    assert view["usd_per_ask"] == "0.00028162" and view["asks_per_being_minute"] == "0.258523"
    assert view["source"] == "docs/evaluation/2026-10-10-minds-ask-rates.json"
    assert view["measured_on"] == {
        "asks": 91,
        "beings_with_the_model": 8,
        "beings_in_the_world": 9,
        "simulated_minutes": 44,
    }


def test_nothing_is_carried_to_an_engine_or_a_model_nobody_measured():
    assert typical_ask(None, *NANO) is None
    assert typical_ask("exulanica-society/v2", *NANO) is None
    assert typical_ask(THINGS, "nebius_token_factory", "Qwen/Qwen3-235B-A22B-Instruct-2507") is None
    assert typical_ask(THINGS, "another_provider", NANO[1]) is None


@pytest.mark.parametrize(
    "change",
    [
        {"rate_class": "guessed"},
        {"asks": 0},
        {"usd": "0"},
        {"key": "another|key|entirely"},
    ],
)
def test_an_entry_that_states_no_class_or_no_counts_is_refused(change):
    entry = {**_entries()[0], **change}
    with pytest.raises(ValueError, match="invalid typical-cost entry"):
        minds_typical._entry(entry)
