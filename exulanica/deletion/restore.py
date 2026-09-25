"""Offline restore from a complete, sealed, independently retained deletion checkpoint.

This is not a disaster detector or a background journal. The operator stops all traffic and
writers, seals the current source, retains the checkpoint outside BOTH backup domains, and
creates a pending marker before restoring database and object bytes. Startup checks that marker
and its matching database receipt. A source resumed after completion needs a fresh checkpoint
before another restore; silently treating an old export as current would resurrect deletions.

A checkpoint seals raw SQL tombstone writes as well as application writes, and every withdrawal
that is not a tombstone (``exulanica.deletion.withdrawals``), which replay writes again before its
tombstones. Replay is an administrative operation, but physical destruction still runs through the
existing purge role.

The operator's command is ``python -m exulanica.orchestration.restore``: a replay writes some
withdrawals by the product's own writers (a retraction, a continued place-name chain), which sit
above this package, so the command that gives replay those writers sits above them.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.db.session import Database, set_workspace
from exulanica.deletion.queue import DESTROYABLE_KINDS, STORED_KINDS
from exulanica.deletion.withdrawals import (
    CATALOG,
    CATALOG_IDENTITY,
    Carried,
    CarryRefused,
    Writer,
    kind_of,
    read_withdrawals,
    reapply,
    require_writers,
    stale_withdrawals,
)
from exulanica.deletion.worker import PurgeWorker
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore
from exulanica.store.namespaces import WorkspaceStores

__all__ = ["RestoreRefused", "checkpoint", "prepare_restore", "replay", "verify_restore"]


class RestoreRefused(RuntimeError):
    """The restore has not proved that every authoritative deletion has been applied."""


#: Every checkpoint profile a replay reads, and whether it carries withdrawals. Version 1 holds
#: tombstones and their purge targets. Version 2 adds every withdrawal the catalog of
#: :mod:`exulanica.deletion.withdrawals` names and the catalog's own identity, and a replay of it
#: refuses a restored database holding a tombstone or withdrawal it does not carry.
#: :func:`checkpoint` writes the last.
CHECKPOINT_PROFILES: Final = {
    "exulanica.restore-tombstone-checkpoint/v1": False,
    "exulanica.restore-tombstone-checkpoint/v2": True,
}
CHECKPOINT_PROFILE: Final = "exulanica.restore-tombstone-checkpoint/v2"


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
        or record.get("profile") not in CHECKPOINT_PROFILES
        or not isinstance(record.get("tombstones"), list)
    ):
        raise RestoreRefused("checkpoint is not a sealed tombstone checkpoint")
    digest = hashlib.sha256(canonical_json(record)).hexdigest()
    if envelope.get("record_sha256") != digest:
        raise RestoreRefused("tombstone checkpoint digest does not match its contents")
    if CHECKPOINT_PROFILES[record["profile"]]:
        if record.get("withdrawal_catalog") != CATALOG_IDENTITY:
            raise RestoreRefused(
                "the checkpoint was sealed under another withdrawal catalog; finish that restore "
                "with the release that sealed it"
            )
        if not isinstance(record.get("withdrawals"), list):
            raise RestoreRefused("checkpoint is not a sealed tombstone checkpoint")
        try:
            for carried in _withdrawals(record):
                kind_of(carried)
        except CarryRefused as unknown:
            raise RestoreRefused(str(unknown)) from unknown
    identities = [item["tombstone"]["tombstone_id"] for item in record["tombstones"]]
    if len(set(identities)) != len(identities):
        raise RestoreRefused("checkpoint repeats a tombstone identity")
    kinds = {target["target_kind"] for item in record["tombstones"] for target in item["targets"]}
    unknown = sorted(kinds - set(DESTROYABLE_KINDS))
    if unknown:
        raise RestoreRefused(f"checkpoint names purge targets no worker destroys: {unknown}")
    return record, digest


def _stored(item: dict[str, Any]) -> list[dict[str, str]]:
    """One checkpoint tombstone's targets whose bytes live in an object store."""
    return [target for target in item["targets"] if target["target_kind"] in STORED_KINDS]


def _withdrawals(record: dict[str, Any]) -> list[Carried]:
    """The withdrawals a checkpoint carries; none for a profile that carries none."""
    return [Carried(item["kind"], item["row"]) for item in record.get("withdrawals", ())]


def _refuse_a_stale_checkpoint(connection: psycopg.Connection, record: dict[str, Any]) -> None:
    """Refuse a restored database that holds a tombstone or a withdrawal the checkpoint lacks.

    Both are written once and never removed, and a checkpoint is sealed from the source after
    every backup of it, so a current checkpoint holds everything its restored database holds. One
    it lacks says the checkpoint is older than the backup, and the deletions and withdrawals made
    between the two are in neither. Asked once, before the attempt writes anything: afterwards the
    database also holds this attempt's own replay copies and the tombstones its withdrawals wrote.
    """
    known = [item["tombstone"]["tombstone_id"] for item in record["tombstones"]]
    unknown = connection.execute(
        "select 1 from tombstone where tombstone_id <> all(%s::uuid[]) limit 1", (known,)
    ).fetchone()
    if unknown is not None or stale_withdrawals(connection, _withdrawals(record)):
        raise RestoreRefused(
            "the restored database holds a deletion or withdrawal the checkpoint does not: "
            "the checkpoint is older than the backup; seal a fresh one from the source"
        )


def _carry_withdrawals(
    database: Database, record: dict[str, Any], writers: Mapping[str, Writer]
) -> None:
    """Write every withdrawal the checkpoint carries into the restored database, before replay.

    Each write is the product's own, so its triggers run: a stopped search or training right
    writes a tombstone of its own again, whose cascade erases what the stop erased (migrations 0104
    and 0082). That erasure does not depend on the order, and a replay that carried withdrawals
    after its tombstones was measured to erase the same entries. Before them, a replayed
    tombstone's cascade reads the rights its source's cascade read, so it records the same targets
    the source recorded. A workspace's rows are written in a session of that workspace, each in its
    own transaction, so an interrupted replay resumes; a row no workspace owns, in an
    administrative one.
    """
    owned: dict[uuid.UUID | None, list[Carried]] = {}
    for carried in _withdrawals(record):
        column = kind_of(carried).workspace
        owner = uuid.UUID(carried.row[column]) if column else None
        owned.setdefault(owner, []).append(carried)
    for owner in sorted(owned, key=lambda value: (value is not None, str(value))):
        opened = database.session(owner) if owner else database.unscoped()
        with opened as connection:
            _admin(connection)
            for carried in owned[owner]:
                try:
                    with connection.transaction():
                        reapply(connection, carried, writers)
                except CarryRefused as refused:
                    raise RestoreRefused(str(refused)) from refused


def _refuse_entries_left(
    connection: psycopg.Connection, workspace_id: uuid.UUID, item: dict[str, Any]
) -> None:
    """Refuse completion while a search entry this checkpoint tombstone erased is still here.

    The checkpoint names every entry the deletion erased where it happened. An entry of the same
    identity may exist again only when it was made after the deletion took effect: an entry's
    identity is a digest of its photograph, text and model, and a search right granted again
    after a stop indexes the photograph again (migration 0104). One made at or before that
    moment is the entry the person deleted, still here because the backup predates the deletion
    and holds something that keeps the entry, such as a search right whose stop this checkpoint
    does not carry.
    """
    stored = _stored(item)
    erased = [target["target_ref"] for target in item["targets"] if target not in stored]
    if not erased:
        return
    left = connection.execute(
        "select 1 from embedding where workspace_id=%s and embedding_id=any(%s::uuid[]) "
        "and created_at<=%s::timestamptz limit 1",
        (workspace_id, erased, item["tombstone"]["effective_at"]),
    ).fetchone()
    if left is not None:
        raise RestoreRefused("a search entry the checkpoint deleted is still in this database")


def checkpoint(database: Database, path: Path) -> str:
    """Seal all committed tombstones and withdrawals, across all workspaces, with purge targets.

    The file is first prepared, then the database seal commits, then the file becomes usable.
    A crash at either boundary leaves a refusal, never a purported complete checkpoint.
    Keep the API and every writer stopped until replay finishes. A digest detects corruption;
    operator custody of this file, not the digest, makes it authoritative.

    Every table the withdrawal catalog names is locked against writes while it is read, and the
    seal then refuses each withdrawal as it refuses a tombstone (migrations 0036 and 0107), so
    nothing the checkpoint misses can be written after it.
    """
    if path.exists():
        raise RestoreRefused("checkpoint paths are immutable; choose a fresh path")
    with database.unscoped() as connection:
        _admin(connection)
        connection.execute("lock table tombstone in access exclusive mode")
        for table in sorted({kind.table for kind in CATALOG}):
            connection.execute(
                sql.SQL("lock table {} in exclusive mode").format(sql.Identifier(table))
            )
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
            "profile": CHECKPOINT_PROFILE,
            "checkpoint_id": str(uuid.uuid4()),
            "sealed_at": dt.datetime.now(dt.UTC).isoformat(),
            "tombstones": rows,
            "withdrawal_catalog": CATALOG_IDENTITY,
            "withdrawals": [
                {"kind": carried.kind, "row": carried.row}
                for carried in read_withdrawals(connection)
            ],
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
    *,
    writers: Mapping[str, Writer],
    materials: WorkspaceStores | None = None,
) -> uuid.UUID:
    """Reapply authoritative deletions, purge, verify, then issue an idempotent receipt.

    Existing tombstones get a deterministic replay identity to run every existing trigger
    again. This also repairs a database backup containing completed jobs paired with an older
    object-store backup. Archived targets retain objects whose row was already marked purged.
    A search entry is a row of the restored database rather than stored bytes, so the replay
    copy's own cascade decides which entries the deletion still erases here, and the checkpoint's
    list of erased entries is a check afterwards: an entry it names may be present only when it
    was made after the deletion took effect.
    Stub rows and evidence addresses remain for audit; serving paths refuse their tombstones.
    Every aggregate in affected workspaces is invalidated because its prior closure is untrusted.

    A checkpoint of profile v2 also carries every withdrawal outside the tombstone table. Its
    first attempt refuses a restored database holding a tombstone or a withdrawal the checkpoint
    lacks, and every attempt writes each carried withdrawal again before any tombstone.

    ``writers`` are the product's writers the withdrawal catalog names, by the names it uses
    (``exulanica.orchestration.restore.WRITERS``); anything else is refused before anything is
    replayed.

    ``materials`` holds each workspace's material bakes (migration 0066). A checkpoint that names
    a bake is refused without it, before anything is replayed, because the purge could not reach
    those bytes and the receipt would then be withheld only after the replay had begun.
    """
    record, digest = _checkpoint(checkpoint_path)
    try:
        require_writers(writers)
    except CarryRefused as refused:
        raise RestoreRefused(str(refused)) from refused
    if materials is None and any(
        target["target_kind"] == "material_bake"
        for item in record["tombstones"]
        for target in item["targets"]
    ):
        raise RestoreRefused("the checkpoint names material bakes and no material store was given")
    marker = _marker(marker_path)
    if (
        marker.get("checkpoint_id") != record["checkpoint_id"]
        or marker.get("checkpoint_sha256") != digest
    ):
        raise RestoreRefused("restore marker names a different authoritative checkpoint")
    restore_id = uuid.UUID(marker["restore_id"])
    _write(marker_path, {**marker, "state": "pending"})
    applied: list[tuple[uuid.UUID, uuid.UUID, dict[str, Any]]] = []
    carries = CHECKPOINT_PROFILES[record["profile"]]
    workspaces = frozenset(
        uuid.UUID(row["tombstone"]["workspace_id"]) for row in record["tombstones"]
    ) | frozenset(
        uuid.UUID(carried.row[column])
        for carried in _withdrawals(record)
        if (column := kind_of(carried).workspace)
    )
    with database.unscoped() as connection:
        _admin(connection)
        control = connection.execute("select restore_id from restore_control").fetchone()
        if carries and (control is None or control["restore_id"] != restore_id):
            _refuse_a_stale_checkpoint(connection, record)
        connection.execute(
            "insert into restore_control (checkpoint_id,checkpoint_sha256,state,restore_id) "
            "values (%s,%s,'replaying',%s) on conflict(singleton) do update set "
            "checkpoint_id=excluded.checkpoint_id,checkpoint_sha256=excluded.checkpoint_sha256,"
            "state='replaying',restore_id=excluded.restore_id,updated_at=now()",
            (record["checkpoint_id"], digest, restore_id),
        )
    _carry_withdrawals(database, record, writers)
    for item in record["tombstones"]:
        original = item["tombstone"]
        workspace_id = uuid.UUID(original["workspace_id"])
        # Independent transactions let an interrupted replay resume. No receipt is written yet.
        with database.session(workspace_id) as connection, connection.transaction():
            # These guards recover a blob address through capture, so a backup older than
            # that row cannot enforce either an interval redaction or a hash blocklist.
            #
            # A `scene_training` tombstone (migration 0082) gets no guard of this shape and
            # cannot have one worth having. What its cascade reads is `scene_training_artifact`,
            # so a backup older than those bindings replays a withdrawal that enqueues nothing,
            # and that is INDISTINGUISHABLE from the legitimate case of a right whose run
            # published nothing at all. A guard here would refuse a correct restore as often as
            # an incomplete one, so the gap is named rather than guarded.
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
            # Store bytes can be older than this database, so the checkpoint's own record of
            # them is queued again. A search entry is a row of this database: the cascade that
            # just ran for the replay copy recorded every entry the deletion still erases here,
            # with the target row that alone authorizes its purge. A checkpoint entry it did not
            # record is gone already or was made again after the deletion, and queued it could
            # never be claimed, so the replay could never complete. After the purge,
            # _refuse_entries_left asks whether each is truly gone.
            for target in _stored(item):
                connection.execute(
                    "insert into purge_job (tombstone_id,workspace_id,target_kind,target_ref) "
                    "values (%s,%s,%s,%s) on conflict(tombstone_id,target_kind,target_ref) "
                    "do nothing",
                    (tombstone_id, workspace_id, target["target_kind"], target["target_ref"]),
                )
            # The original's search-entry jobs stay as this database holds them. A done one
            # erased its entry before this backup was taken, and an entry of that identity here
            # now was made again under a later right, which its old target row would authorize
            # a reset job to destroy.
            connection.execute(
                "update purge_job set state='queued',attempts=0,attempted_at=null,"
                "completed_at=null,last_error=null where tombstone_id=%s "
                "or (tombstone_id=%s and target_kind=any(%s))",
                (tombstone_id, original["tombstone_id"], list(STORED_KINDS)),
            )
            connection.execute(
                "update tombstone set purge_completed_at=null where tombstone_id in (%s,%s)",
                (tombstone_id, original["tombstone_id"]),
            )
            connection.execute(
                "update derived_artifact set stale=true where workspace_id=%s", (workspace_id,)
            )
            applied.append((workspace_id, tombstone_id, item))
    worker = PurgeWorker(purge_database, store, workspaces, material_stores=materials)
    while True:
        outcome = worker.drain()
        if outcome.blocked or outcome.failed or outcome.skipped or outcome.exhausted:
            raise RestoreRefused(f"tombstone replay purge incomplete: {outcome}")
        if outcome.handled == 0:
            break
    with database.unscoped() as connection:
        _admin(connection)
        for workspace_id, tombstone_id, item in applied:
            set_workspace(connection, workspace_id)
            complete = connection.execute(
                "select tombstone_purge_is_complete(%s) as complete", (tombstone_id,)
            ).fetchone()
            if not complete or not complete["complete"]:
                raise RestoreRefused("a replayed tombstone is not completely purged")
            _refuse_entries_left(connection, workspace_id, item)
            targets = connection.execute(
                "select target_kind, target_ref from purge_job where tombstone_id=%s "
                "and target_kind=any(%s)",
                (tombstone_id, list(STORED_KINDS)),
            ).fetchall()
            for row in targets:
                blob_id = BlobId.from_hex(row["target_ref"])
                if row["target_kind"] == "material_bake":
                    assert materials is not None  # refused above when a bake was named
                    present = materials.for_workspace(workspace_id).exists(blob_id)
                else:
                    present = store.exists(blob_id)
                if present:
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


#: Where the operator's restore command is: replay needs writers this package cannot import.
COMMAND: Final = "python -m exulanica.orchestration.restore"


def main(argv: list[str] | None = None) -> int:
    """The restore command's old place, which refuses and names where it is."""
    raise SystemExit(
        f"exulanica.deletion.restore is not the restore command; run `{COMMAND}` with the same "
        "arguments"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
