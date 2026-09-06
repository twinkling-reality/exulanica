"""Which photographs observed a point: recorded provenance, served for click-to-evidence.

Roadmap Phase 10, the Atlas half. A visitor selects a surface and asks what it is made of. The
honest answer is the set of photographs whose cameras actually observed that piece of the world,
and it exists: the pose stage retains a bounded sample of COLMAP's tracks in each recovered camera,
and COLMAP's ``point_id`` is global across the selected model, so grouping those rows by point id
reconstructs the real multi-view observation graph. Nothing was serving it.

**This is recorded, not inferred, and the distinction is the point.** The alternative available to
a client is to reproject a clicked world point into each recovered camera and rank by whether it
would land inside the frame. That answers "which camera could have seen this", which is a geometric
guess and is not what a viewer asking "what is this made of" wants to be told.

**The bounded sample travels with the answer.** 4096 observations per image are retained, ordered
by a hash of the point id, so the images held for one point are a subset of the images that saw it.
Every point therefore carries COLMAP's full ``track_length`` beside the number of observations
actually held. A viewer shown three photographs for a point forty photographs observed would be
misled by omission.

**The guard is scene-scoped, and that is not an implementation detail.** ``tombstone_blocks_scene``
rather than ``tombstone_blocks_capture``, because these rows are a fact about N photographs
together. ``exulanica/graph/geometry.py`` records why the per-capture reduction is wrong for
scene-wide facts: its liveness predicate is an OR over captures sharing a blob, and one live
capture would keep serving a fact about a set from which another was withdrawn.

Consent rides along per photograph, through the same seam the World Read bundle uses, so a
photograph a person has not consented to appear in is never offered as the answer to a click.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

import psycopg

from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.graph.read_consent import consent_for_captures
from exulanica.graph.wire_numbers import NUMBER_ENCODING
from exulanica.graph.wire_numbers import decimal_string as _decimal
from exulanica.reconstruction.placement import sparse_observation_records
from exulanica.store.base import ContentAddressedStore

__all__ = ["OBSERVATIONS_PROFILE", "scene_observations"]

OBSERVATIONS_PROFILE: Final = "exulanica.scene-sparse-observations/v1"

_POSE: Final = """
select pose.content_sha256
  from reconstruction_scene s
  join reconstruction_scene_job j
    on j.workspace_id = s.workspace_id
   and j.job_id = s.current_job_id
   and j.status = 'succeeded'
  join artifact pose
    on pose.workspace_id = s.workspace_id
   and pose.artifact_id = j.pose_receipt_artifact_id
   and pose.kind = 'pose_receipt'
   and pose.purged_at is null
   and not person_withdrawal_blocks_artifact(pose.workspace_id, pose.artifact_id)
 where s.workspace_id = %s
   and s.scene_id = %s
   and not tombstone_blocks_scene(s.workspace_id, s.scene_id)
"""

_MEMBERS: Final = """
select capture_id
  from reconstruction_scene_member
 where workspace_id = %s and scene_id = %s
 order by ordinal
"""


def scene_observations(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    store: ContentAddressedStore | None,
) -> dict[str, Any] | None:
    """The scene's retained sparse observation graph, or ``None`` when it is not readable.

    ``None`` covers a missing scene, a foreign one, a withdrawn one and a scene with no accepted
    pose alike, so the route above cannot turn any of them into an existence oracle.
    """
    if store is None:
        return None
    row = connection.execute(_POSE, (workspace, scene_id)).fetchone()
    if row is None:
        return None
    try:
        payload = store.get(BlobId(bytes(row["content_sha256"])))
        records = sparse_observation_records(payload)
    except (BlobNotFoundError, IntegrityError, ValueError):
        return None
    if not records:
        # An unaccepted pose receipt has no delivered cameras, so it has no observation an
        # answer could hang on. Absence rather than an empty point list, because an empty list
        # would read as "this scene observed nothing".
        return None

    members = [
        item["capture_id"]
        for item in connection.execute(_MEMBERS, (workspace, scene_id)).fetchall()
    ]
    live = {str(capture_id) for capture_id in members}
    consent = consent_for_captures(connection, workspace, members)

    points = []
    for point in records["points"]:
        observations = [
            {
                "capture_id": item["capture_ref"],
                "x": _decimal(item["x"]),
                "y": _decimal(item["y"]),
                "reprojection_error_px": _decimal(item["reprojection_error_px"]),
                "consent": consent[item["capture_ref"]],
            }
            for item in point["observations"]
            # A capture the pose receipt names but that is no longer a live member of the scene is
            # dropped rather than served from the receipt's own copy of its identity. The receipt
            # is immutable; membership is not.
            if item["capture_ref"] in live
        ]
        if not observations:
            continue
        points.append(
            {
                "point_id": point["point_id"],
                "world_xyz": [_decimal(value) for value in point["world_xyz"]],
                # COLMAP's full count, from points3D.txt before any truncation.
                "track_length": point["track_length"],
                # How many of those this answer actually holds.
                "observations_retained": len(observations),
                "observations": observations,
            }
        )

    return {
        "profile": OBSERVATIONS_PROFILE,
        "scene_id": str(scene_id),
        "provenance": "recorded",
        "method": (
            "COLMAP sparse tracks retained by the pose stage, grouped by the model's global point "
            "id. These are observations that were recorded, not visibility inferred by "
            "reprojecting a point into each camera."
        ),
        "retained_per_image": records["retained_per_image"],
        "sampling": (
            "Each image retains at most this many observations, ordered by a hash of the point id. "
            "A point's track_length is the number of photographs that observed it; "
            "observations_retained is how many of them this answer holds."
        ),
        "number_encoding": NUMBER_ENCODING,
        "point_count": len(points),
        "points": points,
    }
