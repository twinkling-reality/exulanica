"""A site world on its land: the grading its layout asks of the land, and what its drawing, its land
routes and its society read from the land once graded.

A site's receipt may carry a land document (``exulanica.landform/v1``, site-plan composer version
5). The site grammar lays the site out in plan exactly as on level ground; on land the layout then
grades the land so that everything its society walks stays within the place contract's one kerb
step per edge (``society_place.STEP_LIMIT_MM``), with no new edge kind and no change to the walking
cost:

* every **zone** is a pad: level, at the height of its path where the zone's gate meets it (the gate
  projected onto the path's centre line), so its yard lattice, corridors, doors, seats and areas
  are level; a pond in the zone is carved into the zone's own pad;
* every **path** is a corridor graded no steeper than one step over its longest station spacing
  (the site's place lays a station every ``footway_station_spacing_mm`` or a little more), less a
  rounding margin, since heights are floored at both ends of an edge;
* every **water area** is a pond, its level its rim less the land catalog's freeboard;
* the **entry** is where the first path meets the site's south edge; a path that ends within a
  lattice cell of the site's edge is graded to the edge, where the society's entry stands.

Steeper natural ground lies only outside the zones, where the place lays no nodes. A site whose land
cannot be graded so is refused by name (``exulanica.grammar.landform`` grading refusals).

The receipt also names the land rules that made its land (``exulanica.grammar.landform.rules``):
land is read against the catalog version those rules name and realized and graded again only under
rules this code serves; a receipt that names others is refused by name
(``generated_world_land_rules_changed``), never drawn as other land.

The site's own frame keeps its origin at height 0, which is the land's datum, the sea's level: every
height here, in the drawing, the place and the browser is above the same zero.

Pure: no connection and no store. The graded land of one receipt is kept for the process, since the
drawing, the land routes and the place each ask for it.
"""

from __future__ import annotations

import functools
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.grammars.site.records import (
    SiteAreaRecord,
    SiteExtentRecord,
    SitePathRecord,
    SiteZoneRecord,
)
from exulanica.grammar.landform import (
    CELL_MM,
    CHUNK_MM,
    Backdrop,
    Basin,
    Corridor,
    GradedLand,
    GradingPlan,
    LandChunk,
    LandDocument,
    LandformRefused,
    Pad,
    WaterBody,
    WorldFrame,
    check_land_rules,
    grade_land,
    landform_catalog,
    read_land_document,
    realize_backdrop,
    realize_near,
    water_bodies,
)
from exulanica.world.society_place import STEP_LIMIT_MM

__all__ = [
    "ROUNDING_MARGIN_MM",
    "SiteLand",
    "check_receipt_land_rules",
    "land_seed",
    "path_grade_permille",
    "site_grading",
    "site_land",
    "site_land_of",
]

#: Heights are floored at both ends of an edge, so a path graded exactly at the step could climb
#: a millimetre more over a station; the margin keeps every edge strictly within it.
ROUNDING_MARGIN_MM: Final = 2


def _along_y(path: SitePathRecord) -> bool:
    return (path.max_y_mm - path.min_y_mm) >= (path.max_x_mm - path.min_x_mm)


def path_grade_permille(path: SitePathRecord, station_mm: int) -> int:
    """The steepest a path may climb: one step over its longest station spacing, as the site's place
    lays its stations (``society_site_place.place_from_site_records``), less the rounding margin."""
    low, high = (path.min_y_mm, path.max_y_mm) if _along_y(path) else (path.min_x_mm, path.max_x_mm)
    count = max(1, (high - low) // station_mm)
    spacing = -(-(high - low) // count)
    return max(1, (STEP_LIMIT_MM - ROUNDING_MARGIN_MM) * 1000 // spacing)


def _within(low: int, high: int, value: int) -> int:
    """The lattice point nearest ``value`` at or below it that lies within [low, high]."""
    first, last = -(-low // CELL_MM) * CELL_MM, high // CELL_MM * CELL_MM
    return min(max(value // CELL_MM * CELL_MM, first), last)


def _graded_rect(path: SitePathRecord, extent: SiteExtentRecord) -> tuple[int, int, int, int]:
    """A path's rectangle as it is graded: a path that ends within one lattice cell of the site's
    edge is graded to the edge, so the society's entry, which stands between the edge and where
    the path's record begins, stands on the path's grade and not on a bank."""
    x0, y0, x1, y1 = path.min_x_mm, path.min_y_mm, path.max_x_mm, path.max_y_mm
    return (
        0 if x0 < CELL_MM else x0,
        0 if y0 < CELL_MM else y0,
        extent.width_mm if extent.width_mm - x1 < CELL_MM else x1,
        extent.depth_mm if extent.depth_mm - y1 < CELL_MM else y1,
    )


def _on_path(rect: tuple[int, int, int, int], along_y: bool, x: int, y: int) -> tuple[int, int]:
    """A point projected onto a path's centre line, on a lattice point of the path itself (a path
    may begin between lattice rows, and the row outside it is not graded with it)."""
    x0, y0, x1, y1 = rect
    if along_y:
        return _within(x0, x1, (x0 + x1) // 2), _within(y0, y1, y)
    return _within(x0, x1, x), _within(y0, y1, (y0 + y1) // 2)


def _distance_squared(path: SitePathRecord, x: int, y: int) -> int:
    dx = max(path.min_x_mm - x, 0, x - path.max_x_mm)
    dy = max(path.min_y_mm - y, 0, y - path.max_y_mm)
    return dx * dx + dy * dy


def site_grading(records: Sequence[object], station_mm: int) -> GradingPlan:
    """The grading a site's records ask of its land."""
    extent = next(r for r in records if isinstance(r, SiteExtentRecord))
    paths = sorted((r for r in records if isinstance(r, SitePathRecord)), key=lambda p: p.ordinal)
    zones = sorted((r for r in records if isinstance(r, SiteZoneRecord)), key=lambda z: z.ordinal)
    areas = sorted((r for r in records if isinstance(r, SiteAreaRecord)), key=lambda a: a.ordinal)
    rects = {path.identity: _graded_rect(path, extent) for path in paths}
    corridors = tuple(
        Corridor(
            id=f"path {path.ordinal}",
            rect_mm=rects[path.identity],
            axis="y" if _along_y(path) else "x",
            grade_permille=path_grade_permille(path, station_mm),
        )
        for path in paths
    )
    pads = []
    for zone in zones:
        nearest = min(
            paths, key=lambda p: (_distance_squared(p, zone.gate_x_mm, zone.gate_y_mm), p.ordinal)
        )
        pads.append(
            Pad(
                id=f"zone {zone.ordinal}",
                rect_mm=(zone.min_x_mm, zone.min_y_mm, zone.max_x_mm, zone.max_y_mm),
                door_mm=_on_path(
                    rects[nearest.identity], _along_y(nearest), zone.gate_x_mm, zone.gate_y_mm
                ),
                water_allowed=True,
            )
        )
    basin = landform_catalog().values_of("basin")
    basins = tuple(
        Basin(
            id=f"pond {area.ordinal}",
            rect_mm=(area.min_x_mm, area.min_y_mm, area.max_x_mm, area.max_y_mm),
            depth_mm=basin["depth_mm"].default,
            shelf_mm=basin["shelf_mm"].default,
            freeboard_mm=basin["freeboard_mm"].default,
        )
        for area in areas
        if "water" in area.roles
    )
    return GradingPlan(
        corridors=corridors,
        pads=tuple(pads),
        basins=basins,
        entry_mm=_on_path(rects[paths[0].identity], _along_y(paths[0]), extent.entry_x_mm, 0),
        walk_grade_permille=min(corridor.grade_permille for corridor in corridors),
    )


@dataclass(frozen=True)
class SiteLand:
    """A site's land, graded by its layout."""

    land: LandDocument
    frame: WorldFrame
    graded: GradedLand
    water: tuple[WaterBody, ...]

    def height_at(self, x_mm: int, y_mm: int) -> int:
        """The graded land's height at a point of the site's frame, millimetres above the datum,
        floored: the plane of the triangle the point lies in (each cell split along its
        south-west to north-east diagonal)."""
        near = self.graded.near
        gx, gy = x_mm - near.x0, y_mm - near.y0
        i = min(near.nx - 2, max(0, gx // CELL_MM))
        j = min(near.ny - 2, max(0, gy // CELL_MM))
        fx = min(CELL_MM, max(0, gx - i * CELL_MM))
        fy = min(CELL_MM, max(0, gy - j * CELL_MM))
        h = near.heights
        h00, h10 = h[j * near.nx + i], h[j * near.nx + i + 1]
        h01, h11 = h[(j + 1) * near.nx + i], h[(j + 1) * near.nx + i + 1]
        if fx >= fy:
            return h00 + ((h10 - h00) * fx + (h11 - h10) * fy) // CELL_MM
        return h00 + ((h11 - h01) * fx + (h01 - h00) * fy) // CELL_MM

    def chunks(self) -> tuple[LandChunk, ...]:
        return self.graded.near.chunks()

    @functools.cached_property
    def backdrop(self) -> Backdrop:
        return realize_backdrop(self.land, self.frame)

    def drawing_section(self) -> dict[str, Any]:
        """What a site drawing states of its land: the land's digest, each chunk's place and
        digest, the backdrop's digest, and the water over the land with its levels."""
        return {
            "land_sha256": self.land.sha256,
            "chunk_mm": CHUNK_MM,
            "chunks": [
                {"chunk": [chunk.chunk_x, chunk.chunk_y], "sha256": chunk.sha256}
                for chunk in self.chunks()
            ],
            "backdrop_sha256": self.backdrop.sha256,
            "water": [body.document() for body in self.water],
        }

    def documents(self) -> dict[str, Any]:
        """The chunk and backdrop documents the land routes serve, each with its digest."""
        return {
            "chunks": {
                f"{chunk.chunk_x},{chunk.chunk_y}": {
                    "sha256": chunk.sha256,
                    "body": canonical_json(chunk.document()).decode("utf-8"),
                }
                for chunk in self.chunks()
            },
            "backdrop": {
                "sha256": self.backdrop.sha256,
                "body": canonical_json(self.backdrop.document()).decode("utf-8"),
            },
        }


def land_seed(world_id: str, land_sha256: str) -> str:
    """The seed a world's land is realized with: its world's identity and its land document's
    digest, both in its receipt. Not the layout candidate's seed: a world's land is the same land
    whichever of its layouts is kept."""
    return hashlib.sha256(f"exulanica.landform:{world_id}:{land_sha256}".encode()).hexdigest()


def _records_digest(records: Sequence[object]) -> str:
    from exulanica.grammar.records import canonical_record

    digest = hashlib.sha256()
    for record in records:
        digest.update(canonical_record(record))
    return digest.hexdigest()


_KEPT: dict[tuple[str, str, str, int], SiteLand] = {}
_KEPT_MOST: Final = 8


def site_land(
    land: LandDocument, records: Sequence[object], seed: str, station_mm: int
) -> SiteLand:
    """Realize a site's land and grade it for its records, or refuse by name. Kept for the process
    by the land, the records, the seed and the station spacing: the composer, the drawing, the land
    routes and the place each ask for the same graded land."""
    key = (land.sha256, _records_digest(records), seed, station_mm)
    if key not in _KEPT:
        extent = next(r for r in records if isinstance(r, SiteExtentRecord))
        frame = WorldFrame(width_mm=extent.width_mm, depth_mm=extent.depth_mm, seed=seed)
        own = water_bodies(land, frame)
        plan = site_grading(records, station_mm)
        graded = grade_land(realize_near(land, frame), plan, water=own)
        if len(_KEPT) >= _KEPT_MOST:
            _KEPT.pop(next(iter(_KEPT)))
        _KEPT[key] = SiteLand(land=land, frame=frame, graded=graded, water=(*own, *graded.water))
    return _KEPT[key]


def check_receipt_land_rules(receipt: Mapping[str, Any]) -> int:
    """The landform catalog version a receipt's land is read against, or a refusal by name of land
    made by rules this code does not serve."""
    try:
        return check_land_rules(receipt.get("land_rules"))
    except LandformRefused as exc:
        from exulanica.world.errors import InvalidStructuralData

        raise InvalidStructuralData(f"generated_world_land_rules_changed: {exc.detail}") from exc


def site_land_of(
    receipt: Mapping[str, Any], records: Sequence[object], station_mm: int
) -> SiteLand:
    """The graded land a version 5 receipt states, for its regenerated records, under the land
    rules the receipt names, its land document read again and held to the digest the receipt
    names."""
    land = read_land_document(receipt["land"], landform_catalog(check_receipt_land_rules(receipt)))
    if land.sha256 != receipt["land_sha256"]:
        from exulanica.world.errors import InvalidStructuralData

        raise InvalidStructuralData(
            "generated_world_land_changed: its land document no longer reads as the one its "
            "receipt names"
        )
    return site_land(land, records, land_seed(str(receipt["world_id"]), land.sha256), station_mm)
