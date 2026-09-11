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

import math
import uuid
from array import array
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Any, Final

import psycopg

from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.graph.read_consent import consent_for_captures
from exulanica.graph.wire_numbers import NUMBER_ENCODING
from exulanica.graph.wire_numbers import decimal_string as _decimal
from exulanica.reconstruction.placement import (
    observations_and_cameras,
    sparse_observation_records,
)
from exulanica.store.base import ContentAddressedStore

__all__ = [
    "DEFAULT_OCCLUSION_BAND_PX",
    "DEFAULT_TOLERANCE_PX",
    "MAX_TOLERANCE_PX",
    "OBSERVATIONS_PROFILE",
    "OBSERVATION_RESOLVE_PROFILE",
    "OBSERVATION_SUMMARY_PROFILE",
    "ViewNotResolvable",
    "clear_observation_index_memo",
    "observation_index_memo_observations",
    "observation_index_memo_size",
    "resolve_observation",
    "scene_observation_summary",
    "scene_observations",
]

OBSERVATIONS_PROFILE: Final = "exulanica.scene-sparse-observations/v1"
OBSERVATION_SUMMARY_PROFILE: Final = "exulanica.scene-observation-summary/v1"
OBSERVATION_RESOLVE_PROFILE: Final = "exulanica.scene-observation-resolve/v1"

_METHOD: Final = (
    "COLMAP sparse tracks retained by the pose stage, grouped by the model's global point "
    "id. These are observations that were recorded, not visibility inferred by "
    "reprojecting a point into each camera."
)

_SAMPLING: Final = (
    "Each image retains at most this many observations, ordered by a hash of the point id. "
    "A point's track_length is the number of photographs that observed it; "
    "observations_retained is how many of them this answer holds."
)

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
        "method": _METHOD,
        "retained_per_image": records["retained_per_image"],
        "sampling": _SAMPLING,
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


# -- one click, resolved on the server ------------------------------------------------------------
#
# What the inspector needs from this module is small, and the graph above is not it. A click in a
# recovered camera's view becomes one cursor in that photograph's own pixels; the inspector wants
# the one recorded point the cursor selects, that point's retained observations, and for its idle
# sentence two counts. Before this, it downloaded the whole graph to answer that, projected every
# point through the camera in the browser and kept one of them.
#
# MEASURED 2026-09-11 against a frozen copy of the volcanic scene (database
# `exulanica_resolve_view_test`, a template copy of `exulanica_segments_view_test`, and a
# hardlinked copy of the store it references): the whole graph is 1,015,016,928 bytes, takes
# 16.2 s and raises the API process from 84 MiB to a 2.73 GiB peak; the browser cannot hold it as
# one string and the inspector failed with "Unexpected end of JSON input". A ONE-point page of the
# same scene is 9,806 bytes and still takes 9.6 s at a 1.6 GiB peak, because the page is cut after
# the whole receipt is grouped. Paging bounded the wire and nothing else.
#
# So the pick runs here, and both halves are bounded. The answer holds at most one point and at
# most that point's retained observations, which is at most one per scene member: no larger for
# a scene of a million points than for one of a thousand. The work is bounded after a scene's
# first read by the index below, which holds the receipt's points as flat arrays keyed by the
# receipt's digest, so a click is one pass over those arrays and a handful of queries.
#
# The pick is the one the inspector ran, moved rather than redesigned: the same camera
# (`recovered_camera_records`, which is what the graph serves as each member's
# `recovered_camera`), the same projection, the same tolerance and occlusion band with the same
# defaults, the same tie-break. Its cases are ported from the browser's own tests. What it computes
# on is the receipt's floats rather than the twelve-decimal strings the graph put on the wire,
# which moves a projection by far less than a pixel and can change only an exact tie.
#
# What is NOT held, and is read on every request exactly as the graph read reads it: which
# captures are live members, every consent state, the tombstone and withdrawal predicates in
# `_POSE`, and the asset-read policy the route applies around this.
#
# THE TRADE, and it is the one `exulanica/graph/asset_read_policy.py` and
# `exulanica/graph/reconstruction_scenes.py` already made for the same receipt. `store.get`
# re-hashes the bytes it returns; on an index hit the only per-request check is `store.exists`. A
# receipt that rots on disk after its index was built keeps answering until the entry is evicted
# or `clear_observation_index_memo` is called. A purge is still seen, because presence is checked
# on every hit and `_POSE` excludes a purged artifact, and a repair is seen because a read that
# raised is never cached.
#
# The bound is on observations held rather than on entries, because that is what tracks memory.
# One observation costs 26 bytes here (a two-byte photograph index and three doubles) and one point
# 40, so the volcanic scene's 860,160 observations and 112,156 points are about 27 MB. Two million
# observations is about two scenes that size, and unlike the graph read there is no sweep over a
# workspace to outlast: a visitor inspects one scene at a time.

#: Where a cursor is compared with each projected point, in source-image pixels. The browser's
#: `pickObservedPoint` defaults, kept so a caller that omits them gets the answer it always got.
DEFAULT_TOLERANCE_PX: Final = 24.0
DEFAULT_OCCLUSION_BAND_PX: Final = 4.0

#: A sanity bound on both, not a budget. The answer is one point whatever the tolerance, so this
#: bounds nothing about size; what it refuses is a tolerance so wide that "the point under the
#: cursor" becomes "the nearest point anywhere in the frame", which is the answer the tolerance
#: exists to prevent. The inspector asks for eight screen pixels, about 47 source pixels on a
#: 4080 pixel tall photograph in a 700 pixel tall view.
MAX_TOLERANCE_PX: Final = 1024.0

_INDEX_MAX_OBSERVATIONS: Final = 2_000_000

_SELECTION: Final = (
    "The point is chosen by projecting every retained point through the named photograph's "
    "recovered camera and taking the one nearest the cursor within tolerance_px. Points within "
    "occlusion_band_px of that nearest distance are treated as lying on one ray, and the one "
    "nearest the camera wins; an exact tie goes to the lower point id. Choosing the point is "
    "geometric and is not provenance. The photographs listed for it are: they are the "
    "observations COLMAP recorded for that point."
)


class ViewNotResolvable(LookupError):
    """The named photograph gives this scene no recovered camera to project through.

    Either it is not a live member of the scene or the pose stage did not register it. Distinct
    from "no observation graph", because the scene is readable and the question was the problem.
    """


@dataclass(frozen=True, slots=True)
class _Camera:
    """One recovered camera, as the pick reads it: the graph's transform and four intrinsics."""

    scene_from_camera: tuple[float, ...]
    fx: float
    fy: float
    cx: float
    cy: float
    projection: str


@dataclass(frozen=True, slots=True)
class _ObservationIndex:
    """One accepted pose receipt's retained points, flat, in point-id order.

    Point ``i``'s observations are ``starts[i]`` up to ``starts[i + 1]`` of the observation
    arrays, in the capture order `sparse_observation_records` sorts them into. ``observers`` holds
    an index into ``captures`` rather than the capture reference, which is most of why an entry is
    27 MB rather than several hundred.
    """

    retained_per_image: int
    captures: tuple[str, ...]
    point_ids: array
    xs: array
    ys: array
    zs: array
    track_lengths: array
    starts: array
    observers: array
    x: array
    y: array
    errors: array
    cameras: dict[str, _Camera]


_index_lock = Lock()
_build_lock = Lock()
_index_memo: OrderedDict[str, _ObservationIndex] = OrderedDict()


def clear_observation_index_memo() -> None:
    """Forget every held index. For tests, and for bytes replaced under an existing digest."""
    with _index_lock:
        _index_memo.clear()


def observation_index_memo_size() -> int:
    """How many receipts are currently indexed. For tests and operational reporting."""
    with _index_lock:
        return len(_index_memo)


def observation_index_memo_observations() -> int:
    """How many observations the held indexes cover, which is what the bound is expressed in."""
    with _index_lock:
        return sum(len(entry.observers) for entry in _index_memo.values())


def _memo_get(key: str) -> _ObservationIndex | None:
    with _index_lock:
        entry = _index_memo.get(key)
        if entry is not None:
            _index_memo.move_to_end(key)
        return entry


def _memo_put(key: str, entry: _ObservationIndex) -> None:
    with _index_lock:
        _index_memo[key] = entry
        _index_memo.move_to_end(key)
        # Never evict down to nothing: a scene larger than the whole bound is still held, or it
        # would be built and dropped on every request and the memo would be pure cost for it.
        while (
            len(_index_memo) > 1
            and sum(len(item.observers) for item in _index_memo.values()) > _INDEX_MAX_OBSERVATIONS
        ):
            _index_memo.popitem(last=False)


def _build_index(payload: bytes) -> _ObservationIndex | None:
    """Flatten one receipt's grouped tracks and cameras, or ``None`` for an unaccepted receipt."""
    records, cameras = observations_and_cameras(payload)
    if not records:
        return None
    captures: list[str] = []
    position: dict[str, int] = {}
    point_ids, track_lengths, starts = array("q"), array("q"), array("q", [0])
    xs, ys, zs = array("d"), array("d"), array("d")
    observers = array("H")
    x, y, errors = array("d"), array("d"), array("d")
    points = records["points"]
    assert isinstance(points, list)
    for point in points:
        point_ids.append(point["point_id"])
        world = point["world_xyz"]
        xs.append(world[0])
        ys.append(world[1])
        zs.append(world[2])
        track_lengths.append(point["track_length"])
        for item in point["observations"]:
            ref = item["capture_ref"]
            slot = position.get(ref)
            if slot is None:
                slot = position[ref] = len(captures)
                captures.append(ref)
            observers.append(slot)
            x.append(item["x"])
            y.append(item["y"])
            errors.append(item["reprojection_error_px"])
        starts.append(len(observers))
    held: dict[str, _Camera] = {}
    for ref, camera in cameras.items():
        calibration = camera["calibration"]
        matrix = camera["scene_from_camera_row_major"]
        assert isinstance(calibration, dict) and isinstance(matrix, list)
        held[ref] = _Camera(
            scene_from_camera=tuple(float(value) for value in matrix),
            fx=float(calibration["fx"]),
            fy=float(calibration["fy"]),
            cx=float(calibration["cx"]),
            cy=float(calibration["cy"]),
            projection=str(camera["projection"]),
        )
    retained = records["retained_per_image"]
    assert isinstance(retained, int)
    return _ObservationIndex(
        retained_per_image=retained,
        captures=tuple(captures),
        point_ids=point_ids,
        xs=xs,
        ys=ys,
        zs=zs,
        track_lengths=track_lengths,
        starts=starts,
        observers=observers,
        x=x,
        y=y,
        errors=errors,
        cameras=held,
    )


def _index_for(store: ContentAddressedStore, blob: BlobId) -> _ObservationIndex | None:
    """The index for one receipt, built once per process and then held.

    Builds are serialised. Grouping the volcanic receipt peaks near a gigabyte before it is
    flattened, and two visitors opening two large scenes at once should wait for each other rather
    than hold two of those. A hit never takes the build lock.
    """
    entry = _memo_get(blob.hex)
    if entry is not None:
        return entry if store.exists(blob) else None
    with _build_lock:
        entry = _memo_get(blob.hex)
        if entry is not None:
            return entry if store.exists(blob) else None
        try:
            entry = _build_index(store.get(blob))
        except (BlobNotFoundError, IntegrityError, ValueError):
            return None
        # An unaccepted receipt is not cached. It answers None, as the graph read does, and
        # holding it would buy nothing a scene without an accepted pose is ever asked for.
        if entry is not None:
            _memo_put(blob.hex, entry)
        return entry


def _read_index(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    store: ContentAddressedStore | None,
) -> tuple[_ObservationIndex, dict[str, uuid.UUID]] | None:
    """The scene's index and its live members, or ``None`` exactly where the graph read is None."""
    if store is None:
        return None
    row = connection.execute(_POSE, (workspace, scene_id)).fetchone()
    if row is None:
        return None
    index = _index_for(store, BlobId(bytes(row["content_sha256"])))
    if index is None:
        return None
    members = {
        str(item["capture_id"]): item["capture_id"]
        for item in connection.execute(_MEMBERS, (workspace, scene_id)).fetchall()
    }
    return index, members


def _live_counts(index: _ObservationIndex, live: list[bool]) -> tuple[int, int]:
    """Points with at least one live observation, and how many live observations there are.

    The graph read drops an observation whose photograph is no longer a live member, and a point
    left with none. These are its `point_count_total` and `observations_total` under that rule.
    """
    if all(live):
        return len(index.point_ids), len(index.observers)
    points = observations = 0
    starts, observers = index.starts, index.observers
    for point in range(len(index.point_ids)):
        held = sum(1 for slot in range(starts[point], starts[point + 1]) if live[observers[slot]])
        if held:
            points += 1
            observations += held
    return points, observations


def scene_observation_summary(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    store: ContentAddressedStore | None,
) -> dict[str, Any] | None:
    """What a click in this scene could resolve against, as counts, or ``None``.

    ``None`` wherever :func:`scene_observations` is None, and also for a scene none of whose
    retained points keeps a live photograph, where the graph read would answer with an empty
    point list that reads as "this scene observed nothing".

    The inspector shows these before a visitor clicks anything, and asks for them when a view
    opens, which also builds the index a click will use while the visitor is still aiming.
    """
    read = _read_index(connection, workspace, scene_id, store)
    if read is None:
        return None
    index, members = read
    points, observations = _live_counts(index, [ref in members for ref in index.captures])
    if points == 0:
        # The graph read answers None for a scene whose every point lost its photographs, rather
        # than "zero points". A count of zero here would say the scene observed nothing.
        return None
    return {
        "profile": OBSERVATION_SUMMARY_PROFILE,
        "scene_id": str(scene_id),
        "provenance": "recorded",
        "method": _METHOD,
        "retained_per_image": index.retained_per_image,
        "sampling": _SAMPLING,
        "point_count_total": points,
        "observations_total": observations,
        "note": (
            "counts only. The points themselves are served one at a time by resolving a cursor, "
            "or in pages of the whole observation graph"
        ),
    }


def _finite(value: float, name: str, low: float, high: float) -> float:
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be a finite number from {low} to {high}")
    return value


def resolve_observation(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    store: ContentAddressedStore | None,
    *,
    capture_id: uuid.UUID,
    u: float,
    v: float,
    tolerance_px: float = DEFAULT_TOLERANCE_PX,
    occlusion_band_px: float = DEFAULT_OCCLUSION_BAND_PX,
) -> dict[str, Any] | None:
    """The recorded point a cursor selects in one photograph, with the photographs that saw it.

    ``(u, v)`` is in the named photograph's own pixels, +u right and +v down from its top-left
    corner, and may fall outside the frame: the inspector shows more of the world than the
    photograph covers when the view is wider than it. ``None`` exactly where
    :func:`scene_observation_summary` is None, and :class:`ViewNotResolvable` when the scene is
    readable but gives that photograph no recovered camera.

    A miss is an answer and says so: ``"state": "miss"`` with no point means nothing recorded
    projects within tolerance of the cursor, which is the honest state for a plain surface.
    """
    _finite(u, "u", -1e9, 1e9)
    _finite(v, "v", -1e9, 1e9)
    tolerance = _finite(tolerance_px, "tolerance_px", 0.0, MAX_TOLERANCE_PX)
    if tolerance == 0.0:
        raise ValueError("tolerance_px must be greater than zero")
    band = _finite(occlusion_band_px, "occlusion_band_px", 0.0, MAX_TOLERANCE_PX)
    read = _read_index(connection, workspace, scene_id, store)
    if read is None:
        return None
    index, members = read
    live = [ref in members for ref in index.captures]
    points, observations = _live_counts(index, live)
    if points == 0:
        return None
    camera = index.cameras.get(str(capture_id))
    if camera is None or str(capture_id) not in members:
        raise ViewNotResolvable(
            "this scene holds no recovered camera for that photograph, so a cursor in it has "
            "nothing to be projected through"
        )
    picked = _pick(index, camera, u, v, tolerance, band, live)
    return {
        "profile": OBSERVATION_RESOLVE_PROFILE,
        "scene_id": str(scene_id),
        "provenance": "recorded",
        "method": _METHOD,
        "selection": _SELECTION,
        "retained_per_image": index.retained_per_image,
        "sampling": _SAMPLING,
        "number_encoding": NUMBER_ENCODING,
        "point_count_total": points,
        "observations_total": observations,
        "query": {
            "capture_id": str(capture_id),
            "u": _decimal(u),
            "v": _decimal(v),
            "tolerance_px": _decimal(tolerance),
            "occlusion_band_px": _decimal(band),
            "projection": camera.projection,
        },
        "state": "miss" if picked is None else "hit",
        "point": None if picked is None else _point(connection, workspace, index, picked, live),
        "note": (
            f"this answer holds at most one of the {points} points retained for this scene: the "
            "one this cursor selects in this photograph. It is not a page of the observation "
            "graph, and no count of points can be read from it"
        ),
    }


def _pick(
    index: _ObservationIndex,
    camera: _Camera,
    u: float,
    v: float,
    tolerance: float,
    band: float,
    live: list[bool],
) -> tuple[float, float, int] | None:
    """``(pixel distance, depth, point index)`` of the selected point, or ``None`` for a miss.

    The browser's `projectToSourcePixel` and `pickObservedPoint`, term for term: the scene point is
    taken into the camera frame by the transpose of the rotation block (the transform is unit
    scale), the renderer camera looks down -Z, and COLMAP's image +v is down where the camera's +Y
    is up, which is the sign on the second term. Getting that sign wrong gives a vertically
    mirrored pick that looks plausible on a symmetric subject, which is why it is tested.
    """
    m = camera.scene_from_camera
    tx, ty, tz = m[3], m[7], m[11]
    fx, fy, cx, cy = camera.fx, camera.fy, camera.cx, camera.cy
    every_photograph_live = all(live)
    starts, observers = index.starts, index.observers
    candidates: list[tuple[float, float, int, int]] = []
    for point, (px, py, pz) in enumerate(zip(index.xs, index.ys, index.zs, strict=True)):
        dx, dy, dz = px - tx, py - ty, pz - tz
        depth = -(m[2] * dx + m[6] * dy + m[10] * dz)
        if not depth > 1e-6:
            continue
        pixel_u = cx + fx * (m[0] * dx + m[4] * dy + m[8] * dz) / depth
        pixel_v = cy - fy * (m[1] * dx + m[5] * dy + m[9] * dz) / depth
        distance = math.hypot(pixel_u - u, pixel_v - v)
        if not distance <= tolerance:
            continue
        # A point whose every retained photograph has left the scene is not in the graph read,
        # so it cannot be picked here either. Asked only of points already under the cursor.
        if not every_photograph_live and not any(
            live[observers[slot]] for slot in range(starts[point], starts[point + 1])
        ):
            continue
        candidates.append((distance, depth, index.point_ids[point], point))
    if not candidates:
        return None
    nearest = min(candidate[0] for candidate in candidates)
    # The nearest surface occludes the ones behind it, and ties break on point id so the same
    # click on the same scene always selects the same point.
    distance, depth, _point_id, point = min(
        (candidate for candidate in candidates if candidate[0] <= nearest + band),
        key=lambda candidate: (candidate[1], candidate[2]),
    )
    return distance, depth, point


def _point(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    index: _ObservationIndex,
    picked: tuple[float, float, int],
    live: list[bool],
) -> dict[str, Any]:
    """The selected point in the graph read's own shape, plus how far it was from the cursor."""
    distance, depth, point = picked
    slots = [
        slot
        for slot in range(index.starts[point], index.starts[point + 1])
        if live[index.observers[slot]]
    ]
    refs = [index.captures[index.observers[slot]] for slot in slots]
    consent = consent_for_captures(connection, workspace, [uuid.UUID(ref) for ref in refs])
    return {
        "point_id": index.point_ids[point],
        "world_xyz": [
            _decimal(index.xs[point]),
            _decimal(index.ys[point]),
            _decimal(index.zs[point]),
        ],
        "track_length": index.track_lengths[point],
        "observations_retained": len(slots),
        "pixel_distance": _decimal(distance),
        "depth": _decimal(depth),
        "observations": [
            {
                "capture_id": ref,
                "x": _decimal(index.x[slot]),
                "y": _decimal(index.y[slot]),
                "reprojection_error_px": _decimal(index.errors[slot]),
                "consent": consent[ref],
            }
            for slot, ref in zip(slots, refs, strict=True)
        ],
    }
