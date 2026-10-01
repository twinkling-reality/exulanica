"""Recovering an installation into an empty, isolated target from a backup set, timed.

Two procedures, kept apart as ADR-0028 keeps them:

*   **Declared crash recovery** (:func:`recover_declared`): the source is lost. The marker is
    written before anything is restored, from the newest withdrawal export and the operator's
    declaration; then the set's database is loaded into the empty target, its stored bytes are
    copied back and verified, the schema and roles are brought current, the export is replayed,
    and only a complete replay lets the target serve. The window the declaration states is lost.
*   **Planned restore** (:func:`restore_planned`): the source is stopped but present. It is sealed
    and checkpointed first, so nothing is lost, and the same restore runs from that checkpoint.
    Until the restore completes, :func:`return_to_source` abandons it and lets the source serve
    again; once it completes, the restored database has served and the source would lack its
    deletions, so a set-aside source is only discarded (:func:`discard_set_aside`).

Both check everything that can refuse before they seal a source or write the marker, and both
resume a pending attempt when run again with the same authority.

The caller supplies ``provision``, which brings a restored database to the running release's
schema and reprovisions its roles (``exulanica-db``'s work), because a restored database's grants
must never be trusted as they came back.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import uuid
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from exulanica.db.local.backup import restore_database_at
from exulanica.db.local.files import write_private
from exulanica.db.session import Database
from exulanica.deletion.queue import STORED_KINDS
from exulanica.deletion.restore import (
    RestoreRefused,
    abandon_declared_restore,
    checkpoint,
    completed_restores,
    loss_window,
    prepare_restore,
    replay,
    source_identity,
    verify_restore,
)
from exulanica.evidence.blob import BlobId
from exulanica.orchestration.installation.backup_set import (
    BackupSetRefused,
    check_bindings,
    read_backup_set,
)
from exulanica.orchestration.installation.custody import UNLISTED_PREFIX, require_newest
from exulanica.orchestration.restore import WRITERS
from exulanica.store.base import ContentAddressedStore
from exulanica.store.configured import ContentStores

__all__ = [
    "Target",
    "abandon_declared",
    "discard_set_aside",
    "recover_declared",
    "restore_planned",
    "return_to_source",
]


@dataclass(frozen=True, slots=True)
class Target:
    """An empty, isolated place to recover into."""

    #: A superuser connection, as the backup's owner role, to the empty server's maintenance
    #: database. Loading creates the dump's database there.
    maintenance_url: str
    #: The restored database, as its owner: the replay's administrative connection.
    database_url: str
    #: The restored database as the purge role, which the replay destroys bytes with.
    purge_url: str
    #: The target's purging stores: every namespace a backup set records resolves here by name,
    #: and the replay destroys bytes through them.
    stores: ContentStores

    def store_for(self, name: str) -> ContentAddressedStore | None:
        return self.stores.namespace(name)


BackupStores = Mapping[str, ContentAddressedStore] | Callable[[str], ContentAddressedStore | None]


def _backup_store(stores: BackupStores, name: str) -> ContentAddressedStore | None:
    return stores.get(name) if isinstance(stores, Mapping) else stores(name)


_KEPT: Final = "_before_"


def _kept_name(name: str, restore_id: uuid.UUID) -> str:
    """The set-aside source's name: within PostgreSQL's 63 bytes, so a resume finds it again."""
    suffix = f"{_KEPT}{restore_id.hex[:8]}"
    return name.encode()[: 63 - len(suffix)].decode(errors="ignore") + suffix


def _record_sha256(path: Path) -> str:
    value = json.loads(path.read_bytes()).get("record_sha256")
    if not isinstance(value, str):
        raise RestoreRefused(f"{path.name} is not a digest-bound checkpoint or export")
    return value


def _pending(marker: Path, authority_sha256: str) -> uuid.UUID | None:
    """The attempt a pending marker names for this authority, so the same command resumes it."""
    if not marker.exists():
        return None
    try:
        state = json.loads(marker.read_bytes())
        if not isinstance(state, dict):
            raise ValueError("not an object")
        if state.get("state") == "pending":
            uuid.UUID(state["restore_id"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RestoreRefused(f"the restore marker {marker} is unreadable: {exc}") from exc
    if state.get("state") == "pending" and state.get("checkpoint_sha256") == authority_sha256:
        return uuid.UUID(state["restore_id"])
    if state.get("state") == "pending":
        raise RestoreRefused(
            "the marker is pending for another checkpoint or export; finish or return from that "
            "restore first"
        )
    return None


def _is_the_source(source: Database, target: Target, name: str) -> bool:
    """Whether the target server's ``name`` is the source database itself: the same server and
    the same database, by the identity every export records."""
    with source.unscoped() as connection:
        mine = source_identity(connection)
    with psycopg.connect(_on_target(target, name), autocommit=True) as connection:
        return source_identity(connection) == mine


def _check_set(backup_set: Path, target: Target) -> Any:
    """The set, after its key list, its dump and the target database's name all check out."""
    loaded = read_backup_set(backup_set)
    record = loaded.manifest["record"]
    key_text = (backup_set / "keys.txt").read_text()
    if hashlib.sha256(key_text.encode()).hexdigest() != record["store"]["keys_sha256"]:
        raise BackupSetRefused("backup_set_invalid", "the key list does not match its manifest")
    check_bindings(loaded)
    named = conninfo_to_dict(target.database_url).get("dbname")
    if named != loaded.database.database:
        raise RestoreRefused(
            f"the target connection names {named!r} and the set restores "
            f"{loaded.database.database!r}"
        )
    return loaded


def _on_target(target: Target, database: str) -> str:
    """The target connection, naming ``database`` on the same server instead."""
    parameters = conninfo_to_dict(target.database_url)
    parameters["dbname"] = database
    return make_conninfo("", **parameters)


def _target_state(
    target: Target, name: str, authority_sha256: str, attempt: uuid.UUID | None = None
) -> str:
    """What the target server holds under ``name``: absent, or what :func:`_state_at` finds."""
    with psycopg.connect(target.maintenance_url, autocommit=True) as connection:
        if not connection.execute(
            "select 1 from pg_database where datname = %s", (name,)
        ).fetchone():
            return "absent"
    return _state_at(_on_target(target, name), authority_sha256, attempt)


def _state_at(url: str, authority_sha256: str, attempt: uuid.UUID | None = None) -> str:
    """What the database at ``url`` is to this restore, by its own restore_control: sealed_source
    (sealed for this authority), replaying (this authority's replay, loaded; or this attempt's
    replay committed before its marker was), live (a restore completed in it), empty (no table)
    or occupied (anything else)."""
    with psycopg.connect(url, autocommit=True) as connection:
        tables = connection.execute(
            "select count(*) from pg_tables where schemaname not in ('pg_catalog', "
            "'information_schema')"
        ).fetchone()
        if not tables or not tables[0]:
            return "empty"
        control_table = connection.execute("select to_regclass('restore_control')").fetchone()
        if control_table is None or control_table[0] is None:
            return "occupied"
        control = connection.execute(
            "select state, checkpoint_sha256, restore_id from restore_control"
        ).fetchone()
    if control is None:
        return "occupied"
    state, digest, restore_id = control
    if state == "complete":
        return "replaying" if attempt is not None and restore_id == attempt else "live"
    if digest == authority_sha256:
        if state == "sealed":
            return "sealed_source"
        if state == "replaying":
            return "replaying"
    return "occupied"


def _refuse_target(state: str, name: str, *, attempt_pending: bool) -> None:
    if state == "replaying":
        raise RestoreRefused(
            f"{name} on the target server is replaying a restore that no pending marker names: "
            "do not drop it; find the marker of the attempt that loaded it"
        )
    if state == "live":
        raise RestoreRefused(
            f"{name} on the target server is a live database, in which a restore completed: do "
            "not drop it; restore into an empty server, or set the source aside"
        )
    if state == "sealed_source":
        raise RestoreRefused(
            f"{name} on the target server is the source this restore sealed, the only copy of "
            "everything written since the backup: do not drop it; rerun with --set-aside, or "
            "restore into another server"
        )
    if state == "empty":
        raise RestoreRefused(
            f"the target server holds an empty database {name} (no table), as a new PostgreSQL "
            "image creates one: drop it and rerun"
        )
    if state == "occupied":
        raise RestoreRefused(
            f"the target server holds {name} with tables"
            + (
                " and this attempt is pending, which was written only after the target held no "
                f"{name}: if this attempt created it, it is a partial copy (the load failed "
                "before replay): drop it and rerun; if it is a live database, do not drop it, and "
                "abandon or return from the attempt instead"
                if attempt_pending
                else ": it may be a live database or a sealed source; do not drop it; restore into "
                "an empty server, or set the source aside"
            )
        )
    raise RestoreRefused(f"the target server holds {name} in a state this restore cannot use")


def restore_bytes(
    backup_set: Path, backup_stores: BackupStores, target: Target, *, erased: Collection[str]
) -> tuple[int, int]:
    """Copy every object the set lists from its backup copy into the target's store of the same
    name, each re-derived from its bytes; return how many were copied and how many withheld.

    An object absent from the backup copy is withheld only when its digest is in ``erased``;
    any other absence refuses.
    """
    copied = withheld = 0
    for line in (backup_set / "keys.txt").read_text().splitlines():
        name, _, hexdigest = line.rpartition("/")
        source, destination = _backup_store(backup_stores, name), target.store_for(name)
        if source is None or destination is None:
            raise BackupSetRefused("backup_store_missing", f"no store for {name}")
        blob_id = BlobId.from_hex(hexdigest)
        if destination.exists(blob_id):
            continue
        if not source.exists(blob_id):
            if hexdigest not in erased:
                raise BackupSetRefused(
                    "backup_object_missing",
                    f"{name}/{hexdigest} is listed by the set, absent from the backup copy, and "
                    "named by no purge the replay carries",
                )
            withheld += 1
            continue
        with source.open(blob_id) as stream:
            if destination.put_stream(stream).blob_id != blob_id:
                raise BackupSetRefused("backup_object_corrupt", f"{name}/{hexdigest}")
        copied += 1
    return copied, withheld


def _load(
    loaded: Any,
    backup_set: Path,
    backup_stores: BackupStores,
    target: Target,
    provision: Callable[[Database], None],
    *,
    authority: Path,
) -> dict[str, Any]:
    """The set's rows and bytes into the absent target database, each object re-derived.

    An object the backup copy no longer holds is accepted only when ``authority`` (the checkpoint
    or export about to be replayed) names it as a stored purge target: a completed purge erased it
    from the backup copy too, and the replay would destroy it again. Any other missing object
    refuses the restore.

    Roles the target server already has are kept: they belong to the whole server, a set-aside
    source or an interrupted attempt leaves them, and ``provision`` reprovisions every one.
    """
    record = json.loads(authority.read_bytes())["record"]
    erased = {
        target["target_ref"]
        for item in record["tombstones"]
        for target in item["targets"]
        if target["target_kind"] in STORED_KINDS
    }
    restore_database_at(
        target.maintenance_url,
        target.database_url,
        loaded.database,
        keep_existing_roles=True,
    )
    copied, withheld = restore_bytes(backup_set, backup_stores, target, erased=erased)
    provision(Database(target.database_url))
    return {
        "objects_copied": copied,
        "erased_objects": withheld,
        "rows": loaded.manifest["record"]["database"]["rows"],
    }


def unlisted_objects(backup_set: Path, target: Target) -> list[str]:
    """Every object the target's stores hold that the set does not list: bytes written after the
    backup, which the restored database cannot reference and no tombstone will ever name."""
    listed = set((backup_set / "keys.txt").read_text().splitlines())
    return [
        key
        for name, store in target.stores.namespaces()
        for blob_id in store.iter_blob_ids()
        if (key := f"{name}/{blob_id.hex}") not in listed
    ]


def _report_unlisted(
    backup_set: Path, target: Target, marker: Path, restore_id: uuid.UUID
) -> dict[str, Any]:
    """Count the objects the restored database does not reference and list their keys beside the
    marker for the operator, who alone may remove them."""
    try:
        found = unlisted_objects(backup_set, target)
    except Exception as failure:
        # The restore is complete; a failed listing must not make anyone rerun it. Maintenance
        # finds nothing to report until the listing is made, and the result says why.
        return {
            "objects_not_in_backup": None,
            "objects_not_in_backup_error": type(failure).__name__,
        }
    if not found:
        return {"objects_not_in_backup": 0}
    listing = marker.parent / f"{UNLISTED_PREFIX}{restore_id}.txt"
    write_private(listing, "".join(f"{key}\n" for key in found))
    return {"objects_not_in_backup": len(found), "objects_not_in_backup_list": str(listing)}


def _finish(
    target: Target, authority: Path, marker: Path, state: str, load: Callable[[], dict[str, Any]]
) -> dict[str, Any]:
    """Load unless this attempt already loaded and began replaying, then replay and verify."""
    loaded = load() if state == "absent" else {"objects_copied": 0, "erased_objects": 0}
    replay(
        Database(target.database_url),
        Database(target.purge_url),
        None,
        authority,
        marker,
        writers=WRITERS,
        stores=target.stores,
    )
    verify_restore(Database(target.database_url), marker)
    return loaded


def recover_declared(
    *,
    backup_set: Path,
    backup_stores: BackupStores,
    export: Path,
    custody: Path,
    declaration: Path,
    max_export_lag: dt.timedelta,
    marker: Path,
    target: Target,
    provision: Callable[[Database], None],
) -> dict[str, Any]:
    """Recover a lost source into ``target`` under a declaration, or refuse, and say how long.

    Everything is checked before the marker is written: the set's digests and database name, that
    the export is the newest valid export in ``custody`` and no older than the one the
    set carries, and that the target is free. The same command resumes a pending attempt for this
    export: loading again only when nothing was loaded, replaying when the load completed.
    """
    started = time.monotonic()
    loaded = _check_set(backup_set, target)
    digest = require_newest(export, custody)
    covered = json.loads(export.read_bytes()).get("record", {}).get("covered_through")
    carried = loaded.manifest["record"]["withdrawal_export"]["covered_through"]
    if not isinstance(covered, str) or dt.datetime.fromisoformat(
        covered
    ) < dt.datetime.fromisoformat(carried):
        raise RestoreRefused(
            "the declared export is older than the one the backup set carries; use the newest"
        )
    attempt = _pending(marker, digest)
    state = _target_state(target, loaded.database.database, digest, attempt)
    if state not in ("absent", "replaying") or (state == "replaying" and attempt is None):
        _refuse_target(state, loaded.database.database, attempt_pending=attempt is not None)
    restore_id = attempt or prepare_restore(
        export, marker, declaration_path=declaration, max_export_lag=max_export_lag
    )
    result = _finish(
        target,
        export,
        marker,
        state,
        lambda: _load(loaded, backup_set, backup_stores, target, provision, authority=export),
    )
    result |= _report_unlisted(backup_set, target, marker, restore_id)
    return {
        "restore_id": str(restore_id),
        "mode": "declared",
        "resumed": attempt is not None,
        "loss_window": loss_window(marker),
        "recovery_seconds": round(time.monotonic() - started, 3),
        **result,
    }


def restore_planned(
    *,
    source: Database,
    checkpoint_path: Path,
    backup_set: Path,
    backup_stores: BackupStores,
    marker: Path,
    target: Target,
    provision: Callable[[Database], None],
    set_aside: bool = False,
) -> dict[str, Any]:
    """Seal the stopped source, then restore the set into ``target`` from that checkpoint.

    Every writer of the source must already be stopped. Nothing is lost: the checkpoint is taken
    after the backup, and replay refuses one that is older. Everything that can refuse does so
    before the source is sealed.

    ``set_aside`` is for a source on the target's own server, as on a single host: after the seal
    it is renamed, never dropped, so the restore can create its name afresh and the sealed source
    stays as the fallback until the restore completes (:func:`return_to_source` before then,
    :func:`discard_set_aside` after). The same command resumes a pending attempt, including one
    interrupted between the seal and the marker.
    """
    started = time.monotonic()
    loaded = _check_set(backup_set, target)
    name = loaded.database.database
    if checkpoint_path.exists():
        digest = _record_sha256(checkpoint_path)
        attempt = _pending(marker, digest)
        if attempt is None:
            # Sealed, then interrupted before the marker: the seal is this checkpoint's.
            with source.unscoped() as connection:
                control = (
                    connection.cursor(row_factory=dict_row)
                    .execute("select state, checkpoint_sha256 from restore_control")
                    .fetchone()
                )
            if (
                control is not None
                and control["state"] == "complete"
                and (control["checkpoint_sha256"] == digest)
            ):
                raise RestoreRefused(
                    "the restore this checkpoint names is already complete; a completed restore "
                    "is never reopened"
                )
            if (
                control is None
                or control["state"] != "sealed"
                or control["checkpoint_sha256"] != digest
            ):
                raise RestoreRefused(
                    "checkpoint paths are immutable, and this one is not the source's seal; a "
                    "fresh path starts a new restore, which seals the source and rolls it back "
                    "to the named set"
                )
            # The target is classified before the marker is written, as on a fresh path.
            held = _target_state(target, name, digest)
            on_one_host = set_aside and held == "sealed_source"
            if held != "absent" and not (on_one_host and _is_the_source(source, target, name)):
                _refuse_target(held, name, attempt_pending=False)
            attempt = prepare_restore(checkpoint_path, marker)
            resumed = False
        else:
            resumed = True
    else:
        if marker.exists() and json.loads(marker.read_bytes()).get("state") == "pending":
            raise RestoreRefused("a pending restore already exists; resume or return from it first")
        state = _target_state(target, name, "")
        if set_aside and state == "absent":
            raise RestoreRefused(f"--set-aside, but the target server holds no {name} to set aside")
        if not set_aside and state != "absent":
            raise RestoreRefused(
                f"the target server holds {name}; on one host that is the source: rerun with "
                "--set-aside, or restore into an empty server"
            )
        if set_aside and not _is_the_source(source, target, name):
            # Only the source itself is ever set aside, and later discarded.
            raise RestoreRefused(
                f"{name} on the target server is not the source database: nothing is sealed or "
                "set aside; restore into an empty server instead"
            )
        checkpoint(source, checkpoint_path)
        digest = _record_sha256(checkpoint_path)
        attempt = prepare_restore(checkpoint_path, marker)
        resumed = False
    kept = _kept_name(name, attempt) if set_aside else None
    if kept is not None:
        with psycopg.connect(target.maintenance_url, autocommit=True) as connection:
            names = {
                row[0] for row in connection.execute("select datname from pg_database").fetchall()
            }
            if kept not in names:
                if _target_state(target, name, digest) != "sealed_source":
                    raise RestoreRefused(
                        f"{name} on the target server is not the source this restore sealed: "
                        "nothing is set aside; restore into an empty server instead"
                    )
                connection.execute(
                    sql.SQL("alter database {} rename to {}").format(
                        sql.Identifier(name), sql.Identifier(kept)
                    )
                )
    state = _target_state(target, name, digest, attempt)
    if state not in ("absent", "replaying"):
        _refuse_target(state, name, attempt_pending=True)
    result = _finish(
        target,
        checkpoint_path,
        marker,
        state,
        lambda: _load(
            loaded, backup_set, backup_stores, target, provision, authority=checkpoint_path
        ),
    )
    result |= _report_unlisted(backup_set, target, marker, attempt)
    return {
        "restore_id": str(attempt),
        "mode": "planned",
        "resumed": resumed,
        "source_kept_as": kept,
        "recovery_seconds": round(time.monotonic() - started, 3),
        **result,
    }


def return_to_source(
    *,
    target: Target,
    name: str,
    source_purge: Database,
    checkpoint_path: Path,
    marker: Path,
    set_aside: bool,
) -> None:
    """Abandon an unfinished planned restore and let the sealed source serve again.

    Allowed only while the marker is pending for this checkpoint: once the restored database has
    served, the source lacks every deletion made there, and no path may serve it. A set-aside
    source is renamed back first; a partial restore under its name is refused by name. The
    source's own seal is completed by replaying its checkpoint into it under the pending attempt,
    which finds every tombstone already present and writes only the receipt.
    """
    digest = _record_sha256(checkpoint_path)
    if _pending(marker, digest) is None:
        raise RestoreRefused(
            "the marker is not pending for this checkpoint: the restore completed and the "
            "restored database has served, so the source would bring back deletions made since; "
            "discard it instead"
        )
    if not set_aside and _state_at(target.database_url, digest) != "sealed_source":
        # Only the source this restore sealed is replayed into: a partial copy loaded under the
        # source's name after it was set aside would otherwise be completed and served.
        raise RestoreRefused(
            "the database the source connection names is not the source this restore sealed; if "
            "the source was set aside, run return-to-source --set-aside"
        )
    if set_aside:
        state = _target_state(target, name, digest)
        if state == "sealed_source":
            raise RestoreRefused(
                f"{name} on the target server is still the sealed source: it was never set "
                "aside; run return-to-source without --set-aside"
            )
        if state != "absent":
            _refuse_target(state, name, attempt_pending=True)
        kept = _kept_name(name, uuid.UUID(json.loads(marker.read_bytes())["restore_id"]))
        if _target_state(target, kept, digest) != "sealed_source":
            raise RestoreRefused(
                f"{kept} on the target server is not the source this restore sealed; nothing is "
                "renamed"
            )
        with psycopg.connect(target.maintenance_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("alter database {} rename to {}").format(
                    sql.Identifier(kept), sql.Identifier(name)
                )
            )
    source = Database(target.database_url)
    replay(
        source, source_purge, None, checkpoint_path, marker, writers=WRITERS, stores=target.stores
    )
    verify_restore(source, marker)


def abandon_declared(*, target: Target, export: Path, marker: Path) -> dict[str, Any]:
    """Abandon a pending declared recovery, so a newer export in custody can be declared instead.

    The source is lost, so nothing serves either way. Allowed only while the marker is pending for
    this export and the target holds no database of that name: whatever this attempt loaded is
    dropped by the operator first. The marker returns to ``none`` and records what was abandoned.
    """
    digest = _record_sha256(export)
    if _pending(marker, digest) is None:
        raise RestoreRefused("the marker is not pending for this export: nothing to abandon")
    name = str(conninfo_to_dict(target.database_url).get("dbname") or "")
    if _target_state(target, name, digest) != "absent":
        raise RestoreRefused(
            f"the target server still holds {name}, loaded by this attempt from the backup: "
            "drop it only if it is that copy, then abandon"
        )
    return abandon_declared_restore(marker, digest)


def discard_set_aside(*, target: Target, name: str, checkpoint_path: Path, marker: Path) -> str:
    """Drop the set-aside source once the restore that set it aside has completed.

    A set-aside source lies outside every deletion path, so its life ends when the restore is
    accepted; maintenance reports one until then (``set_aside_database_present``).
    """
    digest = _record_sha256(checkpoint_path)
    # The marker's record of completed restores, so a set-aside stays discardable after a later
    # restore or recovery has moved the marker on.
    done = [
        item
        for item in completed_restores(json.loads(marker.read_bytes()))
        if item["checkpoint_sha256"] == digest
    ]
    if not done:
        raise RestoreRefused("the restore that set the source aside has not completed")
    kept = _kept_name(name, uuid.UUID(done[-1]["restore_id"]))
    held = _target_state(target, kept, digest)
    if held == "absent":
        raise RestoreRefused(f"no {kept} on the target server: nothing to discard")
    if held != "sealed_source":
        # Only the database this restore sealed and set aside is ever dropped.
        raise RestoreRefused(
            f"{kept} on the target server is not the source this restore sealed; it is not dropped"
        )
    with psycopg.connect(target.maintenance_url, autocommit=True) as connection:
        connection.execute(sql.SQL("drop database {}").format(sql.Identifier(kept)))
    return kept
