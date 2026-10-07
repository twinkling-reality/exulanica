"""Things that cross into a world from an outside program, and leave it: the port a door fills.

A visitor from an outside program comes in through a door (a bridge, under a grant the world's
owner issued) and leaves the same way. The door keeps the crossings it is handed, in the order it
wrote them. A society of things (:mod:`exulanica.world.society_things`) takes the crossings not
yet consumed at each minute, on the minute's connection, in its transaction and under the
society's lock, at most :data:`CROSSINGS_PER_MINUTE` a minute (the rest wait for the next), and
binds each to the event that minute recorded for it, once (:class:`CrossingStream`). A crossing the
society cannot take (a document that fails its check, a visitor or a carried thing whose id is
already here) is bound as refused with its own event, so no crossing ever stops a society's
minutes. Replay reads the bound crossings back with their minutes and recomputes every arrival and
departure from them, so a society's history never asks the door again.

A crossing is one of two documents:

*   an arrival, ``exulanica.thing-arrival/v1``: the arriving thing's id, its kind by key, version
    and digest, its origin record (class ``crossed``: the program that sent it, under its grant),
    the digest of the translation manifest that states what came across, the things it carries
    by id and kind, its grant, and the gate it arrives through, or none;
*   a departure, ``exulanica.thing-departure/v1``: who leaves, and why: ``sent_away`` by its
    program, or ``grant_ended``.

Neither carries a look: a visitor's look is a separate appearance record beside its arrival. An
arrival's origin record may carry bounded text the program states (authors, an attribution, source
references), and its kind and gate are keys of a fixed shape; a society copies none of the origin
into its state or events, which hold the visitor's id, its kind's reference, the bridge and the
grant, and what the visitor is called in the world is its kind's.

With no stream registered, nothing crosses and a society of things advances without visitors.

Pure apart from :func:`society_of_version`, which reads one row on the caller's connection.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, NamedTuple, Protocol

import psycopg

from exulanica.things.origin import OriginRefused, read_origin
from exulanica.world.deciders import BRIDGE

__all__ = [
    "ARRIVAL_PROFILE",
    "ARRIVAL_REFUSALS",
    "CROSSINGS_PER_MINUTE",
    "DEPARTURE_PROFILE",
    "DEPARTURE_REASONS",
    "DISPOSITIONS",
    "MALFORMED",
    "BoundCrossing",
    "ConsumedCrossing",
    "Crossing",
    "CrossingRefused",
    "CrossingStream",
    "check_arrival",
    "check_departure",
    "crossing_stream",
    "register_crossing_stream",
    "society_of_version",
]

ARRIVAL_PROFILE: Final = "exulanica.thing-arrival/v1"
DEPARTURE_PROFILE: Final = "exulanica.thing-departure/v1"
#: Why a departure happens: the program sent its visitor away, or the grant it came under ended.
DEPARTURE_REASONS: Final = ("sent_away", "grant_ended")
#: Why a crossing the society cannot read at all is refused, arrival or departure: its document
#: fails its check, so the society names nothing from it.
MALFORMED: Final = "malformed_crossing"
#: The most crossings one minute takes, in the door's order; the rest wait for later minutes, so a
#: door that queues without end never makes one minute do unbounded work.
CROSSINGS_PER_MINUTE: Final = 32
#: Why an arrival is refused: the version holds no gate to arrive through (or not the one named),
#: the society holds as many visitors as it takes, the kind is not one a visitor may be, or a thing
#: with that id is already here.
ARRIVAL_REFUSALS: Final = frozenset(
    {"no_arrival_place", "visitor_limit", "unknown_kind", "already_here", MALFORMED}
)
#: What became of each crossing, by its document: an arrival arrived or was refused, and a
#: departure departed, found nobody of that id here, or was refused as malformed.
DISPOSITIONS: Final = {
    ARRIVAL_PROFILE: ("arrived", "refused"),
    DEPARTURE_PROFILE: ("departed", "not_here", "refused"),
}
_ARRIVAL_FIELDS: Final = frozenset(
    {
        "profile",
        "arrival_id",
        "thing_id",
        "kind",
        "origin",
        "translation_manifest_sha256",
        "carried",
        "grant_id",
        "gate",
    }
)
_DEPARTURE_FIELDS: Final = frozenset({"profile", "departure_id", "thing_id", "reason"})
#: The most things one visitor carries in.
CARRIED_MAXIMUM: Final = 16
_KEY: Final = re.compile(r"[a-z][a-z0-9_]{0,47}")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_PLACED_ID: Final = re.compile(r"[a-z0-9]([a-z0-9:._-]{0,198}[a-z0-9])?")


class CrossingRefused(ValueError):
    """A crossing document that is not one this port reads, by the field at fault."""


@dataclass(frozen=True, slots=True)
class Crossing:
    """One crossing a door handed over, by its id: an arrival's ``arrival_id`` or a departure's
    ``departure_id``."""

    crossing_id: uuid.UUID
    document: Mapping[str, Any]


class BoundCrossing(NamedTuple):
    """What a minute did with one crossing, and the event it recorded for it."""

    crossing_id: uuid.UUID
    disposition: str
    reason: str | None
    event_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ConsumedCrossing:
    """A crossing a minute consumed, as replay reads it back."""

    tick: int
    crossing: Crossing
    bound: BoundCrossing


class CrossingStream(Protocol):
    """The door's side of crossings, called on the minute's connection and transaction, under the
    society's lock, so a crossing is consumed by one minute exactly once."""

    def pending(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        society_id: uuid.UUID,
        tick: int,
        *,
        limit: int,
    ) -> Sequence[Crossing]:
        """The first ``limit`` crossings for this society no minute has consumed, in the order the
        door wrote them; ``tick`` is the minute about to take them."""
        ...

    def bind(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        society_id: uuid.UUID,
        tick: int,
        bound: Sequence[BoundCrossing],
    ) -> None:
        """Record what the minute ``tick`` did with each crossing it took, once each, after its
        events are written."""
        ...

    def consumed(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, society_id: uuid.UUID
    ) -> Sequence[ConsumedCrossing]:
        """Every crossing a minute of this society consumed, by minute and in binding order."""
        ...


_registered: list[CrossingStream] = []


def register_crossing_stream(stream: CrossingStream | None) -> None:
    """Register the door's stream for this process, or none: then nothing crosses."""
    _registered.clear()
    if stream is not None:
        _registered.append(stream)


def crossing_stream() -> CrossingStream | None:
    """The stream registered for this process, or None."""
    return _registered[0] if _registered else None


def _uuid(where: str, value: object) -> uuid.UUID:
    if not isinstance(value, str):
        raise CrossingRefused(f"{where} is a UUID")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise CrossingRefused(f"{where} is a UUID") from exc
    if str(parsed) != value:
        raise CrossingRefused(f"{where} is a UUID in its canonical form")
    return parsed


def _kind(where: str, value: object) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != {"kind", "version", "sha256"}
        or not isinstance(value["kind"], str)
        or _KEY.fullmatch(value["kind"]) is None
        or type(value["version"]) is not int
        or not 1 <= value["version"] <= 10_000
        or not isinstance(value["sha256"], str)
        or _HEX64.fullmatch(value["sha256"]) is None
    ):
        raise CrossingRefused(f"{where} names a kind by key, version and digest")


def check_arrival(document: object) -> Mapping[str, Any]:
    """``document`` held to the arrival's shape, or :class:`CrossingRefused`. Whether its kind is
    shipped, and where it arrives, are the society's to say."""
    if not isinstance(document, dict) or set(document) != _ARRIVAL_FIELDS:
        raise CrossingRefused("an arrival states exactly its fields")
    if document["profile"] != ARRIVAL_PROFILE:
        raise CrossingRefused(f"an arrival is an {ARRIVAL_PROFILE} document")
    _uuid("arrival_id", document["arrival_id"])
    _uuid("thing_id", document["thing_id"])
    _uuid("grant_id", document["grant_id"])
    _kind("kind", document["kind"])
    try:
        origin = read_origin(document["origin"])
    except OriginRefused as exc:
        raise CrossingRefused(f"origin: {exc}") from exc
    by = origin.document["by"]
    if (
        origin.klass != "crossed"
        or by["grant_id"] != document["grant_id"]
        or BRIDGE.fullmatch(by["bridge"]) is None
    ):
        raise CrossingRefused("an arrival's origin is the program that sent it, under its grant")
    manifest = document["translation_manifest_sha256"]
    if not isinstance(manifest, str) or _HEX64.fullmatch(manifest) is None:
        raise CrossingRefused("translation_manifest_sha256 is a digest")
    carried = document["carried"]
    if not isinstance(carried, list) or len(carried) > CARRIED_MAXIMUM:
        raise CrossingRefused(f"carried is a list of at most {CARRIED_MAXIMUM} things")
    seen = set()
    for index, held in enumerate(carried):
        if not isinstance(held, dict) or set(held) != {"thing_id", "kind"}:
            raise CrossingRefused(f"carried[{index}] states a thing's id and kind")
        seen.add(_uuid(f"carried[{index}].thing_id", held["thing_id"]))
        _kind(f"carried[{index}].kind", held["kind"])
    if len(seen) != len(carried) or _uuid("thing_id", document["thing_id"]) in seen:
        raise CrossingRefused("a visitor and what it carries are each one thing")
    gate = document["gate"]
    if gate is not None and (not isinstance(gate, str) or _PLACED_ID.fullmatch(gate) is None):
        raise CrossingRefused("gate is a placed thing's id, or none")
    return document


def check_departure(document: object) -> Mapping[str, Any]:
    """``document`` held to the departure's shape, or :class:`CrossingRefused`."""
    if not isinstance(document, dict) or set(document) != _DEPARTURE_FIELDS:
        raise CrossingRefused("a departure states exactly its fields")
    if document["profile"] != DEPARTURE_PROFILE:
        raise CrossingRefused(f"a departure is an {DEPARTURE_PROFILE} document")
    _uuid("departure_id", document["departure_id"])
    _uuid("thing_id", document["thing_id"])
    if document["reason"] not in DEPARTURE_REASONS:
        raise CrossingRefused(f"a departure's reason is one of {list(DEPARTURE_REASONS)}")
    return document


def check_crossing(crossing: Crossing) -> Mapping[str, Any]:
    """A crossing held to its document's shape, its id the document's own."""
    document = crossing.document
    profile = document.get("profile") if isinstance(document, Mapping) else None
    if profile == ARRIVAL_PROFILE:
        checked = check_arrival(dict(document))
        named = checked["arrival_id"]
    elif profile == DEPARTURE_PROFILE:
        checked = check_departure(dict(document))
        named = checked["departure_id"]
    else:
        raise CrossingRefused("a crossing is an arrival or a departure")
    if str(crossing.crossing_id) != named:
        raise CrossingRefused("a crossing's id is its document's own")
    return checked


def society_of_version(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, version_id: uuid.UUID
) -> dict[str, Any] | None:
    """The society a world version holds, by its id and engine, or None where it holds none: what
    a door asks before it records a crossing, on its own workspace-scoped connection."""
    row = connection.execute(
        "select society_id,engine_version from world_society where workspace_id=%s "
        "and world_id=%s and version_id=%s",
        (workspace_id, world_id, version_id),
    ).fetchone()
    if row is None:
        return None
    return {"society_id": row["society_id"], "engine_version": row["engine_version"]}
