"""The static glTF binary profile's words, bounds and shapes.

What the profile is called and who prepares it, the units a container may declare, the refusals by
name (:data:`CONTENT_REASONS`, :class:`StaticGlbRefused`) and every bound an admission holds a
container to (:class:`StaticGlbLimits`), the glTF tables the checks read (chunk magic, component
widths, accessor formats, the properties a static file may carry, filters, image media), and the
shapes an inspection and a preparation return. :mod:`exulanica.world.static_glb_checks` checks a
container against them and :mod:`exulanica.world.static_glb` admits and prepares it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType
from typing import Any, Final

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


@dataclass(frozen=True, slots=True)
class _Primitive:
    position: int
    attributes: Mapping[str, int]
    indices: int | None
    vertices: int
    triangles: int
