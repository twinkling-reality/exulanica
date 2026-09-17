"""Before sheets: what a person compares, one row per pose.

Each row is the procedural render at a bench pose, the depth, segmentation and edge pictures a model
would be conditioned on, the exact geometry edges drawn over the render (proof the structure and
the picture line up), and an AFTER panel. Until a generation exists for that pose the AFTER panel
is the stated unavailable state, words on a hatched ground, never an image standing in for one.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import numpy as np
from PIL import Image, ImageDraw

from exulanica_appearance.capture import encode
from exulanica_appearance.structure import LayerStore, load_layers, read_structure

__all__ = ["before_sheets"]

_TILE: Final = (480, 300)
_LABEL: Final = 22


def _unavailable(size: tuple[int, int], words: str) -> Image.Image:
    panel = Image.new("RGB", size, (58, 58, 64))
    draw = ImageDraw.Draw(panel)
    for x in range(-size[1], size[0], 18):
        draw.line([(x, size[1]), (x + size[1], 0)], fill=(74, 74, 82), width=2)
    draw.rectangle([10, size[1] // 2 - 26, size[0] - 10, size[1] // 2 + 26], fill=(30, 30, 34))
    draw.text((20, size[1] // 2 - 18), words, fill=(236, 236, 236))
    draw.text(
        (20, size[1] // 2 + 2), "no generated frame exists for this pose yet", fill=(190, 190, 190)
    )
    return panel


def _labelled(image: Image.Image, label: str) -> Image.Image:
    out = Image.new("RGB", (_TILE[0], _TILE[1] + _LABEL), (18, 18, 20))
    out.paste(image.resize(_TILE, Image.Resampling.LANCZOS), (0, _LABEL))
    ImageDraw.Draw(out).text((6, 5), label, fill=(230, 230, 230))
    return out


def before_sheets(structure_dir: Path, frames_dir: Path, out: Path) -> Iterator[Path]:
    index = json.loads((structure_dir / "index.json").read_bytes())
    store = LayerStore(structure_dir / "layers")
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, entry in index["poses"].items():
        render_path = frames_dir / f"{name}.png"
        if not render_path.exists():
            continue
        record = read_structure(
            (structure_dir / "structures" / f"{entry['structure_sha256']}.json").read_bytes()
        )
        layers = load_layers(record, store)
        render = Image.open(render_path).convert("RGB")
        overlay = np.array(render)
        overlay[layers["edges"] > 0] = (255, 0, 255)
        near_um, far_um = encode.depth_range([layers["depth"]])
        depth = encode.inverse_depth(layers["depth"], near_um, far_um)
        identity = encode.identity_colours(layers["identity"], len(record["legend"]))
        tiles = [
            _labelled(render, f"{name}: procedural look (before)"),
            _labelled(Image.fromarray(depth), "exact depth (inverse, this pose's range)"),
            _labelled(Image.fromarray(identity), "surface identity"),
            _labelled(Image.fromarray(overlay), "exact edges over the render"),
            _labelled(_unavailable(_TILE, "AFTER: UNAVAILABLE"), "after (generated look)"),
        ]
        row = Image.new("RGB", (_TILE[0] * len(tiles), _TILE[1] + _LABEL))
        for column, tile in enumerate(tiles):
            row.paste(tile, (column * _TILE[0], 0))
        path = out / f"before-{name}.png"
        row.save(path)
        rows.append(row)
        yield path
    if rows:
        sheet = Image.new("RGB", (rows[0].width, sum(row.height for row in rows)))
        top = 0
        for row in rows:
            sheet.paste(row, (0, top))
            top += row.height
        path = out / "before-all-poses.png"
        sheet.save(path)
        yield path
