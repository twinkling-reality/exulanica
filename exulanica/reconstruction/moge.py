"""MoGe-2 behind the depth protocol.

``docs/model-and-service-selection.md`` selects MoGe-2 ViT-L, MIT, run locally, with MoGe-3 on a
Linux GPU as the fallback because MoGe-3 has no macOS path. That note turned out to be exactly
right and worth restating with what was found: MoGe 3.0.0 requires ``torchvision>=0.19``,
and no torchvision wheel matching this platform exists for the current torch, so the package
installs only without its transitive dependencies. What it actually needs at run time is torch,
numpy, opencv and ``utils3d_moge``, and the last of those is a different package from the
``utils3d`` on PyPI, which is an unrelated stub. Installing the PyPI one produces
``module 'utils3d' has no attribute 'pt'`` a long way from the cause.

**Torch is an optional dependency and this module is not imported by the package barrel.** An
instance with no depth model still ingests a corpus and reports the stage as not run, which is the
same arrangement the vision stage has and for the same reason: a pipeline that could not run
without a 1.3 GB checkpoint is one that does not run.

**The caller states the checkpoint.** The repository and its full revision are read from the
manifest's ``local_roles.depth`` by whoever builds this, and nothing here defaults either.

**Three things measured here rather than assumed:**

*   **Metric scale is read off the checkpoint.** MoGe-2 applies a ``metric_scale`` when the model
    carries a ``scale_head``, so ``metric`` is ``hasattr(model, 'scale_head')`` rather than a
    constant keyed off the model name. A variant without one produces shape up to an unknown
    factor, the island built from it is not metric, and a spatial question over it refuses instead
    of estimating.
*   **fp16 is off on MPS.** ``infer(use_fp16=True)`` is the default and raises
    ``Input type (c10::Half) and bias type (float) should be the same`` on Metal. Verified by
    running it.
*   **The image is downscaled before inference, not after.** MoGe returns a point per input pixel,
    so a 1600x1200 photograph yields 1.9M points and a 34 MB file. The stage's ``max_edge_px``
    bounds the input, which bounds the output, the cost and the storage in one place.
"""

from __future__ import annotations

import math
from typing import Any, Final

from PIL import Image

from exulanica.reconstruction.depth import DepthPrediction

__all__ = [
    "MoGeDepthModel",
    "checkpoint_ref",
    "to_opm_frame",
]

#: Passed to `infer`. Trades tokens for detail; 6 is the level the timing above was measured at.
_RESOLUTION_LEVEL: Final = 6


class DepthModelUnavailable(RuntimeError):
    """Torch or MoGe is not installed. Raised with what to install rather than an ImportError."""


def checkpoint_ref(model_id: str, revision: str) -> str:
    """``repo@revision``: the identity every point map records and the depth stage binds."""
    return f"{model_id}@{revision}"


def to_opm_frame(points: list[float]) -> list[float]:
    """MoGe's camera frame to the container's.

    MoGe returns OpenCV camera coordinates: x right, y DOWN, z FORWARD. The ``.opm`` container is
    +Y up and -Z forward, which is what both renderer bindings assume and what the viewpoint
    written into the header describes. The conversion is a sign flip on two axes and it is a
    function rather than a comment because getting it wrong produces a world that renders
    perfectly and is upside down and behind the camera.
    """
    out = points[:]
    for index in range(1, len(out), 3):
        out[index] = -out[index]
    for index in range(2, len(out), 3):
        out[index] = -out[index]
    return out


def _fit(size: tuple[int, int], max_edge: int) -> tuple[int, int]:
    width, height = size
    longest = max(width, height)
    if longest <= max_edge:
        return (max(1, width), max(1, height))
    scale = max_edge / longest
    return (max(1, round(width * scale)), max(1, round(height * scale)))


class MoGeDepthModel:
    """MoGe-2, loaded once and reused. Not thread safe, and not intended to be."""

    def __init__(
        self,
        *,
        model_id: str,
        revision: str,
        max_edge_px: int = 512,
        device: str | None = None,
    ) -> None:
        if not isinstance(model_id, str) or not model_id:
            raise ValueError("a MoGe checkpoint is named by its repository identifier")
        if (
            not isinstance(revision, str)
            or len(revision) != 40
            or any(character not in "0123456789abcdef" for character in revision)
        ):
            raise ValueError("a MoGe checkpoint revision must be a full lowercase Git commit")
        try:
            import torch
            from moge.model.v2 import MoGeModel
        except ImportError as exc:  # pragma: no cover - exercised by not installing it
            raise DepthModelUnavailable(
                "reconstruction needs torch and MoGe, which are an optional install because "
                "they are a 1.3 GB checkpoint and a platform-specific wheel. See the "
                "reconstruction extra in pyproject.toml."
            ) from exc

        self._torch = torch
        self._model_id = checkpoint_ref(model_id, revision)
        self._max_edge_px = max_edge_px
        resolved = device or (
            "mps"
            if torch.backends.mps.is_available()
            else "cuda"
            if torch.cuda.is_available()
            else "cpu"
        )
        self._device = torch.device(resolved)
        pretrained = MoGeModel.from_pretrained(model_id, revision=revision)
        self._model = pretrained.to(self._device).eval()
        # Read from the loaded checkpoint, not from its name. `infer` multiplies the points by a
        # recovered `metric_scale` only when the model carries a scale head, so this is the same
        # condition the model itself branches on.
        self._metric = hasattr(self._model, "scale_head")

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def metric(self) -> bool:
        return self._metric

    def predict(self, image: Image.Image) -> DepthPrediction:
        torch = self._torch
        rgb = image.convert("RGB")
        width, height = _fit(rgb.size, self._max_edge_px)
        if (width, height) != rgb.size:
            rgb = rgb.resize((width, height), Image.Resampling.LANCZOS)

        tensor = (
            torch.frombuffer(bytearray(rgb.tobytes()), dtype=torch.uint8)
            .reshape(height, width, 3)
            .permute(2, 0, 1)
            .float()
            .div(255)
            .to(self._device)
        )
        with torch.no_grad():
            # fp16 off: it raises a dtype mismatch on Metal, verified rather than assumed.
            out: dict[str, Any] = self._model.infer(
                tensor, resolution_level=_RESOLUTION_LEVEL, use_fp16=False
            )

        points = out["points"].detach().to("cpu").flatten().tolist()
        mask = bytes(out["mask"].detach().to("cpu").flatten().to(torch.uint8).tolist())
        return DepthPrediction(
            width=width,
            height=height,
            points=to_opm_frame(points),
            valid=mask,
            fov_y_degrees=_fov_y_degrees(out["intrinsics"]),
            metric=self._metric,
            model_id=self._model_id,
        )


def _fov_y_degrees(intrinsics: Any) -> float:
    """Vertical field of view from MoGe's normalised intrinsics.

    MoGe builds them with ``intrinsics_from_focal_center(fx, fy, 0.5, 0.5)``, so the focal lengths
    are in units of image width and height rather than pixels and the principal point is the
    centre. The half-angle is therefore ``atan(0.5 / fy)`` with no image size involved, which is
    why this needs nothing but the matrix.
    """
    fy = float(intrinsics[1][1])
    if fy <= 0:
        raise ValueError(f"the model returned a non-positive vertical focal length: {fy}")
    return math.degrees(2 * math.atan(0.5 / fy))
