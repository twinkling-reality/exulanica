"""Strict decoding and skin/clip checks shared by the corrected artist asset preparation."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import struct
from itertools import pairwise
from pathlib import Path
import urllib.request

COMPONENTS = {
    5120: ("b", 1),
    5121: ("B", 1),
    5122: ("h", 2),
    5123: ("H", 2),
    5125: ("I", 4),
    5126: ("f", 4),
}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def read_glb(data: bytes) -> tuple[dict, bytes]:
    if not 20 <= len(data) <= 32 * 1024 * 1024:
        raise ValueError("GLB byte budget")
    if struct.unpack_from("<4sII", data) != (b"glTF", 2, len(data)):
        raise ValueError("GLB header")
    chunks = []
    offset = 12
    while offset < len(data):
        size, kind = struct.unpack_from("<II", data, offset)
        if size % 4 or offset + 8 + size > len(data):
            raise ValueError("GLB chunk bounds")
        chunks.append((kind, data[offset + 8 : offset + 8 + size]))
        offset += size + 8
    if [c[0] for c in chunks] != [0x4E4F534A, 0x004E4942]:
        raise ValueError("Expected JSON and BIN chunks only")
    document = json.loads(chunks[0][1])
    if document["asset"]["version"] != "2.0":
        raise ValueError("glTF version")
    if document.get("extensionsRequired") or document.get("extensionsUsed"):
        raise ValueError("Unreviewed extension or codec")
    binary = chunks[1][1]
    if len(document["buffers"]) != 1 or document["buffers"][0].get("uri"):
        raise ValueError("External or multiple buffers")
    if not 0 <= len(binary) - document["buffers"][0]["byteLength"] <= 3:
        raise ValueError("Binary buffer length")
    for image in document.get("images", []):
        if (
            image.get("uri")
            or "bufferView" not in image
            or image.get("mimeType") not in ("image/png", "image/jpeg")
        ):
            raise ValueError("External or unsupported image")
    for view in document["bufferViews"]:
        start = view.get("byteOffset", 0)
        if (
            view.get("buffer", 0) != 0
            or start < 0
            or view["byteLength"] < 0
            or start + view["byteLength"] > len(binary)
        ):
            raise ValueError("Buffer view bounds")
    return document, binary


def accessor(document: dict, binary: bytes, index: int) -> list[tuple]:
    value = document["accessors"][index]
    if (
        value.get("sparse")
        or value["componentType"] not in COMPONENTS
        or value["type"] not in WIDTH
    ):
        raise ValueError("Unsupported accessor")
    view = document["bufferViews"][value["bufferView"]]
    code, size = COMPONENTS[value["componentType"]]
    width = WIDTH[value["type"]]
    stride = view.get("byteStride", width * size)
    relative = value.get("byteOffset", 0)
    count = value["count"]
    if (
        count < 1
        or stride < width * size
        or relative < 0
        or relative + (count - 1) * stride + width * size > view["byteLength"]
    ):
        raise ValueError("Accessor bounds")
    start = view.get("byteOffset", 0) + relative
    rows = [
        struct.unpack_from("<" + code * width, binary, start + i * stride) for i in range(count)
    ]
    if any(not math.isfinite(x) for row in rows for x in row):
        raise ValueError("Non-finite accessor")
    return rows


def inspect_glb(data: bytes) -> dict:
    doc, binary = read_glb(data)
    # Inspect every accessor, including ones not referenced by a currently selected clip.
    arrays = [accessor(doc, binary, i) for i in range(len(doc["accessors"]))]
    nodes = doc["nodes"]
    names = [n.get("name") for n in nodes]
    if len(names) != len(set(names)) or any(not n for n in names):
        raise ValueError("Character nodes need unique names")
    parents = {}
    for parent, node in enumerate(nodes):
        for child in node.get("children", []):
            if child in parents or not 0 <= child < len(nodes):
                raise ValueError("Invalid node hierarchy")
            parents[child] = parent
    for child in range(len(nodes)):
        seen = set()
        while child in parents:
            if child in seen:
                raise ValueError("Cyclic hierarchy")
            seen.add(child)
            child = parents[child]
    if len(doc.get("skins", [])) != 1:
        raise ValueError("Expected one shared skin")
    skin = doc["skins"][0]
    joints = skin["joints"]
    if not 1 <= len(joints) <= 96 or len(set(joints)) != len(joints):
        raise ValueError("Joint budget or duplicates")
    if any(not 0 <= joint < len(nodes) for joint in joints):
        raise ValueError("Unknown joint")
    binds = arrays[skin["inverseBindMatrices"]]
    if len(binds) != len(joints) or any(len(row) != 16 for row in binds):
        raise ValueError("Bind matrix count")
    triangles = vertices = primitives = 0
    for node in nodes:
        if "mesh" not in node:
            continue
        if node.get("skin") != 0:
            raise ValueError("Unskinned character component")
        for primitive in doc["meshes"][node["mesh"]]["primitives"]:
            if primitive.get("mode", 4) != 4:
                raise ValueError("Expected triangles")
            attrs = primitive["attributes"]
            position, weights, indices = (
                arrays[attrs[key]] for key in ("POSITION", "WEIGHTS_0", "JOINTS_0")
            )
            if len(position) != len(weights) or len(weights) != len(indices):
                raise ValueError("Skin attribute cardinality")
            if any(abs(sum(row) - 1) > 1e-4 or min(row) < 0 for row in weights):
                raise ValueError("Weights must be nonnegative and normalized")
            if any(not 0 <= joint < len(joints) for row in indices for joint in row):
                raise ValueError("Unknown skin influence")
            draw = arrays[primitive["indices"]]
            if len(draw) % 3 or any(not 0 <= row[0] < len(position) for row in draw):
                raise ValueError("Triangle index bounds")
            vertices += len(position)
            triangles += len(draw) // 3
            primitives += 1
    if triangles > 50000 or primitives > 24:
        raise ValueError("Character geometry budget")
    clips = []
    for animation in doc["animations"]:
        durations = []
        targets = set()
        for channel in animation["channels"]:
            sampler = animation["samplers"][channel["sampler"]]
            times, values = arrays[sampler["input"]], arrays[sampler["output"]]
            if sampler.get("interpolation", "LINEAR") not in ("LINEAR", "STEP"):
                raise ValueError("Unexpected animation interpolation")
            if len(times) != len(values) or any(b[0] <= a[0] for a, b in pairwise(times)):
                raise ValueError("Invalid animation sample times")
            target = channel["target"]
            if not 0 <= target["node"] < len(nodes):
                raise ValueError("Unknown animation target")
            key = (target["node"], target["path"])
            if key in targets:
                raise ValueError("Duplicate animation channel")
            targets.add(key)
            if (
                names[target["node"]] == "Root"
                and target["path"] == "translation"
                and any(
                    max(row[axis] for row in values) - min(row[axis] for row in values) > 1e-5
                    for axis in (0, 2)
                )
            ):
                raise ValueError("Unhandled horizontal root motion")
            durations.append(times[-1][0] - times[0][0])
        clips.append(
            {
                "name": animation["name"],
                "duration_seconds": max(durations),
                "channels": len(targets),
            }
        )
    if {c["name"] for c in clips} != {"Idle", "Walk", "Run"}:
        raise ValueError("Missing or unexpected locomotion clip")
    hierarchy = [
        {
            "name": names[j],
            "parent": names[parents[j]] if j in parents else None,
            "translation": nodes[j].get("translation", [0, 0, 0]),
            "rotation": nodes[j].get("rotation", [0, 0, 0, 1]),
            "scale": nodes[j].get("scale", [1, 1, 1]),
        }
        for j in joints
    ]
    rig_digest = digest(canonical({"hierarchy": hierarchy, "inverse_bind_matrices": binds}))
    return {
        "byte_size": len(data),
        "content_sha256": digest(data),
        "triangles": triangles,
        "vertices": vertices,
        "draw_primitives": primitives,
        "joint_count": len(joints),
        "rig_sha256": rig_digest,
        "joints": hierarchy,
        "animations": clips,
        "materials": [
            {
                "name": m["name"],
                "index": i,
                "base_color_factor": m.get("pbrMetallicRoughness", {}).get(
                    "baseColorFactor", [1, 1, 1, 1]
                ),
            }
            for i, m in enumerate(doc.get("materials", []))
        ],
        "mesh_nodes": [n["name"] for n in nodes if "mesh" in n],
        "morph_target_count": sum(
            len(p.get("targets", [])) for m in doc["meshes"] for p in m["primitives"]
        ),
        "embedded_texture_count": len(doc.get("images", [])),
    }


def fetch_pinned(source: dict, directory: Path) -> Path:
    path = directory / source["filename"]
    if path.exists():
        data = path.read_bytes()
    else:
        with urllib.request.urlopen(source["url"], timeout=60) as response:
            data = response.read(source["byte_length"] + 1)
        if len(data) != source["byte_length"] or digest(data) != source["sha256"]:
            raise ValueError("Downloaded source does not match pinned bytes")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    if len(data) != source["byte_length"] or digest(data) != source["sha256"]:
        raise ValueError("Local source does not match pinned bytes")
    return path


GESTURES = {"interact": "Interact", "wave": "Wave"}


def container(document, binary):
    data = canonical(document)
    data += b" " * (-len(data) % 4)
    return (
        struct.pack("<4sII", b"glTF", 2, 28 + len(data) + len(binary))
        + struct.pack("<II", len(data), 0x4E4F534A)
        + data
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


def inspect_gestures(data):
    document, binary = read_glb(data)
    if {a["name"] for a in document["animations"]} != {
        "Idle",
        "Walk",
        "Run",
        "Interact",
        "Wave",
    } or len(document["animations"]) != 5:
        raise ValueError(
            "Expected exactly the three original locomotion and two original gesture clips"
        )
    # Apply the unchanged baseline skin, geometry and locomotion validator to its original subset.
    # All accessors are still checked. The two additional clips receive explicit checks below.
    locomotion = deepcopy(document)
    locomotion["animations"] = [
        a for a in document["animations"] if a["name"] not in GESTURES.values()
    ]
    audit = inspect_glb(container(locomotion, binary))
    arrays = [accessor(document, binary, i) for i in range(len(document["accessors"]))]
    for animation in document["animations"]:
        if animation["name"] not in GESTURES.values():
            continue
        targets, durations, animated_joints = set(), [], set()
        for channel in animation["channels"]:
            sampler = animation["samplers"][channel["sampler"]]
            times, values = arrays[sampler["input"]], arrays[sampler["output"]]
            if sampler.get("interpolation", "LINEAR") not in ("LINEAR", "STEP"):
                raise ValueError("Unexpected gesture interpolation")
            if len(times) != len(values) or any(b[0] <= a[0] for a, b in pairwise(times)):
                raise ValueError("Invalid gesture sample times")
            target = channel["target"]
            if not 0 <= target["node"] < len(document["nodes"]) or target["path"] not in (
                "translation",
                "rotation",
                "scale",
            ):
                raise ValueError("Unknown gesture target")
            key = (target["node"], target["path"])
            if key in targets:
                raise ValueError("Duplicate gesture channel")
            targets.add(key)
            name = document["nodes"][target["node"]]["name"]
            width = 4 if target["path"] == "rotation" else 3
            if any(len(row) != width for row in values):
                raise ValueError("Gesture vector width")
            if target["path"] == "rotation" and any(
                abs(sum(x * x for x in row) - 1) > 0.001 for row in values
            ):
                raise ValueError("Invalid gesture quaternion")
            if (
                name == "Root"
                and target["path"] == "translation"
                and any(
                    max(v[i] for v in values) - min(v[i] for v in values) > 1e-5 for i in (0, 2)
                )
            ):
                raise ValueError("Unhandled gesture root travel")
            if any(
                max(row[i] for row in values) - min(row[i] for row in values) > 0.001
                for i in range(width)
            ):
                animated_joints.add(name)
            durations.append(times[-1][0] - times[0][0])
        hand = "Wrist.R" if animation["name"] == "Interact" else "Wrist.L"
        if hand not in animated_joints:
            raise ValueError("Original gesture does not animate its declared hand")
        audit["animations"].append(
            {
                "name": animation["name"],
                "duration_seconds": max(durations),
                "channels": len(targets),
                "animated_joints": sorted(animated_joints),
            }
        )
    audit["animations"].sort(key=lambda x: x["name"])
    audit.update(content_sha256=digest(data), byte_size=len(data))
    return audit
