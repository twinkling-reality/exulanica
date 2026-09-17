"""Read and write self-contained GLB 2.0 containers without third-party packages."""

import json
import struct

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942
COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_glb(data):
    """Return (document, binary) after checking the container frame."""
    if len(data) < 20 or len(data) % 4:
        raise ValueError("GLB must be at least 20 bytes and word aligned")
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC or version != 2 or length != len(data):
        raise ValueError("invalid GLB header")
    json_length, json_type = struct.unpack_from("<II", data, 12)
    if json_type != CHUNK_JSON:
        raise ValueError("first chunk must be JSON")
    document = json.loads(data[20 : 20 + json_length])
    offset = 20 + json_length
    binary = b""
    if offset < len(data):
        bin_length, bin_type = struct.unpack_from("<II", data, offset)
        if bin_type != CHUNK_BIN or offset + 8 + bin_length != len(data):
            raise ValueError("second chunk must be BIN and fill the container")
        binary = data[offset + 8 : offset + 8 + bin_length]
    return document, binary


def write_glb(document, binary):
    """Serialise a document and binary chunk, padding both to four-byte words."""
    body = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
    body += b" " * (-len(body) % 4)
    binary = bytes(binary) + b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(body) + (8 + len(binary) if binary else 0)
    out = struct.pack("<III", GLB_MAGIC, 2, total) + struct.pack("<II", len(body), CHUNK_JSON) + body
    if binary:
        out += struct.pack("<II", len(binary), CHUNK_BIN) + binary
    return out


def accessor_values(document, binary, index):
    """Decode a non-sparse accessor into a flat list of numbers."""
    accessor = document["accessors"][index]
    if "sparse" in accessor or "bufferView" not in accessor:
        raise ValueError("only dense accessors are decoded here")
    view = document["bufferViews"][accessor["bufferView"]]
    code, size = COMPONENT[accessor["componentType"]]
    width = WIDTH[accessor["type"]]
    stride = view.get("byteStride", size * width)
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    values = []
    for element in range(accessor["count"]):
        base = start + element * stride
        values.extend(struct.unpack_from(f"<{width}{code}", binary, base))
    return values


class BinaryBuilder:
    """Append aligned buffer views to one embedded buffer."""

    def __init__(self):
        self.data = bytearray()
        self.views = []

    def add(self, payload, target=None):
        self.data += b"\0" * (-len(self.data) % 4)
        view = {"buffer": 0, "byteOffset": len(self.data), "byteLength": len(payload)}
        if target is not None:
            view["target"] = target
        self.data += payload
        self.views.append(view)
        return len(self.views) - 1
