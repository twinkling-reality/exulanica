"""A skinned look's container, ``exulanica.skinned-glb/v1``: what the reader admits and refuses.

Every container here is written by a builder in this file from first principles (struct packing of
a binary glTF), never by the writer the job uses, so the reader is held to the profile and not to
another piece of its own code. One well-formed container is the positive control; each refusal
changes one thing about it.
"""

from __future__ import annotations

import dataclasses
import json
import struct
from typing import Any

import pytest
from exulanica.things.catalogs import MOTIONS as PLAN_MOTIONS
from exulanica_pieces.canonical import Refused
from exulanica_pieces.skinned import LIMITS, MOTIONS, read_skinned_glb


def _pack(document: dict[str, Any], binary: bytes) -> bytes:
    text = json.dumps(document, separators=(",", ":")).encode("ascii")
    text += b" " * (-len(text) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(text) + 8 + len(binary)
    return b"".join(
        (
            struct.pack("<III", 0x46546C67, 2, total),
            struct.pack("<II", len(text), 0x4E4F534A),
            text,
            struct.pack("<II", len(binary), 0x004E4942),
            binary,
        )
    )


class _Builder:
    """A three-joint chain (root, middle, tip) one metre apart up +Y, skinning one triangle."""

    def __init__(self) -> None:
        self.binary = bytearray()
        self.views: list[dict[str, Any]] = []
        self.accessors: list[dict[str, Any]] = []

    def add(
        self, fmt: str, values: list[tuple[Any, ...]], kind: str, component: int, **extra: Any
    ) -> int:
        while len(self.binary) % 4:
            self.binary.append(0)
        start = len(self.binary)
        for value in values:
            self.binary += struct.pack(f"<{fmt}", *value)
        self.views.append(
            {"buffer": 0, "byteOffset": start, "byteLength": len(self.binary) - start}
        )
        self.accessors.append(
            {
                "bufferView": len(self.views) - 1,
                "componentType": component,
                "count": len(values),
                "type": kind,
                **extra,
            }
        )
        return len(self.accessors) - 1

    def document(self) -> tuple[dict[str, Any], bytes]:
        positions = self.add(
            "3f", [(0.0, 0.0, 0.0), (0.2, 1.0, 0.0), (0.0, 2.0, 0.1)], "VEC3", 5126
        )
        colours = self.add("4H", [(65535, 0, 0, 65535)] * 3, "VEC4", 5123, normalized=True)
        joints = self.add("4B", [(0, 1, 0, 0), (1, 2, 0, 0), (2, 0, 0, 0)], "VEC4", 5121)
        weights = self.add(
            "4f", [(0.5, 0.5, 0.0, 0.0), (0.25, 0.75, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)], "VEC4", 5126
        )
        # Joints rest at y = 0, 1 and 2: each inverse bind matrix translates back by its height.
        binds = self.add(
            "16f",
            [(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -float(height), 0, 1) for height in (0, 1, 2)],
            "MAT4",
            5126,
        )
        document = {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0, 3]}],
            "nodes": [
                {"name": "bone:hips", "children": [1]},
                {"name": "bone:spine1", "translation": [0.0, 1.0, 0.0], "children": [2]},
                {"name": "bone:spine2", "translation": [0.0, 1.0, 0.0]},
                {"name": "mesh", "mesh": 0, "skin": 0},
            ],
            "skins": [{"joints": [0, 1, 2], "inverseBindMatrices": binds}],
            "meshes": [
                {
                    "primitives": [
                        {
                            "attributes": {
                                "POSITION": positions,
                                "COLOR_0": colours,
                                "JOINTS_0": joints,
                                "WEIGHTS_0": weights,
                            },
                            "material": 0,
                        }
                    ]
                }
            ],
            "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1]}}],
            "accessors": self.accessors,
            "bufferViews": self.views,
            "buffers": [{"byteLength": len(self.binary)}],
        }
        return document, bytes(self.binary)


def _container(change: Any = None) -> bytes:
    builder = _Builder()
    document, binary = builder.document()
    if change is not None:
        binary = change(document, binary) or binary
    document["buffers"] = [{"byteLength": len(binary)}]
    return _pack(document, binary)


def test_a_well_formed_skinned_container_is_read():
    read = read_skinned_glb(_container())
    assert read.joints == ("bone:hips", "bone:spine1", "bone:spine2")
    assert read.parents == {
        "bone:hips": None,
        "bone:spine1": "bone:hips",
        "bone:spine2": "bone:spine1",
    }
    assert read.rest_m["bone:spine2"] == pytest.approx((0.0, 2.0, 0.0))
    assert (read.vertices, read.triangles, read.primitives, read.materials) == (3, 1, 1, 1)
    bones = {"hips": "bone:hips", "spine1": "bone:spine1", "spine2": "bone:spine2"}
    read_skinned_glb(
        _container(), bones=bones, plan_parents={"hips": None, "spine1": "hips", "spine2": "spine1"}
    )


def test_the_clips_motions_are_the_body_plans():
    assert MOTIONS == PLAN_MOTIONS


def _set(path: list[Any], value: Any) -> Any:
    def change(document: dict[str, Any], _binary: bytes) -> None:
        target = document
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return change


@pytest.mark.parametrize(
    ("change", "words"),
    [
        (_set(["nodes", 0, "scale"], [0.7, 0.7, 0.7]), None),  # a scale on a joint is allowed ...
        (_set(["nodes", 3, "translation"], [1.0, 0.0, 0.0]), "no transform"),
        (_set(["skins", 0, "joints"], [0, 1, 1]), "each joint once"),
        (_set(["nodes", 1, "translation"], [0.0, 1.5, 0.0]), "not the inverse of its rest pose"),
        (_set(["nodes", 1, "matrix"], [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 0, 1]), "matrix"),
        (_set(["extensionsUsed"], ["KHR_materials_unlit"]), "extension"),
        (_set(["meshes", 0, "primitives", 0, "targets"], [{"POSITION": 0}]), "morph target"),
        (_set(["meshes", 0, "primitives", 0, "attributes", "JOINTS_1"], 2), "attributes beyond"),
        (_set(["meshes", 0, "primitives", 0, "mode"], 1), "triangles"),
        (_set(["materials"], [{}, {}, {}]), "materials"),
        (_set(["animations"], [{"name": "Idle_A", "channels": [], "samplers": []}]), "named once"),
    ],
)
def test_one_change_is_refused_by_the_rule_it_breaks(change, words):
    if words is None:
        # ... but then its inverse bind matrices must account for it, which these do not.
        with pytest.raises(Refused, match="not the inverse of its rest pose"):
            read_skinned_glb(_container(change))
        return
    with pytest.raises(Refused, match=words):
        read_skinned_glb(_container(change))


def test_a_scale_above_the_skeleton_is_refused_and_a_baked_one_is_not():
    def wrap(document: dict[str, Any], _binary: bytes) -> None:
        document["nodes"].append({"name": "scaled", "scale": [0.5, 0.5, 0.5], "children": [0]})
        document["scenes"][0]["nodes"] = [4, 3]

    with pytest.raises(Refused, match="not a joint"):
        read_skinned_glb(_container(wrap))


def test_weights_that_are_not_whole_or_name_no_joint_are_refused():
    def heavy(document: dict[str, Any], binary: bytes) -> bytes:
        # Raise the first vertex's first weight from 0.5 to 0.6: its four sum to 1.1.
        view = document["bufferViews"][document["accessors"][3]["bufferView"]]
        data = bytearray(binary)
        struct.pack_into("<f", data, view["byteOffset"], 0.6)
        return bytes(data)

    with pytest.raises(Refused, match="not whole"):
        read_skinned_glb(_container(heavy))

    def stray(document: dict[str, Any], binary: bytes) -> bytes:
        view = document["bufferViews"][document["accessors"][2]["bufferView"]]
        data = bytearray(binary)
        data[view["byteOffset"]] = 7
        return bytes(data)

    with pytest.raises(Refused, match="does not hold"):
        read_skinned_glb(_container(stray))


def test_a_clip_that_walks_the_root_across_the_ground_is_refused():
    def walking(document: dict[str, Any], binary: bytes) -> bytes:
        builder = _Builder()
        builder.binary = bytearray(binary)
        builder.views = document["bufferViews"]
        builder.accessors = document["accessors"]
        times = builder.add("1f", [(0.0,), (1.0,)], "SCALAR", 5126, min=[0.0], max=[1.0])
        moves = builder.add("3f", [(0.0, 0.0, 0.0), (0.0, 0.0, 0.5)], "VEC3", 5126)
        document["animations"] = [
            {
                "name": "walk",
                "samplers": [{"input": times, "output": moves}],
                "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
            }
        ]
        return bytes(builder.binary)

    with pytest.raises(Refused, match="across the ground"):
        read_skinned_glb(_container(walking))


def test_a_joint_tree_that_is_not_the_plan_s_is_refused():
    bones = {"hips": "bone:hips", "spine1": "bone:spine1", "spine2": "bone:spine2"}
    with pytest.raises(Refused, match="does not hang from"):
        read_skinned_glb(
            _container(),
            bones=bones,
            plan_parents={"hips": None, "spine1": "hips", "spine2": "hips"},
        )


def test_a_look_s_whole_rig_is_not_a_bone_map():
    parents = {"hips": None, "spine1": "hips", "spine2": "spine1"}
    rig = {"bones": {"hips": "bone:hips"}, "clips": {}, "sockets": {}}
    with pytest.raises(TypeError, match=r"rig\.bones"):
        read_skinned_glb(_container(), bones=rig, plan_parents=parents)
    with pytest.raises(TypeError, match="together"):
        read_skinned_glb(_container(), bones={"hips": "bone:hips"})


def test_the_bounds_are_the_profile_s():
    assert (LIMITS.joints, LIMITS.triangles, LIMITS.primitives, LIMITS.materials) == (
        128,
        20_000,
        16,
        2,
    )
    assert LIMITS.image_side_px == 1024
    with pytest.raises(Refused, match="joints"):
        read_skinned_glb(_container(), limits=dataclasses.replace(LIMITS, joints=2))


def _textured(*, component: int = 5126) -> tuple[dict[str, Any], bytes]:
    """The independent three-joint fixture with a real embedded one-pixel PNG and UVs."""
    import base64

    builder = _Builder()
    document, _ = builder.document()
    if component == 5126:
        uv = builder.add("2f", [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)], "VEC2", component)
    else:
        uv = builder.add("2H", [(0, 0), (65535, 0), (0, 65535)], "VEC2", component, normalized=True)
    attrs = document["meshes"][0]["primitives"][0]["attributes"]
    del attrs["COLOR_0"]
    attrs["TEXCOORD_0"] = uv
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVioAAAAASUVORK5CYII="
    )
    builder.views.append({"buffer": 0, "byteOffset": len(builder.binary), "byteLength": len(png)})
    builder.binary.extend(png)
    document["images"] = [{"bufferView": len(builder.views) - 1, "mimeType": "image/png"}]
    document["textures"] = [{"source": 0, "sampler": 0}]
    document["samplers"] = [{"magFilter": 9729, "minFilter": 9729}]
    document["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
    document["buffers"][0]["byteLength"] = len(builder.binary)
    return document, bytes(builder.binary)


@pytest.mark.parametrize("component", [5126, 5123])
def test_base_colour_texture_with_float_or_normalized_uvs_is_read(component):
    document, binary = _textured(component=component)
    payload = _pack(document, binary)
    read = read_skinned_glb(payload)
    assert read.image_px == (1, 1)
    assert read.vertices == 3 and read.materials == 1


@pytest.mark.parametrize(
    "path",
    [
        ["normalTexture"],
        ["occlusionTexture"],
        ["emissiveTexture"],
        ["pbrMetallicRoughness", "metallicRoughnessTexture"],
    ],
)
def test_v1_refuses_maps_beyond_base_colour_even_when_the_texture_exists(path):
    document, binary = _textured()
    target = document["materials"][0]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = {"index": 0}
    with pytest.raises(Refused, match="other than the one base colour"):
        read_skinned_glb(_pack(document, binary))


def test_dangling_normal_map_from_audit_is_not_admitted_as_v1():
    payload = _container(_set(["materials", 0, "normalTexture"], {"index": 999}))
    with pytest.raises(Refused, match="other than the one base colour"):
        read_skinned_glb(payload)


@pytest.mark.parametrize(
    ("path", "value", "words"),
    [
        (["materials", 0, "pbrMetallicRoughness", "baseColorTexture"], None, "is an object"),
        (["materials", 0, "pbrMetallicRoughness", "baseColorTexture", "index"], 1, "index names"),
        (
            ["materials", 0, "pbrMetallicRoughness", "baseColorTexture", "index"],
            True,
            "index names",
        ),
        (
            ["materials", 0, "pbrMetallicRoughness", "baseColorTexture", "texCoord"],
            1,
            "TEXCOORD_0 only",
        ),
        (["textures", 0, "source"], 1, "source names"),
        (["textures", 0, "sampler"], 1, "sampler names"),
        (["images", 0, "bufferView"], 999, "bufferView names"),
        (
            ["materials", 0, "pbrMetallicRoughness", "baseColorTexture", "extensions"],
            {"KHR_texture_transform": {"texCoord": 1}},
            "extension",
        ),
    ],
)
def test_texture_reference_chain_and_uv_set_are_checked(path, value, words):
    document, binary = _textured()
    _set(path, value)(document, binary)
    with pytest.raises(Refused, match=words):
        read_skinned_glb(_pack(document, binary))


def test_uvs_alone_are_not_colour_and_textured_vertex_colours_do_not_replace_uvs():
    document, binary = _textured()
    del document["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]
    with pytest.raises(Refused, match="vertex colours or a material"):
        read_skinned_glb(_pack(document, binary))
    document, binary = _textured()
    attrs = document["meshes"][0]["primitives"][0]["attributes"]
    attrs["COLOR_0"] = 1
    del attrs["TEXCOORD_0"]
    with pytest.raises(Refused, match="requires TEXCOORD_0"):
        read_skinned_glb(_pack(document, binary))


@pytest.mark.parametrize(
    ("key", "value", "words"),
    [
        ("type", "VEC3", "is VEC2"),
        ("componentType", 5125, "float or normalized"),
        ("normalized", True, "float or normalized"),
        ("count", 2, "for every vertex"),
    ],
)
def test_uv_accessor_shape_encoding_and_vertex_count_are_checked(key, value, words):
    document, binary = _textured()
    uv = document["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"]
    document["accessors"][uv][key] = value
    with pytest.raises(Refused, match=words):
        read_skinned_glb(_pack(document, binary))


def test_uv_coordinates_must_be_finite():
    document, binary = _textured()
    uv = document["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"]
    view = document["bufferViews"][document["accessors"][uv]["bufferView"]]
    altered = bytearray(binary)
    struct.pack_into("<f", altered, view["byteOffset"], float("nan"))
    with pytest.raises(Refused, match="finite coordinates"):
        read_skinned_glb(_pack(document, bytes(altered)))
