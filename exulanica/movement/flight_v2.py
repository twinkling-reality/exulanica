"""Flight for beings: the movement module that flies a thing of a world through its air columns.

A flying being of the things catalog, winged or one that floats, moves by this module
one society minute at a time. :func:`fly_minute` takes the being's state, the goal its engine gives
it and its kind's figures, flies it through the minute in the module's steps, and hands back its
state at the minute's end, a waypoint ``[x, y, height]`` at the end of each simulated second and the
minute's outcome, the ``flew`` event's payload (``exulanica.flight-minute/v1``).

**The air** (``exulanica.air-columns/v1``, :func:`air_columns`) is a world's ground divided into
square columns, each holding the height of the tallest solid in it, 0 where it is open, under a
ceiling. A column whose top and a kind's clearance reach above the ceiling is not flyable for that
kind. A flyer's body is the square of half its span, rounded up, around its position, and the
columns that square meets are the columns under it.

**A step** steers as flight v1 does, by Reynolds steering: the goal gives a desired velocity, and
the velocity changes toward it within the step, by at most the kind's acceleration along its
heading and by at most its turn rate across it, the heading turned by fixed-point integer turns, its
speed at most its cruise speed. Its height aims at its band, or higher where the columns it can fly
over, under it and ahead in the next three seconds, need its clearance above their tops, never
above the ceiling; where it must climb before it reaches one, it slows. Its vertical speed moves
toward that height within its climb and descent.

**A guard has the last word.** Steering only proposes. A step is taken whole only when the box its
body sweeps stays inside the air, under the ceiling and, at the lower of its two heights, the
kind's clearance above every column top it meets; while a flyer lands or takes off, open ground
asks for no clearance. Otherwise the flyer slides, keeping only the parts of its move that stay
legal, and failing those it holds where it is; each is counted. A flyer that starts a step where it
may not be, as under a column placed since its last minute, climbs straight out where the ceiling
leaves room, and otherwise moves out from under what it cannot fly over.

**Routes.** When the straight way to a goal crosses a column that is not flyable, the flyer follows
a route: an A* search over the columns its body may fly over, from its own column to the goal's,
four neighbours, the Manhattan distance its estimate, ties broken toward the way travelled and then
by column, settling at most ``route_cells`` columns. It aims at the furthest of its next waypoints
it can fly straight to. A route is found again each minute from the state and never stored.

**Goals** are the things engine's primitives: ``go_near`` and ``keep_near`` fly to a point, or the
target's point this minute, and circle it at the larger of the distance and the kind's smallest
turn; ``circle`` orbits a point; ``land`` comes down onto a point along a glide path, down a spiral
when it arrives too high over open ground, and becomes ``walking`` at height 0; ``take_off`` climbs
from the ground to the band; ``stay`` circles where the flyer is at its smallest turn, a tighter and
slower one where that does not fit, or rests where none does, and a kind that hovers slows to rest.
A goal the module cannot serve is refused by name in the outcome, and the flyer stays that minute.

Every value is an integer and every operation exact, so the same input gives the same minute on any
machine; the one draw, for a tie, is ``sha256(seed:flight:<thing_id>:tick:ordinal)``.

**Status is a switch.** The row is read when this module is imported; whether it is built is asked
where a minute is flown. Pure: no connection, no store, no world, no floats.
"""

from __future__ import annotations

import hashlib
import heapq
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from math import isqrt
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.movement.fixed import ONE, ceil_div, scale_to, tdiv, turn
from exulanica.movement.registry import FLIGHT_V2, MovementModule, built_module, movement_module

__all__ = [
    "AIR_COLUMNS_PROFILE",
    "FLIGHT_V2_MODULE",
    "GOAL_REFUSALS",
    "MINUTE_PROFILE",
    "MODES",
    "SERVED_GOALS",
    "AirColumns",
    "FlightMinuteRefused",
    "FlyerFigures",
    "air_columns",
    "check_flyers",
    "column_mm_for",
    "fly_minute",
    "flyer_figures",
]

#: The module's row, read at import whatever its status; :func:`fly_minute` asks for it built.
FLIGHT_V2_MODULE: Final[MovementModule] = movement_module(FLIGHT_V2)
#: The profile of the air a minute is flown in, the space the row declares.
AIR_COLUMNS_PROFILE: Final = "exulanica.air-columns/v1"
#: The profile of a minute's outcome, the ``flew`` event's payload, the output the row declares.
MINUTE_PROFILE: Final = "exulanica.flight-minute/v1"
#: The goals the module serves: the things engine's primitives for a flying being.
SERVED_GOALS: Final = ("go_near", "keep_near", "circle", "land", "take_off", "stay")
#: Every refusal a goal can meet, by name, in a minute's outcome.
GOAL_REFUSALS: Final = (
    "no_route",
    "target_gone",
    "lost_target",
    "circle_blocked",
    "no_room_to_land",
    "no_room_to_rise",
    "not_served_by_module",
)
#: A flyer's modes: airborne, or on the ground, where it walks.
MODES: Final = ("flight", "walking")

_STEP_MS: Final = FLIGHT_V2_MODULE.value("step_ms")
_STEPS: Final = FLIGHT_V2_MODULE.value("steps_per_minute")
_STEPS_PER_WAYPOINT: Final = _STEPS // FLIGHT_V2_MODULE.value("waypoints_per_minute")
_COLUMN_MINIMUM: Final = FLIGHT_V2_MODULE.value("column_minimum_mm")
_COLUMN_MAXIMUM: Final = FLIGHT_V2_MODULE.value("column_maximum_mm")
_CEILING: Final = FLIGHT_V2_MODULE.value("ceiling_mm")
_MAX_COLUMNS: Final = FLIGHT_V2_MODULE.value("max_columns")
_MAX_FLYERS: Final = FLIGHT_V2_MODULE.value("max_flyers")
_ROUTE_CELLS: Final = FLIGHT_V2_MODULE.value("route_cells")
_MS_PER_S: Final = 1000
#: Microradians in a milliradian: a turn rate in milliradians a second turns this many
#: microradians a millisecond.
_MICRO_PER_MILLI: Final = 1000
#: A full turn in microradians, the unit a heading is drawn in.
_FULL_TURN: Final = 6_283_185
#: How far ahead the height looks: the columns the flyer's body passes in its next three seconds.
_LOOKAHEAD_MS: Final = 3000
#: An air's column is half its widest flyer's span rounded up to this, then held to its bounds.
_COLUMN_ROUNDING_MM: Final = 500
#: Within this distance of its landing point, low enough to reach the ground in one step, a flyer
#: touches down on the point: at the slowest cruise a kind may state, one step's travel.
_TOUCHDOWN_MM: Final = 250
#: How many waypoints of its route a flyer looks along: those it may have passed, and those it may
#: aim straight at.
_ROUTE_AHEAD: Final = 8
#: A flyer circles at nine tenths of the fastest speed its turn holds on the circle, so its turning
#: keeps a tenth in hand to correct its radius.
_ORBIT_SHARE: Final = (9, 10)
#: Where its smallest turn's circle does not fit, a winged flyer that stays tries circles of these
#: quarters of that radius, flown as much slower.
_CIRCLE_QUARTERS: Final = (4, 3, 2, 1)
#: The four neighbours a route steps to: a route moves between columns that share a side.
_NEIGHBOURS: Final = ((1, 0), (-1, 0), (0, 1), (0, -1))
_AIR_KEYS: Final = frozenset(
    {"profile", "origin_mm", "column_mm", "columns_x", "columns_y", "ceiling_mm", "tops_mm"}
)
_GOAL_KEYS: Final[Mapping[str, frozenset[str]]] = {
    "go_near": frozenset({"kind", "point_mm", "within_mm"}),
    "keep_near": frozenset({"kind", "target_id", "point_mm", "within_mm"}),
    "circle": frozenset({"kind", "point_mm", "radius_mm"}),
    "land": frozenset({"kind", "point_mm"}),
    "take_off": frozenset({"kind"}),
    "stay": frozenset({"kind"}),
}
_ORBITS: Final = ("go_near", "keep_near", "circle")

Column = tuple[int, int]
Point = tuple[int, int]
#: The first and last column on each axis that a box meets: ``(ix0, ix1, iy0, iy1)``.
Span = tuple[int, int, int, int]


def _built() -> MovementModule:
    """The row when it is built; a row stated otherwise refuses with its own refusal."""
    return built_module(FLIGHT_V2)


class FlightMinuteRefused(ValueError):
    """An input a flight minute refuses, by a code a caller can act on."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail

    def __reduce__(self) -> tuple[Any, ...]:
        return (type(self), (self.code, self.detail))


# -- the air ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AirColumns:
    """A world's ground in square columns, each the height of the tallest solid in it, under a
    ceiling.

    Column ``(ix, iy)`` covers ``[x0 + ix * c, x0 + (ix + 1) * c)`` across and the same along
    ``y``, half-open so every point belongs to exactly one, and its top is
    ``tops_mm[iy * columns_x + ix]``: row by row from the least corner. Heights are above the
    ground.
    """

    origin_x_mm: int
    origin_y_mm: int
    column_mm: int
    columns_x: int
    columns_y: int
    ceiling_mm: int
    tops_mm: tuple[int, ...]
    #: The SHA-256 of the canonical document.
    sha256: str

    @property
    def end_x_mm(self) -> int:
        """Where the air ends across: the first millimetre past its last column."""
        return self.origin_x_mm + self.columns_x * self.column_mm

    @property
    def end_y_mm(self) -> int:
        return self.origin_y_mm + self.columns_y * self.column_mm

    def column_of(self, x: int, y: int) -> Column | None:
        """The column a point stands in, or None outside the air."""
        ix = (x - self.origin_x_mm) // self.column_mm
        iy = (y - self.origin_y_mm) // self.column_mm
        if 0 <= ix < self.columns_x and 0 <= iy < self.columns_y:
            return (ix, iy)
        return None

    def top(self, column: Column) -> int:
        return self.tops_mm[column[1] * self.columns_x + column[0]]

    def document(self) -> dict[str, Any]:
        return {
            "profile": AIR_COLUMNS_PROFILE,
            "origin_mm": [self.origin_x_mm, self.origin_y_mm],
            "column_mm": self.column_mm,
            "columns_x": self.columns_x,
            "columns_y": self.columns_y,
            "ceiling_mm": self.ceiling_mm,
            "tops_mm": list(self.tops_mm),
        }


def _whole(value: object) -> bool:
    return type(value) is int


def _is_point(value: object) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, str)
        and len(value) == 2
        and all(_whole(part) for part in value)
    )


def air_columns(document: object) -> AirColumns:
    """The air a minute is flown in, read from its document and checked, or a refusal by name:
    ``flight_world_too_large`` where it has more columns than the module admits, before any top is
    read, and ``invalid_air_columns`` for anything else the profile does not state."""

    def invalid(detail: str) -> FlightMinuteRefused:
        return FlightMinuteRefused("invalid_air_columns", f"an air's {detail}")

    if not isinstance(document, Mapping) or set(document) != _AIR_KEYS:
        raise invalid(f"document states exactly {sorted(_AIR_KEYS)}")
    if document["profile"] != AIR_COLUMNS_PROFILE:
        raise invalid(f"profile is {AIR_COLUMNS_PROFILE}")
    origin = document["origin_mm"]
    if not _is_point(origin):
        raise invalid("origin_mm is [x, y] in whole millimetres")
    column = document["column_mm"]
    if not _whole(column) or not _COLUMN_MINIMUM <= column <= _COLUMN_MAXIMUM:
        raise invalid(f"column_mm is a whole number from {_COLUMN_MINIMUM} to {_COLUMN_MAXIMUM}")
    columns_x, columns_y = document["columns_x"], document["columns_y"]
    if not _whole(columns_x) or not _whole(columns_y) or columns_x < 1 or columns_y < 1:
        raise invalid("columns_x and columns_y are whole numbers from 1")
    if columns_x * columns_y > _MAX_COLUMNS:
        raise FlightMinuteRefused(
            "flight_world_too_large",
            f"an air of {columns_x} by {columns_y} columns; at most {_MAX_COLUMNS} columns",
        )
    ceiling = document["ceiling_mm"]
    if not _whole(ceiling) or not 1 <= ceiling <= _CEILING:
        raise invalid(f"ceiling_mm is a whole number from 1 to {_CEILING}")
    tops = document["tops_mm"]
    if (
        not isinstance(tops, Sequence)
        or isinstance(tops, str)
        or len(tops) != columns_x * columns_y
        or not all(_whole(top) for top in tops)
        or min(tops) < 0
    ):
        raise invalid("tops_mm holds one whole, non-negative height for each column")
    air = AirColumns(
        origin_x_mm=origin[0],
        origin_y_mm=origin[1],
        column_mm=column,
        columns_x=columns_x,
        columns_y=columns_y,
        ceiling_mm=ceiling,
        tops_mm=tuple(tops),
        sha256="",
    )
    return replace(air, sha256=hashlib.sha256(canonical_json(air.document())).hexdigest())


def column_mm_for(span_mm: int) -> int:
    """The column side for an air whose widest flyer spans ``span_mm``: half the span rounded up
    to 500 mm, held between the module's narrowest and widest column."""
    half = ceil_div(span_mm, 2 * _COLUMN_ROUNDING_MM) * _COLUMN_ROUNDING_MM
    return max(_COLUMN_MINIMUM, min(_COLUMN_MAXIMUM, half))


def check_flyers(count: int) -> None:
    """Refuse, by name, a minute of more flyers than the module moves in one world."""
    if count > _MAX_FLYERS:
        raise FlightMinuteRefused(
            "too_many_flyers", f"a world's things would fly {count}; at most {_MAX_FLYERS}"
        )


# -- figures ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FlyerFigures:
    """One flying kind's figures, each inside the bounds the module's row states."""

    acceleration_mm_per_s2: int
    band_minimum_mm: int
    clearance_mm: int
    climb_mm_per_s: int
    cruise_mm_per_s: int
    descent_mm_per_s: int
    hovers: int
    span_mm: int
    turn_rate_mrad_per_s: int

    @property
    def half_span_mm(self) -> int:
        """Half the kind's span, rounded up: how far its body reaches each way."""
        return ceil_div(self.span_mm, 2)

    @property
    def turn_radius_mm(self) -> int:
        """The kind's smallest turn at its cruise speed: that speed over its turn rate."""
        return ceil_div(self.cruise_mm_per_s * _MICRO_PER_MILLI, self.turn_rate_mrad_per_s)


def flyer_figures(values: object, *, where: str = "a flying kind") -> FlyerFigures:
    """A kind's figures from its stated values: exactly the parameters a kind supplies, each
    inside the module's bounds, or ``ParameterOutOfBounds`` naming the module, the parameter and
    the value."""
    supplied = FLIGHT_V2_MODULE.supplied()
    if not isinstance(values, Mapping) or set(values) != set(supplied):
        raise FlightMinuteRefused(
            "invalid_flight_figures", f"{where} states exactly {sorted(supplied)}"
        )
    return FlyerFigures(
        **{name: FLIGHT_V2_MODULE.checked(name, values[name], where=where) for name in supplied}
    )


# -- the flyer and its goal -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Body:
    """Where a flyer is and how it moves: millimetres, millimetres a second, ``z`` up."""

    x: int
    y: int
    height: int
    vx: int
    vy: int
    vz: int
    flying: bool
    #: Whether the guard took less than the step steering proposed.
    held: bool = False


@dataclass(frozen=True, slots=True)
class _Goal:
    kind: str
    point: Point | None = None
    #: ``within_mm`` of a goal near a point, ``radius_mm`` of a circle.
    distance: int = 0


def _invalid_flyer(detail: str) -> FlightMinuteRefused:
    return FlightMinuteRefused("invalid_flyer", f"a flyer's {detail}")


def _read_flyer(air: AirColumns, flyer: object) -> tuple[str, _Body]:
    """A flyer's identity and body, checked against the state shape agreed with the things
    engine: ``position_mm`` ``[x, y]``, ``mode``, and while in flight ``height_mm`` and an
    optional ``velocity_mm_s`` ``[vx, vy, vz]``, absent at rest."""
    if not isinstance(flyer, Mapping):
        raise _invalid_flyer("state is a mapping")
    thing_id = flyer.get("thing_id")
    if not isinstance(thing_id, str) or not thing_id:
        raise _invalid_flyer("thing_id is non-empty text")
    position, mode = flyer.get("position_mm"), flyer.get("mode")
    if not _is_point(position):
        raise _invalid_flyer("position_mm is [x, y] in whole millimetres")
    if mode not in MODES:
        raise _invalid_flyer(f"mode is one of {MODES}")
    height, velocity = 0, (0, 0, 0)
    if mode == "flight":
        height = flyer.get("height_mm")
        if not _whole(height) or height < 0:
            raise _invalid_flyer("height_mm in flight is a whole, non-negative height")
        stated = flyer.get("velocity_mm_s", None)
        if stated is not None:
            if (
                not isinstance(stated, Sequence)
                or isinstance(stated, str)
                or len(stated) != 3
                or not all(_whole(part) for part in stated)
            ):
                raise _invalid_flyer("velocity_mm_s is [vx, vy, vz] in whole millimetres a second")
            velocity = (stated[0], stated[1], stated[2])
    elif "height_mm" in flyer or "velocity_mm_s" in flyer:
        raise _invalid_flyer("state on the ground has no height_mm or velocity_mm_s")
    if air.column_of(position[0], position[1]) is None:
        raise FlightMinuteRefused(
            "flyer_outside_air", f"flyer {thing_id} stands at {list(position)}, outside the air"
        )
    body = _Body(position[0], position[1], height, *velocity, flying=mode == "flight")
    return thing_id, body


def _read_goal(goal: object) -> _Goal:
    """A goal checked against its primitive's shape. A kind the module does not serve is kept as
    it is, to be refused by name in the minute's outcome."""

    def invalid(detail: str) -> FlightMinuteRefused:
        return FlightMinuteRefused("invalid_flight_goal", f"a goal {detail}")

    if not isinstance(goal, Mapping) or not isinstance(goal.get("kind"), str) or not goal["kind"]:
        raise invalid("names its kind")
    kind = goal["kind"]
    keys = _GOAL_KEYS.get(kind)
    if keys is None:
        return _Goal(kind)
    if set(goal) != keys:
        raise invalid(f"of kind {kind} states exactly {sorted(keys)}")
    point = goal.get("point_mm")
    if "point_mm" in keys and not (_is_point(point) or (kind == "keep_near" and point is None)):
        raise invalid(f"of kind {kind} states point_mm as [x, y] in whole millimetres")
    if kind == "keep_near" and (not isinstance(goal["target_id"], str) or not goal["target_id"]):
        raise invalid("to keep near states its target_id")
    distance = goal.get("within_mm", goal.get("radius_mm", 0))
    if not _whole(distance) or distance < 0:
        raise invalid(f"of kind {kind} states a whole, non-negative distance")
    return _Goal(kind, None if point is None else (point[0], point[1]), distance)


# -- the minute's context ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Minute:
    """What every step of one flyer's minute reads: the air, its figures and their per-step
    forms, and the minute's one draw."""

    air: AirColumns
    figures: FlyerFigures
    half_span: int
    turn_radius: int
    #: The most the flyer's speed, and its vertical speed, change in one step.
    speed_change: int
    #: The cosine and sine, over :data:`ONE`, of the most its heading turns in one step.
    turn_cosine: int
    turn_sine: int
    #: The side a flyer turns to when what it wants lies straight behind it: the minute's draw.
    tie_side: int
    #: The heading, a vector of length about 1000, a flyer at rest sets off along: the draw.
    rest_heading: Point
    #: Whether a route may pass each column asked about, kept for the minute.
    passable: dict[Column, bool] = field(default_factory=dict)


def _minute(
    air: AirColumns, figures: FlyerFigures, seed: str, thing_id: str, tick: int, ordinal: int
) -> _Minute:
    digest = hashlib.sha256(f"{seed}:flight:{thing_id}:{tick}:{ordinal}".encode()).digest()
    heading = int.from_bytes(digest[:8], "big") % _FULL_TURN
    cosine, sine = turn(heading)
    turn_cosine, turn_sine = turn(figures.turn_rate_mrad_per_s * _STEP_MS)
    return _Minute(
        air=air,
        figures=figures,
        half_span=figures.half_span_mm,
        turn_radius=figures.turn_radius_mm,
        speed_change=tdiv(figures.acceleration_mm_per_s2 * _STEP_MS, _MS_PER_S),
        turn_cosine=turn_cosine,
        turn_sine=turn_sine,
        tie_side=1 if digest[8] & 1 else -1,
        rest_heading=(tdiv(cosine * 1000, ONE), tdiv(sine * 1000, ONE)),
    )


# -- columns under a body ---------------------------------------------------------------------


def _box(air: AirColumns, low_x: int, high_x: int, low_y: int, high_y: int) -> Span | None:
    """The columns a closed box meets, or None where any of the box lies outside the air."""
    if (
        low_x < air.origin_x_mm
        or low_y < air.origin_y_mm
        or high_x >= air.end_x_mm
        or high_y >= air.end_y_mm
    ):
        return None
    size = air.column_mm
    return (
        (low_x - air.origin_x_mm) // size,
        (high_x - air.origin_x_mm) // size,
        (low_y - air.origin_y_mm) // size,
        (high_y - air.origin_y_mm) // size,
    )


def _clipped(air: AirColumns, low_x: int, high_x: int, low_y: int, high_y: int) -> Span | None:
    """The columns the part of a closed box inside the air meets, or None where none of it is."""
    return (
        _box(
            air,
            max(low_x, air.origin_x_mm),
            min(high_x, air.end_x_mm - 1),
            max(low_y, air.origin_y_mm),
            min(high_y, air.end_y_mm - 1),
        )
        if max(low_x, air.origin_x_mm) <= min(high_x, air.end_x_mm - 1)
        and max(low_y, air.origin_y_mm) <= min(high_y, air.end_y_mm - 1)
        else None
    )


def _rows(air: AirColumns, span: Span) -> Iterator[Sequence[int]]:
    """The tops of a span's columns, one row of them at a time."""
    ix0, ix1, iy0, iy1 = span
    tops, row = air.tops_mm, air.columns_x
    for start in range(iy0 * row, iy1 * row + 1, row):
        yield tops[start + ix0 : start + ix1 + 1]


def _highest(air: AirColumns, span: Span) -> int:
    """The tallest top among a span's columns."""
    return max(max(row) for row in _rows(air, span))


def _floor(minute: _Minute, span: Span, low: bool, *, over: bool = False) -> int:
    """The lowest a body over a span's columns may fly: its clearance above their tallest top, or
    the ground where ``low`` allows it and every one of them is open.

    ``over`` counts only the columns the kind can fly over, for the height it aims at: one it
    cannot fly over is gone round, by a route, and the guard keeps it out.
    """
    if over:
        limit = minute.air.ceiling_mm - minute.figures.clearance_mm
        top = max(
            max((top for top in row if top <= limit), default=0) for row in _rows(minute.air, span)
        )
    else:
        top = _highest(minute.air, span)
    if low and top == 0:
        return 0
    return top + minute.figures.clearance_mm


def _body_span(minute: _Minute, x: int, y: int) -> Span | None:
    reach = minute.half_span
    return _box(minute.air, x - reach, x + reach, y - reach, y + reach)


def _open_place(minute: _Minute, x: int, y: int) -> bool:
    """Whether every column within half the span of a point lies in the air and is open."""
    span = _body_span(minute, x, y)
    return span is not None and _highest(minute.air, span) == 0


def _legal(minute: _Minute, x: int, y: int, height: int, low: bool) -> bool:
    span = _body_span(minute, x, y)
    return (
        span is not None
        and 0 <= height <= minute.air.ceiling_mm
        and height >= _floor(minute, span, low)
    )


def _admits(minute: _Minute, start: _Body, x: int, y: int, height: int, low: bool) -> bool:
    """The guard: whether the move from ``start`` to ``(x, y, height)`` keeps the body inside the
    air, under the ceiling and, at the lower of its two heights, over everything the box it sweeps
    meets: its clearance above their tops, or, where ``low`` allows it, the ground over open
    ones."""
    reach = minute.half_span
    span = _box(
        minute.air,
        min(start.x, x) - reach,
        max(start.x, x) + reach,
        min(start.y, y) - reach,
        max(start.y, y) + reach,
    )
    if span is None:
        return False
    bottom, top = min(start.height, height), max(start.height, height)
    return bottom >= 0 and top <= minute.air.ceiling_mm and bottom >= _floor(minute, span, low)


def _flyable(minute: _Minute) -> Callable[[int], bool]:
    """Whether a column of a top is flyable for the kind: the top and its clearance under the
    ceiling."""
    limit = minute.air.ceiling_mm - minute.figures.clearance_mm
    return lambda top: top <= limit


def _ring_blocked(
    minute: _Minute, centre: Point, radius: int, blocked: Callable[[int], bool]
) -> bool:
    """Whether a body circling ``centre`` at ``radius`` would leave the air, or pass over a column
    whose top ``blocked`` refuses: every column the ring as wide as the body meets is asked."""
    air = minute.air
    outer = radius + minute.half_span
    inner = radius - minute.half_span
    cx, cy = centre
    span = _box(air, cx - outer, cx + outer, cy - outer, cy + outer)
    if span is None:
        return True
    ix0, ix1, iy0, iy1 = span
    size = air.column_mm
    for iy in range(iy0, iy1 + 1):
        low_y = air.origin_y_mm + iy * size - cy
        high_y = low_y + size
        near_y = max(low_y, 0, -high_y)
        far_y = max(-low_y, high_y)
        row = iy * air.columns_x
        for ix in range(ix0, ix1 + 1):
            if not blocked(air.tops_mm[row + ix]):
                continue
            low_x = air.origin_x_mm + ix * size - cx
            high_x = low_x + size
            near_x = max(low_x, 0, -high_x)
            far_x = max(-low_x, high_x)
            meets_outer = near_x * near_x + near_y * near_y <= outer * outer
            meets_inner = inner <= 0 or far_x * far_x + far_y * far_y >= inner * inner
            if meets_outer and meets_inner:
                return True
    return False


def _clear_line(minute: _Minute, ax: int, ay: int, bx: int, by: int) -> bool:
    """Whether a body flying straight from ``(ax, ay)`` to ``(bx, by)`` stays inside the air over
    flyable columns, looked at a column's length at a time."""
    air = minute.air
    limit = air.ceiling_mm - minute.figures.clearance_mm
    reach = minute.half_span
    dx, dy = bx - ax, by - ay
    pieces = max(1, ceil_div(isqrt(dx * dx + dy * dy), air.column_mm))
    last_x, last_y = ax, ay
    for index in range(1, pieces + 1):
        x, y = ax + tdiv(dx * index, pieces), ay + tdiv(dy * index, pieces)
        span = _box(
            air,
            min(last_x, x) - reach,
            max(last_x, x) + reach,
            min(last_y, y) - reach,
            max(last_y, y) + reach,
        )
        if span is None or _highest(air, span) > limit:
            return False
        last_x, last_y = x, y
    return True


# -- routes -----------------------------------------------------------------------------------


def _centre(air: AirColumns, column: Column) -> Point:
    half = air.column_mm // 2
    return (
        air.origin_x_mm + column[0] * air.column_mm + half,
        air.origin_y_mm + column[1] * air.column_mm + half,
    )


def _passable(minute: _Minute, column: Column) -> bool:
    """Whether a route may pass a column: a body at its centre over flyable columns only."""
    known = minute.passable.get(column)
    if known is None:
        x, y = _centre(minute.air, column)
        span = _body_span(minute, x, y)
        known = span is not None and _flyable(minute)(_highest(minute.air, span))
        minute.passable[column] = known
    return known


def _route(
    minute: _Minute,
    start: Column,
    aim: Column,
    goal: Callable[[Column], bool],
    *,
    goal_unchecked: bool,
) -> list[Column] | None:
    """The columns from ``start`` to the first column ``goal`` accepts, over columns a route may
    pass, or None where there is no such way within ``route_cells`` settled columns.

    A* over the air's columns, four neighbours, the Manhattan distance to ``aim`` its estimate,
    ties broken toward the way already travelled and then by column, so the same state finds the
    same route anywhere. ``goal_unchecked`` lets a goal column be entered whether or not a route
    may pass it, as a landing point's own column is.
    """
    air = minute.air

    def estimate(column: Column) -> int:
        return abs(column[0] - aim[0]) + abs(column[1] - aim[1])

    queue: list[tuple[int, int, Column]] = [(estimate(start), 0, start)]
    cost = {start: 0}
    came: dict[Column, Column] = {}
    settled = 0
    while queue:
        _, negative, column = heapq.heappop(queue)
        travelled = -negative
        if travelled != cost[column]:
            continue
        settled += 1
        if settled > _ROUTE_CELLS:
            return None
        if goal(column):
            path = []
            while column != start:
                path.append(column)
                column = came[column]
            path.reverse()
            return path
        for dx, dy in _NEIGHBOURS:
            near = (column[0] + dx, column[1] + dy)
            if not (0 <= near[0] < air.columns_x and 0 <= near[1] < air.columns_y):
                continue
            if not (_passable(minute, near) or (goal_unchecked and goal(near))):
                continue
            if travelled + 1 >= cost.get(near, travelled + 2):
                continue
            cost[near] = travelled + 1
            came[near] = column
            heapq.heappush(queue, (travelled + 1 + estimate(near), -(travelled + 1), near))
    return None


def _along_route(minute: _Minute, plan: _Plan, body: _Body) -> Point | None:
    """The velocity along the flyer's route, or None once no waypoint is left.

    Every waypoint up to the furthest of the next few whose column the flyer is in is passed; it
    then aims at the furthest of the next few it can fly straight to, slowing as the way it must
    turn grows, to a quarter of its cruise speed for a turn of a right angle or more.
    """
    route = plan.route
    if not route:
        return None
    air = minute.air
    here = air.column_of(body.x, body.y)
    ahead = route[:_ROUTE_AHEAD]
    reached = max(
        (index for index, point in enumerate(ahead) if air.column_of(*point) == here), default=-1
    )
    del route[: reached + 1]
    if not route:
        return None
    target = route[0]
    for point in route[1:_ROUTE_AHEAD]:
        if not _clear_line(minute, body.x, body.y, *point):
            break
        target = point
    offset = (target[0] - body.x, target[1] - body.y)
    cruise = minute.figures.cruise_mm_per_s
    speed = cruise
    moving = isqrt(body.vx * body.vx + body.vy * body.vy)
    distance = isqrt(offset[0] * offset[0] + offset[1] * offset[1])
    if moving and distance:
        along = body.vx * offset[0] + body.vy * offset[1]
        speed = max(cruise // 4, tdiv(cruise * (moving * distance + along), 2 * moving * distance))
    return _scaled(offset, speed)


# -- steering ---------------------------------------------------------------------------------


def _scaled(vector: Point, size: int) -> Point:
    """A plan vector scaled to ``size``, each part truncated; zero stays zero."""
    scaled = scale_to((vector[0], vector[1], 0), size)
    return (scaled[0], scaled[1])


def _heading(minute: _Minute, body: _Body) -> Point:
    """Where a flyer is heading: its horizontal velocity, or the minute's drawn heading at rest."""
    if body.vx or body.vy:
        return (body.vx, body.vy)
    return minute.rest_heading


def _orbit_speed(minute: _Minute, radius: int) -> int:
    """The speed a flyer circles at: the most its turn holds on the circle, less a tenth."""
    share, whole = _ORBIT_SHARE
    held = radius * minute.figures.turn_rate_mrad_per_s // _MICRO_PER_MILLI
    return min(minute.figures.cruise_mm_per_s, held * share // whole)


def _orbit(minute: _Minute, body: _Body, centre: Point, radius: int, side: int) -> Point:
    """The velocity that brings a flyer onto a circle and around it, counter-clockwise seen from
    above for ``side`` 1 and clockwise for -1: outside the circle, toward the point where its way
    meets the circle as a tangent; inside, out along a spiral; on it, along it."""
    ux, uy = body.x - centre[0], body.y - centre[1]
    distance = isqrt(ux * ux + uy * uy)
    far = distance > 2 * radius
    speed = minute.figures.cruise_mm_per_s if far else _orbit_speed(minute, radius)
    if distance == 0:
        return _scaled(_heading(minute, body), speed)
    tx, ty = (-uy, ux) if side > 0 else (uy, -ux)
    if distance > radius:
        along = isqrt(distance * distance - radius * radius)
        return _scaled((tx * radius - ux * along, ty * radius - uy * along), speed)
    outward = radius - distance
    return _scaled((tx * radius + ux * outward, ty * radius + uy * outward), speed)


def _side(minute: _Minute, body: _Body, centre: Point) -> int:
    """The way a flyer goes around a point: the way it is already going, or the minute's draw."""
    cross = (body.x - centre[0]) * body.vy - (body.y - centre[1]) * body.vx
    if cross:
        return 1 if cross > 0 else -1
    return minute.tie_side


def _turned(minute: _Minute, vx: int, vy: int, side: int) -> Point:
    """A velocity turned by the most the flyer turns in a step, to its left for ``side`` 1."""
    cosine, sine = minute.turn_cosine, side * minute.turn_sine
    return (tdiv(vx * cosine - vy * sine, ONE), tdiv(vx * sine + vy * cosine, ONE))


def _steer(minute: _Minute, body: _Body, desired: Point, climb: int) -> tuple[int, int, int]:
    """The velocity after one step of steering toward ``desired`` and the vertical speed
    ``climb``.

    The velocity change a step wants is the desired velocity less the current one. Its part along
    the current heading changes the speed, by at most the kind's acceleration over the step; its
    part across turns the heading toward the desired one, by at most the kind's turn rate over the
    step and never past it, so the turning acceleration is at most speed times turn rate. The speed
    is at most the cruise speed. From rest the change is taken whole, within the acceleration. The
    vertical speed moves toward ``climb`` by at most the acceleration and stays within the climb
    and descent rates.
    """
    figures = minute.figures
    change = minute.speed_change
    vx, vy = body.vx, body.vy
    dx, dy = desired
    speed = isqrt(vx * vx + vy * vy)
    if speed == 0:
        size = min(change, figures.cruise_mm_per_s, isqrt(dx * dx + dy * dy))
        nx, ny = _scaled((dx, dy), size)
    else:
        cross, along = vx * dy - vy * dx, vx * dx + vy * dy
        hx, hy = vx, vy
        if cross or along < 0:
            side = (1 if cross > 0 else -1) if cross else minute.tie_side
            hx, hy = _turned(minute, vx, vy, side)
            after = hx * dy - hy * dx
            if cross and (after == 0 or (after > 0) != (cross > 0)):
                # A whole turn would carry it past the desired heading: it takes that heading.
                hx, hy = dx, dy
        wanted = tdiv(along, speed) - speed
        size = max(0, min(figures.cruise_mm_per_s, speed + max(-change, min(change, wanted))))
        nx, ny = _scaled((hx, hy), size)
    vz = body.vz + max(-change, min(change, climb - body.vz))
    vz = max(-figures.descent_mm_per_s, min(figures.climb_mm_per_s, vz))
    return nx, ny, vz


def _climb(minute: _Minute, body: _Body, target: int) -> int:
    """The vertical speed a flyer wants toward its target height: as fast as its climb or descent
    allows, but no faster than it can stop at the target, changing its vertical speed by at most
    its acceleration a step."""
    error = target - body.height
    if error == 0:
        return 0
    change = minute.speed_change
    distance = abs(error)
    # Braking from v by `change` a step covers about v * (v + change) * step / (2 * change).
    stopping = (
        isqrt(change * change + 8 * _MS_PER_S * change * distance // _STEP_MS) - change
    ) // 2
    figures = minute.figures
    limit = figures.climb_mm_per_s if error > 0 else figures.descent_mm_per_s
    speed = min(limit, stopping, distance * _MS_PER_S // _STEP_MS)
    return speed if error > 0 else -speed


def _looked_along(
    minute: _Minute, body: _Body, velocity: Point, low: bool
) -> tuple[int, int | None]:
    """The lowest the flyer may fly over the columns its body would pass in three seconds at
    ``velocity``, looked at a column's length at a time, and how far it may go along that way
    before the first of them needs it higher than it is, or None where none does. Columns beyond
    the air are not counted."""
    air = minute.air
    reach = minute.half_span
    ahead_x = tdiv(velocity[0] * _LOOKAHEAD_MS, _MS_PER_S)
    ahead_y = tdiv(velocity[1] * _LOOKAHEAD_MS, _MS_PER_S)
    distance = isqrt(ahead_x * ahead_x + ahead_y * ahead_y)
    pieces = ceil_div(distance, air.column_mm)
    floor, block = 0, None
    last_x, last_y = body.x, body.y
    for index in range(1, pieces + 1):
        x, y = body.x + tdiv(ahead_x * index, pieces), body.y + tdiv(ahead_y * index, pieces)
        span = _clipped(
            air,
            min(last_x, x) - reach,
            max(last_x, x) + reach,
            min(last_y, y) - reach,
            max(last_y, y) + reach,
        )
        if span is not None:
            here = _floor(minute, span, low, over=True)
            if here > body.height and block is None:
                block = max(0, distance * (index - 1) // pieces - reach)
            floor = max(floor, here)
        last_x, last_y = x, y
    return floor, block


def _height_target(
    minute: _Minute, body: _Body, desired: Point, height: int, low: bool
) -> tuple[int, Point]:
    """The height a flyer aims at, and the velocity it may want on the way.

    The height is what its goal asks, or its clearance above the columns under it and ahead,
    along its heading and along the way it wants to go, where that is higher, never above the
    ceiling. Where a column ahead on the way it wants to go needs it higher than it is, it slows
    so that it climbs that far before it gets there, and can stop short of it.
    """
    air = minute.air
    reach = minute.half_span
    span = _clipped(air, body.x - reach, body.x + reach, body.y - reach, body.y + reach)
    floor = 0 if span is None else _floor(minute, span, low, over=True)
    heading_floor, _ = _looked_along(minute, body, (body.vx, body.vy), low)
    wanted_floor, block = _looked_along(minute, body, desired, low)
    target = min(air.ceiling_mm, max(height, floor, heading_floor, wanted_floor))
    if block is not None and target > body.height:
        figures = minute.figures
        climb = target - body.height
        allowed = min(
            block * figures.climb_mm_per_s // climb,
            isqrt(2 * figures.acceleration_mm_per_s2 * block),
        )
        if allowed < isqrt(desired[0] * desired[0] + desired[1] * desired[1]):
            desired = _scaled(desired, allowed)
    return target, desired


def _move(speed: int) -> int:
    """How far a speed carries a flyer in one step."""
    return tdiv(speed * _STEP_MS, _MS_PER_S)


def _guarded(minute: _Minute, body: _Body, velocity: tuple[int, int, int], low: bool) -> _Body:
    """The step the guard lets a flyer take: the move steering proposed when it is legal, else
    the parts of it that are, level first, then vertical, then along each axis of the ground; else
    it holds where it is. A flyer that starts the step where it may not be climbs straight toward
    its clearance, or comes down under the ceiling, unless the steered move ends where it may be."""
    vx, vy, vz = velocity
    if not _legal(minute, body.x, body.y, body.height, low):
        return _recovered(minute, body, velocity, low)
    proposals = ((vx, vy, vz), (vx, vy, 0), (0, 0, vz), (vx, 0, 0), (0, vy, 0))
    for index, (px, py, pz) in enumerate(proposals):
        mx, my, mz = _move(px), _move(py), _move(pz)
        if (mx, my, mz) == (0, 0, 0):
            if index == 0:
                # Too slow to move a millimetre this step: it keeps its velocity where it is.
                return replace(body, vx=vx, vy=vy, vz=vz, held=False)
            continue
        x, y, height = body.x + mx, body.y + my, body.height + mz
        if _admits(minute, body, x, y, height, low):
            return _Body(x, y, height, px, py, pz, flying=True, held=index > 0)
    return _Body(body.x, body.y, body.height, 0, 0, 0, flying=True, held=True)


def _recovered(minute: _Minute, body: _Body, velocity: tuple[int, int, int], low: bool) -> _Body:
    """The step of a flyer that starts it where it may not be, as after a column was placed under
    it: the steered move where it ends where the flyer may be; else straight down under the
    ceiling, or straight up toward its clearance where the ceiling leaves room for it; else away
    from the columns under it it cannot fly over, and from the air's sides, at the speed its
    acceleration gives it in a step. Each is a step the guard held."""
    vx, vy, vz = velocity
    x, y, height = body.x + _move(vx), body.y + _move(vy), body.height + _move(vz)
    if _legal(minute, x, y, height, low):
        return _Body(x, y, height, vx, vy, vz, flying=True, held=True)
    figures = minute.figures
    ceiling = minute.air.ceiling_mm
    if body.height > ceiling:
        rate = -figures.descent_mm_per_s
        lower = max(ceiling, body.height + _move(rate))
        return _Body(body.x, body.y, lower, 0, 0, rate, flying=True, held=True)
    span = _body_span(minute, body.x, body.y)
    if span is not None and body.height < _floor(minute, span, low) <= ceiling:
        rate = figures.climb_mm_per_s
        higher = min(_floor(minute, span, low), body.height + _move(rate))
        return _Body(body.x, body.y, higher, 0, 0, rate, flying=True, held=True)
    speed = min(figures.cruise_mm_per_s, max(isqrt(vx * vx + vy * vy), minute.speed_change))
    ax, ay = _scaled(_away(minute, body), speed)
    return _Body(body.x + _move(ax), body.y + _move(ay), body.height, ax, ay, 0, True, True)


def _away(minute: _Minute, body: _Body) -> Point:
    """The way out from under what a flyer cannot fly over: away from the centres of those
    columns under its body, and in from the air's sides it reaches past; the minute's drawn
    heading where that leaves no way."""
    air = minute.air
    reach = minute.half_span
    limit = air.ceiling_mm - minute.figures.clearance_mm
    ax = ay = 0
    span = _clipped(air, body.x - reach, body.x + reach, body.y - reach, body.y + reach)
    if span is not None:
        ix0, ix1, iy0, iy1 = span
        for iy in range(iy0, iy1 + 1):
            for ix in range(ix0, ix1 + 1):
                if air.top((ix, iy)) > limit:
                    cx, cy = _centre(air, (ix, iy))
                    ax, ay = ax + body.x - cx, ay + body.y - cy
    size = air.column_mm
    ax += size * ((body.x - reach < air.origin_x_mm) - (body.x + reach >= air.end_x_mm))
    ay += size * ((body.y - reach < air.origin_y_mm) - (body.y + reach >= air.end_y_mm))
    return (ax, ay) if (ax, ay) != (0, 0) else minute.rest_heading


# -- plans ------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Plan:
    """How one flyer flies one minute, decided from its state at the minute's start."""

    goal: _Goal
    refusal: str | None = None
    #: Once airborne and risen: ``orbit`` a circle, ``land``, ``hover`` where it is, or stay on
    #: the ``ground``.
    behaviour: str = "ground"
    centre: Point = (0, 0)
    radius: int = 0
    side: int = 1
    #: The centres of the columns still ahead on its route, or empty with no route.
    route: list[Point] = field(default_factory=list)
    #: Landing, whether it may come down a spiral around the point.
    spiral: bool = False
    #: The height a hovering flyer holds.
    hold_mm: int = 0
    #: Whether it leaves the ground at the minute's start.
    takes_off: bool = False
    #: Whether it is still climbing from the ground: over open ground below its clearance.
    rising: bool = False
    #: The circle it climbs around while rising, its side and radius; None to rise straight up.
    rise_centre: Point | None = None
    rise_side: int = 1
    rise_radius: int = 0


def _risen(minute: _Minute, body: _Body) -> bool:
    """Whether a flyer is at or above its clearance over the columns under it."""
    span = _body_span(minute, body.x, body.y)
    return span is None or body.height >= _floor(minute, span, low=False)


def _low_over_open_ground(minute: _Minute, body: _Body) -> bool:
    """Whether a flyer in flight is below its clearance over open ground: still taking off."""
    return body.flying and not _risen(minute, body) and _open_place(minute, body.x, body.y)


def _circle_beside(
    minute: _Minute, body: _Body, blocked: Callable[[int], bool]
) -> tuple[Point, int, int] | None:
    """The circle a flyer turns on from where it is, with its centre, the side it goes around and
    its radius: its smallest turn at its cruise speed, to its left where nothing ``blocked``
    refuses lies under the circle, else to its right; failing both, the same at three quarters,
    half and a quarter of that radius, flown as much slower; None where no circle fits."""
    hx, hy = _heading(minute, body)
    for quarters in _CIRCLE_QUARTERS:
        radius = max(1, minute.turn_radius * quarters // 4)
        left = _scaled((-hy, hx), radius)
        for side, (ox, oy) in ((1, left), (-1, (-left[0], -left[1]))):
            centre = (body.x + ox, body.y + oy)
            if not _ring_blocked(minute, centre, radius, blocked):
                return centre, side, radius
    return None


def _stay(minute: _Minute, body: _Body, plan: _Plan, *, airborne: bool) -> None:
    """A minute of staying: on the ground a grounded flyer stays there; in the air a hovering kind
    slows to rest where it is, and a winged one circles where it is (:func:`_circle_beside`) over
    columns it can fly over, or, where no circle fits, slows to rest where it is."""
    if not airborne:
        plan.behaviour = "ground"
        return
    found = None
    if not minute.figures.hovers:
        found = _circle_beside(minute, body, lambda top: not _flyable(minute)(top))
    if found is None:
        plan.behaviour, plan.hold_mm = "hover", body.height
        return
    plan.behaviour = "orbit"
    plan.centre, plan.side, plan.radius = found


def _orbit_aim(body: _Body, centre: Point, radius: int, side: int) -> Point:
    """Where a flyer first meets its circle: the point its way touches the circle as a tangent
    from outside, the nearest point of the circle from inside."""
    ux, uy = body.x - centre[0], body.y - centre[1]
    distance = isqrt(ux * ux + uy * uy)
    if distance == 0:
        return (centre[0] + radius, centre[1])
    if distance <= radius:
        return (centre[0] + tdiv(ux * radius, distance), centre[1] + tdiv(uy * radius, distance))
    along = isqrt(distance * distance - radius * radius)
    tx, ty = (-uy, ux) if side > 0 else (uy, -ux)
    # The tangent's direction has length distance squared; the tangent point is `along` along it.
    square = distance * distance
    return (
        body.x + tdiv((tx * radius - ux * along) * along, square),
        body.y + tdiv((ty * radius - uy * along) * along, square),
    )


def _orbit_route(minute: _Minute, body: _Body, plan: _Plan) -> list[Point] | None:
    """The route onto the plan's circle where the straight way to it is blocked, [] where it is
    clear, or None where no route reaches it."""
    air = minute.air
    aim = _orbit_aim(body, plan.centre, plan.radius, plan.side)
    if _clear_line(minute, body.x, body.y, *aim):
        return []
    start = air.column_of(body.x, body.y)
    aim_column = air.column_of(*aim)
    assert start is not None and aim_column is not None
    band = air.column_mm

    def on_circle(column: Column) -> bool:
        if not _passable(minute, column):
            return False
        x, y = _centre(air, column)
        distance = isqrt((x - plan.centre[0]) ** 2 + (y - plan.centre[1]) ** 2)
        return plan.radius - band <= distance <= plan.radius + band

    columns = _route(minute, start, aim_column, on_circle, goal_unchecked=False)
    return None if columns is None else [_centre(air, column) for column in columns]


def _landing_route(minute: _Minute, body: _Body, point: Point) -> list[Point] | None:
    """The route to a landing point where the straight way to it is blocked, [] where it is
    clear, or None where no route reaches it."""
    air = minute.air
    if _clear_line(minute, body.x, body.y, *point):
        return []
    start = air.column_of(body.x, body.y)
    aim = air.column_of(*point)
    assert start is not None and aim is not None
    columns = _route(minute, start, aim, lambda column: column == aim, goal_unchecked=True)
    return None if columns is None else [_centre(air, column) for column in columns]


def _refused(minute: _Minute, body: _Body, goal: _Goal, code: str) -> _Plan:
    """A refused goal's minute: the refusal named, and the flyer staying."""
    plan = _Plan(goal, refusal=code)
    _stay(minute, body, plan, airborne=body.flying)
    _rise_if_low(minute, body, plan)
    return plan


def _rise_if_low(minute: _Minute, body: _Body, plan: _Plan) -> None:
    """A flyer leaving the ground, or still below its clearance over open ground, climbs first:
    around the circle of its smallest turn through where it is, where the ground under that circle
    is open, else straight up; a hovering kind rises straight up."""
    if not (plan.takes_off or _low_over_open_ground(minute, body)):
        return
    plan.rising = True
    if not minute.figures.hovers:
        found = _circle_beside(minute, body, lambda top: top > 0)
        if found is not None:
            plan.rise_centre, plan.rise_side, plan.rise_radius = found


def _plan(minute: _Minute, body: _Body, goal: _Goal) -> _Plan:
    """How a flyer flies its minute toward ``goal``, or the goal's refusal by name."""
    air = minute.air
    kind = goal.kind
    if kind not in SERVED_GOALS:
        return _refused(minute, body, goal, "not_served_by_module")
    point = goal.point
    if kind == "keep_near" and point is None:
        return _refused(minute, body, goal, "target_gone")
    if point is not None and air.column_of(*point) is None:
        code = {"keep_near": "lost_target", "go_near": "no_route", "circle": "circle_blocked"}
        return _refused(minute, body, goal, code.get(kind, "no_room_to_land"))
    plan = _Plan(goal)
    grounded = not body.flying
    if kind in _ORBITS:
        assert point is not None
        radius = max(goal.distance, minute.turn_radius)
        if _ring_blocked(minute, point, radius, lambda top: not _flyable(minute)(top)):
            return _refused(minute, body, goal, "circle_blocked")
        plan.behaviour, plan.centre, plan.radius = "orbit", point, radius
        plan.side = _side(minute, body, point)
    elif kind == "land":
        assert point is not None
        if not _open_place(minute, *point):
            return _refused(minute, body, goal, "no_room_to_land")
        if grounded and (body.x, body.y) == point:
            return plan
        plan.behaviour, plan.centre = "land", point
        plan.side = _side(minute, body, point)
        plan.spiral = not minute.figures.hovers and not _ring_blocked(
            minute, point, minute.turn_radius, lambda top: top > 0
        )
    else:
        _stay(minute, body, plan, airborne=body.flying or kind == "take_off")
        if kind == "take_off":
            # Taking off ends at the band: a kind that hovers holds there, not where it rose from.
            band = min(air.ceiling_mm, minute.figures.band_minimum_mm)
            plan.hold_mm = max(plan.hold_mm, band)
    if grounded and plan.behaviour != "ground":
        if not _open_place(minute, body.x, body.y) or not _flyable(minute)(0):
            return _refused(minute, body, goal, "no_room_to_rise")
        plan.takes_off = True
    if kind in _ORBITS or kind == "land":
        assert point is not None
        if kind == "land":
            route = _landing_route(minute, body, point)
        else:
            route = _orbit_route(minute, body, plan)
        if route is None:
            return _refused(minute, body, goal, "no_route")
        plan.route = route
    _rise_if_low(minute, body, plan)
    return plan


# -- a step -----------------------------------------------------------------------------------


def _glide(minute: _Minute, distance: int) -> int:
    """The height of the glide path a landing follows at ``distance`` from its point: its descent
    over its cruise speed for each millimetre beyond touching down, never above its band."""
    figures = minute.figures
    slope = max(0, distance - _TOUCHDOWN_MM) * figures.descent_mm_per_s
    return min(figures.band_minimum_mm, slope // figures.cruise_mm_per_s)


def _landing(minute: _Minute, plan: _Plan, body: _Body) -> tuple[Point, int]:
    """The velocity and height a landing flyer wants: along its route while it has one; down a
    spiral around the point while it is within two of its smallest turns and above the glide
    path there; else toward the point, slowing as it nears it, down the glide path."""
    point = plan.centre
    dx, dy = point[0] - body.x, point[1] - body.y
    distance = isqrt(dx * dx + dy * dy)
    along = _along_route(minute, plan, body)
    if along is not None:
        return along, _glide(minute, distance)
    radius = minute.turn_radius
    if plan.spiral and distance <= 2 * radius and body.height > _glide(minute, 2 * radius):
        return _orbit(minute, body, point, radius, plan.side), _glide(minute, radius)
    figures = minute.figures
    speed = min(
        figures.cruise_mm_per_s,
        distance * figures.turn_rate_mrad_per_s // (2 * _MICRO_PER_MILLI),
    )
    return _scaled((dx, dy), speed), _glide(minute, distance)


def _touchdown(minute: _Minute, plan: _Plan, body: _Body) -> _Body | None:
    """A landing flyer near enough its point and low enough to reach the ground in one step
    touches down on the point, as the guard allows; None otherwise."""
    point = plan.centre
    dx, dy = point[0] - body.x, point[1] - body.y
    if dx * dx + dy * dy > _TOUCHDOWN_MM * _TOUCHDOWN_MM:
        return None
    if body.height > _move(minute.figures.descent_mm_per_s):
        return None
    if not _admits(minute, body, point[0], point[1], 0, low=True):
        return None
    return _Body(point[0], point[1], 0, 0, 0, 0, flying=False)


def _step(minute: _Minute, plan: _Plan, body: _Body) -> _Body:
    """One step: steer toward what the plan asks, then move as far as the guard lets."""
    if not body.flying:
        return replace(body, held=False)
    if plan.rising and _risen(minute, body):
        plan.rising = False
    figures = minute.figures
    low_target = low_guard = False
    if plan.rising:
        if plan.rise_centre is None:
            desired: Point = (0, 0)
        else:
            desired = _orbit(minute, body, plan.rise_centre, plan.rise_radius, plan.rise_side)
        height, low_guard = figures.band_minimum_mm, True
    elif plan.behaviour == "land":
        landed = _touchdown(minute, plan, body)
        if landed is not None:
            return landed
        desired, height = _landing(minute, plan, body)
        low_target = low_guard = True
    elif plan.behaviour == "hover":
        desired, height = (0, 0), plan.hold_mm
    else:
        along = _along_route(minute, plan, body)
        if along is None:
            along = _orbit(minute, body, plan.centre, plan.radius, plan.side)
        desired, height = along, figures.band_minimum_mm
    target, desired = _height_target(minute, body, desired, height, low_target)
    velocity = _steer(minute, body, desired, _climb(minute, body, target))
    return _guarded(minute, body, velocity, low_guard)


# -- a minute ---------------------------------------------------------------------------------


def _status(minute: _Minute, plan: _Plan, body: _Body) -> str:
    """Whether the goal holds when the minute ends: ``reached``, ``under_way`` or ``refused``."""
    if plan.refusal is not None:
        return "refused"
    kind = plan.goal.kind
    if kind == "stay":
        return "reached"
    if kind == "land":
        return "reached" if not body.flying and (body.x, body.y) == plan.goal.point else "under_way"
    if kind == "take_off":
        band = min(minute.air.ceiling_mm, minute.figures.band_minimum_mm)
        risen = body.flying and _risen(minute, body) and body.height >= band
        return "reached" if risen else "under_way"
    ux, uy = body.x - plan.centre[0], body.y - plan.centre[1]
    distance = isqrt(ux * ux + uy * uy)
    slack = _ring_slack(minute, plan.radius)
    if kind == "circle":
        held = abs(distance - plan.radius) <= slack
    else:
        held = distance <= plan.radius + slack
    return "reached" if body.flying and held else "under_way"


def _ring_slack(minute: _Minute, radius: int) -> int:
    """How far from its circle a circling flyer may be and still be on it: a quarter of the
    radius, and never less than a column."""
    return max(radius // 4, minute.air.column_mm)


def fly_minute(
    air: AirColumns | Mapping[str, Any],
    flyer: Mapping[str, Any],
    goal: Mapping[str, Any],
    figures: FlyerFigures | Mapping[str, Any],
    seed: str,
    tick: int,
    ordinal: int,
) -> tuple[dict[str, Any], list[list[int]], dict[str, Any]]:
    """One society minute of one flyer: its state after the minute, its 60 waypoints and the
    minute's outcome.

    ``air`` is an :class:`AirColumns` or its document; ``flyer`` the being's state, whose
    ``position_mm``, ``mode``, ``height_mm`` and ``velocity_mm_s`` the minute reads and replaces,
    every other field kept as it was; ``goal`` one of :data:`SERVED_GOALS` with its fields;
    ``figures`` the kind's :class:`FlyerFigures` or its values; ``seed``, ``tick`` and ``ordinal``
    name the minute's one draw. The outcome is the ``flew`` event's payload: the goal's status,
    its refusal by name or None, the waypoints, the ``took_off`` and ``landed`` events with the
    millisecond of the minute each happened at, the steps the guard held and the air's digest.
    """
    _built()
    if not isinstance(air, AirColumns):
        air = air_columns(air)
    if not isinstance(figures, FlyerFigures):
        figures = flyer_figures(figures)
    thing_id, body = _read_flyer(air, flyer)
    wanted = _read_goal(goal)
    if not isinstance(seed, str) or not _whole(tick) or not _whole(ordinal):
        raise FlightMinuteRefused("invalid_flight_draw", "seed is text, tick and ordinal whole")
    minute = _minute(air, figures, seed, thing_id, tick, ordinal)
    plan = _plan(minute, body, wanted)
    events: list[dict[str, Any]] = []
    if plan.takes_off:
        body = _Body(body.x, body.y, 0, 0, 0, 0, flying=True)
        events.append({"kind": "took_off", "at_ms": 0})
    waypoints: list[list[int]] = []
    held = 0
    for index in range(1, _STEPS + 1):
        before = body
        body = _step(minute, plan, body)
        held += body.held
        if before.flying and not body.flying:
            # The millisecond the step it landed in began: 0 to 59,999, as every event of a
            # minute is placed.
            events.append({"kind": "landed", "at_ms": (index - 1) * _STEP_MS})
        if index % _STEPS_PER_WAYPOINT == 0:
            waypoints.append([body.x, body.y, body.height])
    after = dict(flyer)
    after["position_mm"] = [body.x, body.y]
    after.pop("height_mm", None)
    after.pop("velocity_mm_s", None)
    if body.flying:
        after["mode"] = "flight"
        after["height_mm"] = body.height
        if (body.vx, body.vy, body.vz) != (0, 0, 0):
            after["velocity_mm_s"] = [body.vx, body.vy, body.vz]
    else:
        after["mode"] = "walking"
    outcome = {
        "profile": MINUTE_PROFILE,
        "module": FLIGHT_V2,
        "goal": wanted.kind,
        "status": _status(minute, plan, body),
        "refusal": plan.refusal,
        "waypoints_mm": [list(point) for point in waypoints],
        "events": events,
        "held_steps": held,
        "air_sha256": air.sha256,
    }
    return after, waypoints, outcome
