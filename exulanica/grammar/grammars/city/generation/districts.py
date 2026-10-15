"""The districts generator: one district over everything the terrain covers.

This version divides a city into exactly one district, whose boundary is the rectangle the
terrain patches cover, counter-clockwise from the south-west corner. A city of several districts
needs a partition rule this version does not have. The district states the side of the road, which
nothing chooses: ``driving_side`` is required, so an unbound city never reaches this stage.

**Version 2** (city version 6, a town laid on its land) runs before the terrain, which is graded
for the streets and lots laid in the district, so it reads the city's extent itself
(``city_extent_x_mm`` and ``city_extent_y_mm``, refused mid-tile as the terrain refuses them): the
same rectangle, at the frame's datum, as the land's heights are the terrain's to state.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import partial
from typing import Final

from exulanica.grammar.contract import StageContext
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city import districts, terrain
from exulanica.grammar.grammars.city.generation.stage import (
    GeneratorStage,
    covering,
    derived,
    prior_records,
)
from exulanica.grammar.grammars.city.generation.terrain import DATUM_MM, city_tiles

__all__ = ["STAGE", "STAGE_V2"]

_DISTRICT: Final = 0
#: The version that reads the city's extent rather than the terrain's patches.
STAGE_VERSION_2: Final = 2


def _ground(context: StageContext, from_extent: bool) -> Extent:
    if from_extent:
        width = derived(context, "city_extent_x_mm", _DISTRICT)
        depth = derived(context, "city_extent_y_mm", _DISTRICT)
        city_tiles(width, depth)  # type: ignore[arg-type]
        return Extent(0, 0, DATUM_MM, width, depth, DATUM_MM)  # type: ignore[arg-type]
    patches = prior_records(context, terrain.STAGE_ID, terrain.TerrainRecord)
    if not patches:
        raise InvalidRecordError("the districts stage divides the terrain, and there is none")
    return covering(*(patch.extent for patch in patches))


def _generate(
    context: StageContext, from_extent: bool = False
) -> Iterator[districts.DistrictRecord]:
    ground = _ground(context, from_extent)
    boundary = (
        (ground.min_x_mm, ground.min_y_mm),
        (ground.max_x_mm, ground.min_y_mm),
        (ground.max_x_mm, ground.max_y_mm),
        (ground.min_x_mm, ground.max_y_mm),
    )
    yield districts.DistrictRecord(
        identity=context.identity("district", context.subject_identity, _DISTRICT),
        district_ordinal=_DISTRICT,
        boundary_mm=boundary,
        driving_side=derived(context, "driving_side", _DISTRICT),  # type: ignore[arg-type]
        extent=ground,
    )


STAGE: Final = GeneratorStage(
    districts.STAGE_ID, districts.STAGE_VERSION, (districts.SHAPE,), _generate
)
#: Stage version 2: the same district, over the city's extent as its parameters state it.
STAGE_V2: Final = GeneratorStage(
    districts.STAGE_ID, STAGE_VERSION_2, STAGE.shapes, partial(_generate, from_extent=True)
)
