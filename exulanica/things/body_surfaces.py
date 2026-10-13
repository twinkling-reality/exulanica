"""Bounded authored surfaces on an exact body plan, independent of locomotion and decisions.

A surface document attaches rounded ellipsoids and swept tubes to named rest joints. It pins
both the recipe and the plan, uses whole slot-frame millimetres, and passes the existing look
and container readers. No shape selects an ability or changes a recorded body. Retain the
surface document with the output: its digest is an origin ingredient, not a model receipt.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.things.bodies import BodyRecipe, BuiltBody, build_body
from exulanica.things.catalogs import read_body_plan
from exulanica.things.looks import LOOK_PROFILE, Look, read_look
from exulanica.things.pieces import MeshPart, Node, write_container

SURFACE_PROFILE: Final = "exulanica.body-surfaces/v1"
SURFACE_WRITER: Final = "exulanica-body-surfaces/v1"
MAX_PARTS: Final = 128
MAX_TRIANGLES: Final = 20_000
Vec = tuple[float, float, float]
Point = tuple[int, int, int]


class BodySurfaceRefused(ValueError):
    """A surface cannot safely dress its pinned body or exceeds its authoring budget."""


def _closed(value: object, keys: set[str], where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise BodySurfaceRefused(f"{where}: states exactly {sorted(keys)}")
    return value


def _whole(value: object, lo: int, hi: int, where: str) -> int:
    if type(value) is not int or not lo <= value <= hi:
        raise BodySurfaceRefused(f"{where}: whole number from {lo} to {hi}")
    return value


def _point(value: object, where: str) -> Point:
    if not isinstance(value, list) or len(value) != 3:
        raise BodySurfaceRefused(f"{where}: three whole millimetres")
    return tuple(_whole(v, -100_000, 100_000, where) for v in value)  # type: ignore[return-value]


def _sub(a: Sequence[float], b: Sequence[float]) -> Vec:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _cross(a: Vec, b: Vec) -> Vec:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def _unit(v: Vec) -> Vec:
    size = math.hypot(*v)
    if size < 1e-9:
        raise BodySurfaceRefused("surface has a zero direction or a degenerate triangle")
    return tuple(x / size for x in v)  # type: ignore[return-value]


def _normals(vertices: list[Point], triangles: list[tuple[int, int, int]]) -> tuple[Vec, ...]:
    sums = [[0.0, 0.0, 0.0] for _ in vertices]
    for a, b, c in triangles:
        n = _cross(_sub(vertices[b], vertices[a]), _sub(vertices[c], vertices[a]))
        _unit(n)
        for index in (a, b, c):
            for axis in range(3):
                sums[index][axis] += n[axis]
    return tuple(_unit(tuple(n)) for n in sums)  # type: ignore[arg-type]


def _ellipsoid(shape: Mapping[str, Any]) -> tuple[list[Point], list[tuple[int, int, int]]]:
    _closed(
        shape,
        {"kind", "centre_mm", "radii_mm", "segments", "rings", "ridges", "ridge_permille"},
        "ellipsoid",
    )
    centre = _point(shape["centre_mm"], "centre_mm")
    radii = _point(shape["radii_mm"], "radii_mm")
    if min(radii) < 2:
        raise BodySurfaceRefused("ellipsoid radii are at least two millimetres")
    segments = _whole(shape["segments"], 12, 64, "segments")
    rings = _whole(shape["rings"], 4, 32, "rings")
    ridges = _whole(shape["ridges"], 0, segments // 4, "ridges")
    ripple = _whole(shape["ridge_permille"], 0, 180, "ridge_permille") / 1000
    vertices = [(centre[0], centre[1], centre[2] + radii[2])]
    for row in range(1, rings):
        latitude = math.pi * row / rings
        for column in range(segments):
            longitude = 2 * math.pi * column / segments
            r = math.sin(latitude) * (1 + ripple * math.cos(ridges * longitude))
            vertices.append(
                (
                    round(centre[0] + radii[0] * r * math.cos(longitude)),
                    round(centre[1] + radii[1] * r * math.sin(longitude)),
                    round(centre[2] + radii[2] * math.cos(latitude)),
                )
            )
    bottom = len(vertices)
    vertices.append((centre[0], centre[1], centre[2] - radii[2]))
    triangles = []
    for column in range(segments):
        nxt = (column + 1) % segments
        triangles.append((0, 1 + column, 1 + nxt))
        for row in range(rings - 2):
            a, b = 1 + row * segments + column, 1 + row * segments + nxt
            triangles.extend([(a, a + segments, b + segments), (a, b + segments, b)])
        last = 1 + (rings - 2) * segments
        triangles.append((bottom, last + nxt, last + column))
    # Orient convex/ribbed radial surface away from its centre.
    for i, (a, b, c) in enumerate(triangles):
        n = _cross(_sub(vertices[b], vertices[a]), _sub(vertices[c], vertices[a]))
        away = _sub(vertices[a], centre)
        if sum(n[k] * away[k] for k in range(3)) < 0:
            triangles[i] = a, c, b
    return vertices, triangles


def _tube(shape: Mapping[str, Any]) -> tuple[list[Point], list[tuple[int, int, int]]]:
    _closed(
        shape,
        {"kind", "sections", "segments"} | ({"subdivisions"} if "subdivisions" in shape else set()),
        "tube",
    )
    subdivisions = _whole(shape.get("subdivisions", 1), 1, 4, "subdivisions")
    segments = _whole(shape["segments"], 12, 64, "segments")
    sections = shape["sections"]
    if not isinstance(sections, list) or not 2 <= len(sections) <= 16:
        raise BodySurfaceRefused("tube sections: two to sixteen centre/radius pairs")
    centres, radii = [], []
    for section in sections:
        section = _closed(section, {"centre_mm", "radii_mm"}, "section")
        centres.append(_point(section["centre_mm"], "centre_mm"))
        r = section["radii_mm"]
        if not isinstance(r, list) or len(r) != 2:
            raise BodySurfaceRefused("tube radii: two positive millimetres")
        radii.append(tuple(_whole(v, 2, 20_000, "radius") for v in r))
    steps = [_unit(_sub(b, a)) for a, b in pairwise(centres)]
    if any(sum(a[k] * b[k] for k in range(3)) <= 0 for a, b in pairwise(steps)):
        raise BodySurfaceRefused("tube sections do not reverse or bend beyond a right angle")
    if subdivisions > 1:
        sampled_centres, sampled_radii = [], []
        for row in range(len(centres) - 1):
            before = centres[max(row - 1, 0)]
            a, b = centres[row], centres[row + 1]
            after = centres[min(row + 2, len(centres) - 1)]
            for step in range(subdivisions):
                t = step / subdivisions
                h00, h10 = 2 * t**3 - 3 * t * t + 1, t**3 - 2 * t * t + t
                h01, h11 = -2 * t**3 + 3 * t * t, t**3 - t * t
                sampled_centres.append(
                    tuple(
                        round(
                            h00 * a[k]
                            + h10 * (b[k] - before[k]) / 2
                            + h01 * b[k]
                            + h11 * (after[k] - a[k]) / 2
                        )
                        for k in range(3)
                    )
                )
                sampled_radii.append(
                    tuple(round(radii[row][k] * (1 - t) + radii[row + 1][k] * t) for k in range(2))
                )
        centres = [*sampled_centres, centres[-1]]
        radii = [*sampled_radii, radii[-1]]
        steps = [_unit(_sub(b, a)) for a, b in pairwise(centres)]
    vertices: list[Point] = []
    previous: Vec | None = None
    for row, (centre, radius) in enumerate(zip(centres, radii, strict=True)):
        tangent = (
            steps[0]
            if row == 0
            else steps[-1]
            if row == len(centres) - 1
            else _unit(tuple(steps[row - 1][k] + steps[row][k] for k in range(3)))
        )
        reference = previous or ((1.0, 0.0, 0.0) if abs(tangent[2]) > 0.9 else (0.0, 0.0, 1.0))
        # Transport the previous ring axis, avoiding sudden frame flips at bends.
        dot = sum(reference[k] * tangent[k] for k in range(3))
        u = _unit(tuple(reference[k] - dot * tangent[k] for k in range(3)))
        v = _unit(_cross(tangent, u))
        previous = u
        for column in range(segments):
            angle = 2 * math.pi * column / segments
            vertices.append(
                tuple(
                    round(
                        centre[k]
                        + radius[0] * math.cos(angle) * u[k]
                        + radius[1] * math.sin(angle) * v[k]
                    )
                    for k in range(3)
                )
            )
    triangles = []
    for row in range(len(centres) - 1):
        for column in range(segments):
            a, b = row * segments + column, row * segments + (column + 1) % segments
            triangles.extend([(a, b, b + segments), (a, b + segments, a + segments)])
    for row, sign in ((0, -1), (len(centres) - 1, 1)):
        middle = len(vertices)
        vertices.append(centres[row])
        for column in range(segments):
            a, b = row * segments + column, row * segments + (column + 1) % segments
            triangles.append((middle, b, a) if sign < 0 else (middle, a, b))
    return vertices, triangles


def author_surface_look(
    document: object,
    built: BuiltBody,
    recipe: BodyRecipe,
    *,
    look: str,
    version: int,
    label: str,
    origin: Mapping[str, Any],
) -> tuple[Look, bytes, Mapping[str, Any]]:
    """Validate and write an authored look, plus an inspectable deterministic authoring receipt.

    Bounds are rest-pose mesh bounds, not a locomotion/contact guarantee. The host still owns
    clearance and actions, and posed contact must be checked for the actual body and ground.
    """
    spec = _closed(document, {"profile", "plan_sha256", "recipe_sha256", "parts"}, "surface")
    plan = read_body_plan(dict(built.plan))
    expected = build_body(
        recipe,
        key=plan.key,
        version=plan.version,
        title=str(built.plan["title"]),
        origin=built.plan["origin"],
    )
    if dict(expected.plan) != dict(built.plan) or dict(expected.joints) != dict(built.joints):
        raise BodySurfaceRefused("surface body and rest joints must match the recipe's builder")
    if (
        spec["profile"] != SURFACE_PROFILE
        or spec["plan_sha256"] != plan.sha256
        or spec["recipe_sha256"] != recipe.sha256
    ):
        raise BodySurfaceRefused("surface pins its exact profile, body plan and recipe")
    parts = spec["parts"]
    if not isinstance(parts, list) or not 1 <= len(parts) <= MAX_PARTS:
        raise BodySurfaceRefused(f"surface: one to {MAX_PARTS} parts")
    by_bone: dict[str, list[MeshPart]] = {bone: [] for bone in built.joints}
    count = 0
    bounds = [[100_000] * 3, [-100_000] * 3]
    for ordinal, raw in enumerate(parts):
        part = _closed(
            raw, {"bone", "shape", "colour", "roughness_permille", "metallic_permille"}, "part"
        )
        bone = part["bone"]
        if not isinstance(bone, str) or bone not in by_bone:
            raise BodySurfaceRefused("surface attachment names a bone of its pinned plan")
        shape = part["shape"]
        if not isinstance(shape, Mapping) or shape.get("kind") not in ("ellipsoid", "tube"):
            raise BodySurfaceRefused("surface shape is an ellipsoid or tube")
        vertices, triangles = (_ellipsoid if shape["kind"] == "ellipsoid" else _tube)(shape)
        count += len(triangles)
        if count > MAX_TRIANGLES:
            raise BodySurfaceRefused(f"surface exceeds {MAX_TRIANGLES} triangles")
        for point in vertices:
            world = [point[k] + built.joints[bone][k] for k in range(3)]
            if (
                abs(world[0]) * 2 > recipe.extent["width"]
                or abs(world[1]) * 2 > recipe.extent["length"]
                or not 0 <= world[2] <= recipe.extent["height"]
            ):
                raise BodySurfaceRefused(
                    f"surface part {ordinal} exceeds the declared extent "
                    "or penetrates its support plane"
                )
            for k in range(3):
                bounds[0][k] = min(bounds[0][k], world[k])
                bounds[1][k] = max(bounds[1][k], world[k])
        try:
            mesh = MeshPart(
                f"surface{ordinal + 1}",
                tuple(vertices),
                tuple(triangles),
                part["colour"],
                normals=_normals(vertices, triangles),
                roughness_permille=part["roughness_permille"],
                metallic_permille=part["metallic_permille"],
            )
        except ValueError as exc:
            raise BodySurfaceRefused(str(exc)) from exc
        by_bone[bone].append(mesh)
    payload = write_container(
        [Node(f"bone:{bone}", at, tuple(by_bone[bone])) for bone, at in built.joints.items()]
    )
    source_sha = sha256_of_canonical(dict(spec)).hex()
    look_document = {
        "profile": LOOK_PROFILE,
        "look": look,
        "version": version,
        "label": label,
        "body_plan": plan.name,
        "look_kind": "rigid_on_bones",
        "container": {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "media_type": "model/gltf-binary",
        },
        "rig": None,
        "height_mm": recipe.extent["height"],
        "sampling": "linear",
        "light": None,
        "role": None,
        "origin": dict(origin),
    }
    ingredients = list(origin.get("lineage", {}).get("ingredients", []))
    look_document["origin"] = dict(origin) | {
        "lineage": dict(origin.get("lineage", {}))
        | {
            "ingredients": list(
                dict.fromkeys([*ingredients, recipe.sha256, plan.sha256, source_sha])
            )
        }
    }
    made = read_look(look_document, plan_of=lambda name: plan if name == plan.name else None)
    receipt = {
        "writer": SURFACE_WRITER,
        "surface_sha256": source_sha,
        "plan_sha256": plan.sha256,
        "recipe_sha256": recipe.sha256,
        "container_sha256": made.document["container"]["sha256"],
        "triangles": count,
        "parts": len(parts),
        "rest_bounds_mm": bounds,
        "motion_authority": "presentation",
        "model_receipts": [],
    }
    return made, payload, receipt
