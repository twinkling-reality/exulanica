"""The ``world_id`` a world route requires, stated once for every route that takes one.

A workspace can hold several worlds, so a route that reads or changes one is told which by its
caller and has no default to fall back on. ``GET /worlds`` lists the worlds a workspace holds. The
bounds are the registry's (:data:`exulanica.world.worlds.WORLD_ID_MAX_LENGTH`), which are the
bounds every world table's CHECK states.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Query

from exulanica.world.worlds import WORLD_ID_MAX_LENGTH

__all__ = ["WorldId"]

WorldId = Annotated[str, Query(min_length=1, max_length=WORLD_ID_MAX_LENGTH)]
