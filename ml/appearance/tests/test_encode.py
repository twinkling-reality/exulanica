"""Conditioning pictures: inverse depth over a stated range, distinct identity hues, exact edges."""

from __future__ import annotations

import numpy as np
from conftest import quad_scene

from exulanica_appearance.capture import encode
from exulanica_appearance.capture.raster import rasterize


def test_inverse_depth_spans_the_range_of_the_frames_given():
    depth = np.array([[0, 1_000_000], [2_000_000, 4_000_000]], dtype=np.uint32)
    near, far = encode.depth_range([depth])
    assert (near, far) == (1_000_000, 4_000_000)
    grey = encode.inverse_depth(depth, near, far)[..., 0]
    assert grey[0, 0] == 0 and grey[0, 1] == 255 and grey[1, 1] == 0
    assert 0 < grey[1, 0] < 255
    # A path's range, not a frame's: the same depth reads the same grey in every frame of the path.
    wider = encode.depth_range([depth, np.array([[500_000]], dtype=np.uint32)])
    assert encode.inverse_depth(depth, *wider)[0, 1, 0] < 255


def test_neighbouring_identities_get_distinct_hues():
    colours = encode.identity_colours(np.arange(0, 11, dtype=np.uint16), 10)
    assert tuple(colours[0]) == (0, 0, 0)
    for a in range(1, 11):
        for b in range(a + 1, 11):
            assert np.abs(colours[a].astype(int) - colours[b].astype(int)).max() >= 48, (a, b)


def test_edges_and_normals_encode_the_structure():
    triangles, camera = quad_scene()
    layers = rasterize(triangles, camera)
    edges = encode.edge_lines(layers.edges)
    assert set(np.unique(edges)) <= {0, 255}
    normal = encode.normal_camera(layers.normal, camera)
    # The wall faces the camera, so its camera-space normal is +Z: (128, 128, 255).
    assert tuple(normal[24, 32]) == (128, 128, 255)
    assert tuple(normal[0, 0]) == (0, 0, 0)
