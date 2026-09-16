"""Tile: the inputs of one bounded materialisation. Record shape only; no generator.

A subject belongs to the tile that contains its parcel centroid. Generation reads a declared halo
around the tile. Both sizes are declared by this stage's version: version 1 is a 128 m tile with
a 64 m halo, and changing either is a new version.

:func:`tile_inputs_digest` is the digest over exactly the inputs the target architecture lists:
the city seed, the grammar version set, the catalog digest, the tile coordinate, the level of
detail, the halo radius, and the digest of the ordered edit subsequence that targets owned or
halo subjects. How that last digest is computed belongs to the edit log, which does not exist
yet; this record only carries it. Because it is a field of the digested payload, any change to
it changes the tile digest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.records import (
    record_payload,
    require_hex64,
    require_integer,
    require_key,
    require_record,
)
from exulanica.grammar.seed import require_seed

__all__ = [
    "HALO_RADIUS_MM",
    "STAGE",
    "STAGE_ID",
    "STAGE_VERSION",
    "TILE_SIZE_MM",
    "TileRecord",
    "tile_inputs_digest",
    "validate_tile",
]

STAGE_ID: Final = "tile"
STAGE_VERSION: Final = 1
TILE_SIZE_MM: Final = 128_000
HALO_RADIUS_MM: Final = 64_000


@dataclass(frozen=True, slots=True)
class TileRecord:
    RECORD_KIND: ClassVar[str] = "city.tile"
    RECORD_VERSION: ClassVar[int] = 1

    city_seed: str
    #: ``(grammar_id, grammar_version)`` pairs, sorted, one per grammar.
    grammar_versions: tuple[tuple[str, int], ...]
    catalog_digest: str
    tile_x: int
    tile_y: int
    lod: int
    tile_size_mm: int
    halo_radius_mm: int
    edit_delta_digest: str


def validate_tile(candidate: object) -> None:
    record = require_record(candidate, TileRecord)
    require_seed(record.city_seed)
    if not isinstance(record.grammar_versions, tuple) or not record.grammar_versions:
        raise InvalidRecordError("grammar_versions is a non-empty tuple of pairs")
    ids = []
    for index, pair in enumerate(record.grammar_versions):
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise InvalidRecordError(f"grammar_versions[{index}] is a (grammar_id, version) pair")
        ids.append(require_key(f"grammar_versions[{index}] id", pair[0]))
        require_integer(f"grammar_versions[{index}] version", pair[1], minimum=1)
    if ids != sorted(set(ids)):
        raise InvalidRecordError("grammar_versions is sorted and names each grammar once")
    require_hex64("catalog_digest", record.catalog_digest)
    require_integer("tile_x", record.tile_x)
    require_integer("tile_y", record.tile_y)
    require_integer("lod", record.lod, minimum=0)
    require_integer("tile_size_mm", record.tile_size_mm, minimum=TILE_SIZE_MM, maximum=TILE_SIZE_MM)
    require_integer(
        "halo_radius_mm", record.halo_radius_mm, minimum=HALO_RADIUS_MM, maximum=HALO_RADIUS_MM
    )
    require_hex64("edit_delta_digest", record.edit_delta_digest)


def tile_inputs_digest(record: TileRecord) -> str:
    validate_tile(record)
    return sha256_of_canonical(record_payload(record)).hex()


STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, (TileRecord, validate_tile))
