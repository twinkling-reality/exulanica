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
        from step1x3d_geometry.models.autoencoders.surface_extractors import MCSurfaceExtractor
        from step1x3d_geometry.models.autoencoders.volume_decoders import VanillaVolumeDecoder
        from step1x3d_geometry.models.pipelines.pipeline import Step1X3DGeometryPipeline

        self._torch = torch
        self._work = weights.parent
        self._shared = Shared(weights)
        self._pipeline = Step1X3DGeometryPipeline.from_pretrained(
            str(weights / "stepfun-ai__Step1X-3D"),
            subfolder="Step1X-3D-Geometry-1300m",
            torch_dtype=torch.float32,
        ).to("cuda")
        self._pipeline.vae.to(torch.float32)
        # The configured hierarchical decoder evaluates only cells near the surface and marks
        # every other cell NaN, so marching cubes makes non-finite positions there that upstream's
        # trimesh export quietly removes (measured on Nebius, 2026-10-06: about half of every
        # mesh). The dense decoder evaluates every cell instead, so nothing needs removing.
        self._volume = VanillaVolumeDecoder()
        self._surface = MCSurfaceExtractor()

    def simplifier(self) -> Simplifier:
        return quadric_simplify

    def concept(self, prompt: str, seed: int) -> bytes:
        return self._shared.concept(prompt, seed)

    def cutout(self, picture: bytes) -> bytes:
        return self._shared.cutout(picture)

    def mesh(self, cutout: bytes, seed: int, request: Mapping[str, Any]) -> RawMesh:
        from PIL import Image

        image = Image.open(io.BytesIO(cutout)).convert("RGBA")
        # Step1X-3D's input check refuses the very types it names (a PIL image or a tensor) and
        # accepts a file path, which its own inference script passes; and it decodes bfloat16
        # latents with its VAE cast to float16, which gave non-finite positions on every item
        # (measured on Nebius, 2026-10-06). Both read in the pinned tree. So the cut-out goes in
        # as a file on the machine's disk, the latents come out, and the VAE decodes them in
        # float32 with the arguments the pipeline itself passes.
        torch = self._torch
        path = self._work / "step1x-input.png"
        path.write_bytes(cutout)
        generator = torch.Generator(device="cuda").manual_seed(seed)
        out = self._pipeline(
            str(path), guidance_scale=7.5, num_inference_steps=50, generator=generator,
            output_type="latent",
        )  # fmt: skip
        vae = self._pipeline.vae
        latents = out.mesh.float()
        with torch.no_grad():
            decoded = vae.decode(latents)
            grid = self._volume(
                decoded, vae.query, bounds=1.05, octree_resolution=384, num_chunks=65536,
                enable_pbar=False,
            )[0]  # fmt: skip
            meshes = self._surface(grid, mc_level=0.0, bounds=1.05, octree_resolution=384)
        result = meshes[0]
        if result is None:
            raise RuntimeError("marching cubes found no surface in the decoded field")
        finite = torch.isfinite(result.verts).all(dim=-1)
        if not bool(finite.all()):
            # Said with where it starts, so the cause is found rather than the vertices dropped.
            raise RuntimeError(
                f"{int((~finite).sum())} of {len(finite)} positions are not finite; latents "
                f"finite: {bool(torch.isfinite(latents).all())}, decoded field finite: "
                f"{bool(torch.isfinite(decoded).all())}, grid finite: "
                f"{bool(torch.isfinite(grid).all())}"
            )
        vertices = result.verts.detach().float().cpu().numpy().astype(np.float64)
        faces = result.faces.detach().cpu().numpy().astype(np.int64)
        colours = project_colours(vertices, np.asarray(image))
        return RawMesh(Mesh(vertices, faces, colours), up="+Y", front="+Z")

    def runtime(self) -> dict[str, Any]:
        return dict(self._shared.runtime(), model="stepfun-ai/Step1X-3D geometry 1300m")
