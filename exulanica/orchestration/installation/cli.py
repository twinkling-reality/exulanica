"""``exulanica-installation``: the one procedure an installation, and its acceptance, runs.

    exulanica-installation init [--adopt]
    exulanica-installation facts
    exulanica-installation check
    exulanica-installation backup
    exulanica-installation verify --backup-set DIR
    exulanica-installation maintenance (--once | --loop [--pass-seconds N])
    exulanica-installation restore declared --backup-set DIR --export FILE \\
        --declaration FILE
    exulanica-installation restore planned --backup-set DIR --checkpoint FILE [--set-aside]
    exulanica-installation restore return-to-source --checkpoint FILE [--set-aside]
    exulanica-installation restore discard-set-aside --checkpoint FILE
    exulanica-installation restore abandon --export FILE

Every location is a setting, never a guess (deployment.md section 9 lists them):
``EXULANICA_INSTALLATION_PROFILE`` names the profile whose recovery bounds apply;
``EXULANICA_BACKUP_DATABASE_URL`` is the read-only backup role; ``EXULANICA_CUSTODY_DIRECTORY``,
``EXULANICA_BACKUP_DIRECTORY`` and ``EXULANICA_BACKUP_STORE_DIRECTORY`` are where exports, backup
sets and the stored-byte copy go, each outside the data directory; ``EXULANICA_PURGE_DATABASE_URL``
is the purge role. A restore reads the target from ``EXULANICA_RESTORE_MAINTENANCE_URL`` (a
superuser on the empty target server), ``EXULANICA_RESTORE_DATABASE_URL`` (the database it
creates, as its owner), ``EXULANICA_PURGE_DATABASE_URL`` and ``EXULANICA_DATA_DIR``, and the
source from ``EXULANICA_SOURCE_DATABASE_URL`` (which a planned restore seals and a return without
``--set-aside`` replays into). Each command exits 0 on success, 1 on a named refusal, 2 on a
missing setting.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from exulanica.api.installation import (
    InstallationRefused,
    RecoveryPolicy,
    installation_facts,
    load_installation,
)
from exulanica.db.cli import provision_database
from exulanica.db.session import Database
from exulanica.deletion.restore import (
    RestoreRefused,
    adopt_restore_state,
    initialise_restore_state,
)
from exulanica.env import env_get, resolve_data_dir
from exulanica.orchestration.installation.backup_set import (
    BackupSetRefused,
    take_backup_set,
    verify_backup_set,
)
from exulanica.orchestration.installation.custody import erased_targets
from exulanica.orchestration.installation.maintenance import Maintenance, MaintenanceStores
from exulanica.orchestration.installation.recovery import (
    Target,
    abandon_declared,
    discard_set_aside,
    recover_declared,
    restore_planned,
    return_to_source,
)
from exulanica.store.configured import local_content_stores, purging_content_stores

__all__ = ["main"]


class _Missing(Exception):
    pass


def _setting(name: str) -> str:
    value = env_get(name)
    if not value:
        raise _Missing(f"EXULANICA_{name} is not set")
    return value


def _policy() -> RecoveryPolicy:
    installation = load_installation(os.environ)
    if installation.profile is None:
        raise _Missing("EXULANICA_INSTALLATION_PROFILE is not set")
    return installation.profile.recovery


def _stores(backup_root: Path) -> MaintenanceStores:
    """The installation's purging stores, local or object, and the local backup copy under
    ``backup_root``, laid out by the same namespace names."""
    return MaintenanceStores(
        live=purging_content_stores(), backup=local_content_stores(backup_root)
    )


def _identity() -> dict[str, Any]:
    installation = load_installation(os.environ)
    return {
        "profile": None if installation.profile is None else installation.profile.id,
        "profile_sha256": None if installation.profile is None else installation.profile.sha256,
        "code_revision": installation.code_revision,
        "images": dict(installation.images),
    }


def _maintenance() -> Maintenance:
    data_dir = resolve_data_dir()
    backup_root = Path(_setting("BACKUP_STORE_DIRECTORY"))
    return Maintenance(
        backup_url=_setting("BACKUP_DATABASE_URL"),
        purge_url=env_get("PURGE_DATABASE_URL"),
        custody=Path(_setting("CUSTODY_DIRECTORY")),
        backup_directory=Path(_setting("BACKUP_DIRECTORY")),
        status_path=Path(_setting("MAINTENANCE_STATUS_PATH")),
        stores=_stores(backup_root),
        policy=_policy(),
        identity=_identity(),
        restore_state_path=_restore_state_path(),
        backup_domains=(data_dir, backup_root),
    )


def _restore_state_path() -> Path:
    path = load_installation(os.environ).restore_state_path
    if path is None:
        raise _Missing("EXULANICA_INSTALLATION_PROFILE is not set, so no restore marker is named")
    return path


def _print(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, indent=1, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="exulanica-installation", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser(
        "init", help="write the profile's restore marker, state none, if absent"
    )
    init.add_argument(
        "--adopt",
        action="store_true",
        help="an installed database without a marker: write the marker its own restore state "
        "supports, or refuse",
    )
    commands.add_parser("facts", help="this installation's facts document")
    commands.add_parser("check", help="facts, and exit 1 unless it serves on a current schema")
    commands.add_parser("backup", help="take one verified-in-order backup set")
    verify = commands.add_parser("verify", help="prove a backup set restores")
    verify.add_argument("--backup-set", required=True, type=Path)
    maintenance = commands.add_parser("maintenance", help="the unattended maintenance pass")
    once = maintenance.add_mutually_exclusive_group(required=True)
    once.add_argument("--once", action="store_true")
    once.add_argument("--loop", action="store_true")
    maintenance.add_argument("--pass-seconds", type=float, default=15.0)
    restore = commands.add_parser("restore", help="restore a backup set, or end a planned one")
    restore.add_argument(
        "mode",
        choices=("declared", "planned", "return-to-source", "discard-set-aside", "abandon"),
    )
    restore.add_argument("--backup-set", type=Path, help="declared and planned: the set")
    restore.add_argument(
        "--marker",
        type=Path,
        help="the restore marker; with a profile it must be the profile's, which is the default",
    )
    restore.add_argument("--export", type=Path, help="declared: the newest withdrawal export")
    restore.add_argument("--declaration", type=Path, help="declared: the operator's declaration")
    restore.add_argument(
        "--checkpoint", type=Path, help="planned: a fresh path for the sealed checkpoint"
    )
    restore.add_argument(
        "--set-aside",
        action="store_true",
        help="planned and return-to-source: the source database is set aside on this server",
    )
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except _Missing as missing:
        print(f"exulanica-installation: {missing}", file=sys.stderr)
        return 2
    except (InstallationRefused, RestoreRefused, BackupSetRefused) as refused:
        print(f"exulanica-installation: refused: {refused}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace) -> int:
    if args.command == "init" and args.adopt:
        path = _restore_state_path()
        adopted = adopt_restore_state(Database(_setting("RESTORE_DATABASE_URL")), path)
        _print({"restore_state_path": str(path), "written": True, "state": adopted["state"]})
        return 0
    if args.command == "init":
        path = _restore_state_path()
        if not path.exists():
            # Only a first install starts without a marker: on a database that already has its
            # schema, a missing marker is lost custody, possibly of a pending restore, and writing
            # "none" over it would let a restore that never replayed serve.
            with Database(_setting("RESTORE_DATABASE_URL")).unscoped() as connection:
                row = (
                    connection.cursor(row_factory=dict_row)
                    .execute("select to_regclass('schema_migrations') is not null as installed")
                    .fetchone()
                )
            if row is not None and row["installed"]:
                raise RestoreRefused(
                    "the restore marker is missing on an installed database: restore its newest "
                    "copy from custody (an older copy can name a restore that has since "
                    "completed), or complete the restore it belonged to, or, for a database that "
                    "never had a marker, adopt it with init --adopt; nothing was written"
                )
        written = initialise_restore_state(path)
        _print({"restore_state_path": str(path), "written": written})
        return 0
    if args.command in ("facts", "check"):
        from exulanica.api.services import build_services

        facts = installation_facts(build_services(os.environ))
        _print(facts)
        if args.command == "facts":
            return 0
        states = {entry["component"]: entry["state"] for entry in facts["components"]}
        serving = facts["serving"]["state"] == "open"
        return 0 if serving and states["database"] == states["schema"] == "ready" else 1
    if args.command == "backup":
        maintenance = _maintenance()
        taken = take_backup_set(
            backup_url=maintenance.backup_url,
            directory=maintenance.backup_directory,
            namespaces=maintenance.stores.namespaces(),
            custody=maintenance.custody,
            restore_state_path=maintenance.restore_state_path,
            backup_domains=maintenance.backup_domains,
            identity=maintenance.identity,
        )
        _print({"backup_set": str(taken.directory), "sha256": taken.sha256})
        return 0
    if args.command == "verify":
        backup_root = Path(_setting("BACKUP_STORE_DIRECTORY"))
        stores = _stores(backup_root)
        # The gaps maintenance made, and a declared recovery accepts: no more, no fewer.
        erased = erased_targets(Path(_setting("CUSTODY_DIRECTORY")))
        _print(verify_backup_set(args.backup_set, stores.backup_for, erased=erased))
        return 0
    if args.command == "maintenance":
        runner = _maintenance()
        if args.once:
            status = runner.run_pass()
            _print(status)
            return 1 if status["failures"] else 0
        runner.run(pass_seconds=args.pass_seconds)
        return 0
    target = Target(
        maintenance_url=_setting("RESTORE_MAINTENANCE_URL"),
        database_url=_setting("RESTORE_DATABASE_URL"),
        purge_url=_setting("PURGE_DATABASE_URL"),
        stores=purging_content_stores(),
    )
    marker = _marker(args.marker)
    name = _database_name(Database(target.database_url))
    if args.mode == "abandon":
        if args.export is None:
            raise _Missing("abandon needs --export, the export the pending recovery declared")
        _print({"abandoned": abandon_declared(target=target, export=args.export, marker=marker)})
        return 0
    if args.mode in ("return-to-source", "discard-set-aside"):
        if args.checkpoint is None:
            raise _Missing(f"{args.mode} needs --checkpoint, the planned restore's checkpoint")
        if args.mode == "discard-set-aside":
            _print(
                {
                    "dropped": discard_set_aside(
                        target=target, name=name, checkpoint_path=args.checkpoint, marker=marker
                    )
                }
            )
            return 0
        return_to_source(
            # A source set aside on this server is renamed back here; one on another server is
            # replayed where it is.
            target=target
            if args.set_aside
            else replace(target, database_url=_setting("SOURCE_DATABASE_URL")),
            name=name,
            source_purge=Database(target.purge_url),
            checkpoint_path=args.checkpoint,
            marker=marker,
            set_aside=args.set_aside,
        )
        _print({"returned_to_source": name})
        return 0
    if args.backup_set is None:
        raise _Missing(f"a {args.mode} restore needs --backup-set")
    backup_root = Path(_setting("BACKUP_STORE_DIRECTORY"))
    if args.mode == "planned":
        if args.checkpoint is None:
            raise _Missing("a planned restore needs --checkpoint, a fresh path in custody")
        result = restore_planned(
            source=Database(_setting("SOURCE_DATABASE_URL")),
            checkpoint_path=args.checkpoint,
            backup_set=args.backup_set,
            backup_stores=_stores(backup_root).backup_for,
            marker=marker,
            target=target,
            provision=_provisioned,
            set_aside=args.set_aside,
        )
        _print(result)
        return 0
    if args.export is None or args.declaration is None:
        raise _Missing("a declared recovery needs --export and --declaration")
    result = recover_declared(
        backup_set=args.backup_set,
        backup_stores=_stores(backup_root).backup_for,
        export=args.export,
        custody=Path(_setting("CUSTODY_DIRECTORY")),
        declaration=args.declaration,
        max_export_lag=dt.timedelta(seconds=_policy().max_export_lag_seconds),
        marker=marker,
        target=target,
        provision=_provisioned,
    )
    _print(result)
    return 0


def _marker(given: Path | None) -> Path:
    """The restore marker: the profile's when one is declared, which a given one must equal.

    The API reads the profile's marker at startup, so a restore that wrote another could leave a
    failed restore served.
    """
    declared = load_installation(os.environ).restore_state_path
    if declared is None:
        # A marker only this command knows of protects nothing: the API reads its own.
        raise _Missing(
            "no restore marker is declared: set EXULANICA_INSTALLATION_PROFILE (or "
            "EXULANICA_RESTORE_STATE_PATH) as the API's environment does"
        )
    if given is not None and given.resolve() != declared.resolve():
        raise InstallationRefused(
            "restore_state_path_conflict", "--marker differs from the profile's restore marker"
        )
    return declared


def _database_name(database: Database) -> str:
    """The database a connection string names, read without connecting: on a resumed planned
    restore it has already been set aside under another name."""
    name = conninfo_to_dict(database.url).get("dbname")
    if not name:
        raise _Missing("EXULANICA_RESTORE_DATABASE_URL names no database")
    return str(name)


def _provisioned(database: Database) -> None:
    if provision_database(database, sys.stderr) != 0:
        raise RestoreRefused("the restored database could not be migrated and provisioned")
