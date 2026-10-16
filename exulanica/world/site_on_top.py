"""A world laid out on a placed volume's top: site-plan composer version 7.

A landscape may state a ``site`` on a placement whose volume has a top land
(:class:`~exulanica.grammar.landscape.LandscapeSite`); the site is then laid out and graded on that
top (:mod:`exulanica.world.site_top`) in place of the landscape's land, and the world stands on the
volume. The site keeps its own frame, which is the world's: its south-west corner stands at
``at_mm`` of the volume's frame and its height zero is the volume's level 0, so the volume's
altitude enters no height the site states. Here:

* :func:`on_top` reads where the site stands: the placement, and the top as the grader takes it,
  graded under the land rules the landscape's volume rules name for a top land (:func:`top_rules`),
  never the newest land rules.
* :func:`top_field` is the volume's field as the landscape realizes it (the placement's seed under
  the world's landscape seed), capped by the graded top where one is given
  (:class:`~exulanica.grammar.volumes.TopHeights`), so the rock under the site meets the ground
  people walk at every lattice point.
* :func:`check_on_rock` is the one rule that the site stands on rock: every lattice point of the
  site grown by :data:`ROCK_MARGIN_MM` has rock :data:`ROCK_UNDER_MM` under its top. It is held
  before layout on the natural top, from the kind's plan alone, and after grading on the graded
  top (``landscape_site_not_on_rock``, path ``landscape.site``).
* :func:`arrival_beyond_gate` stands a person arriving on the open top outside the site's gate,
  between the gate and the rim (the first of :data:`GATE_CLEAR_MM` with rock under it), or in the
  gate's opening where the site fills the top, so the site's fence is behind them; and
  :func:`open_rim_facing` turns them toward the nearest open rim: of the bearings
  :data:`BEARING_STEP_MDEG` apart facing away from the site, the one whose rim lies nearest within
  :data:`RIM_NEAREST_MM` to :data:`RIM_FARTHEST_MM`, nothing between taller than
  :data:`EYE_HEIGHT_MM` (a building, a wall or a fixture, or the ground rising so far), so a person
  arriving sees the island's edge and the world below it, and no fence across the middle of the
  view.
* :func:`top_world_of` reads a version 7 receipt's world back: its landscape, the graded top for
  its records and the capped field, as :class:`TopWorld`, which stands where a site's graded land
  stands for the drawing, the place and part edits.

Pure: no connection and no store.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.grammars.site.records import (
    SiteFixtureRecord,
    SiteStructureRecord,
    SiteWallRecord,
)
from exulanica.grammar.landform import CELL_MM, NearLand
from exulanica.grammar.landscape import (
    LandscapeDocument,
    LandscapeRefused,
    Placement,
    placement_seed,
)
from exulanica.grammar.volumes import (
    TURN_ONE,
    TopHeights,
    VolumeField,
    realize_top_land,
    sin_cos,
)
from exulanica.grammar.volumes.rules import top_land_rules
from exulanica.world.site_top import OnTop, SiteTop, site_top

__all__ = [
    "AWAY_FROM_SITE",
    "BEARING_STEP_MDEG",
    "EYE_HEIGHT_MM",
    "GATE_CLEAR_MM",
    "RIM_FARTHEST_MM",
    "RIM_NEAREST_MM",
    "ROCK_MARGIN_MM",
    "ROCK_UNDER_MM",
    "TopWorld",
    "arrival_beyond_gate",
    "check_on_rock",
    "natural_top",
    "on_top",
    "open_rim_facing",
    "top_field",
    "top_rules",
    "top_world_of",
]

#: How far round the site the rock must reach, and how deep under the top it must be solid.
ROCK_MARGIN_MM: Final = 1_000
ROCK_UNDER_MM: Final = 1_000
#: The arrival looks toward a rim this near to this far, over nothing taller than a person's eyes.
RIM_NEAREST_MM: Final = 10_000
RIM_FARTHEST_MM: Final = 25_000
EYE_HEIGHT_MM: Final = 1_600
#: The bearings tried, from north clockwise, and how far and in what steps each is walked.
BEARING_STEP_MDEG: Final = 10_000
_REACH_MM: Final = 64_000
_STEP_MM: Final = 500
_FULL_TURN: Final = 360_000
#: The bearings that face away from a site from its gate on its south edge: east through south to
#: west, so the site, its fence and its buildings are behind a person arriving.
AWAY_FROM_SITE: Final = range(90_000, 270_001, BEARING_STEP_MDEG)
#: How far outside the site's gate a person arriving stands, the first that has rock under it.
GATE_CLEAR_MM: Final = (3_000, 2_500, 2_000, 1_500)


def top_rules(landscape: LandscapeDocument) -> int:
    """The land rules a landscape's site is graded under: the ones its volume rules name for a top
    land, so a later land version never moves a graded top."""
    rules = top_land_rules(landscape.volume_rules)
    if rules is None:
        raise LandscapeRefused(
            f"volume rules {landscape.volume_rules} state no top land a site can be laid out on",
            path="landscape.site",
            code="landscape_site_no_top_land",
        )
    return rules


def on_top(landscape: LandscapeDocument, rules_version: int) -> tuple[Placement, OnTop]:
    """The placement a landscape's site stands on and the top the grader takes under the land
    rules ``rules_version``. The landscape reader has already held the site to a placement with a
    top land and to its square."""
    site = landscape.site
    if site is None:
        raise LandscapeRefused("the landscape states no site", path="landscape.site")
    placement = next(p for p in landscape.placements if p.id == site.on)
    top = placement.volume.top_land
    if top is None:
        raise LandscapeRefused(
            f"{site.on} states no top land a site can be laid out on",
            path="landscape.site.on",
            code="landscape_site_no_top_land",
        )
    return placement, OnTop(
        top=top,
        volume_id=placement.volume.id,
        at_mm=site.at_mm,
        cut_fill_mm=site.cut_fill_mm,
        rules_version=rules_version,
    )


def top_field(
    landscape: LandscapeDocument,
    placement: Placement,
    landscape_seed: str,
    graded: SiteTop | None = None,
) -> VolumeField:
    """The placed volume's field as the landscape realizes it under ``landscape_seed``, capped by
    the graded top where one is given."""
    heights = None
    if graded is not None:
        near = graded.graded.near
        heights = TopHeights(count=near.nx, heights=tuple(near.heights))
    return VolumeField(
        placement.volume,
        placement_seed(landscape_seed, placement.id),
        rules=landscape.volume_rules,
        top=heights,
    )


def _natural_height(near: NearLand, x_mm: int, y_mm: int) -> int:
    """The natural top's height at a lattice point of the volume's frame, or the square's nearest
    edge point's beyond it, as the field caps the rock there."""
    i = min(near.nx - 1, max(0, (x_mm - near.x0) // CELL_MM))
    j = min(near.ny - 1, max(0, (y_mm - near.y0) // CELL_MM))
    return near.heights[j * near.nx + i]


def natural_top(on: OnTop) -> Callable[[int, int], int]:
    """The natural top's height at a lattice point of the site's frame."""
    square = realize_top_land(on.top, on.volume_id)
    half = on.top.side_mm // 2
    east, north = on.at_mm
    near = NearLand(-half, -half, square.nx, square.ny, square.heights)
    return lambda x, y: _natural_height(near, x + east, y + north)


def check_on_rock(
    field: VolumeField,
    on: OnTop,
    width_mm: int,
    depth_mm: int,
    height_at: Callable[[int, int], int],
) -> None:
    """Refuse a site whose ground, grown by :data:`ROCK_MARGIN_MM`, has no rock
    :data:`ROCK_UNDER_MM` under the top at some lattice point, the top's height read by
    ``height_at`` in the site's frame."""
    east, north = on.at_mm
    for y in range(-ROCK_MARGIN_MM, depth_mm + ROCK_MARGIN_MM + 1, CELL_MM):
        for x in range(-ROCK_MARGIN_MM, width_mm + ROCK_MARGIN_MM + 1, CELL_MM):
            top = height_at(x, y)
            if field.distance(x + east, y + north, top - ROCK_UNDER_MM) > 0:
                raise LandscapeRefused(
                    f"the site's ground at ({x}, {y}) of the site, ({x + east}, {y + north}) of "
                    f"{on.volume_id}, has no rock {ROCK_UNDER_MM} mm under its top at {top} mm: a "
                    f"site and {ROCK_MARGIN_MM} mm round it stand on the volume's rock",
                    path="landscape.site",
                    code="landscape_site_not_on_rock",
                )


def _blockers(records: Sequence[object]) -> list[tuple[int, int, int, int]]:
    """What a person arriving cannot see over, as rectangles of the site's frame grown by half a
    step: every building, and every wall and fixture taller than a person's eyes."""
    grow = _STEP_MM // 2
    boxes = []
    for record in records:
        if isinstance(record, SiteStructureRecord):
            boxes.append((record.min_x_mm, record.min_y_mm, record.max_x_mm, record.max_y_mm))
        elif isinstance(record, SiteWallRecord) and record.height_mm > EYE_HEIGHT_MM:
            half = record.thickness_mm // 2
            boxes.append(
                (
                    min(record.start_x_mm, record.end_x_mm) - half,
                    min(record.start_y_mm, record.end_y_mm) - half,
                    max(record.start_x_mm, record.end_x_mm) + half,
                    max(record.start_y_mm, record.end_y_mm) + half,
                )
            )
        elif isinstance(record, SiteFixtureRecord) and record.height_mm > EYE_HEIGHT_MM:
            half = max(record.width_mm, record.depth_mm) // 2
            boxes.append(
                (record.x_mm - half, record.y_mm - half, record.x_mm + half, record.y_mm + half)
            )
    return [(x0 - grow, y0 - grow, x1 + grow, y1 + grow) for x0, y0, x1, y1 in boxes]


def _rim(
    field: VolumeField,
    on: OnTop,
    top: SiteTop,
    start: tuple[int, int],
    bearing: int,
    blockers: list[tuple[int, int, int, int]],
) -> int | None:
    """How far along ``bearing`` from ``start`` the rock's top ends, over nothing taller than a
    person's eyes; None where something blocks the view first or no rim lies within reach."""
    sine, cosine = sin_cos(bearing)
    east, north = on.at_mm
    x0, y0 = start
    eyes = top.height_at(x0, y0) + EYE_HEIGHT_MM
    for distance in range(_STEP_MM, _REACH_MM + 1, _STEP_MM):
        x = x0 + distance * sine // TURN_ONE
        y = y0 + distance * cosine // TURN_ONE
        ground = top.height_at(x, y)
        if field.distance(x + east, y + north, ground - ROCK_UNDER_MM) > 0:
            return distance
        if ground > eyes or any(
            bx0 <= x <= bx1 and by0 <= y <= by1 for bx0, by0, bx1, by1 in blockers
        ):
            return None
    return None


def arrival_beyond_gate(field: VolumeField, on: OnTop, top: SiteTop, entry_x_mm: int) -> list[int]:
    """Where a person arriving stands on a volume's top, in the site's frame: on the open top
    outside the site's gate on its south edge, the first of :data:`GATE_CLEAR_MM` south of it with
    rock :data:`ROCK_UNDER_MM` under the top there and a metre either side and beyond; in the gate's
    opening where the site fills the top."""
    east, north = on.at_mm

    def on_rock(x: int, y: int) -> bool:
        return field.distance(x + east, y + north, top.height_at(x, y) - ROCK_UNDER_MM) <= 0

    for clear in GATE_CLEAR_MM:
        y = -clear
        around = ((entry_x_mm, y), (entry_x_mm - CELL_MM, y), (entry_x_mm + CELL_MM, y),
                  (entry_x_mm, y - CELL_MM))  # fmt: skip
        if all(on_rock(x, y) for x, y in around):
            return [entry_x_mm, y]
    return [entry_x_mm, 0]


def open_rim_facing(
    field: VolumeField,
    on: OnTop,
    top: SiteTop,
    position_mm: Sequence[int],
    records: Sequence[object],
    bearings: range = range(0, _FULL_TURN, BEARING_STEP_MDEG),
) -> list[int] | None:
    """The facing, in thousandths along north and east, toward the nearest open rim from the
    arrival, of ``bearings`` (every one by default): within :data:`RIM_NEAREST_MM` to
    :data:`RIM_FARTHEST_MM` where one is, else the open rim nearest that range, the first bearing
    among equals; None where no open rim lies within reach."""
    blockers = _blockers(records)
    start = (int(position_mm[0]), int(position_mm[1]))
    best: tuple[int, int, int] | None = None
    for bearing in bearings:
        distance = _rim(field, on, top, start, bearing, blockers)
        if distance is None:
            continue
        outside = max(0, RIM_NEAREST_MM - distance, distance - RIM_FARTHEST_MM)
        found = (outside, distance, bearing)
        if best is None or found < best:
            best = found
    if best is None:
        return None
    sine, cosine = sin_cos(best[2])
    return [sine * 1000 // TURN_ONE, cosine * 1000 // TURN_ONE]


@dataclass(frozen=True)
class TopWorld:
    """A version 7 world's ground: the top graded for its records, the landscape and placement it
    stands on and the volume's field capped by that top. Stands where a site's graded land stands
    for the drawing, the place and part edits."""

    site: SiteTop
    landscape: LandscapeDocument
    placement_id: str
    field: VolumeField

    @property
    def water(self) -> tuple[Any, ...]:
        return self.site.water

    def height_at(self, x_mm: int, y_mm: int) -> int:
        """The graded top's height at a point of the site's frame, above the volume's level 0."""
        return self.site.height_at(x_mm, y_mm)

    @functools.cached_property
    def rock_cells(self) -> tuple[tuple[int, int, int], ...]:
        """The cells of the graded top's lattice (rows from the south, from its south-west corner)
        whose four corners have rock :data:`ROCK_UNDER_MM` under the top, as runs ``(row, first,
        last)``: the top drawn as land; the volume's own rock draws the rest of it to the rim."""
        near = self.site.graded.near
        east, north = self.site.on.at_mm
        solid = [
            self.field.distance(x + east, y + north, height - ROCK_UNDER_MM) <= 0
            for x, y, height in near.samples()
        ]
        runs = []
        for row in range(near.ny - 1):
            first = None
            for column in range(near.nx):
                at = row * near.nx + column
                held = (
                    column < near.nx - 1
                    and solid[at]
                    and solid[at + 1]
                    and solid[at + near.nx]
                    and solid[at + near.nx + 1]
                )
                if held and first is None:
                    first = column
                elif not held and first is not None:
                    runs.append((row, first, column - 1))
                    first = None
        return tuple(runs)

    def drawing_section(self) -> dict[str, Any]:
        """What a site drawing (``exulanica.site-drawing/v6``) states of the top it stands on: the
        graded top's digest (served by ``GET /world/versions/{version_id}/land/top``), the
        landscape and placement it is a top of, the site's corner in the volume's frame, the water
        on it, and the cells drawn as land."""
        return {
            "top_sha256": self.site.sha256,
            "landscape_sha256": self.landscape.sha256,
            "placement": self.placement_id,
            "offset_mm": list(self.site.on.at_mm),
            "water": [body.document() for body in self.site.water],
            "rock_cells": [list(run) for run in self.rock_cells],
        }

    def documents(self) -> dict[str, Any]:
        """What the land routes serve for a world on a top: no chunks or backdrop, and the graded
        top by its digest."""
        return {
            "chunks": {},
            "top": {
                "sha256": self.site.sha256,
                "body": canonical_json(self.site.document()).decode("utf-8"),
            },
        }


def top_world_of(
    receipt: Mapping[str, Any], records: Sequence[object], station_mm: int
) -> TopWorld:
    """The ground a version 7 receipt's world stands on, for its regenerated records: its
    landscape read back under the rules it names, its site's top graded under the land rules the
    receipt names, and the field capped by it; refused by name as the landscape and the grader
    refuse."""
    from exulanica.world.landscape_drawing import landscape_seed, receipt_landscape

    landscape = receipt_landscape(receipt)
    placement, on = on_top(landscape, int(receipt["land_rules"]["version"]))
    graded = site_top(on, records, station_mm)
    seed = landscape_seed(str(receipt["world_id"]), landscape.sha256)
    return TopWorld(
        site=graded,
        landscape=landscape,
        placement_id=placement.id,
        field=top_field(landscape, placement, seed, graded),
    )
