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

__all__ = ["TrellisBackend", "pipeline_view", "sdpa_attention"]

#: The zeroth spherical harmonic's constant: colour = 0.5 + C0 * dc.
_C0: Final = 0.28209479177387814
_NEIGHBOURS: Final = 8


class TrellisBackend:
    route = "A"

    def __init__(self, weights: Path) -> None:
        os.environ.setdefault("ATTN_BACKEND", "xformers")
        os.environ.setdefault("SPCONV_ALGO", "native")
        import xformers.ops
        from trellis.pipelines import TrellisImageTo3DPipeline

        # TRELLIS calls xformers.ops.memory_efficient_attention by attribute; on an RTX PRO 6000
        # (Blackwell) xformers 0.0.32.post2 sends some calls to its Hopper FlashAttention-3 kernel,
        # which fails with "invalid argument" (measured on Nebius, 2026-10-06). PyTorch's own
        # attention runs there, so every call goes to it instead.
        xformers.ops.memory_efficient_attention = sdpa_attention
        self._shared = Shared(weights)
        view = weights.parent / "trellis-view"
        self._left_out = pipeline_view(weights / "microsoft__TRELLIS-image-large", view)
        self._pipeline = TrellisImageTo3DPipeline.from_pretrained(str(view))
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
        return dict(
            self._shared.runtime(),
            model="microsoft/TRELLIS-image-large",
            models_not_loaded=self._left_out,
            attention="torch scaled_dot_product_attention in place of xformers",
        )


def pipeline_view(weights: Path, view: Path) -> list[str]:
    """A directory TRELLIS loads from: its pipeline.json naming only the models the weights hold.

    TRELLIS loads every model its pipeline.json lists, and one it cannot find locally is looked
    up as a Hugging Face repository instead, which the job's offline mode refuses (measured on
    Nebius, 2026-10-06). The weights manifest leaves out the radiance-field decoder and the
    encoders, which route A never runs, so the view lists the rest and links their files. Returns
    the models left out, in name order."""
    import json

    document = json.loads((weights / "pipeline.json").read_text(encoding="utf-8"))
    listed = document["args"]["models"]
    kept = {
        name: path
        for name, path in listed.items()
        if (weights / f"{path}.json").is_file() and (weights / f"{path}.safetensors").is_file()
    }
    view.mkdir(parents=True, exist_ok=True)
    document["args"]["models"] = kept
    (view / "pipeline.json").write_text(json.dumps(document, indent=1), encoding="utf-8")
    link = view / "ckpts"
    if not link.exists():
        link.symlink_to(weights / "ckpts", target_is_directory=True)
    return sorted(set(listed) - set(kept))


def sdpa_attention(
    q: Any, k: Any, v: Any, attn_bias: Any = None, p: float = 0.0, scale: Any = None, op: Any = None
) -> Any:
    """xformers' memory_efficient_attention contract, computed by PyTorch's attention.

    Tensors are (batch, tokens, heads, channels). A block-diagonal bias (one batch row holding
    many sequences, as TRELLIS's sparse and windowed attention pass) is read from its sequence
    starts: blocks of equal query and key lengths are gathered into one batched call, so a layer
    of equal windows costs one call, not one per window. Dropout and other biases are refused."""
    import torch
    from torch.nn.functional import scaled_dot_product_attention as attend

    if p:
        raise ValueError("attention dropout is not supported here")

    def run(qb: Any, kb: Any, vb: Any) -> Any:
        out = attend(qb.transpose(1, 2), kb.transpose(1, 2), vb.transpose(1, 2), scale=scale)
        return out.transpose(1, 2)

    if attn_bias is None:
        return run(q, k, v)
    if not hasattr(attn_bias, "q_seqinfo") or q.shape[0] != 1:
        raise ValueError(f"attention bias {type(attn_bias).__name__} is not supported here")
    q_starts = list(attn_bias.q_seqinfo.seqstart_py)
    k_starts = list(attn_bias.k_seqinfo.seqstart_py)
    out = q.new_empty(q.shape[:-1] + (v.shape[-1],))
    groups: dict[tuple[int, int], list[int]] = {}
    for i in range(len(q_starts) - 1):
        lengths = (q_starts[i + 1] - q_starts[i], k_starts[i + 1] - k_starts[i])
        groups.setdefault(lengths, []).append(i)
    for (q_length, k_length), blocks in groups.items():
        q_first = torch.tensor([q_starts[i] for i in blocks], device=q.device)
        k_first = torch.tensor([k_starts[i] for i in blocks], device=q.device)
        q_index = q_first[:, None] + torch.arange(q_length, device=q.device)
        k_index = k_first[:, None] + torch.arange(k_length, device=q.device)
        out[0, q_index] = run(q[0, q_index], k[0, k_index], v[0, k_index])
    return out
