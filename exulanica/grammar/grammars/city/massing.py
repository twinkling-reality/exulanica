"""Massing: a building's tiers, storeys and roof, and what stands on the roof. Record shapes only.

**Storeys.** Storey 0 is the ground storey, ``ground_storey_height_mm`` tall from the building's
``base_elevation_mm``; every storey above it is ``upper_storey_height_mm`` tall. Storey ``k``'s
floor is at ``base + ground`` plus ``(k - 1) * upper`` for ``k >= 1``.

**Tiers are the setbacks, written out.** Tier 0's ring is the footprint and starts at storey 0.
Each tier covers a contiguous run of storeys, the next tier starts on the storey after, and the
last ends on the top storey. A tier's ring lies within the ring below it, touching it where the
walls run flush (a party wall usually does), so a setback is a ring the generator computed, never
an offset a reader has to derive. Where a tier is set back, the exposed part of the tier below is
a flat roof terrace with that tier's parapet. Light wells are rings strictly inside their tier;
their walls take the building's own ``wall`` material and carry no openings.

**The roof is a geometric form, not a catalog word.** ``roof_family`` is a label.
``roof_form`` decides the shape: ``flat`` is a deck at the top tier's wall top with the top tier's
parapet; ``ridge`` needs a convex four-sided top tier and ``ridge_mm`` holds the ridge's two plan
points, which are the floored midpoints of two opposite edges (the gable edges). The ridge stands
``roof_rise_mm`` above the wall top; the two gable edges carry vertical triangles, and the other
two edges each carry one plane up to the ridge. A flat roof has no ridge and no rise.

**Rooftop objects** stand only on flat roofs, on a roof region that is not covered by a tier
above, with their base on that region's deck. Their shapes are explicit parts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar import shapes
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import (
    Extent,
    extent_contains_ring,
    ring_inside_ring,
    ring_is_convex,
    ring_within_ring,
    rings_disjoint,
)
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.grammars.city.common import (
    FORM_PART_SHAPE,
    FormPart,
    direction_fields,
    extent_field,
    require_direction,
    require_point_in_extent,
)

__all__ = [
    "MASSING_SHAPE",
    "ROOFTOP_SHAPE",
    "ROOF_FORMS",
    "STAGE",
    "STAGE_ID",
    "STAGE_VERSION",
    "TIER_SHAPE",
    "MassingRecord",
    "RooftopObjectRecord",
    "Tier",
    "storey_floor_mm",
    "tier_top_mm",
]

STAGE_ID: Final = "massing"
STAGE_VERSION: Final = 2
ROOF_FORMS: Final = ("flat", "ridge")


@dataclass(frozen=True, slots=True)
class Tier:
    first_storey: int
    last_storey: int
    ring_mm: tuple[tuple[int, int], ...]
    light_wells_mm: tuple[tuple[tuple[int, int], ...], ...]
    #: The parapet round this tier's roof or terrace; 0 is none.
    parapet_height_mm: int


def _tier_rules(tier: Tier) -> None:
    if tier.first_storey > tier.last_storey:
        raise InvalidRecordError("a tier's first storey is at most its last")
    for index, well in enumerate(tier.light_wells_mm):
        if not ring_inside_ring(well, tier.ring_mm):
            raise InvalidRecordError(f"light well {index} lies strictly inside its tier")
        for other in tier.light_wells_mm[index + 1 :]:
            if not rings_disjoint(well, other):
                raise InvalidRecordError("light wells do not meet")


TIER_SHAPE: Final = shapes.RecordShape(
    Tier,
    (
        shapes.integer("first_storey", 0),
        shapes.integer("last_storey", 0),
        shapes.ring("ring_mm"),
        shapes.rings("light_wells_mm"),
        shapes.integer("parapet_height_mm", 0, 2_000),
    ),
    rules=(shapes.RecordRule("tier_storeys_and_wells", _tier_rules),),
)


@dataclass(frozen=True, slots=True)
class MassingRecord:
    """The building. Its identity is the building's, which every part of it refers to."""

    RECORD_KIND: ClassVar[str] = "city.massing"
    RECORD_VERSION: ClassVar[int] = 2

    identity: str
    parcel_identity: str
    building_ordinal: int
    base_elevation_mm: int
    #: Keys into the typology and era catalogs. Labels.
    typology: str
    era: str
    storeys: int
    ground_storey_height_mm: int
    upper_storey_height_mm: int
    tiers: tuple[Tier, ...]
    #: A key into the roof-family catalog. A label: ``roof_form`` is the geometry.
    roof_family: str
    roof_form: str
    ridge_mm: tuple[tuple[int, int], ...]
    roof_rise_mm: int
    extent: Extent


def storey_floor_mm(record: MassingRecord, storey: int) -> int:
    """The floor level of ``storey``, in millimetres above the datum."""
    if storey == 0:
        return record.base_elevation_mm
    return (
        record.base_elevation_mm
        + record.ground_storey_height_mm
        + (storey - 1) * record.upper_storey_height_mm
    )


def tier_top_mm(record: MassingRecord, tier: Tier) -> int:
    """The wall top of a tier: the ceiling of its last storey."""
    return storey_floor_mm(record, tier.last_storey + 1)


def _floored_midpoint(a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int]:
    return (a[0] + b[0]) // 2, (a[1] + b[1]) // 2


def _massing_rules(record: MassingRecord) -> None:
    expected_first = 0
    for index, tier in enumerate(record.tiers):
        if tier.first_storey != expected_first:
            raise InvalidRecordError(f"tier {index} starts on storey {expected_first}")
        expected_first = tier.last_storey + 1
        if index and not ring_within_ring(tier.ring_mm, record.tiers[index - 1].ring_mm):
            raise InvalidRecordError(f"tier {index} lies within the tier below it")
    if expected_first != record.storeys:
        raise InvalidRecordError("the tiers cover every storey exactly once")
    top = record.tiers[-1]
    if record.roof_form == "flat":
        if record.ridge_mm or record.roof_rise_mm:
            raise InvalidRecordError("a flat roof has no ridge and no rise")
    else:
        ring = top.ring_mm
        if len(ring) != 4 or not ring_is_convex(ring):
            raise InvalidRecordError("a ridge roof stands on a convex four-sided top tier")
        if len(record.ridge_mm) != 2 or record.roof_rise_mm < 1:
            raise InvalidRecordError("a ridge roof states its two ridge points and its rise")
        pairs = {
            (
                _floored_midpoint(ring[k], ring[k + 1]),
                _floored_midpoint(ring[k + 2], ring[(k + 3) % 4]),
            )
            for k in (0, 1)
        }
        if tuple(record.ridge_mm) not in pairs:
            raise InvalidRecordError(
                "a ridge runs between the floored midpoints of edges k and k + 2, in that order"
            )
    if not extent_contains_ring(record.extent, record.tiers[0].ring_mm):
        raise InvalidRecordError("a building's footprint lies inside its extent")
    summit = tier_top_mm(record, top) + max(record.roof_rise_mm, top.parapet_height_mm)
    if record.extent.min_z_mm > record.base_elevation_mm or record.extent.max_z_mm < summit:
        raise InvalidRecordError(f"a building's extent spans its base to {summit}")


MASSING_SHAPE: Final = shapes.RecordShape(
    MassingRecord,
    (
        shapes.identity("identity"),
        shapes.identity("parcel_identity", "city.parcel"),
        shapes.integer("building_ordinal", 0),
        shapes.integer("base_elevation_mm"),
        shapes.key("typology", "typology"),
        shapes.key("era", "era"),
        shapes.integer("storeys", 1, 120),
        shapes.integer("ground_storey_height_mm", 4_000, 6_000),
        shapes.integer("upper_storey_height_mm", 2_400, 6_000),
        shapes.records("tiers", TIER_SHAPE, count_minimum=1),
        shapes.key("roof_family", "roof-family"),
        shapes.choice("roof_form", ROOF_FORMS),
        shapes.points("ridge_mm", 2, count_minimum=0, count_maximum=2),
        shapes.integer("roof_rise_mm", 0, 20_000),
        extent_field(),
    ),
    rules=(shapes.RecordRule("massing_tiers_and_roof", _massing_rules),),
    identity=shapes.IdentityRule(
        "building", owner_field="parcel_identity", ordinal_field="building_ordinal"
    ),
    extent_field="extent",
)


@dataclass(frozen=True, slots=True)
class RooftopObjectRecord:
    """Plant, a tank, a lift overrun: explicit parts at a point on a flat roof."""

    RECORD_KIND: ClassVar[str] = "city.rooftop_object"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    building_identity: str
    object_ordinal: int
    #: A key into the rooftop-object catalog. A label: ``parts`` are the geometry.
    object_class: str
    x_mm: int
    y_mm: int
    z_mm: int
    facing_dx_mm: int
    facing_dy_mm: int
    parts: tuple[FormPart, ...]
    #: The least distance kept from every roof edge and parapet.
    clearance_mm: int
    extent: Extent


def _rooftop_rules(record: RooftopObjectRecord) -> None:
    require_direction("facing", record.facing_dx_mm, record.facing_dy_mm)
    require_point_in_extent(
        "the object's base", record.extent, record.x_mm, record.y_mm, record.z_mm
    )


ROOFTOP_SHAPE: Final = shapes.RecordShape(
    RooftopObjectRecord,
    (
        shapes.identity("identity"),
        shapes.identity("building_identity", "city.massing"),
        shapes.integer("object_ordinal", 0),
        shapes.key("object_class", "rooftop-object"),
        shapes.integer("x_mm"),
        shapes.integer("y_mm"),
        shapes.integer("z_mm"),
        *direction_fields(),
        shapes.records("parts", FORM_PART_SHAPE, count_minimum=1),
        shapes.integer("clearance_mm", 0, 10_000),
        extent_field(),
    ),
    rules=(shapes.RecordRule("rooftop_object_placed", _rooftop_rules),),
    identity=shapes.IdentityRule(
        "rooftop_object", owner_field="building_identity", ordinal_field="object_ordinal"
    ),
    extent_field="extent",
)

STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, MASSING_SHAPE, ROOFTOP_SHAPE)
