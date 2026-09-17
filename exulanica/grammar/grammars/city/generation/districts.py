"""The districts generator: one district over everything the terrain covers.

This version divides a city into exactly one district, whose boundary is the rectangle the
terrain patches cover, counter-clockwise from the south-west corner. A city of several districts
needs a partition rule this version does not have. The district states the side of the road, which
nothing chooses: ``driving_side`` is required, so an unbound city never reaches this stage.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

from exulanica.grammar.contract import StageContext
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.grammars.city import districts, terrain
from exulanica.grammar.grammars.city.generation.stage import (
    GeneratorStage,
    covering,
    derived,
    prior_records,
)

__all__ = ["STAGE"]

_DISTRICT: Final = 0


def _generate(context: StageContext) -> Iterator[districts.DistrictRecord]:
    patches = prior_records(context, terrain.STAGE_ID, terrain.TerrainRecord)
    if not patches:
        raise InvalidRecordError("the districts stage divides the terrain, and there is none")
    ground = covering(*(patch.extent for patch in patches))
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
