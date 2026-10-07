"""Read a skinned look's container, ``exulanica.skinned-glb/v1``, and refuse what it may not be.

A look that bends (a creature's sculpted look, a rigged figure imported from a CC0 pack) is one
binary glTF of a fixed shape, which this reader holds every container to before anything draws
it, the same reader in the product's admission and in the job that makes one:

*   **One skinned mesh.** Exactly one node draws a mesh; it has a skin and no transform, it is a
    root of the one scene, and its mesh holds up to 16 triangle primitives, each with ``POSITION``,
    ``JOINTS_0`` and ``WEIGHTS_0``, a colour (``COLOR_0``, or ``TEXCOORD_0`` with the material's one
    base colour texture) and no morph target. No ``JOINTS_1``: four influences a vertex at most.
*   **The bind pose is the rest pose.** Joints are placed by translation, rotation and scale (never
    a matrix); nothing that is not a joint lies between a joint and the scene's root, so no scale
    or rotation hides above the skeleton; and each joint's inverse bind matrix is the inverse of its
    world matrix at rest, within one part in ten thousand.
*   **Its weights are whole.** Every vertex's joint indices name a joint of the skin, and its four
    weights are not negative and sum to one within one part in a thousand.
*   **Its clips are named by motion and stay in place.** Each animation is named by one of the
    motions a body plan names, moves only joints, and never carries the skeleton's root joint
    across the ground: every key of the root's translation keeps the first key's ground position.
*   **Bounds.** At most 128 joints, 20,000 triangles, 16 primitives, 2 materials, one image of at
    most 1,024 by 1,024 pixels (PNG or JPEG, carried in the binary chunk), 16 clips and 8 MiB; no
    extension and no external file.

:func:`read_skinned_glb` returns what it read (joints, parents, rest positions, counts) and, given a
look's bone map (its ``rig.bones``, ``{plan bone: joint name}``) and the plan's parents, also holds
the joint tree to the plan's: each mapped bone's nearest mapped ancestor joint is the joint of its
plan parent.

Plain Python: no numpy, so the product reads it.
"""

from __future__ import annotations

import json
import math
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica_pieces.canonical import Refused

__all__ = [
    "LIMITS",
    "MOTIONS",
    "PROFILE",
    "SkinnedContainer",
    "SkinnedLimits",
    "read_skinned_glb",
]

PROFILE: Final = "exulanica.skinned-glb/v1"
#: The motions a clip may be named for: a body plan's, as ``exulanica.things.catalogs.MOTIONS``
#: states them (a test holds the two equal; this package may not import the product).
MOTIONS: Final = (
    "idle",
    "walk",
    "run",
    "reach",
    "hold",
    "talk",
    "sit",
    "fly",
    "glide",
    "take_off",
    "land",
)
_MAGIC: Final = 0x46546C67
_JSON: Final = 0x4E4F534A
_BIN: Final = 0x004E4942
_FLOAT: Final = 5126
_UBYTE: Final = 5121
_USHORT: Final = 5123
_UINT: Final = 5125
_COMPONENTS: Final = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_FORMAT: Final = {_FLOAT: "f", _UBYTE: "B", _USHORT: "H", _UINT: "I"}
_NORMALISER: Final = {_UBYTE: 255, _USHORT: 65535}
_ALLOWED_ATTRIBUTES: Final = frozenset(
    {"POSITION", "NORMAL", "COLOR_0", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0"}
)
#: How far a joint's inverse bind matrix may be from the inverse of its rest world matrix, in
#: each element of their product's difference from the identity.
_BIND_TOLERANCE: Final = 1e-4
#: How far a vertex's four weights may sum from one.
_WEIGHT_TOLERANCE: Final = 1e-3
#: How far, in metres, a root joint's translation keys may wander across the ground from the first.
_IN_PLACE_TOLERANCE: Final = 1e-3


@dataclass(frozen=True, slots=True)
class SkinnedLimits:
    """What one skinned container may hold. Declared bounds: the browser's skinning joint limit,
    the triangles one creature may cost the near frame budget, and the sizes a look may weigh."""

    joints: int = 128
    triangles: int = 20_000
    primitives: int = 16
    materials: int = 2
    image_side_px: int = 1024
    clips: int = 16
    bytes: int = 8 * 1024 * 1024


LIMITS: Final = SkinnedLimits()


@dataclass(frozen=True, slots=True)
class SkinnedContainer:
    """What a container was read as: its joints in skin order, each joint's parent joint (none for
    the root), each joint's rest position in the container's own metres (glTF's frame), and its
    counts."""

    joints: tuple[str, ...]
    parents: Mapping[str, str | None]
    rest_m: Mapping[str, tuple[float, float, float]]
    vertices: int
    triangles: int
    primitives: int
    materials: int
    image_px: tuple[int, int] | None
    clips: tuple[str, ...]
    bytes: int


def _refuse(message: str) -> Refused:
    return Refused(f"{PROFILE}: {message}")


def _chunks(data: bytes, limits: SkinnedLimits) -> tuple[dict[str, Any], bytes]:
    if len(data) > limits.bytes:
        raise _refuse(f"{len(data)} bytes, more than {limits.bytes}")
    if len(data) < 20:
        raise _refuse("too short to be a binary glTF")
    magic, version, total = struct.unpack_from("<III", data, 0)
    if magic != _MAGIC or version != 2 or total != len(data):
        raise _refuse("not a binary glTF 2.0 of its stated length")
    length, kind = struct.unpack_from("<II", data, 12)
    if kind != _JSON or 20 + length > len(data):
        raise _refuse("its first chunk is not JSON")
    try:
        document = json.loads(data[20 : 20 + length])
    except ValueError as exc:
        raise _refuse(f"its JSON does not parse: {exc}") from exc
    if not isinstance(document, dict):
        raise _refuse("its JSON is not an object")
    offset = 20 + length
    binary = b""
    if offset < len(data):
        if offset + 8 > len(data):
            raise _refuse("its binary chunk is cut short")
        length, kind = struct.unpack_from("<II", data, offset)
        if kind != _BIN or offset + 8 + length != len(data):
            raise _refuse("its second chunk is not the binary chunk, or chunks follow it")
        binary = data[offset + 8 : offset + 8 + length]
    return document, binary


def _list(document: Mapping[str, Any], name: str) -> list[Any]:
    value = document.get(name, [])
    if not isinstance(value, list):
        raise _refuse(f"{name} is a list")
    return value


def _index(value: Any, length: int, where: str) -> int:
    if type(value) is not int or not 0 <= value < length:
        raise _refuse(f"{where} names one of {length}")
    return value


class _Accessors:
    """Every accessor's values, read from its buffer view with bounds checked."""

    def __init__(self, document: Mapping[str, Any], binary: bytes) -> None:
        self._accessors = _list(document, "accessors")
        self._views = _list(document, "bufferViews")
        self._binary = binary
        buffers = _list(document, "buffers")
        if len(buffers) > 1 or any("uri" in buffer for buffer in buffers):
            raise _refuse("one buffer at most, the binary chunk, and no external file")
        if buffers and buffers[0].get("byteLength", 0) > len(binary):
            raise _refuse("its buffer is longer than its binary chunk")

    def accessor(self, index: Any, where: str) -> Mapping[str, Any]:
        return self._accessors[_index(index, len(self._accessors), where)]

    def values(self, index: Any, where: str) -> tuple[list[tuple[float, ...]], Mapping[str, Any]]:
        accessor = self.accessor(index, where)
        if "sparse" in accessor:
            raise _refuse(f"{where} is sparse")
        kind = accessor.get("type")
        component = accessor.get("componentType")
        if kind not in _COMPONENTS or component not in _FORMAT:
            raise _refuse(f"{where} has a type or component this profile does not read")
        count = accessor.get("count")
        if type(count) is not int or count < 0:
            raise _refuse(f"{where}.count is a whole number")
        width = _COMPONENTS[kind]
        view = self._views[
            _index(accessor.get("bufferView"), len(self._views), f"{where}.bufferView")
        ]
        start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        size = struct.calcsize(_FORMAT[component])
        stride = view.get("byteStride") or size * width
        end = start + (stride * (count - 1) + size * width if count else 0)
        if end > view.get("byteOffset", 0) + view.get("byteLength", 0) or end > len(self._binary):
            raise _refuse(f"{where} reads past its buffer view")
        values = []
        packed = f"<{width}{_FORMAT[component]}"
        for item in range(count):
            values.append(struct.unpack_from(packed, self._binary, start + item * stride))
        return values, accessor


def _image_px(data: bytes, mime: str) -> tuple[int, int]:
    if mime == "image/png":
        if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            raise _refuse("its image is not a PNG")
        width, height = struct.unpack_from(">II", data, 16)
        return width, height
    if mime == "image/jpeg":
        position = 2
        while position + 9 < len(data):
            if data[position] != 0xFF:
                raise _refuse("its image is not a JPEG")
            marker = data[position + 1]
            length = struct.unpack_from(">H", data, position + 2)[0]
            if marker in (0xC0, 0xC1, 0xC2):
                height, width = struct.unpack_from(">HH", data, position + 5)
                return width, height
            position += 2 + length
        raise _refuse("its JPEG states no size")
    raise _refuse("its image is a PNG or a JPEG")


def _quaternion_matrix(q: Sequence[float]) -> list[list[float]]:
    x, y, z, w = q
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def _local(node: Mapping[str, Any], where: str) -> list[list[float]]:
    if "matrix" in node:
        raise _refuse(
            f"{where} is placed by a matrix; joints are placed by translation, rotation and scale"
        )
    t = node.get("translation", [0.0, 0.0, 0.0])
    r = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    s = node.get("scale", [1.0, 1.0, 1.0])
    for name, value, length in (("translation", t, 3), ("rotation", r, 4), ("scale", s, 3)):
        if (
            not isinstance(value, list)
            or len(value) != length
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in value)
        ):
            raise _refuse(f"{where}.{name} is {length} finite numbers")
    if abs(math.sqrt(sum(v * v for v in r)) - 1) > 1e-4:
        raise _refuse(f"{where}.rotation is a unit quaternion")
    if any(v <= 0 for v in s):
        raise _refuse(f"{where}.scale is positive")
    rotation = _quaternion_matrix(r)
    return [
        [rotation[0][0] * s[0], rotation[0][1] * s[1], rotation[0][2] * s[2], t[0]],
        [rotation[1][0] * s[0], rotation[1][1] * s[1], rotation[1][2] * s[2], t[1]],
        [rotation[2][0] * s[0], rotation[2][1] * s[1], rotation[2][2] * s[2], t[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _multiply(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _is_identity(node: Mapping[str, Any]) -> bool:
    return not any(key in node for key in ("matrix", "translation", "rotation", "scale")) or (
        node.get("translation", [0, 0, 0]) == [0, 0, 0]
        and node.get("rotation", [0, 0, 0, 1]) == [0, 0, 0, 1]
        and node.get("scale", [1, 1, 1]) == [1, 1, 1]
        and "matrix" not in node
    )


def read_skinned_glb(
    data: bytes,
    *,
    bones: Mapping[str, str] | None = None,
    plan_parents: Mapping[str, str | None] | None = None,
    limits: SkinnedLimits = LIMITS,
) -> SkinnedContainer:
    """``data`` as a skinned look's container, every rule of :data:`PROFILE` held, or
    :class:`~exulanica_pieces.canonical.Refused` naming the first it breaks. With ``bones`` (a
    look's ``rig.bones``, ``{plan bone: joint name}``, not the whole ``rig`` with its clips and
    sockets) and ``plan_parents`` (each plan bone's parent), the joint tree is also held to the
    plan's."""
    if (bones is None) != (plan_parents is None):
        raise TypeError("bones and plan_parents are given together")
    if bones is not None and not all(
        isinstance(bone, str) and isinstance(joint, str) for bone, joint in bones.items()
    ):
        raise TypeError("bones maps each plan bone to a joint name: a look's rig.bones")
    document, binary = _chunks(data, limits)
    if document.get("extensionsUsed") or document.get("extensionsRequired"):
        raise _refuse("it uses an extension")
    asset = document.get("asset")
    if not isinstance(asset, dict) or asset.get("version") != "2.0":
        raise _refuse("asset.version is 2.0")
    accessors = _Accessors(document, binary)
    nodes = _list(document, "nodes")
    scenes = _list(document, "scenes")
    if len(scenes) != 1:
        raise _refuse("it has exactly one scene")
    roots = scenes[0].get("nodes", [])
    parent_of: dict[int, int | None] = {}
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise _refuse(f"nodes[{index}] is an object")
        for child in node.get("children", []):
            child = _index(child, len(nodes), f"nodes[{index}].children")
            if child in parent_of:
                raise _refuse(f"nodes[{child}] has one parent")
            parent_of[child] = index
    for root in roots:
        if _index(root, len(nodes), "scenes[0].nodes") in parent_of:
            raise _refuse("a scene root is no node's child")
    # The one skinned mesh node.
    drawn = [index for index, node in enumerate(nodes) if "mesh" in node]
    if len(drawn) != 1:
        raise _refuse(f"exactly one node draws a mesh; {len(drawn)} do")
    mesh_node = nodes[drawn[0]]
    if "skin" not in mesh_node or not _is_identity(mesh_node) or drawn[0] in parent_of:
        raise _refuse("the mesh node has a skin, no transform, and is a root of the scene")
    if drawn[0] not in roots:
        raise _refuse("the mesh node is in the scene")
    skins = _list(document, "skins")
    if len(skins) != 1:
        raise _refuse("it has exactly one skin")
    skin = skins[0]
    joints = skin.get("joints")
    if not isinstance(joints, list) or not joints or len(joints) > limits.joints:
        raise _refuse(f"its skin names 1 to {limits.joints} joints")
    joints = [_index(joint, len(nodes), "skin.joints") for joint in joints]
    if len(set(joints)) != len(joints):
        raise _refuse("its skin names each joint once")
    joint_set = set(joints)
    names = [nodes[joint].get("name") for joint in joints]
    if any(type(name) is not str or not name for name in names) or len(set(names)) != len(names):
        raise _refuse("every joint has a name of its own")
    # Nothing that is not a joint lies between a joint and the scene's root.
    for joint in joints:
        above = parent_of.get(joint)
        while above is not None:
            if above not in joint_set:
                raise _refuse(
                    f"joint {nodes[joint]['name']} lies under a node that is not a joint; bake its "
                    "transform into the skeleton"
                )
            above = parent_of.get(above)
    # The bind pose is the rest pose.
    world: dict[int, list[list[float]]] = {}

    def world_of(index: int) -> list[list[float]]:
        if index not in world:
            local = _local(nodes[index], f"joint {nodes[index]['name']}")
            above = parent_of.get(index)
            world[index] = local if above is None else _multiply(world_of(above), local)
        return world[index]

    binds, accessor = accessors.values(skin.get("inverseBindMatrices"), "skin.inverseBindMatrices")
    if (
        accessor.get("type") != "MAT4"
        or accessor.get("componentType") != _FLOAT
        or len(binds) != len(joints)
    ):
        raise _refuse("its inverse bind matrices are one float MAT4 a joint")
    for joint, bind in zip(joints, binds, strict=True):
        matrix = [[bind[column * 4 + row] for column in range(4)] for row in range(4)]
        product = _multiply(matrix, world_of(joint))
        for row in range(4):
            for column in range(4):
                expected = 1.0 if row == column else 0.0
                if abs(product[row][column] - expected) > _BIND_TOLERANCE:
                    raise _refuse(
                        f"joint {nodes[joint]['name']}'s inverse bind matrix is not the inverse of "
                        "its rest pose"
                    )
    # The mesh.
    meshes = _list(document, "meshes")
    mesh = meshes[_index(mesh_node["mesh"], len(meshes), "the mesh node's mesh")]
    primitives = mesh.get("primitives", [])
    if not isinstance(primitives, list) or not 1 <= len(primitives) <= limits.primitives:
        raise _refuse(f"its mesh holds 1 to {limits.primitives} primitives")
    if len(meshes) != 1:
        raise _refuse("it has exactly one mesh")
    materials = _list(document, "materials")
    if len(materials) > limits.materials:
        raise _refuse(f"at most {limits.materials} materials")
    images = _list(document, "images")
    image_px = None
    if len(images) > 1 or len(_list(document, "textures")) > 1:
        raise _refuse("one image at most, the base colour texture")
    if images:
        image = images[0]
        if "uri" in image or "bufferView" not in image:
            raise _refuse("its image is carried in the binary chunk")
        views = _list(document, "bufferViews")
        view = views[_index(image["bufferView"], len(views), "images[0].bufferView")]
        start = view.get("byteOffset", 0)
        image_px = _image_px(
            binary[start : start + view.get("byteLength", 0)], str(image.get("mimeType"))
        )
        if max(image_px) > limits.image_side_px:
            raise _refuse(f"its image is at most {limits.image_side_px} pixels a side")
    vertices = 0
    triangles = 0
    for number, primitive in enumerate(primitives):
        where = f"primitives[{number}]"
        if primitive.get("mode", 4) != 4:
            raise _refuse(f"{where} draws triangles")
        if "targets" in primitive:
            raise _refuse(f"{where} has a morph target")
        attributes = primitive.get("attributes", {})
        if set(attributes) - _ALLOWED_ATTRIBUTES:
            raise _refuse(f"{where} has attributes beyond {sorted(_ALLOWED_ATTRIBUTES)}")
        for needed in ("POSITION", "JOINTS_0", "WEIGHTS_0"):
            if needed not in attributes:
                raise _refuse(f"{where} has {needed}")
        if "COLOR_0" not in attributes and "TEXCOORD_0" not in attributes:
            raise _refuse(f"{where} is coloured by COLOR_0 or by a texture through TEXCOORD_0")
        if "material" in primitive:
            _index(primitive["material"], len(materials), f"{where}.material")
        positions, _ = accessors.values(attributes["POSITION"], f"{where}.POSITION")
        if any(not math.isfinite(value) for position in positions for value in position):
            raise _refuse(f"{where} has a position that is not finite")
        count = len(positions)
        joint_values, joint_accessor = accessors.values(attributes["JOINTS_0"], f"{where}.JOINTS_0")
        weight_values, weight_accessor = accessors.values(
            attributes["WEIGHTS_0"], f"{where}.WEIGHTS_0"
        )
        if joint_accessor.get("type") != "VEC4" or weight_accessor.get("type") != "VEC4":
            raise _refuse(f"{where}'s joints and weights are four a vertex")
        if len(joint_values) != count or len(weight_values) != count:
            raise _refuse(f"{where} states joints and weights for every vertex")
        normaliser = 1
        if weight_accessor.get("componentType") != _FLOAT:
            if not weight_accessor.get("normalized"):
                raise _refuse(f"{where}.WEIGHTS_0 is float or normalized")
            normaliser = _NORMALISER[weight_accessor["componentType"]]
        for vertex, (named, weights) in enumerate(zip(joint_values, weight_values, strict=True)):
            if any(type(joint) is not int or joint >= len(joints) for joint in named):
                raise _refuse(f"{where} vertex {vertex} names a joint the skin does not hold")
            values = [weight / normaliser for weight in weights]
            if any(value < 0 for value in values) or abs(sum(values) - 1) > _WEIGHT_TOLERANCE:
                raise _refuse(f"{where} vertex {vertex}'s weights are not whole")
        if "indices" in primitive:
            indices, _ = accessors.values(primitive["indices"], f"{where}.indices")
            flat = [value for (value,) in indices]
            if len(flat) % 3 or any(value >= count for value in flat):
                raise _refuse(f"{where}'s indices are triangles of its own vertices")
            triangles += len(flat) // 3
        else:
            if count % 3:
                raise _refuse(f"{where}'s vertices are whole triangles")
            triangles += count // 3
        vertices += count
    if triangles > limits.triangles:
        raise _refuse(f"{triangles} triangles, more than {limits.triangles}")
    # Clips.
    animations = _list(document, "animations")
    if len(animations) > limits.clips:
        raise _refuse(f"at most {limits.clips} clips")
    roots_of_skeleton = [joint for joint in joints if parent_of.get(joint) not in joint_set]
    clips = []
    for number, animation in enumerate(animations):
        name = animation.get("name")
        if name not in MOTIONS or name in clips:
            raise _refuse(f"animations[{number}] is named once, by one of {list(MOTIONS)}")
        clips.append(name)
        samplers = animation.get("samplers", [])
        for channel in animation.get("channels", []):
            target = channel.get("target", {})
            node = target.get("node")
            if node not in joint_set:
                raise _refuse(f"clip {name} moves only joints")
            if target.get("path") not in ("translation", "rotation", "scale"):
                raise _refuse(f"clip {name} moves joints by translation, rotation or scale")
            if target["path"] == "translation" and node in roots_of_skeleton:
                sampler = samplers[_index(channel.get("sampler"), len(samplers), f"clip {name}")]
                keys, _ = accessors.values(sampler.get("output"), f"clip {name} output")
                if keys and any(
                    abs(key[0] - keys[0][0]) > _IN_PLACE_TOLERANCE
                    or abs(key[2] - keys[0][2]) > _IN_PLACE_TOLERANCE
                    for key in keys
                ):
                    raise _refuse(f"clip {name} carries the skeleton's root across the ground")
    named = {joint: nodes[joint]["name"] for joint in joints}
    parents = {
        named[joint]: (named[parent_of[joint]] if parent_of.get(joint) in joint_set else None)
        for joint in joints
    }
    if bones is not None and plan_parents is not None:
        _hold_to_plan(bones, plan_parents, parents)
    return SkinnedContainer(
        joints=tuple(named[joint] for joint in joints),
        parents=parents,
        rest_m={
            named[joint]: tuple(world_of(joint)[row][3] for row in range(3)) for joint in joints
        },  # type: ignore[misc]
        vertices=vertices,
        triangles=triangles,
        primitives=len(primitives),
        materials=len(materials),
        image_px=image_px,
        clips=tuple(clips),
        bytes=len(data),
    )


def _hold_to_plan(
    bones: Mapping[str, str],
    plan_parents: Mapping[str, str | None],
    parents: Mapping[str, str | None],
) -> None:
    """Each mapped plan bone's nearest mapped ancestor joint is the joint its plan parent maps
    to."""
    mapped = {joint: bone for bone, joint in bones.items()}
    for bone, joint in bones.items():
        if joint not in parents:
            raise _refuse(f"the bone map maps {bone} to {joint}, which the skin does not hold")
        above = parents[joint]
        while above is not None and above not in mapped:
            above = parents[above]
        plan_parent = plan_parents.get(bone)
        while plan_parent is not None and plan_parent not in bones:
            plan_parent = plan_parents.get(plan_parent)
        expected = None if plan_parent is None else bones[plan_parent]
        if above != expected:
            raise _refuse(f"joint {joint} ({bone}) does not hang from its plan parent's joint")
