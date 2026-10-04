"""Route A: TRELLIS-image-large makes the shape and the colour.

The mesh decoder gives the shape; the Gaussian decoder gives colour, sampled at each mesh vertex
from its nearest Gaussians (the zeroth spherical harmonic, weighted by opacity over distance), so
no rasteriser is needed. TRELLIS's own GLB export, which bakes through nvdiffrast, is not used.
TRELLIS's frame is +Z up with its front toward -Y; its own exporter makes the same turn into glTF.
"""

from __future__ import annotations

import io
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import numpy as np
from exulanica_pieces.geometry.mesh import Mesh, Simplifier

from exulanica_appearance.assets.backends.shared import Shared, quadric_simplify
from exulanica_appearance.assets.job import RawMesh

__all__ = ["TrellisBackend"]

#: The zeroth spherical harmonic's constant: colour = 0.5 + C0 * dc.
_C0: Final = 0.28209479177387814
_NEIGHBOURS: Final = 8


class TrellisBackend:
    route = "A"

    def __init__(self, weights: Path) -> None:
        os.environ.setdefault("ATTN_BACKEND", "xformers")
        os.environ.setdefault("SPCONV_ALGO", "native")
        from trellis.pipelines import TrellisImageTo3DPipeline

        self._shared = Shared(weights)
        self._pipeline = TrellisImageTo3DPipeline.from_pretrained(
            str(weights / "microsoft__TRELLIS-image-large")
        )
        self._pipeline.cuda()

    def simplifier(self) -> Simplifier:
        return quadric_simplify

    def concept(self, prompt: str, seed: int) -> bytes:
        return self._shared.concept(prompt, seed)

    def cutout(self, picture: bytes) -> bytes:
        return self._shared.cutout(picture)

    def mesh(self, cutout: bytes, seed: int, request: Mapping[str, Any]) -> RawMesh:
        from PIL import Image
        from scipy.spatial import cKDTree

        image = Image.open(io.BytesIO(cutout)).convert("RGBA")
        # An image with alpha skips TRELLIS's background removal and is cropped and resized by it.
        outputs = self._pipeline.run(
            image, seed=seed, formats=["mesh", "gaussian"], preprocess_image=True
        )
        mesh = outputs["mesh"][0]
        gaussian = outputs["gaussian"][0]
        vertices = mesh.vertices.detach().float().cpu().numpy().astype(np.float64)
        faces = mesh.faces.detach().cpu().numpy().astype(np.int64)
        centres = gaussian.get_xyz.detach().float().cpu().numpy()
        dc = gaussian._features_dc.detach().float().cpu().numpy().reshape(len(centres), 3)
        opacity = gaussian.get_opacity.detach().float().cpu().numpy().reshape(-1)
        colour = np.clip(0.5 + _C0 * dc, 0, 1)
        distance, index = cKDTree(centres).query(vertices, k=_NEIGHBOURS)
        weight = opacity[index] / np.maximum(distance, 1e-6)
        mixed = (colour[index] * weight[..., None]).sum(axis=1) / weight.sum(axis=1)[:, None]
        srgb = np.rint(np.clip(mixed, 0, 1) * 255).astype(np.uint8)
        return RawMesh(Mesh(vertices, faces, srgb), up="+Z", front="-Y")

    def runtime(self) -> dict[str, Any]:
        return dict(self._shared.runtime(), model="microsoft/TRELLIS-image-large")
