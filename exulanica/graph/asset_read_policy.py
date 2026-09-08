"""Snapshot metadata policy and fresh, buffered asset-delivery authorization.

The final lock protects only the final local check. No store read or network operation is
performed by the lock helper. A byte reader buffers and verifies first, checks the exact
buffer's identity under the lock, then releases it before returning a response.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg

from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore


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
    try:
        receipt = json.loads(store.get(BlobId(bytes(row["content_sha256"]))))
        manifest = receipt["manifest"]
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        if receipt["manifest_digest"] != digest or manifest["scene_ref"] != str(scene_id):
            return None
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
