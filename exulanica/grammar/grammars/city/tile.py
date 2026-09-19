"""Tile: the inputs of one bounded materialisation, and who belongs to it. Record shape only.

Both sizes are declared by this stage's version: a 128 m tile with a 64 m halo, and changing
either is a new version. Tile ``(tile_x, tile_y)`` covers ``[tile_x * 128000,
(tile_x + 1) * 128000)`` on x and likewise on y: the south and west edges belong to it, the north
and east edges to its neighbours.

**Ownership** (``anchor_floor_division``). Every subject has one anchor point, and it belongs to
the tile that contains it, found by floor division. An anchor comes from the record's own fields
wherever the record's owner could be absent from a tile: a street node's is its point, a segment's
the floored midpoint of its centreline's end points, a block's and a parcel's their centroid, a
junction's the floored centre of its extent, and a terrain patch's its tile's south-west corner.
Every other subject shares its owner's anchor, and its extent lies inside its owner's in plan: a
segment's curbs, lanes, crossings, parking, furniture and trees; the record a marking marks; a
junction's lane connections; a parcel's building; and a building's facades, rooftop objects,
premises and vitrines, and a facade's ground bays and entrances. So a tile that carries a subject
by its extent always carries its owner, and a building and everything it owns belong to one tile.
A surface material, a junction approach and a signal have no extent and share the anchor of the
record they relate to. A district and a street have no single anchor, so no tile owns one.
``exulanica.grammar.grammars.city.document`` holds these rules as tables and checks them.

**The halo** (``extent_meets_grown_square``). A subject the tile does not own is in its halo when
the subject's stated extent, in plan, meets the tile grown by the halo radius on every side:
``[tile_x * 128000 - 64000, (tile_x + 1) * 128000 + 64000)`` on x and likewise on y, whose south
and west edges belong to it and whose north and east edges do not. The extent is used rather than
the anchor because a long segment or a large parcel anchored far away can still cross the tile,
and a bake that left it out would treat that ground as open. A record with no extent (a surface
material, a junction approach, a signal) belongs wherever the record it relates to belongs. A bake
draws owned subjects only and reads halo subjects for context.

Ownership reads the anchor alone, so every anchored subject is owned by exactly one tile, and it
is in the halo of every other tile whose grown square its extent reaches.

**The coordinate unit** (``coordinate_unit``, ADR-0024). The record states the unit its document's
coordinates are in, beside the grammar pins. It is stated rather than assumed because the container
asserts its records are in millimetres and, before version 3 of this record, the records asserted
nothing: a producer writing another unit was refused by nothing, and a reader had no way to tell a
document that means millimetres from one that does not. A document written at an earlier version
carries no such field and is millimetres because that version fixes it, never because a reader
supplied one.

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
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.grammars.city.common import TILE_SIZE_MM
from exulanica.grammar.records import record_payload

__all__ = [
    "COORDINATE_UNITS",
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
    "extent_meets_halo",
    "halo_square",
    "membership",
    "tile_inputs_digest",
    "tile_of",
]

STAGE_ID: Final = "tile"
STAGE_VERSION: Final = 3
HALO_RADIUS_MM: Final = 64_000
#: The coordinate units a tile document may declare (ADR-0024). One entry, and a second would be a
#: decision about the whole world rather than about one document: the quantum is a constant of the
#: tessellator version, so two of them coexisting would put a scaling step, and a place to be wrong
#: by a factor of a thousand, into every rule that reads two documents.
COORDINATE_UNITS: Final = ("millimetre",)
OWNERSHIP_RULES: Final = ("anchor_floor_division",)
HALO_RULES: Final = ("extent_meets_grown_square",)
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
    RECORD_VERSION: ClassVar[int] = 3

    city_seed: str
    #: Sorted by grammar id, one per grammar.
    grammar_versions: tuple[GrammarPin, ...]
    #: The unit every coordinate in this document is in. Stated rather than assumed: the container
    #: asserts its records are in millimetres, and before version 3 the records said nothing, so a
    #: reader could not tell a document that means millimetres from one that does not.
    coordinate_unit: str
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
        shapes.choice("coordinate_unit", COORDINATE_UNITS),
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


def halo_square(record: TileRecord) -> tuple[int, int, int, int]:
    """The tile grown by its halo radius: ``(low_x, low_y, high_x, high_y)``, lows inclusive."""
    return (
        record.tile_x * record.tile_size_mm - record.halo_radius_mm,
        record.tile_y * record.tile_size_mm - record.halo_radius_mm,
        (record.tile_x + 1) * record.tile_size_mm + record.halo_radius_mm,
        (record.tile_y + 1) * record.tile_size_mm + record.halo_radius_mm,
    )


def extent_meets_halo(record: TileRecord, extent: Extent) -> bool:
    """Whether an extent, in plan, shares a point with the tile grown by its halo radius."""
    low_x, low_y, high_x, high_y = halo_square(record)
    return (
        low_x <= extent.max_x_mm
        and extent.min_x_mm < high_x
        and low_y <= extent.max_y_mm
        and extent.min_y_mm < high_y
    )


def membership(record: TileRecord, anchor: tuple[int, int] | None, extent: Extent) -> str:
    """``owned``, ``halo`` or ``outside`` for a subject with this anchor and extent.

    Owned when the anchor lies in the tile; otherwise halo when the extent meets the grown square.
    ``anchor`` is ``None`` for a subject with no single anchor, which no tile owns.
    """
    if anchor is not None and tile_of(*anchor) == (record.tile_x, record.tile_y):
        return OWNED
    if extent_meets_halo(record, extent):
        return HALO
    return OUTSIDE_TILE


STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, SHAPE)
