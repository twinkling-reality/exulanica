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

Under rules 3 (DESIGN's ruling: a thing inside a junction) a footprint inside a junction's extent is
an obstacle too, and it closes each lane connection whose path it stands on
(:func:`closed_connections`, read against the compiled network, since the connections are
derived); over every connection of a junction it closes the junction. A town made under rules 2
keeps junctions open to its things, as it was made.

Footprints are in the region's frame (east and south); the town's records and its traffic in the
city plan (east and north), so a point ``(x, z)`` is ``(x, -z)`` there.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any, Final

from exulanica.grammar.grammars.city.roads import JunctionRecord, LaneRecord
from exulanica.traffic.geometry import Point, convex_overlap, rectangle
from exulanica.traffic.network import RoadNetwork

__all__ = [
    "CLOSING_RULES",
    "JUNCTION_RULES",
    "TRAFFIC_RULES",
    "UNPINNED_RULES",
    "closed_connections",
    "closing",
    "closures",
    "obstacles_on_lanes",
    "traffic_rules_of",
]

#: The traffic rules a town made now is pinned to.
TRAFFIC_RULES: Final = 3
#: The first traffic rules under which placed things close lanes.
CLOSING_RULES: Final = 2
#: The first traffic rules under which a placed thing inside a junction closes the connections it
#: stands on.
JUNCTION_RULES: Final = 3
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


def _junction_boxes(records: Sequence[object]) -> list[tuple[str, Ring]]:
    """Each junction of the records as the plan rectangle of its extent."""
    boxes = []
    for record in records:
        if not isinstance(record, JunctionRecord):
            continue
        e = record.extent
        boxes.append(
            (
                record.identity,
                (
                    (e.min_x_mm, e.min_y_mm),
                    (e.max_x_mm, e.min_y_mm),
                    (e.max_x_mm, e.max_y_mm),
                    (e.min_x_mm, e.max_y_mm),
                ),
            )
        )
    return boxes


def obstacles_on_lanes(
    records: Sequence[object],
    footprints: Sequence[Sequence[tuple[int, int]]],
    rules: int = CLOSING_RULES,
) -> tuple[Ring, ...]:
    """Of ``footprints``, the turned footprints of a version's placed things that block walking
    (the region's frame, east and south: ``BlockedPart.ring`` of
    :func:`~exulanica.world.thing_landing.blocking_things`), those that stand on a lane of
    ``records`` or, under ``rules`` 3, inside a junction's extent, in the plan frame and in order:
    what a town's traffic under rules 2 or 3 reads."""
    pieces = _lane_pieces(records)
    if rules >= JUNCTION_RULES:
        pieces += _junction_boxes(records)
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


def closed_connections(
    network: RoadNetwork, records: Sequence[object], obstacles: Sequence[Ring]
) -> tuple[str, ...]:
    """The lane connections of ``network`` the ``obstacles`` stand on, in order (rules 3): each
    ``connector`` path whose line, piece by piece at half the width of the lane it leaves, an
    obstacle overlaps."""
    if not obstacles:
        return ()
    widths = {
        f"lane:{record.identity}": record.width_mm
        for record in records
        if isinstance(record, LaneRecord)
    }
    found = []
    for path_id, path in network.paths.items():
        if path.kind != "connector":
            continue
        width = max((widths.get(lane, 0) for lane in path.predecessors), default=0)
        half = -(-width // 2)
        if half <= 0:
            continue
        for a, b in pairwise(path.line.points):
            ring = rectangle(a, b, half, half)
            if ring is not None and any(convex_overlap(ring, obstacle) for obstacle in obstacles):
                found.append(path_id)
                break
    return tuple(sorted(found))


def closing(
    network: RoadNetwork, records: Sequence[object], obstacles: Sequence[Ring], rules: int
) -> dict[str, list[str]]:
    """What ``obstacles`` (plan frame, :func:`obstacles_on_lanes`) close of ``network`` under
    traffic ``rules``, by the very computations the traffic reads them with (:func:`closures`,
    and under rules 3 :func:`closed_connections`): ``lanes``, the lane paths closed;
    ``segments``, the street segments every lane path of which is closed, so the street is closed
    there; ``turns``, the segment each closed connection turns into. Each in order; all empty
    under rules 1."""
    if rules < CLOSING_RULES or not obstacles:
        return {"lanes": [], "segments": [], "turns": []}
    lanes, _spaces = closures(network, records, obstacles)
    by_segment: dict[str, set[str]] = {}
    for path_id, path in network.paths.items():
        if path.kind == "lane" and path.segment:
            by_segment.setdefault(path.segment, set()).add(path_id)
    closed = set(lanes)
    segments = sorted(segment for segment, paths in by_segment.items() if paths <= closed)
    turns: set[str] = set()
    if rules >= JUNCTION_RULES:
        for path_id in closed_connections(network, records, obstacles):
            for lane in network.paths[path_id].successors:
                if network.paths[lane].segment:
                    turns.add(network.paths[lane].segment)
    return {"lanes": list(lanes), "segments": segments, "turns": sorted(turns)}
