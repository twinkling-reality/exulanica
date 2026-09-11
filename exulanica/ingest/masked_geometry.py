"""The check that makes masking real: did a hidden person leave any geometry behind?

The design note asks for exactly this and says why it matters. Masking a source is a claim about
what the trainer saw, and a claim about an input is not evidence about an output. This counts, in
the trained scene itself, how many Gaussians of meaningful opacity project into a region that was
supposed to be masked in the view they are seen from. The honest number is zero, and a number is
what goes in the evaluation record rather than an assurance.

**It errs toward reporting more, never less.** Four choices all lean the same way. A Gaussian is
counted at its centre against a region grown by a stated margin. A camera whose model is not a
plain pinhole is projected as a pinhole approximation and the margin is widened, rather than the
view being skipped. A scene whose Gaussians carry no opacity property reports opacity as
unavailable instead of assuming the Gaussians are faint. And a stored opacity that could be a
logit or a probability is read as whichever of the two is higher, so no exporter convention can
make the check miss a Gaussian. Over-reporting costs somebody a look at a number; under-reporting
is how a body stays in the world while a receipt says it does not.

A fifth choice does not lean that way and is listed separately for that reason: a nonfinite
opacity is REFUSED rather than read, so the file produces no count at all. That is not
over-reporting, it is declining to report, and it is the right answer for the one input where
leaning either way would be a guess. A NaN compares False against every threshold, so reading it
would have resolved silently to the transparent end and dropped the Gaussian under any floor a
caller set: the direction the other four choices exist to avoid, arrived at by arithmetic rather
than by decision.

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
    "camera_point",
    "count_masked_gaussians",
    "gaussian_centre_array",
    "image_point",
    "masked_geometry_is_clean",
    "ppm_point",
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


def _ply_vertices(data: bytes) -> tuple[int, list[str], bytes]:
    """A Gaussian PLY's vertex count, float property names and vertex bytes, refused if malformed.

    The one header walk both readers below use, so the array reader cannot accept a file the
    tuple reader refuses.
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
    return count, properties, payload


def gaussian_centre_array(data: bytes) -> Any:
    """Every Gaussian centre as an (N, 3) float64 array, for a caller that needs no opacity.

    The same file and the same refusals as ``read_gaussian_centres``, read in one vectorised pass
    rather than one Python tuple per Gaussian: the scene segment lift reads a trained scene of about
    a million Gaussians and keeps a fraction of them. The values are the exact float32 values the
    file holds, widened, which is what the tuple reader returns too.
    """
    import numpy as np

    count, properties, payload = _ply_vertices(data)
    vertices = np.frombuffer(payload, dtype="<f4").reshape(count, len(properties))
    centres = vertices[:, [properties.index(key) for key in ("x", "y", "z")]].astype(np.float64)
    if not np.isfinite(centres).all():
        raise ValueError("Gaussian PLY contains nonfinite geometry")
    return centres


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
    _count, properties, payload = _ply_vertices(data)
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
            opacity = vertex[opacity_index]
            if not math.isfinite(opacity):
                # Refused rather than read, and the refusal is load-bearing since `_probability`
                # started clamping its exponent. A NaN survives every comparison as False, so
                # `min(60.0, nan)` is 60.0 and the clamp would silently resolve a NaN opacity to
                # the TRANSPARENT end, dropping the Gaussian under any floor a caller sets. A
                # file that cannot say how opaque a Gaussian is does not get to answer "barely".
                raise ValueError("Gaussian PLY contains a nonfinite opacity")
            opacities.append(opacity)
    return centres, (opacities if opacity_index is not None else None)


def _rotate(quaternion: Sequence[float], point: Sequence[Any]) -> tuple[Any, Any, Any]:
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


# -- the projector ------------------------------------------------------------------------------
#
# Exposed so that the scene segment lift in `exulanica/ingest/scene_segments.py` projects through
# exactly the arithmetic this check counts with, rather than through a second projector that would
# one day disagree with it about which side of an outline a point lands on.
#
# Every step is plain arithmetic with no branch, so each accepts either a single coordinate or
# three equal-length numpy arrays of them. The check below calls them one Gaussian at a time with
# floats, exactly as it computed before they were split out; the lift calls them once per camera
# over every sample. The order of operations is the order the check always used, so a float in is
# bit-for-bit the value the inline expression produced.


def camera_point(view: GaussianView, point: Sequence[Any]) -> tuple[Any, Any, Any]:
    """A world point in the view's camera axes: rotated, then translated. The last is depth."""
    camera = _rotate(view.quaternion_wxyz, point)
    return (
        camera[0] + view.translation_xyz[0],
        camera[1] + view.translation_xyz[1],
        camera[2] + view.translation_xyz[2],
    )


def image_point(view: GaussianView, camera: Sequence[Any]) -> tuple[Any, Any]:
    """Pixel coordinates of a camera-axis point. The caller must have refused depth <= 0 first."""
    focal_x, focal_y = view.focal_xy
    principal_x, principal_y = view.principal_xy
    return (
        focal_x * camera[0] / camera[2] + principal_x,
        focal_y * camera[1] / camera[2] + principal_y,
    )


def ppm_point(view: GaussianView, u: Any, v: Any) -> tuple[Any, Any]:
    """Pixel coordinates in parts per million of the view's frame, floored, as the outlines are.

    Floored rather than truncated to an int here, so an array stays an array; a scalar caller
    wraps each in ``int``. The caller must have refused a pixel outside the frame first.
    """
    width, height = view.image_size
    return u * PPM // width, v * PPM // height


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
        masked = tuple(_grown(outline, margin_ppm) for outline in view.masked)
        confirmed = tuple(_grown(outline, margin_ppm) for outline in view.confirmed)
        view_masked = 0
        view_confirmed = 0
        for index, centre in enumerate(centres if masked or confirmed else ()):
            if opacities is not None and _probability(opacities[index]) < threshold:
                continue
            camera = camera_point(view, centre)
            if camera[2] <= 0:
                continue
            u, v = image_point(view, camera)
            if not (0 <= u < width and 0 <= v < height):
                continue
            x_ppm, y_ppm = (int(value) for value in ppm_point(view, u, v))
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
    # Which reading produced the count, because the PLY does not say. A reader who assumed the
    # number was computed against probabilities would otherwise misread a scene whose exporter
    # wrote logits, and this repository's exporter writes logits.
    reading = None if opacities is None else "logit or probability, whichever is higher"
    return {
        "profile": "exulanica.masked-geometry-check/v1",
        "gaussians": len(centres),
        "opacity": "unavailable" if opacities is None else "present",
        "opacity_reading": reading,
        "min_opacity_millionths": min_opacity_millionths,
        "margin_ppm": margin_ppm,
        "gaussians_over_masked_region": over_masked,
        "gaussians_over_confirmed_region": over_confirmed,
        "views": per_view,
    }


def _sigmoid(value: float) -> float:
    """Logistic, with the exponent clamped so a corrupt finite opacity saturates instead of raising.

    MEASURED 2026-09-07: an opacity of ``-1e10`` in an otherwise well-formed PLY raised
    ``OverflowError`` out of ``math.exp``, from a module whose entire error vocabulary is
    ``ValueError``. That crashes the check rather than answering it, and a check that crashes on a
    corrupt scene is a check nobody can run on the scene that most needs it.

    The clamp costs no precision that any caller can observe. MEASURED 2026-09-07 in float64:
    ``sigmoid(60)`` is exactly ``1.0`` and ``sigmoid(-60)`` is ``8.76e-27``, while the floor is
    expressed in millionths, so its smallest nonzero value is ``1e-6``. Past ``|60|`` the answer
    had already saturated to the far side of every threshold a caller can name.
    """
    return 1.0 / (1.0 + math.exp(max(-60.0, min(60.0, -value))))


def _probability(value: float) -> float:
    """Read an opacity whose convention the file does not state, in the direction that over-counts.

    MEASURED 2026-09-07: the exporter pinned by this repository writes LOGITS, so for a PLY this
    repository produced there is no ambiguity at all. ``splats["opacities"]`` is the raw
    parameter; every use of it in ``exulanica/reconstruction/gsplat_runner.py`` applies
    ``.sigmoid()`` at the point of use (``:571`` rasterization, ``:641`` floater weighting,
    ``:828`` the opacity regulariser), and ``:850`` then hands that same untransformed tensor to
    the exporter. The ambiguity this function exists for is a foreign file's.

    A value outside ``[0, 1]`` can only be a logit. A value inside it could be either, and this
    used to take it at face value while claiming that was "the reading that counts MORE Gaussians
    and is therefore the safe one". CORRECTED 2026-09-07: that claim was false over
    ``[0, 0.6591)``, which is precisely where the sigmoid exceeds the identity. A Gaussian stored
    as ``0.0``, which under this repository's own exporter means HALF OPAQUE, read as fully
    transparent and was dropped by any opacity floor above zero. Under-reporting is how a body
    stays in the world while a receipt says it does not, so the ambiguous range now returns
    whichever of the two readings is larger. ``0.99`` stays ``0.99`` as a probability, ``0.0``
    becomes ``0.5`` as a logit, and neither convention can make the check miss a Gaussian.
    """
    if 0.0 <= value <= 1.0:
        return max(value, _sigmoid(value))
    return _sigmoid(value)


def masked_geometry_is_clean(report: Mapping[str, Any]) -> bool:
    """Whether the check found nothing. Separate so a caller cannot read a count as a verdict."""
    return int(report["gaussians_over_masked_region"]) == 0
