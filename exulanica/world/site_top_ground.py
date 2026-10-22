"""A volume's top as a placed thing reads it, round the site laid out on it.

A person on a site laid out on a volume's top (site-plan composer version 7) walks the site and the
open top round it out to the rim: the page counts as floor the site's own floor and every cell of
the graded top drawn as land (:attr:`~exulanica.world.site_on_top.TopWorld.rock_cells`), and
stands them on the graded top, the site included. The kind worker states that top with the place
it makes (:func:`top_ground_document`), and :class:`TopGround` reads it, so a placing
(:mod:`~exulanica.world.thing_landing_source`) and the society of things that reads a placed thing
hold it to the ground the person walks: anywhere on the top's land, resting on the graded top. The
site's walking lines stand on the graded top at their ends and part from it only across a bank,
so the graded top is the ground a thing rests on there too.

The document is in the site's frame (east and north from its south-west corner, heights above the
volume's level 0). Every point asked of a :class:`TopGround` is in the region's frame a placed
thing's pose is in (east and south): the site's east and minus its north.

Pure: no connection and no worker.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal

from exulanica.grammar.landform import CELL_MM, NearLand
from exulanica.world.site_land import graded_height_at
from exulanica.world.site_top import SITE_TOP_PROFILE
from exulanica.world.society_walking_surfaces import RESTS_ON_SURFACE_MM
from exulanica.world.thing_landing import BlockedPart, LandingGround, rests_on_footprint

if TYPE_CHECKING:
    from exulanica.world.site_on_top import TopWorld
    from exulanica.world.society_authored_ground import WalkableArea

__all__ = ["TOP_GROUND_PROFILE", "TopGround", "top_ground_document", "top_landing"]

TOP_GROUND_PROFILE: Final = "exulanica.top-ground/v1"

Point = tuple[int, int]
TopRead = Literal["land", "water"]


def top_ground_document(world: TopWorld) -> dict[str, Any]:
    """``exulanica.top-ground/v1``: the site's graded top (``exulanica.site-top/v1``, as
    ``GET /world/versions/{version_id}/land/top`` serves it) and the top's cells drawn as land, as
    runs ``(row, first, last)`` (the drawing's ``top.rock_cells``)."""
    return {
        "profile": TOP_GROUND_PROFILE,
        "top": world.site.document(),
        "rock_cells": [list(run) for run in world.rock_cells],
    }


@dataclass(frozen=True)
class TopGround:
    """The open top round a site, read from :func:`top_ground_document`."""

    near: NearLand
    #: The cells drawn as land, by row: each row's runs of columns, first and last.
    cells: Mapping[int, tuple[tuple[int, int], ...]]
    water: tuple[Mapping[str, Any], ...]

    @classmethod
    def read(cls, document: Mapping[str, Any]) -> TopGround:
        if document.get("profile") != TOP_GROUND_PROFILE:
            raise ValueError(f"not {TOP_GROUND_PROFILE}: {document.get('profile')!r}")
        top = document["top"]
        if top.get("profile") != SITE_TOP_PROFILE or top["cell_mm"] != CELL_MM:
            raise ValueError(f"not {SITE_TOP_PROFILE} on a {CELL_MM} mm lattice")
        cells: dict[int, list[tuple[int, int]]] = {}
        for row, first, last in document["rock_cells"]:
            cells.setdefault(int(row), []).append((int(first), int(last)))
        return cls(
            near=NearLand(
                int(top["origin_mm"][0]),
                int(top["origin_mm"][1]),
                int(top["columns"]),
                int(top["rows"]),
                tuple(int(height) for height in top["height_mm"]),
            ),
            cells={row: tuple(runs) for row, runs in cells.items()},
            water=tuple(top["water"]),
        )

    def height_at(self, point: Point) -> int:
        """The graded top's height at a point of the region, above the volume's level 0: the height
        a thing rests at there."""
        return graded_height_at(self.near, point[0], -point[1])

    def reads(self, point: Point) -> TopRead | None:
        """What a point of the region is on the open top: ``"land"`` in a cell drawn as land (the
        page's own rule: the cell the point falls in, its south and west edges its own),
        ``"water"`` where the top's own water stands over it, or None past the rim."""
        x, y = point[0], -point[1]
        column = (x - self.near.x0) // CELL_MM
        row = (y - self.near.y0) // CELL_MM
        if not any(first <= column <= last for first, last in self.cells.get(row, ())):
            return None
        return "water" if self._under_water(x, y) else "land"

    def _under_water(self, x: int, y: int) -> bool:
        """Whether the top's own water stands over a point of the site's frame: inside a lake's
        circle or a pond's or a pool's rectangle, with the graded top under its level there. A
        fall is a sheet of no depth and stands over nothing."""
        for body in self.water:
            if body["kind"] == "lake":
                cx, cy = body["centre_mm"]
                inside = (x - cx) ** 2 + (y - cy) ** 2 <= body["radius_mm"] ** 2
            elif body["kind"] in ("fall", "sea"):
                continue
            else:
                x0, y0, x1, y1 = body["rect_mm"]
                inside = x0 <= x <= x1 and y0 <= y <= y1
            if inside and graded_height_at(self.near, x, y) < body["level_mm"]:
                return True
        return False


def top_landing(
    ground: TopGround, region_id: str, area: WalkableArea | None, parts: tuple[BlockedPart, ...]
) -> LandingGround:
    """The ground a thing placed on a site on a volume's top is held to: the site's ``area`` and
    the open top past it out to the rim (:meth:`TopGround.reads`), the site's blocked ``parts``,
    and the graded top it rests on, on the highest of it under its footprint as a town's surface
    rests a thing, so a bank's step is no refusal within the step a thing rests across
    (``RESTS_ON_SURFACE_MM``) and beyond it is told how much higher the ground is."""
    return LandingGround(
        region_id,
        area,
        rests_on_footprint(ground.height_at, RESTS_ON_SURFACE_MM),
        parts,
        ground.height_at,
        rests_on_footprint=True,
        beyond=ground.reads,
    )
