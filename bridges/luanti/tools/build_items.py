"""Build the things a Luanti player's items become in a world, from the operator's copy of the game.

    <checkout>/.venv/bin/python bridges/luanti/tools/build_items.py GAME_DIR OUT_DIR [--items FILE]

Each item the list names (``tools/items.v1.json`` by default, written by hand) crosses as itself:
its 16 by 16 inventory picture, each opaque pixel a coloured box one pixel deep, ``mm_per_pixel``
on a side so the thing is near its true size, becomes a static look on the rigid/v1 body plan,
sampled by the nearest texel as pixel art is; and a thing kind of that look which one hand holds by
the pixel the list names. Same-coloured pixels in a rectangle are one box. The container is written
by :mod:`exulanica.things.pieces`, so the same picture writes the same bytes on any machine.

Refused unless every picture and every credit file are exactly the ones the list pins by SHA-256.
Each picture's author and licence are read from the credit file the list names (the game's own
media credits), not typed by hand: a picture the file does not credit, or credits under a licence
other than CC BY-SA 3.0, builds nothing.

Writes, into ``OUT_DIR`` (which must be ignored by git): for each item, ``<look>.glb``, the look
``<look>.v1.json`` and the kind ``<kind>.v1.json``; and ``items.json``, each game item with the
digests of its kind, its look and its picture, and the licence words, as a mapping names them. The
looks and kinds are adaptations of the pictures under CC BY-SA 3.0: admitted to a deployment's
store, credited wherever they are shown, never committed, never part of a shipped image, and never
mixed into an Apache-2.0 or CC0 file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHECKOUT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CHECKOUT))

from exulanica.canonical import sha256_of_canonical  # noqa: E402
from exulanica.things.kinds import read_thing_kind  # noqa: E402
from exulanica.things.looks import read_look  # noqa: E402
from exulanica.things.pieces import Node, Part, write_container  # noqa: E402

ITEMS = Path(__file__).resolve().parent / "items.v1.json"
ITEMS_PROFILE = "exulanica-gate.items/v1"
#: The one licence an item look may carry, as a credit file words it, and what it means here.
CREDITED_LICENCE = "CC BY-SA 3.0"
LICENCE = {
    "spdx": "CC-BY-SA-3.0",
    "share_alike": True,
    "licence_url": "https://creativecommons.org/licenses/by-sa/3.0/",
}
#: The change every item look makes to its picture, for the attribution.
CHANGE = "each opaque pixel a coloured box one pixel deep"
#: A pixel at least this opaque is drawn; a fainter one is left out.
OPAQUE = 128
#: The thinnest a thing is: the thing contract's smallest side of a body's box. A picture whose
#: pixels are smaller is drawn this deep.
THINNEST_MM = 10


class Refused(SystemExit):
    def __init__(self, detail: str) -> None:
        super().__init__(f"build_items refused: {detail}")


def read_png(data: bytes) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    """A PNG, not interlaced, as its width, height and RGBA pixels: indexed colour at 1, 2, 4 or 8
    bits with its palette and transparency, or 8-bit grey, grey with alpha, RGB or RGBA."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise Refused("not a PNG")
    position, chunks, header, palette, transparency = 8, [], None, b"", b""
    while position < len(data):
        (length,) = struct.unpack(">I", data[position : position + 4])
        kind = data[position + 4 : position + 8]
        body = data[position + 8 : position + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            transparency = body
        elif kind == b"IDAT":
            chunks.append(body)
        position += 12 + length
    if header is None:
        raise Refused("a PNG with no header")
    width, height, depth, colour, _, _, interlace = header
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour)
    if channels is None or interlace != 0:
        raise Refused("a PNG of a known colour type, not interlaced")
    if (colour == 3 and depth not in (1, 2, 4, 8)) or (colour != 3 and depth != 8):
        raise Refused("indexed colour at 1, 2, 4 or 8 bits, or 8-bit samples")
    if colour == 3 and not palette:
        raise Refused("an indexed picture with no palette")
    raw = zlib.decompress(b"".join(chunks))
    stride = (width * channels * depth + 7) // 8
    step = max(1, channels * depth // 8)
    rows: list[bytearray] = []
    previous = bytearray(stride)
    for row in range(height):
        start = row * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1 : start + 1 + stride])
        for index in range(stride):
            left = line[index - step] if index >= step else 0
            up = previous[index]
            corner = previous[index - step] if index >= step else 0
            if kind == 1:
                line[index] = (line[index] + left) & 0xFF
            elif kind == 2:
                line[index] = (line[index] + up) & 0xFF
            elif kind == 3:
                line[index] = (line[index] + (left + up) // 2) & 0xFF
            elif kind == 4:
                guess = left + up - corner
                nearest = min(
                    (abs(guess - left), 0, left),
                    (abs(guess - up), 1, up),
                    (abs(guess - corner), 2, corner),
                )[2]
                line[index] = (line[index] + nearest) & 0xFF
            elif kind != 0:
                raise Refused(f"an unknown PNG filter {kind}")
        rows.append(line)
        previous = line
    pixels: list[tuple[int, int, int, int]] = []
    for line in rows:
        for x in range(width):
            if colour == 3:
                per_byte = 8 // depth
                shift = 8 - depth * (x % per_byte + 1)
                index = (line[x // per_byte] >> shift) & ((1 << depth) - 1)
                if 3 * index + 3 > len(palette):
                    raise Refused("an index past the palette")
                red, green, blue = palette[3 * index : 3 * index + 3]
                alpha = transparency[index] if index < len(transparency) else 255
                pixels.append((red, green, blue, alpha))
                continue
            values = line[x * channels : (x + 1) * channels]
            if colour == 0:
                pixels.append((values[0], values[0], values[0], 255))
            elif colour == 4:
                pixels.append((values[0], values[0], values[0], values[1]))
            elif colour == 2:
                pixels.append((values[0], values[1], values[2], 255))
            else:
                pixels.append((values[0], values[1], values[2], values[3]))
    return width, height, pixels


_HEADING = re.compile(r"^(?:Created by )?(?P<author>[^(]+?) \((?P<licence>[^)]+)\):$")
_LISTED = re.compile(r"^- `(?P<file>[^`]+)`")


@dataclass(frozen=True)
class Credit:
    """Who made a picture and under what licence, as a credit file says, and on which line."""

    author: str
    licence: str
    line: int


def credit_of(text: str, picture: str) -> Credit:
    """The credit a game's media file gives ``picture``: the heading ``Author (Licence):`` over
    the list naming it (a ``*`` in a listed name stands for any text), else the file's line for
    everything not listed in it. An address in angle brackets is left out of the author."""
    lines = text.splitlines()
    heading: tuple[str, str] | None = None
    for number, line in enumerate(lines, start=1):
        found = _HEADING.match(line.strip())
        if found:
            heading = (found["author"].strip(), found["licence"].strip())
            continue
        listed = _LISTED.match(line.strip())
        if listed and heading is not None:
            pattern = re.escape(listed["file"]).replace(r"\*", ".*")
            named = picture, picture.removesuffix(".png")
            if any(re.fullmatch(pattern, name) for name in named):
                return Credit(_without_address(heading[0]), heading[1], number)
        if not line.strip():
            continue
        if not listed and not found:
            heading = None if line.startswith("#") else heading
    for number, line in enumerate(lines, start=1):
        if line.strip() == "Everything not listed in here:" and number < len(lines):
            rest = lines[number].strip()
            found = re.fullmatch(r"(?P<author>.+?) \((?P<licence>[^)]+)\)", rest)
            if found:
                return Credit(_without_address(found["author"]), found["licence"], number + 1)
    raise Refused(f"the credit file names no author for {picture}")


def _without_address(author: str) -> str:
    return re.sub(r"\s*<[^>]*>", "", author).strip()


def _colour(pixel: tuple[int, int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*pixel[:3])


def rectangles(width: int, height: int, colour_at: Any) -> list[tuple[int, int, int, int, str]]:
    """The picture's opaque pixels as rectangles of one colour: runs along each row, each grown
    down while the rows below repeat it. Each as (u, v, columns, rows, colour)."""
    taken = [[False] * width for _ in range(height)]
    found: list[tuple[int, int, int, int, str]] = []
    for v in range(height):
        u = 0
        while u < width:
            colour = colour_at(u, v)
            if colour is None or taken[v][u]:
                u += 1
                continue
            run = 1
            while u + run < width and not taken[v][u + run] and colour_at(u + run, v) == colour:
                run += 1
            rows = 1
            while v + rows < height and all(
                not taken[v + rows][u + i] and colour_at(u + i, v + rows) == colour
                for i in range(run)
            ):
                rows += 1
            for dv in range(rows):
                for du in range(run):
                    taken[v + dv][u + du] = True
            found.append((u, v, run, rows, colour))
            u += run
    return found


@dataclass(frozen=True)
class Shape:
    """An item's look as built: its node, its box and where a hand holds it, in millimetres."""

    node: Node
    box_mm: tuple[int, int, int]
    grip_mm: tuple[int, int, int]


def shape(width: int, height: int, pixels: list[tuple[int, int, int, int]], item: dict) -> Shape:
    """The picture's opaque pixels as boxes one pixel deep (at least ``THINNEST_MM``),
    ``mm_per_pixel`` on a side: the picture faces +y, its left at -x and its top up, the bottom of
    its opaque pixels at z 0 and their middle at x 0; the grip is the middle of the pixel the item
    names."""
    p = item["mm_per_pixel"]
    if type(p) is not int or p < 2 or p % 2:
        raise Refused(f"{item['game_item']}: mm_per_pixel is an even whole number of millimetres")
    deep = max(p, THINNEST_MM)

    def colour_at(u: int, v: int) -> str | None:
        pixel = pixels[v * width + u]
        return _colour(pixel) if pixel[3] >= OPAQUE else None

    found = rectangles(width, height, colour_at)
    if not found:
        raise Refused(f"{item['game_item']}: the picture has no opaque pixel")
    left = min(u for u, _, _, _, _ in found)
    right = max(u + columns for u, _, columns, _, _ in found)
    top = min(v for _, v, _, _, _ in found)
    bottom = max(v + rows for _, v, _, rows, _ in found)
    # Whole millimetres: the middle of an even number of even-sized pixels.
    middle = (left + right) * p // 2
    parts = []
    for index, (u, v, columns, rows, colour) in enumerate(found):
        parts.append(
            Part(
                name=f"pixels:{index}",
                shape="box",
                size_mm=(columns * p, deep, rows * p),
                centre_mm=(u * p + columns * p // 2 - middle, 0, (bottom - v) * p - rows * p // 2),
                colour=colour,
            )
        )
    u, v = item["grip"]
    if not (left <= u < right and top <= v < bottom) or colour_at(u, v) is None:
        raise Refused(f"{item['game_item']}: the grip is not on an opaque pixel")
    grip = (u * p + p // 2 - middle, 0, (bottom - v) * p - p // 2)
    box = ((right - left) * p, deep, (bottom - top) * p)
    return Shape(Node("item", (0, 0, 0), tuple(parts)), box, grip)


def origin(item: dict, credit: Credit, items: dict) -> dict[str, Any]:
    """Where an item's look and kind come from: its picture in the game, credited by the game's
    own media file (named by digest, with the day it was read), adapted as the look says."""
    picture_name = Path(item["picture"]["path"]).name
    credit_file = items["credit_files"][item["credit_file"]]
    return {
        "profile": "exulanica.origin/v1",
        "class": "imported",
        "by": {"kind": "project"},
        "sources": [
            {
                "reference": f"{items['game']['reference']}, {item['picture']['path']}",
                "retrieved_on": items["credits_read_on"],
                "revision": items["game"]["revision"],
                "licence_page_sha256": credit_file["sha256"],
            }
        ],
        "licence": {
            "spdx": LICENCE["spdx"],
            "verdict": "SHIP-ATTRIB",
            "attribution": (
                f"{picture_name} by {credit.author} ({CREDITED_LICENCE}), from "
                f"{items['game']['content']}; changed: {CHANGE}"
            ),
            "share_alike": LICENCE["share_alike"],
            "licence_url": LICENCE["licence_url"],
            "licence_text_sha256": items["licence_file"]["sha256"],
        },
        "authors": [credit.author],
        "lineage": {
            "ingredients": [item["picture"]["sha256"]],
            "receipts": [],
            "translation_manifest_sha256": None,
        },
        "distribution": "public",
    }


def look_document(item: dict, container: bytes, made: dict) -> dict[str, Any]:
    """The look: a static container on the rigid/v1 plan, drawn at the size it is built (a rigid
    body states no height; its kind's box says how big it is), sampled as pixel art."""
    return {
        "profile": "exulanica.look/v1",
        "look": item["look"],
        "version": 1,
        "label": item["label"],
        "body_plan": "rigid/v1",
        "look_kind": "static",
        "container": {
            "sha256": hashlib.sha256(container).hexdigest(),
            "bytes": len(container),
            "media_type": "model/gltf-binary",
        },
        "rig": None,
        "height_mm": None,
        "sampling": "nearest",
        "light": None,
        "role": None,
        "origin": made,
    }


def kind_document(item: dict, built: Shape, look_sha256: str, made: dict) -> dict[str, Any]:
    width, depth, height = built.box_mm
    x, y, z = built.grip_mm
    return {
        "profile": "exulanica.thing-kind/v1",
        "kind": item["kind"],
        "version": 1,
        "label": item["label"],
        "summary": item["summary"],
        "class": "object",
        "body": {
            "plan": "rigid/v1",
            "box_mm": {"width": width, "depth": depth, "height": height},
            "blocks_walking": False,
        },
        "origin": made,
        "moves": [],
        "abilities": [],
        "offers": [
            {
                "key": "holdable",
                "parameters": {
                    "hands": 1,
                    "grip": {"x_mm": x, "y_mm": y, "z_mm": z},
                    "axis": item["axis"],
                },
            }
        ],
        "routine": None,
        "deciders": None,
        "looks": [{"look": item["look"], "version": 1, "sha256": look_sha256}],
        "ext": {},
    }


def _pinned(game: Path, pinned: dict, what: str) -> bytes:
    data = (game / pinned["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != pinned["sha256"]:
        raise Refused(f"{pinned['path']} is not the {what} the list pins; no other is used")
    return data


def build_item(game: Path, item: dict, items: dict) -> tuple[bytes, dict, dict, dict]:
    """One item's container, look and kind, and its entry for a mapping."""
    picture = _pinned(game, item["picture"], "picture")
    credit_file = items["credit_files"][item["credit_file"]]
    credits = _pinned(game, credit_file, "credit file").decode("utf-8")
    credit = credit_of(credits, Path(item["picture"]["path"]).name)
    if credit.licence != CREDITED_LICENCE:
        raise Refused(
            f"{item['picture']['path']} is credited under {credit.licence}, not {CREDITED_LICENCE}"
        )
    width, height, pixels = read_png(picture)
    if (width, height) != (16, 16):
        raise Refused(f"{item['picture']['path']} is not a 16 by 16 picture")
    built = shape(width, height, pixels, item)
    container = write_container((built.node,))
    made = origin(item, credit, items)
    look = look_document(item, container, made)
    read_look(look)
    look_sha256 = sha256_of_canonical(look).hex()
    kind = kind_document(item, built, look_sha256, made)
    read_thing_kind(kind)
    entry = {
        "game_item": item["game_item"],
        "kind": {"key": item["kind"], "version": 1, "sha256": sha256_of_canonical(kind).hex()},
        "look": {"look": item["look"], "version": 1, "sha256": look_sha256},
        "source_sha256": item["picture"]["sha256"],
        "ways": "both",
        "words": item["words"],
        "outcome": "exact",
        "licence": {
            "spdx": LICENCE["spdx"],
            "attribution": made["licence"]["attribution"],
            "share_alike": LICENCE["share_alike"],
            "licence_url": LICENCE["licence_url"],
        },
        "credit_line": credit.line,
    }
    return container, look, kind, entry


def read_items(path: Path) -> dict[str, Any]:
    items = json.loads(path.read_text())
    if items.get("profile") != ITEMS_PROFILE:
        raise Refused(f"{path.name} is not {ITEMS_PROFILE}")
    return items


def build(game: Path, items: dict) -> list[tuple[bytes, dict, dict, dict]]:
    _pinned(game, items["licence_file"], "licence file")
    return [build_item(game, item, items) for item in items["items"]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("game", type=Path, help="the operator's own copy of the game")
    parser.add_argument("out", type=Path, help="a folder git ignores")
    parser.add_argument("--items", type=Path, default=ITEMS, help="the items that cross")
    arguments = parser.parse_args(argv)
    arguments.out.mkdir(parents=True, exist_ok=True)
    ignored = subprocess.run(
        ["git", "-C", str(CHECKOUT), "check-ignore", "-q", str(arguments.out.resolve())],
        check=False,
    )
    if ignored.returncode != 0:
        raise Refused(f"{arguments.out} is not ignored by git; the looks are never committed")
    built = build(arguments.game, read_items(arguments.items))
    entries = []
    for container, look, kind, entry in built:
        (arguments.out / f"{look['look']}.glb").write_bytes(container)
        (arguments.out / f"{look['look']}.v1.json").write_text(json.dumps(look, indent=2) + "\n")
        (arguments.out / f"{kind['kind']}.v1.json").write_text(json.dumps(kind, indent=2) + "\n")
        entries.append(entry)
    (arguments.out / "items.json").write_text(json.dumps(entries, indent=2) + "\n")
    print(
        json.dumps(
            [
                {
                    "game_item": entry["game_item"],
                    "kind_sha256": entry["kind"]["sha256"],
                    "look_sha256": entry["look"]["sha256"],
                }
                for entry in entries
            ],
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
