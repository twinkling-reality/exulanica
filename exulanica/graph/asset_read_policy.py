"""Snapshot metadata policy and fresh, buffered asset-delivery authorization.

The final lock protects only the final local check. No store read or network operation is
performed by the lock helper. A byte reader buffers and verifies first, checks the exact
buffer's identity under the lock, then releases it before returning a response.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import uuid
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Any, Final

import psycopg

from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore

__all__ = [
    "bundle_scene_ids",
    "clear_scene_inputs_memo",
    "evaluation_time",
    "final_check",
    "image_source",
    "point_allowed",
    "scene_allowed",
    "scene_inputs",
    "scene_inputs_memo_frames",
    "scene_inputs_memo_size",
]


def evaluation_time(connection: psycopg.Connection) -> dt.datetime:
    return connection.execute("select statement_timestamp() as at").fetchone()["at"]


@contextmanager
def final_check(connection: psycopg.Connection) -> Iterator[dt.datetime]:
    if connection.info.transaction_status.name != "IDLE":
        raise ValueError("final asset authorization requires an idle connection")
    with connection.transaction():
        connection.execute("set transaction read only")
        connection.execute("select asset_read_lock()")
        # Separate statement: READ COMMITTED observes writers that committed during the wait.
        yield evaluation_time(connection)


def point_allowed(
    connection: psycopg.Connection, workspace: uuid.UUID, artifact_id: uuid.UUID, at: dt.datetime
) -> bool:
    return bool(
        connection.execute(
            "select asset_point_allows(%s,%s,%s) as ok", (workspace, artifact_id, at)
        ).fetchone()["ok"]
    )


def image_source(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    digest: bytes,
    at: dt.datetime,
    *,
    original: bool = False,
) -> bytes | None:
    row = connection.execute(
        "select asset_image_source(%s,%s,%s,%s) as digest",
        (workspace, digest, at, original),
    ).fetchone()
    return bytes(row["digest"]) if row["digest"] is not None else None


_SCENE_BINDING = """
select j.job_id,j.build_inputs,a.content_sha256,
       a.artifact_id as pose_id,gate.artifact_id as gate_id,placement.artifact_id as placement_id,
       gate.content_sha256 as gate_sha256,placement.content_sha256 as placement_sha256,
       j.rung_assertion_id
from reconstruction_scene s
join reconstruction_scene_job j on j.workspace_id=s.workspace_id
  and j.job_id=s.current_job_id and j.status='succeeded'
join artifact a on a.workspace_id=j.workspace_id and a.artifact_id=j.pose_receipt_artifact_id
  and a.purged_at is null and not a.needs_repair
join artifact gate on gate.workspace_id=j.workspace_id and gate.artifact_id=j.gate_artifact_id
  and gate.purged_at is null and not gate.needs_repair
join artifact placement on placement.workspace_id=j.workspace_id
  and placement.artifact_id=j.placement_artifact_id
  and placement.purged_at is null and not placement.needs_repair
join assertion claim on claim.workspace_id=j.workspace_id
  and claim.assertion_id=j.rung_assertion_id and claim.status='active'
where s.workspace_id=%s and s.scene_id=%s
"""


# -- the parsed pose manifest memo -----------------------------------------------------------------
#
# MEASURED 2026-09-09 under cProfile against the retained reference copy, and recorded in
# `docs/evaluation/2026-09-09-graph-read-memo.json`: a warm `GET /graph` for the 210 member volcanic
# scene spends 2.896 s in the route body, of which `scene_inputs` is 2.060 s over two calls and
# `json.loads` is 1.924 s. The two calls are one scene: `read_snapshot` reaches `scene_inputs`
# through `trained_geometry_row`, and the route buffers it again for the asset-read policy.
#
# MEASURED 2026-09-09 on that scene's pose receipt, which is 107,742,795 bytes: `json.loads` of the
# whole receipt is 1.29 s, and the parsed receipt is 258 MB in Python. But the manifest this
# function returns is 45,829 bytes of that JSON and 114,312 bytes parsed, or 544 bytes per frame.
# The other 114,588,190 bytes are `quality`, which this function reads, hashes and discards. So the
# whole cost is parsing 108 MB to keep 114 KB, twice a request.
#
# The manifest is a pure function of the receipt bytes and the scene it was asked about: the bytes
# are content addressed, `manifest_digest` is checked against a canonical re-encoding of the
# manifest, and `scene_ref` is checked against the scene. Nothing else in the returned pair is
# memoised: `row` is re-read from the database on every call, exactly as before, because it carries
# `purged_at`, `needs_repair` and the active rung assertion, and `scene_allowed` compares the row it
# reads at the locked time against it. The final check is untouched, so liveness and permission are
# still evaluated fresh under the lock.
#
# THE TRADE, precisely, and it is the one `reconstruction_scenes` already made for point maps.
# `store.get` re-hashes the bytes it returns, so today a pose receipt whose bytes rot on disk fails
# its digest, `scene_inputs` returns None and the scene's geometry is withheld. On a memo hit the
# only per-request check is `store.exists`, a bare `is_file()`, so a receipt that was sound when the
# entry was filled and rots afterwards keeps its scene available until the entry is evicted or
# `clear_scene_inputs_memo` is called. A PURGE is still seen, because presence is checked on every
# hit. A REPAIR under the same digest is still seen, because a read that raised is never cached: the
# memo is filled only from a read that returned bytes which verified.
#
# The returned manifest is a deep copy. MEASURED: 0.327 ms against the 1,290 ms parse it replaces,
# which is 3,900 times cheaper, and it means the held object cannot be reached by a caller. No
# caller mutates the manifest today; this is so that none can start.
#
# The bound is on total frames rather than entries, and it is the same 20,000 the placement memo
# uses, for the same reason: `reconstruction_scene_rows` sweeps every scene in the workspace on a
# graph read, so the access pattern is a cycle, and a bound shorter than the cycle evicts each entry
# before it is reused and the hit rate is zero rather than merely lower. At 544 bytes per frame,
# 20,000 frames is about 11 MB.

_MEMO_MAX_FRAMES = 20_000

#: (scene ref, pose receipt digest). The digest is what makes the entry safe to reuse; the scene is
#: in the key because `scene_ref` is checked against it and one receipt must not answer for another.
_MemoKey = tuple[str, str]

_memo_lock = Lock()
_memo: OrderedDict[_MemoKey, dict[str, Any]] = OrderedDict()


def clear_scene_inputs_memo() -> None:
    """Forget every memoised manifest.

    For tests, and for an operator who has replaced bytes under an existing digest, which the
    content-addressed store is not supposed to allow.
    """
    with _memo_lock:
        _memo.clear()


def scene_inputs_memo_size() -> int:
    """How many parsed manifests are currently held. For tests and for operational reporting."""
    with _memo_lock:
        return len(_memo)


def _frame_count(manifest: dict[str, Any]) -> int:
    """How many frames a manifest declares, for anything a manifest could hold.

    Total rather than trusting the shape: the digest check that fills the memo proves the manifest
    is the one the receipt commits to, not that `frames` is a list. A manifest that carried
    something else would otherwise raise from inside the eviction loop, and a malformed receipt is
    exactly the case where a read must fail quietly rather than in a new way.
    """
    frames = manifest.get("frames")
    return len(frames) if isinstance(frames, list) else 0


def scene_inputs_memo_frames() -> int:
    """How many frames the held manifests cover, which is what the bound is expressed in."""
    with _memo_lock:
        return sum(_frame_count(manifest) for manifest in _memo.values())


def _memo_get(key: _MemoKey) -> dict[str, Any] | None:
    with _memo_lock:
        manifest = _memo.get(key)
        if manifest is not None:
            _memo.move_to_end(key)
        return manifest


def _memo_put(key: _MemoKey, manifest: dict[str, Any]) -> None:
    with _memo_lock:
        _memo[key] = manifest
        _memo.move_to_end(key)
        # Never evict down to nothing: a scene larger than the whole bound should still be held, or
        # it would be inserted and dropped on every request and the memo would be pure cost for it.
        while (
            len(_memo) > 1
            and sum(_frame_count(entry) for entry in _memo.values()) > _MEMO_MAX_FRAMES
        ):
            _memo.popitem(last=False)


#: What `exulanica/reconstruction/pose.py` writes a receipt as: canonical JSON, sorted keys, no
#: whitespace. Of its five top-level keys `manifest` sorts first, so a sound receipt begins with
#: exactly these bytes. Checked rather than assumed, with a fallback for anything that does not.
_RECEIPT_HEAD: Final = b'{"manifest":'
_DIGEST_KEY: Final = ',"manifest_digest":"'


def _manifest_and_digest(data: bytes) -> tuple[Any, Any]:
    """The receipt's manifest and the digest it claims for it, parsing as little as possible.

    The memo below spared the SECOND parse of a pose receipt in a process. This spares most of the
    first, which is what a fresh process and therefore a first visitor pays.

    MEASURED 2026-09-10 on the volcanic scene's CURRENT pose receipt, 107,742,795 bytes at
    f44362e2: reading it is 0.018 s, re-hashing it inside `store.get` is 0.045 s, and
    `json.loads` of the whole object is 1.439 s. The manifest is 44,130 canonical bytes of
    that, 210 frames; the rest is `quality`, which nothing on this path reads. Decoding the
    object and `raw_decode`-ing only the manifest out of its head is 0.017 s, eighty times
    cheaper, and produces a manifest equal to the whole parse's.

    Structural rather than a substring search: the head prefix is checked exactly, the manifest is
    decoded as a JSON value from a known offset, and `manifest_digest` is taken from the bytes
    that must immediately follow it. Anything else about the receipt falls back to parsing the
    whole object, so a receipt written by some other producer still reads correctly and merely
    slowly. A head this function misread cannot be served either way: the caller verifies the
    manifest against the digest returned beside it, and a mismatch denies the scene.
    """
    if data.startswith(_RECEIPT_HEAD):
        try:
            text = data.decode()
            manifest, end = json.JSONDecoder().raw_decode(text, len(_RECEIPT_HEAD))
            # Long enough to hold the digest key, a 64 character digest, its closing quote, and
            # the first ten characters of whatever key comes next, which is what the duplicate
            # check below reads.
            tail = text[end : end + len(_DIGEST_KEY) + 75]
            if tail.startswith(_DIGEST_KEY):
                closing = tail.index('"', len(_DIGEST_KEY))
                # The key that follows must sort strictly after `manifest_digest`. JSON permits a
                # duplicate key and `json.loads` keeps the LAST, so without this a receipt
                # carrying two `manifest` pairs would be read as its first here and as its second
                # by `_read_pose_receipt` and `recovered_camera_records`, which still use
                # `json.loads`. Both halves of the pair returned here come from the head, so the
                # caller's digest check would agree with itself and the split would be silent:
                # `scene_allowed` would authorise against one manifest while the geometry came
                # from the other. Our own writer sorts its keys and cannot emit a duplicate, so
                # this only ever fires on a receipt from somewhere else, and it falls back to the
                # whole-object parse, which agrees with every other reader.
                after = tail[closing + 1 :]
                if after.startswith(',"') and after[2:10] > "manifest":
                    return manifest, tail[len(_DIGEST_KEY) : closing]
        except (UnicodeDecodeError, ValueError):
            pass
    receipt = json.loads(data)
    return receipt["manifest"], receipt["manifest_digest"]


def scene_inputs(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    store: ContentAddressedStore,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Buffer the current pose manifest; absence is not invented legacy lineage."""
    row = connection.execute(_SCENE_BINDING, (workspace, scene_id)).fetchone()
    if row is None or row["content_sha256"] is None:
        return None
    blob = BlobId(bytes(row["content_sha256"]))
    key = (str(scene_id), blob.hex)
    memoised = _memo_get(key)
    if memoised is not None:
        # Presence is checked on every hit rather than being part of the key, because a purged
        # receipt has to keep turning its scene unavailable and this is the cheap half of what
        # `store.get` did. What is no longer re-checked per request is the digest of the bytes.
        return (row, copy.deepcopy(memoised)) if store.exists(blob) else None
    try:
        manifest, claimed_digest = _manifest_and_digest(store.get(blob))
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        if claimed_digest != digest or manifest["scene_ref"] != str(scene_id):
            return None
        # Only a read that returned verified bytes fills the memo. A BlobNotFoundError or an
        # IntegrityError falls through to the handler below and caches nothing, so a receipt
        # restored or repaired under the same digest is seen on the next request.
        _memo_put(key, copy.deepcopy(manifest))
        return row, manifest
    except (BlobNotFoundError, IntegrityError, ValueError, KeyError, TypeError):
        return None


def scene_allowed(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    buffered: tuple[dict[str, Any], dict[str, Any]] | None,
    at: dt.datetime,
) -> bool:
    if buffered is None:
        return False
    row, manifest = buffered
    current = connection.execute(_SCENE_BINDING, (workspace, scene_id)).fetchone()
    if current != row:
        return False
    for key in ("pose_id", "gate_id", "placement_id"):
        if not connection.execute(
            "select asset_artifact_live(%s,%s,%s) as live", (workspace, row[key], at)
        ).fetchone()["live"]:
            return False
    members = connection.execute(
        "select m.capture_id,c.blob_sha256 from reconstruction_scene_job_member m "
        "join capture c on c.workspace_id=m.workspace_id and c.capture_id=m.capture_id "
        "where m.workspace_id=%s and m.job_id=%s",
        (workspace, row["job_id"]),
    ).fetchall()
    try:
        frames = manifest["frames"]
        if len(frames) != len(members) or {f["capture_ref"] for f in frames} != {
            str(m["capture_id"]) for m in members
        }:
            return False
        points = row["build_inputs"]["point_maps"]
        if len(points) != len(members) or {p["capture_ref"] for p in points} != {
            str(m["capture_id"]) for m in members
        }:
            return False
        for member in members:
            frame = next(f for f in frames if f["capture_ref"] == str(member["capture_id"]))
            point = next(p for p in points if p["capture_ref"] == str(member["capture_id"]))
            artifact = connection.execute(
                "select content_sha256,source_blob_sha256,read_source_sha256 from artifact "
                "where workspace_id=%s and artifact_id=%s",
                (workspace, uuid.UUID(point["artifact_ref"])),
            ).fetchone()
            if (
                artifact is None
                or bytes(artifact["content_sha256"]).hex() != point["content_sha256"]
            ):
                return False
            if bytes(artifact["source_blob_sha256"]) != bytes(member["blob_sha256"]):
                return False
            if not point_allowed(connection, workspace, uuid.UUID(point["artifact_ref"]), at):
                return False
            actual = artifact["read_source_sha256"] or artifact["source_blob_sha256"]
            if bytes(actual).hex() != frame["sha256"]:
                return False
        return bool(members)
    except (KeyError, ValueError, TypeError, StopIteration):
        return False


def bundle_scene_ids(value: object) -> set[uuid.UUID]:
    """All scene dependencies of a bundle, including its place anchor and alignments."""
    found: set[uuid.UUID] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                key in {"scene_id", "anchor_scene_id", "candidate_scene_id", "against_scene_id"}
                and item
            ):
                found.add(uuid.UUID(str(item)))
            else:
                found.update(bundle_scene_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(bundle_scene_ids(item))
    return found
