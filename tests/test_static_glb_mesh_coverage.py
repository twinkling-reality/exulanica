"""Exact mesh-instance coverage, independently checked against simple analytic solids."""

import struct
from fractions import Fraction

import pytest
from exulanica.world.static_glb import StaticGlbRefused, static_mesh_instance_bounds

from static_glb_builder import Gltf, cube


def no_image(_: bytes) -> tuple[int, int]:
    raise AssertionError("unexpected image")


def test_parent_transform_nonuniform_scale_and_repeated_mesh_are_all_covered() -> None:
    g = cube()
    # A unit cube scaled to 2x3x4, turned 180 degrees around up, then translated.
    g.document["nodes"] = [
        {"children": [1, 2], "translation": [10, 20, 30], "rotation": [0, 1, 0, 0]},
        {"mesh": 0, "scale": [2, 3, 4]},
        {"mesh": 0, "translation": [5, 0, 0]},
    ]
    g.scene(0)
    facts = static_mesh_instance_bounds(g.build(), decode_image=no_image)
    assert [(m.node_index, m.mesh_index, m.minimum, m.maximum) for m in facts.instances] == [
        (1, 0, (9, 20, 28), (11, 23, 32)),
        (2, 0, (Fraction(9, 2), 20, Fraction(59, 2)), (Fraction(11, 2), 21, Fraction(61, 2))),
    ]
    assert facts.draw_calls == 2 and facts.rendered_triangles == 24


def test_nonindexed_triangles_and_unused_vertex_do_not_trust_accessor_bounds() -> None:
    g = Gltf()
    positions = g.positions([(0, 0, 0), (2, 0, 0), (0, 3, 0)])
    g.document["accessors"][positions]["max"] = [0, 0, 0]
    g.scene(g.node(mesh=g.mesh({"attributes": {"POSITION": positions}})))
    bounds = static_mesh_instance_bounds(g.build(), decode_image=no_image).instances[0]
    assert bounds.minimum == (0, 0, 0) and bounds.maximum == (2, 3, 0)
    # Indexed rendering excludes unused positions; declarations still cannot shrink the triangle.
    g.document["meshes"][0]["primitives"][0]["indices"] = g.indices([0, 1, 1])
    g.document["buffers"][0]["byteLength"] = len(g.binary)
    bounds = static_mesh_instance_bounds(g.build(), decode_image=no_image).instances[0]
    assert bounds.maximum == (2, 0, 0)


def test_out_of_range_indices_and_nonfinite_positions_refuse() -> None:
    g = cube()
    accessor = g.document["accessors"][1]
    view = g.document["bufferViews"][accessor["bufferView"]]
    struct.pack_into("<H", g.binary, view["byteOffset"], 99)
    with pytest.raises(StaticGlbRefused):
        static_mesh_instance_bounds(g.build(), decode_image=no_image)
    g = cube()
    struct.pack_into("<f", g.binary, 0, float("nan"))
    with pytest.raises(StaticGlbRefused):
        static_mesh_instance_bounds(g.build(), decode_image=no_image)
    g = cube()
    del g.document["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
    with pytest.raises(StaticGlbRefused):
        static_mesh_instance_bounds(g.build(), decode_image=no_image)


def test_matrix_transform_shears_actual_vertices_not_declared_box() -> None:
    g = Gltf()
    pos = g.positions([(0, 0, 0), (1, 1, 0), (-1, -1, 0)])
    # x'=x-y: all three triangle vertices have exactly x=0 despite their nonzero local box.
    node = g.node(
        mesh=g.mesh({"attributes": {"POSITION": pos}}),
        matrix=[1, 0, 0, 0, -1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
    )
    g.scene(node)
    result = static_mesh_instance_bounds(g.build(), decode_image=no_image).instances[0]
    assert result.minimum == (0, -1, 0) and result.maximum == (0, 1, 0)


def test_extreme_nested_transform_has_explicit_exact_arithmetic_bound() -> None:
    g = cube()
    g.document["nodes"] = [
        {"scale": [1e-200, 1e-200, 1e-200], "children": [i + 1]} for i in range(7)
    ] + [{"mesh": 0}]
    g.scene(0)
    with pytest.raises(StaticGlbRefused, match="arithmetic limit"):
        static_mesh_instance_bounds(g.build(), decode_image=no_image)


def test_json_integer_transforms_use_the_renderer_binary64_values() -> None:
    g = cube()
    g.document["nodes"] = [
        {"translation": [9007199254740993, 0, 0], "children": [1]},
        {"translation": [-9007199254740992, 0, 0], "mesh": 0},
    ]
    g.scene(0)
    facts = static_mesh_instance_bounds(g.build(), decode_image=no_image)
    # Both JSON integers round to +/-2**53 in JS. Their exact composed translation is zero.
    assert facts.instances[0].minimum == (Fraction(-1, 2), 0, Fraction(-1, 2))
    assert facts.instances[0].maximum == (Fraction(1, 2), 1, Fraction(1, 2))
