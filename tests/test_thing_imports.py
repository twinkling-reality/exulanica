"""Looks imported from packs other makers published: held to their committed files, with no archive.

What is shown here, with no database and none of the source archives:

*   every imported look's container is the committed file its import receipt names, byte for byte,
    the receipt reads as the reviewed importer's, and the container passes the product's container
    check; its translation manifest is the one its origin names, reads, targets that look, and
    accounts for every field of the committed source reading, whose files are its ingredients;
*   an imported figure's rig names only joints and clips its container holds, its clips stay in
    place on the joints its import document names, and it stands at the height its look states;
*   a static look a kind lists lies inside the kind's box, its container read from the file;
*   every file an imported look names (its container, import receipt, source reading and its
    sources' licence files) is allowlisted for the API image and copied into it;
*   the importer's merge, on a small figure made here: only the named clips come across, named by
    their motions, each joint the import holds in place keeps its first key's ground position while
    it rises and falls, and the height is baked into the vertices, the joints' and clips'
    translations and the inverse bind matrices, with no node scaled.

The archives themselves are checked by ``scripts/things/import_looks.py --check`` where they are
present; nothing here needs them.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path
from typing import Any

import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.things.looks import read_look
from exulanica.things.manifests import ManifestRefused, check_accounting, read_manifest
from exulanica.world.asset_import import ReviewedAssetImport, validate_import_container
from exulanica.world.static_glb import inspect_static_glb

ROOT = Path(__file__).resolve().parents[1]
LOOKS = ROOT / "assets/catalogs/things/looks"
MANIFESTS = ROOT / "assets/catalogs/things/manifests"
IMPORTED = ROOT / "assets/things"


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _imported_looks() -> list[dict[str, Any]]:
    return [
        doc
        for doc in (_json(path) for path in sorted(LOOKS.glob("*.json")))
        if doc["origin"]["class"] == "imported" and doc["container"] is not None
    ]


def _receipts() -> dict[str, Path]:
    return {
        _json(path)["content_sha256"]: path for path in sorted(IMPORTED.glob("*/*.import.json"))
    }


def _container(doc: dict[str, Any]) -> bytes:
    receipt = _receipts()[doc["container"]["sha256"]]
    return receipt.with_name(receipt.name.removesuffix(".import.json") + ".glb").read_bytes()


def _gltf(payload: bytes) -> dict[str, Any]:
    """The JSON chunk of a binary glTF, read here apart from the importer under test."""
    length, kind = struct.unpack("<II", payload[12:20])
    assert kind == 0x4E4F534A
    return json.loads(payload[20 : 20 + length])


def test_imported_looks_ship():
    keys = {(doc["look"], doc["look_kind"]) for doc in _imported_looks()}
    assert {kind for _, kind in keys} >= {"skinned", "static"}


@pytest.mark.parametrize("look", [doc["look"] for doc in _imported_looks()])
def test_an_imported_look_is_held_to_its_committed_files(look):
    doc = _json(LOOKS / f"{look}.v1.json")
    read_look(doc)
    receipt_path = _receipts()[doc["container"]["sha256"]]
    receipt = ReviewedAssetImport.model_validate(_json(receipt_path))
    payload = _container(doc)
    assert hashlib.sha256(payload).hexdigest() == doc["container"]["sha256"]
    assert len(payload) == doc["container"]["bytes"] == receipt.byte_size
    validate_import_container(payload)
    if doc["look_kind"] == "static":
        inspect_static_glb(payload)
    plan = _json(receipt_path.parent / "import.json")
    licences = {
        hashlib.sha256((receipt_path.parent / source["licence_file"]).read_bytes()).hexdigest()
        for source in plan["sources"].values()
    }
    assert receipt.licence_sha256 in licences
    assert doc["origin"]["licence"]["licence_text_sha256"] in licences
    manifest = _json(MANIFESTS / f"{look}.v{doc['version']}.json")
    assert (
        sha256_of_canonical(manifest).hex()
        == doc["origin"]["lineage"]["translation_manifest_sha256"]
    )
    assert manifest["target"] == {"kind": None, "look": {"look": look, "version": doc["version"]}}
    reading = _json(receipt_path.with_name(f"{look}.source.json"))
    assert sha256_of_canonical(reading).hex() == manifest["source"]["sha256"]
    check_accounting(read_manifest(manifest), reading)
    assert (
        sorted({file["sha256"] for file in reading["files"]})
        == doc["origin"]["lineage"]["ingredients"]
    )


def test_a_manifest_that_leaves_a_field_unaccounted_is_refused():
    doc = next(doc for doc in _imported_looks() if doc["look_kind"] == "skinned")
    manifest = _json(MANIFESTS / f"{doc['look']}.v{doc['version']}.json")
    receipt_path = _receipts()[doc["container"]["sha256"]]
    reading = _json(receipt_path.with_name(f"{doc['look']}.source.json"))
    check_accounting(read_manifest(manifest), reading)  # the positive control
    short = copy.deepcopy(manifest)
    dropped = next(i for i, f in enumerate(short["fields"]) if f["disposition"] == "dropped")
    del short["fields"][dropped]
    with pytest.raises(ManifestRefused, match="accounted for 0 times"):
        check_accounting(read_manifest(short), reading)


def _figures() -> list[dict[str, Any]]:
    return [doc for doc in _imported_looks() if doc["look_kind"] == "skinned"]


@pytest.mark.parametrize("look", [doc["look"] for doc in _figures()])
def test_an_imported_figure_s_rig_names_only_what_its_container_holds(look):
    doc = _json(LOOKS / f"{look}.v1.json")
    gltf = _gltf(_container(doc))
    joints = {gltf["nodes"][j]["name"] for skin in gltf["skins"] for j in skin["joints"]}
    clips = {animation["name"] for animation in gltf["animations"]}
    rig = doc["rig"]
    assert set(rig["bones"].values()) <= joints
    assert set(rig["sockets"].values()) <= joints
    assert set(rig["clips"].values()) == clips  # only the clips its motions use came across
    assert set(rig["ground_speed_mm_per_s"]) <= set(rig["clips"])


@pytest.mark.parametrize("look", [doc["look"] for doc in _figures()])
def test_an_imported_figure_s_clips_stay_in_place(look):
    doc = _json(LOOKS / f"{look}.v1.json")
    receipt_path = _receipts()[doc["container"]["sha256"]]
    plan = _json(receipt_path.parent / "import.json")
    held = next(entry for entry in plan["looks"] if entry["look"] == look)["in_place"]
    payload = _container(doc)
    gltf = _gltf(payload)
    names = [node.get("name") for node in gltf["nodes"]]
    binary_start = 20 + struct.unpack("<I", payload[12:16])[0] + 8
    seen = 0
    for animation in gltf["animations"]:
        for channel in animation["channels"]:
            if channel["target"]["path"] != "translation":
                continue
            if names[channel["target"]["node"]] not in held:
                continue
            accessor = gltf["accessors"][animation["samplers"][channel["sampler"]]["output"]]
            view = gltf["bufferViews"][accessor["bufferView"]]
            start = binary_start + view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            keys = [
                struct.unpack_from("<3f", payload, start + 12 * i) for i in range(accessor["count"])
            ]
            assert {(x, z) for x, _, z in keys} == {(keys[0][0], keys[0][2])}
            seen += 1
    assert seen, "the clips move the joints the import holds in place"


@pytest.mark.parametrize("look", [doc["look"] for doc in _figures()])
def test_an_imported_figure_stands_at_the_height_its_look_states(look):
    doc = _json(LOOKS / f"{look}.v1.json")
    gltf = _gltf(_container(doc))
    # The height is in the vertices themselves: no node above a joint or the mesh is scaled.
    assert not any("scale" in node or "matrix" in node for node in gltf["nodes"] if "mesh" in node)
    top = gltf["nodes"][gltf["scenes"][0]["nodes"][0]]
    assert "scale" not in top and "matrix" not in top
    tallest = max(
        gltf["accessors"][primitive["attributes"]["POSITION"]]["max"][1]
        for mesh in gltf["meshes"]
        for primitive in mesh["primitives"]
    )
    assert abs(tallest * 1000 - doc["height_mm"]) <= 1


def _placed_bounds(gltf: dict[str, Any]) -> tuple[list[float], list[float]]:
    """Every mesh's bounds where its nodes put it, for nodes that only move and scale."""
    low, high = [float("inf")] * 3, [float("-inf")] * 3

    def visit(index: int, offset: list[float], scale: float) -> None:
        node = gltf["nodes"][index]
        assert "rotation" not in node and "matrix" not in node
        sizes = node.get("scale", [1.0, 1.0, 1.0])
        assert sizes[0] == sizes[1] == sizes[2]
        moved = [
            o + scale * t for o, t in zip(offset, node.get("translation", [0, 0, 0]), strict=True)
        ]
        here = scale * sizes[0]
        if "mesh" in node:
            for primitive in gltf["meshes"][node["mesh"]]["primitives"]:
                accessor = gltf["accessors"][primitive["attributes"]["POSITION"]]
                for i in range(3):
                    low[i] = min(low[i], moved[i] + here * accessor["min"][i])
                    high[i] = max(high[i], moved[i] + here * accessor["max"][i])
        for child in node.get("children", []):
            visit(child, moved, here)

    for root in gltf["scenes"][0]["nodes"]:
        visit(root, [0.0, 0.0, 0.0], 1.0)
    return low, high


def test_every_imported_static_look_a_kind_lists_lies_inside_the_kind_s_box():
    imported = {doc["container"]["sha256"]: doc for doc in _imported_looks()}
    checked = 0
    for kind in shipped_thing_kinds().values():
        box = kind.document["body"].get("box_mm")
        if box is None:
            continue
        for reference in kind.document["looks"]:
            doc = next(
                (
                    d
                    for d in imported.values()
                    if (d["look"], d["version"]) == (reference["look"], reference["version"])
                ),
                None,
            )
            if doc is None or doc["look_kind"] != "static":
                continue
            low, high = _placed_bounds(_gltf(_container(doc)))
            # glTF X = -x, Y = z, Z = y, in metres; the box's base centre is the origin.
            assert max(abs(low[0]), abs(high[0])) * 1000 <= box["width"] / 2 + 1
            assert max(abs(low[2]), abs(high[2])) * 1000 <= box["depth"] / 2 + 1
            assert low[1] * 1000 >= -1 and high[1] * 1000 <= box["height"] + 1
            checked += 1
    assert checked, "a kind lists an imported static look"


def _importer():
    spec = importlib.util.spec_from_file_location(
        "import_looks", ROOT / "scripts/things/import_looks.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["import_looks"] = module
    spec.loader.exec_module(module)
    return module


def _glb(document: dict[str, Any], binary: bytes) -> bytes:
    text = json.dumps(document, separators=(",", ":")).encode("ascii")
    text += b" " * (-len(text) % 4)
    binary += b"\0" * (-len(binary) % 4)
    return b"".join(
        (
            struct.pack("<III", 0x46546C67, 2, 28 + len(text) + len(binary)),
            struct.pack("<II", len(text), 0x4E4F534A),
            text,
            struct.pack("<II", len(binary), 0x004E4942),
            binary,
        )
    )


def _small_figure() -> tuple[bytes, bytes]:
    """A figure of three joints and one triangle 2 m tall whose inverse bind matrices undo its rest
    pose (the hips 1 m above the root, the foot back on the ground), and a clip file with two
    clips."""
    positions = struct.pack("<9f", 0, 0, 0, 0.5, 0, 0, 0, 2.0, 0)
    joints = struct.pack("<12B", 0, 0, 0, 0, 1, 0, 0, 0, 2, 0, 0, 0)
    weights = struct.pack("<12f", 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)
    identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    hips = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -1, 0, 1]
    matrices = struct.pack("<48f", *identity, *hips, *identity)
    figure_binary = positions + joints + weights + matrices
    figure = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [
            {"name": "Top", "children": [1, 4]},
            {"name": "root", "children": [2]},
            {"name": "hips", "translation": [0, 1, 0], "children": [3]},
            {"name": "foot", "translation": [0, -1, 0]},
            {"name": "Body", "mesh": 0, "skin": 0},
        ],
        "meshes": [
            {
                "name": "Body",
                "primitives": [{"attributes": {"POSITION": 0, "JOINTS_0": 1, "WEIGHTS_0": 2}}],
            }
        ],
        "skins": [{"joints": [1, 2, 3], "inverseBindMatrices": 3}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "min": [0, 0, 0],
                "max": [0.5, 2.0, 0],
            },
            {"bufferView": 1, "componentType": 5121, "count": 3, "type": "VEC4"},
            {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC4"},
            {"bufferView": 3, "componentType": 5126, "count": 3, "type": "MAT4"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 12},
            {"buffer": 0, "byteOffset": 48, "byteLength": 48},
            {"buffer": 0, "byteOffset": 96, "byteLength": 192},
        ],
        "buffers": [{"byteLength": len(figure_binary)}],
    }
    times = struct.pack("<3f", 0.0, 0.5, 1.0)
    drifting = struct.pack("<9f", 0.1, 1.0, -0.2, 0.3, 1.1, 0.4, 0.2, 1.0, 0.0)
    turning = struct.pack("<12f", 0, 0, 0, 1, 0, 0.1, 0, 0.995, 0, 0, 0, 1)
    clips_binary = times + drifting + turning
    clips = {
        "asset": {"version": "2.0"},
        "nodes": [{"name": "root"}, {"name": "hips"}, {"name": "foot"}],
        "animations": [
            {
                "name": "Walk",
                "channels": [
                    {"sampler": 0, "target": {"node": 1, "path": "translation"}},
                    {"sampler": 1, "target": {"node": 2, "path": "rotation"}},
                ],
                "samplers": [{"input": 0, "output": 1}, {"input": 0, "output": 2}],
            },
            {
                "name": "Dance",
                "channels": [{"sampler": 0, "target": {"node": 2, "path": "rotation"}}],
                "samplers": [{"input": 0, "output": 2}],
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 3,
                "type": "SCALAR",
                "min": [0],
                "max": [1],
            },
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC4"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 12},
            {"buffer": 0, "byteOffset": 12, "byteLength": 36},
            {"buffer": 0, "byteOffset": 48, "byteLength": 48},
        ],
        "buffers": [{"byteLength": len(clips_binary)}],
    }
    return _glb(figure, figure_binary), _glb(clips, clips_binary)


def test_the_importer_merges_only_the_named_clips_in_place_at_the_stated_height():
    importer = _importer()
    figure, clip_file = _small_figure()
    payload, made = importer.merge_figure(
        importer.read_glb(figure),
        {"clips.glb": importer.read_glb(clip_file)},
        [{"file": "clips.glb", "clip": "Walk", "motion": "walk"}],
        ["hips"],
        1800,
    )
    validate_import_container(payload)
    merged = importer.read_glb(payload)
    # Only the named clip came across, named by the motion it plays.
    assert [a["name"] for a in merged.document["animations"]] == ["walk"]
    walk = merged.document["animations"][0]
    names = [node["name"] for node in merged.document["nodes"]]
    moved = {(names[c["target"]["node"]], c["target"]["path"]): c for c in walk["channels"]}
    translation = walk["samplers"][moved[("hips", "translation")]["sampler"]]["output"]
    keys = merged.values(translation)
    # 1,800 mm of a 2,000 mm figure is 0.9 of it, baked into every translation; the hips hold the
    # first key's ground position (0.1, -0.2) while they rise and fall.
    f32 = lambda value: struct.unpack("<f", struct.pack("<f", value))[0]  # noqa: E731
    first_x, first_z = f32(f32(0.1) * 0.9), f32(f32(-0.2) * 0.9)
    assert [(x, z) for x, _, z in keys] == [(first_x, first_z)] * 3
    assert [y for _, y, _ in keys] == [f32(f32(v) * 0.9) for v in (1.0, 1.1, 1.0)]
    assert round(made["clips"]["Walk"]["drift"], 6) == 0.6  # z went from -0.2 to 0.4
    # No node is scaled; the one mesh node holds the figure's parts on its one skin.
    assert not any("scale" in node for node in merged.document["nodes"])
    mesh_nodes = [node for node in merged.document["nodes"] if "mesh" in node]
    assert len(mesh_nodes) == 1 and mesh_nodes[0]["skin"] == 0
    tallest = merged.document["accessors"][
        merged.document["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
    ]["max"][1]
    assert tallest == f32(2.0 * 0.9)
    # The hips stand 0.9 m above the root in the rest pose, and their bind matrix still undoes it.
    hips = merged.document["nodes"][names.index("hips")]
    assert hips["translation"] == [0.0, 0.9, 0.0]
    skin = merged.document["skins"][0]
    undo = {"root": 0.0, "hips": f32(-1.0 * 0.9), "foot": 0.0}
    for joint, matrix in zip(
        skin["joints"], merged.values(skin["inverseBindMatrices"]), strict=True
    ):
        assert matrix[12:15] == (0.0, undo[names[joint]], 0.0)


def test_every_file_an_imported_look_names_ships_in_the_api_image():
    from test_image_ships_import_reads import IMAGES

    image = IMAGES["api"]
    named = []
    for doc in _imported_looks():
        receipt = _receipts()[doc["container"]["sha256"]]
        plan = _json(receipt.parent / "import.json")
        named += [
            receipt,
            receipt.with_name(receipt.name.removesuffix(".import.json") + ".glb"),
            receipt.with_name(f"{doc['look']}.source.json"),
            *(receipt.parent / source["licence_file"] for source in plan["sources"].values()),
        ]
    paths = sorted({path.relative_to(ROOT).as_posix() for path in named})
    assert paths, "imported looks name files"
    missing = [path for path in paths if not (image.allowlisted(path) and image.shipped(path))]
    assert missing == []
