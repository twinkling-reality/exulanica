"""Flight: the movement module that moves flying kinds through a world's air.

Each flyer is a point mass with integer position (mm) and velocity (mm/s), advanced in the module's
fixed steps. Four states:

- ``perching``: at rest on a declared perch, for a time drawn from its kind's range;
- ``taking_off``: climbing straight up the perch's column to its approach point;
- ``flying``: Reynolds steering (seek and arrive toward a perch's approach point, or wander),
  with obstacle avoidance over the occupancy grid and containment inside the volume and the
  kind's altitude band; turning is bounded as turning acceleration, at most speed times the
  kind's turn rate;
- ``landing``: descending straight down the column onto the perch.

**A guard has the last word.** Steering only proposes a velocity. Before a flying flyer moves,
every cell the closed box spanning its move meets must be free and the new position must lie in
the volume and the kind's band; otherwise the flyer holds where it is, at rest, and the hold is
counted. A landing or take-off moves only inside its perch's column. So no flyer is ever in, or
passes through, a solid cell other than its own perch's, whatever steering proposes.

**Choices are validated like a person's.** A flyer chooses only when its perch or its wander ends:
fly to a free perch, or wander for a while. The seeded chooser proposes, and
:func:`validate_choice`, the check a model's proposal would pass, decides whether the proposal
stands, with a named reason when it does not (``perch_not_declared`` and the rest).

**Episodes bound the cost of any step.** Every flyer starts an episode perching at its home perch
and spends the episode's last minute going home and landing. Going home, a flyer follows the
shortest route over free cells of its band from where it is to its home's approach point, found
once when it sets off and again whenever the guard has held it for a while. The state at an
episode's first step is its genesis, a function of the input and the episode alone, so the state at
any step is at most one episode of steps from a known one. A flyer not home at its episode's last
step is named in every window that holds that step, never moved quietly; the next episode starts
from its genesis all the same.

**Status is a switch.** The module's row is read when this module is imported; whether it is
built is asked only where a flight is made or served, so a row stated ``not_connected`` refuses
there, by its refusal, and nothing fails at import.

Every draw is ``sha256(seed:domain:step:ordinal)``, so the same input gives the same flight on any
machine. Pure: no connection, no store, no world, no floats.
"""

from __future__ import annotations

import hashlib
import heapq
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isqrt as math_isqrt
from types import MappingProxyType
from typing import Any, Final, Literal

from exulanica.canonical import canonical_json
from exulanica.movement.air import (
    AirVolume,
    Cell,
    Column,
    Occupancy,
    PerchSite,
    Solid,
    swept_cells,
)
from exulanica.movement.fixed import (
    Vector,
    add,
    ceil_div,
    clamp_length,
    cross_y,
    dot,
    length,
    scale_to,
    sub,
    tdiv,
)
from exulanica.movement.registry import FLIGHT, MovementModule, built_module, movement_module

__all__ = [
    "FLIGHT_MODULE",
    "STATES",
    "FlightInput",
    "FlightKind",
    "FlightRefused",
    "Flyer",
    "advance_flight",
    "check_request",
    "flight_window",
    "genesis",
    "state_at",
    "validate_choice",
    "window_from",
]

#: The module's row, read at import whatever its status; :func:`_built` asks for it built.
FLIGHT_MODULE: Final[MovementModule] = movement_module(FLIGHT)
STATE_PROFILE: Final = "exulanica.flight-state/v1"
WINDOW_PROFILE: Final = FLIGHT_MODULE.output_profile
STATES: Final = ("perching", "taking_off", "flying", "landing")
State = Literal["perching", "taking_off", "flying", "landing"]

_STEP_MS: Final = FLIGHT_MODULE.step_ms
_EPISODE: Final = FLIGHT_MODULE.value("episode_steps")
_HOMING: Final = FLIGHT_MODULE.value("homing_steps")
_LOOKAHEAD_MS: Final = FLIGHT_MODULE.value("lookahead_ms")
_MARGIN: Final = FLIGHT_MODULE.value("containment_margin_mm")
_SLOWING: Final = FLIGHT_MODULE.value("slowing_radius_mm")
_WANDER_DISTANCE: Final = FLIGHT_MODULE.value("wander_distance_mm")
_WANDER_RADIUS: Final = FLIGHT_MODULE.value("wander_radius_mm")
_WANDER_JITTER: Final = FLIGHT_MODULE.value("wander_jitter_mm")
_MAX_STEPS: Final = FLIGHT_MODULE.value("max_steps_per_request")
_MAX_FROM: Final = FLIGHT_MODULE.value("max_from_step")
_MS_PER_S: Final = 1000
#: The fraction of the lookahead each avoidance probe advances: four probes a lookahead, so at the
#: module's fastest speed probes land at most 500 mm apart, one cell, and none skips a cell.
_PROBES: Final = 4
#: How many headings around the vertical the avoidance fan looks along: every sixteenth of a turn,
#: 22.5 degrees, fine enough to find a gap a crown leaves and few enough to look along in a step.
_FAN_HEADINGS: Final = 16
#: A full turn in microradians, the unit a turn is computed in.
_TURN_MICRORADIANS: Final = 6_283_185
#: The fan's slope up and down, as a direction's vertical part out of 1000: 500, thirty degrees.
_FAN_SLOPE: Final = 500
#: A direction's length in the fan: its components are thousandths of a unit.
_UNIT: Final = 1000
#: The six neighbours a route steps to. A route moves from a cell to one sharing a face, so the
#: straight line between their centres stays inside the two cells.
_NEIGHBOURS: Final = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
#: Steps held in a row, going home, after which a flyer finds its way again from where it is.
_STUCK_STEPS: Final = 10
#: How many waypoints of its route a flyer looks along: those it may have passed, and those it may
#: aim straight at.
_ROUTE_AHEAD: Final = 4
#: Within this distance of the waypoint it aims at, a flyer slows, down to a quarter of its cruise
#: speed, so it enters the waypoint's cell rather than circling it.
_ROUTE_SLOWING: Final = 1500


def _built() -> MovementModule:
    """The flight row when it is built; a row stated otherwise refuses with its own refusal."""
    return built_module(FLIGHT)


class FlightRefused(ValueError):
    """A flight request or input the module refuses, by a code a caller can act on."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class FlightKind:
    """One flying kind's figures, each checked against the flight module's bounds."""

    key: str
    body_span_mm: int
    cruise_speed_mm_s: int
    max_speed_mm_s: int
    max_accel_mm_s2: int
    max_turn_rate_mrad_s: int
    climb_rate_mm_s: int
    descent_rate_mm_s: int
    takeoff_rate_mm_s: int
    landing_rate_mm_s: int
    min_altitude_mm: int
    max_altitude_mm: int
    approach_height_mm: int
    perch_seconds_minimum: int
    perch_seconds_maximum: int
    roam_seconds_minimum: int
    roam_seconds_maximum: int
    roam_weight_milli: int
    glide_speed_mm_s: int
    max_bank_mrad: int
    flap_cycle_ms: int

    @classmethod
    def checked(cls, key: str, values: Mapping[str, object]) -> FlightKind:
        """A kind from its stated values: exactly the parameters a kind supplies, each in bounds,
        and the orders between them that the step relies on."""
        where = f"flight kind {key}"
        supplied = FLIGHT_MODULE.supplied()
        if set(values) != set(supplied):
            raise FlightRefused("invalid_flight_kind", f"{where} states exactly {sorted(supplied)}")
        figures = {
            name: FLIGHT_MODULE.checked(name, values[name], where=where) for name in supplied
        }
        kind = cls(key=key, **figures)
        ceiling = FLIGHT_MODULE.value("ceiling_mm")
        orders = (
            (kind.cruise_speed_mm_s <= kind.max_speed_mm_s, "cruise speed is at most max speed"),
            (kind.glide_speed_mm_s <= kind.max_speed_mm_s, "glide speed is at most max speed"),
            (
                kind.min_altitude_mm + 2 * _MARGIN <= kind.max_altitude_mm < ceiling,
                "the altitude band is two containment margins deep and below the ceiling",
            ),
            (
                kind.perch_seconds_minimum <= kind.perch_seconds_maximum,
                "the shortest perch is at most the longest",
            ),
            (
                kind.roam_seconds_minimum <= kind.roam_seconds_maximum,
                "the shortest wander is at most the longest",
            ),
        )
        for holds, rule in orders:
            if not holds:
                raise FlightRefused("invalid_flight_kind", f"{where}: {rule}")
        return kind

    def document(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in ("key", *FLIGHT_MODULE.supplied())}


@dataclass(frozen=True, slots=True)
class Flyer:
    """One flyer: its identity, its kind, and the perch it starts every episode on."""

    flyer_id: str
    kind: str
    home_perch_id: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class FlightInput:
    """Everything a flight is computed from, bound by one digest."""

    world_id: str
    version_id: str
    seed: str
    volume: AirVolume
    occupancy: Occupancy
    perches: tuple[PerchSite, ...]
    kinds: Mapping[str, FlightKind]
    flyers: tuple[Flyer, ...]
    #: Flyers a world's objects host that could not be placed, each with its object, kind, count
    #: and reason; they are part of what the input says, and none of them flies.
    unplaced: tuple[Mapping[str, Any], ...]
    #: Every part of every placed object, as the grid was built from them.
    solids: tuple[Solid, ...]
    #: How far the grid grew every part: at least half every kind's span.
    clearance_mm: int
    sha256: str
    #: The perches by identity, derived from ``perches`` when the input is made.
    perch_index: Mapping[str, PerchSite]

    def column(self, perch_id: str, kind: str) -> Column:
        return self.perch_index[perch_id].columns[kind]


def input_document(
    *,
    world_id: str,
    version_id: str,
    seed: str,
    occupancy: Occupancy,
    perches: Sequence[PerchSite],
    kinds: Mapping[str, FlightKind],
    flyers: Sequence[Flyer],
    solids: Sequence[Solid],
    unplaced: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """The canonical description of an input, without its digest."""
    return {
        "profile": "exulanica.flight-input/v1",
        "module": FLIGHT,
        "world_id": world_id,
        "version_id": version_id,
        "seed_sha256": seed,
        "volume": occupancy.volume.document(),
        "clearance_mm": occupancy.clearance_mm,
        "occupancy_sha256": occupancy.sha256,
        "solids": [
            {
                "object_id": solid.object_id,
                "box_mm": [
                    solid.box.min_x_mm,
                    solid.box.max_x_mm,
                    solid.box.min_y_mm,
                    solid.box.max_y_mm,
                    solid.box.min_z_mm,
                    solid.box.max_z_mm,
                ],
                "placement": [
                    solid.placement.x_mm,
                    solid.placement.y_mm,
                    solid.placement.z_mm,
                    solid.placement.yaw_microradians,
                    solid.placement.scale_milli,
                ],
                "travel_mm": list(solid.travel_mm),
            }
            for solid in solids
        ],
        "perches": [perch.document() for perch in perches],
        "kinds": [kinds[key].document() for key in sorted(kinds)],
        "flyers": [
            {
                "flyer_id": flyer.flyer_id,
                "kind": flyer.kind,
                "home_perch_id": flyer.home_perch_id,
                "ordinal": flyer.ordinal,
            }
            for flyer in flyers
        ],
        "unplaced": [dict(row) for row in unplaced],
    }


def flight_input(
    *,
    world_id: str,
    version_id: str,
    seed: str,
    occupancy: Occupancy,
    perches: Sequence[PerchSite],
    kinds: Mapping[str, FlightKind],
    flyers: Sequence[Flyer],
    solids: Sequence[Solid],
    unplaced: Sequence[Mapping[str, Any]] = (),
) -> FlightInput:
    """A checked input: every flyer's home usable by its kind, one flyer to a home, within the
    module's population bound, over air grown by at least half of every kind's span."""
    _built()
    for key, kind in kinds.items():
        if ceil_div(kind.body_span_mm, 2) > occupancy.clearance_mm:
            raise FlightRefused(
                "invalid_flight_input",
                f"the air is grown by {occupancy.clearance_mm} mm, and a {key} is "
                f"{kind.body_span_mm} mm across",
            )
    by_id = {perch.perch_id: perch for perch in perches}
    if len(by_id) != len(perches):
        raise FlightRefused("invalid_flight_input", "a perch identity is stated twice")
    homes = [flyer.home_perch_id for flyer in flyers]
    if len(set(homes)) != len(homes):
        raise FlightRefused("invalid_flight_input", "two flyers share a home perch")
    limit = FLIGHT_MODULE.value("max_flyers")
    if len(flyers) > limit:
        raise FlightRefused(
            "too_many_flyers", f"a world's objects host {len(flyers)} flyers; at most {limit}"
        )
    if [flyer.ordinal for flyer in flyers] != list(range(len(flyers))):
        raise FlightRefused("invalid_flight_input", "flyers are numbered from 0 in order")
    for flyer in flyers:
        perch = by_id.get(flyer.home_perch_id)
        if flyer.kind not in kinds:
            raise FlightRefused("invalid_flight_input", f"no flight kind {flyer.kind!r}")
        if perch is None or flyer.kind not in perch.columns:
            reason = "perch_not_declared" if perch is None else perch.refused[flyer.kind]
            raise FlightRefused(
                "home_perch_unusable", f"flyer {flyer.flyer_id} cannot use its home: {reason}"
            )
    document = input_document(
        world_id=world_id,
        version_id=version_id,
        seed=seed,
        occupancy=occupancy,
        perches=perches,
        kinds=kinds,
        flyers=flyers,
        solids=solids,
        unplaced=unplaced,
    )
    return FlightInput(
        world_id=world_id,
        version_id=version_id,
        seed=seed,
        volume=occupancy.volume,
        occupancy=occupancy,
        perches=tuple(perches),
        kinds=dict(kinds),
        flyers=tuple(flyers),
        unplaced=tuple(MappingProxyType(dict(row)) for row in unplaced),
        solids=tuple(solids),
        clearance_mm=occupancy.clearance_mm,
        sha256=hashlib.sha256(canonical_json(document)).hexdigest(),
        perch_index=MappingProxyType(by_id),
    )


# -- draws ------------------------------------------------------------------------------------


def _digest(seed: str, domain: str, step: int, ordinal: int) -> bytes:
    return hashlib.sha256(f"{seed}:{domain}:{step}:{ordinal}".encode()).digest()


def _draw(seed: str, domain: str, step: int, ordinal: int, count: int) -> int:
    """An index below ``count`` drawn for one flyer at one step."""
    return int.from_bytes(_digest(seed, domain, step, ordinal)[:8], "big") % count


def _seconds_to_steps(seconds: int) -> int:
    return seconds * _MS_PER_S // _STEP_MS


def _span(seed: str, domain: str, step: int, ordinal: int, low: int, high: int) -> int:
    """A whole number of steps drawn from ``low`` to ``high`` seconds, inclusive."""
    return _seconds_to_steps(low + _draw(seed, domain, step, ordinal, high - low + 1))


# -- state ------------------------------------------------------------------------------------


def _perched(flight: FlightInput, flyer: Flyer, perch_id: str, timer: int) -> dict[str, Any]:
    perch = flight.perch_index[perch_id]
    return {
        "flyer_id": flyer.flyer_id,
        "ordinal": flyer.ordinal,
        "state": "perching",
        "position_mm": list(perch.point_mm),
        "velocity_mm_s": [0, 0, 0],
        "perch_id": perch_id,
        "goal": None,
        "timer_steps": timer,
        "wander_mm": [_WANDER_RADIUS, 0, 0],
        "turn_mm_s2": 0,
        "flap": False,
        "held": False,
        #: Going home: the centres of the cells still ahead on its route, or [] with none found.
        "route": None,
        "stuck_steps": 0,
    }


def genesis(flight: FlightInput, episode: int) -> dict[str, Any]:
    """The state at an episode's first step: every flyer perching at home, its perch time drawn."""
    step = episode * _EPISODE
    flyers = []
    for flyer in flight.flyers:
        kind = flight.kinds[flyer.kind]
        timer = _span(
            flight.seed,
            "perch",
            step,
            flyer.ordinal,
            kind.perch_seconds_minimum,
            kind.perch_seconds_maximum,
        )
        flyers.append(_perched(flight, flyer, flyer.home_perch_id, timer))
    return {
        "profile": STATE_PROFILE,
        "input_sha256": flight.sha256,
        "step": step,
        "flyers": flyers,
    }


def _held(state: dict[str, Any], me: dict[str, Any]) -> set[str]:
    """The perches somebody else is on, landing on, leaving, or heading to."""
    held = set()
    for other in state["flyers"]:
        if other is me:
            continue
        if other["perch_id"] is not None:
            held.add(other["perch_id"])
        goal = other["goal"]
        if goal is not None and goal["kind"] == "perch":
            held.add(goal["perch_id"])
    return held


def _occupied(state: dict[str, Any], me: dict[str, Any], perch_id: str) -> bool:
    """Whether somebody else is on, landing on or leaving the perch right now."""
    return any(other is not me and other["perch_id"] == perch_id for other in state["flyers"])


# -- choices ----------------------------------------------------------------------------------


def _deciding(flyer_state: dict[str, Any]) -> bool:
    """A flyer chooses only when its perch or its wander has run out."""
    goal = flyer_state["goal"]
    if flyer_state["state"] == "perching":
        return flyer_state["timer_steps"] <= 0
    return (
        flyer_state["state"] == "flying"
        and goal is not None
        and goal["kind"] == "roam"
        and flyer_state["timer_steps"] <= 0
    )


def allowed_choices(
    flight: FlightInput, state: dict[str, Any], flyer_state: dict[str, Any]
) -> list[dict[str, Any]]:
    """What a deciding flyer may choose: each free perch its kind can use, and wandering.

    The list a model deciding for a flyer would be offered; the seeded chooser draws from it.
    """
    flyer = flight.flyers[flyer_state["ordinal"]]
    held = _held(state, flyer_state)
    perches = [
        {"kind": "perch", "perch_id": perch.perch_id}
        for perch in flight.perches
        if flyer.kind in perch.columns
        and perch.perch_id not in held
        and perch.perch_id != flyer_state["perch_id"]
    ]
    return [*perches, {"kind": "roam"}]


def validate_choice(
    flight: FlightInput,
    state: dict[str, Any],
    flyer_id: str,
    proposal: Any,
) -> str | None:
    """None when ``proposal`` is a choice this flyer may make now, else the reason it may not.

    Every choice passes here, the seeded chooser's included, so a model's proposal is held to the
    same rule the built-in chooser is.
    """
    flyer_state = next((f for f in state["flyers"] if f["flyer_id"] == flyer_id), None)
    if flyer_state is None:
        return "unknown_flyer"
    if not isinstance(proposal, dict) or "kind" not in proposal:
        return "invalid_proposal_fields"
    if not _deciding(flyer_state):
        return "action_in_progress"
    if _homing(state["step"]):
        return "homing"
    if proposal["kind"] == "roam":
        return None if set(proposal) == {"kind"} else "invalid_proposal_fields"
    if proposal["kind"] != "perch":
        return "unsupported_proposal"
    if set(proposal) != {"kind", "perch_id"}:
        return "invalid_proposal_fields"
    perch = flight.perch_index.get(proposal["perch_id"])
    if perch is None:
        return "perch_not_declared"
    kind = flight.flyers[flyer_state["ordinal"]].kind
    if kind not in perch.columns:
        return perch.refused[kind]
    if perch.perch_id == flyer_state["perch_id"]:
        return "already_here"
    if perch.perch_id in _held(state, flyer_state):
        return "perch_taken"
    return None


def _homing(step: int) -> bool:
    """Whether a step falls in its episode's last minute, when every flyer goes home."""
    return step % _EPISODE >= _EPISODE - _HOMING


def _choose(flight: FlightInput, state: dict[str, Any], flyer_state: dict[str, Any]) -> None:
    """The seeded choice of a deciding flyer, validated like any proposal, then taken."""
    flyer = flight.flyers[flyer_state["ordinal"]]
    kind = flight.kinds[flyer.kind]
    step = state["step"]
    options = allowed_choices(flight, state, flyer_state)
    perches = options[:-1]
    wander = (
        not perches
        or _draw(flight.seed, "roam", step, flyer.ordinal, 1000) < kind.roam_weight_milli
    )
    if flyer_state["state"] == "flying" and perches:
        # A wander that ran out ends at a perch whenever one is free.
        wander = False
    choice = (
        {"kind": "roam"}
        if wander
        else perches[_draw(flight.seed, "perch-choice", step, flyer.ordinal, len(perches))]
    )
    refusal = validate_choice(flight, state, flyer.flyer_id, choice)
    if refusal is not None:
        raise AssertionError(f"the seeded chooser proposed a refused choice: {refusal}")
    _take(flight, state, flyer_state, choice)


def _take(
    flight: FlightInput,
    state: dict[str, Any],
    flyer_state: dict[str, Any],
    choice: dict[str, Any],
) -> None:
    flyer = flight.flyers[flyer_state["ordinal"]]
    kind = flight.kinds[flyer.kind]
    if choice["kind"] == "roam":
        flyer_state["goal"] = {"kind": "roam"}
        flyer_state["timer_steps"] = _span(
            flight.seed,
            "roam",
            state["step"],
            flyer.ordinal,
            kind.roam_seconds_minimum,
            kind.roam_seconds_maximum,
        )
    else:
        flyer_state["goal"] = {"kind": "perch", "perch_id": choice["perch_id"]}
        flyer_state["timer_steps"] = 0
    if flyer_state["state"] == "perching":
        flyer_state["state"] = "taking_off"


def _go_home(flight: FlightInput, flyer_state: dict[str, Any]) -> None:
    """In an episode's last minute every flyer heads for its home perch, and stays once there."""
    home = flight.flyers[flyer_state["ordinal"]].home_perch_id
    if flyer_state["state"] == "perching":
        if flyer_state["perch_id"] != home:
            flyer_state["goal"] = {"kind": "perch", "perch_id": home}
            flyer_state["state"] = "taking_off"
            flyer_state["route"] = None
        return
    goal = flyer_state["goal"]
    if flyer_state["state"] == "flying" and (goal is None or goal.get("perch_id") != home):
        flyer_state["goal"] = {"kind": "perch", "perch_id": home}
        flyer_state["timer_steps"] = 0
        flyer_state["route"] = None


# -- steering ---------------------------------------------------------------------------------


def _per_step(value: int) -> int:
    """A rate a second as the change it makes in one step."""
    return tdiv(value * _STEP_MS, _MS_PER_S)


def _band(flight: FlightInput, kind: FlightKind) -> tuple[int, int]:
    ground = flight.volume.ground_mm
    return ground + kind.min_altitude_mm, ground + kind.max_altitude_mm


def _inside(flight: FlightInput, kind: FlightKind, point: Sequence[int], margin: int) -> bool:
    volume = flight.volume
    low, high = _band(flight, kind)
    x, y, z = point
    return (
        volume.min_x_mm + margin <= x <= volume.max_x_mm - margin
        and low + margin <= y <= high - margin
        and volume.min_z_mm + margin <= z <= volume.max_z_mm - margin
    )


def _passable(flight: FlightInput, start: Sequence[int], end: Sequence[int]) -> bool:
    """Whether a flying move is clear: every cell its closed box meets is free."""
    occupancy = flight.occupancy
    return all(not occupancy.is_solid(cell) for cell in swept_cells(flight.volume, start, end))


def _fan() -> tuple[Vector, ...]:
    """Every direction avoidance may turn to: each heading level, sloping up and sloping down,
    then straight up and straight down, each a whole-thousandths unit vector, fixed at import."""
    from exulanica.movement.fixed import ONE, turn

    directions: list[Vector] = []
    level = math_isqrt(_UNIT * _UNIT - _FAN_SLOPE * _FAN_SLOPE)
    for index in range(_FAN_HEADINGS):
        cosine, sine = turn(index * _TURN_MICRORADIANS // _FAN_HEADINGS)
        x, z = tdiv(cosine * _UNIT, ONE), tdiv(sine * _UNIT, ONE)
        directions.append((x, 0, z))
        directions.append((tdiv(x * level, _UNIT), _FAN_SLOPE, tdiv(z * level, _UNIT)))
        directions.append((tdiv(x * level, _UNIT), -_FAN_SLOPE, tdiv(z * level, _UNIT)))
    return (*directions, (0, _UNIT, 0), (0, -_UNIT, 0))


def _probe_clear(
    flight: FlightInput, kind: FlightKind, position: Vector, direction: Vector, reach: int
) -> bool:
    """Whether the straight line ``reach`` millimetres along ``direction`` stays clear and in
    the band, looked at in :data:`_PROBES` moves."""
    if reach <= 0 or length(direction) == 0:
        return True
    last = position
    for index in range(1, _PROBES + 1):
        point = add(position, scale_to(direction, reach * index // _PROBES))
        if not _inside(flight, kind, point, 0) or not _passable(flight, last, point):
            return False
        last = point
    return True


def _band_rows(flight: FlightInput, kind: FlightKind) -> tuple[int, int]:
    """The first and last grid rows whose cells lie wholly inside the kind's band."""
    low, high = _band(flight, kind)
    ground, size = flight.volume.ground_mm, flight.volume.cell_mm
    return ceil_div(low - ground, size), (high - ground) // size - 1


def _centre(flight: FlightInput, cell: Cell) -> list[int]:
    low, high = flight.volume.cell_bounds(cell)
    return [(low[0] + high[0]) // 2, (low[1] + high[1]) // 2, (low[2] + high[2]) // 2]


def _route(
    flight: FlightInput, kind: FlightKind, start: Sequence[int], goal: Sequence[int]
) -> list[list[int]] | None:
    """The centres of the cells from ``start``'s to ``goal``'s, the fewest steps over free cells of
    the kind's band that share a face, or None where there is no such way.

    A* over the grid, the Manhattan distance its estimate, ties broken toward the longer way
    already travelled and then by cell, so the same state finds the same route anywhere.
    """
    volume = flight.volume
    occupancy = flight.occupancy
    begin, end = volume.cell_of(start), volume.cell_of(goal)
    if begin is None or end is None:
        return None
    first, last = _band_rows(flight, kind)
    nx, _ny, nz = volume.shape

    def estimate(cell: Cell) -> int:
        return abs(cell[0] - end[0]) + abs(cell[1] - end[1]) + abs(cell[2] - end[2])

    queue: list[tuple[int, int, Cell]] = [(estimate(begin), 0, begin)]
    cost = {begin: 0}
    came: dict[Cell, Cell] = {}
    while queue:
        _, negative, cell = heapq.heappop(queue)
        travelled = -negative
        if travelled != cost[cell]:
            continue
        if cell == end:
            path = []
            while cell != begin:
                path.append(_centre(flight, cell))
                cell = came[cell]
            path.reverse()
            return path
        for dx, dy, dz in _NEIGHBOURS:
            near = (cell[0] + dx, cell[1] + dy, cell[2] + dz)
            if near != end and not (
                0 <= near[0] < nx and first <= near[1] <= last and 0 <= near[2] < nz
            ):
                continue
            if occupancy.is_solid(near) or travelled + 1 >= cost.get(near, travelled + 2):
                continue
            cost[near] = travelled + 1
            came[near] = cell
            heapq.heappush(queue, (travelled + 1 + estimate(near), -(travelled + 1), near))
    return None


def _along_route(
    flight: FlightInput, kind: FlightKind, flyer_state: dict[str, Any], position: Vector
) -> Vector | None:
    """The velocity along a flyer's route home, or None once no waypoint is left.

    Every waypoint up to the furthest of the next few the flyer stands in is passed; it then aims
    at the furthest of the next few it can fly straight to, and slows as it nears it, so it enters
    the cell it aims at rather than circling it.
    """
    route = flyer_state.get("route")
    if not route:
        return None
    volume = flight.volume
    here = volume.cell_of(position)
    ahead = route[:_ROUTE_AHEAD]
    reached = max(
        (index for index, waypoint in enumerate(ahead) if volume.cell_of(waypoint) == here),
        default=-1,
    )
    route = route[reached + 1 :]
    flyer_state["route"] = route
    if not route:
        return None
    target = tuple(route[0])
    for waypoint in route[1:_ROUTE_AHEAD]:
        if not _passable(flight, position, waypoint):
            break
        target = tuple(waypoint)
    offset = sub(target, position)
    distance = length(offset)
    if distance == 0:
        return None
    cruise = kind.cruise_speed_mm_s
    speed = min(cruise, max(cruise // 4, cruise * distance // _ROUTE_SLOWING))
    return scale_to(offset, speed)


def _desired(
    flight: FlightInput, kind: FlightKind, flyer_state: dict[str, Any], step: int
) -> tuple[Vector, bool]:
    """The velocity a flyer wants this step, and whether it is arriving at a perch.

    Seek and arrive toward a perch's approach point, or wander on a circle ahead, holding the
    middle of the band; then containment, and then obstacle avoidance, override it.
    """
    position = tuple(flyer_state["position_mm"])
    velocity = tuple(flyer_state["velocity_mm_s"])
    goal = flyer_state["goal"]
    flyer = flight.flyers[flyer_state["ordinal"]]
    arriving = goal is not None and goal["kind"] == "perch"
    along = _along_route(flight, kind, flyer_state, position) if arriving else None
    if along is not None:
        # A route runs over free cells: the guard alone keeps the flyer in them.
        return along, arriving
    distance = 0
    if arriving:
        target = flight.column(goal["perch_id"], flyer.kind).approach_mm
        offset = sub(target, position)
        distance = length(offset)
        speed = kind.cruise_speed_mm_s
        if distance < _SLOWING:
            speed = speed * distance // _SLOWING
        desired = scale_to(offset, speed)
    else:
        heading = (velocity[0], 0, velocity[2])
        if length(heading) == 0:
            heading = (flyer_state["wander_mm"][0], 0, flyer_state["wander_mm"][2])
        digest = _digest(flight.seed, "wander", step, flyer.ordinal)
        jitter = (
            int.from_bytes(digest[0:2], "big") % (2 * _WANDER_JITTER + 1) - _WANDER_JITTER,
            0,
            int.from_bytes(digest[2:4], "big") % (2 * _WANDER_JITTER + 1) - _WANDER_JITTER,
        )
        wander = scale_to(add(tuple(flyer_state["wander_mm"]), jitter), _WANDER_RADIUS)
        if length(wander) == 0:
            wander = (_WANDER_RADIUS, 0, 0)
        flyer_state["wander_mm"] = list(wander)
        ahead = add(scale_to(heading, _WANDER_DISTANCE), wander)
        low, high = _band(flight, kind)
        middle = (low + high) // 2
        climb = max(-kind.descent_rate_mm_s, min(kind.climb_rate_mm_s, middle - position[1]))
        horizontal = scale_to(ahead, kind.cruise_speed_mm_s)
        desired = (horizontal[0], climb, horizontal[2])
    reach = length(velocity) * _LOOKAHEAD_MS // _MS_PER_S
    predicted = add(position, scale_to(velocity, reach)) if reach else position
    # Containment turns a wandering flyer back from the bounds less a margin. A flyer heading to a
    # perch steers for its approach point, which the perch's own rule puts inside the volume and
    # the band, sometimes a hand's width under the band's top; turning it back there would keep it
    # from ever arriving, and the guard keeps its every move inside them anyway.
    if not arriving and not _inside(flight, kind, predicted, _MARGIN):
        volume = flight.volume
        low, high = _band(flight, kind)
        centre = (
            (volume.min_x_mm + volume.max_x_mm) // 2,
            (low + high) // 2,
            (volume.min_z_mm + volume.max_z_mm) // 2,
        )
        return scale_to(sub(centre, position), kind.cruise_speed_mm_s), arriving
    # Obstacle avoidance: look along where it wants to go, and heading to a perch no further than
    # its approach point; if that is blocked, turn to the fan direction nearest it that is clear,
    # slowing to half its cruise speed while it goes around, and failing every one, stop.
    probe = max(reach, _MARGIN)
    if arriving:
        probe = min(probe, distance)
    if length(desired) == 0 or _probe_clear(flight, kind, position, desired, probe):
        return desired, arriving
    wanted = scale_to(desired, _UNIT)
    ranked = sorted(
        range(len(_FAN_DIRECTIONS)), key=lambda i: (-dot(_FAN_DIRECTIONS[i], wanted), i)
    )
    for index in ranked:
        direction = _FAN_DIRECTIONS[index]
        if _probe_clear(flight, kind, position, direction, probe):
            return scale_to(direction, kind.cruise_speed_mm_s // 2), arriving
    return (0, 0, 0), arriving


_FAN_DIRECTIONS: Final = _fan()


def _steer(kind: FlightKind, velocity: Vector, desired: Vector) -> tuple[Vector, int]:
    """The acceleration toward ``desired``, bounded in size and in turning, and its signed
    horizontal turning part (positive to the left)."""
    force = clamp_length(sub(desired, velocity), kind.max_accel_mm_s2)
    speed_squared = dot(velocity, velocity)
    if speed_squared == 0:
        return force, 0
    along = dot(force, velocity)
    parallel = (
        tdiv(velocity[0] * along, speed_squared),
        tdiv(velocity[1] * along, speed_squared),
        tdiv(velocity[2] * along, speed_squared),
    )
    perpendicular = clamp_length(
        sub(force, parallel), length(velocity) * kind.max_turn_rate_mrad_s // _MS_PER_S
    )
    horizontal = (velocity[0], 0, velocity[2])
    size = length(horizontal)
    turning = tdiv(cross_y(horizontal, perpendicular), size) if size else 0
    return add(parallel, perpendicular), turning


def _fly(
    flight: FlightInput,
    kind: FlightKind,
    flyer_state: dict[str, Any],
    step: int,
    *,
    perch_in_use: bool,
) -> None:
    """One flying step: steer, move under the guard, and land when at a free perch's column.

    ``perch_in_use`` says whether another flyer is still on, landing on or leaving the perch this
    flyer is heading to; it waits at the approach point until the perch is its own.
    """
    flyer = flight.flyers[flyer_state["ordinal"]]
    position = tuple(flyer_state["position_mm"])
    velocity = tuple(flyer_state["velocity_mm_s"])
    goal = flyer_state["goal"]
    if goal is not None and goal["kind"] == "perch":
        column = flight.column(goal["perch_id"], flyer.kind)
        if _homing(step) and flyer_state.get("route") is None:
            flyer_state["route"] = _route(flight, kind, position, column.approach_mm) or []
        remaining = length(sub(column.approach_mm, position))
        reachable = max(_per_step(length(velocity)), _per_step(kind.landing_rate_mm_s))
        if (
            remaining <= reachable
            and not perch_in_use
            and _passable(flight, position, column.approach_mm)
        ):
            flyer_state["position_mm"] = list(column.approach_mm)
            flyer_state["velocity_mm_s"] = [0, 0, 0]
            flyer_state["state"] = "landing"
            flyer_state["perch_id"] = goal["perch_id"]
            flyer_state["goal"] = None
            flyer_state["turn_mm_s2"] = 0
            flyer_state["flap"] = True
            flyer_state["held"] = False
            flyer_state["route"] = None
            flyer_state["stuck_steps"] = 0
            return
    desired, _ = _desired(flight, kind, flyer_state, step)
    force, turning = _steer(kind, velocity, desired)
    moved = add(velocity, (_per_step(force[0]), _per_step(force[1]), _per_step(force[2])))
    moved = clamp_length(moved, kind.max_speed_mm_s)
    moved = (
        moved[0],
        max(-kind.descent_rate_mm_s, min(kind.climb_rate_mm_s, moved[1])),
        moved[2],
    )
    # The guard: a move steering proposed into a solid cell or out of bounds is refused. The flyer
    # then slides, keeping only the parts of its velocity along which it can still move, level
    # first, then vertical, then along each level axis; with none, it stops where it is.
    slides = (
        moved,
        (moved[0], 0, moved[2]),
        (0, moved[1], 0),
        (moved[0], 0, 0),
        (0, 0, moved[2]),
    )
    taken: Vector = (0, 0, 0)
    for candidate in slides:
        step_move = (_per_step(candidate[0]), _per_step(candidate[1]), _per_step(candidate[2]))
        if step_move == (0, 0, 0):
            continue
        target = add(position, step_move)
        if _inside(flight, kind, target, 0) and _passable(flight, position, target):
            taken = candidate
            flyer_state["position_mm"] = list(target)
            break
    held = taken != moved
    flyer_state["velocity_mm_s"] = list(taken)
    flyer_state["turn_mm_s2"] = turning if not held else 0
    flyer_state["held"] = held
    flyer_state["flap"] = held or taken[1] > 0 or length(taken) < kind.glide_speed_mm_s
    stuck = flyer_state.get("stuck_steps", 0) + 1 if held else 0
    if stuck >= _STUCK_STEPS and _homing(step):
        # Held for a while going home: find the way again from where it is.
        flyer_state["route"] = None
        stuck = 0
    flyer_state["stuck_steps"] = stuck


def _column_move(
    flight: FlightInput, kind: FlightKind, flyer_state: dict[str, Any], state: dict[str, Any]
) -> None:
    """Taking off up, or landing down, a perch's column, at the kind's own rate."""
    flyer = flight.flyers[flyer_state["ordinal"]]
    perch = flight.perch_index[flyer_state["perch_id"]]
    column = flight.column(perch.perch_id, flyer.kind)
    x, y, z = flyer_state["position_mm"]
    flyer_state["turn_mm_s2"] = 0
    flyer_state["flap"] = True
    flyer_state["held"] = False
    if flyer_state["state"] == "taking_off":
        rate = kind.takeoff_rate_mm_s
        top = column.approach_mm[1]
        y = min(top, y + _per_step(rate))
        flyer_state["position_mm"] = [x, y, z]
        flyer_state["velocity_mm_s"] = [0, rate, 0]
        if y == top:
            flyer_state["state"] = "flying"
            flyer_state["perch_id"] = None
        return
    rate = kind.landing_rate_mm_s
    bottom = perch.point_mm[1]
    y = max(bottom, y - _per_step(rate))
    flyer_state["position_mm"] = [x, y, z]
    flyer_state["velocity_mm_s"] = [0, -rate, 0]
    if y == bottom:
        flyer_state["state"] = "perching"
        flyer_state["velocity_mm_s"] = [0, 0, 0]
        flyer_state["flap"] = False
        flyer_state["timer_steps"] = _span(
            flight.seed,
            "perch",
            state["step"],
            flyer.ordinal,
            kind.perch_seconds_minimum,
            kind.perch_seconds_maximum,
        )


def advance_flight(flight: FlightInput, state: dict[str, Any]) -> dict[str, Any]:
    """The state one step later. At an episode's first step it is that episode's genesis."""
    if state["profile"] != STATE_PROFILE or state["input_sha256"] != flight.sha256:
        raise FlightRefused("flight_state_mismatch", "the state belongs to another flight input")
    step = state["step"] + 1
    if step % _EPISODE == 0:
        return genesis(flight, step // _EPISODE)
    result = {
        "profile": STATE_PROFILE,
        "input_sha256": flight.sha256,
        "step": step,
        # Shallow copies: a step replaces a flyer's lists and goal, never edits them in place.
        "flyers": [dict(flyer_state) for flyer_state in state["flyers"]],
    }
    # Choices first, in ordinal order, so each sees the perches the earlier ones took.
    homing = _homing(step)
    for flyer_state in result["flyers"]:
        if homing:
            _go_home(flight, flyer_state)
            continue
        if flyer_state["state"] in ("perching", "flying") and flyer_state["timer_steps"] > 0:
            flyer_state["timer_steps"] -= 1
        if _deciding(flyer_state):
            _choose(flight, result, flyer_state)
    # Then every flyer moves, each by the state its choices left and the grid.
    for flyer_state in result["flyers"]:
        kind = flight.kinds[flight.flyers[flyer_state["ordinal"]].kind]
        if flyer_state["state"] == "perching":
            flyer_state["velocity_mm_s"] = [0, 0, 0]
            flyer_state["turn_mm_s2"] = 0
            flyer_state["flap"] = False
            flyer_state["held"] = False
        elif flyer_state["state"] in ("taking_off", "landing"):
            _column_move(flight, kind, flyer_state, result)
        else:
            goal = flyer_state["goal"]
            in_use = (
                goal is not None
                and goal["kind"] == "perch"
                and _occupied(result, flyer_state, goal["perch_id"])
            )
            _fly(flight, kind, flyer_state, step, perch_in_use=in_use)
    return result


def state_at(flight: FlightInput, step: int) -> dict[str, Any]:
    """The state at ``step``, computed from its episode's genesis: at most one episode of steps."""
    episode = step // _EPISODE
    state = genesis(flight, episode)
    for _ in range(step - episode * _EPISODE):
        state = advance_flight(flight, state)
    return state


def state_sha256(state: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(state)).hexdigest()


_STATE_CODES: Final = {state: index for index, state in enumerate(STATES)}


def check_request(from_step: object, steps: object) -> None:
    """Refuse, by name, a window beyond the module's bounds: at most ``max_steps_per_request``
    steps, starting no later than ``max_from_step``."""
    if type(steps) is not int or not 1 <= steps <= _MAX_STEPS:
        raise FlightRefused(
            "flight_window_too_long", f"a window is 1 to {_MAX_STEPS} steps, got {steps!r}"
        )
    if type(from_step) is not int or not 0 <= from_step <= _MAX_FROM:
        raise FlightRefused(
            "flight_step_out_of_range",
            f"a window starts at a step from 0 to {_MAX_FROM}, got {from_step!r}",
        )


def flight_window(flight: FlightInput, from_step: int, steps: int) -> dict[str, Any]:
    """The states at steps ``from_step`` to ``from_step + steps - 1``, as the renderer reads them.

    Each flyer's samples are flat integer arrays, one entry (or three, for a vector) a step:
    position, velocity, signed turning acceleration, state code (:data:`STATES` order), flap and
    guard hold. The first state is computed from its episode's genesis.
    """
    check_request(from_step, steps)
    window, _ = window_from(flight, state_at(flight, from_step), steps)
    return window


def window_from(
    flight: FlightInput, state: dict[str, Any], steps: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The window of ``steps`` states starting at ``state``, and the last state in it."""
    _built()
    from_step = state["step"]
    samples: dict[str, dict[str, list[int]]] = {
        flyer.flyer_id: {
            "position_mm": [],
            "velocity_mm_s": [],
            "turn_mm_s2": [],
            "state": [],
            "flap": [],
            "held": [],
        }
        for flyer in flight.flyers
    }
    late: list[dict[str, Any]] = []
    for index in range(steps):
        if index:
            state = advance_flight(flight, state)
        if state["step"] % _EPISODE == _EPISODE - 1:
            # An episode's last step: every flyer not perching at home is named, in every window
            # that holds the step.
            late.extend(
                {"step": state["step"], "flyer_id": row["flyer_id"]}
                for row in _late_home(flight, state)
            )
        for row in state["flyers"]:
            out = samples[row["flyer_id"]]
            out["position_mm"].extend(row["position_mm"])
            out["velocity_mm_s"].extend(row["velocity_mm_s"])
            out["turn_mm_s2"].append(row["turn_mm_s2"])
            out["state"].append(_STATE_CODES[row["state"]])
            out["flap"].append(int(row["flap"]))
            out["held"].append(int(row["held"]))
    window = {
        "profile": WINDOW_PROFILE,
        "module": FLIGHT,
        "input_sha256": flight.sha256,
        #: The ground the positions stand over, so a renderer places them over its own ground.
        "ground_mm": flight.volume.ground_mm,
        "step_ms": _STEP_MS,
        "episode_steps": _EPISODE,
        "from_step": from_step,
        "steps": steps,
        "states": list(STATES),
        "flyers": [
            {"flyer_id": flyer.flyer_id, "kind": flyer.kind, **samples[flyer.flyer_id]}
            for flyer in flight.flyers
        ],
        "late_home": late,
    }
    return window, state


def _late_home(flight: FlightInput, last: dict[str, Any]) -> list[dict[str, Any]]:
    """The flyers not perching at home in an episode's last state: each is a finding."""
    return [
        row
        for row in last["flyers"]
        if row["state"] != "perching"
        or row["perch_id"] != flight.flyers[row["ordinal"]].home_perch_id
    ]
