"""The landscape document: an extent, an unchanged land and placed unchanged volumes, every value
held to its catalog, every refusal by path inside the landscape with its own code; the catalog and
the landscape rules pinned."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from exulanica.grammar.landscape import (
    LANDSCAPE_RULES_VERSION,
    PROFILE,
    SERVED_LANDSCAPE_RULES,
    LandscapeRefused,
    check_landscape_rules,
    landscape_catalog,
    landscape_rules,
    read_landscape_document,
)
from exulanica.grammar.volumes import read_volume_document, volume_rules

CATALOGS = Path(__file__).parents[1] / "assets" / "catalogs" / "landscape"

#: Every shipped landscape catalog, byte for byte: a change is a new file and a new rules version.
SHIPPED = {
    "landscape-value.v1.json": "9a387c2766f5ed92954046395bff4946fad94e846d78e2e5d48690b182ba1b7e"
}
#: Each landscape rules version: its catalog digest and the volume rules version it names.
RULES = {
    1: {
        "catalogs": {
            "landscape-value.v1": "26c04b3bae0d03b02fe1544cbdda2722f61036d6d7b4a6f1dbccd217e968bf31"
        },
        "volume_rules": 1,
    }
}

#: A small weathered stack with a level top.
ROCK = {
    "profile": "exulanica.volume/v1",
    "id": "rock",
    "erosion": {"amplitude_mm": 800, "wavelength_mm": 6000, "octaves": 2},
    "parts": [
        {"id": "body", "shape": "column", "height_mm": 14000, "base_radius_mm": 5000,
         "top_radius_mm": 6500},
        {"id": "top", "shape": "cap", "height_mm": 11000},
    ],
}  # fmt: skip
LAND = {"profile": "exulanica.landform/v1", "ground_mm": 2000, "features": []}
#: The same stack placed twice in a small bay.
BAY = {
    "profile": PROFILE,
    "extent_mm": [128000, 96000],
    "land": LAND,
    "volumes": [
        {"id": "west_stack", "volume": ROCK, "at_mm": [30000, 40000, -3000]},
        {"id": "east_stack", "volume": ROCK, "at_mm": [90000, 50000, -3000], "yaw_mdeg": 45000},
    ],
}
BAY_SHA256 = "4dfd005deec4499e5319b72eb42e22ca58ca4dd1698c118bfa2c47ded070fc53"


def refusal(raw: object) -> LandscapeRefused:
    with pytest.raises(LandscapeRefused) as caught:
        read_landscape_document(raw)
    return caught.value


def test_the_shipped_catalog_is_never_edited_and_holds_its_defaults():
    found = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in CATALOGS.iterdir()
    }
    assert found == SHIPPED
    for bound in landscape_catalog().values.values():
        assert bound.minimum <= bound.default <= bound.maximum


def test_a_landscape_is_read_with_its_defaults_and_every_piece_whole_with_its_digest():
    read = read_landscape_document(BAY)
    canonical = read.canonical()
    assert canonical["finest_cell_mm"] == 2000 and read.levels == (4000, 2000)
    rock = read_volume_document(ROCK)
    assert [placement["volume_sha256"] for placement in canonical["volumes"]] == [rock.sha256] * 2
    assert canonical["volumes"][0]["yaw_mdeg"] == 0
    assert canonical["volumes"][0]["volume"] == rock.canonical()
    assert canonical["land"]["ground_mm"] == 2000
    assert read.sha256 == hashlib.sha256(read.canonical_bytes).hexdigest() == BAY_SHA256
    assert read_landscape_document(canonical).canonical_bytes == read.canonical_bytes


def test_a_volume_may_stand_on_the_land_beyond_the_extent_within_its_ring_of_chunks():
    # The land is realized over the extent and one ring of 128 m chunks round it: 128 m beyond
    # the south-west corner, and to the next whole chunk and one more beyond the far corner.
    ring = copy.deepcopy(BAY)
    ring["volumes"][0]["at_mm"] = [-128000, -60000, -3000]
    ring["volumes"][1]["at_mm"] = [256000, 256000, -3000]
    read = read_landscape_document(ring)
    assert [placement.at_mm[:2] for placement in read.placements] == [
        (-128000, -60000),
        (256000, 256000),
    ]


def test_reading_never_changes_the_document_it_was_given():
    raw = copy.deepcopy(BAY)
    read_landscape_document(raw)
    assert raw == BAY


def _with(path: tuple, value: object) -> dict:
    raw = copy.deepcopy(BAY)
    target = raw
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return raw


@pytest.mark.parametrize(
    ("path", "value", "where", "code"),
    [
        (("profile",), "exulanica.landscape/v2", "profile", "landscape_invalid"),
        (("sky",), [], "", "landscape_invalid"),
        (("extent_mm",), [10, 96000], "extent_mm[0]", "landscape_invalid"),
        (("extent_mm",), [128000], "extent_mm", "landscape_invalid"),
        (("finest_cell_mm",), 3000, "finest_cell_mm", "landscape_invalid"),
        (("finest_cell_mm",), 250, "finest_cell_mm", "landscape_invalid"),
        (("land", "ground_mm"), 99_000_000, "land.ground_mm", "landform_invalid"),
        (("volumes", 0, "volume", "parts", 0, "height_mm"), 500,
         "volumes[0].volume.parts[0].height_mm", "volume_invalid"),
        (("volumes", 0, "volume", "parts", 1, "op"), "add", "volumes[0].volume.parts[1].op",
         "volume_part_wrong_op"),
        (("volumes", 1, "at_mm"), [300000, 50000, 0], "volumes[1].at_mm",
         "landscape_outside_near_land"),
        (("volumes", 1, "at_mm"), [90000, -140000, 0], "volumes[1].at_mm",
         "landscape_outside_near_land"),
        (("volumes", 1, "at_mm"), [90000, 50000], "volumes[1].at_mm", "landscape_invalid"),
        (("volumes", 1, "yaw_mdeg"), 360000, "volumes[1].yaw_mdeg", "landscape_invalid"),
        (("volumes", 1, "id"), "west_stack", "volumes[1].id", "landscape_invalid"),
        (("volumes", 1, "colour"), "red", "volumes[1]", "landscape_invalid"),
        (("volumes", 1, "volume_sha256"), "0" * 64, "volumes[1].volume_sha256",
         "landscape_digest_mismatch"),
    ],
)  # fmt: skip
def test_every_refusal_names_its_path_inside_the_landscape_and_its_own_code(
    path, value, where, code
):
    refused = refusal(_with(path, value))
    assert (refused.path, refused.code) == (where, code)


def test_a_landscape_places_at_most_its_catalog_volumes_and_may_place_none():
    most = landscape_catalog().values[("landscape", "volumes")].maximum
    many = [{"id": f"stack_{n}", "volume": ROCK, "at_mm": [1000, 1000, 0]} for n in range(most + 1)]
    assert refusal({**BAY, "volumes": many}).path == "volumes"
    assert read_landscape_document({**BAY, "volumes": many[:most]}).placements[-1].id == (
        f"stack_{most - 1}"
    )
    bare = {key: value for key, value in BAY.items() if key != "volumes"}
    assert read_landscape_document(bare).placements == ()


def test_the_landscape_rules_name_the_catalog_and_the_volume_rules():
    assert LANDSCAPE_RULES_VERSION in SERVED_LANDSCAPE_RULES
    assert set(RULES) == set(SERVED_LANDSCAPE_RULES)
    for version, named in RULES.items():
        assert landscape_rules(version) == {
            "version": version,
            "volume_rules": volume_rules(named["volume_rules"]),
            "catalogs": named["catalogs"],
        }
        assert check_landscape_rules(landscape_rules(version)) == SERVED_LANDSCAPE_RULES[version][0]


@pytest.mark.parametrize(
    "named",
    [
        None,
        {**landscape_rules(), "version": 2},
        {**landscape_rules(), "volume_rules": {"version": 2, "catalogs": {}}},
        {**landscape_rules(), "catalogs": {"landscape-value.v1": "0" * 64}},
    ],
)
def test_landscape_rules_this_server_does_not_serve_are_refused_by_name(named):
    with pytest.raises(LandscapeRefused) as caught:
        check_landscape_rules(named)
    assert caught.value.code == "landscape_rules_changed"
