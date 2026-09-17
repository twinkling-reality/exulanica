"""The terrain generator: level patches, one per tile, covering the city's extent exactly.

**What it reads.** ``city_extent_x_mm`` and ``city_extent_y_mm``, the bounded work one generation
covers from the frame origin, and ``terrain_relief_mm`` and ``terrain_cell_mm``. An extent that
does not end on a tile edge is refused: a patch is exactly one tile, so a city ending mid-tile would
leave a patch half inside it.

**This version generates level ground only.** A relief above 0 needs a landform rule this version
does not have, so it is refused rather than approximated; the city's ground is at the datum,
height 0, everywhere. A level patch needs no fine sampling, so the cell is derived as the coarsest
the declared range allows that divides the tile.

Patches are emitted row by row from the south-west tile, and each patch's ordinal is its tile's.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

from exulanica.grammar.contract import StageContext
from exulanica.grammar.errors import InvalidParameterError
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city import terrain
from exulanica.grammar.grammars.city.common import TILE_SIZE_MM, tile_ordinal
from exulanica.grammar.grammars.city.descriptor import CITY_SURFACE
from exulanica.grammar.grammars.city.generation.stage import GeneratorStage, derived

__all__ = ["DATUM_MM", "STAGE", "city_tiles"]

#: The height of level ground: the frame's datum.
DATUM_MM: Final = 0
_CITY: Final = 0


def city_tiles(extent_x_mm: int, extent_y_mm: int) -> list[tuple[int, int]]:
    """Every tile the extent covers, row by row from the south-west, or a refusal mid-tile."""
    for name, value in (("city_extent_x_mm", extent_x_mm), ("city_extent_y_mm", extent_y_mm)):
        if value % TILE_SIZE_MM:
            raise InvalidParameterError(
                f"{name} is {value}, which ends mid-tile; a city is a whole number of "
                f"{TILE_SIZE_MM} mm tiles"
            )
    return [
        (tile_x, tile_y)
        for tile_y in range(extent_y_mm // TILE_SIZE_MM)
        for tile_x in range(extent_x_mm // TILE_SIZE_MM)
    ]


def _coarsest_cell() -> int:
    spec = CITY_SURFACE.parameters.get("terrain_cell_mm")
    for cell in range(spec.maximum, spec.minimum - 1, -1):
        if TILE_SIZE_MM % cell == 0:
            return cell
    raise InvalidParameterError("no terrain cell in the declared range divides the tile")


def _generate(context: StageContext) -> Iterator[terrain.TerrainRecord]:
    extent_x = derived(context, "city_extent_x_mm", _CITY)
    extent_y = derived(context, "city_extent_y_mm", _CITY)
    tiles = city_tiles(extent_x, extent_y)  # type: ignore[arg-type]
    relief = derived(context, "terrain_relief_mm", _CITY)
    if relief:
        raise InvalidParameterError(
            f"terrain_relief_mm is {relief}; this terrain stage version generates level ground "
            "only, and relief waits on a landform rule"
        )
    coarsest = _coarsest_cell()
    cell = derived(context, "terrain_cell_mm", _CITY, minimum=coarsest, maximum=coarsest)
    side = TILE_SIZE_MM // cell + 1  # type: ignore[operator]
    for tile_x, tile_y in tiles:
        ordinal = tile_ordinal(tile_x, tile_y)
        low_x, low_y = tile_x * TILE_SIZE_MM, tile_y * TILE_SIZE_MM
        yield terrain.TerrainRecord(
            identity=context.identity("terrain", context.subject_identity, ordinal),
            tile_ordinal=ordinal,
            tile_x=tile_x,
            tile_y=tile_y,
            cell_mm=cell,  # type: ignore[arg-type]
            samples_per_side=side,
            height_mm=(DATUM_MM,) * (side * side),
            slope_millionths=(0,) * (side * side),
            triangulation="sw_ne",
            extent=Extent(
                low_x, low_y, DATUM_MM, low_x + TILE_SIZE_MM, low_y + TILE_SIZE_MM, DATUM_MM
            ),
        )


STAGE: Final = GeneratorStage(terrain.STAGE_ID, terrain.STAGE_VERSION, (terrain.SHAPE,), _generate)
