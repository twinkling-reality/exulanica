"""The numpy half of the piece format: orienting, fitting, simplifying, colouring and writing.

numpy arrives with the `reconstruction` extra; a plain `uv sync`, as CI runs, does not install it,
and these tests skip there. Expected values are hand-worked rotations and fits and a container
read back with struct rather than through the writer.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

pytest.importorskip(
    "numpy", reason="numpy is absent; install it with `uv sync --extra reconstruction`"
)

import numpy as np
from exulanica_pieces import colour
from exulanica_pieces.canonical import Refused
from exulanica_pieces.geometry.glb import write_glb
from exulanica_pieces.geometry.mesh import (
    Mesh,
    cluster_simplify,
    fit,
    flat_palette,
    orient,
    simplify_to,
)
from exulanica_pieces.geometry.palette import nearest_swatch
from exulanica_pieces.geometry.postprocess import make_piece
from exulanica_pieces.records import build_request, read_request

PACK = {
    "id": "test.toon-town",
    "palette": [[46, 42, 40], [120, 78, 48], [176, 120, 72], [70, 132, 64], [214, 72, 58]],
    "sha256": "0" * 64,
    "style": "toon style, flat colours, chunky simple shapes",
    "version": 1,
}
BENCH = {"look_role": "prop.bench", "slot_mm": {"width": 1800, "height": 900, "depth": 700}}
ROOT = Path(__file__).resolve().parents[1]


def _box(extent: tuple[float, float, float]) -> Mesh:
    x, y, z = extent
    v = np.array([[a, b, c] for a in (0, x) for b in (0, y) for c in (0, z)], dtype=np.float64)
    f = np.array(
        [
            [0, 1, 3],
            [0, 3, 2],
            [4, 6, 7],
            [4, 7, 5],
            [0, 4, 5],
            [0, 5, 1],
            [2, 3, 7],
            [2, 7, 6],
            [0, 2, 6],
            [0, 6, 4],
            [1, 5, 7],
            [1, 7, 3],
        ]
    )
    return Mesh(v, f, np.tile(np.array([[200, 40, 40]], dtype=np.uint8), (8, 1)))


def _grid(cells: int) -> Mesh:
    """A flat square of cells x cells quads, two triangles each, lying in z = 0."""
    side = np.linspace(0.0, 1.0, cells + 1)
    xs, ys = np.meshgrid(side, side)
    positions = np.stack([xs.ravel(), ys.ravel(), np.zeros(xs.size)], axis=1)
    triangles = []
    for row in range(cells):
        for column in range(cells):
            a = row * (cells + 1) + column
            b, c, d = a + 1, a + cells + 1, a + cells + 2
            triangles += [[a, b, d], [a, d, c]]
    colours = np.tile(np.array([[90, 140, 70]], dtype=np.uint8), (len(positions), 1))
    return Mesh(positions, np.array(triangles), colours)


def test_a_colour_snaps_to_the_swatch_a_person_would_pick() -> None:
    palette = [[20, 20, 20], [200, 40, 40], [40, 160, 60]]
    picks = nearest_swatch(np.array([[190, 60, 50], [10, 10, 30], [60, 150, 70]]), palette)
    assert picks.tolist() == [1, 0, 2]


def test_orient_takes_up_to_plus_y_and_front_to_plus_z_by_a_rotation() -> None:
    point = Mesh(
        np.array([[1.0, 2.0, 3.0], [0, 0, 0], [0, 0, 1]]),
        np.array([[0, 1, 2]]),
        np.zeros((3, 3), np.uint8),
    )
    out, record = orient(point, "+Z", "-Y")
    # Raw up +Z becomes y; raw front -Y becomes z, so raw y = 2 goes to z = -2; glTF x is up
    # cross front = Z x -Y = +X, so x stays 1.
    assert out.positions[0].tolist() == [1.0, 3.0, -2.0]
    assert record == {"front": "-Y", "step": "orient", "up": "+Z"}
    with pytest.raises(Refused):
        orient(point, "+Z", "-Z")


def test_contain_scales_uniformly_and_stands_the_base_centre_on_the_origin() -> None:
    out, record = fit(
        _box((1.0, 3.0, 2.0)), "contain", {"width": 500, "height": 1200, "depth": 800}
    )
    # Height limits: 1.2 / 3 = 0.4, so 400 x 1200 x 800, 100 mm spare in width.
    assert record["size_mm"] == {"width": 400, "height": 1200, "depth": 800}
    assert record["gap_mm"] == {"width": 100, "height": 0, "depth": 0}
    assert record["scale_per_million"] == 400_000
    assert out.positions[:, 1].min() == 0
    assert np.allclose(out.positions[:, [0, 2]].min(axis=0), -out.positions[:, [0, 2]].max(axis=0))


def test_fill_refuses_a_piece_the_page_could_not_stretch_to_its_slot() -> None:
    # A cube in a door slot: contained at 300 mm, the page would stretch width 4x.
    with pytest.raises(Refused, match="proportions"):
        fit(_box((1.0, 1.0, 1.0)), "fill", {"width": 1200, "height": 2400, "depth": 300})
    _, record = fit(_box((1.1, 2.3, 0.25)), "fill", {"width": 1200, "height": 2400, "depth": 300})
    assert all(800 <= value <= 1250 for value in record["stretch_per_mille"].values())


def test_simplify_reaches_the_budget_and_records_both_counts() -> None:
    grid = _grid(50)
    assert len(grid.triangles) == 5000
    out, record = simplify_to(grid, 3000, cluster_simplify)
    assert len(out.triangles) <= 3000
    assert record["triangles_before"] == 5000
    assert record["parameters"]["simplifier"] == "cluster-stand-in/v1"


def test_the_written_colours_are_exactly_the_table_values_of_the_swatches() -> None:
    table, _ = colour.read_table(ROOT)
    palette = [[10, 10, 10], [200, 40, 40]]
    mesh, swatch, _ = flat_palette(_box((1.0, 1.0, 1.0)), palette)
    glb = write_glb(mesh, swatch, palette, table)
    magic, version, total = struct.unpack_from("<III", glb, 0)
    assert (magic, version, total) == (0x46546C67, 2, len(glb))
    json_length = struct.unpack_from("<I", glb, 12)[0]
    document = json.loads(glb[20 : 20 + json_length])
    accessor = document["accessors"][
        document["meshes"][0]["primitives"][0]["attributes"]["COLOR_0"]
    ]
    assert (accessor["type"], accessor["componentType"], accessor["normalized"]) == (
        "VEC4",
        5123,
        True,
    )
    view = document["bufferViews"][accessor["bufferView"]]
    binary = glb[20 + json_length + 8 :]
    values = np.frombuffer(
        binary, dtype="<u2", count=accessor["count"] * 4, offset=view["byteOffset"]
    ).reshape(-1, 4)
    red = (table[200], table[40], table[40], 65535)
    assert {tuple(int(x) for x in row) for row in values} == {red}
    assert "extensionsUsed" not in document and "images" not in document


def test_a_piece_over_budget_says_which_measure() -> None:
    table, _ = colour.read_table(ROOT)
    request = read_request(build_request(pack=PACK, variants=1, route="S", **BENCH))
    tight = dict(request, budget=dict(request["budget"], glb_bytes=100))
    piece = make_piece(
        _box((1.8, 0.6, 0.9)),
        up="+Z",
        front="-Y",
        request=tight,
        simplifier=cluster_simplify,
        table=table,
    )
    assert piece.verdict == {"over": ["glb_bytes"], "within": False}


def test_every_written_triangle_carries_one_swatch_at_all_three_corners() -> None:
    """The page refuses a triangle whose corners differ in colour; the writer never makes one."""
    table, _ = colour.read_table(ROOT)
    box = _box((1.0, 1.0, 1.0))
    # Half the corners red, half green: faces across the boundary average to either swatch.
    colours = box.colours.copy()
    colours[box.positions[:, 0] > 0.5] = (40, 160, 60)
    palette = [[200, 40, 40], [40, 160, 60]]
    mesh, swatch, _ = flat_palette(Mesh(box.positions, box.triangles, colours), palette)
    assert len(set(swatch.tolist())) == 2
    glb = write_glb(mesh, swatch, palette, table)
    json_length = struct.unpack_from("<I", glb, 12)[0]
    document = json.loads(glb[20 : 20 + json_length])
    binary = glb[20 + json_length + 8 :]
    primitive = document["meshes"][0]["primitives"][0]

    def read(index: int, dtype: str, width: int) -> np.ndarray:
        accessor = document["accessors"][index]
        view = document["bufferViews"][accessor["bufferView"]]
        count = accessor["count"] * width
        return np.frombuffer(binary, dtype=dtype, count=count, offset=view["byteOffset"])

    corner_colours = read(primitive["attributes"]["COLOR_0"], "<u2", 4).reshape(-1, 4)
    triangles = read(primitive["indices"], "<u2", 1).reshape(-1, 3)
    for a, b, c in triangles:
        assert (corner_colours[a] == corner_colours[b]).all()
        assert (corner_colours[b] == corner_colours[c]).all()
