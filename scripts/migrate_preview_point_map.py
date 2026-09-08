#!/usr/bin/env python3
"""Migrate only the identified stale preview OPM/2 header; never infer or rewrite points."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from exulanica.reconstruction.validation import validate_opm

OLD_SHA256 = "3d6712872eb05bd8b012b3f1e1ddf90cce17fe669fcd8b4360354d1909d096e2"


def migrate(data: bytes) -> bytes:
    if hashlib.sha256(data).hexdigest() != OLD_SHA256:
        raise ValueError("not the exact reviewed legacy preview fixture")
    if data[:4] != b"OPM1":
        raise ValueError("not an OPM container")
    length = struct.unpack_from("<I", data, 4)[0]
    raw = data[8:8 + length]
    header = json.loads(raw)
    if header["version"] != 2 or header["format"] != "orimera-point-map":
        raise ValueError("only the reviewed OPM/2 format-name migration is supported")
    first = min(section["byteOffset"] for section in header["sections"])
    if data[8 + length:first] != b" " * (first - 8 - length):
        raise ValueError("header padding is not the reviewed space padding")
    token = b'"format":"orimera-point-map"'
    if raw.count(token) != 1:
        raise ValueError("ambiguous format field")
    changed = raw.replace(token, b'"format":"exulanica-point-map"')
    if 8 + len(changed) > first:
        raise ValueError("not enough existing padding; refusing to relocate payload")
    if json.loads(changed) != {**header, "format": "exulanica-point-map"}:
        raise ValueError("migration changed other metadata")
    output = b"OPM1" + struct.pack("<I", len(changed)) + changed
    output += b" " * (first - len(output)) + data[first:]
    if len(output) != len(data) or output[first:] != data[first:]:
        raise ValueError("migration changed point payload or offsets")
    validate_opm(output)  # Current validator checks every point, bounds, tags and dimensions.
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    source = args.source.read_bytes()
    migrated = migrate(source)
    # Refuse overwriting an unrelated object, and make reruns checkable/idempotent.
    if args.destination.exists() and args.destination.read_bytes() != migrated:
        parser.error("destination exists with different bytes")
    args.destination.write_bytes(migrated)
    header = json.loads(migrated[8:8 + struct.unpack_from("<I", migrated, 4)[0]])
    print(json.dumps({
        "old_sha256": hashlib.sha256(source).hexdigest(),
        "new_sha256": hashlib.sha256(migrated).hexdigest(),
        "byte_length": len(migrated), "point_count": header["pointCount"],
        "sections": [{"name": s["name"], "sha256": hashlib.sha256(
            migrated[s["byteOffset"]:s["byteOffset"] + s["byteLength"]]).hexdigest()}
            for s in header["sections"]],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
