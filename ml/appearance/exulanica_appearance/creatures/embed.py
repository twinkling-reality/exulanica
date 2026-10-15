"""Fit a body plan's skeleton into a model made from a picture: route P's skeleton, before its skin.

Route C made its model inside the plan's own sketch, so the plan's joints already lay in the model's
limbs. A model made from a picture has the picture's shape: its legs may be shorter than the plan's,
its body rounder, its arms elsewhere. This module reads where the model's limbs are and lays the
plan's chains along them. No learned model, numpy only:

*   **size and stance.** The model is scaled uniformly (never per axis, which would change its
    shape): to the plan's height, or, for a plan many times longer than tall, along its main
    horizontal axis to the plan's length; then stood on the ground, centred over the plan's origin.
*   **inside.** The model's inside on a grid, its hollows filled (``solid_inside``), from the
    model as given, never a simplified copy (simplifying can tear a closed model open), and each
    inside voxel's distance through the inside (a 3-4-5 chamfer geodesic) from the deepest point.
*   **curve skeleton.** The inside is cut into shells of equal geodesic distance. Each shell's
    connected parts are the skeleton's nodes, each at its part's centroid, so a limb's nodes run
    down its middle; a node hangs from the part it touches most in the shell below (a Reeb graph of
    the geodesic distance, kept as a tree). A leaf is the far end of something that sticks out. A
    branch from a leaf back to where it meets another is a limb when it stands out (its far point's
    distance less its junction's) further than both ``min_branch_share`` of the body's largest
    extent and ``min_branch_thickness`` times its own median thickness; anything less is a bump,
    and is pruned, the least first.
*   **facing.** The vertical plane the model is most nearly mirror symmetric about gives its forward
    axis up to a half turn (a second plane, as symmetric, adds its two). Each candidate facing is
    scored by how well the plan's limb ends land on the model's, and the best is kept.
*   **matching.** Each of the plan's leaf bones (a limb's last bone, a jaw, a head, a tail's tip) is
    matched to one limb end, cheapest first: the distance between the end and where the plan, at
    the model's scale over the middle of its box, puts the leaf, and the turn between their
    directions from the body's middle. A leg's end must stand on the ground and a left or right
    chain's end lie on its own side. The deepest point is offered too, to a chain that begins no
    limb: a head can be the model's thickest part and stick out of nothing.
*   **laying the bones.** The path holding most of the trunk (spine, neck, head) is laid first,
    then every other matched path, each from the root along the curve skeleton, pulled taut inside
    the body, to its limb end. The bones not yet laid on a path share it, from where their parent
    was laid, in proportion to their lengths in the plan. A limb starts at the first node that is
    its own (past the last place another matched limb's branch meets its path), and a trunk laid
    on a limb's path stops where that limb's branch meets the others'.
*   **missing limbs.** A plan's leg with no limb end refuses the fit by name: a body that cannot
    stand cannot walk. Any other chain with no limb end is kept inside the body and still: its bones
    point the plan's way from their parent, shortened until they lie inside, and the skin gives them
    nothing to move.

Positions are metres in the slot frame (x across, its left at -x; y forward; z up). Every figure a
creature could want different is a field of :class:`EmbedSettings` with today's value as its
default.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np

from exulanica_appearance.creatures.rig import Inside

__all__ = [
    "DEFAULT_SETTINGS",
    "LIMB_ROLES",
    "EmbedRefused",
    "EmbedSettings",
    "Embedded",
    "Skeleton",
    "curve_skeleton",
    "embed",
    "solid_inside",
]

#: The chain roles that begin a limb: a chain of one of these starts where its limb branches off.
LIMB_ROLES: Final = frozenset({"arm", "fin", "leg", "tail", "tentacle", "wing"})
#: The chain roles a body stands and walks on: a plan's chain of one of these with no limb end in
#: the model refuses the fit.
STANDING_ROLES: Final = frozenset({"leg"})
#: Chamfer costs for a face, edge and corner neighbour: thirds of a voxel.
_FACE, _EDGE, _CORNER = 3.0, 4.0, 5.0
_NEIGHBOURS: Final = tuple(
    (dx, dy, dz)
    for dx in (-1, 0, 1)
    for dy in (-1, 0, 1)
    for dz in (-1, 0, 1)
    if (dx, dy, dz) > (0, 0, 0)
)


class EmbedRefused(ValueError):
    """A fit refused by the rule it breaks, with what was measured before it broke."""

    def __init__(self, code: str, detail: str, measures: Mapping[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.measures = dict(measures or {})


@dataclass(frozen=True)
class EmbedSettings:
    """What the fit may be asked to do differently; each default is the value it was built with."""

    #: Voxels along the model's largest extent.
    grid: int = 128
    #: A plan at least this many times longer than tall (a long low body with no legs to set its
    #: height) has its model scaled by length; any other by height. Measured on development models
    #: made from pictures: two long low bodies (plans fifty times longer than tall) scaled by height
    #: never reached their heads, and two four-legged bodies (plans two and a half to three times
    #: longer than tall) fitted by height but not by length.
    long_body_ratio: float = 8.0
    #: A shell's thickness, voxels; at least 5/3, so neighbouring voxels lie in neighbouring shells.
    shell_voxels: float = 2.0
    #: A branch shorter than this share of the largest extent is a bump, not a limb.
    min_branch_share: float = 0.05
    #: A branch must also stand out further than this many times its own median thickness (the
    #: median distance of its voxels from the outside): a limb is long for its width.
    min_branch_thickness: float = 1.0
    #: The mirror planes tried, every this many degrees.
    symmetry_step_degrees: int = 3
    #: A second mirror plane within this share of the best's score adds its facings.
    symmetry_tie: float = 0.02
    #: A leaf and a limb end whose cost passes this are not matched.
    match_cutoff_share: float = 0.5
    #: What opposite directions from the body's middle add to a match's cost.
    direction_weight: float = 0.5
    #: A leg's end stands on the ground: within this share of the model's height from it.
    ground_share: float = 0.15
    #: A left or right chain's end lies on its own side, at least this share of the model's half
    #: width out from its middle.
    side_share: float = 0.1
    #: Added to a facing's score for each plan leaf left unmatched, and for each missing leg.
    unmatched_penalty: float = 0.5
    standing_unmatched_penalty: float = 2.0
    #: A still chain is shortened by halves at most this many times to lie inside.
    still_halvings: int = 6


DEFAULT_SETTINGS: Final = EmbedSettings()


@dataclass(frozen=True)
class Skeleton:
    """The model's curve skeleton: nodes at the centroids of the shells' parts, a tree from the
    deepest point, and its limb ends."""

    centroids: np.ndarray
    parent: np.ndarray
    #: Kept leaf nodes, the far point of each, and the node each one's branch meets the rest at; the
    #: last is the deepest point's node, an end only a chain that begins no limb may take.
    leaves: tuple[int, ...]
    tips: np.ndarray
    junctions: tuple[int, ...]
    root: int
    voxel: float
    #: The inside the skeleton was read from, and its grid's origin.
    grid: np.ndarray
    origin: np.ndarray


@dataclass(frozen=True)
class Embedded:
    """The model turned, scaled and stood on the ground, and the plan's skeleton laid inside it."""

    positions: np.ndarray
    yaw_degrees: int
    scale: float
    joints: dict[str, np.ndarray]
    ends: dict[str, np.ndarray]
    #: Bones kept inside and still, in plan order.
    still: tuple[str, ...]
    #: Each plan leaf bone and the limb end it was laid to (its index among the skeleton's), or
    #: None where it had none.
    matched: dict[str, int | None]
    #: The model's inside in the placed frame, from the model as given (a simplified copy of it
    #: may be torn open; skin it against this).
    inside: Inside
    #: How the model was placed: its base point, scale, turn about z (degrees) and final shift.
    base: np.ndarray
    shift: np.ndarray
    measures: dict[str, Any] = field(default_factory=dict)

    def place(self, points: np.ndarray) -> np.ndarray:
        """Points of the model as given (another copy of it, simplified) placed as it was."""
        return (
            _turn((np.asarray(points, dtype=np.float64) - self.base) * self.scale, self.yaw_degrees)
            - self.shift
        )


# The skeleton.


def _shifted(array: np.ndarray, offset: tuple[int, int], fill: float) -> np.ndarray:
    """A 2-D slice moved by ``offset`` (what lies at ``p - offset`` comes to ``p``)."""
    db, dc = offset
    moved = np.full_like(array, fill)
    rows, columns = array.shape
    moved[max(db, 0) : rows + min(db, 0), max(dc, 0) : columns + min(dc, 0)] = array[
        max(-db, 0) : rows + min(-db, 0), max(-dc, 0) : columns + min(-dc, 0)
    ]
    return moved


def _relax(
    values: np.ndarray,
    passable: np.ndarray,
    *,
    same: np.ndarray | None = None,
    costs: bool = True,
) -> np.ndarray:
    """``values`` lowered until no neighbour offers less: each voxel takes the least of its
    neighbours' values plus the chamfer cost of the step (or nothing, without ``costs``), between
    passable voxels only and, given ``same``, between voxels of equal ``same`` only. Sweeps each
    axis both ways, slice by slice, so a value travels a whole axis in one sweep; repeated until
    nothing changes."""
    values = values.copy()
    offsets = [(db, dc) for db in (-1, 0, 1) for dc in (-1, 0, 1)]
    step = {
        offset: (0.0 if not costs else (_FACE, _EDGE, _CORNER)[abs(offset[0]) + abs(offset[1])])
        for offset in offsets
    }
    while True:
        changed = False
        for axis in range(3):
            v = np.moveaxis(values, axis, 0)
            open_ = np.moveaxis(passable, axis, 0)
            group = None if same is None else np.moveaxis(same, axis, 0)
            count = v.shape[0]
            for direction in (1, -1):
                order = range(1, count) if direction == 1 else range(count - 2, -1, -1)
                for index in order:
                    here = v[index]
                    allowed_here = open_[index]
                    if not allowed_here.any():
                        continue
                    before = v[index - direction]
                    allowed_before = open_[index - direction]
                    for offset in offsets:
                        candidate = _shifted(before, offset, np.inf) + step[offset]
                        allowed = allowed_here & _shifted(allowed_before, offset, False)
                        if group is not None:
                            allowed &= group[index] == _shifted(
                                group[index - direction], offset, -1
                            )
                        better = allowed & (candidate < here)
                        if better.any():
                            here[better] = candidate[better]
                            changed = True
        if not changed:
            return values


def _grow(grid: np.ndarray, times: int = 1) -> np.ndarray:
    """A grid grown ``times`` voxels toward its face neighbours."""
    for _ in range(times):
        grown = grid.copy()
        grown[1:] |= grid[:-1]
        grown[:-1] |= grid[1:]
        grown[:, 1:] |= grid[:, :-1]
        grown[:, :-1] |= grid[:, 1:]
        grown[:, :, 1:] |= grid[:, :, :-1]
        grown[:, :, :-1] |= grid[:, :, 1:]
        grid = grown
    return grid


def _outside(wall: np.ndarray) -> np.ndarray:
    """Every voxel the grid's border reaches through face neighbours without crossing ``wall``."""
    border = np.zeros(wall.shape, dtype=bool)
    border[[0, -1], :, :] = True
    border[:, [0, -1], :] = True
    border[:, :, [0, -1]] = True
    current = border & ~wall
    outside = current.copy()
    while current.any():
        current = _grow(current) & ~outside & ~wall
        outside |= current
    return outside


def solid_inside(
    corners: np.ndarray, voxel: float, *, seal: int = 3, pad: int = 4
) -> tuple[np.ndarray, np.ndarray]:
    """The voxels a model holds (a boolean grid) and the grid's origin (its lowest corner, metres).

    Surface voxels are those a point sampled on a triangle falls in (samples at most a third of a
    voxel apart, every triangle at once, so a model of a million triangles is quick to fill). The
    inside is what the outside, flooding in from the grid's border, cannot reach. A model made from
    a picture can come back as a thick hollow shell with an opening (one with no open edge, so
    flooded, kept only a rind two voxels thick), so its hollows are filled too: the
    surface is grown by ``seal`` voxels and the flood run again, which closes an opening up to
    twice that wide, and of what that second flood leaves out, the voxels further than ``seal``
    from every surface voxel (a hollow's middle, never a narrow gap between a limb and the body)
    are grown back to the hollow's walls and kept. ``corners`` is T x 3 x 3, metres."""
    corners = np.asarray(corners, dtype=np.float64)
    flat = corners.reshape(-1, 3)
    origin = flat.min(axis=0) - pad * voxel
    shape = tuple(
        int(n) for n in np.ceil((flat.max(axis=0) - origin) / voxel).astype(np.int64) + pad + 1
    )
    surface = np.zeros(shape, dtype=bool)
    longest = np.stack(
        [
            np.linalg.norm(corners[:, 1] - corners[:, 0], axis=1),
            np.linalg.norm(corners[:, 2] - corners[:, 1], axis=1),
            np.linalg.norm(corners[:, 0] - corners[:, 2], axis=1),
        ],
        axis=1,
    ).max(axis=1)
    steps = np.maximum(np.ceil(longest / (voxel / 3)).astype(np.int64), 1)
    for count in np.unique(steps):
        chosen = corners[steps == count]
        u, v = np.meshgrid(np.arange(count + 1), np.arange(count + 1))
        keep = u + v <= count
        u, v = u[keep] / count, v[keep] / count
        for start in range(0, len(chosen), 50_000):
            part = chosen[start : start + 50_000]
            points = (
                part[:, None, 0]
                + u[None, :, None] * (part[:, None, 1] - part[:, None, 0])
                + v[None, :, None] * (part[:, None, 2] - part[:, None, 0])
            ).reshape(-1, 3)
            cells = np.floor((points - origin) / voxel).astype(np.int64)
            surface[cells[:, 0], cells[:, 1], cells[:, 2]] = True
    inside = ~_outside(surface)
    sealed = ~(_grow(_outside(_grow(surface, seal)), seal) & ~surface)
    pocket = sealed & ~inside
    if pocket.any():
        away = _relax(np.where(surface, 0.0, np.inf), np.ones(shape, dtype=bool)) / _FACE
        hollow = pocket & (away > seal)
        for _ in range(seal + 1):
            hollow = _grow(hollow) & pocket
        inside |= hollow
    return inside, origin


def curve_skeleton(
    positions: np.ndarray, triangles: np.ndarray, settings: EmbedSettings = DEFAULT_SETTINGS
) -> Skeleton:
    """The curve skeleton of a closed mesh (slot frame, metres)."""
    positions = np.asarray(positions, dtype=np.float64)
    largest = float(np.ptp(positions, axis=0).max())
    voxel = largest / settings.grid
    grid, origin = solid_inside(positions[np.asarray(triangles)], voxel)
    depth = _relax(np.where(grid, np.inf, 0.0), np.ones_like(grid)) / _FACE * voxel
    deepest = np.unravel_index(int(np.argmax(np.where(grid, depth, -1.0))), grid.shape)
    start = np.full(grid.shape, np.inf)
    start[deepest] = 0.0
    geodesic = _relax(start, grid)
    reached = grid & np.isfinite(geodesic)
    shell = np.where(
        reached,
        np.floor(np.where(reached, geodesic, 0.0) / (_FACE * settings.shell_voxels)).astype(
            np.int64
        ),
        -1,
    )
    flat = np.arange(grid.size, dtype=np.float64).reshape(grid.shape)
    labels = _relax(np.where(reached, flat, np.inf), reached, same=shell, costs=False)
    names, node_of = np.unique(labels[reached], return_inverse=True)
    count = len(names)
    cells = np.argwhere(reached)
    centres = origin + (cells + 0.5) * voxel
    weight = np.bincount(node_of, minlength=count).astype(np.float64)
    centroids = np.stack(
        [
            np.bincount(node_of, weights=centres[:, axis], minlength=count) / weight
            for axis in range(3)
        ],
        axis=1,
    )
    node_shell = np.zeros(count, dtype=np.int64)
    node_shell[node_of] = shell[reached]
    order = np.argsort(node_of, kind="stable")
    bounds = np.searchsorted(node_of[order], np.arange(count + 1))
    far = np.zeros(count, dtype=np.int64)
    distances = geodesic[reached]
    depths = depth[reached]
    thickness = np.zeros(count)
    for node in range(count):
        members = order[bounds[node] : bounds[node + 1]]
        far[node] = members[int(np.argmax(distances[members]))]
        thickness[node] = float(np.median(depths[members]))
        # A curved part's centroid can fall outside it: then the part's voxel nearest it stands in.
        index = np.floor((centroids[node] - origin) / voxel).astype(np.int64)
        if not (((index >= 0) & (index < np.asarray(grid.shape))).all() and reached[tuple(index)]):
            nearest = members[
                int(np.argmin(np.linalg.norm(centres[members] - centroids[node], axis=1)))
            ]
            centroids[node] = centres[nearest]
    node_grid = np.full(grid.shape, -1, dtype=np.int64)
    node_grid[reached] = node_of
    # Contacts between parts of neighbouring shells, counted.
    contacts: dict[tuple[int, int], int] = {}
    for dx, dy, dz in _NEIGHBOURS:
        size = grid.shape
        a = node_grid[
            max(-dx, 0) : size[0] - max(dx, 0),
            max(-dy, 0) : size[1] - max(dy, 0),
            max(-dz, 0) : size[2] - max(dz, 0),
        ]
        b = node_grid[
            max(dx, 0) : size[0] + min(dx, 0),
            max(dy, 0) : size[1] + min(dy, 0),
            max(dz, 0) : size[2] + min(dz, 0),
        ]
        both = (a >= 0) & (b >= 0)
        a, b = a[both], b[both]
        apart = node_shell[a] != node_shell[b]
        a, b = a[apart], b[apart]
        lower = np.where(node_shell[a] < node_shell[b], a, b)
        upper = np.where(node_shell[a] < node_shell[b], b, a)
        pairs, counted = np.unique(np.stack([lower, upper], axis=1), axis=0, return_counts=True)
        for (low, high), number in zip(pairs.tolist(), counted.tolist(), strict=True):
            contacts[(low, high)] = contacts.get((low, high), 0) + number
    root = int(node_grid[deepest])
    parent = np.full(count, -1, dtype=np.int64)
    best = np.zeros(count, dtype=np.int64)
    for (low, high), number in sorted(contacts.items()):
        if node_shell[high] == node_shell[low] + 1 and number > best[high]:
            parent[high], best[high] = low, number
    # Every other node hangs from a part of the shell below: its own part touches it.
    parent[root] = -1
    tips = centres[far]
    level = node_shell * settings.shell_voxels * voxel
    alive = np.ones(count, dtype=bool)
    minimum = settings.min_branch_share * largest
    # Pruned one at a time, the branch that stands out least for what it needs first: pruning it can
    # move another's junction (two bumps side by side share one) and so how far that one stands out.
    while True:
        children = np.bincount(parent[alive & (parent >= 0)], minlength=count)
        weakest, weakest_share, weakest_path = None, 1.0, []
        for leaf in range(count):
            if not alive[leaf] or children[leaf] != 0 or leaf == root:
                continue
            junction, path = _junction(leaf, parent, children, root)
            # How far the branch stands out: its far point's distance from the deepest point less
            # the junction's (a branch's persistence), never the path back to the middle, which
            # would make every bump on a round body as long as the body.
            standing = float(geodesic[tuple(cells[far[leaf]])]) / _FACE * voxel - level[junction]
            needed = max(minimum, settings.min_branch_thickness * float(np.median(thickness[path])))
            if standing / needed < weakest_share:
                weakest, weakest_share, weakest_path = leaf, standing / needed, path
        if weakest is None:
            break
        alive[weakest_path] = False
    children = np.bincount(parent[alive & (parent >= 0)], minlength=count)
    kept = [node for node in range(count) if alive[node] and children[node] == 0 and node != root]
    tip_points = [tips[node] for node in kept]
    junctions = [_junction(leaf, parent, children, root)[0] for leaf in kept]
    # The deepest point is a candidate end too, for a head or a body's end that is the thickest
    # part of the model (a maned head) and so sticks out of nothing.
    kept.append(root)
    tip_points.append(centroids[root])
    junctions.append(root)
    return Skeleton(
        centroids=centroids,
        parent=np.where(alive, parent, -1),
        leaves=tuple(kept),
        tips=np.asarray(tip_points).reshape(-1, 3),
        junctions=tuple(junctions),
        root=root,
        voxel=voxel,
        grid=grid,
        origin=origin,
    )


def _junction(
    leaf: int, parent: np.ndarray, children: np.ndarray, root: int
) -> tuple[int, list[int]]:
    """The node a leaf's branch meets the rest of the tree at, and the branch's nodes (leaf first,
    the junction left out)."""
    path = [leaf]
    node = int(parent[leaf])
    while node != root and node >= 0 and children[node] < 2:
        path.append(node)
        node = int(parent[node])
    return (root if node < 0 else node), path


def _up(node: int, parent: np.ndarray) -> list[int]:
    path = [node]
    while parent[path[-1]] >= 0:
        path.append(int(parent[path[-1]]))
    return path


def _taut(points: np.ndarray, holds, voxel: float) -> np.ndarray:
    """A path pulled taut inside the body: from each kept point, straight to the furthest later
    point the segment to which stays inside (sampled every half voxel). The nodes of a body's
    shells wander about its middle; the taut path keeps where the path goes, not its wandering."""
    kept = [0]
    while kept[-1] < len(points) - 1:
        here = points[kept[-1]]
        reach = kept[-1] + 1
        for later in range(len(points) - 1, kept[-1] + 1, -1):
            length = float(np.linalg.norm(points[later] - here))
            count = max(int(np.ceil(length / (voxel / 2))), 2)
            samples = here + (points[later] - here) * (np.arange(1, count)[:, None] / count)
            if holds(samples).all():
                reach = later
                break
        kept.append(reach)
    return points[kept]


def _arc(points: np.ndarray) -> np.ndarray:
    return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))])


def _at(points: np.ndarray, arc: np.ndarray, where: float) -> np.ndarray:
    where = float(np.clip(where, 0.0, arc[-1]))
    index = int(np.clip(np.searchsorted(arc, where, side="right") - 1, 0, len(points) - 2))
    span = arc[index + 1] - arc[index]
    t = 0.0 if span <= 0 else (where - arc[index]) / span
    return points[index] + t * (points[index + 1] - points[index])


def _projected(points: np.ndarray, arc: np.ndarray, point: np.ndarray) -> float:
    """The arc length of the polyline's point nearest ``point``."""
    a, b = points[:-1], points[1:]
    direction = b - a
    length2 = np.maximum((direction**2).sum(axis=1), 1e-18)
    t = np.clip(((point - a) * direction).sum(axis=1) / length2, 0.0, 1.0)
    closest = a + t[:, None] * direction
    index = int(np.argmin(np.linalg.norm(closest - point, axis=1)))
    return float(arc[index] + t[index] * np.sqrt(length2[index]))


# The plan.


@dataclass(frozen=True)
class _Plan:
    bones: tuple[str, ...]
    parents: Mapping[str, str | None]
    chain_of: Mapping[str, Mapping[str, Any]]
    joints: Mapping[str, np.ndarray]
    ends: Mapping[str, np.ndarray]
    leaves: tuple[str, ...]

    def path(self, leaf: str) -> list[str]:
        path = [leaf]
        while self.parents[path[-1]] is not None:
            path.append(str(self.parents[path[-1]]))
        return path[::-1]

    def length(self, bone: str) -> float:
        return float(np.linalg.norm(self.ends[bone] - self.joints[bone]))

    def side(self, bone: str) -> int:
        chain = self.chain_of.get(bone)
        side = None if chain is None else chain["side"]
        return {"left": -1, "right": 1}.get(str(side), 0)

    def role(self, bone: str) -> str | None:
        chain = self.chain_of.get(bone)
        return None if chain is None else str(chain["role"])

    def begins_limb(self, bone: str) -> bool:
        chain = self.chain_of.get(bone)
        return chain is not None and chain["role"] in LIMB_ROLES and chain["bones"][0] == bone


def _plan(
    bones: Sequence[str],
    parents: Mapping[str, str | None],
    chains: Sequence[Mapping[str, Any]],
    joints: Mapping[str, np.ndarray],
    ends: Mapping[str, np.ndarray],
) -> _Plan:
    chain_of = {str(bone): chain for chain in chains for bone in chain["bones"]}
    has_child = {parent for parent in parents.values() if parent is not None}
    return _Plan(
        bones=tuple(bones),
        parents=parents,
        chain_of=chain_of,
        joints={bone: np.asarray(joints[bone], dtype=np.float64) for bone in bones},
        ends={bone: np.asarray(ends[bone], dtype=np.float64) for bone in bones},
        leaves=tuple(bone for bone in bones if bone not in has_child),
    )


def _turn(points: np.ndarray, degrees: float) -> np.ndarray:
    angle = np.radians(degrees)
    cos, sin = np.cos(angle), np.sin(angle)
    x, y = points[..., 0], points[..., 1]
    return np.stack([x * cos - y * sin, x * sin + y * cos, points[..., 2]], axis=-1)


def _placed(
    plan: _Plan, low: np.ndarray, high: np.ndarray
) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Each plan leaf's end where the plan, at the model's scale (both are the same height), puts it
    over the middle of the model's box ``low``, ``high``; and where it puts the plan's root."""
    points = np.vstack([np.stack(list(plan.joints.values())), np.stack(list(plan.ends.values()))])
    shift = (low + high) / 2 - (points.min(axis=0) + points.max(axis=0)) / 2
    shift[2] = 0.0
    return {leaf: plan.ends[leaf] + shift for leaf in plan.leaves}, plan.joints[
        plan.bones[0]
    ] + shift


def _match(
    plan: _Plan,
    placed: Mapping[str, np.ndarray],
    root: np.ndarray,
    tips: np.ndarray,
    centre: np.ndarray,
    size: float,
    box: tuple[np.ndarray, np.ndarray],
    settings: EmbedSettings,
) -> tuple[dict[str, int | None], float]:
    """Each plan leaf's limb end, cheapest first, and the facing's score. A pair's cost is their
    distance as a share of the model's largest extent, plus half the turn between the leaf's
    direction from the plan's root and the end's from the model's ``centre`` (none for the same
    way, ``direction_weight`` for opposite ways). A leg pairs only with an end on the ground and a
    left or right chain only with an end on its own side of the model's ``box``."""
    low, high = box
    middle = (low[0] + high[0]) / 2
    half_width = max((high[0] - low[0]) / 2, 1e-9)
    pairs = []
    for leaf in plan.leaves:
        side = plan.side(leaf)
        way = placed[leaf] - root
        for index, tip in enumerate(tips):
            if index == len(tips) - 1 and plan.role(leaf) in LIMB_ROLES:
                continue
            if plan.role(leaf) in STANDING_ROLES and tip[2] - low[2] > settings.ground_share * (
                high[2] - low[2]
            ):
                continue
            if side != 0 and side * (tip[0] - middle) < settings.side_share * half_width:
                continue
            cost = float(np.linalg.norm(placed[leaf] - tip)) / size
            other = tip - centre
            lengths = float(np.linalg.norm(way) * np.linalg.norm(other))
            if lengths > 0:
                cost += settings.direction_weight * (1 - float(way @ other) / lengths) / 2
            pairs.append((cost, plan.bones.index(leaf), index, leaf))
    matched: dict[str, int | None] = {leaf: None for leaf in plan.leaves}
    used: set[int] = set()
    score = 0.0
    for cost, _order, index, leaf in sorted(pairs):
        if cost <= settings.match_cutoff_share and matched[leaf] is None and index not in used:
            matched[leaf] = index
            used.add(index)
            score += cost
    for leaf, index in matched.items():
        if index is None:
            score += (
                settings.standing_unmatched_penalty
                if plan.role(leaf) in STANDING_ROLES
                else settings.unmatched_penalty
            )
    return matched, score


def _mirror_planes(inside_points: np.ndarray, holds, settings: EmbedSettings) -> list[float]:
    """Facings (degrees, the forward direction's angle from +x toward +y) from the model's best
    mirror plane and any as good: each plane's two directions along it."""
    centre = inside_points.mean(axis=0)
    scores = []
    for degrees in range(0, 180, settings.symmetry_step_degrees):
        angle = np.radians(degrees)
        normal = np.array([np.cos(angle), np.sin(angle), 0.0])
        reflected = inside_points - 2 * ((inside_points - centre) @ normal)[:, None] * normal
        scores.append((float(holds(reflected).mean()), degrees))
    scores.sort(key=lambda item: (-item[0], item[1]))
    best = scores[0][0]
    planes = [scores[0][1]]
    for score, degrees in scores[1:]:
        apart = min(abs(degrees - other) % 180 for other in planes)
        apart = min(apart, 180 - apart)
        if best - score <= settings.symmetry_tie and apart >= 30:
            planes.append(degrees)
    facings = []
    for degrees in planes:
        # The forward direction lies in the mirror plane: perpendicular to its normal.
        for forward in (degrees + 90, degrees + 270):
            facings.append(float(forward % 360))
    return facings


def _scale(plan: _Plan, positions: np.ndarray, settings: EmbedSettings) -> tuple[float, str]:
    """How much to scale a model to its plan, and by what. A plan many times longer than tall (a long
    low body: ``long_body_ratio``) scales the model's longest horizontal extent, read along its main
    axis so no facing is assumed, to the plan's length: scaled by height, a long low body comes out
    far shorter than its plan and its far end is never reached. Any other plan, one whose legs set
    its height, scales the model to its height."""
    points = np.vstack([np.stack(list(plan.joints.values())), np.stack(list(plan.ends.values()))])
    plan_height = float(points[:, 2].max())
    plan_length = float(np.ptp(points[:, 1]))
    model_height = float(np.ptp(positions[:, 2]))
    if plan_length < settings.long_body_ratio * plan_height:
        return plan_height / model_height, "height"
    flat = positions[:, :2] - positions[:, :2].mean(axis=0)
    _values, vectors = np.linalg.eigh(flat.T @ flat)
    along = flat @ vectors[:, -1]
    return plan_length / float(np.ptp(along)), "length"


def embed(
    positions: np.ndarray,
    triangles: np.ndarray,
    *,
    bones: Sequence[str],
    parents: Mapping[str, str | None],
    chains: Sequence[Mapping[str, Any]],
    joints: Mapping[str, np.ndarray],
    ends: Mapping[str, np.ndarray],
    height: float | None = None,
    settings: EmbedSettings = DEFAULT_SETTINGS,
) -> Embedded:
    """The plan's skeleton laid in a model (``positions`` in the slot frame, z up, any size and any
    turn about z), the model scaled to ``height`` metres, or by the plan's posture when ``height``
    is None (:func:`_scale`); or :class:`EmbedRefused`."""
    plan = _plan(bones, parents, chains, joints, ends)
    positions = np.asarray(positions, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.int64)
    low, high = positions.min(axis=0), positions.max(axis=0)
    if (high - low <= 0).any():
        raise EmbedRefused("embed_mesh_unfit", "the model has no extent along an axis")
    if height is not None:
        scale, scaled_by = height / float(high[2] - low[2]), "height"
    else:
        scale, scaled_by = _scale(plan, positions, settings)
    base = np.array([(low[0] + high[0]) / 2, (low[1] + high[1]) / 2, low[2]])
    stood = (positions - base) * scale
    skeleton = curve_skeleton(stood, triangles, settings)
    size = float(np.ptp(stood, axis=0).max())
    measures: dict[str, Any] = {
        "scale_per_mille": round(scale * 1000),
        "scaled_by": scaled_by,
        "limb_ends": len(skeleton.leaves) - 1,
        "voxel_mm": round(skeleton.voxel * 1000),
    }
    if len(skeleton.leaves) < 2:
        raise EmbedRefused("embed_no_limbs", "nothing sticks out of the model", measures)
    grid, origin = skeleton.grid, skeleton.origin
    shape = np.asarray(grid.shape)

    def holds(points: np.ndarray) -> np.ndarray:
        index = np.floor((np.asarray(points) - origin) / skeleton.voxel).astype(np.int64)
        within = ((index >= 0) & (index < shape)).all(axis=-1)
        index = np.clip(index, 0, shape - 1)
        return within & grid[index[..., 0], index[..., 1], index[..., 2]]

    inside_points = origin + (np.argwhere(grid) + 0.5) * skeleton.voxel
    tried = []
    for facing in _mirror_planes(inside_points, holds, settings):
        # Turning by ``yaw`` brings the facing to +y.
        yaw = (90.0 - facing) % 360.0
        turned = _turn(stood, yaw)
        low_t, high_t = turned.min(axis=0), turned.max(axis=0)
        placed, root = _placed(plan, low_t, high_t)
        centre = np.array([(low_t[0] + high_t[0]) / 2, (low_t[1] + high_t[1]) / 2, root[2]])
        matched, score = _match(
            plan, placed, root, _turn(skeleton.tips, yaw), centre, size, (low_t, high_t), settings
        )
        tried.append((score, min(yaw, 360.0 - yaw), yaw, matched))
    tried.sort(key=lambda item: (item[0], item[1]))
    score, _least, yaw, matched = tried[0]
    measures["facings_per_mille"] = {
        str(round(item[2]) % 360): round(item[0] * 1000) for item in tried
    }
    measures["score_per_mille"] = round(score * 1000)
    missing = sorted(
        str(plan.chain_of[leaf]["key"])
        for leaf, index in matched.items()
        if index is None and plan.role(leaf) in STANDING_ROLES
    )
    if missing:
        raise EmbedRefused(
            "rig_chain_not_found",
            f"the model has no limb end for chain {missing[0]}",
            {**measures, "missing": missing},
        )
    turned = _turn(stood, yaw)
    low_t, high_t = turned.min(axis=0), turned.max(axis=0)
    shift = np.array([(low_t[0] + high_t[0]) / 2, (low_t[1] + high_t[1]) / 2, 0.0])
    final = turned - shift
    # The bones are laid and checked against one inside: the placed model's own.
    final_grid, final_origin = solid_inside(final[triangles], skeleton.voxel)
    final_depth = (
        _relax(np.where(final_grid, np.inf, 0.0), np.ones_like(final_grid)) / _FACE * skeleton.voxel
    )
    inside = Inside(final_grid, final_origin, skeleton.voxel, final_depth)
    placed = Skeleton(
        centroids=_turn(skeleton.centroids, yaw) - shift,
        parent=skeleton.parent,
        leaves=skeleton.leaves,
        tips=_turn(skeleton.tips, yaw) - shift,
        junctions=skeleton.junctions,
        root=skeleton.root,
        voxel=skeleton.voxel,
        grid=final_grid,
        origin=final_origin,
    )
    cells = np.argwhere(final_grid)
    # A point is snapped to the nearest voxel at least a voxel deep, where there is one.
    deep = final_depth[final_grid] > skeleton.voxel
    targets = final_origin + (cells[deep] if deep.any() else cells) * skeleton.voxel
    targets = targets + 0.5 * skeleton.voxel

    def snap(point: np.ndarray) -> np.ndarray:
        if inside.holds(point[None])[0]:
            return point
        return targets[int(np.argmin(((targets - point) ** 2).sum(axis=1)))].copy()

    laid_joints, laid_ends, still = _lay(plan, placed, matched, inside.holds, snap, final, settings)
    return Embedded(
        positions=final,
        yaw_degrees=round(yaw) % 360,
        scale=scale,
        joints=laid_joints,
        ends=laid_ends,
        still=tuple(bone for bone in plan.bones if bone in still),
        matched=matched,
        inside=inside,
        base=base,
        shift=shift,
        measures=measures,
    )


def _distribute(
    plan: _Plan,
    run: Sequence[str],
    points: np.ndarray,
    arc: np.ndarray,
    start: float,
    stop: float,
    joints: dict[str, np.ndarray],
    ends: dict[str, np.ndarray],
) -> None:
    """``run``'s bones laid along the polyline from arc ``start`` to ``stop``, each as long as its
    share of their plan lengths; a bone already laid keeps its joint and gets its end."""
    lengths = np.array([max(plan.length(bone), 1e-6) for bone in run])
    stations = start + np.concatenate([[0.0], np.cumsum(lengths)]) / lengths.sum() * (stop - start)
    for position, bone in enumerate(run):
        if bone not in joints:
            joints[bone] = _at(points, arc, stations[position])
        ends[bone] = _at(points, arc, stations[position + 1])


def _tree_path(skeleton: Skeleton, start: int, finish: int) -> list[int]:
    """The tree's nodes from ``start`` to ``finish``."""
    from_start = _up(start, skeleton.parent)
    from_finish = _up(finish, skeleton.parent)
    common = set(from_start) & set(from_finish)
    meet = next(node for node in from_start if node in common)
    return from_start[: from_start.index(meet) + 1] + from_finish[: from_finish.index(meet)][::-1]


def _lay(
    plan: _Plan,
    skeleton: Skeleton,
    matched: Mapping[str, int | None],
    holds,
    snap,
    model: np.ndarray,
    settings: EmbedSettings,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], set[str]]:
    """Every bone's joint and end in the model's frame, and the bones kept still; a point laid
    between two skeleton nodes that falls outside a thin limb moves to the nearest inside voxel."""
    root_bone = plan.bones[0]
    _placed_leaves, guess = _placed(plan, model.min(axis=0), model.max(axis=0))
    # The root lies at the skeleton node nearest where the plan, at the model's scale, puts it.
    alive = sorted({node for leaf in skeleton.leaves for node in _up(leaf, skeleton.parent)})
    root_node = alive[int(np.argmin(np.linalg.norm(skeleton.centroids[alive] - guess, axis=1)))]
    joints: dict[str, np.ndarray] = {root_bone: skeleton.centroids[root_node].copy()}
    ends: dict[str, np.ndarray] = {}
    trunk_roles = {None, "spine", "neck", "jaw"}
    laid = [leaf for leaf, index in matched.items() if index is not None]
    on_matched = {bone for leaf in laid for bone in plan.path(leaf)}
    tip_node = {
        leaf: skeleton.leaves[index] for leaf, index in matched.items() if index is not None
    }

    def trunk_first(leaf: str) -> tuple[int, int]:
        return (
            -sum(plan.role(bone) in trunk_roles for bone in plan.path(leaf)),
            plan.bones.index(leaf),
        )

    for leaf in sorted(laid, key=trunk_first):
        index = matched[leaf]
        assert index is not None
        nodes = _tree_path(skeleton, root_node, tip_node[leaf])
        raw = np.vstack([skeleton.centroids[nodes], skeleton.tips[index][None]])
        points = _taut(raw, holds, skeleton.voxel)
        arc = _arc(points)
        # A limb starts at the first node that is its own: past the last place another matched
        # limb end's branch meets this path.
        on_path = {node: position for position, node in enumerate(nodes)}
        meets = [
            next(
                on_path[node]
                for node in _tree_path(skeleton, tip_node[other], tip_node[leaf])
                if node in on_path
            )
            for other in laid
            if other != leaf
        ]
        meet = max(meets, default=0)
        own = min(meet + 1, len(nodes) - 1)
        limb_start = _projected(points, arc, raw[own])
        # The trunk ends where this limb's branch meets the others', not where the limb's own
        # branch begins: with no head to lay it toward, a spine stops between the shoulders.
        trunk_stop = _projected(points, arc, raw[meet])
        path = plan.path(leaf)
        first = next((i for i, bone in enumerate(path) if bone not in joints), None)
        if first is None:
            continue
        parent = path[first - 1]
        run = path[first:]
        limb_at = next((i for i, bone in enumerate(run) if plan.begins_limb(bone)), None)
        trunk, limb = (run, []) if limb_at is None else (run[:limb_at], run[limb_at:])
        if trunk:
            # The trunk's bones from the parent's end (laid with them when it has none yet) to
            # where the limb starts, or to the end when no limb follows.
            with_parent = parent not in ends
            start = _projected(points, arc, joints[parent] if with_parent else ends[parent])
            stop = trunk_stop if limb else float(arc[-1])
            if stop - start > skeleton.voxel:
                _distribute(
                    plan,
                    ([parent] if with_parent else []) + trunk,
                    points,
                    arc,
                    start,
                    stop,
                    joints,
                    ends,
                )
        if limb and float(arc[-1]) - limb_start > skeleton.voxel:
            _distribute(plan, limb, points, arc, limb_start, float(arc[-1]), joints, ends)
    # Bones no matched path laid, and ends no child set: the plan's way from their parent, inside.
    still: set[str] = set()
    for bone in plan.bones:
        if bone not in joints:
            parent = plan.parents[bone]
            assert parent is not None
            anchor = ends.get(parent, joints[parent])
            offset = plan.joints[bone] - plan.ends[parent]
            joints[bone] = _inside_along(anchor, offset, holds, halvings=settings.still_halvings)
            if bone not in on_matched:
                still.add(bone)
        if bone not in ends:
            vector = plan.ends[bone] - plan.joints[bone]
            ends[bone] = _inside_along(
                joints[bone],
                vector,
                holds,
                minimum=skeleton.voxel,
                halvings=settings.still_halvings,
            )
    for laid_points in (joints, ends):
        for bone, point in laid_points.items():
            laid_points[bone] = snap(point)
    return joints, ends, still


def _inside_along(
    start: np.ndarray, vector: np.ndarray, holds, *, minimum: float = 0.0, halvings: int = 6
) -> np.ndarray:
    """``start + vector``, the vector halved until the whole of it lies inside (failing that, cut
    to ``minimum`` long)."""
    vector = np.asarray(vector, dtype=np.float64)
    for _ in range(halvings + 1):
        samples = start + vector * (np.arange(1, 9)[:, None] / 8)
        if holds(samples).all():
            return start + vector
        vector = vector / 2
    length = float(np.linalg.norm(vector))
    if minimum > 0 and length > 0:
        return start + vector * (minimum / length)
    return start + vector
