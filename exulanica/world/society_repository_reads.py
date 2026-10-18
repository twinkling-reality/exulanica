"""What a society read answers: its snapshot, the lines said, its inputs' provenance and its events.

A part of :class:`~exulanica.world.society_repository.SocietyRepository` (its methods read the
repository's connection and workspace and reach its authorization and stored rows through
``self``), with the event cursor and the bounds an events window is read under.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from typing import Any

from exulanica.world.society import (
    UnavailableSocietyInput,
    UnknownSociety,
    inputs_ahead,
    served_clock,
)
from exulanica.world.society_engines import (
    INPUT_ENGINES,
    society_engine,
)

#: Profiles that consume authorized inputs and record transition receipts, from the engine table.


#: Profiles that consume authorized inputs and record transition receipts, from the engine table.
INPUT_PROFILES = INPUT_ENGINES

#: The most events one read returns: the read's own bound, a page of a society's history.
EVENTS_READ_MAXIMUM = 256

#: A being's lines, newest first: what :meth:`SocietyRepository.snapshot_and_lines` asks, which
#: migration 0167's index of said events by speaker serves.
LINES_SAID_SQL = (
    "select tick,document from world_society_event "
    "where workspace_id=%s and society_id=%s and subject_id=%s and event_kind='said' "
    "order by tick desc, (document->>'order')::integer nulls last, event_id limit %s"
)

#: The first minute of the day a society of things' people start at, as its first input's people
#: frame states it (``day.start_minute_of_day``; only a first input carries one), and nothing else
#: of that input: null where it carries none.
PEOPLE_DAY_START_SQL = (
    "select document->'people'->'day'->'start_minute_of_day' as start from world_society_input "
    "where workspace_id=%s and society_id=%s and input_seq=1"
)


class InvalidEventCursor(ValueError):
    """A cursor that names no event of this society, or is not one this repository wrote."""

    code = "invalid_event_cursor"


class InvalidEventsWindow(InvalidEventCursor):
    """An events read whose window or kinds cannot be read: a window that ends before it begins,
    ``before`` with a window or ``after`` without one, a cursor outside the window, or a kind that
    is not an event kind's shape. Answered as an invalid cursor is, under its own code."""

    code = "invalid_events_window"


#: The most event kinds one read may name.
EVENT_KINDS_READ_MAXIMUM = 16

_EVENT_KIND = re.compile(r"[a-z][a-z_]{0,47}")


def event_cursor(event: dict[str, Any]) -> str:
    """Where a page of events ends, as the next page names it: the last event's tick, its order
    within the tick (empty where it states none) and its id. Opaque to a client."""
    order = event["document"].get("order")
    return f"{event['tick']}:{'' if order is None else order}:{event['event_id']}"


def _cursor_parts(cursor: str) -> tuple[int, int | None, uuid.UUID]:
    try:
        tick, order, event_id = cursor.split(":", 2)
        return int(tick), None if order == "" else int(order), uuid.UUID(event_id)
    except ValueError as exc:
        raise InvalidEventCursor("this is not a cursor an events read gave") from exc


def consumed_places(document: dict[str, Any]) -> dict[str, Any]:
    """Where inhabitants can go, as the input a society's current state consumed states it.

    Read from the one input the state names, already authorized with it, and copied rather than
    derived: the targets an inhabitant can be directed to, each object activity the input says no
    inhabitant can reach, the area the society walks, and the authored edit the input was composed
    from (``authored_state``: the version's edit and digest; null for an input that states none),
    so a reader knows which of the version's edits the current state has taken in. A queued input
    that no step has consumed yet is not described here, because nothing in the society has acted
    on it.
    """
    navigation = document["navigation"]
    living = document.get("living")
    place = living.get("place") if isinstance(living, dict) else None
    words = place.get("words") if isinstance(place, dict) else None
    return {
        "input_seq": document["input_seq"],
        "input_sha256": document["document_sha256"],
        "authored_state": (
            None
            if document.get("authored_state") is None
            else {
                "edit_seq": document["authored_state"]["edit_seq"],
                "delta_sha256": document["authored_state"]["delta_sha256"],
            }
        ),
        "availability": document["availability"],
        "unavailable_reason": document["unavailable_reason"],
        "walkable_area": navigation.get("walkable_area"),
        "clearance_mm": navigation["clearance_mm"],
        "targets": [dict(target) for target in document["targets"]],
        "unavailable_affordances": [
            dict(record) for record in document.get("unavailable_affordances", [])
        ],
        **(
            {
                "living_destinations": [
                    {
                        "destination_id": destination["destination_id"],
                        "use_class": destination["use_class"],
                        "label": destination["label"],
                        "indoors": destination["indoors"],
                    }
                    for destination in document["living"]["place"]["destinations"]
                    if destination["enabled"]
                ]
            }
            if "living" in document
            else {}
        ),
        # What is said of where a site world's people are and walk, keyed by the society ground
        # the catalog states its words for; a town's place states none, and serves none.
        **(
            {
                "place_words": {
                    "ground": _ground_key(navigation["profile"]),
                    "here": words["here"],
                    "around": words["around"],
                }
            }
            if isinstance(words, dict)
            else {}
        ),
    }


def _ground_key(navigation_profile: str) -> str:
    from exulanica.world.society_grounds import society_ground_for_navigation

    return society_ground_for_navigation(navigation_profile).key


class SocietyReads:
    """The reads of :class:`~exulanica.world.society_repository.SocietyRepository`."""

    def snapshot(self, version_id: uuid.UUID, *, places: bool = False) -> dict[str, Any]:
        """The current state; ``places`` adds, for a society with inputs, where inhabitants go."""
        snapshot, _lines, _left_out = self._read(version_id, places=places)
        return snapshot

    def stored_state(self, version_id: uuid.UUID) -> dict[str, Any] | None:
        """The society's state as stored, or None where the version holds no society: no input is
        authorized and nothing is composed, so a writer may read it under the workspace's lock
        without taking the asset read lock before its own write composes the society's next input.
        For a check that compares; a read that answers a person is :meth:`snapshot`."""
        row = self._row(version_id)
        return None if row is None else dict(row["state"])

    def snapshot_and_lines(
        self, version_id: uuid.UUID, subject_id: uuid.UUID, *, limit: int = 8
    ) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
        """The current state as :meth:`snapshot` answers it, the lines ``subject_id`` said lately
        (newest first, at most ``limit``, each said event's minute and document), and how many of
        those were left out. The lines are read first, through migration 0167's index of said
        events by speaker, and the inputs they were said under are announced with the state's own
        before the first authorization, so a transaction that goes on holding the asset read lock
        reads no stored bytes under it. A line whose input no longer authorizes is left out and
        counted, and the rest are answered: the state's own inputs decide whether the society may
        be read at all."""
        return self._read(version_id, lines_of=subject_id, limit=limit)

    def _read(
        self,
        version_id: uuid.UUID,
        *,
        places: bool = False,
        lines_of: uuid.UUID | None = None,
        limit: int = 8,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
        self._lock()
        row = self._row(version_id)
        if row is None:
            raise UnknownSociety("society is unavailable")
        said = (
            []
            if lines_of is None
            else self.connection.execute(
                LINES_SAID_SQL,
                (self.workspace_id, row["society_id"], lines_of, max(1, min(limit, 64))),
            ).fetchall()
        )
        current = None
        left_out: set[int] = set()
        if row["engine_version"] in INPUT_PROFILES:
            # A historical snapshot is not a current rights grant. Authorizer checks dependencies
            # of the current state plus queued input. Historical replay checks every input below.
            consumed, latest = row["state"]["input_seq"], self._chain(row)
            memories = self._memories(row)
            spoken = sorted(
                {value["document"]["input_seq"] for value in said} - {consumed, latest, *memories}
            )
            documents = self._inputs(row, [consumed, latest, *memories, *spoken])
            current = documents[consumed]
            with inputs_ahead(self.connection, documents.values()):
                self._authorize(current)
                if latest != consumed:
                    self._authorize(documents[latest])
                for sequence in memories:
                    self._authorize(documents[sequence])
                for sequence in spoken:
                    try:
                        self._authorize(documents[sequence])
                    except UnavailableSocietyInput:
                        left_out.add(sequence)
        snapshot = self._snapshot(row)
        if places and current is not None:
            snapshot["places"] = consumed_places(current)
        clock = self._served_clock(row)
        if clock is not None:
            snapshot["clock"] = clock
        lines = [
            {"tick": int(value["tick"]), "document": value["document"]}
            for value in said
            if value["document"]["input_seq"] not in left_out
        ]
        return snapshot, lines, len(said) - len(lines)

    def _served_clock(self, row: dict[str, Any]) -> dict[str, int] | None:
        """The clock served beside the state of a society of things whose state keeps none (a
        resident day keeps its own), from the day its first input's people frame starts
        (:func:`~exulanica.world.society.served_clock`); None for any other society."""
        engine = society_engine(row["engine_version"])
        if engine.state_family != "things" or "clock" in row["state"]:
            return None
        found = self.connection.execute(
            PEOPLE_DAY_START_SQL, (self.workspace_id, row["society_id"])
        ).fetchone()
        start = None if found is None else found["start"]
        if type(start) is not int:
            return None
        return served_clock(start, int(row["current_tick"]))

    def input_provenance(self, version_id: uuid.UUID, input_seq: int) -> dict[str, Any]:
        """One stored input's identity and the authored state it followed, never the input itself.

        Authorized as :meth:`events` authorizes the inputs it shows: the society's current rights
        first (:meth:`snapshot`), then this input's own. ``authored_state`` is the input's own
        record of the version's ``edit_seq`` and state digest (``delta_sha256``), which names the
        edit it followed in the version's history, or None for an input that records none. A
        society that takes no inputs, or a sequence its chain does not hold, is
        :class:`UnknownSociety`.
        """
        self.snapshot(version_id)
        row = self._row(version_id)
        if row is None or row["engine_version"] not in INPUT_PROFILES:
            raise UnknownSociety("society input is unavailable")
        if not 1 <= input_seq <= self._chain(row):
            raise UnknownSociety("society input is unavailable")
        document = self._inputs(row, [input_seq])[input_seq]
        self._authorize(document)
        authored = document.get("authored_state")
        return {
            "version_id": str(version_id),
            "society_id": str(row["society_id"]),
            "input_seq": input_seq,
            "input_sha256": document["document_sha256"],
            "input_profile": document["profile"],
            "authored_state": None
            if authored is None
            else {"edit_seq": authored["edit_seq"], "delta_sha256": authored["delta_sha256"]},
        }

    def events(self, version_id: uuid.UUID, *, limit: int = 256) -> tuple[dict[str, Any], ...]:
        return self.events_page(version_id, limit=limit)[0]

    def events_page(
        self,
        version_id: uuid.UUID,
        *,
        limit: int = EVENTS_READ_MAXIMUM,
        before: str | None = None,
        after: str | None = None,
        kinds: Sequence[str] | None = None,
        from_tick: int | None = None,
        to_tick: int | None = None,
    ) -> tuple[tuple[dict[str, Any], ...], str | None]:
        """A page of the society's events, and the cursor that reads on from it.

        Without a window the page is newest first: tick, newest first, then the order the engine
        gave events within a tick, then id. ``before`` is a cursor a previous page gave
        (:func:`event_cursor`); the page holds the events after it in that order. The cursor that
        comes back is None when no older event is left.

        With a window (``from_tick``, ``to_tick`` or both, inclusive; an open end is the first or
        the latest minute) the page holds the window's events oldest first, in minute, then order,
        then id, so a page can show the lines of the minutes it draws in the order they were said.
        ``after`` is the cursor a previous page of the same window gave; the cursor that comes back
        is None when the window holds no later event. ``kinds`` keeps the events of those kinds
        alone, with or without a window. The inputs of the events a page shows are authorized
        before it is answered, as the first page's are.
        """
        windowed = from_tick is not None or to_tick is not None
        if windowed and before is not None:
            raise InvalidEventsWindow("a window reads oldest first: continue it with after")
        if after is not None and not windowed:
            raise InvalidEventsWindow("after continues a window: name from_tick or to_tick")
        if from_tick is not None and to_tick is not None and to_tick < from_tick:
            raise InvalidEventsWindow("a window ends no earlier than it begins")
        if kinds is not None and (
            not kinds
            or len(kinds) > EVENT_KINDS_READ_MAXIMUM
            or any(not isinstance(k, str) or _EVENT_KIND.fullmatch(k) is None for k in kinds)
        ):
            raise InvalidEventsWindow(
                f"kinds names 1 to {EVENT_KINDS_READ_MAXIMUM} event kinds, each a lowercase key"
            )
        self.snapshot(version_id)  # Current authorization applies to event materialization too.
        row = self._row(version_id)
        bound = max(1, min(limit, EVENTS_READ_MAXIMUM))
        clauses = ""
        values: dict[str, Any] = {
            "workspace": self.workspace_id,
            "society": row["society_id"],
            "rows": bound + 1,
        }
        if kinds is not None:
            clauses += " and event_kind = any(%(kinds)s)"
            values["kinds"] = sorted(set(kinds))
        if from_tick is not None:
            clauses += " and tick>=%(from_tick)s"
            values["from_tick"] = from_tick
        if to_tick is not None:
            clauses += " and tick<=%(to_tick)s"
            values["to_tick"] = to_tick
        cursor = before if before is not None else after
        if cursor is not None:
            tick, order, event_id = _cursor_parts(cursor)
            named = self.connection.execute(
                "select 1 from world_society_event where workspace_id=%s and society_id=%s "
                "and event_id=%s and tick=%s "
                "and (document->>'order')::integer is not distinct from %s::integer",
                (self.workspace_id, row["society_id"], event_id, tick, order),
            ).fetchone()
            if named is None:
                raise InvalidEventCursor("the cursor names no event of this society")
            if windowed and not (
                (from_tick is None or tick >= from_tick) and (to_tick is None or tick <= to_tick)
            ):
                raise InvalidEventsWindow("the cursor names an event outside the window")
            values |= {"tick": tick, "order": order, "event": event_id}
            # Within a minute both directions read order, then id, ascending; the minutes run
            # newest first without a window and oldest first with one.
            clauses += (
                f" and (tick{'>' if windowed else '<'}%(tick)s or (tick=%(tick)s and ("
                "(%(order)s::integer is not null and ((document->>'order')::integer>%(order)s "
                "or document->>'order' is null or ((document->>'order')::integer=%(order)s "
                "and event_id>%(event)s))) "
                "or (%(order)s::integer is null and document->>'order' is null "
                "and event_id>%(event)s))))"
            )
        rows = self.connection.execute(
            "select "
            "event_id,tick,event_kind,subject_id,object_id,place_id,document,document_sha256,"
            "recorded_at from world_society_event "
            "where workspace_id=%(workspace)s and society_id=%(society)s"
            + clauses
            + f" order by tick {'asc' if windowed else 'desc'}, "
            "(document->>'order')::integer nulls last,event_id "
            "limit %(rows)s",
            values,
        ).fetchall()
        page, more = rows[:bound], len(rows) > bound
        if row["engine_version"] in INPUT_PROFILES:
            shown = {value["document"]["input_seq"] for value in page}
            documents = self._inputs(row, shown)
            for sequence in sorted(shown):
                self._authorize(documents[sequence])
        events = tuple(dict(value) for value in page)
        return events, event_cursor(events[-1]) if more else None
