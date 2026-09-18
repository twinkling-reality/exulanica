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


def test_the_stated_encodings_are_exactly_the_pictures_this_module_produces():
    """The vocabulary is held to the code both ways, so it cannot be quietly wrong.

    A published set of names that nothing loads is documentation with a type annotation. These are
    real: each is one function of a structure record's layers, each is named in a generation record
    and on a sheet's label, and the set is closed. So the test reads the module's own source for the
    functions that return a picture and compares that set with what is stated, in both directions.
    """
    import ast
    import inspect

    source = inspect.getsource(encode)
    tree = ast.parse(source)
    produces_a_picture = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
            continue
        returns = ast.unparse(node.returns) if node.returns is not None else ""
        if returns.replace(" ", "") == "NDArray[np.uint8]":
            produces_a_picture.add(node.name)
    # A parse that finds nothing must fail here rather than agree with an empty set.
    assert len(produces_a_picture) >= 4, produces_a_picture

    named = {role: function.__name__ for role, function in encode.ENCODERS.items()}
    assert set(named.values()) == produces_a_picture, (named, produces_a_picture)
    assert set(encode.ENCODERS) == set(encode.ENCODINGS)
    for role, entry in encode.ENCODINGS.items():
        assert set(entry) == {"name", "reason"}, role
        assert entry["name"] and entry["reason"].strip(), role
        assert encode.ENCODERS[role].__module__ == encode.__name__
    # Distinct names, or two records could claim the same encoding for different pictures.
    assert len({entry["name"] for entry in encode.ENCODINGS.values()}) == len(encode.ENCODINGS)


def test_the_before_sheet_labels_come_from_the_stated_encodings(tmp_path):
    """The one runtime that draws these pictures names them from the vocabulary, not its own prose."""
    import inspect

    from exulanica_appearance import sheets

    drawn = inspect.getsource(sheets.before_sheets)
    for role in ("depth", "segmentation", "edge"):
        assert f"encode.ENCODINGS['{role}']['name']" in drawn, role
