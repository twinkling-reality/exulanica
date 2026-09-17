"""The corridor tiles' keys, and the ordered edit subsequence proven to move them.

No edit log exists and no cache is enabled anywhere. This file still proves, with a synthetic
ordered delta fixture, that a tile's ``tile_inputs_digest`` (and so its ``baked_tile_id``) covers
exactly the edits that target subjects it carries, in their order: an edit to a carried subject
moves the key, the same edits in another order move it again, and an edit to a subject the tile
does not carry leaves it alone.
"""

from __future__ import annotations

import dataclasses
import hashlib

from exulanica.grammar.grammars.city.generation.corridor import CORRIDOR_TILE, CORRIDOR_TILES
from exulanica.grammar.grammars.city.generation.tiles import (
    edit_delta_digest,
    tile_edit_subsequence,
)
from exulanica.grammar.grammars.city.massing import MassingRecord
from exulanica.grammar.grammars.city.tile import EMPTY_EDIT_DELTA_DIGEST, tile_inputs_digest
from exulanica.ingest.stages import STAGES, baked_tile_id, edit_delta_digest_of

from corridor_city import documents


def _edit(name: str) -> bytes:
    return hashlib.sha256(f"synthetic corridor edit {name}".encode()).digest()


def _keyed(edits: list[tuple[str, bytes]]) -> tuple[str, str]:
    document = documents()[CORRIDOR_TILE]
    folded = edit_delta_digest(tile_edit_subsequence(document, edits))
    tile = dataclasses.replace(document.tile, edit_delta_digest=folded)
    return tile_inputs_digest(tile), str(baked_tile_id(STAGES["baked_tile"], tile))


def _owned_building(tile: tuple[int, int]) -> str:
    return next(
        record.identity
        for record in documents()[tile].grammars[0].owned
        if isinstance(record, MassingRecord)
    )


def test_every_corridor_tile_has_its_own_key_and_starts_with_no_edits():
    keys = {tile_inputs_digest(documents()[tile].tile) for tile in CORRIDOR_TILES}
    assert len(keys) == len(CORRIDOR_TILES)
    for tile in CORRIDOR_TILES:
        assert documents()[tile].tile.edit_delta_digest == EMPTY_EDIT_DELTA_DIGEST


def test_the_fold_is_the_ingest_stage_fold():
    digests = [_edit("a"), _edit("b")]
    assert edit_delta_digest(digests) == edit_delta_digest_of(digests)
    assert edit_delta_digest([]) == EMPTY_EDIT_DELTA_DIGEST


def test_an_ordered_edit_subsequence_moves_the_tile_key():
    here = _owned_building(CORRIDOR_TILE)
    halo = documents()[CORRIDOR_TILE].grammars[0].halo[0].identity  # type: ignore[attr-defined]
    elsewhere = _owned_building((0, 0))
    carried = {
        record.identity  # type: ignore[attr-defined]
        for record in documents()[CORRIDOR_TILE].grammars[0].records()
    }
    assert elsewhere not in carried
    empty = _keyed([])
    one = _keyed([(here, _edit("a"))])
    both = _keyed([(here, _edit("a")), (halo, _edit("b"))])
    swapped = _keyed([(halo, _edit("b")), (here, _edit("a"))])
    far = _keyed([(elsewhere, _edit("c"))])
    far_between = _keyed([(here, _edit("a")), (elsewhere, _edit("c")), (halo, _edit("b"))])
    assert empty == _keyed([])
    assert len({empty, one, both, swapped}) == 4
    assert far == empty
    assert far_between == both
