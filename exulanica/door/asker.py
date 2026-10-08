"""The door's side of the decision host's external asker: asking a bridge, and waiting for it.

The decision host asks every thing at a choice point once a minute (``docs/decision-roles-
contract.md``). For a thing an outside program decides for, it asks through an external asker the
application gives it (``exulanica/api/external_asking.py``), and this is the one the door gives:

*   :meth:`DoorAsker.configuration`, before anything is reserved, states the external request's
    ``provider_config`` as the grant stands now (its bridge, revision, the mapping its bridge last
    said hello with, and the bridge's declared deadline) and whether to ask at all, for a thing the
    grant names or one of its visitors still here: a revoked or expired grant, a bridge the
    deployment no longer declares or offers here, a workspace that is closed (where the deployment
    has accounts), a program that is not connected, or a visitor whose player left its game, is a
    refusal the host records at once. A program is connected when the holder of the grant's live
    credential said hello since it was issued, with a version and mapping the deployment still
    admits, and polled within the presence window (:func:`exulanica.door.channel.presence_of`). A
    visitor of a grant that ended is sent home: the door writes its departure for the next minute.
*   :meth:`DoorAsker.answer` writes the ask to the grant's outbox, where the bridge's held poll
    reads it, and waits until ``ends_at`` for the bridge's answer in the inbox. The answer it finds
    becomes the result the host records as the receipt: the offered option the bridge named, and
    who answered as the stored answer records it (the adapter version and mapping its presence named
    when it answered). An answer is accepted only while its grant stands and only under the mapping
    its request was reserved with. No answer by then is ``no_answer_in_time``, or the grant's end if
    it ended meanwhile, and the world's routine decides that turn.

It holds no connection while it waits: each read opens a short session in the world's workspace,
and within this process a stored answer wakes it at once (:mod:`exulanica.door.notices`).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

import psycopg

from exulanica.db.session import Database
from exulanica.door.bridges import BridgeDirectory
from exulanica.door.channel import presence_of, presence_window
from exulanica.door.crossings import Visits
from exulanica.door.grants import GrantRepository, grant_actor
from exulanica.door.notices import Notices
from exulanica.door.protocol import DEADLINE_MS_DEFAULT
from exulanica.world.decision_roles import decision_roles

__all__ = ["DoorAsker"]

#: How often a waiting ask reads the inbox when no notice wakes it: an answer stored by another
#: process is seen within this.
_READ_EVERY_SECONDS: Final = 0.25
_ENDED: Final = {"revoked": "grant_revoked", "expired": "grant_expired"}


def _uuid_or_none(text: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


def _unavailable(reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason, "proposal": None, "provider": None}


@dataclass(frozen=True)
class DoorAsker:
    """Asks a grant's bridge for one thing's choice, through the channel."""

    database: Database
    notices: Notices
    bridges: BridgeDirectory
    monotonic: Callable[[], float] = time.monotonic
    #: Whether a workspace is open, where the deployment has accounts.
    open_to: Callable[[uuid.UUID], bool] | None = None

    def configuration(
        self,
        workspace_id: uuid.UUID,
        world_id: str,
        subject_id: str,
        decider: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str | None]:
        """The external ``provider_config`` as the grant stands, and a refusal or None."""
        grant_id = uuid.UUID(decider["grant_id"])
        with self.database.session(workspace_id) as connection:
            grants = GrantRepository(connection, workspace_id, grant_actor(grant_id))
            grant = grants.current(grant_id)
            if grant is None or grant.world_id != world_id or grant.bridge != decider["bridge"]:
                raise LookupError("a decider names a grant this world does not hold")
            presence = presence_of(connection, workspace_id, grant_id)
            now = grants.now()
            ended = grant.ended(now)
            named = subject_id in grant.scope.things
            visits = Visits(connection, workspace_id, grant, grant_actor(grant_id))
            visitor = None if named else _uuid_or_none(subject_id)
            visiting = visitor is not None and visitor in visits.present()
            if ended is not None and visiting:
                # A grant that ended unrevoked sends its visitor home at the next minute; a
                # revocation already did, and writing the same departure again writes nothing.
                visits.depart(visitor, "grant_ended")
            # A visitor whose departure is written is still in the world until the minute that
            # takes it, and its program decides for it until then.
            visiting = visitor is not None and visits.in_world(visitor)
            gone = visiting and visits.gone(visitor)
        bridge = self.bridges.get(grant.bridge)
        config = {
            "kind": "external",
            "bridge": grant.bridge,
            "grant_id": str(grant_id),
            "grant_seq": grant.grant_seq,
            "mapping_sha256": (
                presence.mapping_sha256 if presence is not None else grant.mapping_sha256[0]
            ),
            "deadline_ms": DEADLINE_MS_DEFAULT if bridge is None else bridge.deadline_ms,
        }
        if ended == "expired" and named:
            # A grant that ran out hands its things back to their routine the first time the host
            # meets one of them, as a revocation does: this turn is recorded grant_expired, and the
            # host asks the routine for every later one, with no request.
            with self.database.session(workspace_id) as connection:
                GrantRepository(connection, workspace_id, grant_actor(grant_id)).lapse(grant_id)
        if ended is not None:
            return config, _ENDED[ended]
        if not named and not visiting:
            # Neither a thing the grant names nor one of its visitors still here: the owner
            # narrowed the grant after binding this thing; the routine decides for it.
            return config, "grant_revoked"
        if bridge is None or not bridge.offered_to(workspace_id):
            # The deployment removed the bridge, or stopped offering it here: nobody may answer.
            return config, "decider_disconnected"
        if self.open_to is not None and not self.open_to(workspace_id):
            # The workspace was disabled, or its owner's account or membership ended.
            return config, "decider_disconnected"
        if (
            gone
            or presence is None
            or not presence.admitted_by(bridge)
            or not presence.connected(now, presence_window(bridge))
        ):
            # The bridge is quiet, or said the person behind this visitor left its game.
            return config, "decider_disconnected"
        return config, None

    def answer(
        self,
        workspace_id: uuid.UUID,
        world_id: str,
        request: Mapping[str, Any],
        ends_at: float,
    ) -> dict[str, Any]:
        """Ask the grant's bridge, and return what the receipt records by ``ends_at``."""
        started = self.monotonic()
        config = request["provider_config"]
        grant_id = uuid.UUID(config["grant_id"])
        request_id = uuid.UUID(request["request_id"])
        try:
            self._write_ask(workspace_id, grant_id, request_id)
        except psycopg.errors.CheckViolation:
            # The grant ended between the host's configuration read and this write.
            return _unavailable(self._ended_reason(workspace_id, grant_id) or "grant_revoked")
        self.notices.asked(grant_id)
        try:
            while True:
                found = self._stored_answer(workspace_id, request_id)
                if found is not None:
                    break
                remaining = ends_at - self.monotonic()
                if remaining <= 0:
                    return _unavailable(
                        self._ended_reason(workspace_id, grant_id) or "no_answer_in_time"
                    )
                self.notices.wait_for_answer(request_id, min(_READ_EVERY_SECONDS, remaining))
        finally:
            self.notices.forget(request_id)
        # The grant is read again before the answer counts: an answer stored before a revocation
        # committed is never accepted after it.
        ended = self._ended_reason(workspace_id, grant_id)
        if ended is not None:
            return _unavailable(ended)
        if found["mapping_sha256"] != config["mapping_sha256"]:
            # The bridge said hello with another mapping after this ask was reserved under the
            # last one: the answer was not given under the mapping its request names.
            return _unavailable("decider_disconnected")
        document = found["document"]
        role = decision_roles().for_request(request["profile"])
        if role is None:
            raise LookupError("an ask names a request no registered role writes")
        option = next(
            option
            for option in request["context"]["options"]
            if role.adapter.option_from_record(option).label == document["label"]
        )
        proposal: dict[str, Any] = {"label": option["label"], "option": option}
        if "line" in document:
            proposal["line"] = document["line"]
        return {
            "status": "accepted",
            "reason": "validated_choice",
            "proposal": proposal,
            "provider": {
                "kind": "external",
                "bridge": config["bridge"],
                "adapter_version": found["adapter_version"],
                "grant_id": config["grant_id"],
                "grant_seq": config["grant_seq"],
                "mapping_sha256": found["mapping_sha256"],
                "answer_sha256": found["answer_sha256"],
                "latency_ms": round((self.monotonic() - started) * 1000),
                "source_ref_sha256": None,
            },
        }

    def _write_ask(
        self, workspace_id: uuid.UUID, grant_id: uuid.UUID, request_id: uuid.UUID
    ) -> None:
        with self.database.session(workspace_id) as connection, connection.transaction():
            connection.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 149002))", (str(grant_id),)
            )
            row = connection.execute(
                "select r.society_id, "
                "(select coalesce(max(ask_seq), 0) from door_ask "
                " where workspace_id = %(w)s and grant_id = %(g)s) as latest "
                "from world_society_decision_request r "
                "where r.workspace_id = %(w)s and r.request_id = %(r)s",
                {"w": workspace_id, "g": grant_id, "r": request_id},
            ).fetchone()
            if row is None:
                raise LookupError("the host asks about a request it did not reserve")
            connection.execute(
                "insert into door_ask (workspace_id, grant_id, ask_seq, society_id, request_id) "
                "values (%s, %s, %s, %s, %s)",
                (workspace_id, grant_id, row["latest"] + 1, row["society_id"], request_id),
            )

    def _stored_answer(
        self, workspace_id: uuid.UUID, request_id: uuid.UUID
    ) -> dict[str, Any] | None:
        with self.database.session(workspace_id) as connection:
            return connection.execute(
                "select document, answer_sha256, adapter_version, mapping_sha256 from door_answer "
                "where workspace_id = %s and request_id = %s",
                (workspace_id, request_id),
            ).fetchone()

    def _ended_reason(self, workspace_id: uuid.UUID, grant_id: uuid.UUID) -> str | None:
        with self.database.session(workspace_id) as connection:
            grants = GrantRepository(connection, workspace_id, grant_actor(grant_id))
            grant = grants.current(grant_id)
            ended = None if grant is None else grant.ended(grants.now())
        return None if ended is None else _ENDED[ended]
