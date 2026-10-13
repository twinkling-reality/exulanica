"""Rounded authored mesh shading preserves the historical flat container path."""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import replace

import pytest
from exulanica.things.pieces import MeshPart, Node, write_container
from exulanica.world.static_glb import inspect_static_glb

VERTICES = ((0, 0, 0), (100, 0, 0), (0, 100, 0), (0, 0, 100))
TRIANGLES = ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3))


def _mesh(**kwargs) -> MeshPart:
    return MeshPart("surface", VERTICES, TRIANGLES, "#eeeedb", **kwargs)


def _document(payload):
    size = struct.unpack_from("<I", payload, 12)[0]
    return json.loads(payload[20 : 20 + size]), payload[28 + size :]


def test_absent_normals_keep_the_historical_flat_bytes():
    # Digest measured from the pre-change writer on this identical declaration.
    payload = write_container([Node("bone:hips", (0, 0, 0), (_mesh(),))])
    assert (
        hashlib.sha256(payload).hexdigest()
        == "86fe847b2d94cebbf92efc7d59ecd8fdff8669ed36a43edcb6a09fcfd56154df"
    )
    inspect_static_glb(payload)


def test_smooth_normals_are_indexed_in_the_same_rotated_frame_and_materials_are_bounded():
    normals = ((0.0, 0.0, 1.0),) * 4
    payload = write_container(
        [
            Node(
                "bone:hips",
                (0, 0, 0),
                (_mesh(normals=normals, roughness_permille=260, metallic_permille=100),),
            )
        ]
    )
    gltf, binary = _document(payload)
    primitive = gltf["meshes"][0]["primitives"][0]
    accessor = gltf["accessors"][primitive["attributes"]["NORMAL"]]
    view = gltf["bufferViews"][accessor["bufferView"]]
    assert accessor["count"] == 4
    values = struct.unpack_from("<12f", binary, view["byteOffset"])
    assert values == (0.0, 1.0, 0.0) * 4
    material = gltf["materials"][0]["pbrMetallicRoughness"]
    assert material["roughnessFactor"] == 0.26
    assert material["metallicFactor"] == 0.1
    inspect_static_glb(payload)


@pytest.mark.parametrize(
    "normals",
    [
        ((0, 0, 1),),
        ((0, 0, 0),) * 4,
        ((0, 0, 2),) * 4,
        ((0, float("nan"), 1),) * 4,
        ((True, 0, 0),) * 4,
    ],
)
def test_invalid_normals_refuse_before_writing(normals):
    with pytest.raises(ValueError, match="normal"):
        _mesh(normals=normals)


def test_zero_area_triangle_refuses_with_smooth_normals_too():
    mesh = replace(
        _mesh(normals=((0, 0, 1),) * 4), vertices_mm=((0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0))
    )
    with pytest.raises(ValueError, match="no area"):
        write_container([Node("bone:hips", (0, 0, 0), (mesh,))])


@pytest.mark.parametrize("factor", [-1, 1001, True, 0.5])
def test_material_factor_requires_whole_bounded_thousandths(factor):
    with pytest.raises(ValueError, match="material"):
        _mesh(roughness_permille=factor)
