"""Write a creature's sculpted look as an ``exulanica.skinned-glb/v1`` container.

The skeleton is the body plan's: one joint node a bone, named ``bone:<bone>``, in the plan's
hierarchy, placed by translation alone (each joint's rest position less its parent's), so the bind
pose is the plan's rest pose and each inverse bind matrix is a translation back by the joint's
rest position. One skinned mesh node with no transform draws one triangle primitive: ``POSITION``
and ``NORMAL`` (float), ``COLOR_0`` (``VEC4`` ``UNSIGNED_SHORT`` normalized, the first three
channels from the committed sRGB-to-linear table, as the generated pieces' writer colours its
swatches), ``JOINTS_0`` (``VEC4`` ``UNSIGNED_BYTE``) and ``WEIGHTS_0`` (``VEC4`` float, summing to
one). Flat: each triangle's three corners carry its own normal and its own colour. No texture,
clip, morph target, extension or external file: what
:func:`exulanica_pieces.skinned.read_skinned_glb` admits, which the writer runs on its own output
before returning it.

Positions arrive in the slot frame (whole millimetres or metres as floats, x across, y forward,
z up); glTF's is +Y up with the front at +Z, reached by ``X = -x``, ``Y = z``, ``Z = y``, a proper
rotation, as every container this repository writes.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping, Sequence
from typing import Final

import numpy as np

from exulanica_pieces.canonical import Refused
from exulanica_pieces.skinned import read_skinned_glb

__all__ = ["GENERATOR", "write_skinned_glb"]

GENERATOR: Final = "exulanica sculpted-creature writer v1"
_FLOAT: Final = 5126
_UBYTE: Final = 5121
_USHORT: Final = 5123
_UINT: Final = 5125
_ARRAY_BUFFER: Final = 34962
_ELEMENT_ARRAY_BUFFER: Final = 34963


def _gltf(slot: np.ndarray) -> np.ndarray:
    """Slot-frame vectors (x, y, z) as glTF's (-x, z, y)."""
    out = np.empty_like(slot, dtype=np.float64)
    out[..., 0] = -slot[..., 0]
    out[..., 1] = slot[..., 2]
    out[..., 2] = slot[..., 1]
    return out + 0.0


def _pad(data: bytes, filler: bytes) -> bytes:
    return data + filler * (-len(data) % 4)


def write_skinned_glb(
    *,
    positions_m: np.ndarray,
    triangles: np.ndarray,
    triangle_colours_srgb8: np.ndarray,
    joint_indices: np.ndarray,
    joint_weights: np.ndarray,
    bones: Sequence[str],
    parents: Mapping[str, str | None],
    rest_m: Mapping[str, Sequence[float]],
    table: Sequence[int],
) -> bytes:
    """The container of a skinned mesh in the slot frame.

    ``positions_m`` (V x 3, metres, slot frame), ``triangles`` (T x 3), ``triangle_colours_srgb8``
    (T x 3, each 0 to 255), ``joint_indices`` (V x 4, indices into ``bones``) and ``joint_weights``
    (V x 4, summing to one), ``bones`` in plan order (a bone's parent before it), ``parents`` each
    bone's plan parent, ``rest_m`` each bone's rest position in metres in the slot frame, ``table``
    the committed sRGB-to-linear colour table."""
    if len(table) != 256:
        raise Refused("the colour table has 256 values")
    positions = np.asarray(positions_m, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.int64)
    if (
        positions.ndim != 2
        or positions.shape[1] != 3
        or triangles.ndim != 2
        or triangles.shape[1] != 3
    ):
        raise Refused("positions are V x 3 and triangles T x 3")
    weights = np.asarray(joint_weights, dtype=np.float64)
    indices = np.asarray(joint_indices, dtype=np.int64)
    if weights.shape != (len(positions), 4) or indices.shape != (len(positions), 4):
        raise Refused("four joints and four weights a vertex")
    if not np.all(np.isfinite(positions)):
        raise Refused("a position is not finite")
    weights = np.where(weights < 0, 0.0, weights)
    sums = weights.sum(axis=1)
    if np.any(sums <= 0):
        raise Refused("a vertex moves with no joint")
    weights = weights / sums[:, None]
    order = {bone: index for index, bone in enumerate(bones)}
    for bone in bones:
        parent = parents[bone]
        if parent is not None and order[parent] >= order[bone]:
            raise Refused(f"bone {bone} comes after its parent {parent}")
    # Flat corners: three a triangle, each with the triangle's normal and its vertex's attributes.
    corners = triangles.reshape(-1)
    corner_positions = _gltf(positions[corners]).astype(np.float32)
    a, b, c = (positions[triangles[:, k]] for k in range(3))
    normal = np.cross(b - a, c - a)
    length = np.linalg.norm(normal, axis=1)
    if np.any(length <= 0):
        raise Refused("a triangle has no area, so it has no normal")
    corner_normals = np.repeat(_gltf(normal / length[:, None]), 3, axis=0).astype(np.float32)
    colours = np.asarray(triangle_colours_srgb8, dtype=np.int64)
    if colours.shape != (len(triangles), 3) or colours.min() < 0 or colours.max() > 255:
        raise Refused("one sRGB colour a triangle, each channel 0 to 255")
    srgb = np.repeat(colours, 3, axis=0)
    lookup = np.asarray(table, dtype=np.int64)
    corner_colours = np.empty((len(corners), 4), dtype=np.uint16)
    corner_colours[:, :3] = lookup[srgb]
    corner_colours[:, 3] = 65535
    corner_joints = indices[corners].astype(np.uint8)
    corner_weights = weights[corners].astype(np.float32)
    # float32 rounding: put any remainder on each vertex's heaviest weight so the four sum to one.
    remainder = (1.0 - corner_weights.astype(np.float64).sum(axis=1)).astype(np.float32)
    heaviest = corner_weights.argmax(axis=1)
    corner_weights[np.arange(len(corner_weights)), heaviest] += remainder
    binary = bytearray()
    views: list[dict] = []
    accessors: list[dict] = []

    def view(data: bytes, target: int | None) -> int:
        while len(binary) % 4:
            binary.append(0)
        entry = {"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)}
        if target is not None:
            entry["target"] = target
        views.append(entry)
        binary.extend(data)
        return len(views) - 1

    def accessor(data: np.ndarray, kind: str, component: int, **extra: object) -> int:
        target = _ARRAY_BUFFER if kind != "MAT4" else None
        accessors.append(
            {
                "bufferView": view(data.tobytes(), target),
                "componentType": component,
                "count": len(data),
                "type": kind,
                **extra,
            }
        )
        return len(accessors) - 1

    count = len(corners)
    position_accessor = accessor(
        corner_positions,
        "VEC3",
        _FLOAT,
        min=[float(v) for v in corner_positions.min(axis=0)],
        max=[float(v) for v in corner_positions.max(axis=0)],
    )
    normal_accessor = accessor(corner_normals, "VEC3", _FLOAT)
    colour_accessor = accessor(corner_colours, "VEC4", _USHORT, normalized=True)
    joint_accessor = accessor(corner_joints, "VEC4", _UBYTE)
    weight_accessor = accessor(corner_weights, "VEC4", _FLOAT)
    rest = {bone: _gltf(np.asarray(rest_m[bone], dtype=np.float64)) for bone in bones}
    binds = np.zeros((len(bones), 16), dtype=np.float32)
    for index, bone in enumerate(bones):
        binds[index] = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, *(-rest[bone]), 1]
    bind_accessor = accessor(binds, "MAT4", _FLOAT)
    nodes: list[dict] = []
    children: dict[str, list[int]] = {bone: [] for bone in bones}
    for index, bone in enumerate(bones):
        parent = parents[bone]
        local = rest[bone] - (rest[parent] if parent is not None else 0.0)
        node: dict = {"name": f"bone:{bone}", "translation": [float(v) + 0.0 for v in local]}
        nodes.append(node)
        if parent is not None:
            children[parent].append(index)
    for index, bone in enumerate(bones):
        if children[bone]:
            nodes[index]["children"] = children[bone]
    roots = [index for index, bone in enumerate(bones) if parents[bone] is None]
    nodes.append({"name": "mesh", "mesh": 0, "skin": 0})
    document = {
        "asset": {"version": "2.0", "generator": GENERATOR},
        "scene": 0,
        "scenes": [{"nodes": [*roots, len(nodes) - 1]}],
        "nodes": nodes,
        "skins": [{"joints": list(range(len(bones))), "inverseBindMatrices": bind_accessor}],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": position_accessor,
                            "NORMAL": normal_accessor,
                            "COLOR_0": colour_accessor,
                            "JOINTS_0": joint_accessor,
                            "WEIGHTS_0": weight_accessor,
                        },
                        "material": 0,
                        "mode": 4,
                    }
                ]
            }
        ],
        "materials": [
            {
                "name": "vertex colour",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 1.0,
                },
            }
        ],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(_pad(bytes(binary), b"\0"))}],
    }
    del count
    text = _pad(json.dumps(document, separators=(",", ":"), sort_keys=True).encode("ascii"), b" ")
    data = _pad(bytes(binary), b"\0")
    total = 12 + 8 + len(text) + 8 + len(data)
    container = b"".join(
        (
            struct.pack("<III", 0x46546C67, 2, total),
            struct.pack("<II", len(text), 0x4E4F534A),
            text,
            struct.pack("<II", len(data), 0x004E4942),
            data,
        )
    )
    read_skinned_glb(
        container,
        bones={bone: f"bone:{bone}" for bone in bones},
        plan_parents=dict(parents),
    )
    return container
