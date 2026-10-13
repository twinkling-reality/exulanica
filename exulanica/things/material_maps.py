"""Embedded PNG material inputs for authored static meshes, without files or decoders.

RGB/RGBA eight-bit, non-interlaced PNGs are checked through their compressed scanlines. The
writer keeps the exact validated bytes. Base colour is sRGB; tangent normals and packed glTF
metallic/roughness (green roughness, blue metallic) are linear data, not colour swatches.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from typing import Final

__all__ = ["IMAGES_MAX", "IMAGE_SIDE_MAX", "TEXELS_MAX", "MaterialMaps", "PngMap"]

# Authoring stays within the existing static-glb/v1 admission ceilings.
IMAGE_SIDE_MAX: Final = 4096
IMAGES_MAX: Final = 32
TEXELS_MAX: Final = 1 << 24
_PNG: Final = b"\x89PNG\r\n\x1a\n"
_BYTES_MAX: Final = 32 * 1024 * 1024


def _png_size(data: bytes) -> tuple[int, int]:
    if type(data) is not bytes or not data.startswith(_PNG) or len(data) > _BYTES_MAX:
        raise ValueError("material map is embedded PNG bytes within 32 MiB")
    offset = 8
    size = None
    channels = 0
    compressed = bytearray()
    saw_data = False
    ended_data = False
    finished = False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("material PNG has a truncated chunk")
        length, kind = struct.unpack_from(">I4s", data, offset)
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("material PNG has a truncated chunk")
        payload = data[offset + 8 : end - 4]
        crc = struct.unpack_from(">I", data, end - 4)[0]
        if zlib.crc32(kind + payload) != crc:
            raise ValueError("material PNG chunk checksum disagrees")
        if not all(65 <= c <= 90 or 97 <= c <= 122 for c in kind) or kind[2] & 32:
            raise ValueError("material PNG chunk type is invalid")
        if size is None and kind != b"IHDR":
            raise ValueError("material PNG starts with IHDR")
        if kind == b"IHDR":
            if size is not None or length != 13:
                raise ValueError("material PNG holds one IHDR")
            width, height, depth, colour, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if not 1 <= width <= IMAGE_SIDE_MAX or not 1 <= height <= IMAGE_SIDE_MAX:
                raise ValueError("material PNG sides are 1 to 4096 pixels")
            if (
                depth != 8
                or colour not in (2, 6)
                or (compression, filtering, interlace) != (0, 0, 0)
            ):
                raise ValueError("material PNG is non-interlaced eight-bit RGB or RGBA")
            size = (width, height)
            channels = 3 if colour == 2 else 4
        elif kind == b"IDAT":
            if ended_data:
                raise ValueError("material PNG IDAT chunks are consecutive")
            saw_data = True
            compressed.extend(payload)
        elif kind == b"IEND":
            if length or not compressed or end != len(data):
                raise ValueError("material PNG ends once after its pixel data")
            finished = True
            break
        elif kind in (b"acTL", b"fcTL", b"fdAT") or not kind[0] & 32:
            raise ValueError("material PNG has an unsupported critical or animated chunk")
        elif saw_data:
            ended_data = True
        offset = end
    if size is None or not finished:
        raise ValueError("material PNG is incomplete")
    row_bytes = 1 + size[0] * channels
    expected = row_bytes * size[1]
    try:
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(compressed, expected + 1)
    except zlib.error as exc:
        raise ValueError("material PNG pixels do not decompress") from exc
    if len(pixels) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("material PNG pixel length disagrees with its dimensions")
    if any(pixels[offset] > 4 for offset in range(0, expected, row_bytes)):
        raise ValueError("material PNG has an invalid scanline filter")
    return size


@dataclass(frozen=True, slots=True)
class PngMap:
    """A validated self-contained material image; its exact bytes become part of the GLB digest."""

    data: bytes
    size_px: tuple[int, int] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "size_px", _png_size(self.data))


@dataclass(frozen=True, slots=True)
class MaterialMaps:
    """Optional maps in glTF's material roles, all sampled through the mesh's TEXCOORD_0.

    Normal RGB encodes tangent-space XYZ in the glTF convention (+Y). Roughness is the green
    channel and metallic the blue channel of metallic_roughness; the red channel is unused.
    Existing colour/material factors multiply their maps. This supplies no UV bake or rig.
    """

    base_colour: PngMap | None = None
    normal: PngMap | None = None
    metallic_roughness: PngMap | None = None

    def __post_init__(self) -> None:
        maps = (self.base_colour, self.normal, self.metallic_roughness)
        if not any(maps) or any(m is not None and not isinstance(m, PngMap) for m in maps):
            raise ValueError("material maps hold at least one validated PNG")
