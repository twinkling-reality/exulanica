"""Tile: the inputs of one bounded materialisation, and who belongs to it. Record shape only.

Both sizes are declared by this stage's version: a 128 m tile with a 64 m halo, and changing
either is a new version. Tile ``(tile_x, tile_y)`` covers ``[tile_x * 128000,
(tile_x + 1) * 128000)`` on x and likewise on y: the south and west edges belong to it, the north
and east edges to its neighbours.

**Ownership** (``anchor_floor_division``). Every subject has one anchor point, and it belongs to
the tile that contains it, found by floor division. A parcel's anchor is its centroid, and a
building and everything the building owns share its parcel's anchor. A block's is its centroid.
A street node's is its point, and its junction, the junction's approaches and connections and a
signal controlling it share it. A segment's is the floored midpoint of its two nodes, and its
street, lanes, curbs, crossings, parking, furniture, trees and markings share it (a signal on a
crossing shares the crossing's). A terrain patch's is its tile's south-west corner. A material
record shares its surface's. A district and a street have no single anchor: a tile carries each
one that any of its members names.

**The halo** (``chebyshev_square``). A subject is in a tile's halo when its anchor is outside the
tile and inside the tile grown by the halo radius on every side. A bake draws owned subjects only
and reads halo subjects for context.

:func:`tile_inputs_digest` is the digest over exactly the inputs the target architecture lists:
the city seed, the grammar version set, the catalog digest, the tile coordinate, the level of
detail, the halo radius, and the digest of the ordered edit subsequence that targets owned or halo
subjects. **Each grammar in the version set is pinned by its descriptor's SHA-256**, so a
descriptor edited without a version bump changes every tile key built on it. How the edit
subsequence is digested belongs to the edit log; the empty subsequence is
:data:`EMPTY_EDIT_DELTA_DIGEST`, the SHA-256 of the canonical empty list, which is a real value
and present from the first tile.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.grammar import shapes
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.grammars.city.common import TILE_SIZE_MM
from exulanica.grammar.records import record_payload

__all__ = [
    "EMPTY_EDIT_DELTA_DIGEST",
    "HALO",
    "HALO_RADIUS_MM",
    "HALO_RULES",
    "OUTSIDE_TILE",
    "OWNED",
    "OWNERSHIP_RULES",
    "SHAPE",
    "STAGE",
    "STAGE_ID",
    "STAGE_VERSION",
    "TILE_SIZE_MM",
    "GrammarPin",
    "TileRecord",
    "membership",
    "tile_inputs_digest",
    "tile_of",
]

STAGE_ID: Final = "tile"
STAGE_VERSION: Final = 2
HALO_RADIUS_MM: Final = 64_000
OWNERSHIP_RULES: Final = ("anchor_floor_division",)
HALO_RULES: Final = ("chebyshev_square",)
EMPTY_EDIT_DELTA_DIGEST: Final = sha256_of_canonical([]).hex()
OWNED: Final = "owned"
HALO: Final = "halo"
OUTSIDE_TILE: Final = "outside"


@dataclass(frozen=True, slots=True)
class GrammarPin:
    """One grammar in a tile's version set: its id, version and descriptor digest."""

    grammar_id: str
    grammar_version: int
    descriptor_sha256: str


GRAMMAR_PIN_SHAPE: Final = shapes.RecordShape(
    GrammarPin,
    (
        shapes.key("grammar_id"),
        shapes.integer("grammar_version", 1),
        shapes.hex64("descriptor_sha256"),
    ),
)


@dataclass(frozen=True, slots=True)
class TileRecord:
    RECORD_KIND: ClassVar[str] = "city.tile"
    RECORD_VERSION: ClassVar[int] = 2

    city_seed: str
    #: Sorted by grammar id, one per grammar.
    grammar_versions: tuple[GrammarPin, ...]
    catalog_digest: str
    tile_x: int
    tile_y: int
    lod: int
    tile_size_mm: int
    halo_radius_mm: int
    ownership_rule: str
    halo_rule: str
    edit_delta_digest: str


def _versions_sorted(record: TileRecord) -> None:
    ids = [pin.grammar_id for pin in record.grammar_versions]
    if ids != sorted(set(ids)):
        raise InvalidRecordError("grammar_versions is sorted and names each grammar once")


SHAPE: Final = shapes.RecordShape(
    TileRecord,
    (
        shapes.seed("city_seed"),
        shapes.records("grammar_versions", GRAMMAR_PIN_SHAPE, count_minimum=1),
        shapes.hex64("catalog_digest"),
        shapes.integer("tile_x"),
        shapes.integer("tile_y"),
        shapes.integer("lod", 0),
        shapes.integer("tile_size_mm", TILE_SIZE_MM, TILE_SIZE_MM),
        shapes.integer("halo_radius_mm", HALO_RADIUS_MM, HALO_RADIUS_MM),
        shapes.choice("ownership_rule", OWNERSHIP_RULES),
        shapes.choice("halo_rule", HALO_RULES),
        shapes.hex64("edit_delta_digest"),
    ),
    rules=(shapes.RecordRule("tile_grammar_versions_sorted", _versions_sorted),),
)


def tile_inputs_digest(record: TileRecord) -> str:
    shapes.validate_record(record, SHAPE)
    return sha256_of_canonical(record_payload(record)).hex()


def tile_of(x_mm: int, y_mm: int) -> tuple[int, int]:
    """The tile that owns a point: floor division by the tile size."""
    return x_mm // TILE_SIZE_MM, y_mm // TILE_SIZE_MM


def membership(record: TileRecord, x_mm: int, y_mm: int) -> str:
    """``owned``, ``halo`` or ``outside`` for an anchor point, by the record's rules."""
    if tile_of(x_mm, y_mm) == (record.tile_x, record.tile_y):
        return OWNED
    low_x = record.tile_x * record.tile_size_mm - record.halo_radius_mm
    low_y = record.tile_y * record.tile_size_mm - record.halo_radius_mm
    high_x = (record.tile_x + 1) * record.tile_size_mm + record.halo_radius_mm
    high_y = (record.tile_y + 1) * record.tile_size_mm + record.halo_radius_mm
    if low_x <= x_mm < high_x and low_y <= y_mm < high_y:
        return HALO
    return OUTSIDE_TILE


STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, SHAPE)
