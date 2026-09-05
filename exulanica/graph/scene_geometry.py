"""Read current, digest-bound trained scene geometry through ordinary workspace guards."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from typing import Any

import psycopg

from exulanica.errors import BlobNotFoundError, IntegrityError, TombstonedError
from exulanica.evidence.blob import BlobId
from exulanica.graph.geometry import GeometryBytes
from exulanica.graph.payload import SceneGeometryReferenceRow, SceneTrainedGeometryRow
from exulanica.reconstruction.scene_gate import SceneGateDecision, validate_scene_gate_decision
from exulanica.store.base import ContentAddressedStore

TRAINED_GEOMETRY_KIND = "gaussian_splat_scene"
_IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def trained_geometry_row(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    pose_digest: str,
    decision: SceneGateDecision,
    store: ContentAddressedStore,
) -> SceneTrainedGeometryRow | None:
    training = next((receipt for receipt in decision.receipts if receipt.kind == "splat"), None)
    if training is None or not training.accepted:
        return None
    try:
        row = connection.execute(
            "select artifact_id from artifact where workspace_id=%s and scene_id=%s "
            "and kind='scene_splat_receipt' and content_sha256=%s and purged_at is null "
            "and not person_withdrawal_blocks_artifact(workspace_id,artifact_id)",
            (workspace, scene_id, bytes.fromhex(training.sha256)),
        ).fetchone()
        if row is None:
            return None
        receipt = json.loads(store.get(BlobId.from_hex(training.sha256)))
        if (
            receipt.get("profile") != "exulanica.scene-splat-publication/v1"
            or receipt.get("scene_ref") != str(scene_id)
            or receipt.get("pose_receipt_sha256") != pose_digest
        ):
            raise ValueError("trained scene receipt disagrees with its pose")
        manifest = receipt["manifest"]
        manifest_digest = hashlib.sha256(
            json.dumps(
                manifest,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        if manifest_digest != receipt.get("manifest_digest"):
            raise ValueError("training manifest no longer reproduces its digest")
        quality, delivery = receipt["quality"], receipt["delivery"]
        if (
            quality.get("accepted") is not True
            or not isinstance(delivery, dict)
            or delivery.get("container") != "sog/1"
            or quality.get("delivery_sha256") != delivery.get("content_sha256")
            or quality.get("browser_bytes") != delivery.get("byte_size")
            or delivery.get("scene_from_asset_row_major") != _IDENTITY
        ):
            raise ValueError("trained scene delivery disagrees with its quality receipt")
        bounds = delivery["bounds"]
        if (
            not isinstance(bounds, dict)
            or set(bounds) != {"min", "max"}
            or any(
                not isinstance(bounds[key], list) or len(bounds[key]) != 3 for key in ("min", "max")
            )
            or any(
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
                for key in bounds
                for value in bounds[key]
            )
            or any(bounds["min"][axis] > bounds["max"][axis] for axis in range(3))
        ):
            raise ValueError("trained scene bounds are malformed")
        artifact_id = uuid.UUID(delivery["artifact_id"])
        digest = BlobId.from_hex(delivery["content_sha256"])
        artifact = connection.execute(
            "select byte_size from artifact where workspace_id=%s and scene_id=%s "
            "and artifact_id=%s and kind=%s and content_sha256=%s and purged_at is null "
            "and not person_withdrawal_blocks_artifact(workspace_id,artifact_id)",
            (workspace, scene_id, artifact_id, TRAINED_GEOMETRY_KIND, digest.digest),
        ).fetchone()
        if artifact is None or artifact["byte_size"] != delivery["byte_size"]:
            raise ValueError("trained scene artifact row disagrees with its receipt")
        state = "available"
        try:
            content = store.get(digest)
            if len(content) != artifact["byte_size"]:
                state = "invalid"
        except BlobNotFoundError:
            state = "bytes_missing"
        except IntegrityError:
            state = "invalid"
        return SceneTrainedGeometryRow(
            artifact_id=artifact_id,
            content_sha256=digest.hex,
            container="sog/1",
            scene_from_asset_row_major=_IDENTITY,
            bounds=bounds,
            state=state,
            reference=(
                SceneGeometryReferenceRow(
                    href=f"/scene-geometry/{artifact_id}",
                    authorization="workspace-bearer",
                    content_sha256=digest.hex,
                    byte_size=artifact["byte_size"],
                )
                if state == "available"
                else None
            ),
        )
    except (BlobNotFoundError, IntegrityError, KeyError, TypeError, ValueError):
        return None


def read_scene_geometry(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    artifact_id: uuid.UUID,
    store: ContentAddressedStore,
) -> GeometryBytes | None:
    row: dict[str, Any] | None = connection.execute(
        "select a.content_sha256,a.byte_size,a.purged_at,a.scene_id,"
        "gate.content_sha256 as gate_sha256,pose.content_sha256 as pose_sha256,"
        "tombstone_blocks_scene(a.workspace_id,a.scene_id) as deleted,"
        "person_withdrawal_blocks_artifact(a.workspace_id,a.artifact_id) as withdrawn "
        "from artifact a join reconstruction_scene s on s.workspace_id=a.workspace_id "
        "and s.scene_id=a.scene_id join reconstruction_scene_job j "
        "on j.workspace_id=s.workspace_id and j.job_id=s.current_job_id and j.status='succeeded' "
        "join assertion claim on claim.workspace_id=j.workspace_id "
        "and claim.assertion_id=j.rung_assertion_id and claim.status='active' "
        "join artifact gate on gate.workspace_id=j.workspace_id "
        "and gate.artifact_id=j.gate_artifact_id and gate.purged_at is null "
        "join artifact pose on pose.workspace_id=j.workspace_id "
        "and pose.artifact_id=j.pose_receipt_artifact_id and pose.purged_at is null "
        "where a.workspace_id=%s and a.artifact_id=%s and a.kind=%s",
        (workspace, artifact_id, TRAINED_GEOMETRY_KIND),
    ).fetchone()
    if row is None:
        return None
    if row["deleted"] or row["withdrawn"] or row["purged_at"] is not None:
        raise TombstonedError("this reconstructed scene was withdrawn")
    decision = validate_scene_gate_decision(store.get(BlobId(bytes(row["gate_sha256"]))))
    current = trained_geometry_row(
        connection, workspace, row["scene_id"], bytes(row["pose_sha256"]).hex(), decision, store
    )
    if current is None or current.artifact_id != artifact_id:
        return None
    digest = BlobId(bytes(row["content_sha256"]))
    data = store.get(digest)
    if len(data) != row["byte_size"]:
        raise IntegrityError("trained scene byte size disagrees with its artifact row")
    return GeometryBytes(artifact_id, digest.hex, "sog/1", data)
