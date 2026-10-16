"""The checks of a tile document's lots and buildings: parcels in their blocks, footprints in their
parcels, building vocabulary, rooftop objects, facades and their clearance, ground bays and
entrances.

:class:`_BuildingChecks` is a part of :class:`~exulanica.grammar.grammars.city.document._Checker`,
which runs them with every other check.
"""

from __future__ import annotations

from collections import defaultdict

from exulanica.grammar.geometry import (
    BOUNDARY,
    INSIDE,
    OUTSIDE,
    edge_run_length,
    point_in_ring,
    ring_within_ring,
)
from exulanica.grammar.grammars.city.catalogs import form_parts
from exulanica.grammar.grammars.city.document_plan import (
    _CAPSULE_HEIGHT_MM,
    _NORMAL_ROUNDING_MM,
    BAY_PITCH_TARGET_MM,
    _CheckerCore,
    _fail,
    _near_segment,
)
from exulanica.grammar.grammars.city.facade import (
    EntranceRecord,
    FacadeRecord,
    GroundBayRecord,
    facade_output_digest,
)
from exulanica.grammar.grammars.city.massing import (
    MassingRecord,
    RooftopObjectRecord,
    storey_floor_mm,
    tier_top_mm,
)
from exulanica.grammar.grammars.city.parcels import ParcelRecord


class _BuildingChecks(_CheckerCore):
    """Lot and building checks of :class:`~exulanica.grammar.grammars.city.document._Checker`."""

    # -- lots and buildings ----------------------------------------------------------------

    def check_buildings(self) -> None:
        for parcel in self.of(ParcelRecord):
            block = self.carried(parcel.block_identity)
            if block is not None and not ring_within_ring(parcel.boundary_mm, block.boundary_mm):
                raise _fail("parcel_in_block", f"parcel {parcel.identity} leaves its block")
            for frontage in parcel.frontages:
                curb = self.carried(frontage.curb_identity)
                if curb is not None and curb.block_identity != (parcel.block_identity,):
                    raise _fail(
                        "frontage_curb", f"parcel {parcel.identity} fronts another block's curb"
                    )
        facades_by_building: dict[str, dict[tuple[int, int], FacadeRecord]] = defaultdict(dict)
        for facade in self.of(FacadeRecord):
            facades_by_building[facade.building_identity][
                (facade.tier_ordinal, facade.edge_ordinal)
            ] = facade
        footprints = []
        for building in self.of(MassingRecord):
            parcel = self.get(building.parcel_identity)
            if parcel.lot_class != "building":
                raise _fail("building_lot", f"building {building.identity} stands on a precinct")
            footprint = building.tiers[0].ring_mm
            footprints.append(footprint)
            if not ring_within_ring(footprint, parcel.boundary_mm):
                raise _fail(
                    "footprint_in_parcel", f"building {building.identity} leaves its parcel"
                )
            self._check_building_vocabulary(building)
            edges = {
                (tier_index, edge)
                for tier_index, tier in enumerate(building.tiers)
                for edge in range(len(tier.ring_mm))
            }
            present = facades_by_building.get(building.identity, {})
            if self.complete(building.identity):
                self.report.buildings += 1
                self.report.buildings_with_every_facade += set(present) == edges
            if set(present) - edges:
                raise _fail("facade_edges", f"building {building.identity} has a facade on no edge")
        self._footprints = footprints
        for obj in self.of(RooftopObjectRecord):
            self._check_rooftop(obj)
        for facade in self.of(FacadeRecord):
            self._check_facade(facade)
        for bay in self.of(GroundBayRecord):
            self._check_bay(bay)
        for entrance in self.of(EntranceRecord):
            self._check_entrance(entrance)

    def _check_building_vocabulary(self, building: MassingRecord) -> None:
        typology = self.entry("typology", building.typology)
        era = self.entry("era", building.era)
        family = self.entry("roof-family", building.roof_family)
        where = f"building {building.identity}"
        if building.era not in typology["eras"]:
            raise _fail(
                "typology", f"{where}: a {building.typology} is not of the {building.era} era"
            )
        if (
            building.roof_family not in typology["roof_families"]
            or building.roof_family not in era["roof_families"]
        ):
            raise _fail(
                "roof_family", f"{where}: {building.roof_family} does not suit its typology and era"
            )
        if not typology["storeys_minimum"] <= building.storeys <= typology["storeys_maximum"]:
            raise _fail("typology", f"{where} has storeys its typology does not")
        if (
            not era["upper_storey_minimum_mm"]
            <= building.upper_storey_height_mm
            <= era["upper_storey_maximum_mm"]
        ):
            raise _fail("era", f"{where}'s storeys are not its era's height")
        if family["form"] != building.roof_form:
            raise _fail(
                "roof_family", f"{where}: a {building.roof_family} roof is {family['form']}"
            )
        if not family["rise_minimum_mm"] <= building.roof_rise_mm <= family["rise_maximum_mm"]:
            raise _fail("roof_family", f"{where}'s roof rise is outside its family")
        parapet = building.tiers[-1].parapet_height_mm
        if (family["parapet"] == "required" and not parapet) or (
            family["parapet"] == "none" and parapet
        ):
            raise _fail("roof_family", f"{where}'s parapet disagrees with its roof family")

    def _check_rooftop(self, obj: RooftopObjectRecord) -> None:
        building = self.get(obj.building_identity)
        family = self.entry("roof-family", building.roof_family)
        entry = self.entry("rooftop-object", obj.object_class)
        where = f"rooftop object {obj.identity}"
        if building.roof_form != "flat" or family["rooftop_objects"] != "allowed":
            raise _fail("rooftop", f"{where} stands on a roof that takes none")
        if obj.parts != form_parts(entry["parts"]):
            raise _fail("rooftop", f"{where}'s parts are not its class's parts")
        if obj.clearance_mm < entry["clearance_minimum_mm"]:
            raise _fail("rooftop", f"{where} keeps less clearance than its class")
        tiers = building.tiers
        for index, tier in enumerate(tiers):
            covered = (
                index + 1 < len(tiers)
                and point_in_ring((obj.x_mm, obj.y_mm), tiers[index + 1].ring_mm) != OUTSIDE
            )
            if point_in_ring((obj.x_mm, obj.y_mm), tier.ring_mm) == INSIDE and not covered:
                if obj.z_mm != tier_top_mm(building, tier):
                    raise _fail("rooftop", f"{where} is not on its roof deck")
                return
        raise _fail("rooftop", f"{where} stands on no exposed roof")

    def _check_facade(self, facade: FacadeRecord) -> None:
        self.report.facades += 1
        self.report.facades_with_section_5_1_fields += 1
        building = self.get(facade.building_identity)
        where = f"facade {facade.identity}"
        if facade.tier_ordinal >= len(building.tiers):
            raise _fail("facade_edges", f"{where} stands on no tier")
        tier = building.tiers[facade.tier_ordinal]
        if facade.edge_ordinal >= len(tier.ring_mm):
            raise _fail("facade_edges", f"{where} stands on no edge")
        if facade.run_length_mm != edge_run_length(tier.ring_mm, facade.edge_ordinal):
            raise _fail("facade_run", f"{where}'s run is not its edge's")
        if (facade.first_storey, facade.last_storey) != (tier.first_storey, tier.last_storey):
            raise _fail("facade_storeys", f"{where} covers other storeys than its tier")
        if facade.first_storey == 0 and facade.band_top_mm != building.ground_storey_height_mm:
            raise _fail("ground_band", f"{where}'s ground band is not its ground storey")
        if facade.exposure == "frontage":
            curb = self.carried(facade.faces_curb_identity[0])
            if curb is not None and curb.segment_identity != facade.faces_segment_identity[0]:
                raise _fail("facade_frontage", f"{where} faces a curb of another segment")
            self.report.frontage_faces_with_bays += facade.bays.count > 0
            low, high = BAY_PITCH_TARGET_MM
            self.report.frontage_faces_in_pitch_band += (
                facade.bays.count > 0 and low <= facade.bays.pitch_mm <= high
            )
        if facade.exposure == "party_wall":
            parcel = self.get(building.parcel_identity)
            ring = tier.ring_mm
            for vertex in (ring[facade.edge_ordinal], ring[(facade.edge_ordinal + 1) % len(ring)]):
                if point_in_ring(vertex, parcel.boundary_mm) != BOUNDARY:
                    raise _fail("party_wall", f"{where} is not on its lot line")
        elif facade.run_length_mm > 1_200 and facade.bays.count == 0:
            self.report.edges_over_threshold_without_bays += 1
        era = self.entry("era", building.era)
        if era["cornice"] == "none" and facade.cornice:
            raise _fail("cornice", f"{where} has a cornice its era does not")
        top_frontage = (
            facade.exposure == "frontage" and facade.tier_ordinal == len(building.tiers) - 1
        )
        if era["cornice"] == "required" and top_frontage and not facade.cornice:
            raise _fail("cornice", f"{where} lacks the cornice its era requires")
        self._check_facade_clearance(facade, building)
        bays = tuple(
            bay for bay in self.of(GroundBayRecord) if bay.facade_identity == facade.identity
        )
        expected_bays = list(range(facade.bays.count)) if facade.first_storey == 0 else []
        present_bays = sorted(bay.bay_ordinal for bay in bays)
        complete = self.complete(facade.identity)
        if not set(present_bays) <= set(expected_bays) or (
            complete and present_bays != expected_bays
        ):
            raise _fail("ground_bays", f"{where} has one ground bay record per bay, and no other")
        bound = {binding.name: binding.value for binding in facade.parameters}
        for grid in facade.openings:
            for name, value in (
                ("opening_width_mm", grid.width_mm),
                ("opening_height_mm", grid.height_mm),
                ("sill_height_mm", grid.sill_height_mm),
                ("reveal_depth_mm", grid.reveal_depth_mm),
                ("sill_projection_mm", grid.sill_projection_mm),
                ("sill_thickness_mm", grid.sill_thickness_mm),
                ("head_treatment", grid.head_treatment),
                ("head_rise_mm", grid.head_rise_mm),
                ("head_band_mm", grid.head_band_mm),
                ("head_projection_mm", grid.head_projection_mm),
            ):
                if bound[name] != value:
                    raise _fail("facade_parameters", f"{where}'s openings disagree with {name}")
        entrances = tuple(
            entrance
            for entrance in self.of(EntranceRecord)
            if entrance.facade_identity == facade.identity
        )
        if complete and facade.output_digest != facade_output_digest(facade, bays, entrances):
            raise _fail("output_digest", f"{where}'s output digest is not its layout's")

    def _check_facade_clearance(self, facade: FacadeRecord, building: MassingRecord) -> None:
        """Every part a face puts beyond its building's base ring stands at least the capsule
        height above the building's base: its mouldings, and its openings' projecting sills and
        heads. Panels are set into the wall and project nothing."""
        where = f"facade {facade.identity}"
        for moulding in (*facade.string_courses, *facade.cornice):
            if moulding.z_bottom_mm < _CAPSULE_HEIGHT_MM:
                raise _fail(
                    "facade_clearance",
                    f"{where} projects a moulding {moulding.z_bottom_mm} mm above its base, below "
                    f"the {_CAPSULE_HEIGHT_MM} mm capsule",
                )
        for grid in facade.openings:
            for storey in grid.storeys:
                floor = storey_floor_mm(building, storey) - building.base_elevation_mm
                bottoms = []
                if grid.sill_projection_mm:
                    bottoms.append(floor + grid.sill_height_mm - grid.sill_thickness_mm)
                if grid.head_projection_mm:
                    bottoms.append(floor + grid.sill_height_mm + grid.height_mm)
                if bottoms and min(bottoms) < _CAPSULE_HEIGHT_MM:
                    raise _fail(
                        "facade_clearance",
                        f"{where} projects an opening's sill or head below the "
                        f"{_CAPSULE_HEIGHT_MM} mm capsule on storey {storey}",
                    )

    def _check_bay(self, bay: GroundBayRecord) -> None:
        facade = self.get(bay.facade_identity)
        layout = facade.bays
        where = f"bay {bay.identity}"
        if facade.first_storey != 0:
            raise _fail("ground_bay", f"{where} is on a face above the ground band")
        if bay.bay_ordinal >= layout.count:
            raise _fail("ground_bay", f"{where} is past its face's bays")
        if (bay.u_start_mm, bay.width_mm) != (
            layout.margin_start_mm + bay.bay_ordinal * layout.pitch_mm,
            layout.pitch_mm,
        ):
            raise _fail("ground_bay", f"{where} is not where its face's layout puts it")
        if max(panel.z_top_mm for panel in bay.panels) != facade.band_top_mm:
            raise _fail("ground_bay", f"{where} is not as tall as its ground band")
        for awning in bay.awning:
            if awning.front_z_mm - awning.valance_mm < _CAPSULE_HEIGHT_MM:
                raise _fail(
                    "facade_clearance",
                    f"{where}'s awning hangs to {awning.front_z_mm - awning.valance_mm} mm above "
                    f"its base, below the {_CAPSULE_HEIGHT_MM} mm capsule",
                )

    def _check_entrance(self, entrance: EntranceRecord) -> None:
        facade = self.get(entrance.facade_identity)
        bay = self.carried(entrance.bay_identity)
        building = self.get(facade.building_identity)
        where = f"entrance {entrance.identity}"
        left = entrance.u_centre_mm - entrance.width_mm // 2
        right = left + entrance.width_mm
        if bay is not None:
            if bay.facade_identity != facade.identity:
                raise _fail("entrance", f"{where}'s bay is on another face")
            if left < bay.u_start_mm or right > bay.u_start_mm + bay.width_mm:
                raise _fail("entrance", f"{where} leaves its bay")
            if not any(
                panel.role == "door" and panel.u_start_mm <= left and right <= panel.u_end_mm
                for panel in bay.panels
            ):
                raise _fail("entrance", f"{where} has no door panel")
        tier = building.tiers[facade.tier_ordinal]
        ring = tier.ring_mm
        start, end = ring[facade.edge_ordinal], ring[(facade.edge_ordinal + 1) % len(ring)]
        if not _near_segment(
            (entrance.threshold_x_mm, entrance.threshold_y_mm), start, end, _NORMAL_ROUNDING_MM
        ):
            raise _fail("entrance", f"{where}'s threshold is off its face")
        run = facade.run_length_mm
        along = (entrance.threshold_x_mm - start[0]) * (end[0] - start[0]) + (
            entrance.threshold_y_mm - start[1]
        ) * (end[1] - start[1])
        expected = entrance.u_centre_mm * run
        if abs(along - expected) > _NORMAL_ROUNDING_MM * run:
            raise _fail("entrance", f"{where}'s threshold is not at its centre along the face")
        if entrance.threshold_z_mm != building.base_elevation_mm:
            raise _fail("entrance", f"{where}'s threshold is not at the building's base")
        if (
            facade.faces_curb_identity
            and entrance.approach_curb_identity != facade.faces_curb_identity
        ):
            raise _fail("entrance", f"{where} opens onto another curb than its face")
