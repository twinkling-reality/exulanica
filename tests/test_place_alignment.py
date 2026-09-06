"""Two captures of one place: the similarity fit, and every way it refuses.

Numeric fixtures with a known ground-truth transform, because no real capture pair exists. This
file measures the geometry and the thresholds; it establishes nothing about a real place, and
``docs/place-identity.md`` says so in the same words.
"""

from __future__ import annotations

import math

import pytest
from exulanica.reconstruction.place_alignment import (
    PLACE_ALIGNMENT_POLICY,
    PlaceCorrespondence,
    fit_place_alignment,
)


def _rotation(yaw: float, pitch: float) -> list[list[float]]:
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    return [
        [cy * cp, -sy, cy * sp],
        [sy * cp, cy, sy * sp],
        [-sp, 0.0, cp],
    ]


def _place(count: int = 20) -> list[tuple[str, tuple[float, float, float]]]:
    """Camera centres around one synthetic place, in that capture's own recovered frame."""
    cameras = []
    for index in range(count):
        angle = 2 * math.pi * index / count
        cameras.append(
            (
                f"capture-{index:03d}",
                (
                    3.0 * math.cos(angle),
                    0.4 * math.sin(3 * angle),
                    3.0 * math.sin(angle),
                ),
            )
        )
    return cameras


def _transform(
    cameras: list[tuple[str, tuple[float, float, float]]],
    *,
    scale: float,
    yaw: float,
    pitch: float,
    offset: tuple[float, float, float],
    noise: float = 0.0,
) -> list[PlaceCorrespondence]:
    """The same cameras as the joint reconstruction would recover them, plus optional error."""
    rotation = _rotation(yaw, pitch)
    out = []
    for order, (capture_ref, scene) in enumerate(cameras):
        joint = tuple(
            scale * sum(rotation[i][j] * scene[j] for j in range(3))
            + offset[i]
            # Deterministic, sign-alternating perturbation rather than a random one: a fixture
            # that changes between runs cannot be a regression test.
            + (noise * (1 if (order + i) % 2 == 0 else -1))
            for i in range(3)
        )
        out.append(PlaceCorrespondence(capture_ref, scene, joint))  # type: ignore[arg-type]
    return out


def test_a_clean_pair_recovers_the_transform_that_produced_it():
    cameras = _place()
    correspondences = _transform(cameras, scale=2.5, yaw=0.7, pitch=-0.3, offset=(12.0, -4.0, 6.0))
    result = fit_place_alignment(correspondences, connected=True)

    assert result.accepted, result.reason
    assert result.scene_units_to_joint_units == pytest.approx(2.5, rel=1e-6)
    matrix = result.joint_from_scene_row_major
    assert matrix is not None
    assert matrix[3] == pytest.approx(12.0, abs=1e-6)
    assert matrix[7] == pytest.approx(-4.0, abs=1e-6)
    assert matrix[11] == pytest.approx(6.0, abs=1e-6)
    assert matrix[12:] == (0.0, 0.0, 0.0, 1.0)
    assert result.diagnostics["physically_validated"] is False


def test_the_scale_in_the_matrix_is_the_scale_the_scalar_reports():
    """A consumer must not apply the scalar a second time, and here is why it can tell."""
    correspondences = _transform(_place(), scale=0.4, yaw=1.1, pitch=0.2, offset=(0.0, 0.0, 0.0))
    result = fit_place_alignment(correspondences, connected=True)
    matrix = result.joint_from_scene_row_major
    assert matrix is not None
    linear_scale = math.hypot(matrix[0], matrix[4], matrix[8])
    assert linear_scale == pytest.approx(result.scene_units_to_joint_units, rel=1e-9)


def test_a_disconnected_joint_reconstruction_is_refused_before_any_number_is_looked_at():
    """Two components can each be internally consistent and give a flattering residual."""
    correspondences = _transform(_place(), scale=1.0, yaw=0.0, pitch=0.0, offset=(0.0, 0.0, 0.0))
    result = fit_place_alignment(correspondences, connected=False)
    assert not result.accepted
    assert result.reason == "place-alignment-not-connected"


def test_too_few_cameras_is_a_refusal_rather_than_a_confident_fit():
    correspondences = _transform(
        _place(count=6), scale=1.0, yaw=0.3, pitch=0.0, offset=(1.0, 0.0, 0.0)
    )
    result = fit_place_alignment(correspondences, connected=True)
    assert not result.accepted
    assert result.reason == "place-alignment-insufficient-correspondences"


def test_a_pair_that_does_not_share_a_frame_is_refused():
    """The captures are of different places, so no similarity reconciles their cameras."""
    cameras = _place()
    scrambled = [
        PlaceCorrespondence(
            capture_ref=capture_ref,
            scene_xyz=scene,
            joint_xyz=(scene[2] * 1.7, scene[0] * -0.3, math.sin(index) * 4.0),
        )
        for index, (capture_ref, scene) in enumerate(cameras)
    ]
    result = fit_place_alignment(scrambled, connected=True)
    assert not result.accepted
    assert result.reason == "place-alignment-inconsistent"


def test_a_mirrored_fit_is_refused_rather_than_corrected():
    """A mirrored world can fit two camera sets closely and is not the same place."""
    cameras = _place()
    mirrored = [
        PlaceCorrespondence(capture_ref, scene, (scene[0], scene[1], -scene[2]))
        for capture_ref, scene in cameras
    ]
    result = fit_place_alignment(mirrored, connected=True)
    assert not result.accepted
    assert result.reason == "place-alignment-inconsistent"


def test_every_camera_at_one_point_is_refused_rather_than_scoring_zero():
    """A residual of zero over a degenerate set is arithmetic, not agreement."""
    collapsed = [
        PlaceCorrespondence(f"capture-{index:03d}", (0.0, 0.0, 0.0), (5.0, 5.0, 5.0))
        for index in range(20)
    ]
    result = fit_place_alignment(collapsed, connected=True)
    assert not result.accepted
    assert result.reason == "place-alignment-inconsistent"


def test_small_recovery_error_is_tolerated_and_large_error_is_not():
    """The threshold is a versioned engineering choice, and this is what it currently admits."""
    cameras = _place()
    tolerable = _transform(
        cameras, scale=1.0, yaw=0.5, pitch=0.1, offset=(2.0, 1.0, 0.0), noise=0.01
    )
    assert fit_place_alignment(tolerable, connected=True).accepted

    intolerable = _transform(
        cameras, scale=1.0, yaw=0.5, pitch=0.1, offset=(2.0, 1.0, 0.0), noise=0.6
    )
    refused = fit_place_alignment(intolerable, connected=True)
    assert not refused.accepted
    assert refused.reason == "place-alignment-inconsistent"


def test_the_validation_fold_is_never_fitted_on():
    """A fit judged on its own training points is judged on nothing.

    The discriminator is the PAIR of fractions, not either one alone, and that is worth spelling
    out because the obvious single assertion proves less than it looks.

    Poison only the reserved fifth. A fitter that honoured the fold produces a fit those four
    cameras never touched, so it is perfect on its sixteen and hopeless on the four: training 1.0,
    validation 0.0. A fitter that had trained on all twenty would have dragged its fit toward the
    poison, which makes the four poisoned cameras outliers of its own training set: its training
    fraction could not then be 1.0. No fitter can report both numbers at once except by having
    genuinely held the fold out.

    (An earlier version of this test asserted, instead, that poisoning the fitted four fifths would
    leave the validation fifth clean. That is false and the run said so: eighty percent of the data
    pulled nine units sideways moves the fit so far that the untouched fifth becomes the outlier.
    The measurement is kept below rather than deleted, because it is the honest description of what
    the fitter does under that input.)
    """
    cameras = _place()
    correspondences = _transform(cameras, scale=1.0, yaw=0.2, pitch=0.0, offset=(0.0, 0.0, 0.0))
    clean = fit_place_alignment(correspondences, connected=True)
    assert clean.accepted
    assert clean.diagnostics["training_correspondences"] == 16
    assert clean.diagnostics["validation_correspondences"] == 4

    stride = int(PLACE_ALIGNMENT_POLICY["validation_stride"])
    ordered = sorted(correspondences, key=lambda item: item.capture_ref)

    def poison(indices: set[int]) -> list[PlaceCorrespondence]:
        return [
            PlaceCorrespondence(
                item.capture_ref,
                item.scene_xyz,
                (item.joint_xyz[0] + 9.0, item.joint_xyz[1], item.joint_xyz[2])
                if index in indices
                else item.joint_xyz,
            )
            for index, item in enumerate(ordered)
        ]

    held_out = {index for index in range(len(ordered)) if index % stride == stride - 1}
    fitted_on = {index for index in range(len(ordered)) if index % stride != stride - 1}
    assert len(held_out) == 4 and len(fitted_on) == 16

    refused = fit_place_alignment(poison(held_out), connected=True)
    assert not refused.accepted
    assert refused.reason == "place-alignment-inconsistent"
    # The pair. Neither number alone would settle it.
    assert refused.diagnostics["validation_inlier_fraction_millionths"] == 0
    assert refused.diagnostics["training_inlier_fraction_millionths"] == 1_000_000

    # MEASURED: poisoning the fitted sixteen moves the fit far enough that the untouched four are
    # outliers too, so this refuses on both fractions rather than on one. Recorded because it is
    # what the fitter does, not because it distinguishes anything.
    other = fit_place_alignment(poison(fitted_on), connected=True)
    assert not other.accepted
    assert other.diagnostics["validation_inlier_fraction_millionths"] == 0


def test_the_fold_is_a_property_of_the_data_not_of_the_caller_s_list_order():
    correspondences = _transform(_place(), scale=1.3, yaw=0.9, pitch=0.4, offset=(3.0, 0.0, 1.0))
    forward = fit_place_alignment(correspondences, connected=True)
    backward = fit_place_alignment(list(reversed(correspondences)), connected=True)
    assert forward.joint_from_scene_row_major == backward.joint_from_scene_row_major


def test_one_capture_named_twice_is_a_programming_error_not_a_refusal():
    correspondences = _transform(_place(), scale=1.0, yaw=0.0, pitch=0.0, offset=(0.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="names one capture twice"):
        fit_place_alignment([*correspondences, correspondences[0]], connected=True)


def test_no_result_claims_a_physical_unit():
    correspondences = _transform(_place(), scale=7.5, yaw=0.1, pitch=0.1, offset=(0.0, 0.0, 0.0))
    result = fit_place_alignment(correspondences, connected=True)
    assert result.accepted
    assert result.diagnostics["physically_validated"] is False
    assert "metre" not in str(result.diagnostics).lower()
