"""A style pack's pieces, checked on the server: the profile on arrival, the palette in the worker.

A piece is an ``exulanica.static-glb/v1`` container (:mod:`exulanica.world.static_glb`) that a pack
lists for a look role. A pack a person uploads is held to more than the container profile, in two
steps, so nothing a piece carries is hidden and nothing expensive runs in a request:

1. :func:`check_piece_profile`, in the request, reads the JSON chunk only. On top of
   :func:`~exulanica.world.static_glb.inspect_static_glb` (every structural check and bound), the
   canonical pack-piece profile: one buffer whose length is the binary chunk's less at most three
   zero padding bytes; every buffer view packed tightly, used, and read byte for byte by its
   accessors, so no byte of the binary chunk is out of every accessor's reach; no ``extras``
   anywhere; no images, textures or samplers; names absent or at most 64 characters of plain text;
   ``asset`` holding ``version`` 2.0 and at most a ``generator`` of at most 64 characters. It
   returns the triangle and material counts, read from accessor counts, for the family budget.
2. :func:`read_palette_piece`, in the pack check worker, reads the accessor data the way the
   browser's reader does (``web/packages/atlas-core/src/style-piece.ts``): one primitive of
   triangles with ``POSITION``, ``NORMAL`` and ``COLOR_0`` (``VEC4`` unsigned-short normalized,
   alpha 65535, each RGB a value of the colour table ``exulanica.srgb8-linear16/v1``), and each
   triangle one colour. The caller holds the colours to the pack's palette.

A piece whose container holds images is a textured piece (``docs/style-pack-contract.md``,
section 4): one mesh drawn by one node with no transform, each primitive triangles with float
``POSITION``, ``NORMAL`` and ``TEXCOORD_0`` and a material; each material a base colour texture on
the first texture coordinates, optionally a normal texture, factors, alpha opaque or cut out (never
blended) and whether both sides are drawn; each image a JPEG or PNG embedded in the binary chunk and
walked to its last byte by the pack's picture probe (:func:`style_packs.probe_pack_image`). The
profile check holds that much from the JSON chunk and the images; :func:`read_textured_piece` reads
the accessor data the way the browser's reader does
(``web/packages/atlas-core/src/textured-piece.ts``).

Both refuse with :class:`StylePieceRefused`, by reason and message. :func:`hold_pieces` holds each
piece a manifest lists to the profile and its family's budget (a textured piece's images to the
family's texture side, its variant to no stretch zone, its second level textured too, and the
pack's pictures, its textures' and its pieces', to the shared count), the one place both the
upload's admission and the check of a look made of generated pieces ask it.
"""

from __future__ import annotations

import json
import re
import struct
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from exulanica.world.static_glb import StaticGlbRefused, inspect_static_glb
from exulanica.world.style_pack_preview import PreviewRefused
from exulanica.world.style_packs import StylePackRefused, check_pack_images, probe_pack_image

if TYPE_CHECKING:
    from exulanica_pieces.budgets import PieceBudget

__all__ = [
    "NAME_MAX",
    "PalettePiece",
    "PieceOutOfBounds",
    "PieceProfile",
    "StylePieceRefused",
    "TexturedPiece",
    "check_piece_profile",
    "hold_pieces",
    "is_textured_piece",
    "piece_roles",
    "read_palette_piece",
    "read_textured_piece",
]

#: A name or a generator, at most, in characters.
NAME_MAX: Final = 64

_FLOAT: Final = 5126
_USHORT: Final = 5123
_UINT: Final = 5125
_TRIANGLES: Final = 4
_COMPONENT_SIZES: Final[Mapping[int, int]] = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
_WIDTHS: Final[Mapping[str, int]] = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
#: Control characters (C0, DEL, C1) and the Unicode Bidi_Control characters: never in a name.
_UNPLAIN: Final = re.compile("[\x00-\x1f\x7f-\x9f؜‎‏‪-‮⁦-⁩]")
_REFERENCES: Final = ("images", "textures", "samplers")
_TEXTURED_ATTRIBUTES: Final = frozenset({"POSITION", "NORMAL", "TEXCOORD_0"})
_TEXTURED_MATERIAL: Final = frozenset(
    {"name", "pbrMetallicRoughness", "normalTexture", "alphaMode", "alphaCutoff", "doubleSided"}
)
_TEXTURED_PBR: Final = frozenset(
    {"baseColorFactor", "baseColorTexture", "metallicFactor", "roughnessFactor"}
)


class StylePieceRefused(ValueError):
    """A piece refused by name: the reason, and what broke it."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _refuse(reason: str, message: str) -> StylePieceRefused:
    return StylePieceRefused(reason, message)


@dataclass(frozen=True, slots=True)
class PieceProfile:
    """What the profile check read, for the family budget: from accessor counts only, and a
    textured piece's images as its probe walked them."""

    triangles: int
    materials: int
    #: Each image's width and height, for a textured piece; none for a palette piece.
    image_sizes: tuple[tuple[int, int], ...] = ()

    @property
    def textured(self) -> bool:
        return bool(self.image_sizes)


@dataclass(frozen=True, slots=True)
class TexturedPiece:
    """A textured piece read: its triangles and how many images it embeds."""

    triangles: int
    images: int


@dataclass(frozen=True, slots=True)
class PalettePiece:
    """A palette piece read: its triangles, and the sRGB bytes of each colour it uses."""

    triangles: int
    colours: frozenset[tuple[int, int, int]]


def _walk(value: Any, path: str) -> Iterable[tuple[str, str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield path, key, item
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")


def check_piece_profile(payload: bytes) -> PieceProfile:
    """The canonical pack-piece profile, reading the JSON chunk and no accessor data."""
    try:
        inspected = inspect_static_glb(payload)
    except StaticGlbRefused as refused:
        raise _refuse(refused.reason, str(refused)) from None
    document = inspected.document
    for path, key, item in _walk(document, "$"):
        if key == "extras":
            raise _refuse("hidden_data", f"{path} carries extras")
        if key == "name" and (
            not isinstance(item, str) or len(item) > NAME_MAX or _UNPLAIN.search(item)
        ):
            raise _refuse("hidden_data", f"{path}.name is at most {NAME_MAX} plain characters")
    asset = document.get("asset", {})
    if set(asset) - {"version", "generator"} or asset.get("version") != "2.0":
        raise _refuse("hidden_data", "asset holds version 2.0 and at most a generator")
    generator = asset.get("generator")
    if generator is not None and (
        not isinstance(generator, str) or len(generator) > NAME_MAX or _UNPLAIN.search(generator)
    ):
        raise _refuse("hidden_data", f"asset.generator is at most {NAME_MAX} plain characters")
    sizes: tuple[tuple[int, int], ...] = ()
    if document.get("images"):
        _check_textured_structure(document)
        sizes = _walk_images(document, inspected.bin_chunk)
    else:
        for name in _REFERENCES:
            if document.get(name):
                raise _refuse("hidden_data", f"a pack piece holds no {name}")
    _check_every_byte_read(document, inspected.bin_chunk)
    return PieceProfile(
        triangles=int(inspected.counts["rendered_triangles"]),
        materials=int(inspected.counts["materials"]),
        image_sizes=sizes,
    )


def _check_textured_structure(document: Mapping[str, Any]) -> None:
    """A textured piece's structure from its JSON alone, refused as the browser refuses it."""
    nodes = document.get("nodes") or []
    scenes = document.get("scenes") or []
    scene = scenes[document.get("scene", 0)] if scenes else {}
    if len(nodes) != 1 or scene.get("nodes") != [0]:
        raise _refuse("not_a_textured_piece", "a textured piece is drawn by one node")
    if set(nodes[0]) - {"mesh", "name"} or nodes[0].get("mesh") != 0:
        raise _refuse(
            "not_a_textured_piece", "a textured piece's node draws its mesh with no transform"
        )
    meshes = document.get("meshes") or []
    if len(meshes) != 1:
        raise _refuse("not_a_textured_piece", "a textured piece is one mesh")
    materials = document.get("materials") or []
    for number, primitive in enumerate(meshes[0]["primitives"]):
        where = f"meshes[0].primitives[{number}]"
        if primitive.get("mode", _TRIANGLES) != _TRIANGLES:
            raise _refuse("not_a_textured_piece", f"{where} is triangles")
        if set(primitive.get("attributes", {})) != _TEXTURED_ATTRIBUTES:
            raise _refuse(
                "not_a_textured_piece",
                f"{where} states POSITION, NORMAL and TEXCOORD_0 and nothing else",
            )
        material = primitive.get("material")
        if not isinstance(material, int) or not 0 <= material < len(materials):
            raise _refuse("not_a_textured_piece", f"{where} names its material")
    textures = document.get("textures") or []

    def texture(info: Any, where: str) -> None:
        if not isinstance(info, dict) or info.get("texCoord", 0) != 0:
            raise _refuse("not_a_textured_piece", f"{where} reads the first texture coordinates")
        index = info.get("index")
        if not isinstance(index, int) or not 0 <= index < len(textures):
            raise _refuse("not_a_textured_piece", f"{where} names no image")

    for number, material in enumerate(materials):
        where = f"materials[{number}]"
        pbr = material.get("pbrMetallicRoughness")
        unknown = (set(material) - _TEXTURED_MATERIAL) | (
            set(pbr) - _TEXTURED_PBR if isinstance(pbr, dict) else set()
        )
        if unknown:
            raise _refuse(
                "not_a_textured_piece",
                f"{where} holds base colour, normal and factors only, not {min(unknown)}",
            )
        if not isinstance(pbr, dict):
            raise _refuse("not_a_textured_piece", f"{where} states its base colour")
        texture(pbr.get("baseColorTexture"), f"{where}.baseColorTexture")
        if "normalTexture" in material:
            texture(material["normalTexture"], f"{where}.normalTexture")
        if material.get("alphaMode", "OPAQUE") not in ("OPAQUE", "MASK"):
            raise _refuse("not_a_textured_piece", f"{where} is opaque or cut out, never blended")


def _walk_images(document: Mapping[str, Any], bin_chunk: bytes) -> tuple[tuple[int, int], ...]:
    """Each embedded image walked to its last byte by the pack's picture probe."""
    views = document.get("bufferViews") or []
    sizes = []
    for number, image in enumerate(document.get("images") or []):
        view = views[image["bufferView"]]
        start = int(view.get("byteOffset", 0))
        data = bin_chunk[start : start + int(view["byteLength"])]
        try:
            probed = probe_pack_image(data, image.get("mimeType", ""))
        except PreviewRefused as refused:
            raise _refuse(f"image_{refused.reason}", f"images[{number}]: {refused}") from None
        sizes.append((probed.width_px, probed.height_px))
    return tuple(sizes)


class PieceOutOfBounds(ValueError):
    """A pack's piece refused by the pack-piece profile or its family's budget: the code the
    upload's admission answers it with, what broke it, and the piece's path."""

    def __init__(self, code: str, message: str, path: str) -> None:
        self.code = code
        self.path = path
        super().__init__(message)


def piece_roles(manifest: Mapping[str, Any]) -> dict[str, tuple[str, Mapping[str, Any], bool]]:
    """Every piece the manifest's modules list, by path: its family (the role's first part), its
    variant, and whether it is the variant's second level of detail."""
    pieces: dict[str, tuple[str, Mapping[str, Any], bool]] = {}
    for role, module in manifest["modules"].items():
        family = role.split(".", 1)[0]
        for variant in module["variants"]:
            pieces[variant["file"]] = (family, variant, False)
            if variant["lod1"] is not None:
                pieces[variant["lod1"]] = (family, variant, True)
    return pieces


def _profile(data: bytes, path: str) -> PieceProfile:
    try:
        return check_piece_profile(data)
    except StylePieceRefused as refused:
        raise PieceOutOfBounds(
            "style_pack_piece_refused", f"{refused.reason}: {refused}", path
        ) from None


def hold_pieces(
    pieces: Mapping[str, tuple[str, Mapping[str, Any], bool]],
    read: Callable[[str], bytes],
    budgets: Mapping[str, PieceBudget],
    lod1_share_permille: int,
    texture_images: int = 0,
) -> dict[str, int]:
    """Each piece held, in path order, to the canonical pack-piece profile and its family's budget:
    its file size, its triangles (a tiled family's limit scales with the variant's width, and a
    second level of detail keeps at most its share of the first's) and its materials. Every piece's
    size is held in one pass before any piece is opened, so a far level sorting before its first
    never opens the first unchecked. A textured piece's images are held to its family's texture
    side, its variant to no stretch zone, and a textured first level's second level to being
    textured too; the pack's pictures, ``texture_images`` its textures draw with and every image its
    pieces embed, to the shared count. Returns each piece's triangles by path, or raises
    :class:`PieceOutOfBounds` for the first that fails."""
    data = {path: read(path) for path in sorted(pieces)}
    for path, (family, _variant, _lod1) in sorted(pieces.items()):
        if len(data[path]) > budgets[family].glb_bytes:
            raise PieceOutOfBounds("over_budget", "a piece is over its family's file size", path)
    measured: dict[str, int] = {}
    profiles: dict[str, PieceProfile] = {}
    embedded = 0
    for path, (family, variant, lod1) in sorted(pieces.items()):
        budget = budgets[family]
        profile = profiles.get(path) or _profile(data[path], path)
        profiles[path] = profile
        limit = budget.triangle_limit(variant["size_mm"][0])
        if lod1:
            first = profiles.get(variant["file"])
            if first is None:
                first = _profile(data[variant["file"]], variant["file"])
                profiles[variant["file"]] = first
            limit = first.triangles * lod1_share_permille // 1000
            if first.textured and not profile.textured:
                raise PieceOutOfBounds(
                    "style_pack_piece_refused",
                    "a textured piece's second level is textured too",
                    path,
                )
        if profile.triangles > limit or profile.materials > budget.materials:
            raise PieceOutOfBounds(
                "over_budget",
                f"{profile.triangles} triangles and {profile.materials} materials, over "
                f"{limit} and {budget.materials}",
                path,
            )
        if profile.textured:
            side = max(max(size) for size in profile.image_sizes)
            if side > budget.texture_side_px:
                raise PieceOutOfBounds(
                    "over_budget",
                    f"an image {side} px a side, over its family's {budget.texture_side_px}",
                    path,
                )
            if any(zone is not None for zone in variant.get("stretch_mm") or ()):
                raise PieceOutOfBounds(
                    "style_pack_piece_refused",
                    "a textured piece states no stretch zone: it is drawn whole",
                    path,
                )
            embedded += len(profile.image_sizes)
        measured[path] = profile.triangles
    try:
        check_pack_images(texture_images, embedded)
    except StylePackRefused as refused:
        raise PieceOutOfBounds("over_budget", str(refused), "files") from None
    return measured


def _check_every_byte_read(document: Mapping[str, Any], bin_chunk: bytes) -> None:
    """One buffer, the binary chunk less at most three zero bytes; every view tight, used and
    read byte for byte."""
    buffers = document.get("buffers") or []
    if len(buffers) != 1:
        raise _refuse("hidden_data", "a pack piece holds exactly one buffer")
    length = int(buffers[0]["byteLength"])
    padding = bin_chunk[length:]
    if len(padding) > 3 or any(padding):
        raise _refuse("hidden_data", "the binary chunk is its buffer and at most 3 zero bytes")
    views = document.get("bufferViews") or []
    covered: list[list[tuple[int, int]]] = [[] for _ in views]
    # An image's view is read whole, by the picture probe.
    for image in document.get("images") or []:
        covered[image["bufferView"]].append((0, int(views[image["bufferView"]]["byteLength"])))
    for number, accessor in enumerate(document.get("accessors") or []):
        if "bufferView" not in accessor or "sparse" in accessor:
            raise _refuse("hidden_data", f"accessors[{number}] reads a buffer view, densely")
        view = views[accessor["bufferView"]]
        size = _COMPONENT_SIZES[accessor["componentType"]] * _WIDTHS[accessor["type"]]
        if view.get("byteStride", size) != size:
            raise _refuse("hidden_data", f"accessors[{number}]'s buffer view is packed tightly")
        start = int(accessor.get("byteOffset", 0))
        covered[accessor["bufferView"]].append((start, start + size * int(accessor["count"])))
    ends = []
    for number, (view, spans) in enumerate(zip(views, covered, strict=True)):
        reach = 0
        for start, end in sorted(spans):
            if start > reach:
                break
            reach = max(reach, end)
        if not spans or reach < int(view["byteLength"]):
            raise _refuse("hidden_data", f"bufferViews[{number}] holds bytes no accessor reads")
        offset = int(view.get("byteOffset", 0))
        ends.append((offset, offset + int(view["byteLength"])))
    reach = 0
    for start, end in sorted(ends):
        # Views may leave up to three bytes between them for alignment, and those must be zero.
        if start - reach > 3 or any(bin_chunk[reach:start]):
            raise _refuse("hidden_data", "the buffer holds bytes outside every buffer view")
        reach = max(reach, end)
    if length - reach > 3 or any(bin_chunk[reach:length]):
        raise _refuse("hidden_data", "the buffer holds bytes outside every buffer view")


def read_palette_piece(payload: bytes, table: Sequence[int]) -> PalettePiece:
    """A palette piece's colours and triangles, read as the browser reads it.

    ``table`` is the 256 linear values of ``exulanica.srgb8-linear16/v1``. The payload is a piece
    that passed :func:`check_piece_profile`; this reads its accessor data.
    """
    if len(table) != 256:
        raise ValueError("the colour table holds 256 values")
    if len(payload) < 20 or struct.unpack_from("<II", payload, 0) != (0x46546C67, 2):
        raise _refuse("not_a_piece", "not a binary glTF 2.0 container")
    json_length = struct.unpack_from("<I", payload, 12)[0]
    document = json.loads(payload[20 : 20 + json_length])
    bin_at = 20 + json_length
    bin_length = struct.unpack_from("<I", payload, bin_at)[0]
    bin_chunk = payload[bin_at + 8 : bin_at + 8 + bin_length]
    primitives = [p for mesh in document.get("meshes") or [] for p in mesh["primitives"]]
    if len(primitives) != 1:
        raise _refuse("not_a_palette_piece", "a palette piece is one primitive")
    primitive = primitives[0]
    if primitive.get("mode", _TRIANGLES) != _TRIANGLES:
        raise _refuse("not_a_palette_piece", "a palette piece is triangles")
    accessors = document.get("accessors") or []
    views = document.get("bufferViews") or []

    def accessor(index: int | None, what: str) -> Mapping[str, Any]:
        if index is None or not 0 <= index < len(accessors):
            raise _refuse("not_a_palette_piece", f"a palette piece states {what}")
        return accessors[index]

    def data(item: Mapping[str, Any], size: int) -> bytes:
        view = views[item["bufferView"]]
        start = int(view.get("byteOffset", 0)) + int(item.get("byteOffset", 0))
        return bin_chunk[start : start + int(item["count"]) * size]

    attributes = primitive.get("attributes", {})
    position = accessor(attributes.get("POSITION"), "POSITION")
    normal = accessor(attributes.get("NORMAL"), "NORMAL")
    colour = accessor(attributes.get("COLOR_0"), "COLOR_0")
    if (position["componentType"], position["type"]) != (_FLOAT, "VEC3"):
        raise _refuse("not_a_palette_piece", "POSITION is float VEC3")
    if (normal["componentType"], normal["type"], normal["count"]) != (
        _FLOAT,
        "VEC3",
        position["count"],
    ):
        raise _refuse("not_a_palette_piece", "NORMAL is float VEC3, one per position")
    if (
        colour["componentType"] != _USHORT
        or colour["type"] != "VEC4"
        or colour.get("normalized") is not True
        or colour["count"] != position["count"]
    ):
        raise _refuse(
            "not_a_palette_piece", "COLOR_0 is VEC4 unsigned-short normalized, one per position"
        )
    indices = accessor(primitive.get("indices"), "indices")
    if (
        indices["componentType"] not in (_USHORT, _UINT)
        or indices["type"] != "SCALAR"
        or indices["count"] % 3
    ):
        raise _refuse(
            "not_a_palette_piece", "indices are unsigned short or int scalars, whole triangles"
        )
    vertices = int(position["count"])
    colours = struct.unpack(f"<{vertices * 4}H", data(colour, 8))
    index_format = "H" if indices["componentType"] == _USHORT else "I"
    corners = struct.unpack(
        f"<{indices['count']}{index_format}", data(indices, 2 if index_format == "H" else 4)
    )
    by_linear = {value: byte for byte, value in enumerate(table)}

    def colour_of(vertex: int) -> tuple[int, int, int]:
        r, g, b, a = colours[vertex * 4 : vertex * 4 + 4]
        if a != 65535:
            raise _refuse("not_a_palette_piece", "COLOR_0 alpha is 65535")
        try:
            return (by_linear[r], by_linear[g], by_linear[b])
        except KeyError:
            raise _refuse("not_a_palette_piece", "a colour is no sRGB byte of the table") from None

    used: set[tuple[int, int, int]] = set()
    for first in range(0, len(corners), 3):
        triangle = corners[first : first + 3]
        if any(vertex >= vertices for vertex in triangle):
            raise _refuse("not_a_palette_piece", "an index names a vertex past the end")
        key = colour_of(triangle[0])
        if any(colour_of(vertex) != key for vertex in triangle[1:]):
            raise _refuse("not_a_palette_piece", "a triangle is coloured by one swatch")
        used.add(key)
    if not used:
        raise _refuse("not_a_palette_piece", "a palette piece holds at least one triangle")
    return PalettePiece(triangles=len(corners) // 3, colours=frozenset(used))


def _glb_chunks(payload: bytes, not_a: str) -> tuple[dict[str, Any], bytes]:
    if len(payload) < 20 or struct.unpack_from("<II", payload, 0) != (0x46546C67, 2):
        raise _refuse(not_a, "not a binary glTF 2.0 container")
    json_length = struct.unpack_from("<I", payload, 12)[0]
    document = json.loads(payload[20 : 20 + json_length])
    bin_at = 20 + json_length
    if bin_at + 8 > len(payload):
        return document, b""
    bin_length = struct.unpack_from("<I", payload, bin_at)[0]
    return document, payload[bin_at + 8 : bin_at + 8 + bin_length]


def is_textured_piece(payload: bytes) -> bool:
    """Whether a piece is a textured piece (its container holds images), from its JSON chunk."""
    document, _ = _glb_chunks(payload, "not_a_piece")
    return bool(document.get("images"))


def read_textured_piece(payload: bytes) -> TexturedPiece:
    """A textured piece's triangles and images, read as the browser reads it: its structure, every
    accessor's layout and every index, and every image walked to its end by the picture probe."""
    document, bin_chunk = _glb_chunks(payload, "not_a_textured_piece")
    if not document.get("images"):
        raise _refuse("not_a_textured_piece", "a textured piece holds at least one image")
    _check_textured_structure(document)
    accessors = document.get("accessors") or []
    views = document.get("bufferViews") or []

    def accessor(index: Any, what: str) -> Mapping[str, Any]:
        if not isinstance(index, int) or not 0 <= index < len(accessors):
            raise _refuse("not_a_textured_piece", f"a textured piece's primitive states {what}")
        return accessors[index]

    def data(item: Mapping[str, Any], size: int) -> bytes:
        view = views[item["bufferView"]]
        start = int(view.get("byteOffset", 0)) + int(item.get("byteOffset", 0))
        end = start + int(item["count"]) * size
        if end > len(bin_chunk):
            raise _refuse("not_a_textured_piece", "an accessor reaches past the binary chunk")
        return bin_chunk[start:end]

    triangles = 0
    for primitive in document["meshes"][0]["primitives"]:
        attributes = primitive["attributes"]
        position = accessor(attributes["POSITION"], "POSITION")
        normal = accessor(attributes["NORMAL"], "NORMAL")
        uv = accessor(attributes["TEXCOORD_0"], "TEXCOORD_0")
        if (position["componentType"], position["type"]) != (_FLOAT, "VEC3"):
            raise _refuse("not_a_textured_piece", "POSITION is float VEC3")
        if (normal["componentType"], normal["type"], normal["count"]) != (
            _FLOAT,
            "VEC3",
            position["count"],
        ):
            raise _refuse("not_a_textured_piece", "NORMAL is float VEC3, one per position")
        if (uv["componentType"], uv["type"], uv["count"]) != (_FLOAT, "VEC2", position["count"]):
            raise _refuse("not_a_textured_piece", "TEXCOORD_0 is float VEC2, one per position")
        indices = accessor(primitive.get("indices"), "indices")
        if (
            indices["componentType"] not in (_USHORT, _UINT)
            or indices["type"] != "SCALAR"
            or indices["count"] % 3
            or not indices["count"]
        ):
            raise _refuse(
                "not_a_textured_piece", "indices are unsigned short or int scalars, whole triangles"
            )
        index_format = "H" if indices["componentType"] == _USHORT else "I"
        corners = struct.unpack(
            f"<{indices['count']}{index_format}", data(indices, 2 if index_format == "H" else 4)
        )
        if max(corners) >= int(position["count"]):
            raise _refuse("not_a_textured_piece", "an index names a vertex past the end")
        triangles += len(corners) // 3
    images = _walk_images(document, bin_chunk)
    return TexturedPiece(triangles=triangles, images=len(images))
