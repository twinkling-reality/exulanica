"""What lies behind a building's glass: a vitrine at the ground floor, a room's wall above it.

Two record shapes, no generator. Between them they close every pane a facade has, so a person
looking in sees a shop or a room and never the far side of the building.

The box is explicit: it starts ``u_start_mm`` along the face's run, is ``width_mm`` wide, sits
``sill_mm`` above the building's base, is ``height_mm`` tall and ``depth_mm`` deep behind the face.
The depth bound, 600 to 1500 mm, is the target architecture's and is checked on every record.
The fitout is explicit parts in the vitrine's own frame (``x`` along the run, ``y`` into the
building, ``z`` up from the sill); ``fitout`` is a label. ``light_level_millionths`` is the
interior's emitted light relative to the brightest the renderer shows.

**Interior backing** is the same idea one storey up and plainer. Above the ground band a facade's
openings are glazed, and behind them stands one plane per face: the near wall of the rooms behind
it, ``depth_mm`` back from the face, from ``sill_mm`` to ``sill_mm + height_mm``, across the run
from ``u_start_mm``. One plane per face and not one per window, because the rooms behind a face
are a floor of rooms and not a box per opening, and because a plane a person can never walk to
needs no more detail than closing the view. Its ``light_level_millionths`` reads as the vitrine's
does. It is inside its building, behind glass, exactly as a vitrine is.
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
    "BACKING_DEPTH_MAXIMUM_MM",
    "BACKING_DEPTH_MINIMUM_MM",
    "BACKING_SHAPE",
    "SHAPE",
    "STAGE",
    "STAGE_ID",
    "STAGE_VERSION",
    "VITRINE_DEPTH_MAXIMUM_MM",
    "VITRINE_DEPTH_MINIMUM_MM",
    "InteriorBackingRecord",
    "VitrineRecord",
]

STAGE_ID: Final = "vitrine"
STAGE_VERSION: Final = 2
VITRINE_DEPTH_MINIMUM_MM: Final = 600
VITRINE_DEPTH_MAXIMUM_MM: Final = 1500
#: A room's near wall stands at least a reveal's depth back and never crosses to the far side.
BACKING_DEPTH_MINIMUM_MM: Final = 300
BACKING_DEPTH_MAXIMUM_MM: Final = 3000


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


@dataclass(frozen=True, slots=True)
class InteriorBackingRecord:
    RECORD_KIND: ClassVar[str] = "city.interior_backing"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    facade_identity: str
    building_identity: str
    #: Along the face's run, in the face's own frame, as a vitrine states its box.
    u_start_mm: int
    width_mm: int
    sill_mm: int
    height_mm: int
    #: Back from the face's outer plane.
    depth_mm: int
    light_level_millionths: int
    extent: Extent


BACKING_SHAPE: Final = shapes.RecordShape(
    InteriorBackingRecord,
    (
        shapes.identity("identity"),
        shapes.identity("facade_identity", "city.facade"),
        shapes.identity("building_identity", "city.massing"),
        shapes.integer("u_start_mm", 0),
        shapes.integer("width_mm", 1),
        shapes.integer("sill_mm", 0),
        shapes.integer("height_mm", 1),
        shapes.integer("depth_mm", BACKING_DEPTH_MINIMUM_MM, BACKING_DEPTH_MAXIMUM_MM),
        shapes.integer("light_level_millionths", 0, MILLIONTHS),
        extent_field(),
    ),
    identity=shapes.IdentityRule("interior_backing", owner_field="facade_identity"),
    extent_field="extent",
)

STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, SHAPE, BACKING_SHAPE)
