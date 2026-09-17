"""The massing generator: one terraced building on every building lot, and what stands on its roof.

**One draw decides a building's character.** A building's era is derived first, among the eras of
the typologies its lot can take; its typology is then derived among those typologies of that era.
Storey height, roof family and cornice (in the facade stage) all follow from that one era and
typology, which is the correlated variety the target architecture asks for:

* a typology fits a lot when it is terraced (this version builds to every lot line, and a
  detached building needs side yards no lot record states), its frontage range holds the lot's
  primary frontage, and, on a high street, its ground floor admits a use other than a dwelling;
* storeys are derived within the typology's range; the ground storey within the declared range;
  an upper storey within the era's range;
* the roof family is derived among those both the typology and the era admit, and its form, rise
  range and parapet rule come from the roof-family catalog. A required parapet is derived from 1 mm
  up to the declared maximum; a gable's ridge runs parallel to the street, between the midpoints of
  the lot's side edges, so its gables stand on the party walls.

**Setbacks.** Only a building of an era with no cornice steps back: ``setback_top_storeys`` top
storeys, derived up to one fewer than its storeys, stand ``setback_depth_mm`` back from its
primary frontage, derived up to what leaves the lower tier's roof a terrace. Either derived as 0
means no setback.

**Light wells.** This version cuts none: ``light_well_count`` is derived within ``[0, 0]``, since a
well needs a rule for where it may stand that this version does not have.

**Rooftop objects.** On a flat top tier, ``rooftop_plant_count`` plant units and then
``rooftop_tank_count`` tanks are placed in a row along the tier's middle, west to east, each
keeping its class's clearance from every tier edge and from its neighbours. Each count is derived
up to how many fit. A record's ``clearance_mm`` is the clearance the placement actually keeps.

**Base and extent.** A building stands at its lot's grade. Its extent is its lot's, in plan (the
lot's ring grown by the largest facade projection), and in height from its base to the highest of
its roof, its parapet and its rooftop objects.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator, Sequence
from typing import Final

from exulanica.grammar.contract import StageContext
from exulanica.grammar.errors import InvalidParameterError, InvalidRecordError
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city import massing, parcels, streets
from exulanica.grammar.grammars.city.catalogs import form_parts
from exulanica.grammar.grammars.city.common import FormPart
from exulanica.grammar.grammars.city.generation.stage import (
    GeneratorStage,
    catalog,
    derived,
    entry,
    prior_records,
)

__all__ = ["STAGE", "parts_extent"]

_EAST: Final = (1, 0)
#: A block holds fewer lots than this, so a lot's draw ordinal is its block's times this
#: plus its own.
_LOTS_PER_BLOCK: Final = 10_000
#: The one district this version lays out, as the districts stage numbers it.
_DISTRICT: Final = 0


def parts_extent(x: int, y: int, z: int, parts: Sequence[FormPart]) -> Extent:
    """The box of parts facing +x at ``(x, y, z)``, each size halved upward about its offset."""
    corners = []
    for part in parts:
        half_x, half_y = (part.size_x_mm + 1) // 2, (part.size_y_mm + 1) // 2
        corners += [
            (x + part.offset_x_mm - half_x, y + part.offset_y_mm - half_y, z + part.offset_z_mm),
            (
                x + part.offset_x_mm + half_x,
                y + part.offset_y_mm + half_y,
                z + part.offset_z_mm + part.size_z_mm,
            ),
        ]
    return Extent(
        min(point[0] for point in corners),
        min(point[1] for point in corners),
        min(point[2] for point in corners),
        max(point[0] for point in corners),
        max(point[1] for point in corners),
        max(point[2] for point in corners),
    )


def _typologies(frontage: int, high_street: bool) -> list[str]:
    fitting = []
    for item in catalog("typology").entries:
        fields = entry("typology", item.key)
        if fields["attachment"] != "terraced":
            continue
        if not fields["frontage_minimum_mm"] <= frontage <= fields["frontage_maximum_mm"]:
            continue
        if high_street and set(fields["ground_floor_uses"]) <= {"residential"}:
            continue
        fitting.append(item.key)
    return sorted(fitting)


def _place_row(
    ring: tuple[tuple[int, int], ...], classes: Sequence[str]
) -> tuple[list[tuple[str, int, int, int]], int]:
    """Place objects of ``classes`` west to east along the ring's middle line, as many as fit.

    Returns the placements ``(class, x, y, clearance kept)`` and how many of ``classes`` fit.
    """
    min_x, max_x = min(x for x, _y in ring), max(x for x, _y in ring)
    min_y, max_y = min(y for _x, y in ring), max(y for _x, y in ring)
    middle_y = (min_y + max_y) // 2
    cursor = min_x
    placed = []
    for key in classes:
        parts = form_parts(entry("rooftop-object", key)["parts"])
        clearance = entry("rooftop-object", key)["clearance_minimum_mm"]
        box = parts_extent(0, 0, 0, parts)
        x = cursor + clearance - box.min_x_mm
        if x + box.max_x_mm + clearance > max_x:
            break
        if (
            middle_y + box.min_y_mm - clearance < min_y
            or middle_y + box.max_y_mm + clearance > max_y
        ):
            break
        kept = min(
            x + box.min_x_mm - min_x,
            max_x - (x + box.max_x_mm),
            middle_y + box.min_y_mm - min_y,
            max_y - (middle_y + box.max_y_mm),
        )
        placed.append((key, x, middle_y, kept))
        cursor = x + box.max_x_mm
    return placed, len(placed)


def _on_high_street(lot: parcels.ParcelRecord, curbs: dict, segments: dict) -> bool:
    return (
        segments[curbs[lot.frontages[0].curb_identity].segment_identity].hierarchy == "high_street"
    )


def _storey_reach(typologies: Sequence[str]) -> tuple[int, int]:
    """The fewest and the most storeys any of these typologies can stand: what a band must meet."""
    return (
        min(entry("typology", key)["storeys_minimum"] for key in typologies),
        max(entry("typology", key)["storeys_maximum"] for key in typologies),
    )


def _generate(context: StageContext) -> Iterator[object]:
    lots = prior_records(context, parcels.STAGE_ID, parcels.ParcelRecord)
    curbs = {
        record.identity: record
        for record in prior_records(context, streets.STAGE_ID, streets.CurbEdgeRecord)
    }
    segments = {
        record.identity: record
        for record in prior_records(context, streets.STAGE_ID, streets.StreetSegmentRecord)
    }
    block_ordinals = {
        record.identity: record.block_ordinal
        for record in prior_records(context, streets.STAGE_ID, streets.BlockRecord)
    }
    # The street wall is the district's decision, not each building's: every building's storeys lie
    # in this band as well as in its typology's range, and a typology whose range misses the band is
    # not admitted rather than clamped into it. The band is narrowed to what this district's lots
    # can actually build, so it never asks for a street no lot of it could stand in.
    reach = [
        _storey_reach(
            _typologies(lot.frontages[0].run_length_mm, _on_high_street(lot, curbs, segments))
        )
        for lot in lots
        if lot.lot_class == "building"
    ]
    band_low = derived(
        context, "storey_band_low", _DISTRICT, maximum=min(high for _low, high in reach)
    )
    band_high = derived(
        context,
        "storey_band_high",
        _DISTRICT,
        minimum=max(band_low, max(low for low, _high in reach)),  # type: ignore[arg-type]
    )
    for lot in lots:
        if lot.lot_class != "building":
            continue
        # A building's draws are its lot's: stable whatever other lots hold.
        ordinal = block_ordinals[lot.block_identity] * _LOTS_PER_BLOCK + lot.parcel_ordinal
        primary = lot.frontages[0]
        typologies = [
            key
            for key in _typologies(primary.run_length_mm, _on_high_street(lot, curbs, segments))
            if entry("typology", key)["storeys_minimum"] <= band_high
            and entry("typology", key)["storeys_maximum"] >= band_low
        ]
        if not typologies:
            raise InvalidParameterError(
                f"no typology on a {primary.run_length_mm} mm frontage has storeys inside the "
                f"district's band of {band_low} to {band_high}"
            )
        if not typologies:
            raise InvalidRecordError(
                f"no terraced typology fits lot {lot.identity}'s "
                f"{primary.run_length_mm} mm frontage"
            )
        eras = sorted({era for key in typologies for era in entry("typology", key)["eras"]})
        era = derived(context, "era", ordinal, options=eras)
        typology = derived(
            context,
            "typology",
            ordinal,
            options=[key for key in typologies if era in entry("typology", key)["eras"]],
        )
        kind = entry("typology", typology)  # type: ignore[arg-type]
        period = entry("era", era)  # type: ignore[arg-type]
        storeys = derived(
            context,
            "storeys",
            ordinal,
            minimum=max(kind["storeys_minimum"], band_low),  # type: ignore[arg-type]
            maximum=min(kind["storeys_maximum"], band_high),  # type: ignore[arg-type]
        )
        ground = derived(context, "ground_storey_height_mm", ordinal)
        upper = derived(
            context,
            "upper_storey_height_mm",
            ordinal,
            minimum=period["upper_storey_minimum_mm"],
            maximum=period["upper_storey_maximum_mm"],
        )
        family = derived(
            context,
            "roof_family",
            ordinal,
            options=[key for key in kind["roof_families"] if key in period["roof_families"]],
        )
        roof = entry("roof-family", family)  # type: ignore[arg-type]
        rise = derived(
            context,
            "roof_rise_mm",
            ordinal,
            minimum=roof["rise_minimum_mm"],
            maximum=roof["rise_maximum_mm"],
        )
        parapet = derived(
            context,
            "parapet_height_mm",
            ordinal,
            minimum=1 if roof["parapet"] == "required" else 0,
            maximum=None if roof["parapet"] == "required" else 0,
        )
        ring = lot.boundary_mm
        min_x, max_x = min(x for x, _y in ring), max(x for x, _y in ring)
        min_y, max_y = min(y for _x, y in ring), max(y for _x, y in ring)
        can_step = period["cornice"] == "none" and storeys > 1  # type: ignore[operator]
        setback_storeys = derived(
            context,
            "setback_top_storeys",
            ordinal,
            maximum=storeys - 1 if can_step else 0,  # type: ignore[operator]
        )
        setback_depth = derived(
            context,
            "setback_depth_mm",
            ordinal,
            maximum=(max_y - min_y) // 2 if can_step else 0,
        )
        derived(context, "light_well_count", ordinal, maximum=0)
        base = lot.grade_elevation_mm
        tiers = []
        if setback_storeys and setback_depth:
            first_top = storeys - setback_storeys - 1  # type: ignore[operator]
            upper_ring = (
                (
                    (min_x, min_y + setback_depth),
                    (max_x, min_y + setback_depth),
                    (max_x, max_y),
                    (min_x, max_y),
                )
                if primary.edge_ordinal == 0
                else (
                    (min_x, min_y),
                    (max_x, min_y),
                    (max_x, max_y - setback_depth),
                    (min_x, max_y - setback_depth),
                )  # type: ignore[operator]
            )
            tiers = [
                massing.Tier(0, first_top, ring, (), parapet),  # type: ignore[arg-type]
                massing.Tier(first_top + 1, storeys - 1, upper_ring, (), parapet),  # type: ignore[arg-type,operator]
            ]
        else:
            tiers = [massing.Tier(0, storeys - 1, ring, (), parapet)]  # type: ignore[arg-type,operator]
        top = tiers[-1]
        ridge: tuple[tuple[int, int], ...] = ()
        if roof["form"] == "ridge":
            top_ring = top.ring_mm
            ridge = (
                ((top_ring[1][0] + top_ring[2][0]) // 2, (top_ring[1][1] + top_ring[2][1]) // 2),
                ((top_ring[3][0] + top_ring[0][0]) // 2, (top_ring[3][1] + top_ring[0][1]) // 2),
            )
        identity = context.identity("building", lot.identity, 0)
        draft = massing.MassingRecord(
            identity=identity,
            parcel_identity=lot.identity,
            building_ordinal=0,
            base_elevation_mm=base,
            typology=typology,  # type: ignore[arg-type]
            era=era,  # type: ignore[arg-type]
            storeys=storeys,  # type: ignore[arg-type]
            ground_storey_height_mm=ground,  # type: ignore[arg-type]
            upper_storey_height_mm=upper,  # type: ignore[arg-type]
            tiers=tuple(tiers),
            roof_family=family,  # type: ignore[arg-type]
            roof_form=roof["form"],
            ridge_mm=ridge,
            roof_rise_mm=rise,  # type: ignore[arg-type]
            extent=lot.extent,
        )
        wall_top = massing.tier_top_mm(draft, top)
        objects = []
        if roof["form"] == "flat" and roof["rooftop_objects"] == "allowed":
            _placed, plant_fit = _place_row(top.ring_mm, ["hvac_unit"] * 8)
            plant = derived(context, "rooftop_plant_count", ordinal, maximum=plant_fit)
            _placed, tank_fit = _place_row(top.ring_mm, ["hvac_unit"] * plant + ["water_tank"] * 4)  # type: ignore[operator]
            tanks = derived(
                context,
                "rooftop_tank_count",
                ordinal,
                maximum=tank_fit - plant,  # type: ignore[operator]
            )
            placements, _count = _place_row(
                top.ring_mm, ["hvac_unit"] * plant + ["water_tank"] * tanks
            )  # type: ignore[operator]
            for index, (key, x, y, kept) in enumerate(placements):
                parts = form_parts(entry("rooftop-object", key)["parts"])
                objects.append(
                    massing.RooftopObjectRecord(
                        identity=context.identity("rooftop_object", identity, index),
                        building_identity=identity,
                        object_ordinal=index,
                        object_class=key,
                        x_mm=x,
                        y_mm=y,
                        z_mm=wall_top,
                        facing_dx_mm=_EAST[0],
                        facing_dy_mm=_EAST[1],
                        parts=parts,
                        clearance_mm=kept,
                        extent=parts_extent(x, y, wall_top, parts),
                    )
                )
        else:
            derived(context, "rooftop_plant_count", ordinal, maximum=0)
            derived(context, "rooftop_tank_count", ordinal, maximum=0)
        heights = [rise, parapet, *(item.extent.max_z_mm - wall_top for item in objects)]
        summit = wall_top + max(heights)  # type: ignore[type-var]
        yield dataclasses.replace(
            draft,
            extent=Extent(
                lot.extent.min_x_mm,
                lot.extent.min_y_mm,
                base,
                lot.extent.max_x_mm,
                lot.extent.max_y_mm,
                summit,
            ),
        )
        yield from objects


STAGE: Final = GeneratorStage(
    massing.STAGE_ID,
    massing.STAGE_VERSION,
    (massing.MASSING_SHAPE, massing.ROOFTOP_SHAPE),
    _generate,
)
