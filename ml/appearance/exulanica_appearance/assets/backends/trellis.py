"""Route A: TRELLIS-image-large makes the shape and the colour.

The mesh decoder gives the shape; the Gaussian decoder gives colour, sampled at each mesh vertex
from its nearest Gaussians (the zeroth spherical harmonic, weighted by opacity over distance), so
no rasteriser is needed. TRELLIS's own GLB export, which bakes through nvdiffrast, is not used.
TRELLIS's frame is +Z up with its front toward -Y; its own exporter makes the same turn into glTF.

Route C can run TRELLIS's second stage alone (:func:`second_stage`): its structured latent sampled
and decoded on a sparse structure the caller gives, rather than on one TRELLIS's first stage
infers from the picture. Its method names and parameters are read from TRELLIS at the pinned
commit (:data:`PIPELINE_SIGNATURES`), and a pipeline whose methods differ is refused by name
before any weights load (:func:`check_pipeline`).
"""

from __future__ import annotations

import inspect
import io
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import numpy as np
from exulanica_pieces.canonical import Refused
from exulanica_pieces.geometry.mesh import Mesh, Simplifier

from exulanica_appearance.assets.backends.shared import Shared, quadric_simplify
from exulanica_appearance.assets.job import RawMesh

__all__ = [
    "PIPELINE_SIGNATURES",
    "STRUCTURE_RESOLUTION",
    "TrellisBackend",
    "check_coords",
    "check_pipeline",
    "pipeline_view",
    "raw_mesh",
    "sdpa_attention",
    "second_stage",
]

#: The zeroth spherical harmonic's constant: colour = 0.5 + C0 * dc.
_C0: Final = 0.28209479177387814
_NEIGHBOURS: Final = 8
#: The side of TRELLIS's sparse structure grid: its first stage decodes a 64-cubed occupancy.
STRUCTURE_RESOLUTION: Final = 64
#: The parameters of the pipeline's methods the second stage calls, as TrellisImageTo3DPipeline
#: declares them at the pinned commit (trellis/pipelines/trellis_image_to_3d.py, read 2026-10-07).
PIPELINE_SIGNATURES: Final = {
    "preprocess_image": ("self", "input"),
    "get_cond": ("self", "image"),
    "sample_slat": ("self", "cond", "coords", "sampler_params"),
    "decode_slat": ("self", "slat", "formats"),
}


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
        check_pipeline(TrellisImageTo3DPipeline)
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

        image = Image.open(io.BytesIO(cutout)).convert("RGBA")
        # An image with alpha skips TRELLIS's background removal and is cropped and resized by it.
        outputs = self._pipeline.run(
            image, seed=seed, formats=["mesh", "gaussian"], preprocess_image=True
        )
        return raw_mesh(outputs)

    def mesh_on(self, cutout: bytes, seed: int, coords: np.ndarray) -> RawMesh:
        """The mesh TRELLIS's second stage makes on ``coords`` (N x 4, int32: batch index 0, then
        x, y and z in its 64-cubed grid) from the cut-out, read as :meth:`mesh` reads route A's."""
        import torch
        from PIL import Image

        image = Image.open(io.BytesIO(cutout)).convert("RGBA")
        return raw_mesh(second_stage(self._pipeline, torch, image, seed, coords))

    def runtime(self) -> dict[str, Any]:
        return dict(
            self._shared.runtime(),
            model="microsoft/TRELLIS-image-large",
            models_not_loaded=self._left_out,
            attention="torch scaled_dot_product_attention in place of xformers",
        )


def raw_mesh(outputs: Mapping[str, Any]) -> RawMesh:
    """A pipeline's decoded mesh, coloured from its decoded Gaussians: each vertex the mean of its
    nearest Gaussians' zeroth harmonic, weighted by opacity over distance. TRELLIS's frame: +Z up,
    the front toward -Y."""
    from scipy.spatial import cKDTree

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


def check_pipeline(pipeline: type) -> None:
    """Refuse, by method and parameters, a pipeline class whose methods are not the ones the second
    stage calls as TRELLIS at the pinned commit declares them (:data:`PIPELINE_SIGNATURES`)."""
    for name, expected in PIPELINE_SIGNATURES.items():
        method = getattr(pipeline, name, None)
        if not callable(method):
            raise Refused(f"TRELLIS's pipeline has no method {name}")
        found = tuple(inspect.signature(method).parameters)
        if found != expected:
            raise Refused(
                f"TRELLIS's {name} takes ({', '.join(found)}), not ({', '.join(expected)})"
            )


def check_coords(coords: np.ndarray) -> None:
    """Refuse a sparse structure TRELLIS's second stage cannot take: it is int32, N rows of batch
    index, x, y and z, at least one row, one object (every batch index 0), each voxel inside the
    64-cubed grid, and each named once."""
    if not isinstance(coords, np.ndarray) or coords.dtype != np.int32:
        raise Refused("a structure's coordinates are an int32 array")
    if coords.ndim != 2 or coords.shape[1] != 4:
        raise Refused("a structure's coordinates are rows of batch index, x, y and z")
    if len(coords) == 0:
        raise Refused("a structure holds at least one voxel")
    if (coords[:, 0] != 0).any():
        raise Refused("a structure is one object: every batch index is 0")
    if (coords[:, 1:] < 0).any() or (coords[:, 1:] >= STRUCTURE_RESOLUTION).any():
        raise Refused(f"a structure's voxels lie from 0 to {STRUCTURE_RESOLUTION - 1} on each axis")
    if len(np.unique(coords, axis=0)) != len(coords):
        raise Refused("a structure names each voxel once")


def second_stage(pipeline: Any, torch: Any, image: Any, seed: int, coords: np.ndarray) -> Any:
    """TRELLIS's ``run`` without its first stage, on the structure ``coords`` gives.

    The steps and their order are ``run``'s at the pinned commit, under ``torch.no_grad``:
    1. the picture prepared (``preprocess_image``) and encoded (``get_cond``);
    2. the generator seeded with ``seed``, as ``run`` seeds it before sampling, so a receipt's
       seed makes the same latent;
    3. the structured latent sampled on the structure (``sample_slat``) with the pipeline's own
       sampler settings;
    4. the mesh and the Gaussians decoded (``decode_slat``).

    The coordinates are checked first and moved to the pipeline's device as int32, as the first
    stage gives them."""
    check_coords(coords)
    with torch.no_grad():
        cond = pipeline.get_cond([pipeline.preprocess_image(image)])
        torch.manual_seed(seed)
        structure = torch.from_numpy(coords).to(pipeline.device)
        slat = pipeline.sample_slat(cond, structure)
        return pipeline.decode_slat(slat, ["mesh", "gaussian"])


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
