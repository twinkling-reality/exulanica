"""Read a ready-made kit's model as a mesh with one colour a face.

A kit model is a binary glTF (``.glb``) or a glTF with its buffer and picture beside it
(``.gltf``). Kits colour their models in two ways, and both come to the same thing here: one
8-bit sRGB colour for each triangle.

*   a small picture every model of the kit shares, each face mapped onto one flat patch of it: the
    picture is read where the triangle's middle maps to (its ``KHR_texture_transform`` applied,
    wrapped, nearest pixel);
*   plain materials with no picture: the material's base colour, carried from linear to sRGB.

What is read: each mesh of the default scene with its node's place applied, positions, indices and
the first texture coordinates. A caller may name nodes to leave out, with everything under them (a
boat's spread oars, say); a name the model does not hold is refused, so a record of what was left
out is never a record of nothing. What is not: normals, tangents, skins, animations, cameras, lights
and every extension but the texture transform, which a static piece has no use for. A model whose
file states something this cannot read is refused by name, never guessed at.

The file is untrusted data: it is parsed, never run, and a path it names for its buffer or its
picture is held inside the model's own folder.

Tooling only: it needs numpy and Pillow, which the product does not.
"""

from __future__ import annotations

import base64
import json
import struct
from collections.abc import Collection
from pathlib import Path
from typing import Any, Final

import numpy as np
from PIL import Image

from exulanica_pieces.geometry.mesh import Mesh

__all__ = ["KitModelRefused", "read_kit_model"]

_GLB_MAGIC: Final = 0x46546C67
_JSON_CHUNK: Final = 0x4E4F534A
_BIN_CHUNK: Final = 0x004E4942
_COMPONENTS: Final = {
    5120: np.int8,
    5121: np.uint8,
    5122: np.int16,
    5123: np.uint16,
    5125: np.uint32,
    5126: np.float32,
}
_WIDTHS: Final = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_TRANSFORM: Final = "KHR_texture_transform"


class KitModelRefused(ValueError):
    """A kit model this reader cannot read, named with the file and what it met."""


def _inside(folder: Path, uri: str) -> Path:
    """The file ``uri`` names beside the model, held inside the model's own folder."""
    if uri.startswith(("http:", "https:", "file:", "/")) or "\\" in uri:
        raise KitModelRefused(f"a model names a file outside its folder: {uri!r}")
    path = (folder / uri).resolve()
    if folder.resolve() not in path.parents:
        raise KitModelRefused(f"a model names a file outside its folder: {uri!r}")
    return path


def _document(path: Path) -> tuple[dict[str, Any], bytes | None]:
    data = path.read_bytes()
    if path.suffix.lower() == ".gltf":
        return json.loads(data), None
    magic, version, total = struct.unpack_from("<III", data, 0)
    if (magic, version, total) != (_GLB_MAGIC, 2, len(data)):
        raise KitModelRefused(f"{path.name} is not a binary glTF 2.0 file")
    length, kind = struct.unpack_from("<II", data, 12)
    if kind != _JSON_CHUNK:
        raise KitModelRefused(f"{path.name} does not begin with its JSON")
    document = json.loads(data[20 : 20 + length])
    rest = 20 + length
    if rest >= len(data):
        return document, None
    size, kind = struct.unpack_from("<II", data, rest)
    if kind != _BIN_CHUNK:
        raise KitModelRefused(f"{path.name} holds a chunk that is not its buffer")
    return document, data[rest + 8 : rest + 8 + size]


class _Model:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.document, self._embedded = _document(path)
        self._buffers: dict[int, bytes] = {}
        self._pictures: dict[int, np.ndarray] = {}

    def buffer(self, index: int) -> bytes:
        if index not in self._buffers:
            stated = self.document["buffers"][index]
            uri = stated.get("uri")
            if uri is None:
                if self._embedded is None:
                    raise KitModelRefused(f"{self.path.name} states a buffer it does not hold")
                self._buffers[index] = self._embedded
            elif uri.startswith("data:"):
                self._buffers[index] = base64.b64decode(uri.split(",", 1)[1])
            else:
                self._buffers[index] = _inside(self.path.parent, uri).read_bytes()
        return self._buffers[index]

    def accessor(self, index: int) -> np.ndarray:
        stated = self.document["accessors"][index]
        if "sparse" in stated or "bufferView" not in stated:
            raise KitModelRefused(f"{self.path.name} states a sparse or empty accessor")
        view = self.document["bufferViews"][stated["bufferView"]]
        component = np.dtype(_COMPONENTS[stated["componentType"]]).newbyteorder("<")
        width = _WIDTHS[stated["type"]]
        count = stated["count"]
        start = view.get("byteOffset", 0) + stated.get("byteOffset", 0)
        stride = view.get("byteStride", 0) or component.itemsize * width
        data = self.buffer(view["buffer"])
        if stride == component.itemsize * width:
            values = np.frombuffer(data, dtype=component, count=count * width, offset=start)
            values = values.reshape(count, width)
        else:
            values = np.stack(
                [
                    np.frombuffer(data, dtype=component, count=width, offset=start + i * stride)
                    for i in range(count)
                ]
            )
        values = values.astype(np.float64)
        if stated.get("normalized"):
            values = values / float(np.iinfo(_COMPONENTS[stated["componentType"]]).max)
        return values

    def picture(self, index: int) -> np.ndarray:
        if index not in self._pictures:
            stated = self.document["images"][index]
            if "uri" in stated and not stated["uri"].startswith("data:"):
                source: Any = _inside(self.path.parent, stated["uri"])
            elif "uri" in stated:
                import io

                source = io.BytesIO(base64.b64decode(stated["uri"].split(",", 1)[1]))
            else:
                import io

                view = self.document["bufferViews"][stated["bufferView"]]
                start = view.get("byteOffset", 0)
                source = io.BytesIO(self.buffer(view["buffer"])[start : start + view["byteLength"]])
            with Image.open(source) as opened:
                self._pictures[index] = np.asarray(opened.convert("RGB"), dtype=np.uint8)
        return self._pictures[index]


def _srgb8(linear: np.ndarray) -> np.ndarray:
    """Linear colour in 0 to 1 as sRGB bytes."""
    linear = np.clip(linear, 0.0, 1.0)
    encoded = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)
    return np.rint(encoded * 255).astype(np.uint8)


def _place(node: dict[str, Any]) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    matrix = np.eye(4)
    x, y, z, w = node.get("rotation", (0.0, 0.0, 0.0, 1.0))
    turn = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    matrix[:3, :3] = turn * np.array(node.get("scale", (1.0, 1.0, 1.0)))
    matrix[:3, 3] = node.get("translation", (0.0, 0.0, 0.0))
    return matrix


def _face_colours(
    model: _Model, primitive: dict[str, Any], corners: np.ndarray, faces: int
) -> np.ndarray:
    """One sRGB colour a triangle of ``primitive``: ``corners`` are its triangles' vertex indices."""
    material = model.document.get("materials", [{}])[primitive.get("material", 0)]
    pbr = material.get("pbrMetallicRoughness", {})
    factor = np.array(pbr.get("baseColorFactor", (1.0, 1.0, 1.0, 1.0)), dtype=np.float64)[:3]
    texture = pbr.get("baseColorTexture")
    if texture is None:
        return np.tile(_srgb8(factor), (faces, 1))
    if texture.get("texCoord", 0) != 0 or "TEXCOORD_0" not in primitive["attributes"]:
        raise KitModelRefused(
            f"{model.path.name} maps its picture by coordinates it does not state"
        )
    coordinates = model.accessor(primitive["attributes"]["TEXCOORD_0"])[:, :2]
    middle = coordinates[corners].mean(axis=1)
    transform = texture.get("extensions", {}).get(_TRANSFORM)
    if transform is not None:
        angle = transform.get("rotation", 0.0)
        cos, sin = np.cos(angle), np.sin(angle)
        middle = middle * np.array(transform.get("scale", (1.0, 1.0)))
        middle = np.stack(
            [cos * middle[:, 0] + sin * middle[:, 1], -sin * middle[:, 0] + cos * middle[:, 1]],
            axis=1,
        ) + np.array(transform.get("offset", (0.0, 0.0)))
    picture = model.picture(model.document["textures"][texture["index"]]["source"])
    height, width = picture.shape[:2]
    middle = middle - np.floor(middle)
    column = np.minimum((middle[:, 0] * width).astype(np.int64), width - 1)
    row = np.minimum((middle[:, 1] * height).astype(np.int64), height - 1)
    sampled = picture[row, column].astype(np.float64) / 255.0
    if np.allclose(factor, 1.0):
        return picture[row, column]
    # A tinted picture: the tint is linear, the picture sRGB.
    linear = np.where(sampled <= 0.04045, sampled / 12.92, ((sampled + 0.055) / 1.055) ** 2.4)
    return _srgb8(linear * factor)


def read_kit_model(path: Path, leave_out: Collection[str] = ()) -> Mesh:
    """``path``'s model as one mesh in its own frame (glTF: metres as the kit means them, +Y up):
    every triangle of its default scene with three vertices of its own, each carrying the
    triangle's colour. A node named in ``leave_out`` is not read, nor anything under it."""
    model = _Model(path)
    document = model.document
    unknown = set(document.get("extensionsRequired", ())) - {_TRANSFORM}
    if unknown:
        raise KitModelRefused(f"{path.name} requires {sorted(unknown)}, which this does not read")
    scenes = document.get("scenes") or [{"nodes": list(range(len(document.get("nodes", []))))}]
    positions: list[np.ndarray] = []
    colours: list[np.ndarray] = []
    pending = [(index, np.eye(4)) for index in scenes[document.get("scene", 0)]["nodes"]]
    seen = 0
    left_out: set[str] = set()
    while pending:
        index, parent = pending.pop()
        seen += 1
        if seen > 4096:
            raise KitModelRefused(f"{path.name} nests more nodes than a model has")
        node = document["nodes"][index]
        if node.get("name") in leave_out:
            left_out.add(node["name"])
            continue
        placed = parent @ _place(node)
        pending.extend((child, placed) for child in node.get("children", ()))
        if "mesh" not in node:
            continue
        for primitive in document["meshes"][node["mesh"]]["primitives"]:
            if primitive.get("mode", 4) != 4:
                continue  # Lines and points draw nothing a piece keeps.
            points = model.accessor(primitive["attributes"]["POSITION"])[:, :3]
            if "indices" in primitive:
                corners = model.accessor(primitive["indices"]).astype(np.int64).reshape(-1, 3)
            else:
                corners = np.arange(len(points), dtype=np.int64).reshape(-1, 3)
            if len(corners) == 0:
                continue
            if corners.max() >= len(points):
                raise KitModelRefused(f"{path.name} names a vertex past its positions")
            world = points @ placed[:3, :3].T + placed[:3, 3]
            positions.append(world[corners].reshape(-1, 3))
            face = _face_colours(model, primitive, corners, len(corners))
            colours.append(np.repeat(face, 3, axis=0))
    if left_out != set(leave_out):
        missing = sorted(set(leave_out) - left_out)
        raise KitModelRefused(f"{path.name} holds no node named {missing} to leave out")
    if not positions:
        raise KitModelRefused(f"{path.name} holds no triangle")
    all_positions = np.concatenate(positions)
    triangles = np.arange(len(all_positions), dtype=np.int64).reshape(-1, 3)
    return Mesh(all_positions, triangles, np.concatenate(colours).astype(np.uint8))
