"""Write a textured piece: one mesh, one primitive per material, every image embedded.

A textured piece (``docs/style-pack-contract.md``, section 4.1) is what this writes and nothing
more: float ``POSITION``, ``NORMAL`` and ``TEXCOORD_0`` and unsigned short or int indices per
primitive; each material a base colour texture, optionally a normal texture, its factors, opaque or
cut out by alpha and never blended; each image a JPEG or PNG in the binary chunk; one node with no
transform. No URI, extension or extras. Every buffer view is read whole by an accessor or an image,
and the binary chunk is its one buffer padded with at most three zero bytes.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass

import numpy as np

__all__ = ["Material", "Primitive", "write_textured_glb"]

_FLOAT = 5126
_USHORT = 5123
_UINT = 5125
_ARRAY = 34962
_ELEMENTS = 34963
_REPEAT = 10497
_CLAMP = 33071


@dataclass(frozen=True)
class Material:
    """One material: its pictures (encoded bytes and media type) and its factors."""

    name: str
    colour_image: bytes
    colour_media: str
    normal_image: bytes | None = None
    alpha_cutoff: float | None = None
    double_sided: bool = False
    roughness: float = 0.85
    base_colour: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    repeat: bool = True


@dataclass(frozen=True)
class Primitive:
    """One primitive's arrays, metres on glTF axes, and the index of its material."""

    material: int
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    indices: np.ndarray


def _pad(data: bytes, filler: bytes = b"\x00") -> bytes:
    return data + filler * (-len(data) % 4)


def write_textured_glb(
    primitives: list[Primitive], materials: list[Material], generator: str
) -> bytes:
    """The piece's bytes: the same arrays and pictures always give the same bytes."""
    blob = bytearray()
    views: list[dict[str, int]] = []
    accessors: list[dict[str, object]] = []

    def view(data: bytes, target: int | None) -> int:
        blob.extend(b"\x00" * (-len(blob) % 4))
        entry = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)}
        if target is not None:
            entry["target"] = target
        blob.extend(data)
        views.append(entry)
        return len(views) - 1

    def accessor(
        array: np.ndarray, kind: str, component: int, target: int, bounds: bool = False
    ) -> int:
        entry: dict[str, object] = {
            "bufferView": view(array.tobytes(), target),
            "componentType": component,
            "count": int(array.shape[0]),
            "type": kind,
        }
        if bounds:
            entry["min"] = [float(v) for v in array.min(axis=0)]
            entry["max"] = [float(v) for v in array.max(axis=0)]
        accessors.append(entry)
        return len(accessors) - 1

    gltf_primitives = []
    for primitive in primitives:
        positions = np.ascontiguousarray(primitive.positions, dtype=np.float32)
        wide = positions.shape[0] > 65535
        gltf_primitives.append(
            {
                "attributes": {
                    "POSITION": accessor(positions, "VEC3", _FLOAT, _ARRAY, bounds=True),
                    "NORMAL": accessor(
                        np.ascontiguousarray(primitive.normals, dtype=np.float32),
                        "VEC3",
                        _FLOAT,
                        _ARRAY,
                    ),
                    "TEXCOORD_0": accessor(
                        np.ascontiguousarray(primitive.uvs, dtype=np.float32),
                        "VEC2",
                        _FLOAT,
                        _ARRAY,
                    ),
                },
                "indices": accessor(
                    np.ascontiguousarray(primitive.indices, dtype=np.uint32 if wide else np.uint16),
                    "SCALAR",
                    _UINT if wide else _USHORT,
                    _ELEMENTS,
                ),
                "material": primitive.material,
                "mode": 4,
            }
        )
    images: list[dict[str, object]] = []
    textures: list[dict[str, int]] = []
    samplers: list[dict[str, int]] = []
    gltf_materials: list[dict[str, object]] = []
    for material in materials:
        wrap = _REPEAT if material.repeat else _CLAMP
        sampler = {"magFilter": 9729, "minFilter": 9987, "wrapS": wrap, "wrapT": wrap}
        if sampler not in samplers:
            samplers.append(sampler)

        def texture(data: bytes, media: str, sampler_index: int = samplers.index(sampler)) -> int:
            images.append({"bufferView": view(data, None), "mimeType": media})
            textures.append({"sampler": sampler_index, "source": len(images) - 1})
            return len(textures) - 1

        entry: dict[str, object] = {
            "name": material.name,
            "pbrMetallicRoughness": {
                "baseColorFactor": list(material.base_colour),
                "baseColorTexture": {
                    "index": texture(material.colour_image, material.colour_media)
                },
                "metallicFactor": 0.0,
                "roughnessFactor": material.roughness,
            },
        }
        if material.normal_image is not None:
            entry["normalTexture"] = {"index": texture(material.normal_image, "image/jpeg")}
        if material.alpha_cutoff is not None:
            entry["alphaMode"] = "MASK"
            entry["alphaCutoff"] = material.alpha_cutoff
        if material.double_sided:
            entry["doubleSided"] = True
        gltf_materials.append(entry)
    document = {
        "asset": {"version": "2.0", "generator": generator},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": gltf_primitives}],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
        "materials": gltf_materials,
        "textures": textures,
        "images": images,
        "samplers": samplers,
    }
    json_chunk = _pad(json.dumps(document, separators=(",", ":"), sort_keys=True).encode(), b" ")
    bin_chunk = _pad(bytes(blob))
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    return (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
        + struct.pack("<II", len(bin_chunk), 0x004E4942)
        + bin_chunk
    )
