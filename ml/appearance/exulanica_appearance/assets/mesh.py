"""The deterministic steps between a model's raw mesh and a piece: orient, simplify, fit, colour.

A :class:`Mesh` holds positions in metres, triangles as vertex indices and one 8-bit sRGB colour
per vertex, which is what both routes yield (route A samples its Gaussians at each vertex, route B
projects its concept picture). Each step returns a new mesh and the integers that say what it did,
so the receipt can state every step.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

import numpy as np

from exulanica_appearance.assets.colour import nearest_swatch
from exulanica_appearance.assets.vocabulary import FILL_RATIO_PER_MILLE
from exulanica_appearance.canonical import Refused

__all__ = [
    "AXES",
    "Mesh",
    "Simplifier",
    "cluster_simplify",
    "fit",
    "flat_palette",
    "orient",
    "simplify_to",
]

#: The signed axis names a raw mesh may state for its up and its front.
AXES: Final = MappingProxyType(
    {
        "+X": (0, 1.0),
        "-X": (0, -1.0),
        "+Y": (1, 1.0),
        "-Y": (1, -1.0),
        "+Z": (2, 1.0),
        "-Z": (2, -1.0),
    }
)


@dataclass(frozen=True)
class Mesh:
    positions: np.ndarray  # (n, 3) float64, metres
    triangles: np.ndarray  # (m, 3) int64
    colours: np.ndarray  # (n, 3) uint8, sRGB

    def __post_init__(self) -> None:
        if self.positions.ndim != 2 or self.positions.shape[1] != 3:
            raise Refused("positions are (n, 3)")
        if self.triangles.ndim != 2 or self.triangles.shape[1] != 3 or len(self.triangles) == 0:
            raise Refused("a mesh holds at least one triangle as (m, 3) indices")
        if self.colours.shape != self.positions.shape:
            raise Refused("every vertex has one sRGB colour")
        if not np.isfinite(self.positions).all():
            raise Refused("a position is not finite")
        if self.triangles.min() < 0 or self.triangles.max() >= len(self.positions):
            raise Refused("a triangle names a vertex past the end")

    @property
    def extent(self) -> np.ndarray:
        return self.positions.max(axis=0) - self.positions.min(axis=0)

    def compact(self) -> Mesh:
        """The same triangles without vertices no triangle uses, which would count in the extent
        but never be written."""
        used, triangles = np.unique(self.triangles, return_inverse=True)
        return Mesh(self.positions[used], triangles.reshape(-1, 3), self.colours[used])


def _vector(axis: str) -> np.ndarray:
    if axis not in AXES:
        raise Refused(f"axis {axis!r} is not one of {', '.join(AXES)}")
    index, sign = AXES[axis]
    vector = np.zeros(3)
    vector[index] = sign
    return vector


def orient(mesh: Mesh, up: str, front: str) -> tuple[Mesh, dict[str, object]]:
    """Rotate so the raw mesh's ``up`` is glTF +Y and its ``front`` is glTF +Z.

    The map is a proper rotation (determinant +1), never a reflection, which would turn the piece
    inside out and mirror any lettering.
    """
    u, f = _vector(up), _vector(front)
    if abs(float(u @ f)) > 0:
        raise Refused(f"up {up} and front {front} are not perpendicular")
    # Rows are where the raw x, y, z go: the raw frame's (right, up, front) become glTF's (+X,
    # +Y, +Z). glTF's +X is up cross front, which a right-handed frame requires.
    right = np.cross(u, f)
    rotation = np.stack([right, u, f])
    if round(float(np.linalg.det(rotation))) != 1:
        raise Refused("the stated axes do not make a rotation")
    positions = mesh.positions @ rotation.T
    return Mesh(positions, mesh.triangles, mesh.colours), {
        "front": front,
        "step": "orient",
        "up": up,
    }


Simplifier = Callable[[Mesh, int], tuple[Mesh, Mapping[str, object]]]


def cluster_simplify(mesh: Mesh, target: int) -> tuple[Mesh, Mapping[str, object]]:
    """A STAND-IN simplifier for tests and the dry run: vertex clustering on a uniform grid.

    Each vertex snaps to its grid cell, a cell's vertices merge (position and colour averaged),
    and triangles that collapse are dropped. The grid starts at 64 cells along the longest side
    and halves until the target holds. It keeps silhouettes poorly; the rented machine runs
    meshoptimizer's quadric simplifier behind the same interface.
    """
    longest = float(mesh.extent.max())
    if longest <= 0:
        raise Refused("a mesh with no extent cannot be simplified")
    cells = 64
    while True:
        size = longest / cells
        origin = mesh.positions.min(axis=0)
        keys = np.floor((mesh.positions - origin) / size).astype(np.int64)
        _, cluster, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
        cluster = cluster.reshape(-1)
        positions = np.zeros((len(counts), 3))
        np.add.at(positions, cluster, mesh.positions)
        positions /= counts[:, None]
        colours = np.zeros((len(counts), 3))
        np.add.at(colours, cluster, mesh.colours.astype(np.float64))
        colours = np.rint(colours / counts[:, None]).astype(np.uint8)
        mapped = cluster[mesh.triangles]
        keep = (
            (mapped[:, 0] != mapped[:, 1])
            & (mapped[:, 1] != mapped[:, 2])
            & (mapped[:, 0] != mapped[:, 2])
        )
        mapped = mapped[keep]
        # Two triangles over the same three clusters draw once; the first in order is kept.
        first = np.unique(np.sort(mapped, axis=1), axis=0, return_index=True)[1]
        kept = mapped[np.sort(first)]
        if (len(kept) <= target and len(kept) > 0) or cells <= 2:
            break
        cells //= 2
    if len(kept) == 0 or len(kept) > target:
        raise Refused(f"the stand-in simplifier cannot reach {target} triangles")
    return Mesh(positions, kept, colours), {
        "cells_on_longest_side": cells,
        "simplifier": "cluster-stand-in/v1",
    }


def simplify_to(mesh: Mesh, target: int, simplifier: Simplifier) -> tuple[Mesh, dict[str, object]]:
    before = len(mesh.triangles)
    if before <= target:
        return mesh, {
            "step": "simplify",
            "target": target,
            "triangles_after": before,
            "triangles_before": before,
        }
    out, parameters = simplifier(mesh, target)
    if len(out.triangles) > target:
        raise Refused(f"the simplifier left {len(out.triangles)} triangles over {target}")
    return out, {
        "parameters": dict(parameters),
        "step": "simplify",
        "target": target,
        "triangles_after": len(out.triangles),
        "triangles_before": before,
    }


def _mm(metres: float) -> int:
    return round(metres * 1000)


def fit(mesh: Mesh, rule: str, slot_mm: Mapping[str, int]) -> tuple[Mesh, dict[str, object]]:
    """Scale uniformly into the slot and stand the base centre on the origin.

    ``slot_mm`` is width (glTF X), height (glTF Y) and depth (glTF Z). ``contain`` and ``tile``
    fit inside; ``fill`` fits inside too and then refuses a piece whose own proportions the page
    could not stretch to the slot within 0.8 to 1.25 per axis. Nothing is stretched here.
    """
    mesh = mesh.compact()
    slot = (
        np.array([slot_mm["width"], slot_mm["height"], slot_mm["depth"]], dtype=np.float64) / 1000
    )
    extent = mesh.extent
    if (extent <= 0).any():
        raise Refused("a piece has no extent along an axis")
    scale = float(np.min(slot / extent))
    low = mesh.positions.min(axis=0)
    high = mesh.positions.max(axis=0)
    centre = np.array([(low[0] + high[0]) / 2, low[1], (low[2] + high[2]) / 2])
    positions = (mesh.positions - centre) * scale
    size = extent * scale
    size_mm = {"width": _mm(size[0]), "height": _mm(size[1]), "depth": _mm(size[2])}
    record: dict[str, object] = {
        "gap_mm": {key: slot_mm[key] - size_mm[key] for key in ("width", "height", "depth")},
        "rule": rule,
        "scale_per_million": round(scale * 1_000_000),
        "size_mm": size_mm,
        "step": "fit",
    }
    if rule == "fill":
        low_ratio, high_ratio = FILL_RATIO_PER_MILLE
        ratios = {key: (slot_mm[key] * 1000) // max(size_mm[key], 1) for key in size_mm}
        record["stretch_per_mille"] = ratios
        if any(not low_ratio <= value <= high_ratio for value in ratios.values()):
            raise Refused(
                "the piece's proportions are too far from its fill slot "
                f"(stretch per mille {ratios}, allowed {low_ratio} to {high_ratio})"
            )
    elif rule not in ("contain", "tile"):
        raise Refused(f"fit rule {rule!r} does not make a mesh")
    return Mesh(positions, mesh.triangles, mesh.colours), record


def flat_palette(
    mesh: Mesh, palette: Sequence[Sequence[int]]
) -> tuple[Mesh, np.ndarray, dict[str, object]]:
    """One swatch per triangle, flat shaded: the mean of its vertices' colours, snapped in OKLab.

    Returns a mesh whose vertices are unshared (three per triangle) and each triangle's swatch
    index. Writing merges vertices that agree in position, normal and swatch.
    """
    means = np.rint(mesh.colours[mesh.triangles].astype(np.float64).mean(axis=1)).astype(np.uint8)
    swatch = nearest_swatch(means, palette)
    positions = mesh.positions[mesh.triangles].reshape(-1, 3)
    colours = np.asarray(palette, dtype=np.uint8)[np.repeat(swatch, 3)]
    triangles = np.arange(len(positions), dtype=np.int64).reshape(-1, 3)
    used = sorted({int(index) for index in swatch})
    return (
        Mesh(positions, triangles, colours),
        swatch,
        {
            "space": "oklab",
            "step": "palette",
            "swatches_used": used,
            "triangles": len(triangles),
        },
    )
