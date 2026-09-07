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
    report = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, 1.0, 0.01)]),
        views=[_view(masked=(LEFT_HALF,))],
        min_opacity_millionths=500_000,
    )
    assert report["gaussians_over_masked_region"] == 0


def test_an_opaque_gaussian_above_the_floor_is_counted():
    report = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, 1.0, 0.99)]),
        views=[_view(masked=(LEFT_HALF,))],
        min_opacity_millionths=500_000,
    )
    assert report["gaussians_over_masked_region"] == 1


def test_a_logit_opacity_is_read_as_a_logit():
    """gsplat stores a logit; a raw 4.0 read as a probability would still pass, but 0.0 must not
    be read as fully transparent when it means one half."""
    report = count_masked_gaussians(
        ply=_ply([(-0.2, 0.0, 1.0, 4.0)]),
        views=[_view(masked=(LEFT_HALF,))],
        min_opacity_millionths=900_000,
    )
    assert report["gaussians_over_masked_region"] == 1


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
