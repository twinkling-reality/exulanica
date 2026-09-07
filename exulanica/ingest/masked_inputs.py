"""Make reconstruction read the masked photograph, and refuse if it cannot prove it did.

This is the executable half of "mask before, not only after". The scene job declares, per member,
which masked derivative it will read; the worker resolves those exact artifacts, checks them
against the declaration, and rebinds the member's blob so that COLMAP, the staged scratch and the
pose receipt all name the masked bytes. A hidden person therefore never reaches feature
extraction, so they cannot become depth, points or Gaussians in the first place.

**Two of the four uses of a member's blob id must not be rebound, and getting that wrong is the
dangerous bug here.** Two are the reconstruction path -- the COLMAP frame manifest and the scratch
staging list -- and those must see the masked bytes. The other two are the deletion and tombstone
boundary, which must keep naming the original capture bytes: a purge that looked for the masked
derivative would leave the original on disk, and a tombstone check against a derivative would not
notice that the photograph itself had been withdrawn. So this module rebinds a copy and hands the
original set back beside it, rather than mutating members in place.

**A declared mask that cannot be resolved stops the job.** Not a warning and not a fallback to the
original: falling back is precisely how a person who was meant to be hidden gets reconstructed,
and it would happen on exactly the runs where something had already gone wrong.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

from exulanica.errors import PrivacyAdmissionError
from exulanica.evidence.blob import BlobId
from exulanica.ingest.person_state import region_state_for_capture
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.spine.reconstruction_jobs import ClaimedSceneJob
from exulanica.ingest.stages import stage
from exulanica.ingest.stages.intake import key_for as intake_key_for
from exulanica.ingest.stages.masked_source import masked_source_key

__all__ = [
    "MASKED_SOURCE_KIND",
    "apply_masked_sources",
    "capture_mask_is_current",
    "masked_source_declarations",
    "verify_masked_sources",
]

#: Spelled once. The stage key, the artifact kind and this constant have to agree, and a literal
#: repeated at three call sites is how they stop agreeing.
MASKED_SOURCE_KIND = "masked_source"


def masked_source_declarations(
    repository: IngestRepository, capture_ids: list[uuid.UUID]
) -> list[dict[str, Any]]:
    """The build-input block naming each member's masked derivative, or an empty list.

    Empty when nobody in the set is hidden, which is the ordinary case for a corpus with no people
    in it and keeps those builds byte-identical to the ones this change did not touch.

    ``media_type`` is carried and is not decorative: the worker derives a staged filename's
    extension from it, and a JPEG derivative of a PNG original staged as ``.png`` would be handed
    to COLMAP mislabelled.
    """
    masked = repository.current_capture_artifacts(capture_ids=capture_ids, kind=MASKED_SOURCE_KIND)
    if not masked:
        return []
    spec = stage(MASKED_SOURCE_KIND)
    return [
        {
            "capture_ref": str(capture_id),
            "artifact_ref": str(masked[capture_id].artifact_id),
            "content_sha256": masked[capture_id].content_sha256.hex(),
            "media_type": "image/jpeg",
            "stage_version": spec.version,
            "stage_params_sha256": spec.params_digest.hex(),
        }
        for capture_id in capture_ids
        if capture_id in masked
    ]


def verify_masked_sources(
    repository: IngestRepository, claimed: ClaimedSceneJob
) -> dict[uuid.UUID, tuple[BlobId, str]]:
    """Resolve the exact declared derivatives, or refuse the job.

    Re-resolving the current artifact instead would change the build after it was admitted, which
    is the same rule the point-map binding already follows. Here it matters twice over: the
    current derivative may reflect a consent decision made after this job was queued.
    """
    declared = claimed.build_inputs.get("masked_sources")
    if not declared:
        return {}
    if not isinstance(declared, list):
        raise PrivacyAdmissionError("the masked source declaration is not a list")
    wanted: dict[uuid.UUID, uuid.UUID] = {}
    expected: dict[uuid.UUID, tuple[str, str]] = {}
    for item in declared:
        if not isinstance(item, dict):
            raise PrivacyAdmissionError("a masked source declaration is not an object")
        try:
            capture_id = uuid.UUID(str(item["capture_ref"]))
            wanted[capture_id] = uuid.UUID(str(item["artifact_ref"]))
            expected[capture_id] = (str(item["content_sha256"]), str(item["media_type"]))
        except (KeyError, ValueError) as exc:
            raise PrivacyAdmissionError("a masked source declaration is incomplete") from exc
    members = {member.capture_id for member in claimed.members}
    if not set(wanted) <= members:
        raise PrivacyAdmissionError("a masked source names a capture outside this scene")
    rows = repository.exact_capture_artifacts(
        artifact_ids_by_capture=wanted, kind=MASKED_SOURCE_KIND
    )
    resolved: dict[uuid.UUID, tuple[BlobId, str]] = {}
    for capture_id, artifact_id in wanted.items():
        row = rows.get(capture_id)
        if row is None or row.artifact_id != artifact_id:
            raise PrivacyAdmissionError(
                f"the masked derivative declared for capture {capture_id} is not available; "
                "refusing rather than reconstructing the original"
            )
        digest, media_type = expected[capture_id]
        if row.content_sha256.hex() != digest:
            raise PrivacyAdmissionError(
                f"the masked derivative for capture {capture_id} is not the bytes this job "
                "was admitted with"
            )
        resolved[capture_id] = (BlobId(row.content_sha256), media_type)
    return resolved


def apply_masked_sources(repository: IngestRepository, claimed: ClaimedSceneJob) -> ClaimedSceneJob:
    """Return the job with every masked member's blob rebound to its derivative.

    A copy, never a mutation. The caller keeps the original ``claimed`` for the deletion and
    tombstone boundary; see the module docstring for why those two must not move.
    """
    resolved = verify_masked_sources(repository, claimed)
    if not resolved:
        return claimed
    members = tuple(
        dataclasses.replace(
            member,
            blob_id=resolved[member.capture_id][0],
            media_type=resolved[member.capture_id][1],
        )
        if member.capture_id in resolved
        else member
        for member in claimed.members
    )
    return dataclasses.replace(claimed, members=members)


def capture_mask_is_current(repository: IngestRepository, capture_id: uuid.UUID) -> bool:
    """Whether every person this photograph must hide is hidden by a derivative that exists NOW.

    True in two different situations and the difference matters to nobody downstream: a photograph
    with nobody to hide has nothing to be out of date, and a photograph with somebody to hide has a
    ``masked_source`` artifact under the key today's regions and consents produce. False when a
    mask is needed and the current one is missing, or was built before somebody changed their mind.

    **The key is asked for rather than compared field by field.** ``masked_source_key`` folds the
    source bytes, the confirmed region set and the resolved consent states, so "is this derivative
    current" is one lookup rather than three comparisons that could each be got wrong. A revoked
    consent moves the key, so the artifact under the old key stops being an answer instead of
    quietly remaining one.

    This does NOT assert that the derivative's bytes are in the store. The store check belongs to
    the stage that reads them and to the database trigger that refuses a point map naming a
    derivative that does not exist; repeating it here would be a second place to keep in step.
    """
    state = region_state_for_capture(repository, capture_id)
    if not state.any_masked:
        return True
    capture = repository.capture(capture_id)
    if capture is None:
        return False
    intake = repository.find_artifact(intake_key_for(capture.blob_id))
    if intake is None or intake.content_sha256 is None:
        return False
    key = masked_source_key(
        intake_sha256=intake.content_sha256,
        capture_id=capture_id,
        blob_id=capture.blob_id,
        regions=state.outlines,
        resolved=state.resolved,
    )
    current = repository.find_artifact(key)
    return current is not None and current.content_sha256 is not None
