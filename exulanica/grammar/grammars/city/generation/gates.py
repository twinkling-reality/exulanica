"""The corridor's mechanical gates, measured from the generated records and from nothing else.

Each figure counts records; none reads a mesh, a renderer or a picture. The gates are the target
architecture's, as the corridor brief states them for city version 2:

* **Facade coverage.** Every building has a facade record on every edge of every tier.
* **Ground band.** Every face that includes the ground storey has a band 4000 to 6000 mm tall.
* **Bay pitch.** At least 95 per cent of frontage faces with bays have a pitch of 2400 to 3500 mm,
  and every edge longer than 1200 mm that is not a party wall has at least one bay.
* **Kerb height.** Every curb's kerb stands 100 to 180 mm.
* **Furniture in footprints.** No furniture or tree position lies inside or on a building's base
  ring.
* **Materials.** Every surface material names a texture set (a record without one cannot exist),
  and the surfaces with no published set are listed by role, as the unavailable state.
* **Section 5.1.** Every facade states its building identity, grammar version, parameters, seed,
  output digest and declared semantics, none empty.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from exulanica.grammar.geometry import OUTSIDE, point_in_ring
from exulanica.grammar.grammars.city.facade import (
    FACADE_RECORD_FIELDS,
    GROUND_BAND_TOP_MM,
    MINIMUM_BAYED_RUN_MM,
    FacadeRecord,
    GroundBayRecord,
)
from exulanica.grammar.grammars.city.massing import MassingRecord
from exulanica.grammar.grammars.city.material import SurfaceMaterialRecord
from exulanica.grammar.grammars.city.roads import RoadMarkingRecord
from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord, StreetTreeRecord
from exulanica.grammar.grammars.city.streets import (
    KERB_HEIGHT_MAXIMUM_MM,
    KERB_HEIGHT_MINIMUM_MM,
    CurbEdgeRecord,
)

__all__ = ["BAY_PITCH_BAND_MM", "PITCH_SHARE_PERCENT", "GateReport", "measure_gates"]

BAY_PITCH_BAND_MM: Final = (2_400, 3_500)
#: The share of frontage faces with bays whose pitch must lie in the band, in per cent.
PITCH_SHARE_PERCENT: Final = 95


@dataclass(slots=True)
class GateReport:
    buildings: int = 0
    buildings_with_every_facade: int = 0
    ground_faces: int = 0
    ground_faces_in_band: int = 0
    frontage_faces_with_bays: int = 0
    frontage_faces_in_pitch_band: int = 0
    pitches_mm: tuple[int, ...] = ()
    bayable_edges: int = 0
    bayable_edges_without_bays: int = 0
    curbs: int = 0
    kerb_heights_mm: tuple[int, ...] = ()
    objects: int = 0
    objects_inside_footprints: int = 0
    materials: int = 0
    materials_with_texture_set: int = 0
    unavailable_roles: dict[str, int] = field(default_factory=dict)
    facades: int = 0
    facades_with_section_5_1_fields: int = 0

    def passes(self) -> dict[str, bool]:
        return {
            "facade_coverage": self.buildings > 0
            and self.buildings_with_every_facade == self.buildings,
            "ground_band": self.ground_faces > 0 and self.ground_faces_in_band == self.ground_faces,
            "bay_pitch": self.frontage_faces_with_bays > 0
            and 100 * self.frontage_faces_in_pitch_band
            >= PITCH_SHARE_PERCENT * self.frontage_faces_with_bays
            and self.bayable_edges_without_bays == 0,
            "kerb_height": self.curbs > 0
            and all(
                KERB_HEIGHT_MINIMUM_MM <= height <= KERB_HEIGHT_MAXIMUM_MM
                for height in self.kerb_heights_mm
            ),
            "furniture_outside_footprints": self.objects_inside_footprints == 0,
            "materials_name_texture_sets": self.materials == self.materials_with_texture_set,
            "section_5_1": self.facades > 0
            and self.facades_with_section_5_1_fields == self.facades,
        }

    def as_dict(self) -> dict[str, object]:
        pitches = sorted(self.pitches_mm)
        return {
            "buildings": self.buildings,
            "buildings_with_every_facade": self.buildings_with_every_facade,
            "facade_coverage_percent": 100 * self.buildings_with_every_facade // self.buildings
            if self.buildings
            else 0,
            "ground_faces": self.ground_faces,
            "ground_faces_in_band": self.ground_faces_in_band,
            "frontage_faces_with_bays": self.frontage_faces_with_bays,
            "frontage_faces_in_pitch_band": self.frontage_faces_in_pitch_band,
            "pitch_mm_minimum_median_maximum": [pitches[0], pitches[len(pitches) // 2], pitches[-1]]
            if pitches
            else [],
            "bayable_edges": self.bayable_edges,
            "bayable_edges_without_bays": self.bayable_edges_without_bays,
            "curbs": self.curbs,
            "kerb_height_range_mm": [min(self.kerb_heights_mm), max(self.kerb_heights_mm)]
            if self.kerb_heights_mm
            else [],
            "objects": self.objects,
            "objects_inside_footprints": self.objects_inside_footprints,
            "materials": self.materials,
            "materials_with_texture_set": self.materials_with_texture_set,
            "unavailable_roles": dict(sorted(self.unavailable_roles.items())),
            "facades": self.facades,
            "facades_with_section_5_1_fields": self.facades_with_section_5_1_fields,
            "passes": self.passes(),
        }


def measure_gates(records: Sequence[object]) -> GateReport:
    report = GateReport()
    buildings = [record for record in records if isinstance(record, MassingRecord)]
    faces = [record for record in records if isinstance(record, FacadeRecord)]
    bays = [record for record in records if isinstance(record, GroundBayRecord)]
    faces_of: dict[str, set[tuple[int, int]]] = {}
    for face in faces:
        faces_of.setdefault(face.building_identity, set()).add(
            (face.tier_ordinal, face.edge_ordinal)
        )
    report.buildings = len(buildings)
    for building in buildings:
        edges = {
            (tier_index, edge)
            for tier_index, tier in enumerate(building.tiers)
            for edge in range(len(tier.ring_mm))
        }
        report.buildings_with_every_facade += faces_of.get(building.identity, set()) == edges
    low, high = GROUND_BAND_TOP_MM
    for face in faces:
        report.facades += 1
        report.facades_with_section_5_1_fields += all(
            getattr(face, name) not in ("", (), None) for name in FACADE_RECORD_FIELDS
        )
        if face.first_storey == 0:
            report.ground_faces += 1
            report.ground_faces_in_band += low <= face.band_top_mm <= high
        if face.exposure == "frontage" and face.bays.count:
            report.frontage_faces_with_bays += 1
            report.pitches_mm += (face.bays.pitch_mm,)
            report.frontage_faces_in_pitch_band += (
                BAY_PITCH_BAND_MM[0] <= face.bays.pitch_mm <= BAY_PITCH_BAND_MM[1]
            )
        if face.exposure != "party_wall" and face.run_length_mm > MINIMUM_BAYED_RUN_MM:
            report.bayable_edges += 1
            report.bayable_edges_without_bays += face.bays.count == 0
    for curb in records:
        if isinstance(curb, CurbEdgeRecord):
            report.curbs += 1
            report.kerb_heights_mm += (curb.kerb_height_mm,)
    footprints = [building.tiers[0].ring_mm for building in buildings]
    for item in records:
        if isinstance(item, StreetFurnitureRecord | StreetTreeRecord):
            report.objects += 1
            report.objects_inside_footprints += any(
                point_in_ring((item.x_mm, item.y_mm), ring) != OUTSIDE for ring in footprints
            )
    unavailable: Counter[str] = Counter()
    for item in records:
        if isinstance(item, SurfaceMaterialRecord):
            report.materials += 1
            report.materials_with_texture_set += bool(item.texture_set_id)
        elif isinstance(item, RoadMarkingRecord):
            unavailable["marking"] += 1
        elif isinstance(item, StreetTreeRecord):
            unavailable["tree"] += 1
    for bay in bays:
        for panel in bay.panels:
            if panel.role in ("glazing", "transom", "door"):
                unavailable[panel.role] += 1
    report.unavailable_roles = dict(unavailable)
    return report
