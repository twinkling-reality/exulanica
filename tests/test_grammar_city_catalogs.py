"""The city's catalogs as reviewed data: what they hold, where it came from, and how they agree.

``tests/test_grammar_catalogs.py`` holds the generic loader (envelopes, licences, digests, the
texture manifest). This file holds what the city's catalogs say:

*   **Every key the fixture uses resolves**, and the fixture names every catalog a record field
    resolves in, so no vocabulary is declared and never exercised.
*   **Every entry carries a licence and a source that exists**, and every entry of a catalog with a
    reason states one: authored vocabulary says it is authored, a material names the texture set it
    depicts, and a derived entry says how it was derived.
*   **The cross-catalog checks refuse** each broken reference, one at a time, on a copy.
*   **The descriptor's choice options are the catalog keys**, exactly, so the parameter vocabulary
    and the catalog cannot drift apart.
*   **Tree species re-derive from the retained source bytes**, whose SHA-256 is pinned: the one
    approved download is the only input, and the selection rule is written out here.
*   **Keys agreed with other lanes** are written out: the living society's use classes and bench,
    and the traffic lane's right-of-way, lane use and parking keys.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from exulanica.grammar.catalogs import LICENCE_VERDICTS, Catalog
from exulanica.grammar.errors import CatalogError, UnresolvedReferenceError
from exulanica.grammar.grammars.city import CITY_SHAPES
from exulanica.grammar.grammars.city.catalogs import (
    CATALOG_DIRECTORY,
    city_vocabularies,
    entry_fields,
    load_city_catalogs,
)
from exulanica.grammar.grammars.city.descriptor import CITY_SURFACE
from exulanica.grammar.parameters import CLOSED_VOCABULARY
from exulanica.grammar.textures import read_texture_manifest

from city_v2_fixture import builder

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = load_city_catalogs()
FIXTURE = builder()

TREE_SOURCE = CATALOG_DIRECTORY / "sources" / "nyc-2015-street-tree-census-species.json"
TREE_SOURCE_SHA256 = "68865bbbfdbcff42ce2492eadb218313e20c5f54845e7a4cac93885873b3ae15"
TREE_SOURCE_BYTES = 10_853


def _catalog(catalog_id: str) -> Catalog:
    return next(catalog for catalog in CATALOGS if catalog.catalog_id == catalog_id)


def _field_vocabularies() -> set[str]:
    found: set[str] = set()

    def visit(shape) -> None:
        for field_shape in shape.fields:
            if field_shape.vocabulary:
                found.add(field_shape.vocabulary)
            if field_shape.shape is not None:
                visit(field_shape.shape)

    for shape in CITY_SHAPES:
        visit(shape)
    return found


def _used_keys() -> set[tuple[str, str]]:
    """Every (catalog, key) a fixture record names, at any depth."""
    used: set[tuple[str, str]] = set()
    shapes_by_type = {shape.record_type: shape for shape in CITY_SHAPES}

    def visit(value: object, shape) -> None:
        for field_shape in shape.fields:
            inner = getattr(value, field_shape.name)
            if field_shape.vocabulary:
                for key in (inner,) if field_shape.kind == "key" else inner:
                    used.add((field_shape.vocabulary, key))
            if field_shape.shape is not None:
                for item in inner if field_shape.kind == "records" else (inner,):
                    visit(item, field_shape.shape)

    for record in FIXTURE.build_document().grammars[0].records():
        visit(record, shapes_by_type[type(record)])
    return used


# -------------------------------------------------------------------------------------------
# The fixture's keys


def test_every_key_the_fixture_uses_resolves_in_its_catalog():
    vocabularies = city_vocabularies(CATALOGS)
    used = _used_keys()
    assert used
    for catalog_id, key in sorted(used):
        assert key in vocabularies[catalog_id], (catalog_id, key)


def test_the_fixture_exercises_every_catalog_a_record_field_resolves_in():
    named = _field_vocabularies()
    assert named <= {catalog.catalog_id for catalog in CATALOGS}
    assert {catalog_id for catalog_id, _key in _used_keys()} == named
    assert named == {
        "crossing-type",
        "era",
        "fitout",
        "junction-control",
        "lane-use",
        "material",
        "parking-kind",
        "roof-family",
        "rooftop-object",
        "signage-lexicon",
        "street-furniture",
        "street-hierarchy",
        "street-name",
        "tree-species",
        "typology",
        "use-class",
    }


# -------------------------------------------------------------------------------------------
# Licences, sources and reasons


def test_every_entry_carries_a_shippable_licence_and_a_source_that_exists():
    entries = 0
    for catalog in CATALOGS:
        for entry in catalog.entries:
            entries += 1
            where = f"{catalog.catalog_id} {entry.key}"
            assert entry.licence.verdict in LICENCE_VERDICTS, where
            assert ROOT.joinpath(entry.licence.content_source).is_file(), where
            if entry.licence.origin == "derived":
                assert entry.licence.content_source.startswith("assets/catalogs/sources/"), where
    assert entries == 124


_AUTHORED = (
    "crossing-type",
    "era",
    "fitout",
    "junction-control",
    "lane-use",
    "parking-kind",
    "roof-family",
    "rooftop-object",
    "signage-lexicon",
    "street-furniture",
    "street-hierarchy",
    "street-name",
    "typology",
    "use-class",
)


@pytest.mark.parametrize("catalog_id", _AUTHORED)
def test_authored_vocabulary_says_it_is_authored_and_why(catalog_id):
    catalog = _catalog(catalog_id)
    assert catalog.entries
    for entry in catalog.entries:
        reason = entry_fields(catalog, entry.key)["reason"]
        assert isinstance(reason, str) and reason.startswith("Authored"), (entry.key, reason)
        assert len(reason.split()) >= 5, (entry.key, reason)
        assert entry.licence.origin == "original"


def test_a_guide_cited_by_an_authored_value_is_marked_as_not_re_read():
    for catalog in CATALOGS:
        for entry in catalog.entries:
            reason = dict(entry.values).get("reason", "")
            if "NACTO" in reason or "AASHTO" in reason:
                assert "not re-read" in reason, (catalog.catalog_id, entry.key)


def test_each_material_depicts_one_of_the_eight_pinned_texture_sets():
    catalog = _catalog("material")
    published = read_texture_manifest()
    pinned = {
        "cc0.brick-running-bond",
        "cc0.carriageway-asphalt",
        "cc0.cast-concrete",
        "cc0.footway-paving",
        "cc0.kerb-stone",
        "cc0.limestone-ashlar",
        "cc0.painted-render",
        "cc0.storefront-metal",
    }
    sets = []
    for entry in catalog.entries:
        values = entry_fields(catalog, entry.key)
        sets.append(values["texture_set_id"])
        assert values["texture_set_id"] in published
        assert str(values["reason"]).startswith(
            f"The material the {values['texture_set_id']} texture set depicts."
        )
        assert entry.licence.content_source.startswith("assets/textures/objects/")
    assert sorted(sets) == sorted(pinned)


_SIGN_TEXT = re.compile(r"[A-Z][a-z]+( [A-Z][a-z]+)?")


def test_signs_are_generic_descriptors_of_a_signed_use_class():
    lexicon = _catalog("signage-lexicon")
    uses = _catalog("use-class")
    for entry in lexicon.entries:
        values = entry_fields(lexicon, entry.key)
        assert _SIGN_TEXT.fullmatch(str(values["text"])), values["text"]
        assert entry_fields(uses, str(values["use_class"]))["signage"] == "required"


# -------------------------------------------------------------------------------------------
# Keys agreed with other lanes


def test_the_use_classes_are_exactly_the_living_society_keys_and_a_bench_is_furniture():
    assert _catalog("use-class").keys() == (
        "bakery",
        "bookshop",
        "cafe",
        "grocery",
        "library",
        "office",
        "pharmacy",
        "residential",
        "restaurant",
        "school",
        "workshop",
    )
    assert entry_fields(_catalog("street-furniture"), "bench")["category"] == "seating"


def test_the_traffic_keys_are_the_agreed_ones():
    assert set(_catalog("junction-control").keys()) == {
        "signalised",
        "priority_two_way_stop",
        "all_way_stop",
        "uncontrolled_continuation",
    }
    assert set(_catalog("lane-use").keys()) == {"general", "bus", "cycle", "parking", "buffer"}
    assert set(_catalog("parking-kind").keys()) == {
        "general",
        "loading",
        "accessible",
        "bus_layover",
        "cycle_stand",
    }
    assert entry_fields(_catalog("street-furniture"), "cycle_stand")["bicycles_per_stand"] == 2


# -------------------------------------------------------------------------------------------
# The descriptor's options are the catalog keys


def test_every_choice_parameter_with_a_vocabulary_offers_exactly_its_catalog_keys():
    material = _catalog("material")
    wall_materials = tuple(
        entry.key
        for entry in material.entries
        if "wall" in entry_fields(material, entry.key)["surfaces"]  # type: ignore[operator]
    )
    checked = []
    for spec in CITY_SURFACE.parameters.parameters:
        if spec.kind != "choice" or spec.vocabulary == CLOSED_VOCABULARY:
            continue
        checked.append(spec.name)
        expected = (
            wall_materials if spec.name == "wall_material" else _catalog(spec.vocabulary).keys()
        )
        assert spec.options == expected, spec.name
    assert sorted(checked) == [
        "era",
        "fitout",
        "ground_floor_use",
        "roof_family",
        "tree_species",
        "typology",
        "upper_floor_use",
        "wall_material",
    ]
    assert wall_materials == (
        "brick_running_bond",
        "cast_concrete",
        "limestone_ashlar",
        "painted_render",
    )


# -------------------------------------------------------------------------------------------
# Tree species, re-derived from the retained source


def _species_key(latin: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", latin.lower())).strip("_")


def test_the_retained_tree_census_bytes_are_the_approved_download():
    data = TREE_SOURCE.read_bytes()
    assert (len(data), hashlib.sha256(data).hexdigest()) == (TREE_SOURCE_BYTES, TREE_SOURCE_SHA256)
    provenance = json.loads(
        TREE_SOURCE.with_name(TREE_SOURCE.stem + ".provenance.json").read_text(encoding="utf-8")
    )
    assert (provenance["sha256"], provenance["byte_size"]) == (TREE_SOURCE_SHA256, len(data))
    assert provenance["source_file"] == TREE_SOURCE.name
    assert provenance["attribution"] == "NYC Open Data, Office of Technology and Innovation (OTI)"
    assert provenance["method"] == "GET"


def test_the_tree_species_entries_re_derive_from_the_retained_source():
    """Named species of at least one percent of the named trees, by the rule the entries state.

    A row with no ``spc_latin`` names no tree, and a genus alone names no species.
    """
    rows = json.loads(TREE_SOURCE.read_text(encoding="utf-8"))
    named = [row for row in rows if "spc_latin" in row]
    total = sum(int(row["tree_count"]) for row in named)
    assert total == 652_169
    selected = sorted(
        (
            row
            for row in named
            if len(row["spc_latin"].split()) >= 2 and int(row["tree_count"]) * 100 >= total
        ),
        key=lambda row: _species_key(row["spc_latin"]),
    )
    catalog = _catalog("tree-species")
    derived = [
        (
            _species_key(row["spc_latin"]),
            row["spc_latin"],
            row["spc_common"],
            int(row["tree_count"]),
        )
        for row in selected
    ]
    stated = [
        (
            entry.key,
            entry_fields(catalog, entry.key)["scientific_name"],
            entry_fields(catalog, entry.key)["common_name"],
            entry_fields(catalog, entry.key)["census_count"],
        )
        for entry in catalog.entries
    ]
    assert stated == derived
    assert len(stated) == 19
    for entry in catalog.entries:
        assert f"one percent of the {total} named trees" in str(
            entry_fields(catalog, entry.key)["reason"]
        )
        assert (entry.licence.origin, entry.licence.verdict) == ("derived", "SHIP-ATTRIB")
        assert entry.licence.content_source == TREE_SOURCE.relative_to(ROOT).as_posix()


# -------------------------------------------------------------------------------------------
# Cross-catalog refusals


def _copy_catalogs(tmp_path: Path) -> Path:
    directory = tmp_path / "catalogs"
    directory.mkdir()
    for path in CATALOG_DIRECTORY.glob("*.json"):
        shutil.copyfile(path, directory / path.name)
    return directory


def _edit(directory: Path, name: str, change: Callable[[list[dict[str, Any]]], None]) -> None:
    path = directory / name
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document["entries"])
    path.write_text(json.dumps(document), encoding="utf-8")


def _entry(entries: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return next(entry for entry in entries if entry["key"] == key)


def _set(key: str, field: str, value: object) -> Callable[[list[dict[str, Any]]], None]:
    def change(entries: list[dict[str, Any]]) -> None:
        _entry(entries, key)[field] = value

    return change


def _signs_only_for_other_uses(entries: list[dict[str, Any]]) -> None:
    entries[:] = [entry for entry in entries if entry["use_class"] != "school"]


_CROSS = [
    (
        "an era wall material that dresses no wall",
        "era.v1.json",
        _set("prewar_masonry", "wall_materials", ["brick_running_bond", "carriageway_asphalt"]),
        "does not dress a wall",
    ),
    (
        "an era wall material that does not exist",
        "era.v1.json",
        _set("prewar_masonry", "wall_materials", ["brick_running_bond", "granite"]),
        "not a key of material",
    ),
    (
        "an era roof family that does not exist",
        "era.v1.json",
        _set("prewar_masonry", "roof_families", ["mansard"]),
        "not a key of roof-family",
    ),
    (
        "a typology ground floor use that does not exist",
        "typology.v2.json",
        _set("shophouse", "ground_floor_uses", ["bakery", "florist"]),
        "not a key of use-class",
    ),
    (
        "a typology upper floor use that does not exist",
        "typology.v2.json",
        _set("shophouse", "upper_floor_uses", ["studio"]),
        "not a key of use-class",
    ),
    (
        "a typology era that does not exist",
        "typology.v2.json",
        _set("shophouse", "eras", ["victorian"]),
        "not a key of era",
    ),
    (
        "a typology roof family that does not exist",
        "typology.v2.json",
        _set("shophouse", "roof_families", ["mansard"]),
        "not a key of roof-family",
    ),
    (
        "a sign for a use class that takes none",
        "signage-lexicon.v2.json",
        _set("bakery", "use_class", "residential"),
        "takes no sign",
    ),
    (
        "a signed use class with no sign",
        "signage-lexicon.v2.json",
        _signs_only_for_other_uses,
        "use classes with no sign in the lexicon",
    ),
    (
        "a fitout for a use class that does not exist",
        "fitout.v1.json",
        _set("bakery_counter", "use_classes", ["bakery", "patisserie"]),
        "not a key of use-class",
    ),
    (
        "a street name for a hierarchy that does not exist",
        "street-name.v1.json",
        _set("market_street", "hierarchies", ["boulevard"]),
        "not a key of street-hierarchy",
    ),
]


@pytest.mark.parametrize("why,name,change,message", _CROSS, ids=[case[0] for case in _CROSS])
def test_a_broken_cross_catalog_reference_is_refused(tmp_path, why, name, change, message):
    directory = _copy_catalogs(tmp_path)
    load_city_catalogs(directory)
    _edit(directory, name, change)
    with pytest.raises(CatalogError, match=message):
        load_city_catalogs(directory)


def test_a_material_naming_an_unpublished_texture_set_is_refused(tmp_path):
    directory = _copy_catalogs(tmp_path)
    _edit(directory, "material.v2.json", _set("kerb_stone", "texture_set_id", "cc0.granite-sett"))
    with pytest.raises(UnresolvedReferenceError, match=re.escape("cc0.granite-sett")):
        load_city_catalogs(directory)
