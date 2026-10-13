"""Closed source syntax, whole-instance accounting and final-transform collision coverage."""

import copy
import hashlib
from dataclasses import replace
from typing import Any

import pytest
from exulanica.world.asset_preparation import decode_texture
from exulanica.world.terrain_dressing import (
    COLLISION,
    FRAME,
    PROFILE,
    DressingCoverage,
    TerrainDressingInvalid,
    compile_terrain_dressing,
    read_terrain_dressing,
)

from static_glb_builder import cube, png


def wire(payload: bytes, count: int = 1) -> dict[str, Any]:
    return {
        "profile": PROFILE,
        "frame": FRAME,
        "collision": COLLISION,
        "instances": [
            {
                "instance_id": f"part{i}",
                "source": {
                    "kind": "reviewed_component",
                    "asset_key": "test.cube",
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                },
                "position_mm": [100, 200, 300],
                "quarter_turns": 1,
                "scale_per_mille": 1500,
            }
            for i in range(count)
        ],
    }


def compile_(raw: dict[str, Any], payload: bytes) -> DressingCoverage:
    return compile_terrain_dressing(
        read_terrain_dressing(raw), {"test.cube": payload}, decode_image=decode_texture
    )


def test_outer_quarter_turn_and_fractional_mm_round_only_after_transform() -> None:
    payload = cube(offset=(1, 0, 2), node={"translation": [0.00025, 0, 0]}).build()
    result = compile_(wire(payload), payload)
    assert result.obstructions[0].bounds_mm == (2349, 199, -1951, 3851, 1701, -449)
    result.require_contact(result.obstructions_document())
    for change in ("omit", "shrink", "rename", "unknown"):
        rows = result.obstructions_document()
        if change == "omit":
            rows.clear()
        if change == "shrink":
            rows[0]["bounds_mm"][3] -= 1
        if change == "rename":
            rows[0]["obstruction_id"] = "other"
        if change == "unknown":
            rows[0]["kind"] = "unknown"
        with pytest.raises(TerrainDressingInvalid, match="contact differs"):
            result.require_contact(rows)


@pytest.mark.parametrize(
    "mutation", ["kind", "extra", "bool", "float", "scale", "id", "duplicate", "order", "count"]
)
def test_closed_bounded_syntax(mutation: str) -> None:
    payload = cube().build()
    raw = wire(payload, 2)
    row = raw["instances"][0]
    if mutation == "kind":
        row["source"]["kind"] = "workspace_asset"
    if mutation == "extra":
        row["solid"] = False
    if mutation == "bool":
        row["quarter_turns"] = True
    if mutation == "float":
        row["position_mm"][0] = 1.0
    if mutation == "scale":
        row["scale_per_mille"] = 4001
    if mutation == "id":
        row["instance_id"] = "a" * 65
    if mutation == "duplicate":
        raw["instances"][1] = copy.deepcopy(row)
    if mutation == "order":
        raw["instances"].reverse()
    if mutation == "count":
        raw = wire(payload, 9)
    with pytest.raises(TerrainDressingInvalid):
        read_terrain_dressing(raw)


def test_digest_component_set_and_constructed_dataclass_cannot_bypass_parser() -> None:
    payload = cube().build()
    parsed = read_terrain_dressing(wire(payload))
    with pytest.raises(TerrainDressingInvalid, match="digest"):
        read_terrain_dressing(parsed.document(), "0" * 64)
    for components in ({}, {"test.cube": payload, "extra": payload}, {"test.cube": b"bad"}):
        with pytest.raises(TerrainDressingInvalid):
            compile_terrain_dressing(parsed, components, decode_image=decode_texture)
    broken = replace(parsed, instances=(replace(parsed.instances[0], scale_per_mille=0),))
    with pytest.raises(TerrainDressingInvalid):
        compile_terrain_dressing(broken, {"test.cube": payload}, decode_image=decode_texture)


def test_repeated_sources_charge_geometry_per_placement_but_content_once() -> None:
    payload = cube(texture=png(2, 2)).build()
    result = compile_(wire(payload, 8), payload)
    assert len(result.obstructions) == result.draw_calls == 8
    assert result.rendered_triangles == 8 * 12
    assert result.decoded_texels == 4 and result.content_bytes == len(payload)


def test_repeated_active_nodes_hit_aggregate_limit_before_image_decode() -> None:
    g = cube(texture=png(2, 2))
    g.document["nodes"] = [{"mesh": 0} for _ in range(65)]
    g.scene(*range(65))
    payload = g.build()

    def unexpected(_: bytes) -> tuple[int, int]:
        raise AssertionError("must refuse before decode")

    with pytest.raises(TerrainDressingInvalid, match="geometry limit"):
        compile_terrain_dressing(
            read_terrain_dressing(wire(payload, 8)), {"test.cube": payload}, decode_image=unexpected
        )


def test_content_limit_before_hash_or_decode() -> None:
    payload = bytes(32 * 1024 * 1024 + 1)
    with pytest.raises(TerrainDressingInvalid, match="byte limit"):
        compile_(wire(payload), payload)


def test_decoded_texture_aggregate_refuses_before_decode() -> None:
    # Three individually allowed files with 8M decoded texels each, tiny encoded dimensions fixture.
    # The existing header parser reads PNG dimensions before the real decoder can touch payload.
    import struct
    import zlib

    g = cube(texture=png(1, 1))
    image = g.document["images"][0]
    view = g.document["bufferViews"][image["bufferView"]]
    offset = view["byteOffset"]
    struct.pack_into(">II", g.binary, offset + 16, 4096, 2048)
    struct.pack_into(">I", g.binary, offset + 29, zlib.crc32(g.binary[offset + 12 : offset + 29]))
    components = {}
    rows = []
    for i in range(3):
        g.document["asset"]["generator"] = f"variant{i}"
        payload = g.build()
        row = wire(payload)["instances"][0]
        row["instance_id"] = f"part{i}"
        row["source"]["asset_key"] = f"test.part{i}"
        rows.append(row)
        components[f"test.part{i}"] = payload
    raw = wire(payload)
    raw["instances"] = rows

    def unexpected(_: bytes) -> tuple[int, int]:
        raise AssertionError("must refuse before decode")

    with pytest.raises(TerrainDressingInvalid, match="texel limit"):
        compile_terrain_dressing(read_terrain_dressing(raw), components, decode_image=unexpected)


def test_exact_maximum_draw_and_proxy_budget_is_allowed() -> None:
    g = cube()
    g.document["nodes"] = [{"mesh": 0} for _ in range(64)]
    g.scene(*range(64))
    payload = g.build()
    facts = compile_(wire(payload, 8), payload)
    assert facts.draw_calls == len(facts.obstructions) == 512


def test_outward_rounded_bounds_cannot_leave_contact_domain() -> None:
    payload = cube().build()
    raw = wire(payload)
    raw["instances"][0]["position_mm"] = [512000, 0, 0]
    with pytest.raises(TerrainDressingInvalid, match="outside domain"):
        compile_(raw, payload)


def test_contact_integer_wire_cannot_be_replaced_by_equal_float_or_boolean() -> None:
    payload = cube().build()
    facts = compile_(wire(payload), payload)
    rows = facts.obstructions_document()
    rows[0]["bounds_mm"][0] = float(rows[0]["bounds_mm"][0])
    with pytest.raises(TerrainDressingInvalid):
        facts.require_contact(rows)


def test_dressing_rejects_active_matrix_even_when_legacy_static_admits() -> None:
    g = cube(node={"matrix": [1, 0, 0, 0, -1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]})
    payload = g.build()
    with pytest.raises(TerrainDressingInvalid, match="active matrix"):
        compile_(wire(payload), payload)


def test_large_canceling_trs_translations_are_outside_renderer_domain() -> None:
    g = cube()
    g.document["nodes"] = [
        {"translation": [16777217, 0, 0], "children": [1]},
        {"translation": [-16777216, 0, 0], "mesh": 0},
    ]
    g.scene(0)
    payload = g.build()
    with pytest.raises(TerrainDressingInvalid, match="matrix domain"):
        compile_(wire(payload), payload)


def test_deep_small_trs_chain_refuses_when_error_exceeds_one_mm() -> None:
    g = cube()
    g.document["nodes"] = [{"children": [i + 1]} for i in range(16)] + [{"mesh": 0}]
    g.scene(0)
    payload = g.build()
    with pytest.raises(TerrainDressingInvalid, match="one millimetre"):
        compile_(wire(payload), payload)
