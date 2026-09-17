"""The parcels generator: every block cut into two rows of lots, each lot with frontage.

**Rows.** A block is rectangular. Its row facing the higher-ranked street (the street-hierarchy
catalog's ``rank``, lower first; the south street on a tie) is ``lot_depth_mm`` deep, derived per
block and narrowed so the other row keeps the declared minimum depth; the other row takes the
rest, and a rest outside the declared depths is refused.

**Lots, by seeded recursive subdivision.** Each row is split until every piece is at most one and a
half times the block's ``lot_frontage_mm``: a piece longer than that splits at a drawn point
between a third and two thirds of its length. The target is narrowed to 9 to 20 m, so every piece
lies between 4.5 m and 30 m, the frontages the typology catalog's buildings span: a split piece is
at least a third of one and a half targets, and an unsplit piece is at most one and a half targets.

**Frontage.** A lot's primary frontage is its row's street. A lot at either end of a row also
fronts the cross street there, as its second frontage. Each frontage names the curb across the
footway, whose block is the lot's block.

**Addresses.** Along each street, the lots whose primary frontage faces it are numbered from the
street's start: odd on its left, even on its right, in order along the street.

**The threshold** is the middle of the primary frontage, measured from the edge's start vertex.

**Memory precincts.** ``memory_precinct_lots`` lots per district are reserved as memory precincts,
drawn among the lots with one frontage on a local street, so a high street's frontage stays built.
A precinct is a lot like any other: kerb, frontage, threshold and address.

**Setback.** This version builds to the frontage line: ``front_setback_mm`` is read and must be
0, because a parcel record has no field to state any other value.

**Extent.** A lot's extent is its ring's box, grown in plan by the largest projection any facade
parameter declares, so the building standing on it, and everything its faces project beyond its
walls, lie inside it, as a record anchored to its lot must.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from exulanica.grammar.contract import StageContext
from exulanica.grammar.errors import InvalidParameterError, InvalidRecordError
from exulanica.grammar.geometry import Extent, edge_run_length, ring_centroid
from exulanica.grammar.grammars.city import parcels, streets
from exulanica.grammar.grammars.city.descriptor import CITY_SURFACE
from exulanica.grammar.grammars.city.generation.stage import (
    GeneratorStage,
    derived,
    draw,
    entry,
    prior_records,
)

__all__ = ["LOT_TARGET_MM", "PROJECTION_REACH_MM", "STAGE"]

#: The range a block's lot frontage target is narrowed to, so every lot is 4.5 to 30 m wide.
LOT_TARGET_MM: Final = (9_000, 20_000)
#: The largest projection any facade parameter declares: how far a face may reach past its lot.
PROJECTION_REACH_MM: Final = max(
    spec.maximum
    for spec in CITY_SURFACE.parameters.for_stage("facade")
    if spec.name.endswith("_projection_mm")
)
_DISTRICT: Final = 0


@dataclass(frozen=True, slots=True)
class _Row:
    block: streets.BlockRecord
    street: streets.CurbEdgeRecord
    west: streets.CurbEdgeRecord
    east: streets.CurbEdgeRecord
    south: bool
    low_y: int
    high_y: int


def _split(context: StageContext, low: int, high: int, target: int, ordinal: int) -> list[int]:
    """Cut ``[low, high]`` at drawn points until no piece is over one and a half targets.

    ``ordinal`` names the piece: a row is ``block * 4 + row + 1``, and a piece's two halves are
    ``2 * ordinal`` and ``2 * ordinal + 1``, so no row's cuts depend on another's.
    """
    length = high - low
    if 2 * length <= 3 * target:
        return [low, high]
    cut = low + draw(context, "lot_split", ordinal, (length + 2) // 3, 2 * length // 3)
    return _split(context, low, cut, target, 2 * ordinal)[:-1] + _split(
        context, cut, high, target, 2 * ordinal + 1
    )


def _curbs_of(
    block: streets.BlockRecord, curbs: list[streets.CurbEdgeRecord]
) -> dict[str, streets.CurbEdgeRecord]:
    """A block's four curbs, by the side of the block they face: south, east, north, west."""
    ring = block.boundary_mm
    min_x, max_x = min(x for x, _y in ring), max(x for x, _y in ring)
    min_y, max_y = min(y for _x, y in ring), max(y for _x, y in ring)
    found = {}
    for curb in curbs:
        if curb.block_identity != (block.identity,):
            continue
        (x0, y0, _z0), (x1, y1, _z1) = curb.kerb_line_mm[0], curb.kerb_line_mm[-1]
        if y0 == y1:
            found["south" if y0 < min_y else "north"] = curb
        elif x0 == x1:
            found["west" if x0 < min_x else "east"] = curb
    if set(found) != {"south", "east", "north", "west"} or not (min_x < max_x and min_y < max_y):
        raise InvalidRecordError(f"block {block.identity} is not bounded by four straight curbs")
    return found


def _generate(context: StageContext) -> Iterator[parcels.ParcelRecord]:
    blocks = prior_records(context, streets.STAGE_ID, streets.BlockRecord)
    curbs = prior_records(context, streets.STAGE_ID, streets.CurbEdgeRecord)
    segments = {
        record.identity: record
        for record in prior_records(context, streets.STAGE_ID, streets.StreetSegmentRecord)
    }
    setback = derived(context, "front_setback_mm", _DISTRICT)
    if setback:
        raise InvalidParameterError(
            f"front_setback_mm is {setback}; this parcels stage version builds to the frontage "
            "line, since a parcel record has no field to state a setback"
        )
    precincts = derived(context, "memory_precinct_lots", _DISTRICT)
    depth_spec = CITY_SURFACE.parameters.get("lot_depth_mm")

    lots = []
    for block in blocks:
        faces = _curbs_of(block, curbs)
        ring = block.boundary_mm
        west_x, east_x = min(x for x, _y in ring), max(x for x, _y in ring)
        south_y, north_y = min(y for _x, y in ring), max(y for _x, y in ring)
        south_rank = entry("street-hierarchy", segments[faces["south"].segment_identity].hierarchy)[
            "rank"
        ]
        north_rank = entry("street-hierarchy", segments[faces["north"].segment_identity].hierarchy)[
            "rank"
        ]
        front_south = south_rank <= north_rank
        depth = north_y - south_y
        front_depth = derived(
            context,
            "lot_depth_mm",
            block.block_ordinal,
            maximum=depth - depth_spec.minimum,
        )
        back_depth = depth - front_depth  # type: ignore[operator]
        if not depth_spec.minimum <= back_depth <= depth_spec.maximum:
            raise InvalidParameterError(
                f"block {block.block_ordinal}'s back row is {back_depth} mm deep, outside "
                f"[{depth_spec.minimum}, {depth_spec.maximum}]"
            )
        split_y = south_y + front_depth if front_south else north_y - front_depth  # type: ignore[operator]
        rows = [
            _Row(block, faces["south"], faces["west"], faces["east"], True, south_y, split_y),
            _Row(block, faces["north"], faces["west"], faces["east"], False, split_y, north_y),
        ]
        if not front_south:
            rows.reverse()
        target = derived(
            context,
            "lot_frontage_mm",
            block.block_ordinal,
            minimum=LOT_TARGET_MM[0],
            maximum=LOT_TARGET_MM[1],
        )
        ordinal = 0
        for row_index, row in enumerate(rows):
            row_ordinal = block.block_ordinal * 4 + row_index + 1
            cuts = _split(context, west_x, east_x, target, row_ordinal)  # type: ignore[arg-type]
            for index, (low_x, high_x) in enumerate(pairwise(cuts)):
                ring_lot = (
                    (low_x, row.low_y),
                    (high_x, row.low_y),
                    (high_x, row.high_y),
                    (low_x, row.high_y),
                )
                street_edge = 0 if row.south else 2
                frontages = [(street_edge, row.street)]
                if index == 0:
                    frontages.append((3, row.west))
                if index == len(cuts) - 2:
                    frontages.append((1, row.east))
                lots.append((block, ordinal, ring_lot, frontages))
                ordinal += 1

    # Precincts: lots with one frontage, on a local street.
    candidates = [
        position
        for position, (_block, _ordinal, _ring, frontages) in enumerate(lots)
        if len(frontages) == 1
        and segments[frontages[0][1].segment_identity].hierarchy == "local_street"
    ]
    reserved: set[int] = set()
    for pick_ordinal in range(precincts):  # type: ignore[arg-type]
        left = [position for position in candidates if position not in reserved]
        if not left:
            raise InvalidRecordError(
                "the district has fewer lots for memory precincts than it reserves"
            )
        reserved.add(left[draw(context, "memory_precinct", pick_ordinal, 0, len(left) - 1)])

    # Addresses: along each street, odd on the left and even on the right, in order.
    sides: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for position, (_block, _ordinal, ring_lot, frontages) in enumerate(lots):
        curb = frontages[0][1]
        segment = segments[curb.segment_identity]
        (start_x, start_y, _), (end_x, end_y, _) = (
            segment.centreline_mm[0],
            segment.centreline_mm[-1],
        )
        centre_x, centre_y = ring_centroid(ring_lot)
        # Streets are straight on one axis and run the same way along their length, so the
        # centroid's coordinate on that axis orders lots along the whole street.
        along = centre_x * _sign(end_x - start_x) + centre_y * _sign(end_y - start_y)
        sides.setdefault((segment.street_identity, curb.side), []).append((along, position))
    addresses = {}
    for (_street, side), members in sides.items():
        for rank, (_along, position) in enumerate(sorted(members)):
            addresses[position] = 2 * rank + (1 if side == "left" else 2)

    grade_of = {block.identity: block.grade_elevation_mm for block in blocks}
    for position, (block, ordinal, ring_lot, frontages) in enumerate(lots):
        rows = [
            parcels.Frontage(edge, curb.identity, edge_run_length(ring_lot, edge))
            for edge, curb in frontages
        ]
        grade = grade_of[block.identity]
        xs = [x for x, _y in ring_lot]
        ys = [y for _x, y in ring_lot]
        yield parcels.ParcelRecord(
            identity=context.identity("parcel", block.identity, ordinal),
            block_identity=block.identity,
            parcel_ordinal=ordinal,
            lot_class="memory_precinct" if position in reserved else "building",
            boundary_mm=ring_lot,
            centroid_x_mm=ring_centroid(ring_lot)[0],
            centroid_y_mm=ring_centroid(ring_lot)[1],
            grade_elevation_mm=grade,
            frontages=tuple(rows),
            frontage_mm=sum(row.run_length_mm for row in rows),
            address_number=addresses[position],
            threshold_offset_mm=rows[0].run_length_mm // 2,
            extent=Extent(
                min(xs) - PROJECTION_REACH_MM,
                min(ys) - PROJECTION_REACH_MM,
                grade,
                max(xs) + PROJECTION_REACH_MM,
                max(ys) + PROJECTION_REACH_MM,
                grade,
            ),
        )


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


STAGE: Final = GeneratorStage(parcels.STAGE_ID, parcels.STAGE_VERSION, (parcels.SHAPE,), _generate)
