"""Facade: the durable procedural record per building per tier edge, and its ground band.

``docs/world-memory-model.md`` section 5.1 requires this record: "the admitted building identity,
grammar version, parameters, seed, output digest, and declared semantics". Those six are the
first six fields of :class:`FacadeRecord`, in that order (:data:`FACADE_RECORD_FIELDS`), and
``parameters`` states every parameter the facade stage reads, each with its value and source.

**Everything a tessellator would otherwise choose is a field.** Positions along a face are
millimetres along the tier edge's run from its start vertex (the face's ``u``); heights are
millimetres above the building's ``base_elevation_mm``.

* **Bays.** ``bays.count`` bays of ``bays.pitch_mm`` sit between ``margin_start_mm`` and
  ``margin_end_mm``; the four add up to the run length exactly. An edge longer than 1200 mm has
  at least one bay. A party wall has none.
* **Openings** (upper storeys only) are listed by storey. In every bay, an opening starts
  ``u_offset_mm`` after the bay's start (no implicit centring); its sill is ``sill_height_mm``
  above that storey's floor. It is recessed ``reveal_depth_mm``, its sill projects
  ``sill_projection_mm`` and is ``sill_thickness_mm`` thick, and its head is a flat top when
  ``head_rise_mm`` is 0 or a segmental arch rising ``head_rise_mm`` at the centre otherwise, with
  a head band ``head_band_mm`` tall projecting ``head_projection_mm``. ``head_treatment`` is a
  label.
* **Mouldings** are boxes: each runs the whole face, from ``z_bottom_mm`` to ``z_top_mm``,
  projecting ``projection_mm``. A string course is one box 60 to 200 mm tall. A cornice is a stack
  of boxes whose total height is 400 to 900 mm; an empty stack is no cornice.
* **The ground band** (a face that includes storey 0) is ``band_top_mm`` tall. Each ground bay is
  tiled exactly by rectangular panels whose roles are geometric (stall riser, glazing, transom,
  fascia, wall, frame, door), each at its own recess; an awning is a plane from the wall at
  ``wall_z_mm`` out ``projection_mm`` to the front edge at ``front_z_mm``, with a vertical
  valance ``valance_mm`` deep below the front edge. ``bay_kind`` is a label.
* **A party wall** has no openings. Above ``neighbour_top_mm`` it shows the scar where the
  neighbour's profile met it, and that region takes the ``party_wall_scar`` surface role.

``output_digest`` is :func:`facade_output_digest`: SHA-256 over the canonical JSON of the face's
layout (every field but the six) and the ground bays and entrances the face emitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import ClassVar, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.grammar import shapes
from exulanica.grammar.contract import DeclaredSemantics
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.grammars.city.common import extent_field, require_point_in_extent
from exulanica.grammar.grammars.city.descriptor import (
    CITY_ADMISSIBLE_USES,
    CITY_GRAMMAR_VERSION,
    CITY_SURFACE,
)
from exulanica.grammar.parameters import ParameterBinding, require_parameter_bindings
from exulanica.grammar.records import record_payload

__all__ = [
    "BAY_KINDS",
    "BAY_SHAPE",
    "ENTRANCE_SHAPE",
    "EXPOSURES",
    "FACADE_OUTPUT_PROFILE",
    "FACADE_RECORD_FIELDS",
    "FACADE_SHAPE",
    "FACADE_TIER_STRIDE",
    "HEAD_TREATMENTS",
    "MINIMUM_BAYED_RUN_MM",
    "PANEL_ROLES",
    "PANEL_SURFACE_ROLES",
    "STAGE",
    "STAGE_ID",
    "STAGE_VERSION",
    "Awning",
    "BayLayout",
    "EntranceRecord",
    "FacadeRecord",
    "GroundBayRecord",
    "GroundPanel",
    "Moulding",
    "OpeningGrid",
    "facade_output_digest",
]

STAGE_ID: Final = "facade"
STAGE_VERSION: Final = 2

#: The six fields section 5.1 requires, in its order.
FACADE_RECORD_FIELDS: Final = (
    "building_identity",
    "grammar_version",
    "parameters",
    "seed",
    "output_digest",
    "declared_semantics",
)
#: A facade's ordinal is ``tier_ordinal * FACADE_TIER_STRIDE + edge_ordinal``.
FACADE_TIER_STRIDE: Final = 1_000_000
#: An edge longer than this has at least one bay: the target architecture's rule.
MINIMUM_BAYED_RUN_MM: Final = 1_200
FACADE_OUTPUT_PROFILE: Final = "exulanica.city.facade-output/v1"

EXPOSURES: Final = ("frontage", "flank", "rear", "party_wall")
HEAD_TREATMENTS: Final = ("plain", "lintel", "arch", "hood")
BAY_KINDS: Final = ("shopfront", "entrance", "blank", "service")
#: What a ground panel is, and the surface role that dresses it.
PANEL_SURFACE_ROLES: Final = {
    "stall_riser": "stall_riser",
    "glazing": "glazing",
    "transom": "glazing",
    "fascia": "fascia",
    "wall": "ground_band",
    "frame": "shopfront_frame",
    "door": "door",
}
PANEL_ROLES: Final = tuple(PANEL_SURFACE_ROLES)
STRING_COURSE_HEIGHT_MM: Final = (60, 200)
CORNICE_HEIGHT_MM: Final = (400, 900)
GROUND_BAND_TOP_MM: Final = (4_000, 6_000)


@dataclass(frozen=True, slots=True)
class BayLayout:
    count: int
    pitch_mm: int
    margin_start_mm: int
    margin_end_mm: int


def _bay_layout(layout: BayLayout) -> None:
    if (layout.count == 0) != (layout.pitch_mm == 0):
        raise InvalidRecordError("a face has bays exactly when it has a pitch")


BAY_LAYOUT_SHAPE: Final = shapes.RecordShape(
    BayLayout,
    (
        shapes.integer("count", 0, 1_000),
        shapes.integer("pitch_mm", 0, 100_000),
        shapes.integer("margin_start_mm", 0),
        shapes.integer("margin_end_mm", 0),
    ),
    rules=(shapes.RecordRule("bay_count_and_pitch", _bay_layout),),
)


@dataclass(frozen=True, slots=True)
class OpeningGrid:
    storeys: tuple[int, ...]
    u_offset_mm: int
    width_mm: int
    height_mm: int
    sill_height_mm: int
    reveal_depth_mm: int
    sill_projection_mm: int
    sill_thickness_mm: int
    head_treatment: str
    head_rise_mm: int
    head_band_mm: int
    head_projection_mm: int


def _opening_head(grid: OpeningGrid) -> None:
    if 2 * grid.head_rise_mm > grid.width_mm:
        raise InvalidRecordError("an arched head rises at most half the opening's width")


OPENING_SHAPE: Final = shapes.RecordShape(
    OpeningGrid,
    (
        shapes.integers("storeys", 1, 119, increasing=True, count_minimum=1),
        shapes.integer("u_offset_mm", 0),
        shapes.integer("width_mm", 300, 4_000),
        shapes.integer("height_mm", 500, 5_000),
        shapes.integer("sill_height_mm", 0, 3_000),
        shapes.integer("reveal_depth_mm", 120, 250),
        shapes.integer("sill_projection_mm", 0, 150),
        shapes.integer("sill_thickness_mm", 0, 200),
        shapes.choice("head_treatment", HEAD_TREATMENTS),
        shapes.integer("head_rise_mm", 0, 2_000),
        shapes.integer("head_band_mm", 0, 900),
        shapes.integer("head_projection_mm", 0, 300),
    ),
    rules=(shapes.RecordRule("opening_head_rise", _opening_head),),
)


@dataclass(frozen=True, slots=True)
class Moulding:
    z_bottom_mm: int
    z_top_mm: int
    projection_mm: int


def _moulding(moulding: Moulding) -> None:
    if moulding.z_bottom_mm >= moulding.z_top_mm:
        raise InvalidRecordError("a moulding's bottom is below its top")


MOULDING_SHAPE: Final = shapes.RecordShape(
    Moulding,
    (
        shapes.integer("z_bottom_mm", 0),
        shapes.integer("z_top_mm", 1),
        shapes.integer("projection_mm", 1, 1_500),
    ),
    rules=(shapes.RecordRule("moulding_bottom_below_top", _moulding),),
)


@dataclass(frozen=True, slots=True)
class FacadeRecord:
    RECORD_KIND: ClassVar[str] = "city.facade"
    RECORD_VERSION: ClassVar[int] = 2

    building_identity: str
    grammar_version: int
    #: Every parameter the facade stage reads, sorted by name, with its value and source.
    parameters: tuple[ParameterBinding, ...]
    seed: str
    output_digest: str
    declared_semantics: DeclaredSemantics
    identity: str
    facade_ordinal: int
    tier_ordinal: int
    #: Which edge of the tier's ring this face stands on.
    edge_ordinal: int
    exposure: str
    faces_segment_identity: tuple[str, ...]
    faces_curb_identity: tuple[str, ...]
    run_length_mm: int
    first_storey: int
    last_storey: int
    #: The ground band's height when the face includes storey 0, else 0.
    band_top_mm: int
    bays: BayLayout
    openings: tuple[OpeningGrid, ...]
    string_courses: tuple[Moulding, ...]
    cornice: tuple[Moulding, ...]
    #: For a party wall, the height the neighbour covers; 0 for every other face.
    neighbour_top_mm: int
    extent: Extent


def _ordered(name: str, mouldings: tuple[Moulding, ...]) -> None:
    for before, after in pairwise(mouldings):
        if after.z_bottom_mm < before.z_top_mm:
            raise InvalidRecordError(f"{name} are ordered upward and do not overlap")


def _facade_rules(record: FacadeRecord) -> None:
    require_parameter_bindings(
        "parameters",
        record.parameters,
        CITY_SURFACE.parameters,
        CITY_SURFACE.cascade,
        stage=STAGE_ID,
    )
    if record.declared_semantics != DeclaredSemantics(STAGE_ID, CITY_ADMISSIBLE_USES):
        raise InvalidRecordError("a facade declares the facade subject and the city's projections")
    if record.edge_ordinal >= FACADE_TIER_STRIDE:
        raise InvalidRecordError("an edge ordinal is below the tier stride")
    if record.facade_ordinal != record.tier_ordinal * FACADE_TIER_STRIDE + record.edge_ordinal:
        raise InvalidRecordError("facade_ordinal is tier_ordinal * 1000000 + edge_ordinal")
    bays = record.bays
    if (
        bays.count * bays.pitch_mm + bays.margin_start_mm + bays.margin_end_mm
        != record.run_length_mm
    ):
        raise InvalidRecordError("bays and margins add up to the run length exactly")
    if (
        record.run_length_mm > MINIMUM_BAYED_RUN_MM
        and bays.count == 0
        and record.exposure != "party_wall"
    ):
        raise InvalidRecordError("an edge over 1200 mm has at least one bay")
    if record.exposure == "party_wall":
        if bays.count or record.openings:
            raise InvalidRecordError("a party wall has no bays and no openings")
    elif record.neighbour_top_mm:
        raise InvalidRecordError("only a party wall has a neighbour line")
    if (record.exposure == "frontage") != bool(record.faces_segment_identity):
        raise InvalidRecordError("a face names the segment it faces exactly when it is frontage")
    if bool(record.faces_segment_identity) != bool(record.faces_curb_identity):
        raise InvalidRecordError("a frontage face names both its segment and its curb")
    if record.first_storey > record.last_storey:
        raise InvalidRecordError("a face's first storey is at most its last")
    low, high = GROUND_BAND_TOP_MM
    if record.first_storey == 0:
        if not low <= record.band_top_mm <= high:
            raise InvalidRecordError(f"a ground band is {low} to {high} mm tall")
    elif record.band_top_mm:
        raise InvalidRecordError("a face above the ground storey has no ground band")
    for grid in record.openings:
        if not bays.count:
            raise InvalidRecordError("openings sit in bays")
        if grid.u_offset_mm + grid.width_mm > bays.pitch_mm:
            raise InvalidRecordError("an opening fits inside its bay")
        if grid.storeys[0] < max(1, record.first_storey) or grid.storeys[-1] > record.last_storey:
            raise InvalidRecordError("openings are on this face's upper storeys")
    low, high = STRING_COURSE_HEIGHT_MM
    for course in record.string_courses:
        if not low <= course.z_top_mm - course.z_bottom_mm <= high:
            raise InvalidRecordError(f"a string course is {low} to {high} mm tall")
    _ordered("string courses", record.string_courses)
    _ordered("cornice steps", record.cornice)
    if record.cornice:
        low, high = CORNICE_HEIGHT_MM
        height = record.cornice[-1].z_top_mm - record.cornice[0].z_bottom_mm
        if not low <= height <= high:
            raise InvalidRecordError(f"a cornice is {low} to {high} mm tall in total")


FACADE_SHAPE: Final = shapes.RecordShape(
    FacadeRecord,
    (
        shapes.identity("building_identity", "city.massing"),
        shapes.integer("grammar_version", CITY_GRAMMAR_VERSION, CITY_GRAMMAR_VERSION),
        shapes.records("parameters", shapes.PARAMETER_BINDING_SHAPE),
        shapes.seed("seed"),
        shapes.hex64("output_digest"),
        shapes.record("declared_semantics", shapes.SEMANTICS_SHAPE),
        shapes.identity("identity"),
        shapes.integer("facade_ordinal", 0),
        shapes.integer("tier_ordinal", 0, 1_000),
        shapes.integer("edge_ordinal", 0),
        shapes.choice("exposure", EXPOSURES),
        shapes.optional_identity("faces_segment_identity", "city.street_segment"),
        shapes.optional_identity("faces_curb_identity", "city.curb_edge"),
        shapes.integer("run_length_mm", 1),
        shapes.integer("first_storey", 0, 119),
        shapes.integer("last_storey", 0, 119),
        shapes.integer("band_top_mm", 0),
        shapes.record("bays", BAY_LAYOUT_SHAPE),
        shapes.optional_record("openings", OPENING_SHAPE),
        shapes.records("string_courses", MOULDING_SHAPE),
        shapes.records("cornice", MOULDING_SHAPE),
        shapes.integer("neighbour_top_mm", 0),
        extent_field(),
    ),
    rules=(shapes.RecordRule("facade_layout", _facade_rules),),
    identity=shapes.IdentityRule(
        "facade", owner_field="building_identity", ordinal_field="facade_ordinal"
    ),
    extent_field="extent",
)


@dataclass(frozen=True, slots=True)
class GroundPanel:
    role: str
    u_start_mm: int
    u_end_mm: int
    z_bottom_mm: int
    z_top_mm: int
    #: How far the panel is set back into the building from the face.
    recess_mm: int


def _panel(panel: GroundPanel) -> None:
    if panel.u_start_mm >= panel.u_end_mm or panel.z_bottom_mm >= panel.z_top_mm:
        raise InvalidRecordError("a panel has positive width and height")


PANEL_SHAPE: Final = shapes.RecordShape(
    GroundPanel,
    (
        shapes.choice("role", PANEL_ROLES),
        shapes.integer("u_start_mm", 0),
        shapes.integer("u_end_mm", 1),
        shapes.integer("z_bottom_mm", 0),
        shapes.integer("z_top_mm", 1),
        shapes.integer("recess_mm", 0, 3_000),
    ),
    rules=(shapes.RecordRule("panel_positive", _panel),),
)


@dataclass(frozen=True, slots=True)
class Awning:
    wall_z_mm: int
    front_z_mm: int
    projection_mm: int
    valance_mm: int


def _awning(awning: Awning) -> None:
    if awning.front_z_mm > awning.wall_z_mm:
        raise InvalidRecordError("an awning falls from the wall to its front edge")
    if awning.valance_mm > awning.front_z_mm:
        raise InvalidRecordError("an awning's valance stays above the base")


AWNING_SHAPE: Final = shapes.RecordShape(
    Awning,
    (
        shapes.integer("wall_z_mm", 1),
        shapes.integer("front_z_mm", 1),
        shapes.integer("projection_mm", 300, 4_000),
        shapes.integer("valance_mm", 0, 600),
    ),
    rules=(shapes.RecordRule("awning_profile", _awning),),
)


@dataclass(frozen=True, slots=True)
class GroundBayRecord:
    RECORD_KIND: ClassVar[str] = "city.ground_bay"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    facade_identity: str
    bay_ordinal: int
    #: A label. The panels are the geometry.
    bay_kind: str
    u_start_mm: int
    width_mm: int
    panels: tuple[GroundPanel, ...]
    awning: tuple[Awning, ...]
    extent: Extent


def _bay_rules(record: GroundBayRecord) -> None:
    left, right = record.u_start_mm, record.u_start_mm + record.width_mm
    top = max(panel.z_top_mm for panel in record.panels)
    if min(panel.z_bottom_mm for panel in record.panels) != 0:
        raise InvalidRecordError("a bay's panels start at the base")
    area = 0
    for index, panel in enumerate(record.panels):
        if panel.u_start_mm < left or panel.u_end_mm > right:
            raise InvalidRecordError(f"panel {index} lies within its bay")
        area += (panel.u_end_mm - panel.u_start_mm) * (panel.z_top_mm - panel.z_bottom_mm)
        for other in record.panels[index + 1 :]:
            if (
                panel.u_start_mm < other.u_end_mm
                and other.u_start_mm < panel.u_end_mm
                and panel.z_bottom_mm < other.z_top_mm
                and other.z_bottom_mm < panel.z_top_mm
            ):
                raise InvalidRecordError(f"panel {index} overlaps another")
    if area != record.width_mm * top:
        raise InvalidRecordError("a bay's panels tile it exactly")
    for awning in record.awning:
        if awning.wall_z_mm > top:
            raise InvalidRecordError("an awning meets the wall within the ground band")


BAY_SHAPE: Final = shapes.RecordShape(
    GroundBayRecord,
    (
        shapes.identity("identity"),
        shapes.identity("facade_identity", "city.facade"),
        shapes.integer("bay_ordinal", 0),
        shapes.choice("bay_kind", BAY_KINDS),
        shapes.integer("u_start_mm", 0),
        shapes.integer("width_mm", 1),
        shapes.records("panels", PANEL_SHAPE, count_minimum=1),
        shapes.optional_record("awning", AWNING_SHAPE),
        extent_field(),
    ),
    rules=(shapes.RecordRule("bay_panels_tile", _bay_rules),),
    identity=shapes.IdentityRule(
        "ground_bay", owner_field="facade_identity", ordinal_field="bay_ordinal"
    ),
    extent_field="extent",
)


@dataclass(frozen=True, slots=True)
class EntranceRecord:
    """A door a person can reach: where it is on the face, and where the footway meets it."""

    RECORD_KIND: ClassVar[str] = "city.entrance"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    facade_identity: str
    bay_identity: str
    entrance_ordinal: int
    u_centre_mm: int
    width_mm: int
    height_mm: int
    recess_mm: int
    #: The threshold's height above the footway in front of it.
    step_height_mm: int
    #: The threshold point: on the face line at ``u_centre_mm``, at the building's base level.
    threshold_x_mm: int
    threshold_y_mm: int
    threshold_z_mm: int
    #: The curb whose footway the entrance opens onto; empty for a door onto a lot.
    approach_curb_identity: tuple[str, ...]
    extent: Extent


def _entrance_rules(record: EntranceRecord) -> None:
    if 2 * record.u_centre_mm < record.width_mm:
        raise InvalidRecordError("an entrance starts at or after the face's start")
    require_point_in_extent(
        "the threshold",
        record.extent,
        record.threshold_x_mm,
        record.threshold_y_mm,
        record.threshold_z_mm,
    )


ENTRANCE_SHAPE: Final = shapes.RecordShape(
    EntranceRecord,
    (
        shapes.identity("identity"),
        shapes.identity("facade_identity", "city.facade"),
        shapes.identity("bay_identity", "city.ground_bay"),
        shapes.integer("entrance_ordinal", 0),
        shapes.integer("u_centre_mm", 1),
        shapes.integer("width_mm", 700, 4_000),
        shapes.integer("height_mm", 1_900, 5_000),
        shapes.integer("recess_mm", 0, 3_000),
        shapes.integer("step_height_mm", 0, 600),
        shapes.integer("threshold_x_mm"),
        shapes.integer("threshold_y_mm"),
        shapes.integer("threshold_z_mm"),
        shapes.optional_identity("approach_curb_identity", "city.curb_edge"),
        extent_field(),
    ),
    rules=(shapes.RecordRule("entrance_placed", _entrance_rules),),
    identity=shapes.IdentityRule(
        "entrance", owner_field="facade_identity", ordinal_field="entrance_ordinal"
    ),
    extent_field="extent",
)


def facade_output_digest(
    facade: FacadeRecord,
    bays: tuple[GroundBayRecord, ...],
    entrances: tuple[EntranceRecord, ...],
) -> str:
    """What the facade stage made for one face, digested: its layout, bays and entrances."""
    fields = record_payload(facade)["fields"]
    return sha256_of_canonical(
        {
            "profile": FACADE_OUTPUT_PROFILE,
            "layout": {
                name: value for name, value in fields.items() if name not in FACADE_RECORD_FIELDS
            },
            "bays": [record_payload(bay) for bay in sorted(bays, key=lambda bay: bay.bay_ordinal)],
            "entrances": [
                record_payload(entrance)
                for entrance in sorted(entrances, key=lambda entrance: entrance.entrance_ordinal)
            ],
        }
    ).hex()


STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, FACADE_SHAPE, BAY_SHAPE, ENTRANCE_SHAPE)
