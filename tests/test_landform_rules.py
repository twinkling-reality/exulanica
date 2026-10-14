"""The land rules a world's receipt names hold still: a shipped landform catalog is never edited,
and a graded site is the same land until the rules' version says otherwise."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.grammar.grammars.site.records import (
    SiteAreaRecord,
    SiteExtentRecord,
    SitePathRecord,
    SiteZoneRecord,
)
from exulanica.grammar.landform import (
    LAND_RULES_VERSION,
    LandformRefused,
    check_land_rules,
    land_rules,
    read_land_document,
)
from exulanica.world.site_land import land_seed, site_land

CATALOGS = Path(__file__).parents[1] / "assets" / "catalogs" / "landform"

#: Every shipped landform catalog, byte for byte. A catalog changes by a new file
#: (``landform-value.v2.json``) and, for one that shapes land, a new rules version; never by an
#: edit, since a world made on land names the catalogs that shaped it.
SHIPPED = {
    "landform-feature.v1.json": "5da02f1b42b263f9d54981f34baedcd56a62af2df81c2878a94cb1f5977fbc50",
    "landform-recipe.v1.json": "3e1dd36edac2c739367431eb944c92e1971aeefc2b558c00da7cc6795ae61eca",
    "landform-surface.v1.json": "62dd3fd49c16be7c09def1996fc4b3c9ae023cb95bcf44e0019e0dec7e86e706",
    "landform-value.v1.json": "328c2b0f98b5fa7621a048916d774ef5de6b81cd68042bd58d4e0c77aeb9a9e6",
}

#: Each rules version: the catalogs it names, and the golden site's graded land under it. A change
#: that moves land is a new version with both pinned again; the old entries stay as the record.
RULES = {
    1: {
        "catalogs": {
            "landform-feature.v1": (
                "416d6f75670bc0fc3e7d3801f4a72f02014241db9ab0546ded013184043c5016"
            ),
            "landform-value.v1": "1f3eb0a980eb173b5cdd9135062a4cf0fd14c3bf75c8e38983b791b49820387a",
        },
        "golden_site": "1dfca9b52e76b075feab422c16ce8199c1cb9c1d7a12b6234e693c9ee9ec1620",
    },
}

#: Every feature kind once, a valley and a filled basin beside a terraced hill above a shore.
GOLDEN_LAND = {
    "profile": "exulanica.landform/v1",
    "ground_mm": 9000,
    "features": [
        {"id": "tilt", "kind": "tilt", "side": "north", "grade_permille": 30},
        {"id": "hill", "kind": "rise", "side": "north", "distance_mm": 30000, "width_mm": 420000,
         "depth_mm": 240000, "height_mm": 32000, "roughness_permille": 200, "offset_mm": -50000},
        {"id": "dale", "kind": "valley", "side": "east", "offset_mm": 90000, "width_mm": 80000,
         "floor_mm": 4000, "depth_mm": 5000},
        {"id": "swell", "kind": "undulation", "amplitude_mm": 1200, "wavelength_mm": 60000},
        {"id": "skyline", "kind": "range", "side": "north", "distance_mm": 2000000,
         "band_mm": 800000, "height_mm": 300000},
        {"id": "sea", "kind": "shore", "side": "south", "distance_mm": 70000, "beach_mm": 25000},
        {"id": "mere", "kind": "basin", "side": "west", "distance_mm": 90000, "radius_mm": 20000,
         "water": "fill"},
        {"id": "steps", "kind": "terraces", "side": "north", "distance_mm": 40000,
         "depth_mm": 110000, "width_mm": 220000, "tier_height_mm": 2500, "offset_mm": -50000},
    ],
}  # fmt: skip

#: A site of one path, two zones and a pond, as the site grammar's records state them.
GOLDEN_SITE = (
    SiteExtentRecord("site:extent", "golden", 48000, 60000, 4000, "fence", "ground", "grass",
                     24000, 4000, 1200, 200),
    SitePathRecord("site:path:0", 0, "spine", 22000, 0, 26000, 44000, ("footway",), "ground",
                   "gravel"),
    SiteZoneRecord("site:zone:0", 0, "yard", 4000, 8000, 20000, 24000, "east", "open", "ground",
                   "grass", 20000, 16000),
    SiteZoneRecord("site:zone:1", 1, "garden", 28000, 28000, 44000, 44000, "west", "open",
                   "ground", "grass", 28000, 36000),
    SiteAreaRecord("site:area:0", "site:zone:1", 0, "pond", 32000, 32000, 40000, 40000,
                   ("water",), "water", "pond", 32000, 36000),
)  # fmt: skip


def test_no_shipped_landform_catalog_is_edited() -> None:
    found = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in CATALOGS.iterdir()
    }
    assert {name: found.get(name) for name in SHIPPED} == SHIPPED, (
        "a shipped landform catalog changed: add the next version's file instead, and for a "
        "catalog that shapes land, the next LAND_RULES_VERSION"
    )


def test_the_land_rules_name_their_version_and_the_catalogs_that_shape_land() -> None:
    rules = land_rules()
    assert rules == {
        "version": LAND_RULES_VERSION,
        "catalogs": RULES[LAND_RULES_VERSION]["catalogs"],
    }
    rules["catalogs"].clear()
    assert land_rules()["catalogs"] == RULES[LAND_RULES_VERSION]["catalogs"], "a new mapping a call"
    check_land_rules(land_rules())


@pytest.mark.parametrize(
    "other",
    [
        None,
        {"version": LAND_RULES_VERSION + 1, "catalogs": RULES[LAND_RULES_VERSION]["catalogs"]},
        {"version": LAND_RULES_VERSION, "catalogs": {"landform-feature.v1": "0" * 64}},
        {
            "version": LAND_RULES_VERSION,
            "catalogs": {**RULES[LAND_RULES_VERSION]["catalogs"], "landform-value.v1": "0" * 64},
        },
    ],
)
def test_land_made_by_other_rules_is_refused_saying_both(other: object) -> None:
    with pytest.raises(LandformRefused) as caught:
        check_land_rules(other)
    assert caught.value.code == "landform_rules_changed"
    assert f"this server makes land by land rules version {LAND_RULES_VERSION}" in str(caught.value)


def test_a_graded_site_is_the_same_land_until_the_rules_version_changes() -> None:
    land = read_land_document(GOLDEN_LAND)
    graded = site_land(land, GOLDEN_SITE, land_seed("world:golden", land.sha256), 4000)
    section = graded.drawing_section()
    assert {body["kind"] for body in section["water"]} == {"sea", "lake", "pond"}
    assert (
        hashlib.sha256(canonical_json(section)).hexdigest()
        == (RULES[LAND_RULES_VERSION]["golden_site"])
    ), (
        "the land a site is graded on moved: the realizer, its grading or a site's grading plan "
        "changed. Worlds already made on land name the rules that made them; a change that moves "
        "land is the next LAND_RULES_VERSION, pinned here with its golden site"
    )
