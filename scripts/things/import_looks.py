"""Make looks from packs other makers published, or check the committed ones are exactly them.

    uv run python scripts/things/import_looks.py assets/things/<folder>/import.json \
        --archive <source>=<zip> [--archive <source>=<zip> ...] [--check]

An import document is data: each source pack it reads (its page, its archive by digest, its
licence file), and for each look it makes, the files it reads from which source, how a figure's
joints map onto the body plan's bones and sockets, which clip each motion uses, the box an object
must stand inside, and in plain words why each joint or clip that does not come across stays
behind. This tool is the one translator for every such document; it names no pack, figure or thing.

It reads each archive once, by digest, and writes beside the import document:

*   each look's container: a rigged figure in the shared skinned shape
    (``exulanica.skinned-glb/v1``): one skinned mesh at the root of the scene whose parts are the
    figure's mesh nodes, with only the clips its motions use, each named by its motion and kept in
    place (the joints the document names hold their sideways and forward position at the clip's
    first key, so a clip never carries the figure, while a pose such as sitting back keeps its
    offset), and the uniform scale that stands it at the document's height baked into its
    vertices, bind matrices, joints and clips, so no node is scaled; or an object with its pictures
    embedded, scaled uniformly to stand inside its box and prepared as any person's static
    container is (:func:`exulanica.world.static_glb.prepare_static_glb`);
*   each source's licence file, byte for byte, and a reviewed import receipt per container
    (``exulanica.reviewed-asset-import/v1``), so a host publishes it with the importer it has;
*   a source reading per look: the files it read, by digest, and the fields of the source the
    translation manifest accounts for;

and under ``assets/catalogs/things``, each look document and its translation manifest. The
manifest names the look by key and version; the look's origin names the manifest by digest.

A figure's ground speed per moving motion is measured here from its own clip, not stated: the
median horizontal speed of the feet the document names while each is within ``stance_mm`` of its
lowest point, at the look's height. Rotations between keys are interpolated by normalised linear
interpolation, so the figure is the same on any machine (square roots only, which IEEE 754 rounds
exactly).

``--check`` writes nothing: it makes everything again from the archives and fails on any byte that
differs. Without the archives, the committed files are checked by the tests instead.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import struct
import sys
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from exulanica.canonical import canonical_json, sha256_of_canonical  # noqa: E402
from exulanica.world.asset_import import validate_import_container  # noqa: E402
from exulanica.world.asset_preparation import decode_texture  # noqa: E402
from exulanica.world.static_glb import prepare_static_glb  # noqa: E402

IMPORT_PROFILE: Final = "exulanica.look-import/v1"
TRANSLATOR: Final = "gltf-look-import"
TRANSLATOR_VERSION: Final = 1
PRODUCER: Final = f"exulanica-look-import/{TRANSLATOR_VERSION}"
LOOKS: Final = ROOT / "assets/catalogs/things/looks"
MANIFESTS: Final = ROOT / "assets/catalogs/things/manifests"
_MAGIC: Final = 0x46546C67
_CHUNK_JSON: Final = 0x4E4F534A
_CHUNK_BIN: Final = 0x004E4942
_FLOAT: Final = 5126
_FORMATS: Final = {5126: ("f", 4), 5125: ("I", 4), 5123: ("H", 2), 5121: ("B", 1)}
_WIDTH: Final = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_PATH_WIDTH: Final = {"translation": "VEC3", "rotation": "VEC4", "scale": "VEC3"}


class ImportRefused(ValueError):
    """An import this tool will not make, by what is wrong."""


# -- reading and writing glTF ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Gltf:
    """A glTF document and the one binary buffer its views index."""

    document: dict[str, Any]
    binary: bytes

    def values(self, index: int) -> list[tuple[float, ...]]:
        """An accessor's elements, each a tuple, read from its view."""
        accessor = self.document["accessors"][index]
        view = self.document["bufferViews"][accessor["bufferView"]]
        code, size = _FORMATS[accessor["componentType"]]
        width = _WIDTH[accessor["type"]]
        stride = view.get("byteStride", size * width)
        base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        return [
            struct.unpack_from(f"<{width}{code}", self.binary, base + i * stride)
            for i in range(accessor["count"])
        ]

    def node_index(self) -> dict[str, int]:
        found: dict[str, int] = {}
        for index, node in enumerate(self.document["nodes"]):
            name = node.get("name")
            if name in found:
                raise ImportRefused(f"two nodes are named {name!r}")
            found[name] = index
        return found


def read_glb(payload: bytes) -> Gltf:
    magic, version, length = struct.unpack_from("<III", payload)
    if (magic, version, length) != (_MAGIC, 2, len(payload)):
        raise ImportRefused("not a glTF 2.0 binary of its declared length")
    offset, document, binary = 12, None, b""
    while offset < len(payload):
        size, kind = struct.unpack_from("<II", payload, offset)
        chunk = payload[offset + 8 : offset + 8 + size]
        if kind == _CHUNK_JSON:
            document = json.loads(chunk)
        elif kind == _CHUNK_BIN:
            binary = chunk
        offset += 8 + size
    if document is None or len(document.get("buffers", [])) > 1:
        raise ImportRefused("a binary glTF with one JSON chunk and at most one buffer")
    return Gltf(document, binary)


def read_gltf(text: bytes, resolve: Callable[[str], bytes]) -> Gltf:
    """A text glTF whose one buffer and pictures are files beside it, as one embedded binary:
    the buffer first, then each picture in its own view."""
    document = json.loads(text)
    buffers = document.get("buffers", [])
    if len(buffers) != 1 or "uri" not in buffers[0]:
        raise ImportRefused("a text glTF with one buffer in a file beside it")
    binary = bytearray(resolve(buffers[0]["uri"]))
    if len(binary) != buffers[0]["byteLength"]:
        raise ImportRefused("the buffer file is not the length the document states")
    for image in document.get("images", []):
        if "uri" not in image:
            continue
        picture = resolve(image.pop("uri"))
        _align(binary)
        document["bufferViews"].append(
            {"buffer": 0, "byteOffset": len(binary), "byteLength": len(picture)}
        )
        binary += picture
        image["bufferView"] = len(document["bufferViews"]) - 1
    _align(binary)
    document["buffers"] = [{"byteLength": len(binary)}]
    return Gltf(document, bytes(binary))


def _align(binary: bytearray) -> None:
    while len(binary) % 4:
        binary.append(0)


def write_glb(document: Mapping[str, Any], binary: bytes) -> bytes:
    """The container's bytes: keys sorted, no whitespace, the JSON padded with spaces and the
    binary with zeros, so the same document writes the same bytes on any machine."""
    text = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("ascii")
    text += b" " * (-len(text) % 4)
    body = bytes(binary) + b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(text) + 8 + len(body)
    return b"".join(
        (
            struct.pack("<III", _MAGIC, 2, total),
            struct.pack("<II", len(text), _CHUNK_JSON),
            text,
            struct.pack("<II", len(body), _CHUNK_BIN),
            body,
        )
    )


# -- poses -----------------------------------------------------------------------------------------


def _nlerp(a: Sequence[float], b: Sequence[float], u: float) -> tuple[float, ...]:
    if sum(x * y for x, y in zip(a, b, strict=True)) < 0:
        b = tuple(-x for x in b)
    mixed = tuple(x + u * (y - x) for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in mixed))
    return tuple(x / norm for x in mixed)


def _matrix(t: Sequence[float], r: Sequence[float], s: Sequence[float]) -> list[list[float]]:
    x, y, z, w = r
    return [
        [
            (1 - 2 * (y * y + z * z)) * s[0],
            2 * (x * y - w * z) * s[1],
            2 * (x * z + w * y) * s[2],
            t[0],
        ],
        [
            2 * (x * y + w * z) * s[0],
            (1 - 2 * (x * x + z * z)) * s[1],
            2 * (y * z - w * x) * s[2],
            t[1],
        ],
        [
            2 * (x * z - w * y) * s[0],
            2 * (y * z + w * x) * s[1],
            (1 - 2 * (x * x + y * y)) * s[2],
            t[2],
        ],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _times(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


@dataclass(frozen=True, slots=True)
class Clip:
    """One animation's tracks by joint name and path, read once."""

    name: str
    tracks: Mapping[tuple[str, str], tuple[list[float], list[tuple[float, ...]]]]
    seconds: float

    def at(self, joint: str, path: str, t: float) -> tuple[float, ...] | None:
        track = self.tracks.get((joint, path))
        if track is None:
            return None
        times, values = track
        if t <= times[0]:
            return values[0]
        if t >= times[-1]:
            return values[-1]
        low, high = 0, len(times) - 1
        while high - low > 1:
            middle = (low + high) // 2
            if times[middle] <= t:
                low = middle
            else:
                high = middle
        u = (t - times[low]) / (times[high] - times[low])
        if path == "rotation":
            return _nlerp(values[low], values[high], u)
        return tuple(x + u * (y - x) for x, y in zip(values[low], values[high], strict=True))


def read_clip(gltf: Gltf, animation: Mapping[str, Any]) -> Clip:
    names = [node.get("name") for node in gltf.document["nodes"]]
    tracks: dict[tuple[str, str], tuple[list[float], list[tuple[float, ...]]]] = {}
    seconds = 0.0
    for channel in animation["channels"]:
        sampler = animation["samplers"][channel["sampler"]]
        if sampler.get("interpolation", "LINEAR") != "LINEAR":
            raise ImportRefused(f"clip {animation.get('name')}: only linear keys are read")
        times = [value[0] for value in gltf.values(sampler["input"])]
        target = channel["target"]
        tracks[(names[target["node"]], target["path"])] = (times, gltf.values(sampler["output"]))
        seconds = max(seconds, times[-1])
    return Clip(str(animation.get("name")), tracks, seconds)


def joint_positions(
    gltf: Gltf, clip: Clip | None, t: float
) -> dict[str, tuple[float, float, float]]:
    """Every node's position in the scene at time ``t`` of ``clip`` (its rest pose without one),
    the scene's top node's own transform included."""
    nodes = gltf.document["nodes"]
    parent = {
        child: index for index, node in enumerate(nodes) for child in node.get("children", [])
    }
    world: dict[int, list[list[float]]] = {}

    def local(index: int) -> list[list[float]]:
        node = nodes[index]
        name = node.get("name")
        parts = {
            "translation": tuple(node.get("translation", (0.0, 0.0, 0.0))),
            "rotation": tuple(node.get("rotation", (0.0, 0.0, 0.0, 1.0))),
            "scale": tuple(node.get("scale", (1.0, 1.0, 1.0))),
        }
        if clip is not None:
            for path in parts:
                moved = clip.at(name, path, t)
                if moved is not None:
                    parts[path] = moved
        return _matrix(parts["translation"], parts["rotation"], parts["scale"])

    def at(index: int) -> list[list[float]]:
        if index not in world:
            own = local(index)
            world[index] = _times(at(parent[index]), own) if index in parent else own
        return world[index]

    return {
        node.get("name"): (at(i)[0][3], at(i)[1][3], at(i)[2][3]) for i, node in enumerate(nodes)
    }


# -- a figure --------------------------------------------------------------------------------------


def _top_node(gltf: Gltf) -> int:
    scenes = gltf.document.get("scenes", [])
    if len(scenes) != 1 or len(scenes[0].get("nodes", [])) != 1:
        raise ImportRefused("a figure is one scene with one top node to scale")
    return int(scenes[0]["nodes"][0])


def _rest_height(gltf: Gltf) -> float:
    """The highest point of the figure's meshes in their bind space, in its own units."""
    heights = [
        gltf.document["accessors"][primitive["attributes"]["POSITION"]]["max"][1]
        for mesh in gltf.document["meshes"]
        for primitive in mesh["primitives"]
    ]
    return float(max(heights))


def _animation(gltf: Gltf, name: str) -> Mapping[str, Any] | None:
    for animation in gltf.document.get("animations", []):
        if animation.get("name") == name:
            return animation
    return None


def merge_figure(
    figure: Gltf,
    clip_files: Mapping[str, Gltf],
    clips: Sequence[Mapping[str, str]],
    in_place: Sequence[str],
    height_mm: int,
) -> tuple[bytes, dict[str, Any]]:
    """The figure as one skinned mesh with only ``clips``, each kept in place and named by the
    motion it plays, scaled into its vertices, bind matrices, joints and clips so it stands
    ``height_mm`` tall with no node scaled; and what was done, for the manifest's reasons.

    A uniform scale about the origin keeps every rotation and multiplies every translation, so a
    joint's rest matrix and its inverse bind matrix stay each other's inverse: positions, the
    joints' translations, the clips' translations and the translation column of each inverse bind
    matrix are multiplied by the factor, and nothing else changes. The mesh nodes on the one skin
    become one mesh whose parts are their primitives, unchanged, on one node at the root of the
    scene; the scene's top node, which carries no transform, is dissolved, so its joints become
    roots of the scene too and no plain node stands between a joint and the scene's root."""
    source = figure.document
    if source.get("animations"):
        raise ImportRefused("the figure carries clips of its own; this import adds them")
    if len(source.get("skins", [])) != 1:
        raise ImportRefused("a figure has one skin")
    nodes = source["nodes"]
    top = _top_node(figure)
    if any(key in nodes[top] for key in ("matrix", "translation", "rotation", "scale")):
        raise ImportRefused("the figure's top node already carries a transform")
    parts = [i for i, node in enumerate(nodes) if "mesh" in node]
    for index in parts:
        node = nodes[index]
        if node.get("skin") != 0 or any(
            key in node for key in ("matrix", "translation", "rotation", "scale", "children")
        ):
            raise ImportRefused("every mesh node is on the one skin, untransformed and childless")
    factor = height_mm / 1000 / _rest_height(figure)
    natural_mm = _rest_height(figure) * 1000
    keep = [i for i in range(len(nodes)) if i not in parts and i != top]
    renumber = {old: new for new, old in enumerate(keep)}
    document = json.loads(json.dumps(source))
    binary = bytearray(figure.binary)
    new_nodes = []
    for old in keep:
        node = json.loads(json.dumps(nodes[old]))
        children = [renumber[child] for child in node.get("children", []) if child in renumber]
        node.pop("children", None)
        if children:
            node["children"] = children
        if "translation" in node:
            node["translation"] = [value * factor for value in node["translation"]]
        new_nodes.append(node)
    primitives = [
        json.loads(json.dumps(primitive))
        for index in parts
        for primitive in source["meshes"][nodes[index]["mesh"]]["primitives"]
    ]
    new_nodes.append({"name": nodes[top].get("name", "figure"), "mesh": 0, "skin": 0})
    roots = [
        len(new_nodes) - 1,
        *(renumber[c] for c in nodes[top].get("children", []) if c in renumber),
    ]
    document["nodes"] = new_nodes
    document["meshes"] = [{"name": nodes[top].get("name", "figure"), "primitives": primitives}]
    document["scenes"] = [{**source["scenes"][0], "nodes": roots}]
    skin = document["skins"][0]
    skin["joints"] = [renumber[joint] for joint in skin["joints"]]
    if "skeleton" in skin:
        skin["skeleton"] = renumber[skin["skeleton"]]
    accessors = document["accessors"]
    scaled: set[int] = set()
    for primitive in primitives:
        index = primitive["attributes"]["POSITION"]
        if index in scaled:
            continue
        scaled.add(index)
        accessor = accessors[index]
        view = document["bufferViews"][accessor["bufferView"]]
        if accessor["componentType"] != _FLOAT or view.get("byteStride", 12) != 12:
            raise ImportRefused("positions are tightly packed float triples")
        base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        moved = [tuple(_f32(x * factor) for x in value) for value in figure.values(index)]
        struct.pack_into(f"<{3 * len(moved)}f", binary, base, *(x for v in moved for x in v))
        accessor["min"] = [min(v[i] for v in moved) for i in range(3)]
        accessor["max"] = [max(v[i] for v in moved) for i in range(3)]
    bind = accessors[skin["inverseBindMatrices"]]
    bind_view = document["bufferViews"][bind["bufferView"]]
    if bind_view.get("byteStride", 64) != 64:
        raise ImportRefused("inverse bind matrices are tightly packed")
    bind_base = bind_view.get("byteOffset", 0) + bind.get("byteOffset", 0)
    for number, matrix in enumerate(figure.values(skin["inverseBindMatrices"])):
        column = list(matrix)
        column[12:15] = [_f32(value * factor) for value in column[12:15]]
        struct.pack_into("<16f", binary, bind_base + 64 * number, *column)
    _align(binary)
    views = document["bufferViews"]

    def append(values: Sequence[Sequence[float]], kind: str, bounds: bool) -> int:
        flat = [float(x) for value in values for x in value]
        _align(binary)
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": 4 * len(flat)})
        binary.extend(struct.pack(f"<{len(flat)}f", *flat))
        accessor: dict[str, Any] = {
            "bufferView": len(views) - 1,
            "componentType": _FLOAT,
            "count": len(values),
            "type": kind,
        }
        if bounds:
            width = len(values[0])
            accessor["min"] = [min(value[i] for value in values) for i in range(width)]
            accessor["max"] = [max(value[i] for value in values) for i in range(width)]
        accessors.append(accessor)
        return len(accessors) - 1

    joints = figure.node_index()
    animations: list[dict[str, Any]] = []
    done: dict[str, Any] = {}
    for wanted in clips:
        clip_file = clip_files[wanted["file"]]
        animation = _animation(clip_file, wanted["clip"])
        if animation is None:
            raise ImportRefused(f"{wanted['file']} has no clip {wanted['clip']!r}")
        names = [node.get("name") for node in clip_file.document["nodes"]]
        inputs: dict[int, int] = {}
        samplers: list[dict[str, Any]] = []
        channels: list[dict[str, Any]] = []
        drift = 0.0
        for channel in animation["channels"]:
            sampler = animation["samplers"][channel["sampler"]]
            target = names[channel["target"]["node"]]
            if target not in joints or joints[target] not in renumber:
                raise ImportRefused(
                    f"clip {wanted['clip']} moves {target!r}, which the figure's skeleton lacks"
                )
            if sampler["input"] not in inputs:
                inputs[sampler["input"]] = append(
                    clip_file.values(sampler["input"]), "SCALAR", True
                )
            values = clip_file.values(sampler["output"])
            path = channel["target"]["path"]
            if path == "translation":
                if target in in_place:
                    x, _, z = values[0]
                    drift = max(drift, *(max(abs(v[0] - x), abs(v[2] - z)) for v in values))
                    values = [(x, v[1], z) for v in values]
                values = [tuple(_f32(value * factor) for value in v) for v in values]
            samplers.append(
                {
                    "input": inputs[sampler["input"]],
                    "interpolation": "LINEAR",
                    "output": append(values, _PATH_WIDTH[path], False),
                }
            )
            channels.append(
                {
                    "sampler": len(samplers) - 1,
                    "target": {"node": renumber[joints[target]], "path": path},
                }
            )
        animations.append({"name": wanted["motion"], "channels": channels, "samplers": samplers})
        done[wanted["clip"]] = {"drift": drift}
    document["animations"] = animations
    _align(binary)
    document["buffers"] = [{"byteLength": len(binary)}]
    document["asset"] = {"generator": PRODUCER, "version": "2.0"}
    payload = write_glb(document, bytes(binary))
    validate_import_container(payload)
    return payload, {
        "factor": factor,
        "natural_mm": natural_mm,
        "parts": len(primitives),
        "clips": done,
    }


def ground_speed_mm_per_s(
    gltf: Gltf, clip: Clip, feet: Sequence[str], stance_mm: int, samples: int
) -> int:
    """The median horizontal speed of ``feet`` while each stands within ``stance_mm`` of its lowest
    point, in whole millimetres a second, at the container's own scale."""
    poses = [
        (clip.seconds * k / samples, joint_positions(gltf, clip, clip.seconds * k / samples))
        for k in range(samples + 1)
    ]
    speeds: list[float] = []
    for foot in feet:
        low = min(pose[foot][1] for _, pose in poses)
        stance = [i for i, (_, pose) in enumerate(poses) if pose[foot][1] <= low + stance_mm / 1000]
        for i in stance:
            if i + 1 in stance:
                (t0, a), (t1, b) = poses[i], poses[i + 1]
                dx, dz = b[foot][0] - a[foot][0], b[foot][2] - a[foot][2]
                speeds.append(math.sqrt(dx * dx + dz * dz) / (t1 - t0))
    if not speeds:
        raise ImportRefused(f"clip {clip.name}: no foot stands still long enough to measure")
    speeds.sort()
    middle = len(speeds) // 2
    median = speeds[middle] if len(speeds) % 2 else (speeds[middle - 1] + speeds[middle]) / 2
    return int(median * 1000 + 0.5)


# -- an object -------------------------------------------------------------------------------------


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def scale_positions(gltf: Gltf, factor: float) -> Gltf:
    """Every mesh position multiplied by ``factor``, as float32, in a copy."""
    document = json.loads(json.dumps(gltf.document))
    binary = bytearray(gltf.binary)
    seen: set[int] = set()
    for mesh in document["meshes"]:
        for primitive in mesh["primitives"]:
            index = primitive["attributes"]["POSITION"]
            if index in seen:
                continue
            seen.add(index)
            accessor = document["accessors"][index]
            view = document["bufferViews"][accessor["bufferView"]]
            if accessor["componentType"] != _FLOAT or view.get("byteStride", 12) != 12:
                raise ImportRefused("positions are tightly packed float triples")
            base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            scaled = [tuple(_f32(x * factor) for x in value) for value in gltf.values(index)]
            struct.pack_into(f"<{3 * len(scaled)}f", binary, base, *(x for v in scaled for x in v))
            accessor["min"] = [min(v[i] for v in scaled) for i in range(3)]
            accessor["max"] = [max(v[i] for v in scaled) for i in range(3)]
    for node in document.get("nodes", []):
        if any(key in node for key in ("matrix", "translation", "rotation", "scale")):
            raise ImportRefused("an object's nodes stand at the origin, untransformed")
    return Gltf(document, bytes(binary))


def _extent(gltf: Gltf) -> tuple[float, float, float]:
    low = [math.inf] * 3
    high = [-math.inf] * 3
    for mesh in gltf.document["meshes"]:
        for primitive in mesh["primitives"]:
            accessor = gltf.document["accessors"][primitive["attributes"]["POSITION"]]
            for i in range(3):
                low[i] = min(low[i], accessor["min"][i])
                high[i] = max(high[i], accessor["max"][i])
    return high[0] - low[0], high[1] - low[1], high[2] - low[2]


def fit_object(
    gltf: Gltf, box_mm: Mapping[str, int], margin_mm: int
) -> tuple[bytes, dict[str, Any]]:
    """The object scaled uniformly to stand inside ``box_mm`` less ``margin_mm`` a side, its
    pictures embedded, prepared as a person's static container is. glTF's X, Y and Z are the
    box's width, height and depth."""
    across, up, deep = _extent(gltf)
    factor = min(
        (box_mm["width"] - 2 * margin_mm) / 1000 / across,
        (box_mm["height"] - 2 * margin_mm) / 1000 / up,
        (box_mm["depth"] - 2 * margin_mm) / 1000 / deep,
    )
    scaled = scale_positions(gltf, factor)
    scaled.document["asset"] = {"generator": PRODUCER, "version": "2.0"}
    prepared = prepare_static_glb(
        write_glb(scaled.document, scaled.binary),
        unit="metre",
        expected_dimensions_mm=None,
        decode_image=decode_texture,
    )
    return prepared.output, {"factor": factor, "dimensions_mm": dict(prepared.dimensions_mm)}


# -- sources ---------------------------------------------------------------------------------------


class Archive:
    """One source pack's archive, read once and held to the digest the import document pins."""

    def __init__(self, path: Path, source: Mapping[str, Any]) -> None:
        data = path.read_bytes()
        if len(data) != source["bytes"] or _sha256(data) != source["sha256"]:
            raise ImportRefused(f"{path} is not the archive the import document pins")
        self._zip = zipfile.ZipFile(io.BytesIO(data))

    def read(self, member: str) -> bytes:
        return self._zip.read(member)


@dataclass(frozen=True, slots=True)
class Read:
    """Every file one look read, by source, path and digest, in the order it read them."""

    archives: Mapping[str, Archive]
    files: list[dict[str, str]]

    def __call__(self, source: str, path: str) -> bytes:
        data = self.archives[source].read(path)
        entry = {"source": source, "path": path, "sha256": _sha256(data)}
        if entry not in self.files:
            self.files.append(entry)
        return data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# -- documents -------------------------------------------------------------------------------------


def _translator() -> dict[str, Any]:
    return {
        "key": TRANSLATOR,
        "version": TRANSLATOR_VERSION,
        "sha256": _sha256(Path(__file__).read_bytes()),
    }


def _revision(source: Mapping[str, Any]) -> str:
    return f"{source['upload']}, {source['archive']} sha256 {source['sha256']}"


def _origin(
    plan: Mapping[str, Any],
    sources: Sequence[str],
    licence_texts: Mapping[str, bytes],
    files: Sequence[Mapping[str, str]],
    manifest_sha256: str,
) -> dict[str, Any]:
    """An imported look's origin: every source it read, the first one's licence text (each
    source's licence is the import document's one licence), and every file it read by digest."""
    stated = plan["sources"]
    creators = []
    for key in sources:
        if stated[key]["creator"] not in creators:
            creators.append(stated[key]["creator"])
    return {
        "profile": "exulanica.origin/v1",
        "class": "imported",
        "by": {"kind": "project"},
        "sources": [
            {
                "reference": stated[key]["reference"],
                "retrieved_on": stated[key]["retrieved_at"][:10],
                "revision": _revision(stated[key]),
                "licence_page_sha256": stated[key]["page_sha256"],
            }
            for key in sources
        ],
        "licence": {
            "spdx": plan["licence"]["spdx"],
            "verdict": "SHIP",
            "attribution": None,
            "share_alike": False,
            "licence_url": plan["licence"]["url"],
            "licence_text_sha256": _sha256(licence_texts[sources[0]]),
        },
        "authors": creators,
        "lineage": {
            "ingredients": sorted({file["sha256"] for file in files}),
            "receipts": [],
            "translation_manifest_sha256": manifest_sha256,
        },
        "distribution": "public",
    }


def _receipt(
    plan: Mapping[str, Any],
    look: Mapping[str, Any],
    source: str,
    container: bytes,
    licence_text: bytes,
) -> dict[str, Any]:
    stated = plan["sources"][source]
    return {
        "profile": "exulanica.reviewed-asset-import/v1",
        "asset_key": f"things.{look['look']}.v{look['version']}",
        "title": f"{stated['title']}: {look['label']}",
        "summary": look["summary"],
        "content_sha256": _sha256(container),
        "byte_size": len(container),
        "licence_id": plan["licence"]["spdx"],
        "licence_sha256": _sha256(licence_text),
        "source_url": stated["reference"],
        "source_revision": _revision(stated),
        "producer": PRODUCER,
    }


MANIFEST_PROFILE: Final = "exulanica.translation-manifest/v2"


def _field(
    path: str, disposition: str, to: str | None, reason: str | None, words: str
) -> dict[str, Any]:
    """One field of a manifest: what became of it, why where it did not come across as it was,
    and a line of words saying what it is and what it became, filled from the data read."""
    return {"path": path, "disposition": disposition, "to": to, "reason": reason, "words": words}


def _counted(count: int, one: str, many: str) -> str:
    """``mesh`` for one, ``9 meshes`` for more: the words a manifest line counts in."""
    return one if count == 1 else f"{count} {many}"


def figure_reading(
    figure: Gltf,
    clip_files: Mapping[str, Gltf],
    natural_mm: float,
    files: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    """The source fields a figure's manifest accounts for: the files read, its joints by parent,
    its meshes, materials and pictures, its height, and every clip of every clip file it read with
    its length in milliseconds."""
    nodes = figure.document["nodes"]
    parent = {
        child: index for index, node in enumerate(nodes) for child in node.get("children", [])
    }
    skinned = {j for skin in figure.document["skins"] for j in skin["joints"]}

    def parent_joint(index: int) -> str | None:
        above = parent.get(index)
        return nodes[above]["name"] if above in skinned else None

    by_name: dict[str, dict[str, int]] = {}
    for file, gltf in sorted(clip_files.items()):
        name = PurePosixPath(file).name
        if name in by_name:
            raise ImportRefused(f"two clip files read are named {name}")
        by_name[name] = {
            str(animation["name"]): round(read_clip(gltf, animation).seconds * 1000)
            for animation in gltf.document.get("animations", [])
        }
    return {
        "files": [dict(file) for file in files],
        "joints": {
            nodes[j]["name"]: parent_joint(j)
            for j in sorted(skinned, key=lambda j: nodes[j]["name"])
        },
        "meshes": sorted(mesh["name"] for mesh in figure.document["meshes"]),
        "materials": sorted(material["name"] for material in figure.document["materials"]),
        "pictures": sorted(image["name"] for image in figure.document.get("images", [])),
        "height_mm": round(natural_mm),
        "clips": by_name,
    }


def _clip_reason(reasons: Mapping[str, Any], file: str, clip: str) -> str:
    if clip in reasons["clips"]:
        return str(reasons["clips"][clip])
    if file in reasons.get("files", {}):
        return str(reasons["files"][file])
    raise ImportRefused(f"clip {clip} of {file} is neither kept nor given a reason")


def figure_manifest(
    look: Mapping[str, Any], reading: Mapping[str, Any], made: Mapping[str, Any]
) -> dict[str, Any]:
    reasons = look["reasons"]
    bone_of = {joint: bone for bone, joint in look["bones"].items()}
    socket_of = {joint: socket for socket, joint in look["sockets"].items()}
    files = _counted(len(reading["files"]), "file", "files")
    fields: list[dict[str, Any]] = [
        _field(
            "/files",
            "exact",
            "/origin/lineage/ingredients",
            None,
            f"the {files} it was read from, each named by digest in its origin",
        )
    ]
    for joint in reading["joints"]:
        at = f"/joints/{joint}"
        if joint in bone_of:
            words = f"its joint {joint} moves the body's {bone_of[joint]} bone"
            fields.append(_field(at, "exact", f"/rig/bones/{bone_of[joint]}", None, words))
        elif joint in socket_of:
            words = f"its joint {joint} is where its {socket_of[joint]} holds things"
            fields.append(_field(at, "exact", f"/rig/sockets/{socket_of[joint]}", None, words))
        elif joint in reasons["joints"]:
            words = f"its joint {joint} stays in the figure and moves with its clips"
            fields.append(_field(at, "approximated", "/container", reasons["joints"][joint], words))
        else:
            raise ImportRefused(f"joint {joint} is neither mapped nor given a reason")
    meshes = _counted(len(reading["meshes"]), "mesh", "meshes")
    parts = _counted(made["parts"], "part", "parts")
    if len(reading["meshes"]) == 1 and made["parts"] == 1:
        fields.append(
            _field("/meshes", "exact", "/container", None, "its mesh came across as it is")
        )
    else:
        fields.append(
            _field(
                "/meshes",
                "approximated",
                "/container",
                f"joined into one skinned mesh of {parts}, so the figure is one mesh on one skin; "
                "no vertex changed but by its height",
                f"its {meshes} came across as one mesh of {parts}",
            )
        )
    for key, one, many in (
        ("materials", "material", "materials"),
        ("pictures", "picture", "pictures"),
    ):
        stated = _counted(len(reading[key]), one, many)
        words = f"its {stated} came across as {'it is' if len(reading[key]) == 1 else 'they are'}"
        fields.append(_field(f"/{key}", "exact", "/container", None, words))
    factor = made["factor"]
    fields.append(
        _field(
            "/height_mm",
            "approximated",
            "/height_mm",
            f"scaled uniformly by {factor:.6f} into its vertices, bind matrices, joints and clips "
            f"to {look['height_mm']} mm, inside a person's height",
            f"it stood {reading['height_mm']:,} mm tall and stands {look['height_mm']:,} mm",
        )
    )
    kept = {
        (PurePosixPath(clip["path"]).name, clip["clip"]): clip["motion"] for clip in look["clips"]
    }
    for file, clips in reading["clips"].items():
        for clip in clips:
            at = f"/clips/{file}/{clip}"
            if (file, clip) in kept:
                motion = kept[(file, clip)]
                drift_mm = made["clips"][clip]["drift"] * factor * 1000
                if drift_mm >= 0.5:
                    fields.append(
                        _field(
                            at,
                            "approximated",
                            f"/rig/clips/{motion}",
                            f"kept in place: its {' and '.join(look['in_place'])} hold their place "
                            f"across the ground, {round(drift_mm)} mm of drift removed",
                            f"its clip {clip} came across as its {motion} clip, kept in place",
                        )
                    )
                else:
                    words = f"its clip {clip} came across as its {motion} clip"
                    fields.append(_field(at, "exact", f"/rig/clips/{motion}", None, words))
            else:
                words = f"its clip {clip} did not come across"
                fields.append(_field(at, "dropped", None, _clip_reason(reasons, file, clip), words))
    return {
        "profile": MANIFEST_PROFILE,
        "translator": _translator(),
        "source": {
            "format": "gltf-binary",
            "type": look["source_type"],
            "sha256": sha256_of_canonical(dict(reading)).hex(),
        },
        "target": {"kind": None, "look": {"look": look["look"], "version": look["version"]}},
        "fields": fields,
    }


def object_reading(gltf: Gltf, files: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    across, up, deep = _extent(gltf)
    return {
        "files": [dict(file) for file in files],
        "meshes": sorted(mesh.get("name", "") for mesh in gltf.document["meshes"]),
        "materials": sorted(
            material.get("name", "") for material in gltf.document.get("materials", [])
        ),
        "pictures": sorted(image.get("name", "") for image in gltf.document.get("images", [])),
        "size_mm": {
            "width": round(across * 1000),
            "depth": round(deep * 1000),
            "height": round(up * 1000),
        },
    }


def object_manifest(
    look: Mapping[str, Any], reading: Mapping[str, Any], made: Mapping[str, Any]
) -> dict[str, Any]:
    box = look["fit_box_mm"]
    size = made["dimensions_mm"]
    was = reading["size_mm"]
    files = _counted(len(reading["files"]), "file", "files")
    fields = [
        _field(
            "/files",
            "exact",
            "/origin/lineage/ingredients",
            None,
            f"the {files} it was read from, each named by digest in its origin",
        )
    ]
    for key, one, many in (
        ("meshes", "mesh", "meshes"),
        ("materials", "material", "materials"),
        ("pictures", "picture", "pictures"),
    ):
        stated = _counted(len(reading[key]), one, many)
        words = f"its {stated} came across as {'it is' if len(reading[key]) == 1 else 'they are'}"
        fields.append(_field(f"/{key}", "exact", "/container", None, words))
    fields.append(
        _field(
            "/size_mm",
            "approximated",
            "/container",
            f"scaled uniformly by {made['factor']:.6f} to {size['width']} x {size['depth']} x "
            f"{size['height']} mm, inside its {box['width']} x {box['depth']} x {box['height']} mm "
            "box",
            f"it measured {was['width']:,} x {was['depth']:,} x {was['height']:,} mm and measures "
            f"{size['width']:,} x {size['depth']:,} x {size['height']:,} mm",
        )
    )
    return {
        "profile": MANIFEST_PROFILE,
        "translator": _translator(),
        "source": {
            "format": "gltf",
            "type": look["source_type"],
            "sha256": sha256_of_canonical(dict(reading)).hex(),
        },
        "target": {"kind": None, "look": {"look": look["look"], "version": look["version"]}},
        "fields": fields,
    }


def look_document(
    look: Mapping[str, Any],
    container: bytes,
    origin: Mapping[str, Any],
    rig: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "profile": "exulanica.look/v1",
        "look": look["look"],
        "version": look["version"],
        "label": look["label"],
        "body_plan": look["body_plan"],
        "look_kind": look["look_kind"],
        "container": {
            "sha256": _sha256(container),
            "bytes": len(container),
            "media_type": "model/gltf-binary",
        },
        "rig": rig,
        "height_mm": look.get("height_mm"),
        "sampling": "linear",
        "light": None,
        "role": None,
        "origin": dict(origin),
    }


# -- the import ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Output:
    path: Path
    data: bytes


def _json_file(path: Path, document: Any) -> Output:
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    return Output(path, text.encode("utf-8"))


def read_plan(path: Path) -> dict[str, Any]:
    plan = json.loads(path.read_text("utf-8"))
    if plan.get("profile") != IMPORT_PROFILE:
        raise ImportRefused(f"{path} is not an {IMPORT_PROFILE} document")
    return plan


def _figure(
    look: Mapping[str, Any], read: Read
) -> tuple[bytes, dict[str, Any], dict[str, Any], dict[str, Any]]:
    figure = read_glb(read(look["figure"]["source"], look["figure"]["path"]))
    clip_files = {
        clip["path"]: read_glb(read(clip["source"], clip["path"])) for clip in look["clips"]
    }
    clips = [
        {"file": clip["path"], "clip": clip["clip"], "motion": clip["motion"]}
        for clip in look["clips"]
    ]
    container, made = merge_figure(figure, clip_files, clips, look["in_place"], look["height_mm"])
    reading = figure_reading(figure, clip_files, made["natural_mm"], read.files)
    merged = read_glb(container)
    speed = look["ground_speed"]
    motions = {clip["motion"]: clip["motion"] for clip in look["clips"]}
    played = {str(a["name"]): read_clip(merged, a) for a in merged.document["animations"]}
    rig = {
        "bones": dict(sorted(look["bones"].items())),
        "clips": motions,
        "sockets": dict(sorted(look["sockets"].items())),
        "ground_speed_mm_per_s": {
            motion: ground_speed_mm_per_s(
                merged, played[motions[motion]], speed["feet"], speed["stance_mm"], speed["samples"]
            )
            for motion in speed["motions"]
        },
    }
    return container, made, reading, rig


def _object(look: Mapping[str, Any], read: Read) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    source_key = look["gltf"]["source"]
    folder = PurePosixPath(look["gltf"]["path"]).parent

    def beside(uri: str) -> bytes:
        return read(source_key, str(folder / uri))

    source = read_gltf(read(source_key, look["gltf"]["path"]), beside)
    container, made = fit_object(source, look["fit_box_mm"], look["fit_margin_mm"])
    return container, made, object_reading(source, read.files)


def make(plan_path: Path, archives: Mapping[str, Archive]) -> list[Output]:
    plan = read_plan(plan_path)
    directory = plan_path.parent
    if set(archives) != set(plan["sources"]):
        raise ImportRefused(f"the import reads sources {sorted(plan['sources'])}")
    licences = {
        key: archives[key].read(source["licence_member"]) for key, source in plan["sources"].items()
    }
    outputs = [
        Output(directory / source["licence_file"], licences[key])
        for key, source in plan["sources"].items()
    ]
    for look in plan["looks"]:
        read = Read(archives, [])
        if look["look_kind"] == "skinned":
            container, made, reading, rig = _figure(look, read)
            manifest = figure_manifest(look, reading, made)
            first = look["figure"]["source"]
        elif look["look_kind"] == "static":
            first = look["gltf"]["source"]
            container, made, reading = _object(look, read)
            manifest = object_manifest(look, reading, made)
            rig = None
        else:
            raise ImportRefused(f"look {look['look']}: a {look['look_kind']} look is not imported")
        sources = [first, *sorted({file["source"] for file in read.files} - {first})]
        origin = _origin(plan, sources, licences, read.files, sha256_of_canonical(manifest).hex())
        document = look_document(look, container, origin, rig)
        canonical_json(document)
        key, version = look["look"], look["version"]
        outputs += [
            Output(directory / f"{key}.glb", container),
            _json_file(
                directory / f"{key}.import.json",
                _receipt(plan, look, first, container, licences[first]),
            ),
            _json_file(directory / f"{key}.source.json", reading),
            _json_file(MANIFESTS / f"{key}.v{version}.json", manifest),
            _json_file(LOOKS / f"{key}.v{version}.json", document),
        ]
    return outputs


def _archives(pairs: Sequence[str], plan: Mapping[str, Any]) -> dict[str, Archive]:
    archives = {}
    for pair in pairs:
        key, _, path = pair.partition("=")
        if key not in plan["sources"] or not path:
            raise ImportRefused(f"--archive {pair}: name one of {sorted(plan['sources'])}=<zip>")
        archives[key] = Archive(Path(path), plan["sources"][key])
    return archives


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("plan", type=Path, help="the import document")
    parser.add_argument(
        "--archive",
        action="append",
        default=[],
        help="<source>=<zip>, once per source the document reads, as it pins each",
    )
    parser.add_argument("--check", action="store_true", help="write nothing; fail on a difference")
    args = parser.parse_args(argv)
    plan_path = args.plan.resolve()
    plan = read_plan(plan_path)
    outputs = make(plan_path, _archives(args.archive, plan))
    if args.check:
        differ = [o.path for o in outputs if not o.path.exists() or o.path.read_bytes() != o.data]
        for path in differ:
            print(f"differs: {path.relative_to(ROOT)}", file=sys.stderr)
        return 1 if differ else 0
    for output in outputs:
        output.path.parent.mkdir(parents=True, exist_ok=True)
        output.path.write_bytes(output.data)
        print(f"wrote {output.path.relative_to(ROOT)} ({len(output.data)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
