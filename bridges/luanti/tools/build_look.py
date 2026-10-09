"""Build the look a Luanti traveller arrives in from the operator's own copy of Minetest Game.

    <checkout>/.venv/bin/python bridges/luanti/tools/build_look.py MINETEST_GAME_DIR OUT_DIR

A player in Minetest Game's default skin arrives looking like their own character: the game's
player picture, ``mods/player_api/models/character.png`` (by Jordach, CC BY-SA 3.0), in its legacy
64 by 32 layout (a head and its outer layer, a body, one arm and one leg, the other arm and leg
mirrored). Each opaque pixel becomes one square face, 53 mm on a side and coloured as the pixel,
on the humanoid/v1 bone it moves with, in the plan's T-pose: the character faces +y with its left
at -x, head 8, body 12 and legs 12 pixels tall (1,696 mm), arms held out level with the
shoulders. An arm's twelve rows are its upper arm, forearm and hand, a leg's its thigh, shin and
foot, so the joints bend. The container is written by :mod:`exulanica.things.pieces`, so the same
picture writes the same bytes on any machine.

Refused unless the picture and the game's licence file are exactly the ones this build pins by
SHA-256 (the picture's digest is the one the mapping file names as the look's ``source_sha256``):
no other skin is ever used.

Writes, into ``OUT_DIR`` (which must be ignored by git): ``luanti-default-player.glb`` and a look
document for each version, ``luanti-default-player.v1.json`` and ``.v2.json``, whose origin carries
the licence, its attribution and the change made. The versions are one figure under one credit and
differ only in their label: version 2's names no game. A deployment admits the version its mapping
names. The look is an adaptation of the picture under CC BY-SA 3.0: it is admitted to a
deployment's store, credited wherever it is shown, never committed, never part of a shipped image,
and never mixed into an Apache-2.0 or CC0 file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
import zlib
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHECKOUT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CHECKOUT))

from exulanica.canonical import sha256_of_canonical  # noqa: E402
from exulanica.things.looks import read_look  # noqa: E402
from exulanica.things.pieces import MeshPart, Node, write_container  # noqa: E402

#: The player picture and its licence file in Minetest Game ContentDB release 38214.
PICTURE = Path("mods/player_api/models/character.png")
PICTURE_SHA256 = "351626fcb8155d6285315a213ff4ae668a9607a3eda776663512dd799ec8437a"
LICENCE_FILE = Path("mods/player_api/license.txt")
LICENCE_SHA256 = "3726836be696070e5e66c58cc2f00f3ad901fca07dccc651c9df6291fc00da67"
LOOK = "luanti-default-player"
#: Each version of the look by the label a world shows for it: version 2 says what version 1 says in
#: words that name no game, for a deployment that would not name it.
LABELS = {1: "a luanti player's own look", 2: "a player's own look"}
#: Millimetres per picture pixel: 32 pixels tall make a 1,696 mm figure.
P = 53


class Refused(SystemExit):
    def __init__(self, detail: str) -> None:
        super().__init__(f"build_look refused: {detail}")


def read_png(data: bytes) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    """An 8-bit RGBA or RGB PNG, not interlaced, as its width, height and pixels."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise Refused("not a PNG")
    position, chunks, header = 8, [], None
    while position < len(data):
        (length,) = struct.unpack(">I", data[position : position + 4])
        kind = data[position + 4 : position + 8]
        body = data[position + 8 : position + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            chunks.append(body)
        position += 12 + length
    if header is None:
        raise Refused("a PNG with no header")
    width, height, depth, colour, _, _, interlace = header
    if depth != 8 or colour not in (2, 6) or interlace != 0:
        raise Refused("an 8-bit RGB or RGBA picture, not interlaced")
    channels = 4 if colour == 6 else 3
    raw = zlib.decompress(b"".join(chunks))
    stride = width * channels
    rows: list[bytearray] = []
    previous = bytearray(stride)
    for row in range(height):
        start = row * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1 : start + 1 + stride])
        for index in range(stride):
            left = line[index - channels] if index >= channels else 0
            up = previous[index]
            corner = previous[index - channels] if index >= channels else 0
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
    pixels = []
    for line in rows:
        for x in range(width):
            values = tuple(line[x * channels : (x + 1) * channels])
            pixels.append(values if channels == 4 else (*values, 255))
    return width, height, pixels


#: How close two shades must be to be drawn as one: each colour on each bone is one part the
#: renderer draws, so shades within this distance (in 8-bit RGB) of a more common one take its
#: colour. A colour farther than this from every more common one keeps its own: the eyes, a buckle.
SHADE_DISTANCE = 16


def merged_shades(colours: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """The palette the look is drawn in: the picture's colours from the most to the least common
    (ties by value), each kept unless a kept one lies within :data:`SHADE_DISTANCE`. Integers
    throughout, so the same picture makes the same palette everywhere."""
    counts: dict[tuple[int, int, int], int] = defaultdict(int)
    for colour in colours:
        counts[colour] += 1
    kept: list[tuple[int, int, int]] = []
    for colour, _ in sorted(counts.items(), key=lambda entry: (-entry[1], entry[0])):
        if all(
            sum((colour[axis] - other[axis]) ** 2 for axis in range(3)) > SHADE_DISTANCE**2
            for other in kept
        ):
            kept.append(colour)
    return sorted(kept)


class Picture:
    def __init__(self, width: int, height: int, pixels: list[tuple[int, int, int, int]]) -> None:
        self.width, self.height, self.pixels = width, height, pixels
        opaque = [(r, g, b) for r, g, b, a in pixels if a >= 128]
        self.palette = merged_shades(opaque)

    def colour(self, u: int, v: int) -> str | None:
        """The pixel at (u, v) as its nearest palette colour, #rrggbb, or None where it is not
        opaque."""
        red, green, blue, alpha = self.pixels[v * self.width + u]
        if alpha < 128:
            return None
        nearest = min(
            self.palette,
            key=lambda c: ((c[0] - red) ** 2 + (c[1] - green) ** 2 + (c[2] - blue) ** 2, c),
        )
        return "#{:02x}{:02x}{:02x}".format(*nearest)


@dataclass(frozen=True)
class Sheet:
    """One face of a box as a grid of picture pixels: the plane it lies in, which way it faces,
    how its columns and rows run in millimetres, and which picture pixel each cell shows."""

    normal: tuple[int, int, int]
    plane: tuple[int, int]
    columns: tuple[int, int, int, int]
    rows: tuple[int, int, int, int]
    pixel: Callable[[int, int], tuple[int, int]]

    def corner(self, i: int, j: int) -> tuple[int, int, int]:
        """Where column boundary ``i`` meets row boundary ``j``, in whole millimetres."""
        point = [0, 0, 0]
        point[self.plane[0]] = self.plane[1]
        for (axis, start, end, count), index in ((self.columns, i), (self.rows, j)):
            point[axis] = start + round((end - start) * index / count)
        return (point[0], point[1], point[2])

    def mirrored(self) -> Sheet:
        """The same face across x = 0, showing the same pixels: the legacy layout's other limb."""

        def flip(run: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
            axis, start, end, count = run
            return (axis, -start, -end, count) if axis == 0 else run

        plane = (0, -self.plane[1]) if self.plane[0] == 0 else self.plane
        normal = (-self.normal[0], self.normal[1], self.normal[2])
        return Sheet(normal, plane, flip(self.columns), flip(self.rows), self.pixel)


def hanging_box(
    u: int, v: int, size: tuple[int, int, int], box: tuple[int, int, int, int, int, int]
) -> list[Sheet]:
    """The six faces of a box drawn from the legacy layout at (u, v), standing upright: ``size``
    is its width, height and depth in pixels, ``box`` its x0, x1, y0, y1, z0, z1 in mm. Facing the
    character, the picture's left is the character's right (+x)."""
    width, height, depth = size
    x0, x1, y0, y1, z0, z1 = box
    return [
        Sheet(
            (0, 1, 0),
            (1, y1),
            (0, x1, x0, width),
            (2, z1, z0, height),
            lambda i, j: (u + depth + i, v + depth + j),
        ),
        Sheet(
            (0, -1, 0),
            (1, y0),
            (0, x0, x1, width),
            (2, z1, z0, height),
            lambda i, j: (u + 2 * depth + width + i, v + depth + j),
        ),
        Sheet(
            (1, 0, 0),
            (0, x1),
            (1, y0, y1, depth),
            (2, z1, z0, height),
            lambda i, j: (u + i, v + depth + j),
        ),
        Sheet(
            (-1, 0, 0),
            (0, x0),
            (1, y1, y0, depth),
            (2, z1, z0, height),
            lambda i, j: (u + depth + width + i, v + depth + j),
        ),
        Sheet(
            (0, 0, 1),
            (2, z1),
            (0, x1, x0, width),
            (1, y0, y1, depth),
            lambda i, j: (u + depth + i, v + j),
        ),
        Sheet(
            (0, 0, -1),
            (2, z0),
            (0, x1, x0, width),
            (1, y1, y0, depth),
            lambda i, j: (u + depth + width + i, v + j),
        ),
    ]


def level_arm(u: int, v: int, box: tuple[int, int, int, int, int, int]) -> list[Sheet]:
    """The character's right arm held out level along +x in the T-pose: the legacy arm turned a
    quarter about y, so its outer side faces up, its inner side down, its shoulder end the body and
    its hand end outwards. ``box`` is x0 (the shoulder), x1, y0, y1, z0, z1 in mm."""
    x0, x1, y0, y1, z0, z1 = box
    along = (0, x0, x1, 12)
    return [
        Sheet((0, 1, 0), (1, y1), (2, z1, z0, 4), along, lambda i, j: (u + 4 + i, v + 4 + j)),
        Sheet((0, -1, 0), (1, y0), (2, z0, z1, 4), along, lambda i, j: (u + 12 + i, v + 4 + j)),
        Sheet((0, 0, 1), (2, z1), (1, y0, y1, 4), along, lambda i, j: (u + i, v + 4 + j)),
        Sheet((0, 0, -1), (2, z0), (1, y1, y0, 4), along, lambda i, j: (u + 8 + i, v + 4 + j)),
        Sheet((-1, 0, 0), (0, x0), (2, z1, z0, 4), (1, y0, y1, 4), lambda i, j: (u + 4 + i, v + j)),
        Sheet((1, 0, 0), (0, x1), (2, z1, z0, 4), (1, y1, y0, 4), lambda i, j: (u + 8 + i, v + j)),
    ]


#: Each joint of the humanoid plan this figure dresses, where it stands in the T-pose (mm).
JOINTS = {
    "hips": (0, 0, 12 * P),
    "spine": (0, 0, 16 * P),
    "chest": (0, 0, 20 * P),
    "neck": (0, 0, 24 * P),
    "head": (0, 0, 24 * P),
    "leftUpperLeg": (-2 * P, 0, 12 * P),
    "leftLowerLeg": (-2 * P, 0, 6 * P),
    "leftFoot": (-2 * P, 0, 1 * P),
    "rightUpperLeg": (2 * P, 0, 12 * P),
    "rightLowerLeg": (2 * P, 0, 6 * P),
    "rightFoot": (2 * P, 0, 1 * P),
    "leftUpperArm": (-4 * P, 0, 22 * P),
    "leftLowerArm": (-10 * P, 0, 22 * P),
    "leftHand": (-15 * P, 0, 22 * P),
    "rightUpperArm": (4 * P, 0, 22 * P),
    "rightLowerArm": (10 * P, 0, 22 * P),
    "rightHand": (15 * P, 0, 22 * P),
}

Corners = tuple[tuple[int, int, int], ...]


def bone_of(part: str, side: str, corners: Corners) -> str:
    """The bone a face moves with, from where it lies along its limb or body."""
    x = sum(corner[0] for corner in corners) / len(corners)
    z = sum(corner[2] for corner in corners) / len(corners)
    if part == "head":
        return "head"
    if part == "body":
        return "chest" if z >= 20 * P else "spine" if z >= 16 * P else "hips"
    if part == "leg":
        joint = "UpperLeg" if z > 6 * P else "LowerLeg" if z > 1 * P else "Foot"
        return f"{side}{joint}"
    reach = abs(x)
    joint = "UpperArm" if reach < 10 * P else "LowerArm" if reach < 15 * P else "Hand"
    return f"{side}{joint}"


def rectangles(
    sheet: Sheet, picture: Picture, part: str, side: str
) -> list[tuple[str, str, Corners, tuple[int, int, int]]]:
    """A face's opaque pixels as few rectangles: neighbouring pixels of one colour on one bone
    merged, row runs first, then down while the whole run matches. Each as (colour, bone,
    corners, normal)."""
    columns, rows = sheet.columns[3], sheet.rows[3]
    cells: dict[tuple[int, int], tuple[str, str]] = {}
    for j in range(rows):
        for i in range(columns):
            colour = picture.colour(*sheet.pixel(i, j))
            if colour is not None:
                corners = (
                    sheet.corner(i, j),
                    sheet.corner(i + 1, j),
                    sheet.corner(i + 1, j + 1),
                    sheet.corner(i, j + 1),
                )
                cells[(i, j)] = (colour, bone_of(part, side, corners))
    taken: set[tuple[int, int]] = set()
    found = []
    for j in range(rows):
        for i in range(columns):
            if (i, j) in taken or (i, j) not in cells:
                continue
            key = cells[(i, j)]

            def free(cell: tuple[int, int], key: tuple[str, str] = key) -> bool:
                return cell not in taken and cells.get(cell) == key

            last_i = i
            while free((last_i + 1, j)):
                last_i += 1
            last_j = j
            while all(free((k, last_j + 1)) for k in range(i, last_i + 1)):
                last_j += 1
            taken.update((a, b) for a in range(i, last_i + 1) for b in range(j, last_j + 1))
            corners = (
                sheet.corner(i, j),
                sheet.corner(last_i + 1, j),
                sheet.corner(last_i + 1, last_j + 1),
                sheet.corner(i, last_j + 1),
            )
            found.append((key[0], key[1], corners, sheet.normal))
    return found


def figure(picture: Picture) -> tuple[Node, ...]:
    """The figure's joint nodes, each holding one mesh per colour of the faces it moves with."""
    head = (-4 * P, 4 * P, -4 * P, 4 * P, 24 * P, 32 * P)
    outer = (-4 * P - 26, 4 * P + 26, -4 * P - 26, 4 * P + 26, 24 * P - 26, 32 * P + 26)
    leg = hanging_box(0, 16, (4, 12, 4), (0, 4 * P, -2 * P, 2 * P, 0, 12 * P))
    arm = level_arm(40, 16, (4 * P, 16 * P, -2 * P, 2 * P, 20 * P, 24 * P))
    pieces: list[tuple[str, str, list[Sheet]]] = [
        ("head", "", hanging_box(0, 0, (8, 8, 8), head)),
        ("head", "", hanging_box(32, 0, (8, 8, 8), outer)),
        (
            "body",
            "",
            hanging_box(16, 16, (8, 12, 4), (-4 * P, 4 * P, -2 * P, 2 * P, 12 * P, 24 * P)),
        ),
        ("leg", "right", leg),
        ("leg", "left", [sheet.mirrored() for sheet in leg]),
        ("arm", "right", arm),
        ("arm", "left", [sheet.mirrored() for sheet in arm]),
    ]
    by_bone: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for part, side, sheets in pieces:
        for sheet in sheets:
            for colour, bone, corners, normal in rectangles(sheet, picture, part, side):
                by_bone[bone][colour].append((corners, normal))
    nodes = []
    for bone, at in JOINTS.items():
        parts = []
        for colour in sorted(by_bone.get(bone, {})):
            vertices: list[tuple[int, int, int]] = []
            triangles: list[tuple[int, int, int]] = []
            for corners, normal in by_bone[bone][colour]:
                local = [tuple(c[axis] - at[axis] for axis in range(3)) for c in corners]
                a, b, c = local[0], local[1], local[2]
                ab = [b[k] - a[k] for k in range(3)]
                ac = [c[k] - a[k] for k in range(3)]
                cross = (
                    ab[1] * ac[2] - ab[2] * ac[1],
                    ab[2] * ac[0] - ab[0] * ac[2],
                    ab[0] * ac[1] - ab[1] * ac[0],
                )
                if sum(cross[k] * normal[k] for k in range(3)) < 0:
                    local = [local[0], local[3], local[2], local[1]]
                first = len(vertices)
                vertices += local
                triangles += [(first, first + 1, first + 2), (first, first + 2, first + 3)]
            parts.append(
                MeshPart(f"{bone}-{colour[1:]}", tuple(vertices), tuple(triangles), colour)
            )
        nodes.append(Node(f"bone:{bone}", at, tuple(parts)))
    return tuple(nodes)


def look_document(container: bytes, height_mm: int, version: int = 1) -> dict[str, Any]:
    return {
        "profile": "exulanica.look/v1",
        "look": LOOK,
        "version": version,
        "label": LABELS[version],
        "body_plan": "humanoid/v1",
        "look_kind": "rigid_on_bones",
        "container": {
            "sha256": hashlib.sha256(container).hexdigest(),
            "bytes": len(container),
            "media_type": "model/gltf-binary",
        },
        "rig": None,
        "height_mm": height_mm,
        "sampling": "nearest",
        "light": None,
        "role": None,
        "origin": {
            "profile": "exulanica.origin/v1",
            "class": "imported",
            "by": {"kind": "project"},
            "sources": [
                {
                    "reference": (
                        "Minetest Game "
                        "(https://content.luanti.org/packages/Minetest/minetest_game/), "
                        "mods/player_api/models/character.png"
                    ),
                    "retrieved_on": None,
                    "revision": "ContentDB release 38214",
                    "licence_page_sha256": LICENCE_SHA256,
                }
            ],
            "licence": {
                "spdx": "CC-BY-SA-3.0",
                "verdict": "SHIP-ATTRIB",
                "attribution": (
                    "character.png by Jordach (CC BY-SA 3.0), from Minetest Game; changed: close "
                    "shades merged, each pixel a coloured face on the humanoid/v1 bones"
                ),
                "share_alike": True,
                "licence_url": "https://creativecommons.org/licenses/by-sa/3.0/",
                "licence_text_sha256": LICENCE_SHA256,
            },
            "authors": ["Jordach"],
            "lineage": {
                "ingredients": [PICTURE_SHA256],
                "receipts": [],
                "translation_manifest_sha256": None,
            },
            "distribution": "public",
        },
    }


def build(game: Path) -> tuple[bytes, dict[int, dict[str, Any]]]:
    """The look's container and its document at each version, from the operator's own copy."""
    picture_bytes = (game / PICTURE).read_bytes()
    if hashlib.sha256(picture_bytes).hexdigest() != PICTURE_SHA256:
        raise Refused(f"{PICTURE} is not the picture this build pins; no other skin is used")
    if hashlib.sha256((game / LICENCE_FILE).read_bytes()).hexdigest() != LICENCE_SHA256:
        raise Refused(f"{LICENCE_FILE} is not the licence file this build pins")
    width, height, pixels = read_png(picture_bytes)
    if (width, height) != (64, 32):
        raise Refused("the legacy layout is 64 by 32 pixels")
    nodes = figure(Picture(width, height, pixels))
    container = write_container(nodes)
    top = max(
        node.at_mm[2] + vertex[2]
        for node in nodes
        for part in node.parts
        for vertex in part.vertices_mm
    )
    documents = {version: look_document(container, top, version) for version in LABELS}
    for document in documents.values():
        read_look(document)
    return container, documents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("game", type=Path, help="the operator's own Minetest Game folder")
    parser.add_argument("out", type=Path, help="a folder git ignores")
    arguments = parser.parse_args(argv)
    arguments.out.mkdir(parents=True, exist_ok=True)
    ignored = subprocess.run(
        ["git", "-C", str(CHECKOUT), "check-ignore", "-q", str(arguments.out.resolve())],
        check=False,
    )
    if ignored.returncode != 0:
        raise Refused(f"{arguments.out} is not ignored by git; the look is never committed")
    container, documents = build(arguments.game)
    (arguments.out / f"{LOOK}.glb").write_bytes(container)
    for version, document in documents.items():
        path = arguments.out / f"{LOOK}.v{version}.json"
        path.write_text(json.dumps(document, indent=2) + "\n")
    print(
        json.dumps(
            {
                "look": LOOK,
                "look_sha256": {
                    str(version): sha256_of_canonical(document).hex()
                    for version, document in documents.items()
                },
                "container_sha256": hashlib.sha256(container).hexdigest(),
                "container_bytes": len(container),
                "height_mm": documents[1]["height_mm"],
                "source_sha256": PICTURE_SHA256,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
