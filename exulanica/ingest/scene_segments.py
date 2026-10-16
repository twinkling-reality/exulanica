"""What the photographs found, lifted into the scene they reconstructed.

The segmentation stage finds objects per photograph and a reviewer outlines people per photograph.
Neither says anything about the scene. This module carries both into it: every sample of the
scene's geometry is projected through every recovered camera, each camera says which of its
regions the sample falls in, and a sample joins an entity when enough of the views that could see
it agree. The result is one durable artifact per scene, a list of per-entity segments, each a set
of occupied voxels in the scene's own frame that a renderer can tint and a click can resolve to.

**One projector.** The arithmetic is the masked-geometry check's, exposed from
``exulanica/ingest/masked_geometry.py`` as ``camera_point``, ``image_point`` and ``ppm_point`` and
called here with arrays instead of floats. That check counts Gaussians over person outlines for
privacy; this counts samples over any outline for membership. A second projector would one day
disagree with the first about which side of an outline a point falls on, and the check is the one
whose answer matters more. The margin is zero here: the check grows regions because reporting too
much is its safe direction, and a segment grown past its object would vote for its neighbours.

**What is sampled.** Every placed member's posed point map, subsampled evenly to a declared budget
and carried into the scene frame by the placement's own transform, and, when the caller supplies
one, the centres of a trained Gaussian scene read through the check's own PLY header walk. The
scene worker supplies the accepted training output whenever a build publishes a trained delivery;
the command takes a PLY decoded from a delivery. The volcanic scene has no trained delivery, so it
lifts from point maps alone, and says so in its bindings.

**What a view counts.** A sample is seen by a view when it projects in front of the camera, inside
the frame, and not clearly behind the surface that view's own placed point map records at that
pixel. Without the last test a background sample would vote for whatever foreground object hides
it in that view. A sample then belongs to an entity when at least ``min_votes`` views put it
inside one of that entity's regions and those views are at least ``vote_threshold`` of the views
that saw it at all. Both numbers are stage parameters, so tuning them re-keys the artifact.

**What an entity is.** A person is their subject: every reviewed region naming one subject is one
entity, and only a region a human confirmed or drew, naming a subject whose presentation state is
``shown``, is lifted at all. An object is a label split into connected pieces: the samples of one
label are voxelised and every 26-connected component is its own entity, so two rocks that do not
touch are two segments and the naming flow can tell them apart.

**Bound, and refused when a binding moves.** The artifact names the pose, placement and gate
receipt digests, the member list, the placement's point maps, the exact segmentation artifact of
every member, every person region by its digest, and the Gaussian source. Each segment also names
the regions and point maps it rests on. The graph reader in
``exulanica/graph/reconstruction_scenes_segments.py`` refuses the whole artifact when a
scene-level binding or an object mask input has moved, and withholds a single segment when a
region it rests on has changed, a point map it came from is purged, or the person it depicts is
no longer shown. It parses these bytes itself, because ``graph`` and ``ingest`` are siblings
that may not import each other; a test pins the two spellings together.

**Privacy-bearing, unlike the projection.** A person segment is where a person's body is in the
scene. It is written only under the rule above, it carries a subject reference and never a name,
and the reader re-checks the live consent state on every request and applies the geometry
asset-read policy before any of it leaves the API.

**When it runs.** Right after a scene publishes, in the scene worker's process and in the run that
published it, with the placement that worker has just validated
(``SceneReconstructionProcessor._lift_segments``); a lift that fails there fails its own stage and
never the scene. Again whenever every member of a published scene has object masks that its newest
segments do not bind, which is how masks written after the scene was built reach it
(``scenes_due_segments`` and ``SceneReconstructionWorker.refresh_scene_segments``). And on demand,
from the command at the bottom of this module. All three run numpy and nothing else: the scene
worker holds pycolmap, which cannot share a process with torch on macOS, so the lift reads the masks
the derivative worker's segmenter wrote and never loads a model.

The lift's arithmetic (the geometry it reads, the votes and the voxels) is
:mod:`exulanica.ingest.scene_segments_lift`'s; this module builds, checks and publishes the
artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from exulanica.canonical import canonical_json
from exulanica.consent.regions import Silhouette
from exulanica.ingest.masked_geometry import gaussian_centre_array
from exulanica.ingest.scene_segments_lift import LiftRegion, _cameras, _digest, _lift, _samples
from exulanica.ingest.stages.segmentation import OBJECT_MASK_KIND, OBJECT_MASK_PROFILE
from exulanica.reconstruction.placement import (
    ExcludedPlacementMember,
    PlacedPointMap,
    PlacementRecord,
    PointMapInput,
    validate_placement_record,
    validated_receipt_cameras,
)

if TYPE_CHECKING:
    from exulanica.ingest.ledger import Ledger, StageRecorder
    from exulanica.ingest.repository import IngestRepository
    from exulanica.ingest.stages import StageSpec
    from exulanica.store.base import ContentAddressedStore

__all__ = [
    "SCENE_SEGMENTS_ENVELOPE",
    "SCENE_SEGMENTS_KIND",
    "SCENE_SEGMENTS_PROFILE",
    "SCENE_SEGMENTS_STAGE",
    "LiftRegion",
    "SegmentsDue",
    "ValidatedBuild",
    "build_scene_segments",
    "object_regions_from_artifact",
    "publish_scene_segments",
    "scenes_due_segments",
    "validate_scene_segments",
]

#: Spelled here and again in ``exulanica/graph/reconstruction_scenes_segments.py``, because the
#: layers contract forbids either sibling importing the other. A test pins the spellings together
#: and the stage registry's ``output_kind`` to this one.
SCENE_SEGMENTS_KIND: Final = "scene_segments"
SCENE_SEGMENTS_STAGE: Final = "scene_segments"
SCENE_SEGMENTS_PROFILE: Final = "exulanica.scene-segments/v1"
SCENE_SEGMENTS_ENVELOPE: Final = "exulanica.scene-segments-envelope/v1"


def object_regions_from_artifact(
    capture_ref: str, artifact_ref: str, data: bytes
) -> list[LiftRegion]:
    """Every mask in one segmentation artifact, as a region that can vote.

    The region digest is the SHA-256 of the mask's canonical record, which contains its outline,
    its label and its span digest, so any change to what the mask says changes the digest.
    """
    document = json.loads(data)
    if not isinstance(document, dict) or document.get("profile") != OBJECT_MASK_PROFILE:
        raise ValueError("the object mask list profile is unsupported")
    regions: list[LiftRegion] = []
    for record in document.get("masks", []):
        outline = Silhouette.from_digest_input(record["outline"])
        regions.append(
            LiftRegion(
                capture_ref=capture_ref,
                kind="object",
                label=str(record["label"]),
                subject_ref=None,
                reference={
                    "kind": "object_mask",
                    "artifact_ref": artifact_ref,
                    "mask_index": int(record["index"]),
                    "span_digest": str(record["span_digest"]),
                    # The naming occurrence stands on the hosted prompt box, or on the mask
                    # bounding span for a detector-only object. Both use the reader's existing
                    # occurrence lookup; neither creates an entity before human confirmation.
                    "prompt_span_digest": record.get("prompt_span_digest"),
                },
                digest=_digest(canonical_json(record)),
                outline=outline,
            )
        )
    return regions


# -- the artifact -------------------------------------------------------------------------------


def build_scene_segments(
    *,
    scene_ref: str,
    pose_receipt: bytes,
    pose_receipt_sha256: str,
    placement: PlacementRecord,
    placement_receipt_sha256: str,
    gate_receipt_sha256: str,
    member_capture_refs: Sequence[str],
    point_maps: Mapping[str, bytes],
    object_mask_inputs: Sequence[tuple[str, str, str]],
    object_mask_missing: Sequence[str],
    regions: Sequence[LiftRegion],
    params: Mapping[str, Any],
    gaussian_ply: bytes | None = None,
    gaussian_source: Mapping[str, Any] | None = None,
) -> bytes:
    """Lift one published scene's regions into segments, and bind them to everything they used.

    ``placement`` must already have been validated against ``pose_receipt`` and these exact point
    maps, as the projection requires; the transforms are used as they stand, and building it read
    the whole receipt, so the cameras are read here without its sparse observations. The receipt is
    held to the digest the placement is bound to first, which is what makes that safe. Every person
    region offered must already have passed the reviewed-and-shown rule; ``publish_scene_segments``
    is the one caller that selects them, and a test holds it to that.
    """
    if placement.scene_ref != scene_ref or placement.pose_receipt_sha256 != pose_receipt_sha256:
        raise ValueError("the placement belongs to another scene or another pose receipt")
    if _digest(pose_receipt) != pose_receipt_sha256:
        raise ValueError("the pose receipt is not the bytes its digest names")
    if tuple(placement.member_capture_refs) != tuple(member_capture_refs):
        raise ValueError("the placement member list differs from the scene member list")
    if (gaussian_ply is None) != (gaussian_source is None):
        raise ValueError("a Gaussian source must be declared exactly when its bytes are supplied")
    if (
        gaussian_ply is not None
        and gaussian_source is not None
        and gaussian_source.get("ply_sha256") != _digest(gaussian_ply)
    ):
        raise ValueError("the declared Gaussian source is not these bytes")
    centres = None if gaussian_ply is None else gaussian_centre_array(gaussian_ply)
    cameras = _cameras(pose_receipt)
    samples, occlusion = _samples(placement, point_maps, centres, params, cameras)
    segments, summary = _lift(samples, cameras, occlusion, regions, params)
    payload = {
        "profile": SCENE_SEGMENTS_PROFILE,
        "scene_ref": scene_ref,
        "bindings": {
            "pose_receipt_sha256": pose_receipt_sha256,
            "placement_receipt_sha256": placement_receipt_sha256,
            "gate_receipt_sha256": gate_receipt_sha256,
            "member_capture_refs": list(member_capture_refs),
            "point_map_inputs": [
                {"capture_ref": capture, "artifact_ref": artifact, "content_sha256": digest}
                for capture, artifact, digest in (
                    (item.capture_ref, item.artifact_ref, item.content_sha256)
                    for item in placement.point_map_inputs
                )
            ],
            "object_mask_inputs": [
                {"capture_ref": capture, "artifact_ref": artifact, "content_sha256": digest}
                for capture, artifact, digest in sorted(object_mask_inputs)
            ],
            "object_mask_missing": sorted(object_mask_missing),
            "person_regions": sorted(
                (
                    {
                        "capture_ref": region.capture_ref,
                        "region_key": region.reference["region_key"],
                        "region_digest": region.digest,
                        "subject_ref": region.subject_ref,
                    }
                    for region in regions
                    if region.kind == "person"
                ),
                key=lambda item: (item["capture_ref"], item["region_key"]),
            ),
            "gaussian_source": None if gaussian_source is None else dict(gaussian_source),
        },
        "policy": {
            key: params[key]
            for key in (
                "projector",
                "region_margin_ppm",
                "point_map_samples_per_member",
                "gaussian_samples_max",
                "visibility",
                "occlusion_grid_cells",
                "occlusion_relative_tolerance_millionths",
                "region_raster_cells",
                "min_votes",
                "vote_threshold_millionths",
                "voxel_grid_cells",
                "instance_link_voxels",
                "min_segment_samples",
                "object_instances",
                "person_segments",
            )
        },
        "grid": {"frame": "scene", "voxel_size_microunits": summary["voxel_size_microunits"]},
        "cameras": len(cameras),
        "regions_offered": {
            "object": sum(region.kind == "object" for region in regions),
            "person": sum(region.kind == "person" for region in regions),
        },
        "samples": summary["samples"],
        "samples_seen": summary["seen_by_at_least_one_view"],
        "samples_assigned": summary["assigned"],
        "segments": [
            {key: value for key, value in segment.items() if key != "entity_key"}
            for segment in segments
        ],
    }
    envelope = {
        "profile": SCENE_SEGMENTS_ENVELOPE,
        "payload_sha256": _digest(canonical_json(payload)),
        "segments": payload,
    }
    return canonical_json(envelope) + b"\n"


def validate_scene_segments(
    data: bytes,
    *,
    expected_scene_ref: str,
    pose_receipt_sha256: str,
    placement_receipt_sha256: str,
    gate_receipt_sha256: str,
    member_capture_refs: Sequence[str],
) -> dict[str, Any]:
    """Refuse segments that are malformed or bound to another scene state. Returns the payload.

    The producer checks its own bytes with this before publishing them. The graph reader repeats
    these checks in its own module, and adds the live ones this cannot make.
    """
    envelope = json.loads(data)
    if not isinstance(envelope, dict) or envelope.get("profile") != SCENE_SEGMENTS_ENVELOPE:
        raise ValueError("the scene segments envelope version is unsupported")
    payload = envelope.get("segments")
    if not isinstance(payload, dict) or payload.get("profile") != SCENE_SEGMENTS_PROFILE:
        raise ValueError("the scene segments format version is unsupported")
    if envelope.get("payload_sha256") != _digest(canonical_json(payload)):
        raise ValueError("the scene segments payload disagrees with its digest")
    if payload.get("scene_ref") != expected_scene_ref:
        raise ValueError("the scene segments name another scene")
    bindings = payload["bindings"]
    for field, expected in (
        ("pose_receipt_sha256", pose_receipt_sha256),
        ("placement_receipt_sha256", placement_receipt_sha256),
        ("gate_receipt_sha256", gate_receipt_sha256),
    ):
        if bindings.get(field) != expected:
            raise ValueError(f"the scene segments are bound to another {field}")
    if bindings.get("member_capture_refs") != list(member_capture_refs):
        raise ValueError("the scene segments are bound to another member list")
    for segment in payload["segments"]:
        identity = {key: segment[key] for key in ("kind", "label", "subject_ref", "voxels")}
        if segment["segment_id"] != _digest(canonical_json(identity))[:32]:
            raise ValueError("a segment id does not recompute from its content")
        if segment["kind"] == "person" and segment["label"] is not None:
            raise ValueError("a person segment carries a label")
    return payload


# -- publication --------------------------------------------------------------------------------

#: The scene's CURRENT job and its three receipts, modelled on the projection backfill's query and
#: narrowed the same way: a superseded job is not selected at all.
_SCENE = """
select s.scene_id, j.job_id,
       pose.artifact_id as pose_id, pose.content_sha256 as pose_sha256,
       placement.artifact_id as placement_id, placement.content_sha256 as placement_sha256,
       gate.artifact_id as gate_id, gate.content_sha256 as gate_sha256
  from reconstruction_scene s
  join reconstruction_scene_job j
    on j.workspace_id = s.workspace_id and j.job_id = s.current_job_id and j.status = 'succeeded'
  join artifact pose on pose.workspace_id = s.workspace_id
   and pose.artifact_id = j.pose_receipt_artifact_id and pose.kind = 'pose_receipt'
   and pose.purged_at is null
  join artifact placement on placement.workspace_id = s.workspace_id
   and placement.artifact_id = j.placement_artifact_id
   and placement.kind = 'point_map_placement' and placement.purged_at is null
  join artifact gate on gate.workspace_id = s.workspace_id
   and gate.artifact_id = j.gate_artifact_id and gate.kind = 'scene_gate_receipt'
   and gate.purged_at is null
 where s.workspace_id = %s and s.scene_id = %s
   and not tombstone_blocks_scene(s.workspace_id, s.scene_id)
"""

#: The newest live segmentation artifact of each member's photograph. The reader asks the same
#: question, so an artifact written after these segments is how it knows they are stale.
_OBJECT_MASKS = """
select distinct on (c.capture_id)
       c.capture_id, a.artifact_id, a.content_sha256, a.source_blob_sha256, a.read_source_sha256
  from capture c
  join artifact a on a.workspace_id = c.workspace_id and a.source_blob_sha256 = c.blob_sha256
 where c.workspace_id = %s and c.capture_id = any(%s) and a.kind = %s
   and a.purged_at is null and not a.needs_repair and a.content_sha256 is not null
   and (a.read_source_sha256 is null or a.stage_version >= 2)
   and a.byte_size is not null and not tombstone_blocks_capture(c.workspace_id, c.capture_id)
 order by c.capture_id, a.created_at desc, a.artifact_id desc
"""

#: Reviewed person regions of the members, with the state that holds now. A region is lifted only
#: when a human confirmed or drew it, it names a subject, and that subject is ``shown``: likeness
#: granted, not withdrawn, not temporarily hidden. The composition is migration 0037's own.
_PEOPLE = """
select r.capture_id, encode(r.region_key, 'hex') as region_key, r.silhouette, r.subject_id,
       encode(r.region_digest, 'hex') as region_digest
  from person_region_current r
 where r.workspace_id = %s and r.capture_id = any(%s)
   and r.action in ('confirmed', 'added') and r.confirmed_by is not null
   and r.subject_id is not null
   and not person_region_is_masked(r.workspace_id, r.subject_id, r.region_key)
   and not person_subject_is_withdrawn(r.workspace_id, r.subject_id)
   and not person_consent_is_granted(r.workspace_id, r.subject_id, r.region_key, 'temporary_hide')
 order by r.capture_id, r.region_key
"""

_POINT_MAP = """
select a.artifact_id,a.source_blob_sha256,a.read_source_sha256 from artifact a
  join capture c on c.workspace_id = a.workspace_id and c.capture_id = %s
   and c.blob_sha256 = a.source_blob_sha256
 where a.workspace_id = %s and a.artifact_id = %s and a.kind = 'point_map'
   and a.content_sha256 = %s and a.byte_size is not null and a.purged_at is null
   and not tombstone_blocks_capture(a.workspace_id, c.capture_id)
   and asset_point_allows(a.workspace_id,a.artifact_id,statement_timestamp())
"""


#: Every published scene in the workspace with its current receipts, how many members its build
#: has, the newest live segmentation artifact of each member that has one, and the newest live
#: segments artifact of the scene. The build is narrowed exactly as ``_SCENE`` narrows it, and the
#: masks are ``_OBJECT_MASKS``'s own question asked of every scene at once.
_SCENES_WITH_MASKS = """
with build as (
  select s.scene_id, j.job_id,
         pose.content_sha256 as pose_sha256,
         placement.content_sha256 as placement_sha256,
         gate.content_sha256 as gate_sha256
    from reconstruction_scene s
    join reconstruction_scene_job j
      on j.workspace_id = s.workspace_id and j.job_id = s.current_job_id
     and j.status = 'succeeded'
    join artifact pose on pose.workspace_id = s.workspace_id
     and pose.artifact_id = j.pose_receipt_artifact_id and pose.kind = 'pose_receipt'
     and pose.purged_at is null
    join artifact placement on placement.workspace_id = s.workspace_id
     and placement.artifact_id = j.placement_artifact_id
     and placement.kind = 'point_map_placement' and placement.purged_at is null
    join artifact gate on gate.workspace_id = s.workspace_id
     and gate.artifact_id = j.gate_artifact_id and gate.kind = 'scene_gate_receipt'
     and gate.purged_at is null
   where s.workspace_id = %(workspace)s
     and not tombstone_blocks_scene(s.workspace_id, s.scene_id)
),
member as (
  select b.scene_id, m.capture_id
    from build b
    join reconstruction_scene_build_member m
      on m.workspace_id = %(workspace)s and m.job_id = b.job_id
),
mask as (
  select distinct on (member.scene_id, member.capture_id)
         member.scene_id, member.capture_id, a.artifact_id, a.content_sha256
    from member
    join capture c on c.workspace_id = %(workspace)s and c.capture_id = member.capture_id
    join artifact a on a.workspace_id = c.workspace_id and a.source_blob_sha256 = c.blob_sha256
   where a.kind = %(mask_kind)s
     and a.purged_at is null and not a.needs_repair and a.content_sha256 is not null
     and a.byte_size is not null and not tombstone_blocks_capture(c.workspace_id, c.capture_id)
   order by member.scene_id, member.capture_id, a.created_at desc, a.artifact_id desc
)
select b.scene_id, b.job_id, b.pose_sha256, b.placement_sha256, b.gate_sha256,
       (select count(*) from member where member.scene_id = b.scene_id) as member_count,
       coalesce(
         (select jsonb_agg(jsonb_build_array(
                   mask.capture_id::text, mask.artifact_id::text,
                   encode(mask.content_sha256, 'hex')))
            from mask where mask.scene_id = b.scene_id),
         '[]'::jsonb) as masks,
       (select a.content_sha256 from artifact a
         where a.workspace_id = %(workspace)s and a.scene_id = b.scene_id
           and a.kind = %(segments_kind)s and a.purged_at is null and not a.needs_repair
           and a.content_sha256 is not null and a.byte_size is not null
         order by a.created_at desc, a.artifact_id desc
         limit 1) as segments_sha256
  from build b
 order by b.scene_id
"""


class _LiftRefused(RuntimeError):
    """This scene cannot be lifted as it stands. Fails its own stage and returns as a skip.

    Raised inside an open ``scene_segments`` stage, so the ledger writes ``stage_failed`` naming
    the cause, and caught by ``publish_scene_segments``: a receipt, a point map or a mask that has
    gone is a state of the scene rather than a fault in whoever asked for the lift.
    """


@dataclass(frozen=True, slots=True)
class ValidatedBuild:
    """A build its caller has just validated, so that the lift need not validate it again.

    The scene worker builds the placement from the pose receipt and every point map and checks the
    stored bytes against it before it publishes, and doing that a second time is most of a lift.
    MEASURED 2026-09-11 on the volcanic scene: validating the placement against 210 point maps and
    a 107,742,795 byte pose receipt took 36 to 42 s, and the build that follows it 5.4 s
    (``docs/scene-segments.md`` sections 7 and 8).
    ``publish_scene_segments`` still reads the scene's current build from the database, uses these
    only when they are that build's own receipts byte for byte, and otherwise reads the bound
    projection, falling back to placement validation if no valid projection is available.
    ``placement`` is the record ``build_placement_record``
    makes from that pose receipt and those point maps, which is exactly what
    ``validate_placement_record`` returns for them, so both paths lift from the same record.
    """

    job_id: uuid.UUID
    pose_receipt: bytes
    placement_receipt: bytes
    placement: PlacementRecord
    point_maps: Mapping[str, bytes]


def publish_scene_segments(
    repository: IngestRepository,
    store: ContentAddressedStore,
    scene_id: uuid.UUID,
    *,
    gaussian_ply: bytes | None = None,
    gaussian_source: Mapping[str, Any] | None = None,
    ledger: Ledger | None = None,
    validated: ValidatedBuild | None = None,
    trigger: str = "manual",
) -> dict[str, Any]:
    """Lift one published scene and write its segments artifact, idempotently.

    Returns what happened. A scene with no current build or nothing to lift, a receipt, point map
    or mask that has gone, and a deletion that reaches the scene are each returned as a skip with
    its reason rather than raised; anything else raises, after its stage has recorded it as
    ``stage_failed``. The artifact id is derived from every input digest, so a second run over
    unchanged inputs writes nothing and says so.

    ``ledger`` is a run to record into, which is how the scene worker files the lift beside the
    projection in the run that published the scene; the caller closes it. Without one the lift
    opens a run of its own under ``trigger`` and closes it. A skip decided before any work begins
    is a ``stage_skipped`` event in the caller's run, and no run at all otherwise.
    """
    from exulanica.errors import TombstonedError
    from exulanica.ingest.ledger import Ledger
    from exulanica.ingest.stages import stage

    started = time.monotonic()
    spec = stage(SCENE_SEGMENTS_STAGE)
    workspace = repository.workspace_id
    connection = repository.connection
    row = connection.execute(_SCENE, (workspace, scene_id)).fetchone()
    if row is None:
        return _skipped(
            ledger,
            spec,
            {"scene_id": str(scene_id)},
            "the scene has no current succeeded build with live receipts",
        )
    outcome: dict[str, Any] = {"scene_id": str(scene_id), "job_id": str(row["job_id"])}
    members = [
        str(item["capture_id"])
        for item in connection.execute(
            "select capture_id from reconstruction_scene_build_member "
            "where workspace_id = %s and job_id = %s order by ordinal, capture_id",
            (workspace, row["job_id"]),
        ).fetchall()
    ]
    capture_ids = [uuid.UUID(member) for member in members]
    masks = connection.execute(_OBJECT_MASKS, (workspace, capture_ids, OBJECT_MASK_KIND)).fetchall()
    people = connection.execute(_PEOPLE, (workspace, capture_ids)).fetchall()
    if not masks and not people:
        # Not a lift of nothing. An artifact with no segments in it would tell a reader that these
        # photographs were looked at and nothing was found, when nobody looked. With none the
        # reader says `absent`, which is true, and `scenes_due_segments` finds the scene once its
        # members have masks.
        return _skipped(
            ledger,
            spec,
            outcome,
            "no member has object masks or a reviewed, shown person region to lift",
        )

    run = ledger if ledger is not None else Ledger.start_run(repository, trigger=trigger)
    try:
        with run.stage(
            spec,
            input_artifact_ids=[
                row["pose_id"],
                row["placement_id"],
                row["gate_id"],
                *(mask["artifact_id"] for mask in masks),
            ],
        ) as recorder:
            outcome, inserted = _lift_and_write(
                repository,
                store,
                scene_id,
                row,
                members,
                masks,
                people,
                spec=spec,
                recorder=recorder,
                outcome=outcome,
                validated=validated,
                gaussian_ply=gaussian_ply,
                gaussian_source=gaussian_source,
                started=started,
            )
    except _LiftRefused as refusal:
        _finish(run, ledger, "failed")
        return {**outcome, "action": "skipped", "reason": str(refusal)}
    except TombstonedError as error:
        _finish(run, ledger, "failed")
        return {**outcome, "action": "skipped", "reason": f"deletion reaches this scene: {error}"}
    except BaseException:
        _finish(run, ledger, "failed")
        raise
    _finish(run, ledger, "succeeded")
    return {**outcome, "action": "written" if inserted else "already-present"}


def _lift_and_write(
    repository: IngestRepository,
    store: ContentAddressedStore,
    scene_id: uuid.UUID,
    row: Mapping[str, Any],
    members: list[str],
    masks: Sequence[Mapping[str, Any]],
    people: Sequence[Mapping[str, Any]],
    *,
    spec: StageSpec,
    recorder: StageRecorder,
    outcome: dict[str, Any],
    validated: ValidatedBuild | None,
    gaussian_ply: bytes | None,
    gaussian_source: Mapping[str, Any] | None,
    started: float,
) -> tuple[dict[str, Any], bool]:
    """The lift itself, inside its open stage: read, validate, lift, check and write."""
    from exulanica.evidence.blob import BlobId
    from exulanica.ingest.committed_store import committed_writes
    from exulanica.ingest.scene_reconstruction import _scene_key
    from exulanica.ingest.stages import artifact_id_for, input_digest_of

    workspace = repository.workspace_id
    connection = repository.connection
    pose_digest = bytes(row["pose_sha256"]).hex()
    placement_digest = bytes(row["placement_sha256"]).hex()
    gate_digest = bytes(row["gate_sha256"]).hex()
    build = validated if validated is not None and _is_build(validated, row) else None
    if build is not None:
        pose_bytes, placement_bytes = build.pose_receipt, build.placement_receipt
    else:
        pose_bytes = _stored(store, pose_digest, "a scene receipt")
        placement_bytes = _stored(store, placement_digest, "a scene receipt")

    point_maps: dict[str, PointMapInput] = {}
    pose_frames = {
        frame["capture_ref"]: frame for frame in json.loads(pose_bytes)["manifest"]["frames"]
    }
    cameras = validated_receipt_cameras(pose_bytes)
    point_grids = {}
    point_reads = {}
    for item in json.loads(placement_bytes)["placement"]["point_map_inputs"]:
        capture_ref, artifact_ref = str(item["capture_ref"]), str(item["artifact_ref"])
        digest = str(item["content_sha256"])
        # Asked even of a build validated a moment ago: a purge that landed in between is exactly
        # what this is for, and it costs one indexed read per member.
        live = connection.execute(
            _POINT_MAP,
            (uuid.UUID(capture_ref), workspace, uuid.UUID(artifact_ref), bytes.fromhex(digest)),
        ).fetchone()
        if live is None:
            raise _LiftRefused(f"point map {artifact_ref} is gone")
        content = build.point_maps.get(capture_ref) if build is not None else None
        if content is None:
            content = _stored(store, digest, "a point map")
        selected = bytes(live["read_source_sha256"] or live["source_blob_sha256"]).hex()
        if capture_ref not in pose_frames or pose_frames[capture_ref]["sha256"] != selected:
            raise _LiftRefused("point map and pose read different image bytes")
        try:
            length = int.from_bytes(content[4:8], "little")
            source = json.loads(content[8 : 8 + length])["sourceImage"]
            grid = (source["width"], source["height"])
        except (KeyError, ValueError, TypeError) as error:
            raise _LiftRefused("point map has no verifiable source pixel grid") from error
        if capture_ref in cameras:
            calibration = cameras[capture_ref]["calibration"]
            if grid != (calibration["width"], calibration["height"]):
                raise _LiftRefused("point map and pose use different pixel grids")
        point_grids[capture_ref] = grid
        point_reads[capture_ref] = selected
        point_maps[capture_ref] = PointMapInput(capture_ref, artifact_ref, digest, content)
    placement_started = time.monotonic()
    placement = (
        build.placement
        if build is not None
        else _projected_placement(repository, store, scene_id, row, members, placement_bytes)
    )
    projection_used = build is None and placement is not None
    revalidated = placement is None
    if placement is None:
        placement = validate_placement_record(
            placement_bytes,
            expected_scene_ref=str(scene_id),
            pose_receipt=pose_bytes,
            member_capture_refs=members,
            point_maps=point_maps,
        )
    placement_seconds = time.monotonic() - placement_started

    regions: list[LiftRegion] = []
    mask_inputs: list[tuple[str, str, str]] = []
    for mask in masks:
        digest = bytes(mask["content_sha256"]).hex()
        capture_ref = str(mask["capture_id"])
        data = _stored(store, digest, "an object mask artifact")
        try:
            source = json.loads(data)["source"]
            read = source["read_sha256"] or source["blob_sha256"]
            grid = (source["display"]["w"], source["display"]["h"])
        except (KeyError, ValueError, TypeError) as error:
            raise _LiftRefused("object masks have no exact source/grid binding") from error
        if (
            read != point_reads.get(capture_ref)
            or grid != point_grids.get(capture_ref)
            or read != bytes(mask["read_source_sha256"] or mask["source_blob_sha256"]).hex()
        ):
            raise _LiftRefused(
                "object masks, depth and pose disagree on source bytes or pixel grid"
            )
        regions.extend(object_regions_from_artifact(capture_ref, str(mask["artifact_id"]), data))
        mask_inputs.append((capture_ref, str(mask["artifact_id"]), digest))
    missing = sorted(set(members) - {capture for capture, _, _ in mask_inputs})
    for person in people:
        regions.append(
            LiftRegion(
                capture_ref=str(person["capture_id"]),
                kind="person",
                label=None,
                subject_ref=str(person["subject_id"]),
                reference={"kind": "person_region", "region_key": person["region_key"]},
                digest=person["region_digest"],
                outline=Silhouette.from_digest_input(person["silhouette"]),
            )
        )

    payload = build_scene_segments(
        scene_ref=str(scene_id),
        pose_receipt=pose_bytes,
        pose_receipt_sha256=pose_digest,
        placement=placement,
        placement_receipt_sha256=placement_digest,
        gate_receipt_sha256=gate_digest,
        member_capture_refs=members,
        point_maps={capture: item.content for capture, item in point_maps.items()},
        object_mask_inputs=mask_inputs,
        object_mask_missing=missing,
        regions=regions,
        params=spec.params,
        gaussian_ply=gaussian_ply,
        gaussian_source=gaussian_source,
    )
    checked = validate_scene_segments(
        payload,
        expected_scene_ref=str(scene_id),
        pose_receipt_sha256=pose_digest,
        placement_receipt_sha256=placement_digest,
        gate_receipt_sha256=gate_digest,
        member_capture_refs=members,
    )
    # Keyed on the whole binding set rather than on the bytes, so the key names what the output
    # SHOULD be before it is computed and a rerun over the same inputs is recognised as one.
    input_digest = input_digest_of(
        [
            bytes.fromhex(_digest(canonical_json(json.loads(payload)["segments"]["bindings"]))),
        ]
    )
    key = _scene_key(scene_id, spec.key, input_digest)
    existing_artifact = repository.find_artifact(key)
    artifact_id = (
        existing_artifact.artifact_id
        if existing_artifact is not None
        else artifact_id_for(key, workspace_id=repository.workspace_id)
    )
    content_id = BlobId.of_bytes(payload)
    outcome = {
        **outcome,
        "artifact_id": str(artifact_id),
        "segments_sha256": content_id.hex,
        "byte_size": len(payload),
        "segments": len(checked["segments"]),
        "object_mask_inputs": len(mask_inputs),
        "object_mask_missing": len(missing),
        "person_regions": sum(region.kind == "person" for region in regions),
        "regions_offered": len(regions),
        "placement_revalidated": revalidated,
        "projection_used": projection_used,
        "placement_seconds": round(placement_seconds, 3),
        "lift_seconds": round(time.monotonic() - started, 3),
    }
    with (
        repository.locked_stored_objects([content_id]),
        committed_writes(repository, store) as pending,
    ):
        inserted = repository.insert_scene_artifact(
            artifact_id=artifact_id,
            kind=spec.output_kind,
            scene_id=scene_id,
            stage_key=spec.key,
            stage_version=spec.version,
            params_digest=spec.params_digest,
            input_digest=input_digest,
            idempotency_key=key,
            content_sha256=content_id.digest,
            storage_key=store.key_for(content_id),
            byte_size=len(payload),
            produced_by_event=recorder.stage_started_event,
        )
        # Appended whether or not the row was new, for the reason the projection backfill gives: a
        # run killed between the row commit and the byte flush leaves a live row with nothing
        # behind it, and the rerun is what heals it.
        pending.append(payload)
        if inserted:
            recorder.record_output(artifact_id)
    return outcome, inserted


def _projected_placement(
    repository: IngestRepository,
    store: ContentAddressedStore,
    scene_id: uuid.UUID,
    row: Mapping[str, Any],
    members: list[str],
    placement_bytes: bytes,
) -> PlacementRecord | None:
    """Read the publication's validated transforms with all current bindings checked.

    An absent or invalid projection falls back to receipt validation. Point-map liveness and
    content digests are checked by the caller on either path; the projection grants no access.
    """
    from exulanica.ingest.scene_projection import validate_scene_projection

    raw = json.loads(placement_bytes)["placement"]
    inputs = tuple(
        PointMapInput(item["capture_ref"], item["artifact_ref"], item["content_sha256"])
        for item in raw["point_map_inputs"]
    )
    rows = repository.connection.execute(
        "select content_sha256 from artifact where workspace_id=%s and scene_id=%s "
        "and kind='scene_projection' and purged_at is null and not needs_repair "
        "and content_sha256 is not null and byte_size is not null "
        "order by created_at desc, artifact_id desc limit 4",
        (repository.workspace_id, scene_id),
    ).fetchall()
    for candidate in rows:
        try:
            projection = validate_scene_projection(
                _stored(store, bytes(candidate["content_sha256"]).hex(), "a scene projection"),
                expected_scene_ref=str(scene_id),
                pose_receipt_sha256=bytes(row["pose_sha256"]).hex(),
                placement_receipt_sha256=bytes(row["placement_sha256"]).hex(),
                gate_receipt_sha256=bytes(row["gate_sha256"]).hex(),
                member_capture_refs=members,
                point_map_inputs=tuple(
                    (item.capture_ref, item.artifact_ref, item.content_sha256) for item in inputs
                ),
            )
        except (_LiftRefused, ValueError, KeyError, TypeError):
            continue
        return PlacementRecord(
            scene_ref=projection.scene_ref,
            pose_receipt_sha256=projection.pose_receipt_sha256,
            pose_manifest_sha256=raw["pose_manifest_sha256"],
            member_capture_refs=projection.member_capture_refs,
            placed=tuple(
                PlacedPointMap(
                    item.capture_ref,
                    item.point_map_artifact_ref,
                    item.point_map_content_sha256,
                    item.scene_from_opm_row_major,
                    item.local_units_to_scene_units,
                    {},
                    item.scale_status,
                )
                for item in projection.placed
            ),
            excluded=tuple(
                ExcludedPlacementMember(item.capture_ref, item.registered, item.reason)
                for item in projection.excluded
            ),
            input_sha256=raw["input_sha256"],
            point_map_inputs=inputs,
        )
    return None


def _is_build(build: ValidatedBuild, row: Mapping[str, Any]) -> bool:
    """Whether a caller's validated build is the scene's current one, receipt for receipt."""
    return (
        build.job_id == row["job_id"]
        and hashlib.sha256(build.pose_receipt).digest() == bytes(row["pose_sha256"])
        and hashlib.sha256(build.placement_receipt).digest() == bytes(row["placement_sha256"])
    )


def _stored(store: ContentAddressedStore, digest: str, what: str) -> bytes:
    from exulanica.errors import BlobNotFoundError, IntegrityError
    from exulanica.evidence.blob import BlobId

    try:
        return store.get(BlobId.from_hex(digest))
    except (BlobNotFoundError, IntegrityError) as error:
        raise _LiftRefused(f"{what} is unreadable: {error}") from error


def _skipped(
    ledger: Ledger | None, spec: StageSpec, outcome: dict[str, Any], reason: str
) -> dict[str, Any]:
    """A skip decided before any work began: an event in a caller's run, and nothing otherwise."""
    if ledger is not None:
        ledger.skipped(spec, reason=reason)
    return {**outcome, "action": "skipped", "reason": reason}


def _finish(run: Ledger, caller: Ledger | None, status: str) -> None:
    """Close a run this lift opened. A caller's run is the caller's to close."""
    if caller is None:
        run.finish(status)


# -- lifting again --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SegmentsDue:
    """A published scene to lift again, why, and the mask set a lift of it now would bind."""

    scene_id: uuid.UUID
    job_id: uuid.UUID
    object_masks: tuple[tuple[str, str, str], ...]
    reason: str
    #: The newest segments of this very build were lifted over trained Gaussians, which only
    #: the scene worker at publication and the command given a PLY can lift over again.
    over_gaussians: bool = False

    @property
    def state(self) -> tuple[uuid.UUID, tuple[tuple[str, str, str], ...]]:
        """What a lift would bind beyond the receipts, which the job id already names."""
        return (self.job_id, self.object_masks)


def scenes_due_segments(
    repository: IngestRepository, store: ContentAddressedStore
) -> list[SegmentsDue]:
    """Published scenes whose members all have object masks that their newest segments lack.

    The case this exists for is a scene built before its photographs were segmented, because the
    derivative worker reached them late or had no segmenter until an operator turned one on. The
    lift at publication bound the members that had masks then and named the rest missing, and the
    reader calls those segments stale as soon as one more member has a mask.

    A scene is due only once EVERY member of its current build has a live segmentation artifact,
    and then only when its newest segments are absent, unreadable, bound to another build or bound
    to other masks. Waiting for the whole set is deliberate: a derivative worker segments one
    photograph at a time, and lifting after each would lift a 210 member scene 210 times. The price
    is that a scene whose segmentation never completes stays stale until the command is run for
    it. Person regions play no part: one reviewed after the lift is reported in the reader's
    ``stale_inputs`` while everything else is still served.
    """
    rows = repository.connection.execute(
        _SCENES_WITH_MASKS,
        {
            "workspace": repository.workspace_id,
            "mask_kind": OBJECT_MASK_KIND,
            "segments_kind": SCENE_SEGMENTS_KIND,
        },
    ).fetchall()
    due: list[SegmentsDue] = []
    for row in rows:
        masks = tuple(sorted((str(c), str(a), str(d)) for c, a, d in row["masks"]))
        if not row["member_count"] or len(masks) != row["member_count"]:
            continue
        found = _why_due(store, row, masks)
        if found is not None:
            reason, over_gaussians = found
            due.append(SegmentsDue(row["scene_id"], row["job_id"], masks, reason, over_gaussians))
    return due


def _why_due(
    store: ContentAddressedStore,
    row: Mapping[str, Any],
    masks: tuple[tuple[str, str, str], ...],
) -> tuple[str, bool] | None:
    """Why a scene's newest segments do not answer for these masks under its build, or None.

    The flag says the newest segments are this build's and were lifted over trained Gaussians.
    """
    from exulanica.errors import BlobNotFoundError, IntegrityError
    from exulanica.evidence.blob import BlobId

    if row["segments_sha256"] is None:
        return "no segments have been lifted for this build", False
    try:
        envelope = json.loads(store.get(BlobId(bytes(row["segments_sha256"]))))
        bindings = envelope["segments"]["bindings"]
        receipts = tuple(
            str(bindings[field])
            for field in (
                "pose_receipt_sha256",
                "placement_receipt_sha256",
                "gate_receipt_sha256",
            )
        )
        bound = tuple(
            sorted(
                (str(item["capture_ref"]), str(item["artifact_ref"]), str(item["content_sha256"]))
                for item in bindings["object_mask_inputs"]
            )
        )
        over_gaussians = bindings.get("gaussian_source") is not None
    except (BlobNotFoundError, IntegrityError, KeyError, TypeError, ValueError):
        return "the newest segments cannot be read", False
    if receipts != tuple(
        bytes(row[field]).hex() for field in ("pose_sha256", "placement_sha256", "gate_sha256")
    ):
        return "the newest segments belong to another build", False
    if bound != masks:
        return (
            "a member's object masks changed after the newest segments were lifted",
            over_gaussians,
        )
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m exulanica.ingest.scene_segments --workspace <uuid> --scene <uuid>``."""
    from exulanica.db import Database
    from exulanica.env import resolve_data_dir
    from exulanica.ingest.repository import IngestRepository
    from exulanica.ingest.stages import STAGES
    from exulanica.store.configured import content_stores

    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--workspace", type=uuid.UUID, required=True)
    parser.add_argument("--scene", type=uuid.UUID, required=True)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument(
        "--gaussian-ply",
        type=Path,
        default=None,
        help="a PLY of the scene's trained Gaussians, decoded from its delivery",
    )
    parser.add_argument(
        "--gaussian-delivery-sha256",
        default=None,
        help="the delivery artifact digest the PLY was decoded from; required with --gaussian-ply",
    )
    args = parser.parse_args(argv)
    store = content_stores(data_dir=resolve_data_dir(explicit=args.data_dir).resolve()).blobs
    gaussian_ply = None if args.gaussian_ply is None else args.gaussian_ply.read_bytes()
    gaussian_source = None
    if gaussian_ply is not None:
        if not args.gaussian_delivery_sha256:
            parser.error("--gaussian-ply needs --gaussian-delivery-sha256")
        gaussian_source = {
            "ply_sha256": _digest(gaussian_ply),
            "delivery_sha256": args.gaussian_delivery_sha256,
            "basis": "decoded trained delivery",
        }
    with Database.from_env().session(args.workspace) as connection:
        repository = IngestRepository(connection, args.workspace)
        repository.register_stages(STAGES)
        result = publish_scene_segments(
            repository,
            store,
            args.scene,
            gaussian_ply=gaussian_ply,
            gaussian_source=gaussian_source,
        )
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if result.get("action") in {"written", "already-present"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
