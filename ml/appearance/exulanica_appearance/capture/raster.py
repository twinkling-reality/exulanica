"""Exact per-pixel structure from triangles and a pinhole camera, on the CPU.

For every pixel centre a ray is cast and the nearest triangle beyond the near plane is kept. What
the pixel records is exact geometry, not an estimate and not a render:

- ``depth``: distance along the camera's view axis, in micrometres; 0 where nothing is hit;
- ``normal``: the hit triangle's normal in world space, each component times ``NORMAL_SCALE``;
- ``identity``: the hit surface's index in the legend (1 and up); 0 where nothing is hit;
- ``surface_s``, ``surface_t``: the surface coordinates at the hit, in micrometres, interpolated
  from the vertices' millimetres (the texture placement frame the world states);
- ``edges``: bit 1 where the pixel's right or lower neighbour is a different identity, bit 2 where
  its normal differs by more than ``CREASE_TOLERANCE``, bit 4 where the neighbour's hit point lies
  off this pixel's plane by more than ``PLANE_TOLERANCE_UM`` or only one of the two hits anything.
  A plane test rather than a depth ratio, because ground seen at a grazing angle changes depth
  quickly between rows without any step in the geometry.

The camera matches PlayCanvas's ``lookAt`` with +Y up and a vertical field of view, as the bench
draws it. Arithmetic is float64, element by element, with no matrix library call whose reduction
order could change a digit, and the triangles are tested in a fixed order with a strict nearer test,
so the layers are a function of the geometry and the camera.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "CREASE_TOLERANCE",
    "LAYER_DTYPES",
    "NORMAL_SCALE",
    "PLANE_TOLERANCE_UM",
    "Camera",
    "Layers",
    "Triangles",
    "rasterize",
]

NORMAL_SCALE: Final = 32767
#: 1 per cent of a unit normal: well above rounding, well below the smallest crease the geometry has.
CREASE_TOLERANCE: Final = 327
#: 5 mm: sub-micrometre float noise is far below it, and the smallest real step (a 150 mm kerb) far above.
PLANE_TOLERANCE_UM: Final = 5000

LAYER_DTYPES: Final = {
    "depth": ("<u4", 1),
    "normal": ("<i2", 3),
    "identity": ("<u2", 1),
    "surface_s": ("<i4", 1),
    "surface_t": ("<i4", 1),
    "edges": ("u1", 1),
}


@dataclass(frozen=True, slots=True)
class Camera:
    position_um: tuple[int, int, int]
    target_um: tuple[int, int, int]
    width: int
    height: int
    vertical_fov_degrees: int
    near_um: int

    def basis(self) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
        """Right, up and forward unit vectors, as PlayCanvas's ``lookAt`` with +Y up builds them."""
        origin = np.array(self.position_um, dtype=np.float64) / 1e6
        target = np.array(self.target_um, dtype=np.float64) / 1e6
        forward = target - origin
        forward = forward / math.sqrt(_dot(forward, forward))
        up = np.array([0.0, 1.0, 0.0])
        right = _cross(forward, up)
        right = right / math.sqrt(_dot(right, right))
        return right, _cross(right, forward), forward

    def origin(self) -> NDArray[np.float64]:
        return np.array(self.position_um, dtype=np.float64) / 1e6

    def directions(self) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
        """Per-pixel ray directions whose forward component is 1, so ray length t is view depth."""
        right, up, forward = self.basis()
        half = math.tan(math.radians(self.vertical_fov_degrees) / 2)
        rows, columns = np.mgrid[0 : self.height, 0 : self.width].astype(np.float64)
        cx = ((columns + 0.5) / self.width * 2 - 1) * half * (self.width / self.height)
        cy = (1 - (rows + 0.5) / self.height * 2) * half
        return (
            cx * right[0] + cy * up[0] + forward[0],
            cx * right[1] + cy * up[1] + forward[1],
            cx * right[2] + cy * up[2] + forward[2],
        )


@dataclass(frozen=True, slots=True)
class Triangles:
    """``n`` triangles: corners in metres (n, 3) each, unit normals (n, 3), identity (n,),
    and surface coordinates in millimetres at each corner (n, 2)."""

    a: NDArray[np.float64]
    b: NDArray[np.float64]
    c: NDArray[np.float64]
    normal: NDArray[np.float64]
    identity: NDArray[np.int64]
    st_a: NDArray[np.float64]
    st_b: NDArray[np.float64]
    st_c: NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Layers:
    depth: NDArray[np.uint32]
    normal: NDArray[np.int16]
    identity: NDArray[np.uint16]
    surface_s: NDArray[np.int32]
    surface_t: NDArray[np.int32]
    edges: NDArray[np.uint8]

    def layer_bytes(self, name: str) -> bytes:
        dtype, _ = LAYER_DTYPES[name]
        return np.ascontiguousarray(getattr(self, name), dtype=np.dtype(dtype)).tobytes()


def _dot(a: NDArray[np.float64], b: NDArray[np.float64]) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def _cross(a: NDArray[np.float64], b: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.array(
        [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    )


def rasterize(triangles: Triangles, camera: Camera) -> Layers:
    dx, dy, dz = camera.directions()
    origin = camera.origin()
    near = camera.near_um / 1e6
    shape = (camera.height, camera.width)
    best = np.full(shape, np.inf)
    which = np.full(shape, -1, dtype=np.int64)
    bary_u = np.zeros(shape)
    bary_v = np.zeros(shape)
    for index in range(len(triangles.identity)):
        a, b, c = triangles.a[index], triangles.b[index], triangles.c[index]
        e1 = b - a
        e2 = c - a
        px = dy * e2[2] - dz * e2[1]
        py = dz * e2[0] - dx * e2[2]
        pz = dx * e2[1] - dy * e2[0]
        det = e1[0] * px + e1[1] * py + e1[2] * pz
        usable = np.abs(det) > 1e-12
        inverse = np.divide(1.0, det, out=np.zeros(shape), where=usable)
        tv = origin - a
        u = (tv[0] * px + tv[1] * py + tv[2] * pz) * inverse
        q = _cross(tv, e1)
        v = (dx * q[0] + dy * q[1] + dz * q[2]) * inverse
        t = float(e2[0] * q[0] + e2[1] * q[1] + e2[2] * q[2]) * inverse
        hit = usable & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > near) & (t < best)
        best = np.where(hit, t, best)
        which = np.where(hit, index, which)
        bary_u = np.where(hit, u, bary_u)
        bary_v = np.where(hit, v, bary_v)

    found = which >= 0
    chosen = np.where(found, which, 0)
    depth = np.where(found, np.rint(np.where(found, best, 0) * 1e6), 0).astype(np.uint32)
    normal = np.where(found[..., None], np.rint(triangles.normal[chosen] * NORMAL_SCALE), 0).astype(
        np.int16
    )
    identity = np.where(found, triangles.identity[chosen], 0).astype(np.uint16)
    w = 1 - bary_u - bary_v
    st = (
        w[..., None] * triangles.st_a[chosen]
        + bary_u[..., None] * triangles.st_b[chosen]
        + bary_v[..., None] * triangles.st_c[chosen]
    )
    surface_s = np.where(found, np.rint(st[..., 0] * 1000), 0).astype(np.int32)
    surface_t = np.where(found, np.rint(st[..., 1] * 1000), 0).astype(np.int32)

    points = [
        origin[axis] + np.where(found, best, 0) * direction
        for axis, direction in enumerate((dx, dy, dz))
    ]
    unit = [triangles.normal[chosen][..., axis] for axis in range(3)]
    edges = np.zeros(shape, dtype=np.uint8)
    for axis in (0, 1):
        here = (slice(None, -1), slice(None)) if axis == 0 else (slice(None), slice(None, -1))
        there = (slice(1, None), slice(None)) if axis == 0 else (slice(None), slice(1, None))
        different = identity[here] != identity[there]
        both = found[here] & found[there]
        crease = both & (
            np.abs(normal[here].astype(np.int32) - normal[there].astype(np.int32)).max(axis=-1)
            > CREASE_TOLERANCE
        )
        off_plane = (
            np.abs(
                (points[0][there] - points[0][here]) * unit[0][here]
                + (points[1][there] - points[1][here]) * unit[1][here]
                + (points[2][there] - points[2][here]) * unit[2][here]
            )
            * 1e6
            > PLANE_TOLERANCE_UM
        )
        step = (found[here] != found[there]) | (both & off_plane)
        marks = (
            different.astype(np.uint8) * 1 + crease.astype(np.uint8) * 2 + step.astype(np.uint8) * 4
        )
        edges[here] |= marks
    return Layers(depth, normal, identity, surface_s, surface_t, edges)
