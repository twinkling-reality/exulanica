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

A source that is lost cannot be stopped and sealed, so no current checkpoint of it can exist. For
that case :func:`export_withdrawals` writes the same record from a running source, read in one
snapshot without a lock or a seal, with the time it covers. An export is the authority only for a
declared crash recovery: :func:`prepare_restore` accepts one only with a recovery declaration whose
incident lies within a stated bound of the export, and the marker records the window between the
two, in which a withdrawal the source accepted is not in the export and does not come back. A
sealed checkpoint needs no declaration and takes none, so the two modes never mix.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.db.session import Database, set_workspace
from exulanica.deletion.queue import (
    DESTROYABLE_KINDS,
    STORED_KINDS,
    PurgeTarget,
    stored_target_store,
)
from exulanica.deletion.withdrawals import (
    CATALOG,
    CATALOG_IDENTITY,
    Carried,
    CarryRefused,
    Writer,
    kind_of,
    open_withdrawals,
    read_withdrawals,
    reapply,
    require_writers,
    stale_withdrawals,
)
from exulanica.deletion.worker import HELD_BY_A_LIVE_RECORD, PurgeWorker, still_held
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore
from exulanica.store.namespaces import WorkspaceStores

if TYPE_CHECKING:
    from exulanica.store.configured import ContentStores

__all__ = [
    "DECLARATION_PROFILE",
    "EXPORT_PROFILE",
    "MAX_EXPORT_LAG",
    "RestoreRefused",
    "abandon_declared_restore",
    "adopt_restore_state",
    "checkpoint",
    "complete_committed_replay",
    "completed_restores",
    "export_withdrawals",
    "initialise_restore_state",
    "loss_window",
    "mark_returning",
    "prepare_restore",
    "replay",
    "source_identity",
    "verify_restore",
]


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
#: A checkpoint's record read from a running source without a seal, for a declared crash recovery.
#: It carries what version 2 carries, plus ``covered_through``: every tombstone and withdrawal
#: committed before that time is in it.
EXPORT_PROFILE: Final = "exulanica.restore-withdrawal-export/v1"
#: The operator's statement that the source is lost, which alone lets an export be replayed.
DECLARATION_PROFILE: Final = "exulanica.recovery-declaration/v1"
#: The largest gap any installation may allow between its newest export and a declared incident.
#: An installation states a smaller bound; this is the ceiling no configuration can raise.
MAX_EXPORT_LAG: Final = dt.timedelta(hours=24)
_DECLARATION_KEYS: Final = frozenset(
    {"profile", "declaration_id", "export_sha256", "incident_at", "reason"}
)


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


def _checkpoint(path: Path) -> tuple[dict[str, Any], str, bool]:
    """A sealed checkpoint or an export, verified; the last value says it is an export."""
    envelope = _read(path)
    record = envelope.get("record")
    exported = envelope.get("state") == "exported"
    if (
        envelope.get("profile") != "exulanica.digest-bound-record/v1"
        or envelope.get("state") not in ("sealed", "exported")
        or not isinstance(record, dict)
        or (exported and record.get("profile") != EXPORT_PROFILE)
        or (not exported and record.get("profile") not in CHECKPOINT_PROFILES)
        or not isinstance(record.get("tombstones"), list)
    ):
        raise RestoreRefused("checkpoint is not a sealed tombstone checkpoint or an export")
    digest = hashlib.sha256(canonical_json(record)).hexdigest()
    if envelope.get("record_sha256") != digest:
        raise RestoreRefused("tombstone checkpoint digest does not match its contents")
    if exported:
        _covered_through(record)
    if exported or CHECKPOINT_PROFILES[record["profile"]]:
        if record.get("withdrawal_catalog") != CATALOG_IDENTITY:
            raise RestoreRefused(
                "the checkpoint was sealed under another withdrawal catalog; finish that restore "
                "with the release that sealed it"
            )
        if not isinstance(record.get("withdrawals"), list):
            raise RestoreRefused("checkpoint is not a sealed tombstone checkpoint or an export")
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
    return record, digest, exported


def _covered_through(record: dict[str, Any]) -> dt.datetime:
    """The time an export covers, which must name its time zone."""
    stated = record.get("covered_through")
    try:
        covered = dt.datetime.fromisoformat(stated) if isinstance(stated, str) else None
    except ValueError:
        covered = None
    if covered is None or covered.tzinfo is None:
        raise RestoreRefused("the export does not say, with its time zone, what time it covers")
    return covered


def _carries(record: dict[str, Any]) -> bool:
    """Whether a verified record carries withdrawals beside its tombstones."""
    return record["profile"] == EXPORT_PROFILE or CHECKPOINT_PROFILES[record["profile"]]


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


def _held_open(
    connection: psycopg.Connection, workspace_id: uuid.UUID, tombstone_id: uuid.UUID
) -> list[str] | None:
    """The targets an incomplete tombstone has left because a live record here still holds their
    bytes, or None when it has left anything else: a job failed or not run, a skip for another
    reason, bytes nothing holds any more, or caption vectors not yet erased."""
    cursor = connection.cursor(row_factory=dict_row)
    captions = cursor.execute(
        "select caption_vector_purge_is_complete(%s, %s) as complete", (workspace_id, tombstone_id)
    ).fetchone()
    # As tombstone_purge_is_complete reads it: only false is incomplete; null is nothing to erase.
    if captions is not None and captions["complete"] is False:
        return None
    rows = cursor.execute(
        "select pj.purge_id, pj.workspace_id, pj.target_kind, pj.target_ref, pj.attempts, "
        "pj.state, pj.last_error, t.requested_by, t.reason, t.scope::text as scope "
        "from purge_job pj join tombstone t on t.tombstone_id = pj.tombstone_id "
        "where pj.tombstone_id = %s",
        (tombstone_id,),
    ).fetchall()
    held = []
    for row in rows:
        if row["state"] == "done":
            continue
        if row["state"] != "skipped" or row["last_error"] != HELD_BY_A_LIVE_RECORD:
            return None
        target = PurgeTarget(
            purge_id=row["purge_id"],
            tombstone_id=tombstone_id,
            workspace_id=row["workspace_id"],
            target_kind=row["target_kind"],
            target_ref=row["target_ref"],
            attempts=row["attempts"],
            requested_by=row["requested_by"],
            reason=row["reason"],
            scope=row["scope"],
        )
        if not still_held(connection, target):
            return None
        held.append(f"{row['target_kind']}:{row['target_ref']}")
    return held


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


def _authority(connection: psycopg.Connection) -> dict[str, Any]:
    """Every tombstone with its purge targets, and every catalogued withdrawal, as one record part.

    A checkpoint reads this under its locks and seal; an export reads it in one snapshot.
    """
    rows = connection.execute(
        "select to_jsonb(t) - 'purge_completed_at' as tombstone, "
        "coalesce((select jsonb_agg(jsonb_build_object("
        "'target_kind',j.target_kind,'target_ref',j.target_ref) "
        "order by j.target_kind,j.target_ref) from purge_job j "
        "where j.tombstone_id=t.tombstone_id),'[]'::jsonb) as targets "
        "from tombstone t order by t.workspace_id,t.tombstone_id"
    ).fetchall()
    return {
        "tombstones": rows,
        "withdrawal_catalog": CATALOG_IDENTITY,
        "withdrawals": [
            {"kind": carried.kind, "row": carried.row} for carried in read_withdrawals(connection)
        ],
    }


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
        record = {
            "profile": CHECKPOINT_PROFILE,
            "checkpoint_id": str(uuid.uuid4()),
            "sealed_at": dt.datetime.now(dt.UTC).isoformat(),
            **_authority(connection),
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


def _inside(path: Path, domains: Iterable[Path]) -> Path | None:
    resolved = path.resolve()
    for domain in domains:
        root = domain.resolve()
        if resolved == root or resolved.is_relative_to(root) or root.is_relative_to(resolved):
            return domain
    return None


def export_withdrawals(
    database: Database,
    directory: Path,
    *,
    restore_state_path: Path | None,
    backup_domains: Iterable[Path],
) -> tuple[Path, str]:
    """Write what a checkpoint would hold, from a running source, to a fresh file in ``directory``.

    Nothing is locked beyond the ACCESS SHARE a read takes, and nothing is sealed: tombstones and
    withdrawals are written once and never removed, so one repeatable-read snapshot is a complete
    record of everything committed before it. The reads make a concurrent checkpoint or schema
    change wait for the export, and block no writer. ``covered_through`` is the transaction's
    start, which precedes its snapshot, so every tombstone and withdrawal committed before that
    time is in the export. The window a later recovery reports is therefore in commit time: a
    withdrawal that began before ``covered_through`` and committed after it is outside the export.

    An export is a full cross-workspace copy of every withdrawal's identifying fields (section 5.4
    of the privacy threat model lists them), so ``directory`` must lie outside every backup domain
    named, and outside the content store: a custody copy that a backup also carried would outlive
    the retention its custody applies. Refused, each by name: a directory inside a backup domain;
    a source that is a standby (``pg_is_in_recovery()``), whose snapshot may trail its primary; a
    source that is sealed or replaying; and a restore that is declared and not complete
    (``restore_state_path``), because a restored database that has not replayed would give a new
    ``covered_through`` to backup-era content. The caller passes the installation's marker path,
    or None for an installation that declares none.
    """
    domain = _inside(directory, backup_domains)
    if domain is not None:
        raise RestoreRefused(
            f"the export directory is inside the backup domain {domain}; keep custody apart"
        )
    try:
        verify_restore(database, restore_state_path)
    except RestoreRefused as pending:
        raise RestoreRefused(f"a restore is not complete; nothing is exported ({pending})") from (
            pending
        )
    directory.mkdir(parents=True, exist_ok=True)
    with database.unscoped() as connection:
        # The connection is not in autocommit, and its time zone statement opened a transaction.
        # Commit that, so the next statement opens the one repeatable-read transaction everything
        # below reads in, and takes its snapshot.
        connection.commit()
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        connection.read_only = True
        snapshot = (
            connection.cursor(row_factory=dict_row)
            .execute(
                "select transaction_timestamp() as covered_through, "
                "pg_current_snapshot()::text as snapshot, pg_is_in_recovery() as standby"
            )
            .fetchone()
        )
        assert snapshot is not None
        if snapshot["standby"]:
            raise RestoreRefused("the source is a standby; export from the primary")
        _admin(connection)
        if connection.execute("select 1 from restore_control where state <> 'complete'").fetchone():
            raise RestoreRefused("the source is sealed or replaying; it is not an authority")
        covered = snapshot["covered_through"].astimezone(dt.UTC)
        record = {
            "profile": EXPORT_PROFILE,
            "checkpoint_id": str(uuid.uuid4()),
            "covered_through": covered.isoformat(),
            "snapshot": snapshot["snapshot"],
            "source_identity": source_identity(connection),
            **_authority(connection),
        }
        _refuse_an_older_database(connection, record, directory)
    digest = hashlib.sha256(canonical_json(record)).hexdigest()
    path = directory / f"{covered.strftime('%Y%m%dT%H%M%S%fZ')}-{record['checkpoint_id']}.json"
    if path.exists():
        raise RestoreRefused("export paths are immutable; choose a fresh directory")
    _write(
        path,
        {
            "profile": "exulanica.digest-bound-record/v1",
            "record": record,
            "record_sha256": digest,
            "state": "exported",
        },
    )
    return path, digest


def source_identity(connection: psycopg.Connection) -> str:
    """Which database an export came from: its server's system identifier and its own oid.

    Derived rather than stored, so a database restored from a backup, into a new server or over a
    dropped one, is a different source from the one it came from, and its exports never stand in
    for or prune the lost source's.
    """
    row = (
        connection.cursor(row_factory=dict_row)
        .execute(
            "select (select system_identifier from pg_control_system())::text as system, "
            "d.oid::text as database, d.datname as name from pg_database d "
            "where d.datname = current_database()"
        )
        .fetchone()
    )
    assert row is not None
    return hashlib.sha256(canonical_json([row["system"], row["database"], row["name"]])).hexdigest()


def _newest_export(directory: Path) -> dict[str, Any] | None:
    """The newest valid export in custody, whatever its source, or None."""
    newest: dict[str, Any] | None = None
    for path in sorted(directory.glob("*.json")):
        try:
            record, _digest, exported = _checkpoint(path)
        except RestoreRefused:
            continue
        if exported and (newest is None or record["covered_through"] > newest["covered_through"]):
            newest = record
    return newest


def _refuse_an_older_database(
    connection: psycopg.Connection, record: dict[str, Any], directory: Path
) -> None:
    """Refuse an export from a database that went backwards relative to custody's newest export.

    Two questions, both about what the database would serve, not about what it happens to hold:

    *   **A tombstone the newest export holds and this database lacks.** Tombstones are never
        removed, and a replay writes every tombstone its authority carries, so a database lacking
        one is a restore that has not replayed, or another database pointed at this custody.
    *   **A withdrawal the newest export holds that this database does not honour**: the database
        holds, current, a row the withdrawal ended
        (:func:`exulanica.deletion.withdrawals.open_withdrawals`). A row it does not hold at all
        is honoured: a sign-in session a backup set never carries,
        or a row created after the backup a restore came from. Compared only under the same
        catalog, whose identity fixes the rows' shape.

    Either would date old, permissive content as current and, kept as the newest, could prune the
    real exports.
    """
    newest = _newest_export(directory)
    if newest is None:
        return
    held = {str(item["tombstone"]["tombstone_id"]) for item in newest["tombstones"]}
    have = {str(item["tombstone"]["tombstone_id"]) for item in record["tombstones"]}
    missing = len(held - have)
    if newest.get("withdrawal_catalog") == record.get("withdrawal_catalog"):
        missing += len(open_withdrawals(connection, _withdrawals(newest)))
    if missing:
        raise RestoreRefused(
            f"this database lacks {missing} tombstones or withdrawals the newest export in custody "
            "holds; it is older than that export, so a restore is not complete or it is another "
            "database"
        )


def _microseconds(delta: dt.timedelta) -> int:
    return delta // dt.timedelta(microseconds=1)


def _declared(
    record: dict[str, Any],
    digest: str,
    declaration: Any,
    max_export_lag: dt.timedelta,
) -> dict[str, Any]:
    """The recovery a declaration states for this export, or a refusal naming what is wrong.

    The bound on the gap between the export and the incident is the caller's, from the
    installation's configuration, never the declaration's own, and never above
    :data:`MAX_EXPORT_LAG`: a declaration that could widen it would be an override, and there is
    none. Every malformed value is refused by name; nothing here fails by exception type.
    """
    if not isinstance(max_export_lag, dt.timedelta) or not (
        dt.timedelta(0) < max_export_lag <= MAX_EXPORT_LAG
    ):
        raise RestoreRefused(
            "the export lag bound must be positive and at most "
            f"{MAX_EXPORT_LAG.total_seconds():.0f} s"
        )
    if not isinstance(declaration, dict) or declaration.get("profile") != DECLARATION_PROFILE:
        raise RestoreRefused("the recovery declaration is not a recovery declaration")
    if set(declaration) != _DECLARATION_KEYS or not all(
        isinstance(value, str) for value in declaration.values()
    ):
        raise RestoreRefused(
            "a recovery declaration states exactly "
            f"{', '.join(sorted(_DECLARATION_KEYS))}, each as text"
        )
    if not declaration["reason"].strip():
        raise RestoreRefused("the recovery declaration gives no reason")
    if declaration.get("export_sha256") != digest:
        raise RestoreRefused("the recovery declaration names a different export")
    identity, stated = declaration.get("declaration_id"), declaration.get("incident_at")
    if not isinstance(identity, str) or not isinstance(stated, str):
        raise RestoreRefused("the recovery declaration has no identity or incident time")
    try:
        declaration_id = uuid.UUID(identity)
        incident = dt.datetime.fromisoformat(stated)
    except ValueError as exc:
        raise RestoreRefused("the recovery declaration has no identity or incident time") from exc
    if incident.tzinfo is None:
        raise RestoreRefused("the recovery declaration's incident time names no time zone")
    covered = _covered_through(record)
    if incident < covered:
        raise RestoreRefused(
            "the export covers a time after the declared incident; the source was not lost then"
        )
    if incident - covered > max_export_lag:
        raise RestoreRefused(
            "the withdrawal authority is not current: the newest export ends "
            f"{(incident - covered).total_seconds():.0f} s before the incident, beyond the "
            f"{max_export_lag.total_seconds():.0f} s this installation allows"
        )
    return {
        "mode": "declared",
        "declaration": declaration,
        "declaration_id": str(declaration_id),
        "declaration_sha256": hashlib.sha256(canonical_json(declaration)).hexdigest(),
        "covered_through": covered.isoformat(),
        "incident_at": incident.astimezone(dt.UTC).isoformat(),
        "loss_window_microseconds": _microseconds(incident - covered),
        "max_export_lag_microseconds": _microseconds(max_export_lag),
    }


def _redeclared(record: dict[str, Any], digest: str, marker: dict[str, Any]) -> dict[str, Any]:
    """The marker's declared recovery, validated again in full, for a replay of an export."""
    recovery = marker.get("recovery")
    if not isinstance(recovery, dict):
        raise RestoreRefused(
            "an export is replayed only under the recovery declaration its marker records"
        )
    bound = recovery.get("max_export_lag_microseconds")
    if isinstance(bound, bool) or not isinstance(bound, int):
        raise RestoreRefused("the marker's recovery records no export lag bound")
    if not 0 < bound <= _microseconds(MAX_EXPORT_LAG):
        raise RestoreRefused(
            "the export lag bound must be positive and at most "
            f"{MAX_EXPORT_LAG.total_seconds():.0f} s"
        )
    again = _declared(record, digest, recovery.get("declaration"), dt.timedelta(microseconds=bound))
    if again != recovery:
        raise RestoreRefused("the marker's recovery does not match its declaration")
    return again


def loss_window(marker_path: Path) -> str | None:
    """One line an operator reads: the declared recovery's window, or None for a planned restore."""
    recovery = _marker(marker_path).get("recovery")
    if not isinstance(recovery, dict):
        return None
    return (
        f"declared crash recovery {recovery.get('declaration_id')}: withdrawals committed between "
        f"{recovery.get('covered_through')} and {recovery.get('incident_at')} are not in the "
        f"export and are not restored ({recovery.get('loss_window_microseconds')} microseconds)"
    )


def prepare_restore(
    checkpoint_path: Path,
    marker_path: Path,
    *,
    declaration_path: Path | None = None,
    max_export_lag: dt.timedelta | None = None,
) -> uuid.UUID:
    """Persist the refusal BEFORE restoring anything, outside the restored backup domains.

    A sealed checkpoint takes no declaration and no lag bound. An export takes both: a declaration
    and the installation's bound on how far before the incident the export may end. The marker
    records the declared recovery in full, including the window a withdrawal inside it is lost
    in, and replay validates it again.
    """
    if checkpoint_path.resolve() == marker_path.resolve():
        raise RestoreRefused("the restore marker must not overwrite its checkpoint")
    previous = _read(marker_path) if marker_path.exists() else {}
    if previous and previous.get("state") not in ("complete", "none", "abandoned"):
        raise RestoreRefused("a pending restore already exists; resume that attempt")
    record, digest, exported = _checkpoint(checkpoint_path)
    completed = completed_restores(previous)
    if previous.get("state") == "complete":
        # The record is kept from the first completion onward, including one made before it was.
        completed = _completing(previous)
    if any(item["checkpoint_sha256"] == digest for item in completed):
        # The restored database has served since: reopening it would replay over its writes.
        raise RestoreRefused(
            "the restore this checkpoint names is already complete; a completed restore is "
            "never reopened"
        )
    state: dict[str, Any] = {}
    if exported:
        if declaration_path is None or max_export_lag is None:
            raise RestoreRefused(
                "an export is replayed only in a declared crash recovery; give its declaration "
                "and the installation's export lag bound"
            )
        state["recovery"] = _declared(record, digest, _read(declaration_path), max_export_lag)
    elif declaration_path is not None or max_export_lag is not None:
        raise RestoreRefused(
            "a sealed checkpoint is a planned restore and takes no declaration or lag bound"
        )
    restore_id = uuid.uuid4()
    _write(
        marker_path,
        {
            "profile": "exulanica.restore-state/v1",
            "state": "pending",
            "restore_id": str(restore_id),
            "checkpoint_id": record["checkpoint_id"],
            "checkpoint_sha256": digest,
            "completed": completed,
            **state,
        },
    )
    return restore_id


def completed_restores(marker: dict[str, Any]) -> list[dict[str, str]]:
    """Every restore this installation completed, as the marker carries them: each completed
    checkpoint or export digest with its restore id. Every marker write carries the list forward, so
    a completed restore is remembered after the marker moves on to a later attempt; it is lost only
    with the marker itself."""
    found = marker.get("completed", [])
    if not isinstance(found, list) or not all(
        isinstance(item, dict)
        and isinstance(item.get("checkpoint_sha256"), str)
        and isinstance(item.get("restore_id"), str)
        for item in found
    ):
        raise RestoreRefused("the restore marker's record of completed restores is unreadable")
    return found


def _completing(marker: dict[str, Any]) -> list[dict[str, str]]:
    """The completed list once ``marker``'s own attempt completes."""
    digest, restore_id = marker.get("checkpoint_sha256"), marker.get("restore_id")
    if not isinstance(digest, str) or not isinstance(restore_id, str):
        raise RestoreRefused("the restore marker names no completed attempt it can record")
    done = {"checkpoint_sha256": digest, "restore_id": restore_id}
    found = completed_restores(marker)
    return found if done in found else [*found, done]


def _marker(path: Path) -> dict[str, Any]:
    marker = _read(path)
    if marker.get("profile") != "exulanica.restore-state/v1":
        raise RestoreRefused("unrecognised restore marker")
    completed_restores(marker)
    if marker.get("state") == "none":
        return marker
    for key in ("restore_id", "checkpoint_id"):
        value = marker.get(key)
        try:
            if not isinstance(value, str):
                raise ValueError(key)
            uuid.UUID(value)
        except ValueError as exc:
            raise RestoreRefused("restore marker has no valid attempt identity") from exc
    return marker


def abandon_declared_restore(marker_path: Path, export_sha256: str) -> dict[str, Any]:
    """Move a marker pending for a declared recovery of this export to ``abandoned``. The caller
    has checked that nothing this attempt loaded remains.

    ``abandoned`` still refuses serving, as pending did, so a backup loaded by hand afterwards is
    not served without replay; it accepts a new :func:`prepare_restore`, which abandoning is for.
    """
    marker = _marker(marker_path)
    if (
        marker.get("state") != "pending"
        or marker.get("checkpoint_sha256") != export_sha256
        or "recovery" not in marker
    ):
        raise RestoreRefused("the marker is not pending for a declared recovery of this export")
    abandoned = {
        "restore_id": marker["restore_id"],
        "checkpoint_sha256": export_sha256,
        "at": dt.datetime.now(dt.UTC).isoformat(),
    }
    _write(marker_path, {**marker, "state": "abandoned", "abandoned": abandoned})
    return abandoned


def mark_returning(marker_path: Path, checkpoint_sha256: str, database: str) -> None:
    """Record, in a marker pending for this checkpoint, the database a return to the source is
    replaying into, before that replay begins: a later run resumes a replay only in that database,
    never in the restore's own copy, which carries the same attempt and checkpoint. ``database``
    names it by its server and oid, which a rename keeps."""
    marker = _marker(marker_path)
    if marker.get("state") != "pending" or marker.get("checkpoint_sha256") != checkpoint_sha256:
        raise RestoreRefused("the marker is not pending for this checkpoint: no return to record")
    _write(marker_path, {**marker, "returning": database})


def initialise_restore_state(path: Path) -> bool:
    """Write the marker an installation starts with, state ``none``, unless one exists.

    ``none`` says no restore has been declared since the installation was set up. An installation
    whose profile names a marker path runs this once, before its API first starts, so that a
    missing marker afterwards means lost custody and refuses, as it always has. Returns whether it
    wrote one.
    """
    if path.exists():
        _marker(path)
        return False
    _write(path, {"profile": "exulanica.restore-state/v1", "state": "none"})
    return True


def adopt_restore_state(database: Database, path: Path) -> dict[str, Any]:
    """Write the first marker for an installed database that has never had one, from its own
    restore state, or refuse with nothing written.

    A database installed without a profile has no marker, and on an installed database a missing
    marker is lost custody (:func:`initialise_restore_state`). Adopting reads what the database
    itself records. No ``restore_control`` row means no restore was ever declared here, and the
    marker is ``none``. A ``complete`` row whose replay receipt matches it means the last restore
    finished, and the marker is ``complete`` for that attempt, with every restore the database
    holds a receipt for in ``completed``, so none of those checkpoints is restored again. Anything
    else is a restore in progress, or a record that does not agree with itself, and is refused.

    What this cannot tell apart is a database that has served all along from a backup loaded into
    it by hand without a replay: both read the same. The operator who adopts states that the
    database is the installation's live one. Nor can it rebuild what only a marker held: a declared
    recovery's declaration, ``left_open``, ``returning``, an abandoned attempt, or a completed
    restore whose receipt this database does not hold. A lost marker is restored from custody.
    """
    if path.exists():
        raise RestoreRefused(
            "the restore marker already exists, so there is nothing to adopt; nothing was written"
        )
    with database.unscoped() as connection:
        cursor = connection.cursor(row_factory=dict_row)
        found = cursor.execute(
            "select to_regclass('schema_migrations') is not null as installed, "
            "to_regclass('restore_control') is not null as controlled"
        ).fetchone()
        if found is None or not found["installed"]:
            raise RestoreRefused(
                "the database has no applied schema: a first install runs init without --adopt; "
                "nothing was written"
            )
        if not found["controlled"]:
            raise RestoreRefused(
                "the database's schema predates the restore controls: migrate it, then adopt; "
                "nothing was written"
            )
        control = cursor.execute(
            "select checkpoint_id, checkpoint_sha256, state, restore_id from restore_control"
        ).fetchone()
        if control is None:
            receipts = cursor.execute("select count(*) as n from restore_replay_receipt").fetchone()
            if receipts is not None and receipts["n"]:
                raise RestoreRefused(
                    "the database holds restore receipts but no restore control row, so its "
                    "restore record does not agree with itself; nothing was written"
                )
            marker: dict[str, Any] = {"profile": "exulanica.restore-state/v1", "state": "none"}
        else:
            if control["state"] != "complete":
                raise RestoreRefused(
                    f"the database's restore control is {control['state']}: a checkpoint is sealed "
                    "or a replay is unfinished, so finish that restore before adopting; nothing "
                    "was written"
                )
            receipt = (
                None
                if control["restore_id"] is None
                else cursor.execute(
                    "select checkpoint_id, checkpoint_sha256 from restore_replay_receipt "
                    "where restore_id=%s",
                    (control["restore_id"],),
                ).fetchone()
            )
            if (
                receipt is None
                or receipt["checkpoint_id"] != control["checkpoint_id"]
                or receipt["checkpoint_sha256"] != control["checkpoint_sha256"]
            ):
                raise RestoreRefused(
                    "the database's completed restore has no replay receipt that matches it; "
                    "nothing was written"
                )
            # A receipt is written in the transaction that completes its replay, so every receipt
            # the database holds is a restore that completed here, the current one among them.
            # All of them go into completed, so none of their checkpoints is restored again.
            completed = [
                {
                    "checkpoint_sha256": row["checkpoint_sha256"],
                    "restore_id": str(row["restore_id"]),
                }
                for row in cursor.execute(
                    "select restore_id, checkpoint_sha256 from restore_replay_receipt "
                    "order by completed_at, restore_id"
                ).fetchall()
            ]
            marker = {
                "profile": "exulanica.restore-state/v1",
                "state": "complete",
                "restore_id": str(control["restore_id"]),
                "checkpoint_id": str(control["checkpoint_id"]),
                "checkpoint_sha256": control["checkpoint_sha256"],
                "completed": completed,
            }
    marker["adopted_at"] = dt.datetime.now(dt.UTC).isoformat()
    _write(path, marker)
    verify_restore(database, path)
    return marker


def verify_restore(database: Database, marker_path: Path | None = None) -> None:
    """Called before API workers or serving. Missing, partial or mismatched proof refuses."""
    marker = _marker(marker_path) if marker_path is not None else None
    if marker is not None and marker.get("state") not in ("complete", "none"):
        raise RestoreRefused(
            "mandatory tombstone replay is pending, or a recovery was abandoned before it "
            "replayed; refusing traffic"
        )
    if marker is not None and marker.get("state") == "none":
        marker = None
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
    store: ContentAddressedStore | None,
    checkpoint_path: Path,
    marker_path: Path,
    *,
    writers: Mapping[str, Writer],
    materials: WorkspaceStores | None = None,
    stores: ContentStores | None = None,
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

    ``stores``, an installation's purging stores, replaces ``store`` and ``materials``: the purge
    reaches every namespace through them and each stored target is looked for where its kind's
    namespace keeps it (:func:`exulanica.deletion.queue.stored_target_store`).
    """
    if stores is not None:
        store, materials = stores.blobs, stores.materials
    if store is None:
        raise RestoreRefused("replay needs the content stores its purge destroys bytes in")
    record, digest, exported = _checkpoint(checkpoint_path)
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
    if marker.get("state") == "abandoned":
        raise RestoreRefused(
            "the restore this marker names was abandoned; prepare a new restore instead, which "
            "takes the newest export in custody"
        )
    if marker.get("state") == "complete":
        # Replaying again would make a database that has not served since (a set-aside source)
        # serve with every deletion made in the restored one undone.
        raise RestoreRefused(
            "the restore this marker names is already complete; a completed restore is never "
            "replayed again"
        )
    if exported:
        _redeclared(record, digest, marker)
    elif "recovery" in marker:
        raise RestoreRefused("a sealed checkpoint's marker records no declared recovery")
    restore_id = uuid.UUID(marker["restore_id"])
    _write(marker_path, {**marker, "state": "pending"})
    applied: list[tuple[uuid.UUID, uuid.UUID, dict[str, Any]]] = []
    carries = _carries(record)
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
    worker = (
        PurgeWorker.over(purge_database, stores, workspaces)
        if stores is not None
        else PurgeWorker(purge_database, store, workspaces, material_stores=materials)
    )
    # A skipped job is not terminal: it is tried again after queue.RETRY_AFTER, so it is not claimed
    # again here and the loop ends once a pass handles nothing. Whether each skip is one normal
    # operation reaches (bytes a live record still holds) is judged per tombstone below.
    while True:
        outcome = worker.drain()
        if outcome.blocked or outcome.failed or outcome.exhausted:
            raise RestoreRefused(f"tombstone replay purge incomplete: {outcome}")
        if outcome.handled == 0:
            break
    left_open: dict[str, list[str]] = {}
    with database.unscoped() as connection:
        _admin(connection)
        for workspace_id, tombstone_id, item in applied:
            set_workspace(connection, workspace_id)
            complete = connection.execute(
                "select tombstone_purge_is_complete(%s) as complete", (tombstone_id,)
            ).fetchone()
            held: list[str] = []
            if not complete or not complete["complete"]:
                # Open only on bytes a live record in this database still holds, as a tombstone
                # stays open in normal operation; those jobs stay queued for the ordinary purger.
                found = _held_open(connection, workspace_id, tombstone_id)
                if found is None:
                    raise RestoreRefused("a replayed tombstone is not completely purged")
                held = found
                # Named by the tombstone the checkpoint carries: the one the operator knows.
                left_open[str(item["tombstone"]["tombstone_id"])] = held
            _refuse_entries_left(connection, workspace_id, item)
            targets = connection.execute(
                "select target_kind, target_ref from purge_job where tombstone_id=%s "
                "and target_kind=any(%s)",
                (tombstone_id, list(STORED_KINDS)),
            ).fetchall()
            for row in targets:
                blob_id, kind = BlobId.from_hex(row["target_ref"]), row["target_kind"]
                if f"{kind}:{blob_id.hex}" in held:
                    continue  # rightly kept: a live record holds these bytes
                if stores is not None:
                    present = stored_target_store(stores, kind, workspace_id).exists(blob_id)
                elif kind == "material_bake":
                    assert materials is not None  # refused above when a bake was named
                    present = materials.for_workspace(workspace_id).exists(blob_id)
                else:
                    present = store.exists(blob_id)
                if present:
                    raise RestoreRefused("replayed object-store bytes still exist")
        # A declared recovery's receipt carries its window (migration 0129), so the database that
        # serves afterwards says what it may be missing; a planned restore's leaves them null.
        declared = marker["recovery"] if exported else {}
        connection.execute(
            "insert into restore_replay_receipt "
            "(restore_id,checkpoint_id,checkpoint_sha256,tombstone_count,recovery_mode,"
            "covered_through,incident_at,loss_window_microseconds,max_export_lag_microseconds) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict(restore_id) do nothing",
            (
                restore_id,
                record["checkpoint_id"],
                digest,
                len(record["tombstones"]),
                declared.get("mode"),
                declared.get("covered_through"),
                declared.get("incident_at"),
                declared.get("loss_window_microseconds"),
                declared.get("max_export_lag_microseconds"),
            ),
        )
        connection.execute(
            "update restore_control set state='complete',updated_at=now() where restore_id=%s",
            (restore_id,),
        )
    _write(
        marker_path,
        {**marker, "state": "complete", "completed": _completing(marker), "left_open": left_open},
    )
    verify_restore(database, marker_path)
    return restore_id


def complete_committed_replay(
    database: Database, checkpoint_path: Path, marker_path: Path
) -> uuid.UUID:
    """Complete a pending marker whose attempt's replay already committed in ``database``, without
    replaying again.

    The replay commits its receipt and its complete ``restore_control`` row together, after every
    check it makes, so a database holding both for this attempt and checkpoint holds that replay
    whole. It may have served since (a marker put back from an older copy) or not (interrupted
    before the marker write); either way a second replay would only run its purge jobs again,
    mark every derived artifact stale and write each carried withdrawal again. ``left_open`` is
    read from the database as it stands: each of the checkpoint's tombstones still open there,
    with the targets a live record holds or, when anything else keeps it open, the targets not
    yet done, which the ordinary purger owns as it owns any open tombstone.
    """
    record, digest, exported = _checkpoint(checkpoint_path)
    marker = _marker(marker_path)
    if (
        marker.get("state") != "pending"
        or marker.get("checkpoint_id") != record["checkpoint_id"]
        or marker.get("checkpoint_sha256") != digest
    ):
        raise RestoreRefused("the marker is not pending for this checkpoint: nothing to complete")
    if exported:
        _redeclared(record, digest, marker)
    elif "recovery" in marker:
        raise RestoreRefused("a sealed checkpoint's marker records no declared recovery")
    restore_id = uuid.UUID(marker["restore_id"])
    left_open: dict[str, list[str]] = {}
    with database.unscoped() as connection:
        _admin(connection)
        cursor = connection.cursor(row_factory=dict_row)
        control = cursor.execute(
            "select state, checkpoint_sha256, restore_id from restore_control"
        ).fetchone()
        receipt = cursor.execute(
            "select checkpoint_id, checkpoint_sha256 from restore_replay_receipt "
            "where restore_id=%s",
            (restore_id,),
        ).fetchone()
        if (
            control is None
            or control["state"] != "complete"
            or control["checkpoint_sha256"] != digest
            or control["restore_id"] != restore_id
            or receipt is None
            or str(receipt["checkpoint_id"]) != record["checkpoint_id"]
            or receipt["checkpoint_sha256"] != digest
        ):
            raise RestoreRefused(
                "this database holds no replay of this attempt that committed: nothing to complete"
            )
        for item in record["tombstones"]:
            original = item["tombstone"]
            workspace_id = uuid.UUID(original["workspace_id"])
            replay_id = uuid.uuid5(restore_id, original["tombstone_id"])
            set_workspace(connection, workspace_id)
            complete = cursor.execute(
                "select tombstone_purge_is_complete(%s) as complete", (replay_id,)
            ).fetchone()
            if complete and complete["complete"]:
                continue
            held = _held_open(connection, workspace_id, replay_id)
            if held is None:
                held = [
                    f"{row['target_kind']}:{row['target_ref']}"
                    for row in cursor.execute(
                        "select target_kind, target_ref from purge_job where tombstone_id=%s "
                        "and state <> 'done' order by target_kind, target_ref",
                        (replay_id,),
                    ).fetchall()
                ]
            left_open[str(original["tombstone_id"])] = held
    _write(
        marker_path,
        {**marker, "state": "complete", "completed": _completing(marker), "left_open": left_open},
    )
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
