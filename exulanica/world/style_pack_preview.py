"""A style pack's preview picture, walked to its end on arrival and refused if it hides anything.

A pack shows itself in one listed picture (``preview``), at most 512 KiB, which a person sees before
choosing it. An uploaded picture may carry far more than a picture: where and when a photograph was
taken, the camera, a thumbnail of the uncropped original, text, a second image after its end. So
the server walks each container to its last byte without decoding it, against an allowlist of the
segments and chunks a plain still picture needs, and refuses anything else by name:

- JPEG: SOI; exactly one APP0, which is JFIF and 16 bytes long (no thumbnail, no JFXX); DQT, DHT,
  DRI, one SOF0, SOF1 or SOF2, SOS with its entropy-coded data and RST0 to RST7; EOI and nothing
  after it. No APP1 to APP15 (so no Exif, XMP or ICC) and no COM.
- PNG: the signature, IHDR first, IEND last and nothing after it, and between them only PLTE, tRNS,
  gAMA, cHRM, sRGB and IDAT. No iCCP, no text or time chunk, no private or other ancillary chunk,
  no animation.
- WebP: ``RIFF`` of exactly its declared size holding ``WEBP`` and one ``VP8 `` or ``VP8L``
  chunk, or ``VP8X`` with only the alpha flag, then ``ALPH`` and ``VP8 ``. No ICCP, EXIF, XMP,
  ANIM, ANMF or unknown chunk.

One frame, 1 to 2,048 pixels on each side. The page re-encodes a picture a person chooses through a
canvas before upload, so an ordinary photograph passes; this walk stays the gate.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Final

__all__ = ["PREVIEW_MAX_SIDE", "PreviewRefused", "PreviewSize", "walk_preview"]

#: A preview's longest side, at most, in pixels.
PREVIEW_MAX_SIDE: Final = 2048

_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
_PNG_ALLOWED: Final = frozenset({b"PLTE", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"IDAT"})
#: JPEG markers with no length: SOI, EOI, RST0 to RST7.
_JPEG_STANDALONE: Final = frozenset({0xD8, 0xD9, *range(0xD0, 0xD8)})
_JPEG_FRAMES: Final = frozenset({0xC0, 0xC1, 0xC2})
_JPEG_ALLOWED: Final = frozenset({0xDB, 0xC4, 0xDD})  # DQT, DHT, DRI
_JFIF_APP0_LENGTH: Final = 16


class PreviewRefused(ValueError):
    """A preview refused by name: the reason, and what in it was refused."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PreviewSize:
    width_px: int
    height_px: int


def _refuse(message: str, reason: str = "hidden_data") -> PreviewRefused:
    return PreviewRefused(reason, message)


def _sized(width: int, height: int) -> PreviewSize:
    if not (1 <= width <= PREVIEW_MAX_SIDE and 1 <= height <= PREVIEW_MAX_SIDE):
        raise _refuse(
            f"a preview is 1 to {PREVIEW_MAX_SIDE} pixels a side, not {width} by {height}",
            "preview_size",
        )
    return PreviewSize(width, height)


def walk_preview(data: bytes, media_type: str) -> PreviewSize:
    """The preview's size, once every byte of it has been walked and allowed."""
    if media_type == "image/jpeg":
        return _walk_jpeg(data)
    if media_type == "image/png":
        return _walk_png(data)
    if media_type == "image/webp":
        return _walk_webp(data)
    raise _refuse(f"a preview is a JPEG, PNG or WebP picture, not {media_type}", "media_type")


def _walk_jpeg(data: bytes) -> PreviewSize:
    if data[:2] != b"\xff\xd8":
        raise _refuse("the bytes are not a JPEG picture", "media_type")
    at = 2
    size: PreviewSize | None = None
    app0 = 0
    scanning = False
    while at < len(data):
        if scanning:
            # Entropy-coded data runs to the next marker that is neither a stuffed zero nor RSTn.
            while at < len(data) - 1 and not (
                data[at] == 0xFF and data[at + 1] not in (0x00, *range(0xD0, 0xD8))
            ):
                at += 1
            scanning = False
            if at >= len(data) - 1:
                break
        if data[at] != 0xFF:
            raise _refuse("a JPEG segment does not start with a marker")
        while at < len(data) and data[at] == 0xFF:
            at += 1
        if at >= len(data):
            break
        marker = data[at]
        at += 1
        if marker == 0xD9:  # EOI
            if at != len(data):
                raise _refuse("a JPEG picture holds bytes after its end")
            if size is None or app0 != 1:
                raise _refuse("a JPEG picture is one JFIF frame")
            return size
        if marker in _JPEG_STANDALONE:
            continue
        if at + 2 > len(data):
            raise _refuse("a JPEG segment runs past the end")
        length = struct.unpack_from(">H", data, at)[0]
        if length < 2 or at + length > len(data):
            raise _refuse("a JPEG segment runs past the end")
        body = data[at + 2 : at + length]
        if marker == 0xE0:
            app0 += 1
            if app0 > 1 or length != _JFIF_APP0_LENGTH or body[:5] != b"JFIF\x00":
                raise _refuse("a JPEG holds one JFIF APP0 of 16 bytes, with no thumbnail")
            if body[12:14] != b"\x00\x00":
                raise _refuse("a JPEG holds no thumbnail")
        elif marker in _JPEG_FRAMES:
            if size is not None:
                raise _refuse("a JPEG picture is one frame")
            if len(body) < 5:
                raise _refuse("a JPEG frame header is cut short")
            height, width = struct.unpack_from(">HH", body, 1)
            size = _sized(width, height)
        elif marker == 0xDA:  # SOS
            if size is None:
                raise _refuse("a JPEG scan comes after its frame")
            scanning = True
        elif marker not in _JPEG_ALLOWED:
            raise _refuse(f"a JPEG picture holds a segment 0x{marker:02X}, which is not allowed")
        at += length
    raise _refuse("a JPEG picture ends with its EOI marker")


def _walk_png(data: bytes) -> PreviewSize:
    if data[:8] != _PNG_SIGNATURE:
        raise _refuse("the bytes are not a PNG picture", "media_type")
    at = 8
    size: PreviewSize | None = None
    first = True
    while at + 12 <= len(data):
        length, kind = struct.unpack_from(">I4s", data, at)
        end = at + 12 + length
        if end > len(data):
            raise _refuse("a PNG chunk runs past the end")
        if first:
            if kind != b"IHDR" or length != 13:
                raise _refuse("a PNG picture begins with its IHDR")
            width, height = struct.unpack_from(">II", data, at + 8)
            size = _sized(width, height)
            first = False
        elif kind == b"IEND":
            if end != len(data):
                raise _refuse("a PNG picture holds bytes after its end")
            assert size is not None
            return size
        elif kind not in _PNG_ALLOWED:
            raise _refuse(
                f"a PNG picture holds a {kind.decode('latin-1')!r} chunk, which is not allowed"
            )
        at = end
    raise _refuse("a PNG picture ends with its IEND chunk")


def _walk_webp(data: bytes) -> PreviewSize:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise _refuse("the bytes are not a WebP picture", "media_type")
    if struct.unpack_from("<I", data, 4)[0] + 8 != len(data):
        raise _refuse("a WebP picture is exactly its RIFF size, with nothing after it")
    chunks: list[tuple[bytes, bytes]] = []
    at = 12
    while at < len(data):
        if at + 8 > len(data):
            raise _refuse("a WebP chunk runs past the end")
        kind, length = struct.unpack_from("<4sI", data, at)
        end = at + 8 + length + (length & 1)
        if end > len(data):
            raise _refuse("a WebP chunk runs past the end")
        chunks.append((kind, data[at + 8 : at + 8 + length]))
        at = end
    kinds = [kind for kind, _ in chunks]
    if kinds == [b"VP8 "]:
        return _vp8_size(chunks[0][1])
    if kinds == [b"VP8L"]:
        body = chunks[0][1]
        if len(body) < 5 or body[0] != 0x2F:
            raise _refuse("a lossless WebP image is cut short")
        bits = int.from_bytes(body[1:5], "little")
        return _sized((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    if kinds == [b"VP8X", b"ALPH", b"VP8 "]:
        flags = chunks[0][1][0] if chunks[0][1] else 0xFF
        if flags & ~0x10:
            raise _refuse("an extended WebP picture states alpha and nothing else")
        return _vp8_size(chunks[2][1])
    raise _refuse(
        "a WebP picture holds one VP8 or VP8L image, or VP8X with alpha, and no other chunk: "
        + ", ".join(kind.decode("latin-1") for kind in kinds)
    )


def _vp8_size(body: bytes) -> PreviewSize:
    if len(body) < 10 or body[3:6] != b"\x9d\x01\x2a":
        raise _refuse("a lossy WebP image is cut short")
    width, height = struct.unpack_from("<HH", body, 6)
    return _sized(width & 0x3FFF, height & 0x3FFF)
