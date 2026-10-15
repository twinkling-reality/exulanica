"""Likeness on a model written here: two boxes in an L, one red and one blue, so no turn draws the
same outline in the same colours as another. Its own view at a known turn is the positive control;
a different shape and a recoloured picture each read further from it.
"""

from __future__ import annotations

import numpy as np

from exulanica_appearance.creatures.geometry import Camera, rasterise
from exulanica_appearance.creatures.likeness import framed_cutout, likeness

RED, BLUE = (200, 40, 40), (40, 60, 200)


def _box(low, high) -> np.ndarray:
    (x0, y0, z0), (x1, y1, z1) = low, high
    v = np.array(
        [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
         [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]
    )  # fmt: skip
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]  # fmt: skip
    return v[np.array(faces)]


def _model(upright=((0.0, 0.0, 0.0), (0.2, 0.2, 0.8)), along=((0.2, 0.0, 0.0), (0.7, 0.2, 0.25))):
    first, second = _box(*upright), _box(*along)
    corners = np.concatenate([first, second])
    positions = corners.reshape(-1, 3)
    triangles = np.arange(len(positions)).reshape(-1, 3)
    colours = np.array([RED] * len(first) + [BLUE] * len(second), dtype=np.uint8)
    return positions, triangles, colours


def _picture(positions, triangles, colours, camera, size=300) -> np.ndarray:
    """The model's own view as a cut-out: its colours where it is drawn, clear elsewhere."""
    drawn = rasterise(positions[triangles], camera, size, margin=0.2)
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    rgba[drawn.mask, :3] = colours[drawn.triangle[drawn.mask]]
    rgba[drawn.mask, 3] = 255
    return rgba


def test_a_model_against_its_own_view_is_found_at_that_turn():
    positions, triangles, colours = _model()
    found = likeness(
        positions, triangles, colours, _picture(positions, triangles, colours, Camera(37.0, 15.0))
    )
    assert abs(found.yaw_degrees - 37) <= 1 and found.pitch_degrees == 15
    assert found.outline_overlap_per_mille >= 950
    assert found.colour_difference_milli is not None and found.colour_difference_milli <= 30


def test_another_shape_and_other_colours_read_further_from_the_model():
    positions, triangles, colours = _model()
    own = likeness(
        positions, triangles, colours, _picture(positions, triangles, colours, Camera(37.0, 15.0))
    )
    other = _model(along=((0.2, 0.0, 0.0), (0.4, 0.2, 0.7)))
    shape = likeness(positions, triangles, colours, _picture(*other, Camera(37.0, 15.0)))
    assert shape.outline_overlap_per_mille < own.outline_overlap_per_mille - 50
    swapped = colours[:, ::-1].copy()
    recoloured = likeness(
        positions, triangles, colours, _picture(positions, triangles, swapped, Camera(37.0, 15.0))
    )
    assert recoloured.colour_difference_milli > own.colour_difference_milli + 100


def test_an_empty_cutout_has_no_outline_and_no_colour():
    positions, triangles, colours = _model()
    mask, framed = framed_cutout(np.zeros((64, 64, 4), dtype=np.uint8))
    assert not mask.any() and not framed.any()
    found = likeness(positions, triangles, colours, np.zeros((64, 64, 4), dtype=np.uint8))
    assert found.outline_overlap_per_mille == 0
    assert found.colour_difference_milli is None and found.model_mean_srgb is None


def test_oklab_to_srgb_inverts_the_shared_oklab_reading():
    from exulanica_pieces.geometry.palette import _oklab

    from exulanica_appearance.creatures.likeness import oklab_to_srgb

    colours = np.array(
        [[0, 0, 0], [255, 255, 255], [200, 40, 40], [40, 60, 200], [234, 198, 120], [13, 250, 77]],
        dtype=np.uint8,
    )
    assert np.abs(oklab_to_srgb(_oklab(colours)).astype(int) - colours.astype(int)).max() <= 1


def test_a_model_paler_than_its_picture_is_moved_toward_it_within_the_bound():
    from exulanica_appearance.creatures.likeness import MATCH_BOUND, match_to_picture

    positions, triangles, colours = _model()
    # The picture's colours richer than the model's, as a model made from a picture comes back.
    rich = np.array([(230, 30, 20)] * 12 + [(20, 50, 235)] * 12, dtype=np.uint8)
    picture = _picture(positions, triangles, rich, Camera(37.0, 15.0))
    moved, match, before, after = match_to_picture(positions, triangles, colours, picture)
    assert match is not None
    assert after.colour_difference_milli < before.colour_difference_milli
    assert all(abs(shift) <= bound for shift, bound in zip(match.shift, MATCH_BOUND, strict=True))
    assert moved.shape == colours.shape and not np.array_equal(moved, colours)


def test_with_no_pixel_in_common_the_colours_stay_as_they_are():
    from exulanica_appearance.creatures.likeness import match_to_picture

    positions, triangles, colours = _model()
    empty = np.zeros((64, 64, 4), dtype=np.uint8)
    moved, match, before, after = match_to_picture(positions, triangles, colours, empty)
    assert match is None and before == after
    assert np.array_equal(moved, colours)
