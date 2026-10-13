"""Static glTF containers written from parts: the looks this repository authors, byte for byte.

A look this repository authors (a blocky figure, a primitive sword, a lantern, a well, a gate) is
written here from parts: boxes and upright cylinders in whole millimetres, each one flat colour
and an optional glow, under named nodes. The container is an ``exulanica.static-glb/v1`` one
(:mod:`exulanica.world.static_glb`): one scene, triangle meshes with positions and normals,
materials with colour factors or optional embedded PNG maps, no skin, morph target or animation.
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

from exulanica.things.material_maps import IMAGES_MAX, TEXELS_MAX, MaterialMaps, PngMap

__all__ = ["GENERATOR", "MeshPart", "Node", "Part", "write_container"]

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
class MeshPart:
    """Triangles in one flat colour, their corners in whole millimetres from their node, each
    triangle drawn flat with its own normal: an oriented shape no box or upright cylinder makes (a
    limb's tapered prism, a wing's membrane, which ``double_sided`` draws from both sides)."""

    name: str
    vertices_mm: tuple[tuple[int, int, int], ...]
    triangles: tuple[tuple[int, int, int], ...]
    colour: str
    double_sided: bool = False
    glow: str | None = None
    #: Optional unit normals in the same slot frame, one per corner. Absent keeps flat output.
    normals: tuple[tuple[float, float, float], ...] | None = None
    roughness_permille: int = 800
    metallic_permille: int = 0
    #: Normalized atlas coordinates, one per declared corner; no implicit unwrap or UV flip.
    uvs: tuple[tuple[float, float], ...] | None = None
    #: Slot-frame tangent XYZ and handedness W, one per declared corner.
    tangents: tuple[tuple[float, float, float, float], ...] | None = None
    maps: MaterialMaps | None = None

    def __post_init__(self) -> None:
        if any(len(v) != 3 or any(type(c) is not int for c in v) for v in self.vertices_mm):
            raise ValueError(f"part {self.name}: corners in whole millimetres")
        count = len(self.vertices_mm)
        if not self.triangles or any(
            len(t) != 3
            or len(set(t)) != 3
            or any(type(i) is not int or not 0 <= i < count for i in t)
            for t in self.triangles
        ):
            raise ValueError(f"part {self.name}: triangles of three distinct corners")
        for colour in (self.colour, self.glow):
            if colour is not None and _COLOUR.fullmatch(colour) is None:
                raise ValueError(f"part {self.name}: colours are #rrggbb in lowercase")
        if self.normals is not None and (
            len(self.normals) != count
            or any(
                len(n) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in n)
                or not 0.999 <= math.hypot(*n) <= 1.001
                for n in self.normals
            )
        ):
            raise ValueError(f"part {self.name}: one finite unit normal per corner")
        for value in (self.roughness_permille, self.metallic_permille):
            if type(value) is not int or not 0 <= value <= 1000:
                raise ValueError(f"part {self.name}: material factors in whole thousandths")
        if self.uvs is not None and (
            len(self.uvs) != count
            or any(
                len(uv) != 2
                or any(
                    type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
                    for v in uv
                )
                for uv in self.uvs
            )
        ):
            raise ValueError(f"part {self.name}: one finite normalized UV per corner")
        if self.maps is not None and (not isinstance(self.maps, MaterialMaps) or self.uvs is None):
            raise ValueError(f"part {self.name}: material maps need validated maps and UVs")
        if self.tangents is not None:
            if self.normals is None or self.uvs is None or len(self.tangents) != count:
                raise ValueError(
                    f"part {self.name}: tangent frames need normals and UVs per corner"
                )
            for tangent, normal in zip(self.tangents, self.normals, strict=True):
                if (
                    len(tangent) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in tangent)
                    or not 0.999 <= math.hypot(*tangent[:3]) <= 1.001
                    or tangent[3] not in (-1, 1)
                    or abs(sum(tangent[k] * normal[k] for k in range(3))) > 0.001
                ):
                    raise ValueError(
                        f"part {self.name}: finite unit tangent orthogonal to normal, W +/-1"
                    )
        if self.maps is not None and self.maps.normal is not None:
            if self.tangents is None:
                raise ValueError(f"part {self.name}: normal map needs explicit tangent frames")
            assert self.uvs is not None
            for a, b, c in self.triangles:
                ua, ub, uc = (
                    tuple(struct.unpack("<f", struct.pack("<f", v))[0] for v in self.uvs[i])
                    for i in (a, b, c)
                )
                area = (ub[0] - ua[0]) * (uc[1] - ua[1]) - (ub[1] - ua[1]) * (uc[0] - ua[0])
                if abs(area) <= 1e-12:
                    raise ValueError(
                        f"part {self.name}: normal map needs nondegenerate triangle UVs"
                    )


@dataclass(frozen=True, slots=True)
class Node:
    """A named node at ``at_mm`` in the slot frame, holding its parts."""

    name: str
    at_mm: tuple[int, int, int]
    parts: tuple[Part | MeshPart, ...] = ()


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


def _mesh(part: MeshPart) -> tuple[list[tuple[float, ...]], list[tuple[float, ...]], list[int]]:
    """Each triangle on its own three corners with its own normal: the cross product of two of its
    integer edges, divided by its length, so a flat face is lit as one face on any machine."""
    positions: list[tuple[float, ...]] = []
    normals: list[tuple[float, ...]] = []
    indices: list[int] = []
    for a, b, c in part.triangles:
        pa, pb, pc = part.vertices_mm[a], part.vertices_mm[b], part.vertices_mm[c]
        u = (pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2])
        v = (pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2])
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        length = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
        if length == 0:
            raise ValueError(f"part {part.name}: a triangle with no area")
        normal = _gltf(n[0] / length, n[1] / length, n[2] / length)
        for corner in (pa, pb, pc):
            indices.append(len(positions))
            positions.append(_gltf(*(_metres(value) for value in corner)))
            normals.append(normal)
    if part.normals is not None:
        return (
            [_gltf(*(_metres(value) for value in corner)) for corner in part.vertices_mm],
            [_gltf(*normal) for normal in part.normals],
            [index for triangle in part.triangles for index in triangle],
        )
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
    material_of: dict[tuple, int] = {}
    images: list[dict] = []
    textures: list[dict] = []
    image_of: dict[bytes, int] = {}
    texels = 0
    gltf_nodes: list[dict] = []
    roots: list[int] = []

    def view(data: bytes, target: int | None) -> int:
        while len(binary) % 4:
            binary.append(0)
        entry = {"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)}
        if target is not None:
            entry["target"] = target
        views.append(entry)
        binary.extend(data)
        return len(views) - 1

    def map_texture(image: PngMap) -> int:
        nonlocal texels
        if image.data not in image_of:
            if len(images) >= IMAGES_MAX:
                raise ValueError("material maps exceed static-glb image budget")
            texels += image.size_px[0] * image.size_px[1]
            if texels > TEXELS_MAX:
                raise ValueError("material maps exceed static-glb texel budget")
            index = len(images)
            images.append({"bufferView": view(image.data, None), "mimeType": "image/png"})
            textures.append({"source": index, "sampler": 0})
            image_of[image.data] = index
        return image_of[image.data]

    for node in nodes:
        children = []
        for part in node.parts:
            if isinstance(part, MeshPart):
                positions, normals, indices = _mesh(part)
                double_sided = part.double_sided
            else:
                positions, normals, indices = (_box if part.shape == "box" else _cylinder)(part)
                double_sided = False
            if len(positions) > 0xFFFF:
                raise ValueError(f"part {part.name} has too many corners")
            roughness = part.roughness_permille if isinstance(part, MeshPart) else 800
            metallic = part.metallic_permille if isinstance(part, MeshPart) else 0
            maps = part.maps if isinstance(part, MeshPart) else None
            key = (part.colour, part.glow, double_sided, roughness, metallic, maps)
            if key not in material_of:
                name = f"{part.colour}{'' if part.glow is None else '+' + part.glow}"
                material = {
                    "name": f"{name} both sides" if double_sided else name,
                    "pbrMetallicRoughness": {
                        "baseColorFactor": [*_colour(part.colour), 1.0],
                        "metallicFactor": metallic / 1000,
                        "roughnessFactor": roughness / 1000,
                    },
                }
                if part.glow is not None:
                    material["emissiveFactor"] = _colour(part.glow)
                if double_sided:
                    material["doubleSided"] = True
                if maps is not None:
                    for image, owner, field in (
                        (maps.base_colour, material["pbrMetallicRoughness"], "baseColorTexture"),
                        (
                            maps.metallic_roughness,
                            material["pbrMetallicRoughness"],
                            "metallicRoughnessTexture",
                        ),
                        (maps.normal, material, "normalTexture"),
                    ):
                        if image is not None:
                            owner[field] = {"index": map_texture(image), "texCoord": 0}
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
            attributes = {"POSITION": first, "NORMAL": first + 1}
            if isinstance(part, MeshPart) and part.uvs is not None:
                # Flat faces duplicate their declared corners; smooth faces retain indexing.
                corners = (
                    range(len(part.vertices_mm))
                    if part.normals is not None
                    else [i for triangle in part.triangles for i in triangle]
                )
                uvs = [part.uvs[i] for i in corners]
                flat_uvs = [v for uv in uvs for v in uv]
                uv_view = view(struct.pack(f"<{len(flat_uvs)}f", *flat_uvs), _ARRAY_BUFFER)
                attributes["TEXCOORD_0"] = len(accessors)
                accessors.append(
                    {
                        "bufferView": uv_view,
                        "componentType": _FLOAT,
                        "count": len(uvs),
                        "type": "VEC2",
                    }
                )
                if part.tangents is not None:
                    tangents = [(*_gltf(*t[:3]), t[3]) for t in part.tangents]
                    flat_tangents = [v for t in tangents for v in t]
                    tangent_view = view(
                        struct.pack(f"<{len(flat_tangents)}f", *flat_tangents), _ARRAY_BUFFER
                    )
                    attributes["TANGENT"] = len(accessors)
                    accessors.append(
                        {
                            "bufferView": tangent_view,
                            "componentType": _FLOAT,
                            "count": len(tangents),
                            "type": "VEC4",
                        }
                    )
            meshes.append(
                {
                    "name": part.name,
                    "primitives": [
                        {
                            "attributes": attributes,
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
    if images:
        document.update(
            images=images,
            textures=textures,
            samplers=[{"wrapS": 33071, "wrapT": 33071, "magFilter": 9729, "minFilter": 9987}],
        )
    text = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("ascii")
    text += b" " * (-len(text) % 4)
    total = 12 + 8 + len(text) + 8 + len(binary)
    if images and total > 32 * 1024 * 1024:
        raise ValueError("textured look exceeds the existing 32 MiB container budget")
    return b"".join(
        (
            struct.pack("<III", _MAGIC, 2, total),
            struct.pack("<II", len(text), _CHUNK_JSON),
            text,
            struct.pack("<II", len(binary), _CHUNK_BIN),
            bytes(binary),
        )
    )
