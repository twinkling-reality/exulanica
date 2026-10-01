"""A world version's clock: which timeline each system runs on, and how walkers reach traffic.

**Profiles** are data (``assets/catalogs/world-clock/world-clock-profile.v1.json``), two of them:

- ``legacy`` (``exulanica.world-clock/legacy-v1``) is the timing every world version has until a
  transition says otherwise. The society advances its own minutes. Traffic and flight keep shared
  real time, and no walker's crossing is fed to traffic.
- ``coupled`` (``exulanica.world-clock/coupled-v1``) is one simulated timeline, opened on one
  version by an explicit, one-way transition. The society's tick is the only authority. Traffic
  and flight take their positions from the era the transition opened, never from the wall clock,
  and traffic reads the crossing occupancy the society committed.

**World seconds.** The society state at tick ``N`` stands at world second ``60 N``, and the minute
that produces tick ``N`` covers world seconds ``[60 (N - 1), 60 N)``. A crossing a walker entered in
that minute, ``arrival_second`` into it, is at world second ``60 (N - 1) + arrival_second``.

**Eras and timelines.** A transition opens an era at the society's tick ``T0``, world second
``W0 = 60 T0``. Traffic's sealed minutes, episodes and signal choices are keyed by the version's
traffic timeline: Unix seconds while the version is legacy, and from the transition
``U0 + (w - W0)``, where ``U0`` (:func:`timeline_origin`) is a whole traffic episode strictly after
both the wall clock at the transition and the version's last sealed legacy segment. The timeline
therefore never runs backwards within a version, so a signal choice, request or sealed segment of
the legacy era can never collide with one of the coupled era. Flight's step is ten times the
traffic timeline's second: its episodes are five minutes and ``U0`` is a whole twenty.

**Crossing occupancy** (``exulanica.crossing-occupancy/v1``, :func:`minute_occupancy`): for each
committed minute of a coupled era, every interval in which a walker may stand on a crossing, in
world seconds, inclusive at both ends. An interval ``[s, e]`` protects real time ``(s - 1, e + 1)``,
exactly what the traffic step's pedestrian rule and the independent checker's ``crossing_conflict``
rule protect. Two bases:

- ``entered``: each crossing a walker recorded entering in the minute. Its arrival is the floor of
  the true start and its duration the ceiling of the walk across, so the claim covers the walk.
- ``on_crossing_at_minute_start``: each walker whose location at the minute's start is on a crossing
  edge, from the minute's start until the floor of the time its remaining length takes at its own
  speed, or the whole minute when it is still on that edge at the minute's end. A walker whose plan
  is abandoned part way across (any edit that changes the walking graph abandons every plan) stands
  on the crossing, blocked, and records no entry when it walks on; the recorded entries alone would
  leave that crossing looking free.

**The crossing feed** (``exulanica.crossing-feed-projection/v1``, :func:`crossing_feeds`): one
traffic episode's view of the occupancy, as the traffic step's input,
``exulanica.traffic-crossing-feed/v1``. Walkers name crossings by the city crossing record's
identity and traffic's bands by ``crossing:<segment ordinal>:<offset>``, so the projection maps one
to the other through the compiled network, by the record identity both keep. Feed ``q`` covers the
episode's local seconds through ``60 q + 59``, feed 1 its first two minutes, and holds exactly the
intervals that begin in that span, those begun before the episode clipped to its start. What a feed
holds depends only on the occupancy, so a feed is the same however much of the episode is sealed.

Pure: no connection, no store and no clock of its own.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.catalogs import CatalogSchema, integer_field, load_catalog, text_field
from exulanica.movement.registry import FLIGHT, ROADS, built_module
from exulanica.traffic.inputs import (
    LOOKAHEAD_S,
    SOCIETY_SECONDS_PER_TICK,
    CrossingEntry,
    CrossingFeed,
)
from exulanica.world.society import society_state_sha256
from exulanica.world.society_controls import MAX_CATCHUP_TICKS

__all__ = [
    "BASES",
    "CLOCK_PROFILE",
    "COUPLED",
    "EVENT_PROFILE",
    "FEED_PROJECTION_PROFILE",
    "LEGACY",
    "OCCUPANCY_PROFILE",
    "TRAFFIC_STATES",
    "WORLD_STATES",
    "ClockProfile",
    "ClockRefused",
    "Era",
    "clock_profile",
    "clock_profiles",
    "crossing_edges",
    "crossing_feeds",
    "envelope_report",
    "feed_projection_sha256",
    "lead_room",
    "minute_occupancy",
    "occupancy_intervals",
    "timeline_origin",
    "traffic_timebase",
]

_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "catalogs", "world-clock")
)
_CATALOG: Final = "world-clock-profile"
_VERSION: Final = 1
LEGACY: Final = "legacy"
COUPLED: Final = "coupled"
#: The clock read's profile.
CLOCK_PROFILE: Final = "exulanica.world-clock/v1"
#: A clock event's profile, the append-only receipts of transitions and of what traffic did.
EVENT_PROFILE: Final = "exulanica.world-clock-event/v1"
OCCUPANCY_PROFILE: Final = "exulanica.crossing-occupancy/v1"
FEED_PROJECTION_PROFILE: Final = "exulanica.crossing-feed-projection/v1"
#: Why an interval is in a minute's occupancy, in the order they are listed for one second.
BASES: Final = ("entered", "on_crossing_at_minute_start")
#: What a world's clock is doing, as its read says.
WORLD_STATES: Final = ("playing", "paused", "waiting", "blocked")
#: What a coupled world's traffic is doing: sealing the society's minutes, waiting for the next
#: one, blocked by a named fault in what it reads, or unavailable for the era by a lasting refusal.
TRAFFIC_STATES: Final = ("following", "waiting_for_society", "blocked", "unavailable")
_TIMEBASES: Final = {LEGACY: "unix", COUPLED: "world"}
_ROADS: Final = built_module(ROADS)
#: A traffic episode, in seconds: a coupled era's timeline starts on one.
EPISODE_SECONDS: Final = _ROADS.value("episode_steps") * _ROADS.step_ms // 1000
_FLIGHT: Final = built_module(FLIGHT)
_FLIGHT_EPISODE_MS: Final = _FLIGHT.value("episode_steps") * _FLIGHT.step_ms
#: A flight step is this many to a traffic second.
FLIGHT_STEPS_PER_SECOND: Final = 1000 // _FLIGHT.step_ms


class ClockRefused(ValueError):
    """A clock operation or projection refused by a stable code, which is what a caller receives."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail

    def __reduce__(self) -> tuple[Any, ...]:
        return (type(self), (self.code, self.detail))


@dataclass(frozen=True, slots=True)
class ClockProfile:
    """One profile of the catalog: which timeline each system runs on and the bounds it keeps."""

    key: str
    profile: str
    time_authority: str
    traffic_module: str
    flight_module: str
    crossings_fed: bool
    seconds_per_tick: int
    lead_ticks: int
    crossing_lookahead_seconds: int
    catchup_ticks_maximum: int
    follower_minutes_per_turn: int
    legacy_signal_catchup_episodes: int
    verify_society_ticks_maximum: int
    verify_traffic_minutes_maximum: int


@cache
def clock_profiles() -> Mapping[str, ClockProfile]:
    """The profiles, checked against the constants of the systems they describe."""
    catalog = load_catalog(
        _DIRECTORY.joinpath(f"{_CATALOG}.v{_VERSION}.json"),
        CatalogSchema(
            _CATALOG,
            _VERSION,
            (
                ("profile", text_field),
                ("time_authority", text_field),
                ("traffic_module", text_field),
                ("flight_module", text_field),
                ("crossings_fed", integer_field(0, 1)),
                ("seconds_per_tick", integer_field(1, 3600)),
                ("lead_ticks", integer_field(0, 60)),
                ("crossing_lookahead_seconds", integer_field(1, 3600)),
                ("catchup_ticks_maximum", integer_field(1, 60)),
                ("follower_minutes_per_turn", integer_field(1, 60)),
                ("legacy_signal_catchup_episodes", integer_field(1, 72)),
                ("verify_society_ticks_maximum", integer_field(1, 10_080)),
                ("verify_traffic_minutes_maximum", integer_field(1, 1440)),
                ("reason", text_field),
            ),
        ),
    )
    if set(catalog.keys()) != {LEGACY, COUPLED}:
        raise ValueError("the world clock states exactly a legacy and a coupled profile")
    profiles = {}
    for entry in catalog.entries:
        values = dict(entry.values)
        profile = ClockProfile(
            key=entry.key,
            profile=str(values["profile"]),
            time_authority=str(values["time_authority"]),
            traffic_module=str(values["traffic_module"]),
            flight_module=str(values["flight_module"]),
            crossings_fed=values["crossings_fed"] == 1,
            seconds_per_tick=int(values["seconds_per_tick"]),
            lead_ticks=int(values["lead_ticks"]),
            crossing_lookahead_seconds=int(values["crossing_lookahead_seconds"]),
            catchup_ticks_maximum=int(values["catchup_ticks_maximum"]),
            follower_minutes_per_turn=int(values["follower_minutes_per_turn"]),
            legacy_signal_catchup_episodes=int(values["legacy_signal_catchup_episodes"]),
            verify_society_ticks_maximum=int(values["verify_society_ticks_maximum"]),
            verify_traffic_minutes_maximum=int(values["verify_traffic_minutes_maximum"]),
        )
        # The profile states what the systems do; it may not state something else.
        if (
            profile.seconds_per_tick != SOCIETY_SECONDS_PER_TICK
            or profile.crossing_lookahead_seconds != LOOKAHEAD_S
            or profile.catchup_ticks_maximum != MAX_CATCHUP_TICKS
        ):
            raise ValueError(f"world clock profile {entry.key} restates a system constant wrongly")
        profiles[entry.key] = profile
    coupled = profiles[COUPLED]
    # A traffic minute needs the society's minutes through its lookahead, and one more minute of
    # room to be sealed in: less lead than that and traffic could never advance.
    least = -(-coupled.crossing_lookahead_seconds // coupled.seconds_per_tick) + 1
    if coupled.lead_ticks < least or not coupled.crossings_fed:
        raise ValueError("the coupled profile's lead does not let traffic advance")
    if profiles[LEGACY].lead_ticks or profiles[LEGACY].crossings_fed:
        raise ValueError("the legacy profile couples nothing")
    if (
        _FLIGHT_EPISODE_MS * (EPISODE_SECONDS * 1000 // _FLIGHT_EPISODE_MS)
        != EPISODE_SECONDS * 1000
    ):
        raise ValueError("a traffic episode is not a whole number of flight episodes")
    return profiles


def clock_profile(key: str) -> ClockProfile:
    """The profile ``key``; an unknown one is refused by name."""
    found = clock_profiles().get(key)
    if found is None:
        raise ClockRefused("clock_profile_unknown", f"no world clock profile is named {key!r}")
    return found


def traffic_timebase(profile_key: str) -> str:
    """How a version's traffic seconds, and the signal choices keyed by them, are to be read:
    ``unix`` for a legacy version, ``world`` for a coupled one (convert with the era's mapping)."""
    return _TIMEBASES[clock_profile(profile_key).key]


def timeline_origin(now_second: int, latest_legacy_end_second: int | None) -> int:
    """``U0``: the first whole traffic episode strictly after the wall clock and after the
    version's last sealed legacy segment, so the traffic timeline never runs backwards."""
    floor = max(now_second, 0 if latest_legacy_end_second is None else latest_legacy_end_second)
    return (floor // EPISODE_SECONDS + 1) * EPISODE_SECONDS


@dataclass(frozen=True, slots=True)
class Era:
    """One era of a coupled clock: where it began and how its timelines map to world seconds."""

    era: int
    start_tick: int
    seconds_per_tick: int
    #: ``U0``, the traffic timeline's second at the era's first world second.
    timeline_origin_second: int

    @property
    def start_world_second(self) -> int:
        return self.start_tick * self.seconds_per_tick

    def world_second_of_tick(self, tick: int) -> int:
        return tick * self.seconds_per_tick

    def traffic_second(self, world_second: int) -> int:
        return self.timeline_origin_second + world_second - self.start_world_second

    def world_second(self, traffic_second: int) -> int:
        return traffic_second - self.timeline_origin_second + self.start_world_second

    def flight_step(self, world_second: int) -> int:
        return self.traffic_second(world_second) * FLIGHT_STEPS_PER_SECOND

    def world_second_of_step(self, step: int) -> int:
        return self.world_second(step // FLIGHT_STEPS_PER_SECOND)


def lead_room(lead_ticks: int, society_tick: int, sealed_through_tick: int) -> int:
    """How many more minutes the society may commit before traffic seals another."""
    return max(0, lead_ticks - (society_tick - sealed_through_tick))


# -- crossing occupancy ---------------------------------------------------------------------------


def crossing_edges(places: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """``edge_id -> crossing_id`` over the place documents a minute read. One edge naming two
    crossings is refused: the occupancy could not say which band a walker stands on."""
    found: dict[str, str] = {}
    for place in places:
        for crossing in place.get("crossings", ()):
            edge, identity = crossing["edge_id"], crossing["crossing_id"]
            if found.setdefault(edge, identity) != identity:
                raise ClockRefused(
                    "crossing_edge_ambiguous", f"edge {edge} is two crossings across the minute"
                )
    return found


def minute_occupancy(
    *,
    society_id: str,
    era: int,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    crossings_by_edge: Mapping[str, str],
    place_sha256: str,
    seconds_per_tick: int = SOCIETY_SECONDS_PER_TICK,
    previous_state_sha256: str | None = None,
    state_sha256: str | None = None,
) -> dict[str, Any]:
    """The crossing occupancy of the minute from ``before`` to ``after``, as its record.

    ``events`` are the minute's event documents; ``crossings_by_edge`` is :func:`crossing_edges`
    over the places the minute read. A caller that already holds the two states' digests may pass
    them rather than have them computed again.
    """
    tick = after["tick"]
    if before["tick"] + 1 != tick:
        raise ClockRefused("crossing_occupancy_mismatch", "a minute's occupancy spans one tick")
    known = set(crossings_by_edge.values())
    start = (tick - 1) * seconds_per_tick
    intervals: list[dict[str, Any]] = []
    for document in events:
        if document.get("tick") != tick:
            raise ClockRefused("crossing_occupancy_mismatch", "an event of another minute")
        for crossing in document.get("crossings", ()):
            arrival, duration = crossing["arrival_second"], crossing["duration_seconds"]
            if (
                type(arrival) is not int
                or not 0 <= arrival < seconds_per_tick
                or type(duration) is not int
                or duration < 1
                or crossing["crossing_id"] not in known
            ):
                raise ClockRefused(
                    "crossing_occupancy_mismatch",
                    "a recorded crossing entry does not describe a crossing of this minute's place",
                )
            intervals.append(
                {
                    "crossing_id": crossing["crossing_id"],
                    "from_second": start + arrival,
                    "through_second": start + arrival + duration,
                    "subject_id": document["subject_id"],
                    "basis": "entered",
                }
            )
    later = {person["id"]: person for person in after["inhabitants"]}
    for person in before["inhabitants"]:
        edge = person["location"]["edge"]
        if edge is None or edge["edge_id"] not in crossings_by_edge:
            continue
        now = later.get(person["id"])
        held = now["location"]["edge"] if now is not None else None
        if held is not None and held["edge_id"] == edge["edge_id"]:
            through = start + seconds_per_tick - 1
        else:
            # Walkers always go on forward from where they stand on an edge, from the minute's
            # start, so the rest of the edge at their own speed is when they leave it.
            remaining = edge["length_mm"] - edge["progress_mm"]
            leaves = remaining * seconds_per_tick // person["walk_speed_mm_per_tick"]
            through = start + min(seconds_per_tick - 1, leaves)
        intervals.append(
            {
                "crossing_id": crossings_by_edge[edge["edge_id"]],
                "from_second": start,
                "through_second": through,
                "subject_id": person["id"],
                "basis": "on_crossing_at_minute_start",
            }
        )
    intervals.sort(
        key=lambda item: (
            item["from_second"],
            item["crossing_id"],
            item["subject_id"],
            BASES.index(item["basis"]),
            item["through_second"],
        )
    )
    document = {
        "profile": OCCUPANCY_PROFILE,
        "society_id": str(society_id),
        "era": era,
        "tick": tick,
        "minute_start_second": start,
        "previous_state_sha256": previous_state_sha256 or society_state_sha256(dict(before)),
        "state_sha256": state_sha256 or society_state_sha256(dict(after)),
        "place_sha256": place_sha256,
        "intervals": intervals,
    }
    document["document_sha256"] = hashlib.sha256(canonical_json(document)).hexdigest()
    return document


def occupancy_intervals(documents: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every interval of the occupancy ``documents``, each with the tick it was recorded in."""
    return [
        {**interval, "tick": document["tick"]}
        for document in documents
        for interval in document["intervals"]
    ]


# -- the crossing feed ----------------------------------------------------------------------------


def _feed_span(feed_seq: int) -> tuple[int, int]:
    """The episode-local seconds whose arrivals feed ``feed_seq`` holds, inclusive."""
    last = 60 * feed_seq + 59
    return (0 if feed_seq == 1 else 60 * feed_seq), last


def crossing_feeds(
    intervals: Iterable[Mapping[str, Any]],
    *,
    era: Era,
    episode_first_second: int,
    covers_through_local_second: int,
    bands: Mapping[str, str],
) -> tuple[CrossingFeed, ...]:
    """The feeds one traffic episode reads, through ``covers_through_local_second``.

    ``intervals`` are occupancy intervals in world seconds (:func:`occupancy_intervals`),
    ``episode_first_second`` the episode's first second on the traffic timeline, and ``bands``
    maps a crossing record's identity to its band's ``society_crossing_id``. A crossing no band
    carries is refused: a walker would stand where traffic could not see one.
    """
    if covers_through_local_second < 119 or (covers_through_local_second - 59) % 60:
        raise ClockRefused("crossing_feed_span", "a feed covers whole minutes from the second")
    count = (covers_through_local_second - 59) // 60
    held: dict[int, list[CrossingEntry]] = {seq: [] for seq in range(1, count + 1)}
    for interval in intervals:
        band = bands.get(interval["crossing_id"])
        if band is None:
            raise ClockRefused(
                "crossing_occupancy_unmapped",
                f"crossing {interval['crossing_id']} is no band of these roads",
            )
        first = era.traffic_second(interval["from_second"]) - episode_first_second
        last = era.traffic_second(interval["through_second"]) - episode_first_second
        if last < 0 or first > covers_through_local_second:
            continue
        first = max(0, first)
        seq = 1 if first < 120 else first // 60
        held[seq].append(
            CrossingEntry(
                crossing_id=band,
                arrival_second=first,
                duration_seconds=max(1, last - first),
                source=f"{interval['subject_id']}:{interval['tick']}:{interval['basis']}",
            )
        )
    feeds = []
    for seq in range(1, count + 1):
        low, high = _feed_span(seq)
        entries = sorted(
            held[seq], key=lambda entry: (entry.arrival_second, entry.crossing_id, entry.source)
        )
        assert all(low <= entry.arrival_second <= high for entry in entries)
        feeds.append(CrossingFeed(seq, high, tuple(entries)))
    return tuple(feeds)


def feed_projection_sha256(feeds: Sequence[CrossingFeed]) -> str:
    """The digest a sealed traffic minute binds the feeds it consumed by."""
    return hashlib.sha256(
        canonical_json(
            {"profile": FEED_PROJECTION_PROFILE, "feeds": [feed.document() for feed in feeds]}
        )
    ).hexdigest()


# -- the demand envelope --------------------------------------------------------------------------


def envelope_report(
    intervals: Iterable[tuple[str, int, int]],
    *,
    start: int,
    end: int,
    window_seconds: int,
    gap_seconds: int,
) -> dict[str, Any]:
    """Whether each crossing's occupancy, over seconds ``[start, end)``, keeps inside the envelope
    ``E(window_seconds, gap_seconds)``: every window of ``window_seconds`` holds a run of at least
    ``gap_seconds`` seconds with no walker on the crossing.

    ``intervals`` are ``(crossing, from_second, through_second)``, inclusive. For each crossing the
    report gives its occupied seconds, its longest occupied run, and the windows outside the
    envelope as merged spans of their start seconds.
    """
    if not 0 < gap_seconds <= window_seconds or end <= start:
        raise ValueError("an envelope window holds its gap, over a span of seconds")
    occupied: dict[str, set[int]] = {}
    for crossing, first, last in intervals:
        seconds = occupied.setdefault(crossing, set())
        seconds.update(range(max(first, start), min(last, end - 1) + 1))
    report: dict[str, Any] = {}
    for crossing in sorted(occupied):
        taken = occupied[crossing]
        # free_run[i]: the length of the free run ending at second start + i.
        free_run: list[int] = []
        run = 0
        longest_taken = 0
        taken_run = 0
        for second in range(start, end):
            if second in taken:
                run = 0
                taken_run += 1
                longest_taken = max(longest_taken, taken_run)
            else:
                run += 1
                taken_run = 0
            free_run.append(run)
        # A window [first, first + window) holds a free run of gap seconds exactly when a run of
        # at least gap seconds ends at one of its seconds from first + gap - 1 on: the last gap
        # seconds of that run then lie inside the window.
        good = [0]
        for length in free_run:
            good.append(good[-1] + (1 if length >= gap_seconds else 0))
        outside: list[list[int]] = []
        for first in range(start, end - window_seconds + 1):
            low = first + gap_seconds - 1 - start
            high = first + window_seconds - start
            if good[high] - good[low] == 0:
                if outside and outside[-1][1] == first - 1:
                    outside[-1][1] = first
                else:
                    outside.append([first, first])
        report[crossing] = {
            "occupied_seconds": len(taken),
            "longest_occupied_run_seconds": longest_taken,
            "outside_window_starts": outside,
        }
    return report
