"""What each city record kind is to a person walking, stated as data in the descriptor.

The descriptor's ``navigation`` table gives every declared record kind a ground (support, cover or
none), the region it covers and what a standing capsule keeps clear of, so the tessellator's
navigation projection reads kinds from the grammar rather than listing them in code. The generic
contract refuses a table that is not exhaustive, sorted and in its closed words; the city's
document checks hold the two rules that make ``none`` honest for a facade and ``low_parts``
honest for a tree.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from exulanica.grammar.contract import (
    NAVIGATION_COVER_REGIONS,
    NAVIGATION_GROUND,
    NAVIGATION_REGIONS,
    Grammar,
)
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.grammars.city import CITY_GRAMMAR, CITY_SHAPES, CITY_STAGES
from exulanica.grammar.grammars.city.descriptor import CITY_DESCRIPTOR_PATH
from exulanica.grammar.grammars.city.document import SUPPORT_KINDS, support_top_mm

from city_v2_fixture import records_by_kind


def _rows() -> dict[str, Any]:
    return {row.kind: row for row in CITY_GRAMMAR.navigation}


def test_every_record_kind_has_exactly_one_row_in_closed_words():
    rows = _rows()
    assert sorted(rows) == sorted(shape.kind for shape in CITY_SHAPES)
    assert len(rows) == 27
    for row in rows.values():
        assert row.ground in NAVIGATION_GROUND
        assert row.cover in NAVIGATION_COVER_REGIONS
        assert row.obstruction in NAVIGATION_REGIONS
        assert (row.ground == "cover") == (row.cover != "none")


def test_the_city_table_says_what_the_orchestrator_decided():
    rows = _rows()
    support = {kind for kind, row in rows.items() if row.ground == "support"}
    assert support == {
        "city.block",
        "city.crossing",
        "city.curb_edge",
        "city.entrance",
        "city.junction",
        "city.parcel",
        "city.street_segment",
        "city.street_tree",
        "city.terrain",
    }
    assert (rows["city.massing"].ground, rows["city.massing"].cover) == ("cover", "base_ring")
    obstructing = {kind: row.obstruction for kind, row in rows.items() if row.obstruction != "none"}
    assert obstructing == {
        "city.massing": "base_ring",
        "city.street_furniture": "low_parts",
        "city.street_tree": "low_parts",
    }
    assert "extent" not in NAVIGATION_REGIONS


def test_every_support_kind_states_its_surface_height():
    assert {kind for kind, row in _rows().items() if row.ground == "support"} == SUPPORT_KINDS
    grouped = records_by_kind()
    for kind in SUPPORT_KINDS:
        for record in grouped.get(kind, []):
            assert type(support_top_mm(record)) is int, kind
    with pytest.raises(InvalidRecordError, match="states no support surface"):
        support_top_mm(grouped["city.massing"][0])


def _document() -> dict[str, Any]:
    return json.loads(CITY_DESCRIPTOR_PATH.read_text(encoding="utf-8"))


def _load(tmp_path: Path, document: dict[str, Any]) -> Grammar:
    path = tmp_path / "city.v2.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return Grammar.from_descriptor(path, CITY_STAGES)


def _row(document: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(row for row in document["navigation"] if row["kind"] == kind)


def _missing(document: dict[str, Any]) -> None:
    document["navigation"] = [row for row in document["navigation"] if row["kind"] != "city.lane"]


def _unknown_kind(document: dict[str, Any]) -> None:
    document["navigation"].append({**_row(document, "city.vitrine"), "kind": "city.zeppelin"})


def _twice(document: dict[str, Any]) -> None:
    document["navigation"].append(_row(document, "city.vitrine"))


def _unsorted(document: dict[str, Any]) -> None:
    document["navigation"].reverse()


def _extent_word(document: dict[str, Any]) -> None:
    _row(document, "city.street_furniture")["obstruction"] = "extent"


def _unknown_ground(document: dict[str, Any]) -> None:
    _row(document, "city.parcel")["ground"] = "walkable"


def _cover_without_region(document: dict[str, Any]) -> None:
    _row(document, "city.massing")["cover"] = "none"


def _region_without_cover(document: dict[str, Any]) -> None:
    _row(document, "city.parcel")["cover"] = "base_ring"


def _no_reason(document: dict[str, Any]) -> None:
    _row(document, "city.parcel")["reason"] = ""


def _extra_field(document: dict[str, Any]) -> None:
    _row(document, "city.parcel")["height_mm"] = 0


def _low_parts_with_no_capsule(document: dict[str, Any]) -> None:
    for contract in document["projections"]:
        for row in contract["preserved"]:
            row.pop("measures", None)
    for contract in document["projections"]:
        contract["preserved"] = [
            row for row in contract["preserved"] if row["property"] != "capsule_clearance"
        ]


def _table_missing(document: dict[str, Any]) -> None:
    del document["navigation"]


_CHANGES: list[Callable[[dict[str, Any]], None]] = [
    _missing,
    _unknown_kind,
    _twice,
    _unsorted,
    _extent_word,
    _unknown_ground,
    _cover_without_region,
    _region_without_cover,
    _no_reason,
    _extra_field,
    _low_parts_with_no_capsule,
    _table_missing,
]


def test_an_unchanged_copy_loads_with_the_same_table(tmp_path):
    assert _load(tmp_path, _document()).navigation == CITY_GRAMMAR.navigation


@pytest.mark.parametrize("change", _CHANGES, ids=lambda change: change.__name__.lstrip("_"))
def test_a_navigation_table_outside_its_contract_is_refused(tmp_path, change):
    document = _document()
    change(document)
    with pytest.raises(InvalidRecordError):
        _load(tmp_path, document)
