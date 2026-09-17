"""Does a look stay still as the camera moves? Measured by exact reprojection, with no model.

Consecutive frames of a camera path see the same static street. With the exact depth of frame a
and the exact cameras of both frames, every pixel of a is carried to where frame b sees the same
point. Where b really sees that point (its exact depth there agrees and it is the same identity),
the two frames' luminance there should match, apart from view-dependent light. The error is the
flicker a person sees: painted detail that swims, appears or vanishes between frames.

Pixels within ``TOLERANCE_PX`` of a geometry edge in a are left out, because sampling across an
edge measures the resampling, not the look. The procedural look is measured the same way, and it is
the baseline a generated look is compared with.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from exulanica_appearance.capture.raster import Camera
from exulanica_appearance.metrics.edges import TOLERANCE_PX, dilate, luminance

__all__ = ["COVISIBLE_TOLERANCE_PERMILLE", "COVISIBLE_TOLERANCE_UM", "reprojection_error"]

#: Frame b sees the same point when its exact depth agrees within 5 mm or 1 per cent, whichever is
#: larger: rounding to a pixel moves a grazing ground point by more than a fixed millimetre budget.
COVISIBLE_TOLERANCE_UM: Final = 5000
COVISIBLE_TOLERANCE_PERMILLE: Final = 10


def camera_of(record: Mapping[str, Any]) -> Camera:
    c = record["camera"]
    return Camera(
        position_um=tuple(c["position_um"]),
        target_um=tuple(c["target_um"]),
        width=c["width"],
        height=c["height"],
        vertical_fov_degrees=c["vertical_fov_degrees"],
        near_um=c["near_um"],
    )


def _bilinear(
    image: NDArray[np.float64], rows: NDArray[np.float64], columns: NDArray[np.float64]
) -> NDArray[np.float64]:
    r0 = np.floor(rows).astype(np.int64)
    c0 = np.floor(columns).astype(np.int64)
    r1 = np.minimum(r0 + 1, image.shape[0] - 1)
    c1 = np.minimum(c0 + 1, image.shape[1] - 1)
    fr = rows - r0
    fc = columns - c0
    top = image[r0, c0] * (1 - fc) + image[r0, c1] * fc
    bottom = image[r1, c0] * (1 - fc) + image[r1, c1] * fc
    return top * (1 - fr) + bottom * fr


def reprojection_error(
    rgb_a: NDArray[np.uint8],
    rgb_b: NDArray[np.uint8],
    record_a: Mapping[str, Any],
    record_b: Mapping[str, Any],
    layers_a: Mapping[str, NDArray[Any]],
    layers_b: Mapping[str, NDArray[Any]],
) -> dict[str, int]:
    camera_a = camera_of(record_a)
    camera_b = camera_of(record_b)
    dx, dy, dz = camera_a.directions()
    origin_a = camera_a.origin()
    depth_a = layers_a["depth"].astype(np.float64) / 1e6
    found = layers_a["depth"] > 0
    points = [origin_a[i] + depth_a * d for i, d in enumerate((dx, dy, dz))]

    right, up, forward = camera_b.basis()
    origin_b = camera_b.origin()
    v = [points[i] - origin_b[i] for i in range(3)]
    z = v[0] * forward[0] + v[1] * forward[1] + v[2] * forward[2]
    half = math.tan(math.radians(camera_b.vertical_fov_degrees) / 2)
    aspect = camera_b.width / camera_b.height
    safe_z = np.where(z > 0, z, 1.0)
    x_ndc = (v[0] * right[0] + v[1] * right[1] + v[2] * right[2]) / (safe_z * half * aspect)
    y_ndc = (v[0] * up[0] + v[1] * up[1] + v[2] * up[2]) / (safe_z * half)
    columns = (x_ndc + 1) / 2 * camera_b.width - 0.5
    rows = (1 - y_ndc) / 2 * camera_b.height - 0.5
    inside = (
        found
        & (z * 1e6 > camera_b.near_um)
        & (columns >= 0)
        & (columns <= camera_b.width - 1)
        & (rows >= 0)
        & (rows <= camera_b.height - 1)
    )
    away = ~dilate(layers_a["edges"] > 0, TOLERANCE_PX)
    nearest_r = np.clip(np.rint(np.where(inside, rows, 0)).astype(np.int64), 0, camera_b.height - 1)
    nearest_c = np.clip(
        np.rint(np.where(inside, columns, 0)).astype(np.int64), 0, camera_b.width - 1
    )
    depth_b = layers_b["depth"][nearest_r, nearest_c].astype(np.float64)
    z_um = z * 1e6
    tolerance = np.maximum(COVISIBLE_TOLERANCE_UM, z_um * COVISIBLE_TOLERANCE_PERMILLE / 1000)
    same = layers_b["identity"][nearest_r, nearest_c] == layers_a["identity"]
    covisible = inside & away & (depth_b > 0) & (np.abs(depth_b - z_um) <= tolerance) & same

    lum_a = luminance(rgb_a)
    lum_b = luminance(rgb_b)
    sampled = _bilinear(lum_b, np.where(covisible, rows, 0), np.where(covisible, columns, 0))
    error = np.abs(lum_a - sampled)[covisible]
    counted = int(covisible.sum())
    if counted == 0:
        return {
            "covisible_pixels": 0,
            "mean_milli_levels": 0,
            "p50_milli_levels": 0,
            "p95_milli_levels": 0,
        }
    return {
        "covisible_pixels": counted,
        "mean_milli_levels": int(np.rint(error.mean() * 1000)),
        "p50_milli_levels": int(np.rint(np.percentile(error, 50) * 1000)),
        "p95_milli_levels": int(np.rint(np.percentile(error, 95) * 1000)),
    }
