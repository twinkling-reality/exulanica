"""Streetlife: street furniture and street trees at kerb offsets. Record shapes only.

A tree or a lamp is a record, not a renderer loop, because a person can reasonably point at one.
Placement is a rule (a curb, a distance along its segment's centreline and an offset back from
the kerb face into the footway) and the position that rule resolves to, both stated. The object's
shape is explicit parts in its local frame, turned by its direction vector; the class or species
key is a label, and a reader never looks a shape up by it.

**Exclusion.** Every object keeps ``exclusion_radius_mm`` clear round its position. The document
check refuses a position inside any building footprint (the target architecture's zero
intersections gate), two exclusion circles that overlap, and an object inside a crossing's
extent.

A tree's pit is an explicit ring in the footway round its trunk. No published texture set is
bark, foliage or soil yet, so a tree and its pit have no material records in this version and
draw as unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar import shapes
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import INSIDE, Extent, point_in_ring
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
    "FURNITURE_SHAPE",
    "STAGE",
    "STAGE_ID",
    "STAGE_VERSION",
    "TREE_SHAPE",
    "StreetFurnitureRecord",
    "StreetTreeRecord",
]

STAGE_ID: Final = "streetlife"
STAGE_VERSION: Final = 2


@dataclass(frozen=True, slots=True)
class StreetFurnitureRecord:
    RECORD_KIND: ClassVar[str] = "city.street_furniture"
    RECORD_VERSION: ClassVar[int] = 2

    identity: str
    curb_identity: str
    segment_identity: str
    item_ordinal: int
    #: A key into the street-furniture catalog. A label: ``parts`` are the geometry.
    furniture_class: str
    along_mm: int
    #: From the kerb face back into the footway.
    kerb_offset_mm: int
    x_mm: int
    y_mm: int
    z_mm: int
    facing_dx_mm: int
    facing_dy_mm: int
    parts: tuple[FormPart, ...]
    exclusion_radius_mm: int
    extent: Extent


def _furniture_rules(record: StreetFurnitureRecord) -> None:
    require_direction("facing", record.facing_dx_mm, record.facing_dy_mm)
    require_point_in_extent("the item's base", record.extent, record.x_mm, record.y_mm, record.z_mm)


FURNITURE_SHAPE: Final = shapes.RecordShape(
    StreetFurnitureRecord,
    (
        shapes.identity("identity"),
        shapes.identity("curb_identity", "city.curb_edge"),
        shapes.identity("segment_identity", "city.street_segment"),
        shapes.integer("item_ordinal", 0),
        shapes.key("furniture_class", "street-furniture"),
        shapes.integer("along_mm", 0),
        shapes.integer("kerb_offset_mm", 0, 12_000),
        shapes.integer("x_mm"),
        shapes.integer("y_mm"),
        shapes.integer("z_mm"),
        *direction_fields(),
        shapes.records("parts", FORM_PART_SHAPE, count_minimum=1),
        shapes.integer("exclusion_radius_mm", 0, 10_000),
        extent_field(),
    ),
    rules=(shapes.RecordRule("furniture_placed", _furniture_rules),),
    identity=shapes.IdentityRule(
        "street_furniture", owner_field="curb_identity", ordinal_field="item_ordinal"
    ),
    extent_field="extent",
)


@dataclass(frozen=True, slots=True)
class StreetTreeRecord:
    RECORD_KIND: ClassVar[str] = "city.street_tree"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    curb_identity: str
    segment_identity: str
    tree_ordinal: int
    #: A key into the tree-species catalog. A label: ``parts`` are the geometry.
    species: str
    along_mm: int
    kerb_offset_mm: int
    x_mm: int
    y_mm: int
    z_mm: int
    pit_mm: tuple[tuple[int, int], ...]
    parts: tuple[FormPart, ...]
    exclusion_radius_mm: int
    extent: Extent


def _tree_rules(record: StreetTreeRecord) -> None:
    if point_in_ring((record.x_mm, record.y_mm), record.pit_mm) != INSIDE:
        raise InvalidRecordError("a tree stands inside its pit")
    require_point_in_extent("the trunk base", record.extent, record.x_mm, record.y_mm, record.z_mm)


TREE_SHAPE: Final = shapes.RecordShape(
    StreetTreeRecord,
    (
        shapes.identity("identity"),
        shapes.identity("curb_identity", "city.curb_edge"),
        shapes.identity("segment_identity", "city.street_segment"),
        shapes.integer("tree_ordinal", 0),
        shapes.key("species", "tree-species"),
        shapes.integer("along_mm", 0),
        shapes.integer("kerb_offset_mm", 0, 12_000),
        shapes.integer("x_mm"),
        shapes.integer("y_mm"),
        shapes.integer("z_mm"),
        shapes.ring("pit_mm", count_minimum=4, count_maximum=4),
        shapes.records("parts", FORM_PART_SHAPE, count_minimum=1),
        shapes.integer("exclusion_radius_mm", 0, 10_000),
        extent_field(),
    ),
    rules=(shapes.RecordRule("tree_placed", _tree_rules),),
    identity=shapes.IdentityRule(
        "street_tree", owner_field="curb_identity", ordinal_field="tree_ordinal"
    ),
    extent_field="extent",
)

STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, FURNITURE_SHAPE, TREE_SHAPE)
