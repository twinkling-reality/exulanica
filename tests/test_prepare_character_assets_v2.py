"""Complete exported bodies, mirrored skin groups, original motion and byte/source boundaries."""

from __future__ import annotations

import json
import runpy
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = runpy.run_path(str(ROOT / "scripts/prepare_character_assets_v2.py"))
VALIDATE = TOOLS["TOOLS"]
ASSETS = ROOT / "assets/characters/quaternius-modular-v2"


@pytest.fixture
def glb():
    return VALIDATE["read_glb"]((ASSETS / "hoodie.glb").read_bytes())


def test_complete_exported_parts_have_both_geometry_and_correct_skin_sides():
    TOOLS["verify"](ASSETS)
    assets = json.loads((ASSETS / "manifest.json").read_text())["assets"]
    assert len(assets) == 4
    for asset in assets:
        audit = asset["audit"]
        assert 23000 < audit["triangles"] < 27000
        assert audit["joint_count"] == 62
        assert {a["name"] for a in audit["animations"]} == {
            "Idle",
            "Walk",
            "Run",
            "Interact",
            "Wave",
        }
        for part in audit["bilateral_geometry"]:
            assert part["x_extent_metres"][0] < -0.05
            assert part["x_extent_metres"][1] > 0.05
            assert min(part["triangle_sides"].values()) > 30
            if not part["node"].endswith("_Head"):
                weights = part["limb_weight_sums"]
                assert weights["negative_R"] > 100 * weights["negative_L"]
                assert weights["positive_L"] > 100 * weights["positive_R"]
        assert any("Mirror" in r["operation"] for r in asset["preparation"]["repairs"])
        imported = json.loads((ASSETS / (asset["look_id"] + ".import.json")).read_text())
        assert imported["asset_key"].endswith(".v2")
        assert imported["content_sha256"] == audit["content_sha256"]
        assert imported["licence_sha256"] == TOOLS["digest"](
            (ASSETS / asset["license_file"]).read_bytes()
        )
        assert imported["source_revision"] == "sha256:" + asset["source_sha256"]


def test_original_half_body_failure_is_rejected_even_with_valid_normalized_skin(glb):
    doc, original = glb
    binary = bytearray(original)
    body = next(n for n in doc["nodes"] if n["name"] == "Casual_Body")
    for primitive in doc["meshes"][body["mesh"]]["primitives"]:
        a = doc["accessors"][primitive["attributes"]["POSITION"]]
        v = doc["bufferViews"][a["bufferView"]]
        start = v.get("byteOffset", 0) + a.get("byteOffset", 0)
        for index in range(a["count"]):
            offset = start + index * v.get("byteStride", 12)
            x = struct.unpack_from("<f", binary, offset)[0]
            struct.pack_into("<f", binary, offset, abs(x))
    with pytest.raises(ValueError, match="Incomplete bilateral geometry"):
        TOOLS["inspect_complete"](VALIDATE["container"](doc, binary))


def test_geometric_mirror_without_right_side_weight_remapping_is_rejected(glb):
    doc, original = glb
    binary = bytearray(original)
    names = [doc["nodes"][j]["name"] for j in doc["skins"][0]["joints"]]
    body = next(n for n in doc["nodes"] if n["name"] == "Casual_Body")
    for primitive in doc["meshes"][body["mesh"]]["primitives"]:
        a = doc["accessors"][primitive["attributes"]["JOINTS_0"]]
        v = doc["bufferViews"][a["bufferView"]]
        code, size = VALIDATE["COMPONENTS"][a["componentType"]]
        for index in range(a["count"]):
            start = (
                v.get("byteOffset", 0)
                + a.get("byteOffset", 0)
                + index * v.get("byteStride", 4 * size)
            )
            for channel in range(4):
                offset = start + channel * size
                joint = struct.unpack_from("<" + code, binary, offset)[0]
                if names[joint].endswith(".R"):
                    struct.pack_into(
                        "<" + code, binary, offset, names.index(names[joint][:-2] + ".L")
                    )
    with pytest.raises(ValueError, match="skin groups"):
        TOOLS["inspect_complete"](VALIDATE["container"](doc, binary))


@pytest.mark.parametrize("mutation", ["buffer", "image", "codec", "missing-wave", "cycle"])
def test_external_or_incomplete_character_inputs_fail(glb, mutation):
    doc, binary = glb
    if mutation == "buffer":
        doc["buffers"][0]["uri"] = "https://example.invalid/bytes"
    elif mutation == "image":
        doc["images"] = [{"uri": "https://example.invalid/image.png"}]
    elif mutation == "codec":
        doc["extensionsRequired"] = ["KHR_draco_mesh_compression"]
    elif mutation == "missing-wave":
        doc["animations"] = [a for a in doc["animations"] if a["name"] != "Wave"]
    else:
        doc["nodes"][0]["children"] = [0]
    with pytest.raises(ValueError):
        TOOLS["inspect_complete"](VALIDATE["container"](doc, binary))


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan")])
def test_skin_weights_must_be_finite_nonnegative_and_normalized(glb, value):
    doc, original = glb
    binary = bytearray(original)
    a = doc["accessors"][doc["meshes"][0]["primitives"][0]["attributes"]["WEIGHTS_0"]]
    v = doc["bufferViews"][a["bufferView"]]
    struct.pack_into(
        "<ffff", binary, v.get("byteOffset", 0) + a.get("byteOffset", 0), value, 0, 0, 0
    )
    with pytest.raises(ValueError, match=r"[Ww]eight|Non-finite"):
        TOOLS["inspect_complete"](VALIDATE["container"](doc, binary))


@pytest.mark.parametrize("mutation", ["root-travel", "bad-rotation"])
def test_gesture_tracks_preserve_root_and_quaternion_constraints(glb, mutation):
    doc, original = glb
    binary = bytearray(original)
    clip = next(a for a in doc["animations"] if a["name"] == "Interact")
    name, path = ("Root", "translation") if mutation == "root-travel" else ("Wrist.R", "rotation")
    node = next(i for i, n in enumerate(doc["nodes"]) if n["name"] == name)
    channel = next(c for c in clip["channels"] if c["target"] == {"node": node, "path": path})
    a = doc["accessors"][clip["samplers"][channel["sampler"]]["output"]]
    v = doc["bufferViews"][a["bufferView"]]
    struct.pack_into("<f", binary, v.get("byteOffset", 0) + a.get("byteOffset", 0), 10.0)
    with pytest.raises(ValueError, match=r"root travel|root motion|quaternion"):
        TOOLS["inspect_complete"](VALIDATE["container"](doc, binary))


def test_pinned_source_rejects_changed_local_bytes(tmp_path):
    source = json.loads((ASSETS / "source-lock.json").read_text())["sources"][0]
    (tmp_path / source["filename"]).write_bytes(b"changed source")
    with pytest.raises(ValueError, match="pinned bytes"):
        VALIDATE["fetch_pinned"](source, tmp_path)


@pytest.mark.parametrize("entry", ["prepare_character_assets.py", "prepare_character_gestures.py"])
def test_default_preparation_entry_points_only_verify_complete_v2(entry):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / entry), "--verify-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "complete bilateral geometry" in result.stdout


@pytest.mark.parametrize("mutation", ["licence", "import", "source-page"])
def test_bundle_rejects_drift_outside_glb(tmp_path, mutation):
    shutil.copytree(ASSETS, tmp_path / "assets")
    directory = tmp_path / "assets"
    if mutation == "licence":
        (directory / "men-LICENSE.txt").write_text("changed licence")
    elif mutation == "source-page":
        (directory / "women-source-page.html.txt").write_text("changed page")
    else:
        path = directory / "hoodie.import.json"
        imported = json.loads(path.read_text())
        imported["asset_key"] = "quaternius.modular.hoodie.v1"
        path.write_text(json.dumps(imported))
    with pytest.raises(ValueError, match=r"licence|page|Import"):
        TOOLS["verify"](directory)
