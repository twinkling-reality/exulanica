"""Architecture pieces for authored kits: arcades, halls, towers, colonnades, pavilions, stair
flights and balustrades, each made from a few validated numbers.

Every recipe returns a palette piece (``authored_packs.Piece``): +Y up, centred on X and Z, standing
on Y = 0 and inside its declared size, so a pack can dress a look role with it under the family's
fit (a whole structure is contained in its slot, a boundary run tiles a balustrade). The pieces use
six swatch keys, ``ARCHITECTURE_SWATCHES``: stone for walls and piers, trim for cornices, bases and
balusters, shade for the dark inside of openings, roof, metal and glass. Arches are drawn as real
openings with soffits, never as painted shapes, so light and shadow read their depth.

A piece supplies no support or navigation: a loggia, an arch or a stair is drawn, not walked.
"""

from __future__ import annotations

import math
from itertools import pairwise
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from scripts.style_packs.authored_packs import Piece

Vec = tuple[float, float, float]
Opening = tuple[float, float, float, float]

ARCHITECTURE_SWATCHES = (
    # key, sRGB8, roughness permille, metalness permille
    ("stone", (226, 214, 192), 820, 0),
    ("trim", (240, 232, 214), 700, 0),
    ("shade", (58, 52, 48), 900, 0),
    ("roof", (176, 98, 72), 760, 0),
    ("metal", (120, 128, 120), 400, 600),
    ("glass", (70, 92, 104), 120, 0),
)
ARCHES = ("round", "pointed")
TOWER_ROOFS = ("pyramid", "dome", "terrace")


def arch_points(
    cx: float, spring: float, half: float, rise: float, steps: int, kind: str
) -> list[tuple[float, float]]:
    """The intrados from the left springing to the right one. A round arch is a half ellipse of the
    given rise; a pointed arch is two circular arcs meeting at the apex, and falls back to round
    when the rise does not exceed the half span."""
    if kind == "pointed" and rise > half * 1.02:
        radius = (rise * rise + half * half) / (2 * half)
        top = math.acos((radius - half) / radius)
        count = steps // 2
        left = []
        for i in range(count + 1):
            angle = math.pi - (math.pi - top) * i / count
            left.append(
                (cx + half - radius + radius * math.cos(angle), spring + radius * math.sin(angle))
            )
        return left + [(2 * cx - x, y) for x, y in reversed(left[:-1])]
    return [
        (
            cx + half * math.cos(math.pi * (1 - i / steps)),
            spring + rise * math.sin(math.pi * (1 - i / steps)),
        )
        for i in range(steps + 1)
    ]


def arched_wall(
    piece: Piece,
    x: tuple[float, float],
    z: tuple[float, float],
    y: tuple[float, float],
    openings: Sequence[Opening],
    steps: int,
    kind: str,
    key: str = "stone",
    inner: str = "shade",
) -> None:
    """A wall slab pierced by arched openings (centre x, half width, springing height, rise), drawn
    as convex parts: solid piers, spandrel strips above each arch, soffits and jambs."""
    (x0, x1), (z0, z1), (y0, y1) = x, z, y
    edges = [x0]
    for cx, half, _, _ in openings:
        edges += [cx - half, cx + half]
    edges.append(x1)
    for i in range(0, len(edges), 2):
        a, b = edges[i], edges[i + 1]
        if b - a > 1e-6:
            faces = "xXyYzZ" if a == x0 or b == x1 else "yYzZ"
            piece.box((a, b), (y0, y1), (z0, z1), key, faces)
    for cx, half, spring, rise in openings:
        points = arch_points(cx, spring, half, rise, steps, kind)
        for (xa, ya), (xb, yb) in pairwise(points):
            for depth, sign in ((z1, 1.0), (z0, -1.0)):
                piece.face(
                    [(xa, ya, depth), (xb, yb, depth), (xb, y1, depth), (xa, y1, depth)],
                    key,
                    (0.0, 0.0, sign),
                )
            middle_x, middle_y = (xa + xb) / 2, (ya + yb) / 2
            piece.face(
                [(xa, ya, z0), (xb, yb, z0), (xb, yb, z1), (xa, ya, z1)],
                inner,
                (cx - middle_x, spring - middle_y, 0.0),
            )
        for jamb, sign in ((cx - half, 1.0), (cx + half, -1.0)):
            piece.face(
                [(jamb, y0, z0), (jamb, y0, z1), (jamb, spring, z1), (jamb, spring, z0)],
                inner,
                (sign, 0.0, 0.0),
            )
        piece.face(
            [(cx - half, y1, z0), (cx + half, y1, z0), (cx + half, y1, z1), (cx - half, y1, z1)],
            key,
            (0.0, 1.0, 0.0),
        )


def cornice(
    piece: Piece,
    x: tuple[float, float],
    z: tuple[float, float],
    y: float,
    height: float,
    out: float,
) -> None:
    """A projecting band of two steps along a block's four sides."""
    (x0, x1), (z0, z1) = x, z
    piece.box((x0 - out, x1 + out), (y, y + height * 0.5), (z0 - out, z1 + out), "trim")
    piece.box(
        (x0 - out * 1.8, x1 + out * 1.8),
        (y + height * 0.5, y + height),
        (z0 - out * 1.8, z1 + out * 1.8),
        "trim",
    )


def balustrade_run(
    piece: Piece, x: tuple[float, float], z: float, y: float, height: float, depth: float = 0.32
) -> None:
    """A balustrade along X: plinth, turned balusters (a shaft, a swell and a neck) and a rail."""
    x0, x1 = x
    piece.box((x0, x1), (y, y + 0.16), (z - depth / 2, z + depth / 2), "trim")
    piece.box((x0, x1), (y + height - 0.14, y + height), (z - depth / 2, z + depth / 2), "trim")
    count = max(1, int((x1 - x0) / 0.32))
    inner = height - 0.3
    for i in range(count):
        cx = x0 + (i + 0.5) * (x1 - x0) / count
        piece.prism(1, (cx, y + 0.16 + inner * 0.25, z), 0.055, inner * 0.5, 8, "trim")
        piece.prism(
            1,
            (cx, y + 0.16 + inner * 0.62, z),
            min(0.085, depth / 2 - 0.02),
            inner * 0.26,
            8,
            "trim",
        )
        piece.prism(1, (cx, y + 0.16 + inner * 0.9, z), 0.05, inner * 0.2, 8, "trim")


def column(piece: Piece, x: float, z: float, y: tuple[float, float], radius: float) -> None:
    """A column: square base, shaft, necking, capital and abacus."""
    y0, y1 = y
    h = y1 - y0
    wide = radius * 1.35
    piece.box((x - wide, x + wide), (y0, y0 + h * 0.05), (z - wide, z + wide), "trim")
    piece.prism(1, (x, y0 + h * 0.47, z), radius, h * 0.84, 16, "stone")
    piece.prism(1, (x, y0 + h * 0.91, z), radius * 0.92, h * 0.04, 16, "stone")
    piece.prism(1, (x, y0 + h * 0.95, z), radius * 1.18, h * 0.04, 16, "trim")
    piece.box(
        (x - radius * 1.4, x + radius * 1.4),
        (y1 - h * 0.03, y1),
        (z - radius * 1.4, z + radius * 1.4),
        "trim",
    )


def _mirror_z(target: Piece, source: Piece, sign: float) -> None:
    for k, key in enumerate(source.keys):
        target.corners += [(c[0], c[1], sign * c[2]) for c in source.corners[k * 3 : k * 3 + 3]]
        target.keys.append(key)


def _turn(target: Piece, source: Piece, sign: float) -> None:
    """Add ``source`` turned a quarter about +Y (sign 1) or against it (sign -1)."""
    for k, key in enumerate(source.keys):
        target.corners += [
            (sign * c[2], c[1], -sign * c[0]) for c in source.corners[k * 3 : k * 3 + 3]
        ]
        target.keys.append(key)


def arcade_block(row: Mapping[str, Any]) -> Piece:
    """A block whose ground storey is an open loggia of arches on piers before a dark recessed
    wall, with arched windows on the storeys above, cornices and an optional roof balustrade."""
    w, d, h = [n / 1000 - 0.9 if i < 2 else n / 1000 for i, n in enumerate(row["size_mm"])]
    bays, storeys, kind, steps = row["bays"], row["storeys"], row["arch"], row["segments"]
    railed = row["roof_balustrade"]
    piece = Piece()
    ground = h * row["ground_share_permille"] / 1000
    pier = w / bays * row["pier_share_permille"] / 1000
    loggia = min(d * 0.35, row["loggia_depth_mm"] / 1000)
    front, back, bay = d / 2, -d / 2, w / bays
    arches = [
        (
            -w / 2 + bay * (i + 0.5),
            bay / 2 - pier / 2,
            ground * 0.62,
            min(bay / 2 - pier / 2, ground * 0.3),
        )
        for i in range(bays)
    ]
    arched_wall(piece, (-w / 2, w / 2), (front - 0.8, front), (0, ground), arches, steps, kind)
    piece.box((-w / 2, w / 2), (0, ground), (back, front - loggia), "stone", "xXyYz")
    piece.face(
        [
            (-w / 2 + 0.8, 0.02, front - loggia + 0.01),
            (w / 2 - 0.8, 0.02, front - loggia + 0.01),
            (w / 2 - 0.8, ground - 0.2, front - loggia + 0.01),
            (-w / 2 + 0.8, ground - 0.2, front - loggia + 0.01),
        ],
        "shade",
        (0, 0, 1),
    )
    piece.box((-w / 2, w / 2), (ground - 0.6, ground), (front - loggia, front - 0.8), "stone", "y")
    piece.box((-w / 2, w / 2), (0, 0.05), (front - loggia, front), "trim", "Y")
    piece.box((-w / 2, -w / 2 + 0.6), (0, ground), (front - loggia, front), "stone")
    piece.box((w / 2 - 0.6, w / 2), (0, ground), (front - loggia, front), "stone")
    cornice(piece, (-w / 2, w / 2), (back, front), ground, 0.7, 0.18)
    upper = (h - ground - 0.7) * (0.86 if railed else 0.95)
    if storeys:
        storey = upper / storeys
        piece.box(
            (-w / 2, w / 2),
            (ground + 0.7, ground + 0.7 + upper),
            (back, front - 0.25),
            "stone",
            "xXyz",
        )
        for s in range(storeys):
            y0 = ground + 0.7 + s * storey
            half = min(bay * 0.18, 1.1)
            windows = [
                (-w / 2 + bay * (i + 0.5), half, y0 + storey * 0.6, half) for i in range(bays)
            ]
            arched_wall(
                piece, (-w / 2, w / 2), (front - 0.25, front), (y0, y0 + storey), windows, 8, kind
            )
            for cx, half, spring, _ in windows:
                sill = y0 + storey * 0.25
                piece.face(
                    [
                        (cx - half, sill, front - 0.249),
                        (cx + half, sill, front - 0.249),
                        (cx + half, spring, front - 0.249),
                        (cx - half, spring, front - 0.249),
                    ],
                    "glass",
                    (0, 0, 1),
                )
                piece.box(
                    (cx - half - 0.15, cx + half + 0.15),
                    (sill - 0.18, sill),
                    (front - 0.05, front + 0.25),
                    "trim",
                )
            if s < storeys - 1:
                piece.box(
                    (-w / 2 - 0.05, w / 2 + 0.05),
                    (y0 + storey - 0.18, y0 + storey),
                    (back - 0.05, front + 0.12),
                    "trim",
                )
    top = ground + 0.7 + upper
    eaves = min(top, h - 1.2) if railed else h - 0.7
    cornice(piece, (-w / 2, w / 2), (back, front), eaves, 0.6, 0.25)
    if railed:
        y = min(eaves + 0.6, h - 1.06)
        for z in (front - 0.2, back + 0.2):
            balustrade_run(piece, (-w / 2 + 0.2, w / 2 - 0.2), z, y, min(1.05, h - y))
    return piece


def colonnade(row: Mapping[str, Any]) -> Piece:
    """A covered walk: columns (two rows when deep enough) under an entablature."""
    w, d, h = [n / 1000 for n in row["size_mm"]]
    count = row["columns"]
    piece = Piece()
    radius = min(w / count * 0.16, d * 0.12, 0.6)
    entablature = h * 0.16
    rows = (d / 2 - radius * 1.5, -d / 2 + radius * 1.5) if d > 4 else (d / 2 - radius * 1.5,)
    for z in rows:
        for i in range(count):
            x = -w / 2 + radius * 1.5 + i * (w - radius * 3) / max(1, count - 1)
            column(piece, x, z, (0, h - entablature), radius)
    piece.box((-w / 2, w / 2), (h - entablature, h - entablature * 0.45), (-d / 2, d / 2), "stone")
    cornice(
        piece,
        (-w / 2 + 0.3, w / 2 - 0.3),
        (-d / 2 + 0.3, d / 2 - 0.3),
        h - entablature * 0.45,
        entablature * 0.45 - 0.05,
        0.12,
    )
    return piece


def tower(row: Mapping[str, Any]) -> Piece:
    """A tower in stages marked by bands, small windows, an open belfry of arches on every side
    and a roof: a pyramid, a dome or a balustraded terrace."""
    w, d, h = [n / 1000 for n in row["size_mm"]]
    roof, stages, kind = row["roof"], row["stages"], row["arch"]
    piece = Piece()
    roof_h = {"pyramid": h * 0.22, "dome": h * 0.16, "terrace": 1.1}[roof]
    belfry = h * 0.16
    shaft = h - roof_h - belfry
    a = min(w, d) / 2 * 0.86
    for s in range(stages):
        y0, y1, inset = s * shaft / stages, (s + 1) * shaft / stages, s * 0.12
        piece.box((-a + inset, a - inset), (y0, y1), (-a + inset, a - inset), "stone")
        piece.box(
            (-a + inset - 0.15, a - inset + 0.15),
            (y1 - 0.35, y1),
            (-a + inset - 0.15, a - inset + 0.15),
            "trim",
        )
        half_w, half_h, middle, face = a * 0.18, (y1 - y0) * 0.3, (y0 + y1) / 2, a - inset + 0.01
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
    inner = a - (stages - 1) * 0.12
    y0, y1 = shaft, shaft + belfry
    thick, half = inner * 0.28, inner * 0.42
    arch = [(0.0, half, y0 + belfry * 0.55, min(half, belfry * 0.3))]
    for sign in (1.0, -1.0):
        wall = Piece()
        arched_wall(
            wall, (-inner, inner), (inner - thick, inner), (y0, y1), arch, row["segments"], kind
        )
        _mirror_z(piece, wall, sign)
        side = Piece()
        narrow = [
            (0.0, min(half, inner - thick - 0.3), y0 + belfry * 0.55, min(half, belfry * 0.3))
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
            balustrade_run(piece, (-inner + 0.15, inner - 0.15), z, y1, min(1.0, h - y1))
    return piece


def stair_flight(row: Mapping[str, Any]) -> Piece:
    """A straight flight rising from the front (+Z) to the back, with stepped cheek walls and a
    balustrade post on every other step and a rail at the top."""
    w, d, h = [n / 1000 for n in row["size_mm"]]
    cheek = row["cheek_mm"] / 1000
    rise = h - 1.0
    steps = max(1, round(rise / (row["riser_mm"] / 1000)))
    going = d / steps
    piece = Piece()
    for i in range(steps):
        top = (i + 1) * rise / steps
        z1 = d / 2 - i * going
        piece.box(
            (-w / 2 + cheek, w / 2 - cheek),
            (0, top),
            (z1 - going, z1),
            "stone",
            "yYzZ" if i else "yYZ",
        )
        piece.box(
            (-w / 2 + cheek, w / 2 - cheek),
            (top - 0.04, top),
            (max(-d / 2, z1 - going - 0.03), z1),
            "trim",
            "Y",
        )
    for x0 in (-w / 2, w / 2 - cheek):
        for i in range(steps):
            top = (i + 1) * rise / steps + 0.1
            z1 = d / 2 - i * going
            piece.box((x0, x0 + cheek), (0, top), (z1 - going, z1), "stone")
            if i % 2 == 0:
                piece.prism(1, (x0 + cheek / 2, top + 0.4, z1 - going / 2), 0.05, 0.8, 8, "trim")
        piece.box(
            (x0 + cheek * 0.2, x0 + cheek * 0.8),
            (rise + 0.8, rise + 0.9),
            (-d / 2, -d / 2 + going),
            "trim",
        )
    return piece


def hipped_roof(
    piece: Piece, x: tuple[float, float], z: tuple[float, float], y: float, rise: float, over: float
) -> None:
    """A hipped roof over x and z with eaves overhanging by ``over``, its soffit in trim."""
    x0, x1, z0, z1 = x[0] - over, x[1] + over, z[0] - over, z[1] + over
    ridge = max(0.0, (x1 - x0) - (z1 - z0)) / 2
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    a, b = (cx - ridge, y + rise, cz), (cx + ridge, y + rise, cz)
    piece.face([(x0, y, z1), (x1, y, z1), b, a], "roof", (0, 1, 1))
    piece.face([(x1, y, z0), (x0, y, z0), a, b], "roof", (0, 1, -1))
    piece.face([(x0, y, z0), (x0, y, z1), a], "roof", (-1, 1, 0))
    piece.face([(x1, y, z1), (x1, y, z0), b], "roof", (1, 1, 0))
    piece.face([(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)], "trim", (0, -1, 0))


def pavilion(row: Mapping[str, Any]) -> Piece:
    """A pavilion or cafe: a glazed room inside a colonnade under a hipped roof."""
    w, d, h = [n / 1000 for n in row["size_mm"]]
    over = 0.6
    w, d = w - 2 * over, d - 2 * over
    eaves = h * 0.62
    piece = Piece()
    piece.box((-w / 2, w / 2), (0, 0.45), (-d / 2, d / 2), "trim")
    piece.box(
        (-w / 2 + 2.2, w / 2 - 2.2), (0.45, eaves - 0.6), (-d / 2 + 2.2, d / 2 - 2.2), "glass"
    )
    count = row["columns"]
    along = [-w / 2 + 0.5 + i * (w - 1) / (count - 1) for i in range(count)]
    across_count = max(2, round(count * d / w))
    across = [-d / 2 + 0.5 + i * (d - 1) / (across_count - 1) for i in range(1, across_count - 1)]
    for x in along:
        for z in (-d / 2 + 0.5, d / 2 - 0.5):
            column(piece, x, z, (0.45, eaves - 0.6), 0.22)
    for z in across:
        for x in (-w / 2 + 0.5, w / 2 - 0.5):
            column(piece, x, z, (0.45, eaves - 0.6), 0.22)
    piece.box((-w / 2, w / 2), (eaves - 0.6, eaves), (-d / 2, d / 2), "stone")
    hipped_roof(piece, (-w / 2, w / 2), (-d / 2, d / 2), eaves, h - eaves, over)
    return piece


def hall(row: Mapping[str, Any]) -> Piece:
    """A great hall: an arcaded aisle along each long side, a clerestory of arched windows, a
    barrel roof and gable ends with a round window."""
    w, d, h = [n / 1000 for n in row["size_mm"]]
    bays, kind = row["bays"], row["arch"]
    aisle_h, aisle_d, clere = h * 0.38, d * 0.22, h * 0.72
    nave = d - 2 * aisle_d
    bay = w / bays
    piece = Piece()
    for sign in (1.0, -1.0):
        side = Piece()
        arches = [
            (-w / 2 + bay * (i + 0.5), bay * 0.33, aisle_h * 0.55, min(bay * 0.33, aisle_h * 0.35))
            for i in range(bays)
        ]
        arched_wall(
            side, (-w / 2, w / 2), (d / 2 - 0.7, d / 2), (0, aisle_h), arches, row["segments"], kind
        )
        windows = [
            (
                -w / 2 + bay * (i + 0.5),
                bay * 0.2,
                aisle_h + (clere - aisle_h) * 0.55,
                min(bay * 0.2, (clere - aisle_h) * 0.3),
            )
            for i in range(bays)
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
    return piece


def balustrade(row: Mapping[str, Any]) -> Piece:
    """One run of balustrade, its length the piece's width: a boundary family tiles it along a
    run, so the ends are left open for the next tile."""
    w, d, h = [n / 1000 for n in row["size_mm"]]
    piece = Piece()
    balustrade_run(piece, (-w / 2, w / 2), 0.0, 0.0, h, depth=d)
    return piece


ARCHITECTURE_RECIPES: dict[str, Callable[[Mapping[str, Any]], Piece]] = {
    "arcade_block": arcade_block,
    "colonnade": colonnade,
    "tower": tower,
    "stair_flight": stair_flight,
    "pavilion": pavilion,
    "hall": hall,
    "balustrade": balustrade,
}

# The fewest millimetres each recipe needs for its parts to stay whole: width, depth, height.
MINIMUM_MM = {
    "arcade_block": (6000, 5000, 6000),
    "colonnade": (3000, 1500, 3000),
    "tower": (3000, 3000, 9000),
    "stair_flight": (2000, 1500, 1400),
    "pavilion": (6000, 6000, 3500),
    "hall": (12000, 9000, 9000),
    "balustrade": (600, 200, 600),
}


def _bounded(row: Mapping[str, Any], key: str, low: int, high: int) -> None:
    value = row.get(key)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{row['recipe']} {key} is an integer from {low} to {high}")


def _choice(row: Mapping[str, Any], key: str, choices: Sequence[str]) -> None:
    if row.get(key) not in choices:
        raise ValueError(f"{row['recipe']} {key} is one of {', '.join(choices)}")


def validate_architecture_row(row: Mapping[str, Any]) -> None:
    """Refuse an architecture row whose numbers would break a piece, before anything is written."""
    recipe = row["recipe"]
    if any(n < m for n, m in zip(row["size_mm"], MINIMUM_MM[recipe], strict=True)):
        raise ValueError(f"{recipe} needs at least {MINIMUM_MM[recipe]} millimetres")
    if recipe == "arcade_block":
        _bounded(row, "bays", 1, 24)
        _bounded(row, "storeys", 0, 8)
        _bounded(row, "ground_share_permille", 200, 700)
        _bounded(row, "pier_share_permille", 100, 500)
        _bounded(row, "loggia_depth_mm", 1000, 12000)
        _choice(row, "arch", ARCHES)
        if type(row.get("roof_balustrade")) is not bool:
            raise ValueError("arcade_block roof_balustrade is true or false")
    elif recipe == "colonnade":
        _bounded(row, "columns", 2, 48)
    elif recipe == "tower":
        _bounded(row, "stages", 1, 8)
        _choice(row, "roof", TOWER_ROOFS)
        _choice(row, "arch", ARCHES)
    elif recipe == "stair_flight":
        _bounded(row, "riser_mm", 100, 220)
        _bounded(row, "cheek_mm", 200, min(1000, row["size_mm"][0] // 4))
    elif recipe == "pavilion":
        _bounded(row, "columns", 2, 16)
    elif recipe == "hall":
        _bounded(row, "bays", 2, 24)
        _choice(row, "arch", ARCHES)
