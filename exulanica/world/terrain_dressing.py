"""Immutable terrain dressing syntax and complete final-byte contact coverage.

These pure facts do not authorize assets. Callers must separately prove current reviewed-component
rows at their database read/write barrier, without store I/O while that barrier is held.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.world.static_glb import (
    InspectedGlb,
    StaticMeshCoverage,
    inspect_static_glb,
    static_mesh_instance_bounds,
)

PROFILE = "exulanica.terrain-dressing/v1"
FRAME = "region-local-east-up-south-mm"
COLLISION = "all-mesh-instance-aabb/v1"
MAX_INSTANCES = 8
MAX_CONTENT_BYTES = 32 * 1024 * 1024
MAX_PROXIES = MAX_DRAW_CALLS = 512
MAX_TEXELS = 16_777_216
MAX_VERTICES = MAX_TRIANGLES = 1_048_576
MAX_DOCUMENT_BYTES = 16 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_KEY = re.compile(r"[a-z][a-z0-9.-]{0,199}\Z")
_ID = re.compile(r"[a-z][a-z0-9.-]{0,63}\Z")


class TerrainDressingInvalid(ValueError):
    """The closed dressing document or its exact byte coverage cannot be admitted."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TerrainDressingInvalid(message)


def _closed(raw: Any, keys: set[str]) -> None:
    _require(type(raw) is dict and set(raw) == keys, "unexpected dressing fields")


def _integer(raw: Any, low: int, high: int) -> bool:
    return type(raw) is int and low <= raw <= high


@dataclass(frozen=True, slots=True)
class DressingInstance:
    instance_id: str
    asset_key: str
    content_sha256: str
    position_mm: tuple[int, int, int]
    quarter_turns: int
    scale_per_mille: int

    def document(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "source": {
                "kind": "reviewed_component",
                "asset_key": self.asset_key,
                "content_sha256": self.content_sha256,
            },
            "position_mm": list(self.position_mm),
            "quarter_turns": self.quarter_turns,
            "scale_per_mille": self.scale_per_mille,
        }


@dataclass(frozen=True, slots=True)
class TerrainDressing:
    instances: tuple[DressingInstance, ...]
    canonical_bytes: bytes
    sha256: str

    def document(self) -> dict[str, Any]:
        return {
            "profile": PROFILE,
            "frame": FRAME,
            "collision": COLLISION,
            "instances": [instance.document() for instance in self.instances],
        }


def read_terrain_dressing(raw: Any, expected_sha256: str | None = None) -> TerrainDressing:
    """Read closed canonical syntax. Reviewed source kind is a claim, not authorization."""
    _closed(raw, {"profile", "frame", "collision", "instances"})
    _require(
        (raw["profile"], raw["frame"], raw["collision"]) == (PROFILE, FRAME, COLLISION),
        "unsupported dressing profile, frame or collision policy",
    )
    rows = raw["instances"]
    _require(type(rows) is list and 1 <= len(rows) <= MAX_INSTANCES, "dressing instance limit")
    instances = []
    for row in rows:
        _closed(row, {"instance_id", "source", "position_mm", "quarter_turns", "scale_per_mille"})
        _require(
            type(row["instance_id"]) is str and bool(_ID.fullmatch(row["instance_id"])),
            "invalid dressing instance identity",
        )
        source = row["source"]
        _closed(source, {"kind", "asset_key", "content_sha256"})
        _require(source["kind"] == "reviewed_component", "unsupported dressing source kind")
        for field, pattern in (("asset_key", _KEY), ("content_sha256", _SHA)):
            _require(
                type(source[field]) is str and bool(pattern.fullmatch(source[field])),
                "invalid dressing source pin",
            )
        position = row["position_mm"]
        _require(
            type(position) is list
            and len(position) == 3
            and all(_integer(v, -512000, 512000) for v in position),
            "invalid dressing position",
        )
        _require(_integer(row["quarter_turns"], 0, 3), "invalid dressing quarter turns")
        _require(_integer(row["scale_per_mille"], 100, 4000), "invalid dressing uniform scale")
        instances.append(
            DressingInstance(
                row["instance_id"],
                source["asset_key"],
                source["content_sha256"],
                tuple(position),
                row["quarter_turns"],
                row["scale_per_mille"],
            )
        )
    ids = [instance.instance_id for instance in instances]
    _require(ids == sorted(set(ids)), "dressing identities must be unique and sorted")
    encoded = canonical_json(raw)
    _require(len(encoded) <= MAX_DOCUMENT_BYTES, "dressing document byte limit")
    digest = hashlib.sha256(encoded).hexdigest()
    _require(expected_sha256 is None or expected_sha256 == digest, "dressing digest differs")
    return TerrainDressing(tuple(instances), encoded, digest)


@dataclass(frozen=True, slots=True)
class DressingObstruction:
    obstruction_id: str
    bounds_mm: tuple[int, int, int, int, int, int]

    def document(self) -> dict[str, Any]:
        return {
            "kind": "aabb",
            "obstruction_id": self.obstruction_id,
            "bounds_mm": list(self.bounds_mm),
        }


@dataclass(frozen=True, slots=True)
class DressingCoverage:
    dressing_sha256: str
    obstructions: tuple[DressingObstruction, ...]
    content_bytes: int
    draw_calls: int
    rendered_vertices: int
    rendered_triangles: int
    decoded_texels: int

    def obstructions_document(self) -> list[dict[str, Any]]:
        return [obstruction.document() for obstruction in self.obstructions]

    def require_contact(self, obstructions: Any) -> None:
        """No caller may omit, shrink, rename, add or reclassify source coverage."""
        try:
            exact = canonical_json(obstructions)
        except (TypeError, ValueError):
            raise TerrainDressingInvalid("dressing contact is not canonical") from None
        _require(exact == canonical_json(self.obstructions_document()), "dressing contact differs")


def compile_terrain_dressing(
    dressing: TerrainDressing,
    components: Mapping[str, bytes],
    *,
    decode_image: Callable[[bytes], tuple[int, int]],
) -> DressingCoverage:
    """Derive complete bounds from exact component bytes, never their declared accessor bounds.

    Distinct content hashes charge bytes/textures once; every placed instance charges geometry and
    draws. Quarter turns rotate positive east toward negative south about the up axis. Outward mm
    rounding happens only after the complete node and outer transforms. No source rights verdict.
    """
    # Do not trust directly constructed dataclasses as a way around the wire's constraints.
    checked = read_terrain_dressing(dressing.document(), dressing.sha256)
    _require(checked.canonical_bytes == dressing.canonical_bytes, "dressing canonical bytes differ")
    _require(
        set(components) == {row.asset_key for row in dressing.instances}, "component set differs"
    )
    payloads: dict[str, bytes] = {}
    for row in dressing.instances:
        payload = components[row.asset_key]
        _require(type(payload) is bytes, "component must be immutable bytes")
        _require(len(payload) <= MAX_CONTENT_BYTES, "dressing content byte limit")
        _require(
            hashlib.sha256(payload).hexdigest() == row.content_sha256, "component digest differs"
        )
        payloads[row.content_sha256] = payload
    byte_size = sum(map(len, payloads.values()))
    _require(byte_size <= MAX_CONTENT_BYTES, "dressing content byte limit")
    # Header/resource preflight precedes any texture decode or exact vertex traversal.
    inspected = {digest: inspect_static_glb(payload) for digest, payload in payloads.items()}
    texels = sum(facts.counts["texels"] for facts in inspected.values())
    _require(texels <= MAX_TEXELS, "dressing decoded texel limit")
    for key, ceiling in (
        ("draw_calls", MAX_DRAW_CALLS),
        ("rendered_vertices", MAX_VERTICES),
        ("rendered_triangles", MAX_TRIANGLES),
    ):
        _require(
            sum(inspected[row.content_sha256].counts[key] for row in dressing.instances) <= ceiling,
            "dressing rendered geometry limit",
        )
    _require(
        sum(len(inspected[row.content_sha256].instances) for row in dressing.instances)
        <= MAX_PROXIES,
        "dressing proxy limit",
    )
    for facts in inspected.values():
        active = list(facts.roots)
        while active:
            node = facts.document["nodes"][active.pop()]
            _require("matrix" not in node, "dressing active matrix nodes are unsupported")
            active.extend(node.get("children", []))
    measured: dict[str, StaticMeshCoverage] = {
        digest: static_mesh_instance_bounds(payload, decode_image=decode_image)
        for digest, payload in payloads.items()
    }
    draws = vertices = triangles = 0
    obstructions = []
    for row in dressing.instances:
        facts = measured[row.content_sha256]
        draws += facts.draw_calls
        vertices += facts.rendered_vertices
        triangles += facts.rendered_triangles
        _require(
            draws <= MAX_DRAW_CALLS and vertices <= MAX_VERTICES and triangles <= MAX_TRIANGLES,
            "dressing rendered geometry limit",
        )
        _require(len(obstructions) + len(facts.instances) <= MAX_PROXIES, "dressing proxy limit")
        numerical = _render_envelopes(inspected[row.content_sha256], facts, row)
        for mesh in facts.instances:
            errors = numerical[mesh.node_index]
            corners = []
            for point in itertools.product(*zip(mesh.minimum, mesh.maximum, strict=True)):
                x, y, z = point
                for _ in range(row.quarter_turns):
                    x, z = z, -x
                corners.append(
                    tuple(
                        value * row.scale_per_mille + row.position_mm[k]
                        for k, value in enumerate((x, y, z))
                    )
                )
            bounds = tuple(
                math.floor(min(p[k] for p in corners) - errors[k] * 1000) for k in range(3)
            ) + tuple(math.ceil(max(p[k] for p in corners) + errors[k] * 1000) for k in range(3))
            _require(
                all(-512000 <= value <= 512000 for value in bounds),
                "dressing bounds outside domain",
            )
            key = f"dressing:{row.instance_id}:node:{mesh.node_index}:mesh:{mesh.mesh_index}"
            obstructions.append(DressingObstruction(key, bounds))
    return DressingCoverage(
        dressing.sha256,
        tuple(sorted(obstructions, key=lambda o: o.obstruction_id)),
        byte_size,
        draws,
        vertices,
        triangles,
        texels,
    )


# Renderer numerical contract: binary32 transforms/shader arithmetic, source-space floating
# origin in +/-1024m, active TRS only. These intervals include unrounded intermediates as well
# as binary32 rounding, so fused and unfused multiply/add paths are both covered.
_U32 = Fraction(1, 1 << 24)
_TINY32 = Fraction(1, 1 << 150)
_ORIGIN = Fraction(1024)
_MAX_ERROR = Fraction(1, 1000)
_ROTATION_ERROR = Fraction(1, 1 << 48)
_Interval = tuple[Fraction, Fraction]


def _point_interval(value: int | float | Fraction) -> _Interval:
    result = value if isinstance(value, Fraction) else Fraction(float(value))
    return result, result


def _rounded(low: Fraction, high: Fraction) -> _Interval:
    magnitude = max(abs(low), abs(high))
    _require(magnitude <= 1024, "dressing renderer matrix domain exceeded")
    if magnitude == 0:
        return low, high
    error = magnitude * _U32 + _TINY32
    return low - error, high + error


def _plus(a: _Interval, b: _Interval) -> _Interval:
    return _rounded(a[0] + b[0], a[1] + b[1])


def _times(a: _Interval, b: _Interval) -> _Interval:
    values = [x * y for x in a for y in b]
    return _rounded(min(values), max(values))


def _minus(a: _Interval, b: _Interval) -> _Interval:
    return _plus(a, (-b[1], -b[0]))


def _trs_interval(node: dict[str, Any]) -> tuple[_Interval, ...]:
    x, y, z, w = map(_point_interval, node.get("rotation", (0, 0, 0, 1)))
    sx, sy, sz = map(_point_interval, node.get("scale", (1, 1, 1)))
    two, one, zero = _point_interval(2), _point_interval(1), _point_interval(0)
    xx, yy, zz = (_times(v, v) for v in (x, y, z))
    xy, xz, yz = _times(x, y), _times(x, z), _times(y, z)
    wx, wy, wz = _times(w, x), _times(w, y), _times(w, z)
    return (
        _times(_minus(one, _times(two, _plus(yy, zz))), sx),
        _times(_times(two, _plus(xy, wz)), sx),
        _times(_times(two, _minus(xz, wy)), sx),
        zero,
        _times(_times(two, _minus(xy, wz)), sy),
        _times(_minus(one, _times(two, _plus(xx, zz))), sy),
        _times(_times(two, _plus(yz, wx)), sy),
        zero,
        _times(_times(two, _plus(xz, wy)), sz),
        _times(_times(two, _minus(yz, wx)), sz),
        _times(_minus(one, _times(two, _plus(xx, yy))), sz),
        zero,
        *(_rounded(*_point_interval(v)) for v in node.get("translation", (0, 0, 0))),
        one,
    )


def _interval_product(a: tuple[_Interval, ...], b: tuple[_Interval, ...]) -> tuple[_Interval, ...]:
    def entry(row: int, col: int) -> _Interval:
        total = _point_interval(0)
        for k in range(4):
            total = _plus(total, _times(a[k * 4 + row], b[col * 4 + k]))
        return total

    return tuple(entry(row, col) for col in range(4) for row in range(4))


def _render_envelopes(
    inspected: InspectedGlb, facts: StaticMeshCoverage, placement: DressingInstance
) -> dict[int, tuple[Fraction, Fraction, Fraction]]:
    """Conservative source-relative numerical error, bounded to one millimetre per axis.

    Backend intervals include source TRS and parent products, outer quarter-turn conversion,
    floating-origin matrix quantization and shader dot products. The renderer must enforce the
    declared origin/root/outer transform domain; an unsupported transform withholds the scene.
    """
    scale = Fraction(placement.scale_per_mille, 1000)
    rotation = ((1, 0), (0, -1), (-1, 0), (0, 1))[placement.quarter_turns]
    c, negative_s = map(Fraction, rotation)
    exact_outer = (
        c * scale,
        Fraction(0),
        negative_s * scale,
        Fraction(0),
        Fraction(0),
        scale,
        Fraction(0),
        Fraction(0),
        -negative_s * scale,
        Fraction(0),
        c * scale,
        Fraction(0),
        *(Fraction(v, 1000) for v in placement.position_mm),
        Fraction(1),
    )
    # Allow the native quarter-turn quaternion's trigonometric conversion, plus upload rounding.
    outer = tuple(
        _rounded(value - _ROTATION_ERROR * scale, value + _ROTATION_ERROR * scale)
        if i in (0, 2, 8, 10)
        else _rounded(value, value)
        for i, value in enumerate(exact_outer)
    )
    nodes = inspected.document["nodes"]
    # GraphNode composes environmentRoot -> outer -> each source ancestor, rounding world
    # matrices at each level. Keep origin symbolic: its exact translation cancels when restoring
    # source coordinates, but its upload/composition error accumulates at every ancestor.
    double_u = Fraction(1, 1 << 53)
    double_gamma = 8 * double_u / (1 - 8 * double_u)
    origin_step = _ORIGIN * (_U32 + double_gamma * (1 + _U32)) + _TINY32
    outer = tuple(
        (low - 2 * origin_step, high + 2 * origin_step) if i in (12, 13, 14) else (low, high)
        for i, (low, high) in enumerate(outer)
    )
    stack = [(number, outer) for number in inspected.roots]
    worlds = {}
    while stack:
        number, parent = stack.pop()
        node = nodes[number]
        world = _interval_product(parent, _trs_interval(node))
        world = tuple(
            (low - origin_step, high + origin_step) if i in (12, 13, 14) else (low, high)
            for i, (low, high) in enumerate(world)
        )
        worlds[number] = world
        stack.extend((child, world) for child in node.get("children", []))
    result = {}
    gamma = 7 * _U32 / (1 - 7 * _U32)
    for mesh in facts.instances:
        _require(max(mesh.local_absmax) <= 1024, "dressing renderer vertex domain exceeded")
        world = worlds[mesh.node_index]
        exact = tuple(
            sum(exact_outer[k * 4 + r] * mesh.matrix[col * 4 + k] for k in range(4))
            for col in range(4)
            for r in range(4)
        )
        errors = []
        for axis in range(3):
            radius = [max(abs(v - exact[i]) for v in world[i]) for i in range(16)]
            coefficient_error = (
                sum(radius[k * 4 + axis] * mesh.local_absmax[k] for k in range(3))
                + radius[12 + axis]
            )
            translation = max(abs(v) for v in world[12 + axis])
            dot_magnitude = (
                sum(
                    max(abs(v) for v in world[k * 4 + axis]) * mesh.local_absmax[k]
                    for k in range(3)
                )
                + translation
                + _ORIGIN
            )
            error = coefficient_error + gamma * dot_magnitude + 7 * _TINY32
            _require(error <= _MAX_ERROR, "dressing renderer error exceeds one millimetre")
            errors.append(error)
        result[mesh.node_index] = tuple(errors)
    return result
