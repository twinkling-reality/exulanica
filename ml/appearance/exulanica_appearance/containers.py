"""Read a texture set container (``LTX1``) for measurement only.

The product's readers are ``exulanica/world/texture_assets.py`` and loom-texture's container code;
this package may import neither, so this is a small reader written from
``docs/texture-package.md`` section 3, used only to measure published sets and candidates. It holds
a container to its manifest entry's sha256 and size, then to the framing: magic, header length,
canonical header, space padding to 16 bytes, maps contiguous and exactly the stated lengths.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from exulanica_appearance.canonical import Refused, parse_canonical, sha256_hex

__all__ = ["read_container"]

_MAGIC: Final = b"LTX1"
_PREAMBLE: Final = 8
_ALIGN: Final = 16


def read_container(
    raw: bytes, entry: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, NDArray[np.uint8]]]:
    where = f"texture set {entry.get('set_id')}"
    if len(raw) != entry["byte_size"] or sha256_hex(raw) != entry["content_sha256"]:
        raise Refused(f"{where}: the bytes are not the size and sha256 the manifest pins")
    if raw[:4] != _MAGIC or len(raw) < _PREAMBLE:
        raise Refused(f"{where}: not an LTX1 container")
    (length,) = struct.unpack("<I", raw[4:8])
    header = parse_canonical(raw[_PREAMBLE : _PREAMBLE + length], f"{where} header")
    start = -(-(_PREAMBLE + length) // _ALIGN) * _ALIGN
    if raw[_PREAMBLE + length : start] != b" " * (start - _PREAMBLE - length):
        raise Refused(f"{where}: header padding is not spaces")
    if header.get("set_id") != entry["set_id"] or header.get("version") != entry["version"]:
        raise Refused(f"{where}: the header names another set or version")
    width = header["resolution"]["width"]
    height = header["resolution"]["height"]
    maps: dict[str, NDArray[np.uint8]] = {}
    at = start
    for item in header["maps"]:
        if item["byte_offset"] != at or item["byte_length"] != width * height * item["components"]:
            raise Refused(f"{where}: map {item['name']} is not contiguous at its stated length")
        view = np.frombuffer(raw, dtype=np.uint8, count=item["byte_length"], offset=at)
        maps[item["name"]] = view.reshape(height, width, item["components"])
        at += item["byte_length"]
    if at != len(raw):
        raise Refused(f"{where}: bytes follow the last map")
    return header, maps
