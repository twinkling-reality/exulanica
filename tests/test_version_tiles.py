"""A made town's tiles as a version with changes to its buildings draws them (migration 0219).

The town is the small town recipe composed for a fixed world id, so its seed and records are the
same on every run. The changed tiles are read from the tile documents themselves, so the expected
tiles are found here the same way and never retyped.
"""

from __future__ import annotations

import pytest
from exulanica.grammar.grammars.city.generation.massing import BuildingChange
from exulanica.grammar.grammars.city.tile import EMPTY_EDIT_DELTA_DIGEST, tile_inputs_digest
from exulanica.world import version_tiles
from exulanica.world.composers.city_grammar_town import (
    compose,
    records,
    records_with,
    tile_document_bytes,
    tile_documents,
)
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.generated_worlds import GeneratedRecords
from exulanica.world.town_parts import town_buildings
from exulanica.world.version_tiles import changed_tiles, changes_fold, folded
from exulanica.world.world_recipes import town_recipe

WORLD = "world:generated:00000000-0000-4000-8000-00000000c1a6"


@pytest.fixture(scope="module", name="town")
def _town():  # type: ignore[no-untyped-def]
    return compose(town_recipe("small_town"), WORLD)


@pytest.fixture(name="served")
def _served(town, monkeypatch):  # type: ignore[no-untyped-def]
    """The town's records as :mod:`exulanica.world.generated_worlds` reads them, without a
    database: the receipt and the records it generates, with or without a version's changes."""
    version_tiles.forget_changed_tiles(frozenset({town.receipt_sha256}))

    def read(*_scope):  # type: ignore[no-untyped-def]
        return GeneratedRecords(
            WORLD, None, town.receipt_sha256, town.receipt, records(town.receipt)
        )

    def read_with(*scope):  # type: ignore[no-untyped-def]
        return GeneratedRecords(
            WORLD, None, town.receipt_sha256, town.receipt, records_with(town.receipt, scope[-1])
        )

    monkeypatch.setattr(version_tiles, "town_records", read)
    monkeypatch.setattr(version_tiles, "town_records_with", read_with)
    return lambda changes: changed_tiles(None, None, WORLD, None, changes)


def _buildings(town):  # type: ignore[no-untyped-def]
    return [building.identity for building in town_buildings(records(town.receipt))]


def test_the_fold_is_the_changes_in_identity_order_and_never_the_empty_one(town):
    first, second = _buildings(town)[:2]
    two = {first: BuildingChange(removed=True), second: BuildingChange(storeys=2)}
    assert changes_fold(two) == changes_fold(dict(reversed(list(two.items()))))
    assert changes_fold({}) == EMPTY_EDIT_DELTA_DIGEST
    assert changes_fold(two) != EMPTY_EDIT_DELTA_DIGEST
    # A different storey count, or the same building removed instead, is another fold.
    assert changes_fold(two) != changes_fold({**two, second: BuildingChange(storeys=3)})
    assert changes_fold({first: BuildingChange(removed=True)}) != changes_fold(
        {first: BuildingChange(storeys=2)}
    )


def test_a_changed_tile_is_one_whose_document_the_changes_alter_keyed_by_their_fold(town, served):
    removed = {_buildings(town)[0]: BuildingChange(removed=True)}
    before = tile_documents(town.receipt, records(town.receipt))
    after = tile_documents(town.receipt, records_with(town.receipt, removed))
    altered = {
        (d.tile.tile_x, d.tile.tile_y)
        for d, e in zip(before, after, strict=True)
        if tile_document_bytes(d) != tile_document_bytes(e)
    }
    assert altered, "removing a building of the small town alters a tile"
    found = served(removed)
    assert {(t.tile_x, t.tile_y) for t in found} == altered
    fold = changes_fold(removed)
    public = {(d.tile.tile_x, d.tile.tile_y): tile_inputs_digest(d.tile) for d in before}
    for tile in found:
        assert tile.edit_delta_digest == fold
        # The key is the public tile's inputs with the fold in place of the empty one.
        [document] = [
            d for d in after if (d.tile.tile_x, d.tile.tile_y) == (tile.tile_x, tile.tile_y)
        ]
        assert tile.tile_inputs_digest == tile_inputs_digest(folded(document, fold).tile)
        assert tile.tile_inputs_digest != public[(tile.tile_x, tile.tile_y)]
        assert document.tile.edit_delta_digest == EMPTY_EDIT_DELTA_DIGEST
    # The same changes find the same tiles under the same keys, from memory or not.
    assert served(dict(removed)) == found
    version_tiles.forget_changed_tiles(frozenset({town.receipt_sha256}))
    assert served(dict(removed)) == found


def test_no_changes_or_changes_naming_no_building_of_the_town_alter_no_tile(served):
    assert served({}) == ()
    stranger = {"00000000-0000-5000-8000-000000000000": BuildingChange(removed=True)}
    assert served(stranger) == ()


def test_a_storey_count_the_grammar_refuses_is_refused_by_name(town, served):
    with pytest.raises(InvalidStructuralData, match="generated_world_unreadable"):
        served({_buildings(town)[0]: BuildingChange(storeys=400)})


def test_a_folded_document_differs_from_its_tile_only_in_the_fold(town):
    [document, *_] = tile_documents(town.receipt, records(town.receipt))
    fold = changes_fold({_buildings(town)[0]: BuildingChange(removed=True)})
    changed = folded(document, fold)
    assert changed.grammars == document.grammars
    assert changed.tile.edit_delta_digest == fold
    assert {**vars_of(changed.tile), "edit_delta_digest": None} == {
        **vars_of(document.tile),
        "edit_delta_digest": None,
    }


def vars_of(record):  # type: ignore[no-untyped-def]
    return {name: getattr(record, name) for name in record.__dataclass_fields__}
