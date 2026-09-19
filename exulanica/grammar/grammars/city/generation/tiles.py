"""A generated city cut into tile documents, and the rules a whole city owes that no tile can check.

:func:`generate_city` runs the city grammar for a specification. :func:`tile_document` builds the
tile record for one tile (the seed, the grammar pin by descriptor digest, the catalog digest, the
tile coordinate, the level of detail and the edit delta digest) and selects the records that tile
carries with :func:`~exulanica.grammar.grammars.city.document.select_tile`.

**City reference closure** (:func:`check_city_reference_closure`). A tile lists as external every
identity a carried record names that the tile does not carry. A whole generated city is closed
when every such identity, across every tile the city covers, is carried by some tile of that same
city: nothing a tile points at is missing from the world. The document check cannot see this,
because it sees one tile.

**The edit delta subsequence** (:func:`tile_edit_subsequence`, :func:`edit_delta_digest`). A
tile's ``edit_delta_digest`` covers, in log order, exactly the edits whose targets are subjects the
tile carries, owned or halo: SHA-256 over the canonical JSON list of the edits' digests as
lowercase hex, never sorted. An edit elsewhere in the city leaves the tile's key alone; an edit to
a subject it carries, or the same edits in another order, moves it. The empty subsequence is
:data:`~exulanica.grammar.grammars.city.tile.EMPTY_EDIT_DELTA_DIGEST`. What an edit and its digest
are belongs to the edit log, which does not exist yet; this fixes only how a tile selects and folds
them, the same fold ``exulanica.ingest.stages.edit_delta_digest_of`` states.

**Pieces no longer than 1 km** (:func:`check_piece_lengths`). The tessellator's facing rule scales
a direction toward the grammar's direction bound, so every straight piece of a centreline, kerb
line or lane is at most 1 km long in plan.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise
from typing import Final

from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.catalogs import Catalog, catalog_digest
from exulanica.grammar.contract import Generation, generate
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import integer_sqrt
from exulanica.grammar.grammars.city import CITY_GRAMMAR
from exulanica.grammar.grammars.city.document import (
    TileDocument,
    descriptor_sha256,
    select_tile,
)
from exulanica.grammar.grammars.city.tile import (
    ANCHOR_FLOOR_DIVISION,
    EMPTY_EDIT_DELTA_DIGEST,
    EXTENT_MEETS_GROWN_SQUARE,
    HALO_RADIUS_MM,
    TILE_SIZE_MM,
    WRITTEN_COORDINATE_UNIT,
    GrammarPin,
    TileRecord,
)
from exulanica.grammar.parameters import CascadeBinding

__all__ = [
    "PIECE_LIMIT_MM",
    "check_city_reference_closure",
    "check_piece_lengths",
    "city_records",
    "edit_delta_digest",
    "generate_city",
    "tile_document",
    "tile_edit_subsequence",
    "tile_record",
]

#: The longest straight piece a record may state: the tessellator's facing limit.
PIECE_LIMIT_MM: Final = 1_000_000


def generate_city(
    *, seed: str, subject_identity: str, bindings: Sequence[CascadeBinding]
) -> Generation:
    return generate(CITY_GRAMMAR, seed=seed, subject_identity=subject_identity, bindings=bindings)


def city_records(generation: Generation) -> tuple[object, ...]:
    """Every record the city's stages emitted, in stage order."""
    return tuple(record for emission in generation.emissions for record in emission.records)


def tile_record(
    *,
    seed: str,
    catalogs: Sequence[Catalog],
    tile_x: int,
    tile_y: int,
    lod: int,
    edit_delta_digest: str = EMPTY_EDIT_DELTA_DIGEST,
) -> TileRecord:
    return TileRecord(
        city_seed=seed,
        grammar_versions=(
            GrammarPin(
                CITY_GRAMMAR.key.grammar_id, CITY_GRAMMAR.key.grammar_version, descriptor_sha256()
            ),
        ),
        coordinate_unit=WRITTEN_COORDINATE_UNIT,
        catalog_digest=catalog_digest(catalogs),
        tile_x=tile_x,
        tile_y=tile_y,
        lod=lod,
        tile_size_mm=TILE_SIZE_MM,
        halo_radius_mm=HALO_RADIUS_MM,
        ownership_rule=ANCHOR_FLOOR_DIVISION,
        halo_rule=EXTENT_MEETS_GROWN_SQUARE,
        edit_delta_digest=edit_delta_digest,
    )


def tile_document(
    records: Sequence[object],
    *,
    seed: str,
    subject_identity: str,
    catalogs: Sequence[Catalog],
    tile_x: int,
    tile_y: int,
    lod: int,
    edit_delta_digest: str = EMPTY_EDIT_DELTA_DIGEST,
) -> TileDocument:
    tile = tile_record(
        seed=seed,
        catalogs=catalogs,
        tile_x=tile_x,
        tile_y=tile_y,
        lod=lod,
        edit_delta_digest=edit_delta_digest,
    )
    return select_tile(tile, records, subject_identity=subject_identity)


def check_city_reference_closure(documents: Sequence[TileDocument]) -> None:
    """Every external identity of every tile is carried by some tile of the same city."""
    carried: set[str] = set()
    external: dict[str, str] = {}
    for document in documents:
        for grammar in document.grammars:
            carried.update(record.identity for record in grammar.records())  # type: ignore[attr-defined]
            external.update(dict(grammar.external))
    missing = sorted(identity for identity in external if identity not in carried)
    if missing:
        raise InvalidRecordError(
            f"[city_reference_closure] {len(missing)} external identities no tile of the city "
            f"carries, first {missing[0]} ({external[missing[0]]})"
        )


def _points(record: object) -> list[tuple[tuple[int, ...], ...]]:
    lines = []
    for name in ("centreline_mm", "kerb_line_mm", "path_mm", "line_mm"):
        value = getattr(record, name, None)
        if value:
            lines.append(value)
    return lines


def check_piece_lengths(records: Sequence[object]) -> None:
    """No straight piece a record states is longer than :data:`PIECE_LIMIT_MM` in plan."""
    for record in records:
        for line in _points(record):
            for here, after in pairwise(line):
                dx, dy = after[0] - here[0], after[1] - here[1]
                if integer_sqrt(dx * dx + dy * dy) > PIECE_LIMIT_MM:
                    raise InvalidRecordError(
                        f"[piece_length] {type(record).__name__} "
                        f"{getattr(record, 'identity', '')} has a piece longer than "
                        f"{PIECE_LIMIT_MM} mm"
                    )


def edit_delta_digest(ordered_edit_digests: Sequence[bytes]) -> str:
    """The fold of an ordered edit subsequence: SHA-256 over their hex digests, in order."""
    for digest in ordered_edit_digests:
        if not isinstance(digest, bytes) or len(digest) != 32:
            raise InvalidRecordError("an edit digest is 32 raw SHA-256 bytes")
    return sha256_of_canonical([digest.hex() for digest in ordered_edit_digests]).hex()


def tile_edit_subsequence(
    document: TileDocument, edits: Sequence[tuple[str, bytes]]
) -> tuple[bytes, ...]:
    """The digests of the edits, in log order, whose target identity the tile carries."""
    carried = {
        record.identity  # type: ignore[attr-defined]
        for grammar in document.grammars
        for record in grammar.records()
    }
    return tuple(digest for target, digest in edits if target in carried)
