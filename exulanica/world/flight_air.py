"""The air a flying being of a saved world flies through, as flight for beings reads it.

Flight for beings (:mod:`exulanica.movement.flight_v2`) flies a thing through an
``exulanica.air-columns/v1`` document and knows nothing of worlds. This module composes that
document from a saved world version:

- **the ground** is the area the world's society walks, read by the one reading the society uses
  (:func:`exulanica.world.society_authored_ground.read_authored_ground`): the ground's own extent
  where it states one, the society's declared area where it states none. Its columns are squares
  of the side the widest flyer's span gives (:func:`exulanica.movement.flight_v2.column_mm_for`),
  laid from the area's least corner and covering all of it;
- **the solids** are read exactly as flight v1 reads them
  (:func:`exulanica.world.flight_input.placed_solids`): every part of every placed object from the
  world object catalog's recipe, turned, scaled and placed; an object that moves along a bounded
  path is solid everywhere its path takes it; a person's own admitted asset is one box of the bounds
  its preparation measured. An object whose geometry cannot be stated makes the air unavailable,
  named, because a solid it cannot place is air a flyer might cross;
- **a column's top** is the highest any solid reaching into the column stands above the ground's
  elevation, and 0 where none does; a solid wholly at or below the ground adds nothing;
- **the ceiling** is the flight module's.

Positions are the society's: ``[x, y]`` is the region frame's east and south (its ``x`` and ``z``),
and a height is above the ground's elevation. The air is derived, never stored: the same version
and span give the same document.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from exulanica.movement.air import solid_bounds
from exulanica.movement.fixed import ceil_div
from exulanica.movement.flight import FlightRefused
from exulanica.movement.flight_v2 import (
    AIR_COLUMNS_PROFILE,
    FLIGHT_V2_MODULE,
    AirColumns,
    FlightMinuteRefused,
    air_columns,
    column_mm_for,
)
from exulanica.world.authored_delta import AlternateVersion
from exulanica.world.flight_input import placed_solids
from exulanica.world.object_catalog import WorldObjectCatalog, world_object_catalog
from exulanica.world.society_authored_ground import SocietyGround

__all__ = ["compose_air_columns"]

_CEILING: Final = FLIGHT_V2_MODULE.value("ceiling_mm")
_MAX_COLUMNS: Final = FLIGHT_V2_MODULE.value("max_columns")


def compose_air_columns(
    *,
    world_id: str,
    version: AlternateVersion,
    ground: SocietyGround,
    asset_keys: Mapping[str, str],
    span_mm: int,
    objects: WorldObjectCatalog | None = None,
    workspace_bounds: Mapping[str, tuple[int, int, int]] | None = None,
) -> AirColumns:
    """The air over one saved world version for flyers whose widest span is ``span_mm``, or a
    refusal by name.

    ``asset_keys`` and ``workspace_bounds`` are as :func:`exulanica.world.flight_input.
    compose_flight_input` takes them. ``flight_world_too_large`` refuses a ground of more columns
    than the module flies, before any object is read; ``flight_unavailable`` names an object whose
    geometry the air cannot state."""
    if version.world_id != world_id or ground.world_id != world_id:
        raise FlightMinuteRefused(
            "flight_unavailable", "the version or its ground is another world's"
        )
    area = ground.area
    column = column_mm_for(span_mm)
    origin_x = area.centre_x_mm - area.half_width_mm
    origin_y = area.centre_z_mm - area.half_depth_mm
    columns_x = max(ceil_div(2 * area.half_width_mm, column), 1)
    columns_y = max(ceil_div(2 * area.half_depth_mm, column), 1)
    if columns_x * columns_y > _MAX_COLUMNS:
        raise FlightMinuteRefused(
            "flight_world_too_large",
            f"the air over this ground is {columns_x} by {columns_y} columns; "
            f"at most {_MAX_COLUMNS}",
        )
    try:
        read = placed_solids(
            version=version,
            ground=ground,
            asset_keys=asset_keys,
            objects=world_object_catalog() if objects is None else objects,
            workspace_bounds=workspace_bounds,
        )
    except FlightRefused as refused:
        # Flight v1's reading names the object; flight for beings refuses with its own exception.
        raise FlightMinuteRefused(refused.code, refused.detail) from refused
    tops = [0] * (columns_x * columns_y)
    for solid in read.solids:
        low, high = solid_bounds(solid)
        top = high[1] - ground.elevation_mm
        if top <= 0:
            continue
        # The columns a solid's closed bounds reach into, clipped to the air.
        first_x = max((low[0] - origin_x) // column, 0)
        last_x = min((high[0] - origin_x) // column, columns_x - 1)
        first_y = max((low[2] - origin_y) // column, 0)
        last_y = min((high[2] - origin_y) // column, columns_y - 1)
        for iy in range(first_y, last_y + 1):
            row = iy * columns_x
            for ix in range(first_x, last_x + 1):
                if tops[row + ix] < top:
                    tops[row + ix] = top
    return air_columns(
        {
            "profile": AIR_COLUMNS_PROFILE,
            "origin_mm": [origin_x, origin_y],
            "column_mm": column,
            "columns_x": columns_x,
            "columns_y": columns_y,
            "ceiling_mm": _CEILING,
            "tops_mm": tops,
        }
    )
