"""The explicit, replaceable policy that selects scene groups for pose recovery."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Protocol

from exulanica.ingest.privacy import admit_reconstruction_scene
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.scenes import SceneGroup
from exulanica.ingest.stages import stage

__all__ = [
    "ExactSetJobSelection",
    "SceneGroupPosePolicy",
    "SceneJobSelection",
    "SceneReconstructionPolicy",
    "enqueue_exact_scene_reconstruction",
    "enqueue_scene_reconstructions",
]


@dataclass(frozen=True, slots=True)
class SceneJobSelection:
    job_id: uuid.UUID
    scene_group_ordinal: int
    member_count: int
    inserted: bool


@dataclass(frozen=True, slots=True)
class ExactSetJobSelection:
    job_id: uuid.UUID
    member_count: int
    inserted: bool


class SceneReconstructionPolicy(Protocol):
    """A versioned policy that either records a selection or declines a scene group."""

    def selection_record(self, group: SceneGroup) -> dict[str, object] | None: ...


@dataclass(frozen=True, slots=True)
class SceneGroupPosePolicy:
    """Select time-ordered scene groups large enough for the current COLMAP defaults.

    The minimum of three is not a claim that three photographs are sufficient for a useful
    model. It is the measured operational floor of the current backend: its reviewed defaults
    discard two-view tracks, so two-image groups cannot produce the geometry this job consumes.
    Quality and registration remain outcomes in the pose receipt.
    """

    minimum_member_count: int = 3

    def __post_init__(self) -> None:
        if self.minimum_member_count < 3:
            raise ValueError("the current pose backend does not accept fewer than three members")

    def selection_record(self, group: SceneGroup) -> dict[str, object] | None:
        if len(group.capture_ids) < self.minimum_member_count:
            return None
        grouping = stage("scene_group")
        return {
            "profile": "exulanica.scene-group-pose-selection/v1",
            "minimum_member_count": self.minimum_member_count,
            "ordering": "scene-group-presentation-order",
            "source": {
                "kind": "scene_group",
                "group_key": group.key,
                "group_ordinal": group.ordinal,
                "stage_version": grouping.version,
                "stage_params_sha256": grouping.params_digest.hex(),
            },
            "limitations": [
                "The policy has not been validated against a representative photograph corpus.",
                "Selection does not predict registration or pose quality.",
            ],
        }


def _utc_text(value: dt.datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("exact-set authorization time must include a UTC offset")
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _enqueue_capture_set(
    repository: IngestRepository,
    capture_ids: list[uuid.UUID],
    selection_record: dict[str, object],
) -> tuple[uuid.UUID, bool] | None:
    point_maps = repository.current_capture_artifacts(
        capture_ids=capture_ids,
        kind="point_map",
    )
    if len(point_maps) != len(capture_ids):
        return None
    admission = admit_reconstruction_scene(
        repository,
        capture_ids=capture_ids,
        screening_ids=[point_maps[capture_id].privacy_screening_id for capture_id in capture_ids],
    )
    if admission.eligibility_state != "eligible":
        return None
    build_inputs = {
        "profile": "exulanica.reconstruction-scene-build-input/v1",
        "point_maps": [
            {
                "capture_ref": str(capture_id),
                "artifact_ref": str(point_maps[capture_id].artifact_id),
                "content_sha256": point_maps[capture_id].content_sha256.hex(),
            }
            for capture_id in capture_ids
        ],
        "privacy_admission": {
            "admission_ref": str(admission.admission_id),
            "admission_sha256": admission.admission_digest.hex(),
            "policy_version": admission.policy_version,
            "policy_params_sha256": admission.policy_params_digest.hex(),
        },
        "stages": [
            {
                "key": key,
                "version": stage(key).version,
                "params_sha256": stage(key).params_digest.hex(),
            }
            for key in ("scene_pose", "scene_placement", "scene_gate")
        ],
    }
    return repository.enqueue_reconstruction_scene(
        capture_ids=capture_ids,
        selection_policy=selection_record,
        privacy_admission_id=admission.admission_id,
        privacy_admission_digest=admission.admission_digest,
        build_inputs=build_inputs,
    )


def enqueue_exact_scene_reconstruction(
    repository: IngestRepository,
    capture_ids: list[uuid.UUID],
    *,
    actor: uuid.UUID,
    purpose: str,
    authorized_at: dt.datetime,
) -> ExactSetJobSelection | None:
    """Queue one operator-authorized ordered set behind the normal selection boundary.

    This interface exists for sources such as benchmarks whose honest metadata does not satisfy
    the automatic grouping policy. It does not fabricate capture time or EXIF. The actor,
    purpose, ordered capture identities, and exact source digests are part of the immutable
    selection policy whose canonical digest is stored with the job.
    """
    if len(capture_ids) < 3:
        raise ValueError("the current pose backend does not accept fewer than three members")
    if len(set(capture_ids)) != len(capture_ids):
        raise ValueError("exact-set capture members must be unique")
    if not purpose.strip():
        raise ValueError("exact-set authorization purpose must be non-empty")
    members = []
    for ordinal, capture_id in enumerate(capture_ids):
        capture = repository.capture(capture_id)
        if capture is None or capture.deleted_at is not None:
            raise ValueError(f"exact-set capture {capture_id} is absent or deleted")
        members.append(
            {
                "capture_ref": str(capture_id),
                "ordinal": ordinal,
                "source_sha256": capture.blob_id.hex,
            }
        )
    record: dict[str, object] = {
        "profile": "exulanica.operator-exact-set-pose-selection/v1",
        "authorization": {
            "actor_ref": str(actor),
            "authorized_at": _utc_text(authorized_at),
            "profile": "exulanica.operator-exact-set-authorization/v1",
            "purpose": purpose,
        },
        "members": members,
        "minimum_member_count": 3,
        "ordering": "operator-declared-exact-order",
        "source": {"kind": "operator_exact_set"},
        "limitations": [
            "Selection records authorization but does not predict registration or pose quality.",
            "The interface must not be used to fabricate missing capture metadata.",
        ],
    }
    result = _enqueue_capture_set(repository, capture_ids, record)
    if result is None:
        return None
    job_id, inserted = result
    return ExactSetJobSelection(
        job_id=job_id,
        member_count=len(capture_ids),
        inserted=inserted,
    )


def enqueue_scene_reconstructions(
    repository: IngestRepository,
    groups: list[SceneGroup],
    *,
    policy: SceneReconstructionPolicy | None = None,
) -> list[SceneJobSelection]:
    """Queue selected sets only after every member has an exact point-map input.

    Grouping runs after each derivative completion. Deferring an incomplete group means the
    final point map causes the same continuity pass to queue the build. A pose-only result can
    therefore never become the terminal answer before depth arrives.
    """
    selected_by = policy or SceneGroupPosePolicy()
    selections: list[SceneJobSelection] = []
    for group in groups:
        record = selected_by.selection_record(group)
        if record is None:
            continue
        result = _enqueue_capture_set(repository, group.capture_ids, record)
        if result is None:
            continue
        job_id, inserted = result
        selections.append(
            SceneJobSelection(
                job_id=job_id,
                scene_group_ordinal=group.ordinal,
                member_count=len(group.capture_ids),
                inserted=inserted,
            )
        )
    return selections
