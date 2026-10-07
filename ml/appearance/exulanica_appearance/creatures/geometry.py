"""Geometry the creature route needs and no model: read a sketch, draw it, fill it, make a skin.

Everything here is numpy on the slot frame (metres; x across, y forward, z up):

*   :func:`sketch_triangles` reads a sketch look's static container (``bone:<name>`` nodes, parts
    as children) back into triangles in the slot frame, each tagged with the bone it rides on.
*   :func:`project` and :func:`rasterise` draw triangles from a fixed camera, orthographically,
    into a depth picture and a silhouette mask: the control picture the concept picture follows,
    and the silhouettes a sculpted mesh is registered by.
*   :func:`voxel_inside` fills a mesh's inside on a grid (surface voxels, then everything the
    outside cannot reach), which tolerates a mesh that is not quite closed.
*   :func:`voxel_surface` turns a filled grid into a closed mesh of its boundary faces: an offline
    stand-in for a sculpted mesh in tests, built from a sketch, with no model.

Deterministic: the same inputs give the same arrays on any machine with the same numpy.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

import numpy as np

__all__ = [
    "CONTROL_CAMERA",
    "Camera",
    "Drawn",
    "project",
    "rasterise",
    "sketch_triangles",
    "voxel_inside",
    "voxel_surface",
]


def _accessor(document: dict, binary: bytes, index: int) -> np.ndarray:
    accessor = document["accessors"][index]
    view = document["bufferViews"][accessor["bufferView"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[accessor["type"]]
    dtype = {5126: np.float32, 5123: np.uint16, 5125: np.uint32, 5121: np.uint8}[
        accessor["componentType"]
    ]
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    count = accessor["count"]
    data = np.frombuffer(binary, dtype=dtype, count=count * width, offset=start)
    return data.reshape(count, width) if width > 1 else data


def _slot(gltf: np.ndarray) -> np.ndarray:
    """glTF (X, Y, Z) as the slot frame's (x, y, z) = (-X, Z, Y)."""
    return np.stack([-gltf[..., 0], gltf[..., 2], gltf[..., 1]], axis=-1).astype(np.float64)


def sketch_triangles(container: bytes) -> tuple[np.ndarray, list[str]]:
    """A sketch's triangles in the slot frame (T x 3 x 3, metres) and the bone each rides on."""
    length, _kind = struct.unpack_from("<II", container, 12)
    document = json.loads(container[20 : 20 + length])
    binary = container[20 + length + 8 :]
    nodes = document["nodes"]
    parent: dict[int, int] = {}
    for index, node in enumerate(nodes):
        for child in node.get("children", []):
            parent[child] = index
    triangles: list[np.ndarray] = []
    bones: list[str] = []
    for index, node in enumerate(nodes):
        if "mesh" not in node:
            continue
        offset = np.zeros(3)
        owner = index
        while owner in parent:
            owner = parent[owner]
            offset += np.asarray(nodes[owner].get("translation", [0.0, 0.0, 0.0]))
        offset += np.asarray(node.get("translation", [0.0, 0.0, 0.0]))
        name = nodes[owner]["name"]
        for primitive in document["meshes"][node["mesh"]]["primitives"]:
            positions = _accessor(document, binary, primitive["attributes"]["POSITION"]).astype(
                np.float64
            )
            indices = _accessor(document, binary, primitive["indices"]).astype(np.int64)
            corners = positions[indices.reshape(-1, 3)] + offset
            triangles.append(_slot(corners))
            bones += [name.removeprefix("bone:")] * len(corners)
    return np.concatenate(triangles, axis=0), bones


@dataclass(frozen=True)
class Camera:
    """An orthographic camera: turned ``yaw_deg`` about z from looking along +y, tilted
    ``pitch_deg`` down."""

    yaw_deg: float
    pitch_deg: float


#: The three-quarter view every control picture is drawn from, and a concept picture follows.
CONTROL_CAMERA: Final = Camera(yaw_deg=-35.0, pitch_deg=15.0)


def project(points: np.ndarray, camera: Camera) -> np.ndarray:
    """Points (... x 3, slot frame) as (right, up, toward the camera)."""
    yaw, pitch = np.radians(camera.yaw_deg), np.radians(camera.pitch_deg)
    x, y, z = points[..., 0], points[..., 1], points[..., 2]
    right = x * np.cos(yaw) - y * np.sin(yaw)
    depth_in = x * np.sin(yaw) + y * np.cos(yaw)
    up = z * np.cos(pitch) + depth_in * np.sin(pitch)
    toward = -depth_in * np.cos(pitch) + z * np.sin(pitch)
    return np.stack([right, up, toward], axis=-1)


@dataclass(frozen=True)
class Drawn:
    """A rasterised view: depth (larger nearer, NaN where nothing is drawn), the index of the
    triangle drawn at each pixel (-1 where none is), and the framing that maps the view's (right,
    up) to pixels, so a second mesh can be drawn in the same frame."""

    depth: np.ndarray
    triangle: np.ndarray
    centre: tuple[float, float]
    scale: float

    @property
    def mask(self) -> np.ndarray:
        return ~np.isnan(self.depth)


def rasterise(
    triangles: np.ndarray,
    camera: Camera,
    size: int,
    *,
    frame: Drawn | None = None,
    margin: float = 0.08,
) -> Drawn:
    """Triangles (T x 3 x 3) drawn by ``camera`` into a ``size`` square, framed to fit with a
    margin, or in ``frame``'s framing when given."""
    projected = project(triangles, camera)
    if frame is None:
        flat = projected.reshape(-1, 3)
        low, high = flat[:, :2].min(axis=0), flat[:, :2].max(axis=0)
        centre = (float((low[0] + high[0]) / 2), float((low[1] + high[1]) / 2))
        scale = float(size * (1 - 2 * margin) / max(high[0] - low[0], high[1] - low[1], 1e-9))
    else:
        centre, scale = frame.centre, frame.scale
    depth = np.full((size, size), np.nan)
    drawn = np.full((size, size), -1, dtype=np.int64)
    px = (projected[..., 0] - centre[0]) * scale + size / 2
    py = size / 2 - (projected[..., 1] - centre[1]) * scale
    pz = projected[..., 2]
    for index, ((x0, x1, x2), (y0, y1, y2), (z0, z1, z2)) in enumerate(
        zip(px, py, pz, strict=True)
    ):
        left, right = (
            int(max(np.floor(min(x0, x1, x2)), 0)),
            int(min(np.ceil(max(x0, x1, x2)), size - 1)),
        )
        top, bottom = (
            int(max(np.floor(min(y0, y1, y2)), 0)),
            int(min(np.ceil(max(y0, y1, y2)), size - 1)),
        )
        if left > right or top > bottom:
            continue
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-12:
            continue
        xs, ys = np.meshgrid(np.arange(left, right + 1) + 0.5, np.arange(top, bottom + 1) + 0.5)
        w0 = ((x1 - xs) * (y2 - ys) - (x2 - xs) * (y1 - ys)) / area
        w1 = ((x2 - xs) * (y0 - ys) - (x0 - xs) * (y2 - ys)) / area
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        z = w0 * z0 + w1 * z1 + w2 * z2
        region = depth[top : bottom + 1, left : right + 1]
        nearer = inside & (np.isnan(region) | (z > region))
        region[nearer] = z[nearer]
        drawn[top : bottom + 1, left : right + 1][nearer] = index
    return Drawn(depth, drawn, centre, scale)


def voxel_inside(
    triangles: np.ndarray, voxel: float, *, pad: int = 2
) -> tuple[np.ndarray, np.ndarray]:
    """The voxels a mesh holds (a boolean grid) and the grid's origin (its lowest corner, metres).

    Surface voxels are those a point sampled on a triangle falls in (samples a third of a voxel
    apart); the inside is every voxel the outside cannot reach through non-surface voxels from the
    grid's border, so a hole smaller than a voxel does not let the outside in."""
    corners = triangles.reshape(-1, 3)
    origin = corners.min(axis=0) - pad * voxel
    shape = np.ceil((corners.max(axis=0) - origin) / voxel).astype(int) + pad + 1
    surface = np.zeros(shape, dtype=bool)
    for a, b, c in triangles:
        longest = max(np.linalg.norm(b - a), np.linalg.norm(c - a), np.linalg.norm(c - b))
        steps = max(int(np.ceil(longest / (voxel / 3))), 1)
        u, v = np.meshgrid(np.arange(steps + 1), np.arange(steps + 1))
        keep = u + v <= steps
        u, v = u[keep] / steps, v[keep] / steps
        points = a + np.outer(u, b - a) + np.outer(v, c - a)
        cells = np.floor((points - origin) / voxel).astype(int)
        surface[cells[:, 0], cells[:, 1], cells[:, 2]] = True
    outside = np.zeros(shape, dtype=bool)
    frontier = []
    for axis in range(3):
        for end in (0, shape[axis] - 1):
            index = [slice(None)] * 3
            index[axis] = end
            face = np.zeros(shape, dtype=bool)
            face[tuple(index)] = True
            frontier.append(face & ~surface)
    current = np.logical_or.reduce(frontier)
    outside |= current
    while current.any():
        grown = np.zeros(shape, dtype=bool)
        grown[1:] |= current[:-1]
        grown[:-1] |= current[1:]
        grown[:, 1:] |= current[:, :-1]
        grown[:, :-1] |= current[:, 1:]
        grown[:, :, 1:] |= current[:, :, :-1]
        grown[:, :, :-1] |= current[:, :, 1:]
        current = grown & ~outside & ~surface
        outside |= current
    return ~outside, origin


def voxel_surface(
    inside: np.ndarray, origin: np.ndarray, voxel: float
) -> tuple[np.ndarray, np.ndarray]:
    """A closed mesh (positions V x 3, triangles T x 3) of a filled grid's boundary faces, two
    triangles a face, wound outward; vertices shared at the grid's corners."""
    padded = np.pad(inside, 1)
    faces = []
    for axis in range(3):
        for sign in (1, -1):
            neighbour = np.roll(padded, -sign, axis=axis)
            boundary = padded & ~neighbour
            for cell in np.argwhere(boundary):
                faces.append((tuple(cell - 1), axis, sign))
    index: dict[tuple[int, int, int], int] = {}
    positions: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []

    def corner(point: tuple[int, int, int]) -> int:
        if point not in index:
            index[point] = len(positions)
            positions.append(tuple(origin + np.asarray(point) * voxel))
        return index[point]

    for cell, axis, sign in faces:
        base = list(cell)
        if sign > 0:
            base[axis] += 1
        others = [a for a in range(3) if a != axis]
        quad = []
        for du, dv in ((0, 0), (1, 0), (1, 1), (0, 1)):
            point = list(base)
            point[others[0]] += du
            point[others[1]] += dv
            quad.append(corner(tuple(point)))
        # (others[0], others[1], axis) is right-handed for axis 0 and 2 and left-handed for 1.
        outward = (sign > 0) == (axis != 1)
        if outward:
            triangles += [(quad[0], quad[1], quad[2]), (quad[0], quad[2], quad[3])]
        else:
            triangles += [(quad[0], quad[2], quad[1]), (quad[0], quad[3], quad[2])]
    return np.asarray(positions, dtype=np.float64), np.asarray(triangles, dtype=np.int64)


def bone_segments(
    joints: Mapping[str, np.ndarray], ends: Mapping[str, np.ndarray]
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Each bone as the segment from its joint to its end."""
    return {
        bone: (np.asarray(joints[bone], float), np.asarray(ends[bone], float)) for bone in joints
    }
