"""The scene segments read: the segments of one scene that the graph reader can stand behind.

A part of :mod:`exulanica.graph.reconstruction_scenes`, which imports its public names back.
It proves a ``scene_segments`` artifact against the scene's current build and then makes the
live checks no digest can make, on every request.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Final, Literal

import psycopg

from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.graph.geometry import POINT_MAP_KIND
from exulanica.store.base import ContentAddressedStore


def _hex(value: object) -> str | None:
    return bytes(value).hex() if value is not None else None


# -- the scene segments read ---------------------------------------------------------------------
#
# What the photographs found, lifted into this scene by `exulanica/ingest/scene_segments.py`. The
# producer binds its artifact to the pose, placement and gate receipts, the member list, the
# placement's point maps, every member's exact segmentation artifact and every person region it
# lifted, by digest. This reader proves those bindings before serving a single segment, and then
# makes the live checks no digest can make, on every request:
#
# *   A member whose NEWEST live segmentation artifact is not the one bound, or who has one where
#     the producer found none, makes the whole artifact STALE. Object masks decide votes for every
#     entity, so a changed mask in one photograph can move any segment, and nothing is served.
# *   A segment resting on a point map that is purged, tombstone-blocked or missing its bytes is
#     WITHHELD. Deletion acts at once and only on what it reaches.
# *   A person segment is withheld unless every region it rests on is still current at the bound
#     digest, still reviewed, still names the bound subject, and that subject is still `shown`:
#     likeness granted, not withdrawn, not temporarily hidden. The composition is migration
#     0037's, the same one `exulanica/ingest/scene_segments.py` selected with. A name travels
#     only on a naming receipt, and never once a withdrawal stands, which is how
#     `exulanica/graph/person_regions.py` decides it for the scene row.
#
# The route then applies the geometry asset-read policy, `scene_inputs` and `scene_allowed` at the
# snapshot and again under the final lock, and requires every artifact behind the answer to be
# live at both instants. None of that is decided here, because the route is where the lock is.
#
# The bytes are parsed here rather than by calling the producer, for the reason the projection's
# are: `graph` and `ingest` are siblings in the layers contract. The kinds and profiles are spelled
# again below and a test pins them to the producer's.

#: Spelled here as well as in `exulanica/ingest/scene_segments.py` and
#: `exulanica/ingest/stages/segmentation.py`. A test pins them together.
SCENE_SEGMENTS_KIND: Final = "scene_segments"
OBJECT_MASK_KIND: Final = "object_mask_list"
_SEGMENTS_PROFILE: Final = "exulanica.scene-segments/v1"
_SEGMENTS_ENVELOPE: Final = "exulanica.scene-segments-envelope/v1"

SegmentsState = Literal["available", "stale", "absent", "unavailable"]


@dataclass(frozen=True, slots=True)
class SceneSegmentsRead:
    """One scene's segments as this reader can stand behind them right now.

    ``live_artifact_ids`` is every artifact the answer depends on beyond the scene receipts: the
    segments artifact itself and each bound segmentation artifact. The route re-checks each under
    the final lock, because an artifact purged between this read and the response must not be
    answered for.
    """

    scene_id: uuid.UUID
    state: SegmentsState
    reason: str | None
    artifact_id: uuid.UUID | None = None
    content_sha256: str | None = None
    byte_size: int | None = None
    pose_receipt_sha256: str | None = None
    placement_receipt_sha256: str | None = None
    gate_receipt_sha256: str | None = None
    voxel_size_microunits: int | None = None
    policy: dict[str, Any] | None = None
    segments: tuple[dict[str, Any], ...] = ()
    withheld_segment_count: int = 0
    stale_inputs: tuple[str, ...] = ()
    live_artifact_ids: tuple[uuid.UUID, ...] = ()

    def withheld(self, reason: str) -> SceneSegmentsRead:
        """This read with every segment taken back, for a caller that denied the geometry."""
        return SceneSegmentsRead(
            scene_id=self.scene_id,
            state="unavailable",
            reason=reason,
            artifact_id=self.artifact_id,
            content_sha256=self.content_sha256,
            byte_size=self.byte_size,
            pose_receipt_sha256=self.pose_receipt_sha256,
            placement_receipt_sha256=self.placement_receipt_sha256,
            gate_receipt_sha256=self.gate_receipt_sha256,
            voxel_size_microunits=None,
            policy=self.policy,
            segments=(),
            withheld_segment_count=self.withheld_segment_count + len(self.segments),
            stale_inputs=self.stale_inputs,
            live_artifact_ids=self.live_artifact_ids,
        )


_SEGMENT_SCENE = """
select s.scene_id, j.job_id,
       pose.content_sha256 as pose_sha256,
       placement.content_sha256 as placement_sha256,
       gate.content_sha256 as gate_sha256
  from reconstruction_scene s
  left join reconstruction_scene_job j
    on j.workspace_id = s.workspace_id and j.job_id = s.current_job_id and j.status = 'succeeded'
  left join artifact pose on pose.workspace_id = s.workspace_id
   and pose.artifact_id = j.pose_receipt_artifact_id and pose.kind = 'pose_receipt'
   and pose.purged_at is null
  left join artifact placement on placement.workspace_id = s.workspace_id
   and placement.artifact_id = j.placement_artifact_id
   and placement.kind = 'point_map_placement' and placement.purged_at is null
  left join artifact gate on gate.workspace_id = s.workspace_id
   and gate.artifact_id = j.gate_artifact_id and gate.kind = 'scene_gate_receipt'
   and gate.purged_at is null
 where s.workspace_id = %s and s.scene_id = %s
   and not tombstone_blocks_scene(s.workspace_id, s.scene_id)
"""

_SEGMENT_CANDIDATES = """
select artifact_id, content_sha256, byte_size
  from artifact
 where workspace_id = %s and scene_id = %s and kind = %s and purged_at is null
   and not needs_repair and content_sha256 is not null and byte_size is not null
 order by created_at desc, artifact_id desc
 limit 4
"""

#: The producer's own question, asked again: the newest live segmentation artifact of each member.
_SEGMENT_OBJECT_MASKS = """
select distinct on (c.capture_id)
       c.capture_id, a.artifact_id, a.content_sha256
  from capture c
  join artifact a on a.workspace_id = c.workspace_id and a.source_blob_sha256 = c.blob_sha256
 where c.workspace_id = %s and c.capture_id = any(%s) and a.kind = %s
   and a.purged_at is null and not a.needs_repair and a.content_sha256 is not null
   and (a.read_source_sha256 is null or a.stage_version >= 2)
   and a.byte_size is not null and not tombstone_blocks_capture(c.workspace_id, c.capture_id)
 order by c.capture_id, a.created_at desc, a.artifact_id desc
"""

#: Every region a person segment may still rest on, with the name the browser may draw. The
#: eligibility predicate is the producer's, word for word; the name is `person_regions._name`'s.
_SEGMENT_PEOPLE = """
select r.capture_id, encode(r.region_key, 'hex') as region_key, r.subject_id,
       encode(r.region_digest, 'hex') as region_digest,
       case when person_consent_is_granted(r.workspace_id, r.subject_id, r.region_key, 'naming')
            then e.display_name end as display_name
  from person_region_current r
  left join person_subject s on s.workspace_id = r.workspace_id and s.subject_id = r.subject_id
  left join entity e on e.entity_id = s.entity_id
 where r.workspace_id = %s and r.capture_id = any(%s)
   and r.action in ('confirmed', 'added') and r.confirmed_by is not null
   and r.subject_id is not null
   and not person_region_is_masked(r.workspace_id, r.subject_id, r.region_key)
   and not person_subject_is_withdrawn(r.workspace_id, r.subject_id)
   and not person_consent_is_granted(r.workspace_id, r.subject_id, r.region_key, 'temporary_hide')
"""

_SEGMENT_POINT_MAP = """
select 1 from artifact a
  join capture c on c.workspace_id = a.workspace_id and c.capture_id = %s
   and c.blob_sha256 = a.source_blob_sha256
 where a.workspace_id = %s and a.artifact_id = %s and a.kind = %s
   and a.content_sha256 = %s and a.byte_size is not null and a.purged_at is null
   and not tombstone_blocks_capture(a.workspace_id, c.capture_id)
"""


def scene_segments_read(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    store: ContentAddressedStore,
) -> SceneSegmentsRead | None:
    """The segments this reader can stand behind for one scene, or None when there is no scene.

    Never raises for a malformed or stale artifact. Every refusal is a state and a reason, because
    a client deciding whether to tint anything needs to know which of "none were lifted", "they
    are out of date" and "you may not have them" it is looking at.
    """
    row = connection.execute(_SEGMENT_SCENE, (workspace, scene_id)).fetchone()
    if row is None:
        return None
    pose, placement, gate = (
        _hex(row[key]) for key in ("pose_sha256", "placement_sha256", "gate_sha256")
    )
    if row["job_id"] is None or pose is None or placement is None or gate is None:
        return SceneSegmentsRead(
            scene_id, "unavailable", "The scene has no current build with live receipts."
        )
    receipts = {
        "pose_receipt_sha256": pose,
        "placement_receipt_sha256": placement,
        "gate_receipt_sha256": gate,
    }
    members = [
        str(item["capture_id"])
        for item in connection.execute(
            "select capture_id from reconstruction_scene_build_member "
            "where workspace_id = %s and job_id = %s order by ordinal, capture_id",
            (workspace, row["job_id"]),
        ).fetchall()
    ]
    candidates = connection.execute(
        _SEGMENT_CANDIDATES, (workspace, scene_id, SCENE_SEGMENTS_KIND)
    ).fetchall()
    if not candidates:
        return SceneSegmentsRead(
            scene_id, "absent", "No segments have been lifted for this scene.", **receipts
        )
    chosen = None
    for candidate in candidates:
        try:
            data = store.get(BlobId(bytes(candidate["content_sha256"])))
            payload = _segments_payload(data, str(scene_id), receipts, members)
        except (BlobNotFoundError, IntegrityError, KeyError, TypeError, ValueError):
            continue
        if payload is not None:
            chosen = candidate, payload
            break
    if chosen is None:
        return SceneSegmentsRead(
            scene_id,
            "stale",
            "The lifted segments belong to another build of this scene, or cannot be read.",
            stale_inputs=("scene_build",),
            **receipts,
        )
    candidate, payload = chosen
    try:
        return _proven_read(
            connection, workspace, scene_id, store, candidate, payload, receipts, members
        )
    except (KeyError, TypeError, ValueError):
        # A payload that proved its digest and its bindings and is still not a shape this reader
        # takes. Refused like any other unreadable artifact and never raised, for the reason the
        # projection reader gives: a bad artifact must not become a 500 for its whole scene.
        return SceneSegmentsRead(
            scene_id,
            "stale",
            "The lifted segments cannot be read.",
            stale_inputs=("unreadable",),
            **receipts,
        )


def _proven_read(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    store: ContentAddressedStore,
    candidate: dict[str, Any],
    payload: dict[str, Any],
    receipts: dict[str, str],
    members: list[str],
) -> SceneSegmentsRead:
    """The live checks, over a payload already proven against the scene's current build."""
    bindings = payload["bindings"]
    artifact = {
        "artifact_id": candidate["artifact_id"],
        "content_sha256": bytes(candidate["content_sha256"]).hex(),
        "byte_size": int(candidate["byte_size"]),
        **receipts,
    }

    member_ids = [uuid.UUID(member) for member in members]
    current_masks = {
        (str(item["capture_id"]), str(item["artifact_id"]), bytes(item["content_sha256"]).hex())
        for item in connection.execute(
            _SEGMENT_OBJECT_MASKS, (workspace, member_ids, OBJECT_MASK_KIND)
        ).fetchall()
    }
    bound_masks = {
        (item["capture_ref"], item["artifact_ref"], item["content_sha256"])
        for item in bindings["object_mask_inputs"]
    }
    if current_masks != bound_masks or set(bindings["object_mask_missing"]) & {
        capture for capture, _, _ in current_masks
    }:
        changed = sorted(
            {capture for capture, _, _ in current_masks ^ bound_masks}
            | (set(bindings["object_mask_missing"]) & {c for c, _, _ in current_masks})
        )
        return SceneSegmentsRead(
            scene_id,
            "stale",
            "A member's object masks changed after these segments were lifted.",
            stale_inputs=tuple(f"object_masks:{capture}" for capture in changed),
            **artifact,
        )

    dead_point_maps = {
        item["content_sha256"]
        for item in bindings["point_map_inputs"]
        if not _point_map_live(connection, workspace, store, item)
    }
    eligible = {
        (str(item["capture_id"]), item["region_key"]): item
        for item in connection.execute(_SEGMENT_PEOPLE, (workspace, member_ids)).fetchall()
    }
    bound_people = {
        (item["capture_ref"], item["region_key"]) for item in bindings["person_regions"]
    }
    stale_inputs = tuple(
        f"person_region_added:{capture}:{key}"
        for capture, key in sorted(set(eligible) - bound_people)
    )

    spans = _span_ids(
        connection,
        workspace,
        {
            region["span_digest"]
            for segment in payload["segments"]
            for region in segment["regions"]
            if region.get("kind") == "object_mask"
        },
    )
    occurrences = _object_occurrences(
        connection,
        workspace,
        {
            region["prompt_span_digest"]
            for segment in payload["segments"]
            for region in segment["regions"]
            if region.get("kind") == "object_mask" and region.get("prompt_span_digest")
        },
    )
    served: list[dict[str, Any]] = []
    withheld = 0
    for segment in payload["segments"]:
        view = _served_segment(segment, dead_point_maps, eligible, bound_masks, spans, occurrences)
        if view is None:
            withheld += 1
        else:
            served.append(view)
    return SceneSegmentsRead(
        scene_id,
        "available",
        None,
        voxel_size_microunits=int(payload["grid"]["voxel_size_microunits"]),
        policy=dict(payload["policy"]),
        segments=tuple(served),
        withheld_segment_count=withheld,
        stale_inputs=stale_inputs,
        live_artifact_ids=(
            candidate["artifact_id"],
            *sorted(uuid.UUID(artifact_ref) for _, artifact_ref, _ in bound_masks),
        ),
        **artifact,
    )


def _segments_payload(
    data: bytes, scene_ref: str, receipts: dict[str, str], members: list[str]
) -> dict[str, Any] | None:
    """Parse and prove one segments artifact against the scene's current build."""
    envelope = json.loads(data)
    if not isinstance(envelope, dict) or envelope.get("profile") != _SEGMENTS_ENVELOPE:
        return None
    payload = envelope.get("segments")
    if not isinstance(payload, dict) or payload.get("profile") != _SEGMENTS_PROFILE:
        return None
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    if envelope.get("payload_sha256") != digest or payload.get("scene_ref") != scene_ref:
        return None
    bindings = payload["bindings"]
    if any(bindings.get(field) != value for field, value in receipts.items()):
        return None
    if bindings.get("member_capture_refs") != members:
        return None
    for segment in payload["segments"]:
        identity = {key: segment[key] for key in ("kind", "label", "subject_ref", "voxels")}
        recomputed = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()[:32]
        if segment["segment_id"] != recomputed or segment["kind"] not in ("object", "person"):
            return None
        if segment["kind"] == "person" and segment["label"] is not None:
            return None
    return payload


def _point_map_live(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    store: ContentAddressedStore,
    item: dict[str, Any],
) -> bool:
    """Whether one bound point map is still a live row with its bytes present."""
    try:
        capture = uuid.UUID(str(item["capture_ref"]))
        artifact = uuid.UUID(str(item["artifact_ref"]))
        digest = bytes.fromhex(str(item["content_sha256"]))
    except (KeyError, ValueError):
        return False
    live = connection.execute(
        _SEGMENT_POINT_MAP, (capture, workspace, artifact, POINT_MAP_KIND, digest)
    ).fetchone()
    return live is not None and len(digest) == 32 and store.exists(BlobId(digest))


def _span_ids(
    connection: psycopg.Connection, workspace: uuid.UUID, digests: set[str]
) -> dict[str, uuid.UUID]:
    if not digests:
        return {}
    rows = connection.execute(
        "select span_id, encode(span_digest, 'hex') as digest from evidence_span "
        "where workspace_id = %s and span_digest = any(%s)",
        (workspace, [bytes.fromhex(digest) for digest in sorted(digests)]),
    ).fetchall()
    return {row["digest"]: row["span_id"] for row in rows}


def _object_occurrences(
    connection: psycopg.Connection, workspace: uuid.UUID, digests: set[str]
) -> dict[str, list[uuid.UUID]]:
    """The vision stage's object occurrences standing on each hosted prompt's span.

    These are what the naming flow names. A mask prompted by the local detector has no hosted
    occurrence, and its segment offers none rather than one invented for it.
    """
    if not digests:
        return {}
    rows = connection.execute(
        "select encode(e.span_digest, 'hex') as digest, o.occurrence_id from occurrence o "
        "join evidence_span e on e.workspace_id = o.workspace_id "
        "and e.span_id = o.primary_span_id "
        "where o.workspace_id = %s and o.class = 'object' and e.span_digest = any(%s) "
        "order by o.occurrence_id",
        (workspace, [bytes.fromhex(digest) for digest in sorted(digests)]),
    ).fetchall()
    found: dict[str, list[uuid.UUID]] = {}
    for row in rows:
        found.setdefault(row["digest"], []).append(row["occurrence_id"])
    return found


def _served_segment(
    segment: dict[str, Any],
    dead_point_maps: set[str],
    eligible: dict[tuple[str, str], dict[str, Any]],
    bound_masks: set[tuple[str, str, str]],
    spans: dict[str, uuid.UUID],
    occurrences: dict[str, list[uuid.UUID]],
) -> dict[str, Any] | None:
    """One segment in its wire shape, or None when a live check withholds it."""
    if dead_point_maps & set(segment["point_map_sources"]):
        return None
    mask_artifacts = {artifact for _, artifact, _ in bound_masks}
    display_name = None
    regions: list[dict[str, Any]] = []
    nameable: list[uuid.UUID] = []
    for region in segment["regions"]:
        if region["kind"] == "person_region":
            current = eligible.get((region["capture_ref"], region["region_key"]))
            if (
                segment["kind"] != "person"
                or current is None
                or current["region_digest"] != region["region_digest"]
                or str(current["subject_id"]) != segment["subject_ref"]
            ):
                return None
            display_name = display_name or current["display_name"]
            regions.append(
                {
                    "capture_id": region["capture_ref"],
                    "kind": "person_region",
                    "span_id": None,
                    "region_key": region["region_key"],
                    "samples": int(region["samples"]),
                }
            )
        elif region["kind"] == "object_mask":
            if segment["kind"] != "object" or region["artifact_ref"] not in mask_artifacts:
                return None
            span = spans.get(region["span_digest"])
            regions.append(
                {
                    "capture_id": region["capture_ref"],
                    "kind": "object_mask",
                    "span_id": None if span is None else str(span),
                    "region_key": None,
                    "samples": int(region["samples"]),
                }
            )
            for occurrence in occurrences.get(region.get("prompt_span_digest") or "", []):
                if occurrence not in nameable:
                    nameable.append(occurrence)
        else:
            return None
    if segment["kind"] == "person" and not regions:
        return None
    return {
        "segment_id": segment["segment_id"],
        "kind": segment["kind"],
        "label": segment["label"],
        "subject_id": segment["subject_ref"],
        "display_name": display_name,
        "voxel_count": len(segment["voxels"]),
        "voxels": segment["voxels"],
        "bounds_microunits": segment["bounds_microunits"],
        "centroid_microunits": segment["centroid_microunits"],
        "samples": segment["samples"],
        "votes": segment["votes"],
        "regions": regions,
        "occurrence_ids": [str(item) for item in sorted(nameable)],
    }


def scene_segments_artifacts_live(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    read: SceneSegmentsRead,
    at: Any,
) -> bool:
    """Whether every artifact behind a segments answer is live at one instant.

    `asset_artifact_live` in migration 0041, the predicate the geometry route composes, asked of
    the segments artifact and of each bound segmentation artifact.
    """
    return all(
        connection.execute(
            "select asset_artifact_live(%s, %s, %s) as live", (workspace, artifact_id, at)
        ).fetchone()["live"]
        for artifact_id in read.live_artifact_ids
    )
