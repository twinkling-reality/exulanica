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

Both refuse with :class:`StylePieceRefused`, by reason and message. :func:`hold_pieces` holds each
piece a manifest lists to the profile and its family's budget, the one place both the upload's
admission and the check of a look made of generated pieces ask it.
"""

from __future__ import annotations

import json
import re
import struct
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from exulanica.world.static_glb import StaticGlbRefused, inspect_static_glb

if TYPE_CHECKING:
    from exulanica_pieces.budgets import PieceBudget

__all__ = [
    "NAME_MAX",
    "PalettePiece",
    "PieceOutOfBounds",
    "PieceProfile",
    "StylePieceRefused",
    "check_piece_profile",
    "hold_pieces",
    "piece_roles",
    "read_palette_piece",
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


class StylePieceRefused(ValueError):
    """A piece refused by name: the reason, and what broke it."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _refuse(reason: str, message: str) -> StylePieceRefused:
    return StylePieceRefused(reason, message)


@dataclass(frozen=True, slots=True)
class PieceProfile:
    """What the profile check read, for the family budget: from accessor counts only."""

    triangles: int
    materials: int


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
    for name in _REFERENCES:
        if document.get(name):
            raise _refuse("hidden_data", f"a pack piece holds no {name}")
    _check_every_byte_read(document, inspected.bin_chunk)
    return PieceProfile(
        triangles=int(inspected.counts["rendered_triangles"]),
        materials=int(inspected.counts["materials"]),
    )


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
) -> dict[str, int]:
    """Each piece held, in path order, to the canonical pack-piece profile and its family's budget:
    its file size, its triangles (a tiled family's limit scales with the variant's width, and a
    second level of detail keeps at most its share of the first's) and its materials. Returns each
    piece's triangles by path, or raises :class:`PieceOutOfBounds` for the first that fails."""
    measured: dict[str, int] = {}
    for path, (family, variant, lod1) in sorted(pieces.items()):
        data = read(path)
        budget = budgets[family]
        if len(data) > budget.glb_bytes:
            raise PieceOutOfBounds("over_budget", "a piece is over its family's file size", path)
        profile = _profile(data, path)
        limit = budget.triangle_limit(variant["size_mm"][0])
        if lod1:
            first = measured.get(variant["file"])
            if first is None:
                first = _profile(read(variant["file"]), variant["file"]).triangles
            limit = first * lod1_share_permille // 1000
        if profile.triangles > limit or profile.materials > budget.materials:
            raise PieceOutOfBounds(
                "over_budget",
                f"{profile.triangles} triangles and {profile.materials} materials, over "
                f"{limit} and {budget.materials}",
                path,
            )
        measured[path] = profile.triangles
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
