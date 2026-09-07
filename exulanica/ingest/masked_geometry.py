"""The check that makes masking real: did a hidden person leave any geometry behind?

The design note asks for exactly this and says why it matters. Masking a source is a claim about
what the trainer saw, and a claim about an input is not evidence about an output. This counts, in
the trained scene itself, how many Gaussians of meaningful opacity project into a region that was
supposed to be masked in the view they are seen from. The honest number is zero, and a number is
what goes in the evaluation record rather than an assurance.

**It errs toward reporting more, never less.** Three choices all lean the same way. A Gaussian is
counted at its centre against a region grown by a stated margin. A camera whose model is not a
plain pinhole is projected as a pinhole approximation and the margin is widened, rather than the
view being skipped. And a scene whose Gaussians carry no opacity property reports opacity as
unavailable instead of assuming the Gaussians are faint. Over-reporting costs somebody a look at a
number; under-reporting is how a body stays in the world while a receipt says it does not.

**It counts confirmed regions whether or not they are masked.** So it produces a real measurement
on a scene trained before any of this existed, which is what makes the check testable now rather
than only after the first masked training run. The two counts are reported separately: geometry
over a masked person is a fault, and geometry over a person who consented is simply the person.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from exulanica.consent.regions import Silhouette
from exulanica.evidence.region import PPM

__all__ = [
    "GaussianView",
    "count_masked_gaussians",
    "masked_geometry_is_clean",
    "read_gaussian_centres",
]


@dataclass(frozen=True, slots=True)
class GaussianView:
    """One recovered camera, and the outlines that were meant to be masked in its frame."""

    image_name: str
    quaternion_wxyz: tuple[float, float, float, float]
    translation_xyz: tuple[float, float, float]
    image_size: tuple[int, int]
    focal_xy: tuple[float, float]
    principal_xy: tuple[float, float]
    masked: tuple[Silhouette, ...]
    confirmed: tuple[Silhouette, ...]
    projection: str = "exact"


def read_gaussian_centres(
    data: bytes,
) -> tuple[list[tuple[float, float, float]], list[float] | None]:
    """Centres and, when the exporter wrote one, an opacity per Gaussian.

    The header walk is deliberately the same shape as ``gaussian_ply_bounds`` in
    ``exulanica.ingest.scene_splat``, because the two read the same file and a second, looser
    parser would accept bytes the first refuses. Opacity is returned as ``None`` rather than
    defaulted: whether the pinned exporter writes it, and whether it writes a logit or a
    probability, is not something this function may guess.
    """
    terminator = b"end_header\n"
    end = data.find(terminator)
    if end < 0 or end > 1_048_576:
        raise ValueError("Gaussian PLY has no bounded header")
    lines = data[:end].decode("ascii").splitlines()
    if not lines or lines[0] != "ply" or "format binary_little_endian 1.0" not in lines:
        raise ValueError("Gaussian PLY must use binary little endian float properties")
    properties: list[str] = []
    count = 0
    in_vertices = False
    for line in lines:
        parts = line.split()
        if parts[:1] == ["element"]:
            in_vertices = parts[1] == "vertex"
            if in_vertices:
                count = int(parts[2])
        elif in_vertices and parts[:1] == ["property"]:
            if len(parts) != 3 or parts[1] != "float":
                raise ValueError("Gaussian PLY has an unsupported vertex property")
            properties.append(parts[2])
    if count <= 0 or len(set(properties)) != len(properties):
        raise ValueError("Gaussian PLY has invalid vertex membership")
    if any(key not in properties for key in ("x", "y", "z")):
        raise ValueError("Gaussian PLY omits positions")
    payload = data[end + len(terminator) :]
    stride = len(properties) * 4
    if len(payload) != count * stride:
        raise ValueError("Gaussian PLY vertex bytes disagree with its header")
    axes = [properties.index(key) for key in ("x", "y", "z")]
    opacity_index = properties.index("opacity") if "opacity" in properties else None
    centres: list[tuple[float, float, float]] = []
    opacities: list[float] = []
    for vertex in struct.iter_unpack("<" + "f" * len(properties), payload):
        values = tuple(vertex[index] for index in axes)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Gaussian PLY contains nonfinite geometry")
        centres.append(values)
        if opacity_index is not None:
            opacities.append(vertex[opacity_index])
    return centres, (opacities if opacity_index is not None else None)


def _rotate(quaternion: Sequence[float], point: Sequence[float]) -> tuple[float, float, float]:
    """Rotate a world point into camera axes with a unit quaternion, w first."""
    w, x, y, z = quaternion
    xx, yy, zz = x * x, y * y, z * z
    wx, wy, wz = w * x, w * y, w * z
    xy, xz, yz = x * y, x * z, y * z
    px, py, pz = point
    return (
        px * (1 - 2 * (yy + zz)) + py * 2 * (xy - wz) + pz * 2 * (xz + wy),
        px * 2 * (xy + wz) + py * (1 - 2 * (xx + zz)) + pz * 2 * (yz - wx),
        px * 2 * (xz - wy) + py * 2 * (yz + wx) + pz * (1 - 2 * (xx + yy)),
    )


def _grown(silhouette: Silhouette, margin_ppm: int) -> Silhouette:
    """Push every vertex away from the outline's centre by a fixed margin.

    A crude dilation, and crude in the safe direction: it only ever makes the region tested
    larger, so a Gaussian near a boundary is reported rather than missed.
    """
    if margin_ppm <= 0:
        return silhouette
    bound = silhouette.bounding_rect()
    cx = bound.x_ppm + bound.w_ppm // 2
    cy = bound.y_ppm + bound.h_ppm // 2
    points = []
    for x, y in silhouette.points:
        dx = margin_ppm if x >= cx else -margin_ppm
        dy = margin_ppm if y >= cy else -margin_ppm
        points.append((min(PPM, max(0, x + dx)), min(PPM, max(0, y + dy))))
    return Silhouette(tuple(points))


def count_masked_gaussians(
    *,
    ply: bytes,
    views: Sequence[GaussianView],
    min_opacity_millionths: int = 0,
    margin_ppm: int = 10_000,
) -> dict[str, Any]:
    """Count Gaussians of meaningful opacity that project into a region meant to be masked."""
    centres, opacities = read_gaussian_centres(ply)
    threshold = min_opacity_millionths / 1_000_000
    per_view: list[dict[str, Any]] = []
    over_masked = 0
    over_confirmed = 0
    for view in views:
        width, height = view.image_size
        focal_x, focal_y = view.focal_xy
        principal_x, principal_y = view.principal_xy
        masked = tuple(_grown(outline, margin_ppm) for outline in view.masked)
        confirmed = tuple(_grown(outline, margin_ppm) for outline in view.confirmed)
        view_masked = 0
        view_confirmed = 0
        for index, centre in enumerate(centres):
            if opacities is not None and _probability(opacities[index]) < threshold:
                continue
            camera = _rotate(view.quaternion_wxyz, centre)
            depth = camera[2] + view.translation_xyz[2]
            if depth <= 0:
                continue
            u = focal_x * (camera[0] + view.translation_xyz[0]) / depth + principal_x
            v = focal_y * (camera[1] + view.translation_xyz[1]) / depth + principal_y
            if not (0 <= u < width and 0 <= v < height):
                continue
            x_ppm = int(u * PPM // width)
            y_ppm = int(v * PPM // height)
            if any(outline.contains(x_ppm, y_ppm) for outline in masked):
                view_masked += 1
            if any(outline.contains(x_ppm, y_ppm) for outline in confirmed):
                view_confirmed += 1
        over_masked += view_masked
        over_confirmed += view_confirmed
        per_view.append(
            {
                "image_name": view.image_name,
                "gaussians_over_masked_region": view_masked,
                "gaussians_over_confirmed_region": view_confirmed,
                "projection": view.projection,
            }
        )
    return {
        "profile": "exulanica.masked-geometry-check/v1",
        "gaussians": len(centres),
        "opacity": "unavailable" if opacities is None else "present",
        "min_opacity_millionths": min_opacity_millionths,
        "margin_ppm": margin_ppm,
        "gaussians_over_masked_region": over_masked,
        "gaussians_over_confirmed_region": over_confirmed,
        "views": per_view,
    }


def _probability(value: float) -> float:
    """Read an opacity that may have been written as a logit.

    gsplat stores opacity as a logit and some exporters apply the sigmoid first. A value outside
    ``[0, 1]`` can only be a logit; a value inside it is ambiguous and is taken at face value,
    which is the reading that counts MORE Gaussians and is therefore the safe one.
    """
    if 0.0 <= value <= 1.0:
        return value
    return 1.0 / (1.0 + math.exp(-value))


def masked_geometry_is_clean(report: Mapping[str, Any]) -> bool:
    """Whether the check found nothing. Separate so a caller cannot read a count as a verdict."""
    return int(report["gaussians_over_masked_region"]) == 0
