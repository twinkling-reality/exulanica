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

**Stage version 3** (:func:`on_land`, which city grammar version 6 runs after the parcels) stands
the patches on the land a town is laid on: the land realized for the district's frame, graded for
the town's records (:func:`~exulanica.grammar.grammars.city.land.town_land_plan`: junctions level,
each street a ramp between its mouths, each lot level at its grade, banks at
``bank_grade_permille``, no cut or fill beyond ``cut_fill_most_mm``), and sampled at the finest
cell the declared range allows that divides the tile and lies on the land's 1 m lattice. It reads
the extent from the district. Land the town cannot be graded on is refused by name.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from functools import partial
from typing import Final

from exulanica.grammar.contract import StageContext
from exulanica.grammar.errors import InvalidParameterError, InvalidRecordError
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city import districts, terrain
from exulanica.grammar.grammars.city.common import MILLIONTHS, TILE_SIZE_MM, tile_ordinal
from exulanica.grammar.grammars.city.descriptor import CITY_SURFACE, CITY_SURFACES
from exulanica.grammar.grammars.city.generation.stage import (
    GeneratorStage,
    derived,
    prior_records,
)
from exulanica.grammar.grammars.city.land import near_land, town_frame, town_land_plan
from exulanica.grammar.landform import (
    CELL_MM,
    LandDocument,
    LandformRefused,
    grade_land,
    water_bodies,
)

__all__ = ["DATUM_MM", "STAGE", "STAGE_VERSION_3", "city_tiles", "on_land", "slopes"]

#: The height of level ground: the frame's datum.
DATUM_MM: Final = 0
_CITY: Final = 0
#: The version that stands the terrain on the land (the docstring's last section).
STAGE_VERSION_3: Final = 3


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


def slopes(heights: Sequence[int], side: int, cell: int) -> tuple[int, ...]:
    """A patch's slope field, by the terrain record's exact rule."""
    field = []
    for row in range(side):
        for column in range(side):
            here = heights[row * side + column]
            across = column + 1 if column + 1 < side else column - 1
            up = row + 1 if row + 1 < side else row - 1
            rise = max(
                abs(heights[row * side + across] - here), abs(heights[up * side + column] - here)
            )
            field.append(rise * MILLIONTHS // cell)
    return tuple(field)


def _finest_cell(context: StageContext) -> int:
    spec = CITY_SURFACES[context.grammar_version].parameters.get("terrain_cell_mm")
    for cell in range(spec.minimum, spec.maximum + 1):
        if TILE_SIZE_MM % cell == 0 and cell % CELL_MM == 0:
            return cell
    raise InvalidParameterError("no terrain cell in the declared range lies on the land's lattice")


def _on_land(context: StageContext, land: LandDocument) -> Iterator[terrain.TerrainRecord]:
    [district] = prior_records(context, districts.STAGE_ID, districts.DistrictRecord)
    tiles = city_tiles(district.extent.max_x_mm, district.extent.max_y_mm)
    finest = _finest_cell(context)
    cell: int = derived(context, "terrain_cell_mm", _CITY, minimum=finest, maximum=finest)  # type: ignore[assignment]
    bank = derived(context, "bank_grade_permille", _CITY)
    most = derived(context, "cut_fill_most_mm", _CITY)
    records = [record for emission in context.prior for record in emission.records]
    frame = town_frame([district], context.seed)
    try:
        plan = town_land_plan(records, bank_grade_permille=bank, cut_fill_most_mm=most)  # type: ignore[arg-type]
        near = grade_land(near_land(land, frame), plan, water=water_bodies(land, frame)).near
    except LandformRefused as exc:
        raise InvalidRecordError(f"[{exc.code}] {exc}") from exc
    side = TILE_SIZE_MM // cell + 1
    for tile_x, tile_y in tiles:
        ordinal = tile_ordinal(tile_x, tile_y)
        low_x, low_y = tile_x * TILE_SIZE_MM, tile_y * TILE_SIZE_MM
        heights = tuple(
            near.at(low_x + i * cell, low_y + j * cell) for j in range(side) for i in range(side)
        )
        yield terrain.TerrainRecord(
            identity=context.identity("terrain", context.subject_identity, ordinal),
            tile_ordinal=ordinal,
            tile_x=tile_x,
            tile_y=tile_y,
            cell_mm=cell,
            samples_per_side=side,
            height_mm=heights,
            slope_millionths=slopes(heights, side, cell),
            triangulation="sw_ne",
            extent=Extent(
                low_x, low_y, min(heights), low_x + TILE_SIZE_MM, low_y + TILE_SIZE_MM, max(heights)
            ),
        )


def on_land(land: LandDocument) -> GeneratorStage:
    """Stage version 3: the terrain of a town laid on ``land``, graded for its streets and lots."""
    return GeneratorStage(
        terrain.STAGE_ID, STAGE_VERSION_3, STAGE.shapes, partial(_on_land, land=land)
    )
