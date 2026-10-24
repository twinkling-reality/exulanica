"""Where a being put down at a point would stand: the walking node its society would take it in at.

A creature is made where it will stand. Before it is placed, the page asks where a being put down
near a point would be taken in, so the stand drawn under the creature is where the society puts it,
and Place moves nothing: the walking node of the society's latest input nearest the point, by
:func:`~exulanica.world.society_planner.open_node_near`'s rules (no activity's place, an edge, and
nobody standing at or on the way to it, first among the nodes nobody waiting would be in the way
at), with everybody the society holds now. The answer reads the moment it is asked: a being that
walks there before the creature is placed may take the node, and the society then takes the
creature in at the next one, as it would any being placed there.

A walking node holds a position on the region's ground plane and no height. Where the world's ground
states the height a thing placed at a point rests at (a town's street surface, a site's surface, a
plane's elevation: :func:`~exulanica.world.thing_landing_source.prepare_landing_in_region`), the
stand names that height at its node, so a creature and the things placed beside it stand on one
surface. Pure: nothing is read from a connection and nothing is written.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

from exulanica.world.society_planner import open_node_near

__all__ = ["STAND_PROFILE", "stand_near"]

STAND_PROFILE: Final = "exulanica.society-stand/v1"


def stand_near(
    document: Mapping[str, Any],
    people: Sequence[dict[str, Any]],
    point: tuple[int, int],
    rest: Callable[[tuple[int, int]], int] | None = None,
    *,
    outdoors: bool = False,
) -> dict[str, Any] | None:
    """The walking node of ``document`` a being put down at ``point`` would be taken in at, with
    its position and the height a thing rests at there by ``rest`` (null where the ground states
    none), among ``people``; None where the input has none open, or is unavailable. ``outdoors``
    where the society takes a placed being in outdoors only (never at a door's node,
    :func:`~exulanica.world.society_planner.takes_in_outdoors`), as it would take this one in."""
    node = open_node_near(dict(document), list(people), list(point), outdoors=outdoors)
    if node is None:
        return None
    (position,) = (
        found["position_mm"]
        for found in document["navigation"]["nodes"]
        if found["node_id"] == node
    )
    at = (int(position[0]), int(position[1]))
    height = None if rest is None else rest(at)
    return {"node_id": node, "position_mm": list(at), "height_mm": height}
