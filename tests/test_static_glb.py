"""The static GLB profile: what admission refuses, and what preparation validates, measures and
transforms. Pure: no database and no store. Every container is built in code."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from collections.abc import Callable
from typing import Any

import pytest
from exulanica.canonical import canonical_json
from exulanica.corpus.decode import open_sensor
from exulanica.world.static_glb import (
    CONTENT_REASONS,
    GENERATOR,
    LIMITS,
    PLACEABLE_OBJECT_PROFILE,
    PreparedGlb,
    StaticGlbRefused,
    inspect_static_glb,
    prepare_static_glb,
)

from static_glb_builder import CUBE_CORNERS, CUBE_TRIANGLES, FLOAT, Gltf, cube, jpeg, pack, png


def decode(data: bytes) -> tuple[int, int]:
    with open_sensor(data) as image:
        return image.size


def prepare(
    payload: bytes, unit: str = "metre", expected: dict[str, int] | None = None
) -> PreparedGlb:
    return prepare_static_glb(
        payload, unit=unit, expected_dimensions_mm=expected, decode_image=decode
    )


def chunks(payload: bytes) -> tuple[dict[str, Any], bytes]:
    json_length = struct.unpack_from("<I", payload, 12)[0]
    document = json.loads(payload[20 : 20 + json_length])
    rest = payload[20 + json_length :]
    binary = rest[8 : 8 + struct.unpack_from("<I", rest)[0]] if rest else b""
    return document, binary


def refused(payload: bytes, reason: str, *, stage: Callable[[bytes], object] | None = None) -> str:
    with pytest.raises(StaticGlbRefused) as caught:
        (stage or inspect_static_glb)(payload)
    assert caught.value.reason == reason, str(caught.value)
    return str(caught.value)


# -- a plain object ------------------------------------------------------------------------------


def test_a_cube_in_metres_is_admitted_and_prepared_standing_on_its_origin() -> None:
    payload = cube(offset=(3.0, 2.0, -1.0), extras=True).build()
    inspected = inspect_static_glb(payload)
    assert inspected.counts["rendered_triangles"] == 12
    assert inspected.counts["draw_calls"] == 1

    prepared = prepare(payload)
    assert prepared.dimensions_mm == {"width": 1000, "height": 1000, "depth": 1000}
    assert prepared.footprint_half_extents_mm == (500, 500)
    assert prepared.placeable
    assert [(step["step"], step["kind"]) for step in prepared.steps] == [
        ("container", "validate"),
        ("data", "validate"),
        ("images", "validate"),
        ("measure", "measure"),
        ("normalize", "transform"),
        ("output", "validate"),
    ]
    # Only the normalize step changes bytes, and only the JSON chunk: the binary chunk is copied.
    before, before_binary = chunks(payload)
    after, after_binary = chunks(prepared.output)
    assert after_binary == before_binary
    assert after["asset"] == {"generator": GENERATOR, "version": "2.0"}
    assert "extras" not in json.dumps(after)
    normalize = prepared.steps[4]
    assert normalize["extras_removed"] == 2
    assert normalize["generator_replaced"] == "exulanica tests"
    root = after["nodes"][after["scenes"][0]["nodes"][0]]
    assert root["children"] == before["scenes"][0]["nodes"]
    assert root["scale"] == [1.0, 1.0, 1.0]
    assert root["translation"] == [-3.0, -2.0, 1.0]
    # The receipt facts are canonical: integers and text, never a float.
    canonical_json(list(prepared.steps))
    assert prepared.output_sha256 == hashlib.sha256(prepared.output).hexdigest()


def test_preparation_is_deterministic_and_pinned_to_its_version() -> None:
    first = prepare(cube(texture=png(4, 4)).build())
    second = prepare(cube(texture=png(4, 4)).build())
    assert first.output == second.output
    # The golden digest of this exact fixture under preparer version 1. A change that moves it is
    # a new PREPARER_VERSION, never a new digest under the same version.
    assert first.output_sha256 == GOLDEN_TEXTURED_CUBE


GOLDEN_TEXTURED_CUBE = "3561b2d3916458883ccb406a6a8efec3018e2e23e89a5f519a443c3254a52467"


@pytest.mark.parametrize(
    ("unit", "side_mm", "placeable"),
    [("metre", 1000, True), ("centimetre", 10, True), ("millimetre", 1, False)],
)
def test_the_declared_unit_scales_the_object_into_metres(
    unit: str, side_mm: int, placeable: bool
) -> None:
    prepared = prepare(cube().build(), unit)
    assert prepared.dimensions_mm == {"width": side_mm, "height": side_mm, "depth": side_mm}
    assert prepared.placeable is placeable
    after, _ = chunks(prepared.output)
    root = after["nodes"][after["scenes"][0]["nodes"][0]]
    assert root["scale"] == [float(side_mm) / 1000] * 3
    if not placeable:
        assert prepared.compatibility[0].document() == {
            "profile": PLACEABLE_OBJECT_PROFILE,
            "state": "incompatible",
            "code": "dimensions_out_of_bounds",
        }


def test_declared_dimensions_are_checked_against_the_measurement() -> None:
    payload = cube(scale=2.0).build()
    assert prepare(payload, expected={"width": 2050, "height": 1960, "depth": 2000}).placeable
    message = refused(
        payload,
        "dimensions_disagree",
        stage=lambda data: prepare(data, expected={"width": 20, "height": 20, "depth": 20}),
    )
    assert "2000 mm" in message


def test_a_turned_node_is_measured_vertex_by_vertex() -> None:
    # A quarter turn about +y maps x onto -z: a 2 x 1 x 4 box becomes 4 x 1 x 2.
    gltf = Gltf()
    points = [(x * 2.0, y, z * 4.0) for x, y, z in CUBE_CORNERS]
    mesh = gltf.mesh(
        {
            "attributes": {"POSITION": gltf.positions(points)},
            "indices": gltf.indices(CUBE_TRIANGLES),
        }
    )
    half = math.sqrt(0.5)
    gltf.scene(gltf.node(mesh=mesh, rotation=[0.0, half, 0.0, half]))
    prepared = prepare(gltf.build())
    assert prepared.dimensions_mm == {"width": 4000, "height": 1000, "depth": 2000}


def test_instancing_is_counted_and_measured() -> None:
    gltf = Gltf()
    mesh = gltf.mesh(
        {
            "attributes": {"POSITION": gltf.positions(CUBE_CORNERS)},
            "indices": gltf.indices(CUBE_TRIANGLES),
        }
    )
    left = gltf.node(mesh=mesh, translation=[-2.0, 0.0, 0.0])
    right = gltf.node(mesh=mesh, translation=[2.0, 0.0, 0.0])
    gltf.scene(gltf.node(children=[left, right]))
    inspected = inspect_static_glb(gltf.build())
    assert inspected.counts["draw_calls"] == 2
    assert inspected.counts["rendered_triangles"] == 24
    assert prepare(gltf.build()).dimensions_mm == {"width": 5000, "height": 1000, "depth": 1000}


def test_position_bounds_are_rewritten_exactly() -> None:
    gltf = cube()
    gltf.document["accessors"][0]["min"] = [-9.0, -9.0, -9.0]
    gltf.document["accessors"][0]["max"] = [9.0, 9.0, 9.0]
    prepared = prepare(gltf.build())
    after, _ = chunks(prepared.output)
    assert after["accessors"][0]["min"] == [-0.5, 0.0, -0.5]
    assert after["accessors"][0]["max"] == [0.5, 1.0, 0.5]
    assert prepared.steps[4]["position_bounds_rewritten"] == 1


@pytest.mark.parametrize("media_type", ["image/png", "image/jpeg"])
def test_embedded_images_are_decoded_and_sized(media_type: str) -> None:
    data = png(8, 4) if media_type == "image/png" else jpeg(8, 4)
    prepared = prepare(cube(texture=data, texture_media_type=media_type).build())
    assert prepared.steps[2]["decoded"] == [
        {"image": 0, "media_type": media_type, "width_px": 8, "height_px": 4}
    ]


# -- refusals at admission -----------------------------------------------------------------------


def test_every_refusal_names_a_declared_reason() -> None:
    with pytest.raises(ValueError):
        StaticGlbRefused("not_a_reason", "x")
    assert "malformed_container" in CONTENT_REASONS


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"not a container at all!!", "malformed_container"),
        (b"glTF" + b"\x00" * 16, "malformed_container"),
        (pack({}, json_bytes=b"{not json"), "malformed_container"),
        (pack({}, json_bytes=b'{"asset": {"version": "2.0"}, "asset": {}}'), "malformed_container"),
        (pack({}, json_bytes=b'{"asset": {"version": "2.0"}, "x": NaN}'), "malformed_container"),
        (pack({}, json_bytes=b"\xef\xbb\xbf{}"), "malformed_container"),
        (pack({}, json_bytes=b"[1, 2]"), "malformed_container"),
        (pack({"asset": {"version": "1.0"}}), "malformed_container"),
    ],
)
def test_a_container_that_is_not_one_is_malformed(payload: bytes, reason: str) -> None:
    refused(payload, reason)


def test_a_container_over_the_byte_ceiling_is_refused_before_it_is_read() -> None:
    refused(b"\x00" * (32 * 1024 * 1024 + 4), "resource_limit_exceeded")


def _with(document_change: Callable[[dict[str, Any]], None], gltf: Gltf | None = None) -> bytes:
    gltf = gltf or cube(texture=png(2, 2))
    gltf.document.setdefault("buffers", [{"byteLength": len(gltf.binary)}])
    document_change(gltf.document)
    return gltf.build()


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda d: d.update(extensionsRequired=["KHR_materials_variants"]), "required_extension"),
        (lambda d: d.update(extensionsUsed=["KHR_draco_mesh_compression"]), "compressed_content"),
        (lambda d: d.update(extensionsUsed=["EXT_meshopt_compression"]), "compressed_content"),
        (lambda d: d.update(extensionsUsed=["KHR_texture_basisu"]), "compressed_content"),
        (
            lambda d: d.update(extensionsRequired=["KHR_draco_mesh_compression"]),
            "compressed_content",
        ),
        (
            lambda d: d.update(extensionsUsed=["KHR_materials_emissive_strength"]),
            "extension_not_admitted",
        ),
        (lambda d: d["materials"][0].update(extensions={"KHR_x": {}}), "extension_not_admitted"),
        (
            lambda d: d["buffers"][0].update(uri="https://example.invalid/bench.bin"),
            "external_reference",
        ),
        (lambda d: d["images"][0].update(uri="data:image/png;base64,AAAA"), "external_reference"),
        (lambda d: d.update(animations=[{"channels": [], "samplers": []}]), "not_static"),
        (lambda d: d.update(skins=[{"joints": [0]}]), "not_static"),
        (lambda d: d["nodes"][0].update(skin=0), "not_static"),
        (lambda d: d["meshes"][0]["primitives"][0].update(targets=[{"POSITION": 0}]), "not_static"),
        (lambda d: d["meshes"][0]["primitives"][0]["attributes"].update(JOINTS_0=0), "not_static"),
        (lambda d: d.update(cameras=[{"type": "perspective"}]), "unsupported_feature"),
        (lambda d: d["nodes"][0].update(camera=0), "unsupported_feature"),
        (lambda d: d["accessors"][0].update(sparse={"count": 1}), "unsupported_feature"),
        (lambda d: d["meshes"][0]["primitives"][0].update(mode=1), "unsupported_feature"),
        (
            lambda d: d["meshes"][0]["primitives"][0]["attributes"].update(_CUSTOM=0),
            "unsupported_feature",
        ),
        (lambda d: d.update(scenes=[{"nodes": [0]}, {"nodes": [0]}]), "unsupported_feature"),
        (lambda d: d["images"][0].update(mimeType="image/webp"), "unsupported_feature"),
        (lambda d: d.update(lights=[]), "unsupported_feature"),
        (lambda d: d["nodes"][0].update(children=[0]), "malformed_container"),
        (lambda d: d["accessors"][0].update(count=10_000), "malformed_container"),
        (lambda d: d["accessors"][0].update(byteOffset=2), "malformed_container"),
        (lambda d: d["bufferViews"][0].update(byteLength=10**9), "malformed_container"),
        (
            lambda d: d["meshes"][0]["primitives"][0]["attributes"].pop("POSITION"),
            "malformed_container",
        ),
        (lambda d: d["images"][0].update(mimeType="image/jpeg"), "invalid_image"),
        (lambda d: d.pop("scenes"), "invalid_geometry"),
    ],
)
def test_the_static_profile_refuses_by_name(
    change: Callable[[dict[str, Any]], None], reason: str
) -> None:
    refused(_with(change), reason)


def test_a_node_hierarchy_with_two_parents_or_too_deep_is_refused() -> None:
    gltf = cube()
    mesh_node = 0
    a = gltf.node(children=[mesh_node])
    b = gltf.node(children=[mesh_node])
    gltf.scene(a, b)
    refused(gltf.build(), "malformed_container")

    deep = cube()
    child = 0
    for _ in range(LIMITS.scene_depth):
        child = deep.node(children=[child])
    deep.scene(child)
    refused(deep.build(), "resource_limit_exceeded")


def test_instancing_that_multiplies_triangles_past_the_bound_is_refused() -> None:
    # Three vertices and 300,000 indices are 600 KB; eleven nodes drawing that one mesh draw
    # 1,100,000 triangles, past the bound, from bytes far inside the byte ceiling.
    gltf = Gltf()
    positions = gltf.positions([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
    indices = gltf.indices([0, 1, 2] * 100_000)
    mesh = gltf.mesh({"attributes": {"POSITION": positions}, "indices": indices})
    nodes = [gltf.node(mesh=mesh, translation=[float(n), 0.0, 0.0]) for n in range(11)]
    gltf.scene(gltf.node(children=nodes))
    message = refused(gltf.build(), "resource_limit_exceeded")
    assert "triangles" in message


def test_image_headers_are_bounded_before_any_decode() -> None:
    too_wide = bytearray(png(2, 2))
    too_wide[16:24] = struct.pack(">II", 8192, 2)
    refused(cube(texture=bytes(too_wide)).build(), "resource_limit_exceeded")

    gltf = cube(texture=png(2, 2))
    big = bytearray(png(2, 2))
    big[16:24] = struct.pack(">II", 2048, 2048)
    for _ in range(4):
        gltf.image(bytes(big), "image/png")
    message = refused(gltf.build(), "resource_limit_exceeded")
    assert "texels" in message


def test_a_draw_call_flood_is_refused() -> None:
    gltf = Gltf()
    positions = gltf.positions(CUBE_CORNERS)
    indices = gltf.indices(CUBE_TRIANGLES)
    mesh = gltf.mesh(
        *({"attributes": {"POSITION": positions}, "indices": indices} for _ in range(2))
    )
    nodes = [gltf.node(mesh=mesh) for _ in range(LIMITS.draw_calls // 2 + 1)]
    gltf.scene(gltf.node(children=nodes))
    assert "draw calls" in refused(gltf.build(), "resource_limit_exceeded")


# -- refusals in preparation ---------------------------------------------------------------------


def test_an_index_past_the_vertices_fails_preparation_not_admission() -> None:
    gltf = Gltf()
    positions = gltf.positions(CUBE_CORNERS)
    mesh = gltf.mesh({"attributes": {"POSITION": positions}, "indices": gltf.indices([0, 1, 99])})
    gltf.scene(gltf.node(mesh=mesh))
    payload = gltf.build()
    inspect_static_glb(payload)
    refused(payload, "invalid_geometry", stage=prepare)


def test_a_non_finite_position_fails_preparation() -> None:
    gltf = Gltf()
    points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (math.nan, 1.0, 0.0)]
    mesh = gltf.mesh({"attributes": {"POSITION": gltf.positions(points, bounds=False)}})
    gltf.document["accessors"][0]["min"] = [0.0, 0.0, 0.0]
    gltf.document["accessors"][0]["max"] = [1.0, 1.0, 0.0]
    gltf.scene(gltf.node(mesh=mesh))
    refused(gltf.build(), "invalid_geometry", stage=prepare)


def test_an_image_whose_header_lies_fails_preparation() -> None:
    lying = bytearray(png(2, 2))
    lying[16:24] = struct.pack(">II", 4, 4)
    lying[29:33] = struct.pack(">I", 0)  # the header CRC no longer matches either
    payload = cube(texture=bytes(lying)).build()
    inspect_static_glb(payload)
    refused(payload, "invalid_image", stage=prepare)


def test_a_non_triangle_count_is_invalid_geometry() -> None:
    gltf = Gltf()
    mesh = gltf.mesh({"attributes": {"POSITION": gltf.positions(CUBE_CORNERS[:4])}})
    gltf.scene(gltf.node(mesh=mesh))
    refused(gltf.build(), "invalid_geometry")


def test_strided_positions_are_read_through_their_stride() -> None:
    gltf = Gltf()
    data = b"".join(struct.pack("<3f", *point) + b"\x00" * 4 for point in CUBE_CORNERS)
    view = gltf.view(data, target=34962, stride=16)
    positions = gltf.accessor(view, FLOAT, "VEC3", 8, min=[-0.5, 0.0, -0.5], max=[0.5, 1.0, 0.5])
    mesh = gltf.mesh(
        {"attributes": {"POSITION": positions}, "indices": gltf.indices(CUBE_TRIANGLES)}
    )
    gltf.scene(gltf.node(mesh=mesh))
    assert prepare(gltf.build()).dimensions_mm == {"width": 1000, "height": 1000, "depth": 1000}
