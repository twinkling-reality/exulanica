"""A comparison's runs are read by the line measured on their own engine.

The protocol's line was measured on the purposeful engine. A living town's runs are read by the
line the reading catalog states for the living family, bound to the measurement it was read from;
a family the catalog does not name reads the protocol's line, and the pair's budget is the
protocol's for every family. Which family a comparison's runs are is the family whose score its
catalogs hold, or the family its caller names.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.world import society_comparison_reading as reading
from exulanica.world.society_catalogs import (
    COMPARISON_SCORE_BY_FAMILY,
    COMPARISON_VERSIONS,
    PERSON_SCORE_CATALOG,
    load_comparison_catalogs,
)
from exulanica.world.society_comparison_verdict import ComparisonRefused

#: A line far cheaper than the protocol's, so the two can never be confused.
LIVING = {
    "replay_fixed_ms": 150,
    "replay_per_person_us": 9_000,
    "replay_per_decided_person_us": 12_000,
    "replay_per_decided_pair_us": 20,
}


def _catalog(tmp_path: Path, entries: list[dict[str, Any]]) -> Path:
    path = tmp_path / "society-comparison-reading.json"
    path.write_text(
        json.dumps(
            {
                "catalog_id": "society-comparison-reading",
                "catalog_version": reading._CATALOG_VERSION,
                "source_build": "A test catalog of one measured line, read as the shipped one is.",
                "entries": entries,
            }
        ),
        encoding="utf-8",
    )
    return path


def _living_entry(**changes: Any) -> dict[str, Any]:
    return {
        "key": "living",
        "state_family": "living",
        # A test's entry names no record: the shipped one is held to its record below.
        "source": "a-test-record.json",
        "source_sha256": "0" * 64,
        "extraction": "replay_line",
        **LIVING,
        "reason": "Derived: a test's line, read the way a shipped entry is.",
        **changes,
    }


def _catalogs(score: int):
    return load_comparison_catalogs(versions={**COMPARISON_VERSIONS, PERSON_SCORE_CATALOG: score})


def _by_hand(line: dict[str, int], population: int | None = None) -> int:
    budget_us = _catalogs(3).protocol["pair_replay_budget_ms"]["value"] * 1000 // 2
    room = budget_us - line["replay_fixed_ms"] * 1000
    if population is None:
        return (room - line["replay_per_decided_person_us"]) // (
            line["replay_per_person_us"] + line["replay_per_decided_pair_us"]
        )
    left = room - line["replay_per_person_us"] * population
    each = line["replay_per_decided_person_us"] + line["replay_per_decided_pair_us"] * population
    return max(0, min(population, left // each))


def _protocol_line() -> dict[str, int]:
    protocol = _catalogs(3).protocol
    return {key: protocol[key]["value"] for key in reading.LINE_KEYS}


def _everybody(population: int) -> dict[str, Any]:
    model = {"provider_config": {"model_id": "a/one"}}
    return {
        "group": {"people": None},
        "others": [],
        "arms": {"routine": {"provider_config": None}, "model_a": model},
    }


def test_the_family_of_a_comparison_is_the_one_whose_score_its_catalogs_hold():
    for family, score in COMPARISON_SCORE_BY_FAMILY.items():
        assert reading.family_of(_catalogs(score)) == family
    # An earlier comparison's score is no family's now: it reads the protocol's own line.
    assert reading.family_of(_catalogs(2)) is None


@pytest.mark.parametrize("population", [48, 84, 128])
def test_a_living_town_is_read_by_its_own_line_and_a_saved_world_by_the_protocols(
    tmp_path, monkeypatch, population
):
    monkeypatch.setattr(reading, "READING_CATALOG", _catalog(tmp_path, [_living_entry()]))
    living, purposeful = _catalogs(COMPARISON_SCORE_BY_FAMILY["living"]), _catalogs(3)
    assert reading.population_maximum(living) == _by_hand(LIVING)
    assert reading.decided_maximum(living, population) == _by_hand(LIVING, population)
    assert reading.population_maximum(purposeful) == _by_hand(_protocol_line())
    assert reading.decided_maximum(purposeful, population) == _by_hand(_protocol_line(), population)
    # A caller that knows the engine names its family, whatever score its catalogs hold.
    assert reading.decided_maximum(purposeful, population, "living") == _by_hand(LIVING, population)
    assert reading.reading_refusal(living, population, _everybody(population)) is None


def test_the_pair_budget_is_the_protocols_for_every_family(tmp_path, monkeypatch):
    monkeypatch.setattr(reading, "READING_CATALOG", _catalog(tmp_path, [_living_entry()]))
    living = reading.reading_bound(_catalogs(COMPARISON_SCORE_BY_FAMILY["living"]))
    purposeful = reading.reading_bound(_catalogs(3))
    assert living is not None and purposeful is not None
    assert living.run_us == purposeful.run_us
    assert (living.fixed_us, living.per_decided_us) == (150_000, 12_000)


def test_only_the_family_the_protocol_s_line_was_measured_on_reads_it(tmp_path, monkeypatch):
    # The protocol's own line was measured on a purposeful society: that family reads it, and any
    # other the catalog names no line for is refused by name rather than read by another's line.
    monkeypatch.setattr(reading, "READING_CATALOG", _catalog(tmp_path, []))
    purposeful = _catalogs(COMPARISON_SCORE_BY_FAMILY["purposeful"])
    assert reading.population_maximum(purposeful) == _by_hand(_protocol_line())
    living = _catalogs(COMPARISON_SCORE_BY_FAMILY["living"])
    with pytest.raises(ComparisonRefused) as refused:
        reading.population_maximum(living)
    assert refused.value.code == reading.NO_READING_LINE


@pytest.mark.parametrize(
    "changes",
    [
        {"key": "purposeful"},
        {"state_family": "district"},
        {"extraction": "typed_by_hand"},
        {"replay_per_person_us": 0},
        # A line on which deciding for somebody costs nothing at all.
        {"replay_per_decided_person_us": 0, "replay_per_decided_pair_us": 0},
        {"replay_fixed_ms": -1},
        {"replay_per_decided_pair_us": 1.5},
        {"source_sha256": None},
    ],
)
def test_a_malformed_line_is_refused_by_name(tmp_path, monkeypatch, changes):
    path = _catalog(tmp_path, [_living_entry(**changes)])
    monkeypatch.setattr(reading, "READING_CATALOG", path)
    with pytest.raises(ComparisonRefused, match="reading_catalog"):
        reading.population_maximum(_catalogs(COMPARISON_SCORE_BY_FAMILY["living"]))


@pytest.mark.parametrize("population", [38, 88, 128])
def test_a_line_whose_decided_person_term_is_zero_is_read_by_its_pair_term(
    tmp_path, monkeypatch, population
):
    """A fit may put the cost of one more decided person at zero when the pair term carries what
    deciding adds; such a line is read, and its bounds are the hand-derived ones."""
    line = {**LIVING, "replay_per_decided_person_us": 0}
    path = _catalog(tmp_path, [_living_entry(replay_per_decided_person_us=0)])
    monkeypatch.setattr(reading, "READING_CATALOG", path)
    living = _catalogs(COMPARISON_SCORE_BY_FAMILY["living"])
    assert reading.population_maximum(living) == _by_hand(line)
    assert reading.decided_maximum(living, population) == _by_hand(line, population)


def test_a_bound_whose_decided_terms_are_zero_decides_for_everybody_who_fits():
    """A measured line handed straight to the bound (as the measuring scripts do) may state no
    cost for deciding: everybody is decided where the undecided read fits, and nobody where it
    does not, with no division by its zero terms."""
    bound = reading.ReadingBound(
        run_us=1_000, fixed_us=0, per_person_us=10, per_decided_us=0, per_pair_us=0
    )
    assert bound.decided_most(50) == 50
    assert bound.decided_most(100) == 100
    assert bound.decided_most(101) == 0
    assert bound.decided_most(0) == 0


def test_a_catalog_naming_one_family_twice_is_refused(tmp_path, monkeypatch):
    path = _catalog(tmp_path, [_living_entry(), _living_entry()])
    monkeypatch.setattr(reading, "READING_CATALOG", path)
    with pytest.raises(ComparisonRefused, match="reading_catalog"):
        reading.population_maximum(_catalogs(COMPARISON_SCORE_BY_FAMILY["living"]))


def test_a_catalog_of_another_version_is_refused(tmp_path, monkeypatch):
    path = _catalog(tmp_path, [_living_entry()])
    document = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**document, "catalog_version": 1}), encoding="utf-8")
    monkeypatch.setattr(reading, "READING_CATALOG", path)
    with pytest.raises(ComparisonRefused, match="reading_catalog"):
        reading.population_maximum(_catalogs(COMPARISON_SCORE_BY_FAMILY["living"]))


def test_the_code_reads_the_newest_reading_catalog():
    """Every version of the reading catalog stays beside the others, and the code reads the
    newest, the one its own version names."""
    versions = {
        json.loads(path.read_text(encoding="utf-8"))["catalog_version"]: path
        for path in reading.READING_CATALOG.parent.glob("society-comparison-reading.v*.json")
    }
    assert versions[max(versions)] == reading.READING_CATALOG
    assert max(versions) == json.loads(reading.READING_CATALOG.read_text())["catalog_version"]


def test_the_reading_catalog_ships_with_the_code(tmp_path, monkeypatch):
    assert reading.READING_CATALOG.is_file()
    monkeypatch.setattr(reading, "READING_CATALOG", tmp_path / "absent.json")
    with pytest.raises(FileNotFoundError):
        reading.population_maximum(_catalogs(3))


#: The measurement that fits a living town's line over each window a comparison may run.
RECORD_KINDS = {
    60: "exulanica.living-comparison-replay-measurement/v1",
    1440: "exulanica.living-day-replay-measurement/v1",
}


def test_every_shipped_living_line_is_the_one_its_measurement_record_fitted():
    """The catalog states the living engine's line over an hour, and over any longer window it
    names, each naming the record it was read from. That record exists under the path the entry
    names and digests to the entry's digest. It measured the living town over the entry's window
    under the gate without being discarded, and fitted exactly these four figures."""
    root = reading.READING_CATALOG.parents[3]
    document = json.loads(reading.READING_CATALOG.read_text(encoding="utf-8"))
    living = [row for row in document["entries"] if row["state_family"] == "living"]
    assert [row.get("window_ticks", 60) for row in living].count(60) == 1
    for entry in living:
        window = entry.get("window_ticks", 60)
        source = root / entry["source"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == entry["source_sha256"]
        record = json.loads(source.read_text(encoding="utf-8"))["record"]
        assert record["kind"] == RECORD_KINDS[window]
        assert record["engine"] == "exulanica-society/v5"
        assert record["window_ticks"] == window
        assert record["discard"] is False
        assert {key: record["line"][key] for key in reading.LINE_KEYS} == {
            key: entry[key] for key in reading.LINE_KEYS
        }
