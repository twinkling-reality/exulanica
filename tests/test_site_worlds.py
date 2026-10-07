"""A site world: composed from a world kind, regenerated from its receipt alone, drawn from slots.

The kinds are the hand-written fixtures in ``tests/fixtures/world-kinds`` (test fixtures, not kinds
a person or a model made). Expected figures are counted here from the records and the receipt.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.grammar.grammars.site.records import (
    SiteExtentRecord,
    SiteFixtureRecord,
    SiteStructureRecord,
    SiteWallRecord,
)
from exulanica.world.composers import UnknownWorldComposer, composer_module, receipt_sha256
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.kinds.catalogs import load_kind_catalogs
from exulanica.world.kinds.document import read_kind
from exulanica.world.site_drawing import DRAWING_PROFILE, site_drawing, site_drawing_sha256
from exulanica.world.society_place import validate_place
from exulanica.world.structure import validate_candidate

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"
SITE = composer_module("site-plan", 1)


def _composed(name: str, world_id: str = "world:generated:test"):  # type: ignore[no-untyped-def]
    kind = read_kind(json.loads((FIXTURES / f"fixture-{name}.json").read_text(encoding="utf-8")))
    return kind, SITE.compose_kind(kind, kind.values(kind.presets[0][0]), world_id)


@pytest.mark.parametrize("name", ["farm", "cafe", "site"])
def test_a_site_world_regenerates_from_its_receipt_alone(name: str) -> None:
    kind, composed = _composed(name)
    assert receipt_sha256(composed.receipt) == composed.receipt_sha256
    # The receipt carries the whole kind: the records come back from it with no library at all.
    stored = json.loads(json.dumps(composed.receipt))
    assert stored["kind"]["document"] == dict(kind.document)
    assert SITE.records(stored) == composed.records
    place = SITE.society_place("place:test", stored, composed.records)
    validate_place(place, SITE.receipt_routine(stored))


def test_a_site_world_s_snapshot_states_its_extent_spawn_and_receipt():
    _kind, composed = _composed("farm")
    validate_candidate(composed.candidate)
    extent = next(r for r in composed.records if isinstance(r, SiteExtentRecord))
    stated = SITE.stated_extent(composed.candidate.topology, composed.candidate.placement)
    assert stated.east_mm == (0, extent.width_mm)
    assert stated.south_mm == (-extent.depth_mm, 0)
    east, north = composed.receipt["arrival"]["position_mm"]
    assert stated.arrival_mm == (east, 0, -north)
    assert SITE.receipt_digest_of(composed.candidate.topology) == composed.receipt_sha256
    assert SITE.tile_inputs(composed.receipt) == ()


def test_a_receipt_whose_output_changed_is_refused_by_name():
    _kind, composed = _composed("farm")
    changed = copy.deepcopy(dict(composed.receipt))
    changed["seed"] = "7" * 64
    with pytest.raises(InvalidStructuralData, match="generated_world_output_changed"):
        SITE.records(changed)
    # The catalogs' digests are a record of what the kind was checked against, not a gate: a world
    # whose plan and records come out as they were regenerates after a catalog is edited.
    catalogs = copy.deepcopy(dict(composed.receipt))
    catalogs["catalogs"] = {**catalogs["catalogs"], "look-family": "0" * 64}
    assert SITE.records(catalogs) == composed.records
    kind = copy.deepcopy(dict(composed.receipt))
    kind["kind"]["sha256"] = "0" * 64
    with pytest.raises(InvalidStructuralData, match="generated_world_unreadable"):
        SITE.records(kind)


def test_a_recipe_never_composes_a_site_world():
    with pytest.raises(UnknownWorldComposer):
        SITE.compose(object(), "world:generated:x")


def test_the_drawing_draws_every_record_and_keeps_walkers_out_of_walls():
    _kind, composed = _composed("farm")
    drawing = site_drawing(
        world_id="world:generated:test",
        receipt=composed.receipt,
        receipt_sha256=composed.receipt_sha256,
        records=composed.records,
    )
    assert drawing["profile"] == DRAWING_PROFILE
    identities = [slot["identity"] for slot in drawing["slots"]]
    assert len(identities) == len(set(identities))
    fixtures = [r for r in composed.records if isinstance(r, SiteFixtureRecord)]
    structures = [r for r in composed.records if isinstance(r, SiteStructureRecord)]
    for record in [*fixtures, *structures]:
        assert record.identity in identities
    for structure in structures:
        assert f"{structure.identity}:roof" in identities
    families = load_kind_catalogs().families
    for slot in drawing["slots"]:
        family = slot["lookRole"].split(".")[0]
        assert slot["fit"] == families[family].fit
        # As agreed with the style packs: every surface slot carries its UV frame.
        assert families[family].fit != "surface" or "uvFrame" in slot
    # Every wall's solid run blocks a walker, and none of its openings does: counted from the
    # wall records here.
    walls = [r for r in composed.records if isinstance(r, SiteWallRecord)]
    solid = 0
    for wall in walls:
        length = (wall.end_x_mm - wall.start_x_mm) + (wall.end_y_mm - wall.start_y_mm)
        reached = 0
        for opening in wall.openings:
            solid += opening.offset_mm > reached
            reached = opening.offset_mm + opening.width_mm
        solid += reached < length
    blocking_fixtures = sum(1 for r in fixtures if r.blocks)
    assert len(drawing["walk"]["blockersMm"]) == solid + blocking_fixtures
    assert drawing["arrival"]["positionMm"][:2] == composed.receipt["arrival"]["position_mm"]


def test_one_world_draws_the_same_document_each_time_and_another_world_another():
    _kind, first = _composed("site", "world:generated:a")
    _kind, again = _composed("site", "world:generated:a")
    _kind, other = _composed("site", "world:generated:b")

    def drawn(composed: Any, world_id: str) -> str:
        return site_drawing_sha256(
            site_drawing(
                world_id=world_id,
                receipt=composed.receipt,
                receipt_sha256=composed.receipt_sha256,
                records=composed.records,
            )
        )

    assert drawn(first, "world:generated:a") == drawn(again, "world:generated:a")
    assert drawn(first, "world:generated:a") != drawn(other, "world:generated:b")


def _offsite_home(place: dict[str, Any]) -> dict[str, Any]:
    return next(d for d in place["destinations"] if d["destination_id"] == "home:offsite")


def test_the_home_off_the_site_is_the_kind_s_own_words_or_the_catalog_s():
    # The building site's workers live off the site. Stating nothing, their home is the catalog's.
    _kind, composed = _composed("site")
    default = load_kind_catalogs().society_defaults["offsite_home"]
    stored = json.loads(json.dumps(composed.receipt))
    place = SITE.society_place("place:test", stored, composed.records)
    home = _offsite_home(place)
    assert (home["label"], home["use_class"]) == (default.words, default.use_class)
    assert stored["society"]["offsite_home"] == {
        "label": default.words,
        "use_class": default.use_class,
    }
    # A receipt written before kinds stated it records none, and reads the catalog's: the same
    # place.
    older = copy.deepcopy(stored)
    del older["society"]["offsite_home"]
    assert SITE.society_place("place:test", older, composed.records) == place
    # A kind that says where its people sleep is read in its own words.
    document = json.loads((FIXTURES / "fixture-site.json").read_text(encoding="utf-8"))
    document["society"]["offsite_home"] = {
        "label": "the workers' hostel in town",
        "use_class": "residential",
    }
    stated = read_kind(document)
    made = SITE.compose_kind(stated, stated.values(stated.presets[0][0]), "world:generated:test")
    home = _offsite_home(SITE.society_place("place:test", dict(made.receipt), made.records))
    assert (home["label"], home["use_class"]) == ("the workers' hostel in town", "residential")


@pytest.mark.parametrize(
    ("home", "code"),
    [
        ({"label": "the canteen", "use_class": "cafe"}, "kind_role_unmet"),
        ({"label": "nowhere", "use_class": "no_such_use"}, "kind_reference_unknown"),
        ({"label": "", "use_class": "residential"}, "kind_out_of_bounds"),
        ({"label": "a hostel"}, "kind_document_invalid"),
    ],
)
def test_a_home_off_the_site_that_is_no_home_is_refused_by_name(home, code):
    from exulanica.world.kinds.document import KindRefused

    document = json.loads((FIXTURES / "fixture-site.json").read_text(encoding="utf-8"))
    document["society"]["offsite_home"] = home
    with pytest.raises(KindRefused) as refused:
        read_kind(document)
    assert refused.value.code == code
    assert refused.value.where.startswith("society.offsite_home")


def test_a_site_world_s_people_are_where_its_kind_says_and_a_town_s_where_they_were():
    from exulanica.world.society_living_decisions import living_situation
    from exulanica.world.society_repository import consumed_places

    defaults = load_kind_catalogs().society_defaults
    _kind, composed = _composed("farm")
    place = SITE.society_place("place:test", dict(composed.receipt), composed.records)
    assert place["words"] == {"here": defaults["here"].words, "around": defaults["around"].words}
    document = json.loads((FIXTURES / "fixture-farm.json").read_text(encoding="utf-8"))
    document["society"]["place_words"] = {"here": "on this farm", "around": "across the farm"}
    stated = read_kind(document)
    made = SITE.compose_kind(stated, stated.values(stated.presets[0][0]), "world:generated:test")
    place = SITE.society_place("place:test", dict(made.receipt), made.records)
    assert place["words"] == {"here": "on this farm", "around": "across the farm"}
    # A person asked to choose is told where they are; a town's person, as always, in the town.
    context = {
        "clock": {"minute_of_day": 8 * 60, "day": 1},
        "doing": {"status": "active"},
        "role": None,
        "needs": [],
    }
    assert living_situation(context)[0].startswith("It is 08:00 on day 1 in the town, ")
    assert living_situation({**context, "here": "on this farm"})[0].startswith(
        "It is 08:00 on day 1 on this farm, "
    )
    # The places an input states serve the words, keyed by the ground the catalog keys them by.
    served = consumed_places(
        {
            "input_seq": 1,
            "document_sha256": "a" * 64,
            "availability": "available",
            "unavailable_reason": None,
            "navigation": {"profile": "site-walking-surfaces/v1", "clearance_mm": 340},
            "targets": [],
            "living": {"place": place},
        }
    )
    assert served["place_words"] == {
        "ground": "generated_site",
        "here": "on this farm",
        "around": "across the farm",
    }
    town = dict(place)
    del town["words"]
    served = consumed_places(
        {
            "input_seq": 1,
            "document_sha256": "a" * 64,
            "availability": "available",
            "unavailable_reason": None,
            "navigation": {"profile": "city-walking-surfaces/v1", "clearance_mm": 340},
            "targets": [],
            "living": {"place": town},
        }
    )
    assert "place_words" not in served


@pytest.mark.parametrize(
    ("words", "code"),
    [
        ({"here": "on this farm"}, "kind_document_invalid"),
        ({"here": "", "around": "across the farm"}, "kind_out_of_bounds"),
        ({"here": "on this farm\n", "around": "across the farm"}, "kind_document_invalid"),
    ],
)
def test_place_words_that_cannot_be_said_are_refused_by_name(words, code):
    from exulanica.world.kinds.document import KindRefused

    document = json.loads((FIXTURES / "fixture-farm.json").read_text(encoding="utf-8"))
    document["society"]["place_words"] = words
    with pytest.raises(KindRefused) as refused:
        read_kind(document)
    assert refused.value.code == code
    assert refused.value.where.startswith("society.place_words")
