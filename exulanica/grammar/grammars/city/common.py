"""What every city record shares: the frame, the identity codes, surface roles, parts and anchors.

**The frame** is ``city_local``: x east, y north, z up, integer millimetres, origin at the city
frame origin, metric class ``metric_authored``. "Left" and "right" are relative to a segment's
digitised direction, start node to end node, and a signed lateral offset is positive to the left.
A ring is counter-clockwise, not closed by repetition, and edge ``i`` runs from vertex ``i`` to
vertex ``i + 1``; ``exulanica.grammar.geometry`` holds the rules and the exact tests. An edge's
run length is the floor square root of its squared length, the same number Python's
``math.isqrt`` gives.

**Units.** Lengths and elevations in millimetres, elevations above the city datum. Proportions in
millionths. Durations in milliseconds. Speeds in millimetres per second, floored, so 30 km/h is
8333. Areas in square millimetres. A direction is an integer vector ``(dx_mm, dy_mm)`` of any
length, never an angle: no record asks a reader for a sine. The one angle is a texture rotation,
which is applied in floating point outside every digest.

**Optional values** are tuples of at most one item. Nothing is ``None`` and nothing is a sentinel.

**Identity.** Every subject record's own identity is its ``identity`` field, and every reference
to another record is a field ending ``_identity``. The rule is
:func:`exulanica.grammar.subjects.subject_identity`, over the owner and ordinal each shape
declares; the root is the admitted identity of the city. Codes that stand in for an ordinal are
append-only: once published, a code is never renumbered or reused.

**Extents.** Every record with geometry carries ``extent``, a box that contains everything it
generates, so a reader can refuse a vertex outside it. The relation records
(``surface_material``, ``junction_approach``, ``signal``) have none.

**Surface frames**, which fix what ``s`` and ``t`` mean for every triangle a surface material
dresses. The tessellator emits ``s`` and ``t`` per vertex, in millimetres, and a face's
orientation is ``horizontal`` or ``vertical``. The frame follows from the owning record kind, the
surface role and the orientation alone:

* A vertical face: ``s`` runs along the face's run from its start and ``t = base - z``, pointing
  down. For a facade face (every role a facade owns) the run is the facade's edge run from its
  start vertex, the layout's own ``u``, and the base is the building's ``base_elevation_mm``; the
  same holds for a building's own vertical faces (light-well walls, parapets, ridge gables), each
  along its own ring edge. For a kerb face, ``s`` is the owning segment's along-centreline
  coordinate (the coordinate ``offset_mm`` and ``along_mm`` use) and the base is the kerb line's
  own ``z``. For an object part's side, ``s`` runs round the part from its local ``+x`` and the
  base is the object's ``z_mm``.
* A horizontal face: ``t`` is always to the left of ``s``, seen from the side the face is seen
  from, which is the side its normal points to. For a segment's carriageway and gutter, a curb's
  kerb top and footway, a crossing and a road marking on a segment, ``s`` is the owning segment's
  along-centreline coordinate. Everything else horizontal (a junction's carriageway, terrain, a
  lot, a roof, including a pitched roof plane in plan, an awning, a tree pit and the top of an
  object part) takes ``s = +x`` and ``t = +y`` in plan; a steep roof stretches its set, and says so
  here rather than hiding it.
* **An underside**, which is any horizontal face whose normal points down, takes ``s = +x`` and
  ``t = -y``. It mirrors because the rule above is not "t is +y" but "t is to the left of s from
  where the face is seen", and an underside is seen from below: keeping ``t = +y`` there would put
  ``t`` to the right and the texture would read reversed. The only horizontal face with an
  underside today is an object part's bottom, when its offset lifts it clear of what it stands on.
  The mirror is invisible on a material whose ``grain`` is ``none``, which most undersides wear,
  and visible on any material that states a grain, which is why it is stated here rather than left
  to whichever caller drew one first.

Texture coordinates follow from ``s`` and ``t`` and the material record, as ``material`` states.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from exulanica.grammar import shapes
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import Extent, extent_contains_point

__all__ = [
    "APPROACH_CONTROLS",
    "CITY_FRAME",
    "DIRECTION_LIMIT_MM",
    "DRIVING_SIDES",
    "FORM_PART_SHAPE",
    "FORM_SHAPES",
    "MILLIONTHS",
    "MOVEMENTS",
    "OBJECT_ROLES",
    "ORIENTATIONS",
    "PART_ROLES",
    "POWER_OF_TWO_SEGMENTS",
    "SIDES",
    "SIDE_CODES",
    "SURFACE_ROLES",
    "SURFACE_ROLE_CODES",
    "TILE_SIZE_MM",
    "TREE_PART_ROLES",
    "FormPart",
    "direction_fields",
    "extent_field",
    "require_direction",
    "require_part_roles",
    "require_point_in_extent",
    "tile_ordinal",
]

CITY_FRAME: Final = "city_local"
MILLIONTHS: Final = 1_000_000
#: The tile size of the tile stage's current version, shared so a terrain patch can match it.
TILE_SIZE_MM: Final = 128_000

SIDES: Final = ("left", "right")
#: The ordinal a curb edge's side contributes to its identity. Append-only.
SIDE_CODES: Final = {"left": 0, "right": 1}
DRIVING_SIDES: Final = ("right", "left")
MOVEMENTS: Final = ("left", "straight", "right", "u_turn")
APPROACH_CONTROLS: Final = ("signal", "stop", "yield", "priority")
ORIENTATIONS: Final = ("horizontal", "vertical")

#: Every surface role, and the fixed code a material record's identity takes from it.
#: Append-only: a published code is never renumbered or reused.
SURFACE_ROLE_CODES: Final = {
    "wall": 1,
    "ground_band": 2,
    "stall_riser": 3,
    "fascia": 4,
    "shopfront_frame": 5,
    "glazing": 6,
    "door": 7,
    "trim": 8,
    "party_wall_scar": 9,
    "roof": 10,
    "parapet": 11,
    "awning": 12,
    "carriageway": 13,
    "gutter": 14,
    "kerb": 15,
    "footway": 16,
    "crossing": 17,
    "marking": 18,
    "lot": 19,
    "terrain": 20,
    "object_primary": 21,
    "object_secondary": 22,
    "object_tertiary": 23,
    "tree_pit": 24,
    "canopy": 25,
    "trunk": 26,
}
SURFACE_ROLES: Final = tuple(SURFACE_ROLE_CODES)
OBJECT_ROLES: Final = ("object_primary", "object_secondary", "object_tertiary")
#: The roles a street tree's parts take: its trunk, and its canopy, which a foliage set dresses.
TREE_PART_ROLES: Final = ("trunk", "canopy")
PART_ROLES: Final = (*OBJECT_ROLES, *TREE_PART_ROLES)

FORM_SHAPES: Final = ("box", "prism", "ellipsoid")
#: Segment and ring counts a reader builds by integer chord bisection, so no sine is needed.
POWER_OF_TWO_SEGMENTS: Final = (4, 8, 16, 32, 64)
_ELLIPSOID_RINGS: Final = (4, 8, 16, 32)
#: The largest component a direction vector may have, so its squared length stays exact in a
#: double and a reader can normalise it with an integer square root.
DIRECTION_LIMIT_MM: Final = 1_000_000


def extent_field() -> shapes.FieldShape:
    return shapes.record("extent", shapes.EXTENT_SHAPE)


def require_point_in_extent(name: str, extent: Extent, x: int, y: int, z: int) -> None:
    if not extent_contains_point(extent, x, y, z):
        raise InvalidRecordError(f"{name} ({x}, {y}, {z}) lies outside the record's extent")


def require_part_roles(what: str, parts: tuple[FormPart, ...], roles: tuple[str, ...]) -> None:
    for index, part in enumerate(parts):
        if part.surface_role not in roles:
            raise InvalidRecordError(f"{what}'s part {index} takes one of {roles} as its role")


def require_direction(name: str, dx: int, dy: int) -> None:
    if dx == 0 and dy == 0:
        raise InvalidRecordError(f"{name} is a direction and cannot be zero")


def tile_ordinal(tile_x: int, tile_y: int) -> int:
    """A tile's ordinal: each coordinate folded onto the naturals, then Cantor-paired.

    ``fold(n) = 2n`` for ``n >= 0`` and ``-2n - 1`` below, so every tile of the plane has one
    ordinal and every ordinal one tile. Exact integers throughout.
    """
    if type(tile_x) is not int or type(tile_y) is not int:
        raise InvalidRecordError("tile coordinates are ints")
    first = 2 * tile_x if tile_x >= 0 else -2 * tile_x - 1
    second = 2 * tile_y if tile_y >= 0 else -2 * tile_y - 1
    return (first + second) * (first + second + 1) // 2 + second


@dataclass(frozen=True, slots=True)
class FormPart:
    """One solid of an object, in the object's local frame, before its direction is applied.

    Local ``+x`` is the object's direction vector, ``+y`` is to its left and ``+z`` is up; the
    offset places the part's bottom centre. A ``box`` spans its three sizes. A ``prism`` is a
    regular polygon of ``segments`` sides inscribed in the ``size_x`` by ``size_y`` ellipse,
    first vertex on local ``+x``, extruded by ``size_z`` and scaled at its top by
    ``top_scale_millionths`` (0 makes a cone). An ``ellipsoid`` fills its sizes with
    ``segments`` meridians and ``rings`` bands. The surface role names the material record the
    part takes from its owner: an object role for furniture, rooftop objects and fitouts, and
    ``trunk`` or ``canopy`` for a street tree.
    """

    shape: str
    surface_role: str
    offset_x_mm: int
    offset_y_mm: int
    offset_z_mm: int
    size_x_mm: int
    size_y_mm: int
    size_z_mm: int
    top_scale_millionths: int
    segments: int
    rings: int


def _form_part_counts(part: FormPart) -> None:
    if part.shape == "box":
        if (part.segments, part.rings) != (4, 1):
            raise InvalidRecordError("a box part has 4 segments and 1 ring")
    elif part.shape == "prism":
        if part.segments not in POWER_OF_TWO_SEGMENTS or part.rings != 1:
            raise InvalidRecordError(
                f"a prism part has {POWER_OF_TWO_SEGMENTS} segments and 1 ring"
            )
    else:
        if part.segments not in POWER_OF_TWO_SEGMENTS or part.rings not in _ELLIPSOID_RINGS:
            raise InvalidRecordError(
                f"an ellipsoid has {POWER_OF_TWO_SEGMENTS} segments and {_ELLIPSOID_RINGS} rings"
            )
        if part.top_scale_millionths != MILLIONTHS:
            raise InvalidRecordError("an ellipsoid is not tapered")


FORM_PART_SHAPE: Final = shapes.RecordShape(
    FormPart,
    (
        shapes.choice("shape", FORM_SHAPES),
        shapes.choice("surface_role", PART_ROLES),
        shapes.integer("offset_x_mm"),
        shapes.integer("offset_y_mm"),
        shapes.integer("offset_z_mm"),
        shapes.integer("size_x_mm", 1),
        shapes.integer("size_y_mm", 1),
        shapes.integer("size_z_mm", 1),
        shapes.integer("top_scale_millionths", 0, MILLIONTHS),
        shapes.integer("segments", 4, 64),
        shapes.integer("rings", 1, 32),
    ),
    rules=(shapes.RecordRule("form_part_counts", _form_part_counts),),
)


def direction_fields() -> tuple[shapes.FieldShape, shapes.FieldShape]:
    return (
        shapes.integer("facing_dx_mm", -DIRECTION_LIMIT_MM, DIRECTION_LIMIT_MM),
        shapes.integer("facing_dy_mm", -DIRECTION_LIMIT_MM, DIRECTION_LIMIT_MM),
    )
