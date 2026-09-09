"""Reviewed CC0 geometry, generated rather than committed.

``tests/conftest.py`` states the rule for the Python suite's images and the reason is the same
here: a committed ``.glb`` is bytes nobody in the review can read, and its licence claim is a
sentence in a file next to it rather than a property of the thing. (``web/`` does commit binary
fixtures. This is the backend rule, and it governs a digest a migration pins.) Every asset
below is authored here as vertices and indices, packed into a minimal glTF 2.0 binary by
:func:`_glb`, and dedicated to the public domain under CC0 1.0. That makes the licence a claim
this project is actually in a position to make, and it makes the SHA-256 that migration 0042 pins
reproducible from source on any machine.

Determinism is load-bearing and it is not accidental. The JSON chunk is emitted with sorted keys
and no whitespace, every coordinate is a value that is exact in binary32, and the padding bytes
are fixed. Re-running this module produces the same digest, which is what lets a migration name
the bytes before an object store has ever seen them.

Nothing here writes to the database. The registry row is the reviewed decision and lives in the
migration; the bytes live in the content-addressed store; :func:`seed_reviewed_assets` is the one
function that puts the second where the first says it should be.
"""

from __future__ import annotations

import hashlib
import json
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from exulanica.store.base import ContentAddressedStore

__all__ = [
    "CC0_LICENCE_ID",
    "CC0_LICENCE_TEXT",
    "GLB_MEDIA_TYPE",
    "ReviewedAsset",
    "reviewed_assets",
    "seed_reviewed_assets",
]

GLB_MEDIA_TYPE: Final = "model/gltf-binary"
CC0_LICENCE_ID: Final = "CC0-1.0"

#: The dedication itself, stored as its own blob and referenced by digest. It is short on purpose:
#: it is the statement that applies to these three meshes, not a copy of the full legal code, and
#: a copy nobody updates is worse than a pointer to the canonical text.
CC0_LICENCE_TEXT: Final = (
    "CC0 1.0 Universal Public Domain Dedication\n"
    "\n"
    "The geometry in this asset was authored for the Exulanica repository and is dedicated to\n"
    "the public domain. To the extent possible under law, the authors have waived all copyright\n"
    "and related or neighboring rights to it. The work is published from the repository that\n"
    "generates it and may be copied, modified and distributed, including for commercial\n"
    "purposes, without asking permission.\n"
    "\n"
    "The full text of the dedication is at https://creativecommons.org/publicdomain/zero/1.0/\n"
)

_GLTF_MAGIC: Final = 0x46546C67
_GLTF_VERSION: Final = 2
_CHUNK_JSON: Final = 0x4E4F534A
_CHUNK_BIN: Final = 0x004E4942
_COMPONENT_FLOAT: Final = 5126
_COMPONENT_UNSIGNED_SHORT: Final = 5123
_MODE_TRIANGLES: Final = 4
_TARGET_ARRAY_BUFFER: Final = 34962
_TARGET_ELEMENT_ARRAY_BUFFER: Final = 34963

_Vertex = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class ReviewedAsset:
    """One reviewed asset: its bytes, its licence, and the digests the registry pins."""

    asset_key: str
    title: str
    summary: str
    payload: bytes
    media_type: str = GLB_MEDIA_TYPE
    licence_id: str = CC0_LICENCE_ID

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()

    @property
    def byte_size(self) -> int:
        return len(self.payload)

    @property
    def licence_bytes(self) -> bytes:
        return CC0_LICENCE_TEXT.encode("utf-8")

    @property
    def licence_sha256(self) -> str:
        return hashlib.sha256(self.licence_bytes).hexdigest()


def _pad(data: bytes, filler: bytes) -> bytes:
    """Pad to a four-byte boundary, as the GLB container requires of every chunk."""
    remainder = len(data) % 4
    return data if remainder == 0 else data + filler * (4 - remainder)


def _glb(name: str, vertices: Sequence[_Vertex], indices: Sequence[int]) -> bytes:
    """Pack one indexed triangle mesh into a minimal, deterministic glTF 2.0 binary.

    No material, no normals and no texture. A reviewed asset in this slice is geometry a renderer
    can place and a person can see; a material would be an appearance decision, and appearance is
    a different authority in this backend.
    """
    positions = b"".join(struct.pack("<3f", *vertex) for vertex in vertices)
    index_bytes = _pad(b"".join(struct.pack("<H", value) for value in indices), b"\x00")
    index_offset = len(positions)
    buffer = positions + index_bytes

    document = {
        "accessors": [
            {
                "bufferView": 0,
                "componentType": _COMPONENT_FLOAT,
                "count": len(vertices),
                "max": [max(vertex[axis] for vertex in vertices) for axis in range(3)],
                "min": [min(vertex[axis] for vertex in vertices) for axis in range(3)],
                "type": "VEC3",
            },
            {
                "bufferView": 1,
                "componentType": _COMPONENT_UNSIGNED_SHORT,
                "count": len(indices),
                "type": "SCALAR",
            },
        ],
        "asset": {"generator": "exulanica-reviewed-asset/1", "version": "2.0"},
        "bufferViews": [
            {
                "buffer": 0,
                "byteLength": len(positions),
                "byteOffset": 0,
                "target": _TARGET_ARRAY_BUFFER,
            },
            {
                "buffer": 0,
                "byteLength": len(index_bytes),
                "byteOffset": index_offset,
                "target": _TARGET_ELEMENT_ARRAY_BUFFER,
            },
        ],
        "buffers": [{"byteLength": len(buffer)}],
        "meshes": [
            {
                "name": name,
                "primitives": [
                    {"attributes": {"POSITION": 0}, "indices": 1, "mode": _MODE_TRIANGLES}
                ],
            }
        ],
        "nodes": [{"mesh": 0, "name": name}],
        "scene": 0,
        "scenes": [{"nodes": [0]}],
    }
    json_chunk = _pad(
        json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        ),
        b" ",
    )
    binary_chunk = _pad(buffer, b"\x00")
    total = 12 + 8 + len(json_chunk) + 8 + len(binary_chunk)
    return b"".join(
        (
            struct.pack("<III", _GLTF_MAGIC, _GLTF_VERSION, total),
            struct.pack("<II", len(json_chunk), _CHUNK_JSON),
            json_chunk,
            struct.pack("<II", len(binary_chunk), _CHUNK_BIN),
            binary_chunk,
        )
    )


def _quads(faces: Sequence[tuple[int, int, int, int]]) -> tuple[int, ...]:
    """Triangulate each quad as (a,b,c) and (a,c,d), preserving its winding.

    Faces are given as quads rather than as a flat index list because winding is the one thing a
    reviewer has to be able to check by eye, and a run of thirty-six integers is where a reversed
    face hides. Every quad below is wound counter-clockwise seen from outside, which is what glTF
    means by a front face.
    """
    return tuple(index for a, b, c, d in faces for index in (a, b, c, a, c, d))


def _box(width: float, height: float, depth: float, *, base_at_origin: bool) -> bytes:
    """An axis-aligned box, Y up, in metres.

    ``base_at_origin`` puts the bottom face on y=0 so a placed object sits on the ground rather
    than half inside it. That is a modelling convention rather than a rendering one, and it
    belongs here so every reviewed asset shares it.
    """
    x, z = width / 2, depth / 2
    low = 0.0 if base_at_origin else -height / 2
    high = low + height
    vertices: tuple[_Vertex, ...] = (
        (-x, low, -z),
        (x, low, -z),
        (x, low, z),
        (-x, low, z),
        (-x, high, -z),
        (x, high, -z),
        (x, high, z),
        (-x, high, z),
    )
    faces = (
        (0, 1, 2, 3),  # -Y
        (4, 7, 6, 5),  # +Y
        (0, 4, 5, 1),  # -Z
        (1, 5, 6, 2),  # +X
        (2, 6, 7, 3),  # +Z
        (3, 7, 4, 0),  # -X
    )
    return _glb("box", vertices, _quads(faces))


def _plate(size: float) -> bytes:
    """A flat square in the XZ plane, wound both ways so it is visible from above and below."""
    half = size / 2
    vertices: tuple[_Vertex, ...] = (
        (-half, 0.0, -half),
        (half, 0.0, -half),
        (half, 0.0, half),
        (-half, 0.0, half),
    )
    return _glb("plate", vertices, _quads(((0, 1, 2, 3), (0, 3, 2, 1))))


def reviewed_assets() -> tuple[ReviewedAsset, ...]:
    """The reviewed catalog, in the order migration 0042 seeds it."""
    return (
        ReviewedAsset(
            asset_key="cc0.marker-cube",
            title="Marker cube",
            summary="A half-metre cube resting on the ground plane.",
            payload=_box(0.5, 0.5, 0.5, base_at_origin=True),
        ),
        ReviewedAsset(
            asset_key="cc0.marker-pillar",
            title="Marker pillar",
            summary="A two-metre square pillar resting on the ground plane.",
            payload=_box(0.25, 2.0, 0.25, base_at_origin=True),
        ),
        ReviewedAsset(
            asset_key="cc0.marker-plate",
            title="Marker plate",
            summary="A one-metre flat square lying on the ground plane.",
            payload=_plate(1.0),
        ),
    )


def seed_reviewed_assets(store: ContentAddressedStore) -> tuple[ReviewedAsset, ...]:
    """Write every reviewed asset and the licence text into the content-addressed store.

    Idempotent, because the store is content-addressed: a second call re-hashes the same bytes and
    writes nothing. Returns the catalog so a caller can assert the digests it just made available
    against the ones the migration pinned.
    """
    catalog = reviewed_assets()
    for asset in catalog:
        store.put_bytes(asset.payload)
        store.put_bytes(asset.licence_bytes)
    return catalog
