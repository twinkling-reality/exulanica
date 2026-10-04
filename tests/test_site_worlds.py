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
    catalogs = copy.deepcopy(dict(composed.receipt))
    catalogs["catalogs"] = {**catalogs["catalogs"], "kind-bound": "0" * 64}
    with pytest.raises(InvalidStructuralData, match="generated_world_catalogs_changed"):
        SITE.records(catalogs)
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
