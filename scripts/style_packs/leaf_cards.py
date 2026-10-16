"""Leaf cards: twigs, tufts, sprays and fans composed from scanned single leaves.

A card is a square RGBA picture whose stem starts at its bottom centre and grows up, so a tree's leaf
quad, rooted on a branch, shows a twig rooted there. A sheet is a 2 by 2 grid of four cards of one
recipe drawn from four seeds, so one plant varies its cards without another texture. A species
draws its sheet from its recipe's own seed (``sheet_seed``), not a plant's, so every plant of one
species carries the same sheet and a pack counts it once.

A scan is a colour picture and an opacity picture of single leaves on nothing (a CC0 leaf set). The
leaves are found by cutting the opacity along empty rows and columns, as many times as it takes;
each leaf then knows which way it points in the scan (``points_deg``), so a recipe can turn it to any
direction and set its base on a stem. Recipes are data (the species catalog's ``card``); this file
holds only how each form is laid out.

Tooling only: numpy and Pillow, which the product's runtime does not need.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

__all__ = ["FORMS", "Leaf", "Rng", "compose_sheet", "load_leaves", "palette_png", "sheet_seed"]

#: How a card lays its leaves out.
FORMS = ("twig", "tuft", "spray", "fan")


class Rng:
    """A small deterministic generator: the multiply-with-carry pair ez-tree uses (MIT)."""

    def __init__(self, seed: int) -> None:
        self.w = (123456789 + seed) & 0xFFFFFFFF
        self.z = (987654321 - seed) & 0xFFFFFFFF

    def random(self, high: float = 1.0, low: float = 0.0) -> float:
        self.z = (36969 * (self.z & 65535) + (self.z >> 16)) & 0xFFFFFFFF
        self.w = (18000 * (self.w & 65535) + (self.w >> 16)) & 0xFFFFFFFF
        value = (((self.z << 16) + (self.w & 65535)) & 0xFFFFFFFF) / 4294967296
        return (high - low) * value + low


@dataclass(frozen=True)
class Leaf:
    """One scanned leaf: RGBA cropped to it, and the direction its tip points in the scan."""

    rgba: Image.Image
    points_deg: float


def _runs(occupied: np.ndarray) -> list[tuple[int, int]]:
    """The runs of True in a one-dimensional mask, as half-open spans."""
    edges = np.flatnonzero(np.diff(np.concatenate([[0], occupied.astype(np.int8), [0]])))
    return list(zip(edges[0::2].tolist(), edges[1::2].tolist(), strict=True))


def _cut(mask: np.ndarray, top: int, left: int, smallest: int) -> list[tuple[int, int, int, int]]:
    """Boxes of the shapes in ``mask``, by cutting along empty rows, then empty columns, again."""
    boxes = []
    for r0, r1 in _runs(mask.any(axis=1)):
        band = mask[r0:r1]
        for c0, c1 in _runs(band.any(axis=0)):
            part = band[:, c0:c1]
            rows = _runs(part.any(axis=1))
            if len(rows) > 1:
                boxes.extend(_cut(part, top + r0, left + c0, smallest))
            elif part.sum() >= smallest:
                boxes.append((top + r0, top + r1, left + c0, left + c1))
    return boxes


def load_leaves(colour: Path, opacity: Path, points_deg: float, smallest: int = 500) -> list[Leaf]:
    """The single leaves of a scan, smallest first by size, each cropped to its box."""
    rgb = np.asarray(Image.open(colour).convert("RGB"))
    alpha = np.asarray(Image.open(opacity).convert("L"))
    if rgb.shape[:2] != alpha.shape:
        raise ValueError(f"{colour.name} and {opacity.name} are not one size")
    leaves = []
    for r0, r1, c0, c1 in _cut(alpha > 128, 0, 0, smallest):
        rgba = np.dstack([rgb[r0:r1, c0:c1], alpha[r0:r1, c0:c1]])
        leaves.append(Leaf(Image.fromarray(rgba, "RGBA"), points_deg))
    if not leaves:
        raise ValueError(f"{opacity.name} holds no leaf")
    leaves.sort(key=lambda leaf: (leaf.rgba.size, leaf.rgba.tobytes()[:64]))
    return leaves


def _place(
    card: Image.Image,
    leaf: Leaf,
    base: tuple[float, float],
    direction: float,
    length: float,
    tint: tuple[float, float, float],
    width: float,
    recolour: tuple[int, int, int] | None,
) -> None:
    """Draw ``leaf`` with its base at ``base`` (card pixels, y down), its tip ``direction`` degrees
    counterclockwise from +x, ``length`` pixels long and ``width`` times its own breadth, tinted;
    ``recolour`` takes the scan's light and dark into that sRGB colour."""
    up = leaf.points_deg == 90.0
    w, h = leaf.rgba.size
    scale = max(1e-3, length / (h if up else w))
    sx, sy = (scale * width, scale) if up else (scale, scale * width)
    image = leaf.rgba.resize((max(1, round(w * sx)), max(1, round(h * sy))), Image.LANCZOS)
    arr = np.asarray(image).astype(np.float32)
    if recolour is not None:
        light = arr[..., :3].mean(axis=2, keepdims=True)
        solid = arr[..., 3] > 128
        mean = float(light[solid].mean()) if solid.any() else 128.0
        arr[..., :3] = np.asarray(recolour, dtype=np.float32) * (light / max(mean, 1.0))
    arr[..., :3] *= np.asarray(tint, dtype=np.float32)
    image = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")
    w, h = image.size
    offset = (0.0, h / 2) if up else (-w / 2, 0.0)
    turn = direction - leaf.points_deg
    rotated = image.rotate(turn, resample=Image.BICUBIC, expand=True)
    radians = math.radians(turn)
    ox = offset[0] * math.cos(radians) + offset[1] * math.sin(radians)
    oy = -offset[0] * math.sin(radians) + offset[1] * math.cos(radians)
    rw, rh = rotated.size
    card.alpha_composite(rotated, (round(base[0] - ox - rw / 2), round(base[1] - oy - rh / 2)))


def compose_card(recipe: dict[str, Any], leaves: list[Leaf], size: int, seed: int) -> Image.Image:
    """One card of ``recipe``, ``size`` pixels square."""
    rng = Rng(seed)
    card = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    stem_colour = (*recipe.get("stem_srgb8", [92, 78, 58]), 255)
    width = recipe.get("leaf_width", 1.0)
    recolour = tuple(recipe["recolour_srgb8"]) if "recolour_srgb8" in recipe else None
    spread = recipe["spread_deg"]
    reach = recipe["leaf_length"]
    count = recipe["leaves"]

    def leaf() -> Leaf:
        return leaves[int(rng.random(len(leaves)))]

    def shade(depth: float) -> tuple[float, float, float]:
        value = (0.78 + 0.3 * depth) * rng.random(1.08, 0.9)
        return (value, value, value)

    def put(at: tuple[float, float], angle: float, length: float, depth: float) -> None:
        _place(card, leaf(), at, angle, length, shade(depth), width, recolour)

    bottom = (size / 2, size - 2.0)
    form = recipe["form"]
    if form == "twig":
        # A curved stem from the bottom centre; leaves alternate along it, smaller toward the tip.
        lean = rng.random(14, -14)
        stem = [
            (
                bottom[0]
                + math.sin(math.radians(lean)) * t * size * 0.86
                + math.sin(t * 3.1) * size * 0.03,
                bottom[1] - t * size * 0.9,
            )
            for t in (i / 8 for i in range(9))
        ]
        draw.line(stem, fill=stem_colour, width=max(1, round(size * 0.012)), joint="curve")
        for k in range(count):
            t = 0.16 + 0.84 * (k + rng.random(0.8, 0.2)) / count
            i = min(7, int(t * 8))
            f = t * 8 - i
            at = (
                stem[i][0] + (stem[i + 1][0] - stem[i][0]) * f,
                stem[i][1] + (stem[i + 1][1] - stem[i][1]) * f,
            )
            side = -1 if k % 2 else 1
            angle = 90 - lean + side * rng.random(spread, spread * 0.5)
            put(at, angle, size * reach * (1.1 - 0.45 * t) * rng.random(1.15, 0.85), t)
        put(stem[-1], 90 - lean, size * reach * 0.75, 1.0)
    elif form == "tuft":
        # Needles radiating from a short stem's tip, in an upward fan.
        hub = (bottom[0], bottom[1] - size * 0.22)
        draw.line([bottom, hub], fill=stem_colour, width=max(1, round(size * 0.02)))
        for k in range(count):
            put(
                hub,
                90 + rng.random(spread, -spread),
                size * reach * rng.random(1.1, 0.7),
                k / count,
            )
    elif form == "spray":
        # A flat, dense spray: small leaves along a stem and its side shoots (scale-like foliage).
        shoots_count = recipe.get("shoots", 6)
        shoots = [(bottom, 90.0, size * 0.9)]
        for k in range(shoots_count):
            t = 0.2 + 0.7 * k / max(1, shoots_count - 1)
            side = -1 if k % 2 else 1
            shoots.append(
                (
                    (bottom[0], bottom[1] - t * size * 0.85),
                    90 + side * rng.random(60, 35),
                    size * (0.5 - 0.3 * t),
                )
            )
        for (sx, sy), angle, length in shoots:
            end = (
                sx + math.cos(math.radians(angle)) * length,
                sy - math.sin(math.radians(angle)) * length,
            )
            draw.line([(sx, sy), end], fill=stem_colour, width=max(1, round(size * 0.008)))
            for k in range(count):
                t = k / count
                at = (sx + (end[0] - sx) * t, sy + (end[1] - sy) * t)
                put(at, angle + rng.random(70, -70), size * reach * rng.random(1.2, 0.8), t)
    elif form == "fan":
        # A palm's fan: blades radiating from the petiole's tip over a wide arc.
        hub = (bottom[0], bottom[1] - size * 0.08)
        for k in range(count):
            u = k / max(1, count - 1)
            angle = 90 + (u - 0.5) * spread + rng.random(4, -4)
            length = size * reach * (1 - 0.25 * abs(u - 0.5) * 2) * rng.random(1.05, 0.9)
            put(hub, angle, length, 0.5 + 0.5 * math.sin(u * math.pi))
    else:
        raise ValueError(f"unknown card form {form!r}")
    blossom = recipe.get("blossom")
    if blossom is not None:
        # Five-petal flowers scattered over the leaves.
        colours = blossom["srgb8"]
        for _ in range(blossom["count"]):
            cx, cy = size * rng.random(0.85, 0.15), size * rng.random(0.8, 0.08)
            r = size * blossom["radius"] * rng.random(1.2, 0.8)
            colour = colours[int(rng.random(len(colours)))]
            for p in range(5):
                a = p * 2 * math.pi / 5 + rng.random(0.3)
                px, py = cx + math.cos(a) * r * 0.55, cy + math.sin(a) * r * 0.55
                value = rng.random(1.0, 0.82)
                draw.ellipse(
                    [px - r * 0.5, py - r * 0.5, px + r * 0.5, py + r * 0.5],
                    fill=(*(int(c * value) for c in colour), 255),
                )
            draw.ellipse(
                [cx - r * 0.18, cy - r * 0.18, cx + r * 0.18, cy + r * 0.18],
                fill=(236, 214, 120, 255),
            )
    return card


def _bleed(image: Image.Image, steps: int = 24) -> Image.Image:
    """Carry colour outward from every leaf into the transparent pixels around it, step by step, so
    a mipmap of the cut-out never fringes dark; what no step reaches takes the leaves' mean."""
    arr = np.asarray(image).astype(np.float32)
    rgb, solid = arr[..., :3].copy(), arr[..., 3] > 8
    if not solid.any():
        return image
    filled = solid.copy()
    for _ in range(steps):
        total = np.zeros_like(rgb)
        weight = np.zeros(solid.shape, dtype=np.float32)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            shifted_fill = np.roll(filled, (dy, dx), axis=(0, 1))
            total += np.roll(rgb, (dy, dx), axis=(0, 1)) * shifted_fill[..., None]
            weight += shifted_fill
        grow = ~filled & (weight > 0)
        rgb[grow] = total[grow] / weight[grow][:, None]
        filled |= grow
    rgb[~filled] = rgb[solid].mean(axis=0)
    arr[..., :3] = rgb
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")


def compose_sheet(recipe: dict[str, Any], leaves: list[Leaf], size: int, seed: int) -> Image.Image:
    """A 2 by 2 sheet of four cards of ``recipe``, ``size`` pixels square in all."""
    half = size // 2
    sheet = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for k in range(4):
        sheet.alpha_composite(
            compose_card(recipe, leaves, half, seed * 7 + k), ((k % 2) * half, (k // 2) * half)
        )
    return _bleed(sheet)


def sheet_seed(card: dict[str, Any]) -> int:
    """The seed a species' leaf sheet is drawn from: its card recipe's, read from the recipe's
    canonical JSON, so a recipe always draws one sheet."""
    canonical = json.dumps(card, sort_keys=True, separators=(",", ":")).encode()
    return int.from_bytes(hashlib.sha256(canonical).digest()[:4], "big") & 0x7FFFFFFF


def palette_png(image: Image.Image) -> bytes:
    """A palette PNG with alpha: a sheet of a few greens loses nothing visible in 256 colours."""
    import io

    out = io.BytesIO()
    image.quantize(colors=256, method=Image.Quantize.FASTOCTREE).save(out, "PNG", optimize=True)
    return out.getvalue()
