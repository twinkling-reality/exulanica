"""PostgreSQL authority for deterministic synthetic societies and historical inputs."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from exulanica.world.crossings import CROSSINGS_PER_MINUTE, BoundCrossing, crossing_stream
from exulanica.world.decision_roles import decision_roles
from exulanica.world.role_decisions import (
    append_role_events,
    apply_receipts,
    consumed_receipts,
)
from exulanica.world.society import (
    SOCIETY_POPULATION,
    SOCIETY_TICK_SECONDS,
    SocietyEvent,
    SocietyLivesElsewhere,
    StaleSocietyState,
    UnavailableSocietyInput,
    UnknownSociety,
    event_document_sha256,
    inputs_ahead,
    society_state_sha256,
)
from exulanica.world.society_action_repository import SocietyActionRepository
from exulanica.world.society_actions import (
    action_goal_policies,
    append_action_events,
    applied_hands,
)
from exulanica.world.society_decisions import validate_decision_receipt
from exulanica.world.society_engines import (
    DEFAULT_ENGINE,
    UnknownSocietyEngine,
    creatable_engine,
    society_engine,
)
from exulanica.world.society_grounds import society_population
from exulanica.world.society_input_policy import LIVING_INPUTS, THING_INPUTS, is_authored_ground
from exulanica.world.society_legacy import advance_society, initial_society
from exulanica.world.society_living import (
    initial_living_society,
    input_routine,
    living_places,
    routine_for,
)
from exulanica.world.society_living_decisions import LivingSeam, living_step
from exulanica.world.society_moments import record_moments
from exulanica.world.society_planner import (
    PURPOSEFUL_PROFILE,
    SocietyStartRefused,
    advance_purposeful_society,
    initial_purposeful_society,
    ordered_events_document,
    validate_input_successor,
    validate_society_input,
)
from exulanica.world.society_presence import (
    PresenceRefused,
    change_presence,
    presence_request,
)
from exulanica.world.society_repository_reads import (
    EVENT_KINDS_READ_MAXIMUM as EVENT_KINDS_READ_MAXIMUM,
)
from exulanica.world.society_repository_reads import (
    EVENTS_READ_MAXIMUM as EVENTS_READ_MAXIMUM,
)
from exulanica.world.society_repository_reads import (
    INPUT_PROFILES,
    SocietyReads,
)
from exulanica.world.society_repository_reads import (
    LINES_SAID_SQL as LINES_SAID_SQL,
)
from exulanica.world.society_repository_reads import (
    InvalidEventCursor as InvalidEventCursor,
)
from exulanica.world.society_repository_reads import (
    consumed_places as consumed_places,
)
from exulanica.world.society_repository_replay import SocietyReplay
from exulanica.world.society_social import (
    SOCIAL_PROFILE,
    advance_social_society,
    initial_social_society,
)
from exulanica.world.society_things import advance_things, initial_things_society
from exulanica.world.thing_kind_gone import THING_KIND_GONE_SQL
from exulanica.world.world_clock_repository import WorldClockRepository


class SocietyInputBehind(StaleSocietyState):
    """A society's latest input still lists a thing whose kind its workspace erased, and the
    minute asked for could not compose the input that leaves it out. The minute is not run: an
    erased creature is never run again. Asked again, the minute composes that input first.
    Answered as any society that changed since the caller read it."""


class SocietyRepository(SocietyReads, SocietyReplay):
    """A workspace's deterministic societies and their historical inputs.

    This class creates a society, records its inputs, advances its minute and changes a person's
    presence. Two parts hold the rest of its methods, each in its own module: ``SocietyReads``
    (society_repository_reads) answers snapshots, lines said, input provenance and the events
    window, and ``SocietyReplay`` (society_repository_replay) replays a stored society from its
    inputs and records.
    """

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        world_id: str,
        input_authorizer: Callable[[dict[str, Any]], None] | None = None,
        input_refresher: Callable[[uuid.UUID], None] | None = None,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.world_id = world_id
        self.input_authorizer = input_authorizer
        #: What composes a version's next input from the world as it stands and appends it where
        #: it reads differently: the application's authored-edit hook, bound to this connection
        #: and its session. A minute calls it where the society's input is behind an erasure
        #: (:meth:`tell_of_erased_kinds`); a repository that only reads or replays is given none.
        self.input_refresher = input_refresher

    def _lock(self) -> None:
        # Same ordering as authored edits and structural invalidation.
        self.connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s,880024))", (str(self.workspace_id),)
        )

    def _authorize(self, document: dict[str, Any]) -> None:
        if self.input_authorizer is None:
            raise UnavailableSocietyInput("current society input authorization is not configured")
        self.input_authorizer(document)

    def _latest_input(self, row: dict[str, Any]) -> dict[str, Any]:
        """The newest input the society holds, as stored."""
        sequence = self._chain(row)
        return self._inputs(row, [sequence])[sequence]

    @staticmethod
    def _kept_kind_beings(row: dict[str, Any]) -> set[str]:
        """The placed beings the state holds whose kind is one their workspace kept, by placed
        id."""
        return {
            person["placed_id"]
            for person in row["state"].get("inhabitants", ())
            if person.get("came_by") == "placed"
            and isinstance(person.get("kind"), dict)
            and person["kind"].get("source") == "workspace"
        }

    @staticmethod
    def _kept_kind_things(latest: dict[str, Any]) -> set[str]:
        """The placed things an input lists whose kind is one their workspace kept, by placed
        id."""
        return {
            entry["placed_id"]
            for entry in latest.get("things", ())
            if isinstance(entry.get("kind"), dict) and entry["kind"].get("source") == "workspace"
        }

    def _any_kind_gone(self, row: dict[str, Any], placed_ids: set[str]) -> bool:
        """Whether any of these placed things of the society's version has its kind gone, by
        the condition a version's things are read with: nothing asked for none, else one query.
        Whether a thing was since removed is not asked; each caller says why that is right."""
        if not placed_ids:
            return False
        found = self.connection.execute(
            "select exists(select 1 from world_alternate_thing t "
            "where t.workspace_id=%(w)s and t.world_id=%(world)s and t.version_id=%(v)s "
            f"and t.thing_id = any(%(ids)s) and {THING_KIND_GONE_SQL}) as gone",
            {
                "w": self.workspace_id,
                "world": self.world_id,
                "v": row["version_id"],
                "ids": sorted(placed_ids),
            },
        ).fetchone()
        return bool(found["gone"])

    def _erased_and_untold(self, row: dict[str, Any], latest: dict[str, Any]) -> bool:
        """Whether a creature this society would run was erased and the society not yet told.

        Two ways it can be so. The latest input still LISTS a placed thing whose kind is gone:
        a being already here, or one placed and erased before any minute, which the next minute
        would bring in; an input that lists a thing whose kind is gone is behind whether or not
        the thing was since removed. Or the latest input is NOT AVAILABLE and the STATE holds a
        placed being whose kind is gone: an unavailable input lists nothing and names nobody,
        and would leave the being in the state.

        An available input that does not list a being the state holds is not behind, whatever
        became of the being's kind: the next minute sends away every placed being its input does
        not list, so a creature whose thing was removed and whose kind was then erased leaves in
        that minute as any removed thing does.

        Only a society of things is asked, and it costs nothing unless one of those lists names
        a thing of a kind its workspace kept: then one query asks which of them have their kind
        gone.
        """
        if society_engine(row["engine_version"]).state_family != "things":
            return False
        asked = self._kept_kind_things(latest)
        if latest.get("availability") != "available":
            asked |= self._kept_kind_beings(row)
        return self._any_kind_gone(row, asked)

    def _holds_a_being_about_to_leave(self, row: dict[str, Any], latest: dict[str, Any]) -> bool:
        """Whether the state still holds a placed being whose kind is gone and which the latest
        input, an available one, no longer lists: a society already told of an erasure (the
        erasing request tells at once, which is the usual case), or one whose person removed the
        thing first. The being leaves in the society's next minute; until then the state shows
        it, and no model is asked about that state."""
        if latest.get("availability") != "available":
            return False
        return self._any_kind_gone(
            row, self._kept_kind_beings(row) - self._kept_kind_things(latest)
        )

    def _tell(self, row: dict[str, Any]) -> None:
        """Compose the next input of a society that is behind an erasure, or refuse by name."""
        if self.input_refresher is None:
            raise SocietyInputBehind(
                "a kind this society runs was erased; its next input is composed first"
            )
        self.input_refresher(row["version_id"])
        latest = self._latest_input(row)
        if not self._erased_and_untold(row, latest):
            return
        if latest["availability"] != "available":
            # Nothing can be composed that sends the being away while the world's source cannot
            # be read. The minute is refused as any minute over an unavailable input that must
            # change is: a step answers it by name and a playback round pauses with its reason.
            raise UnavailableSocietyInput(
                "a creature this society holds was erased and its input is unavailable"
            )
        raise SocietyInputBehind(
            "a kind this society runs was erased and its next input still holds it"
        )

    def tell_of_erased_kinds(self, version_id: uuid.UUID) -> str:
        """Compose the society's next input where a creature it would run was erased and it has
        not been told, and answer what was found.

        An erasure tells every society it reaches at once, but one it could not reach, one a
        restore replayed the erasure under, and one that was not running are told by nobody. So
        every minute asks first (:meth:`advance`), and a playback round's worker asks before
        its minutes, in a transaction of its own, which is this. Under the workspace's lock,
        which an erasure and a placing edit also take, so each is wholly before or wholly after
        it. The input is composed by the code an authored edit runs and leaves the thing out,
        naming it among those gone; the being leaves in the society's next minute, recorded as
        ``kind_erased``, and one not yet arrived never arrives.

        The answer is ``told`` where the input was composed now; ``leaving`` where nothing had
        to be composed and the state still holds a being of a gone kind that the next minute
        sends away (:meth:`_holds_a_being_about_to_leave`); and ``clear`` otherwise. After
        ``told`` and ``leaving`` the state holds an erased being until the minute runs, so the
        caller asks no model about it.

        Where no refresher was given, or the one given appended nothing that sends the thing
        away, the minute is refused and the erased creature is not run: as
        :class:`SocietyInputBehind`, or, where the latest input is unavailable, as an
        unavailable input.

        The engine is read alone first, without a lock: a society that is not one of things, or
        a version with none, is answered ``clear`` having locked and read nothing more.
        """
        with self.connection.transaction():
            engine = self.connection.execute(
                "select engine_version from world_society where workspace_id=%s and world_id=%s "
                "and version_id=%s",
                (self.workspace_id, self.world_id, version_id),
            ).fetchone()
            if engine is None or society_engine(engine["engine_version"]).state_family != "things":
                return "clear"
            self._lock()
            row = self._row(version_id, lock=True)
            if row is None or not self._holds_a_gone_kind(row):
                return "clear"
            latest = self._latest_input(row)
            if self._erased_and_untold(row, latest):
                self._tell(row)
                return "told"
            return "leaving" if self._holds_a_being_about_to_leave(row, latest) else "clear"

    def _holds_a_gone_kind(self, row: dict[str, Any]) -> bool:
        """Whether the society's version holds any placed thing whose kind is gone: one small
        query over the version's things, asked before a round so that a society none of whose
        things is of an erased kind has its latest input read by nobody."""
        found = self.connection.execute(
            "select exists(select 1 from world_alternate_thing t "
            "where t.workspace_id=%s and t.world_id=%s and t.version_id=%s "
            f"and {THING_KIND_GONE_SQL}) as held",
            (self.workspace_id, self.world_id, row["version_id"]),
        ).fetchone()
        return bool(found["held"])

    def create(
        self,
        version_id: uuid.UUID,
        *,
        place_id: uuid.UUID,
        region_id: str,
        seed: str,
        actor: uuid.UUID,
        profile: str = DEFAULT_ENGINE,
        initial_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create this version's society, or read back the one it holds with the same engine.

        An engine the table does not state, or states as retired, is refused by name before
        anything is read or written (:func:`~exulanica.world.society_engines.creatable_engine`).
        """
        creatable_engine(profile)
        return self._create(
            version_id,
            place_id=place_id,
            region_id=region_id,
            seed=seed,
            actor=actor,
            profile=profile,
            initial_input=initial_input,
        )

    def held(
        self, version_id: uuid.UUID, *, profile: str, region_id: str | None
    ) -> dict[str, Any] | None:
        """This version's society where it already holds one, read back with nothing composed.

        None where it holds none, so a caller composes the first input only for a society it
        will create. Another engine is refused as :meth:`create` refuses it, and another region by
        name (:class:`~exulanica.world.society.SocietyLivesElsewhere`); a creation that names no
        region reads back the one there is.
        """
        row = self._row(version_id)
        if row is None:
            return None
        if row["engine_version"] != profile:
            raise StaleSocietyState("society profile is immutable; create another authored version")
        if region_id is not None and row["region_id"] != region_id:
            raise SocietyLivesElsewhere(
                "this version's society lives in another region; one version holds one society"
            )
        return self.snapshot(version_id)

    def _create(
        self,
        version_id: uuid.UUID,
        *,
        place_id: uuid.UUID,
        region_id: str,
        seed: str,
        actor: uuid.UUID,
        profile: str,
        initial_input: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """The write a society's creation makes, for any engine the table states.

        :meth:`create` is the only caller that makes a society; a retired engine's genesis stays
        here because it is the write a stored society of that engine was made by, which a test
        repeats to hold such a society (``tests/retired_society_support.py``).
        """
        with self.connection.transaction():
            self._lock()
            version = self.connection.execute(
                "select 1 from world_alternate_version where workspace_id=%s and world_id=%s "
                "and version_id=%s for update",
                (self.workspace_id, self.world_id, version_id),
            ).fetchone()
            if version is None:
                raise UnknownSociety("world version is unavailable")
            existing = self._row(version_id, lock=True)
            if existing is not None:
                if existing["engine_version"] != profile:
                    raise StaleSocietyState(
                        "society profile is immutable; create another authored version"
                    )
                return self.snapshot(version_id)
            society_id = uuid.uuid5(version_id, "exulanica-society/v1")
            # An engine the table does not state is refused by name before anything is written.
            engine = society_engine(profile)
            if not engine.takes_inputs:
                if initial_input is not None:
                    raise ValueError(f"{profile} cannot consume district inputs")
                state = initial_society(
                    society_id,
                    seed,
                    minimum_population=engine.population_minimum,
                    maximum_population=engine.population_maximum,
                    profile=profile,
                )
            else:
                if initial_input is None:
                    raise UnavailableSocietyInput(
                        f"{profile} requires a server-authorized initial input"
                    )
                if is_authored_ground(initial_input["profile"]) and not engine.saved_world:
                    # The living society reads streets, occupancy and stated surface heights out
                    # of its place. A saved world's ground states a flat rectangle and none of
                    # those, so this refuses rather than publishing a place of empty answers.
                    raise ValueError(f"{profile} has no place contract for an authored ground")
                if engine.state_family == "living" and engine.saved_world != (
                    initial_input["profile"] in LIVING_INPUTS
                ):
                    # A living engine that stands on a saved world walks the living place a
                    # town's input carries; one that does not reads a district's input. Any other
                    # pairing is refused by name, whichever engine a caller names.
                    raise SocietyStartRefused("engine_not_for_this_ground")
                self._validate_scope(version_id, initial_input)
                self._authorize(initial_input)
                # A saved world's own ground holds the population its entry in the society ground
                # catalog states or derives by its rule, found by the navigation profile its
                # input records; a district, its full population.
                population = (
                    society_population(initial_input)
                    if is_authored_ground(initial_input["profile"])
                    else SOCIETY_POPULATION
                )
                if engine.state_family == "living":
                    routine = input_routine(initial_input)
                    [place] = living_places([initial_input], routine)
                    state = initial_living_society(
                        society_id,
                        seed,
                        place,
                        routine,
                        branch_id=str(version_id),
                        # A town's people are its homes' residents, bounded by its ground's rule;
                        # a district's population is sized to its place.
                        population=(
                            population if is_authored_ground(initial_input["profile"]) else None
                        ),
                        profile=profile,
                    )
                elif engine.state_family == "things":
                    # A society of things reads the things composition and no other.
                    if initial_input["profile"] not in THING_INPUTS:
                        raise SocietyStartRefused("engine_not_for_this_ground")
                    state = initial_things_society(
                        society_id, seed, initial_input, population=population
                    )
                elif profile == SOCIAL_PROFILE:
                    state = initial_social_society(
                        society_id, seed, initial_input, population=population
                    )
                elif profile == PURPOSEFUL_PROFILE:
                    state = initial_purposeful_society(
                        society_id, seed, initial_input, population=population
                    )
                else:
                    raise UnknownSocietyEngine(f"no genesis is implemented for {profile}")
            if engine.state_family == "living":
                population = state["population"]["size"]
            elif engine.state_family == "things":
                # The people its ground's population brings: the beings its author placed are its
                # things, which every replay places again from the first input.
                population = sum(
                    1 for person in state["inhabitants"] if person["came_by"] == "populated"
                )
            else:
                population = len(state["inhabitants"])
            if not engine.holds(population):
                raise ValueError(f"{profile} holds {engine.said()} inhabitants, not {population}")
            row = self.connection.execute(
                "insert into world_society(workspace_id,society_id,world_id,version_id,place_id,"
                "region_id,engine_version,seed,population_size,tick_seconds,"
                "state,state_sha256,created_by) "
                "values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *",
                (
                    self.workspace_id,
                    society_id,
                    self.world_id,
                    version_id,
                    place_id,
                    region_id,
                    profile,
                    seed,
                    population,
                    SOCIETY_TICK_SECONDS,
                    Jsonb(state),
                    society_state_sha256(state),
                    actor,
                ),
            ).fetchone()
            if initial_input is not None:
                self._insert_input(row, initial_input)
            return self._snapshot(row)

    def _validate_scope(self, version_id: uuid.UUID, document: dict[str, Any]) -> None:
        validate_society_input(document)
        if document["version_id"] != str(version_id) or document["world_id"] != self.world_id:
            raise ValueError("society input belongs to another world or branch")

    def _insert_input(self, row: dict, document: dict[str, Any]) -> None:
        self.connection.execute(
            "insert into "
            "world_society_input(workspace_id,society_id,input_seq,document,document_sha256) "
            "values(%s,%s,%s,%s,%s)",
            (
                self.workspace_id,
                row["society_id"],
                document["input_seq"],
                Jsonb(document),
                document["document_sha256"],
            ),
        )

    def record_input(self, version_id: uuid.UUID, document: dict[str, Any]) -> dict[str, Any]:
        """Internal authored-edit hook; call in the edit transaction, never from arbitrary JSON."""
        with self.connection.transaction():
            self._lock()
            row = self._row(version_id, lock=True)
            if row is None:
                raise UnknownSociety("society is unavailable")
            if row["engine_version"] not in INPUT_PROFILES:
                raise ValueError("legacy society cannot consume authored inputs")
            self._validate_scope(version_id, document)
            self._authorize(document)
            last = self.connection.execute(
                "select document from world_society_input where workspace_id=%s and society_id=%s "
                "order by input_seq desc limit 1",
                (self.workspace_id, row["society_id"]),
            ).fetchone()["document"]
            if document == last:
                return document
            if document["input_seq"] != last["input_seq"] + 1:
                raise StaleSocietyState("society input sequence changed; reload before recording")
            validate_input_successor(last, document)
            self._insert_input(row, document)
            return document

    def _input_rows(self, row: dict) -> list[dict]:
        return self.connection.execute(
            "select input_seq,document,document_sha256 from world_society_input "
            "where workspace_id=%s and society_id=%s order by input_seq",
            (self.workspace_id, row["society_id"]),
        ).fetchall()

    def _chain(self, row: dict) -> int:
        """The newest input sequence, after checking the stored inputs run from one with no gap."""
        found = self.connection.execute(
            "select count(*) as n,min(input_seq) as low,max(input_seq) as high "
            "from world_society_input where workspace_id=%s and society_id=%s",
            (self.workspace_id, row["society_id"]),
        ).fetchone()
        if not found["n"] or found["low"] != 1:
            raise ValueError("missing society genesis input")
        if found["high"] != found["n"]:
            raise ValueError("society input chain has a gap")
        return int(found["high"])

    def _inputs(self, row: dict, sequences: Iterable[int]) -> dict[int, dict]:
        """The stored inputs with these sequence numbers, each held to its own row and validated.

        Every input was validated against the one before it when it was recorded, the table takes
        no update or delete, and replay checks the whole chain again from the first input. So a
        read loads and validates the inputs it shows or consumes, never the history behind them;
        what the history adds to a read is the one count ``_chain`` makes over its rows.
        """
        wanted = sorted(set(sequences))
        rows = self.connection.execute(
            "select input_seq,document,document_sha256 from world_society_input "
            "where workspace_id=%s and society_id=%s and input_seq=any(%s) order by input_seq",
            (self.workspace_id, row["society_id"], wanted),
        ).fetchall()
        if [value["input_seq"] for value in rows] != wanted:
            raise ValueError("a stored society input is missing")
        documents = {}
        for value in rows:
            document = value["document"]
            self._validate_scope(row["version_id"], document)
            if (
                document["input_seq"] != value["input_seq"]
                or document["document_sha256"] != value["document_sha256"]
            ):
                raise ValueError("stored input binding mismatch")
            documents[value["input_seq"]] = document
        return documents

    def _pending_inputs(self, row: dict) -> list[dict]:
        """The input the state consumed and every input queued after it, in order.

        What a step consumes. The engine checks each queued input against the one before it.
        """
        first = row["state"]["input_seq"]
        documents = self._inputs(row, range(first, self._chain(row) + 1))
        return [documents[sequence] for sequence in sorted(documents)]

    @staticmethod
    def _memories(row: dict) -> list[int]:
        """The inputs a social society's people remember, by sequence: what they observed and
        what they believe was each learned from one."""
        if row["engine_version"] != SOCIAL_PROFILE:
            return []
        return [
            memory["input_seq"]
            for agent in row["state"]["social"]["agents"].values()
            for memory in [*agent["observations"], *agent["beliefs"].values()]
        ]

    def named_inputs(self, row: dict) -> tuple[dict, ...]:
        """Every input a society's state names or its next minute consumes, to announce first.

        The input the state consumed, each queued after it and each its people remember: what a
        minute, the state read after it and a change of presence authorize, all in one transaction,
        so each is announced before the first takes the asset read lock
        (:func:`~exulanica.world.society.inputs_ahead`). A caller that reads the state and then
        runs minutes in one transaction, as a playback round does, announces these before the read.
        """
        if row["engine_version"] not in INPUT_PROFILES:
            return ()
        first = row["state"]["input_seq"]
        documents = self._inputs(row, [*range(first, self._chain(row) + 1), *self._memories(row)])
        return tuple(documents[sequence] for sequence in sorted(documents))

    def _validated_inputs(self, row: dict) -> list[dict]:
        """Every stored input from the first, each checked against the one before it: replay's."""
        rows = self._input_rows(row)
        if not rows or rows[0]["input_seq"] != 1:
            raise ValueError("missing society genesis input")
        documents = []
        for value in rows:
            document = value["document"]
            self._validate_scope(row["version_id"], document)
            if (
                document["input_seq"] != value["input_seq"]
                or document["document_sha256"] != value["document_sha256"]
            ):
                raise ValueError("stored input binding mismatch")
            if documents:
                validate_input_successor(documents[-1], document)
            documents.append(document)
        return documents

    def _decisions(self, row: dict, *, after: int = 0) -> list[dict]:
        """The stored receipts after ``after``, in decision order, each held to its request."""
        rows = self.connection.execute(
            "select d.document,d.document_sha256,r.document as request "
            "from world_society_decision d "
            "join world_society_decision_request r using(workspace_id,society_id,request_id) "
            "where d.workspace_id=%s and d.society_id=%s and d.decision_seq>%s "
            "order by d.decision_seq",
            (self.workspace_id, row["society_id"], after),
        ).fetchall()
        documents = []
        for sequence, value in enumerate(rows, after + 1):
            document = value["document"]
            validate_decision_receipt(document, value["request"])
            if (
                document["decision_seq"] != sequence
                or document["document_sha256"] != value["document_sha256"]
            ):
                raise ValueError("stored decision sequence or digest mismatch")
            documents.append(document)
        return documents

    def _consumed_decisions(self, row: dict) -> int:
        """The last receipt a committed minute consumed; every later one is queued."""
        return int(
            self.connection.execute(
                "select coalesce(max(decision_seq),0) as seq "
                "from world_society_transition_decision where workspace_id=%s and society_id=%s",
                (self.workspace_id, row["society_id"]),
            ).fetchone()["seq"]
        )

    def advance(
        self,
        version_id: uuid.UUID,
        *,
        base_tick: int,
        base_state_sha256: str,
        base_clock_revision: int | None = None,
        actor: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Play the society's next minute from ``base_tick``. A being a person plays takes its
        person's answer for the minute first, whichever way the minute is stepped: the playback
        claim, a control's manual step or the step route, never its routine
        (:func:`~exulanica.world.society_play.answer_played`; ``actor`` gives back a being whose
        person stopped answering). Where the decision host answered it already, its request is
        taken and nothing more is done."""
        from exulanica.world.society_play import answer_played

        answer_played(self.connection, self, version_id=version_id, actor=actor)
        with self.connection.transaction(), ExitStack() as ahead:
            self._lock()
            row = self._row(version_id, lock=True)
            if row is None:
                raise UnknownSociety("society is unavailable")
            if row["current_tick"] != base_tick or row["state_sha256"] != base_state_sha256:
                raise StaleSocietyState("society changed; reload before advancing")
            if society_state_sha256(row["state"]) != row["state_sha256"]:
                raise ValueError("stored society state digest mismatch")
            # A coupled world's minute waits while its society leads sealed traffic by the clock's
            # lead; a legacy world has no clock row and runs as it always has.
            clocks = WorldClockRepository(self.connection, self.workspace_id, self.world_id)
            clocks.check_revision(version_id, base_clock_revision)
            clock = clocks.before_minute(version_id, row["current_tick"])
            ahead.enter_context(inputs_ahead(self.connection, self.named_inputs(row)))
            engine = society_engine(row["engine_version"])
            places = None
            crossed: tuple[BoundCrossing, ...] = ()
            if engine.state_family == "legacy":
                state, events = advance_society(row["state"], row["seed"])
            elif engine.state_family == "living":
                inputs = self._pending_inputs(row)
                self._authorize(inputs[-1])
                routine = routine_for(row["state"])
                # The choices of every role this engine hosts are receipts asked before this
                # minute, applied through the living seam; with none, the rule decides for all.
                roles = decision_roles().hosted_by(row["engine_version"])
                receipts = (
                    self._decisions(row, after=self._consumed_decisions(row))
                    if engine.owner_model_choice
                    else []
                )
                places = living_places(inputs, routine)
                seam, decided = apply_receipts(
                    roles,
                    row["state"],
                    inputs[-1],
                    receipts,
                    LivingSeam(row["seed"], places, routine),
                )
                state, events = living_step(row["state"], row["seed"], seam)
                events = append_role_events(
                    roles, row["state"], state, inputs[-1], receipts, decided, events
                )
                processed = [(d.decision_seq, d.disposition) for d in decided]
            elif engine.state_family in ("purposeful", "things"):
                inputs = self._pending_inputs(row)
                # A society told by nobody that a creature it would run was erased is told now,
                # from the row and the inputs the minute has already read: the input that sends
                # the being away is composed first, and the minute consumes it.
                if self._erased_and_untold(row, inputs[-1]):
                    self._tell(row)
                    inputs = self._pending_inputs(row)
                # The latest authorized unavailable input must be able to pause the engine
                # even when earlier dependencies are now withdrawn. Historical replay/reads
                # still authorize every materialized input separately.
                self._authorize(inputs[-1])
                action_repository = SocietyActionRepository(
                    self.connection,
                    self.workspace_id,
                    world_id=self.world_id,
                    input_authorizer=self.input_authorizer,
                )
                requests = action_repository.pending_for_step(
                    version_id,
                    base_tick=base_tick,
                    base_state_sha256=base_state_sha256,
                )
                goal_policy, action_dispositions = action_goal_policies(
                    row["state"], inputs[-1], list(requests)
                )
                if row["engine_version"] == SOCIAL_PROFILE:
                    if inputs[-1]["availability"] == "available":
                        self.snapshot(version_id)
                        for document in inputs:
                            self._authorize(document)
                    decisions = self._decisions(row)
                    queued = [
                        d
                        for d in decisions
                        if d["decision_seq"] > row["state"]["social"]["last_decision_seq"]
                    ]
                    state, events, processed = advance_social_society(
                        row["state"],
                        row["seed"],
                        inputs,
                        queued,
                        external_goal_policy=goal_policy,
                    )
                else:
                    # The model decisions of every role this engine hosts are receipts asked
                    # before this minute; with none, the policies are the direct requests' alone
                    # and nothing is added.
                    roles = decision_roles().hosted_by(row["engine_version"])
                    receipts = self._decisions(row, after=self._consumed_decisions(row))
                    policies, decided = apply_receipts(
                        roles, row["state"], inputs[-1], receipts, goal_policy
                    )
                    state, events = advance_purposeful_society(
                        row["state"], row["seed"], inputs, goal_policy=policies
                    )
                    processed = [(d.decision_seq, d.disposition) for d in decided]
                events = append_action_events(
                    row["state"],
                    state,
                    inputs[-1],
                    list(requests),
                    action_dispositions,
                    events,
                )
                if engine.owner_model_choice:
                    events = append_role_events(
                        roles, row["state"], state, inputs[-1], receipts, decided, events
                    )
                if engine.state_family == "things":
                    # Placed beings as the latest input places them, then the crossings the door
                    # handed over and no minute has consumed, in the order it wrote them, at most
                    # a minute's worth: the rest wait for later minutes.
                    stream = crossing_stream()
                    pending = (
                        ()
                        if stream is None
                        else tuple(
                            stream.pending(
                                self.connection,
                                self.workspace_id,
                                row["society_id"],
                                state["tick"],
                                limit=CROSSINGS_PER_MINUTE,
                            )
                        )[:CROSSINGS_PER_MINUTE]
                    )
                    state, events, crossed = advance_things(
                        row["state"],
                        state,
                        row["seed"],
                        inputs[-1],
                        events,
                        pending,
                        decisions=consumed_receipts(receipts, decided),
                        asked=applied_hands(list(requests), action_dispositions),
                    )
            else:
                raise UnknownSocietyEngine(f"unsupported society engine {row['engine_version']!r}")
            digest = self._record(row, state, events)
            if clock is not None:
                clocks.after_minute(
                    clock,
                    before=row["state"],
                    after=state,
                    previous_state_sha256=row["state_sha256"],
                    state_sha256=digest,
                    events=[event.document for event in events],
                    places=None if places is None else [place.document for place in places],
                )
            if engine.takes_inputs:
                if engine.model_decisions:
                    for sequence, disposition in processed:
                        self.connection.execute(
                            "insert into world_society_transition_decision("
                            "workspace_id,society_id,tick,decision_seq,disposition) "
                            "values(%s,%s,%s,%s,%s)",
                            (
                                self.workspace_id,
                                row["society_id"],
                                state["tick"],
                                sequence,
                                disposition,
                            ),
                        )
                if engine.directed_actions:
                    action_repository.bind(
                        version_id,
                        tick=state["tick"],
                        dispositions=action_dispositions,
                        events=events,
                    )
            if crossed:
                # Each crossing bound once, to the event this minute recorded for it.
                stream = crossing_stream()
                assert stream is not None
                stream.bind(
                    self.connection, self.workspace_id, row["society_id"], state["tick"], crossed
                )
            return self.snapshot(version_id)

    def _record(self, row: dict, state: dict[str, Any], events: tuple[SocietyEvent, ...]) -> str:
        """Commit one minute: the new state, its events and, for an input engine, its receipt.
        Answers the new state's digest."""
        digest = society_state_sha256(state)
        self.connection.execute(
            "update world_society set current_tick=%s,state=%s,state_sha256=%s "
            "where workspace_id=%s and world_id=%s and society_id=%s",
            (
                state["tick"],
                Jsonb(state),
                digest,
                self.workspace_id,
                self.world_id,
                row["society_id"],
            ),
        )
        for event in events:
            self.connection.execute(
                "insert into "
                "world_society_event(workspace_id,society_id,event_id,tick,event_kind,"
                "subject_id,object_id,place_id,document,document_sha256) "
                "values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    row["society_id"],
                    event.event_id,
                    event.tick,
                    event.kind,
                    event.subject_id,
                    event.object_id,
                    row["place_id"],
                    Jsonb(event.document),
                    event_document_sha256(event),
                ),
            )
        # The moments this minute makes, written with it (society_moments): a person's History
        # tells what characters did and said from them, and they land with the minute or not at all.
        record_moments(self.connection, self.workspace_id, row, state, events)
        if row["engine_version"] in INPUT_PROFILES:
            self.connection.execute(
                "insert into "
                "world_society_transition(workspace_id,society_id,tick,from_input_seq,"
                "to_input_seq,previous_state_sha256,state_sha256,event_ids,events_sha256) "
                "values(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    row["society_id"],
                    state["tick"],
                    row["state"]["input_seq"],
                    state["input_seq"],
                    row["state_sha256"],
                    digest,
                    Jsonb([str(e.event_id) for e in events]),
                    society_state_sha256(ordered_events_document(events)),
                ),
            )
        return digest

    def change_presence(
        self,
        version_id: uuid.UUID,
        *,
        wanted: str,
        request_id: uuid.UUID,
        requested_by: uuid.UUID,
        base_tick: int,
        base_state_sha256: str,
    ) -> dict[str, Any]:
        """Send everyone away, or bring them back: one recorded minute, bound to this request.

        The person asks; this decides, under the same lock and compare-and-swap as a step. An
        exact retry of a recorded request returns the society as it is; a request against a state
        that has moved on is stale; one the state cannot honour is refused by name.
        """
        with self.connection.transaction(), ExitStack() as ahead:
            self._lock()
            row = self._row(version_id, lock=True)
            if row is None:
                raise UnknownSociety("society is unavailable")
            if not society_engine(row["engine_version"]).presence:
                raise PresenceRefused(
                    "engine_keeps_its_people",
                    f"the people of an {row['engine_version']} society are not sent away",
                )
            recorded = self.connection.execute(
                "select document from world_society_presence where workspace_id=%s "
                "and society_id=%s and request_id=%s",
                (self.workspace_id, row["society_id"], request_id),
            ).fetchone()
            if recorded is not None:
                document = recorded["document"]
                if (
                    document["presence"] != wanted
                    or document["base_tick"] != base_tick
                    or document["base_state_sha256"] != base_state_sha256
                    or document["requested_by"] != str(requested_by)
                ):
                    raise StaleSocietyState("this request id was used for another request")
                return self.snapshot(version_id)
            if row["current_tick"] != base_tick or row["state_sha256"] != base_state_sha256:
                raise StaleSocietyState("society changed; reload before asking")
            if society_state_sha256(row["state"]) != row["state_sha256"]:
                raise ValueError("stored society state digest mismatch")
            # A presence minute is a minute of a coupled world's clock like any other.
            clocks = WorldClockRepository(self.connection, self.workspace_id, self.world_id)
            clock = clocks.before_minute(version_id, row["current_tick"])
            waiting = self.connection.execute(
                "select 1 from world_society_action_request request "
                "left join world_society_transition_action consumed "
                "using(workspace_id,society_id,action_seq) "
                "where request.workspace_id=%s and request.society_id=%s "
                "and consumed.action_seq is null limit 1",
                (self.workspace_id, row["society_id"]),
            ).fetchone()
            if waiting is not None:
                # A directed request is consumed by the next ordinary minute; this minute would
                # pass it by and leave it bound to a state that no longer exists.
                raise PresenceRefused("a_request_is_waiting")
            deciding = self.connection.execute(
                "select 1 from world_society_decision_request request "
                "left join world_society_decision receipt "
                "using(workspace_id,society_id,request_id) "
                "left join world_society_transition_decision consumed "
                "on consumed.workspace_id=receipt.workspace_id "
                "and consumed.society_id=receipt.society_id "
                "and consumed.decision_seq=receipt.decision_seq "
                "where request.workspace_id=%s and request.society_id=%s "
                "and (request.base_tick=%s "
                "or (receipt.decision_seq is not null and consumed.decision_seq is null)) limit 1",
                (self.workspace_id, row["society_id"], row["current_tick"]),
            ).fetchone()
            if deciding is not None:
                # A model's decision is being asked for this minute, or answered and not yet
                # consumed: like a directed request, the next ordinary minute takes it.
                raise PresenceRefused("a_request_is_waiting")
            inputs = self._pending_inputs(row)
            # The state read after this minute names the same inputs: all are read first.
            ahead.enter_context(inputs_ahead(self.connection, self.named_inputs(row)))
            self._authorize(inputs[-1])
            request = presence_request(
                row["state"],
                request_id=request_id,
                requested_by=requested_by,
                wanted=wanted,  # type: ignore[arg-type]
            )
            state, events = change_presence(
                row["state"], row["seed"], inputs, request, population=row["population_size"]
            )
            digest = self._record(row, state, events)
            if clock is not None:
                clocks.after_minute(
                    clock,
                    before=row["state"],
                    after=state,
                    previous_state_sha256=row["state_sha256"],
                    state_sha256=digest,
                    events=[event.document for event in events],
                    places=None,
                )
            self.connection.execute(
                "insert into world_society_presence(workspace_id,society_id,tick,request_id,"
                "requested_by,presence,document,document_sha256) "
                "values(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    row["society_id"],
                    state["tick"],
                    request_id,
                    requested_by,
                    wanted,
                    Jsonb(request),
                    request["document_sha256"],
                ),
            )
            return self.snapshot(version_id)

    def _row(self, version_id: uuid.UUID, *, lock: bool = False) -> dict[str, Any] | None:
        suffix = " for update" if lock else ""
        return self.connection.execute(
            "select * from world_society where workspace_id=%s and world_id=%s "
            f"and version_id=%s{suffix}",
            (self.workspace_id, self.world_id, version_id),
        ).fetchone()

    @staticmethod
    def _snapshot(row: dict[str, Any]) -> dict[str, Any]:
        """The society as stored, seed included. A route serves it through
        :func:`~exulanica.world.society.served_snapshot`, which never carries the seed."""
        snapshot = {
            "profile": row["engine_version"],
            "society_id": row["society_id"],
            "world_id": row["world_id"],
            "version_id": row["version_id"],
            "place_id": row["place_id"],
            "region_id": row["region_id"],
            "seed": row["seed"],
            "population_size": row["population_size"],
            "tick_seconds": row["tick_seconds"],
            "current_tick": row["current_tick"],
            "state": row["state"],
            "state_sha256": row["state_sha256"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
        }
        if row["engine_version"] in INPUT_PROFILES:
            snapshot.update(
                {key: row["state"][key] for key in ("branch_id", "input_seq", "input_sha256")}
            )
        return snapshot
