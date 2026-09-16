"""Which model may receive a person's own photograph, and where the bytes may go.

:mod:`exulanica.ingest.privacy` answers two questions about a photograph: may it be looked at, and
may it become geometry. Neither says who does the looking. A ``person_detection_only`` receipt
authorizes showing the exact bytes to a detector and names no model, no provider and no
destination, so a receipt recorded for one model authorized every other one, local or hosted, and
the geometry receipt depth and segmentation read has the same gap. Licensed environment sources
have carried a ``model_processing`` operation right since migration 0048, rechecked at the moment
of every read. Personal photographs carried nothing equivalent. This module is that right.

**A right is its own object, not a flag on a screening.** It names the exact capture and its
bytes, the operation, the model as the manifest states it (provider, role, identifier and full
revision, where one exists), the destination the bytes travel to, the account holder who granted
it under which personal authority, when, until when, and its withdrawal. A screening receipt is not
a model right and a model right is not a screening: :func:`require_model_right` requires both, and
merging them into one answer is the mistake ``privacy.py`` already explains, a check that will
eventually be asked the wrong question.

**Deny by default.** Every model read goes through :func:`require_model_right`. It refuses unless
each model the bytes can reach is named by a current, unwithdrawn right for this capture and this
destination. The only captures that need no right are those screened under a synthetic or
benchmark authority that no account holder has also claimed as personal; a capture anybody has
authorized as personal stays personal whichever receipt is presented. Captures screened before
this existed have no right, and nothing here or in migration 0073 invents one.

**Hosted models carry no revision.** Token Factory exposes none for serverless endpoints, and
:meth:`exulanica.models.manifest.ModelSpec.model_ref` omits the field rather than inventing it, so a
hosted right names the provider, role and identifier and the exact origin the egress allowlist
would have to declare. A role with a fallback can send the same bytes to either model, so a hosted
hand-over names the whole chain and needs a right for each member. A local checkpoint is always
named by its full commit, and its destination is this process.

**Checked at the moment of the read.** The right is resolved first, then everything is asked again
inside the final read check that the environment and graph read paths use: the global asset read
lock, a read-only transaction, one evaluation instant. A grant or withdrawal cannot commit while
that check runs, so a withdrawal is either seen by it or refused until it has finished. The lock is
released before the bytes are handed over; a model call can take minutes and holds nothing.
"""

from __future__ import annotations

import datetime as dt
import re
import urllib.parse
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final, Literal

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json, sha256_digest
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest.repository import IngestRepository
from exulanica.models.egress import EgressError, parse_egress_allowlist
from exulanica.models.manifest import PROVIDER, Manifest, Role

__all__ = [
    "LOCAL_PROCESS",
    "LOCAL_PROVIDER",
    "MODEL_PROCESSING",
    "MODEL_RIGHT_PROFILE",
    "ModelHandoff",
    "ModelIdentity",
    "ModelRightDecision",
    "ModelRightRefused",
    "ModelRightRow",
    "RefusalReason",
    "egress_origin",
    "grant_model_right",
    "model_right",
    "model_rights_for_capture",
    "require_model_right",
    "withdraw_model_right",
]

MODEL_RIGHT_PROFILE: Final = "exulanica.personal-model-right/v1"
MODEL_PROCESSING: Final = "model_processing"
#: The provider of a checkpoint this codebase loads and runs itself.
LOCAL_PROVIDER: Final = "local"
#: The destination of bytes that never leave this process.
LOCAL_PROCESS: Final = "local-process"

_RIGHT_NAMESPACE: Final = uuid.UUID("a9452e94-7ca5-5d7a-b45b-276369e0c801")
_NAME: Final = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_MODEL_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_REVISION: Final = re.compile(r"^[0-9a-f]{40}$")
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")

#: Why a hand-over was refused, as a closed vocabulary a caller can branch on.
RefusalReason = Literal[
    "undeclared",
    "missing",
    "expired",
    "withdrawn",
    "lapsed",
    "other_model",
    "other_destination",
    "changed",
]


class ModelRightRefused(PrivacyAdmissionError):
    """No current personal model right names this model and this destination for these bytes.

    A :class:`~exulanica.errors.PrivacyAdmissionError`, so every caller that already refuses on a
    missing screening refuses on this too. ``reason`` says which term failed.
    """

    def __init__(self, reason: RefusalReason, message: str) -> None:
        super().__init__(message)
        self.reason: RefusalReason = reason


def _instant(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("model right times must include a UTC offset")
    return value.astimezone(dt.UTC)


def _spelled(value: dt.datetime) -> str:
    """The one spelling of an instant in a receipt, matching ``personal_model_right_instant``."""
    return _instant(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def egress_origin(url: str) -> str:
    """The origin the egress allowlist would have to declare for ``url``, in its one spelling.

    Parsed by :func:`exulanica.models.egress.parse_egress_allowlist`, so anything that list would
    refuse to declare, an address, userinfo, plain http to a remote host, is refused here too, and
    a default port is written the way :class:`~exulanica.models.egress.Origin` writes it.
    """
    if not isinstance(url, str) or not url:
        raise ValueError("a destination must be a URL or an origin")
    parts = urllib.parse.urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"{url!r} names no origin")
    try:
        allowlist = parse_egress_allowlist([f"{parts.scheme}://{parts.netloc}"])
    except EgressError as exc:
        raise ValueError(
            f"{url!r} names no origin the egress allowlist could declare: {exc}"
        ) from exc
    (origin,) = allowlist.origins
    return str(origin)


def _destination(value: str) -> str:
    return value if value == LOCAL_PROCESS else egress_origin(value)


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """One model as the manifest states it.

    ``revision`` is a full lowercase commit for a local checkpoint and ``None`` for a hosted model
    whose provider exposes none. A hosted identity with ``None`` never matches a right that names a
    revision, and the reverse, so the two cannot stand in for each other.
    """

    provider: str
    role: str
    model_id: str
    revision: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not _NAME.fullmatch(self.provider):
            raise ValueError(f"model provider {self.provider!r} is not a provider key")
        if not isinstance(self.role, str) or not _NAME.fullmatch(self.role):
            raise ValueError(f"model role {self.role!r} is not a role name")
        if not isinstance(self.model_id, str) or not _MODEL_ID.fullmatch(self.model_id):
            raise ValueError(f"model identifier {self.model_id!r} is not an identifier")
        if self.revision is not None and (
            not isinstance(self.revision, str) or not _REVISION.fullmatch(self.revision)
        ):
            raise ValueError(f"{self.model_id} revision must be a full lowercase commit")
        if self.provider == LOCAL_PROVIDER and self.revision is None:
            raise ValueError(f"local checkpoint {self.model_id} must be pinned to a full commit")

    @classmethod
    def local(cls, role: str, model_id: str, revision: str) -> ModelIdentity:
        return cls(provider=LOCAL_PROVIDER, role=role, model_id=model_id, revision=revision)

    @property
    def ref(self) -> str:
        """``model@revision`` when pinned, the bare identifier otherwise."""
        return self.model_id if self.revision is None else f"{self.model_id}@{self.revision}"

    def as_record(self) -> dict[str, str | None]:
        return {
            "provider": self.provider,
            "role": self.role,
            "model_id": self.model_id,
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class ModelHandoff:
    """Every model one hand-over can reach, and the one destination the bytes travel to.

    A hand-over needs a right for each identity. ``destination`` is :data:`LOCAL_PROCESS` or an
    origin, normalised on construction; bytes that stay in this process can only reach local
    checkpoints.
    """

    identities: tuple[ModelIdentity, ...]
    destination: str

    def __post_init__(self) -> None:
        identities = tuple(self.identities)
        if not identities or not all(isinstance(item, ModelIdentity) for item in identities):
            raise ValueError("a model hand-over names at least one model identity")
        if len(set(identities)) != len(identities):
            raise ValueError("a model hand-over names each model once")
        destination = _destination(self.destination)
        if destination == LOCAL_PROCESS and any(
            item.provider != LOCAL_PROVIDER for item in identities
        ):
            raise ValueError("bytes kept in this process can only reach local checkpoints")
        object.__setattr__(self, "identities", identities)
        object.__setattr__(self, "destination", destination)

    @classmethod
    def local(cls, *identities: ModelIdentity) -> ModelHandoff:
        return cls(identities=identities, destination=LOCAL_PROCESS)

    @classmethod
    def hosted(cls, manifest: Manifest, role: Role | str) -> ModelHandoff:
        """A manifest role's whole chain, sent to the manifest's endpoint.

        The chain rather than the primary: the client falls back on a withdrawn identifier, so
        either model can receive the same request, and a right for one is not a right for both.
        """
        binding = manifest[role]
        return cls(
            identities=tuple(
                ModelIdentity(
                    provider=PROVIDER,
                    role=str(binding.role),
                    model_id=spec.model_id,
                    revision=None,
                )
                for spec in binding.chain
            ),
            destination=egress_origin(manifest.base_url),
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "models": [identity.as_record() for identity in self.identities],
            "destination": self.destination,
        }


@dataclass(frozen=True, slots=True)
class ModelRightRow:
    """One stored right, as granted, with its withdrawal if there was one."""

    right_id: uuid.UUID
    capture_id: uuid.UUID
    source_sha256: bytes
    authorization_id: uuid.UUID
    operation: str
    identity: ModelIdentity
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
            "model": self.identity.as_record(),
            "destination": self.destination,
            "granted_at": _spelled(self.granted_at),
            "valid_until": _spelled(self.valid_until),
            "withdrawn": self.withdrawn_at is not None,
            "receipt_sha256": self.receipt_sha256.hex(),
        }


@dataclass(frozen=True, slots=True)
class ModelRightDecision:
    """What permitted one hand-over, as the final read check saw it.

    ``required`` is false only for an exempt capture, and ``rights`` is then empty. Otherwise it
    holds one right per identity, in the hand-over's order.
    """

    capture_id: uuid.UUID
    screening_id: uuid.UUID
    handoff: ModelHandoff | None
    required: bool
    rights: tuple[ModelRightRow, ...]
    checked_at: dt.datetime


_COLUMNS: Final = (
    "right_id,capture_id,source_sha256,authorization_id,operation,model_provider,model_role,"
    "model_id,model_revision,destination,purpose,granted_by,granted_at,valid_until,"
    "withdrawn_at,withdrawn_by,receipt_sha256"
)


def _row(row: dict[str, Any]) -> ModelRightRow:
    return ModelRightRow(
        right_id=row["right_id"],
        capture_id=row["capture_id"],
        source_sha256=bytes(row["source_sha256"]),
        authorization_id=row["authorization_id"],
        operation=row["operation"],
        identity=ModelIdentity(
            provider=row["model_provider"],
            role=row["model_role"],
            model_id=row["model_id"],
            revision=row["model_revision"],
        ),
        destination=row["destination"],
        purpose=row["purpose"],
        granted_by=row["granted_by"],
        granted_at=row["granted_at"],
        valid_until=row["valid_until"],
        withdrawn_at=row["withdrawn_at"],
        withdrawn_by=row["withdrawn_by"],
        receipt_sha256=bytes(row["receipt_sha256"]),
    )


def model_right(repository: IngestRepository, right_id: uuid.UUID) -> ModelRightRow | None:
    """One right by id in this workspace, withdrawn or not, or None."""
    row = repository.connection.execute(
        f"select {_COLUMNS} from personal_model_right where workspace_id=%s and right_id=%s",
        (repository.workspace_id, right_id),
    ).fetchone()
    return None if row is None else _row(row)


def model_rights_for_capture(
    repository: IngestRepository, capture_id: uuid.UUID
) -> list[tuple[ModelRightRow, bool]]:
    """Every right recorded for a capture, newest first, each with whether it is current now.

    Current means the same thing :func:`require_model_right` means by it for this right's own
    model and destination; it is reported, and it permits nothing by being reported.
    """
    rows = repository.connection.execute(
        f"select {_COLUMNS},personal_model_right_allows(workspace_id,right_id,capture_id,"
        "model_provider,model_role,model_id,model_revision,destination,clock_timestamp()) "
        "as current from personal_model_right where workspace_id=%s and capture_id=%s "
        "order by granted_at desc,right_id desc",
        (repository.workspace_id, capture_id),
    ).fetchall()
    return [(_row(row), bool(row["current"])) for row in rows]


def grant_model_right(
    repository: IngestRepository,
    *,
    capture_id: uuid.UUID,
    authorization_id: uuid.UUID,
    identity: ModelIdentity,
    destination: str,
    granted_by: uuid.UUID,
    purpose: str,
    valid_until: dt.datetime,
    granted_at: dt.datetime | None = None,
) -> ModelRightRow:
    """Record that ``granted_by`` lets ``identity`` process these exact bytes at ``destination``.

    The grantor must be the account holder named by the personal authority ``authorization_id``,
    which must be over this capture's exact bytes and current at ``granted_at``; the database
    refuses anything else as well. The term ends at ``valid_until`` and the right lapses earlier if
    that authority does. Recording the same grant twice returns the existing right.
    """
    destination = _destination(destination)
    if destination == LOCAL_PROCESS and identity.provider != LOCAL_PROVIDER:
        raise ValueError("bytes kept in this process can only reach a local checkpoint")
    if not isinstance(purpose, str) or not purpose.strip():
        raise ValueError("a model right records why the photograph may be processed")
    purpose = purpose.strip()
    if len(purpose) > 2000 or _CONTROL.search(purpose):
        raise ValueError("a model right purpose is at most 2000 printable characters")
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
            "a model right is granted by the account holder whose personal authority covers "
            "these exact bytes"
        )
    at = _instant(
        granted_at
        if granted_at is not None
        else connection.execute("select clock_timestamp() as at").fetchone()["at"]
    )
    until = _instant(valid_until)
    if until <= at:
        raise ValueError("a model right must end after it is granted")
    if authority["authorized_at"] > at or (
        authority["valid_until"] is not None and authority["valid_until"] <= at
    ):
        raise PrivacyAdmissionError("the personal authority is not current at the grant time")
    record = {
        "profile": MODEL_RIGHT_PROFILE,
        "capture_id": str(capture_id),
        "source_sha256": capture.blob_id.hex,
        "authorization": {
            "authorization_id": str(authorization_id),
            "evidence_sha256": bytes(authority["evidence_digest"]).hex(),
        },
        "operation": MODEL_PROCESSING,
        "model": identity.as_record(),
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
        "insert into personal_model_right (workspace_id,right_id,capture_id,source_sha256,"
        "authorization_id,operation,model_provider,model_role,model_id,model_revision,"
        "destination,purpose,granted_by,granted_at,valid_until,receipt_record,"
        "receipt_canonical,receipt_sha256) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing",
        (
            repository.workspace_id,
            right_id,
            capture_id,
            capture.blob_id.digest,
            authorization_id,
            MODEL_PROCESSING,
            identity.provider,
            identity.role,
            identity.model_id,
            identity.revision,
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
    stored = model_right(repository, right_id)
    if stored is None or stored.receipt_sha256 != digest:
        raise ValueError("an existing model right disagrees with this receipt")
    return stored


def withdraw_model_right(
    repository: IngestRepository, *, right_id: uuid.UUID, withdrawn_by: uuid.UUID
) -> ModelRightRow:
    """End a right now. Final: a withdrawn right is never restored, only granted again.

    Withdrawing a right that is already withdrawn returns it unchanged, keeping the first
    withdrawal's actor and time.
    """
    repository.connection.execute(
        "update personal_model_right set withdrawn_at=clock_timestamp(),withdrawn_by=%s "
        "where workspace_id=%s and right_id=%s and withdrawn_at is null",
        (withdrawn_by, repository.workspace_id, right_id),
    )
    stored = model_right(repository, right_id)
    if stored is None:
        raise LookupError(f"this workspace has no model right {right_id}")
    return stored


@contextmanager
def _final_check(connection: psycopg.Connection) -> Iterator[dt.datetime]:
    """``exulanica.graph.asset_read_policy.final_check``, restated here.

    ``ingest`` and ``graph`` are sibling layers and may not import each other, so the discipline is
    repeated rather than shared: an idle connection, a read-only transaction, the global asset read
    lock, and an evaluation instant read in a separate statement so READ COMMITTED observes every
    writer that committed while this waited. Nothing is read from the store under it.
    """
    if connection.info.transaction_status.name != "IDLE":
        raise ValueError("a model hand-over is authorized only on an idle connection")
    with connection.transaction():
        connection.execute("set transaction read only")
        connection.execute("select asset_read_lock()")
        yield connection.execute("select statement_timestamp() as at").fetchone()["at"]


def _refusal(
    repository: IngestRepository,
    capture_id: uuid.UUID,
    identity: ModelIdentity,
    destination: str,
    at: dt.datetime,
) -> ModelRightRefused:
    """Say which term failed, from the rights this capture does have. Refuses in every branch."""
    rows = repository.connection.execute(
        f"select {_COLUMNS} from personal_model_right where workspace_id=%s and capture_id=%s "
        "order by granted_at desc,right_id desc",
        (repository.workspace_id, capture_id),
    ).fetchall()
    rights = [_row(row) for row in rows]
    named = f"{identity.provider} {identity.role} model {identity.ref} at {destination}"
    exact = [r for r in rights if r.identity == identity and r.destination == destination]
    if exact:
        if all(r.withdrawn_at is not None for r in exact):
            return ModelRightRefused(
                "withdrawn", f"the model right for {named} over this photograph was withdrawn"
            )
        if all(r.withdrawn_at is not None or r.valid_until <= at for r in exact):
            return ModelRightRefused(
                "expired", f"the model right for {named} over this photograph has expired"
            )
        return ModelRightRefused(
            "lapsed",
            f"the model right for {named} is not current: its personal authority lapsed, the "
            "photograph changed, or its term has not begun",
        )
    if any(r.identity == identity for r in rights):
        return ModelRightRefused(
            "other_destination",
            f"this photograph's model rights for {identity.ref} name another destination, not "
            f"{destination}",
        )
    revisions = sorted(
        {
            str(r.identity.revision)
            for r in rights
            if (r.identity.provider, r.identity.role, r.identity.model_id)
            == (identity.provider, identity.role, identity.model_id)
        }
    )
    if revisions:
        return ModelRightRefused(
            "other_model",
            f"this photograph's model rights for {identity.model_id} name another revision "
            f"({', '.join(revisions)}); none names {named}",
        )
    if rights:
        return ModelRightRefused(
            "other_model",
            f"this photograph's model rights name other models; none names {named}",
        )
    return ModelRightRefused("missing", f"no model right lets {named} process this photograph")


def _candidate(
    repository: IngestRepository,
    capture_id: uuid.UUID,
    identity: ModelIdentity,
    destination: str,
) -> uuid.UUID | None:
    """The right that names exactly this model and destination: the current one, else the newest.

    Resolution only. Whether the candidate permits anything is decided under the final read check,
    and a candidate that is withdrawn or expired is returned so that check can say so.
    """
    row = repository.connection.execute(
        "select coalesce(personal_model_right_current(%(w)s,%(c)s,%(p)s,%(r)s,%(m)s,%(v)s,%(d)s,"
        "clock_timestamp()),(select right_id from personal_model_right where workspace_id=%(w)s "
        "and capture_id=%(c)s and model_provider=%(p)s and model_role=%(r)s and model_id=%(m)s "
        "and model_revision is not distinct from %(v)s and destination=%(d)s "
        "order by granted_at desc,right_id desc limit 1)) as right_id",
        {
            "w": repository.workspace_id,
            "c": capture_id,
            "p": identity.provider,
            "r": identity.role,
            "m": identity.model_id,
            "v": identity.revision,
            "d": destination,
        },
    ).fetchone()
    return row["right_id"]


def require_model_right(
    repository: IngestRepository,
    capture_id: uuid.UUID,
    screening_id: uuid.UUID,
    handoff: ModelHandoff | None,
) -> ModelRightDecision:
    """Permit one hand-over of this capture's bytes to ``handoff``, or raise before any byte goes.

    Call it immediately before the model receives the bytes, after they are read and verified:
    it is the final check, and anything done between it and the call is done after the check.
    ``handoff`` is ``None`` when a caller cannot state which model it is calling or where the
    bytes go; that is refused whenever a right is required.

    The right for each identity is resolved first, and then everything is decided in one
    evaluation under the final read check. Two things must hold there. The screening
    ``screening_id`` must still permit these bytes to be looked at, which is the least any model
    read needs; the geometry question stays with
    :func:`~exulanica.ingest.privacy.require_privacy_screening`, which geometry callers still ask
    first. And unless the capture is exempt, every identity in ``handoff`` must be named, with
    this destination, by a current right. Raises
    :class:`~exulanica.errors.PrivacyAdmissionError` for the screening and
    :class:`ModelRightRefused` for the right.
    """
    connection = repository.connection
    screening = repository.privacy_screening(screening_id)
    if screening is None or screening.capture_id != capture_id:
        raise PrivacyAdmissionError("privacy screening is missing for the exact capture")
    identities: Sequence[ModelIdentity] = handoff.identities if handoff is not None else ()
    resolved = [
        _candidate(repository, capture_id, identity, handoff.destination)
        for identity in identities
        if handoff is not None
    ]

    with _final_check(connection) as at:
        checked = connection.execute(
            "select asset_observation_allows(%(w)s,%(c)s,%(s)s,%(at)s) as observed,"
            "personal_model_right_required(%(w)s,%(c)s,%(s)s) as required,"
            "array(select r.right_id is not null and personal_model_right_allows(%(w)s,"
            "r.right_id,%(c)s,r.provider,r.role,r.model_id,r.revision,%(d)s,%(at)s) "
            "from unnest(%(rights)s::uuid[],%(providers)s::text[],%(roles)s::text[],"
            "%(models)s::text[],%(revisions)s::text[]) with ordinality "
            "as r(right_id,provider,role,model_id,revision,position) "
            "order by r.position) as allowed",
            {
                "w": repository.workspace_id,
                "c": capture_id,
                "s": screening_id,
                "at": at,
                "d": handoff.destination if handoff is not None else None,
                "rights": resolved,
                "providers": [identity.provider for identity in identities],
                "roles": [identity.role for identity in identities],
                "models": [identity.model_id for identity in identities],
                "revisions": [identity.revision for identity in identities],
            },
        ).fetchone()

    if not checked["observed"]:
        raise PrivacyAdmissionError(
            "no current receipt permits showing these bytes to a model at the moment of the read"
        )
    # Unknown is required. Only an explicit exemption, evaluated here, spares a capture a right.
    required = checked["required"] is not False
    if required and handoff is None:
        raise ModelRightRefused(
            "undeclared",
            "this model does not state which model it is or where the bytes go, so no right can "
            "name it and a personal photograph is not sent to it",
        )
    if required:
        for identity, allowed in zip(identities, checked["allowed"], strict=True):
            if not allowed:
                raise _refusal(repository, capture_id, identity, handoff.destination, at)
    rights: tuple[ModelRightRow, ...] = ()
    if required:
        rights = tuple(
            row
            for row in (model_right(repository, right_id) for right_id in resolved if right_id)
            if row is not None
        )
    return ModelRightDecision(
        capture_id=capture_id,
        screening_id=screening_id,
        handoff=handoff,
        required=required,
        rights=rights,
        checked_at=at,
    )
