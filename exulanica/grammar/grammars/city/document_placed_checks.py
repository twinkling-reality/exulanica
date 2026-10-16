"""The checks of what a tile document places on its streets and buildings and of its ground:
surface materials, street furniture and trees, vitrines, the walk groups of signalled crossings,
interior backings, premises and terrain.

:class:`_PlacedChecks` is a part of :class:`~exulanica.grammar.grammars.city.document._Checker`,
which runs them with every other check.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from exulanica.grammar.geometry import OUTSIDE, point_in_ring
from exulanica.grammar.grammars.city.catalogs import form_parts
from exulanica.grammar.grammars.city.common import FormPart
from exulanica.grammar.grammars.city.document_plan import (
    _CAPSULE_HEIGHT_MM,
    _SHAPES_BY_TYPE,
    SUPPORT_KINDS,
    _CheckerCore,
    _fail,
    _in_extent_plan,
    support_top_mm,
)
from exulanica.grammar.grammars.city.facade import FacadeRecord, GroundBayRecord
from exulanica.grammar.grammars.city.material import SurfaceMaterialRecord, scaled_module_mm
from exulanica.grammar.grammars.city.premises import PremisesRecord
from exulanica.grammar.grammars.city.roads import (
    JunctionApproachRecord,
    RoadMarkingRecord,
    SignalRecord,
)
from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord, StreetTreeRecord
from exulanica.grammar.grammars.city.streets import CrossingRecord
from exulanica.grammar.grammars.city.support import support_top_under
from exulanica.grammar.grammars.city.terrain import TerrainRecord
from exulanica.grammar.grammars.city.vitrine import InteriorBackingRecord, VitrineRecord


class _PlacedChecks(_CheckerCore):
    """The material, street life, vitrine, walk group, backing, premises and terrain checks of
    :class:`~exulanica.grammar.grammars.city.document._Checker`."""

    # -- materials -------------------------------------------------------------------------

    def check_materials(self) -> None:
        dressed: set[tuple[str, str]] = set()
        for material in self.of(SurfaceMaterialRecord):
            self.report.materials += 1
            surface = self.get(material.surface_identity)
            where = f"material {material.identity}"
            if _SHAPES_BY_TYPE[type(surface)].kind != material.surface_kind:
                raise _fail(
                    "material_surface", f"{where} names a {material.surface_kind} it is not"
                )
            entry = self.entry("material", material.material)
            if entry["texture_set_id"] != material.texture_set_id:
                raise _fail("material_texture", f"{where} names another set than its material")
            self.report.materials_with_texture_set += 1
            if material.role not in entry["surfaces"]:
                raise _fail(
                    "material_role",
                    f"{where}: {material.material} does not dress a {material.role}",
                )
            for name, module in (
                ("course_module_mm", "course_module_mm"),
                ("mortar_module_mm", "mortar_module_mm"),
            ):
                if getattr(material, name) != scaled_module_mm(
                    entry[module], material.repeat_size_millionths
                ):
                    raise _fail("material_module", f"{where}'s {name} is not its set's, scaled")
            dressed.add((material.surface_identity, material.role))
        for facade in self.of(FacadeRecord):
            if (facade.identity, "wall") not in dressed:
                raise _fail("material_wall", f"facade {facade.identity} has no wall material")
            building = self.get(facade.building_identity)
            if facade.exposure != "party_wall" and (facade.identity, "wall") in dressed:
                wall = next(
                    material
                    for material in self.of(SurfaceMaterialRecord)
                    if material.surface_identity == facade.identity and material.role == "wall"
                )
                if wall.material not in self.entry("era", building.era)["wall_materials"]:
                    raise _fail(
                        "material_era", f"facade {facade.identity}'s wall is not of its era"
                    )
        unavailable = []
        for bay in self.of(GroundBayRecord):
            for panel in bay.panels:
                if panel.role in ("glazing", "transom", "door"):
                    unavailable.append(f"{bay.identity}:{panel.role}")
        for marking in self.of(RoadMarkingRecord):
            unavailable.append(f"{marking.identity}:marking")
        for tree in self.of(StreetTreeRecord):
            unavailable.append(f"{tree.identity}:tree")
        self.report.unavailable_surfaces = tuple(sorted(unavailable))

    # -- streetlife, vitrines, premises ----------------------------------------------------

    def _check_placed(self, record: Any, parts: tuple[FormPart, ...], exclusion: int) -> None:
        curb = self.carried(record.curb_identity)
        where = f"{_SHAPES_BY_TYPE[type(record)].kind} {record.identity}"
        if curb is not None and curb.segment_identity != record.segment_identity:
            raise _fail("placement", f"{where}'s curb is on another segment")
        if record.parts != parts:
            raise _fail("placement", f"{where}'s parts are not its class's parts")
        if record.exclusion_radius_mm < exclusion:
            raise _fail("placement", f"{where} keeps less clear than its class")
        for footprint in self._footprints:
            if point_in_ring((record.x_mm, record.y_mm), footprint) != OUTSIDE:
                raise _fail("footprint_intersection", f"{where} stands inside a building")
        for crossing in self.of(CrossingRecord):
            if _in_extent_plan(crossing.extent, record.x_mm, record.y_mm):
                raise _fail("placement", f"{where} stands in a crossing")

    def check_streetlife(self) -> None:
        placed = []
        for furniture in self.of(StreetFurnitureRecord):
            entry = self.entry("street-furniture", furniture.furniture_class)
            self._check_placed(furniture, form_parts(entry["parts"]), entry["exclusion_radius_mm"])
            if (
                not entry["kerb_offset_minimum_mm"]
                <= furniture.kerb_offset_mm
                <= entry["kerb_offset_maximum_mm"]
            ):
                raise _fail(
                    "placement",
                    f"furniture {furniture.identity} is outside its class's kerb offsets",
                )
            placed.append(furniture)
        for tree in self.of(StreetTreeRecord):
            self._check_placed(tree, tree.parts, 0)
            self._check_canopy_clearance(tree)
            placed.append(tree)
        for index, first in enumerate(placed):
            for second in placed[index + 1 :]:
                dx, dy = first.x_mm - second.x_mm, first.y_mm - second.y_mm
                reach = first.exclusion_radius_mm + second.exclusion_radius_mm
                if dx * dx + dy * dy < reach * reach:
                    raise _fail(
                        "exclusion", f"{first.identity} and {second.identity} crowd each other"
                    )

    def _check_canopy_clearance(self, tree: StreetTreeRecord) -> None:
        """A canopy part whose plan box meets a support record stands at least the capsule height
        above that record's support surface under the canopy (:mod:`.support`)."""
        supports = [
            record for record in self.records if _SHAPES_BY_TYPE[type(record)].kind in SUPPORT_KINDS
        ]
        for index, part in enumerate(tree.parts):
            if part.surface_role != "canopy":
                continue
            x, y = tree.x_mm + part.offset_x_mm, tree.y_mm + part.offset_y_mm
            half_x, half_y = (part.size_x_mm + 1) // 2, (part.size_y_mm + 1) // 2
            low_x, high_x, low_y, high_y = x - half_x, x + half_x, y - half_y, y + half_y
            bottom = tree.z_mm + part.offset_z_mm
            for support in supports:
                extent = support.extent
                if (
                    extent.min_x_mm <= high_x
                    and low_x <= extent.max_x_mm
                    and extent.min_y_mm <= high_y
                    and low_y <= extent.max_y_mm
                    and bottom
                    < support_top_under(support, low_x, low_y, high_x, high_y, support_top_mm)
                    + _CAPSULE_HEIGHT_MM
                ):
                    raise _fail(
                        "canopy_clearance",
                        f"tree {tree.identity}'s canopy part {index} hangs to {bottom} mm over "
                        f"{support.identity}, less than the {_CAPSULE_HEIGHT_MM} mm capsule above "
                        "its surface",
                    )

    def check_vitrines(self) -> None:
        for vitrine in self.of(VitrineRecord):
            bay = self.carried(vitrine.bay_identity)
            facade = self.carried(vitrine.facade_identity)
            where = f"vitrine {vitrine.identity}"
            if (
                bay is not None and facade is not None and bay.facade_identity != facade.identity
            ) or (facade is not None and facade.building_identity != vitrine.building_identity):
                raise _fail("vitrine", f"{where} names a bay, face and building that disagree")
            left, right = vitrine.u_start_mm, vitrine.u_start_mm + vitrine.width_mm
            bottom, top = vitrine.sill_mm, vitrine.sill_mm + vitrine.height_mm
            covered = 0
            for panel in bay.panels if bay is not None else ():
                if panel.role != "glazing":
                    continue
                width = min(right, panel.u_end_mm) - max(left, panel.u_start_mm)
                height = min(top, panel.z_top_mm) - max(bottom, panel.z_bottom_mm)
                if width > 0 and height > 0:
                    covered += width * height
            if bay is not None and covered != vitrine.width_mm * vitrine.height_mm:
                raise _fail("vitrine", f"{where} is not wholly behind glazing")
            unit = form_parts(self.entry("fitout", vitrine.fitout)["parts"])
            for part in vitrine.parts:
                if not any(
                    dataclasses.replace(part, offset_x_mm=other.offset_x_mm) == other
                    for other in unit
                ):
                    raise _fail(
                        "vitrine",
                        f"{where} holds a part that is not its fitout's, moved along the run",
                    )
                half_x, half_y = part.size_x_mm // 2, part.size_y_mm // 2
                if (
                    part.offset_x_mm - half_x < 0
                    or part.offset_x_mm + half_x > vitrine.width_mm
                    or part.offset_y_mm - half_y < 0
                    or part.offset_y_mm + half_y > vitrine.depth_mm
                    or part.offset_z_mm < 0
                    or part.offset_z_mm + part.size_z_mm > vitrine.height_mm
                ):
                    raise _fail("vitrine", f"{where}'s fitout leaves its box")

    def check_walk_groups(self) -> None:
        """Which walk a crossing belongs to: the one that walks while its own street is stopped.

        A person crossing the north leg of a junction walks while the east to west phase is green,
        so the crossings of one street belong to one pedestrian group and the crossings of the
        street that meets it belong to another. Two groups that released the crossings of one
        street would walk people into the same stopped traffic twice and leave the other street
        uncrossable.

        A crossing a signal releases must also lie on a leg of the junction that signal controls: a
        crossing no phase of that junction stops traffic for is refused here rather than paired by
        ordinal with whatever group happens to be next. In a document that passes ``[approaches]``
        that branch is unreachable, since every inbound segment of a junction has an approach; it
        is kept because the two checks are independent and a later junction rule may part them.

        The plan's intervals say which groups run together, and they live in traffic's signal-plan
        catalog, which this grammar names by digest and never reads. What is checkable here is the
        pairing, and the pairing is what a generator gets wrong.
        """
        legs: dict[str, set[str]] = {}
        for approach in self.of(JunctionApproachRecord):
            legs.setdefault(approach.junction_identity, set()).add(approach.segment_identity)
        for signal in self.of(SignalRecord):
            junction_legs = legs.get(signal.controls_identity)
            by_street: dict[str, str] = {}
            for group in signal.groups:
                if group.connection_identities or not group.crossing_identities:
                    continue
                streets = set()
                for identity in group.crossing_identities:
                    crossing = self.carried(identity)
                    if crossing is None:
                        continue
                    if junction_legs is not None and crossing.segment_identity not in junction_legs:
                        raise _fail(
                            "walk_group",
                            f"crossing {identity} is released by {signal.identity}'s group "
                            f"{group.group} and crosses no leg of the junction it controls",
                        )
                    segment = self.carried(crossing.segment_identity)
                    if segment is not None:
                        streets.add(segment.street_identity)
                if len(streets) > 1:
                    raise _fail(
                        "walk_group",
                        f"{signal.identity}'s group {group.group} releases crossings of "
                        f"{len(streets)} streets; a walk crosses one street",
                    )
                for street in streets:
                    if by_street.setdefault(street, group.group) != group.group:
                        raise _fail(
                            "walk_group",
                            f"{signal.identity} releases crossings of street {street} in both "
                            f"{by_street[street]} and {group.group}",
                        )

    def check_backings(self) -> None:
        """What lies behind a face's glass: one plane per glazed face, covering every opening.

        A face with openings and no backing is glass with the far side of the building behind it,
        which is the thing this record exists to stop. The plane stands behind the deepest reveal
        (so it is behind the glass, never in front of it) and its band covers every opening the
        face has, so no opening looks past its edge.
        """
        backings: dict[str, InteriorBackingRecord] = {}
        for backing in self.of(InteriorBackingRecord):
            where = f"interior backing {backing.identity}"
            if backing.facade_identity in backings:
                raise _fail("behind_glazing", f"{where} is a second backing for one face")
            backings[backing.facade_identity] = backing
            facade = self.carried(backing.facade_identity)
            if facade is None:
                continue
            if facade.building_identity != backing.building_identity:
                raise _fail("behind_glazing", f"{where} names a face and building that disagree")
            if not facade.openings:
                raise _fail("behind_glazing", f"{where} stands behind a face with no openings")
            if backing.u_start_mm or backing.width_mm != facade.run_length_mm:
                raise _fail("behind_glazing", f"{where} does not run the whole face")
            building = self.carried(facade.building_identity)
            if building is None:
                continue
            bottom, top = backing.sill_mm, backing.sill_mm + backing.height_mm
            for grid in facade.openings:
                if backing.depth_mm <= grid.reveal_depth_mm:
                    raise _fail(
                        "behind_glazing",
                        f"{where} stands {backing.depth_mm} mm back, no deeper than the "
                        f"{grid.reveal_depth_mm} mm reveal in front of it",
                    )
                for storey in grid.storeys:
                    floor = building.ground_storey_height_mm + (
                        (storey - 1) * building.upper_storey_height_mm
                    )
                    sill = floor + grid.sill_height_mm
                    head = sill + grid.height_mm + grid.head_rise_mm
                    if sill < bottom or head > top:
                        raise _fail(
                            "behind_glazing",
                            f"{where} covers {bottom} to {top} mm and storey {storey}'s opening "
                            f"reaches {sill} to {head} mm",
                        )
        for facade in self.of(FacadeRecord):
            if facade.openings and facade.identity not in backings:
                raise _fail(
                    "behind_glazing",
                    f"facade {facade.identity} has openings and nothing behind its glass",
                )

    def check_premises(self) -> None:
        for premises in self.of(PremisesRecord):
            building = self.get(premises.building_identity)
            where = f"premises {premises.identity}"
            if premises.last_storey >= building.storeys:
                raise _fail("premises", f"{where} is above its building")
            faces = {
                facade.identity
                for facade in self.of(FacadeRecord)
                if facade.building_identity == building.identity
            }
            for identity in premises.bay_identities:
                bay = self.carried(identity)
                if bay is not None and bay.facade_identity not in faces:
                    raise _fail("premises", f"{where} occupies another building's bay")
            for identity in premises.entrance_identities:
                entrance = self.carried(identity)
                if entrance is not None and entrance.facade_identity not in faces:
                    raise _fail("premises", f"{where} is reached through another building")
            use = self.entry("use-class", premises.use_class)
            if (use["signage"] == "required") != bool(premises.sign):
                raise _fail("premises_sign", f"{where}'s sign disagrees with its use class")
            for key, text in zip(premises.sign, premises.sign_text, strict=True):
                sign = self.entry("signage-lexicon", key)
                if sign["use_class"] != premises.use_class or sign["text"] != text:
                    raise _fail("premises_sign", f"{where}'s sign is another use's or another text")
            typology = self.entry("typology", building.typology)
            uses = typology[
                "ground_floor_uses" if premises.first_storey == 0 else "upper_floor_uses"
            ]
            if premises.use_class not in uses:
                raise _fail(
                    "premises_use",
                    f"{where}: a {building.typology} has no {premises.use_class} there",
                )
            for vitrine in self.of(VitrineRecord):
                if vitrine.bay_identity in premises.bay_identities:
                    fitout = self.entry("fitout", vitrine.fitout)
                    if premises.use_class not in fitout["use_classes"]:
                        raise _fail(
                            "vitrine_fitout",
                            f"vitrine {vitrine.identity} is not dressed for a {premises.use_class}",
                        )

    def check_terrain(self) -> None:
        for terrain in self.grammar.owned:
            if isinstance(terrain, TerrainRecord) and (terrain.tile_x, terrain.tile_y) != (
                self.tile.tile_x,
                self.tile.tile_y,
            ):
                raise _fail("terrain", f"terrain {terrain.identity} is another tile's")
