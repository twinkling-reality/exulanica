"""``exulanica.appearance-structure/v1``: exact structure at one camera, as a data object.

A structure record says where the geometry came from (by digest), the camera, what every identity
in the picture is (a surface and the texture set the world dresses it with), and each layer the
rasteriser produced, by name, encoding and the sha256 of its raw little-endian bytes. Every
parameter the capture fixes carries its reason.

Layers are stored by digest in a content store, zlib-compressed on disk. The digest is always of
the raw bytes, so the compressor never enters an identity. A model is conditioned on encodings
derived from these layers (``capture.encode``), and a generated pixel is attributable to a record
through the ``identity`` layer of the structure it was conditioned on.
"""

from __future__ import annotations

import re
import zlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from exulanica_appearance.canonical import (
    Refused,
    canonical_bytes,
    exact_keys,
    is_count,
    is_sha256,
    is_text,
    parse_canonical,
    sha256_hex,
)
from exulanica_appearance.capture.raster import (
    CREASE_TOLERANCE,
    LAYER_DTYPES,
    NORMAL_SCALE,
    PLANE_TOLERANCE_UM,
    Camera,
    Layers,
)

__all__ = [
    "STRUCTURE_PROFILE",
    "LayerStore",
    "build_structure",
    "load_layers",
    "read_structure",
]

STRUCTURE_PROFILE: Final = "exulanica.appearance-structure/v1"
_KEYS: Final = (
    "camera",
    "code_sha256",
    "frame",
    "layers",
    "legend",
    "parameters",
    "profile",
    "reasons",
    "source",
    "truth",
)
_CAMERA_KEYS: Final = (
    "height",
    "name",
    "near_um",
    "position_um",
    "target_um",
    "up",
    "vertical_fov_degrees",
    "width",
)
_BENCH_SOURCE_KEYS: Final = (
    "geometry_sha256",
    "kind",
    "module",
    "module_sha256",
    "poses_from",
    "poses_from_sha256",
)
_PARAMETERS: Final = {
    "crease_tolerance": CREASE_TOLERANCE,
    "normal_scale": NORMAL_SCALE,
    "plane_tolerance_um": PLANE_TOLERANCE_UM,
}
_UNITS: Final = {
    "depth": "micrometres along the view axis; 0 where nothing is hit",
    "normal": "world-space unit normal times normal_scale, x y z interleaved",
    "identity": "legend index; 0 where nothing is hit",
    "surface_s": "surface coordinate s in micrometres; 0 where nothing is hit",
    "surface_t": "surface coordinate t in micrometres; 0 where nothing is hit",
    "edges": "bit 1 identity change, bit 2 crease, bit 4 step, toward the right or lower neighbour",
}
#: Every reason a structure record must carry, one per fixed choice.
REASON_KEYS: Final = ("camera", "crease_tolerance", "frame", "normal_scale", "plane_tolerance_um")
_NAME: Final = re.compile(r"[a-z0-9][a-z0-9-]*")
_SET: Final = re.compile(r"[a-z0-9][a-z0-9.-]*")


class LayerStore:
    """Raw layer bytes by sha256, zlib-compressed on disk; the digest is of the raw bytes."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def put(self, raw: bytes) -> str:
        digest = sha256_hex(raw)
        path = self.directory / f"{digest}.bin.z"
        if not path.exists():
            self.directory.mkdir(parents=True, exist_ok=True)
            partial = path.with_suffix(".partial")
            partial.write_bytes(zlib.compress(raw, 6))
            partial.replace(path)
        return digest

    def get(self, digest: str, byte_length: int) -> bytes:
        raw = zlib.decompress((self.directory / f"{digest}.bin.z").read_bytes())
        if len(raw) != byte_length or sha256_hex(raw) != digest:
            raise Refused(f"layer {digest} in {self.directory} does not have its recorded digest")
        return raw


def build_structure(
    *,
    source: Mapping[str, str],
    camera: Camera,
    name: str,
    legend: Sequence[Mapping[str, Any]],
    layers: Layers,
    code_sha256: str,
    reasons: Mapping[str, str],
    store: LayerStore,
) -> bytes:
    entries = []
    for layer, (dtype, components) in LAYER_DTYPES.items():
        raw = layers.layer_bytes(layer)
        entries.append(
            {
                "byte_length": len(raw),
                "components": components,
                "dtype": _dtype_name(dtype),
                "name": layer,
                "sha256": store.put(raw),
                "unit": _UNITS[layer],
            }
        )
    document = {
        "camera": {
            "height": camera.height,
            "name": name,
            "near_um": camera.near_um,
            "position_um": list(camera.position_um),
            "target_um": list(camera.target_um),
            "up": [0, 1, 0],
            "vertical_fov_degrees": camera.vertical_fov_degrees,
            "width": camera.width,
        },
        "code_sha256": code_sha256,
        "frame": "bench: metres, +Y up, the street along X, the wall facing -Z",
        "layers": entries,
        "legend": [dict(entry) for entry in legend],
        "parameters": dict(_PARAMETERS),
        "profile": STRUCTURE_PROFILE,
        "reasons": dict(reasons),
        "source": dict(source),
        "truth": "invented",
    }
    raw = canonical_bytes(document)
    read_structure(raw)
    return raw


def _dtype_name(dtype: str) -> str:
    return {
        "<u4": "uint32le",
        "<i2": "int16le",
        "<u2": "uint16le",
        "<i4": "int32le",
        "u1": "uint8",
    }[dtype]


def read_structure(raw: bytes) -> dict[str, Any]:
    where = "the structure record"
    document = exact_keys(parse_canonical(raw, where), _KEYS, where)
    if document["profile"] != STRUCTURE_PROFILE or document["truth"] != "invented":
        raise Refused(f"{where}: profile is {STRUCTURE_PROFILE} and truth is invented")
    source = exact_keys(document["source"], _BENCH_SOURCE_KEYS, f"{where}: source")
    if source["kind"] != "bench":
        raise Refused(f"{where}: source kind is bench, the only source this version captures")
    for key in ("geometry_sha256", "module_sha256", "poses_from_sha256"):
        if not is_sha256(source[key]):
            raise Refused(f"{where}: source {key} is 64 lowercase hex")
    if not is_text(source["module"]) or not is_text(source["poses_from"]):
        raise Refused(f"{where}: source names its module and pose file by repository path")
    camera = exact_keys(document["camera"], _CAMERA_KEYS, f"{where}: camera")
    if not isinstance(camera["name"], str) or not _NAME.fullmatch(camera["name"]):
        raise Refused(f"{where}: camera name is lowercase words joined by hyphens")
    for key in ("position_um", "target_um"):
        value = camera[key]
        if not (
            isinstance(value, list)
            and len(value) == 3
            and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
        ):
            raise Refused(f"{where}: camera {key} is three integers")
    if camera["position_um"] == camera["target_um"]:
        raise Refused(f"{where}: camera looks at a target away from its position")
    if camera["up"] != [0, 1, 0]:
        raise Refused(f"{where}: camera up is +Y")
    if not (is_count(camera["width"], 1) and is_count(camera["height"], 1)):
        raise Refused(f"{where}: camera width and height are positive")
    if not (is_count(camera["vertical_fov_degrees"], 1) and camera["vertical_fov_degrees"] < 180):
        raise Refused(f"{where}: camera vertical_fov_degrees is between 1 and 179")
    if not is_count(camera["near_um"], 1):
        raise Refused(f"{where}: camera near_um is positive")
    legend = document["legend"]
    if not isinstance(legend, list) or not legend:
        raise Refused(f"{where}: legend lists at least one identity")
    for index, entry in enumerate(legend, start=1):
        item = exact_keys(
            entry, ("identity", "surface", "texture_set"), f"{where}: legend[{index - 1}]"
        )
        if item["identity"] != index:
            raise Refused(f"{where}: legend identities run 1, 2, 3 and so on, in order")
        if not isinstance(item["surface"], str) or not _NAME.fullmatch(item["surface"]):
            raise Refused(f"{where}: legend surface is lowercase words joined by hyphens")
        if not isinstance(item["texture_set"], str) or not _SET.fullmatch(item["texture_set"]):
            raise Refused(f"{where}: legend texture_set is a texture set id")
    if document["parameters"] != _PARAMETERS:
        raise Refused(f"{where}: parameters are the rasteriser's own, {_PARAMETERS}")
    reasons = document["reasons"]
    if (
        not isinstance(reasons, dict)
        or set(reasons) != set(REASON_KEYS)
        or not all(is_text(text) for text in reasons.values())
    ):
        raise Refused(f"{where}: reasons give a reason for exactly {', '.join(REASON_KEYS)}")
    if not is_sha256(document["code_sha256"]) or not is_text(document["frame"]):
        raise Refused(f"{where}: code_sha256 is 64 lowercase hex and frame is stated")
    layers = document["layers"]
    if not isinstance(layers, list) or [
        entry.get("name") for entry in layers if isinstance(entry, dict)
    ] != list(LAYER_DTYPES):
        raise Refused(f"{where}: layers are exactly {', '.join(LAYER_DTYPES)}, in that order")
    pixels = camera["width"] * camera["height"]
    for entry in layers:
        item = exact_keys(
            entry,
            ("byte_length", "components", "dtype", "name", "sha256", "unit"),
            f"{where}: layer",
        )
        dtype, components = LAYER_DTYPES[item["name"]]
        size = np.dtype(dtype).itemsize
        if (
            item["dtype"] != _dtype_name(dtype)
            or item["components"] != components
            or item["byte_length"] != pixels * components * size
            or item["unit"] != _UNITS[item["name"]]
            or not is_sha256(item["sha256"])
        ):
            raise Refused(
                f"{where}: layer {item['name']} is not {_dtype_name(dtype)} over the camera's pixels"
            )
    return document


def load_layers(document: Mapping[str, Any], store: LayerStore) -> dict[str, NDArray[Any]]:
    camera = document["camera"]
    out: dict[str, NDArray[Any]] = {}
    for entry in document["layers"]:
        dtype, components = LAYER_DTYPES[entry["name"]]
        raw = store.get(entry["sha256"], entry["byte_length"])
        array = np.frombuffer(raw, dtype=np.dtype(dtype))
        shape = (camera["height"], camera["width"]) + ((components,) if components > 1 else ())
        out[entry["name"]] = array.reshape(shape)
    return out
