"""The material generator: a surface material for every surface a published texture set can dress.

**Which surfaces.** Every role a record draws, and nothing else: a facade's wall always; its ground
band, and its stall riser, fascia, shopfront frame, glazing, door and awning where its bays have
them; its trim where it has mouldings or openings; its party wall scar where a neighbour stands
lower than it. A building's roof, its parapet where it has one, and its wall where a ridge roof
leaves gables. A rooftop object's parts' roles. A segment's carriageway and, with a gutter, its
gutter; a curb's kerb and footway; a junction's carriageway; a block's and a lot's ground. A street
tree's trunk, canopy and pit; a crossing's painted band. Terrain is the only role no published set
dresses, so it is the only one that draws as unavailable, and it does so at the district's edges
where no other record covers the ground.

**Everything a record draws, including what the late stages make.** This stage runs last but one,
after streetlife, vitrine and premises, so a street lamp's parts, a vitrine's fitout and the plane
behind a face's upper glazing are all dressed: they exist by the time it runs. It ran before them
until 2026-09-17, when it was moved, because a stage cannot dress a record that does not exist and
half the street was drawing unavailable for that reason alone.

**Which material.** A building's wall material is ``wall_material``, derived per building among
its era's wall materials. Every other role follows :data:`ROLE_MATERIALS`, an authored preference
order per role: a role marked ``wall`` takes the building's wall material when that material
dresses it, and otherwise, like every other role, the first material in its list that dresses it.
The table is authored and awaits the generated appearance lane's model-made looks; nothing in it
is a measured preference.

**Placement.** ``repeat_size_millionths`` is derived per building for its surfaces, per street for
a street's and per block or lot for its ground, so one building's brick is one size. The course and
mortar modules are the catalog's scaled by the repeat.

``texture_offset_u_mm`` and ``texture_offset_v_mm`` are derived the same way and narrowed to the
material's own modules, so a building's brick starts at its own place in the bond and no two
neighbours line their courses up. A material with no module along an axis states no offset on it.
This shifts the pattern within its module and not the set's image, whose repeat the grammar cannot
know: only the texture manifest holds a set's physical extent. ``texture_quarter_turns`` turns a
surface a whole number of quarter turns, and only where the material states no grain: a quarter
turn of a running bond lays its courses vertically, and a quarter turn of bark lays a trunk's
fibres across it.
``soiling_gradient_millionths``, ``base_weathering_millionths`` and
``reveal_darkening_millionths`` are building parameters, derived per building for its surfaces; a
street's surfaces belong to no building, so no parameter states their weathering and it is 0.

**The soiled bands on glass** are ``glazing_soil_band_bottom_mm`` and ``glazing_soil_band_edge_mm``,
derived per building so one building's shopfronts are dirty alike, and stated on its glazing
surfaces only: every other role states 0, which the record's ``soil_band_role`` rule holds. No
published set dresses glazing yet, so this version writes no glazing record at all and the bands
reach the document the moment one does.

**Stage version 3** (:data:`STAGE_V3`, which city grammar version 5 runs) dresses what version 2
leaves undressed. Every face's ground band takes a material, a party wall's included: version 2
skips a party wall's band, which the tessellator draws on every ground storey face, so a band
behind a neighbour showed through shop glass as the unavailable pattern. Every ground storey face
with bays takes a trim material, for the wall where its bays' panels step in depth. And every
terrain patch takes the first material in its role's order that dresses terrain, which edition 5
of the material catalog gives the tree pit soil: a city's bare ground where no street, block or
lot is drawn.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import partial
from typing import Final

from exulanica.grammar.contract import StageContext
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.grammars.city import (
    facade,
    massing,
    material,
    parcels,
    roads,
    streetlife,
    streets,
    terrain,
    vitrine,
)
from exulanica.grammar.grammars.city.common import SURFACE_ROLE_CODES
from exulanica.grammar.grammars.city.descriptor import CITY_GRAMMAR_VERSION
from exulanica.grammar.grammars.city.generation.stage import (
    GeneratorStage,
    catalog,
    derived,
    entry,
    prior_records,
)

__all__ = ["ROLE_MATERIALS", "STAGE", "STAGE_V3", "STAGE_VERSION_3"]

#: For each role, ``wall`` (the building's wall material, if it dresses the role) and then the
#: materials to try, in order. Authored; awaiting generated appearance.
ROLE_MATERIALS: Final = {
    "wall": ("wall",),
    "ground_band": ("wall", "limestone_ashlar"),
    "stall_riser": ("wall", "limestone_ashlar"),
    "fascia": ("painted_render", "storefront_metal"),
    "trim": ("wall", "limestone_ashlar", "cast_concrete"),
    "party_wall_scar": ("wall", "brick_running_bond"),
    "awning": ("awning_canvas", "storefront_metal"),
    "roof": ("cast_concrete",),
    "parapet": ("wall", "limestone_ashlar"),
    "carriageway": ("carriageway_asphalt",),
    "gutter": ("kerb_stone",),
    "kerb": ("kerb_stone",),
    "footway": ("footway_paving",),
    "lot": ("footway_paving",),
    "object_primary": ("storefront_metal",),
    "object_secondary": ("cast_concrete", "storefront_metal"),
    "object_tertiary": ("storefront_metal",),
    "shopfront_frame": ("painted_timber", "storefront_metal"),
    "glazing": ("float_glazing",),
    "door": ("painted_timber",),
    "tree_pit": ("tree_pit_soil",),
    # A crossing's band is paint over the carriageway, not a different road surface. There is no
    # entry for a lane marking: the record kind exists in the grammar and no stage emits one yet,
    # and a preference for a role nothing asks for would never be read.
    "crossing": ("road_paint_white",),
    "trunk": ("tree_bark",),
    "canopy": ("broadleaf_foliage",),
    # Bare ground, dressed from stage version 3 on: the material catalog's edition 5 names the one
    # material that dresses it.
    "terrain": ("tree_pit_soil",),
}
#: An interior backing takes the ``wall`` role and this order, not the building's wall material:
#: the finish inside a room is not what the street front is built of, and brick reads wrong.
_BACKING_MATERIALS: Final = ("painted_render", "cast_concrete")
#: A quarter turn, a half and three quarters, in microradians, rounded to the nearest.
_QUARTER_TURN_URAD: Final = (0, 1_570_796, 3_141_593, 4_712_389)
_LOTS_PER_BLOCK: Final = 10_000
#: Draw ordinals for surfaces no building owns, clear of every building's ordinal.
_STREETS: Final = 1 << 30
_GROUNDS: Final = 1 << 31
#: Draw ordinals for terrain patches, clear of every ground's: a ground's ordinal is below
#: ``_GROUNDS`` plus a lot's, which stays under ``1 << 30`` more.
_TERRAIN: Final = 3 << 30
#: The stage version that dresses every ground band and the bare ground (the docstring's last
#: section). Version 2 is :data:`~exulanica.grammar.grammars.city.material.STAGE_VERSION`.
STAGE_VERSION_3: Final = 3


def _material_for(
    role: str,
    wall: str | None,
    order: tuple[str, ...] | None = None,
    grammar_version: int = CITY_GRAMMAR_VERSION,
) -> str:
    for choice in order or ROLE_MATERIALS[role]:
        key = wall if choice == "wall" else choice
        if key is not None and role in entry("material", key, grammar_version)["surfaces"]:
            return key
    raise InvalidRecordError(f"no material in the role table dresses a {role} surface")


def _generate(
    context: StageContext, dress_all: bool = False
) -> Iterator[material.SurfaceMaterialRecord]:
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
    rooftops = prior_records(context, massing.STAGE_ID, massing.RooftopObjectRecord)
    walls = {
        key.key
        for key in catalog("material").entries
        if "wall" in entry("material", key.key)["surfaces"]
    }

    def record(
        surface: str,
        kind: str,
        role: str,
        key: str,
        placement: tuple[int, int, int, int, int, int],
        ordinal: int,
    ) -> material.SurfaceMaterialRecord:
        values = entry("material", key)
        repeat, soiling, weathering, darkening, band_bottom, band_edge = placement
        glazing = role == "glazing"
        # The offset shifts the pattern within its own module, so two buildings side by side do not
        # line their courses up. A material with no module along an axis states no offset on it.
        # This cannot break the set's own image repeat: the grammar reads the catalog's modules and
        # never the set's physical extent, which only the texture manifest holds.
        unit = material.scaled_module_mm(values["unit_length_mm"], repeat)
        course = material.scaled_module_mm(values["course_module_mm"], repeat)
        offset_u = derived(context, "texture_offset_u_mm", ordinal, maximum=max(unit - 1, 0))
        offset_v = derived(context, "texture_offset_v_mm", ordinal, maximum=max(course - 1, 0))
        turns = derived(
            context,
            "texture_quarter_turns",
            ordinal,
            maximum=3 if values["grain"] == "none" else 0,
        )
        return material.SurfaceMaterialRecord(
            identity=context.identity("surface_material", surface, SURFACE_ROLE_CODES[role]),
            surface_identity=surface,
            surface_kind=kind,
            role=role,
            material=key,
            texture_set_id=values["texture_set_id"],
            repeat_size_millionths=repeat,
            uv_rotation_urad=_QUARTER_TURN_URAD[turns],  # type: ignore[index]
            uv_offset_u_mm=offset_u,  # type: ignore[arg-type]
            uv_offset_v_mm=offset_v,  # type: ignore[arg-type]
            course_module_mm=material.scaled_module_mm(values["course_module_mm"], repeat),
            mortar_module_mm=material.scaled_module_mm(values["mortar_module_mm"], repeat),
            soiling_gradient_millionths=soiling,
            base_weathering_millionths=weathering,
            reveal_darkening_millionths=darkening,
            soil_band_bottom_mm=band_bottom if glazing else 0,
            soil_band_edge_mm=band_edge if glazing else 0,
        )

    bays_of: dict[str, list[facade.GroundBayRecord]] = {}
    for bay in bays:
        bays_of.setdefault(bay.facade_identity, []).append(bay)
    faces_of: dict[str, list[facade.FacadeRecord]] = {}
    for face in faces:
        faces_of.setdefault(face.building_identity, []).append(face)
    rooftops_of: dict[str, list[massing.RooftopObjectRecord]] = {}
    for item in rooftops:
        rooftops_of.setdefault(item.building_identity, []).append(item)

    building_placement: dict[str, tuple[int, int, int, int, int, int]] = {}
    building_ordinals: dict[str, int] = {}
    for building in buildings:
        lot = lots[building.parcel_identity]
        ordinal = block_ordinals[lot.block_identity] * _LOTS_PER_BLOCK + lot.parcel_ordinal
        era = entry("era", building.era)
        wall = derived(
            context,
            "wall_material",
            ordinal,
            options=[key for key in era["wall_materials"] if key in walls],
        )
        placement = (
            derived(context, "repeat_size_millionths", ordinal),
            derived(context, "soiling_gradient_millionths", ordinal),
            derived(context, "base_weathering_millionths", ordinal),
            derived(context, "reveal_darkening_millionths", ordinal),
            derived(context, "glazing_soil_band_bottom_mm", ordinal),
            derived(context, "glazing_soil_band_edge_mm", ordinal),
        )
        building_placement[building.identity] = placement  # type: ignore[assignment]
        building_ordinals[building.identity] = ordinal
        for face in faces_of.get(building.identity, []):
            face_bays = bays_of.get(face.identity, [])
            panel_roles = {
                facade.PANEL_SURFACE_ROLES[panel.role] for bay in face_bays for panel in bay.panels
            }
            roles = ["wall"]
            if face.first_storey == 0 and (dress_all or face.exposure != "party_wall"):
                roles.append("ground_band")
            roles += [
                role
                for role in ("stall_riser", "fascia", "shopfront_frame", "glazing", "door")
                if role in panel_roles
            ]
            # A ground storey's bays draw trim where their panels step in depth (a recessed door):
            # stage version 3 dresses it on every such face, which version 2 leaves undressed
            # unless the face also has openings or mouldings.
            if (
                face.string_courses
                or face.cornice
                or face.openings
                or (dress_all and face.first_storey == 0 and face_bays)
            ):
                roles.append("trim")
            height = massing.tier_top_mm(building, building.tiers[face.tier_ordinal]) - (
                building.base_elevation_mm
            )
            if face.exposure == "party_wall" and face.neighbour_top_mm < height:
                roles.append("party_wall_scar")
            if any(bay.awning for bay in face_bays):
                roles.append("awning")
            for role in roles:
                yield record(
                    face.identity,
                    "city.facade",
                    role,
                    _material_for(role, wall),
                    placement,  # type: ignore[arg-type]
                    ordinal,
                )
        roles = ["roof"]
        if any(tier.parapet_height_mm for tier in building.tiers):
            roles.append("parapet")
        if building.roof_form == "ridge":
            roles.append("wall")
        for role in roles:
            yield record(
                building.identity,
                "city.massing",
                role,
                _material_for(role, wall),
                placement,  # type: ignore[arg-type]
                ordinal,
            )
        for item in rooftops_of.get(building.identity, []):
            for role in sorted({part.surface_role for part in item.parts}):
                yield record(
                    item.identity,
                    "city.rooftop_object",
                    role,
                    _material_for(role, None),
                    placement,  # type: ignore[arg-type]
                    ordinal,
                )

    segment_records = prior_records(context, streets.STAGE_ID, streets.StreetSegmentRecord)
    street_ordinals = {
        record.identity: record.street_ordinal
        for record in prior_records(context, streets.STAGE_ID, streets.StreetRecord)
    }
    segments_by_identity = {record.identity: record.street_identity for record in segment_records}
    street_placement: dict[str, tuple[int, int, int, int, int, int]] = {}
    for segment in segment_records:
        street_placement[segment.identity] = (
            derived(
                context,
                "repeat_size_millionths",
                _STREETS + street_ordinals[segment.street_identity],
            ),
            0,
            0,
            0,
            0,
            0,
        )  # type: ignore[assignment]
        placement = street_placement[segment.identity]
        yield record(
            segment.identity,
            "city.street_segment",
            "carriageway",
            _material_for("carriageway", None),
            placement,
            _STREETS + street_ordinals[segment.street_identity],
        )
    curbs = prior_records(context, streets.STAGE_ID, streets.CurbEdgeRecord)
    for segment in segment_records:
        placement = street_placement[segment.identity]
        if any(curb.gutter_width_mm for curb in curbs if curb.segment_identity == segment.identity):
            yield record(
                segment.identity,
                "city.street_segment",
                "gutter",
                _material_for("gutter", None),
                placement,
                _STREETS + street_ordinals[segment.street_identity],
            )
    for curb in curbs:
        placement = street_placement[curb.segment_identity]
        for role in ("kerb", "footway"):
            yield record(
                curb.identity,
                "city.curb_edge",
                role,
                _material_for(role, None),
                placement,
                _STREETS + street_ordinals[segments_by_identity[curb.segment_identity]],
            )
    for junction in prior_records(context, streets.STAGE_ID, roads.JunctionRecord):
        placement = street_placement[junction.segment_identities[0]]
        yield record(
            junction.identity,
            "city.junction",
            "carriageway",
            _material_for("carriageway", None),
            placement,
            _STREETS + street_ordinals[segments_by_identity[junction.segment_identities[0]]],
        )
    for crossing in prior_records(context, streets.STAGE_ID, streets.CrossingRecord):
        yield record(
            crossing.identity,
            "city.crossing",
            "crossing",
            _material_for("crossing", None),
            street_placement[crossing.segment_identity],
            _STREETS + street_ordinals[segments_by_identity[crossing.segment_identity]],
        )
    for item in prior_records(context, streetlife.STAGE_ID, streetlife.StreetFurnitureRecord):
        placement = street_placement[item.segment_identity]
        for role in sorted({part.surface_role for part in item.parts}):
            yield record(
                item.identity,
                "city.street_furniture",
                role,
                _material_for(role, None),
                placement,
                _STREETS + street_ordinals[segments_by_identity[item.segment_identity]],
            )
    for case in prior_records(context, vitrine.STAGE_ID, vitrine.VitrineRecord):
        placement = building_placement[case.building_identity]
        for role in sorted({part.surface_role for part in case.parts}):
            yield record(
                case.identity,
                "city.vitrine",
                role,
                _material_for(role, None),
                placement,
                building_ordinals[case.building_identity],
            )
    for tree in prior_records(context, streetlife.STAGE_ID, streetlife.StreetTreeRecord):
        placement = street_placement[tree.segment_identity]
        ordinal = _STREETS + street_ordinals[segments_by_identity[tree.segment_identity]]
        # The pit is the tree's too: open ground beside its trunk, which the navigation table
        # calls a support surface a person may stand on.
        for role in (*sorted({part.surface_role for part in tree.parts}), "tree_pit"):
            yield record(
                tree.identity,
                "city.street_tree",
                role,
                _material_for(role, None),
                placement,
                ordinal,
            )
    for backing in prior_records(context, vitrine.STAGE_ID, vitrine.InteriorBackingRecord):
        yield record(
            backing.identity,
            "city.interior_backing",
            "wall",
            _material_for("wall", None, _BACKING_MATERIALS),
            building_placement[backing.building_identity],
            building_ordinals[backing.building_identity],
        )
    for block in prior_records(context, streets.STAGE_ID, streets.BlockRecord):
        repeat = derived(context, "repeat_size_millionths", _GROUNDS + block.block_ordinal)
        yield record(
            block.identity,
            "city.block",
            "lot",
            _material_for("lot", None),
            (repeat, 0, 0, 0, 0, 0),  # type: ignore[arg-type]
            _GROUNDS + block.block_ordinal,
        )
    for lot in lots.values():
        ordinal = block_ordinals[lot.block_identity] * _LOTS_PER_BLOCK + lot.parcel_ordinal
        repeat = derived(context, "repeat_size_millionths", _GROUNDS + _LOTS_PER_BLOCK + ordinal)
        yield record(
            lot.identity,
            "city.parcel",
            "lot",
            _material_for("lot", None),
            (repeat, 0, 0, 0, 0, 0),  # type: ignore[arg-type]
            _GROUNDS + _LOTS_PER_BLOCK + ordinal,
        )
    if not dress_all:
        return
    for patch in prior_records(context, terrain.STAGE_ID, terrain.TerrainRecord):
        repeat = derived(context, "repeat_size_millionths", _TERRAIN + patch.tile_ordinal)
        yield record(
            patch.identity,
            "city.terrain",
            "terrain",
            _material_for("terrain", None, grammar_version=context.grammar_version),
            (repeat, 0, 0, 0, 0, 0),  # type: ignore[arg-type]
            _TERRAIN + patch.tile_ordinal,
        )


STAGE: Final = GeneratorStage(
    material.STAGE_ID, material.STAGE_VERSION, (material.SHAPE,), _generate
)
#: Stage version 3: every ground band and the bare ground dressed as well.
STAGE_V3: Final = GeneratorStage(
    material.STAGE_ID,
    STAGE_VERSION_3,
    (material.SHAPE,),
    partial(_generate, dress_all=True),
)
