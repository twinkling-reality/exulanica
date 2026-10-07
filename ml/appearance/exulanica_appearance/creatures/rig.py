"""The plan-guided rig: a body plan's own skeleton fitted into a sculpted mesh, and its skin.

No learned model. The sculpted mesh was made from a concept picture that followed the plan's sketch
and was registered onto the plan's extent, so the plan's joints at rest already lie near the limbs
they belong to. This module:

*   **fits** each joint into the mesh's inside: a joint outside moves to the nearest inside voxel,
    and every joint within a chain (not its first, where a limb meets the body) moves, in the plane
    across its bone, to the deepest point of the part of the mesh's cross-section it lies in, so a
    limb's bones run down the middle of the limb;
*   **skins** the mesh by bone heat (Baran and Popovic, "Automatic Rigging and Animation of 3D
    Characters", 2007, the method of Blender's automatic weights): each vertex is heated by the
    nearest bone it can see from inside the body, and the heat equation on the surface spreads each
    bone's weight smoothly, so a leg's vertices do not follow the neighbouring leg;
*   **checks** the result by rule: every joint inside and near its plan place, every bone mostly
    inside, four influences a vertex summing to one, every limb bone moving some of the body, and no
    limb's swing dragging another limb (a vertex belonging to the bone that weighs on it most).

Numpy only, so it runs in the base environment as well as in the job; when scipy is importable the
heat equation is solved by its sparse factorisation, else by conjugate gradients, to a tolerance
far below what the checks can see. Every refusal names its rule, so the route falls back to the
next look with the reason recorded. Positions are metres in the slot frame (x across, y forward,
z up).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

from exulanica_appearance.creatures.geometry import voxel_inside

__all__ = [
    "CHAIN_ROLES",
    "INSIDE_SHARE",
    "JOINT_MOVE_SHARE",
    "LEAKED_SHARE",
    "MOVED_SHARE",
    "SWING_DEGREES",
    "Inside",
    "RigChecks",
    "RigRefused",
    "bone_heat",
    "check_rig",
    "fit_joints",
    "inside_of",
    "linear_blend",
]

#: The roles whose chains swing about their first joint, and are checked for it.
CHAIN_ROLES: Final = ("arm", "fin", "leg", "neck", "tail", "tentacle", "wing")
#: A swing's angle in the deformation check, and the bound it is judged by. A vertex belongs to the
#: bone that weighs on it most, and a limb is a chain with what hangs from it; the limb's first bone,
#: where it meets the body, is left out of what it holds, as the body around it blends into both.
#: When one limb swings, at most LEAKED_SHARE of another limb's vertices (not one it hangs from or
#: that hangs from it) may move further than MOVED_SHARE of the body's largest extent.
SWING_DEGREES: Final = 30.0
MOVED_SHARE: Final = 0.02
LEAKED_SHARE: Final = 0.03
#: A bone is mostly inside when at least this share of nine points along it are.
INSIDE_SHARE: Final = 0.75
#: A fitted joint may lie at most this share of its bone's length from the plan's (two voxels at
#: least): further, and the mesh's limb is not where the plan put it.
JOINT_MOVE_SHARE: Final = 0.5

_INFLUENCES: Final = 4
#: Chamfer costs for a face, edge and corner neighbour: thirds of a voxel, within eight per cent of
#: the Euclidean distance.
_CHAMFER: Final = {1: 3, 2: 4, 3: 5}
#: The nearest bones by distance a vertex tries, in order, for one it can see.
_CANDIDATES: Final = 8
#: A heat path is sampled every half voxel.
_PATH_STEP: Final = 0.5
_TOLERANCE: Final = 1e-8
_ITERATIONS: Final = 10_000


class RigRefused(ValueError):
    """A rig the checks refuse, by the rule it breaks, with what they measured when they ran."""

    def __init__(self, code: str, detail: str, checks: RigChecks | None = None) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.checks = checks


@dataclass(frozen=True)
class Inside:
    """A mesh's filled inside on a grid, and each voxel's distance to the outside (metres)."""

    grid: np.ndarray
    origin: np.ndarray
    voxel: float
    depth: np.ndarray

    def _index(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        index = np.floor((np.asarray(points, dtype=np.float64) - self.origin) / self.voxel)
        index = index.astype(np.int64)
        shape = np.asarray(self.grid.shape)
        within = ((index >= 0) & (index < shape)).all(axis=-1)
        return np.clip(index, 0, shape - 1), within

    def holds(self, points: np.ndarray) -> np.ndarray:
        index, within = self._index(points)
        return within & self.grid[index[..., 0], index[..., 1], index[..., 2]]

    def depth_at(self, points: np.ndarray) -> np.ndarray:
        index, within = self._index(points)
        return np.where(within, self.depth[index[..., 0], index[..., 1], index[..., 2]], 0.0)


def _chamfer_depth(grid: np.ndarray) -> np.ndarray:
    """Each inside voxel's distance to the nearest outside voxel, in voxels (a 3-4-5 chamfer)."""
    distance = np.where(grid, np.int64(1) << 40, np.int64(0))
    offsets = [
        (dx, dy, dz)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        for dz in (-1, 0, 1)
        if (dx, dy, dz) != (0, 0, 0)
    ]
    changed = True
    while changed:
        changed = False
        for offset in offsets:
            source = tuple(
                slice(max(step, 0), size + min(step, 0))
                for step, size in zip(offset, grid.shape, strict=True)
            )
            target = tuple(
                slice(max(-step, 0), size + min(-step, 0))
                for step, size in zip(offset, grid.shape, strict=True)
            )
            candidate = distance[source] + _CHAMFER[sum(abs(step) for step in offset)]
            view = distance[target]
            better = candidate < view
            if better.any():
                view[better] = candidate[better]
                changed = True
    return distance / 3.0


def inside_of(positions: np.ndarray, triangles: np.ndarray, voxel: float) -> Inside:
    """The mesh's inside on a grid of ``voxel`` metres."""
    grid, origin = voxel_inside(np.asarray(positions)[np.asarray(triangles)], voxel)
    return Inside(grid, origin, voxel, _chamfer_depth(grid) * voxel)


def _snap(inside: Inside, point: np.ndarray, centres: np.ndarray) -> np.ndarray:
    if inside.holds(point[None])[0]:
        return point
    return centres[int(np.argmin(((centres - point) ** 2).sum(axis=1)))]


def _middle(inside: Inside, point: np.ndarray, along: np.ndarray, reach: float) -> np.ndarray:
    """The deepest point, within ``reach`` of ``point`` in the plane across ``along``, of the part
    of the mesh's cross-section ``point`` lies in; the nearest such point on a tie."""
    length = float(np.linalg.norm(along))
    if length == 0.0 or not inside.holds(point[None])[0]:
        return point
    axis = along / length
    helper = np.array([0.0, 0.0, 1.0]) if abs(axis[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(axis, helper)
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    steps = max(int(np.ceil(reach / inside.voxel)), 1)
    span = np.arange(-steps, steps + 1) * inside.voxel
    grid_u, grid_v = np.meshgrid(span, span, indexing="ij")
    points = point + grid_u[..., None] * u + grid_v[..., None] * v
    radius2 = grid_u**2 + grid_v**2
    held = inside.holds(points) & (radius2 <= (steps * inside.voxel) ** 2 + 1e-12)
    region = np.zeros_like(held)
    region[steps, steps] = True
    while True:
        grown = region.copy()
        grown[1:, :] |= region[:-1, :]
        grown[:-1, :] |= region[1:, :]
        grown[:, 1:] |= region[:, :-1]
        grown[:, :-1] |= region[:, 1:]
        grown &= held
        if np.array_equal(grown, region):
            break
        region = grown
    depth = np.where(region, inside.depth_at(points), -1.0).ravel()
    best = np.lexsort((radius2.ravel(), -depth))[0]
    return points.reshape(-1, 3)[best]


def fit_joints(
    joints: Mapping[str, np.ndarray],
    ends: Mapping[str, np.ndarray],
    chains: Sequence[Mapping[str, Any]],
    radii: Mapping[str, float],
    inside: Inside,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Each joint and bone end moved into the mesh and onto the middle of its limb.

    ``radii`` is each bone's thickness at its joint (metres): the centring looks no further than
    twice it. Only the joints within a chain are centred: a chain's first joint (where a leg,
    wing, neck, tail or a second spine meets the body) and a joint in no chain (the root, a head)
    only move in when they lie outside, as the deepest point there is the body's, not the limb's.
    A bone's end that is another bone's joint moves with that joint."""
    centres = inside.origin + (np.argwhere(inside.grid) + 0.5) * inside.voxel
    within = {str(bone) for chain in chains for bone in chain["bones"][1:]}
    fitted: dict[str, np.ndarray] = {}
    for bone, joint in joints.items():
        start = np.asarray(joint, dtype=np.float64)
        point = _snap(inside, start, centres)
        if bone in within:
            along = np.asarray(ends[bone], dtype=np.float64) - start
            point = _middle(inside, point, along, max(2 * radii[bone], 2 * inside.voxel))
        fitted[bone] = point
    at_joint = {
        tuple(np.round(np.asarray(joint, dtype=np.float64), 9)): bone
        for bone, joint in joints.items()
    }
    fitted_ends: dict[str, np.ndarray] = {}
    for bone, end in ends.items():
        tip = np.asarray(end, dtype=np.float64)
        child = at_joint.get(tuple(np.round(tip, 9)))
        if child is not None and child != bone:
            fitted_ends[bone] = fitted[child]
            continue
        point = _snap(inside, tip, centres)
        along = tip - np.asarray(joints[bone], dtype=np.float64)
        fitted_ends[bone] = _middle(inside, point, along, max(2 * radii[bone], 2 * inside.voxel))
    return fitted, fitted_ends


def _closest_on_segments(
    points: np.ndarray, starts: np.ndarray, ends: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """For each point and segment: the closest point on the segment (P x B x 3) and the distance
    to it (P x B)."""
    direction = ends - starts
    length2 = np.maximum((direction**2).sum(axis=1), 1e-18)
    offset = points[:, None, :] - starts[None, :, :]
    t = np.clip((offset * direction[None]).sum(axis=2) / length2[None], 0.0, 1.0)
    closest = starts[None] + t[..., None] * direction[None]
    return closest, np.linalg.norm(points[:, None, :] - closest, axis=2)


def _laplacian(
    positions: np.ndarray, triangles: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """The cotangent weight of every directed edge (rows, columns, weights; each undirected edge's
    two triangles summed; sorted by row) and each vertex's area, a third of its triangles'."""
    a, b, c = (positions[triangles[:, k]] for k in range(3))

    def cot(u: np.ndarray, v: np.ndarray) -> np.ndarray:
        return (u * v).sum(axis=1) / np.maximum(np.linalg.norm(np.cross(u, v), axis=1), 1e-18)

    # The angle at a corner weighs the edge opposite it.
    at_a, at_b, at_c = cot(b - a, c - a), cot(c - b, a - b), cot(a - c, b - c)
    first = np.concatenate([triangles[:, 1], triangles[:, 2], triangles[:, 0]])
    second = np.concatenate([triangles[:, 2], triangles[:, 0], triangles[:, 1]])
    half = 0.5 * np.concatenate([at_a, at_b, at_c])
    rows = np.concatenate([first, second])
    columns = np.concatenate([second, first])
    weights = np.concatenate([half, half])
    key = rows * len(positions) + columns
    order = np.argsort(key, kind="stable")
    key, weights = key[order], weights[order]
    unique, start = np.unique(key, return_index=True)
    summed = np.add.reduceat(weights, start)
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    vertex_area = np.zeros(len(positions))
    for k in range(3):
        np.add.at(vertex_area, triangles[:, k], area / 3)
    return unique // len(positions), unique % len(positions), summed, vertex_area


def _solve(
    rows: np.ndarray,
    columns: np.ndarray,
    weights: np.ndarray,
    diagonal: np.ndarray,
    right: np.ndarray,
) -> np.ndarray:
    """``X`` with ``(D - W) X = right``: ``D`` the diagonal, ``W`` the directed edges' weights
    (symmetric, rows sorted); the matrix is symmetric positive definite. One column a bone."""
    count = len(diagonal)
    try:
        from scipy import sparse
        from scipy.sparse.linalg import splu
    except ImportError:
        pass
    else:
        everything = np.arange(count)
        matrix = sparse.coo_matrix(
            (
                np.concatenate([-weights, diagonal]),
                (np.concatenate([rows, everything]), np.concatenate([columns, everything])),
            ),
            shape=(count, count),
        ).tocsc()
        return np.asarray(splu(matrix).solve(right))
    starts = np.searchsorted(rows, np.arange(count))
    has_edges = np.diff(np.append(starts, len(rows))) > 0

    def multiply(x: np.ndarray) -> np.ndarray:
        summed = np.zeros_like(x)
        summed[has_edges] = np.add.reduceat(
            weights[:, None] * x[columns], starts[has_edges], axis=0
        )
        return diagonal[:, None] * x - summed

    inverse = 1.0 / diagonal
    x = np.zeros_like(right)
    residual = right.copy()
    z = inverse[:, None] * residual
    direction = z.copy()
    rz = (residual * z).sum(axis=0)
    scale = np.maximum(np.linalg.norm(right, axis=0), 1e-300)
    for _ in range(_ITERATIONS):
        if (np.linalg.norm(residual, axis=0) <= _TOLERANCE * scale).all():
            break
        product = multiply(direction)
        curvature = (direction * product).sum(axis=0)
        alpha = np.divide(rz, curvature, out=np.zeros_like(rz), where=curvature > 0)
        x += alpha * direction
        residual -= alpha * product
        z = inverse[:, None] * residual
        following = (residual * z).sum(axis=0)
        beta = np.divide(following, rz, out=np.zeros_like(rz), where=rz > 0)
        direction = z + beta * direction
        rz = following
    return x


def bone_heat(
    positions: np.ndarray,
    triangles: np.ndarray,
    bones: Sequence[str],
    joints: Mapping[str, np.ndarray],
    ends: Mapping[str, np.ndarray],
    inside: Inside,
) -> tuple[np.ndarray, np.ndarray]:
    """Bone heat weights: four bone indices and their weights a vertex (V x 4 each), the weights
    summing to one.

    A vertex is heated by the nearest of its eight nearest bones it can see from inside the body
    (failing all, its nearest), ``H = 1 / d^2``, and ``(-L + A H) w_j = A H p_j`` is solved for each
    bone ``j``, with ``L`` the cotangent Laplacian, ``A`` each vertex's area and ``p_j`` one where
    ``j`` heats the vertex."""
    positions = np.asarray(positions, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.int64)
    starts = np.stack([np.asarray(joints[bone], dtype=np.float64) for bone in bones])
    finishes = np.stack([np.asarray(ends[bone], dtype=np.float64) for bone in bones])
    closest, distance = _closest_on_segments(positions, starts, finishes)
    order = np.argsort(distance, axis=1, kind="stable")[:, : min(_CANDIDATES, len(bones))]
    nearest = order[:, 0].copy()
    seen = np.zeros(len(positions), dtype=bool)
    for rank in range(order.shape[1]):
        todo = np.nonzero(~seen)[0]
        if len(todo) == 0:
            break
        candidate = order[todo, rank]
        start = positions[todo]
        finish = closest[todo, candidate]
        longest = float(np.linalg.norm(finish - start, axis=1).max())
        samples = max(int(np.ceil(longest / (inside.voxel * _PATH_STEP))), 2)
        fractions = np.arange(1, samples) / samples
        path = start[:, None, :] + (finish - start)[:, None, :] * fractions[None, :, None]
        visible = inside.holds(path).all(axis=1)
        nearest[todo[visible]] = candidate[visible]
        seen[todo[visible]] = True
    reach = np.maximum(distance[np.arange(len(positions)), nearest], inside.voxel / 2)
    rows, columns, weights, area = _laplacian(positions, triangles)
    heat = area / reach**2
    degree = np.zeros(len(positions))
    np.add.at(degree, rows, weights)
    diagonal = degree + heat
    if (heat <= 0).any():
        raise RigRefused("rig_mesh_unfit", "a vertex belongs to no triangle with area")
    used = sorted({int(index) for index in nearest})
    right = np.zeros((len(positions), len(used)))
    for slot, index in enumerate(used):
        right[:, slot] = np.where(nearest == index, heat, 0.0)
    full = np.zeros((len(positions), len(bones)))
    full[:, used] = np.clip(_solve(rows, columns, weights, diagonal, right), 0.0, 1.0)
    keep = np.argsort(-full, axis=1, kind="stable")[:, :_INFLUENCES]
    kept = np.take_along_axis(full, keep, axis=1)
    cold = kept.sum(axis=1) <= 1e-12
    kept[cold] = 0.0
    kept[cold, 0] = 1.0
    keep[cold, 0] = nearest[cold]
    return keep.astype(np.int64), kept / kept.sum(axis=1, keepdims=True)


def _rotation(axis: np.ndarray, degrees: float) -> np.ndarray:
    axis = axis / np.linalg.norm(axis)
    angle = np.radians(degrees)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(angle) * k + (1 - np.cos(angle)) * (k @ k)


def linear_blend(
    positions: np.ndarray,
    indices: np.ndarray,
    weights: np.ndarray,
    bones: Sequence[str],
    transforms: Mapping[str, tuple[np.ndarray, np.ndarray]],
) -> np.ndarray:
    """Positions skinned by linear blending: each bone's ``(rotation, translation)`` takes a rest
    point to its posed place; a bone with none stays at rest."""
    still = (np.eye(3), np.zeros(3))
    rotation = np.stack([transforms.get(bone, still)[0] for bone in bones])
    translation = np.stack([transforms.get(bone, still)[1] for bone in bones])
    moved = np.einsum("vkij,vj->vki", rotation[indices], positions) + translation[indices]
    return (weights[..., None] * moved).sum(axis=1)


@dataclass(frozen=True)
class RigChecks:
    """What the checks measured, for the record."""

    #: Each joint's distance from the plan's rest place, metres.
    joint_moved_m: Mapping[str, float]
    #: The share of nine points along each bone that lie inside.
    inside_share: Mapping[str, float]
    #: The vertices each bone moves (weight above 0.3).
    moved_vertices: Mapping[str, int]
    #: For each swung chain, the largest share of another limb's vertices it moved too far.
    leaked_share: Mapping[str, float]


def check_rig(
    *,
    positions: np.ndarray,
    indices: np.ndarray,
    weights: np.ndarray,
    bones: Sequence[str],
    parents: Mapping[str, str | None],
    plan_joints: Mapping[str, np.ndarray],
    joints: Mapping[str, np.ndarray],
    ends: Mapping[str, np.ndarray],
    chains: Sequence[Mapping[str, Any]],
    inside: Inside,
    size: float,
) -> RigChecks:
    """Every rule of the rig, or :class:`RigRefused` naming the first it breaks. Every measure is
    taken whichever rule breaks, and a refusal carries them all, so a refused rig's record says
    how far from the plan it was and not only where it first failed. ``plan_joints`` are the
    plan's rest joints, ``joints`` and ``ends`` the fitted ones, ``size`` the body's largest
    extent (metres)."""
    broken: list[tuple[str, str]] = []
    if indices.shape[1] > _INFLUENCES or not np.allclose(weights.sum(axis=1), 1.0, atol=1e-3):
        broken.append(("rig_weights_not_whole", "four influences a vertex, summing to one"))
    if (weights < 0).any():
        broken.append(("rig_weights_not_whole", "a weight is below zero"))
    moved_m: dict[str, float] = {}
    for bone in bones:
        point = np.asarray(joints[bone], dtype=np.float64)
        if not inside.holds(point[None])[0]:
            broken.append(("rig_joint_outside", f"joint {bone} lies outside the body"))
        planned = np.asarray(plan_joints[bone], dtype=np.float64)
        moved_m[bone] = float(np.linalg.norm(point - planned))
        bone_length = float(np.linalg.norm(np.asarray(ends[bone], dtype=np.float64) - point))
        if moved_m[bone] > max(JOINT_MOVE_SHARE * bone_length, 2 * inside.voxel):
            broken.append(
                (
                    "rig_joint_far_from_plan",
                    f"joint {bone} lies {moved_m[bone] * 1000:.0f} mm from where the plan puts it",
                )
            )
    inside_share: dict[str, float] = {}
    for bone in bones:
        start = np.asarray(joints[bone], dtype=np.float64)
        end = np.asarray(ends[bone], dtype=np.float64)
        samples = start + (end - start) * (np.arange(9)[:, None] / 8)
        inside_share[bone] = float(inside.holds(samples).mean())
        if inside_share[bone] < INSIDE_SHARE:
            broken.append(("rig_bone_outside", f"bone {bone} lies mostly outside the body"))
    moved_vertices = {
        bone: int(((indices == index) & (weights > 0.3)).any(axis=1).sum())
        for index, bone in enumerate(bones)
    }
    for chain in chains:
        if chain["role"] not in CHAIN_ROLES:
            continue
        for bone in chain["bones"]:
            if moved_vertices[bone] == 0:
                broken.append(("rig_bone_moves_nothing", f"bone {bone} moves none of the body"))
    children: dict[str, list[str]] = {bone: [] for bone in bones}
    for bone in bones:
        parent = parents[bone]
        if parent is not None:
            children[parent].append(bone)

    def below(bone: str) -> list[str]:
        found = [bone]
        for child in children[bone]:
            found += below(child)
        return found

    index_of = {bone: index for index, bone in enumerate(bones)}
    part = np.take_along_axis(indices, np.argmax(weights, axis=1)[:, None], axis=1)[:, 0]
    limbs = {
        str(chain["key"]): below(str(chain["bones"][0]))
        for chain in chains
        if chain["role"] in CHAIN_ROLES
    }
    members = {
        key: np.isin(part, [index_of[bone] for bone in bones_of[1:]])
        for key, bones_of in limbs.items()
    }
    leaked: dict[str, float] = {}
    for key, swung in limbs.items():
        root = swung[0]
        pivot = np.asarray(joints[root], dtype=np.float64)
        axis = np.cross(np.asarray(ends[root], dtype=np.float64) - pivot, [0.0, 0.0, 1.0])
        if np.linalg.norm(axis) < 1e-9:
            axis = np.array([1.0, 0.0, 0.0])
        rotation = _rotation(axis, SWING_DEGREES)
        transforms = {bone: (rotation, pivot - rotation @ pivot) for bone in swung}
        moved = (
            np.linalg.norm(
                linear_blend(positions, indices, weights, bones, transforms) - positions, axis=1
            )
            > MOVED_SHARE * size
        )
        worst = 0.0
        for other, other_bones in limbs.items():
            # Neither this limb, nor one it hangs from, nor one hanging from it.
            if other == key or root in other_bones or other_bones[0] in swung:
                continue
            own = members[other]
            if not own.any():
                continue
            share = float((own & moved).sum()) / float(own.sum())
            if share > LEAKED_SHARE:
                broken.append(
                    ("rig_limb_drags_body", f"swinging {key} moves {share:.0%} of {other}")
                )
            worst = max(worst, share)
        leaked[key] = worst
    checks = RigChecks(moved_m, inside_share, moved_vertices, leaked)
    if broken:
        code, detail = broken[0]
        raise RigRefused(code, detail, checks)
    return checks
