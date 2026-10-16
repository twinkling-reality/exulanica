"""Placed volumes stand apart: no two placements' rock meets at a point of the grid laid over where
their reaches meet.

A placement's reach is its volume's extent (:attr:`~exulanica.grammar.volumes.VolumeField.extent`,
the box every solid point of the volume lies in, its weathering counted), turned about the vertical
by the placement's yaw and moved to its origin: the box of the four turned corners east and north,
in whole numbers (:func:`~exulanica.grammar.volumes.sin_cos` at
:data:`~exulanica.grammar.volumes.TURN_ONE`, floored once), and the extent's own floor and top
raised by the origin's height. Two placements whose reaches share no point in all three dimensions
stand apart, with nothing evaluated.

Where two reaches meet, the box they share is sampled at :data:`SAMPLE_CELL_MM`: along each axis
at the centres of the fewest equal cells no longer than it, and where the box is thinner than a
cell, at its own two faces as well. Each point is taken into each placement's own frame (less its
origin, turned back by its yaw, floored as the turn is) and its volume's field is evaluated there,
the field each placement is realized by (:func:`~exulanica.grammar.landscape.placement_seed` from
the landscape's seed, under the landscape's volume rules), so weathering is counted. A point that
is rock (a value of zero or less) in both is refused, the first one found with east slowest and up
fastest; the later placement's field is evaluated only where the earlier one's is rock.

**What it holds.** Rock that meets rock at a grid point is refused. A sliver of shared rock
thinner than a cell can pass between the points. Reaches that meet with their rock apart, an
island beside another's keel, compose. The cost is the shared box's points, at most two field
evaluations each.
"""

from __future__ import annotations

import itertools
from typing import Final, TypeAlias

from exulanica.grammar.landscape.compose import placement_seed
from exulanica.grammar.landscape.document import LandscapeDocument, LandscapeRefused, Placement
from exulanica.grammar.volumes import TURN_ONE, VolumeField, sin_cos

__all__ = ["SAMPLE_CELL_MM", "check_volumes_apart", "placement_reach"]

#: The cell the box two reaches share is sampled at: the landscape's default finest cell.
SAMPLE_CELL_MM: Final = 2000

Point: TypeAlias = tuple[int, int, int]
Reach: TypeAlias = tuple[Point, Point]


def _turned(extent: Reach, placement: Placement) -> Reach:
    (low_x, low_y, low_z), (high_x, high_y, high_z) = extent
    sine, cosine = sin_cos(placement.yaw_mdeg)
    turned = [
        ((cosine * x - sine * y) // TURN_ONE, (sine * x + cosine * y) // TURN_ONE)
        for x in (low_x, high_x)
        for y in (low_y, high_y)
    ]
    east, north, up = placement.at_mm
    return (
        (min(x for x, _ in turned) + east, min(y for _, y in turned) + north, low_z + up),
        (max(x for x, _ in turned) + east, max(y for _, y in turned) + north, high_z + up),
    )


def placement_reach(placement: Placement) -> Reach:
    """The box a placed volume's rock lies in, in the world: its lowest and highest corners. The
    extent is the same under every seed."""
    return _turned(VolumeField(placement.volume, b"").extent, placement)


def _shared(one: Reach, other: Reach) -> Reach | None:
    low = tuple(max(one[0][axis], other[0][axis]) for axis in range(3))
    high = tuple(min(one[1][axis], other[1][axis]) for axis in range(3))
    if any(low[axis] > high[axis] for axis in range(3)):
        return None
    return (low[0], low[1], low[2]), (high[0], high[1], high[2])


def _along(low: int, high: int) -> list[int]:
    span = high - low
    cells = max(1, -(-span // SAMPLE_CELL_MM))
    centres = [low + (2 * cell + 1) * span // (2 * cells) for cell in range(cells)]
    return sorted({low, *centres, high}) if span < SAMPLE_CELL_MM else centres


class _Placed:
    """A placement's field, the one it is realized by, and its turn back into its own frame."""

    __slots__ = ("at", "cosine", "field", "placement", "reach", "sine")

    def __init__(self, placement: Placement, field: VolumeField) -> None:
        self.placement = placement
        self.field = field
        self.at = placement.at_mm
        self.sine, self.cosine = sin_cos(placement.yaw_mdeg)
        self.reach = _turned(field.extent, placement)

    def rock(self, east: int, north: int, up: int) -> bool:
        x, y = east - self.at[0], north - self.at[1]
        return (
            self.field.distance(
                (self.cosine * x + self.sine * y) // TURN_ONE,
                (self.cosine * y - self.sine * x) // TURN_ONE,
                up - self.at[2],
            )
            <= 0
        )


def _rock_in_both(shared: Reach, first: _Placed, second: _Placed) -> Point | None:
    (low_x, low_y, low_z), (high_x, high_y, high_z) = shared
    for east, north, up in itertools.product(
        _along(low_x, high_x), _along(low_y, high_y), _along(low_z, high_z)
    ):
        if first.rock(east, north, up) and second.rock(east, north, up):
            return east, north, up
    return None


def check_volumes_apart(landscape: LandscapeDocument, seed: str) -> None:
    """Refuse the first placement, in the document's order, whose rock meets an earlier one's at a
    grid point where their reaches meet, the landscape realized under ``seed``; naming both and the
    point (``landscape_volumes_overlap``, by the later placement's path)."""
    placed = [
        _Placed(
            placement,
            VolumeField(
                placement.volume,
                placement_seed(seed, placement.id),
                rules=landscape.volume_rules,
            ),
        )
        for placement in landscape.placements
    ]
    for index, later in enumerate(placed):
        for earlier, other in enumerate(placed[:index]):
            shared = _shared(later.reach, other.reach)
            if shared is None:
                continue
            point = _rock_in_both(shared, other, later)
            if point is not None:
                raise LandscapeRefused(
                    f"{later.placement.id} and {other.placement.id} (volumes[{earlier}]) are both "
                    f"rock at {point}, east, north and up, where their reaches meet from "
                    f"{shared[0]} to {shared[1]}; placed volumes stand apart",
                    path=f"volumes[{index}]",
                    code="landscape_volumes_overlap",
                )
