"""Static glTF containers written from parts: the looks this repository authors, byte for byte.

A look this repository authors (a blocky figure, a primitive sword, a lantern, a well, a gate) is
written here from parts: boxes and upright cylinders in whole millimetres, each one flat colour
and an optional glow, under named nodes. The container is an ``exulanica.static-glb/v1`` one
(:mod:`exulanica.world.static_glb`): one scene, triangle meshes with positions and normals,
materials with a base colour and an emissive colour, no texture, skin, morph target or animation.
The same parts write the same bytes on any machine: every vertex is a whole number of millimetres
turned into metres by one float32 division, and a cylinder's corners come from a table built from
square roots alone, which IEEE 754 rounds exactly everywhere.

The slot frame the parts are stated in is the world's: x across, y with the front at +y, z up, the
pivot at the base centre. glTF's is +Y up with the front at +Z, which the style packs' rotation
reaches (``X = -x``, ``Y = z``, ``Z = y``: a proper rotation, so nothing is mirrored). A
``rigid_on_bones`` look names each joint node ``bone:<VRM name>`` at the joint's rest position, a
direct child of the scene root, its parts children of it at their offsets from the joint.

Pure: no connection, no store.
"""

from __future__ import annotations

import json
import math
import re
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

__all__ = ["GENERATOR", "Node", "Part", "write_container"]

GENERATOR: Final = "exulanica-things-pieces/1"
_COLOUR: Final = re.compile(r"#[0-9a-f]{6}")
_MAGIC: Final = 0x46546C67
_CHUNK_JSON: Final = 0x4E4F534A
_CHUNK_BIN: Final = 0x004E4942
_FLOAT: Final = 5126
_UNSIGNED_SHORT: Final = 5123
_TRIANGLES: Final = 4
_ARRAY_BUFFER: Final = 34962
_ELEMENT_ARRAY_BUFFER: Final = 34963
#: A cylinder's twelve corners around its axis, as (cos, sin): built from square roots alone.
_HALF_ROOT_THREE: Final = math.sqrt(3) / 2
_CIRCLE: Final = (
    (1.0, 0.0),
    (_HALF_ROOT_THREE, 0.5),
    (0.5, _HALF_ROOT_THREE),
    (0.0, 1.0),
    (-0.5, _HALF_ROOT_THREE),
    (-_HALF_ROOT_THREE, 0.5),
    (-1.0, 0.0),
    (-_HALF_ROOT_THREE, -0.5),
    (-0.5, -_HALF_ROOT_THREE),
    (0.0, -1.0),
    (0.5, -_HALF_ROOT_THREE),
    (_HALF_ROOT_THREE, -0.5),
)


@dataclass(frozen=True, slots=True)
class Part:
    """One solid: a box, or an upright cylinder whose size's width is its diameter, centred at
    ``centre_mm`` from its node, in one colour, glowing where ``glow`` names one."""

    name: str
    shape: str
    size_mm: tuple[int, int, int]
    centre_mm: tuple[int, int, int]
    colour: str
    glow: str | None = None

    def __post_init__(self) -> None:
        if self.shape not in ("box", "cylinder"):
            raise ValueError(f"part {self.name}: a box or a cylinder")
        if any(type(v) is not int or v <= 0 for v in self.size_mm):
            raise ValueError(f"part {self.name}: whole positive millimetres")
        if any(type(v) is not int for v in self.centre_mm):
            raise ValueError(f"part {self.name}: a centre in whole millimetres")
        for colour in (self.colour, self.glow):
            if colour is not None and _COLOUR.fullmatch(colour) is None:
                raise ValueError(f"part {self.name}: colours are #rrggbb in lowercase")


@dataclass(frozen=True, slots=True)
class Node:
    """A named node at ``at_mm`` in the slot frame, holding its parts."""

    name: str
    at_mm: tuple[int, int, int]
    parts: tuple[Part, ...] = ()


def _gltf(x: float, y: float, z: float) -> tuple[float, float, float]:
    """A slot-frame vector in glTF's frame: X = -x, Y = z, Z = y; a zero is written +0."""
    return (-x + 0.0, z + 0.0, y + 0.0)


def _metres(mm: int) -> float:
    return struct.unpack("<f", struct.pack("<f", mm / 1000))[0]


def _box(part: Part) -> tuple[list[tuple[float, ...]], list[tuple[float, ...]], list[int]]:
    w, d, h = part.size_mm
    cx, cy, cz = part.centre_mm
    lo = (cx * 2 - w, cy * 2 - d, cz * 2 - h)
    hi = (cx * 2 + w, cy * 2 + d, cz * 2 + h)
    positions: list[tuple[float, ...]] = []
    normals: list[tuple[float, ...]] = []
    indices: list[int] = []
    # Each face: its outward normal in the slot frame and its four corners, counterclockwise seen
    # from outside, in doubled millimetres (halved when written).
    faces = (
        ((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]),
        ((-1, 0, 0), [(0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)]),
        ((0, 1, 0), [(1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)]),
        ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
        ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]),
        ((0, 0, -1), [(0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0)]),
    )
    for normal, corners in faces:
        base = len(positions)
        for corner in corners:
            doubled = [hi[i] if corner[i] else lo[i] for i in range(3)]
            positions.append(_gltf(*(_metres(v) / 2 for v in doubled)))
            normals.append(_gltf(*map(float, normal)))
        # The rotation into glTF's frame is proper, so a counterclockwise face stays one.
        indices += [base, base + 1, base + 2, base, base + 2, base + 3]
    return positions, normals, indices


def _cylinder(part: Part) -> tuple[list[tuple[float, ...]], list[tuple[float, ...]], list[int]]:
    diameter, _depth, h = part.size_mm
    cx, cy, cz = part.centre_mm
    r = _metres(diameter) / 2
    x0, y0 = _metres(cx), _metres(cy)
    z0, z1 = _metres(cz) - _metres(h) / 2, _metres(cz) + _metres(h) / 2
    positions: list[tuple[float, ...]] = []
    normals: list[tuple[float, ...]] = []
    indices: list[int] = []
    count = len(_CIRCLE)
    for c, s in _CIRCLE:
        for z in (z0, z1):
            positions.append(_gltf(x0 + r * c, y0 + r * s, z))
            normals.append(_gltf(c, s, 0.0))
    for k in range(count):
        a, b = 2 * k, 2 * ((k + 1) % count)
        indices += [a, b, b + 1, a, b + 1, a + 1]
    for z, sign in ((z1, 1.0), (z0, -1.0)):
        centre = len(positions)
        positions.append(_gltf(x0, y0, z))
        normals.append(_gltf(0.0, 0.0, sign))
        rim = len(positions)
        for c, s in _CIRCLE:
            positions.append(_gltf(x0 + r * c, y0 + r * s, z))
            normals.append(_gltf(0.0, 0.0, sign))
        for k in range(count):
            a, b = rim + k, rim + (k + 1) % count
            indices += [centre, a, b] if sign > 0 else [centre, b, a]
    return positions, normals, indices


def _colour(hex_colour: str) -> list[float]:
    """An sRGB colour as glTF's linear factors, by the sRGB transfer function."""
    out = []
    for i in (1, 3, 5):
        value = int(hex_colour[i : i + 2], 16) / 255
        linear = value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        out.append(round(linear, 6))
    return out


def write_container(nodes: Sequence[Node]) -> bytes:
    """The static glTF binary of ``nodes``, each a direct child of the scene root."""
    if len({node.name for node in nodes}) != len(nodes):
        raise ValueError("each node is named once")
    binary = bytearray()
    accessors: list[dict] = []
    views: list[dict] = []
    meshes: list[dict] = []
    materials: list[dict] = []
    material_of: dict[tuple[str, str | None], int] = {}
    gltf_nodes: list[dict] = []
    roots: list[int] = []

    def view(data: bytes, target: int) -> int:
        while len(binary) % 4:
            binary.append(0)
        views.append(
            {"buffer": 0, "byteOffset": len(binary), "byteLength": len(data), "target": target}
        )
        binary.extend(data)
        return len(views) - 1

    for node in nodes:
        children = []
        for part in node.parts:
            positions, normals, indices = (_box if part.shape == "box" else _cylinder)(part)
            if len(positions) > 0xFFFF:
                raise ValueError(f"part {part.name} has too many corners")
            key = (part.colour, part.glow)
            if key not in material_of:
                material = {
                    "name": f"{part.colour}{'' if part.glow is None else '+' + part.glow}",
                    "pbrMetallicRoughness": {
                        "baseColorFactor": [*_colour(part.colour), 1.0],
                        "metallicFactor": 0.0,
                        "roughnessFactor": 0.8,
                    },
                }
                if part.glow is not None:
                    material["emissiveFactor"] = _colour(part.glow)
                materials.append(material)
                material_of[key] = len(materials) - 1
            flat = [value for vertex in positions for value in vertex]
            position_view = view(struct.pack(f"<{len(flat)}f", *flat), _ARRAY_BUFFER)
            normal_flat = [value for vertex in normals for value in vertex]
            normal_view = view(struct.pack(f"<{len(normal_flat)}f", *normal_flat), _ARRAY_BUFFER)
            index_view = view(struct.pack(f"<{len(indices)}H", *indices), _ELEMENT_ARRAY_BUFFER)
            mins = [min(vertex[i] for vertex in positions) for i in range(3)]
            maxs = [max(vertex[i] for vertex in positions) for i in range(3)]
            accessors += [
                {
                    "bufferView": position_view,
                    "componentType": _FLOAT,
                    "count": len(positions),
                    "type": "VEC3",
                    "min": mins,
                    "max": maxs,
                },
                {
                    "bufferView": normal_view,
                    "componentType": _FLOAT,
                    "count": len(normals),
                    "type": "VEC3",
                },
                {
                    "bufferView": index_view,
                    "componentType": _UNSIGNED_SHORT,
                    "count": len(indices),
                    "type": "SCALAR",
                },
            ]
            first = len(accessors) - 3
            meshes.append(
                {
                    "name": part.name,
                    "primitives": [
                        {
                            "attributes": {"POSITION": first, "NORMAL": first + 1},
                            "indices": first + 2,
                            "material": material_of[key],
                            "mode": _TRIANGLES,
                        }
                    ],
                }
            )
            gltf_nodes.append({"name": part.name, "mesh": len(meshes) - 1})
            children.append(len(gltf_nodes) - 1)
        entry: dict = {
            "name": node.name,
            "translation": list(_gltf(*(_metres(v) for v in node.at_mm))),
        }
        if children:
            entry["children"] = children
        gltf_nodes.append(entry)
        roots.append(len(gltf_nodes) - 1)
    while len(binary) % 4:
        binary.append(0)
    document = {
        "asset": {"version": "2.0", "generator": GENERATOR},
        "scene": 0,
        "scenes": [{"nodes": roots}],
        "nodes": gltf_nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(binary)}],
    }
    text = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("ascii")
    text += b" " * (-len(text) % 4)
    total = 12 + 8 + len(text) + 8 + len(binary)
    return b"".join(
        (
            struct.pack("<III", _MAGIC, 2, total),
            struct.pack("<II", len(text), _CHUNK_JSON),
            text,
            struct.pack("<II", len(binary), _CHUNK_BIN),
            bytes(binary),
        )
    )
