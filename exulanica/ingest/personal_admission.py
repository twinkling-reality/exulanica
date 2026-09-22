"""Operator admission over exact bytes, composing the existing privacy and review policy."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any, Literal, NoReturn

from pydantic import BaseModel, ConfigDict, Field, field_validator

from exulanica.evidence.blob import BlobId
from exulanica.ingest.model_rights import (
    LOCAL_PROVIDER,
    ModelHandoff,
    ModelIdentity,
    grant_model_right,
)
from exulanica.ingest.person_review import record_region_edits, review_list
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.privacy import (
    authorize_personal_capture,
    record_human_screening,
    record_person_detection_screening,
    require_observation_screening,
    require_privacy_screening,
)
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.stages.segmentation import (
    DEPTH_ROLE,
    DETECTION_ROLE,
    SEGMENTATION_ROLE,
    local_model_role,
)
from exulanica.models import manifest as models_manifest


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def identifier(value: str) -> str:
    if str(uuid.UUID(value)) != value:
        raise ValueError("use a canonical UUID")
    return value


class Source(StrictInput):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0)
    capture_id: str | None

    @field_validator("capture_id")
    @classmethod
    def capture_identifier(cls, value: str | None) -> str | None:
        return identifier(value) if value is not None else None

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or str(path) != value or ".." in path.parts:
            raise ValueError("source path must be canonical and relative")
        return value


class Authority(StrictInput):
    account_authority_basis: str = Field(min_length=1)
    authorized_at: str
    valid_until: str


class Outline(StrictInput):
    kind: Literal["polygon"]
    points: list[list[int]]


class Edit(StrictInput):
    action: Literal["add", "confirm", "delete"]
    region_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    silhouette: Outline | None


class Manifest(StrictInput):
    profile: Literal["exulanica.personal-admission/v1"]
    actor_id: str
    workspace_id: str
    purpose: str = Field(min_length=1)
    source: Source
    authority: Authority
    operation: Literal["admit", "detect", "review", "mask", "rescreen", "retry", "geometry-check"]
    authorization_id: str | None
    screening_id: str | None
    recorded_at: str
    review: Literal["not-reviewed", "no-person", "confirmed-regions"]
    edits: list[Edit]

    @field_validator("actor_id", "workspace_id")
    @classmethod
    def canonical_uuid(cls, value: str) -> str:
        return identifier(value)

    @field_validator("authorization_id", "screening_id")
    @classmethod
    def receipt_identifier(cls, value: str | None) -> str | None:
        return identifier(value) if value is not None else None


def instant(value: str) -> dt.datetime:
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamps require a UTC offset")
    return result


def load_manifest(path: Path) -> Manifest:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def no_number(value: str) -> NoReturn:
        raise ValueError(f"non-integer JSON number refused: {value}")

    manifest = Manifest.model_validate(
        json.loads(
            path.read_text(),
            object_pairs_hook=pairs,
            parse_float=no_number,
            parse_constant=no_number,
        )
    )
    now = dt.datetime.now(dt.UTC)
    if not manifest.purpose.strip() or not manifest.authority.account_authority_basis.strip():
        raise ValueError("explicit purpose and account authority basis are required")
    start = instant(manifest.authority.authorized_at)
    end = instant(manifest.authority.valid_until)
    if not start <= now < end:
        raise ValueError("authority is missing, future or expired; obtain current authority")
    if not start <= instant(manifest.recorded_at) <= now:
        raise ValueError("recorded_at must fall between authorization and now")
    if manifest.operation == "admit":
        if manifest.source.capture_id or manifest.authorization_id or manifest.screening_id:
            raise ValueError("admit creates capture authority; do not supply receipt identifiers")
    elif not manifest.source.capture_id or not manifest.authorization_id:
        raise ValueError("this operation requires exact capture and authorization identifiers")
    if manifest.operation in {"review", "rescreen"}:
        if manifest.review == "not-reviewed":
            raise ValueError("explicit human review of exact bytes is required")
    elif manifest.edits or manifest.review != "not-reviewed":
        raise ValueError("only review/rescreen may contain human review decisions")
    return manifest


def read_source(manifest: Manifest, photo_dir: Path) -> bytes:
    path = photo_dir / manifest.source.path
    if photo_dir.is_symlink() or any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("source symbolic links are refused")
    data = path.read_bytes()
    if len(data) != manifest.source.bytes or BlobId.of_bytes(data).hex != manifest.source.sha256:
        raise ValueError("source bytes do not match the exact manifest digest and size")
    return data


def execute(manifest: Manifest, data: bytes, pipeline: PhotoIngestPipeline) -> dict:
    repository: IngestRepository = pipeline.repository
    actor = uuid.UUID(manifest.actor_id)
    if repository.workspace_id != uuid.UUID(manifest.workspace_id):
        raise ValueError("manifest workspace differs from repository workspace")
    if BlobId.of_bytes(data).hex != manifest.source.sha256 or len(data) != manifest.source.bytes:
        raise ValueError("source bytes do not match the manifest")
    at = instant(manifest.recorded_at)
    until = instant(manifest.authority.valid_until)
    outcome = None
    screening = None
    if manifest.operation == "admit":
        outcome = pipeline.ingest_intake(data, filename=manifest.source.path)
        if outcome.error:
            raise ValueError(outcome.error)
        capture_id = outcome.capture_id
        authorization = authorize_personal_capture(
            repository,
            capture_id=capture_id,
            actor=actor,
            account_authority_basis=manifest.authority.account_authority_basis,
            authorization_scope={"purpose": manifest.purpose},
            purpose=manifest.purpose,
            authorized_at=instant(manifest.authority.authorized_at),
            valid_until=until,
        )
    else:
        capture_id = uuid.UUID(manifest.source.capture_id)
        capture = repository.capture(capture_id)
        if capture is None or capture.deleted_at or capture.blob_id.hex != manifest.source.sha256:
            raise ValueError("exact capture is absent, deleted or belongs to another workspace")
        authorization = repository.reconstruction_authorization(
            uuid.UUID(manifest.authorization_id)
        )
        authority_record = repository.connection.execute(
            "select authorized_by, purpose, authorization_evidence, authorized_at "
            "from capture_reconstruction_authorization "
            "where workspace_id=%s and authorization_id=%s",
            (repository.workspace_id, uuid.UUID(manifest.authorization_id)),
        ).fetchone()
        if (
            authorization is None
            or authorization.capture_id != capture_id
            or authorization.corpus_class != "personal"
            or authority_record["authorized_by"] != actor
            or authority_record["purpose"] != manifest.purpose
            or authority_record["authorization_evidence"]
            != {"account_authority_basis": manifest.authority.account_authority_basis}
            or authority_record["authorized_at"] != instant(manifest.authority.authorized_at)
            or authorization.valid_until != until
        ):
            raise ValueError(
                "exact personal authority does not match this actor, source and purpose"
            )
    if manifest.operation == "detect":
        screening = record_person_detection_screening(
            repository,
            authorization_id=authorization.authorization_id,
            authorized_by=actor,
            purpose=manifest.purpose,
            screened_at=at,
            valid_until=until,
        )
    elif manifest.operation in {"review", "rescreen"}:
        with repository.connection.transaction():
            repository.connection.execute(
                "select current_privacy_inputs(%s,%s)",
                (repository.workspace_id, capture_id),
            )
            for edit in manifest.edits:
                # Repeating the same dated operator edit reuses its existing immutable receipt.
                exists = repository.connection.execute(
                    "select action, silhouette from person_region "
                    "where workspace_id=%s and capture_id=%s "
                    "and region_key=%s and recorded_at=%s and confirmed_by=%s",
                    (
                        repository.workspace_id,
                        capture_id,
                        bytes.fromhex(edit.region_key),
                        at,
                        actor,
                    ),
                ).fetchone()
                if exists and (
                    exists["action"]
                    != {"add": "added", "confirm": "confirmed", "delete": "deleted"}[edit.action]
                    or (
                        edit.silhouette is not None
                        and exists["silhouette"] != edit.silhouette.model_dump()
                    )
                ):
                    raise ValueError(
                        "dated edit conflicts with an existing receipt; use a new time"
                    )
                if not exists:
                    value = edit.model_dump(exclude_none=True)
                    prior = next(
                        (
                            row
                            for row in review_list(repository, capture_id)
                            if row["region_key"] == edit.region_key
                        ),
                        None,
                    )
                    if prior is not None:
                        value.update(subject_id=prior["subject_id"], shape=prior["shape"])
                    record_region_edits(
                        repository,
                        capture_id=capture_id,
                        actor=actor,
                        edits=[value],
                        recorded_at=at,
                    )
            regions = review_list(repository, capture_id)
            if manifest.review == "no-person" and regions:
                raise ValueError("no-person review conflicts with the current region inventory")
            if manifest.review == "confirmed-regions" and (
                not regions or any(r["action"] == "detected" for r in regions)
            ):
                raise ValueError("confirm every proposed region or explicitly review no-person")
            screening = record_human_screening(
                repository,
                authorization_id=authorization.authorization_id,
                reviewed_by=actor,
                sensitive_regions=regions,
                screened_at=at,
                valid_until=until,
            )
    elif manifest.operation in {"mask", "retry", "geometry-check"}:
        if manifest.screening_id is None:
            raise ValueError("an explicit persisted screening is required")
        screening = repository.privacy_screening(uuid.UUID(manifest.screening_id))
        if screening is None or screening.authorization_id != authorization.authorization_id:
            raise ValueError("screening does not belong to this authority")
    if manifest.operation in {"detect", "mask", "retry", "geometry-check"}:
        check = (
            require_privacy_screening
            if manifest.operation == "geometry-check"
            else require_observation_screening
        )
        check(repository, capture_id, screening.screening_id)
        if manifest.operation != "geometry-check":
            outcome = pipeline.ingest_derivatives(
                capture_id, privacy_screening_id=screening.screening_id
            )
            if outcome.error:
                raise ValueError(outcome.error)
    return {
        "capture_id": str(capture_id),
        "authorization_id": str(authorization.authorization_id),
        "screening_id": str(screening.screening_id) if screening else None,
        "eligibility_state": screening.eligibility_state if screening else "not-screened",
        "regions": review_list(repository, capture_id),
        "stages_run": outcome.stages_run if outcome else [],
        "stages_reused": outcome.stages_reused if outcome else [],
        "stages_unavailable": outcome.stages_unavailable if outcome else [],
        "notice": "Account authority is not subject consent. Empty inventory is not human review.",
    }


class BatchMember(StrictInput):
    capture_id: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0)
    review: Literal["not-reviewed", "no-person", "confirmed-regions"] = "not-reviewed"
    edits: list[Edit] = Field(default_factory=list)

    _capture_identifier = field_validator("capture_id")(identifier)


class ModelRightRequest(StrictInput):
    """A role whose models may process every photograph in the batch, until ``valid_until``.

    A role, never an identifier: the server resolves it against the manifest and records a right
    for each exact model the role can reach, which the response names.

    ``notice`` is the wording the account holder was shown before granting it. A role listed in
    :data:`ROLE_NOTICE` carries its exact text and nothing else; a role that is not listed carries
    none. Both halves matter. Without the first, a client could grant the depth role while showing
    a person any sentence it liked, or none; without the second, a client could attach a sentence
    of its own invention to a role whose wording the server has never approved, and the stored
    receipt would say the person read it.
    """

    role: str = Field(min_length=1, max_length=63)
    valid_until: str
    notice: str | None = None


class PersonalBatch(StrictInput):
    """An exact upload inventory; identity always comes from the authenticated session."""

    request_id: str | None = None

    _request_identifier = field_validator("request_id")(
        lambda value: identifier(value) if value is not None else None
    )

    members: list[BatchMember] = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=2000)
    authority: Authority
    recorded_at: str
    operation: Literal["detect", "review"]
    reviewed_by_name: str | None = None
    attestation: str | None = None
    #: Empty unless the account holder names roles. A receipt lets a photograph be looked at or
    #: built from and names no model, so without a right here no model receives these bytes.
    model_rights: list[ModelRightRequest] = Field(default_factory=list, max_length=8)


def role_handoff(role: str, manifest: models_manifest.Manifest | None = None) -> ModelHandoff:
    """Every model a manifest role can reach, and where its bytes go.

    A hosted role resolves to its whole chain at the manifest's endpoint; a local role, depth
    included, to its pinned checkpoint and fallback in this process. A role the manifest does not
    state is refused.
    """
    if role in {member.value for member in models_manifest.Role}:
        return ModelHandoff.hosted(manifest or models_manifest.load_manifest(), role)
    if role not in (SEGMENTATION_ROLE, DETECTION_ROLE, DEPTH_ROLE):
        raise ValueError(f"the manifest states no model role {role!r}")
    local = local_model_role(role)
    return ModelHandoff.local(
        *(
            ModelIdentity(
                provider=LOCAL_PROVIDER, role=role, model_id=pin.repo_id, revision=pin.revision
            )
            for pin in (local.primary, local.fallback)
            if pin is not None
        )
    )


HUMAN_ATTESTATION = (
    "I personally inspected every exact photograph in this inventory and reviewed all people "
    "and sensitive person regions, including any missed by the detector."
)

#: What a person is shown before letting the depth model estimate shape from their photographs.
#:
#: It says what runs, where the bytes go, what masking has already happened, what the result is
#: and is not, where it can appear, and how to stop it. It deliberately does not say "runs
#: locally" or "fully deleted": ``docs/privacy-consent-threat-model.md`` forbids both, because
#: neither is a promise this system keeps in every configuration.
DEPTH_MODEL_NOTICE = (
    "Exulanica's depth model (MoGe-2, a fixed version) will estimate the 3D shape of what each "
    "selected photo shows. It runs inside Exulanica's own processing; the photo is not sent to "
    "an outside AI service for this step. People you chose to hide are hidden before the model "
    "sees the photo. The result is an estimate from one photo: sizes and distances are "
    "approximate, and it shows only what the camera saw. It appears in a world only where you "
    "place it. You can stop this at any time: no new estimates are made and existing estimates "
    "stop being shown in your worlds."
)

#: The roles a person is shown wording for, and the exact wording. Checked the way
#: :data:`HUMAN_ATTESTATION` is: the client sends back the text it displayed, and a single
#: character of difference is a different statement and is refused.
ROLE_NOTICE: dict[str, str] = {DEPTH_ROLE: DEPTH_MODEL_NOTICE}


def admit_batch(
    body: PersonalBatch, *, actor: uuid.UUID, pipeline: PhotoIngestPipeline
) -> dict[str, Any]:
    """Validate the whole batch before atomically recording personal receipts and queueing it."""
    from exulanica.ingest import derivative_queue
    from exulanica.ingest.batch import IntakeBatch

    repository = pipeline.repository
    now = dt.datetime.now(dt.UTC)
    start = instant(body.authority.authorized_at)
    end = instant(body.authority.valid_until)
    at = instant(body.recorded_at)
    if not body.purpose.strip() or not body.authority.account_authority_basis.strip():
        raise ValueError("explicit purpose and account authority basis are required")
    if not start <= at <= now < end:
        raise ValueError("authority and recorded_at must be current, never future or expired")
    if len({member.capture_id for member in body.members}) != len(body.members):
        raise ValueError("a batch must name each capture exactly once")
    reviewing = body.operation == "review"
    if reviewing:
        if not (body.reviewed_by_name or "").strip() or body.attestation != HUMAN_ATTESTATION:
            raise ValueError(
                "an explicit named human exact-byte review and attestation are required"
            )
        if any(member.review == "not-reviewed" for member in body.members):
            raise ValueError("explicit human review is required for every photograph")
    elif (
        body.reviewed_by_name is not None
        or body.attestation is not None
        or any(member.review != "not-reviewed" or member.edits for member in body.members)
    ):
        raise ValueError("detection-only permission cannot contain human review decisions")
    # Every requested right is resolved and checked before anything is written, like the members.
    if len({request.role for request in body.model_rights}) != len(body.model_rights):
        raise ValueError("a batch names each model role at most once")
    rights = []
    for request in body.model_rights:
        until = instant(request.valid_until)
        if not now < until <= end:
            raise ValueError(
                "a model right must end in the future and no later than the authority granting it"
            )
        expected = ROLE_NOTICE.get(request.role)
        if request.notice != expected:
            raise ValueError(
                f"the {request.role} model right is granted against this server's own notice"
                if expected is not None
                else f"this server states no notice for the model role {request.role!r}"
            )
        rights.append((role_handoff(request.role), until))
    # Check all originals, including storage bytes, before the first receipt is written.
    for member in body.members:
        capture = repository.capture(uuid.UUID(member.capture_id))
        if capture is None or capture.deleted_at or capture.blob_id.hex != member.sha256:
            raise ValueError("batch does not match an available exact capture")
        data = pipeline.store.get(capture.blob_id)
        if len(data) != member.bytes or BlobId.of_bytes(data).hex != member.sha256:
            raise ValueError("source bytes do not match the exact batch digest and size")
    scope: dict[str, Any] = {"purpose": body.purpose}
    if reviewing:
        scope.update(
            reviewed_by_name=body.reviewed_by_name.strip(), human_attestation=body.attestation
        )
    if body.model_rights:
        # The wording each right was granted against, inside the authority the screening receipt
        # hashes, so what the person was shown is fixed by the same digest as the review itself.
        # The right rows carry the model, destination and term; this carries the sentence.
        scope["model_rights"] = [
            {"role": request.role, "valid_until": request.valid_until, "notice": request.notice}
            for request in sorted(body.model_rights, key=lambda request: request.role)
        ]
    results = []
    with repository.connection.transaction():
        for member in body.members:
            capture_id = uuid.UUID(member.capture_id)
            authorization = authorize_personal_capture(
                repository,
                capture_id=capture_id,
                actor=actor,
                account_authority_basis=body.authority.account_authority_basis,
                authorization_scope=scope,
                purpose=body.purpose,
                authorized_at=start,
                valid_until=end,
            )
            if reviewing:
                manifest = Manifest(
                    profile="exulanica.personal-admission/v1",
                    actor_id=str(actor),
                    workspace_id=str(repository.workspace_id),
                    purpose=body.purpose,
                    source=Source(
                        path="uploaded",
                        sha256=member.sha256,
                        bytes=member.bytes,
                        capture_id=member.capture_id,
                    ),
                    authority=body.authority,
                    operation="review",
                    authorization_id=str(authorization.authorization_id),
                    screening_id=None,
                    recorded_at=body.recorded_at,
                    review=member.review,
                    edits=member.edits,
                )
                result = execute(
                    manifest, pipeline.store.get(BlobId.from_hex(member.sha256)), pipeline
                )
            else:
                screening = record_person_detection_screening(
                    repository,
                    authorization_id=authorization.authorization_id,
                    authorized_by=actor,
                    purpose=body.purpose,
                    screened_at=at,
                    valid_until=end,
                )
                result = {
                    "capture_id": member.capture_id,
                    "authorization_id": str(authorization.authorization_id),
                    "screening_id": str(screening.screening_id),
                    "eligibility_state": screening.eligibility_state,
                    "regions": review_list(repository, capture_id),
                }
            # A separate object from the receipt above, granted by the same account holder under
            # the same authority, and only for the roles the request names.
            granted = [
                grant_model_right(
                    repository,
                    capture_id=capture_id,
                    authorization_id=authorization.authorization_id,
                    identity=identity,
                    destination=handoff.destination,
                    granted_by=actor,
                    purpose=body.purpose,
                    valid_until=until,
                    granted_at=at,
                )
                for handoff, until in rights
                for identity in handoff.identities
            ]
            result["model_right_ids"] = [str(right.right_id) for right in granted]
            result["model_rights"] = [right.as_reference() for right in granted]
            results.append(result)
        batch = IntakeBatch.open(repository, label="personal admission")
        batch.declare_size(len(body.members))
        job_id = derivative_queue.enqueue(
            repository.connection,
            repository.workspace_id,
            batch_id=batch.batch_id,
            capture_ids=[uuid.UUID(member.capture_id) for member in body.members],
        )
    return {"batch_id": str(batch.batch_id), "queued_job_id": str(job_id), "receipts": results}
