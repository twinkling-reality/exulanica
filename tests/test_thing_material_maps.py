"""Embedded material inputs survive static admission with aligned authored UV/tangent frames."""

from __future__ import annotations

import copy
import hashlib
import json
import struct
import zlib
from dataclasses import replace
from pathlib import Path

import pytest
from exulanica.things.material_maps import (
    IMAGE_SIDE_MAX,
    IMAGES_MAX,
    TEXELS_MAX,
    MaterialMaps,
    PngMap,
)
from exulanica.things.pieces import MeshPart, Node, write_container
from exulanica.world.static_glb import LIMITS, inspect_static_glb
from exulanica.world.thing_store import read_admission


def png(colour=(128, 128, 255), *, width=2, height=2, pixels=None):
    """Original deterministic RGB image, including real PNG compression and checksums."""

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6 if len(colour) == 4 else 2, 0, 0, 0)
    rows = pixels if pixels is not None else (b"\0" + bytes(colour) * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def patch(**changes):
    return replace(
        MeshPart(
            "material-patch",
            ((0, 0, 0), (1000, 0, 0), (1000, 1000, 0), (0, 1000, 0)),
            ((0, 1, 2), (0, 2, 3)),
            "#ffffff",
            normals=((0, 0, 1),) * 4,
            uvs=((0, 0), (1, 0), (1, 1), (0, 1)),
            tangents=((1, 0, 0, 1),) * 4,
            maps=MaterialMaps(
                PngMap(png((220, 180, 120))), PngMap(png()), PngMap(png((0, 180, 64)))
            ),
            roughness_permille=1000,
            metallic_permille=1000,
        ),
        **changes,
    )


def document(payload):
    size = struct.unpack_from("<I", payload, 12)[0]
    return json.loads(payload[20 : 20 + size]), payload[28 + size :]


def look_document(payload):
    template = (
        Path(__file__).resolve().parents[1] / "assets/catalogs/things/looks/cafe-table.v1.json"
    )
    result = copy.deepcopy(json.loads(template.read_text()))
    result.update(look="original-material-patch", label="original embedded material patch")
    result["container"].update(sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))
    result["origin"]["licence"]["licence_text_sha256"] = None
    result["origin"]["lineage"]["ingredients"] = [result["container"]["sha256"]]
    return result


def test_embedded_maps_pass_existing_static_reader_and_real_look_admission():
    mesh = patch()
    payload = write_container([Node("surface", (0, 0, 0), (mesh,))])
    inspected = inspect_static_glb(payload)
    assert inspected.counts["images"] == 3 and inspected.counts["texels"] == 12
    admitted = read_admission(look_document(payload), payload)
    assert admitted.container_profile == "exulanica.static-glb/v1"
    assert admitted.report["counts"]["images"] == 3
    gltf, binary = document(payload)
    material = gltf["materials"][0]
    for image, field, holder in (
        (mesh.maps.base_colour, "baseColorTexture", material["pbrMetallicRoughness"]),
        (mesh.maps.normal, "normalTexture", material),
        (
            mesh.maps.metallic_roughness,
            "metallicRoughnessTexture",
            material["pbrMetallicRoughness"],
        ),
    ):
        reference = holder[field]
        embedded = gltf["images"][gltf["textures"][reference["index"]]["source"]]
        view = gltf["bufferViews"][embedded["bufferView"]]
        assert reference["texCoord"] == 0
        assert "target" not in view and "uri" not in embedded
        assert binary[view["byteOffset"] : view["byteOffset"] + view["byteLength"]] == image.data
    attributes = gltf["meshes"][0]["primitives"][0]["attributes"]
    tangent = gltf["accessors"][attributes["TANGENT"]]
    view = gltf["bufferViews"][tangent["bufferView"]]
    assert struct.unpack_from("<4f", binary, view["byteOffset"]) == (-1, 0, 0, 1)
    assert tangent["count"] == 4


def test_flat_faces_expand_uvs_with_corners_and_same_images_are_embedded_once():
    mesh = patch(normals=None, tangents=None, maps=MaterialMaps(base_colour=PngMap(png())))
    payload = write_container([Node("surface", (0, 0, 0), (mesh, replace(mesh, name="second")))])
    gltf, binary = document(payload)
    attributes = gltf["meshes"][0]["primitives"][0]["attributes"]
    uv = gltf["accessors"][attributes["TEXCOORD_0"]]
    view = gltf["bufferViews"][uv["bufferView"]]
    assert uv["count"] == 6
    assert struct.unpack_from("<12f", binary, view["byteOffset"]) == (
        0,
        0,
        1,
        0,
        1,
        1,
        0,
        0,
        1,
        1,
        0,
        1,
    )
    assert len(gltf["images"]) == len(gltf["materials"]) == 1
    inspect_static_glb(payload)


def test_rgba_and_mirrored_uv_handedness_survive_the_frame_rotation():
    image = PngMap(png((128, 128, 255, 255)))
    mesh = patch(
        maps=MaterialMaps(normal=image),
        uvs=((0, 1), (1, 1), (1, 0), (0, 0)),
        tangents=((1, 0, 0, -1),) * 4,
    )
    payload = write_container([Node("surface", (0, 0, 0), (mesh,))])
    gltf, binary = document(payload)
    attributes = gltf["meshes"][0]["primitives"][0]["attributes"]
    accessor = gltf["accessors"][attributes["TANGENT"]]
    view = gltf["bufferViews"][accessor["bufferView"]]
    assert struct.unpack_from("<4f", binary, view["byteOffset"]) == (-1, 0, 0, -1)
    inspect_static_glb(payload)


@pytest.mark.parametrize(
    "change",
    [
        {"uvs": None},
        {"uvs": ((0, 0),)},
        {"uvs": ((float("nan"), 0),) * 4},
        {"uvs": ((1.1, 0),) * 4},
        {"uvs": ((True, 0),) * 4},
        {"tangents": None},
        {"tangents": ((1, 0, 0, 1),)},
        {"tangents": ((0, 0, 1, 1),) * 4},
        {"tangents": ((2, 0, 0, 1),) * 4},
        {"tangents": ((1, 0, 0, 0),) * 4},
        {"tangents": ((1, 0, 0, True),) * 4},
        {"uvs": ((0.5, 0.5), (0.5 + 1e-9, 0.5), (0.5, 0.5 + 1e-9), (0, 1))},
    ],
)
def test_missing_or_invalid_coordinate_and_tangent_frames_refuse(change):
    with pytest.raises(ValueError, match=r"UV|tangent|normal map"):
        patch(**change)


@pytest.mark.parametrize(
    "data",
    [
        b"https://example.invalid/texture.png",
        png()[:-1],
        png() + b"trailing",
        png()[:-8] + b"bad-crc!",
        png(pixels=b"\0short"),
        png(pixels=(b"\5" + bytes(6)) * 2),
        png(width=4097, height=1),
    ],
)
def test_png_bytes_are_checked_beyond_the_header(data):
    with pytest.raises(ValueError, match="PNG"):
        PngMap(data)


def test_image_and_aggregate_texel_budgets_match_existing_admission():
    assert (
        LIMITS.texture_side_px,
        LIMITS.images,
        LIMITS.texels,
    ) == (IMAGE_SIDE_MAX, IMAGES_MAX, TEXELS_MAX)
    large = PngMap(png(width=4096, height=4096))
    with pytest.raises(ValueError, match="texel budget"):
        write_container(
            [Node("surface", (0, 0, 0), (patch(maps=MaterialMaps(large, PngMap(png()))),))]
        )
    parts = tuple(
        patch(name=f"map{i}", maps=MaterialMaps(base_colour=PngMap(png((i, 0, 0)))))
        for i in range(33)
    )
    with pytest.raises(ValueError, match="image budget"):
        write_container([Node("surface", (0, 0, 0), parts)])
