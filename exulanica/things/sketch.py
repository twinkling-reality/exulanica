"""A drafted body's sketch: its own body plan made visible at once, as rigid parts on its bones.

A creature drafted from words has a body plan within seconds and a sculpted look only after a GPU
has made one. Until then, and whenever no sculpted look passes its checks, it wears its **sketch**:
look kind ``rigid_on_bones``, one node per bone of its plan named ``bone:<name>`` at the joint's
rest position (a direct child of the scene root, with no rotation or scale), each carrying a
tapered six-sided limb from the joint to where the bone ends, pointed at both ends so joints read
round; a wing bone also carries its stretch of membrane, drawn from both sides; each head carries
two eyes. Colours are the recipe's named ones: the body, then the belly (jaws, membranes), an
accent (the last segment of every limb and the tail's tip) and the eyes. The drawing poses the
nodes by the plan's chains exactly as it poses a sculpted look's joints, so a sketch walks, beats
its wings and sways its tail.

It is not a picture standing in for the creature: it is the creature's body plan, drawn, and the
card says it is a sketch. Every corner is a whole number of millimetres from integer arithmetic
(:mod:`exulanica.things.bodies`), so a recipe gives the same container on any machine.

Pure: no connection, no store.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

from exulanica.things.bodies import BodyGrammar, BodyRecipe, BuiltBody, Point, body_grammar
from exulanica.things.looks import LOOK_PROFILE
from exulanica.things.pieces import MeshPart, Node, Part, write_container

__all__ = ["SKETCH_LABEL", "SKETCH_WRITER", "colour_names", "sketch_look"]

#: The writer's identity: a change to any shape or colour rule below is a new version.
SKETCH_WRITER: Final = "exulanica-body-sketch/v1"
#: The words the card reads for a sketch.
SKETCH_LABEL: Final = "a sketch of its body"
_MILLION: Final = 1_000_000
#: The six corners around a limb, as cosines and sines in millionths: 0, 60, 120, 180, 240 and 300
#: degrees, from the square root of three alone.
_HEXAGON: Final = (
    (1_000_000, 0),
    (500_000, 866_025),
    (-500_000, 866_025),
    (-1_000_000, 0),
    (-500_000, -866_025),
    (500_000, -866_025),
)
#: How far a limb's pointed ends reach past its joint and its end, in thousandths of its radius.
_POINT_PERMILLE: Final = 600
_EYE_COLOUR: Final = "amber"


def _tdiv(numerator: int, denominator: int) -> int:
    quotient = abs(numerator) // abs(denominator)
    return quotient if (numerator >= 0) == (denominator > 0) else -quotient


def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Point, b: Point) -> Point:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a: Point, b: Point) -> int:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _unit(v: Point) -> Point:
    """``v`` scaled to a length of one million, by the integer square root."""
    length = math.isqrt(_dot(v, v))
    if length == 0:
        raise ValueError("a zero vector has no direction")
    return (
        _tdiv(v[0] * _MILLION, length),
        _tdiv(v[1] * _MILLION, length),
        _tdiv(v[2] * _MILLION, length),
    )


def _outward(
    vertices: list[Point], triangles: list[tuple[int, int, int]], centre: Point
) -> tuple[tuple[int, int, int], ...]:
    """Each triangle wound so its face looks away from ``centre``, the middle of a convex shape: a
    face turned toward it is flipped. Integer arithmetic, so the test is exact."""
    out = []
    for a, b, c in triangles:
        pa, pb, pc = vertices[a], vertices[b], vertices[c]
        normal = _cross(_sub(pb, pa), _sub(pc, pa))
        middle = (pa[0] + pb[0] + pc[0], pa[1] + pb[1] + pc[1], pa[2] + pb[2] + pc[2])
        away = (middle[0] - 3 * centre[0], middle[1] - 3 * centre[1], middle[2] - 3 * centre[2])
        out.append((a, b, c) if _dot(normal, away) >= 0 else (a, c, b))
    return tuple(out)


def _limb(name: str, length: Point, r0: int, r1: int, colour: str) -> MeshPart:
    """A tapered six-sided limb from its node's origin to ``length``, pointed at both ends."""
    direction = _unit(length)
    reference = (
        (1, 0, 0) if abs(direction[2]) >= max(abs(direction[0]), abs(direction[1])) else (0, 0, 1)
    )
    u = _unit(_cross(direction, reference))
    v = _unit(_cross(direction, u))
    vertices: list[Point] = []
    for base, radius in (((0, 0, 0), r0), (length, r1)):
        for cos, sin in _HEXAGON:
            vertices.append(
                tuple(  # type: ignore[arg-type]
                    base[i] + _tdiv((u[i] * cos + v[i] * sin) * radius, _MILLION * _MILLION)
                    for i in range(3)
                )
            )
    back = _tdiv(r0 * _POINT_PERMILLE, 1000)
    front = _tdiv(r1 * _POINT_PERMILLE, 1000)
    vertices.append(tuple(-_tdiv(direction[i] * back, _MILLION) for i in range(3)))  # type: ignore[arg-type]
    vertices.append(tuple(length[i] + _tdiv(direction[i] * front, _MILLION) for i in range(3)))  # type: ignore[arg-type]
    start, end = 12, 13
    triangles = []
    for k in range(6):
        a, b = k, (k + 1) % 6
        triangles += [(a, b, 6 + b), (a, 6 + b, 6 + a), (start, b, a), (end, 6 + a, 6 + b)]
    centre = (_tdiv(length[0], 2), _tdiv(length[1], 2), _tdiv(length[2], 2))
    # A degenerate limb shorter than its own rounding collapses to a point: it draws nothing.
    distinct = [t for t in triangles if len({vertices[t[0]], vertices[t[1]], vertices[t[2]]}) == 3]
    return MeshPart(name, tuple(vertices), _outward(vertices, distinct, centre), colour)


def _membrane(name: str, corners: tuple[Point, ...], colour: str) -> MeshPart:
    """A wing's stretch of membrane between three or four corners, drawn from both sides."""
    triangles = ((0, 1, 2),) if len(corners) == 3 else ((0, 1, 2), (0, 2, 3))
    return MeshPart(name, corners, triangles, colour, double_sided=True)


def colour_names(recipe: BodyRecipe) -> tuple[str, str, str, str]:
    """The recipe's colours by role, body, belly, accent and eyes: the accent is the belly's
    where the recipe names two, and the eyes amber where it names three or fewer."""
    names = recipe.colours
    accent = names[2] if len(names) > 2 else names[1]
    eyes = names[3] if len(names) > 3 else _EYE_COLOUR
    return names[0], names[1], accent, eyes


def _colours(recipe: BodyRecipe, grammar: BodyGrammar) -> tuple[str, str, str, str]:
    body, belly, accent, eyes = (grammar.colours[name] for name in colour_names(recipe))
    return body, belly, accent, eyes


def _tips(plan: Mapping[str, Any]) -> frozenset[str]:
    """The bones at the end of each limb, tail and arm, which the accent colours."""
    return frozenset(
        limb["bones"][-1]
        for limb in plan["limbs"]
        if limb["role"] in ("leg", "arm", "wing", "fin", "tentacle", "tail")
    )


def sketch_look(
    built: BuiltBody,
    recipe: BodyRecipe,
    *,
    look: str,
    version: int,
    plan_name: str,
    origin: Mapping[str, Any],
    grammar: BodyGrammar | None = None,
) -> tuple[Mapping[str, Any], bytes]:
    """The sketch look document of ``built`` and its container's bytes.

    ``origin`` is the look's origin record: the sketch is drawn by this project from the drafted
    plan, so its class is ``authored`` by the project, its licence CC0-1.0 like every look this
    repository authors, with the plan's and the recipe's digests among its ingredients."""
    grammar = grammar or body_grammar()
    body, belly, accent, eyes = _colours(recipe, grammar)
    tips = _tips(built.plan)
    nodes = []
    for bone, joint in built.joints.items():
        end = built.ends[bone]
        r0, r1 = built.radii[bone]
        length = _sub(end, joint)
        parts: list[Part | MeshPart] = []
        colour = belly if bone.endswith("Jaw") else (accent if bone in tips else body)
        if _dot(length, length) > 0:
            parts.append(_limb(f"{bone} limb", length, r0, r1, colour))
        if bone in built.membranes:
            corners = tuple(_sub(point, joint) for point in built.membranes[bone])
            parts.append(_membrane(f"{bone} membrane", corners, belly))
        if bone.startswith("head") and bone[4:].isdigit():
            size = max(_tdiv(r0 * 300, 1000), 2)
            along = (
                _tdiv(length[0] * 450, 1000),
                _tdiv(length[1] * 450, 1000),
                _tdiv(length[2] * 450, 1000),
            )
            for side in (-1, 1):
                centre = (
                    along[0] + side * _tdiv(r0 * 550, 1000),
                    along[1],
                    along[2] + _tdiv(r0 * 450, 1000),
                )
                parts.append(
                    Part(
                        f"{bone} eye {'left' if side < 0 else 'right'}",
                        "box",
                        (size, size, size),
                        centre,
                        eyes,
                    )
                )
        nodes.append(Node(f"bone:{bone}", joint, tuple(parts)))
    container = write_container(nodes)
    document = {
        "profile": LOOK_PROFILE,
        "look": look,
        "version": version,
        "label": SKETCH_LABEL,
        "body_plan": plan_name,
        "look_kind": "rigid_on_bones",
        "container": {
            "sha256": hashlib.sha256(container).hexdigest(),
            "bytes": len(container),
            "media_type": "model/gltf-binary",
        },
        "rig": None,
        "height_mm": recipe.extent["height"],
        "sampling": "linear",
        "light": None,
        "role": None,
        "origin": dict(origin),
    }
    return MappingProxyType(document), container
