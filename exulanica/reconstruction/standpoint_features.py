"""Local features for the standpoint join: COLMAP's SIFT, through pycolmap, on the CPU.

**Why COLMAP's and not OpenCV's.** The join runs in the scene worker, which already carries
pycolmap for pose recovery; OpenCV is not in that process's extra, and a second feature library
would be a new dependency for no measured gain. MEASURED 2026-09-23 on a 1024 x 768 synthetic
courtyard render: OpenCV's SIFT found 149 keypoints and COLMAP's found 660 at its default peak
threshold and 1,908 at 0.004. Both extractors are deterministic on repeat.

**The peak threshold is the policy's, not a default.** COLMAP's 0.0067 is tuned for photographs
of textured objects; the stage parameter says what this join uses, so changing it re-keys every
standpoint scene.

Like :mod:`exulanica.reconstruction.moge`, this module is not imported by the package barrel:
pycolmap is an optional extra, and an instance without it reports the stage as not run.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["FeaturesUnavailable", "PycolmapSift"]


class FeaturesUnavailable(RuntimeError):
    """pycolmap is not installed. Raised with what to install rather than an ImportError."""


class PycolmapSift:
    """SIFT keypoints and L2-normalised descriptors for one greyscale image."""

    def __init__(self, *, max_features: int, peak_threshold: float, threads: int) -> None:
        try:
            import numpy
            import pycolmap
        except ImportError as error:  # pragma: no cover - exercised by not installing it
            raise FeaturesUnavailable(
                "the standpoint join needs pycolmap and numpy, which the pose extra installs"
            ) from error
        options = pycolmap.FeatureExtractionOptions()
        options.sift.max_num_features = max_features
        options.sift.peak_threshold = peak_threshold
        options.num_threads = threads
        options.use_gpu = False
        self._numpy = numpy
        self._extractor = pycolmap.FeatureExtractor.create(options, pycolmap.Device.cpu)
        self._identity = {
            "contract": "pycolmap-sift",
            "pycolmap": str(pycolmap.__version__),
            "max_num_features": str(max_features),
            "peak_threshold_ppm": str(round(peak_threshold * 1_000_000)),
        }

    @property
    def identity(self) -> Mapping[str, str]:
        return dict(self._identity)

    def extract(self, gray: Any) -> tuple[Any, Any]:
        """``(xy, descriptors)``: pixel positions (image spans [0, width]) and unit descriptors."""
        np = self._numpy
        image = np.ascontiguousarray(gray, dtype=np.uint8)
        keypoints, descriptors = self._extractor.extract_from_uint8_array(image)
        xy = np.array([[point.x, point.y] for point in keypoints], dtype=np.float64).reshape(-1, 2)
        vectors = np.asarray(descriptors.data, dtype=np.float32).reshape(-1, 128)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.maximum(norms, 1e-12)
        return xy, vectors
