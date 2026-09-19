"""Which of an account holder's photographs a trainer may read, and what the run leaves behind.

:mod:`exulanica.ingest.model_rights` answers which model may receive a person's own photograph and
where the bytes go. It works because showing bytes to a model is a TRANSIENT act: withdraw the
right and the next read is refused. **You cannot un-train weights.** A Gaussian splat trained on
somebody's photographs of their home is a reconstruction of their home, and it persists after the
photographs are withdrawn, deleted or re-screened. So a right shaped like a model right, naming
only its inputs, would repeat in a new place the failure :mod:`exulanica.ingest.privacy` records
for privacy version 1: a rule whose only available answer is the one that loses the collection.

**This right names its inputs and binds what the run produced.** The right itself cannot name the
artefact, because at grant time the artefact does not exist. Migration 0080 records the binding at
publication instead, by trigger, so :func:`artifact_training_sources` answers "which photographs
was this artefact trained from" out of a record rather than out of somebody's memory.

**Not to be confused with migration 0039.** ``training_use_consent`` is a person-subject consenting
to their likeness travelling to a named counterparty inside an exported dataset package. It says
nothing about whether a trainer here may read the account holder's own photographs. Two questions
that share one English word, so everything here is spelled ``scene_training``.

**The destination may not be spelled ``localhost``, which is the one difference from 0073 a reader
should stop at.** The reference compute is a rented GPU VM reached over a tunnel, which is exactly
how such a machine presents itself locally, and a right recording that spelling would state that
the bytes never left this machine when they did. A genuinely local run is ``local-process``;
anything else names the host it actually reaches, through :func:`rented_host`.

**Deny by default, and checked twice, because a training run takes a long time.** Migration 0080
refuses a member insert for a training job whose captures have no current right, so a run cannot be
queued; and it refuses the artifact insert that would publish anything, so a right that was current
when the job was queued but was withdrawn during the run stops the run publishing. A withdrawal
landing mid run therefore costs the GPU seconds and leaves nothing behind.

**What a withdrawal does, and what it does not do yet.** It refuses every further read at once,
which is what :func:`require_artifact_training_right` enforces under the final read check, and it
is recorded against every artefact the right permitted. It does NOT yet enqueue destruction. That
reaches into the tombstone and purge-queue invariants of migrations 0013 and 0015 and is its own
piece of work; :func:`artifact_training_sources` and ``scene_training_artifact`` are what that work
will read. Destruction could not be synchronous in any case, since the purger is a separate process
that correctly skips bytes another live capture still holds, so the immediate refusal is not a
substitute for destruction but the thing that covers the interval before it lands.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final, Literal

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json, sha256_digest
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest.repository import IngestRepository
from exulanica.models.handoff import LOCAL_PROCESS, egress_origin

__all__ = [
    "LOCAL_PROCESS",
    "SCENE_TRAINING",
    "SCENE_TRAINING_RIGHT_PROFILE",
    "TrainingRightRefused",
    "TrainingRightRow",
    "TrainingSource",
    "artifact_training_sources",
    "canonical_training_destination",
    "grant_training_right",
    "rented_host",
    "require_artifact_training_right",
    "require_scene_training",
    "training_right",
    "training_rights_for_capture",
    "withdraw_training_right",
]

SCENE_TRAINING_RIGHT_PROFILE: Final = "exulanica.scene-training-right/v1"
SCENE_TRAINING: Final = "scene_training"
#: The build input a training job states its destination in. Read by the database gate, so a job
#: that states nothing is refused rather than defaulted.
DESTINATION_INPUT: Final = "scene_training_destination"

_RIGHT_NAMESPACE: Final = uuid.UUID("f0a1d6c2-4e37-5b8a-9c05-3d7e1b2a6f48")
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_RENTED: Final = re.compile(r"^rented-host:[a-z][a-z0-9_-]{0,31}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_PROVIDER: Final = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_INSTANCE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

#: Why a training run was refused, as a closed vocabulary a caller can branch on. ``undeclared``
#: is a job that never said where the bytes go, which is its own failure and not a missing right.
RefusalReason = Literal[
    "undeclared", "missing", "expired", "withdrawn", "lapsed", "other_destination"
]


class TrainingRightRefused(PrivacyAdmissionError):
    """No current training right covers every photograph this run would read.

    A :class:`~exulanica.errors.PrivacyAdmissionError`, so every caller that already refuses on a
    missing screening refuses on this too. ``reason`` says which term failed and ``capture_id``
    which photograph it failed for, because a run names many and a message naming none sends the
    reader to the wrong one.
    """

    def __init__(self, reason: RefusalReason, capture_id: uuid.UUID, message: str) -> None:
        super().__init__(message)
        self.reason: RefusalReason = reason
        self.capture_id = capture_id


def rented_host(provider: str, instance: str) -> str:
    """The one spelling of a rented machine: ``rented-host:<provider>/<instance>``.

    Neither half is decoration. The provider is who billed for it and the instance is the name
    that provider gave it, so a later reader can ask them what ran there. A provider that exposes
    no stable instance name is one this right cannot honestly describe, and that is a reason not to
    send somebody's photographs to it rather than a reason to invent a name.
    """
    if not isinstance(provider, str) or not _PROVIDER.fullmatch(provider):
        raise ValueError(f"rented host provider {provider!r} is not a provider key")
    if not isinstance(instance, str) or not _INSTANCE.fullmatch(instance):
        raise ValueError(f"rented host instance {instance!r} is not an instance name")
    return f"rented-host:{provider}/{instance}"


def canonical_training_destination(value: str) -> str:
    """``local-process``, a rented host, or the one spelling of the origin ``value`` names.

    A loopback address is refused outright, and the error says why rather than leaving the caller
    to discover the check constraint: a tunnel to a rented GPU presents itself at ``localhost``,
    and a right recording that would state the bytes never left this machine.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("a training right states where the bytes go")
    if value == LOCAL_PROCESS or _RENTED.fullmatch(value):
        return value
    origin = egress_origin(value)
    host = origin.split("://", 1)[1].split(":", 1)[0]
    if host == "localhost" or host == "127.0.0.1" or host.startswith("127."):
        raise ValueError(
            "a training right cannot name a loopback address: a tunnel to a rented machine looks "
            "local, so 'local-process' means this process and anything else names its real host, "
            "through exulanica.ingest.training_rights.rented_host"
        )
    return origin


def _instant(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("training right times must include a UTC offset")
    return value.astimezone(dt.UTC)


def _spelled(value: dt.datetime) -> str:
    """The one spelling of an instant in a receipt, matching ``personal_model_right_instant``."""
    return _instant(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True, slots=True)
class TrainingRightRow:
    """One stored right, as granted, with its withdrawal if there was one."""

    right_id: uuid.UUID
    capture_id: uuid.UUID
    source_sha256: bytes
    authorization_id: uuid.UUID
    operation: str
    destination: str
    purpose: str
    granted_by: uuid.UUID
    granted_at: dt.datetime
    valid_until: dt.datetime
    withdrawn_at: dt.datetime | None
    withdrawn_by: uuid.UUID | None
    receipt_sha256: bytes

    def as_reference(self) -> dict[str, Any]:
        """What a response may carry about this right: identities and terms, never the purpose."""
        return {
            "right_id": str(self.right_id),
            "capture_id": str(self.capture_id),
            "operation": self.operation,
            "destination": self.destination,
            "granted_at": _spelled(self.granted_at),
            "valid_until": _spelled(self.valid_until),
            "withdrawn": self.withdrawn_at is not None,
            "receipt_sha256": self.receipt_sha256.hex(),
        }


@dataclass(frozen=True, slots=True)
class TrainingSource:
    """One photograph a trained artefact was produced from, and whether its right still stands."""

    capture_id: uuid.UUID
    right_id: uuid.UUID
    destination: str
    withdrawn_at: dt.datetime | None
    current: bool


_COLUMNS: Final = (
    "right_id,capture_id,source_sha256,authorization_id,operation,destination,purpose,"
    "granted_by,granted_at,valid_until,withdrawn_at,withdrawn_by,receipt_sha256"
)


def _row(row: dict[str, Any]) -> TrainingRightRow:
    return TrainingRightRow(
        right_id=row["right_id"],
        capture_id=row["capture_id"],
        source_sha256=bytes(row["source_sha256"]),
        authorization_id=row["authorization_id"],
        operation=row["operation"],
        destination=row["destination"],
        purpose=row["purpose"],
        granted_by=row["granted_by"],
        granted_at=row["granted_at"],
        valid_until=row["valid_until"],
        withdrawn_at=row["withdrawn_at"],
        withdrawn_by=row["withdrawn_by"],
        receipt_sha256=bytes(row["receipt_sha256"]),
    )


def training_right(
    repository: IngestRepository, right_id: uuid.UUID
) -> TrainingRightRow | None:
    """One right by id in this workspace, withdrawn or not, or None."""
    row = repository.connection.execute(
        f"select {_COLUMNS} from scene_training_right where workspace_id=%s and right_id=%s",
        (repository.workspace_id, right_id),
    ).fetchone()
    return None if row is None else _row(row)


def training_rights_for_capture(
    repository: IngestRepository, capture_id: uuid.UUID
) -> list[tuple[TrainingRightRow, bool]]:
    """Every right recorded for a photograph, newest first, each with whether it is current now.

    Current means the same thing :func:`require_scene_training` means by it for this right's own
    destination; it is reported, and it permits nothing by being reported.
    """
    rows = repository.connection.execute(
        f"select {_COLUMNS},scene_training_right_allows(workspace_id,right_id,capture_id,"
        "destination,clock_timestamp()) as current from scene_training_right "
        "where workspace_id=%s and capture_id=%s order by granted_at desc,right_id desc",
        (repository.workspace_id, capture_id),
    ).fetchall()
    return [(_row(row), bool(row["current"])) for row in rows]


def grant_training_right(
    repository: IngestRepository,
    *,
    capture_id: uuid.UUID,
    authorization_id: uuid.UUID,
    destination: str,
    granted_by: uuid.UUID,
    purpose: str,
    valid_until: dt.datetime,
    granted_at: dt.datetime | None = None,
) -> TrainingRightRow:
    """Record that ``granted_by`` lets a trainer at ``destination`` read these exact bytes.

    The grantor must be the account holder named by the personal authority ``authorization_id``,
    which must be over this capture's exact bytes and current at ``granted_at``; the database
    refuses anything else as well. The term ends at ``valid_until`` and the right lapses earlier if
    that authority does. Recording the IDENTICAL grant twice, its instant included, returns the
    existing right; two grants a second apart are two different records and so two rights.
    """
    capture_id = uuid.UUID(str(capture_id))
    authorization_id = uuid.UUID(str(authorization_id))
    granted_by = uuid.UUID(str(granted_by))
    destination = canonical_training_destination(destination)
    if not isinstance(purpose, str) or not purpose.strip():
        raise ValueError("a training right records why the photographs may be trained on")
    purpose = purpose.strip()
    if len(purpose) > 2000 or _CONTROL.search(purpose):
        raise ValueError("a training right purpose is at most 2000 printable characters")
    connection = repository.connection
    authority = connection.execute(
        "select capture_id,source_sha256,corpus_class,authorized_by,authorized_at,valid_until,"
        "evidence_digest from capture_reconstruction_authorization "
        "where workspace_id=%s and authorization_id=%s",
        (repository.workspace_id, authorization_id),
    ).fetchone()
    capture = repository.capture(capture_id)
    if capture is None or capture.deleted_at is not None:
        raise PrivacyAdmissionError(f"capture {capture_id} is absent or deleted")
    if (
        authority is None
        or authority["corpus_class"] != "personal"
        or authority["capture_id"] != capture_id
        or bytes(authority["source_sha256"]) != capture.blob_id.digest
        or authority["authorized_by"] != granted_by
    ):
        raise PrivacyAdmissionError(
            "a training right is granted by the account holder whose personal authority covers "
            "these exact bytes"
        )
    at = _instant(
        granted_at
        if granted_at is not None
        else connection.execute("select clock_timestamp() as at").fetchone()["at"]
    )
    until = _instant(valid_until)
    if until <= at:
        raise ValueError("a training right must end after it is granted")
    if authority["authorized_at"] > at or (
        authority["valid_until"] is not None and authority["valid_until"] <= at
    ):
        raise PrivacyAdmissionError("the personal authority is not current at the grant time")
    record = {
        "profile": SCENE_TRAINING_RIGHT_PROFILE,
        "capture_id": str(capture_id),
        "source_sha256": capture.blob_id.hex,
        "authorization": {
            "authorization_id": str(authorization_id),
            "evidence_sha256": bytes(authority["evidence_digest"]).hex(),
        },
        "operation": SCENE_TRAINING,
        "destination": destination,
        "purpose": purpose,
        "granted_by": str(granted_by),
        "granted_at": _spelled(at),
        "valid_until": _spelled(until),
    }
    canonical = canonical_json(record)
    digest = sha256_digest(canonical)
    right_id = uuid.uuid5(
        _RIGHT_NAMESPACE, f"{repository.workspace_id}:{capture_id}:{digest.hex()}"
    )
    connection.execute(
        "insert into scene_training_right (workspace_id,right_id,capture_id,source_sha256,"
        "authorization_id,operation,destination,purpose,granted_by,granted_at,valid_until,"
        "receipt_record,receipt_canonical,receipt_sha256) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing",
        (
            repository.workspace_id,
            right_id,
            capture_id,
            capture.blob_id.digest,
            authorization_id,
            SCENE_TRAINING,
            destination,
            purpose,
            granted_by,
            at,
            until,
            Jsonb(record),
            canonical,
            digest,
        ),
    )
    stored = training_right(repository, right_id)
    if stored is None or stored.receipt_sha256 != digest:
        raise ValueError("an existing training right disagrees with this receipt")
    return stored


def withdraw_training_right(
    repository: IngestRepository, *, right_id: uuid.UUID, withdrawn_by: uuid.UUID
) -> TrainingRightRow:
    """End a right now. Final: a withdrawn right is never restored, only granted again.

    Withdrawing a right that is already withdrawn returns it unchanged, keeping the first
    withdrawal's actor and time.
    """
    right_id = uuid.UUID(str(right_id))
    repository.connection.execute(
        "update scene_training_right set withdrawn_at=clock_timestamp(),withdrawn_by=%s "
        "where workspace_id=%s and right_id=%s and withdrawn_at is null",
        (uuid.UUID(str(withdrawn_by)), repository.workspace_id, right_id),
    )
    stored = training_right(repository, right_id)
    if stored is None:
        raise LookupError(f"this workspace has no training right {right_id}")
    return stored


@contextmanager
def _final_check(connection: psycopg.Connection) -> Iterator[dt.datetime]:
    """``exulanica.graph.asset_read_policy.final_check``, restated here.

    ``ingest`` and ``graph`` are sibling layers and may not import each other, so the discipline is
    repeated rather than shared, exactly as :mod:`exulanica.ingest.model_rights` repeats it: an
    idle connection, a read-only transaction, the global asset read lock, and an evaluation instant
    read in a separate statement so READ COMMITTED observes every writer that committed while this
    waited. A grant or withdrawal cannot commit while this runs.
    """
    if connection.info.transaction_status.name != "IDLE":
        raise ValueError("a training run is authorized only on an idle connection")
    with connection.transaction():
        connection.execute("set transaction read only")
        connection.execute("select asset_read_lock()")
        yield connection.execute("select statement_timestamp() as at").fetchone()["at"]


_REASONS: Final[tuple[tuple[str, RefusalReason], ...]] = (
    ("must state where the bytes go", "undeclared"),
    ("was withdrawn", "withdrawn"),
    ("has expired", "expired"),
    ("is not current", "lapsed"),
    ("name another destination", "other_destination"),
)


def _reason(message: str) -> RefusalReason:
    """Which term the database said failed. Its message names one; nothing here guesses."""
    for phrase, reason in _REASONS:
        if phrase in message:
            return reason
    return "missing"


def require_scene_training(
    repository: IngestRepository, job_id: uuid.UUID
) -> tuple[TrainingRightRow, ...]:
    """Permit this training job to read its photographs now, or raise before any byte is read.

    Call it immediately before the trainer starts, not when the job was queued: a training run
    takes a long time and a right that was current an hour ago says nothing about now. Migration
    0080 refuses the publication too, so a withdrawal that lands after this returns still stops the
    run leaving anything behind; this exists so a run that cannot publish does not burn the GPU
    seconds first.

    Every member is asked under one evaluation inside the final read check. Returns the rights that
    permitted it, one per member that needed one, in member order.
    """
    connection = repository.connection
    with _final_check(connection) as at:
        rows = connection.execute(
            "select m.capture_id,"
            "scene_training_job_refusal(%(w)s,%(j)s,m.capture_id,%(at)s) as refusal,"
            "scene_training_right_current(%(w)s,m.capture_id,"
            "scene_training_destination(j.build_inputs),%(at)s) as right_id "
            "from reconstruction_scene_job j "
            "join reconstruction_scene_job_member m "
            "on m.workspace_id=j.workspace_id and m.job_id=j.job_id "
            "where j.workspace_id=%(w)s and j.job_id=%(j)s order by m.ordinal",
            {"w": repository.workspace_id, "j": job_id, "at": at},
        ).fetchall()
    if not rows:
        raise TrainingRightRefused(
            "missing", job_id, f"scene job {job_id} has no members in this workspace"
        )
    for row in rows:
        if row["refusal"] is not None:
            raise TrainingRightRefused(
                _reason(row["refusal"]),
                row["capture_id"],
                f"photograph {row['capture_id']}: {row['refusal']}",
            )
    return tuple(
        right
        for right in (
            training_right(repository, row["right_id"]) for row in rows if row["right_id"]
        )
        if right is not None
    )


def artifact_training_sources(
    repository: IngestRepository, artifact_id: uuid.UUID
) -> tuple[TrainingSource, ...]:
    """Every photograph this artefact was trained from, and whether each right still stands.

    From ``scene_training_artifact``, which migration 0080 writes by trigger at publication, so
    this is a record rather than a reconstruction of one.
    """
    rows = repository.connection.execute(
        "select * from scene_training_artifact_sources(%s,%s)",
        (repository.workspace_id, artifact_id),
    ).fetchall()
    return tuple(
        TrainingSource(
            capture_id=row["capture_id"],
            right_id=row["right_id"],
            destination=row["destination"],
            withdrawn_at=row["withdrawn_at"],
            current=bool(row["current"]),
        )
        for row in rows
    )


def require_artifact_training_right(
    repository: IngestRepository, artifact_id: uuid.UUID
) -> dt.datetime:
    """Permit one read of a trained artefact, or raise. Returns the instant it was checked at.

    This is what a withdrawal does to an artefact that already exists: every further read of it is
    refused, from the instant the withdrawal commits. Asked under the final read check, so a
    withdrawal is either seen by it or refused until it has finished.
    """
    connection = repository.connection
    with _final_check(connection) as at:
        withdrawn = connection.execute(
            "select scene_training_artifact_withdrawn(%s,%s,%s) as withdrawn",
            (repository.workspace_id, artifact_id, at),
        ).fetchone()["withdrawn"]
    if withdrawn:
        sources = artifact_training_sources(repository, artifact_id)
        gone = [str(source.capture_id) for source in sources if not source.current]
        raise TrainingRightRefused(
            "withdrawn",
            uuid.UUID(gone[0]) if gone else artifact_id,
            "this artefact was trained from photographs whose training right no longer stands "
            f"({', '.join(gone)}), so it is not read",
        )
    return at
