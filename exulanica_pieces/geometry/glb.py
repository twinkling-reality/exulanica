"""Write a flat-shaded, palette-coloured piece as a plain ``exulanica.static-glb/v1`` container.

One scene, one node, one mesh, one triangle primitive, one material: white base colour, no metal,
full roughness, so the colour is the vertex colour and the page sets roughness, metalness and
emission from the swatch. Attributes are ``POSITION`` and ``NORMAL`` (float) and ``COLOR_0``
(``VEC4`` ``UNSIGNED_SHORT`` normalized, the first three channels from the committed sRGB-to-linear
table, the fourth 65535). No extension, no texture, no compression, no URI: what the product's
static profile admits. Vertices that agree in position, normal and swatch are written once.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Sequence
from typing import Final

import numpy as np

from exulanica_pieces.canonical import Refused
from exulanica_pieces.geometry.mesh import Mesh

__all__ = ["GENERATOR", "write_glb"]

GENERATOR: Final = "exulanica generated-asset writer v1"
_FLOAT: Final = 5126
_USHORT: Final = 5123
_UINT: Final = 5125
_ARRAY_BUFFER: Final = 34962
_ELEMENT_ARRAY_BUFFER: Final = 34963


def _pad(data: bytes, filler: bytes) -> bytes:
    return data + filler * (-len(data) % 4)


def _face_normals(positions: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    a, b, c = (positions[triangles[:, k]] for k in range(3))
    normal = np.cross(b - a, c - a)
    length = np.linalg.norm(normal, axis=1)
    if (length <= 0).any():
        raise Refused("a triangle has no area, so it has no normal")
    return normal / length[:, None]


def write_glb(
    mesh: Mesh, swatch: np.ndarray, palette: Sequence[Sequence[int]], table: Sequence[int]
) -> bytes:
    """``mesh`` is flat (three unshared vertices per triangle) and ``swatch`` names each triangle's
    palette entry, as :func:`~exulanica_pieces.geometry.mesh.flat_palette` returns them."""
    if len(table) != 256:
        raise Refused("the colour table has 256 values")
    triangles = mesh.triangles
    normals = _face_normals(mesh.positions, triangles)
    corner_positions = mesh.positions[triangles].reshape(-1, 3).astype(np.float32)
    corner_normals = np.repeat(normals, 3, axis=0).astype(np.float32)
    corner_swatch = np.repeat(np.asarray(swatch, dtype=np.int64), 3)
    # Merge corners that agree exactly in position, normal and swatch.
    keys = np.concatenate(
        [
            corner_positions.view(np.uint32),
            corner_normals.view(np.uint32),
            corner_swatch[:, None].astype(np.uint32),
        ],
        axis=1,
    )
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    order = np.argsort(first)
    rank = np.empty_like(order)
    rank[order] = np.arange(len(order))
    positions = corner_positions[first[order]]
    vertex_normals = corner_normals[first[order]]
    vertex_swatch = corner_swatch[first[order]]
    indices = rank[inverse.reshape(-1)]
    lookup = np.asarray(table, dtype=np.uint16)
    rgb = lookup[np.asarray(palette, dtype=np.int64)[vertex_swatch]]
    colours = np.concatenate([rgb, np.full((len(rgb), 1), 65535, dtype=np.uint16)], axis=1)
    index_type, index_format = (_USHORT, "<u2") if len(positions) <= 65535 else (_UINT, "<u4")

    views: list[bytes] = [
        positions.astype("<f4").tobytes(),
        vertex_normals.astype("<f4").tobytes(),
        colours.astype("<u2").tobytes(),
        indices.astype(index_format).tobytes(),
    ]
    buffer_views = []
    offset = 0
    binary = b""
    for number, data in enumerate(views):
        target = _ELEMENT_ARRAY_BUFFER if number == 3 else _ARRAY_BUFFER
        buffer_views.append(
            {"buffer": 0, "byteLength": len(data), "byteOffset": offset, "target": target}
        )
        padded = _pad(data, b"\x00")
        binary += padded
        offset += len(padded)
    low = positions.min(axis=0).astype(float).tolist()
    high = positions.max(axis=0).astype(float).tolist()
    document = {
        "accessors": [
            {
                "bufferView": 0,
                "componentType": _FLOAT,
                "count": len(positions),
                "type": "VEC3",
                "min": low,
                "max": high,
            },
            {"bufferView": 1, "componentType": _FLOAT, "count": len(positions), "type": "VEC3"},
            {
                "bufferView": 2,
                "componentType": _USHORT,
                "count": len(positions),
                "normalized": True,
                "type": "VEC4",
            },
            {"bufferView": 3, "componentType": index_type, "count": len(indices), "type": "SCALAR"},
        ],
        "asset": {"generator": GENERATOR, "version": "2.0"},
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(binary)}],
        "materials": [
            {
                "pbrMetallicRoughness": {
                    "baseColorFactor": [1, 1, 1, 1],
                    "metallicFactor": 0,
                    "roughnessFactor": 1,
                }
            }
        ],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"COLOR_0": 2, "NORMAL": 1, "POSITION": 0},
                        "indices": 3,
                        "material": 0,
                    }
                ]
            }
        ],
        "nodes": [{"mesh": 0}],
        "scene": 0,
        "scenes": [{"nodes": [0]}],
    }
    json_chunk = _pad(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "ascii"
        ),
        b" ",
    )
    total = 12 + 8 + len(json_chunk) + 8 + len(binary)
    return b"".join(
        [
            struct.pack("<III", 0x46546C67, 2, total),
            struct.pack("<II", len(json_chunk), 0x4E4F534A),
            json_chunk,
            struct.pack("<II", len(binary), 0x004E4942),
            binary,
        ]
    )
