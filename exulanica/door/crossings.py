"""Crossings: the visitors a bridge sends into a society of things and calls back, as the door keeps
them and hands them to the society's minutes.

A grant that admits visitors names the world version they arrive in (``Scope.version_id``) and,
optionally, the gate they come through (``Scope.gate``, a placed thing's id). Its bridge asks for an
arrival under an id of its own, a random version 4 UUID (a departure's id is one the door derives,
version 5, so the two never meet), with what the person in its game is (the game's own type, from
the grant's admitted kinds and its mapping), the look they arrive in (a key the mapping offers for
that type, naming a look the thing library ships, held at intake to the library and the kind's
body plan by :func:`exulanica.world.thing_looks.check_crossing_look`) and what they carry in (game
items the mapping lets travel in, one thing each). A grant takes at most
:data:`ARRIVALS_PER_HOUR_MAXIMUM` arrivals in any hour, refused ones included. The door writes the
arrival as the society of things reads it (:func:`exulanica.world.crossings.check_arrival`): the
visitor's id and each carried thing's, derived from the grant and the bridge's arrival id so a
resent arrival is the same one; the kind each becomes, by the shipped library's digest; the
visitor's origin (class ``crossed``: the program that sent it, under its grant), whose licence and
distribution are the shipped look's own, never the mapping's words about it; and the digest of the
translation manifest that says what came across (:mod:`exulanica.door.manifest`), kept in the
workspace by its digest. Departures are written for a visitor the world's owner sends home
(``sent_away``) and for every visitor of a grant that ends (``grant_ended``). A bridge whose player
left says so (``gone``): the visitor is not asked again, so its kind's quiet minutes pass and the
society sends it home (``decider_lost``).

The society's next minute takes the crossings no minute has consumed, in the order the door wrote
them, on its own connection under the society's lock (:class:`DoorCrossings`, THINGS's
``CrossingStream``), and binds each once to the event it recorded: an arrival arrived or was
refused, a departure departed, found nobody of that id here or was refused. An arrival that arrived
records its visitor's look in the same transaction
(:func:`exulanica.world.thing_looks.record_crossing_look`), never anything the society reads.
Replay reads the bound crossings back by minute, so a society with visitors replays with no bridge
running.

A visitor is present from its arrival (bound as arrived, or not yet taken) until a departure of it
is written or the society records it leaving by its own rules. Every query here runs on a
connection scoped to the grant's workspace.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import sha256_of_canonical
from exulanica.door.channel import ChannelRefused
from exulanica.door.grants import Grant, visitors_society
from exulanica.door.manifest import arrival_manifest
from exulanica.world.crossings import (
    ARRIVAL_PROFILE,
    DEPARTURE_PROFILE,
    BoundCrossing,
    ConsumedCrossing,
    Crossing,
    check_arrival,
    check_departure,
)
from exulanica.world.errors import InvalidThingPlacement
from exulanica.world.placed_things import named_kind, shipped_kind
from exulanica.world.thing_library import shipped_looks
from exulanica.world.thing_looks import (
    ThingLookRefused,
    check_crossing_look,
    record_crossing_look,
)

__all__ = [
    "ARRIVALS_PER_HOUR_MAXIMUM",
    "CARRIED_UNITS_MAXIMUM",
    "DoorCrossings",
    "Visits",
    "departure_id",
]

#: The most things one arrival carries in, every unit counted: the society's own bound.
CARRIED_UNITS_MAXIMUM: Final = 16
#: The deciders the world gives a visitor it decides for.
WORLD_DECIDERS: Final = ("routine", "model", "person")
#: The most arrivals one grant writes in any hour, refused ones included: an arrival the minute
#: refuses frees its place at once, so without this a bridge could write one every minute for good.
ARRIVALS_PER_HOUR_MAXIMUM: Final = 60
#: The namespace of the ids the door derives: a visitor's and its carried things' from the grant and
#: the bridge's arrival id, a departure's from the grant, the visitor and why it leaves.
_IDS: Final = uuid.UUID("8f1d6a52-3c47-5e09-b4a8-1e7c2d90f6b3")


def _id(grant_id: uuid.UUID, *parts: object) -> uuid.UUID:
    return uuid.uuid5(_IDS, ":".join([str(grant_id), *(str(part) for part in parts)]))


def _look_reference(named: str | Mapping[str, Any]) -> Mapping[str, Any]:
    """A mapping's look as the thing library's reference: a ``bridge-mapping/v2`` look is one
    already; a ``bridge-mapping/v1`` look, ``sha256:<digest>``, is the shipped look with that
    digest, or a reference the library's check refuses (``look_not_shipped``) when it ships
    none."""
    if not isinstance(named, str):
        return named
    digest = named.removeprefix("sha256:")
    shipped = next((look for look in shipped_looks().values() if look.sha256 == digest), None)
    if shipped is None:
        return {"look": "unknown", "version": 1, "sha256": digest}
    return {"look": shipped.look, "version": shipped.version, "sha256": shipped.sha256}


def _shipped_kind(named: Mapping[str, Any]) -> Any:
    """The shipped kind a pinned mapping names, or a refusal by name: a deployment may pin a
    mapping naming a kind this release does not ship."""
    try:
        return named_kind(named["key"], named["version"])
    except InvalidThingPlacement as exc:
        raise ChannelRefused("kind_not_shipped", 422, str(exc)) from exc


def _world_may_decide(kind: Any) -> bool:
    """Whether a decider the world gives (the routine, a model or a person) may decide for a thing
    of ``kind``, as its shipped kind's allowed deciders say."""
    deciders = shipped_kind(kind).document["deciders"]
    return deciders is not None and bool(set(deciders["allowed"]) & set(WORLD_DECIDERS))


def departure_id(grant_id: uuid.UUID, thing_id: uuid.UUID, reason: str) -> uuid.UUID:
    """The one departure the door writes for ``thing_id`` for ``reason``: writing it twice is
    writing it once."""
    return _id(grant_id, "departure", thing_id, reason)


class DoorCrossings:
    """The door's side of THINGS's crossing port, read and written on the minute's connection."""

    def pending(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        society_id: uuid.UUID,
        tick: int,
        *,
        limit: int | None = None,
    ) -> Sequence[Crossing]:
        """The first ``limit`` crossings no minute has taken (all of them without one), in the
        order the door wrote them."""
        rows = connection.execute(
            "select c.crossing_id, c.document from door_crossing c "
            "left join door_crossing_binding b "
            "  on b.workspace_id = c.workspace_id and b.society_id = c.society_id "
            " and b.crossing_id = c.crossing_id "
            "where c.workspace_id = %s and c.society_id = %s and b.crossing_id is null "
            "order by c.crossing_seq limit %s",
            (workspace_id, society_id, limit),
        ).fetchall()
        return [Crossing(row["crossing_id"], row["document"]) for row in rows]

    def bind(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        society_id: uuid.UUID,
        tick: int,
        bound: Sequence[BoundCrossing],
    ) -> None:
        for crossing in bound:
            connection.execute(
                "insert into door_crossing_binding (workspace_id, society_id, crossing_id, tick, "
                "disposition, reason, event_id) values (%s, %s, %s, %s, %s, %s, %s)",
                (
                    workspace_id,
                    society_id,
                    crossing.crossing_id,
                    tick,
                    crossing.disposition,
                    crossing.reason,
                    crossing.event_id,
                ),
            )
            if crossing.disposition == "arrived":
                self._wear(connection, workspace_id, society_id, crossing.crossing_id)

    @staticmethod
    def _wear(
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        society_id: uuid.UUID,
        crossing_id: uuid.UUID,
    ) -> None:
        """Record the look an arrival that arrived brought, in the minute's transaction."""
        row = connection.execute(
            "select c.thing_id, c.document, c.look, s.world_id, s.version_id "
            "from door_crossing c join world_society s "
            "  on s.workspace_id = c.workspace_id and s.society_id = c.society_id "
            "where c.workspace_id = %s and c.society_id = %s and c.crossing_id = %s",
            (workspace_id, society_id, crossing_id),
        ).fetchone()
        assert row is not None and row["look"] is not None
        # Checked at intake against the same shipped library, so only a release that changed the
        # library between the arrival and its minute refuses it here: the visitor still arrives,
        # in its kind's own look, and a minute is never stopped by a look.
        with contextlib.suppress(ThingLookRefused):
            record_crossing_look(
                connection,
                workspace_id=workspace_id,
                world_id=row["world_id"],
                version_id=row["version_id"],
                thing_id=row["thing_id"],
                crossing_id=crossing_id,
                kind=row["document"]["kind"],
                look=row["look"],
            )

    def consumed(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, society_id: uuid.UUID
    ) -> Sequence[ConsumedCrossing]:
        rows = connection.execute(
            "select b.tick, c.crossing_id, c.document, b.disposition, b.reason, b.event_id "
            "from door_crossing_binding b join door_crossing c "
            "  on c.workspace_id = b.workspace_id and c.society_id = b.society_id "
            " and c.crossing_id = b.crossing_id "
            "where b.workspace_id = %s and b.society_id = %s order by b.tick, c.crossing_seq",
            (workspace_id, society_id),
        ).fetchall()
        return [
            ConsumedCrossing(
                tick=row["tick"],
                crossing=Crossing(row["crossing_id"], row["document"]),
                bound=BoundCrossing(
                    row["crossing_id"], row["disposition"], row["reason"], row["event_id"]
                ),
            )
            for row in rows
        ]


@dataclass(frozen=True)
class Visits:
    """One grant's visitors, on a connection scoped to its workspace."""

    connection: psycopg.Connection
    workspace_id: uuid.UUID
    grant: Grant
    actor: uuid.UUID

    @property
    def _ids(self) -> dict[str, Any]:
        return {"w": self.workspace_id, "g": self.grant.grant_id}

    def society(self) -> dict[str, Any]:
        """The society of things the grant's visitors arrive in, or a refusal by name: the rule
        the grant was issued under, read again, so a grant stored before it held is refused too."""
        version = self.grant.scope.version_id
        society = (
            None
            if version is None
            else visitors_society(self.connection, self.workspace_id, self.grant.world_id, version)
        )
        if society is None:
            raise ChannelRefused(
                "world_not_open_to_visitors", 409, "this world's version takes no visitors"
            )
        return society

    def present(self) -> list[uuid.UUID]:
        """The visitors of this grant still in its society, oldest arrival first."""
        rows = self.connection.execute(
            "select c.thing_id from door_crossing c "
            "left join door_crossing_binding b "
            "  on b.workspace_id = c.workspace_id and b.society_id = c.society_id "
            " and b.crossing_id = c.crossing_id "
            "where c.workspace_id = %(w)s and c.grant_id = %(g)s and c.kind = 'arrival' "
            "  and (b.disposition is null or b.disposition = 'arrived') "
            "  and not exists (select 1 from door_crossing d "
            "    where d.workspace_id = c.workspace_id and d.society_id = c.society_id "
            "      and d.grant_id = c.grant_id and d.kind = 'departure' "
            "      and d.thing_id = c.thing_id) "
            "  and not exists (select 1 from world_society_event e "
            "    where e.workspace_id = c.workspace_id and e.society_id = c.society_id "
            "      and e.subject_id = c.thing_id and e.event_kind = 'thing_departed') "
            "order by c.crossing_seq",
            self._ids,
        ).fetchall()
        return [row["thing_id"] for row in rows]

    def in_world(self, thing_id: uuid.UUID) -> bool:
        """Whether ``thing_id`` arrived under this grant, or waits to, and its society has not
        recorded it leaving: a departure the door wrote counts only once a minute takes it."""
        row = self.connection.execute(
            "select 1 from door_crossing c "
            "left join door_crossing_binding b "
            "  on b.workspace_id = c.workspace_id and b.society_id = c.society_id "
            " and b.crossing_id = c.crossing_id "
            "where c.workspace_id = %(w)s and c.grant_id = %(g)s and c.kind = 'arrival' "
            "  and c.thing_id = %(t)s and (b.disposition is null or b.disposition = 'arrived') "
            "  and not exists (select 1 from world_society_event e "
            "    where e.workspace_id = c.workspace_id and e.society_id = c.society_id "
            "      and e.subject_id = c.thing_id and e.event_kind = 'thing_departed')",
            {**self._ids, "t": thing_id},
        ).fetchone()
        return row is not None

    def gone(self, thing_id: uuid.UUID) -> bool:
        """Whether the bridge said the person behind ``thing_id`` left its game."""
        row = self.connection.execute(
            "select 1 from door_visitor_gone where workspace_id = %(w)s and grant_id = %(g)s "
            "and thing_id = %(t)s",
            {**self._ids, "t": thing_id},
        ).fetchone()
        return row is not None

    def _write(
        self,
        society_id: uuid.UUID,
        kind: str,
        document: Mapping[str, Any],
        game_items: Sequence[Mapping[str, Any]] | None,
        look: Mapping[str, Any] | None,
    ) -> bool:
        """Append one crossing to its society, or find it written already; True when new."""
        crossing_id = document["arrival_id" if kind == "arrival" else "departure_id"]
        self.connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 153001))", (str(society_id),)
        )
        held = self.connection.execute(
            "select document_sha256 from door_crossing where workspace_id = %s "
            "and society_id = %s and crossing_id = %s",
            (self.workspace_id, society_id, crossing_id),
        ).fetchone()
        digest = sha256_of_canonical(dict(document)).hex()
        if held is not None:
            if held["document_sha256"] != digest:
                raise ChannelRefused(
                    "crossing_id_reused", 409, "this id already names another crossing"
                )
            return False
        if kind == "arrival":
            self._within_arrivals_per_hour()
        if kind == "arrival" and len(self.present()) >= self.grant.scope.visitors_maximum:
            # Counted under the society's crossing lock, so two arrivals at once never both take
            # the last place the grant gives.
            raise ChannelRefused(
                "visitors_full", 409, "this grant has as many visitors in the world as it lets in"
            )
        latest = self.connection.execute(
            "select coalesce(max(crossing_seq), 0) as latest from door_crossing "
            "where workspace_id = %s and society_id = %s",
            (self.workspace_id, society_id),
        ).fetchone()
        assert latest is not None
        self.connection.execute(
            "insert into door_crossing (workspace_id, society_id, crossing_id, crossing_seq, "
            "grant_id, kind, thing_id, document, document_sha256, game_items, look, recorded_by) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                self.workspace_id,
                society_id,
                crossing_id,
                latest["latest"] + 1,
                self.grant.grant_id,
                kind,
                document["thing_id"],
                Jsonb(dict(document)),
                digest,
                None if game_items is None else Jsonb(list(game_items)),
                None if look is None else Jsonb(dict(look)),
                self.actor,
            ),
        )
        return True

    def _within_arrivals_per_hour(self) -> None:
        """Refuse an arrival past the grant's hourly bound, counted under the society's crossing
        lock the caller holds; answered with when the oldest arrival of the hour leaves the
        count."""
        row = self.connection.execute(
            "select count(*) as recent, ceil(extract(epoch from min(recorded_at) "
            "  + interval '1 hour' - statement_timestamp())) as wait "
            "from door_crossing where workspace_id = %(w)s and grant_id = %(g)s "
            "and kind = 'arrival' and recorded_at > statement_timestamp() - interval '1 hour'",
            self._ids,
        ).fetchone()
        assert row is not None
        if row["recent"] >= ARRIVALS_PER_HOUR_MAXIMUM:
            raise ChannelRefused(
                "too_many_arrivals",
                429,
                f"a grant takes at most {ARRIVALS_PER_HOUR_MAXIMUM} arrivals an hour",
                retry_after_s=max(1, int(row["wait"])),
            )

    def arrive(
        self,
        *,
        arrival_id: uuid.UUID,
        game_type: str,
        look_key: str,
        carried: Sequence[Mapping[str, Any]],
        presence: Any,
        mapping: Mapping[str, Any],
        reads: Sequence[str],
    ) -> tuple[dict[str, Any], bool]:
        """Write one arrival under this grant, or answer with the one this arrival id wrote; a
        refusal by name when the grant, its mapping or its society does not admit it."""
        scope = self.grant.scope
        if scope.visitors_maximum == 0:
            raise ChannelRefused("no_visitors_allowed", 403, "this grant brings no visitors in")
        if arrival_id.version != 4:
            # A random id of the bridge's own: a derived departure id is never one.
            raise ChannelRefused(
                "arrival_id_not_random", 422, "an arrival is named by a random version 4 UUID"
            )
        visitor = next(
            (entry for entry in mapping["visitors"] if entry["game_type"] == game_type), None
        )
        if game_type not in scope.kinds or visitor is None:
            raise ChannelRefused(
                "kind_not_admitted", 422, "this grant does not admit that kind of visitor"
            )
        look = next((entry for entry in visitor["looks"] if entry["look_key"] == look_key), None)
        if look is None:
            raise ChannelRefused("look_not_offered", 422, "that look is not one the mapping offers")
        visitor_kind = _shipped_kind(visitor["kind"])
        if scope.visitors_decided_by == "world" and not _world_may_decide(visitor_kind):
            raise ChannelRefused(
                "kind_not_world_decided", 422, "the world decides for no visitor of that kind"
            )
        kind_reference = {
            "kind": visitor_kind.kind,
            "version": visitor_kind.version,
            "sha256": visitor_kind.sha256,
        }
        try:
            worn = check_crossing_look(kind_reference, _look_reference(look["look"]))
        except ThingLookRefused as exc:
            raise ChannelRefused(exc.code, 422, exc.detail) from exc
        units = sum(int(entry["count"]) for entry in carried)
        if units and not scope.may_carry_in:
            raise ChannelRefused(
                "carrying_not_allowed", 403, "this grant lets nothing be carried in"
            )
        if units > CARRIED_UNITS_MAXIMUM:
            raise ChannelRefused(
                "too_much_carried", 422, f"a visitor carries at most {CARRIED_UNITS_MAXIMUM} things"
            )
        items = {entry["game_item"]: entry for entry in mapping["items"]}
        for entry in carried:
            item = items.get(entry["game_item"])
            if item is None or item["ways"] not in ("in", "both"):
                raise ChannelRefused(
                    "item_not_mapped", 422, "that item does not cross into this world"
                )
        society = self.society()
        thing_id = _id(self.grant.grant_id, "arrival", arrival_id)
        held: list[dict[str, Any]] = []
        units_list: list[dict[str, Any]] = []
        for index, entry in enumerate(carried):
            item = items[entry["game_item"]]
            kind = _shipped_kind(item["kind"])
            for unit in range(int(entry["count"])):
                carried_id = _id(self.grant.grant_id, "arrival", arrival_id, index, unit)
                held.append(
                    {
                        "thing_id": str(carried_id),
                        "kind": {"kind": kind.kind, "version": kind.version, "sha256": kind.sha256},
                    }
                )
                units_list.append({"thing_id": str(carried_id), "game_item": entry["game_item"]})
        manifest = arrival_manifest(
            mapping=mapping,
            mapping_sha256=presence.mapping_sha256,
            reads=reads,
            visitor=visitor,
            kind=kind_reference,
            carried=carried,
            sent={
                "arrival_id": str(arrival_id),
                "game_type": game_type,
                "look_key": look_key,
                "carried": [dict(entry) for entry in carried],
            },
        )
        manifest_sha256 = sha256_of_canonical(manifest).hex()
        self.connection.execute(
            "insert into door_manifest (workspace_id, manifest_sha256, document) "
            "values (%s, %s, %s) on conflict do nothing",
            (self.workspace_id, manifest_sha256, Jsonb(manifest)),
        )
        # The visitor wears the shipped look, so it carries the look's own licence and may be shown
        # where the look may; a mapping's words about the look's licence are not read for it.
        worn_origin = shipped_looks()[(worn.look, worn.version)].document["origin"]
        document = {
            "profile": ARRIVAL_PROFILE,
            "arrival_id": str(arrival_id),
            "thing_id": str(thing_id),
            "kind": kind_reference,
            "origin": {
                "profile": "exulanica.origin/v1",
                "class": "crossed",
                "by": {
                    "kind": "program",
                    "bridge": self.grant.bridge,
                    "adapter_version": presence.adapter_version,
                    "mapping_sha256": presence.mapping_sha256,
                    "grant_id": str(self.grant.grant_id),
                },
                "sources": [],
                "licence": dict(worn_origin["licence"]),
                "authors": [],
                "lineage": {
                    "ingredients": [],
                    "receipts": [],
                    "translation_manifest_sha256": manifest_sha256,
                },
                "distribution": worn_origin["distribution"],
            },
            "translation_manifest_sha256": manifest_sha256,
            "carried": held,
            "grant_id": str(self.grant.grant_id),
            "gate": scope.gate,
            # Who decides for the visitor is the grant's word, as its revision under the grant's
            # lock states it, never the bridge's; stated only where the world decides, so a
            # program's visitor's arrival keeps its bytes.
            **({"decided_by": "world"} if scope.visitors_decided_by == "world" else {}),
        }
        check_arrival(document)
        with self.connection.transaction():
            created = self._write(
                society["society_id"], "arrival", document, units_list, worn.document()
            )
        return document, created

    def departure_written(self, thing_id: uuid.UUID, reason: str) -> bool:
        """Whether the door wrote the departure of ``thing_id`` for ``reason`` under this grant."""
        row = self.connection.execute(
            "select 1 from door_crossing where workspace_id = %(w)s and grant_id = %(g)s "
            "and kind = 'departure' and crossing_id = %(d)s",
            {**self._ids, "d": departure_id(self.grant.grant_id, thing_id, reason)},
        ).fetchone()
        return row is not None

    def depart(self, thing_id: uuid.UUID, reason: str) -> bool:
        """Write the departure of one of this grant's visitors for ``reason``; True when new."""
        society = self.society()
        document = {
            "profile": DEPARTURE_PROFILE,
            "departure_id": str(departure_id(self.grant.grant_id, thing_id, reason)),
            "thing_id": str(thing_id),
            "reason": reason,
        }
        check_departure(document)
        with self.connection.transaction():
            return self._write(society["society_id"], "departure", document, None, None)

    def end(self) -> int:
        """A departure for every visitor of this grant still present, because the grant ended;
        how many were written."""
        if self.grant.scope.version_id is None or self.grant.scope.visitors_maximum == 0:
            return 0
        written = 0
        for thing_id in self.present():
            written += self.depart(thing_id, "grant_ended")
        return written
