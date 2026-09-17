"""Measurement reports, as canonical JSON: a look's frames against structure, and texture sets.

``measure_frames`` reads a structure capture (``capture bench``) and a directory of frames rendered
or generated at the same cameras, named by camera (``<camera name>.png``), and reports per pose the
edge agreement and the per-surface measurements, and along the walk the reprojection error between
each pair of consecutive frames. ``measure_published_textures`` reports every set the texture
manifest pins. Every figure is an integer in a stated unit; the method and its constants travel with
the numbers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

import numpy as np
from PIL import Image

from exulanica_appearance.canonical import Refused, canonical_bytes, sha256_hex
from exulanica_appearance.containers import read_container
from exulanica_appearance.metrics import edges, regions, stability, textures
from exulanica_appearance.structure import LayerStore, load_layers, read_structure

__all__ = ["FRAMES_PROFILE", "TEXTURES_PROFILE", "measure_frames", "measure_published_textures"]

FRAMES_PROFILE: Final = "exulanica.appearance-frame-measurements/v1"
TEXTURES_PROFILE: Final = "exulanica.appearance-texture-measurements/v1"


def _frame(path: Path, width: int, height: int) -> tuple[np.ndarray, dict[str, str]]:
    raw_file = path.read_bytes()
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"))
    if rgb.shape[:2] != (height, width):
        raise Refused(
            f"{path} is {rgb.shape[1]} by {rgb.shape[0]}, not its camera's {width} by {height}"
        )
    return rgb, {
        "file_sha256": hashlib.sha256(raw_file).hexdigest(),
        "pixels_sha256": hashlib.sha256(np.ascontiguousarray(rgb).tobytes()).hexdigest(),
    }


def measure_frames(structure_dir: Path, frames_dir: Path) -> bytes:
    index = json.loads((structure_dir / "index.json").read_bytes())
    store = LayerStore(structure_dir / "layers")

    def load(entry: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        raw = (structure_dir / "structures" / f"{entry['structure_sha256']}.json").read_bytes()
        record = read_structure(raw)
        return record, load_layers(record, store)

    poses = {}
    for name, entry in sorted(index["poses"].items()):
        path = frames_dir / f"{name}.png"
        if not path.exists():
            continue
        record, layers = load(entry)
        rgb, digests = _frame(path, record["camera"]["width"], record["camera"]["height"])
        detected = edges.image_edges(rgb)
        poses[name] = {
            "edges": edges.edge_agreement(detected, layers["edges"]),
            "frame": digests,
            "regions": regions.region_measurements(
                rgb, layers["identity"], layers["edges"], detected, record["legend"]
            ),
            "structure_sha256": entry["structure_sha256"],
        }

    pairs = []
    previous = None
    for entry in index["walk"]:
        path = frames_dir / f"{entry['name']}.png"
        if not path.exists():
            previous = None
            continue
        record, layers = load(entry)
        rgb, digests = _frame(path, record["camera"]["width"], record["camera"]["height"])
        current = (entry, record, layers, rgb, digests)
        if previous is not None:
            error = stability.reprojection_error(
                previous[3], rgb, previous[1], record, previous[2], layers
            )
            pairs.append({"from": previous[0]["name"], "to": entry["name"], **error})
        previous = current
    walk: dict[str, Any] = {"pairs": pairs}
    if pairs:
        means = np.array([pair["mean_milli_levels"] for pair in pairs])
        p95s = np.array([pair["p95_milli_levels"] for pair in pairs])
        walk["summary"] = {
            "mean_of_means_milli_levels": int(np.rint(means.mean())),
            "median_p95_milli_levels": int(np.rint(np.median(p95s))),
            "worst_p95_milli_levels": int(p95s.max()),
        }
    report = {
        "method": {
            "covisible_tolerance": f"{stability.COVISIBLE_TOLERANCE_UM} um or {stability.COVISIBLE_TOLERANCE_PERMILLE} per mille of depth, whichever is larger, and the same identity",
            "edge_step_levels": edges.EDGE_STEP_LEVELS,
            "luminance": "Rec. 709 weights over stored sRGB bytes",
            "tolerance_px": edges.TOLERANCE_PX,
        },
        "poses": poses,
        "profile": FRAMES_PROFILE,
        "structure_geometry_sha256": index["geometry_sha256"],
        "walk": walk,
    }
    return canonical_bytes(report)


def measure_published_textures(repository: Path) -> bytes:
    manifest_raw = (repository / "assets" / "textures" / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    sets = []
    for entry in manifest["sets"]:
        raw = (
            repository / "assets" / "textures" / "blobs" / f"{entry['content_sha256']}.ltex"
        ).read_bytes()
        header, maps = read_container(raw, entry)
        width = header["resolution"]["width"]
        height = header["resolution"]["height"]
        drawn = [name for name in maps if name != "height"]
        parameters = header.get("parameters", {})
        sets.append(
            {
                "base_color": {
                    "dominant_cycles": textures.dominant_cycles(maps["base_color"]),
                    "low_frequency_share_ppm": textures.low_frequency_share_ppm(maps["base_color"]),
                },
                "content_sha256": entry["content_sha256"],
                "decoded_bytes_drawn_maps": textures.decoded_bytes(width, height, len(drawn)),
                "extent_mm": header["extent_mm"],
                "height": {"dominant_cycles": textures.dominant_cycles(maps["height"])}
                if "height" in maps
                else {},
                "recipe_modules": {
                    key: parameters[key]
                    for key in sorted(parameters)
                    if key in ("courses", "units_per_course", "units_per_tile", "rows", "columns")
                    and isinstance(parameters[key], int)
                },
                "resolution": header["resolution"],
                "seams_ppm": {
                    name: textures.seam_ratio_ppm(pixels) for name, pixels in maps.items()
                },
                "set_id": entry["set_id"],
                "texel_pitch_um": {
                    "u": textures.texel_pitch_um(header["extent_mm"]["u"], width),
                    "v": textures.texel_pitch_um(header["extent_mm"]["v"], height),
                },
                "version": entry["version"],
            }
        )
    report = {
        "manifest_sha256": sha256_hex(manifest_raw),
        "method": {
            "decoded_bytes": "RGBA8 with a full mip chain for every map but height, as lane 16's binding uploads",
            "dominant_cycles": "strongest period of the row-mean and column-mean luminance profiles, cycles per tile",
            "low_frequency_cycles": textures.LOW_FREQUENCY_CYCLES,
            "seams": "wrap difference over the mean of the two neighbour differences beside it, parts per million",
        },
        "profile": TEXTURES_PROFILE,
        "sets": sets,
    }
    return canonical_bytes(report)
