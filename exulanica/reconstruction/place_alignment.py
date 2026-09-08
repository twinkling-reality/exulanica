"""Fit one shared frame between two captures of the same place, or refuse and say why.

Roadmap Phase 10 capability 3, and experiment FR-2's measurement. See
``docs/place-identity.md`` for the design this implements and, more importantly, for the
constraint that shapes it: retained receipts alone cannot align two captures, because no learned
feature descriptors are persisted and COLMAP point ids mean nothing across two reconstructions. The
correspondences this fitter consumes therefore come from a **joint reconstruction over both capture
sets**, which recovers each scene's cameras a second time in one shared frame. What is fitted here
is the similarity between a scene's own frame and that joint frame.

The discipline is copied from ``exulanica.reconstruction.alignment``, deliberately and in full,
because that pattern has already caught real failures on real photographs:

*   **A validation fold reserved before fitting.** Every fifth correspondence by a deterministic
    ordering never enters the fit. A residual measured on the points that produced it measures
    nothing at all.
*   **A similarity, not an affine.** Rotation, one positive scale, translation. Permitting shear
    would let a bad correspondence set reach a low residual by deforming the world, which is the
    exact failure the residual exists to catch. Kabsch with a reflection guard, so a mirrored fit
    is refused rather than accepted at a flattering residual.
*   **Refusal is an outcome.** A refused pair is two places, and the world says their frames could
    not be reconciled. The 2026-09-05 volcanic coverage refusal is the precedent: a measured
    refusal, recorded, is a result.

**No metres.** Both frames are recovered COLMAP frames. Two captures sharing one frame is a
statement about their consistency with each other and about nothing physical, and
``physically_validated`` is False in every result this module can produce.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Final, Literal

__all__ = [
    "PLACE_ALIGNMENT_POLICY",
    "PlaceAlignmentResult",
    "PlaceCorrespondence",
    "fit_place_alignment",
]

#: Integer policy, shared with whatever stage records this, so a changed limit changes the build
#: identity rather than silently reinterpreting an old result. These are versioned engineering
#: choices, not corpus-calibrated quality claims: no real capture pair has been measured, and
#: ``docs/place-identity.md`` says the tolerance must be chosen from an observed distribution
#: rather than declared in advance.
PLACE_ALIGNMENT_POLICY: Final[dict[str, Any]] = {
    "method": "joint-reconstruction-camera-similarity/v1",
    "minimum_training_correspondences": 8,
    "minimum_validation_correspondences": 3,
    "validation_stride": 5,
    "maximum_relative_residual_millionths": 50_000,
    "minimum_inlier_fraction_millionths": 600_000,
}

PlaceAlignmentReason = Literal[
    "place-alignment-not-connected",
    "place-alignment-insufficient-correspondences",
    "place-alignment-inconsistent",
]

_Vector = tuple[float, float, float]



@dataclass(frozen=True, slots=True)
class PlaceCorrespondence:
    """One camera, located twice: in its own scene's frame and in the joint frame.

    ``capture_ref`` identifies the photograph, and it is what the deterministic ordering is taken
    over, so the validation fold is a property of the data rather than of the order a caller
    happened to build a list in.
    """

    capture_ref: str
    scene_xyz: _Vector
    joint_xyz: _Vector


@dataclass(frozen=True, slots=True)
class PlaceAlignmentResult:
    """The fitted similarity and the numbers that decided it, or a refusal and the same numbers."""

    #: Row-major 4x4 ``joint_from_scene``. None when refused.
    joint_from_scene_row_major: tuple[float, ...] | None
    #: The uniform scale already present in the linear block above. A consumer must not apply it
    #: a second time, the same rule ``scene_from_opm`` states for its own scalar.
    scene_units_to_joint_units: float | None
    reason: PlaceAlignmentReason | None
    diagnostics: dict[str, Any]

    @property
    def accepted(self) -> bool:
        return self.joint_from_scene_row_major is not None


def _centroid(points: list[_Vector]) -> _Vector:
    count = len(points)
    return (
        sum(p[0] for p in points) / count,
        sum(p[1] for p in points) / count,
        sum(p[2] for p in points) / count,
    )


def _kabsch(source: list[_Vector], target: list[_Vector]) -> tuple[list[list[float]], float] | None:
    """Rotation and one positive scale taking ``source`` onto ``target``, or None if degenerate.

    Kabsch by way of an explicit 3x3 SVD would need a linear-algebra dependency this layer does
    not carry, so the rotation is the orthogonal polar factor of the cross-covariance, found by
    Newton iteration (see :func:`_orthogonal_polar_factor`). For a similarity that is the same
    answer SVD gives, because the optimal rotation is the orthogonal factor of that matrix.

    The reflection guard is the part that matters: a negative determinant means the best-fitting
    orthogonal transform mirrors the world, and a mirrored place is not the same place, so it is
    refused rather than corrected into the nearest proper rotation.
    """
    source_centre = _centroid(source)
    target_centre = _centroid(target)
    a = [[p[i] - source_centre[i] for i in range(3)] for p in source]
    b = [[p[i] - target_centre[i] for i in range(3)] for p in target]

    covariance = [
        [sum(b[k][i] * a[k][j] for k in range(len(a))) for j in range(3)] for i in range(3)
    ]
    rotation = _orthogonal_polar_factor(covariance)
    if rotation is None:
        return None
    if _determinant(rotation) <= 0:
        # A reflection, not a rotation. Refused rather than nudged: a mirrored world can fit two
        # camera sets closely and is not the same place.
        return None

    numerator = sum(
        sum(rotation[i][j] * a[k][j] for j in range(3)) * b[k][i]
        for k in range(len(a))
        for i in range(3)
    )
    denominator = sum(sum(component * component for component in row) for row in a)
    if denominator <= 0 or numerator <= 0:
        return None
    return rotation, numerator / denominator


def _orthogonal_polar_factor(matrix: list[list[float]]) -> list[list[float]] | None:
    """The orthogonal polar factor of ``matrix``, by averaging it with its inverse transpose.

    The classic Newton iteration ``X <- (X + X^-T) / 2``, which converges quadratically to the
    orthogonal factor of a nonsingular matrix. Chosen over an SVD because this layer carries no
    linear-algebra dependency and the matrix is always 3x3.

    A singular input returns None, which the caller turns into a refusal. That is the correct
    outcome rather than a nuisance: a singular cross-covariance means the cameras are collinear or
    coincident, so no rotation is determined and any matrix returned would be an arbitrary choice
    presented as a fit.
    """
    current = [row[:] for row in matrix]
    for _ in range(64):
        inverse = _inverse(current)
        if inverse is None:
            return None
        nxt = [[0.5 * (current[i][j] + inverse[j][i]) for j in range(3)] for i in range(3)]
        delta = max(abs(nxt[i][j] - current[i][j]) for i in range(3) for j in range(3))
        current = nxt
        if delta < 1e-15:
            break
    return current


def _determinant(m: list[list[float]]) -> float:
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def _inverse(m: list[list[float]]) -> list[list[float]] | None:
    determinant = _determinant(m)
    if abs(determinant) < 1e-12:
        return None
    cofactors = [
        [
            (m[(i + 1) % 3][(j + 1) % 3] * m[(i + 2) % 3][(j + 2) % 3])
            - (m[(i + 1) % 3][(j + 2) % 3] * m[(i + 2) % 3][(j + 1) % 3])
            for j in range(3)
        ]
        for i in range(3)
    ]
    return [[cofactors[j][i] / determinant for j in range(3)] for i in range(3)]


def _apply(
    rotation: list[list[float]],
    scale: float,
    translation: _Vector,
    point: _Vector,
) -> _Vector:
    return tuple(  # type: ignore[return-value]
        scale * sum(rotation[i][j] * point[j] for j in range(3)) + translation[i] for i in range(3)
    )


def fit_place_alignment(
    correspondences: list[PlaceCorrespondence],
    *,
    connected: bool,
) -> PlaceAlignmentResult:
    """Fit ``joint_from_scene`` on four fifths of the cameras and judge it on the untouched fifth.

    ``connected`` is the joint reconstruction's own verdict that both capture sets landed in one
    connected model. It is a separate input rather than something inferred from the numbers,
    because two disconnected components can each be internally consistent and produce a flattering
    residual over whichever cameras happen to be present.
    """
    diagnostics: dict[str, Any] = {
        "method": PLACE_ALIGNMENT_POLICY["method"],
        "physically_validated": False,
        "correspondence_count": len(correspondences),
    }

    def refused(reason: PlaceAlignmentReason) -> PlaceAlignmentResult:
        return PlaceAlignmentResult(None, None, reason, diagnostics)

    if not connected:
        return refused("place-alignment-not-connected")

    ordered = sorted(correspondences, key=lambda item: item.capture_ref)
    if len({item.capture_ref for item in ordered}) != len(ordered):
        raise ValueError("a place alignment correspondence set names one capture twice")

    stride = int(PLACE_ALIGNMENT_POLICY["validation_stride"])
    training = [item for index, item in enumerate(ordered) if index % stride != stride - 1]
    validation = [item for index, item in enumerate(ordered) if index % stride == stride - 1]
    diagnostics["training_correspondences"] = len(training)
    diagnostics["validation_correspondences"] = len(validation)

    if len(training) < int(PLACE_ALIGNMENT_POLICY["minimum_training_correspondences"]) or len(
        validation
    ) < int(PLACE_ALIGNMENT_POLICY["minimum_validation_correspondences"]):
        return refused("place-alignment-insufficient-correspondences")

    fitted = _kabsch([item.scene_xyz for item in training], [item.joint_xyz for item in training])
    if fitted is None:
        return refused("place-alignment-inconsistent")
    rotation, scale = fitted

    source_centre = _centroid([item.scene_xyz for item in training])
    target_centre = _centroid([item.joint_xyz for item in training])
    translation: _Vector = tuple(  # type: ignore[assignment]
        target_centre[i] - scale * sum(rotation[i][j] * source_centre[j] for j in range(3))
        for i in range(3)
    )

    # The scale of the scene itself, used to make residuals relative. Taken from the training
    # cameras' spread rather than from an assumed unit, because a recovered frame has no unit.
    spread = math.sqrt(
        sum(sum((item.scene_xyz[i] - source_centre[i]) ** 2 for i in range(3)) for item in training)
        / len(training)
    )
    if spread <= 0:
        # Every training camera at one point. There is no geometry to fit and a residual of zero
        # would be arithmetic rather than agreement.
        #
        # MEASURED 2026-09-07 by negative control: this branch is unreachable, and two separate
        # mutations that tried to prove otherwise both survived. A coincident training set gives a
        # zero cross-covariance, which three guards inside ``_kabsch`` catch in turn: the polar
        # factor is singular, and if that were removed the denominator is zero, and if that were
        # removed too the numerator is. So the coincident-cameras test is satisfied by whichever
        # fires first, no single-guard mutation can be attributed to it, and the spread can never
        # be non-positive by the time it is read here. Kept as defence in depth against a future
        # ``_kabsch`` that refuses less, and documented rather than deleted because a reader who
        # removes it should know what does the work today.
        return refused("place-alignment-inconsistent")
    joint_spread = spread * scale

    tolerance = int(PLACE_ALIGNMENT_POLICY["maximum_relative_residual_millionths"]) / 1_000_000
    minimum_fraction = int(PLACE_ALIGNMENT_POLICY["minimum_inlier_fraction_millionths"]) / 1_000_000

    def residuals(items: list[PlaceCorrespondence]) -> list[float]:
        out = []
        for item in items:
            predicted = _apply(rotation, scale, translation, item.scene_xyz)
            # All three components, never distance from a centre: agreement on one derived
            # quantity can hide a wrong geometry, which is the reason the point-map fitter gives.
            error = math.sqrt(sum((predicted[i] - item.joint_xyz[i]) ** 2 for i in range(3)))
            out.append(error / joint_spread)
        return out

    training_residuals = residuals(training)
    validation_residuals = residuals(validation)
    training_inliers = sum(1 for value in training_residuals if value <= tolerance)
    validation_inliers = sum(1 for value in validation_residuals if value <= tolerance)

    diagnostics.update(
        {
            "scene_units_to_joint_units_micro": round(scale * 1_000_000),
            "training_inlier_fraction_millionths": round(
                training_inliers / len(training) * 1_000_000
            ),
            "validation_inlier_fraction_millionths": round(
                validation_inliers / len(validation) * 1_000_000
            ),
            "validation_p90_relative_residual_millionths": round(
                sorted(validation_residuals)[max(0, math.ceil(len(validation_residuals) * 0.9) - 1)]
                * 1_000_000
            ),
        }
    )

    if (
        training_inliers / len(training) < minimum_fraction
        or validation_inliers / len(validation) < minimum_fraction
    ):
        return refused("place-alignment-inconsistent")

    matrix = (
        scale * rotation[0][0],
        scale * rotation[0][1],
        scale * rotation[0][2],
        translation[0],
        scale * rotation[1][0],
        scale * rotation[1][1],
        scale * rotation[1][2],
        translation[1],
        scale * rotation[2][0],
        scale * rotation[2][1],
        scale * rotation[2][2],
        translation[2],
        0.0,
        0.0,
        0.0,
        1.0,
    )
    return PlaceAlignmentResult(matrix, scale, None, diagnostics)
