"""Whole traffic episodes: what the traffic's worker process computes, and windows cut from them.

Traffic is a function of a world's road records and its clock, and every episode starts from the
same genesis, so an episode can be computed whole, once, anywhere, and any window of seconds read
from the episodes it spans. This module holds that, in the pattern the flight's episodes set
(:mod:`exulanica.movement.flight_episodes`):

- **the input** (:class:`TrafficInput`): the city records a world states that bear on its roads,
  its city identity and grammar version, keyed by world and version and digested whole;
- **the wire form** (:func:`wire`, :func:`from_wire`): plain data the worker process rebuilds the
  input from, refused when its digest differs;
- **the network** (:func:`prepared`): the lane connections, parking spaces and signals traffic
  derives from the records (:mod:`exulanica.traffic.city_derivation`, signals by the
  ``signal-placement`` entry it names), compiled, kept in the worker by the input's digest,
  because compiling a district takes seconds;
- **the fleet**, by rule from the home places the network holds: in every parking kind, the
  roads module's ``fleet_share_permille`` of its places, divided among the classes the kind admits
  in the catalog's order, so every vehicle has a place free to drive to. A world whose places
  would host more than ``max_vehicles`` is refused by name, ``roads_world_too_large``;
- **an episode** (:func:`compute_episode`): ``episode_steps`` seconds from the genesis
  :func:`~exulanica.traffic.simulation.initial_traffic` places the fleet in, every vehicle
  leaving home once at a second of the first ``departure_steps`` drawn from the seed, for a space
  of its class that is nobody's home and has a free place, reached and returned from; staying
  there for a dwell drawn from the seed; and driving home. The trip requests are decided second by
  second by this rule and recorded as the run's inputs, so the episode replays exactly. The
  crossing feed is empty: no walker's crossing is fed to traffic, and the window says so;
- **a window** (:func:`window_of`): the presentation frames of its seconds
  (``exulanica.traffic-presentation-frame/v1``), grouped by vehicle, packed as integers, and each
  signal's groups with where their heads stand and the indication each shows every second
  (``exulanica.traffic-signal-presentation/v1``).

Pure: no connection, no store, no process of its own (:mod:`exulanica.world.traffic_host` runs the
job in one).
"""

from __future__ import annotations

import hashlib
import uuid
from array import array
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar import shapes
from exulanica.grammar.draw import draw_integer
from exulanica.grammar.grammars.city import CITY_SHAPES_BY_TYPE
from exulanica.grammar.grammars.city.catalogs import load_city_catalogs
from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord
from exulanica.grammar.grammars.city.streets import CurbEdgeRecord
from exulanica.grammar.records import record_payload
from exulanica.movement.registry import ROADS, MovementError, built_module
from exulanica.traffic.catalogs import TrafficCatalogs, load_traffic_catalogs
from exulanica.traffic.city_derivation import PLACEMENT_KEY, DerivedRoads, derive_road_records
from exulanica.traffic.city_roads import READ_KINDS, road_input_from_city
from exulanica.traffic.inputs import LOOKAHEAD_S, CrossingFeed, TrafficInputs, TripRequest
from exulanica.traffic.network import RoadNetwork, compile_network
from exulanica.traffic.presentation import presentation_frame, signal_codes, signal_heads
from exulanica.traffic.routing import plan_route
from exulanica.traffic.signal_actuation import SignalTimeline, signal_actuation, signal_observation
from exulanica.traffic.signals import PEDESTRIAN_INDICATIONS, VEHICLE_INDICATIONS
from exulanica.traffic.simulation import advance_traffic, initial_traffic, state_sha256

__all__ = [
    "EPISODE",
    "INPUT_PROFILE",
    "MODES",
    "WINDOW_PROFILE",
    "PackedTrafficEpisode",
    "TrafficInput",
    "TrafficRefused",
    "check_request",
    "compute_episode",
    "compute_signal_catalog",
    "compute_signal_probe",
    "compute_signal_replay",
    "from_wire",
    "home_segment",
    "road_records",
    "traffic_input",
    "window_of",
    "window_of_segments",
    "wire",
]

ROADS_MODULE: Final = built_module(ROADS)
INPUT_PROFILE: Final = "exulanica.traffic-input/v1"
WINDOW_PROFILE: Final = ROADS_MODULE.output_profile
EPISODE: Final = ROADS_MODULE.value("episode_steps")
_DEPARTURE: Final = ROADS_MODULE.value("departure_steps")
_DWELL: Final = (
    ROADS_MODULE.value("dwell_steps_minimum"),
    ROADS_MODULE.value("dwell_steps_maximum"),
)
_FLEET_SHARE_PERMILLE: Final = ROADS_MODULE.value("fleet_share_permille")
_MAX_VEHICLES: Final = ROADS_MODULE.value("max_vehicles")
_MAX_STEPS: Final = ROADS_MODULE.value("max_steps_per_request")
_PERMILLE: Final = 1000
#: The traffic's vehicle modes, in the order a window's ``mode`` integers index.
MODES: Final = ("parked", "leaving", "driving", "arriving")
#: The integers each vehicle's frame takes a second, in order: front axle, rear axle, mode, speed
#: and the place of its space it stands in.
_FIELDS: Final = (
    ("front_axle_mm", 2),
    ("rear_axle_mm", 2),
    ("mode", 1),
    ("speed_mm_per_s", 1),
    ("slot", 1),
)
_TYPECODE: Final = "i"
#: What the trip rule writes as a request's source.
_SOURCE: Final = "exulanica.traffic-host trip rule v1"
_NAMESPACE: Final = uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.invalid/traffic-host")
#: The city record kinds a traffic input carries: what traffic reads, and the curbs and street
#: furniture its derivation places spaces by.
_CARRIED: Final = (*READ_KINDS, CurbEdgeRecord, StreetFurnitureRecord)
_SHAPES_BY_KIND: Final = {shape.kind: shape for shape in CITY_SHAPES_BY_TYPE.values()}
#: Networks kept in a worker process, by input digest: a page reads one world at a time.
_PREPARED_LIMIT: Final = 4


class TrafficRefused(MovementError):
    """A traffic read or input refused by name: ``code`` is what a caller receives."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail

    def __reduce__(self) -> tuple[Any, ...]:
        return (type(self), (self.code, self.detail))


def check_request(from_second: int, seconds: int) -> None:
    """Refuse a window the roads module does not serve."""
    if type(from_second) is not int or from_second < 0:
        raise TrafficRefused("traffic_second_out_of_range", f"no second {from_second!r}")
    if type(seconds) is not int or not 1 <= seconds <= _MAX_STEPS:
        raise TrafficRefused(
            "traffic_window_too_long", f"a window is 1 to {_MAX_STEPS} seconds, not {seconds!r}"
        )


def check_clock(from_second: int, clock_second: int) -> None:
    reach = ROADS_MODULE.value("clock_reach_steps")
    if abs(from_second - clock_second) > reach:
        raise TrafficRefused(
            "traffic_second_out_of_range",
            f"second {from_second} is more than {reach} seconds from the clock's {clock_second}",
        )


@dataclass(frozen=True, slots=True)
class TrafficInput:
    """A world's road records, as traffic reads them, keyed by the world and its version."""

    world_id: str
    version_id: str
    city_identity: str
    grammar_version: int
    records: tuple[object, ...]
    sha256: str

    @property
    def seed(self) -> str:
        """The seed every draw of this world's traffic is made from, derived from its keys."""
        return hashlib.sha256(
            f"exulanica-traffic/v1:{self.world_id}:{self.version_id}".encode()
        ).hexdigest()

    @property
    def traffic_id(self) -> str:
        return str(uuid.uuid5(_NAMESPACE, f"{self.world_id}:{self.version_id}"))


def road_records(records: Sequence[object]) -> tuple[object, ...]:
    """The city records a traffic input carries, in identity order."""
    return tuple(
        sorted(
            (record for record in records if isinstance(record, _CARRIED)),
            key=lambda record: record.identity,  # type: ignore[attr-defined]
        )
    )


def _digest(
    world_id: str, version_id: str, city: str, grammar_version: int, records: Sequence[object]
) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "profile": INPUT_PROFILE,
                "world_id": world_id,
                "version_id": version_id,
                "city_identity": city,
                "grammar_version": grammar_version,
                "module": ROADS,
                "records": [record_payload(record) for record in records],
            }
        )
    ).hexdigest()


def traffic_input(
    *,
    world_id: str,
    version_id: str,
    city_identity: str,
    grammar_version: int,
    records: Sequence[object],
) -> TrafficInput:
    carried = road_records(records)
    return TrafficInput(
        world_id=world_id,
        version_id=version_id,
        city_identity=city_identity,
        grammar_version=grammar_version,
        records=carried,
        sha256=_digest(world_id, version_id, city_identity, grammar_version, carried),
    )


def wire(value: TrafficInput) -> dict[str, Any]:
    """Plain data from which :func:`from_wire` rebuilds ``value`` exactly."""
    return {
        "input_sha256": value.sha256,
        "world_id": value.world_id,
        "version_id": value.version_id,
        "city_identity": value.city_identity,
        "grammar_version": value.grammar_version,
        "records": [record_payload(record) for record in value.records],
    }


def from_wire(data: Mapping[str, Any]) -> TrafficInput:
    """The input :func:`wire` describes, refused unless it digests to the input it names."""
    records = []
    for index, payload in enumerate(data["records"]):
        shape = _SHAPES_BY_KIND.get(payload["kind"])
        if shape is None:
            raise ValueError(f"records[{index}] is no city record kind")
        records.append(shapes.read_record(payload, shape, f"records[{index}]"))
    rebuilt = traffic_input(
        world_id=data["world_id"],
        version_id=data["version_id"],
        city_identity=data["city_identity"],
        grammar_version=data["grammar_version"],
        records=records,
    )
    if rebuilt.sha256 != data["input_sha256"]:
        raise ValueError("the traffic's wire form does not rebuild the input it names")
    return rebuilt


# -- the network and the fleet ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Prepared:
    """What every episode of one input shares: the derivation, the network and the fleet."""

    derived: DerivedRoads
    network: RoadNetwork
    catalogs: TrafficCatalogs
    fleet: Mapping[str, int]


_prepared: OrderedDict[str, Prepared] = OrderedDict()


def _fleet(network: RoadNetwork, catalogs: TrafficCatalogs) -> dict[str, int]:
    """Vehicles by class from the home places: each kind's share of its places, divided among the
    classes the kind admits, in the catalog's order."""
    places: dict[str, int] = {}
    admitted: dict[str, list[str]] = {}
    for space in network.spaces.values():
        if not space.classes:
            continue
        places[space.kind] = places.get(space.kind, 0) + space.capacity
        order = catalogs.parking_kind(space.kind).classes
        kept = admitted.setdefault(space.kind, [key for key in order if key in space.classes])
        if kept != [key for key in order if key in space.classes]:
            raise TrafficRefused(
                "roads_unavailable", f"spaces of kind {space.kind} admit different classes"
            )
    fleet: dict[str, int] = {}
    for kind in sorted(places):
        count = places[kind] * _FLEET_SHARE_PERMILLE // _PERMILLE
        classes = admitted[kind]
        for index, key in enumerate(classes):
            share = count // len(classes) + (1 if index < count % len(classes) else 0)
            fleet[key] = fleet.get(key, 0) + share
    total = sum(fleet.values())
    if total > _MAX_VEHICLES:
        raise TrafficRefused(
            "roads_world_too_large",
            f"the world's home places host {total} vehicles and the roads module drives at most "
            f"{_MAX_VEHICLES}",
        )
    return {key: count for key, count in sorted(fleet.items()) if count}


def prepared(value: TrafficInput) -> Prepared:
    """The derivation, network and fleet of ``value``, kept by its digest in this process."""
    found = _prepared.get(value.sha256)
    if found is not None:
        _prepared.move_to_end(value.sha256)
        return found
    catalogs = load_traffic_catalogs()
    derived = derive_road_records(
        value.records,
        catalogs,
        load_city_catalogs(grammar_version=value.grammar_version),
        city_identity=value.city_identity,
        placement_key=PLACEMENT_KEY,
    )
    network = compile_network(
        road_input_from_city(
            derived.records,
            catalogs,
            city_identity=value.city_identity,
            signals=derived.signals,
        ),
        catalogs,
    )
    found = Prepared(derived, network, catalogs, _fleet(network, catalogs))
    _prepared[value.sha256] = found
    while len(_prepared) > _PREPARED_LIMIT:
        _prepared.popitem(last=False)
    return found


# -- an episode ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PackedTrafficEpisode:
    """One episode of one input: every vehicle's frames, packed, and what its trips came to."""

    input_sha256: str
    episode: int
    network_sha256: str
    catalog_sha256: str
    #: For each vehicle in id order: its id, class, body family, colour and dimensions.
    vehicles: tuple[dict[str, Any], ...]
    #: For each vehicle, each field of :data:`_FIELDS` as native 32-bit integers, every second.
    samples: tuple[tuple[bytes, ...], ...]
    #: For each vehicle, how many points its front passed each second, and the points, flat.
    path_counts: tuple[bytes, ...]
    path_points: tuple[bytes, ...]
    #: The vehicles not parked at home at the episode's last second, in id order.
    late_home: tuple[str, ...]
    #: Each signal's groups and where their heads stand (``signal_heads``), in identity order.
    signals: tuple[dict[str, Any], ...]
    #: For each signal, for each of its groups, the code it shows every second, packed.
    signal_codes: tuple[tuple[bytes, ...], ...]
    #: Trips requested, arrived, and blocked by reason.
    trips: dict[str, Any]
    derivation: dict[str, Any]


def home_segment(
    value: TrafficInput,
    prepared_input: Prepared,
    episode: int,
    end_second: int,
    continuation: Mapping[str, Any] | None = None,
    *,
    signal_timelines: Mapping[str, SignalTimeline] | None = None,
    chosen_signals: Sequence[str] = (),
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    """Run to an exclusive episode-local second, carrying every trip-rule fact across a seam.

    The continuation is sealed over the exact road input and episode. A later worker can resume
    it without replaying the prefix or drawing a different departure, destination or dwell.
    A segment returns only its own states; the first also returns the genesis state.
    """
    if type(episode) is not int or episode < 0 or type(end_second) is not int:
        raise TrafficRefused("traffic_second_out_of_range", "invalid segment coordinates")
    if not 1 <= end_second <= EPISODE:
        raise TrafficRefused("traffic_second_out_of_range", "segment ends outside the episode")
    network, catalogs = prepared_input.network, prepared_input.catalogs
    seed = value.seed
    genesis = initial_traffic(value.traffic_id, seed, network, catalogs, prepared_input.fleet)
    homes = {vehicle["id"]: vehicle["space"] for vehicle in genesis["vehicles"]}
    ordinals = {vehicle["id"]: vehicle["ordinal"] for vehicle in genesis["vehicles"]}
    classes = {
        vehicle["id"]: catalogs.vehicle_class(vehicle["vehicle_class"])
        for vehicle in genesis["vehicles"]
    }
    salt = episode * 1_000_000
    departs = {
        vehicle_id: draw_integer(seed, "traffic_host.departure", salt + ordinal, 0, _DEPARTURE - 1)
        for vehicle_id, ordinal in ordinals.items()
    }
    feeds = (CrossingFeed(1, EPISODE + LOOKAHEAD_S, ()),)
    if continuation is None:
        returning: dict[str, int] = {}
        trips: list[TripRequest] = []
        state = genesis
        states = [state]
        legs: dict[str, int] = {}
        start_second = 1
    else:
        source = dict(continuation)
        digest = source.pop("document_sha256", None)
        if (
            set(source)
            != {
                "profile",
                "input_sha256",
                "episode",
                "next_second",
                "state",
                "returning",
                "trips",
                "legs",
                "signal_choices",
                "signal_cursors",
                "signal_cursors_before",
                "initial_signal_cursors",
            }
            or source["profile"] != "exulanica.traffic-continuation/v1"
            or source["input_sha256"] != value.sha256
            or source["episode"] != episode
            or hashlib.sha256(canonical_json(source)).hexdigest() != digest
            or type(source["next_second"]) is not int
            or not 1 <= source["next_second"] <= EPISODE
            or source["state"].get("second") != source["next_second"] - 1
        ):
            raise TrafficRefused(
                "traffic_continuation_changed", "segment state or identity changed"
            )
        state = source["state"]
        returning = dict(source["returning"])
        trips = [TripRequest(**item) for item in source["trips"]]
        legs = dict(source["legs"])
        states = []
        start_second = source["next_second"]
        for signal_id, choices in source["signal_choices"].items():
            timeline = (signal_timelines or {}).get(signal_id)
            if timeline is None or any(
                timeline.choices.get(int(second)) != action for second, action in choices.items()
            ):
                raise TrafficRefused(
                    "traffic_continuation_changed", "recorded signal choices changed"
                )
        for signal_id, cursor in source["signal_cursors_before"].items():
            timeline = (signal_timelines or {}).get(signal_id)
            before = (
                None
                if timeline is None
                else timeline.cursor
                if state["second"] == 0
                else timeline.cursor_at(state["second"] - 1)
            )
            if before is None or list(before) != cursor:
                raise TrafficRefused(
                    "traffic_continuation_changed", "recorded signal phase changed"
                )
        for signal_id, cursor in source["initial_signal_cursors"].items():
            timeline = (signal_timelines or {}).get(signal_id)
            if timeline is None or timeline.cursor is None or list(timeline.cursor) != cursor:
                raise TrafficRefused("traffic_continuation_changed", "initial signal phase changed")
    if end_second < start_second:
        raise TrafficRefused("traffic_second_out_of_range", "segment ends before its continuation")

    def request(second: int, vehicle_id: str, destination: str) -> None:
        leg = legs.get(vehicle_id, 0)
        legs[vehicle_id] = leg + 1
        trips.append(
            TripRequest(
                request_seq=len(trips) + 1,
                trip_id=f"{episode}:{ordinals[vehicle_id]}:{leg}",
                vehicle_id=vehicle_id,
                depart_second=second,
                destination_kind="space",
                destination=destination,
                street_segment_ordinal=-1,
                source=_SOURCE,
            )
        )

    def destination_for(vehicle: Mapping[str, Any]) -> str | None:
        # A place is taken by a vehicle parked in it or heading for it, and kept for a vehicle
        # whose home it is while that vehicle is away: nobody takes another's home.
        holding: dict[str, int] = {}
        for other in state["vehicles"]:
            held = [other["space"] if other["mode"] == "parked" else "", other["target_space"]]
            if other["space"] != homes[other["id"]] or other["mode"] != "parked":
                held.append(homes[other["id"]])
            for identity in dict.fromkeys(item for item in held if item):
                holding[identity] = holding.get(identity, 0) + 1
        vehicle_class = classes[vehicle["id"]]
        candidates = sorted(
            identity
            for identity, space in network.spaces.items()
            if vehicle_class.key in space.classes
            and identity != homes[vehicle["id"]]
            and holding.get(identity, 0) < space.capacity
        )
        if not candidates:
            return None
        home = network.spaces[vehicle["space"]]
        first = draw_integer(
            seed, "traffic_host.destination", salt + ordinals[vehicle["id"]], 0, len(candidates) - 1
        )
        for offset in range(len(candidates)):
            identity = candidates[(first + offset) % len(candidates)]
            goal = network.spaces[identity]
            out = plan_route(
                network,
                vehicle_class,
                home.access_path,
                home.access_end,
                goal.access_path,
                goal.access_end,
            )
            back = plan_route(
                network,
                vehicle_class,
                goal.access_path,
                goal.access_end,
                home.access_path,
                home.access_end,
            )
            if out is not None and back is not None:
                return identity
        return None

    def due_point() -> dict[str, Any] | None:
        second = state["second"]
        for signal_id in sorted(chosen_signals):
            timeline = (signal_timelines or {}).get(signal_id)
            if timeline is None:
                raise TrafficRefused("traffic_signal_timeline_missing", signal_id)
            if second in timeline.choices:
                continue
            observation = signal_observation(state, network, timeline, signal_id)
            if observation is not None and observation["near_vehicle_count"] > 0:
                return {
                    "signal_id": signal_id,
                    "choice_second": second,
                    "state_sha256": state_sha256(state),
                    "observation": observation,
                }
        return None

    point = None
    reached_end = end_second
    for second in range(start_second - 1, end_second - 1):
        point = due_point()
        if point is not None:
            reached_end = second + 1
            break
        by_id = {vehicle["id"]: vehicle for vehicle in state["vehicles"]}
        for vehicle_id in sorted(by_id):
            vehicle = by_id[vehicle_id]
            if vehicle["mode"] != "parked" or vehicle["trip_id"]:
                continue
            if departs[vehicle_id] == second and vehicle["space"] == homes[vehicle_id]:
                target = destination_for(vehicle)
                if target is not None:
                    request(second, vehicle_id, target)
            elif returning.get(vehicle_id) == second:
                request(second, vehicle_id, homes[vehicle_id])
        inputs = TrafficInputs(trips=tuple(trips), feeds=feeds)
        step = advance_traffic(
            state, seed, network, catalogs, inputs, signal_timelines=signal_timelines
        )
        state = step.state
        states.append(state)
        for event in step.events:
            document = event["document"]
            if document.get("kind") != "trip_arrived":
                continue
            vehicle_id = document["vehicle_id"]
            if document["space"] != homes[vehicle_id]:
                dwell = draw_integer(
                    seed, "traffic_host.dwell", salt + ordinals[vehicle_id], _DWELL[0], _DWELL[1]
                )
                returning[vehicle_id] = state["second"] + dwell
    if point is None and state["second"] == end_second - 1:
        point = due_point()
    reasons: dict[str, int] = {}
    arrived = 0
    for trip in state["trips"]:
        if trip["status"] == "arrived":
            arrived += 1
        elif trip["status"] == "blocked":
            reasons[trip["reason"]] = reasons.get(trip["reason"], 0) + 1
    summary = {
        "requested": len(trips),
        "arrived": arrived,
        "blocked": dict(sorted(reasons.items())),
        "unfinished": len(trips) - arrived - sum(reasons.values()),
    }
    next_state = {
        "profile": "exulanica.traffic-continuation/v1",
        "input_sha256": value.sha256,
        "episode": episode,
        "next_second": reached_end,
        "state": state,
        "returning": returning,
        "trips": [asdict(trip) for trip in trips],
        "legs": legs,
        "signal_choices": {
            signal_id: {str(second): action for second, action in timeline.choices.items()}
            for signal_id, timeline in sorted((signal_timelines or {}).items())
            if timeline.choices
        },
        "signal_cursors": {
            signal_id: list(timeline.cursor_at(state["second"]))
            for signal_id, timeline in sorted((signal_timelines or {}).items())
        },
        "signal_cursors_before": {
            signal_id: list(
                timeline.cursor
                if state["second"] == 0 and timeline.cursor is not None
                else timeline.cursor_at(state["second"] - 1)
            )
            for signal_id, timeline in sorted((signal_timelines or {}).items())
            if state["second"] > 0 or timeline.cursor is not None
        },
        "initial_signal_cursors": {
            signal_id: list(timeline.cursor)
            for signal_id, timeline in sorted((signal_timelines or {}).items())
            if timeline.cursor is not None
        },
    }
    next_state["document_sha256"] = hashlib.sha256(canonical_json(next_state)).hexdigest()
    return states, next_state, summary, point


def _home_trip_rule(
    value: TrafficInput, prepared_input: Prepared, episode: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Run the fixed episode through the same continuation rule used at signal handoffs."""
    states: list[dict[str, Any]] = []
    continuation = None
    summary: dict[str, Any] = {}
    for end_second in range(60, EPISODE + 1, 60):
        section, continuation, summary, point = home_segment(
            value, prepared_input, episode, end_second, continuation
        )
        assert point is None
        states.extend(section)
    assert continuation is not None
    return states, [TripRequest(**item).document() for item in continuation["trips"]], summary


def compute_signal_probe(
    data: Mapping[str, Any],
    episode: int,
    end_second: int,
    continuation: Mapping[str, Any] | None,
    choices: Mapping[str, Mapping[int, str]],
    initial_cursors: Mapping[str, Sequence[int]],
    chosen_signals: Sequence[str],
) -> dict[str, Any]:
    """One released-worker probe, stopping before a live model choice when one is due.

    The caller supplies only recorded actions and a prior sealed phase cursor. No model client,
    clock or database is present in this worker job. Its continuation binds the road input and
    every traffic rule fact; the controller persists and validates it before another probe.
    """
    value = from_wire(data)
    ready = prepared(value)
    signals = {
        junction.signal.identity: junction.signal
        for junction in ready.network.junctions.values()
        if junction.signal is not None
    }
    named = set(choices) | set(initial_cursors) | set(chosen_signals)
    if not named <= signals.keys():
        raise TrafficRefused("signal_not_in_world", "a signal is not in the compiled roads")
    timelines = {
        signal_id: SignalTimeline(
            ready.catalogs.plan(signals[signal_id].plan),
            signals[signal_id].offset_s,
            0,
            EPISODE + LOOKAHEAD_S,
            dict(choices.get(signal_id, {})),
            signal_actuation(),
            None if signal_id not in initial_cursors else tuple(initial_cursors[signal_id]),
        )
        for signal_id in sorted(named)
    }
    states, following, summary, point = home_segment(
        value,
        ready,
        episode,
        end_second,
        continuation,
        signal_timelines=timelines,
        chosen_signals=chosen_signals,
    )
    return {
        "states": states,
        "continuation": following,
        "summary": summary,
        "point": point,
        "network_sha256": ready.network.digest,
    }


def compute_signal_catalog(data: Mapping[str, Any]) -> list[dict[str, str]]:
    """The compiled signals a saved world's roads own, for a model choice read or write."""
    value = from_wire(data)
    ready = prepared(value)
    return [
        {"signal_id": head["signal_id"], "junction_id": head["junction_id"]}
        for head in signal_heads(ready.network, ready.catalogs)
    ]


def compute_signal_replay(
    data: Mapping[str, Any],
    episode: int,
    segment: int,
    continuation: Mapping[str, Any] | None,
    choices: Mapping[str, Mapping[int, str]],
    initial_cursors: Mapping[str, Sequence[int]],
) -> tuple[PackedTrafficEpisode, dict[str, Any], str]:
    """Rebuild a sealed minute without a client, returning its packed frames and state digest."""
    value = from_wire(data)
    ready = prepared(value)
    signals = {
        junction.signal.identity: junction.signal
        for junction in ready.network.junctions.values()
        if junction.signal is not None
    }
    named = set(choices) | set(initial_cursors)
    if not named <= signals.keys():
        raise TrafficRefused("signal_not_in_world", "a replay signal is not in these roads")
    timelines = {
        signal_id: SignalTimeline(
            ready.catalogs.plan(signals[signal_id].plan),
            signals[signal_id].offset_s,
            0,
            EPISODE + LOOKAHEAD_S,
            dict(choices.get(signal_id, {})),
            signal_actuation(),
            None if signal_id not in initial_cursors else tuple(initial_cursors[signal_id]),
        )
        for signal_id in sorted(named)
    }
    states, following, summary, point = home_segment(
        value,
        ready,
        episode,
        (segment + 1) * signal_actuation().segment_seconds,
        continuation,
        signal_timelines=timelines,
    )
    assert point is None
    packed = _pack_states(value, ready, episode, states, summary, timelines)
    if segment != EPISODE // signal_actuation().segment_seconds - 1:
        packed = replace(packed, late_home=())
    frames_sha = hashlib.sha256(
        canonical_json(
            {
                "states": states,
                "signal_choices": following["signal_choices"],
                "initial_signal_cursors": following["initial_signal_cursors"],
            }
        )
    ).hexdigest()
    return packed, following, frames_sha


def compute_episode(data: Mapping[str, Any], episode: int) -> PackedTrafficEpisode:
    """Every second of ``episode`` of the input ``data`` describes, packed: the worker's job."""
    if type(episode) is not int or episode < 0:
        raise TrafficRefused("traffic_second_out_of_range", f"no episode {episode!r}")
    value = from_wire(data)
    ready = prepared(value)
    states, _trips, summary = _home_trip_rule(value, ready, episode)
    return _pack_states(value, ready, episode, states, summary)


def _pack_states(
    value: TrafficInput,
    ready: Prepared,
    episode: int,
    states: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    timelines: Mapping[str, SignalTimeline] | None = None,
) -> PackedTrafficEpisode:
    """Pack the states a whole episode or one sealed minute provides in the worker."""
    if not states:
        raise ValueError("a packed traffic segment carries at least one state")
    frames = [presentation_frame(state, ready.network, ready.catalogs) for state in states]
    genesis = initial_traffic(
        value.traffic_id, value.seed, ready.network, ready.catalogs, ready.fleet
    )
    homes = {vehicle["id"]: vehicle["space"] for vehicle in genesis["vehicles"]}
    last = {vehicle["id"]: vehicle for vehicle in states[-1]["vehicles"]}
    vehicles = []
    samples = []
    counts = []
    points = []
    for index, record in enumerate(frames[0]["vehicles"]):
        vehicles.append(
            {
                "vehicle_id": record["vehicle_id"],
                "vehicle_class": record["vehicle_class"],
                "body_family": record["body_family"],
                "colour": record["colour"],
                "dimensions_mm": dict(record["dimensions_mm"]),
            }
        )
        fields = {name: array(_TYPECODE) for name, _ in _FIELDS}
        count = array(_TYPECODE)
        flat = array(_TYPECODE)
        for frame in frames:
            item = frame["vehicles"][index]
            if item["vehicle_id"] != record["vehicle_id"]:
                raise ValueError("a frame lists its vehicles in another order")
            fields["front_axle_mm"].extend(item["front_axle_mm"])
            fields["rear_axle_mm"].extend(item["rear_axle_mm"])
            fields["mode"].append(MODES.index(item["mode"]))
            fields["speed_mm_per_s"].append(item["speed_mm_per_s"])
            fields["slot"].append(item["slot"])
            count.append(len(item["motion_path_mm"]))
            for point in item["motion_path_mm"]:
                flat.extend(point[:2])
        samples.append(tuple(fields[name].tobytes() for name, _ in _FIELDS))
        counts.append(count.tobytes())
        points.append(flat.tobytes())
    late = tuple(
        vehicle_id
        for vehicle_id in sorted(last)
        if last[vehicle_id]["mode"] != "parked" or last[vehicle_id]["space"] != homes[vehicle_id]
    )
    heads = signal_heads(ready.network, ready.catalogs)
    shown = [[array(_TYPECODE) for _group in item["groups"]] for item in heads]
    for state in states:
        for signal_index, row in enumerate(
            signal_codes(ready.network, ready.catalogs, state["second"], signal_timelines=timelines)
        ):
            for group_index, code in enumerate(row):
                shown[signal_index][group_index].append(code)
    return PackedTrafficEpisode(
        input_sha256=value.sha256,
        episode=episode,
        network_sha256=ready.network.digest,
        catalog_sha256=ready.catalogs.digest,
        vehicles=tuple(vehicles),
        samples=tuple(samples),
        path_counts=tuple(counts),
        path_points=tuple(points),
        late_home=late,
        signals=tuple(heads),
        signal_codes=tuple(tuple(codes.tobytes() for codes in row) for row in shown),
        trips=summary,
        derivation=ready.derived.document(),
    )


# -- a window, cut from episodes ----------------------------------------------------------------


def window_of(
    value: TrafficInput,
    episodes: Mapping[int, PackedTrafficEpisode],
    from_second: int,
    seconds: int,
) -> dict[str, Any]:
    """The window of ``seconds`` seconds from ``from_second``, read from the packed ``episodes``
    it spans: each second's presentation frame, grouped by vehicle."""
    check_request(from_second, seconds)
    end = from_second + seconds
    spans = []
    for episode in range(from_second // EPISODE, (end - 1) // EPISODE + 1):
        packed = episodes.get(episode)
        if packed is None or packed.input_sha256 != value.sha256:
            raise ValueError(f"episode {episode} of this input was not handed in")
        first = episode * EPISODE
        spans.append((packed, max(from_second, first) - first, min(end, first + EPISODE) - first))
    return _window_spans(value, spans, from_second, seconds)


def window_of_segments(
    value: TrafficInput,
    segments: Mapping[tuple[int, int], PackedTrafficEpisode],
    from_second: int,
    seconds: int,
) -> dict[str, Any]:
    """Cut a page window across sealed minutes, including a 1,200-second episode boundary."""
    check_request(from_second, seconds)
    end = from_second + seconds
    span_seconds = signal_actuation().segment_seconds
    spans = []
    for first in range(
        (from_second // span_seconds) * span_seconds,
        ((end - 1) // span_seconds) * span_seconds + 1,
        span_seconds,
    ):
        episode, local = divmod(first, EPISODE)
        segment = local // span_seconds
        packed = segments.get((episode, segment))
        if packed is None or packed.input_sha256 != value.sha256:
            raise ValueError(f"sealed traffic segment {episode}:{segment} was not handed in")
        spans.append(
            (packed, max(from_second, first) - first, min(end, first + span_seconds) - first)
        )
    return _window_spans(value, spans, from_second, seconds)


def _window_spans(
    value: TrafficInput,
    spans: Sequence[tuple[PackedTrafficEpisode, int, int]],
    from_second: int,
    seconds: int,
) -> dict[str, Any]:
    """The common packed-frame projection of whole episodes and sealed minute segments."""
    head = spans[0][0]
    vehicles = []
    for ordinal, static in enumerate(head.vehicles):
        row: dict[str, Any] = dict(static)
        for index, (name, width) in enumerate(_FIELDS):
            values = array(_TYPECODE)
            for packed, low, high in spans:
                source = array(_TYPECODE)
                source.frombytes(packed.samples[ordinal][index])
                values.extend(source[low * width : high * width])
            row[name] = values.tolist()
        paths = []
        for packed, low, high in spans:
            count = array(_TYPECODE)
            count.frombytes(packed.path_counts[ordinal])
            flat = array(_TYPECODE)
            flat.frombytes(packed.path_points[ordinal])
            offset = 2 * sum(count[:low])
            for second in range(low, high):
                width = 2 * count[second]
                paths.append(flat[offset : offset + width].tolist())
                offset += width
        row["motion_path_mm"] = paths
        vehicles.append(row)
    late = [
        {"second": (packed.episode + 1) * EPISODE - 1, "vehicle_id": vehicle_id}
        for packed, _low, high in spans
        if packed.late_home
        and high == len(packed.samples[0][0]) // (array(_TYPECODE).itemsize * _FIELDS[0][1])
        for vehicle_id in packed.late_home
    ]
    signals = []
    for signal_index, heads in enumerate(head.signals):
        groups = []
        for group_index, group in enumerate(heads["groups"]):
            codes = array(_TYPECODE)
            for packed, low, high in spans:
                source = array(_TYPECODE)
                source.frombytes(packed.signal_codes[signal_index][group_index])
                codes.extend(source[low:high])
            groups.append({**group, "codes": codes.tolist()})
        signals.append(
            {"signal_id": heads["signal_id"], "junction_id": heads["junction_id"], "groups": groups}
        )
    return {
        "profile": WINDOW_PROFILE,
        "module": ROADS,
        "input_sha256": value.sha256,
        "network_sha256": head.network_sha256,
        "catalog_sha256": head.catalog_sha256,
        "step_ms": ROADS_MODULE.step_ms,
        "episode_steps": EPISODE,
        "from_second": from_second,
        "seconds": seconds,
        "modes": list(MODES),
        "crossings_fed": False,
        "vehicles": vehicles,
        "late_home": late,
        "indications": {
            "vehicle": list(VEHICLE_INDICATIONS),
            "pedestrian": list(PEDESTRIAN_INDICATIONS),
        },
        "signals": signals,
        "episodes": list(
            {
                packed.episode: {
                    "episode": packed.episode,
                    "trips": packed.trips,
                    "derivation": packed.derivation,
                }
                for packed, _low, _high in spans
            }.values()
        ),
    }
