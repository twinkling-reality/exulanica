"""Climbing plants as textured pieces: ivy or a flowering creeper grown over a wall patch of a
given width and height, for a look's ``climb`` (``docs/style-pack-contract.md``, sections 7.1 and 8).

A patch stands on its base at the origin with its wall in the plane z = 0 behind it, its leaves
toward +Z and +Y up. Stems rise from roots spaced along its foot, wander and branch as they climb,
and stay inside the patch; leaf cards (``leaf_cards.py``, from the scans the tree species catalog
names) hug the wall along them, each rooted on its stem, leaning a little out of the wall, fewer
toward a stem's growing end. A patch's pictures are its species' alone: the leaf sheet is drawn from
the species' card recipe, not the patch's seed, and the stem from its bark, so every patch of one
species carries the same pictures and a pack counts them once (``docs/style-pack-contract.md``,
section 5) while the stems and cards vary by seed. The species is data (``assets/style-packs/makers/creeper-species.v1.json``,
profile ``exulanica.creeper-species/v1``), every figure held to its range when the catalog is read;
a species, its scans, a size and a seed always make the same bytes.

A patch is held to the plant family's triangle budget: past it, every other card is dropped and the
rest grown larger to cover the same wall, until it fits; the receipt says how many were kept. Its
second level keeps a share of the cards, larger, on stems drawn with fewer points, within the share
of the first level's triangles a second level may hold. Tooling only: numpy and Pillow.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

import numpy as np
from PIL import Image

from scripts.style_packs import tree_maker
from scripts.style_packs.leaf_cards import Rng, compose_sheet, palette_png
from scripts.style_packs.textured_glb import Material, Primitive, write_textured_glb

PROFILE: Final = "exulanica.creeper-species/v1"
CATALOG: Final = Path("assets/style-packs/makers/creeper-species.v1.json")
MAKER: Final = "exulanica.creeper-maker/1"
#: The tree species catalog whose scans (leaves and barks) a creeper catalog version names.
SOURCES: Final = {"tree-species.v1": tree_maker.CATALOG}


class CreeperCatalogRefused(ValueError):
    """A creeper catalog or a request refused, by the path of what broke."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        super().__init__(f"{path}: {message}")


def _number(value: Any, path: str, low: float, high: float, *, whole: bool = False) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or (whole and type(value) is not int)
    ):
        raise CreeperCatalogRefused(path, "is a whole number" if whole else "is a number")
    if not low <= value <= high:
        raise CreeperCatalogRefused(path, f"is from {low} to {high}")


def _pair(value: Any, path: str, low: float, high: float) -> None:
    if not isinstance(value, list) or len(value) != 2:
        raise CreeperCatalogRefused(path, "is a least and a most")
    for index, item in enumerate(value):
        _number(item, f"{path}[{index}]", low, high)
    if value[0] > value[1]:
        raise CreeperCatalogRefused(path, "has its least above its most")


def _keys(
    value: Any, path: str, keys: set[str], optional: frozenset[str] = frozenset()
) -> dict[str, Any]:
    if not isinstance(value, dict) or not keys <= set(value) <= keys | optional:
        raise CreeperCatalogRefused(
            path,
            f"states {sorted(keys)}" + (f" and may state {sorted(optional)}" if optional else ""),
        )
    return value


def read_catalog(document: Any, tree_catalog: dict[str, Any]) -> dict[str, Any]:
    """The creeper catalog, every figure held to its range and every scan it names one the tree
    species catalog it states holds, or refused by the path that broke it."""
    catalog = _keys(document, "$", {"profile", "about", "sources", "textures", "species"})
    if catalog["profile"] != PROFILE:
        raise CreeperCatalogRefused("$.profile", f"is {PROFILE}")
    if catalog["sources"] not in SOURCES:
        raise CreeperCatalogRefused(
            "$.sources", f"names a tree species catalog among {sorted(SOURCES)}"
        )
    leaves, barks = tree_catalog["sources"]["leaves"], tree_catalog["sources"]["barks"]
    textures = _keys(catalog["textures"], "$.textures", {"lod0", "lod1", "jpeg_quality"})
    for level in ("lod0", "lod1"):
        sides = _keys(textures[level], f"$.textures.{level}", {"stem_px", "sheet_px"})
        if not isinstance(sides["stem_px"], list) or len(sides["stem_px"]) != 2:
            raise CreeperCatalogRefused(f"$.textures.{level}.stem_px", "is a width and a height")
        for index, side in enumerate(sides["stem_px"]):
            _number(side, f"$.textures.{level}.stem_px[{index}]", 16, 2048, whole=True)
        _number(sides["sheet_px"], f"$.textures.{level}.sheet_px", 32, 2048, whole=True)
    _number(textures["jpeg_quality"], "$.textures.jpeg_quality", 50, 95, whole=True)
    if not isinstance(catalog["species"], dict) or not catalog["species"]:
        raise CreeperCatalogRefused("$.species", "names at least one species")
    for name, species in catalog["species"].items():
        where = f"$.species.{name}"
        _keys(species, where, {"stem", "growth", "card", "cards", "lod1", "sway_permille"})
        stem = _keys(species["stem"], f"{where}.stem", {"bark", "radius_m", "tint"})
        if stem["bark"] not in barks:
            raise CreeperCatalogRefused(
                f"{where}.stem.bark", f"names a bark of {catalog['sources']}"
            )
        _number(stem["radius_m"], f"{where}.stem.radius_m", 0.002, 0.2)
        if not isinstance(stem["tint"], list) or len(stem["tint"]) != 3:
            raise CreeperCatalogRefused(f"{where}.stem.tint", "is three factors")
        for index, factor in enumerate(stem["tint"]):
            _number(factor, f"{where}.stem.tint[{index}]", 0.0, 2.0)
        growth = _keys(
            species["growth"],
            f"{where}.growth",
            {"root_spacing_m", "step_m", "wander_deg", "pull", "branching", "depth", "reach"},
        )
        _number(growth["root_spacing_m"], f"{where}.growth.root_spacing_m", 0.1, 10.0)
        _number(growth["step_m"], f"{where}.growth.step_m", 0.02, 2.0)
        _number(growth["wander_deg"], f"{where}.growth.wander_deg", 0, 90)
        _number(growth["pull"], f"{where}.growth.pull", 0.0, 1.0)
        _number(growth["branching"], f"{where}.growth.branching", 0.0, 1.0)
        _number(growth["depth"], f"{where}.growth.depth", 0, 3, whole=True)
        _pair(growth["reach"], f"{where}.growth.reach", 0.05, 1.0)
        card = species["card"]
        if not isinstance(card, dict) or card.get("source") not in leaves:
            raise CreeperCatalogRefused(
                f"{where}.card.source", f"names a leaf of {catalog['sources']}"
            )
        cards = _keys(
            species["cards"],
            f"{where}.cards",
            {"size_m", "per_step", "density", "tilt_deg", "out_m"},
        )
        _number(cards["size_m"], f"{where}.cards.size_m", 0.05, 5.0)
        _number(cards["per_step"], f"{where}.cards.per_step", 1, 8, whole=True)
        _number(cards["density"], f"{where}.cards.density", 0.05, 1.0)
        _pair(cards["tilt_deg"], f"{where}.cards.tilt_deg", 0, 80)
        _pair(cards["out_m"], f"{where}.cards.out_m", 0.0, 1.0)
        lod1 = _keys(species["lod1"], f"{where}.lod1", {"card_share", "card_scale"})
        _number(lod1["card_share"], f"{where}.lod1.card_share", 0.05, 1.0)
        _number(lod1["card_scale"], f"{where}.lod1.card_scale", 1.0, 4.0)
        _number(species["sway_permille"], f"{where}.sway_permille", 0, 4000, whole=True)
    return catalog


@dataclass(frozen=True)
class MadeCreeper:
    """A patch's two levels as piece bytes, its size, its share of the wind and what made it."""

    lod0: bytes
    lod1: bytes
    size_mm: tuple[int, int, int]
    sway_permille: int
    receipt: dict[str, Any]


def grow_stems(species: dict[str, Any], width: float, height: float, seed: int) -> list[np.ndarray]:
    """Each stem's points, metres: rising from roots spaced along the foot, wandering, pulled back
    toward up, branching to the species' depth, kept inside the patch."""
    growth = species["growth"]
    rng = Rng(seed)
    roots = max(1, round(width / growth["root_spacing_m"]))
    step = growth["step_m"]
    wander = math.radians(growth["wander_deg"])
    least, most = growth["reach"]
    queue: list[tuple[np.ndarray, float, float, int]] = []
    for k in range(roots):
        x = -width / 2 + (k + rng.random(0.8, 0.2)) * width / roots
        queue.append((np.array([x, 0.0]), math.pi / 2, height * rng.random(most, least), 0))
    stems: list[np.ndarray] = []
    while queue:
        start, heading, length, depth = queue.pop(0)
        point = start.copy()
        line = [point.copy()]
        travelled = 0.0
        while travelled < length:
            heading += rng.random(wander, -wander)
            heading += (math.pi / 2 - heading) * growth["pull"]
            point = point + step * np.array([math.cos(heading), math.sin(heading)])
            point[0] = min(width / 2, max(-width / 2, point[0]))
            point[1] = min(height, max(0.0, point[1]))
            line.append(point.copy())
            travelled += step
            if depth < growth["depth"] and rng.random() < growth["branching"]:
                side = 1.0 if rng.random() < 0.5 else -1.0
                queue.append(
                    (
                        point.copy(),
                        heading + side * rng.random(1.0, 0.5),
                        (length - travelled) * rng.random(0.8, 0.4),
                        depth + 1,
                    )
                )
        stems.append(np.asarray(line))
    return stems


def _cards(
    species: dict[str, Any], stems: list[np.ndarray], seed: int
) -> list[tuple[np.ndarray, float, float, float, int]]:
    """Every card a patch carries: where it roots (x, y), its turn, its lean out, its distance out
    of the wall and which of the sheet's four it shows; fewer toward a stem's growing end."""
    cards = species["cards"]
    rng = Rng(seed + 1)
    out = []
    for line in stems:
        for i, point in enumerate(line):
            for _ in range(cards["per_step"]):
                along = i / max(1, len(line) - 1)
                if rng.random() > cards["density"] * (1.0 - 0.45 * along):
                    continue
                at = point + np.array([rng.random(0.15, -0.15), rng.random(0.15, -0.15)])
                out.append(
                    (
                        at,
                        rng.random(math.pi, -math.pi),
                        math.radians(rng.random(*reversed(cards["tilt_deg"]))),
                        rng.random(*reversed(cards["out_m"])),
                        int(rng.random(4.0)) % 4,
                    )
                )
    return out


def _mesh(
    species: dict[str, Any],
    stems: list[np.ndarray],
    cards: list[tuple[np.ndarray, float, float, float, int]],
    size: float,
    width: float,
    height: float,
) -> tuple[tuple[np.ndarray, ...], tuple[np.ndarray, ...]]:
    """The stems as flat ribbons against the wall and the cards as quads, each part's positions,
    normals, texture coordinates and triangles."""
    radius = species["stem"]["radius_m"]
    s_pos, s_nrm, s_uv, s_idx = [], [], [], []
    for line in stems:
        for a, b in pairwise(line):
            d = b - a
            side = np.array([-d[1], d[0]]) / (np.linalg.norm(d) + 1e-12) * radius
            base = len(s_pos)
            # A ribbon's edge stays inside the patch as its middle does.
            for p in (a - side, a + side, b + side, b - side):
                s_pos.append(
                    (min(width / 2, max(-width / 2, p[0])), min(height, max(0.0, p[1])), 0.01)
                )
            s_nrm += [(0.0, 0.0, 1.0)] * 4
            s_uv += [(0, 0), (1, 0), (1, 1), (0, 1)]
            s_idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    c_pos, c_nrm, c_uv, c_idx = [], [], [], []
    for at, turn, lean, out, quadrant in cards:
        right = np.array([math.cos(turn), math.sin(turn), 0.0])
        up = np.array([-math.sin(turn), math.cos(turn), 0.0])
        outward = np.array([0.0, 0.0, 1.0])
        leaning = up * math.cos(lean) + outward * math.sin(lean)
        root = np.array([at[0], at[1], out])
        corners = [
            root - right * size / 2 + leaning * size,
            root - right * size / 2,
            root + right * size / 2,
            root + right * size / 2 + leaning * size,
        ]
        base = len(c_pos)
        for corner in corners:
            c_pos.append(
                (
                    min(width / 2, max(-width / 2, corner[0])),
                    min(height, max(0.0, corner[1])),
                    max(0.0, corner[2]),
                )
            )
        normal = outward * 0.8 + leaning * 0.2
        c_nrm += [tuple(normal / np.linalg.norm(normal))] * 4
        u0, v0 = (quadrant % 2) * 0.5, (quadrant // 2) * 0.5
        c_uv += [(u0, v0), (u0, v0 + 0.5), (u0 + 0.5, v0 + 0.5), (u0 + 0.5, v0)]
        c_idx += [base, base + 1, base + 2, base, base + 2, base + 3]

    def arrays(p: list, n: list, u: list, i: list) -> tuple[np.ndarray, ...]:
        return (
            np.asarray(p, np.float32).reshape(-1, 3),
            np.asarray(n, np.float32).reshape(-1, 3),
            np.asarray(u, np.float32).reshape(-1, 2),
            np.asarray(i, np.uint32),
        )

    return arrays(s_pos, s_nrm, s_uv, s_idx), arrays(c_pos, c_nrm, c_uv, c_idx)


def sheet_seed(card: dict[str, Any]) -> int:
    """The seed a species' leaf sheet is drawn from: its card recipe's, read from the recipe's
    canonical JSON, so a recipe always draws one sheet."""
    canonical = json.dumps(card, sort_keys=True, separators=(",", ":")).encode()
    return int.from_bytes(hashlib.sha256(canonical).digest()[:4], "big") & 0x7FFFFFFF


def _jpeg(image: Image.Image, quality: int) -> bytes:
    import io

    out = io.BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=quality, optimize=True, progressive=False)
    return out.getvalue()


def make_creeper(
    catalog: dict[str, Any],
    species_key: str,
    width_mm: int,
    height_mm: int,
    seed: int,
    sources: tree_maker.Sources,
    most_triangles: int,
    lod1_share_permille: int,
) -> MadeCreeper:
    """One patch of ``species_key``, ``width_mm`` by ``height_mm``, held to ``most_triangles`` and
    its second level to ``lod1_share_permille`` of its first's triangles."""
    if species_key not in catalog["species"]:
        raise CreeperCatalogRefused("species", f"names no species of the catalog: {species_key!r}")
    _number(width_mm, "width_mm", 200, 50_000, whole=True)
    _number(height_mm, "height_mm", 200, 50_000, whole=True)
    _number(seed, "seed", 0, 2**31 - 1, whole=True)
    species = catalog["species"][species_key]
    width, height = width_mm / 1000, height_mm / 1000
    stems = grow_stems(species, width, height, seed)
    cards = _cards(species, stems, seed)
    stem_triangles = 2 * sum(len(line) - 1 for line in stems)
    if stem_triangles >= most_triangles:
        raise CreeperCatalogRefused(
            "species", f"{species_key}'s stems alone take {stem_triangles} triangles"
        )
    size = species["cards"]["size_m"]
    grown = len(cards)
    # Over the budget: drop every other card and grow the rest larger to cover the same wall.
    while stem_triangles + 2 * len(cards) > most_triangles:
        cards = cards[::2]
        size *= math.sqrt(2)
    # The second level: a share of the cards on stems of every other point, thinned further until it
    # holds no more than its share of the first level's triangles.
    first = stem_triangles + 2 * len(cards)
    card_stride, stem_stride = max(1, round(1 / species["lod1"]["card_share"])), 2
    while True:
        lod1_stems = [line[::stem_stride] if len(line) > 2 else line for line in stems]
        lod1_cards = cards[::card_stride]
        lod1_triangles = 2 * sum(max(0, len(line) - 1) for line in lod1_stems) + 2 * len(lod1_cards)
        if lod1_triangles * 1000 <= first * lod1_share_permille or (
            card_stride > len(cards) and stem_stride > 64
        ):
            break
        card_stride, stem_stride = card_stride + 1, stem_stride + 1
    textures = catalog["textures"]
    bark = sources.catalog["sources"]["barks"][species["stem"]["bark"]]
    stem_colour = Image.open(sources.path(bark["colour"]))
    sheet = compose_sheet(
        species["card"], sources.leaves(species["card"]["source"]), 512, sheet_seed(species["card"])
    )
    tint = species["stem"]["tint"]
    out: list[tuple[bytes, int, list[str]]] = []
    depth = 0.0
    for level, level_stems, level_cards, level_size in (
        ("lod0", stems, cards, size),
        ("lod1", lod1_stems, lod1_cards, size * species["lod1"]["card_scale"]),
    ):
        sides = textures[level]
        materials = [
            Material(
                "stem",
                _jpeg(
                    stem_colour.resize(tuple(sides["stem_px"]), Image.LANCZOS),
                    textures["jpeg_quality"],
                ),
                "image/jpeg",
                roughness=0.9,
                base_colour=(tint[0], tint[1], tint[2], 1.0),
            ),
            Material(
                "leaves",
                palette_png(sheet.resize((sides["sheet_px"],) * 2, Image.LANCZOS)),
                "image/png",
                alpha_cutoff=0.45,
                double_sided=True,
                roughness=0.7,
                repeat=False,
            ),
        ]
        meshes = _mesh(species, level_stems, level_cards, level_size, width, height)
        primitives = [Primitive(index, *part) for index, part in enumerate(meshes) if len(part[3])]
        if level == "lod0":
            depth = float(max(np.abs(p.positions[:, 2]).max() for p in primitives))
        out.append(
            (
                write_textured_glb(primitives, materials, MAKER),
                sum(len(p.indices) // 3 for p in primitives),
                [hashlib.sha256(m.colour_image).hexdigest() for m in materials],
            )
        )
    canonical = json.dumps(species, sort_keys=True, separators=(",", ":")).encode()
    # As a piece's box is centred on its depth, twice the farthest any leaf stands from the wall.
    size_mm = (width_mm, max(1, math.ceil(2 * depth * 1000)), height_mm)
    receipt = {
        "maker": MAKER,
        "species": species_key,
        "species_sha256": hashlib.sha256(canonical).hexdigest(),
        "width_mm": width_mm,
        "height_mm": height_mm,
        "seed": seed,
        "cards": {"grown": grown, "kept": len(cards), "size_m": round(size, 6)},
        "sources": dict(sorted(sources.read.items())),
        # Each level's pictures (stem, then leaves), the species' alone: a pack counts them once.
        "lods": [
            {
                "sha256": hashlib.sha256(glb).hexdigest(),
                "bytes": len(glb),
                "triangles": triangles,
                "pictures_sha256": pictures,
            }
            for glb, triangles, pictures in out
        ],
    }
    return MadeCreeper(out[0][0], out[1][0], size_mm, species["sway_permille"], receipt)
