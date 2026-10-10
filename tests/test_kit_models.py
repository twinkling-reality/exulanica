"""The kit model reader, on models written here: what it reads, what it leaves out and what it
refuses.

A kit's archive is untrusted data and is not in this repository, so every model here is built by
the test in a temporary folder. Held: a node's place is applied; a plain material's colour is
carried from linear to sRGB and a picture is read where a triangle's middle maps to; a node named
to leave out is left out with what hangs under it, and a name the model does not hold is refused;
and a file a model names outside its own folder is refused, never opened.
"""

from __future__ import annotations

import importlib.util
import json
import struct
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# The reader builds meshes with numpy, which only the reconstruction extra installs.
np = pytest.importorskip(
    "numpy", reason="numpy is absent; install it with `uv sync --extra reconstruction`"
)

ROOT = Path(__file__).resolve().parents[1]
READER = ROOT / "scripts" / "style_packs" / "kit_models.py"
#: One triangle in the ground plane, and a second a metre up.
CORNERS = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)]


@pytest.fixture(scope="module")
def reader() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exulanica_kit_models_under_test", READER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _document(buffer_bytes: int, **more: Any) -> dict[str, Any]:
    """A model of two nodes: ``hull`` with one triangle, and under it ``oars``, the same triangle
    moved two metres along X, each with its own material."""
    return {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [
            {"name": "hull", "mesh": 0, "children": [1]},
            {"name": "oars", "mesh": 1, "translation": [2.0, 0.0, 0.0]},
        ],
        "meshes": [
            {"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "material": 0}]},
            {"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "material": 1}]},
        ],
        "materials": [
            {"pbrMetallicRoughness": {"baseColorFactor": [1.0, 0.0, 0.0, 1.0]}},
            {"pbrMetallicRoughness": {"baseColorFactor": [0.5, 0.5, 0.5, 1.0]}},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC2"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 24},
        ],
        "buffers": [{"byteLength": buffer_bytes}],
        **more,
    }


def _buffer(coordinates: list[tuple[float, float]]) -> bytes:
    positions = b"".join(struct.pack("<3f", *corner) for corner in CORNERS)
    return positions + b"".join(struct.pack("<2f", *uv) for uv in coordinates)


def _glb(document: dict[str, Any], binary: bytes) -> bytes:
    text = json.dumps(document).encode()
    text += b" " * (-len(text) % 4)
    binary += b"\x00" * (-len(binary) % 4)
    total = 12 + 8 + len(text) + 8 + len(binary)
    return (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(text), 0x4E4F534A)
        + text
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


UVS = [(0.1, 0.1), (0.3, 0.1), (0.1, 0.3)]


def _plain(tmp_path: Path) -> Path:
    binary = _buffer(UVS)
    path = tmp_path / "model.glb"
    path.write_bytes(_glb(_document(len(binary)), binary))
    return path


def test_a_node_is_placed_and_a_plain_material_is_its_colour_in_srgb(tmp_path, reader) -> None:
    mesh = reader.read_kit_model(_plain(tmp_path))
    assert len(mesh.triangles) == 2 and len(mesh.positions) == 6
    by_x = sorted(mesh.positions[triangle].min(axis=0)[0] for triangle in mesh.triangles)
    assert by_x == [0.0, 2.0]
    colours = {tuple(int(v) for v in colour) for colour in mesh.colours}
    # Linear 1, 0, 0 is sRGB 255, 0, 0; linear one half is sRGB 188, not 128.
    assert colours == {(255, 0, 0), (188, 188, 188)}


def test_a_node_named_to_leave_out_is_left_out_and_an_unknown_name_is_refused(
    tmp_path, reader
) -> None:
    path = _plain(tmp_path)
    mesh = reader.read_kit_model(path, ("oars",))
    assert len(mesh.triangles) == 1
    assert {tuple(int(v) for v in colour) for colour in mesh.colours} == {(255, 0, 0)}
    # Leaving out a node leaves out what hangs under it: nothing is left of this model.
    with pytest.raises(reader.KitModelRefused, match="no triangle"):
        reader.read_kit_model(path, ("hull",))
    with pytest.raises(reader.KitModelRefused, match="paddles"):
        reader.read_kit_model(path, ("paddles",))


def test_a_picture_is_read_where_the_triangles_middle_maps_to(tmp_path, reader) -> None:
    # Pillow is one of the product's own dependencies, so it is imported, not skipped for.
    from PIL import Image as image

    # Four flat patches: the triangle's middle, about (0.17, 0.17), lies in the first.
    picture = image.new("RGB", (2, 2))
    picture.putdata([(10, 20, 30), (40, 50, 60), (70, 80, 90), (100, 110, 120)])
    picture.save(tmp_path / "patches.png")
    binary = _buffer(UVS)
    (tmp_path / "model.bin").write_bytes(binary)
    document = _document(len(binary), images=[{"uri": "patches.png"}], textures=[{"source": 0}])
    document["buffers"][0]["uri"] = "model.bin"
    document["materials"][0] = {"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}
    (tmp_path / "model.gltf").write_text(json.dumps(document), encoding="utf-8")
    mesh = reader.read_kit_model(tmp_path / "model.gltf", ("oars",))
    assert {tuple(int(v) for v in colour) for colour in mesh.colours} == {(10, 20, 30)}


@pytest.mark.parametrize("uri", ["../outside.bin", "/etc/hosts", "https://example.org/a.bin"])
def test_a_file_named_outside_the_models_folder_is_refused(tmp_path, reader, uri) -> None:
    folder = tmp_path / "kit"
    folder.mkdir()
    binary = _buffer(UVS)
    # The file exists where the name points, so only the refusal keeps it from being read.
    (tmp_path / "outside.bin").write_bytes(binary)
    document = _document(len(binary))
    document["buffers"][0]["uri"] = uri
    (folder / "model.gltf").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(reader.KitModelRefused, match="outside its folder"):
        reader.read_kit_model(folder / "model.gltf")


def test_a_file_that_is_not_a_binary_gltf_is_refused(tmp_path, reader) -> None:
    path = tmp_path / "model.glb"
    path.write_bytes(b"not a model at all, only some bytes")
    with pytest.raises(reader.KitModelRefused, match="not a binary glTF"):
        reader.read_kit_model(path)
