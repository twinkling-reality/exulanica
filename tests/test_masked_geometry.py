"""Did a hidden person leave any geometry behind?

Masking a source is a claim about what the trainer saw. This is the check that turns it into a
claim about what the trainer produced, and the design note asks for it by name because the two are
not the same: a mask applied to the wrong frame, a held-out view slipping into training, or a
region confirmed on one photograph and missed on another all leave a body in the scene while every
receipt says otherwise.

The scenes here are built vertex by vertex rather than trained, so what is pinned is the counting,
the projection and the direction the check errs in. It does not establish anything about a real
trained scene, and the evaluation record must not read as though it does.
"""

from __future__ import annotations

import struct

import pytest
from exulanica.consent.regions import Silhouette
from exulanica.evidence.region import Rect
from exulanica.ingest.masked_geometry import (
    GaussianView,
    count_masked_gaussians,
    masked_geometry_is_clean,
    read_gaussian_centres,
)

IDENTITY = (1.0, 0.0, 0.0, 0.0)


def _ply(vertices, *, with_opacity=True):
    names = ["x", "y", "z"] + (["opacity"] if with_opacity else [])
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(vertices)}\n"
        + "".join(f"property float {name}\n" for name in names)
        + "end_header\n"
    )
    body = b"".join(struct.pack("<" + "f" * len(names), *vertex) for vertex in vertices)
    return header.encode("ascii") + body


def _view(masked=(), confirmed=()):
    return GaussianView(
        image_name="000000.jpg",
        quaternion_wxyz=IDENTITY,
        translation_xyz=(0.0, 0.0, 0.0),
        image_size=(100, 100),
        focal_xy=(100.0, 100.0),
        principal_xy=(50.0, 50.0),
        masked=masked,
        confirmed=confirmed,
    )


LEFT_HALF = Silhouette.from_rect(Rect.from_normalised(0.0, 0.0, 0.5, 1.0))


def test_a_gaussian_over_a_masked_region_is_counted():
    """One Gaussian at x=-0.2 projects to u=30, inside the left half."""
    report = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, 1.0, 1.0)]), views=[_view(masked=(LEFT_HALF,))]
    )
    assert report["gaussians_over_masked_region"] == 1
    assert masked_geometry_is_clean(report) is False


def test_a_gaussian_outside_every_masked_region_is_not_counted():
    """x=+0.2 projects to u=70, in the unmasked right half."""
    report = count_masked_gaussians(
        ply=_ply([(0.2, 0.0, 1.0, 1.0)]), views=[_view(masked=(LEFT_HALF,))]
    )
    assert report["gaussians_over_masked_region"] == 0
    assert masked_geometry_is_clean(report) is True


def test_a_scene_with_no_masked_region_is_clean_and_still_counts_confirmed_people():
    """So the check produces a real number on a scene trained before any of this existed."""
    report = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, 1.0, 1.0)]), views=[_view(confirmed=(LEFT_HALF,))]
    )
    assert report["gaussians_over_masked_region"] == 0
    assert report["gaussians_over_confirmed_region"] == 1


def test_a_gaussian_behind_the_camera_is_not_projected():
    report = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, -1.0, 1.0)]), views=[_view(masked=(LEFT_HALF,))]
    )
    assert report["gaussians_over_masked_region"] == 0


def test_a_gaussian_outside_the_frame_is_not_projected():
    report = count_masked_gaussians(
        ply=_ply([(-9.0, 0.0, 1.0, 1.0)]), views=[_view(masked=(LEFT_HALF,))]
    )
    assert report["gaussians_over_masked_region"] == 0


def test_a_faint_gaussian_below_the_opacity_floor_is_not_counted():
    """Stored -6.0, which is opacity 0.0025 as a logit and not a probability at all.

    It used to store 0.01, which is faint only under the face-value reading that was removed:
    read as the logit this repository's exporter actually writes, 0.01 is opacity 0.5025 and
    belongs above a half floor. Keeping that fixture would have made the test's name a lie about
    what it stores, so the fixture moved rather than the assertion.
    """
    report = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, 1.0, -6.0)]),
        views=[_view(masked=(LEFT_HALF,))],
        min_opacity_millionths=500_000,
    )
    assert report["gaussians_over_masked_region"] == 0


def test_a_half_opaque_gaussian_stored_as_logit_zero_is_not_dropped_by_a_half_floor():
    """A body at half opacity reported as clean, which is the module's own forbidden direction.

    MEASURED 2026-09-07 against the code before this fix: this exact call returned
    ``gaussians_over_masked_region == 0`` and ``masked_geometry_is_clean(report) is True``. The
    stored 0.0 is a gsplat logit meaning half opaque, and the ambiguous-range branch read it at
    face value as fully transparent. Latent only because the default floor is 0 and nothing calls
    the module; reachable the instant a caller sets a floor, which is the first thing wiring the
    count into anything would do.
    """
    report = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, 1.0, 0.0)]),
        views=[_view(masked=(LEFT_HALF,))],
        min_opacity_millionths=500_000,
    )
    assert report["gaussians_over_masked_region"] == 1
    assert masked_geometry_is_clean(report) is False
    assert report["opacity_reading"] == "logit or probability, whichever is higher"


def test_a_corrupt_opacity_saturates_rather_than_crashing_the_check():
    """-1e10 used to raise OverflowError out of math.exp, from a ValueError-only module.

    A corrupt scene is the scene that most needs the check to run, and a traceback is not a
    number. The value is finite, so refusing it as nonfinite is not available; it saturates.
    """
    report = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, 1.0, -1e10)]),
        views=[_view(masked=(LEFT_HALF,))],
        min_opacity_millionths=1,
    )
    assert report["gaussians_over_masked_region"] == 0
    at_no_floor = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, 1.0, 1e10)]), views=[_view(masked=(LEFT_HALF,))]
    )
    assert at_no_floor["gaussians_over_masked_region"] == 1


def test_a_nonfinite_opacity_is_refused_rather_than_read_as_transparent():
    """A NaN opacity must not resolve to "barely there" once the sigmoid exponent is clamped.

    NaN loses every comparison, so ``min(60.0, nan)`` is 60.0 and the clamp would hand the
    transparent end of the curve to a Gaussian whose opacity the file never stated: the exact
    under-report the module exists to prevent. The header walk checked x, y and z for
    finiteness and never the opacity column.
    """
    with pytest.raises(ValueError, match="nonfinite opacity"):
        read_gaussian_centres(_ply([(-0.2, 0.0, 1.0, float("nan"))]))


def test_an_opaque_gaussian_above_the_floor_is_counted():
    report = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, 1.0, 0.99)]),
        views=[_view(masked=(LEFT_HALF,))],
        min_opacity_millionths=500_000,
    )
    assert report["gaussians_over_masked_region"] == 1


def test_a_logit_opacity_is_read_as_a_logit():
    """gsplat stores a logit; a raw 4.0 read as a probability would still pass, but 0.0 must not
    be read as fully transparent when it means one half.

    The second half of that sentence used to have no assertion under it: only 4.0 was exercised,
    so the docstring described behaviour the test did not hold. Both cases are now here, and 0.0
    is checked at the floor its sigmoid clears rather than at 4.0's.
    """
    report = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, 1.0, 4.0)]),
        views=[_view(masked=(LEFT_HALF,))],
        min_opacity_millionths=900_000,
    )
    assert report["gaussians_over_masked_region"] == 1
    half = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, 1.0, 0.0)]),
        views=[_view(masked=(LEFT_HALF,))],
        min_opacity_millionths=400_000,
    )
    assert half["gaussians_over_masked_region"] == 1, "logit 0.0 is opacity 0.5, not opacity 0.0"


def test_a_scene_without_opacity_says_so_rather_than_assuming_faint():
    report = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, 1.0)], with_opacity=False),
        views=[_view(masked=(LEFT_HALF,))],
        min_opacity_millionths=900_000,
    )
    assert report["opacity"] == "unavailable"
    assert report["gaussians_over_masked_region"] == 1, "an unknown opacity must still be counted"


def test_the_margin_errs_toward_reporting_more():
    """A Gaussian just outside the outline is still reported, because missing one is worse."""
    narrow = Silhouette.from_rect(Rect.from_normalised(0.0, 0.0, 0.29, 1.0))
    inside_margin = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, 1.0, 1.0)]),
        views=[_view(masked=(narrow,))],
        margin_ppm=30_000,
    )
    no_margin = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, 1.0, 1.0)]),
        views=[_view(masked=(narrow,))],
        margin_ppm=0,
    )
    assert inside_margin["gaussians_over_masked_region"] == 1
    assert no_margin["gaussians_over_masked_region"] == 0


def test_every_view_is_reported_separately():
    report = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, 1.0, 1.0)]),
        views=[_view(masked=(LEFT_HALF,)), _view(masked=())],
    )
    assert len(report["views"]) == 2
    assert report["views"][0]["gaussians_over_masked_region"] == 1
    assert report["views"][1]["gaussians_over_masked_region"] == 0


def test_a_ply_that_is_not_binary_little_endian_is_refused():
    with pytest.raises(ValueError, match="binary little endian"):
        read_gaussian_centres(b"ply\nformat ascii 1.0\nelement vertex 1\nend_header\n")


def test_a_ply_whose_bytes_disagree_with_its_header_is_refused():
    good = _ply([(0.0, 0.0, 1.0, 1.0)])
    with pytest.raises(ValueError, match="disagree with its header"):
        read_gaussian_centres(good[:-4])


def test_a_nonfinite_gaussian_is_refused_rather_than_skipped():
    with pytest.raises(ValueError, match="nonfinite"):
        read_gaussian_centres(_ply([(float("nan"), 0.0, 1.0, 1.0)]))
