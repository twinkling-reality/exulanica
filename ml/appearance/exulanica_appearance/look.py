"""``exulanica.appearance-third-party-look/v1``: every texel looked at before a set is pinned.

A model can paint a mark it learned: lettering, a logo, a badge. The texture lane requires, and the
orchestrator accepted, that before a model-made set is pinned every map is looked at at full
resolution, with what was looked at and what was found recorded. This module cuts each map into 1:1
crops that cover every texel exactly once, so looking is a finite, stated act rather than a glance
at a thumbnail, and writes the record of it.

The record says what was looked at (each crop by digest, with its rectangle), what was found in the
lane's own words, and anything that might be third-party content. The crops also go to the
orchestrator as a contact sheet (:func:`contact_sheet`) with those findings, before any candidate is
handed to the texture lane. Anything the lane is unsure about is said as such rather than decided,
and the operator decides it; a set is not pinned while the list is unresolved.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from exulanica_appearance.canonical import (
    Refused,
    canonical_bytes,
    exact_keys,
    is_count,
    is_sha256,
    is_text,
    parse_canonical,
)

__all__ = [
    "CONTACT_COLUMNS",
    "CROP_PX",
    "LOOK_PROFILE",
    "build_look",
    "contact_sheet",
    "crop_sheets",
    "read_look",
]

LOOK_PROFILE: Final = "exulanica.appearance-third-party-look/v1"
#: 512 px crops: a 1024 map is four of them, each shown at 1:1 with no downscaling, which is what
#: makes lettering legible. A larger crop would not fit a screen at 1:1.
CROP_PX: Final = 512
_DATE: Final = re.compile(r"20[0-9]{2}-[01][0-9]-[0-3][0-9]")
STATEMENT: Final = (
    "Every texel of every map is inside exactly one of these crops, each written at 1:1 with no "
    "resampling, and each was looked at before this set was offered for publication."
)


def crop_sheets(maps: Mapping[str, NDArray[np.uint8]], out: Path) -> list[dict[str, Any]]:
    """Write 1:1 crops covering every texel of every map; return what was written."""
    out.mkdir(parents=True, exist_ok=True)
    crops: list[dict[str, Any]] = []
    for name in sorted(maps):
        pixels = maps[name]
        height, width = pixels.shape[0], pixels.shape[1]
        for top in range(0, height, CROP_PX):
            for left in range(0, width, CROP_PX):
                tile = np.ascontiguousarray(pixels[top : top + CROP_PX, left : left + CROP_PX])
                relative = f"{name}-{top:05d}-{left:05d}.png"
                picture = (
                    tile
                    if tile.ndim == 3 and tile.shape[2] == 3
                    else np.repeat(
                        tile.reshape(tile.shape[0], tile.shape[1], -1)[..., :1], 3, axis=-1
                    )
                )
                Image.fromarray(picture).save(out / relative, format="PNG")
                crops.append(
                    {
                        "file": relative,
                        "height": int(tile.shape[0]),
                        "left": int(left),
                        "map": name,
                        "pixels_sha256": hashlib.sha256(tile.tobytes()).hexdigest(),
                        "top": int(top),
                        "width": int(tile.shape[1]),
                    }
                )
    return crops


def build_look(
    *,
    output_sha256: str,
    crops: Sequence[Mapping[str, Any]],
    maps: Mapping[str, tuple[int, int]],
    found: str,
    suspected: Sequence[str],
    looked_on: str,
    looked_by: str,
) -> bytes:
    document = {
        "crops": sorted(
            (dict(crop) for crop in crops),
            key=lambda item: (item["map"], item["top"], item["left"]),
        ),
        "found": found,
        "looked_by": looked_by,
        "looked_on": looked_on,
        "maps": {name: {"height": size[0], "width": size[1]} for name, size in maps.items()},
        "output_sha256": output_sha256,
        "profile": LOOK_PROFILE,
        "statement": STATEMENT,
        "suspected": list(suspected),
    }
    raw = canonical_bytes(document)
    read_look(raw)
    return raw


def read_look(raw: bytes) -> dict[str, Any]:
    where = "the third-party look record"
    document = exact_keys(
        parse_canonical(raw, where),
        (
            "crops",
            "found",
            "looked_by",
            "looked_on",
            "maps",
            "output_sha256",
            "profile",
            "statement",
            "suspected",
        ),
        where,
    )
    if document["profile"] != LOOK_PROFILE or document["statement"] != STATEMENT:
        raise Refused(
            f"{where}: profile is {LOOK_PROFILE} and the statement is the one this module makes"
        )
    if not is_sha256(document["output_sha256"]):
        raise Refused(f"{where}: output_sha256 is 64 lowercase hex")
    if not is_text(document["found"]) or not is_text(document["looked_by"]):
        raise Refused(
            f"{where}: found and looked_by are printable ASCII; an empty finding is not a finding"
        )
    if not isinstance(document["looked_on"], str) or not _DATE.fullmatch(document["looked_on"]):
        raise Refused(f"{where}: looked_on is a date, YYYY-MM-DD")
    suspected = document["suspected"]
    if not isinstance(suspected, list) or not all(is_text(item) for item in suspected):
        raise Refused(
            f"{where}: suspected lists what might be third-party content, in words, or is empty"
        )
    sizes = {}
    for name, size in document["maps"].items():
        shape = exact_keys(size, ("height", "width"), f"{where}: map {name}")
        if not is_count(shape["height"], 1) or not is_count(shape["width"], 1):
            raise Refused(f"{where}: map {name} states its size in texels")
        sizes[name] = (shape["height"], shape["width"])
    covered: dict[str, int] = {name: 0 for name in sizes}
    seen: set[tuple[str, int, int]] = set()
    for crop in document["crops"]:
        item = exact_keys(
            crop,
            ("file", "height", "left", "map", "pixels_sha256", "top", "width"),
            f"{where}: crop",
        )
        if item["map"] not in sizes:
            raise Refused(
                f"{where}: a crop names the map {item['map']!r}, which the record does not list"
            )
        height, width = sizes[item["map"]]
        if (
            not is_sha256(item["pixels_sha256"])
            or not isinstance(item["file"], str)
            or not is_count(item["top"])
            or not is_count(item["left"])
            or item["top"] + item["height"] > height
            or item["left"] + item["width"] > width
            or item["height"] > CROP_PX
            or item["width"] > CROP_PX
        ):
            raise Refused(f"{where}: crop {item['file']} is not a 1:1 rectangle inside its map")
        if (item["map"], item["top"], item["left"]) in seen:
            raise Refused(f"{where}: crop {item['file']} is listed twice")
        seen.add((item["map"], item["top"], item["left"]))
        covered[item["map"]] += item["height"] * item["width"]
    for name, (height, width) in sizes.items():
        if covered[name] != height * width:
            raise Refused(
                f"{where}: the crops of {name} cover {covered[name]} of its {height * width} texels; "
                "every texel is looked at or the record is not a look"
            )
    return document


#: Four crops across: at 512 px a row of four is 2048 px wide, which reads on a laptop screen while
#: each crop is still shown at 1:1 in its own file.
CONTACT_COLUMNS: Final = 4


def contact_sheet(crops: Sequence[Mapping[str, Any]], directory: Path, out: Path) -> Path:
    """A labelled sheet of every crop, for the orchestrator to look at beside the 1:1 files."""
    from PIL import ImageDraw

    label = 18
    ordered = sorted(crops, key=lambda item: (item["map"], item["top"], item["left"]))
    columns = min(CONTACT_COLUMNS, len(ordered))
    rows = -(-len(ordered) // columns)
    cell_width = max(int(crop["width"]) for crop in ordered)
    cell_height = max(int(crop["height"]) for crop in ordered) + label
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), (18, 18, 20))
    draw = ImageDraw.Draw(sheet)
    for index, crop in enumerate(ordered):
        column, row = index % columns, index // columns
        x, y = column * cell_width, row * cell_height
        with Image.open(directory / crop["file"]) as picture:
            sheet.paste(picture.convert("RGB"), (x, y + label))
        draw.text(
            (x + 4, y + 3),
            f"{crop['map']} at {crop['left']},{crop['top']} 1:1",
            fill=(232, 232, 232),
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out
