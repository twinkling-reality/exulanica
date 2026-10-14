"""Kind bounds version 3: a kind naming it may stand taller; a kind naming none reads as before.

The kinds here are the hand-written fixtures in ``tests/fixtures/world-kinds``, changed one thing
at a time. Expected figures are counted from the documents and the catalog files, never read back
from the code under test.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.grammar.grammars.site.records import SiteStructureRecord
from exulanica.world.composers.site_plan import compose_kind, records
from exulanica.world.kinds.catalogs import CATALOG_DIRECTORY, load_kind_catalogs
from exulanica.world.kinds.document import (
    PROFILE,
    REQUIREMENTS_PROFILE,
    KindRefused,
    bounds_version_of,
    read_kind,
)

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"
WORLD = "world:generated:00000000-0000-4000-8000-0000000000b3"


def _document(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"fixture-{name}.json").read_text(encoding="utf-8"))


def _catalog(version: int) -> dict[str, Any]:
    return json.loads((CATALOG_DIRECTORY / f"kind-bound.v{version}.json").read_text("utf-8"))


def _tall_site(storeys: int) -> dict[str, Any]:
    """The building site fixture with its block going up ``storeys`` storeys and bounds 3 named."""
    document = _document("site")
    document["bounds"] = {"version": 3}
    parameter = next(p for p in document["parameters"] if p["key"] == "storeys")
    parameter["maximum"] = storeys
    document["presets"][0]["values"]["storeys"] = storeys
    return document


def test_bounds_3_is_version_2_with_more_storeys_and_nothing_else():
    two, three = _catalog(2), _catalog(3)
    assert three["catalog_version"] == 3 and two["catalog_id"] == three["catalog_id"]
    old = {entry["key"]: entry for entry in two["entries"]}
    new = {entry["key"]: entry for entry in three["entries"]}
    assert old.keys() == new.keys()
    assert {key for key in old if old[key] != new[key]} == {"storeys"}
    assert new["storeys"]["minimum"] == old["storeys"]["minimum"]
    # More storeys than version 2, and no more than a site's structure record holds (1 to 64,
    # exulanica/grammar/grammars/site/records.py).
    assert old["storeys"]["maximum"] < new["storeys"]["maximum"] <= 64


def test_the_bounds_version_is_the_named_one_else_the_profile_s_own():
    assert bounds_version_of({"profile": PROFILE}) == 1
    assert bounds_version_of({"profile": REQUIREMENTS_PROFILE}) == 2
    assert bounds_version_of({"profile": PROFILE, "bounds": {"version": 3}}) == 3
    assert bounds_version_of({"profile": REQUIREMENTS_PROFILE, "bounds": {"version": 3}}) == 3
    # A statement that names nothing it may name chooses nothing; read_kind refuses it.
    assert bounds_version_of({"profile": PROFILE, "bounds": {"version": 4}}) == 1
    assert bounds_version_of({"profile": PROFILE, "bounds": {"version": True}}) == 1


def test_a_kind_naming_bounds_3_stands_taller_and_is_made_and_read_back_from_its_receipt():
    storeys = 30
    kind = read_kind(_tall_site(storeys))
    world = compose_kind(kind, kind.values("small_job"), WORLD)
    blocks = [
        r for r in world.records if isinstance(r, SiteStructureRecord) and r.part_key == "new_block"
    ]
    assert [block.storeys for block in blocks] == [storeys]
    stated = hashlib.sha256((CATALOG_DIRECTORY / "kind-bound.v3.json").read_bytes()).hexdigest()
    assert world.receipt["catalogs"]["kind-bound"] == stated
    assert world.receipt["kind"]["document"]["bounds"] == {"version": 3}
    assert records(world.receipt) == world.records


def test_the_same_kind_naming_no_bounds_is_refused_at_its_storeys():
    document = _tall_site(30)
    del document["bounds"]
    with pytest.raises(KindRefused) as caught:
        read_kind(document)
    assert caught.value.code == "kind_out_of_bounds"
    assert "storeys" in f"{caught.value.where} {caught.value.detail}"


@pytest.mark.parametrize("name", ["farm", "cafe", "site"])
def test_a_kind_naming_no_bounds_reads_and_is_made_as_before(name: str):
    document = _document(name)
    kind = read_kind(document)
    assert kind.document == document
    assert kind.sha256 == read_kind(document, catalogs=load_kind_catalogs(bounds_version=1)).sha256
    world = compose_kind(kind, kind.values(kind.presets[0][0]), WORLD)
    version_1 = {
        catalog: hashlib.sha256((CATALOG_DIRECTORY / f"{catalog}.v1.json").read_bytes()).hexdigest()
        for catalog in world.receipt["catalogs"]
    }
    assert world.receipt["catalogs"] == version_1
    assert "bounds" not in world.receipt["kind"]["document"]


@pytest.mark.parametrize(
    "stated",
    [
        {"version": 1},
        {"version": 2},
        {"version": 4},
        {"version": "3"},
        {"version": True},
        {"version": 3, "storeys": 40},
        {},
        [],
        3,
    ],
)
def test_bounds_names_version_3_only(stated: object):
    document = _tall_site(6)
    document["bounds"] = copy.deepcopy(stated)
    with pytest.raises(KindRefused) as caught:
        read_kind(document)
    assert caught.value.code == "kind_document_invalid"
    assert caught.value.where.startswith("bounds")


def test_a_kind_naming_bounds_3_is_refused_by_a_reader_given_other_bounds():
    with pytest.raises(KindRefused) as caught:
        read_kind(_tall_site(6), catalogs=load_kind_catalogs(bounds_version=1))
    assert caught.value.where == "bounds.version"
