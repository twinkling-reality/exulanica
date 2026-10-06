"""What a hand meets on a held piece: the section through its grip, and how full its box is.

A thing kind that may be held states a grip point and an axis in its slot frame (x across the
width, y the depth with the front at +y, z up, millimetres from the base centre): the axis is the
direction the thing extends from the hand. The piece, fitted into the kind's box, is cut by a slab
:data:`BAND_MM` either side of the plane through the grip point across that axis, and the section
is the extent of everything inside the slab along the two other axes. A hand can close around the
piece there when the section exists, is no wider than the body plan's figure, and contains the
grip point. The checks themselves are :func:`exulanica_pieces.records.verdict`'s; this module only
measures.

The fill is the fitted size along the box's longest side, per mille of that side: a model that laid
a sword down would be shrunk by the contain fit until its blade was a stub at the bottom of the box,
and the grip, measured from the base, would land on nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

import numpy as np

from exulanica_pieces.geometry.mesh import Mesh

__all__ = ["BAND_MM", "measure_hold"]

#: Half the slab's thickness, so a section through a vertex or a flat face still has its extent.
BAND_MM: Final = 10

#: Slot axis to (glTF column, sign): X_gltf = -x, Y_gltf = z, Z_gltf = y.
_GLTF: Final = {"x": (0, -1.0), "y": (2, 1.0), "z": (1, 1.0)}


def measure_hold(
    mesh: Mesh, slot_mm: Mapping[str, int], size_mm: Mapping[str, int], hold: Mapping[str, Any]
) -> dict[str, Any]:
    """``mesh`` as fitted, in metres in glTF's frame with its base centre at the origin."""
    longest = max(("width", "height", "depth"), key=lambda key: (slot_mm[key], key))
    fill = size_mm[longest] * 1000 // slot_mm[longest]
    along = hold["axis"][1]
    across = tuple(axis for axis in "xyz" if axis != along)
    grip = {axis: hold["grip"][f"{axis}_mm"] for axis in "xyz"}
    points = _slab_points(mesh, along, grip[along])
    if len(points) == 0:
        return {
            "band_mm": BAND_MM,
            "fill_permille": fill,
            "grip_in_section": False,
            "section_mm": None,
        }
    low = {axis: float(points[:, i].min()) for i, axis in enumerate(across)}
    high = {axis: float(points[:, i].max()) for i, axis in enumerate(across)}
    section = {f"{axis}_mm": round(high[axis] - low[axis]) for axis in across}
    inside = all(low[axis] - 0.5 <= grip[axis] <= high[axis] + 0.5 for axis in across)
    return {
        "band_mm": BAND_MM,
        "fill_permille": fill,
        "grip_in_section": inside,
        "section_mm": section,
    }


def _slot_mm(positions: np.ndarray, axis: str) -> np.ndarray:
    column, sign = _GLTF[axis]
    return positions[..., column] * sign * 1000


def _slab_points(mesh: Mesh, along: str, centre_mm: int) -> np.ndarray:
    """Every corner of each triangle's part inside the slab, as (n, 2) across-axis millimetres.

    The part of a triangle inside a slab is a convex polygon whose corners are the triangle's
    vertices inside it and the points where its edges cross the slab's two faces, so their extent
    is the section's extent exactly."""
    across = tuple(axis for axis in "xyz" if axis != along)
    coordinate = _slot_mm(mesh.positions, along)
    flat = np.stack([_slot_mm(mesh.positions, axis) for axis in across], axis=1)
    low, high = centre_mm - BAND_MM, centre_mm + BAND_MM
    used = np.unique(mesh.triangles)
    keep = used[(coordinate[used] >= low) & (coordinate[used] <= high)]
    found = [flat[keep]]
    edges = np.concatenate(
        [mesh.triangles[:, [0, 1]], mesh.triangles[:, [1, 2]], mesh.triangles[:, [2, 0]]]
    )
    start, end = coordinate[edges[:, 0]], coordinate[edges[:, 1]]
    for face in (low, high):
        crossing = (start - face) * (end - face) < 0
        if crossing.any():
            a, b = edges[crossing, 0], edges[crossing, 1]
            t = (face - coordinate[a]) / (coordinate[b] - coordinate[a])
            found.append(flat[a] + (flat[b] - flat[a]) * t[:, None])
    return np.concatenate(found)
