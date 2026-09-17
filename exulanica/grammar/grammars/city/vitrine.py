"""Vitrine: a lit interior volume behind ground-floor glazing. Record shape only; no generator.

The box is explicit: it starts ``u_start_mm`` along the face's run, is ``width_mm`` wide, sits
``sill_mm`` above the building's base, is ``height_mm`` tall and ``depth_mm`` deep behind the face.
The depth bound, 600 to 1500 mm, is the target architecture's and is checked on every record.
The fitout is explicit parts in the vitrine's own frame (``x`` along the run, ``y`` into the
building, ``z`` up from the sill); ``fitout`` is a label. ``light_level_millionths`` is the
interior's emitted light relative to the brightest the renderer shows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar import shapes
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.grammars.city.common import (
    FORM_PART_SHAPE,
    MILLIONTHS,
    FormPart,
    extent_field,
)

__all__ = [
    "SHAPE",
    "STAGE",
    "STAGE_ID",
    "STAGE_VERSION",
    "VITRINE_DEPTH_MAXIMUM_MM",
    "VITRINE_DEPTH_MINIMUM_MM",
    "VitrineRecord",
]

STAGE_ID: Final = "vitrine"
STAGE_VERSION: Final = 2
VITRINE_DEPTH_MINIMUM_MM: Final = 600
VITRINE_DEPTH_MAXIMUM_MM: Final = 1500


@dataclass(frozen=True, slots=True)
class VitrineRecord:
    RECORD_KIND: ClassVar[str] = "city.vitrine"
    RECORD_VERSION: ClassVar[int] = 2

    identity: str
    bay_identity: str
    facade_identity: str
    building_identity: str
    u_start_mm: int
    width_mm: int
    sill_mm: int
    height_mm: int
    depth_mm: int
    #: A key into the fitout catalog. A label: ``parts`` are the geometry.
    fitout: str
    light_level_millionths: int
    parts: tuple[FormPart, ...]
    extent: Extent


SHAPE: Final = shapes.RecordShape(
    VitrineRecord,
    (
        shapes.identity("identity"),
        shapes.identity("bay_identity", "city.ground_bay"),
        shapes.identity("facade_identity", "city.facade"),
        shapes.identity("building_identity", "city.massing"),
        shapes.integer("u_start_mm", 0),
        shapes.integer("width_mm", 1),
        shapes.integer("sill_mm", 0),
        shapes.integer("height_mm", 1),
        shapes.integer("depth_mm", VITRINE_DEPTH_MINIMUM_MM, VITRINE_DEPTH_MAXIMUM_MM),
        shapes.key("fitout", "fitout"),
        shapes.integer("light_level_millionths", 0, MILLIONTHS),
        shapes.records("parts", FORM_PART_SHAPE),
        extent_field(),
    ),
    identity=shapes.IdentityRule("vitrine", owner_field="bay_identity"),
    extent_field="extent",
)

STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, SHAPE)
