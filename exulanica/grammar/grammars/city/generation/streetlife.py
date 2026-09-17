"""The streetlife generator: street lamps along every curb that bounds a block.

**What this version places, and what it does not.** Every class the street-furniture catalog places
on the kerb line, and street trees. A class the catalog places at a crossing or a junction is not
generated yet, and a class it places nowhere (a hydrant follows a water main, a signal pole follows
a signal plan) never will be by this stage: the catalog says so and says why.

**Trees.** Along each curb of a block, at ``tree_spacing_mm``, a tree stands in a square pit
``tree_pit_width_mm`` across, its centre ``furniture_kerb_offset_mm`` from the kerb face, narrowed
so the pit lies wholly on the footway and touches neither the kerb nor the frontage. Its trunk is
``tree_trunk_diameter_mm`` across and clear to ``tree_trunk_clear_height_mm``, narrowed so its
crown hangs a capsule's height above the highest ground the crown reaches; its crown is an
ellipsoid ``tree_crown_radius_mm`` by ``tree_crown_height_mm`` on top of it. The species is a
label: the tree-species catalog states a census and a licence, and no size. Lamps are placed
first, and a tree position that would crowd a lamp or a tree already placed carries no tree: the
rhythm skips rather than shifts, so one absence never moves another tree.

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
from exulanica.grammar.grammars.city import parcels, streetlife, streets
from exulanica.grammar.grammars.city.catalogs import form_parts
from exulanica.grammar.grammars.city.common import MILLIONTHS, FormPart
from exulanica.grammar.grammars.city.corners import along, walk_round_face
from exulanica.grammar.grammars.city.generation.stage import (
    GeneratorStage,
    catalog,
    derived,
    entry,
    prior_records,
)
from exulanica.grammar.grammars.city.generation.terrain import DATUM_MM

__all__ = ["STAGE"]

_LAMP: Final = "street_lamp"
#: A pit never touches the kerb or the frontage: this is what it keeps clear of each.
_PIT_MARGIN_MM: Final = 450
#: A trunk is clear to at least this, whatever the ground under its crown.
_CLEAR_LOW_MM: Final = 2_200
#: The walking capsule, as the navigation table states it.
_CAPSULE_HEIGHT_MM: Final = 1_900
#: How far apart one block's furniture classes draw, so each class has its own rhythm and offset.
_CLASS_STRIDE: Final = 100


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


def _even(value: int) -> int:
    """A size whose half is a whole millimetre, so a part's box is symmetric about its centre."""
    return value - value % 2


def _support_top_near(records: list, low_x: int, low_y: int, high_x: int, high_y: int) -> int:
    """The highest drawn ground under a plan box: what a canopy must clear the capsule above."""
    top = None
    for record in records:
        extent = record.extent
        if (
            extent.min_x_mm <= high_x
            and low_x <= extent.max_x_mm
            and extent.min_y_mm <= high_y
            and low_y <= extent.max_y_mm
        ):
            top = extent.max_z_mm if top is None else max(top, extent.max_z_mm)
    return DATUM_MM if top is None else top


def _trees(
    context: StageContext,
    curb: streets.CurbEdgeRecord,
    face: int,
    segment: streets.StreetSegmentRecord,
    grounds: list,
    taken: list[tuple[int, int, int]],
) -> Iterator[streetlife.StreetTreeRecord]:
    """Street trees along one curb, at the block's spacing, wherever one does not crowd its
    neighbours.

    A tree stands in a square pit on the footway, its offset from the kerb face narrowed so the
    pit lies wholly on the footway and touches neither the kerb nor the frontage. Its trunk is
    clear to ``tree_trunk_clear_height_mm``, narrowed so its crown hangs a capsule's height above
    the highest ground the crown reaches, and its crown is an ellipsoid of
    ``tree_crown_radius_mm`` by ``tree_crown_height_mm`` on top of it. Where a position would
    crowd a lamp or a tree already placed, no tree stands there: the rhythm skips rather than
    shifts, so one tree's absence never moves another.
    """
    spacing = derived(context, "tree_spacing_mm", face)
    clearance = derived(context, "exclusion_clearance_mm", face)
    reach = curb.kerb_width_mm + curb.footway_width_mm
    offset = derived(
        context,
        "furniture_kerb_offset_mm",
        face,
        minimum=curb.kerb_width_mm + _PIT_MARGIN_MM,
        maximum=reach - _PIT_MARGIN_MM,
    )
    pit = _even(
        derived(
            context,
            "tree_pit_width_mm",
            face,
            maximum=2 * min(offset - curb.kerb_width_mm, reach - offset),  # type: ignore[operator]
        )
    )
    diameter = _even(derived(context, "tree_trunk_diameter_mm", face))
    radius = derived(context, "tree_crown_radius_mm", face)
    crown = derived(context, "tree_crown_height_mm", face)
    species = derived(context, "tree_species", face)
    walk = walk_round_face(curb)
    start, end = walk[0], walk[-1]
    direction = (end[0] - start[0], end[1] - start[1])
    length = abs(direction[0]) + abs(direction[1])
    unit = _unit(direction)
    inward = (-unit[1], unit[0])
    node = segment.centreline_mm[0]
    heading = _unit(
        (segment.centreline_mm[-1][0] - node[0], segment.centreline_mm[-1][1] - node[1])
    )
    keep = pit // 2 + clearance  # type: ignore[operator]
    ordinal = 0
    position = spacing // 2  # type: ignore[operator]
    while position <= length - spacing // 2:  # type: ignore[operator]
        base = (start[0] + unit[0] * position, start[1] + unit[1] * position)
        shift = along(inward, offset)  # type: ignore[arg-type]
        x, y = base[0] + shift[0], base[1] + shift[1]
        position += spacing  # type: ignore[operator]
        if any(
            (x - other_x) * (x - other_x) + (y - other_y) * (y - other_y)
            < (keep + other_keep) * (keep + other_keep)
            for other_x, other_y, other_keep in taken
        ):
            continue
        line_z = curb.kerb_line_mm[0][2]
        z = (
            line_z
            + curb.kerb_height_mm
            + (offset - curb.kerb_width_mm) * curb.footway_crossfall_millionths // MILLIONTHS  # type: ignore[operator]
        )
        highest = _support_top_near(grounds, x - radius, y - radius, x + radius, y + radius)  # type: ignore[operator]
        clear = derived(
            context,
            "tree_trunk_clear_height_mm",
            face,
            minimum=max(_CLEAR_LOW_MM, highest + _CAPSULE_HEIGHT_MM - z),
        )
        half = pit // 2
        parts = (
            FormPart("prism", "trunk", 0, 0, 0, diameter, diameter, clear, 800_000, 8, 1),  # type: ignore[arg-type]
            FormPart(
                "ellipsoid",
                "canopy",
                0,
                0,
                clear,
                2 * radius,
                2 * radius,
                crown,
                MILLIONTHS,
                16,
                8,  # type: ignore[arg-type]
            ),
        )
        yield streetlife.StreetTreeRecord(
            identity=context.identity("street_tree", curb.identity, ordinal),
            curb_identity=curb.identity,
            segment_identity=curb.segment_identity,
            tree_ordinal=ordinal,
            species=species,  # type: ignore[arg-type]
            along_mm=(base[0] - node[0]) * heading[0] + (base[1] - node[1]) * heading[1],
            kerb_offset_mm=offset,  # type: ignore[arg-type]
            x_mm=x,
            y_mm=y,
            z_mm=z,
            pit_mm=(
                (x - half, y - half),
                (x + half, y - half),
                (x + half, y + half),
                (x - half, y + half),
            ),
            parts=parts,
            exclusion_radius_mm=keep,
            extent=Extent(
                min(x - half, x - radius),  # type: ignore[operator]
                min(y - half, y - radius),  # type: ignore[operator]
                z,
                max(x + half, x + radius),  # type: ignore[operator]
                max(y + half, y + radius),  # type: ignore[operator]
                z + clear + crown,  # type: ignore[operator]
            ),
        )
        taken.append((x, y, keep))
        ordinal += 1


def _generate(context: StageContext) -> Iterator[object]:
    curbs = prior_records(context, streets.STAGE_ID, streets.CurbEdgeRecord)
    blocks = {
        record.identity: record
        for record in prior_records(context, streets.STAGE_ID, streets.BlockRecord)
    }
    segments = {
        record.identity: record
        for record in prior_records(context, streets.STAGE_ID, streets.StreetSegmentRecord)
    }
    grounds = [
        *blocks.values(),
        *prior_records(context, parcels.STAGE_ID, parcels.ParcelRecord),
        *curbs,
    ]
    classes = [
        item.key
        for item in catalog("street-furniture").entries
        if entry("street-furniture", item.key)["placement"] == "kerb_line"
    ]
    for curb in curbs:
        if not curb.block_identity:
            continue
        face = blocks[curb.block_identity[0]].block_ordinal
        segment = segments[curb.segment_identity]
        taken: list[tuple[int, int, int]] = []
        ordinal = 0
        for index, key in enumerate(classes):
            for record in _furniture(context, curb, face, segment, key, index, taken, ordinal):
                ordinal += 1
                yield record
        yield from _trees(context, curb, face, segment, grounds, taken)


def _furniture(
    context: StageContext,
    curb: streets.CurbEdgeRecord,
    face: int,
    segment: streets.StreetSegmentRecord,
    key: str,
    index: int,
    taken: list[tuple[int, int, int]],
    first_ordinal: int,
) -> Iterator[streetlife.StreetFurnitureRecord]:
    """One class of street furniture along one curb, at that class's own spacing.

    A class the catalog places on the kerb line stands every ``furniture_spacing_mm``, narrowed to
    the class's own band; the lamp keeps ``lamp_spacing_mm``, the one furniture spacing the target
    architecture named. Each item stands ``furniture_kerb_offset_mm`` back from the kerb face,
    narrowed to the class's offsets, facing the carriageway. Where a class pairs with another, the
    paired item stands beside it, just clear of both their exclusions. A position that would crowd
    anything already placed on this curb carries nothing: the rhythm skips rather than shifts.
    """
    values = entry("street-furniture", key)
    parts = form_parts(values["parts"])
    draw = face * _CLASS_STRIDE + index
    if key == _LAMP:
        spacing = derived(
            context,
            "lamp_spacing_mm",
            face,
            minimum=values["spacing_minimum_mm"],
            maximum=values["spacing_maximum_mm"],
        )
    else:
        spacing = derived(
            context,
            "furniture_spacing_mm",
            draw,
            minimum=values["spacing_minimum_mm"],
            maximum=values["spacing_maximum_mm"],
        )
    offset = derived(
        context,
        "furniture_kerb_offset_mm",
        draw,
        minimum=values["kerb_offset_minimum_mm"],
        maximum=values["kerb_offset_maximum_mm"],
    )
    clearance = derived(context, "exclusion_clearance_mm", face)
    radius = values["exclusion_radius_mm"] + clearance  # type: ignore[operator]
    partner = values["pairs_with"]
    pair = entry("street-furniture", partner) if partner != "none" else None
    walk = walk_round_face(curb)
    start, end = walk[0], walk[-1]
    direction = (end[0] - start[0], end[1] - start[1])
    length = abs(direction[0]) + abs(direction[1])
    unit = _unit(direction)
    inward = (-unit[1], unit[0])
    facing = (-inward[0], -inward[1])
    node = segment.centreline_mm[0]
    heading = _unit(
        (segment.centreline_mm[-1][0] - node[0], segment.centreline_mm[-1][1] - node[1])
    )
    line_z = curb.kerb_line_mm[0][2]
    ordinal = first_ordinal
    position = spacing // 2  # type: ignore[operator]
    while position <= length - spacing // 2:  # type: ignore[operator]
        here = position
        position += spacing  # type: ignore[operator]
        stand = [(key, values, parts, radius, here)]
        if pair is not None:
            pair_radius = pair["exclusion_radius_mm"] + clearance  # type: ignore[operator]
            stand.append(
                (
                    partner,
                    pair,
                    form_parts(pair["parts"]),
                    pair_radius,
                    here + radius + pair_radius,  # type: ignore[operator]
                )
            )
        for name, fields, item_parts, item_radius, at in stand:
            if at > length:
                continue
            item_offset = min(
                max(offset, fields["kerb_offset_minimum_mm"]), fields["kerb_offset_maximum_mm"]
            )
            base = (start[0] + unit[0] * at, start[1] + unit[1] * at)
            shift = along(inward, item_offset)  # type: ignore[arg-type]
            x, y = base[0] + shift[0], base[1] + shift[1]
            if any(
                (x - other_x) * (x - other_x) + (y - other_y) * (y - other_y)
                < (item_radius + other_radius) * (item_radius + other_radius)
                for other_x, other_y, other_radius in taken
            ):
                continue
            z = (
                line_z
                + curb.kerb_height_mm
                + (item_offset - curb.kerb_width_mm)
                * curb.footway_crossfall_millionths
                // MILLIONTHS
            )
            taken.append((x, y, item_radius))
            yield streetlife.StreetFurnitureRecord(
                identity=context.identity("street_furniture", curb.identity, ordinal),
                curb_identity=curb.identity,
                segment_identity=curb.segment_identity,
                item_ordinal=ordinal,
                furniture_class=name,
                along_mm=(base[0] - node[0]) * heading[0] + (base[1] - node[1]) * heading[1],
                kerb_offset_mm=item_offset,
                x_mm=x,
                y_mm=y,
                z_mm=z,
                facing_dx_mm=facing[0],
                facing_dy_mm=facing[1],
                parts=item_parts,
                exclusion_radius_mm=item_radius,
                extent=_extent(x, y, z, facing, item_parts),
            )
            ordinal += 1


STAGE: Final = GeneratorStage(
    streetlife.STAGE_ID,
    streetlife.STAGE_VERSION,
    (streetlife.FURNITURE_SHAPE, streetlife.TREE_SHAPE),
    _generate,
)
