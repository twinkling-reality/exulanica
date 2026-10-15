"""The land document: features from the landform catalogs, every value held to its bound."""

from __future__ import annotations

import copy

import pytest
from exulanica.grammar.landform import (
    PROFILE,
    LandformRefused,
    landform_catalog,
    level_land,
    read_land_document,
)

HILL = {"id": "hill", "kind": "rise", "side": "north", "height_mm": 18000}


def document(*features: dict, ground_mm: int = 6000) -> dict:
    return {"profile": PROFILE, "ground_mm": ground_mm, "features": [dict(f) for f in features]}


def refusal(raw: object) -> LandformRefused:
    with pytest.raises(LandformRefused) as caught:
        read_land_document(raw)
    return caught.value


def test_every_value_bound_names_a_feature_the_catalog_lists_and_holds_its_default():
    first = {"tilt", "rise", "valley", "undulation", "range", "shore", "basin", "terraces"}
    assert set(landform_catalog(1).features) == first
    catalog = landform_catalog()
    assert set(catalog.features) == first | {"cascade"}
    for (feature, value), bound in catalog.values.items():
        assert feature in catalog.features or feature == "land", (feature, value)
        if bound.words:
            assert 0 <= bound.default < len(bound.words), (feature, value)
        else:
            assert bound.minimum <= bound.default <= bound.maximum, (feature, value)
    # Every feature can be placed, except the two that apply everywhere.
    for feature in catalog.features:
        assert ((feature, "side") in catalog.values) == (feature != "undulation"), feature


def test_a_stated_document_is_read_with_its_defaults_filled():
    land = read_land_document(document(HILL))
    [hill] = land.features
    assert hill.kind == "rise" and hill.values["height_mm"] == 18000
    # Unstated values take the catalog's defaults, written into the canonical document, so a
    # later catalog default never changes a world that was made before it.
    assert hill.values["width_mm"] == landform_catalog().values[("rise", "width_mm")].default
    assert land.canonical()["features"][0]["width_mm"] == hill.values["width_mm"]
    again = read_land_document(land.canonical())
    assert again.sha256 == land.sha256 and again.canonical_bytes == land.canonical_bytes


def test_unknown_profiles_keys_kinds_and_values_are_refused_by_path():
    assert "profile" in refusal({**document(), "profile": "exulanica.landform/v9"}).detail
    assert "colour" in refusal({**document(), "colour": "green"}).detail
    wrong = refusal(document({"id": "x", "kind": "volcano", "side": "north"}))
    assert wrong.path == "features[0].kind" and "volcano" in wrong.detail
    unknown = refusal(document({**HILL, "snow_mm": 3}))
    assert unknown.path == "features[0]" and "snow_mm" in unknown.detail


def test_every_value_is_held_to_its_catalog_bound_and_the_refusal_names_the_bound():
    high = refusal(document({**HILL, "height_mm": 600001}))
    assert high.path == "features[0].height_mm"
    assert "600000" in high.detail and "hill" in high.detail
    word = refusal(document({**HILL, "side": "up"}))
    assert word.path == "features[0].side" and "north" in word.detail
    assert refusal(document({**HILL, "height_mm": 18000.5})).path == "features[0].height_mm"
    assert refusal(document({**HILL, "height_mm": True})).path == "features[0].height_mm"
    assert refusal(document(ground_mm=40001)).path == "ground_mm"


def test_a_required_value_must_be_stated():
    stated = {key: value for key, value in HILL.items() if key != "side"}
    missing = refusal(document(stated))
    assert missing.path == "features[0].side" and "required" in missing.detail


def test_feature_ids_are_unique_keys_and_each_kind_appears_at_most_its_catalog_count():
    assert refusal(document(HILL, dict(HILL))).path == "features[1].id"
    assert refusal(document({**HILL, "id": "Big Hill"})).path == "features[0].id"
    most = landform_catalog().features["tilt"].most
    tilts = [{"id": f"t{i}", "kind": "tilt", "side": "north"} for i in range(most + 1)]
    assert "tilt" in refusal(document(*tilts)).detail
    limit = landform_catalog().values[("land", "features")].maximum
    many = [{"id": f"u{i}", "kind": "undulation"} for i in range(limit + 1)]
    assert refusal(document(*many)).path == "features"


def test_a_shore_needs_level_ground_above_its_beach():
    shore = {"id": "sea", "kind": "shore", "side": "south", "beach_top_mm": 2500}
    low = refusal(document(shore, ground_mm=2000))
    assert low.path == "ground_mm" and "2500" in low.detail
    assert read_land_document(document(shore, ground_mm=2500)).ground_mm == 2500


def test_the_level_land_states_no_features_and_reads_as_itself():
    level = level_land()
    assert level.features == () and level.ground_mm == 0
    assert read_land_document(level.canonical()).sha256 == level.sha256
    assert level_land(4000).ground_mm == 4000


def test_reading_never_changes_the_document_it_was_given():
    raw = document(HILL, {"id": "swell", "kind": "undulation"})
    before = copy.deepcopy(raw)
    read_land_document(raw)
    assert raw == before
