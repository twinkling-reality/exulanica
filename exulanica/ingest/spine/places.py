"""The three tables a place lives on, and the two reads a joint reconstruction needs first.

``docs/place-identity.md`` decides that a place is a durable plane of its own: ``place``,
``place_version`` and ``place_alignment``, added by migration 0038. This module is the SQL half
of that plane and nothing else, in the same division the rest of this package keeps: a function
here is a table, and the sentence a build says is in ``exulanica.ingest.place_alignment``.

Two of the reads below are not writes to those tables and are here anyway, because they exist
only to feed one. :func:`retained_pose_receipt` is the input the whole build rests on, and the
shape of that query is the load-bearing part: a place alignment's correspondences come from the
receipts two scenes already retained, never from a fresh read over their sparse tracks, because
COLMAP point ids mean nothing across two reconstructions and this system persists no learned
descriptors that could be matched instead. A scene with no retained pose receipt therefore has
no correspondences at all, and this returns None so the caller can say so rather than invent
them.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from exulanica.db.guards import terminal_if_tombstoned
from exulanica.evidence.blob import BlobId
from exulanica.ingest.spine.scope import WorkspaceScope

__all__ = [
    "PlaceAlignmentRow",
    "PlaceSceneMember",
    "PlaceVersionRow",
    "RetainedPoseReceipt",
    "alignment",
    "artifact_content_sha256",
    "earliest_capture_time",
    "find_alignment",
    "insert_alignment",
    "insert_place",
    "insert_place_artifact",
    "insert_version",
    "next_ordinal",
    "retained_pose_receipt",
    "scene_blocked",
    "scene_members",
    "version",
    "version_of_scene",
]


@dataclass(frozen=True, slots=True)
class PlaceSceneMember:
    """One photograph of one scene, with everything a joint manifest needs to stage it."""

    capture_id: uuid.UUID
    ordinal: int
    registered: bool | None
    blob_id: BlobId
    media_type: str


@dataclass(frozen=True, slots=True)
class RetainedPoseReceipt:
    artifact_id: uuid.UUID
    content_sha256: bytes
    storage_key: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class PlaceAlignmentRow:
    alignment_id: uuid.UUID
    place_id: uuid.UUID
    candidate_scene_id: uuid.UUID
    against_scene_id: uuid.UUID
    accepted: bool
    reason: str | None
    receipt_artifact_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class PlaceVersionRow:
    place_id: uuid.UUID
    scene_id: uuid.UUID
    ordinal: int
    frame_hops: int
    admitted_by_alignment_id: uuid.UUID | None


def insert_place(scope: WorkspaceScope, *, place_id: uuid.UUID) -> bool:
    """Allocate one durable place. False means it was already there.

    The id is passed in rather than defaulted by the column, because a caller that cannot name
    the row it just created cannot write the anchor version that gives the place a frame, and a
    place with no anchor is blocked by ``tombstone_blocks_place`` until it has one.
    """
    cursor = scope.connection.execute(
        "insert into place (place_id, workspace_id) values (%s, %s) "
        "on conflict (workspace_id, place_id) do nothing",
        (place_id, scope.workspace_id),
    )
    return cursor.rowcount > 0


def scene_members(scope: WorkspaceScope, scene_id: uuid.UUID) -> list[PlaceSceneMember]:
    """Every member of one scene in its recorded order, with its bytes and its media type.

    The media type comes from ``blob`` rather than from the scene, because the joint manifest
    names a file on disk and the extension is a property of the bytes.
    """
    rows = scope.connection.execute(
        "select m.capture_id,m.ordinal,m.registered,c.blob_sha256,b.media_type "
        "from reconstruction_scene_member m "
        "join capture c on c.workspace_id=m.workspace_id and c.capture_id=m.capture_id "
        "join blob b on b.blob_sha256=c.blob_sha256 "
        "where m.workspace_id=%s and m.scene_id=%s order by m.ordinal,m.capture_id",
        (scope.workspace_id, scene_id),
    ).fetchall()
    return [
        PlaceSceneMember(
            capture_id=row["capture_id"],
            ordinal=int(row["ordinal"]),
            registered=row["registered"],
            blob_id=BlobId(bytes(row["blob_sha256"])),
            media_type=row["media_type"],
        )
        for row in rows
    ]


def earliest_capture_time(scope: WorkspaceScope, scene_id: uuid.UUID) -> dt.datetime | None:
    """The earliest ``capture.started_at`` over a scene's members, or None when none has one.

    A scene has no capture-time column, and 0001 calls this one a best estimate only. It is read
    once, at bind time, so a corrected photograph does not later rearrange a place's history;
    None is recorded as the ``unavailable`` basis rather than guessed at.
    """
    row = scope.connection.execute(
        "select min(c.started_at) as started_at from reconstruction_scene_member m "
        "join capture c on c.workspace_id=m.workspace_id and c.capture_id=m.capture_id "
        "where m.workspace_id=%s and m.scene_id=%s and c.deleted_at is null",
        (scope.workspace_id, scene_id),
    ).fetchone()
    return None if row is None else row["started_at"]


def scene_blocked(scope: WorkspaceScope, scene_id: uuid.UUID) -> bool:
    """Does deletion reach this scene. Asked again while COLMAP owns the CPU."""
    row = scope.connection.execute(
        "select tombstone_blocks_scene(%s, %s) as blocked", (scope.workspace_id, scene_id)
    ).fetchone()
    return bool(row is not None and row["blocked"])


def retained_pose_receipt(scope: WorkspaceScope, scene_id: uuid.UUID) -> RetainedPoseReceipt | None:
    """The current retained pose receipt of one scene, or None when it has none.

    None is a real answer and the caller must treat it as one. Every correspondence a place
    alignment fits comes from the ``camera_centre_xyz`` this receipt kept per registered
    photograph, so a scene without one contributes no correspondences and cannot be admitted to
    a place. Filling that gap by recomputing camera centres from anything else would be a
    measurement of a frame nobody retained.

    The ordering matches :func:`exulanica.ingest.spine.artifacts.current_for_captures`: the
    highest stage version, then the newest row, then the id, so a re-run under a later stage
    version supersedes rather than ties.
    """
    row = scope.connection.execute(
        "select a.artifact_id,a.content_sha256,a.storage_key,a.byte_size from artifact a "
        "where a.workspace_id=%s and a.scene_id=%s and a.kind='pose_receipt' "
        "and a.superseded_by is null and a.purged_at is null and a.content_sha256 is not null "
        "and a.storage_key is not null and a.byte_size is not null "
        "and not tombstone_blocks_scene(a.workspace_id,a.scene_id) "
        "order by a.stage_version desc,a.created_at desc,a.artifact_id limit 1",
        (scope.workspace_id, scene_id),
    ).fetchone()
    if row is None:
        return None
    return RetainedPoseReceipt(
        artifact_id=row["artifact_id"],
        content_sha256=bytes(row["content_sha256"]),
        storage_key=row["storage_key"],
        byte_size=int(row["byte_size"]),
    )


def artifact_content_sha256(scope: WorkspaceScope, artifact_id: uuid.UUID) -> bytes | None:
    """The content address of one live artifact, for reading an earlier receipt back.

    A composed place transform is read off the receipt that measured the version it was composed
    through, because ``place_version`` deliberately records no transform: 0038 keeps measured
    numbers in digest-bound artifacts rather than in columns nothing recomputes.
    """
    row = scope.connection.execute(
        "select content_sha256 from artifact where workspace_id=%s and artifact_id=%s "
        "and purged_at is null and content_sha256 is not null",
        (scope.workspace_id, artifact_id),
    ).fetchone()
    return None if row is None else bytes(row["content_sha256"])


def insert_place_artifact(
    scope: WorkspaceScope,
    *,
    artifact_id: uuid.UUID,
    kind: str,
    place_id: uuid.UUID,
    stage_key: str,
    stage_version: int,
    params_digest: bytes,
    input_digest: bytes,
    idempotency_key: str,
    content_sha256: bytes,
    storage_key: str,
    byte_size: int,
    produced_by_event: uuid.UUID | None,
) -> bool:
    """Insert a derivative whose subject is a place. Returns False when it already existed.

    The third subject form ``artifact`` accepts, after a blob and a scene. A place alignment is
    measured over a PAIR of scenes, so attaching its receipt to either one would be a claim
    about one scene that was measured over two, and the claim would be invisible from the scene
    side. 0038's ``an_artifact_names_one_subject`` still allows exactly one.
    """
    with terminal_if_tombstoned():
        cursor = scope.connection.execute(
            "insert into artifact (artifact_id, workspace_id, kind, place_id, stage_key, "
            "stage_version, params_digest, input_digest, idempotency_key, content_sha256, "
            "storage_key, byte_size, produced_by_event) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "on conflict (workspace_id, idempotency_key) do nothing",
            (
                artifact_id,
                scope.workspace_id,
                kind,
                place_id,
                stage_key,
                stage_version,
                params_digest,
                input_digest,
                idempotency_key,
                content_sha256,
                storage_key,
                byte_size,
                produced_by_event,
            ),
        )
    return cursor.rowcount > 0


def _alignment_row(row: dict) -> PlaceAlignmentRow:
    return PlaceAlignmentRow(
        alignment_id=row["alignment_id"],
        place_id=row["place_id"],
        candidate_scene_id=row["candidate_scene_id"],
        against_scene_id=row["against_scene_id"],
        accepted=bool(row["accepted"]),
        reason=row["reason"],
        receipt_artifact_id=row["receipt_artifact_id"],
    )


_ALIGNMENT_COLUMNS = (
    "alignment_id,place_id,candidate_scene_id,against_scene_id,accepted,reason,receipt_artifact_id"
)


def find_alignment(
    scope: WorkspaceScope,
    *,
    place_id: uuid.UUID,
    candidate_scene_id: uuid.UUID,
    against_scene_id: uuid.UUID,
    union_member_digest: bytes,
    policy_digest: bytes,
) -> PlaceAlignmentRow | None:
    """The verdict this exact build already reached, or None.

    Keyed on 0038's own unique constraint, so "has this been run" is asked of the six columns
    the database uses to refuse a second verdict rather than of a re-derived guess at them. One
    build over one union under one policy has one answer, accepted or refused.
    """
    row = scope.connection.execute(
        f"select {_ALIGNMENT_COLUMNS} from place_alignment "
        "where workspace_id=%s and place_id=%s and candidate_scene_id=%s "
        "and against_scene_id=%s and union_member_digest=%s and policy_digest=%s",
        (
            scope.workspace_id,
            place_id,
            candidate_scene_id,
            against_scene_id,
            union_member_digest,
            policy_digest,
        ),
    ).fetchone()
    return None if row is None else _alignment_row(row)


def alignment(scope: WorkspaceScope, alignment_id: uuid.UUID) -> PlaceAlignmentRow | None:
    row = scope.connection.execute(
        f"select {_ALIGNMENT_COLUMNS} from place_alignment where workspace_id=%s "
        "and alignment_id=%s",
        (scope.workspace_id, alignment_id),
    ).fetchone()
    return None if row is None else _alignment_row(row)


def insert_alignment(
    scope: WorkspaceScope,
    *,
    alignment_id: uuid.UUID,
    place_id: uuid.UUID,
    candidate_scene_id: uuid.UUID,
    against_scene_id: uuid.UUID,
    union_member_digest: bytes,
    policy_digest: bytes,
    joint_model_sha256: bytes | None,
    accepted: bool,
    reason: str | None,
    receipt_artifact_id: uuid.UUID,
) -> bool:
    """Record one joint reconstruction, accepted or refused. False means it was already there.

    A refusal is a row like any other. That is the whole posture of this plane: a refused pair
    stays two places and the world can say their frames could not be reconciled, which it cannot
    say from an absent row or from an exception somebody logged.
    """
    cursor = scope.connection.execute(
        "insert into place_alignment (alignment_id, workspace_id, place_id, "
        "candidate_scene_id, against_scene_id, union_member_digest, policy_digest, "
        "joint_model_sha256, accepted, reason, receipt_artifact_id) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "on conflict (workspace_id, place_id, candidate_scene_id, against_scene_id, "
        "union_member_digest, policy_digest) do nothing",
        (
            alignment_id,
            scope.workspace_id,
            place_id,
            candidate_scene_id,
            against_scene_id,
            union_member_digest,
            policy_digest,
            joint_model_sha256,
            accepted,
            reason,
            receipt_artifact_id,
        ),
    )
    return cursor.rowcount > 0


def version(
    scope: WorkspaceScope, *, place_id: uuid.UUID, scene_id: uuid.UUID
) -> PlaceVersionRow | None:
    row = scope.connection.execute(
        "select place_id,scene_id,ordinal,frame_hops,admitted_by_alignment_id "
        "from place_version where workspace_id=%s and place_id=%s and scene_id=%s",
        (scope.workspace_id, place_id, scene_id),
    ).fetchone()
    return None if row is None else _version_row(row)


def version_of_scene(scope: WorkspaceScope, scene_id: uuid.UUID) -> PlaceVersionRow | None:
    """The place this scene already belongs to, if any.

    A scene belongs to at most one place, because two places claiming one scene would be two
    coordinate frames claiming one set of photographs. Asked before a joint run rather than
    discovered as a unique violation after forty-five minutes of matching.
    """
    row = scope.connection.execute(
        "select place_id,scene_id,ordinal,frame_hops,admitted_by_alignment_id "
        "from place_version where workspace_id=%s and scene_id=%s",
        (scope.workspace_id, scene_id),
    ).fetchone()
    return None if row is None else _version_row(row)


def _version_row(row: dict) -> PlaceVersionRow:
    return PlaceVersionRow(
        place_id=row["place_id"],
        scene_id=row["scene_id"],
        ordinal=int(row["ordinal"]),
        frame_hops=int(row["frame_hops"]),
        admitted_by_alignment_id=row["admitted_by_alignment_id"],
    )


def next_ordinal(scope: WorkspaceScope, *, place_id: uuid.UUID) -> int:
    """One past the highest ordinal this place holds; 0 for a place with no versions."""
    row = scope.connection.execute(
        "select coalesce(max(ordinal) + 1, 0) as next from place_version "
        "where workspace_id=%s and place_id=%s",
        (scope.workspace_id, place_id),
    ).fetchone()
    assert row is not None
    return int(row["next"])


def insert_version(
    scope: WorkspaceScope,
    *,
    place_id: uuid.UUID,
    scene_id: uuid.UUID,
    ordinal: int,
    ordered_by_utc: dt.datetime | None,
    ordered_by_basis: str,
    frame_hops: int,
    admitted_by_alignment_id: uuid.UUID | None,
) -> bool:
    """Bind one scene to one place. False means the binding was already there.

    Nothing is written to the scene. ``reconstruction_scene`` carries an append-only trigger
    that would refuse an UPDATE anyway, and a place is a join rather than a merge: the scene's
    own receipts, rung and digests are untouched by joining one.
    """
    cursor = scope.connection.execute(
        "insert into place_version (workspace_id, place_id, scene_id, ordinal, ordered_by_utc, "
        "ordered_by_basis, frame_hops, admitted_by_alignment_id) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s) "
        "on conflict (workspace_id, place_id, scene_id) do nothing",
        (
            scope.workspace_id,
            place_id,
            scene_id,
            ordinal,
            ordered_by_utc,
            ordered_by_basis,
            frame_hops,
            admitted_by_alignment_id,
        ),
    )
    return cursor.rowcount > 0
