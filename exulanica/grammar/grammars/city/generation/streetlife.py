"""The streetlife generator: street lamps along every curb that bounds a block.

**What this version places, and what it does not.** Lamps only. ``lamp_spacing_mm`` is the one
spacing the descriptor declares for furniture; a bench, a bin, a bollard or a hydrant has no
declared spacing or rule of where it stands, so none is generated rather than placed by a number
nobody declared. Street trees are not generated either: a tree record states its trunk and canopy
as explicit parts and its pit as a ring, and neither the tree-species catalog nor any declared
parameter states a size for any of them, so ``tree_species`` and ``tree_spacing_mm`` are not read.

**Where a lamp stands.** Along each curb of a block, lamps stand ``lamp_spacing_mm`` apart on the
curb's straight kerb line, the first half a spacing in from its start, as many as fit before half
a spacing from its end. Each stands ``furniture_kerb_offset_mm`` back from the kerb face, narrowed
to the lamp class's own offsets, on the footway at the height its crossfall gives there, facing the
carriageway so its arm reaches over the road. A lamp stands at the kerb, clear of the doors at the
frontage behind it. A curb and its face share one spacing and offset.

**Exclusion.** A lamp keeps its class's exclusion radius plus ``exclusion_clearance_mm`` clear.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

from exulanica.grammar.contract import StageContext
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city import streetlife, streets
from exulanica.grammar.grammars.city.catalogs import form_parts
from exulanica.grammar.grammars.city.common import MILLIONTHS, FormPart
from exulanica.grammar.grammars.city.corners import along, walk_round_face
from exulanica.grammar.grammars.city.generation.stage import (
    GeneratorStage,
    derived,
    entry,
    prior_records,
)

__all__ = ["STAGE"]

_LAMP: Final = "street_lamp"


def _turned(facing: tuple[int, int], local_x: int, local_y: int) -> tuple[int, int]:
    """A local offset turned by an axis-aligned unit direction."""
    dx, dy = facing
    return dx * local_x - dy * local_y, dy * local_x + dx * local_y


def _extent(x: int, y: int, z: int, facing: tuple[int, int], parts: tuple[FormPart, ...]) -> Extent:
    corners = []
    for part in parts:
        half_x, half_y = (part.size_x_mm + 1) // 2, (part.size_y_mm + 1) // 2
        for sx in (-half_x, half_x):
            for sy in (-half_y, half_y):
                wx, wy = _turned(facing, part.offset_x_mm + sx, part.offset_y_mm + sy)
                corners.append((x + wx, y + wy, z + part.offset_z_mm))
                corners.append((x + wx, y + wy, z + part.offset_z_mm + part.size_z_mm))
    return Extent(
        min(point[0] for point in corners),
        min(point[1] for point in corners),
        min(point[2] for point in corners),
        max(point[0] for point in corners),
        max(point[1] for point in corners),
        max(point[2] for point in corners),
    )


def _unit(vector: tuple[int, int]) -> tuple[int, int]:
    return (vector[0] > 0) - (vector[0] < 0), (vector[1] > 0) - (vector[1] < 0)


def _generate(context: StageContext) -> Iterator[streetlife.StreetFurnitureRecord]:
    curbs = prior_records(context, streets.STAGE_ID, streets.CurbEdgeRecord)
    blocks = {
        record.identity: record
        for record in prior_records(context, streets.STAGE_ID, streets.BlockRecord)
    }
    segments = {
        record.identity: record
        for record in prior_records(context, streets.STAGE_ID, streets.StreetSegmentRecord)
    }
    lamp = entry("street-furniture", _LAMP)
    parts = form_parts(lamp["parts"])
    for curb in curbs:
        if not curb.block_identity:
            continue
        block = blocks[curb.block_identity[0]]
        face = block.block_ordinal
        spacing = derived(context, "lamp_spacing_mm", face)
        offset = derived(
            context,
            "furniture_kerb_offset_mm",
            face,
            minimum=lamp["kerb_offset_minimum_mm"],
            maximum=lamp["kerb_offset_maximum_mm"],
        )
        clearance = derived(context, "exclusion_clearance_mm", face)
        radius = lamp["exclusion_radius_mm"] + clearance  # type: ignore[operator]
        walk = walk_round_face(curb)
        start, end = walk[0], walk[-1]
        direction = (end[0] - start[0], end[1] - start[1])
        length = abs(direction[0]) + abs(direction[1])
        unit = _unit(direction)
        inward = (-unit[1], unit[0])
        ordinal = 0
        position = spacing // 2  # type: ignore[operator]
        while position <= length - spacing // 2:  # type: ignore[operator]
            base = (start[0] + unit[0] * position, start[1] + unit[1] * position)
            shift = along(inward, offset)  # type: ignore[arg-type]
            x, y = base[0] + shift[0], base[1] + shift[1]
            line_z = curb.kerb_line_mm[0][2]
            z = (
                line_z
                + curb.kerb_height_mm
                + (offset - curb.kerb_width_mm) * curb.footway_crossfall_millionths // MILLIONTHS  # type: ignore[operator]
            )
            facing = (-inward[0], -inward[1])
            segment = segments[curb.segment_identity]
            node = segment.centreline_mm[0]
            heading = _unit(
                (segment.centreline_mm[-1][0] - node[0], segment.centreline_mm[-1][1] - node[1])
            )
            segment_along = (base[0] - node[0]) * heading[0] + (base[1] - node[1]) * heading[1]
            yield streetlife.StreetFurnitureRecord(
                identity=context.identity("street_furniture", curb.identity, ordinal),
                curb_identity=curb.identity,
                segment_identity=curb.segment_identity,
                item_ordinal=ordinal,
                furniture_class=_LAMP,
                along_mm=segment_along,
                kerb_offset_mm=offset,  # type: ignore[arg-type]
                x_mm=x,
                y_mm=y,
                z_mm=z,
                facing_dx_mm=facing[0],
                facing_dy_mm=facing[1],
                parts=parts,
                exclusion_radius_mm=radius,
                extent=_extent(x, y, z, facing, parts),
            )
            ordinal += 1
            position += spacing  # type: ignore[operator]


STAGE: Final = GeneratorStage(
    streetlife.STAGE_ID,
    streetlife.STAGE_VERSION,
    (streetlife.FURNITURE_SHAPE, streetlife.TREE_SHAPE),
    _generate,
)
