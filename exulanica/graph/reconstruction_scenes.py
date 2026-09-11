"""Validated multi-photograph reconstruction scenes for the graph snapshot.

The database says what a scene recorded. The object store says what can be drawn. Those answers
are deliberately separate: a missing placement object never rewrites an earned rung, and an
earned rung never causes a renderer reference to be invented. A transform crosses this boundary
only after the pose, placement and gate envelopes reproduce their digests and agree with the
immutable scene members and exact point-map artifact rows.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Any, Final, Literal, NamedTuple

import psycopg

from exulanica.epistemics.vocabulary import RECONSTRUCTION_SCENE_RUNG_PREDICATE
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.graph.generated_geometry import generated_geometry_rows
from exulanica.graph.geometry import POINT_MAP_KIND
from exulanica.graph.payload import (
    ReconstructionSceneMemberRow,
    ReconstructionSceneRow,
    SceneGeometryReferenceRow,
    ScenePointMapPlacementRow,
    SceneRecoveredCameraRow,
)
from exulanica.graph.person_regions import (
    hidden_people,
    person_regions_for_captures,
    review_states_for_captures,
)
from exulanica.graph.scene_geometry import trained_geometry_row
from exulanica.reconstruction.placement import (
    PlacementRecord,
    PointMapInput,
    recovered_camera_records,
    validate_placement_record,
)
from exulanica.reconstruction.scene_gate import validate_scene_gate_decision
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


# -- the persisted scene projection -------------------------------------------------------------
#
# The memo below fixed the second graph read in a process. This fixes the first.
#
# MEASURED 2026-09-09 and recorded in `docs/evaluation/2026-09-09-graph-read-memo.json`: a cold
# `GET /graph` for the 210 member volcanic scene was 47.9 s, and every second of it went on
# rebuilding an answer the scene worker had already computed and verified when the scene
# published. So the worker now writes that answer down as a fourth scene artifact, and this reader
# serves it instead of rebuilding, when and only when it can prove the projection still answers
# for the scene in front of it.
#
# WHAT IS PROVED BEFORE ONE IS USED, and each of these is a way a projection can go stale:
#
# *   The three receipt digests. A rebuilt scene has different ones, so a projection from a
#     superseded build is a different artifact rather than a stale answer.
# *   The member capture refs, in scene order. This is the one input no digest covers: withdrawing
#     a member leaves all three receipts byte-identical, and the projection must stop answering.
# *   The placement's point-map references, in record order. This one is a self-check rather
#     than an independent fact: both sides derive from the placement bytes, which the digest
#     above already pins, so it cannot refuse a projection that binding accepts. It is kept
#     because it makes the artifact auditable on its own and because the producer checks its
#     own output against it. What actually sees a superseded, re-pointed or purged point-map
#     ARTIFACT ROW is `_point_map_references`, which raises before any projection is read.
# *   That every one of those point maps is present AND reproduces its content digest. A
#     projection asserts geometry for the members it placed, so the bytes behind those members are
#     read through the store, which re-hashes them, and dropped. If one is gone or has rotted the
#     honest answer is the rebuild's, which erases that member's geometry and reports
#     `alignment-unavailable`. MEASURED 2026-09-10: 0.385 s of a 0.889 s cold route body under
#     cProfile, and 1.031 s standalone for all 780.3 MB when the page cache is cold. Hashing
#     was never what made the cold read 48 s; the 19,493,182 point Python walk in
#     `validate_opm` and the per-member scale fit were, and those are what a projection
#     replaces. Keeping the verification is what lets three existing tests about a rotted
#     point map go on passing unchanged.
#
# ANY of those failing falls back to the rebuild, which is the behaviour this reader had before the
# projection existed. So does a projection that is absent, purged, flagged for repair, unparseable
# or failing its own payload digest. There is no case in which a refused projection is worse than
# no projection: it costs the rebuild, which is what the reader would have done anyway.
#
# WHAT A PROJECTION IS NOT TRUSTED FOR. Nothing live. The artifact rows with their `purged_at` and
# tombstone predicates, the scene's members, the gate agreement, the person regions and review
# states, and the asset-read policy the route applies afterwards are all re-read on every request
# exactly as before. A projection shortens one computation; it does not answer one question about
# permission or liveness.
#
# The bytes are parsed here rather than by calling into `exulanica/ingest/scene_projection.py`,
# which is the producer, because the layers contract in `pyproject.toml` makes `graph`, `selection`
# and `ingest` siblings and none may import another. `POINT_MAP_KIND` is spelled twice for the same
# reason, in `exulanica/graph/geometry.py` and in the stage registry, pinned by a test.
#
# BUT THAT IS NOT THE ONLY SHAPE AVAILABLE, and the honest note is that it is not the best one.
# `GENERATED_SCENE_KIND` is spelled ONCE, in `exulanica/reconstruction/generated.py`, and imported
# by both siblings, because `exulanica.reconstruction` sits BELOW both of them and its forbidden
# contract bans only evidence, store, db, ingest, identity and selection. `scene_projection.py`
# imports nothing but the standard library and `exulanica.reconstruction.placement`, so it would be
# legal there today, unmoved, and this module already imports `validate_placement_record` and
# `validate_scene_gate_decision` from that layer for the other three scene artifacts. Putting it
# there would delete this reader's copy of the parser outright. The brief that asked for this work
# named `exulanica/ingest/scene_projection.py`, so that is where it is; the duplication below is a
# consequence of that placement rather than of the layering.

#: Spelled here as well as in `exulanica/ingest/scene_projection.py`. A test pins them together.
SCENE_PROJECTION_KIND: Final = "scene_projection"
_PROJECTION_PROFILE: Final = "exulanica.scene-graph-projection/v1"
_PROJECTION_ENVELOPE: Final = "exulanica.scene-graph-projection-envelope/v1"


# -- the validated placement memo ---------------------------------------------------------------
#
# MEASURED 2026-09-09 against the retained reference copy: `GET /graph` took 48.0, 51.1 and 50.6
# seconds for the 210 member volcanic scene, and 21.7, 21.5 and 21.4 seconds for the 91 member bowl
# whose geometry is withheld anyway. Both work out at about 0.24 seconds per member. The asset-read
# policy is not the cost: both `scene_allowed` passes together are 252 ms and every per-member
# predicate together is 242 ms. The cost is here, in `_scene_row`, which re-reads the scene's blobs
# and rebuilds the placement on every request: `store.get` verifies 780 MB of point maps and a
# 108 MB pose receipt, `fit_point_map_scale` runs once per member and `validate_opm` walks all
# 19,493,182 points in Python.
#
# None of that work depends on anything mutable. The pose receipt, the placement record, the gate
# receipt and every point map are content addressed, and their digests are columns on the scene row
# this function already read. So the rebuilt placement and the recovered cameras are memoised on
# those digests, on the scene's member list, and on whether each point map's bytes are present. On
# a hit the pose receipt and the point maps are not fetched at all, which is where most of the time
# went.
#
# What is deliberately NOT memoised is everything that can change without a digest changing: the
# scene's members, the person regions and review states, the artifact rows with their `purged_at`
# and tombstone predicates, the gate agreement, and the asset-read policy the route applies
# afterwards. Those are re-read on every request exactly as before.
#
# THE TRADE THIS MAKES, precisely. Before this memo every graph read pulled each point map through
# `store.get`, which re-hashes the bytes, so a blob that had rotted on disk came back as `content=
# None`, its member was excluded as `alignment-unavailable`, and no fetch reference was emitted for
# it. On a memo hit the only per-request check is `store.exists`, a bare `is_file()`. So a point map
# whose bytes are present but no longer hash to their key is now reported as placed and available,
# with a `/geometry` reference, until the entry is evicted or `clear_placement_memo` is called. The
# bytes themselves are still safe: `exulanica/api/routes/geometry.py` reads them through the store
# and refuses on `IntegrityError`, so a visitor gets a refusal rather than wrong geometry. What is
# lost is that the graph used to withhold the reference instead of advertising it. A purge IS still
# seen, because presence is in the key, and a REPAIR is seen too, because a record built from a
# failed digest read is never cached in the first place.
#
# The bound is on total members rather than on entries, because that is what tracks memory:
# MEASURED 2026-09-09 on the 210 member volcanic scene, one entry was 639.6 KiB, or 3.05 KiB per
# member, and held no point-map bytes at all. 20,000 members was therefore about 60 MiB. Bounding by
# entry count would have been the wrong unit: sixteen tiny scenes and sixteen large ones are three
# orders of magnitude apart.
#
# That 639.6 KiB was measured when an entry held a whole `PlacementRecord`, with every member's
# alignment diagnostics and the rebuilt input bindings. It now holds `_Outcome`, which is the six
# fields `_scene_row` actually reads, so an entry is SMALLER than the figure above and the bound is
# correspondingly more conservative. The number has not been re-measured, so it is left as the
# ceiling it was rather than restated as something it no longer is.
#
# `reconstruction_scene_rows` sweeps every scene in the workspace on a graph read, so the access
# pattern is a cycle. A cycle longer than the bound evicts each entry before it is reused and the
# hit rate is zero, not merely lower. The bound is sized so that does not happen for any workspace
# this corpus has: 20,000 members is about 95 scenes the size of the volcanic one.

_MEMO_MAX_MEMBERS = 20_000


class _PointMapRef(NamedTuple):
    capture_ref: str
    artifact_ref: str
    content_sha256: str


_MemoKey = tuple[
    str,  # workspace
    str,  # scene ref
    str,  # pose receipt digest
    str,  # placement record digest
    str,  # gate receipt digest
    tuple[str, ...],  # member capture refs, in scene order
    tuple[_PointMapRef, ...],  # the placement's point-map references, in record order
    tuple[bool, ...],  # whether each of those point maps' bytes are present
    tuple[str, ...],  # the projections offered, so revoking one revokes the entry it filled
]


class _PlacedMember(NamedTuple):
    """One placed member, as the scene row emits it.

    Exactly the fields `_scene_row` reads and no others. It used to hold a whole `PlacementRecord`,
    which also carried each member's alignment diagnostics and the rebuilt input bindings; those
    are in the durable placement record where anybody who wants them can read them, and holding a
    second copy per memo entry bought nothing. This shape is also what a persisted projection
    carries, so the two paths reach the same object rather than two objects that agree.
    """

    point_map_artifact_ref: str
    point_map_content_sha256: str
    scene_from_opm: tuple[float, ...]
    local_units_to_scene_units: float
    scale_status: str


class _Outcome(NamedTuple):
    """Every scene member's placement outcome, keyed by capture ref."""

    placed: dict[str, _PlacedMember]
    excluded: dict[str, str]


_MemoValue = tuple[_Outcome, dict[str, dict[str, object]]]

_memo_lock = Lock()
_memo: OrderedDict[_MemoKey, _MemoValue] = OrderedDict()


def clear_placement_memo() -> None:
    """Forget every memoised placement.

    For tests, and for an operator who has replaced bytes under an existing digest, which the
    content-addressed store is not supposed to allow.
    """
    with _memo_lock:
        _memo.clear()


def placement_memo_size() -> int:
    """How many validated placements are currently held. For tests and for operational reporting."""
    with _memo_lock:
        return len(_memo)


def placement_memo_members() -> int:
    """How many scene members the held placements cover, which is what the bound is expressed in."""
    with _memo_lock:
        return sum(len(key[5]) for key in _memo)


def _memo_get(key: _MemoKey) -> _MemoValue | None:
    with _memo_lock:
        value = _memo.get(key)
        if value is not None:
            _memo.move_to_end(key)
        return value


def _memo_put(key: _MemoKey, value: _MemoValue) -> None:
    with _memo_lock:
        _memo[key] = value
        _memo.move_to_end(key)
        # Never evict down to nothing: one scene larger than the whole bound should still be held,
        # or it would be inserted and dropped on every request and the memo would be pure cost.
        while len(_memo) > 1 and sum(len(entry[5]) for entry in _memo) > _MEMO_MAX_MEMBERS:
            _memo.popitem(last=False)


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
 order by s.scene_id, a.asserted_at desc, a.assertion_id desc,
          j.completed_at desc nulls last, j.job_id desc
"""


def reconstruction_scene_rows(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    store: ContentAddressedStore | None,
    *,
    scene_id: uuid.UUID | None = None,
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
            RECONSTRUCTION_SCENE_RUNG_PREDICATE,
            SCENE_PROJECTION_KIND,
            workspace,
            scene_id,
            scene_id,
        ),
    ).fetchall()
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
            # so the module's claim above, that a refused projection is never worse than no
            # projection, is true rather than nearly true.
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
                    person_regions=people.get(capture_ref, []),
                    person_review_state=review_state.get(capture_ref, "unscreened"),
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
                person_regions=people.get(capture_ref, []),
                person_review_state=review_state.get(capture_ref, "unscreened"),
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
        hidden_person_count=hidden_count,
        masked_member_count=masked_members,
        trained_geometry=trained,
        members=output_members,
        generated_geometry=generated_geometry_rows(connection, workspace, scene_id, store),
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


def _verifies(store: ContentAddressedStore, blob: BlobId) -> bool:
    """Whether one object is present and reproduces its content address.

    For the pose receipt on the projection path. The presence check at the top of `_scene_row` is
    a bare `is_file()`, and the rebuild is what used to re-hash the receipt, so without this a
    receipt that had rotted would be reported `receipt_state="available"` where it used to be
    reported `"invalid"`. The route withholds the geometry either way, because `scene_inputs` does
    its own verified read, but the scene row would have been saying something untrue about the
    receipt chain. MEASURED 2026-09-10 on the 108,267,697 byte volcanic receipt: reading it is
    0.094 s and hashing it 0.047 s, which is what this costs.
    """
    try:
        store.get(blob)
    except (BlobNotFoundError, IntegrityError):
        return False
    return True


def _point_maps_verify(store: ContentAddressedStore, references: tuple[_PointMapRef, ...]) -> bool:
    """Whether every referenced point map is present and reproduces its content digest.

    Reads through the store, which re-hashes, and drops each object immediately: the projection
    path wants the verdict, not the bytes. A false answer sends the read to the rebuild, which
    reads them again and erases the affected member's geometry, so nothing here has to decide
    which member was at fault.
    """
    for reference in references:
        if _point_map_bytes(store, reference.content_sha256).content is None:
            return False
    return True


def _projected(
    store: ContentAddressedStore,
    projection_digests: object,
    *,
    scene_id: uuid.UUID,
    pose_digest: str,
    placement_digest: str,
    gate_digest: str,
    member_refs: tuple[str, ...],
    references: tuple[_PointMapRef, ...],
) -> _MemoValue | None:
    """The published projection for this exact scene state, or None to rebuild instead.

    Every refusal returns None rather than raising, because a projection is an optimisation and
    the reader has a correct, slower answer for every case in which one cannot be used. Raising
    would reach the fallback handlers in `_scene_row` and report a scene as having an inconsistent
    receipt chain, which would be a false statement about the pose, placement and gate records.

    The candidates are the newest four the lateral found. `array_agg` over an ordered subquery
    fixes which four, not the order they arrive in, so this makes no assumption about order:
    each is proved independently and any that passes every binding answers for the same scene
    state as any other that would.
    """
    for candidate in projection_digests or ():
        try:
            # `BlobId` is constructed inside the guard, not before it. `artifact.content_sha256` is
            # a bare `bytea` with no length constraint, and a value that is not 32 bytes raises
            # `InvalidAddressError`, which is a ValueError. Outside the guard it would reach
            # `_scene_row` and report a scene whose three receipts are perfectly sound as an
            # inconsistent receipt chain, dropping its geometry, its person regions and its
            # generated geometry. A projection must never make a scene worse than no projection.
            data = store.get(BlobId(bytes(candidate)))
        except (BlobNotFoundError, IntegrityError, TypeError, ValueError):
            continue
        try:
            projected = _read_projection(
                data,
                scene_id=scene_id,
                pose_digest=pose_digest,
                placement_digest=placement_digest,
                gate_digest=gate_digest,
                member_refs=member_refs,
                references=references,
            )
        except (KeyError, TypeError, ValueError):
            continue
        if projected is not None:
            return projected
    return None


def _read_projection(
    data: bytes,
    *,
    scene_id: uuid.UUID,
    pose_digest: str,
    placement_digest: str,
    gate_digest: str,
    member_refs: tuple[str, ...],
    references: tuple[_PointMapRef, ...],
) -> _MemoValue | None:
    """Parse and prove one projection. Returns None when it does not answer for this scene."""
    envelope = json.loads(data)
    if not isinstance(envelope, dict) or envelope.get("profile") != _PROJECTION_ENVELOPE:
        return None
    payload = envelope.get("projection")
    if (
        not isinstance(payload, dict)
        or payload.get("profile") != _PROJECTION_PROFILE
        or payload.get("scene_ref") != str(scene_id)
    ):
        return None
    # The payload digest is checked even though `store.get` already verified the object's own
    # content address, because the two answer different questions: the store proves these are the
    # bytes that were stored, and this proves the payload is the one the envelope commits to.
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    if envelope.get("payload_sha256") != digest:
        return None

    bindings = payload.get("bindings")
    if not isinstance(bindings, dict):
        return None
    if (
        bindings.get("pose_receipt_sha256") != pose_digest
        or bindings.get("placement_receipt_sha256") != placement_digest
        or bindings.get("gate_receipt_sha256") != gate_digest
        or bindings.get("member_capture_refs") != list(member_refs)
    ):
        return None
    bound = bindings.get("point_map_inputs")
    if not isinstance(bound, list) or len(bound) != len(references):
        return None
    for item, reference in zip(bound, references, strict=True):
        if not isinstance(item, dict) or (
            item.get("capture_ref"),
            item.get("artifact_ref"),
            item.get("content_sha256"),
        ) != tuple(reference):
            return None

    # A placed member must name one of the point-map references this projection is bound to, and
    # exactly. The rebuild cannot produce anything else: `build_placement_record` emits a placed
    # member only for a capture that has a `PointMapInput` and copies both refs straight off it.
    #
    # This is also where the reader's OWN safety comes from, and it is the reason the check is a
    # set membership rather than a shape test. Three of these values are consumed further down
    # `_scene_row` and OUTSIDE its fallback handlers: `artifacts[capture_ref]`,
    # `BlobId.from_hex(point_map_content_sha256)` and `uuid.UUID(point_map_artifact_ref)`. Every
    # triple in `references` has already been through `uuid.UUID` and `bytes.fromhex` in
    # `_point_map_references`, so matching one proves all three are well formed. Without this a
    # projection naming a capture with no point map, or a malformed digest, would be a 500 for the
    # whole snapshot rather than a fallback, which is the one way a bad projection could be worse
    # than no projection.
    bound_triples = {tuple(reference) for reference in references}
    placed: dict[str, _PlacedMember] = {}
    for raw in payload["placed"]:
        matrix = raw["scene_from_opm_row_major"]
        if not isinstance(matrix, list) or len(matrix) != 16:
            return None
        triple = (
            raw["capture_ref"],
            raw["point_map_artifact_ref"],
            raw["point_map_content_sha256"],
        )
        if triple not in bound_triples or raw["scale_status"] != _SCALE_STATUS:
            return None
        transform = tuple(_number(value) for value in matrix)
        scale = _number(raw["local_units_to_scene_units"])
        if not _valid_transform(transform, scale):
            return None
        placed[str(raw["capture_ref"])] = _PlacedMember(
            point_map_artifact_ref=str(raw["point_map_artifact_ref"]),
            point_map_content_sha256=str(raw["point_map_content_sha256"]),
            scene_from_opm=transform,
            local_units_to_scene_units=scale,
            scale_status=str(raw["scale_status"]),
        )
    excluded: dict[str, str] = {}
    for raw in payload["excluded"]:
        if raw["reason"] not in _EXCLUSION_REASONS:
            return None
        excluded[str(raw["capture_ref"])] = str(raw["reason"])
    # Exactly one outcome per member, which is what makes `excluded[capture_ref]` below safe for
    # every member the placement did not place.
    if len(placed) + len(excluded) != len(member_refs) or set(placed) | set(excluded) != set(
        member_refs
    ):
        return None
    cameras = _cameras(payload["recovered_cameras"])
    if cameras is None:
        return None
    return _Outcome(placed=placed, excluded=excluded), cameras


#: Exactly the fields `SceneRecoveredCameraRow` and `SceneRecoveredCalibrationRow` accept. Both
#: forbid an extra key, and they are constructed below outside this module's fallback handlers, so
#: a projection whose camera shape is wrong has to be refused HERE. Otherwise it is a 500 rather
#: than the rebuild, which is the one way a bad projection could be worse than no projection.
_CAMERA_FIELDS: Final = ("calibration", "projection", "scene_from_camera_row_major")
_CALIBRATION_FIELDS: Final = ("cx", "cy", "fx", "fy", "height", "model", "parameters", "width")
_CAMERA_PROJECTIONS: Final = ("pinhole", "pinhole-approximation")

#: The only scale status `ScenePointMapPlacementRow` accepts, and the five reasons
#: `ExcludedPlacementMember` can carry. Spelled here because the reader may not import either
#: producer, and because `ReconstructionSceneMemberRow.exclusion_reason` is a bare `str | None`:
#: without this a projection could put any string on the wire where the rebuild can emit only
#: these five, and a client switching on it would meet a state that does not exist. A test pins
#: both tuples against the producers.
_SCALE_STATUS: Final = "colmap-correspondence-fit"
_EXCLUSION_REASONS: Final = (
    "alignment-inconsistent",
    "alignment-insufficient-correspondences",
    "alignment-unavailable",
    "point-map-unavailable",
    "pose-not-registered",
)


def _cameras(value: object) -> dict[str, dict[str, object]] | None:
    """The projection's recovered cameras, or None if any one of them is not what the row takes."""
    if not isinstance(value, dict):
        return None
    for capture_ref, camera in value.items():
        if (
            not isinstance(capture_ref, str)
            or not isinstance(camera, dict)
            or tuple(sorted(camera)) != _CAMERA_FIELDS
            or camera["projection"] not in _CAMERA_PROJECTIONS
        ):
            return None
        matrix = camera["scene_from_camera_row_major"]
        calibration = camera["calibration"]
        if (
            not isinstance(matrix, list)
            or len(matrix) != 16
            or not isinstance(calibration, dict)
            or tuple(sorted(calibration)) != _CALIBRATION_FIELDS
            or not isinstance(calibration["model"], str)
            or not isinstance(calibration["parameters"], list)
        ):
            return None
        for field in ("width", "height"):
            if isinstance(calibration[field], bool) or not isinstance(calibration[field], int):
                return None
        for number in [*matrix, *calibration["parameters"]] + [
            calibration[field] for field in ("fx", "fy", "cx", "cy")
        ]:
            _number(number)
    return value


def _valid_transform(matrix: tuple[float, ...], scale: float) -> bool:
    """Whether a projected transform is one a renderer may be handed.

    The same conditions `_validate_matrix` in `exulanica/reconstruction/placement.py` applies to
    every placed member of a REBUILT record: affine last row, a positive finite scale, an
    orthonormal rotation once the scale is divided out, and a proper rotation rather than a
    reflection. Without them the reader would be less strict than the rebuild about the one value
    it hands to a renderer, so a projection carrying a negative scale or a mirrored rotation would
    be drawn where the rebuild refuses the whole record. Spelled here rather than imported because
    `_validate_matrix` is private to that module and raises where this must return a verdict.
    """
    if scale <= 0 or matrix[12:] != (0.0, 0.0, 0.0, 1.0):
        return False
    rotation = tuple(
        tuple(matrix[row * 4 + column] / scale for column in range(3)) for row in range(3)
    )
    for left in range(3):
        for right in range(3):
            dot = sum(rotation[row][left] * rotation[row][right] for row in range(3))
            if not math.isclose(dot, 1.0 if left == right else 0.0, rel_tol=1e-6, abs_tol=1e-6):
                return False
    determinant = (
        rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
        - rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
        + rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
    )
    return math.isclose(determinant, 1.0, rel_tol=1e-6, abs_tol=1e-6)


def _number(value: object) -> float:
    """A finite float, or a refusal. Guards the transforms a renderer will be handed."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("a projected number is not numeric")
    try:
        number = float(value)
    except OverflowError as error:
        # An integer literal too large for a double. `float()` raises OverflowError, which is NOT
        # a ValueError, so without this it would escape `_read_projection`, `_projected` and every
        # handler in `_scene_row` and turn one bad projection into a 500 for the whole snapshot.
        # `json.loads` turns 1e400 into inf, which the finiteness check below already refuses; it
        # is only the integer literal that reaches here, and its digest verifies like any other.
        raise ValueError("a projected number is out of range") from error
    if not math.isfinite(number):
        raise ValueError("a projected number is not finite")
    return number


class _PointMapBytes(NamedTuple):
    """What one point-map read produced, and whether it failed its digest rather than being absent.

    The distinction matters to the memo. `store.exists` is a bare presence test, so "present and
    valid" and "present but rotted" build the same key while producing different correct records.
    A result built from a failed digest is therefore never cached, so a repair under the same
    digest is picked up on the very next read instead of surviving for the life of the process.
    """

    content: bytes | None
    digest_failed: bool


def _point_map_bytes(store: ContentAddressedStore, content_sha256: str) -> _PointMapBytes:
    """The point map's bytes, or None when the object is gone or fails its digest.

    Absence is not an error here: `validate_placement_record` is called with
    `allow_unavailable_bytes`, which erases an unavailable member's geometry rather than
    withholding the whole scene.
    """
    try:
        return _PointMapBytes(store.get(BlobId.from_hex(content_sha256)), False)
    except BlobNotFoundError:
        return _PointMapBytes(None, False)
    except IntegrityError:
        return _PointMapBytes(None, True)


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
                exclusion_reason=(
                    "pose-not-registered" if not member.registered else "placement-unavailable"
                ),
                # A scene that collapsed to the fallback for some unrelated reason -- a bad gate,
                # a missing placement -- must not thereby report that it contains nobody. Until
                # the regions are resolved here too, the honest answer is that nothing screened
                # this photograph, which draws silhouettes rather than pixels.
                person_regions=[],
                person_review_state="unscreened",
            )
            for member in members
        ],
        # The fallback is reached when the receipts are unreadable, and it cannot resolve
        # generations either. An empty list here is honest only because it sits beside a
        # receipt_state that already says this reader could not read the scene: a client that
        # draws generated content at all reads `receipt_state` first.
        generated_geometry=[],
    )


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
