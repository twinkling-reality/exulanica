"""Where a being put down at a point would stand: the walking node its society would take it in at.

A creature is made where it will stand. Before it is placed, the page asks where a being put down
near a point would be taken in, so the stand drawn under the creature is where the society puts it,
and Place moves nothing: the walking node of the society's latest input nearest the point, by
:func:`~exulanica.world.society_planner.open_node_near`'s rules (no activity's place, an edge, and
nobody standing at or on the way to it, first among the nodes nobody waiting would be in the way
at), with everybody the society holds now. The answer reads the moment it is asked: a being that
walks there before the creature is placed may take the node, and the society then takes the
creature in at the next one, as it would any being placed there.

A walking node holds a position on the region's ground plane and no height: the page sets the
stand on the ground it draws there. Pure: nothing is read from a connection and nothing is written.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from exulanica.world.society_planner import open_node_near

__all__ = ["STAND_PROFILE", "stand_near"]

STAND_PROFILE: Final = "exulanica.society-stand/v1"


def stand_near(
    document: Mapping[str, Any], people: Sequence[dict[str, Any]], point: tuple[int, int]
) -> dict[str, Any] | None:
    """The walking node of ``document`` a being put down at ``point`` would be taken in at, with
    its position, among ``people``; None where the input has none open, or is unavailable."""
    node = open_node_near(dict(document), list(people), list(point))
    if node is None:
        return None
    (position,) = (
        found["position_mm"]
        for found in document["navigation"]["nodes"]
        if found["node_id"] == node
    )
    return {"node_id": node, "position_mm": [int(position[0]), int(position[1])]}
