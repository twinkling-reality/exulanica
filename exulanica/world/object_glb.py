"""A catalog kind's triangles and texture sets, packed as one self-contained glTF 2.0 binary.

:mod:`exulanica.world.object_meshes` makes a kind's triangles from its recipe, and this module
packs them with the texture sets its catalog entry names (:mod:`exulanica.world.object_catalog`)
into the container a person's world draws. The renderer already draws a container's own glTF
materials and embedded images as declared (``web/packages/atlas-react/src/playcanvas/
scene-objects.ts`` gives its matte fallback only to a container with no material), so a textured
object needs no route and no renderer change: everything it looks like travels inside its bytes.

**Byte for byte reproducible, because a migration pins the digest.** The JSON chunk is sorted with
no whitespace; every float is a binary32 value packed by ``struct``; every image is a PNG written
here with stored (uncompressed) deflate blocks, so no zlib build can change a byte (zlib's own
block layout at level 0 has changed between releases; its CRC-32 and Adler-32 are checksums, fixed
by their definitions); vertices are kept in first-seen order; and the one float computation that is
not a plain conversion, rebuilding a normal's ``z``, is IEEE-754 arithmetic Python performs the same
way on every platform.

**One primitive per texture set.** The triangles of every part a set dresses are one primitive with
one material, so a kind drawn in three sets is three draws and each set's maps are embedded once.

**What a material states is the set's own maps, read the way the tile renderer reads them**
(``generated-tile/texture-materials.ts``): the base colour is sRGB; a two-component normal map
gets its ``z`` rebuilt as ``normalTexels`` rebuilds it, ``z = sqrt(max(0, 1 - x * x - y * y))``
rounded half up; and the ORM map is glTF's own packing, occlusion in red, roughness in green and
metalness in blue, so one image is both the occlusion and the metallic-roughness texture. A cutout
set is glTF's ``alphaMode: MASK`` at the set's declared cutoff, drawn from both sides. The set's
declared extent is the UV scale: ``u = s / extent_u_mm`` and ``v = t / extent_v_mm``, with ``s``
and ``t`` the surface coordinates :mod:`exulanica.world.object_meshes` gives every vertex.

**Axes.** A part's frame has ``+x`` across the object, ``+y`` its front and ``+z`` up; glTF has
``+y`` up. A point ``(x, y, z)`` millimetres is ``(x, z, -y) / 1000`` metres here, a rotation, so a
triangle wound counter-clockwise seen from outside stays so, and the object's front faces glTF
``-z``, toward the person who placed it.

**Tangents** point where ``s`` increases, made perpendicular to the normal in exact integers before
they are normalised; ``w`` is the handedness glTF defines, ``bitangent = cross(normal, tangent) *
w``, chosen so the bitangent points toward row 0 of the maps, which is where the sets' normal
convention puts ``+Y`` (:data:`exulanica.materials.classes.NORMAL_CONVENTION`). On a side ``t``
runs down, so ``w`` is ``+1``; on a top or an underside ``w`` is ``-1``.

**Provenance travels in the bytes.** Each material's ``extras`` name the set it embeds by its pin
(id, version and content digest) and the texel size it was embedded at, and each image is named
``<set id>/<map>``.
"""

from __future__ import annotations

import functools
import json
import math
import struct
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.world.object_meshes import FormTriangle, FormVertex, SurfaceFrame
from exulanica.world.texture_assets import (
    PinnedTextureSet,
    decode_texture_set,
    load_texture_catalog,
)

__all__ = [
    "GENERATOR",
    "EmbeddedTextureSet",
    "embedded_texture_set",
    "stored_png",
    "textured_glb",
]

#: The generator a textured container states; a new writer that moves a byte is a new version.
GENERATOR: Final = "exulanica-world-object/1"

_GLTF_MAGIC: Final = 0x46546C67
_GLTF_VERSION: Final = 2
_CHUNK_JSON: Final = 0x4E4F534A
_CHUNK_BIN: Final = 0x004E4942
_COMPONENT_FLOAT: Final = 5126
_COMPONENT_UNSIGNED_SHORT: Final = 5123
_MODE_TRIANGLES: Final = 4
_TARGET_ARRAY_BUFFER: Final = 34962
_TARGET_ELEMENT_ARRAY_BUFFER: Final = 34963
#: glTF sampler enums: linear magnification, trilinear minification, repeat on both axes.
_LINEAR: Final = 9729
_LINEAR_MIPMAP_LINEAR: Final = 9987
_REPEAT: Final = 10497
#: The largest index an unsigned 16-bit index buffer holds.
_MAX_INDEX: Final = 0xFFFF
#: Millimetres in a metre, the unit glTF positions are in.
_MM_PER_METRE: Final = 1000

_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
#: A zlib stream header for deflate with a 32 KiB window, no dictionary, and a valid check.
_ZLIB_HEADER: Final = b"\x78\x01"
#: The most bytes one stored deflate block holds (RFC 1951, section 3.2.4).
_STORED_BLOCK: Final = 0xFFFF
#: PNG colour types (PNG specification, IHDR) for the two layouts embedded here.
_PNG_COLOUR_TYPE: Final[Mapping[int, int]] = {3: 2, 4: 6}
#: Each row's filter byte: filter type 0, the row as stored.
_PNG_NO_FILTER: Final = b"\x00"

#: ``w`` for each surface frame, derived in the module docstring and held by a test against the
#: triangles' own geometry.
_HANDEDNESS: Final[Mapping[SurfaceFrame, int]] = {"vertical": 1, "top": -1, "underside": -1}

Direction = tuple[int, int, int]


# -- images -------------------------------------------------------------------------------------


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _stored_zlib(raw: bytes) -> bytes:
    """``raw`` as a zlib stream of stored deflate blocks, the one layout this module writes."""
    blocks = [_ZLIB_HEADER]
    offsets = range(0, len(raw), _STORED_BLOCK) if raw else range(1)
    for offset in offsets:
        block = raw[offset : offset + _STORED_BLOCK]
        final = offset + _STORED_BLOCK >= len(raw)
        blocks.append(
            bytes((1 if final else 0,))
            + struct.pack("<HH", len(block), len(block) ^ 0xFFFF)
            + block
        )
    blocks.append(struct.pack(">I", zlib.adler32(raw) & 0xFFFFFFFF))
    return b"".join(blocks)


def stored_png(width: int, height: int, components: int, texels: bytes) -> bytes:
    """Eight-bit RGB or RGBA texels, row 0 first, as a PNG no compressor wrote."""
    colour_type = _PNG_COLOUR_TYPE.get(components)
    if colour_type is None:
        raise ValueError(f"a PNG here holds 3 or 4 components a texel, not {components}")
    row = width * components
    if len(texels) != row * height:
        raise ValueError(f"{len(texels)} bytes are not {width} by {height} texels of {components}")
    raw = b"".join(
        _PNG_NO_FILTER + texels[start : start + row] for start in range(0, row * height, row)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0)
    return b"".join(
        (
            _PNG_SIGNATURE,
            _png_chunk(b"IHDR", header),
            _png_chunk(b"IDAT", _stored_zlib(raw)),
            _png_chunk(b"IEND", b""),
        )
    )


def _box_filtered(texels: bytes, side: int, components: int, factor: int) -> bytes:
    """A square map averaged over ``factor`` by ``factor`` blocks, each mean rounded half up."""
    if factor == 1:
        return texels
    out_side = side // factor
    count = factor * factor
    out = bytearray(out_side * out_side * components)
    for out_row in range(out_side):
        for out_column in range(out_side):
            for component in range(components):
                total = 0
                for row in range(out_row * factor, out_row * factor + factor):
                    start = (row * side + out_column * factor) * components + component
                    total += sum(texels[start : start + factor * components : components])
                out[(out_row * out_side + out_column) * components + component] = (
                    total + count // 2
                ) // count
    return bytes(out)


@functools.cache
def _normal_z_table() -> bytes:
    """``z`` for every pair of stored ``x`` and ``y`` bytes, as ``normalTexels`` rebuilds it.

    ``Math.round`` there rounds half up, which is ``floor(value + 0.5)`` for these values (all at
    least 127.5, where adding a half is exact in binary64).
    """
    table = bytearray(256 * 256)
    for x in range(256):
        nx = (2 * x) / 255 - 1
        for y in range(256):
            ny = (2 * y) / 255 - 1
            nz = math.sqrt(max(0.0, 1 - nx * nx - ny * ny))
            table[(x << 8) | y] = math.floor(((nz + 1) / 2) * 255 + 0.5)
    return bytes(table)


def _normal_rgb(normal: bytes, components: int) -> bytes:
    """A normal map as RGB: three components as stored, or two with ``z`` rebuilt."""
    if components == 3:
        return normal
    if components != 2:
        raise ValueError(f"a normal map holds 2 or 3 components a texel, not {components}")
    xs, ys = normal[0::2], normal[1::2]
    table = _normal_z_table()
    out = bytearray(len(xs) * 3)
    out[0::3] = xs
    out[1::3] = ys
    out[2::3] = bytes(table[(x << 8) | y] for x, y in zip(xs, ys, strict=True))
    return bytes(out)


@dataclass(frozen=True, slots=True)
class EmbeddedTextureSet:
    """A published set's maps as the PNG images a container embeds, and what its material states."""

    set_id: str
    version: int
    content_sha256: str
    extent_u_mm: int
    extent_v_mm: int
    #: The side, in texels, the maps are embedded at.
    texels: int
    #: The byte a cutout set's coverage is tested against, or ``None`` for an opaque set.
    alpha_cutoff: int | None
    double_sided: bool
    base_color_png: bytes
    normal_png: bytes
    orm_png: bytes

    def pin(self) -> dict[str, Any]:
        return {
            "content_sha256": self.content_sha256,
            "set_id": self.set_id,
            "version": self.version,
        }


@functools.cache
def _published_sets() -> Mapping[str, PinnedTextureSet]:
    """The texture library, every set verified against its pin, loaded once per process."""
    return load_texture_catalog().sets


#: The material classes a container here embeds: glTF's opaque and ``MASK`` modes.
_EMBEDDED_CLASSES: Final = ("opaque", "cutout")


@functools.cache
def embedded_texture_set(set_id: str, texels: int) -> EmbeddedTextureSet:
    """A published set's maps at ``texels`` a side, read from its verified container.

    ``texels`` is the set's own side or that side divided by a power of two; a smaller size averages
    each block of texels. A set that is not square, is not opaque or cutout, or has no normal or
    ORM map is refused by name: a container here draws exactly those, and nothing is substituted.
    """
    pinned = _published_sets().get(set_id)
    if pinned is None:
        raise ValueError(f"{set_id} is not a published texture set")
    if pinned.material_class not in _EMBEDDED_CLASSES:
        raise ValueError(
            f"{set_id} is a {pinned.material_class} set; an object embeds {_EMBEDDED_CLASSES}"
        )
    side = pinned.width
    if pinned.height != side:
        raise ValueError(f"{set_id} is {pinned.width} by {pinned.height}; an object embeds squares")
    factor, remainder = divmod(side, texels) if texels > 0 else (0, 1)
    if remainder or factor < 1 or factor & (factor - 1):
        raise ValueError(f"{set_id} is {side} texels a side; {texels} is not it over a power of 2")
    decoded = decode_texture_set(pinned.read_bytes())
    layout = {texture_map.name: texture_map for texture_map in decoded.layout}
    cutout = pinned.material_class == "cutout"
    colour_name = "base_color_coverage" if cutout else "base_color"
    for name in (colour_name, "normal", "orm"):
        if name not in layout:
            raise ValueError(f"{set_id} holds no {name} map, which an embedded material draws")
    colour_components = layout[colour_name].components
    normal_components = layout["normal"].components

    def filtered(name: str, components: int) -> bytes:
        return _box_filtered(bytes(decoded.maps[name]), side, components, factor)

    # The normal is rebuilt at the stored resolution and then averaged, so a smaller map holds the
    # mean of the normals the set states, not a normal rebuilt from averaged components.
    normal_rgb = _box_filtered(
        _normal_rgb(bytes(decoded.maps["normal"]), normal_components), side, 3, factor
    )
    # A cutout header's class parameters were held to the class's own rule when it was decoded
    # (exulanica.materials.classes.class_parameters), so they are read here, never defaulted. Only
    # a v2 container states a class, and every cutout set is one.
    stated = decoded.header["class"] if cutout else {}
    return EmbeddedTextureSet(
        set_id=set_id,
        version=pinned.version,
        content_sha256=pinned.content_sha256,
        extent_u_mm=pinned.extent_u_mm,
        extent_v_mm=pinned.extent_v_mm,
        texels=texels,
        alpha_cutoff=stated["alpha_cutoff"] if cutout else None,
        double_sided=stated["double_sided"] is True if cutout else False,
        base_color_png=stored_png(
            texels, texels, colour_components, filtered(colour_name, colour_components)
        ),
        normal_png=stored_png(texels, texels, 3, normal_rgb),
        orm_png=stored_png(texels, texels, 3, filtered("orm", layout["orm"].components)),
    )


# -- vertices -----------------------------------------------------------------------------------


def _dot(a: Direction, b: Direction) -> int:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _perpendicular(tangent: Direction, normal: Direction) -> Direction:
    """``tangent`` less its part along ``normal``, scaled by ``|normal|^2`` to stay integral."""
    along, length = _dot(tangent, normal), _dot(normal, normal)
    return (
        tangent[0] * length - normal[0] * along,
        tangent[1] * length - normal[1] * along,
        tangent[2] * length - normal[2] * along,
    )


def _gltf(direction: Direction) -> Direction:
    """A part-frame direction in glTF's axes, negating in integers so no zero is negative."""
    return (direction[0], direction[2], -direction[1])


def _unit(direction: Direction) -> tuple[float, float, float]:
    length = math.sqrt(float(_dot(direction, direction)))
    if length == 0:
        raise ValueError("a direction of zero length cannot be normalised")
    return (direction[0] / length, direction[1] / length, direction[2] / length)


def _f32(value: float) -> float:
    """``value`` as the binary32 number the buffer holds, so a stated bound equals the data."""
    return float(struct.unpack("<f", struct.pack("<f", value))[0])


@dataclass(frozen=True, slots=True)
class _Vertex:
    position: tuple[float, float, float]
    normal: tuple[float, float, float]
    tangent: tuple[float, float, float, float]
    uv: tuple[float, float]


def _vertex(corner: FormVertex, frame: SurfaceFrame, extent: tuple[int, int]) -> _Vertex:
    position = _gltf((corner.x_mm, corner.y_mm, corner.z_mm))
    normal = _gltf(corner.normal)
    tangent = _gltf(_perpendicular(corner.tangent, corner.normal))
    return _Vertex(
        position=tuple(_f32(axis / _MM_PER_METRE) for axis in position),  # type: ignore[arg-type]
        normal=tuple(_f32(axis) for axis in _unit(normal)),  # type: ignore[arg-type]
        tangent=(*(_f32(axis) for axis in _unit(tangent)), float(_HANDEDNESS[frame])),  # type: ignore[arg-type]
        uv=(_f32(corner.s_mm / extent[0]), _f32(corner.t_mm / extent[1])),
    )


@dataclass(frozen=True, slots=True)
class _Primitive:
    embedded: EmbeddedTextureSet
    vertices: tuple[_Vertex, ...]
    indices: tuple[int, ...]


def _primitive(triangles: Sequence[FormTriangle], embedded: EmbeddedTextureSet) -> _Primitive:
    extent = (embedded.extent_u_mm, embedded.extent_v_mm)
    seen: dict[_Vertex, int] = {}
    indices: list[int] = []
    for triangle in triangles:
        for corner in triangle.vertices:
            vertex = _vertex(corner, triangle.frame, extent)
            index = seen.setdefault(vertex, len(seen))
            indices.append(index)
    if len(seen) > _MAX_INDEX + 1:
        raise ValueError(f"{len(seen)} vertices do not fit 16-bit indices")
    return _Primitive(embedded, tuple(seen), tuple(indices))


# -- the container ------------------------------------------------------------------------------


def _pad(data: bytes, filler: bytes) -> bytes:
    remainder = len(data) % 4
    return data if remainder == 0 else data + filler * (4 - remainder)


class _Buffer:
    """The BIN chunk under construction: views appended in order, each aligned to four bytes."""

    def __init__(self) -> None:
        self.parts: list[bytes] = []
        self.length = 0
        self.views: list[dict[str, Any]] = []

    def view(self, data: bytes, target: int | None) -> int:
        view: dict[str, Any] = {"buffer": 0, "byteLength": len(data), "byteOffset": self.length}
        if target is not None:
            view["target"] = target
        padded = _pad(data, b"\x00")
        self.parts.append(padded)
        self.length += len(padded)
        self.views.append(view)
        return len(self.views) - 1

    def bytes(self) -> bytes:
        return b"".join(self.parts)


def textured_glb(
    name: str, triangles: Sequence[FormTriangle], materials: Mapping[str, EmbeddedTextureSet]
) -> bytes:
    """Pack a kind's triangles, one primitive per set its roles name, into one GLB.

    ``materials`` maps each surface role a triangle takes to the embedded set that dresses it; a
    triangle whose role maps to nothing is refused, never drawn plain.
    """
    by_set: dict[str, list[FormTriangle]] = {}
    embedded_by_id: dict[str, EmbeddedTextureSet] = {}
    for triangle in triangles:
        embedded = materials.get(triangle.surface_role)
        if embedded is None:
            raise ValueError(f"{name}: no texture set dresses {triangle.surface_role}")
        by_set.setdefault(embedded.set_id, []).append(triangle)
        embedded_by_id[embedded.set_id] = embedded
    primitives = [_primitive(group, embedded_by_id[set_id]) for set_id, group in by_set.items()]

    buffer = _Buffer()
    accessors: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    textures: list[dict[str, Any]] = []
    gltf_materials: list[dict[str, Any]] = []
    gltf_primitives: list[dict[str, Any]] = []

    def accessor(values: Sequence[Sequence[float]], kind: str, bounds: bool) -> int:
        packed = b"".join(struct.pack(f"<{len(value)}f", *value) for value in values)
        entry: dict[str, Any] = {
            "bufferView": buffer.view(packed, _TARGET_ARRAY_BUFFER),
            "componentType": _COMPONENT_FLOAT,
            "count": len(values),
            "type": kind,
        }
        if bounds:
            width = len(values[0])
            entry["max"] = [max(value[axis] for value in values) for axis in range(width)]
            entry["min"] = [min(value[axis] for value in values) for axis in range(width)]
        accessors.append(entry)
        return len(accessors) - 1

    def texture(set_id: str, map_name: str, png: bytes) -> int:
        images.append(
            {
                "bufferView": buffer.view(png, None),
                "mimeType": "image/png",
                "name": f"{set_id}/{map_name}",
            }
        )
        textures.append({"sampler": 0, "source": len(images) - 1})
        return len(textures) - 1

    for primitive in primitives:
        vertices = primitive.vertices
        attributes = {
            "NORMAL": accessor([vertex.normal for vertex in vertices], "VEC3", False),
            "POSITION": accessor([vertex.position for vertex in vertices], "VEC3", True),
            "TANGENT": accessor([vertex.tangent for vertex in vertices], "VEC4", False),
            "TEXCOORD_0": accessor([vertex.uv for vertex in vertices], "VEC2", False),
        }
        index_bytes = b"".join(struct.pack("<H", index) for index in primitive.indices)
        accessors.append(
            {
                "bufferView": buffer.view(index_bytes, _TARGET_ELEMENT_ARRAY_BUFFER),
                "componentType": _COMPONENT_UNSIGNED_SHORT,
                "count": len(primitive.indices),
                "type": "SCALAR",
            }
        )
        indices = len(accessors) - 1
        embedded = primitive.embedded
        colour = texture(embedded.set_id, "base_color", embedded.base_color_png)
        normal = texture(embedded.set_id, "normal", embedded.normal_png)
        orm = texture(embedded.set_id, "orm", embedded.orm_png)
        material: dict[str, Any] = {
            "extras": {"texels": embedded.texels, "texture_set": embedded.pin()},
            "name": embedded.set_id,
            "normalTexture": {"index": normal},
            "occlusionTexture": {"index": orm},
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": colour},
                "metallicRoughnessTexture": {"index": orm},
            },
        }
        if embedded.alpha_cutoff is not None:
            material["alphaMode"] = "MASK"
            material["alphaCutoff"] = embedded.alpha_cutoff / 255
        if embedded.double_sided:
            material["doubleSided"] = True
        gltf_materials.append(material)
        gltf_primitives.append(
            {
                "attributes": attributes,
                "indices": indices,
                "material": len(gltf_materials) - 1,
                "mode": _MODE_TRIANGLES,
            }
        )

    binary = buffer.bytes()
    document = {
        "accessors": accessors,
        "asset": {"generator": GENERATOR, "version": "2.0"},
        "bufferViews": buffer.views,
        "buffers": [{"byteLength": len(binary)}],
        "images": images,
        "materials": gltf_materials,
        "meshes": [{"name": name, "primitives": gltf_primitives}],
        "nodes": [{"mesh": 0, "name": name}],
        "samplers": [
            {
                "magFilter": _LINEAR,
                "minFilter": _LINEAR_MIPMAP_LINEAR,
                "wrapS": _REPEAT,
                "wrapT": _REPEAT,
            }
        ],
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "textures": textures,
    }
    json_chunk = _pad(
        json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        ),
        b" ",
    )
    binary_chunk = _pad(binary, b"\x00")
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
