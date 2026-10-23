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
  gate's opening where the site fills the top; they face the site through its gate
  (:data:`INTO_SITE`), so the first view holds the hamlet's track and houses, and the island's
  other volumes beyond.
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
from exulanica.grammar.landform import CELL_MM, NearLand
from exulanica.grammar.landscape import (
    LandscapeDocument,
    LandscapeRefused,
    Placement,
    placement_seed,
)
from exulanica.grammar.volumes import TopHeights, VolumeField, realize_top_land
from exulanica.grammar.volumes.rules import top_land_rules
from exulanica.world.site_top import OnTop, SiteTop, site_top

__all__ = [
    "GATE_CLEAR_MM",
    "INTO_SITE",
    "ROCK_MARGIN_MM",
    "ROCK_UNDER_MM",
    "TopWorld",
    "arrival_beyond_gate",
    "check_on_rock",
    "natural_top",
    "on_top",
    "top_field",
    "top_rules",
    "top_world_of",
]

#: How far round the site the rock must reach, and how deep under the top it must be solid.
ROCK_MARGIN_MM: Final = 1_000
ROCK_UNDER_MM: Final = 1_000
#: The way a person arriving faces, in thousandths along east and north: north, into the site
#: through its gate on the site's south edge.
INTO_SITE: Final = (0, 1000)
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
        on it, the cells drawn as land and, where its grading lists them (land rules from
        version 5), the retaining walls where its levels meet, as a site on land states them."""
        section: dict[str, Any] = {
            "top_sha256": self.site.sha256,
            "landscape_sha256": self.landscape.sha256,
            "placement": self.placement_id,
            "offset_mm": list(self.site.on.at_mm),
            "water": [body.document() for body in self.site.water],
            "rock_cells": [list(run) for run in self.rock_cells],
        }
        if self.site.graded.retaining is not None:
            section["walls"] = [wall.document() for wall in self.site.graded.retaining]
        return section

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
