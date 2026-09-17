"""The vitrine generator: a lit display behind every shopfront's glazing.

**Which bays.** Every shopfront bay of a building's shop units gets one vitrine, exactly as wide as
the bay and as tall as its glazing panel, standing on the stall riser, so it lies wholly behind
glazing. A shop's door bay has none: its glazing is the transom above the door.

**One fitout per building.** ``fitout``, ``vitrine_depth_mm`` and ``vitrine_light_level_millionths``
are derived with the building as the subject, so a building's shops dress alike, and the premises
stage then gives them a use the fitout serves. The fitout is derived among those that serve some
use the building's typology admits on its ground floor and whose unit fits the building's
narrowest shopfront and its glazing's height; the depth is narrowed to hold the unit's parts.

**The fitout's parts.** As many whole units as the vitrine's width holds, side by side, the row
centred along the run; every part is the catalog's, moved along the run only.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import Final

from exulanica.grammar.contract import StageContext
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city import facade, massing, parcels, streets, vitrine
from exulanica.grammar.grammars.city.catalogs import form_parts
from exulanica.grammar.grammars.city.common import FormPart
from exulanica.grammar.grammars.city.generation.facade import building_shop_units
from exulanica.grammar.grammars.city.generation.stage import (
    GeneratorStage,
    catalog,
    derived,
    entry,
    prior_records,
)

__all__ = ["STAGE", "unit_width_mm"]

_LOTS_PER_BLOCK: Final = 10_000


def unit_width_mm(parts: tuple[FormPart, ...]) -> int:
    """How much run one fitout unit takes: its parts' reach along x from the unit's start."""
    return max(part.offset_x_mm + (part.size_x_mm + 1) // 2 for part in parts)


def _unit_depth_mm(parts: tuple[FormPart, ...]) -> int:
    return max(part.offset_y_mm + (part.size_y_mm + 1) // 2 for part in parts)


def _unit_height_mm(parts: tuple[FormPart, ...]) -> int:
    return max(part.offset_z_mm + part.size_z_mm for part in parts)


def _face_frame(
    building: massing.MassingRecord, face: facade.FacadeRecord
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    """A face's two ends in plan and the unit direction into the building."""
    ring = building.tiers[face.tier_ordinal].ring_mm
    first, last = ring[face.edge_ordinal], ring[(face.edge_ordinal + 1) % len(ring)]
    dx, dy = last[0] - first[0], last[1] - first[1]
    return first, last, (-((dy > 0) - (dy < 0)), (dx > 0) - (dx < 0))


def _reach_mm(building: massing.MassingRecord, face: facade.FacadeRecord) -> int:
    """How deep the building is behind this face: its ring's furthest point inward."""
    first, _last, inward = _face_frame(building, face)
    ring = building.tiers[face.tier_ordinal].ring_mm
    return max((x - first[0]) * inward[0] + (y - first[1]) * inward[1] for x, y in ring)


def _opening_band_mm(
    building: massing.MassingRecord, face: facade.FacadeRecord
) -> tuple[int, int] | None:
    """The band above the building's base this face's openings cover, or None when it has none."""
    if not face.openings:
        return None
    sills, heads = [], []
    for grid in face.openings:
        for storey in grid.storeys:
            floor = (
                building.ground_storey_height_mm + (storey - 1) * building.upper_storey_height_mm
            )
            sill = floor + grid.sill_height_mm
            sills.append(sill)
            heads.append(sill + grid.height_mm + grid.head_rise_mm)
    return min(sills), max(heads) - min(sills)


def _backings(
    context: StageContext,
    building: massing.MassingRecord,
    faces: list[facade.FacadeRecord],
    ordinal: int,
) -> Iterator[vitrine.InteriorBackingRecord]:
    """One plane behind each face that has openings, at one depth for the whole building."""
    glazed = [face for face in faces if _opening_band_mm(building, face) is not None]
    if not glazed:
        return
    room = min(_reach_mm(building, face) for face in glazed)
    reveal = max(grid.reveal_depth_mm for face in glazed for grid in face.openings)
    low = max(vitrine.BACKING_DEPTH_MINIMUM_MM, reveal + 1)
    high = min(vitrine.BACKING_DEPTH_MAXIMUM_MM, room - 1)
    if high < low:
        raise InvalidRecordError(
            f"building {building.identity} is {room} mm deep behind its glazed faces, which "
            f"holds no backing between {low} and {vitrine.BACKING_DEPTH_MAXIMUM_MM} mm"
        )
    depth = derived(context, "interior_backing_depth_mm", ordinal, minimum=low, maximum=high)
    light = derived(context, "interior_backing_light_level_millionths", ordinal)
    base = building.base_elevation_mm
    for face in glazed:
        sill, height = _opening_band_mm(building, face)  # type: ignore[misc]
        first, last, inward = _face_frame(building, face)
        xs = [first[0], last[0], first[0] + inward[0] * depth, last[0] + inward[0] * depth]  # type: ignore[operator]
        ys = [first[1], last[1], first[1] + inward[1] * depth, last[1] + inward[1] * depth]  # type: ignore[operator]
        yield vitrine.InteriorBackingRecord(
            identity=context.identity("interior_backing", face.identity, 0),
            facade_identity=face.identity,
            building_identity=building.identity,
            u_start_mm=0,
            width_mm=face.run_length_mm,
            sill_mm=sill,
            height_mm=height,
            depth_mm=depth,  # type: ignore[arg-type]
            light_level_millionths=light,  # type: ignore[arg-type]
            extent=Extent(min(xs), min(ys), base + sill, max(xs), max(ys), base + sill + height),
        )


def _generate(context: StageContext) -> Iterator[object]:
    buildings = prior_records(context, massing.STAGE_ID, massing.MassingRecord)
    lots = {
        record.identity: record
        for record in prior_records(context, parcels.STAGE_ID, parcels.ParcelRecord)
    }
    block_ordinals = {
        record.identity: record.block_ordinal
        for record in prior_records(context, streets.STAGE_ID, streets.BlockRecord)
    }
    faces = prior_records(context, facade.STAGE_ID, facade.FacadeRecord)
    bays = prior_records(context, facade.STAGE_ID, facade.GroundBayRecord)
    faces_of: dict[str, list[facade.FacadeRecord]] = {}
    for face in faces:
        faces_of.setdefault(face.building_identity, []).append(face)
    face_by_identity = {face.identity: face for face in faces}
    bays_of: dict[str, list[facade.GroundBayRecord]] = {}
    for bay in bays:
        bays_of.setdefault(face_by_identity[bay.facade_identity].building_identity, []).append(bay)

    for building in buildings:
        lot = lots[building.parcel_identity]
        ordinal_of = block_ordinals[lot.block_identity] * _LOTS_PER_BLOCK + lot.parcel_ordinal
        yield from _backings(context, building, faces_of.get(building.identity, []), ordinal_of)
        units = building_shop_units(
            lot, faces_of.get(building.identity, []), bays_of.get(building.identity, [])
        )
        shopfronts = [bay for unit in units for bay in unit if bay.bay_kind == "shopfront"]
        if not shopfronts:
            continue
        ordinal = block_ordinals[lot.block_identity] * _LOTS_PER_BLOCK + lot.parcel_ordinal
        glazing = [panel for bay in shopfronts for panel in bay.panels if panel.role == "glazing"]
        height = min(panel.z_top_mm - panel.z_bottom_mm for panel in glazing)
        narrowest = min(bay.width_mm for bay in shopfronts)
        uses = set(entry("typology", building.typology)["ground_floor_uses"])
        options = []
        for item in catalog("fitout").entries:
            fields = entry("fitout", item.key)
            parts = form_parts(fields["parts"])
            if (
                uses & set(fields["use_classes"])
                and unit_width_mm(parts) <= narrowest
                and _unit_height_mm(parts) <= height
            ):
                options.append(item.key)
        if not options:
            raise InvalidRecordError(f"no fitout fits building {building.identity}'s shopfronts")
        fitout = derived(context, "fitout", ordinal, options=sorted(options))
        unit = form_parts(entry("fitout", fitout)["parts"])  # type: ignore[arg-type]
        depth = derived(context, "vitrine_depth_mm", ordinal, minimum=_unit_depth_mm(unit))
        light = derived(context, "vitrine_light_level_millionths", ordinal)
        pitch = unit_width_mm(unit)
        for bay in shopfronts:
            face = face_by_identity[bay.facade_identity]
            [panel] = [item for item in bay.panels if item.role == "glazing"]
            count = bay.width_mm // pitch
            start = (bay.width_mm - count * pitch) // 2
            parts = tuple(
                dataclasses.replace(part, offset_x_mm=part.offset_x_mm + start + index * pitch)
                for index in range(count)
                for part in unit
            )
            ring = building.tiers[face.tier_ordinal].ring_mm
            first, last = ring[face.edge_ordinal], ring[(face.edge_ordinal + 1) % len(ring)]
            run = face.run_length_mm
            u0, u1 = bay.u_start_mm, bay.u_start_mm + bay.width_mm
            a = (
                first[0] + (last[0] - first[0]) * u0 // run,
                first[1] + (last[1] - first[1]) * u0 // run,
            )
            b = (
                first[0] + (last[0] - first[0]) * u1 // run,
                first[1] + (last[1] - first[1]) * u1 // run,
            )
            dx, dy = last[0] - first[0], last[1] - first[1]
            inward = (-((dy > 0) - (dy < 0)), (dx > 0) - (dx < 0))
            xs = [a[0], b[0], a[0] + inward[0] * depth]  # type: ignore[operator]
            ys = [a[1], b[1], a[1] + inward[1] * depth]  # type: ignore[operator]
            base = building.base_elevation_mm
            yield vitrine.VitrineRecord(
                identity=context.identity("vitrine", bay.identity, 0),
                bay_identity=bay.identity,
                facade_identity=face.identity,
                building_identity=building.identity,
                u_start_mm=u0,
                width_mm=bay.width_mm,
                sill_mm=panel.z_bottom_mm,
                height_mm=panel.z_top_mm - panel.z_bottom_mm,
                depth_mm=depth,  # type: ignore[arg-type]
                fitout=fitout,  # type: ignore[arg-type]
                light_level_millionths=light,  # type: ignore[arg-type]
                parts=parts,
                extent=Extent(
                    min(xs),
                    min(ys),
                    base + panel.z_bottom_mm,
                    max(xs),
                    max(ys),
                    base + panel.z_top_mm,
                ),
            )


STAGE: Final = GeneratorStage(
    vitrine.STAGE_ID,
    vitrine.STAGE_VERSION,
    (vitrine.SHAPE, vitrine.BACKING_SHAPE),
    _generate,
)
