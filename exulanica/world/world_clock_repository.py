"""A world version's clock in the database: its transition, each society minute, each sealed
traffic minute and the read a client is shown.

A version without a row keeps legacy timing (:mod:`exulanica.world.world_clock`). The one-way
transition writes the row and its first receipt; from then on three writers move it forward. Each
holds the workspace edit lock before it locks the clock row, and nothing locks the clock row
without it, so none waits for another in a cycle. The transition, a seal and a hold lock the
version row and then the clock row; a society minute locks its society row and then the clock
row, and touches the version row only as the share its foreign keys take:

- the society's own minute (:meth:`WorldClockRepository.before_minute` and
  :meth:`~WorldClockRepository.after_minute`, called by the society repository inside the minute's
  transaction, which already holds the edit lock): refuse a minute past the lead, record the
  minute's crossing occupancy and move the society's head;
- the traffic follower's seal (:meth:`~WorldClockRepository.seal_minute`): one sealed traffic minute
  per world tick, exactly once;
- traffic becoming blocked or unavailable (:meth:`~WorldClockRepository.hold_traffic`).

The database refuses a society minute past the lead and a traffic minute that reads occupancy not
yet committed, whatever the host does (migration 0125).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.db.session import set_workspace
from exulanica.world.decision_roles import DecisionRole
from exulanica.world.society_controls import effective_interval_ms, utc
from exulanica.world.society_engines import society_engine
from exulanica.world.traffic_signal_repository import SignalChoiceRefused, TrafficSignalRepository
from exulanica.world.workspace_lock import lock_workspace
from exulanica.world.world_clock import (
    CLOCK_PROFILE,
    COUPLED,
    EVENT_PROFILE,
    LEGACY,
    ClockRefused,
    Era,
    clock_profile,
    crossing_edges,
    lead_room,
    minute_occupancy,
    timeline_origin,
)

__all__ = [
    "MINUTE_PROFILE",
    "ClockLeadExhausted",
    "RoadsFacts",
    "WorldClockRepository",
]

#: A sealed coupled traffic minute's document.
MINUTE_PROFILE: Final = "exulanica.world-traffic-minute/v1"


class ClockLeadExhausted(ClockRefused):
    """A society minute past the lead a coupled world keeps over its sealed traffic: retry once
    traffic has sealed the minute it waits for."""

    def __init__(self, detail: str) -> None:
        super().__init__("clock_lead_exhausted", detail)

    def __reduce__(self) -> tuple[Any, ...]:
        return (type(self), (self.detail,))


@dataclass(frozen=True, slots=True)
class RoadsFacts:
    """What a transition needs to know of a version's roads, gathered before its transaction:
    the roads' version and traffic input digest, and each band's ``society_crossing_id`` by the
    crossing record identity the band keeps."""

    roads_version: str
    input_sha256: str
    bands: Mapping[str, str]


def _sealed(document: dict[str, Any]) -> dict[str, Any]:
    document = dict(document)
    document.pop("document_sha256", None)
    document["document_sha256"] = hashlib.sha256(canonical_json(document)).hexdigest()
    return document


def era_of(row: Mapping[str, Any]) -> Era:
    """The era a clock row states."""
    return Era(
        era=row["era"],
        start_tick=row["era_start_tick"],
        seconds_per_tick=row["seconds_per_tick"],
        timeline_origin_second=row["timeline_origin_second"],
    )


def _crossing_identities(place: Mapping[str, Any]) -> list[str]:
    """The crossing records a living place walks, by record identity."""
    return sorted({crossing["crossing_id"] for crossing in place.get("crossings", ())})


class WorldClockRepository:
    """One world's clocks, through a workspace-scoped connection."""

    def __init__(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.world_id = world_id
        connection.row_factory = dict_row
        set_workspace(connection, workspace_id)

    # -- reads --------------------------------------------------------------------------------

    def row(self, version_id: uuid.UUID, *, lock: bool = False) -> dict[str, Any] | None:
        """The version's clock row, or None while it keeps legacy timing."""
        return self.connection.execute(
            "select * from world_clock where workspace_id=%s and world_id=%s and version_id=%s"
            + (" for update" if lock else ""),
            (self.workspace_id, self.world_id, version_id),
        ).fetchone()

    def _now(self) -> dt.datetime:
        return self.connection.execute("select clock_timestamp() as now").fetchone()["now"]

    def _society(self, version_id: uuid.UUID) -> dict[str, Any] | None:
        return self.connection.execute(
            "select society_id,engine_version,current_tick,state_sha256,tick_seconds "
            "from world_society where workspace_id=%s and world_id=%s and version_id=%s",
            (self.workspace_id, self.world_id, version_id),
        ).fetchone()

    def _control(self, society_id: uuid.UUID) -> dict[str, Any] | None:
        return self.connection.execute(
            "select revision,mode,speed,base_tick_interval_ms,lease_token,lease_expires_at "
            "from world_society_control where workspace_id=%s and society_id=%s",
            (self.workspace_id, society_id),
        ).fetchone()

    def read(self, version_id: uuid.UUID) -> dict[str, Any]:
        """``exulanica.world-clock/v1``: the version's clock as a client is shown it.

        A version without a row answers its legacy timing, revision 0. Reading takes no lock.
        """
        with self.connection.transaction():
            if (
                self.connection.execute(
                    "select 1 from world_alternate_version where workspace_id=%s and world_id=%s "
                    "and version_id=%s",
                    (self.workspace_id, self.world_id, version_id),
                ).fetchone()
                is None
            ):
                raise ClockRefused("unknown_reference", "the world holds no such version")
            clock = self.row(version_id)
            society = self._society(version_id)
            control = None if society is None else self._control(society["society_id"])
            last = self.connection.execute(
                "select coalesce(max(event_seq),0) as seq from world_clock_event "
                "where workspace_id=%s and world_id=%s and version_id=%s",
                (self.workspace_id, self.world_id, version_id),
            ).fetchone()["seq"]
            now = self._now()
        return clock_document(
            self.world_id, version_id, clock, society, control, last_event_seq=last, now=now
        )

    def events(self, version_id: uuid.UUID, *, limit: int = 64) -> list[dict[str, Any]]:
        """The version's clock receipts, newest first, each held to its digest."""
        rows = self.connection.execute(
            "select document,document_sha256 from world_clock_event where workspace_id=%s "
            "and world_id=%s and version_id=%s order by event_seq desc limit %s",
            (self.workspace_id, self.world_id, version_id, max(1, min(limit, 128))),
        ).fetchall()
        for row in rows:
            if _sealed(row["document"])["document_sha256"] != row["document_sha256"]:
                raise ValueError("world clock receipt digest mismatch")
        return [row["document"] for row in rows]

    # -- locks and receipts --------------------------------------------------------------------

    def _lock_edits(self) -> None:
        lock_workspace(self.connection, self.workspace_id)

    def _lock_version(self, version_id: uuid.UUID) -> None:
        if (
            self.connection.execute(
                "select version_id from world_alternate_version where workspace_id=%s "
                "and world_id=%s and version_id=%s for update",
                (self.workspace_id, self.world_id, version_id),
            ).fetchone()
            is None
        ):
            raise ClockRefused("unknown_reference", "the world holds no such version")

    def record_event(
        self, version_id: uuid.UUID, kind: str, details: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Append one receipt. The caller holds the version row, which serializes the sequence."""
        sequence = self.connection.execute(
            "select coalesce(max(event_seq),0)+1 as seq from world_clock_event "
            "where workspace_id=%s and world_id=%s and version_id=%s",
            (self.workspace_id, self.world_id, version_id),
        ).fetchone()["seq"]
        document = _sealed(
            {
                "profile": EVENT_PROFILE,
                "world_id": self.world_id,
                "version_id": str(version_id),
                "event_seq": sequence,
                "kind": kind,
                "recorded_at": utc(self._now()),
                **details,
            }
        )
        self.connection.execute(
            "insert into world_clock_event(workspace_id,world_id,version_id,event_seq,kind,"
            "document,document_sha256) values(%s,%s,%s,%s,%s,%s,%s)",
            (
                self.workspace_id,
                self.world_id,
                version_id,
                sequence,
                kind,
                Jsonb(document),
                document["document_sha256"],
            ),
        )
        return document

    # -- the transition -------------------------------------------------------------------------

    def transition_refusal(
        self, version_id: uuid.UUID, *, roads: RoadsFacts | None
    ) -> ClockRefused | None:
        """What the transition would refuse for the version's state now, in the transition's own
        order, or None. ``roads`` is None when the world states no roads.

        It reads and takes no lock, so a read may ask it; :meth:`transition` asks it in its own
        transaction, after taking its locks, and raises what it answers. The checks that do not
        read the roads come first: asked with None, it answers every refusal but the crossings'.
        """
        if self.row(version_id) is not None:
            return ClockRefused("clock_already_coupled", "this version's clock is coupled")
        society = self.connection.execute(
            "select * from world_society where workspace_id=%s and world_id=%s and version_id=%s",
            (self.workspace_id, self.world_id, version_id),
        ).fetchone()
        if society is None:
            return ClockRefused("clock_requires_society", "this version holds no society")
        engine = society_engine(society["engine_version"])
        if not engine.playback:
            return ClockRefused(
                "clock_society_not_playable",
                f"{society['engine_version']} is advanced by hand only",
            )
        seconds_per_tick = clock_profile(COUPLED).seconds_per_tick
        if society["tick_seconds"] != seconds_per_tick:
            return ClockRefused(
                "clock_tick_seconds_unsupported",
                f"a tick of {society['tick_seconds']} s is not the clock's minute",
            )
        control = self._control(society["society_id"])
        if control is not None and (
            control["mode"] != "paused"
            or (
                control["lease_expires_at"] is not None
                and control["lease_expires_at"] > self._now()
            )
        ):
            return ClockRefused("clock_transition_requires_pause", "pause the world's people first")
        if roads is None:
            return None
        if engine.state_family != "living":
            return ClockRefused(
                "clock_crossings_unsupported",
                f"{society['engine_version']} records no crossing its people make",
            )
        try:
            identities = _crossing_identities(self._current_place(society))
        except ClockRefused as refused:
            return refused
        unmapped = [identity for identity in identities if identity not in roads.bands]
        if unmapped:
            return ClockRefused(
                "clock_crossings_unmapped",
                "crossings no band of the roads carries: " + ", ".join(unmapped[:8]),
            )
        return None

    def transition(
        self,
        version_id: uuid.UUID,
        *,
        actor: uuid.UUID,
        base_revision: int,
        profile: str,
        roads: RoadsFacts | None,
    ) -> dict[str, Any]:
        """Couple the version's clock, from its society's current tick, or refuse by name.

        ``roads`` is None when the world states no roads. Nothing is written on a refusal.
        """
        if type(base_revision) is not int or base_revision < 0:
            raise ClockRefused("invalid_clock_request", "base_revision is a nonnegative integer")
        target = clock_profile(profile)
        if target.key != COUPLED:
            raise ClockRefused(
                "clock_transition_unsupported", "a clock is coupled, never uncoupled"
            )
        with self.connection.transaction():
            self._lock_edits()
            self._lock_version(version_id)
            current = self.row(version_id, lock=True)
            if base_revision != (0 if current is None else current["revision"]):
                raise ClockRefused("stale_clock_revision", "the clock changed; read it again")
            society = self.connection.execute(
                "select * from world_society where workspace_id=%s and world_id=%s "
                "and version_id=%s for update",
                (self.workspace_id, self.world_id, version_id),
            ).fetchone()
            refusal = self.transition_refusal(version_id, roads=roads)
            if refusal is not None:
                raise refusal
            now = self._now()
            crossings = (
                0 if roads is None else len(_crossing_identities(self._current_place(society)))
            )
            latest = self.connection.execute(
                "select max(end_second) as last from world_traffic_signal_segment "
                "where workspace_id=%s and world_id=%s and version_id=%s",
                (self.workspace_id, self.world_id, version_id),
            ).fetchone()["last"]
            now_second = int(now.timestamp())
            origin = timeline_origin(now_second, latest)
            era = Era(1, society["current_tick"], target.seconds_per_tick, origin)
            receipt = self.record_event(
                version_id,
                "transitioned",
                {
                    "from_profile": clock_profile(LEGACY).profile,
                    "to_profile": target.profile,
                    "era": era.era,
                    "revision": base_revision + 1,
                    "actor_id": str(actor),
                    "society_id": str(society["society_id"]),
                    "start_tick": era.start_tick,
                    "start_world_second": era.start_world_second,
                    "timeline_origin_second": origin,
                    "lead_ticks": target.lead_ticks,
                    "roads_version": None if roads is None else roads.roads_version,
                    "input_sha256": None if roads is None else roads.input_sha256,
                    "crossings": crossings,
                    "society_state_sha256": society["state_sha256"],
                },
            )
            self.connection.execute(
                "insert into world_clock(workspace_id,world_id,version_id,society_id,revision,"
                "profile,era,era_start_tick,seconds_per_tick,lead_ticks,timeline_origin_second,"
                "roads_version,input_sha256,society_tick,society_state_sha256,"
                "traffic_sealed_through_tick,traffic_state,presented_through_tick,presented_at,"
                "last_event_seq,changed_by) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                "%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    self.world_id,
                    version_id,
                    society["society_id"],
                    base_revision + 1,
                    target.profile,
                    era.era,
                    era.start_tick,
                    era.seconds_per_tick,
                    target.lead_ticks,
                    origin,
                    None if roads is None else roads.roads_version,
                    None if roads is None else roads.input_sha256,
                    society["current_tick"],
                    society["state_sha256"],
                    None if roads is None else era.start_tick,
                    None if roads is None else "running",
                    era.start_tick,
                    now,
                    receipt["event_seq"],
                    actor,
                ),
            )
        return self.read(version_id)

    def _current_place(self, society: Mapping[str, Any]) -> dict[str, Any]:
        """The living place the society's latest input states; its crossings are record data."""
        row = self.connection.execute(
            "select document->'living'->'place' as place from world_society_input "
            "where workspace_id=%s and society_id=%s order by input_seq desc limit 1",
            (self.workspace_id, society["society_id"]),
        ).fetchone()
        if row is None or not isinstance(row["place"], dict):
            raise ClockRefused(
                "clock_crossings_unsupported", "the society's input states no living place"
            )
        return row["place"]

    def check_revision(self, version_id: uuid.UUID, base_clock_revision: int | None) -> None:
        """Refuse a request made against another clock revision (0 while legacy). Called under the
        workspace edit lock, in the transaction of the change it pins."""
        if base_clock_revision is None:
            return
        row = self.row(version_id)
        if base_clock_revision != (0 if row is None else row["revision"]):
            raise ClockRefused("stale_clock_revision", "the clock changed; read it again")

    # -- the society's minute --------------------------------------------------------------------

    def before_minute(self, version_id: uuid.UUID, society_tick: int) -> dict[str, Any] | None:
        """Refuse a society minute past the lead; answer the clock row the minute runs under.

        Called inside the minute's transaction, which already holds the edit lock. A legacy
        version answers None and the minute runs as it always has.
        """
        clock = self.row(version_id, lock=True)
        if clock is None:
            return None
        if clock["traffic_state"] in ("running", "blocked") and not lead_room(
            clock["lead_ticks"], society_tick, clock["traffic_sealed_through_tick"]
        ):
            raise ClockLeadExhausted(
                f"the society is {society_tick - clock['traffic_sealed_through_tick']} minutes "
                "ahead of sealed traffic; it waits for the next sealed minute"
            )
        return clock

    def after_minute(
        self,
        clock: Mapping[str, Any],
        *,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        previous_state_sha256: str,
        state_sha256: str,
        events: Sequence[Mapping[str, Any]],
        places: Sequence[Mapping[str, Any]] | None,
    ) -> None:
        """Record a committed minute: its crossing occupancy, when the society records crossings,
        and the society's new head. ``places`` are the place documents a living minute read; None
        for an engine that records no crossings."""
        if places is not None:
            document = minute_occupancy(
                society_id=str(clock["society_id"]),
                era=clock["era"],
                before=before,
                after=after,
                events=events,
                crossings_by_edge=crossing_edges(places),
                place_sha256=places[-1]["document_sha256"],
                previous_state_sha256=previous_state_sha256,
                state_sha256=state_sha256,
            )
            self.connection.execute(
                "insert into world_crossing_occupancy(workspace_id,world_id,version_id,society_id,"
                "era,tick,previous_state_sha256,state_sha256,document,document_sha256) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    self.world_id,
                    clock["version_id"],
                    clock["society_id"],
                    clock["era"],
                    after["tick"],
                    document["previous_state_sha256"],
                    document["state_sha256"],
                    Jsonb(document),
                    document["document_sha256"],
                ),
            )
        shown = clock["traffic_state"] in (None, "unavailable")
        self.connection.execute(
            "update world_clock set society_tick=%s,society_state_sha256=%s"
            + (",presented_through_tick=%s,presented_at=clock_timestamp()" if shown else "")
            + " where workspace_id=%s and world_id=%s and version_id=%s",
            (
                after["tick"],
                state_sha256,
                *((after["tick"],) if shown else ()),
                self.workspace_id,
                self.world_id,
                clock["version_id"],
            ),
        )

    # -- traffic ---------------------------------------------------------------------------------

    def followed(self) -> list[dict[str, Any]]:
        """This world's coupled versions whose traffic a follower seals."""
        return self.connection.execute(
            "select * from world_clock where workspace_id=%s and world_id=%s "
            "and traffic_state='running' order by version_id",
            (self.workspace_id, self.world_id),
        ).fetchall()

    def occupancy(
        self, clock: Mapping[str, Any], *, first_tick: int, through_tick: int
    ) -> list[dict[str, Any]]:
        """The era's occupancy documents from ``first_tick`` through ``through_tick``, each held
        to its digest and to the society transition it was read from; a gap is refused."""
        rows = self.connection.execute(
            "select o.tick,o.document,o.document_sha256,t.previous_state_sha256 as previous,"
            "t.state_sha256 as state from world_crossing_occupancy o "
            "join world_society_transition t "
            "using (workspace_id,society_id,tick) where o.workspace_id=%s and o.world_id=%s "
            "and o.society_id=%s and o.era=%s and o.tick between %s and %s order by o.tick",
            (
                self.workspace_id,
                self.world_id,
                clock["society_id"],
                clock["era"],
                first_tick,
                through_tick,
            ),
        ).fetchall()
        if [row["tick"] for row in rows] != list(range(first_tick, through_tick + 1)):
            raise ClockRefused(
                "crossing_occupancy_missing",
                f"occupancy of ticks {first_tick} to {through_tick} is not all committed",
            )
        for row in rows:
            document = row["document"]
            if (
                _sealed(document)["document_sha256"] != row["document_sha256"]
                or document["previous_state_sha256"] != row["previous"]
                or document["state_sha256"] != row["state"]
            ):
                raise ClockRefused(
                    "crossing_occupancy_mismatch",
                    f"the occupancy of tick {row['tick']} is not what its minute committed",
                )
        return [row["document"] for row in rows]

    def minutes(self, clock: Mapping[str, Any], episode: int) -> list[dict[str, Any]]:
        """The era's sealed minutes of one traffic episode, in order."""
        return self.connection.execute(
            "select * from world_clock_traffic_minute where workspace_id=%s and world_id=%s "
            "and version_id=%s and era=%s and episode=%s order by segment",
            (self.workspace_id, self.world_id, clock["version_id"], clock["era"], episode),
        ).fetchall()

    def minute(self, clock: Mapping[str, Any], world_tick: int) -> dict[str, Any] | None:
        return self.connection.execute(
            "select * from world_clock_traffic_minute where workspace_id=%s and world_id=%s "
            "and version_id=%s and era=%s and world_tick=%s",
            (self.workspace_id, self.world_id, clock["version_id"], clock["era"], world_tick),
        ).fetchone()

    def seal_minute(
        self,
        version_id: uuid.UUID,
        *,
        era: int,
        world_tick: int,
        occupancy_through_tick: int,
        feed_sha256: str,
        frames_sha256: str,
        continuation: Mapping[str, Any],
        selected_generations: Mapping[str, int],
        role: DecisionRole,
    ) -> dict[str, Any]:
        """Seal traffic's minute ``world_tick`` of the era, once, and move the clock to it.

        The minute's reserved signal points are finished here, in the seal's own transaction, as a
        legacy segment's are (:meth:`TrafficSignalRepository.finalize_requests`). An exact retry
        answers the minute already sealed; a different one is refused,
        ``traffic_minute_sealed_differently``: what a viewer was shown does not change.
        """
        with self.connection.transaction():
            self._lock_edits()
            self._lock_version(version_id)
            clock = self.row(version_id, lock=True)
            if clock is None or clock["era"] != era or clock["traffic_state"] is None:
                raise ClockRefused("clock_era_changed", "the clock is not the era being sealed")
            timeline = era_of(clock)
            start = timeline.traffic_second(timeline.world_second_of_tick(world_tick - 1))
            episode, local = divmod(start, 1200)
            signals = TrafficSignalRepository(
                self.connection, self.workspace_id, self.world_id, version_id
            )
            try:
                signals.check_generations(start, selected_generations)
                decisions = signals.finalize_requests(
                    role,
                    episode=episode,
                    absolute_start=start,
                    absolute_end=start + 60,
                    selected_generations=selected_generations,
                    signal_choices=continuation["signal_choices"],
                )
            except SignalChoiceRefused as error:
                raise ClockRefused(error.code, "the minute's signal points changed") from error
            existing = self.minute(clock, world_tick)
            document = _sealed(
                {
                    "profile": MINUTE_PROFILE,
                    "world_id": self.world_id,
                    "version_id": str(version_id),
                    "era": era,
                    "world_tick": world_tick,
                    "roads_version": clock["roads_version"],
                    "input_sha256": clock["input_sha256"],
                    "episode": episode,
                    "segment": local // 60,
                    "start_second": start,
                    "occupancy_through_tick": occupancy_through_tick,
                    "feed_sha256": feed_sha256,
                    "decisions_sha256": decisions["decisions_sha256"],
                    "frames_sha256": frames_sha256,
                    "continuation_sha256": continuation["document_sha256"],
                    "signal_choices": continuation["signal_choices"],
                    "signal_cursors": continuation["signal_cursors"],
                    "initial_signal_cursors": continuation["initial_signal_cursors"],
                    "choice_seq": decisions["choice_seq"],
                    "active_second": decisions["active_second"],
                    "previous_sha256": None
                    if world_tick == clock["era_start_tick"] + 1
                    else (self.minute(clock, world_tick - 1) or {}).get("document_sha256"),
                }
            )
            if existing is not None:
                if existing["document_sha256"] != document["document_sha256"]:
                    raise ClockRefused(
                        "traffic_minute_sealed_differently",
                        f"traffic minute {world_tick} was sealed with other contents",
                    )
                return existing
            if clock["traffic_state"] != "running":
                raise ClockRefused(
                    "traffic_not_running", f"traffic is {clock['traffic_state']} in this era"
                )
            if world_tick != clock["traffic_sealed_through_tick"] + 1:
                raise ClockRefused(
                    "traffic_minute_out_of_order",
                    f"minute {world_tick} does not follow sealed minute "
                    f"{clock['traffic_sealed_through_tick']}",
                )
            row = self.connection.execute(
                "insert into world_clock_traffic_minute(workspace_id,world_id,version_id,era,"
                "world_tick,roads_version,input_sha256,episode,segment,start_second,end_second,"
                "occupancy_through_tick,choice_seq,active_second,previous_sha256,feed_sha256,"
                "decisions_sha256,frames_sha256,continuation_sha256,document,document_sha256) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "returning *",
                (
                    self.workspace_id,
                    self.world_id,
                    version_id,
                    era,
                    world_tick,
                    clock["roads_version"],
                    clock["input_sha256"],
                    episode,
                    local // 60,
                    start,
                    start + 60,
                    occupancy_through_tick,
                    decisions["choice_seq"],
                    decisions["active_second"],
                    document["previous_sha256"],
                    feed_sha256,
                    decisions["decisions_sha256"],
                    frames_sha256,
                    continuation["document_sha256"],
                    Jsonb(document),
                    document["document_sha256"],
                ),
            ).fetchone()
            self.connection.execute(
                "update world_clock set traffic_sealed_through_tick=%s,presented_through_tick=%s,"
                "presented_at=clock_timestamp() where workspace_id=%s and world_id=%s "
                "and version_id=%s",
                (world_tick, world_tick, self.workspace_id, self.world_id, version_id),
            )
            return row

    def hold_traffic(self, version_id: uuid.UUID, *, era: int, state: str, code: str) -> None:
        """Mark the era's traffic ``blocked`` (a fault in what it reads; the society waits) or
        ``unavailable`` (a lasting refusal; the society goes on without it), with a receipt."""
        if state not in ("blocked", "unavailable"):
            raise ValueError("traffic is held blocked or unavailable")
        with self.connection.transaction():
            self._lock_edits()
            self._lock_version(version_id)
            clock = self.row(version_id, lock=True)
            if clock is None or clock["era"] != era or clock["traffic_state"] in (None, state):
                return
            if clock["traffic_state"] == "unavailable":
                return
            shown = (
                clock["society_tick"]
                if state == "unavailable"
                else clock["traffic_sealed_through_tick"]
            )
            receipt = self.record_event(
                version_id,
                "traffic_blocked" if state == "blocked" else "traffic_unavailable",
                {
                    "era": era,
                    "code": code,
                    "sealed_through_tick": clock["traffic_sealed_through_tick"],
                },
            )
            self.connection.execute(
                "update world_clock set traffic_state=%s,traffic_code=%s,presented_through_tick=%s,"
                "presented_at=clock_timestamp(),last_event_seq=%s where workspace_id=%s "
                "and world_id=%s and version_id=%s",
                (
                    state,
                    code,
                    shown,
                    receipt["event_seq"],
                    self.workspace_id,
                    self.world_id,
                    version_id,
                ),
            )


def clock_document(
    world_id: str,
    version_id: uuid.UUID,
    clock: Mapping[str, Any] | None,
    society: Mapping[str, Any] | None,
    control: Mapping[str, Any] | None,
    *,
    last_event_seq: int,
    now: dt.datetime,
) -> dict[str, Any]:
    """The clock read, from the rows it is made of."""
    profile = clock_profile(COUPLED if clock is not None else LEGACY)
    mode = "paused" if control is None else control["mode"]
    speed = 1 if control is None else control["speed"]
    head = None
    if society is not None:
        head = {
            "society_id": str(society["society_id"]),
            "engine": society["engine_version"],
            "tick": society["current_tick"],
            "state_sha256": society["state_sha256"],
            "mode": mode,
            "speed": speed,
            "control_revision": 0 if control is None else control["revision"],
            "tick_interval_ms": None
            if control is None
            else effective_interval_ms(control["base_tick_interval_ms"], speed),
        }
    document: dict[str, Any] = {
        "profile": CLOCK_PROFILE,
        "world_id": world_id,
        "version_id": str(version_id),
        "clock_profile": profile.profile,
        "revision": 0 if clock is None else clock["revision"],
        "era": 0 if clock is None else clock["era"],
        "timebases": {
            "society": "tick",
            "traffic": "unix" if clock is None else "world",
            "flight": "unix" if clock is None else "world",
        },
        "crossings_fed": clock is not None and clock["roads_version"] is not None,
        "lead_ticks": profile.lead_ticks,
        "catchup_ticks_maximum": profile.catchup_ticks_maximum,
        "society": head,
        "era_mapping": None,
        "traffic": None,
        "state": mode,
        "presented_through_tick": None,
        "presented_through_world_second": None,
        "presented_at": None,
        "last_event_seq": last_event_seq,
        "answered_at": utc(now),
    }
    if clock is None:
        return document
    era = era_of(clock)
    document["era_mapping"] = {
        "start_tick": era.start_tick,
        "start_world_second": era.start_world_second,
        "seconds_per_tick": era.seconds_per_tick,
        "timeline_origin_second": era.timeline_origin_second,
        "flight_steps_per_second": 10,
    }
    document["presented_through_tick"] = clock["presented_through_tick"]
    document["presented_through_world_second"] = era.world_second_of_tick(
        clock["presented_through_tick"]
    )
    document["presented_at"] = utc(clock["presented_at"])
    state = mode
    if clock["roads_version"] is not None:
        traffic_state = clock["traffic_state"]
        if traffic_state == "running":
            traffic_state = (
                "following"
                if clock["traffic_sealed_through_tick"] < clock["society_tick"] - 1
                else "waiting_for_society"
            )
        document["traffic"] = {
            "state": traffic_state,
            "code": clock["traffic_code"],
            "roads_version": clock["roads_version"],
            "input_sha256": clock["input_sha256"],
            "sealed_through_tick": clock["traffic_sealed_through_tick"],
            "sealed_through_second": era.traffic_second(
                era.world_second_of_tick(clock["traffic_sealed_through_tick"])
            ),
        }
        if traffic_state == "blocked":
            state = "blocked"
        elif (
            mode == "playing"
            and traffic_state != "unavailable"
            and not lead_room(
                clock["lead_ticks"], clock["society_tick"], clock["traffic_sealed_through_tick"]
            )
        ):
            state = "waiting"
    document["state"] = state
    return document
