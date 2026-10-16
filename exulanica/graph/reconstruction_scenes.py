"""Validated multi-photograph reconstruction scenes for the graph snapshot.

The database says what a scene recorded. The object store says what can be drawn. Those answers
are deliberately separate: a missing placement object never rewrites an earned rung, and an
earned rung never causes a renderer reference to be invented. A transform crosses this boundary
only after the pose, placement and gate envelopes reproduce their digests and agree with the
immutable scene members and exact point-map artifact rows.

The persisted scene projection and the validated placement memo, which spare a scene row its
rebuild, are :mod:`exulanica.graph.reconstruction_scenes_placement`'s, and the scene segments read
is :mod:`exulanica.graph.reconstruction_scenes_segments`'s. This module builds the scene rows and
imports the public names of both back.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

import psycopg

from exulanica.epistemics.vocabulary import RECONSTRUCTION_SCENE_RUNG_PREDICATE
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.graph.asset_read_policy import evaluation_time, image_source, point_allowed
from exulanica.graph.generated_geometry import generated_geometry_rows
from exulanica.graph.geometry import POINT_MAP_KIND
from exulanica.graph.payload import (
    ReconstructionSceneMemberRow,
    ReconstructionSceneRow,
    SceneGeometryReferenceRow,
    ScenePointMapPlacementRow,
    SceneRecoveredCameraRow,
    SceneStandpointExclusionRow,
    SceneStandpointPlacementRow,
    SceneStandpointRow,
    SceneUnposedPhotographRow,
    SceneUnposedPointMapRow,
)
from exulanica.graph.person_regions import (
    hidden_people,
    person_regions_for_captures,
    review_states_for_captures,
)
from exulanica.graph.reconstruction_scenes_placement import (
    SCENE_PROJECTION_KIND as SCENE_PROJECTION_KIND,
)
from exulanica.graph.reconstruction_scenes_placement import (
    _memo_get,
    _memo_put,
    _MemoKey,
    _Outcome,
    _PlacedMember,
    _point_map_bytes,
    _point_maps_verify,
    _PointMapRef,
    _projected,
    _verifies,
)
from exulanica.graph.reconstruction_scenes_placement import (
    clear_placement_memo as clear_placement_memo,
)
from exulanica.graph.reconstruction_scenes_placement import (
    placement_memo_members as placement_memo_members,
)
from exulanica.graph.reconstruction_scenes_placement import (
    placement_memo_size as placement_memo_size,
)
from exulanica.graph.reconstruction_scenes_segments import (
    OBJECT_MASK_KIND as OBJECT_MASK_KIND,
)
from exulanica.graph.reconstruction_scenes_segments import (
    SCENE_SEGMENTS_KIND as SCENE_SEGMENTS_KIND,
)
from exulanica.graph.reconstruction_scenes_segments import (
    SceneSegmentsRead as SceneSegmentsRead,
)
from exulanica.graph.reconstruction_scenes_segments import (
    SegmentsState as SegmentsState,
)
from exulanica.graph.reconstruction_scenes_segments import _hex
from exulanica.graph.reconstruction_scenes_segments import (
    scene_segments_artifacts_live as scene_segments_artifacts_live,
)
from exulanica.graph.reconstruction_scenes_segments import (
    scene_segments_read as scene_segments_read,
)
from exulanica.graph.scene_geometry import trained_geometry_row
from exulanica.reconstruction.placement import (
    PlacementRecord,
    PointMapInput,
    recovered_camera_records,
    validate_placement_record,
)
from exulanica.reconstruction.scene_gate import validate_scene_gate_decision
from exulanica.reconstruction.standpoint_record import (
    PARTS_PER_MILLION,
    STANDPOINT_KIND,
    StandpointRecordError,
    member_refusal,
    parse_standpoint_record,
    scene_from_opm_row_major,
)
from exulanica.store.base import ContentAddressedStore

__all__ = [
    "OBJECT_MASK_KIND",
    "SCENE_PROJECTION_KIND",
    "SCENE_SEGMENTS_KIND",
    "SceneSegmentsRead",
    "clear_placement_memo",
    "placement_memo_members",
    "placement_memo_size",
    "reconstruction_scene_rows",
    "scene_segments_artifacts_live",
    "scene_segments_read",
]


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
       gate.content_sha256 as gate_sha256,
       projection.digests as projection_digests
  from reconstruction_scene s
  cross join (select %s::uuid as retained_job_id) requested
  left join reconstruction_scene_job j
    on j.workspace_id = s.workspace_id
   and j.job_id = coalesce(requested.retained_job_id,s.current_job_id)
   and j.status = 'succeeded'
  join assertion a
    on a.workspace_id = s.workspace_id
   and a.subject_ref ->> 'type' = 'scene'
   and a.subject_ref ->> 'id' = s.scene_id::text
   and ((requested.retained_job_id is null and a.status = 'active'
         and (s.current_job_id is null or a.assertion_id = j.rung_assertion_id))
     or (requested.retained_job_id is not null and a.status in ('active','superseded')
         and a.assertion_id = j.rung_assertion_id))
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
  -- The projection has no column on the job row to be joined through, unlike the three receipts
  -- above, so the newest few live ones for the scene are offered and the reader proves or refuses
  -- each from its own bindings.
  --
  -- Several rather than one, and this is the whole reason: nothing in `exulanica.ingest` ever sets
  -- `artifact.superseded_by`, so every projection a scene has ever had stays live. A rebuild is
  -- safe on its own, because its projection is the newest. A BACKFILL that runs after a rebuild
  -- and projects the superseded job is not: with `limit 1` it would win on `created_at`, fail its
  -- bindings, and silently cost that scene the fast path on every cold process from then on, with
  -- nothing in the response saying so. `scripts/backfill_scene_projections.py` refuses a job that
  -- is not the scene's current one for the same reason; this is the half that does not depend on
  -- every writer remembering. Four is chosen against the corpus, where a scene has one; the cost
  -- of the extra candidates is at most three more reads of a small object, only on a memo miss.
  --
  -- Aggregated rather than joined directly so a scene with several does not multiply its row.
  left join lateral (
    select array_agg(newest.content_sha256) as digests
      from (
        select projection.content_sha256
          from artifact projection
         where projection.workspace_id = s.workspace_id
           and projection.scene_id = s.scene_id
           and projection.kind = %s
           and projection.purged_at is null
           and not projection.needs_repair
           and projection.content_sha256 is not null
           and projection.byte_size is not null
         order by projection.created_at desc, projection.artifact_id desc
         limit 4
      ) newest
  ) projection on true
 where s.workspace_id = %s
   and (%s::uuid is null or s.scene_id = %s::uuid)
   and not tombstone_blocks_scene(s.workspace_id, s.scene_id)
   and (requested.retained_job_id is null or exists (
     select 1 from assertion build join predicate bp on bp.predicate_id=build.predicate_id
     where build.workspace_id=s.workspace_id and build.status='active'
       and bp.key='reconstruction_scene_build_rung_is'
       and build.subject_ref->>'type'='scene'
       and build.subject_ref->>'id'=s.scene_id::text
       and build.subject_ref->>'job_id'=j.job_id::text
       and build.object_value-'job_id'=a.object_value))
 order by s.scene_id, a.asserted_at desc, a.assertion_id desc,
          j.completed_at desc nulls last, j.job_id desc
"""


def reconstruction_scene_rows(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    store: ContentAddressedStore | None,
    *,
    scene_id: uuid.UUID | None = None,
    retained_job_id: uuid.UUID | None = None,
) -> list[ReconstructionSceneRow]:
    """Return live scene claims, exposing placements only when their receipt chain verifies.

    ``scene_id`` narrows the read to one scene. It exists because the World Read API serves one
    scene per request, and building every scene in the workspace to answer for one means reading
    and validating every pose, placement and gate receipt in the store each time. The filter is in
    the query rather than applied to the result so the receipts of the other scenes are never
    fetched. Passing None keeps the whole-workspace read the graph snapshot needs.
    """
    rows = connection.execute(
        _SCENES,
        (
            retained_job_id,
            RECONSTRUCTION_SCENE_RUNG_PREDICATE,
            SCENE_PROJECTION_KIND,
            workspace,
            scene_id,
            scene_id,
        ),
    ).fetchall()
    return [
        _scene_row(connection, workspace, row, store, retained_job_id=retained_job_id)
        for row in rows
    ]


def _scene_row(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    row: dict[str, Any],
    store: ContentAddressedStore | None,
    *,
    retained_job_id: uuid.UUID | None = None,
) -> ReconstructionSceneRow:
    scene_id = row["scene_id"]
    members = _members(connection, workspace, scene_id, row["job_id"])
    claim = _claim(row["object_value"], members)
    capture_ids = [member.capture_id for member in members]
    people = person_regions_for_captures(connection, workspace, capture_ids)
    review_state = review_states_for_captures(connection, workspace, capture_ids)
    hidden_count, masked_members = hidden_people(people)
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
    pose_blob = BlobId(bytes(row["pose_sha256"]))
    try:
        # The pose receipt is the largest object a scene owns and is wanted only when the memo
        # below misses, so its presence is established here, first, and its bytes are read there.
        # First so that a double fault still reports what the unmemoised reader reported, which
        # fetched the pose before the other two.
        pose_present = store.exists(pose_blob)
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
    if not pose_present:
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

    try:
        decision = validate_scene_gate_decision(gate_bytes)
        if not _gate_agrees(decision, claim, pose_digest, placement_digest, members):
            raise ValueError("the scene gate disagrees with the durable scene claim")
        # The artifact rows carry `purged_at` and the tombstone predicate, so they are read live on
        # every request and never enter the memo.
        references, artifacts = _point_map_references(
            connection, workspace, scene_id, placement_bytes
        )
        member_refs = tuple(str(member.capture_id) for member in members)
        present = tuple(
            store.exists(BlobId.from_hex(reference.content_sha256)) for reference in references
        )
        # The offered projections are part of the key, and this is not decoration. Without them,
        # an operator who purges a projection or flags it `needs_repair` because it is wrong stops
        # it being OFFERED, so a fresh process rebuilds, while every already running worker keeps
        # serving the value it filed under an otherwise identical key. There is no TTL and nothing
        # outside tests calls `clear_placement_memo`, so the entry would outlive the revocation for
        # the life of the process. With them, revoking a projection changes the key and the next
        # read misses and rebuilds. A scene with no projection has an empty tuple here, so this
        # costs a rebuild-derived entry nothing.
        # Hex rather than raw bytes, like the three receipt digests above it: the memo is asserted
        # to hold no `bytes` anywhere, which is how it is kept from ever holding a point map. And
        # SORTED, because `array_agg` over an ordered subquery fixes the set but not the array
        # order, and a key that moved with the planner would miss for no reason.
        offered = tuple(sorted(bytes(item).hex() for item in (row["projection_digests"] or ())))
        key: _MemoKey = (
            str(workspace),
            str(scene_id),
            pose_digest,
            placement_digest,
            _hex(row["gate_sha256"]) or "",
            member_refs,
            tuple(references),
            present,
            offered,
        )
        memoised = _memo_get(key)
        if memoised is not None:
            outcome, cameras = memoised
        else:
            # A projection is served only for a scene whose every point map is present AND
            # reproduces its digest, and that is established the only way it can be: by reading
            # the bytes through the store, which re-hashes them.
            #
            # MEASURED 2026-09-10 on the 210 member volcanic scene: reading and hashing all
            # 780.3 MB is 0.385 s of a 0.889 s cold route body, and `json.loads` of its
            # 107,742,795 byte pose receipt alone is 1.439 s. Hashing was never what made the
            # cold read 48 seconds. `validate_opm` walking 19,493,182 points in Python and
            # `fit_point_map_scale` running once per member were, and those are exactly what a
            # projection replaces. So the verification is kept: giving it up would buy about
            # four tenths of a second and would mean the graph advertising a `/geometry`
            # reference for bytes it never checked.
            #
            # The bytes are read and dropped rather than kept, because the projection path has no
            # use for them. Peak memory here is one point map instead of all of them.
            #
            # The bindings are proved FIRST and the bytes verified only afterwards. The two are
            # independent: `_projected` reads the projection object and the scene row, never a
            # point map. Verifying first would mean a scene whose projection fails its bindings
            # read and hashed all 780.3 MB for a verdict that was then thrown away, and the
            # rebuild read them again. This way a refused projection costs one small object read,
            # so the claim in `reconstruction_scenes_placement.py`, that a refused projection is
            # never worse than no projection, is true rather than nearly true.
            projected = _projected(
                store,
                row["projection_digests"],
                scene_id=scene_id,
                pose_digest=pose_digest,
                placement_digest=placement_digest,
                gate_digest=_hex(row["gate_sha256"]) or "",
                member_refs=member_refs,
                references=references,
            )
            if projected is not None and not (
                _verifies(store, pose_blob) and _point_maps_verify(store, references)
            ):
                projected = None
            if projected is not None:
                outcome, cameras = projected
                _memo_put(key, projected)
            else:
                pose_bytes = store.get(pose_blob)
                reads = {
                    reference.capture_ref: _point_map_bytes(store, reference.content_sha256)
                    for reference in references
                }
                point_maps = {
                    reference.capture_ref: PointMapInput(
                        reference.capture_ref,
                        reference.artifact_ref,
                        reference.content_sha256,
                        reads[reference.capture_ref].content,
                    )
                    for reference in references
                }
                placement = validate_placement_record(
                    placement_bytes,
                    expected_scene_ref=str(scene_id),
                    pose_receipt=pose_bytes,
                    member_capture_refs=list(member_refs),
                    point_maps=point_maps,
                    allow_unavailable_bytes=True,
                )
                outcome = _outcome_from_record(placement)
                cameras = recovered_camera_records(pose_bytes)
                # A record built from a blob that failed its digest is not cached. `store.exists`
                # cannot tell a rotted object from a sound one, so caching this would make the key
                # identical before and after a repair and the degraded answer would outlive it.
                if not any(read.digest_failed for read in reads.values()):
                    _memo_put(key, (outcome, cameras))
    except BlobNotFoundError:
        # A purge between the presence check above and the read below. BlobNotFoundError is a
        # KeyError, so without its own arm here it would reach the handler beneath and be reported
        # as an inconsistent receipt chain rather than as the missing bytes it is.
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

    placed = outcome.placed
    excluded = outcome.excluded
    output_members: list[ReconstructionSceneMemberRow] = []
    available_count = 0
    withheld_count = 0
    unposed_count = 0
    unposed_withheld_count = 0
    # The pose recovered no photograph at all. Not "nothing was placed": a pose that registered
    # members can still place none, because the gate refused it or its point-map bytes are gone,
    # and those keep their recorded meaning.
    nothing_registered = not any(member.registered for member in members)
    # Permission is deliberately outside the placement memo. A retained transform can remain
    # current while its point-map screening, capture or person consent stops authorising delivery.
    # Evaluate one fresh read time for this response, exactly as the ordinary geometry descriptor
    # list does, and never let the memo retain an earlier permission answer.
    viewed_at = evaluation_time(connection)
    # A scene pose placed nothing may have a measured standpoint arrangement instead of the
    # client's unmeasured one. Read under the same live checks, at the same evaluation time.
    standpoint, standpoint_placements = (
        _standpoint(connection, workspace, scene_id, members, references, store, viewed_at)
        if nothing_registered
        else (None, {})
    )
    joined_standpoint = standpoint is not None and standpoint.state == "joined"
    for member in members:
        capture_ref = str(member.capture_id)
        recovered_camera = (
            SceneRecoveredCameraRow(**cameras[capture_ref]) if capture_ref in cameras else None
        )
        placed_member = placed.get(capture_ref)
        if placed_member is None:
            # A joined arrangement is drawn alone. A member outside it opens as a photograph,
            # because an unmeasured panel beside measured ones would borrow their authority.
            in_arrangement = capture_ref in standpoint_placements
            unposed = (
                _unposed_point_map(
                    connection, workspace, viewed_at, references, artifacts, capture_ref, store
                )
                if nothing_registered and (in_arrangement or not joined_standpoint)
                else None
            )
            if unposed is not None and unposed.state == "available":
                unposed_count += 1
            elif unposed is not None and unposed.state == "unavailable":
                unposed_withheld_count += 1
            output_members.append(
                ReconstructionSceneMemberRow(
                    capture_id=member.capture_id,
                    ordinal=member.ordinal,
                    registered=member.registered,
                    placement=None,
                    unposed_point_map=unposed,
                    exclusion_reason=excluded[capture_ref],
                    person_regions=people.get(capture_ref, []),
                    person_review_state=review_state.get(capture_ref, "unscreened"),
                    recovered_camera=recovered_camera,
                    standpoint_placement=(
                        standpoint_placements.get(capture_ref)
                        if unposed is not None and unposed.state == "available"
                        else None
                    ),
                )
            )
            continue
        artifact = artifacts[capture_ref]
        digest = BlobId.from_hex(placed_member.point_map_content_sha256)
        present = store.exists(digest)
        allowed = point_allowed(
            connection,
            workspace,
            uuid.UUID(placed_member.point_map_artifact_ref),
            viewed_at,
        )
        available = present and allowed
        if available:
            available_count += 1
        elif present:
            withheld_count += 1
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
                    state=(
                        "available" if available else "unavailable" if present else "bytes_missing"
                    ),
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
                unposed_point_map=None,
                exclusion_reason=None,
                person_regions=people.get(capture_ref, []),
                person_review_state=review_state.get(capture_ref, "unscreened"),
                recovered_camera=recovered_camera,
                standpoint_placement=None,
            )
        )

    placed_count = sum(member.registered for member in members)
    if available_count == placed_count and available_count > 0:
        placement_state: Literal[
            "available", "partial", "none_placed", "bytes_missing", "unavailable"
        ] = "available"
    elif available_count > 0:
        placement_state = "partial"
    elif nothing_registered:
        # The pose recovered no photograph, which is a fact about the pose and not about storage:
        # every point map can be present and verified while none of them has a position.
        placement_state = "none_placed"
    elif withheld_count > 0:
        placement_state = "unavailable"
    else:
        placement_state = "bytes_missing"
    substrate: Literal[
        "posed_point_maps", "unposed_point_maps", "source_photographs", "gaussian_splats"
    ] = (
        "posed_point_maps"
        if available_count
        else "unposed_point_maps"
        if unposed_count
        else "source_photographs"
    )
    # Rung 3 by the product specification's own definition: per-image monocular point maps, "no
    # poses required ... on a derived path where they do not" exist. The recorded rung is the
    # scene gate's receipt and is left exactly as recorded; what changes is what can be shown.
    displayed_rung = max(claim.rung or 4, 3) if available_count else 3 if unposed_count else 4
    display_reasons = list(claim.reasons)
    if not available_count and unposed_count:
        # The gate's sentence is about POSED rung 3 and is true; beside a displayed rung 3 it
        # would read as a contradiction, so it is restated precisely rather than dropped.
        display_reasons = [
            reason for reason in display_reasons if reason != _POSED_RUNG_THREE_WITHHELD
        ]
        if joined_standpoint and standpoint is not None:
            display_reasons.append(
                "No photograph's position was recovered, so the recorded rung stays 4. "
                f"{standpoint.joined_member_count} of the {standpoint.member_count} photographs "
                "are joined where they were taken: the turn between them is measured from the "
                "photographs themselves, and each keeps its own estimated depth, at approximate "
                "size. Rung 3 needs no pose."
            )
            if standpoint.excluded:
                display_reasons.append(
                    f"{len(standpoint.excluded)} photograph"
                    f"{'s do' if len(standpoint.excluded) != 1 else ' does'} not join the others "
                    "and open as photographs."
                )
        else:
            display_reasons.append(
                "No photograph's position was recovered, so the recorded rung stays 4. Each "
                "photograph's own depth is shown unplaced, in an arrangement that is not "
                "measured: rung 3 needs no pose."
            )
            if standpoint is not None and standpoint.state in _STANDPOINT_WITHHELD:
                display_reasons.append(_STANDPOINT_WITHHELD[standpoint.state])
    if placement_state == "partial":
        display_reasons.append(
            "Some posed point maps are unavailable; the remaining verified maps are displayed."
        )
    elif placement_state == "unavailable":
        display_reasons.append(
            "Current access policy withholds the posed point maps, so source photographs are "
            "displayed."
        )
    if available_count and claim.rung is not None and claim.rung < 3:
        display_reasons.append(
            "This client displays posed point maps and has no supported rung-1 or rung-2 substrate."
        )
    if not available_count and not unposed_count and unposed_withheld_count:
        display_reasons.append(
            "Current access policy withholds each photograph's depth, so source photographs are "
            "displayed."
        )
    elif not available_count and not unposed_count and not withheld_count:
        display_reasons.append(
            "No photograph's depth is available to show, so source photographs are displayed."
            if nothing_registered
            else "No verified posed point map bytes are available, so source photographs are "
            "displayed."
        )
    trained = trained_geometry_row(
        connection,
        workspace,
        scene_id,
        pose_digest,
        decision,
        store,
        retained_job_id=retained_job_id,
    )
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
        hidden_person_count=hidden_count,
        masked_member_count=masked_members,
        trained_geometry=trained,
        members=output_members,
        generated_geometry=generated_geometry_rows(connection, workspace, scene_id, store),
        standpoint=standpoint,
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


def _outcome_from_record(placement: PlacementRecord) -> _Outcome:
    """Reduce a rebuilt placement to what the scene row emits, so both paths return one shape."""
    return _Outcome(
        placed={
            member.capture_ref: _PlacedMember(
                point_map_artifact_ref=member.point_map_artifact_ref,
                point_map_content_sha256=member.point_map_content_sha256,
                scene_from_opm=tuple(member.scene_from_opm),
                local_units_to_scene_units=member.local_units_to_scene_units,
                scale_status=member.scale_status,
            )
            for member in placement.placed
        },
        excluded={member.capture_ref: member.reason for member in placement.excluded},
    )


#: The scene gate's sentence when no member was placed. Matched exactly so that restating it beside
#: an unposed rung 3 cannot silently stop happening if the gate's wording changes: a test pins the
#: two together.
_POSED_RUNG_THREE_WITHHELD: Final = (
    "Rung 3 withheld: no member point map has a recovered placement."
)


def _unposed_point_map(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    viewed_at: dt.datetime,
    references: tuple[_PointMapRef, ...],
    artifacts: Mapping[str, Mapping[str, Any]],
    capture_ref: str,
    store: ContentAddressedStore,
) -> SceneUnposedPointMapRow | None:
    """This member's own point map, when its scene's pose recovered no photograph at all.

    ``references`` and ``artifacts`` come from ``_point_map_references``, which reads the scene's
    placement record and checks each artifact row live on every request (purge, tombstone,
    content digest), so nothing here is looser than what a placed member gets.

    Only when nothing registered, which the caller decides. A pose that registered members and
    was then refused by the gate also places nothing, and whether its members should show unplaced
    depth is a separate decision this change does not make: it would change what "cannot draw"
    means for a scene the gate rejected. See ``SceneUnposedPointMapRow``.
    """
    reference = next((item for item in references if item.capture_ref == capture_ref), None)
    artifact = artifacts.get(capture_ref)
    if reference is None or artifact is None:
        return None
    present = store.exists(BlobId.from_hex(reference.content_sha256))
    allowed = point_allowed(connection, workspace, uuid.UUID(reference.artifact_ref), viewed_at)
    available = present and allowed
    photograph = (
        _viewer_photograph(connection, workspace, capture_ref, viewed_at) if available else None
    )
    return SceneUnposedPointMapRow(
        artifact_id=uuid.UUID(reference.artifact_ref),
        content_sha256=reference.content_sha256,
        container=artifact["container"],
        state="available" if available else "unavailable" if present else "bytes_missing",
        reference=(
            SceneGeometryReferenceRow(
                href=f"/geometry/{reference.artifact_ref}",
                authorization="workspace-bearer",
                content_sha256=reference.content_sha256,
                byte_size=int(artifact["byte_size"]),
            )
            if available
            else None
        ),
        photograph=photograph,
    )


#: What the status line says when a standpoint record exists and is not drawn. Keyed by state.
_STANDPOINT_WITHHELD: Final = {
    "nothing_joined": (
        "These photographs were checked for being taken from one place and no two of them could "
        "be joined, so they stay unmeasured."
    ),
    "withdrawn": (
        "The measured arrangement of these photographs is withheld until it is joined again, "
        "because one of them may no longer be used."
    ),
    "stale": (
        "The measured arrangement of these photographs was made for an earlier version of them "
        "and is not drawn; it is joined again for this one."
    ),
    "invalid": "The measured arrangement of these photographs could not be read.",
    "bytes_missing": "The measured arrangement of these photographs is missing from storage.",
}

_STANDPOINT: Final = (
    "select artifact_id, content_sha256 from artifact where workspace_id=%s and scene_id=%s "
    "and kind=%s and purged_at is null and not needs_repair and content_sha256 is not null "
    "and byte_size is not null order by created_at desc, artifact_id desc limit 1"
)


def _standpoint(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    members: list[_Member],
    references: tuple[_PointMapRef, ...],
    store: ContentAddressedStore,
    viewed_at: dt.datetime,
) -> tuple[SceneStandpointRow | None, dict[str, SceneStandpointPlacementRow]]:
    """The scene's newest standpoint record, held to this build and to permission now.

    Placements come out only when the record parses canonically, names exactly this build's
    members in order with exactly the point maps this build's placement record binds, and every
    member it read may still be read (``asset_point_allows`` now, the check every served point map
    passes). A member withdrawn after the join withdraws the whole arrangement, because every
    rotation in it was measured with that member's pixels; the standpoint stage joins what remains.
    The artifact row itself is read live, so a purge or a deletion reaching the scene removes it.
    """
    row = connection.execute(_STANDPOINT, (workspace, scene_id, STANDPOINT_KIND)).fetchone()
    if row is None:
        return None, {}
    base: dict[str, Any] = {
        "artifact_id": row["artifact_id"],
        "content_sha256": bytes(row["content_sha256"]).hex(),
        "member_count": len(members),
    }

    def withheld(
        state: Literal["withdrawn", "stale", "invalid", "bytes_missing"],
    ) -> tuple[SceneStandpointRow, dict[str, SceneStandpointPlacementRow]]:
        return (
            SceneStandpointRow(
                **base,
                state=state,
                joined_member_count=0,
                reference_capture_id=None,
                rotation_residual_max_millidegrees=None,
                scale_residual_max_ppm=None,
                up_method=None,
                implied_roll_max_millidegrees=None,
                excluded=[],
            ),
            {},
        )

    try:
        data = store.get(BlobId(bytes(row["content_sha256"])))
    except BlobNotFoundError:
        return withheld("bytes_missing")
    except IntegrityError:
        return withheld("invalid")
    try:
        record = parse_standpoint_record(data, expected_scene_ref=str(scene_id))
    except StandpointRecordError:
        return withheld("invalid")
    if [member.member_ref for member in record.members] != [
        str(member.capture_id) for member in members
    ]:
        return withheld("stale")
    live = {reference.capture_ref: reference for reference in references}
    for member in record.members:
        if member.point_map_artifact_ref is None:
            continue
        bound = live.get(member.member_ref)
        if bound is None or (bound.artifact_ref, bound.content_sha256) != (
            member.point_map_artifact_ref,
            member.point_map_sha256,
        ):
            return withheld("stale")
    for member in record.members:
        if member.reading is not None and not point_allowed(
            connection, workspace, uuid.UUID(str(member.point_map_artifact_ref)), viewed_at
        ):
            return withheld("withdrawn")
    excluded = []
    for member in record.members:
        reason = member_refusal(record, member.ordinal)
        if reason is not None:
            excluded.append(
                SceneStandpointExclusionRow(capture_id=uuid.UUID(member.member_ref), reason=reason)
            )
    arrangement = record.arrangement
    if arrangement is None:
        return (
            SceneStandpointRow(
                **base,
                state="nothing_joined",
                joined_member_count=0,
                reference_capture_id=None,
                rotation_residual_max_millidegrees=None,
                scale_residual_max_ppm=None,
                up_method=None,
                implied_roll_max_millidegrees=None,
                excluded=excluded,
            ),
            {},
        )
    placements = {
        record.member(arranged.ordinal).member_ref: SceneStandpointPlacementRow(
            scene_from_opm_row_major=list(scene_from_opm_row_major(arranged)),
            depth_scale=arranged.depth_scale_ppm / PARTS_PER_MILLION,
            lateral_scale=arranged.lateral_scale_ppm / PARTS_PER_MILLION,
        )
        for arranged in arrangement.members
    }
    roll = arrangement.up.get("implied_roll_millidegrees")
    return (
        SceneStandpointRow(
            **base,
            state="joined",
            joined_member_count=len(placements),
            reference_capture_id=uuid.UUID(record.member(arrangement.reference).member_ref),
            rotation_residual_max_millidegrees=int(
                arrangement.rotation_solve["max_residual_millidegrees"]
            ),
            scale_residual_max_ppm=int(arrangement.scale_solve["max_residual_ppm"]),
            up_method=str(arrangement.up.get("method")),
            implied_roll_max_millidegrees=int(roll["max"]) if isinstance(roll, dict) else None,
            excluded=excluded,
        ),
        placements,
    )


def _viewer_photograph(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    capture_ref: str,
    viewed_at: dt.datetime,
) -> SceneUnposedPhotographRow | None:
    """The image the viewer route would serve for this capture now, as a digest-bound reference.

    ``image_source`` is the same function ``GET /evidence/{span_id}/masked`` asks, at the same kind
    of evaluation time, so the digest named here is the one that route resolves unless something
    changes in between; the route runs its own final check either way. Null when it would serve
    nothing, or when the capture has no whole-photograph span to address it by.
    """
    row = connection.execute(
        "select c.blob_sha256, (select s.span_id from evidence_span s "
        "where s.workspace_id=c.workspace_id and s.blob_sha256=c.blob_sha256 "
        "and s.modality='still_image' and s.track_key='img' and s.region is null "
        "order by s.span_id limit 1) as span_id "
        "from capture c where c.workspace_id=%s and c.capture_id=%s and c.deleted_at is null",
        (workspace, uuid.UUID(capture_ref)),
    ).fetchone()
    if row is None or row["span_id"] is None:
        return None
    digest = image_source(connection, workspace, bytes(row["blob_sha256"]), viewed_at)
    if digest is None:
        return None
    size = connection.execute(
        "select coalesce((select byte_size from blob where blob_sha256=%s),"
        "(select byte_size from artifact where workspace_id=%s and content_sha256=%s "
        "and byte_size is not null limit 1)) as size",
        (digest, workspace, digest),
    ).fetchone()
    if size is None or size["size"] is None:
        return None
    return SceneUnposedPhotographRow(
        href=f"/evidence/{row['span_id']}/masked",
        authorization="workspace-bearer",
        content_sha256=digest.hex(),
        byte_size=int(size["size"]),
    )


def _point_map_references(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    placement_bytes: bytes,
) -> tuple[tuple[_PointMapRef, ...], dict[str, dict[str, Any]]]:
    """The placement's point-map references and their live artifact rows, without reading bytes.

    Split from the byte read so the memo key can be built before deciding whether any object needs
    fetching. The query is the live half and runs on every request: it is what refuses a purged,
    superseded or tombstone-blocked artifact.
    """
    raw = json.loads(placement_bytes)
    placed = raw["placement"]["point_map_inputs"]
    if not isinstance(placed, list):
        raise ValueError("the placement member list is malformed")
    references: list[_PointMapRef] = []
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
        references.append(_PointMapRef(capture_ref, artifact_ref, content_sha256))
        artifacts[capture_ref] = row
    return tuple(references), artifacts


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
        # The fallback cannot resolve regions: it is reached when the receipts are unreadable, and
        # a count of zero would read as "nobody is hidden here". Zero is honest only beside the
        # member rows' "unscreened", which is what stops the client drawing anybody.
        hidden_person_count=0,
        masked_member_count=0,
        members=[
            ReconstructionSceneMemberRow(
                capture_id=member.capture_id,
                ordinal=member.ordinal,
                registered=member.registered,
                placement=None,
                # The receipts are unreadable here, so there is no placement record naming these
                # bytes and nothing whose lineage an unplaced map could carry.
                unposed_point_map=None,
                exclusion_reason=(
                    "pose-not-registered" if not member.registered else "placement-unavailable"
                ),
                # A scene that collapsed to the fallback for some unrelated reason -- a bad gate,
                # a missing placement -- must not thereby report that it contains nobody. Until
                # the regions are resolved here too, the honest answer is that nothing screened
                # this photograph, which draws silhouettes rather than pixels.
                person_regions=[],
                person_review_state="unscreened",
                standpoint_placement=None,
            )
            for member in members
        ],
        # The fallback is reached when the receipts are unreadable, and it cannot resolve
        # generations either. An empty list here is honest only because it sits beside a
        # receipt_state that already says this reader could not read the scene: a client that
        # draws generated content at all reads `receipt_state` first.
        generated_geometry=[],
        # Unreadable receipts name no build, so no standpoint record can be checked against one.
        standpoint=None,
    )
