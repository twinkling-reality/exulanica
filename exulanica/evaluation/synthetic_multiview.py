"""Deterministic overlapping views of one explicit synthetic 3D scene.

The scene is a textured three-sided room plus offset blocks, sampled as coloured surface points.
Every view projects the same points from a known camera, so overlap, parallax, intrinsics and
extrinsics are properties of one scene rather than similarities between independent generators.
The output is a plumbing fixture. It is not evidence of performance on photographs.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from exulanica.canonical import canonical_json

__all__ = [
    "SYNTHETIC_MULTIVIEW_PROFILE",
    "SyntheticFixture",
    "SyntheticFixtureParameters",
    "generate_synthetic_multiview",
]

SYNTHETIC_MULTIVIEW_PROFILE: Final = "exulanica.synthetic-multiview/v1"
_GENERATOR_VERSION: Final = 1
_BACKGROUND: Final = 238


@dataclass(frozen=True, slots=True)
class SyntheticFixtureParameters:
    seed: int = 20260904
    width: int = 800
    height: int = 600
    view_count: int = 8
    fov_y_millidegrees: int = 50000
    surface_step_micrometres: int = 35000
    sprite_size_micrometres: int = 48000
    jpeg_quality: int = 94

    def validate(self) -> None:
        if self.width < 320 or self.height < 240:
            raise ValueError("synthetic fixture resolution is too small for feature recovery")
        if self.view_count < 3:
            raise ValueError("synthetic multi-view fixture needs at least three views")
        if not 10000 <= self.fov_y_millidegrees <= 120000:
            raise ValueError("synthetic fixture vertical field of view is invalid")
        if self.surface_step_micrometres <= 0 or self.sprite_size_micrometres <= 0:
            raise ValueError("synthetic fixture surface sampling must be positive")
        if not 1 <= self.jpeg_quality <= 100:
            raise ValueError("synthetic fixture JPEG quality is invalid")


@dataclass(frozen=True, slots=True)
class SyntheticFixture:
    root: Path
    image_directory: Path
    source_manifest_path: Path
    camera_manifest_path: Path
    scene_manifest_path: Path
    source_manifest_digest: str
    camera_manifest_digest: str
    scene_manifest_digest: str


def _modules() -> tuple[Any, Any, str]:
    try:
        import numpy
        from PIL import Image
        from PIL import __version__ as pillow_version
    except ImportError as error:  # pragma: no cover - evaluation extra controls availability
        raise RuntimeError("synthetic fixture generation needs numpy and Pillow") from error
    return numpy, Image, pillow_version


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_record(path: Path, record: dict[str, Any]) -> str:
    payload = canonical_json(record)
    digest = _digest(payload)
    path.write_bytes(
        canonical_json(
            {
                "profile": "exulanica.digest-bound-record/v1",
                "record": record,
                "record_sha256": digest,
            }
        )
    )
    return digest


def _texture(np: Any, a: Any, b: Any, surface: int, seed: int) -> Any:
    ia = np.rint(a * 1000).astype(np.int64)
    ib = np.rint(b * 1000).astype(np.int64)
    value = (ia * 73856093) ^ (ib * 19349663) ^ (surface * 83492791) ^ seed
    value ^= value >> 13
    value *= 1274126177
    checker = ((ia // 140) + (ib // 140) + surface) & 1
    return np.stack(
        [
            35 + ((value >> 2) & 159) + checker * 35,
            30 + ((value >> 10) & 159) + (1 - checker) * 25,
            40 + ((value >> 18) & 149) + checker * 20,
        ],
        axis=1,
    ).clip(0, 255).astype(np.uint8)


def _grid(np: Any, start: float, stop: float, step: float) -> Any:
    count = math.floor((stop - start) / step) + 1
    return np.linspace(start, stop, count, dtype=np.float64)


def _surface(
    np: Any,
    *,
    axis: int,
    fixed: float,
    a_axis: int,
    a_range: tuple[float, float],
    b_axis: int,
    b_range: tuple[float, float],
    step: float,
    surface: int,
    seed: int,
) -> tuple[Any, Any]:
    a, b = _grid(np, *a_range, step), _grid(np, *b_range, step)
    aa, bb = np.meshgrid(a, b, indexing="xy")
    points = np.empty((aa.size, 3), dtype=np.float64)
    points[:, axis] = fixed
    points[:, a_axis] = aa.ravel()
    points[:, b_axis] = bb.ravel()
    return points, _texture(np, aa.ravel(), bb.ravel(), surface, seed)


def _scene(np: Any, params: SyntheticFixtureParameters) -> tuple[Any, Any, dict[str, Any]]:
    step = params.surface_step_micrometres / 1_000_000
    definitions = [
        (2, -7.0, 0, (-4.2, 4.2), 1, (-2.4, 2.6)),
        (1, -2.4, 0, (-4.2, 4.2), 2, (-10.0, -2.0)),
        (0, -4.2, 1, (-2.4, 2.6), 2, (-10.0, -2.0)),
        (0, 4.2, 1, (-2.4, 2.6), 2, (-10.0, -2.0)),
        (2, -4.8, 0, (-2.3, -0.5), 1, (-2.4, 0.3)),
        (2, -5.7, 0, (0.5, 2.6), 1, (-2.4, 1.5)),
        (1, 0.3, 0, (-2.3, -0.5), 2, (-5.8, -4.8)),
        (1, 1.5, 0, (0.5, 2.6), 2, (-6.7, -5.7)),
    ]
    points, colours = [], []
    for index, (axis, fixed, a_axis, a_range, b_axis, b_range) in enumerate(definitions):
        surface_points, surface_colours = _surface(
            np,
            axis=axis,
            fixed=fixed,
            a_axis=a_axis,
            a_range=a_range,
            b_axis=b_axis,
            b_range=b_range,
            step=step,
            surface=index,
            seed=params.seed,
        )
        points.append(surface_points)
        colours.append(surface_colours)
    joined = np.concatenate(points), np.concatenate(colours)
    description = {
        "coordinate_convention": "+x right, +y up, camera looks toward -z",
        "generator_version": _GENERATOR_VERSION,
        "profile": SYNTHETIC_MULTIVIEW_PROFILE,
        "seed": params.seed,
        "surface_count": len(definitions),
        "surface_definitions_millimetres": [
            {
                "axis": axis,
                "fixed": round(fixed * 1000),
                "a_axis": a_axis,
                "a_range": [round(value * 1000) for value in a_range],
                "b_axis": b_axis,
                "b_range": [round(value * 1000) for value in b_range],
            }
            for axis, fixed, a_axis, a_range, b_axis, b_range in definitions
        ],
    }
    return joined[0], joined[1], description


def _cameras(np: Any, params: SyntheticFixtureParameters) -> list[tuple[Any, Any, Any, Any]]:
    target = np.array([0.0, -0.1, -6.5])
    cameras = []
    for index in range(params.view_count):
        u = (index / (params.view_count - 1)) * 2 - 1
        eye = np.array([1.35 * u, 0.12 * math.sin(index * 1.1), -0.2 - 0.5 * (1 - u * u)])
        forward = target - eye
        forward /= np.linalg.norm(forward)
        right = np.cross(forward, np.array([0.0, 1.0, 0.0]))
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)
        cameras.append((eye, right, up, forward))
    return cameras


_GLYPHS: Final = {
    "S": (30, 16, 16, 14, 1, 1, 30),
    "Y": (17, 17, 10, 4, 4, 4, 4),
    "N": (17, 25, 21, 19, 17, 17, 17),
    "T": (31, 4, 4, 4, 4, 4, 4),
    "H": (17, 17, 17, 31, 17, 17, 17),
    "E": (31, 16, 16, 30, 16, 16, 31),
    "I": (31, 4, 4, 4, 4, 4, 31),
    "C": (15, 16, 16, 16, 16, 16, 15),
}


def _mark_synthetic(canvas: Any) -> None:
    canvas[:28, :, :] = (18, 22, 31)
    scale, x0, y0 = 3, 12, 3
    for character in "SYNTHETIC":
        for row, bits in enumerate(_GLYPHS[character]):
            for column in range(5):
                if bits & (1 << (4 - column)):
                    canvas[
                        y0 + row * scale : y0 + (row + 1) * scale,
                        x0 + column * scale : x0 + (column + 1) * scale,
                    ] = (255, 190, 35)
        x0 += 6 * scale


def _render(
    np: Any,
    points: Any,
    colours: Any,
    camera: tuple[Any, Any, Any, Any],
    params: SyntheticFixtureParameters,
) -> tuple[Any, int]:
    eye, right, up, forward = camera
    relative = points - eye
    local = np.stack([relative @ right, relative @ up, relative @ forward], axis=1)
    keep = local[:, 2] > 0.1
    local, visible = local[keep], colours[keep]
    fov = math.radians(params.fov_y_millidegrees / 1000)
    focal = (params.height / 2) / math.tan(fov / 2)
    x = local[:, 0] * focal / local[:, 2] + params.width / 2
    y = -local[:, 1] * focal / local[:, 2] + params.height / 2
    size = np.minimum(
        (params.sprite_size_micrometres / 1_000_000) * focal / local[:, 2], 10.0
    )
    canvas = np.full((params.height, params.width, 3), _BACKGROUND, np.uint8)
    for point in np.argsort(-local[:, 2]):
        radius = size[point] / 2
        x0, x1 = math.floor(x[point] - radius), math.ceil(x[point] + radius)
        y0, y1 = math.floor(y[point] - radius), math.ceil(y[point] + radius)
        if x1 <= 0 or y1 <= 28 or x0 >= params.width or y0 >= params.height:
            continue
        canvas[max(28, y0) : min(params.height, y1), max(0, x0) : min(params.width, x1)] = (
            visible[point]
        )
    _mark_synthetic(canvas)
    return canvas, int(keep.sum())


def _decimal_matrix(values: Any) -> list[list[str]]:
    return [[f"{float(value):.12f}" for value in row] for row in values]


def generate_synthetic_multiview(
    root: Path, params: SyntheticFixtureParameters | None = None
) -> SyntheticFixture:
    """Generate exact images plus digest-bound scene, camera and source manifests."""
    params = params or SyntheticFixtureParameters()
    params.validate()
    np, Image, pillow_version = _modules()
    root.mkdir(parents=True, exist_ok=True)
    image_directory = root / "images"
    image_directory.mkdir(exist_ok=True)
    if any(image_directory.iterdir()):
        raise ValueError("synthetic fixture output image directory must be empty")

    points, colours, scene = _scene(np, params)
    scene["parameters"] = asdict(params)
    scene["point_count"] = len(points)
    scene["runtime"] = {"numpy": np.__version__, "pillow": pillow_version}
    scene_path = root / "scene-manifest.json"
    scene_digest = _write_record(scene_path, scene)

    fov = math.radians(params.fov_y_millidegrees / 1000)
    focal = (params.height / 2) / math.tan(fov / 2)
    image_records, camera_records = [], []
    for index, camera in enumerate(_cameras(np, params)):
        canvas, points_in_front = _render(np, points, colours, camera, params)
        path = image_directory / f"view_{index:02d}.jpg"
        image = Image.fromarray(canvas)
        exif = Image.Exif()
        exif[270] = "SYNTHETIC EXULANICA MULTI-VIEW FIXTURE"
        exif[305] = SYNTHETIC_MULTIVIEW_PROFILE
        image.save(
            path,
            format="JPEG",
            quality=params.jpeg_quality,
            subsampling=0,
            optimize=False,
            progressive=False,
            exif=exif,
        )
        data = path.read_bytes()
        image_records.append(
            {"bytes": len(data), "path": path.name, "sha256": _digest(data)}
        )
        eye, right, up, forward = camera
        world_from_camera = np.stack([right, -up, forward], axis=1)
        camera_from_world = world_from_camera.T
        translation = -camera_from_world @ eye
        camera_records.append(
            {
                "camera_center_metres": [f"{float(value):.12f}" for value in eye],
                "camera_from_world_rotation": _decimal_matrix(camera_from_world),
                "camera_from_world_translation_metres": [
                    f"{float(value):.12f}" for value in translation
                ],
                "image": path.name,
                "points_in_front": points_in_front,
                "world_from_camera_rotation": _decimal_matrix(world_from_camera),
            }
        )

    camera_record = {
        "camera_convention": "OpenCV +x right, +y down, +z forward",
        "cx_pixels": f"{params.width / 2:.12f}",
        "cy_pixels": f"{params.height / 2:.12f}",
        "fx_pixels": f"{focal:.12f}",
        "fy_pixels": f"{focal:.12f}",
        "height": params.height,
        "profile": "exulanica.synthetic-camera-manifest/v1",
        "scene_manifest_sha256": scene_digest,
        "views": camera_records,
        "width": params.width,
    }
    camera_path = root / "camera-manifest.json"
    camera_digest = _write_record(camera_path, camera_record)
    source_record = {
        "camera_manifest_sha256": camera_digest,
        "corpus_class": "synthetic",
        "generator_profile": SYNTHETIC_MULTIVIEW_PROFILE,
        "images": image_records,
        "notice": "SYNTHETIC FIXTURE. NOT PERSONAL MEDIA OR REAL-WORLD QUALITY EVIDENCE.",
        "profile": "exulanica.synthetic-source-manifest/v1",
        "scene_manifest_sha256": scene_digest,
    }
    source_path = root / "source-manifest.json"
    source_digest = _write_record(source_path, source_record)
    return SyntheticFixture(
        root=root,
        image_directory=image_directory,
        source_manifest_path=source_path,
        camera_manifest_path=camera_path,
        scene_manifest_path=scene_path,
        source_manifest_digest=source_digest,
        camera_manifest_digest=camera_digest,
        scene_manifest_digest=scene_digest,
    )
