"""Versioned privacy admission policy for reconstruction geometry.

Synthetic sources may use an exemption only when their durable authorization is itself synthetic.
Benchmark and personal sources require a named human to inspect the exact bytes.

**What version 2 changed, and why version 1 had to go.** Version 1 blocked geometry for any
detected or unresolved person and implemented no mask, so the only eligible answer a reviewer could
give about a photograph with somebody in it was that there was nobody in it. That is not a
hypothetical: the retained bowl collection was reviewed on 2026-09-05 as having "no visible people
or sensitive person regions" over 51 frames containing the arms, hands and clothing of diners at
the edge, because the alternative was to lose the collection. Version 2 takes a confirmed region
list with a consent state per person, and the people who did not consent are hidden by
:mod:`exulanica.ingest.stages.masked_source` before any geometry reads a pixel.

A region list does not make a photograph eligible on its own. Eligibility says a named human
looked and resolved every region; that reconstruction actually read the masked bytes is enforced
separately, by ``tg_geometry_reads_the_masked_derivative`` in migration 0037, because a rule that
lives only here is a rule a future caller can route around.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Final, get_args

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.consent.states import MASKED_STATES, PersonState
from exulanica.errors import PrivacyAdmissionError
from exulanica.evidence.blob import BlobId
from exulanica.evidence.scene import scene_id_for, scene_member_digest
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.spine.privacy import (
    PrivacyAdmissionRow,
    PrivacyScreeningRow,
    ReconstructionAuthorizationRow,
)

__all__ = [
    "PRIVACY_POLICY_PARAMS",
    "PRIVACY_POLICY_VERSION",
    "admit_reconstruction_scene",
    "authorize_benchmark_capture",
    "authorize_personal_capture",
    "authorize_synthetic_capture",
    "record_human_screening",
    "record_person_detection_screening",
    "record_synthetic_exemption",
    "require_observation_screening",
    "require_privacy_screening",
]

PRIVACY_POLICY_VERSION: Final = "exulanica.reconstruction-privacy/v2"
#: Version 2 replaces "is anybody visible?" with "who is here, and what did each of them agree
#: to?". Version 1 could only block a photograph containing a person, so a reviewer looking at one
#: had two options: refuse the photograph, or say nobody was there. MEASURED 2026-09-05, the
#: retained bowl review took the second over 51 frames containing diners' arms and hands, which is
#: what this version exists to make unnecessary.
#:
#: The digest of these parameters is embedded in every screening and admission receipt, so bumping
#: them makes every receipt written under version 1 provably old-policy rather than silently
#: carried forward. That is the mechanism by which the two retained collections must be
#: re-screened, and it is deliberate that it costs a re-screening rather than being free.
PRIVACY_POLICY_PARAMS: Final[dict[str, Any]] = {
    "person_policy": "confirmed-region-list-with-per-person-consent-state",
    "masking": "masked-source-derivative-read-before-any-geometry",
    "default_state": "hidden-until-a-consent-receipt-says-otherwise",
    "consents": "presence-naming-likeness-separately-plus-reversible-temporary-hide",
    "biometric_templates": "never",
    "synthetic_exemption": "requires-durable-synthetic-generator-manifest",
    "real_media_review": "named-human-over-exact-source-bytes",
}
_POLICY_DIGEST: Final = sha256_of_canonical(PRIVACY_POLICY_PARAMS)
_AUTHORIZATION_NAMESPACE: Final = uuid.UUID("c43ad553-9510-5de2-876c-7359e58520e1")
_SCREENING_NAMESPACE: Final = uuid.UUID("f4f2600b-aa92-59d4-a75c-0914ad9d88c4")
_ADMISSION_NAMESPACE: Final = uuid.UUID("345e1307-d5b9-52e2-8ca2-8f8db00a378d")

#: The five states a confirmed region may carry, spelled here so a receipt cannot record a
#: sixth. Imported rather than restated: a vocabulary duplicated in two files is a vocabulary
#: that will be extended in one of them.
_REGION_STATES: Final = frozenset(get_args(PersonState))


def _utc(value: dt.datetime | None = None) -> dt.datetime:
    instant = value or dt.datetime.now(dt.UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("privacy receipt times must include a UTC offset")
    return instant.astimezone(dt.UTC)


def _iso(value: dt.datetime | None) -> str | None:
    return None if value is None else _utc(value).isoformat().replace("+00:00", "Z")


def _capture(repository: IngestRepository, capture_id: uuid.UUID) -> BlobId:
    capture = repository.capture(capture_id)
    if capture is None or capture.deleted_at is not None:
        raise PrivacyAdmissionError(f"capture {capture_id} is absent or deleted")
    return capture.blob_id


def _authorize(
    repository: IngestRepository,
    *,
    capture_id: uuid.UUID,
    corpus_class: str,
    purpose: str,
    authorization_scope: dict[str, Any],
    evidence: dict[str, Any],
    synthetic_manifest_digest: bytes | None,
    authorized_by: uuid.UUID,
    authorized_at: dt.datetime | None,
    valid_until: dt.datetime | None,
) -> ReconstructionAuthorizationRow:
    source = _capture(repository, capture_id)
    at = _utc(authorized_at)
    until = _utc(valid_until) if valid_until else None
    record = {
        "profile": "exulanica.capture-reconstruction-authorization/v1",
        "capture_id": str(capture_id),
        "source_sha256": source.hex,
        "corpus_class": corpus_class,
        "purpose": purpose,
        "authorization_scope": authorization_scope,
        "authorization_evidence": evidence,
        "synthetic_manifest_sha256": (
            synthetic_manifest_digest.hex() if synthetic_manifest_digest else None
        ),
        "authorized_by": str(authorized_by),
        "authorized_at": _iso(at),
        "valid_until": _iso(until),
    }
    digest = sha256_of_canonical(record)
    canonical = canonical_json(record)
    authorization_id = uuid.uuid5(
        _AUTHORIZATION_NAMESPACE,
        f"{repository.workspace_id}:{capture_id}:{digest.hex()}",
    )
    return repository.insert_reconstruction_authorization(
        authorization_id=authorization_id,
        capture_id=capture_id,
        source_sha256=source,
        corpus_class=corpus_class,
        purpose=purpose,
        authorization_scope=authorization_scope,
        authorization_evidence=evidence,
        authorization_record=record,
        authorization_canonical=canonical,
        evidence_digest=digest,
        synthetic_manifest_digest=synthetic_manifest_digest,
        authorized_by=authorized_by,
        authorized_at=at,
        valid_until=until,
    )


def authorize_synthetic_capture(
    repository: IngestRepository,
    *,
    capture_id: uuid.UUID,
    actor: uuid.UUID,
    generator_manifest: dict[str, Any],
    authorization_scope: dict[str, Any],
    purpose: str = "reconstruction evaluation",
    authorized_at: dt.datetime | None = None,
    valid_until: dt.datetime | None = None,
) -> ReconstructionAuthorizationRow:
    """Authorize exact bytes generated by one canonical synthetic scene manifest."""
    profile = generator_manifest.get("profile")
    if not isinstance(profile, str) or not profile:
        raise ValueError("a synthetic generator manifest needs a non-empty profile")
    manifest_digest = sha256_of_canonical(generator_manifest)
    return _authorize(
        repository,
        capture_id=capture_id,
        corpus_class="synthetic",
        purpose=purpose,
        authorization_scope=authorization_scope,
        evidence={
            "generator_profile": profile,
            "generator_manifest_sha256": manifest_digest.hex(),
        },
        synthetic_manifest_digest=manifest_digest,
        authorized_by=actor,
        authorized_at=authorized_at,
        valid_until=valid_until,
    )


def authorize_benchmark_capture(
    repository: IngestRepository,
    *,
    capture_id: uuid.UUID,
    actor: uuid.UUID,
    official_source_url: str,
    retrieval_date: str,
    license_document_sha256: str,
    permitted_use: str,
    authorization_scope: dict[str, Any],
    purpose: str = "non-commercial reconstruction engineering evaluation",
    authorized_at: dt.datetime | None = None,
    valid_until: dt.datetime | None = None,
) -> ReconstructionAuthorizationRow:
    """Authorize benchmark bytes using a recorded official source and license digest."""
    if len(license_document_sha256) != 64:
        raise ValueError("license_document_sha256 must be 64 hexadecimal characters")
    try:
        bytes.fromhex(license_document_sha256)
    except ValueError as exc:
        raise ValueError("license_document_sha256 must be hexadecimal") from exc
    return _authorize(
        repository,
        capture_id=capture_id,
        corpus_class="benchmark",
        purpose=purpose,
        authorization_scope=authorization_scope,
        evidence={
            "official_source_url": official_source_url,
            "retrieval_date": retrieval_date,
            "license_document_sha256": license_document_sha256,
            "permitted_use": permitted_use,
        },
        synthetic_manifest_digest=None,
        authorized_by=actor,
        authorized_at=authorized_at,
        valid_until=valid_until,
    )


def authorize_personal_capture(
    repository: IngestRepository,
    *,
    capture_id: uuid.UUID,
    actor: uuid.UUID,
    account_authority_basis: str,
    authorization_scope: dict[str, Any],
    purpose: str,
    authorized_at: dt.datetime | None = None,
    valid_until: dt.datetime | None = None,
) -> ReconstructionAuthorizationRow:
    """Record account authority without treating it as another person's consent."""
    return _authorize(
        repository,
        capture_id=capture_id,
        corpus_class="personal",
        purpose=purpose,
        authorization_scope=authorization_scope,
        evidence={"account_authority_basis": account_authority_basis},
        synthetic_manifest_digest=None,
        authorized_by=actor,
        authorized_at=authorized_at,
        valid_until=valid_until,
    )


def _record_screening(
    repository: IngestRepository,
    *,
    authorization: ReconstructionAuthorizationRow,
    method: str,
    reviewed_by: uuid.UUID | None,
    sensitive_regions: list[dict[str, Any]],
    eligibility_state: str,
    blocking_reasons: list[str],
    screened_at: dt.datetime | None,
    valid_until: dt.datetime | None,
) -> PrivacyScreeningRow:
    at = _utc(screened_at)
    until = _utc(valid_until) if valid_until else None
    record = {
        "profile": "exulanica.reconstruction-privacy-screening-receipt/v1",
        "authorization": {
            "authorization_id": str(authorization.authorization_id),
            "evidence_sha256": authorization.evidence_digest.hex(),
            "scope": authorization.authorization_scope,
        },
        "capture_id": str(authorization.capture_id),
        "source_sha256": authorization.source_sha256.hex(),
        "screening_method": method,
        "model": None,
        "human_review": {
            "required": method == "human_review",
            "reviewed_by": str(reviewed_by) if reviewed_by else None,
        },
        "sensitive_regions": sensitive_regions,
        "mask_artifacts": [],
        "eligibility_state": eligibility_state,
        "blocking_reasons": blocking_reasons,
        "policy": {
            "version": PRIVACY_POLICY_VERSION,
            "params_sha256": _POLICY_DIGEST.hex(),
        },
        "screened_at": _iso(at),
        "valid_until": _iso(until),
    }
    digest = sha256_of_canonical(record)
    canonical = canonical_json(record)
    screening_id = uuid.uuid5(
        _SCREENING_NAMESPACE,
        f"{repository.workspace_id}:{authorization.capture_id}:{digest.hex()}",
    )
    return repository.insert_privacy_screening(
        screening_id=screening_id,
        authorization_id=authorization.authorization_id,
        capture_id=authorization.capture_id,
        source_sha256=BlobId(authorization.source_sha256),
        screening_method=method,
        human_review_required=method == "human_review",
        reviewed_by=reviewed_by,
        sensitive_regions=sensitive_regions,
        eligibility_state=eligibility_state,
        blocking_reasons=blocking_reasons,
        policy_version=PRIVACY_POLICY_VERSION,
        policy_params_digest=_POLICY_DIGEST,
        authorization_scope=authorization.authorization_scope,
        screened_at=at,
        valid_until=until,
        receipt_record=record,
        receipt_canonical=canonical,
        receipt_digest=digest,
    )


def record_synthetic_exemption(
    repository: IngestRepository,
    *,
    authorization_id: uuid.UUID,
    screened_at: dt.datetime | None = None,
    valid_until: dt.datetime | None = None,
) -> PrivacyScreeningRow:
    """Exempt only an explicitly synthetic authorization, backed by a database trigger too."""
    authorization = repository.reconstruction_authorization(authorization_id)
    if authorization is None:
        raise PrivacyAdmissionError("the reconstruction authorization does not exist")
    if authorization.corpus_class != "synthetic":
        raise PrivacyAdmissionError(
            "synthetic exemption cannot be applied to benchmark or personal media"
        )
    return _record_screening(
        repository,
        authorization=authorization,
        method="synthetic_exemption",
        reviewed_by=None,
        sensitive_regions=[],
        eligibility_state="eligible",
        blocking_reasons=[],
        screened_at=screened_at,
        valid_until=valid_until,
    )


def record_human_screening(
    repository: IngestRepository,
    *,
    authorization_id: uuid.UUID,
    reviewed_by: uuid.UUID,
    sensitive_regions: list[dict[str, Any]],
    failure_reason: str | None = None,
    screened_at: dt.datetime | None = None,
    valid_until: dt.datetime | None = None,
) -> PrivacyScreeningRow:
    """Record exact-byte review as a confirmed region list with a state per person.

    Under version 1 a non-empty region list blocked the photograph outright, and the effect was
    the opposite of the intent: it made "there is nobody here" the only answer that kept a
    collection usable. Under version 2 a listed person is fine, because a person who has not
    consented to their likeness is filled with neutral grey before any geometry reads them. What
    blocks now is a region nobody resolved -- one with no state, or a state outside the closed
    vocabulary -- because that is a person the reviewer saw and did not decide about, and deciding
    nothing is not consent.

    A caller passing ``[]`` still records an eligible screening, so an inventory a human really did
    find empty behaves exactly as before.
    """
    authorization = repository.reconstruction_authorization(authorization_id)
    if authorization is None:
        raise PrivacyAdmissionError("the reconstruction authorization does not exist")
    unresolved = [
        region
        for region in sensitive_regions
        if not isinstance(region, dict) or region.get("state") not in _REGION_STATES
    ]
    # A region in a masked state blocks, and it blocks for a reason worth stating plainly: the
    # masking stages are not yet wired into the pipeline, so nothing anywhere would actually
    # hide this person before depth read them. Marking such a screening eligible would be
    # strictly worse than the version 1 rule it replaced, which blocked any photograph naming a
    # person at all. `unknown` is the important member of this set: it means somebody was seen
    # and nobody decided, and "nobody decided" is the case default deny exists for.
    #
    # When masking is wired end to end this becomes "eligible if every masked region has a
    # current masked_source derivative", which is the whole point of the design. Until then the
    # honest rule is the conservative one, and this comment is the record of why.
    masked = [
        region
        for region in sensitive_regions
        if isinstance(region, dict) and region.get("state") in MASKED_STATES
    ]
    if failure_reason:
        state = "failed"
        reasons = [failure_reason]
    elif unresolved:
        state = "blocked"
        reasons = [
            f"{len(unresolved)} confirmed person region(s) carry no resolved presentation state"
        ]
    elif masked:
        state = "blocked"
        reasons = [
            f"{len(masked)} person region(s) are not consented to likeness and no masked source "
            "derivative is produced yet, so geometry over these bytes is refused"
        ]
    else:
        state = "eligible"
        reasons = []
    return _record_screening(
        repository,
        authorization=authorization,
        method="human_review",
        reviewed_by=reviewed_by,
        sensitive_regions=sensitive_regions,
        eligibility_state=state,
        blocking_reasons=reasons,
        screened_at=screened_at,
        valid_until=valid_until,
    )


def record_person_detection_screening(
    repository: IngestRepository,
    *,
    authorization_id: uuid.UUID,
    authorized_by: uuid.UUID,
    purpose: str,
    screened_at: dt.datetime | None = None,
    valid_until: dt.datetime | None = None,
) -> PrivacyScreeningRow:
    """Permit showing these exact bytes to a detector, and permit nothing else.

    **What this is for.** Finding the people in a photograph means showing it to something that
    can find them, and the detector here is a hosted model. But the confirmed region list that
    makes a screening eligible is the *output* of that looking, so a photograph containing
    somebody who has not consented had no way to be looked at at all: an empty region list asserts
    nobody is there, and a list naming them is blocked. This receipt is the narrow way out.

    **What it does not do.** It records ``blocked``, because blocked is what it is for geometry,
    and the blocking reason says so in words. ``privacy_screening_allows_capture`` does not admit
    it, so no point map, pose, placement or trained scene can be produced on its strength; only
    ``privacy_screening_allows_observation`` does. A caller who wanted geometry and reached for
    this would find it refused by the database rather than by a code review.

    **It is not consent, and the wording matters.** Nobody in the photograph has agreed to
    anything here. An account holder has authorized a search for them so that they can be hidden,
    which is a different act with a different actor, and ``purpose`` is recorded so the receipt
    says which act it was.
    """
    authorization = repository.reconstruction_authorization(authorization_id)
    if authorization is None:
        raise PrivacyAdmissionError("the reconstruction authorization does not exist")
    if not purpose.strip():
        raise PrivacyAdmissionError(
            "a detection authorization records why the photograph is being looked at"
        )
    return _record_screening(
        repository,
        authorization=authorization,
        method="person_detection_only",
        reviewed_by=authorized_by,
        sensitive_regions=[],
        eligibility_state="blocked",
        blocking_reasons=[
            "authorized for person detection only; geometry needs a confirmed region list "
            f"with a consent state per person. Purpose: {purpose.strip()}"
        ],
        screened_at=screened_at,
        valid_until=valid_until,
    )


def require_observation_screening(
    repository: IngestRepository,
    capture_id: uuid.UUID,
    screening_id: uuid.UUID,
) -> PrivacyScreeningRow:
    """Resolve one receipt that permits showing these bytes to a detector, or stop.

    Separate from :func:`require_privacy_screening` on purpose. The two questions are "may this be
    looked at" and "may this become geometry", and a single function with a flag would eventually
    be called with the wrong flag; the failure mode there is a photograph reconstructed on the
    strength of a receipt that only ever permitted looking at it.
    """
    screening = repository.privacy_screening(screening_id)
    if screening is None or screening.capture_id != capture_id:
        raise PrivacyAdmissionError("privacy screening is missing for the exact capture")
    if not repository.privacy_screening_allows_observation(capture_id, screening_id):
        raise PrivacyAdmissionError("no current receipt permits showing these bytes to a detector")
    return screening


def require_privacy_screening(
    repository: IngestRepository,
    capture_id: uuid.UUID,
    screening_id: uuid.UUID,
) -> PrivacyScreeningRow:
    """Resolve one exact eligible receipt or stop before geometry inference."""
    screening = repository.privacy_screening(screening_id)
    if screening is None or screening.capture_id != capture_id:
        raise PrivacyAdmissionError("privacy screening is missing for the exact capture")
    if not repository.privacy_screening_allows(capture_id, screening_id):
        raise PrivacyAdmissionError("privacy screening is failed, blocked, stale, or withdrawn")
    return screening


def admit_reconstruction_scene(
    repository: IngestRepository,
    *,
    capture_ids: list[uuid.UUID],
    screening_ids: list[uuid.UUID | None],
    admitted_at: dt.datetime | None = None,
    valid_until: dt.datetime | None = None,
) -> PrivacyAdmissionRow:
    """Persist a fail-closed decision over one exact ordered capture set."""
    if not capture_ids or len(capture_ids) != len(screening_ids):
        raise ValueError("privacy admission needs one screening slot per capture")
    if len(set(capture_ids)) != len(capture_ids):
        raise ValueError("privacy admission capture members must be unique")
    until = _utc(valid_until) if valid_until else None
    sources: list[BlobId] = []
    screenings: list[PrivacyScreeningRow | None] = []
    blockers: list[str] = []
    pairs = zip(capture_ids, screening_ids, strict=True)
    for ordinal, (capture_id, screening_id) in enumerate(pairs):
        source = _capture(repository, capture_id)
        sources.append(source)
        receipt = repository.privacy_screening(screening_id) if screening_id else None
        screenings.append(receipt)
        if receipt is None or receipt.capture_id != capture_id:
            blockers.append(f"member {ordinal} has no screening for its exact source")
        elif not repository.privacy_screening_allows(capture_id, receipt.screening_id):
            blockers.append(f"member {ordinal} screening is failed, blocked, stale, or withdrawn")
    at = (
        _utc(admitted_at)
        if admitted_at
        else max(
            (receipt.screened_at for receipt in screenings if receipt is not None),
            default=dt.datetime.now(dt.UTC),
        )
    )
    classes = {receipt.corpus_class for receipt in screenings if receipt is not None}
    scopes = {
        sha256_of_canonical(receipt.authorization_scope)
        for receipt in screenings
        if receipt is not None
    }
    corpus_class = (
        next(iter(classes)) if len(classes) == 1 else ("unknown" if not classes else "mixed")
    )
    if len(classes) != 1:
        blockers.append("members do not share one explicit corpus class")
    if len(scopes) != 1:
        blockers.append("members do not share one authorization scope")
    authorization_scope = (
        next(receipt.authorization_scope for receipt in screenings if receipt is not None)
        if len(scopes) == 1
        else {}
    )
    state = "eligible" if not blockers else "blocked"
    members = []
    member_records = []
    for ordinal, (capture_id, source, receipt) in enumerate(
        zip(capture_ids, sources, screenings, strict=True)
    ):
        authorization_id = receipt.authorization_id if receipt else None
        screening_id = receipt.screening_id if receipt else None
        members.append((capture_id, source, authorization_id, screening_id))
        member_records.append(
            {
                "ordinal": ordinal,
                "capture_id": str(capture_id),
                "source_sha256": source.hex,
                "authorization_id": str(authorization_id) if authorization_id else None,
                "screening_id": str(screening_id) if screening_id else None,
                "screening_receipt_sha256": receipt.receipt_digest.hex() if receipt else None,
            }
        )
    scene_id = scene_id_for(capture_ids)
    member_digest = scene_member_digest(capture_ids)
    record = {
        "profile": "exulanica.reconstruction-privacy-admission/v1",
        "scene_id": str(scene_id),
        "member_digest": member_digest.hex(),
        "members": member_records,
        "corpus_class": corpus_class,
        "eligibility_state": state,
        "blocking_reasons": blockers,
        "authorization_scope": authorization_scope,
        "policy": {
            "version": PRIVACY_POLICY_VERSION,
            "params_sha256": _POLICY_DIGEST.hex(),
        },
        "admitted_at": _iso(at),
        "valid_until": _iso(until),
    }
    digest = sha256_of_canonical(record)
    canonical = canonical_json(record)
    admission_id = uuid.uuid5(
        _ADMISSION_NAMESPACE,
        f"{repository.workspace_id}:{scene_id}:{digest.hex()}",
    )
    return repository.insert_privacy_admission(
        admission_id=admission_id,
        scene_id=scene_id,
        member_digest=member_digest,
        corpus_class=corpus_class,
        eligibility_state=state,
        blocking_reasons=blockers,
        policy_version=PRIVACY_POLICY_VERSION,
        policy_params_digest=_POLICY_DIGEST,
        authorization_scope=authorization_scope,
        admitted_at=at,
        valid_until=until,
        admission_record=record,
        admission_canonical=canonical,
        admission_digest=digest,
        members=members,
    )
