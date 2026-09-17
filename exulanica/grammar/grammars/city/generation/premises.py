"""The premises generator: every shop, every home and office above, with its door and its sign.

**Shops.** Each shop unit of a building (its door bay and the shopfronts that follow it, with a
corner's second frontage joined at its end) is one premises on the ground storey. The building's
``ground_floor_use`` is derived among the uses its vitrines' fitout serves and its typology admits
on the ground floor, so a shop's window and its trade agree; a building's shops share the use, as
they share the fitout. A shop's floor area is the ground storey's footprint area shared by the width
of its bays on the primary frontage.

**Signs.** A shop's sign is the first key of the signage lexicon, in key order, for its use class
whose text fits the fascia run above its primary frontage bays at a readable size
(:mod:`~exulanica.grammar.grammars.city.generation.signs`); a shop with no fitting sign is refused.

**Above the shops, and houses.** The storeys above the ground storey are one premises, entered by
the building's own door, or by the first shop's when the building has no door of its own. Their
``upper_floor_use`` is derived among the typology's upper floor uses whose use class takes no sign,
since nothing above a shop carries a fascia for one. A building whose ground floor is a dwelling is
one premises from its ground storey to its top, entered by its door, of a use that takes no sign.
``units_per_storey`` is the number of premises on the ground storey, derived within exactly that.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

from exulanica.grammar.contract import StageContext
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import Extent, ring_twice_area
from exulanica.grammar.grammars.city import facade, massing, parcels, premises, streets, vitrine
from exulanica.grammar.grammars.city.generation.facade import building_shop_units
from exulanica.grammar.grammars.city.generation.signs import sign_run_mm
from exulanica.grammar.grammars.city.generation.stage import (
    GeneratorStage,
    catalog,
    derived,
    entry,
    prior_records,
)

__all__ = ["STAGE"]

_LOTS_PER_BLOCK: Final = 10_000


def _unsigned(uses: list[str]) -> list[str]:
    return sorted(use for use in uses if entry("use-class", use)["signage"] == "none")


def _sign(use: str, run: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if entry("use-class", use)["signage"] == "none":
        return (), ()
    for item in sorted(catalog("signage-lexicon").entries, key=lambda value: value.key):
        fields = entry("signage-lexicon", item.key)
        if fields["use_class"] == use and sign_run_mm(fields["text"]) <= run:
            return (item.key,), (fields["text"],)
    raise InvalidRecordError(f"no {use} sign fits a {run} mm fascia")


def _area(tier: massing.Tier) -> int:
    return ring_twice_area(tier.ring_mm) // 2


def _generate(context: StageContext) -> Iterator[premises.PremisesRecord]:
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
    entrances = prior_records(context, facade.STAGE_ID, facade.EntranceRecord)
    vitrines = prior_records(context, vitrine.STAGE_ID, vitrine.VitrineRecord)
    faces_of: dict[str, list[facade.FacadeRecord]] = {}
    for face in faces:
        faces_of.setdefault(face.building_identity, []).append(face)
    face_by_identity = {face.identity: face for face in faces}
    bays_of: dict[str, list[facade.GroundBayRecord]] = {}
    for bay in bays:
        bays_of.setdefault(face_by_identity[bay.facade_identity].building_identity, []).append(bay)
    door_of = {entrance.bay_identity: entrance for entrance in entrances}
    fitout_of = {item.building_identity: item.fitout for item in vitrines}

    for building in buildings:
        lot = lots[building.parcel_identity]
        ordinal = block_ordinals[lot.block_identity] * _LOTS_PER_BLOCK + lot.parcel_ordinal
        kind = entry("typology", building.typology)
        ring = building.tiers[0].ring_mm
        footprint = ring_twice_area(ring) // 2
        base = building.base_elevation_mm
        ground_top = base + building.ground_storey_height_mm
        summit = massing.tier_top_mm(building, building.tiers[-1])
        plan = (
            min(x for x, _y in ring),
            min(y for _x, y in ring),
            max(x for x, _y in ring),
            max(y for _x, y in ring),
        )
        own = faces_of.get(building.identity, [])
        primary = next(
            face
            for face in own
            if face.tier_ordinal == 0 and face.edge_ordinal == lot.frontages[0].edge_ordinal
        )
        building_doors = [
            bay
            for bay in bays_of.get(building.identity, [])
            if bay.facade_identity == primary.identity
            and bay.bay_kind == "entrance"
            and bay.identity in door_of
            and not any(panel.role == "fascia" for panel in bay.panels)
        ]
        units = building_shop_units(lot, own, bays_of.get(building.identity, []))
        unit_ordinal = 0
        if units:
            fitout = fitout_of.get(building.identity)
            served = (
                set(entry("fitout", fitout)["use_classes"])
                if fitout
                else set(kind["ground_floor_uses"])
            )
            use = derived(
                context,
                "ground_floor_use",
                ordinal,
                options=sorted(served & set(kind["ground_floor_uses"]) - {"residential"}),
            )
            derived(context, "units_per_storey", ordinal, minimum=len(units), maximum=len(units))
            for unit in units:
                on_primary = [bay for bay in unit if bay.facade_identity == primary.identity]
                run = sum(bay.width_mm for bay in on_primary)
                sign, text = _sign(use, run)  # type: ignore[arg-type]
                doors = sorted(
                    door_of[bay.identity].identity for bay in unit if bay.identity in door_of
                )
                if not doors:
                    raise InvalidRecordError(f"a shop of building {building.identity} has no door")
                yield premises.PremisesRecord(
                    identity=context.identity("premises", building.identity, unit_ordinal),
                    building_identity=building.identity,
                    unit_ordinal=unit_ordinal,
                    use_class=use,  # type: ignore[arg-type]
                    sign=sign,
                    sign_text=text,
                    first_storey=0,
                    last_storey=0,
                    floor_area_mm2=max(1, footprint * run // primary.run_length_mm),
                    bay_identities=tuple(sorted(bay.identity for bay in unit)),
                    entrance_identities=tuple(doors),
                    extent=Extent(plan[0], plan[1], base, plan[2], plan[3], ground_top),
                )
                unit_ordinal += 1
            first_upper = 1
            door_bays = building_doors or [next(bay for bay in units[0] if bay.identity in door_of)]
        else:
            use = derived(
                context, "ground_floor_use", ordinal, options=_unsigned(kind["ground_floor_uses"])
            )
            derived(context, "units_per_storey", ordinal, minimum=1, maximum=1)
            first_upper = 0
            door_bays = building_doors
            if not door_bays:
                raise InvalidRecordError(f"building {building.identity}'s dwelling has no door")
        if first_upper > building.storeys - 1:
            continue
        upper_use = (
            use
            if first_upper == 0
            else derived(
                context, "upper_floor_use", ordinal, options=_unsigned(kind["upper_floor_uses"])
            )
        )
        area = sum(
            _area(tier) * (tier.last_storey - max(tier.first_storey, first_upper) + 1)
            for tier in building.tiers
            if tier.last_storey >= first_upper
        )
        yield premises.PremisesRecord(
            identity=context.identity("premises", building.identity, unit_ordinal),
            building_identity=building.identity,
            unit_ordinal=unit_ordinal,
            use_class=upper_use,  # type: ignore[arg-type]
            sign=(),
            sign_text=(),
            first_storey=first_upper,
            last_storey=building.storeys - 1,
            floor_area_mm2=area,
            bay_identities=tuple(sorted(bay.identity for bay in building_doors)),
            entrance_identities=tuple(sorted(door_of[bay.identity].identity for bay in door_bays)),
            extent=Extent(
                plan[0], plan[1], base if first_upper == 0 else ground_top, plan[2], plan[3], summit
            ),
        )


STAGE: Final = GeneratorStage(
    premises.STAGE_ID, premises.STAGE_VERSION, (premises.SHAPE,), _generate
)
