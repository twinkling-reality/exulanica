"""A comparison's development seeds are committed text, so a server needs no file of seeds.

The seed catalog's third version commits each development seed's text beside the digest the first
two versions commit it by, and its schema holds the text to the digest. A held-out seed stays
committed by its digest alone: an entry that states one's text is refused by name. A server takes
its development seeds from the catalog a new comparison is defined under, and no setting names a
file of them.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from exulanica.api.services import build_services
from exulanica.api.society_comparison_start import development_seeds
from exulanica.grammar.errors import CatalogError
from exulanica.world.society_catalogs import (
    COMPARISON_VERSIONS,
    DAY_COMPARISON_VERSIONS,
    HELD_OUT_SEED_TEXT,
    ROUTINE_DIRECTORY,
    load_comparison_catalogs,
)

EVALUATION = Path(__file__).resolve().parents[1] / "docs" / "evaluation"
SEEDS_V2 = ROUTINE_DIRECTORY / "society-comparison-seeds.v2.json"
SEEDS_V3 = ROUTINE_DIRECTORY / "society-comparison-seeds.v3.json"
#: The seeds a new comparison is defined under.
SEEDS_NOW = (
    ROUTINE_DIRECTORY
    / f"society-comparison-seeds.v{COMPARISON_VERSIONS['society-comparison-seeds']}.json"
)


def _entries(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


def test_each_development_seed_is_the_text_of_its_second_version_digest():
    second = {entry["key"]: entry for entry in _entries(SEEDS_V2)}
    third = _entries(SEEDS_V3)
    development = [entry for entry in third if entry["phase"] == "development"]
    assert len(development) == 8
    for entry in development:
        assert hashlib.sha256(entry["seed"].encode("utf-8")).hexdigest() == entry["seed_digest"]
        assert entry["seed_digest"] == second[entry["key"]]["seed_digest"], entry["key"]
    # Every held-out seed is the second version's, by its digest alone.
    held_out = [entry for entry in third if entry["phase"] == "held_out"]
    assert held_out
    assert all(entry["seed"] == "none" for entry in held_out)
    assert {e["key"]: e["seed_digest"] for e in held_out} == {
        key: entry["seed_digest"] for key, entry in second.items() if entry["phase"] == "held_out"
    }


def _catalogs_with(tmp_path: Path, change) -> Path:
    for path in ROUTINE_DIRECTORY.glob("*.json"):
        shutil.copy(path, tmp_path / path.name)
    document = json.loads(SEEDS_NOW.read_text(encoding="utf-8"))
    change(document["entries"])
    (tmp_path / SEEDS_NOW.name).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("version", [4, 5, 6])
def test_each_later_version_keeps_development_seeds_and_draws_held_out_seeds_afresh(version):
    third = _entries(SEEDS_V3)
    later = _entries(ROUTINE_DIRECTORY / f"society-comparison-seeds.v{version}.json")
    assert [
        (e["key"], e["seed_digest"], e["seed"]) for e in later if e["phase"] == "development"
    ] == [(e["key"], e["seed_digest"], e["seed"]) for e in third if e["phase"] == "development"]
    held_out = [entry for entry in later if entry["phase"] == "held_out"]
    assert len(held_out) == 8
    assert all(entry["seed"] == "none" for entry in held_out)
    # None of them is a seed an earlier version committed, whose held-out seeds were spent.
    earlier = {
        entry["seed_digest"]
        for earlier_version in range(1, version)
        for entry in _entries(
            ROUTINE_DIRECTORY / f"society-comparison-seeds.v{earlier_version}.json"
        )
    }
    assert not {entry["seed_digest"] for entry in held_out} & earlier


def test_a_held_out_entry_that_states_its_text_is_refused_by_name(tmp_path):
    def stated(entries):
        held = next(entry for entry in entries if entry["phase"] == "held_out")
        held["seed"] = "a held-out seed written down"

    with pytest.raises(CatalogError, match=HELD_OUT_SEED_TEXT):
        load_comparison_catalogs(_catalogs_with(tmp_path, stated))


def test_a_days_held_out_seeds_were_run_by_no_comparison_registered_under_other_seeds():
    """A judged comparison's records name the seed catalog they were registered under and the
    held-out seeds they ran, by digest. A held-out seed of the catalog a day is defined under that
    a record naming no such catalog holds was spent by another comparison, which is how the fifth
    version's were found spent by the judged town comparison of 2026-09-30."""
    assert DAY_COMPARISON_VERSIONS["society-comparison-seeds"] == 6
    name = "society-comparison-seeds.v6.json"
    held_out = {
        entry["seed_digest"]
        for entry in _entries(ROUTINE_DIRECTORY / name)
        if entry["phase"] == "held_out"
    }
    assert len(held_out) == 8
    records = sorted(EVALUATION.rglob("*.json"))
    assert len(records) > 100
    for path in records:
        text = path.read_text(encoding="utf-8")
        if name not in text:
            assert not {digest for digest in held_out if digest in text}, path.name


def test_a_development_seed_whose_text_is_not_its_digest_is_refused(tmp_path):
    def wrong(entries):
        entry = next(entry for entry in entries if entry["phase"] == "development")
        entry["seed"] = entry["seed"][::-1]

    with pytest.raises(CatalogError, match="text of its digest"):
        load_comparison_catalogs(_catalogs_with(tmp_path, wrong))


def test_the_committed_catalog_reads_and_gives_its_development_seeds_in_order():
    catalogs = load_comparison_catalogs()
    assert (
        catalogs.versions["society-comparison-seeds"]
        == 5
        == COMPARISON_VERSIONS["society-comparison-seeds"]
    )
    seeds = development_seeds(catalogs)
    assert [hashlib.sha256(seed.encode()).hexdigest() for seed in seeds] == [
        entry["seed_digest"] for entry in _entries(SEEDS_NOW) if entry["phase"] == "development"
    ]
    # The second version commits no text, so it gives none.
    earlier = load_comparison_catalogs(
        versions={**COMPARISON_VERSIONS, "society-comparison-seeds": 2}
    )
    assert development_seeds(earlier) == ()


def test_a_server_with_no_seeds_setting_holds_every_development_seed(monkeypatch, tmp_path):
    runtime = object()
    monkeypatch.setattr("exulanica.api.services.load_account_runtime", lambda _: runtime)
    environ = {"EXULANICA_DATABASE_URL": "postgresql://unused", "EXULANICA_DATA_DIR": str(tmp_path)}
    services = build_services(environ)
    assert services.comparison_seeds == development_seeds(load_comparison_catalogs())
    assert len(services.comparison_seeds) == 8
    # A server that still names the retired setting reads nothing from it.
    retired = build_services({**environ, "EXULANICA_COMPARISON_SEEDS": str(tmp_path / "none")})
    assert retired.comparison_seeds == services.comparison_seeds
