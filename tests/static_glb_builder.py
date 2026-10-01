"""glTF binaries built in code for the static GLB profile's tests.

The Python suite carries no binary fixture (``tests/conftest.py``), so every container a test
admits, prepares or refuses is written here from a document and typed arrays. The builder writes
exactly what it is told, hostile containers included: it checks nothing a test might want to get
wrong on purpose.
"""

from __future__ import annotations

import io
import json
import struct
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from exulanica.world.object_glb import stored_png
from PIL import Image

__all__ = ["Gltf", "cube", "jpeg", "pack", "png"]

FLOAT = 5126
UNSIGNED_SHORT = 5123
UNSIGNED_INT = 5125

#: A unit cube's eight corners and its twelve triangles, wound outward.
CUBE_CORNERS = (
    (-0.5, 0.0, -0.5), (0.5, 0.0, -0.5), (0.5, 1.0, -0.5), (-0.5, 1.0, -0.5),
    (-0.5, 0.0, 0.5), (0.5, 0.0, 0.5), (0.5, 1.0, 0.5), (-0.5, 1.0, 0.5),
)  # fmt: skip
CUBE_TRIANGLES = (
    0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4,
    3, 6, 2, 3, 7, 6, 0, 4, 7, 0, 7, 3, 1, 2, 6, 1, 6, 5,
)  # fmt: skip


def pack(
    document: Mapping[str, Any], binary: bytes | None = None, *, json_bytes: bytes | None = None
) -> bytes:
    """A GLB of exactly this JSON and binary chunk, padded as the format says and nothing else."""
    raw = json_bytes if json_bytes is not None else json.dumps(document).encode("utf-8")
    raw += b" " * (-len(raw) % 4)
    parts = [struct.pack("<II", len(raw), 0x4E4F534A), raw]
    if binary is not None:
        padded = binary + b"\x00" * (-len(binary) % 4)
        parts.extend((struct.pack("<II", len(padded), 0x004E4942), padded))
    body = b"".join(parts)
    return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body


def png(width: int, height: int, *, colour: tuple[int, int, int] = (200, 120, 40)) -> bytes:
    return stored_png(width, height, 3, bytes(colour) * (width * height))


def jpeg(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (90, 140, 200)).save(out, format="JPEG", quality=80)
    return out.getvalue()


class Gltf:
    """A document and a binary chunk under construction. Every add returns the new index."""

    def __init__(self, *, generator: str = "exulanica tests") -> None:
        self.document: dict[str, Any] = {"asset": {"version": "2.0", "generator": generator}}
        self.binary = bytearray()

    def _list(self, name: str) -> list[dict[str, Any]]:
        return self.document.setdefault(name, [])

    def view(self, data: bytes, *, target: int | None = None, stride: int | None = None) -> int:
        self.binary.extend(b"\x00" * (-len(self.binary) % 4))
        entry: dict[str, Any] = {
            "buffer": 0,
            "byteOffset": len(self.binary),
            "byteLength": len(data),
        }
        if target is not None:
            entry["target"] = target
        if stride is not None:
            entry["byteStride"] = stride
        self.binary.extend(data)
        self._list("bufferViews").append(entry)
        return len(self.document["bufferViews"]) - 1

    def accessor(self, view: int, component: int, kind: str, count: int, **fields: Any) -> int:
        entry = {"bufferView": view, "componentType": component, "type": kind, "count": count}
        entry.update(fields)
        self._list("accessors").append(entry)
        return len(self.document["accessors"]) - 1

    def positions(self, points: Sequence[Sequence[float]], *, bounds: bool = True) -> int:
        data = b"".join(struct.pack("<3f", *point) for point in points)
        fields: dict[str, Any] = {}
        if bounds:
            fields["min"] = [min(point[axis] for point in points) for axis in range(3)]
            fields["max"] = [max(point[axis] for point in points) for axis in range(3)]
        return self.accessor(self.view(data, target=34962), FLOAT, "VEC3", len(points), **fields)

    def vectors(self, values: Sequence[Sequence[float]], kind: str) -> int:
        width = {"VEC2": 2, "VEC3": 3, "VEC4": 4}[kind]
        data = b"".join(struct.pack(f"<{width}f", *value) for value in values)
        return self.accessor(self.view(data, target=34962), FLOAT, kind, len(values))

    def indices(self, values: Iterable[int], component: int = UNSIGNED_SHORT) -> int:
        items = list(values)
        code = {5121: "B", UNSIGNED_SHORT: "H", UNSIGNED_INT: "I"}[component]
        data = struct.pack(f"<{len(items)}{code}", *items)
        return self.accessor(self.view(data, target=34963), component, "SCALAR", len(items))

    def mesh(self, *primitives: Mapping[str, Any]) -> int:
        self._list("meshes").append({"primitives": [dict(primitive) for primitive in primitives]})
        return len(self.document["meshes"]) - 1

    def node(self, **fields: Any) -> int:
        self._list("nodes").append(dict(fields))
        return len(self.document["nodes"]) - 1

    def scene(self, *roots: int) -> None:
        self.document["scenes"] = [{"nodes": list(roots)}]
        self.document["scene"] = 0

    def image(self, data: bytes, media_type: str) -> int:
        self._list("images").append({"bufferView": self.view(data), "mimeType": media_type})
        return len(self.document["images"]) - 1

    def texture(self, image: int) -> int:
        self._list("textures").append({"source": image})
        return len(self.document["textures"]) - 1

    def material(self, **fields: Any) -> int:
        self._list("materials").append(dict(fields))
        return len(self.document["materials"]) - 1

    def build(self) -> bytes:
        if self.binary:
            self.document.setdefault("buffers", [{"byteLength": len(self.binary)}])
        return pack(self.document, bytes(self.binary) if self.binary else None)


def cube(
    *,
    scale: float = 1.0,
    offset: Sequence[float] = (0.0, 0.0, 0.0),
    node: Mapping[str, Any] | None = None,
    texture: bytes | None = None,
    texture_media_type: str = "image/png",
    extras: bool = False,
) -> Gltf:
    """A cube ``scale`` a side, standing on y = offset[1], as one indexed primitive."""
    gltf = Gltf()
    points = [
        tuple(corner[axis] * scale + offset[axis] for axis in range(3)) for corner in CUBE_CORNERS
    ]
    attributes: dict[str, int] = {"POSITION": gltf.positions(points)}
    primitive: dict[str, Any] = {"attributes": attributes, "indices": gltf.indices(CUBE_TRIANGLES)}
    if texture is not None:
        attributes["TEXCOORD_0"] = gltf.vectors(
            [(corner[0] + 0.5, corner[2] + 0.5) for corner in CUBE_CORNERS], "VEC2"
        )
        source = gltf.image(texture, texture_media_type)
        primitive["material"] = gltf.material(
            pbrMetallicRoughness={"baseColorTexture": {"index": gltf.texture(source)}}
        )
    mesh = gltf.mesh(primitive)
    fields = dict(node or {})
    if extras:
        fields["extras"] = {"exported_from": "C:\\Users\\someone\\bench.blend"}
        gltf.document["asset"]["extras"] = {"tool": "exporter"}
    gltf.scene(gltf.node(mesh=mesh, **fields))
    return gltf
