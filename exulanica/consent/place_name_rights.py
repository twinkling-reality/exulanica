"""The place name right as stored: decisions appended, a place's rights read, and the resolver.

:mod:`exulanica.consent.place_names` states the rule; this module gives it its facts and records
what the account holder decides. It is the one module in this package that reaches a database,
and it reads and writes the tables migration 0097 adds, the entity and naming rows those name, and
nothing else.

**Every decision is appended.** Allowing a use records one ``granted`` event for each model of the
role's chain; stopping it records one ``withdrawn`` event for each model that still stands granted.
Each event is the next in its place, model and destination's sequence and carries the digest of
the one before it. Nothing is updated and nothing is deleted, so a withdrawal ends a right from the
next read and every earlier grant stays readable. Both writers take the workspace's privacy
currency lock before reading the last event, which is what makes the next position theirs.

**Deciding and releasing are different reads.** :func:`read_place_name_rights` reports what each
use means now and permits nothing by reporting it. :func:`released_place_names` and
:func:`place_name_released` are the only functions here that answer whether a name may be sent, and
they read under the final read check the photograph right uses: an idle connection, a read-only
transaction, the global asset read lock and one evaluation instant. A grant, withdrawal, rename,
merge or deletion cannot commit while the check runs, so each is either seen or refused until it
has finished, and the lock is released before anything is sent.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final, Literal

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json, sha256_digest
from exulanica.consent.place_names import (
    DECISION_PROFILE,
    DecisionKind,
    LastDecision,
    PlaceNameUses,
    UseReading,
    load_place_name_uses,
    model_state,
    read_use,
)
from exulanica.errors import PrivacyAdmissionError
from exulanica.models.handoff import ModelHandoff, ModelIdentity
from exulanica.models.manifest import Manifest, load_manifest

__all__ = [
    "PlaceNameRightRefused",
    "PlaceNameRights",
    "RefusalReason",
    "UnknownPlace",
    "grant_place_name",
    "name_digest",
    "place_name_released",
    "places_with_decisions",
    "read_place_name_rights",
    "released_place_names",
    "withdraw_place_name",
]

#: Why a grant was refused, as a closed vocabulary a screen can say in words.
RefusalReason = Literal["unnamed", "not_yours", "not_offered", "notice_changed"]

_EVENT_NAMESPACE: Final = uuid.UUID("0b5a7f52-3c41-5e0f-9d7a-6f2e1c8b4a97")


class UnknownPlace(LookupError):
    """No entity of class ``place`` with this id in the session's workspace."""


class PlaceNameRightRefused(PrivacyAdmissionError):
    """A grant this place, account holder or request cannot make. ``reason`` says which."""

    def __init__(self, reason: RefusalReason, message: str) -> None:
        super().__init__(message)
        self.reason: RefusalReason = reason


@dataclass(frozen=True, slots=True)
class PlaceNameRights:
    """What each offered use of one place's name means now, as one read found it.

    ``name`` is the place's current name, shown to the account holder who gave it; None when the
    place is unnamed, merged or deleted, and then no use can be allowed.
    """

    entity_id: uuid.UUID
    name: str | None
    uses: tuple[UseReading, ...]
    read_at: dt.datetime


@dataclass(frozen=True, slots=True)
class _Stored:
    """The last event for one place, model and destination: what the next one follows."""

    decision: LastDecision
    sequence: int
    receipt_sha256: bytes


def name_digest(name: str) -> bytes:
    """What a grant binds: the SHA-256 of the name's UTF-8 bytes, as the database computes it."""
    return hashlib.sha256(name.encode("utf-8")).digest()


def _instant(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("a place name decision time must include a UTC offset")
    return value.astimezone(dt.UTC)


def _spelled(value: dt.datetime) -> str:
    """One spelling of an instant in a receipt, matching ``personal_model_right_instant``."""
    return _instant(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _now(connection: psycopg.Connection) -> dt.datetime:
    return connection.execute("select clock_timestamp() as at").fetchone()["at"]


def _place_class(
    connection: psycopg.Connection, workspace_id: uuid.UUID, entity_id: uuid.UUID
) -> None:
    row = connection.execute(
        "select class::text as class from entity where workspace_id=%s and entity_id=%s",
        (workspace_id, entity_id),
    ).fetchone()
    if row is None or row["class"] != "place":
        raise UnknownPlace(f"no place {entity_id} in this workspace")


def _naming(
    connection: psycopg.Connection, workspace_id: uuid.UUID, entity_id: uuid.UUID
) -> Mapping[str, Any] | None:
    """The naming the place's current name rests on, or None if it is not a live, named place."""
    return connection.execute(
        "select display_name,naming_assertion_id,stated_by from place_naming(%s,%s) "
        "order by naming_assertion_id limit 1",
        (workspace_id, entity_id),
    ).fetchone()


def _last_decisions(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    entity_ids: Sequence[uuid.UUID] | None,
    at: dt.datetime,
) -> dict[uuid.UUID, dict[tuple[ModelIdentity, str], _Stored]]:
    rows = connection.execute(
        "select * from place_name_right_last_decisions(%s,%s,%s)",
        (workspace_id, None if entity_ids is None else list(entity_ids), at),
    ).fetchall()
    found: dict[uuid.UUID, dict[tuple[ModelIdentity, str], _Stored]] = {}
    for row in rows:
        identity = ModelIdentity(
            provider=row["model_provider"],
            role=row["model_role"],
            model_id=row["model_id"],
            revision=row["model_revision"],
        )
        found.setdefault(row["entity_id"], {})[(identity, row["destination"])] = _Stored(
            decision=LastDecision(
                identity=identity,
                destination=row["destination"],
                event=row["event"],
                decided_at=row["decided_at"],
                valid_until=row["valid_until"],
                notice=row["notice"],
                naming_holds=bool(row["naming_holds"]),
            ),
            sequence=row["sequence"],
            receipt_sha256=bytes(row["receipt_sha256"]),
        )
    return found


def _append(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    entity_id: uuid.UUID,
    identity: ModelIdentity,
    destination: str,
    previous: _Stored | None,
    event: DecisionKind,
    actor: uuid.UUID,
    at: dt.datetime,
    grant: tuple[Mapping[str, Any], str, dt.datetime] | None = None,
) -> None:
    """Append one decision after ``previous``; ``grant`` is a grant's naming, notice and term."""
    record: dict[str, Any] = {
        "profile": DECISION_PROFILE,
        "event": event,
        "entity_id": str(entity_id),
        "model": identity.as_record(),
        "destination": destination,
        "sequence": 0 if previous is None else previous.sequence + 1,
        "previous_sha256": None if previous is None else previous.receipt_sha256.hex(),
        "decided_by": str(actor),
        "decided_at": _spelled(at),
    }
    naming_assertion_id = name_sha256 = notice = valid_until = None
    if grant is not None:
        naming, notice, valid_until = grant
        naming_assertion_id = naming["naming_assertion_id"]
        name_sha256 = name_digest(naming["display_name"])
        record |= {
            "naming_assertion_id": str(naming_assertion_id),
            "name_sha256": name_sha256.hex(),
            "notice": notice,
            "valid_until": _spelled(valid_until),
        }
    canonical = canonical_json(record)
    digest = sha256_digest(canonical)
    connection.execute(
        "insert into place_name_right_event (workspace_id,event_id,entity_id,model_provider,"
        "model_role,model_id,model_revision,destination,sequence,previous_sha256,event,"
        "naming_assertion_id,name_sha256,notice,valid_until,decided_by,decided_at,"
        "receipt_record,receipt_canonical,receipt_sha256) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            workspace_id,
            uuid.uuid5(_EVENT_NAMESPACE, f"{workspace_id}:{digest.hex()}"),
            entity_id,
            identity.provider,
            identity.role,
            identity.model_id,
            identity.revision,
            destination,
            record["sequence"],
            None if previous is None else previous.receipt_sha256,
            event,
            naming_assertion_id,
            name_sha256,
            notice,
            valid_until,
            actor,
            at,
            Jsonb(record),
            canonical,
            digest,
        ),
    )


def places_with_decisions(
    connection: psycopg.Connection, workspace_id: uuid.UUID
) -> tuple[uuid.UUID, ...]:
    """Every place in this workspace with any decision about its name, withdrawn ones included."""
    rows = connection.execute(
        "select distinct entity_id from place_name_right_event where workspace_id=%s "
        "order by entity_id",
        (workspace_id,),
    ).fetchall()
    return tuple(row["entity_id"] for row in rows)


def read_place_name_rights(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    entity_id: uuid.UUID,
    *,
    uses: PlaceNameUses | None = None,
    manifest: Manifest | None = None,
) -> PlaceNameRights:
    """Every offered use of one place's name and what it means now. Reported, never permitted.

    Raises :class:`UnknownPlace` for an id that is not a place in this workspace. A merged, deleted
    or unnamed place is still read, so a grant it had can be seen and stopped.
    """
    uses = uses or load_place_name_uses()
    manifest = manifest or load_manifest()
    _place_class(connection, workspace_id, entity_id)
    naming = _naming(connection, workspace_id, entity_id)
    at = _now(connection)
    stored = _last_decisions(connection, workspace_id, [entity_id], at).get(entity_id, {})
    decisions = {key: each.decision for key, each in stored.items()}
    readings = []
    for use in uses.uses:
        handoff = uses.handoff(use, manifest)
        readings.append(
            read_use(
                use,
                handoff,
                notice=uses.notice(use, handoff),
                decisions=decisions,
                at=at,
            )
        )
    return PlaceNameRights(
        entity_id=entity_id,
        name=None if naming is None else naming["display_name"],
        uses=tuple(readings),
        read_at=at,
    )


def grant_place_name(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    entity_id: uuid.UUID,
    role: str,
    notice: str,
    actor: uuid.UUID,
    uses: PlaceNameUses | None = None,
    manifest: Manifest | None = None,
) -> None:
    """Allow this place's current name to go to every model of ``role``'s chain.

    ``notice`` is the text the account holder was shown, and it must be exactly the text the
    product states for this use now; anything else is a statement nobody agreed to. Only the
    account holder who stated the name may allow it. A model already allowed under this naming and
    notice is left as it is, so asking twice records nothing twice. The database refuses every
    grant this function would refuse, as well.
    """
    uses = uses or load_place_name_uses()
    manifest = manifest or load_manifest()
    use = uses.use(role)
    if use is None:
        raise PlaceNameRightRefused(
            "not_offered", f"a place's name is not offered to the {role} role"
        )
    handoff = uses.handoff(use, manifest)
    expected = uses.notice(use, handoff)
    if notice != expected:
        raise PlaceNameRightRefused(
            "notice_changed",
            "what this allows has changed since it was shown; read it again before allowing it",
        )
    actor = uuid.UUID(str(actor))
    with connection.transaction():
        connection.execute("select privacy_currency_lock(%s)", (workspace_id,))
        _place_class(connection, workspace_id, entity_id)
        naming = _naming(connection, workspace_id, entity_id)
        if naming is None:
            raise PlaceNameRightRefused(
                "unnamed", "this place has no name that could be allowed to go anywhere"
            )
        if naming["stated_by"] != actor:
            raise PlaceNameRightRefused(
                "not_yours", "only the account holder who named this place can allow its name to go"
            )
        at = _now(connection)
        stored = _last_decisions(connection, workspace_id, [entity_id], at).get(entity_id, {})
        for identity in handoff.identities:
            previous = stored.get((identity, handoff.destination))
            if (
                previous is not None
                and model_state(previous.decision, notice=expected, at=at) == "allowed"
            ):
                continue
            _append(
                connection,
                workspace_id,
                entity_id=entity_id,
                identity=identity,
                destination=handoff.destination,
                previous=previous,
                event="granted",
                actor=actor,
                at=at,
                grant=(naming, expected, at + uses.term),
            )


def withdraw_place_name(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    entity_id: uuid.UUID,
    role: str,
    actor: uuid.UUID,
) -> None:
    """Stop this place's name going to any model of ``role``, from the next read on.

    Appends a withdrawal after every model of that role, at any destination, whose last decision is
    a grant, whether or not the grant still counts: a withdrawn right stays withdrawn whatever
    happens to the place afterwards. Offered or not, and named or not, a place's grants can always
    be stopped. Nothing to stop records nothing.
    """
    actor = uuid.UUID(str(actor))
    with connection.transaction():
        connection.execute("select privacy_currency_lock(%s)", (workspace_id,))
        _place_class(connection, workspace_id, entity_id)
        at = _now(connection)
        stored = _last_decisions(connection, workspace_id, [entity_id], at).get(entity_id, {})
        for (identity, destination), previous in sorted(
            stored.items(), key=lambda item: (item[0][0].model_id, item[0][1])
        ):
            if identity.role != role or previous.decision.event != "granted":
                continue
            _append(
                connection,
                workspace_id,
                entity_id=entity_id,
                identity=identity,
                destination=destination,
                previous=previous,
                event="withdrawn",
                actor=actor,
                at=at,
            )


@contextmanager
def _final_check(connection: psycopg.Connection) -> Iterator[dt.datetime]:
    """``exulanica.graph.asset_read_policy.final_check``, restated for this layer.

    ``consent`` sits below ``graph`` and may not import it, so the discipline is repeated as
    :mod:`exulanica.ingest.model_rights` repeats it: an idle connection, a read-only transaction,
    the global asset read lock, and an instant read in a separate statement so READ COMMITTED
    observes every writer that committed while this waited.
    """
    if connection.info.transaction_status.name != "IDLE":
        raise ValueError("a place name is released only on an idle connection")
    with connection.transaction():
        connection.execute("set transaction read only")
        connection.execute("select asset_read_lock()")
        yield connection.execute("select statement_timestamp() as at").fetchone()["at"]


def _released(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    handoff: ModelHandoff,
    entity_ids: Sequence[uuid.UUID] | None,
    uses: PlaceNameUses | None,
    manifest: Manifest | None,
) -> frozenset[uuid.UUID]:
    if not isinstance(handoff, ModelHandoff):
        return frozenset()
    uses = uses or load_place_name_uses()
    manifest = manifest or load_manifest()
    roles = {identity.role for identity in handoff.identities}
    use = uses.use(next(iter(roles))) if len(roles) == 1 else None
    if use is None:
        return frozenset()
    notice = uses.notice(use, uses.handoff(use, manifest))
    with _final_check(connection) as at:
        stored = _last_decisions(connection, workspace_id, entity_ids, at)
    return frozenset(
        entity_id
        for entity_id, decisions in stored.items()
        if all(
            (found := decisions.get((identity, handoff.destination))) is not None
            and model_state(found.decision, notice=notice, at=at) == "allowed"
            for identity in handoff.identities
        )
    )


def released_place_names(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    handoff: ModelHandoff,
    *,
    uses: PlaceNameUses | None = None,
    manifest: Manifest | None = None,
) -> frozenset[uuid.UUID]:
    """Every place whose name may go to every model ``handoff`` can reach, now. None by default.

    A place is in the answer only when each identity of ``handoff`` has, at its destination, a
    last decision that reads ``allowed`` against the notice the product states for that role now.
    Build ``handoff`` with :meth:`~exulanica.models.handoff.ModelHandoff.hosted` for the role the
    request goes to: the role's whole chain at the manifest's endpoint, which is what a grant
    covers. A hand-over naming a model outside that chain, another destination, or the models of
    more than one role releases nothing, and so does anything that is not a
    :class:`~exulanica.models.handoff.ModelHandoff`.

    **Call it on an idle connection.** It opens its own read-only transaction, takes the asset
    read lock, reads, and releases both before returning, and it raises ``ValueError`` on a
    connection already inside a transaction rather than hold the lock across whatever that
    transaction does next. A caller holding an open transaction resolves the released names
    before entering it, or resolves them on a fresh connection; either way once per request and
    hand-over, and never across the model call itself.
    """
    return _released(connection, workspace_id, handoff, None, uses, manifest)


def place_name_released(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    entity_id: uuid.UUID,
    handoff: ModelHandoff,
) -> bool:
    """Whether this place's name may go to every model ``handoff`` can reach, now. No by default.

    The single-place form of :func:`released_place_names`, with the same terms and the same final
    read check.
    """
    entity_id = uuid.UUID(str(entity_id))
    return entity_id in _released(connection, workspace_id, handoff, [entity_id], None, None)
