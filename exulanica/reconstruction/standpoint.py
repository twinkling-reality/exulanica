"""Several photographs taken from one standpoint, joined by the rotation between them.

Most people's photographs of a place were taken from about where they stood: they turned, maybe
zoomed, and took a few more. Multi-view reconstruction needs the camera to move, so those sets
give it nothing to triangulate, and pose recovery refuses them ("no good initial image pair").
What they do have is overlap between photographs taken from one point, and between two such
photographs the geometry is exactly a rotation: every direction seen in one is the same
direction seen in the other, turned. This module measures that rotation from matched features,
joins every photograph that overlaps another into one arrangement, gives each photograph the
depth the depth model estimated for it, and brings those depths to one scale where two
photographs see the same thing. The result is :class:`~exulanica.reconstruction.
standpoint_record.StandpointRecord`.

**Nothing is invented.** A photograph contributes only what it showed; a direction no photograph
covered is recorded as not covered, and nothing here fills it (ADR-0008).

**Refused by name, never joined wrong.** A pair of photographs is joined only when the rotation
explains them. Three situations look like overlap and are not, and each has its own code:

* ``insufficient_overlap``: too few features agree, or they cluster in one corner, so nothing
  says the photographs share a view.
* ``moved_between_photographs``: the photographs were taken from places further apart than the
  policy allows. Matched points at different depths shift by different angles when the camera
  moves, which a rotation cannot explain; the translation is estimated from that parallax and the
  depth model's depth, and used ONLY to recognise this case. It never places anything.
* ``scene_changed``: the rotation explains the matched features, but where the photographs overlap
  they show different things over more of the view than the policy allows: one photograph,
  carried into the other through the measured turn, differs from it in connected regions, so
  something was added, removed or moved between them.

A photograph that does not state its lens's focal length (EXIF ``FocalLengthIn35mmFilm``) is kept
apart as ``focal_length_unstated`` before anything is matched: the depth model's own field of view
was measured to join such photographs visibly wrong, and a turn measured through the wrong lens
is the wrong turn.

A pair that survives all three can still disagree with the rest of the set, which the rotation
solve measures; the worst such pair is dropped as ``inconsistent_with_set`` and the solve repeated.

**What a pair records is the turn that lines the photographs up from one point.** It is fitted
to the matched features without translation, because the arrangement draws every photograph from
one standpoint; the camera's own turn differs from it by the parallax a hand-held movement made.

**What the translation estimate is and is not.** It comes from the depth model's depth, whose
scale nobody has measured, so it is metres only as far as the model's own scale is. The policy's
bound is chosen against that: a hand-held turn moves a phone by tens of centimetres and must be
joined; a few steps sideways must be refused. Photographs within the bound still carry that small
movement as parallax at the seam, and every pair records how large it is.

**A cause is named only where its measurement holds (stage version 2).** Matched features that
all lie at about one distance, one facade across a square, cannot tell a step aside from a turn:
the parallax a step makes is the same at every one of them, and a turn absorbs it. So a pair is
named moved only when the movement estimated would shift the nearer matched points against the
farther ones by the policy's angle (``min_translation_parallax_deg``), and the camera
counts as having stood still only when a movement of the moved bound would have shifted them so; a
pair whose features cannot show a movement is never named moved. A pair is named ``scene_changed``
only when the camera is measured to have stood within the policy's hand-held bound
(``still_max_translation_m``), because a disagreement beside a movement the depth model's scale
may understate cannot be told from a change. Between the two, or without a measurement, a pair
joins only if a pure turn explains what the photographs share, and is otherwise refused as
``insufficient_overlap``: what they share does not establish one standpoint. The translation of
version 2 is fitted with a relative zoom between the pair's lenses, held to the stated lenses by
the focal prior, so that a focal length stated a few percent off is not read as a step forward.
Where the camera stood still, a tile at a depth edge whose parallax under the measured movement
exceeds the comparison's search is not compared: the far surface beside a near post is uncovered
by the movement, not changed. Version 1's parameters name none of this and are decoded to exactly
what they meant.

**Up (stage version 2).** People hold a camera level only roughly, so the camera's own
horizontal axes lean with its roll. Version 2 takes up from the photographs' vertical edges: the
direction most perpendicular to the planes through the camera and each strong edge, sought from
the camera-axes estimate as a mode rather than a least-squares fit, so that a photograph with no
vertical structure adds background and not a pull. Where the edges do not stand out of that
background by the policy's ratio, the camera-axes estimate is kept and the record says so.

**Deterministic in the ADR-0017 sense.** No model runs here: MoGe-2 ran in the depth stage, and
this stage reads its point maps. Feature extraction is COLMAP's SIFT, measured deterministic on
repeat; every random choice comes from a generator seeded by the policy and the pair.

**numpy only.** The scene worker's image installs pycolmap and the numpy it pulls in, and nothing
else of the numeric stack, so the two image filters the join needs are written here.

**Every number is the policy's.** :class:`StandpointPolicy` is decoded from the stage's integer
parameters, which are inside its idempotency key, so a changed threshold re-keys every scene.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

import numpy as np
from PIL import Image

from exulanica.reconstruction.standpoint_record import (
    MICROPIXELS,
    MILLIDEGREES,
    PARTS_PER_BILLION,
    PARTS_PER_MILLION,
    ArrangedMember,
    Arrangement,
    MemberIntrinsics,
    MemberReading,
    StandpointMember,
    StandpointPair,
    StandpointRecord,
)
from exulanica.reconstruction.validation import OpmIntegrityError, validate_opm

__all__ = [
    "FULL_FRAME_DIAGONAL_MM",
    "FeatureExtractor",
    "StandpointExclusion",
    "StandpointInput",
    "StandpointPolicy",
    "UpFromEdges",
    "join_standpoint",
]

#: The diagonal of a 36 x 24 mm frame, which is what a 35 mm equivalent focal length is defined
#: against (EXIF 2.3, FocalLengthIn35mmFilm): the field of view along the image diagonal is the
#: one a lens of that focal length would give on that frame.
FULL_FRAME_DIAGONAL_MM: Final = math.hypot(36.0, 24.0)

#: Units the policy's integer parameters are written in.
_MILLI: Final = 1_000
_MICRO: Final = 1_000_000

#: How far scipy's Gaussian filter reaches, in standard deviations: its default ``truncate``, which
#: the version 1 join ran with. The filter below reproduces it (see :func:`_gaussian_filter`).
_GAUSSIAN_TRUNCATE: Final = 4.0

#: What a pair's rotation and translation are fitted with, by the name the policy gives. Version
#: 1's parameters name none: theirs is the rotation-and-translation fit, and decoding keeps it.
_PAIR_FIT_V1: Final = "rotation-translation"
#: Where the camera stood still, how tiles at depth edges are treated, by name. Version 1's
#: parameters name none: theirs compares every tile, and decoding keeps it.
_DISOCCLUSION_V1: Final = "none"


@dataclass(frozen=True, slots=True)
class UpFromEdges:
    """The vertical-edges up method's parameters (stage version 2), decoded and named.

    ``background_deg`` is the band of angles from perpendicular whose edge density stands for
    edges that are not vertical; ``min_evidence`` is how many times denser than it the mode must
    be for the edges to decide.
    """

    long_edge_px: int
    blur_px: float
    edge_fraction: float
    max_pixels: int
    kernel_deg: float
    search_deg: float
    background_deg: tuple[float, float]
    iterations: int
    min_evidence: float


@dataclass(frozen=True, slots=True)
class StandpointPolicy:
    """The stage's parameters, decoded once and named. See the stage registry for each reason.

    The fields after ``up_min_spread`` exist from stage version 2. Version 1's parameters decode
    to the values that keep what version 1 computed: the rotation-and-translation fit, no zoom,
    no hand-held bound or depth-spread requirement (two outcomes of the moved test, not three),
    every tile compared, and up from the cameras' horizontal axes.
    """

    feature_max_edge_px: int
    max_features: int
    peak_threshold: float
    feature_threads: int
    match_ratio: float
    ransac_iterations: int
    ransac_seed: int
    ransac_threshold_deg: float
    candidate_window_deg: float
    inlier_threshold_deg: float
    refine_iterations: int
    min_inliers: int
    coverage_grid: int
    min_inlier_cells: int
    max_translation_m: float
    translation_sigmas: float
    change_long_edge_px: int
    change_tile_px: int
    change_blur_px: float
    change_zncc_min: float
    change_flat_sigma: float
    change_flat_delta: float
    change_search_base_px: int
    change_search_max_px: int
    change_depth_uncertainty: float
    change_min_cluster_tiles: int
    max_changed_fraction: float
    max_edge_residual_deg: float
    exif_focal_mm_range: tuple[float, float]
    focal_prior_sigma: float
    focal_refine_matches: int
    focal_refine_iterations: int
    focal_refine_noise_deg: float
    focal_refine_min_inliers: int
    focal_refine_max_translation_m: float
    up_min_spread: float
    pair_fit: str
    zoom_prior_sigma: float
    still_max_translation_m: float | None
    min_translation_parallax_deg: float | None
    change_disocclusion: str
    change_edge_jump: float
    change_disocclusion_max_px: int
    change_disocclusion_min_share: float
    change_disocclusion_margin_px: int
    up_method: str
    up_edges: UpFromEdges | None

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> StandpointPolicy:
        features = params["features"]
        matching = params["matching"]
        rotation = params["rotation"]
        overlap = params["overlap"]
        translation = params["translation"]
        change = params["change"]
        intrinsics = params["intrinsics"]
        up = params["up"]
        if intrinsics["precedence"] != ["exif-35mm-equivalent"] or (
            intrinsics["unstated"] != "keep-apart"
        ):
            raise ValueError(
                "this join knows one intrinsics precedence and the policy names another"
            )
        if params["scale"]["gauge"] != "geometric-mean-of-member-depth-scales":
            raise ValueError("this join knows one scale gauge and the policy names another")
        if change["method"] != "registered-appearance":
            raise ValueError("this join knows one way to see a change and the policy names another")
        pair_fit = str(translation.get("fit", _PAIR_FIT_V1))
        if pair_fit not in _PAIR_FITS:
            raise ValueError(f"this join knows no pair fit named {pair_fit!r}")
        disocclusion = str(change.get("disocclusion", _DISOCCLUSION_V1))
        if disocclusion not in _DISOCCLUSIONS:
            raise ValueError(f"this join knows no depth-edge treatment named {disocclusion!r}")
        if (disocclusion == "depth-edge-parallax") != all(
            key in change
            for key in (
                "edge_jump_ppm",
                "disocclusion_max_px",
                "disocclusion_min_share_ppm",
                "disocclusion_margin_px",
            )
        ):
            raise ValueError("the depth-edge treatment and its parameters come together")
        up_method = str(up["method"])
        if up_method not in _UP_METHODS:
            raise ValueError(f"this join knows no way to estimate up named {up_method!r}")
        edges = up.get("edges")
        if (up_method == "vertical-edges") != (edges is not None):
            raise ValueError("the vertical-edges up method and its parameters come together")
        if edges is not None and up.get("fallback") != "camera-horizontal-axes":
            raise ValueError("the vertical-edges up method falls back to the camera axes only")
        still = translation.get("still_max_mm")
        parallax = translation.get("min_parallax_millidegrees")
        if (still is None) != (parallax is None):
            raise ValueError("a hand-held bound and a measured-parallax requirement come together")
        zoom_sigma = translation.get("zoom_prior_sigma_ppm")
        if (pair_fit == "rotation-translation-zoom") != (zoom_sigma is not None):
            raise ValueError("the zoom fit and its prior come together")
        low, high = intrinsics["exif_plausible_mm"]
        return cls(
            feature_max_edge_px=int(features["max_edge_px"]),
            max_features=int(features["max_features"]),
            peak_threshold=int(features["peak_threshold_ppm"]) / _MICRO,
            feature_threads=int(features["threads"]),
            match_ratio=int(matching["ratio_milli"]) / _MILLI,
            ransac_iterations=int(rotation["ransac_iterations"]),
            ransac_seed=int(rotation["ransac_seed"]),
            ransac_threshold_deg=int(rotation["ransac_threshold_millidegrees"]) / _MILLI,
            candidate_window_deg=int(rotation["candidate_window_millidegrees"]) / _MILLI,
            inlier_threshold_deg=int(rotation["inlier_threshold_millidegrees"]) / _MILLI,
            refine_iterations=int(rotation["refine_iterations"]),
            min_inliers=int(overlap["min_inliers"]),
            coverage_grid=int(overlap["coverage_grid"]),
            min_inlier_cells=int(overlap["min_inlier_cells"]),
            max_translation_m=int(translation["max_mm"]) / _MILLI,
            translation_sigmas=float(int(translation["confidence_sigmas"])),
            change_long_edge_px=int(change["long_edge_px"]),
            change_tile_px=int(change["tile_px"]),
            change_blur_px=int(change["blur_milli_px"]) / _MILLI,
            change_zncc_min=int(change["zncc_min_milli"]) / _MILLI,
            change_flat_sigma=int(change["flat_sigma_milli"]) / _MILLI,
            change_flat_delta=int(change["flat_delta_milli"]) / _MILLI,
            change_search_base_px=int(change["search_base_px"]),
            change_search_max_px=int(change["search_max_px"]),
            change_depth_uncertainty=int(change["depth_uncertainty_milli"]) / _MILLI,
            change_min_cluster_tiles=int(change["min_cluster_tiles"]),
            max_changed_fraction=int(change["max_changed_ppm"]) / _MICRO,
            max_edge_residual_deg=int(params["set"]["max_edge_residual_millidegrees"]) / _MILLI,
            exif_focal_mm_range=(float(low), float(high)),
            focal_prior_sigma=int(intrinsics["refine"]["prior_sigma_ppm"]) / _MICRO,
            focal_refine_matches=int(intrinsics["refine"]["matches_per_pair"]),
            focal_refine_iterations=int(intrinsics["refine"]["iterations"]),
            focal_refine_noise_deg=int(intrinsics["refine"]["noise_millidegrees"]) / _MILLI,
            focal_refine_min_inliers=int(intrinsics["refine"]["min_inliers"]),
            focal_refine_max_translation_m=int(intrinsics["refine"]["max_translation_mm"]) / _MILLI,
            up_min_spread=int(up["min_spread_ppm"]) / _MICRO,
            pair_fit=pair_fit,
            zoom_prior_sigma=0.0 if zoom_sigma is None else int(zoom_sigma) / _MICRO,
            still_max_translation_m=None if still is None else int(still) / _MILLI,
            min_translation_parallax_deg=None if parallax is None else int(parallax) / _MILLI,
            change_disocclusion=disocclusion,
            change_edge_jump=int(change.get("edge_jump_ppm", 0)) / _MICRO,
            change_disocclusion_max_px=int(change.get("disocclusion_max_px", 0)),
            change_disocclusion_min_share=int(change.get("disocclusion_min_share_ppm", 0)) / _MICRO,
            change_disocclusion_margin_px=int(change.get("disocclusion_margin_px", 0)),
            up_method=up_method,
            up_edges=(
                None
                if edges is None
                else UpFromEdges(
                    long_edge_px=int(edges["long_edge_px"]),
                    blur_px=int(edges["blur_milli_px"]) / _MILLI,
                    edge_fraction=int(edges["edge_fraction_ppm"]) / _MICRO,
                    max_pixels=int(edges["max_pixels"]),
                    kernel_deg=int(edges["kernel_millidegrees"]) / _MILLI,
                    search_deg=int(edges["search_millidegrees"]) / _MILLI,
                    background_deg=(
                        int(edges["background_millidegrees"][0]) / _MILLI,
                        int(edges["background_millidegrees"][1]) / _MILLI,
                    ),
                    iterations=int(edges["iterations"]),
                    min_evidence=int(edges["min_evidence_milli"]) / _MILLI,
                )
            ),
        )


class FeatureExtractor(Protocol):
    """Keypoints and unit descriptors for one greyscale image, and what produced them."""

    @property
    def identity(self) -> Mapping[str, str]: ...

    def extract(self, gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]: ...


@dataclass(frozen=True, slots=True)
class StandpointInput:
    """One member photograph, as the stage hands it over.

    ``image`` is the upright pixels the depth model read, so features and depth describe one
    picture: the masked derivative when anybody in it is hidden, never the original then.
    ``exif_focal_35mm`` is the photograph's own FocalLengthIn35mmFilm, or None when it states none.
    """

    ordinal: int
    member_ref: str
    point_map_artifact_ref: str
    point_map: bytes
    image: Image.Image
    image_sha256: str
    exif_focal_35mm: float | None


@dataclass(frozen=True, slots=True)
class StandpointExclusion:
    """A member photograph the stage did not hand over, and why: nothing of it is read."""

    ordinal: int
    member_ref: str


@dataclass(slots=True)
class _Member:
    source: StandpointInput
    point_map_sha256: str
    source_size: tuple[int, int]
    model_size: tuple[int, int]
    depth_focal_model: float
    focal_source: float
    stated_focal: float
    intrinsics_source: str
    ranges: np.ndarray
    gray: np.ndarray
    gray_focal: float
    xy: np.ndarray
    descriptors: np.ndarray
    bearings: np.ndarray
    inverse_range: np.ndarray

    @property
    def depth_focal_source(self) -> float:
        return self.depth_focal_model * self.source_size[1] / self.model_size[1]


@dataclass(frozen=True, slots=True)
class _PairResult:
    record: StandpointPair | None
    rotation: np.ndarray | None
    depth_ratio: float | None
    weight: float
    #: The matched features the pair's turn rests on, by index into each member's features.
    inliers: tuple[np.ndarray, np.ndarray] | None = None
    #: The provisional pass's rotation and translation of ``b`` into ``a`` (``b``'s depth units).
    motion: tuple[np.ndarray, np.ndarray] | None = None


# -- geometry helpers ----------------------------------------------------------------------------


def _rotation_from_vector(omega: np.ndarray) -> np.ndarray:
    """Rodrigues: the rotation by ``|omega|`` radians about ``omega``."""
    angle = float(np.linalg.norm(omega))
    if angle < 1e-15:
        return np.eye(3)
    axis = omega / angle
    k = np.array([[0.0, -axis[2], axis[1]], [axis[2], 0.0, -axis[0]], [-axis[1], axis[0], 0.0]])
    return np.eye(3) + math.sin(angle) * k + (1 - math.cos(angle)) * (k @ k)


def _vector_from_rotation(rotation: np.ndarray) -> np.ndarray:
    """The inverse of :func:`_rotation_from_vector`, for rotations short of a half turn."""
    cosine = max(-1.0, min(1.0, (float(np.trace(rotation)) - 1) / 2))
    angle = math.acos(cosine)
    if angle < 1e-12:
        return np.zeros(3)
    axis = np.array(
        [
            rotation[2, 1] - rotation[1, 2],
            rotation[0, 2] - rotation[2, 0],
            rotation[1, 0] - rotation[0, 1],
        ]
    ) / (2 * math.sin(angle))
    return axis * angle


def _kabsch(
    target: np.ndarray, source: np.ndarray, weights: np.ndarray | None = None
) -> np.ndarray:
    """The rotation ``R`` minimising ``sum w |target - R source|^2`` over unit vectors (rows)."""
    w = np.ones(len(source)) if weights is None else weights
    h = (source * w[:, None]).T @ target
    u, _s, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T)) or 1.0
    return vt.T @ np.diag([1.0, 1.0, d]) @ u.T


def _kabsch_batch(target: np.ndarray, source: np.ndarray) -> np.ndarray:
    """:func:`_kabsch` for a stack of hypotheses: ``(k, m, 3)`` rows each, equal weights."""
    h = np.einsum("kmi,kmj->kij", source, target)
    u, _s, vt = np.linalg.svd(h)
    v = np.transpose(vt, (0, 2, 1))
    det = np.linalg.det(v @ np.transpose(u, (0, 2, 1)))
    correction = np.tile(np.eye(3), (len(h), 1, 1))
    correction[:, 2, 2] = np.where(det < 0, -1.0, 1.0)
    return v @ correction @ np.transpose(u, (0, 2, 1))


def _angles_deg(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """The angle between rows of two unit-vector arrays, degrees, stable near zero."""
    cross = np.linalg.norm(np.cross(a, b), axis=1)
    dot = np.sum(a * b, axis=1)
    return np.degrees(np.arctan2(cross, dot))


def _stats_millidegrees(angles: np.ndarray) -> dict[str, int]:
    if len(angles) == 0:
        return {"max": 0, "p50": 0, "p90": 0}
    return {
        "max": round(float(np.max(angles)) * MILLIDEGREES),
        "p50": round(float(np.percentile(angles, 50)) * MILLIDEGREES),
        "p90": round(float(np.percentile(angles, 90)) * MILLIDEGREES),
    }


def _ppb(rotation: np.ndarray) -> tuple[int, ...]:
    return tuple(round(float(value) * PARTS_PER_BILLION) for value in rotation.reshape(-1))


# -- image filters, numpy only -------------------------------------------------------------------


def _gaussian_filter(image: np.ndarray, sigma: float, *, outside: str) -> np.ndarray:
    """``scipy.ndimage.gaussian_filter`` in numpy: separable, reaching ``_GAUSSIAN_TRUNCATE`` sigma.

    ``outside`` is ``"zero"`` (scipy's ``mode="constant"``) or ``"mirror"`` (scipy's default
    ``"reflect"``, the edge sample repeated). MEASURED 2026-09-24 against scipy 1.17.1 on 150
    random images at three widths: largest difference 6.7e-16 of the largest value.
    """
    radius = int(_GAUSSIAN_TRUNCATE * float(sigma) + 0.5)
    offsets = np.arange(-radius, radius + 1, dtype=np.float64)
    weights = np.exp(-0.5 * (offsets / sigma) ** 2)
    weights /= weights.sum()
    mode = {"zero": "constant", "mirror": "symmetric"}[outside]
    out = np.asarray(image, dtype=np.float64)
    for axis in range(out.ndim):
        moved = np.moveaxis(out, axis, 0)
        padded = np.pad(moved, [(radius, radius)] + [(0, 0)] * (moved.ndim - 1), mode=mode)
        total = np.zeros_like(moved)
        for index, weight in enumerate(weights):
            total += weight * padded[index : index + moved.shape[0]]
        out = np.moveaxis(total, 0, axis)
    return out


def _component_sizes(mask: np.ndarray) -> np.ndarray:
    """The sizes of the 4-connected regions of a 2D mask (``scipy.ndimage.label``'s default).

    Every cell takes the smallest index among its connected neighbours until nothing changes, so
    each region ends labelled by its first cell. The masks here are tile grids of at most a few
    thousand cells.
    """
    height, width = mask.shape
    empty = height * width
    labels = np.where(mask, np.arange(height * width).reshape(height, width), empty)
    while True:
        spread = labels.copy()
        down = mask[1:, :] & mask[:-1, :]
        spread[1:, :] = np.where(down, np.minimum(spread[1:, :], labels[:-1, :]), spread[1:, :])
        spread[:-1, :] = np.where(down, np.minimum(spread[:-1, :], labels[1:, :]), spread[:-1, :])
        across = mask[:, 1:] & mask[:, :-1]
        spread[:, 1:] = np.where(across, np.minimum(spread[:, 1:], labels[:, :-1]), spread[:, 1:])
        spread[:, :-1] = np.where(across, np.minimum(spread[:, :-1], labels[:, 1:]), spread[:, :-1])
        if np.array_equal(spread, labels):
            break
        labels = spread
    _regions, sizes = np.unique(labels[mask], return_counts=True)
    return sizes


def _neighbourhood(values: np.ndarray, reduce: Callable[..., np.ndarray]) -> np.ndarray:
    """``reduce`` over each cell's 3 x 3 neighbourhood, the border cells repeated outward."""
    height, width = values.shape
    padded = np.pad(values, 1, mode="edge")
    return reduce(
        np.stack([padded[dy : dy + height, dx : dx + width] for dy in range(3) for dx in range(3)]),
        axis=0,
    )


def _sobel(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Horizontal and vertical Sobel derivatives, the edge sample repeated outward."""
    p = np.pad(image, 1, mode="symmetric")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    return gx, gy


# -- members -------------------------------------------------------------------------------------


def _depth_grid(data: bytes) -> tuple[Any, np.ndarray, float]:
    """The point map as distances on its own model grid: NaN where the model placed nothing.

    A single-photograph point map is a grid in disguise (web/packages/atlas-react/src/playcanvas/
    depth-surface.ts records the measurement): every point unprojects from one model pixel through
    the header's own centred pinhole camera, so the cell a point came from is recovered exactly by
    projecting it back.
    """
    report = validate_opm(data)
    header_length = int.from_bytes(data[4:8], "little")
    header = json.loads(data[8 : 8 + header_length])
    viewpoint = header["viewpoint"]
    if (
        viewpoint["position"] != [0.0, 0.0, 0.0]
        or viewpoint["forward"] != [0.0, 0.0, -1.0]
        or viewpoint["up"] != [0.0, 1.0, 0.0]
    ):
        raise OpmIntegrityError("the point map is not one photograph's own camera frame")
    width, height = report.model_size
    section = next(item for item in header["sections"] if item["name"] == "position")
    points = (
        np.frombuffer(
            data, dtype="<f4", count=section["byteLength"] // 4, offset=section["byteOffset"]
        )
        .reshape(-1, 3)
        .astype(np.float64)
    )
    focal = (height / 2) / math.tan(math.radians(report.fov_y_degrees) / 2)
    ranges = np.full((height, width), np.nan)
    z = -points[:, 2]
    ahead = z > 0
    u = focal * points[ahead, 0] / z[ahead] + width / 2
    v = -focal * points[ahead, 1] / z[ahead] + height / 2
    columns = np.floor(u).astype(np.int64)
    rows = np.floor(v).astype(np.int64)
    inside = (columns >= 0) & (columns < width) & (rows >= 0) & (rows < height)
    ranges[rows[inside], columns[inside]] = np.linalg.norm(points[ahead][inside], axis=1)
    return report, ranges, focal


def _stated_focal(source: StandpointInput, policy: StandpointPolicy) -> float | None:
    """The focal length the photograph states, in its own pixels, or None when it states none.

    EXIF's 35 mm equivalent is defined over the full-frame diagonal, so it converts through the
    photograph's own diagonal whatever its aspect or orientation. A value outside the policy's
    plausible range is no statement at all.
    """
    width, height = source.image.size
    focal_mm = source.exif_focal_35mm
    low, high = policy.exif_focal_mm_range
    if focal_mm is None or not math.isfinite(focal_mm) or not low <= focal_mm <= high:
        return None
    return focal_mm / FULL_FRAME_DIAGONAL_MM * math.hypot(width, height)


def _bearings(xy: np.ndarray, size: tuple[int, int], focal: float) -> np.ndarray:
    width, height = size
    rays = np.stack(
        [(xy[:, 0] - width / 2) / focal, -(xy[:, 1] - height / 2) / focal, -np.ones(len(xy))],
        axis=1,
    )
    return rays / np.linalg.norm(rays, axis=1, keepdims=True)


class _FocalLengthUnstated(Exception):
    """The photograph states no focal length; raised before any feature is extracted from it."""


def _prepare(
    source: StandpointInput, policy: StandpointPolicy, extractor: FeatureExtractor
) -> _Member:
    """One member read for joining: its point map checked, its lens known, its features found.

    The point map is checked first, so a member with an unreadable estimate is named for that
    whatever else it lacks: that is a fault in the depth stage's output, the other is a fact about
    the photograph.
    """
    report, ranges, depth_focal_model = _depth_grid(source.point_map)
    width, height = source.image.size
    if report.source_size != (width, height):
        raise OpmIntegrityError("the point map was not made from these pixels")
    model_size = report.model_size
    focal = _stated_focal(source, policy)
    if focal is None:
        raise _FocalLengthUnstated(source.ordinal)
    scale = min(1.0, policy.feature_max_edge_px / max(width, height))
    feature_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    gray = source.image.convert("L")
    if feature_size != (width, height):
        gray = gray.resize(feature_size, Image.Resampling.LANCZOS)
    keypoints, descriptors = extractor.extract(np.asarray(gray, dtype=np.uint8))
    xy = keypoints * np.array([width / feature_size[0], height / feature_size[1]])
    columns = np.clip(
        np.floor(xy[:, 0] * model_size[0] / width).astype(np.int64), 0, model_size[0] - 1
    )
    rows = np.clip(
        np.floor(xy[:, 1] * model_size[1] / height).astype(np.int64), 0, model_size[1] - 1
    )
    at_keypoints = ranges[rows, columns]
    inverse = np.where(np.isfinite(at_keypoints) & (at_keypoints > 0), 1.0 / at_keypoints, 0.0)
    return _Member(
        source=source,
        point_map_sha256=report.sha256,
        source_size=(width, height),
        model_size=model_size,
        depth_focal_model=depth_focal_model,
        focal_source=focal,
        stated_focal=focal,
        intrinsics_source="exif-35mm-equivalent",
        ranges=ranges,
        gray=np.asarray(gray, dtype=np.float32),
        gray_focal=focal * feature_size[0] / width,
        xy=xy,
        descriptors=descriptors,
        bearings=_bearings(xy, (width, height), focal),
        inverse_range=np.nan_to_num(inverse),
    )


# -- one pair ------------------------------------------------------------------------------------


def _match(a: _Member, b: _Member, ratio: float) -> tuple[np.ndarray, np.ndarray]:
    """Mutual nearest neighbours that also pass Lowe's ratio test."""
    if len(a.descriptors) < 2 or len(b.descriptors) < 2:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    similarity = a.descriptors @ b.descriptors.T
    top_two = np.argpartition(-similarity, kth=1, axis=1)[:, :2]
    scores = np.take_along_axis(similarity, top_two, axis=1)
    order = np.argsort(-scores, axis=1, kind="stable")
    best = np.take_along_axis(top_two, order[:, :1], axis=1)[:, 0]
    best_score = np.take_along_axis(scores, order[:, :1], axis=1)[:, 0]
    second_score = np.take_along_axis(scores, order[:, 1:2], axis=1)[:, 0]
    best_distance = np.sqrt(np.maximum(0.0, 2.0 - 2.0 * best_score))
    second_distance = np.sqrt(np.maximum(0.0, 2.0 - 2.0 * second_score))
    passes = best_distance < ratio * second_distance
    mutual = np.argmax(similarity, axis=0)[best] == np.arange(len(best))
    keep = np.nonzero(passes & mutual)[0]
    return keep, best[keep]


def _ransac(
    target: np.ndarray, source: np.ndarray, policy: StandpointPolicy, seed: Sequence[int]
) -> np.ndarray | None:
    """The rotation that most matches agree with, from two-match samples."""
    count = len(target)
    if count < 2:
        return None
    rng = np.random.default_rng([policy.ransac_seed, *seed])
    first = rng.integers(0, count, size=policy.ransac_iterations)
    second = rng.integers(0, count, size=policy.ransac_iterations)
    usable = first != second
    first, second = first[usable], second[usable]
    cross_source = np.cross(source[first], source[second])
    cross_target = np.cross(target[first], target[second])
    # Both sides: a feature extractor may return one location twice with two orientations, so
    # two distinct matches can share a bearing in either photograph and define no rotation.
    length_source = np.linalg.norm(cross_source, axis=1)
    length_target = np.linalg.norm(cross_target, axis=1)
    floor = math.sin(math.radians(1.0))
    usable = (length_source > floor) & (length_target > floor)
    first, second = first[usable], second[usable]
    if len(first) == 0:
        return None
    cross_source = cross_source[usable] / length_source[usable, None]
    cross_target = cross_target[usable] / length_target[usable, None]
    hypotheses = _kabsch_batch(
        np.stack([target[first], target[second], cross_target], axis=1),
        np.stack([source[first], source[second], cross_source], axis=1),
    )
    threshold = math.cos(math.radians(policy.ransac_threshold_deg))
    best_count = -1
    best_rotation: np.ndarray | None = None
    for start in range(0, len(hypotheses), 256):
        batch = hypotheses[start : start + 256]
        predicted = np.einsum("kij,nj->kni", batch, source)
        agreeing = np.sum(np.einsum("kni,ni->kn", predicted, target) > threshold, axis=1)
        index = int(np.argmax(agreeing))
        if int(agreeing[index]) > best_count:
            best_count = int(agreeing[index])
            best_rotation = batch[index]
    return best_rotation


def _turn_only(
    target: np.ndarray, source: np.ndarray, start: np.ndarray, policy: StandpointPolicy
) -> np.ndarray:
    """The rotation alone that best lines up matched bearings, as they are drawn from one point.

    Iteratively reweighted Kabsch with the refinement's Huber weights. This, not the rotation of
    the rotation-and-translation fit, is what a pair records: the arrangement draws every
    photograph from one standpoint, so the turn that lines the photographs' content up there is
    the one to draw. The camera's own turn differs from it by whatever parallax a hand-held
    movement made, which a turn absorbs where the matched surfaces lie at similar distances, and
    where they do not, a rotation-and-translation fit can trade one for the other.
    """
    delta = math.radians(policy.inlier_threshold_deg)
    rotation = start
    for _ in range(policy.refine_iterations):
        norms = np.radians(_angles_deg(target, source @ rotation.T))
        rotation = _kabsch(target, source, _huber(norms, delta))
    return rotation


def _huber(norms: np.ndarray, delta: float) -> np.ndarray:
    return np.where(norms <= delta, 1.0, delta / np.maximum(norms, 1e-15))


def _refine(
    target: np.ndarray,
    source: np.ndarray,
    inverse_range: np.ndarray,
    rotation: np.ndarray,
    policy: StandpointPolicy,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rotation and translation that best explain the matches, with the translation's covariance.

    The model is ``target ~ normalise(R source + t / r)``, where ``r`` is the depth model's
    distance to the matched point in the source photograph (so ``t`` is in that photograph's depth
    units) and ``1 / r`` is zero where the model placed nothing, which is a point too far for any
    translation to move. Gauss-Newton with Huber weights; the Jacobian is numerical, which costs
    six residual evaluations a step over a few thousand matches and cannot disagree with the
    residual it differentiates.
    """
    delta = math.radians(policy.inlier_threshold_deg)

    def residuals(parameters: np.ndarray) -> np.ndarray:
        turned = source @ (_rotation_from_vector(parameters[:3]) @ rotation).T
        predicted = turned + parameters[3:][None, :] * inverse_range[:, None]
        predicted /= np.linalg.norm(predicted, axis=1, keepdims=True)
        return np.cross(target, predicted)

    parameters = np.zeros(6)
    observable = bool(np.any(inverse_range > 0))
    step = 1e-7
    normal = np.eye(6)
    residual = residuals(parameters)
    for _ in range(policy.refine_iterations):
        norms = np.linalg.norm(residual, axis=1)
        weights = np.repeat(_huber(norms, delta), 3)
        flat = residual.reshape(-1)
        jacobian = np.empty((len(flat), 6))
        for column in range(6):
            nudged = parameters.copy()
            nudged[column] += step
            jacobian[:, column] = (residuals(nudged).reshape(-1) - flat) / step
        normal = jacobian.T @ (jacobian * weights[:, None])
        damping = 1e-9 * max(float(np.max(np.diag(normal))), 1e-12)
        normal = normal + damping * np.eye(6)
        if not observable:
            # No matched point has a depth, so nothing constrains a translation: hold it at zero.
            normal[3:, :] = 0.0
            normal[:, 3:] = 0.0
            normal[3:, 3:] = np.eye(3)
        gradient = jacobian.T @ (flat * weights)
        if not observable:
            gradient[3:] = 0.0
        update = -np.linalg.solve(normal, gradient)
        parameters = parameters + update
        residual = residuals(parameters)
        if float(np.linalg.norm(update)) < 1e-12:
            break
    norms = np.linalg.norm(residual, axis=1)
    weights = _huber(norms, delta)
    dof = max(1, 2 * len(norms) - 6)
    variance = float(np.sum(weights * norms**2)) / dof
    covariance = variance * np.linalg.inv(normal)
    if not observable:
        covariance[3:, 3:] = np.inf
    refined = _rotation_from_vector(parameters[:3]) @ rotation
    return refined, parameters[3:], covariance[3:, 3:]


def _refine_zoom(
    target: np.ndarray,
    xy: np.ndarray,
    size: tuple[int, int],
    focal: float,
    inverse: np.ndarray,
    rotation: np.ndarray,
    policy: StandpointPolicy,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """:func:`_refine` with one more unknown: a relative zoom of ``b``'s lens, held by a prior.

    A lens stated a few percent off scales every direction about the frame's centre, and so does a
    step towards what is photographed, where the matched points lie at about one distance. Fitted
    without the zoom, the step takes the lens's error: MEASURED on the development sets with the
    stated lenses perturbed by up to 3 percent, translations of 0.14 to 0.69 m along the view
    appeared where the camera had moved 0.01 to 0.02 m, and one joinable pair was refused as moved.
    The zoom is ``exp(s)`` on ``b``'s focal length; ``s / zoom_prior_sigma`` is one more residual,
    scaled to the angular noise the focal refinement uses. Returns the rotation, the translation
    and its covariance, and ``s``.
    """
    delta = math.radians(policy.inlier_threshold_deg)
    noise = math.radians(policy.focal_refine_noise_deg)

    def angular(parameters: np.ndarray) -> np.ndarray:
        bearings = _bearings(xy, size, focal * math.exp(float(parameters[6])))
        turned = bearings @ (_rotation_from_vector(parameters[:3]) @ rotation).T
        predicted = turned + parameters[3:6][None, :] * inverse[:, None]
        predicted /= np.linalg.norm(predicted, axis=1, keepdims=True)
        return np.cross(target, predicted)

    def residuals(parameters: np.ndarray) -> np.ndarray:
        prior = parameters[6] / policy.zoom_prior_sigma * noise
        return np.concatenate([angular(parameters).reshape(-1), [prior]])

    parameters = np.zeros(7)
    observable = bool(np.any(inverse > 0))
    step = 1e-7
    normal = np.eye(7)
    residual = residuals(parameters)
    for _ in range(policy.refine_iterations):
        norms = np.linalg.norm(residual[:-1].reshape(-1, 3), axis=1)
        weights = np.concatenate([np.repeat(_huber(norms, delta), 3), [1.0]])
        jacobian = np.empty((len(residual), 7))
        for column in range(7):
            nudged = parameters.copy()
            nudged[column] += step
            jacobian[:, column] = (residuals(nudged) - residual) / step
        normal = jacobian.T @ (jacobian * weights[:, None])
        damping = 1e-9 * max(float(np.max(np.diag(normal))), 1e-12)
        normal = normal + damping * np.eye(7)
        gradient = jacobian.T @ (residual * weights)
        if not observable:
            # No matched point has a depth, so nothing constrains a translation: hold it at zero.
            normal[3:6, :] = 0.0
            normal[:, 3:6] = 0.0
            normal[3:6, 3:6] = np.eye(3)
            gradient[3:6] = 0.0
        update = -np.linalg.solve(normal, gradient)
        parameters = parameters + update
        residual = residuals(parameters)
        if float(np.linalg.norm(update)) < 1e-12:
            break
    norms = np.linalg.norm(residual[:-1].reshape(-1, 3), axis=1)
    weights = _huber(norms, delta)
    dof = max(1, 2 * len(norms) - 7)
    variance = float(np.sum(weights * norms**2)) / dof
    covariance = variance * np.linalg.inv(normal)
    if not observable:
        covariance[3:6, 3:6] = np.inf
    refined = _rotation_from_vector(parameters[:3]) @ rotation
    return refined, parameters[3:6], covariance[3:6, 3:6], float(parameters[6])


@dataclass(frozen=True, slots=True)
class _Motion:
    """A pair's fitted motion of ``b`` into ``a``: turn, translation (``b``'s depth units), zoom."""

    rotation: np.ndarray
    translation: np.ndarray
    covariance: np.ndarray
    zoom: float

    def source(self, b: _Member, ib: np.ndarray) -> np.ndarray:
        """``b``'s matched bearings through the zoom the fit found (none for version 1)."""
        if self.zoom == 0.0:
            return b.bearings[ib]
        return _bearings(b.xy[ib], b.source_size, b.focal_source * math.exp(self.zoom))

    def predict(self, b: _Member, ib: np.ndarray) -> np.ndarray:
        predicted = self.source(b, ib) @ self.rotation.T + (
            self.translation[None, :] * b.inverse_range[ib][:, None]
        )
        return predicted / np.linalg.norm(predicted, axis=1, keepdims=True)


def _fit_rotation_translation(
    a: _Member,
    b: _Member,
    ia: np.ndarray,
    ib: np.ndarray,
    rotation: np.ndarray,
    policy: StandpointPolicy,
) -> _Motion:
    refined, translation, covariance = _refine(
        a.bearings[ia], b.bearings[ib], b.inverse_range[ib], rotation, policy
    )
    return _Motion(refined, translation, covariance, 0.0)


def _zoom_refinement(
    a: _Member,
    b: _Member,
    ia: np.ndarray,
    ib: np.ndarray,
    rotation: np.ndarray,
    policy: StandpointPolicy,
) -> _Motion:
    refined, translation, covariance, zoom = _refine_zoom(
        a.bearings[ia],
        b.xy[ib],
        b.source_size,
        b.focal_source,
        b.inverse_range[ib],
        rotation,
        policy,
    )
    return _Motion(refined, translation, covariance, zoom)


#: What the final pass adds to a pair's rotation-and-translation fit, by the name the policy gives:
#: nothing, or a relative zoom. A name missing here is refused when the policy is decoded.
_PAIR_FITS: Final[Mapping[str, Callable[..., _Motion] | None]] = {
    "rotation-translation": None,
    "rotation-translation-zoom": _zoom_refinement,
}
_DISOCCLUSIONS: Final = frozenset({"none", "depth-edge-parallax"})


def _bound_parallax_deg(inverse: np.ndarray, movement: float) -> float:
    """How far a movement of ``movement`` would shift the nearer matched points against the farther.

    The difference between the 90th and 10th percentile of the points' inverse depths, times the
    movement, in degrees: the parallax a sideways step of that size makes between them, which is
    the signal a translation estimate rests on. MEASURED on the development sets for a step of the
    moved bound: under 0.2 degrees the estimates were off by up to 3.3 m (one facade 29 m away,
    where it is 0.03 degrees); from 0.3 degrees the median error was 0.02 m. Zero when too few
    points carry a depth to say.
    """
    placed = inverse[inverse > 0]
    if len(placed) < 6:
        return 0.0
    low, high = np.percentile(placed, [10, 90])
    return math.degrees(movement * float(high - low))


def _cells(xy: np.ndarray, size: tuple[int, int], grid: int) -> int:
    columns = np.clip((xy[:, 0] / size[0] * grid).astype(np.int64), 0, grid - 1)
    rows = np.clip((xy[:, 1] / size[1] * grid).astype(np.int64), 0, grid - 1)
    return len(set(zip(rows.tolist(), columns.tolist(), strict=True)))


def _model_bearings(member: _Member) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Every model cell's centre as a bearing under the join's intrinsics, with its row, column."""
    width, height = member.model_size
    rows, columns = np.nonzero(np.isfinite(member.ranges))
    xy = np.stack(
        [
            (columns + 0.5) * member.source_size[0] / width,
            (rows + 0.5) * member.source_size[1] / height,
        ],
        axis=1,
    )
    return _bearings(xy, member.source_size, member.focal_source), rows, columns


def _project(member: _Member, points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Model cells hit by camera-frame points under the join's intrinsics, and which landed."""
    depth = -points[:, 2]
    ahead = depth > 1e-9
    safe = np.where(ahead, depth, 1.0)
    x = member.focal_source * points[:, 0] / safe + member.source_size[0] / 2
    y = -member.focal_source * points[:, 1] / safe + member.source_size[1] / 2
    columns = np.floor(x * member.model_size[0] / member.source_size[0]).astype(np.int64)
    rows = np.floor(y * member.model_size[1] / member.source_size[1]).astype(np.int64)
    landed = (
        ahead
        & (columns >= 0)
        & (columns < member.model_size[0])
        & (rows >= 0)
        & (rows < member.model_size[1])
    )
    return rows, columns, landed


def _comparison_raster(member: _Member, angle: float) -> tuple[np.ndarray, float]:
    """The member's pixels resampled so one pixel spans ``angle`` radians at the centre."""
    height, width = member.gray.shape
    scale = (1.0 / member.gray_focal) / angle
    size = (max(8, round(width * scale)), max(8, round(height * scale)))
    image = Image.fromarray(member.gray).resize(size, Image.Resampling.BOX)
    return np.asarray(image, dtype=np.float64), member.gray_focal * size[0] / width


def _bilinear(image: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    height, width = image.shape
    x0 = np.clip(np.floor(x).astype(np.int64), 0, width - 2)
    y0 = np.clip(np.floor(y).astype(np.int64), 0, height - 2)
    fx, fy = x - x0, y - y0
    top = image[y0, x0] * (1 - fx) + image[y0, x0 + 1] * fx
    bottom = image[y0 + 1, x0] * (1 - fx) + image[y0 + 1, x0 + 1] * fx
    return top * (1 - fy) + bottom * fy


def _low_pass(image: np.ndarray, mask: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian smoothing where only ``mask`` pixels contribute and count."""
    weight = _gaussian_filter(mask.astype(np.float64), sigma, outside="zero")
    total = _gaussian_filter(np.where(mask, image, 0.0), sigma, outside="zero")
    return total / np.maximum(weight, 1e-9)


def _changed_fraction(
    to: _Member,
    from_: _Member,
    rotation: np.ndarray,
    translation: np.ndarray,
    ratio: float,
    policy: StandpointPolicy,
    *,
    tolerant: bool = False,
) -> float:
    """How much of the view ``to`` shares with ``from_`` shows something else in ``from_``.

    ``from_``'s photograph is carried into ``to``'s through the pair's measured rotation,
    translation and depth ratio (``X_to = ratio (R X_from + t)``, with ``to``'s own depth for where
    each of its pixels is, and a direction it placed no depth at taken at infinity), both at the
    coarser of the two photographs' angular resolutions, and compared tile by tile after one
    exposure fit for the pair. A tile disagrees when its best normalised correlation, over the
    shifts the pair's parallax and a depth error of the policy's size could explain, is under the
    policy's minimum; when one of the two is flat and the other is not; or when both are flat at
    different brightness. What counts is the share of compared tiles in connected regions of at
    least the policy's size: a change is a region, and the scattered tiles a fine pattern sampled
    twice disagrees on are not. A small low-pass first keeps that pattern from reading as a change.

    ``tolerant`` (stage version 2, only where the camera was measured to stand still) leaves out
    a tile whose shifts cannot cover what the movement does to it: the parallax its own nearest
    point allows, or, where the tile and its eight neighbours span a depth edge, the parallax
    between the edge's near and far sides. There the movement uncovers the far surface beside the
    near one, which one photograph shows and the other hides, and no shift lines that up.
    MEASURED on the development sets: such strips beside lamp posts and building edges were what
    refused four joinable courtyard pairs as changed.
    """
    angle = max(
        1.0 / to.gray_focal,
        1.0 / from_.gray_focal,
        (max(to.gray.shape) / to.gray_focal) / policy.change_long_edge_px,
    )
    here, focal_here = _comparison_raster(to, angle)
    there, focal_there = _comparison_raster(from_, angle)
    height, width = here.shape
    v, u = np.mgrid[0:height, 0:width]
    rays = np.stack(
        [
            (u + 0.5 - width / 2) / focal_here,
            -(v + 0.5 - height / 2) / focal_here,
            -np.ones(u.shape),
        ],
        axis=-1,
    )
    rays /= np.linalg.norm(rays, axis=-1, keepdims=True)
    model_height, model_width = to.ranges.shape
    rows = np.clip(((v + 0.5) / height * model_height).astype(np.int64), 0, model_height - 1)
    columns = np.clip(((u + 0.5) / width * model_width).astype(np.int64), 0, model_width - 1)
    ranges = to.ranges[rows, columns]
    placed = np.isfinite(ranges) & (ranges > 0)
    points = np.where(
        placed[..., None],
        rays * np.where(placed, ranges, 1.0)[..., None] / ratio - translation,
        rays,
    )
    back = points @ rotation
    depth = -back[..., 2]
    ahead = depth > 1e-9
    safe = np.where(ahead, depth, 1.0)
    there_height, there_width = there.shape
    x = focal_there * back[..., 0] / safe + there_width / 2 - 0.5
    y = -focal_there * back[..., 1] / safe + there_height / 2 - 0.5
    valid = ahead & (x >= 0) & (x <= there_width - 1.001) & (y >= 0) & (y <= there_height - 1.001)
    if np.count_nonzero(valid) < 64:
        return 0.0
    warped = _bilinear(there, np.where(valid, x, 0.0), np.where(valid, y, 0.0))
    here = _low_pass(here, np.ones(here.shape, dtype=bool), policy.change_blur_px)
    warped = _low_pass(warped, valid, policy.change_blur_px)
    design = np.stack([here[valid], np.ones(np.count_nonzero(valid))], axis=1)
    (gain, offset), *_ = np.linalg.lstsq(design, warped[valid], rcond=None)
    here = gain * here + offset
    tile = policy.change_tile_px
    tiles_high, tiles_wide = height // tile, width // tile
    if tiles_high == 0 or tiles_wide == 0:
        return 0.0

    def tiled(values: np.ndarray) -> np.ndarray:
        return values[: tiles_high * tile, : tiles_wide * tile].reshape(
            tiles_high, tile, tiles_wide, tile
        )

    # How far a tile may be searched: the parallax a depth error of the policy's size leaves at
    # the tile's nearest placed point, never less than the base nor more than the maximum.
    moved = float(np.linalg.norm(translation)) * ratio
    nearest = np.min(tiled(np.where(placed, ranges, np.inf)), axis=(1, 3))
    needed = policy.change_search_base_px + policy.change_depth_uncertainty * focal_here * moved / (
        np.maximum(nearest, 1e-9)
    )
    counted = tiled(valid).all(axis=(1, 3))
    reach = np.floor(
        np.clip(needed, policy.change_search_base_px, policy.change_search_max_px)
    ).astype(np.int64)
    here_tiles = tiled(here)
    widest = policy.change_search_max_px
    padded = np.pad(np.where(valid, warped, np.nan), widest, constant_values=np.nan)
    best = np.full((tiles_high, tiles_wide), -np.inf)
    if tolerant and policy.change_disocclusion == "depth-edge-parallax":
        # A tile is compared on the pixels no depth edge's band marks, and only when they are at
        # least the policy's share of it.
        weight = tiled((~_disocclusion(placed, ranges, focal_here * moved, policy)).astype(float))
        kept = weight.sum(axis=(1, 3))
        counted &= kept >= policy.change_disocclusion_min_share * tile * tile
        kept = np.maximum(kept, 1.0)

        def statistics(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            mean = (values * weight).sum(axis=(1, 3)) / kept
            spread = (weight * (values - mean[:, None, :, None]) ** 2).sum(axis=(1, 3)) / kept
            return mean, np.sqrt(np.maximum(spread, 0.0))

        here_mean, here_sigma = statistics(here_tiles)
        there_mean = there_sigma = np.zeros((tiles_high, tiles_wide))
        for dy in range(-widest, widest + 1):
            for dx in range(-widest, widest + 1):
                shifted = tiled(
                    padded[widest + dy : widest + dy + height, widest + dx : widest + dx + width]
                )
                finite = np.isfinite(shifted)
                usable = (finite | (weight == 0)).all(axis=(1, 3)) & (
                    reach >= max(abs(dx), abs(dy))
                )
                filled = np.where(finite, shifted, 0.0)
                mean, sigma = statistics(filled)
                if dx == 0 and dy == 0:
                    there_mean, there_sigma = mean, sigma
                covariance = (
                    weight
                    * (here_tiles - here_mean[:, None, :, None])
                    * (filled - mean[:, None, :, None])
                ).sum(axis=(1, 3)) / kept
                correlation = covariance / np.maximum(here_sigma * sigma, 1e-9)
                best = np.where(usable, np.maximum(best, correlation), best)
    else:
        here_mean = here_tiles.mean(axis=(1, 3))
        here_sigma = here_tiles.std(axis=(1, 3))
        there_mean = there_sigma = np.zeros((tiles_high, tiles_wide))
        for dy in range(-widest, widest + 1):
            for dx in range(-widest, widest + 1):
                shifted = tiled(
                    padded[widest + dy : widest + dy + height, widest + dx : widest + dx + width]
                )
                usable = np.isfinite(shifted).all(axis=(1, 3)) & (reach >= max(abs(dx), abs(dy)))
                filled = np.where(np.isfinite(shifted), shifted, 0.0)
                mean = filled.mean(axis=(1, 3))
                sigma = filled.std(axis=(1, 3))
                if dx == 0 and dy == 0:
                    there_mean, there_sigma = mean, sigma
                covariance = (
                    (here_tiles - here_mean[:, None, :, None]) * (filled - mean[:, None, :, None])
                ).mean(axis=(1, 3))
                correlation = covariance / np.maximum(here_sigma * sigma, 1e-9)
                best = np.where(usable, np.maximum(best, correlation), best)
    flat = policy.change_flat_sigma
    flat_here, flat_there = here_sigma < flat, there_sigma < flat
    one_flat = (flat_here & (there_sigma > 2 * flat)) | (flat_there & (here_sigma > 2 * flat))
    disagree = np.where(
        flat_here & flat_there,
        np.abs(here_mean - there_mean) > policy.change_flat_delta,
        one_flat | (best < policy.change_zncc_min),
    )
    disagree &= counted
    total = int(np.count_nonzero(counted))
    if total == 0:
        return 0.0
    sizes = _component_sizes(disagree)
    clustered = int(np.sum(sizes[sizes >= policy.change_min_cluster_tiles]))
    return clustered / total


def _disocclusion(
    placed: np.ndarray,
    ranges: np.ndarray,
    pixels_per_inverse_metre: float,
    policy: StandpointPolicy,
) -> np.ndarray:
    """The pixels a movement may uncover beside a depth edge, which one photograph shows and the
    other hides.

    A depth edge is two neighbouring pixels whose inverse depths differ by more than
    ``change_edge_jump`` of the nearer one's, or a placed pixel beside one the depth model left
    unplaced (taken at infinity). A movement shifts the near side against the far side by
    ``pixels_per_inverse_metre`` (the comparison's focal length times the movement) times their
    inverse-depth difference, and the band that uncovers is as wide as that shift, beside the edge.
    Every pixel within that distance of an edge is marked, the band capped at
    ``change_disocclusion_max_px``; a shift within the comparison's base search marks nothing. A
    surface's own slope is not an edge: the ground running up to an object on it changes smoothly,
    and what stands on it is still compared. MEASURED on the development sets: the rule it replaced,
    every tile whose 3 x 3 neighbourhood of tiles spanned a large enough inverse-depth range, took
    the ground under a moved fountain for an edge and left 1.85 percent of a changed pair
    disagreeing where the comparison without it saw 3.78.
    """
    inverse = np.where(placed, 1.0 / np.where(placed, ranges, 1.0), 0.0)
    band = np.zeros(inverse.shape)
    for axis in (0, 1):
        first = np.take(inverse, np.arange(inverse.shape[axis] - 1), axis=axis)
        second = np.take(inverse, np.arange(1, inverse.shape[axis]), axis=axis)
        nearer = np.maximum(first, second)
        step = np.abs(first - second)
        edge = (nearer > 0) & (step > policy.change_edge_jump * nearer)
        shift = np.where(edge, pixels_per_inverse_metre * step, 0.0)
        if axis == 0:
            band[:-1, :] = np.maximum(band[:-1, :], shift)
            band[1:, :] = np.maximum(band[1:, :], shift)
        else:
            band[:, :-1] = np.maximum(band[:, :-1], shift)
            band[:, 1:] = np.maximum(band[:, 1:], shift)
    # A shift the comparison's base search covers uncovers nothing it cannot line up. Each other
    # edge pixel reaches as far as its own shift: a reach that falls by one pixel a step.
    band = np.where(
        band > policy.change_search_base_px, band + policy.change_disocclusion_margin_px, 0.0
    )
    reach = np.minimum(np.ceil(band), policy.change_disocclusion_max_px)
    for _ in range(policy.change_disocclusion_max_px):
        spread = _neighbourhood(reach, np.max) - 1.0
        grown = np.maximum(reach, spread)
        if np.array_equal(grown, reach):
            break
        reach = grown
    return reach > 0


def _pair_changed(
    a: _Member,
    b: _Member,
    rotation: np.ndarray,
    translation: np.ndarray,
    ratio: float,
    policy: StandpointPolicy,
    *,
    tolerant: bool,
) -> float:
    """The changed share of a pair under one motion: each photograph carried into the other, the
    larger of the two, since what one of them added shows only from its own side."""
    changed_ab = _changed_fraction(a, b, rotation, translation, ratio, policy, tolerant=tolerant)
    changed_ba = _changed_fraction(
        b,
        a,
        rotation.T,
        -(rotation.T @ translation) * ratio,
        1.0 / ratio,
        policy,
        tolerant=tolerant,
    )
    return max(changed_ab, changed_ba)


def _join_pair(
    a: _Member, b: _Member, policy: StandpointPolicy, *, provisional: bool = False
) -> _PairResult:
    """One pair's outcome, or with ``provisional`` only whether and where the two overlap.

    The provisional pass stops once the overlap is established and the turn fitted, with no
    record: its matches are what the focal refinement reads (:func:`_refine_focals`), and every
    test that depends on the lens runs again on the refined one.
    """
    ia, ib = _match(a, b, policy.match_ratio)
    matches = len(ia)

    def refused(outcome: str, **fields: Any) -> _PairResult:
        record = StandpointPair(
            a=a.source.ordinal,
            b=b.source.ordinal,
            outcome=outcome,  # type: ignore[arg-type]
            matches=matches,
            inliers=int(fields.get("inliers", 0)),
            inlier_cells=int(fields.get("cells", 0)),
            rotation_ppb=fields.get("rotation_ppb"),
            residual_millidegrees=fields.get("residual"),
            standpoint_residual_millidegrees=fields.get("standpoint_residual"),
            translation_mm=fields.get("translation_mm"),
            translation_sigma_mm=fields.get("translation_sigma_mm"),
            depth_ratio_ppm=fields.get("depth_ratio_ppm"),
            changed_ppm=fields.get("changed_ppm"),
        )
        return _PairResult(record, None, None, 0.0)

    target, source = a.bearings[ia], b.bearings[ib]
    rotation = _ransac(target, source, policy, (a.source.ordinal, b.source.ordinal))
    if rotation is None:
        return refused("insufficient_overlap")
    window = _angles_deg(target, source @ rotation.T) <= policy.candidate_window_deg
    inverse = b.inverse_range[ib]
    motion = _Motion(rotation, np.zeros(3), np.full((3, 3), np.inf), 0.0)
    inliers = window
    for _ in range(2):
        if np.count_nonzero(inliers) < max(3, policy.min_inliers // 2):
            break
        motion = _fit_rotation_translation(a, b, ia[inliers], ib[inliers], motion.rotation, policy)
        predicted = motion.predict(b, ib)
        inliers = window & (_angles_deg(target, predicted) <= policy.inlier_threshold_deg)
    # What the final pass adds to that fit, on its inliers and from its rotation. The provisional
    # pass's motions start the focal refinement and keep version 1's fit: MEASURED on the
    # development sets, starting that refinement from motions fitted with a zoom left one room's
    # lens 3.4 percent off where version 1's start left it 0.1 percent off. And fitted from the
    # RANSAC turn with its inliers chosen again, the zoom found a 17 percent zoom and a 0.7 m step
    # in a landscape pair whose camera stood still, on 74 of the 125 matches the plain fit keeps.
    refinement = _PAIR_FITS[policy.pair_fit]
    if (
        refinement is not None
        and not provisional
        and np.count_nonzero(inliers) >= max(3, policy.min_inliers // 2)
    ):
        motion = refinement(a, b, ia[inliers], ib[inliers], motion.rotation, policy)
    rotation, translation, covariance = motion.rotation, motion.translation, motion.covariance
    count = int(np.count_nonzero(inliers))
    cells = min(
        _cells(a.xy[ia[inliers]], a.source_size, policy.coverage_grid),
        _cells(b.xy[ib[inliers]], b.source_size, policy.coverage_grid),
    )
    if count < policy.min_inliers or cells < policy.min_inlier_cells:
        return refused("insufficient_overlap", inliers=count, cells=cells)
    predicted = motion.predict(b, ib[inliers])
    residual = _stats_millidegrees(_angles_deg(target[inliers], predicted))
    turn = _turn_only(target[inliers], source[inliers], rotation, policy)
    turn_angles = _angles_deg(target[inliers], source[inliers] @ turn.T)
    if provisional:
        return _PairResult(
            None, turn, None, float(count), (ia[inliers], ib[inliers]), (rotation, translation)
        )
    standpoint = _stats_millidegrees(turn_angles)
    # The depth ratio: a's distance to a matched point over b's, carried into a by the model.
    ranges_a = 1.0 / np.where(
        a.inverse_range[ia[inliers]] > 0, a.inverse_range[ia[inliers]], np.nan
    )
    ranges_b = 1.0 / np.where(inverse[inliers] > 0, inverse[inliers], np.nan)
    carried = np.linalg.norm(
        (motion.source(b, ib[inliers]) * ranges_b[:, None]) @ rotation.T + translation[None, :],
        axis=1,
    )
    ratios = ranges_a / carried
    ratios = ratios[np.isfinite(ratios) & (ratios > 0)]
    if len(ratios) < max(3, policy.min_inliers // 4):
        return refused("insufficient_overlap", inliers=count, cells=cells)
    ratio = float(np.exp(np.median(np.log(ratios))))
    translation_a = ratio * translation
    distance = float(np.linalg.norm(translation_a))
    if np.all(np.isfinite(covariance)) and distance > 0:
        direction = translation / np.linalg.norm(translation)
        sigma = ratio * math.sqrt(max(0.0, float(direction @ covariance @ direction)))
    else:
        sigma = math.inf
    fields: dict[str, Any] = {
        "inliers": count,
        "cells": cells,
        "rotation_ppb": _ppb(turn),
        "residual": residual,
        "standpoint_residual": standpoint,
        "translation_mm": tuple(round(float(value) * _MILLI) for value in translation_a),
        "translation_sigma_mm": None if not math.isfinite(sigma) else round(sigma * _MILLI),
        "depth_ratio_ppm": round(ratio * PARTS_PER_MILLION),
    }

    # Whether a movement shows at all: only as parallax between points at different depths
    # (version 1 asks no such question, and every translation counts). A movement is claimed only
    # where the one estimated would show; the camera is claimed to have stood still only where a
    # movement of the moved bound would have shown.
    def shows(movement: float) -> bool:
        return policy.min_translation_parallax_deg is None or (
            _bound_parallax_deg(inverse[inliers], movement) >= policy.min_translation_parallax_deg
        )

    if (
        shows(distance)
        and math.isfinite(sigma)
        and distance - policy.translation_sigmas * sigma > policy.max_translation_m
    ):
        return refused("moved_between_photographs", **fields)
    if policy.still_max_translation_m is None:
        # Version 1: the camera is taken to have stood still wherever it was not measured to move.
        still = True
        changed = _pair_changed(a, b, rotation, translation, ratio, policy, tolerant=False)
    else:
        still = (
            shows(policy.max_translation_m)
            and math.isfinite(sigma)
            and distance + policy.translation_sigmas * sigma <= policy.still_max_translation_m
        )
        # Where the camera stood still, the measured movement and a pure turn are both admissible
        # and the one that explains more of what the photographs share decides; elsewhere only a
        # pure turn is, because a movement nobody measured must not be used to explain anything.
        # There the turn must also explain the matched features themselves, within the inlier
        # threshold at the 90th percentile: MEASURED on the development sets, the one pair such a
        # turn left 2.4 degrees apart there joined 0.81 degrees misregistered, and no pair joined
        # under a measured movement left more than 1.0.
        if (
            not still
            and turn_angles.size
            and (float(np.percentile(turn_angles, 90)) > policy.inlier_threshold_deg)
        ):
            return refused("insufficient_overlap", **fields)
        changed = _pair_changed(a, b, turn, np.zeros(3), ratio, policy, tolerant=False)
        if still:
            changed = min(
                changed, _pair_changed(a, b, rotation, translation, ratio, policy, tolerant=True)
            )
    fields["changed_ppm"] = round(changed * PARTS_PER_MILLION)
    if changed > policy.max_changed_fraction:
        return refused("scene_changed" if still else "insufficient_overlap", **fields)
    record = StandpointPair(
        a=a.source.ordinal,
        b=b.source.ordinal,
        outcome="joined",
        matches=matches,
        inliers=count,
        inlier_cells=cells,
        rotation_ppb=fields["rotation_ppb"],
        residual_millidegrees=residual,
        standpoint_residual_millidegrees=standpoint,
        translation_mm=fields["translation_mm"],
        translation_sigma_mm=fields["translation_sigma_mm"],
        depth_ratio_ppm=fields["depth_ratio_ppm"],
        changed_ppm=fields["changed_ppm"],
    )
    return _PairResult(record, turn, ratio, float(count))


# -- the lenses ----------------------------------------------------------------------------------


def _with_focal(member: _Member, focal: float) -> _Member:
    """The member read through a lens of ``focal`` pixels instead of the one it had."""
    return dataclasses.replace(
        member,
        focal_source=focal,
        gray_focal=member.gray_focal * focal / member.focal_source,
        bearings=_bearings(member.xy, member.source_size, focal),
    )


def _refine_focals(
    members: Mapping[int, _Member],
    provisional: Mapping[tuple[int, int], _PairResult],
    policy: StandpointPolicy,
) -> dict[int, float]:
    """Each member's focal length, refined from the photographs it overlaps.

    A photograph states its lens as a whole number of 35 mm equivalent millimetres, and a turn
    measured through a lens a few percent off is off by as much at the frame's edges; measured on
    the evaluation's development sets, 3 percent was enough to part joined photographs by a degree.
    Photographs taken from one point constrain their lenses as well as their turns: a direction
    two photographs share must come out the same through both. So every overlapping group is
    solved at once for its members' turns and a scale on each stated focal length (see
    :func:`_refine_group`). Only a pair that says something about lenses takes part: one with the
    policy's number of matched features, whose provisional movement is under the policy's bound.
    Fewer matches let a lens and a movement trade places, and photographs taken from places apart
    measured the depth model's error more than any lens. A member in no such pair keeps its stated
    focal length.
    """
    usable = {
        key: result
        for key, result in provisional.items()
        if result.motion is not None
        and result.inliers is not None
        and len(result.inliers[0]) >= policy.focal_refine_min_inliers
        # In the depth model's metres, as the moved test reads it.
        and float(np.linalg.norm(result.motion[1])) <= policy.focal_refine_max_translation_m
    }
    refined = {ordinal: member.focal_source for ordinal, member in members.items()}
    for component in _components(sorted(members), sorted(usable)):
        if len(component) >= 2:
            edges = {key: usable[key] for key in sorted(usable) if key[0] in component}
            refined.update(_refine_group(component, edges, members, policy))
    return refined


def _refine_group(
    component: list[int],
    edges: Mapping[tuple[int, int], _PairResult],
    members: Mapping[int, _Member],
    policy: StandpointPolicy,
) -> dict[int, float]:
    """Turns, movements and focal scales of one overlapping group, by Gauss-Newton.

    The unknowns are a small turn of every member but the lowest ordinal, which fixes the frame;
    ``s`` per member, its focal length being ``stated * exp(s)``; and a translation per pair, in
    the scene's axes and the second member's depth units, as :func:`_refine` has one. The
    translation is what keeps a hand-held movement out of the lenses: its parallax scales with a
    matched point's inverse depth, which a lens's radial scale does not, and where the depths are
    too alike to tell the two apart the prior keeps the lens the photograph states. The residuals
    are the cross products of matched features' directions (their sines, as vectors), Huber
    weighted, and ``s / sigma`` per member scaled to the same angular noise. The Jacobian is
    numerical, as in :func:`_refine`.
    """
    absolute, _residuals = _solve_rotations(
        component,
        {key: (result.motion[0], result.weight) for key, result in edges.items()},  # type: ignore[index]
    )
    data = []
    moves = []
    for (a, b), result in edges.items():
        ia, ib = result.inliers  # type: ignore[misc]
        keep = np.unique(
            np.linspace(0, len(ia) - 1, min(len(ia), policy.focal_refine_matches))
            .round()
            .astype(np.int64)
        )
        data.append(
            (
                a,
                b,
                members[a].xy[ia[keep]],
                members[b].xy[ib[keep]],
                members[b].inverse_range[ib[keep]],
            )
        )
        moves.append(absolute[a] @ result.motion[1])  # type: ignore[index]
    root = component[0]
    slot = {node: position for position, node in enumerate(n for n in component if n != root)}
    scale_at = {node: 3 * len(slot) + position for position, node in enumerate(component)}
    move_at = 3 * len(slot) + len(component)
    noise = math.radians(policy.focal_refine_noise_deg)
    delta = math.radians(policy.inlier_threshold_deg)

    def residuals(parameters: np.ndarray, weights: np.ndarray | None) -> np.ndarray:
        rotations = {
            node: absolute[node]
            if node == root
            else _rotation_from_vector(parameters[3 * slot[node] : 3 * slot[node] + 3])
            @ absolute[node]
            for node in component
        }

        def directions(node: int, xy: np.ndarray) -> np.ndarray:
            focal = members[node].focal_source * math.exp(parameters[scale_at[node]])
            return _bearings(xy, members[node].source_size, focal) @ rotations[node].T

        parts = []
        for edge, (a, b, xy_a, xy_b, inverse) in enumerate(data):
            moved = directions(b, xy_b) + (
                parameters[move_at + 3 * edge : move_at + 3 * edge + 3][None, :] * inverse[:, None]
            )
            moved /= np.linalg.norm(moved, axis=1, keepdims=True)
            parts.append(np.cross(directions(a, xy_a), moved))
        angular = np.concatenate(parts)
        if weights is not None:
            angular = angular * np.sqrt(weights)[:, None]
        prior = np.array(
            [parameters[scale_at[node]] / policy.focal_prior_sigma * noise for node in component]
        )
        return np.concatenate([angular.reshape(-1), prior])

    parameters = np.concatenate([np.zeros(3 * len(slot) + len(component)), *moves])
    for _ in range(policy.focal_refine_iterations):
        unweighted = residuals(parameters, None)
        weights = _huber(
            np.linalg.norm(unweighted[: -len(component)].reshape(-1, 3), axis=1), delta
        )
        base = residuals(parameters, weights)
        jacobian = np.empty((len(base), len(parameters)))
        for column in range(len(parameters)):
            step = np.zeros_like(parameters)
            step[column] = 1e-7
            jacobian[:, column] = (residuals(parameters + step, weights) - base) / 1e-7
        update, *_ = np.linalg.lstsq(jacobian, -base, rcond=None)
        parameters = parameters + update
        if float(np.max(np.abs(update))) < 1e-9:
            break
    return {
        node: members[node].focal_source * math.exp(float(parameters[scale_at[node]]))
        for node in component
    }


# -- the set -------------------------------------------------------------------------------------


def _components(nodes: Sequence[int], edges: Sequence[tuple[int, int]]) -> list[list[int]]:
    parent = {node: node for node in nodes}

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    groups: dict[int, list[int]] = {}
    for node in nodes:
        groups.setdefault(find(node), []).append(node)
    return sorted((sorted(group) for group in groups.values()), key=lambda g: (-len(g), g[0]))


def _solve_rotations(
    nodes: list[int], edges: dict[tuple[int, int], tuple[np.ndarray, float]]
) -> tuple[dict[int, np.ndarray], dict[tuple[int, int], float]]:
    """Absolute rotations (scene from camera) agreeing best with every pairwise rotation.

    A pair's rotation maps ``b``'s directions into ``a``'s, so ``A_b = A_a R_ab``. Start from a
    maximum-weight spanning tree rooted at the lowest ordinal, then minimise the weighted squared
    angles ``|log(A_a R_ab A_b^T)|^2`` by Gauss-Newton on small rotations of every node but the
    root.
    """
    root = nodes[0]
    absolute = {root: np.eye(3)}
    remaining = sorted(edges.items(), key=lambda item: (-item[1][1], item[0]))
    while len(absolute) < len(nodes):
        for (a, b), (rotation, _weight) in remaining:
            if a in absolute and b not in absolute:
                absolute[b] = absolute[a] @ rotation
                break
            if b in absolute and a not in absolute:
                absolute[a] = absolute[b] @ rotation.T
                break
        else:  # pragma: no cover - callers pass one connected component
            raise ValueError("the rotation solve was given nodes no edge connects")
    index = {node: position for position, node in enumerate(nodes) if node != root}
    for _ in range(20):
        rows: list[np.ndarray] = []
        values: list[np.ndarray] = []
        for (a, b), (rotation, weight) in edges.items():
            error = _vector_from_rotation(absolute[a] @ rotation @ absolute[b].T)
            row = np.zeros((3, 3 * (len(nodes) - 1)))
            if a in index:
                row[:, 3 * (index[a] - 1) : 3 * index[a]] = np.eye(3)
            if b in index:
                row[:, 3 * (index[b] - 1) : 3 * index[b]] -= np.eye(3)
            scale = math.sqrt(weight)
            rows.append(row * scale)
            values.append(-error * scale)
        matrix = np.vstack(rows)
        update, *_ = np.linalg.lstsq(matrix, np.concatenate(values), rcond=None)
        for node, position in index.items():
            absolute[node] = (
                _rotation_from_vector(update[3 * (position - 1) : 3 * position]) @ absolute[node]
            )
        if float(np.max(np.abs(update))) < 1e-12:
            break
    residuals = {
        pair: math.degrees(
            float(
                np.linalg.norm(
                    _vector_from_rotation(absolute[pair[0]] @ rotation @ absolute[pair[1]].T)
                )
            )
        )
        for pair, (rotation, _weight) in edges.items()
    }
    return absolute, residuals


def _solve_scales(
    nodes: list[int], ratios: dict[tuple[int, int], tuple[float, float]]
) -> tuple[dict[int, float], dict[tuple[int, int], float]]:
    """Per-member depth scales making every joined overlap agree, geometric mean one.

    A pair's ratio is ``a``'s distance over ``b``'s for the same point, so the scales that bring
    them together satisfy ``log s_a - log s_b = -log ratio``. The gauge keeps the product of the
    scales at one: the scene keeps the depth model's own scale on average, and no member's
    estimate is privileged over another's.
    """
    index = {node: position for position, node in enumerate(nodes)}
    rows = []
    values = []
    for (a, b), (ratio, weight) in ratios.items():
        row = np.zeros(len(nodes))
        row[index[a]] = 1.0
        row[index[b]] = -1.0
        scale = math.sqrt(weight)
        rows.append(row * scale)
        values.append(-math.log(ratio) * scale)
    gauge_weight = math.sqrt(sum(weight for _ratio, weight in ratios.values()))
    rows.append(np.ones(len(nodes)) * gauge_weight)
    values.append(0.0)
    logs, *_ = np.linalg.lstsq(np.vstack(rows), np.array(values), rcond=None)
    scales = {node: float(math.exp(logs[position])) for node, position in index.items()}
    residuals = {
        (a, b): math.log(scales[a]) - math.log(scales[b]) + math.log(ratio)
        for (a, b), (ratio, _weight) in ratios.items()
    }
    return scales, residuals


def _up_camera_axes(
    absolute: Mapping[int, np.ndarray], policy: StandpointPolicy
) -> tuple[np.ndarray, str]:
    """Up from the cameras' own axes, and the name of the way it was found.

    People hold a camera level far more reliably than they hold its pitch, so the camera's own
    horizontal axis is taken to lie in the horizontal plane, and up is the direction closest to
    perpendicular to all of them. Photographs turned only up and down share one horizontal axis,
    which leaves up undetermined in a plane; then the average camera up, projected onto that
    plane, is used. MEASURED on the development sets, whose photographs roll by 1.2 degrees at
    one standard deviation: this leans by 1.3 degrees at the median and 3.9 at worst on the true
    turns, and by nothing once the roll is removed, so the roll is its whole error.
    """
    nodes = sorted(absolute)
    horizontal = np.array([absolute[node][:, 0] for node in nodes])
    camera_up = np.array([absolute[node][:, 1] for node in nodes])
    values, vectors = np.linalg.eigh(horizontal.T @ horizontal)
    if values[1] >= policy.up_min_spread * float(np.sum(values)):
        up = vectors[:, 0]
        method = "camera-horizontal-axes"
    else:
        axis = np.mean(horizontal, axis=0)
        axis /= np.linalg.norm(axis)
        mean_up = np.mean(camera_up, axis=0)
        up = mean_up - (mean_up @ axis) * axis
        up /= np.linalg.norm(up)
        method = "mean-camera-up-about-a-shared-horizontal-axis"
    if float(up @ np.sum(camera_up, axis=0)) < 0:
        up = -up
    return up, method


def _edge_normals(member: _Member, edges: UpFromEdges) -> tuple[np.ndarray, np.ndarray]:
    """The planes through the camera and each of the photograph's strongest edge pixels.

    Each is given by its unit normal in the camera frame, weighted by the edge's gradient. A
    vertical line in the scene lies in the plane of every one of its edge pixels, so up is
    perpendicular to all their normals; an edge that is not vertical has a normal pointing
    anywhere. The pixels are the ``edge_fraction`` with the strongest gradient after a small blur,
    at most ``max_pixels`` of them, taken evenly in raster order.
    """
    gray = member.gray
    focal = member.gray_focal
    height, width = gray.shape
    scale = min(1.0, edges.long_edge_px / max(height, width))
    if scale < 1.0:
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        gray = np.asarray(
            Image.fromarray(gray).resize(size, Image.Resampling.BOX), dtype=np.float32
        )
        focal = focal * size[0] / width
        height, width = gray.shape
    smooth = _gaussian_filter(gray, edges.blur_px, outside="mirror")
    gx, gy = _sobel(smooth)
    magnitude = np.hypot(gx, gy)
    threshold = max(float(np.quantile(magnitude, 1.0 - edges.edge_fraction)), 1e-9)
    rows, columns = np.nonzero(magnitude > threshold)
    if len(rows) > edges.max_pixels:
        pick = (np.arange(edges.max_pixels) * (len(rows) / edges.max_pixels)).astype(np.int64)
        rows, columns = rows[pick], columns[pick]
    strength = magnitude[rows, columns]
    # The edge runs across the gradient; image v grows downward and camera y upward.
    along_u = -gy[rows, columns] / strength
    along_v = gx[rows, columns] / strength
    rays = np.stack(
        [
            (columns + 0.5 - width / 2) / focal,
            -(rows + 0.5 - height / 2) / focal,
            -np.ones(len(rows)),
        ],
        axis=1,
    )
    along = np.stack([along_u / focal, -along_v / focal, np.zeros(len(rows))], axis=1)
    normals = np.cross(rays, along)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-15)
    return normals, strength


def _up_vertical_edges(
    members: Mapping[int, _Member],
    absolute: Mapping[int, np.ndarray],
    start: np.ndarray,
    edges: UpFromEdges,
) -> tuple[np.ndarray, float, int]:
    """Up as the mode of the edges' perpendicular, sought from ``start``; its evidence; its support.

    Every photograph's edge-plane normals are turned into the arrangement. From ``start``, up is
    repeatedly replaced by the direction least aligned with the normals within ``search_deg`` of
    perpendicular, each weighted by its gradient and by a Gaussian of ``kernel_deg`` in its angle
    from perpendicular: a mode, which a photograph of rocks with no vertical structure shifts
    little, where a least-squares fit follows it. MEASURED on the development sets with the true
    turns: 0.51 degrees at the 95th percentile and 0.71 at worst, where least squares in a
    shrinking window left one set 5.7 degrees off. The evidence is how many times denser the
    edges are within ``kernel_deg`` of perpendicular than in the ``background_deg`` band.
    """
    found_normals, found_weights = [], []
    for node in sorted(absolute):
        node_normals, node_weights = _edge_normals(members[node], edges)
        found_normals.append(node_normals @ absolute[node].T)
        found_weights.append(node_weights)
    normals = np.concatenate(found_normals)
    weights = np.concatenate(found_weights)
    up = start / np.linalg.norm(start)
    reach = math.sin(math.radians(edges.search_deg))
    for _ in range(edges.iterations):
        sines = normals @ up
        near = np.abs(sines) < reach
        if not np.any(near):
            break
        angles = np.degrees(np.arcsin(np.clip(sines[near], -1.0, 1.0)))
        kernel = weights[near] * np.exp(-0.5 * (angles / edges.kernel_deg) ** 2)
        scatter = (normals[near] * kernel[:, None]).T @ normals[near]
        _values, vectors = np.linalg.eigh(scatter)
        found = vectors[:, 0] if float(vectors[:, 0] @ up) >= 0 else -vectors[:, 0]
        moved = float(np.degrees(np.arccos(np.clip(found @ up, -1.0, 1.0))))
        up = found
        if moved < 1e-4:
            break
    angles = np.degrees(np.arcsin(np.clip(normals @ up, -1.0, 1.0)))
    low, high = edges.background_deg
    peak = float(np.sum(weights[np.abs(angles) < edges.kernel_deg])) / (2 * edges.kernel_deg)
    band = (np.abs(angles) >= low) & (np.abs(angles) < high)
    background = float(np.sum(weights[band])) / (2 * (high - low))
    evidence = peak / max(background, peak * 1e-6, 1e-12)
    return up, evidence, int(np.count_nonzero(np.abs(angles) < edges.kernel_deg))


#: The ways up is estimated, by the name the policy gives. A name missing here is refused when
#: the policy is decoded, never guessed.
_UP_METHODS: Final = frozenset({"camera-horizontal-axes", "vertical-edges"})


def _estimate_up(
    members: Mapping[int, _Member], absolute: Mapping[int, np.ndarray], policy: StandpointPolicy
) -> tuple[np.ndarray, dict[str, Any]]:
    """The arrangement's up and what the record says about how it was found."""
    axes_up, axes_method = _up_camera_axes(absolute, policy)
    if policy.up_method == "camera-horizontal-axes":
        return axes_up, {
            "method": axes_method,
            "assumption": "each photograph was held without roll",
        }
    if policy.up_method == "vertical-edges" and policy.up_edges is not None:
        edges_up, evidence, support = _up_vertical_edges(
            members, absolute, axes_up, policy.up_edges
        )
        facts = {"vertical_edges_evidence_milli": round(evidence * _MILLI)}
        if evidence >= policy.up_edges.min_evidence:
            return edges_up, {
                "method": "vertical-edges",
                "assumption": "the scene's vertical edges are vertical",
                "edge_pixels": support,
                "camera_axes_millidegrees": round(
                    math.degrees(math.acos(max(-1.0, min(1.0, float(edges_up @ axes_up)))))
                    * MILLIDEGREES
                ),
                **facts,
            }
        return axes_up, {
            "method": axes_method,
            "assumption": "each photograph was held without roll",
            **facts,
        }
    raise ValueError(f"this join knows no way to estimate up named {policy.up_method!r}")


def _level(
    absolute: dict[int, np.ndarray], reference: int, up: np.ndarray
) -> tuple[dict[int, np.ndarray], list[float]]:
    """Turn the arrangement so ``up`` is +Y and the reference faces -Z; each photograph's roll."""
    nodes = sorted(absolute)
    target = np.array([0.0, 1.0, 0.0])
    axis = np.cross(up, target)
    sine = float(np.linalg.norm(axis))
    cosine = float(up @ target)
    tilt = (
        np.eye(3) if sine < 1e-12 else _rotation_from_vector(axis / sine * math.atan2(sine, cosine))
    )
    forward = tilt @ absolute[reference] @ np.array([0.0, 0.0, -1.0])
    heading = math.atan2(-forward[0], -forward[2])
    turn = _rotation_from_vector(np.array([0.0, -heading, 0.0]))
    leveled = {node: turn @ tilt @ rotation for node, rotation in absolute.items()}
    rolls = [
        math.degrees(math.asin(max(-1.0, min(1.0, float(leveled[node][1, 0]))))) for node in nodes
    ]
    return leveled, rolls


def join_standpoint(
    *,
    scene_ref: str,
    inputs: Sequence[StandpointInput],
    excluded: Sequence[StandpointExclusion] = (),
    policy: StandpointPolicy,
    policy_sha256: str,
    stage_version: int,
    extractor: FeatureExtractor,
) -> StandpointRecord:
    """Join what can be joined, and record everything, including every refusal."""
    ordered = sorted(inputs, key=lambda item: item.ordinal)
    ordinals = sorted([item.ordinal for item in ordered] + [item.ordinal for item in excluded])
    if ordinals != list(range(len(ordinals))):
        raise ValueError("standpoint members must be numbered 0 to n-1, once each")
    members: dict[int, _Member] = {}
    unreadable: dict[int, StandpointInput] = {}
    unstated: dict[int, StandpointInput] = {}
    for item in ordered:
        try:
            members[item.ordinal] = _prepare(item, policy, extractor)
        except OpmIntegrityError:
            unreadable[item.ordinal] = item
        except _FocalLengthUnstated:
            unstated[item.ordinal] = item
    readable = sorted(members)
    everyone = [(a, b) for position, a in enumerate(readable) for b in readable[position + 1 :]]
    # Where the photographs overlap, through the lenses they state; then the lenses, refined from
    # those overlaps; then every pair again, through the refined lenses, with every test.
    provisional = {
        (a, b): _join_pair(members[a], members[b], policy, provisional=True) for a, b in everyone
    }
    focals = _refine_focals(members, provisional, policy)
    members = {ordinal: _with_focal(member, focals[ordinal]) for ordinal, member in members.items()}
    pairs: dict[tuple[int, int], _PairResult] = {
        (a, b): _join_pair(members[a], members[b], policy) for a, b in everyone
    }

    accepted = {
        key for key, result in pairs.items() if result.record and result.record.outcome == "joined"
    }
    inconsistent: set[tuple[int, int]] = set()
    while True:
        components = _components(readable, sorted(accepted))
        worst: tuple[float, tuple[int, int]] | None = None
        solved: dict[int, np.ndarray] = {}
        rotation_residuals: dict[tuple[int, int], float] = {}
        for component in components:
            if len(component) < 2:
                continue
            edges = {
                key: (pairs[key].rotation, pairs[key].weight)  # type: ignore[misc]
                for key in sorted(accepted)
                if key[0] in component and key[1] in component
            }
            absolute, residuals = _solve_rotations(component, edges)  # type: ignore[arg-type]
            solved.update(absolute)
            rotation_residuals.update(residuals)
            for key, residual in residuals.items():
                if residual > policy.max_edge_residual_deg and (
                    worst is None or residual > worst[0]
                ):
                    worst = (residual, key)
        if worst is None:
            break
        accepted.discard(worst[1])
        inconsistent.add(worst[1])

    pair_records: list[StandpointPair] = []
    for key in sorted(pairs):
        record = pairs[key].record
        assert record is not None, "only the provisional pass leaves a pair without a record"
        if key in inconsistent:
            record = StandpointPair(**{**_fields(record), "outcome": "inconsistent_with_set"})
        pair_records.append(record)

    joined_components = [component for component in components if len(component) >= 2]
    all_components = sorted(
        [
            *components,
            *([ordinal] for ordinal in sorted(unreadable)),
            *([ordinal] for ordinal in sorted(unstated)),
            *([item.ordinal] for item in excluded),
        ],
        key=lambda group: (-len(group), group[0]),
    )
    arrangement: Arrangement | None = None
    joined: set[int] = set()
    if joined_components:
        component = joined_components[0]
        joined = set(component)
        reference = component[0]
        turned = {node: solved[node] for node in component}
        up_direction, up = _estimate_up(members, turned, policy)
        leveled, rolls = _level(turned, reference, up_direction)
        up["implied_roll_millidegrees"] = {
            "max": round(max(abs(roll) for roll in rolls) * MILLIDEGREES),
            "rms": round(math.sqrt(sum(roll * roll for roll in rolls) / len(rolls)) * MILLIDEGREES),
        }
        ratios = {
            key: (pairs[key].depth_ratio, pairs[key].weight)
            for key in sorted(accepted)
            if key[0] in joined and key[1] in joined
        }
        scales, scale_residuals = _solve_scales(component, ratios)  # type: ignore[arg-type]
        arranged = tuple(
            ArrangedMember(
                ordinal=node,
                scene_from_camera_ppb=_ppb(leveled[node]),
                depth_scale_ppm=round(scales[node] * PARTS_PER_MILLION),
                lateral_scale_ppm=round(
                    members[node].depth_focal_source
                    / members[node].focal_source
                    * PARTS_PER_MILLION
                ),
            )
            for node in component
        )
        edge_residuals = {key: rotation_residuals[key] for key in ratios}
        arrangement = Arrangement(
            reference=reference,
            members=arranged,
            up=up,
            rotation_solve={
                "edges": [
                    {
                        "a": a,
                        "b": b,
                        "residual_millidegrees": round(edge_residuals[(a, b)] * MILLIDEGREES),
                    }
                    for a, b in sorted(edge_residuals)
                ],
                "max_residual_millidegrees": round(max(edge_residuals.values()) * MILLIDEGREES),
            },
            scale_solve={
                "edges": [
                    {
                        "a": a,
                        "b": b,
                        "residual_ppm": round(abs(scale_residuals[(a, b)]) * PARTS_PER_MILLION),
                    }
                    for a, b in sorted(scale_residuals)
                ],
                "gauge": "geometric-mean-of-member-depth-scales",
                "max_residual_ppm": round(
                    max(abs(value) for value in scale_residuals.values()) * PARTS_PER_MILLION
                ),
            },
        )

    member_records: list[StandpointMember] = []
    for item in excluded:
        member_records.append(
            StandpointMember(
                ordinal=item.ordinal, member_ref=item.member_ref, outcome="not_permitted"
            )
        )
    for item in ordered:
        member = members.get(item.ordinal)
        if member is None:
            member_records.append(
                StandpointMember(
                    ordinal=item.ordinal,
                    member_ref=item.member_ref,
                    outcome=(
                        "focal_length_unstated"
                        if item.ordinal in unstated
                        else "point_map_unreadable"
                    ),
                    point_map_artifact_ref=item.point_map_artifact_ref,
                    point_map_sha256=hashlib.sha256(item.point_map).hexdigest(),
                )
            )
            continue
        member_records.append(
            StandpointMember(
                ordinal=item.ordinal,
                member_ref=item.member_ref,
                outcome="joined" if item.ordinal in joined else "not_joined",
                point_map_artifact_ref=item.point_map_artifact_ref,
                point_map_sha256=member.point_map_sha256,
                reading=MemberReading(
                    image_sha256=item.image_sha256,
                    source_size=member.source_size,
                    model_size=member.model_size,
                    intrinsics=MemberIntrinsics(
                        source=member.intrinsics_source,  # type: ignore[arg-type]
                        stated_focal_micropixels=round(member.stated_focal * MICROPIXELS),
                        focal_micropixels=round(member.focal_source * MICROPIXELS),
                        depth_model_focal_micropixels=round(
                            member.depth_focal_source * MICROPIXELS
                        ),
                    ),
                    features=len(member.xy),
                ),
            )
        )
    member_records.sort(key=lambda record: record.ordinal)
    return StandpointRecord(
        scene_ref=scene_ref,
        policy_sha256=policy_sha256,
        stage_version=stage_version,
        feature_extractor=extractor.identity,
        members=tuple(member_records),
        pairs=tuple(pair_records),
        components=tuple(tuple(component) for component in all_components),
        arrangement=arrangement,
        refusal=None if arrangement is not None else "nothing_joined",
    )


def _fields(record: StandpointPair) -> dict[str, Any]:
    return {name: getattr(record, name) for name in StandpointPair.__slots__}
