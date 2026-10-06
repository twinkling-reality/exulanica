"""The authored style packs: a toon town, a cozy town and a finished town, written from this file.

    uv run python scripts/style_packs/authored_packs.py          # write the packs
    uv run python scripts/style_packs/authored_packs.py --check  # refuse if a committed byte differs

Each pack is ``assets/style-packs/packs/<pack id>/manifest.json`` (canonical JSON and one newline)
and the pieces it lists under ``pieces/``. Every piece is built here from boxes, prisms, cones and
faceted spheres, each triangle coloured by one swatch of its pack's palette, and written by the shared
piece writer (``exulanica_pieces.geometry.glb``), so running this again reproduces every byte;
``tests/test_authored_style_packs.py`` holds the committed files to that and reads each manifest with
the product's reader.

Pieces are glTF metres, +Y up, +Z front, pivot at the base centre. A window or a door is a frame
whose bars keep their size, so it states stretch zones between them; a car, a tree and a fence are
scaled whole. Positions are rounded to a tenth of a millimetre before they are written, so a float's
last bit never decides a byte.

The packs are CC0-1.0 and authored by Exulanica: nothing in them is copied from another work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import numpy as np

from exulanica.grammar.grammars.city.facade import OPENING_SHAPE
from exulanica.grammar.grammars.site.layout import DOOR_HEIGHT_MM, INNER_WALL_MM, OUTER_WALL_MM
from exulanica.world import style_packs
from exulanica_pieces.colour import read_table
from exulanica_pieces.geometry.glb import write_glb
from exulanica_pieces.geometry.mesh import Mesh

ROOT: Final = Path(__file__).resolve().parents[2]
PACKS: Final = Path("assets/style-packs/packs")


def load_kind_catalogs_bounds() -> list[dict[str, Any]]:
    """The kinds' bounds catalog, whose door widths a site's doors are cut at."""
    document = json.loads(
        (ROOT / "assets/catalogs/world-kinds/kind-bound.v1.json").read_text(encoding="utf-8")
    )
    return list(document["entries"])


Vec = tuple[float, float, float]


def rgb(code: str) -> list[int]:
    return [int(code[i : i + 2], 16) for i in (1, 3, 5)]


# ------------------------------------------------------------------------------------ geometry


@dataclass
class Piece:
    """Triangles, three corners each, and the swatch key of each."""

    corners: list[Vec] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)

    def face(self, points: Sequence[Vec], key: str, outward: Vec) -> None:
        """A convex polygon as a fan, wound so its normal points along ``outward``."""
        a = np.asarray(points[0], dtype=np.float64)
        normal = np.cross(np.asarray(points[1]) - a, np.asarray(points[2]) - a)
        ordered = (
            list(points) if float(normal @ np.asarray(outward)) > 0 else list(reversed(points))
        )
        for k in range(1, len(ordered) - 1):
            self.corners += [ordered[0], ordered[k], ordered[k + 1]]
            self.keys.append(key)

    def box(
        self, x: Vec2, y: Vec2, z: Vec2, key: str | Callable[[str], str], faces: str = "xXyYzZ"
    ) -> None:
        """An axis-aligned box; ``faces`` names the faces drawn (x for -X, X for +X, and so on)."""
        (x0, x1), (y0, y1), (z0, z1) = x, y, z
        quads = {
            "X": ([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], (1.0, 0.0, 0.0)),
            "x": ([(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)], (-1.0, 0.0, 0.0)),
            "Y": ([(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)], (0.0, 1.0, 0.0)),
            "y": ([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], (0.0, -1.0, 0.0)),
            "Z": ([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], (0.0, 0.0, 1.0)),
            "z": ([(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)], (0.0, 0.0, -1.0)),
        }
        for name in faces:
            points, outward = quads[name]
            self.face(points, key(name) if callable(key) else key, outward)

    def prism(
        self, axis: int, centre: Vec, radius: float, length: float, sides: int, key: str
    ) -> None:
        """A regular prism of ``sides`` faces about ``axis`` (0 x, 1 y, 2 z), capped at both ends."""
        other = [i for i in range(3) if i != axis]

        def point(angle: float, along: float) -> Vec:
            p = list(centre)
            p[axis] += along
            p[other[0]] += radius * math.cos(angle)
            p[other[1]] += radius * math.sin(angle)
            return (p[0], p[1], p[2])

        angles = [2 * math.pi * (k + 0.5) / sides for k in range(sides)]
        half = length / 2
        for k, angle in enumerate(angles):
            following = angles[(k + 1) % sides]
            middle = (angle + following) / 2
            outward = [0.0, 0.0, 0.0]
            outward[other[0]], outward[other[1]] = math.cos(middle), math.sin(middle)
            corners = [
                point(angle, -half),
                point(following, -half),
                point(following, half),
                point(angle, half),
            ]
            self.face(corners, key, (outward[0], outward[1], outward[2]))
        for sign in (-1.0, 1.0):
            outward = [0.0, 0.0, 0.0]
            outward[axis] = sign
            self.face(
                [point(angle, sign * half) for angle in angles],
                key,
                (outward[0], outward[1], outward[2]),
            )

    def cone(self, centre: Vec, radius: float, height: float, sides: int, key: str) -> None:
        """A cone standing on ``centre``, its base drawn."""
        cx, cy, cz = centre
        apex = (cx, cy + height, cz)
        ring = [
            (
                cx + radius * math.cos(2 * math.pi * k / sides),
                cy,
                cz + radius * math.sin(2 * math.pi * k / sides),
            )
            for k in range(sides)
        ]
        for k in range(sides):
            a, b = ring[k], ring[(k + 1) % sides]
            middle = 2 * math.pi * (k + 0.5) / sides
            self.face([a, b, apex], key, (math.cos(middle), radius / height, math.sin(middle)))
        self.face(ring, key, (0.0, -1.0, 0.0))

    def ball(self, centre: Vec, radius: Vec, keys: Sequence[str]) -> None:
        """A faceted ellipsoid (an icosahedron subdivided once), its faces taking ``keys`` in turn."""
        t = (1 + math.sqrt(5)) / 2
        vertices = [
            np.array(v, dtype=np.float64)
            for v in (
                (-1, t, 0),
                (1, t, 0),
                (-1, -t, 0),
                (1, -t, 0),
                (0, -1, t),
                (0, 1, t),
                (0, -1, -t),
                (0, 1, -t),
                (t, 0, -1),
                (t, 0, 1),
                (-t, 0, -1),
                (-t, 0, 1),
            )
        ]
        faces = [
            (0, 11, 5),
            (0, 5, 1),
            (0, 1, 7),
            (0, 7, 10),
            (0, 10, 11),
            (1, 5, 9),
            (5, 11, 4),
            (11, 10, 2),
            (10, 7, 6),
            (7, 1, 8),
            (3, 9, 4),
            (3, 4, 2),
            (3, 2, 6),
            (3, 6, 8),
            (3, 8, 9),
            (4, 9, 5),
            (2, 4, 11),
            (6, 2, 10),
            (8, 6, 7),
            (9, 8, 1),
        ]
        unit = [v / np.linalg.norm(v) for v in vertices]
        fine: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
        for a, b, c in faces:
            ab, bc, ca = (unit[a] + unit[b]), (unit[b] + unit[c]), (unit[c] + unit[a])
            ab, bc, ca = ab / np.linalg.norm(ab), bc / np.linalg.norm(bc), ca / np.linalg.norm(ca)
            fine += [(unit[a], ab, ca), (ab, unit[b], bc), (ca, bc, unit[c]), (ab, bc, ca)]
        scale = np.array(radius)
        middle = np.array(centre)
        for index, triangle in enumerate(fine):
            points = [tuple(float(x) for x in middle + p * scale) for p in triangle]
            outward = sum(triangle) / 3
            self.face(
                points,
                keys[index % len(keys)],
                (float(outward[0]), float(outward[1]), float(outward[2])),
            )  # type: ignore[arg-type]

    def bytes(self, palette: Sequence[dict[str, Any]], table: Sequence[int]) -> bytes:
        index = {swatch["key"]: k for k, swatch in enumerate(palette)}
        positions = np.round(np.asarray(self.corners, dtype=np.float64), 4)
        triangles = np.arange(len(positions), dtype=np.int64).reshape(-1, 3)
        swatch = np.asarray([index[key] for key in self.keys], dtype=np.int64)
        colours = np.asarray([palette[k]["srgb8"] for k in np.repeat(swatch, 3)], dtype=np.uint8)
        srgb = [s["srgb8"] for s in palette]
        return write_glb(Mesh(positions, triangles, colours), swatch, srgb, table)


Vec2 = tuple[float, float]


@dataclass(frozen=True)
class FrameStyle:
    """A window or door frame: its bars, how far it sits back in the hole, its glazing bars."""

    frame_mm: int
    depth_mm: int
    recess_mm: int
    bar_mm: int
    mullions: int
    transom: bool
    frame: str
    glass: str
    bars: str


def window_piece(
    style: FrameStyle, size_mm: tuple[int, int, int]
) -> tuple[Piece, list[list[int] | None]]:
    """A window that fills its hole: a frame, a pane and glazing bars, and its stretch zones."""
    w, d, h = (n / 1000 for n in size_mm)
    f, depth, recess, bar = (
        style.frame_mm / 1000,
        style.depth_mm / 1000,
        style.recess_mm / 1000,
        style.bar_mm / 1000,
    )
    piece = Piece()
    front = d / 2 - recess
    back = front - depth
    pane = (front + back) / 2
    x0, x1 = -w / 2, w / 2
    # The frame's bars: the front face and the faces toward the pane, which are the ones seen.
    piece.box((x0, x0 + f), (0, h), (back, front), style.frame, "XZ")
    piece.box((x1 - f, x1), (0, h), (back, front), style.frame, "xZ")
    piece.box((x0 + f, x1 - f), (0, f), (back, front), style.frame, "YZ")
    piece.box((x0 + f, x1 - f), (h - f, h), (back, front), style.frame, "yZ")
    piece.face(
        [(x0 + f, f, pane), (x1 - f, f, pane), (x1 - f, h - f, pane), (x0 + f, h - f, pane)],
        style.glass,
        (0, 0, 1),
    )
    bar_front = front - 0.006
    for k in range(style.mullions):
        u = x0 + f + (w - 2 * f) * (k + 1) / (style.mullions + 1)
        piece.box((u - bar / 2, u + bar / 2), (f, h - f), (pane, bar_front), style.bars, "xXZ")
    if style.transom:
        v = f + (h - 2 * f) * 0.68
        piece.box(
            (x0 + f, x1 - f), (v - bar / 2, v + bar / 2), (pane, bar_front), style.bars, "yYZ"
        )
    zones = [
        [style.frame_mm, size_mm[0] - style.frame_mm],
        [0, round((back + d / 2) * 1000)],
        [style.frame_mm, size_mm[2] - style.frame_mm],
    ]
    return piece, zones


def door_piece(
    style: FrameStyle, panel: str, size_mm: tuple[int, int, int]
) -> tuple[Piece, list[list[int] | None]]:
    """A door that fills its hole: a frame on three sides, a panel with two raised fields and a light."""
    w, d, h = (n / 1000 for n in size_mm)
    f, depth, recess = style.frame_mm / 1000, style.depth_mm / 1000, style.recess_mm / 1000
    piece = Piece()
    front = d / 2 - recess
    back = front - depth
    x0, x1 = -w / 2, w / 2
    piece.box((x0, x0 + f), (0, h), (back, front), style.frame, "XZ")
    piece.box((x1 - f, x1), (0, h), (back, front), style.frame, "xZ")
    piece.box((x0 + f, x1 - f), (h - f, h), (back, front), style.frame, "yZ")
    leaf = back + depth * 0.35
    piece.face(
        [(x0 + f, 0, leaf), (x1 - f, 0, leaf), (x1 - f, h - f, leaf), (x0 + f, h - f, leaf)],
        panel,
        (0, 0, 1),
    )
    margin = 0.09
    light_top = h - f - margin
    light_bottom = light_top - 0.32
    piece.face(
        [
            (x0 + f + margin, light_bottom, leaf + 0.002),
            (x1 - f - margin, light_bottom, leaf + 0.002),
            (x1 - f - margin, light_top, leaf + 0.002),
            (x0 + f + margin, light_top, leaf + 0.002),
        ],
        style.glass,
        (0, 0, 1),
    )
    field_top = light_bottom - margin
    split = margin + (field_top - margin) * 0.45
    for y0, y1 in ((margin, split - margin / 2), (split + margin / 2, field_top)):
        piece.box(
            (x0 + f + margin, x1 - f - margin), (y0, y1), (leaf, leaf + 0.025), panel, "xXyYZ"
        )
    zones = [
        [style.frame_mm, size_mm[0] - style.frame_mm],
        [0, round((back + d / 2) * 1000)],
        [style.frame_mm, size_mm[2] - style.frame_mm],
    ]
    return piece, zones


@dataclass(frozen=True)
class VehicleStyle:
    glass: str
    tyre: str
    lamp: str
    tail: str
    rounded: bool


#: The swatch a vehicle piece paints its body with; the page draws it in the vehicle's own colour as
#: the pack states it (``vehicle_<colour>``), so one piece serves every colour the traffic drives.
BODY: Final = "vehicle_body"


def _wheels(
    piece: Piece, style: VehicleStyle, x: float, axles: Sequence[float], radius: float
) -> None:
    for side in (-x, x):
        for z in axles:
            # A flat of the octagon on the ground.
            piece.prism(0, (side, radius * math.cos(math.pi / 8), z), radius, 0.24, 8, style.tyre)


def _windows(
    piece: Piece,
    style: VehicleStyle,
    x: float,
    low: float,
    high: float,
    back: float,
    front: float,
    panes: int,
) -> None:
    """Side windows a millimetre proud of a cabin's sides, inset so its pillars show, and the screens."""
    span = (front - back - 0.12 * (panes + 1)) / panes
    for side, outward in ((-x - 0.001, -1.0), (x + 0.001, 1.0)):
        for k in range(panes):
            z0 = back + 0.12 + k * (span + 0.12)
            piece.face(
                [
                    (side, low, z0),
                    (side, low, z0 + span),
                    (side, high, z0 + span),
                    (side, high, z0),
                ],
                style.glass,
                (outward, 0.0, 0.0),
            )
    inset = x - 0.12
    piece.face(
        [
            (-inset, low, front + 0.001),
            (inset, low, front + 0.001),
            (inset, high, front + 0.001),
            (-inset, high, front + 0.001),
        ],
        style.glass,
        (0.0, 0.0, 1.0),
    )
    piece.face(
        [
            (-inset, low, back - 0.001),
            (inset, low, back - 0.001),
            (inset, high, back - 0.001),
            (-inset, high, back - 0.001),
        ],
        style.glass,
        (0.0, 0.0, -1.0),
    )


def _lamps(
    piece: Piece, style: VehicleStyle, x: float, y: float, front: float, back: float
) -> None:
    for side in (-x, x):
        piece.box((side - 0.15, side + 0.15), (y, y + 0.11), (front, front + 0.01), style.lamp, "Z")
        piece.box((side - 0.15, side + 0.15), (y, y + 0.11), (back - 0.01, back), style.tail, "z")


def car_piece(style: VehicleStyle, length: float, cabin: tuple[float, float], roof: float) -> Piece:
    """A car 1.8 m wide and ``length`` long, its nose toward +Z: a body, a cabin from ``cabin`` (its
    back and front along the car) whose pillars and roof are the body's, wheels and lamps."""
    piece = Piece()
    half = length / 2
    piece.box((-0.86, 0.86), (0.28, 0.8), (-half, half), BODY)
    base = 0.8
    if style.rounded:
        piece.box((-0.8, 0.8), (0.8, 0.88), (-half + 0.1, half - 0.1), BODY, "xXYzZ")
        base = 0.88
    back, front = cabin
    piece.box((-0.76, 0.76), (base, roof), (back, front), BODY, "xXYzZ")
    _windows(piece, style, 0.76, base + 0.09, roof - 0.07, back, front, 2)
    _wheels(piece, style, 0.78, (-half + 0.78, half - 0.78), 0.32)
    _lamps(piece, style, 0.6, 0.6, half, -half)
    return piece


def wagon_piece(style: VehicleStyle) -> Piece:
    """A van 1.85 m wide, 4.6 m long and 1.75 m tall: a short bonnet and a tall box behind it."""
    piece = Piece()
    piece.box((-0.9, 0.9), (0.28, 0.85), (-2.3, 2.3), BODY)
    piece.box((-0.86, 0.86), (0.85, 1.75), (-2.25, 1.25), BODY, "xXYzZ")
    _windows(piece, style, 0.86, 0.98, 1.6, -2.1, 1.25, 3)
    _wheels(piece, style, 0.8, (-1.55, 1.55), 0.33)
    _lamps(piece, style, 0.62, 0.62, 2.3, -2.3)
    return piece


def bus_piece(style: VehicleStyle) -> Piece:
    """A city bus 2.55 m wide, 12 m long and 3.1 m tall: a long body, a band of windows, six wheels."""
    piece = Piece()
    piece.box((-1.275, 1.275), (0.35, 3.1), (-6.0, 6.0), BODY)
    _windows(piece, style, 1.275, 1.35, 2.65, -5.8, 5.85, 6)
    _wheels(piece, style, 1.12, (-4.2, -2.9, 4.0), 0.48)
    _lamps(piece, style, 0.95, 0.75, 6.0, -6.0)
    return piece


def tree_piece(trunk: str, leaves: Sequence[str], shape: str) -> Piece:
    """A tree 3.2 m across and 6 m tall: a trunk and a canopy of faceted balls or stacked cones."""
    piece = Piece()
    piece.prism(1, (0.0, 1.2, 0.0), 0.17, 2.4, 6, trunk)
    if shape == "cones":
        piece.cone((0.0, 1.9, 0.0), 1.55, 2.6, 8, leaves[0])
        piece.cone((0.0, 3.3, 0.0), 1.15, 2.7, 8, leaves[-1])
    else:
        piece.ball((0.0, 3.85, 0.0), (1.6, 1.55, 1.6), leaves)
        piece.ball((0.55, 4.9, 0.25), (0.95, 0.9, 0.95), leaves[::-1])
    return piece


def fence_piece(wood: str, posts: str) -> Piece:
    """A fence panel 2 m long and 1.1 m tall: two posts and two rails."""
    piece = Piece()
    for x in (-0.96, 0.96):
        piece.box((x - 0.04, x + 0.04), (0.0, 1.1), (-0.04, 0.04), posts)
    for y in (0.35, 0.8):
        piece.box((-0.92, 0.92), (y, y + 0.12), (-0.025, 0.025), wood, "yYzZ")
    return piece


# ------------------------------------------------------------------------------------ the packs


def swatch(
    key: str, code: str, roughness: int = 850, metalness: int = 0, emission: int = 0
) -> dict[str, Any]:
    return {
        "key": key,
        "srgb8": rgb(code),
        "roughness_permille": roughness,
        "metalness_permille": metalness,
        "emission_permille": emission,
    }


def preset(
    *,
    exposure: int,
    tone: str,
    sky: tuple[str, str, str, str],
    sky_intensity: int,
    glow: int,
    clouds: tuple[int, str, str, int, int] | None,
    fog: tuple[int, str],
    sun: tuple[int, int, str, int, str],
    environment: int,
    contact: tuple[str, int, int],
    bloom: int,
    grading: tuple[int, int, int, str],
    enhance: tuple[int, int, int],
    vignette: int,
) -> dict[str, Any]:
    """A light preset in the manifest's whole-number units, from the values a look is drawn with."""
    zenith, horizon, ground, bounce = sky
    elevation, azimuth, sun_colour, intensity, shadow = sun
    return {
        "exposure_permille": exposure,
        "tone_mapping": tone,
        "sky": {
            "zenith": rgb(zenith),
            "horizon": rgb(horizon),
            "ground": rgb(ground),
            "bounce_ground": rgb(bounce),
            "intensity_permille": sky_intensity,
            "sun_glow_permille": glow,
            "sun_disc_permille": 30_000,
            "clouds": None
            if clouds is None
            else {
                "cover_permille": clouds[0],
                "colour": rgb(clouds[1]),
                "shade": rgb(clouds[2]),
                "scale_permille": clouds[3],
                "seed": clouds[4],
            },
            "face_texels": 128,
        },
        "fog": {"kind": "exp2", "density_micro": fog[0], "colour": rgb(fog[1])},
        "sun": {
            "elevation_mdeg": elevation * 1000,
            "azimuth_mdeg": azimuth * 1000,
            "colour": rgb(sun_colour),
            "intensity_permille": intensity,
            "shadow": {"filter": shadow},
        },
        "environment": {"intensity_permille": environment},
        "contact_shadow": {
            "mode": contact[0],
            "radius_mm": contact[1],
            "intensity_permille": contact[2],
        },
        "post": {
            "bloom": {"intensity_permille": bloom, "blur_level": 16} if bloom > 0 else None,
            "grading": {
                "brightness_permille": grading[0],
                "contrast_permille": grading[1],
                "saturation_permille": grading[2],
                "tint": rgb(grading[3]),
            },
            "enhance": {
                "shadows_permille": enhance[0],
                "highlights_permille": enhance[1],
                "midtones_permille": 0,
                "vibrance_permille": enhance[2],
                "dehaze_permille": 0,
            },
            "vignette": {
                "intensity_permille": vignette,
                "inner_permille": 550,
                "outer_permille": 1250,
                "curvature_permille": 600,
                "colour": [0, 0, 0],
            }
            if vignette > 0
            else None,
            "taa": False,
        },
    }


#: The town's texture sets as look roles (assets/style-packs/town-look-roles.v1.json), and the
#: defaults a world of another kind draws its parts with.
TOWN_WALLS: Final = (
    "brick_running_bond",
    "limestone_ashlar",
    "cast_concrete",
    "painted_render",
    "painted_timber",
    "storefront_metal",
    "awning_canvas",
)


@dataclass(frozen=True)
class PackSpec:
    pack_id: str
    title: str
    description: str
    tags: tuple[str, ...]
    presets: dict[str, dict[str, Any]]
    default_preset: str
    shading: dict[str, Any]
    edge: str
    palette: tuple[dict[str, Any], ...]
    surfaces: dict[str, dict[str, Any]]
    windows: dict[str, tuple[tuple[str, FrameStyle], ...]]
    door: tuple[FrameStyle, str]
    vehicles: VehicleStyle
    tree: tuple[str, tuple[str, ...], str]
    fence: tuple[str, str]


def surface(key: str, up: str | None = None) -> dict[str, Any]:
    return {"swatch": key, "up": up}


def textured(set_id: str, up: str | None = None) -> dict[str, Any]:
    return {"texture_set": set_id, "up": up}


TOON: Final = PackSpec(
    pack_id="exulanica.toon-town",
    title="Toon town",
    description="Bright flat colour in two light bands with dark ink lines: white frames, blue glass, round green trees and cars like toys.",
    tags=("toon", "bright", "town"),
    presets={
        "day": preset(
            exposure=920,
            tone="neutral",
            sky=("#3b82dc", "#cfe9fb", "#86c46a", "#b5b2a8"),
            sky_intensity=1000,
            glow=250,
            clouds=(420, "#ffffff", "#cddcf0", 1200, 3),
            fog=(1000, "#cfe6f5"),
            sun=(50, 150, "#fff5e6", 2100, "pcf1"),
            environment=850,
            contact=("lighting", 600, 50),
            bloom=12,
            grading=(1000, 1050, 1060, "#ffffff"),
            enhance=(60, -50, 80),
            vignette=160,
        ),
        "evening": preset(
            exposure=980,
            tone="neutral",
            sky=("#3d5fa8", "#ffc9a0", "#7fae63", "#a89a8c"),
            sky_intensity=950,
            glow=900,
            clouds=(350, "#ffe9d6", "#c98f9a", 1100, 5),
            fog=(420, "#f2c9a8"),
            sun=(13, 250, "#ffc58a", 1800, "pcf1"),
            environment=700,
            contact=("lighting", 600, 50),
            bloom=30,
            grading=(1000, 1060, 1080, "#fff4ea"),
            enhance=(80, -60, 100),
            vignette=220,
        ),
    },
    default_preset="day",
    shading={
        "model": "toon",
        "toon": {
            "shadow_edge_permille": 110,
            "light_edge_permille": 570,
            "band_share_permille": 720,
            "softness_permille": 60,
        },
        "ink": rgb("#27304a"),
    },
    edge="#7fb069",
    palette=(
        swatch("brick", "#d8694b"),
        swatch("brick_top", "#f2e6d0"),
        swatch("stone", "#f3e2c2"),
        swatch("stone_top", "#f7efe0"),
        swatch("concrete", "#f0d9b8"),
        swatch("concrete_top", "#e9e1d3"),
        swatch("render", "#8ccfb9"),
        swatch("render_top", "#f2ece0"),
        swatch("timber", "#2e7f8f"),
        swatch("metal", "#3e4d78", 550),
        swatch("metal_top", "#5d6a8f", 550),
        swatch("awning", "#ef5d6f"),
        swatch("roof", "#e0674f"),
        swatch("asphalt", "#4d5566", 900),
        swatch("kerb", "#f2eee6"),
        swatch("paint_white", "#ffffff"),
        swatch("paint_yellow", "#ffcc33"),
        swatch("paving", "#ddd3c2"),
        swatch("grass", "#86c46a", 950),
        swatch("soil", "#8cc06c", 950),
        swatch("water", "#4fb3d9", 150),
        swatch("frame", "#fbf7ef", 600),
        swatch("glass", "#7fc4ea", 120, 0, 120),
        swatch("door", "#2f6f9f", 700),
        swatch("vehicle_body", "#f9b233", 450),
        swatch("vehicle_black", "#2b2f3a", 450),
        swatch("vehicle_blue", "#3a9be0", 450),
        swatch("vehicle_grey", "#9aa3b5", 450),
        swatch("vehicle_red", "#e8505b", 450),
        swatch("vehicle_silver", "#d5dbe6", 400),
        swatch("vehicle_white", "#fbfbf7", 450),
        swatch("car_glass", "#22344d", 150),
        swatch("tyre", "#262b36", 900),
        swatch("lamp", "#fff4d6", 300, 0, 700),
        swatch("tail", "#d8323c", 400, 0, 350),
        swatch("bark", "#6e4a30", 950),
        swatch("leaf", "#58ad46", 900),
        swatch("leaf_light", "#6cc457", 900),
        swatch("picket", "#f5efe3", 800),
    ),
    surfaces={
        "wall.brick_running_bond": surface("brick", "brick_top"),
        "wall.limestone_ashlar": surface("stone", "stone_top"),
        "wall.cast_concrete": surface("concrete", "concrete_top"),
        "wall.painted_render": surface("render", "render_top"),
        "wall.painted_timber": surface("timber"),
        "wall.storefront_metal": surface("metal", "metal_top"),
        "wall.awning_canvas": surface("awning"),
        "wall.default": surface("stone", "roof"),
        "roof.default": surface("roof"),
        "road.carriageway_asphalt": surface("asphalt"),
        "road.kerb_stone": surface("kerb"),
        "road.road_paint_white": surface("paint_white"),
        "road.road_paint_yellow": surface("paint_yellow"),
        "road.default": surface("asphalt"),
        "path.footway_paving": surface("paving"),
        "path.default": surface("paving"),
        "ground.tree_pit_soil": surface("soil"),
        "ground.default": surface("grass"),
        "water.default": surface("water"),
    },
    windows={
        "window.default": (
            ("pieces/window.glb", FrameStyle(90, 70, 30, 34, 1, True, "frame", "glass", "frame")),
        ),
        "window.arch": (
            (
                "pieces/window-arch.glb",
                FrameStyle(90, 70, 30, 34, 0, True, "frame", "glass", "frame"),
            ),
        ),
    },
    door=(FrameStyle(90, 60, 20, 0, 0, False, "frame", "glass", "frame"), "door"),
    vehicles=VehicleStyle("car_glass", "tyre", "lamp", "tail", True),
    tree=("bark", ("leaf", "leaf_light"), "balls"),
    fence=("picket", "picket"),
)

COZY: Final = PackSpec(
    pack_id="exulanica.cozy-town",
    title="Cozy town",
    description="Faceted low-poly in warm late light: terracotta roofs, cream frames, lamps lit in some windows, soft fog and pastel cars.",
    tags=("cozy", "low-poly", "warm", "town"),
    presets={
        "day": preset(
            exposure=900,
            tone="aces",
            sky=("#7fa3d6", "#f6d4b2", "#93ad62", "#a99a86"),
            sky_intensity=950,
            glow=800,
            clouds=(300, "#fff3e6", "#d9b2ad", 900, 7),
            fog=(900, "#e3d6c8"),
            sun=(26, 235, "#ffdbb3", 2200, "pcf5"),
            environment=800,
            contact=("combine", 1000, 700),
            bloom=30,
            grading=(1000, 1070, 980, "#fffcf7"),
            enhance=(80, -120, 150),
            vignette=300,
        ),
        "evening": preset(
            exposure=1000,
            tone="aces",
            sky=("#4a5b91", "#ffb98a", "#7c8f55", "#8f7f72"),
            sky_intensity=900,
            glow=1400,
            clouds=(380, "#ffd9bf", "#b07f8a", 900, 11),
            fog=(1100, "#e8bfa3"),
            sun=(8, 250, "#ffb070", 1600, "pcf5"),
            environment=650,
            contact=("combine", 1000, 700),
            bloom=60,
            grading=(1000, 1080, 1000, "#fff4ea"),
            enhance=(100, -100, 180),
            vignette=340,
        ),
    },
    default_preset="day",
    shading={"model": "flat", "toon": None, "ink": None},
    edge="#88a560",
    palette=(
        swatch("brick", "#bf6f55"),
        swatch("brick_top", "#8f5a4a"),
        swatch("stone", "#ecdcc4"),
        swatch("stone_top", "#9c8a7a"),
        swatch("concrete", "#e6d2b8"),
        swatch("concrete_top", "#a89584"),
        swatch("render", "#e9bfa0"),
        swatch("render_top", "#b25d45"),
        swatch("timber", "#5f8a62"),
        swatch("metal", "#5a4740", 700),
        swatch("metal_top", "#7c5446", 700),
        swatch("awning", "#d9705a"),
        swatch("roof", "#a8563f"),
        swatch("asphalt", "#857873", 950),
        swatch("kerb", "#cdbb9f"),
        swatch("paint_white", "#f3eadb"),
        swatch("paint_yellow", "#e9bb63"),
        swatch("paving", "#d9c6aa"),
        swatch("grass", "#88a560", 950),
        swatch("soil", "#9a7a5a", 950),
        swatch("water", "#6f9fb0", 200),
        swatch("frame", "#f4ead9", 700),
        swatch("glass", "#5d6f7a", 250),
        swatch("glass_lit", "#ffcf8a", 300, 0, 450),
        swatch("door", "#4f7a58", 750),
        swatch("vehicle_body", "#8fbf98", 600),
        swatch("vehicle_black", "#4a4040", 600),
        swatch("vehicle_blue", "#98b2df", 600),
        swatch("vehicle_grey", "#b5ada5", 600),
        swatch("vehicle_red", "#e09a72", 600),
        swatch("vehicle_silver", "#d8d2c8", 500),
        swatch("vehicle_white", "#f6efe4", 600),
        swatch("car_glass", "#34444f", 300),
        swatch("tyre", "#3a322e", 950),
        swatch("lamp", "#ffe2b0", 300, 0, 700),
        swatch("tail", "#c9483e", 400, 0, 350),
        swatch("bark", "#6a4b35", 950),
        swatch("leaf", "#7fa650", 950),
        swatch("leaf_dark", "#6a9046", 950),
        swatch("fence", "#b08a62", 900),
    ),
    surfaces={
        "wall.brick_running_bond": surface("brick", "brick_top"),
        "wall.limestone_ashlar": surface("stone", "stone_top"),
        "wall.cast_concrete": surface("concrete", "concrete_top"),
        "wall.painted_render": surface("render", "render_top"),
        "wall.painted_timber": surface("timber"),
        "wall.storefront_metal": surface("metal", "metal_top"),
        "wall.awning_canvas": surface("awning"),
        "wall.default": surface("stone", "roof"),
        "roof.default": surface("roof"),
        "road.carriageway_asphalt": surface("asphalt"),
        "road.kerb_stone": surface("kerb"),
        "road.road_paint_white": surface("paint_white"),
        "road.road_paint_yellow": surface("paint_yellow"),
        "road.default": surface("asphalt"),
        "path.footway_paving": surface("paving"),
        "path.default": surface("paving"),
        "ground.tree_pit_soil": surface("soil"),
        "ground.default": surface("grass"),
        "water.default": surface("water"),
    },
    windows={
        "window.default": (
            (
                "pieces/window-lit.glb",
                FrameStyle(70, 70, 40, 30, 1, True, "frame", "glass_lit", "frame"),
            ),
            ("pieces/window.glb", FrameStyle(70, 70, 40, 30, 1, True, "frame", "glass", "frame")),
        ),
        "window.arch": (
            (
                "pieces/window-arch-lit.glb",
                FrameStyle(70, 70, 40, 30, 2, True, "frame", "glass_lit", "frame"),
            ),
            (
                "pieces/window-arch.glb",
                FrameStyle(70, 70, 40, 30, 2, True, "frame", "glass", "frame"),
            ),
        ),
    },
    door=(FrameStyle(80, 60, 20, 0, 0, False, "frame", "glass_lit", "frame"), "door"),
    vehicles=VehicleStyle("car_glass", "tyre", "lamp", "tail", True),
    tree=("bark", ("leaf", "leaf_dark"), "balls"),
    fence=("fence", "fence"),
)

FINISHED: Final = PackSpec(
    pack_id="exulanica.finished-town",
    title="Finished town",
    description="Physically lit stone, brick and render from the town's own materials, slate roofs, dark steel frames, soft sun shadows and a graded sky.",
    tags=("finished", "realistic", "town"),
    presets={
        "day": preset(
            exposure=920,
            tone="aces2",
            sky=("#2d68c4", "#d3e3f2", "#6e7c5c", "#8a8a84"),
            sky_intensity=1050,
            glow=550,
            clouds=(300, "#ffffff", "#b9c5d6", 1400, 13),
            fog=(800, "#c7d6e6"),
            sun=(36, 142, "#ffeed4", 3300, "pcf5"),
            environment=1150,
            contact=("lighting", 500, 500),
            bloom=10,
            grading=(1000, 1080, 1050, "#fffcf7"),
            enhance=(100, -60, 160),
            vignette=180,
        ),
        "evening": preset(
            exposure=1350,
            tone="aces2",
            sky=("#30477a", "#f0c7a4", "#5f6a4d", "#7a7470"),
            sky_intensity=1100,
            glow=1100,
            clouds=(340, "#ffe2cc", "#a38a96", 1400, 17),
            fog=(950, "#d9c4b6"),
            sun=(14, 258, "#ffc287", 2600, "pcf5"),
            environment=1100,
            contact=("lighting", 500, 500),
            bloom=25,
            grading=(1000, 1080, 1040, "#fff6ec"),
            enhance=(120, -80, 140),
            vignette=220,
        ),
    },
    default_preset="day",
    shading={"model": "pbr", "toon": None, "ink": None},
    edge="#6f7d58",
    palette=(
        swatch("slate", "#6e6660", 700),
        swatch("slate_warm", "#7a746c", 700),
        swatch("slate_light", "#857d72", 700),
        swatch("leads", "#6f6b66", 500, 300),
        swatch("roof", "#5c5752", 700),
        swatch("grass", "#6f7d58", 950),
        swatch("soil", "#6c7a52", 1000),
        swatch("paving", "#a39a8c", 900),
        swatch("asphalt", "#3f4246", 900),
        swatch("stone", "#cfc6b6", 900),
        swatch("water", "#3c5a6b", 80),
        swatch("frame", "#2a2e33", 450, 200),
        swatch("glass", "#3a4a58", 80, 0, 30),
        swatch("door", "#4a3a30", 650),
        swatch("vehicle_body", "#a0a4aa", 300, 600),
        swatch("vehicle_black", "#16181b", 250, 500),
        swatch("vehicle_blue", "#1f3a5a", 300, 500),
        swatch("vehicle_grey", "#6b7078", 300, 500),
        swatch("vehicle_red", "#7a1f24", 300, 400),
        swatch("vehicle_silver", "#c9ccd1", 300, 600),
        swatch("vehicle_white", "#e8e8e6", 350, 300),
        swatch("car_glass", "#1b2229", 80),
        swatch("tyre", "#1c1c1e", 900),
        swatch("lamp", "#f4f1e8", 200, 0, 600),
        swatch("tail", "#b0242c", 300, 0, 300),
        swatch("bark", "#4b3b2d", 950),
        swatch("leaf", "#4f6b3a", 900),
        swatch("leaf_dark", "#435c33", 900),
        swatch("fence", "#6b6158", 850),
    ),
    surfaces={
        "wall.brick_running_bond": textured("cc0.brick-running-bond", "slate"),
        "wall.limestone_ashlar": textured("cc0.limestone-ashlar", "slate_light"),
        "wall.cast_concrete": textured("cc0.cast-concrete", "slate_warm"),
        "wall.painted_render": textured("cc0.painted-render", "slate_warm"),
        "wall.storefront_metal": textured("cc0.storefront-metal", "leads"),
        "wall.default": surface("stone", "roof"),
        "roof.default": surface("roof"),
        "road.default": surface("asphalt"),
        "path.default": surface("paving"),
        "ground.tree_pit_soil": surface("soil"),
        "ground.default": surface("grass"),
        "water.default": surface("water"),
    },
    windows={
        "window.default": (
            ("pieces/window.glb", FrameStyle(55, 70, 40, 26, 1, True, "frame", "glass", "frame")),
        ),
        "window.arch": (
            (
                "pieces/window-arch.glb",
                FrameStyle(55, 70, 40, 26, 2, True, "frame", "glass", "frame"),
            ),
        ),
    },
    door=(FrameStyle(70, 60, 20, 0, 0, False, "frame", "glass", "frame"), "door"),
    vehicles=VehicleStyle("car_glass", "tyre", "lamp", "tail", False),
    tree=("bark", ("leaf", "leaf_dark"), "balls"),
    fence=("fence", "fence"),
)

SPECS: Final = (TOON, COZY, FINISHED)


def smallest_openings() -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """The smallest window the city grammar cuts and the smallest door a site cuts, each as width,
    depth and height in millimetres, read from the grammars and the kinds' bounds. Every frame's
    fixed parts must fit inside them, so no opening is left undressed."""
    fields = {shape.name: shape for shape in OPENING_SHAPE.fields}
    window = (
        fields["width_mm"].minimum,
        fields["reveal_depth_mm"].minimum,
        fields["height_mm"].minimum,
    )
    door_width = next(
        entry for entry in load_kind_catalogs_bounds() if entry["key"] == "door_width_mm"
    )["minimum"]
    door = (door_width, min(INNER_WALL_MM, OUTER_WALL_MM), DOOR_HEIGHT_MM)
    return window, door  # type: ignore[return-value]


WINDOW_MM: Final = (1000, 160, 1500)
DOOR_MM: Final = (1000, 160, 2100)
HATCHBACK_MM: Final = [1800, 4000, 1500]
SEDAN_MM: Final = [1800, 4600, 1440]
WAGON_MM: Final = [1850, 4600, 1750]
BUS_MM: Final = [2550, 12000, 3100]
TREE_MM: Final = [3200, 3200, 6000]
FENCE_MM: Final = [2000, 80, 1100]


def build(spec: PackSpec, table: Sequence[int]) -> dict[str, bytes]:
    """Every file of one pack, by its path inside the pack's folder."""
    palette = list(spec.palette)
    pieces: dict[str, bytes] = {}
    modules: dict[str, Any] = {}

    smallest_window, smallest_door = smallest_openings()

    def add(
        role: str, path: str, piece: Piece, size: Sequence[int], stretch: Sequence[Any]
    ) -> None:
        smallest = smallest_door if role.startswith("door.") else smallest_window
        for axis, zone in enumerate(stretch):
            if zone is not None and size[axis] - (zone[1] - zone[0]) >= smallest[axis]:
                raise SystemExit(
                    f"{spec.pack_id} {path}: its fixed parts on axis {axis} fill the smallest opening"
                )
        pieces[path] = piece.bytes(palette, table)
        modules.setdefault(role, {"variants": []})["variants"].append(
            {"file": path, "lod1": None, "size_mm": list(size), "stretch_mm": list(stretch)}
        )

    for role, variants in spec.windows.items():
        for path, frame in variants:
            piece, zones = window_piece(frame, WINDOW_MM)
            add(role, path, piece, WINDOW_MM, zones)
    door, zones = door_piece(spec.door[0], spec.door[1], DOOR_MM)
    add("door.default", "pieces/door.glb", door, DOOR_MM, zones)
    none = [None, None, None]
    style = spec.vehicles
    add(
        "vehicle.hatchback",
        "pieces/hatchback.glb",
        car_piece(style, 4.0, (-1.55, 0.45), 1.5),
        HATCHBACK_MM,
        none,
    )
    add(
        "vehicle.sedan",
        "pieces/sedan.glb",
        car_piece(style, 4.6, (-1.25, 0.65), 1.44),
        SEDAN_MM,
        none,
    )
    wagon = wagon_piece(style)
    add("vehicle.minivan", "pieces/wagon.glb", wagon, WAGON_MM, none)
    add("vehicle.panel_van", "pieces/wagon.glb", wagon, WAGON_MM, none)
    add("vehicle.rigid_city_bus", "pieces/bus.glb", bus_piece(style), BUS_MM, none)
    trunk, leaves, shape = spec.tree
    add("plant.default", "pieces/tree.glb", tree_piece(trunk, leaves, shape), TREE_MM, none)
    add("boundary.default", "pieces/fence.glb", fence_piece(*spec.fence), FENCE_MM, none)

    files = [
        {
            "path": path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "media_type": "model/gltf-binary",
        }
        for path, data in sorted(pieces.items())
    ]
    manifest = {
        "profile": style_packs.PROFILE,
        "pack_id": spec.pack_id,
        "version": 1,
        "title": spec.title,
        "description": spec.description,
        "tags": list(spec.tags),
        "origin": "authored",
        "provenance": {"kind": "authored"},
        "licence": {"id": "CC0-1.0", "attribution": None},
        "authors": ["Exulanica"],
        "base": None,
        "light": {"default_preset": spec.default_preset, "presets": spec.presets},
        "shading": spec.shading,
        "edge": {"ground": rgb(spec.edge), "drop_mm": 600, "reach_mm": 3_000_000},
        "palette": {"encoding": style_packs.COLOUR_ENCODING, "swatches": palette},
        "surfaces": spec.surfaces,
        "modules": modules,
        "files": files,
    }
    style_packs.read_manifest(manifest, style_packs.load_context(ROOT))
    out = {"manifest.json": (style_packs.canonical_json(manifest) + "\n").encode("ascii")}
    out.update(pieces)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="refuse if a committed file differs")
    args = parser.parse_args(argv)
    table, _digest = read_table(ROOT)
    stale: list[str] = []
    for spec in SPECS:
        folder = ROOT / PACKS / spec.pack_id
        for name, data in build(spec, table).items():
            path = folder / name
            if args.check:
                if not path.is_file() or path.read_bytes() != data:
                    stale.append(str(path.relative_to(ROOT)))
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    if stale:
        print("stale:\n" + "\n".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
