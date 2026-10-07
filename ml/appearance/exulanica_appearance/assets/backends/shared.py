"""What every route shares: the concept picture, the cut-out, the simplifier and the runtime.

The concept picture is Z-Image-Turbo through diffusers at its pinned files, with no control,
at 1024 px, 9 steps and no guidance (the settings its model card gives). The cut-out is BiRefNet
at 1024 px; its mask becomes the picture's alpha. The simplifier is fast-simplification's quadric
decimation (MIT), which collapses edges by quadric error and carries no vertex colour, so colour
is carried to the simplified vertices from the nearest original vertex.
"""

from __future__ import annotations

import io
import platform
from pathlib import Path
from typing import Any, Final

import numpy as np
from exulanica_pieces.geometry.mesh import Mesh

__all__ = ["CONCEPT_SETTINGS", "Shared", "quadric_simplify"]

CONCEPT_SETTINGS: Final = {"guidance_scale": 0, "height": 1024, "steps": 9, "width": 1024}


def quadric_simplify(mesh: Mesh, target: int) -> tuple[Mesh, dict[str, object]]:
    import fast_simplification
    from scipy.spatial import cKDTree

    reduction = 1 - target / len(mesh.triangles)
    points, faces = fast_simplification.simplify(
        mesh.positions.astype(np.float32),
        mesh.triangles.astype(np.int32),
        target_reduction=reduction,
    )
    # The decimation lands a little either side of the target; tighten until it holds.
    while len(faces) > target and reduction < 0.999:
        reduction = min(0.999, reduction + 0.01)
        points, faces = fast_simplification.simplify(
            mesh.positions.astype(np.float32),
            mesh.triangles.astype(np.int32),
            target_reduction=reduction,
        )
    nearest = cKDTree(mesh.positions).query(points)[1]
    out = Mesh(points.astype(np.float64), faces.astype(np.int64), mesh.colours[nearest])
    return out, {
        "simplifier": "fast-simplification/quadric",
        "target_reduction_per_mille": round(reduction * 1000),
    }


class Shared:
    """The concept and cut-out models, each loaded on its first use and kept for the job.

    Route B starts from route A's cut-outs and its lock pins a diffusers without Z-Image (Step1X-3D
    needs that release; measured on Nebius, 2026-10-06), so a route B job loads neither model, and
    its weights leave them out."""

    def __init__(self, weights: Path) -> None:
        import torch

        self._torch = torch
        self._weights = weights
        self._concept_model: Any = None
        self._cutout_model: Any = None

    def _concept(self, *args: Any, **kwargs: Any) -> Any:
        if self._concept_model is None:
            directory = self._weights / "Tongyi-MAI__Z-Image-Turbo"
            if not directory.is_dir():
                raise RuntimeError(
                    "this job holds no concept model; start its items from a cut-out"
                )
            from diffusers import ZImagePipeline

            self._concept_model = ZImagePipeline.from_pretrained(
                str(directory), torch_dtype=self._torch.bfloat16
            ).to("cuda")
        return self._concept_model(*args, **kwargs)

    def _cutout(self, *args: Any) -> Any:
        if self._cutout_model is None:
            directory = self._weights / "ZhengPeng7__BiRefNet"
            if not directory.is_dir():
                raise RuntimeError(
                    "this job holds no cut-out model; start its items from a cut-out"
                )
            from transformers import AutoModelForImageSegmentation

            self._cutout_model = (
                AutoModelForImageSegmentation.from_pretrained(
                    str(directory), trust_remote_code=True
                )
                .to("cuda")
                .eval()
            )
        return self._cutout_model(*args)

    def concept(self, prompt: str, seed: int) -> bytes:
        torch = self._torch
        image = self._concept(
            prompt,
            height=CONCEPT_SETTINGS["height"],
            width=CONCEPT_SETTINGS["width"],
            num_inference_steps=CONCEPT_SETTINGS["steps"],
            guidance_scale=float(CONCEPT_SETTINGS["guidance_scale"]),
            generator=torch.Generator("cuda").manual_seed(seed),
        ).images[0]
        return _png(image)

    def cutout(self, picture: bytes) -> bytes:
        torch = self._torch
        from PIL import Image
        from torchvision import transforms

        image = Image.open(io.BytesIO(picture)).convert("RGB")
        prepare = transforms.Compose(
            [
                transforms.Resize((1024, 1024)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )
        with torch.no_grad():
            mask = self._cutout(prepare(image).unsqueeze(0).to("cuda"))[-1].sigmoid().cpu()[0, 0]
        alpha = Image.fromarray((mask.numpy() * 255).round().astype(np.uint8)).resize(image.size)
        cut = image.convert("RGBA")
        cut.putalpha(alpha)
        return _png(cut)

    def runtime(self) -> dict[str, Any]:
        torch = self._torch
        properties = torch.cuda.get_device_properties(0)
        return {
            "cuda": torch.version.cuda,
            "gpu": properties.name,
            "gpu_memory_mib": properties.total_memory // (1 << 20),
            "machine": platform.platform(),
            "python": platform.python_version(),
            "torch": torch.__version__,
        }


def _png(image: Any) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
