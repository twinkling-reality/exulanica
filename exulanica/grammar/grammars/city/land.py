"""A town on its land: the grading a town's layout asks of the land it stands on.

The city grammar lays a town out in plan. On land the layout then grades the land
(:mod:`exulanica.grammar.landform.grading`) so that what its people walk stays within the place
contract's one step per edge and every lot stands level at its own door:

* every **junction** is level, at a height read over the whole street network before any street
  is graded: the midpoint of the network's upper and lower envelopes over the natural land, so no
  street between two junctions has to climb faster than its grade (the rule a single corridor is
  graded by, over the network);
* every **street segment** (its carriageway and both footways: the segment's extent in plan) is a
  corridor graded along its centre line between its two junctions, no steeper than one step over
  the longest footway station spacing of its kerbs, less a rounding margin;
* every **lot** is a pad, level at the height of its street's centre line opposite its threshold
  (where its primary frontage is entered), so a row of lots steps down a sloping street lot by lot
  and every front door meets its footway; a lot's cells under a street keep the street's grade;
* the **entry** is where the town's arrival stands: every lot's door must be reached from it over
  ground walked within the walking grade.

Steeper natural ground lies only behind and between lots, banked at the bank grade or held by a
retaining wall where a bank does not fit. A town whose land cannot be graded so is refused by name
(the grading's refusals).

Every figure is the caller's (:class:`TownGrading`): the footway station spacing is the town
routine's, the step per edge the place contract's, the bank grade and the cut and fill bound the
land's. The town's frame keeps its origin at the south-west corner of its district at height 0,
the land's datum, the sea's level. Pure and integer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Final

from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import Extent, integer_sqrt
from exulanica.grammar.grammars.city.common import MILLIONTHS
from exulanica.grammar.grammars.city.corners import (
    corner_box,
    footway_rise_mm,
    junction_fill_box,
    strip_box,
)
from exulanica.grammar.grammars.city.districts import DistrictRecord
from exulanica.grammar.grammars.city.parcels import ParcelRecord
from exulanica.grammar.grammars.city.roads import JunctionRecord, LaneRecord
from exulanica.grammar.grammars.city.streets import (
    BlockRecord,
    CrossingRecord,
    CurbEdgeRecord,
    StreetNodeRecord,
    StreetRecord,
    StreetSegmentRecord,
)
from exulanica.grammar.landform import (
    CELL_MM,
    Corridor,
    GradedLand,
    GradingPlan,
    LandDocument,
    LandformRefused,
    NearLand,
    Pad,
    WorldFrame,
    grade_land,
    realize_near,
    water_bodies,
)

__all__ = [
    "ROUNDING_MARGIN_MM",
    "StreetProfile",
    "TownGrading",
    "door_of",
    "footway_surface_at",
    "footway_top_at",
    "frontage_top",
    "grade_town",
    "kerb_height_at",
    "near_land",
    "node_levels",
    "street_profiles",
    "streets_on_land",
    "town_frame",
    "town_grading_plan",
    "town_land_plan",
]

#: A point of a record's line, ``(x, y, z)``, and a plan rectangle ``(x0, y0, x1, y1)``.
Point3 = tuple[int, int, int]
Rect = tuple[int, int, int, int]

#: Heights are floored at both ends of an edge, so a street graded exactly at the step could climb
#: a millimetre more over a station; the margin keeps every edge strictly within it.
ROUNDING_MARGIN_MM: Final = 2
#: Beyond any town: a junction with no leg leaving it on one side is not bounded on that side.
_FAR_MM: Final = 1 << 60


@dataclass(frozen=True, slots=True)
class TownGrading:
    """The figures a town is graded with, each from where it is stated."""

    #: The footway station spacing the town's place lays stations at (its routine's catalog).
    station_mm: int
    #: The most one walking edge climbs (the place contract's step).
    step_mm: int
    #: The steepest a bank beside a level lot or street may stand, per mille.
    bank_grade_permille: int
    #: The most a lot, a street or a bank may cut or fill the land.
    cut_fill_most_mm: int


def _rect(extent: Extent) -> tuple[int, int, int, int]:
    return extent.min_x_mm, extent.min_y_mm, extent.max_x_mm, extent.max_y_mm


def _along_x(segment: StreetSegmentRecord) -> bool:
    (x0, y0, _z0), (x1, y1, _z1) = segment.centreline_mm[0], segment.centreline_mm[-1]
    return abs(x1 - x0) >= abs(y1 - y0)


def _within(low: int, high: int, value: int) -> int:
    """The lattice point nearest ``value`` at or below it that lies within [low, high]."""
    first, last = -(-low // CELL_MM) * CELL_MM, high // CELL_MM * CELL_MM
    return min(max(value // CELL_MM * CELL_MM, first), last)


def _station_spacing(length_mm: int, station_mm: int) -> int:
    """The longest spacing between stations along a kerb of ``length_mm``, as the town's place
    lays them (one every ``station_mm`` or a little more)."""
    count = max(1, length_mm // station_mm)
    return -(-length_mm // count)


def _kerb_length(curb: CurbEdgeRecord) -> int:
    return sum(
        abs(b[0] - a[0]) + abs(b[1] - a[1])
        for a, b in zip(curb.kerb_line_mm, curb.kerb_line_mm[1:], strict=False)
    )


def _street_grade(
    segment: StreetSegmentRecord, curbs: Sequence[CurbEdgeRecord], station_mm: int, step_mm: int
) -> int:
    """The steepest a segment may climb, per mille: one step, less the rounding margin, over the
    longest station spacing of its kerbs."""
    lengths = [_kerb_length(curb) for curb in curbs] or [segment.length_mm]
    spacing = max(_station_spacing(length, station_mm) for length in lengths)
    return max(1, (step_mm - ROUNDING_MARGIN_MM) * 1000 // spacing)


def _corridor(
    segment: StreetSegmentRecord, curbs: Sequence[CurbEdgeRecord], figures: TownGrading
) -> Corridor:
    return Corridor(
        id=f"street {segment.identity}",
        rect_mm=_rect(segment.extent),
        axis="x" if _along_x(segment) else "y",
        grade_permille=_street_grade(segment, curbs, figures.station_mm, figures.step_mm),
    )


def _on_centre(corridor: Corridor, x: int, y: int) -> tuple[int, int]:
    """A point projected onto a corridor's centre line, on a lattice point within the corridor."""
    x0, y0, x1, y1 = corridor.rect_mm
    if corridor.axis == "x":
        return _within(x0, x1, x), _within(y0, y1, (y0 + y1) // 2)
    return _within(x0, x1, (x0 + x1) // 2), _within(y0, y1, y)


def door_of(parcel: ParcelRecord) -> tuple[int, int]:
    """Where a lot is entered: its threshold along its primary frontage edge, from that edge's
    start vertex."""
    ring = parcel.boundary_mm
    edge = parcel.frontages[0].edge_ordinal
    (ax, ay), (bx, by) = ring[edge], ring[(edge + 1) % len(ring)]
    length = abs(bx - ax) + abs(by - ay)
    along = min(parcel.threshold_offset_mm, length)
    return (
        ax + (bx - ax) * along // max(1, length),
        ay + (by - ay) * along // max(1, length),
    )


def town_frame(records: Sequence[object], seed: str) -> WorldFrame:
    """A town's frame: its district's extent from the origin, its land realized with ``seed``."""
    district = next(r for r in records if isinstance(r, DistrictRecord))
    _x0, _y0, x1, y1 = _rect(district.extent)
    return WorldFrame(width_mm=x1, depth_mm=y1, seed=seed)


def _junctions(
    segments: Sequence[StreetSegmentRecord],
    corridors: Mapping[str, Corridor],
    nodes: Mapping[str, StreetNodeRecord],
    near: NearLand,
) -> list[Pad]:
    """Every junction as a level pad over the box its streets share, at the midpoint of the street
    network's upper and lower envelopes over the natural land, so each street can climb between
    its two junctions within its grade."""
    boxes: dict[str, list[int]] = {}
    for node_id, node in nodes.items():
        meeting = [
            corridors[s.identity]
            for s in segments
            if node_id in (s.start_node_identity, s.end_node_identity)
        ]
        across_x = [c.rect_mm for c in meeting if c.axis == "y"]
        across_y = [c.rect_mm for c in meeting if c.axis == "x"]
        boxes[node_id] = [
            min((r[0] for r in across_x), default=node.x_mm - CELL_MM),
            min((r[1] for r in across_y), default=node.y_mm - CELL_MM),
            max((r[2] for r in across_x), default=node.x_mm + CELL_MM),
            max((r[3] for r in across_y), default=node.y_mm + CELL_MM),
        ]
    rises: list[tuple[str, str, int]] = []
    for segment in segments:
        corridor = corridors[segment.identity]
        a, b = segment.start_node_identity, segment.end_node_identity
        low, high = (0, 2) if corridor.axis == "x" else (1, 3)
        first, second = sorted((a, b), key=lambda n: boxes[n][low])
        free = max(0, boxes[second][low] - boxes[first][high])
        rises.append((a, b, max(0, corridor.grade_permille * free // 1000 - ROUNDING_MARGIN_MM)))
    levels = _network_levels({key: _natural_at(near, node) for key, node in nodes.items()}, rises)
    return [
        Pad(
            id=f"junction {node_id}",
            rect_mm=(boxes[node_id][0], boxes[node_id][1], boxes[node_id][2], boxes[node_id][3]),
            level_mm=levels[node_id],
        )
        for node_id in sorted(nodes)
    ]


def _natural_at(near: NearLand, node: StreetNodeRecord) -> int:
    """The natural land at a node, on the lattice point at or below it within the land."""
    x0, y0, x1, y1 = near.domain_mm
    return near.at(
        min(max(node.x_mm // CELL_MM * CELL_MM, x0), x1),
        min(max(node.y_mm // CELL_MM * CELL_MM, y0), y1),
    )


def _network_levels(
    natural: Mapping[str, int], rises: Sequence[tuple[str, str, int]]
) -> dict[str, int]:
    """Each node's level: the midpoint of the network's upper and lower envelopes over the natural
    land, so every street can climb between its two nodes within the rise it allows."""
    upper, lower = dict(natural), dict(natural)
    changed = True
    while changed:
        changed = False
        for a, b, rise in rises:
            for here, there in ((a, b), (b, a)):
                if upper[here] + rise < upper[there]:
                    upper[there], changed = upper[here] + rise, True
                if lower[here] - rise > lower[there]:
                    lower[there], changed = lower[here] - rise, True
    return {key: (upper[key] + lower[key]) // 2 for key in natural}


def town_grading_plan(
    records: Sequence[object],
    arrival_mm: tuple[int, int],
    figures: TownGrading,
    near: NearLand,
) -> GradingPlan:
    """The grading a town's records ask of its land, realized as ``near``, with its arrival at
    ``arrival_mm``."""
    segments = sorted(
        (r for r in records if isinstance(r, StreetSegmentRecord)),
        key=lambda s: (s.street_identity, int(s.segment_ordinal)),
    )
    curbs: dict[str, list[CurbEdgeRecord]] = {}
    for curb in (r for r in records if isinstance(r, CurbEdgeRecord)):
        curbs.setdefault(curb.segment_identity, []).append(curb)
    corridors = {s.identity: _corridor(s, curbs.get(s.identity, ()), figures) for s in segments}
    by_curb: Mapping[str, Corridor] = {
        curb.identity: corridors[segment]
        for segment, held in curbs.items()
        if segment in corridors
        for curb in held
    }
    parcels = sorted(
        (r for r in records if isinstance(r, ParcelRecord)),
        key=lambda p: (p.block_identity, p.parcel_ordinal),
    )
    nodes = {r.identity: r for r in records if isinstance(r, StreetNodeRecord)}
    pads = _junctions(segments, corridors, nodes, near)
    for parcel in parcels:
        if not parcel.frontages or parcel.frontages[0].curb_identity not in by_curb:
            raise LandformRefused(
                f"lot {parcel.identity} fronts no street the town lays, so no door sets its level",
                code="landform_unreachable",
            )
        xs = [x for x, _ in parcel.boundary_mm]
        ys = [y for _, y in parcel.boundary_mm]
        pads.append(
            Pad(
                id=f"lot {parcel.identity}",
                rect_mm=(min(xs), min(ys), max(xs), max(ys)),
                door_mm=_on_centre(by_curb[parcel.frontages[0].curb_identity], *door_of(parcel)),
            )
        )
    graded = tuple(corridors[s.identity] for s in segments)
    return GradingPlan(
        corridors=graded,
        pads=tuple(pads),
        entry_mm=(arrival_mm[0] // CELL_MM * CELL_MM, arrival_mm[1] // CELL_MM * CELL_MM),
        bank_grade_permille=figures.bank_grade_permille,
        cut_fill_most_mm=figures.cut_fill_most_mm,
        # Every street is walked within its own grade; a door is reached over ground no steeper
        # than the steepest a street was allowed.
        walk_grade_permille=max(corridor.grade_permille for corridor in graded),
    )


def grade_town(
    land: LandDocument,
    records: Sequence[object],
    seed: str,
    arrival_mm: tuple[int, int],
    figures: TownGrading,
) -> GradedLand:
    """Realize a town's near land with ``seed`` and grade it for its records, or refuse it by name.
    The land's own water (a sea, lakes, a cascade's pools and falls) is held as the lots are."""
    frame = town_frame(records, seed)
    near = realize_near(land, frame)
    return grade_land(
        near, town_grading_plan(records, arrival_mm, figures, near), water=water_bodies(land, frame)
    )


# -- version 6: a town laid on its land ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StreetProfile:
    """A segment's crown along its axis (``axis`` 0 for x, 1 for y): level at ``low_level_mm`` up to
    ``low_mm``, a straight climb to ``high_level_mm`` at ``high_mm``, and level beyond. ``low_mm``
    and ``high_mm`` are its mouths, where its strip starts and ends (at each end, the kerb end
    nearer the middle), so its junctions and every corner round them stand level."""

    axis: int
    low_mm: int
    high_mm: int
    low_level_mm: int
    high_level_mm: int

    def at(self, t: int) -> int:
        """The crown's height at ``t`` along the axis."""
        if t <= self.low_mm:
            return self.low_level_mm
        if t >= self.high_mm:
            return self.high_level_mm
        rise = self.high_level_mm - self.low_level_mm
        return self.low_level_mm + rise * (t - self.low_mm) // (self.high_mm - self.low_mm)

    def bends(self, a: int, b: int) -> list[int]:
        """Where the crown bends strictly between ``a`` and ``b`` along the axis, from ``a``."""
        if self.low_level_mm == self.high_level_mm:
            return []
        inside = [t for t in (self.low_mm, self.high_mm) if min(a, b) < t < max(a, b)]
        return inside if a <= b else inside[::-1]


def _street_parts(
    records: Sequence[object],
) -> tuple[
    dict[str, StreetNodeRecord], list[StreetSegmentRecord], dict[str, dict[str, CurbEdgeRecord]]
]:
    nodes = {r.identity: r for r in records if isinstance(r, StreetNodeRecord)}
    segments = [r for r in records if isinstance(r, StreetSegmentRecord)]
    curbs: dict[str, dict[str, CurbEdgeRecord]] = {}
    for curb in (r for r in records if isinstance(r, CurbEdgeRecord)):
        curbs.setdefault(curb.segment_identity, {})[curb.side] = curb
    return nodes, segments, curbs


def _mouths(
    segment: StreetSegmentRecord,
    curbs: Mapping[str, CurbEdgeRecord],
    nodes: Mapping[str, StreetNodeRecord],
) -> tuple[int, int, int, str, str]:
    """``(axis, low, high, low node, high node)``: where the segment's strip starts and ends along
    its axis, and the node at each end. A kerb line runs from its segment's start node toward its
    end node; at each end the kerb end nearer the middle is the mouth."""
    axis = 0 if _along_x(segment) else 1
    start, end = nodes[segment.start_node_identity], nodes[segment.end_node_identity]
    at_start, at_end = (start.x_mm, start.y_mm)[axis], (end.x_mm, end.y_mm)[axis]
    firsts = [curb.kerb_line_mm[0][axis] for curb in curbs.values()] or [at_start]
    lasts = [curb.kerb_line_mm[-1][axis] for curb in curbs.values()] or [at_end]
    if at_start <= at_end:
        return axis, max(firsts), min(lasts), start.identity, end.identity
    return axis, max(lasts), min(firsts), end.identity, start.identity


def node_levels(
    records: Sequence[object], near: NearLand, station_mm: int, step_mm: int
) -> dict[str, int]:
    """Each street node's level on ``near``'s natural land: the network's envelope midpoint, each
    segment rising between its mouths by at most one step, less the rounding margin, per station
    spacing of its kerbs."""
    nodes, segments, curbs = _street_parts(records)
    rises = []
    for segment in segments:
        sides = curbs.get(segment.identity, {})
        _axis, low, high, _low_node, _high_node = _mouths(segment, sides, nodes)
        grade = _street_grade(segment, list(sides.values()), station_mm, step_mm)
        rise = max(0, grade * max(0, high - low) // 1000 - ROUNDING_MARGIN_MM)
        rises.append((segment.start_node_identity, segment.end_node_identity, rise))
    return _network_levels({key: _natural_at(near, node) for key, node in nodes.items()}, rises)


def street_profiles(records: Sequence[object]) -> dict[str, StreetProfile]:
    """Each segment's profile, read from its records: its nodes' heights and its kerbs' ends."""
    nodes, segments, curbs = _street_parts(records)
    profiles = {}
    for segment in segments:
        axis, low, high, low_node, high_node = _mouths(
            segment, curbs.get(segment.identity, {}), nodes
        )
        profiles[segment.identity] = StreetProfile(
            axis, low, max(low, high), nodes[low_node].z_mm, nodes[high_node].z_mm
        )
    return profiles


def _lift(line: Sequence[tuple[int, int, int]], profile: StreetProfile) -> tuple[Point3, ...]:
    """A line of a level street raised onto ``profile``, with a point wherever the crown bends."""
    axis = profile.axis

    def raised(x: int, y: int, z: int) -> Point3:
        return x, y, z + profile.at((x, y)[axis])

    points = [raised(*line[0])]
    for a, b in pairwise(line):
        for t in profile.bends(a[axis], b[axis]):
            run, into = b[axis] - a[axis], t - a[axis]
            other = a[1 - axis] + (b[1 - axis] - a[1 - axis]) * into // run
            plan = (t, other) if axis == 0 else (other, t)
            points.append(raised(*plan, a[2] + (b[2] - a[2]) * into // run))
        points.append(raised(*b))
    return tuple(points)


def _point_extent(node: StreetNodeRecord, levels: Mapping[str, int]) -> Extent:
    z = levels[node.identity]
    return Extent(node.x_mm, node.y_mm, z, node.x_mm, node.y_mm, z)


def _covering(*extents: Extent) -> Extent:
    return Extent(
        min(extent.min_x_mm for extent in extents),
        min(extent.min_y_mm for extent in extents),
        min(extent.min_z_mm for extent in extents),
        max(extent.max_x_mm for extent in extents),
        max(extent.max_y_mm for extent in extents),
        max(extent.max_z_mm for extent in extents),
    )


def _line_extent(points: Sequence[Point3]) -> Extent:
    xs, ys, zs = zip(*points, strict=True)
    return Extent(min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def streets_on_land(records: Sequence[object], levels: Mapping[str, int]) -> list[object]:
    """A level street network's records (every height at the datum) laid on its nodes' ``levels``:
    each node at its level, each segment's lines raised onto its profile, and every extent and
    grade that follows from them read again by the rules that made them."""
    nodes = {
        r.identity: replace(r, z_mm=levels[r.identity], extent=_point_extent(r, levels))
        for r in records
        if isinstance(r, StreetNodeRecord)
    }
    raised: dict[str, object] = dict(nodes)
    profiles = street_profiles([nodes.get(getattr(r, "identity", ""), r) for r in records])
    for record in records:
        if isinstance(record, CurbEdgeRecord):
            raised[record.identity] = replace(
                record, kerb_line_mm=_lift(record.kerb_line_mm, profiles[record.segment_identity])
            )
    curbs = {key: value for key, value in raised.items() if isinstance(value, CurbEdgeRecord)}
    boxes = {key: strip_box(curb) for key, curb in curbs.items()}
    for key, curb in curbs.items():
        for next_identity in curb.next_curb_identity:
            box = corner_box(curb, curbs[next_identity])
            if box is not None:
                boxes[key] = _covering(boxes[key], box)
                boxes[next_identity] = _covering(boxes[next_identity], box)
    for key, curb in curbs.items():
        raised[key] = replace(curb, extent=boxes[key])
    lanes: dict[str, list[Extent]] = {}
    for record in records:
        if isinstance(record, LaneRecord):
            line = _lift(record.centreline_mm, profiles[record.segment_identity])
            low, high = min(z for *_xy, z in line), max(z for *_xy, z in line)
            extent = replace(record.extent, min_z_mm=low, max_z_mm=high)
            raised[record.identity] = replace(record, centreline_mm=line, extent=extent)
            lanes.setdefault(record.segment_identity, []).append(extent)
        elif isinstance(record, CrossingRecord):
            profile = profiles[record.segment_identity]
            lift = profile.at(record.line_mm[0][profile.axis])
            low, high = record.extent.min_z_mm + lift, record.extent.max_z_mm + lift
            raised[record.identity] = replace(
                record,
                line_mm=tuple((x, y, z + lift) for x, y, z in record.line_mm),
                extent=replace(record.extent, min_z_mm=low, max_z_mm=high),
            )
    by_side: dict[str, dict[str, CurbEdgeRecord]] = {}
    for curb in (raised[key] for key in curbs):
        by_side.setdefault(curb.segment_identity, {})[curb.side] = curb  # type: ignore[attr-defined]
    segments: dict[str, StreetSegmentRecord] = {}
    for record in records:
        if isinstance(record, StreetSegmentRecord):
            line = _lift(record.centreline_mm, profiles[record.identity])
            sides = by_side[record.identity]
            segments[record.identity] = replace(
                record,
                centreline_mm=line,
                extent=_covering(
                    _line_extent(line),
                    *(curb.extent for curb in sides.values()),
                    *lanes.get(record.identity, ()),
                ),
            )
    raised.update(segments)
    for record in records:
        if isinstance(record, StreetRecord):
            raised[record.identity] = replace(
                record,
                extent=_covering(*(segments[key].extent for key in record.segment_identities)),
            )
        elif isinstance(record, BlockRecord):
            grade = max(
                strip_box(curb).max_z_mm
                for curb in curbs.values()
                if record.identity in curb.block_identity
            )
            raised[record.identity] = replace(
                record,
                grade_elevation_mm=grade,
                extent=replace(record.extent, min_z_mm=grade, max_z_mm=grade),
            )
        elif isinstance(record, JunctionRecord):
            box = junction_fill_box(
                nodes[record.node_identity],
                [segments[key] for key in record.segment_identities],
                lambda key: by_side[key],
                raised.get,
            )
            if box is None:
                raise InvalidRecordError(f"junction {record.identity} has a leg without curbs")
            raised[record.identity] = replace(record, extent=box)
    return [raised.get(getattr(record, "identity", ""), record) for record in records]


def _round_div(numerator: int, denominator: int) -> int:
    """Integer division rounded half away from zero."""
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    quotient, remainder = divmod(abs(numerator), denominator)
    if 2 * remainder >= denominator:
        quotient += 1
    return quotient if numerator >= 0 else -quotient


def _ceil_distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    dx, dy = a[0] - b[0], a[1] - b[1]
    squared = dx * dx + dy * dy
    root = integer_sqrt(squared)
    return root + (root * root < squared)


def footway_surface_at(curb: CurbEdgeRecord, point: tuple[int, int]) -> int:
    """The footway's height under ``point``, read as a town's walking graph reads it: the point
    projected onto the kerb line (the nearest point, the first on a tie), the kerb line's height
    there between its piece's two points rounded half away from zero, the kerb, and the footway's
    rise out to the point, which stops at the footway's back edge. A door states its step above
    this height, and the walking graph holds the step to it, so the rule is read the same way here
    (a test holds the two readings equal)."""
    points: list[tuple[int, int]] = []
    heights: list[int] = []
    for x, y, z in curb.kerb_line_mm:
        if not points or points[-1] != (x, y):
            points.append((x, y))
            heights.append(z)
    best: tuple[int, int, int] | None = None
    start = 0
    for index, (a, b) in enumerate(pairwise(points)):
        length = _ceil_distance(a, b)
        dx, dy = b[0] - a[0], b[1] - a[1]
        squared = dx * dx + dy * dy
        t = max(0, min(squared, (point[0] - a[0]) * dx + (point[1] - a[1]) * dy))
        foot = (a[0] + _round_div(dx * t, squared), a[1] + _round_div(dy * t, squared))
        across_x, across_y = point[0] - foot[0], point[1] - foot[1]
        gap = across_x * across_x + across_y * across_y
        into = _round_div(length * t, squared)
        if best is None or (gap, start + into) < best[:2]:
            best = (gap, start + into, index)
        start += length
    assert best is not None
    gap, along, _index = best
    start = 0
    for index, (a, b) in enumerate(pairwise(points)):
        length = _ceil_distance(a, b)
        if along <= start + length or index == len(points) - 2:
            into = max(0, min(length, along - start))
            kerb = heights[index] + _round_div((heights[index + 1] - heights[index]) * into, length)
            break
        start += length
    out = max(0, min(curb.footway_width_mm, integer_sqrt(gap) - curb.kerb_width_mm))
    return kerb + curb.kerb_height_mm + out * curb.footway_crossfall_millionths // MILLIONTHS


def kerb_height_at(curb: CurbEdgeRecord, point: tuple[int, int]) -> int:
    """The kerb line's height opposite ``point``: its footway's height there, at the kerb top's
    back edge, less the kerb (:func:`footway_surface_at`'s reading of the line)."""
    on_line = _nearest_on_line(curb, point)
    return footway_surface_at(curb, on_line) - curb.kerb_height_mm


def _nearest_on_line(curb: CurbEdgeRecord, point: tuple[int, int]) -> tuple[int, int]:
    line = curb.kerb_line_mm
    axis = 0 if line[0][0] != line[-1][0] else 1
    low, high = sorted((line[0][axis], line[-1][axis]))
    t = min(max(point[axis], low), high)
    return (t, line[0][1]) if axis == 0 else (line[0][0], t)


def frontage_top(curb: CurbEdgeRecord, edge: tuple[tuple[int, int], tuple[int, int]]) -> int:
    """The highest the footway stands along a lot's frontage edge, at its back edge: read at the
    edge's two ends and wherever the kerb line bends between them."""
    (ax, ay), (bx, by) = edge
    axis = 0 if ax != bx else 1
    low, high = sorted(((ax, ay)[axis], (bx, by)[axis]))
    places = [(ax, ay), (bx, by)]
    for x, y, _z in curb.kerb_line_mm:
        if low < (x, y)[axis] < high:
            places.append((x, ay) if axis == 0 else (ax, y))
    return max(footway_surface_at(curb, place) for place in places)


def footway_top_at(curb: CurbEdgeRecord, point: tuple[int, int]) -> int:
    """The footway's top at its back edge opposite ``point``: the kerb line's height there, the
    kerb, and the footway's whole rise."""
    return kerb_height_at(curb, point) + curb.kerb_height_mm + footway_rise_mm(curb)


_NEAR_HELD: Final = 2
_near: dict[tuple[str, WorldFrame], NearLand] = {}


def near_land(land: LandDocument, frame: WorldFrame) -> NearLand:
    """``land`` realized near ``frame``, the last few kept: a town's streets and its terrain read
    the same land, and realizing it is most of the time a town on land takes."""
    key = (land.sha256, frame)
    held = _near.get(key)
    if held is None:
        if len(_near) >= _NEAR_HELD:
            _near.clear()
        held = _near[key] = realize_near(land, frame)
    return held


def _across(
    segment: StreetSegmentRecord, curbs: Mapping[str, CurbEdgeRecord], axis: int
) -> tuple[int, int]:
    """A street's width across ``axis``: its carriageway between its kerb lines and each footway
    out to its back edge (not the corners its curbs turn, which are its junctions')."""
    centre = segment.centreline_mm[0][1 - axis]
    low = high = centre
    for curb in curbs.values():
        kerb = curb.kerb_line_mm[0][1 - axis]
        reach = curb.kerb_width_mm + curb.footway_width_mm
        low, high = (
            min(low, kerb - (reach if kerb < centre else 0)),
            max(high, kerb + (reach if kerb > centre else 0)),
        )
    return low, high


def _band(axis: int, side: tuple[int, int], a: int, b: int) -> Rect:
    """The rectangle from ``a`` to ``b`` along ``axis``, ``side`` across it."""
    low, high = min(a, b), max(a, b)
    return (low, side[0], high, side[1]) if axis == 0 else (side[0], low, side[1], high)


def town_land_plan(
    records: Sequence[object], *, bank_grade_permille: int, cut_fill_most_mm: int
) -> GradingPlan:
    """The grading a town laid on its land asks: each junction level at its node's height along
    each leg out to that leg's mouth (a pad per leg, so no junction reaches over a street's ramp),
    each segment a ramp between its mouths, each lot level at its grade with its door on its
    street's centre line, and the entry at the first node. Doors are reached over ground no
    steeper than the steepest street.

    A leg's pad stands across its street's width only as far as the mouths of the legs leaving
    its node the other way: a street wider on one side than its crossing street's kerbs reach
    would otherwise hold level ground where that street has begun to climb."""
    nodes, segments, curbs = _street_parts(records)
    profiles = street_profiles(records)
    legs: dict[str, list[tuple[int, tuple[int, int], int]]] = {key: [] for key in nodes}
    #: Per node and axis, the nearest mouths either side of the node along that axis.
    bounds: dict[tuple[str, int], tuple[int, int]] = {}
    ramps: list[Corridor] = []
    for segment in segments:
        profile = profiles[segment.identity]
        axis, low, high, low_node, high_node = _mouths(
            segment, curbs.get(segment.identity, {}), nodes
        )
        side = _across(segment, curbs.get(segment.identity, {}), axis)
        for key, mouth in ((low_node, low), (high_node, high)):
            legs[key].append((axis, side, mouth))
            at = (nodes[key].x_mm, nodes[key].y_mm)[axis]
            below, above = bounds.get((key, axis), (-_FAR_MM, _FAR_MM))
            bounds[key, axis] = (
                (max(below, mouth), above) if mouth < at else (below, min(above, mouth))
            )
        if profile.high_mm > profile.low_mm:
            climb = abs(profile.high_level_mm - profile.low_level_mm) * 1000
            ramps.append(
                Corridor(
                    id=f"street {segment.identity}",
                    rect_mm=_band(axis, side, profile.low_mm, profile.high_mm),
                    axis="xy"[axis],
                    grade_permille=max(1, -(-climb // (profile.high_mm - profile.low_mm))),
                    levels_mm=(profile.low_level_mm, profile.high_level_mm),
                )
            )
    pads = []
    for key in sorted(nodes):
        node = (nodes[key].x_mm, nodes[key].y_mm)
        for leg, (axis, side, mouth) in enumerate(legs[key]):
            below, above = bounds.get((key, 1 - axis), (-_FAR_MM, _FAR_MM))
            across = (max(side[0], below), min(side[1], above))
            pads.append(
                Pad(
                    id=f"junction {key} leg {leg}",
                    rect_mm=_band(axis, across, node[axis], mouth),
                    level_mm=nodes[key].z_mm,
                )
            )
    by_curb = {curb.identity: curb for curb in records if isinstance(curb, CurbEdgeRecord)}
    by_segment = {segment.identity: segment for segment in segments}
    for parcel in (r for r in records if isinstance(r, ParcelRecord)):
        curb = by_curb[parcel.frontages[0].curb_identity]
        segment = by_segment[curb.segment_identity]
        axis = profiles[segment.identity].axis
        door = door_of(parcel)
        x0, y0, x1, y1 = _rect(segment.extent)
        centre = segment.centreline_mm[0][1 - axis]
        if axis == 0:
            on_street = (_within(x0, x1, door[0]), _within(y0, y1, centre))
        else:
            on_street = (_within(x0, x1, centre), _within(y0, y1, door[1]))
        xs = [x for x, _ in parcel.boundary_mm]
        ys = [y for _, y in parcel.boundary_mm]
        pads.append(
            Pad(
                id=f"lot {parcel.identity}",
                rect_mm=(min(xs), min(ys), max(xs), max(ys)),
                level_mm=parcel.grade_elevation_mm,
                door_mm=on_street,
            )
        )
    first = min(nodes.values(), key=lambda node: node.node_ordinal)
    return GradingPlan(
        corridors=tuple(ramps),
        pads=tuple(pads),
        entry_mm=(first.x_mm // CELL_MM * CELL_MM, first.y_mm // CELL_MM * CELL_MM),
        bank_grade_permille=bank_grade_permille,
        cut_fill_most_mm=cut_fill_most_mm,
        walk_grade_permille=max((ramp.grade_permille for ramp in ramps), default=1),
    )
