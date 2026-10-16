"""What the checks of a tile document share: plan geometry by exact integers, the figures the
checks hold records to, and the part of the checker every check reads.

:mod:`~exulanica.grammar.grammars.city.document` runs the checks and re-exports this module's
public names.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise
from typing import TYPE_CHECKING, Any, Final

from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import Extent, integer_sqrt
from exulanica.grammar.grammars.city import CITY_GRAMMAR, CITY_SHAPES
from exulanica.grammar.grammars.city.corners import strip_box
from exulanica.grammar.grammars.city.facade import EntranceRecord
from exulanica.grammar.grammars.city.parcels import ParcelRecord
from exulanica.grammar.grammars.city.roads import JunctionRecord
from exulanica.grammar.grammars.city.streetlife import StreetTreeRecord
from exulanica.grammar.grammars.city.streets import (
    BlockRecord,
    CrossingRecord,
    CurbEdgeRecord,
    StreetSegmentRecord,
)
from exulanica.grammar.grammars.city.terrain import TerrainRecord

if TYPE_CHECKING:
    from exulanica.grammar.grammars.city.document import CityDocumentReport, GrammarRecords
    from exulanica.grammar.grammars.city.tile import TileRecord


#: The target architecture's bay pitch band, which the report measures frontage faces against.
BAY_PITCH_TARGET_MM: Final = (2_400, 3_500)
_SHAPES_BY_TYPE: Final = {shape.record_type: shape for shape in CITY_SHAPES}
#: How close, in millimetres, a point derived with one floored integer normal must land.
_NORMAL_ROUNDING_MM: Final = 2
#: The height of the capsule the nav envelope keeps clear, from the descriptor's measures.
_CAPSULE_HEIGHT_MM: Final = next(
    dict(row.measures)["height_mm"]
    for row in CITY_GRAMMAR.projection("nav_envelope").preserved
    if row.property == "capsule_clearance"
)
#: The record kinds whose drawn horizontal surfaces a person stands on, from the descriptor.
SUPPORT_KINDS: Final = frozenset(
    row.kind for row in CITY_GRAMMAR.navigation if row.ground == "support"
)


def support_top_mm(record: Any) -> int:
    """The highest a support record's drawn surface stands, for a clearance above it.

    Each support kind the descriptor names has a rule here, read from its own fields rather than
    its extent, which may hold things that are not its surface (a lot's building, a segment's
    curbs): terrain's highest sample; a segment's highest crown point; a curb's kerb top plus its
    footway's rise; a junction's and a crossing's extent tops, which hold only their surfaces; a
    block's and a lot's grade; an entrance's threshold; a tree's pit, at its trunk base.
    """
    kind = type(record)
    if kind is TerrainRecord:
        return max(record.height_mm)
    if kind is StreetSegmentRecord:
        return max(point[2] for point in record.centreline_mm)
    if kind is CurbEdgeRecord:
        return strip_box(record).max_z_mm
    if kind in (JunctionRecord, CrossingRecord):
        return record.extent.max_z_mm
    if kind in (BlockRecord, ParcelRecord):
        return record.grade_elevation_mm
    if kind is EntranceRecord:
        return record.threshold_z_mm
    if kind is StreetTreeRecord:
        return record.z_mm
    raise InvalidRecordError(f"{kind.__name__} states no support surface")


def _fail(check: str, message: str) -> InvalidRecordError:
    return InvalidRecordError(f"[{check}] {message}")


def _cross(a: tuple[int, int], b: tuple[int, int], p: tuple[int, int]) -> int:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _near_segment(
    p: tuple[int, int], a: tuple[int, int], b: tuple[int, int], tolerance: int
) -> bool:
    """Whether ``p`` is within ``tolerance`` mm of segment ``ab``, by exact integers."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_squared = dx * dx + dy * dy
    cross = _cross(a, b, p)
    if cross * cross > tolerance * tolerance * length_squared:
        return False
    along = (p[0] - a[0]) * dx + (p[1] - a[1]) * dy
    reach = tolerance * integer_sqrt(length_squared) + 1
    return -reach <= along <= length_squared + reach


def _near_ring(p: tuple[int, int], ring: tuple[tuple[int, int], ...], tolerance: int) -> bool:
    return any(
        _near_segment(p, ring[index], ring[(index + 1) % len(ring)], tolerance)
        for index in range(len(ring))
    )


def _plan(point: tuple[int, ...]) -> tuple[int, int]:
    return point[0], point[1]


def _extent_ring(extent: Extent) -> tuple[tuple[int, int], ...]:
    return (
        (extent.min_x_mm, extent.min_y_mm),
        (extent.max_x_mm, extent.min_y_mm),
        (extent.max_x_mm, extent.max_y_mm),
        (extent.min_x_mm, extent.max_y_mm),
    )


def _holds(outer: Extent, inner: Extent) -> bool:
    """Whether ``outer`` contains ``inner`` on every axis, height included."""
    return (
        _within_plan(inner, outer)
        and outer.min_z_mm <= inner.min_z_mm
        and inner.max_z_mm <= outer.max_z_mm
    )


def _within_plan(inner: Extent, outer: Extent) -> bool:
    return (
        outer.min_x_mm <= inner.min_x_mm
        and inner.max_x_mm <= outer.max_x_mm
        and outer.min_y_mm <= inner.min_y_mm
        and inner.max_y_mm <= outer.max_y_mm
    )


def _in_extent_plan(extent: Extent, x: int, y: int) -> bool:
    return extent.min_x_mm <= x <= extent.max_x_mm and extent.min_y_mm <= y <= extent.max_y_mm


def _counter_clockwise(directions: Sequence[tuple[int, int]]) -> bool:
    for (ax, ay), (bx, by) in pairwise(directions):
        half_a = 0 if (ay > 0 or (ay == 0 and ax > 0)) else 1
        half_b = 0 if (by > 0 or (by == 0 and bx > 0)) else 1
        if half_a != half_b:
            if half_a > half_b:
                return False
            continue
        if ax * by - ay * bx <= 0:
            return False
    return True


#: The first city grammar version whose tiles are refused here when they own a curb turning a
#: rounded corner into a follower they do not carry (``[corner_follower]``); earlier versions'
#: documents are held to what they were written under, and the tessellator refuses such a tile.
_CORNER_FOLLOWER_FROM_VERSION: Final = 5


class _CheckerCore:
    """What the check parts of :class:`~exulanica.grammar.grammars.city.document._Checker` read
    from the checker itself, declared for the type checker. The checker defines each, and this
    class holds nothing at run time."""

    if TYPE_CHECKING:
        tile: TileRecord
        grammar: GrammarRecords
        records: tuple[object, ...]
        report: CityDocumentReport
        _footprints: list[tuple[tuple[int, int], ...]]

        def of(self, record_type: type) -> list[Any]: ...

        def get(self, identity: str) -> Any: ...

        def carried(self, identity: str) -> Any | None: ...

        def complete(self, owner_identity: str) -> bool: ...

        def entry(self, catalog: str, key: str) -> dict[str, Any]: ...
