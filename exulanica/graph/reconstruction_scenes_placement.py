"""The persisted scene projection and the placement memo, which spare a scene row its rebuild.

A part of :mod:`exulanica.graph.reconstruction_scenes`, which imports its names back. Both hold
a scene's placement outcome, which members were placed and why the others were not, with the
recovered cameras. A projection is the outcome the scene worker wrote down, read from the store
and proved against the scene before it is used; the memo holds an outcome inside one process,
keyed on what it was built from.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections import OrderedDict
from threading import Lock
from typing import Final, NamedTuple

from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore

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
# legal there today, unmoved, and this reader already imports `validate_placement_record` and
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
# predicate together is 242 ms. The cost is in `_scene_row`, which re-reads the scene's blobs
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
#: forbid an extra key, and they are constructed in `_scene_row` outside its fallback handlers, so
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
