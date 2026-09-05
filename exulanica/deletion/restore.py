"""Offline restore from a complete, sealed, independently retained deletion checkpoint.

This is not a disaster detector or a background journal. The operator stops all traffic and
writers, seals the current source, retains the checkpoint outside BOTH backup domains, and
creates a pending marker before restoring database and object bytes. Startup checks that marker
and its matching database receipt. A source resumed after completion needs a fresh checkpoint
before another restore; silently treating an old export as current would resurrect deletions.

A checkpoint seals raw SQL tombstone writes as well as application writes. Replay is an
administrative operation, but physical destruction still runs through the existing purge role.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.db.session import Database, set_workspace
from exulanica.deletion.worker import PurgeWorker
from exulanica.env import env_get, resolve_data_dir
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore
from exulanica.store.local import LocalContentAddressedStore

__all__ = ["RestoreRefused", "checkpoint", "prepare_restore", "replay", "verify_restore"]


class RestoreRefused(RuntimeError):
    """The restore has not proved that every authoritative deletion has been applied."""


def _write(path: Path, value: dict[str, Any]) -> None:
    """Atomic durable replacement. The marker must survive a crash before database commit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict):
            raise ValueError("expected an object")
        return value
    except (OSError, ValueError) as exc:
        raise RestoreRefused(f"restore control file is unavailable or invalid: {path}") from exc


def _admin(connection: psycopg.Connection) -> None:
    row = connection.execute(
        "select rolsuper or rolbypassrls as complete_view from pg_roles where rolname=current_user"
    ).fetchone()
    if not row or not row["complete_view"]:
        raise RestoreRefused("offline checkpoint/replay requires an administrative complete view")


def _checkpoint(path: Path) -> tuple[dict[str, Any], str]:
    envelope = _read(path)
    record = envelope.get("record")
    if (
        envelope.get("profile") != "exulanica.digest-bound-record/v1"
        or envelope.get("state") != "sealed"
        or not isinstance(record, dict)
        or record.get("profile") != "exulanica.restore-tombstone-checkpoint/v1"
        or not isinstance(record.get("tombstones"), list)
    ):
        raise RestoreRefused("checkpoint is not a sealed tombstone checkpoint")
    digest = hashlib.sha256(canonical_json(record)).hexdigest()
    if envelope.get("record_sha256") != digest:
        raise RestoreRefused("tombstone checkpoint digest does not match its contents")
    identities = [item["tombstone"]["tombstone_id"] for item in record["tombstones"]]
    if len(set(identities)) != len(identities):
        raise RestoreRefused("checkpoint repeats a tombstone identity")
    return record, digest


def checkpoint(database: Database, path: Path) -> str:
    """Seal all committed tombstones, across all workspaces, and retain their purge targets.

    The file is first prepared, then the database seal commits, then the file becomes usable.
    A crash at either boundary leaves a refusal, never a purported complete checkpoint.
    Keep the API and every writer stopped until replay finishes. A digest detects corruption;
    operator custody of this file, not the digest, makes it authoritative.
    """
    if path.exists():
        raise RestoreRefused("checkpoint paths are immutable; choose a fresh path")
    with database.unscoped() as connection:
        _admin(connection)
        connection.execute("lock table tombstone in access exclusive mode")
        if connection.execute("select 1 from restore_control where state <> 'complete'").fetchone():
            raise RestoreRefused("the source already has an unfinished restore checkpoint")
        rows = connection.execute(
            "select to_jsonb(t) - 'purge_completed_at' as tombstone, "
            "coalesce((select jsonb_agg(jsonb_build_object("
            "'target_kind',j.target_kind,'target_ref',j.target_ref) "
            "order by j.target_kind,j.target_ref) from purge_job j "
            "where j.tombstone_id=t.tombstone_id),'[]'::jsonb) as targets "
            "from tombstone t order by t.workspace_id,t.tombstone_id"
        ).fetchall()
        record = {
            "profile": "exulanica.restore-tombstone-checkpoint/v1",
            "checkpoint_id": str(uuid.uuid4()),
            "sealed_at": dt.datetime.now(dt.UTC).isoformat(),
            "tombstones": rows,
        }
        digest = hashlib.sha256(canonical_json(record)).hexdigest()
        envelope = {
            "profile": "exulanica.digest-bound-record/v1",
            "record": record,
            "record_sha256": digest,
            "state": "prepared",
        }
        _write(path, envelope)
        connection.execute(
            "insert into restore_control (checkpoint_id,checkpoint_sha256,state) "
            "values (%s,%s,'sealed') on conflict(singleton) do update set "
            "checkpoint_id=excluded.checkpoint_id,checkpoint_sha256=excluded.checkpoint_sha256,"
            "state='sealed',restore_id=null,updated_at=now()",
            (record["checkpoint_id"], digest),
        )
    _write(path, {**envelope, "state": "sealed"})
    return digest


def prepare_restore(checkpoint_path: Path, marker_path: Path) -> uuid.UUID:
    """Persist the refusal BEFORE restoring anything, outside the restored backup domains."""
    if checkpoint_path.resolve() == marker_path.resolve():
        raise RestoreRefused("the restore marker must not overwrite its checkpoint")
    if marker_path.exists() and _read(marker_path).get("state") != "complete":
        raise RestoreRefused("a pending restore already exists; resume that attempt")
    record, digest = _checkpoint(checkpoint_path)
    restore_id = uuid.uuid4()
    _write(
        marker_path,
        {
            "profile": "exulanica.restore-state/v1",
            "state": "pending",
            "restore_id": str(restore_id),
            "checkpoint_id": record["checkpoint_id"],
            "checkpoint_sha256": digest,
        },
    )
    return restore_id


def _marker(path: Path) -> dict[str, Any]:
    marker = _read(path)
    if marker.get("profile") != "exulanica.restore-state/v1":
        raise RestoreRefused("unrecognised restore marker")
    try:
        uuid.UUID(marker["restore_id"])
        uuid.UUID(marker["checkpoint_id"])
    except (KeyError, ValueError, TypeError) as exc:
        raise RestoreRefused("restore marker has no valid attempt identity") from exc
    return marker


def verify_restore(database: Database, marker_path: Path | None = None) -> None:
    """Called before API workers or serving. Missing, partial or mismatched proof refuses."""
    marker = _marker(marker_path) if marker_path is not None else None
    if marker is not None and marker.get("state") != "complete":
        raise RestoreRefused("mandatory tombstone replay is pending; refusing traffic")
    with database.unscoped() as connection:
        control = connection.execute("select * from restore_control").fetchone()
        if control is not None and control["state"] != "complete":
            raise RestoreRefused("database is sealed or replay is incomplete; refusing traffic")
        if marker is not None:
            receipt = connection.execute(
                "select * from restore_replay_receipt where restore_id=%s",
                (marker["restore_id"],),
            ).fetchone()
            if (
                receipt is None
                or str(receipt["checkpoint_id"]) != marker["checkpoint_id"]
                or receipt["checkpoint_sha256"] != marker["checkpoint_sha256"]
                or control is None
                or str(control["restore_id"]) != marker["restore_id"]
                or control["checkpoint_sha256"] != marker["checkpoint_sha256"]
            ):
                raise RestoreRefused(
                    "restore completion receipt does not match the external marker"
                )


def replay(
    database: Database,
    purge_database: Database,
    store: ContentAddressedStore,
    checkpoint_path: Path,
    marker_path: Path,
) -> uuid.UUID:
    """Reapply authoritative deletions, purge, verify, then issue an idempotent receipt.

    Existing tombstones get a deterministic replay identity to run every existing trigger
    again. This also repairs a database backup containing completed jobs paired with an older
    object-store backup. Archived targets retain objects whose row was already marked purged.
    Stub rows and evidence addresses remain for audit; serving paths refuse their tombstones.
    Every aggregate in affected workspaces is invalidated because its prior closure is untrusted.
    """
    record, digest = _checkpoint(checkpoint_path)
    marker = _marker(marker_path)
    if (
        marker.get("checkpoint_id") != record["checkpoint_id"]
        or marker.get("checkpoint_sha256") != digest
    ):
        raise RestoreRefused("restore marker names a different authoritative checkpoint")
    restore_id = uuid.UUID(marker["restore_id"])
    _write(marker_path, {**marker, "state": "pending"})
    applied: list[tuple[uuid.UUID, uuid.UUID]] = []
    workspaces = frozenset(
        uuid.UUID(row["tombstone"]["workspace_id"]) for row in record["tombstones"]
    )
    with database.unscoped() as connection:
        _admin(connection)
        connection.execute(
            "insert into restore_control (checkpoint_id,checkpoint_sha256,state,restore_id) "
            "values (%s,%s,'replaying',%s) on conflict(singleton) do update set "
            "checkpoint_id=excluded.checkpoint_id,checkpoint_sha256=excluded.checkpoint_sha256,"
            "state='replaying',restore_id=excluded.restore_id,updated_at=now()",
            (record["checkpoint_id"], digest, restore_id),
        )
    for item in record["tombstones"]:
        original = item["tombstone"]
        workspace_id = uuid.UUID(original["workspace_id"])
        # Independent transactions let an interrupted replay resume. No receipt is written yet.
        with database.session(workspace_id) as connection, connection.transaction():
            # These guards recover a blob address through capture, so a backup older than
            # that row cannot enforce either an interval redaction or a hash blocklist.
            if original["capture_id"] and (
                original["scope"] == "interval" or original["blocklist_hash"]
            ):
                binding = connection.execute(
                    "select 1 from capture where workspace_id=%s and capture_id=%s",
                    (workspace_id, original["capture_id"]),
                ).fetchone()
                if binding is None:
                    raise RestoreRefused("required capture binding is absent from this backup")
            existing = connection.execute(
                "select to_jsonb(t)-'purge_completed_at' as value from tombstone t "
                "where tombstone_id=%s",
                (original["tombstone_id"],),
            ).fetchone()
            if existing is not None and existing["value"] != original:
                raise RestoreRefused("restored tombstone conflicts with the authoritative record")
            value = dict(original)
            # Keep the original identity and a stable replay identity on every retry.
            replay_id = uuid.uuid5(restore_id, original["tombstone_id"])
            if existing is None:
                connection.execute(
                    "insert into tombstone select (jsonb_populate_record(null::tombstone,%s)).* "
                    "on conflict (tombstone_id) do nothing",
                    (Jsonb(original),),
                )
            value["tombstone_id"] = str(replay_id)
            tombstone_id = replay_id
            connection.execute(
                "insert into tombstone select (jsonb_populate_record(null::tombstone,%s)).* "
                "on conflict (tombstone_id) do nothing",
                (Jsonb(value),),
            )
            for target in item["targets"]:
                connection.execute(
                    "insert into purge_job (tombstone_id,workspace_id,target_kind,target_ref) "
                    "values (%s,%s,%s,%s) on conflict(tombstone_id,target_kind,target_ref) "
                    "do nothing",
                    (tombstone_id, workspace_id, target["target_kind"], target["target_ref"]),
                )
            connection.execute(
                "update purge_job set state='queued',attempts=0,attempted_at=null,"
                "completed_at=null,last_error=null where tombstone_id in (%s,%s)",
                (tombstone_id, original["tombstone_id"]),
            )
            connection.execute(
                "update tombstone set purge_completed_at=null where tombstone_id in (%s,%s)",
                (tombstone_id, original["tombstone_id"]),
            )
            connection.execute(
                "update derived_artifact set stale=true where workspace_id=%s", (workspace_id,)
            )
            applied.append((workspace_id, tombstone_id))
    worker = PurgeWorker(purge_database, store, workspaces)
    while True:
        outcome = worker.drain()
        if outcome.blocked or outcome.failed or outcome.skipped or outcome.exhausted:
            raise RestoreRefused(f"tombstone replay purge incomplete: {outcome}")
        if outcome.handled == 0:
            break
    with database.unscoped() as connection:
        _admin(connection)
        for workspace_id, tombstone_id in applied:
            set_workspace(connection, workspace_id)
            complete = connection.execute(
                "select tombstone_purge_is_complete(%s) as complete", (tombstone_id,)
            ).fetchone()
            if not complete or not complete["complete"]:
                raise RestoreRefused("a replayed tombstone is not completely purged")
            targets = connection.execute(
                "select target_ref from purge_job where tombstone_id=%s "
                "and target_kind in ('blob','artifact')",
                (tombstone_id,),
            ).fetchall()
            if any(store.exists(BlobId.from_hex(row["target_ref"])) for row in targets):
                raise RestoreRefused("replayed object-store bytes still exist")
        connection.execute(
            "insert into restore_replay_receipt "
            "(restore_id,checkpoint_id,checkpoint_sha256,tombstone_count) values (%s,%s,%s,%s) "
            "on conflict(restore_id) do nothing",
            (restore_id, record["checkpoint_id"], digest, len(record["tombstones"])),
        )
        connection.execute(
            "update restore_control set state='complete',updated_at=now() where restore_id=%s",
            (restore_id,),
        )
    _write(marker_path, {**marker, "state": "complete"})
    verify_restore(database, marker_path)
    return restore_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("checkpoint", "prepare", "replay"))
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--marker", type=Path)
    args = parser.parse_args(argv)
    if args.action == "checkpoint":
        checkpoint(Database.from_env(), args.checkpoint)
    elif args.marker is None:
        parser.error("prepare and replay require --marker outside both backup domains")
    elif args.action == "prepare":
        prepare_restore(args.checkpoint, args.marker)
    else:
        purge_url = env_get("PURGE_DATABASE_URL")
        if not purge_url:
            parser.error("PURGE_DATABASE_URL must name the separately provisioned purge role")
        replay(
            Database.from_env(),
            Database(purge_url),
            LocalContentAddressedStore(resolve_data_dir() / "blobs"),
            args.checkpoint,
            args.marker,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
