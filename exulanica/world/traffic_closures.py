"""What a town's placed things close of its traffic, under traffic rules 2 (DESIGN's ruling: a thing
in the road).

A town's receipt pins the traffic rules it was made under (``traffic_rules``); a town without the
pin was made under rules 1, where traffic reads no placed things and keeps its traffic byte for
byte. Under rules 2 a placed object whose kind blocks walking (the things a moved thing may not be
stood on, :func:`~exulanica.world.thing_landing.blocking_things`, read by the server and handed in
as footprints, so the traffic's worker imports nothing of things) and whose turned footprint stands
on a lane of the town's records is an obstacle: it closes every traffic lane it stands on, the
stretch between that lane's two junctions, and every space it stands in
(:func:`~exulanica.traffic.closures.close_network`). A thing across every lane of a street closes
the street. A being, or a kind the workspace keeps, has no footprint here and closes nothing.
People still walk round a thing as they do anywhere else; this is the traffic's reading alone.

Footprints are in the region's frame (east and south); the town's records and its traffic in the
city plan (east and north), so a point ``(x, z)`` is ``(x, -z)`` there.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any, Final

from exulanica.grammar.grammars.city.roads import LaneRecord
from exulanica.traffic.geometry import Point, convex_overlap, rectangle
from exulanica.traffic.network import RoadNetwork

__all__ = [
    "CLOSING_RULES",
    "TRAFFIC_RULES",
    "UNPINNED_RULES",
    "closures",
    "obstacles_on_lanes",
    "traffic_rules_of",
]

#: The traffic rules a town made now is pinned to.
TRAFFIC_RULES: Final = 2
#: The first traffic rules under which placed things close lanes.
CLOSING_RULES: Final = 2
#: The rules of a town whose receipt pins none: made before the rules were pinned, or under them.
UNPINNED_RULES: Final = 1

Ring = tuple[Point, ...]


def traffic_rules_of(receipt: Mapping[str, Any]) -> int:
    """The traffic rules a town's receipt pins, rules 1 where it pins none."""
    pinned = receipt.get("traffic_rules", UNPINNED_RULES)
    if type(pinned) is not int or pinned < UNPINNED_RULES:
        raise ValueError(f"a town's receipt pins no traffic rules {pinned!r}")
    return pinned


def _lane_pieces(records: Sequence[object]) -> list[tuple[str, Ring]]:
    """Each lane of the records, piece by piece, as the rectangle its width covers (plan frame)."""
    pieces = []
    for record in records:
        if not isinstance(record, LaneRecord):
            continue
        half = -(-record.width_mm // 2)
        line = [(x, y) for x, y, _ in record.centreline_mm]
        for a, b in pairwise(line):
            ring = rectangle(a, b, half, half)
            if ring is not None:
                pieces.append((record.identity, ring))
    return pieces


def obstacles_on_lanes(
    records: Sequence[object], footprints: Sequence[Sequence[tuple[int, int]]]
) -> tuple[Ring, ...]:
    """Of ``footprints``, the turned footprints of a version's placed things that block walking
    (the region's frame, east and south: ``BlockedPart.ring`` of
    :func:`~exulanica.world.thing_landing.blocking_things`), those that stand on a lane of
    ``records``, in the plan frame and in order: what a town's traffic under rules 2 reads."""
    pieces = _lane_pieces(records)
    found = set()
    for footprint in footprints:
        ring = tuple((round(x), -round(z)) for x, z in footprint)
        if any(convex_overlap(ring, piece) for _, piece in pieces):
            found.add(ring)
    return tuple(sorted(found))


def closures(
    network: RoadNetwork, records: Sequence[object], obstacles: Sequence[Ring]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The lane paths and the spaces of ``network`` the ``obstacles`` close: each traffic lane an
    obstacle stands on, and each space it stands in, in order."""
    if not obstacles:
        return (), ()
    lanes = {
        f"lane:{identity}"
        for identity, piece in _lane_pieces(records)
        if any(convex_overlap(piece, ring) for ring in obstacles)
    }
    closed = tuple(
        sorted(
            path_id
            for path_id in lanes
            if path_id in network.paths and network.paths[path_id].kind == "lane"
        )
    )
    spaces = tuple(
        sorted(
            identity
            for identity, space in network.spaces.items()
            if any(convex_overlap(space.footprint, ring) for ring in obstacles)
        )
    )
    return closed, spaces
