"""The records the site grammar emits, each declared once as a record shape.

The frame is the site's own: x east and y north from the site's south-west corner, z up, integer
millimetres. Every footprint is an axis-aligned rectangle (``min_x_mm`` to ``max_x_mm``,
``min_y_mm`` to ``max_y_mm``) on the site's module, and a fixture turns in quarter turns, so every
overlap, clearance and reach the grammar and its readers check is exact integer arithmetic.

Every record states its subject identity by the one rule (:mod:`exulanica.grammar.subjects`): from
the generation's root for the site, its paths and its zones; from its zone for an area, a
structure or a zone's fixture; from its structure for a room; from its owner for a wall or a
fixture. The ordinal is the record's place among its owner's records of its kind, so an identity
is the same each time the receipt is generated again and never names a position.

Every record that is drawn states its look role as a family and a leaf, which the browser
resolves against the world's style pack when it draws; nothing here says what a part looks like.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Final

from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.grammars.site.plan import (
    ACCESS,
    ENCLOSURES,
    LOOK_FAMILIES,
    ROLES,
    ROOF_FORMS,
)
from exulanica.grammar.shapes import (
    IdentityRule,
    RecordRule,
    RecordShape,
    choice,
    choices,
    identity,
    integer,
    key,
    records,
    validate_record,
)

__all__ = [
    "FACINGS",
    "OPENING_KINDS",
    "RECORD_SHAPES",
    "SiteAreaRecord",
    "SiteExtentRecord",
    "SiteFixtureRecord",
    "SiteOpening",
    "SitePathRecord",
    "SiteRoomRecord",
    "SiteStructureRecord",
    "SiteWallRecord",
    "SiteZoneRecord",
    "shape_of",
    "validate_site_record",
]

#: The side of a rectangle a door, a gate or a zone's front faces.
FACINGS: Final = ("north", "east", "south", "west")
#: What a gap in a wall is: a door into a structure or a room, or a gate in a boundary.
OPENING_KINDS: Final = ("door", "gate")
#: The largest coordinate a record states: a site is at most a few hundred metres a side, and the
#: bound keeps every product of two coordinates inside an exact double.
_COORDINATE_MAXIMUM: Final = 10_000_000


def _ordered(record: Any) -> None:
    if not (record.min_x_mm < record.max_x_mm and record.min_y_mm < record.max_y_mm):
        raise InvalidRecordError(f"{type(record).RECORD_KIND} footprint is not a rectangle")


def _axis_aligned(record: Any) -> None:
    along_x = record.start_y_mm == record.end_y_mm and record.start_x_mm < record.end_x_mm
    along_y = record.start_x_mm == record.end_x_mm and record.start_y_mm < record.end_y_mm
    if not (along_x or along_y):
        raise InvalidRecordError("a wall runs along x or y, from its lesser end to its greater")
    length = (record.end_x_mm - record.start_x_mm) + (record.end_y_mm - record.start_y_mm)
    reached = 0
    for opening in record.openings:
        if opening.offset_mm < reached or opening.offset_mm + opening.width_mm > length:
            raise InvalidRecordError("a wall's openings lie inside it, in order, apart")
        if opening.height_mm > record.height_mm:
            raise InvalidRecordError("an opening is no taller than its wall")
        reached = opening.offset_mm + opening.width_mm


def _door_stated(record: Any) -> None:
    if (record.door_width_mm == 0) != (record.room_count == 0 and not record.roles):
        raise InvalidRecordError("a structure has a door exactly when it has rooms or a role")


def _rectangle() -> tuple[Any, ...]:
    return tuple(
        integer(f"{corner}_{axis}_mm", 0, _COORDINATE_MAXIMUM)
        for corner in ("min", "max")
        for axis in ("x", "y")
    )


def _look(prefix: str) -> tuple[Any, ...]:
    return (choice(f"{prefix}_family", LOOK_FAMILIES), key(f"{prefix}_leaf"))


@dataclass(frozen=True, slots=True)
class SiteExtentRecord:
    RECORD_KIND: ClassVar[str] = "site.extent"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    kind_key: str
    width_mm: int
    depth_mm: int
    module_mm: int
    enclosure: str
    ground_family: str
    ground_leaf: str
    entry_x_mm: int
    entry_width_mm: int
    wall_height_mm: int
    wall_thickness_mm: int


@dataclass(frozen=True, slots=True)
class SitePathRecord:
    RECORD_KIND: ClassVar[str] = "site.path"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    ordinal: int
    part_key: str
    min_x_mm: int
    min_y_mm: int
    max_x_mm: int
    max_y_mm: int
    roles: tuple[str, ...]
    look_family: str
    look_leaf: str


@dataclass(frozen=True, slots=True)
class SiteZoneRecord:
    RECORD_KIND: ClassVar[str] = "site.zone"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    ordinal: int
    zone_key: str
    min_x_mm: int
    min_y_mm: int
    max_x_mm: int
    max_y_mm: int
    frontage: str
    access: str
    ground_family: str
    ground_leaf: str
    gate_x_mm: int
    gate_y_mm: int


@dataclass(frozen=True, slots=True)
class SiteAreaRecord:
    RECORD_KIND: ClassVar[str] = "site.area"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    zone_identity: str
    ordinal: int
    part_key: str
    min_x_mm: int
    min_y_mm: int
    max_x_mm: int
    max_y_mm: int
    roles: tuple[str, ...]
    look_family: str
    look_leaf: str
    access_x_mm: int
    access_y_mm: int


@dataclass(frozen=True, slots=True)
class SiteStructureRecord:
    RECORD_KIND: ClassVar[str] = "site.structure"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    zone_identity: str
    ordinal: int
    part_key: str
    min_x_mm: int
    min_y_mm: int
    max_x_mm: int
    max_y_mm: int
    storeys: int
    storey_height_mm: int
    roof_form: str
    roles: tuple[str, ...]
    look_family: str
    look_leaf: str
    roof_family: str
    roof_leaf: str
    wall_family: str
    wall_leaf: str
    door_width_mm: int
    door_x_mm: int
    door_y_mm: int
    door_facing: str
    room_count: int


@dataclass(frozen=True, slots=True)
class SiteRoomRecord:
    RECORD_KIND: ClassVar[str] = "site.room"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    structure_identity: str
    ordinal: int
    part_key: str
    min_x_mm: int
    min_y_mm: int
    max_x_mm: int
    max_y_mm: int
    roles: tuple[str, ...]
    floor_family: str
    floor_leaf: str


@dataclass(frozen=True, slots=True)
class SiteOpening:
    """A gap in a wall: from ``offset_mm`` along the wall from its start, ``width_mm`` wide and
    ``height_mm`` high from the ground."""

    offset_mm: int
    width_mm: int
    height_mm: int
    kind: str


@dataclass(frozen=True, slots=True)
class SiteWallRecord:
    RECORD_KIND: ClassVar[str] = "site.wall"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    owner_identity: str
    ordinal: int
    part_key: str
    start_x_mm: int
    start_y_mm: int
    end_x_mm: int
    end_y_mm: int
    thickness_mm: int
    height_mm: int
    look_family: str
    look_leaf: str
    openings: tuple[SiteOpening, ...]


@dataclass(frozen=True, slots=True)
class SiteFixtureRecord:
    RECORD_KIND: ClassVar[str] = "site.fixture"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    owner_identity: str
    ordinal: int
    part_key: str
    x_mm: int
    y_mm: int
    yaw_quarter_turns: int
    width_mm: int
    depth_mm: int
    height_mm: int
    roles: tuple[str, ...]
    look_family: str
    look_leaf: str
    seats: int
    stands: int
    sleepers: int
    blocks: int


_OPENING_SHAPE: Final = RecordShape(
    SiteOpening,
    (
        integer("offset_mm", 0, _COORDINATE_MAXIMUM),
        integer("width_mm", 1, _COORDINATE_MAXIMUM),
        integer("height_mm", 1, _COORDINATE_MAXIMUM),
        choice("kind", OPENING_KINDS),
    ),
)

RECORD_SHAPES: Final = (
    RecordShape(
        SiteExtentRecord,
        (
            identity("identity"),
            key("kind_key"),
            integer("width_mm", 1, _COORDINATE_MAXIMUM),
            integer("depth_mm", 1, _COORDINATE_MAXIMUM),
            integer("module_mm", 1, _COORDINATE_MAXIMUM),
            choice("enclosure", ENCLOSURES),
            *_look("ground"),
            integer("entry_x_mm", 0, _COORDINATE_MAXIMUM),
            integer("entry_width_mm", 1, _COORDINATE_MAXIMUM),
            integer("wall_height_mm", 0, _COORDINATE_MAXIMUM),
            integer("wall_thickness_mm", 0, _COORDINATE_MAXIMUM),
        ),
        identity=IdentityRule("site_extent"),
    ),
    RecordShape(
        SitePathRecord,
        (
            identity("identity"),
            integer("ordinal", 0, _COORDINATE_MAXIMUM),
            key("part_key"),
            *_rectangle(),
            choices("roles", ROLES, count_minimum=1),
            *_look("look"),
        ),
        rules=(RecordRule("site_path_rectangle", _ordered),),
        identity=IdentityRule("site_path", ordinal_field="ordinal"),
    ),
    RecordShape(
        SiteZoneRecord,
        (
            identity("identity"),
            integer("ordinal", 0, _COORDINATE_MAXIMUM),
            key("zone_key"),
            *_rectangle(),
            choice("frontage", FACINGS),
            choice("access", ACCESS),
            *_look("ground"),
            integer("gate_x_mm", 0, _COORDINATE_MAXIMUM),
            integer("gate_y_mm", 0, _COORDINATE_MAXIMUM),
        ),
        rules=(RecordRule("site_zone_rectangle", _ordered),),
        identity=IdentityRule("site_zone", ordinal_field="ordinal"),
    ),
    RecordShape(
        SiteAreaRecord,
        (
            identity("identity"),
            identity("zone_identity", "site.zone"),
            integer("ordinal", 0, _COORDINATE_MAXIMUM),
            key("part_key"),
            *_rectangle(),
            choices("roles", ROLES, count_minimum=1),
            *_look("look"),
            integer("access_x_mm", 0, _COORDINATE_MAXIMUM),
            integer("access_y_mm", 0, _COORDINATE_MAXIMUM),
        ),
        rules=(RecordRule("site_area_rectangle", _ordered),),
        identity=IdentityRule("site_area", owner_field="zone_identity", ordinal_field="ordinal"),
    ),
    RecordShape(
        SiteStructureRecord,
        (
            identity("identity"),
            identity("zone_identity", "site.zone"),
            integer("ordinal", 0, _COORDINATE_MAXIMUM),
            key("part_key"),
            *_rectangle(),
            integer("storeys", 1, 64),
            integer("storey_height_mm", 1, _COORDINATE_MAXIMUM),
            choice("roof_form", ROOF_FORMS),
            choices("roles", ROLES),
            *_look("look"),
            *_look("roof"),
            *_look("wall"),
            integer("door_width_mm", 0, _COORDINATE_MAXIMUM),
            integer("door_x_mm", 0, _COORDINATE_MAXIMUM),
            integer("door_y_mm", 0, _COORDINATE_MAXIMUM),
            choice("door_facing", FACINGS),
            integer("room_count", 0, 64),
        ),
        rules=(
            RecordRule("site_structure_rectangle", _ordered),
            RecordRule("site_structure_door", _door_stated),
        ),
        identity=IdentityRule(
            "site_structure", owner_field="zone_identity", ordinal_field="ordinal"
        ),
    ),
    RecordShape(
        SiteRoomRecord,
        (
            identity("identity"),
            identity("structure_identity", "site.structure"),
            integer("ordinal", 0, _COORDINATE_MAXIMUM),
            key("part_key"),
            *_rectangle(),
            choices("roles", ROLES),
            *_look("floor"),
        ),
        rules=(RecordRule("site_room_rectangle", _ordered),),
        identity=IdentityRule(
            "site_room", owner_field="structure_identity", ordinal_field="ordinal"
        ),
    ),
    RecordShape(
        SiteWallRecord,
        (
            identity("identity"),
            identity("owner_identity", "site.extent", "site.zone", "site.structure"),
            integer("ordinal", 0, _COORDINATE_MAXIMUM),
            key("part_key"),
            integer("start_x_mm", 0, _COORDINATE_MAXIMUM),
            integer("start_y_mm", 0, _COORDINATE_MAXIMUM),
            integer("end_x_mm", 0, _COORDINATE_MAXIMUM),
            integer("end_y_mm", 0, _COORDINATE_MAXIMUM),
            integer("thickness_mm", 1, _COORDINATE_MAXIMUM),
            integer("height_mm", 1, _COORDINATE_MAXIMUM),
            *_look("look"),
            records("openings", _OPENING_SHAPE),
        ),
        rules=(RecordRule("site_wall_axis_aligned", _axis_aligned),),
        identity=IdentityRule("site_wall", owner_field="owner_identity", ordinal_field="ordinal"),
    ),
    RecordShape(
        SiteFixtureRecord,
        (
            identity("identity"),
            identity("owner_identity", "site.zone", "site.room"),
            integer("ordinal", 0, _COORDINATE_MAXIMUM),
            key("part_key"),
            integer("x_mm", 0, _COORDINATE_MAXIMUM),
            integer("y_mm", 0, _COORDINATE_MAXIMUM),
            integer("yaw_quarter_turns", 0, 3),
            integer("width_mm", 1, _COORDINATE_MAXIMUM),
            integer("depth_mm", 1, _COORDINATE_MAXIMUM),
            integer("height_mm", 1, _COORDINATE_MAXIMUM),
            choices("roles", ROLES, count_minimum=1),
            *_look("look"),
            integer("seats", 0, 64),
            integer("stands", 0, 64),
            integer("sleepers", 0, 2),
            integer("blocks", 0, 1),
        ),
        identity=IdentityRule(
            "site_fixture", owner_field="owner_identity", ordinal_field="ordinal"
        ),
    ),
)

_BY_TYPE: Final = {shape.record_type: shape for shape in RECORD_SHAPES}


def shape_of(record_type: type) -> RecordShape:
    """The shape of a site record type, or a refusal naming it."""
    shape = _BY_TYPE.get(record_type)
    if shape is None:
        raise InvalidRecordError(f"{record_type.__name__} is not a site record")
    return shape


def validate_site_record(record: object) -> None:
    """Hold one site record to its shape: every field, every rule."""
    validate_record(record, shape_of(type(record)))
