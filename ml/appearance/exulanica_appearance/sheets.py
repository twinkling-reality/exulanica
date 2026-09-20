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

__all__ = ["before_sheets", "texture_pairs"]

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
            _labelled(
                Image.fromarray(depth),
                f"exact depth, {encode.ENCODINGS['depth']['name']}, this pose's range",
            ),
            _labelled(
                Image.fromarray(identity),
                f"surface identity, {encode.ENCODINGS['segmentation']['name']}",
            ),
            _labelled(
                Image.fromarray(overlay),
                f"exact edges over the render, {encode.ENCODINGS['edge']['name']}",
            ),
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


def texture_pairs(
    *,
    repository: Path,
    results: Path,
    out: Path,
    tile: int = 2,
) -> list[Path]:
    """One sheet a target: the published set's colour, then each candidate's, and a tiled composite.

    The left panel is what the procedural recipe paints, read from the pinned container. Each
    panel to its right is a generated base colour at the same size, labelled with its candidate,
    seed and measured seam ratio. Below each, the same map tiled ``tile`` by ``tile``, because
    repetition and seams are what a person sees on a wall and not in one square.
    """
    import numpy as np

    from exulanica_appearance.canonical import parse_canonical
    from exulanica_appearance.containers import read_container
    from exulanica_appearance.generation import read_generation

    manifest = json.loads((repository / "assets" / "textures" / "manifest.json").read_bytes())
    pinned = {entry["content_sha256"]: entry for entry in manifest["sets"]}
    summary = parse_canonical((results / "results.json").read_bytes(), "the results")
    out.mkdir(parents=True, exist_ok=True)

    by_target: dict[str, list[dict]] = {}
    for item in summary["generations"]:
        by_target.setdefault(item["target"], []).append(item)

    written = []
    for target, items in sorted(by_target.items()):
        record = read_generation(
            (results / "records" / f"{items[0]['record_sha256']}.json").read_bytes()
        )
        source = record["conditioning"][0]["sources"][0]
        entry = pinned[source]
        raw = (repository / "assets" / "textures" / "blobs" / f"{source}.ltex").read_bytes()
        _, maps = read_container(raw, entry)
        panels: list[tuple[str, np.ndarray]] = [
            (f"{entry['set_id']} as the recipe paints it", maps["base_color"])
        ]
        for item in sorted(
            items, key=lambda value: (value["candidate"], value["role"], value["index"])
        )[:3]:
            pixels = np.frombuffer(
                (results / "outputs" / f"{item['output_sha256']}.rgb").read_bytes(), dtype=np.uint8
            )
            side = int((pixels.size // 3) ** 0.5)
            label = (
                f"{item['candidate']} {item['role']} seed {item['seed']} "
                f"seams {item['seams_ppm']['u'] / 1e6:.2f}/{item['seams_ppm']['v'] / 1e6:.2f}"
            )
            panels.append((label, pixels.reshape(side, side, 3)))
        width = 420
        sheet = Image.new("RGB", (width * len(panels), width * 2 + _LABEL * 2), (18, 18, 20))
        draw = ImageDraw.Draw(sheet)
        for column, (label, pixels) in enumerate(panels):
            picture = Image.fromarray(np.ascontiguousarray(pixels))
            sheet.paste(
                picture.resize((width, width), Image.Resampling.LANCZOS), (column * width, _LABEL)
            )
            draw.text((column * width + 6, 4), label[:64], fill=(230, 230, 230))
            tiled = Image.new("RGB", (pixels.shape[1] * tile, pixels.shape[0] * tile))
            for row in range(tile):
                for step in range(tile):
                    tiled.paste(picture, (step * pixels.shape[1], row * pixels.shape[0]))
            sheet.paste(
                tiled.resize((width, width), Image.Resampling.LANCZOS),
                (column * width, width + _LABEL * 2),
            )
            draw.text(
                (column * width + 6, width + _LABEL + 4), f"{tile} by {tile}", fill=(200, 200, 200)
            )
        path = out / f"pairs-{target}.png"
        sheet.save(path)
        written.append(path)
    return written
