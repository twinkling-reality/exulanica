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

**A page says it is a page, by the same rule.** The whole graph is large, and the size was
measured rather than estimated. MEASURED 2026-09-07, read-only against the retained reference
instance (``postgresql://localhost:5433/exulanica_spine_test``, store
``.exulanica/reference-baseline/runtime/blobs``): the bowl scene
``851ca35b-31c3-560c-84f9-4e142962755b`` holds 15005 points and 71214 observations and serialises
to **97,633,587** canonical bytes; the volcanic scene ``45ad50b7`` holds 111694 points and
serialises to **1,179,240,157**. A 500-point page of the same two scenes is **4,973,392** and
**8,173,297** bytes, 5.1% and 0.7% of the whole. A place spans several captures, so this is the
read that fails first once a place is addressable, and ``limit`` is what bounds it.

What a bounded answer must never do is look like a complete one. Every response carries a
``bounds`` block naming the state, how many points the scene has, how many this answer holds and
the cursor for the rest. The unbounded call is unchanged and stays the default, so a client
already reading the whole graph keeps getting it and is now told that it did. This is the sampling
rule one level up and it is the same argument: a viewer shown 500 points of 15005 and not told
would be misled by omission.

The bound is on the answer, not on the work. The pose receipt is one object and it is read and
grouped in full before any page is cut, so paging saves the wire and the client's memory and saves
nothing on the server. Saying otherwise would be a performance claim nobody measured.

**The guard is scene-scoped, and that is not an implementation detail.** ``tombstone_blocks_scene``
rather than ``tombstone_blocks_capture``, because these rows are a fact about N photographs
together. ``exulanica/graph/geometry.py`` records why the per-capture reduction is wrong for
scene-wide facts: its liveness predicate is an OR over captures sharing a blob, and one live
capture would keep serving a fact about a set from which another was withdrawn.

Consent rides along per photograph, through the same seam the World Read bundle uses. Note what
that does and does not do today: it **reports** each photograph's screening state, and it filters
nothing, because no per-person consent state exists to filter on. Every observation currently
carries ``person_consent: unscreened``, which says nobody has looked at that photograph for people
and never that there is nobody in it. Filtering is Phase 10 capability 5's to add, on the
privacy branch, and until it lands a caller has a state to display and no decision to enforce.
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
    *,
    limit: int | None = None,
    after_point_id: int | None = None,
) -> dict[str, Any] | None:
    """The scene's retained sparse observation graph, or ``None`` when it is not readable.

    ``None`` covers a missing scene, a foreign one, a withdrawn one and a scene with no accepted
    pose alike, so the route above cannot turn any of them into an existence oracle.

    ``limit`` and ``after_point_id`` cut a page out of the graph, in point-id order. Both default
    to None, which returns the whole graph exactly as this function always has, because a client
    already reading it asked for the whole thing and a default that quietly stopped answering that
    question would be the failure this module's own sampling rule exists to prevent. What every
    answer gains is a ``bounds`` block: a complete one says it is complete, and a page says how
    many points it left behind and where to continue.

    A page is stable across requests without a snapshot: the pose receipt is immutable and its
    points are ordered by COLMAP's global point id, so a cursor over that order cannot skip or
    repeat a point. What a cursor cannot promise is that the scene is still readable between
    pages, and it is not asked to: a withdrawal between two pages makes the next one ``None``.
    """
    if limit is not None and limit < 1:
        raise ValueError("a page of the observation graph holds at least one point")
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

    window = [
        point for point in points if after_point_id is None or point["point_id"] > after_point_id
    ]
    page = window if limit is None else window[:limit]
    # A cursor is offered only when there is somewhere to go. `next_point_id` on an exhausted page
    # would invite one more request whose answer is empty, and an empty page of an observation
    # graph reads like a scene that observed nothing, which is the sentence this module opens by
    # refusing to write.
    next_point_id = page[-1]["point_id"] if page and len(page) < len(window) else None

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
        "bounds": _bounds(points, page, limit, after_point_id, next_point_id),
        # How many points THIS ANSWER holds, which is what it has always meant. The scene's own
        # total is in `bounds`, kept apart on purpose: one field that meant "the scene's points"
        # on a complete answer and "this page's points" on a bounded one is a field no client can
        # read correctly, and the reading it would get wrong is the one that undercounts a world.
        "point_count": len(page),
        "points": page,
    }


def _bounds(
    points: list[dict[str, Any]],
    page: list[dict[str, Any]],
    limit: int | None,
    after_point_id: int | None,
    next_point_id: int | None,
) -> dict[str, Any]:
    """What this answer holds and what it does not, in the shape a client has to read first."""
    held = sum(len(point["observations"]) for point in points)
    returned = sum(len(point["observations"]) for point in page)
    complete = len(page) == len(points)
    return {
        "state": "complete" if complete else "page",
        "limit": limit,
        "after_point_id": after_point_id,
        "next_point_id": next_point_id,
        "point_count_total": len(points),
        "point_count_returned": len(page),
        "point_count_not_returned": len(points) - len(page),
        "observations_total": held,
        "observations_returned": returned,
        "order": (
            "points ascend by COLMAP's global point id, the order the pose receipt retains. The "
            "receipt is immutable, so a cursor over this order can neither skip nor repeat a point"
        ),
        "note": (
            "this answer holds every point retained for this scene"
            if complete
            else (
                f"this answer holds {len(page)} of the {len(points)} points retained for this "
                "scene. It is a page of the observation graph and not the graph: counting these "
                "points understates what the scene observed, the same way counting a point's "
                "held observations understates its track length. Ask again with after_point_id "
                "set to next_point_id for the rest"
            )
        ),
    }
