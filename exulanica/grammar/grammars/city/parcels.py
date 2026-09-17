"""Parcels: the lots a block is subdivided into, each with frontage. Record shape only.

A reserved memory precinct is a lot like any other, with a kerb, a frontage, a threshold and a
street address, so the city is coherent whether or not anything ever docks there and no hole is
ever cut into a block.

A parcel's centroid is its anchor: the parcel, every building on it and everything a building
owns belong to the tile that contains it. The first frontage is the primary one, where the
address and the threshold are.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar import shapes
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import (
    Extent,
    edge_run_length,
    extent_contains_ring,
    ring_centroid,
)
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.grammars.city.common import extent_field

__all__ = [
    "LOT_CLASSES",
    "SHAPE",
    "STAGE",
    "STAGE_ID",
    "STAGE_VERSION",
    "Frontage",
    "ParcelRecord",
]

STAGE_ID: Final = "parcels"
STAGE_VERSION: Final = 2
LOT_CLASSES: Final = ("building", "memory_precinct")


@dataclass(frozen=True, slots=True)
class Frontage:
    """One boundary edge of a lot that meets a footway, and the curb across that footway."""

    edge_ordinal: int
    curb_identity: str
    run_length_mm: int


FRONTAGE_SHAPE: Final = shapes.RecordShape(
    Frontage,
    (
        shapes.integer("edge_ordinal", 0),
        shapes.identity("curb_identity", "city.curb_edge"),
        shapes.integer("run_length_mm", 1),
    ),
)


@dataclass(frozen=True, slots=True)
class ParcelRecord:
    RECORD_KIND: ClassVar[str] = "city.parcel"
    RECORD_VERSION: ClassVar[int] = 2

    identity: str
    block_identity: str
    parcel_ordinal: int
    lot_class: str
    boundary_mm: tuple[tuple[int, int], ...]
    centroid_x_mm: int
    centroid_y_mm: int
    #: The finished level of the lot outside any building.
    grade_elevation_mm: int
    frontages: tuple[Frontage, ...]
    #: The sum of the frontages' run lengths.
    frontage_mm: int
    address_number: int
    #: Where the lot is entered, along the primary frontage edge from its start vertex.
    threshold_offset_mm: int
    extent: Extent


def _parcel_geometry(record: ParcelRecord) -> None:
    ring = record.boundary_mm
    if (record.centroid_x_mm, record.centroid_y_mm) != ring_centroid(ring):
        raise InvalidRecordError("a parcel's centroid is the ring centroid of its boundary")
    edges = [frontage.edge_ordinal for frontage in record.frontages]
    if len(set(edges)) != len(edges):
        raise InvalidRecordError("a parcel names each frontage edge once")
    for frontage in record.frontages:
        if frontage.edge_ordinal >= len(ring):
            raise InvalidRecordError(f"frontage edge {frontage.edge_ordinal} is not on the ring")
        if frontage.run_length_mm != edge_run_length(ring, frontage.edge_ordinal):
            raise InvalidRecordError(f"frontage edge {frontage.edge_ordinal} has another length")
    if record.frontage_mm != sum(frontage.run_length_mm for frontage in record.frontages):
        raise InvalidRecordError("frontage_mm is the sum of the frontage run lengths")
    if record.threshold_offset_mm > record.frontages[0].run_length_mm:
        raise InvalidRecordError("the threshold lies on the primary frontage")
    if not extent_contains_ring(record.extent, ring):
        raise InvalidRecordError("a parcel's boundary lies inside its extent")


SHAPE: Final = shapes.RecordShape(
    ParcelRecord,
    (
        shapes.identity("identity"),
        shapes.identity("block_identity", "city.block"),
        shapes.integer("parcel_ordinal", 0),
        shapes.choice("lot_class", LOT_CLASSES),
        shapes.ring("boundary_mm"),
        shapes.integer("centroid_x_mm"),
        shapes.integer("centroid_y_mm"),
        shapes.integer("grade_elevation_mm"),
        shapes.records("frontages", FRONTAGE_SHAPE, count_minimum=1),
        shapes.integer("frontage_mm", 1),
        shapes.integer("address_number", 1),
        shapes.integer("threshold_offset_mm", 0),
        extent_field(),
    ),
    rules=(shapes.RecordRule("parcel_geometry", _parcel_geometry),),
    identity=shapes.IdentityRule(
        "parcel", owner_field="block_identity", ordinal_field="parcel_ordinal"
    ),
    extent_field="extent",
)

STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, SHAPE)
