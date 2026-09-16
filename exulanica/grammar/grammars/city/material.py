"""Material: a ``surface_material`` record per surface. Record shape only; no generator.

**A material with no texture set is a schema error, not a default.** ``texture_set_id`` is a
required field of every record, and :func:`require_texture_set` refuses one that does not name
a published set. The texture sets themselves are produced by the texture lane; this package
does not know any, and does not make any up.

Rotation is in microradians, in ``[0, 6283185]``, which is one turn less the part of a
microradian that 2 pi does not fill. Proportions are in millionths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar.errors import UnresolvedReferenceError
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.records import (
    require_identity,
    require_integer,
    require_key,
    require_record,
    require_text,
)

__all__ = [
    "MAXIMUM_ROTATION_URAD",
    "MILLIONTHS",
    "STAGE",
    "STAGE_ID",
    "STAGE_VERSION",
    "SurfaceMaterialRecord",
    "require_texture_set",
    "validate_surface_material",
]

STAGE_ID: Final = "material"
STAGE_VERSION: Final = 1
MILLIONTHS: Final = 1_000_000
MAXIMUM_ROTATION_URAD: Final = 6_283_185


@dataclass(frozen=True, slots=True)
class SurfaceMaterialRecord:
    RECORD_KIND: ClassVar[str] = "city.surface_material"
    RECORD_VERSION: ClassVar[int] = 1

    building_identity: str
    edge_ordinal: int
    #: A key into the material catalog.
    material: str
    texture_set_id: str
    uv_scale_millionths: int
    uv_rotation_urad: int
    course_module_mm: int
    mortar_module_mm: int
    soiling_gradient_millionths: int
    base_weathering_millionths: int
    reveal_darkening_millionths: int


def validate_surface_material(candidate: object) -> None:
    record = require_record(candidate, SurfaceMaterialRecord)
    require_identity("building_identity", record.building_identity)
    require_integer("edge_ordinal", record.edge_ordinal, minimum=0)
    require_key("material", record.material)
    require_text("texture_set_id", record.texture_set_id)
    require_integer("uv_scale_millionths", record.uv_scale_millionths, minimum=1)
    require_integer(
        "uv_rotation_urad", record.uv_rotation_urad, minimum=0, maximum=MAXIMUM_ROTATION_URAD
    )
    require_integer("course_module_mm", record.course_module_mm, minimum=0)
    require_integer("mortar_module_mm", record.mortar_module_mm, minimum=0)
    for name in (
        "soiling_gradient_millionths",
        "base_weathering_millionths",
        "reveal_darkening_millionths",
    ):
        require_integer(name, getattr(record, name), minimum=0, maximum=MILLIONTHS)


def require_texture_set(record: SurfaceMaterialRecord, published: frozenset[str]) -> None:
    """The record's texture set exists among ``published``, or the record is refused."""
    if record.texture_set_id not in published:
        raise UnresolvedReferenceError(
            f"texture set {record.texture_set_id!r} is not published; "
            "a material with no texture set is a schema error, not a default"
        )


STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, (SurfaceMaterialRecord, validate_surface_material))
