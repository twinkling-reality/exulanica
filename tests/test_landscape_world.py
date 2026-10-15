"""A site world laid out on a landscape: the same site on the landscape's land as on that land
alone, composer six naming its landscape and landscape rules, volumes standing off the site, its
landscape drawn beside the site's drawing, and every receipt that no longer binds refused by
name."""

from __future__ import annotations

import copy

import pytest
from exulanica.grammar.grammars.site.records import SiteExtentRecord
from exulanica.grammar.landscape import LandscapeRefused, landscape_rules, read_landscape_document
from exulanica.world.composers import site_plan
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.landscape_drawing import (
    LANDSCAPE_DRAWING_PROFILE,
    landscape_drawing,
    landscape_drawing_sha256,
)
from exulanica.world.site_drawing import LAND_DRAWING_PROFILE, site_drawing, site_drawing_sha256

from test_landscape_document import ROCK
from test_site_land import TILT, kind

WORLD = "world:generated:landscape"


def compose(**more):  # type: ignore[no-untyped-def]
    found = kind("farm")
    return site_plan.compose_kind(
        found, found.values(found.presets[0][0]), WORLD, place_id="place:landscape", **more
    )


@pytest.fixture(scope="module")
def on_land():  # type: ignore[no-untyped-def]
    return compose(land=TILT)


def extent_of(world) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    found = next(r for r in world.records if isinstance(r, SiteExtentRecord))
    return found.width_mm, found.depth_mm


def bay(on_land, **placement: object) -> dict:  # type: ignore[no-untyped-def]
    """The farm's land with a weathered stack in the sea beyond its south edge."""
    width, depth = extent_of(on_land)
    stack = {"id": "stack", "volume": ROCK, "at_mm": [width // 2, -60000, -3000], **placement}
    return {
        "profile": "exulanica.landscape/v1",
        "extent_mm": [width, depth],
        "land": TILT,
        "volumes": [stack],
    }


@pytest.fixture(scope="module")
def on_landscape(on_land):  # type: ignore[no-untyped-def]
    return compose(landscape=bay(on_land))


def test_a_site_on_a_landscape_is_the_site_on_its_land_and_names_its_landscape(
    on_land, on_landscape
):
    receipt = on_landscape.receipt
    assert receipt["composer"] == {"key": "site-plan", "version": 6}
    assert site_plan.LANDSCAPE_COMPOSER_VERSION in site_plan.ON_LAND_VERSIONS
    landscape = read_landscape_document(bay(on_land))
    assert receipt["landscape"] == landscape.canonical()
    assert receipt["landscape_sha256"] == landscape.sha256
    assert receipt["landscape_rules"] == landscape_rules()
    # The land fields are the landscape's land, so the site is the one laid out on that land.
    for name in ("land", "land_sha256", "land_rules", "output_digest", "seed", "plan_sha256"):
        assert receipt[name] == on_land.receipt[name], name
    site_plan.check_receipt(receipt)
    assert site_plan.records(receipt) == tuple(on_landscape.records)


def test_its_site_is_drawn_on_its_land_and_its_landscape_beside_it(on_land, on_landscape):
    receipt, digest = on_landscape.receipt, on_landscape.receipt_sha256
    drawing = site_drawing(
        world_id=WORLD, receipt=receipt, receipt_sha256=digest, records=on_landscape.records
    )
    level = site_drawing(
        world_id=WORLD,
        receipt=on_land.receipt,
        receipt_sha256=on_land.receipt_sha256,
        records=on_land.records,
    )
    assert drawing["profile"] == LAND_DRAWING_PROFILE
    assert drawing["land"] == level["land"]
    landscape, bodies = landscape_drawing(WORLD, receipt, digest, site_drawing_sha256(drawing))
    assert landscape["profile"] == LANDSCAPE_DRAWING_PROFILE
    assert (landscape["receipt_sha256"], landscape["site_drawing_sha256"]) == (
        digest,
        site_drawing_sha256(drawing),
    )
    assert landscape["land_sha256"] == receipt["land_sha256"]
    assert landscape["landscape_sha256"] == receipt["landscape_sha256"]
    (stack,) = landscape["volumes"]
    assert stack["id"] == "stack" and stack["chunks"] and stack["tops"]
    named = {entry["sha256"] for entry in [*stack["chunks"], *stack["tops"]]}
    assert named == set(bodies)
    again, _ = landscape_drawing(WORLD, receipt, digest, site_drawing_sha256(drawing))
    assert landscape_drawing_sha256(again) == landscape_drawing_sha256(landscape)


def test_its_people_stand_on_its_land(on_landscape):
    place = site_plan.society_place("place:landscape", on_landscape.receipt, on_landscape.records)
    assert place == on_landscape.place


def _refused(on_land, raw: dict, **more) -> LandscapeRefused:  # type: ignore[no-untyped-def]
    with pytest.raises(LandscapeRefused) as caught:
        compose(landscape=raw, **more)
    return caught.value


def test_a_landscape_off_its_site_is_refused_by_name_and_path(on_land):
    width, depth = extent_of(on_land)
    wider = bay(on_land)
    wider["extent_mm"] = [width + 1000, depth]
    refused = _refused(on_land, wider)
    assert (refused.code, refused.path) == ("landscape_extent_not_site", "landscape.extent_mm")
    onto = bay(on_land, at_mm=[width // 2, depth // 2, 0])
    refused = _refused(on_land, onto)
    assert (refused.code, refused.path) == ("landscape_volume_on_site", "landscape.volumes[0]")
    # A stack just off the south edge reaches onto the site once its weathering is counted.
    close = bay(on_land, at_mm=[width // 2, -5000, -3000])
    assert _refused(on_land, close).code == "landscape_volume_on_site"
    inner = bay(on_land)
    inner["volumes"][0]["volume"] = {**ROCK, "erosion": {"amplitude_mm": 9000}}
    refused = _refused(on_land, inner)
    assert (refused.code, refused.path) == (
        "volume_invalid",
        "landscape.volumes[0].volume.erosion.amplitude_mm",
    )
    refused = _refused(on_land, bay(on_land), land=TILT)
    assert (refused.code, refused.path) == ("landscape_not_served", "landscape")


def _unreadable(receipt: dict) -> str:
    with pytest.raises(InvalidStructuralData) as caught:
        site_plan.check_receipt(receipt)
    return str(caught.value).split(":")[0]


def test_a_receipt_that_no_longer_binds_its_landscape_is_refused_by_name(on_land, on_landscape):
    receipt = on_landscape.receipt
    rules = copy.deepcopy(receipt)
    rules["landscape_rules"]["version"] = 3
    assert _unreadable(rules) == "generated_world_landscape_rules_changed"
    named = copy.deepcopy(receipt)
    named["landscape_sha256"] = "0" * 64
    assert _unreadable(named) == "generated_world_landscape_changed"
    other_land = copy.deepcopy(receipt)
    other_land["landscape"]["land"]["ground_mm"] = 9000
    assert _unreadable(other_land) == "generated_world_landscape_changed"
    unbound = copy.deepcopy(receipt)
    del unbound["landscape"]
    assert _unreadable(unbound) == "generated_world_landscape_changed"
    stray = copy.deepcopy(on_land.receipt)
    stray["landscape_rules"] = landscape_rules()
    assert _unreadable(stray) == "generated_world_landscape_rules_changed"


def test_a_world_made_by_the_first_landscape_rules_reads_and_draws_by_them(on_land, on_landscape):
    """A receipt written before the beds could vary names landscape rules 1: its volumes are read
    against the catalogs and realized by the volume rules those name, so it rebuilds unchanged."""
    first = read_landscape_document(bay(on_land), volume_rules=1)
    receipt = copy.deepcopy(on_landscape.receipt)
    receipt["landscape"] = first.canonical()
    receipt["landscape_sha256"] = first.sha256
    receipt["landscape_rules"] = landscape_rules(1)
    assert receipt["landscape"] != on_landscape.receipt["landscape"]
    site_plan.check_receipt(receipt)
    drawn, bodies = landscape_drawing(WORLD, receipt, "0" * 64, "1" * 64)
    assert drawn["landscape_rules_version"] == 1
    assert {body["rules_version"] for body in bodies.values()} == {1}
    (stack,) = drawn["volumes"]
    assert stack["volume_sha256"] == first.placements[0].volume.sha256
    newest, _ = landscape_drawing(WORLD, on_landscape.receipt, "0" * 64, "1" * 64)
    assert newest["landscape_rules_version"] == 2
