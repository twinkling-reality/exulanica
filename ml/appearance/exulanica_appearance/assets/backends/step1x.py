"""Route B: Step1X-3D's geometry pipeline makes the shape; colour comes from the cut-out.

The pipeline is asked for plain arrays (``output_type="np"``), which skips its floater removal and
face reduction (both pymeshlab, GPL-3, not installed). Colour is a PROTOTYPE projection: every
vertex takes the cut-out's colour at its position seen straight from the front, the mesh's front
bounds matched to the cut-out's opaque bounds. The concept picture is drawn at three-quarters, so
this is approximate by construction; the palette step then flattens it. The pipeline returns a
glTF-framed mesh, +Y up and front +Z, as its own GLB export writes it.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from exulanica_pieces.geometry.mesh import Mesh, Simplifier

from exulanica_appearance.assets.backends.shared import Shared, quadric_simplify
from exulanica_appearance.assets.job import RawMesh

__all__ = ["Step1XBackend", "project_colours"]


def project_colours(vertices: np.ndarray, cutout_rgba: np.ndarray) -> np.ndarray:
    """sRGB per vertex from an RGBA picture, seen along -Z with +Y up, bounds to opaque bounds."""
    opaque = np.argwhere(cutout_rgba[:, :, 3] > 127)
    if len(opaque) == 0:
        raise ValueError("the cut-out has no opaque pixel")
    (top, left), (bottom, right) = opaque.min(axis=0), opaque.max(axis=0)
    low, high = vertices.min(axis=0), vertices.max(axis=0)
    u = (vertices[:, 0] - low[0]) / max(high[0] - low[0], 1e-9)
    v = (high[1] - vertices[:, 1]) / max(high[1] - low[1], 1e-9)
    columns = np.clip(np.rint(left + u * (right - left)).astype(int), 0, cutout_rgba.shape[1] - 1)
    rows = np.clip(np.rint(top + v * (bottom - top)).astype(int), 0, cutout_rgba.shape[0] - 1)
    return cutout_rgba[rows, columns, :3].astype(np.uint8)


class Step1XBackend:
    route = "B"

    def __init__(self, weights: Path) -> None:
        import torch
        from step1x3d_geometry.models.pipelines.pipeline import Step1X3DGeometryPipeline

        self._torch = torch
        self._shared = Shared(weights)
        self._pipeline = Step1X3DGeometryPipeline.from_pretrained(
            str(weights / "stepfun-ai__Step1X-3D"), subfolder="Step1X-3D-Geometry-1300m"
        ).to("cuda")

    def simplifier(self) -> Simplifier:
        return quadric_simplify

    def concept(self, prompt: str, seed: int) -> bytes:
        return self._shared.concept(prompt, seed)

    def cutout(self, picture: bytes) -> bytes:
        return self._shared.cutout(picture)

    def mesh(self, cutout: bytes, seed: int, request: Mapping[str, Any]) -> RawMesh:
        from PIL import Image

        image = Image.open(io.BytesIO(cutout)).convert("RGBA")
        generator = self._torch.Generator(device="cuda").manual_seed(seed)
        out = self._pipeline(
            image, guidance_scale=7.5, num_inference_steps=50, generator=generator, output_type="np"
        )
        vertices, faces = out.mesh[0]
        vertices = np.asarray(vertices, dtype=np.float64)
        colours = project_colours(vertices, np.asarray(image))
        return RawMesh(
            Mesh(vertices, np.asarray(faces, dtype=np.int64), colours), up="+Y", front="+Z"
        )

    def runtime(self) -> dict[str, Any]:
        return dict(self._shared.runtime(), model="stepfun-ai/Step1X-3D geometry 1300m")
