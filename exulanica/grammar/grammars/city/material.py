"""Material: a ``surface_material`` record per dressed surface role. Record shape only.

**A material with no texture set is a schema error, not a default.** ``texture_set_id`` is a
required field, follows the texture set id rule, and must be the set the material catalog entry
names; :func:`require_texture_set` refuses one that is not published. A record carries the
stable id only; the set's version and digest are pinned where the catalog resolves it.

**Which surface.** A record dresses one role (:data:`SURFACE_ROLE_OWNERS` says which record kinds
may own each role) of the subject ``surface_identity`` names. Its identity derives from that
subject and the role's fixed code. A role with no material record draws as unavailable: in this
version no published set can dress glazing, doors, road paint, terrain, tree pits or foliage.

**Texture coordinates, exactly.** The tessellator states each vertex's surface coordinates
``(s, t)`` in millimetres, in the frame ``common`` fixes for the owning record kind, the role and
the face's orientation. The set's physical extent is ``(extent_u_mm, extent_v_mm)`` from the
texture manifest. Then:

* ``repeat_u = extent_u_mm * repeat_size_millionths / 10**6`` and
  ``repeat_v = extent_v_mm * repeat_size_millionths / 10**6``. One factor, so a texel keeps its
  aspect; 2,000,000 makes one tile of the set twice as large.
* ``u`` pairs with ``s`` and ``v`` with ``t``. The rotation ``theta = uv_rotation_urad`` pivots
  about ``(s, t) = (0, 0)``, and a positive ``theta`` turns ``+s`` toward ``+t``. The offsets are
  millimetres along the texture's own axes, added after the rotation and before dividing by the
  repeat::

      u = (cos(theta) * s - sin(theta) * t + uv_offset_u_mm) / repeat_u
      v = (sin(theta) * s + cos(theta) * t + uv_offset_v_mm) / repeat_v

  This is evaluated in floating point by the renderer and enters no digest.
* Row 0 of a set is the top of each repeat. On a vertical face ``t = base - z``, so repeats start
  at the base.
* ``course_module_mm`` and ``mortar_module_mm`` are the set's baked course and joint modules, as
  the material catalog reads them from the set's recipe, times ``repeat_size_millionths``,
  floored: the sizes a face can align openings and string courses to.

Rotation is in microradians, in ``[0, 6283185]``, which is one turn less the part of a microradian
that 2 pi does not fill. Proportions are in millionths.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar import shapes
from exulanica.grammar.errors import InvalidRecordError, UnresolvedReferenceError
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.grammars.city.common import MILLIONTHS, SURFACE_ROLE_CODES, SURFACE_ROLES
from exulanica.grammar.textures import TextureSet

__all__ = [
    "MAXIMUM_ROTATION_URAD",
    "MILLIONTHS",
    "REPEAT_SIZE_RANGE",
    "SHAPE",
    "STAGE",
    "STAGE_ID",
    "STAGE_VERSION",
    "SURFACE_KINDS",
    "SURFACE_ROLE_OWNERS",
    "SurfaceMaterialRecord",
    "require_texture_set",
    "scaled_module_mm",
]

STAGE_ID: Final = "material"
STAGE_VERSION: Final = 2
MAXIMUM_ROTATION_URAD: Final = 6_283_185
REPEAT_SIZE_RANGE: Final = (500_000, 2_000_000)

_FACADE_ROLES: Final = (
    "wall",
    "ground_band",
    "stall_riser",
    "fascia",
    "shopfront_frame",
    "glazing",
    "door",
    "trim",
    "party_wall_scar",
    "awning",
)
_OBJECTS: Final = (
    "city.rooftop_object",
    "city.street_furniture",
    "city.street_tree",
    "city.vitrine",
)

#: For every surface role, the record kinds whose subjects may own a surface of that role.
SURFACE_ROLE_OWNERS: Final = {
    **{role: ("city.facade",) for role in _FACADE_ROLES},
    "wall": ("city.facade", "city.massing"),
    "roof": ("city.massing",),
    "parapet": ("city.massing",),
    "carriageway": ("city.street_segment", "city.junction"),
    "gutter": ("city.street_segment",),
    "kerb": ("city.curb_edge",),
    "footway": ("city.curb_edge",),
    "crossing": ("city.crossing",),
    "marking": ("city.road_marking",),
    "lot": ("city.parcel", "city.block"),
    "terrain": ("city.terrain",),
    "object_primary": _OBJECTS,
    "object_secondary": _OBJECTS,
    "object_tertiary": _OBJECTS,
    "tree_pit": ("city.street_tree",),
}
SURFACE_KINDS: Final = tuple(
    sorted({kind for kinds in SURFACE_ROLE_OWNERS.values() for kind in kinds})
)


def scaled_module_mm(module_mm: int, repeat_size_millionths: int) -> int:
    """A baked module as it lands on a surface: ``module * repeat // 10**6``."""
    return module_mm * repeat_size_millionths // MILLIONTHS


@dataclass(frozen=True, slots=True)
class SurfaceMaterialRecord:
    RECORD_KIND: ClassVar[str] = "city.surface_material"
    RECORD_VERSION: ClassVar[int] = 2

    identity: str
    surface_identity: str
    #: The record kind of the subject ``surface_identity`` names.
    surface_kind: str
    role: str
    #: A key into the material catalog.
    material: str
    texture_set_id: str
    repeat_size_millionths: int
    uv_rotation_urad: int
    uv_offset_u_mm: int
    uv_offset_v_mm: int
    course_module_mm: int
    mortar_module_mm: int
    soiling_gradient_millionths: int
    base_weathering_millionths: int
    reveal_darkening_millionths: int


def _role_owner(record: SurfaceMaterialRecord) -> None:
    if record.surface_kind not in SURFACE_ROLE_OWNERS[record.role]:
        raise InvalidRecordError(
            f"a {record.surface_kind} does not own a {record.role} surface; "
            f"{SURFACE_ROLE_OWNERS[record.role]} do"
        )


SHAPE: Final = shapes.RecordShape(
    SurfaceMaterialRecord,
    (
        shapes.identity("identity"),
        shapes.identity("surface_identity", *SURFACE_KINDS),
        shapes.choice("surface_kind", SURFACE_KINDS),
        shapes.choice("role", SURFACE_ROLES),
        shapes.key("material", "material"),
        shapes.texture_set_id("texture_set_id"),
        shapes.integer("repeat_size_millionths", *REPEAT_SIZE_RANGE),
        shapes.integer("uv_rotation_urad", 0, MAXIMUM_ROTATION_URAD),
        shapes.integer("uv_offset_u_mm", 0, 100_000),
        shapes.integer("uv_offset_v_mm", 0, 100_000),
        shapes.integer("course_module_mm", 0, 100_000),
        shapes.integer("mortar_module_mm", 0, 1_000),
        shapes.integer("soiling_gradient_millionths", 0, MILLIONTHS),
        shapes.integer("base_weathering_millionths", 0, MILLIONTHS),
        shapes.integer("reveal_darkening_millionths", 0, MILLIONTHS),
    ),
    rules=(shapes.RecordRule("material_role_owner", _role_owner),),
    identity=shapes.IdentityRule(
        "surface_material",
        owner_field="surface_identity",
        ordinal_field="role",
        ordinal_codes=SURFACE_ROLE_CODES,
    ),
)


def require_texture_set(record: SurfaceMaterialRecord, published: Mapping[str, TextureSet]) -> None:
    """The record's texture set exists among ``published``, or the record is refused."""
    if record.texture_set_id not in published:
        raise UnresolvedReferenceError(
            f"texture set {record.texture_set_id!r} is not published; "
            "a material with no texture set is a schema error, not a default"
        )


STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, SHAPE)
