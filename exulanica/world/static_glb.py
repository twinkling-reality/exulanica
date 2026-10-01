"""A workspace's static glTF binary: what may be admitted, and how it is prepared for placement.

This is the one content profile a person may admit to their own workspace today
(:mod:`exulanica.world.workspace_assets`): a self-contained glTF 2.0 binary with one scene of
triangles, embedded PNG or JPEG textures, and nothing that moves, deforms or reaches outside the
file. It is not the operator's importer (:mod:`exulanica.world.asset_import`), whose container
check it reuses unchanged as a second wall, and it never makes a global catalog row.

Every step says what kind of step it is, and the preparation receipt repeats the word:

- **validate** decides and changes nothing. :func:`inspect_static_glb` is the whole admission
  check. It reads the JSON chunk and the image headers only, so an upload route can run it before
  a row or a byte is written, and every limit is checked before the loop it bounds.
- **measure** reads facts from the content (exact bounds from the vertex data, counts, decoded
  image sizes) and changes nothing.
- **transform** changes bytes. Exactly one step does: :func:`prepare_static_glb` rewrites the JSON
  chunk so the object stands on its origin in metres (one new root node carrying the declared
  unit's scale and the translation that puts the bottom centre of its bounds at the origin), the
  position bounds are exact, and no ``extras`` survive. The binary chunk is copied byte for byte.

**The bounds are declared, not measured capacity.** The byte and JSON ceilings are the browser's
container boundary (``validate_import_container`` states the same ones). The counts bound the work
this module and a renderer do; instancing is counted, so one mesh drawn by a thousand nodes costs
a thousand draws here as it would there. Renderer frame cost at these bounds is not measured by
anything in this module.

**No I/O.** No database, store or network. Decoding a texture is the caller's
(``decode_image``), because the one place pixels are decoded is :mod:`exulanica.corpus.decode`
and a validator that imported a decoder would be a second one.

**Deterministic.** The output is a pure function of the input bytes, the declared unit and this
module's version: sorted keys, no whitespace, IEEE-754 doubles written by Python's shortest
round-trip representation, and the binary chunk untouched. A change that can move an output byte
is a new :data:`PREPARER_VERSION`, and tests hold golden digests to that rule.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import struct
import sys
from array import array
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from types import MappingProxyType
from typing import Any, Final

from exulanica.canonical import ceil_div, round_half_down
from exulanica.world.asset_import import MAX_ASSET_BYTES, validate_import_container

__all__ = [
    "CONTENT_REASONS",
    "GENERATOR",
    "LIMITS",
    "MAX_JSON_BYTES",
    "MEDIA_TYPE",
    "PLACEABLE_OBJECT_PROFILE",
    "PREPARER_ID",
    "PREPARER_VERSION",
    "PROFILE",
    "UNITS",
    "Compatibility",
    "InspectedGlb",
    "PreparedGlb",
    "StaticGlbLimits",
    "StaticGlbRefused",
    "inspect_static_glb",
    "prepare_static_glb",
]

#: The content profile this module admits.
PROFILE: Final = "exulanica.static-glb/v1"
#: The preparer a preparation row pins. A change that can move an output byte is a new version.
PREPARER_ID: Final = "exulanica.static-glb-preparer"
PREPARER_VERSION: Final = 1
#: What a prepared container's ``asset.generator`` states. The original is kept in the receipt.
GENERATOR: Final = f"{PREPARER_ID}/{PREPARER_VERSION}"
MEDIA_TYPE: Final = "model/gltf-binary"
#: The one use profile a prepared static asset is checked against today.
PLACEABLE_OBJECT_PROFILE: Final = "exulanica.placeable-object/v1"

#: The browser's JSON chunk ceiling, the same number ``validate_import_container`` states.
MAX_JSON_BYTES: Final = 4 * 1024 * 1024

#: Metres per declared unit, exactly. glTF states metres; files authored in other units say so.
UNITS: Final[Mapping[str, Fraction]] = MappingProxyType(
    {"millimetre": Fraction(1, 1000), "centimetre": Fraction(1, 100), "metre": Fraction(1)}
)

#: Every content reason a refusal or a failed preparation can name. Stable: added, never renamed.
CONTENT_REASONS: Final = frozenset(
    {
        "malformed_container",
        "compressed_content",
        "required_extension",
        "extension_not_admitted",
        "external_reference",
        "not_static",
        "unsupported_feature",
        "resource_limit_exceeded",
        "invalid_image",
        "invalid_geometry",
        "dimensions_disagree",
    }
)

#: Geometry or texture codecs a container may name; each needs a decoder the product does not ship.
_CODECS: Final = frozenset(
    {
        "KHR_draco_mesh_compression",
        "EXT_meshopt_compression",
        "KHR_mesh_quantization",
        "KHR_texture_basisu",
        "EXT_texture_webp",
        "EXT_texture_avif",
    }
)

_GLTF_MAGIC: Final = 0x46546C67
_CHUNK_JSON: Final = 0x4E4F534A
_CHUNK_BIN: Final = 0x004E4942

_FLOAT: Final = 5126
#: componentType -> (struct code, bytes per component).
_COMPONENTS: Final[Mapping[int, tuple[str, int]]] = MappingProxyType(
    {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
)
_WIDTHS: Final[Mapping[str, int]] = MappingProxyType({"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4})

#: The vertex attributes a static primitive may carry, and the accessor formats each may take, as
#: glTF 2.0 section 3.7.2.1 states them. ``(type, componentType, normalized)``.
_ATTRIBUTE_FORMATS: Final[Mapping[str, frozenset[tuple[str, int, bool]]]] = MappingProxyType(
    {
        "POSITION": frozenset({("VEC3", _FLOAT, False)}),
        "NORMAL": frozenset({("VEC3", _FLOAT, False)}),
        "TANGENT": frozenset({("VEC4", _FLOAT, False)}),
        "TEXCOORD_0": frozenset(
            {("VEC2", _FLOAT, False), ("VEC2", 5121, True), ("VEC2", 5123, True)}
        ),
        "TEXCOORD_1": frozenset(
            {("VEC2", _FLOAT, False), ("VEC2", 5121, True), ("VEC2", 5123, True)}
        ),
        "COLOR_0": frozenset(
            {
                (kind, component, normalized)
                for kind in ("VEC3", "VEC4")
                for component, normalized in ((_FLOAT, False), (5121, True), (5123, True))
            }
        ),
    }
)
_INDEX_FORMATS: Final = frozenset(
    {("SCALAR", 5121, False), ("SCALAR", 5123, False), ("SCALAR", 5125, False)}
)
_TRIANGLES: Final = 4

_TOP_LEVEL: Final = frozenset(
    {
        "accessors",
        "animations",
        "asset",
        "bufferViews",
        "buffers",
        "cameras",
        "extensions",
        "extensionsRequired",
        "extensionsUsed",
        "extras",
        "images",
        "materials",
        "meshes",
        "nodes",
        "samplers",
        "scene",
        "scenes",
        "skins",
        "textures",
    }
)
#: The properties each object may state. ``name`` and ``extras`` are allowed everywhere and
#: ``extensions`` nowhere (refused before this is read).
_PROPERTIES: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "asset": frozenset({"copyright", "generator", "minVersion", "version"}),
        "scene": frozenset({"nodes"}),
        "node": frozenset({"children", "matrix", "mesh", "rotation", "scale", "translation"}),
        "mesh": frozenset({"primitives"}),
        "primitive": frozenset({"attributes", "indices", "material", "mode"}),
        "accessor": frozenset(
            {
                "bufferView",
                "byteOffset",
                "componentType",
                "count",
                "max",
                "min",
                "normalized",
                "type",
            }
        ),
        "bufferView": frozenset({"buffer", "byteLength", "byteOffset", "byteStride", "target"}),
        "buffer": frozenset({"byteLength"}),
        "image": frozenset({"bufferView", "mimeType"}),
        "texture": frozenset({"sampler", "source"}),
        "sampler": frozenset({"magFilter", "minFilter", "wrapS", "wrapT"}),
        "material": frozenset(
            {
                "alphaCutoff",
                "alphaMode",
                "doubleSided",
                "emissiveFactor",
                "emissiveTexture",
                "normalTexture",
                "occlusionTexture",
                "pbrMetallicRoughness",
            }
        ),
        "pbrMetallicRoughness": frozenset(
            {
                "baseColorFactor",
                "baseColorTexture",
                "metallicFactor",
                "metallicRoughnessTexture",
                "roughnessFactor",
            }
        ),
        "textureInfo": frozenset({"index", "texCoord"}),
        "normalTextureInfo": frozenset({"index", "scale", "texCoord"}),
        "occlusionTextureInfo": frozenset({"index", "strength", "texCoord"}),
    }
)
#: ``extensions`` is here only because a non-empty one is refused before any object is read, so
#: what remains is ``{}``, which normalization removes with ``extras``.
_UNIVERSAL: Final = frozenset({"extensions", "extras", "name"})
#: What a property a static object cannot hold means, so the refusal names the right reason.
_NOT_STATIC: Final = frozenset({"skin", "weights", "targets"})
_MAG_FILTERS: Final = frozenset({9728, 9729})
_MIN_FILTERS: Final = frozenset({9728, 9729, 9984, 9985, 9986, 9987})
_WRAPS: Final = frozenset({33071, 33648, 10497})
_IMAGE_MEDIA: Final = MappingProxyType(
    {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8"}
)
#: JPEG start-of-frame markers that carry the frame size (every SOFn but DHT, JPG and DAC).
_JPEG_FRAMES: Final = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)
#: A quaternion may be off unit length by this much, as the Khronos validator's tolerance.
_UNIT_QUATERNION: Final = 1e-3
#: How far a prepared container's bottom centre may be from the origin, in metres.
_CENTRE_TOLERANCE_M: Final = 0.001


class StaticGlbRefused(ValueError):
    """A container this profile does not admit or cannot prepare. ``reason`` is the stable code."""

    def __init__(self, reason: str, message: str) -> None:
        if reason not in CONTENT_REASONS:
            raise ValueError(f"{reason!r} is not a content reason")
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class StaticGlbLimits:
    """What one admitted container may hold. Declared bounds; see the module docstring."""

    nodes: int = 1024
    meshes: int = 256
    primitives: int = 1024
    accessors: int = 4096
    buffer_views: int = 4096
    materials: int = 64
    textures: int = 64
    images: int = 32
    samplers: int = 32
    #: Primitive instances the scene draws, counting every node that draws a mesh.
    draw_calls: int = 512
    #: Vertices and triangles the scene draws, counting instancing.
    rendered_vertices: int = 1 << 20
    rendered_triangles: int = 1 << 20
    texture_side_px: int = 4096
    #: Texels over every image: 64 MiB of RGBA8 before mipmaps.
    texels: int = 1 << 24
    scene_depth: int = 32
    #: The largest prepared extent a placeable object may have, and the smallest largest extent.
    placeable_max_extent_mm: int = 50_000
    placeable_min_extent_mm: int = 10


LIMITS: Final = StaticGlbLimits()


@dataclass(frozen=True, slots=True)
class ImageHeader:
    index: int
    media_type: str
    width_px: int
    height_px: int
    offset: int
    length: int

    def document(self) -> dict[str, Any]:
        return {
            "image": self.index,
            "media_type": self.media_type,
            "width_px": self.width_px,
            "height_px": self.height_px,
        }


@dataclass(frozen=True, slots=True)
class _Instance:
    """One node that draws a mesh, with its world matrix (column-major, as glTF writes it)."""

    node: int
    mesh: int
    matrix: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class InspectedGlb:
    """A container that passed every admission check, and what was read to decide it."""

    document: Mapping[str, Any]
    json_chunk: bytes
    bin_chunk: bytes
    images: tuple[ImageHeader, ...]
    instances: tuple[_Instance, ...]
    roots: tuple[int, ...]
    counts: Mapping[str, int]
    accessors: tuple[_Accessor, ...]
    meshes: tuple[tuple[_Primitive, ...], ...]

    def facts(self) -> dict[str, Any]:
        return {"counts": dict(self.counts), "images": [image.document() for image in self.images]}


@dataclass(frozen=True, slots=True)
class Compatibility:
    profile: str
    state: str
    code: str | None

    def document(self) -> dict[str, Any]:
        return {"profile": self.profile, "state": self.state, "code": self.code}


@dataclass(frozen=True, slots=True)
class PreparedGlb:
    """The prepared container, its digest, and every fact the receipt states about making it."""

    output: bytes
    output_sha256: str
    steps: tuple[Mapping[str, Any], ...]
    dimensions_mm: Mapping[str, int]
    footprint_half_extents_mm: tuple[int, int]
    compatibility: tuple[Compatibility, ...]

    @property
    def placeable(self) -> bool:
        return any(
            item.profile == PLACEABLE_OBJECT_PROFILE and item.state == "compatible"
            for item in self.compatibility
        )


# -- the container -------------------------------------------------------------------------------


def _refuse(reason: str, message: str) -> StaticGlbRefused:
    return StaticGlbRefused(reason, message)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _refuse("malformed_container", f"the JSON chunk states {key!r} twice")
        result[key] = value
    return result


def _no_constant(name: str) -> Any:
    raise _refuse("malformed_container", f"the JSON chunk holds {name}, which JSON does not")


def _chunks(payload: bytes) -> tuple[bytes, bytes | None]:
    """The JSON chunk and the binary chunk (or None), exactly as stored."""
    if len(payload) > MAX_ASSET_BYTES:
        raise _refuse("resource_limit_exceeded", f"a container is at most {MAX_ASSET_BYTES} bytes")
    if len(payload) < 20 or len(payload) % 4:
        raise _refuse("malformed_container", "a container is at least 20 bytes in whole words")
    if struct.unpack_from("<III", payload) != (_GLTF_MAGIC, 2, len(payload)):
        raise _refuse("malformed_container", "not a glTF 2.0 binary of its stated length")
    chunks: list[tuple[int, bytes]] = []
    offset = 12
    while offset < len(payload):
        if len(chunks) == 2:
            raise _refuse("malformed_container", "a container holds at most a JSON and a BIN chunk")
        if offset + 8 > len(payload):
            raise _refuse("malformed_container", "a chunk header is cut short")
        length, kind = struct.unpack_from("<II", payload, offset)
        offset += 8
        if length % 4 or offset + length > len(payload):
            raise _refuse("malformed_container", "a chunk's length is not inside the container")
        chunks.append((kind, payload[offset : offset + length]))
        offset += length
    if not chunks or chunks[0][0] != _CHUNK_JSON:
        raise _refuse("malformed_container", "the first chunk must be JSON")
    if len(chunks) == 2 and chunks[1][0] != _CHUNK_BIN:
        raise _refuse("malformed_container", "the second chunk must be BIN")
    if not 0 < len(chunks[0][1]) <= MAX_JSON_BYTES:
        raise _refuse("resource_limit_exceeded", f"the JSON chunk is over {MAX_JSON_BYTES} bytes")
    return chunks[0][1], chunks[1][1] if len(chunks) == 2 else None


def _document(json_chunk: bytes) -> dict[str, Any]:
    try:
        text = json_chunk.decode("utf-8")
        document = json.loads(text, object_pairs_hook=_unique_keys, parse_constant=_no_constant)
    except StaticGlbRefused:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise _refuse("malformed_container", f"the JSON chunk does not parse: {error}") from None
    if not isinstance(document, dict):
        raise _refuse("malformed_container", "the JSON chunk is not an object")
    return document


def _walk(value: Any, path: str) -> Iterator[tuple[str, str, Any]]:
    """Every ``(path, key, value)`` in the document outside ``extras``, which nothing reads."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "extras":
                continue
            yield path, key, item
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")


def _declared_extensions(document: Mapping[str, Any]) -> None:
    required = document.get("extensionsRequired", [])
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise _refuse("malformed_container", "extensionsRequired is a list of names")
    used = document.get("extensionsUsed", [])
    if not isinstance(used, list) or any(not isinstance(item, str) for item in used):
        raise _refuse("malformed_container", "extensionsUsed is a list of names")
    codecs = sorted(_CODECS.intersection(required) | _CODECS.intersection(used))
    if codecs:
        raise _refuse(
            "compressed_content",
            f"{', '.join(codecs)} needs a decoder this profile does not admit",
        )
    if required:
        raise _refuse("required_extension", f"the container requires {', '.join(sorted(required))}")
    if used:
        raise _refuse(
            "extension_not_admitted",
            f"this profile admits no glTF extension, and the container uses "
            f"{', '.join(sorted(used))}",
        )
    for path, key, value in _walk(document, "$"):
        if key == "uri":
            raise _refuse(
                "external_reference",
                f"{path}.uri names something outside the container; every resource is embedded",
            )
        if key == "extensions" and value not in ({}, None):
            raise _refuse("extension_not_admitted", f"{path} states an extension")


# -- typed reads ---------------------------------------------------------------------------------


def _int(value: Any, where: str, *, low: int = 0, high: int | None = None) -> int:
    if type(value) is not int or value < low or (high is not None and value > high):
        bound = f"{low} or more" if high is None else f"{low} to {high}"
        raise _refuse("malformed_container", f"{where} is an integer {bound}")
    return value


def _number(value: Any, where: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise _refuse("malformed_container", f"{where} is a finite number")
    return float(value)


def _numbers(value: Any, where: str, count: int) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != count:
        raise _refuse("malformed_container", f"{where} is {count} numbers")
    return tuple(_number(item, f"{where}[{index}]") for index, item in enumerate(value))


def _unit_interval(value: Any, where: str) -> None:
    number = _number(value, where)
    if not 0 <= number <= 1:
        raise _refuse("malformed_container", f"{where} is between 0 and 1")


def _objects(document: Mapping[str, Any], name: str, limit: int) -> list[dict[str, Any]]:
    value = document.get(name, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise _refuse("malformed_container", f"{name} is a list of objects")
    if len(value) > limit:
        raise _refuse(
            "resource_limit_exceeded", f"{len(value)} {name} is over this profile's {limit}"
        )
    return value


def _properties(item: Mapping[str, Any], kind: str, where: str) -> None:
    for key in item:
        if key in _UNIVERSAL or key in _PROPERTIES[kind]:
            continue
        if key in _NOT_STATIC:
            raise _refuse("not_static", f"{where}.{key} makes the object move or deform")
        if key == "camera":
            raise _refuse("unsupported_feature", f"{where} carries a camera")
        if key == "sparse":
            raise _refuse("unsupported_feature", f"{where} is a sparse accessor")
        raise _refuse("unsupported_feature", f"{where}.{key} is not a property this profile reads")
    name = item.get("name")
    if name is not None and not isinstance(name, str):
        raise _refuse("malformed_container", f"{where}.name is text")


def _index(value: Any, where: str, count: int) -> int:
    if type(value) is not int or not 0 <= value < count:
        raise _refuse("malformed_container", f"{where} names no entry of its list")
    return value


# -- the checks ----------------------------------------------------------------------------------


def _check_asset(document: Mapping[str, Any]) -> None:
    asset = document.get("asset")
    if not isinstance(asset, dict):
        raise _refuse("malformed_container", "the container states no asset")
    _properties(asset, "asset", "asset")
    if asset.get("version") != "2.0":
        raise _refuse("malformed_container", "asset.version must be 2.0")
    for key in ("copyright", "generator", "minVersion"):
        if key in asset and not isinstance(asset[key], str):
            raise _refuse("malformed_container", f"asset.{key} is text")
    if "minVersion" in asset and asset["minVersion"] != "2.0":
        raise _refuse("unsupported_feature", "asset.minVersion names a version after 2.0")


def _check_buffers(
    document: Mapping[str, Any], bin_chunk: bytes | None, limits: StaticGlbLimits
) -> tuple[list[dict[str, Any]], int]:
    buffers = _objects(document, "buffers", 1)
    if buffers and bin_chunk is None:
        raise _refuse("malformed_container", "a buffer is declared and the container has no BIN")
    buffer_length = 0
    for number, buffer in enumerate(buffers):
        _properties(buffer, "buffer", f"buffers[{number}]")
        buffer_length = _int(
            buffer.get("byteLength"),
            f"buffers[{number}].byteLength",
            low=1,
            high=len(bin_chunk or b""),
        )
    views = _objects(document, "bufferViews", limits.buffer_views)
    for number, view in enumerate(views):
        where = f"bufferViews[{number}]"
        _properties(view, "bufferView", where)
        _index(view.get("buffer"), f"{where}.buffer", len(buffers))
        offset = _int(view.get("byteOffset", 0), f"{where}.byteOffset")
        length = _int(view.get("byteLength"), f"{where}.byteLength", low=1)
        if offset + length > buffer_length:
            raise _refuse("malformed_container", f"{where} runs past its buffer")
        if "byteStride" in view:
            stride = _int(view["byteStride"], f"{where}.byteStride", low=4, high=252)
            if stride % 4:
                raise _refuse("malformed_container", f"{where}.byteStride is a multiple of 4")
        if "target" in view and view["target"] not in (34962, 34963):
            raise _refuse("malformed_container", f"{where}.target is a buffer target")
    return views, buffer_length


@dataclass(frozen=True, slots=True)
class _Accessor:
    index: int
    kind: str
    component: int
    normalized: bool
    count: int
    offset: int
    stride: int
    element: int

    @property
    def format(self) -> tuple[str, int, bool]:
        return (self.kind, self.component, self.normalized)


def _check_accessors(
    document: Mapping[str, Any], views: list[dict[str, Any]], limits: StaticGlbLimits
) -> list[_Accessor]:
    accessors = _objects(document, "accessors", limits.accessors)
    checked: list[_Accessor] = []
    for number, accessor in enumerate(accessors):
        where = f"accessors[{number}]"
        _properties(accessor, "accessor", where)
        if "bufferView" not in accessor:
            raise _refuse("unsupported_feature", f"{where} has no buffer view")
        view = views[_index(accessor["bufferView"], f"{where}.bufferView", len(views))]
        component = accessor.get("componentType")
        if component not in _COMPONENTS or type(component) is not int:
            raise _refuse("malformed_container", f"{where}.componentType is a glTF component type")
        kind = accessor.get("type")
        if kind not in _WIDTHS:
            raise _refuse("unsupported_feature", f"{where}.type {kind!r} is not a vector or scalar")
        normalized = accessor.get("normalized", False)
        if type(normalized) is not bool:
            raise _refuse("malformed_container", f"{where}.normalized is true or false")
        if normalized and component in (5125, _FLOAT):
            raise _refuse("malformed_container", f"{where} normalizes a type that cannot be")
        count = _int(accessor.get("count"), f"{where}.count", low=1)
        size = _COMPONENTS[component][1]
        element = size * _WIDTHS[kind]
        offset = _int(accessor.get("byteOffset", 0), f"{where}.byteOffset")
        base = view.get("byteOffset", 0) + offset
        if base % size:
            raise _refuse("malformed_container", f"{where} is not aligned to its component size")
        stride = view.get("byteStride", element)
        if stride < element:
            raise _refuse("malformed_container", f"{where} is wider than its view's stride")
        if offset + stride * (count - 1) + element > view["byteLength"]:
            raise _refuse("malformed_container", f"{where} runs past its buffer view")
        for bound in ("min", "max"):
            if bound in accessor:
                _numbers(accessor[bound], f"{where}.{bound}", _WIDTHS[kind])
        checked.append(_Accessor(number, kind, component, normalized, count, base, stride, element))
    return checked


def _check_images(
    document: Mapping[str, Any],
    views: list[dict[str, Any]],
    bin_chunk: bytes | None,
    limits: StaticGlbLimits,
) -> tuple[ImageHeader, ...]:
    images = _objects(document, "images", limits.images)
    headers: list[ImageHeader] = []
    texels = 0
    for number, image in enumerate(images):
        where = f"images[{number}]"
        _properties(image, "image", where)
        if "bufferView" not in image:
            raise _refuse("malformed_container", f"{where} names no embedded buffer view")
        view = views[_index(image["bufferView"], f"{where}.bufferView", len(views))]
        if "byteStride" in view:
            raise _refuse("malformed_container", f"{where}'s buffer view has a stride")
        media_type = image.get("mimeType")
        if media_type not in _IMAGE_MEDIA:
            raise _refuse("unsupported_feature", f"{where}.mimeType is image/png or image/jpeg")
        start = view.get("byteOffset", 0)
        data = (bin_chunk or b"")[start : start + view["byteLength"]]
        width, height = _image_size(data, media_type, where)
        if max(width, height) > limits.texture_side_px:
            raise _refuse(
                "resource_limit_exceeded",
                f"{where} is {width} by {height}; a side is at most {limits.texture_side_px} px",
            )
        texels += width * height
        if texels > limits.texels:
            raise _refuse(
                "resource_limit_exceeded",
                f"the images hold more than {limits.texels} texels",
            )
        headers.append(ImageHeader(number, media_type, width, height, start, view["byteLength"]))
    return tuple(headers)


def _image_size(data: bytes, media_type: str, where: str) -> tuple[int, int]:
    """Width and height from the header alone. No pixel is decoded here."""
    if not data.startswith(_IMAGE_MEDIA[media_type]):
        raise _refuse("invalid_image", f"{where} is not the {media_type} it says it is")
    if media_type == "image/png":
        if len(data) < 33 or data[12:16] != b"IHDR" or struct.unpack(">I", data[8:12])[0] != 13:
            raise _refuse("invalid_image", f"{where} has no PNG header")
        width, height = struct.unpack(">II", data[16:24])
    else:
        width, height = _jpeg_size(data, where)
    if width < 1 or height < 1:
        raise _refuse("invalid_image", f"{where} states an empty frame")
    return width, height


def _jpeg_size(data: bytes, where: str) -> tuple[int, int]:
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            raise _refuse("invalid_image", f"{where} has a broken JPEG marker")
        marker = data[offset + 1]
        if marker == 0xFF:
            offset += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        if marker in (0xD9, 0xDA):
            break
        length = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
        if length < 2 or offset + 2 + length > len(data):
            raise _refuse("invalid_image", f"{where} has a JPEG segment past its end")
        if marker in _JPEG_FRAMES:
            if length < 7:
                raise _refuse("invalid_image", f"{where} has a short JPEG frame header")
            height, width = struct.unpack(">HH", data[offset + 5 : offset + 9])
            return width, height
        offset += 2 + length
    raise _refuse("invalid_image", f"{where} states no JPEG frame size")


def _texture_info(value: Any, where: str, kind: str, textures: int) -> None:
    if not isinstance(value, dict):
        raise _refuse("malformed_container", f"{where} is an object")
    _properties(value, kind, where)
    _index(value.get("index"), f"{where}.index", textures)
    if "texCoord" in value:
        _int(value["texCoord"], f"{where}.texCoord", high=1)
    if "scale" in value:
        _number(value["scale"], f"{where}.scale")
    if "strength" in value:
        _unit_interval(value["strength"], f"{where}.strength")


def _check_materials(
    document: Mapping[str, Any], images: int, limits: StaticGlbLimits
) -> tuple[int, int]:
    samplers = _objects(document, "samplers", limits.samplers)
    for number, sampler in enumerate(samplers):
        where = f"samplers[{number}]"
        _properties(sampler, "sampler", where)
        for key, allowed in (
            ("magFilter", _MAG_FILTERS),
            ("minFilter", _MIN_FILTERS),
            ("wrapS", _WRAPS),
            ("wrapT", _WRAPS),
        ):
            if key in sampler and (type(sampler[key]) is not int or sampler[key] not in allowed):
                raise _refuse("malformed_container", f"{where}.{key} is not a glTF sampler value")
    textures = _objects(document, "textures", limits.textures)
    for number, texture in enumerate(textures):
        where = f"textures[{number}]"
        _properties(texture, "texture", where)
        if "source" not in texture:
            raise _refuse("unsupported_feature", f"{where} names no image")
        _index(texture["source"], f"{where}.source", images)
        if "sampler" in texture:
            _index(texture["sampler"], f"{where}.sampler", len(samplers))
    materials = _objects(document, "materials", limits.materials)
    for number, material in enumerate(materials):
        where = f"materials[{number}]"
        _properties(material, "material", where)
        pbr = material.get("pbrMetallicRoughness")
        if pbr is not None:
            if not isinstance(pbr, dict):
                raise _refuse("malformed_container", f"{where}.pbrMetallicRoughness is an object")
            _properties(pbr, "pbrMetallicRoughness", f"{where}.pbrMetallicRoughness")
            if "baseColorFactor" in pbr:
                for index, value in enumerate(
                    _numbers(pbr["baseColorFactor"], f"{where}.baseColorFactor", 4)
                ):
                    _unit_interval(value, f"{where}.baseColorFactor[{index}]")
            for key in ("metallicFactor", "roughnessFactor"):
                if key in pbr:
                    _unit_interval(pbr[key], f"{where}.{key}")
            for key in ("baseColorTexture", "metallicRoughnessTexture"):
                if key in pbr:
                    _texture_info(pbr[key], f"{where}.{key}", "textureInfo", len(textures))
        for key, kind in (
            ("normalTexture", "normalTextureInfo"),
            ("occlusionTexture", "occlusionTextureInfo"),
            ("emissiveTexture", "textureInfo"),
        ):
            if key in material:
                _texture_info(material[key], f"{where}.{key}", kind, len(textures))
        if "emissiveFactor" in material:
            for index, value in enumerate(
                _numbers(material["emissiveFactor"], f"{where}.emissiveFactor", 3)
            ):
                _unit_interval(value, f"{where}.emissiveFactor[{index}]")
        if material.get("alphaMode", "OPAQUE") not in ("OPAQUE", "MASK", "BLEND"):
            raise _refuse("malformed_container", f"{where}.alphaMode is OPAQUE, MASK or BLEND")
        if (
            "alphaCutoff" in material
            and _number(material["alphaCutoff"], f"{where}.alphaCutoff") < 0
        ):
            raise _refuse("malformed_container", f"{where}.alphaCutoff is not negative")
        if "doubleSided" in material and type(material["doubleSided"]) is not bool:
            raise _refuse("malformed_container", f"{where}.doubleSided is true or false")
    return len(textures), len(materials)


@dataclass(frozen=True, slots=True)
class _Primitive:
    position: int
    attributes: Mapping[str, int]
    indices: int | None
    vertices: int
    triangles: int


def _check_meshes(
    document: Mapping[str, Any],
    accessors: list[_Accessor],
    materials: int,
    limits: StaticGlbLimits,
) -> list[list[_Primitive]]:
    meshes = _objects(document, "meshes", limits.meshes)
    checked: list[list[_Primitive]] = []
    total = 0
    for number, mesh in enumerate(meshes):
        where = f"meshes[{number}]"
        _properties(mesh, "mesh", where)
        primitives = mesh.get("primitives")
        if not isinstance(primitives, list) or not primitives:
            raise _refuse("malformed_container", f"{where}.primitives is a non-empty list")
        total += len(primitives)
        if total > limits.primitives:
            raise _refuse(
                "resource_limit_exceeded",
                f"the meshes hold more than this profile's {limits.primitives} primitives",
            )
        mesh_primitives: list[_Primitive] = []
        for index, primitive in enumerate(primitives):
            mesh_primitives.append(
                _check_primitive(primitive, f"{where}.primitives[{index}]", accessors, materials)
            )
        checked.append(mesh_primitives)
    return checked


def _check_primitive(
    primitive: Any, where: str, accessors: list[_Accessor], materials: int
) -> _Primitive:
    if not isinstance(primitive, dict):
        raise _refuse("malformed_container", f"{where} is an object")
    _properties(primitive, "primitive", where)
    if primitive.get("mode", _TRIANGLES) != _TRIANGLES:
        raise _refuse("unsupported_feature", f"{where} draws something other than triangles")
    if "material" in primitive:
        _index(primitive["material"], f"{where}.material", materials)
    attributes = primitive.get("attributes")
    if not isinstance(attributes, dict) or "POSITION" not in attributes:
        raise _refuse("malformed_container", f"{where} states no POSITION attribute")
    counts: set[int] = set()
    resolved: dict[str, int] = {}
    for semantic, value in attributes.items():
        if semantic.startswith(("JOINTS_", "WEIGHTS_")):
            raise _refuse("not_static", f"{where} is skinned by {semantic}")
        formats = _ATTRIBUTE_FORMATS.get(semantic)
        if formats is None:
            raise _refuse("unsupported_feature", f"{where}.attributes.{semantic} is not read")
        accessor = accessors[_index(value, f"{where}.attributes.{semantic}", len(accessors))]
        if accessor.format not in formats:
            raise _refuse(
                "malformed_container", f"{where}.attributes.{semantic} has the wrong format"
            )
        counts.add(accessor.count)
        resolved[semantic] = accessor.index
    if len(counts) != 1:
        raise _refuse("malformed_container", f"{where}'s attributes differ in count")
    vertices = counts.pop()
    indices: int | None = None
    if "indices" in primitive:
        accessor = accessors[_index(primitive["indices"], f"{where}.indices", len(accessors))]
        if accessor.format not in _INDEX_FORMATS:
            raise _refuse("malformed_container", f"{where}.indices has the wrong format")
        if accessor.stride != accessor.element:
            raise _refuse("malformed_container", f"{where}.indices are strided")
        if accessor.count % 3:
            raise _refuse("invalid_geometry", f"{where}.indices is not whole triangles")
        indices = accessor.index
        triangles = accessor.count // 3
    else:
        if vertices % 3:
            raise _refuse("invalid_geometry", f"{where} is not whole triangles")
        triangles = vertices // 3
    return _Primitive(
        resolved["POSITION"], MappingProxyType(resolved), indices, vertices, triangles
    )


def _check_nodes(
    document: Mapping[str, Any], meshes: int, limits: StaticGlbLimits
) -> list[dict[str, Any]]:
    nodes = _objects(document, "nodes", limits.nodes)
    for number, node in enumerate(nodes):
        where = f"nodes[{number}]"
        _properties(node, "node", where)
        if "mesh" in node:
            _index(node["mesh"], f"{where}.mesh", meshes)
        children = node.get("children", [])
        if not isinstance(children, list):
            raise _refuse("malformed_container", f"{where}.children is a list")
        for index, child in enumerate(children):
            _index(child, f"{where}.children[{index}]", len(nodes))
        if len(set(children)) != len(children):
            raise _refuse("malformed_container", f"{where} names a child twice")
        if "matrix" in node:
            if {"rotation", "scale", "translation"} & node.keys():
                raise _refuse("malformed_container", f"{where} states a matrix and TRS both")
            matrix = _numbers(node["matrix"], f"{where}.matrix", 16)
            if (matrix[3], matrix[7], matrix[11], matrix[15]) != (0.0, 0.0, 0.0, 1.0):
                raise _refuse("malformed_container", f"{where}.matrix is not an affine transform")
        if "rotation" in node:
            rotation = _numbers(node["rotation"], f"{where}.rotation", 4)
            if abs(math.sqrt(sum(value * value for value in rotation)) - 1) > _UNIT_QUATERNION:
                raise _refuse("malformed_container", f"{where}.rotation is not a unit quaternion")
        for key in ("scale", "translation"):
            if key in node:
                _numbers(node[key], f"{where}.{key}", 3)
    return nodes


def _roots(document: Mapping[str, Any], nodes: list[dict[str, Any]]) -> tuple[int, ...]:
    scenes = _objects(document, "scenes", 1 << 16)
    if len(scenes) > 1:
        raise _refuse("unsupported_feature", f"the container holds {len(scenes)} scenes, not one")
    if not scenes:
        raise _refuse("invalid_geometry", "the container states no scene to draw")
    if "scene" in document:
        _index(document["scene"], "scene", len(scenes))
    scene = scenes[0]
    _properties(scene, "scene", "scenes[0]")
    roots = scene.get("nodes")
    if not isinstance(roots, list) or not roots:
        raise _refuse("invalid_geometry", "the scene names no node")
    for index, root in enumerate(roots):
        _index(root, f"scenes[0].nodes[{index}]", len(nodes))
    if len(set(roots)) != len(roots):
        raise _refuse("malformed_container", "the scene names a node twice")
    return tuple(roots)


def _check_graph(
    nodes: list[dict[str, Any]], roots: tuple[int, ...], limits: StaticGlbLimits
) -> None:
    parent: dict[int, int] = {}
    for number, node in enumerate(nodes):
        for child in node.get("children", []):
            if child in parent:
                raise _refuse("malformed_container", f"nodes[{child}] has two parents")
            if child == number:
                raise _refuse("malformed_container", f"nodes[{number}] is its own child")
            parent[child] = number
    for root in roots:
        if root in parent:
            raise _refuse("malformed_container", f"scene root nodes[{root}] has a parent")
    for number in range(len(nodes)):
        seen = {number}
        cursor = number
        depth = 1
        while cursor in parent:
            cursor = parent[cursor]
            depth += 1
            if cursor in seen:
                raise _refuse("malformed_container", "the node hierarchy has a cycle")
            seen.add(cursor)
            if depth > limits.scene_depth:
                raise _refuse(
                    "resource_limit_exceeded",
                    f"the node hierarchy is deeper than this profile's {limits.scene_depth}",
                )


# -- matrices ------------------------------------------------------------------------------------

_IDENTITY: Final = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def _multiply(a: Sequence[float], b: Sequence[float]) -> tuple[float, ...]:
    """``a @ b`` for column-major 4x4 matrices."""
    return tuple(
        sum(a[k * 4 + row] * b[column * 4 + k] for k in range(4))
        for column in range(4)
        for row in range(4)
    )


def _local(node: Mapping[str, Any]) -> tuple[float, ...]:
    if "matrix" in node:
        return tuple(float(value) for value in node["matrix"])
    tx, ty, tz = (float(value) for value in node.get("translation", (0, 0, 0)))
    qx, qy, qz, qw = (float(value) for value in node.get("rotation", (0, 0, 0, 1)))
    sx, sy, sz = (float(value) for value in node.get("scale", (1, 1, 1)))
    rotation = (
        1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy + qz * qw), 2 * (qx * qz - qy * qw),
        2 * (qx * qy - qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz + qx * qw),
        2 * (qx * qz + qy * qw), 2 * (qy * qz - qx * qw), 1 - 2 * (qx * qx + qy * qy),
    )  # fmt: skip
    return (
        rotation[0] * sx, rotation[1] * sx, rotation[2] * sx, 0.0,
        rotation[3] * sy, rotation[4] * sy, rotation[5] * sy, 0.0,
        rotation[6] * sz, rotation[7] * sz, rotation[8] * sz, 0.0,
        tx, ty, tz, 1.0,
    )  # fmt: skip


def _axis_aligned(matrix: Sequence[float]) -> bool:
    """Whether the linear part maps each axis onto one axis, so a box maps exactly onto a box."""
    for column in range(3):
        if sum(1 for row in range(3) if matrix[column * 4 + row] != 0.0) > 1:
            return False
    return True


def _point(matrix: Sequence[float], x: float, y: float, z: float) -> tuple[float, float, float]:
    return (
        matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
        matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
        matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14],
    )


def _instances(
    nodes: list[dict[str, Any]],
    roots: tuple[int, ...],
    meshes: list[list[_Primitive]],
    limits: StaticGlbLimits,
) -> tuple[tuple[_Instance, ...], dict[str, int]]:
    instances: list[_Instance] = []
    draws = vertices = triangles = 0
    stack: list[tuple[int, tuple[float, ...]]] = [(root, _IDENTITY) for root in reversed(roots)]
    while stack:
        number, parent = stack.pop()
        node = nodes[number]
        world = _multiply(parent, _local(node))
        if "mesh" in node:
            instances.append(_Instance(number, node["mesh"], world))
            for primitive in meshes[node["mesh"]]:
                draws += 1
                vertices += primitive.vertices
                triangles += primitive.triangles
            for name, value, limit in (
                ("draw calls", draws, limits.draw_calls),
                ("vertices", vertices, limits.rendered_vertices),
                ("triangles", triangles, limits.rendered_triangles),
            ):
                if value > limit:
                    raise _refuse(
                        "resource_limit_exceeded",
                        f"the scene draws more than this profile's {limit} {name}",
                    )
        stack.extend((child, world) for child in reversed(node.get("children", [])))
    if not triangles:
        raise _refuse("invalid_geometry", "the scene draws no triangle")
    return tuple(instances), {
        "draw_calls": draws,
        "rendered_vertices": vertices,
        "rendered_triangles": triangles,
    }


# -- admission -----------------------------------------------------------------------------------


def inspect_static_glb(payload: bytes, limits: StaticGlbLimits = LIMITS) -> InspectedGlb:
    """Every admission check, reading the JSON chunk and image headers only. Changes nothing.

    Raises :class:`StaticGlbRefused` with the first reason found. The order is fixed so one
    container always answers the same reason: the container, then what it declares it needs
    (extensions and references), then the operator importer's container check as a second wall,
    then the static profile, then the bounds.
    """
    json_chunk, bin_chunk = _chunks(payload)
    document = _document(json_chunk)
    _declared_extensions(document)
    try:
        validate_import_container(payload)
    except ValueError as error:
        raise _refuse("malformed_container", str(error)) from None
    unknown = sorted(set(document) - _TOP_LEVEL)
    if unknown:
        raise _refuse("unsupported_feature", f"the container states {', '.join(unknown)}")
    for name in ("animations", "skins"):
        if document.get(name):
            raise _refuse("not_static", f"the container holds {name}")
    if document.get("cameras"):
        raise _refuse("unsupported_feature", "the container holds cameras")
    _check_asset(document)
    views, _ = _check_buffers(document, bin_chunk, limits)
    accessors = _check_accessors(document, views, limits)
    images = _check_images(document, views, bin_chunk, limits)
    textures, materials = _check_materials(document, len(images), limits)
    meshes = _check_meshes(document, accessors, materials, limits)
    nodes = _check_nodes(document, len(meshes), limits)
    roots = _roots(document, nodes)
    _check_graph(nodes, roots, limits)
    instances, drawn = _instances(nodes, roots, meshes, limits)
    counts = {
        "nodes": len(nodes),
        "meshes": len(meshes),
        "primitives": sum(len(mesh) for mesh in meshes),
        "accessors": len(accessors),
        "images": len(images),
        "textures": textures,
        "materials": materials,
        "texels": sum(image.width_px * image.height_px for image in images),
        **drawn,
    }
    return InspectedGlb(
        document=document,
        json_chunk=json_chunk,
        bin_chunk=bin_chunk or b"",
        images=images,
        instances=instances,
        roots=roots,
        counts=MappingProxyType(counts),
        accessors=tuple(accessors),
        meshes=tuple(tuple(mesh) for mesh in meshes),
    )


# -- preparation ---------------------------------------------------------------------------------


def _values(bin_chunk: bytes, accessor: _Accessor) -> array[Any]:
    """Every component of an accessor, in order, as one typed array."""
    code, _ = _COMPONENTS[accessor.component]
    width = _WIDTHS[accessor.kind]
    if accessor.stride == accessor.element:
        end = accessor.offset + accessor.element * accessor.count
        values = array(code, bin_chunk[accessor.offset : end])
    else:
        values = array(code)
        for number in range(accessor.count):
            start = accessor.offset + number * accessor.stride
            values.frombytes(bin_chunk[start : start + accessor.element])
    if len(values) != width * accessor.count:
        raise _refuse("malformed_container", f"accessors[{accessor.index}] is cut short")
    if sys.byteorder == "big":
        values.byteswap()
    return values


def _position_box(
    values: array[Any], index: int
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    lows = [math.inf, math.inf, math.inf]
    highs = [-math.inf, -math.inf, -math.inf]
    for axis in range(3):
        column = values[axis::3]
        for value in column:
            if not math.isfinite(value):
                raise _refuse("invalid_geometry", f"accessors[{index}] holds a non-finite position")
        lows[axis] = min(column)
        highs[axis] = max(column)
    return (lows[0], lows[1], lows[2]), (highs[0], highs[1], highs[2])


def _scan(
    inspected: InspectedGlb,
    accessors: Sequence[_Accessor],
    meshes: Sequence[Sequence[_Primitive]],
) -> dict[int, tuple[tuple[float, float, float], tuple[float, float, float]]]:
    """P2: every value the scene draws is finite and every index names a vertex. Returns boxes."""
    boxes: dict[int, tuple[tuple[float, float, float], tuple[float, float, float]]] = {}
    checked: set[int] = set()
    used = {instance.mesh for instance in inspected.instances}
    for mesh in sorted(used):
        for primitive in meshes[mesh]:
            for semantic, index in sorted(primitive.attributes.items()):
                if index in checked:
                    continue
                accessor = accessors[index]
                values = _values(inspected.bin_chunk, accessor)
                if semantic == "POSITION":
                    boxes[index] = _position_box(values, index)
                elif accessor.component == _FLOAT:
                    for value in values:
                        if not math.isfinite(value):
                            raise _refuse(
                                "invalid_geometry", f"accessors[{index}] holds a non-finite value"
                            )
                checked.add(index)
            if primitive.indices is not None:
                values = _values(inspected.bin_chunk, accessors[primitive.indices])
                if max(values) >= primitive.vertices:
                    raise _refuse(
                        "invalid_geometry",
                        f"accessors[{primitive.indices}] names a vertex past {primitive.vertices}",
                    )
    return boxes


def _world_box(
    inspected: InspectedGlb,
    accessors: Sequence[_Accessor],
    meshes: Sequence[Sequence[_Primitive]],
    boxes: Mapping[int, tuple[tuple[float, float, float], tuple[float, float, float]]],
    root: Sequence[float] = _IDENTITY,
) -> tuple[list[float], list[float]]:
    """P4: the scene's axis-aligned bounds, exact: boxes where a transform keeps them boxes,
    every vertex where it turns them."""
    lows = [math.inf, math.inf, math.inf]
    highs = [-math.inf, -math.inf, -math.inf]

    def include(point: tuple[float, float, float]) -> None:
        for axis in range(3):
            lows[axis] = min(lows[axis], point[axis])
            highs[axis] = max(highs[axis], point[axis])

    positions: dict[int, array[Any]] = {}
    for instance in inspected.instances:
        matrix = _multiply(root, instance.matrix)
        for primitive in meshes[instance.mesh]:
            low, high = boxes[primitive.position]
            if _axis_aligned(matrix):
                for x in (low[0], high[0]):
                    for y in (low[1], high[1]):
                        for z in (low[2], high[2]):
                            include(_point(matrix, x, y, z))
            else:
                values = positions.get(primitive.position)
                if values is None:
                    values = _values(inspected.bin_chunk, accessors[primitive.position])
                    positions[primitive.position] = values
                for offset in range(0, len(values), 3):
                    include(_point(matrix, values[offset], values[offset + 1], values[offset + 2]))
    return lows, highs


def _mm(metres: float) -> int:
    fraction = Fraction(metres) * 1000
    return round_half_down(fraction.numerator, fraction.denominator)


def _um(metres: float) -> int:
    fraction = Fraction(metres) * 1_000_000
    return round_half_down(fraction.numerator, fraction.denominator)


def _strip_extras(value: Any) -> int:
    """Remove every ``extras`` and every empty ``extensions``; count the ``extras`` removed."""
    removed = 0
    if isinstance(value, dict):
        if "extras" in value:
            del value["extras"]
            removed += 1
        if value.get("extensions") == {}:
            del value["extensions"]
        for item in value.values():
            removed += _strip_extras(item)
    elif isinstance(value, list):
        for item in value:
            removed += _strip_extras(item)
    return removed


def _pad(data: bytes, filler: bytes) -> bytes:
    remainder = len(data) % 4
    return data if remainder == 0 else data + filler * (4 - remainder)


def _container_bytes(document: Mapping[str, Any], bin_chunk: bytes) -> bytes:
    json_chunk = _pad(
        json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8"),
        b" ",
    )
    parts = [struct.pack("<II", len(json_chunk), _CHUNK_JSON), json_chunk]
    if bin_chunk:
        parts.extend((struct.pack("<II", len(bin_chunk), _CHUNK_BIN), bin_chunk))
    body = b"".join(parts)
    return struct.pack("<III", _GLTF_MAGIC, 2, 12 + len(body)) + body


def _dimensions_agree(measured: int, declared: int) -> bool:
    """Within max(2 mm, 5 %) of what the person declared, in integers."""
    return 100 * abs(measured - declared) <= max(200, 5 * declared)


def prepare_static_glb(
    payload: bytes,
    *,
    unit: str,
    expected_dimensions_mm: Mapping[str, int] | None,
    decode_image: Callable[[bytes], tuple[int, int]],
    limits: StaticGlbLimits = LIMITS,
) -> PreparedGlb:
    """Validate, measure and normalize one admitted container. Deterministic; no I/O.

    ``decode_image`` decodes one embedded image and returns its decoded size, raising on bytes it
    cannot read; the preparation worker passes :mod:`exulanica.corpus.decode`. Raises
    :class:`StaticGlbRefused` with the reason the preparation fails with.
    """
    if unit not in UNITS:
        raise ValueError(f"{unit!r} is not a declared unit")
    inspected = inspect_static_glb(payload, limits)
    document = inspected.document
    accessors, meshes = inspected.accessors, inspected.meshes
    steps: list[Mapping[str, Any]] = [
        {"step": "container", "kind": "validate", "profile": PROFILE, **inspected.facts()}
    ]

    boxes = _scan(inspected, accessors, meshes)
    steps.append(
        {
            "step": "data",
            "kind": "validate",
            "position_accessors": len(boxes),
            "rendered_vertices": inspected.counts["rendered_vertices"],
            "rendered_triangles": inspected.counts["rendered_triangles"],
        }
    )

    decoded = []
    for image in inspected.images:
        data = inspected.bin_chunk[image.offset : image.offset + image.length]
        try:
            size = decode_image(data)
        except Exception as error:  # the decoder's refusal, whatever its class
            raise _refuse(
                "invalid_image", f"images[{image.index}] does not decode: {type(error).__name__}"
            ) from None
        if tuple(size) != (image.width_px, image.height_px):
            raise _refuse(
                "invalid_image",
                f"images[{image.index}] decodes to {size[0]} by {size[1]}, not its header's "
                f"{image.width_px} by {image.height_px}",
            )
        decoded.append(image.document())
    steps.append({"step": "images", "kind": "validate", "decoded": decoded})

    lows, highs = _world_box(inspected, accessors, meshes, boxes)
    scale = UNITS[unit]
    extents = [float(Fraction(highs[axis] - lows[axis]) * scale) for axis in range(3)]
    dimensions = {"width": _mm(extents[0]), "height": _mm(extents[1]), "depth": _mm(extents[2])}
    if expected_dimensions_mm is not None:
        for name in ("width", "height", "depth"):
            if not _dimensions_agree(dimensions[name], int(expected_dimensions_mm[name])):
                raise _refuse(
                    "dimensions_disagree",
                    f"the {name} measures {dimensions[name]} mm in {unit}s and was declared "
                    f"{expected_dimensions_mm[name]} mm",
                )
    largest = max(dimensions.values())
    compatible = limits.placeable_min_extent_mm <= largest <= limits.placeable_max_extent_mm
    compatibility = (
        Compatibility(
            PLACEABLE_OBJECT_PROFILE,
            "compatible" if compatible else "incompatible",
            None if compatible else "dimensions_out_of_bounds",
        ),
    )
    # Half extents round up, so the obstacle a society reads is never smaller than the object.
    footprint = (ceil_div(dimensions["width"], 2), ceil_div(dimensions["depth"], 2))
    steps.append(
        {
            "step": "measure",
            "kind": "measure",
            "unit": unit,
            "bounds_um": {
                "min": [_um(float(Fraction(value) * scale)) for value in lows],
                "max": [_um(float(Fraction(value) * scale)) for value in highs],
            },
            "dimensions_mm": dimensions,
            "footprint_half_extents_mm": list(footprint),
            "compatibility": [item.document() for item in compatibility],
        }
    )

    output_document = copy.deepcopy(dict(document))
    extras = _strip_extras(output_document)
    original = document["asset"].get("generator")
    output_document["asset"] = {
        **{
            key: document["asset"][key]
            for key in ("copyright", "minVersion")
            if key in document["asset"]
        },
        "generator": GENERATOR,
        "version": "2.0",
    }
    rewritten = 0
    for index, (low, high) in sorted(boxes.items()):
        accessor = output_document["accessors"][index]
        exact_min, exact_max = [float(value) for value in low], [float(value) for value in high]
        if accessor.get("min") != exact_min or accessor.get("max") != exact_max:
            rewritten += 1
        accessor["min"], accessor["max"] = exact_min, exact_max
    factor = float(scale)
    translation = [
        -(factor * ((lows[0] + highs[0]) / 2)),
        -(factor * lows[1]),
        -(factor * ((lows[2] + highs[2]) / 2)),
    ]
    translation = [0.0 if value == 0 else value for value in translation]
    nodes = output_document.setdefault("nodes", [])
    nodes.append(
        {
            "children": list(inspected.roots),
            "name": "prepared-root",
            "scale": [factor, factor, factor],
            "translation": translation,
        }
    )
    scene = dict(output_document["scenes"][0])
    scene["nodes"] = [len(nodes) - 1]
    output_document["scenes"] = [scene]
    output_document["scene"] = 0
    output = _container_bytes(output_document, inspected.bin_chunk)
    steps.append(
        {
            "step": "normalize",
            "kind": "transform",
            "scale": repr(factor),
            "translation_m": [repr(value) for value in translation],
            "extras_removed": extras,
            "position_bounds_rewritten": rewritten,
            "generator_replaced": original,
            "binary_chunk": "copied",
        }
    )

    _verify_output(output, dimensions, limits)
    steps.append({"step": "output", "kind": "validate", "byte_size": len(output)})
    return PreparedGlb(
        output=output,
        output_sha256=hashlib.sha256(output).hexdigest(),
        steps=tuple(steps),
        dimensions_mm=MappingProxyType(dimensions),
        footprint_half_extents_mm=footprint,
        compatibility=compatibility,
    )


def _verify_output(output: bytes, dimensions: Mapping[str, int], limits: StaticGlbLimits) -> None:
    """P6: the output passes admission again and stands centred on its origin in metres.

    The one node normalization adds, and the one level it adds above every root, are allowed for.
    """
    widened = replace(limits, nodes=limits.nodes + 1, scene_depth=limits.scene_depth + 1)
    try:
        again = inspect_static_glb(output, widened)
    except StaticGlbRefused as error:
        raise _refuse(error.reason, f"the prepared container fails admission: {error}") from None
    boxes = _scan(again, again.accessors, again.meshes)
    lows, highs = _world_box(again, again.accessors, again.meshes, boxes)
    centre = ((lows[0] + highs[0]) / 2, lows[1], (lows[2] + highs[2]) / 2)
    if any(abs(value) > _CENTRE_TOLERANCE_M for value in centre):
        raise _refuse("invalid_geometry", "the prepared container does not stand on its origin")
    measured = {
        "width": _mm(highs[0] - lows[0]),
        "height": _mm(highs[1] - lows[1]),
        "depth": _mm(highs[2] - lows[2]),
    }
    if any(abs(measured[name] - dimensions[name]) > 1 for name in dimensions):
        raise _refuse("invalid_geometry", "the prepared container does not keep its dimensions")
