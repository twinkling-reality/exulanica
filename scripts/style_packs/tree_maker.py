"""Trees as textured pieces, made from a species of the catalog, a height, a width and a seed.

    .venv/bin/python -I scripts/style_packs/tree_maker.py --sources DIR --out DIR SPECIES HEIGHT_MM SEED [WIDTH_MM]

A species is data (``assets/style-packs/makers/tree-species.v1.json``, profile
``exulanica.tree-species/v1``), read and refused by name here: how its trunk and branches grow, the
leaf card it carries, its bark, and how its second level of detail thins it. The growth follows
ez-tree (Daniel Greenheck, MIT): a branch grown in sections, each turned a little by the species'
gnarliness, twisted, and bent toward a force; children spread stratified along their parent and
around it; leaf cards on the last level. Every random draw happens while the skeleton grows, so the
one skeleton is meshed twice: the first level, and a second with fewer sections, sides and cards and
without the finest branches.

A tree is grown to the box it is made for, never stretched to it: given a width, the crown's spread
is searched until the tree's width over its height is at most the box's; the tree is then scaled
whole so its height is the one asked. Its second level is held inside the first level's box. Bark is
a scanned bark (``sources.barks``), leaves are cards composed by ``leaf_cards.py`` from scanned single
leaves (``sources.leaves``); every source file is read from ``--sources`` and held to the digest the
catalog states before it is used, so the same catalog, sources and row give the same bytes. A
tree's pictures are its species' alone: the leaf sheet is drawn from the species' card recipe, not
the tree's seed, and the bark from its scan, so every tree of one species carries the same pictures
and a pack counts them once (``docs/style-pack-contract.md``, section 5), while its branches and
cards follow its seed. A receipt records what made each tree, each level's pictures among it. The pieces are textured pieces as
``docs/style-pack-contract.md`` (section 4.1) states, written by ``textured_glb.py``.

Tooling only: numpy and Pillow, which the product's runtime does not need.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import numpy as np
from PIL import Image

ROOT: Final = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.style_packs.leaf_cards import (  # noqa: E402
    FORMS,
    Leaf,
    Rng,
    compose_sheet,
    load_leaves,
    palette_png,
    sheet_seed,
)
from scripts.style_packs.textured_glb import Material, Primitive, write_textured_glb  # noqa: E402

__all__ = [
    "CATALOG",
    "MAKER",
    "MadeTree",
    "Sources",
    "TreeCatalogRefused",
    "make_tree",
    "read_catalog",
]

#: Version 2 draws a species' leaf sheet from its card recipe (version 1 drew it from each tree's
#: seed), so a row made by either keeps its receipt's word for what made it.
MAKER: Final = "exulanica.tree-maker/2"
PROFILE: Final = "exulanica.tree-species/v1"
CATALOG: Final = Path("assets/style-packs/makers/tree-species.v1.json")


class TreeCatalogRefused(ValueError):
    """A catalog or a row refused, by the path of what broke it."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        super().__init__(f"{path}: {message}")


# --- the catalog -------------------------------------------------------------------------------


def _number(value: Any, path: str, low: float, high: float, *, whole: bool = False) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or (whole and not isinstance(value, int))
    ):
        raise TreeCatalogRefused(
            path, f"is a {'whole ' if whole else ''}number from {low} to {high}"
        )
    if not low <= value <= high or not math.isfinite(value):
        raise TreeCatalogRefused(
            path, f"is a {'whole ' if whole else ''}number from {low} to {high}"
        )
    return value


def _numbers(
    value: Any, path: str, count: int, low: float, high: float, *, whole: bool = False
) -> list[float]:
    if not isinstance(value, list) or len(value) < count:
        raise TreeCatalogRefused(path, f"lists at least {count} numbers")
    return [_number(item, f"{path}[{k}]", low, high, whole=whole) for k, item in enumerate(value)]


def _srgb8(value: Any, path: str) -> None:
    if not isinstance(value, list) or len(value) != 3:
        raise TreeCatalogRefused(path, "is three sRGB bytes")
    for k, item in enumerate(value):
        _number(item, f"{path}[{k}]", 0, 255, whole=True)


def _keys(
    value: Any, path: str, required: set[str], optional: set[str] = frozenset()
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TreeCatalogRefused(path, "is an object")
    missing, unknown = required - set(value), set(value) - required - optional
    if missing:
        raise TreeCatalogRefused(path, f"states no {min(missing)}")
    if unknown:
        raise TreeCatalogRefused(path, f"states an unknown {min(unknown)}")
    return value


def _file(value: Any, path: str) -> None:
    item = _keys(value, path, {"path", "sha256"})
    parts = Path(str(item["path"])).parts
    if not isinstance(item["path"], str) or Path(item["path"]).is_absolute() or ".." in parts:
        raise TreeCatalogRefused(f"{path}.path", "is a path inside the sources folder")
    if not isinstance(item["sha256"], str) or len(item["sha256"]) != 64:
        raise TreeCatalogRefused(f"{path}.sha256", "is a SHA-256 in hexadecimal")


def _species(value: Any, path: str, leaves: dict[str, Any], barks: dict[str, Any]) -> None:
    item = _keys(
        value,
        path,
        {"type", "bark", "branch", "leaves", "card", "lod1"},
        {"bark_tint", "bark_scale", "spread_scales", "sway_permille"},
    )
    if "sway_permille" in item:
        _number(item["sway_permille"], f"{path}.sway_permille", 0, 4000, whole=True)
    if item["type"] not in ("deciduous", "evergreen"):
        raise TreeCatalogRefused(f"{path}.type", "is deciduous or evergreen")
    if item["bark"] not in barks:
        raise TreeCatalogRefused(f"{path}.bark", "names a bark of the sources")
    _numbers(item.get("bark_tint", [1, 1, 1]), f"{path}.bark_tint", 3, 0, 1.5)
    _numbers(item.get("bark_scale", [1, 1]), f"{path}.bark_scale", 2, 0.1, 10)
    scales = item.get("spread_scales", ["length"])
    if not isinstance(scales, list) or not scales or set(scales) - {"length", "leaves"}:
        raise TreeCatalogRefused(f"{path}.spread_scales", "lists length, leaves or both")
    branch = _keys(
        item["branch"],
        f"{path}.branch",
        {
            "levels",
            "angle",
            "children",
            "gnarliness",
            "length",
            "radius",
            "sections",
            "segments",
            "start",
            "taper",
            "twist",
            "force",
        },
        {"length_profile"},
    )
    levels = int(_number(branch["levels"], f"{path}.branch.levels", 1, 3, whole=True))
    for key, low, high, whole in (
        ("angle", 0, 180, False),
        ("gnarliness", -1, 1, False),
        ("length", 0.01, 200, False),
        ("radius", 0.001, 10, False),
        ("sections", 1, 32, True),
        ("segments", 3, 16, True),
        ("start", 0, 1, False),
        ("taper", 0, 1, False),
        ("twist", -3.2, 3.2, False),
    ):
        _numbers(branch[key], f"{path}.branch.{key}", levels + 1, low, high, whole=whole)
    _numbers(branch["children"], f"{path}.branch.children", levels, 0, 40, whole=True)
    if "length_profile" in branch:
        profile = branch["length_profile"]
        if not isinstance(profile, list) or not 2 <= len(profile) <= 16:
            raise TreeCatalogRefused(f"{path}.branch.length_profile", "lists 2 to 16 numbers")
        _numbers(profile, f"{path}.branch.length_profile", 2, 0, 2)
    force = _keys(branch["force"], f"{path}.branch.force", {"direction", "strength"})
    direction = _numbers(force["direction"], f"{path}.branch.force.direction", 3, -1, 1)
    if len(direction) != 3 or not any(direction):
        raise TreeCatalogRefused(f"{path}.branch.force.direction", "is a direction")
    strength = force["strength"]
    if isinstance(strength, list):
        _numbers(strength, f"{path}.branch.force.strength", levels + 1, -0.5, 0.5)
    else:
        _number(strength, f"{path}.branch.force.strength", -0.5, 0.5)
    leaf = _keys(
        item["leaves"],
        f"{path}.leaves",
        {"count", "start", "size", "size_variance", "angle", "billboard", "alpha_cutoff"},
        {"rounded_normals"},
    )
    _number(leaf["count"], f"{path}.leaves.count", 0, 40, whole=True)
    _number(leaf["start"], f"{path}.leaves.start", 0, 1)
    _number(leaf["size"], f"{path}.leaves.size", 0.01, 50)
    _number(leaf["size_variance"], f"{path}.leaves.size_variance", 0, 1)
    _number(leaf["angle"], f"{path}.leaves.angle", 0, 180)
    _number(leaf["alpha_cutoff"], f"{path}.leaves.alpha_cutoff", 0.05, 0.95)
    if leaf["billboard"] not in ("single", "double"):
        raise TreeCatalogRefused(f"{path}.leaves.billboard", "is single or double")
    if not isinstance(leaf.get("rounded_normals", True), bool):
        raise TreeCatalogRefused(f"{path}.leaves.rounded_normals", "is true or false")
    card = _keys(
        item["card"],
        f"{path}.card",
        {"source", "form", "leaves", "leaf_length", "spread_deg"},
        {"leaf_width", "recolour_srgb8", "stem_srgb8", "shoots", "blossom"},
    )
    if card["source"] not in leaves:
        raise TreeCatalogRefused(f"{path}.card.source", "names a leaf set of the sources")
    if card["form"] not in FORMS:
        raise TreeCatalogRefused(f"{path}.card.form", f"is one of {', '.join(FORMS)}")
    _number(card["leaves"], f"{path}.card.leaves", 1, 120, whole=True)
    _number(card["leaf_length"], f"{path}.card.leaf_length", 0.01, 1)
    _number(card["spread_deg"], f"{path}.card.spread_deg", 0, 360)
    _number(card.get("leaf_width", 1), f"{path}.card.leaf_width", 0.2, 10)
    _number(card.get("shoots", 6), f"{path}.card.shoots", 1, 16, whole=True)
    for key in ("recolour_srgb8", "stem_srgb8"):
        if key in card:
            _srgb8(card[key], f"{path}.card.{key}")
    if "blossom" in card:
        blossom = _keys(card["blossom"], f"{path}.card.blossom", {"count", "radius", "srgb8"})
        _number(blossom["count"], f"{path}.card.blossom.count", 1, 40, whole=True)
        _number(blossom["radius"], f"{path}.card.blossom.radius", 0.01, 0.2)
        if not isinstance(blossom["srgb8"], list) or not 1 <= len(blossom["srgb8"]) <= 8:
            raise TreeCatalogRefused(f"{path}.card.blossom.srgb8", "lists 1 to 8 colours")
        for k, colour in enumerate(blossom["srgb8"]):
            _srgb8(colour, f"{path}.card.blossom.srgb8[{k}]")
    lod1 = _keys(
        item["lod1"],
        f"{path}.lod1",
        {"section_stride", "segment_factor", "leaf_stride", "leaf_scale", "drop_levels"},
    )
    _number(lod1["section_stride"], f"{path}.lod1.section_stride", 1, 8, whole=True)
    _number(lod1["segment_factor"], f"{path}.lod1.segment_factor", 0.1, 1)
    _number(lod1["leaf_stride"], f"{path}.lod1.leaf_stride", 1, 8, whole=True)
    _number(lod1["leaf_scale"], f"{path}.lod1.leaf_scale", 1, 3)
    _number(lod1["drop_levels"], f"{path}.lod1.drop_levels", 0, 3, whole=True)


def read_catalog(document: Any) -> dict[str, Any]:
    """The species catalog, every field held to its range, or refused by the path that broke it."""
    catalog = _keys(document, "$", {"profile", "about", "sources", "textures", "species"})
    if catalog["profile"] != PROFILE:
        raise TreeCatalogRefused("$.profile", f"is {PROFILE}")
    sources = _keys(catalog["sources"], "$.sources", {"leaves", "barks"})
    for name, leaf in _keys(sources["leaves"], "$.sources.leaves", set(sources["leaves"])).items():
        item = _keys(
            leaf, f"$.sources.leaves.{name}", {"colour", "opacity", "points_deg", "archive"}
        )
        _file(item["colour"], f"$.sources.leaves.{name}.colour")
        _file(item["opacity"], f"$.sources.leaves.{name}.opacity")
        if item["points_deg"] not in (0, 90):
            raise TreeCatalogRefused(
                f"$.sources.leaves.{name}.points_deg", "is 0 (right) or 90 (up)"
            )
    for name, bark in _keys(sources["barks"], "$.sources.barks", set(sources["barks"])).items():
        item = _keys(bark, f"$.sources.barks.{name}", {"colour", "normal", "archive"})
        _file(item["colour"], f"$.sources.barks.{name}.colour")
        _file(item["normal"], f"$.sources.barks.{name}.normal")
    textures = _keys(catalog["textures"], "$.textures", {"lod0", "lod1", "jpeg_quality"})
    for level in ("lod0", "lod1"):
        sides = _keys(textures[level], f"$.textures.{level}", {"bark_px", "sheet_px"})
        _numbers(sides["bark_px"], f"$.textures.{level}.bark_px", 2, 16, 2048, whole=True)
        _number(sides["sheet_px"], f"$.textures.{level}.sheet_px", 32, 2048, whole=True)
    _number(textures["jpeg_quality"], "$.textures.jpeg_quality", 50, 95, whole=True)
    for name, species in _keys(catalog["species"], "$.species", set(catalog["species"])).items():
        _species(species, f"$.species.{name}", sources["leaves"], sources["barks"])
    return catalog


# --- sources ------------------------------------------------------------------------------------


class Sources:
    """The scans a catalog names, read from one folder, each held to its stated digest once."""

    def __init__(self, catalog: dict[str, Any], folder: Path) -> None:
        self.catalog = catalog
        self.folder = folder
        self.read: dict[str, str] = {}
        self._leaves: dict[str, list[Leaf]] = {}

    def path(self, stated: dict[str, str]) -> Path:
        path = self.folder / stated["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != stated["sha256"]:
            raise TreeCatalogRefused(stated["path"], "is not the bytes the catalog states")
        self.read[stated["path"]] = digest
        return path

    def leaves(self, name: str) -> list[Leaf]:
        if name not in self._leaves:
            stated = self.catalog["sources"]["leaves"][name]
            self._leaves[name] = load_leaves(
                self.path(stated["colour"]),
                self.path(stated["opacity"]),
                float(stated["points_deg"]),
            )
        return self._leaves[name]


# --- growth -------------------------------------------------------------------------------------

IDENTITY: Final = np.array([1.0, 0.0, 0.0, 0.0])
X: Final = (1.0, 0.0, 0.0)
Y: Final = (0.0, 1.0, 0.0)
Z: Final = (0.0, 0.0, 1.0)


def _q_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ]
    )


def _q_axis(axis: Any, angle: float) -> np.ndarray:
    axis = np.asarray(axis, dtype=float)
    s = math.sin(angle / 2)
    return np.array([math.cos(angle / 2), axis[0] * s, axis[1] * s, axis[2] * s])


def _q_rotate(q: np.ndarray, v: Any) -> np.ndarray:
    u, w = q[1:], q[0]
    v = np.asarray(v, dtype=float)
    return v + 2 * np.cross(u, np.cross(u, v) + w * v)


def _q_slerp(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    dot = float(np.dot(a, b))
    if dot < 0:
        b, dot = -b, -dot
    if dot > 0.9995:
        r = a + t * (b - a)
        return r / np.linalg.norm(r)
    theta = math.acos(dot)
    return (math.sin((1 - t) * theta) * a + math.sin(t * theta) * b) / math.sin(theta)


def _at(values: Any, level: int) -> Any:
    return values[min(level, len(values) - 1)]


@dataclass
class _Branch:
    origin: np.ndarray
    q: np.ndarray
    length: float
    radius: float
    level: int
    sections: int
    segments: int


@dataclass
class Skeleton:
    """Every branch's sections (origin, orientation, radius) and every leaf (origin, orientation, size)."""

    branches: list[tuple[int, int, list[tuple[np.ndarray, np.ndarray, float]]]] = field(
        default_factory=list
    )
    leaves: list[tuple[np.ndarray, np.ndarray, float]] = field(default_factory=list)


def grow(species: dict[str, Any], seed: int) -> Skeleton:
    """The species' skeleton for ``seed``: every random draw of the tree happens here."""
    b, leaves = species["branch"], species["leaves"]
    levels = b["levels"]
    evergreen = species["type"] == "evergreen"
    rng = Rng(seed)
    skeleton = Skeleton()
    queue = [
        _Branch(
            np.zeros(3),
            IDENTITY.copy(),
            b["length"][0],
            b["radius"][0],
            0,
            b["sections"][0],
            b["segments"][0],
        )
    ]
    force = np.asarray(b["force"]["direction"], dtype=float)
    force = force / np.linalg.norm(force)

    def shuffled(count: int) -> list[int]:
        order = list(range(count))
        for k in range(count - 1, 0, -1):
            r = int(rng.random() * (k + 1))
            order[k], order[r] = order[r], order[k]
        return order

    def record_leaf(origin: np.ndarray, q: np.ndarray) -> None:
        size = leaves["size"] * (1 + rng.random(leaves["size_variance"], -leaves["size_variance"]))
        skeleton.leaves.append((origin.copy(), q.copy(), size))

    def spread(count: int, start_min: float, sections: list, place: Any) -> None:
        offset = rng.random()
        step = (1.0 - start_min) / count
        slots = shuffled(count)
        for i in range(count):
            s = start_min + (i + rng.random()) * step
            index = min(len(sections) - 1, int(s * (len(sections) - 1)))
            a, c = sections[index], sections[min(index + 1, len(sections) - 1)]
            alpha = (s - index / (len(sections) - 1)) * (len(sections) - 1)
            origin = a[0] + (c[0] - a[0]) * alpha
            radius = (1 - alpha) * a[2] + alpha * c[2]
            parent = _q_slerp(a[1], c[1], alpha)
            angle = 2 * math.pi * (offset + (slots[i] + rng.random(0.5, -0.5)) / count)
            place(s, origin, radius, parent, angle)

    while queue:
        branch = queue.pop(0)
        q, origin = branch.q.copy(), branch.origin.copy()
        step = branch.length / branch.sections
        sections: list[tuple[np.ndarray, np.ndarray, float]] = []
        for i in range(branch.sections + 1):
            radius = branch.radius
            if i == branch.sections and branch.level == levels:
                radius = 0.001
            elif evergreen:
                radius *= 1 - i / branch.sections
            else:
                radius *= 1 - _at(b["taper"], branch.level) * (i / branch.sections)
            radius = max(radius, 0.001)
            sections.append((origin.copy(), q.copy(), radius))
            origin = origin + _q_rotate(q, (0, step, 0))
            g = max(1.0, 1.0 / math.sqrt(radius)) * _at(b["gnarliness"], branch.level)
            q = _q_mul(q, _q_axis(X, rng.random(g, -g)))
            q = _q_mul(q, _q_axis(Z, rng.random(g, -g)))
            q = _q_mul(q, _q_axis(Y, _at(b["twist"], branch.level)))
            up = _q_rotate(q, Y)
            axis = np.cross(up, force)
            sin_full = float(np.linalg.norm(axis))
            if sin_full > 1e-6:
                full = math.atan2(sin_full, float(np.dot(up, force)))
                strength = b["force"]["strength"]
                strength = _at(strength, branch.level) if isinstance(strength, list) else strength
                turn = max(-full, min(full, strength / radius))
                q = _q_mul(_q_axis(axis / sin_full, turn), q)
            q = q / np.linalg.norm(q)
        skeleton.branches.append((branch.level, branch.segments, sections))
        last = sections[-1]
        if not evergreen:
            if branch.level < levels:
                queue.append(
                    _Branch(
                        last[0],
                        last[1],
                        _at(b["length"], branch.level + 1),
                        last[2],
                        branch.level + 1,
                        branch.sections,
                        branch.segments,
                    )
                )
            else:
                record_leaf(last[0], last[1])
        if branch.level == levels:
            if leaves["count"] > 0:

                def leaf(
                    _s: float, o: np.ndarray, _r: float, parent: np.ndarray, angle: float
                ) -> None:
                    record_leaf(
                        o,
                        _q_mul(
                            parent,
                            _q_mul(_q_axis(Y, angle), _q_axis(X, math.radians(leaves["angle"]))),
                        ),
                    )

                spread(leaves["count"], leaves["start"], sections, leaf)
        elif branch.level < levels:
            level = branch.level + 1

            def child(
                s: float,
                o: np.ndarray,
                r: float,
                parent: np.ndarray,
                angle: float,
                level: int = level,
            ) -> None:
                cq = _q_mul(
                    parent,
                    _q_mul(_q_axis(Y, angle), _q_axis(X, math.radians(_at(b["angle"], level)))),
                )
                length = _at(b["length"], level) * ((1.0 - s) if evergreen else 1.0)
                if "length_profile" in b and level == 1:
                    # The crown's outline along the trunk: a child's length scaled by the profile at
                    # its height, piecewise linear over evenly spaced points.
                    p = b["length_profile"]
                    x = s * (len(p) - 1)
                    k = min(len(p) - 2, int(x))
                    length = _at(b["length"], level) * (p[k] + (p[k + 1] - p[k]) * (x - k))
                queue.append(
                    _Branch(
                        o,
                        cq,
                        length,
                        _at(b["radius"], level) * r,
                        level,
                        _at(b["sections"], level),
                        _at(b["segments"], level),
                    )
                )

            spread(_at(b["children"], branch.level), _at(b["start"], level), sections, child)
    return skeleton


# --- meshing -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Detail:
    """How one level of detail meshes the skeleton."""

    section_stride: int = 1
    segment_factor: float = 1.0
    leaf_stride: int = 1
    leaf_scale: float = 1.0
    deepest_level: int = 99


_Arrays = tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]


def _arrays(positions: list, normals: list, uvs: list, indices: list) -> _Arrays:
    return (
        np.asarray(positions, np.float32).reshape(-1, 3),
        np.asarray(normals, np.float32).reshape(-1, 3),
        np.asarray(uvs, np.float32).reshape(-1, 2),
        np.asarray(indices, np.uint32),
    )


def mesh(skeleton: Skeleton, species: dict[str, Any], detail: Detail) -> tuple[_Arrays, _Arrays]:
    """The bark's and the leaves' arrays at ``detail``, in the skeleton's own units."""
    bark: tuple[list, list, list, list] = ([], [], [], [])
    scale_u, scale_v = species.get("bark_scale", [1.0, 1.0])
    for level, segments, sections in skeleton.branches:
        if level > detail.deepest_level:
            continue
        sides = max(3, round(segments * detail.segment_factor))
        chosen = sections[:: detail.section_stride]
        if chosen[-1] is not sections[-1]:
            chosen.append(sections[-1])
        base, travelled, previous = len(bark[0]), 0.0, None
        circumference = max(2 * math.pi * sections[0][2], 1e-4)
        for origin, q, radius in chosen:
            if previous is not None:
                travelled += float(np.linalg.norm(origin - previous))
            previous = origin
            for j in range(sides + 1):
                a = 2 * math.pi * j / sides
                normal = _q_rotate(q, (math.cos(a), 0.0, math.sin(a)))
                bark[0].append(origin + normal * radius)
                bark[1].append(normal)
                bark[2].append((j / sides * scale_u, travelled / circumference * scale_v))
        ring = sides + 1
        for i in range(len(chosen) - 1):
            for j in range(sides):
                a = base + i * ring + j
                c = a + ring
                bark[3].extend([a, a + 1, c, a + 1, c + 1, c])
    leaves: tuple[list, list, list, list] = ([], [], [], [])
    double = species["leaves"]["billboard"] == "double"
    rounded = species["leaves"].get("rounded_normals", True)
    for n, (origin, q, size) in enumerate(skeleton.leaves[:: detail.leaf_stride]):
        size *= detail.leaf_scale
        card = (n * 2654435761 >> 7) % 4
        u0, v0 = (card % 2) * 0.5, (card // 2) * 0.5
        for turn in [0.0, math.pi / 2] if double else [0.0]:
            qq = _q_mul(q, _q_axis(Y, turn))
            corners = [
                (-size / 2, size, 0.0),
                (-size / 2, 0.0, 0.0),
                (size / 2, 0.0, 0.0),
                (size / 2, size, 0.0),
            ]
            facing = _q_rotate(qq, Z)
            base = len(leaves[0])
            for corner in corners:
                at = origin + _q_rotate(qq, corner)
                normal = facing + (at - origin) / max(size, 1e-6) if rounded else facing
                leaves[0].append(at)
                leaves[1].append(normal / np.linalg.norm(normal))
            leaves[2].extend([(u0, v0), (u0, v0 + 0.5), (u0 + 0.5, v0 + 0.5), (u0 + 0.5, v0)])
            leaves[3].extend([base, base + 1, base + 2, base, base + 2, base + 3])
    return _arrays(*bark), _arrays(*leaves)


def _spread(species: dict[str, Any], spread: float) -> dict[str, Any]:
    """The species with its crown narrower or wider: what ``spread_scales`` names scaled."""
    species = json.loads(json.dumps(species))
    scales = species.get("spread_scales", ["length"])
    if "length" in scales:
        lengths = species["branch"]["length"]
        species["branch"]["length"] = [lengths[0]] + [v * spread for v in lengths[1:]]
    if "leaves" in scales:
        species["leaves"]["size"] *= spread
    return species


def _width_over_height(species: dict[str, Any], seed: int) -> float:
    bark, leaves = mesh(grow(species, seed), species, Detail())
    points = np.concatenate([bark[0], leaves[0]])
    return (
        2
        * float(max(np.abs(points[:, 0]).max(), np.abs(points[:, 2]).max()))
        / float(points[:, 1].max())
    )


def fit_spread(species: dict[str, Any], seed: int, ratio: float) -> float:
    """The spread at which the crown's width over its height is at most ``ratio``, the widest a
    twelve-step bisection finds between 0.1 and 1.6. Where even 0.1 is too wide (a crown of cards
    is never narrower than its cards), 0.1 is made, and the receipt's size says how wide it is."""
    low, high = 0.1, 1.6
    if _width_over_height(_spread(species, low), seed) > ratio:
        return low
    for _ in range(12):
        middle = (low + high) / 2
        if _width_over_height(_spread(species, middle), seed) <= ratio:
            low = middle
        else:
            high = middle
    return low


# --- the piece -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class MadeTree:
    """A tree's two levels as piece bytes, its size as placed, what made it, and the share of a
    look's wind its species takes (none when the species states no share: the whole of it)."""

    lod0: bytes
    lod1: bytes
    size_mm: tuple[int, int, int]
    receipt: dict[str, Any]
    sway_permille: int | None = None


def _jpeg(image: Image.Image, quality: int) -> bytes:
    out = io.BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=quality, optimize=True, progressive=False)
    return out.getvalue()


def _hold_inside(lod1: np.ndarray, quads: int, half_x: float, half_z: float, top: float) -> None:
    """Shrink each of the second level's leaf cards toward its root until it lies inside the first
    level's box (the root itself lies inside)."""

    def over(points: np.ndarray) -> float:
        return float(
            max(
                np.abs(points[:, 0]).max() / half_x,
                np.abs(points[:, 2]).max() / half_z,
                points[:, 1].max() / top,
            )
        )

    for start in range(0, len(lod1), quads):
        card = lod1[start : start + quads]
        if over(card) <= 1.0:
            continue
        root = (card[1] + card[2]) / 2
        low, high = 0.0, 1.0
        for _ in range(20):
            middle = (low + high) / 2
            if over(root + (card - root) * middle) <= 1.0:
                low = middle
            else:
                high = middle
        lod1[start : start + quads] = root + (card - root) * low


def make_tree(
    catalog: dict[str, Any],
    species_key: str,
    height_mm: int,
    seed: int,
    sources: Sources,
    width_mm: int | None = None,
) -> MadeTree:
    """One tree of ``species_key``, ``height_mm`` tall, grown to at most ``width_mm`` wide."""
    if species_key not in catalog["species"]:
        raise TreeCatalogRefused("species", f"names no species of the catalog: {species_key!r}")
    _number(height_mm, "height_mm", 200, 50_000, whole=True)
    _number(seed, "seed", 0, 2**31 - 1, whole=True)
    if width_mm is not None:
        _number(width_mm, "width_mm", 100, 50_000, whole=True)
    species = catalog["species"][species_key]
    spread = 1.0 if width_mm is None else fit_spread(species, seed, width_mm / height_mm)
    grown = _spread(species, spread)
    skeleton = grow(grown, seed)
    levels = grown["branch"]["levels"]
    thin = grown["lod1"]
    details = [
        Detail(),
        Detail(
            section_stride=thin["section_stride"],
            segment_factor=thin["segment_factor"],
            leaf_stride=thin["leaf_stride"],
            leaf_scale=thin["leaf_scale"],
            deepest_level=levels - thin["drop_levels"],
        ),
    ]
    meshes = [mesh(skeleton, grown, detail) for detail in details]
    first = np.concatenate([meshes[0][0][0], meshes[0][1][0]])
    scale = height_mm / 1000 / float(first[:, 1].max())
    _hold_inside(
        meshes[1][1][0],
        8 if grown["leaves"]["billboard"] == "double" else 4,
        float(np.abs(first[:, 0]).max()),
        float(np.abs(first[:, 2]).max()),
        float(first[:, 1].max()),
    )
    textures = catalog["textures"]
    bark_source = catalog["sources"]["barks"][grown["bark"]]
    bark_colour = Image.open(sources.path(bark_source["colour"]))
    bark_normal = Image.open(sources.path(bark_source["normal"]))
    # The species' sheet, not this tree's: every tree of one species carries the same pictures.
    sheet = compose_sheet(
        grown["card"], sources.leaves(grown["card"]["source"]), 512, sheet_seed(grown["card"])
    )
    tint = grown.get("bark_tint", [1.0, 1.0, 1.0])
    out: list[tuple[bytes, list[int], int, list[str]]] = []
    for level, (bark, leaves) in zip(("lod0", "lod1"), meshes, strict=True):
        sides = textures[level]
        bark_px = tuple(sides["bark_px"])
        materials = [
            Material(
                "bark",
                _jpeg(bark_colour.resize(bark_px, Image.LANCZOS), textures["jpeg_quality"]),
                "image/jpeg",
                normal_image=_jpeg(
                    bark_normal.resize(bark_px, Image.LANCZOS), textures["jpeg_quality"]
                ),
                roughness=0.92,
                base_colour=(tint[0], tint[1], tint[2], 1.0),
            ),
            Material(
                "leaves",
                palette_png(sheet.resize((sides["sheet_px"],) * 2, Image.LANCZOS)),
                "image/png",
                alpha_cutoff=grown["leaves"]["alpha_cutoff"],
                double_sided=True,
                roughness=0.75,
                repeat=False,
            ),
        ]
        primitives = []
        for material, (positions, normals, uvs, indices) in enumerate([bark, leaves]):
            if len(indices):
                placed = positions * scale
                placed[:, 1] = np.maximum(placed[:, 1], 0.0)
                primitives.append(Primitive(material, placed, normals, uvs, indices))
        glb = write_textured_glb(primitives, materials, MAKER)
        points = np.concatenate([p.positions for p in primitives])
        size = [
            math.ceil(2 * float(np.abs(points[:, 0]).max()) * 1000),
            math.ceil(2 * float(np.abs(points[:, 2]).max()) * 1000),
            math.ceil(float(points[:, 1].max()) * 1000),
        ]
        # The level's pictures in the order the piece embeds them: each material's colour, then its normal map.
        pictures = [
            hashlib.sha256(image).hexdigest()
            for m in materials
            for image in (m.colour_image, m.normal_image)
            if image is not None
        ]
        out.append((glb, size, sum(len(p.indices) // 3 for p in primitives), pictures))
    canonical = json.dumps(species, sort_keys=True, separators=(",", ":")).encode()
    receipt = {
        "maker": MAKER,
        "species": species_key,
        "species_sha256": hashlib.sha256(canonical).hexdigest(),
        "height_mm": height_mm,
        "width_mm": width_mm,
        "seed": seed,
        "spread": round(spread, 6),
        "sources": dict(sorted(sources.read.items())),
        # Each level's pictures (bark, its normal map, leaves), the species' alone: a pack counts them once.
        "lods": [
            {
                "sha256": hashlib.sha256(glb).hexdigest(),
                "bytes": len(glb),
                "size_mm": size,
                "triangles": triangles,
                "pictures_sha256": pictures,
            }
            for glb, size, triangles, pictures in out
        ],
    }
    size_mm = tuple(out[0][1])
    return MadeTree(
        out[0][0],
        out[1][0],
        (size_mm[0], size_mm[1], size_mm[2]),
        receipt,
        species.get("sway_permille"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Make one tree of a species of the catalog.")
    parser.add_argument(
        "--sources", type=Path, required=True, help="the folder of the unpacked scans"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=ROOT / CATALOG)
    parser.add_argument("species")
    parser.add_argument("height_mm", type=int)
    parser.add_argument("seed", type=int)
    parser.add_argument("width_mm", type=int, nargs="?")
    args = parser.parse_args(argv)
    catalog = read_catalog(json.loads(args.catalog.read_text()))
    made = make_tree(
        catalog,
        args.species,
        args.height_mm,
        args.seed,
        Sources(catalog, args.sources),
        args.width_mm,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"{args.species}-{args.height_mm}-{args.seed}"
    (args.out / f"{stem}.glb").write_bytes(made.lod0)
    (args.out / f"{stem}-far.glb").write_bytes(made.lod1)
    (args.out / f"{stem}.receipt.json").write_text(
        json.dumps(made.receipt, indent=1, sort_keys=True) + "\n"
    )
    print(stem, made.size_mm, [lod["triangles"] for lod in made.receipt["lods"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
