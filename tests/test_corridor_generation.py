"""The corridor city, generated from its specification, cut into tiles and held to every check.

The corridor specification (``exulanica/grammar/grammars/city/generation/corridor.py``) binds a
640 m by 128 m level city. Its generators emit records only; these tests cut the city into its
five tiles, validate each with the tile document check, and hold the whole city to the rules no
single tile can check: every external reference is carried by some tile, and no straight piece is
longer than 1 km.
"""

from __future__ import annotations

from collections import Counter

import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.grammars.city.document import (
    TileDocument,
    document_bytes,
    validate_city_document,
)
from exulanica.grammar.grammars.city.generation.corridor import (
    CORRIDOR_BINDINGS,
    CORRIDOR_CITY_IDENTITY,
    CORRIDOR_SEED,
    CORRIDOR_TILE,
    CORRIDOR_TILES,
)
from exulanica.grammar.grammars.city.generation.tiles import (
    check_city_reference_closure,
    check_piece_lengths,
    city_records,
    generate_city,
)
from exulanica.grammar.grammars.city.streets import (
    BlockRecord,
    CurbEdgeRecord,
    StreetRecord,
    StreetSegmentRecord,
)
from exulanica.grammar.records import record_payload

from corridor_city import catalogs, documents, records


def _catalogs():
    return catalogs()


def _records() -> tuple[object, ...]:
    return records()


def _documents() -> dict[tuple[int, int], TileDocument]:
    return documents()


def test_generating_the_corridor_twice_gives_the_same_records():
    again = city_records(
        generate_city(
            seed=CORRIDOR_SEED, subject_identity=CORRIDOR_CITY_IDENTITY, bindings=CORRIDOR_BINDINGS
        )
    )
    assert sha256_of_canonical([record_payload(item) for item in again]) == sha256_of_canonical(
        [record_payload(item) for item in _records()]
    )


@pytest.mark.parametrize("tile", CORRIDOR_TILES)
def test_every_corridor_tile_validates(tile):
    document = _documents()[tile]
    validate_city_document(document, catalogs=_catalogs())
    assert document_bytes(document)


def test_the_city_is_closed_over_its_references_and_its_pieces_are_short():
    check_city_reference_closure(list(_documents().values()))
    check_piece_lengths(_records())


def test_one_tile_alone_is_not_a_closed_city():
    """The west tile names streets that run the city's length; alone, their far segments are
    carried by no tile. (A single missing tile can still close, since halos overlap.)"""
    with pytest.raises(InvalidRecordError, match=r"\[city_reference_closure\]"):
        check_city_reference_closure([_documents()[(0, 0)]])


def test_the_corridor_tile_owns_the_corridor_segment_and_its_blocks():
    counts = Counter(type(record) for record in _records())
    assert counts[StreetRecord] == 7
    assert counts[StreetSegmentRecord] == 23
    assert counts[BlockRecord] == 6
    assert counts[CurbEdgeRecord] == 46
    owned = _documents()[CORRIDOR_TILE].grammars[0].owned
    high = [
        record
        for record in owned
        if isinstance(record, StreetSegmentRecord) and record.hierarchy == "high_street"
    ]
    assert [(record.centreline_mm[0][:2], record.centreline_mm[-1][:2]) for record in high] == [
        ((250_000, 64_000), (390_000, 64_000))
    ]
    blocks = [record for record in owned if isinstance(record, BlockRecord)]
    assert len(blocks) == 2
    for block in blocks:
        xs = [x for x, _y in block.boundary_mm]
        assert min(xs) >= 256_000 and max(xs) <= 384_000
