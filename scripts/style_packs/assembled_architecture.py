"""Buildings that repeat their bays and storeys to meet their box: architecture modules for kits
pinned to appearance catalog version 3 (``docs/style-pack-contract.md``, sections 3 and 8).

A kit pinned to version 3 makes its arcade blocks, towers and halls as modules rather than whole
buildings of one size. An arcade block is its two end walls about one bay across, its ground storey,
one upper storey and its eaves; a tower is one stage under its belfry and roof; a hall is its two
gable ends about one bay. Each recipe returns the piece with the zones its variant states: the bay
repeats across (``repeat_mm``, width), the storey or stage repeats up (height), and an arcade
block's plain body behind its loggia stretches in depth (``stretch_mm``); an axis with neither is
scaled within the family's bounds. The page draws the copies a box needs.

The parts are ``architecture.py``'s (arched walls, cornices, balustrades), placed as its recipes
place them, so a module reads as the building it repeats. The row's fields are the same: its size,
bays and storeys give the bay width and storey height the module is drawn at. Every face is cut at
the zone edges (:func:`split_at`), so no triangle lies across one, which the server holds.
"""

from __future__ import annotations

import math
from itertools import pairwise
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from scripts.style_packs.architecture import (
    _mirror_z,
    _turn,
    arched_wall,
    balustrade_run,
    cornice,
)
from scripts.style_packs.authored_packs import Piece

Vec = tuple[float, float, float]
#: A zone in whole millimetres from the piece's low face on its axis, or none.
Zone = tuple[int, int] | None

#: How far a block's cornices reach past its walls on each side, in millimetres: the eaves cornice's
#: outer step (0.25 m out, drawn 1.8 times as far), as ``architecture.arcade_block`` insets it.
OVERHANG_MM = 450
#: An arcade block's end wall, in millimetres: the site grammar's outer wall, so a building's end
#: stands where its walls do.
END_WALL_MM = 200
#: An arcade block's plain body begins this far behind its back wall and ends this far before its
#: loggia, in millimetres, clear of the roof balustrade and the loggia's ceiling.
BODY_MARGINS_MM = (600, 300)
#: The eaves cornice and the roof balustrade above the storeys, in millimetres: the cornice 600 and,
#: on a railed roof, a 1,050 balustrade standing on it (with 10 to spare); else the cornice and 100.
TOP_MM = {True: 1660, False: 700}
#: A hall's gable end, in millimetres from each end to its first bay.
HALL_END_MM = 600
#: A tower's belfry stands this much inside its stages, in metres, as one stage of
#: ``architecture.tower`` steps in.
TOWER_SETBACK_M = 0.12
#: The narrowest bay a module is drawn at, in millimetres: an arch on its piers with a window over
#: it, the opening still wider than a door.
LEAST_BAY_MM = 2000
#: The lowest upper storey, in millimetres: a room's height under its arched window.
LEAST_STOREY_MM = 2500
#: A corner closer than this to a cut, in metres, is on it.
_ON_CUT_M = 1e-9


@dataclass(frozen=True, slots=True)
class Module:
    """A module and how its variant meets a box: its own size and its zones, width, depth, height."""

    piece: Piece
    size_mm: tuple[int, int, int]
    stretch_mm: tuple[Zone, Zone, Zone]
    repeat_mm: tuple[Zone, Zone, Zone]


def _clip(polygon: list[Vec], axis: int, cut: float, keep_above: bool) -> list[Vec]:
    """The part of a convex polygon on one side of the plane ``axis = cut``, its corners in order."""
    out: list[Vec] = []
    for k, a in enumerate(polygon):
        b = polygon[(k + 1) % len(polygon)]
        da = (a[axis] - cut) if keep_above else (cut - a[axis])
        db = (b[axis] - cut) if keep_above else (cut - b[axis])
        if da >= -_ON_CUT_M:
            out.append(a)
        if (da > _ON_CUT_M and db < -_ON_CUT_M) or (da < -_ON_CUT_M and db > _ON_CUT_M):
            t = da / (da - db)
            point = [a[i] + (b[i] - a[i]) * t for i in range(3)]
            point[axis] = cut
            out.append((point[0], point[1], point[2]))
    return out


def _area(polygon: Sequence[Vec]) -> float:
    total = [0.0, 0.0, 0.0]
    first = polygon[0]
    for b, c in pairwise(polygon[1:]):
        u = [b[i] - first[i] for i in range(3)]
        v = [c[i] - first[i] for i in range(3)]
        total[0] += u[1] * v[2] - u[2] * v[1]
        total[1] += u[2] * v[0] - u[0] * v[2]
        total[2] += u[0] * v[1] - u[1] * v[0]
    return math.hypot(*total) / 2


def split_at(piece: Piece, cuts: Sequence[Sequence[float]]) -> Piece:
    """``piece`` with every triangle cut by the planes ``x = c`` for each ``c`` in ``cuts[0]``,
    ``y = c`` in ``cuts[1]`` and ``z = c`` in ``cuts[2]``: each part keeps its triangle's winding
    and swatch, so no triangle of the result lies across a cut."""
    out = Piece()
    for k, key in enumerate(piece.keys):
        parts = [list(piece.corners[k * 3 : k * 3 + 3])]
        for axis, planes in enumerate(cuts):
            for cut in planes:
                split: list[list[Vec]] = []
                for polygon in parts:
                    for side in (False, True):
                        kept = _clip(polygon, axis, cut, side)
                        if len(kept) >= 3 and _area(kept) > 1e-12:
                            split.append(kept)
                parts = split
        for polygon in parts:
            for m in range(1, len(polygon) - 1):
                out.corners += [polygon[0], polygon[m], polygon[m + 1]]
                out.keys.append(key)
    return out


def _cuts(size_mm: Sequence[int], *zones: Sequence[Zone]) -> list[list[float]]:
    """The planes, glTF metres, at every zone edge: size order (width, depth, height) to x, y, z."""
    width, depth, _height = size_mm
    low_faces = {0: -width / 2000, 1: -depth / 2000, 2: 0.0}
    planes: dict[int, set[float]] = {0: set(), 1: set(), 2: set()}
    for stated in zones:
        for axis, zone in enumerate(stated):
            if zone is not None:
                planes[axis] |= {low_faces[axis] + edge / 1000 for edge in zone}
    # glTF x is the width, y the height, z the depth.
    return [sorted(planes[0]), sorted(planes[2]), sorted(planes[1])]


def _module(
    piece: Piece, size_mm: tuple[int, int, int], stretch: Sequence[Zone], repeat: Sequence[Zone]
) -> Module:
    cut = split_at(piece, _cuts(size_mm, stretch, repeat))
    return Module(
        cut, size_mm, (stretch[0], stretch[1], stretch[2]), (repeat[0], repeat[1], repeat[2])
    )


def arcade_block(row: Mapping[str, Any]) -> Module:
    """``architecture.arcade_block`` as a module: its end walls about one bay of an arch on piers
    before the loggia's dark back, an arched window over it on each upper storey, the ground storey
    and its cornice below, the eaves and an optional roof balustrade above. The bay repeats across,
    the upper storey up, and the plain body between the back wall and the loggia stretches."""
    width_mm, depth_mm, height_mm = row["size_mm"]
    bays, storeys, kind, steps = row["bays"], row["storeys"], row["arch"], row["segments"]
    railed = row["roof_balustrade"]
    bay_mm = round((width_mm - 2 * OVERHANG_MM - 2 * END_WALL_MM) / bays)
    ground_mm = round(height_mm * row["ground_share_permille"] / 1000)
    top_mm = TOP_MM[railed]
    storey_mm = round((height_mm - ground_mm - 700 - top_mm) / storeys) if storeys else 0
    body_depth_mm = depth_mm - 2 * OVERHANG_MM
    loggia_mm = min(round(body_depth_mm * 0.35), row["loggia_depth_mm"])
    size = (
        2 * OVERHANG_MM + 2 * END_WALL_MM + bay_mm,
        depth_mm,
        ground_mm + 700 + storey_mm + top_mm,
    )
    w, d, bay = (size[0] - 2 * OVERHANG_MM) / 1000, body_depth_mm / 1000, bay_mm / 1000
    ground, storey, loggia, end = (
        ground_mm / 1000,
        storey_mm / 1000,
        loggia_mm / 1000,
        END_WALL_MM / 1000,
    )
    front, back = d / 2, -d / 2
    pier = bay * row["pier_share_permille"] / 1000
    piece = Piece()
    half = bay / 2 - pier / 2
    arch = (0.0, half, ground * 0.62, min(half, ground * 0.3))
    arched_wall(piece, (-w / 2, w / 2), (front - 0.8, front), (0, ground), [arch], steps, kind)
    piece.box((-w / 2, w / 2), (0, ground), (back, front - loggia), "stone", "xXyYz")
    piece.face(
        [
            (-w / 2 + end, 0.02, front - loggia + 0.01),
            (w / 2 - end, 0.02, front - loggia + 0.01),
            (w / 2 - end, ground - 0.2, front - loggia + 0.01),
            (-w / 2 + end, ground - 0.2, front - loggia + 0.01),
        ],
        "shade",
        (0, 0, 1),
    )
    piece.box((-w / 2, w / 2), (ground - 0.6, ground), (front - loggia, front - 0.8), "stone", "y")
    piece.box((-w / 2, w / 2), (0, 0.05), (front - loggia, front), "trim", "Y")
    piece.box((-w / 2, -w / 2 + end), (0, ground), (front - loggia, front), "stone")
    piece.box((w / 2 - end, w / 2), (0, ground), (front - loggia, front), "stone")
    cornice(piece, (-w / 2, w / 2), (back, front), ground, 0.7, 0.18)
    eaves = ground + 0.7 + storey
    if storeys:
        y0 = ground + 0.7
        piece.box((-w / 2, w / 2), (y0, eaves), (back, front - 0.25), "stone", "xXz")
        window = min(bay * 0.18, 1.1)
        spring = y0 + storey * 0.6
        arched_wall(
            piece,
            (-w / 2, w / 2),
            (front - 0.25, front),
            (y0, eaves),
            [(0.0, window, spring, window)],
            8,
            kind,
        )
        sill = y0 + storey * 0.25
        piece.face(
            [
                (-window, sill, front - 0.249),
                (window, sill, front - 0.249),
                (window, spring, front - 0.249),
                (-window, spring, front - 0.249),
            ],
            "glass",
            (0, 0, 1),
        )
        piece.box(
            (-window - 0.15, window + 0.15),
            (sill - 0.18, sill),
            (front - 0.05, front + 0.25),
            "trim",
        )
        # Each storey's string course at its top, so every copy carries one.
        piece.box(
            (-w / 2 - 0.05, w / 2 + 0.05),
            (eaves - 0.18, eaves),
            (back - 0.05, front + 0.12),
            "trim",
        )
    cornice(piece, (-w / 2, w / 2), (back, front), eaves, 0.6, 0.25)
    if railed:
        # Three runs, so no baluster stands across a bay's edge and every copy's balusters keep step.
        runs = [(-w / 2 + 0.2, -bay / 2), (-bay / 2, bay / 2), (bay / 2, w / 2 - 0.2)]
        for z in (front - 0.2, back + 0.2):
            for x0, x1 in runs:
                if x1 - x0 >= 0.32:
                    balustrade_run(piece, (x0, x1), z, eaves + 0.6, 1.05)
    width_zone = (OVERHANG_MM + END_WALL_MM, OVERHANG_MM + END_WALL_MM + bay_mm)
    depth_zone = (
        OVERHANG_MM + BODY_MARGINS_MM[0],
        depth_mm - OVERHANG_MM - loggia_mm - BODY_MARGINS_MM[1],
    )
    height_zone = (ground_mm + 700, ground_mm + 700 + storey_mm) if storeys else None
    return _module(piece, size, (None, depth_zone, None), (width_zone, None, height_zone))


def tower(row: Mapping[str, Any]) -> Module:
    """``architecture.tower`` as a module: one stage of its shaft (a band at its top, a small window
    in each face) under the open belfry and the roof. The stage repeats up; the plan is scaled."""
    width_mm, depth_mm, height_mm = row["size_mm"]
    roof, stages, kind = row["roof"], row["stages"], row["arch"]
    roof_mm = {
        "pyramid": round(height_mm * 0.22),
        "dome": round(height_mm * 0.16),
        "terrace": 1100,
    }[roof]
    belfry_mm = round(height_mm * 0.16)
    stage_mm = round((height_mm - roof_mm - belfry_mm) / stages)
    size = (width_mm, depth_mm, stage_mm + belfry_mm + roof_mm)
    w, d = width_mm / 1000, depth_mm / 1000
    stage, belfry, roof_h = stage_mm / 1000, belfry_mm / 1000, roof_mm / 1000
    piece = Piece()
    a = min(w, d) / 2 * 0.86
    piece.box((-a, a), (0, stage), (-a, a), "stone", "xXzZ")
    piece.box((-a - 0.15, a + 0.15), (stage - 0.35, stage), (-a - 0.15, a + 0.15), "trim")
    half_w, half_h, middle, face = a * 0.18, stage * 0.3, stage / 2, a + 0.01
    for sign in (1.0, -1.0):
        piece.face(
            [
                (-half_w, middle - half_h, sign * face),
                (half_w, middle - half_h, sign * face),
                (half_w, middle + half_h, sign * face),
                (-half_w, middle + half_h, sign * face),
            ],
            "shade",
            (0, 0, sign),
        )
        piece.face(
            [
                (sign * face, middle - half_h, -half_w),
                (sign * face, middle - half_h, half_w),
                (sign * face, middle + half_h, half_w),
                (sign * face, middle + half_h, -half_w),
            ],
            "shade",
            (sign, 0, 0),
        )
    inner = a - TOWER_SETBACK_M
    y0, y1 = stage, stage + belfry
    thick, opening = inner * 0.28, inner * 0.42
    arch = [(0.0, opening, y0 + belfry * 0.55, min(opening, belfry * 0.3))]
    for sign in (1.0, -1.0):
        wall = Piece()
        arched_wall(
            wall, (-inner, inner), (inner - thick, inner), (y0, y1), arch, row["segments"], kind
        )
        _mirror_z(piece, wall, sign)
        side = Piece()
        narrow = [
            (0.0, min(opening, inner - thick - 0.3), y0 + belfry * 0.55, min(opening, belfry * 0.3))
        ]
        arched_wall(
            side,
            (-inner + thick, inner - thick),
            (inner - thick, inner),
            (y0, y1),
            narrow,
            row["segments"],
            kind,
        )
        _turn(piece, side, sign)
    piece.box((-inner * 0.55, inner * 0.55), (y0, y1 - 0.4), (-inner * 0.55, inner * 0.55), "shade")
    piece.box((-inner - 0.2, inner + 0.2), (y1 - 0.4, y1), (-inner - 0.2, inner + 0.2), "trim")
    if roof == "pyramid":
        piece.cone((0, y1, 0), inner * 1.12, roof_h * 0.92, 4, "roof")
        piece.prism(1, (0, y1 + roof_h * 0.96, 0), 0.08, roof_h * 0.08, 6, "metal")
    elif roof == "dome":
        rings, sides = 8, 16
        for i in range(rings):
            a0, a1 = i / rings * math.pi / 2, (i + 1) / rings * math.pi / 2
            for k in range(sides):
                b0, b1 = k / sides * 2 * math.pi, (k + 1) / sides * 2 * math.pi

                def at(lat: float, lon: float) -> Vec:
                    return (
                        inner * math.cos(lat) * math.cos(lon),
                        y1 + roof_h * math.sin(lat),
                        inner * math.cos(lat) * math.sin(lon),
                    )

                mid_lat, mid_lon = (a0 + a1) / 2, (b0 + b1) / 2
                outward = (
                    math.cos(mid_lat) * math.cos(mid_lon),
                    math.sin(mid_lat),
                    math.cos(mid_lat) * math.sin(mid_lon),
                )
                piece.face([at(a0, b0), at(a0, b1), at(a1, b1), at(a1, b0)], "roof", outward)
    else:
        for z in (inner - 0.15, -inner + 0.15):
            balustrade_run(
                piece, (-inner + 0.15, inner - 0.15), z, y1, min(1.0, size[2] / 1000 - y1)
            )
    return _module(piece, size, (None, None, None), (None, None, (0, stage_mm)))


def hall(row: Mapping[str, Any]) -> Module:
    """``architecture.hall`` as a module: its two gable ends about one bay of an aisle arch below a
    clerestory window on each long side, under the barrel roof. The bay repeats along the hall; its
    section is scaled."""
    width_mm, depth_mm, height_mm = row["size_mm"]
    bays, kind = row["bays"], row["arch"]
    bay_mm = round((width_mm - 2 * HALL_END_MM) / bays)
    size = (2 * HALL_END_MM + bay_mm, depth_mm, height_mm)
    w, d, h = size[0] / 1000, depth_mm / 1000, height_mm / 1000
    bay = bay_mm / 1000
    aisle_h, aisle_d, clere = h * 0.38, d * 0.22, h * 0.72
    nave = d - 2 * aisle_d
    piece = Piece()
    for sign in (1.0, -1.0):
        side = Piece()
        arches = [(0.0, bay * 0.33, aisle_h * 0.55, min(bay * 0.33, aisle_h * 0.35))]
        arched_wall(
            side, (-w / 2, w / 2), (d / 2 - 0.7, d / 2), (0, aisle_h), arches, row["segments"], kind
        )
        windows = [
            (
                0.0,
                bay * 0.2,
                aisle_h + (clere - aisle_h) * 0.55,
                min(bay * 0.2, (clere - aisle_h) * 0.3),
            )
        ]
        arched_wall(
            side,
            (-w / 2, w / 2),
            (nave / 2 - 0.6, nave / 2),
            (aisle_h + 0.5, clere),
            windows,
            row["segments"],
            kind,
        )
        for cx, half, spring, _ in windows:
            side.face(
                [
                    (cx - half, aisle_h + 1.2, nave / 2 - 0.59),
                    (cx + half, aisle_h + 1.2, nave / 2 - 0.59),
                    (cx + half, spring, nave / 2 - 0.59),
                    (cx - half, spring, nave / 2 - 0.59),
                ],
                "glass",
                (0, 0, 1),
            )
        side.box((-w / 2, w / 2), (aisle_h, aisle_h + 0.5), (nave / 2, d / 2), "trim")
        side.box((-w / 2, w / 2), (0, aisle_h), (nave / 2, nave / 2 + 0.6), "shade")
        _mirror_z(piece, side, sign)
    piece.box(
        (-w / 2 + 0.6, w / 2 - 0.6),
        (aisle_h + 0.5, clere),
        (-nave / 2 + 0.6, nave / 2 - 0.6),
        "shade",
        "Y",
    )
    rise, segments = h - clere, 24
    for i in range(segments):
        a0, a1 = math.pi * i / segments, math.pi * (i + 1) / segments
        z0, z1 = nave / 2 * math.cos(a0), nave / 2 * math.cos(a1)
        y0, y1 = clere + rise * math.sin(a0), clere + rise * math.sin(a1)
        middle = (a0 + a1) / 2
        piece.face(
            [(-w / 2, y0, z0), (w / 2, y0, z0), (w / 2, y1, z1), (-w / 2, y1, z1)],
            "roof",
            (0, math.sin(middle), math.cos(middle)),
        )
        for x, sign in ((-w / 2, -1.0), (w / 2, 1.0)):
            gable = x - sign * 0.06
            piece.face(
                [(gable, clere, 0.0), (gable, y0, z0), (gable, y1, z1)], "stone", (sign, 0, 0)
            )
    for x, sign in ((-w / 2, -1.0), (w / 2, 1.0)):
        piece.face(
            [
                (x, aisle_h + 0.5, -nave / 2),
                (x, aisle_h + 0.5, nave / 2),
                (x, clere, nave / 2),
                (x, clere, -nave / 2),
            ],
            "stone",
            (sign, 0, 0),
        )
        ring = [
            (
                x - sign * 0.03,
                clere + rise * 0.3 + rise * 0.28 * math.sin(2 * math.pi * k / 16),
                rise * 0.28 * math.cos(2 * math.pi * k / 16),
            )
            for k in range(16)
        ]
        piece.face(ring, "glass", (sign, 0, 0))
    width_zone = (HALL_END_MM, HALL_END_MM + bay_mm)
    return _module(piece, size, (None, None, None), (width_zone, None, None))


#: The recipes a kit pinned to appearance catalog version 3 makes as modules; every other
#: architecture recipe is made whole, as ``architecture.py`` makes it, and scaled within bounds.
ASSEMBLED_RECIPES: dict[str, Callable[[Mapping[str, Any]], Module]] = {
    "arcade_block": arcade_block,
    "tower": tower,
    "hall": hall,
}


def validate_assembled_row(row: Mapping[str, Any]) -> None:
    """Refuse a row whose module would not stay whole, before anything is made: a bay narrower than
    an arch on its piers with a window over it, or a storey lower than a person's room under its
    window. The row has passed ``architecture.validate_architecture_row``."""
    recipe = row["recipe"]
    width_mm, _depth_mm, height_mm = row["size_mm"]
    if recipe == "arcade_block":
        if (width_mm - 2 * OVERHANG_MM - 2 * END_WALL_MM) / row["bays"] < LEAST_BAY_MM:
            raise ValueError(f"arcade_block bays are at least {LEAST_BAY_MM} mm")
        ground_mm = round(height_mm * row["ground_share_permille"] / 1000)
        above = height_mm - ground_mm - 700 - TOP_MM[row["roof_balustrade"]]
        if row["storeys"] and above / row["storeys"] < LEAST_STOREY_MM:
            raise ValueError(f"arcade_block storeys are at least {LEAST_STOREY_MM} mm")
    elif recipe == "hall":
        if (width_mm - 2 * HALL_END_MM) / row["bays"] < LEAST_BAY_MM:
            raise ValueError(f"hall bays are at least {LEAST_BAY_MM} mm")
