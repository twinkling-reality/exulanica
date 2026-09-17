"""Structure capture of the tile runtime bench's test street.

The bench (``web/packages/atlas-react/test/generated-tile-bench/``) is lane 16's test-only street:
a carriageway, a kerb, a footway and a wall with a plinth, a recessed door and a cornice. Its
geometry is exported by ``capture/export-bench.ts``, which imports ``test-street.ts`` and copies the
bench's poses from ``bench.ts`` verbatim. This module rasterises that geometry at:

- the bench's six named eye-level poses, at the bench's own 1440 by 900 and 70 degrees, so every
  structure record lines up pixel for pixel with the bench's rendered picture at that pose;
- a fixed walk along the footway (``FOOTWAY_WALK``), 121 frames at 1280 by 720, for temporal
  stability.

Nothing here edits, serves or imports lane 16's code; it reads two of its files to digest them.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import numpy as np

from exulanica_appearance.canonical import Refused, canonical_bytes, sha256_hex
from exulanica_appearance.capture.raster import Camera, Triangles, rasterize
from exulanica_appearance.structure import LayerStore, build_structure

__all__ = [
    "BENCH_MODULE",
    "BENCH_POSES_FROM",
    "FOOTWAY_WALK",
    "POSE_NAMES",
    "capture_bench",
    "code_sha256",
    "read_geometry",
    "triangles_of",
    "walk_cameras",
]

REPOSITORY: Final = Path(__file__).resolve().parents[4]
BENCH_MODULE: Final = "web/packages/atlas-react/test/generated-tile-bench/test-street.ts"
BENCH_POSES_FROM: Final = "web/packages/atlas-react/test/generated-tile-bench/bench.ts"
POSE_NAMES: Final = ("wall", "kerb", "door", "cornice", "street", "footway")
GEOMETRY_PROFILE: Final = "exulanica.appearance-bench-geometry/v1"

#: The walk, with the reason for every number. 121 frames is Cosmos 3 transfer's default chunk; 24
#: fps is the base_fps its transformer config states; 7 m in 5 s is 1.4 m/s, an ordinary walking
#: pace; 1 m out from the kerb line puts the walker in the footway's first half, 2 m from the wall;
#: the eye is the bench's (1.62 m over the 150 mm footway); looking 8 m ahead and 1.6 m toward the
#: wall keeps the doorway and cornice passing through view; 1280 by 720 is the 720p the video models
#: generate at; 70 degrees is the bench's vertical field of view.
FOOTWAY_WALK: Final = {
    "frames": 121,
    "fps": 24,
    "start_x_um": -5_000_000,
    "end_x_um": 2_000_000,
    "z_um": 1_000_000,
    "eye_um": 1_770_000,
    "look_ahead_um": 8_000_000,
    "look_toward_wall_um": 1_600_000,
    "look_height_um": 1_600_000,
    "width": 1280,
    "height": 720,
}

_POSE_REASON: Final = (
    "the bench's own eyeLevel pose of this name, copied verbatim from bench.ts and checked "
    "against it, at the bench's 1440 by 900, 70 degree vertical field of view and 80 mm near "
    "plane, so this structure lines up pixel for pixel with the bench's picture at that pose"
)
_WALK_REASON: Final = (
    "frame {index} of the footway walk: 121 frames at 24 fps (Cosmos 3 transfer's default chunk "
    "and base fps), 7 m in 5 s along x at 1.4 m/s, 1 m out from the kerb line at the bench's eye "
    "height, looking 8 m ahead and 1.6 m toward the wall, at 720p and the bench's 70 degrees"
)
_REASONS: Final = {
    "crease_tolerance": "1 per cent of a unit normal: above rounding, below any real crease",
    "frame": "the bench's own coordinates, which test-street.ts states",
    "normal_scale": "a unit normal component in int16 with no overflow at plus or minus 1",
    "plane_tolerance_um": "5 mm: far above float noise, far below the smallest real step, the 150 mm kerb",
}


def _strict_json(raw: bytes, where: str) -> Any:
    def refuse(literal: str) -> Any:
        raise Refused(f"{where} holds the fraction {literal}")

    return json.loads(raw, parse_float=refuse)


def read_geometry(path: Path) -> tuple[dict[str, Any], str]:
    """The exported bench geometry and the sha256 of its canonical form."""
    document = _strict_json(path.read_bytes(), str(path))
    if document.get("profile") != GEOMETRY_PROFILE:
        raise Refused(f"{path} is not {GEOMETRY_PROFILE}")
    if sorted(document["poses"]) != sorted(POSE_NAMES):
        raise Refused(f"{path} does not hold exactly the bench's six poses")
    return document, sha256_hex(canonical_bytes(document))


def legend_of(geometry: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"identity": index, "surface": surface["name"], "texture_set": surface["texture_set"]}
        for index, surface in enumerate(geometry["surfaces"], start=1)
    ]


def triangles_of(geometry: dict[str, Any]) -> Triangles:
    a, b, c, normal, identity, st_a, st_b, st_c = ([] for _ in range(8))
    for number, surface in enumerate(geometry["surfaces"], start=1):
        positions = np.array(surface["positions_um"], dtype=np.float64).reshape(-1, 3) / 1e6
        normals = np.array(surface["normals_millionths"], dtype=np.float64).reshape(-1, 3) / 1e6
        st = np.array(surface["surface_mm"], dtype=np.float64).reshape(-1, 2)
        indices = surface["indices"]
        for k in range(0, len(indices), 3):
            i, j, m = indices[k : k + 3]
            a.append(positions[i])
            b.append(positions[j])
            c.append(positions[m])
            normal.append(normals[i])
            identity.append(number)
            st_a.append(st[i])
            st_b.append(st[j])
            st_c.append(st[m])
    return Triangles(
        a=np.array(a),
        b=np.array(b),
        c=np.array(c),
        normal=np.array(normal),
        identity=np.array(identity, dtype=np.int64),
        st_a=np.array(st_a),
        st_b=np.array(st_b),
        st_c=np.array(st_c),
    )


def walk_cameras(near_um: int) -> list[Camera]:
    walk = FOOTWAY_WALK
    last = walk["frames"] - 1
    cameras = []
    for index in range(walk["frames"]):
        x = (
            walk["start_x_um"]
            + ((walk["end_x_um"] - walk["start_x_um"]) * index + last // 2) // last
        )
        cameras.append(
            Camera(
                position_um=(x, walk["eye_um"], walk["z_um"]),
                target_um=(
                    x + walk["look_ahead_um"],
                    walk["look_height_um"],
                    walk["z_um"] + walk["look_toward_wall_um"],
                ),
                width=walk["width"],
                height=walk["height"],
                vertical_fov_degrees=70,
                near_um=near_um,
            )
        )
    return cameras


def code_sha256() -> str:
    """The digest of the capture's own source: every file whose change could change a layer."""
    package = Path(__file__).resolve().parents[1]
    files = [
        package / "capture" / "bench.py",
        package / "capture" / "raster.py",
        package / "structure.py",
        package / "canonical.py",
        package.parent / "capture" / "export-bench.ts",
    ]
    listing = {
        str(path.relative_to(package.parent)): sha256_hex(path.read_bytes()) for path in files
    }
    return sha256_hex(canonical_bytes(listing))


def capture_bench(geometry_path: Path, out: Path) -> Iterator[str]:
    """Capture every pose and every walk frame into ``out``; yield one line per record."""
    geometry, geometry_sha256 = read_geometry(geometry_path)
    source = {
        "geometry_sha256": geometry_sha256,
        "kind": "bench",
        "module": BENCH_MODULE,
        "module_sha256": sha256_hex((REPOSITORY / BENCH_MODULE).read_bytes()),
        "poses_from": BENCH_POSES_FROM,
        "poses_from_sha256": sha256_hex((REPOSITORY / BENCH_POSES_FROM).read_bytes()),
    }
    (out / "geometry").mkdir(parents=True, exist_ok=True)
    (out / "geometry" / f"{geometry_sha256}.json").write_bytes(canonical_bytes(geometry))
    legend = legend_of(geometry)
    triangles = triangles_of(geometry)
    store = LayerStore(out / "layers")
    code = code_sha256()
    bench_camera = geometry["camera"]
    index: dict[str, Any] = {"geometry_sha256": geometry_sha256, "poses": {}, "walk": []}

    jobs: list[tuple[str, Camera, str]] = []
    for name in POSE_NAMES:
        pose = geometry["poses"][name]
        camera = Camera(
            position_um=tuple(pose["position_um"]),
            target_um=tuple(pose["target_um"]),
            width=bench_camera["width"],
            height=bench_camera["height"],
            vertical_fov_degrees=bench_camera["vertical_fov_degrees"],
            near_um=bench_camera["near_um"],
        )
        jobs.append((name, camera, _POSE_REASON))
    for number, camera in enumerate(walk_cameras(bench_camera["near_um"])):
        jobs.append((f"footway-walk-{number:03d}", camera, _WALK_REASON.format(index=number)))

    for name, camera, camera_reason in jobs:
        layers = rasterize(triangles, camera)
        raw = build_structure(
            source=source,
            camera=camera,
            name=name,
            legend=legend,
            layers=layers,
            code_sha256=code,
            reasons={**_REASONS, "camera": camera_reason},
            store=store,
        )
        digest = sha256_hex(raw)
        (out / "structures").mkdir(parents=True, exist_ok=True)
        (out / "structures" / f"{digest}.json").write_bytes(raw)
        entry = {"name": name, "structure_sha256": digest}
        if name.startswith("footway-walk-"):
            index["walk"].append(entry)
        else:
            index["poses"][name] = entry
        hit = int((layers.identity > 0).sum())
        yield f"{name} {digest} pixels_hit={hit}"
    (out / "index.json").write_text(json.dumps(index, indent=1, sort_keys=True) + "\n")
