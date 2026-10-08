"""A stand-in for route C's models, so the whole creature job runs on this Mac with no GPU.

The concept picture is the control picture itself; the cut-out keeps what is not black; the mesh is
the plan's sketch filled on a grid and its surface taken, then given as route C's 3D model gives
one, built on the sketch's own voxels: in TRELLIS's frame (+Z up, its front toward -Y), unturned,
its box centred and its longest side one, coloured light above and dark below. So every later step
(turning into the slot frame, simplifying, registering, colouring, rigging, checking, writing,
reading back) runs as it does on the rented machine, on a body whose shape the plan states.
"""

from __future__ import annotations

import io
import platform
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
from exulanica_pieces.geometry.mesh import Mesh, Simplifier, cluster_simplify

from exulanica_appearance.creatures.geometry import voxel_inside, voxel_surface

__all__ = ["StandInBackend", "StandInMesh"]

#: Cells along the sketch's longest side when it is filled.
_CELLS: Final = 56


@dataclass(frozen=True)
class StandInMesh:
    mesh: Mesh
    up: str = "+Z"
    front: str = "-Y"


def _png(picture: np.ndarray) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(picture).save(buffer, format="PNG")
    return buffer.getvalue()


class StandInBackend:
    route = "stand-in"

    def simplifier(self) -> Simplifier:
        return cluster_simplify

    def concept(self, prompt: str, control: np.ndarray, seed: int) -> bytes:
        del prompt, seed
        return _png(np.asarray(control, dtype=np.uint8))

    def cutout(self, picture: bytes) -> bytes:
        from PIL import Image

        image = np.asarray(Image.open(io.BytesIO(picture)).convert("RGB"))
        alpha = np.where(image.max(axis=2) > 0, 255, 0).astype(np.uint8)
        return _png(np.dstack([image, alpha]))

    def mesh(self, cutout: bytes, seed: int, sketch: np.ndarray) -> StandInMesh:
        del cutout, seed
        corners = sketch.reshape(-1, 3)
        longest = float((corners.max(axis=0) - corners.min(axis=0)).max())
        grid, origin = voxel_inside(sketch, longest / _CELLS)
        positions, triangles = voxel_surface(grid, origin, longest / _CELLS)
        # The slot frame (x across, y forward, z up) as TRELLIS's: its front is -Y, so x and y
        # turn half way round; then into a unit box, as the second stage's structure is.
        trellis = np.stack([-positions[:, 0], -positions[:, 1], positions[:, 2]], axis=1)
        low, high = trellis.min(axis=0), trellis.max(axis=0)
        trellis = (trellis - (low + high) / 2) / float((high - low).max())
        height = (trellis[:, 2] - trellis[:, 2].min()) / max(float(np.ptp(trellis[:, 2])), 1e-12)
        colours = np.where(height[:, None] > 0.5, [196, 168, 120], [92, 70, 52]).astype(np.uint8)
        return StandInMesh(Mesh(trellis, triangles, colours))

    def runtime(self) -> dict[str, Any]:
        return {
            "machine": platform.platform(),
            "models": "stand-in",
            "python": platform.python_version(),
        }
