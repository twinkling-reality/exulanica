"""Independent checks of a prepared character body: container, rig, motion, deformation, budget.

A parametric family's bodies are fitted by a preparer this repository runs as a separate process
(:mod:`exulanica.world.character_preparation`). What the preparer says about its output is not
believed: every number a saved look or the renderer later relies on is measured here from the
container's own bytes, with the standard library only, and a body that fails a check is refused
with the class of the failure. A refusal is the capability being unavailable for that recipe; it is
never repaired, substituted or drawn anyway.

What is measured, in the glTF 2.0 convention (+Y up, the skinned mesh placed by its joints alone):

* **Container.** The reviewed-asset boundary of
  :func:`~exulanica.world.asset_import.validate_import_container`.
* **Rig.** Exactly one skin whose joint names are the family's declared joints, invertible inverse
  bind matrices, and every mesh bound to it with at most four influences per vertex whose weights
  are non-negative and sum to one.
* **Motion.** Each declared clip exists once, with linear or step keys and a real duration.
* **Deformation.** Skinned positions at the idle frame for every vertex and at fixed times through
  walk and run for a deterministic sample: finite, never farther from the hips than the body is
  tall, never collapsed or stretched beyond declared ratios, and standing on the ground at idle.
* **Budget.** Bytes, triangles, vertices, joints, images and image sizes within declared bounds.

Every measurement is an integer in its field's unit, because the receipt it goes into is a digest
input (:mod:`exulanica.canonical`).
"""

from __future__ import annotations

import json
import math
import statistics
import struct
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from itertools import pairwise
from typing import Any, Final

from exulanica.world.asset_import import validate_import_container

__all__ = [
    "BodyBudget",
    "BodyDeclaration",
    "BodyMeasurements",
    "BodyRefused",
    "measure_prepared_body",
    "rest_bounds_mm",
]

#: Failure classes a body check answers, as the preparation queue records them.
FAILURE_CLASSES: Final = frozenset(
    {"unverified_output", "rig_incompatible", "deformation_invalid", "over_budget"}
)
_COMPONENTS: Final = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
_WIDTHS: Final = {"b": 1, "B": 1, "h": 2, "H": 2, "I": 4, "f": 4}
_NORMALISING: Final = {"b": 127.0, "B": 255.0, "h": 32767.0, "H": 65535.0}
_SIZES: Final = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
#: Frames per second a clip is sampled at for gait calibration, as the preparer bakes them.
_FPS: Final = 24
#: How many vertices the moving-frame deformation check skins per frame, at most.
_SAMPLED_VERTICES: Final = 4000
#: Sample times through a moving clip, as shares of its duration.
_CLIP_SHARES: Final = (0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875)
_WEIGHT_TOLERANCE: Final = 0.01


class BodyRefused(ValueError):
    """A prepared body failed a check; ``failure_class`` names which kind, ``code`` which one."""

    def __init__(self, failure_class: str, code: str, detail: str = "") -> None:
        if failure_class not in FAILURE_CLASSES:
            raise ValueError(f"unknown body failure class {failure_class}")
        self.failure_class, self.code, self.detail = failure_class, code, detail
        super().__init__(f"{failure_class}: {code}" + (f": {detail}" if detail else ""))


@dataclass(frozen=True, slots=True)
class BodyBudget:
    """Declared bounds a prepared body must fit, each in the unit its name says."""

    max_bytes: int
    max_triangles: int
    max_vertices: int
    max_joints: int
    max_images: int
    max_image_pixels: int


@dataclass(frozen=True, slots=True)
class BodyDeclaration:
    """What the family says a body prepared for one recipe must be."""

    joints: tuple[str, ...]
    #: Clip role (``idle``, ``walk``, ``run``) to its animation name.
    clips: Mapping[str, str]
    height_cm: int
    #: Material names the recipe's choices require, such as ``Skin`` and ``Hair``.
    materials: frozenset[str]
    budget: BodyBudget
    #: The joint the deformation checks measure distances from.
    hips: str
    #: The two joints gait calibration follows.
    feet: tuple[str, str]
    #: Largest and smallest skinned height while moving, in thousandths of the rest height.
    moving_height_milli: tuple[int, int] = (600, 1100)
    #: Farthest any vertex may be from the hips, in thousandths of the rest height.
    reach_milli: int = 1200
    #: Largest idle floor offset from the ground plane, in millimetres once scaled.
    idle_floor_mm: int = 50


@dataclass(frozen=True, slots=True)
class BodyMeasurements:
    """Everything measured about one accepted body. Integers only."""

    byte_size: int
    triangles: int
    vertices: int
    joints: int
    images: int
    max_image_pixels: int
    #: Height of the body mesh at rest, millionths of the asset's own unit.
    native_rest_height_millionths: int
    #: Metres per asset unit that makes the rest height the recipe's height, in millionths.
    unit_scale_millionths: int
    #: Lowest skinned point at the idle clip's first frame, millionths of the asset's unit.
    native_idle_floor_millionths: int
    #: Skinned standing height at the idle clip's first frame, millionths of the asset's unit.
    native_idle_height_millionths: int
    idle_ms: int
    walk_ms: int
    run_ms: int
    #: Ground speed of a planted foot, once scaled, in millimetres per second.
    walk_speed_mm_per_s: int
    run_speed_mm_per_s: int
    #: Largest distance of a sampled vertex from the hips while moving, thousandths of rest height.
    max_reach_milli: int
    #: Smallest and largest skinned height while moving, thousandths of rest height.
    min_moving_height_milli: int
    max_moving_height_milli: int
    #: Largest departure of a vertex's weights from summing to one, in millionths.
    max_weight_error_millionths: int
    sampled_vertices: int

    def document(self) -> dict[str, int]:
        return asdict(self)


# -- the container --------------------------------------------------------------------------------


def _chunks(payload: bytes) -> tuple[dict[str, Any], bytes]:
    try:
        validate_import_container(payload)
    except (ValueError, UnicodeDecodeError) as exc:
        raise BodyRefused("unverified_output", "malformed_container", str(exc)) from exc
    length = struct.unpack_from("<I", payload, 12)[0]
    document = json.loads(payload[20 : 20 + length].decode("utf-8"))
    offset = 20 + length
    binary = b""
    if offset < len(payload):
        binary_length = struct.unpack_from("<I", payload, offset)[0]
        binary = payload[offset + 8 : offset + 8 + binary_length]
    return document, binary


def _accessor(document: Mapping[str, Any], binary: bytes, index: int) -> list[tuple[float, ...]]:
    try:
        accessor = document["accessors"][index]
        if "sparse" in accessor:
            raise BodyRefused("unverified_output", "sparse_accessor")
        fmt = _COMPONENTS[accessor["componentType"]]
        width = _SIZES[accessor["type"]]
        view = document["bufferViews"][accessor["bufferView"]]
        if view.get("buffer", 0) != 0:
            raise BodyRefused("unverified_output", "external_buffer")
        count = accessor["count"]
        element = _WIDTHS[fmt] * width
        stride = view.get("byteStride") or element
        start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        end = view.get("byteOffset", 0) + view["byteLength"]
    except (KeyError, IndexError, TypeError) as exc:
        raise BodyRefused("unverified_output", "malformed_accessor", str(index)) from exc
    if count < 0 or stride < element or (count and start + stride * (count - 1) + element > end):
        raise BodyRefused("unverified_output", "accessor_out_of_bounds", str(index))
    if end > len(binary):
        raise BodyRefused("unverified_output", "accessor_out_of_bounds", str(index))
    layout = "<" + fmt * width
    if stride == element:
        values = list(struct.iter_unpack(layout, binary[start : start + element * count]))
    else:
        values = [struct.unpack_from(layout, binary, start + i * stride) for i in range(count)]
    if accessor.get("normalized") and fmt in _NORMALISING:
        scale = _NORMALISING[fmt]
        values = [tuple(max(v / scale, -1.0) for v in row) for row in values]
    return values


# -- transforms (column-major, as glTF stores them) --------------------------------------------

_IDENTITY: Final = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def _multiply(a: Sequence[float], b: Sequence[float]) -> tuple[float, ...]:
    return tuple(
        a[r] * b[c * 4]
        + a[4 + r] * b[c * 4 + 1]
        + a[8 + r] * b[c * 4 + 2]
        + a[12 + r] * b[c * 4 + 3]
        for c in range(4)
        for r in range(4)
    )


def _compose(t: Sequence[float], q: Sequence[float], s: Sequence[float]) -> tuple[float, ...]:
    x, y, z, w = q
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz, wx, wy, wz = x * y, x * z, y * z, w * x, w * y, w * z
    return (
        (1 - 2 * (yy + zz)) * s[0], 2 * (xy + wz) * s[0], 2 * (xz - wy) * s[0], 0.0,
        2 * (xy - wz) * s[1], (1 - 2 * (xx + zz)) * s[1], 2 * (yz + wx) * s[1], 0.0,
        2 * (xz + wy) * s[2], 2 * (yz - wx) * s[2], (1 - 2 * (xx + yy)) * s[2], 0.0,
        t[0], t[1], t[2], 1.0,
    )  # fmt: skip


def _apply(m: Sequence[float], p: Sequence[float]) -> tuple[float, float, float]:
    return (
        m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12],
        m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13],
        m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14],
    )


def _determinant3(m: Sequence[float]) -> float:
    return (
        m[0] * (m[5] * m[10] - m[9] * m[6])
        - m[4] * (m[1] * m[10] - m[9] * m[2])
        + m[8] * (m[1] * m[6] - m[5] * m[2])
    )


def _slerp(a: Sequence[float], b: Sequence[float], u: float) -> tuple[float, ...]:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    if dot < 0:
        b, dot = tuple(-v for v in b), -dot
    if dot > 0.9995:
        mixed = tuple(x + (y - x) * u for x, y in zip(a, b, strict=True))
    else:
        theta = math.acos(min(1.0, dot))
        sa, sb = math.sin((1 - u) * theta), math.sin(u * theta)
        mixed = tuple((x * sa + y * sb) / math.sin(theta) for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(v * v for v in mixed)) or 1.0
    return tuple(v / norm for v in mixed)


class _Pose:
    """World matrices of every node at one time of one animation (or at rest when None)."""

    def __init__(self, scene: _Scene, animation: Mapping[str, Any] | None, time: float) -> None:
        local: dict[int, tuple[float, ...]] = {}
        overrides: dict[tuple[int, str], tuple[float, ...]] = {}
        if animation is not None:
            for channel in animation["channels"]:
                target = channel["target"]
                sampler = animation["samplers"][channel["sampler"]]
                overrides[(target["node"], target["path"])] = scene.sample(
                    sampler, time, target["path"]
                )
        for index, node in enumerate(scene.nodes):
            if "matrix" in node and not any(
                (index, p) in overrides for p in ("translation", "rotation", "scale")
            ):
                local[index] = tuple(float(v) for v in node["matrix"])
                continue
            t = overrides.get(
                (index, "translation"), tuple(node.get("translation", (0.0, 0.0, 0.0)))
            )
            q = overrides.get(
                (index, "rotation"), tuple(node.get("rotation", (0.0, 0.0, 0.0, 1.0)))
            )
            s = overrides.get((index, "scale"), tuple(node.get("scale", (1.0, 1.0, 1.0))))
            local[index] = _compose(t, q, s)
        self.world: dict[int, tuple[float, ...]] = {}
        for root in scene.roots:
            stack = [(root, _IDENTITY)]
            while stack:
                index, parent = stack.pop()
                matrix = _multiply(parent, local[index])
                self.world[index] = matrix
                stack.extend((child, matrix) for child in scene.nodes[index].get("children", ()))


@dataclass
class _Primitive:
    positions: list[tuple[float, ...]]
    joints: list[tuple[float, ...]]
    weights: list[tuple[float, ...]]
    triangles: int
    material: str | None


class _Scene:
    def __init__(self, document: Mapping[str, Any], binary: bytes) -> None:
        self.document, self.binary = document, binary
        self.nodes: list[Mapping[str, Any]] = document.get("nodes", [])
        children = {c for node in self.nodes for c in node.get("children", ())}
        if any(not 0 <= c < len(self.nodes) for c in children):
            raise BodyRefused("unverified_output", "malformed_hierarchy")
        self.roots = [i for i in range(len(self.nodes)) if i not in children]
        self._times: dict[int, list[float]] = {}
        self._values: dict[int, list[tuple[float, ...]]] = {}

    def keys(self, sampler: Mapping[str, Any]) -> tuple[list[float], list[tuple[float, ...]]]:
        inputs, outputs = sampler["input"], sampler["output"]
        if inputs not in self._times:
            self._times[inputs] = [row[0] for row in _accessor(self.document, self.binary, inputs)]
        if outputs not in self._values:
            self._values[outputs] = _accessor(self.document, self.binary, outputs)
        return self._times[inputs], self._values[outputs]

    def sample(self, sampler: Mapping[str, Any], time: float, path: str) -> tuple[float, ...]:
        mode = sampler.get("interpolation", "LINEAR")
        if mode not in ("LINEAR", "STEP"):
            raise BodyRefused("unverified_output", "interpolation_not_admitted", mode)
        times, values = self.keys(sampler)
        if not times or len(times) != len(values):
            raise BodyRefused("unverified_output", "malformed_animation")
        if time <= times[0]:
            return values[0]
        if time >= times[-1]:
            return values[-1]
        upper = next(i for i, t in enumerate(times) if t > time)
        lower = upper - 1
        if mode == "STEP":
            return values[lower]
        span = times[upper] - times[lower]
        u = 0.0 if span <= 0 else (time - times[lower]) / span
        if path == "rotation":
            return _slerp(values[lower], values[upper], u)
        return tuple(a + (b - a) * u for a, b in zip(values[lower], values[upper], strict=True))

    def duration(self, animation: Mapping[str, Any]) -> float:
        return max(self.keys(sampler)[0][-1] for sampler in animation["samplers"])


# -- the checks ----------------------------------------------------------------------------------


def _png_pixels(data: bytes) -> int:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise BodyRefused("unverified_output", "image_not_png")
    width, height = struct.unpack(">II", data[16:24])
    return width * height


def _skin(
    joint_matrices: Sequence[Sequence[float]], primitive: _Primitive, indices: Sequence[int]
) -> list[tuple[float, float, float]]:
    skinned = []
    for i in indices:
        x = y = z = 0.0
        position = primitive.positions[i]
        for joint, weight in zip(primitive.joints[i], primitive.weights[i], strict=True):
            if weight:
                px, py, pz = _apply(joint_matrices[int(joint)], position)
                x, y, z = x + weight * px, y + weight * py, z + weight * pz
        skinned.append((x, y, z))
    return skinned


def _gait_speed(scene: _Scene, animation: Mapping[str, Any], feet: Sequence[int]) -> float:
    """Median backward speed of a planted foot, asset units a second, as the preparer measures."""
    frames = round(scene.duration(animation) * _FPS)
    tracks: dict[int, list[tuple[float, float, float]]] = {foot: [] for foot in feet}
    for frame in range(frames + 1):
        pose = _Pose(scene, animation, frame / _FPS)
        for foot in feet:
            tracks[foot].append(_apply(pose.world[foot], (0.0, 0.0, 0.0)))
    samples = []
    for path in tracks.values():
        floor = min(p[1] for p in path)
        for a, b in pairwise(path):
            if max(a[1], b[1]) < floor + 0.04 and a[2] > b[2] + 0.0001:
                samples.append((a[2] - b[2]) * _FPS)
    return statistics.median(samples) if samples else 0.0


def measure_prepared_body(payload: bytes, declaration: BodyDeclaration) -> BodyMeasurements:
    """Measure a prepared body against its declaration, or refuse it with the failure's class."""
    budget = declaration.budget
    if len(payload) > budget.max_bytes:
        raise BodyRefused("over_budget", "bytes", str(len(payload)))
    document, binary = _chunks(payload)
    scene = _Scene(document, binary)

    skins = document.get("skins", [])
    if len(skins) != 1:
        raise BodyRefused("rig_incompatible", "one_skin_required", str(len(skins)))
    skin = skins[0]
    joint_nodes: list[int] = list(skin.get("joints", ()))
    names = [scene.nodes[j].get("name") for j in joint_nodes]
    if (
        len(set(names)) != len(names)
        or set(names) != set(declaration.joints)
        or len(names) != len(declaration.joints)
    ):
        raise BodyRefused("rig_incompatible", "joints_differ_from_family")
    if len(joint_nodes) > budget.max_joints:
        raise BodyRefused("over_budget", "joints", str(len(joint_nodes)))
    if "inverseBindMatrices" not in skin:
        raise BodyRefused("rig_incompatible", "inverse_bind_matrices_missing")
    inverse_binds = _accessor(document, binary, skin["inverseBindMatrices"])
    if len(inverse_binds) != len(joint_nodes) or any(
        len(m) != 16 or abs(_determinant3(m)) < 1e-12 for m in inverse_binds
    ):
        raise BodyRefused("rig_incompatible", "inverse_bind_matrices_invalid")
    node_of = {name: joint_nodes[i] for i, name in enumerate(names)}
    if declaration.hips not in node_of or any(foot not in node_of for foot in declaration.feet):
        raise BodyRefused("rig_incompatible", "calibration_joints_missing")

    materials = [m.get("name") for m in document.get("materials", [])]
    missing = declaration.materials - set(materials)
    if missing:
        raise BodyRefused("unverified_output", "materials_missing", ",".join(sorted(missing)))

    primitives: list[_Primitive] = []
    weight_error = 0.0
    for node in scene.nodes:
        if "mesh" not in node:
            continue
        if node.get("skin") != 0:
            raise BodyRefused("rig_incompatible", "mesh_not_skinned")
        for primitive in document["meshes"][node["mesh"]]["primitives"]:
            attributes = primitive.get("attributes", {})
            if primitive.get("mode", 4) != 4 or primitive.get("targets"):
                raise BodyRefused("unverified_output", "primitive_not_admitted")
            if not {"POSITION", "JOINTS_0", "WEIGHTS_0"} <= set(attributes) or (
                {"JOINTS_1", "WEIGHTS_1"} & set(attributes)
            ):
                raise BodyRefused("rig_incompatible", "influences_not_admitted")
            positions = _accessor(document, binary, attributes["POSITION"])
            joints = _accessor(document, binary, attributes["JOINTS_0"])
            weights = _accessor(document, binary, attributes["WEIGHTS_0"])
            if not len(positions) == len(joints) == len(weights):
                raise BodyRefused("unverified_output", "attribute_counts_differ")
            for joint_row, weight_row in zip(joints, weights, strict=True):
                if any(w < 0 for w in weight_row) or any(
                    w and not 0 <= j < len(joint_nodes)
                    for j, w in zip(joint_row, weight_row, strict=True)
                ):
                    raise BodyRefused("rig_incompatible", "influence_out_of_range")
                weight_error = max(weight_error, abs(sum(weight_row) - 1.0))
            if weight_error > _WEIGHT_TOLERANCE:
                raise BodyRefused("rig_incompatible", "weights_not_normalised")
            if any(not all(math.isfinite(v) for v in p) for p in positions):
                raise BodyRefused("unverified_output", "positions_not_finite")
            if "indices" in primitive:
                triangles = len(_accessor(document, binary, primitive["indices"])) // 3
            else:
                triangles = len(positions) // 3
            material = materials[primitive["material"]] if "material" in primitive else None
            primitives.append(_Primitive(positions, joints, weights, triangles, material))
    triangles = sum(p.triangles for p in primitives)
    vertices = sum(len(p.positions) for p in primitives)
    if triangles > budget.max_triangles:
        raise BodyRefused("over_budget", "triangles", str(triangles))
    if vertices > budget.max_vertices:
        raise BodyRefused("over_budget", "vertices", str(vertices))
    images = document.get("images", [])
    if len(images) > budget.max_images:
        raise BodyRefused("over_budget", "images", str(len(images)))
    largest_image = 0
    for image in images:
        view = document["bufferViews"][image["bufferView"]]
        start = view.get("byteOffset", 0)
        largest_image = max(largest_image, _png_pixels(binary[start : start + view["byteLength"]]))
    if largest_image > budget.max_image_pixels:
        raise BodyRefused("over_budget", "image_pixels", str(largest_image))

    body = [p for p in primitives if p.material == "Skin"]
    if len(body) != 1:
        raise BodyRefused("unverified_output", "body_mesh_not_found")
    rest_height = max(p[1] for p in body[0].positions) - min(p[1] for p in body[0].positions)
    if not rest_height > 0:
        raise BodyRefused("deformation_invalid", "rest_height_not_positive")
    unit_scale = declaration.height_cm / 100 / rest_height

    animations = {a.get("name"): a for a in document.get("animations", [])}
    clips: dict[str, Mapping[str, Any]] = {}
    for role, name in declaration.clips.items():
        found = [a for a in document.get("animations", []) if a.get("name") == name]
        if len(found) != 1:
            raise BodyRefused("unverified_output", "clip_missing_or_ambiguous", name)
        clips[role] = found[0]
        for channel in found[0]["channels"]:
            if channel["target"].get("path") not in ("translation", "rotation", "scale"):
                raise BodyRefused("unverified_output", "channel_not_admitted", name)
        if not scene.duration(found[0]) >= 0.1:
            raise BodyRefused("unverified_output", "clip_too_short", name)
    del animations

    def joint_matrices(pose: _Pose) -> list[tuple[float, ...]]:
        return [_multiply(pose.world[j], inverse_binds[i]) for i, j in enumerate(joint_nodes)]

    idle = _Pose(scene, clips["idle"], 0.0)
    matrices = joint_matrices(idle)
    idle_points = [
        point for p in primitives for point in _skin(matrices, p, range(len(p.positions)))
    ]
    if any(not all(math.isfinite(v) for v in point) for point in idle_points):
        raise BodyRefused("deformation_invalid", "idle_not_finite")
    idle_floor = min(p[1] for p in idle_points)
    idle_height = max(p[1] for p in idle_points) - idle_floor
    if abs(idle_floor) * unit_scale * 1000 > declaration.idle_floor_mm:
        raise BodyRefused("deformation_invalid", "idle_not_on_ground", f"{idle_floor:.4f}")

    stride = max(1, vertices // _SAMPLED_VERTICES)
    samples: list[tuple[_Primitive, list[int]]] = []
    seen = 0
    for p in primitives:
        chosen = [i for i in range(len(p.positions)) if (seen + i) % stride == 0]
        seen += len(p.positions)
        samples.append((p, chosen))
    sampled = sum(len(chosen) for _, chosen in samples)
    hips = node_of[declaration.hips]
    reach = 0.0
    heights: list[float] = []
    for role in ("walk", "run"):
        length = scene.duration(clips[role])
        for share in _CLIP_SHARES:
            pose = _Pose(scene, clips[role], share * length)
            matrices = joint_matrices(pose)
            centre = _apply(pose.world[hips], (0.0, 0.0, 0.0))
            points = [point for p, chosen in samples for point in _skin(matrices, p, chosen)]
            if any(not all(math.isfinite(v) for v in point) for point in points):
                raise BodyRefused("deformation_invalid", "motion_not_finite", role)
            reach = max(reach, max(math.dist(point, centre) for point in points))
            heights.append(max(p[1] for p in points) - min(p[1] for p in points))
    reach_milli = round(1000 * reach / rest_height)
    low_milli = round(1000 * min(heights) / rest_height)
    high_milli = round(1000 * max(heights) / rest_height)
    if reach_milli > declaration.reach_milli:
        raise BodyRefused("deformation_invalid", "vertex_beyond_reach", str(reach_milli))
    low, high = declaration.moving_height_milli
    if not low <= low_milli <= high_milli <= high:
        raise BodyRefused(
            "deformation_invalid", "moving_height_out_of_range", f"{low_milli}-{high_milli}"
        )

    feet = [node_of[foot] for foot in declaration.feet]
    walk = _gait_speed(scene, clips["walk"], feet) * unit_scale
    run = _gait_speed(scene, clips["run"], feet) * unit_scale
    if not 0 < walk < run:
        raise BodyRefused("deformation_invalid", "gait_not_calibrated", f"{walk:.3f}/{run:.3f}")

    return BodyMeasurements(
        byte_size=len(payload),
        triangles=triangles,
        vertices=vertices,
        joints=len(joint_nodes),
        images=len(images),
        max_image_pixels=largest_image,
        native_rest_height_millionths=round(rest_height * 1_000_000),
        unit_scale_millionths=round(unit_scale * 1_000_000),
        native_idle_floor_millionths=round(idle_floor * 1_000_000),
        native_idle_height_millionths=round(idle_height * 1_000_000),
        idle_ms=round(scene.duration(clips["idle"]) * 1000),
        walk_ms=round(scene.duration(clips["walk"]) * 1000),
        run_ms=round(scene.duration(clips["run"]) * 1000),
        walk_speed_mm_per_s=round(walk * 1000),
        run_speed_mm_per_s=round(run * 1000),
        max_reach_milli=reach_milli,
        min_moving_height_milli=low_milli,
        max_moving_height_milli=high_milli,
        max_weight_error_millionths=round(weight_error * 1_000_000),
        sampled_vertices=sampled,
    )


def rest_bounds_mm(payload: bytes, unit_scale_millionths: int) -> dict[str, int]:
    """The rest-pose extent of every primitive together, in whole millimetres once scaled.

    Read from the stored vertex positions, the frame the rest height is measured in, so ask it of a
    body :func:`measure_prepared_body` accepted, with the unit scale it measured. The preparation
    queue records it as the output's dimensions: x is the width, y the height and z the depth.
    """
    document, binary = _chunks(payload)
    low, high = [math.inf] * 3, [-math.inf] * 3
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            for position in _accessor(document, binary, primitive["attributes"]["POSITION"]):
                for axis in range(3):
                    low[axis] = min(low[axis], position[axis])
                    high[axis] = max(high[axis], position[axis])
    if not all(math.isfinite(value) for value in (*low, *high)):
        raise BodyRefused("unverified_output", "positions_not_finite")
    width, height, depth = (
        round((high[axis] - low[axis]) * unit_scale_millionths / 1000) for axis in range(3)
    )
    return {"width": width, "height": height, "depth": depth}
