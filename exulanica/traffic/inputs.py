"""The two ordered inputs traffic consumes: trip requests and the pedestrian crossing feed.

**Trip requests** (``exulanica.traffic-trip-request/v1``). A request names a fleet vehicle, the
second it wants to leave and a destination: either a parking space, or a society destination by
its stable ``destination_id`` and the ``street_segment_ordinal`` of its frontage. Those two
fields are the whole of what traffic reads of a society place, and every ``society-place``
profile states both, so no profile version is named here: naming one would make this line false
the day the society publishes the next, and a trip request would not have changed.
``request_seq`` starts at 1 and is contiguous.
A request is never a movement: it is decided by the next step at or after its second.

**Crossing feed** (``exulanica.traffic-crossing-feed/v1``). The living society's v4 walkers do
not wait for a grant; each records ``{crossing_id, arrival_second, duration_seconds}`` in its
``route_progressed`` event. :func:`feed_from_society_crossings` turns those into absolute
seconds (society tick times 60 plus the arrival second) and keeps their source keys. Each feed
document states the last second it covers, and a step at second ``t`` refuses to run unless the
feeds cover ``t + LOOKAHEAD_S``: traffic runs a society minute behind so that no pedestrian can
step onto a crossing a vehicle has already committed to.

A pedestrian occupies the whole band from its arrival second through arrival plus duration,
inclusive at both ends.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.traffic.errors import InvalidTrafficInputError

__all__ = [
    "CROSSING_FEED_PROFILE",
    "LOOKAHEAD_S",
    "SOCIETY_SECONDS_PER_TICK",
    "TRIP_REQUEST_PROFILE",
    "CrossingEntry",
    "CrossingFeed",
    "TrafficInputs",
    "TripRequest",
    "feed_from_society_crossings",
    "input_sha256",
]

TRIP_REQUEST_PROFILE: Final = "exulanica.traffic-trip-request/v1"
CROSSING_FEED_PROFILE: Final = "exulanica.traffic-crossing-feed/v1"
#: A society tick is one simulated minute and a traffic tick one simulated second.
SOCIETY_SECONDS_PER_TICK: Final = 60
#: How far ahead the crossing feed must reach before a second may be simulated.
LOOKAHEAD_S: Final = 60
_DESTINATION_KINDS: Final = ("space", "frontage")


def input_sha256(document: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(document)).hexdigest()


def _int(name: str, value: object, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise InvalidTrafficInputError(f"{name} is an int of at least {minimum}, got {value!r}")
    return value


def _text(name: str, value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise InvalidTrafficInputError(f"{name} is non-empty text")
    return value


@dataclass(frozen=True, slots=True)
class TripRequest:
    request_seq: int
    trip_id: str
    vehicle_id: str
    depart_second: int
    destination_kind: str
    #: A space identity, or a society destination id.
    destination: str
    #: The frontage segment for a society destination; -1 for a space.
    street_segment_ordinal: int
    source: str

    def __post_init__(self) -> None:
        _int("request_seq", self.request_seq, 1)
        _text("trip_id", self.trip_id)
        _text("vehicle_id", self.vehicle_id)
        _int("depart_second", self.depart_second, 0)
        if self.destination_kind not in _DESTINATION_KINDS:
            raise InvalidTrafficInputError(f"destination kind is one of {_DESTINATION_KINDS}")
        _text("destination", self.destination)
        if self.destination_kind == "space" and self.street_segment_ordinal != -1:
            raise InvalidTrafficInputError("a space destination carries no segment")
        if self.destination_kind == "frontage":
            _int("street_segment_ordinal", self.street_segment_ordinal, 0)
        _text("source", self.source)

    def document(self) -> dict[str, Any]:
        return {
            "profile": TRIP_REQUEST_PROFILE,
            "request_seq": self.request_seq,
            "trip_id": self.trip_id,
            "vehicle_id": self.vehicle_id,
            "depart_second": self.depart_second,
            "destination": {
                "kind": self.destination_kind,
                "id": self.destination,
                "street_segment_ordinal": self.street_segment_ordinal,
            },
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class CrossingEntry:
    crossing_id: str
    arrival_second: int
    duration_seconds: int
    #: ``society_id:tick:event_order`` of the walker event, or a fixture label.
    source: str

    def __post_init__(self) -> None:
        _text("crossing_id", self.crossing_id)
        _int("arrival_second", self.arrival_second, 0)
        _int("duration_seconds", self.duration_seconds, 1)
        _text("source", self.source)

    @property
    def last_second(self) -> int:
        return self.arrival_second + self.duration_seconds


@dataclass(frozen=True, slots=True)
class CrossingFeed:
    feed_seq: int
    covers_through_second: int
    entries: tuple[CrossingEntry, ...]

    def __post_init__(self) -> None:
        _int("feed_seq", self.feed_seq, 1)
        _int("covers_through_second", self.covers_through_second, 0)
        ordered = sorted(
            self.entries, key=lambda entry: (entry.arrival_second, entry.crossing_id, entry.source)
        )
        if list(self.entries) != ordered:
            raise InvalidTrafficInputError(
                "feed entries are sorted by arrival, crossing and source"
            )
        for entry in self.entries:
            if entry.arrival_second > self.covers_through_second:
                raise InvalidTrafficInputError(
                    "a feed entry arrives after the second the feed covers"
                )

    def document(self) -> dict[str, Any]:
        return {
            "profile": CROSSING_FEED_PROFILE,
            "feed_seq": self.feed_seq,
            "covers_through_second": self.covers_through_second,
            "entries": [
                {
                    "crossing_id": entry.crossing_id,
                    "arrival_second": entry.arrival_second,
                    "duration_seconds": entry.duration_seconds,
                    "source": entry.source,
                }
                for entry in self.entries
            ],
        }


@dataclass(frozen=True)
class TrafficInputs:
    """Everything a run consumes, in order. Replay needs exactly these and nothing else."""

    trips: tuple[TripRequest, ...]
    feeds: tuple[CrossingFeed, ...]

    def __post_init__(self) -> None:
        for index, trip in enumerate(self.trips, start=1):
            if trip.request_seq != index:
                raise InvalidTrafficInputError("trip requests are contiguous from 1")
        seen = [trip.trip_id for trip in self.trips]
        if len(set(seen)) != len(seen):
            raise InvalidTrafficInputError("a trip id repeats")
        previous = -1
        for index, feed in enumerate(self.feeds, start=1):
            if feed.feed_seq != index:
                raise InvalidTrafficInputError("crossing feeds are contiguous from 1")
            if feed.covers_through_second <= previous:
                raise InvalidTrafficInputError("each crossing feed covers later seconds")
            if feed.entries and feed.entries[0].arrival_second <= previous:
                raise InvalidTrafficInputError(
                    "a feed entry falls in a second an earlier feed covered"
                )
            previous = feed.covers_through_second

    def covered_through(self, feed_count: int) -> int:
        return self.feeds[feed_count - 1].covers_through_second if feed_count else -1

    def feeds_needed(self, second: int) -> int:
        """How many feeds a step at ``second`` needs, or raise if they do not reach far enough."""
        needed = second + LOOKAHEAD_S
        for index, feed in enumerate(self.feeds, start=1):
            if feed.covers_through_second >= needed:
                return index
        raise InvalidTrafficInputError(
            f"the crossing feed covers second {self.covered_through(len(self.feeds))}; "
            f"second {second} needs it to reach {needed}"
        )

    def trips_at(self, second: int) -> list[TripRequest]:
        return [trip for trip in self.trips if trip.depart_second == second]

    def occupancies(self, feed_count: int) -> list[CrossingEntry]:
        return [entry for feed in self.feeds[:feed_count] for entry in feed.entries]

    def digest_through(self, second: int, feed_count: int) -> str:
        return input_sha256(
            {
                "trips": [trip.document() for trip in self.trips if trip.depart_second <= second],
                "feeds": [feed.document() for feed in self.feeds[:feed_count]],
            }
        )


def feed_from_society_crossings(
    feed_seq: int,
    society_id: str,
    covers_through_second: int,
    walkers: Iterable[tuple[int, int, Sequence[dict[str, Any]]]],
) -> CrossingFeed:
    """Build a feed from ``(society tick, event order, crossings)`` of v4 ``route_progressed``.

    Each crossing is ``{crossing_id, arrival_second, duration_seconds}`` with the arrival second
    inside the society tick. The absolute arrival is ``tick * 60 + arrival_second``.
    """
    entries = []
    for tick, order, crossings in walkers:
        for crossing in crossings:
            if set(crossing) != {"crossing_id", "arrival_second", "duration_seconds"}:
                raise InvalidTrafficInputError("a society crossing entry has exactly three fields")
            arrival = crossing["arrival_second"]
            if type(arrival) is not int or not 0 <= arrival < SOCIETY_SECONDS_PER_TICK:
                raise InvalidTrafficInputError("a society arrival second is 0 to 59")
            entries.append(
                CrossingEntry(
                    crossing_id=crossing["crossing_id"],
                    arrival_second=tick * SOCIETY_SECONDS_PER_TICK + arrival,
                    duration_seconds=crossing["duration_seconds"],
                    source=f"{society_id}:{tick}:{order}",
                )
            )
    entries.sort(key=lambda entry: (entry.arrival_second, entry.crossing_id, entry.source))
    return CrossingFeed(feed_seq, covers_through_second, tuple(entries))
