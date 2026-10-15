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
from dataclasses import dataclass
from typing import Final

from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city.districts import DistrictRecord
from exulanica.grammar.grammars.city.parcels import ParcelRecord
from exulanica.grammar.grammars.city.streets import (
    CurbEdgeRecord,
    StreetNodeRecord,
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
    "TownGrading",
    "grade_town",
    "town_frame",
    "town_grading_plan",
]

#: Heights are floored at both ends of an edge, so a street graded exactly at the step could climb
#: a millimetre more over a station; the margin keeps every edge strictly within it.
ROUNDING_MARGIN_MM: Final = 2


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


def _corridor(
    segment: StreetSegmentRecord, curbs: Sequence[CurbEdgeRecord], figures: TownGrading
) -> Corridor:
    lengths = [_kerb_length(curb) for curb in curbs] or [segment.length_mm]
    spacing = max(_station_spacing(length, figures.station_mm) for length in lengths)
    return Corridor(
        id=f"street {segment.identity}",
        rect_mm=_rect(segment.extent),
        axis="x" if _along_x(segment) else "y",
        grade_permille=max(1, (figures.step_mm - ROUNDING_MARGIN_MM) * 1000 // spacing),
    )


def _on_centre(corridor: Corridor, x: int, y: int) -> tuple[int, int]:
    """A point projected onto a corridor's centre line, on a lattice point within the corridor."""
    x0, y0, x1, y1 = corridor.rect_mm
    if corridor.axis == "x":
        return _within(x0, x1, x), _within(y0, y1, (y0 + y1) // 2)
    return _within(x0, x1, (x0 + x1) // 2), _within(y0, y1, y)


def _door(parcel: ParcelRecord) -> tuple[int, int]:
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
    x0, y0, x1, y1 = near.domain_mm
    natural = {
        node_id: near.at(
            min(max(node.x_mm // CELL_MM * CELL_MM, x0), x1),
            min(max(node.y_mm // CELL_MM * CELL_MM, y0), y1),
        )
        for node_id, node in nodes.items()
    }
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
    return [
        Pad(
            id=f"junction {node_id}",
            rect_mm=(boxes[node_id][0], boxes[node_id][1], boxes[node_id][2], boxes[node_id][3]),
            level_mm=(upper[node_id] + lower[node_id]) // 2,
        )
        for node_id in sorted(nodes)
    ]


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
                door_mm=_on_centre(by_curb[parcel.frontages[0].curb_identity], *_door(parcel)),
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
