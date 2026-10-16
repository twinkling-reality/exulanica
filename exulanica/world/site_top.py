"""A site laid out on a volume's top land, graded as a site on land is graded.

A volume may state a top land (:class:`~exulanica.grammar.volumes.TopLand`): an unchanged land over
a square centred on the volume's own origin, its datum the volume's level 0. A site laid out on it
keeps its own frame: its south-west corner stands at a whole-metre point of the volume's frame
(:attr:`OnTop.at_mm`), and its height zero is the volume's level 0, so every height the site states
is above the top's datum whatever the volume's altitude.

The natural top is the one realization the volume's field caps its rock by
(:func:`~exulanica.grammar.volumes.realize_top_land`), moved into the site's frame on the same 1 m
lattice, so nothing is resampled. The site's records grade it exactly as they grade land
(:func:`~exulanica.world.site_land.site_grading` and the land's grader), over the whole square, so
banks run out to the rim and no cliff stands where grading would stop; the deepest cut or fill is
the bound the site states (:attr:`OnTop.cut_fill_mm`), under the land rules the top states
(:attr:`OnTop.rules_version`, the ones the volume rules name for a top land), so a later land
version never moves a graded top. Heights are read between lattice points by the graded land's
triangle rule (:func:`~exulanica.world.site_land.graded_height_at`).

Refused by name (:class:`~exulanica.grammar.landform.LandformRefused`): a site that does not lie
inside the square (``landscape_site_outside_top``), a top whose land has a shore
(``landscape_site_top_has_sea``: the sea is the ground's, at the datum), and every refusal of the
land's grader. Whether the rock under the graded top holds it is the island's own check, not this
module's.

Pure: no connection and no store. The graded top of one site is kept for the process, as a site's
graded land is.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.grammars.site.records import SiteExtentRecord
from exulanica.grammar.landform import (
    CELL_MM,
    GradedLand,
    LandformRefused,
    NearLand,
    WaterBody,
    grade_land,
    water_bodies,
)
from exulanica.grammar.volumes import TopLand, realize_top_land, top_land_frame
from exulanica.world.site_land import graded_height_at, records_digest, site_grading

__all__ = ["SITE_TOP_PROFILE", "TOP_DATUM", "OnTop", "SiteTop", "site_top"]

SITE_TOP_PROFILE: Final = "exulanica.site-top/v1"
#: What a place's heights stand above on a site laid out on a volume's top.
TOP_DATUM: Final = "site_local z, above the level 0 of the volume the site stands on"


@dataclass(frozen=True, slots=True)
class OnTop:
    """Where a site stands on a volume's top: the volume's top land and id, the site's south-west
    corner in the volume's frame (whole metres), the deepest its grading may cut or fill, and the
    land rules the top is realized and graded under (the ones the volume rules name for a top
    land)."""

    top: TopLand
    volume_id: str
    at_mm: tuple[int, int]
    cut_fill_mm: int
    rules_version: int


@dataclass(frozen=True)
class SiteTop:
    """A volume's top graded for the site laid out on it, in the site's frame."""

    on: OnTop
    graded: GradedLand
    water: tuple[WaterBody, ...]

    def height_at(self, x_mm: int, y_mm: int) -> int:
        """The graded top's height at a point of the site's frame, above the volume's level 0."""
        return graded_height_at(self.graded.near, x_mm, y_mm)

    def document(self) -> dict[str, Any]:
        """``exulanica.site-top/v1``: the graded heights on the 1 m lattice, rows from the south,
        from the south-west corner in the site's frame, and the water standing on them."""
        near = self.graded.near
        return {
            "profile": SITE_TOP_PROFILE,
            "cell_mm": CELL_MM,
            "origin_mm": [near.x0, near.y0],
            "columns": near.nx,
            "rows": near.ny,
            "height_mm": list(near.heights),
            "water": [body.document() for body in self.water],
        }

    @functools.cached_property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.document())).hexdigest()


def _moved(body: WaterBody, east: int, north: int) -> WaterBody:
    """A water body of the top's square moved into the site's frame."""
    x0, y0, x1, y1 = body.rect_mm
    cx, cy = body.centre_mm
    return dataclasses.replace(
        body,
        centre_mm=(cx + east, cy + north) if body.kind == "lake" else body.centre_mm,
        rect_mm=(x0 + east, y0 + north, x1 + east, y1 + north)
        if any(body.rect_mm)
        else body.rect_mm,
    )


def _natural(on: OnTop, width_mm: int, depth_mm: int) -> tuple[NearLand, tuple[WaterBody, ...]]:
    """The natural top and its water in the site's frame, or a refusal of a site off the square or
    a top with a shore."""
    side, (east, north) = on.top.side_mm, on.at_mm
    half = side // 2
    if east % CELL_MM or north % CELL_MM:
        raise LandformRefused(
            f"a site stands at whole metres of the top's frame, got ({east}, {north})",
            code="landscape_site_outside_top",
        )
    if not (
        -half <= east and east + width_mm <= half and -half <= north and north + depth_mm <= half
    ):
        raise LandformRefused(
            f"the site from ({east}, {north}) to ({east + width_mm}, {north + depth_mm}) does not "
            f"lie inside the top's square, {-half} to {half} east and north",
            code="landscape_site_outside_top",
        )
    frame = top_land_frame(on.top, on.volume_id)
    own = water_bodies(on.top.land, frame)
    shores = [body.id for body in own if body.kind == "sea"]
    if shores:
        raise LandformRefused(
            f"a site's top has no sea: {', '.join(shores)} is a shore, which is the ground's",
            code="landscape_site_top_has_sea",
        )
    square = realize_top_land(on.top, on.volume_id)
    # The square's south-west corner is the volume's (-half, -half); the site's is (east, north).
    move_east, move_north = -half - east, -half - north
    near = NearLand(
        square.x0 + move_east, square.y0 + move_north, square.nx, square.ny, square.heights
    )
    return near, tuple(_moved(body, move_east, move_north) for body in own)


_KEPT: dict[tuple[object, ...], SiteTop] = {}
_KEPT_MOST: Final = 8


def site_top(on: OnTop, records: Sequence[object], station_mm: int) -> SiteTop:
    """Grade a volume's top for a site's records, or refuse by name. Kept for the process by every
    input, as a site's graded land is."""
    key = (
        on.top.land.sha256,
        on.top.side_mm,
        on.volume_id,
        on.at_mm,
        on.cut_fill_mm,
        on.rules_version,
        records_digest(records),
        station_mm,
    )
    if key not in _KEPT:
        extent = next(r for r in records if isinstance(r, SiteExtentRecord))
        near, own = _natural(on, extent.width_mm, extent.depth_mm)
        plan = dataclasses.replace(
            site_grading(records, station_mm, rules_version=on.rules_version),
            cut_fill_most_mm=on.cut_fill_mm,
        )
        graded = grade_land(near, plan, water=own)
        if len(_KEPT) >= _KEPT_MOST:
            _KEPT.pop(next(iter(_KEPT)))
        _KEPT[key] = SiteTop(on=on, graded=graded, water=(*own, *graded.water))
    return _KEPT[key]
