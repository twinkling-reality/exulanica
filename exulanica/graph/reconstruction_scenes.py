"""Validated multi-photograph reconstruction scenes for the graph snapshot.

The database says what a scene recorded. The object store says what can be drawn. Those answers
are deliberately separate: a missing placement object never rewrites an earned rung, and an
earned rung never causes a renderer reference to be invented. A transform crosses this boundary
only after the pose, placement and gate envelopes reproduce their digests and agree with the
immutable scene members and exact point-map artifact rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

import psycopg

from exulanica.epistemics.vocabulary import RECONSTRUCTION_SCENE_RUNG_PREDICATE
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.graph.geometry import POINT_MAP_KIND
from exulanica.graph.payload import (
    ReconstructionSceneMemberRow,
    ReconstructionSceneRow,
    SceneGeometryReferenceRow,
    ScenePointMapPlacementRow,
    SceneRecoveredCameraRow,
)
from exulanica.graph.scene_geometry import trained_geometry_row
from exulanica.reconstruction.placement import (
    PointMapInput,
    recovered_camera_records,
    validate_placement_record,
)
from exulanica.reconstruction.scene_gate import validate_scene_gate_decision
from exulanica.store.base import ContentAddressedStore

__all__ = ["reconstruction_scene_rows"]


@dataclass(frozen=True, slots=True)
class _Member:
    capture_id: uuid.UUID
    ordinal: int
    registered: bool


@dataclass(frozen=True, slots=True)
class _Claim:
    rung: int | None
    reasons: list[str]
    member_count: int
    registered_member_count: int
    gate_digest: str | None


_SCENES = """
select distinct on (s.scene_id)
       s.scene_id,
       s.member_digest,
       a.object_value,
       j.job_id,
       j.completed_at,
       pose.content_sha256 as pose_sha256,
       placement.content_sha256 as placement_sha256,
       gate.content_sha256 as gate_sha256
  from reconstruction_scene s
  left join reconstruction_scene_job j
    on j.workspace_id = s.workspace_id
   and j.job_id = s.current_job_id
   and j.status = 'succeeded'
  join assertion a
    on a.workspace_id = s.workspace_id
   and a.subject_ref ->> 'type' = 'scene'
   and a.subject_ref ->> 'id' = s.scene_id::text
   and a.status = 'active'
   and (s.current_job_id is null or a.assertion_id = j.rung_assertion_id)
  join predicate p
    on p.predicate_id = a.predicate_id
   and p.key = %s
  left join artifact pose
    on pose.workspace_id = s.workspace_id
   and pose.scene_id = s.scene_id
   and pose.artifact_id = j.pose_receipt_artifact_id
   and pose.kind = 'pose_receipt'
   and pose.purged_at is null
  left join artifact placement
    on placement.workspace_id = s.workspace_id
   and placement.scene_id = s.scene_id
   and placement.artifact_id = j.placement_artifact_id
   and placement.kind = 'point_map_placement'
   and placement.purged_at is null
  left join artifact gate
    on gate.workspace_id = s.workspace_id
   and gate.scene_id = s.scene_id
   and gate.artifact_id = j.gate_artifact_id
   and gate.kind = 'scene_gate_receipt'
   and gate.purged_at is null
 where s.workspace_id = %s
   and not tombstone_blocks_scene(s.workspace_id, s.scene_id)
 order by s.scene_id, a.asserted_at desc, a.assertion_id desc,
          j.completed_at desc nulls last, j.job_id desc
"""


def reconstruction_scene_rows(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    store: ContentAddressedStore | None,
) -> list[ReconstructionSceneRow]:
    """Return live scene claims, exposing placements only when their receipt chain verifies."""
    rows = connection.execute(_SCENES, (RECONSTRUCTION_SCENE_RUNG_PREDICATE, workspace)).fetchall()
    return [_scene_row(connection, workspace, row, store) for row in rows]


def _scene_row(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    row: dict[str, Any],
    store: ContentAddressedStore | None,
) -> ReconstructionSceneRow:
    scene_id = row["scene_id"]
    members = _members(connection, workspace, scene_id, row["job_id"])
    claim = _claim(row["object_value"], members)
    pose_digest = _hex(row["pose_sha256"])
    placement_digest = _hex(row["placement_sha256"])

    if (
        store is None
        or pose_digest is None
        or placement_digest is None
        or row["gate_sha256"] is None
    ):
        return _fallback(
            scene_id,
            bytes(row["member_digest"]).hex(),
            claim,
            members,
            pose_digest,
            placement_digest,
            "missing",
            "unavailable",
            "The scene receipts are not available to this graph reader.",
        )
    try:
        pose_bytes = store.get(BlobId(bytes(row["pose_sha256"])))
        placement_bytes = store.get(BlobId(bytes(row["placement_sha256"])))
        gate_bytes = store.get(BlobId(bytes(row["gate_sha256"])))
    except BlobNotFoundError:
        return _fallback(
            scene_id,
            bytes(row["member_digest"]).hex(),
            claim,
            members,
            pose_digest,
            placement_digest,
            "missing",
            "bytes_missing",
            "A durable scene receipt is missing from object storage.",
        )
    except IntegrityError:
        return _fallback(
            scene_id,
            bytes(row["member_digest"]).hex(),
            claim,
            members,
            pose_digest,
            placement_digest,
            "invalid",
            "invalid",
            "A durable scene receipt failed its content digest.",
        )

    try:
        decision = validate_scene_gate_decision(gate_bytes)
        if not _gate_agrees(decision, claim, pose_digest, placement_digest, members):
            raise ValueError("the scene gate disagrees with the durable scene claim")
        point_maps, artifacts = _point_maps_from_placement(
            connection, workspace, scene_id, placement_bytes, store
        )
        placement = validate_placement_record(
            placement_bytes,
            expected_scene_ref=str(scene_id),
            pose_receipt=pose_bytes,
            member_capture_refs=[str(member.capture_id) for member in members],
            point_maps=point_maps,
            allow_unavailable_bytes=True,
        )
        cameras = recovered_camera_records(pose_bytes)
    except (KeyError, TypeError, ValueError):
        return _fallback(
            scene_id,
            bytes(row["member_digest"]).hex(),
            claim,
            members,
            pose_digest,
            placement_digest,
            "invalid",
            "invalid",
            "The pose, placement and gate records do not reproduce one consistent scene.",
        )

    placed = {member.capture_ref: member for member in placement.placed}
    excluded = {member.capture_ref: member.reason for member in placement.excluded}
    output_members: list[ReconstructionSceneMemberRow] = []
    available_count = 0
    for member in members:
        capture_ref = str(member.capture_id)
        recovered_camera = (
            SceneRecoveredCameraRow(**cameras[capture_ref]) if capture_ref in cameras else None
        )
        placed_member = placed.get(capture_ref)
        if placed_member is None:
            output_members.append(
                ReconstructionSceneMemberRow(
                    capture_id=member.capture_id,
                    ordinal=member.ordinal,
                    registered=member.registered,
                    placement=None,
                    exclusion_reason=excluded[capture_ref],
                    recovered_camera=recovered_camera,
                )
            )
            continue
        artifact = artifacts[capture_ref]
        digest = BlobId.from_hex(placed_member.point_map_content_sha256)
        available = store.exists(digest)
        if available:
            available_count += 1
        output_members.append(
            ReconstructionSceneMemberRow(
                capture_id=member.capture_id,
                ordinal=member.ordinal,
                registered=member.registered,
                placement=ScenePointMapPlacementRow(
                    artifact_id=uuid.UUID(placed_member.point_map_artifact_ref),
                    content_sha256=placed_member.point_map_content_sha256,
                    container=artifact["container"],
                    scene_from_opm_row_major=list(placed_member.scene_from_opm),
                    local_units_to_scene_units=placed_member.local_units_to_scene_units,
                    scale_status=placed_member.scale_status,
                    state="available" if available else "bytes_missing",
                    reference=(
                        SceneGeometryReferenceRow(
                            href=f"/geometry/{placed_member.point_map_artifact_ref}",
                            authorization="workspace-bearer",
                            content_sha256=placed_member.point_map_content_sha256,
                            byte_size=int(artifact["byte_size"]),
                        )
                        if available
                        else None
                    ),
                ),
                exclusion_reason=None,
                recovered_camera=recovered_camera,
            )
        )

    placed_count = sum(member.registered for member in members)
    if available_count == placed_count and available_count > 0:
        placement_state: Literal["available", "partial", "bytes_missing"] = "available"
    elif available_count > 0:
        placement_state = "partial"
    else:
        placement_state = "bytes_missing"
    substrate: Literal["posed_point_maps", "source_photographs", "gaussian_splats"] = (
        "posed_point_maps" if available_count else "source_photographs"
    )
    displayed_rung = max(claim.rung or 4, 3) if available_count else 4
    display_reasons = list(claim.reasons)
    if placement_state == "partial":
        display_reasons.append(
            "Some posed point maps are unavailable; the remaining verified maps are displayed."
        )
    if available_count and claim.rung is not None and claim.rung < 3:
        display_reasons.append(
            "This client displays posed point maps and has no supported rung-1 or rung-2 substrate."
        )
    if not available_count:
        display_reasons.append(
            "No verified posed point map bytes are available, so source photographs are displayed."
        )
    trained = trained_geometry_row(connection, workspace, scene_id, pose_digest, decision, store)
    if trained is not None and trained.state == "available":
        substrate = "gaussian_splats"
        displayed_rung = max(claim.rung or 4, 3)
        display_reasons = list(claim.reasons)
    elif any(receipt.kind == "splat" and receipt.accepted for receipt in decision.receipts):
        display_reasons.append(
            "Trained scene geometry is unavailable; verified fallback content is shown."
        )
    return ReconstructionSceneRow(
        scene_id=scene_id,
        member_digest=bytes(row["member_digest"]).hex(),
        pose_receipt_sha256=pose_digest,
        placement_receipt_sha256=placement_digest,
        gate_digest=claim.gate_digest,
        recorded_rung=claim.rung,
        recorded_reasons=claim.reasons,
        displayed_rung=displayed_rung,
        display_reasons=display_reasons,
        member_count=len(members),
        registered_member_count=sum(member.registered for member in members),
        receipt_state="available",
        placement_state=placement_state,
        rendering_substrate=substrate,
        trained_geometry=trained,
        members=output_members,
    )


def _members(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    job_id: uuid.UUID | None,
) -> list[_Member]:
    if job_id is None:
        rows = connection.execute(
            "select capture_id,ordinal,registered from reconstruction_scene_member "
            "where workspace_id=%s and scene_id=%s order by ordinal,capture_id",
            (workspace, scene_id),
        ).fetchall()
    else:
        rows = connection.execute(
            "select capture_id,ordinal,registered from reconstruction_scene_build_member "
            "where workspace_id=%s and job_id=%s order by ordinal,capture_id",
            (workspace, job_id),
        ).fetchall()
    return [
        _Member(row["capture_id"], int(row["ordinal"]), row["registered"] is True) for row in rows
    ]


def _claim(value: object, members: list[_Member]) -> _Claim:
    fallback = _Claim(None, [], len(members), sum(member.registered for member in members), None)
    if not isinstance(value, dict):
        return fallback
    rung = value.get("rung")
    reasons = value.get("reasons")
    member_count = value.get("member_count")
    registered_count = value.get("registered_member_count")
    gate_digest = value.get("gate_digest")
    if (
        isinstance(rung, bool)
        or rung not in (1, 2, 3, 4)
        or not isinstance(reasons, list)
        or any(not isinstance(reason, str) for reason in reasons)
        or isinstance(member_count, bool)
        or not isinstance(member_count, int)
        or isinstance(registered_count, bool)
        or not isinstance(registered_count, int)
        or not isinstance(gate_digest, str)
    ):
        return fallback
    return _Claim(rung, list(reasons), member_count, registered_count, gate_digest)


def _gate_agrees(
    decision: Any,
    claim: _Claim,
    pose_digest: str,
    placement_digest: str,
    members: list[_Member],
) -> bool:
    receipts = {receipt.kind: receipt.sha256 for receipt in decision.receipts}
    return bool(
        claim.rung == decision.rung
        and claim.reasons == list(decision.reasons)
        and claim.member_count == decision.member_count == len(members)
        and claim.registered_member_count
        == decision.registered_member_count
        == sum(member.registered for member in members)
        and claim.gate_digest == decision.digest
        and receipts.get("pose") == pose_digest
        and receipts.get("placement") == placement_digest
    )


def _point_maps_from_placement(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    placement_bytes: bytes,
    store: ContentAddressedStore,
) -> tuple[dict[str, PointMapInput], dict[str, dict[str, Any]]]:
    import json

    raw = json.loads(placement_bytes)
    placed = raw["placement"]["point_map_inputs"]
    if not isinstance(placed, list):
        raise ValueError("the placement member list is malformed")
    inputs: dict[str, PointMapInput] = {}
    artifacts: dict[str, dict[str, Any]] = {}
    for item in placed:
        if not isinstance(item, dict):
            raise ValueError("a placement member is malformed")
        capture_ref = str(item.get("capture_ref", ""))
        artifact_ref = str(item.get("artifact_ref", ""))
        content_sha256 = str(item.get("content_sha256", ""))
        capture_id = uuid.UUID(capture_ref)
        artifact_id = uuid.UUID(artifact_ref)
        content_digest = bytes.fromhex(content_sha256)
        row = connection.execute(
            "select a.artifact_id,a.byte_size,sd.params->>'container' as container "
            "from artifact a join capture c on c.workspace_id=a.workspace_id "
            "and c.capture_id=%s and c.blob_sha256=a.source_blob_sha256 "
            "left join stage_definition sd on sd.stage_key=a.stage_key "
            "and sd.stage_version=a.stage_version and sd.params_digest=a.params_digest "
            "where a.workspace_id=%s and a.artifact_id=%s and a.kind=%s "
            "and a.content_sha256=%s and a.byte_size is not null and a.purged_at is null "
            "and not tombstone_blocks_capture(a.workspace_id,c.capture_id)",
            (capture_id, workspace, artifact_id, POINT_MAP_KIND, content_digest),
        ).fetchone()
        if row is None:
            raise ValueError(f"scene {scene_id} references an unavailable point-map artifact")
        try:
            content = store.get(BlobId(content_digest))
        except (BlobNotFoundError, IntegrityError):
            content = None
        inputs[capture_ref] = PointMapInput(capture_ref, artifact_ref, content_sha256, content)
        artifacts[capture_ref] = row
    return inputs, artifacts


def _fallback(
    scene_id: uuid.UUID,
    member_digest: str,
    claim: _Claim,
    members: list[_Member],
    pose_digest: str | None,
    placement_digest: str | None,
    receipt_state: Literal["missing", "invalid"],
    placement_state: Literal["bytes_missing", "unavailable", "invalid"],
    reason: str,
) -> ReconstructionSceneRow:
    reasons = list(claim.reasons)
    reasons.append(reason)
    return ReconstructionSceneRow(
        scene_id=scene_id,
        member_digest=member_digest,
        pose_receipt_sha256=pose_digest,
        placement_receipt_sha256=placement_digest,
        gate_digest=claim.gate_digest,
        recorded_rung=claim.rung,
        recorded_reasons=claim.reasons,
        displayed_rung=4,
        display_reasons=reasons,
        member_count=len(members),
        registered_member_count=sum(member.registered for member in members),
        receipt_state=receipt_state,
        placement_state=placement_state,
        rendering_substrate="source_photographs",
        members=[
            ReconstructionSceneMemberRow(
                capture_id=member.capture_id,
                ordinal=member.ordinal,
                registered=member.registered,
                placement=None,
                exclusion_reason=(
                    "pose-not-registered" if not member.registered else "placement-unavailable"
                ),
            )
            for member in members
        ],
    )


def _hex(value: object) -> str | None:
    return bytes(value).hex() if value is not None else None
